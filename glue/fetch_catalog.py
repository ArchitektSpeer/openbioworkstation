"""Fetch optional upstream metadata for the tool catalog."""

import argparse
import json
import os
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from glue.config import load_config

WRAPPERS_URL = "https://codeload.github.com/snakemake/snakemake-wrappers/tar.gz/refs/tags/{version}"
WRAPPER_FILES = {"meta.yaml", "wrapper.py", "wrapper.R"}
NFCORE_URL = "https://github.com/nf-core/modules.git"
NFCORE_PATTERNS = (
    "modules/nf-core/**/meta.yml",
    "modules/nf-core/**/main.nf",
    "modules/nf-core/**/environment.yml",
)


def download(url, destination, timeout=120):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "OpenBioWorkstation"})
    with (
        urllib.request.urlopen(request, timeout=timeout) as response,
        tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as temporary,
    ):
        while chunk := response.read(1 << 20):
            temporary.write(chunk)
    os.replace(temporary.name, destination)
    return destination


def fetch_channeldata(config):
    destination = config.upstream_dir / "bioconda-recipes" / "channeldata.json"
    download(config.bioconda_channeldata_url, destination)
    try:
        packages = json.loads(destination.read_text())["packages"]
        if not isinstance(packages, dict):
            raise TypeError
    except (ValueError, KeyError, TypeError):
        destination.unlink(missing_ok=True)
        raise ValueError("channeldata.json 缺少 packages 字典") from None
    return len(packages)


def fetch_wrappers(config):
    version = config.wrappers_version
    archive = config.cache_dir / f"snakemake-wrappers-{version}.tar.gz"
    if not archive.exists():
        download(WRAPPERS_URL.format(version=version), archive)
    destination = config.upstream_dir / "snakemake-wrappers"
    extracted = 0
    with tarfile.open(archive) as tar:
        members = []
        for member in tar.getmembers():
            parts = Path(member.name).parts
            if len(parts) >= 4 and parts[1] == "bio" and parts[-1] in WRAPPER_FILES:
                member.name = "/".join(parts[1:])
                members.append(member)
                extracted += parts[-1] == "meta.yaml"
        tar.extractall(destination, members=members, filter="data")
    return extracted


def fetch_nfcore(config):
    destination = config.upstream_dir / "nf-core-modules"
    if not (destination / ".git").exists():
        subprocess.run(
            ["git", "clone", "--depth", "1", "--filter=blob:none", "--no-checkout",
             NFCORE_URL, str(destination)],
            check=True,
            timeout=900,
        )
    subprocess.run(
        ["git", "-C", str(destination), "sparse-checkout", "init", "--no-cone"],
        check=True,
        timeout=60,
    )
    subprocess.run(
        ["git", "-C", str(destination), "sparse-checkout", "set", *NFCORE_PATTERNS],
        check=True,
        timeout=60,
    )
    subprocess.run(["git", "-C", str(destination), "checkout"], check=True, timeout=600)
    return len(list((destination / "modules/nf-core").rglob("meta.yml")))


def main(argv=None):
    parser = argparse.ArgumentParser(description="下载可选的工具目录上游元数据")
    parser.add_argument("--channeldata", action="store_true", help="下载 Bioconda channeldata.json")
    parser.add_argument("--wrappers", action="store_true", help="下载 snakemake-wrappers 元数据")
    parser.add_argument("--nfcore", action="store_true", help="稀疏下载 nf-core/modules 元数据")
    parser.add_argument("--all", action="store_true", help="下载全部")
    args = parser.parse_args(argv)
    if not (args.channeldata or args.wrappers or args.nfcore or args.all):
        parser.error("至少指定 --channeldata、--wrappers、--nfcore 或 --all")
    config = load_config()
    if args.channeldata or args.all:
        print(f"Bioconda 包：{fetch_channeldata(config)}")
    if args.wrappers or args.all:
        print(f"snakemake-wrappers {config.wrappers_version}：{fetch_wrappers(config)} 个 wrapper")
    if args.nfcore or args.all:
        print(f"nf-core 模块：{fetch_nfcore(config)} 个 meta.yml")


if __name__ == "__main__":
    main()
