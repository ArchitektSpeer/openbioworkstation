"""Exact port contracts for the pinned Snakemake wrapper demo chain."""

from glue.models import ExecSpec, ParamSpec, PortSpec, ToolSpec


def builtin_specs(version="v5.0.0"):
    def p(name, fmt, multiple=False):
        return PortSpec(name, (fmt,), multiple)

    definitions = [
        (
            "fastp",
            "Quality control",
            (p("sample", "FASTQ", True),),
            (p("trimmed", "FASTQ", True), p("html", "HTML"), p("json", "JSON")),
            (ParamSpec("extra", ""),),
        ),
        (
            "bwa/index",
            "Alignment",
            (p("fasta", "FASTA"),),
            (p("idx", "BWA_INDEX", True),),
            (ParamSpec("extra", ""),),
        ),
        (
            "bwa/mem",
            "Alignment",
            (p("reads", "FASTQ", True), p("idx", "BWA_INDEX", True)),
            (p("bam", "BAM"),),
            (ParamSpec("extra", ""), ParamSpec("sorting", "none")),
        ),
        (
            "samtools/sort",
            "Alignment",
            (p("bam", "BAM"),),
            (p("bam", "BAM"),),
            (ParamSpec("extra", ""),),
        ),
        (
            "samtools/index",
            "Alignment",
            (p("bam", "BAM"),),
            (p("bai", "BAI"),),
            (ParamSpec("extra", ""),),
        ),
    ]
    return {
        f"smk:bio/{name}": ToolSpec(
            f"smk:bio/{name}",
            name,
            category,
            "snakemake-wrappers",
            f"{name} Snakemake wrapper",
            tuple(name.split("/")),
            inputs,
            outputs,
            params,
            ExecSpec("wrapper", wrapper=f"{version}/bio/{name}"),
            threads=2,
        )
        for name, category, inputs, outputs, params in definitions
    }
