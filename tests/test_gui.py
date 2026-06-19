from __future__ import annotations

import os
import threading
import time
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from gui_test_helpers import stub_gui_settings
from PySide6.QtCore import QCoreApplication, QEvent, QSettings, QSize
from PySide6.QtGui import QCloseEvent, Qt
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QLabel,
    QMenuBar,
    QMessageBox,
    QSizePolicy,
    QSplitter,
    QTableWidgetItem,
    QToolBar,
    QToolButton,
    QWidget,
)
from shiboken6 import isValid

from matchpatch.devices import list_device_profiles
from matchpatch.diagnostics import DiagnosticCheck
from matchpatch.gui import main_window, measurement_optimization, progress_widgets, window_state
from matchpatch.gui import worker as gui_worker
from matchpatch.gui.main_window import MainWindow
from matchpatch.gui.preset_table import (
    ContentHeightTableWidget,
)
from matchpatch.gui.table_roles import PRESET_ORIGINAL_FILENAME_ROLE, PRESET_TABLE_ATTENTION_ROLE
from matchpatch.gui.worker import NormalizationWorker
from matchpatch.normalize import DEFAULT_REFERENCE_DI, DEFAULT_WINDOWS_PYTHON
from matchpatch.progress import ProgressEvent
from matchpatch.workflow import ImportRequest, NormalizationRequest, NormalizationResult


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    QCoreApplication.setOrganizationName("MatchPatchTests")
    QCoreApplication.setApplicationName("MatchPatchTests")
    yield instance


@pytest.fixture(autouse=True)
def isolated_qsettings(app, tmp_path):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, str(tmp_path))
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    QSettings().clear()
    yield
    QSettings().clear()


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

        @staticmethod
        def parse_patch_set(value):
            return [1] if value == "01A" else []

    Handler.file_kind = staticmethod(lambda path: "preset")

    profile = SimpleNamespace(
        display_name="Line 6 Helix",
        create_patch_file_handler=lambda root: Handler(),
    )
    monkeypatch.setattr(main_window, "get_device_profile", lambda device: profile)


class _SignalStub:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, *args):
        for callback in list(self.callbacks):
            callback(*args)


class _FakePreflightWorker:
    instances = []

    def __init__(self, request, parent=None):
        self.request = request
        self.parent = parent
        self.completed = _SignalStub()
        self.failed = _SignalStub()
        self.finished = _SignalStub()
        self.started = False
        _FakePreflightWorker.instances.append(self)

    def start(self):
        self.started = True

    def deleteLater(self):
        return None


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


