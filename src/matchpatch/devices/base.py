"""Interfaces implemented by each supported audio processor."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Literal, Protocol, Self, cast, runtime_checkable

if TYPE_CHECKING:
    import numpy as np

    from matchpatch.diagnostics import DiagnosticCheck
    from matchpatch.workflow import NormalizationRequest

DeviceFileKind = Literal["preset", "setlist", "unknown"]
AudioProcessingMode = Literal["hardware", "loopback", "simulated", "offline"]
DeviceTargetId = int | str
DeviceSubdivisionId = int | str
GainPointScope = Literal["target", "subdivision"]
SettingKind = Literal[
    "string",
    "integer",
    "float",
    "boolean",
    "choice",
    "path",
    "channel_mapping",
]
SettingScope = Literal["audio", "steering", "processing", "diagnostics", "device"]
DeviceSettings = dict[str, object]


@dataclass(frozen=True)
class DeviceSettingDescriptor:
    name: str
    scope: SettingScope
    kind: SettingKind
    default: object | None = None
    config_path: tuple[str, ...] = ()
    cli_flags: tuple[str, ...] = ()
    label: str = ""
    help: str = ""
    choices: tuple[str, ...] = ()
    minimum: int | float | None = None
    maximum: int | float | None = None
    required: bool = False


@dataclass(frozen=True)
class DeviceTerminology:
    device: str = "device"
    preset: str = "preset"
    snapshot: str = "snapshot"
    setlist: str = "setlist"


@dataclass(frozen=True)
class DeviceFileType:
    kind: DeviceFileKind
    extensions: tuple[str, ...]
    description: str
    can_open: bool = True
    can_save: bool = True

    def normalized_extensions(self) -> tuple[str, ...]:
        return tuple(
            extension.lower() if extension.startswith(".") else f".{extension.lower()}"
            for extension in self.extensions
        )

    def patterns(self) -> tuple[str, ...]:
        return tuple(f"*{extension}" for extension in self.normalized_extensions())

    def name_filter(self) -> str:
        return f"{self.description} ({' '.join(self.patterns())})"


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
class AudioTransportCapabilities:
    mode: AudioProcessingMode
    supported_sample_rates: tuple[int, ...] = ()
    channel_layout: str = "stereo"
    real_time: bool = True
    offline: bool = False
    asynchronous: bool = False
    alignment_guarantee: bool = True
    can_record_debug_output: bool = False


@dataclass(frozen=True)
class NamingRules:
    preset_name_max_length: int | None = None
    snapshot_name_max_length: int | None = None
    allowed_name_pattern: str | None = None
    replacement_character: str = ""
    trim_whitespace: bool = False
    forbidden_names: frozenset[str] = frozenset()


@dataclass(frozen=True)
class PresetFileRecord:
    path: Path
    slot_id: int | None
    device_patch: str | None
    name: str
    original_filename: str | None = None


@dataclass(frozen=True)
class GainPoint:
    id: str
    label: str
    current_db: float
    minimum_db: float
    maximum_db: float
    scope: GainPointScope
    path: str | None = None


@dataclass(frozen=True)
class GainAdjustment:
    target_id: DeviceTargetId
    subdivision_id: DeviceSubdivisionId | None
    gain_point_id: str
    delta_db: float


@dataclass(frozen=True)
class PatchAssignment:
    id: int
    device_patch: str
    name: str
    snapshot_names: tuple[str, ...] = ()
    snapshot_output_levels: tuple[tuple[float, ...], ...] = ()
    snapshot_output_paths: tuple[str, ...] = ()
    original_filename: str | None = None
    gain_points: tuple[GainPoint, ...] = ()


@dataclass(frozen=True)
class MeasurementSubdivision:
    id: DeviceSubdivisionId
    display_label: str
    index: int
    name: str
    gain_points: tuple[GainPoint, ...] = ()


@dataclass(frozen=True)
class MeasurementTarget:
    id: DeviceTargetId
    display_label: str
    index: int
    name: str
    source_filename: str | None = None
    subdivisions: tuple[MeasurementSubdivision, ...] = ()
    compat_numeric_id: int | None = None
    gain_points: tuple[GainPoint, ...] = ()


@dataclass(frozen=True)
class TargetSelection:
    id: DeviceTargetId
    display_label: str
    index: int | None = None
    name: str = ""
    compat_numeric_id: int | None = None


@dataclass(frozen=True)
class SubdivisionSelection:
    target_id: DeviceTargetId
    id: DeviceSubdivisionId
    display_label: str
    index: int | None = None
    name: str = ""
    compat_numeric_id: int | None = None


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
class AudioTransportContext:
    profile: DeviceProfile
    mode: AudioProcessingMode
    settings: Mapping[str, object]
    audio_routing: AudioRouting
    steering_options: SteeringOptions
    sample_rate: int
    snapshot_count: int
    audio_config: object | None = None
    controller: DeviceController | None = None
    temporary_file_dir: Path | None = None
    failing_preset_ids: frozenset[int] = frozenset()
    timing_values: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class OfflineAudioProcessingRequest:
    reference_audio: np.ndarray
    sample_rate: int
    target_id: int
    subdivision_id: int
    target_metadata: Mapping[str, object] = field(default_factory=dict)
    subdivision_metadata: Mapping[str, object] = field(default_factory=dict)
    temporary_file_dir: Path | None = None


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


@dataclass(frozen=True)
class DiagnosticsContext:
    request: NormalizationRequest
    profile: DeviceProfile
    handler: PatchFileHandler
    resolved_settings: Mapping[str, object]
    project_dir: Path


class DiagnosticsProvider(Protocol):
    def run_checks(self, context: DiagnosticsContext) -> list[DiagnosticCheck]:
        """Return device-specific preflight diagnostics."""


def normalize_regex_pattern(pattern: str) -> str:
    r"""Preserve user-visible ``\b`` word-boundary escapes decoded by config/UI paths."""
    return pattern.replace("\b", r"\b")


def _assignment_to_measurement_target(
    assignment: PatchAssignment,
    index: int,
) -> MeasurementTarget:
    return MeasurementTarget(
        id=assignment.id,
        display_label=assignment.device_patch,
        index=index,
        name=assignment.name,
        source_filename=assignment.original_filename,
        subdivisions=_assignment_subdivisions(assignment),
        compat_numeric_id=assignment.id,
        gain_points=tuple(
            gain_point for gain_point in assignment.gain_points if gain_point.scope == "target"
        ),
    )


def _assignment_subdivisions(
    assignment: PatchAssignment,
) -> tuple[MeasurementSubdivision, ...]:
    subdivision_count = max(
        len(assignment.snapshot_names),
        len(assignment.snapshot_output_levels),
        len(assignment.snapshot_output_paths),
    )
    return tuple(_assignment_subdivision(assignment, index) for index in range(subdivision_count))


def _assignment_subdivision(
    assignment: PatchAssignment,
    index: int,
) -> MeasurementSubdivision:
    name = assignment.snapshot_names[index] if index < len(assignment.snapshot_names) else ""
    subdivision_id = index + 1
    display_label = name or str(subdivision_id)
    return MeasurementSubdivision(
        id=subdivision_id,
        display_label=display_label,
        index=index,
        name=name,
        gain_points=_assignment_subdivision_gain_points(assignment, index),
    )


def _assignment_subdivision_gain_points(
    assignment: PatchAssignment,
    index: int,
) -> tuple[GainPoint, ...]:
    if index >= len(assignment.snapshot_output_levels):
        return tuple(
            gain_point for gain_point in assignment.gain_points if gain_point.scope == "subdivision"
        )

    levels = assignment.snapshot_output_levels[index]
    subdivision_gain_points = tuple(
        gain_point for gain_point in assignment.gain_points if gain_point.scope == "subdivision"
    )
    return tuple(
        GainPoint(
            id=gain_point.id,
            label=gain_point.label,
            current_db=float(levels[point_index]),
            minimum_db=gain_point.minimum_db,
            maximum_db=gain_point.maximum_db,
            scope=gain_point.scope,
            path=gain_point.path,
        )
        for point_index, gain_point in enumerate(subdivision_gain_points)
        if point_index < len(levels)
    )


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


class AudioProcessorTransport(Protocol):
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def activate_target(self, target: int) -> None: ...

    def activate_subdivision(self, subdivision: int) -> None: ...

    def process(self, reference_audio: np.ndarray) -> np.ndarray: ...


@runtime_checkable
class OfflineAudioTransport(Protocol):
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def activate_target(self, target: int) -> None: ...

    def activate_subdivision(self, subdivision: int) -> None: ...

    def process_offline(self, request: OfflineAudioProcessingRequest) -> np.ndarray: ...


AudioTransport = AudioProcessorTransport | OfflineAudioTransport


class AudioTransportFactory(Protocol):
    capabilities: AudioTransportCapabilities

    def supports(self, mode: AudioProcessingMode, settings: Mapping[str, object]) -> bool: ...

    def create(self, context: AudioTransportContext) -> AudioTransport: ...


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

    def list_targets(self, input_path: Path) -> list[MeasurementTarget]:
        """List measurable targets contained in a patch file."""
        return [
            _assignment_to_measurement_target(assignment, index)
            for index, assignment in enumerate(self.list_assignments(input_path))
        ]

    def list_gain_points(
        self,
        input_path: Path,
        target_id: DeviceTargetId | None = None,
        subdivision_id: DeviceSubdivisionId | None = None,
    ) -> list[GainPoint]:
        """List gain points available for a target or subdivision."""
        points: list[GainPoint] = []
        for target in self.list_targets(input_path):
            if target_id is not None and target.id != target_id:
                continue
            if subdivision_id is None:
                points.extend(target.gain_points)
            for subdivision in target.subdivisions:
                if subdivision_id is None or subdivision.id == subdivision_id:
                    points.extend(subdivision.gain_points)
        return points

    def metadata(self, input_path: Path) -> dict[str, object]:
        """Extract displayable metadata from a patch file."""
        return {}

    def file_capabilities(self) -> FileOperationCapabilities:
        """Describe device file operations supported by this handler."""
        return FileOperationCapabilities()

    def file_types(self) -> tuple[DeviceFileType, ...]:
        """Describe device-owned file extensions and their user-facing labels."""
        return ()

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

    def diff_targets(
        self,
        input_path: Path,
        previous_input_path: Path,
    ) -> list[TargetSelection]:
        """List changed targets between two patch files."""
        return [
            self._target_selection_from_numeric_id(input_path, preset_id)
            for preset_id in self.diff_preset_ids(input_path, previous_input_path)
        ]

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

    def diff_subdivisions(
        self,
        input_path: Path,
        previous_input_path: Path,
        subdivision_count: int,
    ) -> dict[DeviceTargetId, tuple[SubdivisionSelection, ...]]:
        """List changed subdivisions per changed target."""
        return {
            target.id: tuple(
                self._subdivision_selection_from_numeric_id(
                    input_path,
                    target,
                    subdivision_id,
                )
                for subdivision_id in subdivision_ids
            )
            for preset_id, subdivision_ids in self.diff_snapshot_ids(
                input_path,
                previous_input_path,
                subdivision_count,
            ).items()
            for target in (self._target_selection_from_numeric_id(input_path, preset_id),)
        }

    @abstractmethod
    def parse_patch_set(self, value: str) -> list[int]:
        """Parse device-facing preset labels into numeric preset IDs."""

    def parse_target_set(self, value: str) -> list[DeviceTargetId]:
        """Parse device-facing target labels into device target IDs."""
        return list(self.parse_patch_set(value))

    @abstractmethod
    def select_preset_ids(
        self,
        input_path: Path,
        assignments: list[PatchAssignment],
        requested_ids: list[int] | None,
    ) -> list[int]:
        """Resolve the presets that should be measured."""

    def select_targets(
        self,
        input_path: Path,
        targets: list[MeasurementTarget],
        requested_ids: list[DeviceTargetId] | None,
    ) -> list[TargetSelection]:
        """Resolve the measurement targets that should be measured."""
        requested_numeric_ids = self._compat_numeric_ids(requested_ids)
        assignments = self.list_assignments(input_path)
        return [
            self._target_selection_from_numeric_id(input_path, preset_id, targets)
            for preset_id in self.select_preset_ids(
                input_path,
                assignments,
                requested_numeric_ids,
            )
        ]

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

    def apply_gain_adjustments(
        self,
        input_path: Path,
        output_path: Path,
        adjustments: list[GainAdjustment],
    ) -> None:
        """Apply explicit gain adjustments to a patch file."""
        if adjustments:
            raise NotImplementedError("Gain adjustments are not supported for this device")

    @abstractmethod
    def automation_output_path(self, input_path: Path, postfix: str) -> Path:
        """Build a device-compatible output path beside the input file."""

    @staticmethod
    def _compat_numeric_ids(ids: list[DeviceTargetId] | None) -> list[int] | None:
        if ids is None:
            return None
        if all(isinstance(item, int) for item in ids):
            return list(cast("list[int]", ids))
        raise NotImplementedError("Generic target selection is not supported for this device")

    def _target_selection_from_numeric_id(
        self,
        input_path: Path,
        preset_id: int,
        targets: list[MeasurementTarget] | None = None,
    ) -> TargetSelection:
        target = self._target_from_numeric_id(input_path, preset_id, targets)
        if target is None:
            return TargetSelection(
                id=preset_id,
                display_label=self.format_patch_id(preset_id),
                compat_numeric_id=preset_id,
            )
        return TargetSelection(
            id=target.id,
            display_label=target.display_label,
            index=target.index,
            name=target.name,
            compat_numeric_id=target.compat_numeric_id,
        )

    def _subdivision_selection_from_numeric_id(
        self,
        input_path: Path,
        target: TargetSelection,
        subdivision_id: int,
    ) -> SubdivisionSelection:
        measurement_target = self._target_from_selection(input_path, target)
        if measurement_target is not None:
            for subdivision in measurement_target.subdivisions:
                if subdivision.id == subdivision_id:
                    return SubdivisionSelection(
                        target_id=target.id,
                        id=subdivision.id,
                        display_label=subdivision.display_label,
                        index=subdivision.index,
                        name=subdivision.name,
                        compat_numeric_id=subdivision_id,
                    )

        return SubdivisionSelection(
            target_id=target.id,
            id=subdivision_id,
            display_label=str(subdivision_id),
            index=subdivision_id - 1,
            compat_numeric_id=subdivision_id,
        )

    def _target_from_selection(
        self,
        input_path: Path,
        selection: TargetSelection,
    ) -> MeasurementTarget | None:
        for target in self.list_targets(input_path):
            if target.id == selection.id:
                return target
            if (
                selection.compat_numeric_id is not None
                and target.compat_numeric_id == selection.compat_numeric_id
            ):
                return target
        return None

    def _target_from_numeric_id(
        self,
        input_path: Path,
        preset_id: int,
        targets: list[MeasurementTarget] | None = None,
    ) -> MeasurementTarget | None:
        candidate_targets = targets if targets is not None else self.list_targets(input_path)
        for target in candidate_targets:
            if target.compat_numeric_id == preset_id or target.id == preset_id:
                return target
        return None


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

    def audio_transport_factories(self) -> tuple[AudioTransportFactory, ...]:
        """Return plugin-provided audio transport factories for this device."""
        return ()

    def diagnostics_provider(self) -> DiagnosticsProvider | None:
        """Return optional device-specific preflight diagnostics."""
        return None

    def naming_rules(self) -> NamingRules:
        return NamingRules(
            preset_name_max_length=getattr(self, "preset_name_max_length", None),
            snapshot_name_max_length=getattr(self, "snapshot_name_max_length", None),
        )

    def validate_preset_name(self, name: str) -> str:
        return self._validate_name(name, self.naming_rules().preset_name_max_length)

    def validate_subdivision_name(self, name: str) -> str:
        return self._validate_name(name, self.naming_rules().snapshot_name_max_length)

    def sanitize_preset_name(self, name: str) -> str:
        return self._sanitize_name(name, self.naming_rules().preset_name_max_length)

    def sanitize_subdivision_name(self, name: str) -> str:
        return self._sanitize_name(name, self.naming_rules().snapshot_name_max_length)

    def _validate_name(self, name: str, max_length: int | None) -> str:
        rules = self.naming_rules()
        candidate = name.strip() if rules.trim_whitespace else name
        if (
            rules.allowed_name_pattern is not None
            and re.fullmatch(
                rules.allowed_name_pattern,
                candidate,
            )
            is None
        ):
            raise ValueError(f"Invalid {self.display_name} name: {name!r}")
        if max_length is not None and len(candidate) > max_length:
            raise ValueError(f"{self.display_name} name exceeds {max_length} characters: {name!r}")
        if candidate in rules.forbidden_names:
            raise ValueError(f"Forbidden {self.display_name} name: {name!r}")
        return candidate

    def _sanitize_name(self, name: str, max_length: int | None) -> str:
        rules = self.naming_rules()
        sanitized = name.strip() if rules.trim_whitespace else name
        if rules.allowed_name_pattern is not None:
            sanitized = "".join(
                character
                if re.fullmatch(rules.allowed_name_pattern, character) is not None
                else rules.replacement_character
                for character in sanitized
            )
        if max_length is not None:
            sanitized = sanitized[:max_length]
        return "" if sanitized in rules.forbidden_names else sanitized

    def format_patch_id(self, preset_id: int) -> str:
        """Format a numeric preset ID for device-facing status text."""
        return str(preset_id)

    @abstractmethod
    def default_audio_routing(self) -> AudioRouting:
        """Return the processor's USB measurement channel defaults."""

    @abstractmethod
    def default_steering_options(self) -> SteeringOptions:
        """Return the processor's steering defaults."""

    def setting_descriptors(self) -> tuple[DeviceSettingDescriptor, ...]:
        """Return GUI-free device setting metadata for config and front ends."""
        audio = self.default_audio_routing()
        steering = self.default_steering_options()
        audio_path = ("devices", self.name, "audio")
        steering_path = ("devices", self.name, "steering")
        return (
            DeviceSettingDescriptor(
                name="audio_device",
                scope="audio",
                kind="string",
                default=audio.device,
                config_path=(*audio_path, "device"),
                cli_flags=("--audio-device",),
                label="Audio device",
                help="Audio input/output device used for measurement.",
            ),
            DeviceSettingDescriptor(
                name="sample_rate",
                scope="audio",
                kind="integer",
                default=audio.sample_rate,
                config_path=(*audio_path, "sample_rate"),
                cli_flags=("--sample-rate",),
                label="Sample rate",
                help="Audio sample rate in hertz.",
                minimum=1,
            ),
            DeviceSettingDescriptor(
                name="input_mapping",
                scope="audio",
                kind="channel_mapping",
                default=audio.input_mapping,
                config_path=(*audio_path, "input_mapping"),
                cli_flags=("--input-mapping",),
                label="Input mapping",
                help="One-based stereo input channel mapping.",
            ),
            DeviceSettingDescriptor(
                name="output_mapping",
                scope="audio",
                kind="channel_mapping",
                default=audio.output_mapping,
                config_path=(*audio_path, "output_mapping"),
                cli_flags=("--output-mapping",),
                label="Output mapping",
                help="One-based stereo output channel mapping.",
            ),
            DeviceSettingDescriptor(
                name="blocksize",
                scope="audio",
                kind="integer",
                default=0,
                config_path=(*audio_path, "blocksize"),
                cli_flags=("--blocksize",),
                label="Blocksize",
                help="Audio block size, or zero for the backend default.",
                minimum=0,
            ),
            DeviceSettingDescriptor(
                name="midi_output",
                scope="steering",
                kind="string",
                default=steering.output,
                config_path=(*steering_path, "output"),
                cli_flags=("--steering-output", "--midi-output"),
                label="MIDI output",
                help="MIDI output port query used for device steering.",
            ),
            DeviceSettingDescriptor(
                name="midi_channel",
                scope="steering",
                kind="integer",
                default=steering.channel,
                config_path=(*steering_path, "channel"),
                cli_flags=("--midi-channel",),
                label="MIDI channel",
                help="Zero-based MIDI channel used for steering.",
                minimum=0,
                maximum=15,
            ),
            DeviceSettingDescriptor(
                name="preset_wait",
                scope="steering",
                kind="float",
                default=steering.preset_wait_seconds,
                config_path=(*steering_path, "preset_wait_seconds"),
                cli_flags=("--preset-wait",),
                label="Preset wait",
                help="Seconds to wait after changing presets.",
                minimum=0.0,
            ),
            DeviceSettingDescriptor(
                name="snapshot_wait",
                scope="steering",
                kind="float",
                default=steering.snapshot_wait_seconds,
                config_path=(*steering_path, "snapshot_wait_seconds"),
                cli_flags=("--snapshot-wait",),
                label="Snapshot wait",
                help="Seconds to wait after changing snapshots.",
                minimum=0.0,
            ),
            DeviceSettingDescriptor(
                name="measurement_wait",
                scope="steering",
                kind="float",
                default=steering.measurement_wait_seconds,
                config_path=(*steering_path, "measurement_wait_seconds"),
                cli_flags=("--measurement-wait",),
                label="Measurement wait",
                help="Seconds to wait before recording each measurement.",
                minimum=0.0,
            ),
        )

    def validate_settings(self, settings: Mapping[str, object]) -> None:
        """Validate provided setting values against this profile's descriptors."""
        descriptors = {descriptor.name: descriptor for descriptor in self.setting_descriptors()}

        for descriptor in descriptors.values():
            if descriptor.required and descriptor.name not in settings:
                raise ValueError(f"Missing required device setting: {descriptor.name}")

        for name, value in settings.items():
            descriptor = descriptors.get(name)
            if descriptor is None:
                continue
            _validate_setting_value(descriptor, value)

    @abstractmethod
    def create_controller(self, options: SteeringOptions) -> DeviceController:
        """Open the transport used to select presets and snapshots."""


