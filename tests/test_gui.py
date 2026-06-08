from __future__ import annotations

import os
import threading
import time
import tomllib
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QPoint
from PySide6.QtGui import QCloseEvent, QColor, QPalette, QPixmap, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
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
    QWidget,
)
from shiboken6 import isValid

from matchpatch.gui import main_window
from matchpatch.gui import worker as gui_worker
from matchpatch.gui.main_window import MainWindow
from matchpatch.gui.worker import NormalizationWorker
from matchpatch.measurement_optimizer import OptimizationProgress, StabilityStatistics
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


def _write_silent_wav(path: Path, *, seconds: float, sample_rate: int = 48_000) -> None:
    frames = round(seconds * sample_rate)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\0\0" * frames * 2)


def _mock_single_hlx_handler(
    monkeypatch,
    *,
    name: str = "example",
    snapshot_names: tuple[str, ...] = ("Clean", "Solo"),
    snapshot_output_levels: tuple[tuple[float, ...], ...] = ((0.0,), (-3.5, -4.0)),
    assignments: list[SimpleNamespace] | None = None,
) -> None:
    if assignments is None:
        assignments = [
            SimpleNamespace(
                device_patch="01A",
                name=name,
                snapshot_names=snapshot_names,
                snapshot_output_levels=snapshot_output_levels,
            )
        ]

    class Handler:
        @staticmethod
        def validate_input(path):
            return None

        @staticmethod
        def list_assignments(path):
            return assignments

        @staticmethod
        def metadata(path):
            return {"file_type": "hlx"}

    class Profile:
        @staticmethod
        def create_patch_file_handler(root):
            return Handler()

    monkeypatch.setattr(main_window, "get_device_profile", lambda device: Profile())


class _FakeSaveChangesMessageBox:
    StandardButton = QMessageBox.StandardButton
    ButtonRole = QMessageBox.ButtonRole
    next_click = QMessageBox.StandardButton.Cancel
    instances = []

    def __init__(self, parent=None):
        self.parent = parent
        self.title = ""
        self.text = ""
        self.buttons = []
        self.default_button = None
        self._clicked_button = None
        _FakeSaveChangesMessageBox.instances.append(self)

    def setWindowTitle(self, title):
        self.title = title

    def setText(self, text):
        self.text = text

    def addButton(self, button, role=None):
        button_ref = object()
        self.buttons.append((button, role, button_ref))
        return button_ref

    def setDefaultButton(self, button):
        self.default_button = button

    def exec(self):
        for button, _role, button_ref in self.buttons:
            if button == self.next_click:
                self._clicked_button = button_ref
                break
        return 0

    def clickedButton(self):
        return self._clicked_button


def test_save_as_icon_uses_standard_save_disk_with_drawn_overlay(app) -> None:
    image = main_window._save_as_icon().pixmap(56, 56).toImage()
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


def test_save_measurement_icon_draws_disk_and_chart_overlay(app) -> None:
    image = main_window._save_measurement_icon().pixmap(56, 56).toImage()
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
        main_window._record_icon(recording=False).pixmap(56, 56).toImage().pixelColor(x, y).name()
        for x in range(56)
        for y in range(56)
    }
    record_on_colors = {
        main_window._record_icon(recording=True).pixmap(56, 56).toImage().pixelColor(x, y).name()
        for x in range(56)
        for y in range(56)
    }
    speaker_off_colors = {
        main_window._speaker_icon(enabled=False).pixmap(56, 56).toImage().pixelColor(x, y).name()
        for x in range(56)
        for y in range(56)
    }
    speaker_on_colors = {
        main_window._speaker_icon(enabled=True).pixmap(56, 56).toImage().pixelColor(x, y).name()
        for x in range(56)
        for y in range(56)
    }

    assert "#9ca3af" in record_off_colors
    assert "#dc2626" in record_on_colors
    assert "#9ca3af" in speaker_off_colors
    assert "#6b7280" in speaker_off_colors
    assert "#2563eb" in speaker_on_colors