def test_main_window_starts_with_registry_device_and_hardware(app) -> None:
    window = MainWindow()

    assert window.device.currentData() == "helix"
    assert window.backend.currentText() == "hardware"
    assert isinstance(window.advanced, QWidget)
    assert not isinstance(window.advanced, QGroupBox)
    assert not window.advanced.isHidden()
    assert window.advanced_button.isChecked()
    assert [window.advanced_tabs.tabText(index) for index in range(8)] == [
        "Device",
        "Files",
        "Timing",
        "Loudness",
        "Selection",
        "Misc",
        "Meta Data",
        "Diagnostics",
    ]
    assert window.advanced_tabs.widget(0).isAncestorOf(window.backend)
    assert not window.advanced_tabs.widget(1).isAncestorOf(window.backend)
    device_labels = {label.text() for label in window.advanced_tabs.widget(0).findChildren(QLabel)}
    assert "Preset wait (s)" not in device_labels
    assert "Snapshot wait (s)" not in device_labels
    assert "Measurement wait (s)" not in device_labels
    assert window.advanced_tabs.widget(1).isAncestorOf(window.config_path)
    assert not window.advanced_tabs.widget(1).isAncestorOf(window.diagnostic_bundle_button)
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
    lufs_group_titles = {
        group.title() for group in window.advanced_tabs.widget(3).findChildren(QGroupBox)
    }
    assert "Snapshot name regex" not in lufs_group_titles
    lufs_labels = {label.text() for label in window.advanced_tabs.widget(3).findChildren(QLabel)}
    assert "Ignore snapshot" not in lufs_labels
    assert not window.advanced_tabs.widget(3).isAncestorOf(window.solo_regex)
    assert not window.advanced_tabs.widget(3).isAncestorOf(window.ignore_snapshot_regex)
    assert window.advanced_tabs.widget(4).isAncestorOf(window.solo_regex)
    assert window.advanced_tabs.widget(4).isAncestorOf(window.ignore_snapshot_regex)
    assert window.advanced_tabs.widget(4).isAncestorOf(window.ignore_preset_regex)
    selection_labels = {
        label.text() for label in window.advanced_tabs.widget(4).findChildren(QLabel)
    }
    assert "Solo" in selection_labels
    assert "Ignored" in selection_labels
    assert "Hide presets" in selection_labels
    assert window.advanced_tabs.widget(5).isAncestorOf(window.snapshot_count_input)
    assert window.advanced_tabs.widget(7).isAncestorOf(window.preflight_button)
    assert window.advanced_tabs.widget(7).isAncestorOf(window.diagnostic_summary_button)
    assert window.advanced_tabs.widget(7).isAncestorOf(window.diagnostic_bundle_button)
    assert window.advanced_tabs.widget(7).isAncestorOf(window.log)
    assert window.advanced_tabs.widget(7).isAncestorOf(window.log_level)
    diagnostic_groups = {
        group.title() for group in window.advanced_tabs.widget(7).findChildren(QGroupBox)
    }
    assert "Privacy notice" in diagnostic_groups
    assert "Log" in diagnostic_groups
    assert "saved locally" in window.diagnostics_privacy_notice.text()
    assert "Review the ZIP before sharing" in window.diagnostics_privacy_notice.text()
    privacy_style = window.diagnostics_privacy_panel.styleSheet()
    assert "#eff6ff" in privacy_style
    assert "#3b82f6" in privacy_style
    assert "#1d4ed8" in privacy_style
    assert not isinstance(window.presets, QGroupBox)
    assert window.measurement_parameter_preset.currentText() == "Default"
    assert window.pre_roll.text() == "0.3"
    assert window.post_roll.text() == "0.5"
    assert window.snapshot_wait.text() == "1.0"
    assert window.measurement_wait.text() == "0.6"
    assert window.preset_wait.text() == "1.3"
    assert window.round_trip_latency.text() == "0.001"
    timing_form = window.advanced_tabs.widget(2).layout().itemAt(1).layout()
    assert [
        timing_form.itemAt(row, QFormLayout.ItemRole.FieldRole).widget()
        for row in range(timing_form.rowCount())
    ] == [
        window.analysis_window,
        window.analysis_interval,
        window.pre_roll,
        window.post_roll,
        window.snapshot_wait,
        window.measurement_wait,
        window.preset_wait,
        window.round_trip_latency,
    ]
    expected_seconds = 1.0 + 0.6 + 0.3 + 0.5 + 0.001 + 1.3 / 4
    expected_seconds += progress_widgets.reference_audio_seconds(DEFAULT_REFERENCE_DI)
    assert window.measurement_time_estimate.text() == (
        "Estimated measurement time per snapshot: "
        f"{measurement_optimization._format_short_seconds(expected_seconds)} "
        "(1 preset, 4 snapshots)"
    )
    assert window.presets.layout().contentsMargins().isNull()
    assert window.scroll_area.frameShape() == QFrame.Shape.NoFrame
    assert window.measurement_panel_separator.frameShape() == QFrame.Shape.HLine
    assert window.measurement_panel_separator.frameShadow() == QFrame.Shadow.Sunken
    assert not window.presets.isHidden()
    assert not window.preset_empty_state.isHidden()
    assert "border: none" in window.preset_empty_state.styleSheet()
    assert window.preset_header.isHidden()
    assert window.preset_table.isHidden()
    assert not window.preset_empty_logo.pixmap().isNull()
    assert window.preset_empty_logo.pixmap().size() == QSize(360, 360)
    assert window.preset_empty_logo.size() == QSize(360, 360)
    assert window.preset_empty_state.layout().itemAt(1).alignment() & Qt.AlignmentFlag.AlignHCenter
    assert isinstance(window.preset_empty_open_button, QToolButton)
    assert window.preset_empty_open_button.text() == "Open preset/setlist"
    assert not window.preset_empty_open_button.icon().isNull()
    assert window.preset_empty_open_button.iconSize() == QSize(64, 64)
    assert (
        window.preset_empty_open_button.toolButtonStyle()
        == Qt.ToolButtonStyle.ToolButtonTextUnderIcon
    )
    assert window.preset_empty_open_button.autoRaise()
    assert window.preset_empty_open_button.parent() is window.preset_empty_state
    assert window.recent_files.parent() is window.preset_empty_state
    assert window.preset_empty_state.layout().itemAt(3).alignment() & Qt.AlignmentFlag.AlignHCenter
    assert not hasattr(window, "preset_empty_recent_label")
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
    menu_bar = window.menuBar()
    assert isinstance(menu_bar, QMenuBar)
    assert [action.text() for action in menu_bar.actions()] == ["File", "Run", "Help"]
    file_menu = menu_bar.actions()[0].menu()
    run_menu = menu_bar.actions()[1].menu()
    help_menu = menu_bar.actions()[2].menu()
    assert file_menu is not None
    assert run_menu is not None
    assert help_menu is not None
    assert [action.text() for action in file_menu.actions() if not action.isSeparator()] == [
        "Open",
        "Save",
        "Save As",
        "Save Measurement File",
        "Split Setlist",
        "Exit",
    ]
    assert file_menu.actions()[-1] is window.exit_action
    assert [action.text() for action in run_menu.actions()] == ["Normalize"]
    assert run_menu.actions()[0] is window.run_normalization_action
    assert [action.text() for action in help_menu.actions()] == ["Help", "About"]
    assert help_menu.actions()[0] is window.help_action
    assert help_menu.actions()[1] is window.about_action
    for action in (
        window.open_action,
        window.save_action,
        window.save_as_action,
        window.save_measurement_action,
        window.split_setlist_action,
        window.exit_action,
        window.run_normalization_action,
        window.help_action,
        window.about_action,
    ):
        assert not action.icon().isNull()
    toolbar = window.findChildren(QToolBar)[0]
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
    assert toolbar.actions().index(window.recording_separator_action) == (
        toolbar.actions().index(window.device_action) + 1
    )
    assert toolbar.actions().index(window.advanced_action) == (
        toolbar.actions().index(window.play_recorded_output_action) + 1
    )
    assert toolbar.actions().index(window.record_output_action) == (
        toolbar.actions().index(window.recording_separator_action) + 1
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
    assert toolbar.iconSize() == QSize(20, 20)
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
    assert isinstance(window.start_button, QToolButton)
    assert isinstance(window.cancel_button, QToolButton)
    assert isinstance(window.record_output_button, QToolButton)
    assert isinstance(window.play_recorded_output_button, QToolButton)
    assert isinstance(window.advanced_button, QToolButton)
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
    assert toolbar.minimumHeight() == (
        window.advanced_button.height() + main_window.TOOLBAR_VERTICAL_PADDING
    )
    assert toolbar.maximumHeight() == (
        window.advanced_button.height() + main_window.TOOLBAR_VERTICAL_PADDING
    )
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
        assert button.property("keep_tooltip_visible")
    assert window.open_action.isEnabled()
    assert not window.save_action.isEnabled()
    assert not window.save_as_action.isEnabled()
    assert not window.save_measurement_action.isEnabled()
    assert not window.start_button.isEnabled()
    assert not window.run_normalization_action.isEnabled()
    assert not window.determine_parameters_button.isEnabled()
    assert not window.determine_parameters_hint.isHidden()
    assert "Open a Helix file" in window.determine_parameters_hint.text()
    assert not window.record_output_button.isEnabled()
    assert window.record_output_button.isChecked()
    assert not window.play_recorded_output_button.isChecked()
    assert window.log_level.currentText() == "Info"
    assert window.metadata_text.toPlainText() == "{}"
    assert window.device_stack.count() == len(list_device_profiles())
    assert set(window.device_panels) == {profile.name for profile in list_device_profiles()}
    assert window.device_panels["helix"].audio_group.isEnabled()
    assert window.device_panels["podgo"].isEnabled()
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
    assert window.preset_table_note.text() == "Only non-empty presets are listed."
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
    assert window.comparison_enabled.text() == "Enabled"
    assert window.comparison_enabled.isHidden()
    assert not window.comparison_enabled.isEnabled()
    assert not window.comparison_enabled.isChecked()
    assert window.show_legend_button.text() == "Show legend"
    assert window.show_legend_button.isHidden()
    assert window.load_csv_button.width() == window.load_csv_button.height()
    assert window.save_csv_button.width() == window.save_csv_button.height()
    assert window.snapshot_count_input.value() == 4
    assert window.snapshot_count_input.maximum() == 8

    window.close()


def test_main_window_lists_device_without_settings_panel(monkeypatch, app) -> None:
    helix = main_window.get_device_profile("helix")
    fake = SimpleNamespace(
        name="fake",
        display_name="Fake Device",
        measurement_backends=lambda: ("offline",),
        default_audio_routing=lambda: SimpleNamespace(
            device=None,
            sample_rate=48000,
            input_mapping="1,2",
            output_mapping="1,2",
        ),
        default_steering_options=lambda: SimpleNamespace(
            output=None,
            channel=0,
            preset_wait_seconds=0.0,
            snapshot_wait_seconds=0.0,
            measurement_wait_seconds=0.0,
        ),
        default_ignore_preset_regex=lambda: "",
    )
    monkeypatch.setattr(main_window, "list_device_profiles", lambda: [helix, fake])
    monkeypatch.setattr(
        main_window,
        "get_device_profile",
        lambda name: fake if name == "fake" else helix,
    )
    monkeypatch.setattr(
        "matchpatch.normalize.get_device_profile",
        lambda name: fake if name == "fake" else helix,
    )

    window = MainWindow()
    window.loading_controller.get_profile = lambda name: fake if name == "fake" else helix
    fake_index = window.device.findData("fake")

    assert fake_index >= 0
    assert "fake" not in window.device_panels

    window.device.setCurrentIndex(fake_index)
    app.processEvents()

    assert window.device.currentData() == "fake"
    assert window.backend.currentText() == "offline"

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


def test_loading_preset_table_does_not_resize_window(monkeypatch, app, tmp_path) -> None:
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
                    device_patch=f"{row + 1:02d}A",
                    name=f"Preset {row + 1}",
                    snapshot_names=("Clean", "Solo"),
                )
                for row in range(ContentHeightTableWidget.MAX_VISIBLE_ROWS)
            ]

        @staticmethod
        def metadata(path):
            return {"file_type": "hls"}

    Handler.file_kind = staticmethod(lambda path: "setlist")

    profile = SimpleNamespace(create_patch_file_handler=lambda root: Handler())
    monkeypatch.setattr(main_window, "get_device_profile", lambda device: profile)
    window.show()
    app.processEvents()
    initial_size = window.size()

    window.input_path.setText(str(path))
    window.load_assignments()
    app.processEvents()

    assert window.preset_empty_state.isHidden()
    assert not window.preset_table.isHidden()
    assert not window.select_diff_button.isHidden()
    assert window.size() == initial_size

    window.close()


