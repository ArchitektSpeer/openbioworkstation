"""End-to-end MCP stdio check: real subprocess, workflow editing tools, real Snakemake dry-run."""

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


def params(workspace):
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server.bio_mcp", "--workspace", str(workspace)],
        cwd=str(ROOT),
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )


def payload(result):
    if getattr(result, "structuredContent", None):
        return result.structuredContent
    if getattr(result, "isError", False):
        raise RuntimeError(result.content[0].text)
    return json.loads(result.content[0].text)


async def registration_and_graph(workspace):
    async with (
        stdio_client(params(workspace)) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        tools = sorted(t.name for t in (await session.list_tools()).tools)
        print("TOOLS", tools)
        assert {
            "get_workflow",
            "get_tool_schema",
            "update_node",
            "remove_node",
            "disconnect_nodes",
            "cancel_run",
            "list_runs",
            "get_run_snapshot",
            "add_node",
            "connect_nodes",
            "compile_and_run_async",
            "get_run_status",
            "inspect_output_file",
            "wrap_tool",
            "get_wrap_job",
        } <= set(tools), tools

        found = payload(await session.call_tool("search_bio_tools", {"query": "fastp"}))
        print("SEARCH", found["total"], found["items"][0]["tool_id"])
        assert found["total"] >= 1

        reads = workspace / "reads.fastq"
        reads.write_text("@r\nACGT\n+\nIIII\n")
        src = payload(
            await session.call_tool(
                "add_node",
                {"tool_id_or_kind": "fastq_input", "properties": {"path_r1": str(reads)}},
            )
        )
        print("ADD_INPUT", src["node_id"], src["inspect"][0]["format"])
        assert src["inspect"][0]["valid"] is True

        tool = payload(await session.call_tool("add_node", {"tool_id_or_kind": "smk:bio/fastp"}))
        dst = payload(await session.call_tool("add_node", {"tool_id_or_kind": "output"}))
        linked = payload(
            await session.call_tool(
                "connect_nodes",
                {
                    "from_node": src["node_id"],
                    "from_port": "reads",
                    "to_node": tool["node_id"],
                    "to_port": "sample",
                },
            )
        )
        linked2 = payload(
            await session.call_tool(
                "connect_nodes",
                {
                    "from_node": tool["node_id"],
                    "from_port": "trimmed",
                    "to_node": dst["node_id"],
                    "to_port": "files",
                },
            )
        )
        current = payload(await session.call_tool("get_workflow", {}))
        assert len(current["nodes"]) == 3
        schema = payload(await session.call_tool("get_tool_schema", {"tool_id": "smk:bio/fastp"}))
        assert "threads" in schema["properties"]
        changed = payload(
            await session.call_tool(
                "update_node",
                {
                    "node_id": tool["node_id"],
                    "properties": {"threads": 2},
                    "expected_revision": current["revision"],
                },
            )
        )
        assert changed["revision"] > current["revision"]
        stale = await session.call_tool(
            "update_node",
            {
                "node_id": tool["node_id"],
                "properties": {"threads": 3},
                "expected_revision": current["revision"],
            },
        )
        assert stale.isError
        payload(
            await session.call_tool(
                "disconnect_nodes",
                {
                    "from_node": tool["node_id"],
                    "from_port": "trimmed",
                    "to_node": dst["node_id"],
                    "to_port": "files",
                },
            )
        )
        assert len(payload(await session.call_tool("get_workflow", {}))["connections"]) == 1
        payload(await session.call_tool("remove_node", {"node_id": dst["node_id"]}))
        assert len(payload(await session.call_tool("get_workflow", {}))["nodes"]) == 2
        print("EDIT_RECOVERY_OK")
        print("CONNECT", linked, linked2)
        assert linked["ok"] and linked2["ok"]

        bam = payload(await session.call_tool("add_node", {"tool_id_or_kind": "bam_input"}))
        rejected = payload(
            await session.call_tool(
                "connect_nodes",
                {
                    "from_node": bam["node_id"],
                    "from_port": "bam",
                    "to_node": tool["node_id"],
                    "to_port": "sample",
                },
            )
        )
        print("REJECT_BAM_TO_FASTQ", rejected)
        assert rejected["ok"] is False

        inspected = payload(
            await session.call_tool("inspect_output_file", {"node_id_or_path": str(reads)})
        )
        print("INSPECT_PATH", inspected["files"][0]["format"], inspected["files"][0]["valid"])
        assert inspected["files"][0]["valid"] is True

        try:
            payload(
                await session.call_tool(
                    "auto_wrap_bioconda_pkg", {"pkg_name": "pkg;rm", "cli_cmd": "cmd"}
                )
            )
        except Exception as exc:
            print("AUTO_WRAP_REJECT", type(exc).__name__, str(exc)[:120])
        else:
            raise AssertionError("auto_wrap accepted an invalid package name")


async def run_flow(workspace):
    reads = workspace / "reads.fastq"
    reads.write_text("@r\nACGT\n+\nIIII\n")
    async with (
        stdio_client(params(workspace)) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        src = payload(
            await session.call_tool(
                "add_node",
                {"tool_id_or_kind": "fastq_input", "properties": {"path_r1": str(reads)}},
            )
        )
        dst = payload(await session.call_tool("add_node", {"tool_id_or_kind": "output"}))
        linked = payload(
            await session.call_tool(
                "connect_nodes",
                {
                    "from_node": src["node_id"],
                    "from_port": "reads",
                    "to_node": dst["node_id"],
                    "to_port": "files",
                },
            )
        )
        print("RUN_CONNECT", linked)
        assert linked["ok"] is True

        run = payload(
            await session.call_tool("compile_and_run_async", {"mode": "all", "dry_run": True})
        )
        snapshot = payload(await session.call_tool("get_run_snapshot", {"run_id": run["run_id"]}))
        assert snapshot["status"]["dry_run"] is True
        history = payload(await session.call_tool("list_runs", {}))
        assert run["run_id"] in {item["run_id"] for item in history["runs"]}
        print("RUN", run["run_id"], run["warnings"], "planned_jobs=", run["planned_jobs"])

        state = None
        for _ in range(300):
            state = payload(await session.call_tool("get_run_status", {"run_id": run["run_id"]}))
            if state["state"] in ("success", "failed", "cancelled"):
                break
            await asyncio.sleep(0.2)
        print("STATE", state["state"], "returncode=", state["returncode"])
        assert state["state"] == "success", json.dumps(state, ensure_ascii=False)


async def main():
    root = ROOT / "validation"
    import tempfile

    with tempfile.TemporaryDirectory(prefix="tmp-mcp-", dir=root) as temporary:
        first, second = Path(temporary) / "a", Path(temporary) / "b"
        first.mkdir()
        second.mkdir()
        await registration_and_graph(first)
        await run_flow(second)
    print("MCP_STDIO_OK")


if __name__ == "__main__":
    asyncio.run(main())
    sys.exit(0)
