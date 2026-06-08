"""Application entry point for the MatchPatch PySide6 GUI."""

from __future__ import annotations

import os
import signal
import sys
from pathlib import Path

from PySide6.QtCore import QMessageLogContext, Qt, QTimer, QtMsgType, qInstallMessageHandler
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QImage, QPainter
from PySide6.QtWidgets import QApplication

from matchpatch.gui.main_window import MainWindow

IGNORED_QT_MESSAGES = {"This plugin supports grabbing the mouse only for popup windows"}
ASSETS_DIR = Path(__file__).resolve().parents[3] / "docs" / "assets"
DESKTOP_FILE_ID = "matchpatch-gui"
DESKTOP_ICON_SIZE = 512
DEFAULT_XDG_DATA_DIRS = "/usr/local/share:/usr/share"
GUI_STYLE = "Fusion"
GUI_FONT_FAMILY = "DejaVu Sans"
GUI_FONT_POINT_SIZE = 10


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


def configure_high_dpi_scaling() -> None:
    """Keep Qt's per-screen scale factors stable across platforms."""
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )


def configure_gui_appearance(app: QApplication) -> None:
    """Apply the WSLg visual baseline consistently on every Qt platform."""
    app.setStyle(GUI_STYLE)
    app.setFont(QFont(GUI_FONT_FAMILY, GUI_FONT_POINT_SIZE))
    app.setPalette(app.style().standardPalette())


def _write_square_desktop_icon(source: Path, target: Path) -> None:
    image = QImage(str(source))
    if image.isNull():
        return

    icon = QImage(DESKTOP_ICON_SIZE, DESKTOP_ICON_SIZE, QImage.Format.Format_ARGB32)
    icon.fill(QColor(0, 0, 0, 0))
    scaled = image.scaled(
        DESKTOP_ICON_SIZE,
        DESKTOP_ICON_SIZE,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    x = (DESKTOP_ICON_SIZE - scaled.width()) // 2
    y = (DESKTOP_ICON_SIZE - scaled.height()) // 2
    painter = QPainter(icon)
    painter.drawImage(x, y, scaled)
    painter.end()
    icon.save(str(target), "PNG")


def _desktop_entry_data_dirs() -> list[Path]:
    data_home = Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    data_dirs = [
        Path(path)
        for path in os.getenv("XDG_DATA_DIRS", DEFAULT_XDG_DATA_DIRS).split(os.pathsep)
        if path
    ]
    return [*data_dirs, data_home]


def _desktop_entry(icon: Path) -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=MatchPatch\n"
        "Comment=Normalize audio processor presets\n"
        "Exec=matchpatch-gui\n"
        f"Icon={icon}\n"
        "Terminal=false\n"
        "Categories=AudioVideo;Audio;\n"
        f"StartupWMClass={DESKTOP_FILE_ID}\n"
    )


def register_desktop_entry() -> None:
    """Give Wayland/WSLg an application ID with a project icon."""
    for data_dir in _desktop_entry_data_dirs():
        applications = data_dir / "applications"
        icons = data_dir / "icons" / "hicolor" / "512x512" / "apps"
        desktop_file = applications / f"{DESKTOP_FILE_ID}.desktop"
        installed_icon = icons / f"{DESKTOP_FILE_ID}.png"
        entry = _desktop_entry(installed_icon)
        try:
            applications.mkdir(parents=True, exist_ok=True)
            icons.mkdir(parents=True, exist_ok=True)
            _write_square_desktop_icon(ASSETS_DIR / "matchmatch-icon-512.png", installed_icon)
            if not desktop_file.exists() or desktop_file.read_text(encoding="utf-8") != entry:
                desktop_file.write_text(entry, encoding="utf-8")
        except OSError:
            continue


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
    configure_high_dpi_scaling()
    register_desktop_entry()
    qInstallMessageHandler(qt_message_handler)
    app = QApplication(sys.argv)
    configure_gui_appearance(app)
    app.setApplicationName(DESKTOP_FILE_ID)
    app.setApplicationDisplayName("MatchPatch")
    app.setDesktopFileName(DESKTOP_FILE_ID)
    icon = ASSETS_DIR / "matchmatch-icon.png"
    app.setWindowIcon(QIcon(str(icon)))
    window = MainWindow()
    window.showMaximized()
    _interrupt_timer = install_terminal_interrupt_handler(app, window)
    raise SystemExit(app.exec())


if __name__ == "__main__":  # pragma: no cover - module entry point
    main()
