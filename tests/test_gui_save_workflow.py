from __future__ import annotations

# These focused GUI files include tests moved verbatim from tests/test_gui.py.
# Keep a broad import preamble while the old window-coupled assertions settle.
# ruff: noqa: F401, I001, F811
import csv
import json
import os
import threading
import time
import tomllib
import wave
import zipfile
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import (
    QAbstractAnimation,
    QCoreApplication,
    QEvent,
    QPoint,
    QRect,
    QSettings,
    QSize,
    Qt,
)
from PySide6.QtGui import QCloseEvent, QColor, QPalette, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenuBar,
    QMessageBox,
    QSizePolicy,
    QSplitter,
    QStyle,
    QTableWidgetItem,
    QTextEdit,
    QWidget,
)
from shiboken6 import isValid

from matchpatch.devices.base import (
    DeviceFileType,
    FileOperationCapabilities,
    NormalizationPolicy,
    PatchFileAdjustments,
)
from matchpatch.diagnostics import DiagnosticCheck
from matchpatch.gui import (
    advanced_settings,
    file_operations_workflow,
    icons,
    loudness_widgets,
    main_window,
    measurement_optimization,
    results,
)
from matchpatch.gui import worker as gui_worker
from matchpatch.gui.advanced_settings import (
    GuiSettingsState,
    PresetTableSelectionContext,
    append_optional_argument,
    parse_config_channel_mapping,
    request_with_preset_table_selection,
    selected_preset_set,
)
from matchpatch.gui.diagnostics_panel import (
    DiagnosticsPanel,
    format_hardware_check_request_details,
    format_preflight_results,
    format_preflight_results_html,
    hardware_check_failure_details,
    preflight_headline,
)
from matchpatch.gui.main_window import MainWindow
from matchpatch.gui.measurement_optimization import (
    MeasurementOptimizationDialog,
    MeasurementOptimizationSettings,
    MeasurementOptimizationSetupDialog,
    _optimization_progress_event_total,
)
from matchpatch.gui.preset_table import (
    ContentHeightTableWidget,
    SnapshotNameCellWidget,
    is_snapshot_adjustment_column,
    is_snapshot_name_column,
    snapshot_adjustment_column,
    snapshot_name_column,
    snapshot_output_column,
)
from matchpatch.gui.save_workflow import (
    SaveCancelled,
    SaveContext,
    SaveWorkflow,
    create_table_save_csv,
)
from matchpatch.gui.table_roles import IGNORE_REASON_COMPARISON
from matchpatch.gui.worker import NormalizationWorker
from matchpatch.measurement_optimizer import (
    TIMING_PARAMETERS,
    OptimizationProgress,
    StabilityStatistics,
)
from matchpatch.normalize import DEFAULT_REFERENCE_DI, DEFAULT_WINDOWS_PYTHON
from matchpatch.progress import ProgressEvent
from matchpatch.workflow import ImportRequest, NormalizationRequest, NormalizationResult
from gui_test_helpers import (
    FakePreflightWorker,
    FakeSaveChangesMessageBox,
    SignalStub,
    mock_single_hlx_handler,
    request,
    write_silent_wav,
)

_request = request
_write_silent_wav = write_silent_wav
_mock_single_hlx_handler = mock_single_hlx_handler
_SignalStub = SignalStub
_FakePreflightWorker = FakePreflightWorker
_FakeSaveChangesMessageBox = FakeSaveChangesMessageBox


class SaveMeasurementFileDialog:
    Option = QFileDialog.Option
    AcceptMode = QFileDialog.AcceptMode
    FileMode = QFileDialog.FileMode
    DialogLabel = QFileDialog.DialogLabel
    output_path = ""

    def __init__(self, *args):
        pass

    def setOption(self, option):
        pass

    def setAcceptMode(self, mode):
        pass

    def setFileMode(self, mode):
        pass

    def setNameFilter(self, file_filter):
        pass

    def selectFile(self, path):
        pass

    def setLabelText(self, label, text):
        pass

    def exec(self):
        return True

    def selectedFiles(self):
        return [str(self.output_path)]


class RecordingMeasurementHandler:
    created = []
    validated = []

    def validate_output(self, selected_input_path, selected_output_path):
        self.validated.append((selected_input_path, selected_output_path))

    def create_measurement_file(self, selected_input_path, selected_output_path):
        self.created.append((selected_input_path, selected_output_path))


class RecordingMeasurementProfile:
    @staticmethod
    def create_patch_file_handler(project_dir):
        return RecordingMeasurementHandler()


