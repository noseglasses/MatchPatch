"""Shared Line 6 JSON preset helpers."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any


def normalize_regex_pattern(pattern: str) -> str:
    return pattern.replace("\b", r"\b")


def get_snapshot_output_gain(
    snapshot: MutableMapping[str, Any],
    dsp_name: str,
    output_name: str,
    base_gain: float,
) -> float:
    controllers = snapshot.get("controllers")

    if not isinstance(controllers, dict):
        return base_gain

    dsp_snapshot = controllers.get(dsp_name)

    if not isinstance(dsp_snapshot, dict):
        return base_gain

    output_snapshot = dsp_snapshot.get(output_name)

    if not isinstance(output_snapshot, dict):
        return base_gain

    gain = output_snapshot.get("gain")

    if isinstance(gain, dict):
        gain = gain.get("@value")

    if gain is None:
        return base_gain

    return float(gain)


def ensure_snapshot_output_gain_values(
    tone: MutableMapping[str, Any],
    dsp_name: str,
    output_name: str,
    base_gain: float,
    *,
    snapshot_count: int = 8,
) -> int:
    changes = 0

    for snapshot_index in range(snapshot_count):
        snapshot = tone.get(f"snapshot{snapshot_index}")

        if not isinstance(snapshot, dict):
            continue

        snapshot_controllers = snapshot.setdefault("controllers", {})
        dsp_snapshot = snapshot_controllers.setdefault(dsp_name, {})
        output_snapshot = dsp_snapshot.setdefault(output_name, {})

        if "gain" in output_snapshot:
            continue

        output_snapshot["gain"] = {"@fs_enabled": False, "@value": base_gain}
        changes += 1

    return changes
