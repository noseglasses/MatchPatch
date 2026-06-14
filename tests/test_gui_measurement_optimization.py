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

from matchpatch.devices.base import NormalizationPolicy, PatchFileAdjustments
from matchpatch.diagnostics import DiagnosticCheck
from matchpatch.gui import (
    advanced_settings,
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


def _settings(**kwargs) -> MeasurementOptimizationSettings:
    values = dict(
        pre_roll=0.2,
        post_roll=0.1,
        round_trip_latency=0.02,
        preset_wait=0.5,
        snapshot_wait=0.2,
        measurement_wait=0.1,
        stability_runs=3,
        termination_tolerance=10.0,
        stability_tolerance=2.0,
    )
    values.update(kwargs)
    return MeasurementOptimizationSettings(**values)


def test_measurement_optimization_dialog_shows_latest_statistics(app) -> None:
    dialog = MeasurementOptimizationDialog()
    statistics = StabilityStatistics(
        snapshot1_lufs_mean=-18.1234,
        snapshot1_lufs_std=0.0023,
        snapshot1_crest_mean=11.5678,
        snapshot1_crest_std=0.0045,
        snapshot2_lufs_mean=-21.9876,
        snapshot2_lufs_std=0.0067,
        snapshot2_crest_mean=14.1234,
        snapshot2_crest_std=0.0089,
        tolerance_percent=0.5,
        snapshot1_lufs_tolerance=0.0906,
        snapshot1_lufs_max_deviation=0.0023,
        snapshot1_crest_tolerance=0.0578,
        snapshot1_crest_max_deviation=0.0045,
        snapshot2_lufs_tolerance=0.1099,
        snapshot2_lufs_max_deviation=0.0067,
        snapshot2_crest_tolerance=0.0706,
        snapshot2_crest_max_deviation=0.0089,
    )

    dialog.update_progress(
        OptimizationProgress(
            "candidate_completed",
            "Measurement wait: 0.5 s unstable",
            parameter="measurement_wait",
            candidate=0.5,
            stable=False,
            statistics=statistics,
        )
    )

    assert dialog.table.columnCount() == 4
    assert dialog.table.horizontalHeaderItem(3).text() == "Latest stats"
    assert dialog.table.columnWidth(3) == 900
    assert dialog.table.textElideMode() == Qt.TextElideMode.ElideNone
    assert dialog.table.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    stats_item = dialog.table.item(0, 3)
    assert stats_item is not None
    assert "tol 0.5%" in stats_item.text()
    assert "S1 LUFS mean -18.123, std 0.0023" in stats_item.text()
    assert "S2 crest mean 14.123, std 0.0089" in stats_item.text()

    dialog.set_finished()
    dialog.accept()
    dialog.deleteLater()


def test_measurement_optimization_dialog_shows_runtime_estimate(app) -> None:
    dialog = MeasurementOptimizationDialog(_settings())

    notice = dialog.runtime_notice.text()

    assert notice.startswith("Parameter optimization is running")
    assert "up to 24 bisection checks" in notice
    assert "across 6 parameters" in notice
    assert "about <strong>14 min 32 s</strong>" in notice
    assert "can be shorter" in notice
    assert "background: #eff6ff" in dialog.runtime_notice.styleSheet()
    assert "color: #1d4ed8" in dialog.runtime_notice.styleSheet()

    dialog.set_finished()
    dialog.accept()
    dialog.deleteLater()


def test_measurement_optimization_dialog_shows_success_duration_summary(app) -> None:
    dialog = MeasurementOptimizationDialog(_settings())
    dialog._started_at = measurement_optimization.datetime.now() - timedelta(seconds=65)

    dialog.set_result("[analysis]\npre_roll_seconds = 0.1")
    notice = dialog.runtime_notice.text()

    assert "Parameter optimization successfully finished" in notice
    assert "Actual duration:" in notice
    assert "Predicted duration: 14 min 32 s" in notice
    assert "background: #f0fdf4" in dialog.runtime_notice.styleSheet()
    assert "color: #166534" in dialog.runtime_notice.styleSheet()

    dialog.accept()
    dialog.deleteLater()


def test_measurement_optimization_dialog_shows_failure_duration_summary(app) -> None:
    dialog = MeasurementOptimizationDialog(_settings())
    dialog._started_at = measurement_optimization.datetime.now() - timedelta(seconds=125)

    dialog.set_failed()
    notice = dialog.runtime_notice.text()

    assert "Parameter optimization failed" in notice
    assert "Actual duration:" in notice
    assert "Predicted duration: 14 min 32 s" in notice
    assert "background: #fef2f2" in dialog.runtime_notice.styleSheet()
    assert "color: #991b1b" in dialog.runtime_notice.styleSheet()

    dialog.accept()
    dialog.deleteLater()


def test_measurement_optimization_dialog_updates_progress_bar_below_table(app) -> None:
    settings = _settings()
    dialog = MeasurementOptimizationDialog(settings)
    main_layout = dialog.main_panel.layout()
    side_layout = dialog.side_panel.layout()

    assert dialog.layout().indexOf(dialog.content_splitter) >= 0
    assert dialog.content_splitter.count() == 2
    assert dialog.content_splitter.widget(0) is dialog.main_panel
    assert dialog.content_splitter.widget(1) is dialog.side_panel
    assert main_layout.indexOf(dialog.status) < main_layout.indexOf(dialog.table)
    assert main_layout.indexOf(dialog.progress_bar) > main_layout.indexOf(dialog.table)
    assert main_layout.indexOf(dialog.convergence_plot) > main_layout.indexOf(dialog.progress_bar)
    assert side_layout.indexOf(dialog.runtime_notice) == 0
    assert side_layout.indexOf(dialog.runtime_notice) < side_layout.indexOf(
        dialog.fixed_settings_panel
    )
    assert side_layout.indexOf(dialog.fixed_settings_panel) < side_layout.indexOf(dialog.info)
    assert side_layout.indexOf(dialog.info) < side_layout.indexOf(dialog.result_text)
    assert dialog.progress_bar.maximum() == _optimization_progress_event_total(settings)
    assert dialog.progress_bar.value() == 0
    assert [row.parameter for row in dialog.convergence_plot._ordered_rows()] == [
        "pre_roll",
        "post_roll",
        "snapshot_wait",
        "measurement_wait",
        "preset_wait",
        "round_trip_latency",
    ]

    dialog.update_progress(
        OptimizationProgress(
            "parameter_started",
            "Investigating Pre-roll",
            parameter="pre_roll",
            low=0.0,
            high=0.2,
            best=0.2,
            iteration=0,
        )
    )
    assert dialog.progress_bar.value() == 1
    assert dialog.progress_bar.format() == "%p%"
    row = dialog.convergence_plot._rows["pre_roll"]
    assert row.low == 0.0
    assert row.high == 0.2
    assert row.best == 0.2

    dialog.update_progress(
        OptimizationProgress(
            "candidate_completed",
            "Pre-roll: 0.1 s stable",
            parameter="pre_roll",
            candidate=0.1,
            stable=True,
            low=0.0,
            high=0.1,
            best=0.1,
            iteration=1,
        )
    )
    assert dialog.progress_bar.value() == 2
    assert row.low == 0.0
    assert row.high == 0.1
    assert row.best == 0.1
    assert row.iteration == 1
    assert row.candidates is not None
    assert [(candidate.value, candidate.stable) for candidate in row.candidates] == [(0.1, True)]

    dialog.set_result("[analysis]\npre_roll_seconds = 0.1")
    assert dialog.progress_bar.value() == dialog.progress_bar.maximum()
    assert dialog.progress_bar.format() == "Completed"

    dialog.accept()
    dialog.deleteLater()


def test_measurement_optimization_dialog_lists_fixed_settings_at_top(app) -> None:
    settings = _settings(
        stability_runs=5,
        termination_tolerance=7.5,
        stability_tolerance=0.5,
        pinned_parameters=("pre_roll", "measurement_wait"),
    )
    dialog = MeasurementOptimizationDialog(settings)

    assert dialog.fixed_settings_panel.title() == "Fixed study settings"
    assert dialog.fixed_settings_values["Stability runs"].text() == "5"
    assert dialog.fixed_settings_values["Termination tolerance"].text() == "7.5%"
    assert dialog.fixed_settings_values["Stability tolerance"].text() == "0.5%"
    assert (
        dialog.fixed_settings_values["Pinned timing parameters"].text()
        == "Pre-roll, Measurement wait"
    )
    assert "not optimized or bisected" in dialog.fixed_settings_panel.toolTip()

    dialog.set_finished()
    dialog.accept()
    dialog.deleteLater()


def test_measurement_optimization_dialog_status_text_is_selectable(app) -> None:
    dialog = MeasurementOptimizationDialog()

    dialog.set_status("Parameter study failed: backend detail")

    flags = dialog.status.textInteractionFlags()
    assert flags & Qt.TextInteractionFlag.TextSelectableByMouse
    assert flags & Qt.TextInteractionFlag.TextSelectableByKeyboard
    assert dialog.status.wordWrap()
    assert dialog.status.text() == "Parameter study failed: backend detail"

    dialog.set_finished()
    dialog.accept()
    dialog.deleteLater()


def test_measurement_optimization_dialog_apply_emits_result(app) -> None:
    dialog = MeasurementOptimizationDialog()
    applied = []
    dialog.applied.connect(applied.append)

    assert not dialog.apply_button.isEnabled()

    dialog.set_result("[analysis]\npre_roll_seconds = 0.7")
    dialog.apply_button.click()

    assert applied == ["[analysis]\npre_roll_seconds = 0.7"]

    dialog.accept()
    dialog.deleteLater()


def test_optimization_dialog_action_button_becomes_close(monkeypatch, app) -> None:
    dialog = MeasurementOptimizationDialog()
    answers = [
        QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    ]
    monkeypatch.setattr(QMessageBox, "question", lambda *args: answers.pop(0))

    assert dialog.action_button.text() == "Abort"

    dialog.set_finished()

    assert dialog.action_button.text() == "Close"

    first_event = QCloseEvent()
    dialog.closeEvent(first_event)

    assert not first_event.isAccepted()

    second_event = QCloseEvent()
    dialog.closeEvent(second_event)

    assert second_event.isAccepted()

    dialog.deleteLater()


def test_optimization_dialog_abort_button_confirms_abort(monkeypatch, app) -> None:
    dialog = MeasurementOptimizationDialog()
    cancelled = []
    answers = [
        QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    ]
    monkeypatch.setattr(QMessageBox, "question", lambda *args: answers.pop(0))
    dialog.cancelled.connect(lambda: cancelled.append(True))

    dialog.action_button.click()

    assert cancelled == []
    assert dialog.action_button.isEnabled()

    dialog.action_button.click()

    assert cancelled == [True]
    assert not dialog.isVisible()

    dialog.set_finished()
    dialog.accept()
    dialog.deleteLater()


def test_optimization_dialog_close_confirms_abort(monkeypatch, app) -> None:
    dialog = MeasurementOptimizationDialog()
    cancelled = []
    answers = [
        QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    ]
    monkeypatch.setattr(QMessageBox, "question", lambda *args: answers.pop(0))
    dialog.cancelled.connect(lambda: cancelled.append(True))

    assert dialog.action_button.text() == "Abort"

    first_event = QCloseEvent()
    dialog.closeEvent(first_event)

    assert not first_event.isAccepted()
    assert cancelled == []
    assert dialog.cancel_button.isEnabled()

    second_event = QCloseEvent()
    dialog.closeEvent(second_event)

    assert second_event.isAccepted()
    assert cancelled == [True]
    assert not dialog.isVisible()

    dialog.set_finished()
    assert dialog.action_button.text() == "Close"
    dialog.accept()
    dialog.deleteLater()


def test_measurement_optimization_setup_dialog_returns_adjusted_values(app) -> None:
    dialog = MeasurementOptimizationSetupDialog(_settings(), "02C", 7)

    dialog._parameter_inputs["pre_roll"].setValue(0.35)
    dialog._parameter_inputs["measurement_wait"].setValue(0.45)
    dialog._parameter_pins["pre_roll"].setChecked(True)
    dialog._parameter_pins["measurement_wait"].setChecked(True)
    dialog.stability_runs.setValue(5)
    dialog.termination_tolerance.setValue(7.5)
    dialog.stability_tolerance.setValue(0.5)

    settings = dialog.settings()

    assert dialog.run_button.text() == "Run"
    assert dialog.optimization_preset_hint.text() == (
        "Optimization will use preset 02C (preset number 7). Before running it, "
        "make sure the matching measurement preset or setlist is already loaded "
        'on the device. You can save one from the main window toolbar with "Save '
        'Measurement File".'
    )
    assert settings.pre_roll == 0.35
    assert settings.measurement_wait == 0.45
    assert settings.pinned_parameters == ("pre_roll", "measurement_wait")
    assert settings.stability_runs == 5
    assert settings.termination_tolerance == 7.5
    assert settings.stability_tolerance == 0.5

    dialog.deleteLater()


def test_measurement_optimization_setup_dialog_explains_configurable_widgets(app) -> None:
    dialog = MeasurementOptimizationSetupDialog(_settings(), "02C", 7)

    for parameter in TIMING_PARAMETERS:
        label = dialog._parameter_labels[parameter.name]
        input_widget = dialog._parameter_inputs[parameter.name]
        pin_widget = dialog._parameter_pins[parameter.name]

        assert label.toolTip()
        assert input_widget.toolTip() == label.toolTip()
        assert input_widget.lineEdit().toolTip() == label.toolTip()
        assert "not optimized or bisected" in pin_widget.toolTip()

    assert "repeat measurements" in dialog.stability_runs.toolTip()
    assert dialog.stability_runs_label.toolTip() == dialog.stability_runs.toolTip()
    assert "bisection search" in dialog.termination_tolerance.toolTip()
    assert dialog.termination_tolerance_label.toolTip() == dialog.termination_tolerance.toolTip()
    assert "measurement variation" in dialog.stability_tolerance.toolTip()
    assert dialog.stability_tolerance_label.toolTip() == dialog.stability_tolerance.toolTip()
    assert "connected device" in dialog.optimization_preset_hint.toolTip()
    assert "Start the parameter study" in dialog.run_button.toolTip()
    assert "without starting" in dialog.cancel_button.toolTip()

    dialog.deleteLater()


def test_measurement_optimization_setup_dialog_return_focuses_next_parameter_input(
    app,
) -> None:
    dialog = MeasurementOptimizationSetupDialog(_settings(), "02C", 7)
    dialog.show()
    app.processEvents()

    editor = dialog._parameter_inputs["pre_roll"].lineEdit()
    editor.setFocus()
    QTest.keyClick(editor, Qt.Key.Key_Return)
    app.processEvents()

    next_editor = dialog._parameter_inputs["post_roll"].lineEdit()
    assert next_editor.hasFocus()
    assert next_editor.selectedText()
    assert dialog.isVisible()
    assert dialog.result() != QDialog.DialogCode.Accepted

    dialog.close()
    dialog.deleteLater()


def test_determine_optimal_parameters_button_tracks_loaded_file_and_workers(app) -> None:
    window = MainWindow()
    window.input_path.setText("/tmp/input.hls")
    window._loaded_input_path = window.input_path.text()
    window.preset_table.insertRow(0)
    selected = QTableWidgetItem()
    selected.setCheckState(Qt.CheckState.Checked)
    window.preset_table.setItem(0, 0, selected)
    window.preset_table.setItem(0, 1, QTableWidgetItem("01A"))
    window.preset_table.setItem(0, 2, QTableWidgetItem("Example"))
    window.preset_table_controller.set_snapshot_names(0, ("Clean",))

    window._refresh_file_actions()

    assert window.determine_parameters_button.isEnabled()
    assert window.determine_parameters_hint.isHidden()

    selected.setCheckState(Qt.CheckState.Unchecked)
    window._refresh_file_actions()

    assert not window.determine_parameters_button.isEnabled()
    assert "Select at least one preset" in window.determine_parameters_hint.text()

    selected.setCheckState(Qt.CheckState.Checked)
    window._refresh_file_actions()

    window.optimization_worker = object()
    window._refresh_file_actions()

    assert not window.determine_parameters_button.isEnabled()
    assert "current operation" in window.determine_parameters_hint.text()

    window.optimization_worker = None
    window.hardware_check_worker = object()
    window._refresh_file_actions()

    assert not window.determine_parameters_button.isEnabled()
    assert "current operation" in window.determine_parameters_hint.text()

    window.hardware_check_worker = None
    window._loaded_input_path = ""
    window._refresh_file_actions()

    assert not window.determine_parameters_button.isEnabled()
    assert "Open a Helix file" in window.determine_parameters_hint.text()

    window.close()


def test_main_window_applies_optimized_timing_parameters(monkeypatch, app) -> None:
    window = MainWindow()
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args))

    window._apply_measurement_optimization_result(
        "[analysis]\n"
        "pre_roll_seconds = 0.7\n"
        "post_roll_seconds = 0.8\n"
        "round_trip_latency_seconds = 0.09\n"
        "\n"
        "[devices.helix.steering]\n"
        "preset_wait_seconds = 1.1\n"
        "snapshot_wait_seconds = 1.2\n"
        "measurement_wait_seconds = 1.3\n"
    )

    assert window.pre_roll.text() == "0.7"
    assert window.post_roll.text() == "0.8"
    assert window.round_trip_latency.text() == "0.09"
    assert window.preset_wait.text() == "1.1"
    assert window.snapshot_wait.text() == "1.2"
    assert window.measurement_wait.text() == "1.3"
    assert messages

    window.close()


