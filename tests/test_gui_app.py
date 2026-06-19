from __future__ import annotations

import os
import signal
from pathlib import Path
from unittest.mock import Mock

from matchpatch.gui import app as gui_app
from matchpatch.gui.app import configure_wslg_runtime


class RecordingApplication:
    calls = []

    def __init__(self, argv) -> None:
        self.argv = argv

    def setApplicationName(self, name: str) -> None:
        self.calls.append(("application_name", name))

    def setApplicationDisplayName(self, name: str) -> None:
        self.calls.append(("display_name", name))

    def setDesktopFileName(self, name: str) -> None:
        self.calls.append(("desktop_file", name))

    def setWindowIcon(self, icon) -> None:
        self.calls.append(("window_icon", icon))

    def processEvents(self) -> None:
        self.calls.append(("process_events",))

    def exec(self) -> int:
        self.calls.append(("exec",))
        return 0


class MaximizedWindow:
    calls = []

    def showMaximized(self) -> None:
        self.calls.append(("show_maximized",))

    def showFullScreen(self) -> None:
        self.calls.append(("show_fullscreen",))

    def show(self) -> None:
        self.calls.append(("show",))


class SmokeWindow:
    calls = []

    def showMaximized(self) -> None:
        self.calls.append(("show_maximized",))

    def show(self) -> None:
        self.calls.append(("show",))

    def close(self) -> None:
        self.calls.append(("close",))


def install_recording_gui(monkeypatch, calls, window_type) -> None:
    RecordingApplication.calls = calls
    window_type.calls = calls
    monkeypatch.setattr(gui_app, "configure_wslg_runtime", lambda: calls.append(("wslg",)))
    monkeypatch.setattr(gui_app, "configure_high_dpi_scaling", lambda: calls.append(("dpi",)))
    monkeypatch.setattr(
        gui_app,
        "configure_gui_appearance",
        lambda app: calls.append(("appearance", app)),
    )
    monkeypatch.setattr(gui_app, "register_desktop_entry", lambda: calls.append(("desktop",)))
    monkeypatch.setattr(
        gui_app, "qInstallMessageHandler", lambda handler: calls.append(("qt", handler))
    )
    monkeypatch.setattr(gui_app, "QApplication", RecordingApplication)
    monkeypatch.setattr(gui_app, "QIcon", lambda path: path)
    monkeypatch.setattr(gui_app, "MainWindow", window_type)
    monkeypatch.setattr(
        gui_app,
        "install_terminal_interrupt_handler",
        lambda app, window: calls.append(("interrupt", app, window)),
    )


def test_configure_wslg_runtime_uses_existing_runtime_socket(tmp_path, monkeypatch) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    runtime.joinpath("wayland-0").touch()
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.setattr(gui_app, "xcb_runtime_error", lambda: None)

    configure_wslg_runtime()

    assert os.environ["XDG_RUNTIME_DIR"] == str(runtime)
    assert os.environ["QT_QPA_PLATFORM"] == "xcb"


def test_configure_wslg_runtime_selects_wslg_socket(tmp_path, monkeypatch) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.setattr(gui_app, "xcb_runtime_error", lambda: None)
    original_exists = Path.exists

    def fake_exists(path: Path) -> bool:
        if path == Path("/mnt/wslg/runtime-dir/wayland-0"):
            return True
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", fake_exists)

    configure_wslg_runtime()

    assert os.environ["XDG_RUNTIME_DIR"] == str(Path("/mnt/wslg/runtime-dir"))
    assert os.environ["QT_QPA_PLATFORM"] == "xcb"


def test_configure_wslg_runtime_uses_wayland_when_xcb_dependency_is_missing(
    tmp_path, monkeypatch
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    runtime.joinpath("wayland-0").touch()
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.setattr(gui_app, "xcb_runtime_error", lambda: "missing dependency")

    configure_wslg_runtime()

    assert os.environ["QT_QPA_PLATFORM"] == "wayland"


def test_configure_wslg_runtime_uses_wayland_without_x11(tmp_path, monkeypatch) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    runtime.joinpath("wayland-0").touch()
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)

    configure_wslg_runtime()

    assert os.environ["QT_QPA_PLATFORM"] == "wayland"


