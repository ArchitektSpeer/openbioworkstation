"""Nodes for a small, explicitly installed shared Bioconda environment."""

import json
import os
import shlex
import sys
from pathlib import Path

from glue.errors import ToolNotFoundError
from glue.models import ExecSpec, ParamSpec, PortSpec, ToolSpec

PACKAGES = ("fastp", "bwa", "samtools", "bcftools", "seqkit")


def common_prefix():
    return (
        Path(
            os.environ.get(
                "BIOWS_COMMON_ENV",
                Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
                / "biows/common-tools",
            )
        )
        .expanduser()
        .resolve()
    )


class InstalledToolsAdapter:
    source = "local-installed"

    def __init__(self, prefix=None):
        self.prefix = Path(prefix).resolve() if prefix else common_prefix()

    @property
    def version(self):
        history = self.prefix / "conda-meta/history"
        return f"{self.prefix}:v1:{history.stat().st_mtime_ns if history.exists() else 0}"

    def packages(self):
        result = {}
        for name in PACKAGES:
            for path in (self.prefix / "conda-meta").glob(name + "-*.json"):
                item = json.loads(path.read_text())
                if item.get("name") == name:
                    result[name] = item["version"]
        return result

    def specs(self):
        versions = self.packages()
        command = shlex.join(
            [sys.executable, "-m", "glue.tool_runner", "--prefix", str(self.prefix)]
        )

        def p(name, fmt, multiple=False):
            return PortSpec(name, tuple(fmt.split("|")), multiple)

        definitions = [
            (
                "fastp",
                "fastp · FASTQ 处理",
                "Quality control",
                "fastp",
                (p("sample", "FASTQ", True),),
                (p("trimmed", "FASTQ", True), p("html", "HTML"), p("json", "JSON")),
                "fastp --reads {input.sample:q} --trimmed {output.trimmed:q} --html {output.html:q} --json {output.json:q} --threads {threads}",
            ),
            (
                "bwa/index",
                "BWA · 构建索引",
                "Alignment",
                "bwa",
                (p("fasta", "FASTA"),),
                (p("idx", "BWA_INDEX", True),),
                "bwa-index --fasta {input.fasta:q} --indexes {output.idx:q}",
            ),
            (
                "bwa/mem",
                "BWA MEM · 比对",
                "Alignment",
                "bwa",
                (p("reads", "FASTQ", True), p("idx", "BWA_INDEX", True)),
                (p("sam", "SAM"),),
                "bwa-mem --reads {input.reads:q} --indexes {input.idx:q} --output {output.sam:q} --threads {threads}",
            ),
            (
                "samtools/view",
                "SAMtools · SAM 转 BAM",
                "Alignment",
                "samtools",
                (p("sam", "SAM"),),
                (p("bam", "BAM"),),
                "samtools-view --input {input.sam:q} --output {output.bam:q} --threads {threads}",
            ),
            (
                "samtools/sort",
                "SAMtools · BAM 排序",
                "Alignment",
                "samtools",
                (p("bam", "BAM"),),
                (p("bam", "BAM"),),
                "samtools-sort --input {input.bam:q} --output {output.bam:q} --threads {threads}",
            ),
            (
                "samtools/index",
                "SAMtools · BAM 索引",
                "Alignment",
                "samtools",
                (p("bam", "BAM"),),
                (p("bai", "BAI"),),
                "samtools-index --input {input.bam:q} --output {output.bai:q} --threads {threads}",
            ),
            (
                "bcftools/stats",
                "BCFtools · 变异统计",
                "Variant Calling",
                "bcftools",
                (p("variants", "VCF|BCF"),),
                (p("stats", "TEXT"),),
                "bcftools-stats --input {input.variants:q} --output {output.stats:q}",
            ),
            (
                "seqkit/stats",
                "SeqKit · 序列统计",
                "Sequence utilities",
                "seqkit",
                (p("reads", "FASTQ|FASTA", True),),
                (p("stats", "TSV"),),
                "seqkit-stats --reads {input.reads:q} --output {output.stats:q} --threads {threads}",
            ),
            (
                "bam_dedup",
                "SAMtools · 过滤去重与索引",
                "Alignment",
                "samtools",
                (p("sam", "SAM"),),
                (p("bam", "BAM"), p("bai", "BAI")),
                "bam-dedup --input {input.sam:q} --output {output.bam:q} --bai {output.bai:q} --threads {threads} --mem 256M",
            ),
            (
                "viral_variant_stats",
                "病毒变异 · 位点统计",
                "Viral analysis",
                "pysam",
                (p("bam", "BAM"), p("bai", "BAI"), p("fasta", "FASTA"), p("vcf", "VCF")),
                (p("sites", "TSV"), p("summary", "JSON")),
                "viral-variant-stats --bam {input.bam:q} --bai {input.bai:q} --fasta {input.fasta:q} --vcf {input.vcf:q} --sample {params.sample:q} --treatment {params.treatment:q} --dpi {params.dpi} --rep {params.rep} --total-pairs {params.total_pairs} --min-bq {params.min_bq} --min-mq {params.min_mq} --min-depth {params.min_depth} --min-maf {params.min_maf} --min-support {params.min_support} --fixed-threshold {params.fixed_threshold} --out-sites {output.sites:q} --out-summary {output.summary:q}",
            ),
        ]
        specs = {}
        for key, title, category, package, inputs, outputs, args in definitions:
            if key == "viral_variant_stats":
                available, version_text = True, "pysam"
            else:
                available = package in versions and (self.prefix / "bin" / package).exists()
                version_text = versions.get(package, "")
            if not available:
                continue
            description = (
                "本机 Python 节点（pysam），统计病毒位点深度、碱基构成与低频变异"
                if key == "viral_variant_stats"
                else f"本机 {package} {version_text}；独立 Bioconda 环境：{self.prefix}"
            )
            tool_id = f"local:{key}"
            specs[tool_id] = ToolSpec(
                tool_id,
                title,
                category,
                self.source,
                description,
                (package, key, "installed", "本机"),
                inputs,
                outputs,
                (
                    (
                        ParamSpec("sample", ""),
                        ParamSpec("treatment", ""),
                        ParamSpec("dpi", 0),
                        ParamSpec("rep", 0),
                        ParamSpec("total_pairs", 500000),
                        ParamSpec("min_bq", 30),
                        ParamSpec("min_mq", 20),
                        ParamSpec("min_depth", 100),
                        ParamSpec("min_maf", 0.01),
                        ParamSpec("min_support", 5),
                        ParamSpec("fixed_threshold", 0.9),
                    )
                    if key == "viral_variant_stats"
                    else ()
                ),
                ExecSpec("shell", shell=command + " " + args + " > {log:q} 2>&1"),
                threads=4 if key == "bam_dedup" else 2,
            )
        return specs

    def iter_index(self):
        # Import here to keep registry adapter discovery free of circular imports.
        from glue.wrapper_registry import index_entry

        return iter(index_entry(spec) for spec in self.specs().values())

    def load_spec(self, tool_id):
        try:
            return self.specs()[tool_id]
        except KeyError as exc:
            raise ToolNotFoundError(f"本机工具未安装：{tool_id}") from exc