def test_determine_optimal_parameters_passes_stability_tolerance(monkeypatch, app) -> None:
    window = MainWindow()
    captured = {}

    class Signal:
        def connect(self, callback) -> None:
            return None

    class Worker:
        def __init__(
            self,
            request,
            preset_id,
            stability_runs,
            termination_tolerance,
            stability_tolerance,
            pinned_parameters=(),
            parent=None,
        ) -> None:
            captured["request"] = request
            captured["preset_id"] = preset_id
            captured["stability_runs"] = stability_runs
            captured["termination_tolerance"] = termination_tolerance
            captured["stability_tolerance"] = stability_tolerance
            captured["pinned_parameters"] = pinned_parameters
            captured["parent"] = parent
            self.progress = Signal()
            self.completed = Signal()
            self.cancelled = Signal()
            self.failed = Signal()
            self.finished = Signal()

        def start(self) -> None:
            captured["started"] = True

        def deleteLater(self) -> None:
            return None

        def cancel(self) -> None:
            captured["cancelled"] = True

        def wait(self) -> None:
            captured["waited"] = True

    request = _request()
    monkeypatch.setattr(main_window, "MeasurementOptimizationWorker", Worker)
    monkeypatch.setattr(window, "_validate_single_preset_slot_for_run", lambda: True)
    monkeypatch.setattr(advanced_settings, "parse_args", lambda argv: object())
    monkeypatch.setattr(advanced_settings, "apply_config", lambda args: args)
    monkeypatch.setattr(advanced_settings, "request_from_args", lambda args: request)
    monkeypatch.setattr(window, "_optimization_preset_id", lambda request: 7)
    monkeypatch.setattr(
        window,
        "_show_measurement_optimization_setup",
        lambda request, preset_id: MeasurementOptimizationSettings(
            pre_roll=0.3,
            post_roll=0.4,
            round_trip_latency=0.05,
            preset_wait=0.6,
            snapshot_wait=0.7,
            measurement_wait=0.8,
            stability_runs=4,
            termination_tolerance=12.5,
            stability_tolerance=0.25,
            pinned_parameters=("pre_roll", "measurement_wait"),
        ),
    )
    window.determine_optimal_parameters()

    assert captured["request"].device == request.device
    assert captured["request"].defer_export
    assert captured["request"].pre_roll == 0.3
    assert captured["request"].post_roll == 0.4
    assert captured["request"].round_trip_latency == 0.05
    assert captured["request"].preset_wait == 0.6
    assert captured["request"].snapshot_wait == 0.7
    assert captured["request"].measurement_wait == 0.8
    assert captured["preset_id"] == 7
    assert captured["stability_runs"] == 4
    assert captured["termination_tolerance"] == 12.5
    assert captured["stability_tolerance"] == 0.25
    assert captured["pinned_parameters"] == ("pre_roll", "measurement_wait")
    assert captured["parent"] is window
    assert captured["started"]

    window.close()


