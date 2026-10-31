"""Launch a prepared offline demo with local tools and genuine Snakemake execution."""

import argparse
import shlex
import sys
from dataclasses import replace
from pathlib import Path

from glue import session_schema as s
from glue.config import load_config
from glue.models import ExecSpec, PortSpec, ToolSpec
from glue.session_store import save_session
from glue.wrapper_registry import ToolRegistry, index_entry

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACE = ROOT / "demo_workspace"


class DemoAdapter:
    source = "local-demo"

    def __init__(self):
        command = shlex.join([sys.executable, str(ROOT / "examples/demo_tools.py")])

        def port(name, fmt, multiple=False):
            return PortSpec(name, (fmt,), multiple)

        self.specs = {}
        for name, title, fmt, multiple in (
            ("reads", "01 · 测序文件检查", "FASTQ", True),
            ("reference", "02 · 参考序列检查", "FASTA", False),
        ):
            spec = ToolSpec(
                "demo:" + name,
                title,
                "离线演示",
                self.source,
                "使用共享 inspect_bio_file 完整读取文件；不下载工具环境。",
                ("demo", "offline", fmt),
                (port("files", fmt, multiple),),
                (port("stats", "JSON"),),
                (),
                ExecSpec(
                    "shell",
                    shell=command + " inspect --input {input.files:q} --output {output.stats:q}",
                ),
            )
            self.specs[spec.tool_id] = spec
        spec = ToolSpec(
            "demo:report",
            "03 · 汇总演示报告",
            "离线演示",
            self.source,
            "合并测序与参考序列检查结果，输出 HTML 和 JSON。",
            ("demo", "report", "offline"),
            (port("reads", "JSON"), port("reference", "JSON")),
            (port("html", "HTML"), port("json", "JSON")),
            (),
            ExecSpec(
                "shell",
                shell=command
                + " report --reads {input.reads:q} --reference {input.reference:q} --html {output.html:q} --json {output.json:q}",
            ),
        )
        self.specs[spec.tool_id] = spec

    def iter_index(self):
        return iter(index_entry(spec) for spec in self.specs.values())

    def load_spec(self, tool_id):
        return self.specs[tool_id]


def demo_context(workspace=DEFAULT_WORKSPACE):
    workspace = Path(workspace).resolve()
    config = replace(
        load_config(workspace=workspace),
        data_dir=workspace / ".biows/data",
        cache_dir=workspace / ".biows/cache",
        upstream_dir=workspace / ".biows/upstream",
        conda_prefix=workspace / ".biows/envs",
        cores=2,
    )
    registry = ToolRegistry.from_config(config)
    registry.adapters.append(DemoAdapter())
    return config, registry


def prepare_demo(workspace=DEFAULT_WORKSPACE, reset=False):
    config, registry = demo_context(workspace)
    workspace = config.workspace
    workspace.mkdir(parents=True, exist_ok=True)
    if (workspace / s.SESSION_FILE).exists() and not reset:
        return config, registry
    inputs = workspace / "inputs"
    inputs.mkdir(exist_ok=True)
    for mate in (1, 2):
        records = []
        for i in range(1, 13):
            sequence = ("ACGT" if mate == 1 else "TGCA") * 20
            records.append(f"@demo_read_{i}/{mate}\n{sequence}\n+\n" + "I" * len(sequence) + "\n")
        (inputs / f"sample_R{mate}.fastq").write_text("".join(records))
    (inputs / "reference.fa").write_text(">demo_reference\n" + "ACGT" * 250 + "\n")
    fastq = s.INPUT_KIND_BY_MCP["fastq_input"]
    fasta = s.INPUT_KIND_BY_MCP["fasta_reference"]
    nodes = {
        "reads": s.node_entry(
            fastq.node_type,
            "双端 FASTQ · 12 对 reads",
            s.input_custom_defaults(fastq, "de000001")
            | {
                "path_r1": str(inputs / "sample_R1.fastq"),
                "path_r2": str(inputs / "sample_R2.fastq"),
            },
            (0, 0),
        ),
        "reference": s.node_entry(
            fasta.node_type,
            "参考序列 · 1000 bp",
            s.input_custom_defaults(fasta, "de000002") | {"path": str(inputs / "reference.fa")},
            (0, 280),
        ),
    }
    for name, uid, pos in (
        ("reads", "de000003", (380, 0)),
        ("reference", "de000004", (380, 280)),
        ("report", "de000005", (800, 100)),
    ):
        spec = registry.get("demo:" + name)
        nodes["tool_" + name] = s.node_entry(
            s.tool_node_type(spec.tool_id), spec.name, s.tool_custom_defaults(spec, uid), pos
        )
    nodes["output"] = s.node_entry(
        s.OUTPUT_NODE,
        "演示结果 · HTML / JSON",
        s.output_custom_defaults("de000006") | {"label": "离线演示结果"},
        (1220, 100),
    )
    edges = [
        s.connection_entry("reads", "reads", "tool_reads", "files"),
        s.connection_entry("reference", "fasta", "tool_reference", "files"),
        s.connection_entry("tool_reads", "stats", "tool_report", "reads"),
        s.connection_entry("tool_reference", "stats", "tool_report", "reference"),
        s.connection_entry("tool_report", "html", "output", "files"),
        s.connection_entry("tool_report", "json", "output", "files"),
    ]
    save_session(workspace, {"nodes": nodes, "connections": edges}, updated_by="demo")
    return config, registry


def main():
    parser = argparse.ArgumentParser(description="离线 UI 演示：文件检查 → 统计 → 报告")
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--reset", action="store_true", help="重置演示画布和示例输入")
    args = parser.parse_args()
    config, registry = prepare_demo(args.workspace, args.reset)
    if args.prepare_only:
        print(config.workspace)
        return 0
    from PySide6 import QtCore, QtWidgets

    from ui.workstation_window import MainWindow

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
    window = MainWindow(config, registry)
    window.setWindowTitle("OpenBioWorkstation · 离线演示")
    window.resize(1680, 1000)
    window.show()

    def fit_canvas():
        window.graph.clear_selection()
        window.graph.fit_to_selection()

    QtCore.QTimer.singleShot(350, fit_canvas)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
