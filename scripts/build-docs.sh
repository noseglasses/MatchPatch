#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

sphinx_bin="${XDG_DATA_HOME:-$HOME/.local/share}/matchpatch/.venv-wsl/bin/sphinx-build"

if [[ ! -x "$sphinx_bin" ]]; then
  echo "MatchPatch docs builder not found: $sphinx_bin" >&2
  echo "Run scripts/sync-wsl.sh to create/update the WSL environment." >&2
  exit 127
fi

rm -rf docs_html
exec "$sphinx_bin" -W --keep-going -b html docs docs_html "$@"
