"""OpenBioWorkstation 桌面工作台。

左侧工具库（懒加载 + 搜索）→ 中间 NodeGraphQt 画布 → 右侧属性与文件预览，底部为运行日志。
Agent（MCP 服务端）对 session.json 的修改与其发起的运行，通过轻量轮询工作区文件同步到界面。

启动：python -m ui.workstation_window [--workspace DIR] [--config FILE]
"""

from __future__ import annotations

import argparse
import functools
import logging
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from NodeGraphQt import BaseNode, NodeGraph, PropertiesBinWidget
from NodeGraphQt.constants import NodePropWidgetEnum
from PySide6 import QtCore, QtGui, QtWidgets

from glue import session_schema as schema
from glue.bio_inspector import inspect_bio_file
from glue.config import load_config
from glue.errors import CompileError, SessionConflictError, ToolNotWrappedError, WorkstationError
from glue.formats import formats_compatible
from glue.models import Config, IndexEntry, InspectResult, RunMode, RunStatus, ToolSpec
from glue.session_store import load_session, read_revision, sanitize_session, save_session
from glue.snakemake_bridge import RunManager, compile_session
from glue.wrapper_registry import ToolRegistry

logger = logging.getLogger(__name__)

RGB = tuple[int, int, int]
RGBA = tuple[int, int, int, int]

DEFAULT_NODE_COLOR: RGB = (13, 18, 23)
UNREVIEWED_NODE_COLOR: RGB = (92, 42, 42)
DEFAULT_BORDER_COLOR: RGBA = (74, 84, 85, 255)
INVALID_BORDER_COLOR: RGBA = (225, 85, 84, 255)
STATE_BORDER_COLORS: dict[str, RGBA] = {
    "waiting": (128, 128, 128, 255),
    "running": (230, 194, 41, 255),
    "done": (59, 178, 115, 255),
    "failed": (225, 85, 84, 255),
    "skipped": (59, 178, 115, 110),
}
NODE_STATE_LABELS: dict[str, str] = {
    "waiting": "等待",
    "running": "运行中",
    "done": "完成",
    "failed": "失败",
    "skipped": "跳过/缓存",
}
RUN_STATE_LABELS: dict[str, str] = {
    "pending": "排队中",
    "running": "运行中",
    "success": "成功",
    "failed": "失败",
    "cancelled": "已取消",
}
RUN_MODE_LABELS: dict[str, str] = {"all": "全量", "until": "运行至此", "step": "单步"}
ANY_PORT_COLOR: RGB = (150, 150, 150)
FORMAT_PORT_COLORS: dict[str, RGB] = {
    "FASTQ": (66, 135, 245),
    "FASTA": (102, 178, 255),
    "SAM": (255, 196, 102),
    "BAM": (240, 150, 50),
    "CRAM": (214, 120, 40),
    "BAI": (200, 160, 110),
    "VCF": (156, 102, 214),
    "BCF": (124, 77, 184),
    "BED": (77, 182, 172),
    "GTF": (110, 190, 90),
    "GFF": (110, 190, 90),
    "BWA_INDEX": (190, 110, 70),
    "HTML": (120, 180, 120),
    "JSON": (170, 170, 110),
    "TSV": (170, 170, 110),
    "TEXT": (170, 170, 170),
}

TOOL_MIME_PREFIX = "biows-tool:"
NODE_MIME_PREFIX = "biows-node:"
PAYLOAD_ROLE = int(QtCore.Qt.ItemDataRole.UserRole) + 1
CATEGORY_ROLE = int(QtCore.Qt.ItemDataRole.UserRole) + 2
SEARCH_DEBOUNCE_MS = 200
SEARCH_LIMIT = 200
POLL_INTERVAL_MS = 500
LOG_MAX_LINES = 5000
MAX_PREVIEW_FILES = 10
MAX_OPEN_FILES = 5
RUN_HISTORY_LIMIT = 50


def port_color(formats: Sequence[str]) -> RGB:
    return next((FORMAT_PORT_COLORS[f] for f in formats if f in FORMAT_PORT_COLORS), ANY_PORT_COLOR)


def parse_search_text(text: str) -> tuple[str, str | None, str | None]:
    """解析搜索框文本，支持 in:FORMAT / out:FORMAT 过滤，其余部分作为关键词。"""
    words: list[str] = []
    input_format = output_format = None
    for token in text.split():
        lowered = token.lower()
        if lowered.startswith("in:") and len(token) > 3:
            input_format = token[3:].upper()
        elif lowered.startswith("out:") and len(token) > 4:
            output_format = token[4:].upper()
        else:
            words.append(token)
    return " ".join(words), input_format, output_format


def format_inspection(result: InspectResult) -> str:
    """把文件检查结果排版为预览面板中的纯文本。"""
    fmt = f"{result.format}（{result.compressed}）" if result.compressed else result.format
    status = "合法" if result.valid else f"无效：{result.error}"
    lines = [f"文件：{result.path}", f"格式：{fmt}", f"状态：{status}"]
    if result.index:
        marks = (f"{name} {'✔' if present else '✘'}" for name, present in result.index.items())
        lines.append("索引：" + "  ".join(marks))
    if result.stats:
        lines.append("统计：")
        lines.extend(f"  {key}: {_format_value(value)}" for key, value in result.stats.items())
    if result.warnings:
        lines.append("警告：")
        lines.extend(f"  {warning}" for warning in result.warnings)
    if result.preview:
        lines.append(f"前 {len(result.preview)} 条记录：")
        lines.extend(result.preview)
    lines.append(f"耗时：{result.elapsed_ms:.1f} ms")
    return "\n".join(lines)


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def _inspect_job(uid: str, path: str, full_stats: bool) -> tuple[str, InspectResult]:
    return uid, inspect_bio_file(path, full_stats=full_stats)


def _format_time(iso_text: str | None) -> str:
    if not iso_text:
        return "—"
    try:
        return datetime.fromisoformat(iso_text).astimezone().strftime("%m-%d %H:%M:%S")
    except ValueError:
        return iso_text


def _color_swatch(color: RGBA, text: str) -> str:
    red, green, blue, alpha = color
    return f'<span style="color: rgba({red},{green},{blue},{alpha});">■</span> {text}'


# ---------------------------------------------------------------- 节点


