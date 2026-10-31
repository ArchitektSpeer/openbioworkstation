"""Atomic JSON snapshots with advisory locks and optimistic revisions."""

import copy
import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from glue import session_schema as schema
from glue.errors import SessionConflictError, WorkstationError


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix="." + path.name)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def workspace_lock(workdir: Path, name="session.lock", blocking=True):
    workdir.mkdir(parents=True, exist_ok=True)
    with (workdir / name).open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        try:
            yield handle
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _load(workdir):
    path = Path(workdir) / schema.SESSION_FILE
    if not path.exists():
        return {"nodes": {}, "connections": []}, 0
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict) or not isinstance(data.get("nodes", {}), dict):
            raise ValueError("无效的会话结构")
        # Revision is embedded in the same atomic file; sidecar is for external observers.
        return data, int(data.get("_biows_revision", 0))
    except (ValueError, OSError) as exc:
        raise WorkstationError(f"无法读取会话：{exc}") from exc


def load_session(workdir: Path):
    with workspace_lock(Path(workdir)):
        return _load(workdir)


def read_revision(workdir: Path) -> int:
    return load_session(workdir)[1]


def save_session(workdir: Path, session: dict, expected_revision=None, updated_by="backend") -> int:
    workdir = Path(workdir)
    with workspace_lock(workdir):
        _, revision = _load(workdir)
        if expected_revision is not None and revision != expected_revision:
            raise SessionConflictError("会话已修改，请重新读取后再保存")
        revision += 1
        data = copy.deepcopy(session)
        data["_biows_revision"] = revision
        atomic_json(workdir / schema.SESSION_FILE, data)
        atomic_json(
            workdir / schema.SESSION_META_FILE,
            {
                "revision": revision,
                "updated_by": updated_by,
                "schema_version": schema.SCHEMA_VERSION,
            },
        )
        return revision


def sanitize_session(session: dict, registry):
    result = copy.deepcopy(session)
    warnings = []
    nodes = result.setdefault("nodes", {})
    seen = set()
    for key, entry in list(nodes.items()):
        try:
            kind = entry.get("type_", "")
            if schema.is_tool_type(kind):
                spec = registry.get(entry.get("custom", {}).get(schema.TOOL_ID_PROP, ""))
                entry["type_"] = schema.tool_node_type(spec.tool_id)
                defaults = schema.tool_custom_defaults(spec)
            elif kind in schema.INPUT_KIND_BY_TYPE:
                defaults = schema.input_custom_defaults(schema.INPUT_KIND_BY_TYPE[kind])
            elif kind == schema.OUTPUT_NODE:
                defaults = schema.output_custom_defaults()
            else:
                raise WorkstationError(f"未知节点类型：{kind}")
            custom = entry.setdefault("custom", {})
            entry["custom"] = defaults | custom
            uid = schema.node_uid(entry)
            if not schema.is_valid_uid(uid) or uid in seen:
                entry["custom"][schema.UID_PROP] = schema.new_uid()
                warnings.append(f"已修复节点 {key} 的标识")
            seen.add(schema.node_uid(entry))
        except WorkstationError as exc:
            del nodes[key]
            warnings.append(f"已移除不可用节点 {key}：{exc}")
    connections = []
    for edge in result.get("connections", []):
        try:
            if edge["out"][0] in nodes and edge["in"][0] in nodes:
                connections.append(edge)
        except (KeyError, TypeError, IndexError):
            warnings.append("已移除损坏连线")
    result["connections"] = connections
    return result, warnings
