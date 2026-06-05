from __future__ import annotations

import numpy as np

from matchpatch.analysis import AnalysisOptions
from matchpatch.devices import get_device_profile
from matchpatch.measurement_optimizer import (
    TIMING_PARAMETERS,
    OptimizationProgress,
    optimization_results_toml,
    optimize_timing_parameters,
)


class ThresholdBackend:
    def __init__(self, offset: float) -> None:
        self.snapshot = 1
        self.run_offset = offset

    def activate_preset(self, preset_id: int) -> None:
        return None

    def reapply_snapshot(self, snapshot: int) -> None:
        self.snapshot = snapshot

    def record(self, reference_audio: np.ndarray) -> np.ndarray:
        gain = 1.0 if self.snapshot == 1 else 0.5
        return reference_audio * (gain + self.run_offset)


class SilentBackend:
    def __init__(self, silent: bool) -> None:
        self.silent = silent

    def activate_preset(self, preset_id: int) -> None:
        return None

    def reapply_snapshot(self, snapshot: int) -> None:
        return None

    def record(self, reference_audio: np.ndarray) -> np.ndarray:
        if self.silent:
            return np.zeros_like(reference_audio)
        return reference_audio


def test_optimize_timing_parameters_bisects_to_lowest_stable_value() -> None:
    reference = np.ones((200, 2), dtype=np.float32) * 0.25
    progress: list[OptimizationProgress] = []

    run_index = 0

    def backend_factory(values: dict[str, float]) -> ThresholdBackend:
        nonlocal run_index
        run_index += 1
        offset = 0.0 if values["measurement_wait"] >= 0.25 else run_index * 0.1
        return ThresholdBackend(offset)

    results = optimize_timing_parameters(
        get_device_profile("helix"),
        1,
        2,
        reference,
        100,
        backend_factory,
        {
            "analysis_window": 0.5,
            "analysis_interval": 0.1,
            "pre_roll": 0.2,
            "post_roll": 0.2,
            "round_trip_latency": 0.0,
            "preset_wait": 0.2,
            "snapshot_wait": 0.2,
            "measurement_wait": 1.0,
        },
        AnalysisOptions(window_seconds=0.5, interval_seconds=0.1),
        stability_runs=2,
        termination_tolerance_percent=10.0,
        stability_tolerance_percent=0.5,
        on_progress=progress.append,
        parameters=(TIMING_PARAMETERS[-1],),
    )

    assert len(results) == 1
    assert results[0].stable
    assert 0.25 <= results[0].value <= 0.35
    assert results[0].statistics is not None
    parameter_completed = next(
        event for event in reversed(progress) if event.kind == "parameter_completed"
    )
    assert progress[-1].kind == "final_stability_completed"
    restored = OptimizationProgress.from_json(parameter_completed.to_json())
    assert restored.results[0].value == results[0].value
    assert restored.results[0].statistics is not None
    assert "measurement_wait_seconds" in optimization_results_toml("helix", results)


def test_optimizer_treats_unanalyzable_candidates_as_unstable() -> None:
    reference = np.ones((200, 2), dtype=np.float32) * 0.25
    progress: list[OptimizationProgress] = []

    def backend_factory(values: dict[str, float]) -> SilentBackend:
        return SilentBackend(values["measurement_wait"] < 0.75)

    results = optimize_timing_parameters(
        get_device_profile("helix"),
        1,
        2,
        reference,
        100,
        backend_factory,
        {
            "analysis_window": 0.5,
            "analysis_interval": 0.1,
            "pre_roll": 0.2,
            "post_roll": 0.2,
            "round_trip_latency": 0.0,
            "preset_wait": 0.2,
            "snapshot_wait": 0.2,
            "measurement_wait": 1.0,
        },
        AnalysisOptions(window_seconds=0.5, interval_seconds=0.1),
        stability_runs=2,
        termination_tolerance_percent=50.0,
        stability_tolerance_percent=0.5,
        on_progress=progress.append,
        parameters=(TIMING_PARAMETERS[-1],),
    )

    unstable_event = next(event for event in progress if event.stable is False)

    assert len(results) == 1
    assert results[0].stable
    assert results[0].value == 1.0
    assert unstable_event.statistics is None
    assert progress[-1].kind == "final_stability_completed"


