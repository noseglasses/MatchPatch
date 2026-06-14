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


def test_loudness_text_labels_target_direction() -> None:
    assert loudness_widgets._loudness_text(-16.0, -18.0) == "-16.0 LUFS (2.0 LUFS above target)"
    assert loudness_widgets._loudness_text(-18.0, -18.0) == "-18.0 LUFS (on target)"
    assert loudness_widgets._loudness_text(-20.0, -18.0) == "-20.0 LUFS (2.0 LUFS below target)"


def test_loudness_bar_color_uses_symmetric_green_yellow_red_gradient() -> None:
    assert loudness_widgets._loudness_bar_color(-18.0, -18.0) == QColor("#16a34a")
    assert loudness_widgets._loudness_bar_color(-16.5, -18.0) == QColor(128, 171, 41)
    assert loudness_widgets._loudness_bar_color(-15.0, -18.0) == QColor("#eab308")
    assert loudness_widgets._loudness_bar_color(-13.5, -18.0) == QColor(227, 108, 23)
    assert loudness_widgets._loudness_bar_color(-12.0, -18.0) == QColor("#dc2626")
    assert loudness_widgets._loudness_bar_color(-15.0, -18.0) == (
        loudness_widgets._loudness_bar_color(-21.0, -18.0)
    )


def test_loudness_widgets_expose_stable_ranges(app) -> None:
    bar = loudness_widgets.LoudnessBar()
    scale = loudness_widgets.LoudnessScale()

    assert bar.minimum() == round(
        loudness_widgets.LOUDNESS_MINIMUM * loudness_widgets.LOUDNESS_SCALE
    )
    assert bar.maximum() == round(
        loudness_widgets.LOUDNESS_MAXIMUM * loudness_widgets.LOUDNESS_SCALE
    )
    assert scale.sizeHint().height() == 24


def test_progress_shows_measured_loudness_relative_to_target(app) -> None:
    window = MainWindow()
    window.target_lufs.setText("-18.0")
    window._reset_loudness_bars()
    measured_text_color = window.measured_loudness_reading.palette().color(
        QPalette.ColorRole.WindowText
    )

    window.update_progress(ProgressEvent("reference_loudness", reference_lufs=-20.5))
    window.update_progress(ProgressEvent("snapshot_completed", reference_lufs=-20.5, lufs=-16.0))

    assert window.measured_loudness_reading.text() == "-16.0 LUFS (2.0 LUFS above target)"
    assert not hasattr(window, "reference_loudness")
    assert not hasattr(window, "reference_loudness_label")
    assert not hasattr(window, "reference_loudness_reading")
    assert not window.measured_loudness.isTextVisible()
    assert window.measured_loudness.palette().color(
        QPalette.ColorRole.Highlight
    ) == loudness_widgets._loudness_bar_color(
        -16.0,
        -18.0,
    )
    assert (
        window.measured_loudness_reading.palette().color(QPalette.ColorRole.WindowText)
        == measured_text_color
    )
    assert window.loudness_scale.sizeHint().height() == 24
    assert not hasattr(window, "measured_loudness_label")

    window.close()


def test_measured_loudness_bar_uses_symmetric_green_yellow_red_gradient() -> None:
    assert loudness_widgets._loudness_bar_color(-18.0, -18.0) == QColor("#16a34a")
    assert loudness_widgets._loudness_bar_color(-16.5, -18.0) == QColor(128, 171, 41)
    assert loudness_widgets._loudness_bar_color(-15.0, -18.0) == QColor("#eab308")
    assert loudness_widgets._loudness_bar_color(-13.5, -18.0) == QColor(227, 108, 23)
    assert loudness_widgets._loudness_bar_color(-12.0, -18.0) == QColor("#dc2626")
    assert loudness_widgets._loudness_bar_color(-15.0, -18.0) == (
        loudness_widgets._loudness_bar_color(-21.0, -18.0)
    )
