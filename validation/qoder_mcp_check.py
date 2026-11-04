"""Opt-in live Qoder inference against MCP; records wire calls and checks artifacts.

Never run by CI: this invokes a real authenticated model and needs local SeqKit.
The model gets MCP tools only; verification does not build or edit its graph.
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import threading
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TOOLS = (
    "get_workflow",
    "get_tool_schema",
    "search_bio_tools",
    "add_node",
    "update_node",
    "connect_nodes",
    "disconnect_nodes",
    "remove_node",
    "compile_and_run_async",
    "get_run_status",
    "inspect_output_file",
    "list_runs",
    "get_run_snapshot",
    "cancel_run",
)
REQUIRED = {
    "get_workflow",
    "get_tool_schema",
    "search_bio_tools",
    "add_node",
    "update_node",
    "connect_nodes",
    "compile_and_run_async",
    "get_run_status",
    "inspect_output_file",
    "list_runs",
    "get_run_snapshot",
}


def proxy(config_path, audit_path):
    """Transparent stdio relay: the real server receives the model's wire requests."""
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    with (
        audit_path.open("a", buffering=1) as audit,
        audit_path.with_suffix(".stderr.log").open("a") as stderr,
    ):
        process = subprocess.Popen(
            [sys.executable, "-m", "mcp_server.bio_mcp", "--config", str(config_path)],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            env={**os.environ, "PYTHONPATH": str(ROOT)},
        )

        def record(direction, line):
            try:
                message = json.loads(line)
            except ValueError:
                message = {"invalid_json": line.decode(errors="replace")}
            with lock:
                audit.write(
                    json.dumps(
                        {
                            "at": datetime.now(UTC).isoformat(),
                            "direction": direction,
                            "message": message,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

        def forward_input():
            try:
                for line in sys.stdin.buffer:
                    record("request", line)
                    process.stdin.write(line)
                    process.stdin.flush()
            except BrokenPipeError:
                pass
            finally:
                process.stdin.close()

        threading.Thread(target=forward_input, daemon=True).start()
        try:
            for line in process.stdout:
                record("response", line)
                sys.stdout.buffer.write(line)
                sys.stdout.buffer.flush()
        except BrokenPipeError:
            pass
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def verify(output):
    from glue.config import load_config
    from glue.session_store import load_session
    from glue.snakemake_bridge import RunManager
    from glue.wrapper_registry import ToolRegistry

    events = [json.loads(line) for line in (output / "wire.jsonl").read_text().splitlines()]
    requests = [
        e["message"]
        for e in events
        if e["direction"] == "request" and e["message"].get("method") == "tools/call"
    ]
    counts = Counter(e["params"]["name"] for e in requests)
    missing = REQUIRED - counts.keys()
    if missing:
        raise AssertionError(f"Missing actual model MCP calls: {sorted(missing)}")
    forbidden = counts.keys() - set(TOOLS)
    if forbidden:
        raise AssertionError(f"Unexpected tool requests: {sorted(forbidden)}")
    responses = {
        e["message"]["id"]: e["message"]
        for e in events
        if e["direction"] == "response" and "id" in e["message"]
    }
    successful = Counter()
    errors = []
    for request in requests:
        response = responses.get(request["id"], {})
        if "error" in response or not response.get("result") or response["result"].get("isError"):
            errors.append({"tool": request["params"]["name"], "id": request["id"]})
        else:
            successful[request["params"]["name"]] += 1
    if REQUIRED - successful.keys():
        raise AssertionError(
            f"Missing successful actual model calls: {sorted(REQUIRED - successful.keys())}"
        )
    workspace = output / "workspace"
    session, revision = load_session(workspace)
    if len(session["nodes"]) != 3 or len(session["connections"]) != 2:
        raise AssertionError("Expected the model to create three nodes and two connections")
    tool = next(
        n
        for n in session["nodes"].values()
        if n.get("custom", {}).get("tool_id") == "local:seqkit/stats"
    )
    if tool["custom"]["threads"] != "2":
        raise AssertionError("Model did not persist the requested thread configuration")
    config = load_config(output / "biows.yaml")
    manager = RunManager(workspace, ToolRegistry.from_config(config), config)
    runs = manager.list_runs()
    dry = [r for r in runs if r.dry_run and r.state == "success"]
    real = [r for r in runs if not r.dry_run and r.state == "success"]
    if len(dry) != 1 or len(real) != 1:
        raise AssertionError("Expected one successful dry-run and one successful real run")
    report = Path(manager.output_paths(real[0].run_id, tool["custom"]["bio_uid"])[0])
    with report.open() as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    if len(rows) != 1 or int(rows[0]["num_seqs"]) != 2 or int(rows[0]["sum_len"]) != 8:
        raise AssertionError(f"Unexpected actual SeqKit statistics: {rows}")
    return {
        "verified": True,
        "model_mcp_calls": dict(counts),
        "successful_mcp_calls": dict(successful),
        "recovered_tool_errors": errors,
        "revision": revision,
        "nodes": 3,
        "connections": 2,
        "dry_run_id": dry[0].run_id,
        "run_id": real[0].run_id,
        "report_path": str(report),
        "num_seqs": 2,
        "sum_len": 8,
    }


def run_live(output, model, timeout):
    from software_factory.adapters import run_process
    from software_factory.storage import Store

    if output.exists():
        raise RuntimeError("Choose a fresh output directory; existing evidence is preserved")
    output.mkdir(parents=True)
    workspace = output / "workspace"
    (workspace / "inputs").mkdir(parents=True)
    reads = workspace / "inputs/reads.fastq"
    reads.write_text("@r1\nACGT\n+\nIIII\n@r2\nTGCA\n+\nIIII\n")
    config = {
        "workspace": str(workspace),
        "data_dir": str(output / "data"),
        "cache_dir": str(output / "cache"),
        "upstream_dir": str(output / "upstream"),
        "cores": 2,
        "allow_unreviewed": False,
    }
    (output / "biows.yaml").write_text(yaml.safe_dump(config))
    mcp = {
        "mcpServers": {
            "openbioworkstation": {
                "command": sys.executable,
                "args": [
                    "-m",
                    "validation.qoder_mcp_check",
                    "--serve",
                    "--config",
                    str(output / "biows.yaml"),
                    "--audit",
                    str(output / "wire.jsonl"),
                ],
                "cwd": str(ROOT),
                "env": {"PYTHONPATH": str(ROOT)},
                "alwaysAllow": list(TOOLS),
            }
        }
    }
    (output / "mcp.json").write_text(json.dumps(mcp, indent=2))
    prompt = (
        f"Use only the openbioworkstation MCP server for a real analysis task. Built-in tools are disabled. "
        f"The workspace is {workspace}; the existing input is {reads}. "
        "Read the saved workflow first, discover SeqKit stats and its tool schema, then create "
        "FASTQ input -> local:seqkit/stats -> output. Use stable node IDs and ports from actual tool results. "
        "Use update_node to set the tool threads to 2 and its name to Qoder SeqKit live, using a current revision. "
        "Run a dry-run and poll it to success, then a real run with cores=2 and poll it to success. "
        "Inspect the real output with its run_id, check num_seqs=2 and sum_len=8. "
        "Use list_runs and get_run_snapshot to verify the execution configuration, and get_workflow again to verify saved edits. "
        "Do not install packages, wrap tools, alter inputs or use shell/file tools. Do not claim completion before successful real execution. "
        "Return a short summary with actual run IDs, node IDs and observed statistics."
    )
    argv = [
        "qodercn",
        "--model",
        model,
        "--output-format",
        "stream-json",
        "--no-session-persistence",
        "--strict-mcp-config",
        "--mcp-config",
        str(output / "mcp.json"),
        "--allowed-mcp-server-names",
        "openbioworkstation",
        "--tools",
        "",
        "--permission-mode",
        "dont_ask",
        "--allowed-tools",
        ",".join(f"mcp__openbioworkstation__{name}" for name in TOOLS),
        "--max-model-request-retries",
        "0",
        "-p",
        prompt,
    ]
    store = Store(ROOT / ".factory/state.sqlite3")
    task_id = output.name
    store.create(task_id)
    policy = yaml.safe_load((ROOT / "config/factory-routes.yaml").read_text())
    call_id = None
    base = {
        "requested_model": model,
        "actual_model": None,
        "cli_status": "not_started",
        "output_dir": str(output),
    }
    try:
        call_id = store.reserve_call(task_id, "mcp_live", "qodercn", model, policy)
        store.update(task_id, state="running", stage="mcp_live")
        result = run_process(argv, ROOT, timeout, output / "qoder")
        final = None
        for line in result.stdout.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") == "result":
                final = event
        status = (
            "timeout"
            if result.timed_out
            else "success"
            if result.returncode == 0 and final and not final.get("is_error")
            else "failed"
        )
        store.finish_call(
            call_id,
            status,
            final.get("total_cost_usd") if final else None,
            {"log_dir": str(output), "duration": result.duration, "requested_model": model},
        )
        call_id = None
        base.update(cli_status=status, duration=result.duration)
        if status != "success":
            raise RuntimeError(f"Qoder returned {status}; inspect raw logs")
        report = {**base, **verify(output)}
        store.update(
            task_id,
            state="verified",
            detail="Real MCP wire calls, saved graph and SeqKit output verified",
        )
    except Exception as exc:
        if call_id is not None:
            store.finish_call(call_id, "failed", None, {"error": str(exc), "log_dir": str(output)})
        cleanup = []
        try:
            from glue.config import load_config
            from glue.snakemake_bridge import RunManager
            from glue.wrapper_registry import ToolRegistry

            cfg = load_config(output / "biows.yaml")
            manager = RunManager(workspace, ToolRegistry.from_config(cfg), cfg)
            for run in manager.list_runs():
                if not run.finished:
                    cleanup.append(
                        {"run_id": run.run_id, "cancel_requested": manager.cancel(run.run_id)}
                    )
            deadline = time.monotonic() + 25
            for item in cleanup:
                while time.monotonic() < deadline and not manager.status(item["run_id"]).finished:
                    time.sleep(0.2)
                item["final_state"] = manager.status(item["run_id"]).state
        except Exception as cleanup_error:
            cleanup.append({"error": str(cleanup_error)})
        report = {**base, "verified": False, "error": str(exc), "cleanup": cleanup}
        store.update(task_id, state="failed", detail=str(exc))
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        raise
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--audit", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model", default="Qwen3.8-Flash")
    parser.add_argument("--timeout", type=int, default=480)
    args = parser.parse_args()
    if args.serve:
        proxy(args.config, args.audit)
    else:
        output = args.output or ROOT / ".factory/mcp-live" / datetime.now(UTC).strftime(
            "qoder-mcp-%Y%m%dT%H%M%S"
        )
        run_live(output.resolve(), args.model, args.timeout)


if __name__ == "__main__":
    main()
