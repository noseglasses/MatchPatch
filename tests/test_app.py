from __future__ import annotations

import sys
from types import ModuleType

from matchpatch import app


def test_launcher_defaults_to_gui(monkeypatch) -> None:
    calls = []
    gui_module = ModuleType("matchpatch.gui.app")
    gui_module.main = calls.append  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "matchpatch.gui.app", gui_module)

    app.main(["project.hls"])

    assert calls == [["project.hls"]]


def test_launcher_cli_switch_dispatches_cli_without_switch(monkeypatch) -> None:
    calls = []
    cli_module = ModuleType("matchpatch.cli")
    cli_module.main = calls.append  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "matchpatch.cli", cli_module)

    app.main(["--cli", "normalize", "--device", "helix"])

    assert calls == [["normalize", "--device", "helix"]]


def test_launcher_cli_version_returns_cleanly_without_stdout(monkeypatch) -> None:
    calls = []
    cli_module = ModuleType("matchpatch.cli")
    cli_module.main = calls.append  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "matchpatch.cli", cli_module)
    monkeypatch.setattr(app, "_attach_parent_console", lambda: False)

    class BrokenStdout:
        def write(self, _text: str) -> None:
            raise OSError

        def flush(self) -> None:
            raise OSError

    monkeypatch.setattr(sys, "stdout", BrokenStdout())

    app.main(["--cli", "--version"])

    assert calls == []


def test_launcher_cli_version_uses_attached_console_stdout(monkeypatch) -> None:
    calls = []
    cli_module = ModuleType("matchpatch.cli")
    cli_module.main = calls.append  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "matchpatch.cli", cli_module)

    class BrokenStdout:
        def write(self, _text: str) -> None:
            raise OSError

        def flush(self) -> None:
            raise OSError

    class AttachedStdout:
        def write(self, _text: str) -> None:
            return None

        def flush(self) -> None:
            return None

    def attach_parent_console() -> bool:
        monkeypatch.setattr(sys, "stdout", AttachedStdout())
        return True

    monkeypatch.setattr(sys, "stdout", BrokenStdout())
    monkeypatch.setattr(app, "_attach_parent_console", attach_parent_console)

    app.main(["--cli", "--version"])

    assert calls == [["--version"]]
