"""Functional smoke tests for auto-wrapped tools using synthetic inputs.

Runs each tool's shell template with generated FASTA/FASTQ/BED/VCF/GTF/BAM files,
checks the exit code and declared outputs, and writes validation/wrap-smoke-result.json.
Synthetic data only; not a biological validation.
"""

from __future__ import annotations

import argparse
import json
import random
import shlex
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from string import Formatter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from glue.config import load_config  # noqa: E402
from glue.formats import EXTENSIONS  # noqa: E402
from glue.wrapper_registry import ToolRegistry  # noqa: E402

RESULT = ROOT / "validation" / "wrap-smoke-result.json"

FASTA = ">chr1\n" + "ACGT" * 500 + "\n"
REF4000 = ">chr1\n" + "ACGT" * 1000 + "\n"
FASTA4 = (
    ">s1\nACGTACGTACGT\n>s2\nACGTACGTACGA\n>s3\nACGTTCGTACGT\n>s4\nACGTACGTTCGT\n"
)
FASTQ = "@r1\nACGTACGTACGT\n+\nIIIIIIIIIIII\n@r2\nTTTTAAAACCCC\n+\nIIIIIIIIIIII\n"
PROTEINS = ">prot1\nMKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ\n>prot2\nAAAAAAAAGGGGGGGGCCCCCCCC\n"
HMM_ALIGNMENT = (
    ">a\nMKTAYIAKQRQISFVKSHFSRQ\n>b\nMKTAYIAKQRQISFVKSHFSRQ\n"
    ">c\nMKTAYIAKQRQISFVKSHFSRE\n"
)
BED = "chr1\t10\t20\nchr1\t15\t30\nchr2\t5\t10\n"
BED_B = "chr1\t12\t18\n"
VCF = (
    "##fileformat=VCFv4.2\n"
    "##contig=<ID=chr1,length=4000>\n"
    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
    "chr1\t10\t.\tA\tT\t60\tPASS\t.\n"
    "chr1\t20\t.\tC\tG\t60\tPASS\t.\n"
)
GTF = (
    'chr1\tsrc\tgene\t1\t100\t.\t+\t.\tgene_id "g1";\n'
    'chr1\tsrc\texon\t1\t100\t.\t+\t.\tgene_id "g1";\n'
)


def contig(length=25000, seed=7):
    rng = random.Random(seed)
    return ">contig1\n" + "".join(rng.choice("ACGT") for _ in range(length)) + "\n"


CONTIG = contig()