def test_first_hardware_optimization_checks_backend_once(monkeypatch, app) -> None:
    window = MainWindow()
    request = _request(backend="hardware")
    checks = []
    captured = {}

    class Signal:
        def connect(self, callback) -> None:
            return None

    class Worker:
        def __init__(
            self,
            request,
            preset_id,
            stability_runs,
            termination_tolerance,
            stability_tolerance,
            pinned_parameters=(),
            parent=None,
        ) -> None:
            captured["request"] = request
            captured["preset_id"] = preset_id
            captured["pinned_parameters"] = pinned_parameters
            self.progress = Signal()
            self.completed = Signal()
            self.cancelled = Signal()
            self.failed = Signal()
            self.finished = Signal()

        def start(self) -> None:
            captured["started"] = True

        def deleteLater(self) -> None:
            return None

        def cancel(self) -> None:
            captured["cancelled"] = True

        def wait(self) -> None:
            captured["waited"] = True

    monkeypatch.setattr(window, "_backend_check_enabled", lambda: True)
    monkeypatch.setattr(window, "_validate_single_preset_slot_for_run", lambda: True)
    monkeypatch.setattr(advanced_settings, "parse_args", lambda argv: object())
    monkeypatch.setattr(advanced_settings, "apply_config", lambda args: args)
    monkeypatch.setattr(advanced_settings, "request_from_args", lambda args: request)
    monkeypatch.setattr(window, "_optimization_preset_id", lambda request: 7)
    monkeypatch.setattr(main_window, "MeasurementOptimizationWorker", Worker)
    monkeypatch.setattr(
        window,
        "_show_measurement_optimization_setup",
        lambda request, preset_id: MeasurementOptimizationSettings(
            pre_roll=0.3,
            post_roll=0.4,
            round_trip_latency=0.05,
            preset_wait=0.6,
            snapshot_wait=0.7,
            measurement_wait=0.8,
            stability_runs=4,
            termination_tolerance=12.5,
            stability_tolerance=0.25,
            pinned_parameters=("measurement_wait",),
        ),
    )
    monkeypatch.setattr(
        gui_worker,
        "collect_windows_hardware_diagnostics",
        lambda checked_request: (
            checks.append(checked_request)
            or [DiagnosticCheck("windows_hardware_check", "pass", "ok")]
        ),
    )

    window.determine_optimal_parameters()

    for _ in range(100):
        app.processEvents()
        if captured.get("started") and window.hardware_check_worker is None:
            break
        time.sleep(0.01)

    assert len(checks) == 1
    assert checks[0].backend == "hardware"
    assert captured["request"].backend == "hardware"
    assert captured["request"].defer_export
    assert captured["request"].measurement_wait == 0.8
    assert captured["preset_id"] == 7
    assert captured["pinned_parameters"] == ("measurement_wait",)
    assert captured["started"]
    assert window.hardware_check_overlay.isHidden()

    window.close()


