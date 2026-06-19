from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtWidgets import QApplication, QMessageBox

from matchpatch.gui import main_window, window_state
from matchpatch.gui.main_window import MainWindow
from matchpatch.normalize import DEFAULT_REFERENCE_DI, DEFAULT_WINDOWS_PYTHON
from matchpatch.workflow import NormalizationRequest, NormalizationResult


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


def _request(**kwargs) -> NormalizationRequest:
    values = dict(
        device="helix",
        input_path=Path("input.hls"),
        backend="loopback",
        windows_python=str(DEFAULT_WINDOWS_PYTHON),
        reference_di=DEFAULT_REFERENCE_DI,
        automation=False,
    )
    values.update(kwargs)
    return NormalizationRequest(**values)


def _mock_loaded_file_profile(monkeypatch, name: str = "Loaded") -> None:
    class Handler:
        @staticmethod
        def file_kind(path):
            return "preset"

        @staticmethod
        def validate_input(path):
            return None

        @staticmethod
        def list_assignments(path):
            return [
                SimpleNamespace(
                    device_patch="01A",
                    name=name,
                    snapshot_names=("Clean", "Solo"),
                    snapshot_output_levels=((0.0,), (-1.0,)),
                )
            ]

        @staticmethod
        def metadata(path):
            return {"file_type": "preset"}

    profile = SimpleNamespace(
        create_patch_file_handler=lambda root: Handler(),
        measurement_backends=lambda: ("hardware", "loopback"),
        max_snapshot_count=8,
    )
    monkeypatch.setattr(main_window, "get_device_profile", lambda device: profile)


def test_podgo_uses_shared_backend_selector(app) -> None:
    window = MainWindow()
    window.device.setCurrentIndex(window.device.findData("podgo"))
    app.processEvents()

    assert window.device.currentData() == "podgo"
    assert [window.backend.itemText(index) for index in range(window.backend.count())] == [
        "hardware",
        "loopback",
        "simulated",
    ]
    assert window.advanced_tabs.widget(0).isAncestorOf(window.backend)

    window.close()


def test_recent_files_selector_filters_by_active_device(tmp_path, app) -> None:
    helix_setlist = tmp_path / "helix.hls"
    helix_preset = tmp_path / "helix.hlx"
    podgo_setlist = tmp_path / "podgo.pgs"
    podgo_preset = tmp_path / "podgo.pgp"
    for path in (helix_setlist, helix_preset, podgo_setlist, podgo_preset):
        path.touch()
    QSettings().setValue(
        window_state.RECENT_FILES_SETTINGS_KEY,
        [str(helix_setlist), str(podgo_setlist), str(helix_preset), str(podgo_preset)],
    )
    window = MainWindow()

    assert [
        window.recent_files.itemData(index) for index in range(1, window.recent_files.count())
    ] == [str(helix_setlist), str(helix_preset)]

    window.device.setCurrentIndex(window.device.findData("podgo"))
    app.processEvents()

    assert [
        window.recent_files.itemData(index) for index in range(1, window.recent_files.count())
    ] == [str(podgo_setlist), str(podgo_preset)]

    window.close()


def test_device_change_cancel_keeps_loaded_adjusted_table(tmp_path, monkeypatch, app) -> None:
    _mock_loaded_file_profile(monkeypatch)
    window = MainWindow()
    input_file = tmp_path / "loaded.hlx"
    input_file.touch()
    window.input_path.setText(str(input_file))
    window.load_assignments()
    window.preset_table.item(0, 2).setText("Edited")
    window._mark_preset_table_modified()
    previous_index = window.device.currentIndex()
    prompts = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args: prompts.append(args) or QMessageBox.StandardButton.Cancel,
    )

    window.device.setCurrentIndex(window.device.findData("podgo"))
    app.processEvents()

    assert prompts
    assert window.device.currentIndex() == previous_index
    assert window.input_path.text() == str(input_file)
    assert window.preset_table.rowCount() == 1
    assert window.preset_table.item(0, 2).text() == "Edited"
    assert window._preset_table_has_unsaved_changes()

    window.close()


def test_device_change_discard_clears_loaded_normalization_state(
    tmp_path, monkeypatch, app
) -> None:
    _mock_loaded_file_profile(monkeypatch)
    window = MainWindow()
    input_file = tmp_path / "loaded.hlx"
    input_file.touch()
    window.input_path.setText(str(input_file))
    window.load_assignments()
    window.completed_request = _request(input_path=input_file)
    window.completed_result = NormalizationResult(None, tmp_path, tmp_path / "analysis.csv")
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args: QMessageBox.StandardButton.Discard,
    )

    window.device.setCurrentIndex(window.device.findData("podgo"))
    app.processEvents()

    assert window.device.currentData() == "podgo"
    assert window.input_path.text() == ""
    assert window._loaded_input_path == ""
    assert window.preset_table.rowCount() == 0
    assert window.completed_request is None
    assert window.completed_result is None
    assert not window.preset_empty_state.isHidden()
    assert not window._preset_table_has_unsaved_changes()

    window.close()
