from __future__ import annotations

import argparse
import csv
import subprocess
import threading
from pathlib import Path

import pytest

from matchpatch import normalize
from matchpatch.devices.base import PatchAssignment
from matchpatch.workflow import NormalizationRequest, export_adjusted_file, normalize_presets


class FakeHandler:
    def __init__(self) -> None:
        self.applied = []
        self.measurement_files = []

    def validate_input(self, input_path: Path) -> None:
        return None

    def validate_output(self, input_path: Path, output_path: Path) -> None:
        return None

    def automation_output_path(self, input_path: Path, postfix: str) -> Path:
        return input_path.with_name(input_path.stem + postfix + input_path.suffix)

    def create_measurement_file(self, input_path: Path, output_path: Path) -> None:
        self.measurement_files.append((input_path, output_path))

    def parse_patch_set(self, value: str) -> list[int]:
        return [int(item) for item in value.split(",")]

    def list_assignments(self, input_path: Path) -> list[PatchAssignment]:
        return [PatchAssignment(1, "patch-1", "One"), PatchAssignment(2, "patch-2", "Two")]

    def diff_preset_ids(self, input_path: Path, previous_input_path: Path) -> list[int]:
        return [2]

    def select_preset_ids(self, input_path, assignments, requested_ids):
        return requested_ids if requested_ids is not None else [item.id for item in assignments]

    def format_patch_id(self, preset_id: int) -> str:
        return f"patch-{preset_id}"

    def apply_analysis_csv(self, *args) -> None:
        self.applied.append(args)


class FakeProfile:
    name = "fake"
    display_name = "Fake Processor"

    def __init__(self, handler: FakeHandler) -> None:
        self.handler = handler

    def create_patch_file_handler(self, project_dir: Path) -> FakeHandler:
        return self.handler


def test_count_csv_rows_handles_header(tmp_path) -> None:
    csv_path = tmp_path / "results.csv"
    csv_path.write_text("Preset,DevicePatch\n1,patch-1\n2,patch-2\n", encoding="utf-8")

    assert normalize.count_csv_rows(csv_path) == 2


def test_normalize_presets_filters_to_diff_input(tmp_path) -> None:
    handler = FakeHandler()
    input_path = tmp_path / "input.hls"
    previous_path = tmp_path / "previous.hls"
    output_path = tmp_path / "output.hls"
    reference = tmp_path / "reference.wav"
    work_dir = tmp_path / "work"
    input_path.touch()
    previous_path.touch()
    reference.touch()
    work_dir.mkdir()
    measured = []

    def fake_analysis(request, preset_ids, csv_path, callback):
        measured.append(preset_ids)
        write_analysis_csv(request, preset_ids, csv_path)

    normalize_presets(
        NormalizationRequest(
            device="fake",
            input_path=input_path,
            output_path=output_path,
            diff_input_path=previous_path,
            backend="loopback",
            windows_python="python.exe",
            reference_di=reference,
            automation=False,
        ),
        run_analysis=fake_analysis,
        get_profile=lambda device: FakeProfile(handler),
        make_temp_dir=lambda: work_dir,
    )

    assert measured == [[2]]


def test_request_from_args_includes_diff_input() -> None:
    args = normalize.apply_config(
        normalize.parse_args(
            [
                "--device",
                "helix",
                "-i",
                "current.hls",
                "--diff-input",
                "previous.hls",
            ]
        )
    )

    assert normalize.request_from_args(args).diff_input_path == Path("previous.hls")


def test_subprocess_helpers_delegate_and_translate_paths(tmp_path, monkeypatch) -> None:
    calls = []
    completed = subprocess.CompletedProcess([], 0, stdout="C:\\MatchPatch\\file.hls\n")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: calls.append((args, kwargs)) or completed,
    )

    normalize.run_command(["tool", Path("input.hls")], timeout=3)
    assert normalize.wsl_path_to_windows(tmp_path / "file.hls") == "C:\\MatchPatch\\file.hls"
    assert calls[0] == ((["tool", "input.hls"],), {"check": True, "text": True, "timeout": 3})
    assert calls[1][0][0][0:2] == ["wslpath", "-w"]