def test_main_window_starts_with_registry_device_and_hardware(app) -> None:
    window = MainWindow()

    assert window.device.currentData() == "helix"
    assert window.backend.currentText() == "hardware"
    assert isinstance(window.advanced, QWidget)
    assert not isinstance(window.advanced, QGroupBox)
    assert not window.advanced.isHidden()
    assert window.advanced_button.isChecked()
    assert [window.advanced_tabs.tabText(index) for index in range(7)] == [
        "Device",
        "Files",
        "Measurement",
        "LUFS",
        "Misc",
        "Meta Data",
        "Log",
    ]
    assert window.advanced_tabs.widget(0).isAncestorOf(window.backend)
    assert not window.advanced_tabs.widget(1).isAncestorOf(window.backend)
    assert window.advanced_tabs.widget(1).isAncestorOf(window.config_path)
    assert window.advanced_tabs.widget(1).isAncestorOf(window.custom_adjustments_path)
    assert window.advanced_tabs.widget(1).isAncestorOf(window.reference_di)
    assert window.advanced_tabs.widget(1).isAncestorOf(window.keep_temp)
    assert not window.advanced_tabs.widget(2).isAncestorOf(window.config_path)
    assert not window.advanced_tabs.widget(2).isAncestorOf(window.custom_adjustments_path)
    assert not window.advanced_tabs.widget(2).isAncestorOf(window.reference_di)
    assert not window.advanced_tabs.widget(2).isAncestorOf(window.keep_temp)
    assert window.advanced_tabs.widget(2).isAncestorOf(window.measurement_parameter_preset)
    assert window.advanced_tabs.widget(2).isAncestorOf(window.apply_measurement_parameters_button)
    assert window.advanced_tabs.widget(2).isAncestorOf(window.pre_roll)
    assert window.advanced_tabs.widget(2).isAncestorOf(window.post_roll)
    assert window.advanced_tabs.widget(2).isAncestorOf(window.round_trip_latency)
    assert window.advanced_tabs.widget(2).isAncestorOf(window.preset_wait)
    assert window.advanced_tabs.widget(2).isAncestorOf(window.snapshot_wait)
    assert window.advanced_tabs.widget(2).isAncestorOf(window.measurement_wait)
    assert window.advanced_tabs.widget(2).isAncestorOf(window.measurement_time_estimate)
    assert window.advanced_tabs.widget(2).isAncestorOf(window.determine_parameters_button)
    measurement_labels = {
        label.text() for label in window.advanced_tabs.widget(2).findChildren(QLabel)
    }
    assert "Termination tolerance" not in measurement_labels
    assert "Stability tolerance" not in measurement_labels
    assert "Stability runs" not in measurement_labels
    assert not window.advanced_tabs.widget(2).isAncestorOf(window.snapshot_count_input)
    assert not window.advanced_tabs.widget(2).isAncestorOf(window.target_lufs)
    assert not window.advanced_tabs.widget(2).isAncestorOf(window.solo_gain_bump_db)
    assert not window.advanced_tabs.widget(2).isAncestorOf(window.solo_regex)
    assert window.advanced_tabs.widget(3).isAncestorOf(window.target_lufs)
    assert window.advanced_tabs.widget(3).isAncestorOf(window.solo_gain_bump_db)
    assert window.advanced_tabs.widget(3).isAncestorOf(window.solo_regex)
    assert window.advanced_tabs.widget(3).isAncestorOf(window.ignore_snapshot_regex)
    lufs_group_titles = {
        group.title() for group in window.advanced_tabs.widget(3).findChildren(QGroupBox)
    }
    assert "Snapshot name regex" in lufs_group_titles
    lufs_labels = {label.text() for label in window.advanced_tabs.widget(3).findChildren(QLabel)}
    assert "Solo" in lufs_labels
    assert "Ignored" in lufs_labels
    assert "Ignore snapshot" not in lufs_labels
    assert window.advanced_tabs.widget(4).isAncestorOf(window.snapshot_count_input)
    assert not isinstance(window.presets, QGroupBox)
    assert window.measurement_parameter_preset.currentText() == "Default"
    assert window.pre_roll.text() == "0.3"
    assert window.post_roll.text() == "0.5"
    assert window.snapshot_wait.text() == "1.0"
    assert window.measurement_wait.text() == "0.6"
    assert window.preset_wait.text() == "1.3"
    assert window.round_trip_latency.text() == "0.001"
    expected_seconds = 1.0 + 0.6 + 0.3 + 0.5 + 0.001 + 1.3 / 4
    expected_seconds += main_window._reference_audio_seconds(DEFAULT_REFERENCE_DI)
    assert window.measurement_time_estimate.text() == (
        "Estimated measurement time per snapshot: "
        f"{main_window._format_short_seconds(expected_seconds)} (1 preset, 4 snapshots)"
    )
    assert window.presets.layout().contentsMargins().isNull()
    assert window.scroll_area.frameShape() == main_window.QFrame.Shape.NoFrame
    assert window.measurement_panel_separator.frameShape() == main_window.QFrame.Shape.HLine
    assert window.measurement_panel_separator.frameShadow() == main_window.QFrame.Shadow.Sunken
    assert not window.presets.isHidden()
    assert not window.preset_empty_state.isHidden()
    assert "border: none" in window.preset_empty_state.styleSheet()
    assert window.preset_header.isHidden()
    assert window.preset_table.isHidden()
    assert not window.preset_empty_logo.pixmap().isNull()
    assert window.preset_empty_logo.pixmap().size() == main_window.QSize(360, 360)
    assert window.preset_empty_logo.size() == main_window.QSize(360, 360)
    assert window.preset_empty_state.layout().itemAt(1).alignment() & Qt.AlignmentFlag.AlignHCenter
    assert window.preset_empty_file_dialog_title.text() == "Open setlist/preset file"
    assert window.preset_empty_file_dialog_title.alignment() == Qt.AlignmentFlag.AlignCenter
    assert window.preset_empty_file_dialog_title.font().pointSize() >= app.font().pointSize() + 2
    assert isinstance(window.preset_empty_file_dialog, QFileDialog)
    assert window.preset_empty_file_dialog.acceptMode() == QFileDialog.AcceptMode.AcceptOpen
    assert window.preset_empty_file_dialog.fileMode() == QFileDialog.FileMode.ExistingFile
    assert window.preset_empty_file_dialog.nameFilters() == ["Patches (*.hls *.hlx)"]
    assert window.preset_empty_file_dialog.testOption(QFileDialog.Option.DontUseNativeDialog)
    assert window.preset_empty_file_dialog.parent() is window.preset_empty_state
    assert isinstance(window.preset_advanced_splitter, QSplitter)
    assert window.preset_advanced_splitter.orientation() == Qt.Orientation.Horizontal
    assert not window.preset_advanced_splitter.isHidden()
    assert (
        window.preset_advanced_splitter.sizePolicy().verticalPolicy()
        == QSizePolicy.Policy.Expanding
    )
    assert window.preset_advanced_splitter.widget(0) is window.presets
    assert window.preset_advanced_splitter.widget(1) is window.advanced
    assert window.content.layout().indexOf(window.preset_advanced_splitter) == 0
    assert not window.findChildren(QMenuBar)
    toolbar = window.findChildren(main_window.QToolBar)[0]
    toolbar_actions = [
        action for action in toolbar.actions() if action.text() and not action.isSeparator()
    ]
    assert [action.text() for action in toolbar_actions] == [
        "Open",
        "Save",
        "Save As",
        "Save Measurement File",
        "Help",
        "About",
    ]
    assert toolbar.actions().index(window.normalization_separator_action) == (
        toolbar.actions().index(window.save_measurement_action) + 1
    )
    assert toolbar.actions().index(window.save_measurement_action) == (
        toolbar.actions().index(window.save_as_action) + 1
    )
    assert toolbar.actions().index(window.normalization_action) == (
        toolbar.actions().index(window.normalization_separator_action) + 1
    )
    assert toolbar.actions().index(window.help_spacer_action) < toolbar.actions().index(
        window.help_action
    )
    assert toolbar.actions().index(window.device_action) == (
        toolbar.actions().index(window.help_spacer_action) + 1
    )
    assert toolbar.actions().index(window.advanced_action) == (
        toolbar.actions().index(window.play_recorded_output_action) + 1
    )
    assert toolbar.actions().index(window.record_output_action) == (
        toolbar.actions().index(window.device_action) + 1
    )
    assert toolbar.actions().index(window.play_recorded_output_action) == (
        toolbar.actions().index(window.record_output_action) + 1
    )
    help_spacer = toolbar.widgetForAction(window.help_spacer_action)
    assert help_spacer is not None
    assert help_spacer.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding
    assert toolbar.widgetForAction(window.device_action) is window.device
    assert toolbar.widgetForAction(window.record_output_action) is window.record_output_button
    assert (
        toolbar.widgetForAction(window.play_recorded_output_action)
        is window.play_recorded_output_button
    )
    assert toolbar.widgetForAction(window.advanced_action) is window.advanced_button
    assert toolbar.widgetForAction(window.normalization_action) is window.start_cancel_stack
    assert toolbar.iconSize() == main_window.QSize(20, 20)
    assert toolbar.contentsMargins().isNull()
    assert window.start_cancel_stack.currentWidget() is window.start_button
    assert window.start_button.text() == ""
    assert window.advanced_button.text() == ""
    assert window.record_output_button.text() == ""
    assert window.play_recorded_output_button.text() == ""
    assert not window.start_button.icon().isNull()
    assert not window.record_output_button.icon().isNull()
    assert not window.play_recorded_output_button.icon().isNull()
    assert not window.advanced_button.icon().isNull()
    assert window.start_button.iconSize() == toolbar.iconSize()
    assert window.record_output_button.iconSize() == toolbar.iconSize()
    assert window.play_recorded_output_button.iconSize() == toolbar.iconSize()
    assert window.advanced_button.iconSize() == toolbar.iconSize()
    assert isinstance(window.start_button, main_window.QToolButton)
    assert isinstance(window.cancel_button, main_window.QToolButton)
    assert isinstance(window.record_output_button, main_window.QToolButton)
    assert isinstance(window.play_recorded_output_button, main_window.QToolButton)
    assert isinstance(window.advanced_button, main_window.QToolButton)
    assert window.start_button.autoRaise()
    assert window.cancel_button.autoRaise()
    assert window.record_output_button.autoRaise()
    assert window.play_recorded_output_button.autoRaise()
    assert window.advanced_button.autoRaise()
    assert window.start_button.toolTip().startswith("Start")
    assert window.record_output_button.toolTip().startswith("Record")
    assert window.play_recorded_output_button.toolTip().startswith("Play")
    assert window.advanced_button.toolTip().startswith("Show")
    assert window.start_button.width() == window.start_button.height()
    assert window.cancel_button.width() == window.cancel_button.height()
    assert window.record_output_button.width() == window.record_output_button.height()
    assert window.play_recorded_output_button.width() == window.play_recorded_output_button.height()
    assert window.advanced_button.width() == window.advanced_button.height()
    assert window.start_button.size() == window.cancel_button.size()
    assert window.record_output_button.size() == window.start_button.size()
    assert window.play_recorded_output_button.size() == window.start_button.size()
    assert window.advanced_button.size() == window.start_button.size()
    assert window.start_cancel_stack.size() == window.start_button.size()
    assert toolbar.minimumHeight() == window.advanced_button.height() + 4
    assert toolbar.maximumHeight() == window.advanced_button.height() + 4
    for action in (
        window.open_action,
        window.save_action,
        window.save_as_action,
        window.save_measurement_action,
        window.help_action,
        window.about_action,
    ):
        button = toolbar.widgetForAction(action)
        assert button is not None
        assert button.size() == window.start_button.size()
    assert window.open_action.isEnabled()
    assert not window.save_action.isEnabled()
    assert not window.save_as_action.isEnabled()
    assert not window.save_measurement_action.isEnabled()
    assert not window.start_button.isEnabled()
    assert not window.record_output_button.isEnabled()
    assert window.record_output_button.isChecked()
    assert not window.play_recorded_output_button.isChecked()
    assert window.log_level.currentText() == "Info"
    assert window.metadata_text.toPlainText() == "{}"
    assert window.device_stack.count() == 1
    assert window.device_panels["helix"].audio_group.isEnabled()
    assert window.progress_group.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Maximum
    assert not window.statusBar().isHidden()
    assert not window.statusBar().isSizeGripEnabled()
    assert window.phase.parent() is window.statusBar()
    assert window.processing_dot.parent() is window.statusBar()
    assert window.progress_group.layout().itemAt(0).widget() is window.measurement_panel_separator
    assert window.progress_group.layout().itemAt(1).widget() is window.current
    assert window.progress_group.layout().itemAt(3).widget() is window.preset_progress
    assert window.progress_group.isHidden()
    assert not window.processing_dot.isHidden()
    assert not window._processing_dot_green
    assert not hasattr(window, "ignore_bad_lufs")
    assert window.preset_table.verticalHeader().isHidden()
    assert not window.preset_table.wordWrap()
    assert window.preset_table.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Expanding
    assert window.advanced_tabs.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Expanding
    assert (
        window.preset_table_note.text()
        == "Only non-empty presets are listed. Solo snapshots are marked with a "
        "<span style='color: #f59e0b;'>★</span>."
    )
    assert window.preset_table_note.textFormat() == Qt.TextFormat.RichText
    assert window.preset_csv_label.text() == "CSV: "
    assert window.preset_csv_controls.layout().indexOf(window.preset_csv_label) >= 0
    assert window.preset_csv_controls.layout().indexOf(window.load_csv_button) >= 0
    assert window.preset_csv_controls.layout().indexOf(window.save_csv_button) >= 0
    assert not window.load_csv_button.isEnabled()
    assert not window.save_csv_button.isEnabled()
    assert window.load_csv_button.text() == ""
    assert window.save_csv_button.text() == ""
    assert not window.save_as_action.icon().isNull()
    assert not window.save_csv_button.icon().isNull()
    assert window.save_csv_button.icon().cacheKey() == window.save_as_action.icon().cacheKey()
    assert window.select_diff_button.text() == "Select changed"
    assert not window.select_diff_button.icon().isNull()
    assert window.select_diff_button.isHidden()
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


