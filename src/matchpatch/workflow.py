"""Reusable preset-normalization workflow shared by CLI and GUI front ends."""

from __future__ import annotations

import csv
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import replace as dataclass_replace
from pathlib import Path
from typing import TypeVar

from matchpatch.analysis import AnalysisOptions
from matchpatch.custom_adjustments import load_custom_adjustments_file
from matchpatch.devices import get_device_profile
from matchpatch.devices.base import (
    DeviceProfile,
    DeviceSettings,
    DeviceTargetId,
    NormalizationPolicy,
    PatchFileAdjustments,
    PatchFileHandler,
    SubdivisionSelection,
    TargetSelection,
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
    snapshot_plan: tuple[tuple[str, tuple[int, ...]], ...] = ()
    policy: NormalizationPolicy = NormalizationPolicy()
    analysis_options: AnalysisOptions = AnalysisOptions()
    device_settings: DeviceSettings | None = None


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
T = TypeVar("T")


def normalize_presets(
    request: NormalizationRequest,
    *,
    run_analysis: AnalysisRunner,
    on_progress: ProgressCallback | None = None,
    confirm_import: ConfirmationCallback | None = None,
    get_profile: ProfileProvider = get_device_profile,
    make_temp_dir: TempDirFactory | None = None,
) -> NormalizationResult:
    profile, handler = _prepare_handler(request, get_profile, on_progress)
    input_path = request.input_path.resolve()
    handler.validate_input(input_path)

    if not request.reference_di.is_file():
        raise ValueError(f"Reference DI WAV does not exist: {request.reference_di}")
    _validate_custom_adjustments(request)

    output_path = _resolve_output_paths(
        request, handler, input_path, profile, confirm_import, on_progress
    )
    selected_targets = _select_targets(request, handler, input_path)
    selected_targets, snapshot_plan = _apply_diff_filter(
        request, handler, input_path, selected_targets, request.snapshot_plan
    )
    selected_targets = _apply_limit(request.limit, selected_targets)

    if not selected_targets:
        raise ValueError("Patch file contains no measurable presets")

    preset_ids = _compat_numeric_target_ids(selected_targets)
    return _run_normalization_workspace(
        request,
        run_analysis,
        handler,
        profile,
        input_path,
        output_path,
        preset_ids,
        snapshot_plan,
        on_progress,
        confirm_import,
        make_temp_dir,
    )


def _prepare_handler(
    request: NormalizationRequest,
    get_profile: ProfileProvider,
    on_progress: ProgressCallback | None,
) -> tuple[DeviceProfile, PatchFileHandler]:
    profile = get_profile(request.device)
    validate_snapshot_count(profile, request.policy.snapshot_count)
    handler = profile.create_patch_file_handler(PROJECT_DIR)
    log_setter = getattr(handler, "set_log_callback", None)
    if log_setter is not None:
        log_setter(lambda message: _emit(on_progress, ProgressEvent("log", message=message)))
    return profile, handler


def _resolve_output_paths(
    request: NormalizationRequest,
    handler: PatchFileHandler,
    input_path: Path,
    profile: DeviceProfile,
    confirm_import: ConfirmationCallback | None,
    on_progress: ProgressCallback | None,
) -> Path | None:
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
        return output_path

    if request.output_path is None:
        raise ValueError("--output is required unless --automation is used")

    output_path = request.output_path.resolve()
    handler.validate_output(input_path, output_path)
    return output_path


def _select_targets(
    request: NormalizationRequest,
    handler: PatchFileHandler,
    input_path: Path,
) -> list[TargetSelection]:
    if _has_target_selection_api(handler):
        requested_ids = (
            handler.parse_target_set(request.preset_set) if request.preset_set is not None else None
        )
        return handler.select_targets(
            input_path,
            handler.list_targets(input_path),
            requested_ids,
        )

    requested_preset_ids = (
        handler.parse_patch_set(request.preset_set) if request.preset_set is not None else None
    )
    assignments = handler.list_assignments(input_path)
    return [
        TargetSelection(
            id=preset_id,
            display_label=handler.format_patch_id(preset_id),
            compat_numeric_id=preset_id,
        )
        for preset_id in handler.select_preset_ids(
            input_path,
            assignments,
            requested_preset_ids,
        )
    ]


def _apply_diff_filter(
    request: NormalizationRequest,
    handler: PatchFileHandler,
    input_path: Path,
    selected_targets: list[TargetSelection],
    snapshot_plan: tuple[tuple[str, tuple[int, ...]], ...],
) -> tuple[list[TargetSelection], tuple[tuple[str, tuple[int, ...]], ...]]:
    if request.diff_input_path is None:
        return selected_targets, snapshot_plan

    previous_input_path = request.diff_input_path.resolve()
    if previous_input_path.suffix.lower() != input_path.suffix.lower():
        raise ValueError("--diff-input must use the same file type as --input")

    diff_snapshots = _diff_subdivisions(request, handler, input_path, previous_input_path)
    diff_ids = set(diff_snapshots)
    filtered_targets = [target for target in selected_targets if target.id in diff_ids]
    return filtered_targets, _intersect_snapshot_plans(
        snapshot_plan,
        tuple((target.display_label, diff_snapshots[target.id]) for target in filtered_targets),
    )


def _diff_subdivisions(
    request: NormalizationRequest,
    handler: PatchFileHandler,
    input_path: Path,
    previous_input_path: Path,
) -> dict[DeviceTargetId, tuple[int, ...]]:
    diff_subdivisions = getattr(handler, "diff_subdivisions", None)
    if diff_subdivisions is None:
        return _legacy_diff_subdivisions(request, handler, input_path, previous_input_path)

    return {
        target_id: tuple(
            _compat_numeric_subdivision_id(subdivision) for subdivision in subdivisions
        )
        for target_id, subdivisions in diff_subdivisions(
            input_path,
            previous_input_path,
            request.policy.snapshot_count,
        ).items()
    }


def _legacy_diff_subdivisions(
    request: NormalizationRequest,
    handler: PatchFileHandler,
    input_path: Path,
    previous_input_path: Path,
) -> dict[DeviceTargetId, tuple[int, ...]]:
    diff_snapshot_ids = getattr(handler, "diff_snapshot_ids", None)
    if diff_snapshot_ids is not None:
        return diff_snapshot_ids(
            input_path,
            previous_input_path,
            request.policy.snapshot_count,
        )

    return {
        preset_id: tuple(range(1, request.policy.snapshot_count + 1))
        for preset_id in handler.diff_preset_ids(input_path, previous_input_path)
    }


def _has_target_selection_api(handler: PatchFileHandler) -> bool:
    return hasattr(handler, "list_targets") and hasattr(handler, "select_targets")


def _apply_limit(limit: int | None, items: list[T]) -> list[T]:
    if limit is None:
        return items
    if limit < 1:
        raise ValueError("--limit must be at least 1")
    return items[:limit]


def _compat_numeric_target_ids(targets: list[TargetSelection]) -> list[int]:
    preset_ids: list[int] = []
    for target in targets:
        if target.compat_numeric_id is not None:
            preset_ids.append(target.compat_numeric_id)
        elif isinstance(target.id, int):
            preset_ids.append(target.id)
        else:
            raise ValueError(
                f"Target {target.display_label!r} cannot be measured by the legacy worker"
            )
    return preset_ids


def _compat_numeric_subdivision_id(subdivision: SubdivisionSelection) -> int:
    if subdivision.compat_numeric_id is not None:
        return subdivision.compat_numeric_id
    if isinstance(subdivision.id, int):
        return subdivision.id
    if subdivision.index is not None:
        return subdivision.index + 1
    raise ValueError(
        f"Subdivision {subdivision.display_label!r} cannot be measured by the legacy worker"
    )


def _run_normalization_workspace(
    request: NormalizationRequest,
    run_analysis: AnalysisRunner,
    handler: PatchFileHandler,
    profile: DeviceProfile,
    input_path: Path,
    output_path: Path | None,
    preset_ids: list[int],
    snapshot_plan: tuple[tuple[str, tuple[int, ...]], ...],
    on_progress: ProgressCallback | None,
    confirm_import: ConfirmationCallback | None,
    make_temp_dir: TempDirFactory | None,
) -> NormalizationResult:
    temp_dir = (
        make_temp_dir()
        if make_temp_dir is not None
        else Path(tempfile.mkdtemp(prefix="matchpatch_normalization_"))
    )
    csv_path = temp_dir / "lufs_analysis.csv"
    success = False

    try:
        _measure_workspace(
            request,
            run_analysis,
            preset_ids,
            snapshot_plan,
            temp_dir,
            csv_path,
            on_progress,
        )
        _apply_workspace_adjustments(
            request, handler, input_path, output_path, csv_path, temp_dir, on_progress
        )
        success = True
    finally:
        _cleanup_workspace(request, temp_dir, csv_path, success, on_progress)

    _emit_completion(request, output_path, profile, confirm_import, on_progress)
    return NormalizationResult(
        output_path,
        temp_dir if request.keep_temp or not success or request.defer_export else None,
        csv_path if request.keep_temp or not success or request.defer_export else None,
    )


def _measure_workspace(
    request: NormalizationRequest,
    run_analysis: AnalysisRunner,
    preset_ids: list[int],
    snapshot_plan: tuple[tuple[str, tuple[int, ...]], ...],
    temp_dir: Path,
    csv_path: Path,
    on_progress: ProgressCallback | None,
) -> None:
    analysis_request = (
        request
        if not request.record_device_output or request.recorded_output_dir is not None
        else dataclass_replace(request, recorded_output_dir=temp_dir / "recordings")
    )
    if snapshot_plan != analysis_request.snapshot_plan:
        analysis_request = dataclass_replace(analysis_request, snapshot_plan=snapshot_plan)
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


def _apply_workspace_adjustments(
    request: NormalizationRequest,
    handler: PatchFileHandler,
    input_path: Path,
    output_path: Path | None,
    csv_path: Path,
    temp_dir: Path,
    on_progress: ProgressCallback | None,
) -> None:
    if output_path is not None:
        _apply_analysis_csv(
            request, handler, input_path, output_path, csv_path, "Applying adjustments", on_progress
        )
        return

    if request.defer_export:
        preview_path = temp_dir / f"{input_path.stem}_preview{input_path.suffix}"
        try:
            _apply_analysis_csv(
                request,
                handler,
                input_path,
                preview_path,
                csv_path,
                "Calculating adjustments",
                on_progress,
            )
        finally:
            preview_path.unlink(missing_ok=True)


def _apply_analysis_csv(
    request: NormalizationRequest,
    handler: PatchFileHandler,
    input_path: Path,
    output_path: Path,
    csv_path: Path,
    message: str,
    on_progress: ProgressCallback | None,
) -> None:
    _emit(on_progress, ProgressEvent("phase", phase="applying", message=message))
    handler.apply_analysis_csv(
        input_path,
        output_path,
        csv_path,
        request.ignore_bad_lufs,
        request.target_lufs,
        request.policy,
        request.custom_adjustments_path,
    )


def _cleanup_workspace(
    request: NormalizationRequest,
    temp_dir: Path,
    csv_path: Path,
    success: bool,
    on_progress: ProgressCallback | None,
) -> None:
    if not request.keep_temp and success and not request.defer_export:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return

    if not request.defer_export:
        _emit(
            on_progress,
            ProgressEvent(
                "temp_retained",
                message=f"Kept temporary CSV: {csv_path}",
                path=str(csv_path),
            ),
        )


def _emit_completion(
    request: NormalizationRequest,
    output_path: Path | None,
    profile: DeviceProfile,
    confirm_import: ConfirmationCallback | None,
    on_progress: ProgressCallback | None,
) -> None:
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


def _intersect_snapshot_plans(
    first: tuple[tuple[str, tuple[int, ...]], ...],
    second: tuple[tuple[str, tuple[int, ...]], ...],
) -> tuple[tuple[str, tuple[int, ...]], ...]:
    if not first:
        return second
    first_by_patch = {patch.upper(): tuple(snapshots) for patch, snapshots in first}
    result = []
    for patch, snapshots in second:
        first_snapshots = first_by_patch.get(patch.upper(), ())
        selected = tuple(snapshot for snapshot in snapshots if snapshot in first_snapshots)
        if selected:
            result.append((patch, selected))
    return tuple(result)


def _emit(callback: ProgressCallback | None, event: ProgressEvent) -> None:
    if callback is not None:
        callback(event)


def _confirm(callback: ConfirmationCallback | None, request: ImportRequest) -> None:
    if callback is not None and not callback(request):
        raise RuntimeError("Normalization cancelled by user")


def _count_csv_rows(csv_path: Path) -> int:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        return sum(1 for _ in csv.DictReader(csv_file))
