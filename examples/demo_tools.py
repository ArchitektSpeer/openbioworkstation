"""Offline demo commands: use the shared C-backed inspector, then render its JSON."""

import argparse
import html
import json
from pathlib import Path

from glue.bio_inspector import inspect_bio_file


def inspect(paths, output):
    results = [inspect_bio_file(path, full_stats=True).to_dict() for path in paths]
    errors = [result["error"] for result in results if not result["valid"]]
    if errors:
        raise ValueError("; ".join(errors))
    Path(output).write_text(json.dumps(results, ensure_ascii=False, indent=2))


def report(reads, reference, html_path, json_path):
    payload = {
        "title": "OpenBioWorkstation 离线演示",
        "reads": json.loads(Path(reads).read_text()),
        "reference": json.loads(Path(reference).read_text()),
    }
    Path(json_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    rows = []
    for group in ("reads", "reference"):
        for result in payload[group]:
            rows.append(
                "<tr>"
                + "".join(
                    "<td>" + html.escape(str(value)) + "</td>"
                    for value in (
                        Path(result["path"]).name,
                        result["format"],
                        result["stats"].get("records", ""),
                        result["stats"].get("total_bases", ""),
                        "通过" if result["valid"] else "失败",
                    )
                )
                + "</tr>"
            )
    document = """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>OpenBioWorkstation 演示报告</title><style>
body{font:16px system-ui;margin:60px auto;max-width:1000px;background:#101820;color:#e8f0f4}
h1{color:#63d9b6}p{color:#aac0ce}table{width:100%;border-collapse:collapse;background:#1a2833}
th,td{text-align:left;padding:18px;border-bottom:1px solid #344956}th{color:#63d9b6}
.badge{display:inline-block;padding:7px 14px;border:1px solid #63d9b6;border-radius:20px}
</style><span class="badge">OFFLINE DEMO · 真实执行</span>
<h1>从测序文件到检查报告</h1><p>文件由 pyfastx 经共享检查接口读取，任务由 Snakemake 执行。此演示展示输入、连线、缓存、单步运行与报告输出，不执行比对或变异分析。</p>
<table><thead><tr><th>文件</th><th>格式</th><th>序列数</th><th>总碱基数</th><th>检查</th></tr></thead><tbody>"""
    Path(html_path).write_text(document + "".join(rows) + "</tbody></table></html>")


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    inspection = commands.add_parser("inspect")
    inspection.add_argument("--input", nargs="+", required=True)
    inspection.add_argument("--output", required=True)
    reporting = commands.add_parser("report")
    reporting.add_argument("--reads", required=True)
    reporting.add_argument("--reference", required=True)
    reporting.add_argument("--html", required=True)
    reporting.add_argument("--json", required=True)
    args = parser.parse_args()
    if args.command == "inspect":
        inspect(args.input, args.output)
    else:
        report(args.reads, args.reference, args.html, args.json)


if __name__ == "__main__":
    main()
