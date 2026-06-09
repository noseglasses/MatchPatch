#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

windows_workdir="${MATCHPATCH_WINDOWS_WORKDIR:-/mnt/c/src/MatchPatch-windows}"

scripts/sync-windows-from-wsl.sh --group docs --group installer --extra gui

installer_script="$windows_workdir/scripts/build-windows-installer.cmd"
if [[ ! -f "$installer_script" ]]; then
    echo "Installer build script is not implemented yet: $installer_script" >&2
    echo "Implement scripts/build-windows-installer.cmd in the Inno Setup step." >&2
    exit 1
fi

installer_script_windows_path="$(wslpath -w "$installer_script")"
windows_workdir_windows_path="$(wslpath -w "$windows_workdir")"

cmd.exe /d /c "cd /d \"$windows_workdir_windows_path\" && call \"$installer_script_windows_path\""

version="$(
    "$HOME/.local/share/matchpatch/.venv-wsl/bin/python" - <<'PY'
import tomllib
from pathlib import Path

with Path("pyproject.toml").open("rb") as pyproject_file:
    print(tomllib.load(pyproject_file)["project"]["version"])
PY
)"

installer_wsl_path="$windows_workdir/dist/installer/MatchPatch-Setup-$version.exe"
installer_windows_path="$(wslpath -w "$installer_wsl_path")"

if [[ ! -f "$installer_wsl_path" ]]; then
    echo "Expected installer was not produced: $installer_wsl_path" >&2
    exit 1
fi

echo
echo "MatchPatch Windows installer:"
echo "  WSL:     $installer_wsl_path"
echo "  Windows: $installer_windows_path"
