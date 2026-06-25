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
from PySide6.QtGui import QCloseEvent, QColor, QIcon, QPalette, QPixmap
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
    QToolButton,
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
    MANUAL_NAME_MODIFIED_BACKGROUND,
    NORMALIZATION_FOCUS_BLUE,
    PresetTableController,
    SnapshotNameCellWidget,
    adjustment_column_width,
    is_snapshot_adjustment_column,
    is_snapshot_name_column,
    output_level_column_width,
    refresh_adjustment_cell_widget,
    refresh_preset_item_background,
    refresh_snapshot_name_cell_widget,
    snapshot_adjustment_column,
    snapshot_name_column,
    snapshot_output_column,
)
from matchpatch.gui.preset_table_csv import preset_table_csv_row
from matchpatch.gui.save_workflow import (
    SaveCancelled,
    SaveContext,
    SaveWorkflow,
    create_table_save_csv,
)
from matchpatch.gui.table_roles import (
    ADJUSTMENT_VALUE_ROLE,
    BAD_LUFS_HIGHLIGHT_ROLE,
    CUSTOM_ADJUSTMENT_COLOR,
    IGNORED_SNAPSHOT_REASONS_ROLE,
    IGNORED_SNAPSHOT_ROLE,
    IGNORE_REASON_COMPARISON,
    IGNORE_REASON_PRESET,
    IGNORE_REASON_REGEX,
    MANUAL_NAME_MODIFIED_ROLE,
    MEASURED_ADJUSTMENT_ROLE,
    NORMALIZATION_FOCUS_ROLE,
    PRESET_ORIGINAL_FILENAME_ROLE,
    PROCESSED_SNAPSHOT_ROLE,
    RECORDED_OUTPUT_PATH_ROLE,
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


class _ControllerCallbacks:
    def __init__(self, table: ContentHeightTableWidget) -> None:
        self.table = table
        self.snapshot_count_value = 2
        self.input_path = "/tmp/input.hls"
        self.refresh_estimate_calls = 0
        self.refresh_file_action_calls = 0
        self.clear_manual_highlight_calls = 0
        self.modified_values: list[bool] = []
        self.manual_checked = False
        self.errors: list[str] = []
        self.snapshot_name_calls: list[tuple[QTableWidgetItem, str, bool, bool]] = []
        self.snapshot_ignore_calls: list[tuple[int, int, str, bool]] = []
        self.refresh_measurement_calls = 0
        self.refresh_adjustment_calls = 0
        self.refresh_snapshot_widget_calls = 0
        self.refresh_cell_background_calls = 0

    def snapshot_count_for_estimate(self) -> int:
        return self.snapshot_count_value

    def snapshot_count(self) -> int:
        return self.snapshot_count_value

    def input_path_text(self) -> str:
        return self.input_path

    def validate_helix_name(self, name: str, max_length: int | None = None) -> str:
        if max_length is not None:
            return name[:max_length]
        return name

    def validate_preset_name(self, name: str) -> str:
        return self.validate_helix_name(name, self.preset_name_max_length())

    def validate_subdivision_name(self, name: str) -> str:
        return self.validate_helix_name(name, self.snapshot_name_max_length())

    def sanitize_preset_name(self, name: str) -> str:
        max_length = self.preset_name_max_length()
        sanitized = name.replace("%", "")
        return sanitized[:max_length] if max_length is not None else sanitized

    def sanitize_subdivision_name(self, name: str) -> str:
        max_length = self.snapshot_name_max_length()
        sanitized = name.replace("%", "")
        return sanitized[:max_length] if max_length is not None else sanitized

    def preset_name_max_length(self) -> int | None:
        return None

    def snapshot_name_max_length(self) -> int | None:
        return None

    def preset_table_csv_row(self, row: int) -> list[str]:
        return [
            self.table.item(row, column).text() if self.table.item(row, column) is not None else ""
            for column in range(self.table.columnCount())
        ]

    def preset_table_clean_signature(self) -> tuple[tuple[str, ...], ...]:
        return ()

    def preset_row(self, patch: str) -> int | None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 1)
            if item is not None and item.text() == patch:
                return row
        return None

    def refresh_preset_measurement_time_estimate(self) -> None:
        self.refresh_estimate_calls += 1

    def refresh_file_actions(self) -> None:
        self.refresh_file_action_calls += 1

    def preset_table_modified_changed(self, modified: bool) -> None:
        self.modified_values.append(modified)

    def clear_manual_name_modified_highlights(self) -> None:
        self.clear_manual_highlight_calls += 1

    def manual_adjustments_checked(self) -> bool:
        return self.manual_checked

    def set_preset_ignore_reason(self, row: int, active: bool) -> None:
        pass

    def clear_preset_adjustments(self, row: int) -> None:
        pass

    def set_adjustment_value(self, item: QTableWidgetItem, text: str, value: float) -> None:
        item.setText(text)
        item.setData(ADJUSTMENT_VALUE_ROLE, value)

    def refresh_adjustment_cell_widget(self, item: QTableWidgetItem) -> None:
        self.refresh_adjustment_calls += 1

    def refresh_snapshot_name_cell_widget(self, item: QTableWidgetItem) -> None:
        self.refresh_snapshot_widget_calls += 1

    def set_snapshot_name(
        self,
        item: QTableWidgetItem,
        name: str,
        is_solo: bool,
        is_ignored: bool = False,
    ) -> None:
        self.snapshot_name_calls.append((item, name, is_solo, is_ignored))
        item.setText(name)

    def set_snapshot_ignore_reason(
        self,
        row: int,
        snapshot_index: int,
        reason: str,
        active: bool,
    ) -> None:
        self.snapshot_ignore_calls.append((row, snapshot_index, reason, active))

    def is_solo_snapshot_name(self, name: str) -> bool:
        return "solo" in name.lower()

    def is_ignored_snapshot_name(self, name: str) -> bool:
        return "skip" in name.lower()

    def refresh_measurement_time_estimate(self) -> None:
        self.refresh_measurement_calls += 1

    def refresh_preset_item_background(self, item: QTableWidgetItem) -> None:
        refresh_preset_item_background(item)

    def refresh_preset_cell_widget_background(self, item: QTableWidgetItem) -> None:
        self.refresh_cell_background_calls += 1

    def show_error(self, message: str) -> None:
        self.errors.append(message)


def _controller_table() -> tuple[ContentHeightTableWidget, _ControllerCallbacks]:
    table = ContentHeightTableWidget()
    table.setColumnCount(9)
    for row, patch in enumerate(("01A", "02B")):
        table.insertRow(row)
        selected = QTableWidgetItem()
        selected.setCheckState(Qt.CheckState.Checked)
        table.setItem(row, 0, selected)
        table.setItem(row, 1, QTableWidgetItem(patch))
        table.setItem(row, 2, QTableWidgetItem(f"Preset {patch}"))
        for snapshot_index in range(2):
            table.setItem(row, snapshot_name_column(snapshot_index), QTableWidgetItem("Snap"))
    return table, _ControllerCallbacks(table)


