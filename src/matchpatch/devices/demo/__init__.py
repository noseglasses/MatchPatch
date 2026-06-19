"""Demo MatchPatch device implementation and copyable device template.

This module is intentionally small, deterministic, and offline. The classes
demonstrate the MatchPatch device API; the ``.demobank`` JSON format is fake
demo behavior, not a format recommendation for real devices.

When adding a real device, copying this file is a reasonable starting point:

* replace the fake ``.demobank`` JSON parsing with the device's real file format;
* replace ``DemoController`` with MIDI, USB, network, or SDK steering code;
* keep the public method shapes the same so MatchPatch can call the device
  through the shared ``DeviceProfile`` and ``PatchFileHandler`` APIs.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from matchpatch.devices.base import (
    AudioRouting,
    DeviceController,
    DeviceFileKind,
    DeviceFileType,
    DeviceProfile,
    DeviceSettingDescriptor,
    FileOperationCapabilities,
    GainAdjustment,
    GainPoint,
    MeasurementSubdivision,
    MeasurementTarget,
    NormalizationPolicy,
    PatchAssignment,
    PatchFileAdjustments,
    PatchFileHandler,
    SteeringOptions,
)

# Demo-only file extension. Real devices should use their vendor file
# extensions, such as ``.hls``/``.hlx`` for Helix.
DEMO_EXTENSION = ".demobank"

# Stable gain-point ids let MatchPatch tell the file handler exactly which
# control to adjust after measurement. Real devices usually have ids for
# outputs, blocks, scenes/snapshots, or other gain-bearing parameters.
DEMO_GAIN_POINT_ID = "main-output"

# These settings still exist for config and CLI compatibility, but the demo
# panel hides them because the GUI has a dedicated timing tab. This is useful
# when a setting is part of the backend API but should not be duplicated in the
# per-device panel.
DEMO_REDUNDANT_PANEL_SETTINGS = frozenset(
    {
        "preset_wait",
        "snapshot_wait",
        "measurement_wait",
    }
)


class DemoController(DeviceController):
    """No-op controller for an offline demo device.

    Real hardware-backed devices would open MIDI, USB, network, or vendor SDK
    resources here. This demo accepts calls so tests and docs can run without
    hardware.
    """

    def activate_preset(self, preset_id: int) -> None:
        """Switch the physical or virtual device to a preset before measuring.

        MatchPatch calls this during measurement. A real implementation would
        send MIDI program changes, call a vendor SDK, or otherwise steer the
        device. The demo has no hardware, so this method is intentionally a
        no-op.
        """
        return None

    def reapply_snapshot(self, snapshot: int) -> None:
        """Select or reapply the current subdivision within the active preset.

        Helix calls these subdivisions snapshots; the demo calls them scenes.
        Real devices should translate MatchPatch's one-based subdivision number
        to whatever addressing scheme their hardware uses.
        """
        return None


class DemoPatchFileHandler(PatchFileHandler):
    """Patch handler for the fake JSON ``.demobank`` format.

    Required API methods validate paths, expose measurement targets, parse
    selectors, create derived files, and apply adjustments. The JSON schema used
    below is demo-only:

    {
      "presets": [
        {
          "id": "preset:clean",
          "number": 1,
          "name": "Clean",
          "scenes": [
            {"id": "scene:intro", "name": "Intro", "output_level_db": -6.0}
          ]
        }
      ]
    }
    """

    def validate_input(self, input_path: Path) -> None:
        """Reject input files that this handler cannot read.

        MatchPatch calls validation before file operations and normalization.
        Keep the error message user-facing: it may appear in CLI or GUI errors.
        """
        if input_path.suffix.lower() != DEMO_EXTENSION:
            raise ValueError(f"Demo device inputs must use the {DEMO_EXTENSION} extension")

    def validate_output(self, input_path: Path, output_path: Path) -> None:
        """Reject output paths that would produce an unsupported device file.

        The input path is provided too because some devices may allow different
        output extensions depending on whether the input is a preset, setlist,
        library, project, or bank file.
        """
        self.validate_input(input_path)
        if output_path.suffix.lower() != DEMO_EXTENSION:
            raise ValueError(f"Demo device outputs must use the {DEMO_EXTENSION} extension")

    def list_assignments(self, input_path: Path) -> list[PatchAssignment]:
        """Return GUI table rows for the patches contained in a file.

        ``PatchAssignment`` is the older compatibility model used by parts of
        the GUI. Each row needs a stable numeric id, a display patch number, a
        name, and the source filename. New devices should still implement this
        until all workflows have moved fully to ``MeasurementTarget``.
        """
        return [
            PatchAssignment(
                id=_numeric_preset_id(preset, index),
                device_patch=self.format_patch_id(_numeric_preset_id(preset, index)),
                name=str(preset.get("name", "")),
                original_filename=input_path.name,
            )
            for index, preset in enumerate(self._read_presets(input_path))
        ]

    def list_targets(self, input_path: Path) -> list[MeasurementTarget]:
        """Return measurement targets with subdivisions and adjustable points.

        A target is the thing MatchPatch can measure as a unit: usually a
        preset, patch, rig, or bank slot. Subdivisions are optional states below
        that target, such as snapshots or scenes. Gain points describe where
        MatchPatch may write level corrections.
        """
        targets = []
        for preset_index, preset in enumerate(self._read_presets(input_path)):
            preset_id = str(preset.get("id", f"preset:{preset_index + 1}"))
            numeric_id = _numeric_preset_id(preset, preset_index)
            targets.append(
                MeasurementTarget(
                    id=preset_id,
                    display_label=self.format_patch_id(numeric_id),
                    index=preset_index,
                    name=str(preset.get("name", "")),
                    source_filename=input_path.name,
                    subdivisions=self._subdivisions(preset_id, preset),
                    compat_numeric_id=numeric_id,
                )
            )
        return targets

    def file_capabilities(self) -> FileOperationCapabilities:
        """Advertise only the file operations this handler actually supports.

        The demo can read and write whole fake bank files. Real handlers should
        enable flags conservatively; GUI actions and tests rely on this contract
        to avoid offering unsupported operations.
        """
        return FileOperationCapabilities(reads_setlist_files=True, writes_setlist_files=True)

    def file_types(self) -> tuple[DeviceFileType, ...]:
        """Describe file extensions for open/save dialogs and file-kind checks.

        ``kind`` uses MatchPatch's generic vocabulary: ``preset`` for a single
        patch-like file, ``setlist`` for a multi-patch container, and
        ``unknown`` for paths the handler should ignore.
        """
        return (
            DeviceFileType(
                kind="setlist",
                extensions=(DEMO_EXTENSION,),
                description="Demo Device Banks",
            ),
        )

    def file_kind(self, path: Path) -> DeviceFileKind:
        """Classify a path without opening it.

        Returning ``unknown`` is important. It lets the GUI silently ignore a
        file selected for another device instead of showing scary validation
        popups while the user is only changing device selection.
        """
        if path.suffix.lower() == DEMO_EXTENSION:
            return "setlist"
        return "unknown"

    def parse_patch_set(self, value: str) -> list[int]:
        """Parse legacy numeric patch selectors from CLI text.

        This demo accepts comma-separated numbers such as ``1,2,3``. A real
        device can accept vendor-style labels if it also maps them to stable
        ids before returning.
        """
        return [int(item.strip()) for item in value.split(",") if item.strip()]

    def parse_target_set(self, value: str) -> list[int | str]:
        """Parse target selectors from CLI text.

        Targets may use strings because real device formats often have stable
        UUIDs or composite ids. This demo keeps the input text unchanged after
        trimming whitespace.
        """
        return [item.strip() for item in value.split(",") if item.strip()]

    def select_preset_ids(
        self,
        input_path: Path,
        assignments: list[PatchAssignment],
        requested_ids: list[int] | None,
    ) -> list[int]:
        """Choose which assignment ids should be measured by default.

        If the user requested specific ids, preserve that request. Otherwise
        measure every assignment found in the file. Real devices can filter out
        unsupported factory slots, empty presets, or non-audio patches here.
        """
        if requested_ids is not None:
            return requested_ids
        return [assignment.id for assignment in assignments]

    def format_patch_id(self, preset_id: int) -> str:
        """Format a numeric patch id for display in the GUI and logs."""
        return f"D{preset_id:03d}"

    def create_measurement_file(self, input_path: Path, output_path: Path) -> None:
        """Create a file variant suitable for measurement.

        Some devices need a temporary measurement file that disables effects,
        rewrites routing, or normalizes controller state before recording. The
        demo simply copies the JSON and adds a marker so the behavior is visible
        in tests.
        """
        self.validate_output(input_path, output_path)
        data = self._read_data(input_path)
        data["measurement_file"] = True
        self._write_data(output_path, data)

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
        """Apply the classic CSV-driven normalization output.

        Real handlers usually parse ``csv_path`` or the structured
        ``adjustments`` object and write device-specific gain values. The demo
        does not implement loudness normalization; it only writes a note so this
        method remains deterministic and offline.
        """
        self.validate_output(input_path, output_path)
        data = self._read_data(input_path)
        data["normalization_note"] = "Demo device copied file; CSV parsing is not implemented."
        self._write_data(output_path, data)

    def apply_gain_adjustments(
        self,
        input_path: Path,
        output_path: Path,
        adjustments: list[GainAdjustment],
    ) -> None:
        """Apply structured gain adjustments to a copied output file.

        This is the clearest example of real patch mutation in the demo. It
        deep-copies the JSON so unrelated data from the input survives unchanged,
        validates each requested gain point, and changes only the selected
        scene's ``output_level_db`` value.
        """
        self.validate_output(input_path, output_path)
        data = self._read_data(input_path)
        output_data = deepcopy(data)

        scenes = {
            (str(preset.get("id")), str(scene.get("id"))): scene
            for preset in cast("list[dict[str, Any]]", output_data.get("presets", []))
            for scene in cast("list[dict[str, Any]]", preset.get("scenes", []))
        }
        for adjustment in adjustments:
            if adjustment.gain_point_id != DEMO_GAIN_POINT_ID:
                raise ValueError(f"Unknown demo gain point: {adjustment.gain_point_id}")
            scene = scenes.get((str(adjustment.target_id), str(adjustment.subdivision_id)))
            if scene is None:
                raise ValueError(
                    "Unknown demo target/subdivision: "
                    f"{adjustment.target_id}/{adjustment.subdivision_id}"
                )
            scene["output_level_db"] = float(scene.get("output_level_db", 0.0)) + float(
                adjustment.delta_db
            )

        self._write_data(output_path, output_data)

    def automation_output_path(self, input_path: Path, postfix: str) -> Path:
        """Return the default output path for generated files.

        MatchPatch passes suffixes such as ``_normalized`` or
        ``_measurement``. Most devices can preserve the original extension and
        append the postfix to the stem, as shown here.
        """
        return input_path.with_name(f"{input_path.stem}{postfix}{input_path.suffix}")

    def _subdivisions(
        self,
        preset_id: str,
        preset: dict[str, Any],
    ) -> tuple[MeasurementSubdivision, ...]:
        """Convert fake demo scenes into MatchPatch measurement subdivisions.

        Private helpers are not required by the API. They are here to keep the
        public methods small and to show where a real handler would translate
        vendor file structures into MatchPatch dataclasses.
        """
        scenes = cast("list[dict[str, Any]]", preset.get("scenes", []))
        return tuple(
            MeasurementSubdivision(
                id=str(scene.get("id", f"scene:{index + 1}")),
                display_label=str(scene.get("name", index + 1)),
                index=index,
                name=str(scene.get("name", "")),
                gain_points=(
                    GainPoint(
                        id=DEMO_GAIN_POINT_ID,
                        label="Main output",
                        current_db=float(scene.get("output_level_db", 0.0)),
                        minimum_db=-60.0,
                        maximum_db=12.0,
                        scope="subdivision",
                        path=f"{preset_id}/{scene.get('id', f'scene:{index + 1}')}",
                    ),
                ),
            )
            for index, scene in enumerate(scenes)
        )

    def _read_presets(self, input_path: Path) -> list[dict[str, Any]]:
        """Read and type-check the demo's top-level preset list."""
        data = self._read_data(input_path)
        presets = data.get("presets", [])
        if not isinstance(presets, list):
            raise ValueError("Demo device file must contain a list named 'presets'")
        return cast("list[dict[str, Any]]", presets)

    def _read_data(self, input_path: Path) -> dict[str, Any]:
        """Read a demo bank JSON object after validating the path.

        Real handlers should use structured parsers whenever possible. Avoid
        ad-hoc string manipulation for binary or JSON-like vendor formats unless
        the format truly leaves no better option.
        """
        self.validate_input(input_path)
        with input_path.open(encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, dict):
            raise ValueError("Demo device file must contain a JSON object")
        return cast("dict[str, Any]", data)

    @staticmethod
    def _write_data(output_path: Path, data: dict[str, Any]) -> None:
        """Write deterministic JSON so tests can compare output reliably."""
        with output_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, sort_keys=True)
            file.write("\n")