def _validate_setting_value(descriptor: DeviceSettingDescriptor, value: object) -> None:
    if value is None:
        if descriptor.required:
            raise ValueError(f"Device setting {descriptor.name} is required")
        return

    validators = {
        "boolean": _validate_boolean_setting,
        "integer": _validate_integer_setting,
        "float": _validate_float_setting,
        "choice": _validate_choice_setting,
        "path": _validate_path_setting,
        "channel_mapping": _validate_channel_mapping_setting,
    }
    validator = validators.get(descriptor.kind, _validate_string_setting)
    validator(descriptor, value)


def _validate_boolean_setting(descriptor: DeviceSettingDescriptor, value: object) -> None:
    if not isinstance(value, bool):
        raise ValueError(f"Device setting {descriptor.name} must be a boolean")


def _validate_integer_setting(descriptor: DeviceSettingDescriptor, value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"Device setting {descriptor.name} must be an integer")
    _validate_numeric_range(descriptor, value)


def _validate_float_setting(descriptor: DeviceSettingDescriptor, value: object) -> None:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"Device setting {descriptor.name} must be a number")
    _validate_numeric_range(descriptor, float(value))


def _validate_choice_setting(descriptor: DeviceSettingDescriptor, value: object) -> None:
    if not isinstance(value, str):
        raise ValueError(f"Device setting {descriptor.name} must be a string choice")
    if descriptor.choices and value not in descriptor.choices:
        choices = ", ".join(descriptor.choices)
        raise ValueError(f"Device setting {descriptor.name} must be one of: {choices}")