class BioNode(BaseNode):
    """所有生信节点的基类：记录各端口的格式标签，并持有稳定的 bio_uid。"""

    __identifier__ = "bio"
    NODE_NAME = "Bio"

    def __init__(self) -> None:
        super().__init__()
        self.input_formats: dict[str, tuple[str, ...]] = {}
        self.output_formats: dict[str, tuple[str, ...]] = {}

    def uid(self) -> str:
        return str(self.get_property(schema.UID_PROP))

    def _add_port(
        self, direction: str, name: str, formats: tuple[str, ...], multiple: bool
    ) -> None:
        color = port_color(formats)
        if direction == "in":
            self.add_input(name, multi_input=multiple, color=color)
            self.input_formats[name] = formats
        else:
            self.add_output(name, multi_output=True, color=color)
            self.output_formats[name] = formats

    def _add_custom(self, name: str, value: str, widget: NodePropWidgetEnum, **kwargs: Any) -> None:
        self.create_property(name, value, widget_type=widget.value, **kwargs)


class BioInputNode(BioNode):
    """输入节点基类：路径属性变化时由主窗口触发文件检查。"""

    __identifier__ = "bio.input"
    KIND: schema.InputKind

    def __init__(self) -> None:
        super().__init__()
        kind = self.KIND
        for prop, value in schema.input_custom_defaults(kind).items():
            if prop in kind.path_props:
                self._add_custom(prop, value, NodePropWidgetEnum.FILE_OPEN, tab="文件")
            else:
                self._add_custom(prop, value, NodePropWidgetEnum.HIDDEN)
        self._add_port("out", kind.port, kind.formats, kind.multiple)

    def paths(self) -> list[str]:
        values = (str(self.get_property(prop) or "").strip() for prop in self.KIND.path_props)
        return [value for value in values if value]


class FastqInputNode(BioInputNode):
    KIND = schema.INPUT_KIND_BY_TYPE[schema.FASTQ_INPUT]
    NODE_NAME = KIND.label


class FastaReferenceNode(BioInputNode):
    KIND = schema.INPUT_KIND_BY_TYPE[schema.FASTA_INPUT]
    NODE_NAME = KIND.label


class BamInputNode(BioInputNode):
    KIND = schema.INPUT_KIND_BY_TYPE[schema.BAM_INPUT]
    NODE_NAME = KIND.label


class VcfInputNode(BioInputNode):
    KIND = schema.INPUT_KIND_BY_TYPE[schema.VCF_INPUT]
    NODE_NAME = KIND.label


INPUT_NODE_CLASSES: tuple[type[BioInputNode], ...] = (
    FastqInputNode,
    FastaReferenceNode,
    BamInputNode,
    VcfInputNode,
)


class BioOutputNode(BioNode):
    """输出汇总节点：一个可多连的 ANY 输入端口，运行后可预览其上游产物。"""

    __identifier__ = "bio.output"
    NODE_NAME = "输出汇总"

    def __init__(self) -> None:
        super().__init__()
        for prop, value in schema.output_custom_defaults().items():
            if prop == schema.LABEL_PROP:
                self._add_custom(prop, value, NodePropWidgetEnum.QLINE_EDIT, tab="输出")
            else:
                self._add_custom(prop, value, NodePropWidgetEnum.HIDDEN)
        self._add_port("in", schema.OUTPUT_NODE_PORT, (schema.ANY_FORMAT,), multiple=True)


class SnakemakeWrapperNode(BioNode):
    """工具节点基类；每个 tool_id 在首次使用时由 MainWindow 动态生成一个子类（SPEC 指向其定义）。"""

    __identifier__ = "bio.tool"
    NODE_NAME = "工具"
    SPEC: ToolSpec | None = None

    def __init__(self) -> None:
        super().__init__()
        spec = self.SPEC
        if spec is None:
            raise TypeError("SnakemakeWrapperNode 只能通过 MainWindow 动态生成的子类实例化")
        tooltips = {schema.param_prop(p.name): p.description for p in spec.params}
        for prop, value in schema.tool_custom_defaults(spec).items():
            if prop in (schema.UID_PROP, schema.TOOL_ID_PROP):
                self._add_custom(prop, value, NodePropWidgetEnum.HIDDEN)
            elif prop == schema.THREADS_PROP:
                self._add_custom(prop, value, NodePropWidgetEnum.QLINE_EDIT, tab="运行")
            else:
                self._add_custom(
                    prop,
                    value,
                    NodePropWidgetEnum.QLINE_EDIT,
                    widget_tooltip=tooltips.get(prop) or None,
                    tab="参数",
                )
        for port in spec.inputs:
            self._add_port("in", port.name, port.formats, port.multiple)
        for port in spec.outputs:
            self._add_port("out", port.name, port.formats, port.multiple)
        if not spec.reviewed:
            self.set_color(*UNREVIEWED_NODE_COLOR)

    def tool_id(self) -> str:
        return str(self.get_property(schema.TOOL_ID_PROP))


# ---------------------------------------------------------------- 后台任务


class _TaskSignals(QtCore.QObject):
    succeeded = QtCore.Signal(object)
    failed = QtCore.Signal(object)


class _Task(QtCore.QRunnable):
    """在全局线程池执行 func；结果通过信号排队回到主线程。"""

    def __init__(self, func: Callable[[], Any]) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self.func = func
        self.signals = _TaskSignals()
        self.done = False

    def run(self) -> None:
        try:
            result = self.func()
        except Exception as exc:
            logger.exception("后台任务失败")
            self.signals.failed.emit(exc)
        else:
            self.signals.succeeded.emit(result)
        finally:
            self.done = True


# ---------------------------------------------------------------- 工具库


class ToolTreeModel(QtGui.QStandardItemModel):
    """工具树模型：拖拽只携带 text/plain 载荷，NodeGraphQt 画布会以 data_dropped 信号转交。"""

    def mimeTypes(self) -> list[str]:
        return ["text/plain"]

    def mimeData(self, indexes: Sequence[QtCore.QModelIndex]) -> QtCore.QMimeData:
        mime = QtCore.QMimeData()
        payload = next((i.data(PAYLOAD_ROLE) for i in indexes if i.data(PAYLOAD_ROLE)), "")
        mime.setText(payload)
        return mime


