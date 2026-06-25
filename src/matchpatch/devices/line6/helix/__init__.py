"""Line 6 Helix profile: patch files, MIDI steering, and USB routing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from matchpatch.devices.base import (
    AudioRouting,
    DeviceController,
    DeviceFileType,
    PatchFileHandler,
    SteeringOptions,
)
from matchpatch.devices.line6 import common as _common
from matchpatch.devices.line6 import file_ops
from matchpatch.devices.line6.common import (
    LINE6_NAME_CHAR_PATTERN,
    LINE6_NAME_PATTERN,
    Line6DeviceProfile,
    Line6MidiController,
    Line6PatchFileHandler,
)

HELIX_NAME_PATTERN = LINE6_NAME_PATTERN
HELIX_NAME_CHAR_PATTERN = LINE6_NAME_CHAR_PATTERN
runpy = _common.runpy
time = _common.time


class HelixPatchFileHandler(Line6PatchFileHandler):
    display_name = "Helix"
    module = "matchpatch.devices.helix.preset_handling"
    preset_extension = ".hlx"
    setlist_extension = ".hls"
    assignment_patch_key = "helix_preset"

    def file_types(self) -> tuple[DeviceFileType, ...]:
        return (
            DeviceFileType(
                kind="setlist",
                extensions=(".hls",),
                description="Helix .hls",
                can_open=True,
                can_save=True,
            ),
            DeviceFileType(
                kind="preset",
                extensions=(".hlx",),
                description="Helix .hlx",
                can_open=True,
                can_save=True,
            ),
        )

    def _file_operations(self):  # noqa: ANN202
        return _load_helix_file_operations()


class HelixMidiController(Line6MidiController):
    display_name = "Helix"
    max_snapshot_count = 8


class HelixDeviceProfile(Line6DeviceProfile):
    name = "helix"
    display_name = "Line 6 Helix"
    device_label = "Helix"
    max_snapshot_count = 8
    preset_name_max_length = 16
    snapshot_name_max_length = 10
    audio_device_query = "Helix"
    audio_sample_rate = 48000
    audio_input_mapping = (1, 2)
    audio_output_mapping = (3, 4)
    steering_output_query = "Helix"
    steering_preset_wait_seconds = 0.5
    steering_snapshot_wait_seconds = 0.2
    steering_measurement_wait_seconds = 0.1

    def create_patch_file_handler(self, project_dir: Path) -> PatchFileHandler:
        return HelixPatchFileHandler(project_dir)

    def create_controller(self, options: SteeringOptions) -> DeviceController:
        return HelixMidiController(options)

    def default_audio_routing(self) -> AudioRouting:
        return super().default_audio_routing()


def _load_helix_file_operations() -> Any:  # noqa: ANN401
    return file_ops
