"""Native Windows measurement worker for MatchPatch audio processors."""

from __future__ import annotations

import argparse
import csv
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import numpy as np
import soundfile as sf

from matchpatch.analysis import AnalysisOptions, analyze_audio
from matchpatch.config import (
    config_value,
    load_config,
)
from matchpatch.config import (
    parse_channel_mapping as parse_config_mapping,
)
from matchpatch.devices import get_device_profile, list_device_profiles
from matchpatch.devices.base import (
    AudioRouting,
    DeviceController,
    DeviceProfile,
    SteeringOptions,
    validate_snapshot_count,
)
from matchpatch.progress import ProgressEvent

if TYPE_CHECKING:
    from matchpatch.audio import AudioConfig


class MeasurementBackend(Protocol):
    def activate_preset(self, preset_id: int) -> None: ...

    def reapply_snapshot(self, snapshot: int) -> None: ...

    def record(self, reference_audio: np.ndarray) -> np.ndarray: ...


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
    results: list[tuple[float, float]] | None,
) -> None:
    row: dict[str, str | int | float] = {
        "Preset": preset_id,
        "DevicePatch": device_patch,
    }

    for snapshot in range(1, snapshot_count + 1):
        if results is None:
            row[f"LUFS{snapshot}"] = "ERROR"
            row[f"CrestFactor{snapshot}"] = "ERROR"
        else:
            lufs, crest = results[snapshot - 1]
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

        for preset_index, preset_id in enumerate(preset_ids, start=1):
            device_patch = handler.format_patch_id(preset_id)
            _emit_progress(
                on_progress,
                ProgressEvent(
                    "preset_started",
                    preset_id=preset_id,
                    device_patch=device_patch,
                    preset_index=preset_index,
                    preset_total=len(preset_ids),
                    snapshot_total=measured_snapshots,
                ),
            )

            if log_output:
                print(f"[MEASURE] {profile.name}:{device_patch}", flush=True)

            try:
                backend.activate_preset(preset_id)
                results = []

                for snapshot in range(1, measured_snapshots + 1):
                    _emit_progress(
                        on_progress,
                        ProgressEvent(
                            "snapshot_started",
                            preset_id=preset_id,
                            device_patch=device_patch,
                            preset_index=preset_index,
                            preset_total=len(preset_ids),
                            snapshot=snapshot,
                            snapshot_total=measured_snapshots,
                        ),
                    )
                    backend.reapply_snapshot(snapshot)
                    values = analyze_audio(backend.record(reference), sample_rate, analysis_options)
                    results.append(
                        (
                            values.short_term_lufs,
                            values.crest_factor_db,
                        )
                    )
                    _emit_progress(
                        on_progress,
                        ProgressEvent(
                            "snapshot_completed",
                            preset_id=preset_id,
                            device_patch=device_patch,
                            preset_index=preset_index,
                            preset_total=len(preset_ids),
                            snapshot=snapshot,
                            snapshot_total=measured_snapshots,
                            reference_lufs=reference_lufs,
                            lufs=values.short_term_lufs,
                            crest_factor_db=values.crest_factor_db,
                        ),
                    )

                    if log_output:
                        print(
                            f"  snapshot {snapshot}: "
                            f"{values.short_term_lufs:.3f} LUFS, "
                            f"{values.crest_factor_db:.3f} dB crest",
                            flush=True,
                        )

                append_result_row(
                    writer,
                    preset_id,
                    device_patch,
                    measured_snapshots,
                    results,
                )

            except Exception as exc:
                _emit_progress(
                    on_progress,
                    ProgressEvent(
                        "preset_failed",
                        message=str(exc),
                        preset_id=preset_id,
                        device_patch=device_patch,
                        preset_index=preset_index,
                        preset_total=len(preset_ids),
                        snapshot_total=measured_snapshots,
                    ),
                )

                if log_output:
                    print(
                        f"[ERROR] {profile.name}:{device_patch}: {exc}",
                        file=sys.stderr,
                        flush=True,
                    )
                append_result_row(
                    writer,
                    preset_id,
                    device_patch,
                    measured_snapshots,
                    None,
                )

            csv_file.flush()

    _emit_progress(on_progress, ProgressEvent("measurement_completed"))


def _emit_progress(
    callback: Callable[[ProgressEvent], None] | None,
    event: ProgressEvent,
) -> None:
    if callback is not None:
        callback(event)