def test_wait_for_user_confirmation_prompts(monkeypatch, capsys) -> None:
    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt))

    normalize.wait_for_user_confirmation("Import the patch")

    assert "Import the patch" in capsys.readouterr().out
    assert prompts == ["Press Enter to continue..."]


def test_apply_config_layers_cli_environment_and_toml(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[normalize]
backend = "hardware"
reference_di = "configured.wav"
target_lufs = -18.0
timeout_seconds = 90
ignore_bad_lufs = true

[devices.helix.audio]
device = "Configured Audio"
sample_rate = 44100
input_mapping = [3, 4]
output_mapping = [5, 6]
blocksize = 128

[devices.helix.steering]
output = "Configured MIDI"
channel = 2
preset_wait_seconds = 0.8
snapshot_wait_seconds = 0.1
measurement_wait_seconds = 0.7

[policy]
measured_snapshots = 3
solo_marker = "lead"
solo_gain_bump_db = 4.0
crest_factor_reference_db = 11.0
crest_factor_correction_ratio = 0.5
max_crest_factor_correction_db = 2.0
gain_deadband_db = 0.1

[analysis]
window_seconds = 2.0
interval_seconds = 0.2
minimum_valid_lufs = -90.0
pre_roll_seconds = 1.5
post_roll_seconds = 2.0
round_trip_latency_seconds = 0.03
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("MATCHPATCH_BACKEND", "loopback")
    monkeypatch.setenv("MATCHPATCH_REFERENCE_DI", "environment.wav")
    args = normalize.apply_config(
        normalize.parse_args(
            [
                "--config",
                str(config_path),
                "--device",
                "helix",
                "-i",
                "input.hls",
                "--target-lufs",
                "-17",
                "--audio-device",
                "CLI Audio",
            ]
        )
    )

    assert args.backend == "loopback"
    assert args.reference_di == "environment.wav"
    assert args.target_lufs == -17
    assert args.audio_device == "CLI Audio"
    assert args.input_mapping == "3,4"
    assert args.output_mapping == "5,6"
    assert args.blocksize == 128
    assert args.steering_output == "Configured MIDI"
    assert args.policy.snapshot_count == 3
    assert args.policy.solo_regex == "lead"
    assert args.analysis_options.window_seconds == 2.0
    assert args.pre_roll == 1.5
    assert args.post_roll == 2.0
    assert args.round_trip_latency == 0.03


def test_apply_config_rejects_invalid_snapshot_count(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[policy]\nmeasured_snapshots = 0\n", encoding="utf-8")

    with pytest.raises(ValueError, match="at least 1"):
        normalize.apply_config(
            normalize.parse_args(
                ["--config", str(config_path), "--device", "helix", "-i", "input.hls"]
            )
        )


def test_apply_config_cli_snapshot_count_overrides_toml(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[policy]\nmeasured_snapshots = 3\n", encoding="utf-8")

    args = normalize.apply_config(
        normalize.parse_args(
            [
                "--config",
                str(config_path),
                "--device",
                "helix",
                "-i",
                "input.hls",
                "--snapshot-count",
                "6",
            ]
        )
    )

    assert args.policy.snapshot_count == 6


def test_apply_config_rejects_snapshot_count_above_device_limit() -> None:
    with pytest.raises(ValueError, match="must not exceed 8"):
        normalize.apply_config(
            normalize.parse_args(["--device", "helix", "-i", "input.hls", "--snapshot-count", "9"])
        )


def test_apply_config_rejects_invalid_solo_regex(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[policy]\nsolo_regex = '('\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid solo snapshot regex"):
        normalize.apply_config(
            normalize.parse_args(
                ["--config", str(config_path), "--device", "helix", "-i", "input.hls"]
            )
        )


def test_run_windows_analysis_builds_worker_command(tmp_path, monkeypatch) -> None:
    windows_python = tmp_path / "python.exe"
    windows_python.touch()
    csv_path = tmp_path / "results.csv"
    reference = tmp_path / "reference.wav"
    args = argparse.Namespace(
        windows_python=str(windows_python),
        device="helix",
        backend="loopback",
        reference_di=str(reference),
        audio_device="Helix",
        steering_output=None,
        steering_channel=2,
        sample_rate=None,
        input_mapping="1,2",
        output_mapping=None,
        simulate_fail_presets="6,7",
        pre_roll=1.5,
        post_roll=2.0,
        round_trip_latency=0.03,
        timeout=12.0,
    )
    calls = []
    monkeypatch.setattr(normalize, "wsl_path_to_windows", lambda path: f"WIN:{path.name}")
    monkeypatch.setattr(
        normalize, "run_command", lambda command, timeout=None: calls.append((command, timeout))
    )

    normalize.run_windows_analysis(args, [1, 6], csv_path)

    command, timeout = calls[0]
    assert command[:5] == [
        windows_python.resolve(),
        "-m",
        "matchpatch.measure",
        "measure",
        "--device",
    ]
    assert "1,6" in command
    audio_index = command.index("--audio-device")
    assert command[audio_index : audio_index + 2] == ["--audio-device", "Helix"]
    failure_index = command.index("--simulate-fail-presets")
    assert command[failure_index : failure_index + 2] == ["--simulate-fail-presets", "6,7"]
    assert command[command.index("--pre-roll") : command.index("--pre-roll") + 2] == [
        "--pre-roll",
        1.5,
    ]
    assert command[
        command.index("--round-trip-latency") : command.index("--round-trip-latency") + 2
    ] == ["--round-trip-latency", 0.03]
    assert timeout == 12.0


def test_run_windows_analysis_reports_missing_environment(tmp_path) -> None:
    args = argparse.Namespace(windows_python=str(tmp_path / "missing.exe"))

    with pytest.raises(RuntimeError, match="sync-windows"):
        normalize.run_windows_analysis(args, [1], tmp_path / "results.csv")


def test_check_windows_hardware_builds_worker_command(tmp_path, monkeypatch) -> None:
    windows_python = tmp_path / "python.exe"
    windows_python.touch()
    args = argparse.Namespace(
        windows_python=str(windows_python),
        device="helix",
        audio_device="Helix",
        steering_output="Helix MIDI",
        steering_channel=2,
        sample_rate=48000,
        input_mapping="1,2",
        output_mapping="3,4",
        blocksize=128,
        preset_wait=None,
        snapshot_wait=None,
        measurement_wait=None,
        timeout=5,
    )
    calls = []
    monkeypatch.setattr(
        normalize.subprocess,
        "run",
        lambda command, **kwargs: calls.append((command, kwargs))
        or subprocess.CompletedProcess(command, 0, stdout="", stderr=""),
    )

    normalize.check_windows_hardware(args)

    command, kwargs = calls[0]
    assert command[:5] == [
        str(windows_python.resolve()),
        "-m",
        "matchpatch.measure",
        "check-hardware",
        "--device",
    ]
    assert command[command.index("--audio-device") : command.index("--audio-device") + 2] == [
        "--audio-device",
        "Helix",
    ]
    assert command[command.index("--steering-output") : command.index("--steering-output") + 2] == [
        "--steering-output",
        "Helix MIDI",
    ]
    assert command[command.index("--output-mapping") : command.index("--output-mapping") + 2] == [
        "--output-mapping",
        "3,4",
    ]
    assert kwargs["timeout"] == 5
    assert kwargs["stdout"] == subprocess.PIPE
    assert kwargs["stderr"] == subprocess.PIPE


def test_run_windows_analysis_translates_timeout(tmp_path, monkeypatch) -> None:
    windows_python = tmp_path / "python.exe"
    windows_python.touch()
    args = argparse.Namespace(
        windows_python=str(windows_python),
        device="helix",
        backend="loopback",
        reference_di=str(tmp_path / "reference.wav"),
        audio_device=None,
        steering_output=None,
        steering_channel=None,
        sample_rate=None,
        input_mapping=None,
        output_mapping=None,
        simulate_fail_presets=None,
        timeout=1,
    )
    monkeypatch.setattr(normalize, "wsl_path_to_windows", lambda path: str(path))
    monkeypatch.setattr(
        normalize,
        "run_command",
        lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired("worker", 1)),
    )

    with pytest.raises(TimeoutError, match="Windows analysis"):
        normalize.run_windows_analysis(args, [1], tmp_path / "results.csv")


def test_progress_command_parses_json_lines(monkeypatch) -> None:
    events = []

    class FakeProcess:
        stdout = ['{"kind":"preset_started","device_patch":"01A"}\n']
        stderr = []

        def poll(self):
            return 0

        def wait(self):
            return 0

    monkeypatch.setattr(normalize.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())

    normalize._run_progress_command(["worker"], None, events.append)

    assert events == [normalize.ProgressEvent("preset_started", device_patch="01A")]


def test_progress_command_forwards_stderr_as_log_event(monkeypatch) -> None:
    events = []

    class FakeProcess:
        stdout = []
        stderr = ["worker detail\n"]

        def poll(self):
            return 0

        def wait(self):
            return 0

    monkeypatch.setattr(normalize.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())

    normalize._run_progress_command(["worker"], None, events.append)

    assert events == [normalize.ProgressEvent("error_log", message="worker detail")]


def test_progress_command_does_not_hang_when_cancelled_process_cannot_be_reaped(
    monkeypatch,
) -> None:
    class FakeProcess:
        stdout = []
        stderr = []

        def __init__(self) -> None:
            self.killed = False
            self.wait_timeout = None

        def poll(self):
            return None

        def kill(self) -> None:
            self.killed = True

        def wait(self, timeout=None):
            self.wait_timeout = timeout
            raise subprocess.TimeoutExpired("worker", timeout)

    process = FakeProcess()
    monkeypatch.setattr(normalize.subprocess, "Popen", lambda *args, **kwargs: process)

    with pytest.raises(RuntimeError, match="cancelled"):
        normalize._run_progress_command(["worker"], None, lambda event: None, lambda: True)

    assert process.killed
    assert process.wait_timeout == normalize.PROCESS_REAP_TIMEOUT_SECONDS


def test_progress_command_does_not_hang_when_cancelled_process_kill_stalls(
    monkeypatch,
) -> None:
    kill_started = threading.Event()
    release_kill = threading.Event()

    class FakeProcess:
        stdout = []
        stderr = []

        def poll(self):
            return None

        def kill(self) -> None:
            kill_started.set()
            release_kill.wait()

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(normalize, "PROCESS_REAP_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(normalize.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())

    try:
        with pytest.raises(RuntimeError, match="cancelled"):
            normalize._run_progress_command(["worker"], None, lambda event: None, lambda: True)
        assert kill_started.is_set()
    finally:
        release_kill.set()


def test_main_runs_measurement_and_applies_csv(tmp_path, monkeypatch) -> None:
    handler = FakeHandler()
    profile = FakeProfile(handler)
    input_path = tmp_path / "input.hls"
    output_path = tmp_path / "output.hls"
    reference = tmp_path / "reference.wav"
    input_path.touch()
    reference.touch()
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    def fake_analysis(args, preset_ids, csv_path):
        with csv_path.open("w", encoding="utf-8", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=["Preset", "DevicePatch"])
            writer.writeheader()
            for preset_id in preset_ids:
                writer.writerow({"Preset": preset_id, "DevicePatch": f"patch-{preset_id}"})

    monkeypatch.setattr(normalize, "get_device_profile", lambda device: profile)
    monkeypatch.setattr(normalize.tempfile, "mkdtemp", lambda **kwargs: str(work_dir))
    monkeypatch.setattr(normalize, "run_windows_analysis", fake_analysis)

    normalize.main(
        [
            "--device",
            "fake",
            "-i",
            str(input_path),
            "-o",
            str(output_path),
            "--reference-di",
            str(reference),
            "--limit",
            "1",
        ]
    )

    assert len(handler.applied) == 1
    assert handler.applied[0][0:2] == (input_path.resolve(), output_path.resolve())
    assert not work_dir.exists()


def write_analysis_csv(args, preset_ids, csv_path) -> None:
    with csv_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=["Preset", "DevicePatch"])
        writer.writeheader()
        for preset_id in preset_ids:
            writer.writerow({"Preset": preset_id, "DevicePatch": f"patch-{preset_id}"})


def test_gui_style_workflow_defers_adjusted_file_export(tmp_path) -> None:
    class PreviewHandler(FakeHandler):
        def set_log_callback(self, callback) -> None:
            self.log_callback = callback

        def apply_analysis_csv(self, *args) -> None:
            super().apply_analysis_csv(*args)
            args[1].touch()
            self.log_callback("[GAIN] patch-1 Clean | stable at 0.0 dB (Delta: +0.0 dB)")

    handler = PreviewHandler()
    input_path = tmp_path / "input.hls"
    reference = tmp_path / "reference.wav"
    work_dir = tmp_path / "work"
    input_path.touch()
    reference.touch()
    work_dir.mkdir()
    confirmations = []
    events = []

    result = normalize_presets(
        NormalizationRequest(
            device="fake",
            input_path=input_path,
            backend="loopback",
            windows_python="python.exe",
            reference_di=reference,
            defer_export=True,
        ),
        run_analysis=lambda request, preset_ids, csv_path, callback: write_analysis_csv(
            request, preset_ids, csv_path
        ),
        on_progress=events.append,
        confirm_import=lambda request: confirmations.append(request.kind) or True,
        get_profile=lambda device: FakeProfile(handler),
        make_temp_dir=lambda: work_dir,
    )

    assert confirmations == ["measurement"]
    assert len(handler.applied) == 1
    assert handler.applied[0][0:3] == (
        input_path.resolve(),
        work_dir / "input_preview.hls",
        work_dir / "lufs_analysis.csv",
    )
    assert not (work_dir / "input_preview.hls").exists()
    assert any(event.kind == "log" and event.message.startswith("[GAIN]") for event in events)
    assert result.output_path is None
    assert result.temp_dir == work_dir
    assert result.retained_csv_path == work_dir / "lufs_analysis.csv"


def test_export_adjusted_file_applies_retained_csv(tmp_path) -> None:
    handler = FakeHandler()
    input_path = tmp_path / "input.hls"
    output_path = tmp_path / "output.hls"
    csv_path = tmp_path / "lufs_analysis.csv"
    input_path.touch()

    export_adjusted_file(
        NormalizationRequest(
            device="fake",
            input_path=input_path,
            backend="loopback",
            windows_python="python.exe",
            reference_di=tmp_path / "reference.wav",
        ),
        csv_path,
        output_path,
        get_profile=lambda device: FakeProfile(handler),
    )

    assert handler.applied[0][0:3] == (input_path.resolve(), output_path.resolve(), csv_path)


def test_export_adjusted_file_passes_complete_csv_through(tmp_path) -> None:
    handler = FakeHandler()
    input_path = tmp_path / "input.hls"
    output_path = tmp_path / "output.hls"
    csv_path = tmp_path / "lufs_analysis.csv"
    input_path.touch()
    csv_path.write_text("Preset,DevicePatch\n1,01A\n2,01B\n", encoding="utf-8")

    export_adjusted_file(
        NormalizationRequest(
            device="fake",
            input_path=input_path,
            backend="loopback",
            windows_python="python.exe",
            reference_di=tmp_path / "reference.wav",
        ),
        csv_path,
        output_path,
        get_profile=lambda device: FakeProfile(handler),
    )

    assert handler.applied[0][2] == csv_path


def test_main_automation_creates_measurement_file_confirms_and_keeps_temp(
    tmp_path, monkeypatch
) -> None:
    handler = FakeHandler()
    input_path = tmp_path / "input.hls"
    reference = tmp_path / "reference.wav"
    work_dir = tmp_path / "work"
    input_path.touch()
    reference.touch()
    work_dir.mkdir()
    confirmations = []
    monkeypatch.setattr(normalize, "get_device_profile", lambda device: FakeProfile(handler))
    monkeypatch.setattr(normalize.tempfile, "mkdtemp", lambda **kwargs: str(work_dir))
    monkeypatch.setattr(normalize, "run_windows_analysis", write_analysis_csv)
    monkeypatch.setattr(normalize, "wait_for_user_confirmation", confirmations.append)

    normalize.main(
        [
            "--device",
            "fake",
            "-i",
            str(input_path),
            "--reference-di",
            str(reference),
            "--automation",
            "--keep-temp",
            "-S",
            "2",
        ]
    )

    assert handler.measurement_files == [(input_path.resolve(), tmp_path / "input_measurement.hls")]
    assert len(confirmations) == 2
    assert handler.applied[0][1] == tmp_path / "input_adjusted.hls"
    assert work_dir.exists()


def test_main_rejects_missing_reference_di(tmp_path, monkeypatch) -> None:
    input_path = tmp_path / "input.hls"
    input_path.touch()
    monkeypatch.setattr(normalize, "get_device_profile", lambda device: FakeProfile(FakeHandler()))

    with pytest.raises(ValueError, match="Reference DI WAV"):
        normalize.main(
            [
                "--device",
                "fake",
                "-i",
                str(input_path),
                "-o",
                str(tmp_path / "output.hls"),
                "--reference-di",
                str(tmp_path / "missing.wav"),
            ]
        )


def test_main_rejects_empty_preset_selection(tmp_path, monkeypatch) -> None:
    handler = FakeHandler()
    handler.select_preset_ids = lambda *args: []
    input_path = tmp_path / "input.hls"
    reference = tmp_path / "reference.wav"
    input_path.touch()
    reference.touch()
    monkeypatch.setattr(normalize, "get_device_profile", lambda device: FakeProfile(handler))

    with pytest.raises(ValueError, match="no measurable presets"):
        normalize.main(
            [
                "--device",
                "fake",
                "-i",
                str(input_path),
                "-o",
                str(tmp_path / "output.hls"),
                "--reference-di",
                str(reference),
            ]
        )


def test_main_keeps_temp_when_worker_writes_wrong_row_count(tmp_path, monkeypatch) -> None:
    handler = FakeHandler()
    input_path = tmp_path / "input.hls"
    reference = tmp_path / "reference.wav"
    work_dir = tmp_path / "work"
    input_path.touch()
    reference.touch()
    work_dir.mkdir()
    monkeypatch.setattr(normalize, "get_device_profile", lambda device: FakeProfile(handler))
    monkeypatch.setattr(normalize.tempfile, "mkdtemp", lambda **kwargs: str(work_dir))
    monkeypatch.setattr(
        normalize,
        "run_windows_analysis",
        lambda args, ids, path: path.write_text("Preset,DevicePatch\n", encoding="utf-8"),
    )

    with pytest.raises(RuntimeError, match="wrote 0 rows"):
        normalize.main(
            [
                "--device",
                "fake",
                "-i",
                str(input_path),
                "-o",
                str(tmp_path / "output.hls"),
                "--reference-di",
                str(reference),
            ]
        )

    assert work_dir.exists()


@pytest.mark.parametrize(
    ("extra_args", "message"),
    [
        ([], "--output is required"),
        (["--automation", "-o", "out.hls"], "must not be specified"),
        (["-o", "out.hls", "--limit", "0"], "at least 1"),
    ],
)
def test_main_validates_orchestration_arguments(tmp_path, monkeypatch, extra_args, message) -> None:
    handler = FakeHandler()
    input_path = tmp_path / "input.hls"
    reference = tmp_path / "reference.wav"
    input_path.touch()
    reference.touch()
    monkeypatch.setattr(normalize, "get_device_profile", lambda device: FakeProfile(handler))

    with pytest.raises(ValueError, match=message):
        normalize.main(
            [
                "--device",
                "fake",
                "-i",
                str(input_path),
                "--reference-di",
                str(reference),
                *extra_args,
            ]
        )