RECIPES = {
    "auto:seqkit/seqkit": {"files": {"reads": ("reads.fa", FASTA)}},
    "auto:seqtk/seqtk": {"files": {"reads": ("reads.fq", FASTQ)}},
    "auto:seqtk/seqtk-sample": {"files": {"reads": ("reads.fq", FASTQ)}},
    "auto:bedtools/bedtools-sort": {"files": {"bed": ("in.bed", BED)}},
    "auto:bedtools/bedtools-merge": {"files": {"bed": ("in.bed", BED)}},
    "auto:bedtools/bedtools-intersect": {
        "files": {"a": ("a.bed", BED), "b": ("b.bed", BED_B)}
    },
    "auto:bedtools/bedtools-genomecov": {"bam": True},
    "auto:samtools/samtools-faidx": {"files": {"fasta": ("ref.fa", FASTA)}},
    "auto:samtools/samtools-flagstat": {"bam": True},
    "auto:samtools/samtools-depth": {"bam": True},
    "auto:bcftools/bcftools-view": {"files": {"vcf": ("in.vcf", VCF)}},
    "auto:bcftools/bcftools-query": {"files": {"vcf": ("in.vcf", VCF)}},
    "auto:minimap2/minimap2": {
        "files": {"reference": ("ref.fa", FASTA), "reads": ("reads.fq", FASTQ)}
    },
    "auto:mafft/mafft": {"files": {"fasta": ("aln.fa", FASTA4)}},
    "auto:fasttree/FastTree": {"files": {"alignment": ("aln.fa", FASTA4)}},
    "auto:cutadapt/cutadapt": {"files": {"reads": ("reads.fq", FASTQ)}},
    "auto:freebayes/freebayes": {"bam": True, "files": {"reference": ("ref.fa", REF4000)}},
    "auto:blast/blastn": {
        "files": {"query": ("q.fa", FASTA), "subject": ("s.fa", FASTA)}
    },
    "auto:prodigal/prodigal": {"files": {"contigs": ("contigs.fa", CONTIG)}},
    "auto:htslib/bgzip": {"files": {"file": ("in.txt", BED)}},
    "auto:htslib/tabix": {"bgzip": True},
    "auto:kallisto/kallisto-index": {"files": {"fasta": ("tx.fa", FASTA)}},
    "auto:subread/featureCounts": {"bam": True, "files": {"annotation": ("genes.gtf", GTF)}},
    "auto:picard/picard-markduplicates": {"bam": True},
    "auto:clustalo/clustalo": {"files": {"fasta": ("aln.fa", FASTA4)}},
    "auto:sourmash/sourmash-sketch": {"files": {"reads": ("reads.fa", FASTA)}},
    "auto:kmer-jellyfish/jellyfish-count": {"files": {"reads": ("reads.fq", FASTQ)}},
    "auto:trimmomatic/trimmomatic": {"files": {"reads": ("reads.fq", FASTQ)}},
    "auto:lastz/lastz": {
        "files": {"reference": ("ref.fa", FASTA), "query": ("q.fa", FASTA)}
    },
    "auto:ngmlr/ngmlr": {
        "files": {"reference": ("ref.fa", REF4000), "reads": ("reads.fq", FASTQ)}
    },
    "auto:abricate/abricate": {"files": {"contigs": ("contigs.fa", CONTIG)}},
    "auto:mlst/mlst": {"files": {"contigs": ("contigs.fa", CONTIG)}},
    "auto:mummer/mummer": {
        "files": {"reference": ("ref.fa", FASTA), "query": ("q.fa", FASTA)}
    },
    "auto:emboss/water": {
        "files": {"sequence_a": ("a.fa", ">a\nACGTACGTACGT\n"), "sequence_b": ("b.fa", ">b\nACGTTCGTACGT\n")}
    },
    "auto:trnascan-se/tRNAscan-SE": {"files": {"genome": ("genome.fa", CONTIG)}},
    "auto:hmmer/hmmsearch": {"hmm": True, "files": {"sequences": ("prot.fa", PROTEINS)}},
    "auto:barrnap/barrnap": {"files": {"genome": ("genome.fa", CONTIG)}},
}


def write_bam(path):
    import pysam

    header = {
        "HD": {"VN": "1.6", "SO": "coordinate"},
        "SQ": [{"SN": "chr1", "LN": 4000}],
    }
    read = pysam.AlignedSegment()
    read.query_name = "r1"
    read.query_sequence = "ACGTACGTACGT"
    read.flag = 0
    read.reference_id = 0
    read.reference_start = 0
    read.mapping_quality = 60
    read.cigarstring = "12M"
    read.query_qualities = pysam.qualitystring_to_array("IIIIIIIIIIII")
    with pysam.AlignmentFile(path, "wb", header=header) as handle:
        handle.write(read)
    pysam.index(str(path))


def render(template, values):
    parts = []
    for literal, field, spec, _conversion in Formatter().parse(template):
        parts.append(literal)
        if field is not None:
            value = values[field]
            parts.append(shlex.quote(value) if spec == "q" else value)
    return "".join(parts)