def test_window_size_stays_fixed_when_advanced_side_pane_is_hidden(app) -> None:
    window = MainWindow()
    window._show_loaded_preset_state(single_preset=True)
    window.show()
    app.processEvents()

    expanded_size = window.size()
    window.advanced_button.setChecked(False)
    app.processEvents()

    assert window.size() == expanded_size
    assert window.advanced.isHidden()

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

    window.advanced_button.setChecked(True)
    app.processEvents()

    assert window.size() == initial_size
    assert not window.advanced.isHidden()

    window.close()


def test_window_size_stays_fixed_when_progress_visibility_changes(app) -> None:
    window = MainWindow()
    window.show()
    app.processEvents()
    window._resize_to_initial_content()
    app.processEvents()
    initial_size = window.size()

    window._show_indeterminate_progress("Preparing measurement...")
    app.processEvents()
    assert window.size() == initial_size

    window._stop_busy_phase()
    app.processEvents()
    assert window.size() == initial_size

    window.close()


def test_window_size_stays_fixed_when_advanced_tab_changes(app) -> None:
    window = MainWindow()
    window.show()
    app.processEvents()
    initial_size = window.size()

    for index in range(window.advanced_tabs.count()):
        window.advanced_tabs.setCurrentIndex(index)
        app.processEvents()
        assert window.size() == initial_size

    window.close()


