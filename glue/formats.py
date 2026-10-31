"""Shared file format inference and explicit port compatibility."""

import re
from pathlib import Path

EXTENSIONS = {
    "FASTQ": ".fastq.gz",
    "FASTA": ".fa",
    "SAM": ".sam",
    "BAM": ".bam",
    "CRAM": ".cram",
    "BAI": ".bai",
    "VCF": ".vcf.gz",
    "BCF": ".bcf",
    "BED": ".bed",
    "GTF": ".gtf",
    "GFF": ".gff",
    "HTML": ".html",
    "JSON": ".json",
    "TSV": ".tsv",
    "TEXT": ".txt",
    "ANY": ".dat",
}
ALIASES = {
    ".fq": "FASTQ",
    ".fastq": "FASTQ",
    ".fa": "FASTA",
    ".fasta": "FASTA",
    ".fna": "FASTA",
    ".fas": "FASTA",
    ".gff3": "GFF",
    ".csv": "TSV",
    ".txt": "TEXT",
    ".log": "TEXT",
    ".csi": "BAI",
}
ALIASES.update({ext.removesuffix(".gz"): fmt for fmt, ext in EXTENSIONS.items()})
BWA_EXTENSIONS = (".amb", ".ann", ".bwt", ".pac", ".sa")
GROUPS = {"ALIGNMENT": {"SAM", "BAM", "CRAM"}, "VARIANT": {"VCF", "BCF"}}


def detect_format(path: str) -> str:
    name = str(path).lower()
    for suffix in (".gz", ".bgz", ".bgzf"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    ext = Path(name).suffix
    return "BWA_INDEX" if ext in BWA_EXTENSIONS else ALIASES.get(ext, "ANY")


def formats_compatible(out, incoming) -> tuple[bool, str]:
    outgoing = {f.upper() for f in out}
    required = {f.upper() for f in incoming}
    accepted = set(required)
    for group, members in GROUPS.items():
        if group in required:
            accepted.update(members)
    ok = bool("ANY" in outgoing | required or outgoing & accepted)
    return (
        ok,
        ""
        if ok
        else f"输出为 {', '.join(sorted(outgoing))}，输入需要 {', '.join(sorted(required))}",
    )


def expand_brace_glob(pattern: str) -> list[str]:
    match = re.search(r"\{([^{}]+)\}", pattern)
    if not match:
        return [pattern]
    return [
        expanded
        for part in match[1].split(",")
        for expanded in expand_brace_glob(pattern[: match.start()] + part + pattern[match.end() :])
    ]


def infer_formats(text: str) -> tuple[str, ...]:
    formats = {detect_format(p) for p in expand_brace_glob(text)} - {"ANY"}
    formats.update(
        fmt for fmt in EXTENSIONS if fmt != "ANY" and re.search(rf"\b{fmt}\b", text, re.I)
    )
    return tuple(sorted(formats)) or ("ANY",)
