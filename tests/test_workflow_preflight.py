"""Regressions for the read-only saved-graph preflight service."""

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from test_backend import config

from glue import session_schema as s
from glue import workflow_preflight as preflight_module
from glue.errors import CompileError, SessionConflictError, WorkstationError
from glue.models import CompileResult, ExecSpec, PortSpec, ToolSpec
from glue.session_store import load_session, save_session
from glue.workflow_preflight import preflight_workflow
from glue.wrapper_registry import SnakemakeWrapperAdapter, ToolRegistry

ROOT = Path(__file__).resolve().parents[1]


def make_registry(tmp_path):
    return ToolRegistry([SnakemakeWrapperAdapter(tmp_path / "upstream")], tmp_path / "cache")


def copy_spec(*, reviewed=True):
    return ToolSpec(
        "test:copy",
        "copy",
        "test",
        "bioconda-auto",
        "",
        (),
        (PortSpec("reads", ("FASTQ",)),),
        (PortSpec("report", ("TEXT",)),),
        (),
        ExecSpec("shell", shell="cp {input.reads:q} {output.report:q}"),
        reviewed=reviewed,
    )


def register_spec(registry, spec):
    registry.build_index()

    class Adapter:
        def load_spec(self, tool_id):
            return spec

    registry._owners[spec.tool_id] = Adapter()
    registry._specs.clear()


def copy_graph(
    tmp_path,
    *,
    connected=True,
    include_output=True,
    missing_input=False,
    reviewed=True,
):
    spec = copy_spec(reviewed=reviewed)
    reads = tmp_path / ("missing.fastq" if missing_input else "reads.fastq")
    if not missing_input:
        reads.write_text("@r\nACGT\n+\nIIII\n")
    graph = {
        "nodes": {
            "i": s.node_entry(
                s.FASTQ_INPUT,
                "reads",
                s.input_custom_defaults(s.INPUT_KINDS[0], "aaaaaaaa") | {"path_r1": str(reads)},
            ),
            "t": s.node_entry(
                s.tool_node_type(spec.tool_id), "copy", s.tool_custom_defaults(spec, "bbbbbbbb")
            ),
        },
        "connections": [],
    }
    if include_output:
        graph["nodes"]["o"] = s.node_entry(
            s.OUTPUT_NODE, "输出", s.output_custom_defaults("cccccccc")
        )
        graph["connections"].append(s.connection_entry("t", "report", "o", "files"))
    if connected:
        graph["connections"].insert(0, s.connection_entry("i", "reads", "t", "reads"))
    return graph, spec