def test_optimizer_progress_uses_device_preset_display_id() -> None:
    reference = np.ones((200, 2), dtype=np.float32) * 0.25
    progress: list[OptimizationProgress] = []

    results = optimize_timing_parameters(
        get_device_profile("helix"),
        7,
        8,
        reference,
        100,
        lambda values: ThresholdBackend(0.0),
        {
            "analysis_window": 0.5,
            "analysis_interval": 0.1,
            "pre_roll": 0.2,
            "post_roll": 0.2,
            "round_trip_latency": 0.0,
            "preset_wait": 0.2,
            "snapshot_wait": 0.2,
            "measurement_wait": 1.0,
        },
        AnalysisOptions(window_seconds=0.5, interval_seconds=0.1),
        stability_runs=2,
        termination_tolerance_percent=50.0,
        stability_tolerance_percent=0.5,
        on_progress=progress.append,
        parameters=(TIMING_PARAMETERS[-1],),
    )

    assert len(results) == 1
    assert any("preset 02C" in event.message for event in progress)
    assert not any("preset 7" in event.message for event in progress)


def test_optimizer_uses_stable_start_when_configured_value_is_small() -> None:
    reference = np.ones((200, 2), dtype=np.float32) * 0.25

    run_index = 0

    def backend_factory(values: dict[str, float]) -> ThresholdBackend:
        nonlocal run_index
        run_index += 1
        offset = 0.0 if values["measurement_wait"] >= 0.25 else run_index * 0.1
        return ThresholdBackend(offset)

    results = optimize_timing_parameters(
        get_device_profile("helix"),
        1,
        2,
        reference,
        100,
        backend_factory,
        {
            "analysis_window": 0.5,
            "analysis_interval": 0.1,
            "pre_roll": 0.2,
            "post_roll": 0.2,
            "round_trip_latency": 0.0,
            "preset_wait": 0.2,
            "snapshot_wait": 0.2,
            "measurement_wait": 0.05,
        },
        AnalysisOptions(window_seconds=0.5, interval_seconds=0.1),
        stability_runs=2,
        termination_tolerance_percent=10.0,
        stability_tolerance_percent=0.5,
        parameters=(TIMING_PARAMETERS[-1],),
    )

    assert len(results) == 1
    assert results[0].stable
    assert 0.25 <= results[0].value <= 0.35


def test_optimizer_orders_parameters_by_duration_impact() -> None:
    reference = np.ones((200, 2), dtype=np.float32) * 0.25
    progress: list[OptimizationProgress] = []

    def backend_factory(values: dict[str, float]) -> ThresholdBackend:
        return ThresholdBackend(0.0)

    results = optimize_timing_parameters(
        get_device_profile("helix"),
        1,
        2,
        reference,
        100,
        backend_factory,
        {
            "analysis_window": 0.5,
            "analysis_interval": 0.1,
            "pre_roll": 0.2,
            "post_roll": 0.2,
            "round_trip_latency": 0.0,
            "preset_wait": 3.0,
            "snapshot_wait": 0.2,
            "measurement_wait": 1.0,
        },
        AnalysisOptions(window_seconds=0.5, interval_seconds=0.1),
        stability_runs=2,
        termination_tolerance_percent=100.0,
        on_progress=progress.append,
        parameters=(TIMING_PARAMETERS[3], TIMING_PARAMETERS[-1]),
    )

    started = [event.parameter for event in progress if event.kind == "parameter_started"]

    assert started == ["preset_wait", "measurement_wait"]
    assert [result.parameter.name for result in results] == [
        "preset_wait",
        "measurement_wait",
    ]


def test_optimizer_reuses_previous_stability_proof_for_next_parameter() -> None:
    reference = np.ones((200, 2), dtype=np.float32) * 0.25
    active_parameter: str | None = None
    checked_values_by_parameter: dict[str, list[dict[str, float]]] = {}

    def backend_factory(values: dict[str, float]) -> ThresholdBackend:
        if active_parameter is not None:
            checked_values_by_parameter.setdefault(active_parameter, []).append(dict(values))
        return ThresholdBackend(0.0)

    def on_progress(event: OptimizationProgress) -> None:
        nonlocal active_parameter
        if event.kind == "parameter_started":
            active_parameter = event.parameter
        elif event.kind == "parameter_completed":
            active_parameter = None

    optimize_timing_parameters(
        get_device_profile("helix"),
        1,
        2,
        reference,
        100,
        backend_factory,
        {
            "analysis_window": 0.5,
            "analysis_interval": 0.1,
            "pre_roll": 0.2,
            "post_roll": 0.2,
            "round_trip_latency": 0.0,
            "preset_wait": 3.0,
            "snapshot_wait": 0.2,
            "measurement_wait": 1.0,
        },
        AnalysisOptions(window_seconds=0.5, interval_seconds=0.1),
        stability_runs=2,
        termination_tolerance_percent=50.0,
        on_progress=on_progress,
        parameters=(TIMING_PARAMETERS[3], TIMING_PARAMETERS[-1]),
    )

    assert checked_values_by_parameter["measurement_wait"]
    assert all(
        values["measurement_wait"] == 0.5
        for values in checked_values_by_parameter["measurement_wait"][:2]
    )


