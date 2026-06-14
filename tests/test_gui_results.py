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
from matchpatch.gui import icons, loudness_widgets, main_window, measurement_optimization, results
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
    IGNORED_SNAPSHOT_BACKGROUND,
    PROCESSED_SNAPSHOT_BACKGROUND,
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
from matchpatch.gui.table_roles import (
    ADJUSTMENT_VALUE_ROLE,
    BAD_LUFS_HIGHLIGHT_ROLE,
    IGNORE_REASON_COMPARISON,
)
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


def test_gain_log_parsing_distinguishes_changed_stable_bad_lufs_and_sync() -> None:
    changed = results.parse_gain_correction_log(
        "[GAIN] 02B Clean | 0.0 dB -> 1.5 dB (Delta: +1.5 dB)"
    )
    assert changed is not None
    assert changed.patch == "02B"
    assert changed.snapshot_label == "Clean"
    assert changed.kind == "changed"
    assert changed.before_db == 0.0
    assert changed.after_db == 1.5
    assert changed.delta_db == 1.5

    stable = results.parse_gain_correction_log(
        "[GAIN] 03C Solo (S) | stable at -4.0 dB (Delta: +0.0 dB)"
    )
    assert stable is not None
    assert stable.kind == "stable"
    assert stable.is_solo
    assert stable.snapshot_label == "Solo"

    bad = results.parse_gain_correction_log(
        "[GAIN] 04D Lead | measurement unavailable (Implausible output gain 21.2 dB)"
    )
    assert bad is not None
    assert bad.kind == "bad_lufs"
    assert bad.detail == "Implausible output gain 21.2 dB"

    assert results.gain_preset_sync_patch("[GAIN] 04D: synchronized preset state") == "04D"
    assert not results.is_gain_correction_log("[WARNING] unrelated")


def test_snapshot_measurement_display_applies_policy_custom_and_implausible_checks() -> None:
    policy = NormalizationPolicy(solo_gain_bump_db=3.0)
    display = results.snapshot_measurement_display(
        ProgressEvent("snapshot_completed", device_patch="06A", snapshot=2, lufs=-20.0),
        policy=policy,
        target_lufs=-16.0,
        output_levels=(0.0,),
        is_solo=True,
        is_ignored=False,
        custom_adjustment=-1.0,
    )

    assert display is not None
    assert display.status == "measured"
    assert display.snapshot_index == 1
    assert display.adjustment_value == 6.0
    assert display.display_adjustment == 7.0

    implausible = results.snapshot_measurement_display(
        ProgressEvent("snapshot_completed", device_patch="06A", snapshot=1, lufs=-20.0),
        policy=policy,
        target_lufs=-16.0,
        output_levels=(19.0,),
        is_solo=False,
        is_ignored=False,
        custom_adjustment=None,
    )
    assert implausible is not None
    assert implausible.status == "implausible"
    assert implausible.implausible_output_gain == 23.0
    assert implausible.display_adjustment == 4.0


def test_measurement_gain_delta_and_manual_target_formatting_are_pure() -> None:
    policy = NormalizationPolicy(
        crest_factor_reference_db=12.0,
        crest_factor_correction_ratio=0.5,
        max_crest_factor_correction_db=3.0,
    )

    assert (
        results.measurement_gain_delta(
            target_lufs=-16.0,
            lufs=-20.0,
            crest_factor_db=8.0,
            policy=policy,
        )
        == 2.0
    )
    assert results.implausible_snapshot_output_gain((19.0, -130.0), 4.0) == 23.0
    assert results.manual_adjustment_targets(
        [
            results.ManualAdjustmentSnapshot(
                patch="02B",
                preset="Song",
                snapshot_index=1,
                snapshot_name="Solo",
            )
        ]
    ) == ["02B Song: snapshot 2 (Solo)"]