def test_preset_table_controller_tracks_selection_and_measurable_rows(app) -> None:
    table, callbacks = _controller_table()
    controller = PresetTableController(table, callbacks, set())
    table.item(0, snapshot_name_column(1)).setData(IGNORED_SNAPSHOT_ROLE, True)
    table.item(1, snapshot_name_column(0)).setData(IGNORED_SNAPSHOT_ROLE, True)
    table.item(1, snapshot_name_column(1)).setData(IGNORED_SNAPSHOT_ROLE, True)

    assert controller.row_measured_snapshot_indexes(0) == (1,)
    assert controller.row_measured_snapshot_count(1) == 0
    assert controller.has_ignored_snapshot_cells()
    assert controller.checked_preset_rows() == [0, 1]
    assert controller.selected_measurable_preset_rows() == [0]

    table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    assert controller.checked_preset_rows() == [1]
    assert controller.selected_measurable_preset_rows() == []
    table.close()


def test_preset_table_controller_restores_selection_state_and_modified_signature(app) -> None:
    table, callbacks = _controller_table()
    controller = PresetTableController(table, callbacks, set())
    table.selectRow(1)
    table.setCurrentCell(1, 1)
    state = controller.preset_selection_state()

    controller.set_all_presets_checked(False)
    table.clearSelection()
    table.setCurrentCell(0, 1)
    controller.restore_preset_selection_state(state)

    assert controller.checked_preset_rows() == [0, 1]
    assert {index.row() for index in table.selectionModel().selectedIndexes()} == {1}
    assert table.currentRow() == 1
    assert callbacks.refresh_estimate_calls == 1

    controller.reset_preset_table_modified()
    assert not controller.preset_table_has_unsaved_changes()
    assert callbacks.clear_manual_highlight_calls == 1
    assert callbacks.refresh_file_action_calls == 1
    table.item(0, 2).setText("Changed")
    assert controller.preset_table_content_signature() != controller.clean_signature
    controller.mark_preset_table_modified()
    assert controller.preset_table_has_unsaved_changes()
    table.close()


def test_preset_table_controller_builds_adjustment_payload(app) -> None:
    table, callbacks = _controller_table()
    controller = PresetTableController(table, callbacks, set())
    first_adjustment = QTableWidgetItem("+1.5")
    first_adjustment.setData(ADJUSTMENT_VALUE_ROLE, 1.5)
    table.setItem(0, snapshot_adjustment_column(0), first_adjustment)
    ignored_adjustment = QTableWidgetItem("+9.0")
    ignored_adjustment.setData(ADJUSTMENT_VALUE_ROLE, 9.0)
    ignored_adjustment.setData(IGNORED_SNAPSHOT_ROLE, True)
    table.setItem(0, snapshot_adjustment_column(1), ignored_adjustment)

    adjustments = controller.table_adjustments()

    assert adjustments.preset_names["01A"] == "Preset 01A"
    assert adjustments.snapshot_names["01A"] == {0: "Snap", 1: "Snap"}
    assert adjustments.gain_deltas["01A"] == {0: 1.5}
    table.close()


def test_preset_table_controller_tracks_original_filenames(app) -> None:
    table, callbacks = _controller_table()
    controller = PresetTableController(table, callbacks, set())

    controller.set_preset_original_filename(0, "lead.hlx")
    controller.set_preset_original_filename(1, "")

    assert controller.preset_original_filename(0) == "lead.hlx"
    assert controller.preset_original_filename(1) is None
    assert table.item(0, 2).data(PRESET_ORIGINAL_FILENAME_ROLE) == "lead.hlx"
    assert controller.original_filename_map(lambda patch: {"01A": [1], "02B": [6]}[patch]) == {
        1: "lead.hlx"
    }

    table.item(1, 1).setText("06B")
    controller.set_preset_original_filename(1, "rhythm.hlx")
    assert controller.preset_ids_for_rows(
        [0, 1], lambda patch: {"01A": [1], "06B": [22]}[patch]
    ) == [
        1,
        22,
    ]
    table.close()


def test_preset_table_controller_lists_patch_ids_for_save_workflow(app) -> None:
    table, callbacks = _controller_table()
    controller = PresetTableController(table, callbacks, set())

    assert controller.preset_patches() == ["01A", "02B"]

    table.close()


def test_preset_table_controller_owns_manual_edit_rules(app) -> None:
    table, callbacks = _controller_table()
    controller = PresetTableController(table, callbacks, set())
    callbacks.manual_checked = True
    callbacks.snapshot_count_value = 1
    callbacks.preset_name_max_length = lambda: 6
    callbacks.snapshot_name_max_length = lambda: 8
    adjustment = QTableWidgetItem("0")
    table.setItem(0, snapshot_adjustment_column(0), adjustment)

    assert controller.manual_table_cell_double_click_target(0, 2) is table.item(0, 2)

    assert controller.finish_manual_cell_edit(0, 2, "Preset%Long", commit=True)
    assert table.item(0, 2).text() == "Preset"
    assert table.item(0, 2).data(MANUAL_NAME_MODIFIED_ROLE)

    snapshot_item = table.item(0, snapshot_name_column(0))
    assert controller.finish_manual_cell_edit(
        0,
        snapshot_name_column(0),
        "Solo Skip!",
        commit=True,
    )
    assert snapshot_item.text() == "Solo Ski"
    assert snapshot_item.data(MANUAL_NAME_MODIFIED_ROLE)

    assert controller.finish_manual_cell_edit(
        0,
        snapshot_adjustment_column(0),
        "1.25",
        commit=True,
    )
    assert adjustment.data(ADJUSTMENT_VALUE_ROLE) == 1.25

    snapshot_item.setText("Skip%")
    controller.preset_item_changed(snapshot_item)

    assert snapshot_item.text() == "Skip"
    assert table.item(0, 2).data(Qt.ItemDataRole.UserRole)[0] == "Skip"
    assert snapshot_item.data(IGNORED_SNAPSHOT_ROLE)
    assert IGNORE_REASON_REGEX in snapshot_item.data(IGNORED_SNAPSHOT_REASONS_ROLE)
    assert callbacks.refresh_measurement_calls == 1
    assert callbacks.modified_values[-1] is True
    table.close()


def test_preset_table_controller_uses_callback_name_sanitizers(app) -> None:
    table, callbacks = _controller_table()
    controller = PresetTableController(table, callbacks, set())
    callbacks.manual_checked = True
    callbacks.snapshot_count_value = 1
    callbacks.sanitize_preset_name = lambda name: name.replace("*", "-")
    callbacks.sanitize_subdivision_name = lambda name: name.replace("*", "")

    assert controller.finish_manual_cell_edit(0, 2, "Lead*Wide", commit=True)
    assert table.item(0, 2).text() == "Lead-Wide"

    assert controller.finish_manual_cell_edit(
        0,
        snapshot_name_column(0),
        "Solo*Boost",
        commit=True,
    )
    assert table.item(0, snapshot_name_column(0)).text() == "SoloBoost"

    table.close()


