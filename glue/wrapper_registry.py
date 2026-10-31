"""Lazy multi-source tool catalog; upstream execution remains in Snakemake."""

import json
import keyword
import re
import string
import subprocess
import threading
from collections import defaultdict
from dataclasses import asdict, replace
from pathlib import Path

import yaml

from glue.builtins import builtin_specs
from glue.catalog_cache import cached_entries
from glue.errors import InvalidToolDefinitionError, ToolNotFoundError, ToolNotWrappedError
from glue.formats import infer_formats
from glue.installed_tools import InstalledToolsAdapter
from glue.models import ExecSpec, IndexEntry, ParamSpec, PortSpec, SearchPage, ToolSpec
from glue.nf_converter import convert_script
from glue.session_store import atomic_json

NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PACKAGE = re.compile(r"^[a-z0-9][a-z0-9_.+-]{0,127}$")
COMMAND = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}$")


def identifier(name):
    if not NAME.fullmatch(name) or keyword.iskeyword(name):
        raise InvalidToolDefinitionError(f"无效的端口或参数名称：{name}")
    return name


def index_entry(spec):
    return IndexEntry(
        spec.tool_id,
        spec.name,
        spec.category,
        spec.source,
        spec.keywords,
        tuple(sorted({f for p in spec.inputs for f in p.formats})),
        tuple(sorted({f for p in spec.outputs for f in p.formats})),
        spec.description[:300],
        spec.reviewed,
    )


def read_yaml(path):
    value = yaml.safe_load(Path(path).read_text()) or {}
    if not isinstance(value, dict):
        raise InvalidToolDefinitionError(f"元数据必须是字典：{path}")
    return value


def metadata_ports(value):
    """Flatten old/new nf-core tuples and wrapper free-text fields."""
    ports = {}

    def visit(obj):
        if isinstance(obj, list):
            for item in obj:
                visit(item)
        elif isinstance(obj, dict):
            for name, detail in obj.items():
                if isinstance(detail, dict) and (
                    detail.get("type") == "file" or "pattern" in detail
                ):
                    identifier(str(name))
                    pattern = str(detail.get("pattern", ""))
                    ports[name] = PortSpec(
                        name,
                        infer_formats(pattern + " " + str(detail.get("description", ""))),
                        bool(detail.get("multiple", False)),
                        bool(detail.get("optional", False)),
                        pattern,
                        str(detail.get("description", "")),
                    )
                elif isinstance(detail, (dict, list)):
                    visit(detail)
                elif isinstance(detail, str) and name != "meta":
                    identifier(str(name))
                    ports[name] = PortSpec(name, infer_formats(detail), description=detail)
        elif isinstance(obj, str):
            name = f"file_{len(ports) + 1}"
            ports[name] = PortSpec(name, infer_formats(obj), description=obj)

    visit(value)
    return tuple(ports.values())


class SnakemakeWrapperAdapter:
    source = "snakemake-wrappers"

    def __init__(self, root: Path, version="v5.0.0"):
        self.root, self.version = Path(root), version
        self.builtins = builtin_specs(version)

    def iter_index(self):
        yield from (index_entry(spec) for spec in self.builtins.values())
        for path in sorted((self.root / "bio").rglob("meta.yaml")):
            tool_id = "smk:" + path.parent.relative_to(self.root).as_posix()
            if tool_id not in self.builtins and any(
                (path.parent / f"wrapper.{ext}").exists() for ext in ("py", "R")
            ):
                try:
                    yield index_entry(self.load_spec(tool_id))
                except (InvalidToolDefinitionError, yaml.YAMLError):
                    continue

    def load_spec(self, tool_id):
        if tool_id in self.builtins:
            return self.builtins[tool_id]
        relative = tool_id.removeprefix("smk:")
        directory = (self.root / relative).resolve()
        if not tool_id.startswith("smk:bio/") or not directory.is_relative_to(self.root.resolve()):
            raise ToolNotFoundError(tool_id)
        meta = directory / "meta.yaml"
        if not meta.exists():
            raise ToolNotFoundError(tool_id)
        data = read_yaml(meta)
        # Free-text upstream metadata cannot guarantee executable port names.
        return ToolSpec(
            tool_id,
            data.get("name", relative),
            "Other",
            self.source,
            str(data.get("description", "")),
            tuple(data.get("keywords", [])),
            metadata_ports(data.get("input", [])),
            metadata_ports(data.get("output", [])),
            (ParamSpec("extra", ""),),
            ExecSpec("wrapper", wrapper=f"{self.version}/{relative}"),
            reviewed=False,
        )


