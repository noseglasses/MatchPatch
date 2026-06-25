from __future__ import annotations

import csv
from pathlib import Path

from matchpatch.devices.base import PatchAssignment


class FakeHandler:
    def __init__(self) -> None:
        self.applied = []
        self.measurement_files = []

    def validate_input(self, input_path: Path) -> None:
        return None

    def validate_output(self, input_path: Path, output_path: Path) -> None:
        return None

    def automation_output_path(self, input_path: Path, postfix: str) -> Path:
        return input_path.with_name(input_path.stem + postfix + input_path.suffix)

    def create_measurement_file(self, input_path: Path, output_path: Path) -> None:
        self.measurement_files.append((input_path, output_path))

    def parse_patch_set(self, value: str) -> list[int]:
        return [int(item) for item in value.split(",")]

    def list_assignments(self, input_path: Path) -> list[PatchAssignment]:
        return [PatchAssignment(1, "patch-1", "One"), PatchAssignment(2, "patch-2", "Two")]

    def diff_preset_ids(self, input_path: Path, previous_input_path: Path) -> list[int]:
        return [2]

    def select_preset_ids(self, input_path, assignments, requested_ids):
        return requested_ids if requested_ids is not None else [item.id for item in assignments]

    def format_patch_id(self, preset_id: int) -> str:
        return f"patch-{preset_id}"

    def apply_analysis_csv(self, *args) -> None:
        self.applied.append(args)


class FakeProfile:
    name = "fake"
    display_name = "Fake Processor"

    def __init__(self, handler: FakeHandler) -> None:
        self.handler = handler

    def create_patch_file_handler(self, project_dir: Path) -> FakeHandler:
        return self.handler

    def default_ignore_preset_regex(self) -> str:
        return ""


def write_analysis_csv(args, preset_ids, csv_path) -> None:
    with csv_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=["Preset", "DevicePatch"])
        writer.writeheader()
        for preset_id in preset_ids:
            writer.writerow({"Preset": preset_id, "DevicePatch": f"patch-{preset_id}"})