def test_gain_log_updates_preset_correction_columns(monkeypatch, app) -> None:
    window = MainWindow()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)
    window.preset_table.insertRow(0)
    selected = QTableWidgetItem()
    selected.setCheckState(Qt.CheckState.Checked)
    window.preset_table.setItem(0, 0, selected)
    window.preset_table.setItem(0, 1, QTableWidgetItem("02B"))
    window.preset_table.setItem(0, 2, QTableWidgetItem("Song"))
    window.preset_table_controller.clear_preset_adjustments(0)

    window.update_progress(
        ProgressEvent("log", message="[GAIN] 02B Solo (S) | 0.0 dB -> 11.1 dB (Delta: +11.1 dB)")
    )
    window.update_progress(
        ProgressEvent("log", message="[GAIN] 02B Clean | stable at -1.0 dB (Delta: +0.0 dB)")
    )
    window.update_progress(
        ProgressEvent("log", message="[GAIN] 02B Rhythm | 0.0 dB -> -2.0 dB (Delta: -2.0 dB)")
    )
    window.update_progress(ProgressEvent("preset_completed", device_patch="02B"))

    assert window.preset_table.horizontalHeaderItem(3).text() == "1"
    assert window.preset_table.horizontalHeaderItem(4).text() == "Out (dB)"
    assert window.preset_table.horizontalHeaderItem(5).text() == "Δ (dB)"
    assert window.preset_table.item(0, 3).text() == "Solo"
    assert (
        window.preset_table.cellWidget(0, 3).text() == "Solo <span style='color: #f59e0b;'>★</span>"
    )
    assert window.preset_table.item(0, 3).toolTip() == "Solo snapshot"
    assert window.preset_table.item(0, 4).text() == "0.0"
    assert window.preset_table.item(0, 5).text() == "+11.1"
    assert window.preset_table.item(0, 6).text() == "Clean"
    assert window.preset_table.item(0, 7).text() == "-1.0"
    assert window.preset_table.item(0, 8).text() == "0"
    assert window.preset_table.item(0, 9).text() == "Rhythm"
    assert window.preset_table.item(0, 10).text() == "0.0"
    assert window.preset_table.item(0, 11).text() == "-2.0"
    assert window.preset_table.item(0, 5).foreground().style() == Qt.BrushStyle.NoBrush
    assert window.preset_table.item(0, 11).foreground().style() == Qt.BrushStyle.NoBrush
    assert window.preset_table.columnWidth(0) == window.style().pixelMetric(
        QStyle.PixelMetric.PM_IndicatorWidth
    ) + 2 * window.style().pixelMetric(QStyle.PixelMetric.PM_CheckBoxLabelSpacing)
    metrics = window.preset_table.fontMetrics()
    assert window.preset_table.columnWidth(4) == max(
        58,
        metrics.horizontalAdvance("-120.0") + 14,
        metrics.horizontalAdvance("20.0") + 14,
    )
    assert window.preset_table.columnWidth(5) == max(
        58,
        metrics.horizontalAdvance("-140.0") + 14,
        metrics.horizontalAdvance("+140.0") + 14,
    )
    assert window.preset_table.columnWidth(5) < (metrics.horizontalAdvance("+12.5 (+12.5)") + 18)
    assert (
        window.preset_table.horizontalHeader().sectionResizeMode(0) == QHeaderView.ResizeMode.Fixed
    )
    assert all(
        window.preset_table.horizontalHeader().sectionResizeMode(column)
        == QHeaderView.ResizeMode.Interactive
        for column in range(1, window.preset_table.columnCount())
    )

    window.close()