class NfCoreModuleAdapter:
    source = "nf-core"

    def __init__(self, root: Path):
        self.root = Path(root)

    def iter_index(self):
        base = self.root / "modules/nf-core"
        for path in sorted(base.rglob("meta.yml")):
            try:
                yield index_entry(self.load_spec("nf:" + path.parent.relative_to(base).as_posix()))
            except (InvalidToolDefinitionError, yaml.YAMLError):
                continue
        for path in sorted(self.root.rglob("*.cwl")):
            try:
                data = read_yaml(path)
                if data.get("class") == "CommandLineTool":
                    yield index_entry(
                        self.load_spec("cwl:" + path.relative_to(self.root).as_posix())
                    )
            except (InvalidToolDefinitionError, yaml.YAMLError):
                continue

    def load_spec(self, tool_id):
        cwl = tool_id.startswith("cwl:")
        base = self.root if cwl else self.root / "modules/nf-core"
        path = (base / tool_id.split(":", 1)[1]).resolve()
        if not path.is_relative_to(base.resolve()):
            raise ToolNotFoundError(tool_id)
        if cwl:
            data = read_yaml(path)

            def ports(value, output=False):
                if not isinstance(value, dict):
                    raise InvalidToolDefinitionError("CWL inputs/outputs 必须为字典")
                result = []
                for name, item in value.items():
                    identifier(name)
                    item = {"type": item} if isinstance(item, str) else item
                    typ = item.get("type", "")
                    array = isinstance(typ, dict) and typ.get("type") == "array"
                    if typ not in ("File", "File?") and not (array and typ.get("items") == "File"):
                        raise InvalidToolDefinitionError("仅支持静态 File / File[] CWL 端口")
                    glob = item.get("outputBinding", {}).get("glob", "") if output else ""
                    if output and (not glob or any(c in glob for c in "*?[$(")):
                        raise InvalidToolDefinitionError("CWL 输出必须为静态文件名")
                    result.append(
                        PortSpec(name, infer_formats(glob), array, typ == "File?", str(glob))
                    )
                return tuple(result)

            return ToolSpec(
                tool_id,
                str(data.get("label", path.stem)),
                "CWL",
                "cwl",
                "",
                (),
                ports(data.get("inputs", {})),
                ports(data.get("outputs", {}), True),
                (),
                ExecSpec("cwl", cwl=str(path)),
                reviewed=False,
            )
        data = read_yaml(path / "meta.yml")
        source = (path / "main.nf").read_text() if (path / "main.nf").exists() else ""
        inputs = metadata_ports(data.get("input", []))
        outputs = metadata_ports(data.get("output", []))
        shell = convert_script(source, inputs, outputs)
        return ToolSpec(
            tool_id,
            str(data.get("name", path.name)),
            "nf-core",
            self.source,
            str(data.get("description", "")) + "\n需要审核并提供 Snakemake shell 模板。\n" + source,
            tuple(data.get("keywords", [])),
            inputs,
            outputs,
            (ParamSpec("extra", ""),),
            ExecSpec(
                "shell",
                shell=shell,
                conda_env=str(path / "environment.yml")
                if (path / "environment.yml").exists()
                else "",
            ),
            reviewed=False,
        )


