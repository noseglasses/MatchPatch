from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    QCoreApplication.setOrganizationName("MatchPatchTests")
    QCoreApplication.setApplicationName("MatchPatchTests")
    yield instance


@pytest.fixture(autouse=True)
def isolated_qsettings(tmp_path):
    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, str(tmp_path))
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    QSettings().clear()
    yield
    QSettings().clear()
