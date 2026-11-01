"""On-demand wrapping: env, help capture, definition generation, validation and storage."""

import argparse
import json
import queue
import re
import shlex
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from string import Formatter

import yaml

from glue.config import load_config
from glue.errors import WorkstationError
from glue.formats import EXTENSIONS
from glue.wrapper_registry import PACKAGE, BiocondaAutoWrapAdapter, ToolRegistry

FORMATS = [
    "FASTQ",
    "FASTA",
    "SAM",
    "BAM",
    "CRAM",
    "BAI",
    "VCF",
    "BCF",
    "BED",
    "GTF",
    "GFF",
    "HTML",
    "JSON",
    "TSV",
    "TEXT",
    "ANY",
]
BLOCKED = {
    "python",
    "python3",
    "pip",
    "pip3",
    "conda",
    "mamba",
    "micromamba",
    "activate",
    "deactivate",
    "jupyter",
    "openssl",
    "curl",
    "wget",
    "perl",
    "R",
    "Rscript",
    "tclsh",
    "wish",
    "sqlite3",
    "ssh",
    "scp",
    "tar",
    "gzip",
    "bzip2",
    "xz",
}
TERMINAL = {"wrapped", "needs_review", "needs_definition", "checked", "failed"}
FORMAT_SAMPLES = {
    "TEXT": "a\t1\nb\t2\n",
    "TSV": "a\t1\nb\t2\n",
    "BED": "chr1\t1\t10\n",
    "FASTA": ">s1\nACGTACGTACGT\n",
    "FASTQ": "@r1\nACGTACGTACGT\n+\nIIIIIIIIIIII\n",
    "VCF": (
        "##fileformat=VCFv4.2\n##contig=<ID=chr1,length=4000>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr1\t10\t.\tA\tT\t60\tPASS\t.\n"
    ),
    "GFF": "##gff-version 3\nchr1\tsrc\tgene\t1\t100\t.\t+\t.\tID=g1\n",
    "GTF": 'chr1\tsrc\tgene\t1\t100\t.\t+\t.\tgene_id "g1";\n',
    "ANY": "a\t1\nb\t2\n",
}

SYSTEM_PROMPT = (
    "你是生信工具封装助手。只输出一个 YAML 文档，不要解释，不要 markdown 代码块。"
)
DEFINITION_EXAMPLE = """name: seqkit stats
description: 序列统计
biows:
  inputs:
    reads: {formats: [FASTQ, FASTA], multiple: true}
  outputs:
    stats: {formats: [TSV]}
  params: {}
  shell: "seqkit stats -T {input.reads:q} > {output.stats:q}"
"""


def render_shell(template, values):
    parts = []
    for literal, placeholder, spec, _conversion in Formatter().parse(template):
        parts.append(literal)
        if placeholder is not None:
            value = values[placeholder]
            parts.append(shlex.quote(value) if spec == "q" else value)
    return "".join(parts)


def trial_run(spec, env, conda, timeout=90):
    with tempfile.TemporaryDirectory(prefix="biows-trial-") as temporary:
        work = Path(temporary)
        values = {}
        for port in spec.inputs:
            sample = next((FORMAT_SAMPLES[f] for f in port.formats if f in FORMAT_SAMPLES), None)
            if sample is None:
                return None, "未试运行（输入格式缺少合成夹具）"
            path = work / f"{port.name}.in"
            path.write_text(sample)
            values[f"input.{port.name}"] = str(path)
        for port in spec.outputs:
            if port.directory:
                path = work / port.name
            else:
                extension = EXTENSIONS.get(port.formats[0], ".dat") if port.formats else ".dat"
                path = work / f"{port.name}{extension}"
            values[f"output.{port.name}"] = str(path)
        for param in spec.params:
            values[f"params.{param.name}"] = str(param.default)
        values["threads"] = "1"
        command = render_shell(spec.execution.shell, values)
        process = subprocess.run(
            [conda, "run", "-p", str(env), "bash", "-lc", command],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=work,
        )
        output = (process.stdout + process.stderr).strip()[-300:]
        return process.returncode == 0, output


