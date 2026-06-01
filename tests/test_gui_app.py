from __future__ import annotations

import os
import signal
from pathlib import Path
from unittest.mock import Mock

from matchpatch.gui import app as gui_app
from matchpatch.gui.app import configure_wslg_runtime


def test_configure_wslg_runtime_uses_existing_runtime_socket(tmp_path, monkeypatch) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    runtime.joinpath("wayland-0").touch()
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)

    configure_wslg_runtime()

    assert os.environ["XDG_RUNTIME_DIR"] == str(runtime)
    assert "QT_QPA_PLATFORM" not in os.environ


def test_configure_wslg_runtime_selects_wslg_socket(tmp_path, monkeypatch) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    original_exists = Path.exists

    def fake_exists(path: Path) -> bool:
        if path == Path("/mnt/wslg/runtime-dir/wayland-0"):
            return True
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", fake_exists)

    configure_wslg_runtime()

    assert os.environ["XDG_RUNTIME_DIR"] == "/mnt/wslg/runtime-dir"
    assert os.environ["QT_QPA_PLATFORM"] == "wayland"


def test_terminal_interrupt_queues_normal_window_close(monkeypatch) -> None:
    handlers = {}
    scheduled = []

    class FakeSignal:
        def connect(self, callback) -> None:
            self.callback = callback

    class FakeTimer:
        def __init__(self, parent) -> None:
            self.parent = parent
            self.timeout = FakeSignal()
            self.interval = None

        def start(self, interval: int) -> None:
            self.interval = interval

        @staticmethod
        def singleShot(interval: int, callback) -> None:
            scheduled.append((interval, callback))

    monkeypatch.setattr(
        gui_app.signal, "signal", lambda signum, handler: handlers.setdefault(signum, handler)
    )
    monkeypatch.setattr(gui_app, "QTimer", FakeTimer)
    app = Mock()
    window = Mock()

    timer = gui_app.install_terminal_interrupt_handler(app, window)
    handlers[signal.SIGINT](signal.SIGINT, None)

    assert timer.parent is app
    assert timer.interval == 100
    assert scheduled == [(0, window.close)]
