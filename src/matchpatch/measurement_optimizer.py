"""Timing-parameter stability optimization for measurement runs."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Protocol

import numpy as np

from matchpatch.analysis import AnalysisOptions, analyze_audio
from matchpatch.devices.base import DeviceProfile


class MeasurementBackend(Protocol):
    def activate_preset(self, preset_id: int) -> None: ...

    def reapply_snapshot(self, snapshot: int) -> None: ...

    def record(self, reference_audio: np.ndarray) -> np.ndarray: ...


@dataclass(frozen=True)
class TimingParameter:
    name: str
    label: str
    table: tuple[str, ...]
    key: str
    duration_multiplier: float = 1.0
    lower_bound: Callable[[dict[str, float]], float] = lambda values: 0.0
    stable_start: Callable[[dict[str, float]], float] = lambda values: 0.0


@dataclass(frozen=True)
class StabilityStatistics:
    snapshot1_lufs_mean: float
    snapshot1_lufs_std: float
    snapshot1_crest_mean: float
    snapshot1_crest_std: float
    snapshot2_lufs_mean: float
    snapshot2_lufs_std: float
    snapshot2_crest_mean: float
    snapshot2_crest_std: float
    tolerance_percent: float = 2.0
    snapshot1_lufs_tolerance: float = 0.0
    snapshot1_lufs_max_deviation: float = 0.0
    snapshot1_crest_tolerance: float = 0.0
    snapshot1_crest_max_deviation: float = 0.0
    snapshot2_lufs_tolerance: float = 0.0
    snapshot2_lufs_max_deviation: float = 0.0
    snapshot2_crest_tolerance: float = 0.0
    snapshot2_crest_max_deviation: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot1_lufs_mean": self.snapshot1_lufs_mean,
            "snapshot1_lufs_std": self.snapshot1_lufs_std,
            "snapshot1_crest_mean": self.snapshot1_crest_mean,
            "snapshot1_crest_std": self.snapshot1_crest_std,
            "snapshot2_lufs_mean": self.snapshot2_lufs_mean,
            "snapshot2_lufs_std": self.snapshot2_lufs_std,
            "snapshot2_crest_mean": self.snapshot2_crest_mean,
            "snapshot2_crest_std": self.snapshot2_crest_std,
            "tolerance_percent": self.tolerance_percent,
            "snapshot1_lufs_tolerance": self.snapshot1_lufs_tolerance,
            "snapshot1_lufs_max_deviation": self.snapshot1_lufs_max_deviation,
            "snapshot1_crest_tolerance": self.snapshot1_crest_tolerance,
            "snapshot1_crest_max_deviation": self.snapshot1_crest_max_deviation,
            "snapshot2_lufs_tolerance": self.snapshot2_lufs_tolerance,
            "snapshot2_lufs_max_deviation": self.snapshot2_lufs_max_deviation,
            "snapshot2_crest_tolerance": self.snapshot2_crest_tolerance,
            "snapshot2_crest_max_deviation": self.snapshot2_crest_max_deviation,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> StabilityStatistics:
        return cls(
            snapshot1_lufs_mean=float(value["snapshot1_lufs_mean"]),
            snapshot1_lufs_std=float(value["snapshot1_lufs_std"]),
            snapshot1_crest_mean=float(value["snapshot1_crest_mean"]),
            snapshot1_crest_std=float(value["snapshot1_crest_std"]),
            snapshot2_lufs_mean=float(value["snapshot2_lufs_mean"]),
            snapshot2_lufs_std=float(value["snapshot2_lufs_std"]),
            snapshot2_crest_mean=float(value["snapshot2_crest_mean"]),
            snapshot2_crest_std=float(value["snapshot2_crest_std"]),
            tolerance_percent=float(value.get("tolerance_percent", 2.0)),
            snapshot1_lufs_tolerance=float(value.get("snapshot1_lufs_tolerance", 0.0)),
            snapshot1_lufs_max_deviation=float(value.get("snapshot1_lufs_max_deviation", 0.0)),
            snapshot1_crest_tolerance=float(value.get("snapshot1_crest_tolerance", 0.0)),
            snapshot1_crest_max_deviation=float(value.get("snapshot1_crest_max_deviation", 0.0)),
            snapshot2_lufs_tolerance=float(value.get("snapshot2_lufs_tolerance", 0.0)),
            snapshot2_lufs_max_deviation=float(value.get("snapshot2_lufs_max_deviation", 0.0)),
            snapshot2_crest_tolerance=float(value.get("snapshot2_crest_tolerance", 0.0)),
            snapshot2_crest_max_deviation=float(value.get("snapshot2_crest_max_deviation", 0.0)),
        )


@dataclass(frozen=True)
class ParameterOptimizationResult:
    parameter: TimingParameter
    value: float
    stable: bool
    iterations: int
    statistics: StabilityStatistics | None = None


@dataclass(frozen=True)
class OptimizationProgress:
    kind: str
    message: str
    parameter: str | None = None
    candidate: float | None = None
    stable: bool | None = None
    low: float | None = None
    high: float | None = None
    best: float | None = None
    iteration: int | None = None
    statistics: StabilityStatistics | None = None
    result_toml: str | None = None
    results: tuple[ParameterOptimizationResult, ...] = ()

    def to_json(self) -> str:
        payload = {
            "kind": self.kind,
            "message": self.message,
            "parameter": self.parameter,
            "candidate": self.candidate,
            "stable": self.stable,
            "low": self.low,
            "high": self.high,
            "best": self.best,
            "iteration": self.iteration,
            "statistics": (self.statistics.to_dict() if self.statistics is not None else None),
            "result_toml": self.result_toml,
            "results": [
                {
                    "parameter": {
                        "name": result.parameter.name,
                        "label": result.parameter.label,
                        "table": result.parameter.table,
                        "key": result.parameter.key,
                    },
                    "value": result.value,
                    "stable": result.stable,
                    "iterations": result.iterations,
                    "statistics": (
                        result.statistics.to_dict() if result.statistics is not None else None
                    ),
                }
                for result in self.results
            ],
        }
        return json.dumps(payload, separators=(",", ":"))

    @classmethod
    def from_json(cls, value: str) -> OptimizationProgress:
        payload: Any = json.loads(value)
        if not isinstance(payload, dict):
            raise ValueError("Optimization progress must be a JSON object")
        payload["results"] = tuple(
            ParameterOptimizationResult(
                TimingParameter(
                    item["parameter"]["name"],
                    item["parameter"]["label"],
                    tuple(item["parameter"]["table"]),
                    item["parameter"]["key"],
                ),
                item["value"],
                item["stable"],
                item["iterations"],
                StabilityStatistics.from_dict(item["statistics"])
                if item.get("statistics") is not None
                else None,
            )
            for item in payload.get("results", ())
        )
        if payload.get("statistics") is not None:
            payload["statistics"] = StabilityStatistics.from_dict(payload["statistics"])
        return cls(**payload)


class BackendFactory(Protocol):
    def __call__(self, values: dict[str, float]) -> MeasurementBackend: ...


ProgressCallback = Callable[[OptimizationProgress], None]


class MeasurementAnalysisError(ValueError):
    """Raised when a timing candidate produces audio that cannot be analyzed."""


TIMING_PARAMETERS: tuple[TimingParameter, ...] = (
    TimingParameter(
        "pre_roll",
        "Pre-roll",
        ("analysis",),
        "pre_roll_seconds",
        2.0,
        stable_start=lambda values: 1.0,
    ),
    TimingParameter(
        "post_roll",
        "Post-roll",
        ("analysis",),
        "post_roll_seconds",
        2.0,
        lower_bound=lambda values: values["round_trip_latency"],
        stable_start=lambda values: 1.0,
    ),
    TimingParameter(
        "round_trip_latency",
        "Round-trip latency",
        ("analysis",),
        "round_trip_latency_seconds",
        2.0,
        stable_start=lambda values: 0.05,
    ),
    TimingParameter(
        "preset_wait",
        "Preset wait",
        ("devices", "{device}", "steering"),
        "preset_wait_seconds",
        1.0,
        stable_start=lambda values: 2.0,
    ),
    TimingParameter(
        "snapshot_wait",
        "Snapshot wait",
        ("devices", "{device}", "steering"),
        "snapshot_wait_seconds",
        2.0,
        stable_start=lambda values: 1.0,
    ),
    TimingParameter(
        "measurement_wait",
        "Measurement wait",
        ("devices", "{device}", "steering"),
        "measurement_wait_seconds",
        2.0,
        stable_start=lambda values: 1.0,
    ),
)


def _optimization_start_values(
    initial_values: dict[str, float], parameters: tuple[TimingParameter, ...]
) -> dict[str, float]:
    values = dict(initial_values)
    for parameter in parameters:
        lower = parameter.lower_bound(values)
        stable_start = parameter.stable_start(values)
        values[parameter.name] = max(values[parameter.name], lower, stable_start)
    return values


def _parameters_by_duration_impact(
    values: dict[str, float], parameters: tuple[TimingParameter, ...]
) -> tuple[TimingParameter, ...]:
    return tuple(
        sorted(
            parameters,
            key=lambda parameter: (
                values[parameter.name] * parameter.duration_multiplier,
                parameter.duration_multiplier,
            ),
            reverse=True,
        )
    )


def optimize_timing_parameters(
    profile: DeviceProfile,
    preset_id: int,
    alternate_preset_id: int,
    reference: np.ndarray,
    sample_rate: int,
    backend_factory: BackendFactory,
    initial_values: dict[str, float],
    analysis_options: AnalysisOptions,
    *,
    stability_runs: int = 3,
    termination_tolerance_percent: float = 10.0,
    stability_tolerance_percent: float = 2.0,
    on_progress: ProgressCallback | None = None,
    parameters: tuple[TimingParameter, ...] = TIMING_PARAMETERS,
) -> tuple[ParameterOptimizationResult, ...]:
    _validate_optimizer_settings(
        stability_runs,
        termination_tolerance_percent,
        stability_tolerance_percent,
    )
    results: list[ParameterOptimizationResult] = []
    values = _optimization_start_values(initial_values, parameters)
    ordered_parameters = _parameters_by_duration_impact(values, parameters)
    preset_label = profile.format_patch_id(preset_id)
    reference_stable, reference_statistics = _is_stable(
        profile,
        preset_id,
        alternate_preset_id,
        reference,
        sample_rate,
        backend_factory,
        values,
        analysis_options,
        stability_runs,
        stability_tolerance_percent,
    )
    proven_statistics = reference_statistics if reference_stable else None

    for parameter in ordered_parameters:
        proven_statistics = _optimize_parameter(
            profile,
            preset_id,
            alternate_preset_id,
            preset_label,
            reference,
            sample_rate,
            backend_factory,
            values,
            analysis_options,
            stability_runs,
            termination_tolerance_percent,
            stability_tolerance_percent,
            reference_statistics,
            proven_statistics,
            parameter,
            results,
            on_progress,
        )

    if any(not result.stable for result in results):
        return tuple(results)

    _emit_final_stability_progress(on_progress, preset_label, proven_statistics, results)
    if proven_statistics is None:
        raise RuntimeError("Final stability check failed with optimized timing values")

    return tuple(results)


def _validate_optimizer_settings(
    stability_runs: int,
    termination_tolerance_percent: float,
    stability_tolerance_percent: float,
) -> None:
    if stability_runs < 2:
        raise ValueError("Stability runs must be at least 2")
    if termination_tolerance_percent <= 0:
        raise ValueError("Termination tolerance must be greater than zero")
    if stability_tolerance_percent < 0:
        raise ValueError("Stability tolerance must be zero or greater")


def _optimize_parameter(
    profile: DeviceProfile,
    preset_id: int,
    alternate_preset_id: int,
    preset_label: str,
    reference: np.ndarray,
    sample_rate: int,
    backend_factory: BackendFactory,
    values: dict[str, float],
    analysis_options: AnalysisOptions,
    stability_runs: int,
    termination_tolerance_percent: float,
    stability_tolerance_percent: float,
    reference_statistics: StabilityStatistics | None,
    proven_statistics: StabilityStatistics | None,
    parameter: TimingParameter,
    results: list[ParameterOptimizationResult],
    on_progress: ProgressCallback | None,
) -> StabilityStatistics | None:
    start = values[parameter.name]
    low = parameter.lower_bound(values)
    if start < low:
        raise ValueError(f"{parameter.label} must be at least {low:g} s for optimization")
    state = _initial_optimizer_bounds(start, low, termination_tolerance_percent, proven_statistics)
    _emit_parameter_started(on_progress, parameter, state, preset_label, stability_runs, results)
    if proven_statistics is None:
        _append_unstable_start_result(parameter, state, reference_statistics, results, on_progress)
        return None

    state = _bisect_stable_delay(
        profile,
        preset_id,
        alternate_preset_id,
        preset_label,
        reference,
        sample_rate,
        backend_factory,
        values,
        analysis_options,
        stability_runs,
        stability_tolerance_percent,
        reference_statistics,
        parameter,
        state,
        results,
        on_progress,
    )
    values[parameter.name] = state["best"]
    result = _build_optimization_result(parameter, state, state["best_statistics"])
    results.append(result)
    _emit_parameter_completed(on_progress, parameter, state, results)
    return state["best_statistics"]


def _initial_optimizer_bounds(
    start: float,
    low: float,
    termination_tolerance_percent: float,
    proven_statistics: StabilityStatistics | None,
) -> dict[str, Any]:
    tolerance = abs(start) * termination_tolerance_percent / 100.0
    if tolerance == 0:
        tolerance = termination_tolerance_percent / 1000.0
    return {
        "low": low,
        "high": start,
        "best": start,
        "iterations": 0,
        "tolerance": tolerance,
        "latest_statistics": proven_statistics,
        "best_statistics": proven_statistics,
    }


def _bisect_stable_delay(
    profile: DeviceProfile,
    preset_id: int,
    alternate_preset_id: int,
    preset_label: str,
    reference: np.ndarray,
    sample_rate: int,
    backend_factory: BackendFactory,
    values: dict[str, float],
    analysis_options: AnalysisOptions,
    stability_runs: int,
    stability_tolerance_percent: float,
    reference_statistics: StabilityStatistics | None,
    parameter: TimingParameter,
    state: dict[str, Any],
    results: list[ParameterOptimizationResult],
    on_progress: ProgressCallback | None,
) -> dict[str, Any]:
    while state["high"] - state["low"] > state["tolerance"]:
        candidate = (state["low"] + state["high"]) / 2.0
        stable, statistics = _run_stability_probe(
            profile,
            preset_id,
            alternate_preset_id,
            reference,
            sample_rate,
            backend_factory,
            {**values, parameter.name: candidate},
            analysis_options,
            stability_runs,
            stability_tolerance_percent,
            reference_statistics,
        )
        state = _updated_optimizer_state(state, candidate, stable, statistics)
        _emit_optimizer_progress(
            on_progress, parameter, candidate, stable, state, preset_label, stability_runs, results
        )
    return state


def _run_stability_probe(
    profile: DeviceProfile,
    preset_id: int,
    alternate_preset_id: int,
    reference: np.ndarray,
    sample_rate: int,
    backend_factory: BackendFactory,
    values: dict[str, float],
    analysis_options: AnalysisOptions,
    stability_runs: int,
    stability_tolerance_percent: float,
    reference_statistics: StabilityStatistics | None,
) -> tuple[bool, StabilityStatistics | None]:
    return _is_stable(
        profile,
        preset_id,
        alternate_preset_id,
        reference,
        sample_rate,
        backend_factory,
        values,
        analysis_options,
        stability_runs,
        stability_tolerance_percent,
        reference_statistics,
    )


def _updated_optimizer_state(
    state: dict[str, Any],
    candidate: float,
    stable: bool,
    statistics: StabilityStatistics | None,
) -> dict[str, Any]:
    state = {**state, "iterations": state["iterations"] + 1, "latest_statistics": statistics}
    if stable:
        return {**state, "best": candidate, "high": candidate, "best_statistics": statistics}
    return {**state, "low": candidate}


def _build_optimization_result(
    parameter: TimingParameter,
    state: dict[str, Any],
    statistics: StabilityStatistics | None,
) -> ParameterOptimizationResult:
    return ParameterOptimizationResult(
        parameter, state["best"], True, state["iterations"], statistics
    )


def _append_unstable_start_result(
    parameter: TimingParameter,
    state: dict[str, Any],
    statistics: StabilityStatistics | None,
    results: list[ParameterOptimizationResult],
    on_progress: ProgressCallback | None,
) -> None:
    result = ParameterOptimizationResult(
        parameter, state["high"], False, state["iterations"], statistics
    )
    results.append(result)
    _emit(
        on_progress,
        OptimizationProgress(
            "parameter_completed",
            f"{parameter.label} is unstable at the optimization start value",
            parameter=parameter.name,
            candidate=state["high"],
            stable=False,
            low=state["low"],
            high=state["high"],
            best=state["best"],
            iteration=state["iterations"],
            statistics=statistics,
            results=tuple(results),
        ),
    )


def _emit_parameter_started(
    on_progress: ProgressCallback | None,
    parameter: TimingParameter,
    state: dict[str, Any],
    preset_label: str,
    stability_runs: int,
    results: list[ParameterOptimizationResult],
) -> None:
    _emit(
        on_progress,
        OptimizationProgress(
            "parameter_started",
            (
                f"Investigating {parameter.label} from {state['high']:.6g} s "
                f"on preset {preset_label} using snapshots 1 and 2 "
                f"({stability_runs} stability runs)"
            ),
            parameter=parameter.name,
            low=state["low"],
            high=state["high"],
            best=state["best"],
            iteration=state["iterations"],
            results=tuple(results),
        ),
    )


def _emit_optimizer_progress(
    on_progress: ProgressCallback | None,
    parameter: TimingParameter,
    candidate: float,
    stable: bool,
    state: dict[str, Any],
    preset_label: str,
    stability_runs: int,
    results: list[ParameterOptimizationResult],
) -> None:
    _emit(
        on_progress,
        OptimizationProgress(
            "candidate_completed",
            (
                f"{parameter.label}: {candidate:.6g} s "
                f"{'stable' if stable else 'unstable'} after "
                f"{stability_runs} runs on preset {preset_label}, snapshots 1 and 2"
            ),
            parameter=parameter.name,
            candidate=candidate,
            stable=stable,
            low=state["low"],
            high=state["high"],
            best=state["best"],
            iteration=state["iterations"],
            statistics=state["latest_statistics"],
            results=tuple(results),
        ),
    )


def _emit_parameter_completed(
    on_progress: ProgressCallback | None,
    parameter: TimingParameter,
    state: dict[str, Any],
    results: list[ParameterOptimizationResult],
) -> None:
    _emit(
        on_progress,
        OptimizationProgress(
            "parameter_completed",
            (
                f"{parameter.label}: {state['best']:.6g} s; applying this value "
                "to the remaining parameter checks"
            ),
            parameter=parameter.name,
            candidate=state["best"],
            stable=True,
            low=state["low"],
            high=state["high"],
            best=state["best"],
            iteration=state["iterations"],
            statistics=state["latest_statistics"],
            results=tuple(results),
        ),
    )


def _emit_final_stability_progress(
    on_progress: ProgressCallback | None,
    preset_label: str,
    final_statistics: StabilityStatistics | None,
    results: list[ParameterOptimizationResult],
) -> None:
    _emit(
        on_progress,
        OptimizationProgress(
            "final_stability_started",
            (
                f"Verifying final stability proof on preset {preset_label}, "
                "snapshots 1 and 2, with all optimized values"
            ),
            results=tuple(results),
        ),
    )
    final_stable = final_statistics is not None
    _emit(
        on_progress,
        OptimizationProgress(
            "final_stability_completed",
            (
                "Final stability check passed with optimized timing values"
                if final_stable
                else "Final stability check failed"
            ),
            stable=final_stable,
            statistics=final_statistics,
            results=tuple(results),
        ),
    )


def optimization_results_toml(device: str, results: tuple[ParameterOptimizationResult, ...]) -> str:
    grouped: dict[tuple[str, ...], list[tuple[str, float]]] = {}
    for result in results:
        table = tuple(device if part == "{device}" else part for part in result.parameter.table)
        grouped.setdefault(table, []).append((result.parameter.key, result.value))

    lines: list[str] = []
    for table, items in grouped.items():
        if lines:
            lines.append("")
        lines.append(f"[{'.'.join(table)}]")
        for key, value in items:
            lines.append(f"{key} = {_format_float(value)}")
    return "\n".join(lines)


def alternate_preset_id(preset_id: int) -> int:
    return preset_id + 1 if preset_id < 128 else preset_id - 1


def _is_stable(
    profile: DeviceProfile,
    preset_id: int,
    alternate_preset_id: int,
    reference: np.ndarray,
    sample_rate: int,
    backend_factory: BackendFactory,
    values: dict[str, float],
    analysis_options: AnalysisOptions,
    stability_runs: int,
    stability_tolerance_percent: float,
    reference_statistics: StabilityStatistics | None = None,
) -> tuple[bool, StabilityStatistics | None]:
    measurements = []
    for _ in range(stability_runs):
        try:
            measurements.append(
                _measure_two_snapshots(
                    profile,
                    preset_id,
                    alternate_preset_id,
                    reference,
                    sample_rate,
                    backend_factory(values),
                    _analysis_options(values, analysis_options),
                )
            )
        except MeasurementAnalysisError:
            return False, None
    statistics = _stability_statistics(
        measurements,
        stability_tolerance_percent,
        reference_statistics,
    )
    stable = all(
        deviation <= tolerance
        for deviation, tolerance in (
            (statistics.snapshot1_lufs_max_deviation, statistics.snapshot1_lufs_tolerance),
            (
                statistics.snapshot1_crest_max_deviation,
                statistics.snapshot1_crest_tolerance,
            ),
            (statistics.snapshot2_lufs_max_deviation, statistics.snapshot2_lufs_tolerance),
            (
                statistics.snapshot2_crest_max_deviation,
                statistics.snapshot2_crest_tolerance,
            ),
        )
    )
    return stable, statistics


def _measure_two_snapshots(
    profile: DeviceProfile,
    preset_id: int,
    alternate_preset_id: int,
    reference: np.ndarray,
    sample_rate: int,
    backend: MeasurementBackend,
    analysis_options: AnalysisOptions,
) -> tuple[tuple[float, float], tuple[float, float]]:
    if getattr(profile, "max_snapshot_count", None) == 1:
        raise ValueError(f"{profile.display_name} must support at least two snapshots")

    backend.activate_preset(alternate_preset_id)
    backend.activate_preset(preset_id)
    results = []
    for snapshot in (1, 2):
        backend.reapply_snapshot(snapshot)
        try:
            values = analyze_audio(backend.record(reference), sample_rate, analysis_options)
        except ValueError as exc:
            raise MeasurementAnalysisError(str(exc)) from exc
        results.append((values.short_term_lufs, values.crest_factor_db))
    return results[0], results[1]


def _stability_statistics(
    measurements: list[tuple[tuple[float, float], tuple[float, float]]],
    tolerance_percent: float,
    reference_statistics: StabilityStatistics | None = None,
) -> StabilityStatistics:
    values = np.asarray(measurements, dtype=np.float64)
    means = values.mean(axis=0)
    stds = values.std(axis=0)
    reference_means = (
        means
        if reference_statistics is None
        else np.asarray(
            [
                [
                    reference_statistics.snapshot1_lufs_mean,
                    reference_statistics.snapshot1_crest_mean,
                ],
                [
                    reference_statistics.snapshot2_lufs_mean,
                    reference_statistics.snapshot2_crest_mean,
                ],
            ],
            dtype=np.float64,
        )
    )
    max_deviations = (
        np.max(np.abs(values - means), axis=0)
        if reference_statistics is None
        else np.abs(means - reference_means)
    )
    tolerances = np.maximum(np.abs(reference_means), 1.0) * tolerance_percent / 100.0
    return StabilityStatistics(
        snapshot1_lufs_mean=float(means[0, 0]),
        snapshot1_lufs_std=float(stds[0, 0]),
        snapshot1_crest_mean=float(means[0, 1]),
        snapshot1_crest_std=float(stds[0, 1]),
        snapshot2_lufs_mean=float(means[1, 0]),
        snapshot2_lufs_std=float(stds[1, 0]),
        snapshot2_crest_mean=float(means[1, 1]),
        snapshot2_crest_std=float(stds[1, 1]),
        tolerance_percent=tolerance_percent,
        snapshot1_lufs_tolerance=float(tolerances[0, 0]),
        snapshot1_lufs_max_deviation=float(max_deviations[0, 0]),
        snapshot1_crest_tolerance=float(tolerances[0, 1]),
        snapshot1_crest_max_deviation=float(max_deviations[0, 1]),
        snapshot2_lufs_tolerance=float(tolerances[1, 0]),
        snapshot2_lufs_max_deviation=float(max_deviations[1, 0]),
        snapshot2_crest_tolerance=float(tolerances[1, 1]),
        snapshot2_crest_max_deviation=float(max_deviations[1, 1]),
    )


def _analysis_options(values: dict[str, float], options: AnalysisOptions) -> AnalysisOptions:
    return replace(
        options,
        window_seconds=values["analysis_window"],
        interval_seconds=values["analysis_interval"],
    )


def _format_float(value: float) -> str:
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text if text else "0"


def _emit(callback: ProgressCallback | None, progress: OptimizationProgress) -> None:
    if callback is not None:
        callback(progress)
