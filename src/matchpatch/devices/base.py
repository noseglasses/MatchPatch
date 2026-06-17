"""Interfaces implemented by each supported audio processor."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Literal, Self

DeviceFileKind = Literal["preset", "setlist", "unknown"]


@dataclass(frozen=True)
class DeviceTerminology:
    device: str = "device"
    preset: str = "preset"
    snapshot: str = "snapshot"
    setlist: str = "setlist"


@dataclass(frozen=True)
class FileOperationCapabilities:
    reads_preset_files: bool = False
    writes_preset_files: bool = False
    reads_setlist_files: bool = False
    writes_setlist_files: bool = False
    joins_presets_to_setlist: bool = False
    splits_setlist_to_presets: bool = False
    replaces_setlist_slots: bool = False
    exports_selected_setlist_slots: bool = False


@dataclass(frozen=True)
class MeasurementBackendCapabilities:
    hardware: bool = True
    loopback: bool = True
    simulated: bool = True
    offline: bool = False

    def names(self) -> tuple[str, ...]:
        return tuple(
            name for name in ("hardware", "loopback", "simulated", "offline") if getattr(self, name)
        )


@dataclass(frozen=True)
class NamingRules:
    preset_name_max_length: int | None = None
    snapshot_name_max_length: int | None = None
    allowed_name_pattern: str | None = None


@dataclass(frozen=True)
class PresetFileRecord:
    path: Path
    slot_id: int | None
    device_patch: str | None
    name: str
    original_filename: str | None = None


@dataclass(frozen=True)
class PatchAssignment:
    id: int
    device_patch: str
    name: str
    snapshot_names: tuple[str, ...] = ()
    snapshot_output_levels: tuple[tuple[float, ...], ...] = ()
    snapshot_output_paths: tuple[str, ...] = ()
    original_filename: str | None = None


@dataclass(frozen=True)
class PatchFileAdjustments:
    preset_names: dict[str, str]
    snapshot_names: dict[str, dict[int, str]]
    gain_deltas: dict[str, dict[int, float]]


@dataclass(frozen=True)
class AudioRouting:
    device: str | int | None
    sample_rate: int
    input_mapping: tuple[int, int]
    output_mapping: tuple[int, int]


@dataclass(frozen=True)
class SteeringOptions:
    output: str | None
    channel: int
    preset_wait_seconds: float
    snapshot_wait_seconds: float
    measurement_wait_seconds: float


@dataclass(frozen=True)
class NormalizationPolicy:
    snapshot_count: int = 4
    solo_regex: str = r"(?i)\bsolo\b"
    ignore_snapshot_regex: str = r"(?i)^SNAPSHOT [1-9]\d*$"
    ignore_preset_regex: str = ""
    solo_gain_bump_db: float = 3.0
    crest_factor_reference_db: float = 12.0
    crest_factor_correction_ratio: float = 0.4
    max_crest_factor_correction_db: float = 3.0
    gain_deadband_db: float = 0.25


def normalize_regex_pattern(pattern: str) -> str:
    r"""Preserve user-visible ``\b`` word-boundary escapes decoded by config/UI paths."""
    return pattern.replace("\b", r"\b")


class DeviceController(ABC):
    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    @abstractmethod
    def activate_preset(self, preset_id: int) -> None:
        """Select a processor preset by its internal numeric ID."""

    @abstractmethod
    def reapply_snapshot(self, snapshot: int) -> None:
        """Select a processor snapshot by its one-based numeric ID."""


class PatchFileHandler(ABC):
    def set_log_callback(self, callback: Callable[[str], None] | None) -> None:
        """Receive device-specific utility output when a front end wants it."""
        return None

    @abstractmethod
    def validate_input(self, input_path: Path) -> None:
        """Validate an input setlist or preset file."""

    @abstractmethod
    def validate_output(self, input_path: Path, output_path: Path) -> None:
        """Validate the requested output filename."""

    @abstractmethod
    def list_assignments(self, input_path: Path) -> list[PatchAssignment]:
        """List measurable presets contained in a patch file."""

    def metadata(self, input_path: Path) -> dict[str, object]:
        """Extract displayable metadata from a patch file."""
        return {}

    def file_capabilities(self) -> FileOperationCapabilities:
        """Describe device file operations supported by this handler."""
        return FileOperationCapabilities()

    def file_kind(self, path: Path) -> DeviceFileKind:
        """Classify a path as a device preset file, setlist file, or unknown."""
        return "unknown"

    def join_preset_files(
        self,
        preset_paths: list[Path],
        output_path: Path,
        *,
        slot_ids: list[int] | None = None,
    ) -> None:
        """Join individual preset files into a setlist file when supported."""
        raise NotImplementedError("Joining preset files is not supported for this device")

    def split_setlist_file(
        self,
        input_path: Path,
        output_dir: Path,
        *,
        selected_ids: list[int] | None = None,
        original_filenames: Mapping[int, str] | None = None,
    ) -> list[Path]:
        """Split a setlist file into individual preset files when supported."""
        raise NotImplementedError("Splitting setlist files is not supported for this device")

    def suggest_preset_filename(
        self,
        assignment: PatchAssignment,
        used_names: set[str],
    ) -> str:
        """Suggest a unique filename for exporting an individual preset."""
        original = assignment.original_filename
        if original:
            candidate = Path(original).name
        else:
            stem = "".join(
                char if char.isalnum() or char in "._- " else "_" for char in assignment.name
            )
            candidate = (stem.strip(" .") or self.format_patch_id(assignment.id)) + ".preset"

        path = Path(candidate)
        stem = path.stem or self.format_patch_id(assignment.id)
        suffix = path.suffix or ".preset"
        unique = stem + suffix
        counter = 2
        while unique.casefold() in used_names:
            unique = f"{stem}-{self.format_patch_id(assignment.id)}-{counter}{suffix}"
            counter += 1
        used_names.add(unique.casefold())
        return unique

    def diff_preset_ids(self, input_path: Path, previous_input_path: Path) -> list[int]:
        """List presets whose loudness-affecting content differs between two patch files."""
        raise NotImplementedError("Preset diff selection is not supported for this device")

    def diff_snapshot_ids(
        self,
        input_path: Path,
        previous_input_path: Path,
        snapshot_count: int,
    ) -> dict[int, tuple[int, ...]]:
        """List changed one-based snapshots per changed preset."""
        return {
            preset_id: tuple(range(1, snapshot_count + 1))
            for preset_id in self.diff_preset_ids(input_path, previous_input_path)
        }

    @abstractmethod
    def parse_patch_set(self, value: str) -> list[int]:
        """Parse device-facing preset labels into numeric preset IDs."""

    @abstractmethod
    def select_preset_ids(
        self,
        input_path: Path,
        assignments: list[PatchAssignment],
        requested_ids: list[int] | None,
    ) -> list[int]:
        """Resolve the presets that should be measured."""

    @abstractmethod
    def format_patch_id(self, preset_id: int) -> str:
        """Format a numeric preset ID for logs and CSV output."""

    @abstractmethod
    def create_measurement_file(self, input_path: Path, output_path: Path) -> None:
        """Rewrite a patch file for processor USB measurement."""

    @abstractmethod
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
        """Apply measured gain adjustments to a patch file."""

    @abstractmethod
    def automation_output_path(self, input_path: Path, postfix: str) -> Path:
        """Build a device-compatible output path beside the input file."""


class DeviceProfile(ABC):
    name: str
    display_name: str
    snapshot_count: int = 4
    max_snapshot_count: int | None = None
    preset_name_max_length: int | None = None
    snapshot_name_max_length: int | None = None

    @abstractmethod
    def create_patch_file_handler(self, project_dir: Path) -> PatchFileHandler:
        """Create the device-specific patch-file adapter."""

    def terminology(self) -> DeviceTerminology:
        return DeviceTerminology()

    def file_capabilities(self) -> FileOperationCapabilities:
        return FileOperationCapabilities()

    def measurement_backends(self) -> tuple[str, ...]:
        return MeasurementBackendCapabilities().names()

    def naming_rules(self) -> NamingRules:
        return NamingRules(
            preset_name_max_length=getattr(self, "preset_name_max_length", None),
            snapshot_name_max_length=getattr(self, "snapshot_name_max_length", None),
        )

    def format_patch_id(self, preset_id: int) -> str:
        """Format a numeric preset ID for device-facing status text."""
        return str(preset_id)

    @abstractmethod
    def default_audio_routing(self) -> AudioRouting:
        """Return the processor's USB measurement channel defaults."""

    @abstractmethod
    def default_steering_options(self) -> SteeringOptions:
        """Return the processor's steering defaults."""

    @abstractmethod
    def create_controller(self, options: SteeringOptions) -> DeviceController:
        """Open the transport used to select presets and snapshots."""


def validate_snapshot_count(profile: DeviceProfile, snapshot_count: int) -> None:
    if not isinstance(snapshot_count, int) or isinstance(snapshot_count, bool):
        raise ValueError("Configured measured snapshot count must be an integer")

    if snapshot_count < 1:
        raise ValueError("Configured measured snapshot count must be at least 1")

    max_snapshot_count = getattr(profile, "max_snapshot_count", None)

    if max_snapshot_count is not None and snapshot_count > max_snapshot_count:
        raise ValueError(
            f"Configured measured snapshot count for {profile.display_name} "
            f"must not exceed {max_snapshot_count}"
        )
