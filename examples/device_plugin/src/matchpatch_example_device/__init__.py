"""Minimal read-only MatchPatch device plugin example."""

from __future__ import annotations

from pathlib import Path

from matchpatch.devices.base import (
    AudioRouting,
    DeviceController,
    DeviceFileKind,
    DeviceFileType,
    DeviceProfile,
    DeviceSettingDescriptor,
    FileOperationCapabilities,
    NormalizationPolicy,
    PatchAssignment,
    PatchFileAdjustments,
    PatchFileHandler,
    SteeringOptions,
)


class ExampleController(DeviceController):
    def activate_preset(self, preset_id: int) -> None:
        raise NotImplementedError("Example device does not implement hardware steering")

    def reapply_snapshot(self, snapshot: int) -> None:
        raise NotImplementedError("Example device does not implement hardware steering")


class ExamplePatchFileHandler(PatchFileHandler):
    def validate_input(self, input_path: Path) -> None:
        if input_path.suffix.lower() != ".examplebank":
            raise ValueError("Example device inputs must use the .examplebank extension")

    def validate_output(self, input_path: Path, output_path: Path) -> None:
        if output_path.suffix.lower() != ".examplebank":
            raise ValueError("Example device outputs must use the .examplebank extension")

    def list_assignments(self, input_path: Path) -> list[PatchAssignment]:
        self.validate_input(input_path)
        return []

    def file_capabilities(self) -> FileOperationCapabilities:
        return FileOperationCapabilities(reads_setlist_files=True)

    def file_types(self) -> tuple[DeviceFileType, ...]:
        return (
            DeviceFileType(
                kind="setlist",
                extensions=(".examplebank",),
                description="Example Device Banks",
                can_save=False,
            ),
        )

    def file_kind(self, path: Path) -> DeviceFileKind:
        if path.suffix.lower() == ".examplebank":
            return "setlist"
        return "unknown"

    def parse_patch_set(self, value: str) -> list[int]:
        return [int(item.strip()) for item in value.split(",") if item.strip()]

    def select_preset_ids(
        self,
        input_path: Path,
        assignments: list[PatchAssignment],
        requested_ids: list[int] | None,
    ) -> list[int]:
        if requested_ids is not None:
            return requested_ids
        return [assignment.id for assignment in assignments]

    def format_patch_id(self, preset_id: int) -> str:
        return f"EX{preset_id:03d}"

    def create_measurement_file(self, input_path: Path, output_path: Path) -> None:
        raise NotImplementedError("Example device does not create measurement files")

    def apply_analysis_csv(
        self,
        input_path: Path,
        output_path: Path,
        csv_path: Path,
        ignore_bad_lufs: bool,
        target_lufs: float,
        policy: NormalizationPolicy,
        custom_adjustments_path: Path | None = None,
        adjustments: PatchFileAdjustments | None = None,
    ) -> None:
        raise NotImplementedError("Example device does not apply analysis CSVs")

    def automation_output_path(self, input_path: Path, postfix: str) -> Path:
        return input_path.with_name(f"{input_path.stem}{postfix}{input_path.suffix}")


class ExampleDeviceProfile(DeviceProfile):
    name = "example-device"
    display_name = "Example Device"

    def create_patch_file_handler(self, project_dir: Path) -> PatchFileHandler:
        return ExamplePatchFileHandler()

    def default_audio_routing(self) -> AudioRouting:
        return AudioRouting(None, 48000, (1, 2), (1, 2))

    def default_steering_options(self) -> SteeringOptions:
        return SteeringOptions(None, 0, 0.0, 0.0, 0.0)

    def create_controller(self, options: SteeringOptions) -> DeviceController:
        return ExampleController()

    def setting_descriptors(self) -> tuple[DeviceSettingDescriptor, ...]:
        audio = self.default_audio_routing()
        return (
            DeviceSettingDescriptor(
                name="audio_device",
                scope="audio",
                kind="string",
                default=audio.device,
                config_path=("devices", self.name, "audio", "device"),
                cli_flags=("--audio-device",),
                label="Audio device",
            ),
            DeviceSettingDescriptor(
                name="sample_rate",
                scope="audio",
                kind="integer",
                default=audio.sample_rate,
                config_path=("devices", self.name, "audio", "sample_rate"),
                cli_flags=("--sample-rate",),
                label="Sample rate",
                minimum=1,
            ),
        )

    def file_capabilities(self) -> FileOperationCapabilities:
        return FileOperationCapabilities(reads_setlist_files=True)


__all__ = ["ExampleDeviceProfile", "ExamplePatchFileHandler"]