def test_failed_hardware_optimization_restores_parameter_setup(monkeypatch, app) -> None:
    window = MainWindow()
    request = _request(backend="hardware")
    checks = []
    popups = []
    dialogs = []
    adjusted_settings = MeasurementOptimizationSettings(
        pre_roll=0.3,
        post_roll=0.4,
        round_trip_latency=0.05,
        preset_wait=0.6,
        snapshot_wait=0.7,
        measurement_wait=0.8,
        stability_runs=4,
        termination_tolerance=12.5,
        stability_tolerance=0.25,
        pinned_parameters=("pre_roll", "measurement_wait"),
    )

    class SetupDialog:
        def __init__(self, settings, preset_label, preset_id, parent=None) -> None:
            self.initial_settings = settings
            self.preset_label = preset_label
            self.preset_id = preset_id
            self.parent = parent
            dialogs.append(self)

        def exec(self):
            if len(dialogs) == 1:
                return QDialog.DialogCode.Accepted
            return QDialog.DialogCode.Rejected

        def settings(self):
            return adjusted_settings

    monkeypatch.setattr(window, "_backend_check_enabled", lambda: True)
    monkeypatch.setattr(window, "_validate_single_preset_slot_for_run", lambda: True)
    monkeypatch.setattr(advanced_settings, "parse_args", lambda argv: object())
    monkeypatch.setattr(advanced_settings, "apply_config", lambda args: args)
    monkeypatch.setattr(advanced_settings, "request_from_args", lambda args: request)
    monkeypatch.setattr(window, "_optimization_preset_id", lambda request: 7)
    monkeypatch.setattr(main_window, "MeasurementOptimizationSetupDialog", SetupDialog)
    monkeypatch.setattr(
        gui_worker,
        "collect_windows_hardware_diagnostics",
        lambda checked_request: (
            checks.append(checked_request)
            or [
                DiagnosticCheck(
                    "audio_device",
                    "fail",
                    "No audio device matched",
                    "audio_device=Helix",
                )
            ]
        ),
    )
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: popups.append(args))
    monkeypatch.setattr(
        main_window.MeasurementOptimizationWorker,
        "start",
        lambda self: (_ for _ in ()).throw(AssertionError("unexpected optimization")),
    )

    window.determine_optimal_parameters()

    for _ in range(100):
        app.processEvents()
        if len(dialogs) == 2 and window.hardware_check_worker is None:
            break
        time.sleep(0.01)

    assert len(checks) == 1
    assert len(popups) == 1
    assert len(dialogs) == 2
    assert dialogs[1].initial_settings == adjusted_settings
    assert dialogs[1].preset_id == 7
    assert window.optimization_worker is None
    assert window.hardware_check_worker is None
    assert window.hardware_check_overlay.isHidden()

    window.close()


