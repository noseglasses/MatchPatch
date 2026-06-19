#!/usr/bin/env python3

import argparse
import copy
import csv
import json
import math
import os
import re
import sys
from dataclasses import dataclass

from matchpatch.devices.line6.file_ops import (  # noqa: F401
    build_hls_text,
    build_new_hls_text,
    decode_hls_text,
    join_preset_files_to_setlist,
    split_setlist_to_preset_data,
)
from matchpatch.devices.line6.file_ops import (
    helix_to_preset_index as helix_to_preset_index,
)
from matchpatch.devices.line6.file_ops import (
    load_preset_file as load_preset_file,
)
from matchpatch.devices.line6.file_ops import (
    load_setlist_file as load_setlist_file,
)
from matchpatch.devices.line6.file_ops import (
    safe_preset_filename as safe_preset_filename,
)
from matchpatch.devices.line6.preset_handling import (
    ensure_snapshot_output_gain_values as line6_ensure_snapshot_output_gain_values,
)
from matchpatch.devices.line6.preset_handling import (
    get_snapshot_output_gain as line6_get_snapshot_output_gain,
)
from matchpatch.devices.line6.preset_handling import (
    normalize_regex_pattern as normalize_regex_pattern,
)

# =================================================
# HELIX CONSTANTS
# =================================================

INPUT_MULTI = 1
INPUT_USB_3_4 = 14

OUTPUT_XLR = 6
OUTPUT_DSP_HANDOFF = 2
OUTPUT_USB_1_2 = 10

OUTPUT_NAMES = {
    0: "None",
    1: "Multi",
    2: "Path 2A",
    3: "Path 2B",
    4: "Send 1/2",
    5: '1/4"',
    6: "XLR",
    7: "Digital",
    10: "USB 1/2",
    11: "USB 3/4",
    12: "USB 5/6",
    13: "USB 7/8",
}


TARGET_LUFS = -16.0
SOLO_GAIN_BUMP = 3.0
CONTROLLER_ASSIGNMENT_LIMIT = 64
LUFS_ERROR_SENTINEL = "ERROR"
LUFS_SKIP_SENTINEL = "SKIP"
CREST_FACTOR_REFERENCE_DB = 12.0
CREST_FACTOR_CORRECTION_RATIO = 0.4
MAX_CREST_FACTOR_CORRECTION_DB = 3.0
GAIN_ADJUSTMENT_DEADBAND_DB = 0.25
HELIX_NAME_PATTERN = re.compile(r"""^[A-Za-z0-9\-_+=!@#$&()?:'",./ ]*$""")


@dataclass(frozen=True)
class SnapshotGainContext:
    preset_id: str
    snapshot_index: int
    snapshot_name: str
    gain_delta: object
    manual_delta: object
    is_solo: bool
    is_ignored: bool
    snapshot: dict


# =================================================
# FILETYPE
# =================================================


def get_filetype(filename):

    ext = os.path.splitext(filename)[1].lower()

    if ext == ".hls":
        return "hls"

    if ext == ".hlx":
        return "hlx"

    if ext == ".json":
        return "json"

    raise ValueError(f"Unsupported file extension: {ext}")


def decode_hls_file(filename):

    with open(filename, "r", encoding="utf-8") as f:
        hls_text = f.read()

    json_text = decode_hls_text(hls_text)

    return json_text, hls_text


# =================================================
# PRESET ASSIGNMENT EXTRACTION
# =================================================


def extract_preset_assignments(data):

    assignments = []

    presets = data.get("presets", [])

    for preset_index, preset in enumerate(presets):
        preset_name = str(get_preset_name(preset)).strip()

        if is_default_preset(preset):
            continue

        assignments.append(
            {
                "id": preset_index + 1,
                "helix_preset": preset_index_to_helix(preset_index),
                "name": preset_name,
                "snapshot_names": [
                    snapshot.get("@name", f"Snapshot {snapshot_index + 1}")
                    for snapshot_index in range(8)
                    if isinstance(
                        snapshot := preset.get("tone", {}).get(f"snapshot{snapshot_index}"), dict
                    )
                ],
                "snapshot_output_paths": extract_snapshot_output_paths(preset),
                "snapshot_output_levels": extract_snapshot_output_levels(preset),
            }
        )

    return assignments


def extract_snapshot_output_paths(preset):
    return [
        f"{dsp_name}.{output_name}"
        for dsp_name, output_name, output_block in get_final_output_blocks(preset)
        if "gain" in output_block
    ]


def extract_snapshot_output_levels(preset):
    output_blocks = []
    for dsp_name, output_name, output_block in get_final_output_blocks(preset):
        if "gain" not in output_block:
            continue
        try:
            base_gain = float(output_block["gain"])
        except (TypeError, ValueError):
            continue
        output_blocks.append((dsp_name, output_name, base_gain))

    tone = preset.get("tone", {})
    levels = []

    for snapshot_index in range(8):
        snapshot = tone.get(f"snapshot{snapshot_index}")
        if not isinstance(snapshot, dict):
            continue

        levels.append(
            [
                get_snapshot_output_gain(snapshot, dsp_name, output_name, base_gain)
                for dsp_name, output_name, base_gain in output_blocks
            ]
        )

    return levels


def extract_diff_preset_ids(current_filename, previous_filename):
    current_filetype = get_filetype(current_filename)
    previous_filetype = get_filetype(previous_filename)
    if previous_filetype != current_filetype:
        raise ValueError(
            "Diff input file type must match input file type: "
            f".{previous_filetype} != .{current_filetype}"
        )

    current_json_text, _ = load_input(current_filename)
    previous_json_text, _ = load_input(previous_filename)
    current_data = json.loads(current_json_text)
    previous_data = json.loads(previous_json_text)
    current_presets = current_data.get("presets", [])
    previous_presets = previous_data.get("presets", [])
    diff_ids = []

    for preset_index, current_preset in enumerate(current_presets):
        if is_default_preset(current_preset):
            continue

        previous_preset = (
            previous_presets[preset_index] if preset_index < len(previous_presets) else None
        )
        if canonical_preset_signal_content(current_preset) != canonical_preset_signal_content(
            previous_preset
        ):
            diff_ids.append(preset_index + 1)

    return diff_ids


def extract_diff_snapshot_ids(current_filename, previous_filename, snapshot_count=8):
    current_filetype = get_filetype(current_filename)
    previous_filetype = get_filetype(previous_filename)
    if previous_filetype != current_filetype:
        raise ValueError(
            "Diff input file type must match input file type: "
            f".{previous_filetype} != .{current_filetype}"
        )

    current_json_text, _ = load_input(current_filename)
    previous_json_text, _ = load_input(previous_filename)
    current_data = json.loads(current_json_text)
    previous_data = json.loads(previous_json_text)
    current_presets = current_data.get("presets", [])
    previous_presets = previous_data.get("presets", [])
    diff_snapshots = {}

    for preset_index, current_preset in enumerate(current_presets):
        if is_default_preset(current_preset):
            continue

        previous_preset = (
            previous_presets[preset_index] if preset_index < len(previous_presets) else None
        )
        preset_id = preset_index + 1

        if canonical_non_snapshot_signal_content(
            current_preset
        ) != canonical_non_snapshot_signal_content(previous_preset):
            diff_snapshots[preset_id] = list(range(1, snapshot_count + 1))
            continue

        changed = []
        for snapshot_index in range(snapshot_count):
            if canonical_snapshot_signal_content(
                current_preset, snapshot_index
            ) != canonical_snapshot_signal_content(previous_preset, snapshot_index):
                changed.append(snapshot_index + 1)
        if changed:
            diff_snapshots[preset_id] = changed

    return diff_snapshots