def test_gain_log_with_output_prefix_keeps_bad_lufs_on_matching_snapshot(monkeypatch, app) -> None:
    window = MainWindow()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)
    window.preset_table.insertRow(0)
    selected = QTableWidgetItem()
    selected.setCheckState(Qt.CheckState.Checked)
    window.preset_table.setItem(0, 0, selected)
    window.preset_table.setItem(0, 1, QTableWidgetItem("04B"))
    window.preset_table.setItem(0, 2, QTableWidgetItem("Sharp dressed M"))
    window.preset_table_controller.clear_preset_adjustments(0)
    window.preset_table_controller.set_snapshot_names(
        0, ("Intro", "Solo", "Solo Pitch", "Solo Pitch")
    )
    window.preset_table_controller.set_snapshot_output_levels(0, ((7.4,), (7.4,), (6.9,), (6.9,)))

    for message in [
        "[GAIN] 04B Intro | dsp1.outputA 7.4 dB -> 8.1 dB (Delta: +0.7 dB)",
        "[GAIN] 04B Solo (S) | dsp1.outputA 7.4 dB -> 8.1 dB (Delta: +0.7 dB)",
        (
            "[GAIN] 04B Solo Pitch (S) | measurement unavailable "
            "(Implausible output gain 30.6 dB for 04B Solo Pitch dsp1.outputA. "
            "This usually means the measurement recorded silence.)"
        ),
        (
            "[GAIN] 04B Solo Pitch (S) | measurement unavailable "
            "(Implausible output gain 30.6 dB for 04B Solo Pitch dsp1.outputA. "
            "This usually means the measurement recorded silence.)"
        ),
    ]:
        window.update_progress(ProgressEvent("log", message=message))
    window.update_progress(ProgressEvent("preset_completed", device_patch="04B"))

    assert window.preset_table.item(0, 5).text() == "+0.7"
    assert window.preset_table.item(0, 8).text() == "+0.7"
    assert window.preset_table.item(0, 11).text() == "+23.7 ⚠️"
    assert window.preset_table.item(0, 14).text() == "+23.7 ⚠️"
    assert (
        "Resulting output block level would be 30.6 dB" in window.preset_table.item(0, 11).toolTip()
    )

    window.close()


def test_single_preset_gain_log_updates_table_when_apply_log_uses_wrapped_slot(
    monkeypatch, app
) -> None:
    window = MainWindow()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)
    window.input_path.setText("/tmp/example.hlx")
    window.preset_table.setRowCount(1)
    selected = QTableWidgetItem()
    selected.setCheckState(Qt.CheckState.Checked)
    window.preset_table.setItem(0, 0, selected)
    window.preset_table.setItem(0, 1, QTableWidgetItem("12A"))
    window.preset_table.setItem(0, 2, QTableWidgetItem("Lead"))
    window.preset_table_controller.clear_preset_adjustments(0)

    window.update_progress(
        ProgressEvent("log", message="[GAIN] 01A Clean | 0.0 dB -> 2.5 dB (Delta: +2.5 dB)")
    )
    window.update_progress(ProgressEvent("preset_completed", device_patch="01A"))

    assert window.preset_table.item(0, 3).text() == "Clean"
    assert window.preset_table.item(0, 4).text() == "0.0"
    assert window.preset_table.item(0, 5).text() == "+2.5"
    assert window._table_adjustments().gain_deltas["12A"][0] == 2.5

    window.close()


