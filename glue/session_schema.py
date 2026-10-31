"""画布会话 JSON（NodeGraphQt 会话格式）的约定：节点类型、端口名、自定义属性与默认值。

UI 与 MCP 服务端都按本模块创建节点，二者写出的节点必须逐字段一致。
节点在会话中的稳定标识是自定义属性 bio_uid——NodeGraphQt 每次加载都会重新分配节点 id，
nodes 字典的键只用于在同一份 JSON 内解析 connections，不能跨保存/加载引用。
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from glue.models import ParamValue, ToolSpec

SCHEMA_VERSION = 1
SESSION_FILE = "session.json"
SESSION_META_FILE = "session.meta.json"
ANY_FORMAT = "ANY"

FASTQ_INPUT = "bio.input.FastqInputNode"
FASTA_INPUT = "bio.input.FastaReferenceNode"
BAM_INPUT = "bio.input.BamInputNode"
VCF_INPUT = "bio.input.VcfInputNode"
OUTPUT_NODE = "bio.output.BioOutputNode"
TOOL_PREFIX = "bio.tool."

UID_PROP = "bio_uid"
TOOL_ID_PROP = "tool_id"
THREADS_PROP = "threads"
LABEL_PROP = "label"
PARAM_PREFIX = "param_"
OUTPUT_NODE_PORT = "files"
OUTPUT_MCP_KIND = "output"

_UID_RE = re.compile(r"^[0-9a-f]{8}$")
_TRUE_WORDS = frozenset({"true", "1", "yes", "y", "on"})
_FALSE_WORDS = frozenset({"false", "0", "no", "n", "off"})


@dataclass(frozen=True, slots=True)
class InputKind:
    """一种输入节点：单个输出端口，值为 path_props 中非空路径组成的列表。"""

    node_type: str
    mcp_kind: str
    label: str
    port: str
    formats: tuple[str, ...]
    path_props: tuple[str, ...]
    multiple: bool = False


INPUT_KINDS: tuple[InputKind, ...] = (
    InputKind(
        FASTQ_INPUT, "fastq_input", "FASTQ 输入", "reads", ("FASTQ",), ("path_r1", "path_r2"), True
    ),
    InputKind(FASTA_INPUT, "fasta_reference", "FASTA 参考序列", "fasta", ("FASTA",), ("path",)),
    InputKind(BAM_INPUT, "bam_input", "BAM 输入", "bam", ("BAM",), ("path",)),
    InputKind(VCF_INPUT, "vcf_input", "VCF 输入", "vcf", ("VCF", "BCF"), ("path",)),
)
INPUT_KIND_BY_TYPE: dict[str, InputKind] = {kind.node_type: kind for kind in INPUT_KINDS}
INPUT_KIND_BY_MCP: dict[str, InputKind] = {kind.mcp_kind: kind for kind in INPUT_KINDS}


def new_uid() -> str:
    return uuid.uuid4().hex[:8]


def is_valid_uid(uid: object) -> bool:
    return isinstance(uid, str) and bool(_UID_RE.match(uid))


def tool_node_type(tool_id: str) -> str:
    """tool_id → NodeGraphQt 节点类型；带短哈希以避免不同 tool_id 清洗后同名。"""
    slug = re.sub(r"[^0-9A-Za-z]+", "_", tool_id).strip("_")
    digest = hashlib.sha1(tool_id.encode(), usedforsecurity=False).hexdigest()[:6]
    return f"{TOOL_PREFIX}T_{slug}_{digest}"


def is_tool_type(node_type: str) -> bool:
    return node_type.startswith(TOOL_PREFIX)


def param_prop(name: str) -> str:
    return f"{PARAM_PREFIX}{name}"


def param_to_str(value: ParamValue) -> str:
    """参数值 → 画布上保存的字符串（画布属性一律为字符串）。"""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def param_from_str(raw: str, default: ParamValue) -> ParamValue:
    """画布字符串 → 参数值：空串取 default，否则按 default 的类型转换，失败抛 ValueError。"""
    text = raw.strip()
    if not text:
        return default
    if isinstance(default, bool):
        lowered = text.lower()
        if lowered in _TRUE_WORDS:
            return True
        if lowered in _FALSE_WORDS:
            return False
        raise ValueError(f"无法解析为布尔值：{raw!r}")
    if isinstance(default, int):
        return int(text)
    if isinstance(default, float):
        return float(text)
    return raw


def input_custom_defaults(kind: InputKind, uid: str | None = None) -> dict[str, str]:
    return {UID_PROP: uid or new_uid(), **dict.fromkeys(kind.path_props, "")}


def output_custom_defaults(uid: str | None = None) -> dict[str, str]:
    return {UID_PROP: uid or new_uid(), LABEL_PROP: ""}


def tool_custom_defaults(spec: ToolSpec, uid: str | None = None) -> dict[str, str]:
    custom = {
        UID_PROP: uid or new_uid(),
        TOOL_ID_PROP: spec.tool_id,
        THREADS_PROP: str(spec.threads),
    }
    custom.update({param_prop(p.name): param_to_str(p.default) for p in spec.params})
    return custom


def node_entry(
    node_type: str, name: str, custom: Mapping[str, str], pos: tuple[float, float] = (0.0, 0.0)
) -> dict[str, Any]:
    """构造 NodeGraphQt 可反序列化的最小节点条目（其余字段由 NodeGraphQt 取默认值）。"""
    return {
        "type_": node_type,
        "name": name,
        "pos": [float(pos[0]), float(pos[1])],
        "custom": dict(custom),
    }


def connection_entry(
    out_key: str, out_port: str, in_key: str, in_port: str
) -> dict[str, list[str]]:
    return {"out": [out_key, out_port], "in": [in_key, in_port]}


def iter_nodes(session: Mapping[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    """遍历会话中的 (节点键, 节点条目)。"""
    yield from session.get("nodes", {}).items()


def node_uid(entry: Mapping[str, Any]) -> str:
    return str(entry.get("custom", {}).get(UID_PROP, ""))


def node_key_by_uid(session: Mapping[str, Any], uid: str) -> str | None:
    return next((key for key, entry in iter_nodes(session) if node_uid(entry) == uid), None)


def input_paths(entry: Mapping[str, Any]) -> list[str]:
    """输入节点条目中按端口顺序排列的非空路径。"""
    kind = INPUT_KIND_BY_TYPE.get(entry.get("type_", ""))
    if kind is None:
        return []
    custom = entry.get("custom", {})
    return [path for prop in kind.path_props if (path := str(custom.get(prop, "")).strip())]
