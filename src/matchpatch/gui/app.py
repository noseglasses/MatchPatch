"""Application entry point for the MatchPatch PySide6 GUI."""

from __future__ import annotations

import os
import platform
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QMessageLogContext, Qt, QTimer, QtMsgType, qInstallMessageHandler
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QImage, QPainter
from PySide6.QtWidgets import QApplication

from matchpatch import __version__
from matchpatch.gui.main_window import MainWindow

IGNORED_QT_MESSAGES = {"This plugin supports grabbing the mouse only for popup windows"}
SOURCE_ROOT = Path(__file__).resolve().parents[3]
DESKTOP_FILE_ID = "matchpatch-gui"
DESKTOP_ICON_SIZE = 512
DEFAULT_XDG_DATA_DIRS = "/usr/local/share:/usr/share"
GUI_STYLE = "Fusion"
GUI_FONT_FAMILY = "DejaVu Sans"
GUI_FONT_POINT_SIZE = 10
GUI_SMOKE_ENV = "MATCHPATCH_GUI_SMOKE"
XCB_PROBE_TIMEOUT_SECONDS = 5.0
WINDOWS_INPUT_LANGUAGE_COMMAND = (
    "Add-Type -AssemblyName System.Windows.Forms; "
    "[System.Windows.Forms.InputLanguage]::CurrentInputLanguage.Culture.Name"
)
WINDOWS_KEYBOARD_LAYOUT_PROBE = (
    "using System; "
    "using System.Runtime.InteropServices; "
    "public static class KeyboardLayoutProbe { "
    '[DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow(); '
    '[DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId('
    "IntPtr hWnd, IntPtr processId); "
    '[DllImport("user32.dll")] public static extern IntPtr GetKeyboardLayout(uint idThread); '
    "}"
)
WINDOWS_KEYBOARD_LAYOUT_COMMAND = (
    '$code = @"\n'
    f"{WINDOWS_KEYBOARD_LAYOUT_PROBE}\n"
    '"@; '
    "Add-Type -TypeDefinition $code; "
    "$hwnd=[KeyboardLayoutProbe]::GetForegroundWindow(); "
    "$thread=[KeyboardLayoutProbe]::GetWindowThreadProcessId($hwnd,[IntPtr]::Zero); "
    "$hkl=[KeyboardLayoutProbe]::GetKeyboardLayout($thread).ToInt64(); "
    '("{0:x8}" -f ($hkl -band 0xffffffff))'
)
WINDOWS_HKL_LANGUAGE_TO_XKB_LAYOUT = {
    "0405": "cz",
    "0406": "dk",
    "0407": "de",
    "0409": "us",
    "040a": "es",
    "040b": "fi",
    "040c": "fr",
    "0410": "it",
    "0411": "jp",
    "0413": "nl",
    "0415": "pl",
    "0416": "br",
    "041d": "se",
    "041f": "tr",
    "0809": "gb",
    "0816": "pt",
}
WINDOWS_LANGUAGE_TO_XKB_LAYOUT = {
    "da": "dk",
    "de": "de",
    "en-gb": "gb",
    "en-us": "us",
    "es": "es",
    "fi": "fi",
    "fr": "fr",
    "it": "it",
    "ja": "jp",
    "nb": "no",
    "nl": "nl",
    "nn": "no",
    "pl": "pl",
    "pt-br": "br",
    "pt": "pt",
    "sv": "se",
    "tr": "tr",
}


def resource_path(*parts: str) -> Path:
    """Resolve bundled resources in frozen and source-tree execution."""
    relative_path = Path(*parts)
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False):
        if meipass:
            candidates.append(Path(meipass) / relative_path)
        candidates.append(Path(sys.executable).resolve().parent / relative_path)
    candidates.append(SOURCE_ROOT / relative_path)

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def assets_dir() -> Path:
    return resource_path("docs", "assets")


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
    """Point Qt at WSLg and prefer the keyboard-layout friendly platform plugin."""
    wayland_display = os.getenv("WAYLAND_DISPLAY")
    if not wayland_display:
        return

    runtime_dir = Path(os.getenv("XDG_RUNTIME_DIR", ""))
    runtime_has_wayland = runtime_dir.joinpath(wayland_display).exists()

    wslg_runtime = Path("/mnt/wslg/runtime-dir")
    wslg_has_wayland = wslg_runtime.joinpath(wayland_display).exists()
    if not runtime_has_wayland and wslg_has_wayland:
        os.environ["XDG_RUNTIME_DIR"] = str(wslg_runtime)

    if os.getenv("QT_QPA_PLATFORM"):
        return

    if os.getenv("DISPLAY"):
        xcb_error = xcb_runtime_error()
        if xcb_error is None:
            os.environ["QT_QPA_PLATFORM"] = "xcb"
            return
        if runtime_has_wayland or wslg_has_wayland:
            print(
                f"MatchPatch: Qt xcb startup failed; falling back to Wayland. {xcb_error}",
                file=sys.stderr,
            )

    if runtime_has_wayland or wslg_has_wayland:
        os.environ["QT_QPA_PLATFORM"] = "wayland"


