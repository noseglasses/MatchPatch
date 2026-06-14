"""Recorded-output playback helpers for the GUI."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from matchpatch.normalize import wsl_path_to_windows

WINDOWS_PLAYBACK_CODE = (
    "from pathlib import Path\n"
    "import sys\n"
    "import soundfile as sf\n"
    "from matchpatch.audio import play_audio\n"
    "audio, sample_rate = sf.read(Path(sys.argv[1]), dtype='float32', always_2d=True)\n"
    "play_audio(audio, sample_rate)\n"
)


def _windows_playback_path(path: Path) -> str:
    text = str(path)
    if re.match(r"^[A-Za-z]:[\\/]", text) or text.startswith("\\\\") or os.name == "nt":
        return text
    return wsl_path_to_windows(path)


class AudioPlaybackWorker(QThread):
    failed = Signal(str)

    def __init__(
        self,
        path: Path,
        parent: QObject | None = None,
        *,
        windows_python: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.path = path
        self.windows_python = windows_python

    def run(self) -> None:
        try:
            if self.windows_python:
                windows_path = _windows_playback_path(self.path)
                completed = subprocess.run(
                    [self.windows_python, "-c", WINDOWS_PLAYBACK_CODE, windows_path],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                if completed.stderr.strip():
                    self.failed.emit(completed.stderr.strip())
                return

            import soundfile as sf

            from matchpatch.audio import play_audio

            audio, sample_rate = sf.read(self.path, dtype="float32", always_2d=True)
            play_audio(audio, sample_rate)
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            self.failed.emit(detail or str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