def install_save_measurement_fakes(monkeypatch, output_path, request):
    SaveMeasurementFileDialog.output_path = output_path
    RecordingMeasurementHandler.created = []
    RecordingMeasurementHandler.validated = []
    monkeypatch.setattr(main_window, "QFileDialog", SaveMeasurementFileDialog)
    monkeypatch.setattr(advanced_settings, "parse_args", lambda argv: argv)
    monkeypatch.setattr(advanced_settings, "apply_config", lambda args: args)
    monkeypatch.setattr(advanced_settings, "request_from_args", lambda args: request)
    monkeypatch.setattr(
        main_window, "get_device_profile", lambda device: RecordingMeasurementProfile()
    )
    return RecordingMeasurementHandler


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


class _Callbacks:
    def __init__(self, csv_path: Path | None = None, *, confirm: bool = True) -> None:
        self.csv_path = csv_path
        self.confirm = confirm
        self.confirmed_paths: list[Path] = []
        self.progress_events: list[ProgressEvent] = []

    def confirm_overwrite(self, output_path: Path) -> bool:
        self.confirmed_paths.append(output_path)
        return self.confirm

    def create_table_save_csv(self, directory: Path) -> Path:
        assert self.csv_path is not None
        return self.csv_path

    def table_adjustments(self) -> PatchFileAdjustments:
        return PatchFileAdjustments({}, {}, {})

    def update_progress(self, event: ProgressEvent) -> None:
        self.progress_events.append(event)


class _Handler:
    def __init__(self) -> None:
        self.validated: list[tuple[Path, Path]] = []
        self.measurements: list[tuple[Path, Path]] = []

    def validate_output(self, input_path: Path, output_path: Path) -> None:
        self.validated.append((input_path, output_path))

    def create_measurement_file(self, input_path: Path, output_path: Path) -> None:
        self.measurements.append((input_path, output_path))
        output_path.write_text("measurement", encoding="utf-8")


class _Profile:
    def __init__(self, handler: _Handler) -> None:
        self.handler = handler

    def create_patch_file_handler(self, project_dir: Path) -> _Handler:
        return self.handler


def test_create_table_save_csv_writes_patch_rows(tmp_path) -> None:
    csv_path = create_table_save_csv(
        tmp_path,
        snapshot_count=2,
        patches=["02B", "03C"],
        target_lufs="-15.5",
    )

    with csv_path.open("r", encoding="utf-8", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))

    assert rows == [
        {
            "DevicePatch": "02B",
            "LUFS1": "-15.5",
            "CrestFactor1": "12.0",
            "LUFS2": "-15.5",
            "CrestFactor2": "12.0",
        },
        {
            "DevicePatch": "03C",
            "LUFS1": "-15.5",
            "CrestFactor1": "12.0",
            "LUFS2": "-15.5",
            "CrestFactor2": "12.0",
        },
    ]


def test_save_adjusted_file_without_table_changes_copies_active_file(tmp_path) -> None:
    input_path = tmp_path / "input.hls"
    output_path = tmp_path / "output.hls"
    input_path.write_text("source", encoding="utf-8")
    callbacks = _Callbacks()

    result = SaveWorkflow().save_adjusted_file(
        SaveContext(
            input_path=input_path,
            output_path=output_path,
            completed_request=None,
            completed_result=None,
            table_has_unsaved_changes=False,
        ),
        callbacks,
    )

    assert result.copied_active_file
    assert not result.saved_table_changes
    assert output_path.read_text(encoding="utf-8") == "source"
    assert callbacks.confirmed_paths == [output_path]


def test_save_adjusted_file_replaces_active_input_via_temporary_output(tmp_path) -> None:
    input_path = tmp_path / "input.hls"
    csv_path = tmp_path / "analysis.csv"
    input_path.write_text("original", encoding="utf-8")
    csv_path.write_text("DevicePatch\n02B\n", encoding="utf-8")
    handler = _Handler()
    exported_paths: list[Path] = []

    def export_file(request, selected_csv_path, export_path, **kwargs) -> None:
        assert request.input_path == input_path
        assert selected_csv_path == csv_path
        assert kwargs["adjustments"] == PatchFileAdjustments({}, {}, {})
        exported_paths.append(export_path)
        export_path.write_text("adjusted", encoding="utf-8")

    workflow = SaveWorkflow(
        get_profile=lambda device: _Profile(handler),
        export_file=export_file,
    )
    callbacks = _Callbacks(csv_path)

    result = workflow.save_adjusted_file(
        SaveContext(
            input_path=input_path,
            output_path=input_path,
            completed_request=_request(input_path=input_path),
            completed_result=NormalizationResult(None, tmp_path, csv_path),
            table_has_unsaved_changes=True,
        ),
        callbacks,
    )

    assert result.saved_table_changes
    assert input_path.read_text(encoding="utf-8") == "adjusted"
    assert exported_paths and exported_paths[0] != input_path
    assert not exported_paths[0].exists()
    assert handler.validated == [(input_path, input_path)]