def run_tool(config, registry, tool_id, conda, timeout):
    package, command = tool_id.removeprefix("auto:").split("/", 1)
    env = config.conda_prefix / f"biows-{package}"
    spec = registry.get(tool_id)
    recipe = RECIPES[tool_id]
    with tempfile.TemporaryDirectory(prefix=f"wrap-smoke-{package}-") as temporary:
        work = Path(temporary)
        values = {}
        for name, (filename, content) in recipe.get("files", {}).items():
            path = work / filename
            path.write_text(content)
            values[f"input.{name}"] = str(path)
        if recipe.get("bam"):
            path = work / "input.bam"
            write_bam(path)
            for port in spec.inputs:
                if "BAM" in port.formats and f"input.{port.name}" not in values:
                    values[f"input.{port.name}"] = str(path)
                    break
        if recipe.get("hmm"):
            alignment = work / "aln.fa"
            alignment.write_text(HMM_ALIGNMENT)
            model = work / "model.hmm"
            subprocess.run(
                [
                    conda,
                    "run",
                    "-p",
                    str(env),
                    "bash",
                    "-lc",
                    f"hmmbuild {shlex.quote(str(model))} {shlex.quote(str(alignment))} >/dev/null",
                ],
                check=True,
                capture_output=True,
                timeout=timeout,
            )
            values["input.hmm"] = str(model)
        if recipe.get("bgzip"):
            source = work / "in.vcf"
            source.write_text(VCF)
            gz = work / "in.vcf.gz"
            subprocess.run(
                [
                    conda,
                    "run",
                    "-p",
                    str(env),
                    "bash",
                    "-lc",
                    f"bgzip -c {shlex.quote(str(source))} > {shlex.quote(str(gz))}",
                ],
                check=True,
                capture_output=True,
                timeout=timeout,
            )
            values["input.vcf_gz"] = str(gz)
        for port in spec.outputs:
            extension = EXTENSIONS.get(port.formats[0], ".dat") if port.formats else ".dat"
            values[f"output.{port.name}"] = str(work / f"{port.name}{extension}")
        for param in spec.params:
            values[f"params.{param.name}"] = str(param.default)
        values["threads"] = "1"
        values["log"] = str(work / "task.log")
        commandline = render(spec.execution.shell, values)
        process = subprocess.run(
            [conda, "run", "-p", str(env), "bash", "-lc", commandline],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=work,
        )
        outputs = {}
        for port in spec.outputs:
            path = Path(values[f"output.{port.name}"])
            outputs[port.name] = {"exists": path.is_file(), "bytes": path.stat().st_size if path.is_file() else 0}
        return {
            "exit": process.returncode,
            "command": commandline,
            "outputs": outputs,
            "ok": process.returncode == 0 and all(item["exists"] for item in outputs.values()),
            "stderr": (process.stdout + process.stderr).strip()[-600:],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="auto 封装工具的功能冒烟")
    parser.add_argument("--only", default="")
    parser.add_argument("--review-passed", action="store_true")
    parser.add_argument("--conda", default="")
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()
    config = load_config()
    if args.conda:
        config = replace(config, conda_bin=args.conda)
    registry = ToolRegistry.from_config(config)
    registry.build_index()
    adapter = next(a for a in registry.adapters if hasattr(a, "_conda"))
    conda = adapter._conda()
    only = {item.strip() for item in args.only.split(",") if item.strip()}
    results = []
    for tool_id in sorted(RECIPES):
        if only and tool_id not in only:
            continue
        try:
            record = run_tool(config, registry, tool_id, conda, args.timeout)
        except Exception as exc:
            record = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        record["tool_id"] = tool_id
        results.append(record)
        if args.review_passed and record.get("ok"):
            registry.mark_reviewed(tool_id)
            record["reviewed"] = True
        print(tool_id, "OK" if record.get("ok") else "FAIL", flush=True)
        RESULT.write_text(json.dumps({"tools": results}, ensure_ascii=False, indent=2))
    passed = sum(1 for item in results if item.get("ok"))
    print(f"smoke {passed}/{len(results)} passed; report {RESULT}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