def sync_wslg_keyboard_layout() -> None:
    """Apply the active Windows keyboard layout to Xwayland when possible."""
    if not is_wsl() or not os.getenv("DISPLAY"):
        return

    layout_id = windows_keyboard_layout_id()
    language = None if layout_id else windows_input_language()
    layout = xkb_layout_for_windows_keyboard_layout(layout_id) or xkb_layout_for_windows_language(
        language
    )
    if layout is None:
        return

    os.environ.setdefault("XKB_DEFAULT_LAYOUT", layout)
    setxkbmap = shutil.which("setxkbmap")
    if setxkbmap is None:
        print(
            "MatchPatch: Windows keyboard layout sync needs setxkbmap. "
            "Install x11-xkb-utils if keyboard input still uses the wrong layout.",
            file=sys.stderr,
        )
        return

    completed = subprocess.run(
        [setxkbmap, layout],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        source = layout_id or language
        print(
            f"MatchPatch: Could not apply Windows keyboard layout {source!r} "
            f"as XKB layout {layout!r}. {detail}",
            file=sys.stderr,
        )


def is_wsl() -> bool:
    return bool(os.getenv("WSL_DISTRO_NAME")) or "microsoft" in platform.release().casefold()


def windows_input_language() -> str | None:
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        return None
    try:
        completed = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                WINDOWS_INPUT_LANGUAGE_COMMAND,
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=2.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode:
        return None
    language = completed.stdout.strip()
    return language or None


def windows_keyboard_layout_id() -> str | None:
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        return None
    try:
        completed = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                WINDOWS_KEYBOARD_LAYOUT_COMMAND,
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=2.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode:
        return None
    match = re.search(r"[0-9a-fA-F]{4,}", completed.stdout.strip())
    return match.group(0).casefold() if match else None


def xkb_layout_for_windows_keyboard_layout(layout_id: str | None) -> str | None:
    if not layout_id:
        return None
    normalized = re.sub(r"[^0-9a-fA-F]", "", layout_id).casefold()
    if len(normalized) < 4:
        return None
    return WINDOWS_HKL_LANGUAGE_TO_XKB_LAYOUT.get(normalized[-4:])


def xkb_layout_for_windows_language(language: str | None) -> str | None:
    if not language:
        return None
    normalized = re.sub(r"[_ ]", "-", language.strip().casefold())
    return WINDOWS_LANGUAGE_TO_XKB_LAYOUT.get(
        normalized,
        WINDOWS_LANGUAGE_TO_XKB_LAYOUT.get(normalized.split("-", 1)[0]),
    )


def xcb_runtime_available() -> bool:
    """Return whether Qt can initialize the xcb platform plugin."""
    return xcb_runtime_error() is None


def xcb_runtime_error() -> str | None:
    """Return the Qt xcb startup error, or None when xcb works."""
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "xcb"
    env["QT_DEBUG_PLUGINS"] = "1"
    probe = (
        "import sys\n"
        "from PySide6.QtWidgets import QApplication\n"
        "app = QApplication(['matchpatch-xcb-probe'])\n"
        "app.quit()\n"
        "sys.exit(0)\n"
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            check=False,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=XCB_PROBE_TIMEOUT_SECONDS,
            text=True,
        )
    except subprocess.TimeoutExpired:
        return "Qt xcb probe timed out."
    except OSError as exc:
        return str(exc)
    if completed.returncode == 0:
        return None
    return _summarize_xcb_probe_error(completed.stderr or completed.stdout)


def _summarize_xcb_probe_error(output: str) -> str:
    for line in output.splitlines():
        if "cannot open shared object file" in line:
            return line.strip()
    for line in reversed(output.splitlines()):
        if line.strip():
            return line.strip()
    return "Qt xcb probe exited with an error."


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
    icon.save(str(target))


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
            _write_square_desktop_icon(assets_dir() / "matchmatch-icon-512.png", installed_icon)
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


def gui_smoke_enabled() -> bool:
    return os.getenv(GUI_SMOKE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def handle_cli_arguments(argv: list[str]) -> bool:
    if argv == ["--help"] or argv == ["-h"]:
        print("usage: matchpatch-gui [-h] [--version]")
        print()
        print("Launch the MatchPatch desktop interface")
        print()
        print("options:")
        print("  -h, --help  show this help message and exit")
        print("  --version   show program's version number and exit")
        return True

    if argv == ["--version"]:
        print(f"matchpatch-gui {__version__}")
        return True

    return False


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if handle_cli_arguments(args):
        raise SystemExit(0)

    configure_wslg_runtime()
    sync_wslg_keyboard_layout()
    configure_high_dpi_scaling()
    register_desktop_entry()
    qInstallMessageHandler(qt_message_handler)
    app = QApplication([sys.argv[0], *args])
    configure_gui_appearance(app)
    app.setApplicationName(DESKTOP_FILE_ID)
    app.setApplicationDisplayName("MatchPatch")
    app.setDesktopFileName(DESKTOP_FILE_ID)
    icon = assets_dir() / "matchmatch-icon.png"
    app.setWindowIcon(QIcon(str(icon)))
    window = MainWindow()
    if gui_smoke_enabled():
        window.show()
        app.processEvents()
        window.close()
        raise SystemExit(0)
    window.showMaximized()
    _interrupt_timer = install_terminal_interrupt_handler(app, window)
    raise SystemExit(app.exec())


if __name__ == "__main__":  # pragma: no cover - module entry point
    main()
