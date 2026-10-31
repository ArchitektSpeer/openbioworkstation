import json
import time
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from glue import session_schema as s
from glue.bio_inspector import inspect_bio_file
from glue.config import allowed_path, load_config
from glue.errors import (
    CompileError,
    InvalidToolDefinitionError,
    PathNotAllowedError,
    SessionConflictError,
)
from glue.formats import formats_compatible, infer_formats
from glue.models import ExecSpec, PortSpec, RunStatus, ToolSpec
from glue.session_store import load_session, save_session
from glue.snakemake_bridge import RunManager, compile_session, parse_log_line
from glue.wrapper_registry import BiocondaAutoWrapAdapter, SnakemakeWrapperAdapter, ToolRegistry


@pytest.fixture
def registry(tmp_path):
    return ToolRegistry([SnakemakeWrapperAdapter(tmp_path / "upstream")], tmp_path / "cache")


def config(tmp_path):
    return replace(
        load_config(workspace=tmp_path),
        cache_dir=tmp_path / "cache",
        conda_prefix=tmp_path / "envs",
        data_dir=tmp_path / "data",
    )


def shell_graph(tmp_path, registry, shell="cp {input.reads:q} {output.report:q}"):
    spec = ToolSpec(
        "test:copy",
        "copy",
        "test",
        "bioconda-auto",
        "",
        (),
        (PortSpec("reads", ("FASTQ",)),),
        (PortSpec("report", ("TEXT",)),),
        (),
        ExecSpec("shell", shell=shell),
    )
    registry.build_index()

    class Adapter:
        def load_spec(self, tool_id):
            return spec

    registry._owners[spec.tool_id] = Adapter()
    path = tmp_path / "reads.fastq"
    path.write_text("@r\nACGT\n+\nIIII\n")
    return {
        "nodes": {
            "i": s.node_entry(
                s.FASTQ_INPUT,
                "reads",
                s.input_custom_defaults(s.INPUT_KINDS[0], "aaaaaaaa") | {"path_r1": str(path)},
            ),
            "t": s.node_entry(
                s.tool_node_type(spec.tool_id), "copy", s.tool_custom_defaults(spec, "bbbbbbbb")
            ),
        },
        "connections": [s.connection_entry("i", "reads", "t", "reads")],
    }


