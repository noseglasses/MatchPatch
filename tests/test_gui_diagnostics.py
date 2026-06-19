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
    GuiSettingsBinder,
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
    preset_table_selection_preflight_checks,
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


def test_preflight_formatting_uses_display_names_and_escapes_html() -> None:
    checks = [
        DiagnosticCheck("request", "pass", "Request ok"),
        DiagnosticCheck("hardware", "skip", "Hardware skipped"),
        DiagnosticCheck(
            "snapshot_plan",
            "skip",
            "No per-snapshot selection configured; selected presets use all measurable snapshots",
        ),
        DiagnosticCheck(
            "audio_device",
            "fail",
            "Audio failed",
            "<unsafe detail>",
        ),
    ]

    text = format_preflight_results(checks)
    html = format_preflight_results_html(checks)

    assert "SKIP Per-snapshot selection" in text
    assert "#15803d" in html
    assert "#854d0e" in html
    assert "#dc2626" in html
    assert "Per-snapshot selection" in html
    assert "snapshot_plan" not in html
    assert "snapshot plan" not in html.lower()
    assert "&lt;unsafe detail&gt;" in html
    assert "<unsafe detail>" not in html


def test_preflight_headline_reflects_highest_status() -> None:
    assert preflight_headline([DiagnosticCheck("request", "pass", "ok")]) == "Preflight passed."
    assert (
        preflight_headline([DiagnosticCheck("request", "warning", "risky")])
        == "Preflight completed with warnings."
    )
    assert (
        preflight_headline([DiagnosticCheck("request", "fail", "broken")])
        == "Preflight found setup problems."
    )


@dataclass(frozen=True)
class _ProgressPlan:
    preset_snapshots: tuple[tuple[str, tuple[int, ...]], ...]


def test_preset_table_selection_preflight_checks_use_context_without_window() -> None:
    checks = preset_table_selection_preflight_checks(
        PresetTableSelectionContext(
            has_table=True,
            row_count=2,
            visible_rows={0, 1},
            checked_rows={0, 1},
            has_ignored_snapshots=False,
            comparison_snapshot_plan={"01A": (0, 2), "01B": (1,)},
            input_path="/tmp/input.hls",
            patch_at_row=lambda row: ("01A", "01B")[row],
            row_measured_snapshot_indexes=lambda row: ((0,), ())[row],
            measurement_progress_plan_for_request=lambda _request: None,
            progress_plan_factory=_ProgressPlan,
        )
    )

    assert checks == [
        DiagnosticCheck(
            "preset_set",
            "pass",
            "Preset selection includes 2 preset(s): 01A, 01B",
        ),
        DiagnosticCheck(
            "snapshot_plan",
            "pass",
            "Per-snapshot selection includes 1 preset(s) and 1 snapshot(s)",
        ),
    ]


def test_diagnostics_panel_buttons_emit_requests_and_track_workflow(app) -> None:
    panel = DiagnosticsPanel(log_widget=QTextEdit())
    emitted: list[str] = []
    panel.preflight_requested.connect(lambda: emitted.append("preflight"))
    panel.copy_summary_requested.connect(lambda: emitted.append("copy"))
    panel.export_bundle_requested.connect(lambda: emitted.append("export"))

    panel.preflight_button.click()
    panel.copy_summary_button.click()
    panel.export_bundle_button.click()

    assert emitted == ["preflight", "copy", "export"]

    panel.set_workflow_active(True)
    assert not panel.preflight_button.isEnabled()
    assert not panel.copy_summary_button.isEnabled()
    assert not panel.export_bundle_button.isEnabled()

    panel.set_preflight_running(False)
    assert panel.preflight_button.text() == "Run preflight check"
    assert panel.preflight_button.isEnabled()
    assert panel.copy_summary_button.isEnabled()
    assert panel.export_bundle_button.isEnabled()


def test_hardware_check_details_format_request_and_failed_checks() -> None:
    request = NormalizationRequest(
        device="helix",
        input_path="input.hls",
        backend="hardware",
        windows_python="python.exe",
        reference_di="reference.wav",
        automation=False,
        audio_device="Interface",
        sample_rate=48000,
        input_mapping=(1, 2),
        output_mapping=(3, 4),
        steering_output="Helix MIDI",
    )
    checks = [
        DiagnosticCheck("audio_device", "pass", "Audio ok"),
        DiagnosticCheck("midi_output", "fail", "MIDI missing", "No MIDI output"),
    ]

    details = format_hardware_check_request_details(request)

    assert "backend=hardware" in details
    assert "audio_device=Interface" in details
    assert "midi_output=Helix MIDI" in details
    assert hardware_check_failure_details(checks, "fallback") == "No MIDI output"
    assert hardware_check_failure_details([], "fallback") == "fallback"