def package_binaries(env, pkg_name):
    names = set()
    for meta in (Path(env) / "conda-meta").glob(f"{pkg_name}-*.json"):
        try:
            data = json.loads(meta.read_text())
        except (OSError, ValueError):
            continue
        for name in data.get("files", []):
            if not name.startswith("bin/"):
                continue
            binary = Path(name).name
            if binary in BLOCKED or binary.startswith(("python", "pip", "x86_64-conda")):
                continue
            names.add(binary)
    target = pkg_name.lower().replace("-", "").replace("_", "")
    helpers = ("graph", "plot", "example", "demo", "test", "helper", "util")

    def rank(name):
        lower = name.lower()
        flat = lower.replace("-", "").replace("_", "")
        score = 0 if flat == target else 1 if flat.startswith(target) else 2 if target in flat else 3
        helper = any(word in lower for word in helpers)
        return (score, helper, len(name), name)

    return sorted(names, key=rank)


@dataclass
class WrapJob:
    job_id: str
    tool_id: str
    status: str = "queued"
    message: str = ""
    help_text: str = ""
    definition: str = ""
    tool_ids: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class WrapService:
    def __init__(self, config, registry=None, max_commands=3):
        self.config = config
        self.registry = registry or ToolRegistry.from_config(config)
        self.adapter = next(
            (a for a in self.registry.adapters if isinstance(a, BiocondaAutoWrapAdapter)),
            None,
        )
        if self.adapter is None:
            raise WorkstationError("未配置 Bioconda 适配器")
        self.max_commands = max_commands
        self._jobs = {}
        self._lock = threading.RLock()
        self._queue = queue.Queue()
        self._thread = None

    def submit(self, tool_id):
        if not re.fullmatch(r"(conda|auto):[a-z0-9][a-z0-9_.+-]*(/[A-Za-z0-9][A-Za-z0-9_.+-]*)?", tool_id):
            raise WorkstationError("仅支持 conda:<包名> 或 auto:<包>/<命令>")
        job = WrapJob(uuid.uuid4().hex[:8], tool_id)
        with self._lock:
            self._jobs[job.job_id] = job
        self._queue.put(job.job_id)
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._worker, daemon=True)
            self._thread.start()
        return self.job(job.job_id)

    def jobs(self):
        with self._lock:
            items = sorted(self._jobs.values(), key=lambda job: job.created_at, reverse=True)
        result = []
        for job in items:
            data = asdict(job)
            data["help_text"] = job.help_text[-4000:]
            result.append(data)
        return result

    def job(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise WorkstationError("找不到封装任务")
            data = asdict(job)
        data["help_text"] = job.help_text[-4000:]
        return data

    def _update(self, job, status, message=""):
        with self._lock:
            job.status, job.message, job.updated_at = status, message, time.time()

    def _worker(self):
        while True:
            job_id = self._queue.get()
            try:
                with self._lock:
                    job = self._jobs[job_id]
                if job.tool_id.startswith("conda:"):
                    self._wrap_package(job)
                else:
                    self._check_auto(job)
            except Exception as exc:
                self._update(job, "failed", f"{type(exc).__name__}: {exc}")
            finally:
                self._queue.task_done()

    def _wrap_package(self, job):
        pkg = job.tool_id.split(":", 1)[1]
        if not PACKAGE.fullmatch(pkg):
            raise WorkstationError("包名无效")
        self._update(job, "creating_env", f"准备环境 biows-{pkg}")
        env, version = self.adapter.ensure_env(pkg)
        binaries = package_binaries(env, pkg)[: self.max_commands]
        if not binaries:
            raise WorkstationError("该包没有可封装的命令行程序")
        outcomes = []
        for binary in binaries:
            self._update(job, "capturing_help", f"{binary}：抓取 --help")
            prepared = self.adapter.prepare(pkg, binary, binary)
            help_text = prepared["help_text"]
            job.help_text = (job.help_text + "\n\n" + help_text)[-20000:]
            self._update(job, "generating", f"{binary}：生成定义")
            definition, error = self._generate(pkg, binary, help_text)
            if definition is None:
                outcomes.append(f"{binary}: 未生成有效定义（{error}）")
                continue
            text = yaml.safe_dump(definition, allow_unicode=True)
            spec = self.adapter.store_definition(pkg, binary, text, version)
            job.definition = text
            job.tool_ids.append(spec.tool_id)
            self._update(job, "trialing", f"{spec.tool_id}：合成输入试运行")
            passed, detail = trial_run(spec, env, self.adapter._conda())
            if passed is True:
                outcomes.append(f"{spec.tool_id}: 试运行通过（未审核）")
            elif passed is False:
                outcomes.append(f"{spec.tool_id}: 试运行失败（未审核）：{detail}")
            else:
                outcomes.append(f"{spec.tool_id}: {detail}（未审核）")
        if job.tool_ids:
            self._update(job, "indexing", "刷新工具索引")
            self.registry.build_index()
            failed = any("试运行失败" in item for item in outcomes)
            self._update(
                job,
                "needs_review" if failed else "wrapped",
                "；".join(outcomes)[:600],
            )
        else:
            self._update(
                job,
                "needs_definition",
                "未生成有效定义；帮助文本已返回，可配置 LLM 或用 MCP 提交定义",
            )

    def _check_auto(self, job):
        pkg, command = job.tool_id.removeprefix("auto:").split("/", 1)
        spec = self.registry.get(job.tool_id)
        env = self.config.conda_prefix / f"biows-{pkg}"
        candidates = [command]
        shell = spec.execution.shell.split() if spec.execution.shell else []
        if shell:
            candidates.append(shell[0])
        binary = next((c for c in candidates if (env / "bin" / c).is_file()), command)
        self._update(job, "checking", f"{binary}：执行 --version/--help")
        conda = self.adapter._conda()
        output = ""
        for args in (["--version"], ["--help"], []):
            process = subprocess.run(
                [conda, "run", "-p", str(env), binary, *args],
                capture_output=True,
                text=True,
                timeout=60,
            )
            output = (process.stdout + process.stderr).strip()
            if output:
                break
        job.help_text = output[-20000:]
        self._update(job, "checked", output[:300] or "无输出")

    def _generate(self, pkg, command, help_text):
        if not (self.config.llm_base_url and self.config.llm_model):
            return None, "未配置 LLM"
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"包：{pkg}\n命令：{command}\n"
                    f"可用格式标签：{', '.join(FORMATS)}\n\n"
                    "输出一个 biows 定义，字段为 name、description、biows.inputs/outputs/params/shell。\n"
                    "规则：至少一个输入和一个输出；端口名必须是合法标识符；"
                    "shell 使用 {input.<端口>:q}、{output.<端口>:q}、{params.<参数>}、{threads} 占位符；"
                    "只使用帮助文本中真实存在的选项；不确定时省略参数；"
                    "如果帮助文本指出必需参数，必须在 params 中声明并在 shell 中使用；"
                    "不要生成仅把输入重定向到输出的占位命令；"
                    "输出是目录时在端口上加 directory: true，并在 shell 里 mkdir -p；"
                    "参数默认值必须是标量；不要编造输入输出格式。\n\n"
                    f"示例：\n{DEFINITION_EXAMPLE}\n帮助文本：\n{help_text[:12000]}"
                ),
            },
        ]
        error = ""
        for _ in range(2):
            content = self._chat(messages)
            text = content.strip()
            if text.startswith("```"):
                text = "\n".join(line for line in text.splitlines() if not line.startswith("```"))
            try:
                data = yaml.safe_load(text)
                if not isinstance(data, dict):
                    raise ValueError("YAML 不是字典")
                self.adapter.validate(pkg, command, data, self.adapter.wrapped_dir)
                return data, ""
            except Exception as exc:
                error = str(exc)[:200]
                messages += [
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": f"上面的定义校验失败：{error}。请修正并只输出 YAML。"},
                ]
        return None, error

    def _chat(self, messages):
        url = self.config.llm_base_url.rstrip("/")
        if not url.endswith("/chat/completions"):
            url += "/chat/completions"
        payload = {
            "model": self.config.llm_model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 1500,
        }
        headers = {"Content-Type": "application/json"}
        if self.config.llm_api_key:
            headers["Authorization"] = f"Bearer {self.config.llm_api_key}"
        request = urllib.request.Request(
            url, data=json.dumps(payload).encode(), headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                data = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:300]
            raise WorkstationError(f"LLM HTTP {exc.code}: {body}") from exc
        return data["choices"][0]["message"]["content"]


def main(argv=None):
    parser = argparse.ArgumentParser(description="按需封装一个 Bioconda 工具")
    parser.add_argument("--tool", required=True, help="conda:<包名> 或 auto:<包>/<命令>")
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args(argv)
    service = WrapService(load_config())
    job = service.submit(args.tool)
    print(json.dumps(job, ensure_ascii=False))
    if args.wait:
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            job = service.job(job["job_id"])
            if job["status"] in TERMINAL:
                break
            time.sleep(2)
        print(json.dumps(service.job(job["job_id"]), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
