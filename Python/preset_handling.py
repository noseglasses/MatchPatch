#!/usr/bin/env python3

import argparse
import base64
import binascii
import csv
import json
import math
import os
import re
import sys
import zlib

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
CREST_FACTOR_REFERENCE_DB = 12.0
CREST_FACTOR_CORRECTION_RATIO = 0.4
MAX_CREST_FACTOR_CORRECTION_DB = 3.0
GAIN_ADJUSTMENT_DEADBAND_DB = 0.25
HELIX_NAME_PATTERN = re.compile(r"""^[A-Za-z0-9\-_+=!@#$&()?:'",./ ]*$""")


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


# =================================================
# HLS DECODING
# =================================================


def decode_hls_text(hls_text):

    wrapper = json.loads(hls_text)

    compressed = base64.b64decode(wrapper["encoded_data"])

    raw = zlib.decompress(compressed)

    return raw.decode("utf-8")


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
            }
        )

    return assignments


def extract_metadata(filename, json_text, original_data=None):
    filetype = get_filetype(filename)
    data = json.loads(json_text)
    result = {
        "file_type": filetype,
        "metadata": list(iter_metadata_nodes(data)),
    }

    if filetype == "hls" and isinstance(original_data, str):
        wrapper = json.loads(original_data)
        result["wrapper"] = {
            key: value for key, value in wrapper.items() if key != "encoded_data"
        }
    elif filetype == "hlx" and isinstance(original_data, dict):
        wrapper = {
            key: value
            for key, value in original_data.items()
            if key not in {"data", "tone"}
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
    final_outputs = [output for output in get_final_output_blocks(preset) if "gain" in output[2]]

    if not final_outputs:
        return None

    for selected_output in final_outputs:
        output_block = selected_output[2]

        if output_block.get("@output") in [OUTPUT_XLR, OUTPUT_USB_1_2]:
            return selected_output

    return final_outputs[0]


def get_missing_selected_output_gain_assignment(preset):
    selected_output = find_gain_output(preset)

    if selected_output is None:
        return []

    dsp_name, output_name, _ = selected_output
    tone = preset.get("tone", {})
    controller_root = tone.get("controller", {})
    dsp_controller = {}

    if isinstance(controller_root, dict):
        dsp_controller = controller_root.get(dsp_name, {})

    if not isinstance(dsp_controller, dict):
        dsp_controller = {}

    output_controller = dsp_controller.get(output_name, {})

    if isinstance(output_controller, dict) and "gain" in output_controller:
        return []

    return [(dsp_name, output_name, "gain")]


def validate_controller_assignment_capacity(data, gain_deltas=None):
    presets = data.get("presets", [])

    for preset_index, preset in enumerate(presets):
        if is_default_preset(preset):
            continue

        helix_preset = preset_index_to_helix(preset_index)

        if gain_deltas is not None and helix_preset not in gain_deltas:
            continue

        current_count = count_controller_assignments(preset)

        missing = get_missing_selected_output_gain_assignment(preset)

        final_count = current_count + len(missing)

        if final_count <= CONTROLLER_ASSIGNMENT_LIMIT:
            continue

        preset_name = get_preset_name(preset)

        missing_text = ", ".join(
            f"{dsp_name}.{output_name}.{parameter}" for dsp_name, output_name, parameter in missing
        )

        raise ValueError(
            "Cannot assign output gain/level to snapshots: "
            "the Helix controller assignment limit would be "
            f"exceeded for preset {preset_index + 1} "
            f'({helix_preset}, "{preset_name}"). '
            f"Current controller assignments: {current_count}. "
            f"Required additional assignments: {len(missing)} "
            f"({missing_text}). "
            f"Limit: {CONTROLLER_ASSIGNMENT_LIMIT}. "
            "Please edit this preset manually in HX Edit/Helix "
            "and remove unused controller/snapshot assignments "
            "before running this conversion."
        )


def add_selected_output_gain_assignment(preset):
    selected_output = find_gain_output(preset)

    if selected_output is None:
        return 0

    dsp_name, output_name, _ = selected_output
    tone = preset.get("tone", {})

    controller_root = tone.setdefault("controller", {})

    dsp_controller = controller_root.setdefault(dsp_name, {})

    output_controller = dsp_controller.setdefault(output_name, {})

    if "gain" in output_controller:
        return 0

    output_controller["gain"] = {
        "@controller": 19,
        "@max": 20.0,
        "@min": -120.0,
        "@snapshot_disable": False,
    }

    return 1


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
                elif row.get(lufs_key) and row.get(crest_factor_key):
                    lufs_value = float(row[lufs_key])
                    crest_factor_db = float(row[crest_factor_key])

                    lufs_delta = target_lufs - lufs_value
                    crest_factor_correction = get_crest_factor_correction(
                        crest_factor_db,
                        crest_factor_reference_db,
                        crest_factor_correction_ratio,
                        max_crest_factor_correction_db,
                    )
                    gain_delta = round(lufs_delta - crest_factor_correction, 1)

                else:
                    raise ValueError(f"Missing {lufs_key} or {crest_factor_key} for {helix_preset}")

                snapshot_gain_deltas[i - 1] = gain_delta

            gain_deltas[helix_preset] = snapshot_gain_deltas

    return gain_deltas


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


def ensure_snapshot_output_gain_values(tone, dsp_name, output_name, base_gain):
    changes = 0

    for snapshot_index in range(8):
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
        controller_root = tone.get("controller", {})
        current_snapshot = get_current_snapshot_index(tone)

        if not isinstance(controller_root, dict):
            continue

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

                for parameter, assignment in block_controller.items():
                    if not isinstance(assignment, dict):
                        continue

                    if assignment.get("@controller") != 19:
                        continue

                    if parameter not in block:
                        continue

                    base_value = block[parameter]

                    for snapshot_index in range(8):
                        snapshot = tone.get(f"snapshot{snapshot_index}")

                        if not isinstance(snapshot, dict):
                            continue

                        snapshot_controllers = snapshot.setdefault("controllers", {})
                        dsp_snapshot = snapshot_controllers.setdefault(dsp_name, {})
                        block_snapshot = dsp_snapshot.setdefault(block_name, {})

                        if parameter not in block_snapshot:
                            block_snapshot[parameter] = {"@fs_enabled": False, "@value": base_value}

                    snapshot = tone.get(f"snapshot{current_snapshot}", {})
                    snapshot_value = (
                        snapshot.get("controllers", {})
                        .get(dsp_name, {})
                        .get(block_name, {})
                        .get(parameter)
                    )

                    if isinstance(snapshot_value, dict):
                        snapshot_value = snapshot_value.get("@value")

                    if snapshot_value is not None and block.get(parameter) != snapshot_value:
                        block[parameter] = snapshot_value
                        changes += 1

    return changes


def adjust_snapshot_gains(
    data,
    gain_deltas,
    ignore_bad_lufs=False,
    snapshot_count=4,
    solo_regex=r"(?i)\bsolo\b",
    solo_gain_bump_db=SOLO_GAIN_BUMP,
    gain_deadband_db=GAIN_ADJUSTMENT_DEADBAND_DB,
    manual_gain_deltas=None,
):

    changes = 0
    solo_pattern = re.compile(solo_regex)

    presets = data.get("presets", [])

    for preset_index, preset in enumerate(presets):
        if is_default_preset(preset):
            continue

        helix_preset = preset_index_to_helix(preset_index)

        if helix_preset not in gain_deltas:
            continue

        tone = preset.get("tone", {})
        snapshot_gain_deltas = gain_deltas[helix_preset]

        # -----------------------------------------
        # find exactly one active output block
        # -----------------------------------------

        selected_output = find_gain_output(preset)

        if selected_output is None:
            print(f"[GAIN] {helix_preset}: no active output block found")
            continue

        dsp_name, output_name, output_block = selected_output

        normalize_adjusted_output_to_xlr(preset_index, preset, dsp_name, output_name, output_block)

        base_gain = float(output_block["gain"])

        ensure_snapshot_output_gain_values(tone, dsp_name, output_name, base_gain)

        # -----------------------------------------
        # ensure snapshot controller exists
        # -----------------------------------------

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

        # -----------------------------------------
        # process measured view snapshots only
        # -----------------------------------------

        for snapshot_index in range(snapshot_count):
            snapshot_key = f"snapshot{snapshot_index}"
            snapshot = tone.get(snapshot_key)

            if not isinstance(snapshot, dict):
                continue

            if snapshot_index not in snapshot_gain_deltas:
                continue

            snapshot_name = snapshot.get("@name", f"Snapshot {snapshot_index + 1}")

            is_solo = solo_pattern.search(snapshot_name) is not None

            manual_delta = (manual_gain_deltas or {}).get(helix_preset, {}).get(str(snapshot_index))
            gain_delta = snapshot_gain_deltas[snapshot_index]
            marker = " (S)" if is_solo else ""

            if manual_delta is not None:
                gain_delta = float(manual_delta)
                if not math.isfinite(gain_delta):
                    raise ValueError(
                        f"Invalid manual gain delta for {helix_preset} snapshot "
                        f"{snapshot_index + 1}: {manual_delta!r}"
                    )
            elif gain_delta is None:
                print(f"[GAIN] {helix_preset} {snapshot_name}{marker} | bad LUFS")
                continue

            if is_solo and manual_delta is None:
                gain_delta += solo_gain_bump_db

            current_gain = get_snapshot_output_gain(snapshot, dsp_name, output_name, base_gain)

            delta_text = f"Delta: {gain_delta:+.1f} dB"

            if abs(gain_delta) <= gain_deadband_db:
                print(
                    f"[GAIN] "
                    f"{helix_preset} "
                    f"{snapshot_name}{marker} | "
                    f"stable at {current_gain:.1f} dB "
                    f"({delta_text})"
                )
                continue

            new_gain = round(current_gain + gain_delta, 2)

            if new_gain < -120.0 or new_gain > 20.0:
                message = (
                    f"Implausible output gain "
                    f"{new_gain} dB for "
                    f"{helix_preset} {snapshot_name}. "
                    "This usually means the "
                    "measurement recorded silence."
                )

                if not ignore_bad_lufs:
                    raise ValueError(message)

                print(f"[GAIN] {helix_preset} {snapshot_name}{marker} | bad LUFS ({message})")
                continue

            snapshot_controllers = snapshot.setdefault("controllers", {})

            dsp_snapshot = snapshot_controllers.setdefault(dsp_name, {})

            output_snapshot = dsp_snapshot.setdefault(output_name, {})

            output_snapshot["gain"] = {"@fs_enabled": False, "@value": new_gain}

            changes += 1

            print(
                f"[GAIN] "
                f"{helix_preset} "
                f"{snapshot_name}{marker} | "
                f"{current_gain:.1f} dB -> "
                f"{new_gain:.1f} dB "
                f"({delta_text})"
            )

        if sync_output_gain_to_current_snapshot(
            tone, dsp_name, output_name, output_block, base_gain
        ):
            print(f"[GAIN] {helix_preset}: synchronized output block gain to the current snapshot")

    return changes


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


def convert_json_text(text, mode):
    data = json.loads(text)
    input_changes = 0
    output_changes = 0

    for preset_index, preset in enumerate(data.get("presets", [])):
        if is_default_preset(preset):
            continue

        tone = preset.get("tone", {})

        for dsp_name in ["dsp0", "dsp1"]:
            dsp = tone.get(dsp_name)

            if not isinstance(dsp, dict):
                continue

            for input_name in ["inputA", "inputB"]:
                input_block = dsp.get(input_name)

                if not isinstance(input_block, dict):
                    continue

                current_input = input_block.get("@input")

                if mode == "measurement" and current_input == INPUT_MULTI:
                    input_block["@input"] = INPUT_USB_3_4
                    input_changes += 1

                elif mode == "stage" and current_input == INPUT_USB_3_4:
                    input_block["@input"] = INPUT_MULTI
                    input_changes += 1

        normalize_snapshot_assigned_parameters({"presets": [preset]})

        for dsp_name, output_name, output_block in get_final_output_blocks(preset):
            current_output = output_block.get("@output")

            if mode == "measurement":
                if current_output == OUTPUT_USB_1_2:
                    continue

                if current_output != OUTPUT_XLR:
                    warn_non_xlr_output_conversion(
                        preset_index, preset, dsp_name, output_name, current_output
                    )

                output_block["@output"] = OUTPUT_USB_1_2
                output_changes += 1

            elif mode == "stage":
                if current_output == OUTPUT_USB_1_2:
                    output_block["@output"] = OUTPUT_XLR
                    output_changes += 1

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
            solo_gain_bump_db,
            gain_deadband_db,
            manual_gain_deltas,
        )

    modified_json_text = json.dumps(data, indent=1)

    return (modified_json_text, snapshot_changes, gain_changes)


