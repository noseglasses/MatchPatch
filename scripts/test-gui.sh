#!/usr/bin/env bash
set -euo pipefail

pytest_bin="${XDG_DATA_HOME:-$HOME/.local/share}/matchpatch/.venv-wsl/bin/pytest"

if [[ ! -x "$pytest_bin" ]]; then
  echo "MatchPatch GUI test runner not found: $pytest_bin" >&2
  echo "Run scripts/sync-wsl.sh to create/update the WSL environment." >&2
  exit 127
fi

if [[ $# -eq 0 ]]; then
  set -- tests/test_gui.py
fi

exec "$pytest_bin" "$@"