def test_configure_wslg_runtime_preserves_explicit_qt_platform(tmp_path, monkeypatch) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    runtime.joinpath("wayland-0").touch()
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("QT_QPA_PLATFORM", "wayland")

    configure_wslg_runtime()

    assert os.environ["QT_QPA_PLATFORM"] == "wayland"


def test_xkb_layout_for_windows_language_maps_common_tags() -> None:
    assert gui_app.xkb_layout_for_windows_language("en-US") == "us"
    assert gui_app.xkb_layout_for_windows_language("en_GB") == "gb"
    assert gui_app.xkb_layout_for_windows_language("de-DE") == "de"
    assert gui_app.xkb_layout_for_windows_language("fr-CA") == "fr"
    assert gui_app.xkb_layout_for_windows_language("") is None


def test_xkb_layout_for_windows_keyboard_layout_maps_hkl_language_ids() -> None:
    assert gui_app.xkb_layout_for_windows_keyboard_layout("fffffffff0c00409") == "us"
    assert gui_app.xkb_layout_for_windows_keyboard_layout("00000407") == "de"
    assert gui_app.xkb_layout_for_windows_keyboard_layout("00000809") == "gb"
    assert gui_app.xkb_layout_for_windows_keyboard_layout("bogus") is None


def test_windows_keyboard_layout_id_uses_foreground_hkl(monkeypatch) -> None:
    calls = []

    class Completed:
        returncode = 0
        stdout = "00000407\n"
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return Completed()

    monkeypatch.setattr(gui_app.shutil, "which", lambda name: f"/mnt/c/{name}")
    monkeypatch.setattr(gui_app.subprocess, "run", fake_run)

    assert gui_app.windows_keyboard_layout_id() == "00000407"

    command, kwargs = calls[0]
    assert command[:4] == ["/mnt/c/powershell.exe", "-NoProfile", "-NonInteractive", "-Command"]
    assert gui_app.WINDOWS_KEYBOARD_LAYOUT_COMMAND in command
    assert kwargs["text"] is True


def test_windows_input_language_uses_powershell(monkeypatch) -> None:
    calls = []

    class Completed:
        returncode = 0
        stdout = "de-DE\n"
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return Completed()

    monkeypatch.setattr(gui_app.shutil, "which", lambda name: f"/mnt/c/{name}")
    monkeypatch.setattr(gui_app.subprocess, "run", fake_run)

    assert gui_app.windows_input_language() == "de-DE"

    command, kwargs = calls[0]
    assert command[:4] == ["/mnt/c/powershell.exe", "-NoProfile", "-NonInteractive", "-Command"]
    assert gui_app.WINDOWS_INPUT_LANGUAGE_COMMAND in command
    assert kwargs["text"] is True


def test_sync_wslg_keyboard_layout_applies_windows_layout(monkeypatch) -> None:
    calls = []
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv("XKB_DEFAULT_LAYOUT", raising=False)
    monkeypatch.setattr(gui_app, "is_wsl", lambda: True)
    monkeypatch.setattr(gui_app, "windows_keyboard_layout_id", lambda: "00000407")
    monkeypatch.setattr(gui_app, "windows_input_language", lambda: None)
    monkeypatch.setattr(gui_app.shutil, "which", lambda name: f"/usr/bin/{name}")

    class Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return Completed()

    monkeypatch.setattr(gui_app.subprocess, "run", fake_run)

    gui_app.sync_wslg_keyboard_layout()

    assert os.environ["XKB_DEFAULT_LAYOUT"] == "de"
    assert calls[0][0] == ["/usr/bin/setxkbmap", "de"]