def test_diagnostic_bundle_action_is_available_in_diagnostics_tab(app) -> None:
    window = MainWindow()

    assert window.preflight_button.text() == "Run preflight check"
    assert window.diagnostic_summary_button.text() == "Copy diagnostic summary"
    assert window.diagnostic_bundle_button.text() == "Export diagnostic bundle"
    diagnostics_tab = window.advanced_tabs.widget(7)
    assert window.advanced_tabs.tabText(7) == "Diagnostics"
    assert diagnostics_tab.isAncestorOf(window.preflight_button)
    assert diagnostics_tab.isAncestorOf(window.diagnostic_summary_button)
    assert diagnostics_tab.isAncestorOf(window.diagnostic_bundle_button)
    assert diagnostics_tab.isAncestorOf(window.log)

    window.close()


def test_current_diagnostic_request_uses_settings_boundary(tmp_path, monkeypatch, app) -> None:
    window = MainWindow()
    config_path = tmp_path / "matchpatch.toml"
    window.input_path.setText(str(tmp_path / "input.hls"))
    window.config_path.setText(str(config_path))
    captured = {}
    request = _request(input_path=tmp_path / "input.hls")

    def diagnostic_request(settings, context, *, completed_request=None):
        captured["settings"] = settings
        captured["context"] = context
        captured["completed_request"] = completed_request
        return request

    monkeypatch.setattr(main_window, "diagnostic_request", diagnostic_request)

    assert window._current_diagnostic_request() is request
    assert captured["settings"] == GuiSettingsBinder.from_widgets(window)
    assert captured["context"].input_path == str(tmp_path / "input.hls")
    assert captured["completed_request"] is None

    window.close()


def test_copy_diagnostic_summary_uses_effective_config_and_clipboard(
    tmp_path, monkeypatch, app
) -> None:
    window = MainWindow()
    config_path = tmp_path / "matchpatch.toml"
    request = _request(
        input_path=tmp_path / "input.hls",
        reference_di=tmp_path / "reference.wav",
        target_lufs=-17.25,
        backend="loopback",
    )
    window.config_path.setText(str(config_path))
    monkeypatch.setattr(advanced_settings, "apply_config", lambda args: args)
    monkeypatch.setattr(advanced_settings, "request_from_args", lambda args: request)
    app.clipboard().clear()

    window.copy_diagnostic_summary()

    summary = app.clipboard().text()
    assert f"Config: {config_path}" in summary
    assert f"Input: {request.input_path}" in summary
    assert f"Reference DI: {request.reference_di}" in summary
    assert "Backend: loopback" in summary
    assert "Target LUFS: -17.25" in summary
    assert any("Diagnostic summary copied" in entry[2] for entry in window.log_entries)

    window.close()


def test_copy_diagnostic_summary_reports_invalid_request(monkeypatch, app) -> None:
    window = MainWindow()
    errors = []
    monkeypatch.setattr(advanced_settings, "apply_config", lambda args: args)
    monkeypatch.setattr(
        advanced_settings,
        "request_from_args",
        lambda args: (_ for _ in ()).throw(ValueError("bad config")),
    )
    monkeypatch.setattr(window, "show_error", lambda message: errors.append(message))

    window.copy_diagnostic_summary()

    assert errors == ["bad config"]
    assert not any("Diagnostic summary copied" in entry[2] for entry in window.log_entries)

    window.close()


def test_diagnostic_actions_disable_while_workflow_is_active(app) -> None:
    window = MainWindow()

    window.worker = object()
    window._refresh_file_actions()

    assert not window.preflight_button.isEnabled()
    assert not window.diagnostic_summary_button.isEnabled()
    assert not window.diagnostic_bundle_button.isEnabled()

    window.worker = None
    window._refresh_file_actions()

    assert window.preflight_button.isEnabled()
    assert window.diagnostic_summary_button.isEnabled()
    assert window.diagnostic_bundle_button.isEnabled()

    window.close()


