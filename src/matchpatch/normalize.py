"""Generic MatchPatch gain-normalization orchestration."""

from __future__ import annotations

import argparse
import csv
import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

from matchpatch.analysis import AnalysisOptions
from matchpatch.config import Config, config_value, load_config, parse_channel_mapping, prefer
from matchpatch.devices import get_device_profile
from matchpatch.devices.base import (
    NormalizationPolicy,
    normalize_regex_pattern,
    validate_snapshot_count,
)
from matchpatch.diagnostics import (
    DiagnosticCheck,
    HardwarePreflightResult,
    diagnostic_check_from_dict,
    summarize_failed_checks,
)
from matchpatch.measurement_optimizer import OptimizationProgress
from matchpatch.progress import ProgressEvent
from matchpatch.workflow import ImportRequest, NormalizationRequest, normalize_presets

PROJECT_DIR = Path(__file__).resolve().parents[2]
PROCESS_REAP_TIMEOUT_SECONDS = 1.0
DEFAULT_REFERENCE_DI = (
    PROJECT_DIR / "audio" / "reference-di" / "DI_Strandberg_Boden_Fusion_Bridge_Humbucker.wav"
)


def _default_windows_python() -> Path:
    if getattr(sys, "frozen", False) and os.name == "nt":
        return type(PROJECT_DIR)(sys.executable)
    return PROJECT_DIR / ".venv-windows" / "Scripts" / "python.exe"


DEFAULT_WINDOWS_PYTHON = _default_windows_python()


def _mapping_argument(value: object | None) -> str | None:
    if value is None:
        return None

    return ",".join(str(channel) for channel in parse_channel_mapping(value))


def _configured_windows_python(args: argparse.Namespace, config: Config) -> str:
    if args.windows_python:
        return str(args.windows_python)

    env_value = os.getenv("MATCHPATCH_WINDOWS_PYTHON")
    if env_value:
        return env_value

    if getattr(sys, "frozen", False) and os.name == "nt":
        return str(DEFAULT_WINDOWS_PYTHON)

    return str(
        config_value(
            config,
            "normalize",
            "windows_python",
            default=str(DEFAULT_WINDOWS_PYTHON),
        )
    )


