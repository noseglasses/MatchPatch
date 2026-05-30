#!/usr/bin/env python3

import argparse
import json
import sys

from hls_adjust import (
    load_input,
    save_output,
    require_helix_input_path,
    require_compatible_output_path,
    preset_index_to_helix,
    get_preset_name,
    is_default_preset
)


DSP_NAMES = [
    "dsp0",
    "dsp1"
]

SNAPSHOT_COUNT = 4

PEDAL_CONTROLLERS = {
    1,
    2,
    3
}


def iter_effect_blocks(tone):
    if not isinstance(tone, dict):
        return

    for dsp_name in DSP_NAMES:
        dsp = tone.get(dsp_name)

        if not isinstance(dsp, dict):
            continue

        for block_name, block in list(dsp.items()):
            if not block_name.startswith("block"):
                continue

            if not isinstance(block, dict):
                continue

            yield dsp_name, block_name, block


def snapshot_block_state(tone, snapshot_index, dsp_name, block_name):
    snapshot = tone.get(f"snapshot{snapshot_index}")

    if not isinstance(snapshot, dict):
        return None

    snapshot_blocks = snapshot.get("blocks")

    if not isinstance(snapshot_blocks, dict):
        return None

    dsp_blocks = snapshot_blocks.get(dsp_name)

    if not isinstance(dsp_blocks, dict):
        return None

    return dsp_blocks.get(block_name)


def is_inactive_in_first_snapshots(tone, dsp_name, block_name):
    states = [
        snapshot_block_state(
            tone,
            snapshot_index,
            dsp_name,
            block_name
        )
        for snapshot_index in range(SNAPSHOT_COUNT)
    ]

    return all(state is False for state in states)


def get_block_controller_assignments(tone, dsp_name, block_name):
    controller_root = tone.get("controller")

    if not isinstance(controller_root, dict):
        return {}

    dsp_controller = controller_root.get(dsp_name)

    if not isinstance(dsp_controller, dict):
        return {}

    block_controller = dsp_controller.get(block_name)

    if not isinstance(block_controller, dict):
        return {}

    return block_controller


def get_pedal_assignments(tone, dsp_name, block_name):
    assignments = []
    block_controller = get_block_controller_assignments(
        tone,
        dsp_name,
        block_name
    )

    for parameter, assignment in block_controller.items():
        if not isinstance(assignment, dict):
            continue

        controller = assignment.get("@controller")

        if controller not in PEDAL_CONTROLLERS:
            continue

        assignments.append(
            (
                parameter,
                controller
            )
        )

    return assignments


def remove_block_references(tone, dsp_name, block_name):
    removed_references = 0

    controller_root = tone.get("controller")

    if isinstance(controller_root, dict):
        dsp_controller = controller_root.get(dsp_name)

        if (
            isinstance(dsp_controller, dict)
            and block_name in dsp_controller
        ):
            del dsp_controller[block_name]
            removed_references += 1

    for snapshot_index in range(8):
        snapshot = tone.get(f"snapshot{snapshot_index}")

        if not isinstance(snapshot, dict):
            continue

        snapshot_blocks = snapshot.get("blocks")

        if isinstance(snapshot_blocks, dict):
            dsp_blocks = snapshot_blocks.get(dsp_name)

            if (
                isinstance(dsp_blocks, dict)
                and block_name in dsp_blocks
            ):
                del dsp_blocks[block_name]
                removed_references += 1

        snapshot_controllers = snapshot.get("controllers")

        if isinstance(snapshot_controllers, dict):
            dsp_controllers = snapshot_controllers.get(dsp_name)

            if (
                isinstance(dsp_controllers, dict)
                and block_name in dsp_controllers
            ):
                del dsp_controllers[block_name]
                removed_references += 1

    return removed_references


def format_pedal_assignments(assignments):
    return ", ".join(
        f"{parameter}->EXP{controller}"
        for parameter, controller in assignments
    )


def remove_inactive_blocks(data):
    removed_blocks = 0
    removed_references = 0
    manual_blocks = 0
    affected_presets = 0

    for preset_index, preset in enumerate(
        data.get("presets", [])
    ):
        if is_default_preset(preset):
            continue

        tone = preset.get("tone", {})

        if not isinstance(tone, dict):
            continue

        removed = []
        manual = []

        for dsp_name, block_name, block in list(
            iter_effect_blocks(tone)
        ):
            if not is_inactive_in_first_snapshots(
                tone,
                dsp_name,
                block_name
            ):
                continue

            model = block.get("@model", "")
            block_type = block.get("@type")
            pedal_assignments = get_pedal_assignments(
                tone,
                dsp_name,
                block_name
            )

            if pedal_assignments:
                manual_blocks += 1
                manual.append(
                    (
                        dsp_name,
                        block_name,
                        model,
                        block_type,
                        pedal_assignments
                    )
                )
                continue

            dsp = tone.get(dsp_name)
            del dsp[block_name]
            removed_blocks += 1
            refs = remove_block_references(
                tone,
                dsp_name,
                block_name
            )
            removed_references += refs

            removed.append(
                (
                    dsp_name,
                    block_name,
                    model,
                    block_type,
                    refs
                )
            )

        if removed or manual:
            affected_presets += 1

        if removed:
            mappings = ", ".join(
                f"{dsp_name}.{block_name}: "
                f"{model} (type {block_type}, refs {refs})"
                for (
                    dsp_name,
                    block_name,
                    model,
                    block_type,
                    refs
                ) in removed
            )

            print(
                f"[REMOVED] "
                f"{preset_index_to_helix(preset_index)} "
                f"\"{get_preset_name(preset)}\": "
                f"{mappings}"
            )

        if manual:
            mappings = ", ".join(
                f"{dsp_name}.{block_name}: "
                f"{model} (type {block_type}, "
                f"{format_pedal_assignments(assignments)})"
                for (
                    dsp_name,
                    block_name,
                    model,
                    block_type,
                    assignments
                ) in manual
            )

            print(
                f"[MANUAL] "
                f"{preset_index_to_helix(preset_index)} "
                f"\"{get_preset_name(preset)}\": "
                f"inactive in snapshots 1-4 but pedal-bound; "
                f"please inspect manually: {mappings}"
            )

    return (
        affected_presets,
        removed_blocks,
        removed_references,
        manual_blocks
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Remove Helix blocks that are inactive in the first "
            "four snapshots, except blocks controlled by expression "
            "pedals such as wah/pitch effects"
        )
    )

    parser.add_argument(
        "-i",
        "--input",
        required=True,
        help="Input .hls or .hlx file"
    )

    parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Output .hls or .hlx file to create"
    )

    return parser.parse_args()


def main():
    args = parse_args()

    try:
        require_helix_input_path(args.input, "Input")
        require_compatible_output_path(
            args.input,
            args.output,
            allow_json=False
        )

        json_text, original_hls_text = load_input(args.input)
        data = json.loads(json_text)

        (
            affected_presets,
            removed_blocks,
            removed_references,
            manual_blocks
        ) = remove_inactive_blocks(data)

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
    print("[OK] Inactive block cleanup complete")
    print(f"Input             : {args.input}")
    print(f"Output            : {args.output}")
    print(f"Affected presets  : {affected_presets}")
    print(f"Removed blocks    : {removed_blocks}")
    print(f"Removed references: {removed_references}")
    print(f"Manual blocks     : {manual_blocks}")
    print()


if __name__ == "__main__":
    main()
