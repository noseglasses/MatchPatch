#!/usr/bin/env python3

import argparse
import base64
import binascii
import csv
import json
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
    5: "1/4\"",
    6: "XLR",
    7: "Digital",
    10: "USB 1/2",
    11: "USB 3/4",
    12: "USB 5/6",
    13: "USB 7/8"
}

TARGET_LUFS = -23.0
SOLO_GAIN_BUMP = 3.0
CLEAN_GAIN_BUMP = 2.0
CONTROLLER_ASSIGNMENT_LIMIT = 64


# =================================================
# FILETYPE
# =================================================

def get_filetype(filename):

    ext = os.path.splitext(filename)[1].lower()

    if ext == ".hls":
        return "hls"

    if ext == ".json":
        return "json"

    raise ValueError(
        f"Unsupported file extension: {ext}"
    )


# =================================================
# HLS DECODING
# =================================================

def decode_hls_text(hls_text):

    wrapper = json.loads(hls_text)

    compressed = base64.b64decode(
        wrapper["encoded_data"]
    )

    raw = zlib.decompress(compressed)

    return raw.decode("utf-8")


def decode_hls_file(filename):

    with open(
        filename,
        "r",
        encoding="utf-8"
    ) as f:

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

        meta = preset.get("meta", {})

        preset_name = (
            meta.get("name")
            or preset.get("name")
            or preset.get("@name")
            or ""
        )

        preset_name = str(preset_name).strip()

        if preset_name == "New Preset":
            continue

        assignments.append(
            {
                "id": preset_index + 1,
                "helix_preset": preset_index_to_helix(
                    preset_index
                ),
                "name": preset_name
            }
        )

    return assignments


# =================================================
# SNAPSHOT LEVEL ASSIGNMENT
# =================================================

def get_preset_name(preset):
    meta = preset.get("meta", {})

    return (
        meta.get("name")
        or preset.get("name")
        or preset.get("@name")
        or ""
    )


def is_default_preset(preset):
    return str(get_preset_name(preset)).strip() == "New Preset"


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
                if (
                    isinstance(parameter_controller, dict)
                    and "@controller" in parameter_controller
                ):
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

    for dsp_name, output_name, output_block in iter_output_blocks(
        preset
    ):
        if not is_active_signal_dsp(
            preset,
            dsp_name,
            chained
        ):
            continue

        current_output = output_block.get("@output", 0)

        if current_output == 0:
            continue

        if current_output == OUTPUT_DSP_HANDOFF:
            continue

        if chained and dsp_name != "dsp1":
            continue

        final_outputs.append(
            (
                dsp_name,
                output_name,
                output_block
            )
        )

    return final_outputs


def find_gain_output(preset):
    final_outputs = [
        output
        for output in get_final_output_blocks(preset)
        if "gain" in output[2]
    ]

    if not final_outputs:
        return None

    for selected_output in final_outputs:
        output_block = selected_output[2]

        if output_block.get("@output") in [
            OUTPUT_XLR,
            OUTPUT_USB_1_2
        ]:
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
        dsp_controller = controller_root.get(
            dsp_name,
            {}
        )

    if not isinstance(dsp_controller, dict):
        dsp_controller = {}

    output_controller = dsp_controller.get(
        output_name,
        {}
    )

    if (
        isinstance(output_controller, dict)
        and "gain" in output_controller
    ):
        return []

    return [
        (
            dsp_name,
            output_name,
            "gain"
        )
    ]


