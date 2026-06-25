from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtWidgets import QApplication

from matchpatch import config as matchpatch_config
from matchpatch.gui import main_window


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    QCoreApplication.setOrganizationName("MatchPatchTests")
    QCoreApplication.setApplicationName("MatchPatchTests")
    yield instance


@pytest.fixture(autouse=True)
def isolated_test_environment(tmp_path, monkeypatch, request):
    if request.node.path.name.startswith("test_gui"):
        config_path = tmp_path / "config" / "matchpatch" / "config.toml"
        monkeypatch.setattr(matchpatch_config, "default_config_paths", lambda: [config_path])
        monkeypatch.setattr(main_window, "default_config_path", lambda: config_path)
    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, str(tmp_path))
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    QSettings().clear()
    yield
    QSettings().clear()