def test_window_size_stays_fixed_when_preset_table_rows_change(app) -> None:
    window = MainWindow()
    window._show_loaded_preset_state(single_preset=False)
    window.show()
    app.processEvents()
    initial_size = window.size()

    for row in range(20):
        window.preset_table.insertRow(row)
        app.processEvents()
        assert window.size() == initial_size

    window.preset_table.setRowCount(1)
    app.processEvents()

    assert window.size() == initial_size

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
    assert not window.select_diff_button.isHidden()
    assert not window.comparison_enabled.isHidden()
    assert not window.show_legend_button.isHidden()
    assert not window.preset_csv_controls.isHidden()
    assert window.load_csv_button.isEnabled()
    assert window.save_csv_button.isEnabled()
    assert window.preset_table.rowCount() == 1
    assert window.preset_table.item(0, 1).text() == ""
    assert window.preset_table.item(0, 2).text() == "Lead"
    assert window.preset_table.item(0, 2).data(PRESET_ORIGINAL_FILENAME_ROLE) == "example.hlx"
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
    assert window.preset_table.item(0, 1).data(PRESET_TABLE_ATTENTION_ROLE)
    assert window.worker is None
    assert window.start_button.isEnabled()

    window.close()


def test_podgo_single_preset_run_requires_temporary_slot(monkeypatch, app) -> None:
    window = MainWindow()
    window.input_path.setText("/tmp/example.pgp")
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))

    class Handler:
        @staticmethod
        def file_kind(path):
            return "preset"

        @staticmethod
        def parse_patch_set(value):
            return {"01A": [1], "32D": [128]}.get(value, [])

    profile = SimpleNamespace(
        display_name="Line 6 Pod Go",
        create_patch_file_handler=lambda root: Handler(),
    )
    monkeypatch.setattr(main_window, "get_device_profile", lambda device: profile)

    assert not window._validate_single_preset_slot_for_run()
    assert warnings[0][2] == (
        "Enter the temporary Line 6 Pod Go preset ID in the Preset column before "
        "running normalization."
    )

    window.preset_table.setRowCount(1)
    window.preset_table.setItem(0, 1, QTableWidgetItem("32D"))

    assert window._validate_single_preset_slot_for_run()

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
            return [
                SimpleNamespace(
                    device_patch="01A",
                    name="Lead",
                    snapshot_names=("Verse",),
                    original_filename="lead.hlx",
                )
            ]

        @staticmethod
        def metadata(path):
            return {"file_type": "hls", "metadata": [{"path": "$.meta", "value": {"name": "Set"}}]}

    Handler.file_kind = staticmethod(lambda path: "setlist")

    profile = SimpleNamespace(create_patch_file_handler=lambda root: Handler())
    monkeypatch.setattr(main_window, "get_device_profile", lambda device: profile)
    window.input_path.setText(str(path))
    window.load_assignments()

    assert not window.presets.isHidden()
    assert not window.preset_advanced_splitter.isHidden()
    assert not window.preset_table.isHidden()
    assert not window.preset_table.isColumnHidden(0)
    assert window.preset_table.item(0, 2).data(PRESET_ORIGINAL_FILENAME_ROLE) == "lead.hlx"
    assert not window.preset_csv_controls.isHidden()
    assert window.preset_hint.text() == "Select the presets to normalize."
    assert '"file_type": "hls"' in window.metadata_text.toPlainText()
    assert '"name": "Set"' in window.metadata_text.toPlainText()
    assert not window.advanced.isHidden()

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

    Handler.file_kind = staticmethod(
        lambda path: "preset" if Path(path).suffix.lower() == ".hlx" else "setlist"
    )

    profile = SimpleNamespace(create_patch_file_handler=lambda root: Handler())
    monkeypatch.setattr(main_window, "get_device_profile", lambda device: profile)
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
    window.preset_table_controller.clear_preset_adjustments(0)
    window.update_progress(
        ProgressEvent("log", message="[GAIN] 02B Solo | 0.0 dB -> 1.0 dB (Delta: +1.0 dB)")
    )
    window.update_progress(ProgressEvent("preset_completed", device_patch="02B"))
    answers = iter([QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Discard])
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: (["/tmp/new.hlx"], ""),
    )
    monkeypatch.setattr(main_window, "QMessageBox", _FakeSaveChangesMessageBox)
    _FakeSaveChangesMessageBox.instances = []

    _FakeSaveChangesMessageBox.next_click = next(answers)
    window.browse_input()

    assert window.input_path.text() == "/tmp/original.hls"
    assert window.preset_table.item(0, 5).text() == "+1.0"

    _FakeSaveChangesMessageBox.next_click = next(answers)
    window.browse_input()

    assert window.input_path.text() == str(Path("/tmp/new.hlx"))
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
        "getOpenFileNames",
        lambda *args, **kwargs: (["/tmp/new.hlx"], ""),
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args: pytest.fail("clean preset table should not prompt"),
    )

    window.browse_input()

    assert window.input_path.text() == str(Path("/tmp/new.hlx"))

    window.close()


