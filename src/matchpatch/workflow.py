"""Reusable preset-normalization workflow shared by CLI and GUI front ends."""

from __future__ import annotations

import csv
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import replace as dataclass_replace
from pathlib import Path

from matchpatch.analysis import AnalysisOptions
from matchpatch.custom_adjustments import load_custom_adjustments_file
from matchpatch.devices import get_device_profile
from matchpatch.devices.base import (
    DeviceProfile,
    NormalizationPolicy,
    PatchFileAdjustments,
    validate_snapshot_count,
)
from matchpatch.progress import ProgressEvent

PROJECT_DIR = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ImportRequest:
    kind: str
    device_display_name: str
    path: Path

    @property
    def message(self) -> str:
        description = "measurement" if self.kind == "measurement" else "adjusted"
        return (
            f"Please import this {description} file into {self.device_display_name}:\n{self.path}"
        )


@dataclass(frozen=True)
class NormalizationRequest:
    device: str
    input_path: Path
    backend: str
    windows_python: str
    reference_di: Path
    custom_adjustments_path: Path | None = None
    output_path: Path | None = None
    diff_input_path: Path | None = None
    automation: bool = True
    defer_export: bool = False
    preset_set: str | None = None
    limit: int | None = None
    keep_temp: bool = False
    ignore_bad_lufs: bool = True
    target_lufs: float = -16.0
    timeout: float | None = None
    audio_device: str | int | None = None
    sample_rate: int | None = None
    input_mapping: str | None = None
    output_mapping: str | None = None
    blocksize: int | None = None
    steering_output: str | None = None
    steering_channel: int | None = None
    preset_wait: float | None = None
    snapshot_wait: float | None = None
    measurement_wait: float | None = None
    pre_roll: float | None = None
    post_roll: float | None = None
    round_trip_latency: float | None = None
    simulate_fail_presets: str | None = None
    play_recorded_output: bool = False
    record_device_output: bool = False
    playback_toggle_path: Path | None = None
    recorded_output_dir: Path | None = None
    policy: NormalizationPolicy = NormalizationPolicy()
    analysis_options: AnalysisOptions = AnalysisOptions()


@dataclass(frozen=True)
class NormalizationResult:
    output_path: Path | None
    temp_dir: Path | None
    retained_csv_path: Path | None = None


ProgressCallback = Callable[[ProgressEvent], None]
ConfirmationCallback = Callable[[ImportRequest], bool]
AnalysisRunner = Callable[[NormalizationRequest, list[int], Path, ProgressCallback | None], None]
ProfileProvider = Callable[[str], DeviceProfile]
TempDirFactory = Callable[[], Path]


