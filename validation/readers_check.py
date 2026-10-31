"""Small-sample pyfastx / pysam / cyvcf2 read checks through inspect_bio_file."""

import gzip
import json
import shutil
from pathlib import Path

import pysam
from cyvcf2 import VCF, Writer

from glue.bio_inspector import inspect_bio_file

WS = Path(__file__).resolve().parent / "tmp-readers"


def build_samples():
    if WS.exists():
        shutil.rmtree(WS)
    WS.mkdir(parents=True)
    fastq = WS / "reads.fastq"
    fastq.write_text("@r1\nACGT\n+\nIIII\n@r2\nTGCA\n+\nJJJJ\n")
    fasta = WS / "ref.fa"
    fasta.write_text(">chr1\n" + "ACGT" * 250 + "\n")
    pysam.faidx(str(fasta))

    header = {"HD": {"VN": "1.0"}, "SQ": [{"LN": 1000, "SN": "chr1"}]}
    bam = WS / "aln.bam"
    with pysam.AlignmentFile(str(bam), "wb", header=header) as out:
        for name, start in (("r1", 10), ("r2", 20)):
            read = pysam.AlignedSegment()
            read.query_name = name
            read.query_sequence = "ACGT"
            read.flag = 0
            read.reference_id = 0
            read.reference_start = start
            read.mapping_quality = 60
            read.cigarstring = "4M"
            read.query_qualities = pysam.qualitystring_to_array("IIII")
            out.write(read)
    pysam.index(str(bam))

    sam = WS / "aln.sam"
    with (
        pysam.AlignmentFile(str(sam), "w", header=header) as out,
        pysam.AlignmentFile(str(bam), "rb") as src,
    ):
        for read in src:
            out.write(read)

    cram = WS / "aln.cram"
    with (
        pysam.AlignmentFile(str(cram), "wc", header=header, reference_filename=str(fasta)) as out,
        pysam.AlignmentFile(str(bam), "rb") as src,
    ):
        for read in src:
            out.write(read)
    pysam.index(str(cram))

    plain_vcf = WS / "variants.vcf"
    plain_vcf.write_text(
        "##fileformat=VCFv4.2\n"
        "##contig=<ID=chr1,length=1000>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr1\t15\t.\tA\tT\t50\tPASS\t.\n"
    )
    vcf_gz = WS / "variants.vcf.gz"
    pysam.tabix_compress(str(plain_vcf), str(vcf_gz), force=True)
    pysam.tabix_index(str(vcf_gz), preset="vcf", force=True)
    bcf = WS / "variants.bcf"
    reader = VCF(str(plain_vcf))
    writer = Writer(str(bcf), reader)
    for record in reader:
        writer.write_record(record)
    writer.close()
    reader.close()
    try:
        pysam.index(str(bcf))
    except pysam.utils.SamtoolsError as exc:
        print("bcf indexing unsupported here:", exc)

    (WS / "notes.txt").write_text("hello\n")
    (WS / "table.tsv").write_text("a\tb\n1\t2\n")
    (WS / "page.html").write_text("<html><body>hi</body></html>\n")
    (WS / "data.json").write_text(json.dumps({"a": 1}) + "\n")
    (WS / "regions.bed").write_text("chr1\t0\t10\n")
    (WS / "genes.gtf").write_text('chr1\tsrc\tgene\t1\t10\t.\t+\t.\tgene_id "g1";\n')
    (WS / "genes.gff").write_text("##gff-version 3\nchr1\tsrc\tgene\t1\t10\t.\t+\t.\tID=g1\n")

    truncated = WS / "truncated.fastq.gz"
    with gzip.open(truncated, "wb") as out:
        out.write(b"@r1\nACGT\n+\n")
    return {
        "fastq": fastq,
        "fasta": fasta,
        "sam": sam,
        "bam": bam,
        "cram": cram,
        "vcf.gz": vcf_gz,
        "bcf": bcf,
        "bed": WS / "regions.bed",
        "gtf": WS / "genes.gtf",
        "gff": WS / "genes.gff",
        "html": WS / "page.html",
        "json": WS / "data.json",
        "tsv": WS / "table.tsv",
        "text": WS / "notes.txt",
        "truncated": truncated,
    }


def main():
    samples = build_samples()
    expected = {
        "fastq": "FASTQ",
        "fasta": "FASTA",
        "sam": "SAM",
        "bam": "BAM",
        "cram": "CRAM",
        "vcf.gz": "VCF",
        "bcf": "BCF",
        "bed": "BED",
        "gtf": "GTF",
        "gff": "GFF",
        "html": "HTML",
        "json": "JSON",
        "tsv": "TSV",
        "text": "TEXT",
    }
    for name, fmt in expected.items():
        result = inspect_bio_file(str(samples[name]), full_stats=name in ("fastq", "bam", "vcf.gz"))
        print(
            f"{name:9} format={result.format:6} valid={result.valid} "
            f"error={result.error!r} stats={result.stats} index={result.index}"
        )
        assert result.format == fmt, (name, result.format)
        assert result.valid, (name, result.error)
    fastq = inspect_bio_file(str(samples["fastq"]), full_stats=True)
    assert fastq.stats["records"] == 2
    bam = inspect_bio_file(str(samples["bam"]))
    assert bam.index.get(".bai") is True
    assert bam.stats.get("mapped") == 2, bam.stats
    cram = inspect_bio_file(str(samples["cram"]))
    assert cram.valid
    assert "mapped" not in cram.stats and "unmapped" not in cram.stats, cram.stats
    vcf = inspect_bio_file(str(samples["vcf.gz"]), full_stats=True)
    assert vcf.stats["records"] == 1
    assert vcf.index.get(".tbi") is True
    assert inspect_bio_file(str(WS / "missing.bam")).valid is False
    broken = inspect_bio_file(str(samples["truncated"]))
    print("truncated valid=", broken.valid, "error=", broken.error)
    assert broken.valid is False
    print("READERS_OK")


if __name__ == "__main__":
    main()
