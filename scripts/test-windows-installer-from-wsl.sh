#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

windows_workdir="${MATCHPATCH_WINDOWS_WORKDIR:-/mnt/c/src/MatchPatch-windows}"

scripts/sync-windows-from-wsl.sh --group docs --group installer --extra gui

test_script="$windows_workdir/scripts/test-windows-installer.cmd"
if [[ ! -f "$test_script" ]]; then
    echo "Installer test script is not implemented yet: $test_script" >&2
    exit 1
fi

windows_workdir_windows_path="$(wslpath -w "$windows_workdir")"
windows_workdir_cmd_path="${windows_workdir_windows_path//\\/\\\\}"
unsafe_cmd_regex='[[:space:]"&()<>^|]'

if [[ "$windows_workdir_windows_path" =~ $unsafe_cmd_regex ]]; then
    echo "Windows mirror path cannot be forwarded safely to cmd.exe: $windows_workdir_windows_path" >&2
    echo "Set MATCHPATCH_WINDOWS_WORKDIR to a path without spaces or cmd metacharacters." >&2
    exit 1
fi

cmd_args=()
for arg in "$@"; do
    if [[ "$arg" =~ $unsafe_cmd_regex ]]; then
        echo "Argument cannot be forwarded safely to cmd.exe: $arg" >&2
        exit 1
    fi
    cmd_args+=("$arg")
done

cmd_line="cd /d $windows_workdir_cmd_path && call scripts\\\\test-windows-installer.cmd"
for arg in "${cmd_args[@]}"; do
    cmd_line+=" $arg"
done

cmd.exe /d /c "$cmd_line"

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
echo "MatchPatch Windows installer test artifact:"
echo "  WSL:     $installer_wsl_path"
echo "  Windows: $installer_windows_path"
