from __future__ import annotations

import os
from pathlib import Path

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
