"""Native Windows measurement worker for MatchPatch audio processors."""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import numpy as np
import soundfile as sf

from matchpatch.analysis import analyze_audio
from matchpatch.devices import get_device_profile, list_device_profiles
from matchpatch.devices.base import DeviceController, DeviceProfile, SteeringOptions

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
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    handler = profile.create_patch_file_handler(Path.cwd())

    with csv_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=csv_fields(profile.snapshot_count))
        writer.writeheader()

        for preset_id in preset_ids:
            device_patch = handler.format_patch_id(preset_id)
            print(f"[MEASURE] {profile.name}:{device_patch}", flush=True)

            try:
                backend.activate_preset(preset_id)
                results = []

                for snapshot in range(1, profile.snapshot_count + 1):
                    backend.reapply_snapshot(snapshot)
                    values = analyze_audio(backend.record(reference), sample_rate)
                    results.append(
                        (
                            values.short_term_lufs,
                            values.crest_factor_db,
                        )
                    )
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
                    profile.snapshot_count,
                    results,
                )

            except Exception as exc:
                print(
                    f"[ERROR] {profile.name}:{device_patch}: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
                append_result_row(
                    writer,
                    preset_id,
                    device_patch,
                    profile.snapshot_count,
                    None,
                )

            csv_file.flush()


def resolve_audio_config(args: argparse.Namespace, profile: DeviceProfile) -> AudioConfig:
    from matchpatch.audio import AudioConfig

    defaults = profile.default_audio_routing()
    return AudioConfig(
        device=args.audio_device if args.audio_device is not None else defaults.device,
        sample_rate=args.sample_rate if args.sample_rate is not None else defaults.sample_rate,
        input_mapping=(
            args.input_mapping if args.input_mapping is not None else defaults.input_mapping
        ),
        output_mapping=(
            args.output_mapping if args.output_mapping is not None else defaults.output_mapping
        ),
        blocksize=args.blocksize,
    )


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
    reference = load_reference_audio(Path(args.reference_di), sample_rate)

    if args.backend == "loopback":
        measure_presets(
            profile,
            args.preset_ids,
            Path(args.csv),
            reference,
            sample_rate,
            LoopbackBackend(),
        )
        return

    from matchpatch.audio import resolve_audio_device

    audio_config = resolve_audio_config(args, profile)
    steering_options = resolve_steering_options(args, profile)
    resolve_audio_device(audio_config.device)

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
    parser.add_argument("--blocksize", type=int, default=0)
    parser.add_argument("--preset-wait", type=float)
    parser.add_argument("--snapshot-wait", type=float)
    parser.add_argument("--measurement-wait", type=float)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("devices", help="List profiles, audio devices, and MIDI outputs")

    measure_parser = subparsers.add_parser(
        "measure",
        help="Measure processor snapshots for each preset",
    )
    measure_parser.add_argument("--device", required=True)
    measure_parser.add_argument("--preset-ids", type=parse_int_list, required=True)
    measure_parser.add_argument("--csv", required=True)
    measure_parser.add_argument("--reference-di", required=True)
    measure_parser.add_argument(
        "--backend",
        choices=["hardware", "loopback", "helix"],
        default="hardware",
        help="Use processor hardware or an in-process empty-patch simulation",
    )
    add_hardware_arguments(measure_parser)

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.command == "devices":
        list_devices()
    else:
        if args.backend == "helix":
            args.backend = "hardware"
        measure(args)


if __name__ == "__main__":  # pragma: no cover - module entry point
    main()