def test_consecutive_optimization_reuses_previous_start_parameters(monkeypatch, app) -> None:
    window = MainWindow()
    request = _request()
    previous_settings = MeasurementOptimizationSettings(
        pre_roll=0.33,
        post_roll=0.44,
        round_trip_latency=0.055,
        preset_wait=0.66,
        snapshot_wait=0.77,
        measurement_wait=0.88,
        stability_runs=5,
        termination_tolerance=7.5,
        stability_tolerance=0.25,
        pinned_parameters=("pre_roll",),
    )
    captured = {}

    class SetupDialog:
        def __init__(self, settings, preset_label, preset_id, parent=None) -> None:
            captured["settings"] = settings
            captured["preset_label"] = preset_label
            captured["preset_id"] = preset_id
            captured["parent"] = parent

        def exec(self):
            return QDialog.DialogCode.Accepted

        def settings(self):
            return previous_settings

    window._last_measurement_optimization_settings = previous_settings
    monkeypatch.setattr(main_window, "MeasurementOptimizationSetupDialog", SetupDialog)

    settings = window._show_measurement_optimization_setup(request, 7)

    assert captured["settings"] == previous_settings
    assert captured["preset_label"] == "02C"
    assert captured["preset_id"] == 7
    assert captured["parent"] is window
    assert settings == previous_settings

    window.close()