def _validate_path_setting(descriptor: DeviceSettingDescriptor, value: object) -> None:
    if not isinstance(value, str | Path):
        raise ValueError(f"Device setting {descriptor.name} must be a path")


def _validate_channel_mapping_setting(
    descriptor: DeviceSettingDescriptor,
    value: object,
) -> None:
    if (
        not isinstance(value, tuple | list)
        or len(value) != 2
        or any(not isinstance(channel, int) or isinstance(channel, bool) for channel in value)
    ):
        raise ValueError(f"Device setting {descriptor.name} must be a two-channel integer mapping")
    channels = cast("tuple[int, ...] | list[int]", value)
    if any(channel < 1 for channel in channels):
        raise ValueError(f"Device setting {descriptor.name} channels must be at least 1")


def _validate_string_setting(descriptor: DeviceSettingDescriptor, value: object) -> None:
    if not isinstance(value, str):
        raise ValueError(f"Device setting {descriptor.name} must be a string")


def _validate_numeric_range(descriptor: DeviceSettingDescriptor, value: int | float) -> None:
    if descriptor.minimum is not None and value < descriptor.minimum:
        raise ValueError(f"Device setting {descriptor.name} must be at least {descriptor.minimum}")

    if descriptor.maximum is not None and value > descriptor.maximum:
        raise ValueError(f"Device setting {descriptor.name} must not exceed {descriptor.maximum}")


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
