#!/usr/bin/env python3

import argparse
import json
import os
import sys

from hls_adjust import (
    load_input,
    save_output,
    preset_index_to_helix,
    get_preset_name,
    is_default_preset
)


AMP_BLOCK_TYPE = 1
AMP_CAB_BLOCK_TYPE = 3


def require_hls_path(filename, label):
    ext = os.path.splitext(filename)[1].lower()

    if ext != ".hls":
        raise ValueError(
            f"{label} must be an .hls file: {filename}"
        )


def is_amp_cab_block(block):
    if not isinstance(block, dict):
        return False

    model = block.get("@model", "")

    return (
        isinstance(model, str)
        and model.startswith("HD2_Amp")
        and "@cab" in block
        and block.get("@type") == AMP_CAB_BLOCK_TYPE
    )


def replace_amp_cab_blocks(data):
    changes = 0

    for preset_index, preset in enumerate(
        data.get("presets", [])
    ):
        if is_default_preset(preset):
            continue

        preset_changes = []
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

                if not is_amp_cab_block(block):
                    continue

                model = block["@model"]
                old_cab = block.pop("@cab")
                block["@type"] = AMP_BLOCK_TYPE
                changes += 1

                preset_changes.append(
                    (
                        dsp_name,
                        block_name,
                        model,
                        old_cab
                    )
                )

        if preset_changes:
            mappings = ", ".join(
                f"{dsp_name}.{block_name}: "
                f"{model}+cab({old_cab}) -> {model}"
                for (
                    dsp_name,
                    block_name,
                    model,
                    old_cab
                ) in preset_changes
            )

            print(
                f"[AMP] "
                f"{preset_index_to_helix(preset_index)} "
                f"\"{get_preset_name(preset)}\": "
                f"{mappings}"
            )

    return changes


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Replace Helix amp+cab blocks with "
            "the equivalent amp-only blocks"
        )
    )

    parser.add_argument(
        "-i",
        "--input",
        required=True,
        help="Input .hls file"
    )

    parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Output .hls file to create"
    )

    return parser.parse_args()


def main():
    args = parse_args()

    try:
        require_hls_path(args.input, "Input")
        require_hls_path(args.output, "Output")

        json_text, original_hls_text = load_input(args.input)
        data = json.loads(json_text)

        changes = replace_amp_cab_blocks(data)

        modified_json_text = json.dumps(
            data,
            indent=1
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
    print("[OK] Amp+cab replacement complete")
    print(f"Input  : {args.input}")
    print(f"Output : {args.output}")
    print(f"Changes: {changes}")
    print()


if __name__ == "__main__":
    main()