class DemoDeviceProfile(DeviceProfile):
    """Top-level description of one MatchPatch-supported device.

    MatchPatch discovers devices from ``src/matchpatch/devices/available.py``.
    Each entry in that list is a ``DeviceProfile`` instance. The profile owns
    device-wide defaults and creates the smaller helpers used by workflows.
    """

    # ``name`` is the stable machine id used by CLI arguments, config files,
    # tests, and saved GUI state. Changing it is a breaking change.
    name = "demo-device"

    # ``display_name`` is user-facing and can be friendlier than ``name``.
    display_name = "Demo Device"

    # Default and maximum subdivision counts used by policies and GUI controls.
    # For Helix these correspond to snapshots; for the demo they correspond to
    # fake scenes.
    snapshot_count = 2
    max_snapshot_count = 8

    def create_patch_file_handler(self, project_dir: Path) -> PatchFileHandler:
        """Create the object that reads, writes, and mutates device files.

        ``project_dir`` is available for handlers that need bundled resources
        or conversion tools. The demo does not need it.
        """
        return DemoPatchFileHandler()

    def default_audio_routing(self) -> AudioRouting:
        """Return device-specific audio defaults for measurement.

        The demo is offline, but it still provides harmless defaults so shared
        settings code can run. Real devices should choose values that are useful
        for first-run setup.
        """
        return AudioRouting(None, 48000, (1, 2), (1, 2))

    def default_steering_options(self) -> SteeringOptions:
        """Return default device steering options.

        Hardware devices normally provide a MIDI or network output, a channel,
        and wait times. The demo uses zero waits and no output because it cannot
        steer real hardware.
        """
        return SteeringOptions(None, 1, 0.0, 0.0, 0.0)

    def create_controller(self, options: SteeringOptions) -> DeviceController:
        """Create the runtime controller used during measurement.

        A real implementation should pass ``options`` into its controller so it
        can open the configured MIDI port, channel, or transport endpoint.
        """
        return DemoController()

    def supports_normalization(self) -> bool:
        """Disable the normalize button workflow for this example device.

        The demo can demonstrate file parsing and structured adjustment tests,
        but it cannot record audio or compute real loudness corrections.
        """
        return False

    def normalization_unavailable_message(self) -> str:
        """Return the GUI message shown when normalization is unavailable."""
        return (
            "Demo Device is an example for developers and cannot normalize files. "
            "Select a real device, such as Line 6 Helix, to run normalization."
        )

    def setting_descriptors(self) -> tuple[DeviceSettingDescriptor, ...]:
        """Describe settings for config, CLI, validation, and generic GUI.

        Reusing ``super().setting_descriptors()`` gives the demo the standard
        audio and steering settings. The three wait settings are kept for config
        and CLI but hidden from the device panel because they are already shown
        in the GUI timing tab.
        """
        return (
            *(
                replace(descriptor, show_in_gui=False)
                if descriptor.name in DEMO_REDUNDANT_PANEL_SETTINGS
                else descriptor
                for descriptor in super().setting_descriptors()
            ),
            DeviceSettingDescriptor(
                name="demo_mode",
                scope="device",
                kind="choice",
                default="offline",
                config_path=("devices", self.name, "mode"),
                label="Demo mode",
                help="Example device-specific setting rendered by generic front ends.",
                choices=("offline", "simulated"),
            ),
        )

    def file_capabilities(self) -> FileOperationCapabilities:
        """Advertise profile-level file capabilities for menus and dialogs.

        This mirrors ``DemoPatchFileHandler.file_capabilities()`` so callers can
        inspect capabilities from either the profile or a concrete handler.
        """
        return FileOperationCapabilities(reads_setlist_files=True, writes_setlist_files=True)


def _numeric_preset_id(preset: dict[str, Any], index: int) -> int:
    """Return a stable numeric compatibility id for one demo preset.

    The modern API can use string target ids, but parts of MatchPatch still use
    numeric preset ids. Real devices with non-numeric ids should provide a
    deterministic compatibility mapping.
    """
    number = preset.get("number", index + 1)
    if not isinstance(number, int) or isinstance(number, bool):
        raise ValueError("Demo preset 'number' must be an integer")
    return number


__all__ = ["DemoDeviceProfile", "DemoPatchFileHandler"]
