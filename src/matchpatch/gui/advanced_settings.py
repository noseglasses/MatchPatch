"""Advanced GUI settings state and config/request binding."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence, cast

from matchpatch.config import Config, default_config
from matchpatch.devices.base import normalize_regex_pattern
from matchpatch.normalize import apply_config, parse_args, request_from_args
from matchpatch.workflow import NormalizationRequest


class _MeasurementOptimizationSettingsLike(Protocol):
    pre_roll: float
    post_roll: float
    round_trip_latency: float
    preset_wait: float
    snapshot_wait: float
    measurement_wait: float


@dataclass(frozen=True)
class GuiSettingsState:
    device: str
    input_path: str
    backend: str
    config_path: str
    custom_adjustments_path: str
    reference_di: str
    target_lufs: str
    solo_gain_bump_db: str
    solo_regex: str
    ignore_snapshot_regex: str
    snapshot_count: int
    keep_temp: bool
    device_arguments: tuple[str, ...]
    analysis_window: str
    analysis_interval: str
    pre_roll: str
    post_roll: str
    round_trip_latency: str
    preset_wait: str
    snapshot_wait: str
    measurement_wait: str
    selected_preset_set: str
    optimization_stability_runs: int
    optimization_termination_tolerance: float
    optimization_stability_tolerance: float
    play_recorded_output: bool = False
    record_device_output: bool = False
    playback_toggle_path: Path | None = None

    def base_argv(self, input_path: str) -> list[str]:
        argv = [
            "--device",
            self.device,
            "-i",
            input_path,
            "--automation",
            "--backend",
            self.backend,
        ]
        if self.config_path:
            argv.extend(["--config", self.config_path])
        if self.custom_adjustments_path:
            argv.extend(["--custom-adjustments-file", self.custom_adjustments_path])
        return argv

    def build_argv(self) -> list[str]:
        argv = self.base_argv(self.input_path)
        self.append_gui_config_arguments(argv)
        if self.selected_preset_set:
            argv.extend(["--preset-set", self.selected_preset_set])
        return argv

    def build_config_export_argv(self) -> list[str]:
        argv = self.base_argv(self.input_path or "placeholder.hls")
        self.append_gui_config_arguments(argv)
        return argv

    def append_gui_config_arguments(self, argv: list[str]) -> None:
        argv.extend(["--reference-di", self.reference_di])
        argv.extend(["--target-lufs", self.target_lufs])
        argv.extend(["--solo-gain-bump-db", self.solo_gain_bump_db])
        argv.extend(["--solo-regex", normalize_regex_pattern(self.solo_regex)])
        argv.extend(
            ["--ignore-snapshot-regex", normalize_regex_pattern(self.ignore_snapshot_regex)]
        )
        argv.extend(["--snapshot-count", str(self.snapshot_count)])
        if self.keep_temp:
            argv.append("--keep-temp")
        argv.extend(self.device_arguments)
        append_optional_argument(argv, "--analysis-window", self.analysis_window)
        append_optional_argument(argv, "--analysis-interval", self.analysis_interval)
        append_optional_argument(argv, "--pre-roll", self.pre_roll)
        append_optional_argument(argv, "--post-roll", self.post_roll)
        append_optional_argument(argv, "--round-trip-latency", self.round_trip_latency)
        append_optional_argument(argv, "--preset-wait", self.preset_wait)
        append_optional_argument(argv, "--snapshot-wait", self.snapshot_wait)
        append_optional_argument(argv, "--measurement-wait", self.measurement_wait)

    def active_config(self) -> Config:
        args = apply_config(parse_args(self.build_config_export_argv()))
        config = default_config()
        config["normalize"] = {
            "backend": args.backend,
            "windows_python": str(args.windows_python),
            "reference_di": str(args.reference_di),
            "custom_adjustments_file": (
                str(args.custom_adjustments_file) if args.custom_adjustments_file else None
            ),
            "target_lufs": args.target_lufs,
        }
        if args.timeout is not None:
            config["normalize"]["timeout_seconds"] = args.timeout
        config["analysis"] = {
            "window_seconds": args.analysis_options.window_seconds,
            "interval_seconds": args.analysis_options.interval_seconds,
            "minimum_valid_lufs": args.analysis_options.minimum_valid_lufs,
            "pre_roll_seconds": args.pre_roll,
            "post_roll_seconds": args.post_roll,
            "round_trip_latency_seconds": args.round_trip_latency,
        }
        config["measurement"] = {
            "stability_runs": self.optimization_stability_runs,
            "termination_tolerance_percent": self.optimization_termination_tolerance,
            "stability_tolerance_percent": self.optimization_stability_tolerance,
        }
        config["policy"] = {
            "measured_snapshots": args.policy.snapshot_count,
            "solo_regex": args.policy.solo_regex,
            "ignore_snapshot_regex": args.policy.ignore_snapshot_regex,
            "solo_gain_bump_db": args.policy.solo_gain_bump_db,
            "crest_factor_reference_db": args.policy.crest_factor_reference_db,
            "crest_factor_correction_ratio": args.policy.crest_factor_correction_ratio,
            "max_crest_factor_correction_db": args.policy.max_crest_factor_correction_db,
            "gain_deadband_db": args.policy.gain_deadband_db,
        }
        devices = config["devices"]
        assert isinstance(devices, dict)
        devices[args.device] = {
            "audio": {
                "device": args.audio_device,
                "sample_rate": args.sample_rate,
                "input_mapping": list(parse_config_channel_mapping(args.input_mapping)),
                "output_mapping": list(parse_config_channel_mapping(args.output_mapping)),
                "blocksize": args.blocksize,
            },
            "steering": {
                "output": args.steering_output,
                "channel": args.steering_channel,
                "preset_wait_seconds": args.preset_wait,
                "snapshot_wait_seconds": args.snapshot_wait,
                "measurement_wait_seconds": args.measurement_wait,
            },
        }
        return config

    def normalization_request(self, *, defer_export: bool = False) -> NormalizationRequest:
        request = request_from_args(apply_config(parse_args(self.build_argv())))
        if defer_export:
            request = replace(request, defer_export=True)
        return request

    def with_audio_capture_options(
        self,
        request: NormalizationRequest,
        *,
        record_device_output: bool | None = None,
        playback_toggle_path: Path | None = None,
    ) -> NormalizationRequest:
        return replace(
            request,
            play_recorded_output=self.play_recorded_output,
            record_device_output=(
                self.record_device_output if record_device_output is None else record_device_output
            ),
            playback_toggle_path=playback_toggle_path or self.playback_toggle_path,
        )


class GuiSettingsBinder:
    @staticmethod
    def from_widgets(window: object) -> GuiSettingsState:
        window = cast(Any, window)
        device_arguments: list[str] = []
        panel = window.device_panels.get(window.device.currentData())
        if panel is not None:
            panel.append_arguments(device_arguments)
        return GuiSettingsState(
            device=window.device.currentData(),
            input_path=window.input_path.text().strip(),
            backend=window.backend.currentText(),
            config_path=window.config_path.text().strip(),
            custom_adjustments_path=(
                window.custom_adjustments_path.text().strip()
                if hasattr(window, "custom_adjustments_path")
                else ""
            ),
            reference_di=window.reference_di.text(),
            target_lufs=window.target_lufs.text(),
            solo_gain_bump_db=window.solo_gain_bump_db.text(),
            solo_regex=window.solo_regex.text(),
            ignore_snapshot_regex=window.ignore_snapshot_regex.text(),
            snapshot_count=window.snapshot_count_input.value(),
            keep_temp=window.keep_temp.isChecked(),
            device_arguments=tuple(device_arguments),
            analysis_window=window.analysis_window.text(),
            analysis_interval=window.analysis_interval.text(),
            pre_roll=window.pre_roll.text(),
            post_roll=window.post_roll.text(),
            round_trip_latency=window.round_trip_latency.text(),
            preset_wait=window.preset_wait.text(),
            snapshot_wait=window.snapshot_wait.text(),
            measurement_wait=window.measurement_wait.text(),
            selected_preset_set=selected_preset_set(
                window._selected_measurable_preset_rows(),
                window._preset_patch_at_row,
            ),
            optimization_stability_runs=window._optimization_stability_runs,
            optimization_termination_tolerance=window._optimization_termination_tolerance,
            optimization_stability_tolerance=window._optimization_stability_tolerance,
            play_recorded_output=window.play_recorded_output_button.isChecked(),
            record_device_output=window.record_output_button.isChecked(),
            playback_toggle_path=window._playback_toggle_path,
        )


@dataclass(frozen=True)
class PresetTableSelectionContext:
    has_table: bool
    row_count: int
    checked_rows: set[int]
    has_ignored_snapshots: bool
    comparison_snapshot_plan: dict[str, tuple[int, ...]] | None
    input_path: str
    patch_at_row: Callable[[int], str | None]
    row_measured_snapshot_indexes: Callable[[int], tuple[int, ...]]
    measurement_progress_plan_for_request: Callable[[NormalizationRequest], Any]
    progress_plan_factory: Callable[[tuple[tuple[str, tuple[int, ...]], ...]], Any]


def request_with_preset_table_selection(
    request: NormalizationRequest,
    context: PresetTableSelectionContext,
) -> NormalizationRequest:
    if not context.has_table or context.row_count == 0:
        return request

    has_unchecked_presets = any(row not in context.checked_rows for row in range(context.row_count))
    has_ignored_snapshots = context.has_ignored_snapshots
    comparison_snapshot_plan = context.comparison_snapshot_plan
    if comparison_snapshot_plan is not None:
        has_ignored_snapshots = True
    preset_set = request.preset_set
    progress_plan = context.measurement_progress_plan_for_request(request)
    if has_unchecked_presets or has_ignored_snapshots:
        candidate_rows = selected_candidate_rows(
            context, has_unchecked_presets, has_ignored_snapshots
        )
        selected_patches, preset_snapshots = selected_patch_snapshots(
            context, candidate_rows, comparison_snapshot_plan
        )
        preset_set = preset_set_from_selected_patches(selected_patches) or preset_set
        progress_plan = (
            context.progress_plan_factory(tuple(preset_snapshots)) if preset_snapshots else None
        )
    if progress_plan is None:
        if preset_set == request.preset_set:
            return request
        return replace(request, preset_set=preset_set)

    if preset_set is None and (has_unchecked_presets or has_ignored_snapshots):
        preset_set = ",".join(patch for patch, _snapshots in progress_plan.preset_snapshots)
    snapshot_plan = request.snapshot_plan
    if has_ignored_snapshots:
        snapshot_plan = progress_plan.preset_snapshots
    if preset_set == request.preset_set and snapshot_plan == request.snapshot_plan:
        return request
    return replace(request, preset_set=preset_set, snapshot_plan=snapshot_plan)


def selected_candidate_rows(
    context: PresetTableSelectionContext,
    has_unchecked_presets: bool,
    has_ignored_snapshots: bool,
) -> list[int]:
    if Path(context.input_path).suffix.lower() == ".hlx":
        return [0] if context.row_count else []
    if has_unchecked_presets:
        return sorted(context.checked_rows)
    if has_ignored_snapshots:
        return list(range(context.row_count))
    return []


def selected_patch_snapshots(
    context: PresetTableSelectionContext,
    candidate_rows: Sequence[int],
    comparison_snapshot_plan: dict[str, tuple[int, ...]] | None,
) -> tuple[list[str], list[tuple[str, tuple[int, ...]]]]:
    selected_patches: list[str] = []
    preset_snapshots: list[tuple[str, tuple[int, ...]]] = []
    for row in candidate_rows:
        patch = _normalized_patch_at_row(context, row)
        if patch is None:
            continue
        selected_patches.append(patch)
        snapshots = _selected_row_snapshots(context, row, patch, comparison_snapshot_plan)
        if snapshots:
            preset_snapshots.append((patch, snapshots))
    return selected_patches, preset_snapshots


def preset_set_from_selected_patches(selected_patches: Sequence[str]) -> str | None:
    return ",".join(selected_patches) if selected_patches else None


def _normalized_patch_at_row(
    context: PresetTableSelectionContext,
    row: int,
) -> str | None:
    patch = context.patch_at_row(row)
    if patch is None:
        return None
    patch = patch.strip().upper()
    return patch or None


def _selected_row_snapshots(
    context: PresetTableSelectionContext,
    row: int,
    patch: str,
    comparison_snapshot_plan: dict[str, tuple[int, ...]] | None,
) -> tuple[int, ...]:
    measurable_snapshots = context.row_measured_snapshot_indexes(row)
    if comparison_snapshot_plan is None:
        return measurable_snapshots
    return tuple(
        snapshot
        for snapshot in comparison_snapshot_plan.get(patch, ())
        if snapshot in measurable_snapshots
    )


def diagnostic_request(
    settings: GuiSettingsState,
    context: PresetTableSelectionContext,
    *,
    completed_request: NormalizationRequest | None = None,
) -> NormalizationRequest:
    request = (
        completed_request if completed_request is not None else settings.normalization_request()
    )
    return request_with_preset_table_selection(request, context)


def selected_preset_set(
    selected_rows: Sequence[int],
    patch_at_row: Callable[[int], str | None],
) -> str:
    selected = []
    for row in selected_rows:
        patch = patch_at_row(row)
        if patch is not None and patch.strip():
            selected.append(patch)
    return ",".join(selected)


def request_with_measurement_optimization_settings(
    request: NormalizationRequest,
    settings: _MeasurementOptimizationSettingsLike,
) -> NormalizationRequest:
    return replace(
        request,
        pre_roll=settings.pre_roll,
        post_roll=settings.post_roll,
        round_trip_latency=settings.round_trip_latency,
        preset_wait=settings.preset_wait,
        snapshot_wait=settings.snapshot_wait,
        measurement_wait=settings.measurement_wait,
    )


def append_optional_argument(argv: list[str], name: str, value: object) -> None:
    text = "" if value is None else str(value).strip()
    if text and text != "None":
        argv.extend([name, text])


def nested_config_value(config: dict[str, Any], path: tuple[str, ...]) -> object | None:
    value: object = config
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def parse_config_channel_mapping(value: object) -> tuple[int, int]:
    if isinstance(value, str):
        parsed = [int(item.strip()) for item in value.split(",") if item.strip()]
    elif isinstance(value, (list, tuple)):
        parsed = [item for item in value if isinstance(item, int)]
    else:
        raise ValueError("Channel mapping must contain two positive IDs")
    if len(parsed) != 2:
        raise ValueError("Channel mapping must contain two positive IDs")
    return parsed[0], parsed[1]
