"""Compile the shared canvas contract; delegate all scheduling to Snakemake."""

import json
import os
import re
import subprocess
import sys
import threading
import uuid
from datetime import UTC, datetime
from graphlib import CycleError, TopologicalSorter
from pathlib import Path

from glue import session_schema as schema
from glue.config import allowed_path, load_config
from glue.errors import CompileError, RunBusyError, RunNotFoundError, WorkstationError
from glue.formats import BWA_EXTENSIONS, EXTENSIONS, formats_compatible
from glue.models import CompileResult, RunStatus
from glue.session_store import atomic_json, workspace_lock
from glue.wrapper_registry import identifier


def compile_session(
    session, registry, workdir: Path, *, allow_unreviewed=False, allowed_input_roots=()
):
    workdir = Path(workdir).resolve()
    nodes = session.get("nodes", {})
    dependencies = {key: set() for key in nodes}
    uids, specs, rules, outputs, logs, incoming = {}, {}, {}, {}, {}, {}
    warnings = []
    for key, entry in nodes.items():
        uid = schema.node_uid(entry)
        if not schema.is_valid_uid(uid) or uid in uids.values():
            raise CompileError("节点 bio_uid 无效或重复", uid)
        uids[key] = uid
        typ = entry.get("type_", "")
        if schema.is_tool_type(typ):
            spec = registry.get(entry.get("custom", {}).get(schema.TOOL_ID_PROP, ""))
            for p in (*spec.inputs, *spec.outputs, *spec.params):
                identifier(p.name)
            if not spec.outputs:
                raise CompileError("工具没有输出端口", uid)
            if not spec.reviewed:
                if not allow_unreviewed:
                    raise CompileError(f"工具尚未审核：{spec.name}", uid)
                warnings.append(f"未审核工具：{spec.name}")
            specs[key] = spec
            rules[uid] = "n_" + re.sub(r"[^A-Za-z0-9_]", "_", spec.name) + "_" + uid
        elif typ not in schema.INPUT_KIND_BY_TYPE and typ != schema.OUTPUT_NODE:
            raise CompileError(f"未知节点类型：{typ}", uid)
    for edge in session.get("connections", []):
        try:
            src, out_port = edge["out"]
            dst, in_port = edge["in"]
            if src not in nodes or dst not in nodes:
                raise ValueError("连线引用不存在的节点")
            src_kind = schema.INPUT_KIND_BY_TYPE.get(nodes[src].get("type_"))
            if src in specs:
                source_port = specs[src].output_port(out_port)
                source_formats = source_port.formats if source_port else None
            else:
                source_formats = (
                    src_kind.formats if src_kind and out_port == src_kind.port else None
                )
            if dst in specs:
                dest_port = specs[dst].input_port(in_port)
                dest_formats = dest_port.formats if dest_port else None
            else:
                dest_port = None
                dest_formats = (
                    ("ANY",)
                    if nodes[dst].get("type_") == schema.OUTPUT_NODE
                    and in_port == schema.OUTPUT_NODE_PORT
                    else None
                )
            if source_formats is None or dest_formats is None:
                raise ValueError("连线端口不存在或方向不合法")
            ok, reason = formats_compatible(source_formats, dest_formats)
            if not ok:
                raise ValueError(reason)
            bucket = incoming.setdefault((dst, in_port), [])
            if (src, out_port) in bucket:
                raise ValueError("重复连线")
            if bucket and dest_port and not dest_port.multiple:
                raise ValueError("单文件输入不能连接多个上游")
            bucket.append((src, out_port))
            dependencies[dst].add(src)
        except (ValueError, KeyError, TypeError) as exc:
            raise CompileError(f"无效连线：{exc}") from exc
    try:
        ordered = list(TopologicalSorter(dependencies).static_order())
    except CycleError as exc:
        raise CompileError("画布存在环，无法运行") from exc

    def source_paths(key, port):
        if key in specs:
            return outputs[uids[key]][port]
        paths = schema.input_paths(nodes[key])
        if not paths:
            raise CompileError("输入节点未指定文件", uids[key])
        resolved = [allowed_path(p, workdir, allowed_input_roots) for p in paths]
        if any(not p.is_file() for p in resolved):
            raise CompileError("输入文件不存在", uids[key])
        return [str(p) for p in resolved]

    blocks = []
    for key in ordered:
        if key not in specs:
            continue
        spec, uid = specs[key], uids[key]
        rule = rules[uid]
        resolved_inputs, input_expr = {}, {}
        for port in spec.inputs:
            sources = incoming.get((key, port.name), [])
            if not sources and not port.optional:
                raise CompileError(f"缺少必填输入：{port.name}", uid)
            paths = [path for src, out in sources for path in source_paths(src, out)]
            if not port.multiple and len(paths) > 1:
                raise CompileError(f"端口 {port.name} 仅接受一个文件", uid)
            resolved_inputs[port.name] = paths
            if len(sources) == 1 and sources[0][0] in specs:
                src, out = sources[0]
                input_expr[port.name] = f"rules.{rules[uids[src]]}.output.{out}"
            else:
                input_expr[port.name] = repr(paths if port.multiple else paths[0] if paths else [])
        if spec.tool_id == "smk:bio/fastp" and len(resolved_inputs.get("sample", [])) not in (1, 2):
            raise CompileError("fastp 需要一个或两个 FASTQ 文件", uid)
        output_paths, output_expr = {}, {}
        count = max(
            (
                len(v)
                for p, v in resolved_inputs.items()
                if (spec.input_port(p).multiple and spec.input_port(p).formats != ("BWA_INDEX",))
            ),
            default=1,
        )
        count = max(count, 1)
        for port in spec.outputs:
            prefix = workdir / "results" / rule / port.name
            if port.directory:
                path = str(prefix)
                paths = [path]
                expression = f"directory({path!r})"
            elif spec.execution.kind == "cwl":
                # cwltool output binding filenames are preserved inside this rule's outdir.
                pattern = port.pattern
                if not pattern or Path(pattern).is_absolute() or ".." in Path(pattern).parts:
                    raise CompileError("CWL 输出路径必须是静态相对文件名", uid)
                paths = [str(workdir / "results" / rule / pattern)]
                expression = repr(paths if port.multiple else paths[0])
            elif "BWA_INDEX" in port.formats:
                paths = [str(prefix) + ext for ext in BWA_EXTENSIONS]
                expression = (
                    f"multiext({str(prefix)!r}, " + ", ".join(repr(e) for e in BWA_EXTENSIONS) + ")"
                )
            else:
                extension = EXTENSIONS.get(port.formats[0], ".dat")
                paths = [
                    str(prefix) + (f"_{i + 1}" if port.multiple else "") + extension
                    for i in range(count if port.multiple else 1)
                ]
                expression = repr(paths if port.multiple else paths[0])
            output_paths[port.name], output_expr[port.name] = paths, expression
        outputs[uid] = output_paths
        log = str(workdir / "logs" / f"{rule}.log")
        logs[uid] = log
        lines = [f"rule {rule}:", "    input:"]
        lines.extend(f"        {p}={expr}," for p, expr in input_expr.items())
        if not input_expr:
            lines.append("        [],")
        lines.append("    output:")
        lines.extend(f"        {p}={expr}," for p, expr in output_expr.items())
        custom = nodes[key].get("custom", {})
        params = {}
        try:
            threads = int(custom.get(schema.THREADS_PROP, spec.threads))
            if threads < 1:
                raise ValueError("threads 必须为正整数")
            for param in spec.params:
                params[param.name] = schema.param_from_str(
                    str(custom.get(schema.param_prop(param.name), "")), param.default
                )
        except (ValueError, TypeError) as exc:
            raise CompileError(f"参数无效：{exc}", uid) from exc
        if params:
            lines.append("    params:")
            lines.extend(f"        {name}={value!r}," for name, value in params.items())
        lines += [
            f"    threads: {threads}",
            f"    log: {log!r}",
            f"    benchmark: {str(workdir / 'benchmarks' / (rule + '.tsv'))!r}",
        ]
        execution = spec.execution
        if execution.kind != "wrapper":
            if execution.conda_env:
                lines.append(f"    conda: {execution.conda_env!r}")
            if execution.container:
                lines.append(f"    container: {execution.container!r}")
        if execution.kind == "wrapper":
            if not execution.wrapper:
                raise CompileError("缺少 wrapper 地址", uid)
            lines.append(f"    wrapper: {execution.wrapper!r}")
        elif execution.kind == "cwl":
            # File-valued inputs are passed through a generated immutable job JSON.
            job = {
                name: (
                    [{"class": "File", "path": p} for p in paths]
                    if spec.input_port(name).multiple
                    else {"class": "File", "path": paths[0]}
                    if paths
                    else None
                )
                for name, paths in resolved_inputs.items()
            }
            # Inline job bytes avoid compiler side effects; a separate CLI runner writes them.
            import base64
            import shlex

            encoded = base64.b64encode(json.dumps(job).encode()).decode()
            command = shlex.join(
                [
                    sys.executable,
                    "-m",
                    "glue.cwl_runner",
                    execution.cwl,
                    str(workdir / "results" / rule),
                    encoded,
                ]
            )
            lines.append(f"    shell: {command!r}")
        elif execution.kind == "shell" and execution.shell.strip():
            lines.append(f"    shell: {execution.shell!r}")
        else:
            raise CompileError("缺少可执行模板，请先完成工具转换与审核", uid)
        blocks.append("\n".join(lines))
    targets = []
    output_keys = [k for k in ordered if nodes[k].get("type_") == schema.OUTPUT_NODE]
    if output_keys:
        for key in output_keys:
            paths = [
                path
                for src, port in incoming.get((key, schema.OUTPUT_NODE_PORT), [])
                for path in source_paths(src, port)
            ]
            outputs[uids[key]] = {schema.OUTPUT_NODE_PORT: paths}
            targets.extend(paths)
    else:
        used = {src for deps in dependencies.values() for src in deps}
        targets = [
            path
            for key in specs
            if key not in used
            for paths in outputs[uids[key]].values()
            for path in paths
        ]
    if not targets:
        raise CompileError("画布没有可运行的输出目标")
    text = (
        "# Generated by OpenBioWorkstation\nrule all:\n    input: "
        + repr(list(dict.fromkeys(targets)))
        + "\n\n"
        + "\n\n".join(blocks)
        + "\n"
    )
    return CompileResult(text, rules, outputs, logs, list(dict.fromkeys(targets)), warnings)


