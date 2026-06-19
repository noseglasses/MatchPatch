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
    icons,
    loudness_widgets,
    main_window,
    measurement_optimization,
    results,
    table_legend,
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
    NORMALIZATION_FOCUS_BACKGROUND,
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
    IGNORE_REASON_COMPARISON,
    IGNORE_REASON_PRESET,
    IGNORE_REASON_REGEX,
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


def test_save_as_icon_uses_standard_save_disk_with_drawn_overlay(app) -> None:
    image = icons._save_as_icon().pixmap(56, 56).toImage()
    save_image = (
        QApplication.style()
        .standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
        .pixmap(56, 56)
        .toImage()
    )
    sampled_colors = {
        image.pixelColor(x, y).name()
        for x in range(image.width())
        for y in range(image.height())
        if image.pixelColor(x, y).alpha() > 0
    }

    for x in range(24):
        for y in range(24):
            assert image.pixelColor(x, y) == save_image.pixelColor(x, y)
    assert "#fbbf24" in sampled_colors


def test_toggle_icons_show_distinct_off_and_on_states(app) -> None:
    record_off_colors = {
        icons._record_icon(recording=False).pixmap(56, 56).toImage().pixelColor(x, y).name()
        for x in range(56)
        for y in range(56)
    }
    record_on_colors = {
        icons._record_icon(recording=True).pixmap(56, 56).toImage().pixelColor(x, y).name()
        for x in range(56)
        for y in range(56)
    }
    speaker_off_colors = {
        icons._speaker_icon(enabled=False).pixmap(56, 56).toImage().pixelColor(x, y).name()
        for x in range(56)
        for y in range(56)
    }
    speaker_on_colors = {
        icons._speaker_icon(enabled=True).pixmap(56, 56).toImage().pixelColor(x, y).name()
        for x in range(56)
        for y in range(56)
    }

    assert "#9ca3af" in record_off_colors
    assert "#dc2626" in record_on_colors
    assert "#9ca3af" in speaker_off_colors
    assert "#6b7280" in speaker_off_colors
    assert "#2563eb" in speaker_on_colors


def test_ignore_reason_icon_draws_no_entry_symbol(app) -> None:
    image = icons._ignore_reason_icon(IGNORE_REASON_COMPARISON).pixmap(18, 18).toImage()

    green_pixels = 0
    white_pixels = 0
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            if color.alpha() == 0:
                continue
            if color.name() == "#16a34a":
                green_pixels += 1
            if color.name() == "#ffffff":
                white_pixels += 1

    assert green_pixels > 0
    assert white_pixels > 0


def test_tooltip_position_is_kept_inside_screen() -> None:
    available = QRect(0, 0, 200, 100)
    tooltip_size = QSize(80, 20)

    position = icons._visible_tooltip_position(QPoint(195, 90), tooltip_size, available)

    assert position.x() >= available.left() + icons.TOOLTIP_SCREEN_MARGIN
    assert position.y() >= available.top() + icons.TOOLTIP_SCREEN_MARGIN
    assert position.x() + tooltip_size.width() <= available.right() - icons.TOOLTIP_SCREEN_MARGIN
    assert position.y() + tooltip_size.height() <= available.bottom() - icons.TOOLTIP_SCREEN_MARGIN


def test_save_measurement_icon_draws_disk_and_chart_overlay(app) -> None:
    image = icons._save_measurement_icon().pixmap(56, 56).toImage()
    save_image = (
        QApplication.style()
        .standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
        .pixmap(56, 56)
        .toImage()
    )
    sampled_colors = {
        image.pixelColor(x, y).name()
        for x in range(image.width())
        for y in range(image.height())
        if image.pixelColor(x, y).alpha() > 0
    }

    for x in range(24):
        for y in range(24):
            assert image.pixelColor(x, y) == save_image.pixelColor(x, y)
    assert {"#38bdf8", "#22c55e", "#f59e0b"}.issubset(sampled_colors)


