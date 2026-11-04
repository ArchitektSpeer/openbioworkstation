"""Lightweight artifact identity checks; no expensive scans of sequencing files."""

from pathlib import Path


def fingerprint(path):
    file = Path(path)
    if file.is_symlink():
        stat = file.lstat()
        try:
            target = file.resolve()
        except RuntimeError as exc:
            raise OSError("循环符号链接不支持历史结果验证") from exc
        if not target.is_file():
            raise OSError("目录或失效符号链接不支持历史结果验证")
        target_stat = target.stat()
        return {
            "symlink": str(file.readlink()),
            "mtime_ns": stat.st_mtime_ns,
            "target": str(target),
            "size": target_stat.st_size,
            "target_mtime_ns": target_stat.st_mtime_ns,
            "inode": target_stat.st_ino,
        }
    if not file.exists():
        return None
    stat = file.stat()
    result = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "inode": stat.st_ino}
    if file.is_dir():
        result["entries"] = {str(p.relative_to(file)): fingerprint(p) for p in file.iterdir()}
    return result
