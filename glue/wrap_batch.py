"""Batch-wrap curated Bioconda CLIs from a manifest into auto: tool definitions."""

import argparse
import json
import subprocess
import tempfile
import time
from dataclasses import replace
from pathlib import Path

import yaml

from glue.config import load_config
from glue.session_store import atomic_json
from glue.wrapper_registry import BiocondaAutoWrapAdapter, ToolRegistry


def load_manifest(path):
    data = yaml.safe_load(Path(path).read_text()) or {}
    if not isinstance(data, dict) or not isinstance(data.get("tools"), list):
        raise SystemExit("清单格式必须为 {tools: [...]}")
    return data


def liveness(conda, environment, command, timeout=60):
    with tempfile.TemporaryDirectory(prefix="biows-liveness-") as scratch:
        for args in (["--version"], ["--help"], []):
            process = subprocess.run(
                [conda, "run", "-p", str(environment), command, *args],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=scratch,
            )
            output = (process.stdout + process.stderr).strip()
            if output:
                return {"args": args, "returncode": process.returncode, "output": output[:400]}
    return {"args": [], "returncode": None, "output": ""}


def main(argv=None):
    parser = argparse.ArgumentParser(description="批量封装 Bioconda 工具")
    parser.add_argument("--manifest", default="tool_packs/top50.yaml")
    parser.add_argument("--only", default="", help="逗号分隔的 package 或 package/command")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--conda", default="")
    parser.add_argument("--report", default="validation/wrap-batch-result.json")
    args = parser.parse_args(argv)

    config = load_config()
    if args.conda:
        config = replace(config, conda_bin=args.conda)
    entries = load_manifest(args.manifest)["tools"]
    only = {item.strip() for item in args.only.split(",") if item.strip()}
    if only:
        entries = [
            entry
            for entry in entries
            if entry["package"] in only or f"{entry['package']}/{entry['command']}" in only
        ]
    if args.limit:
        entries = entries[: args.limit]

    adapter = BiocondaAutoWrapAdapter(
        config.upstream_dir / "bioconda-recipes",
        config.data_dir / "auto_wrapped",
        config.conda_prefix,
        config.conda_bin,
    )
    conda = adapter._conda()
    results = []
    for entry in entries:
        package, command = entry["package"], entry["command"]
        binary = entry.get("binary")
        started = time.monotonic()
        record = {"package": package, "command": command, "status": "failed"}
        try:
            prepared = adapter.prepare(package, command, binary)
            record.update(version=prepared["version"], environment=prepared["environment"])
            definition = entry.get("definition")
            if definition is None:
                record["status"] = "needs_definition"
            else:
                spec = adapter.store_definition(
                    package,
                    command,
                    yaml.safe_dump(definition, allow_unicode=True),
                    prepared["version"],
                )
                record.update(
                    tool_id=spec.tool_id,
                    inputs=[p.name for p in spec.inputs],
                    outputs=[p.name for p in spec.outputs],
                    smoke=liveness(conda, prepared["environment"], binary or command),
                )
                record["status"] = "wrapped"
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
        record["seconds"] = round(time.monotonic() - started, 1)
        results.append(record)
        print(json.dumps(record, ensure_ascii=False), flush=True)
        atomic_json(Path(args.report), {"tools": results})

    ToolRegistry.from_config(config).build_index(refresh=True)
    print(f"完成 {len(results)} 项；报告：{args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
