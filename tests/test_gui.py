from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QPoint
from PySide6.QtGui import QCloseEvent, QColor, QPalette, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStyle,
    QTableWidgetItem,
)
from shiboken6 import isValid

from matchpatch.gui import main_window
from matchpatch.gui import worker as gui_worker
from matchpatch.gui.main_window import MainWindow
from matchpatch.gui.worker import NormalizationWorker
from matchpatch.normalize import DEFAULT_REFERENCE_DI, DEFAULT_WINDOWS_PYTHON
from matchpatch.progress import ProgressEvent
from matchpatch.workflow import ImportRequest, NormalizationRequest, NormalizationResult


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


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


def test_main_window_starts_with_registry_device_and_hardware(app) -> None:
    window = MainWindow()

    assert window.device.currentData() == "helix"
    assert window.backend.currentText() == "hardware"
    assert window.general.title() == "General"
    assert not window.advanced.is_expanded()
    assert window.advanced.content.isHidden()
    assert [window.advanced_tabs.tabText(index) for index in range(4)] == [
        "Device",
        "Misc",
        "Meta Data",
        "Log",
    ]
    assert window.presets.title() == "Presets"
    assert window.presets.isHidden()
    assert window.content.layout().indexOf(window.presets) == (
        window.content.layout().indexOf(window.advanced) + 1
    )
    assert not window.findChildren(QMenuBar)
    assert "Setlist/Preset file" not in [
        label.text() for label in window.general.findChildren(QLabel)
    ]
    assert {"Help", "About"}.isdisjoint(
        {button.text() for button in window.general.findChildren(QPushButton)}
    )
    toolbar = window.findChildren(main_window.QToolBar)[0]
    toolbar_actions = [
        action for action in toolbar.actions() if action.text() and not action.isSeparator()
    ]
    assert [action.text() for action in toolbar_actions] == [
        "Open",
        "Save",
        "Save As",
        "Help",
        "About",
    ]
    assert toolbar.actions().index(window.normalization_separator_action) == (
        toolbar.actions().index(window.save_as_action) + 1
    )
    assert toolbar.actions().index(window.normalization_action) == (
        toolbar.actions().index(window.normalization_separator_action) + 1
    )
    assert toolbar.actions().index(window.help_spacer_action) < toolbar.actions().index(
        window.help_action
    )
    help_spacer = toolbar.widgetForAction(window.help_spacer_action)
    assert help_spacer is not None
    assert help_spacer.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding
    assert toolbar.widgetForAction(window.normalization_action) is window.start_cancel_stack
    assert window.start_cancel_stack.currentWidget() is window.start_button
    assert window.start_button.text() == ""
    assert not window.start_button.icon().isNull()
    assert window.start_button.iconSize() == toolbar.iconSize()
    assert isinstance(window.start_button, main_window.QToolButton)
    assert isinstance(window.cancel_button, main_window.QToolButton)
    assert window.start_button.autoRaise()
    assert window.cancel_button.autoRaise()
    assert window.start_button.toolTip().startswith("Start")
    assert window.start_button.width() == window.start_button.height()
    assert window.cancel_button.width() == window.cancel_button.height()
    assert window.start_button.size() == window.cancel_button.size()
    assert window.start_cancel_stack.size() == window.start_button.size()
    for action in (window.help_action, window.about_action):
        button = toolbar.widgetForAction(action)
        assert button is not None
        assert button.width() == button.height()
    assert window.open_action.isEnabled()
    assert not window.save_action.isEnabled()
    assert not window.save_as_action.isEnabled()
    assert not window.start_button.isEnabled()
    assert window.log_level.currentText() == "Info"
    assert window.metadata_text.toPlainText() == "{}"
    assert window.device_stack.count() == 1
    assert window.device_panels["helix"].audio_group.isEnabled()
    assert window.progress_group.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Maximum
    assert not window.statusBar().isHidden()
    assert not window.statusBar().isSizeGripEnabled()
    assert window.phase.parent() is window.statusBar()
    assert window.processing_dot.parent() is window.statusBar()
    assert window.progress_group.layout().itemAt(0).widget() is window.current
    assert window.progress_group.layout().itemAt(2).widget() is window.preset_progress
    assert window.progress_group.isHidden()
    assert not window.processing_dot.isHidden()
    assert not window._processing_dot_green
    assert not hasattr(window, "ignore_bad_lufs")
    assert window.preset_table.verticalHeader().isHidden()
    assert not window.preset_table.wordWrap()
    assert window.preset_table_note.text() == "Only non-empty presets are listed."
    assert window.preset_csv_label.text() == "CSV: "
    assert window.preset_csv_controls.layout().indexOf(window.preset_csv_label) >= 0
    assert window.preset_csv_controls.layout().indexOf(window.load_csv_button) >= 0
    assert window.preset_csv_controls.layout().indexOf(window.save_csv_button) >= 0
    assert not window.load_csv_button.isEnabled()
    assert not window.save_csv_button.isEnabled()
    assert window.load_csv_button.text() == ""
    assert window.save_csv_button.text() == ""
    assert window.load_csv_button.width() == window.load_csv_button.height()
    assert window.save_csv_button.width() == window.save_csv_button.height()
    assert window.snapshot_count_input.value() == 4
    assert window.snapshot_count_input.maximum() == 8

    window.close()