class BiocondaAutoWrapAdapter:
    source = "bioconda-auto"

    def __init__(self, root: Path, wrapped_dir: Path, conda_prefix: Path):
        self.root, self.wrapped_dir, self.conda_prefix = map(
            Path, (root, wrapped_dir, conda_prefix)
        )

    def iter_index(self):
        for path in sorted((self.root / "recipes").glob("*/meta.yaml")):
            name = path.parent.name
            yield IndexEntry(
                f"conda:{name}", name, "Bioconda", self.source, wrapped=False, reviewed=False
            )
        for path in sorted(self.wrapped_dir.glob("*/*/meta.yaml")):
            yield index_entry(self.load_spec(f"auto:{path.parent.parent.name}/{path.parent.name}"))

    def location(self, pkg_name, cli_cmd):
        if not PACKAGE.fullmatch(pkg_name) or not COMMAND.fullmatch(cli_cmd):
            raise InvalidToolDefinitionError("包名或命令名无效，不允许路径、空白或 shell 字符")
        return self.wrapped_dir / pkg_name / cli_cmd

    def prepare(self, pkg_name, cli_cmd):
        self.location(pkg_name, cli_cmd)
        env = self.conda_prefix / f"biows-{pkg_name}"
        if not (env / "conda-meta").exists():
            subprocess.run(
                [
                    "conda",
                    "create",
                    "-y",
                    "-p",
                    str(env),
                    "-c",
                    "conda-forge",
                    "-c",
                    "bioconda",
                    pkg_name,
                ],
                check=True,
                timeout=900,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        packages = json.loads(
            subprocess.check_output(["conda", "list", "-p", str(env), "--json"], timeout=30)
        )
        version = next((p["version"] for p in packages if p["name"] == pkg_name), None)
        if not version:
            raise InvalidToolDefinitionError("环境中未找到指定包")
        help_text = ""
        for args in (["--help"], ["-h"], ["help"], []):
            process = subprocess.run(
                ["conda", "run", "-p", str(env), cli_cmd, *args],
                capture_output=True,
                text=True,
                timeout=60,
            )
            help_text = (process.stdout + process.stderr)[:16384]
            if process.returncode == 0 and help_text.strip():
                break
        return {"help_text": help_text, "version": version, "environment": str(env)}

    def validate(self, pkg_name, cli_cmd, data, directory):
        self.location(pkg_name, cli_cmd)
        bio = data.get("biows", {})

        def ports(key):
            value = bio.get(key, {})
            if not isinstance(value, dict) or not value:
                raise InvalidToolDefinitionError("至少声明一个输入和一个输出端口")
            result = []
            for name, item in value.items():
                identifier(name)
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("formats"), list)
                    or not item["formats"]
                ):
                    raise InvalidToolDefinitionError("端口 formats 必须为非空列表")
                result.append(
                    PortSpec(
                        name,
                        tuple(str(f).upper() for f in item["formats"]),
                        bool(item.get("multiple", False)),
                        bool(item.get("optional", False)),
                    )
                )
            return tuple(result)

        inputs, outputs = ports("inputs"), ports("outputs")
        params = tuple(
            ParamSpec(identifier(name), value) for name, value in bio.get("params", {}).items()
        )
        if any(
            p.default is not None and not isinstance(p.default, (str, int, float, bool))
            for p in params
        ):
            raise InvalidToolDefinitionError("参数默认值必须为标量")
        shell = bio.get("shell", "")
        if not isinstance(shell, str) or not shell.strip():
            raise InvalidToolDefinitionError("缺少 shell 模板")
        fields = (
            {"input." + p.name for p in inputs}
            | {"output." + p.name for p in outputs}
            | {"params." + p.name for p in params}
            | {"threads", "log"}
        )
        try:
            for _, field, spec, conversion in string.Formatter().parse(shell):
                if field is not None and (
                    field not in fields or conversion or spec not in ("", "q")
                ):
                    raise ValueError(f"不允许的占位符：{field}")
        except ValueError as exc:
            raise InvalidToolDefinitionError(str(exc)) from exc
        return ToolSpec(
            f"auto:{pkg_name}/{cli_cmd}",
            str(data.get("name", cli_cmd)),
            "Bioconda",
            self.source,
            str(data.get("description", "")),
            (pkg_name,),
            inputs,
            outputs,
            params,
            ExecSpec("shell", shell=shell, conda_env=str(directory / "environment.yaml")),
            reviewed=bool(bio.get("reviewed", False)),
        )

    def store_definition(self, pkg_name, cli_cmd, meta_yaml, version):
        directory = self.location(pkg_name, cli_cmd)
        try:
            data = yaml.safe_load(meta_yaml)
            if not isinstance(data, dict):
                raise ValueError("YAML 必须为字典")
            data.setdefault("biows", {})["reviewed"] = False
            spec = self.validate(pkg_name, cli_cmd, data, directory)
        except (ValueError, TypeError, yaml.YAMLError) as exc:
            raise InvalidToolDefinitionError(str(exc)) from exc
        directory.mkdir(parents=True, exist_ok=True)
        # Metadata is committed last, so an indexed definition always has its environment.
        (directory / "environment.yaml").write_text(
            yaml.safe_dump(
                {"channels": ["conda-forge", "bioconda"], "dependencies": [f"{pkg_name}={version}"]}
            )
        )
        (directory / "meta.yaml").write_text(yaml.safe_dump(data, allow_unicode=True))
        return spec

    def load_spec(self, tool_id):
        if tool_id.startswith("conda:"):
            raise ToolNotWrappedError(f"{tool_id} 尚未封装")
        pkg, cmd = tool_id.removeprefix("auto:").split("/", 1)
        directory = self.location(pkg, cmd)
        if not (directory / "meta.yaml").exists():
            raise ToolNotFoundError(tool_id)
        return self.validate(pkg, cmd, read_yaml(directory / "meta.yaml"), directory)