def test_preset_table_controller_owns_adjustment_and_ignore_state(app) -> None:
    table, callbacks = _controller_table()
    controller = PresetTableController(table, callbacks, set())
    callbacks.snapshot_count_value = 1
    adjustment = QTableWidgetItem()
    output = QTableWidgetItem()
    table.setItem(0, snapshot_output_column(0), output)
    table.setItem(0, snapshot_adjustment_column(0), adjustment)

    controller.set_output_level(output, 3.25)
    controller.set_adjustment_value(adjustment, "+1.5", 1.5)

    assert output.text() == "3.2"
    assert adjustment.text() == "+1.5"
    assert adjustment.data(ADJUSTMENT_VALUE_ROLE) == 1.5

    controller.set_snapshot_ignore_reason(0, 0, IGNORE_REASON_REGEX, True)

    name = table.item(0, snapshot_name_column(0))
    assert name.data(IGNORED_SNAPSHOT_ROLE)
    assert output.data(IGNORED_SNAPSHOT_ROLE)
    assert adjustment.data(IGNORED_SNAPSHOT_ROLE)
    assert adjustment.text() == "-"
    assert callbacks.refresh_snapshot_widget_calls >= 1

    controller.set_snapshot_ignore_reason(0, 0, IGNORE_REASON_REGEX, False)

    assert not name.data(IGNORED_SNAPSHOT_ROLE)
    assert not output.data(IGNORED_SNAPSHOT_ROLE)
    assert not adjustment.data(IGNORED_SNAPSHOT_ROLE)
    assert adjustment.text() == "0"
    table.close()


def test_preset_table_controller_collects_manual_adjustment_snapshots(app) -> None:
    table, callbacks = _controller_table()
    controller = PresetTableController(table, callbacks, set())
    table.item(0, snapshot_name_column(0)).setText(" Clean ")
    table.item(1, snapshot_name_column(1)).setText(" Lead ")
    first_adjustment = QTableWidgetItem("Manual")
    first_adjustment.setData(BAD_LUFS_HIGHLIGHT_ROLE, True)
    second_adjustment = QTableWidgetItem("Manual")
    second_adjustment.setData(BAD_LUFS_HIGHLIGHT_ROLE, True)
    ignored_adjustment = QTableWidgetItem("OK")
    ignored_adjustment.setData(BAD_LUFS_HIGHLIGHT_ROLE, False)
    table.setItem(0, snapshot_adjustment_column(0), first_adjustment)
    table.setItem(0, snapshot_adjustment_column(1), ignored_adjustment)
    table.setItem(1, snapshot_adjustment_column(1), second_adjustment)

    snapshots = controller.manual_adjustment_snapshots()

    assert snapshots == [
        results.ManualAdjustmentSnapshot(
            patch="01A",
            preset="Preset 01A",
            snapshot_index=0,
            snapshot_name="Clean",
        ),
        results.ManualAdjustmentSnapshot(
            patch="02B",
            preset="Preset 02B",
            snapshot_index=1,
            snapshot_name="Lead",
        ),
    ]
    assert results.manual_adjustment_targets(snapshots) == [
        "01A Preset 01A: snapshot 1 (Clean)",
        "02B Preset 02B: snapshot 2 (Lead)",
    ]
    table.close()


def test_preset_table_controller_applies_snapshot_measurement_display(app) -> None:
    table, callbacks = _controller_table()
    controller = PresetTableController(table, callbacks, set())
    adjustment = QTableWidgetItem("0")
    table.setItem(0, snapshot_adjustment_column(0), adjustment)

    applied = controller.apply_snapshot_measurement_display(
        0,
        results.SnapshotMeasurementDisplay(
            patch="01A",
            snapshot_index=0,
            adjustment_text="",
            adjustment_value=2.5,
            measured_adjustment=None,
            tooltip="",
            status="measured",
            display_adjustment=2.5,
        ),
    )

    assert applied
    assert adjustment.text() == "+2.5"
    assert adjustment.data(ADJUSTMENT_VALUE_ROLE) == 2.5
    assert table.item(0, snapshot_name_column(0)).data(PROCESSED_SNAPSHOT_ROLE)
    assert "01A" in controller.adjusted_presets
    table.close()


def test_preset_table_controller_marks_implausible_snapshot_measurement(app) -> None:
    table, callbacks = _controller_table()
    controller = PresetTableController(table, callbacks, set())
    adjustment = QTableWidgetItem("0")
    table.setItem(0, snapshot_adjustment_column(0), adjustment)

    applied = controller.apply_snapshot_measurement_display(
        0,
        results.SnapshotMeasurementDisplay(
            patch="01A",
            snapshot_index=0,
            adjustment_text="",
            adjustment_value=None,
            measured_adjustment=4.0,
            tooltip="Implausible output gain 23 dB",
            status="implausible",
            display_adjustment=4.0,
            implausible_output_gain=23.0,
        ),
    )

    assert applied
    assert adjustment.text() == "+4 ⚠️"
    assert adjustment.data(ADJUSTMENT_VALUE_ROLE) is None
    assert adjustment.data(MEASURED_ADJUSTMENT_ROLE) == 4.0
    assert adjustment.data(BAD_LUFS_HIGHLIGHT_ROLE)
    assert "Resulting output block level would be 23 dB" in adjustment.toolTip()
    assert "01A" in controller.adjusted_presets
    table.close()


def test_preset_table_controller_applies_and_clears_comparison_ignore_plan(app) -> None:
    table, callbacks = _controller_table()
    controller = PresetTableController(table, callbacks, set())

    measurable = controller.set_comparison_ignore_plan({"01A": (2,)})

    assert measurable == 1
    assert table.item(0, snapshot_name_column(0)).data(IGNORED_SNAPSHOT_REASONS_ROLE) == (
        IGNORE_REASON_COMPARISON,
    )
    assert table.item(0, snapshot_name_column(1)).data(IGNORED_SNAPSHOT_REASONS_ROLE) is None
    assert table.item(1, snapshot_name_column(0)).data(IGNORED_SNAPSHOT_REASONS_ROLE) == (
        IGNORE_REASON_COMPARISON,
    )
    assert table.item(1, snapshot_name_column(1)).data(IGNORED_SNAPSHOT_REASONS_ROLE) == (
        IGNORE_REASON_COMPARISON,
    )

    controller.set_snapshot_ignore_reason(0, 0, IGNORE_REASON_REGEX, True)
    controller.set_preset_ignore_reason(1, True)
    controller.clear_comparison_ignore_plan()

    assert table.item(0, snapshot_name_column(0)).data(IGNORED_SNAPSHOT_REASONS_ROLE) == (
        IGNORE_REASON_REGEX,
    )
    assert table.item(1, snapshot_name_column(0)).data(IGNORED_SNAPSHOT_REASONS_ROLE) == (
        IGNORE_REASON_PRESET,
    )
    assert table.item(1, snapshot_name_column(1)).data(IGNORED_SNAPSHOT_REASONS_ROLE) == (
        IGNORE_REASON_PRESET,
    )
    table.close()


