#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

hardware_mode="0"
if [[ "${MATCHPATCH_MACOS_HARDWARE:-}" == "1" ]]; then
    hardware_mode="1"
fi

output_dir="build/macos-hardware"
mkdir -p "$output_dir"
rm -f "$output_dir"/*

uv sync --locked --no-default-groups --extra hardware

uv run --frozen --no-default-groups --extra hardware python -c \
    "import mido; import mido.backends.rtmidi; import rtmidi; import sounddevice; print('macOS hardware imports OK')"

uv run --frozen --no-default-groups --extra hardware python -m matchpatch.measure devices \
    | tee "$output_dir/device-list.txt"

validate_device() {
    local device_name="$1"
    local diagnostics_json="$output_dir/${device_name}-diagnostics.json"
    local diagnostics_stderr="$output_dir/${device_name}-diagnostics.stderr.txt"
    local status=0

    set +e
    uv run --frozen --no-default-groups --extra hardware python -m matchpatch.measure \
        check-hardware \
        --device "$device_name" \
        --diagnostics-json \
        >"$diagnostics_json" \
        2>"$diagnostics_stderr"
    status=$?
    set -e

    python - "$diagnostics_json" "$device_name" "$hardware_mode" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

diagnostics_path = Path(sys.argv[1])
device_name = sys.argv[2]
hardware_mode = sys.argv[3] == "1"

payload = json.loads(diagnostics_path.read_text(encoding="utf-8"))
checks = {check["name"]: check for check in payload}

device_check = checks["device_profile"]
audio_check = checks["audio_device"]
midi_check = checks["midi_output"]

if device_check["status"] != "pass":
    raise SystemExit(f"{device_name}: device profile check failed unexpectedly")

audio_detail = json.loads(audio_check.get("detail") or "{}")
midi_detail = json.loads(midi_check.get("detail") or "{}")

if hardware_mode:
    if audio_check["status"] != "pass":
        raise SystemExit(f"{device_name}: expected audio_device to pass with hardware")
    if midi_check["status"] != "pass":
        raise SystemExit(f"{device_name}: expected midi_output to pass with hardware")
    if "input_mapping" not in audio_detail or "output_mapping" not in audio_detail:
        raise SystemExit(f"{device_name}: missing audio channel mapping details")
    if "output" not in midi_detail:
        raise SystemExit(f"{device_name}: missing MIDI output details")
else:
    if audio_check["status"] != "fail":
        raise SystemExit(f"{device_name}: expected audio_device to fail without hardware")
    if midi_check["status"] != "fail":
        raise SystemExit(f"{device_name}: expected midi_output to fail without hardware")

print(f"{device_name}: diagnostics validated")
PY

    if [[ "$hardware_mode" == "1" ]]; then
        if [[ "$status" -ne 0 ]]; then
            echo "Expected $device_name hardware diagnostics to succeed on a self-hosted runner." >&2
            cat "$diagnostics_stderr" >&2
            exit 1
        fi
    else
        if [[ "$status" -eq 0 ]]; then
            echo "Expected $device_name hardware diagnostics to fail when no device is attached." >&2
            exit 1
        fi
    fi
}

validate_device helix
validate_device podgo

echo
if [[ "$hardware_mode" == "1" ]]; then
    echo "macOS hardware validation completed with attached Helix and Pod Go devices."
else
    echo "macOS no-hardware validation completed."
fi
