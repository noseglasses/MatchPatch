#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "MatchPatch macOS app builds must run on macOS." >&2
  exit 1
fi

payload_dir="build/macos-payload/MatchPatch.app"

rm -rf docs_html
rm -rf build/macos-payload
rm -rf build/pyinstaller

uv run --frozen --no-default-groups --group docs sphinx-build -W --keep-going -b html docs docs_html
uv run --frozen --no-default-groups --group installer --extra gui --extra hardware pyinstaller installer/pyinstaller/matchpatch-macos.spec

# PyInstaller signs the initial bundle, then the spec stages docs, audio, and
# build metadata into Contents/MacOS. Re-sign after staging so Gatekeeper does
# not report a broken bundle seal. This is still not Developer ID notarization.
codesign --force --deep --sign - "$payload_dir"
codesign --verify --deep --strict --verbose=4 "$payload_dir"

# TODO(future signed releases): once signing credentials exist, replace the
# ad-hoc signature with Developer ID app signing, hardened runtime, and any
# required entitlements here.

if [[ ! -f "$payload_dir/Contents/Info.plist" ]]; then
  echo "Missing app bundle metadata: $payload_dir/Contents/Info.plist" >&2
  exit 1
fi
if [[ ! -x "$payload_dir/Contents/MacOS/MatchPatch" ]]; then
  echo "Missing app executable: $payload_dir/Contents/MacOS/MatchPatch" >&2
  exit 1
fi
if [[ ! -f "$payload_dir/Contents/MacOS/docs_html/index.html" ]]; then
  echo "Missing payload docs: $payload_dir/Contents/MacOS/docs_html/index.html" >&2
  exit 1
fi
if [[ ! -f "$payload_dir/Contents/MacOS/build-info.json" ]]; then
  echo "Missing payload manifest: $payload_dir/Contents/MacOS/build-info.json" >&2
  exit 1
fi
if [[ ! -f "$payload_dir/Contents/MacOS/audio/reference-di/DI_Strandberg_Boden_Fusion_Bridge_Humbucker.wav" ]]; then
  echo "Missing reference DI audio: $payload_dir/Contents/MacOS/audio/reference-di/DI_Strandberg_Boden_Fusion_Bridge_Humbucker.wav" >&2
  exit 1
fi

echo
echo "MatchPatch macOS app bundle:"
echo "  $(pwd)/$payload_dir"
