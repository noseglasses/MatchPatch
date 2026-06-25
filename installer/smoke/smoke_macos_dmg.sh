#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "MatchPatch macOS DMG smoke tests must run on macOS." >&2
  exit 1
fi

usage() {
  echo "Usage: installer/smoke/smoke_macos_dmg.sh [--reuse-artifact] [--dmg <path>]" >&2
}

reuse_artifact=0
dmg_path=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --reuse-artifact)
      reuse_artifact=1
      shift
      ;;
    --dmg)
      if [[ $# -lt 2 ]]; then
        usage
        exit 64
      fi
      dmg_path="$2"
      reuse_artifact=1
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 64
      ;;
  esac
done

project_version="$(python3 - <<'PY'
import tomllib
from pathlib import Path

with Path("pyproject.toml").open("rb") as handle:
    pyproject = tomllib.load(handle)
print(pyproject["project"]["version"])
PY
)"
arch="$(uname -m)"
expected_dmg="dist/installer/MatchPatch-macOS-${arch}-${project_version}.dmg"

if [[ "$reuse_artifact" -eq 0 ]]; then
  bash scripts/build-macos-dmg.sh
  dmg_path="$expected_dmg"
else
  if [[ -z "$dmg_path" ]]; then
    dmg_path="$expected_dmg"
  fi
  if [[ ! -f "$dmg_path" ]]; then
    echo "Missing DMG artifact: $dmg_path" >&2
    echo "Run without --reuse-artifact to rebuild the DMG." >&2
    exit 1
  fi
fi

if [[ ! -f "$dmg_path" ]]; then
  echo "Missing DMG artifact: $dmg_path" >&2
  exit 1
fi

mount_point="$(mktemp -d "${TMPDIR:-/tmp}/matchpatch-macos-dmg.XXXXXX")"
mounted=0

cleanup() {
  if [[ "$mounted" -eq 1 ]]; then
    if ! hdiutil detach -force -quiet "$mount_point"; then
      echo "Warning: failed to detach DMG mount: $mount_point" >&2
    fi
  fi
  rmdir "$mount_point" >/dev/null 2>&1 || true
}
trap cleanup EXIT

hdiutil attach -nobrowse -readonly -mountpoint "$mount_point" "$dmg_path" >/dev/null
mounted=1

app_bundle="$mount_point/MatchPatch.app"
if [[ ! -d "$app_bundle" ]]; then
  echo "Missing app bundle inside DMG: $app_bundle" >&2
  exit 1
fi

bash installer/smoke/smoke_macos_payload.sh "$app_bundle" "$project_version"

echo "DMG smoke passed: $dmg_path"
