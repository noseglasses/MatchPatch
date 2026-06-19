"""Line 6 Pod Go profile: patch files, MIDI steering, and USB routing."""

from __future__ import annotations

from pathlib import Path

from matchpatch.devices.base import (
    DeviceController,
    DeviceFileType,
    PatchFileHandler,
    SteeringOptions,
)
from matchpatch.devices.line6.common import (
    Line6DeviceProfile,
    Line6MidiController,
    Line6PatchFileHandler,
)


class PodGoPatchFileHandler(Line6PatchFileHandler):
    display_name = "Pod Go"
    module = "matchpatch.devices.line6.podgo.preset_handling"
    preset_extension = ".pgp"
    setlist_extension = ".pgs"
    assignment_patch_key = "podgo_preset"

    def file_types(self) -> tuple[DeviceFileType, ...]:
        return (
            DeviceFileType(
                kind="setlist",
                extensions=(".pgs",),
                description="Pod Go .pgs",
                can_open=True,
                can_save=True,
            ),
            DeviceFileType(
                kind="preset",
                extensions=(".pgp",),
                description="Pod Go .pgp",
                can_open=True,
                can_save=True,
            ),
        )


class PodGoMidiController(Line6MidiController):
    display_name = "Pod Go"
    max_snapshot_count = 4


class PodGoDeviceProfile(Line6DeviceProfile):
    name = "podgo"
    display_name = "Line 6 Pod Go"
    device_label = "Pod Go"
    max_snapshot_count = 4
    preset_name_max_length = 16
    snapshot_name_max_length = 10
    audio_device_query = "POD Go"
    audio_sample_rate = 48000
    audio_input_mapping = (1, 2)
    audio_output_mapping = (3, 4)
    steering_output_query = "POD Go"
    steering_preset_wait_seconds = 0.5
    steering_snapshot_wait_seconds = 0.2
    steering_measurement_wait_seconds = 0.1

    def create_patch_file_handler(self, project_dir: Path) -> PatchFileHandler:
        return PodGoPatchFileHandler(project_dir)

    def create_controller(self, options: SteeringOptions) -> DeviceController:
        return PodGoMidiController(options)

    def default_ignore_preset_regex(self) -> str:
        return r"(?i)^New Preset$"
