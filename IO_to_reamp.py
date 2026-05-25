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
OUTPUT_USB_1_2 = 10

SOLO_GAIN_BUMP = 3.0


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

def assign_snapshot_level(data):

    """
    Adds:
        "level": "snapshot"

    to all output blocks if not already present.
    """

    changes = 0

    if not isinstance(data, dict):
        return changes

    presets = data.get("presets", [])

    for preset in presets:

        tone = preset.get("tone", {})

        for dsp_name in ["dsp0", "dsp1"]:

            dsp = tone.get(dsp_name)

            if not isinstance(dsp, dict):
                continue

            for output_name in ["outputA", "outputB"]:

                output_block = dsp.get(output_name)

                if not isinstance(output_block, dict):
                    continue

                if output_block.get("level") == "snapshot":
                    continue

                output_block["level"] = "snapshot"
                changes += 1

    return changes


# =================================================
# LOAD GAIN FILE
# =================================================

def load_gain_file(filename):

    gain_data = {}

    with open(
        filename,
        "r",
        encoding="utf-8-sig"
    ) as f:

        reader = csv.DictReader(f)

        for row in reader:

            helix_preset = row["HelixPreset"].strip()

            snapshots = {}

            for i in range(1, 5):

                gain_key = f"Gain{i}"

                gain_value = 0.0
                solo_value = 0.0

                if row.get(gain_key):
                    gain_value = float(
                        row[gain_key]
                    )

                snapshots[i - 1] = {
                    "gain": gain_value
                }

            gain_data[helix_preset] = snapshots

    return gain_data


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


def adjust_snapshot_gains(data, gain_data):

    changes = 0

    presets = data.get("presets", [])

    for preset_index, preset in enumerate(presets):

        helix_preset = preset_index_to_helix(
            preset_index
        )

        if helix_preset not in gain_data:
            continue

        tone = preset.get("tone", {})
        snapshot_gain_info = gain_data[helix_preset]

        # -----------------------------------------
        # find exactly one active output block
        # -----------------------------------------

        selected_output = None

        for dsp_name in ["dsp0", "dsp1"]:

            dsp = tone.get(dsp_name)

            if not isinstance(dsp, dict):
                continue

            for output_name in ["outputA", "outputB"]:

                output_block = dsp.get(output_name)

                if not isinstance(output_block, dict):
                    continue

                # @output 0 means unused / none
                if output_block.get("@output", 0) == 0:
                    continue

                if "gain" not in output_block:
                    continue

                selected_output = (
                    dsp_name,
                    output_name,
                    output_block
                )

                break

            if selected_output is not None:
                break

        if selected_output is None:
            print(
                f"[GAIN] {helix_preset}: "
                f"no active output block found"
            )
            continue

        dsp_name, output_name, output_block = selected_output

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
                "@max": 12.0,
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

            if snapshot_index not in snapshot_gain_info:
                continue

            snapshot_name = snapshot.get(
                "@name",
                f"Snapshot {snapshot_index + 1}"
            )

            is_solo = (
                snapshot_name.strip().lower()
                == "solo"
            )

            gain_info = snapshot_gain_info[
                snapshot_index
            ]

            gain_delta = (
                gain_info["gain"] + SOLO_GAIN_BUMP
                if is_solo
                else gain_info["gain"]
            )

            new_gain = round(
                base_gain + gain_delta,
                2
            )

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

            solo_marker = " (S)" if is_solo else ""

            print(
                f"[GAIN] "
                f"{helix_preset} "
                f"{snapshot_name}{solo_marker} | "
                f"{base_gain:.1f} dB -> "
                f"{new_gain:.1f} dB "
                f"(Delta: {gain_delta:+.1f} dB)"
            )

    return changes


# =================================================
# TEXTUAL CONVERSION
# =================================================

def convert_json_text(text, mode):

    if mode == "reamp":

        text = re.sub(
            r'("@input"\s*:\s*)1(\s*[,}])',
            r'\g<1>14\2',
            text
        )

        text = re.sub(
            r'("@output"\s*:\s*)6(\s*[,}])',
            r'\g<1>10\2',
            text
        )

    else:

        text = re.sub(
            r'("@input"\s*:\s*)14(\s*[,}])',
            r'\g<1>1\2',
            text
        )

        text = re.sub(
            r'("@output"\s*:\s*)10(\s*[,}])',
            r'\g<1>6(\2',
            text
        )

    return text


# =================================================
# PROCESS JSON STRUCTURE
# =================================================

def process_json_structure(
    json_text,
    gain_data=None
):

    data = json.loads(json_text)

    snapshot_changes = assign_snapshot_level(data)

    gain_changes = 0

    if gain_data is not None:

        gain_changes = adjust_snapshot_gains(
            data,
            gain_data
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
        "--gain-file",
        help="Gain CSV file"
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

        if args.reamp or args.stage:

            modified_json_text = (
                convert_json_text(
                    json_text,
                    mode
                )
            )

        gain_data = None

        if args.adjust_gain:

            if not args.gain_file:

                raise ValueError(
                    "Adjust gain mode "
                    "requires -g gainfile.csv"
                )

            gain_data = load_gain_file(
                args.gain_file
            )

        (
            modified_json_text,
            snapshot_changes,
            gain_changes
        ) = process_json_structure(
            modified_json_text,
            gain_data
        )

        input_changes = 0
        output_changes = 0

        if args.reamp:

            input_changes = len(
                re.findall(
                    r'("@input"\s*:\s*)14(\s*[,}])',
                    modified_json_text
                )
            )

            output_changes = len(
                re.findall(
                    r'("@output"\s*:\s*)10(\s*[,}])',
                    modified_json_text
                )
            )

        elif args.stage:

            input_changes = len(
                re.findall(
                    r'("@input"\s*:\s*)1(\s*[,}])',
                    modified_json_text
                )
            )

            output_changes = len(
                re.findall(
                    r'("@output"\s*:\s*)6(\s*[,}])',
                    modified_json_text
                )
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

    if args.gain_file:

        print(f"GainCSV: {args.gain_file}")

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