def test_preflight_action_starts_worker_without_starting_normalization(
    tmp_path, monkeypatch, app
) -> None:
    window = MainWindow()
    request = _request(input_path=tmp_path / "input.hls")
    _FakePreflightWorker.instances = []
    monkeypatch.setattr(advanced_settings, "apply_config", lambda args: args)
    monkeypatch.setattr(advanced_settings, "request_from_args", lambda args: request)
    monkeypatch.setattr(main_window, "PreflightWorker", _FakePreflightWorker)

    window.run_preflight_check()

    assert len(_FakePreflightWorker.instances) == 1
    assert _FakePreflightWorker.instances[0].request is request
    assert _FakePreflightWorker.instances[0].started
    assert window.preflight_worker is _FakePreflightWorker.instances[0]
    assert window.worker is None
    assert window.phase.text() == "Running pre flight checks..."
    assert not window.phase_icon.pixmap().isNull()
    assert not window.preflight_overlay.isHidden()
    assert window.preflight_overlay.spinner.minimum() == 0
    assert window.preflight_overlay.spinner.maximum() == 0

    window._preflight_finished()

    assert window.preflight_overlay.isHidden()

    window.preflight_worker = None
    window.close()


def test_preflight_request_includes_measurable_snapshot_plan(tmp_path, monkeypatch, app) -> None:
    window = MainWindow()
    request = _request(input_path=tmp_path / "input.hls", preset_set="02B,02C")
    _FakePreflightWorker.instances = []
    monkeypatch.setattr(advanced_settings, "apply_config", lambda args: args)
    monkeypatch.setattr(advanced_settings, "request_from_args", lambda args: request)
    monkeypatch.setattr(main_window, "PreflightWorker", _FakePreflightWorker)
    window.snapshot_count_input.setValue(3)
    for row, preset_id in enumerate(("02B", "02C")):
        window.preset_table.insertRow(row)
        selected = QTableWidgetItem()
        selected.setCheckState(Qt.CheckState.Checked)
        window.preset_table.setItem(row, 0, selected)
        window.preset_table.setItem(row, 1, QTableWidgetItem(preset_id))
        window.preset_table.setItem(row, 2, QTableWidgetItem("Song"))
        window.preset_table_controller.clear_preset_adjustments(row)

    window.preset_table_controller.set_ignored_snapshot_highlight(0, 1, True)
    window.preset_table_controller.set_ignored_snapshot_highlight(1, 0, True)
    window.preset_table_controller.set_ignored_snapshot_highlight(1, 2, True)

    window.run_preflight_check()

    assert len(_FakePreflightWorker.instances) == 1
    assert _FakePreflightWorker.instances[0].request.snapshot_plan == (
        ("02B", (1, 3)),
        ("02C", (2,)),
    )

    window.preflight_worker = None
    window.close()


def test_preflight_request_overlays_table_selection_when_args_have_no_selection(
    tmp_path, monkeypatch, app
) -> None:
    window = MainWindow()
    request = _request(input_path=tmp_path / "input.hls")
    _FakePreflightWorker.instances = []
    monkeypatch.setattr(advanced_settings, "apply_config", lambda args: args)
    monkeypatch.setattr(advanced_settings, "request_from_args", lambda args: request)
    monkeypatch.setattr(main_window, "PreflightWorker", _FakePreflightWorker)
    window.snapshot_count_input.setValue(3)
    for row, preset_id in enumerate(("02A", "02B", "02C")):
        window.preset_table.insertRow(row)
        selected = QTableWidgetItem()
        selected.setCheckState(
            Qt.CheckState.Unchecked if preset_id == "02A" else Qt.CheckState.Checked
        )
        window.preset_table.setItem(row, 0, selected)
        window.preset_table.setItem(row, 1, QTableWidgetItem(preset_id))
        window.preset_table.setItem(row, 2, QTableWidgetItem("Song"))
        window.preset_table_controller.clear_preset_adjustments(row)

    window.preset_table_controller.set_snapshot_ignore_reason(1, 0, IGNORE_REASON_COMPARISON, True)
    window.preset_table_controller.set_snapshot_ignore_reason(1, 2, IGNORE_REASON_COMPARISON, True)
    window.preset_table_controller.set_snapshot_ignore_reason(2, 0, IGNORE_REASON_COMPARISON, True)
    window.preset_table_controller.set_snapshot_ignore_reason(2, 1, IGNORE_REASON_COMPARISON, True)
    window.preset_table_controller.set_snapshot_ignore_reason(2, 2, IGNORE_REASON_COMPARISON, True)

    window.run_preflight_check()

    assert len(_FakePreflightWorker.instances) == 1
    assert _FakePreflightWorker.instances[0].request.preset_set == "02B,02C"
    assert _FakePreflightWorker.instances[0].request.snapshot_plan == (("02B", (2,)),)

    window.preflight_worker = None
    window.close()


