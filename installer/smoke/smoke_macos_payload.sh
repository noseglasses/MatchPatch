#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: installer/smoke/smoke_macos_payload.sh <app-bundle> <expected-version>" >&2
  exit 64
fi

app_bundle="$1"
expected_version="$2"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "MatchPatch macOS payload smoke tests must run on macOS." >&2
  exit 1
fi

if [[ ! -d "$app_bundle" ]]; then
  echo "Missing app bundle: $app_bundle" >&2
  exit 1
fi

info_plist="$app_bundle/Contents/Info.plist"
app_exe="$app_bundle/Contents/MacOS/MatchPatch"
docs_index="$app_bundle/Contents/MacOS/docs_html/index.html"
build_info="$app_bundle/Contents/MacOS/build-info.json"
reference_di="$app_bundle/Contents/MacOS/audio/reference-di/DI_Strandberg_Boden_Fusion_Bridge_Humbucker.wav"

for path in "$info_plist" "$app_exe" "$docs_index" "$build_info" "$reference_di"; do
  if [[ ! -e "$path" ]]; then
    echo "Missing expected payload path: $path" >&2
    exit 1
  fi
done

python3 - "$info_plist" "$expected_version" <<'PY'
import plistlib
import sys
from pathlib import Path

info_plist = Path(sys.argv[1])
expected_version = sys.argv[2]
with info_plist.open("rb") as handle:
    info = plistlib.load(handle)

expected = {
    "CFBundleDisplayName": "MatchPatch",
    "CFBundleExecutable": "MatchPatch",
    "CFBundleIdentifier": "io.github.noseglasses.matchpatch",
    "CFBundleName": "MatchPatch",
    "CFBundleShortVersionString": expected_version,
    "CFBundleVersion": expected_version,
}
for key, value in expected.items():
    actual = info.get(key)
    if actual != value:
        raise SystemExit(f"Info.plist {key}={actual!r} did not match expected {value!r}")
PY

python3 - "$build_info" "$expected_version" <<'PY'
import json
import sys
from pathlib import Path

build_info = Path(sys.argv[1])
expected_version = sys.argv[2]
payload = json.loads(build_info.read_text(encoding="utf-8"))
if payload.get("version") != expected_version:
    raise SystemExit(
        f"build-info.json version {payload.get('version')!r} did not match expected "
        f"{expected_version!r}"
    )
if payload.get("builder") != "pyinstaller":
    raise SystemExit(
        f"build-info.json builder {payload.get('builder')!r} did not match 'pyinstaller'"
    )
PY

if ! codesign --verify --deep --strict --verbose=4 "$app_bundle"; then
  echo "Bundled app code signature seal is invalid." >&2
  exit 1
fi

cli_output="$("$app_exe" --cli --version)"
if [[ "$cli_output" != *"$expected_version"* ]]; then
  echo "Bundled CLI version output did not mention $expected_version: $cli_output" >&2
  exit 1
fi

gui_log="$(mktemp "${TMPDIR:-/tmp}/matchpatch-gui-smoke.XXXXXX")"
gui_timeout_marker="$(mktemp "${TMPDIR:-/tmp}/matchpatch-gui-smoke-timeout.XXXXXX")"
rm -f "$gui_timeout_marker"
gui_status=0

MATCHPATCH_GUI_SMOKE=1 "$app_exe" >"$gui_log" 2>&1 &
gui_pid=$!
(
  sleep 60
  if kill -0 "$gui_pid" 2>/dev/null; then
    touch "$gui_timeout_marker"
    kill "$gui_pid" 2>/dev/null || true
  fi
) &
watchdog_pid=$!

wait "$gui_pid" || gui_status=$?
kill "$watchdog_pid" 2>/dev/null || true
wait "$watchdog_pid" 2>/dev/null || true

if [[ -f "$gui_timeout_marker" ]]; then
  echo "Bundled GUI smoke timed out after 60 seconds." >&2
  echo "GUI smoke log:" >&2
  cat "$gui_log" >&2
  rm -f "$gui_log" "$gui_timeout_marker"
  exit 1
fi

if [[ "$gui_status" -ne 0 ]]; then
  echo "Bundled GUI smoke failed with exit code $gui_status." >&2
  echo "GUI smoke log:" >&2
  cat "$gui_log" >&2
  rm -f "$gui_log" "$gui_timeout_marker"
  exit 1
fi
rm -f "$gui_log" "$gui_timeout_marker"

echo "Payload smoke passed: $app_bundle"
