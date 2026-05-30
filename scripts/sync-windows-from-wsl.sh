#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

sync_script_windows_path="$(
    wslpath -w "$PWD/scripts/sync-windows.cmd"
)"

powershell.exe \
    -NoProfile \
    -NonInteractive \
    -Command \
    "& '$sync_script_windows_path'"