def test_preflight_completed_replaces_stale_selection_skips_from_table_state(app) -> None:
    window = MainWindow()
    shown = []
    window.snapshot_count_input.setValue(3)
    for row, preset_id in enumerate(("02A", "02B", "02C")):
        window.preset_table.insertRow(row)
        selected = QTableWidgetItem()
        selected.setCheckState(
            Qt.CheckState.Unchecked if preset_id == "02A" else Qt.CheckState.Checked
        )
        window.preset_table.setItem(row, 0, selected)
        window.preset_table.setItem(row, 1, QTableWidgetItem(preset_id))
        window.preset_table.setItem(row, 2, QTableWidgetItem("Song"))
        window.preset_table_controller.clear_preset_adjustments(row)
    window.preset_table_controller.set_snapshot_ignore_reason(1, 0, IGNORE_REASON_COMPARISON, True)
    window.preset_table_controller.set_snapshot_ignore_reason(1, 2, IGNORE_REASON_COMPARISON, True)
    window.preset_table_controller.set_snapshot_ignore_reason(2, 0, IGNORE_REASON_COMPARISON, True)
    window.preset_table_controller.set_snapshot_ignore_reason(2, 1, IGNORE_REASON_COMPARISON, True)
    window.preset_table_controller.set_snapshot_ignore_reason(2, 2, IGNORE_REASON_COMPARISON, True)
    window._show_preflight_results = lambda checks: shown.append(checks)

    window._preflight_completed(
        [
            DiagnosticCheck("request", "pass", "Request ok"),
            DiagnosticCheck(
                "preset_set",
                "skip",
                "No preset selection configured; all presets are eligible",
            ),
            DiagnosticCheck(
                "snapshot_plan",
                "skip",
                "No per-snapshot selection configured; selected presets use all measurable snapshots",
            ),
        ]
    )

    assert shown
    by_name = {check.name: check for check in shown[0]}
    assert by_name["preset_set"].status == "pass"
    assert by_name["preset_set"].summary == "Preset selection includes 2 preset(s): 02B, 02C"
    assert by_name["snapshot_plan"].status == "pass"
    assert by_name["snapshot_plan"].summary == (
        "Per-snapshot selection includes 1 preset(s) and 1 snapshot(s)"
    )

    window.close()


def test_preflight_completed_uses_enabled_comparison_plan_without_cell_flags(app) -> None:
    window = MainWindow()
    shown = []
    window.snapshot_count_input.setValue(3)
    for row, preset_id in enumerate(("02A", "02B", "02C")):
        window.preset_table.insertRow(row)
        selected = QTableWidgetItem()
        selected.setCheckState(
            Qt.CheckState.Unchecked if preset_id == "02A" else Qt.CheckState.Checked
        )
        window.preset_table.setItem(row, 0, selected)
        window.preset_table.setItem(row, 1, QTableWidgetItem(preset_id))
        window.preset_table.setItem(row, 2, QTableWidgetItem("Song"))
        window.preset_table_controller.clear_preset_adjustments(row)
    window._comparison_changed_by_patch = {"02B": (2,), "02C": ()}
    window.comparison_enabled.setEnabled(True)
    window.comparison_enabled.setChecked(True)
    window._show_preflight_results = lambda checks: shown.append(checks)

    window._preflight_completed(
        [
            DiagnosticCheck(
                "preset_set",
                "skip",
                "No preset selection configured; all presets are eligible",
            ),
            DiagnosticCheck(
                "snapshot_plan",
                "skip",
                "No per-snapshot selection configured; selected presets use all measurable snapshots",
            ),
        ]
    )

    by_name = {check.name: check for check in shown[0]}
    assert by_name["preset_set"].summary == "Preset selection includes 2 preset(s): 02B, 02C"
    assert by_name["snapshot_plan"].summary == (
        "Per-snapshot selection includes 1 preset(s) and 1 snapshot(s)"
    )

    window.close()


