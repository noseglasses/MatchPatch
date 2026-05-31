"""Generic MatchPatch gain-normalization orchestration for WSL."""

from __future__ import annotations

import argparse
import csv
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import cast

from matchpatch.analysis import AnalysisOptions
from matchpatch.config import Config, config_value, load_config, parse_channel_mapping, prefer
from matchpatch.devices import get_device_profile
from matchpatch.devices.base import NormalizationPolicy
from matchpatch.progress import ProgressEvent
from matchpatch.workflow import ImportRequest, NormalizationRequest, normalize_presets

PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_WINDOWS_PYTHON = PROJECT_DIR / ".venv-windows" / "Scripts" / "python.exe"
DEFAULT_REFERENCE_DI = (
    PROJECT_DIR
    / "Reaper"
    / "Referenz_Gitarre_DI_Strandberg_Boden_Fusion_Bridge_Humbucker_short.wav"
)


def _mapping_argument(value: object | None) -> str | None:
    if value is None:
        return None

    return ",".join(str(channel) for channel in parse_channel_mapping(value))


def _normalization_policy(config: Config, args: argparse.Namespace) -> NormalizationPolicy:
    policy = NormalizationPolicy(
        snapshot_count=config_value(config, "policy", "measured_snapshots", default=4),
        solo_regex=cast(
            str,
            prefer(
                args.solo_regex,
                config,
                "policy",
                "solo_regex",
                default=config_value(config, "policy", "solo_marker", default=r"(?i)\bsolo\b"),
            ),
        ),
        solo_gain_bump_db=cast(
            float,
            prefer(args.solo_gain_bump_db, config, "policy", "solo_gain_bump_db", default=3.0),
        ),
        crest_factor_reference_db=config_value(
            config, "policy", "crest_factor_reference_db", default=12.0
        ),
        crest_factor_correction_ratio=config_value(
            config, "policy", "crest_factor_correction_ratio", default=0.4
        ),
        max_crest_factor_correction_db=config_value(
            config, "policy", "max_crest_factor_correction_db", default=3.0
        ),
        gain_deadband_db=config_value(config, "policy", "gain_deadband_db", default=0.25),
    )

    if policy.snapshot_count < 1:
        raise ValueError("Configured measured snapshot count must be at least 1")
    try:
        re.compile(policy.solo_regex)
    except re.error as exc:
        raise ValueError(f"Invalid solo snapshot regex: {exc}") from exc

    return policy


def _analysis_options(config: Config) -> AnalysisOptions:
    return AnalysisOptions(
        window_seconds=config_value(config, "analysis", "window_seconds", default=3.0),
        interval_seconds=config_value(config, "analysis", "interval_seconds", default=0.1),
        minimum_valid_lufs=config_value(config, "analysis", "minimum_valid_lufs", default=-100.0),
    )


def apply_config(args: argparse.Namespace) -> argparse.Namespace:
    config = load_config(args.config)
    device_audio = ("devices", args.device, "audio")
    device_steering = ("devices", args.device, "steering")
    args.backend = (
        args.backend
        or os.getenv("MATCHPATCH_BACKEND")
        or config_value(config, "normalize", "backend", default="hardware")
    )
    args.windows_python = (
        args.windows_python
        or os.getenv("MATCHPATCH_WINDOWS_PYTHON")
        or config_value(
            config,
            "normalize",
            "windows_python",
            default=str(DEFAULT_WINDOWS_PYTHON),
        )
    )
    args.reference_di = (
        args.reference_di
        or os.getenv("MATCHPATCH_REFERENCE_DI")
        or config_value(config, "normalize", "reference_di", default=str(DEFAULT_REFERENCE_DI))
    )
    args.target_lufs = prefer(args.target_lufs, config, "normalize", "target_lufs", default=-16.0)
    args.timeout = prefer(args.timeout, config, "normalize", "timeout_seconds")
    args.ignore_bad_lufs = True
    args.audio_device = prefer(args.audio_device, config, *device_audio, "device")
    args.sample_rate = prefer(args.sample_rate, config, *device_audio, "sample_rate")
    args.input_mapping = _mapping_argument(
        prefer(args.input_mapping, config, *device_audio, "input_mapping")
    )
    args.output_mapping = _mapping_argument(
        prefer(args.output_mapping, config, *device_audio, "output_mapping")
    )
    args.blocksize = prefer(args.blocksize, config, *device_audio, "blocksize")
    args.steering_output = prefer(args.steering_output, config, *device_steering, "output")
    args.steering_channel = prefer(args.steering_channel, config, *device_steering, "channel")
    args.preset_wait = prefer(args.preset_wait, config, *device_steering, "preset_wait_seconds")
    args.snapshot_wait = prefer(
        args.snapshot_wait, config, *device_steering, "snapshot_wait_seconds"
    )
    args.measurement_wait = prefer(
        args.measurement_wait,
        config,
        *device_steering,
        "measurement_wait_seconds",
    )
    args.policy = _normalization_policy(config, args)
    args.analysis_options = _analysis_options(config)
    return args