def test_snapshot_completed_updates_adjustment_cells_immediately(monkeypatch, app) -> None:
    window = MainWindow()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)
    window.target_lufs.setText("-16.0")
    window.preset_table.insertRow(0)
    selected = QTableWidgetItem()
    selected.setCheckState(Qt.CheckState.Checked)
    window.preset_table.setItem(0, 0, selected)
    window.preset_table.setItem(0, 1, QTableWidgetItem("02B"))
    window.preset_table.setItem(0, 2, QTableWidgetItem("Song"))
    window.preset_table_controller.clear_preset_adjustments(0)
    window.preset_table_controller.set_snapshot_names(0, ("Clean", "Solo"))
    window._custom_adjustments = {"02B": {0: 1.0}}
    window.preset_table_controller.mark_selected_preset_adjustments_pending(0)

    window.update_progress(
        ProgressEvent(
            "snapshot_completed",
            device_patch="02B",
            snapshot=1,
            lufs=-18.0,
            crest_factor_db=12.0,
        )
    )
    window.update_progress(
        ProgressEvent(
            "snapshot_completed",
            device_patch="02B",
            snapshot=2,
            lufs=-17.0,
            crest_factor_db=12.0,
        )
    )

    assert window.preset_table.item(0, 5).text() == "+2 (+1)"
    assert window.preset_table.item(0, 5).data(ADJUSTMENT_VALUE_ROLE) == 3.0
    assert window.preset_table.item(0, 5).foreground().style() == Qt.BrushStyle.NoBrush
    assert window.preset_table.item(0, 8).text() == "+4"
    assert window.preset_table.item(0, 8).foreground().style() == Qt.BrushStyle.NoBrush
    assert not window.preset_table.item(0, 5).font().bold()
    assert not window.preset_table.item(0, 8).font().bold()

    window.close()


def test_snapshot_names_are_preloaded_and_bad_lufs_is_marked(monkeypatch, app) -> None:
    window = MainWindow()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)
    window.preset_table.insertRow(0)
    selected = QTableWidgetItem()
    selected.setCheckState(Qt.CheckState.Checked)
    window.preset_table.setItem(0, 0, selected)
    window.preset_table.setItem(0, 1, QTableWidgetItem("02B"))
    window.preset_table.setItem(0, 2, QTableWidgetItem("Song"))
    window.preset_table_controller.clear_preset_adjustments(0)
    window.preset_table_controller.set_snapshot_names(0, ("Clean", "Solo"))

    window.update_progress(ProgressEvent("log", message="[GAIN] 02B Clean | bad LUFS"))

    assert window.preset_table.item(0, 5).text() == "0"
    assert all(
        window.preset_table.item(0, column).background().style() == Qt.BrushStyle.NoBrush
        for column in range(window.preset_table.columnCount())
    )

    window.update_progress(ProgressEvent("preset_completed", device_patch="02B"))

    assert window.preset_table.item(0, 3).text() == "Clean"
    assert window.preset_table.item(0, 5).text() == "Measurement failed ⚠️"
    assert window.preset_table.item(0, 5).font().bold()
    assert window.preset_table.item(0, 5).font().pointSize() == max(app.font().pointSize(), 9)
    assert window.preset_table.item(0, 5).foreground().color().name() == "#b91c1c"
    assert (
        "cannot calculate a safe Line 6 Helix output block level"
        in window.preset_table.item(0, 5).toolTip()
    )
    assert window.preset_table.item(0, 6).text() == "Solo"
    assert (
        window.preset_table.cellWidget(0, 6).text() == "Solo <span style='color: #f59e0b;'>★</span>"
    )
    assert window.preset_table.item(0, 6).toolTip() == "Solo snapshot"
    assert all(
        window.preset_table.item(0, column).background().color().name() == "#fee2e2"
        for column in (1, 2, 3, 4, 5)
    )
    assert all(
        not window.preset_table.item(0, column).data(BAD_LUFS_HIGHLIGHT_ROLE)
        for column in (0, 6, 7, 8, 9, 10, 11, 12, 13, 14)
    )
    assert not window.preset_table.item(0, 6).data(BAD_LUFS_HIGHLIGHT_ROLE)

    window.close()


