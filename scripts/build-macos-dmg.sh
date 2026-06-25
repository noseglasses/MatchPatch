#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "MatchPatch macOS DMG builds must run on macOS." >&2
  exit 1
fi

project_version="$(python3 - <<'PY'
import tomllib
from pathlib import Path

with Path("pyproject.toml").open("rb") as handle:
    pyproject = tomllib.load(handle)
print(pyproject["project"]["version"])
PY
)"
arch="$(uname -m)"

app_bundle="build/macos-payload/MatchPatch.app"
dmg_stage_root="build/macos-dmg/MatchPatch"
dmg_path="dist/installer/MatchPatch-macOS-${arch}-${project_version}.dmg"

rm -rf build/macos-dmg
rm -rf dist/installer

bash scripts/build-macos-app.sh

if [[ ! -d "$app_bundle" ]]; then
  echo "Missing app bundle: $app_bundle" >&2
  exit 1
fi

rm -rf "$dmg_stage_root"
mkdir -p "$dmg_stage_root"
ditto "$app_bundle" "$dmg_stage_root/MatchPatch.app"

mkdir -p "$(dirname "$dmg_path")"

if [[ -f "$dmg_path" ]]; then
  rm -f "$dmg_path"
fi

# TODO(future signed releases): Signing and notarization are intentionally deferred
# until the project can support Apple Developer credentials. Import the Developer
# ID certificate from GitHub Actions secrets, sign the app with hardened runtime,
# optionally sign the DMG, submit with xcrun notarytool, staple with xcrun
# stapler, and verify with spctl --assess. Keep the current DMG without a
# Developer ID signature until then; manual Gatekeeper approval may be required
# on first launch.
hdiutil create \
  -fs HFS+ \
  -format UDZO \
  -volname MatchPatch \
  -srcfolder "$dmg_stage_root" \
  -ov \
  "$dmg_path"

if [[ ! -f "$dmg_path" ]]; then
  echo "Missing DMG artifact: $dmg_path" >&2
  exit 1
fi

echo
echo "MatchPatch macOS DMG:"
echo "  $(pwd)/$dmg_path"
