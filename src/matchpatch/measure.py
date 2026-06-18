"""Native Windows measurement worker for MatchPatch audio processors."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any, Protocol, cast

import numpy as np
import soundfile as sf

from matchpatch.analysis import AnalysisOptions, AudioMeasurements, analyze_audio
from matchpatch.config import (
    Config,
    config_value,
    load_config,
)
from matchpatch.device_settings import (
    resolve_device_settings,
    settings_to_audio_routing,
    settings_to_steering_options,
)
from matchpatch.devices import get_device_profile, list_device_profiles
from matchpatch.devices.base import (
    AudioProcessingMode,
    AudioProcessorTransport,
    AudioRouting,
    AudioTransport,
    AudioTransportCapabilities,
    AudioTransportContext,
    AudioTransportFactory,
    DeviceController,
    DeviceProfile,
    OfflineAudioProcessingRequest,
    OfflineAudioTransport,
    PatchFileHandler,
    SteeringOptions,
    validate_snapshot_count,
)
from matchpatch.diagnostics import (
    DiagnosticCheck,
    HardwarePreflightResult,
    diagnostic_check_to_dict,
    preflight_check_to_diagnostic,
    summarize_failed_checks,
)
from matchpatch.measurement_optimizer import (
    TIMING_PARAMETERS,
    OptimizationProgress,
    ParameterOptimizationResult,
    alternate_preset_id,
    optimization_results_toml,
    optimize_timing_parameters,
)
from matchpatch.progress import ProgressEvent

if TYPE_CHECKING:
    from matchpatch.audio import AudioConfig

SnapshotPlan = dict[str, tuple[int, ...]]
SnapshotResult = tuple[float, float] | None
SNAPSHOT_SKIP_SENTINEL = "SKIP"


@dataclass(frozen=True)
class MeasurementTarget:
    preset_id: int
    device_patch: str
    preset_index: int
    preset_total: int
    snapshot_total: int
    snapshots: tuple[int, ...]


class HardwareDiagnosticError(RuntimeError, ValueError):
    """Hardware preflight error that preserves legacy ValueError callers."""


class MeasurementBackend(Protocol):
    def activate_preset(self, preset_id: int) -> None: ...

    def reapply_snapshot(self, snapshot: int) -> None: ...

    def record(self, reference_audio: np.ndarray) -> np.ndarray: ...


PlaybackEnabled = Callable[[], bool]


class BackendAudioTransport:
    def __init__(self, backend: MeasurementBackend) -> None:
        self.backend = backend

    def __enter__(self) -> BackendAudioTransport:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def activate_target(self, target: int) -> None:
        self.backend.activate_preset(target)

    def activate_subdivision(self, subdivision: int) -> None:
        self.backend.reapply_snapshot(subdivision)

    def process(self, reference_audio: np.ndarray) -> np.ndarray:
        return self.backend.record(reference_audio)


class TransportMeasurementBackend:
    def __init__(
        self,
        transport: AudioTransport,
        sample_rate: int | None = None,
        temporary_file_dir: Path | None = None,
    ) -> None:
        self.transport = transport
        self.sample_rate = sample_rate
        self.temporary_file_dir = temporary_file_dir
        self.active_preset_id: int | None = None
        self.active_snapshot: int | None = None

    def activate_preset(self, preset_id: int) -> None:
        self.active_preset_id = preset_id
        self.active_snapshot = None
        self.transport.activate_target(preset_id)

    def reapply_snapshot(self, snapshot: int) -> None:
        self.active_snapshot = snapshot
        self.transport.activate_subdivision(snapshot)

    def record(self, reference_audio: np.ndarray) -> np.ndarray:
        if isinstance(self.transport, OfflineAudioTransport):
            if self.sample_rate is None:
                raise ValueError("Offline transport requires a sample rate")
            if self.active_preset_id is None or self.active_snapshot is None:
                raise RuntimeError("Offline transport target and subdivision must be active")
            return self.transport.process_offline(
                OfflineAudioProcessingRequest(
                    reference_audio=reference_audio,
                    sample_rate=self.sample_rate,
                    target_id=self.active_preset_id,
                    subdivision_id=self.active_snapshot,
                    target_metadata={"preset_id": self.active_preset_id},
                    subdivision_metadata={"snapshot": self.active_snapshot},
                    temporary_file_dir=self.temporary_file_dir,
                )
            )
        return self.transport.process(reference_audio)


class HardwareBackend:
    def __init__(
        self,
        audio_config: AudioConfig,
        controller: DeviceController,
        measurement_wait_seconds: float,
    ) -> None:
        self.audio_config = audio_config
        self.controller = controller
        self.measurement_wait_seconds = measurement_wait_seconds

    def activate_preset(self, preset_id: int) -> None:
        self.controller.activate_preset(preset_id)

    def reapply_snapshot(self, snapshot: int) -> None:
        self.controller.reapply_snapshot(snapshot)
        time.sleep(self.measurement_wait_seconds)

    def record(self, reference_audio: np.ndarray) -> np.ndarray:
        from matchpatch.audio import record_processed_audio

        return record_processed_audio(reference_audio, self.audio_config)


class LoopbackBackend:
    """Simulate an empty processor patch without steering or USB access."""

    def activate_preset(self, preset_id: int) -> None:
        return None

    def reapply_snapshot(self, snapshot: int) -> None:
        return None

    def record(self, reference_audio: np.ndarray) -> np.ndarray:
        return reference_audio.copy()


class SimulatedHardwareBackend:
    """Stateful processor simulation for portable integration tests."""

    def __init__(
        self,
        routing: AudioRouting,
        snapshot_count: int,
        input_mapping: tuple[int, int] | None = None,
        output_mapping: tuple[int, int] | None = None,
        failing_preset_ids: frozenset[int] = frozenset(),
    ) -> None:
        self.routing = routing
        self.snapshot_count = snapshot_count
        self.input_mapping = input_mapping or routing.input_mapping
        self.output_mapping = output_mapping or routing.output_mapping
        self.failing_preset_ids = failing_preset_ids
        self.active_preset_id: int | None = None
        self.active_snapshot: int | None = None
        self.steering_events: list[tuple[str, int]] = []
        self._validate_routing()

    def _validate_routing(self) -> None:
        if self.input_mapping != self.routing.input_mapping:
            raise ValueError(
                f"Simulated processor input mapping must be {self.routing.input_mapping}, "
                f"got {self.input_mapping}"
            )

        if self.output_mapping != self.routing.output_mapping:
            raise ValueError(
                f"Simulated processor output mapping must be {self.routing.output_mapping}, "
                f"got {self.output_mapping}"
            )

    def activate_preset(self, preset_id: int) -> None:
        if preset_id < 1:
            raise ValueError(f"Invalid simulated preset ID: {preset_id}")

        if preset_id in self.failing_preset_ids:
            raise RuntimeError(f"Simulated processor failure for preset {preset_id}")

        self.active_preset_id = preset_id
        self.active_snapshot = None
        self.steering_events.append(("preset", preset_id))

    def reapply_snapshot(self, snapshot: int) -> None:
        if self.active_preset_id is None:
            raise RuntimeError("Simulated processor preset is not active")

        if snapshot < 1 or snapshot > self.snapshot_count:
            raise ValueError(f"Invalid simulated snapshot: {snapshot}")

        self.steering_events.append(("snapshot", snapshot))
        self.active_snapshot = snapshot

    def record(self, reference_audio: np.ndarray) -> np.ndarray:
        if self.active_preset_id is None or self.active_snapshot is None:
            raise RuntimeError("Simulated processor preset and snapshot must be active")

        gain_db = self._gain_db(self.active_preset_id, self.active_snapshot)
        processed = reference_audio.astype(np.float64, copy=True) * 10.0 ** (gain_db / 20.0)

        if self.active_snapshot % 2 == 0:
            processed = np.tanh(processed * 2.0) / 2.0

        return processed

    @staticmethod
    def _gain_db(preset_id: int, snapshot: int) -> float:
        return float(((preset_id - 1) % 5 - 2) * 2 + (snapshot - 1))


class LoopbackTransportFactory:
    capabilities = AudioTransportCapabilities(mode="loopback")

    def supports(self, mode: AudioProcessingMode, settings: Mapping[str, object]) -> bool:  # noqa: ARG002
        return mode == self.capabilities.mode

    def create(self, context: AudioTransportContext) -> AudioProcessorTransport:  # noqa: ARG002
        return BackendAudioTransport(LoopbackBackend())


class SimulatedTransportFactory:
    capabilities = AudioTransportCapabilities(mode="simulated")

    def supports(self, mode: AudioProcessingMode, settings: Mapping[str, object]) -> bool:  # noqa: ARG002
        return mode == self.capabilities.mode

    def create(self, context: AudioTransportContext) -> AudioProcessorTransport:
        return BackendAudioTransport(
            SimulatedHardwareBackend(
                context.audio_routing,
                context.snapshot_count,
                _channel_mapping_setting(context.settings, "input_mapping"),
                _channel_mapping_setting(context.settings, "output_mapping"),
                context.failing_preset_ids,
            )
        )


class HardwareTransportFactory:
    capabilities = AudioTransportCapabilities(mode="hardware")

    def supports(self, mode: AudioProcessingMode, settings: Mapping[str, object]) -> bool:  # noqa: ARG002
        return mode == self.capabilities.mode

    def create(self, context: AudioTransportContext) -> AudioProcessorTransport:
        if context.audio_config is None or context.controller is None:
            raise ValueError("Hardware transport requires audio configuration and controller")
        return BackendAudioTransport(
            HardwareBackend(
                cast("AudioConfig", context.audio_config),
                context.controller,
                context.timing_values.get(
                    "measurement_wait",
                    context.steering_options.measurement_wait_seconds,
                ),
            )
        )


def parse_int_list(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def parse_channel_mapping(value: str) -> tuple[int, int]:
    channels = tuple(parse_int_list(value))

    if len(channels) != 2 or any(channel < 1 for channel in channels):
        raise argparse.ArgumentTypeError("Channel mapping must contain two positive IDs")

    return channels[0], channels[1]


def load_reference_audio(path: Path, sample_rate: int) -> np.ndarray:
    audio, actual_rate = sf.read(path, dtype="float32", always_2d=True)

    if actual_rate != sample_rate:
        raise ValueError(f"Reference DI sample rate is {actual_rate}, expected {sample_rate}")

    if audio.shape[1] < 2:
        audio = np.repeat(audio, 2, axis=1)
    elif audio.shape[1] > 2:
        audio = audio[:, :2]

    return audio


def csv_fields(snapshot_count: int) -> list[str]:
    return [
        "Preset",
        "DevicePatch",
        *(f"LUFS{snapshot}" for snapshot in range(1, snapshot_count + 1)),
        *(f"CrestFactor{snapshot}" for snapshot in range(1, snapshot_count + 1)),
    ]


def append_result_row(
    writer: csv.DictWriter,
    preset_id: int,
    device_patch: str,
    snapshot_count: int,
    results: list[SnapshotResult] | dict[int, SnapshotResult] | None,
) -> None:
    row: dict[str, str | int | float] = {
        "Preset": preset_id,
        "DevicePatch": device_patch,
    }

    for snapshot in range(1, snapshot_count + 1):
        if results is None:
            row[f"LUFS{snapshot}"] = "ERROR"
            row[f"CrestFactor{snapshot}"] = "ERROR"
        elif isinstance(results, dict) and snapshot not in results:
            row[f"LUFS{snapshot}"] = SNAPSHOT_SKIP_SENTINEL
            row[f"CrestFactor{snapshot}"] = SNAPSHOT_SKIP_SENTINEL
        else:
            result = results[snapshot] if isinstance(results, dict) else results[snapshot - 1]
            if result is None:
                row[f"LUFS{snapshot}"] = "ERROR"
                row[f"CrestFactor{snapshot}"] = "ERROR"
            else:
                lufs, crest = result
                row[f"LUFS{snapshot}"] = lufs
                row[f"CrestFactor{snapshot}"] = crest

    writer.writerow(row)


def measure_presets(
    profile: DeviceProfile,
    preset_ids: list[int],
    csv_path: Path,
    reference: np.ndarray,
    sample_rate: int,
    backend: MeasurementBackend,
    *,
    snapshot_count: int | None = None,
    analysis_options: AnalysisOptions = AnalysisOptions(),
    on_progress: Callable[[ProgressEvent], None] | None = None,
    log_output: bool = True,
    play_recorded_output: bool | PlaybackEnabled = False,
    recorded_output_dir: Path | None = None,
    snapshot_plan: SnapshotPlan | None = None,
) -> None:
    measured_snapshots = (
        snapshot_count if snapshot_count is not None else getattr(profile, "snapshot_count", 4)
    )
    validate_snapshot_count(profile, measured_snapshots)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    handler = profile.create_patch_file_handler(Path.cwd())
    _emit_progress(
        on_progress,
        ProgressEvent("measurement_preparation", message="Analyzing reference DI loudness..."),
    )
    reference_lufs = analyze_audio(reference, sample_rate, analysis_options).short_term_lufs
    _emit_progress(
        on_progress,
        ProgressEvent("reference_loudness", reference_lufs=reference_lufs),
    )

    with csv_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=csv_fields(measured_snapshots))
        writer.writeheader()

        for target in _iter_measurement_targets(
            handler,
            preset_ids,
            snapshot_plan,
            measured_snapshots,
        ):
            _emit_preset_started(on_progress, target)
            _log_preset_started(profile, target, log_output)
            try:
                backend.activate_preset(target.preset_id)
                results = {
                    snapshot: _measure_snapshot_target(
                        profile,
                        backend,
                        target,
                        snapshot,
                        reference,
                        sample_rate,
                        analysis_options,
                        reference_lufs,
                        on_progress,
                        log_output,
                        play_recorded_output,
                        recorded_output_dir,
                    )
                    for snapshot in target.snapshots
                }
                _write_measurement_row(writer, target, results)

            except Exception as exc:
                _emit_preset_failure(profile, target, exc, on_progress, log_output)
                _write_measurement_row(writer, target, None)

            csv_file.flush()
            _emit_preset_completed(on_progress, target)

    _emit_progress(on_progress, ProgressEvent("measurement_completed"))


def _iter_measurement_targets(
    handler: PatchFileHandler,
    preset_ids: list[int],
    snapshot_plan: SnapshotPlan | None,
    snapshot_count: int,
) -> tuple[MeasurementTarget, ...]:
    return tuple(
        MeasurementTarget(
            preset_id=preset_id,
            device_patch=device_patch,
            preset_index=preset_index,
            preset_total=len(preset_ids),
            snapshot_total=snapshot_count,
            snapshots=_snapshots_to_measure(
                snapshot_plan,
                device_patch,
                snapshot_count,
            ),
        )
        for preset_index, preset_id in enumerate(preset_ids, start=1)
        for device_patch in (handler.format_patch_id(preset_id),)
    )


def _measure_snapshot_target(
    profile: DeviceProfile,
    backend: MeasurementBackend,
    target: MeasurementTarget,
    snapshot: int,
    reference: np.ndarray,
    sample_rate: int,
    analysis_options: AnalysisOptions,
    reference_lufs: float,
    on_progress: Callable[[ProgressEvent], None] | None,
    log_output: bool,
    play_recorded_output: bool | PlaybackEnabled,
    recorded_output_dir: Path | None,
) -> SnapshotResult:
    _emit_snapshot_started(on_progress, target, snapshot)
    try:
        values = _record_and_analyze_snapshot(
            backend,
            target,
            snapshot,
            reference,
            sample_rate,
            analysis_options,
            on_progress,
            play_recorded_output,
            recorded_output_dir,
        )
    except Exception as exc:  # noqa: BLE001
        _emit_measurement_failure(profile, target, snapshot, exc, on_progress, log_output)
        return None

    _emit_snapshot_completed(on_progress, target, snapshot, reference_lufs, values)
    _log_snapshot_completed(snapshot, values, log_output)
    return values.short_term_lufs, values.crest_factor_db


def _record_and_analyze_snapshot(
    backend: MeasurementBackend,
    target: MeasurementTarget,
    snapshot: int,
    reference: np.ndarray,
    sample_rate: int,
    analysis_options: AnalysisOptions,
    on_progress: Callable[[ProgressEvent], None] | None,
    play_recorded_output: bool | PlaybackEnabled,
    recorded_output_dir: Path | None,
) -> AudioMeasurements:
    backend.reapply_snapshot(snapshot)
    recorded = backend.record(reference)
    _write_recorded_snapshot(
        recorded, recorded_output_dir, target, snapshot, sample_rate, on_progress
    )
    if _playback_enabled(play_recorded_output):
        _play_audio(recorded, sample_rate)
    return analyze_audio(recorded, sample_rate, analysis_options)


def _write_recorded_snapshot(
    recorded: np.ndarray,
    recorded_output_dir: Path | None,
    target: MeasurementTarget,
    snapshot: int,
    sample_rate: int,
    on_progress: Callable[[ProgressEvent], None] | None,
) -> None:
    recorded_path = _recorded_output_path(recorded_output_dir, target.device_patch, snapshot)
    if recorded_path is None:
        return
    recorded_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(recorded_path, recorded, sample_rate)
    _emit_progress(
        on_progress,
        ProgressEvent(
            "snapshot_recorded",
            preset_id=target.preset_id,
            device_patch=target.device_patch,
            preset_index=target.preset_index,
            preset_total=target.preset_total,
            snapshot=snapshot,
            snapshot_total=target.snapshot_total,
            path=str(recorded_path),
        ),
    )


def _write_measurement_row(
    writer: csv.DictWriter,
    target: MeasurementTarget,
    results: dict[int, SnapshotResult] | None,
) -> None:
    append_result_row(
        writer,
        target.preset_id,
        target.device_patch,
        target.snapshot_total,
        results,
    )


def _emit_preset_started(
    on_progress: Callable[[ProgressEvent], None] | None,
    target: MeasurementTarget,
) -> None:
    _emit_progress(on_progress, _target_event("preset_started", target))


def _emit_preset_completed(
    on_progress: Callable[[ProgressEvent], None] | None,
    target: MeasurementTarget,
) -> None:
    _emit_progress(on_progress, _target_event("preset_completed", target))


def _emit_snapshot_started(
    on_progress: Callable[[ProgressEvent], None] | None,
    target: MeasurementTarget,
    snapshot: int,
) -> None:
    _emit_progress(on_progress, _target_event("snapshot_started", target, snapshot=snapshot))


def _emit_snapshot_completed(
    on_progress: Callable[[ProgressEvent], None] | None,
    target: MeasurementTarget,
    snapshot: int,
    reference_lufs: float,
    values: AudioMeasurements,
) -> None:
    _emit_progress(
        on_progress,
        _target_event(
            "snapshot_completed",
            target,
            snapshot=snapshot,
            reference_lufs=reference_lufs,
            lufs=values.short_term_lufs,
            crest_factor_db=values.crest_factor_db,
        ),
    )


def _emit_measurement_failure(
    profile: DeviceProfile,
    target: MeasurementTarget,
    snapshot: int,
    exc: Exception,
    on_progress: Callable[[ProgressEvent], None] | None,
    log_output: bool,
) -> None:
    _emit_progress(
        on_progress,
        _target_event("snapshot_failed", target, message=str(exc), snapshot=snapshot),
    )
    if log_output:
        print(
            f"[ERROR] {profile.name}:{target.device_patch} snapshot {snapshot}: {exc}",
            file=sys.stderr,
            flush=True,
        )


def _emit_preset_failure(
    profile: DeviceProfile,
    target: MeasurementTarget,
    exc: Exception,
    on_progress: Callable[[ProgressEvent], None] | None,
    log_output: bool,
) -> None:
    _emit_progress(on_progress, _target_event("preset_failed", target, message=str(exc)))
    if log_output:
        print(
            f"[ERROR] {profile.name}:{target.device_patch}: {exc}",
            file=sys.stderr,
            flush=True,
        )


def _target_event(
    kind: str,
    target: MeasurementTarget,
    *,
    message: str | None = None,
    snapshot: int | None = None,
    reference_lufs: float | None = None,
    lufs: float | None = None,
    crest_factor_db: float | None = None,
    path: str | None = None,
) -> ProgressEvent:
    return ProgressEvent(
        kind,
        message=message,
        preset_id=target.preset_id,
        device_patch=target.device_patch,
        preset_index=target.preset_index,
        preset_total=target.preset_total,
        snapshot=snapshot,
        snapshot_total=target.snapshot_total,
        reference_lufs=reference_lufs,
        lufs=lufs,
        crest_factor_db=crest_factor_db,
        path=path,
    )


def _log_preset_started(
    profile: DeviceProfile,
    target: MeasurementTarget,
    log_output: bool,
) -> None:
    if log_output:
        print(f"[MEASURE] {profile.name}:{target.device_patch}", flush=True)


def _log_snapshot_completed(snapshot: int, values: AudioMeasurements, log_output: bool) -> None:
    if log_output:
        print(
            f"  snapshot {snapshot}: "
            f"{values.short_term_lufs:.3f} LUFS, "
            f"{values.crest_factor_db:.3f} dB crest",
            flush=True,
        )


def _snapshots_to_measure(
    snapshot_plan: SnapshotPlan | None,
    device_patch: str,
    snapshot_count: int,
) -> tuple[int, ...]:
    if snapshot_plan is None:
        return tuple(range(1, snapshot_count + 1))

    snapshots = snapshot_plan.get(device_patch.upper(), ())
    return tuple(snapshot for snapshot in snapshots if 1 <= snapshot <= snapshot_count)


def parse_snapshot_plan(value: str | None) -> SnapshotPlan | None:
    if not value:
        return None

    plan: SnapshotPlan = {}
    for chunk in value.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            raise argparse.ArgumentTypeError("Snapshot plan entries must be PATCH=1,2")
        patch, snapshots_text = chunk.split("=", 1)
        patch = patch.strip().upper()
        if not patch:
            raise argparse.ArgumentTypeError("Snapshot plan patch IDs must not be empty")
        try:
            snapshots = tuple(parse_int_list(snapshots_text))
        except ValueError as exc:
            raise argparse.ArgumentTypeError("Snapshot plan snapshots must be integers") from exc
        if not snapshots or any(snapshot < 1 for snapshot in snapshots):
            raise argparse.ArgumentTypeError("Snapshot plan snapshots must be positive integers")
        plan[patch] = snapshots
    return plan or None


def _recorded_output_path(
    recorded_output_dir: Path | None,
    device_patch: str,
    snapshot: int,
) -> Path | None:
    if recorded_output_dir is None:
        return None
    safe_patch = re.sub(r"[^A-Za-z0-9_-]+", "_", device_patch).strip("_") or "preset"
    return recorded_output_dir / f"{safe_patch}_snapshot_{snapshot}.wav"


def _playback_enabled(value: bool | PlaybackEnabled) -> bool:
    return value() if callable(value) else bool(value)


def _play_audio(audio: np.ndarray, sample_rate: int) -> None:
    from matchpatch.audio import play_audio

    play_audio(audio, sample_rate)


def _playback_toggle(path: str | None, fallback: bool = False) -> PlaybackEnabled:
    if not path:
        return lambda: fallback

    toggle_path = Path(path)

    def enabled() -> bool:
        try:
            return toggle_path.read_text(encoding="utf-8").strip() in {"1", "true", "yes", "on"}
        except OSError:
            return fallback

    return enabled


class PlaybackBackend:
    def __init__(
        self,
        backend: MeasurementBackend,
        sample_rate: int,
        play_recorded_output: bool | PlaybackEnabled,
    ) -> None:
        self.backend = backend
        self.sample_rate = sample_rate
        self.play_recorded_output = play_recorded_output

    def activate_preset(self, preset_id: int) -> None:
        self.backend.activate_preset(preset_id)

    def reapply_snapshot(self, snapshot: int) -> None:
        self.backend.reapply_snapshot(snapshot)

    def record(self, reference_audio: np.ndarray) -> np.ndarray:
        recorded = self.backend.record(reference_audio)
        if _playback_enabled(self.play_recorded_output):
            _play_audio(recorded, self.sample_rate)
        return recorded


def _emit_progress(
    callback: Callable[[ProgressEvent], None] | None,
    event: ProgressEvent,
) -> None:
    if callback is not None:
        callback(event)


def resolve_audio_config(args: argparse.Namespace, profile: DeviceProfile) -> AudioConfig:
    from matchpatch.audio import AudioConfig

    settings = getattr(args, "device_settings", None) or resolve_device_settings(profile, {}, args)
    routing = settings_to_audio_routing(profile, settings)
    config = AudioConfig(
        device=routing.device,
        sample_rate=routing.sample_rate,
        input_mapping=routing.input_mapping,
        output_mapping=routing.output_mapping,
        blocksize=cast("int", settings.get("blocksize", getattr(args, "blocksize", 0) or 0)),
        pre_roll_seconds=getattr(args, "pre_roll", 0.2),
        post_roll_seconds=getattr(args, "post_roll", 0.1),
        round_trip_latency_seconds=getattr(args, "round_trip_latency", 0.02),
    )

    if (
        min(
            config.pre_roll_seconds,
            config.post_roll_seconds,
            config.round_trip_latency_seconds,
        )
        < 0
    ):
        raise ValueError("Audio pre-roll, post-roll, and round-trip latency must not be negative")

    if config.round_trip_latency_seconds > config.post_roll_seconds:
        raise ValueError("Audio post-roll must be at least as long as round-trip latency")

    return config


def resolve_steering_options(
    args: argparse.Namespace,
    profile: DeviceProfile,
) -> SteeringOptions:
    return settings_to_steering_options(
        profile,
        getattr(args, "device_settings", None) or resolve_device_settings(profile, {}, args),
    )


def _builtin_audio_transport_factories() -> tuple[AudioTransportFactory, ...]:
    return (
        HardwareTransportFactory(),
        LoopbackTransportFactory(),
        SimulatedTransportFactory(),
    )


def _audio_transport_factories(profile: DeviceProfile) -> tuple[AudioTransportFactory, ...]:
    profile_factories = getattr(profile, "audio_transport_factories", lambda: ())()
    return (*profile_factories, *_builtin_audio_transport_factories())


def _backend_mode(backend: str) -> AudioProcessingMode:
    if backend not in {"hardware", "loopback", "simulated", "offline"}:
        raise ValueError(f"Unknown measurement backend: {backend}")
    return cast("AudioProcessingMode", backend)


def _transport_settings(
    args: argparse.Namespace,
    profile: DeviceProfile,
) -> Mapping[str, object]:
    return getattr(args, "device_settings", None) or resolve_device_settings(profile, {}, args)


def _select_audio_transport_factory(
    profile: DeviceProfile,
    mode: AudioProcessingMode,
    settings: Mapping[str, object],
) -> AudioTransportFactory:
    _validate_profile_backend_support(profile, mode)
    for factory in _audio_transport_factories(profile):
        if factory.supports(mode, settings):
            return factory
    if mode == "offline":
        raise NotImplementedError(
            "The offline measurement backend is not implemented yet; "
            "enable a device-provided offline audio transport factory"
        )
    raise ValueError(
        f"Backend {mode!r} is supported by {profile.display_name}, "
        "but no audio transport factory is available"
    )


def _validate_profile_backend_support(profile: DeviceProfile, mode: AudioProcessingMode) -> None:
    supported_backends = profile.measurement_backends()
    if mode not in supported_backends:
        supported = ", ".join(supported_backends)
        raise ValueError(
            f"Backend {mode!r} is not supported by {profile.display_name}; "
            f"choose one of: {supported}"
        )


def _transport_context(
    args: argparse.Namespace,
    profile: DeviceProfile,
    mode: AudioProcessingMode,
    settings: Mapping[str, object],
    sample_rate: int,
    snapshot_count: int,
    *,
    audio_config: object | None = None,
    controller: DeviceController | None = None,
    timing_values: Mapping[str, float] | None = None,
) -> AudioTransportContext:
    temporary_file_dir = getattr(args, "temporary_file_dir", None)
    return AudioTransportContext(
        profile=profile,
        mode=mode,
        settings=settings,
        audio_routing=settings_to_audio_routing(profile, settings),
        steering_options=resolve_steering_options(args, profile),
        sample_rate=sample_rate,
        snapshot_count=snapshot_count,
        audio_config=audio_config,
        controller=controller,
        temporary_file_dir=Path(temporary_file_dir) if temporary_file_dir else None,
        failing_preset_ids=frozenset(getattr(args, "simulate_fail_presets", ())),
        timing_values=timing_values or {},
    )


def _channel_mapping_setting(
    settings: Mapping[str, object],
    name: str,
) -> tuple[int, int] | None:
    value = settings.get(name)
    if value is None:
        return None
    channels = tuple(cast("tuple[int, int] | list[int]", value))
    if len(channels) != 2:
        raise ValueError(f"{name} must contain exactly two channels")
    return channels[0], channels[1]


def measure(args: argparse.Namespace) -> None:
    profile = get_device_profile(args.device)
    mode = _backend_mode(args.backend)
    settings = _transport_settings(args, profile)
    factory = _select_audio_transport_factory(profile, mode, settings)
    routing = settings_to_audio_routing(profile, settings)
    sample_rate = routing.sample_rate
    on_progress = getattr(args, "on_progress", None)
    _emit_progress(
        on_progress,
        ProgressEvent("measurement_preparation", message="Loading reference DI audio..."),
    )
    reference = load_reference_audio(Path(args.reference_di), sample_rate)
    requested_snapshot_count = getattr(args, "snapshot_count", None)
    snapshot_count = (
        requested_snapshot_count
        if requested_snapshot_count is not None
        else getattr(profile, "snapshot_count", 4)
    )
    analysis_options = getattr(args, "analysis_options", AnalysisOptions())
    log_output = not getattr(args, "progress_jsonl", False)
    play_recorded_output = _playback_toggle(
        getattr(args, "playback_toggle_file", None),
        getattr(args, "play_recorded_output", False),
    )
    recorded_output_dir = (
        Path(args.recordings_dir) if getattr(args, "recordings_dir", None) else None
    )
    snapshot_plan = getattr(args, "snapshot_plan", None)
    measure_kwargs = {
        "snapshot_count": snapshot_count,
        "analysis_options": analysis_options,
        "on_progress": on_progress,
        "log_output": log_output,
        "play_recorded_output": play_recorded_output,
        "recorded_output_dir": recorded_output_dir,
        "snapshot_plan": snapshot_plan,
    }

    if mode != "hardware":
        context = _transport_context(args, profile, mode, settings, sample_rate, snapshot_count)
        with factory.create(context) as transport:
            measure_presets(
                profile,
                args.preset_ids,
                Path(args.csv),
                reference,
                sample_rate,
                TransportMeasurementBackend(transport, sample_rate, context.temporary_file_dir),
                **measure_kwargs,
            )
        return

    from matchpatch.audio import prepare_audio_config

    _emit_progress(
        on_progress,
        ProgressEvent(
            "measurement_preparation", message="Resolving and validating audio device..."
        ),
    )
    audio_config = prepare_audio_config(resolve_audio_config(args, profile))
    steering_options = resolve_steering_options(args, profile)

    _emit_progress(
        on_progress,
        ProgressEvent("measurement_preparation", message="Opening processor MIDI output..."),
    )
    with profile.create_controller(steering_options) as controller:
        context = _transport_context(
            args,
            profile,
            mode,
            settings,
            sample_rate,
            snapshot_count,
            audio_config=audio_config,
            controller=controller,
        )
        with factory.create(context) as transport:
            measure_presets(
                profile,
                args.preset_ids,
                Path(args.csv),
                reference,
                sample_rate,
                TransportMeasurementBackend(transport, sample_rate, context.temporary_file_dir),
                **measure_kwargs,
            )


def optimize_measurement_timing(args: argparse.Namespace) -> None:
    profile = get_device_profile(args.device)
    mode = _backend_mode(args.backend)
    settings = _transport_settings(args, profile)
    factory = _select_audio_transport_factory(profile, mode, settings)
    routing = settings_to_audio_routing(profile, settings)
    sample_rate = routing.sample_rate
    reference = load_reference_audio(Path(args.reference_di), sample_rate)
    initial_values = _timing_values(args)
    valid_parameter_names = {parameter.name for parameter in TIMING_PARAMETERS}
    pinned_names = tuple(dict.fromkeys(getattr(args, "pinned_parameter", ())))
    invalid_pins = sorted(set(pinned_names) - valid_parameter_names)
    if invalid_pins:
        raise ValueError(f"Unknown pinned timing parameter: {', '.join(invalid_pins)}")
    pinned_parameters = tuple(
        parameter for parameter in TIMING_PARAMETERS if parameter.name in pinned_names
    )
    optimization_parameters = tuple(
        parameter for parameter in TIMING_PARAMETERS if parameter.name not in pinned_names
    )
    pinned_results = tuple(
        ParameterOptimizationResult(parameter, initial_values[parameter.name], True, 0)
        for parameter in pinned_parameters
    )
    alternate_id = (
        args.alternate_preset_id
        if args.alternate_preset_id is not None
        else alternate_preset_id(args.preset_id)
    )

    on_progress = getattr(args, "on_optimization_progress", None)
    analysis_options = getattr(args, "analysis_options", AnalysisOptions())
    play_recorded_output = _playback_toggle(
        getattr(args, "playback_toggle_file", None),
        getattr(args, "play_recorded_output", False),
    )

    if mode == "hardware":
        from matchpatch.audio import prepare_audio_config

        audio_config = prepare_audio_config(resolve_audio_config(args, profile))
        steering_options = resolve_steering_options(args, profile)

        with profile.create_controller(steering_options) as controller:

            def hardware_backend(values: dict[str, float]) -> PlaybackBackend:
                if hasattr(controller, "options"):
                    controller_any: Any = controller
                    controller_any.options = replace(
                        steering_options,
                        preset_wait_seconds=values["preset_wait"],
                        snapshot_wait_seconds=values["snapshot_wait"],
                    )
                context = _transport_context(
                    args,
                    profile,
                    mode,
                    settings,
                    sample_rate,
                    max(2, getattr(profile, "snapshot_count", 4)),
                    audio_config=replace(
                        audio_config,
                        pre_roll_seconds=values["pre_roll"],
                        post_roll_seconds=values["post_roll"],
                        round_trip_latency_seconds=values["round_trip_latency"],
                    ),
                    controller=controller,
                    timing_values=values,
                )
                return PlaybackBackend(
                    TransportMeasurementBackend(
                        factory.create(context),
                        sample_rate,
                        context.temporary_file_dir,
                    ),
                    sample_rate,
                    play_recorded_output,
                )

            results = optimize_timing_parameters(
                profile,
                args.preset_id,
                alternate_id,
                reference,
                sample_rate,
                hardware_backend,
                initial_values,
                analysis_options,
                stability_runs=args.stability_runs,
                termination_tolerance_percent=args.termination_tolerance,
                stability_tolerance_percent=args.stability_tolerance,
                on_progress=on_progress,
                parameters=optimization_parameters,
            )
    else:

        def transport_backend(values: dict[str, float]) -> PlaybackBackend:
            context = _transport_context(
                args,
                profile,
                mode,
                settings,
                sample_rate,
                max(2, getattr(profile, "snapshot_count", 4)),
                timing_values=values,
            )
            return PlaybackBackend(
                TransportMeasurementBackend(
                    factory.create(context),
                    sample_rate,
                    context.temporary_file_dir,
                ),
                sample_rate,
                play_recorded_output,
            )

        results = optimize_timing_parameters(
            profile,
            args.preset_id,
            alternate_id,
            reference,
            sample_rate,
            transport_backend,
            initial_values,
            analysis_options,
            stability_runs=args.stability_runs,
            termination_tolerance_percent=args.termination_tolerance,
            stability_tolerance_percent=args.stability_tolerance,
            on_progress=on_progress,
            parameters=optimization_parameters,
        )

    result_by_name = {result.parameter.name: result for result in (*pinned_results, *results)}
    results = tuple(
        result_by_name[parameter.name]
        for parameter in TIMING_PARAMETERS
        if parameter.name in result_by_name
    )
    toml_text = optimization_results_toml(args.device, results)
    if on_progress is not None:
        on_progress(
            OptimizationProgress(
                "completed",
                "Timing optimization completed",
                result_toml=toml_text,
                results=results,
            )
        )
    else:
        print(toml_text, flush=True)


def _timing_values(args: argparse.Namespace) -> dict[str, float]:
    return {
        "analysis_window": args.analysis_options.window_seconds,
        "analysis_interval": args.analysis_options.interval_seconds,
        "pre_roll": args.pre_roll,
        "post_roll": args.post_roll,
        "round_trip_latency": args.round_trip_latency,
        "preset_wait": args.preset_wait,
        "snapshot_wait": args.snapshot_wait,
        "measurement_wait": args.measurement_wait,
    }


def check_hardware(args: argparse.Namespace) -> None:
    """Validate that configured processor audio and steering endpoints are present."""
    checks = collect_hardware_diagnostics(args)
    if any(check.status == "fail" for check in checks):
        raise HardwareDiagnosticError(summarize_failed_checks(checks))


def collect_hardware_diagnostics(args: argparse.Namespace) -> list[DiagnosticCheck]:
    """Collect structured hardware diagnostics without changing endpoints."""
    checks: list[DiagnosticCheck] = []
    backend = getattr(args, "backend", "hardware")
    profile: DeviceProfile | None = None

    try:
        profile = get_device_profile(args.device)
    except Exception as exc:  # noqa: BLE001
        checks.append(
            DiagnosticCheck(
                "device_profile",
                "fail",
                str(exc),
                f"device={args.device}; backend={backend}",
            )
        )
        return checks

    checks.append(
        DiagnosticCheck(
            "device_profile",
            "pass",
            f"Loaded {profile.display_name}",
            f"device={profile.name}; display_name={profile.display_name}; backend={backend}",
        )
    )

    try:
        from matchpatch.audio import validate_audio_device_available

        audio_config = resolve_audio_config(args, profile)
        checked_audio_config = validate_audio_device_available(audio_config)
    except Exception as exc:  # noqa: BLE001
        checks.append(
            DiagnosticCheck(
                "audio_device",
                "fail",
                str(exc),
                _diagnostic_detail(
                    query=getattr(args, "audio_device", None),
                    sample_rate=getattr(args, "sample_rate", None),
                    input_mapping=getattr(args, "input_mapping", None),
                    output_mapping=getattr(args, "output_mapping", None),
                    backend=backend,
                ),
            )
        )
    else:
        checks.append(
            DiagnosticCheck(
                "audio_device",
                "pass",
                "Audio device is available",
                _diagnostic_detail(
                    query=getattr(args, "audio_device", None),
                    device=checked_audio_config.device,
                    sample_rate=checked_audio_config.sample_rate,
                    input_mapping=checked_audio_config.input_mapping,
                    output_mapping=checked_audio_config.output_mapping,
                    blocksize=checked_audio_config.blocksize,
                    backend=backend,
                ),
            )
        )

    try:
        steering_options = resolve_steering_options(args, profile)
        midi_outputs = _midi_output_names()
        matched_outputs = _matching_steering_outputs(midi_outputs, steering_options.output)
        matched_output = _validate_steering_output_available(
            steering_options,
            matched_outputs=matched_outputs,
        )
    except Exception as exc:  # noqa: BLE001
        midi_outputs = locals().get("midi_outputs")
        matched_outputs = locals().get("matched_outputs")
        checks.append(
            DiagnosticCheck(
                "midi_output",
                "fail",
                str(exc),
                _diagnostic_detail(
                    query=getattr(args, "steering_output", None),
                    channel=getattr(args, "steering_channel", None),
                    output_count=len(midi_outputs) if isinstance(midi_outputs, list) else None,
                    match_count=(
                        len(matched_outputs) if isinstance(matched_outputs, list) else None
                    ),
                    matched_outputs=(
                        matched_outputs if isinstance(matched_outputs, list) else None
                    ),
                ),
            )
        )
    else:
        checks.append(
            DiagnosticCheck(
                "midi_output",
                "pass",
                "MIDI steering output is available",
                _diagnostic_detail(
                    query=steering_options.output,
                    output=matched_output,
                    channel=steering_options.channel,
                    output_count=len(midi_outputs),
                    match_count=len(matched_outputs),
                    matched_outputs=matched_outputs,
                ),
            )
        )

    return checks


def collect_hardware_preflight(args: argparse.Namespace) -> HardwarePreflightResult:
    """Compatibility wrapper around structured hardware diagnostics."""
    return HardwarePreflightResult.from_diagnostic_checks(
        args.device,
        getattr(args, "backend", "hardware"),
        collect_hardware_diagnostics(args),
    )


def _diagnostic_detail(**values: object) -> str:
    return "; ".join(
        f"{key}={_diagnostic_detail_value(value)}"
        for key, value in values.items()
        if value is not None
    )


def _diagnostic_detail_value(value: object) -> str:
    if isinstance(value, tuple):
        return json.dumps(list(value))
    if isinstance(value, list):
        return json.dumps(value)
    return str(value)


def _midi_output_names() -> list[str]:
    from matchpatch.midi import midi_output_names

    return midi_output_names()


def _matching_steering_outputs(names: list[str], query: str | None) -> list[str]:
    if query is None:
        return names
    return [name for name in names if query.casefold() in name.casefold()]


def _validate_steering_output_available(
    steering_options: SteeringOptions,
    *,
    matched_outputs: list[str],
) -> str:
    if len(matched_outputs) != 1:
        raise ValueError(
            f"MIDI output query {steering_options.output!r} matched {len(matched_outputs)} ports; "
            "configure a unique steering output"
        )
    return matched_outputs[0]


def list_devices() -> None:
    from matchpatch.audio import sd

    print("MatchPatch processor profiles:")

    for profile in list_device_profiles():
        print(f"  {profile.name}: {profile.display_name}")

    print("\nAudio host APIs:")

    for index, api in enumerate(sd.query_hostapis()):
        print(f"  [{index}] {api['name']}")

    print("\nAudio devices:")

    for index, device in enumerate(sd.query_devices()):
        api = sd.query_hostapis(device["hostapi"])["name"]
        print(
            f"  [{index}] {device['name']} | {api} | "
            f"in={device['max_input_channels']} "
            f"out={device['max_output_channels']}"
        )

    print("\nMIDI outputs:")

    try:
        from matchpatch.midi import midi_output_names

        for name in midi_output_names():
            print(f"  {name}")
    except ValueError as exc:
        print(f"  unavailable: {exc}")


def add_hardware_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--audio-device")
    parser.add_argument("--steering-output", "--midi-output")
    parser.add_argument("--steering-channel", "--midi-channel", type=int)
    parser.add_argument("--sample-rate", type=int)
    parser.add_argument("--input-mapping", type=parse_channel_mapping)
    parser.add_argument("--output-mapping", type=parse_channel_mapping)
    parser.add_argument("--blocksize", type=int)
    parser.add_argument("--preset-wait", type=float)
    parser.add_argument("--snapshot-wait", type=float)
    parser.add_argument("--measurement-wait", type=float)
    parser.add_argument("--pre-roll", type=float)
    parser.add_argument("--post-roll", type=float)
    parser.add_argument("--round-trip-latency", type=float)


def apply_config(args: argparse.Namespace) -> argparse.Namespace:
    config = load_config(args.config)
    profile = get_device_profile(args.device)
    _apply_backend_config(args, config, profile)
    args.device_settings = resolve_device_settings(profile, config, args)
    _validate_configured_backend_factory(args, profile)
    _apply_resolved_device_settings(args)
    _apply_timing_config(args, config)
    _apply_optimization_config(args, config)
    if args.snapshot_count is not None:
        validate_snapshot_count(profile, args.snapshot_count)
    args.analysis_options = _analysis_options_from_config(args, config)
    return args


def _apply_backend_config(
    args: argparse.Namespace,
    config: Config,
    profile: DeviceProfile,
) -> None:
    args.backend = getattr(args, "backend", None) or config_value(
        config, "normalize", "backend", default="hardware"
    )
    if args.backend == "helix":
        args.backend = "hardware"
    _validate_profile_backend_support(profile, _backend_mode(args.backend))


def _validate_configured_backend_factory(
    args: argparse.Namespace,
    profile: DeviceProfile,
) -> None:
    mode = _backend_mode(args.backend)
    if mode == "offline":
        return
    settings = cast("Mapping[str, object]", args.device_settings)
    if any(factory.supports(mode, settings) for factory in _audio_transport_factories(profile)):
        return
    raise ValueError(
        f"Backend {mode!r} is supported by {profile.display_name}, "
        "but no audio transport factory is available"
    )


def _apply_resolved_device_settings(args: argparse.Namespace) -> None:
    settings = args.device_settings
    args.audio_device = settings["audio_device"]
    args.sample_rate = settings["sample_rate"]
    args.input_mapping = settings["input_mapping"]
    args.output_mapping = settings["output_mapping"]
    args.blocksize = settings["blocksize"]
    args.steering_output = settings["midi_output"]
    args.steering_channel = settings["midi_channel"]
    args.preset_wait = settings["preset_wait"]
    args.snapshot_wait = settings["snapshot_wait"]
    args.measurement_wait = settings["measurement_wait"]


def _apply_timing_config(
    args: argparse.Namespace,
    config: Config,
) -> None:
    for attr, key, default in (
        ("pre_roll", "pre_roll_seconds", 0.2),
        ("post_roll", "post_roll_seconds", 0.1),
        ("round_trip_latency", "round_trip_latency_seconds", 0.02),
    ):
        setattr(args, attr, _arg_or_config(args, attr, config, "analysis", key, default=default))
    args.snapshot_count = _arg_or_config(
        args, "snapshot_count", config, "policy", "measured_snapshots"
    )


def _apply_optimization_config(args: argparse.Namespace, config: Config) -> None:
    args.stability_tolerance = _arg_or_config(
        args,
        "stability_tolerance",
        config,
        "measurement",
        "stability_tolerance_percent",
        default=2.0,
    )


def _analysis_options_from_config(args: argparse.Namespace, config: Config) -> AnalysisOptions:
    return AnalysisOptions(
        window_seconds=_float_config_value(
            _arg_or_config(
                args, "analysis_window", config, "analysis", "window_seconds", default=3.0
            ),
            3.0,
        ),
        interval_seconds=_float_config_value(
            _arg_or_config(
                args, "analysis_interval", config, "analysis", "interval_seconds", default=0.1
            ),
            0.1,
        ),
        minimum_valid_lufs=_float_config_value(
            _arg_or_config(
                args,
                "minimum_valid_lufs",
                config,
                "analysis",
                "minimum_valid_lufs",
                default=-100.0,
            ),
            -100.0,
        ),
    )


def _arg_or_config(
    args: argparse.Namespace,
    attr: str,
    config: Config,
    *path: str,
    default: object | None = None,
) -> object:
    value = getattr(args, attr, None)
    if value is not None:
        return value
    return config_value(config, *path, default=default)


def _float_config_value(value: object | None, default: float) -> float:
    if value is None:
        return default
    return float(cast(Any, value))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("devices", help="List profiles, audio devices, and MIDI outputs")

    check_parser = subparsers.add_parser(
        "check-hardware",
        help="Validate configured processor audio and MIDI endpoints",
    )
    check_parser.add_argument("--device", required=True)
    check_parser.add_argument("--config", help="TOML configuration file")
    check_parser.add_argument(
        "--diagnostics-json",
        action="store_true",
        help="Print structured hardware preflight diagnostics as JSON",
    )
    add_hardware_arguments(check_parser)

    measure_parser = subparsers.add_parser(
        "measure",
        help="Measure processor snapshots for each preset",
    )
    measure_parser.add_argument("--device", required=True)
    measure_parser.add_argument("--config", help="TOML configuration file")
    measure_parser.add_argument("--preset-ids", type=parse_int_list, required=True)
    measure_parser.add_argument("--csv", required=True)
    measure_parser.add_argument("--reference-di", required=True)
    measure_parser.add_argument(
        "--backend",
        help="Use hardware, empty-patch loopback, or a stateful processor simulation",
    )
    measure_parser.add_argument(
        "--simulate-fail-presets",
        type=parse_int_list,
        default=[],
        help="Comma-separated numeric preset IDs that fail in simulated mode",
    )
    measure_parser.add_argument("--snapshot-count", type=int)
    measure_parser.add_argument("--snapshot-plan", type=parse_snapshot_plan)
    measure_parser.add_argument("--analysis-window", type=float)
    measure_parser.add_argument("--analysis-interval", type=float)
    measure_parser.add_argument("--minimum-valid-lufs", type=float)
    measure_parser.add_argument("--play-recorded-output", action="store_true")
    measure_parser.add_argument("--playback-toggle-file")
    measure_parser.add_argument("--recordings-dir")
    measure_parser.add_argument("--progress-jsonl", action="store_true")
    add_hardware_arguments(measure_parser)

    optimize_parser = subparsers.add_parser(
        "optimize",
        help="Determine stable lower bounds for measurement timing parameters",
    )
    optimize_parser.add_argument("--device", required=True)
    optimize_parser.add_argument("--config", help="TOML configuration file")
    optimize_parser.add_argument("--preset-id", type=int, required=True)
    optimize_parser.add_argument("--alternate-preset-id", type=int)
    optimize_parser.add_argument("--reference-di", required=True)
    optimize_parser.add_argument(
        "--backend",
    )
    optimize_parser.add_argument("--stability-runs", type=int, default=3)
    optimize_parser.add_argument("--termination-tolerance", type=float, default=10.0)
    optimize_parser.add_argument("--stability-tolerance", type=float)
    optimize_parser.add_argument(
        "--pinned-parameter",
        action="append",
        default=[],
        help="Timing parameter to keep fixed at its configured value during optimization",
    )
    optimize_parser.add_argument(
        "--simulate-fail-presets",
        type=parse_int_list,
        default=[],
        help="Comma-separated numeric preset IDs that fail in simulated mode",
    )
    optimize_parser.add_argument("--analysis-window", type=float)
    optimize_parser.add_argument("--analysis-interval", type=float)
    optimize_parser.add_argument("--minimum-valid-lufs", type=float)
    optimize_parser.add_argument("--play-recorded-output", action="store_true")
    optimize_parser.add_argument("--playback-toggle-file")
    optimize_parser.add_argument("--progress-jsonl", action="store_true")
    add_hardware_arguments(optimize_parser)

    args = parser.parse_args(argv)
    return apply_config(args) if args.command in {"check-hardware", "measure", "optimize"} else args


def main(argv: list[str] | None = None) -> None:
    args = parse_args() if argv is None else parse_args(argv)
    _run_measure_command(args, _request_from_measure_args(args))


def _request_from_measure_args(args: argparse.Namespace) -> argparse.Namespace:
    if getattr(args, "backend", None) == "helix":
        args.backend = "hardware"
    return args


def _run_measure_command(
    args: argparse.Namespace,
    request: argparse.Namespace,
) -> None:
    if args.command == "devices":
        list_devices()
    elif args.command == "check-hardware":
        profile = get_device_profile(request.device) if hasattr(request, "device") else None
        _run_check_hardware_command(request, profile)
    elif args.command == "measure":
        _run_measure_subcommand(request)
    else:
        _run_optimize_subcommand(request)


def _run_check_hardware_command(
    args: argparse.Namespace,
    profile: DeviceProfile | None,  # noqa: ARG001
) -> None:
    if getattr(args, "diagnostics_json", False):
        checks = _hardware_diagnostic_checks(args)
        print(
            json.dumps([diagnostic_check_to_dict(check) for check in checks], sort_keys=True),
            flush=True,
        )
        if any(check.status == "fail" for check in checks):
            raise SystemExit(1)
        return
    try:
        check_hardware(args)
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    else:
        print("Hardware available")


def _hardware_diagnostic_checks(args: argparse.Namespace) -> list[DiagnosticCheck]:
    preflight = collect_hardware_preflight(args)
    return [preflight_check_to_diagnostic(check) for check in preflight.checks]


def _run_measure_subcommand(args: argparse.Namespace) -> None:
    if getattr(args, "progress_jsonl", False):
        args.on_progress = lambda event: print(event.to_json(), flush=True)
    measure(args)


def _run_optimize_subcommand(args: argparse.Namespace) -> None:
    if getattr(args, "progress_jsonl", False):
        args.on_optimization_progress = lambda event: print(event.to_json(), flush=True)
    optimize_measurement_timing(args)


if __name__ == "__main__":  # pragma: no cover - module entry point
    main()
