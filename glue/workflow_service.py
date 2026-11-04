"""Shared editable workflow contract for desktop and external agents.

Drafts may be incomplete. Saving validates editable configuration; compilation
validates that the selected workflow is executable.
"""

import copy
import math
from dataclasses import asdict
from graphlib import CycleError, TopologicalSorter

from glue import session_schema as s
from glue.config import allowed_path
from glue.errors import SessionConflictError, WorkstationError
from glue.formats import formats_compatible
from glue.session_store import load_session, save_session


def node_defaults(entry, registry):
    kind = s.INPUT_KIND_BY_TYPE.get(entry.get("type_"))
    if kind:
        return s.input_custom_defaults(kind, s.node_uid(entry))
    if entry.get("type_") == s.OUTPUT_NODE:
        return s.output_custom_defaults(s.node_uid(entry))
    return s.tool_custom_defaults(registry.get(entry["custom"][s.TOOL_ID_PROP]), s.node_uid(entry))


def node_ports(entry, registry):
    kind = s.INPUT_KIND_BY_TYPE.get(entry.get("type_"))
    if kind:
        return {}, {kind.port: (kind.formats, True)}
    if entry.get("type_") == s.OUTPUT_NODE:
        return {s.OUTPUT_NODE_PORT: (("ANY",), True)}, {}
    spec = registry.get(entry["custom"][s.TOOL_ID_PROP])
    return (
        {p.name: (p.formats, p.multiple) for p in spec.inputs},
        {p.name: (p.formats, True) for p in spec.outputs},
    )


def validate_session(session, registry, config):
    """Normalize a copy without requiring a finished graph or installed inputs."""
    result = copy.deepcopy(session)
    nodes = result.get("nodes", {})
    seen = set()
    for entry in nodes.values():
        uid = s.node_uid(entry)
        if not s.is_valid_uid(uid) or uid in seen:
            raise WorkstationError("节点标识无效或重复")
        seen.add(uid)
        defaults = node_defaults(entry, registry)
        custom = entry.setdefault("custom", {})
        for prop in defaults:
            value = custom.get(prop, defaults[prop])
            custom[prop] = s.param_to_str(value) if not isinstance(value, str) else value
        kind = s.INPUT_KIND_BY_TYPE.get(entry.get("type_"))
        if kind:
            for prop in kind.path_props:
                if custom[prop].strip():
                    custom[prop] = str(
                        allowed_path(custom[prop], config.workspace, config.allowed_input_roots)
                    )
        elif s.is_tool_type(entry.get("type_", "")):
            spec = registry.get(custom[s.TOOL_ID_PROP])
            try:
                if int(custom[s.THREADS_PROP]) < 1:
                    raise ValueError("threads 必须为正整数")
                for param in spec.params:
                    s.param_from_str(custom[s.param_prop(param.name)], param.default)
            except (ValueError, TypeError) as exc:
                raise WorkstationError(f"参数无效：{exc}") from exc
        pos = entry.get("pos", [0, 0])
        if len(pos) != 2 or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
            for v in pos
        ):
            raise WorkstationError("position 必须包含两个有限数值")
    dependencies = {key: set() for key in nodes}
    occupied, edges = set(), set()
    for edge in result.get("connections", []):
        src, out = edge["out"]
        dst, incoming = edge["in"]
        if src not in nodes or dst not in nodes:
            raise WorkstationError("连线引用不存在的节点")
        inputs, _ = node_ports(nodes[dst], registry)
        _, outputs = node_ports(nodes[src], registry)
        if out not in outputs or incoming not in inputs:
            raise WorkstationError("指定端口不存在或方向无效")
        ok, reason = formats_compatible(outputs[out][0], inputs[incoming][0])
        if not ok:
            raise WorkstationError(reason)
        signature = (src, out, dst, incoming)
        if signature in edges or ((dst, incoming) in occupied and not inputs[incoming][1]):
            raise WorkstationError("重复连线或输入端口已连接")
        edges.add(signature)
        occupied.add((dst, incoming))
        dependencies[dst].add(src)
    try:
        tuple(TopologicalSorter(dependencies).static_order())
    except CycleError as exc:
        raise WorkstationError("连线会形成环") from exc
    return result


