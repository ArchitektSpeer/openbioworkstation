"""Bounded previews through C-backed readers; full scans are explicitly requested."""

import gzip
import json
from itertools import islice
from pathlib import Path
from time import perf_counter

from glue.formats import BWA_EXTENSIONS, detect_format
from glue.models import InspectResult


def inspect_bio_file(path: str, preview_n: int = 5, full_stats: bool = False) -> InspectResult:
    start = perf_counter()
    result = InspectResult(
        path=str(Path(path).expanduser().resolve()), format=detect_format(path), valid=False
    )
    try:
        if not 0 <= preview_n <= 100:
            raise ValueError("preview_n 必须在 0 到 100 之间")
        file = Path(result.path)
        if not file.is_file():
            raise ValueError("文件不存在或不是普通文件")
        if not file.stat().st_size:
            raise ValueError("文件为空")
        fmt = result.format
        result.compressed = "gzip/BGZF" if file.suffix.lower() in (".gz", ".bgz", ".bgzf") else ""
        suffixes = {
            "FASTA": (".fai", ".fxi", *BWA_EXTENSIONS),
            "FASTQ": (".fxi",),
            "BAM": (".bai", ".csi"),
            "CRAM": (".crai",),
            "VCF": (".tbi", ".csi"),
            "BCF": (".csi",),
        }.get(fmt, ())
        result.index = {
            ext: Path(str(file) + ext).exists() or file.with_suffix(ext).exists()
            for ext in suffixes
        }
        if fmt in ("FASTA", "FASTQ"):
            import pyfastx

            count = bases = 0
            records = pyfastx.Fastx(str(file))
            iterator = iter(records) if full_stats else islice(records, max(preview_n, 1))
            for record in iterator:
                name, sequence = record[:2]
                if not sequence or (
                    fmt == "FASTQ" and (len(record) < 3 or len(record[2]) != len(sequence))
                ):
                    raise ValueError("序列或质量字符串无效")
                count += 1
                bases += len(sequence)
                if len(result.preview) < preview_n:
                    result.preview.append(f"{name}: {sequence[:100]} (length={len(sequence)})")
            if count == 0:
                raise ValueError("未找到有效序列")
            result.stats = {
                "records" if full_stats else "sampled_records": count,
                "total_bases" if full_stats else "sampled_bases": bases,
            }
        elif fmt in ("SAM", "BAM", "CRAM"):
            import pysam

            mode = {"SAM": "r", "BAM": "rb", "CRAM": "rc"}[fmt]
            with pysam.AlignmentFile(str(file), mode) as reader:
                result.stats = {"references": list(reader.references)}
                count = 0
                for record in (
                    reader.fetch(until_eof=True)
                    if full_stats
                    else islice(reader.fetch(until_eof=True), preview_n)
                ):
                    count += 1
                    if len(result.preview) < preview_n:
                        result.preview.append(record.to_string()[:1000])
                if full_stats:
                    result.stats["records"] = count
                elif fmt == "BAM" and reader.has_index():
                    stats = reader.get_index_statistics()
                    result.stats.update(
                        mapped=sum(s.mapped for s in stats), unmapped=sum(s.unmapped for s in stats)
                    )
                if fmt == "CRAM" and not full_stats:
                    result.warnings.append("CRAM 索引不提供可靠的记录计数，请使用完整统计")
        elif fmt in ("VCF", "BCF"):
            from cyvcf2 import VCF

            reader = VCF(str(file))
            try:
                result.stats = {"samples": reader.samples, "contigs": reader.seqnames}
                count = 0
                for record in reader if full_stats else islice(reader, preview_n):
                    count += 1
                    if len(result.preview) < preview_n:
                        result.preview.append(str(record).strip()[:1000])
                if full_stats:
                    result.stats["records"] = count
            finally:
                reader.close()
        elif fmt in ("HTML", "JSON", "TEXT", "TSV", "BED", "GFF", "GTF"):
            opener = gzip.open if result.compressed else open
            with opener(file, "rt", encoding="utf-8") as reader:
                result.preview = [reader.readline(2000).rstrip() for _ in range(preview_n)]
                result.preview = [line for line in result.preview if line]
            if fmt == "JSON" and full_stats:
                with opener(file, "rt", encoding="utf-8") as reader:
                    json.load(reader)
        else:
            raise ValueError(f"不支持的文件格式：{file.suffix}")
        result.valid = True
        if not full_stats:
            result.warnings.append(
                "快速预览只检查已读取的记录，不代表全文件完整性校验；完整检查请启用 full_stats"
            )
    except Exception as exc:
        result.error = str(exc)
    result.elapsed_ms = (perf_counter() - start) * 1000
    return result