def test_preset_table_controller_owns_snapshot_highlights(app) -> None:
    table, callbacks = _controller_table()
    controller = PresetTableController(table, callbacks, set())
    callbacks.snapshot_count_value = 1
    table.setItem(0, snapshot_output_column(0), QTableWidgetItem())
    table.setItem(0, snapshot_adjustment_column(0), QTableWidgetItem())

    controller.set_processed_snapshot_highlight(0, 0, True)

    assert table.item(0, snapshot_name_column(0)).data(PROCESSED_SNAPSHOT_ROLE)
    assert callbacks.refresh_cell_background_calls == 3

    controller.set_bad_lufs_highlight(0, 0)

    assert table.item(0, 1).data(BAD_LUFS_HIGHLIGHT_ROLE)
    assert not table.item(0, snapshot_name_column(0)).data(PROCESSED_SNAPSHOT_ROLE)

    controller.clear_bad_lufs_highlight(0)

    assert not table.item(0, 1).data(BAD_LUFS_HIGHLIGHT_ROLE)
    table.close()


def test_snapshot_column_helpers_match_snapshot_stride() -> None:
    assert snapshot_name_column(0) == 3
    assert snapshot_output_column(0) == 4
    assert snapshot_adjustment_column(0) == 5
    assert snapshot_name_column(2) == 9
    assert snapshot_output_column(2) == 10
    assert snapshot_adjustment_column(2) == 11
    assert is_snapshot_name_column(3)
    assert is_snapshot_name_column(9)
    assert not is_snapshot_name_column(4)
    assert is_snapshot_adjustment_column(5)
    assert is_snapshot_adjustment_column(11)
    assert not is_snapshot_adjustment_column(3)


def test_preset_table_controller_configures_snapshot_columns(app) -> None:
    table, callbacks = _controller_table()
    callbacks.snapshot_count_value = 3
    controller = PresetTableController(table, callbacks, set())

    controller.configure_snapshot_columns(3)

    assert table.columnCount() == 12
    assert [table.horizontalHeaderItem(column).text() for column in range(6)] == [
        "",
        "Preset",
        "Name",
        "1",
        "Out (dB)",
        "Δ (dB)",
    ]
    header = table.horizontalHeader()
    assert header.sectionResizeMode(0) == QHeaderView.ResizeMode.Fixed
    assert header.sectionResizeMode(1) == QHeaderView.ResizeMode.Interactive
    assert not header.stretchLastSection()
    assert table.columnWidth(1) == 52
    assert table.columnWidth(2) == 120
    assert table.columnWidth(snapshot_name_column(0)) == 100
    assert table.columnWidth(snapshot_output_column(0)) == output_level_column_width(table)
    assert table.columnWidth(snapshot_adjustment_column(0)) == adjustment_column_width(table)
    assert table.horizontalHeaderItem(3).toolTip() == "Name of snapshot 1 read from the input file."
    assert table.item(0, snapshot_output_column(2)).text() == ""
    assert table.item(0, snapshot_adjustment_column(2)).text() == "0"
    table.close()


def test_content_height_table_uses_configured_background_refreshers(app) -> None:
    table = ContentHeightTableWidget()
    table.setColumnCount(6)
    table.insertRow(0)
    for column in range(table.columnCount()):
        table.setItem(0, column, QTableWidgetItem())
    refreshed_items = []
    refreshed_widgets = []
    table.refresh_preset_item_background = refreshed_items.append
    table.refresh_preset_cell_widget_background = refreshed_widgets.append

    table.set_normalization_focus(0, 0)

    assert refreshed_items
    assert refreshed_widgets
    assert table.item(0, 3).data(NORMALIZATION_FOCUS_ROLE)
    table.close()


def test_refresh_adjustment_cell_widget_renders_custom_adjustment_label(app) -> None:
    table = ContentHeightTableWidget()
    table.setColumnCount(1)
    table.insertRow(0)
    item = QTableWidgetItem("+1.5 (+2)")
    item.setToolTip("Custom loudness adjustment: +2")
    table.setItem(0, 0, item)

    refresh_adjustment_cell_widget(item)

    widget = table.cellWidget(0, 0)
    assert isinstance(widget, QLabel)
    assert "+1.5" in widget.text()
    assert CUSTOM_ADJUSTMENT_COLOR in widget.text()
    table.close()


def test_refresh_snapshot_name_cell_widget_uses_explicit_playback_dependencies(
    tmp_path, app
) -> None:
    table = ContentHeightTableWidget()
    table.setColumnCount(1)
    table.insertRow(0)
    item = QTableWidgetItem("Clean")
    recording = tmp_path / "recorded.wav"
    item.setData(RECORDED_OUTPUT_PATH_ROLE, str(recording))
    table.setItem(0, 0, item)
    played: list[Path] = []

    refresh_snapshot_name_cell_widget(
        item,
        ignore_reason_icons={},
        speaker_icon=QIcon(),
        normalization_in_progress=lambda: False,
        play_recording=played.append,
    )

    button = table.cellWidget(0, 0).findChild(QToolButton)
    assert button is not None
    assert button.isEnabled()
    button.click()
    assert played == [recording]
    table.close()