class ToolLibraryWidget(QtWidgets.QWidget):
    """左侧工具库：分类懒展开；输入关键词后切换为平铺的检索结果。"""

    activated = QtCore.Signal(str)

    def __init__(self, registry: ToolRegistry, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._registry = registry
        self._pending: dict[str, list[IndexEntry]] = {}

        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setPlaceholderText("搜索工具，如：bwa  in:FASTQ  out:BAM")
        self.search_edit.setClearButtonEnabled(True)
        self._model = ToolTreeModel(self)
        self._tree = QtWidgets.QTreeView()
        self._tree.setModel(self._model)
        self._tree.setHeaderHidden(True)
        self._tree.setUniformRowHeights(True)
        self._tree.setDragEnabled(True)
        self._tree.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.DragOnly)
        self._tree.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.search_edit)
        layout.addWidget(self._tree)

        self._debounce = QtCore.QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(SEARCH_DEBOUNCE_MS)
        self._debounce.timeout.connect(self.reload)
        self.search_edit.textChanged.connect(self._debounce.start)
        self._tree.expanded.connect(self._on_expanded)
        self._tree.doubleClicked.connect(self._on_double_clicked)
        self.reload()

    def reload(self) -> None:
        query, input_format, output_format = parse_search_text(self.search_edit.text())
        self._model.clear()
        self._pending.clear()
        if query or input_format or output_format:
            self._populate_search(query, input_format, output_format)
        else:
            self._populate_categories()

    def _populate_categories(self) -> None:
        root = self._model.invisibleRootItem()
        canvas = self._category_item("画布节点", "")
        for kind in schema.INPUT_KINDS:
            canvas.appendRow(self._node_item(kind.label, kind.node_type, "、".join(kind.formats)))
        canvas.appendRow(
            self._node_item(BioOutputNode.NODE_NAME, schema.OUTPUT_NODE, "汇总最终产物")
        )
        root.appendRow(canvas)
        self._tree.expand(canvas.index())
        for category, entries in self._registry.categories().items():
            item = self._category_item(f"{category}（{len(entries)}）", category)
            item.appendRow(self._hint_item("加载中…"))
            self._pending[category] = entries
            root.appendRow(item)

    def _populate_search(
        self, query: str, input_format: str | None, output_format: str | None
    ) -> None:
        page = self._registry.search(
            query, input_format=input_format, output_format=output_format, limit=SEARCH_LIMIT
        )
        for entry in page.items:
            self._model.appendRow(self._entry_item(entry))
        if page.total == 0:
            self._model.appendRow(self._hint_item("无匹配工具"))
        elif page.total > len(page.items):
            self._model.appendRow(
                self._hint_item(f"共 {page.total} 个结果，仅显示前 {len(page.items)} 个")
            )

    def _on_expanded(self, index: QtCore.QModelIndex) -> None:
        item = self._model.itemFromIndex(index)
        entries = self._pending.pop(item.data(CATEGORY_ROLE) or "", None)
        if entries is None:
            return
        item.removeRows(0, item.rowCount())
        for entry in entries:
            item.appendRow(self._entry_item(entry))

    def _on_double_clicked(self, index: QtCore.QModelIndex) -> None:
        if payload := index.data(PAYLOAD_ROLE):
            self.activated.emit(payload)

    @staticmethod
    def _category_item(text: str, category: str) -> QtGui.QStandardItem:
        item = QtGui.QStandardItem(text)
        item.setData(category, CATEGORY_ROLE)
        item.setDragEnabled(False)
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        return item

    @staticmethod
    def _hint_item(text: str) -> QtGui.QStandardItem:
        item = QtGui.QStandardItem(text)
        item.setEnabled(False)
        item.setDragEnabled(False)
        return item

    @staticmethod
    def _node_item(label: str, node_type: str, tooltip: str) -> QtGui.QStandardItem:
        item = QtGui.QStandardItem(label)
        item.setData(f"{NODE_MIME_PREFIX}{node_type}", PAYLOAD_ROLE)
        item.setToolTip(tooltip)
        return item

    @staticmethod
    def _entry_item(entry: IndexEntry) -> QtGui.QStandardItem:
        label = entry.name
        if not entry.wrapped:
            label += "（未封装）"
        elif not entry.reviewed:
            label += "（未审核）"
        item = QtGui.QStandardItem(label)
        item.setData(f"{TOOL_MIME_PREFIX}{entry.tool_id}", PAYLOAD_ROLE)
        tooltip = [
            entry.tool_id,
            f"来源：{entry.source}",
            f"输入：{'、'.join(entry.input_formats) or '—'}",
            f"输出：{'、'.join(entry.output_formats) or '—'}",
        ]
        if entry.summary:
            tooltip.append(entry.summary)
        item.setToolTip("\n".join(tooltip))
        if not (entry.wrapped and entry.reviewed):
            item.setForeground(QtGui.QBrush(QtGui.QColor(140, 140, 140)))
        return item


# ---------------------------------------------------------------- 运行历史


class RunHistoryDialog(QtWidgets.QDialog):
    """列出工作区最近的运行（含 Agent 发起的），选中后在主窗口回放其节点状态与日志。"""

    HEADERS = ("开始时间", "模式", "目标节点", "状态", "进度", "运行 ID")

    def __init__(
        self,
        runs: Sequence[RunStatus],
        node_name: Callable[[str], str],
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("运行历史")
        self.resize(820, 420)
        self.selected_run_id: str | None = None

        self._table = QtWidgets.QTableWidget(len(runs), len(self.HEADERS))
        self._table.setHorizontalHeaderLabels(self.HEADERS)
        self._table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        for row, run in enumerate(runs):
            mode = RUN_MODE_LABELS.get(run.mode, run.mode) + ("（预演）" if run.dry_run else "")
            done, total = run.progress
            cells = (
                _format_time(run.started_at),
                mode,
                node_name(run.target_uid) if run.target_uid else "—",
                RUN_STATE_LABELS.get(run.state, run.state),
                f"{done}/{total}",
                run.run_id,
            )
            for column, text in enumerate(cells):
                self._table.setItem(row, column, QtWidgets.QTableWidgetItem(text))
        self._table.resizeColumnsToContents()
        if runs:
            self._table.selectRow(0)
        self._table.doubleClicked.connect(self.accept)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Open
            | QtWidgets.QDialogButtonBox.StandardButton.Close
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self._table)
        layout.addWidget(buttons)

    def accept(self) -> None:
        row = self._table.currentRow()
        if row >= 0:
            self.selected_run_id = self._table.item(row, len(self.HEADERS) - 1).text()
        super().accept()


# ---------------------------------------------------------------- 主窗口