def test_module_imports_standalone_without_cycle():
    completed = subprocess.run(
        [sys.executable, "-c", "import glue.workflow_preflight"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_broken_graph_then_repair_uses_stable_uid(tmp_path):
    registry = make_registry(tmp_path)
    graph, spec = copy_graph(tmp_path, connected=False)
    register_spec(registry, spec)
    revision = save_session(tmp_path, graph, 0)
    cfg = config(tmp_path)

    broken = preflight_workflow(cfg, registry)
    assert broken["valid"] is False
    assert broken["revision"] == revision
    assert broken["allow_unreviewed"] is False
    assert broken["tool_node_count"] == 0
    assert broken["targets"] == [] and broken["outputs"] == {}
    assert len(broken["diagnostics"]) == 1
    diagnostic = broken["diagnostics"][0]
    assert diagnostic["code"] == "compile_error"
    assert diagnostic["node_id"] == "bbbbbbbb"
    assert "reads" in diagnostic["message"]

    graph["connections"].insert(0, s.connection_entry("i", "reads", "t", "reads"))
    repaired_revision = save_session(tmp_path, graph, revision)
    repaired = preflight_workflow(cfg, registry)

    assert repaired["valid"] is True
    assert repaired["revision"] == repaired_revision
    assert repaired["diagnostics"] == []
    assert repaired["tool_node_count"] == 1
    assert repaired["targets"]
    assert all(path.startswith(str(tmp_path / "results")) for path in repaired["targets"])
    assert repaired["outputs"]["bbbbbbbb"]["report"]
    assert all(
        path.startswith(str(tmp_path / "results"))
        for path in repaired["outputs"]["bbbbbbbb"]["report"]
    )


def test_missing_input_file_reports_input_node_uid(tmp_path):
    registry = make_registry(tmp_path)
    graph, spec = copy_graph(tmp_path, missing_input=True)
    register_spec(registry, spec)
    save_session(tmp_path, graph, 0)

    result = preflight_workflow(config(tmp_path), registry)

    assert result["valid"] is False
    assert result["diagnostics"][0]["code"] == "compile_error"
    assert result["diagnostics"][0]["node_id"] == "aaaaaaaa"
    assert "输入文件不存在" in result["diagnostics"][0]["message"]


def test_unknown_tool_is_structured_not_a_crash(tmp_path):
    registry = make_registry(tmp_path)
    graph = {
        "nodes": {
            "t": s.node_entry(
                s.tool_node_type("missing:tool"),
                "missing",
                {
                    s.UID_PROP: "deadbeef",
                    s.TOOL_ID_PROP: "missing:tool",
                    s.THREADS_PROP: "1",
                },
            )
        },
        "connections": [],
    }
    save_session(tmp_path, graph, 0)

    result = preflight_workflow(config(tmp_path), registry)

    assert result["valid"] is False
    assert result["diagnostics"] == [
        {
            "code": "tool_not_found",
            "message": result["diagnostics"][0]["message"],
            "node_id": None,
        }
    ]
    assert "missing:tool" in result["diagnostics"][0]["message"]


def test_unknown_node_type_is_structured_not_a_crash(tmp_path):
    registry = make_registry(tmp_path)
    spec = copy_spec()
    register_spec(registry, spec)
    graph = {
        "nodes": {
            "t": s.node_entry(
                "bio.unknown.Type",
                "unknown",
                s.tool_custom_defaults(spec, "bbbbbbbb"),
            )
        },
        "connections": [],
    }
    save_session(tmp_path, graph, 0)

    result = preflight_workflow(config(tmp_path), registry)

    assert result["valid"] is False
    assert result["diagnostics"][0]["code"] == "compile_error"
    assert result["diagnostics"][0]["node_id"] == "bbbbbbbb"
    assert "未知节点类型" in result["diagnostics"][0]["message"]


def test_stale_revision_is_rejected(tmp_path):
    registry = make_registry(tmp_path)
    graph, spec = copy_graph(tmp_path)
    register_spec(registry, spec)
    revision = save_session(tmp_path, graph, 0)

    with pytest.raises(SessionConflictError):
        preflight_workflow(config(tmp_path), registry, expected_revision=revision + 1)
    assert (
        preflight_workflow(config(tmp_path), registry, expected_revision=revision)["revision"]
        == revision
    )


@pytest.mark.parametrize("allow_unreviewed", [True, False])
def test_config_driven_unreviewed_policy(tmp_path, allow_unreviewed):
    registry = make_registry(tmp_path)
    graph, spec = copy_graph(tmp_path, reviewed=False)
    register_spec(registry, spec)
    save_session(tmp_path, graph, 0)
    cfg = replace(config(tmp_path), allow_unreviewed=allow_unreviewed)

    result = preflight_workflow(cfg, registry)

    assert result["allow_unreviewed"] is allow_unreviewed
    if allow_unreviewed:
        assert result["valid"] is True
        assert "未审核工具：copy" in result["warnings"]
        assert result["tool_node_count"] == 1
    else:
        assert result["valid"] is False
        assert result["tool_node_count"] == 0
        assert result["targets"] == [] and result["outputs"] == {}
        assert result["diagnostics"][0]["code"] == "compile_error"
        assert result["diagnostics"][0]["node_id"] == "bbbbbbbb"


def test_explicit_unreviewed_policy_overrides_config(tmp_path):
    registry = make_registry(tmp_path)
    graph, spec = copy_graph(tmp_path, reviewed=False)
    register_spec(registry, spec)
    save_session(tmp_path, graph, 0)
    cfg = replace(config(tmp_path), allow_unreviewed=False)

    allowed = preflight_workflow(cfg, registry, allow_unreviewed=True)
    assert allowed["valid"] is True
    assert allowed["allow_unreviewed"] is True
    assert "未审核工具：copy" in allowed["warnings"]

    denied = preflight_workflow(
        replace(cfg, allow_unreviewed=True), registry, allow_unreviewed=False
    )
    assert denied["valid"] is False
    assert denied["allow_unreviewed"] is False
    assert denied["diagnostics"][0]["node_id"] == "bbbbbbbb"


def test_unexpected_bug_propagates(tmp_path, monkeypatch):
    registry = make_registry(tmp_path)
    graph, spec = copy_graph(tmp_path)
    register_spec(registry, spec)
    save_session(tmp_path, graph, 0)

    def explode(*args, **kwargs):
        raise TypeError("compiler bug")

    monkeypatch.setattr(preflight_module, "compile_session", explode)
    with pytest.raises(TypeError, match="compiler bug"):
        preflight_workflow(config(tmp_path), registry)


def test_preflight_has_no_session_run_or_process_side_effects(tmp_path, monkeypatch):
    registry = make_registry(tmp_path)
    graph, spec = copy_graph(tmp_path)
    register_spec(registry, spec)
    revision = save_session(tmp_path, graph, 0)
    session_bytes = (tmp_path / s.SESSION_FILE).read_bytes()
    meta_bytes = (tmp_path / s.SESSION_META_FILE).read_bytes()

    def forbidden(*args, **kwargs):
        raise AssertionError("preflight must not launch processes")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)

    result = preflight_workflow(config(tmp_path), registry)

    assert result["valid"] is True
    assert (tmp_path / s.SESSION_FILE).read_bytes() == session_bytes
    assert (tmp_path / s.SESSION_META_FILE).read_bytes() == meta_bytes
    assert load_session(tmp_path)[1] == revision
    for folder in ("runs", "results", "logs", "benchmarks"):
        assert not (tmp_path / folder).exists()
    assert not (tmp_path / "Snakefile").exists()
    assert not list(tmp_path.rglob("manifest.json"))


def test_empty_or_missing_session_is_reported_without_creating_it(tmp_path):
    result = preflight_workflow(config(tmp_path), make_registry(tmp_path))

    assert result["valid"] is False
    assert result["revision"] == 0
    assert result["tool_node_count"] == 0
    assert result["targets"] == [] and result["outputs"] == {}
    assert result["diagnostics"][0]["code"] == "compile_error"
    assert result["diagnostics"][0]["node_id"] is None
    assert "没有可运行的输出目标" in result["diagnostics"][0]["message"]
    assert not (tmp_path / s.SESSION_FILE).exists()


def test_corrupt_session_surfaces_as_expected_error(tmp_path):
    (tmp_path / s.SESSION_FILE).write_text("{not json")
    with pytest.raises(WorkstationError, match="无法读取会话"):
        preflight_workflow(config(tmp_path), make_registry(tmp_path))


def test_plan_and_message_bounds(tmp_path, monkeypatch):
    outputs = {
        f"{index:08x}": {"report": [f"/tmp/out-{index}-{item}" for item in range(120)]}
        for index in range(3)
    }

    def fake_compile(*args, **kwargs):
        return CompileResult(
            "SECRET SNAKEFILE",
            {"a0000001": "rule_a"},
            outputs,
            {},
            [f"/tmp/target-{index}" for index in range(250)],
            ["kept warning", "x" * 1000] + ["extra"] * 210,
        )

    monkeypatch.setattr(preflight_module, "compile_session", fake_compile)
    result = preflight_workflow(config(tmp_path), make_registry(tmp_path))

    assert result["valid"] is True
    assert result["truncated"] is True
    assert len(result["targets"]) == 200
    assert (
        sum(len(paths) for ports in result["outputs"].values() for paths in ports.values()) == 200
    )
    assert len(result["warnings"]) == 200
    assert result["warnings"][0] == "kept warning"
    assert len(result["warnings"][1]) == 500
    assert result["tool_node_count"] == 1
    assert "SECRET SNAKEFILE" not in json.dumps(result)

    def explode(*args, **kwargs):
        raise CompileError("长" * 1000, "deadbeef")

    monkeypatch.setattr(preflight_module, "compile_session", explode)
    failed = preflight_workflow(config(tmp_path), make_registry(tmp_path))
    assert failed["valid"] is False
    assert len(failed["diagnostics"][0]["message"]) == preflight_module.MAX_MESSAGE_CHARS
    assert failed["diagnostics"][0]["node_id"] == "deadbeef"
