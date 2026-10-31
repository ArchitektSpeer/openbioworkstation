"""Reproducible scale check for the optional upstream tool catalogs.

Builds the registry from the real configuration, reports per-source entry counts and
writes validation/catalog-result.json. Requires glue.fetch_catalog to have been run.
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from glue.config import load_config  # noqa: E402
from glue.wrapper_registry import ToolRegistry  # noqa: E402

RESULT = ROOT / "validation" / "catalog-result.json"
QUERIES = ("fastp", "bwa", "samtools", "variant calling", "wheat", "rna-seq")


def main() -> int:
    started = datetime.now(UTC).isoformat()
    config = load_config()
    registry = ToolRegistry.from_config(config)
    begin = time.monotonic()
    registry.build_index(refresh=True)
    elapsed = time.monotonic() - begin
    entries = list(registry._entries.values())
    by_source = Counter(entry.source for entry in entries)
    payload = {
        "generated_at": started,
        "upstream_dir": str(config.upstream_dir),
        "build_seconds": round(elapsed, 2),
        "total": len(entries),
        "by_source": dict(sorted(by_source.items())),
        "reviewed": sum(entry.reviewed for entry in entries),
        "wrapped": sum(entry.wrapped for entry in entries),
        "searches": {
            query: registry.search(query, limit=5).total for query in QUERIES
        },
        "limitations": [
            "计数表示可检索的上游条目，不等于可执行工具：未审核的 nf-core/CWL 与未封装的 Bioconda 包只能检索。",
            "上游元数据未做人工逐个复核，端口由启发式推断。",
        ],
    }
    RESULT.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print("CATALOG_OK", json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
