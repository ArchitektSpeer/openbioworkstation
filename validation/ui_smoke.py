"""Bounded offscreen UI smoke test: load a shared session, save, then exit hard."""

import os
import shutil
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets  # noqa: E402

from glue import session_schema as schema  # noqa: E402
from glue.config import load_config  # noqa: E402
from glue.session_store import load_session, save_session  # noqa: E402
from glue.workflow_service import WorkflowService
from glue.wrapper_registry import ToolRegistry  # noqa: E402
from ui.workstation_window import MainWindow  # noqa: E402

WS = Path(__file__).resolve().parent / "tmp-ui"


def seed():
    if WS.exists():
        shutil.rmtree(WS)
    WS.mkdir(parents=True)
    reads = WS / "reads.fastq"
    reads.write_text("@r\nACGT\n+\nIIII\n")
    spec = ToolRegistry.from_config(
        replace(
            load_config(workspace=WS),
            upstream_dir=WS / "upstream",
            cache_dir=WS / "cache",
            data_dir=WS / "data",
        )
    ).get("smk:bio/fastp")
    session = {
        "nodes": {
            "i": schema.node_entry(
                schema.FASTQ_INPUT,
                "reads",
                schema.input_custom_defaults(schema.INPUT_KINDS[0], "aaaaaaaa")
                | {"path_r1": str(reads)},
                (0, 0),
            ),
            "t": schema.node_entry(
                schema.tool_node_type(spec.tool_id),
                "fastp",
                schema.tool_custom_defaults(spec, "bbbbbbbb"),
                (300, 0),
            ),
            "o": schema.node_entry(
                schema.OUTPUT_NODE, "输出", schema.output_custom_defaults("0000000f"), (600, 0)
            ),
        },
        "connections": [
            schema.connection_entry("i", "reads", "t", "sample"),
            schema.connection_entry("t", "trimmed", "o", "files"),
        ],
    }
    save_session(WS, session, updated_by="seed")


def main():
    seed()
    config = replace(
        load_config(workspace=WS),
        cache_dir=WS / "cache",
        conda_prefix=WS / "envs",
        data_dir=WS / "data",
        upstream_dir=WS / "upstream",
    )
    registry = ToolRegistry.from_config(config)
    app = QtWidgets.QApplication([])
    win = MainWindow(config, registry)
    app.processEvents()
    nodes = win.graph.all_nodes()
    edges = win._current_session()["connections"]
    print("UI_NODES", len(nodes), [n.name() for n in nodes])
    print("UI_EDGES", len(edges), "revision=", win._revision)
    assert len(nodes) == 3 and len(edges) == 2 and win._revision == 1
    assert win.save() is True
    print("UI_SAVED_REVISION", load_session(WS)[1])
    assert load_session(WS)[1] == 2
    agent = WorkflowService(config, registry)
    agent.edit("update", node_id="bbbbbbbb", properties={"threads": 2}, name="Agent QC")
    win._check_session_revision()
    assert len(win.graph.all_nodes()) == 3
    assert win._node_by_uid("bbbbbbbb").get_property("threads") == "2"
    assert win._node_by_uid("bbbbbbbb").name() == "Agent QC"
    win._node_by_uid("bbbbbbbb").set_property("threads", "3")
    assert win.save()
    assert (
        next(n for n in agent.read()["nodes"] if n["node_id"] == "bbbbbbbb")["properties"][
            "threads"
        ]
        == "3"
    )
    print("UI_AGENT_ROUNDTRIP_OK", flush=True)
    # A separate agent process writes a newly wrapped tool after the UI index was built.
    from glue.wrapper_registry import BiocondaAutoWrapAdapter

    adapter = next(a for a in registry.adapters if isinstance(a, BiocondaAutoWrapAdapter))
    spec = adapter.store_definition(
        "example",
        "example",
        """name: Example
biows:
  inputs: {reads: {formats: [FASTQ]}}
  outputs: {report: {formats: [TEXT]}}
  params: {minimum: 1}
  shell: "cat {input.reads:q} > {output.report:q}"
""",
        "1.0",
    )
    saved, revision = load_session(WS)
    saved["nodes"]["external"] = schema.node_entry(
        schema.tool_node_type(spec.tool_id),
        "Example",
        schema.tool_custom_defaults(spec, "cccccccc"),
    )
    save_session(WS, saved, revision, "external-agent")
    win._check_session_revision()
    assert win._node_by_uid("cccccccc") is not None
    assert win._node_by_uid("cccccccc").get_property("param_minimum") == "1"
    print("UI_EXTERNAL_WRAPPER_OK", flush=True)
    # Exercise workspace rebinding without opening a native directory chooser.
    from unittest.mock import patch

    other = WS / "other"
    with patch.object(QtWidgets.QFileDialog, "getExistingDirectory", return_value=str(other)):
        win.open_workspace()
    assert win.workflow_service.config.workspace == other
    assert win.save()
    assert len(load_session(WS)[0]["nodes"]) == 4
    assert load_session(other)[0]["nodes"] == {}
    print("UI_WORKSPACE_SWITCH_OK", flush=True)
    win._poll_timer.stop()
    app.processEvents()
    print("UI_SMOKE_OK", flush=True)
    os._exit(0)


if __name__ == "__main__":
    main()