def _normalization_policy(config: Config, args: argparse.Namespace) -> NormalizationPolicy:
    profile = get_device_profile(args.device)
    policy = NormalizationPolicy(
        snapshot_count=cast(
            int,
            prefer(
                args.snapshot_count,
                config,
                "policy",
                "measured_snapshots",
                default=getattr(profile, "snapshot_count", 4),
            ),
        ),
        solo_regex=normalize_regex_pattern(
            cast(
                str,
                prefer(
                    args.solo_regex,
                    config,
                    "policy",
                    "solo_regex",
                    default=config_value(
                        config,
                        "policy",
                        "solo_marker",
                        default=NormalizationPolicy().solo_regex,
                    ),
                ),
            )
        ),
        ignore_snapshot_regex=normalize_regex_pattern(
            cast(
                str,
                prefer(
                    args.ignore_snapshot_regex,
                    config,
                    "policy",
                    "ignore_snapshot_regex",
                    default=NormalizationPolicy().ignore_snapshot_regex,
                ),
            )
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

    validate_snapshot_count(profile, policy.snapshot_count)
    try:
        re.compile(policy.solo_regex)
    except re.error as exc:
        raise ValueError(f"Invalid solo snapshot regex: {exc}") from exc
    try:
        re.compile(policy.ignore_snapshot_regex)
    except re.error as exc:
        raise ValueError(f"Invalid ignore snapshot regex: {exc}") from exc

    return policy


def _analysis_options(config: Config, args: argparse.Namespace) -> AnalysisOptions:
    def float_prefer(arg_value: object | None, section: str, key: str, default: float) -> float:
        value = prefer(arg_value, config, section, key, default=default)
        if value is None:
            return default
        return float(cast(Any, value))

    return AnalysisOptions(
        window_seconds=float_prefer(
            args.analysis_window,
            "analysis",
            "window_seconds",
            default=3.0,
        ),
        interval_seconds=float_prefer(
            args.analysis_interval,
            "analysis",
            "interval_seconds",
            default=0.1,
        ),
        minimum_valid_lufs=float_prefer(
            args.minimum_valid_lufs,
            "analysis",
            "minimum_valid_lufs",
            default=-100.0,
        ),
    )


def apply_config(args: argparse.Namespace) -> argparse.Namespace:
    config = load_config(args.config)
    profile = get_device_profile(args.device)
    default_audio = (
        profile.default_audio_routing()
        if hasattr(profile, "default_audio_routing")
        else argparse.Namespace(
            device=None,
            sample_rate=None,
            input_mapping=None,
            output_mapping=None,
        )
    )
    default_steering = (
        profile.default_steering_options()
        if hasattr(profile, "default_steering_options")
        else argparse.Namespace(
            output=None,
            channel=None,
            preset_wait_seconds=None,
            snapshot_wait_seconds=None,
            measurement_wait_seconds=None,
        )
    )
    device_audio = ("devices", args.device, "audio")
    device_steering = ("devices", args.device, "steering")
    args.backend = (
        args.backend
        or os.getenv("MATCHPATCH_BACKEND")
        or config_value(config, "normalize", "backend", default="hardware")
    )
    args.windows_python = _configured_windows_python(args, config)
    args.reference_di = (
        args.reference_di
        or os.getenv("MATCHPATCH_REFERENCE_DI")
        or config_value(config, "normalize", "reference_di", default=str(DEFAULT_REFERENCE_DI))
    )
    args.custom_adjustments_file = prefer(
        args.custom_adjustments_file,
        config,
        "normalize",
        "custom_adjustments_file",
        default=config_value(config, "normalize", "custom_adjustments"),
    )
    args.target_lufs = prefer(args.target_lufs, config, "normalize", "target_lufs", default=-16.0)
    args.timeout = prefer(args.timeout, config, "normalize", "timeout_seconds")
    args.ignore_bad_lufs = True
    args.audio_device = prefer(
        args.audio_device,
        config,
        *device_audio,
        "device",
        default=default_audio.device,
    )
    args.sample_rate = prefer(
        args.sample_rate,
        config,
        *device_audio,
        "sample_rate",
        default=default_audio.sample_rate,
    )
    args.input_mapping = _mapping_argument(
        prefer(
            args.input_mapping,
            config,
            *device_audio,
            "input_mapping",
            default=default_audio.input_mapping,
        )
    )
    args.output_mapping = _mapping_argument(
        prefer(
            args.output_mapping,
            config,
            *device_audio,
            "output_mapping",
            default=default_audio.output_mapping,
        )
    )
    args.blocksize = prefer(args.blocksize, config, *device_audio, "blocksize", default=0)
    args.steering_output = prefer(
        args.steering_output,
        config,
        *device_steering,
        "output",
        default=default_steering.output,
    )
    args.steering_channel = prefer(
        args.steering_channel,
        config,
        *device_steering,
        "channel",
        default=default_steering.channel,
    )
    args.preset_wait = prefer(
        args.preset_wait,
        config,
        *device_steering,
        "preset_wait_seconds",
        default=default_steering.preset_wait_seconds,
    )
    args.snapshot_wait = prefer(
        args.snapshot_wait,
        config,
        *device_steering,
        "snapshot_wait_seconds",
        default=default_steering.snapshot_wait_seconds,
    )
    args.measurement_wait = prefer(
        args.measurement_wait,
        config,
        *device_steering,
        "measurement_wait_seconds",
        default=default_steering.measurement_wait_seconds,
    )
    args.pre_roll = prefer(args.pre_roll, config, "analysis", "pre_roll_seconds", default=0.2)
    args.post_roll = prefer(args.post_roll, config, "analysis", "post_roll_seconds", default=0.1)
    args.round_trip_latency = prefer(
        args.round_trip_latency,
        config,
        "analysis",
        "round_trip_latency_seconds",
        default=0.02,
    )
    args.policy = _normalization_policy(config, args)
    args.analysis_options = _analysis_options(config, args)
    return args


def run_command(args: list[object], timeout: float | None = None) -> None:
    subprocess.run(
        [str(arg) for arg in args],
        check=True,
        text=True,
        timeout=timeout,
    )


def _is_windows() -> bool:
    return os.name == "nt"


def _is_matchpatch_executable(path: Path) -> bool:
    return path.name.casefold() in {"matchpatch", "matchpatch.exe"}


def _windows_measure_command(executable: Path, command: str) -> list[object]:
    if _is_matchpatch_executable(executable):
        return [executable, "--cli", "measure", command]
    return [executable, "-m", "matchpatch.measure", command]


def wsl_path_to_windows(path: Path) -> str:
    text = str(path)
    if _is_windows() or re.match(r"^[A-Za-z]:[\\/]", text) or text.startswith("\\\\"):
        return text

    completed = subprocess.run(
        ["wslpath", "-w", str(path.resolve())],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return completed.stdout.strip()


def _missing_windows_environment_message() -> str:
    if _is_windows():
        return (
            "Native Windows MatchPatch environment is missing. Run scripts\\sync-windows.cmd first."
        )
    return (
        "Native Windows MatchPatch environment is missing. "
        "Run scripts/sync-windows-from-wsl.sh first."
    )


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
        raise RuntimeError(_missing_windows_environment_message())

    command: list[object] = [
        *_windows_measure_command(windows_python, "measure"),
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
        "--pre-roll": getattr(args, "pre_roll", None),
        "--post-roll": getattr(args, "post_roll", None),
        "--round-trip-latency": getattr(args, "round_trip_latency", None),
        "--snapshot-count": getattr(args, "policy", NormalizationPolicy()).snapshot_count,
        "--analysis-window": getattr(args, "analysis_options", AnalysisOptions()).window_seconds,
        "--analysis-interval": getattr(
            args, "analysis_options", AnalysisOptions()
        ).interval_seconds,
        "--minimum-valid-lufs": getattr(
            args, "analysis_options", AnalysisOptions()
        ).minimum_valid_lufs,
    }
    path_values = {
        "--playback-toggle-file": getattr(args, "playback_toggle_path", None),
        "--recordings-dir": getattr(args, "recorded_output_dir", None),
    }

    for option, value in optional_values.items():
        if value is not None:
            command.extend([option, value])
    for option, value in path_values.items():
        if value is not None:
            command.extend([option, wsl_path_to_windows(Path(value))])
    snapshot_plan = getattr(args, "snapshot_plan", ())
    if snapshot_plan:
        command.extend(["--snapshot-plan", _format_snapshot_plan(snapshot_plan)])
    if getattr(args, "play_recorded_output", False):
        command.append("--play-recorded-output")

    if on_progress is None:
        try:
            run_command(command, timeout=args.timeout)
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("Timed out waiting for native Windows analysis") from exc
        return

    command.append("--progress-jsonl")
    _run_progress_command(command, args.timeout, on_progress, cancel_requested)


def _format_snapshot_plan(snapshot_plan: tuple[tuple[str, tuple[int, ...]], ...]) -> str:
    return ";".join(
        f"{patch}={','.join(str(snapshot) for snapshot in snapshots)}"
        for patch, snapshots in snapshot_plan
        if snapshots
    )


def run_windows_optimization(
    args: argparse.Namespace | NormalizationRequest,
    preset_id: int,
    *,
    stability_runs: int,
    termination_tolerance: float,
    stability_tolerance: float,
    pinned_parameters: tuple[str, ...] = (),
    on_progress: Callable[[OptimizationProgress], None] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> str:
    windows_python = Path(args.windows_python).resolve()

    if not windows_python.exists():
        raise RuntimeError(_missing_windows_environment_message())

    command: list[object] = [
        *_windows_measure_command(windows_python, "optimize"),
        "--device",
        args.device,
        "--backend",
        args.backend,
        "--preset-id",
        preset_id,
        "--reference-di",
        wsl_path_to_windows(Path(args.reference_di)),
        "--stability-runs",
        stability_runs,
        "--termination-tolerance",
        termination_tolerance,
        "--stability-tolerance",
        stability_tolerance,
    ]
    for parameter in pinned_parameters:
        command.extend(["--pinned-parameter", parameter])

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
        "--pre-roll": getattr(args, "pre_roll", None),
        "--post-roll": getattr(args, "post_roll", None),
        "--round-trip-latency": getattr(args, "round_trip_latency", None),
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
    playback_toggle_path = getattr(args, "playback_toggle_path", None)
    if playback_toggle_path is not None:
        command.extend(["--playback-toggle-file", wsl_path_to_windows(Path(playback_toggle_path))])
    if getattr(args, "play_recorded_output", False):
        command.append("--play-recorded-output")

    if on_progress is None:
        completed = subprocess.run(
            [str(arg) for arg in command],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            timeout=args.timeout,
        )
        return completed.stdout.strip()

    command.append("--progress-jsonl")
    return _run_optimization_progress_command(
        command,
        args.timeout,
        on_progress,
        cancel_requested,
    )


def _windows_hardware_command(
    args: argparse.Namespace | NormalizationRequest,
    *,
    diagnostics_json: bool = False,
) -> list[object]:
    windows_python = Path(args.windows_python).resolve()

    if not windows_python.exists():
        raise RuntimeError(_missing_windows_environment_message())

    command: list[object] = [
        *_windows_measure_command(windows_python, "check-hardware"),
        "--device",
        args.device,
    ]

    optional_values = {
        "--audio-device": args.audio_device,
        "--steering-output": args.steering_output,
        "--steering-channel": args.steering_channel,
        "--sample-rate": args.sample_rate,
        "--input-mapping": args.input_mapping,
        "--output-mapping": args.output_mapping,
        "--blocksize": getattr(args, "blocksize", None),
        "--preset-wait": getattr(args, "preset_wait", None),
        "--snapshot-wait": getattr(args, "snapshot_wait", None),
        "--measurement-wait": getattr(args, "measurement_wait", None),
        "--pre-roll": getattr(args, "pre_roll", None),
        "--post-roll": getattr(args, "post_roll", None),
        "--round-trip-latency": getattr(args, "round_trip_latency", None),
    }

    for option, value in optional_values.items():
        if value is not None:
            command.extend([option, value])

    if diagnostics_json:
        command.append("--diagnostics-json")

    return command


def check_windows_hardware(args: argparse.Namespace | NormalizationRequest) -> None:
    checks = collect_windows_hardware_diagnostics(args)
    if any(check.status == "fail" for check in checks):
        raise RuntimeError(summarize_failed_checks(checks))


def collect_windows_hardware_diagnostics(
    args: argparse.Namespace | NormalizationRequest,
) -> list[DiagnosticCheck]:
    try:
        command = _windows_hardware_command(args, diagnostics_json=True)
    except RuntimeError as exc:
        return [
            DiagnosticCheck(
                "windows_hardware_check",
                "fail",
                str(exc),
                f"windows_python={getattr(args, 'windows_python', '')}",
            )
        ]

    try:
        completed = subprocess.run(
            [str(arg) for arg in command],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=args.timeout,
        )
    except subprocess.TimeoutExpired:
        return [
            DiagnosticCheck(
                "windows_hardware_check",
                "fail",
                "Native Windows hardware check timed out",
                f"timeout={args.timeout}",
            )
        ]

    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError:
        if completed.returncode == 0 and not completed.stdout.strip():
            return [
                DiagnosticCheck(
                    "windows_hardware_check",
                    "pass",
                    "Native Windows hardware check completed",
                )
            ]
        message = (completed.stderr or completed.stdout or "").strip()
        return [
            DiagnosticCheck(
                "windows_hardware_check",
                "fail",
                message or "Native Windows hardware check failed without structured output",
            )
        ]

    checks = _diagnostic_checks_from_native_payload(data)
    if checks:
        return checks

    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "").strip()
        return [
            DiagnosticCheck(
                "windows_hardware_check",
                "fail",
                message or "Native Windows hardware check failed",
            )
        ]

    return [
        DiagnosticCheck(
            "windows_hardware_check",
            "warning",
            "Native Windows hardware check returned no checks",
        )
    ]


def collect_windows_hardware_preflight(
    args: argparse.Namespace | NormalizationRequest,
) -> HardwarePreflightResult:
    return HardwarePreflightResult.from_diagnostic_checks(
        args.device,
        getattr(args, "backend", "hardware"),
        collect_windows_hardware_diagnostics(args),
    )


def _diagnostic_checks_from_native_payload(data: object) -> list[DiagnosticCheck]:
    if isinstance(data, list):
        return [
            diagnostic_check_from_dict(cast("Mapping[str, object]", item))
            for item in data
            if isinstance(item, Mapping)
        ]
    if isinstance(data, Mapping):
        checks = data.get("checks")
        if isinstance(checks, list):
            return [
                diagnostic_check_from_dict(cast("Mapping[str, object]", item))
                for item in checks
                if isinstance(item, Mapping)
            ]
    return []


def _run_progress_command(
    command: list[object],
    timeout: float | None,
    on_progress: Callable[[ProgressEvent], None],
    cancel_requested: Callable[[], bool] | None = None,
) -> None:
    process = _start_process(command)

    def parse_stdout(text: str) -> None:
        try:
            on_progress(ProgressEvent.from_json(text))
        except ValueError as exc:
            raise RuntimeError(
                f"Invalid progress output from native Windows analysis: {text}"
            ) from exc

    def parse_stderr(text: str) -> None:
        on_progress(ProgressEvent("error_log", message=text.rstrip()))

    try:
        _read_progress_lines(
            process,
            timeout,
            cancel_requested,
            "Normalization cancelled by user",
            "Timed out waiting for native Windows analysis",
            parse_stdout,
            parse_stderr,
        )
        _finish_progress_process(
            process,
            command,
            lambda return_code: subprocess.CalledProcessError(
                return_code, [str(arg) for arg in command]
            ),
        )
    finally:
        _cleanup_progress_process(process)


def _run_optimization_progress_command(
    command: list[object],
    timeout: float | None,
    on_progress: Callable[[OptimizationProgress], None],
    cancel_requested: Callable[[], bool] | None = None,
) -> str:
    process = _start_process(command)
    result_toml = ""
    error_lines: list[str] = []

    def parse_stdout(text: str) -> None:
        nonlocal result_toml
        event = _parse_optimization_progress(text)
        if event.result_toml is not None:
            result_toml = event.result_toml
        on_progress(event)

    def parse_stderr(text: str) -> None:
        stripped = text.rstrip()
        if stripped:
            error_lines.append(stripped)

    try:
        _read_progress_lines(
            process,
            timeout,
            cancel_requested,
            "Measurement optimization cancelled by user",
            "Timed out waiting for native Windows optimization",
            parse_stdout,
            parse_stderr,
        )
        _finish_progress_process(
            process,
            command,
            lambda return_code: _optimization_progress_error(return_code, error_lines),
        )
    finally:
        _cleanup_progress_process(process)

    return result_toml


def _start_process(command: list[object]) -> subprocess.Popen[str]:
    process = subprocess.Popen(  # noqa: S603
        [str(arg) for arg in command],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
    )
    return process


def _read_progress_lines(
    process: subprocess.Popen[str],
    timeout: float | None,
    cancel_requested: Callable[[], bool] | None,
    cancel_message: str,
    timeout_message: str,
    parse_stdout: Callable[[str], None],
    parse_stderr: Callable[[str], None],
) -> None:
    lines: queue.Queue[tuple[str, str] | None] = queue.Queue()
    _start_progress_readers(process, lines)
    deadline = time.monotonic() + timeout if timeout is not None else None
    open_streams = 2

    while open_streams or process.poll() is None:
        _raise_if_progress_cancelled(cancel_requested, cancel_message)
        _raise_if_progress_timed_out(deadline, timeout_message)

        try:
            line = lines.get(timeout=0.1)
        except queue.Empty:
            continue

        if line is None:
            open_streams -= 1
            continue

        stream_name, text = line
        if stream_name == "stderr":
            parse_stderr(text)
        else:
            parse_stdout(text)


def _start_progress_readers(
    process: subprocess.Popen[str],
    lines: queue.Queue[tuple[str, str] | None],
) -> None:
    threading.Thread(
        target=_read_process_stream,
        args=(process, "stdout", lines),
        daemon=True,
    ).start()
    threading.Thread(
        target=_read_process_stream,
        args=(process, "stderr", lines),
        daemon=True,
    ).start()


def _read_process_stream(
    process: subprocess.Popen[str],
    name: str,
    lines: queue.Queue[tuple[str, str] | None],
) -> None:
    stream = getattr(process, name)
    assert stream is not None

    for line in stream:
        lines.put((name, line))

    lines.put(None)


def _raise_if_progress_cancelled(
    cancel_requested: Callable[[], bool] | None,
    message: str,
) -> None:
    if cancel_requested is not None and cancel_requested():
        raise RuntimeError(message)


def _raise_if_progress_timed_out(deadline: float | None, message: str) -> None:
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError(message)


def _finish_progress_process(
    process: subprocess.Popen[str],
    command: list[object],
    error_factory: Callable[[int], BaseException],
) -> None:
    return_code = process.wait()
    if return_code:
        raise error_factory(return_code)


def _parse_optimization_progress(text: str) -> OptimizationProgress:
    try:
        return OptimizationProgress.from_json(text)
    except ValueError as exc:
        raise RuntimeError(
            f"Invalid progress output from native Windows optimization: {text}"
        ) from exc


def _optimization_progress_error(return_code: int, error_lines: list[str]) -> RuntimeError:
    detail = "\n".join(error_lines).strip()
    if detail:
        return RuntimeError(detail)
    return RuntimeError(f"Native Windows optimization failed with exit status {return_code}")


def _cleanup_progress_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    cleanup = threading.Thread(target=_kill_process, args=(process,), daemon=True)
    cleanup.start()
    cleanup.join(PROCESS_REAP_TIMEOUT_SECONDS)


def _kill_process(process: subprocess.Popen[str]) -> None:
    try:
        process.kill()
    except OSError:
        return
    try:
        process.wait(timeout=PROCESS_REAP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="TOML configuration file")
    parser.add_argument("--device", required=True, help="Audio processor profile")
    parser.add_argument("-i", "--input", required=True)
    parser.add_argument("-o", "--output")
    parser.add_argument(
        "--diff-input",
        help="Previous version of the input file; only changed presets are normalized",
    )
    parser.add_argument("-a", "--automation", action="store_true")
    parser.add_argument("-S", "--preset-set")
    parser.add_argument("-n", "--limit", type=int)
    parser.add_argument("--keep-temp", action="store_true")
    parser.add_argument("--target-lufs", type=float)
    parser.add_argument("--solo-regex")
    parser.add_argument("--ignore-snapshot-regex")
    parser.add_argument("--solo-gain-bump-db", type=float)
    parser.add_argument("--snapshot-count", type=int)
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
    parser.add_argument("--custom-adjustments-file")
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
    parser.add_argument("--pre-roll", type=float)
    parser.add_argument("--post-roll", type=float)
    parser.add_argument("--round-trip-latency", type=float)
    parser.add_argument("--analysis-window", type=float)
    parser.add_argument("--analysis-interval", type=float)
    parser.add_argument("--minimum-valid-lufs", type=float)
    parser.add_argument("--play-recorded-output", action="store_true")
    parser.add_argument("--record-device-output", action="store_true")
    parser.add_argument("--playback-toggle-path")
    parser.add_argument("--recorded-output-dir")
    parser.add_argument("--timeout", type=float)
    return parser.parse_args(argv)


def request_from_args(args: argparse.Namespace) -> NormalizationRequest:
    return NormalizationRequest(
        device=args.device,
        input_path=Path(args.input),
        output_path=Path(args.output) if args.output else None,
        diff_input_path=Path(args.diff_input) if args.diff_input else None,
        automation=args.automation,
        preset_set=args.preset_set,
        limit=args.limit,
        keep_temp=args.keep_temp,
        ignore_bad_lufs=args.ignore_bad_lufs,
        target_lufs=args.target_lufs,
        backend=args.backend,
        windows_python=args.windows_python,
        reference_di=Path(args.reference_di),
        custom_adjustments_path=(
            Path(args.custom_adjustments_file) if args.custom_adjustments_file else None
        ),
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
        pre_roll=args.pre_roll,
        post_roll=args.post_roll,
        round_trip_latency=args.round_trip_latency,
        simulate_fail_presets=args.simulate_fail_presets,
        play_recorded_output=getattr(args, "play_recorded_output", False),
        record_device_output=getattr(args, "record_device_output", False),
        playback_toggle_path=(
            Path(args.playback_toggle_path) if getattr(args, "playback_toggle_path", None) else None
        ),
        recorded_output_dir=(
            Path(args.recorded_output_dir) if getattr(args, "recorded_output_dir", None) else None
        ),
        timeout=args.timeout,
        policy=args.policy,
        analysis_options=args.analysis_options,
    )


def _cli_confirm_import(request: ImportRequest) -> bool:
    wait_for_user_confirmation(request.message)
    return True


def _cli_progress(event: ProgressEvent) -> None:
    if event.phase == "preparing_measurement":
        print("Creating measurement file")
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
        make_temp_dir=lambda: Path(tempfile.mkdtemp(prefix="matchpatch_normalization_")),
    )
    print()
    print("[OK] Gain-adjusted patch file written")
    print(f"Output: {result.output_path}")
