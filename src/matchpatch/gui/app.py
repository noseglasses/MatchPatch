"""Application entry point for the MatchPatch PySide6 GUI."""

from __future__ import annotations

import os
import shutil
import signal
import sys
from pathlib import Path

from PySide6.QtCore import QMessageLogContext, QTimer, QtMsgType, qInstallMessageHandler
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from matchpatch.gui.main_window import MainWindow

IGNORED_QT_MESSAGES = {"This plugin supports grabbing the mouse only for popup windows"}
ASSETS_DIR = Path(__file__).resolve().parents[3] / "doc" / "assets"


def qt_message_handler(
    message_type: QtMsgType,
    context: QMessageLogContext,
    message: str,
) -> None:
    """Suppress known harmless platform noise while preserving other Qt messages."""
    del message_type, context
    if message not in IGNORED_QT_MESSAGES:
        print(message, file=sys.stderr)


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


def register_desktop_entry() -> None:
    """Give Wayland/WSLg an application ID with a project icon."""
    data_home = Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    applications = data_home / "applications"
    icons = data_home / "icons" / "hicolor" / "512x512" / "apps"
    desktop_file = applications / "matchpatch.desktop"
    installed_icon = icons / "matchpatch.png"
    entry = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=MatchPatch\n"
        "Comment=Normalize audio processor presets\n"
        "Exec=matchpatch-gui\n"
        "Icon=matchpatch\n"
        "Terminal=false\n"
        "Categories=AudioVideo;Audio;\n"
        "StartupWMClass=matchpatch\n"
    )
    try:
        applications.mkdir(parents=True, exist_ok=True)
        icons.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ASSETS_DIR / "matchmatch-icon-512.png", installed_icon)
        if not desktop_file.exists() or desktop_file.read_text(encoding="utf-8") != entry:
            desktop_file.write_text(entry, encoding="utf-8")
    except OSError:
        return


def install_terminal_interrupt_handler(app: QApplication, window: MainWindow) -> QTimer:
    """Route terminal cancellation through the window's normal close handling."""

    def close_window(_signum: int, _frame: object) -> None:
        QTimer.singleShot(0, window.close)

    signal.signal(signal.SIGINT, close_window)
    timer = QTimer(app)
    timer.timeout.connect(lambda: None)
    timer.start(100)
    return timer


def main() -> None:
    configure_wslg_runtime()
    register_desktop_entry()
    qInstallMessageHandler(qt_message_handler)
    app = QApplication(sys.argv)
    app.setApplicationName("matchpatch")
    app.setApplicationDisplayName("MatchPatch")
    app.setDesktopFileName("matchpatch")
    icon = ASSETS_DIR / "matchmatch-icon.png"
    app.setWindowIcon(QIcon(str(icon)))
    window = MainWindow()
    window.show()
    _interrupt_timer = install_terminal_interrupt_handler(app, window)
    raise SystemExit(app.exec())


if __name__ == "__main__":  # pragma: no cover - module entry point
    main()