def test_initial_empty_state_reserves_loaded_preset_table_size(monkeypatch, app, tmp_path) -> None:
    initial_window = MainWindow()
    initial_window.show()
    app.processEvents()
    initial_window._resize_to_initial_content()
    app.processEvents()
    initial_size = initial_window.size()
    initial_window.close()

    loaded_window = MainWindow()
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
                    device_patch=f"{row + 1:02d}A",
                    name=f"Preset {row + 1}",
                    snapshot_names=("Clean", "Solo"),
                )
                for row in range(main_window.ContentHeightTableWidget.MAX_VISIBLE_ROWS)
            ]

        @staticmethod
        def metadata(path):
            return {"file_type": "hls"}

    class Profile:
        @staticmethod
        def create_patch_file_handler(root):
            return Handler()

    monkeypatch.setattr(main_window, "get_device_profile", lambda device: Profile())
    loaded_window.show()
    loaded_window.input_path.setText(str(path))
    loaded_window.load_assignments()
    app.processEvents()
    loaded_window._resize_to_initial_content()
    app.processEvents()

    assert loaded_window.preset_empty_state.isHidden()
    assert not loaded_window.preset_table.isHidden()
    assert not loaded_window.select_diff_button.isHidden()
    assert initial_size == loaded_window.size()

    loaded_window.close()


def test_window_shrinks_when_advanced_side_pane_is_hidden(app) -> None:
    window = MainWindow()
    window._show_loaded_preset_state(single_preset=True)
    window.show()
    app.processEvents()

    expanded_height = window.height()
    window.advanced_button.setChecked(False)
    app.processEvents()

    assert window.height() < expanded_height

    window.close()


def test_maximized_window_does_not_resize_when_advanced_side_pane_toggles(monkeypatch, app) -> None:
    window = MainWindow()
    window.show()
    app.processEvents()
    window.resize(1200, 800)
    app.processEvents()
    initial_size = window.size()

    monkeypatch.setattr(window, "isMaximized", lambda: True)

    window.advanced_button.setChecked(False)
    app.processEvents()

    assert window.size() == initial_size
    assert window.advanced.isHidden()

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
    window._show_loaded_preset_state(single_preset=False)
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


def test_single_preset_load_displays_presets_panel_with_instruction_label(monkeypatch, app) -> None:
    window = MainWindow()
    _mock_single_hlx_handler(monkeypatch, name="Lead", snapshot_names=("Clean", "Solo"))
    window.show()
    app.processEvents()

    window.input_path.setText("/tmp/example.hlx")
    window.load_assignments()
    app.processEvents()

    assert not window.presets.isHidden()
    assert not window.preset_advanced_splitter.isHidden()
    assert not window.preset_table.isHidden()
    assert window.preset_table.isColumnHidden(0)
    assert window.single_slot.isHidden()
    assert window.preset_table_note.isHidden()
    assert window.select_diff_button.isHidden()
    assert not window.preset_csv_controls.isHidden()
    assert window.load_csv_button.isEnabled()
    assert window.save_csv_button.isEnabled()
    assert window.preset_table.rowCount() == 1
    assert window.preset_table.item(0, 1).text() == ""
    assert window.preset_table.item(0, 2).text() == "Lead"
    assert window.preset_table.item(0, 3).text() == "Clean"
    assert window.preset_table.item(0, 4).text() == "0.0"
    assert window.preset_table.item(0, 6).text() == "Solo"
    assert window.preset_table.item(0, 7).text() == "-3.5, -4.0"
    assert window.preset_table.item(0, 1).flags() & Qt.ItemFlag.ItemIsEditable
    assert window.preset_hint.height() == window.preset_hint.sizeHint().height()
    assert window.preset_hint.text() == (
        "Enter the temporary Helix slot used during measurement in the Preset column."
    )

    window.close()


def test_empty_single_preset_load_still_displays_table(monkeypatch, app) -> None:
    window = MainWindow()
    _mock_single_hlx_handler(monkeypatch, assignments=[])
    window.input_path.setText("/tmp/empty.hlx")

    window.load_assignments()

    assert not window.preset_table.isHidden()
    assert window.preset_table.isColumnHidden(0)
    assert window.preset_table_note.isHidden()
    assert window.load_csv_button.isEnabled()
    assert window.save_csv_button.isEnabled()
    assert window.preset_table.rowCount() == 1
    assert window.preset_table.item(0, 1).text() == ""
    assert window.preset_table.item(0, 2).text() == "empty"

    window.close()


def test_single_preset_uses_table_preset_id_for_normalization(monkeypatch, app) -> None:
    window = MainWindow()
    _mock_single_hlx_handler(monkeypatch)
    window.input_path.setText("/tmp/example.hlx")
    window.load_assignments()

    window.preset_table.item(0, 1).setText("12a")

    argv = window._build_argv()
    assert argv[argv.index("--preset-set") + 1] == "12A"

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
    assert adjustment.data(main_window.ADJUSTMENT_VALUE_ROLE) is None
    assert 0 not in window._table_adjustments().gain_deltas["01A"]

    window.close()


def test_all_ignored_presets_are_excluded_from_normalization_request(app) -> None:
    window = MainWindow()
    window.snapshot_count_input.setValue(2)
    for row, preset_id in enumerate(("02B", "02C")):
        window.preset_table.insertRow(row)
        selected = QTableWidgetItem()
        selected.setCheckState(Qt.CheckState.Checked)
        window.preset_table.setItem(row, 0, selected)
        window.preset_table.setItem(row, 1, QTableWidgetItem(preset_id))
        window.preset_table.setItem(row, 2, QTableWidgetItem("Song"))
        window._clear_preset_adjustments(row)

    window._set_ignored_snapshot_highlight(0, 0, True)
    window._set_ignored_snapshot_highlight(0, 1, True)
    window._set_ignored_snapshot_highlight(1, 0, True)

    argv = window._build_argv()

    assert argv[argv.index("--preset-set") + 1] == "02C"

    window.close()