def test_optimizer_runs_final_stability_check_with_optimized_values() -> None:
    reference = np.ones((200, 2), dtype=np.float32) * 0.25
    progress: list[OptimizationProgress] = []
    factory_values = []

    def backend_factory(values: dict[str, float]) -> ThresholdBackend:
        factory_values.append(dict(values))
        return ThresholdBackend(0.0)

    results = optimize_timing_parameters(
        get_device_profile("helix"),
        1,
        2,
        reference,
        100,
        backend_factory,
        {
            "analysis_window": 0.5,
            "analysis_interval": 0.1,
            "pre_roll": 0.2,
            "post_roll": 0.2,
            "round_trip_latency": 0.0,
            "preset_wait": 0.2,
            "snapshot_wait": 0.2,
            "measurement_wait": 1.0,
        },
        AnalysisOptions(window_seconds=0.5, interval_seconds=0.1),
        stability_runs=2,
        termination_tolerance_percent=100.0,
        on_progress=progress.append,
        parameters=(TIMING_PARAMETERS[-1],),
    )

    final_event = progress[-1]

    assert results[0].parameter.name == "measurement_wait"
    assert final_event.kind == "final_stability_completed"
    assert final_event.stable
    assert len(factory_values) == 2
    assert factory_values[-1]["measurement_wait"] == results[0].value


def test_optimizer_reuses_last_accepted_candidate_for_final_stability() -> None:
    reference = np.ones((200, 2), dtype=np.float32) * 0.25
    progress: list[OptimizationProgress] = []
    factory_calls = 0

    def backend_factory(values: dict[str, float]) -> ThresholdBackend:
        nonlocal factory_calls
        factory_calls += 1
        offset = 0.0 if factory_calls <= 4 else factory_calls * 0.1
        return ThresholdBackend(offset)

    results = optimize_timing_parameters(
        get_device_profile("helix"),
        1,
        2,
        reference,
        100,
        backend_factory,
        {
            "analysis_window": 0.5,
            "analysis_interval": 0.1,
            "pre_roll": 0.2,
            "post_roll": 0.2,
            "round_trip_latency": 0.0,
            "preset_wait": 0.2,
            "snapshot_wait": 0.2,
            "measurement_wait": 1.0,
        },
        AnalysisOptions(window_seconds=0.5, interval_seconds=0.1),
        stability_runs=2,
        termination_tolerance_percent=50.0,
        stability_tolerance_percent=0.5,
        on_progress=progress.append,
        parameters=(TIMING_PARAMETERS[-1],),
    )

    final_event = progress[-1]

    assert results[0].stable
    assert results[0].value == 0.5
    assert final_event.kind == "final_stability_completed"
    assert final_event.stable
    assert final_event.statistics == results[0].statistics
    assert factory_calls == 4


def test_progress_statistics_show_unstable_measurement_spread() -> None:
    reference = np.ones((200, 2), dtype=np.float32) * 0.25
    progress: list[OptimizationProgress] = []

    run_index = 0

    def backend_factory(values: dict[str, float]) -> ThresholdBackend:
        nonlocal run_index
        run_index += 1
        offset = 0.0 if values["measurement_wait"] >= 0.25 else run_index * 0.1
        return ThresholdBackend(offset)

    optimize_timing_parameters(
        get_device_profile("helix"),
        1,
        2,
        reference,
        100,
        backend_factory,
        {
            "analysis_window": 0.5,
            "analysis_interval": 0.1,
            "pre_roll": 0.2,
            "post_roll": 0.2,
            "round_trip_latency": 0.0,
            "preset_wait": 0.2,
            "snapshot_wait": 0.2,
            "measurement_wait": 1.0,
        },
        AnalysisOptions(window_seconds=0.5, interval_seconds=0.1),
        stability_runs=2,
        termination_tolerance_percent=10.0,
        stability_tolerance_percent=0.5,
        on_progress=progress.append,
        parameters=(TIMING_PARAMETERS[-1],),
    )

    unstable_event = next(event for event in progress if event.stable is False)

    assert unstable_event.statistics is not None
    assert unstable_event.statistics.snapshot1_lufs_std > 0


