"""Bounded verification for the offline demo: real runs first, then an offscreen UI pass."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "demo_workspace"
BACKEND_JSON = ROOT / "validation" / "demo-backend.json"
OVERVIEW_PNG = ROOT / "validation" / "demo-overview.png"
OUTPUT_PNG = ROOT / "validation" / "demo-output.png"

sys.path.insert(0, str(ROOT))

from examples.demo import prepare_demo  # noqa: E402

FASTQ_UID = "de000003"
FASTA_UID = "de000004"
REPORT_UID = "de000005"
OUTPUT_UID = "de000006"


def wait_run(manager, run_id, timeout=90.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = manager.status(run_id)
        if status.finished:
            return status
        time.sleep(0.25)
    raise TimeoutError(f"运行 {run_id} 超过 {timeout}s 未结束")


def compile_demo(config, registry, session):
    from glue.snakemake_bridge import compile_session

    return compile_session(
        session,
        registry,
        config.workspace,
        allowed_input_roots=config.allowed_input_roots,
    )


def backend(reset=False):
    from glue.session_store import load_session
    from glue.snakemake_bridge import RunManager

    config, registry = prepare_demo(WORKSPACE, reset=reset)
    session, revision = load_session(config.workspace)
    assert len(session["nodes"]) == 6, session["nodes"]
    assert len(session["connections"]) == 6, session["connections"]
    print(f"BACKEND_SESSION nodes=6 connections=6 revision={revision}")

    manager = RunManager(config.workspace, registry, config)
    compiled = compile_demo(config, registry, session)
    outputs = compiled.outputs
    print("BACKEND_OUTPUTS", outputs)

    all_run = manager.start(session, mode="all", cores=2)
    status = wait_run(manager, all_run)
    print("BACKEND_ALL", status.run_id, status.state, status.node_states, status.progress)
    assert status.state == "success", status.to_dict()
    for uid in (FASTQ_UID, FASTA_UID, REPORT_UID):
        assert status.node_states.get(uid) == "done", (uid, status.node_states)
    log = Path(status.log_path).read_text(errors="replace")
    assert log.count("Finished job") >= 3, log[-3000:]

    def stats_for(uid):
        return outputs[uid]["stats"][0]

    reads_stats = json.loads(Path(stats_for(FASTQ_UID)).read_text())
    reference_stats = json.loads(Path(stats_for(FASTA_UID)).read_text())
    print("BACKEND_READS_STATS", [(r["format"], r["valid"], r["stats"]) for r in reads_stats])
    assert len(reads_stats) == 2
    for item in reads_stats:
        assert item["valid"] is True
        assert item["format"] == "FASTQ"
        assert item["stats"]["records"] == 12
        assert item["stats"]["total_bases"] == 960
    print(
        "BACKEND_REFERENCE_STATS",
        [(r["format"], r["valid"], r["stats"]) for r in reference_stats],
    )
    assert len(reference_stats) == 1
    assert reference_stats[0]["valid"] is True
    assert reference_stats[0]["format"] == "FASTA"
    assert reference_stats[0]["stats"]["records"] == 1
    assert reference_stats[0]["stats"]["total_bases"] == 1000

    html_path = Path(outputs[REPORT_UID]["html"][0])
    report_json_path = Path(outputs[REPORT_UID]["json"][0])
    assert html_path.is_file() and report_json_path.is_file()
    html_text = html_path.read_text()
    report = json.loads(report_json_path.read_text())
    assert report["reads"] == reads_stats and report["reference"] == reference_stats
    assert html_text.count("<tr>") == 4  # header + 2 FASTQ + 1 FASTA
    for token in ("sample_R1.fastq", "sample_R2.fastq", "reference.fa", "960", "1000", "通过"):
        assert token in html_text, token
    print("BACKEND_REPORT", html_path, report_json_path, "rows=3")

    html_mtime = html_path.stat().st_mtime_ns
    reads_mtime = Path(stats_for(FASTQ_UID)).stat().st_mtime_ns
    reference_mtime = Path(stats_for(FASTA_UID)).stat().st_mtime_ns

    cached = manager.start(session, mode="all", cores=2)
    cached_status = wait_run(manager, cached)
    cached_log = Path(cached_status.log_path).read_text(errors="replace")
    print("BACKEND_CACHE", cached_status.run_id, cached_status.state, cached_status.node_states)
    assert cached_status.state == "success", cached_status.to_dict()
    assert all(state == "skipped" for state in cached_status.node_states.values())
    assert "Nothing to be done" in cached_log
    assert html_path.stat().st_mtime_ns == html_mtime
    print("BACKEND_CACHE_HIT outputs unchanged")

    step = manager.start(session, mode="step", target_uid=REPORT_UID, cores=2)
    step_status = wait_run(manager, step)
    step_log = Path(step_status.log_path).read_text(errors="replace")
    print("BACKEND_STEP", step_status.run_id, step_status.state, step_status.node_states)
    assert step_status.state == "success", step_status.to_dict()
    assert step_status.node_states.get(REPORT_UID) == "done"
    report_rule = compiled.rule_of_node[REPORT_UID]
    assert f"rule {report_rule}:" in step_log
    for uid in (FASTQ_UID, FASTA_UID):
        assert f"rule {compiled.rule_of_node[uid]}:" not in step_log
    assert html_path.stat().st_mtime_ns > html_mtime
    assert Path(stats_for(FASTQ_UID)).stat().st_mtime_ns == reads_mtime
    assert Path(stats_for(FASTA_UID)).stat().st_mtime_ns == reference_mtime
    print("BACKEND_STEP_ONLY_REPORT")

    payload = {
        "workspace": str(config.workspace),
        "all_run": status.run_id,
        "cache_run": cached_status.run_id,
        "step_run": step_status.run_id,
        "outputs": dict(outputs),
        "html": str(html_path),
        "report_json": str(report_json_path),
        "all_log": status.log_path,
        "step_log": step_status.log_path,
        "checks": {
            "nodes": 6,
            "connections": 6,
            "fastq": "2 x 12 reads / 960 bp",
            "reference": "1 x 1000 bp",
            "cache_hit": True,
            "step_only_report": True,
        },
    }
    BACKEND_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print("BACKEND_OK", BACKEND_JSON)
    return payload


def setup_logger():
    import logging

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def _process(app, seconds=0.0):
    deadline = time.monotonic() + seconds
    while True:
        app.processEvents()
        if time.monotonic() >= deadline:
            break
        time.sleep(0.02)


def _wait_until(app, predicate, timeout=20.0, description=""):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.03)
    raise TimeoutError(f"等待超时：{description}")


def _session_counts(window):
    session = window._current_session()
    return len(session["nodes"]), len(session["connections"])


def _select(window, node):
    window.graph.node_selected.emit(node)


def ui():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtWidgets

    from glue.models import RunStatus
    from glue.snakemake_bridge import RunManager
    from ui.workstation_window import STATE_BORDER_COLORS, MainWindow

    if not BACKEND_JSON.exists():
        backend()
    data = json.loads(BACKEND_JSON.read_text())
    config, registry = prepare_demo(WORKSPACE)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(config, registry)
    window.resize(1680, 1000)
    window.show()
    _process(app, 0.3)

    nodes, edges = _session_counts(window)
    print("UI_NODES", nodes, "UI_EDGES", edges)
    assert (nodes, edges) == (6, 6)

    window.graph.clear_selection()
    window.graph.fit_to_selection()
    _process(app, 0.3)
    viewer = window.graph.viewer()
    rect = viewer.viewport().rect()
    positions = []
    for node in window.graph.all_nodes():
        center = node.view.sceneBoundingRect().center()
        point = viewer.mapFromScene(center)
        positions.append((node.name(), point.x(), point.y(), rect.contains(point)))
    print("UI_GEOMETRY viewport=", rect.width(), rect.height(), "zoom=", window.graph.get_zoom())
    print("UI_NODE_CENTERS", positions)
    assert all(visible for *_rest, visible in positions), positions

    library = window.library
    library.search_edit.setText("demo")
    library.reload()
    _process(app, 0.1)
    labels = [library._model.item(row).text() for row in range(library._model.rowCount())]
    print("UI_SEARCH_DEMO", labels)
    for title in ("01 · 测序文件检查", "02 · 参考序列检查", "03 · 汇总演示报告"):
        assert any(title in label for label in labels), (title, labels)
    library.search_edit.clear()
    library.reload()
    _process(app, 0.1)

    by_uid = {node.uid(): node for node in window._bio_nodes()}
    reads_in, ref_in = by_uid["de000001"], by_uid["de000002"]
    tool_reads, tool_ref, tool_report = (
        by_uid[FASTQ_UID],
        by_uid[FASTA_UID],
        by_uid[REPORT_UID],
    )
    output_node = by_uid[OUTPUT_UID]

    _select(window, tool_report)
    tool_report.set_selected(True)
    _process(app, 0.2)
    editor = window.properties_bin.get_property_editor_widget(tool_report)
    print("UI_PROPERTIES", editor is not None, tool_report.name())
    assert editor is not None

    _select(window, reads_in)
    _wait_until(
        app,
        lambda: (
            "sample_R1.fastq" in window.preview_view.toPlainText()
            and "records" in window.preview_view.toPlainText()
        ),
        description="FASTQ 输入预览",
    )
    preview = window.preview_view.toPlainText()
    print(
        "UI_INPUT_PREVIEW chars=",
        len(preview),
        "sampled=",
        "sampled_records" in preview,
        "valid=",
        "合法" in preview,
    )
    assert "sample_R1.fastq" in preview and "sampled_records" in preview and "合法" in preview

    _select(window, output_node)
    output_node.set_selected(True)
    window._preview_outputs(output_node)
    _wait_until(
        app,
        lambda: (
            "html.html" in window.preview_view.toPlainText()
            and "json.json" in window.preview_view.toPlainText()
        ),
        description="输出预览",
    )
    output_preview = window.preview_view.toPlainText()
    print("UI_OUTPUT_PREVIEW chars=", len(output_preview))
    assert "合法" in output_preview
    assert len(output_preview) > 200

    manager = RunManager(config.workspace, registry, config)
    status = RunStatus.from_dict(manager.status(data["all_run"]).to_dict())
    window._follow_run(status.run_id)
    window._apply_run_status(status)
    window._tail_log(status.log_path)
    window._on_run_finished(status)
    _process(app, 0.2)
    log_text = window.log_view.toPlainText()
    print("UI_RUN_LOG chars=", len(log_text), "finished=", "Finished job" in log_text)
    assert "Finished job" in log_text
    for node in (tool_reads, tool_ref, tool_report):
        color = node.get_property("border_color")
        print("UI_BORDER", node.name(), color)
        assert tuple(color) == STATE_BORDER_COLORS["done"], (node.name(), color)

    before = _session_counts(window)
    bad_out = ref_in.outputs()["fasta"]
    bad_in = tool_reads.inputs()["files"]
    bad_out.connect_to(bad_in)
    _process(app, 0.3)
    after = _session_counts(window)
    refused = "已拒绝连线" in window.log_view.toPlainText()
    print("UI_BAD_EDGE", before, after, "refused=", refused, window.statusBar().currentMessage())
    assert before == after == (6, 6)
    assert refused

    assert window.save() is True
    window.reload_from_disk()
    _process(app, 0.2)
    reloaded = _session_counts(window)
    uids = {node.uid() for node in window._bio_nodes()}
    print("UI_RELOAD", reloaded, sorted(uids))
    assert reloaded == (6, 6)
    assert uids == {"de000001", "de000002", FASTQ_UID, FASTA_UID, REPORT_UID, OUTPUT_UID}

    window.graph.clear_selection()
    window.graph.fit_to_selection()
    _process(app, 0.4)
    pixmap = window.grab()
    assert pixmap.width() == 1680 and pixmap.height() == 1000, pixmap.size()
    assert pixmap.save(str(OVERVIEW_PNG))
    print("UI_SCREENSHOT", OVERVIEW_PNG, pixmap.width(), pixmap.height())

    output_node = {node.uid(): node for node in window._bio_nodes()}[OUTPUT_UID]
    _select(window, output_node)
    output_node.set_selected(True)
    window._preview_outputs(output_node)
    _wait_until(
        app,
        lambda: "html.html" in window.preview_view.toPlainText(),
        description="截图输出预览",
    )
    _process(app, 0.3)
    pixmap = window.grab()
    assert pixmap.width() == 1680 and pixmap.height() == 1000, pixmap.size()
    assert pixmap.save(str(OUTPUT_PNG))
    print("UI_SCREENSHOT", OUTPUT_PNG, pixmap.width(), pixmap.height())
    window._poll_timer.stop()
    print("UI_OK", flush=True)
    os._exit(0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("section", choices=("backend", "ui", "all"), nargs="?", default="all")
    parser.add_argument("--reset", action="store_true", help="重建演示工作区与输入")
    args = parser.parse_args()
    setup_logger()
    if args.section in ("backend", "all"):
        backend(reset=args.reset)
    if args.section in ("ui", "all"):
        ui()


if __name__ == "__main__":
    main()
