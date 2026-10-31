"""Small metadata cache with upstream fingerprints, independent of execution environments."""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from glue.models import IndexEntry
from glue.session_store import atomic_json


def fingerprint(adapter):
    digest = hashlib.sha256()
    digest.update(str(getattr(adapter, "version", "")).encode())
    roots = [getattr(adapter, "root", None), getattr(adapter, "wrapped_dir", None)]
    for root in filter(None, roots):
        root = Path(root)
        digest.update(str(root.resolve()).encode())
        # Only YAML metadata and Git references are considered, not binaries/environments.
        if root.exists():
            paths = (
                list(root.rglob("meta.yaml"))
                + list(root.rglob("meta.yml"))
                + list(root.rglob("*.cwl"))
            )
            paths += [root / ".git/HEAD", root / ".git/packed-refs"]
            for path in sorted(paths):
                if path.is_file():
                    stat = path.stat()
                    digest.update(f"{path}:{stat.st_mtime_ns}:{stat.st_size}".encode())
    return digest.hexdigest()


def cached_entries(adapter, cache_dir, refresh=False):
    path = Path(cache_dir) / ("catalog-" + adapter.source + ".json")
    stamp = fingerprint(adapter)
    if not refresh and path.exists():
        try:
            data = json.loads(path.read_text())
            if data["fingerprint"] == stamp:
                result = []
                for item in data["entries"]:
                    for key in ("keywords", "input_formats", "output_formats"):
                        item[key] = tuple(item.get(key, ()))
                    result.append(IndexEntry(**item))
                return result
        except (ValueError, TypeError, KeyError):
            pass
    entries = list(adapter.iter_index())
    atomic_json(path, {"fingerprint": stamp, "entries": [asdict(item) for item in entries]})
    return entries