def test_stability_tolerance_percent_controls_equality_detection() -> None:
    reference = np.ones((200, 2), dtype=np.float32) * 0.25
    run_index = 0

    def backend_factory(values: dict[str, float]) -> ThresholdBackend:
        nonlocal run_index
        offset = 0.0001 if run_index % 2 else 0.0
        run_index += 1
        return ThresholdBackend(offset)

    common_kwargs = dict(
        profile=get_device_profile("helix"),
        preset_id=1,
        alternate_preset_id=2,
        reference=reference,
        sample_rate=100,
        backend_factory=backend_factory,
        initial_values={
            "analysis_window": 0.5,
            "analysis_interval": 0.1,
            "pre_roll": 0.2,
            "post_roll": 0.2,
            "round_trip_latency": 0.0,
            "preset_wait": 0.2,
            "snapshot_wait": 0.2,
            "measurement_wait": 1.0,
        },
        analysis_options=AnalysisOptions(window_seconds=0.5, interval_seconds=0.1),
        stability_runs=2,
        termination_tolerance_percent=100.0,
        parameters=(TIMING_PARAMETERS[-1],),
    )

    precise_results = optimize_timing_parameters(
        **common_kwargs,
        stability_tolerance_percent=0.001,
    )
    coarse_results = optimize_timing_parameters(
        **common_kwargs,
        stability_tolerance_percent=0.01,
    )

    assert not precise_results[0].stable
    assert coarse_results[0].stable


def test_optimizer_rejects_mean_drift_from_safe_start_reference() -> None:
    reference = np.ones((200, 2), dtype=np.float32) * 0.25
    progress: list[OptimizationProgress] = []

    def backend_factory(values: dict[str, float]) -> ThresholdBackend:
        offset = 0.1 if values["measurement_wait"] < 0.75 else 0.0
        return ThresholdBackend(offset)

    results = optimize_timing_parameters(
        get_device_profile("helix"),
        1,
        2,
        reference,
        100,
        backend_factory,
        {
            "analysis_window": 0.5,
            "analysis_interval": 0.1,
            "pre_roll": 0.2,
            "post_roll": 0.2,
            "round_trip_latency": 0.0,
            "preset_wait": 0.2,
            "snapshot_wait": 0.2,
            "measurement_wait": 1.0,
        },
        AnalysisOptions(window_seconds=0.5, interval_seconds=0.1),
        stability_runs=2,
        termination_tolerance_percent=50.0,
        stability_tolerance_percent=0.5,
        on_progress=progress.append,
        parameters=(TIMING_PARAMETERS[-1],),
    )

    unstable_event = next(event for event in progress if event.stable is False)

    assert results[0].stable
    assert results[0].value == 1.0
    assert unstable_event.statistics is not None
    assert unstable_event.statistics.snapshot1_lufs_std == 0.0
    assert (
        unstable_event.statistics.snapshot1_lufs_max_deviation
        > unstable_event.statistics.snapshot1_lufs_tolerance
    )


def test_statistics_include_tolerance_values_used_for_stability() -> None:
    reference = np.ones((200, 2), dtype=np.float32) * 0.25
    run_index = 0

    def backend_factory(values: dict[str, float]) -> ThresholdBackend:
        nonlocal run_index
        gain = 1.0 if run_index % 2 else 0.99
        run_index += 1
        return ThresholdBackend(gain - 1.0)

    results = optimize_timing_parameters(
        get_device_profile("helix"),
        1,
        2,
        reference,
        100,
        backend_factory,
        {
            "analysis_window": 0.5,
            "analysis_interval": 0.1,
            "pre_roll": 0.2,
            "post_roll": 0.2,
            "round_trip_latency": 0.0,
            "preset_wait": 0.2,
            "snapshot_wait": 0.2,
            "measurement_wait": 1.0,
        },
        AnalysisOptions(window_seconds=0.5, interval_seconds=0.1),
        stability_runs=2,
        termination_tolerance_percent=100.0,
        stability_tolerance_percent=0.1,
        parameters=(TIMING_PARAMETERS[-1],),
    )

    statistics = results[0].statistics

    assert statistics is not None
    assert not results[0].stable
    assert statistics.snapshot1_lufs_std < 0.1
    assert statistics.tolerance_percent == 0.1
    assert statistics.snapshot1_lufs_max_deviation > statistics.snapshot1_lufs_tolerance


def test_optimized_parameters_exclude_analysis_definition_values() -> None:
    names = {parameter.name for parameter in TIMING_PARAMETERS}

    assert "analysis_window" not in names
    assert "analysis_interval" not in names