def test_startup_open_button_loads_like_toolbar_open(tmp_path, monkeypatch, app) -> None:
    window = MainWindow()
    _mock_single_hlx_handler(monkeypatch, name="Embedded")
    input_file = tmp_path / "embedded.hlx"
    input_file.touch()
    path = str(input_file)
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: ([path], ""),
    )

    window.preset_empty_open_button.click()

    assert window.input_path.text() == path
    assert window.preset_table.rowCount() == 1
    assert window.preset_table.item(0, 1).text() == ""
    assert window.preset_table.item(0, 2).text() == "Embedded"
    assert window.preset_empty_state.isHidden()
    assert QSettings().value(window_state.RECENT_FILES_SETTINGS_KEY) == [path]

    window.close()


def test_startup_recent_files_selector_loads_selected_file(tmp_path, monkeypatch, app) -> None:
    older_file = tmp_path / "older.hls"
    recent_file = tmp_path / "recent.hlx"
    older_file.touch()
    recent_file.touch()
    older = str(older_file)
    recent_path = str(recent_file)
    recent = [older, recent_path]
    QSettings().setValue(window_state.RECENT_FILES_SETTINGS_KEY, recent)
    window = MainWindow()
    _mock_single_hlx_handler(monkeypatch, name="Recent")

    assert window.recent_files.isEnabled()
    assert window.recent_files.itemText(0) == "Open recent file..."
    assert window.recent_files.itemData(1) == older
    assert "older.hls" in window.recent_files.itemText(1)

    window._recent_file_activated(2)

    assert window.input_path.text() == recent_path
    assert window.preset_table.rowCount() == 1
    assert window.preset_table.item(0, 2).text() == "Recent"
    assert QSettings().value(window_state.RECENT_FILES_SETTINGS_KEY) == [recent_path, older]

    window.close()


