#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

windows_python_path="$PWD/.venv-windows/Scripts/python.exe"

exec "$windows_python_path" -m matchpatch.measure "$@"