def build_command(
    snakefile, workdir, config, *, mode="all", rule=None, cores=4, dry_run=False, use_conda=True
):
    if mode not in ("all", "until", "step") or cores < 1:
        raise WorkstationError("无效的运行模式或 CPU 数")
    if mode != "all" and not rule:
        raise WorkstationError("单步或运行至此需要工具节点")
    command = [
        sys.executable,
        "-m",
        "snakemake",
        "-s",
        str(snakefile),
        "-d",
        str(workdir),
        "--cores",
        str(cores),
        "--printshellcmds",
        "--rerun-incomplete",
        "--nocolor",
    ]
    if use_conda:
        command += ["--conda-prefix", str(config.conda_prefix)]
        command += ["--use-conda"] if config.deploy == "conda" else ["--sdm", "conda", "apptainer"]
    if rule:
        # Explicitly target the rule, including disconnected branches not present in rule all.
        command += [rule, "--until", rule]
        if mode == "step":
            command += ["--forcerun", rule]
    if dry_run:
        command += ["--dry-run"]
    return command


def parse_log_line(line, status, node_of_rule, jobs=None):
    """Update a status from Snakemake 8/9 logs; caller owns the job map."""
    jobs = jobs if jobs is not None else {}
    line = line.strip()
    match = re.match(r"(?:local)?rule (\S+):", line)
    if match:
        jobs["_rule"] = match[1]
        uid = node_of_rule.get(match[1])
        if uid:
            status.node_states[uid] = "running"
    match = re.match(r"jobid:\s*(\d+)", line)
    if match and jobs.get("_rule"):
        jobs[match[1]] = jobs["_rule"]
    match = re.search(r"Finished job(?:id)?\s*:?\s*(\d+)", line)
    if match:
        uid = node_of_rule.get(jobs.get(match[1]))
        if uid:
            status.node_states[uid] = "done"
    match = re.match(r"(\d+) of (\d+) steps", line)
    if match:
        status.progress = (int(match[1]), int(match[2]))
    match = re.search(r"Error in rule (\S+):", line)
    if match:
        status.failed_rule = match[1]
        uid = node_of_rule.get(match[1])
        if uid:
            status.node_states[uid] = "failed"
    if "Nothing to be done" in line:
        status.node_states = {
            uid: "skipped" if state == "waiting" else state
            for uid, state in status.node_states.items()
        }
    return status


