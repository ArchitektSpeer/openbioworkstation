"""Thin argv adapters for installed CLIs. No bioinformatics algorithms or DAG scheduling."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

BASE_INDEX = {"A": 0, "C": 1, "G": 2, "T": 3}


def _quantile(sorted_values: list[int], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, max(0, round(fraction * (len(sorted_values) - 1))))
    return float(sorted_values[index])


def _viral_variant_stats(args: argparse.Namespace) -> None:
    """按位点统计病毒 BAM 的碱基构成、深度与低频变异；输出位点表与汇总 JSON。"""
    import pysam

    bam = pysam.AlignmentFile(args.bam, "rb", index_filename=args.bai)
    fasta = pysam.FastaFile(args.fasta)
    vcf_counts = {"records": 0, "variants": 0}
    if args.vcf and Path(args.vcf).exists():
        with pysam.VariantFile(args.vcf) as vcf:
            for record in vcf:
                vcf_counts["records"] += 1
                if record.alts:
                    vcf_counts["variants"] += 1

    columns = [
        "sample",
        "virus",
        "pos",
        "ref",
        "depth",
        "A",
        "C",
        "G",
        "T",
        "major_alt",
        "major_alt_count",
        "maf",
        "is_variant",
        "fixed_candidate",
        "ref_fwd",
        "ref_rev",
        "alt_fwd",
        "alt_rev",
    ]
    rows = [columns]
    summary: dict[str, object] = {
        "sample": args.sample,
        "treatment": args.treatment,
        "dpi": args.dpi,
        "rep": args.rep,
        "total_pairs": args.total_pairs,
        "parameters": {
            "min_bq": args.min_bq,
            "min_mq": args.min_mq,
            "min_depth": args.min_depth,
            "min_maf": args.min_maf,
            "min_support": args.min_support,
            "fixed_threshold": args.fixed_threshold,
            "pileup_stepper": "all",
            "flag_filter": "0xF04 (unmapped, secondary, qcfail, duplicate, supplementary)",
            "ignore_overlaps": True,
            "mapping_quality": "explicit per-read filter",
            "baq": "not applied",
        },
        "vcf": vcf_counts,
        "viruses": {},
    }
    for ref_name in fasta.references:
        sequence = fasta.fetch(ref_name).upper()
        counts = [[0, 0, 0, 0, 0] for _ in range(len(sequence))]
        strands: dict[int, list[list[int]]] = {}
        for column in bam.pileup(
            ref_name,
            stepper="all",
            flag_filter=0xF04,
            ignore_overlaps=True,
            min_base_quality=args.min_bq,
            truncate=True,
            max_depth=1_000_000,
        ):
            position = column.reference_pos
            if position >= len(sequence):
                continue
            row = counts[position]
            per_base = [[0, 0] for _ in BASE_INDEX]
            for pileup_read in column.pileups:
                if pileup_read.is_del or pileup_read.is_refskip:
                    continue
                alignment = pileup_read.alignment
                # stepper="all" 不应用 min_mapping_quality；这里显式执行与 QC 相同的过滤。
                if alignment.mapping_quality < args.min_mq or alignment.is_supplementary:
                    continue
                query_position = pileup_read.query_position
                if query_position is None:
                    continue
                qualities = alignment.query_qualities
                if qualities is not None and qualities[query_position] < args.min_bq:
                    continue
                base = alignment.query_sequence[query_position].upper()
                index = BASE_INDEX.get(base)
                if index is None:
                    if base == "N":
                        row[4] += 1
                    continue
                row[index] += 1
                per_base[index][1 if alignment.is_reverse else 0] += 1
            strands[position] = per_base

        depths = [sum(row[:4]) for row in counts]
        finite = sorted(depth for depth in depths if depth >= args.min_depth)
        total_bases = total_nonref = 0
        pi_sum = 0.0
        pi_sites = 0
        variant_counts = {1: 0, 2: 0, 5: 0}
        fixed_count = 0
        for position, row in enumerate(counts):
            depth = sum(row[:4])
            ref_base = BASE_INDEX.get(sequence[position])
            alt_base, alt_count, maf = "N", 0, 0.0
            if depth > 0 and ref_base is not None:
                alt_index = max(
                    (index for index in range(4) if index != ref_base),
                    key=lambda index: row[index],
                )
                alt_base, alt_count = "ACGT"[alt_index], row[alt_index]
                maf = alt_count / depth
            fixed = bool(
                ref_base is not None
                and depth >= args.min_depth
                and alt_base != "N"
                and maf > args.fixed_threshold
            )
            is_variant = bool(
                ref_base is not None
                and depth >= args.min_depth
                and not fixed
                and alt_base != "N"
                and maf >= args.min_maf
                and alt_count >= args.min_support
            )
            if fixed:
                fixed_count += 1
            if is_variant:
                for threshold in variant_counts:
                    if maf >= threshold / 100:
                        variant_counts[threshold] += 1
            if depth >= args.min_depth and ref_base is not None:
                total_bases += depth
                total_nonref += depth - row[ref_base]
                pi_sum += 1.0 - sum((value / depth) ** 2 for value in row[:4])
                pi_sites += 1
            per_base = strands.get(position, [[0, 0] for _ in BASE_INDEX])
            ref_fwd, ref_rev = per_base[ref_base] if ref_base is not None else (0, 0)
            alt_fwd, alt_rev = per_base[BASE_INDEX[alt_base]] if alt_base in BASE_INDEX else (0, 0)
            rows.append(
                [
                    args.sample,
                    ref_name.split("|")[0],
                    position + 1,
                    sequence[position],
                    depth,
                    *row[:4],
                    alt_base,
                    alt_count,
                    f"{maf:.6f}",
                    int(is_variant),
                    int(fixed),
                    ref_fwd,
                    ref_rev,
                    alt_fwd,
                    alt_rev,
                ]
            )
        depth_mean = sum(depths) / len(depths) if depths else 0.0
        summary["viruses"][ref_name.split("|")[0]] = {
            "reference": ref_name,
            "length": len(sequence),
            "depth_mean": round(depth_mean, 3),
            "depth_median": _quantile(finite, 0.5),
            "depth_p10": _quantile(finite, 0.1),
            "depth_p90": _quantile(finite, 0.9),
            "breadth_1x": round(sum(depth >= 1 for depth in depths) / len(depths), 6),
            "breadth_10x": round(sum(depth >= 10 for depth in depths) / len(depths), 6),
            "breadth_100x": round(sum(depth >= 100 for depth in depths) / len(depths), 6),
            "breadth_400x": round(sum(depth >= 400 for depth in depths) / len(depths), 6),
            "breadth_1000x": round(sum(depth >= 1000 for depth in depths) / len(depths), 6),
            "sites_ge_min_depth": len(finite),
            "error_floor": round(total_nonref / total_bases, 8) if total_bases else 0.0,
            "pi_raw": round(pi_sum / pi_sites, 8) if pi_sites else 0.0,
            "n_variant_1pct": variant_counts[1],
            "n_variant_2pct": variant_counts[2],
            "n_variant_5pct": variant_counts[5],
            "n_fixed_candidates": fixed_count,
        }

    with Path(args.out_sites).open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write("\t".join(str(value) for value in row) + "\n")
    Path(args.out_summary).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", required=True, type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in (
        "fastp",
        "bwa-index",
        "bwa-mem",
        "samtools-view",
        "samtools-sort",
        "samtools-index",
        "bcftools-stats",
        "seqkit-stats",
        "bam-dedup",
        "viral-variant-stats",
    ):
        sub = commands.add_parser(name)
        sub.add_argument("--threads", type=int, default=2)
        if name in ("fastp", "bwa-mem", "seqkit-stats"):
            sub.add_argument("--reads", nargs="+", required=True)
        if name in ("bwa-index", "bwa-mem"):
            sub.add_argument("--indexes", nargs=5, required=True)
        if name == "bwa-index":
            sub.add_argument("--fasta", required=True)
        elif name == "fastp":
            sub.add_argument("--trimmed", nargs="+", required=True)
            sub.add_argument("--html", required=True)
            sub.add_argument("--json", required=True)
        elif name == "bam-dedup":
            sub.add_argument("--input", required=True)
            sub.add_argument("--output", required=True)
            sub.add_argument("--bai", required=True)
            sub.add_argument("--mem", default="256M")
        elif name == "viral-variant-stats":
            sub.add_argument("--bam", required=True)
            sub.add_argument("--bai", required=True)
            sub.add_argument("--fasta", required=True)
            sub.add_argument("--vcf", default="")
            sub.add_argument("--sample", required=True)
            sub.add_argument("--treatment", required=True)
            sub.add_argument("--dpi", type=int, required=True)
            sub.add_argument("--rep", type=int, required=True)
            sub.add_argument("--total-pairs", type=int, default=0, dest="total_pairs")
            sub.add_argument("--min-bq", type=int, default=30, dest="min_bq")
            sub.add_argument("--min-mq", type=int, default=20, dest="min_mq")
            sub.add_argument("--min-depth", type=int, default=100, dest="min_depth")
            sub.add_argument("--min-maf", type=float, default=0.01, dest="min_maf")
            sub.add_argument("--min-support", type=int, default=5, dest="min_support")
            sub.add_argument("--fixed-threshold", type=float, default=0.9, dest="fixed_threshold")
            sub.add_argument("--out-sites", required=True, dest="out_sites")
            sub.add_argument("--out-summary", required=True, dest="out_summary")
        else:
            sub.add_argument("--output", required=True)
            if name.startswith("samtools-") or name == "bcftools-stats":
                sub.add_argument("--input", required=True)
    args = parser.parse_args()
    prefix = args.prefix.resolve()
    env = dict(
        os.environ,
        PATH=str(prefix / "bin") + os.pathsep + os.environ.get("PATH", ""),
        CONDA_PREFIX=str(prefix),
    )

    def run(tool, flags, stdout=None):
        subprocess.run(
            [str(prefix / "bin" / tool), *map(str, flags)], env=env, stdout=stdout, check=True
        )

    def index_prefix():
        extensions = (".amb", ".ann", ".bwt", ".pac", ".sa")
        first = str(args.indexes[0])
        base = first[:-4] if first.endswith(".amb") else ""
        if not base or list(args.indexes) != [base + ext for ext in extensions]:
            parser.error("BWA 索引必须为同前缀的 amb/ann/bwt/pac/sa 五件套")
        return base

    if args.threads < 1:
        parser.error("threads 必须为正整数")
    if args.command == "bam-dedup":
        if args.threads < 1:
            parser.error("threads 必须为正整数")
        output = Path(args.output).resolve()
        bai = Path(args.bai).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        bai.parent.mkdir(parents=True, exist_ok=True)
        work = output.parent / (output.stem + ".dedup_tmp")
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True)
        unsorted, namesort = work / "unsorted.bam", work / "namesort.bam"
        fixmate, coordsort = work / "fixmate.bam", work / "coordsort.bam"
        try:
            run(
                "samtools",
                ["view", "-@", args.threads, "-b", "-F", "4", "-o", unsorted, args.input],
            )
            run(
                "samtools",
                ["sort", "-@", args.threads, "-m", args.mem, "-n", "-o", namesort, unsorted],
            )
            run("samtools", ["fixmate", "-@", args.threads, "-m", namesort, fixmate])
            run(
                "samtools",
                ["sort", "-@", args.threads, "-m", args.mem, "-o", coordsort, fixmate],
            )
            run(
                "samtools",
                ["markdup", "-@", args.threads, "-s", coordsort, output],
            )
            run("samtools", ["index", "-@", args.threads, output, bai])
        finally:
            shutil.rmtree(work, ignore_errors=True)
    elif args.command == "viral-variant-stats":
        _viral_variant_stats(args)
    elif args.command == "fastp":
        if len(args.reads) not in (1, 2) or len(args.trimmed) != len(args.reads):
            parser.error("fastp 需要一份或两份 reads，输出数量必须一致")
        flags = [
            "--thread",
            args.threads,
            "--in1",
            args.reads[0],
            "--out1",
            args.trimmed[0],
            "--html",
            args.html,
            "--json",
            args.json,
        ]
        if len(args.reads) == 2:
            flags += ["--in2", args.reads[1], "--out2", args.trimmed[1]]
        run("fastp", flags)
    elif args.command == "bwa-index":
        run("bwa", ["index", "-p", index_prefix(), args.fasta])
    elif args.command == "bwa-mem":
        if len(args.reads) not in (1, 2):
            parser.error("BWA MEM 需要一份或两份 FASTQ")
        with open(args.output, "wb") as output:
            run("bwa", ["mem", "-t", args.threads, index_prefix(), *args.reads], output)
    elif args.command == "samtools-view":
        run("samtools", ["view", "-@", args.threads, "-b", "-o", args.output, args.input])
    elif args.command == "samtools-sort":
        run("samtools", ["sort", "-@", args.threads, "-o", args.output, args.input])
    elif args.command == "samtools-index":
        run("samtools", ["index", "-@", args.threads, args.input, args.output])
    elif args.command == "bcftools-stats":
        with open(args.output, "wb") as output:
            run("bcftools", ["stats", args.input], output)
    elif args.command == "seqkit-stats":
        with open(args.output, "wb") as output:
            run("seqkit", ["stats", "-T", "-j", args.threads, *args.reads], output)


if __name__ == "__main__":
    main()