def test_preflight_completed_reports_configured_selection_with_zero_measurable_snapshots(
    app,
) -> None:
    window = MainWindow()
    shown = []
    window.snapshot_count_input.setValue(2)
    for row, preset_id in enumerate(("02A", "02B")):
        window.preset_table.insertRow(row)
        selected = QTableWidgetItem()
        selected.setCheckState(
            Qt.CheckState.Unchecked if preset_id == "02A" else Qt.CheckState.Checked
        )
        window.preset_table.setItem(row, 0, selected)
        window.preset_table.setItem(row, 1, QTableWidgetItem(preset_id))
        window.preset_table.setItem(row, 2, QTableWidgetItem("Song"))
        window.preset_table_controller.clear_preset_adjustments(row)
    window._comparison_changed_by_patch = {"02B": ()}
    window.comparison_enabled.setEnabled(True)
    window.comparison_enabled.setChecked(True)
    window._show_preflight_results = lambda checks: shown.append(checks)

    window._preflight_completed(
        [
            DiagnosticCheck(
                "preset_set",
                "skip",
                "No preset selection configured; all presets are eligible",
            ),
            DiagnosticCheck(
                "snapshot_plan",
                "skip",
                "No per-snapshot selection configured; selected presets use all measurable snapshots",
            ),
        ]
    )

    by_name = {check.name: check for check in shown[0]}
    assert by_name["preset_set"].summary == "Preset selection includes 1 preset(s): 02B"
    assert by_name["snapshot_plan"].status == "warning"
    assert by_name["snapshot_plan"].summary == (
        "Per-snapshot selection is configured but leaves no measurable snapshots "
        "across 1 selected preset(s)"
    )

    window.close()


def test_preflight_intersects_comparison_plan_with_current_ignored_cells(app) -> None:
    window = MainWindow()
    shown = []
    window.snapshot_count_input.setValue(2)
    for row, preset_id in enumerate(("02A", "02B")):
        window.preset_table.insertRow(row)
        selected = QTableWidgetItem()
        selected.setCheckState(Qt.CheckState.Checked)
        window.preset_table.setItem(row, 0, selected)
        window.preset_table.setItem(row, 1, QTableWidgetItem(preset_id))
        window.preset_table.setItem(row, 2, QTableWidgetItem("Song"))
        window.preset_table_controller.clear_preset_adjustments(row)
        window.preset_table_controller.set_snapshot_ignore_reason(
            row, 0, IGNORE_REASON_COMPARISON, True
        )
        window.preset_table_controller.set_snapshot_ignore_reason(
            row, 1, IGNORE_REASON_COMPARISON, True
        )
    window._comparison_changed_by_patch = {"02A": (1, 2), "02B": ()}
    window.comparison_enabled.setEnabled(True)
    window.comparison_enabled.setChecked(True)
    window.preset_table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    window._show_preflight_results = lambda checks: shown.append(checks)

    window._preflight_completed(
        [
            DiagnosticCheck(
                "preset_set",
                "skip",
                "No preset selection configured; all presets are eligible",
            ),
            DiagnosticCheck(
                "snapshot_plan",
                "skip",
                "No per-snapshot selection configured; selected presets use all measurable snapshots",
            ),
        ]
    )

    by_name = {check.name: check for check in shown[0]}
    assert by_name["preset_set"].summary == "Preset selection includes 1 preset(s): 02B"
    assert by_name["snapshot_plan"].status == "warning"
    assert by_name["snapshot_plan"].summary == (
        "Per-snapshot selection is configured but leaves no measurable snapshots "
        "across 1 selected preset(s)"
    )

    window.close()


def test_preflight_completed_checks_open_result_dialog(monkeypatch, app) -> None:
    window = MainWindow()
    checks = [DiagnosticCheck("input_file", "fail", "Missing input", "missing.hls")]
    shown = []
    monkeypatch.setattr(window, "_show_preflight_results", lambda checks: shown.append(checks))

    window._preflight_completed(checks)

    assert shown == [checks]
    assert any(
        "Preflight check completed with 1 failure" in entry[2] for entry in window.log_entries
    )

    window.close()