def _now():
    return datetime.now(UTC).isoformat()


class RunManager:
    def __init__(self, workdir: Path, registry, config=None, on_update=None):
        self.workdir, self.registry = Path(workdir).resolve(), registry
        self.config = config or load_config(workspace=self.workdir)
        self.on_update = on_update

    def start(self, session, mode="all", target_uid=None, cores=None, dry_run=False):
        result = compile_session(
            session,
            self.registry,
            self.workdir,
            allow_unreviewed=self.config.allow_unreviewed,
            allowed_input_roots=self.config.allowed_input_roots,
        )
        rule = result.rule_of_node.get(target_uid) if mode != "all" else None
        nodes = session.get("nodes", {})
        predecessors = {key: set() for key in nodes}
        for edge in session.get("connections", []):
            predecessors[edge["in"][0]].add(edge["out"][0])
        if mode != "all":
            seeds = {key for key, entry in nodes.items() if schema.node_uid(entry) == target_uid}
        else:
            seeds = {
                key for key, entry in nodes.items() if entry.get("type_") == schema.OUTPUT_NODE
            }
            if not seeds:
                used = {key for values in predecessors.values() for key in values}
                seeds = {
                    key
                    for key, entry in nodes.items()
                    if schema.node_uid(entry) in result.rule_of_node and key not in used
                }
        selected = set(seeds)
        pending = list(seeds)
        while pending:
            for key in predecessors[pending.pop()]:
                if key not in selected:
                    selected.add(key)
                    pending.append(key)
        planned_nodes = {
            schema.node_uid(nodes[key]) for key in selected
        } & result.rule_of_node.keys()
        run_id = uuid.uuid4().hex
        directory = self.workdir / "runs" / run_id
        with workspace_lock(self.workdir, "runs.lock"):
            if any(not run.finished for run in self.list_runs(limit=100000)):
                raise RunBusyError("工作区已有运行中的任务")
            command = build_command(
                directory / "Snakefile",
                self.workdir,
                self.config,
                mode=mode,
                rule=rule,
                cores=self.config.cores if cores is None else cores,
                dry_run=dry_run,
                use_conda=bool(
                    re.search(r"^    (?:wrapper|conda|container):", result.snakefile_text, re.M)
                ),
            )
            directory.mkdir(parents=True)
            for folder in ("logs", "benchmarks"):
                (self.workdir / folder).mkdir(exist_ok=True)
            (directory / "Snakefile").write_text(result.snakefile_text)
            (self.workdir / "Snakefile").write_text(result.snakefile_text)
            atomic_json(directory / "session.json", session)
            atomic_json(
                directory / "manifest.json",
                {
                    "command": command,
                    "node_of_rule": result.node_of_rule(),
                    "outputs": result.outputs,
                    "warnings": result.warnings,
                    "planned_jobs": len(planned_nodes),
                    "planned_jobs_kind": "graph_rules_before_cache",
                },
            )
            status = RunStatus(
                run_id,
                mode,
                target_uid,
                dry_run,
                node_states={
                    uid: "waiting" if uid in planned_nodes else "skipped"
                    for uid in result.rule_of_node
                },
                log_path=str(directory / "snakemake.log"),
                started_at=_now(),
            )
            atomic_json(directory / "status.json", status.to_dict())
            # A detached Python supervisor owns stdout and state even after UI/MCP exits.
            env = os.environ.copy()
            root = str(Path(__file__).resolve().parent.parent)
            env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
            if self.config.deploy == "conda":
                condarc = self.config.cache_dir / "conda.condarc"
                if not condarc.exists():
                    condarc.parent.mkdir(parents=True, exist_ok=True)
                    condarc.write_text(
                        "channels:\n  - conda-forge\n  - bioconda\n"
                        "default_channels: []\nchannel_priority: strict\n"
                    )
                env.setdefault("CONDARC", str(condarc))
                env.setdefault("CONDA_DEFAULT_CHANNELS", "")
                conda_bin = Path(self.config.conda_bin)
                if conda_bin.is_file():
                    env["PATH"] = str(conda_bin.parent) + os.pathsep + env.get("PATH", "")
            try:
                with (directory / "supervisor.log").open("a") as log:
                    process = subprocess.Popen(
                        [sys.executable, "-m", "glue.run_worker", str(directory)],
                        stdin=subprocess.DEVNULL,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                        env=env,
                    )
                status.pid, status.state = process.pid, "running"
                atomic_json(directory / "status.json", status.to_dict())
                # Worker waits for this ready marker before reading status.
                (directory / "ready").touch()
            except OSError as exc:
                status.state, status.finished_at = "failed", _now()
                atomic_json(directory / "status.json", status.to_dict())
                raise WorkstationError(f"无法启动运行：{exc}") from exc
        if self.on_update:

            def follow():
                import time

                while True:
                    current = self.status(run_id)
                    self.on_update(current.snapshot())
                    if current.finished:
                        return
                    time.sleep(0.3)

            threading.Thread(target=follow, daemon=True).start()
        return run_id

    def _directory(self, run_id):
        if not re.fullmatch(r"[0-9a-f]{32}", run_id):
            raise RunNotFoundError(run_id)
        path = self.workdir / "runs" / run_id
        if not (path / "status.json").exists():
            raise RunNotFoundError(run_id)
        return path

    def status(self, run_id):
        directory = self._directory(run_id)
        status = RunStatus.from_dict(json.loads((directory / "status.json").read_text()))
        if not status.finished and status.pid:
            try:
                os.kill(status.pid, 0)
                # Zombies are no longer executing but still accept signal 0.
                stat = Path(f"/proc/{status.pid}/stat")
                if stat.exists() and stat.read_text().split(") ", 1)[1].startswith("Z"):
                    raise ProcessLookupError()
            except ProcessLookupError:
                status.state, status.finished_at = "failed", _now()
                atomic_json(directory / "status.json", status.to_dict())
        return status

    def cancel(self, run_id):
        directory = self._directory(run_id)
        status = self.status(run_id)
        if status.finished:
            return False
        (directory / "cancel").touch()
        return True

    def list_runs(self, limit=20):
        paths = sorted(
            (self.workdir / "runs").glob("*/status.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return [self.status(path.parent.name) for path in paths[: max(0, limit)]]
