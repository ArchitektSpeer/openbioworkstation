"""XDG configuration and canonical path authorization."""

import os
from pathlib import Path

import yaml

from glue.errors import PathNotAllowedError, WorkstationError
from glue.models import Config


def load_config(path: Path | None = None, *, workspace: Path | None = None) -> Config:
    home = Path.home()
    data = Path(os.environ.get("XDG_DATA_HOME", home / ".local/share")) / "biows"
    cache = Path(os.environ.get("XDG_CACHE_HOME", home / ".cache")) / "biows"
    path = path or Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / "biows/config.yaml"
    raw = yaml.safe_load(path.read_text()) if path.exists() else {}
    raw = raw or {}
    if not isinstance(raw, dict):
        raise WorkstationError("配置必须是 YAML 字典")

    def absolute(value):
        return Path(value).expanduser().resolve()

    config = Config(
        workspace=absolute(workspace or raw.get("workspace", home / "biows/projects/default")),
        data_dir=absolute(raw.get("data_dir", data)),
        cache_dir=absolute(raw.get("cache_dir", cache)),
        upstream_dir=absolute(raw.get("upstream_dir", data / "upstream")),
        conda_prefix=absolute(raw.get("conda_prefix", cache / "conda-envs")),
        conda_bin=str(raw.get("conda_bin", "conda")),
        wrappers_version=str(raw.get("wrappers_version", "v5.0.0")),
        cores=int(raw.get("cores", 4)),
        deploy=raw.get("deploy", "conda"),
        allowed_input_roots=tuple(absolute(p) for p in raw.get("allowed_input_roots", [])),
        allow_unreviewed=bool(raw.get("allow_unreviewed", False)),
        bioconda_channeldata_url=raw.get(
            "bioconda_channeldata_url",
            Config.__dataclass_fields__["bioconda_channeldata_url"].default,
        ),
    )
    if config.cores < 1 or config.deploy not in ("conda", "apptainer"):
        raise WorkstationError("cores 必须为正整数，deploy 必须为 conda 或 apptainer")
    return config


def allowed_path(path: str | Path, workspace: Path, roots=()) -> Path:
    candidate = Path(path).expanduser()
    candidate = (workspace / candidate if not candidate.is_absolute() else candidate).resolve()
    if not any(candidate.is_relative_to(Path(root).resolve()) for root in (workspace, *roots)):
        raise PathNotAllowedError(f"路径不在允许的目录内：{candidate}")
    return candidate
