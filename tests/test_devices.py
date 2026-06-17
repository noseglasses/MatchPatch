from __future__ import annotations

from pathlib import Path

import pytest

from matchpatch import file_operations
from matchpatch.devices import get_device_profile, registry
from matchpatch.devices.base import (
    AudioRouting,
    DeviceController,
    DeviceProfile,
    FileOperationCapabilities,
    MeasurementBackendCapabilities,
    PatchFileHandler,
    SteeringOptions,
    validate_snapshot_count,
)


def test_helix_profile_defines_processor_boundaries() -> None:
    profile = get_device_profile("helix")
    routing = profile.default_audio_routing()
    steering = profile.default_steering_options()
    handler = profile.create_patch_file_handler(Path("."))

    assert routing.input_mapping == (1, 2)
    assert routing.output_mapping == (3, 4)
    assert steering.output == "Helix"
    assert steering.snapshot_wait_seconds == 0.2
    assert steering.measurement_wait_seconds == 0.1
    assert profile.snapshot_count == 4
    assert profile.max_snapshot_count == 8
    assert profile.terminology().device == "Helix"
    assert profile.file_capabilities().reads_setlist_files
    assert profile.file_capabilities().reads_preset_files
    assert profile.file_capabilities().joins_presets_to_setlist
    assert profile.file_capabilities().splits_setlist_to_presets
    assert profile.file_capabilities().exports_selected_setlist_slots
    assert profile.measurement_backends() == ("hardware", "loopback", "simulated")
    assert profile.naming_rules().preset_name_max_length == 16
    assert profile.naming_rules().snapshot_name_max_length == 10
    assert handler.file_kind(Path("tone.hlx")) == "preset"
    assert handler.file_kind(Path("setlist.hls")) == "setlist"
    assert handler.parse_patch_set("01A,02B") == [1, 6]
    assert handler.format_patch_id(6) == "02B"
    assert profile.format_patch_id(7) == "02C"


def test_helix_profile_rejects_more_than_eight_snapshots() -> None:
    with pytest.raises(ValueError, match="must not exceed 8"):
        validate_snapshot_count(get_device_profile("helix"), 9)


def test_unknown_device_profile_lists_supported_devices() -> None:
    with pytest.raises(ValueError, match="Unsupported device 'unknown'.*helix"):
        get_device_profile("unknown")


class EmptyController(DeviceController):
    def activate_preset(self, preset_id: int) -> None:
        return None

    def reapply_snapshot(self, snapshot: int) -> None:
        return None


def test_base_controller_context_manager_returns_and_closes_cleanly() -> None:
    controller = EmptyController()

    assert controller.__enter__() is controller
    assert controller.__exit__(None, None, None) is None


class MinimalHandler(PatchFileHandler):
    def validate_input(self, input_path: Path) -> None:
        return None

    def validate_output(self, input_path: Path, output_path: Path) -> None:
        return None

    def list_assignments(self, input_path: Path):
        return []

    def parse_patch_set(self, value: str) -> list[int]:
        return []

    def select_preset_ids(self, input_path, assignments, requested_ids):
        return []

    def format_patch_id(self, preset_id: int) -> str:
        return str(preset_id)

    def create_measurement_file(self, input_path: Path, output_path: Path) -> None:
        return None

    def apply_analysis_csv(self, *args) -> None:
        return None

    def automation_output_path(self, input_path: Path, postfix: str) -> Path:
        return input_path


class FileOperationsHandler(MinimalHandler):
    def __init__(self) -> None:
        self.join_calls = []
        self.split_calls = []

    def file_capabilities(self) -> FileOperationCapabilities:
        return FileOperationCapabilities(
            joins_presets_to_setlist=True,
            splits_setlist_to_presets=True,
            exports_selected_setlist_slots=True,
        )

    def file_kind(self, path: Path):
        if path.suffix == ".preset":
            return "preset"
        if path.suffix == ".setlist":
            return "setlist"
        return "unknown"

    def join_preset_files(self, preset_paths, output_path, *, slot_ids=None) -> None:
        self.join_calls.append((preset_paths, output_path, slot_ids))

    def split_setlist_file(
        self,
        input_path,
        output_dir,
        *,
        selected_ids=None,
        original_filenames=None,
    ):
        self.split_calls.append((input_path, output_dir, selected_ids, original_filenames))
        return [output_dir / "one.preset"]


class PluginProfile(DeviceProfile):
    name = "plugin-device"
    display_name = "Plugin Device"

    def create_patch_file_handler(self, project_dir: Path) -> PatchFileHandler:
        return MinimalHandler()

    def default_audio_routing(self) -> AudioRouting:
        return AudioRouting(None, 48000, (1, 2), (1, 2))

    def default_steering_options(self) -> SteeringOptions:
        return SteeringOptions(None, 0, 0.0, 0.0, 0.0)

    def create_controller(self, options: SteeringOptions) -> DeviceController:
        return EmptyController()


