#!/usr/bin/env python3
"""Line 6 Pod Go PGS/PGP/JSON utility."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, cast

from matchpatch.devices.line6 import file_ops
from matchpatch.devices.line6.helix import preset_handling as helix_common
from matchpatch.devices.line6.preset_handling import (
    ensure_snapshot_output_gain_values,
    get_snapshot_output_gain,
)

PODGO_PRESET_EXTENSION = ".pgp"
PODGO_SETLIST_EXTENSION = ".pgs"
PODGO_SNAPSHOT_COUNT = 4
PODGO_PRESET_COUNT = 128
CONTROLLER_ASSIGNMENT_LIMIT = 64
PODGO_SNAPSHOT_CONTROLLER = 11

PODGO_INPUT_GUITAR = 3
PODGO_OUTPUT_MAIN = 1

PODGO_INPUT_USB_3_4 = 4
PODGO_OUTPUT_USB_1_2 = 1


def get_filetype(filename: str | os.PathLike[str]) -> str:
    ext = os.path.splitext(os.fspath(filename))[1].lower()
    if ext == PODGO_SETLIST_EXTENSION:
        return "pgs"
    if ext == PODGO_PRESET_EXTENSION:
        return "pgp"
    if ext == ".json":
        return "json"
    raise ValueError(f"Unsupported Pod Go file extension: {ext}")


def preset_index_to_podgo(index: int) -> str:
    return file_ops.banked_slot_label(index)


def podgo_to_preset_index(label: str) -> int:
    return file_ops.banked_slot_index(label, device_name="Pod Go")


def load_input(filename: str | os.PathLike[str]) -> tuple[str, str | dict[str, Any] | None]:
    filetype = get_filetype(filename)
    with open(filename, "r", encoding="utf-8") as f:
        text = f.read()

    if filetype == "pgs":
        return file_ops.decode_compressed_setlist_text(text), text

    if filetype == "pgp":
        original_data = json.loads(text)
        data = file_ops.wrap_preset_data(
            original_data,
            preset_extension=PODGO_PRESET_EXTENSION,
        )
        return json.dumps(data, indent=1), original_data

    return text, None


def rebuild_pgp_data(
    original_pgp_data: dict[str, Any] | None,
    preset: dict[str, Any],
) -> dict[str, Any]:
    if isinstance(original_pgp_data, dict) and isinstance(original_pgp_data.get("data"), dict):
        rebuilt = dict(original_pgp_data)
        rebuilt["data"] = preset
        return rebuilt
    return _wrap_pgp_preset(preset)


def save_output(
    modified_json_text: str,
    output_filename: str | os.PathLike[str],
    original_data: str | dict[str, Any] | None = None,
) -> None:
    filetype = get_filetype(output_filename)
    if filetype == "json":
        with open(output_filename, "w", encoding="utf-8") as f:
            f.write(modified_json_text)
        return

    if filetype == "pgp":
        data = json.loads(modified_json_text)
        preset = file_ops.unwrap_preset_data(data, preset_extension=PODGO_PRESET_EXTENSION)
        with open(output_filename, "w", encoding="utf-8") as f:
            json.dump(
                rebuild_pgp_data(
                    original_data if isinstance(original_data, dict) else None, preset
                ),
                f,
                indent=1,
            )
        return

    if isinstance(original_data, str):
        output_text = file_ops.build_compressed_setlist_text(original_data, modified_json_text)
    else:
        output_text = build_new_pgs_text(modified_json_text)
    with open(output_filename, "w", encoding="utf-8") as f:
        f.write(output_text)


def build_new_pgs_text(json_text: str) -> str:
    wrapper = json.loads(file_ops.build_new_compressed_setlist_text(json_text))
    wrapper["schema"] = "L6Setlist"
    wrapper.setdefault("version", 6)
    wrapper.setdefault("meta", {"name": "User"})
    wrapper.setdefault("encoding", "utf-8")
    return json.dumps(wrapper)


def get_preset_name(preset: dict[str, Any]) -> str:
    meta = preset.get("meta", {})
    return meta.get("name") or preset.get("name") or preset.get("@name") or ""


def preset_has_blocks(preset: dict[str, Any]) -> bool:
    dsp0 = preset.get("tone", {}).get("dsp0", {})
    return isinstance(dsp0, dict) and any(str(key).startswith("block") for key in dsp0)


def is_default_preset(preset: dict[str, Any]) -> bool:
    return not preset_has_blocks(preset)


def get_gain_outputs(preset: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    output = preset.get("tone", {}).get("dsp0", {}).get("output")
    if not isinstance(output, dict) or "gain" not in output:
        return []
    return [("dsp0", "output", output)]


def extract_preset_assignments(data: dict[str, Any]) -> list[dict[str, Any]]:
    assignments = []
    for preset_index, preset in enumerate(data.get("presets", [])[:PODGO_PRESET_COUNT]):
        if is_default_preset(preset):
            continue
        assignments.append(
            {
                "id": preset_index + 1,
                "device_patch": preset_index_to_podgo(preset_index),
                "podgo_preset": preset_index_to_podgo(preset_index),
                "name": str(get_preset_name(preset)).strip(),
                "snapshot_names": [
                    snapshot.get("@name", f"Snapshot {snapshot_index + 1}")
                    for snapshot_index in range(PODGO_SNAPSHOT_COUNT)
                    if isinstance(
                        snapshot := preset.get("tone", {}).get(f"snapshot{snapshot_index}"),
                        dict,
                    )
                ],
                "snapshot_output_paths": extract_snapshot_output_paths(preset),
                "snapshot_output_levels": extract_snapshot_output_levels(preset),
            }
        )
    return assignments


def extract_snapshot_output_paths(preset: dict[str, Any]) -> list[str]:
    return [f"{dsp_name}.{output_name}" for dsp_name, output_name, _ in get_gain_outputs(preset)]


def extract_snapshot_output_levels(preset: dict[str, Any]) -> list[list[float]]:
    outputs = []
    for dsp_name, output_name, output_block in get_gain_outputs(preset):
        outputs.append((dsp_name, output_name, float(output_block["gain"])))

    levels = []
    tone = preset.get("tone", {})
    for snapshot_index in range(PODGO_SNAPSHOT_COUNT):
        snapshot = tone.get(f"snapshot{snapshot_index}")
        if not isinstance(snapshot, dict):
            continue
        levels.append(
            [
                get_snapshot_output_gain(snapshot, dsp_name, output_name, base_gain)
                for dsp_name, output_name, base_gain in outputs
            ]
        )
    return levels


def extract_metadata(
    filename: str | os.PathLike[str],
    json_text: str,
    original_data: object = None,
) -> dict[str, Any]:
    filetype = get_filetype(filename)
    data = json.loads(json_text)
    result: dict[str, Any] = {
        "file_type": filetype,
        "metadata": list(helix_common.iter_metadata_nodes(data)),
    }
    if filetype == "pgs" and isinstance(original_data, str):
        wrapper = json.loads(original_data)
        result["wrapper"] = {key: value for key, value in wrapper.items() if key != "encoded_data"}
    elif filetype == "pgp" and isinstance(original_data, dict):
        wrapper = {key: value for key, value in original_data.items() if key != "data"}
        if wrapper:
            result["wrapper"] = wrapper
    return result


def extract_diff_preset_ids(
    current_filename: str | os.PathLike[str], previous_filename: str | os.PathLike[str]
) -> list[int]:
    if get_filetype(current_filename) != get_filetype(previous_filename):
        raise ValueError("Diff input file type must match input file type")
    current_data = json.loads(load_input(current_filename)[0])
    previous_data = json.loads(load_input(previous_filename)[0])
    diff_ids = []
    for preset_index, current_preset in enumerate(current_data.get("presets", [])):
        if is_default_preset(current_preset):
            continue
        previous_presets = previous_data.get("presets", [])
        previous_preset = (
            previous_presets[preset_index] if preset_index < len(previous_presets) else None
        )
        if helix_common.canonical_preset_signal_content(
            current_preset
        ) != helix_common.canonical_preset_signal_content(previous_preset):
            diff_ids.append(preset_index + 1)
    return diff_ids


def extract_diff_snapshot_ids(
    current_filename: str | os.PathLike[str],
    previous_filename: str | os.PathLike[str],
    snapshot_count: int = PODGO_SNAPSHOT_COUNT,
) -> dict[int, list[int]]:
    if get_filetype(current_filename) != get_filetype(previous_filename):
        raise ValueError("Diff input file type must match input file type")
    current_data = json.loads(load_input(current_filename)[0])
    previous_data = json.loads(load_input(previous_filename)[0])
    diff_snapshots = {}
    for preset_index, current_preset in enumerate(current_data.get("presets", [])):
        if is_default_preset(current_preset):
            continue
        previous_presets = previous_data.get("presets", [])
        previous_preset = (
            previous_presets[preset_index] if preset_index < len(previous_presets) else None
        )
        preset_id = preset_index + 1
        if helix_common.canonical_non_snapshot_signal_content(
            current_preset
        ) != helix_common.canonical_non_snapshot_signal_content(previous_preset):
            diff_snapshots[preset_id] = list(range(1, snapshot_count + 1))
            continue
        changed = [
            snapshot_index + 1
            for snapshot_index in range(snapshot_count)
            if helix_common.canonical_snapshot_signal_content(current_preset, snapshot_index)
            != helix_common.canonical_snapshot_signal_content(previous_preset, snapshot_index)
        ]
        if changed:
            diff_snapshots[preset_id] = changed
    return diff_snapshots


def has_output_gain_assignment(tone: dict[str, Any]) -> bool:
    output_controller = tone.get("controller", {}).get("dsp0", {}).get("output", {})
    if not isinstance(output_controller, dict):
        return False
    return _is_snapshot_gain_assignment(output_controller.get("gain"))


def _is_snapshot_gain_assignment(assignment: object) -> bool:
    return (
        isinstance(assignment, dict) and assignment.get("@controller") == PODGO_SNAPSHOT_CONTROLLER
    )


def count_snapshot_assigned_parameters(preset: dict[str, Any]) -> int:
    tone = preset.get("tone", {})
    if not isinstance(tone, dict):
        return 0
    controller = tone.get("controller", {})
    if not isinstance(controller, dict):
        return 0
    count = 0
    for dsp_controller in controller.values():
        if not isinstance(dsp_controller, dict):
            continue
        for block_controller in dsp_controller.values():
            if not isinstance(block_controller, dict):
                continue
            count += sum(
                1
                for parameter_controller in block_controller.values()
                if _is_snapshot_gain_assignment(parameter_controller)
            )
    return count


def get_missing_output_gain_assignments(preset: dict[str, Any]) -> list[tuple[str, str, str]]:
    tone = preset.get("tone", {})
    return (
        []
        if has_output_gain_assignment(tone) or not get_gain_outputs(preset)
        else [("dsp0", "output", "gain")]
    )


def validate_controller_assignment_capacity(
    data: dict[str, Any], gain_deltas: dict[str, Any] | None = None
) -> None:
    for preset_index, preset in enumerate(data.get("presets", [])):
        if is_default_preset(preset):
            continue
        podgo_preset = preset_index_to_podgo(preset_index)
        if gain_deltas is not None and podgo_preset not in gain_deltas:
            continue
        current_count = count_snapshot_assigned_parameters(preset)
        missing = get_missing_output_gain_assignments(preset)
        if current_count + len(missing) <= CONTROLLER_ASSIGNMENT_LIMIT:
            continue
        missing_text = ", ".join(".".join(item) for item in missing)
        raise ValueError(
            "Cannot assign output gain to snapshots: the Pod Go "
            f"snapshot-assigned parameter limit would be exceeded for preset {preset_index + 1} "
            f'({podgo_preset}, "{get_preset_name(preset)}"). '
            f"Current snapshot-assigned parameters: {current_count}. "
            f"Required additional assignments: {len(missing)} ({missing_text}). "
            f"Limit: {CONTROLLER_ASSIGNMENT_LIMIT}."
        )


def add_selected_output_gain_assignment(preset: dict[str, Any]) -> int:
    tone = preset.get("tone", {})
    if not isinstance(tone, dict):
        return 0
    changes = 0
    for dsp_name, output_name, output_block in get_gain_outputs(preset):
        base_gain = float(output_block["gain"])
        output_controller = (
            tone.setdefault("controller", {}).setdefault(dsp_name, {}).setdefault(output_name, {})
        )
        if not _is_snapshot_gain_assignment(output_controller.get("gain")):
            output_controller["gain"] = {
                "@controller": PODGO_SNAPSHOT_CONTROLLER,
                "@max": 20.0,
                "@min": -120.0,
            }
            changes += 1
        ensure_snapshot_output_gain_values(
            tone,
            dsp_name,
            output_name,
            base_gain,
            snapshot_count=PODGO_SNAPSHOT_COUNT,
        )
    return changes


def assign_snapshot_level(data: dict[str, Any], gain_deltas: dict[str, Any] | None = None) -> int:
    changes = 0
    for preset_index, preset in enumerate(data.get("presets", [])):
        if is_default_preset(preset):
            continue
        if gain_deltas is not None and preset_index_to_podgo(preset_index) not in gain_deltas:
            continue
        changes += add_selected_output_gain_assignment(preset)
    return changes


def adjust_snapshot_gains(
    data: dict[str, Any],
    gain_deltas: dict[str, dict[int, float | None]],
    *,
    ignore_bad_lufs: bool = False,
    snapshot_count: int = PODGO_SNAPSHOT_COUNT,
    gain_deadband_db: float = helix_common.GAIN_ADJUSTMENT_DEADBAND_DB,
    manual_gain_deltas: dict[str, Any] | None = None,
) -> int:
    changes = 0
    for preset_index, preset in enumerate(data.get("presets", [])):
        podgo_preset = preset_index_to_podgo(preset_index)
        if is_default_preset(preset) or podgo_preset not in gain_deltas:
            continue
        add_selected_output_gain_assignment(preset)
        tone = preset.get("tone", {})
        output_base_gains = [
            (dsp_name, output_name, output_block, float(output_block["gain"]))
            for dsp_name, output_name, output_block in get_gain_outputs(preset)
        ]
        changes += _adjust_preset_snapshot_gains(
            preset,
            podgo_preset,
            gain_deltas[podgo_preset],
            output_base_gains,
            ignore_bad_lufs,
            snapshot_count,
            gain_deadband_db,
            manual_gain_deltas,
        )
        _sync_output_gains_to_current_snapshot(tone, output_base_gains)
    return changes


def _adjust_preset_snapshot_gains(
    preset: dict[str, Any],
    podgo_preset: str,
    snapshot_gain_deltas: dict[int, float | None],
    output_base_gains: list[tuple[str, str, dict[str, Any], float]],
    ignore_bad_lufs: bool,
    snapshot_count: int,
    gain_deadband_db: float,
    manual_gain_deltas: dict[str, Any] | None,
) -> int:
    changes = 0
    tone = preset.get("tone", {})
    for snapshot_index in range(snapshot_count):
        snapshot = tone.get(f"snapshot{snapshot_index}")
        gain_delta = _snapshot_gain_delta(
            podgo_preset,
            snapshot_index,
            snapshot_gain_deltas,
            manual_gain_deltas,
        )
        if not isinstance(snapshot, dict) or gain_delta is None:
            continue
        if abs(gain_delta) <= gain_deadband_db:
            continue
        changes += _write_snapshot_output_gains(
            podgo_preset,
            snapshot,
            output_base_gains,
            gain_delta,
            ignore_bad_lufs,
        )
    return changes


def _snapshot_gain_delta(
    podgo_preset: str,
    snapshot_index: int,
    snapshot_gain_deltas: dict[int, float | None],
    manual_gain_deltas: dict[str, Any] | None,
) -> float | None:
    if snapshot_index not in snapshot_gain_deltas:
        return None
    manual_delta = (manual_gain_deltas or {}).get(podgo_preset, {}).get(str(snapshot_index))
    gain_delta = manual_delta if manual_delta is not None else snapshot_gain_deltas[snapshot_index]
    return None if gain_delta is None else float(gain_delta)


def _write_snapshot_output_gains(
    podgo_preset: str,
    snapshot: dict[str, Any],
    output_base_gains: list[tuple[str, str, dict[str, Any], float]],
    gain_delta: float,
    ignore_bad_lufs: bool,
) -> int:
    changes = 0
    for dsp_name, output_name, _, base_gain in output_base_gains:
        current_gain = get_snapshot_output_gain(snapshot, dsp_name, output_name, base_gain)
        new_gain = round(current_gain + gain_delta, 2)
        if not -120.0 <= new_gain <= 20.0:
            if ignore_bad_lufs:
                continue
            raise ValueError(f"Implausible output gain {new_gain} dB for {podgo_preset}")
        snapshot.setdefault("controllers", {}).setdefault(dsp_name, {}).setdefault(output_name, {})[
            "gain"
        ] = {
            "@fs_enabled": False,
            "@value": new_gain,
        }
        changes += 1
    return changes


def _sync_output_gains_to_current_snapshot(
    tone: dict[str, Any],
    output_base_gains: list[tuple[str, str, dict[str, Any], float]],
) -> int:
    current_snapshot = _current_snapshot_index(tone)
    snapshot = tone.get(f"snapshot{current_snapshot}")
    if not isinstance(snapshot, dict):
        return 0

    changes = 0
    for dsp_name, output_name, output_block, base_gain in output_base_gains:
        snapshot_gain = get_snapshot_output_gain(snapshot, dsp_name, output_name, base_gain)
        if output_block.get("gain") == snapshot_gain:
            continue
        output_block["gain"] = snapshot_gain
        changes += 1
    return changes


def _current_snapshot_index(tone: dict[str, Any]) -> int:
    global_settings = tone.get("global", {})
    if not isinstance(global_settings, dict):
        return 0
    try:
        return int(global_settings.get("@current_snapshot", 0))
    except (TypeError, ValueError):
        return 0


def process_json_structure(
    json_text: str,
    gain_deltas: dict[str, Any] | None = None,
    assign_output_gain: bool = False,
    ignore_bad_lufs: bool = False,
    snapshot_count: int = PODGO_SNAPSHOT_COUNT,
    gain_deadband_db: float = helix_common.GAIN_ADJUSTMENT_DEADBAND_DB,
    manual_gain_deltas: dict[str, Any] | None = None,
) -> tuple[str, int, int]:
    data = json.loads(json_text)
    snapshot_changes = 0
    if assign_output_gain:
        validate_controller_assignment_capacity(data, gain_deltas)
        snapshot_changes = assign_snapshot_level(data, gain_deltas)
    gain_changes = 0
    if gain_deltas is not None:
        gain_changes = adjust_snapshot_gains(
            data,
            gain_deltas,
            ignore_bad_lufs=ignore_bad_lufs,
            snapshot_count=snapshot_count,
            gain_deadband_db=gain_deadband_db,
            manual_gain_deltas=manual_gain_deltas,
        )
    return json.dumps(data, indent=1), snapshot_changes, gain_changes


def restore_original_input_values(modified_json_text: str, original_json_text: str) -> str:
    modified_data = json.loads(modified_json_text)
    original_data = json.loads(original_json_text)
    for modified_preset, original_preset in zip(
        modified_data.get("presets", []),
        original_data.get("presets", []),
        strict=False,
    ):
        _restore_preset_input_value(modified_preset, original_preset)
    return json.dumps(modified_data, indent=1)


def _restore_preset_input_value(
    modified_preset: dict[str, Any],
    original_preset: dict[str, Any],
) -> None:
    modified_input = modified_preset.get("tone", {}).get("dsp0", {}).get("input")
    original_input = original_preset.get("tone", {}).get("dsp0", {}).get("input")
    if not isinstance(modified_input, dict) or not isinstance(original_input, dict):
        return
    if "@input" not in original_input:
        return
    modified_input_data = cast("dict[str, Any]", modified_input)
    modified_input_data["@input"] = original_input["@input"]


def convert_json_text(text: str, mode: str) -> tuple[str, int, int]:
    data = json.loads(text)
    input_changes = 0
    output_changes = 0
    for preset in data.get("presets", []):
        if is_default_preset(preset):
            continue
        preset_input_changes, preset_output_changes = _convert_preset_io(preset, mode)
        input_changes += preset_input_changes
        output_changes += preset_output_changes
    return json.dumps(data, indent=1), input_changes, output_changes


def _convert_preset_io(preset: dict[str, Any], mode: str) -> tuple[int, int]:
    dsp0 = preset.get("tone", {}).get("dsp0", {})
    if not isinstance(dsp0, dict):
        return 0, 0
    return _convert_input_block(dsp0.get("input"), mode), _convert_output_block(
        dsp0.get("output"), mode
    )


def _convert_input_block(input_block: object, mode: str) -> int:
    if not isinstance(input_block, dict):
        return 0
    input_data = cast("dict[str, Any]", input_block)
    current_input = input_data.get("@input")
    if mode == "measurement" and current_input != PODGO_INPUT_USB_3_4:
        input_data["@input"] = PODGO_INPUT_USB_3_4
        return 1
    if mode == "stage" and current_input == PODGO_INPUT_USB_3_4:
        input_data["@input"] = PODGO_INPUT_GUITAR
        return 1
    return 0


def _convert_output_block(output_block: object, mode: str) -> int:
    if not isinstance(output_block, dict):
        return 0
    output_data = cast("dict[str, Any]", output_block)
    current_output = output_data.get("@output")
    if mode == "measurement" and current_output == PODGO_OUTPUT_MAIN:
        output_data["@output"] = PODGO_OUTPUT_USB_1_2
        return 1
    if mode == "stage" and current_output == PODGO_OUTPUT_USB_1_2:
        output_data["@output"] = PODGO_OUTPUT_MAIN
        return 1
    return 0


def join_preset_files_to_setlist(
    preset_paths: list[str | os.PathLike[str]],
    template_setlist_path: str | os.PathLike[str] | None = None,
    slot_ids: list[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    hls_text, metadata = file_ops.join_preset_files_to_compressed_setlist(
        preset_paths,
        template_setlist_path=template_setlist_path,
        slot_ids=slot_ids,
        preset_extension=PODGO_PRESET_EXTENSION,
        slot_label=preset_index_to_podgo,
    )
    if template_setlist_path is not None:
        return hls_text, metadata
    data = json.loads(file_ops.decode_compressed_setlist_text(hls_text))
    data.setdefault("meta", {"name": "User"})
    return build_new_pgs_text(json.dumps(data, indent=1)), metadata


def split_setlist_to_preset_data(
    input_path: str | os.PathLike[str],
    selected_ids: list[int] | None = None,
    original_filenames: dict[int | str, str] | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    split_presets = file_ops.split_compressed_setlist_to_preset_data(
        input_path,
        selected_ids=selected_ids,
        original_filenames=original_filenames,
        preset_extension=PODGO_PRESET_EXTENSION,
        slot_label=preset_index_to_podgo,
    )
    return [(filename, _wrap_pgp_preset(preset)) for filename, preset in split_presets]


def _wrap_pgp_preset(preset: dict[str, Any]) -> dict[str, Any]:
    return {"data": preset, "schema": "L6Preset", "version": 6}


def _parse_slot_ids(slot_ids: str | None) -> list[str] | None:
    if not slot_ids:
        return None
    return [slot_id.strip() for slot_id in slot_ids.split(",") if slot_id.strip()]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Line 6 Pod Go PGS/PGP/JSON Utility")
    parser.add_argument("-i", "--input", help="Input file (.pgs, .pgp, or .json)")
    parser.add_argument("-o", "--output", help="Output file (.pgs, .pgp, or .json)")
    parser.add_argument("--slot-ids", help="Comma-separated Pod Go slot IDs, for example 01A,01B")
    parser.add_argument("-g", "--lufs-analysis-file", help="LUFS analysis CSV file")
    parser.add_argument(
        "--manual-adjustments", help="GUI preset, snapshot, and gain overrides JSON"
    )
    parser.add_argument(
        "--custom-adjustments-file", help="CSV of per-preset snapshot target loudness bumps in dB"
    )
    parser.add_argument("--ignore-bad-lufs", action="store_true")
    parser.add_argument("--target-lufs", type=float, default=helix_common.TARGET_LUFS)
    parser.add_argument("--snapshot-count", type=int, default=PODGO_SNAPSHOT_COUNT)
    parser.add_argument(
        "--solo-regex",
        "--solo-marker",
        dest="solo_regex",
        default=r"(?i)\bsolo\b",
    )
    parser.add_argument(
        "--ignore-snapshot-regex",
        default=r"(?i)^SNAPSHOT [1-9]\d*$",
    )
    parser.add_argument("--solo-gain-bump-db", type=float, default=helix_common.SOLO_GAIN_BUMP)
    parser.add_argument(
        "--crest-factor-reference-db",
        type=float,
        default=helix_common.CREST_FACTOR_REFERENCE_DB,
    )
    parser.add_argument(
        "--crest-factor-correction-ratio",
        type=float,
        default=helix_common.CREST_FACTOR_CORRECTION_RATIO,
    )
    parser.add_argument(
        "--max-crest-factor-correction-db",
        type=float,
        default=helix_common.MAX_CREST_FACTOR_CORRECTION_DB,
    )
    parser.add_argument(
        "--gain-deadband-db", type=float, default=helix_common.GAIN_ADJUSTMENT_DEADBAND_DB
    )
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("-r", "--measurement", action="store_true")
    mode_group.add_argument("-s", "--stage", action="store_true")
    mode_group.add_argument("-a", "--adjust-gain", action="store_true")
    mode_group.add_argument("--list-presets", action="store_true")
    mode_group.add_argument("--metadata", action="store_true")
    mode_group.add_argument("--diff-presets", metavar="PREVIOUS_INPUT")
    mode_group.add_argument("--diff-snapshots", metavar="PREVIOUS_INPUT")
    mode_group.add_argument("--join-presets", nargs="+", metavar="PATH")
    mode_group.add_argument("--split-setlist", metavar="DIR")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    try:
        _run_command(args)
    except Exception as exc:
        print()
        print(f"ERROR: {exc}")
        print()
        sys.exit(1)


def _run_command(args: argparse.Namespace) -> None:
    if args.join_presets:
        _run_join_presets_command(args)
        return
    if args.split_setlist:
        _run_split_setlist_command(args)
        return

    _validate_input_args(args)
    json_text, original_data = load_input(args.input)
    if _run_query_command(args, json_text, original_data):
        return

    if not args.output:
        raise ValueError("Output file is required")
    modified_json_text = _convert_if_needed(args, json_text)
    modified_json_text, manual_adjustments = _apply_manual_adjustments(args, modified_json_text)
    gain_deltas = _load_gain_deltas(args)
    modified_json_text, _, _ = process_json_structure(
        modified_json_text,
        gain_deltas,
        args.measurement or args.stage or args.adjust_gain,
        args.ignore_bad_lufs,
        args.snapshot_count,
        args.gain_deadband_db,
        manual_adjustments.get("gain_deltas"),
    )
    if args.adjust_gain:
        modified_json_text = restore_original_input_values(modified_json_text, json_text)
    save_output(modified_json_text, args.output, original_data)


def _run_join_presets_command(args: argparse.Namespace) -> None:
    if not args.output:
        raise ValueError("Output file is required for --join-presets")
    text, _ = join_preset_files_to_setlist(
        args.join_presets,
        slot_ids=_parse_slot_ids(args.slot_ids),
    )
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(text)


def _run_split_setlist_command(args: argparse.Namespace) -> None:
    if not args.input:
        raise ValueError("Input file is required for --split-setlist")
    os.makedirs(args.split_setlist, exist_ok=True)
    for filename, preset_data in split_setlist_to_preset_data(args.input):
        with open(os.path.join(args.split_setlist, filename), "w", encoding="utf-8") as f:
            json.dump(preset_data, f, indent=1)


def _validate_input_args(args: argparse.Namespace) -> None:
    if args.snapshot_count < 1 or args.snapshot_count > PODGO_SNAPSHOT_COUNT:
        raise ValueError("Pod Go snapshot count must be between 1 and 4")
    if not args.input:
        raise ValueError("Input file is required")


def _run_query_command(
    args: argparse.Namespace,
    json_text: str,
    original_data: object,
) -> bool:
    if args.list_presets:
        json.dump(
            extract_preset_assignments(json.loads(json_text)),
            sys.stdout,
            indent=2,
            ensure_ascii=False,
        )
    elif args.metadata:
        json.dump(
            extract_metadata(args.input, json_text, original_data),
            sys.stdout,
            indent=2,
            ensure_ascii=False,
        )
    elif args.diff_presets:
        json.dump(extract_diff_preset_ids(args.input, args.diff_presets), sys.stdout, indent=2)
    elif args.diff_snapshots:
        json.dump(
            extract_diff_snapshot_ids(args.input, args.diff_snapshots, args.snapshot_count),
            sys.stdout,
            indent=2,
        )
    else:
        return False
    print()
    return True


def _convert_if_needed(args: argparse.Namespace, json_text: str) -> str:
    if not (args.measurement or args.stage):
        return json_text
    mode = "measurement" if args.measurement else "stage"
    return convert_json_text(json_text, mode)[0]


def _apply_manual_adjustments(
    args: argparse.Namespace,
    modified_json_text: str,
) -> tuple[str, dict[str, Any]]:
    if not args.manual_adjustments:
        return modified_json_text, {}
    with open(args.manual_adjustments, "r", encoding="utf-8") as f:
        manual_adjustments = json.load(f)
    data = json.loads(modified_json_text)
    helix_common.apply_manual_adjustments(data, manual_adjustments)
    return json.dumps(data), manual_adjustments


def _load_gain_deltas(args: argparse.Namespace) -> dict[str, Any] | None:
    if not args.adjust_gain:
        return None
    if not args.lufs_analysis_file:
        raise ValueError("Adjust gain mode requires -g lufs_analysis.csv")
    custom = (
        helix_common.load_custom_adjustments_file(args.custom_adjustments_file, args.snapshot_count)
        if args.custom_adjustments_file
        else None
    )
    gain_deltas = helix_common.load_lufs_analysis_file(
        args.lufs_analysis_file,
        args.target_lufs,
        args.snapshot_count,
        args.crest_factor_reference_db,
        args.crest_factor_correction_ratio,
        args.max_crest_factor_correction_db,
        custom_adjustments=custom,
    )
    if get_filetype(args.input) == "pgp":
        return {"01A": next(iter(gain_deltas.values()))} if gain_deltas else {}
    return gain_deltas


if __name__ == "__main__":
    main()
