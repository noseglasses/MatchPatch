from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

pytest.importorskip("PySide6")

from gui_test_helpers import request
from PySide6.QtCore import QAbstractAnimation, Qt
from PySide6.QtWidgets import QMessageBox, QTableWidgetItem

from matchpatch.gui import main_window_status, progress_widgets
from matchpatch.gui.main_window import MainWindow
from matchpatch.gui.preset_table import (
    IGNORED_SNAPSHOT_BACKGROUND,
    NORMALIZATION_FOCUS_BACKGROUND,
)
from matchpatch.gui.table_roles import NORMALIZATION_FOCUS_ROLE
from matchpatch.progress import ProgressEvent
from matchpatch.workflow import NormalizationResult

_request = request


def test_log_section_and_busy_indicator(monkeypatch, app) -> None:
    window = MainWindow()
    resize_calls = []
    monkeypatch.setattr(window, "_schedule_resize_for_content", lambda: resize_calls.append(True))

    assert window.log_section is window.log
    assert window.advanced_tabs.widget(7).isAncestorOf(window.log_section)
    window._start_busy_phase()
    assert window.progress_group.isHidden()
    assert window.busy_animation.state() == QAbstractAnimation.State.Running
    assert window.busy_animation.duration() == 2000
    assert window.busy_animation.loopCount() == -1
    assert window._processing_dot_green
    window.update_progress(
        ProgressEvent(
            "preset_started",
            device_patch="01A",
            preset_index=1,
            preset_total=2,
            snapshot_total=4,
        )
    )
    assert not window.progress_group.isHidden()
    assert window.busy_animation.state() == QAbstractAnimation.State.Running
    assert window.preset_progress.maximum() == 8
    assert resize_calls == [True]
    window.update_progress(
        ProgressEvent(
            "snapshot_started",
            device_patch="01A",
            preset_index=1,
            preset_total=2,
            snapshot=2,
            snapshot_total=4,
        )
    )
    assert resize_calls == [True]
    window._stop_busy_phase()
    assert window.progress_group.isHidden()
    assert resize_calls == [True, True]
    assert window.busy_animation.state() == QAbstractAnimation.State.Stopped
    assert window.processing_dot_effect.opacity() == 1.0
    assert not window._processing_dot_green

    window.close()


def test_progress_statuses_include_suitable_icons(monkeypatch, app) -> None:
    window = MainWindow()
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)

    assert window.phase.text() == "Ready"
    assert not window.phase_icon.pixmap().isNull()
    window.update_progress(ProgressEvent("phase", phase="measuring"))
    assert window.phase.text() == "Measuring..."
    assert not window.phase_icon.pixmap().isNull()
    assert not window.progress_group.isHidden()
    assert window.current.text() == "Preparing measurement..."
    assert window.preset_progress.minimum() == 0
    assert window.preset_progress.maximum() == 0
    window.update_progress(
        ProgressEvent("measurement_preparation", message="Loading reference DI audio...")
    )
    assert window.current.text() == "Loading reference DI audio..."
    window.update_progress(ProgressEvent("phase", phase="waiting_for_measurement_import"))
    assert window.phase.text() == "Waiting For Measurement Import..."
    assert window.progress_group.isHidden()
    window.update_progress(ProgressEvent("phase", phase="measuring"))
    window.normalization_completed(NormalizationResult(Path("adjusted.hls"), None))
    assert window.phase.text() == "Completed"
    assert not window.phase_icon.pixmap().isNull()
    assert window.progress_group.isHidden()
    window.show_error("Measurement failed")
    assert window.phase.text() == "Error"
    assert not window.phase_icon.pixmap().isNull()

    window.close()


