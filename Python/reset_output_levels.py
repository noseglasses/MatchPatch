#!/usr/bin/env python3

import argparse
import json
import sys

from preset_handling import (
    get_preset_name,
    is_default_preset,
    load_input,
    output_label,
    preset_index_to_helix,
    require_compatible_output_path,
    require_helix_input_path,
    save_output,
)

INACTIVE_OUTPUTS = {0, 2, 3}

OUTPUT_BLOCKS = ["outputA", "outputB"]


def is_active_output(block):
    if not isinstance(block, dict):
        return False

    output_id = block.get("@output", 0)

    return output_id not in INACTIVE_OUTPUTS


def set_gain_to_zero(container):
    if not isinstance(container, dict):
        return False

    if "gain" not in container:
        return False

    gain = container["gain"]

    if isinstance(gain, dict):
        if gain.get("@value") == 0.0:
            return False

        gain["@value"] = 0.0
        return True

    if gain == 0.0:
        return False

    container["gain"] = 0.0
    return True


def reset_snapshot_output_gains(tone, dsp_name, output_name):
    changes = 0

    for snapshot_index in range(8):
        snapshot = tone.get(f"snapshot{snapshot_index}")

        if not isinstance(snapshot, dict):
            continue

        controllers = snapshot.get("controllers", {})

        if not isinstance(controllers, dict):
            continue

        dsp_snapshot = controllers.get(dsp_name, {})

        if not isinstance(dsp_snapshot, dict):
            continue

        output_snapshot = dsp_snapshot.get(output_name, {})

        if set_gain_to_zero(output_snapshot):
            changes += 1

    return changes


def reset_output_levels(data):
    base_changes = 0
    snapshot_changes = 0

    for preset_index, preset in enumerate(data.get("presets", [])):
        tone = _resettable_tone(preset)
        if tone is None:
            continue
        preset_changes = []
        for output in _iter_active_outputs(tone):
            changed, snapshot_count, change = _reset_output_level(tone, output)
            base_changes += 1 if changed else 0
            snapshot_changes += snapshot_count
            if change is not None:
                preset_changes.append(change)

        if preset_changes:
            _log_output_level_changes(preset_index, preset, preset_changes)

    return base_changes, snapshot_changes


def _resettable_tone(preset):
    if is_default_preset(preset):
        return None
    tone = preset.get("tone", {})
    return tone if isinstance(tone, dict) else None


def _iter_active_outputs(tone):
    for dsp_name in ["dsp0", "dsp1"]:
        dsp = tone.get(dsp_name)
        if not isinstance(dsp, dict):
            continue
        for output_name in OUTPUT_BLOCKS:
            output_block = dsp.get(output_name)
            if is_active_output(output_block):
                yield dsp_name, output_name, output_block


def _reset_output_level(tone, output):
    dsp_name, output_name, output_block = output
    output_id = output_block.get("@output")
    old_gain = output_block.get("gain")
    changed = set_gain_to_zero(output_block)
    snapshot_count = reset_snapshot_output_gains(tone, dsp_name, output_name)
    change = None
    if changed or snapshot_count:
        change = (dsp_name, output_name, output_id, old_gain, snapshot_count)
    return changed, snapshot_count, change


def _log_output_level_changes(preset_index, preset, preset_changes):
    mappings = ", ".join(_output_level_change_text(change) for change in preset_changes)
    print(f'[OUTPUT] {preset_index_to_helix(preset_index)} "{get_preset_name(preset)}": {mappings}')


def _output_level_change_text(change):
    dsp_name, output_name, output_id, old_gain, snapshot_count = change
    return f"{dsp_name}.{output_name} {output_label(output_id)}: {old_gain} dB -> 0.0 dB" + (
        f", {snapshot_count} snapshot values" if snapshot_count else ""
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Set active Helix output block levels and snapshot-assigned output levels to 0 dB"
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

        base_changes, snapshot_changes = reset_output_levels(data)

        modified_json_text = json.dumps(data, indent=1)

        save_output(modified_json_text, args.output, original_hls_text)

    except Exception as e:
        print()
        print(f"ERROR: {e}")
        print()
        sys.exit(1)

    print()
    print("[OK] Output levels reset")
    print(f"Input             : {args.input}")
    print(f"Output            : {args.output}")
    print(f"Base gains changed: {base_changes}")
    print(f"Snapshot gains    : {snapshot_changes}")
    print()


if __name__ == "__main__":
    main()
