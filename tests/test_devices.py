from __future__ import annotations

import sys
from pathlib import Path

import pytest

from matchpatch import file_operations
from matchpatch.devices import get_device_profile, registry
from matchpatch.devices.base import (
    AudioRouting,
    DeviceController,
    DeviceProfile,
    DeviceTargetId,
    FileOperationCapabilities,
    GainAdjustment,
    GainPoint,
    MeasurementBackendCapabilities,
    MeasurementSubdivision,
    MeasurementTarget,
    NamingRules,
    PatchAssignment,
    PatchFileHandler,
    SteeringOptions,
    SubdivisionSelection,
    TargetSelection,
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


def test_helix_profile_name_rules_match_legacy_gui_helpers() -> None:
    profile = get_device_profile("helix")

    assert profile.validate_preset_name("Clean + Lead") == "Clean + Lead"
    assert profile.sanitize_preset_name("Bad*Name🙂") == "BadName"
    with pytest.raises(ValueError, match="Invalid Helix name"):
        profile.validate_preset_name("Bad*Name")
    with pytest.raises(ValueError, match="exceeds 10 characters"):
        profile.validate_subdivision_name("Very Long Snapshot")


def test_helix_setting_descriptors_match_current_defaults() -> None:
    profile = get_device_profile("helix")
    descriptors = {descriptor.name: descriptor for descriptor in profile.setting_descriptors()}

    assert set(descriptors) == {
        "audio_device",
        "sample_rate",
        "input_mapping",
        "output_mapping",
        "blocksize",
        "midi_output",
        "midi_channel",
        "preset_wait",
        "snapshot_wait",
        "measurement_wait",
    }
    assert descriptors["audio_device"].default == "Helix"
    assert descriptors["audio_device"].config_path == ("devices", "helix", "audio", "device")
    assert descriptors["audio_device"].cli_flags == ("--audio-device",)
    assert descriptors["sample_rate"].default == 48000
    assert descriptors["sample_rate"].kind == "integer"
    assert descriptors["input_mapping"].default == (1, 2)
    assert descriptors["input_mapping"].kind == "channel_mapping"
    assert descriptors["output_mapping"].default == (3, 4)
    assert descriptors["blocksize"].default == 0
    assert descriptors["blocksize"].minimum == 0
    assert descriptors["midi_output"].default == "Helix"
    assert descriptors["midi_output"].cli_flags == ("--steering-output", "--midi-output")
    assert descriptors["midi_channel"].default == 0
    assert descriptors["midi_channel"].minimum == 0
    assert descriptors["midi_channel"].maximum == 15
    assert descriptors["preset_wait"].default == 0.5
    assert descriptors["snapshot_wait"].default == 0.2
    assert descriptors["measurement_wait"].default == 0.1

    profile.validate_settings(
        {name: descriptor.default for name, descriptor in descriptors.items()}
    )


def test_device_setting_validation_rejects_wrong_kind_and_range() -> None:
    profile = get_device_profile("helix")

    with pytest.raises(ValueError, match="sample_rate must be an integer"):
        profile.validate_settings({"sample_rate": "48000"})

    with pytest.raises(ValueError, match="midi_channel must not exceed 15"):
        profile.validate_settings({"midi_channel": 16})

    with pytest.raises(ValueError, match="blocksize must be at least 0"):
        profile.validate_settings({"blocksize": -1})

    with pytest.raises(ValueError, match="input_mapping channels must be at least 1"):
        profile.validate_settings({"input_mapping": (0, 2)})


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


class AssignmentBackedHandler(MinimalHandler):
    def list_assignments(self, input_path: Path):
        return [
            PatchAssignment(
                1,
                "01A",
                "Clean",
                snapshot_names=("Rhythm", "Solo"),
                original_filename="Clean.hlx",
            ),
            PatchAssignment(6, "02B", "Lead"),
        ]

    def parse_patch_set(self, value: str) -> list[int]:
        if value == "01A,02B":
            return [1, 6]
        return [int(value)]

    def diff_preset_ids(self, input_path: Path, previous_input_path: Path) -> list[int]:
        return [6]

    def diff_snapshot_ids(
        self,
        input_path: Path,
        previous_input_path: Path,
        snapshot_count: int,
    ) -> dict[int, tuple[int, ...]]:
        return {1: (2,), 6: (1,)}


class StringTargetHandler(MinimalHandler):
    def list_targets(self, input_path: Path) -> list[MeasurementTarget]:
        return [
            MeasurementTarget(
                id="scene:clean",
                display_label="Clean Scene",
                index=0,
                name="Clean",
                source_filename="bank.scene",
                compat_numeric_id=None,
            )
        ]

    def parse_target_set(self, value: str) -> list[DeviceTargetId]:
        return [token.strip() for token in value.split(",") if token.strip()]


class MultiOutputHandler(MinimalHandler):
    def __init__(self) -> None:
        self.gain_adjustments: list[GainAdjustment] = []

    def list_targets(self, input_path: Path) -> list[MeasurementTarget]:
        return [
            MeasurementTarget(
                id="preset:clean",
                display_label="Clean",
                index=0,
                name="Clean",
                subdivisions=(
                    MeasurementSubdivision(
                        id="snap:intro",
                        display_label="Intro",
                        index=0,
                        name="Intro",
                        gain_points=(
                            GainPoint("main", "Main Out", -3.0, -60.0, 12.0, "subdivision"),
                            GainPoint("aux", "Aux Out", -6.0, -60.0, 12.0, "subdivision"),
                        ),
                    ),
                ),
            )
        ]

    def apply_gain_adjustments(
        self,
        input_path: Path,
        output_path: Path,
        adjustments: list[GainAdjustment],
    ) -> None:
        self.gain_adjustments.extend(adjustments)


class FileOperationsHandler(MinimalHandler):
    def __init__(self) -> None:
        self.join_calls = []
        self.split_calls = []
        self.log_callback = None

    def set_log_callback(self, callback) -> None:
        self.log_callback = callback

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


class PermissiveNamingProfile(PluginProfile):
    name = "permissive-names"
    display_name = "Permissive Names"


class RestrictiveNamingProfile(PluginProfile):
    name = "restrictive-names"
    display_name = "Restrictive Names"

    def naming_rules(self) -> NamingRules:
        return NamingRules(
            preset_name_max_length=8,
            snapshot_name_max_length=4,
            allowed_name_pattern=r"^[A-Z0-9 ]*$",
            replacement_character="-",
            trim_whitespace=True,
            forbidden_names=frozenset({"BYPASS"}),
        )


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
    descriptors = {descriptor.name: descriptor for descriptor in profile.setting_descriptors()}

    assert profile.terminology().preset == "preset"
    assert profile.file_capabilities().reads_preset_files is False
    assert profile.measurement_backends() == ("hardware", "loopback", "simulated")
    assert profile.naming_rules().preset_name_max_length is None
    assert descriptors["audio_device"].default is None
    assert descriptors["sample_rate"].default == 48000
    assert descriptors["input_mapping"].default == (1, 2)
    assert descriptors["output_mapping"].default == (1, 2)
    assert descriptors["midi_output"].default is None
    assert descriptors["midi_channel"].default == 0
    profile.validate_settings({})
    profile.validate_settings({"unknown_plugin_setting": object()})
    assert handler.file_capabilities().reads_setlist_files is False
    assert handler.file_kind(Path("anything")) == "unknown"


def test_permissive_device_name_rules_allow_long_names() -> None:
    profile = PermissiveNamingProfile()
    name = "Wide preset name with * and emoji 🙂"

    assert profile.validate_preset_name(name) == name
    assert profile.sanitize_subdivision_name(name) == name


def test_restrictive_device_name_rules_validate_and_sanitize() -> None:
    profile = RestrictiveNamingProfile()

    assert profile.validate_preset_name(" LEAD 1 ") == "LEAD 1"
    assert profile.sanitize_preset_name("lead*123456") == "-----123"
    assert profile.sanitize_subdivision_name("A*B123") == "A-B1"
    with pytest.raises(ValueError, match="Invalid Restrictive Names name"):
        profile.validate_preset_name("lead")
    with pytest.raises(ValueError, match="exceeds 8 characters"):
        profile.validate_preset_name("TOO LONG NAME")
    with pytest.raises(ValueError, match="Forbidden Restrictive Names name"):
        profile.validate_preset_name("BYPASS")


def test_default_target_api_adapts_legacy_assignments() -> None:
    handler = AssignmentBackedHandler()

    targets = handler.list_targets(Path("set.hls"))

    assert handler.parse_target_set("01A,02B") == [1, 6]
    assert [target.id for target in targets] == [1, 6]
    assert [target.display_label for target in targets] == ["01A", "02B"]
    assert [target.compat_numeric_id for target in targets] == [1, 6]
    assert targets[0].index == 0
    assert targets[0].source_filename == "Clean.hlx"
    assert [
        (subdivision.id, subdivision.display_label, subdivision.index)
        for subdivision in targets[0].subdivisions
    ] == [
        (1, "Rhythm", 0),
        (2, "Solo", 1),
    ]


def test_generic_gain_points_can_be_listed_and_adjusted_for_multi_output_device() -> None:
    handler = MultiOutputHandler()

    points = handler.list_gain_points(Path("bank.fake"), "preset:clean", "snap:intro")
    adjustments = [
        GainAdjustment("preset:clean", "snap:intro", points[0].id, 1.5),
        GainAdjustment("preset:clean", "snap:intro", points[1].id, -2.0),
    ]

    handler.apply_gain_adjustments(Path("bank.fake"), Path("out.fake"), adjustments)

    assert [(point.id, point.current_db) for point in points] == [("main", -3.0), ("aux", -6.0)]
    assert handler.gain_adjustments == adjustments


def test_default_gain_adjustment_api_reports_unsupported_for_read_only_devices() -> None:
    handler = MinimalHandler()

    assert handler.list_gain_points(Path("readonly.fake")) == []
    with pytest.raises(NotImplementedError, match="Gain adjustments are not supported"):
        handler.apply_gain_adjustments(
            Path("readonly.fake"),
            Path("out.fake"),
            [GainAdjustment(1, 1, "main", 1.0)],
        )


def test_target_api_accepts_string_ids_without_numeric_compatibility() -> None:
    handler = StringTargetHandler()

    targets = handler.list_targets(Path("bank.scene"))

    assert handler.parse_target_set("scene:clean, scene:lead") == ["scene:clean", "scene:lead"]
    assert targets == [
        MeasurementTarget(
            id="scene:clean",
            display_label="Clean Scene",
            index=0,
            name="Clean",
            source_filename="bank.scene",
            compat_numeric_id=None,
        )
    ]


def test_diff_target_api_defaults_adapt_legacy_numeric_diff() -> None:
    handler = AssignmentBackedHandler()

    assert handler.diff_targets(Path("current.hls"), Path("previous.hls")) == [
        TargetSelection(
            id=6,
            display_label="02B",
            index=1,
            name="Lead",
            compat_numeric_id=6,
        )
    ]
    assert handler.diff_subdivisions(Path("current.hls"), Path("previous.hls"), 4) == {
        1: (
            SubdivisionSelection(
                target_id=1,
                id=2,
                display_label="Solo",
                index=1,
                name="Solo",
                compat_numeric_id=2,
            ),
        ),
        6: (
            SubdivisionSelection(
                target_id=6,
                id=1,
                display_label="1",
                index=0,
                compat_numeric_id=1,
            ),
        ),
    }


def test_string_target_diff_api_can_report_changed_subdivisions() -> None:
    class DiffStringTargetHandler(StringTargetHandler):
        def list_targets(self, input_path: Path) -> list[MeasurementTarget]:
            return [
                MeasurementTarget(
                    id="scene:clean",
                    display_label="Clean Scene",
                    index=0,
                    name="Clean",
                    subdivisions=(
                        MeasurementSubdivision("snapshot:rhythm", "Rhythm", 0, "Rhythm"),
                        MeasurementSubdivision("snapshot:solo", "Solo", 1, "Solo"),
                    ),
                )
            ]

        def diff_targets(
            self,
            input_path: Path,
            previous_input_path: Path,
        ) -> list[TargetSelection]:
            return [TargetSelection(id="scene:clean", display_label="Clean Scene", index=0)]

        def diff_subdivisions(
            self,
            input_path: Path,
            previous_input_path: Path,
            subdivision_count: int,
        ) -> dict[DeviceTargetId, tuple[SubdivisionSelection, ...]]:
            return {
                "scene:clean": (
                    SubdivisionSelection(
                        target_id="scene:clean",
                        id="snapshot:solo",
                        display_label="Solo",
                        index=1,
                    ),
                )
            }

    handler = DiffStringTargetHandler()

    assert handler.diff_targets(Path("current.scene"), Path("previous.scene")) == [
        TargetSelection(id="scene:clean", display_label="Clean Scene", index=0)
    ]
    assert handler.diff_subdivisions(Path("current.scene"), Path("previous.scene"), 2) == {
        "scene:clean": (
            SubdivisionSelection(
                target_id="scene:clean",
                id="snapshot:solo",
                display_label="Solo",
                index=1,
            ),
        )
    }


def test_file_operations_join_validates_capabilities_and_delegates(tmp_path) -> None:
    handler = FileOperationsHandler()
    messages = []
    log_callback = messages.append

    result = file_operations.join_preset_files(
        "files-device",
        [tmp_path / "one.preset"],
        tmp_path / "joined.setlist",
        slot_ids=[1],
        log_callback=log_callback,
        get_profile=lambda device: FileOperationsProfile(handler),
    )

    assert result.output_path == tmp_path / "joined.setlist"
    assert handler.log_callback is log_callback
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


def test_example_device_plugin_imports_and_defines_entry_point_contract() -> None:
    example_src = Path(__file__).resolve().parents[1] / "examples" / "device_plugin" / "src"
    sys.path.insert(0, str(example_src))
    try:
        from matchpatch_example_device import ExampleDeviceProfile
    finally:
        sys.path.remove(str(example_src))

    profile = ExampleDeviceProfile()
    handler = profile.create_patch_file_handler(Path("."))

    assert profile.name == "example-device"
    assert profile.display_name == "Example Device"
    assert profile.file_capabilities().reads_setlist_files
    assert handler.file_kind(Path("demo.examplebank")) == "setlist"
    assert handler.file_types()[0].name_filter() == "Example Device Banks (*.examplebank)"
    assert handler.parse_patch_set("1, 2") == [1, 2]
    assert handler.automation_output_path(Path("demo.examplebank"), "_measurement") == Path(
        "demo_measurement.examplebank"
    )