class FileOperationsProfile(PluginProfile):
    name = "files-device"
    display_name = "Files Device"

    def __init__(self, handler: PatchFileHandler) -> None:
        self.handler = handler

    def create_patch_file_handler(self, project_dir: Path) -> PatchFileHandler:
        return self.handler


class OfflineOnlyProfile(PluginProfile):
    name = "offline-device"
    display_name = "Offline Device"

    def measurement_backends(self) -> tuple[str, ...]:
        return MeasurementBackendCapabilities(
            hardware=False,
            loopback=False,
            simulated=False,
            offline=True,
        ).names()


class EntryPoint:
    def __init__(self, name: str, value) -> None:
        self.name = name
        self.value = value

    def load(self):
        if isinstance(self.value, BaseException):
            raise self.value
        return self.value


class EntryPoints(list):
    def select(self, *, group: str):
        assert group == registry.ENTRY_POINT_GROUP
        return self


def test_default_device_capabilities_are_backward_compatible() -> None:
    profile = PluginProfile()
    handler = profile.create_patch_file_handler(Path("."))

    assert profile.terminology().preset == "preset"
    assert profile.file_capabilities().reads_preset_files is False
    assert profile.measurement_backends() == ("hardware", "loopback", "simulated")
    assert profile.naming_rules().preset_name_max_length is None
    assert handler.file_capabilities().reads_setlist_files is False
    assert handler.file_kind(Path("anything")) == "unknown"


def test_file_operations_join_validates_capabilities_and_delegates(tmp_path) -> None:
    handler = FileOperationsHandler()

    result = file_operations.join_preset_files(
        "files-device",
        [tmp_path / "one.preset"],
        tmp_path / "joined.setlist",
        slot_ids=[1],
        get_profile=lambda device: FileOperationsProfile(handler),
    )

    assert result.output_path == tmp_path / "joined.setlist"
    assert handler.join_calls == [([tmp_path / "one.preset"], tmp_path / "joined.setlist", [1])]

    with pytest.raises(ValueError, match="does not support joining"):
        file_operations.join_preset_files(
            "plugin-device",
            [tmp_path / "one.preset"],
            tmp_path / "joined.setlist",
            get_profile=lambda device: PluginProfile(),
        )


def test_file_operations_split_validates_capabilities_and_delegates(tmp_path) -> None:
    handler = FileOperationsHandler()

    result = file_operations.split_setlist_file(
        "files-device",
        tmp_path / "joined.setlist",
        tmp_path / "presets",
        selected_ids=[1],
        original_filenames={1: "one.preset"},
        get_profile=lambda device: FileOperationsProfile(handler),
    )

    assert result.created_paths == [tmp_path / "presets" / "one.preset"]
    assert handler.split_calls == [
        (tmp_path / "joined.setlist", tmp_path / "presets", [1], {1: "one.preset"})
    ]

    with pytest.raises(ValueError, match="does not support splitting"):
        file_operations.split_setlist_file(
            "plugin-device",
            tmp_path / "joined.setlist",
            tmp_path / "presets",
            get_profile=lambda device: PluginProfile(),
        )


def test_plugin_device_profiles_are_discovered(monkeypatch) -> None:
    monkeypatch.setattr(
        registry.metadata,
        "entry_points",
        lambda: EntryPoints([EntryPoint("plugin", PluginProfile)]),
    )

    assert get_device_profile("plugin-device").display_name == "Plugin Device"
    assert [profile.name for profile in registry.list_device_profiles()] == [
        "helix",
        "plugin-device",
    ]


def test_plugin_load_errors_are_reported_for_explicit_lookup(monkeypatch) -> None:
    monkeypatch.setattr(
        registry.metadata,
        "entry_points",
        lambda: EntryPoints([EntryPoint("broken", RuntimeError("boom"))]),
    )

    assert [profile.name for profile in registry.list_device_profiles()] == ["helix"]
    assert registry.plugin_load_errors() == {"broken": "boom"}
    with pytest.raises(ValueError, match="Device plugin load errors: broken: boom"):
        get_device_profile("missing")


def test_duplicate_plugin_device_names_are_reported(monkeypatch) -> None:
    class DuplicateProfile(PluginProfile):
        name = "helix"

    monkeypatch.setattr(
        registry.metadata,
        "entry_points",
        lambda: EntryPoints([EntryPoint("duplicate", DuplicateProfile())]),
    )

    assert registry.plugin_load_errors() == {"duplicate": "duplicate device profile name 'helix'"}