def test_solo_snapshot_name_cell_widget_draws_left_separator(app) -> None:
    window = MainWindow()
    window.preset_table.insertRow(0)
    window.preset_table.setItem(0, 2, QTableWidgetItem("Song"))
    window.preset_table_controller.clear_preset_adjustments(0)
    window.preset_table_controller.set_snapshot_names(0, ("Solo",))

    widget = window.preset_table.cellWidget(0, 3)
    assert isinstance(widget, SnapshotNameCellWidget)
    widget.resize(80, 24)
    pixmap = QPixmap(widget.size())
    pixmap.fill(widget.palette().color(QPalette.ColorRole.Window))
    widget.render(pixmap)

    separator_color = widget.palette().mid().color().name()
    image = pixmap.toImage()
    assert image.pixelColor(0, widget.height() // 2).name() == separator_color

    window.close()


def test_focused_solo_snapshot_name_cell_widget_draws_blue_frame(app) -> None:
    window = MainWindow()
    window.preset_table.insertRow(0)
    window.preset_table.setItem(0, 2, QTableWidgetItem("Song"))
    window.preset_table_controller.clear_preset_adjustments(0)
    window.preset_table_controller.set_snapshot_names(0, ("Solo",))

    window.preset_table.set_normalization_focus(0, 0)

    widget = window.preset_table.cellWidget(0, 3)
    assert isinstance(widget, SnapshotNameCellWidget)
    focus_rect = widget.property("normalizationSnapshotFocusRect")
    table_focus_rect = window.preset_table._normalization_focus_rect(0, 0)
    assert table_focus_rect is not None
    expected_rect = table_focus_rect.adjusted(0, 0, -1, -1)
    expected_rect.translate(-widget.geometry().x(), -widget.geometry().y())
    assert focus_rect == expected_rect

    pixmap = QPixmap(widget.size())
    pixmap.fill(widget.palette().color(QPalette.ColorRole.Window))
    widget.render(pixmap)

    focus_color = NORMALIZATION_FOCUS_BLUE.name()
    image = pixmap.toImage()
    assert image.pixelColor(focus_rect.left() + 1, image.height() // 2).name() == focus_color
    assert image.pixelColor(image.width() // 2, focus_rect.top() + 1).name() == focus_color
    assert image.pixelColor(image.width() // 2, focus_rect.bottom()).name() == focus_color

    window.close()


def test_ignore_snapshot_regex_marks_and_skips_default_snapshots(monkeypatch, app) -> None:
    window = MainWindow()
    _mock_single_hlx_handler(
        monkeypatch,
        snapshot_names=("SNAPSHOT 1", "Verse"),
        snapshot_output_levels=((0.0,), (0.0,)),
    )
    window.input_path.setText("/tmp/example.hlx")
    window.load_assignments()
    window.preset_table.item(0, 1).setText("01A")
    selected = window.preset_table.item(0, 0)
    assert selected is not None
    selected.setCheckState(Qt.CheckState.Checked)
    window.target_lufs.setText("-16")

    name = window.preset_table.item(0, 3)
    output = window.preset_table.item(0, 4)
    adjustment = window.preset_table.item(0, 5)
    assert name.background().color().name() == "#e5e7eb"
    assert output.background().color().name() == "#e5e7eb"
    assert adjustment.background().color().name() == "#e5e7eb"
    assert name.foreground().color().name() == "#4b5563"
    assert output.foreground().color().name() == "#4b5563"
    assert adjustment.foreground().color().name() == "#4b5563"
    assert adjustment.text() == "-"

    window.update_progress(
        ProgressEvent(
            "snapshot_completed",
            device_patch="01A",
            snapshot=1,
            lufs=-20.0,
            crest_factor_db=12.0,
        )
    )

    assert adjustment.text() == "-"
    assert adjustment.data(ADJUSTMENT_VALUE_ROLE) is None
    assert 0 not in window._table_adjustments().gain_deltas["01A"]

    window.close()


def test_hide_preset_regex_hides_matching_preset(monkeypatch, app) -> None:
    window = MainWindow()
    _mock_single_hlx_handler(
        monkeypatch,
        name="Init Tone",
        snapshot_names=("Verse", "Chorus"),
        snapshot_output_levels=((0.0,), (0.0,)),
    )
    window.ignore_preset_regex.setText("^Init")
    window.input_path.setText("/tmp/example.hlx")
    window.load_assignments()
    window.preset_table.item(0, 1).setText("01A")
    selected = window.preset_table.item(0, 0)
    assert selected is not None
    selected.setCheckState(Qt.CheckState.Checked)

    assert window.preset_table.isRowHidden(0)
    assert window._selected_measurable_preset_rows() == []

    selected.setCheckState(Qt.CheckState.Unchecked)
    name = window.preset_table.item(0, snapshot_name_column(0))
    assert name.data(IGNORED_SNAPSHOT_REASONS_ROLE) == (IGNORE_REASON_PRESET,)

    window.ignore_preset_regex.setText("^Other")

    assert not window.preset_table.isRowHidden(0)
    assert name.data(IGNORED_SNAPSHOT_REASONS_ROLE) == (IGNORE_REASON_PRESET,)
    assert window._row_measured_snapshot_indexes(0) == ()

    selected.setCheckState(Qt.CheckState.Checked)

    assert name.data(IGNORED_SNAPSHOT_ROLE) is None
    assert window._row_measured_snapshot_indexes(0) == (1, 2, 3, 4)

    window.close()


def test_snapshot_ignore_reasons_stack_and_clear_independently(app) -> None:
    window = MainWindow()
    window.snapshot_count_input.setValue(1)
    window.preset_table.insertRow(0)
    selected = QTableWidgetItem()
    selected.setCheckState(Qt.CheckState.Checked)
    window.preset_table.setItem(0, 0, selected)
    window.preset_table.setItem(0, 1, QTableWidgetItem("02B"))
    window.preset_table.setItem(0, 2, QTableWidgetItem("Song"))
    window.preset_table_controller.clear_preset_adjustments(0)
    window.preset_table_controller.set_snapshot_names(0, ("SNAPSHOT 1",))

    selected.setCheckState(Qt.CheckState.Unchecked)
    window.preset_table_controller.set_snapshot_ignore_reason(
        0,
        0,
        IGNORE_REASON_COMPARISON,
        True,
    )

    name = window.preset_table.item(0, snapshot_name_column(0))
    assert name.data(IGNORED_SNAPSHOT_REASONS_ROLE) == (
        IGNORE_REASON_REGEX,
        IGNORE_REASON_PRESET,
        IGNORE_REASON_COMPARISON,
    )
    assert "ignore regex" in name.toolTip()
    assert "preset unchecked" in name.toolTip()
    assert "unchanged compared" in name.toolTip()

    selected.setCheckState(Qt.CheckState.Checked)

    assert name.data(IGNORED_SNAPSHOT_REASONS_ROLE) == (
        IGNORE_REASON_REGEX,
        IGNORE_REASON_COMPARISON,
    )

    window.ignore_snapshot_regex.setText("^Mute$")

    assert name.data(IGNORED_SNAPSHOT_REASONS_ROLE) == (IGNORE_REASON_COMPARISON,)
    assert name.data(IGNORED_SNAPSHOT_ROLE) is True

    window.preset_table_controller.set_snapshot_ignore_reason(
        0,
        0,
        IGNORE_REASON_COMPARISON,
        False,
    )

    assert name.data(IGNORED_SNAPSHOT_ROLE) is None
    assert name.background().style() == Qt.BrushStyle.NoBrush

    window.close()


def test_preset_bulk_selection_buttons(app) -> None:
    window = MainWindow()
    for row, name in enumerate(("01A", "01B")):
        window.preset_table.insertRow(row)
        selected = QTableWidgetItem()
        selected.setCheckState(Qt.CheckState.Checked)
        window.preset_table.setItem(row, 0, selected)
        window.preset_table.setItem(row, 1, QTableWidgetItem(name))
        window.preset_table_controller.clear_preset_adjustments(row)

    window.set_all_presets_checked(False)
    assert all(
        window.preset_table.item(row, 0).checkState() == Qt.CheckState.Unchecked
        for row in range(window.preset_table.rowCount())
    )
    assert window.preset_table.item(0, snapshot_adjustment_column(0)).text() == "-"
    window.set_all_presets_checked(True)
    assert all(
        window.preset_table.item(row, 0).checkState() == Qt.CheckState.Checked
        for row in range(window.preset_table.rowCount())
    )

    window.close()


def test_select_diff_presets_marks_unchanged_snapshots(monkeypatch, app, tmp_path) -> None:
    window = MainWindow()
    input_path = tmp_path / "current.hls"
    previous_path = tmp_path / "previous.hls"
    input_path.touch()
    previous_path.touch()
    window.input_path.setText(str(input_path))
    window._show_loaded_preset_state(single_preset=False)
    window.snapshot_count_input.setValue(2)
    for row, name in enumerate(("01A", "01B", "01C")):
        window.preset_table.insertRow(row)
        selected = QTableWidgetItem()
        selected.setCheckState(Qt.CheckState.Checked)
        window.preset_table.setItem(row, 0, selected)
        window.preset_table.setItem(row, 1, QTableWidgetItem(name))
        window.preset_table_controller.clear_preset_adjustments(row)

    class Handler:
        @staticmethod
        def diff_snapshot_ids(input_path, previous_input_path, snapshot_count):
            return {2: (2,)}

        @staticmethod
        def format_patch_id(preset_id):
            return f"01{'ABC'[preset_id - 1]}"

    class Profile:
        @staticmethod
        def create_patch_file_handler(root):
            return Handler()

    monkeypatch.setattr(main_window, "get_device_profile", lambda device: Profile())
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(previous_path), ""),
    )
    window.measurement_time_estimate.setText("stale")

    window.select_diff_presets()

    assert [
        window.preset_table.item(row, 0).checkState()
        for row in range(window.preset_table.rowCount())
    ] == [
        Qt.CheckState.Checked,
        Qt.CheckState.Checked,
        Qt.CheckState.Checked,
    ]
    assert window.preset_table.item(1, snapshot_name_column(0)).data(
        IGNORED_SNAPSHOT_REASONS_ROLE
    ) == (IGNORE_REASON_COMPARISON,)
    assert window.preset_table.item(1, snapshot_name_column(1)).data(IGNORED_SNAPSHOT_ROLE) is None
    assert window._row_measured_snapshot_indexes(1) == (2,)
    assert (
        selected_preset_set(window._selected_measurable_preset_rows(), window._preset_patch_at_row)
        == "01B"
    )
    assert "1 preset, 1 snapshot" in window.measurement_time_estimate.text()
    assert window.comparison_enabled.isEnabled()
    assert window.comparison_enabled.isChecked()

    window.comparison_enabled.setChecked(False)

    assert (
        window.preset_table.item(1, snapshot_name_column(0)).data(IGNORED_SNAPSHOT_REASONS_ROLE)
        is None
    )
    assert window._row_measured_snapshot_indexes(1) == (1, 2)
    assert (
        selected_preset_set(window._selected_measurable_preset_rows(), window._preset_patch_at_row)
        == "01A,01B,01C"
    )

    window.comparison_enabled.setChecked(True)

    assert window.preset_table.item(1, snapshot_name_column(0)).data(
        IGNORED_SNAPSHOT_REASONS_ROLE
    ) == (IGNORE_REASON_COMPARISON,)
    assert window._row_measured_snapshot_indexes(1) == (2,)

    window.close()


def test_manual_adjustments_gate_table_editing_and_build_export_payload(monkeypatch, app) -> None:
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

    assert not window.manual_adjustments.isChecked()
    assert window.manual_adjustments.text() == "Edit manually"
    assert window.show_legend_button.text() == "Show legend"
    assert window.preset_table.editTriggers() == window.preset_table.EditTrigger.NoEditTriggers
    assert window.presets.layout().indexOf(window.preset_measurement_time_estimate) == 4
    preset_table_note_row = window.presets.layout().itemAt(3).layout()
    assert preset_table_note_row is not None
    assert preset_table_note_row.indexOf(window.show_legend_button) < preset_table_note_row.indexOf(
        window.manual_adjustments
    )
    assert preset_table_note_row.indexOf(window.manual_adjustments) < preset_table_note_row.indexOf(
        window.preset_csv_controls
    )

    window.manual_adjustments.setChecked(True)
    assert window.preset_table.editTriggers() == window.preset_table.EditTrigger.NoEditTriggers
    assert all(
        not window.preset_table.item(0, column).flags() & Qt.ItemFlag.ItemIsEditable
        for column in range(1, 5)
    )

    answers = iter([("Song 2", True), ("Clean!", True), ("+1.5", True)])
    for column in (2, snapshot_name_column(0), snapshot_adjustment_column(0)):
        value, _accepted = next(answers)
        window._manual_table_cell_double_clicked(0, column)
        assert isinstance(window._manual_cell_editor, QLineEdit)
        assert window._manual_cell_editor.parent() is window.preset_table.viewport()
        assert window._manual_cell_editor.geometry() == window.preset_table.visualItemRect(
            window.preset_table.item(0, column)
        )
        window._manual_cell_editor.setText(value)
        window._finish_manual_cell_edit(commit=True)

    window.update_progress(
        ProgressEvent("log", message="[GAIN] 02B Clean | 0.0 dB -> 1.5 dB (Delta: +1.5 dB)")
    )
    window.update_progress(ProgressEvent("preset_completed", device_patch="02B"))

    adjustments = window._table_adjustments()
    assert adjustments.preset_names == {"02B": "Song 2"}
    assert adjustments.snapshot_names["02B"][0] == "Clean!"
    assert adjustments.gain_deltas["02B"][0] == 1.5
    assert window._preset_table_modified
    window.preset_table.item(0, 2).setText("Invalid%")
    assert window.preset_table.item(0, 2).text() == "Invalid"

    window.close()


def test_manual_name_edits_highlight_changed_cells_until_csv_save(
    tmp_path, monkeypatch, app
) -> None:
    window = MainWindow()
    window.snapshot_count_input.setValue(1)
    window.preset_table.insertRow(0)
    selected = QTableWidgetItem()
    selected.setCheckState(Qt.CheckState.Checked)
    window.preset_table.setItem(0, 0, selected)
    window.preset_table.setItem(0, 1, QTableWidgetItem("02B"))
    window.preset_table.setItem(0, 2, QTableWidgetItem("Song"))
    window.preset_table_controller.clear_preset_adjustments(0)
    window.preset_table_controller.set_snapshot_names(0, ("Clean",))
    window._reset_preset_table_modified()
    window.manual_adjustments.setChecked(True)

    preset_item = window.preset_table.item(0, 2)
    snapshot_item = window.preset_table.item(0, 3)

    window._manual_table_cell_double_clicked(0, 2)
    window._manual_cell_editor.setText("Song")
    window._finish_manual_cell_edit(commit=True)
    assert preset_item.background().style() == Qt.BrushStyle.NoBrush

    window._manual_table_cell_double_clicked(0, 2)
    window._manual_cell_editor.setText("Song%")
    window._finish_manual_cell_edit(commit=True)
    assert preset_item.text() == "Song"
    assert preset_item.background().style() == Qt.BrushStyle.NoBrush

    window._manual_table_cell_double_clicked(0, 2)
    window._manual_cell_editor.setText("Song 2")
    window._finish_manual_cell_edit(commit=True)
    assert preset_item.background().color() == MANUAL_NAME_MODIFIED_BACKGROUND

    window._manual_table_cell_double_clicked(0, 3)
    window._manual_cell_editor.setText("Clean!")
    window._finish_manual_cell_edit(commit=True)
    assert snapshot_item.background().color() == MANUAL_NAME_MODIFIED_BACKGROUND

    csv_path = tmp_path / "preset-table.csv"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(csv_path), ""),
    )

    window.save_preset_table_csv()

    assert preset_item.background().style() == Qt.BrushStyle.NoBrush
    assert snapshot_item.background().style() == Qt.BrushStyle.NoBrush

    window.close()