def test_save_measurement_file_honors_cancelled_overwrite(tmp_path) -> None:
    input_path = tmp_path / "input.hls"
    output_path = tmp_path / "measurement.hls"
    handler = _Handler()
    workflow = SaveWorkflow(get_profile=lambda device: _Profile(handler))

    with pytest.raises(SaveCancelled):
        workflow.save_measurement_file(
            _request(input_path=input_path),
            output_path,
            confirm_overwrite=lambda path: False,
        )

    assert handler.validated == [(input_path, output_path)]
    assert handler.measurements == []


class _FileOperationHandler:
    def __init__(
        self,
        *,
        capabilities: FileOperationCapabilities,
        file_kind: str = "setlist",
    ) -> None:
        self._capabilities = capabilities
        self._file_kind = file_kind

    def file_capabilities(self) -> FileOperationCapabilities:
        return self._capabilities

    def file_kind(self, path: Path) -> str:
        return self._file_kind

    @staticmethod
    def parse_patch_set(patch: str) -> list[int]:
        return {"01A": [1], "02B": [6], "03C": [11]}[patch]


class _FileOperationProfile:
    def __init__(self, handler: _FileOperationHandler) -> None:
        self.handler = handler

    def create_patch_file_handler(self, project_dir: Path) -> _FileOperationHandler:
        return self.handler


def test_file_operation_actions_are_gated_by_capabilities_and_active_kind(
    monkeypatch,
    app,
    tmp_path,
) -> None:
    window = MainWindow()
    input_path = tmp_path / "input.hls"
    input_path.write_text("{}", encoding="utf-8")
    window.input_path.setText(str(input_path))
    window._loaded_input_path = str(input_path)
    capabilities = FileOperationCapabilities(
        joins_presets_to_setlist=True,
        splits_setlist_to_presets=True,
    )
    handler = _FileOperationHandler(capabilities=capabilities, file_kind="setlist")
    monkeypatch.setattr(
        main_window, "get_device_profile", lambda device: _FileOperationProfile(handler)
    )

    window._refresh_file_actions()

    assert window.join_preset_files_action.isEnabled()
    assert window.split_setlist_action.isEnabled()

    handler._file_kind = "preset"
    window._refresh_file_actions()

    assert window.join_preset_files_action.isEnabled()
    assert not window.split_setlist_action.isEnabled()

    handler._capabilities = FileOperationCapabilities()
    window._refresh_file_actions()

    assert not window.join_preset_files_action.isEnabled()
    assert not window.split_setlist_action.isEnabled()
    window.close()


def test_join_preset_files_action_calls_workflow_and_opens_output(
    monkeypatch,
    app,
    tmp_path,
) -> None:
    window = MainWindow()
    preset_paths = [tmp_path / "lead.hlx", tmp_path / "rhythm.hlx"]
    output_path = tmp_path / "joined.hls"
    opened_paths: list[str] = []
    calls = []
    monkeypatch.setattr(
        file_operations_workflow,
        "choose_join_preset_paths",
        lambda parent, file_types=(): preset_paths,
    )
    monkeypatch.setattr(
        file_operations_workflow,
        "choose_join_output_path",
        lambda parent, file_types=(): output_path,
    )
    monkeypatch.setattr(window, "_open_input_path", opened_paths.append)

    def join_preset_files(device, selected_preset_paths, selected_output_path):
        calls.append((device, selected_preset_paths, selected_output_path))
        return file_operations_workflow.file_operations.JoinPresetFilesResult(
            output_path=selected_output_path
        )

    monkeypatch.setattr(
        file_operations_workflow.file_operations,
        "join_preset_files",
        join_preset_files,
    )

    assert file_operations_workflow.join_preset_files(window)

    assert calls == [("helix", preset_paths, output_path)]
    assert opened_paths == [str(output_path)]
    window.close()


def test_input_browse_uses_device_file_type_filter(monkeypatch, app) -> None:
    window = MainWindow()
    filters = []

    class Handler:
        @staticmethod
        def file_types():
            return (
                DeviceFileType("setlist", (".setlist",), "Fake setlist"),
                DeviceFileType("preset", (".preset",), "Fake preset"),
            )

    class Profile:
        @staticmethod
        def create_patch_file_handler(project_dir):
            return Handler()

    monkeypatch.setattr(
        main_window.file_type_filters,
        "get_device_profile",
        lambda device: Profile(),
    )

    def get_open_file_name(*args, **kwargs):
        filters.append(kwargs["filter"])
        return "", ""

    monkeypatch.setattr(QFileDialog, "getOpenFileName", get_open_file_name)

    window.browse_input()

    assert filters == ["Patches (*.setlist *.preset)"]
    window.close()


