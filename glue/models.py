"""前后端共享的数据模型（接口契约）。

UI、MCP 服务端与胶水层都只通过这些类型交换数据。字段名与含义是冻结的契约，
修改前必须同时更新 ui/ 与 BACKEND_PROMPT.md。
"""

from __future__ import annotations

import dataclasses
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

ExecKind = Literal["wrapper", "shell", "cwl"]
ToolSource = Literal[
    "snakemake-wrappers", "nf-core", "cwl", "bioconda-auto", "local-demo", "local-installed"
]
RunMode = Literal["all", "until", "step"]
RunState = Literal["pending", "running", "success", "failed", "cancelled"]
NodeState = Literal["waiting", "running", "done", "failed", "skipped"]
DeployMethod = Literal["conda", "apptainer"]
ParamValue = str | int | float | bool | None

TERMINAL_RUN_STATES: frozenset[str] = frozenset({"success", "failed", "cancelled"})


@dataclass(frozen=True, slots=True)
class PortSpec:
    """工具端口；name 即 Snakefile 中 input/output 的关键字名。"""

    name: str
    formats: tuple[str, ...]
    multiple: bool = False
    optional: bool = False
    pattern: str = ""
    description: str = ""


@dataclass(frozen=True, slots=True)
class ParamSpec:
    """工具参数；default 的类型决定画布字符串值如何转换（见 session_schema.param_from_str）。"""

    name: str
    default: ParamValue = None
    description: str = ""


@dataclass(frozen=True, slots=True)
class ExecSpec:
    """工具在 Snakefile 中的执行方式。"""

    kind: ExecKind
    wrapper: str = ""
    shell: str = ""
    conda_env: str = ""
    container: str = ""
    cwl: str = ""


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """完整的工具定义，由 ToolRegistry.get() 按需加载。"""

    tool_id: str
    name: str
    category: str
    source: ToolSource
    description: str
    keywords: tuple[str, ...]
    inputs: tuple[PortSpec, ...]
    outputs: tuple[PortSpec, ...]
    params: tuple[ParamSpec, ...]
    execution: ExecSpec
    threads: int = 1
    reviewed: bool = True

    def input_port(self, name: str) -> PortSpec | None:
        return next((p for p in self.inputs if p.name == name), None)

    def output_port(self, name: str) -> PortSpec | None:
        return next((p for p in self.outputs if p.name == name), None)


@dataclass(frozen=True, slots=True)
class IndexEntry:
    """检索索引中的轻量条目；wrapped=False 表示 Bioconda 包尚未自动封装。"""

    tool_id: str
    name: str
    category: str
    source: ToolSource
    keywords: tuple[str, ...] = ()
    input_formats: tuple[str, ...] = ()
    output_formats: tuple[str, ...] = ()
    summary: str = ""
    reviewed: bool = True
    wrapped: bool = True


@dataclass(frozen=True, slots=True)
class SearchPage:
    """分页检索结果；next_offset 为 None 表示没有下一页。"""

    total: int
    items: tuple[IndexEntry, ...]
    next_offset: int | None = None


@dataclass(slots=True)
class InspectResult:
    """inspect_bio_file() 的结果；stats 的值只允许 JSON 标量或标量列表。"""

    path: str
    format: str
    valid: bool
    error: str = ""
    compressed: str = ""
    index: dict[str, bool] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)
    preview: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CompileResult:
    """compile_session() 的结果；所有路径均为绝对路径，键为节点 bio_uid。"""

    snakefile_text: str
    rule_of_node: dict[str, str]
    outputs: dict[str, dict[str, list[str]]]
    log_paths: dict[str, str]
    targets: list[str]
    warnings: list[str] = field(default_factory=list)

    def node_of_rule(self) -> dict[str, str]:
        return {rule: uid for uid, rule in self.rule_of_node.items()}


@dataclass(slots=True)
class RunStatus:
    """一次运行的派生状态视图，持久化为 runs/<run_id>/status.json。"""

    run_id: str
    mode: RunMode
    target_uid: str | None = None
    dry_run: bool = False
    state: RunState = "pending"
    node_states: dict[str, NodeState] = field(default_factory=dict)
    progress: tuple[int, int] = (0, 0)
    pid: int | None = None
    log_path: str = ""
    started_at: str = ""
    finished_at: str | None = None
    returncode: int | None = None
    failed_rule: str | None = None

    @property
    def finished(self) -> bool:
        return self.state in TERMINAL_RUN_STATES

    def snapshot(self) -> RunStatus:
        """返回可安全跨线程传递的副本。"""
        return dataclasses.replace(self, node_states=dict(self.node_states))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["progress"] = list(self.progress)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunStatus:
        known = {f.name for f in dataclasses.fields(cls)}
        values = {key: value for key, value in data.items() if key in known}
        values["progress"] = tuple(values.get("progress", (0, 0)))
        return cls(**values)


@dataclass(frozen=True, slots=True)
class Config:
    """全局配置，由 glue.config.load_config() 构造。"""

    workspace: Path
    data_dir: Path
    cache_dir: Path
    upstream_dir: Path
    conda_prefix: Path
    wrappers_version: str = "v5.0.0"
    cores: int = 4
    deploy: DeployMethod = "conda"
    allowed_input_roots: tuple[Path, ...] = ()
    allow_unreviewed: bool = False
    bioconda_channeldata_url: str = "https://conda.anaconda.org/bioconda/channeldata.json"