def test_snapshot_failure_replaces_pending_adjustment_immediately(monkeypatch, app) -> None:
    window = MainWindow()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)
    window.preset_table.insertRow(0)
    selected = QTableWidgetItem()
    selected.setCheckState(Qt.CheckState.Checked)
    window.preset_table.setItem(0, 0, selected)
    window.preset_table.setItem(0, 1, QTableWidgetItem("18D"))
    window.preset_table.setItem(0, 2, QTableWidgetItem("Song"))
    window.preset_table_controller.clear_preset_adjustments(0)
    window.preset_table_controller.mark_selected_preset_adjustments_pending(0)

    window.update_progress(
        ProgressEvent(
            "snapshot_failed",
            device_patch="18D",
            snapshot=4,
            message="Could not collect valid short-term LUFS values",
        )
    )

    adjustment = window.preset_table.item(0, 14)
    assert adjustment.text() == "Measurement failed ⚠️"
    assert adjustment.font().bold()
    assert adjustment.foreground().color().name() == "#b91c1c"
    assert "Could not collect valid short-term LUFS values" in adjustment.toolTip()
    assert all(
        window.preset_table.item(0, column).background().color().name() == "#fee2e2"
        for column in (1, 2, 12, 13, 14)
    )
    assert all(
        window.preset_table.item(0, column).background().style() == Qt.BrushStyle.NoBrush
        for column in (0, 3, 4, 5, 6, 7, 8, 9, 10, 11)
    )

    window.close()


def test_live_snapshot_completion_marks_processed_snapshot_cells_green(monkeypatch, app) -> None:
    window = MainWindow()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)
    window.preset_table.insertRow(0)
    selected = QTableWidgetItem()
    selected.setCheckState(Qt.CheckState.Checked)
    window.preset_table.setItem(0, 0, selected)
    window.preset_table.setItem(0, 1, QTableWidgetItem("18D"))
    window.preset_table.setItem(0, 2, QTableWidgetItem("Song"))
    window.preset_table_controller.clear_preset_adjustments(0)
    window.preset_table_controller.set_snapshot_names(0, ("Clean", "Skip"))
    window.preset_table_controller.set_ignored_snapshot_highlight(0, 1, True)

    window.update_progress(
        ProgressEvent(
            "snapshot_completed",
            device_patch="18D",
            snapshot=1,
            lufs=-20.0,
            crest_factor_db=12.0,
        )
    )
    window.update_progress(
        ProgressEvent(
            "snapshot_completed",
            device_patch="18D",
            snapshot=2,
            lufs=-20.0,
            crest_factor_db=12.0,
        )
    )

    assert all(
        window.preset_table.item(0, column).background().color() == PROCESSED_SNAPSHOT_BACKGROUND
        for column in (3, 4, 5)
    )
    assert all(
        window.preset_table.item(0, column).background().color() == IGNORED_SNAPSHOT_BACKGROUND
        for column in (6, 7, 8)
    )
    assert window.preset_table.item(0, 0).background().style() == Qt.BrushStyle.NoBrush
    assert window.preset_table.item(0, 1).background().style() == Qt.BrushStyle.NoBrush
    assert window.preset_table.item(0, 2).background().style() == Qt.BrushStyle.NoBrush

    window.preset_table_controller.clear_preset_adjustments(0)

    assert all(
        window.preset_table.item(0, column).background().style() == Qt.BrushStyle.NoBrush
        for column in (3, 4, 5)
    )

    window.close()


def test_live_snapshot_completion_marks_implausible_output_gain_immediately(
    monkeypatch, app
) -> None:
    window = MainWindow()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)
    window.preset_table.insertRow(0)
    selected = QTableWidgetItem()
    selected.setCheckState(Qt.CheckState.Checked)
    window.preset_table.setItem(0, 0, selected)
    window.preset_table.setItem(0, 1, QTableWidgetItem("18D"))
    window.preset_table.setItem(0, 2, QTableWidgetItem("Song"))
    window.preset_table_controller.clear_preset_adjustments(0)
    window.preset_table_controller.set_output_level(window.preset_table.item(0, 4), "19.0")
    window.target_lufs.setText("-16")

    window.update_progress(
        ProgressEvent(
            "snapshot_completed",
            device_patch="18D",
            snapshot=1,
            lufs=-20.0,
            crest_factor_db=12.0,
        )
    )

    adjustment = window.preset_table.item(0, 5)
    assert adjustment.text() == "+4 ⚠️"
    assert adjustment.font().bold()
    assert "Resulting output block level would be 23 dB" in adjustment.toolTip()
    assert window.preset_table.item(0, 1).background().color().name() == "#fee2e2"
    assert window.preset_table.item(0, 0).background().style() == Qt.BrushStyle.NoBrush

    window.close()