def test_join_dialogs_use_device_file_type_filters(monkeypatch, app, tmp_path) -> None:
    window = MainWindow()
    preset_paths = [tmp_path / "lead.preset"]
    output_path = tmp_path / "joined"
    filters = []

    class Handler:
        @staticmethod
        def file_types():
            return (
                DeviceFileType("setlist", (".setlist",), "Fake setlist"),
                DeviceFileType("preset", (".preset",), "Fake preset"),
            )

    class Profile:
        @staticmethod
        def create_patch_file_handler(project_dir):
            return Handler()

    monkeypatch.setattr(file_operations_workflow, "get_device_profile", lambda device: Profile())
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: filters.append(kwargs["filter"]) or ([str(preset_paths[0])], ""),
    )
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: filters.append(kwargs["filter"]) or (str(output_path), ""),
    )
    monkeypatch.setattr(window, "_open_input_path", lambda path: None)
    monkeypatch.setattr(
        file_operations_workflow.file_operations,
        "join_preset_files",
        lambda device, selected_preset_paths, selected_output_path: (
            file_operations_workflow.file_operations.JoinPresetFilesResult(
                output_path=selected_output_path
            )
        ),
    )

    assert file_operations_workflow.join_preset_files(window)

    assert filters == ["Preset files (*.preset)", "Setlist files (*.setlist)"]
    window.close()


def test_split_setlist_action_passes_selected_ids_and_original_filename_map(
    monkeypatch,
    app,
    tmp_path,
) -> None:
    window = MainWindow()
    input_path = tmp_path / "input.hls"
    output_dir = tmp_path / "split"
    created_paths = [output_dir / "rhythm.hlx"]
    window.input_path.setText(str(input_path))
    window._loaded_input_path = str(input_path)
    window.preset_table.setRowCount(0)
    for row, patch in enumerate(("01A", "02B", "03C")):
        window.preset_table.insertRow(row)
        window.preset_table.setItem(row, 1, QTableWidgetItem(patch))
        window.preset_table.setItem(row, 2, QTableWidgetItem(f"Preset {patch}"))
        window.preset_table.setItem(row, 3, QTableWidgetItem("Snap"))
    window.preset_table_controller.set_preset_original_filename(0, "lead.hlx")
    window.preset_table_controller.set_preset_original_filename(1, "rhythm.hlx")
    window.preset_table.selectRow(1)
    handler = _FileOperationHandler(
        capabilities=FileOperationCapabilities(splits_setlist_to_presets=True),
    )
    monkeypatch.setattr(
        main_window, "get_device_profile", lambda device: _FileOperationProfile(handler)
    )
    monkeypatch.setattr(
        file_operations_workflow, "choose_split_output_dir", lambda parent: output_dir
    )
    calls = []

    def split_setlist_file(
        device,
        selected_input_path,
        selected_output_dir,
        *,
        selected_ids=None,
        original_filenames=None,
    ):
        calls.append(
            (
                device,
                selected_input_path,
                selected_output_dir,
                selected_ids,
                original_filenames,
            )
        )
        return file_operations_workflow.file_operations.SplitSetlistFileResult(
            created_paths=created_paths
        )

    monkeypatch.setattr(
        file_operations_workflow.file_operations,
        "split_setlist_file",
        split_setlist_file,
    )

    assert file_operations_workflow.split_setlist(
        window,
        get_profile=main_window.get_device_profile,
        project_dir=Path(main_window.__file__).resolve().parents[3],
    )

    assert calls == [
        (
            "helix",
            input_path,
            output_dir,
            [6],
            {1: "lead.hlx", 6: "rhythm.hlx"},
        )
    ]
    assert any(str(created_paths[0].resolve()) in entry[2] for entry in window.log_entries)
    window.close()


def test_completion_enables_save_and_shows_success_popup(tmp_path, monkeypatch, app) -> None:
    window = MainWindow()
    window.input_path.setText(str(tmp_path / "input.hls"))
    window._loaded_input_path = window.input_path.text()
    information_popups = []
    warning_popups = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: information_popups.append(args))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warning_popups.append(args))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)

    window.normalization_completed(
        NormalizationResult(None, tmp_path, tmp_path / "lufs_analysis.csv")
    )

    assert len(information_popups) == 1
    assert information_popups[0][1] == "Normalization completed"
    assert "Normalization completed successfully" in information_popups[0][2]
    assert '"Save" or "Save As"' in information_popups[0][2]
    assert "import the saved file on your device" in information_popups[0][2]
    assert warning_popups == []
    assert window.save_action.isEnabled()
    assert "save the active file" in window.log.toHtml()

    window.close()


