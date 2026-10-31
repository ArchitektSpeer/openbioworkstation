#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"
export QT_API=pyside6
exec "$project_dir/.venv/bin/python" -m examples.demo "$@"