def canonical_preset_signal_content(preset):
    if not isinstance(preset, dict):
        return None

    return remove_non_signal_content(preset.get("tone", {}))


def canonical_non_snapshot_signal_content(preset):
    if not isinstance(preset, dict):
        return None

    tone = preset.get("tone", {})
    if not isinstance(tone, dict):
        return None

    non_snapshot_tone = copy.deepcopy(
        {key: value for key, value in tone.items() if not is_snapshot_key(key)}
    )
    for dsp_name, block_name, parameter in iter_snapshot_assigned_parameters(tone):
        block = non_snapshot_tone.get(dsp_name, {}).get(block_name, {})
        if isinstance(block, dict):
            block.pop(parameter, None)

    return remove_non_signal_content(
        non_snapshot_tone,
    )


def canonical_snapshot_signal_content(preset, snapshot_index):
    if not isinstance(preset, dict):
        return None

    tone = preset.get("tone", {})
    if not isinstance(tone, dict):
        return None
    return remove_non_signal_content(
        {
            "snapshot": tone.get(f"snapshot{snapshot_index}"),
            "snapshot_assigned_parameters": snapshot_assigned_parameter_values(
                tone,
                snapshot_index,
            ),
        }
    )


def iter_snapshot_assigned_parameters(tone):
    controller_root = _controller_root(tone)
    if controller_root is None:
        return

    for dsp_name, block_name, block_controller, block in _iter_controller_blocks(
        tone, controller_root
    ):
        for parameter, assignment in block_controller.items():
            if _is_snapshot_parameter_assignment(assignment, parameter, block):
                yield str(dsp_name), str(block_name), str(parameter)


def _controller_root(tone):
    controller_root = tone.get("controller", {})
    if not isinstance(controller_root, dict):
        return None
    return controller_root


def _iter_controller_blocks(tone, controller_root):
    for dsp_name, dsp_controller in controller_root.items():
        if not isinstance(dsp_controller, dict):
            continue
        dsp = tone.get(dsp_name, {})
        if not isinstance(dsp, dict):
            continue
        for block_name, block_controller in dsp_controller.items():
            if not isinstance(block_controller, dict):
                continue
            block = dsp.get(block_name, {})
            if not isinstance(block, dict):
                continue
            yield dsp_name, block_name, block_controller, block


def _is_snapshot_parameter_assignment(assignment, parameter, block):
    return (
        isinstance(assignment, dict)
        and assignment.get("@controller") == 19
        and assignment.get("@snapshot_disable") is not True
        and parameter in block
    )


def snapshot_assigned_parameter_values(tone, snapshot_index):
    result = {}
    snapshot = tone.get(f"snapshot{snapshot_index}", {})
    snapshot_controllers = snapshot.get("controllers", {}) if isinstance(snapshot, dict) else {}

    for dsp_name, block_name, parameter in iter_snapshot_assigned_parameters(tone):
        block = tone.get(dsp_name, {}).get(block_name, {})
        base_value = block.get(parameter) if isinstance(block, dict) else None
        snapshot_value = snapshot_controllers.get(dsp_name, {}).get(block_name, {}).get(parameter)
        value = snapshot_value if snapshot_value is not None else base_value
        result.setdefault(dsp_name, {}).setdefault(block_name, {})[parameter] = copy.deepcopy(value)

    return result


def is_snapshot_key(key):
    return re.fullmatch(r"snapshot\d+", str(key)) is not None


def remove_non_signal_content(value):
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            key_text = str(key)
            normalized_key = key_text.lstrip("@").casefold()
            if (
                normalized_key
                in {
                    "current_snapshot",
                    "name",
                    "meta",
                    "metadata",
                }
                or "color" in normalized_key
            ):
                continue
            result[key_text] = remove_non_signal_content(child)
        return result

    if isinstance(value, list):
        return [remove_non_signal_content(child) for child in value]

    return value


def extract_metadata(filename, json_text, original_data=None):
    filetype = get_filetype(filename)
    data = json.loads(json_text)
    result = {
        "file_type": filetype,
        "metadata": list(iter_metadata_nodes(data)),
    }

    if filetype == "hls" and isinstance(original_data, str):
        wrapper = json.loads(original_data)
        result["wrapper"] = {key: value for key, value in wrapper.items() if key != "encoded_data"}
    elif filetype == "hlx" and isinstance(original_data, dict):
        wrapper = {
            key: value for key, value in original_data.items() if key not in {"data", "tone"}
        }
        if wrapper:
            result["wrapper"] = wrapper

    return result