def test_completion_with_bad_lufs_shows_manual_adjustment_popup(
    tmp_path,
    monkeypatch,
    app,
) -> None:
    window = MainWindow()
    window.input_path.setText(str(tmp_path / "input.hls"))
    window._loaded_input_path = window.input_path.text()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)
    information_popups = []
    warning_popups = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: information_popups.append(args))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warning_popups.append(args))

    window.preset_table.insertRow(0)
    selected = QTableWidgetItem()
    selected.setCheckState(Qt.CheckState.Checked)
    window.preset_table.setItem(0, 0, selected)
    window.preset_table.setItem(0, 1, QTableWidgetItem("02B"))
    window.preset_table.setItem(0, 2, QTableWidgetItem("Song"))
    window.preset_table_controller.clear_preset_adjustments(0)
    window.preset_table_controller.set_snapshot_names(0, ("Clean", "Solo"))
    window.update_progress(ProgressEvent("log", message="[GAIN] 02B Clean | bad LUFS"))
    window.update_progress(ProgressEvent("preset_completed", device_patch="02B"))

    window.normalization_completed(
        NormalizationResult(None, tmp_path, tmp_path / "lufs_analysis.csv")
    )

    assert information_popups == []
    assert len(warning_popups) == 1
    assert warning_popups[0][1] == "Normalization completed with errors"
    assert "manual modifications are required" in warning_popups[0][2]
    assert "enough headroom to raise the output level if necessary" in warning_popups[0][2]
    assert "- 02B Song: snapshot 1 (Clean)" in warning_popups[0][2]
    assert '"Save" or "Save As"' in warning_popups[0][2]
    assert "import the saved file on your device" in warning_popups[0][2]

    window.close()


def test_discarding_before_normalization_preserves_preset_selection(
    tmp_path, monkeypatch, app
) -> None:
    window = MainWindow()
    input_path = tmp_path / "input.hls"
    input_path.write_text("{}", encoding="utf-8")

    class Handler:
        @staticmethod
        def validate_input(path):
            return None

        @staticmethod
        def list_assignments(path):
            return [
                SimpleNamespace(device_patch="02B", name="Song", snapshot_names=("Clean",)),
                SimpleNamespace(device_patch="03C", name="Lead", snapshot_names=("Solo",)),
            ]

        @staticmethod
        def metadata(path):
            return {"file_type": "hls"}

    class Profile:
        @staticmethod
        def create_patch_file_handler(project_dir):
            return Handler()

    monkeypatch.setattr(main_window, "get_device_profile", lambda device: Profile())
    monkeypatch.setattr(
        window,
        "_prompt_save_or_discard_preset_table_changes",
        lambda action: "discard",
    )
    window.input_path.setText(str(input_path))
    window.load_assignments()
    window.preset_table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    window.preset_table.selectRow(1)
    window._mark_preset_table_modified()

    assert window._prompt_save_before_normalization()

    assert (
        selected_preset_set(window._selected_measurable_preset_rows(), window._preset_patch_at_row)
        == "03C"
    )
    selected_rows = {
        index.row() for index in window.preset_table.selectionModel().selectedIndexes()
    }
    assert selected_rows == {1}
    assert window.preset_table.item(1, 1).text() == "03C"

    window.close()


def test_save_as_uses_file_selection_dialog(monkeypatch, app) -> None:
    window = MainWindow()
    window.input_path.setText("/tmp/input.hls")
    dialogs = []
    save_targets = []

    class FileDialog:
        class Option:
            DontUseNativeDialog = object()

        class AcceptMode:
            AcceptOpen = object()

        class FileMode:
            AnyFile = object()

        class DialogLabel:
            Accept = object()

        def __init__(self, parent, title):
            self.parent = parent
            self.title = title
            self.settings = []
            dialogs.append(self)

        def setOption(self, option):
            self.settings.append(("option", option))

        def setAcceptMode(self, mode):
            self.settings.append(("accept_mode", mode))

        def setFileMode(self, mode):
            self.settings.append(("file_mode", mode))

        def setNameFilter(self, file_filter):
            self.settings.append(("name_filter", file_filter))

        def setLabelText(self, label, text):
            self.settings.append(("label", label, text))

        @staticmethod
        def exec():
            return True

        @staticmethod
        def selectedFiles():
            return ["/tmp/output.hls"]

    monkeypatch.setattr(main_window, "QFileDialog", FileDialog)
    monkeypatch.setattr(
        window,
        "_save_to_path",
        lambda path, **kwargs: save_targets.append((path, kwargs)) or True,
    )

    window.save_active_file_as()

    assert save_targets == [(Path("/tmp/output.hls"), {"make_active": True})]
    assert dialogs[0].settings == [
        ("option", FileDialog.Option.DontUseNativeDialog),
        ("accept_mode", FileDialog.AcceptMode.AcceptOpen),
        ("file_mode", FileDialog.FileMode.AnyFile),
        ("name_filter", "Helix .hls (*.hls)"),
        ("label", FileDialog.DialogLabel.Accept, "Save as"),
    ]
    window.close()