def resolve_audio_config(args: argparse.Namespace, profile: DeviceProfile) -> AudioConfig:
    from matchpatch.audio import AudioConfig

    defaults = profile.default_audio_routing()
    config = AudioConfig(
        device=args.audio_device if args.audio_device is not None else defaults.device,
        sample_rate=args.sample_rate if args.sample_rate is not None else defaults.sample_rate,
        input_mapping=(
            args.input_mapping if args.input_mapping is not None else defaults.input_mapping
        ),
        output_mapping=(
            args.output_mapping if args.output_mapping is not None else defaults.output_mapping
        ),
        blocksize=args.blocksize,
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
    defaults = profile.default_steering_options()
    return SteeringOptions(
        output=(args.steering_output if args.steering_output is not None else defaults.output),
        channel=args.steering_channel if args.steering_channel is not None else defaults.channel,
        preset_wait_seconds=(
            args.preset_wait if args.preset_wait is not None else defaults.preset_wait_seconds
        ),
        snapshot_wait_seconds=(
            args.snapshot_wait if args.snapshot_wait is not None else defaults.snapshot_wait_seconds
        ),
        measurement_wait_seconds=(
            args.measurement_wait
            if args.measurement_wait is not None
            else defaults.measurement_wait_seconds
        ),
    )


def measure(args: argparse.Namespace) -> None:
    profile = get_device_profile(args.device)
    defaults = profile.default_audio_routing()
    sample_rate = args.sample_rate if args.sample_rate is not None else defaults.sample_rate
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

    if args.backend == "loopback":
        measure_presets(
            profile,
            args.preset_ids,
            Path(args.csv),
            reference,
            sample_rate,
            LoopbackBackend(),
            snapshot_count=snapshot_count,
            analysis_options=analysis_options,
            on_progress=on_progress,
            log_output=log_output,
        )
        return

    if args.backend == "simulated":
        measure_presets(
            profile,
            args.preset_ids,
            Path(args.csv),
            reference,
            sample_rate,
            SimulatedHardwareBackend(
                defaults,
                snapshot_count,
                args.input_mapping,
                args.output_mapping,
                frozenset(args.simulate_fail_presets),
            ),
            snapshot_count=snapshot_count,
            analysis_options=analysis_options,
            on_progress=on_progress,
            log_output=log_output,
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
        measure_presets(
            profile,
            args.preset_ids,
            Path(args.csv),
            reference,
            sample_rate,
            HardwareBackend(
                audio_config,
                controller,
                steering_options.measurement_wait_seconds,
            ),
            snapshot_count=snapshot_count,
            analysis_options=analysis_options,
            on_progress=on_progress,
            log_output=log_output,
        )


def check_hardware(args: argparse.Namespace) -> None:
    """Validate that configured processor audio and steering endpoints are present."""
    profile = get_device_profile(args.device)

    from matchpatch.audio import validate_audio_device_available

    validate_audio_device_available(resolve_audio_config(args, profile))
    steering_options = resolve_steering_options(args, profile)
    _validate_steering_output_available(steering_options)


def _validate_steering_output_available(steering_options: SteeringOptions) -> None:
    import mido

    names = mido.get_output_names()
    query = steering_options.output
    matches = (
        names if query is None else [name for name in names if query.casefold() in name.casefold()]
    )

    if len(matches) != 1:
        raise ValueError(
            f"MIDI output query {query!r} matched {len(matches)} ports; "
            "configure a unique steering output"
        )


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
        import mido

        for name in mido.get_output_names():
            print(f"  {name}")
    except ImportError:
        print("  unavailable: mido is not installed")


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


def apply_config(args: argparse.Namespace) -> argparse.Namespace:
    config = load_config(args.config)
    profile = get_device_profile(args.device)
    device_audio = ("devices", args.device, "audio")
    device_steering = ("devices", args.device, "steering")
    args.backend = (
        getattr(args, "backend", None)
        or config_value(config, "normalize", "backend", default="hardware")
    )
    args.audio_device = (
        args.audio_device
        if args.audio_device is not None
        else config_value(config, *device_audio, "device")
    )
    args.sample_rate = (
        args.sample_rate
        if args.sample_rate is not None
        else config_value(config, *device_audio, "sample_rate")
    )

    for name in ("input_mapping", "output_mapping"):
        value = getattr(args, name)

        if value is None:
            value = config_value(config, *device_audio, name)

        if value is not None:
            setattr(args, name, parse_config_mapping(value))

    args.blocksize = (
        args.blocksize
        if args.blocksize is not None
        else config_value(config, *device_audio, "blocksize", default=0)
    )
    args.steering_output = (
        args.steering_output
        if args.steering_output is not None
        else config_value(config, *device_steering, "output")
    )
    args.steering_channel = (
        args.steering_channel
        if args.steering_channel is not None
        else config_value(config, *device_steering, "channel")
    )
    args.preset_wait = (
        args.preset_wait
        if args.preset_wait is not None
        else config_value(config, *device_steering, "preset_wait_seconds")
    )
    args.snapshot_wait = (
        args.snapshot_wait
        if args.snapshot_wait is not None
        else config_value(config, *device_steering, "snapshot_wait_seconds")
    )
    args.measurement_wait = (
        args.measurement_wait
        if args.measurement_wait is not None
        else config_value(config, *device_steering, "measurement_wait_seconds")
    )
    args.pre_roll = (
        getattr(args, "pre_roll", None)
        if getattr(args, "pre_roll", None) is not None
        else config_value(config, "analysis", "pre_roll_seconds", default=0.2)
    )
    args.post_roll = (
        getattr(args, "post_roll", None)
        if getattr(args, "post_roll", None) is not None
        else config_value(config, "analysis", "post_roll_seconds", default=0.1)
    )
    args.round_trip_latency = (
        getattr(args, "round_trip_latency", None)
        if getattr(args, "round_trip_latency", None) is not None
        else config_value(config, "analysis", "round_trip_latency_seconds", default=0.02)
    )
    args.snapshot_count = (
        getattr(args, "snapshot_count", None)
        if getattr(args, "snapshot_count", None) is not None
        else config_value(config, "policy", "measured_snapshots")
    )

    if args.snapshot_count is not None:
        validate_snapshot_count(profile, args.snapshot_count)

    args.analysis_options = AnalysisOptions(
        window_seconds=(
            getattr(args, "analysis_window", None)
            if getattr(args, "analysis_window", None) is not None
            else config_value(config, "analysis", "window_seconds", default=3.0)
        ),
        interval_seconds=(
            getattr(args, "analysis_interval", None)
            if getattr(args, "analysis_interval", None) is not None
            else config_value(config, "analysis", "interval_seconds", default=0.1)
        ),
        minimum_valid_lufs=(
            getattr(args, "minimum_valid_lufs", None)
            if getattr(args, "minimum_valid_lufs", None) is not None
            else config_value(config, "analysis", "minimum_valid_lufs", default=-100.0)
        ),
    )
    return args


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("devices", help="List profiles, audio devices, and MIDI outputs")

    check_parser = subparsers.add_parser(
        "check-hardware",
        help="Validate configured processor audio and MIDI endpoints",
    )
    check_parser.add_argument("--device", required=True)
    check_parser.add_argument("--config", help="TOML configuration file")
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
        choices=["hardware", "loopback", "simulated", "helix"],
        help="Use hardware, empty-patch loopback, or a stateful processor simulation",
    )
    measure_parser.add_argument(
        "--simulate-fail-presets",
        type=parse_int_list,
        default=[],
        help="Comma-separated numeric preset IDs that fail in simulated mode",
    )
    measure_parser.add_argument("--snapshot-count", type=int)
    measure_parser.add_argument("--analysis-window", type=float)
    measure_parser.add_argument("--analysis-interval", type=float)
    measure_parser.add_argument("--minimum-valid-lufs", type=float)
    measure_parser.add_argument("--pre-roll", type=float)
    measure_parser.add_argument("--post-roll", type=float)
    measure_parser.add_argument("--round-trip-latency", type=float)
    measure_parser.add_argument("--progress-jsonl", action="store_true")
    add_hardware_arguments(measure_parser)

    args = parser.parse_args()
    return apply_config(args) if args.command in {"check-hardware", "measure"} else args


def main() -> None:
    args = parse_args()

    if args.command == "devices":
        list_devices()
    elif args.command == "check-hardware":
        try:
            check_hardware(args)
        except Exception as exc:  # noqa: BLE001
            print(str(exc), file=sys.stderr)
            raise SystemExit(1) from None
        else:
            print("Hardware available")
    else:
        if args.backend == "helix":
            args.backend = "hardware"
        if getattr(args, "progress_jsonl", False):
            args.on_progress = lambda event: print(event.to_json(), flush=True)
        measure(args)


if __name__ == "__main__":  # pragma: no cover - module entry point
    main()