class MainWindow(QtWidgets.QMainWindow):
    """工作台主窗口：画布编辑、端口格式拦截、运行控制与工作区同步。"""

    def __init__(self, config: Config, registry: ToolRegistry) -> None:
        super().__init__()
        self.config = config
        self.registry = registry
        self.workdir = config.workspace
        self.run_manager = RunManager(self.workdir, registry, config)

        self._revision = 0
        self._declined_revision: int | None = None
        self._prompting = False
        self._tool_classes: dict[str, type[SnakemakeWrapperNode]] = {}
        self._inspections: dict[str, dict[str, InspectResult]] = {}
        self._tasks: set[_Task] = set()
        self._preview_uid: str | None = None
        self._run_id: str | None = None
        self._run_finished = True
        self._log_offset = 0
        self._log_partial = ""

        self.graph = NodeGraph()
        self.graph.set_acyclic(True)
        self.setCentralWidget(self.graph.widget)
        self._setup_graph()
        self._setup_docks()
        self._setup_menus()
        self._setup_toolbar()
        self._setup_status_bar()

        self._poll_timer = QtCore.QTimer(self)
        self._poll_timer.setInterval(POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll_workspace)

        self._load_from_disk()
        self._refresh_index(refresh=False)
        self._poll_timer.start()

    # ---- 初始化

    def _setup_graph(self) -> None:
        for node_class in (*INPUT_NODE_CLASSES, BioOutputNode):
            self.graph.register_node(node_class)
            self._register_node_commands(node_class.type_)
        graph_menu = self.graph.get_context_menu("graph")
        graph_menu.add_command("全量运行", lambda _graph: self._start_run("all"))
        graph_menu.add_command(
            "预演（Dry Run）", lambda _graph: self._start_run("all", dry_run=True)
        )
        graph_menu.add_command("取消当前运行", lambda _graph: self.cancel_run())
        graph_menu.add_command("自动布局", lambda _graph: self.graph.auto_layout_nodes())
        graph_menu.add_command("保存会话", lambda _graph: self.save())

        self.graph.port_connected.connect(self._on_port_connected)
        self.graph.data_dropped.connect(self._on_data_dropped)
        self.graph.node_created.connect(self._on_node_created)
        self.graph.property_changed.connect(self._on_property_changed)
        self.graph.node_selected.connect(self._on_node_selected)
        self.graph.undo_stack().cleanChanged.connect(self._update_title)

    def _setup_docks(self) -> None:
        self.library = ToolLibraryWidget(self.registry)
        self.library.activated.connect(self._add_node_at_center)
        self.properties_bin = PropertiesBinWidget(node_graph=self.graph)

        fixed_font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)
        self.preview_view = QtWidgets.QPlainTextEdit()
        self.preview_view.setReadOnly(True)
        self.preview_view.setFont(fixed_font)
        self.preview_view.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(fixed_font)
        self.log_view.setMaximumBlockCount(LOG_MAX_LINES)

        left = QtCore.Qt.DockWidgetArea.LeftDockWidgetArea
        right = QtCore.Qt.DockWidgetArea.RightDockWidgetArea
        bottom = QtCore.Qt.DockWidgetArea.BottomDockWidgetArea
        self.library_dock = self._add_dock("工具库", self.library, left)
        self.properties_dock = self._add_dock("属性", self.properties_bin, right)
        self.preview_dock = self._add_dock("文件预览", self.preview_view, right)
        self.log_dock = self._add_dock("运行日志", self.log_view, bottom)
        self.splitDockWidget(
            self.properties_dock, self.preview_dock, QtCore.Qt.Orientation.Vertical
        )

    def _add_dock(
        self, title: str, widget: QtWidgets.QWidget, area: QtCore.Qt.DockWidgetArea
    ) -> QtWidgets.QDockWidget:
        dock = QtWidgets.QDockWidget(title, self)
        dock.setObjectName(f"dock_{title}")
        dock.setWidget(widget)
        self.addDockWidget(area, dock)
        return dock

    def _setup_menus(self) -> None:
        keys = QtGui.QKeySequence.StandardKey
        icon = self.style().standardIcon
        pixmap = QtWidgets.QStyle.StandardPixmap
        bar = self.menuBar()

        file_menu = bar.addMenu("文件")
        self._action(file_menu, "新建会话", self.new_session, "Ctrl+N")
        self._action(file_menu, "打开工作区…", self.open_workspace, "Ctrl+O")
        self.save_action = self._action(file_menu, "保存会话", self.save, "Ctrl+S")
        self.save_action.setIcon(icon(pixmap.SP_DialogSaveButton))
        self._action(file_menu, "从磁盘重新加载", self.reload_from_disk)
        file_menu.addSeparator()
        self._action(file_menu, "退出", self.close, "Ctrl+Q")

        # 复制/删除等只在画布获得焦点时生效，避免抢走搜索框、属性面板里的同名快捷键
        edit_menu = bar.addMenu("编辑")
        stack = self.graph.undo_stack()
        undo_action = stack.createUndoAction(self, "撤销")
        undo_action.setShortcut(QtGui.QKeySequence(keys.Undo))
        redo_action = stack.createRedoAction(self, "重做")
        redo_action.setShortcut(QtGui.QKeySequence(keys.Redo))
        edit_menu.addActions([undo_action, redo_action])
        edit_menu.addSeparator()
        self._action(edit_menu, "复制", self._copy_nodes, keys.Copy, canvas_only=True)
        self._action(edit_menu, "粘贴", self._paste_nodes, keys.Paste, canvas_only=True)
        self._action(edit_menu, "删除", self._delete_nodes, keys.Delete, canvas_only=True)
        self._action(edit_menu, "全选", self.graph.select_all, keys.SelectAll, canvas_only=True)

        run_menu = bar.addMenu("运行")
        self.run_action = self._action(run_menu, "全量运行", lambda: self._start_run("all"), "F5")
        self.run_action.setIcon(icon(pixmap.SP_MediaPlay))
        self.dry_run_action = self._action(
            run_menu, "预演（Dry Run）", lambda: self._start_run("all", dry_run=True), "Shift+F5"
        )
        self.dry_run_action.setIcon(icon(pixmap.SP_FileDialogContentsView))
        self.cancel_action = self._action(run_menu, "取消当前运行", self.cancel_run, "Ctrl+F5")
        self.cancel_action.setIcon(icon(pixmap.SP_MediaStop))
        run_menu.addSeparator()
        self.history_action = self._action(run_menu, "运行历史…", self.show_run_history, "Ctrl+H")
        self.history_action.setIcon(icon(pixmap.SP_FileDialogDetailedView))

        library_menu = bar.addMenu("工具库")
        self._action(library_menu, "搜索工具", self._focus_search, "Ctrl+F")
        self._action(library_menu, "刷新工具索引", lambda: self._refresh_index(refresh=True))

        view_menu = bar.addMenu("视图")
        self.fit_action = self._action(
            view_menu, "适应画布", self._fit_canvas, "F", canvas_only=True
        )
        self.fit_action.setIcon(icon(pixmap.SP_TitleBarMaxButton))
        self._action(view_menu, "自动布局", lambda: self.graph.auto_layout_nodes())
        view_menu.addSeparator()
        for dock in (self.library_dock, self.properties_dock, self.preview_dock, self.log_dock):
            view_menu.addAction(dock.toggleViewAction())

    def _action(
        self,
        menu: QtWidgets.QMenu,
        text: str,
        slot: Callable[[], Any],
        shortcut: str | QtGui.QKeySequence.StandardKey | None = None,
        *,
        canvas_only: bool = False,
    ) -> QtGui.QAction:
        action = menu.addAction(text)
        action.triggered.connect(lambda _checked=False: slot())
        if shortcut:
            action.setShortcut(QtGui.QKeySequence(shortcut))
        if canvas_only:
            self.graph.viewer().addAction(action)
            action.setShortcutContext(QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut)
        return action

    def _setup_toolbar(self) -> None:
        toolbar = self.addToolBar("运行")
        toolbar.setObjectName("toolbar_run")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar.addAction(self.save_action)
        toolbar.addSeparator()
        for action in (
            self.run_action,
            self.dry_run_action,
            self.cancel_action,
            self.history_action,
        ):
            toolbar.addAction(action)
        toolbar.addSeparator()
        toolbar.addAction(self.fit_action)

        spacer = QtWidgets.QWidget()
        spacer.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred
        )
        toolbar.addWidget(spacer)
        legend = "　".join(
            _color_swatch(STATE_BORDER_COLORS[state], label)
            for state, label in NODE_STATE_LABELS.items()
        )
        legend_label = QtWidgets.QLabel(f"节点边框：{legend}　")
        legend_label.setToolTip(
            "运行时节点边框颜色对应的状态；输入文件校验失败时边框同样显示为红色。"
        )
        toolbar.addWidget(legend_label)
        self._update_run_actions()

    def _setup_status_bar(self) -> None:
        self.run_label = QtWidgets.QLabel("空闲")
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setMaximumWidth(220)
        self.progress_bar.setFormat("%v/%m")
        self.progress_bar.setValue(0)
        self.statusBar().addPermanentWidget(self.run_label)
        self.statusBar().addPermanentWidget(self.progress_bar)

    def _register_node_commands(self, node_type: str) -> None:
        menu = self.graph.get_context_menu("nodes")
        if schema.is_tool_type(node_type):
            commands: list[tuple[str, Callable[[Any, Any], None]]] = [
                ("运行此步（Step Run）", lambda _g, node: self._start_run("step", node)),
                ("运行至此节点（Run to Here）", lambda _g, node: self._start_run("until", node)),
                ("预览输出文件", lambda _g, node: self._preview_outputs(node)),
                ("用默认程序打开输出", lambda _g, node: self._open_outputs(node)),
                ("查看节点日志", lambda _g, node: self._open_node_log(node)),
                ("打开输出目录", lambda _g, node: self._open_output_dir(node)),
                ("标记为已审核", lambda _g, node: self._mark_reviewed(node)),
            ]
        elif node_type == schema.OUTPUT_NODE:
            commands = [
                ("预览输出文件", lambda _g, node: self._preview_outputs(node)),
                ("用默认程序打开输出", lambda _g, node: self._open_outputs(node)),
            ]
        else:
            commands = [
                (
                    "检查文件（完整统计）",
                    lambda _g, node: self._inspect_input(node, full_stats=True),
                )
            ]
        for text, func in commands:
            menu.add_command(text, func, node_type=node_type)

    # ---- 节点与连线

    def _ensure_tool_type(self, tool_id: str) -> str:
        """按需为 tool_id 生成并注册节点子类，返回其节点类型。"""
        node_type = schema.tool_node_type(tool_id)
        if node_type not in self._tool_classes:
            spec = self.registry.get(tool_id)
            class_name = node_type.removeprefix(schema.TOOL_PREFIX)
            attrs = {"__identifier__": "bio.tool", "NODE_NAME": spec.name, "SPEC": spec}
            node_class = type(class_name, (SnakemakeWrapperNode,), attrs)
            self.graph.register_node(node_class)
            self._register_node_commands(node_type)
            self._tool_classes[node_type] = node_class
        return node_type

    def _add_payload_node(self, payload: str, pos: tuple[float, float]) -> None:
        if payload.startswith(TOOL_MIME_PREFIX):
            try:
                node_type = self._ensure_tool_type(payload.removeprefix(TOOL_MIME_PREFIX))
            except ToolNotWrappedError as exc:
                QtWidgets.QMessageBox.information(
                    self,
                    "工具尚未封装",
                    f"{exc}\n\n请让 Agent 调用 MCP 工具 auto_wrap_bioconda_pkg 完成封装。",
                )
                return
            except WorkstationError as exc:
                self._warn("无法添加工具", str(exc))
                return
        elif payload.startswith(NODE_MIME_PREFIX):
            node_type = payload.removeprefix(NODE_MIME_PREFIX)
        else:
            return
        self.graph.create_node(node_type, pos=[pos[0], pos[1]])

    def _add_node_at_center(self, payload: str) -> None:
        viewer = self.graph.viewer()
        center = viewer.mapToScene(viewer.viewport().rect().center())
        self._add_payload_node(payload, (center.x(), center.y()))

    def _on_data_dropped(self, mime: QtCore.QMimeData, pos: QtCore.QPoint) -> None:
        if mime.hasText():
            self._add_payload_node(mime.text(), (float(pos.x()), float(pos.y())))

    def _on_node_created(self, node: Any) -> None:
        if isinstance(node, BioNode):
            self._ensure_unique_uids()

    def _on_port_connected(self, in_port: Any, out_port: Any) -> None:
        in_node, out_node = in_port.node(), out_port.node()
        if not (isinstance(in_node, BioNode) and isinstance(out_node, BioNode)):
            return
        any_format = (schema.ANY_FORMAT,)
        ok, reason = formats_compatible(
            out_node.output_formats.get(out_port.name(), any_format),
            in_node.input_formats.get(in_port.name(), any_format),
        )
        if ok:
            return
        self._notify(
            f"已拒绝连线 {out_node.name()}.{out_port.name()} → {in_node.name()}.{in_port.name()}：{reason}"
        )
        # 信号在 NodeGraphQt 的撤销宏内发出，延后到事件循环再撤销，可一并恢复被替换的旧连线
        QtCore.QTimer.singleShot(0, lambda: self._revert_connection(in_port, out_port))

    def _revert_connection(self, in_port: Any, out_port: Any) -> None:
        out_node_id = out_port.node().id
        still_connected = any(
            p.node().id == out_node_id and p.name() == out_port.name()
            for p in in_port.connected_ports()
        )
        if not still_connected:
            return
        stack = self.graph.undo_stack()
        top = stack.command(stack.index() - 1)
        if top is not None and top.text().startswith("connect"):
            stack.undo()
        else:
            in_port.disconnect_from(out_port, push_undo=False)

    def _on_property_changed(self, node: Any, name: str, _value: Any) -> None:
        if isinstance(node, BioInputNode) and name in node.KIND.path_props:
            self._inspect_input(node)

    def _on_node_selected(self, node: Any) -> None:
        self.properties_bin.add_node(node)
        if isinstance(node, BioNode):
            self._show_preview(node.uid())

    def _copy_nodes(self) -> None:
        self.graph.copy_nodes()

    def _paste_nodes(self) -> None:
        # 粘贴不触发 node_created，需在此处为副本重新分配 bio_uid
        self.graph.paste_nodes()
        self._ensure_unique_uids()

    def _delete_nodes(self) -> None:
        if nodes := self.graph.selected_nodes():
            self.graph.delete_nodes(nodes)

    def _fit_canvas(self) -> None:
        # NodeGraphQt 只在无选中节点时适配全部节点，因此临时清空选择
        selected = self.graph.selected_nodes()
        self.graph.clear_selection()
        self.graph.fit_to_selection()
        for node in selected:
            node.set_selected(True)

    def _bio_nodes(self) -> list[BioNode]:
        return [node for node in self.graph.all_nodes() if isinstance(node, BioNode)]

    def _node_by_uid(self, uid: str | None) -> BioNode | None:
        return next((node for node in self._bio_nodes() if node.uid() == uid), None)

    def _ensure_unique_uids(self) -> None:
        """复制/粘贴会连同 bio_uid 一起复制，重复者重新分配。"""
        seen: set[str] = set()
        for node in self._bio_nodes():
            uid = node.uid()
            if uid in seen or not schema.is_valid_uid(uid):
                uid = schema.new_uid()
                node.set_property(schema.UID_PROP, uid, push_undo=False)
            seen.add(uid)

    def _set_border(self, node: BioNode, color: RGBA) -> None:
        node.set_property("border_color", color, push_undo=False)

    # ---- 文件检查与预览

    def _submit(
        self,
        func: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_error: Callable[[Any], None] | None = None,
    ) -> None:
        """on_success/on_error 必须是本窗口的方法，以保证信号排队回主线程执行。"""
        self._tasks = {task for task in self._tasks if not task.done}
        task = _Task(func)
        task.signals.succeeded.connect(on_success)
        task.signals.failed.connect(on_error or self._on_task_error)
        self._tasks.add(task)
        QtCore.QThreadPool.globalInstance().start(task)

    def _on_task_error(self, exc: Any) -> None:
        self._notify(f"后台任务失败：{exc}")

    def _inspect_input(self, node: BioInputNode, full_stats: bool = False) -> None:
        uid, paths = node.uid(), node.paths()
        current = self._inspections.setdefault(uid, {})
        for stale in set(current) - set(paths):
            del current[stale]
        if not paths:
            self._set_border(node, DEFAULT_BORDER_COLOR)
            self._refresh_preview_if_shown(uid)
            return
        for path in paths:
            self._submit(functools.partial(_inspect_job, uid, path, full_stats), self._on_inspected)

    def _inspect_paths(self, uid: str, paths: Sequence[str]) -> None:
        self._inspections[uid] = {}
        for path in paths[:MAX_PREVIEW_FILES]:
            self._submit(functools.partial(_inspect_job, uid, path, False), self._on_inspected)
        self._show_preview(uid)

    def _on_inspected(self, payload: tuple[str, InspectResult]) -> None:
        uid, result = payload
        node = self._node_by_uid(uid)
        if isinstance(node, BioInputNode):
            if result.path not in node.paths():
                return
            results = self._inspections.setdefault(uid, {})
            results[result.path] = result
            invalid = any(not r.valid for r in results.values())
            self._set_border(node, INVALID_BORDER_COLOR if invalid else DEFAULT_BORDER_COLOR)
        else:
            self._inspections.setdefault(uid, {})[result.path] = result
        self._refresh_preview_if_shown(uid)

    def _refresh_preview_if_shown(self, uid: str) -> None:
        if self._preview_uid == uid:
            self._show_preview(uid)

    def _show_preview(self, uid: str) -> None:
        self._preview_uid = uid
        results = self._inspections.get(uid)
        if not results:
            self.preview_view.setPlainText(
                "该节点暂无文件检查结果。\n"
                "输入节点：设置文件路径后自动检查；\n"
                "工具/输出节点：运行后右键「预览输出文件」。"
            )
            return
        separator = "\n\n" + "─" * 60 + "\n\n"
        self.preview_view.setPlainText(
            separator.join(format_inspection(r) for r in results.values())
        )

    def _compile_quietly(self) -> Any:
        """只为解析输出/日志路径而编译（不写文件），失败时提示并返回 None。"""
        try:
            return compile_session(
                self._current_session(),
                self.registry,
                self.workdir,
                allow_unreviewed=True,
                allowed_input_roots=self.config.allowed_input_roots,
            )
        except CompileError as exc:
            self._show_compile_error(exc)
            return None

    def _node_output_paths(self, node: BioNode) -> list[str]:
        result = self._compile_quietly()
        if result is None:
            return []
        if isinstance(node, SnakemakeWrapperNode):
            return [path for paths in result.outputs.get(node.uid(), {}).values() for path in paths]
        paths: list[str] = []
        for port in node.inputs().values():
            for upstream_port in port.connected_ports():
                upstream = upstream_port.node()
                if isinstance(upstream, SnakemakeWrapperNode):
                    paths += result.outputs.get(upstream.uid(), {}).get(upstream_port.name(), [])
                elif isinstance(upstream, BioInputNode):
                    paths += upstream.paths()
        return paths

    def _preview_outputs(self, node: BioNode) -> None:
        existing = [path for path in self._node_output_paths(node) if Path(path).exists()]
        if not existing:
            self._notify("输出文件尚未生成，请先运行该节点")
            return
        self._inspect_paths(node.uid(), existing)

    def _open_outputs(self, node: BioNode) -> None:
        existing = [path for path in self._node_output_paths(node) if Path(path).is_file()]
        if not existing:
            self._notify("输出文件尚未生成，请先运行该节点")
            return
        for path in existing[:MAX_OPEN_FILES]:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))
        if len(existing) > MAX_OPEN_FILES:
            self._notify(f"共 {len(existing)} 个输出文件，只打开了前 {MAX_OPEN_FILES} 个")

    def _open_node_log(self, node: SnakemakeWrapperNode) -> None:
        result = self._compile_quietly()
        log_path = result.log_paths.get(node.uid()) if result else None
        if not log_path or not Path(log_path).exists():
            self._notify("该节点尚无日志，请先运行")
            return
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(log_path))

    def _open_output_dir(self, node: SnakemakeWrapperNode) -> None:
        paths = self._node_output_paths(node)
        directory = Path(paths[0]).parent if paths else None
        if directory is None or not directory.exists():
            self._notify("输出目录尚未生成，请先运行该节点")
            return
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(directory)))

    def _mark_reviewed(self, node: SnakemakeWrapperNode) -> None:
        tool_id = node.tool_id()
        try:
            self.registry.mark_reviewed(tool_id)
            spec = self.registry.get(tool_id)
        except WorkstationError as exc:
            self._warn("无法标记为已审核", str(exc))
            return
        node_type = schema.tool_node_type(tool_id)
        self._tool_classes[node_type].SPEC = spec
        for other in self._bio_nodes():
            if isinstance(other, SnakemakeWrapperNode) and other.tool_id() == tool_id:
                other.set_color(*DEFAULT_NODE_COLOR)
        self.library.reload()
        self._notify(f"已将 {spec.name} 标记为已审核")

    # ---- 运行

    def _start_run(self, mode: RunMode, target: Any = None, *, dry_run: bool = False) -> None:
        target_uid = target.uid() if isinstance(target, SnakemakeWrapperNode) else None
        try:
            run_id = self.run_manager.start(
                self._current_session(),
                mode=mode,
                target_uid=target_uid,
                cores=self.config.cores,
                dry_run=dry_run,
            )
        except CompileError as exc:
            self._show_compile_error(exc)
            return
        except WorkstationError as exc:
            self._warn("无法启动运行", str(exc))
            return
        self._follow_run(run_id)

    def cancel_run(self) -> None:
        if self._run_id is None or self._run_finished:
            self._notify("当前没有进行中的运行")
            return
        if self.run_manager.cancel(self._run_id):
            self._notify(f"已请求取消运行 {self._run_id}")

    def show_run_history(self) -> None:
        runs = sorted(
            self.run_manager.list_runs(limit=RUN_HISTORY_LIMIT),
            key=lambda run: run.started_at,
            reverse=True,
        )
        if not runs:
            self._notify("该工作区还没有运行记录")
            return
        dialog = RunHistoryDialog(runs, self._node_name, self)
        if dialog.exec() and dialog.selected_run_id:
            self._follow_run(dialog.selected_run_id)

    def _node_name(self, uid: str) -> str:
        node = self._node_by_uid(uid)
        return node.name() if node is not None else f"（已删除）{uid}"

    def _follow_run(self, run_id: str) -> None:
        """开始跟随某次运行：状态与日志由轮询逐步回放，对已结束的运行同样适用。"""
        self._run_id = run_id
        self._run_finished = False
        self._log_offset = 0
        self._log_partial = ""
        self._reset_run_colors()
        self.log_view.clear()
        self.log_view.appendPlainText(f"===== 运行 {run_id} =====")
        self.log_dock.raise_()
        self._update_run_actions()

    def _update_run_actions(self) -> None:
        idle = self._run_finished
        for action in (self.run_action, self.dry_run_action):
            action.setEnabled(idle)
        self.cancel_action.setEnabled(not idle)

    def _reset_run_colors(self) -> None:
        for node in self._bio_nodes():
            if isinstance(node, SnakemakeWrapperNode):
                self._set_border(node, DEFAULT_BORDER_COLOR)

    def _apply_run_status(self, status: RunStatus) -> None:
        for uid, state in status.node_states.items():
            node = self._node_by_uid(uid)
            if node is not None:
                self._set_border(node, STATE_BORDER_COLORS.get(state, DEFAULT_BORDER_COLOR))
        done, total = status.progress
        self.progress_bar.setRange(0, max(total, 1))
        self.progress_bar.setValue(min(done, max(total, 1)))
        prefix = "预演" if status.dry_run else "运行"
        self.run_label.setText(
            f"{prefix} {status.run_id}：{RUN_STATE_LABELS.get(status.state, status.state)}"
        )

    def _on_run_finished(self, status: RunStatus) -> None:
        if self._log_partial:
            self.log_view.appendPlainText(self._log_partial)
            self._log_partial = ""
        if status.state == "success":
            message = "预演完成" if status.dry_run else "运行成功，可右键输出节点预览结果"
        elif status.state == "failed":
            message = f"运行失败（rule：{status.failed_rule or '未知'}），详见运行日志"
        else:
            message = f"运行已结束：{RUN_STATE_LABELS.get(status.state, status.state)}"
        self._notify(message)

    def _tail_log(self, log_path: str) -> None:
        if not log_path:
            return
        try:
            with Path(log_path).open(encoding="utf-8", errors="replace") as handle:
                handle.seek(self._log_offset)
                chunk = handle.read()
                self._log_offset = handle.tell()
        except OSError:
            return
        if not chunk:
            return
        lines = (self._log_partial + chunk).split("\n")
        self._log_partial = lines.pop()
        for line in lines:
            self.log_view.appendPlainText(line)

    # ---- 工作区同步

    def _poll_workspace(self) -> None:
        if self._prompting:
            return
        self._check_session_revision()
        self._check_runs()

    def _check_session_revision(self) -> None:
        try:
            revision = read_revision(self.workdir)
        except (OSError, WorkstationError):
            return
        if revision in (self._revision, self._declined_revision):
            return
        if self._is_dirty():
            answer = self._ask(
                "画布已在外部修改",
                "Agent（或其他进程）修改了 session.json。\n是否重新加载？本地未保存的修改将丢失。",
            )
            if answer != QtWidgets.QMessageBox.StandardButton.Yes:
                self._declined_revision = revision
                return
        self._load_from_disk()
        self._notify("已同步外部对画布的修改")

    def _check_runs(self) -> None:
        latest = self.run_manager.list_runs(limit=1)
        if latest and latest[0].run_id != self._run_id and not latest[0].finished:
            self._notify(f"检测到新的运行 {latest[0].run_id}（可能由 Agent 发起）")
            self._follow_run(latest[0].run_id)
        if self._run_id is None or self._run_finished:
            return
        try:
            status = self.run_manager.status(self._run_id)
        except WorkstationError:
            return
        self._tail_log(status.log_path)
        self._apply_run_status(status)
        if status.finished:
            self._run_finished = True
            self._update_run_actions()
            self._on_run_finished(status)

    # ---- 会话

    def _current_session(self) -> dict[str, Any]:
        self._ensure_unique_uids()
        return self.graph.serialize_session()

    def _is_dirty(self) -> bool:
        return not self.graph.undo_stack().isClean()

    def _load_from_disk(self) -> None:
        try:
            session, revision = load_session(self.workdir)
        except WorkstationError as exc:
            self._warn("无法读取会话", str(exc))
            return
        session, warnings = sanitize_session(session, self.registry)
        for warning in warnings:
            self.log_view.appendPlainText(f"[会话] {warning}")
        for _key, entry in schema.iter_nodes(session):
            tool_id = entry.get("custom", {}).get(schema.TOOL_ID_PROP)
            if schema.is_tool_type(entry.get("type_", "")) and tool_id:
                try:
                    self._ensure_tool_type(tool_id)
                except WorkstationError as exc:
                    self.log_view.appendPlainText(f"[会话] {exc}")
        if session.get("nodes"):
            self.graph.deserialize_session(session)
        else:
            self.graph.clear_session()
            self.graph.clear_undo_stack()
        self._revision = revision
        self._declined_revision = None
        self._inspections.clear()
        self._reset_run_colors()
        for node in self._bio_nodes():
            if isinstance(node, BioInputNode):
                self._inspect_input(node)
        self._update_title()

    def save(self) -> bool:
        session = self._current_session()
        try:
            self._revision = save_session(
                self.workdir, session, expected_revision=self._revision, updated_by="ui"
            )
        except SessionConflictError:
            buttons = QtWidgets.QMessageBox.StandardButton
            answer = self._ask(
                "保存冲突",
                "磁盘上的会话已被 Agent 修改。\n「是」覆盖磁盘版本；「否」放弃本地修改并重新加载。",
                buttons.Yes | buttons.No | buttons.Cancel,
            )
            if answer == buttons.No:
                self._load_from_disk()
                return False
            if answer != buttons.Yes:
                return False
            self._revision = save_session(
                self.workdir, session, expected_revision=None, updated_by="ui"
            )
        except WorkstationError as exc:
            self._warn("保存失败", str(exc))
            return False
        self.graph.undo_stack().setClean()
        self._declined_revision = None
        self._notify(f"已保存到 {self.workdir / schema.SESSION_FILE}")
        return True

    def reload_from_disk(self) -> None:
        if self._is_dirty() and not self._confirm_discard():
            return
        self._load_from_disk()

    def new_session(self) -> None:
        if self._is_dirty() and not self._confirm_discard():
            return
        self.graph.clear_session()
        self.graph.clear_undo_stack()
        self._inspections.clear()
        self.preview_view.clear()
        self._update_title()

    def open_workspace(self) -> None:
        if self._is_dirty() and not self._confirm_discard():
            return
        chosen = QtWidgets.QFileDialog.getExistingDirectory(
            self, "选择工作区目录", str(self.workdir)
        )
        if not chosen:
            return
        self.workdir = Path(chosen)
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.run_manager = RunManager(self.workdir, self.registry, self.config)
        self._run_id = None
        self._run_finished = True
        self._update_run_actions()
        self.log_view.clear()
        self.run_label.setText("空闲")
        self.progress_bar.setValue(0)
        self._load_from_disk()

    def _confirm_discard(self) -> bool:
        answer = self._ask("放弃未保存的修改？", "当前画布有未保存的修改，继续将丢失这些修改。")
        return answer == QtWidgets.QMessageBox.StandardButton.Yes

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802 (Qt 覆写)
        if self._is_dirty():
            buttons = QtWidgets.QMessageBox.StandardButton
            answer = self._ask(
                "退出", "是否保存当前画布？", buttons.Save | buttons.Discard | buttons.Cancel
            )
            if answer == buttons.Cancel or (answer == buttons.Save and not self.save()):
                event.ignore()
                return
        if self._run_id and not self._run_finished:
            QtWidgets.QMessageBox.information(
                self, "运行仍在继续", "Snakemake 会在后台继续运行，重新打开工作台即可查看进度。"
            )
        self._poll_timer.stop()
        event.accept()

    # ---- 索引

    def _refresh_index(self, refresh: bool) -> None:
        self._notify("正在更新工具索引…" if refresh else "正在加载工具索引…")
        self._submit(lambda: self.registry.build_index(refresh=refresh), self._on_index_built)

    def _on_index_built(self, _result: Any) -> None:
        self.library.reload()
        self._notify("工具索引已就绪")

    def _focus_search(self) -> None:
        self.library_dock.show()
        self.library.search_edit.setFocus()
        self.library.search_edit.selectAll()

    # ---- 提示

    def _update_title(self, *_args: Any) -> None:
        marker = " *" if self._is_dirty() else ""
        self.setWindowTitle(f"OpenBioWorkstation — {self.workdir}{marker}")

    def _notify(self, message: str) -> None:
        self.statusBar().showMessage(message, 6000)
        self.log_view.appendPlainText(f"[界面] {message}")
        logger.info(message)

    def _warn(self, title: str, message: str) -> None:
        QtWidgets.QMessageBox.warning(self, title, message)

    def _ask(
        self,
        title: str,
        message: str,
        buttons: QtWidgets.QMessageBox.StandardButton | None = None,
    ) -> QtWidgets.QMessageBox.StandardButton:
        standard = QtWidgets.QMessageBox.StandardButton
        self._prompting = True
        try:
            return QtWidgets.QMessageBox.question(
                self, title, message, buttons or (standard.Yes | standard.No)
            )
        finally:
            self._prompting = False

    def _show_compile_error(self, exc: CompileError) -> None:
        node = self._node_by_uid(exc.uid)
        if node is not None:
            self._set_border(node, INVALID_BORDER_COLOR)
            self.graph.clear_selection()
            node.set_selected(True)
        self._warn("画布无法编译", str(exc))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenBioWorkstation 桌面工作台")
    parser.add_argument("--workspace", type=Path, help="项目工作区目录（默认取配置文件）")
    parser.add_argument("--config", type=Path, help="配置文件（默认 ~/.config/biows/config.yaml）")
    parser.add_argument("-v", "--verbose", action="store_true", help="输出调试日志")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = load_config(args.config, workspace=args.workspace)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
    app.setApplicationName("OpenBioWorkstation")
    window = MainWindow(config, ToolRegistry.from_config(config))
    window.resize(1600, 960)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