def test_save_measurement_dialog_uses_loaded_suffix_and_save_label(
    tmp_path, monkeypatch, app
) -> None:
    window = MainWindow()
    input_path = tmp_path / "input.hlx"
    output_path = tmp_path / "measurement.hlx"
    dialogs = []

    class FileDialog:
        Option = QFileDialog.Option
        AcceptMode = QFileDialog.AcceptMode
        FileMode = QFileDialog.FileMode
        DialogLabel = QFileDialog.DialogLabel

        def __init__(self, *args):
            self.args = args
            self.settings = []
            dialogs.append(self)

        def setOption(self, option):
            self.settings.append(("option", option))

        def setAcceptMode(self, mode):
            self.settings.append(("accept_mode", mode))

        def setFileMode(self, mode):
            self.settings.append(("file_mode", mode))

        def setNameFilter(self, file_filter):
            self.settings.append(("name_filter", file_filter))

        def selectFile(self, path):
            self.settings.append(("select_file", path))

        def setLabelText(self, label, text):
            self.settings.append(("label", label, text))

        def exec(self):
            return True

        def selectedFiles(self):
            return [str(output_path)]

    monkeypatch.setattr(main_window, "QFileDialog", FileDialog)
    window.input_path.setText(str(input_path))

    assert window._choose_measurement_save_path() == output_path
    assert dialogs[0].args[1] == "Save measurement file"
    assert dialogs[0].settings == [
        ("option", FileDialog.Option.DontUseNativeDialog),
        ("accept_mode", FileDialog.AcceptMode.AcceptSave),
        ("file_mode", FileDialog.FileMode.AnyFile),
        ("name_filter", "Helix .hlx (*.hlx)"),
        ("select_file", str(tmp_path / "input_measurement.hlx")),
        ("label", FileDialog.DialogLabel.Accept, "Save"),
    ]
    window.close()


def test_save_measurement_file_creates_matching_measurement_file(
    tmp_path, monkeypatch, app
) -> None:
    window = MainWindow()
    input_path = tmp_path / "input.hls"
    output_path = tmp_path / "manual_measurement.hls"
    input_path.touch()
    request = NormalizationRequest(
        device="helix",
        input_path=input_path,
        backend="loopback",
        windows_python=str(DEFAULT_WINDOWS_PYTHON),
        reference_di=DEFAULT_REFERENCE_DI,
    )
    handler = install_save_measurement_fakes(monkeypatch, output_path, request)
    window.input_path.setText(str(input_path))
    window._loaded_input_path = str(input_path)
    window._refresh_file_actions()

    assert window.save_measurement_action.isEnabled()
    assert window.save_measurement_file()
    assert handler.validated == [(input_path, output_path)]
    assert handler.created == [(input_path, output_path)]
    window.close()


def test_save_measurement_file_rejects_mismatched_suffix(tmp_path, monkeypatch, app) -> None:
    window = MainWindow()
    input_path = tmp_path / "input.hls"
    output_path = tmp_path / "measurement.hlx"
    errors = []

    class FileDialog:
        Option = QFileDialog.Option
        AcceptMode = QFileDialog.AcceptMode
        FileMode = QFileDialog.FileMode
        DialogLabel = QFileDialog.DialogLabel

        def __init__(self, *args):
            pass

        def setOption(self, option):
            pass

        def setAcceptMode(self, mode):
            pass

        def setFileMode(self, mode):
            pass

        def setNameFilter(self, file_filter):
            pass

        def selectFile(self, path):
            pass

        def setLabelText(self, label, text):
            pass

        def exec(self):
            return True

        def selectedFiles(self):
            return [str(output_path)]

    monkeypatch.setattr(main_window, "QFileDialog", FileDialog)
    monkeypatch.setattr(window, "show_error", errors.append)
    window.input_path.setText(str(input_path))

    assert window._choose_measurement_save_path() is None
    assert errors == ["Measurement file must use the .hls extension"]
    window.close()


