"""stdio MCP facade over the same backend and session contract as the desktop UI."""

import argparse
import asyncio
import json
import uuid
from collections import deque
from dataclasses import asdict
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from glue import session_schema as schema
from glue.bio_inspector import inspect_bio_file
from glue.config import allowed_path, load_config
from glue.errors import WorkstationError
from glue.formats import formats_compatible
from glue.session_store import load_session, save_session
from glue.snakemake_bridge import RunManager, compile_session
from glue.wrapper_registry import BiocondaAutoWrapAdapter, ToolRegistry

DEFINITION_EXAMPLE = """name: example
biows:
  inputs:
    reads: {formats: [FASTQ]}
  outputs:
    report: {formats: [TEXT]}
  params: {extra: ""}
  shell: "example {params.extra} {input.reads:q} > {output.report:q}"
"""


def create_server(config, registry=None):
    registry = registry or ToolRegistry.from_config(config)
    manager = RunManager(config.workspace, registry, config)
    mcp = FastMCP("openbioworkstation")

    def compile_current(allow_unreviewed=False):
        session, _ = load_session(config.workspace)
        return compile_session(
            session,
            registry,
            config.workspace,
            allow_unreviewed=allow_unreviewed,
            allowed_input_roots=config.allowed_input_roots,
        )

    def node_ports(entry):
        kind = schema.INPUT_KIND_BY_TYPE.get(entry.get("type_"))
        if kind:
            return {}, {kind.port: (kind.formats, True)}
        if entry.get("type_") == schema.OUTPUT_NODE:
            return {schema.OUTPUT_NODE_PORT: (("ANY",), True)}, {}
        spec = registry.get(entry.get("custom", {}).get(schema.TOOL_ID_PROP, ""))
        return (
            {p.name: (p.formats, p.multiple) for p in spec.inputs},
            {p.name: (p.formats, True) for p in spec.outputs},
        )

    @mcp.tool()
    async def search_bio_tools(
        query: str = "",
        input_format: str | None = None,
        output_format: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> dict:
        """Search a bounded catalog page, filtering input/output format tags."""
        page = await asyncio.to_thread(
            registry.search, query, input_format, output_format, limit=limit, offset=offset
        )
        return asdict(page)

    @mcp.tool()
    async def auto_wrap_bioconda_pkg(
        pkg_name: str,
        cli_cmd: str,
        meta_yaml: str | None = None,
        binary: str | None = None,
    ) -> dict:
        """Fetch CLI help, then submit a biows YAML definition in a second call. New tools require review."""
        adapter = next(
            (a for a in registry.adapters if isinstance(a, BiocondaAutoWrapAdapter)), None
        )
        if adapter is None:
            raise WorkstationError("未配置 Bioconda 适配器")
        prepared = await asyncio.to_thread(adapter.prepare, pkg_name, cli_cmd, binary)
        if meta_yaml is None:
            help_text = prepared["help_text"]
            return {
                "status": "needs_definition",
                "help_text": help_text[:6000],
                "truncated": len(help_text) > 6000,
                "schema": "biows: inputs/outputs={name:{formats:[FORMAT],multiple:bool,optional:bool}}, params={name:scalar}, shell=str",
                "example": DEFINITION_EXAMPLE,
            }
        spec = await asyncio.to_thread(
            adapter.store_definition, pkg_name, cli_cmd, meta_yaml, prepared["version"]
        )
        await asyncio.to_thread(registry.build_index, True)
        return {
            "tool_id": spec.tool_id,
            "reviewed": False,
            "inputs": [asdict(p) for p in spec.inputs],
            "outputs": [asdict(p) for p in spec.outputs],
        }

    @mcp.tool()
    async def add_node(
        tool_id_or_kind: str, properties: dict | None = None, position: list[float] | None = None
    ) -> dict:
        """Add an input/output/tool node and return its stable bio_uid for future calls."""
        session, revision = await asyncio.to_thread(load_session, config.workspace)
        uid, key = schema.new_uid(), uuid.uuid4().hex
        kind = schema.INPUT_KIND_BY_MCP.get(tool_id_or_kind)
        if kind:
            typ, name = kind.node_type, kind.label
            custom = schema.input_custom_defaults(kind, uid)
        elif tool_id_or_kind == schema.OUTPUT_MCP_KIND:
            typ, name = schema.OUTPUT_NODE, "输出"
            custom = schema.output_custom_defaults(uid)
        else:
            spec = await asyncio.to_thread(registry.get, tool_id_or_kind)
            typ, name = schema.tool_node_type(spec.tool_id), spec.name
            custom = schema.tool_custom_defaults(spec, uid)
        for prop, value in (properties or {}).items():
            if prop not in custom or prop in (schema.UID_PROP, schema.TOOL_ID_PROP):
                raise WorkstationError(f"不可设置的属性：{prop}")
            custom[prop] = str(value)
        inspections = []
        if kind:
            for prop in kind.path_props:
                if custom[prop]:
                    path = allowed_path(custom[prop], config.workspace, config.allowed_input_roots)
                    custom[prop] = str(path)
                    inspection = await asyncio.to_thread(inspect_bio_file, str(path))
                    inspections.append(inspection.to_dict())
        if position is not None and (
            len(position) != 2 or any(not isinstance(v, (int, float)) for v in position)
        ):
            raise WorkstationError("position 必须包含两个数值")
        pos = (
            tuple(position)
            if position is not None
            else (
                0 if kind else 600 if typ == schema.OUTPUT_NODE else 300,
                150 * len(session.get("nodes", {})),
            )
        )
        entry = schema.node_entry(typ, name, custom, pos)
        session.setdefault("nodes", {})[key] = entry
        await asyncio.to_thread(save_session, config.workspace, session, revision, "mcp")
        inputs, outputs = node_ports(entry)
        return {
            "node_id": uid,
            "inputs": list(inputs),
            "outputs": list(outputs),
            "inspect": inspections,
        }

    @mcp.tool()
    async def connect_nodes(from_node: str, from_port: str, to_node: str, to_port: str) -> dict:
        """Connect stable node IDs using the same port format checks as the UI."""
        session, revision = await asyncio.to_thread(load_session, config.workspace)
        src, dst = (
            schema.node_key_by_uid(session, from_node),
            schema.node_key_by_uid(session, to_node),
        )
        if src is None or dst is None:
            raise WorkstationError("节点不存在，请使用 add_node 返回的 node_id")
        inputs, _ = node_ports(session["nodes"][dst])
        _, outputs = node_ports(session["nodes"][src])
        if from_port not in outputs or to_port not in inputs:
            raise WorkstationError("指定端口不存在或方向无效")
        ok, reason = formats_compatible(outputs[from_port][0], inputs[to_port][0])
        if not ok:
            return {"ok": False, "reason": reason}
        edge = schema.connection_entry(src, from_port, dst, to_port)
        edges = session.setdefault("connections", [])
        if edge in edges:
            return {"ok": True}
        if not inputs[to_port][1] and any(e["in"] == [dst, to_port] for e in edges):
            return {"ok": False, "reason": "输入端口已连接"}
        from graphlib import CycleError, TopologicalSorter

        dependencies = {key: set() for key in session["nodes"]}
        for item in [*edges, edge]:
            dependencies[item["in"][0]].add(item["out"][0])
        try:
            tuple(TopologicalSorter(dependencies).static_order())
        except CycleError:
            return {"ok": False, "reason": "连线会形成环"}
        edges.append(edge)
        await asyncio.to_thread(save_session, config.workspace, session, revision, "mcp")
        return {"ok": True}

    @mcp.tool()
    async def compile_and_run_async(
        mode: str = "all", target_node: str | None = None, cores: int = 4, dry_run: bool = False
    ) -> dict:
        """Compile an immutable run snapshot and start Snakemake in the background."""
        session, _ = await asyncio.to_thread(load_session, config.workspace)
        run_id = await asyncio.to_thread(
            manager.start, session, mode=mode, target_uid=target_node, cores=cores, dry_run=dry_run
        )
        directory = config.workspace / "runs" / run_id
        manifest = json.loads((directory / "manifest.json").read_text())
        return {
            "run_id": run_id,
            "snakefile_path": str(directory / "Snakefile"),
            "planned_jobs": manifest["planned_jobs"],
            "planned_jobs_kind": manifest["planned_jobs_kind"],
            "warnings": manifest["warnings"],
        }

    @mcp.tool()
    async def get_run_status(run_id: str, log_tail: int = 30) -> dict:
        """Return durable run state and at most 100 log lines / 8 KB."""
        status = await asyncio.to_thread(manager.status, run_id)
        data = status.to_dict()
        count = max(0, min(100, log_tail))
        path = Path(status.log_path)
        if path.exists() and count:

            def tail():
                with path.open("rb") as stream:
                    stream.seek(max(0, path.stat().st_size - 16384))
                    return stream.read().decode("utf-8", errors="replace")

            lines = deque((await asyncio.to_thread(tail)).splitlines(), maxlen=count)
            data["log_tail"] = "\n".join(lines)[-8000:]
        else:
            data["log_tail"] = ""
        return data

    @mcp.tool()
    async def inspect_output_file(node_id_or_path: str, full_stats: bool = False) -> dict:
        """Inspect a node's outputs or a workspace-contained path; symlinks are resolved."""
        session, _ = await asyncio.to_thread(load_session, config.workspace)
        key = schema.node_key_by_uid(session, node_id_or_path)
        if key is not None:
            compiled = await asyncio.to_thread(compile_current, True)
            paths = [
                path
                for values in compiled.outputs.get(node_id_or_path, {}).values()
                for path in values
            ]
            if not paths:
                raise WorkstationError("节点没有输出文件")
        else:
            paths = [node_id_or_path]
        results = []
        for path in paths[:10]:
            safe = allowed_path(path, config.workspace)
            result = await asyncio.to_thread(inspect_bio_file, str(safe), full_stats=full_stats)
            results.append(result.to_dict())
        return {"files": results, "truncated": len(paths) > 10}

    return mcp


def main():
    parser = argparse.ArgumentParser(description="OpenBioWorkstation MCP stdio server")
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    create_server(load_config(args.config, workspace=args.workspace)).run(transport="stdio")


if __name__ == "__main__":
    main()
