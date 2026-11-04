"""Agent/desktop editing and historical artifact contract regressions."""

import json
from dataclasses import replace

import pytest
from test_backend import config, shell_graph, wait

from glue import session_schema as s
from glue.config import load_config
from glue.errors import SessionConflictError, WorkstationError
from glue.session_store import load_session
from glue.snakemake_bridge import RunManager
from glue.workflow_service import WorkflowService
from glue.wrapper_registry import SnakemakeWrapperAdapter, ToolRegistry


def setup_service(tmp_path):
    cfg = replace(load_config(workspace=tmp_path), cache_dir=tmp_path / "cache")
    reg = ToolRegistry([SnakemakeWrapperAdapter(tmp_path / "upstream")], tmp_path / "cache")
    spec = reg.get("smk:bio/fastp")
    graph = {
        "nodes": {
            "t": s.node_entry(
                s.tool_node_type(spec.tool_id), "fastp", s.tool_custom_defaults(spec, "aaaaaaaa")
            )
        },
        "connections": [],
    }
    svc = WorkflowService(cfg, reg)
    svc.save(graph, 0)
    return svc


def test_edit_roundtrip_and_conflict(tmp_path):
    svc = setup_service(tmp_path)
    initial = svc.read()
    changed = svc.edit(
        "update",
        node_id="aaaaaaaa",
        properties={"threads": 2},
        name="QC",
        expected_revision=initial["revision"],
    )
    assert svc.read()["nodes"][0]["properties"]["threads"] == "2"
    assert svc.read()["nodes"][0]["name"] == "QC"
    with pytest.raises(SessionConflictError):
        svc.edit("remove", node_id="aaaaaaaa", expected_revision=initial["revision"])
    with pytest.raises(WorkstationError):
        svc.edit("update", node_id="aaaaaaaa", properties={"threads": 0})
    assert svc.read()["revision"] == changed["revision"]
    with pytest.raises(WorkstationError):
        svc.edit("update", node_id="aaaaaaaa", properties={"tool_id": "other"})
    svc.edit("remove", node_id="aaaaaaaa")
    assert svc.read()["nodes"] == []


def test_shared_save_rejects_bad_ui_config(tmp_path):
    svc = setup_service(tmp_path)
    graph, revision = load_session(tmp_path)
    graph["nodes"]["t"]["custom"]["threads"] = "invalid"
    with pytest.raises(WorkstationError):
        svc.save(graph, revision)
    assert svc.read()["revision"] == revision


def test_run_snapshot_policy_and_stale_artifact(tmp_path):
    reg = ToolRegistry([SnakemakeWrapperAdapter(tmp_path / "upstream")], tmp_path / "cache")
    graph = shell_graph(tmp_path, reg)
    manager = RunManager(tmp_path, reg, config(tmp_path))
    uid = "bbbbbbbb"
    # Explicitly allow the external agent to execute an unreviewed definition.
    owner = reg._owners["test:copy"]
    original = owner.load_spec
    owner.load_spec = lambda tool_id: replace(original(tool_id), reviewed=False)
    reg._specs.clear()
    with pytest.raises(WorkstationError):
        manager.start(graph)
    run_id = manager.start(graph, allow_unreviewed=True)
    assert wait(manager, run_id).state == "success"
    snapshot = manager.snapshot(run_id)
    assert snapshot["manifest"]["allow_unreviewed"] is True
    assert snapshot["manifest"]["tool_definitions"][uid]["reviewed"] is False
    output = manager.output_paths(run_id, uid)[0]
    graph["nodes"]["t"]["custom"]["threads"] = "3"
    assert snapshot["session"]["nodes"]["t"]["custom"]["threads"] == "1"
    from pathlib import Path

    Path(output).write_text("new run changed this artifact")
    with pytest.raises(WorkstationError, match="已变更"):
        manager.output_paths(run_id, uid)
    assert json.loads((tmp_path / "runs" / run_id / "artifacts.json").read_text())


def test_artifact_link_target_changes_and_directory_loop(tmp_path):
    from glue.run_artifacts import fingerprint

    target = tmp_path / "target.txt"
    target.write_text("old")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    before = fingerprint(link)
    target.write_text("new-longer-output")
    assert fingerprint(link) != before
    loop = tmp_path / "loop"
    loop.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(OSError):
        fingerprint(tmp_path)


def test_artifact_scan_failure_keeps_terminal_state(tmp_path):
    from glue.models import PortSpec

    reg = ToolRegistry([SnakemakeWrapperAdapter(tmp_path / "upstream")], tmp_path / "cache")
    graph = shell_graph(tmp_path, reg)
    owner = reg._owners["test:copy"]
    spec = replace(
        owner.load_spec("test:copy"),
        outputs=(PortSpec("report", ("ANY",), directory=True),),
        execution=replace(
            owner.load_spec("test:copy").execution,
            shell="mkdir -p {output.report:q}; ln -s loop {output.report:q}/loop",
        ),
    )
    owner.load_spec = lambda tool_id: spec
    reg._specs.clear()
    manager = RunManager(tmp_path, reg, config(tmp_path))
    run_id = manager.start(graph)
    assert wait(manager, run_id).state == "success"
    assert "结果身份记录失败" in (tmp_path / "runs" / run_id / "snakemake.log").read_text()
    with pytest.raises(WorkstationError, match="尚无可验证"):
        manager.output_paths(run_id, "bbbbbbbb")


def test_builtin_nodes_are_discoverable_and_configurable(tmp_path):
    svc = setup_service(tmp_path)
    assert "fastq_input" in svc.read()["builtin_node_kinds"]
    input_schema = svc.tool_schema("fastq_input")
    assert set(input_schema["properties"]) == {"path_r1", "path_r2"}
    assert input_schema["definition"]["outputs"][0]["name"] == "reads"
    output_schema = svc.tool_schema("output")
    assert output_schema["definition"]["inputs"][0]["name"] == "files"