def test_single_preset_save_as_preserves_preset_table_state(tmp_path, monkeypatch, app) -> None:
    window = MainWindow()
    input_path = tmp_path / "input.hlx"
    output_path = tmp_path / "output.hlx"
    csv_path = tmp_path / "lufs_analysis.csv"
    input_path.touch()
    csv_path.touch()
    exports = []

    class Handler:
        @staticmethod
        def validate_input(path):
            return None

        @staticmethod
        def validate_output(selected_input_path, selected_output_path):
            assert selected_input_path == input_path
            assert selected_output_path == output_path

        @staticmethod
        def list_assignments(path):
            name = "Saved" if path == output_path else "Loaded"
            return [
                SimpleNamespace(
                    device_patch="01A",
                    name=name,
                    snapshot_names=("Clean", "Solo"),
                )
            ]

        @staticmethod
        def metadata(path):
            return {"file_type": "hlx"}

    class Profile:
        @staticmethod
        def create_patch_file_handler(project_dir):
            return Handler()

    monkeypatch.setattr(main_window, "get_device_profile", lambda device: Profile())

    def export_adjusted_file(*args, **kwargs):
        exports.append((args, kwargs))
        output_path.touch()

    monkeypatch.setattr(main_window, "export_adjusted_file", export_adjusted_file)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)

    window.input_path.setText(str(input_path))
    window.load_assignments()
    window.preset_table.item(0, 1).setText("12a")
    window.preset_table_controller.set_adjustment_value(window.preset_table.item(0, 5), "+1.0", 1.0)
    window._mark_preset_table_modified()
    window.completed_request = _request(input_path=input_path)
    window.completed_result = NormalizationResult(None, tmp_path, csv_path)

    assert window._save_to_path(output_path)

    assert len(exports) == 1
    assert window.input_path.text() == str(output_path)
    assert window.preset_table.item(0, 1).text() == "12A"
    assert window.preset_table.item(0, 2).text() == "Loaded"
    assert window.preset_table.item(0, 5).text() == "+1.0"
    assert not window._preset_table_has_unsaved_changes()

    window.close()


def test_saving_table_changes_preserves_preset_selection(tmp_path, monkeypatch, app) -> None:
    window = MainWindow()
    input_path = tmp_path / "input.hls"
    input_path.write_text("{}", encoding="utf-8")
    csv_path = tmp_path / "lufs_analysis.csv"
    csv_path.touch()

    class Handler:
        @staticmethod
        def validate_input(path):
            return None

        @staticmethod
        def validate_output(selected_input_path, selected_output_path):
            assert selected_input_path == input_path
            assert selected_output_path == input_path

        @staticmethod
        def list_assignments(path):
            return [
                SimpleNamespace(device_patch="02B", name="Song", snapshot_names=("Clean",)),
                SimpleNamespace(device_patch="03C", name="Lead", snapshot_names=("Solo",)),
            ]

        @staticmethod
        def metadata(path):
            return {"file_type": "hls"}

    class Profile:
        @staticmethod
        def create_patch_file_handler(project_dir):
            return Handler()

    monkeypatch.setattr(main_window, "get_device_profile", lambda device: Profile())

    def export_adjusted_file(*args, **kwargs):
        args[2].touch()

    monkeypatch.setattr(main_window, "export_adjusted_file", export_adjusted_file)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)

    window.input_path.setText(str(input_path))
    window.load_assignments()
    window.preset_table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    window.preset_table.selectRow(1)
    window._mark_preset_table_modified()
    window.completed_request = _request(input_path=input_path)
    window.completed_result = NormalizationResult(None, tmp_path, csv_path)

    assert window.save_active_file()

    assert (
        selected_preset_set(window._selected_measurable_preset_rows(), window._preset_patch_at_row)
        == "03C"
    )
    selected_rows = {
        index.row() for index in window.preset_table.selectionModel().selectedIndexes()
    }
    assert selected_rows == {1}
    assert not window._preset_table_has_unsaved_changes()

    window.close()


