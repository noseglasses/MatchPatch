#!/usr/bin/env python3

import argparse
import json
import os
import sys

from hls_adjust import (
    load_input,
    preset_index_to_helix,
    get_preset_name,
    is_default_preset
)


CAB_BLOCK_TYPES = {
    2,
    4
}


def require_hls_path(filename, label):
    ext = os.path.splitext(filename)[1].lower()

    if ext != ".hls":
        raise ValueError(
            f"{label} must be an .hls file: {filename}"
        )


def is_cab_block(block):
    if not isinstance(block, dict):
        return False

    model = block.get("@model", "")

    return (
        block.get("@type") in CAB_BLOCK_TYPES
        or (
            isinstance(model, str)
            and model.startswith("HD2_Cab")
        )
    )


def list_cab_presets(data):
    preset_count = 0
    block_count = 0

    for preset_index, preset in enumerate(
        data.get("presets", [])
    ):
        if is_default_preset(preset):
            continue

        cab_blocks = []
        tone = preset.get("tone", {})

        if not isinstance(tone, dict):
            continue

        for dsp_name in ["dsp0", "dsp1"]:
            dsp = tone.get(dsp_name)

            if not isinstance(dsp, dict):
                continue

            for block_name, block in dsp.items():
                if not block_name.startswith("block"):
                    continue

                if not is_cab_block(block):
                    continue

                cab_blocks.append(
                    (
                        dsp_name,
                        block_name,
                        block.get("@model", ""),
                        block.get("@type")
                    )
                )

        if not cab_blocks:
            continue

        preset_count += 1
        block_count += len(cab_blocks)

        mappings = ", ".join(
            f"{dsp_name}.{block_name}: "
            f"{model} (type {block_type})"
            for (
                dsp_name,
                block_name,
                model,
                block_type
            ) in cab_blocks
        )

        print(
            f"[CAB] "
            f"{preset_index_to_helix(preset_index)} "
            f"\"{get_preset_name(preset)}\": "
            f"{mappings}"
        )

    return preset_count, block_count


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "List Helix presets that use isolated cab blocks"
        )
    )

    parser.add_argument(
        "-i",
        "--input",
        required=True,
        help="Input .hls file"
    )

    return parser.parse_args()


def main():
    args = parse_args()

    try:
        require_hls_path(args.input, "Input")

        json_text, _ = load_input(args.input)
        data = json.loads(json_text)

        preset_count, block_count = list_cab_presets(data)

    except Exception as e:
        print()
        print(f"ERROR: {e}")
        print()
        sys.exit(1)

    print()
    print("[OK] Cab scan complete")
    print(f"Input  : {args.input}")
    print(f"Presets: {preset_count}")
    print(f"Blocks : {block_count}")
    print()


if __name__ == "__main__":
    main()
