"""Reproduce the tutorial's MCP calls against a fresh synthetic-data workspace."""

import argparse
import asyncio
import csv
import json
import os
import sys
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def exercise(workspace):
    workspace.mkdir(parents=True, exist_ok=True)
    if (workspace / "session.json").exists() or (workspace / "inputs/reads.fastq").exists():
        raise RuntimeError("Choose a fresh workspace; existing inputs and graphs are preserved.")
    inputs = workspace / "inputs"
    inputs.mkdir(exist_ok=True)
    reads = inputs / "reads.fastq"
    reads.write_text("@r1\nACGT\n+\nIIII\n@r2\nTGCA\n+\nIIII\n")
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server.bio_mcp", "--workspace", str(workspace)],
        cwd=str(ROOT),
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as client,
    ):
        await client.initialize()

        async def call(name, **arguments):
            result = await client.call_tool(name, arguments)
            if result.isError:
                raise RuntimeError(str(result.content))
            data = getattr(result, "structuredContent", None)
            if data is None:
                data = json.loads(result.content[0].text)
            print(json.dumps({"tool": name, "result": data}, ensure_ascii=False), flush=True)
            return data

        async def wait(run_id):
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                status = await call("get_run_status", run_id=run_id, log_tail=8)
                if status["state"] in ("success", "failed", "cancelled"):
                    if status["state"] != "success":
                        raise RuntimeError(f"Run did not succeed: {status}")
                    return
                await asyncio.sleep(1)
            raise TimeoutError(f"Run {run_id} exceeded tutorial wait; inspect its saved status.")

        found = await call("search_bio_tools", query="seqkit", limit=10)
        if not any(item["tool_id"] == "local:seqkit/stats" for item in found["items"]):
            raise RuntimeError(
                "Install SeqKit in BIOWS_COMMON_ENV or the default common-tools prefix."
            )
        source = await call(
            "add_node", tool_id_or_kind="fastq_input", properties={"path_r1": str(reads)}
        )
        tool = await call("add_node", tool_id_or_kind="local:seqkit/stats")
        output = await call("add_node", tool_id_or_kind="output")
        for src, src_port, dst, dst_port in (
            (source, "reads", tool, "reads"),
            (tool, "stats", output, "files"),
        ):
            result = await call(
                "connect_nodes",
                from_node=src["node_id"],
                from_port=src_port,
                to_node=dst["node_id"],
                to_port=dst_port,
            )
            if not result["ok"]:
                raise RuntimeError(str(result))
        for dry_run in (True, False):
            run = await call("compile_and_run_async", mode="all", cores=2, dry_run=dry_run)
            await wait(run["run_id"])
        inspected = await call("inspect_output_file", node_id_or_path=tool["node_id"])
        # Resolve paths from the same compiler used by MCP; no output names are guessed.
        from glue.config import load_config
        from glue.session_store import load_session
        from glue.snakemake_bridge import compile_session
        from glue.wrapper_registry import ToolRegistry

        config = load_config(workspace=workspace)
        registry = ToolRegistry.from_config(config)
        session, _ = load_session(workspace)
        compiled = compile_session(session, registry, workspace)
        report = Path(compiled.outputs[tool["node_id"]]["stats"][0])
        with report.open() as stream:
            rows = list(csv.DictReader(stream, delimiter="\t"))
        if len(rows) != 1 or int(rows[0]["num_seqs"]) != 2 or int(rows[0]["sum_len"]) != 8:
            raise RuntimeError(f"Unexpected synthetic statistics: {rows}")
        print(
            json.dumps(
                {"verified": True, "report": str(report), "preview": inspected}, ensure_ascii=False
            ),
            flush=True,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(exercise(args.workspace.expanduser().resolve()))


if __name__ == "__main__":
    main()