def test_preset_progress_shows_most_recently_measured_preset_and_snapshot_names(
    monkeypatch, app
) -> None:
    window = MainWindow()
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args: QMessageBox.StandardButton.Discard,
    )
    window.preset_table.insertRow(0)
    selected = QTableWidgetItem()
    selected.setCheckState(Qt.CheckState.Checked)
    window.preset_table.setItem(0, 0, selected)
    window.preset_table.setItem(0, 1, QTableWidgetItem("02B"))
    window.preset_table.setItem(0, 2, QTableWidgetItem("Lead"))
    window.preset_table_controller.clear_preset_adjustments(0)
    window.preset_table_controller.set_snapshot_names(0, ("Rhythm", "Solo"))

    window.update_progress(
        ProgressEvent(
            "snapshot_started",
            device_patch="02B",
            preset_index=1,
            preset_total=1,
            snapshot=1,
            snapshot_total=4,
        )
    )

    assert window.current.text() == ""
    assert not window.progress_group.isHidden()
    window.update_progress(
        ProgressEvent(
            "snapshot_completed",
            device_patch="02B",
            preset_index=1,
            preset_total=1,
            snapshot=1,
            snapshot_total=4,
            lufs=-18.0,
        )
    )

    assert window.current.text() == "Preset 02B: Lead, snapshot 1/4: Rhythm"
    window.update_progress(
        ProgressEvent(
            "snapshot_started",
            device_patch="02B",
            preset_index=1,
            preset_total=1,
            snapshot=2,
            snapshot_total=4,
        )
    )

    assert window.current.text() == "Preset 02B: Lead, snapshot 1/4: Rhythm"
    window.update_progress(
        ProgressEvent(
            "snapshot_completed",
            device_patch="02B",
            preset_index=1,
            preset_total=1,
            snapshot=2,
            snapshot_total=4,
            lufs=-17.0,
        )
    )

    assert window.current.text() == "Preset 02B: Lead, snapshot 2/4: Solo"
    window.update_progress(ProgressEvent("measurement_completed"))
    assert window.progress_group.isHidden()

    window.close()


def test_preset_table_highlights_current_normalization_focus(monkeypatch, app) -> None:
    window = MainWindow()
    for row, preset_id in enumerate(("02B", "02C")):
        window.preset_table.insertRow(row)
        selected = QTableWidgetItem()
        selected.setCheckState(Qt.CheckState.Checked)
        window.preset_table.setItem(row, 0, selected)
        window.preset_table.setItem(row, 1, QTableWidgetItem(preset_id))
        window.preset_table.setItem(row, 2, QTableWidgetItem("Song"))
        window.preset_table_controller.clear_preset_adjustments(row)
    window.preset_table_controller.set_ignored_snapshot_highlight(0, 2, True)

    window.update_progress(ProgressEvent("preset_started", device_patch="02B"))

    assert window.preset_table._normalizing_row == 0
    assert window.preset_table._normalizing_snapshot is None
    assert window.preset_table.item(0, 1).background().color() == (NORMALIZATION_FOCUS_BACKGROUND)
    assert window.preset_table.item(0, 3).background().color() == (NORMALIZATION_FOCUS_BACKGROUND)
    assert window.preset_table.item(0, 4).background().color() == (NORMALIZATION_FOCUS_BACKGROUND)
    assert window.preset_table.item(0, 5).background().color() == (NORMALIZATION_FOCUS_BACKGROUND)
    assert window.preset_table.item(0, 9).background().color() == (IGNORED_SNAPSHOT_BACKGROUND)
    assert window.preset_table.item(0, 10).background().color() == (IGNORED_SNAPSHOT_BACKGROUND)
    assert window.preset_table.item(0, 11).background().color() == (IGNORED_SNAPSHOT_BACKGROUND)
    assert window.preset_table.item(1, 1).background().style() == Qt.BrushStyle.NoBrush

    window.update_progress(ProgressEvent("snapshot_started", device_patch="02B", snapshot=2))

    assert window.preset_table._normalizing_row == 0
    assert window.preset_table._normalizing_snapshot == 1
    assert window.preset_table.item(0, 3).background().color() == (NORMALIZATION_FOCUS_BACKGROUND)
    assert window.preset_table.item(0, 6).background().color() == (NORMALIZATION_FOCUS_BACKGROUND)
    assert window.preset_table.item(0, 9).background().color() == (IGNORED_SNAPSHOT_BACKGROUND)

    focus_during_completion = []

    def capture_completion_focus(event):
        focus_during_completion.append(window.preset_table._normalizing_snapshot)
        for column in (6, 7, 8):
            assert not window.preset_table.item(0, column).data(NORMALIZATION_FOCUS_ROLE)

    monkeypatch.setattr(
        window,
        "_apply_snapshot_measurement",
        capture_completion_focus,
    )
    window.update_progress(
        ProgressEvent(
            "snapshot_completed",
            device_patch="02B",
            snapshot=2,
            lufs=-18.0,
        )
    )

    assert focus_during_completion == [None]
    assert window.preset_table._normalizing_snapshot is None
    assert window.preset_table.item(0, 6).background().style() == Qt.BrushStyle.NoBrush

    window.update_progress(ProgressEvent("snapshot_started", device_patch="02B", snapshot=3))

    assert window.preset_table._normalizing_row == 0
    assert window.preset_table._normalizing_snapshot is None
    assert window.preset_table.item(0, 9).background().color() == (IGNORED_SNAPSHOT_BACKGROUND)

    window.update_progress(ProgressEvent("preset_completed", device_patch="02B"))

    assert window.preset_table._normalizing_row == 0
    assert window.preset_table._normalizing_snapshot is None

    window.update_progress(ProgressEvent("measurement_completed"))

    assert window.preset_table._normalizing_row is None
    assert window.preset_table._normalizing_snapshot is None
    assert window.preset_table.item(0, 1).background().style() == Qt.BrushStyle.NoBrush

    window._preset_table_clean_signature = window._preset_table_content_signature()
    window._preset_table_modified = False
    window._adjusted_presets.clear()
    window.close()


