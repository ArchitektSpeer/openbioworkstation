"""Compatibility bridge for static CWL File ports on Snakemake 8+."""

import base64
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    cwl, outdir, encoded = sys.argv[1:]
    Path(outdir).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="biows-cwl-") as temporary:
        job = Path(temporary) / "job.json"
        job.write_bytes(base64.b64decode(encoded))
        return subprocess.call(["cwltool", "--outdir", outdir, cwl, str(job)])


if __name__ == "__main__":
    sys.exit(main())