class WorkflowService:
    def __init__(self, config, registry):
        self.config, self.registry = config, registry

    def save(self, session, expected_revision, updated_by="ui"):
        normalized = validate_session(session, self.registry, self.config)
        return save_session(self.config.workspace, normalized, expected_revision, updated_by)

    def read(self):
        self.registry.build_index()
        session, revision = load_session(self.config.workspace)
        nodes = []
        for entry in session.get("nodes", {}).values():
            inputs, outputs = node_ports(entry, self.registry)
            nodes.append(
                {
                    "node_id": s.node_uid(entry),
                    "name": entry.get("name", ""),
                    "type": entry["type_"],
                    "properties": entry.get("custom", {}),
                    "position": entry.get("pos", [0, 0]),
                    "inputs": inputs,
                    "outputs": outputs,
                }
            )
        entries = session.get("nodes", {})
        connections = [
            {
                "from_node": s.node_uid(entries[e["out"][0]]),
                "from_port": e["out"][1],
                "to_node": s.node_uid(entries[e["in"][0]]),
                "to_port": e["in"][1],
            }
            for e in session.get("connections", [])
        ]
        return {
            "revision": revision,
            "nodes": nodes,
            "connections": connections,
            "allow_unreviewed": self.config.allow_unreviewed,
            "builtin_node_kinds": [kind.mcp_kind for kind in s.INPUT_KINDS] + ["output"],
        }

    def tool_schema(self, tool_id):
        kind = s.INPUT_KIND_BY_MCP.get(tool_id)
        if kind:
            return {
                "definition": {
                    "tool_id": kind.mcp_kind,
                    "name": kind.label,
                    "source": "builtin",
                    "inputs": [],
                    "outputs": [
                        {"name": kind.port, "formats": kind.formats, "multiple": kind.multiple}
                    ],
                },
                "properties": dict.fromkeys(kind.path_props, ""),
            }
        if tool_id == "output":
            return {
                "definition": {
                    "tool_id": "output",
                    "name": "输出汇总",
                    "source": "builtin",
                    "inputs": [{"name": "files", "formats": ["ANY"], "multiple": True}],
                    "outputs": [],
                },
                "properties": {"label": ""},
            }
        self.registry.build_index()
        spec = self.registry.get(tool_id)
        return {"definition": asdict(spec), "properties": s.tool_custom_defaults(spec)}

    def edit(
        self,
        operation,
        node_id=None,
        properties=None,
        position=None,
        name=None,
        from_node=None,
        from_port=None,
        to_node=None,
        to_port=None,
        expected_revision=None,
    ):
        session, revision = load_session(self.config.workspace)
        if expected_revision is not None and revision != expected_revision:
            raise SessionConflictError("会话已修改，请重新读取后再编辑")
        if operation in ("update", "remove"):
            key = s.node_key_by_uid(session, node_id)
            if key is None:
                raise WorkstationError("节点不存在")
            if operation == "remove":
                del session["nodes"][key]
                session["connections"] = [
                    e
                    for e in session.get("connections", [])
                    if key not in (e["out"][0], e["in"][0])
                ]
            else:
                entry = session["nodes"][key]
                defaults = node_defaults(entry, self.registry)
                for prop, value in (properties or {}).items():
                    if prop not in defaults or prop in (s.UID_PROP, s.TOOL_ID_PROP):
                        raise WorkstationError(f"不可设置的属性：{prop}")
                    entry["custom"][prop] = s.param_to_str(value)
                if position is not None:
                    entry["pos"] = position
                if name is not None:
                    entry["name"] = name
        elif operation == "disconnect":
            src, dst = s.node_key_by_uid(session, from_node), s.node_key_by_uid(session, to_node)
            if src is None or dst is None:
                raise WorkstationError("节点不存在")
            edge = s.connection_entry(src, from_port, dst, to_port)
            session["connections"] = [e for e in session.get("connections", []) if e != edge]
        else:
            raise WorkstationError("未知编辑操作")
        revision = self.save(session, revision, "mcp")
        return {"ok": True, "revision": revision}