def test_initial_window_size_avoids_scrollbar_for_collapsed_layout(app) -> None:
    window = MainWindow()
    window.show()
    app.processEvents()
    window._resize_to_initial_content()
    app.processEvents()

    assert not window.scroll_area.verticalScrollBar().isVisible()
    chrome_height = window.height() - window.scroll_area.viewport().height()
    assert window.height() == window.content.sizeHint().height() + chrome_height + 4

    window.close()


def test_window_shrinks_when_advanced_settings_are_folded(app) -> None:
    window = MainWindow()
    window.show()
    app.processEvents()

    window.advanced.set_expanded(True)
    app.processEvents()
    expanded_height = window.height()
    window.advanced.set_expanded(False)
    app.processEvents()

    assert window.height() < expanded_height

    window.close()


def test_window_shrinks_when_progress_is_hidden(app) -> None:
    window = MainWindow()
    window.show()
    app.processEvents()
    window._resize_to_initial_content()
    app.processEvents()
    initial_height = window.height()

    window._show_indeterminate_progress("Preparing measurement...")
    app.processEvents()
    assert window.height() > initial_height

    window._stop_busy_phase()
    app.processEvents()
    assert window.height() == initial_height

    window.close()


def test_advanced_and_preset_panes_follow_their_content_height(app) -> None:
    window = MainWindow()
    initial_presets_height = window.presets.sizeHint().height()
    initial_table_height = window.preset_table.sizeHint().height()
    for row in range(20):
        window.preset_table.insertRow(row)
    app.processEvents()

    assert window.preset_table.sizeHint().height() > initial_table_height
    assert window.preset_table.sizeHint().height() == (
        window.preset_table.horizontalHeader().sizeHint().height()
        + sum(
            window.preset_table.rowHeight(row)
            for row in range(window.preset_table.MAX_VISIBLE_ROWS)
        )
        + window.preset_table.frameWidth() * 2
    )
    assert window.presets.sizeHint().height() > initial_presets_height
    device_height = window.advanced_tabs.sizeHint().height()
    window.advanced_tabs.setCurrentIndex(1)
    app.processEvents()

    assert window.advanced_tabs.sizeHint().height() != device_height

    window.close()


def test_single_preset_load_displays_presets_panel_with_instruction_label(app) -> None:
    window = MainWindow()
    window.show()
    app.processEvents()

    window.input_path.setText("/tmp/example.hlx")
    window.load_assignments()
    app.processEvents()

    assert not window.presets.isHidden()
    assert window.preset_table.isHidden()
    assert not window.single_slot.isHidden()
    assert window.preset_csv_controls.isHidden()
    assert window.preset_hint.height() == window.preset_hint.sizeHint().height()
    assert window.preset_hint.text() == ("Enter the temporary Helix slot used during measurement.")

    window.close()


def test_setlist_load_displays_presets_panel(monkeypatch, app, tmp_path) -> None:
    window = MainWindow()
    path = tmp_path / "example.hls"
    path.write_text("{}", encoding="utf-8")

    class Handler:
        @staticmethod
        def validate_input(path):
            return None

        @staticmethod
        def list_assignments(path):
            return []

        @staticmethod
        def metadata(path):
            return {"file_type": "hls", "metadata": [{"path": "$.meta", "value": {"name": "Set"}}]}

    class Profile:
        @staticmethod
        def create_patch_file_handler(root):
            return Handler()

    monkeypatch.setattr(main_window, "get_device_profile", lambda device: Profile())
    window.input_path.setText(str(path))
    window.load_assignments()

    assert not window.presets.isHidden()
    assert not window.preset_table.isHidden()
    assert not window.preset_csv_controls.isHidden()
    assert window.preset_hint.text() == "Select the presets to normalize."
    assert '"file_type": "hls"' in window.metadata_text.toPlainText()
    assert '"name": "Set"' in window.metadata_text.toPlainText()

    window.close()