def test_single_preset_run_warns_when_preset_id_is_missing(monkeypatch, app) -> None:
    window = MainWindow()
    _mock_single_hlx_handler(monkeypatch)
    window.input_path.setText("/tmp/example.hlx")
    window.load_assignments()
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))

    window.start_normalization()

    assert len(warnings) == 1
    assert warnings[0][1] == "Preset ID required"
    assert window.preset_table.item(0, 1).data(main_window.PRESET_TABLE_ATTENTION_ROLE)
    assert window.worker is None
    assert window.start_button.isEnabled()

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
    assert not window.preset_advanced_splitter.isHidden()
    assert not window.preset_table.isHidden()
    assert not window.preset_table.isColumnHidden(0)
    assert not window.preset_csv_controls.isHidden()
    assert window.preset_hint.text() == "Select the presets to normalize."
    assert '"file_type": "hls"' in window.metadata_text.toPlainText()
    assert '"name": "Set"' in window.metadata_text.toPlainText()
    assert window.advanced.isHidden()

    window.show()
    window.resize(1100, 900)
    window.advanced_button.setChecked(True)
    app.processEvents()

    assert not window.preset_table.isHidden()
    assert not window.advanced.isHidden()
    assert not window.preset_advanced_splitter.isHidden()
    assert (
        window.preset_advanced_splitter.height()
        > window.preset_advanced_splitter.sizeHint().height()
    )
    assert window.presets.height() == window.preset_advanced_splitter.height()
    assert window.advanced.height() == window.preset_advanced_splitter.height()
    layout_bottom = window.content.height() - window.content.layout().contentsMargins().bottom()
    assert window.preset_advanced_splitter.geometry().bottom() >= layout_bottom - 1
    assert window.preset_advanced_splitter.handle(1) is not None
    preset_width, advanced_width = window.preset_advanced_splitter.sizes()
    assert preset_width > advanced_width > 0

    window.advanced_button.setChecked(False)
    app.processEvents()

    assert not window.preset_table.isHidden()
    assert window.advanced.isHidden()

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
                    snapshot_output_levels=((1.5,), (-2.0, -2.5)),
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
    assert window.preset_table.item(0, 4).text() == "1.5"
    assert window.preset_table.item(0, 7).text() == "-2.0, -2.5"

    window.input_path.setText(str(tmp_path / "single.hlx"))
    window.load_assignments()

    assert window.load_csv_button.isEnabled()
    assert window.save_csv_button.isEnabled()

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


def test_preset_table_highlights_current_normalization_focus(monkeypatch, app) -> None:
    window = MainWindow()
    for row, preset_id in enumerate(("02B", "02C")):
        window.preset_table.insertRow(row)
        selected = QTableWidgetItem()
        selected.setCheckState(Qt.CheckState.Checked)
        window.preset_table.setItem(row, 0, selected)
        window.preset_table.setItem(row, 1, QTableWidgetItem(preset_id))
        window.preset_table.setItem(row, 2, QTableWidgetItem("Song"))
        window._clear_preset_adjustments(row)
    window._set_ignored_snapshot_highlight(0, 2, True)

    window.update_progress(ProgressEvent("preset_started", device_patch="02B"))

    assert window.preset_table._normalizing_row == 0
    assert window.preset_table._normalizing_snapshot is None
    assert window.preset_table.item(0, 1).background().color() == (
        main_window.NORMALIZATION_FOCUS_BACKGROUND
    )
    assert window.preset_table.item(0, 3).background().color() == (
        main_window.NORMALIZATION_FOCUS_BACKGROUND
    )
    assert window.preset_table.item(0, 4).background().color() == (
        main_window.NORMALIZATION_FOCUS_BACKGROUND
    )
    assert window.preset_table.item(0, 5).background().color() == (
        main_window.NORMALIZATION_FOCUS_BACKGROUND
    )
    assert window.preset_table.item(0, 9).background().color() == (
        main_window.IGNORED_SNAPSHOT_BACKGROUND
    )
    assert window.preset_table.item(0, 10).background().color() == (
        main_window.IGNORED_SNAPSHOT_BACKGROUND
    )
    assert window.preset_table.item(0, 11).background().color() == (
        main_window.IGNORED_SNAPSHOT_BACKGROUND
    )
    assert window.preset_table.item(1, 1).background().style() == Qt.BrushStyle.NoBrush

    window.update_progress(ProgressEvent("snapshot_started", device_patch="02B", snapshot=2))

    assert window.preset_table._normalizing_row == 0
    assert window.preset_table._normalizing_snapshot == 1
    assert window.preset_table.item(0, 3).background().color() == (
        main_window.NORMALIZATION_FOCUS_BACKGROUND
    )
    assert window.preset_table.item(0, 6).background().color() == (
        main_window.NORMALIZATION_FOCUS_BACKGROUND
    )
    assert window.preset_table.item(0, 9).background().color() == (
        main_window.IGNORED_SNAPSHOT_BACKGROUND
    )

    focus_during_completion = []

    def capture_completion_focus(event):
        focus_during_completion.append(window.preset_table._normalizing_snapshot)
        for column in (6, 7, 8):
            assert not window.preset_table.item(0, column).data(
                main_window.NORMALIZATION_FOCUS_ROLE
            )

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
    assert window.preset_table.item(0, 9).background().color() == (
        main_window.IGNORED_SNAPSHOT_BACKGROUND
    )

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
    window._measurement_progress_estimate = main_window._MeasurementProgressEstimate.from_request(
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

[measurement]
stability_tolerance_percent = 0.25

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
    assert window.preset_table.columnCount() == 21
    assert window.device_panels["helix"].audio_device.text() == "Configured Audio"
    assert window.pre_roll.text() == "0.3"
    assert window.post_roll.text() == "0.5"
    assert window.round_trip_latency.text() == "0.001"
    assert window.preset_wait.text() == "1.3"
    assert window.snapshot_wait.text() == "1.0"
    assert window.measurement_wait.text() == "0.6"
    assert window._optimization_stability_tolerance == 0.25
    assert window.device_panels["helix"].preset_wait.text() == "1.3"
    assert window.device_panels["helix"].snapshot_wait.text() == "1.0"
    assert window.device_panels["helix"].measurement_wait.text() == "0.6"
    argv = window._build_argv()
    assert "None" not in argv
    assert argv[argv.index("--preset-wait") + 1] == "1.3"
    assert window.device_panels["helix"].audio_group.isEnabled()

    window.close()


def test_main_window_applies_measurement_parameter_presets(monkeypatch, app) -> None:
    window = MainWindow()
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))

    window.pre_roll.setText("9")
    window.post_roll.setText("9")
    window.snapshot_wait.setText("9")
    window.measurement_wait.setText("9")
    window.preset_wait.setText("9")
    window.round_trip_latency.setText("9")

    window.measurement_parameter_preset.setCurrentText("Fast")
    window.apply_measurement_parameters_button.click()

    assert warnings
    assert warnings[0][1] == "Fast measurement parameters"
    assert "reverb and delay" in warnings[0][2].lower()
    assert window.pre_roll.text() == "0.01"
    assert window.post_roll.text() == "0.06"
    assert window.snapshot_wait.text() == "0.01"
    assert window.measurement_wait.text() == "0.47"
    assert window.preset_wait.text() == "0.21"
    assert window.round_trip_latency.text() == "0.001"
    assert window.device_panels["helix"].preset_wait.text() == "0.21"
    assert window.device_panels["helix"].snapshot_wait.text() == "0.01"
    assert window.device_panels["helix"].measurement_wait.text() == "0.47"

    window.measurement_parameter_preset.setCurrentText("Default")
    window.apply_measurement_parameters_button.click()

    assert window.pre_roll.text() == "0.3"
    assert window.post_roll.text() == "0.5"
    assert window.snapshot_wait.text() == "1.0"
    assert window.measurement_wait.text() == "0.6"
    assert window.preset_wait.text() == "1.3"
    assert window.round_trip_latency.text() == "0.001"

    window.close()