def test_implausible_gain_warning_is_marked_as_bad_lufs(monkeypatch, app) -> None:
    window = MainWindow()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)
    window.preset_table.insertRow(0)
    selected = QTableWidgetItem()
    selected.setCheckState(Qt.CheckState.Checked)
    window.preset_table.setItem(0, 0, selected)
    window.preset_table.setItem(0, 1, QTableWidgetItem("02B"))
    window.preset_table_controller.clear_preset_adjustments(0)
    window.preset_table_controller.set_output_level(window.preset_table.item(0, 4), "0.0")

    window.update_progress(
        ProgressEvent(
            "log",
            message="[GAIN] 02B Solo (S) | bad LUFS (Implausible output gain 21.9 dB)",
        )
    )
    window.update_progress(ProgressEvent("preset_completed", device_patch="02B"))

    assert window.preset_table.item(0, 3).text() == "Solo"
    assert (
        window.preset_table.cellWidget(0, 3).text() == "Solo <span style='color: #f59e0b;'>★</span>"
    )
    adjustment = window.preset_table.item(0, 5)
    assert adjustment.text() == "+21.9 ⚠️"
    assert adjustment.font().bold()
    assert adjustment.foreground().color().name() == "#b91c1c"
    assert "Resulting output block level would be 21.9 dB" in adjustment.toolTip()
    assert "Line 6 Helix supported range of -120.0 to +20.0 dB" in adjustment.toolTip()

    window.close()


def test_bad_lufs_log_derives_adjustment_from_matching_multi_output_levels(
    monkeypatch, app
) -> None:
    window = MainWindow()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)
    window.preset_table.insertRow(0)
    selected = QTableWidgetItem()
    selected.setCheckState(Qt.CheckState.Checked)
    window.preset_table.setItem(0, 0, selected)
    window.preset_table.setItem(0, 1, QTableWidgetItem("06A"))
    window.preset_table.setItem(0, 2, QTableWidgetItem("Song"))
    window.preset_table_controller.clear_preset_adjustments(0)
    window.preset_table_controller.set_snapshot_names(0, ("Snap One",))
    window.preset_table_controller.set_output_level(window.preset_table.item(0, 4), "14.0, 14.0")

    window.update_progress(
        ProgressEvent(
            "log",
            message=(
                "[GAIN] 06A Snap One | measurement unavailable "
                "(Implausible output gain 21.2 dB for 06A Snap One dsp1.outputA. "
                "This usually means the measurement recorded silence.)"
            ),
        )
    )
    window.update_progress(ProgressEvent("preset_completed", device_patch="06A"))

    adjustment = window.preset_table.item(0, 5)
    assert adjustment.text() == "+7.2 ⚠️"
    assert "output block level is unavailable" not in adjustment.toolTip()
    assert "Resulting output block level would be 21.2 dB" in adjustment.toolTip()

    window.close()


