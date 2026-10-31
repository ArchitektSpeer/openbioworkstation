"""Real Snakemake run-mode matrix: dry-run, all, step, until on a 3-tool chain."""

import json
import time
from dataclasses import replace
from pathlib import Path

from glue import session_schema as s
from glue.config import load_config
from glue.models import ExecSpec, PortSpec, ToolSpec
from glue.snakemake_bridge import RunManager, compile_session
from glue.wrapper_registry import SnakemakeWrapperAdapter, ToolRegistry

ROOT = Path(__file__).resolve().parents[1]
WS = ROOT / "validation" / "tmp-modes"


def wait(manager, run_id, timeout=90):
    deadline = time.monotonic() + timeout
    status = manager.status(run_id)
    while time.monotonic() < deadline and not status.finished:
        time.sleep(0.2)
        status = manager.status(run_id)
    return status


def make_spec(name, in_port, out_port):
    return ToolSpec(
        f"test:{name}",
        name,
        "test",
        "bioconda-auto",
        "",
        (),
        (PortSpec(in_port, ("FASTQ",)),),
        (PortSpec(out_port, ("FASTQ",)),),
        (),
        ExecSpec("shell", shell=f"cp {{input.{in_port}:q}} {{output.{out_port}:q}}"),
    )


def build():
    import shutil

    if WS.exists():
        shutil.rmtree(WS)
    WS.mkdir(parents=True)
    reads = WS / "reads.fastq"
    reads.write_text("@r\nACGT\n+\nIIII\n")
    specs = [
        make_spec("a", "reads", "draft"),
        make_spec("b", "draft", "mid"),
        make_spec("c", "mid", "final"),
    ]
    registry = ToolRegistry([SnakemakeWrapperAdapter(WS / "upstream")], WS / "cache")
    registry.build_index()

    class Adapter:
        def load_spec(self, tool_id):
            return next(spec for spec in specs if spec.tool_id == tool_id)

    for spec in specs:
        registry._owners[spec.tool_id] = Adapter()
    graph = {
        "nodes": {
            "i": s.node_entry(
                s.FASTQ_INPUT,
                "reads",
                s.input_custom_defaults(s.INPUT_KINDS[0], "aaaaaaaa") | {"path_r1": str(reads)},
            ),
            "a": s.node_entry(
                s.tool_node_type(specs[0].tool_id),
                "a",
                s.tool_custom_defaults(specs[0], "a0000001"),
            ),
            "b": s.node_entry(
                s.tool_node_type(specs[1].tool_id),
                "b",
                s.tool_custom_defaults(specs[1], "b0000001"),
            ),
            "c": s.node_entry(
                s.tool_node_type(specs[2].tool_id),
                "c",
                s.tool_custom_defaults(specs[2], "c0000001"),
            ),
            "o": s.node_entry(s.OUTPUT_NODE, "输出", s.output_custom_defaults("0000000f")),
        },
        "connections": [
            s.connection_entry("i", "reads", "a", "reads"),
            s.connection_entry("a", "draft", "b", "draft"),
            s.connection_entry("b", "mid", "c", "mid"),
            s.connection_entry("c", "final", "o", "files"),
        ],
    }
    config = replace(
        load_config(workspace=WS),
        cache_dir=WS / "cache",
        conda_prefix=WS / "envs",
        data_dir=WS / "data",
    )
    return graph, registry, config


def main():
    graph, registry, config = build()
    compiled = compile_session(graph, registry, WS)
    print("RULES", compiled.rule_of_node)
    manager = RunManager(WS, registry, config)
    draft = Path(compiled.outputs["a0000001"]["draft"][0])
    mid = Path(compiled.outputs["b0000001"]["mid"][0])
    final = Path(compiled.outputs["c0000001"]["final"][0])
    outputs = [draft, mid, final]
    print("OUTPUTS", outputs)

    dry = wait(manager, manager.start(graph, dry_run=True))
    print("DRY", dry.state, dry.node_states, "outputs_exist=", [p.exists() for p in outputs])
    assert dry.state == "success"
    assert not any(p.exists() for p in outputs), "dry-run created outputs"

    first = wait(manager, manager.start(graph))
    print("ALL", first.state, first.node_states)
    assert first.state == "success"
    assert all(p.exists() for p in outputs)
    manifest = json.loads((WS / "runs" / first.run_id / "manifest.json").read_text())
    print("PLANNED", manifest["planned_jobs"], manifest["planned_jobs_kind"])
    assert isinstance(manifest["planned_jobs"], int) and manifest["planned_jobs"] > 0
    assert manifest["planned_jobs_kind"] == "graph_rules_before_cache"
    stamps = {p.name: p.stat().st_mtime_ns for p in outputs}

    step = wait(manager, manager.start(graph, mode="step", target_uid="b0000001"))
    print("STEP", step.state, step.node_states)
    assert step.state == "success"
    assert step.node_states["a0000001"] == "skipped"
    assert step.node_states["b0000001"] == "done"
    assert step.node_states["c0000001"] == "skipped"
    assert mid.stat().st_mtime_ns != stamps[mid.name], "step target did not rerun"
    assert draft.stat().st_mtime_ns == stamps[draft.name]
    assert final.stat().st_mtime_ns == stamps[final.name]

    stamps = {p.name: p.stat().st_mtime_ns for p in outputs}
    until = wait(manager, manager.start(graph, mode="until", target_uid="b0000001"))
    print("UNTIL", until.state, until.node_states)
    assert until.state == "success"
    assert final.stat().st_mtime_ns == stamps[final.name], "downstream ran"
    runs = manager.list_runs()
    print("RUN_COUNT", len(runs), [r.state for r in runs])
    status = json.loads((WS / "runs" / until.run_id / "status.json").read_text())
    print("PERSISTED", status["state"], status["finished_at"] is not None)
    print("MODES_OK")


if __name__ == "__main__":
    main()
