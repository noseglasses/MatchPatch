from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from matchpatch.gui import device_panel_registry, device_panels, main_window
from matchpatch.gui.main_window import MainWindow


class _GuiEntryPoint:
    def __init__(self, name: str, loaded: object) -> None:
        self.name = name
        self._loaded = loaded

    def load(self) -> object:
        if isinstance(self._loaded, BaseException):
            raise self._loaded
        return self._loaded


class _GuiEntryPoints(list[_GuiEntryPoint]):
    def select(self, *, group: str) -> list[_GuiEntryPoint]:
        if group == device_panel_registry.ENTRY_POINT_GROUP:
            return list(self)
        return []


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


def test_plugin_device_settings_panel_is_selected_before_builtin_mapping(
    monkeypatch,
    app,
) -> None:
    class PluginPanelFactory:
        device_name = "helix"

        def create_panel(self, profile, backend_selector):
            panel = QLabel(f"{profile.name}:{backend_selector.objectName()}")
            panel.setObjectName("plugin-helix-panel")
            return panel

    monkeypatch.setattr(
        device_panel_registry.metadata,
        "entry_points",
        lambda: _GuiEntryPoints([_GuiEntryPoint("helix-gui", PluginPanelFactory())]),
    )
    backend = QWidget()
    backend.setObjectName("backend-selector")

    panel = device_panels.create_settings_panel(main_window.get_device_profile("helix"), backend)

    assert isinstance(panel, QLabel)
    assert panel.objectName() == "plugin-helix-panel"
    assert panel.text() == "helix:backend-selector"
    assert device_panel_registry.plugin_load_errors() == {}


def test_broken_plugin_device_settings_panel_does_not_break_main_window_startup(
    monkeypatch,
    app,
) -> None:
    monkeypatch.setattr(
        device_panel_registry.metadata,
        "entry_points",
        lambda: _GuiEntryPoints([_GuiEntryPoint("broken-gui", RuntimeError("boom"))]),
    )

    window = MainWindow()

    assert window.device.findData("helix") >= 0
    assert "helix" in window.device_panels
    assert device_panel_registry.plugin_load_errors() == {"broken-gui": "boom"}

    window.close()