def run_command(args: list[object], timeout: float | None = None) -> None:
    subprocess.run(
        [str(arg) for arg in args],
        check=True,
        text=True,
        timeout=timeout,
    )


def wsl_path_to_windows(path: Path) -> str:
    completed = subprocess.run(
        ["wslpath", "-w", str(path.resolve())],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return completed.stdout.strip()


def count_csv_rows(csv_path: Path) -> int:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        return sum(1 for _ in csv.DictReader(csv_file))


def wait_for_user_confirmation(message: str) -> None:
    print()
    print(message)
    input("Press Enter to continue...")


def run_windows_analysis(
    args: argparse.Namespace | NormalizationRequest,
    preset_ids: list[int],
    csv_path: Path,
    on_progress: Callable[[ProgressEvent], None] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> None:
    windows_python = Path(args.windows_python).resolve()

    if not windows_python.exists():
        raise RuntimeError(
            "Native Windows MatchPatch environment is missing. "
            "Run scripts/sync-windows-from-wsl.sh first."
        )

    command: list[object] = [
        windows_python,
        "-m",
        "matchpatch.measure",
        "measure",
        "--device",
        args.device,
        "--backend",
        args.backend,
        "--preset-ids",
        ",".join(str(preset_id) for preset_id in preset_ids),
        "--csv",
        wsl_path_to_windows(csv_path),
        "--reference-di",
        wsl_path_to_windows(Path(args.reference_di)),
    ]

    optional_values = {
        "--audio-device": args.audio_device,
        "--steering-output": args.steering_output,
        "--steering-channel": args.steering_channel,
        "--sample-rate": args.sample_rate,
        "--input-mapping": args.input_mapping,
        "--output-mapping": args.output_mapping,
        "--simulate-fail-presets": getattr(args, "simulate_fail_presets", None),
        "--blocksize": getattr(args, "blocksize", None),
        "--preset-wait": getattr(args, "preset_wait", None),
        "--snapshot-wait": getattr(args, "snapshot_wait", None),
        "--measurement-wait": getattr(args, "measurement_wait", None),
        "--snapshot-count": getattr(args, "policy", NormalizationPolicy()).snapshot_count,
        "--analysis-window": getattr(args, "analysis_options", AnalysisOptions()).window_seconds,
        "--analysis-interval": getattr(
            args, "analysis_options", AnalysisOptions()
        ).interval_seconds,
        "--minimum-valid-lufs": getattr(
            args, "analysis_options", AnalysisOptions()
        ).minimum_valid_lufs,
    }

    for option, value in optional_values.items():
        if value is not None:
            command.extend([option, value])

    if on_progress is None:
        try:
            run_command(command, timeout=args.timeout)
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("Timed out waiting for native Windows analysis") from exc
        return

    command.append("--progress-jsonl")
    _run_progress_command(command, args.timeout, on_progress, cancel_requested)


def _run_progress_command(
    command: list[object],
    timeout: float | None,
    on_progress: Callable[[ProgressEvent], None],
    cancel_requested: Callable[[], bool] | None = None,
) -> None:
    process = subprocess.Popen(  # noqa: S603
        [str(arg) for arg in command],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
    )
    lines: queue.Queue[tuple[str, str] | None] = queue.Queue()

    def read_stream(name: str) -> None:
        stream = getattr(process, name)
        assert stream is not None

        for line in stream:
            lines.put((name, line))

        lines.put(None)

    threading.Thread(target=read_stream, args=("stdout",), daemon=True).start()
    threading.Thread(target=read_stream, args=("stderr",), daemon=True).start()
    deadline = time.monotonic() + timeout if timeout is not None else None
    open_streams = 2

    try:
        while open_streams or process.poll() is None:
            if cancel_requested is not None and cancel_requested():
                raise RuntimeError("Normalization cancelled by user")

            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("Timed out waiting for native Windows analysis")

            try:
                line = lines.get(timeout=0.1)
            except queue.Empty:
                continue

            if line is None:
                open_streams -= 1
                continue

            stream_name, text = line
            if stream_name == "stderr":
                on_progress(ProgressEvent("error_log", message=text.rstrip()))
                continue

            try:
                on_progress(ProgressEvent.from_json(text))
            except ValueError as exc:
                raise RuntimeError(
                    f"Invalid progress output from native Windows analysis: {text}"
                ) from exc

        return_code = process.wait()

        if return_code:
            raise subprocess.CalledProcessError(return_code, [str(arg) for arg in command])
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="TOML configuration file")
    parser.add_argument("--device", required=True, help="Audio processor profile")
    parser.add_argument("-i", "--input", required=True)
    parser.add_argument("-o", "--output")
    parser.add_argument("-a", "--automation", action="store_true")
    parser.add_argument("-S", "--preset-set")
    parser.add_argument("-n", "--limit", type=int)
    parser.add_argument("--keep-temp", action="store_true")
    parser.add_argument("--target-lufs", type=float)
    parser.add_argument("--solo-regex")
    parser.add_argument("--solo-gain-bump-db", type=float)
    parser.add_argument(
        "--backend",
        choices=["hardware", "loopback", "simulated"],
    )
    parser.add_argument(
        "--windows-python",
    )
    parser.add_argument(
        "--reference-di",
    )
    parser.add_argument("--audio-device")
    parser.add_argument("--steering-output", "--midi-output")
    parser.add_argument("--steering-channel", "--midi-channel", type=int)
    parser.add_argument("--sample-rate", type=int)
    parser.add_argument("--input-mapping")
    parser.add_argument("--output-mapping")
    parser.add_argument("--simulate-fail-presets")
    parser.add_argument("--blocksize", type=int)
    parser.add_argument("--preset-wait", type=float)
    parser.add_argument("--snapshot-wait", type=float)
    parser.add_argument("--measurement-wait", type=float)
    parser.add_argument("--timeout", type=float)
    return parser.parse_args(argv)


def request_from_args(args: argparse.Namespace) -> NormalizationRequest:
    return NormalizationRequest(
        device=args.device,
        input_path=Path(args.input),
        output_path=Path(args.output) if args.output else None,
        automation=args.automation,
        preset_set=args.preset_set,
        limit=args.limit,
        keep_temp=args.keep_temp,
        ignore_bad_lufs=args.ignore_bad_lufs,
        target_lufs=args.target_lufs,
        backend=args.backend,
        windows_python=args.windows_python,
        reference_di=Path(args.reference_di),
        audio_device=args.audio_device,
        sample_rate=args.sample_rate,
        input_mapping=args.input_mapping,
        output_mapping=args.output_mapping,
        blocksize=args.blocksize,
        steering_output=args.steering_output,
        steering_channel=args.steering_channel,
        preset_wait=args.preset_wait,
        snapshot_wait=args.snapshot_wait,
        measurement_wait=args.measurement_wait,
        simulate_fail_presets=args.simulate_fail_presets,
        timeout=args.timeout,
        policy=args.policy,
        analysis_options=args.analysis_options,
    )


def _cli_confirm_import(request: ImportRequest) -> bool:
    wait_for_user_confirmation(request.message)
    return True


def _cli_progress(event: ProgressEvent) -> None:
    if event.phase == "preparing_reamp":
        print("Creating reamp file")
    elif event.phase == "applying":
        print("Applying gain adjustments")
    elif event.kind == "temp_retained":
        print(event.message)
    elif event.kind == "log":
        print(event.message)
    elif event.kind == "error_log":
        print(event.message, file=sys.stderr)


def main(argv: list[str] | None = None) -> None:
    args = apply_config(parse_args(argv))
    request = request_from_args(args)

    def run_analysis(
        workflow_request: NormalizationRequest,
        preset_ids: list[int],
        csv_path: Path,
        on_progress: Callable[[ProgressEvent], None] | None,
    ) -> None:
        profile = get_device_profile(workflow_request.device)
        handler = profile.create_patch_file_handler(PROJECT_DIR)
        print(f"Device     : {profile.name}")
        print(f"Preset set : {','.join(str(preset_id) for preset_id in preset_ids)}")
        print(
            "Device IDs : "
            + ",".join(handler.format_patch_id(preset_id) for preset_id in preset_ids)
        )
        print(f"Temp CSV   : {csv_path}")
        run_windows_analysis(args, preset_ids, csv_path)

    result = normalize_presets(
        request,
        run_analysis=run_analysis,
        on_progress=_cli_progress,
        confirm_import=_cli_confirm_import if request.automation else None,
        get_profile=get_device_profile,
        make_temp_dir=lambda: Path(tempfile.mkdtemp(prefix="matchpatch_gain_", dir=PROJECT_DIR)),
    )
    print()
    print("[OK] Gain-adjusted patch file written")
    print(f"Output: {result.output_path}")