def normalize_presets(
    request: NormalizationRequest,
    *,
    run_analysis: AnalysisRunner,
    on_progress: ProgressCallback | None = None,
    confirm_import: ConfirmationCallback | None = None,
    get_profile: ProfileProvider = get_device_profile,
    make_temp_dir: TempDirFactory | None = None,
) -> NormalizationResult:
    profile = get_profile(request.device)
    validate_snapshot_count(profile, request.policy.snapshot_count)
    handler = profile.create_patch_file_handler(PROJECT_DIR)
    log_setter = getattr(handler, "set_log_callback", None)
    if log_setter is not None:
        log_setter(lambda message: _emit(on_progress, ProgressEvent("log", message=message)))
    input_path = request.input_path.resolve()
    handler.validate_input(input_path)

    if not request.reference_di.is_file():
        raise ValueError(f"Reference DI WAV does not exist: {request.reference_di}")
    _validate_custom_adjustments(request)

    if request.automation:
        if request.output_path is not None:
            raise ValueError("--output must not be specified with --automation")

        measurement_path = handler.automation_output_path(input_path, "_measurement")
        output_path = (
            None
            if request.defer_export
            else handler.automation_output_path(input_path, "_adjusted")
        )
        _emit(on_progress, ProgressEvent("phase", phase="preparing_measurement"))
        handler.create_measurement_file(input_path, measurement_path)
        _emit(on_progress, ProgressEvent("phase", phase="waiting_for_measurement_import"))
        _confirm(
            confirm_import,
            ImportRequest("measurement", profile.display_name, measurement_path),
        )
    else:
        if request.output_path is None:
            raise ValueError("--output is required unless --automation is used")

        output_path = request.output_path.resolve()
        handler.validate_output(input_path, output_path)

    requested_ids = (
        handler.parse_patch_set(request.preset_set) if request.preset_set is not None else None
    )
    assignments = handler.list_assignments(input_path)
    preset_ids = handler.select_preset_ids(input_path, assignments, requested_ids)

    if request.diff_input_path is not None:
        previous_input_path = request.diff_input_path.resolve()
        if previous_input_path.suffix.lower() != input_path.suffix.lower():
            raise ValueError("--diff-input must use the same file type as --input")
        diff_ids = set(handler.diff_preset_ids(input_path, previous_input_path))
        preset_ids = [preset_id for preset_id in preset_ids if preset_id in diff_ids]

    if request.limit is not None:
        if request.limit < 1:
            raise ValueError("--limit must be at least 1")

        preset_ids = preset_ids[: request.limit]

    if not preset_ids:
        raise ValueError("Patch file contains no measurable presets")

    temp_dir = (
        make_temp_dir()
        if make_temp_dir is not None
        else Path(tempfile.mkdtemp(prefix="matchpatch_normalization_", dir=PROJECT_DIR))
    )
    success = False

    try:
        csv_path = temp_dir / "lufs_analysis.csv"
        analysis_request = (
            request
            if not request.record_device_output or request.recorded_output_dir is not None
            else dataclass_replace(request, recorded_output_dir=temp_dir / "recordings")
        )
        _emit(
            on_progress,
            ProgressEvent(
                "phase",
                phase="measuring",
                message="Starting measurement worker...",
                preset_total=len(preset_ids),
                snapshot_total=request.policy.snapshot_count,
            ),
        )
        run_analysis(analysis_request, preset_ids, csv_path, on_progress)

        measured_rows = _count_csv_rows(csv_path)

        if measured_rows != len(preset_ids):
            raise RuntimeError(
                f"Windows analysis wrote {measured_rows} rows for {len(preset_ids)} presets"
            )

        if output_path is not None:
            _emit(
                on_progress,
                ProgressEvent("phase", phase="applying", message="Applying adjustments"),
            )
            handler.apply_analysis_csv(
                input_path,
                output_path,
                csv_path,
                request.ignore_bad_lufs,
                request.target_lufs,
                request.policy,
                request.custom_adjustments_path,
            )
        elif request.defer_export:
            preview_path = temp_dir / f"{input_path.stem}_preview{input_path.suffix}"
            _emit(
                on_progress,
                ProgressEvent("phase", phase="applying", message="Calculating adjustments"),
            )
            try:
                handler.apply_analysis_csv(
                    input_path,
                    preview_path,
                    csv_path,
                    request.ignore_bad_lufs,
                    request.target_lufs,
                    request.policy,
                    request.custom_adjustments_path,
                )
            finally:
                preview_path.unlink(missing_ok=True)
        success = True
    finally:
        if not request.keep_temp and success and not request.defer_export:
            shutil.rmtree(temp_dir, ignore_errors=True)
        elif not request.defer_export:
            _emit(
                on_progress,
                ProgressEvent(
                    "temp_retained",
                    message=f"Kept temporary CSV: {csv_path}",
                    path=str(csv_path),
                ),
            )

    _emit(
        on_progress,
        ProgressEvent(
            "phase",
            phase="completed",
            message=(
                "Measurement completed; ready to export"
                if request.defer_export
                else "Gain-adjusted patch file written"
            ),
        ),
    )

    if request.automation and output_path is not None:
        _emit(on_progress, ProgressEvent("phase", phase="waiting_for_adjusted_import"))
        _confirm(
            confirm_import,
            ImportRequest("adjusted", profile.display_name, output_path),
        )

    return NormalizationResult(
        output_path,
        temp_dir if request.keep_temp or not success or request.defer_export else None,
        csv_path if request.keep_temp or not success or request.defer_export else None,
    )


def export_adjusted_file(
    request: NormalizationRequest,
    csv_path: Path,
    output_path: Path,
    *,
    adjustments: PatchFileAdjustments | None = None,
    on_progress: ProgressCallback | None = None,
    get_profile: ProfileProvider = get_device_profile,
) -> None:
    profile = get_profile(request.device)
    handler = profile.create_patch_file_handler(PROJECT_DIR)
    log_setter = getattr(handler, "set_log_callback", None)
    if log_setter is not None:
        log_setter(lambda message: _emit(on_progress, ProgressEvent("log", message=message)))
    input_path = request.input_path.resolve()
    output_path = output_path.resolve()
    handler.validate_input(input_path)
    handler.validate_output(input_path, output_path)
    _validate_custom_adjustments(request)
    handler.apply_analysis_csv(
        input_path,
        output_path,
        csv_path,
        request.ignore_bad_lufs,
        request.target_lufs,
        request.policy,
        request.custom_adjustments_path,
        adjustments,
    )


def _validate_custom_adjustments(request: NormalizationRequest) -> None:
    if request.custom_adjustments_path is None:
        return
    if not request.custom_adjustments_path.is_file():
        raise ValueError(
            f"Custom adjustments CSV does not exist: {request.custom_adjustments_path}"
        )
    load_custom_adjustments_file(request.custom_adjustments_path, request.policy.snapshot_count)


def _emit(callback: ProgressCallback | None, event: ProgressEvent) -> None:
    if callback is not None:
        callback(event)


def _confirm(callback: ConfirmationCallback | None, request: ImportRequest) -> None:
    if callback is not None and not callback(request):
        raise RuntimeError("Normalization cancelled by user")


def _count_csv_rows(csv_path: Path) -> int:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        return sum(1 for _ in csv.DictReader(csv_file))