def test_output_save_picker_uses_save_button(monkeypatch, app) -> None:
    window = MainWindow()
    window.input_path.setText(str(Path("/tmp/input.hls")))
    dialogs = []

    class FileDialog:
        class Option:
            DontUseNativeDialog = object()

        class AcceptMode:
            AcceptOpen = object()

        class FileMode:
            AnyFile = object()

        class DialogLabel:
            Accept = object()

        def __init__(self, parent, title):
            self.parent = parent
            self.title = title
            self.settings = []
            dialogs.append(self)

        def setOption(self, option):
            self.settings.append(("option", option))

        def setAcceptMode(self, mode):
            self.settings.append(("accept_mode", mode))

        def setFileMode(self, mode):
            self.settings.append(("file_mode", mode))

        def setNameFilter(self, file_filter):
            self.settings.append(("name_filter", file_filter))

        def setLabelText(self, label, text):
            self.settings.append(("label", label, text))

        @staticmethod
        def exec():
            return True

        @staticmethod
        def selectedFiles():
            return [str(Path("/tmp/output.hls"))]

    monkeypatch.setattr(main_window, "QFileDialog", FileDialog)

    window.browse_output()

    assert window.output_path.text() == str(Path("/tmp/output.hls"))
    assert dialogs[0].settings[-1] == ("label", FileDialog.DialogLabel.Accept, "Save")
    window.close()


def test_save_prompts_before_overwriting_existing_file(tmp_path, monkeypatch, app) -> None:
    window = MainWindow()
    input_path = tmp_path / "input.hls"
    input_path.touch()
    csv_path = tmp_path / "lufs_analysis.csv"
    exported = []
    prompts = []

    class Handler:
        @staticmethod
        def validate_output(input_path, selected_output_path):
            assert selected_output_path == input_path

    class Profile:
        @staticmethod
        def create_patch_file_handler(project_dir):
            return Handler()

    window.input_path.setText(str(input_path))
    window._mark_preset_table_modified()
    window.completed_request = _request(input_path=input_path)
    window.completed_result = NormalizationResult(None, tmp_path, csv_path)
    monkeypatch.setattr(main_window, "get_device_profile", lambda device: Profile())
    monkeypatch.setattr(
        main_window, "export_adjusted_file", lambda *args, **kwargs: exported.append(args)
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args: prompts.append(args) or QMessageBox.StandardButton.No,
    )

    window.save_active_file()

    assert len(prompts) == 1
    assert exported == []
    window.close()


def test_automation_overwrite_confirmation_only_prompts_for_existing_files(
    tmp_path, monkeypatch, app
) -> None:
    window = MainWindow()
    input_path = tmp_path / "input.hls"
    measurement_path = tmp_path / "input_measurement.hls"
    adjusted_path = tmp_path / "input_adjusted.hls"
    measurement_path.touch()
    adjusted_path.touch()
    prompts = []

    class Handler:
        @staticmethod
        def automation_output_path(path, postfix):
            return path.with_name(path.stem + postfix + path.suffix)

    class Profile:
        @staticmethod
        def create_patch_file_handler(project_dir):
            return Handler()

    request = NormalizationRequest(
        device="helix",
        input_path=input_path,
        backend="loopback",
        windows_python=str(DEFAULT_WINDOWS_PYTHON),
        reference_di=DEFAULT_REFERENCE_DI,
        automation=True,
    )
    monkeypatch.setattr(main_window, "get_device_profile", lambda device: Profile())
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args: prompts.append(args) or QMessageBox.StandardButton.Yes,
    )

    assert window._confirm_automation_overwrites(request)
    assert len(prompts) == 1
    assert "measurement" in prompts[0][2]
    assert str(measurement_path) in prompts[0][2]
    assert str(adjusted_path) not in prompts[0][2]

    window.close()


def test_normalization_does_not_start_when_overwrite_is_declined(
    tmp_path, monkeypatch, app
) -> None:
    window = MainWindow()
    input_path = tmp_path / "input.hls"
    measurement_path = tmp_path / "input_measurement.hls"
    measurement_path.touch()

    class Handler:
        @staticmethod
        def automation_output_path(path, postfix):
            return path.with_name(path.stem + postfix + path.suffix)

    class Profile:
        @staticmethod
        def create_patch_file_handler(project_dir):
            return Handler()

    request = NormalizationRequest(
        device="helix",
        input_path=input_path,
        backend="loopback",
        windows_python=str(DEFAULT_WINDOWS_PYTHON),
        reference_di=DEFAULT_REFERENCE_DI,
    )
    monkeypatch.setattr(advanced_settings, "parse_args", lambda argv: object())
    monkeypatch.setattr(advanced_settings, "apply_config", lambda args: args)
    monkeypatch.setattr(advanced_settings, "request_from_args", lambda args: request)
    monkeypatch.setattr(main_window, "get_device_profile", lambda device: Profile())
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    window.input_path.setText(str(input_path))
    window._loaded_input_path = str(input_path)
    window._refresh_file_actions()

    window.start_normalization()

    assert window.worker is None
    assert window.start_button.isEnabled()
    assert window.start_cancel_stack.currentWidget() is window.start_button
    assert window.phase.text() == "Ready"

    window.close()