def test_sync_wslg_keyboard_layout_warns_without_setxkbmap(monkeypatch, capsys) -> None:
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(gui_app, "is_wsl", lambda: True)
    monkeypatch.setattr(gui_app, "windows_keyboard_layout_id", lambda: None)
    monkeypatch.setattr(gui_app, "windows_input_language", lambda: "de-DE")
    monkeypatch.setattr(gui_app.shutil, "which", lambda name: None)

    gui_app.sync_wslg_keyboard_layout()

    assert "setxkbmap" in capsys.readouterr().err


def test_xcb_runtime_available_probes_qt_platform(monkeypatch) -> None:
    calls = []

    class Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return Completed()

    monkeypatch.setattr(gui_app.subprocess, "run", fake_run)

    assert gui_app.xcb_runtime_available() is True

    command, kwargs = calls[0]
    assert command[:2] == [gui_app.sys.executable, "-c"]
    assert kwargs["env"]["QT_QPA_PLATFORM"] == "xcb"
    assert kwargs["env"]["QT_DEBUG_PLUGINS"] == "1"
    assert kwargs["stdout"] is gui_app.subprocess.PIPE
    assert kwargs["stderr"] is gui_app.subprocess.PIPE
    assert kwargs["timeout"] == gui_app.XCB_PROBE_TIMEOUT_SECONDS
    assert kwargs["text"] is True


def test_xcb_runtime_available_returns_false_when_probe_fails(monkeypatch) -> None:
    class Completed:
        returncode = 1
        stdout = ""
        stderr = "missing dependency"

    monkeypatch.setattr(gui_app.subprocess, "run", lambda *args, **kwargs: Completed())

    assert gui_app.xcb_runtime_available() is False
    assert gui_app.xcb_runtime_error() == "missing dependency"


def test_summarize_xcb_probe_error_prefers_missing_library_line() -> None:
    assert gui_app._summarize_xcb_probe_error(
        "noise\n"
        "Cannot load library libqxcb.so: libxkbcommon-x11.so.0: "
        "cannot open shared object file: No such file or directory\n"
        "generic fallback message\n"
    ) == (
        "Cannot load library libqxcb.so: libxkbcommon-x11.so.0: "
        "cannot open shared object file: No such file or directory"
    )