def chain_graph(tmp_path, registry):
    specs = [
        ToolSpec(
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
        for name, in_port, out_port in (
            ("a", "reads", "draft"),
            ("b", "draft", "mid"),
            ("c", "mid", "final"),
        )
    ]
    registry.build_index()

    class Adapter:
        def load_spec(self, tool_id):
            return next(spec for spec in specs if spec.tool_id == tool_id)

    for spec in specs:
        registry._owners[spec.tool_id] = Adapter()
    path = tmp_path / "reads.fastq"
    path.write_text("@r\nACGT\n+\nIIII\n")
    graph = {
        "nodes": {
            "i": s.node_entry(
                s.FASTQ_INPUT,
                "reads",
                s.input_custom_defaults(s.INPUT_KINDS[0], "aaaaaaaa") | {"path_r1": str(path)},
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
    return graph


def wait(manager, run_id, timeout=60):
    deadline = time.monotonic() + timeout
    status = manager.status(run_id)
    while time.monotonic() < deadline and not status.finished:
        time.sleep(0.2)
        status = manager.status(run_id)
    return status


def test_formats():
    assert infer_formats("*.{bam,cram}") == ("BAM", "CRAM")
    assert not formats_compatible(("BAM",), ("SAM",))[0]
    assert formats_compatible(("BAM",), ("ALIGNMENT",))[0]


def test_session_conflicts(tmp_path):
    session, revision = load_session(tmp_path)
    assert save_session(tmp_path, session, revision) == 1
    with pytest.raises(SessionConflictError):
        save_session(tmp_path, session, revision)
    assert load_session(tmp_path)[1] == 1


def test_path_symlink(tmp_path):
    (tmp_path / "link").symlink_to("/etc")
    with pytest.raises(PathNotAllowedError):
        allowed_path("link/passwd", tmp_path)


def test_registry(registry):
    assert registry.search("fastp", input_format="FASTQ").total == 1
    assert registry.search(limit=500).total == 5
    assert registry.get("smk:bio/bwa/index").outputs[0].formats == ("BWA_INDEX",)


def test_compile_and_cycle(tmp_path, registry):
    graph = shell_graph(tmp_path, registry)
    result = compile_session(graph, registry, tmp_path)
    assert "rule n_copy_bbbbbbbb:" in result.snakefile_text
    assert str(tmp_path / "reads.fastq") in result.snakefile_text
    graph["connections"].append(s.connection_entry("t", "report", "t", "reads"))
    with pytest.raises(CompileError):
        compile_session(graph, registry, tmp_path)


def test_inspect(tmp_path):
    file = tmp_path / "reads.fastq"
    file.write_text("@r\nACGT\n+\nIIII\n")
    quick = inspect_bio_file(str(file))
    assert quick.valid and quick.stats["sampled_records"] == 1
    assert inspect_bio_file(str(file), full_stats=True).stats["records"] == 1
    assert not inspect_bio_file(str(tmp_path / "missing.fastq")).valid
    assert not list(tmp_path.glob("*.fxi"))


def test_definition_validation(tmp_path):
    adapter = BiocondaAutoWrapAdapter(tmp_path, tmp_path / "wrapped", tmp_path / "envs")
    with pytest.raises(InvalidToolDefinitionError):
        adapter.location("pkg;rm", "cmd")
    with pytest.raises(InvalidToolDefinitionError):
        adapter.store_definition(
            "pkg",
            "cmd",
            """biows:
  inputs: {reads: {formats: [FASTQ]}}
  outputs: {report: {formats: [TEXT]}}
  shell: "cmd {input.__class__}"
""",
            "1.0",
        )


def test_bioconda_channeldata_index(tmp_path):
    root = tmp_path / "bioconda"
    root.mkdir()
    (root / "channeldata.json").write_text(
        json.dumps({"packages": {"fastqc": {"summary": "Quality control"}, "bwa": {}}}),
        encoding="utf-8",
    )
    adapter = BiocondaAutoWrapAdapter(root, tmp_path / "wrapped", tmp_path / "envs")
    entries = {entry.tool_id: entry for entry in adapter.iter_index()}
    assert entries["conda:fastqc"].summary == "Quality control"
    assert entries["conda:bwa"].wrapped is False
    assert entries["conda:bwa"].reviewed is False
    registry = ToolRegistry([adapter], tmp_path / "cache")
    assert registry.search("fastqc").total == 1


def test_mark_reviewed_upstream(tmp_path):
    tool = tmp_path / "upstream" / "bio" / "demo"
    tool.mkdir(parents=True)
    (tool / "meta.yaml").write_text("name: demo\ninput:\n  - reads\noutput:\n  - out\n")
    (tool / "wrapper.py").write_text("")
    reviewed = tmp_path / "reviewed.json"
    registry = ToolRegistry(
        [SnakemakeWrapperAdapter(tmp_path / "upstream")], tmp_path / "cache", reviewed
    )
    registry.build_index(refresh=True)
    tool_id = "smk:bio/demo"
    assert registry.get(tool_id).reviewed is False
    registry.mark_reviewed(tool_id)
    assert registry.get(tool_id).reviewed is True
    again = ToolRegistry(
        [SnakemakeWrapperAdapter(tmp_path / "upstream")], tmp_path / "cache", reviewed
    )
    again.build_index()
    assert again.get(tool_id).reviewed is True


def test_top50_manifest_definitions(tmp_path):
    manifest = Path(__file__).resolve().parents[1] / "tool_packs/top50.yaml"
    data = yaml.safe_load(manifest.read_text())
    adapter = BiocondaAutoWrapAdapter(tmp_path, tmp_path / "wrapped", tmp_path / "envs")
    tool_ids = set()
    for entry in data["tools"]:
        spec = adapter.validate(
            entry["package"], entry["command"], entry["definition"], tmp_path / "wrapped"
        )
        assert spec.tool_id not in tool_ids
        tool_ids.add(spec.tool_id)
    assert len(tool_ids) == len(data["tools"])


def test_logs():
    state = RunStatus("id", "all", node_states={"aaaaaaaa": "waiting"})
    jobs = {}
    for line in [
        "localrule n_test:",
        "jobid: 1",
        "Finished jobid: 1 (Rule: n_test)",
        "1 of 2 steps (50%) done",
    ]:
        parse_log_line(line, state, {"n_test": "aaaaaaaa"}, jobs)
    assert state.node_states["aaaaaaaa"] == "done"
    assert state.progress == (1, 2)


def test_real_snakemake_execution(tmp_path, registry):
    graph = shell_graph(tmp_path, registry)
    manager = RunManager(tmp_path, registry, config(tmp_path))
    run_id = manager.start(graph)
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        status = manager.status(run_id)
        if status.finished:
            break
        time.sleep(0.2)
    assert status.state == "success", Path(status.log_path).read_text()
    assert status.node_states["bbbbbbbb"] == "done"
    manifest = json.loads((tmp_path / "runs" / run_id / "manifest.json").read_text())
    output = manifest["outputs"]["bbbbbbbb"]["report"][0]
    assert Path(output).read_text().startswith("@r")
    assert isinstance(manifest["planned_jobs"], int) and manifest["planned_jobs"] > 0
    assert manifest["planned_jobs_kind"] == "graph_rules_before_cache"


def test_planned_jobs_and_step_states(tmp_path, registry):
    graph = chain_graph(tmp_path, registry)
    manager = RunManager(tmp_path, registry, config(tmp_path))
    all_run = wait(manager, manager.start(graph))
    assert all_run.state == "success", Path(all_run.log_path).read_text()
    manifest = json.loads((tmp_path / "runs" / all_run.run_id / "manifest.json").read_text())
    assert manifest["planned_jobs"] == 3
    assert manifest["planned_jobs_kind"] == "graph_rules_before_cache"

    step = wait(manager, manager.start(graph, mode="step", target_uid="b0000001"))
    assert step.state == "success", Path(step.log_path).read_text()
    assert step.node_states["a0000001"] == "skipped"
    assert step.node_states["b0000001"] == "done"
    assert step.node_states["c0000001"] == "skipped"