def test_measurement_time_estimate_updates_with_timing_and_loaded_counts(
    tmp_path,
    app,
) -> None:
    window = MainWindow()
    reference_di = tmp_path / "reference.wav"
    _write_silent_wav(reference_di, seconds=5.0)

    window.reference_di.setText(str(reference_di))
    window.preset_wait.setText("5")

    assert window.measurement_time_estimate.text() == (
        "Estimated measurement time per snapshot: 8.65 s (1 preset, 4 snapshots)"
    )
    assert window.preset_measurement_time_estimate.text() == (
        "Estimated total measurement time for selected presets: 34.6 s (1 preset, 4 snapshots)"
    )

    window.preset_table.insertRow(0)
    window.preset_table.insertRow(1)
    for row in range(2):
        selected = QTableWidgetItem()
        selected.setCheckState(Qt.CheckState.Checked)
        window.preset_table.setItem(row, 0, selected)
    window.snapshot_count_input.setValue(2)

    assert window.measurement_time_estimate.text() == (
        "Estimated measurement time per snapshot: 9.90 s (2 presets, 4 snapshots)"
    )
    assert window.preset_measurement_time_estimate.text() == (
        "Estimated total measurement time for selected presets: 39.6 s (2 presets, 4 snapshots)"
    )

    window.preset_table.item(1, 0).setCheckState(Qt.CheckState.Unchecked)

    assert window.preset_measurement_time_estimate.text() == (
        "Estimated total measurement time for selected presets: 19.8 s (1 preset, 2 snapshots)"
    )

    shorter_reference_di = tmp_path / "shorter.wav"
    _write_silent_wav(shorter_reference_di, seconds=1.0)
    window.reference_di.setText(str(shorter_reference_di))

    assert window.measurement_time_estimate.text() == (
        "Estimated measurement time per snapshot: 5.90 s (2 presets, 4 snapshots)"
    )
    assert window.preset_measurement_time_estimate.text() == (
        "Estimated total measurement time for selected presets: 11.8 s (1 preset, 2 snapshots)"
    )

    window.measurement_wait.setText("bad")

    assert window.measurement_time_estimate.text() == (
        "Estimated measurement time per snapshot: invalid timing value"
    )
    assert window.preset_measurement_time_estimate.text() == (
        "Estimated total measurement time for selected presets: invalid timing value"
    )

    window.close()


def test_measurement_time_estimate_counts_only_measurable_snapshots(
    tmp_path,
    app,
) -> None:
    window = MainWindow()
    reference_di = tmp_path / "reference.wav"
    _write_silent_wav(reference_di, seconds=1.0)
    window.reference_di.setText(str(reference_di))
    window.preset_wait.setText("5")
    window.snapshot_count_input.setValue(2)

    for row, preset_id in enumerate(("02B", "02C")):
        window.preset_table.insertRow(row)
        selected = QTableWidgetItem()
        selected.setCheckState(Qt.CheckState.Checked)
        window.preset_table.setItem(row, 0, selected)
        window.preset_table.setItem(row, 1, QTableWidgetItem(preset_id))
        window.preset_table.setItem(row, 2, QTableWidgetItem("Song"))
        window._clear_preset_adjustments(row)

    window._set_ignored_snapshot_highlight(0, 0, True)
    window._set_ignored_snapshot_highlight(0, 1, True)
    window._set_ignored_snapshot_highlight(1, 0, True)
    window._refresh_measurement_time_estimate()

    assert window.measurement_time_estimate.text() == (
        "Estimated measurement time per snapshot: 8.40 s (1 preset, 1 snapshot)"
    )
    assert window.preset_measurement_time_estimate.text() == (
        "Estimated total measurement time for selected presets: 8.40 s (1 preset, 1 snapshot)"
    )

    window.close()


def test_main_window_exports_current_config_by_default(tmp_path, monkeypatch, app) -> None:
    window = MainWindow()
    path = tmp_path / "current.toml"
    messages = []
    window.backend.setCurrentText("loopback")
    window.reference_di.setText("modified.wav")
    window.target_lufs.setText("-18.5")
    window.pre_roll.setText("0.7")
    window.preset_wait.setText("1.2")
    window.device_panels["helix"].audio_device.setText("Modified Helix")
    monkeypatch.setattr(window, "_choose_config_export_path", lambda: (str(path), False))
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args))

    window.config_export_button.click()

    assert window.config_path.text() == str(path)
    saved = tomllib.loads(path.read_text(encoding="utf-8"))
    assert saved["normalize"]["backend"] == "loopback"
    assert saved["normalize"]["reference_di"] == "modified.wav"
    assert saved["normalize"]["target_lufs"] == -18.5
    assert saved["analysis"]["pre_roll_seconds"] == 0.7
    assert saved["devices"]["helix"]["steering"]["preset_wait_seconds"] == 1.2
    assert saved["devices"]["helix"]["audio"]["device"] == "Modified Helix"
    assert "Saved current configuration" in messages[0][2]

    window.close()


def test_main_window_exports_default_config_when_requested(tmp_path, monkeypatch, app) -> None:
    window = MainWindow()
    path = tmp_path / "defaults.toml"
    messages = []
    window.backend.setCurrentText("loopback")
    monkeypatch.setattr(window, "_choose_config_export_path", lambda: (str(path), True))
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args))

    window.config_export_button.click()

    saved = tomllib.loads(path.read_text(encoding="utf-8"))
    assert saved["normalize"]["backend"] == "hardware"
    assert "Saved default configuriation" in messages[0][2]

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
    assert window.preset_table.item(0, 5).text() == "?"
    window.set_all_presets_checked(True)
    assert all(
        window.preset_table.item(row, 0).checkState() == Qt.CheckState.Checked
        for row in range(window.preset_table.rowCount())
    )

    window.close()