class ToolRegistry:
    def __init__(self, adapters, cache_dir: Path):
        self.adapters, self.cache_dir = adapters, Path(cache_dir)
        self._entries, self._owners, self._specs = {}, {}, {}
        self._lock = threading.RLock()
        self._built = False

    @classmethod
    def from_config(cls, config):
        return cls(
            [
                InstalledToolsAdapter(),
                SnakemakeWrapperAdapter(
                    config.upstream_dir / "snakemake-wrappers", config.wrappers_version
                ),
                NfCoreModuleAdapter(config.upstream_dir / "nf-core-modules"),
                BiocondaAutoWrapAdapter(
                    config.upstream_dir / "bioconda-recipes",
                    config.data_dir / "auto_wrapped",
                    config.conda_prefix,
                ),
            ],
            config.cache_dir,
        )

    def build_index(self, refresh=False):
        with self._lock:
            entries, owners = {}, {}
            for adapter in self.adapters:
                for entry in cached_entries(adapter, self.cache_dir, refresh):
                    entries[entry.tool_id], owners[entry.tool_id] = entry, adapter
            self._entries, self._owners, self._specs = entries, owners, {}
            self._built = True
            atomic_json(self.cache_dir / "index.json", [asdict(item) for item in entries.values()])

    def _ensure(self):
        if not self._built:
            self.build_index()

    def get(self, tool_id):
        with self._lock:
            self._ensure()
            if tool_id not in self._owners:
                raise ToolNotFoundError(f"找不到工具：{tool_id}")
            if tool_id not in self._specs:
                self._specs[tool_id] = self._owners[tool_id].load_spec(tool_id)
            return self._specs[tool_id]

    def categories(self):
        self._ensure()
        result = defaultdict(list)
        for item in self._entries.values():
            result[item.category].append(item)
        return dict(sorted(result.items()))

    def search(
        self, query="", input_format=None, output_format=None, category=None, limit=10, offset=0
    ):
        self._ensure()
        limit, offset = max(1, min(int(limit), 50)), max(0, int(offset))
        tokens = query.lower().split()
        ranked = []
        for item in self._entries.values():
            if category and item.category != category:
                continue
            if input_format and input_format.upper() not in item.input_formats:
                continue
            if output_format and output_format.upper() not in item.output_formats:
                continue
            name, words, summary = (
                item.name.lower(),
                " ".join(item.keywords).lower(),
                item.summary.lower(),
            )
            scores = [
                10
                if token == name
                else 6
                if name.startswith(token)
                else 4
                if token in name or token in words
                else 1
                if token in summary
                else 0
                for token in tokens
            ]
            if tokens and not all(scores):
                continue
            ranked.append((sum(scores) * (1 if item.reviewed else 0.5), item))
        ranked.sort(key=lambda pair: (-pair[0], pair[1].tool_id))
        return SearchPage(
            len(ranked),
            tuple(item for _, item in ranked[offset : offset + limit]),
            offset + limit if offset + limit < len(ranked) else None,
        )

    def mark_reviewed(self, tool_id):
        self._ensure()
        owner = self._owners.get(tool_id)
        if not isinstance(owner, BiocondaAutoWrapAdapter) or not tool_id.startswith("auto:"):
            raise InvalidToolDefinitionError("请先为上游工具提供经审核的自动封装定义")
        pkg, cmd = tool_id[5:].split("/", 1)
        path = owner.location(pkg, cmd) / "meta.yaml"
        data = read_yaml(path)
        data["biows"]["reviewed"] = True
        path.write_text(yaml.safe_dump(data, allow_unicode=True))
        with self._lock:
            self._specs.pop(tool_id, None)
            self._entries[tool_id] = replace(self._entries[tool_id], reviewed=True)