def iter_metadata_nodes(value, path="$"):
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key).casefold() in {"meta", "metadata"}:
                yield {"path": child_path, "value": child}
            yield from iter_metadata_nodes(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_metadata_nodes(child, f"{path}[{index}]")


# =================================================
# SNAPSHOT LEVEL ASSIGNMENT
# =================================================


def get_preset_name(preset):
    meta = preset.get("meta", {})

    return meta.get("name") or preset.get("name") or preset.get("@name") or ""


def apply_manual_adjustments(data, adjustments):
    preset_names = adjustments.get("preset_names", {})
    snapshot_names = adjustments.get("snapshot_names", {})

    for preset_index, preset in enumerate(data.get("presets", [])):
        helix_preset = preset_index_to_helix(preset_index)

        if helix_preset in preset_names:
            name = str(preset_names[helix_preset])
            require_helix_name(name)
            preset.setdefault("meta", {})["name"] = name

        tone = preset.get("tone", {})
        for snapshot_index, name in snapshot_names.get(helix_preset, {}).items():
            name = str(name)
            require_helix_name(name)
            snapshot = tone.get(f"snapshot{int(snapshot_index)}")
            if isinstance(snapshot, dict):
                snapshot["@name"] = name


def require_helix_name(name):
    if HELIX_NAME_PATTERN.fullmatch(name) is None:
        raise ValueError(f"Invalid Helix name: {name!r}")


def require_helix_input_path(filename, label):
    filetype = get_filetype(filename)

    if filetype not in ["hls", "hlx"]:
        raise ValueError(f"{label} must be an .hls or .hlx file: {filename}")

    return filetype


def require_compatible_output_path(
    input_filename, output_filename, label="Output", allow_json=True
):
    input_filetype = get_filetype(input_filename)
    output_filetype = get_filetype(output_filename)

    if input_filetype == "hlx":
        if output_filetype != "hlx":
            raise ValueError(f"{label} must be an .hlx file when input is .hlx: {output_filename}")

        return output_filetype

    allowed = ["hls"]

    if allow_json:
        allowed.append("json")

    if output_filetype not in allowed:
        allowed_text = " or ".join(f".{item}" for item in allowed)
        raise ValueError(
            f"{label} must be {allowed_text} when input is .{input_filetype}: {output_filename}"
        )

    return output_filetype


def wrap_preset_data(data):
    if not isinstance(data, dict):
        raise ValueError(".hlx preset content must be a JSON object")

    if isinstance(data.get("data"), dict):
        preset = data["data"]

        if "tone" not in preset:
            raise ValueError(".hlx preset data does not contain a tone section")

        return {"presets": [preset]}

    if "presets" in data:
        raise ValueError(".hlx input must contain one preset, not a setlist")

    if "tone" not in data:
        raise ValueError(".hlx preset content does not contain a tone section")

    return {"presets": [data]}


def unwrap_preset_data(data):
    presets = data.get("presets")

    if not isinstance(presets, list) or len(presets) != 1:
        raise ValueError(".hlx output requires exactly one preset")

    return presets[0]


def rebuild_hlx_data(original_hlx_data, preset):
    if isinstance(original_hlx_data, dict) and isinstance(original_hlx_data.get("data"), dict):
        rebuilt = dict(original_hlx_data)
        rebuilt["data"] = preset
        return rebuilt

    return preset


def preset_has_blocks(preset):
    tone = preset.get("tone", {})

    if not isinstance(tone, dict):
        return False

    for dsp_name in ["dsp0", "dsp1"]:
        dsp = tone.get(dsp_name)

        if not isinstance(dsp, dict):
            continue

        for block_name in dsp:
            if str(block_name).startswith("block"):
                return True

    return False


def is_default_preset(preset):
    return not preset_has_blocks(preset)


def count_controller_assignments(preset):
    count = 0
    controller = preset.get("tone", {}).get("controller", {})

    if not isinstance(controller, dict):
        return count

    for dsp_controller in controller.values():
        if not isinstance(dsp_controller, dict):
            continue

        for block_controller in dsp_controller.values():
            if not isinstance(block_controller, dict):
                continue

            for parameter_controller in block_controller.values():
                if isinstance(parameter_controller, dict) and "@controller" in parameter_controller:
                    count += 1

    return count


def count_snapshot_assigned_properties(preset):
    tone = preset.get("tone", {})
    if not isinstance(tone, dict):
        return 0
    return sum(1 for _ in iter_snapshot_assigned_parameters(tone))


def iter_output_blocks(preset):
    tone = preset.get("tone", {})

    for dsp_name in ["dsp0", "dsp1"]:
        dsp = tone.get(dsp_name)

        if not isinstance(dsp, dict):
            continue

        for output_name in ["outputA", "outputB"]:
            output_block = dsp.get(output_name)

            if not isinstance(output_block, dict):
                continue

            yield dsp_name, output_name, output_block


def is_dsp_chained(preset):
    return any(
        block.get("@output") == OUTPUT_DSP_HANDOFF
        for dsp_name, _, block in iter_output_blocks(preset)
        if dsp_name == "dsp0"
    )


def dsp_has_active_input(preset, dsp_name):
    dsp = preset.get("tone", {}).get(dsp_name)

    if not isinstance(dsp, dict):
        return False

    for input_name in ["inputA", "inputB"]:
        input_block = dsp.get(input_name)

        if not isinstance(input_block, dict):
            continue

        if input_block.get("@input", 0) != 0:
            return True

    return False


def is_active_signal_dsp(preset, dsp_name, chained):
    if dsp_has_active_input(preset, dsp_name):
        return True

    return chained and dsp_name == "dsp1"


def get_final_output_blocks(preset):
    chained = is_dsp_chained(preset)
    final_outputs = []

    for dsp_name, output_name, output_block in iter_output_blocks(preset):
        if not is_active_signal_dsp(preset, dsp_name, chained):
            continue

        current_output = output_block.get("@output", 0)

        if current_output == 0:
            continue

        if current_output == OUTPUT_DSP_HANDOFF:
            continue

        if chained and dsp_name != "dsp1":
            continue

        final_outputs.append((dsp_name, output_name, output_block))

    return final_outputs


def find_gain_output(preset):
    final_outputs = get_gain_outputs(preset)

    if not final_outputs:
        return None

    for selected_output in final_outputs:
        output_block = selected_output[2]

        if output_block.get("@output") in [OUTPUT_XLR, OUTPUT_USB_1_2]:
            return selected_output

    return final_outputs[0]


def get_gain_outputs(preset):
    return [output for output in get_final_output_blocks(preset) if "gain" in output[2]]


def has_output_gain_assignment(tone, dsp_name, output_name):
    if not isinstance(tone, dict):
        return False

    controller_root = tone.get("controller", {})
    dsp_controller = {}

    if isinstance(controller_root, dict):
        dsp_controller = controller_root.get(dsp_name, {})

    if not isinstance(dsp_controller, dict):
        dsp_controller = {}

    output_controller = dsp_controller.get(output_name, {})

    if isinstance(output_controller, dict) and "gain" in output_controller:
        return True

    return False


def get_missing_output_gain_assignments(preset):
    missing = []
    tone = preset.get("tone", {})

    for dsp_name, output_name, _ in get_gain_outputs(preset):
        if has_output_gain_assignment(tone, dsp_name, output_name):
            continue

        missing.append((dsp_name, output_name, "gain"))

    return missing


def get_missing_selected_output_gain_assignment(preset):
    return get_missing_output_gain_assignments(preset)


def validate_controller_assignment_capacity(data, gain_deltas=None):
    presets = data.get("presets", [])

    for preset_index, preset in enumerate(presets):
        if is_default_preset(preset):
            continue

        helix_preset = preset_index_to_helix(preset_index)

        if gain_deltas is not None and helix_preset not in gain_deltas:
            continue

        current_count = count_snapshot_assigned_properties(preset)

        missing = get_missing_output_gain_assignments(preset)

        final_count = current_count + len(missing)

        if final_count <= CONTROLLER_ASSIGNMENT_LIMIT:
            continue

        preset_name = get_preset_name(preset)

        missing_text = ", ".join(
            f"{dsp_name}.{output_name}.{parameter}" for dsp_name, output_name, parameter in missing
        )

        raise ValueError(
            "Cannot assign output gain/level to snapshots: "
            "the Helix snapshot-assigned property limit would be "
            f"exceeded for preset {preset_index + 1} "
            f'({helix_preset}, "{preset_name}"). '
            f"Current snapshot-assigned properties: {current_count}. "
            f"Required additional assignments: {len(missing)} "
            f"({missing_text}). "
            f"Limit: {CONTROLLER_ASSIGNMENT_LIMIT}. "
            "Please edit this preset manually in HX Edit/Helix "
            "and remove unused snapshot assignments "
            "before running this conversion."
        )


def add_selected_output_gain_assignment(preset):
    tone = preset.get("tone", {})

    if not isinstance(tone, dict):
        return 0

    changes = 0

    for dsp_name, output_name, output_block in get_gain_outputs(preset):
        try:
            base_gain = float(output_block["gain"])
        except (TypeError, ValueError):
            continue

        controller_root = tone.setdefault("controller", {})
        dsp_controller = controller_root.setdefault(dsp_name, {})
        output_controller = dsp_controller.setdefault(output_name, {})

        if "gain" not in output_controller:
            output_controller["gain"] = {
                "@controller": 19,
                "@max": 20.0,
                "@min": -120.0,
                "@snapshot_disable": False,
            }
            changes += 1

        ensure_snapshot_output_gain_values(tone, dsp_name, output_name, base_gain)

    return changes


def assign_snapshot_level(data, gain_deltas=None):
    """
    Assigns output level/gain to snapshots by adding
    the matching controller entries.
    """

    changes = 0

    if not isinstance(data, dict):
        return changes

    presets = data.get("presets", [])

    for preset_index, preset in enumerate(presets):
        if is_default_preset(preset):
            continue

        if gain_deltas is not None and preset_index_to_helix(preset_index) not in gain_deltas:
            continue

        changes += add_selected_output_gain_assignment(preset)

    return changes


# =================================================
# LOAD LUFS ANALYSIS FILE
# =================================================


def get_crest_factor_correction(
    crest_factor_db,
    reference_db=CREST_FACTOR_REFERENCE_DB,
    correction_ratio=CREST_FACTOR_CORRECTION_RATIO,
    max_correction_db=MAX_CREST_FACTOR_CORRECTION_DB,
):
    return min(
        max((reference_db - crest_factor_db) * correction_ratio, 0.0),
        max_correction_db,
    )


def load_lufs_analysis_file(
    filename,
    target_lufs=TARGET_LUFS,
    snapshot_count=4,
    crest_factor_reference_db=CREST_FACTOR_REFERENCE_DB,
    crest_factor_correction_ratio=CREST_FACTOR_CORRECTION_RATIO,
    max_crest_factor_correction_db=MAX_CREST_FACTOR_CORRECTION_DB,
    custom_adjustments=None,
):

    gain_deltas = {}

    with open(filename, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        for row in reader:
            helix_preset = row["HelixPreset"].strip()

            snapshot_gain_deltas = {}

            for i in range(1, snapshot_count + 1):
                lufs_key = f"LUFS{i}"
                crest_factor_key = f"CrestFactor{i}"

                gain_delta = None

                if any(
                    str(row.get(key) or "").strip().upper() == LUFS_ERROR_SENTINEL
                    for key in [lufs_key, crest_factor_key]
                ):
                    gain_delta = None
                elif any(
                    str(row.get(key) or "").strip().upper() == LUFS_SKIP_SENTINEL
                    for key in [lufs_key, crest_factor_key]
                ):
                    continue
                elif row.get(lufs_key) and row.get(crest_factor_key):
                    lufs_value = float(row[lufs_key])
                    crest_factor_db = float(row[crest_factor_key])

                    custom_adjustment = 0.0
                    if custom_adjustments is not None:
                        custom_adjustment = custom_adjustments.get(helix_preset, {}).get(i - 1, 0.0)
                    lufs_delta = target_lufs - lufs_value
                    crest_factor_correction = get_crest_factor_correction(
                        crest_factor_db,
                        crest_factor_reference_db,
                        crest_factor_correction_ratio,
                        max_crest_factor_correction_db,
                    )
                    normal_gain_delta = round(lufs_delta - crest_factor_correction, 1)
                    gain_delta = normal_gain_delta + custom_adjustment

                else:
                    raise ValueError(f"Missing {lufs_key} or {crest_factor_key} for {helix_preset}")

                snapshot_gain_deltas[i - 1] = gain_delta

            gain_deltas[helix_preset] = snapshot_gain_deltas

    return gain_deltas


def load_custom_adjustments_file(filename, snapshot_count=4):
    adjustments = {}
    expected_columns = snapshot_count + 1

    with open(filename, "r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(f, dialect)

        for line_number, row in enumerate(reader, start=1):
            if not row or all(not cell.strip() for cell in row):
                continue
            if len(row) != expected_columns:
                raise ValueError(
                    f"Line {line_number}: expected {expected_columns} columns, got {len(row)}"
                )
            helix_preset, snapshot_adjustments = _parse_custom_adjustment_row(row, line_number)
            if helix_preset in adjustments:
                raise ValueError(f"Line {line_number}: duplicate preset ID {helix_preset!r}")
            adjustments[helix_preset] = snapshot_adjustments

    return adjustments


def _parse_custom_adjustment_row(row, line_number):
    helix_preset = row[0].strip().upper()
    if not helix_preset:
        raise ValueError(f"Line {line_number}: preset ID is empty")
    return helix_preset, _parse_snapshot_adjustments(row[1:], line_number)


def _parse_snapshot_adjustments(cells, line_number):
    snapshot_adjustments = {}
    for snapshot_index, cell in enumerate(cells):
        text = cell.strip()
        if not text:
            continue
        value = _parse_custom_adjustment_value(text, line_number, snapshot_index)
        snapshot_adjustments[snapshot_index] = value
    return snapshot_adjustments


def _parse_custom_adjustment_value(text, line_number, snapshot_index):
    try:
        value = float(text)
    except ValueError as exc:
        raise ValueError(
            f"Line {line_number}: snapshot {snapshot_index + 1} "
            f"custom adjustment is not a floating point number: {text!r}"
        ) from exc
    if not math.isfinite(value):
        raise ValueError(
            f"Line {line_number}: snapshot {snapshot_index + 1} "
            f"custom adjustment is not finite: {text!r}"
        )
    return value


def normalize_single_preset_gain_deltas(gain_deltas):
    if len(gain_deltas) > 1:
        raise ValueError(
            "Adjusting gain for an .hlx preset requires a LUFS "
            "analysis CSV with at most one usable preset row"
        )

    if not gain_deltas:
        return {}

    return {"01A": next(iter(gain_deltas.values()))}


# =================================================
# ADJUST SNAPSHOT GAINS
# =================================================

# =================================================
# ADJUST SNAPSHOT GAINS
# =================================================


def preset_index_to_helix(index):
    bank = (index // 4) + 1
    slot = ["A", "B", "C", "D"][index % 4]

    return f"{bank:02d}{slot}"


def get_snapshot_output_gain(snapshot, dsp_name, output_name, base_gain):
    return line6_get_snapshot_output_gain(snapshot, dsp_name, output_name, base_gain)


def ensure_snapshot_output_gain_values(tone, dsp_name, output_name, base_gain):
    return line6_ensure_snapshot_output_gain_values(
        tone, dsp_name, output_name, base_gain, snapshot_count=8
    )


def sync_output_gain_to_current_snapshot(tone, dsp_name, output_name, output_block, base_gain):
    global_settings = tone.get("global", {})
    current_snapshot = 0

    if isinstance(global_settings, dict):
        current_snapshot = global_settings.get("@current_snapshot", 0)

    snapshot = tone.get(f"snapshot{current_snapshot}")

    if not isinstance(snapshot, dict):
        return False

    snapshot_gain = get_snapshot_output_gain(snapshot, dsp_name, output_name, base_gain)

    if output_block.get("gain") == snapshot_gain:
        return False

    output_block["gain"] = snapshot_gain
    return True


def normalize_snapshot_assigned_output_gain(tone, dsp_name, output_name, output_block):
    controller_root = tone.get("controller", {})

    if not isinstance(controller_root, dict):
        return False

    dsp_controller = controller_root.get(dsp_name, {})

    if not isinstance(dsp_controller, dict):
        return False

    output_controller = dsp_controller.get(output_name, {})

    if not isinstance(output_controller, dict):
        return False

    controller_assignment = output_controller.get("gain")

    if not isinstance(controller_assignment, dict):
        return False

    if "gain" not in output_block:
        return False

    base_gain = float(output_block["gain"])

    ensure_snapshot_output_gain_values(tone, dsp_name, output_name, base_gain)

    return sync_output_gain_to_current_snapshot(
        tone, dsp_name, output_name, output_block, base_gain
    )


def get_current_snapshot_index(tone):
    global_settings = tone.get("global", {})

    if not isinstance(global_settings, dict):
        return 0

    return global_settings.get("@current_snapshot", 0)


def normalize_snapshot_assigned_parameters(data):
    changes = 0

    for preset in data.get("presets", []):
        tone = preset.get("tone", {})
        current_snapshot = get_current_snapshot_index(tone)
        for dsp_name, block_name, parameter, block in _iter_snapshot_parameter_values(tone):
            snapshot_value = _resolve_snapshot_controller_value(
                tone, current_snapshot, dsp_name, block_name, parameter
            )
            if _normalize_snapshot_parameter(block, parameter, snapshot_value):
                changes += 1

    return changes


def _iter_snapshot_parameter_values(tone, snapshot_count=8):
    controller_root = _controller_root(tone)
    if controller_root is None:
        return
    for dsp_name, block_name, block_controller, block in _iter_controller_blocks(
        tone, controller_root
    ):
        for parameter, assignment in block_controller.items():
            if not _is_snapshot_parameter_assignment(assignment, parameter, block):
                continue
            _ensure_snapshot_parameter_values(
                tone, dsp_name, block_name, parameter, block, snapshot_count
            )
            yield dsp_name, block_name, parameter, block


def _ensure_snapshot_parameter_values(tone, dsp_name, block_name, parameter, block, snapshot_count):
    base_value = block[parameter]
    for snapshot_index in range(snapshot_count):
        snapshot = tone.get(f"snapshot{snapshot_index}")
        if not isinstance(snapshot, dict):
            continue
        snapshot_controllers = snapshot.setdefault("controllers", {})
        dsp_snapshot = snapshot_controllers.setdefault(dsp_name, {})
        block_snapshot = dsp_snapshot.setdefault(block_name, {})
        if parameter not in block_snapshot:
            block_snapshot[parameter] = {"@fs_enabled": False, "@value": base_value}


def _resolve_snapshot_controller_value(tone, snapshot, dsp_name, block_name, parameter):
    snapshot_data = tone.get(f"snapshot{snapshot}", {})
    snapshot_value = (
        snapshot_data.get("controllers", {}).get(dsp_name, {}).get(block_name, {}).get(parameter)
    )
    if isinstance(snapshot_value, dict):
        return snapshot_value.get("@value")
    return snapshot_value


def _normalize_snapshot_parameter(block, parameter, snapshot_value):
    if snapshot_value is None or block.get(parameter) == snapshot_value:
        return False
    block[parameter] = snapshot_value
    return True


def adjust_snapshot_gains(
    data,
    gain_deltas,
    ignore_bad_lufs=False,
    snapshot_count=4,
    solo_regex=r"(?i)\bsolo\b",
    ignore_snapshot_regex=r"(?i)^SNAPSHOT [1-9]\d*$",
    solo_gain_bump_db=SOLO_GAIN_BUMP,
    gain_deadband_db=GAIN_ADJUSTMENT_DEADBAND_DB,
    manual_gain_deltas=None,
):
    changes = 0
    solo_pattern = re.compile(normalize_regex_pattern(solo_regex))
    ignore_snapshot_pattern = re.compile(normalize_regex_pattern(ignore_snapshot_regex))

    for preset_index, helix_preset, preset in _iter_adjustable_presets(data, gain_deltas):
        tone = preset.get("tone", {})
        snapshot_gain_deltas = gain_deltas[helix_preset]
        output_base_gains = _prepare_gain_outputs(preset_index, preset, tone)
        if output_base_gains is None:
            continue
        _ensure_gain_controllers(tone, output_base_gains)

        for context in _iter_snapshot_gain_contexts(
            tone,
            helix_preset,
            snapshot_gain_deltas,
            snapshot_count,
            manual_gain_deltas,
            solo_pattern,
            ignore_snapshot_pattern,
        ):
            result = _apply_snapshot_gain_delta(
                context,
                output_base_gains,
                ignore_bad_lufs,
                solo_gain_bump_db,
                gain_deadband_db,
            )
            _log_snapshot_gain_decision(context, result)
            changes += result.get("changes", 0)

        _sync_output_gains_to_current_snapshot(helix_preset, tone, output_base_gains)

    return changes


def _iter_adjustable_presets(data, gain_deltas):
    for preset_index, preset in enumerate(data.get("presets", [])):
        if is_default_preset(preset):
            continue
        helix_preset = preset_index_to_helix(preset_index)
        if helix_preset in gain_deltas:
            yield preset_index, helix_preset, preset


def _prepare_gain_outputs(preset_index, preset, tone):
    gain_outputs = get_gain_outputs(preset)
    helix_preset = preset_index_to_helix(preset_index)
    if not gain_outputs:
        print(f"[GAIN] {helix_preset}: no active output block found")
        return None

    output_base_gains = []
    for dsp_name, output_name, output_block in gain_outputs:
        normalize_adjusted_output_to_xlr(preset_index, preset, dsp_name, output_name, output_block)
        base_gain = float(output_block["gain"])
        output_base_gains.append((dsp_name, output_name, output_block, base_gain))
        ensure_snapshot_output_gain_values(tone, dsp_name, output_name, base_gain)
    return output_base_gains


def _ensure_gain_controllers(tone, output_base_gains):
    controller_root = tone.setdefault("controller", {})
    for dsp_name, output_name, _, _ in output_base_gains:
        output_controller = controller_root.setdefault(dsp_name, {}).setdefault(output_name, {})
        if "gain" not in output_controller:
            output_controller["gain"] = {
                "@controller": 19,
                "@max": 20.0,
                "@min": -120.0,
                "@snapshot_disable": False,
            }


def _iter_snapshot_gain_contexts(
    tone,
    helix_preset,
    snapshot_gain_deltas,
    snapshot_count,
    manual_gain_deltas,
    solo_pattern,
    ignore_snapshot_pattern,
):
    for snapshot_index in range(snapshot_count):
        snapshot = tone.get(f"snapshot{snapshot_index}")
        if not isinstance(snapshot, dict) or snapshot_index not in snapshot_gain_deltas:
            continue
        snapshot_name = snapshot.get("@name", f"Snapshot {snapshot_index + 1}")
        yield SnapshotGainContext(
            preset_id=helix_preset,
            snapshot_index=snapshot_index,
            snapshot_name=snapshot_name,
            gain_delta=snapshot_gain_deltas[snapshot_index],
            manual_delta=(manual_gain_deltas or {}).get(helix_preset, {}).get(str(snapshot_index)),
            is_solo=solo_pattern.search(snapshot_name) is not None,
            is_ignored=ignore_snapshot_pattern.search(snapshot_name) is not None,
            snapshot=snapshot,
        )


def _apply_snapshot_gain_delta(
    context,
    output_base_gains,
    ignore_bad_lufs,
    solo_gain_bump_db,
    gain_deadband_db,
):
    gain_delta = context.gain_delta
    if context.is_ignored:
        return {"kind": "ignored"}

    if context.manual_delta is not None:
        gain_delta = _validated_manual_gain_delta(context)
    elif gain_delta is None:
        return {"kind": "missing"}

    if context.is_solo and context.manual_delta is None:
        gain_delta += solo_gain_bump_db

    output_gain_changes = _snapshot_output_gain_changes(context, output_base_gains, gain_delta)
    if abs(gain_delta) <= gain_deadband_db:
        return {"kind": "stable", "gain_delta": gain_delta, "output_changes": output_gain_changes}

    bad_gain_message = _bad_output_gain_message(context, output_gain_changes)
    if bad_gain_message is not None:
        if not ignore_bad_lufs:
            raise ValueError(bad_gain_message)
        return {"kind": "bad_gain", "message": bad_gain_message}

    return _write_snapshot_gain_changes(context, output_gain_changes, gain_delta)


def _validated_manual_gain_delta(context):
    gain_delta = float(context.manual_delta)
    if not math.isfinite(gain_delta):
        raise ValueError(
            f"Invalid manual gain delta for {context.preset_id} snapshot "
            f"{context.snapshot_index + 1}: {context.manual_delta!r}"
        )
    return gain_delta


def _snapshot_output_gain_changes(context, output_base_gains, gain_delta):
    output_gain_changes = []
    for dsp_name, output_name, _, base_gain in output_base_gains:
        current_gain = get_snapshot_output_gain(context.snapshot, dsp_name, output_name, base_gain)
        new_gain = round(current_gain + gain_delta, 2)
        output_gain_changes.append((dsp_name, output_name, current_gain, new_gain))
    return output_gain_changes


def _bad_output_gain_message(context, output_gain_changes):
    for dsp_name, output_name, _, new_gain in output_gain_changes:
        if -120.0 <= new_gain <= 20.0:
            continue
        return (
            f"Implausible output gain "
            f"{new_gain} dB for "
            f"{context.preset_id} {context.snapshot_name} {dsp_name}.{output_name}. "
            "This usually means the "
            "measurement recorded silence."
        )
    return None


def _write_snapshot_gain_changes(context, output_gain_changes, gain_delta):
    snapshot_controllers = context.snapshot.setdefault("controllers", {})
    for dsp_name, output_name, _, new_gain in output_gain_changes:
        output_snapshot = snapshot_controllers.setdefault(dsp_name, {}).setdefault(output_name, {})
        output_snapshot["gain"] = {"@fs_enabled": False, "@value": new_gain}
    return {
        "kind": "applied",
        "gain_delta": gain_delta,
        "output_changes": output_gain_changes,
        "changes": len(output_gain_changes),
    }


def _log_snapshot_gain_decision(context, result):
    marker = " (S)" if context.is_solo else ""
    if result["kind"] == "ignored":
        print(
            f"[GAIN] {context.preset_id} {context.snapshot_name}{marker} | ignored by snapshot regex"
        )
        return
    if result["kind"] == "missing":
        print(
            f"[GAIN] {context.preset_id} {context.snapshot_name}{marker} | "
            "measurement unavailable (Missing LUFS or crest factor in analysis CSV)"
        )
        return
    if result["kind"] == "bad_gain":
        print(
            f"[GAIN] {context.preset_id} {context.snapshot_name}{marker} | "
            f"measurement unavailable ({result['message']})"
        )
        return

    delta_text = f"Delta: {result['gain_delta']:+g} dB"
    if result["kind"] == "stable":
        gain_text = ", ".join(
            f"{dsp_name}.{output_name} {current_gain:.1f} dB"
            for dsp_name, output_name, current_gain, _ in result["output_changes"]
        )
        print(
            f"[GAIN] "
            f"{context.preset_id} "
            f"{context.snapshot_name}{marker} | "
            f"stable at {gain_text} "
            f"({delta_text})"
        )
        return

    gain_text = ", ".join(
        f"{dsp_name}.{output_name} {current_gain:.1f} dB -> {new_gain:.1f} dB"
        for dsp_name, output_name, current_gain, new_gain in result["output_changes"]
    )
    print(
        f"[GAIN] {context.preset_id} {context.snapshot_name}{marker} | {gain_text} ({delta_text})"
    )


def _sync_output_gains_to_current_snapshot(helix_preset, tone, output_base_gains):
    for dsp_name, output_name, output_block, base_gain in output_base_gains:
        if sync_output_gain_to_current_snapshot(
            tone, dsp_name, output_name, output_block, base_gain
        ):
            print(
                f"[GAIN] {helix_preset}: synchronized "
                f"{dsp_name}.{output_name} gain to the current snapshot"
            )


# =================================================
# TEXTUAL CONVERSION
# =================================================


def output_label(value):
    name = OUTPUT_NAMES.get(value)

    if name is None:
        return f"unknown output (id {value})"

    return f"{name} (id {value})"


def warn_non_xlr_output_conversion(preset_index, preset, dsp_name, output_name, current_output):
    print(
        "WARNING: "
        f"{preset_index_to_helix(preset_index)} "
        f'"{get_preset_name(preset)}" '
        f"{dsp_name}.{output_name} was "
        f"{output_label(current_output)}, not XLR; "
        "converting final output to USB 1/2 for measurement.",
        file=sys.stderr,
    )


def normalize_adjusted_output_to_xlr(preset_index, preset, dsp_name, output_name, output_block):
    current_output = output_block.get("@output")

    if current_output == OUTPUT_XLR:
        return 0

    output_block["@output"] = OUTPUT_XLR

    print(
        f"[OUTPUT] "
        f"{preset_index_to_helix(preset_index)} "
        f'"{get_preset_name(preset)}" '
        f"{dsp_name}.{output_name}: "
        f"{output_label(current_output)} -> "
        f"{output_label(OUTPUT_XLR)}"
    )

    return 1


def _convert_input_block(input_block, mode):
    current_input = input_block.get("@input")
    if mode == "measurement" and current_input == INPUT_MULTI:
        input_block["@input"] = INPUT_USB_3_4
        return 1
    if mode == "stage" and current_input == INPUT_USB_3_4:
        input_block["@input"] = INPUT_MULTI
        return 1
    return 0


def _convert_output_block(preset_index, preset, dsp_name, output_name, output_block, mode):
    current_output = output_block.get("@output")
    if mode == "measurement":
        return _convert_measurement_output(
            preset_index, preset, dsp_name, output_name, output_block, current_output
        )
    if mode == "stage" and current_output == OUTPUT_USB_1_2:
        output_block["@output"] = OUTPUT_XLR
        return 1
    return 0


def _convert_measurement_output(
    preset_index, preset, dsp_name, output_name, output_block, current_output
):
    if current_output == OUTPUT_USB_1_2:
        return 0
    if current_output != OUTPUT_XLR:
        warn_non_xlr_output_conversion(preset_index, preset, dsp_name, output_name, current_output)
    output_block["@output"] = OUTPUT_USB_1_2
    return 1


def _convert_preset_io(preset_index, preset, mode):
    input_changes = 0
    output_changes = 0
    tone = preset.get("tone", {})

    for dsp_name in ["dsp0", "dsp1"]:
        dsp = tone.get(dsp_name)
        if not isinstance(dsp, dict):
            continue
        for input_name in ["inputA", "inputB"]:
            input_block = dsp.get(input_name)
            if isinstance(input_block, dict):
                input_changes += _convert_input_block(input_block, mode)

    normalize_snapshot_assigned_parameters({"presets": [preset]})

    for dsp_name, output_name, output_block in get_final_output_blocks(preset):
        output_changes += _convert_output_block(
            preset_index, preset, dsp_name, output_name, output_block, mode
        )

    return input_changes, output_changes


def convert_json_text(text, mode):
    data = json.loads(text)
    input_changes = 0
    output_changes = 0

    for preset_index, preset in enumerate(data.get("presets", [])):
        if is_default_preset(preset):
            continue
        preset_input_changes, preset_output_changes = _convert_preset_io(preset_index, preset, mode)
        input_changes += preset_input_changes
        output_changes += preset_output_changes

    return (json.dumps(data, indent=1), input_changes, output_changes)


# =================================================
# PROCESS JSON STRUCTURE
# =================================================


def process_json_structure(
    json_text,
    gain_deltas=None,
    assign_output_gain=False,
    ignore_bad_lufs=False,
    snapshot_count=4,
    solo_regex=r"(?i)\bsolo\b",
    ignore_snapshot_regex=r"(?i)^SNAPSHOT [1-9]\d*$",
    solo_gain_bump_db=SOLO_GAIN_BUMP,
    gain_deadband_db=GAIN_ADJUSTMENT_DEADBAND_DB,
    manual_gain_deltas=None,
):

    data = json.loads(json_text)

    snapshot_changes = 0

    if gain_deltas is not None:
        normalize_snapshot_assigned_parameters(data)

    if assign_output_gain:
        validate_controller_assignment_capacity(data, gain_deltas)

        snapshot_changes = assign_snapshot_level(data, gain_deltas)

    gain_changes = 0

    if gain_deltas is not None:
        gain_changes = adjust_snapshot_gains(
            data,
            gain_deltas,
            ignore_bad_lufs,
            snapshot_count,
            solo_regex,
            ignore_snapshot_regex,
            solo_gain_bump_db,
            gain_deadband_db,
            manual_gain_deltas,
        )

    modified_json_text = json.dumps(data, indent=1)

    return (modified_json_text, snapshot_changes, gain_changes)


# =================================================
# LOAD INPUT
# =================================================


def load_input(filename):

    filetype = get_filetype(filename)

    if filetype == "hls":
        json_text, original_hls_text = decode_hls_file(filename)

        return (json_text, original_hls_text)

    with open(filename, "r", encoding="utf-8") as f:
        json_text = f.read()

    if filetype == "hlx":
        original_hlx_data = json.loads(json_text)
        data = wrap_preset_data(original_hlx_data)

        return (json.dumps(data, indent=1), original_hlx_data)

    return json_text, None


# =================================================
# SAVE OUTPUT
# =================================================


def save_output(modified_json_text, output_filename, original_hls_text=None):

    filetype = get_filetype(output_filename)

    if filetype == "json":
        with open(output_filename, "w", encoding="utf-8") as f:
            f.write(modified_json_text)

        return

    if filetype == "hlx":
        data = json.loads(modified_json_text)
        preset = unwrap_preset_data(data)
        hlx_data = rebuild_hlx_data(original_hls_text, preset)

        with open(output_filename, "w", encoding="utf-8") as f:
            json.dump(hlx_data, f, indent=1)

        return

    if original_hls_text is not None:
        rebuilt_hls = build_hls_text(original_hls_text, modified_json_text)

        with open(output_filename, "w", encoding="utf-8") as f:
            f.write(rebuilt_hls)

        return

    with open(output_filename, "w", encoding="utf-8") as f:
        f.write(build_new_hls_text(modified_json_text))


# =================================================
# MAIN
# =================================================


def _build_parser():
    parser = argparse.ArgumentParser(description=("Line 6 Helix HLS/HLX/JSON Utility"))

    parser.add_argument("-i", "--input", help="Input file (.hls, .hlx, or .json)")

    parser.add_argument("-o", "--output", help="Output file (.hls, .hlx, or .json)")

    parser.add_argument(
        "--slot-ids",
        help="Comma-separated Helix slot IDs for --join-presets, for example 01A,01B",
    )

    parser.add_argument("-g", "--lufs-analysis-file", help="LUFS analysis CSV file")
    parser.add_argument(
        "--manual-adjustments", help="GUI preset, snapshot, and gain overrides JSON"
    )
    parser.add_argument(
        "--custom-adjustments-file",
        help="CSV of per-preset snapshot target loudness bumps in dB",
    )

    parser.add_argument(
        "--ignore-bad-lufs",
        action="store_true",
        help=("Skip implausible LUFS-derived gain values instead of aborting"),
    )

    parser.add_argument(
        "--target-lufs",
        type=float,
        default=TARGET_LUFS,
        help=(
            "Target average short-term LUFS value used for gain "
            f"adjustment (default: {TARGET_LUFS:g})"
        ),
    )

    parser.add_argument("--snapshot-count", type=int, default=4)

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

    parser.add_argument("--solo-gain-bump-db", type=float, default=SOLO_GAIN_BUMP)

    parser.add_argument(
        "--crest-factor-reference-db",
        type=float,
        default=CREST_FACTOR_REFERENCE_DB,
    )

    parser.add_argument(
        "--crest-factor-correction-ratio",
        type=float,
        default=CREST_FACTOR_CORRECTION_RATIO,
    )

    parser.add_argument(
        "--max-crest-factor-correction-db",
        type=float,
        default=MAX_CREST_FACTOR_CORRECTION_DB,
    )

    parser.add_argument(
        "--gain-deadband-db",
        type=float,
        default=GAIN_ADJUSTMENT_DEADBAND_DB,
    )

    mode_group = parser.add_mutually_exclusive_group(required=True)

    mode_group.add_argument(
        "-r", "--measurement", action="store_true", help=("Convert Multi/XLR -> USB")
    )

    mode_group.add_argument("-s", "--stage", action="store_true", help=("Convert USB -> Multi/XLR"))

    mode_group.add_argument(
        "-a", "--adjust-gain", action="store_true", help=("Adjust snapshot gains using gain CSV")
    )

    mode_group.add_argument(
        "--list-presets",
        action="store_true",
        help=("Print non-default preset ID/name assignments as JSON"),
    )

    mode_group.add_argument(
        "--metadata",
        action="store_true",
        help=("Print extracted file metadata as JSON"),
    )

    mode_group.add_argument(
        "--diff-presets",
        metavar="PREVIOUS_INPUT",
        help=("Print preset IDs whose loudness-affecting content differs from PREVIOUS_INPUT"),
    )

    mode_group.add_argument(
        "--diff-snapshots",
        metavar="PREVIOUS_INPUT",
        help=(
            "Print changed snapshot IDs per preset whose loudness-affecting content "
            "differs from PREVIOUS_INPUT"
        ),
    )

    mode_group.add_argument(
        "--join-presets",
        nargs="+",
        metavar="PATH",
        help="Join .hlx preset files into an .hls setlist",
    )

    mode_group.add_argument(
        "--split-setlist",
        metavar="DIR",
        help="Split an .hls setlist into .hlx preset files in DIR",
    )

    return parser


def _load_input_text(args):
    if not args.input:
        raise ValueError("Input file is required")
    input_filetype = get_filetype(args.input)
    if args.snapshot_count < 1 or args.snapshot_count > 8:
        raise ValueError("Snapshot count must be between 1 and 8")
    json_text, original_hls_text = load_input(args.input)
    return input_filetype, json_text, original_hls_text


def _run_query_command(args, json_text, original_hls_text):
    if args.list_presets:
        data = json.loads(json_text)
        json.dump(extract_preset_assignments(data), sys.stdout, indent=2, ensure_ascii=False)
    elif args.metadata:
        metadata = extract_metadata(args.input, json_text, original_hls_text)
        json.dump(metadata, sys.stdout, indent=2, ensure_ascii=False)
    elif args.diff_presets:
        json.dump(extract_diff_preset_ids(args.input, args.diff_presets), sys.stdout, indent=2)
    elif args.diff_snapshots:
        diff_snapshots = extract_diff_snapshot_ids(
            args.input,
            args.diff_snapshots,
            args.snapshot_count,
        )
        json.dump(diff_snapshots, sys.stdout, indent=2)
    else:
        return False
    print()
    return True


def _require_output_for_mutating_command(args):
    if not args.output:
        raise ValueError(
            "Output file is required unless --list-presets, --metadata, "
            "--diff-presets, or --diff-snapshots is used"
        )
    require_compatible_output_path(args.input, args.output)


def _conversion_mode(args):
    return "measurement" if args.measurement else "stage" if args.stage else "adjust-gain"


def _convert_if_needed(args, json_text, mode):
    if args.measurement or args.stage:
        return convert_json_text(json_text, mode)
    return json_text, 0, 0


def _apply_manual_adjustments_if_needed(args, modified_json_text):
    if not args.manual_adjustments:
        return modified_json_text, {}
    with open(args.manual_adjustments, "r", encoding="utf-8") as f:
        manual_adjustments = json.load(f)
    data = json.loads(modified_json_text)
    apply_manual_adjustments(data, manual_adjustments)
    return json.dumps(data), manual_adjustments


def _load_gain_deltas_for_command(args, input_filetype):
    if not args.adjust_gain:
        return None
    if not args.lufs_analysis_file:
        raise ValueError("Adjust gain mode requires -g lufs_analysis.csv")
    custom_adjustments = _load_custom_adjustments_for_command(args)
    gain_deltas = load_lufs_analysis_file(
        args.lufs_analysis_file,
        args.target_lufs,
        args.snapshot_count,
        args.crest_factor_reference_db,
        args.crest_factor_correction_ratio,
        args.max_crest_factor_correction_db,
        custom_adjustments,
    )
    return (
        normalize_single_preset_gain_deltas(gain_deltas) if input_filetype == "hlx" else gain_deltas
    )


def _load_custom_adjustments_for_command(args):
    if not args.custom_adjustments_file:
        return None
    return load_custom_adjustments_file(args.custom_adjustments_file, args.snapshot_count)


def _parse_slot_ids(slot_ids):
    if not slot_ids:
        return None
    return [slot_id.strip() for slot_id in slot_ids.split(",") if slot_id.strip()]


def _run_join_presets_command(args):
    if not args.output:
        raise ValueError("Output file is required for --join-presets")
    if get_filetype(args.output) != "hls":
        raise ValueError(f"Join output must be an .hls file: {args.output}")

    hls_text, metadata = join_preset_files_to_setlist(
        args.join_presets,
        slot_ids=_parse_slot_ids(args.slot_ids),
    )
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(hls_text)
    return metadata


def _run_split_setlist_command(args):
    if not args.input:
        raise ValueError("Input file is required for --split-setlist")
    if get_filetype(args.input) != "hls":
        raise ValueError(f"Split input must be an .hls file: {args.input}")

    os.makedirs(args.split_setlist, exist_ok=True)
    split_presets = split_setlist_to_preset_data(args.input)
    for filename, hlx_data in split_presets:
        output_path = os.path.join(args.split_setlist, filename)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(hlx_data, f, indent=1)
    return split_presets


def _run_split_join_command(args):
    if args.join_presets:
        metadata = _run_join_presets_command(args)
        print(f"[OK] Joined {len(args.join_presets)} presets into {args.output}")
        return metadata
    if args.split_setlist:
        split_presets = _run_split_setlist_command(args)
        print(f"[OK] Split {len(split_presets)} presets into {args.split_setlist}")
        return split_presets
    return None


def _run_preset_handling_command(args, json_text, input_filetype):
    mode = _conversion_mode(args)
    modified_json_text, input_changes, output_changes = _convert_if_needed(args, json_text, mode)
    modified_json_text, manual_adjustments = _apply_manual_adjustments_if_needed(
        args, modified_json_text
    )
    gain_deltas = _load_gain_deltas_for_command(args, input_filetype)
    modified_json_text, snapshot_changes, gain_changes = process_json_structure(
        modified_json_text,
        gain_deltas,
        args.measurement or args.stage or args.adjust_gain,
        args.ignore_bad_lufs,
        args.snapshot_count,
        args.solo_regex,
        args.ignore_snapshot_regex,
        args.solo_gain_bump_db,
        args.gain_deadband_db,
        manual_adjustments.get("gain_deltas"),
    )
    return modified_json_text, mode, input_changes, output_changes, snapshot_changes, gain_changes


def _write_output(args, modified_json_text, original_hls_text):
    save_output(modified_json_text, args.output, original_hls_text)


def _print_processing_summary(
    args, mode, input_changes, output_changes, snapshot_changes, gain_changes
):
    print()
    print("[OK] Processing complete")
    print()
    print(f"Mode   : {mode}")
    print(f"Input  : {args.input}")
    print(f"Output : {args.output}")
    if args.lufs_analysis_file:
        print(f"LUFSCSV: {args.lufs_analysis_file}")
    print()
    print(f"Input replacements : {input_changes}")
    print(f"Output replacements: {output_changes}")
    print(f"Snapshot assignments: {snapshot_changes}")
    print(f"Gain adjustments    : {gain_changes}")
    print()


def main():
    args = _build_parser().parse_args()

    try:
        if args.join_presets or args.split_setlist:
            _run_split_join_command(args)
            return
        input_filetype, json_text, original_hls_text = _load_input_text(args)
        if _run_query_command(args, json_text, original_hls_text):
            return
        _require_output_for_mutating_command(args)
        result = _run_preset_handling_command(args, json_text, input_filetype)
        modified_json_text, mode, input_changes, output_changes, snapshot_changes, gain_changes = (
            result
        )
        _write_output(args, modified_json_text, original_hls_text)

    except Exception as e:
        print()
        print(f"ERROR: {e}")
        print()

        sys.exit(1)

    _print_processing_summary(
        args, mode, input_changes, output_changes, snapshot_changes, gain_changes
    )


if __name__ == "__main__":
    main()