def test_setlist_load_enables_preset_table_csv_buttons(monkeypatch, app, tmp_path) -> None:
    window = MainWindow()
    path = tmp_path / "example.hls"
    path.write_text("{}", encoding="utf-8")

    class Handler:
        @staticmethod
        def validate_input(path):
            return None

        @staticmethod
        def list_assignments(path):
            return [
                SimpleNamespace(
                    device_patch="02B",
                    name="Song",
                    snapshot_names=("Clean", "Solo"),
                )
            ]

        @staticmethod
        def metadata(path):
            return {"file_type": "hls"}

    class Profile:
        @staticmethod
        def create_patch_file_handler(root):
            return Handler()

    monkeypatch.setattr(main_window, "get_device_profile", lambda device: Profile())
    window.input_path.setText(str(path))
    window.load_assignments()

    assert window.load_csv_button.isEnabled()
    assert window.save_csv_button.isEnabled()

    window.input_path.setText(str(tmp_path / "single.hlx"))
    window.load_assignments()

    assert not window.load_csv_button.isEnabled()
    assert not window.save_csv_button.isEnabled()

    window.close()


def test_log_section_and_busy_indicator(monkeypatch, app) -> None:
    window = MainWindow()
    resize_calls = []
    monkeypatch.setattr(window, "_schedule_resize_for_content", lambda: resize_calls.append(True))

    assert window.log_section is window.log
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


@pytest.mark.parametrize(
    ("phase", "text"),
    [
        ("ready", "Ready"),
        ("starting", "Starting..."),
        ("preparing_measurement", "Preparing Measurement..."),
        ("waiting_for_measurement_import", "Waiting For Measurement Import..."),
        ("measuring", "Measuring..."),
        ("applying", "Applying..."),
        ("waiting_for_adjusted_import", "Waiting For Adjusted Import..."),
        ("completed", "Completed"),
        ("error", "Error"),
        ("cancelling", "Cancelling..."),
        ("normalization_cancelled_by_user", "Normalization cancelled by user"),
    ],
)
def test_phase_text_marks_in_progress_statuses(phase, text) -> None:
    assert main_window._phase_text(phase) == text