# =================================================
# BUILD HLS
# =================================================


def build_hls_text(original_hls_text, modified_json_text):

    raw = modified_json_text.encode("utf-8")

    compressed = zlib.compress(raw, level=9)

    encoded_data = base64.b64encode(compressed).decode("ascii")

    decompressed_size = len(raw)

    crc32 = binascii.crc32(raw) & 0xFFFFFFFF

    result = original_hls_text

    result = re.sub(
        r'("encoded_data"\s*:\s*")([^"]*)(")', rf"\g<1>{encoded_data}\g<3>", result, flags=re.DOTALL
    )

    result = re.sub(r'("decompressed_size"\s*:\s*)(\d+)', rf"\g<1>{decompressed_size}", result)

    result = re.sub(r'("crc32"\s*:\s*)(\d+)', rf"\g<1>{crc32}", result)

    return result


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

    raw = modified_json_text.encode("utf-8")

    compressed = zlib.compress(raw, level=9)

    wrapper = {
        "compression": {
            "crc32": (binascii.crc32(raw) & 0xFFFFFFFF),
            "decompressed_size": len(raw),
            "type": "zlib",
        },
        "encoded_data": base64.b64encode(compressed).decode("ascii"),
    }

    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(wrapper, f)


# =================================================
# MAIN
# =================================================