def test_preset_progress_format_shows_duration_and_eta(app) -> None:
    window = MainWindow()
    window._measurement_progress_estimate = (
        progress_widgets.MeasurementProgressEstimate.from_request(
            _request(
                preset_wait=0.5,
                snapshot_wait=0.2,
                measurement_wait=0.4,
                pre_roll=0.2,
                post_roll=0.3,
                round_trip_latency=0.1,
                reference_di=Path("missing-reference.wav"),
            )
        )
    )

    window.update_progress(
        ProgressEvent(
            "preset_started",
            preset_index=1,
            preset_total=2,
            snapshot_total=2,
        )
    )

    assert window.preset_progress.format() == "%p% | total 6 s | ETA 6 s"
    window.update_progress(
        ProgressEvent(
            "snapshot_started",
            preset_index=1,
            preset_total=2,
            snapshot=1,
            snapshot_total=2,
        )
    )

    assert window.preset_progress.format() == "%p% | total 6 s | ETA 6 s"
    window.update_progress(
        ProgressEvent(
            "snapshot_completed",
            preset_index=1,
            preset_total=2,
            snapshot=1,
            snapshot_total=2,
        )
    )

    assert window.preset_progress.format() == "%p% | total 6 s | ETA 5 s"
    window.update_progress(
        ProgressEvent(
            "snapshot_started",
            preset_index=2,
            preset_total=2,
            snapshot=2,
            snapshot_total=2,
        )
    )

    assert window.preset_progress.format() == "%p% | total 6 s | ETA 2 s"
    window.update_progress(ProgressEvent("measurement_completed"))
    assert window.preset_progress.format() == "%p%"

    window.close()


def test_cancellation_sets_status_without_redundant_popup(monkeypatch, app) -> None:
    window = MainWindow()
    popups = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: popups.append(args))

    window.normalization_cancelled()

    assert popups == []
    assert window.phase.text() == "Normalization cancelled by user"
    assert "Normalization cancelled by user" in window.log.toHtml()
    assert main_window_status.PROCESSING_DOT_RED in window.processing_dot.styleSheet()

    window.worker_finished()

    assert main_window_status.PROCESSING_DOT_RED in window.processing_dot.styleSheet()

    window.close()


def test_cancel_button_keeps_measurement_running_when_confirmation_is_declined(
    monkeypatch, app
) -> None:
    window = MainWindow()
    worker = Mock()
    window.worker = worker
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)

    window.cancel_normalization()

    worker.cancel.assert_not_called()
    assert window.phase.text() == "Ready"

    window.worker = None
    window.close()


def test_cancel_button_requests_cancellation_when_confirmation_is_accepted(
    monkeypatch, app
) -> None:
    window = MainWindow()
    worker = Mock()
    window.worker = worker
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)

    window.cancel_normalization()

    worker.cancel.assert_called_once_with()
    assert window.phase.text() == "Cancelling..."

    window.worker = None
    window.close()