def test_preset_progress_shows_most_recently_measured_preset_and_snapshot_names(app) -> None:
    window = MainWindow()
    window.preset_table.insertRow(0)
    selected = QTableWidgetItem()
    selected.setCheckState(Qt.CheckState.Checked)
    window.preset_table.setItem(0, 0, selected)
    window.preset_table.setItem(0, 1, QTableWidgetItem("02B"))
    window.preset_table.setItem(0, 2, QTableWidgetItem("Lead"))
    window._clear_preset_adjustments(0)
    window._set_snapshot_names(0, ("Rhythm", "Solo"))

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
    ) == main_window._loudness_bar_color(
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
    assert main_window._loudness_bar_color(-18.0, -18.0) == QColor("#16a34a")
    assert main_window._loudness_bar_color(-16.5, -18.0) == QColor(128, 171, 41)
    assert main_window._loudness_bar_color(-15.0, -18.0) == QColor("#eab308")
    assert main_window._loudness_bar_color(-13.5, -18.0) == QColor(227, 108, 23)
    assert main_window._loudness_bar_color(-12.0, -18.0) == QColor("#dc2626")
    assert main_window._loudness_bar_color(-15.0, -18.0) == (
        main_window._loudness_bar_color(-21.0, -18.0)
    )


def test_main_window_loads_explicit_config(tmp_path, app) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[normalize]
backend = "hardware"
target_lufs = -18.0

[devices.helix.audio]
device = "Configured Audio"

[policy]
measured_snapshots = 6
""",
        encoding="utf-8",
    )
    window = MainWindow()
    window.config_path.setText(str(config_path))
    window.load_defaults()

    assert window.backend.currentText() == "hardware"
    assert window.target_lufs.text() == "-18.0"
    assert window.snapshot_count_input.value() == 6
    assert window.preset_table.columnCount() == 15
    assert window.device_panels["helix"].audio_device.text() == "Configured Audio"
    assert window.device_panels["helix"].audio_group.isEnabled()

    window.close()


def test_preset_bulk_selection_buttons(app) -> None:
    window = MainWindow()
    for row, name in enumerate(("01A", "01B")):
        window.preset_table.insertRow(row)
        selected = QTableWidgetItem()
        selected.setCheckState(Qt.CheckState.Checked)
        window.preset_table.setItem(row, 0, selected)
        window.preset_table.setItem(row, 1, QTableWidgetItem(name))
        window._clear_preset_adjustments(row)

    window.set_all_presets_checked(False)
    assert all(
        window.preset_table.item(row, 0).checkState() == Qt.CheckState.Unchecked
        for row in range(window.preset_table.rowCount())
    )
    assert window.preset_table.item(0, 4).text() == "0"
    window.set_all_presets_checked(True)
    assert all(
        window.preset_table.item(row, 0).checkState() == Qt.CheckState.Checked
        for row in range(window.preset_table.rowCount())
    )

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
    window._clear_preset_adjustments(0)
    window._set_snapshot_names(0, ("Clean", "Solo"))

    assert not window.manual_adjustments.isChecked()
    assert window.manual_adjustments.text() == "Edit content"
    assert window.preset_table.editTriggers() == window.preset_table.EditTrigger.NoEditTriggers
    preset_table_note_row = window.presets.layout().itemAt(2).layout()
    assert preset_table_note_row is not None
    assert preset_table_note_row.indexOf(
        window.manual_adjustments
    ) < preset_table_note_row.indexOf(
        window.preset_csv_controls
    )

    window.manual_adjustments.setChecked(True)
    assert window.preset_table.editTriggers() == window.preset_table.EditTrigger.NoEditTriggers
    assert all(
        not window.preset_table.item(0, column).flags() & Qt.ItemFlag.ItemIsEditable
        for column in range(1, 5)
    )

    answers = iter([("Song 2", True), ("Clean!", True), ("+1.5", True)])
    for column in (2, 3, 4):
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

    adjustments = window._table_adjustments()
    assert adjustments.preset_names == {"02B": "Song 2"}
    assert adjustments.snapshot_names["02B"][0] == "Clean!"
    assert adjustments.gain_deltas["02B"][0] == 1.5
    assert window._preset_table_modified
    window.preset_table.item(0, 2).setText("Invalid%")
    assert window.preset_table.item(0, 2).text() == "Invalid"

    window.close()


def test_preset_table_csv_save_uses_pipe_delimiter(tmp_path, monkeypatch, app) -> None:
    window = MainWindow()
    window.snapshot_count_input.setValue(2)
    window.preset_table.insertRow(0)
    selected = QTableWidgetItem()
    selected.setCheckState(Qt.CheckState.Checked)
    window.preset_table.setItem(0, 0, selected)
    window.preset_table.setItem(0, 1, QTableWidgetItem("02B"))
    window.preset_table.setItem(0, 2, QTableWidgetItem("Song, Part 1"))
    window._clear_preset_adjustments(0)
    window._set_snapshot_names(0, ("Clean, bright", "Solo"))
    window._set_adjustment_value(window.preset_table.item(0, 4), "+1.5", 1.5)
    window._set_adjustment_value(window.preset_table.item(0, 6), "-2.0", -2.0)
    csv_path = tmp_path / "preset-table"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(csv_path), ""),
    )

    window.save_preset_table_csv()

    assert (tmp_path / "preset-table.csv").read_text(encoding="utf-8").splitlines() == [
        "preset_id|preset_name|snapshot_1_name|snapshot_1_adjustment|"
        "snapshot_2_name|snapshot_2_adjustment",
        "02B|Song, Part 1|Clean, bright|+1.5|Solo|-2.0",
    ]
    assert "Preset table CSV saved" in window.log.toHtml()

    window.close()


def test_preset_table_csv_load_applies_valid_rows_and_reports_line_errors(
    tmp_path, monkeypatch, app
) -> None:
    window = MainWindow()
    window.snapshot_count_input.setValue(2)
    for row, (patch, name) in enumerate((("02B", "Song"), ("01A", "Other"))):
        window.preset_table.insertRow(row)
        selected = QTableWidgetItem()
        selected.setCheckState(Qt.CheckState.Checked)
        window.preset_table.setItem(row, 0, selected)
        window.preset_table.setItem(row, 1, QTableWidgetItem(patch))
        window.preset_table.setItem(row, 2, QTableWidgetItem(name))
        window._clear_preset_adjustments(row)

    csv_path = tmp_path / "preset-table.csv"
    csv_path.write_text(
        "\n".join(
            [
                "preset_id|preset_name|snapshot_1_name|snapshot_1_adjustment|"
                "snapshot_2_name|snapshot_2_adjustment",
                "02B|Song 2|Clean!|+1.5|Solo|-2.0",
                "99A|Missing|Clean|0|Solo|0",
                "01A|Invalid%|Clean|0|Solo|0",
                "01A|Other|Clean|nan|Solo|0",
                "01A|Other 2|Clean|0|Solo|+3.0",
            ]
        ),
        encoding="utf-8",
    )
    popups = []
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(csv_path), ""),
    )
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: popups.append(args))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)

    window.load_preset_table_csv()

    assert window.preset_table.item(0, 2).text() == "Song 2"
    assert window.preset_table.item(0, 3).text() == "Clean!"
    assert window.preset_table.item(0, 4).text() == "+1.5"
    assert window.preset_table.item(0, 5).text() == "Solo"
    assert window.preset_table.item(0, 6).text() == "-2.0"
    assert window.preset_table.item(1, 2).text() == "Other 2"
    assert window.preset_table.item(1, 6).text() == "+3.0"
    assert len(popups) == 1
    assert popups[0][1] == "Preset table CSV errors"
    assert "Line 3" in popups[0][2]
    assert "Line 4" in popups[0][2]
    assert "Line 5" in popups[0][2]
    assert "preset ID '99A'" in window.log.toPlainText()
    assert "Preset table CSV loaded" in window.log.toHtml()
    assert window._preset_table_modified

    window.close()


def test_preset_table_csv_load_does_not_mark_identical_content_modified(
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
    window._clear_preset_adjustments(0)
    window._set_snapshot_names(0, ("Clean",))
    window._reset_preset_table_modified()
    csv_path = tmp_path / "preset-table.csv"
    csv_path.write_text(
        "\n".join(
            [
                "preset_id|preset_name|snapshot_1_name|snapshot_1_adjustment",
                "02B|Song|Clean|0",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(csv_path), ""),
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args: pytest.fail("identical CSV should not create a close prompt"),
    )

    window.load_preset_table_csv()

    assert not window._preset_table_modified

    window.close()


def test_manual_adjustments_reject_invalid_helix_names(app) -> None:
    window = MainWindow()
    window.preset_table.insertRow(0)
    window.preset_table.setItem(0, 1, QTableWidgetItem("02B"))
    window.preset_table.setItem(0, 2, QTableWidgetItem("Invalid%"))
    window._clear_preset_adjustments(0)

    with pytest.raises(ValueError, match="Invalid Helix name"):
        window._table_adjustments()

    window.close()


def test_manual_adjustments_limit_helix_name_lengths(monkeypatch, app) -> None:
    window = MainWindow()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)
    window.preset_table.insertRow(0)
    window.preset_table.setItem(0, 1, QTableWidgetItem("02B"))
    window.preset_table.setItem(0, 2, QTableWidgetItem("Original"))
    window._clear_preset_adjustments(0)
    window._set_snapshot_names(0, ("Clean",))

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
        window._clear_preset_adjustments(row)

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


def test_gain_log_updates_preset_correction_columns(monkeypatch, app) -> None:
    window = MainWindow()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)
    window.preset_table.insertRow(0)
    selected = QTableWidgetItem()
    selected.setCheckState(Qt.CheckState.Checked)
    window.preset_table.setItem(0, 0, selected)
    window.preset_table.setItem(0, 1, QTableWidgetItem("02B"))
    window.preset_table.setItem(0, 2, QTableWidgetItem("Song"))
    window._clear_preset_adjustments(0)

    window.update_progress(
        ProgressEvent("log", message="[GAIN] 02B Solo (S) | 0.0 dB -> 11.1 dB (Delta: +11.1 dB)")
    )
    window.update_progress(
        ProgressEvent("log", message="[GAIN] 02B Clean | stable at -1.0 dB (Delta: +0.0 dB)")
    )
    window.update_progress(
        ProgressEvent("log", message="[GAIN] 02B Rhythm | 0.0 dB -> -2.0 dB (Delta: -2.0 dB)")
    )

    assert window.preset_table.horizontalHeaderItem(3).text() == "1"
    assert window.preset_table.horizontalHeaderItem(4).text() == "Δ (dB)"
    assert window.preset_table.item(0, 3).text() == "Solo"
    assert (
        window.preset_table.cellWidget(0, 3).text() == "Solo <span style='color: #f59e0b;'>★</span>"
    )
    assert window.preset_table.item(0, 3).toolTip() == "Solo snapshot"
    assert window.preset_table.item(0, 4).text() == "+11.1"
    assert window.preset_table.item(0, 5).text() == "Clean"
    assert window.preset_table.item(0, 6).text() == "0"
    assert window.preset_table.item(0, 7).text() == "Rhythm"
    assert window.preset_table.item(0, 8).text() == "-2.0"
    assert window.preset_table.item(0, 4).foreground().color().name() == "#15803d"
    assert window.preset_table.item(0, 8).foreground().color().name() == "#b91c1c"
    assert window.preset_table.columnWidth(0) == window.style().pixelMetric(
        QStyle.PixelMetric.PM_IndicatorWidth
    ) + 2 * window.style().pixelMetric(QStyle.PixelMetric.PM_CheckBoxLabelSpacing)
    assert (
        window.preset_table.horizontalHeader().sectionResizeMode(0) == QHeaderView.ResizeMode.Fixed
    )
    assert all(
        window.preset_table.horizontalHeader().sectionResizeMode(column)
        == QHeaderView.ResizeMode.Interactive
        for column in range(1, window.preset_table.columnCount())
    )

    window.close()


def test_input_browse_prompts_before_discarding_preset_adjustments(monkeypatch, app) -> None:
    window = MainWindow()
    window.input_path.setText("/tmp/original.hls")
    window.preset_table.insertRow(0)
    selected = QTableWidgetItem()
    selected.setCheckState(Qt.CheckState.Checked)
    window.preset_table.setItem(0, 0, selected)
    window.preset_table.setItem(0, 1, QTableWidgetItem("02B"))
    window.preset_table.setItem(0, 2, QTableWidgetItem("Song"))
    window._clear_preset_adjustments(0)
    window.update_progress(
        ProgressEvent("log", message="[GAIN] 02B Solo | 0.0 dB -> 1.0 dB (Delta: +1.0 dB)")
    )
    prompts = []
    answers = iter([QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Discard])
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: ("/tmp/new.hlx", ""),
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args: prompts.append(args) or next(answers),
    )

    window.browse_input()

    assert window.input_path.text() == "/tmp/original.hls"
    assert window.preset_table.item(0, 4).text() == "+1.0"

    window.browse_input()

    assert window.input_path.text() == "/tmp/new.hlx"
    assert window.preset_table.rowCount() == 0
    assert not window._adjusted_presets
    assert len(prompts) == 2
    assert prompts[0][1] == "Discard preset table changes"

    window.close()


def test_input_browse_does_not_prompt_for_clean_preset_table(monkeypatch, app) -> None:
    window = MainWindow()
    window.input_path.setText("/tmp/original.hls")
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: ("/tmp/new.hlx", ""),
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args: pytest.fail("clean preset table should not prompt"),
    )

    window.browse_input()

    assert window.input_path.text() == "/tmp/new.hlx"

    window.close()


def test_closing_main_window_can_cancel_discarding_manual_table_changes(
    monkeypatch, app
) -> None:
    window = MainWindow()
    window.preset_table.insertRow(0)
    window.preset_table.setItem(0, 1, QTableWidgetItem("02B"))
    window.preset_table.setItem(0, 2, QTableWidgetItem("Song"))
    window._clear_preset_adjustments(0)
    window._reset_preset_table_modified()
    window.manual_adjustments.setChecked(True)
    prompts = []
    quit_requests = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args: prompts.append(args) or QMessageBox.StandardButton.Cancel,
    )
    monkeypatch.setattr(QApplication, "quit", lambda: quit_requests.append(True))

    window.preset_table.item(0, 2).setText("Song 2")
    event = QCloseEvent()
    window.closeEvent(event)

    assert not event.isAccepted()
    assert window._preset_table_modified
    assert quit_requests == []
    assert prompts[0][1] == "Discard preset table changes"

    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)
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
    window._clear_preset_adjustments(0)
    window._set_snapshot_names(0, ("Clean", "Solo"))

    window.update_progress(ProgressEvent("log", message="[GAIN] 02B Clean | bad LUFS"))

    assert window.preset_table.item(0, 3).text() == "Clean"
    assert window.preset_table.item(0, 4).text() == "⚠️"
    assert window.preset_table.item(0, 4).font().pointSize() > app.font().pointSize()
    assert "unusable LUFS" in window.preset_table.item(0, 4).toolTip()
    assert window.preset_table.item(0, 5).text() == "Solo"
    assert (
        window.preset_table.cellWidget(0, 5).text() == "Solo <span style='color: #f59e0b;'>★</span>"
    )
    assert window.preset_table.item(0, 5).toolTip() == "Solo snapshot"
    assert all(
        window.preset_table.item(0, column).background().color().name() == "#fee2e2"
        for column in range(window.preset_table.columnCount())
    )

    window.close()


def test_snapshot_count_widget_redraws_columns_and_preserves_loaded_names(app) -> None:
    window = MainWindow()
    window.preset_table.insertRow(0)
    window.preset_table.setItem(0, 2, QTableWidgetItem("Song"))
    window._clear_preset_adjustments(0)
    window._set_snapshot_names(0, ("One", "Two", "Three", "Four", "Five", "Six"))

    window.snapshot_count_input.setValue(6)

    assert window.snapshot_count == 6
    assert window.preset_table.columnCount() == 15
    assert window.preset_table.item(0, 13).text() == "Six"
    argv = window._build_argv()
    assert argv[argv.index("--snapshot-count") + 1] == "6"

    window.snapshot_count_input.setValue(2)
    window.snapshot_count_input.setValue(6)

    assert window.preset_table.item(0, 13).text() == "Six"

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
    window._clear_preset_adjustments(0)

    window.update_progress(ProgressEvent("log", message="[GAIN] 02B Clean | bad LUFS"))
    assert window.preset_table.item(0, 0).background().color().name() == "#fee2e2"

    monkeypatch.setattr(QMessageBox, "critical", lambda *args: None)

    class FailingProfile:
        @staticmethod
        def create_patch_file_handler(root):
            class FailingHandler:
                @staticmethod
                def validate_input(path):
                    raise ValueError("Invalid input")

            return FailingHandler()

    monkeypatch.setattr(main_window, "get_device_profile", lambda device: FailingProfile())
    window.input_path.setText("missing.hls")
    window.load_assignments()
    assert window.preset_table.item(0, 0).background().style() == Qt.BrushStyle.NoBrush

    window.update_progress(ProgressEvent("log", message="[GAIN] 02B Clean | bad LUFS"))
    monkeypatch.setattr(main_window, "parse_args", lambda argv: object())
    monkeypatch.setattr(main_window, "apply_config", lambda args: args)
    monkeypatch.setattr(main_window, "request_from_args", lambda args: _request())
    monkeypatch.setattr(main_window.NormalizationWorker, "start", lambda self: None)
    monkeypatch.setattr(window, "_prompt_save_before_normalization", lambda: True)
    window.start_normalization()
    assert window.preset_table.item(0, 0).background().style() == Qt.BrushStyle.NoBrush

    window.worker_finished()
    window.close()


def test_implausible_gain_warning_is_marked_as_bad_lufs(monkeypatch, app) -> None:
    window = MainWindow()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)
    window.preset_table.insertRow(0)
    selected = QTableWidgetItem()
    selected.setCheckState(Qt.CheckState.Checked)
    window.preset_table.setItem(0, 0, selected)
    window.preset_table.setItem(0, 1, QTableWidgetItem("02B"))
    window._clear_preset_adjustments(0)

    window.update_progress(
        ProgressEvent(
            "log",
            message="[GAIN] 02B Solo (S) | bad LUFS (Implausible output gain 21.9 dB)",
        )
    )

    assert window.preset_table.item(0, 3).text() == "Solo"
    assert (
        window.preset_table.cellWidget(0, 3).text() == "Solo <span style='color: #f59e0b;'>★</span>"
    )
    assert window.preset_table.item(0, 4).text() == "⚠️"

    window.close()


def test_gui_always_requests_bad_lufs_tolerance(app) -> None:
    window = MainWindow()

    assert not hasattr(window, "ignore_bad_lufs")
    assert not hasattr(window, "limit")
    assert "--limit" not in window._build_argv()
    assert "--ignore-bad-lufs" not in window._build_argv()
    assert "--no-ignore-bad-lufs" not in window._build_argv()

    window.close()


def test_retained_csv_path_and_colored_timestamped_log_are_displayed(app) -> None:
    window = MainWindow()
    window.update_progress(
        ProgressEvent(
            "temp_retained",
            message="Kept temporary CSV",
            path="/tmp/matchpatch/lufs_analysis.csv",
        )
    )

    assert window.retained_csv.text() == "/tmp/matchpatch/lufs_analysis.csv"
    assert not window.retained_csv.isHidden()
    assert "Kept temporary CSV" not in window.log.toHtml()
    window.log_level.setCurrentText("Debug")
    html = window.log.toHtml()
    assert "Kept temporary CSV" in html
    assert "DEBUG" in html
    assert "#" in html

    window.close()


def test_completion_enables_save_without_redundant_popup(tmp_path, monkeypatch, app) -> None:
    window = MainWindow()
    window.input_path.setText(str(tmp_path / "input.hls"))
    window._loaded_input_path = window.input_path.text()
    popups = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: popups.append(args))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)

    window.normalization_completed(
        NormalizationResult(None, tmp_path, tmp_path / "lufs_analysis.csv")
    )

    assert popups == []
    assert window.save_action.isEnabled()
    assert "save the active file" in window.log.toHtml()

    window.close()


def test_loaded_file_updates_window_title_and_save_as_state(app) -> None:
    window = MainWindow()
    assert not window.start_button.isEnabled()
    window.input_path.setText("/tmp/input.hlx")

    window.load_assignments()

    assert window.windowTitle() == "input.hlx"
    assert window.save_as_action.isEnabled()
    assert window.start_button.isEnabled()
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


def test_output_save_picker_uses_save_button(monkeypatch, app) -> None:
    window = MainWindow()
    window.input_path.setText("/tmp/input.hls")
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
            return ["/tmp/output.hls"]

    monkeypatch.setattr(main_window, "QFileDialog", FileDialog)

    window.browse_output()

    assert window.output_path.text() == "/tmp/output.hls"
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
    measurement_path.touch()
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
    monkeypatch.setattr(main_window, "parse_args", lambda argv: object())
    monkeypatch.setattr(main_window, "apply_config", lambda args: args)
    monkeypatch.setattr(main_window, "request_from_args", lambda args: request)
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


def test_cancellation_sets_status_without_redundant_popup(monkeypatch, app) -> None:
    window = MainWindow()
    popups = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: popups.append(args))

    window.normalization_cancelled()

    assert popups == []
    assert window.phase.text() == "Normalization cancelled by user"
    assert "Normalization cancelled by user" in window.log.toHtml()
    assert main_window.PROCESSING_DOT_RED in window.processing_dot.styleSheet()

    window.worker_finished()

    assert main_window.PROCESSING_DOT_RED in window.processing_dot.styleSheet()

    window.close()


def test_bad_lufs_is_logged_as_warning(app) -> None:
    window = MainWindow()
    window.update_progress(ProgressEvent("log", message="[GAIN] 02B Clean | bad LUFS"))

    assert "WARNING" in window.log.toHtml()

    window.close()


def test_worker_import_confirmation_blocks_until_answered(app) -> None:
    worker = NormalizationWorker(
        NormalizationRequest(
            device="helix",
            input_path=Path("input.hls"),
            backend="loopback",
            windows_python=str(DEFAULT_WINDOWS_PYTHON),
            reference_di=DEFAULT_REFERENCE_DI,
        )
    )
    requests = []
    answers = []
    worker.import_requested.connect(requests.append)
    thread = threading.Thread(
        target=lambda: answers.append(
            worker._confirm_import(
                ImportRequest("measurement", "Line 6 Helix", Path("measurement.hls"))
            )
        )
    )
    thread.start()

    for _ in range(100):
        app.processEvents()
        if requests:
            break
        time.sleep(0.01)

    assert requests
    assert thread.is_alive()
    worker.answer_import(True)
    thread.join()
    assert answers == [True]


def test_worker_thread_exits_without_processing_gui_events(monkeypatch, app) -> None:
    window = MainWindow()
    request = _request()
    monkeypatch.setattr(main_window, "parse_args", lambda argv: object())
    monkeypatch.setattr(main_window, "apply_config", lambda args: args)
    monkeypatch.setattr(main_window, "request_from_args", lambda args: request)
    monkeypatch.setattr(
        gui_worker,
        "normalize_presets",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("cancelled")),
    )
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: None)

    window.start_normalization()
    worker = window.worker

    assert worker is not None
    assert worker.wait(1000)
    assert isValid(worker)

    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(worker)
    window.close()


def test_worker_completion_drains_queued_progress_updates(monkeypatch, app) -> None:
    window = MainWindow()
    window.show()
    monkeypatch.setattr(main_window, "parse_args", lambda argv: object())
    monkeypatch.setattr(main_window, "apply_config", lambda args: args)
    monkeypatch.setattr(main_window, "request_from_args", lambda args: _request())

    def emit_progress(*args, on_progress, **kwargs):
        for snapshot in range(1, 13):
            on_progress(
                ProgressEvent(
                    "snapshot_started",
                    device_patch="01A",
                    preset_index=1,
                    preset_total=1,
                    snapshot=snapshot,
                    snapshot_total=12,
                    reference_lufs=-18.0,
                    lufs=-16.0,
                )
            )
        return NormalizationResult(Path("/tmp/adjusted.hls"), None)

    monkeypatch.setattr(gui_worker, "normalize_presets", emit_progress)

    for _ in range(30):
        window.start_normalization()
        worker = window.worker
        assert worker is not None
        assert worker.wait(1000)
        while window.worker is worker:
            app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert not isValid(worker)

    app.processEvents()
    assert window.preset_progress.value() == 12
    window.close()


def test_worker_emits_cancelled_instead_of_failed_after_cancellation(monkeypatch, app) -> None:
    worker = NormalizationWorker(object())
    cancelled = []
    failures = []
    monkeypatch.setattr(
        gui_worker,
        "normalize_presets",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("cancelled")),
    )
    worker.cancelled.connect(lambda: cancelled.append(True))
    worker.failed.connect(failures.append)

    worker.cancel()
    worker.run()

    assert cancelled == [True]
    assert failures == []


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


def test_closing_main_window_is_ignored_when_cancellation_is_declined(monkeypatch, app) -> None:
    window = MainWindow()
    worker = Mock()
    window.worker = worker
    quit_requests = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    monkeypatch.setattr(QApplication, "quit", lambda: quit_requests.append(True))
    event = QCloseEvent()

    window.closeEvent(event)

    assert not event.isAccepted()
    worker.cancel.assert_not_called()
    assert quit_requests == []

    window.worker = None
    window.close()


def test_closing_main_window_cancels_measurement_when_confirmation_is_accepted(
    monkeypatch, app
) -> None:
    window = MainWindow()
    worker = Mock()
    window.worker = worker
    quit_requests = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QApplication, "quit", lambda: quit_requests.append(True))
    event = QCloseEvent()

    window.closeEvent(event)

    assert event.isAccepted()
    worker.cancel.assert_called_once_with()
    assert quit_requests == [True]


def test_closing_main_window_explicitly_quits_application(monkeypatch, app) -> None:
    window = MainWindow()
    quit_requests = []
    monkeypatch.setattr(QApplication, "quit", lambda: quit_requests.append(True))

    window.close()

    assert quit_requests == [True]