def validate_controller_assignment_capacity(
    data,
    gain_deltas=None
):
    presets = data.get("presets", [])

    for preset_index, preset in enumerate(presets):
        if is_default_preset(preset):
            continue

        helix_preset = preset_index_to_helix(
            preset_index
        )

        if (
            gain_deltas is not None
            and helix_preset not in gain_deltas
        ):
            continue

        current_count = count_controller_assignments(
            preset
        )

        missing = get_missing_selected_output_gain_assignment(
            preset
        )

        final_count = current_count + len(missing)

        if final_count <= CONTROLLER_ASSIGNMENT_LIMIT:
            continue

        preset_name = get_preset_name(preset)

        missing_text = ", ".join(
            f"{dsp_name}.{output_name}.{parameter}"
            for dsp_name, output_name, parameter in missing
        )

        raise ValueError(
            "Cannot assign output gain/level to snapshots: "
            "the Helix controller assignment limit would be "
            f"exceeded for preset {preset_index + 1} "
            f"({helix_preset}, \"{preset_name}\"). "
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

    controller_root = tone.setdefault(
        "controller",
        {}
    )

    dsp_controller = controller_root.setdefault(
        dsp_name,
        {}
    )

    output_controller = dsp_controller.setdefault(
        output_name,
        {}
    )

    if "gain" in output_controller:
        return 0

    output_controller["gain"] = {
        "@controller": 19,
        "@max": 20.0,
        "@min": -120.0,
        "@snapshot_disable": False
    }

    return 1


def assign_snapshot_level(data):

    """
    Assigns output level/gain to snapshots by adding
    the matching controller entries.
    """

    changes = 0

    if not isinstance(data, dict):
        return changes

    presets = data.get("presets", [])

    for preset in presets:
        if is_default_preset(preset):
            continue

        changes += add_selected_output_gain_assignment(
            preset
        )

    return changes


# =================================================
# LOAD LUFS ANALYSIS FILE
# =================================================

def load_lufs_analysis_file(filename):

    gain_deltas = {}

    with open(
        filename,
        "r",
        encoding="utf-8-sig"
    ) as f:

        reader = csv.DictReader(f)

        for row in reader:

            helix_preset = row["HelixPreset"].strip()

            snapshot_gain_deltas = {}

            for i in range(1, 5):
                lufs_key = f"LUFS{i}"

                gain_delta = None

                if row.get(lufs_key):
                    lufs_value = float(
                        row[lufs_key]
                    )

                    lufs_delta = TARGET_LUFS - lufs_value
                    gain_delta = round(lufs_delta, 1)

                else:
                    raise ValueError(
                        f"Missing {lufs_key} "
                        f"for {helix_preset}"
                    )

                snapshot_gain_deltas[i - 1] = gain_delta

            gain_deltas[helix_preset] = snapshot_gain_deltas

    return gain_deltas


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


def adjust_snapshot_gains(
    data,
    gain_deltas,
    ignore_bad_lufs=False
):

    changes = 0

    presets = data.get("presets", [])

    for preset_index, preset in enumerate(presets):
        if is_default_preset(preset):
            continue

        helix_preset = preset_index_to_helix(
            preset_index
        )

        if helix_preset not in gain_deltas:
            continue

        tone = preset.get("tone", {})
        snapshot_gain_deltas = gain_deltas[helix_preset]

        # -----------------------------------------
        # find exactly one active output block
        # -----------------------------------------

        selected_output = find_gain_output(preset)

        if selected_output is None:
            print(
                f"[GAIN] {helix_preset}: "
                f"no active output block found"
            )
            continue

        dsp_name, output_name, output_block = selected_output

        normalize_adjusted_output_to_xlr(
            preset_index,
            preset,
            dsp_name,
            output_name,
            output_block
        )

        base_gain = float(
            output_block["gain"]
        )

        # -----------------------------------------
        # ensure snapshot controller exists
        # -----------------------------------------

        controller_root = tone.setdefault(
            "controller",
            {}
        )

        dsp_controller = controller_root.setdefault(
            dsp_name,
            {}
        )

        output_controller = dsp_controller.setdefault(
            output_name,
            {}
        )

        if "gain" not in output_controller:

            output_controller["gain"] = {
                "@controller": 19,
                "@max": 20.0,
                "@min": -120.0,
                "@snapshot_disable": False
            }

        # -----------------------------------------
        # process first 4 view snapshots only
        # -----------------------------------------

        for snapshot_index in range(4):

            snapshot_key = f"snapshot{snapshot_index}"
            snapshot = tone.get(snapshot_key)

            if not isinstance(snapshot, dict):
                continue

            if snapshot_index not in snapshot_gain_deltas:
                continue

            snapshot_name = snapshot.get(
                "@name",
                f"Snapshot {snapshot_index + 1}"
            )

            is_solo = (
                "solo" in snapshot_name.lower()
            )

            is_clean = (
                "clean" in snapshot_name.lower()
            )

            gain_delta = snapshot_gain_deltas[
                snapshot_index
            ]

            if is_solo:
                gain_delta += SOLO_GAIN_BUMP

            if is_clean:
                gain_delta += CLEAN_GAIN_BUMP

            new_gain = round(
                base_gain + gain_delta,
                2
            )

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

                print(
                    f"[GAIN] {helix_preset} "
                    f"{snapshot_name}: "
                    f"skipping bad LUFS measurement "
                    f"({message})"
                )
                continue

            snapshot_controllers = snapshot.setdefault(
                "controllers",
                {}
            )

            dsp_snapshot = snapshot_controllers.setdefault(
                dsp_name,
                {}
            )

            output_snapshot = dsp_snapshot.setdefault(
                output_name,
                {}
            )

            output_snapshot["gain"] = {
                "@fs_enabled": False,
                "@value": new_gain
            }

            changes += 1

            marker = "".join(
                [
                    " (S)" if is_solo else "",
                    " (C)" if is_clean else ""
                ]
            )

            delta_text = f"Delta: {gain_delta:+.1f} dB"

            print(
                f"[GAIN] "
                f"{helix_preset} "
                f"{snapshot_name}{marker} | "
                f"{base_gain:.1f} dB -> "
                f"{new_gain:.1f} dB "
                f"({delta_text})"
            )

    return changes


# =================================================
# TEXTUAL CONVERSION
# =================================================

def output_label(value):
    name = OUTPUT_NAMES.get(value)

    if name is None:
        return f"unknown output (id {value})"

    return f"{name} (id {value})"


def warn_non_xlr_output_conversion(
    preset_index,
    preset,
    dsp_name,
    output_name,
    current_output
):
    print(
        "WARNING: "
        f"{preset_index_to_helix(preset_index)} "
        f"\"{get_preset_name(preset)}\" "
        f"{dsp_name}.{output_name} was "
        f"{output_label(current_output)}, not XLR; "
        "converting final output to USB 1/2 for reamping.",
        file=sys.stderr
    )


def normalize_adjusted_output_to_xlr(
    preset_index,
    preset,
    dsp_name,
    output_name,
    output_block
):
    current_output = output_block.get("@output")

    if current_output == OUTPUT_XLR:
        return 0

    output_block["@output"] = OUTPUT_XLR

    print(
        f"[OUTPUT] "
        f"{preset_index_to_helix(preset_index)} "
        f"\"{get_preset_name(preset)}\" "
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

                if mode == "reamp" and current_input == INPUT_MULTI:
                    input_block["@input"] = INPUT_USB_3_4
                    input_changes += 1

                elif mode == "stage" and current_input == INPUT_USB_3_4:
                    input_block["@input"] = INPUT_MULTI
                    input_changes += 1

        for dsp_name, output_name, output_block in (
            get_final_output_blocks(preset)
        ):
            current_output = output_block.get("@output")

            if mode == "reamp":
                if current_output == OUTPUT_USB_1_2:
                    continue

                if current_output != OUTPUT_XLR:
                    warn_non_xlr_output_conversion(
                        preset_index,
                        preset,
                        dsp_name,
                        output_name,
                        current_output
                    )

                output_block["@output"] = OUTPUT_USB_1_2
                output_changes += 1

            elif mode == "stage":
                if current_output == OUTPUT_USB_1_2:
                    output_block["@output"] = OUTPUT_XLR
                    output_changes += 1

    return (
        json.dumps(
            data,
            indent=1
        ),
        input_changes,
        output_changes
    )


# =================================================
# PROCESS JSON STRUCTURE
# =================================================

def process_json_structure(
    json_text,
    gain_deltas=None,
    assign_output_gain=False,
    ignore_bad_lufs=False
):

    data = json.loads(json_text)

    snapshot_changes = 0

    if assign_output_gain:
        validate_controller_assignment_capacity(
            data,
            gain_deltas
        )

        snapshot_changes = assign_snapshot_level(data)

    gain_changes = 0

    if gain_deltas is not None:

        gain_changes = adjust_snapshot_gains(
            data,
            gain_deltas,
            ignore_bad_lufs
        )

    modified_json_text = json.dumps(
        data,
        indent=1
    )

    return (
        modified_json_text,
        snapshot_changes,
        gain_changes
    )


# =================================================
# BUILD HLS
# =================================================

def build_hls_text(
    original_hls_text,
    modified_json_text
):

    raw = modified_json_text.encode("utf-8")

    compressed = zlib.compress(raw, level=9)

    encoded_data = base64.b64encode(
        compressed
    ).decode("ascii")

    decompressed_size = len(raw)

    crc32 = (
        binascii.crc32(raw)
        & 0xffffffff
    )

    result = original_hls_text

    result = re.sub(
        r'("encoded_data"\s*:\s*")([^"]*)(")',
        rf'\g<1>{encoded_data}\g<3>',
        result,
        flags=re.DOTALL
    )

    result = re.sub(
        r'("decompressed_size"\s*:\s*)(\d+)',
        rf'\g<1>{decompressed_size}',
        result
    )

    result = re.sub(
        r'("crc32"\s*:\s*)(\d+)',
        rf'\g<1>{crc32}',
        result
    )

    return result


# =================================================
# LOAD INPUT
# =================================================

def load_input(filename):

    filetype = get_filetype(filename)

    if filetype == "hls":

        json_text, original_hls_text = (
            decode_hls_file(filename)
        )

        return (
            json_text,
            original_hls_text
        )

    with open(
        filename,
        "r",
        encoding="utf-8"
    ) as f:

        json_text = f.read()

    return json_text, None


# =================================================
# SAVE OUTPUT
# =================================================

def save_output(
    modified_json_text,
    output_filename,
    original_hls_text=None
):

    filetype = get_filetype(
        output_filename
    )

    if filetype == "json":

        with open(
            output_filename,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(modified_json_text)

        return

    if original_hls_text is not None:

        rebuilt_hls = build_hls_text(
            original_hls_text,
            modified_json_text
        )

        with open(
            output_filename,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(rebuilt_hls)

        return

    raw = modified_json_text.encode(
        "utf-8"
    )

    compressed = zlib.compress(raw, level=9)

    wrapper = {
        "compression": {
            "crc32": (
                binascii.crc32(raw)
                & 0xffffffff
            ),
            "decompressed_size": len(raw),
            "type": "zlib"
        },
        "encoded_data": base64.b64encode(
            compressed
        ).decode("ascii")
    }

    with open(
        output_filename,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(wrapper, f)


# =================================================
# MAIN
# =================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Line 6 Helix "
            "HLS/JSON Utility"
        )
    )

    parser.add_argument(
        "-i",
        "--input",
        required=True,
        help="Input file (.hls or .json)"
    )

    parser.add_argument(
        "-o",
        "--output",
        help="Output file (.hls or .json)"
    )

    parser.add_argument(
        "-g",
        "--lufs-analysis-file",
        help="LUFS analysis CSV file"
    )

    parser.add_argument(
        "--ignore-bad-lufs",
        action="store_true",
        help=(
            "Skip implausible LUFS-derived gain values "
            "instead of aborting"
        )
    )

    mode_group = (
        parser.add_mutually_exclusive_group(
            required=True
        )
    )

    mode_group.add_argument(
        "-r",
        "--reamp",
        action="store_true",
        help=(
            "Convert "
            "Multi/XLR -> USB"
        )
    )

    mode_group.add_argument(
        "-s",
        "--stage",
        action="store_true",
        help=(
            "Convert "
            "USB -> Multi/XLR"
        )
    )

    mode_group.add_argument(
        "-a",
        "--adjust-gain",
        action="store_true",
        help=(
            "Adjust snapshot gains "
            "using gain CSV"
        )
    )

    mode_group.add_argument(
        "--list-presets",
        action="store_true",
        help=(
            "Print non-default preset "
            "ID/name assignments as JSON"
        )
    )

    args = parser.parse_args()

    try:

        json_text, original_hls_text = (
            load_input(args.input)
        )

        if args.list_presets:

            data = json.loads(json_text)
            assignments = extract_preset_assignments(
                data
            )

            json.dump(
                assignments,
                sys.stdout,
                indent=2,
                ensure_ascii=False
            )

            print()

            return

        if not args.output:

            raise ValueError(
                "Output file is required "
                "unless --list-presets is used"
            )

        mode = (
            "reamp"
            if args.reamp
            else "stage"
            if args.stage
            else "adjust-gain"
        )

        modified_json_text = json_text
        input_changes = 0
        output_changes = 0

        if args.reamp or args.stage:
            (
                modified_json_text,
                input_changes,
                output_changes
            ) = convert_json_text(
                json_text,
                mode
            )

        gain_deltas = None

        if args.adjust_gain:

            if not args.lufs_analysis_file:

                raise ValueError(
                    "Adjust gain mode "
                    "requires -g lufs_analysis.csv"
                )

            gain_deltas = load_lufs_analysis_file(
                args.lufs_analysis_file
            )

        (
            modified_json_text,
            snapshot_changes,
            gain_changes
        ) = process_json_structure(
            modified_json_text,
            gain_deltas,
            args.reamp or args.stage or args.adjust_gain,
            args.ignore_bad_lufs
        )

        save_output(
            modified_json_text,
            args.output,
            original_hls_text
        )

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

    print(
        f"Input replacements : "
        f"{input_changes}"
    )

    print(
        f"Output replacements: "
        f"{output_changes}"
    )

    print(
        f"Snapshot assignments: "
        f"{snapshot_changes}"
    )

    print(
        f"Gain adjustments    : "
        f"{gain_changes}"
    )

    print()


if __name__ == "__main__":
    main()
