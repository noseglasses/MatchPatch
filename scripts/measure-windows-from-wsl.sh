#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

windows_workdir="${MATCHPATCH_WINDOWS_WORKDIR:-/mnt/c/src/MatchPatch-windows}"
windows_python_path="$windows_workdir/.venv-windows/Scripts/python.exe"

if [[ ! -x "$windows_python_path" ]]; then
    echo "Native Windows MatchPatch environment not found: $windows_python_path" >&2
    echo "Run scripts/sync-windows-from-wsl.sh first." >&2
    exit 1
fi

exec "$windows_python_path" -m matchpatch.measure "$@"