def test_recorded_snapshot_playback_uses_completed_request_windows_python(monkeypatch, app) -> None:
    captured = {}

    class SignalStub:
        def connect(self, callback):
            captured.setdefault("connections", []).append(callback)

    class WorkerStub:
        failed = SignalStub()
        finished = SignalStub()

        def __init__(self, path, parent=None, *, windows_python=None):
            captured["path"] = path
            captured["parent"] = parent
            captured["windows_python"] = windows_python

        def isRunning(self):
            return False

        def deleteLater(self):
            captured["delete_later"] = True

        def start(self):
            captured["started"] = True

    monkeypatch.setattr(main_window, "AudioPlaybackWorker", WorkerStub)
    window = MainWindow()
    window.completed_request = _request(windows_python="C:/MatchPatch/python.exe")
    path = Path("/tmp/recorded.wav")

    window._play_recording(path)

    assert captured["path"] == path
    assert captured["parent"] is window
    assert captured["windows_python"] == "C:/MatchPatch/python.exe"
    assert captured["started"]

    window.close()


def test_custom_adjustment_is_shown_but_numeric_delta_is_exported(app) -> None:
    window = MainWindow()
    window.snapshot_count_input.setValue(2)
    window.input_path.setText("input.hls")
    window.preset_table.setRowCount(1)
    window.preset_table.setItem(0, 0, QTableWidgetItem())
    window.preset_table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    window.preset_table.setItem(0, 1, QTableWidgetItem("02B"))
    window.preset_table.setItem(0, 2, QTableWidgetItem("Song"))
    window.preset_table_controller.clear_preset_adjustments(0)
    window._custom_adjustments = {"02B": {0: 2.0}}

    window.update_progress(
        ProgressEvent("log", message="[GAIN] 02B Clean | 0.0 dB -> 3.5 dB (Delta: +3.5 dB)")
    )
    window.update_progress(ProgressEvent("preset_completed", device_patch="02B"))

    adjustment_item = window.preset_table.item(0, 5)
    assert adjustment_item.text() == "+1.5 (+2)"
    assert adjustment_item.toolTip() == "Custom loudness adjustment: +2"
    custom_label = window.preset_table.cellWidget(0, 5)
    assert isinstance(custom_label, QLabel)
    assert custom_label.autoFillBackground()
    assert "color: #2563eb" in custom_label.text()
    assert "(+2)" in custom_label.text()
    assert window._table_adjustments().gain_deltas["02B"][0] == 3.5
    assert preset_table_csv_row(window.preset_table, 0, window.snapshot_count)[3] == "+3.5"

    window._reset_preset_table_modified()
    window.close()


