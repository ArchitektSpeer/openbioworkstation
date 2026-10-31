"""Cancel a genuinely running Snakemake job, then verify no process survives."""

import os
import sys
import time
from dataclasses import replace
from pathlib import Path

from glue import session_schema as s
from glue.config import load_config
from glue.errors import RunBusyError
from glue.models import ExecSpec, PortSpec, ToolSpec
from glue.snakemake_bridge import RunManager
from glue.wrapper_registry import SnakemakeWrapperAdapter, ToolRegistry

ROOT = Path(__file__).resolve().parents[1]
WS = ROOT / "validation" / "tmp-cancel"


def build():
    ws = WS
    ws.mkdir(parents=True, exist_ok=True)
    reads = ws / "reads.fastq"
    reads.write_text("@r\nACGT\n+\nIIII\n")
    pidfile = ws / "job.pid"
    for stale in (pidfile, "runs", "reads.fastq"):
        target = ws / stale
        if target.is_dir():
            import shutil

            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
    reads.write_text("@r\nACGT\n+\nIIII\n")
    spec = ToolSpec(
        "test:sleep",
        "sleep",
        "test",
        "bioconda-auto",
        "",
        (),
        (PortSpec("reads", ("FASTQ",)),),
        (PortSpec("report", ("TEXT",)),),
        (),
        ExecSpec(
            "shell",
            shell=(
                f'{sys.executable} -c "import os, time; '
                f"open('{pidfile}', 'w').write(str(os.getpid())); time.sleep(300)\""
            ),
        ),
    )
    registry = ToolRegistry([SnakemakeWrapperAdapter(ws / "upstream")], ws / "cache")
    registry.build_index()

    class Adapter:
        def load_spec(self, tool_id):
            return spec

    registry._owners[spec.tool_id] = Adapter()
    graph = {
        "nodes": {
            "i": s.node_entry(
                s.FASTQ_INPUT,
                "reads",
                s.input_custom_defaults(s.INPUT_KINDS[0], "aaaaaaaa") | {"path_r1": str(reads)},
            ),
            "t": s.node_entry(
                s.tool_node_type(spec.tool_id), "sleep", s.tool_custom_defaults(spec, "bbbbbbbb")
            ),
        },
        "connections": [s.connection_entry("i", "reads", "t", "reads")],
    }
    config = replace(
        load_config(workspace=ws),
        cache_dir=ws / "cache",
        conda_prefix=ws / "envs",
        data_dir=ws / "data",
    )
    return graph, registry, config, pidfile


def main():
    graph, registry, config, pidfile = build()
    manager = RunManager(WS, registry, config)
    run_id = manager.start(graph)
    try:
        manager.start(graph)
    except RunBusyError:
        print("BUSY_MUTEX_OK")
    else:
        raise AssertionError("second concurrent start was accepted")

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and not pidfile.exists():
        time.sleep(0.2)
    assert pidfile.exists(), "job never started"
    pid = int(pidfile.read_text().strip())
    print("RUNNING_PID", pid, "state=", manager.status(run_id).state)
    assert manager.cancel(run_id) is True

    deadline = time.monotonic() + 30
    status = manager.status(run_id)
    while time.monotonic() < deadline and not status.finished:
        time.sleep(0.2)
        status = manager.status(run_id)
    print("CANCELLED_STATE", status.state, "returncode=", status.returncode)
    assert status.state == "cancelled", status.to_dict()

    time.sleep(1)
    alive = True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        alive = False
    print("JOB_PROCESS_ALIVE", alive)
    assert not alive, f"job process {pid} survived cancellation"

    restarted = manager.start(graph)
    time.sleep(1)
    manager.cancel(restarted)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        final = manager.status(restarted)
        if final.finished:
            break
        time.sleep(0.2)
    print("RESTART_AFTER_CANCEL", final.state)
    assert final.finished
    print("CANCEL_OK")


if __name__ == "__main__":
    main()