def test_preflight_result_markup_highlights_statuses() -> None:
    html = format_preflight_results_html(
        [
            DiagnosticCheck("request", "pass", "Request ok"),
            DiagnosticCheck("hardware", "skip", "Hardware skipped"),
            DiagnosticCheck(
                "snapshot_plan",
                "skip",
                "No per-snapshot selection configured; selected presets use all measurable snapshots",
            ),
            DiagnosticCheck(
                "audio_device",
                "fail",
                "Audio failed",
                "<unsafe detail>",
            ),
        ]
    )

    assert "#15803d" in html
    assert "#854d0e" in html
    assert "#dc2626" in html
    assert "Per-snapshot selection" in html
    assert "snapshot_plan" not in html
    assert "snapshot plan" not in html.lower()
    assert "&lt;unsafe detail&gt;" in html
    assert "<unsafe detail>" not in html


def test_preflight_failure_appears_in_dialog_and_log(monkeypatch, app) -> None:
    window = MainWindow()
    messages = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda parent, title, message: messages.append((title, message)),
    )

    window._preflight_failed("unexpected problem")

    assert messages == [("Preflight check", "Preflight check failed: unexpected problem")]
    assert any("unexpected problem" in entry[2] for entry in window.log_entries)

    window.close()


def test_preflight_controls_disable_while_worker_runs(tmp_path, monkeypatch, app) -> None:
    window = MainWindow()
    request = _request(input_path=tmp_path / "input.hls")
    _FakePreflightWorker.instances = []
    monkeypatch.setattr(advanced_settings, "apply_config", lambda args: args)
    monkeypatch.setattr(advanced_settings, "request_from_args", lambda args: request)
    monkeypatch.setattr(main_window, "PreflightWorker", _FakePreflightWorker)

    window.run_preflight_check()

    assert not window.preflight_button.isEnabled()
    assert not window.diagnostic_summary_button.isEnabled()
    assert not window.diagnostic_bundle_button.isEnabled()
    assert not window.start_button.isEnabled()

    window.preflight_worker = None
    window.close()


def test_diagnostic_bundle_export_cancel_stops_after_request_build(monkeypatch, app) -> None:
    window = MainWindow()
    request = _request()
    monkeypatch.setattr(advanced_settings, "apply_config", lambda args: args)
    monkeypatch.setattr(advanced_settings, "request_from_args", lambda args: request)
    monkeypatch.setattr(window, "_choose_diagnostic_bundle_path", lambda: None)
    writes = []
    monkeypatch.setattr(main_window, "write_diagnostic_bundle", lambda *args: writes.append(args))

    window.export_diagnostic_bundle()

    assert writes == []
    assert not any("Diagnostic bundle exported" in entry[2] for entry in window.log_entries)

    window.close()


def test_diagnostic_bundle_export_writes_gui_logs_config_and_retained_csv(
    tmp_path, monkeypatch, app
) -> None:
    window = MainWindow()
    destination = tmp_path / "diagnostics"
    config_path = tmp_path / "matchpatch.toml"
    csv_path = tmp_path / "lufs_analysis.csv"
    csv_path.write_text("Preset,DevicePatch,LUFS1\n1,01A,-16.0\n", encoding="utf-8")
    request = _request(
        input_path=tmp_path / "input.hls",
        reference_di=tmp_path / "reference.wav",
        target_lufs=-17.0,
    )
    window.config_path.setText(str(config_path))
    window.retained_csv.setText(str(csv_path))
    window._log("Visible diagnostic line", "info")
    monkeypatch.setattr(advanced_settings, "apply_config", lambda args: args)
    monkeypatch.setattr(advanced_settings, "request_from_args", lambda args: request)
    monkeypatch.setattr(window, "_choose_diagnostic_bundle_path", lambda: destination)

    window.export_diagnostic_bundle()

    bundle_path = tmp_path / "diagnostics.zip"
    assert bundle_path.exists()
    with zipfile.ZipFile(bundle_path) as archive:
        diagnostics = json.loads(archive.read("diagnostics.json"))
        gui_log = archive.read("gui-log.txt").decode("utf-8")
        csv_summary = json.loads(archive.read("retained-csv-summary.json"))

    assert diagnostics["config_path"] == str(config_path)
    assert diagnostics["effective_config"]["target_lufs"] == -17.0
    assert diagnostics["recent_gui_log_lines"][0]["message"] == "Visible diagnostic line"
    assert "Visible diagnostic line" in gui_log
    assert csv_summary["path"] == str(csv_path)
    assert csv_summary["device_patches"] == ["01A"]
    assert any(
        f"Diagnostic bundle exported: {bundle_path}" in entry[2] for entry in window.log_entries
    )

    window.close()


