#!/usr/bin/env python3

import argparse
import json
import sys
from collections import defaultdict

from preset_handling import (
    get_preset_name,
    is_default_preset,
    load_input,
    preset_index_to_helix,
    require_compatible_output_path,
    require_helix_input_path,
    save_output,
)

CAB_BLOCK_TYPES = {2, 3, 4, 5}

DSP_HANDOFF_OUTPUT = 2

DEDICATED_STEREO_MODELS = {
    "GainMono": "GainStereo",
    "VolumePedalMono": "VolumePedalStereo",
    "PanMono": "PanStereo",
    "SendMono": "SendStereo",
    "ReturnMono": "ReturnStereo",
    "FXLoopMono": "FXLoopStereo",
    "1SwitchLooperMono": "1SwitchLooperStereo",
    "6SwitchLooperMono": "6SwitchLooperStereo",
    "mono_ir": "stereo_ir",
    "HD2_VolPanGainMono": "HD2_VolPanGainStereo",
    "HD2_VolPanVolMono": "HD2_VolPanVolStereo",
    "HD2_VolPanPanMono": "HD2_VolPanPanStereo",
    "HD2_SendMono1": "HD2_SendStereo1",
    "HD2_SendMono2": "HD2_SendStereo2",
    "HD2_SendMono3": "HD2_SendStereo3",
    "HD2_SendMono4": "HD2_SendStereo4",
    "HD2_ReturnMono1": "HD2_ReturnStereo1",
    "HD2_ReturnMono2": "HD2_ReturnStereo2",
    "HD2_ReturnMono3": "HD2_ReturnStereo3",
    "HD2_ReturnMono4": "HD2_ReturnStereo4",
    "HD2_FXLoopMono1": "HD2_FXLoopStereo1",
    "HD2_FXLoopMono2": "HD2_FXLoopStereo2",
    "HD2_FXLoopMono3": "HD2_FXLoopStereo3",
    "HD2_FXLoopMono4": "HD2_FXLoopStereo4",
    "HD2_ImpulseResponse1024Mono": "HD2_ImpulseResponse1024Stereo",
    "HD2_ImpulseResponse2048Mono": "HD2_ImpulseResponse2048Stereo",
}


def is_cab_or_ir_block(block):
    if not isinstance(block, dict):
        return False

    model = block.get("@model", "")

    return block.get("@type") in CAB_BLOCK_TYPES or (
        isinstance(model, str)
        and (model.startswith("HD2_Cab") or model.startswith("HD2_ImpulseResponse"))
    )


def is_dsp_chained(tone):
    dsp0 = tone.get("dsp0", {})

    if not isinstance(dsp0, dict):
        return False

    for output_name in ["outputA", "outputB"]:
        output_block = dsp0.get(output_name)

        if not isinstance(output_block, dict):
            continue

        if output_block.get("@output") == DSP_HANDOFF_OUTPUT:
            return True

    return False


def iter_blocks_by_path(dsp):
    blocks_by_path = defaultdict(list)

    if not isinstance(dsp, dict):
        return blocks_by_path

    for block_name, block in dsp.items():
        if not block_name.startswith("block"):
            continue

        if not isinstance(block, dict):
            continue

        path = block.get("@path", 0)
        position = block.get("@position", 0)
        blocks_by_path[path].append((position, block_name, block))

    for path in blocks_by_path:
        blocks_by_path[path].sort(key=lambda item: item[0])

    return blocks_by_path


def get_post_cab_blocks(tone):
    post_blocks = []
    chain_after_cab = False
    chained = is_dsp_chained(tone)

    for dsp_name in ["dsp0", "dsp1"]:
        dsp = tone.get(dsp_name, {})
        blocks_by_path = iter_blocks_by_path(dsp)
        dsp_has_cab = False

        for path, blocks in blocks_by_path.items():
            after_cab = chain_after_cab and dsp_name == "dsp1"

            for _, block_name, block in blocks:
                if is_cab_or_ir_block(block):
                    after_cab = True
                    dsp_has_cab = True
                    continue

                if after_cab:
                    post_blocks.append((dsp_name, path, block_name, block))

        if dsp_name == "dsp0" and chained and dsp_has_cab:
            chain_after_cab = True

    return post_blocks


def stereofy_block(block):
    model_key = "@model" if "@model" in block else "model" if "model" in block else None

    model = block.get(model_key, "") if model_key is not None else ""

    if "@stereo" in block:
        if block["@stereo"] is True:
            return "already", None

        block["@stereo"] = True
        return "changed", "@stereo False -> True"

    stereo_model = DEDICATED_STEREO_MODELS.get(model)

    if stereo_model is not None:
        block[model_key] = stereo_model
        return ("changed", f"{model} -> {stereo_model}")

    return ("unknown", "no @stereo parameter and no verified stereo model mapping")


def stereofy(data):
    changed_count = 0
    already_count = 0
    unknown_count = 0

    for preset_index, preset in enumerate(data.get("presets", [])):
        if is_default_preset(preset):
            continue

        tone = preset.get("tone", {})

        if not isinstance(tone, dict):
            continue

        changes = []
        already = []
        unknown = []

        for dsp_name, path, block_name, block in get_post_cab_blocks(tone):
            status, detail = stereofy_block(block)
            model = block.get("@model", "")
            location = f"{dsp_name}.{block_name}(path {path})"

            if status == "changed":
                changed_count += 1
                changes.append(f"{location}: {model} ({detail})")

            elif status == "already":
                already_count += 1
                already.append(f"{location}: {model}")

            else:
                unknown_count += 1
                unknown.append(f"{location}: {model} ({detail})")

        if changes:
            print(
                f"[STEREO] "
                f"{preset_index_to_helix(preset_index)} "
                f'"{get_preset_name(preset)}": ' + ", ".join(changes)
            )

        if unknown:
            print(
                f"[UNSURE] "
                f"{preset_index_to_helix(preset_index)} "
                f'"{get_preset_name(preset)}": ' + ", ".join(unknown)
            )

    return changed_count, already_count, unknown_count


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Turn blocks after cab or IR blocks stereo "
            "where the conversion can be identified safely"
        )
    )

    parser.add_argument("-i", "--input", required=True, help="Input .hls or .hlx file")

    parser.add_argument("-o", "--output", required=True, help="Output .hls or .hlx file to create")

    return parser.parse_args()


def main():
    args = parse_args()

    try:
        require_helix_input_path(args.input, "Input")
        require_compatible_output_path(args.input, args.output, allow_json=False)

        json_text, original_hls_text = load_input(args.input)
        data = json.loads(json_text)

        changed, already, unknown = stereofy(data)

        modified_json_text = json.dumps(data, indent=1)

        save_output(modified_json_text, args.output, original_hls_text)

    except Exception as e:
        print()
        print(f"ERROR: {e}")
        print()
        sys.exit(1)

    print()
    print("[OK] Stereofy complete")
    print(f"Input          : {args.input}")
    print(f"Output         : {args.output}")
    print(f"Changed blocks : {changed}")
    print(f"Already stereo : {already}")
    print(f"Unsure blocks  : {unknown}")
    print()


if __name__ == "__main__":
    main()