def main():

    parser = argparse.ArgumentParser(description=("Line 6 Helix HLS/HLX/JSON Utility"))

    parser.add_argument("-i", "--input", required=True, help="Input file (.hls, .hlx, or .json)")

    parser.add_argument("-o", "--output", help="Output file (.hls, .hlx, or .json)")

    parser.add_argument("-g", "--lufs-analysis-file", help="LUFS analysis CSV file")
    parser.add_argument(
        "--manual-adjustments", help="GUI preset, snapshot, and gain overrides JSON"
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

    parser.add_argument("--solo-regex", "--solo-marker", dest="solo_regex", default=r"(?i)\bsolo\b")

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

    args = parser.parse_args()

    try:
        input_filetype = get_filetype(args.input)

        if args.snapshot_count < 1 or args.snapshot_count > 8:
            raise ValueError("Snapshot count must be between 1 and 8")

        json_text, original_hls_text = load_input(args.input)

        if args.list_presets:
            data = json.loads(json_text)
            assignments = extract_preset_assignments(data)

            json.dump(assignments, sys.stdout, indent=2, ensure_ascii=False)

            print()

            return

        if args.metadata:
            metadata = extract_metadata(args.input, json_text, original_hls_text)

            json.dump(metadata, sys.stdout, indent=2, ensure_ascii=False)

            print()

            return

        if not args.output:
            raise ValueError("Output file is required unless --list-presets or --metadata is used")

        require_compatible_output_path(args.input, args.output)

        mode = "measurement" if args.measurement else "stage" if args.stage else "adjust-gain"

        modified_json_text = json_text
        input_changes = 0
        output_changes = 0

        if args.measurement or args.stage:
            (modified_json_text, input_changes, output_changes) = convert_json_text(json_text, mode)

        manual_adjustments = {}
        if args.manual_adjustments:
            with open(args.manual_adjustments, "r", encoding="utf-8") as f:
                manual_adjustments = json.load(f)
            data = json.loads(modified_json_text)
            apply_manual_adjustments(data, manual_adjustments)
            modified_json_text = json.dumps(data)

        gain_deltas = None

        if args.adjust_gain:
            if not args.lufs_analysis_file:
                raise ValueError("Adjust gain mode requires -g lufs_analysis.csv")

            gain_deltas = load_lufs_analysis_file(
                args.lufs_analysis_file,
                args.target_lufs,
                args.snapshot_count,
                args.crest_factor_reference_db,
                args.crest_factor_correction_ratio,
                args.max_crest_factor_correction_db,
            )

            if input_filetype == "hlx":
                gain_deltas = normalize_single_preset_gain_deltas(gain_deltas)

        (modified_json_text, snapshot_changes, gain_changes) = process_json_structure(
            modified_json_text,
            gain_deltas,
            args.measurement or args.stage or args.adjust_gain,
            args.ignore_bad_lufs,
            args.snapshot_count,
            args.solo_regex,
            args.solo_gain_bump_db,
            args.gain_deadband_db,
            manual_adjustments.get("gain_deltas"),
        )

        save_output(modified_json_text, args.output, original_hls_text)

    except Exception as e:
        print()
        print(f"ERROR: {e}")
        print()

        sys.exit(1)

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


if __name__ == "__main__":
    main()