def test_bad_lufs_log_matches_named_output_path_for_different_output_levels(
    monkeypatch, app
) -> None:
    window = MainWindow()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)
    window.preset_table.insertRow(0)
    selected = QTableWidgetItem()
    selected.setCheckState(Qt.CheckState.Checked)
    window.preset_table.setItem(0, 0, selected)
    window.preset_table.setItem(0, 1, QTableWidgetItem("06C"))
    window.preset_table.setItem(0, 2, QTableWidgetItem("Tuerlich"))
    window.preset_table_controller.clear_preset_adjustments(0)
    window.preset_table_controller.set_snapshot_names(0, ("Intro",))
    window.preset_table_controller.set_snapshot_output_levels(
        0, ((17.3, 6.3),), ("dsp0.outputA", "dsp1.outputA")
    )

    window.update_progress(
        ProgressEvent(
            "log",
            message=(
                "[GAIN] 06C Intro | measurement unavailable "
                "(Implausible output gain 21.2 dB for 06C Intro dsp1.outputA. "
                "This usually means the measurement recorded silence.)"
            ),
        )
    )
    window.update_progress(ProgressEvent("preset_completed", device_patch="06C"))

    adjustment = window.preset_table.item(0, 5)
    assert adjustment.text() == "+14.9 ⚠️"
    assert "output block level is unavailable" not in adjustment.toolTip()
    assert "Resulting output block level would be 21.2 dB" in adjustment.toolTip()

    window.close()


def test_bad_gain_log_uses_snapshot_label_after_unparsed_gain_line(monkeypatch, app) -> None:
    window = MainWindow()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)
    window.target_lufs.setText("-16.0")
    window.preset_table.insertRow(0)
    selected = QTableWidgetItem()
    selected.setCheckState(Qt.CheckState.Checked)
    window.preset_table.setItem(0, 0, selected)
    window.preset_table.setItem(0, 1, QTableWidgetItem("06A"))
    window.preset_table.setItem(0, 2, QTableWidgetItem("Song"))
    window.preset_table_controller.clear_preset_adjustments(0)
    window.preset_table_controller.set_snapshot_names(0, ("Snap One", "Snap Two"))
    window.preset_table_controller.set_output_level(window.preset_table.item(0, 4), "14.0, 14.0")
    window.preset_table_controller.set_output_level(window.preset_table.item(0, 7), "14.0, 10.0")

    window.update_progress(
        ProgressEvent(
            "snapshot_completed",
            device_patch="06A",
            snapshot=1,
            lufs=-14.1865,
            crest_factor_db=17.1954,
        )
    )
    window.update_progress(
        ProgressEvent(
            "snapshot_completed",
            device_patch="06A",
            snapshot=2,
            lufs=-23.4837,
            crest_factor_db=11.4141,
        )
    )

    assert window.preset_table.item(0, 5).text() == "-1.8"
    assert window.preset_table.item(0, 8).text() == "+7.2 ⚠️"

    window.update_progress(
        ProgressEvent(
            "log",
            message=(
                "[GAIN] 06A Snap One | "
                "dsp1.outputA 14.0 dB -> 12.2 dB, "
                "dsp2.outputB 14.0 dB -> 12.2 dB "
                "(Delta: -1.8 dB)"
            ),
        )
    )
    window.update_progress(
        ProgressEvent(
            "log",
            message=(
                "[GAIN] 06A Snap Two | measurement unavailable "
                "(Implausible output gain 21.2 dB for 06A Snap Two dsp1.outputA. "
                "This usually means the measurement recorded silence.)"
            ),
        )
    )
    window.update_progress(ProgressEvent("preset_completed", device_patch="06A"))

    assert window.preset_table.item(0, 5).text() == "-1.8"
    assert window.preset_table.item(0, 8).text() == "+7.2 ⚠️"
    assert window.preset_table.item(0, 8).foreground().color().name() == "#b91c1c"
    assert "output block level is unavailable" not in window.preset_table.item(0, 8).toolTip()
    assert all(
        not window.preset_table.item(0, column).data(BAD_LUFS_HIGHLIGHT_ROLE)
        for column in (3, 4, 5)
    )
    assert all(
        window.preset_table.item(0, column).data(BAD_LUFS_HIGHLIGHT_ROLE) for column in (6, 7, 8)
    )

    window.close()


def test_bad_lufs_is_logged_as_warning(app) -> None:
    window = MainWindow()
    window.update_progress(ProgressEvent("log", message="[GAIN] 02B Clean | bad LUFS"))

    assert "WARNING" in window.log.toHtml()

    window.close()
