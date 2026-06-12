#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

export UV_PROJECT_ENVIRONMENT="${XDG_DATA_HOME:-$HOME/.local/share}/matchpatch/.venv-wsl"

uv sync --locked --no-default-groups --group wsl --group docs --extra gui "$@"