def test_select_diff_presets_checks_only_changed_rows(monkeypatch, app, tmp_path) -> None:
    window = MainWindow()
    input_path = tmp_path / "current.hls"
    previous_path = tmp_path / "previous.hls"
    input_path.touch()
    previous_path.touch()
    window.input_path.setText(str(input_path))
    window._show_loaded_preset_state(single_preset=False)
    for row, name in enumerate(("01A", "01B", "01C")):
        window.preset_table.insertRow(row)
        selected = QTableWidgetItem()
        selected.setCheckState(Qt.CheckState.Checked)
        window.preset_table.setItem(row, 0, selected)
        window.preset_table.setItem(row, 1, QTableWidgetItem(name))
        window._clear_preset_adjustments(row)

    class Handler:
        @staticmethod
        def diff_preset_ids(input_path, previous_input_path):
            return [2]

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

    window.select_diff_presets()

    assert [
        window.preset_table.item(row, 0).checkState()
        for row in range(window.preset_table.rowCount())
    ] == [
        Qt.CheckState.Unchecked,
        Qt.CheckState.Checked,
        Qt.CheckState.Unchecked,
    ]

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
    assert window.manual_adjustments.text() == "Edit manually"
    assert window.preset_table.editTriggers() == window.preset_table.EditTrigger.NoEditTriggers
    assert window.presets.layout().indexOf(window.preset_measurement_time_estimate) == 4
    preset_table_note_row = window.presets.layout().itemAt(3).layout()
    assert preset_table_note_row is not None
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
    window._clear_preset_adjustments(0)
    window._set_snapshot_names(0, ("Clean",))
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
    assert preset_item.background().color() == main_window.MANUAL_NAME_MODIFIED_BACKGROUND

    window._manual_table_cell_double_clicked(0, 3)
    window._manual_cell_editor.setText("Clean!")
    window._finish_manual_cell_edit(commit=True)
    assert snapshot_item.background().color() == main_window.MANUAL_NAME_MODIFIED_BACKGROUND

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
    window._clear_preset_adjustments(0)
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
    assert window._preset_table_csv_row(0)[3] == "+3.5"

    window._reset_preset_table_modified()
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
    window._set_adjustment_value(window.preset_table.item(0, 5), "+1.5", 1.5)
    window._set_adjustment_value(window.preset_table.item(0, 8), "-2.0", -2.0)
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
    assert window.preset_table.item(0, 5).text() == "+1.5"
    assert window.preset_table.item(0, 6).text() == "Solo"
    assert window.preset_table.item(0, 8).text() == "-2.0"
    assert window.preset_table.item(1, 2).text() == "Other 2"
    assert window.preset_table.item(1, 8).text() == "+3.0"
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
    assert window.preset_table.columnWidth(5) >= (
        window.preset_table.fontMetrics().horizontalAdvance("+12.5 (+12.5)") + 18
    )
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
    window._clear_preset_adjustments(0)
    window._set_snapshot_names(0, ("Intro", "Solo", "Solo Pitch", "Solo Pitch"))
    window._set_snapshot_output_levels(0, ((7.4,), (7.4,), (6.9,), (6.9,)))

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
    window._clear_preset_adjustments(0)

    window.update_progress(
        ProgressEvent("log", message="[GAIN] 01A Clean | 0.0 dB -> 2.5 dB (Delta: +2.5 dB)")
    )
    window.update_progress(ProgressEvent("preset_completed", device_patch="01A"))

    assert window.preset_table.item(0, 3).text() == "Clean"
    assert window.preset_table.item(0, 4).text() == "0.0"
    assert window.preset_table.item(0, 5).text() == "+2.5"
    assert window._table_adjustments().gain_deltas["12A"][0] == 2.5

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
        window._clear_preset_adjustments(row)

    for row in range(window.preset_table.rowCount()):
        window._clear_preset_adjustments(row)
        window._mark_selected_preset_adjustments_pending(row)

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
    window._clear_preset_adjustments(0)
    window._set_snapshot_names(0, ("Clean", "Solo"))
    window._custom_adjustments = {"02B": {0: 1.0}}
    window._mark_selected_preset_adjustments_pending(0)

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
    assert window.preset_table.item(0, 5).data(main_window.ADJUSTMENT_VALUE_ROLE) == 3.0
    assert window.preset_table.item(0, 5).foreground().style() == Qt.BrushStyle.NoBrush
    assert window.preset_table.item(0, 8).text() == "+4"
    assert window.preset_table.item(0, 8).foreground().style() == Qt.BrushStyle.NoBrush
    assert not window.preset_table.item(0, 5).font().bold()
    assert not window.preset_table.item(0, 8).font().bold()

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
    window._clear_preset_adjustments(0)
    window._mark_selected_preset_adjustments_pending(0)

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
    pending_widget = window.preset_table.cellWidget(0, 5)
    assert pending_widget.findChild(QLabel).text() == "?"

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
    cell_widget = window.preset_table.cellWidget(0, 5)
    label = cell_widget.findChild(QLabel)
    assert item.text() == "+1.5"
    assert cell_widget.autoFillBackground()
    assert label.text() == "+1.5"
    assert not label.font().bold()
    assert label.styleSheet() == ""

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
    window._clear_preset_adjustments(0)
    window._mark_selected_preset_adjustments_pending(0)

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

    speaker_button = window.preset_table.cellWidget(0, 5).findChild(main_window.QToolButton)
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

    speaker_button = window.preset_table.cellWidget(0, 5).findChild(main_window.QToolButton)
    assert speaker_button is not None
    assert speaker_button.isEnabled()

    window.close()


def test_input_browse_prompts_before_discarding_preset_adjustments(monkeypatch, app) -> None:
    window = MainWindow()
    _mock_single_hlx_handler(monkeypatch, name="New")
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
    window.update_progress(ProgressEvent("preset_completed", device_patch="02B"))
    answers = iter([QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Discard])
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: ("/tmp/new.hlx", ""),
    )
    monkeypatch.setattr(main_window, "QMessageBox", _FakeSaveChangesMessageBox)
    _FakeSaveChangesMessageBox.instances = []

    _FakeSaveChangesMessageBox.next_click = next(answers)
    window.browse_input()

    assert window.input_path.text() == "/tmp/original.hls"
    assert window.preset_table.item(0, 5).text() == "+1.0"

    _FakeSaveChangesMessageBox.next_click = next(answers)
    window.browse_input()

    assert window.input_path.text() == "/tmp/new.hlx"
    assert window.preset_table.rowCount() == 1
    assert window.preset_table.item(0, 1).text() == ""
    assert window.preset_table.item(0, 2).text() == "New"
    assert not window._adjusted_presets
    prompts = _FakeSaveChangesMessageBox.instances
    assert len(prompts) == 2
    assert prompts[0].title == "Save changes"
    assert prompts[0].text == (
        "The preset table contains changes. Save them before opening another preset or setlist "
        "file?"
    )
    assert QMessageBox.StandardButton.Discard in [
        button for button, _role, _ref in prompts[0].buttons
    ]

    window.close()


def test_input_browse_does_not_prompt_for_clean_preset_table(monkeypatch, app) -> None:
    window = MainWindow()
    _mock_single_hlx_handler(monkeypatch)
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


def test_embedded_startup_file_selection_loads_like_open_button(monkeypatch, app) -> None:
    window = MainWindow()
    _mock_single_hlx_handler(monkeypatch, name="Embedded")

    window.preset_empty_file_dialog.fileSelected.emit("/tmp/embedded.hlx")

    assert window.input_path.text() == "/tmp/embedded.hlx"
    assert window.preset_table.rowCount() == 1
    assert window.preset_table.item(0, 1).text() == ""
    assert window.preset_table.item(0, 2).text() == "Embedded"
    assert window.preset_empty_state.isHidden()

    window.close()


def test_closing_main_window_can_cancel_discarding_manual_table_changes(monkeypatch, app) -> None:
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
        not window.preset_table.item(0, column).data(main_window.BAD_LUFS_HIGHLIGHT_ROLE)
        for column in (0, 6, 7, 8, 9, 10, 11, 12, 13, 14)
    )
    assert not window.preset_table.item(0, 6).data(main_window.BAD_LUFS_HIGHLIGHT_ROLE)

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
    window._clear_preset_adjustments(0)
    window._mark_selected_preset_adjustments_pending(0)

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
    window._clear_preset_adjustments(0)
    window._set_output_level(window.preset_table.item(0, 4), "19.0")
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