def test_record_and_play_toggle_icons_show_distinct_off_and_on_states(app) -> None:
    record_off_colors = {
        icons._record_icon(recording=False).pixmap(56, 56).toImage().pixelColor(x, y).name()
        for x in range(56)
        for y in range(56)
    }
    record_on_colors = {
        icons._record_icon(recording=True).pixmap(56, 56).toImage().pixelColor(x, y).name()
        for x in range(56)
        for y in range(56)
    }
    speaker_off_colors = {
        icons._speaker_icon(enabled=False).pixmap(56, 56).toImage().pixelColor(x, y).name()
        for x in range(56)
        for y in range(56)
    }
    speaker_on_colors = {
        icons._speaker_icon(enabled=True).pixmap(56, 56).toImage().pixelColor(x, y).name()
        for x in range(56)
        for y in range(56)
    }

    assert "#9ca3af" in record_off_colors
    assert "#dc2626" in record_on_colors
    assert "#9ca3af" in speaker_off_colors
    assert "#6b7280" in speaker_off_colors
    assert "#2563eb" in speaker_on_colors


def test_toolbar_tooltip_position_is_kept_inside_screen() -> None:
    available = QRect(0, 0, 200, 100)
    tooltip_size = QSize(80, 20)

    position = icons._visible_tooltip_position(
        QPoint(195, 90),
        tooltip_size,
        available,
    )

    assert position.x() >= available.left() + icons.TOOLTIP_SCREEN_MARGIN
    assert position.y() >= available.top() + icons.TOOLTIP_SCREEN_MARGIN
    assert position.x() + tooltip_size.width() <= available.right() - icons.TOOLTIP_SCREEN_MARGIN
    assert position.y() + tooltip_size.height() <= available.bottom() - icons.TOOLTIP_SCREEN_MARGIN


def test_preset_table_legend_dialog_uses_table_icons(app) -> None:
    ignore_reasons = (
        IGNORE_REASON_PRESET,
        IGNORE_REASON_COMPARISON,
        IGNORE_REASON_REGEX,
    )
    ignore_reason_icons = {reason: icons._ignore_reason_icon(reason) for reason in ignore_reasons}

    parent = QWidget()
    dialog = table_legend.build_preset_table_legend_dialog(
        parent=parent,
        ignore_reason_icons=ignore_reason_icons,
    )

    assert dialog.windowTitle() == "Preset table legend"
    labels = dialog.findChildren(QLabel)
    label_text = "\n".join(label.text() for label in labels)
    assert "Snapshot markers" in label_text
    assert "★" in label_text
    assert "Solo snapshot" in label_text
    assert "whole preset is unchecked" in label_text
    assert "comparison with another Helix file" in label_text
    assert "ignored-snapshot regex" in label_text
    assert "Snapshot cell colors" in label_text
    assert "White: initial state." in label_text
    assert "Grey: ignored." in label_text
    assert "Light blue: preset in progress." in label_text
    assert "Light green: snapshot successfully normalized." in label_text
    assert "Light red: snapshot normalization error." in label_text
    assert "Light blue with blue outline: snapshot in progress." in label_text
    color_entries = [
        "White: initial state.",
        "Light blue: preset in progress.",
        "Light blue with blue outline: snapshot in progress.",
        "Light green: snapshot successfully normalized.",
        "Light red: snapshot normalization error.",
        "Grey: ignored.",
    ]
    assert [label_text.index(entry) for entry in color_entries] == sorted(
        label_text.index(entry) for entry in color_entries
    )
    pixmap_labels = [
        dialog.findChild(QLabel, f"legendIgnoreIcon{reason}") for reason in ignore_reasons
    ]
    assert all(label is not None for label in pixmap_labels)
    assert len(pixmap_labels) == len(ignore_reasons)
    assert {label.pixmap().cacheKey() for label in pixmap_labels if label is not None} == {
        ignore_reason_icons[reason].pixmap(18, 18).cacheKey() for reason in ignore_reasons
    }
    color_swatches = dialog.findChildren(QLabel, "legendColorSwatch")
    assert len(color_swatches) == 6
    outlined_swatch = color_swatches[2].pixmap().toImage()
    center = outlined_swatch.pixelColor(outlined_swatch.width() // 2, outlined_swatch.height() // 2)
    assert center == NORMALIZATION_FOCUS_BACKGROUND

    dialog.close()
    parent.close()
