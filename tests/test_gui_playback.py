from __future__ import annotations

import subprocess
from pathlib import Path, PureWindowsPath

import pytest

pytest.importorskip("PySide6")

from matchpatch.gui import playback


def test_windows_playback_path_keeps_native_windows_paths() -> None:
    assert playback._windows_playback_path(Path("C:/Recordings/take.wav")) == (
        "C:/Recordings/take.wav"
    )
    assert playback._windows_playback_path(PureWindowsPath("C:/Recordings/take.wav")) == (
        "C:/Recordings/take.wav"
    )
    assert playback._windows_playback_path(Path("\\\\server\\share\\take.wav")) == (
        "\\\\server\\share\\take.wav"
    )
    assert playback._windows_playback_path(PureWindowsPath("\\\\server\\share\\take.wav")) == (
        "\\\\server\\share\\take.wav"
    )


def test_windows_playback_path_converts_wsl_paths(monkeypatch) -> None:
    converted = "C:/Users/flo/AppData/Local/Temp/take.wav"
    monkeypatch.setattr(playback, "wsl_path_to_windows", lambda path: converted)

    assert playback._windows_playback_path(Path("/tmp/take.wav")) == converted
    assert playback._windows_playback_path(PureWindowsPath("/tmp/take.wav")) == converted


def test_audio_playback_worker_emits_subprocess_error(monkeypatch, app) -> None:
    def fail_run(*args, **kwargs):
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=args[0],
            stderr="audio device unavailable\n",
        )

    errors: list[str] = []
    monkeypatch.setattr(playback.subprocess, "run", fail_run)
    worker = playback.AudioPlaybackWorker(
        Path("/tmp/take.wav"),
        windows_python="C:/MatchPatch/python.exe",
    )
    worker.failed.connect(errors.append)

    worker.run()

    assert errors == ["audio device unavailable"]
