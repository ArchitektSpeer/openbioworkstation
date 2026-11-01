"""Pre-warm common Bioconda CLIs through the on-demand wrapping service.

Reads tool_packs/prewarm.txt, wraps each indexed package once, records statuses,
and stops before the disk is exhausted. Requires an LLM configuration for
automatic definitions (BIOWS_LLM_BASE_URL / BIOWS_LLM_MODEL / BIOWS_LLM_API_KEY).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from glue.config import load_config  # noqa: E402
from glue.wrap_service import TERMINAL, WrapService  # noqa: E402
from glue.wrapper_registry import ToolRegistry  # noqa: E402

LIST = ROOT / "tool_packs/prewarm.txt"
REPORT = ROOT / "validation/prewarm-result.json"
SKIP = {"wrapped", "needs_review", "missing", "already_wrapped"}


def main() -> int:
    parser = argparse.ArgumentParser(description="批量预热 Bioconda 工具")
    parser.add_argument("--list", default=str(LIST))
    parser.add_argument("--report", default=str(REPORT))
    parser.add_argument("--only", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--conda", default="")
    parser.add_argument("--min-free-gb", type=float, default=25)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--retry", action="store_true")
    args = parser.parse_args()

    config = load_config()
    if args.conda:
        config = replace(config, conda_bin=args.conda)
    registry = ToolRegistry.from_config(config)
    registry.build_index()
    entries = {entry.tool_id for entry in registry._entries.values()}
    auto_packages = {
        tool_id.split("/", 1)[0].removeprefix("auto:")
        for tool_id in entries
        if tool_id.startswith("auto:")
    }
    names = [
        line.strip()
        for line in Path(args.list).read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    only = {item.strip() for item in args.only.split(",") if item.strip()}
    if only:
        names = [name for name in names if name in only]
    if args.limit:
        names = names[: args.limit]

    report_path = Path(args.report)
    try:
        report = json.loads(report_path.read_text())
    except (OSError, ValueError):
        report = {"tools": {}}
    tools = report.setdefault("tools", {})
    service = WrapService(config, registry, max_commands=1)

    for index, package in enumerate(names, 1):
        previous = tools.get(package, {}).get("status")
        if package in auto_packages:
            tools.setdefault(package, {})["status"] = "already_wrapped"
            continue
        if f"conda:{package}" not in entries:
            tools.setdefault(package, {})["status"] = "missing"
            continue
        if previous in SKIP and not args.retry:
            continue
        free = shutil.disk_usage(config.cache_dir).free
        if free < args.min_free_gb * 2**30:
            tools[package] = {"status": "stopped_low_disk", "message": f"剩余 {free / 2**30:.1f} GB"}
            break
        started = time.monotonic()
        job = service.submit(f"conda:{package}")
        deadline = time.monotonic() + args.timeout
        state = service.job(job["job_id"])
        while time.monotonic() < deadline and state["status"] not in TERMINAL:
            time.sleep(3)
            state = service.job(job["job_id"])
        tools[package] = {
            "status": state["status"],
            "message": state["message"][:300],
            "tool_ids": state["tool_ids"],
            "seconds": round(time.monotonic() - started, 1),
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(
            f"[{index}/{len(names)}] {package}: {tools[package]['status']} "
            f"{tools[package]['seconds']}s {tools[package]['message'][:100]}",
            flush=True,
        )

    registry.build_index()
    counts = {}
    for item in tools.values():
        counts[item.get("status", "unknown")] = counts.get(item.get("status", "unknown"), 0) + 1
    print("prewarm:", json.dumps(counts, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
