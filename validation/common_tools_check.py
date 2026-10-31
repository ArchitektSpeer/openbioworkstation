"""Reproducible check for the locally installed fastp/bwa/samtools/bcftools/seqkit nodes.

Creates a synthetic 12-node workspace, executes it through RunManager (real Snakemake
run), validates the artefacts with pysam/pyfastx, then runs an offscreen UI pass and an
MCP catalog query. Synthetic data only; no real biological sample is analysed.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from glue import session_schema as schema  # noqa: E402
from glue.config import load_config  # noqa: E402
from glue.models import ToolSource  # noqa: E402
from glue.session_store import load_session, save_session  # noqa: E402
from glue.snakemake_bridge import RunManager, compile_session  # noqa: E402
from glue.wrapper_registry import ToolRegistry  # noqa: E402

WORKSPACE = ROOT / "common_tools_workspace"
RESULT_JSON = ROOT / "validation" / "common-tools-result.json"
ENV_YML = ROOT / "validation" / "common-tools-environment.yml"
UI_JSON = ROOT / "validation" / "common-tools-ui.json"
UI_SCRIPT = ROOT / "validation" / "common_tools_ui.py"
ENV_PREFIX = Path(
    os.environ.get(
        "BIOWS_COMMON_ENV",
        Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "biows/common-tools",
    )
)
PACKAGES = ("fastp", "bwa", "samtools", "bcftools", "seqkit")

UIDS = {
    "fastq": "c7000001",
    "ref": "c7000002",
    "vcf": "c7000003",
    "fastp": "c7000004",
    "bwa_idx": "c7000005",
    "bwa_mem": "c7000006",
    "view": "c7000007",
    "sort": "c7000008",
    "index": "c7000009",
    "seqkit": "c700000a",
    "bcftools": "c700000b",
    "out": "c700000c",
}

COMPLEMENT = str.maketrans("ACGT", "TGCA")


def revcomp(seq: str) -> str:
    return seq.translate(COMPLEMENT)[::-1]


def write_synthetic_inputs(inputs: Path, rng: random.Random) -> dict:
    inputs.mkdir(parents=True, exist_ok=True)
    reference = "".join(rng.choice("ACGT") for _ in range(2000))
    # A random 2000 bp sequence has essentially no duplicated 12-mers; assert it explicitly.
    kmers = {reference[i : i + 12] for i in range(len(reference) - 11)}
    if len(kmers) != len(reference) - 11:
        raise RuntimeError("合成参考序列出现重复 12-mer")
    (inputs / "synth_ref.fa").write_text(f">synth_chr1\n{reference}\n")

    r1_path, r2_path = inputs / "sample_R1.fastq.gz", inputs / "sample_R2.fastq.gz"
    with gzip.open(r1_path, "wt") as r1, gzip.open(r2_path, "wt") as r2:
        for i in range(24):
            start = rng.randrange(0, len(reference) - 100)
            fragment = reference[start : start + 100]
            r1.write(f"@SYN{i + 1:04d}/1\n{fragment}\n+\n{'I' * 100}\n")
            r2.write(f"@SYN{i + 1:04d}/2\n{revcomp(fragment)}\n+\n{'I' * 100}\n")

    pos = 500
    ref_base = reference[pos - 1]
    alt_base = next(base for base in "ACGT" if base != ref_base)
    vcf = inputs / "variants.vcf"
    vcf.write_text(
        "##fileformat=VCFv4.2\n"
        "##contig=<ID=synth_chr1,length=2000>\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSYNTH\n"
        f"synth_chr1\t{pos}\t.\t{ref_base}\t{alt_base}\t60\tPASS\t.\tGT\t0/1\n"
    )
    return {
        "reference": reference,
        "r1": r1_path,
        "r2": r2_path,
        "vcf": vcf,
        "variant": {"pos": pos, "ref": ref_base, "alt": alt_base},
    }


def build_session(registry: ToolRegistry, data: dict) -> dict:
    def tool(key: str, uid: str, pos: tuple[float, float]):
        spec = registry.get(f"local:{key}")
        return schema.node_entry(
            schema.tool_node_type(spec.tool_id),
            spec.name,
            schema.tool_custom_defaults(spec, uid),
            pos,
        )

    nodes = {
        "fastq": schema.node_entry(
            schema.FASTQ_INPUT,
            "sample FASTQ",
            schema.input_custom_defaults(schema.INPUT_KINDS[0], UIDS["fastq"])
            | {"path_r1": "inputs/sample_R1.fastq.gz", "path_r2": "inputs/sample_R2.fastq.gz"},
            (0, -180),
        ),
        "ref": schema.node_entry(
            schema.FASTA_INPUT,
            "synth reference",
            schema.input_custom_defaults(schema.INPUT_KINDS[1], UIDS["ref"])
            | {"path": "inputs/synth_ref.fa"},
            (0, 40),
        ),
        "vcf": schema.node_entry(
            schema.VCF_INPUT,
            "synthetic VCF",
            schema.input_custom_defaults(schema.INPUT_KINDS[3], UIDS["vcf"])
            | {"path": "inputs/variants.vcf"},
            (0, 260),
        ),
        "fastp": tool("fastp", UIDS["fastp"], (280, -180)),
        "bwa_idx": tool("bwa/index", UIDS["bwa_idx"], (280, 40)),
        "bwa_mem": tool("bwa/mem", UIDS["bwa_mem"], (560, -80)),
        "view": tool("samtools/view", UIDS["view"], (840, -80)),
        "sort": tool("samtools/sort", UIDS["sort"], (1120, -80)),
        "index": tool("samtools/index", UIDS["index"], (1400, -80)),
        "seqkit": tool("seqkit/stats", UIDS["seqkit"], (840, -320)),
        "bcftools": tool("bcftools/stats", UIDS["bcftools"], (280, 260)),
        "out": schema.node_entry(
            schema.OUTPUT_NODE, "汇总输出", schema.output_custom_defaults(UIDS["out"]), (1680, 80)
        ),
    }
    connections = [
        schema.connection_entry("fastq", "reads", "fastp", "sample"),
        schema.connection_entry("ref", "fasta", "bwa_idx", "fasta"),
        schema.connection_entry("fastp", "trimmed", "bwa_mem", "reads"),
        schema.connection_entry("bwa_idx", "idx", "bwa_mem", "idx"),
        schema.connection_entry("bwa_mem", "sam", "view", "sam"),
        schema.connection_entry("view", "bam", "sort", "bam"),
        schema.connection_entry("sort", "bam", "index", "bam"),
        schema.connection_entry("fastp", "trimmed", "seqkit", "reads"),
        schema.connection_entry("vcf", "vcf", "bcftools", "variants"),
        schema.connection_entry("index", "bai", "out", "files"),
        schema.connection_entry("seqkit", "stats", "out", "files"),
        schema.connection_entry("bcftools", "stats", "out", "files"),
    ]
    return {"nodes": nodes, "connections": connections}


def wait_run(manager: RunManager, run_id: str, timeout=120.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = manager.status(run_id)
        if status.finished:
            return status
        time.sleep(0.25)
    manager.cancel(run_id)
    raise TimeoutError(f"运行 {run_id} 超过 {timeout}s 未结束")


def cli_versions() -> dict[str, str]:
    commands = {
        "fastp": ["fastp", "--version"],
        "bwa": ["bwa"],
        "samtools": ["samtools", "--version"],
        "bcftools": ["bcftools", "--version"],
        "seqkit": ["seqkit", "version"],
    }
    env = dict(os.environ, PATH=str(ENV_PREFIX / "bin") + os.pathsep + os.environ["PATH"])
    result = {}
    for name, command in commands.items():
        process = subprocess.run(
            [str(ENV_PREFIX / "bin" / command[0]), *command[1:]],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        output = (process.stdout + process.stderr).strip()
        if name == "bwa":
            match = re.search(r"Version:\s*(\S+)", output)
            result[name] = f"bwa {match.group(1)}" if match else output.splitlines()[0]
        else:
            result[name] = output.splitlines()[0] if output else ""
    return result


def write_environment(versions: dict[str, str]) -> None:
    conda = shutil.which("conda") or "/opt/miniconda3/bin/conda"
    exported = ""
    if Path(conda).exists():
        process = subprocess.run(
            [conda, "env", "export", "--from-history", "-p", str(ENV_PREFIX)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        exported = process.stdout
    history = (ENV_PREFIX / "conda-meta/history").read_text().splitlines()
    exact = []
    for line in history:
        if not line.startswith("+"):
            continue
        chunks = line.removeprefix("+").split("::", 1)[-1].rsplit("-", 2)
        if len(chunks) == 3:
            exact.append(f"#   {chunks[0]} {chunks[1]} {chunks[2]}")
    requested = next(
        (line.split(":", 1)[1].strip() for line in history if line.startswith("# update specs:")),
        "['fastp', 'bwa', 'samtools', 'bcftools', 'seqkit']",
    )
    create = next((line[7:] for line in history if line.startswith("# cmd:")), "unknown")
    create = create.replace(str(ENV_PREFIX), "<env-prefix>")
    body = [
        "# Generated by validation/common_tools_check.py",
        "# `conda env export --from-history` output, machine-specific name/prefix removed",
        "# and channels aligned with the actual creation command (conda-forge + bioconda).",
        f"# create command: {create}",
        "name: biows-common-tools",
        "channels:",
        "  - conda-forge",
        "  - bioconda",
        "dependencies:",
    ]
    if exported.strip():
        deps = [
            line
            for line in exported.splitlines()
            if line.startswith("  - ") and "defaults" not in line
        ]
        body += deps
    else:
        body += [f"  - {name}" for name in PACKAGES]
    body += [
        f"# requested: {requested}",
        "# Exact conda-meta versions (name version build):",
        *exact,
        "# CLI version output:",
        *(f"#   {name}: {version}" for name, version in versions.items()),
    ]
    ENV_YML.write_text("\n".join(body) + "\n")


def validate_outputs(compiled, status, data: dict) -> dict:
    import pyfastx
    import pysam

    out = compiled.outputs
    fastp_paths = out[UIDS["fastp"]]
    fastp_json = json.loads(Path(fastp_paths["json"][0]).read_text())
    fastp_html = Path(fastp_paths["html"][0])
    before = fastp_json["summary"]["before_filtering"]
    after = fastp_json["summary"]["after_filtering"]
    assert before["total_reads"] == 48, before
    assert before["total_bases"] == 4800, before
    assert after["total_reads"] == 48, after
    assert fastp_html.stat().st_size > 1000 and "fastp" in fastp_html.read_text()

    trimmed = fastp_paths["trimmed"]
    assert len(trimmed) == 2, trimmed
    trimmed_counts = [sum(1 for _ in pyfastx.Fastx(path)) for path in trimmed]
    assert trimmed_counts == [24, 24], trimmed_counts

    sam_path = Path(out[UIDS["bwa_mem"]]["sam"][0])
    sam_lines = [
        line for line in sam_path.read_text().splitlines() if line and not line.startswith("@")
    ]
    sam_header = [line for line in sam_path.read_text().splitlines() if line.startswith("@")]
    assert len(sam_lines) == 48, len(sam_lines)
    mapped_sam = sum(1 for line in sam_lines if not int(line.split("\t")[1]) & 4)
    assert mapped_sam >= 1, mapped_sam
    assert any(line.startswith("@SQ") and "LN:2000" in line for line in sam_header)

    view_bam = Path(out[UIDS["view"]]["bam"][0])
    pysam.quickcheck(str(view_bam))  # raises on a truncated/corrupt BAM
    with pysam.AlignmentFile(view_bam, "rb") as handle:
        view_reads = sum(1 for _ in handle)
    assert view_reads == 48, view_reads

    bam_path = Path(out[UIDS["sort"]]["bam"][0])
    bai_path = Path(out[UIDS["index"]]["bai"][0])
    assert bai_path.is_file() and bai_path.stat().st_size > 0, bai_path
    pysam.quickcheck(str(bam_path))  # raises on a truncated/corrupt BAM
    with pysam.AlignmentFile(bam_path, "rb", index_filename=str(bai_path)) as handle:
        reads = list(handle)
        mapped = sum(1 for read in reads if not read.is_unmapped)
        assert len(reads) == 48, len(reads)
        assert mapped == 48, mapped
        assert tuple(handle.references) == ("synth_chr1",), handle.references
        assert tuple(handle.lengths) == (2000,), handle.lengths
        assert sum(1 for _ in handle.fetch("synth_chr1", 0, 2000)) == 48

    seqkit_path = Path(out[UIDS["seqkit"]]["stats"][0])
    seqkit_lines = [line for line in seqkit_path.read_text().splitlines() if line]
    seqkit_header = seqkit_lines[0].split("\t")
    seqkit_rows = [
        dict(zip(seqkit_header, line.split("\t"), strict=True)) for line in seqkit_lines[1:]
    ]
    assert len(seqkit_rows) == 2, seqkit_rows
    for row in seqkit_rows:
        assert int(row["num_seqs"]) == 24, row
        assert int(row["sum_len"]) == 2400, row
        assert float(row["avg_len"]) == 100.0, row

    bcftools_path = Path(out[UIDS["bcftools"]]["stats"][0])
    stats = {}
    for line in bcftools_path.read_text().splitlines():
        fields = line.split("\t")
        if len(fields) >= 4 and fields[0] == "SN":
            stats[fields[2].rstrip(":")] = int(fields[3])
    assert stats.get("number of records") == 1, stats
    assert stats.get("number of SNPs") == 1, stats

    output_paths = [Path(path) for path in out[UIDS["out"]]["files"]]
    assert len(output_paths) == 3 and all(path.is_file() for path in output_paths)
    assert {path.suffix for path in output_paths} == {".bai", ".tsv", ".txt"}, output_paths

    assert status.state == "success", status.to_dict()
    assert all(state == "done" for state in status.node_states.values()), status.node_states

    return {
        "fastp": {
            "json": str(fastp_paths["json"][0]),
            "html": str(fastp_html),
            "before_reads": before["total_reads"],
            "before_bases": before["total_bases"],
            "after_reads": after["total_reads"],
            "trimmed_reads_per_file": trimmed_counts,
        },
        "sam": {"path": str(sam_path), "records": len(sam_lines), "mapped": mapped_sam},
        "bam": {
            "path": str(bam_path),
            "index": str(bai_path),
            "records": 48,
            "mapped": 48,
            "reference": "synth_chr1",
            "length": 2000,
            "quickcheck": "ok",
        },
        "seqkit": {"path": str(seqkit_path), "rows": seqkit_rows},
        "bcftools": {"path": str(bcftools_path), "summary": stats},
        "output_node": [str(path) for path in output_paths],
        "synthetic_variant": data["variant"],
    }


def mcp_local_count(config, registry) -> dict:
    from mcp_server.bio_mcp import create_server

    server = create_server(config, registry)
    tool = server._tool_manager._tools["search_bio_tools"].fn
    found = {}
    for query in PACKAGES:
        page = asyncio.run(tool(query=query, limit=50))
        items = page["items"] if isinstance(page, dict) else page.items
        for item in items:
            tool_id = item["tool_id"] if isinstance(item, dict) else item.tool_id
            source = item["source"] if isinstance(item, dict) else item.source
            if tool_id.startswith("local:"):
                found[tool_id] = source
    return {
        "local_tool_ids": sorted(found),
        "count": len(found),
        "sources": sorted(set(found.values())),
    }


def run_ui() -> dict:
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    process = subprocess.run(
        [sys.executable, str(UI_SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        cwd=ROOT,
    )
    (ROOT / "validation" / "common-tools-ui.log").write_text(process.stdout + process.stderr)
    if process.returncode != 0:
        raise RuntimeError(f"UI 检查失败：\n{process.stdout}\n{process.stderr}")
    return json.loads(UI_JSON.read_text())


def main() -> int:
    started = datetime.now(UTC).isoformat()
    rng = random.Random(20261030)
    data = write_synthetic_inputs(WORKSPACE / "inputs", rng)
    config = replace(load_config(workspace=WORKSPACE), cores=4)
    registry = ToolRegistry.from_config(config)
    registry.build_index(refresh=True)

    from glue.installed_tools import InstalledToolsAdapter

    adapter = next(a for a in registry.adapters if isinstance(a, InstalledToolsAdapter))
    installed = adapter.packages()
    assert "local-installed" in get_args(ToolSource)
    local_entries = {
        entry.tool_id: entry
        for entry in registry._entries.values()
        if entry.tool_id.startswith("local:")
    }
    assert len(local_entries) == 8, sorted(local_entries)
    assert all(entry.source == "local-installed" for entry in local_entries.values())
    registry_checks = {
        "local_count": len(local_entries),
        "source": sorted({entry.source for entry in local_entries.values()}),
        "tool_source_literal": "local-installed" in get_args(ToolSource),
        "ports": {
            tool_id: {
                "inputs": [f"{p.name}:{'/'.join(p.formats)}" for p in registry.get(tool_id).inputs],
                "outputs": [
                    f"{p.name}:{'/'.join(p.formats)}" for p in registry.get(tool_id).outputs
                ],
            }
            for tool_id in sorted(local_entries)
        },
    }
    session = build_session(registry, data)
    revision = save_session(WORKSPACE, session, updated_by="common-tools-check")
    loaded, loaded_revision = load_session(WORKSPACE)
    assert loaded_revision == revision
    assert len(loaded["nodes"]) == 12 and len(loaded["connections"]) == 12

    compiled = compile_session(
        loaded, registry, WORKSPACE, allowed_input_roots=config.allowed_input_roots
    )
    manager = RunManager(WORKSPACE, registry, config)
    # Remove artefacts from earlier attempts so every node really executes (no cache hits).
    for name in ("results", ".snakemake", "logs", "benchmarks"):
        shutil.rmtree(WORKSPACE / name, ignore_errors=True)
    run_id = manager.start(loaded, mode="all", cores=4)
    status = wait_run(manager, run_id, timeout=120)
    log_tail = Path(status.log_path).read_text(errors="replace")[-4000:]
    if status.state != "success":
        raise RuntimeError(f"运行失败：{status.to_dict()}\n{log_tail}")

    checks = validate_outputs(compiled, status, data)
    versions = cli_versions()
    write_environment(versions)
    mcp = mcp_local_count(config, registry)
    assert mcp["count"] == 8, mcp
    ui = run_ui()
    assert ui["nodes"] == 12 and ui["connections"] == 12, ui
    assert ui["local_in_library"] == 8, ui
    assert ui["save_reload_ok"] is True, ui

    payload = {
        "generated_at": started,
        "finished_at": datetime.now(UTC).isoformat(),
        "workspace": str(WORKSPACE),
        "session": {"nodes": 12, "connections": 12, "revision": revision},
        "run_id": run_id,
        "run_state": status.state,
        "node_states": status.node_states,
        "log": status.log_path,
        "packages": {
            name: {
                "conda_meta": installed.get(name),
                "cli": versions.get(name),
            }
            for name in PACKAGES
        },
        "environment_file": str(ENV_YML),
        "inputs": {
            "reference": str(WORKSPACE / "inputs/synth_ref.fa"),
            "r1": str(data["r1"]),
            "r2": str(data["r2"]),
            "vcf": str(data["vcf"]),
            "pairs": 24,
        },
        "outputs": dict(compiled.outputs.items()),
        "registry": registry_checks,
        "checks": checks,
        "mcp": mcp,
        "ui": ui,
        "limitations": [
            "仅验证本机 Conda 包的可执行性与结果结构，未做真实样本分析或生物学结论。",
            "合成数据为随机 100 bp 高质量读段与 2000 bp 随机参考，不能代表真实测序误差/重复区域。",
            "VCF 为人工构造的单 SNP，bcftools 仅做统计，不含变异检出流程。",
        ],
    }
    RESULT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print("COMMON_TOOLS_OK", run_id, status.state)
    print("packages", json.dumps(payload["packages"], ensure_ascii=False))
    print("mcp", mcp["count"], mcp["local_tool_ids"])
    print("ui", ui["nodes"], ui["connections"], ui["local_in_library"], ui["screenshot"])
    print("result", RESULT_JSON)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
