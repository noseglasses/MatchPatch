"""Application entry point for the MatchPatch PySide6 GUI."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from matchpatch.gui.main_window import MainWindow


def configure_wslg_runtime() -> None:
    """Point Qt at WSLg when systemd provides a runtime dir without its socket."""
    wayland_display = os.getenv("WAYLAND_DISPLAY")
    if not wayland_display:
        return

    runtime_dir = Path(os.getenv("XDG_RUNTIME_DIR", ""))
    if runtime_dir.joinpath(wayland_display).exists():
        return

    wslg_runtime = Path("/mnt/wslg/runtime-dir")
    if wslg_runtime.joinpath(wayland_display).exists():
        os.environ["XDG_RUNTIME_DIR"] = str(wslg_runtime)
        os.environ.setdefault("QT_QPA_PLATFORM", "wayland")


def main() -> None:
    configure_wslg_runtime()
    app = QApplication(sys.argv)
    icon = Path(__file__).resolve().parents[3] / "doc" / "assets" / "matchmatch-icon.png"
    app.setWindowIcon(QIcon(str(icon)))
    window = MainWindow()
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":  # pragma: no cover - module entry point
    main()
