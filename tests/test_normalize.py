from __future__ import annotations

import argparse
import csv
import subprocess
from pathlib import Path

import pytest

from matchpatch import normalize
from matchpatch.devices.base import PatchAssignment


class FakeHandler:
    def __init__(self) -> None:
        self.applied = []
        self.reamped = []

    def validate_input(self, input_path: Path) -> None:
        return None

    def validate_output(self, input_path: Path, output_path: Path) -> None:
        return None

    def automation_output_path(self, input_path: Path, postfix: str) -> Path:
        return input_path.with_name(input_path.stem + postfix + input_path.suffix)

    def create_reamp_file(self, input_path: Path, output_path: Path) -> None:
        self.reamped.append((input_path, output_path))

    def parse_patch_set(self, value: str) -> list[int]:
        return [int(item) for item in value.split(",")]

    def list_assignments(self, input_path: Path) -> list[PatchAssignment]:
        return [PatchAssignment(1, "patch-1", "One"), PatchAssignment(2, "patch-2", "Two")]

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
    assert ["--audio-device", "Helix"] == command[-8:-6]
    assert command[-2:] == ["--simulate-fail-presets", "6,7"]
    assert timeout == 12.0


def test_run_windows_analysis_reports_missing_environment(tmp_path) -> None:
    args = argparse.Namespace(windows_python=str(tmp_path / "missing.exe"))

    with pytest.raises(RuntimeError, match="sync-windows"):
        normalize.run_windows_analysis(args, [1], tmp_path / "results.csv")


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


def test_main_automation_reamps_confirms_and_keeps_temp(tmp_path, monkeypatch) -> None:
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

    assert handler.reamped == [(input_path.resolve(), tmp_path / "input_reamp.hls")]
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