def test_recent_progress_events_are_retained_for_diagnostics(monkeypatch, app) -> None:
    window = MainWindow()
    event = ProgressEvent("snapshot_started", device_patch="02B", snapshot=2)
    monkeypatch.setattr(advanced_settings, "apply_config", lambda args: args)
    monkeypatch.setattr(advanced_settings, "request_from_args", lambda args: _request())

    window.update_progress(event)

    snapshot = window._current_diagnostic_snapshot()
    assert snapshot.recent_progress_events == [
        {
            "kind": "snapshot_started",
            "message": None,
            "phase": None,
            "preset_id": None,
            "device_patch": "02B",
            "preset_index": None,
            "preset_total": None,
            "snapshot": 2,
            "snapshot_total": None,
            "reference_lufs": None,
            "lufs": None,
            "crest_factor_db": None,
            "path": None,
        }
    ]

    window.close()


def test_recent_progress_events_keep_last_100(app) -> None:
    window = MainWindow()

    for index in range(105):
        window.update_progress(ProgressEvent("log", message=f"event-{index}"))

    assert len(window._recent_progress_events) == 100
    assert window._recent_progress_events[0].message == "event-5"
    assert window._recent_progress_events[-1].message == "event-104"

    window.close()


def test_recent_progress_events_clear_when_new_normalization_starts(monkeypatch, app) -> None:
    window = MainWindow()
    monkeypatch.setattr(main_window.NormalizationWorker, "start", lambda self: None)
    window.update_progress(ProgressEvent("log", message="previous failure context"))

    window._start_normalization_request(_request())

    assert list(window._recent_progress_events) == []

    window.worker_finished()
    window.close()


def test_diagnostic_bundle_export_includes_recent_progress_events(
    tmp_path, monkeypatch, app
) -> None:
    window = MainWindow()
    destination = tmp_path / "diagnostics.zip"
    monkeypatch.setattr(advanced_settings, "apply_config", lambda args: args)
    monkeypatch.setattr(advanced_settings, "request_from_args", lambda args: _request())
    monkeypatch.setattr(window, "_choose_diagnostic_bundle_path", lambda: destination)
    window.update_progress(
        ProgressEvent(
            "snapshot_failed",
            message="bad LUFS",
            device_patch="02B",
            snapshot=1,
            lufs=-16.5,
        )
    )

    window.export_diagnostic_bundle()

    with zipfile.ZipFile(destination) as archive:
        events = json.loads(archive.read("progress-events.json"))
        diagnostics = json.loads(archive.read("diagnostics.json"))

    assert events[0]["kind"] == "snapshot_failed"
    assert events[0]["device_patch"] == "02B"
    assert events[0]["lufs"] == -16.5
    assert diagnostics["recent_progress_events"] == events

    window.close()


def test_diagnostic_bundle_export_reports_write_errors(tmp_path, monkeypatch, app) -> None:
    window = MainWindow()
    errors = []
    monkeypatch.setattr(advanced_settings, "apply_config", lambda args: args)
    monkeypatch.setattr(advanced_settings, "request_from_args", lambda args: _request())
    monkeypatch.setattr(
        window, "_choose_diagnostic_bundle_path", lambda: tmp_path / "diagnostics.zip"
    )
    monkeypatch.setattr(
        main_window,
        "write_diagnostic_bundle",
        lambda *args: (_ for _ in ()).throw(OSError("disk full")),
    )
    monkeypatch.setattr(window, "show_error", lambda message: errors.append(message))

    window.export_diagnostic_bundle()

    assert errors == ["disk full"]

    window.close()


def test_diagnostic_bundle_export_can_cancel_overwrite(tmp_path, monkeypatch, app) -> None:
    window = MainWindow()
    existing = tmp_path / "diagnostics.zip"
    existing.write_text("old", encoding="utf-8")
    questions = []
    writes = []
    monkeypatch.setattr(advanced_settings, "apply_config", lambda args: args)
    monkeypatch.setattr(advanced_settings, "request_from_args", lambda args: _request())
    monkeypatch.setattr(window, "_choose_diagnostic_bundle_path", lambda: tmp_path / "diagnostics")
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args: questions.append(args) or QMessageBox.StandardButton.No,
    )
    monkeypatch.setattr(main_window, "write_diagnostic_bundle", lambda *args: writes.append(args))

    window.export_diagnostic_bundle()

    assert writes == []
    assert questions
    assert str(existing) in questions[0][2]
    assert existing.read_text(encoding="utf-8") == "old"

    window.close()
