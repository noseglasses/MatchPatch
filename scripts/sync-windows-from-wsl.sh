#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

windows_workdir="${MATCHPATCH_WINDOWS_WORKDIR:-/mnt/c/src/MatchPatch-windows}"
mkdir -p "$windows_workdir"

rsync \
    -a \
    --delete \
    --exclude /.git/ \
    --exclude /.venv-windows/ \
    --exclude /.venv/ \
    --exclude /.pytest_cache/ \
    --exclude /htmlcov/ \
    --exclude '**/__pycache__/' \
    ./ \
    "$windows_workdir/"

sync_script_windows_path="$(
    wslpath -w "$windows_workdir/scripts/sync-windows.cmd"
)"

cmd.exe /d /c call "$sync_script_windows_path" "$@"

echo
echo "Windows runtime mirror: $windows_workdir"
echo "Use this from WSL for normalize hardware runs:"
echo "  export MATCHPATCH_WINDOWS_PYTHON=\"$windows_workdir/.venv-windows/Scripts/python.exe\""
