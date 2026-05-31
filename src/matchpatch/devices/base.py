"""Interfaces implemented by each supported audio processor."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Self


@dataclass(frozen=True)
class PatchAssignment:
    id: int
    device_patch: str
    name: str
    snapshot_names: tuple[str, ...] = ()


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
    solo_gain_bump_db: float = 3.0
    crest_factor_reference_db: float = 12.0
    crest_factor_correction_ratio: float = 0.4
    max_crest_factor_correction_db: float = 3.0
    gain_deadband_db: float = 0.25


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
        """Select a snapshot after forcing its state to be reloaded."""


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
    def create_reamp_file(self, input_path: Path, output_path: Path) -> None:
        """Rewrite a patch file for processor USB reamping."""

    @abstractmethod
    def apply_analysis_csv(
        self,
        input_path: Path,
        output_path: Path,
        csv_path: Path,
        ignore_bad_lufs: bool,
        target_lufs: float,
        policy: NormalizationPolicy,
    ) -> None:
        """Apply measured gain adjustments to a patch file."""

    @abstractmethod
    def automation_output_path(self, input_path: Path, postfix: str) -> Path:
        """Build a device-compatible output path beside the input file."""


class DeviceProfile(ABC):
    name: str
    display_name: str
    snapshot_count: int = 4

    @abstractmethod
    def create_patch_file_handler(self, project_dir: Path) -> PatchFileHandler:
        """Create the device-specific patch-file adapter."""

    @abstractmethod
    def default_audio_routing(self) -> AudioRouting:
        """Return the processor's USB reamping channel defaults."""

    @abstractmethod
    def default_steering_options(self) -> SteeringOptions:
        """Return the processor's steering defaults."""

    @abstractmethod
    def create_controller(self, options: SteeringOptions) -> DeviceController:
        """Open the transport used to select presets and snapshots."""