def test_solo_snapshot_name_cell_widget_draws_left_separator(app) -> None:
    window = MainWindow()
    window.preset_table.insertRow(0)
    window.preset_table.setItem(0, 2, QTableWidgetItem("Song"))
    window._clear_preset_adjustments(0)
    window._set_snapshot_names(0, ("Solo",))

    widget = window.preset_table.cellWidget(0, 3)
    assert isinstance(widget, main_window.SnapshotNameCellWidget)
    widget.resize(80, 24)
    pixmap = QPixmap(widget.size())
    pixmap.fill(widget.palette().color(QPalette.ColorRole.Window))
    widget.render(pixmap)

    separator_color = widget.palette().mid().color().name()
    image = pixmap.toImage()
    assert image.pixelColor(0, widget.height() // 2).name() == separator_color

    window.close()


def test_snapshot_count_widget_redraws_columns_and_preserves_loaded_names(app) -> None:
    window = MainWindow()
    window.preset_table.insertRow(0)
    window.preset_table.setItem(0, 2, QTableWidgetItem("Song"))
    window._clear_preset_adjustments(0)
    window._set_snapshot_names(0, ("One", "Two", "Three", "Four", "Five", "Six"))

    window.snapshot_count_input.setValue(6)

    assert window.snapshot_count == 6
    assert window.preset_table.columnCount() == 21
    assert window.preset_table.item(0, 18).text() == "Six"
    argv = window._build_argv()
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
    window._clear_preset_adjustments(0)

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
                def validate_input(path):
                    raise ValueError("Invalid input")

            return FailingHandler()

    monkeypatch.setattr(main_window, "get_device_profile", lambda device: FailingProfile())
    window.input_path.setText("missing.hls")
    window.load_assignments()
    assert window.preset_table.item(0, 0).background().style() == Qt.BrushStyle.NoBrush

    window.update_progress(ProgressEvent("log", message="[GAIN] 02B Clean | bad LUFS"))
    window.update_progress(ProgressEvent("preset_completed", device_patch="02B"))
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
    window._set_output_level(window.preset_table.item(0, 4), "0.0")

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
    window._clear_preset_adjustments(0)
    window._set_snapshot_names(0, ("Snap One", "Snap Two"))
    window._set_output_level(window.preset_table.item(0, 4), "14.0, 14.0")
    window._set_output_level(window.preset_table.item(0, 7), "14.0, 14.0")

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
    assert all(
        not window.preset_table.item(0, column).data(main_window.BAD_LUFS_HIGHLIGHT_ROLE)
        for column in (3, 4, 5)
    )
    assert all(
        window.preset_table.item(0, column).data(main_window.BAD_LUFS_HIGHLIGHT_ROLE)
        for column in (6, 7, 8)
    )

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
    window._clear_preset_adjustments(0)
    window._set_snapshot_names(0, ("Clean", "Solo"))
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

    assert window._selected_preset_set() == "03C"
    selected_rows = {
        index.row() for index in window.preset_table.selectionModel().selectedIndexes()
    }
    assert selected_rows == {1}
    assert window.preset_table.item(1, 1).text() == "03C"

    window.close()


def test_loaded_file_updates_window_title_and_save_as_state(monkeypatch, app) -> None:
    window = MainWindow()
    _mock_single_hlx_handler(monkeypatch)
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
    created = []
    validated = []

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

    class Handler:
        def validate_output(self, selected_input_path, selected_output_path):
            validated.append((selected_input_path, selected_output_path))

        def create_measurement_file(self, selected_input_path, selected_output_path):
            created.append((selected_input_path, selected_output_path))

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
    monkeypatch.setattr(main_window, "QFileDialog", FileDialog)
    monkeypatch.setattr(main_window, "parse_args", lambda argv: argv)
    monkeypatch.setattr(main_window, "apply_config", lambda args: args)
    monkeypatch.setattr(main_window, "request_from_args", lambda args: request)
    monkeypatch.setattr(main_window, "get_device_profile", lambda device: Profile())
    window.input_path.setText(str(input_path))
    window._loaded_input_path = str(input_path)
    window._refresh_file_actions()

    assert window.save_measurement_action.isEnabled()
    assert window.save_measurement_file()
    assert validated == [(input_path, output_path)]
    assert created == [(input_path, output_path)]
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


def test_single_preset_save_as_preserves_target_preset_id(tmp_path, monkeypatch, app) -> None:
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
            return [
                SimpleNamespace(
                    device_patch="01A",
                    name="Saved",
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
    window._set_adjustment_value(window.preset_table.item(0, 5), "+1.0", 1.0)
    window._mark_preset_table_modified()
    window.completed_request = _request(input_path=input_path)
    window.completed_result = NormalizationResult(None, tmp_path, csv_path)

    assert window._save_to_path(output_path)

    assert len(exports) == 1
    assert window.input_path.text() == str(output_path)
    assert window.preset_table.item(0, 1).text() == "12A"
    assert window.preset_table.item(0, 2).text() == "Saved"
    assert window.preset_table.item(0, 5).text() == "0"
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

    assert window._selected_preset_set() == "03C"
    selected_rows = {
        index.row() for index in window.preset_table.selectionModel().selectedIndexes()
    }
    assert selected_rows == {1}
    assert not window._preset_table_has_unsaved_changes()

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


def test_measurement_optimization_dialog_shows_latest_statistics(app) -> None:
    dialog = main_window.MeasurementOptimizationDialog()
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
    dialog = main_window.MeasurementOptimizationDialog(
        main_window.MeasurementOptimizationSettings(
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
    )

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


def test_measurement_optimization_dialog_status_text_is_selectable(app) -> None:
    dialog = main_window.MeasurementOptimizationDialog()

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
    dialog = main_window.MeasurementOptimizationDialog()
    applied = []
    dialog.applied.connect(applied.append)

    assert not dialog.apply_button.isEnabled()

    dialog.set_result("[analysis]\npre_roll_seconds = 0.7")
    dialog.apply_button.click()

    assert applied == ["[analysis]\npre_roll_seconds = 0.7"]

    dialog.accept()
    dialog.deleteLater()


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
    assert window.device_panels["helix"].preset_wait.text() == "1.1"
    assert window.device_panels["helix"].snapshot_wait.text() == "1.2"
    assert window.device_panels["helix"].measurement_wait.text() == "1.3"
    assert messages

    window.close()


def test_optimization_dialog_action_button_becomes_close(monkeypatch, app) -> None:
    dialog = main_window.MeasurementOptimizationDialog()
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
    dialog = main_window.MeasurementOptimizationDialog()
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
    monkeypatch.setattr(main_window, "parse_args", lambda argv: object())
    monkeypatch.setattr(main_window, "apply_config", lambda args: args)
    monkeypatch.setattr(main_window, "request_from_args", lambda args: request)
    monkeypatch.setattr(window, "_optimization_preset_id", lambda request: 7)
    monkeypatch.setattr(
        window,
        "_show_measurement_optimization_setup",
        lambda request, preset_id: main_window.MeasurementOptimizationSettings(
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
    monkeypatch.setattr(main_window, "parse_args", lambda argv: object())
    monkeypatch.setattr(main_window, "apply_config", lambda args: args)
    monkeypatch.setattr(main_window, "request_from_args", lambda args: request)
    monkeypatch.setattr(window, "_optimization_preset_id", lambda request: 7)
    monkeypatch.setattr(main_window, "MeasurementOptimizationWorker", Worker)
    monkeypatch.setattr(
        window,
        "_show_measurement_optimization_setup",
        lambda request, preset_id: main_window.MeasurementOptimizationSettings(
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
        "check_windows_hardware",
        lambda checked_request: checks.append(checked_request),
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
    adjusted_settings = main_window.MeasurementOptimizationSettings(
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
                return main_window.QDialog.DialogCode.Accepted
            return main_window.QDialog.DialogCode.Rejected

        def settings(self):
            return adjusted_settings

    monkeypatch.setattr(window, "_backend_check_enabled", lambda: True)
    monkeypatch.setattr(window, "_validate_single_preset_slot_for_run", lambda: True)
    monkeypatch.setattr(main_window, "parse_args", lambda argv: object())
    monkeypatch.setattr(main_window, "apply_config", lambda args: args)
    monkeypatch.setattr(main_window, "request_from_args", lambda args: request)
    monkeypatch.setattr(window, "_optimization_preset_id", lambda request: 7)
    monkeypatch.setattr(main_window, "MeasurementOptimizationSetupDialog", SetupDialog)
    monkeypatch.setattr(
        gui_worker,
        "check_windows_hardware",
        lambda checked_request: (
            checks.append(checked_request) or (_ for _ in ()).throw(RuntimeError("no audio device"))
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


def test_optimization_dialog_close_confirms_abort(monkeypatch, app) -> None:
    dialog = main_window.MeasurementOptimizationDialog()
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


def test_consecutive_optimization_reuses_previous_start_parameters(monkeypatch, app) -> None:
    window = MainWindow()
    request = _request()
    previous_settings = main_window.MeasurementOptimizationSettings(
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
            return main_window.QDialog.DialogCode.Accepted

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
    modified_settings = main_window.MeasurementOptimizationSettings(
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
                return main_window.QDialog.DialogCode.Rejected
            return main_window.QDialog.DialogCode.Accepted

        def settings(self):
            return modified_settings

    monkeypatch.setattr(main_window, "MeasurementOptimizationSetupDialog", SetupDialog)

    assert window._show_measurement_optimization_setup(request, 7) is None
    settings = window._show_measurement_optimization_setup(request, 7)

    assert window._last_measurement_optimization_settings == modified_settings
    assert captured[1] == modified_settings
    assert settings == modified_settings

    window.close()


def test_measurement_optimization_setup_dialog_returns_adjusted_values(app) -> None:
    dialog = main_window.MeasurementOptimizationSetupDialog(
        main_window.MeasurementOptimizationSettings(
            pre_roll=0.2,
            post_roll=0.1,
            round_trip_latency=0.02,
            preset_wait=0.5,
            snapshot_wait=0.2,
            measurement_wait=0.1,
            stability_runs=3,
            termination_tolerance=10.0,
            stability_tolerance=2.0,
        ),
        "02C",
        7,
    )

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


def test_measurement_optimization_setup_dialog_return_focuses_next_parameter_input(
    app,
) -> None:
    dialog = main_window.MeasurementOptimizationSetupDialog(
        main_window.MeasurementOptimizationSettings(
            pre_roll=0.2,
            post_roll=0.1,
            round_trip_latency=0.02,
            preset_wait=0.5,
            snapshot_wait=0.2,
            measurement_wait=0.1,
            stability_runs=3,
            termination_tolerance=10.0,
            stability_tolerance=2.0,
        ),
        "02C",
        7,
    )
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
    assert dialog.result() != main_window.QDialog.DialogCode.Accepted

    dialog.deleteLater()


def test_determine_optimal_parameters_cancel_setup_aborts(monkeypatch, app) -> None:
    window = MainWindow()
    request = _request(backend="hardware")
    checks = []

    monkeypatch.setattr(window, "_backend_check_enabled", lambda: True)
    monkeypatch.setattr(window, "_validate_single_preset_slot_for_run", lambda: True)
    monkeypatch.setattr(main_window, "parse_args", lambda argv: object())
    monkeypatch.setattr(main_window, "apply_config", lambda args: args)
    monkeypatch.setattr(main_window, "request_from_args", lambda args: request)
    monkeypatch.setattr(window, "_optimization_preset_id", lambda request: 7)
    monkeypatch.setattr(
        window, "_show_measurement_optimization_setup", lambda request, preset_id: None
    )
    monkeypatch.setattr(
        gui_worker,
        "check_windows_hardware",
        lambda checked_request: checks.append(checked_request),
    )

    window.determine_optimal_parameters()

    assert checks == []
    assert window.hardware_check_worker is None
    assert window.optimization_worker is None

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


def test_first_hardware_normalization_checks_backend_once(monkeypatch, app) -> None:
    window = MainWindow()
    request = _request(backend="hardware")
    checks = []
    monkeypatch.setattr(window, "_backend_check_enabled", lambda: True)
    monkeypatch.setattr(main_window, "parse_args", lambda argv: object())
    monkeypatch.setattr(main_window, "apply_config", lambda args: args)
    monkeypatch.setattr(main_window, "request_from_args", lambda args: request)
    monkeypatch.setattr(
        gui_worker,
        "check_windows_hardware",
        lambda checked_request: checks.append(checked_request),
    )
    monkeypatch.setattr(main_window.NormalizationWorker, "start", lambda self: None)

    window.start_normalization()

    for _ in range(100):
        app.processEvents()
        if window.worker is not None and window.hardware_check_worker is None:
            break
        time.sleep(0.01)

    assert len(checks) == 1
    assert checks[0].backend == "hardware"
    assert checks[0].defer_export
    assert window.worker is not None
    assert window.hardware_check_overlay.isHidden()
    window.worker_finished()

    window.start_normalization()

    assert len(checks) == 1
    assert window.worker is not None
    assert window.hardware_check_overlay.isHidden()
    window.worker_finished()
    window.close()


def test_unavailable_backend_blocks_first_normalization(monkeypatch, app) -> None:
    window = MainWindow()
    request = _request(backend="hardware")
    popups = []
    checks = []
    monkeypatch.setattr(window, "_backend_check_enabled", lambda: True)
    monkeypatch.setattr(main_window, "parse_args", lambda argv: object())
    monkeypatch.setattr(main_window, "apply_config", lambda args: args)
    monkeypatch.setattr(main_window, "request_from_args", lambda args: request)
    monkeypatch.setattr(
        gui_worker,
        "check_windows_hardware",
        lambda checked_request: (
            checks.append(checked_request) or (_ for _ in ()).throw(RuntimeError("no audio device"))
        ),
    )
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: popups.append(args))
    monkeypatch.setattr(
        main_window.NormalizationWorker,
        "start",
        lambda self: (_ for _ in ()).throw(AssertionError("unexpected normalization")),
    )

    window.start_normalization()

    for _ in range(100):
        app.processEvents()
        if popups and window.hardware_check_worker is None:
            break
        time.sleep(0.01)

    assert len(checks) == 1
    assert checks[0].backend == "hardware"
    assert checks[0].defer_export
    assert len(popups) == 1
    assert popups[0][1] == "Error"
    assert "No suitable device connected" in popups[0][2]
    assert window.worker is None
    assert window.hardware_check_worker is None
    assert window.hardware_check_overlay.isHidden()

    window.close()


def test_switching_backend_only_rechecks_on_next_normalization(monkeypatch, app) -> None:
    window = MainWindow()
    request = _request(backend="hardware")
    checks = []
    monkeypatch.setattr(window, "_backend_check_enabled", lambda: True)
    monkeypatch.setattr(main_window, "parse_args", lambda argv: object())
    monkeypatch.setattr(main_window, "apply_config", lambda args: args)
    monkeypatch.setattr(main_window, "request_from_args", lambda args: request)
    monkeypatch.setattr(
        gui_worker,
        "check_windows_hardware",
        lambda checked_request: checks.append(checked_request),
    )
    monkeypatch.setattr(main_window.NormalizationWorker, "start", lambda self: None)

    window.backend.setCurrentText("loopback")
    window.backend.setCurrentText("hardware")

    for _ in range(10):
        app.processEvents()
        time.sleep(0.01)

    assert checks == []
    assert window.worker is None
    assert window.hardware_check_worker is None

    window.start_normalization()

    for _ in range(100):
        app.processEvents()
        if window.worker is not None and window.hardware_check_worker is None:
            break
        time.sleep(0.01)

    assert len(checks) == 1
    assert checks[0].backend == "hardware"
    assert checks[0].defer_export
    assert window.worker is not None
    assert window.hardware_check_worker is None
    assert window.hardware_check_overlay.isHidden()
    window.worker_finished()

    window.backend.setCurrentText("loopback")
    window.backend.setCurrentText("hardware")
    window.start_normalization()

    for _ in range(100):
        app.processEvents()
        if len(checks) == 2 and window.worker is not None and window.hardware_check_worker is None:
            break
        time.sleep(0.01)

    assert len(checks) == 2
    assert window.worker is not None
    window.worker_finished()

    window.close()


def test_loopback_normalization_skips_hardware_check(monkeypatch, app) -> None:
    window = MainWindow()
    request = _request(backend="loopback")
    monkeypatch.setattr(main_window, "parse_args", lambda argv: object())
    monkeypatch.setattr(main_window, "apply_config", lambda args: args)
    monkeypatch.setattr(main_window, "request_from_args", lambda args: request)
    monkeypatch.setattr(
        gui_worker,
        "check_windows_hardware",
        lambda request: (_ for _ in ()).throw(AssertionError("unexpected hardware check")),
    )
    monkeypatch.setattr(main_window.NormalizationWorker, "start", lambda self: None)

    window.start_normalization()

    assert window.worker is not None
    window.worker_finished()
    window.close()


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