def test_cancelled_modified_optimization_setup_is_reused_next_time(monkeypatch, app) -> None:
    window = MainWindow()
    request = _request()
    modified_settings = MeasurementOptimizationSettings(
        pre_roll=0.31,
        post_roll=0.41,
        round_trip_latency=0.051,
        preset_wait=0.61,
        snapshot_wait=0.71,
        measurement_wait=0.81,
        stability_runs=4,
        termination_tolerance=9.5,
        stability_tolerance=0.75,
        pinned_parameters=("pre_roll", "measurement_wait"),
    )
    captured = []

    class SetupDialog:
        def __init__(self, settings, preset_label, preset_id, parent=None) -> None:
            captured.append(settings)

        def exec(self):
            if len(captured) == 1:
                return QDialog.DialogCode.Rejected
            return QDialog.DialogCode.Accepted

        def settings(self):
            return modified_settings

    monkeypatch.setattr(main_window, "MeasurementOptimizationSetupDialog", SetupDialog)

    assert window._show_measurement_optimization_setup(request, 7) is None
    settings = window._show_measurement_optimization_setup(request, 7)

    assert window._last_measurement_optimization_settings == modified_settings
    assert captured[1] == modified_settings
    assert settings == modified_settings

    window.close()


def test_determine_optimal_parameters_cancel_setup_aborts(monkeypatch, app) -> None:
    window = MainWindow()
    request = _request(backend="hardware")
    checks = []

    monkeypatch.setattr(window, "_backend_check_enabled", lambda: True)
    monkeypatch.setattr(window, "_validate_single_preset_slot_for_run", lambda: True)
    monkeypatch.setattr(advanced_settings, "parse_args", lambda argv: object())
    monkeypatch.setattr(advanced_settings, "apply_config", lambda args: args)
    monkeypatch.setattr(advanced_settings, "request_from_args", lambda args: request)
    monkeypatch.setattr(window, "_optimization_preset_id", lambda request: 7)
    monkeypatch.setattr(
        window, "_show_measurement_optimization_setup", lambda request, preset_id: None
    )
    monkeypatch.setattr(
        gui_worker,
        "collect_windows_hardware_diagnostics",
        lambda checked_request: (
            checks.append(checked_request)
            or [DiagnosticCheck("windows_hardware_check", "pass", "ok")]
        ),
    )

    window.determine_optimal_parameters()

    assert checks == []
    assert window.hardware_check_worker is None
    assert window.optimization_worker is None

    window.close()