def test_manual_adjustments_reject_invalid_helix_names(app) -> None:
    window = MainWindow()
    window.preset_table.insertRow(0)
    window.preset_table.setItem(0, 1, QTableWidgetItem("02B"))
    window.preset_table.setItem(0, 2, QTableWidgetItem("Invalid%"))
    window.preset_table_controller.clear_preset_adjustments(0)

    with pytest.raises(ValueError, match="Invalid Helix name"):
        window._table_adjustments()

    window.close()


def test_manual_adjustments_limit_helix_name_lengths(monkeypatch, app) -> None:
    window = MainWindow()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)
    window.preset_table.insertRow(0)
    window.preset_table.setItem(0, 1, QTableWidgetItem("02B"))
    window.preset_table.setItem(0, 2, QTableWidgetItem("Original"))
    window.preset_table_controller.clear_preset_adjustments(0)
    window.preset_table_controller.set_snapshot_names(0, ("Clean",))

    window.manual_adjustments.setChecked(True)

    window._manual_table_cell_double_clicked(0, 2)
    assert isinstance(window._manual_cell_editor, QLineEdit)
    assert window._manual_cell_editor.maxLength() == 16
    window._manual_cell_editor.setText("PresetNameLongerThanSixteen")
    window._finish_manual_cell_edit(commit=True)
    assert window.preset_table.item(0, 2).text() == "PresetNameLonger"

    window._manual_table_cell_double_clicked(0, 3)
    assert isinstance(window._manual_cell_editor, QLineEdit)
    assert window._manual_cell_editor.maxLength() == 10
    window._manual_cell_editor.setText("SnapshotNameTooLong")
    window._finish_manual_cell_edit(commit=True)
    assert window.preset_table.item(0, 3).text() == "SnapshotNa"

    window.preset_table.item(0, 2).setText("DirectNameLongerThanSixteen")
    assert window.preset_table.item(0, 2).text() == "DirectNameLonger"

    window.manual_adjustments.setChecked(False)
    window.preset_table.item(0, 3).setText("UncheckedSnapshotName")
    with pytest.raises(ValueError, match="exceeds 10 characters"):
        window._table_adjustments()

    window.close()


def test_preset_table_can_be_sorted_by_column_headers(app) -> None:
    window = MainWindow()
    for row, (patch, name) in enumerate((("02B", "Clean"), ("01A", "Lead"))):
        window.preset_table.insertRow(row)
        selected = QTableWidgetItem()
        selected.setCheckState(Qt.CheckState.Checked)
        window.preset_table.setItem(row, 0, selected)
        window.preset_table.setItem(row, 1, QTableWidgetItem(patch))
        window.preset_table.setItem(row, 2, QTableWidgetItem(name))
        window.preset_table_controller.clear_preset_adjustments(row)

    assert window.preset_table.isSortingEnabled()
    header = window.preset_table.horizontalHeader()
    assert header.sectionsClickable()

    def click_header(column: int) -> None:
        QTest.mouseClick(
            header.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(header.sectionViewportPosition(column) + header.sectionSize(column) // 2, 5),
        )
        app.processEvents()

    click_header(1)
    assert window.preset_table.item(0, 1).text() == "01A"
    assert window.preset_table.item(0, 2).text() == "Lead"

    click_header(2)
    assert window.preset_table.item(0, 1).text() == "02B"
    assert window.preset_table.item(0, 2).text() == "Clean"

    window.close()


def test_selected_preset_adjustments_are_pending_until_measured(monkeypatch, app) -> None:
    window = MainWindow()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)
    window.preset_table.insertRow(0)
    window.preset_table.insertRow(1)
    for row, preset_id in enumerate(("02B", "02C")):
        selected = QTableWidgetItem()
        selected.setCheckState(Qt.CheckState.Checked if row == 0 else Qt.CheckState.Unchecked)
        window.preset_table.setItem(row, 0, selected)
        window.preset_table.setItem(row, 1, QTableWidgetItem(preset_id))
        window.preset_table.setItem(row, 2, QTableWidgetItem("Song"))
        window.preset_table_controller.clear_preset_adjustments(row)

    for row in range(window.preset_table.rowCount()):
        window.preset_table_controller.clear_preset_adjustments(row)
        window.preset_table_controller.mark_selected_preset_adjustments_pending(row)

    assert [window.preset_table.item(0, column).text() for column in (5, 8, 11, 14)] == [
        "?",
        "?",
        "?",
        "?",
    ]
    assert [window.preset_table.item(1, column).text() for column in (5, 8, 11, 14)] == [
        "0",
        "0",
        "0",
        "0",
    ]

    window.update_progress(
        ProgressEvent("log", message="[GAIN] 02B Clean | 0.0 dB -> 1.5 dB (Delta: +1.5 dB)")
    )
    window.update_progress(ProgressEvent("preset_completed", device_patch="02B"))

    assert window.preset_table.item(0, 4).text() == "0.0"
    assert window.preset_table.item(0, 5).text() == "+1.5"
    assert [window.preset_table.item(0, column).text() for column in (8, 11, 14)] == [
        "?",
        "?",
        "?",
    ]

    window.close()


