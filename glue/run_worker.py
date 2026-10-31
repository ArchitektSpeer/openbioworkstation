"""Detached run supervisor. The CLI, rather than a UI thread, owns durable state."""

import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from glue.models import RunStatus
from glue.session_store import atomic_json
from glue.snakemake_bridge import _now, parse_log_line


def main(directory):
    directory = Path(directory)
    for _ in range(200):
        if (directory / "ready").exists():
            break
        time.sleep(0.05)
    else:
        return 1
    status = RunStatus.from_dict(json.loads((directory / "status.json").read_text()))
    manifest = json.loads((directory / "manifest.json").read_text())
    jobs = {}
    process = None
    try:
        with (directory / "snakemake.log").open("a", buffering=1) as log:
            process = subprocess.Popen(
                manifest["command"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                start_new_session=True,
            )

            def cancel_watch():
                while process.poll() is None:
                    if (directory / "cancel").exists():
                        for sig, wait in (
                            (signal.SIGINT, 10),
                            (signal.SIGTERM, 5),
                            (signal.SIGKILL, 0),
                        ):
                            try:
                                os.killpg(process.pid, sig)
                            except ProcessLookupError:
                                return
                            try:
                                process.wait(timeout=wait)
                                return
                            except subprocess.TimeoutExpired:
                                pass
                        return
                    time.sleep(0.2)

            threading.Thread(target=cancel_watch, daemon=True).start()
            for line in process.stdout:
                log.write(line)
                parse_log_line(line, status, manifest["node_of_rule"], jobs)
                atomic_json(directory / "status.json", status.to_dict())
            status.returncode = process.wait()
            status.state = (
                "cancelled"
                if (directory / "cancel").exists()
                else "success"
                if status.returncode == 0
                else "failed"
            )
    except Exception as exc:
        with (directory / "snakemake.log").open("a") as log:
            log.write(f"运行监督器错误：{exc}\n")
        status.state = "failed"
        if process and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait()
    if status.state == "success":
        for uid, state in status.node_states.items():
            paths = [p for values in manifest["outputs"].get(uid, {}).values() for p in values]
            status.node_states[uid] = (
                "done"
                if not status.dry_run
                and state in ("running", "done")
                and paths
                and all(Path(p).exists() for p in paths)
                else "skipped"
            )
    elif status.state == "failed":
        for uid, state in status.node_states.items():
            if state == "running":
                status.node_states[uid] = "failed"
    status.finished_at = _now()
    atomic_json(directory / "status.json", status.to_dict())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