def test_resource_path_uses_pyinstaller_meipass(tmp_path, monkeypatch) -> None:
    meipass = tmp_path / "bundle"
    asset = meipass / "docs" / "assets" / "matchmatch-icon.png"
    asset.parent.mkdir(parents=True)
    asset.touch()
    monkeypatch.setattr(gui_app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(gui_app.sys, "_MEIPASS", str(meipass), raising=False)
    monkeypatch.setattr(gui_app.sys, "executable", str(tmp_path / "app" / "MatchPatch.exe"))

    assert gui_app.resource_path("docs", "assets", "matchmatch-icon.png") == asset
    assert gui_app.assets_dir() == asset.parent


def test_resource_path_uses_frozen_executable_dir_when_meipass_is_missing(
    tmp_path, monkeypatch
) -> None:
    executable = tmp_path / "MatchPatch" / "MatchPatch.exe"
    asset = executable.parent / "docs" / "assets" / "matchmatch-icon.png"
    asset.parent.mkdir(parents=True)
    asset.touch()
    monkeypatch.setattr(gui_app.sys, "frozen", True, raising=False)
    monkeypatch.delattr(gui_app.sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(gui_app.sys, "executable", str(executable))

    assert gui_app.resource_path("docs", "assets", "matchmatch-icon.png") == asset


def test_resource_path_falls_back_to_source_tree(monkeypatch) -> None:
    monkeypatch.setattr(gui_app.sys, "frozen", False, raising=False)

    assert gui_app.resource_path("docs", "assets") == gui_app.SOURCE_ROOT / "docs" / "assets"


def test_configure_high_dpi_scaling_uses_pass_through(monkeypatch) -> None:
    policies = []

    class FakeGuiApplication:
        @staticmethod
        def setHighDpiScaleFactorRoundingPolicy(policy) -> None:
            policies.append(policy)

    monkeypatch.setattr(gui_app, "QGuiApplication", FakeGuiApplication)

    gui_app.configure_high_dpi_scaling()

    assert policies == [gui_app.Qt.HighDpiScaleFactorRoundingPolicy.PassThrough]


def test_configure_gui_appearance_uses_wsl_visual_baseline(monkeypatch) -> None:
    calls = []
    palette = object()

    class FakeStyle:
        @staticmethod
        def standardPalette():
            calls.append(("standard_palette",))
            return palette

    class FakeApplication:
        def setStyle(self, style: str) -> None:
            calls.append(("style", style))

        def setFont(self, font) -> None:
            calls.append(("font", font.family(), font.pointSize()))

        def style(self):
            return FakeStyle()

        def setPalette(self, app_palette) -> None:
            calls.append(("palette", app_palette))

    gui_app.configure_gui_appearance(FakeApplication())

    assert calls == [
        ("style", "Fusion"),
        ("font", "DejaVu Sans", 10),
        ("standard_palette",),
        ("palette", palette),
    ]


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


def test_main_help_prints_usage_without_starting_gui(monkeypatch, capsys) -> None:
    calls = []

    monkeypatch.setattr(gui_app, "configure_wslg_runtime", lambda: calls.append("wslg"))
    monkeypatch.setattr(gui_app, "configure_high_dpi_scaling", lambda: calls.append("dpi"))
    monkeypatch.setattr(gui_app, "register_desktop_entry", lambda: calls.append("desktop"))

    try:
        gui_app.main(["--help"])
    except SystemExit as exc:
        assert exc.code == 0

    captured = capsys.readouterr()

    assert "usage: matchpatch-gui" in captured.out
    assert "Launch the MatchPatch desktop interface" in captured.out
    assert not calls


def test_main_version_prints_version_without_starting_gui(monkeypatch, capsys) -> None:
    calls = []

    monkeypatch.setattr(gui_app, "configure_wslg_runtime", lambda: calls.append("wslg"))
    monkeypatch.setattr(gui_app, "configure_high_dpi_scaling", lambda: calls.append("dpi"))
    monkeypatch.setattr(gui_app, "register_desktop_entry", lambda: calls.append("desktop"))

    try:
        gui_app.main(["--version"])
    except SystemExit as exc:
        assert exc.code == 0

    captured = capsys.readouterr()

    assert f"matchpatch-gui {gui_app.__version__}" in captured.out
    assert not calls


def test_main_shows_window_maximized(monkeypatch) -> None:
    calls = []
    install_recording_gui(monkeypatch, calls, MaximizedWindow)
    monkeypatch.delenv(gui_app.GUI_SMOKE_ENV, raising=False)

    try:
        gui_app.main()
    except SystemExit as exc:
        assert exc.code == 0

    assert ("show_maximized",) in calls
    assert ("show_fullscreen",) not in calls
    assert ("show",) not in calls
    assert ("application_name", "matchpatch-gui") in calls
    assert ("display_name", "MatchPatch") in calls
    assert ("desktop_file", "matchpatch-gui") in calls
    assert ("dpi",) in calls
    assert any(call[0] == "appearance" for call in calls)
    assert calls.index(("dpi",)) < calls.index(("desktop",))
    assert next(index for index, call in enumerate(calls) if call[0] == "appearance") < calls.index(
        ("show_maximized",)
    )
    assert calls.index(("show_maximized",)) < calls.index(("exec",))


def test_main_smoke_mode_processes_events_and_exits(monkeypatch) -> None:
    calls = []
    monkeypatch.setenv(gui_app.GUI_SMOKE_ENV, "1")
    install_recording_gui(monkeypatch, calls, SmokeWindow)

    try:
        gui_app.main()
    except SystemExit as exc:
        assert exc.code == 0

    assert ("show",) in calls
    assert ("process_events",) in calls
    assert ("close",) in calls
    assert ("show_maximized",) not in calls
    assert ("exec",) not in calls
    assert not any(call[0] == "interrupt" for call in calls)