def test_recorded_pending_adjustment_widget_updates_with_gain_value(tmp_path, monkeypatch, app):
    window = MainWindow()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)
    window.preset_table.insertRow(0)
    selected = QTableWidgetItem()
    selected.setCheckState(Qt.CheckState.Checked)
    window.preset_table.setItem(0, 0, selected)
    window.preset_table.setItem(0, 1, QTableWidgetItem("02B"))
    window.preset_table.setItem(0, 2, QTableWidgetItem("Song"))
    window.preset_table_controller.clear_preset_adjustments(0)
    window.preset_table_controller.mark_selected_preset_adjustments_pending(0)

    recording = tmp_path / "recorded.wav"
    recording.touch()
    window.update_progress(
        ProgressEvent(
            "snapshot_recorded",
            device_patch="02B",
            snapshot=1,
            path=str(recording),
        )
    )

    assert window.preset_table.item(0, 5).text() == "?"
    assert window.preset_table.cellWidget(0, 5) is None
    name_widget = window.preset_table.cellWidget(0, 3)
    assert name_widget.findChild(QToolButton) is not None

    window.target_lufs.setText("-16.0")
    window.update_progress(
        ProgressEvent(
            "snapshot_completed",
            device_patch="02B",
            snapshot=1,
            lufs=-17.5,
            crest_factor_db=12.0,
        )
    )

    item = window.preset_table.item(0, 5)
    assert item.text() == "+1.5"
    assert window.preset_table.cellWidget(0, 5) is None
    assert window.preset_table.cellWidget(0, 3).autoFillBackground()

    window.close()


def test_recorded_snapshot_playback_is_disabled_while_normalizing(
    tmp_path, monkeypatch, app
) -> None:
    window = MainWindow()
    window.preset_table.insertRow(0)
    selected = QTableWidgetItem()
    selected.setCheckState(Qt.CheckState.Checked)
    window.preset_table.setItem(0, 0, selected)
    window.preset_table.setItem(0, 1, QTableWidgetItem("02B"))
    window.preset_table.setItem(0, 2, QTableWidgetItem("Song"))
    window.preset_table_controller.clear_preset_adjustments(0)
    window.preset_table_controller.mark_selected_preset_adjustments_pending(0)

    recording = tmp_path / "recorded.wav"
    recording.touch()
    window.worker = SimpleNamespace(isRunning=lambda: True)
    window.update_progress(
        ProgressEvent(
            "snapshot_recorded",
            device_patch="02B",
            snapshot=1,
            path=str(recording),
        )
    )

    speaker_button = window.preset_table.cellWidget(0, 3).findChild(QToolButton)
    assert speaker_button is not None
    assert not speaker_button.isEnabled()

    monkeypatch.setattr(
        main_window,
        "AudioPlaybackWorker",
        lambda *args, **kwargs: pytest.fail("playback should wait until normalization ends"),
    )
    window._play_recording(recording)

    window.worker = None
    window._refresh_recorded_output_buttons()

    speaker_button = window.preset_table.cellWidget(0, 3).findChild(QToolButton)
    assert speaker_button is not None
    assert speaker_button.isEnabled()

    window.close()


def test_snapshot_count_widget_redraws_columns_and_preserves_loaded_names(app) -> None:
    window = MainWindow()
    window.preset_table.insertRow(0)
    window.preset_table.setItem(0, 2, QTableWidgetItem("Song"))
    window.preset_table_controller.clear_preset_adjustments(0)
    window.preset_table_controller.set_snapshot_names(
        0, ("One", "Two", "Three", "Four", "Five", "Six")
    )

    window.snapshot_count_input.setValue(6)

    assert window.snapshot_count == 6
    assert window.preset_table.columnCount() == 21
    assert window.preset_table.item(0, 18).text() == "Six"
    argv = GuiSettingsBinder.from_widgets(window).build_argv()
    assert argv[argv.index("--snapshot-count") + 1] == "6"

    window.snapshot_count_input.setValue(2)
    window.snapshot_count_input.setValue(6)

    assert window.preset_table.item(0, 18).text() == "Six"

    window.close()


def test_bad_lufs_row_highlight_is_reset_for_new_input_and_measurement(monkeypatch, app) -> None:
    window = MainWindow()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)
    window.preset_table.insertRow(0)
    selected = QTableWidgetItem()
    selected.setCheckState(Qt.CheckState.Checked)
    window.preset_table.setItem(0, 0, selected)
    window.preset_table.setItem(0, 1, QTableWidgetItem("02B"))
    window.preset_table.setItem(0, 2, QTableWidgetItem("Song"))
    window.preset_table_controller.clear_preset_adjustments(0)

    window.update_progress(ProgressEvent("log", message="[GAIN] 02B Clean | bad LUFS"))
    window.update_progress(ProgressEvent("preset_completed", device_patch="02B"))
    assert window.preset_table.item(0, 1).background().color().name() == "#fee2e2"
    assert window.preset_table.item(0, 0).background().style() == Qt.BrushStyle.NoBrush

    monkeypatch.setattr(QMessageBox, "critical", lambda *args: None)

    class FailingProfile:
        @staticmethod
        def create_patch_file_handler(root):
            class FailingHandler:
                @staticmethod
                def file_kind(path):
                    return "setlist"

                @staticmethod
                def validate_input(path):
                    raise ValueError("Invalid input")

            return FailingHandler()

    monkeypatch.setattr(main_window, "get_device_profile", lambda device: FailingProfile())
    window.input_path.setText("missing.hls")
    window.load_assignments()
    assert window.preset_table.item(0, 0).background().style() == Qt.BrushStyle.NoBrush

    window.update_progress(ProgressEvent("log", message="[GAIN] 02B Clean | bad LUFS"))
    window.update_progress(ProgressEvent("preset_completed", device_patch="02B"))
    monkeypatch.setattr(advanced_settings, "parse_args", lambda argv: object())
    monkeypatch.setattr(advanced_settings, "apply_config", lambda args: args)
    monkeypatch.setattr(advanced_settings, "request_from_args", lambda args: _request())
    monkeypatch.setattr(main_window.NormalizationWorker, "start", lambda self: None)
    monkeypatch.setattr(window, "_prompt_save_before_normalization", lambda: True)
    window.start_normalization()
    assert window.preset_table.item(0, 0).background().style() == Qt.BrushStyle.NoBrush

    window.worker_finished()
    window.close()
