"""Offscreen MainWindow check for common_tools_workspace; writes a screenshot and JSON."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6 import QtWidgets  # noqa: E402

from glue.config import load_config  # noqa: E402
from glue.session_store import load_session  # noqa: E402
from glue.wrapper_registry import ToolRegistry  # noqa: E402
from ui.workstation_window import PAYLOAD_ROLE, TOOL_MIME_PREFIX, MainWindow  # noqa: E402

WORKSPACE = ROOT / "common_tools_workspace"
UI_JSON = ROOT / "validation" / "common-tools-ui.json"
SCREENSHOT = ROOT / "validation" / "common-tools-ui.png"
PACKAGES = ("fastp", "bwa", "samtools", "bcftools", "seqkit")


def process(app, seconds=0.0):
    deadline = time.monotonic() + seconds
    while True:
        app.processEvents()
        if time.monotonic() >= deadline:
            break
        time.sleep(0.02)


def local_in_library(window) -> list[str]:
    found = set()
    model = window.library._model
    for query in PACKAGES:
        window.library.search_edit.setText(query)
        window.library.reload()
        for row in range(model.rowCount()):
            item = model.item(row, 0)
            payload = item.data(PAYLOAD_ROLE) if item else None
            if isinstance(payload, str) and payload.startswith(TOOL_MIME_PREFIX + "local:"):
                found.add(payload.removeprefix(TOOL_MIME_PREFIX))
    window.library.search_edit.clear()
    window.library.reload()
    return sorted(found)


def main() -> int:
    config = load_config(workspace=WORKSPACE)
    registry = ToolRegistry.from_config(config)
    session, revision = load_session(WORKSPACE)
    assert len(session["nodes"]) == 12, len(session["nodes"])
    assert len(session["connections"]) == 12, len(session["connections"])

    app = QtWidgets.QApplication([])
    window = MainWindow(config, registry)
    window.resize(1600, 960)
    window.show()
    process(app, 0.4)

    nodes = window.graph.all_nodes()
    edges = window._current_session()["connections"]
    assert len(nodes) == 12, len(nodes)
    assert len(edges) == 12, len(edges)
    assert window._revision == revision, (window._revision, revision)

    local_ids = local_in_library(window)
    assert len(local_ids) == 8, local_ids

    assert window.save() is True
    saved_revision = load_session(WORKSPACE)[1]
    window.reload_from_disk()
    process(app, 0.3)
    reloaded_nodes = window.graph.all_nodes()
    reloaded_edges = window._current_session()["connections"]
    assert len(reloaded_nodes) == 12, len(reloaded_nodes)
    assert len(reloaded_edges) == 12, len(reloaded_edges)

    window.graph.clear_selection()
    window.graph.fit_to_selection()
    process(app, 0.4)
    pixmap = window.grab()
    assert pixmap.save(str(SCREENSHOT)), SCREENSHOT

    payload = {
        "nodes": len(reloaded_nodes),
        "connections": len(reloaded_edges),
        "local_in_library": len(local_ids),
        "local_tool_ids": local_ids,
        "revision_before": revision,
        "revision_saved": saved_revision,
        "save_reload_ok": True,
        "screenshot": str(SCREENSHOT),
        "window_size": [pixmap.width(), pixmap.height()],
    }
    UI_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print("UI_COMMON_TOOLS_OK", json.dumps(payload, ensure_ascii=False))
    window._poll_timer.stop()
    process(app, 0.1)
    os._exit(0)


if __name__ == "__main__":
    main()
