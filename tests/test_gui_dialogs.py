from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QLabel

from matchpatch import __version__
from matchpatch.gui.app import qt_message_handler, register_desktop_entry
from matchpatch.gui.dialogs import PROJECT_URL, AboutDialog, HelpDialog
from matchpatch.gui.help import HelpId


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


def test_about_dialog_displays_project_metadata_and_logo(app) -> None:
    dialog = AboutDialog()
    labels = dialog.findChildren(QLabel)
    texts = [label.text() for label in labels]

    logo = next(label.pixmap() for label in labels if label.pixmap() is not None)
    assert logo.height() == 320
    assert any("MatchPatch" in text for text in texts)
    assert any(__version__ in text for text in texts)
    assert any("Documentation" in text for text in texts)
    assert any(PROJECT_URL in text for text in texts)
    assert dialog.property("help_id") == HelpId.DOCS_INDEX
    assert any("MIT License" in text for text in texts)
    assert any("Copyright" in text for text in texts)
    assert not dialog.windowIcon().isNull()


def test_help_dialog_is_available(app) -> None:
    dialog = HelpDialog()

    assert dialog.windowTitle() == "MatchPatch Help"
    assert not dialog.windowIcon().isNull()


def test_known_qt_platform_noise_is_suppressed(capsys) -> None:
    qt_message_handler(
        SimpleNamespace(),
        SimpleNamespace(),
        "This plugin supports grabbing the mouse only for popup windows",
    )
    assert capsys.readouterr().err == ""


def test_other_qt_messages_remain_visible(capsys) -> None:
    qt_message_handler(SimpleNamespace(), SimpleNamespace(), "Useful Qt diagnostic")
    assert "Useful Qt diagnostic" in capsys.readouterr().err


def test_desktop_entry_registers_matchpatch_icon(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    register_desktop_entry()

    entry = (tmp_path / "applications" / "matchpatch-gui.desktop").read_text(encoding="utf-8")
    installed_icon = tmp_path / "icons" / "hicolor" / "512x512" / "apps" / "matchpatch-gui.png"
    icon = QImage(str(installed_icon))

    assert "Name=MatchPatch" in entry
    assert installed_icon.is_file()
    assert f"Icon={installed_icon}" in entry
    assert "StartupWMClass=matchpatch-gui" in entry
    assert icon.width() == 512
    assert icon.height() == 512


def test_desktop_entry_registers_wslg_visible_data_dir(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "usr" / "local" / "share"
    user_data = tmp_path / "home" / ".local" / "share"
    monkeypatch.setenv("XDG_DATA_DIRS", str(data_dir))
    monkeypatch.setenv("XDG_DATA_HOME", str(user_data))

    register_desktop_entry()

    desktop_file = data_dir / "applications" / "matchpatch-gui.desktop"
    installed_icon = data_dir / "icons" / "hicolor" / "512x512" / "apps" / "matchpatch-gui.png"
    icon = QImage(str(installed_icon))

    assert f"Icon={installed_icon}" in desktop_file.read_text(encoding="utf-8")
    assert icon.width() == 512
    assert icon.height() == 512