def test_startup_recent_files_selector_is_disabled_without_history(app) -> None:
    window = MainWindow()

    assert not window.recent_files.isEnabled()
    assert window.recent_files.count() == 1
    assert window.recent_files.itemText(0) == "Open recent file..."

    window.close()


def test_closing_main_window_can_cancel_discarding_manual_table_changes(monkeypatch, app) -> None:
    window = MainWindow()
    window.preset_table.insertRow(0)
    window.preset_table.setItem(0, 1, QTableWidgetItem("02B"))
    window.preset_table.setItem(0, 2, QTableWidgetItem("Song"))
    window.preset_table_controller.clear_preset_adjustments(0)
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


def test_loaded_file_updates_window_title_and_save_as_state(monkeypatch, app) -> None:
    window = MainWindow()
    _mock_single_hlx_handler(monkeypatch)
    assert not window.start_button.isEnabled()
    assert not window.determine_parameters_button.isEnabled()
    window.input_path.setText("/tmp/input.hlx")

    window.load_assignments()

    assert window.windowTitle() == "input.hlx"
    assert window.save_as_action.isEnabled()
    assert window.start_button.isEnabled()
    assert window.determine_parameters_button.isEnabled()
    assert window.determine_parameters_hint.isHidden()
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
    stub_gui_settings(monkeypatch, request)
    monkeypatch.setattr(
        gui_worker,
        "collect_windows_hardware_diagnostics",
        lambda checked_request: (
            checks.append(checked_request)
            or [DiagnosticCheck("windows_hardware_check", "pass", "ok")]
        ),
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
    request = _request(
        backend="hardware",
        audio_device="Line 6 Helix",
        sample_rate=48000,
        input_mapping="1,2",
        output_mapping="3,4",
        steering_output="Helix MIDI",
    )
    popups = []
    checks = []
    monkeypatch.setattr(window, "_backend_check_enabled", lambda: True)
    stub_gui_settings(monkeypatch, request)
    monkeypatch.setattr(
        gui_worker,
        "collect_windows_hardware_diagnostics",
        lambda checked_request: (
            checks.append(checked_request)
            or [
                DiagnosticCheck(
                    "audio_device",
                    "fail",
                    "no audio device",
                    "audio_device=Line 6 Helix",
                )
            ]
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
    assert "no audio device" in popups[0][2]
    assert "audio_device=Line 6 Helix" in popups[0][2]
    assert "Preflight check" in popups[0][2]
    assert any("Hardware check failed: no audio device" in entry[2] for entry in window.log_entries)
    assert any(
        "backend=hardware" in entry[2]
        and "sample_rate=48000" in entry[2]
        and "midi_output=Helix MIDI" in entry[2]
        for entry in window.log_entries
    )
    assert window.worker is None
    assert window.hardware_check_worker is None
    assert window.hardware_check_overlay.isHidden()
    assert window._available_backend is None

    window.close()


def test_hardware_check_warning_logs_and_allows_normalization(monkeypatch, app) -> None:
    window = MainWindow()
    request = _request(backend="hardware")
    checks = []
    monkeypatch.setattr(window, "_backend_check_enabled", lambda: True)
    stub_gui_settings(monkeypatch, request)
    monkeypatch.setattr(
        gui_worker,
        "collect_windows_hardware_diagnostics",
        lambda checked_request: (
            checks.append(checked_request)
            or [
                DiagnosticCheck("audio_device", "pass", "Audio device resolved"),
                DiagnosticCheck(
                    "midi_output",
                    "warning",
                    "MIDI output not selected",
                    "steering_output=None",
                ),
            ]
        ),
    )
    monkeypatch.setattr(main_window.NormalizationWorker, "start", lambda self: None)

    window.start_normalization()

    for _ in range(100):
        app.processEvents()
        if window.worker is not None and window.hardware_check_worker is None:
            break
        time.sleep(0.01)

    assert len(checks) == 1
    assert window.worker is not None
    assert any(
        "Hardware check warning: MIDI output not selected" in entry[2]
        for entry in window.log_entries
    )
    assert window._available_backend == "hardware"

    window.worker_finished()
    window.close()


def test_old_string_hardware_failure_path_still_shows_error(monkeypatch, app) -> None:
    window = MainWindow()
    request = _request(backend="hardware")
    popups = []
    window._pending_backend_check_request = request
    window._pending_backend_check_action = "normalization"
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: popups.append(args))

    window._hardware_check_failed("legacy failure")

    assert popups
    assert popups[0][1] == "Error"
    assert "No suitable device connected" in popups[0][2]
    assert "legacy failure" in popups[0][2]
    assert window._available_backend is None

    window.close()


def test_switching_backend_only_rechecks_on_next_normalization(monkeypatch, app) -> None:
    window = MainWindow()
    request = _request(backend="hardware")
    checks = []
    monkeypatch.setattr(window, "_backend_check_enabled", lambda: True)
    stub_gui_settings(monkeypatch, request)
    monkeypatch.setattr(
        gui_worker,
        "collect_windows_hardware_diagnostics",
        lambda checked_request: (
            checks.append(checked_request)
            or [DiagnosticCheck("windows_hardware_check", "pass", "ok")]
        ),
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
    stub_gui_settings(monkeypatch, request)
    monkeypatch.setattr(
        gui_worker,
        "collect_windows_hardware_diagnostics",
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
    stub_gui_settings(monkeypatch, request)
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
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    stub_gui_settings(monkeypatch, _request())

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
