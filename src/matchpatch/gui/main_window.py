"""Main MatchPatch GUI window."""

from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Iterator

from PySide6.QtCore import QThread, QTimer
from PySide6.QtGui import QBrush, QCloseEvent, QColor, QIcon, Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from matchpatch.config import config_value, load_config
from matchpatch.devices import get_device_profile, list_device_profiles
from matchpatch.gui.collapsible import CollapsibleSection
from matchpatch.gui.device_panels import HelixSettingsPanel
from matchpatch.gui.dialogs import ASSETS_DIR, AboutDialog, HelpDialog
from matchpatch.gui.snapshot_header import SnapshotHeader
from matchpatch.gui.worker import NormalizationWorker
from matchpatch.normalize import apply_config, parse_args, request_from_args
from matchpatch.progress import ProgressEvent
from matchpatch.workflow import ImportRequest, NormalizationResult

GAIN_CORRECTION_PATTERN = re.compile(
    r"^\[GAIN\] (?P<patch>\d{2}[A-D]) (?P<label>.*?) \| "
    r"(?P<before>-?\d+(?:\.\d+)?) dB -> (?P<after>-?\d+(?:\.\d+)?) dB "
    r"\(Delta: (?P<delta>[+-]\d+(?:\.\d+)?) dB\)$"
)
GAIN_STABLE_PATTERN = re.compile(
    r"^\[GAIN\] (?P<patch>\d{2}[A-D]) (?P<label>.*?) \| "
    r"stable at (?P<after>-?\d+(?:\.\d+)?) dB "
    r"\(Delta: (?P<delta>[+-]\d+(?:\.\d+)?) dB\)$"
)
GAIN_BAD_LUFS_PATTERN = re.compile(
    r"^\[GAIN\] (?P<patch>\d{2}[A-D]) (?P<label>.*?) \| bad LUFS(?: \(.*\))?$"
)
BAD_LUFS_ROW_BACKGROUND = QColor("#fee2e2")
PHASE_ICON = {
    "ready": QStyle.StandardPixmap.SP_DialogApplyButton,
    "starting": QStyle.StandardPixmap.SP_MediaPlay,
    "preparing_reamp": QStyle.StandardPixmap.SP_BrowserReload,
    "waiting_for_reamp_import": QStyle.StandardPixmap.SP_MediaPause,
    "measuring": QStyle.StandardPixmap.SP_ComputerIcon,
    "applying": QStyle.StandardPixmap.SP_BrowserReload,
    "completed": QStyle.StandardPixmap.SP_DialogApplyButton,
    "waiting_for_adjusted_import": QStyle.StandardPixmap.SP_MediaPause,
    "error": QStyle.StandardPixmap.SP_MessageBoxWarning,
    "cancelling": QStyle.StandardPixmap.SP_MessageBoxWarning,
    "normalization_cancelled_by_user": QStyle.StandardPixmap.SP_MessageBoxWarning,
}


def _phase_text(phase: str) -> str:
    if phase == "normalization_cancelled_by_user":
        return "Normalization cancelled by user"
    return phase.replace("_", " ").title()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MatchPatch")
        self.setWindowIcon(QIcon(str(ASSETS_DIR / "matchmatch-icon.png")))
        self.setMinimumSize(620, 480)
        screen = QApplication.primaryScreen()
        available_height = screen.availableGeometry().height() if screen is not None else 800
        self.resize(820, min(760, max(560, available_height - 100)))
        self.worker_thread: QThread | None = None
        self.worker: NormalizationWorker | None = None
        self.device_panels: dict[str, HelixSettingsPanel] = {}
        self.snapshot_count = 4
        self.preset_snapshot_positions: dict[str, int] = {}
        self.log_entries: list[tuple[str, str, str]] = []
        self.busy_timer = QTimer(self)
        self.busy_timer.setSingleShot(True)
        self.busy_timer.setInterval(2000)
        self.busy_timer.timeout.connect(self._show_busy_progress)

        content = QWidget()
        self.content = content
        scroll = QScrollArea()
        self.scroll_area = scroll
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        self.setCentralWidget(scroll)
        self._build_footer()
        layout = QVBoxLayout(content)
        layout.addWidget(self._build_inputs())
        layout.addWidget(self._build_advanced())
        self.start_button = QPushButton("Start normalization")
        self.start_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.start_button.setToolTip("Start the guided preset-normalization workflow.")
        self.start_button.clicked.connect(self.start_normalization)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton)
        )
        self.cancel_button.setToolTip("Stop the currently running normalization workflow.")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_normalization)
        buttons = QHBoxLayout()
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)
        layout.addWidget(self._build_progress())
        layout.addWidget(self._build_retained_csv())
        layout.addStretch()
        self._set_phase("ready")
        self._populate_devices()
        self.load_defaults()
        QTimer.singleShot(0, self._resize_to_initial_content)

    def _build_inputs(self) -> QGroupBox:
        group = QGroupBox("General")
        self.general = group
        layout = QGridLayout(group)
        self.input_path = QLineEdit()
        input_browse = QPushButton("Browse")
        input_browse.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
        input_browse.setToolTip("Choose the Helix setlist or preset file to normalize.")
        input_browse.clicked.connect(self.browse_input)
        layout.addWidget(
            _label("Setlist/Preset file", "The Helix .hls setlist or .hlx preset to normalize."),
            0,
            0,
        )
        layout.addWidget(_path_row(self.input_path, input_browse), 0, 1)
        self.device = QComboBox()
        self.device.currentIndexChanged.connect(self.device_changed)
        layout.addWidget(
            _label("Device", "The audio processor profile used by this workflow."), 1, 0
        )
        layout.addWidget(self.device, 1, 1)
        help_button = QPushButton("Help")
        help_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogHelpButton))
        help_button.setToolTip("Open the guided MatchPatch usage instructions.")
        help_button.clicked.connect(self.show_help)
        about_button = QPushButton("About")
        about_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation)
        )
        about_button.setToolTip("Show project version, license, and repository information.")
        about_button.clicked.connect(self.show_about)
        layout.addWidget(help_button, 0, 2)
        layout.addWidget(about_button, 1, 2)
        layout.setColumnStretch(1, 1)
        return group

    def _build_presets(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        self.preset_hint = QLabel("Choose an .hls or .hlx file.")
        self.preset_table = QTableWidget()
        self.preset_table.setHorizontalHeader(SnapshotHeader(self.preset_table))
        self.preset_table.verticalHeader().hide()
        self.preset_table.setWordWrap(False)
        self.preset_table.setToolTip(
            "Select presets and inspect snapshot names and calculated output-gain adjustments."
        )
        self._configure_snapshot_columns(self.snapshot_count)
        self.preset_table.itemChanged.connect(self._preset_item_changed)
        self.preset_table.setSortingEnabled(True)
        self.preset_table.setMinimumHeight(160)
        self.preset_table_note = QLabel("Only non-empty presets are listed.")
        self.single_slot = QLineEdit()
        self.single_slot.setPlaceholderText("Temporary slot, for example 12A")
        self.single_slot.hide()
        layout.addWidget(self.preset_hint)
        selection_buttons = QHBoxLayout()
        self.select_all_button = QPushButton("Select all")
        self.select_all_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
        )
        self.select_all_button.setToolTip("Include every preset in this setlist.")
        self.select_all_button.clicked.connect(lambda: self.set_all_presets_checked(True))
        self.unselect_all_button = QPushButton("Unselect all")
        self.unselect_all_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogResetButton)
        )
        self.unselect_all_button.setToolTip("Exclude every preset in this setlist.")
        self.unselect_all_button.clicked.connect(lambda: self.set_all_presets_checked(False))
        selection_buttons.addWidget(self.select_all_button)
        selection_buttons.addWidget(self.unselect_all_button)
        self.limit = QSpinBox()
        self.limit.setRange(0, 128)
        self.limit.setSpecialValueText("All")
        selection_buttons.addWidget(
            _label("Preset limit", "Optionally process only the first selected presets.")
        )
        selection_buttons.addWidget(self.limit)
        selection_buttons.addStretch()
        layout.addLayout(selection_buttons)
        layout.addWidget(self.preset_table)
        layout.addWidget(self.preset_table_note)
        layout.addWidget(self.single_slot)
        self.presets = content
        return content

    def _build_device_settings(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        self.device_stack = QStackedWidget()
        layout.addWidget(self.device_stack)
        self.device_settings = content
        return content

    def _build_progress(self) -> QWidget:
        pane = QWidget()
        self.progress_group = pane
        pane.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)
        self.current = QLabel("")
        self.preset_progress = QProgressBar()
        self.preset_progress.setRange(0, 1)
        layout.addWidget(self.current)
        layout.addWidget(self.preset_progress)
        pane.hide()
        return pane

    def _build_retained_csv(self) -> QWidget:
        pane = QWidget()
        self.retained_csv_pane = pane
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)
        self.retained_csv_label = _label(
            "Retained CSV", "Exact measurement CSV path when temporary files are retained."
        )
        self.retained_csv = QLineEdit()
        self.retained_csv.setReadOnly(True)
        layout.addWidget(self.retained_csv_label)
        layout.addWidget(self.retained_csv)
        pane.hide()
        return pane

    def _build_footer(self) -> None:
        self.phase_icon = QLabel()
        self.phase_icon.setFixedSize(16, 16)
        self.phase = QLabel()
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(160)
        self.progress.hide()
        footer = self.statusBar()
        footer.addWidget(self.phase_icon)
        footer.addWidget(self.phase)
        footer.addPermanentWidget(self.progress)

    def _build_log(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        filter_row = QHBoxLayout()
        filter_row.addWidget(
            _label("Minimum log level", "Hide log entries below the selected severity.")
        )
        self.log_level = QComboBox()
        self.log_level.addItems(["Debug", "Info", "Warning", "Error"])
        self.log_level.setCurrentText("Info")
        self.log_level.currentTextChanged.connect(self._refresh_log)
        filter_row.addWidget(self.log_level)
        filter_row.addStretch()
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(140)
        self.log_section = self.log
        layout.addLayout(filter_row)
        layout.addWidget(self.log)
        return content

    def _build_advanced(self) -> CollapsibleSection:
        content = QWidget()
        layout = QVBoxLayout(content)
        self.advanced_tabs = QTabWidget()
        self.advanced_tabs.addTab(self._build_presets(), "Presets")
        self.advanced_tabs.addTab(self._build_device_settings(), "Device")
        self.advanced_tabs.addTab(self._build_misc(), "Misc")
        self.advanced_tabs.addTab(self._build_log(), "Log")
        self.advanced_tabs.currentChanged.connect(self._schedule_resize_for_content)
        layout.addWidget(self.advanced_tabs)
        self.advanced = CollapsibleSection("Advanced", content)
        self.advanced.toggle_button.toggled.connect(self._schedule_resize_for_content)
        self.advanced.setToolTip("Show less frequently changed settings and diagnostic details.")
        return self.advanced

    def _build_misc(self) -> QWidget:
        content = QWidget()
        form = QFormLayout(content)
        self.backend = QComboBox()
        self.backend.addItems(["hardware", "loopback", "simulated"])
        self.backend.currentTextChanged.connect(self.backend_changed)
        form.addRow(
            _label("Backend", "Select loopback for testing or hardware for a connected device."),
            self.backend,
        )
        self.config_path = QLineEdit()
        config_browse = QPushButton("Browse")
        config_browse.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
        config_browse.setToolTip("Choose an optional TOML configuration file.")
        config_browse.clicked.connect(self.browse_config)
        form.addRow(
            _label("Config file", "Optional TOML file providing saved MatchPatch defaults."),
            _path_row(self.config_path, config_browse),
        )
        self.reference_di = QLineEdit()
        reference_browse = QPushButton("Browse")
        reference_browse.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton)
        )
        reference_browse.setToolTip("Choose the clean DI WAV used for reamping measurements.")
        reference_browse.clicked.connect(self.browse_reference)
        form.addRow(
            _label("Reference DI", "Clean guitar DI WAV replayed through each preset."),
            _path_row(self.reference_di, reference_browse),
        )
        self.target_lufs = QLineEdit("-16.0")
        form.addRow(
            _label("Target LUFS", "Desired loudness used to calculate snapshot gain corrections."),
            self.target_lufs,
        )
        self.keep_temp = QCheckBox()
        form.addRow(
            _label(
                "Keep temporary files",
                "Retain the measurement CSV for inspection after processing.",
            ),
            self.keep_temp,
        )
        self.solo_gain_bump_db = QLineEdit("3.0")
        form.addRow(
            _label(
                "Solo boost (dB)", "Additional output gain added to snapshots identified as solos."
            ),
            self.solo_gain_bump_db,
        )
        self.solo_regex = QLineEdit(r"(?i)\bsolo\b")
        self.solo_regex.setToolTip(
            "Case-insensitive regular expression used to identify solo snapshots."
        )
        form.addRow(
            _label(
                "Solo snapshot regex", "Regular expression used to identify solo snapshot names."
            ),
            self.solo_regex,
        )
        return content

    def _populate_devices(self) -> None:
        for profile in list_device_profiles():
            self.device.addItem(profile.display_name, profile.name)
            if profile.name == "helix":
                panel = HelixSettingsPanel()
                self.device_panels[profile.name] = panel
                self.device_stack.addWidget(panel)

    def browse_input(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose patch file", filter="Patches (*.hls *.hlx)"
        )
        if path:
            self.input_path.setText(path)
            self.load_assignments()

    def show_help(self) -> None:
        HelpDialog(self).exec()

    def show_about(self) -> None:
        AboutDialog(self).exec()

    def browse_reference(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose reference DI", filter="Audio (*.wav)")
        if path:
            self.reference_di.setText(path)

    def browse_config(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose config", filter="TOML (*.toml)")
        if path:
            self.config_path.setText(path)
            self.load_defaults()

    def device_changed(self) -> None:
        name = self.device.currentData()
        panel = self.device_panels.get(name)
        if panel is not None:
            self.device_stack.setCurrentWidget(panel)
        self.load_defaults()

    def backend_changed(self) -> None:
        if self.backend.currentText() == "loopback":
            self.device_settings.setToolTip(
                "Audio and MIDI settings are editable but unused by the loopback backend."
            )
        else:
            self.device_settings.setToolTip("")

    def load_defaults(self) -> None:
        if not self.device.currentData():
            return

        try:
            config = load_config(self.config_path.text().strip() or None)
            self.backend.setCurrentText(
                config_value(config, "normalize", "backend", default="hardware")
            )
            args = apply_config(parse_args(self._base_argv("placeholder.hls")))
        except Exception as exc:  # noqa: BLE001
            self.show_error(str(exc))
            return

        self.backend.setCurrentText(args.backend)
        self.reference_di.setText(str(args.reference_di))
        self.target_lufs.setText(str(args.target_lufs))
        self.solo_gain_bump_db.setText(str(args.policy.solo_gain_bump_db))
        self.solo_regex.setText(args.policy.solo_regex)
        self._configure_snapshot_columns(args.policy.snapshot_count)
        panel = self.device_panels.get(args.device)
        if panel is not None:
            panel.populate(args)
        self.backend_changed()

    def load_assignments(self) -> None:
        self.preset_snapshot_positions.clear()
        self._clear_bad_lufs_highlights()
        path = Path(self.input_path.text())
        is_single_preset = path.suffix.lower() == ".hlx"
        self.single_slot.setVisible(is_single_preset)
        self.preset_table.setVisible(not is_single_preset)
        self.preset_table_note.setVisible(not is_single_preset)
        self.select_all_button.setVisible(not is_single_preset)
        self.unselect_all_button.setVisible(not is_single_preset)

        if path.suffix.lower() == ".hlx":
            self.preset_table.setRowCount(0)
            self.preset_hint.setText("Choose the temporary Helix slot used during measurement.")
            return

        try:
            profile = get_device_profile(self.device.currentData())
            handler = profile.create_patch_file_handler(Path(__file__).resolve().parents[3])
            handler.validate_input(path)
            with self._sorting_paused():
                self.preset_table.setRowCount(0)
                for assignment in handler.list_assignments(path):
                    row = self.preset_table.rowCount()
                    self.preset_table.insertRow(row)
                    selected = QTableWidgetItem()
                    selected.setCheckState(Qt.CheckState.Checked)
                    self.preset_table.setItem(row, 0, selected)
                    self.preset_table.setItem(row, 1, QTableWidgetItem(assignment.device_patch))
                    self.preset_table.setItem(row, 2, QTableWidgetItem(assignment.name))
                    self._clear_preset_adjustments(row)
                    self._set_snapshot_names(row, assignment.snapshot_names)
        except Exception as exc:  # noqa: BLE001
            self.show_error(str(exc))
            return

        self.preset_hint.setText("Select the presets to normalize.")

    def start_normalization(self) -> None:
        try:
            args = apply_config(parse_args(self._build_argv()))
            request = request_from_args(args)
        except Exception as exc:  # noqa: BLE001
            self.show_error(str(exc))
            return

        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.log.clear()
        self.log_entries.clear()
        self.preset_snapshot_positions.clear()
        self._clear_bad_lufs_highlights()
        with self._sorting_paused():
            for row in range(self.preset_table.rowCount()):
                self._clear_preset_adjustments(row)
        self.retained_csv.clear()
        self.retained_csv_pane.hide()
        self._set_phase("starting")
        self._log("Normalization started", "info")
        self._log(f"Backend: {getattr(request, 'backend', 'unknown')}", "info")
        self._start_busy_phase()
        self.worker_thread = QThread(self)
        self.worker = NormalizationWorker(request)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.update_progress)
        self.worker.import_requested.connect(self.confirm_import)
        self.worker.completed.connect(self.normalization_completed)
        self.worker.cancelled.connect(self.normalization_cancelled)
        self.worker.failed.connect(self.show_error)
        self.worker.finished.connect(self.worker_thread.quit, Qt.ConnectionType.DirectConnection)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_finished)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.start()

    def update_progress(self, event: ProgressEvent) -> None:
        if event.phase:
            self._set_phase(event.phase)
            self.progress_group.hide()
            if event.phase in {
                "completed",
                "waiting_for_reamp_import",
                "waiting_for_adjusted_import",
            }:
                self._stop_busy_phase()
            else:
                self._start_busy_phase()

        if event.device_patch:
            text = self._preset_progress_text(event)
            if event.snapshot is not None:
                text += self._snapshot_progress_text(event)
            self.current.setText(text)

        if event.preset_total and event.snapshot_total and event.preset_index:
            self.busy_timer.stop()
            self.progress.hide()
            self.progress_group.show()
            total = event.preset_total * event.snapshot_total
            snapshot = event.snapshot or 1
            value = (event.preset_index - 1) * event.snapshot_total + snapshot
            self.preset_progress.setRange(0, total)
            self.preset_progress.setValue(value)
        elif event.kind == "measurement_completed":
            self.progress_group.hide()

        message = event.message or event.kind.replace("_", " ")
        if event.kind == "log":
            self._apply_gain_correction(message)
        if event.lufs is not None and event.crest_factor_db is not None:
            message += f": {event.lufs:.3f} LUFS, {event.crest_factor_db:.3f} dB crest"
        if event.kind == "temp_retained" and event.path:
            self.retained_csv.setText(event.path)
            self.retained_csv_pane.show()

        if "bad LUFS" in message or message.startswith("[WARNING]"):
            level = "warning"
        else:
            level = "error" if event.kind in {"error_log", "preset_failed"} else "debug"
        self._log(message, level)

    def confirm_import(self, request: ImportRequest) -> None:
        self._stop_busy_phase()
        answer = QMessageBox.question(
            self,
            "Import preset/setlist file",
            request.message,
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        )
        if self.worker is not None:
            self.worker.answer_import(answer == QMessageBox.StandardButton.Ok)

    def normalization_completed(self, result: NormalizationResult) -> None:
        self._stop_busy_phase()
        self._set_phase("completed")
        if result.retained_csv_path is not None:
            self.retained_csv.setText(str(result.retained_csv_path))
            self.retained_csv_pane.show()
        self._log(f"Output: {result.output_path}", "success")

    def show_error(self, message: str) -> None:
        self._stop_busy_phase()
        self._set_phase("error")
        self._log(message, "error")
        QMessageBox.critical(self, "MatchPatch error", message)

    def normalization_cancelled(self) -> None:
        self._stop_busy_phase()
        self._set_phase("normalization_cancelled_by_user")
        self._log("Normalization cancelled by user", "warning")

    def worker_finished(self) -> None:
        self._stop_busy_phase()
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.worker = None
        self.worker_thread = None

    def cancel_normalization(self) -> None:
        if self.worker is not None and self._confirm_cancellation():
            self.worker.cancel()
            self._set_phase("cancelling")
            self._log("Cancellation requested", "warning")
            self._start_busy_phase()

    def _confirm_cancellation(self) -> bool:
        answer = QMessageBox.question(
            self,
            "Cancel measurement",
            "A measurement is currently running. Do you want to cancel it?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.worker is not None:
            if not self._confirm_cancellation():
                event.ignore()
                return
            self.worker.cancel()
        if self.worker_thread is not None:
            self.worker_thread.quit()
            self.worker_thread.wait()
        super().closeEvent(event)
        QApplication.quit()

    def _base_argv(self, input_path: str) -> list[str]:
        argv = [
            "--device",
            self.device.currentData(),
            "-i",
            input_path,
            "--automation",
            "--backend",
            self.backend.currentText(),
        ]
        if self.config_path.text().strip():
            argv.extend(["--config", self.config_path.text().strip()])
        return argv

    def _build_argv(self) -> list[str]:
        argv = self._base_argv(self.input_path.text().strip())
        argv.extend(["--reference-di", self.reference_di.text()])
        argv.extend(["--target-lufs", self.target_lufs.text()])
        argv.extend(["--solo-gain-bump-db", self.solo_gain_bump_db.text()])
        argv.extend(["--solo-regex", self.solo_regex.text()])
        if self.keep_temp.isChecked():
            argv.append("--keep-temp")
        if self.limit.value():
            argv.extend(["--limit", str(self.limit.value())])

        preset_set = self._selected_preset_set()
        if preset_set:
            argv.extend(["--preset-set", preset_set])

        panel = self.device_panels.get(self.device.currentData())
        if panel is not None:
            panel.append_arguments(argv)
        return argv

    def _selected_preset_set(self) -> str:
        if Path(self.input_path.text()).suffix.lower() == ".hlx":
            return self.single_slot.text().strip()

        selected = []
        for row in range(self.preset_table.rowCount()):
            selected_item = self.preset_table.item(row, 0)
            patch_item = self.preset_table.item(row, 1)
            if (
                selected_item is not None
                and patch_item is not None
                and selected_item.checkState() == Qt.CheckState.Checked
            ):
                selected.append(patch_item.text())
        return ",".join(selected)

    def set_all_presets_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        with self._sorting_paused():
            for row in range(self.preset_table.rowCount()):
                item = self.preset_table.item(row, 0)
                if item is not None:
                    item.setCheckState(state)

    def _set_phase(self, phase: str) -> None:
        self.phase.setText(_phase_text(phase))
        standard_pixmap = PHASE_ICON.get(phase.lower())
        icon = (
            self.style().standardIcon(standard_pixmap) if standard_pixmap is not None else QIcon()
        )
        self.phase_icon.setPixmap(icon.pixmap(16, 16))

    def _apply_gain_correction(self, message: str) -> None:
        match = (
            GAIN_CORRECTION_PATTERN.match(message)
            or GAIN_STABLE_PATTERN.match(message)
            or GAIN_BAD_LUFS_PATTERN.match(message)
        )
        if match is None:
            return

        row = self._preset_row(match["patch"])
        if row is None:
            return

        selected = self.preset_table.item(row, 0)
        if selected is None or selected.checkState() != Qt.CheckState.Checked:
            self._clear_preset_adjustments(row)
            return

        snapshot_position = self.preset_snapshot_positions.get(match["patch"], 0)
        if snapshot_position >= self.snapshot_count:
            return

        label = match["label"]
        is_solo = label.endswith(" (S)")
        if is_solo:
            label = label[:-4]
        name_column = 3 + snapshot_position * 2
        adjustment_column = name_column + 1
        name_item = self.preset_table.item(row, name_column)
        adjustment_item = self.preset_table.item(row, adjustment_column)
        if name_item is None or adjustment_item is None:
            return
        self._set_snapshot_name(name_item, label, is_solo)
        if match.re is GAIN_BAD_LUFS_PATTERN:
            adjustment_item.setText("⚠️")
            adjustment_item.setToolTip("This snapshot produced an unusable LUFS measurement.")
            adjustment_item.setForeground(QBrush(QColor("#b45309")))
            font = adjustment_item.font()
            font.setBold(True)
            font.setPointSize(max(font.pointSize(), QApplication.font().pointSize(), 9) + 5)
            adjustment_item.setFont(font)
            self._set_bad_lufs_highlight(row)
            self.preset_snapshot_positions[match["patch"]] = snapshot_position + 1
            return

        adjustment = match["delta"]
        self._set_adjustment_value(
            adjustment_item,
            adjustment,
            float(match["delta"]),
        )
        self.preset_snapshot_positions[match["patch"]] = snapshot_position + 1

    def _configure_snapshot_columns(self, snapshot_count: int) -> None:
        self.snapshot_count = snapshot_count
        labels = ["", "Preset", "Name"]
        for snapshot in range(1, snapshot_count + 1):
            labels.extend([str(snapshot), "Δ (dB)"])
        with self._sorting_paused():
            self.preset_table.setColumnCount(len(labels))
            self.preset_table.setHorizontalHeaderLabels(labels)
            header = self.preset_table.horizontalHeader()
            header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            header.setStretchLastSection(False)
            checkbox_width = self.style().pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth)
            checkbox_spacing = self.style().pixelMetric(QStyle.PixelMetric.PM_CheckBoxLabelSpacing)
            selection_width = checkbox_width + checkbox_spacing * 2
            header.setMinimumSectionSize(selection_width)
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
            self.preset_table.setColumnWidth(0, selection_width)
            self.preset_table.setColumnWidth(1, 52)
            self.preset_table.setColumnWidth(2, 120)
            for column in range(3, len(labels), 2):
                self.preset_table.setColumnWidth(column, 100)
                self.preset_table.setColumnWidth(column + 1, 62)
            for column, tooltip in enumerate(
                [
                    "Include this preset in normalization.",
                    "Processor slot containing the preset.",
                    "Preset name read from the input file.",
                    *(
                        tooltip
                        for snapshot in range(1, snapshot_count + 1)
                        for tooltip in (
                            f"Name of snapshot {snapshot} read from the input file.",
                            f"Calculated gain adjustment for snapshot {snapshot}.",
                        )
                    ),
                ]
            ):
                item = self.preset_table.horizontalHeaderItem(column)
                if item is not None:
                    item.setToolTip(tooltip)
            for row in range(self.preset_table.rowCount()):
                self._clear_preset_adjustments(row)

    @contextmanager
    def _sorting_paused(self) -> Iterator[None]:
        sorting_enabled = self.preset_table.isSortingEnabled()
        self.preset_table.setSortingEnabled(False)
        try:
            yield
        finally:
            self.preset_table.setSortingEnabled(sorting_enabled)

    def _clear_preset_adjustments(self, row: int) -> None:
        self._clear_bad_lufs_highlight(row)
        for column in range(3, self.preset_table.columnCount(), 2):
            name = self.preset_table.item(row, column)
            adjustment = self.preset_table.item(row, column + 1)
            if name is None:
                name = QTableWidgetItem()
                self.preset_table.setItem(row, column, name)
            if adjustment is None:
                adjustment = QTableWidgetItem()
                self.preset_table.setItem(row, column + 1, adjustment)
            self._set_adjustment_value(adjustment, "+0", 0)

    def _set_bad_lufs_highlight(self, row: int) -> None:
        for column in range(self.preset_table.columnCount()):
            item = self.preset_table.item(row, column)
            if item is not None:
                item.setBackground(BAD_LUFS_ROW_BACKGROUND)

    def _clear_bad_lufs_highlight(self, row: int) -> None:
        for column in range(self.preset_table.columnCount()):
            item = self.preset_table.item(row, column)
            if item is not None:
                item.setBackground(QBrush())

    def _clear_bad_lufs_highlights(self) -> None:
        for row in range(self.preset_table.rowCount()):
            self._clear_bad_lufs_highlight(row)

    def _set_snapshot_names(self, row: int, snapshot_names: tuple[str, ...]) -> None:
        try:
            solo_pattern = re.compile(self.solo_regex.text())
        except re.error:
            solo_pattern = None
        for snapshot, name in enumerate(snapshot_names[: self.snapshot_count]):
            item = self.preset_table.item(row, 3 + snapshot * 2)
            if item is not None:
                self._set_snapshot_name(
                    item,
                    name,
                    solo_pattern is not None and solo_pattern.search(name) is not None,
                )

    @staticmethod
    def _set_snapshot_name(item: QTableWidgetItem, name: str, is_solo: bool) -> None:
        item.setText(name)
        item.setIcon(QIcon())
        item.setToolTip("Solo snapshot" if is_solo else "")
        table = item.tableWidget()
        if table is None:
            return
        if not is_solo:
            table.removeCellWidget(item.row(), item.column())
            return
        label = QLabel(f"{escape(name)} <span style='color: #f59e0b;'>★</span>")
        label.setContentsMargins(3, 0, 0, 0)
        label.setToolTip("Solo snapshot")
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        table.setCellWidget(item.row(), item.column(), label)

    def _preset_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() == 0 and item.checkState() != Qt.CheckState.Checked:
            self._clear_preset_adjustments(item.row())

    def _preset_row(self, patch: str) -> int | None:
        for row in range(self.preset_table.rowCount()):
            item = self.preset_table.item(row, 1)
            if item is not None and item.text() == patch:
                return row
        return None

    def _log(self, message: str, level: str) -> None:
        timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
        self.log_entries.append((timestamp, level, message))
        if self._log_is_visible(level):
            self.log.append(self._format_log_entry(timestamp, level, message))

    def _refresh_log(self) -> None:
        self.log.clear()
        for timestamp, level, message in self.log_entries:
            if self._log_is_visible(level):
                self.log.append(self._format_log_entry(timestamp, level, message))

    def _log_is_visible(self, level: str) -> bool:
        priorities = {"debug": 10, "info": 20, "success": 20, "warning": 30, "error": 40}
        selected = self.log_level.currentText().lower()
        return priorities.get(level, 20) >= priorities[selected]

    @staticmethod
    def _format_log_entry(timestamp: str, level: str, message: str) -> str:
        colors = {
            "debug": "#6b7280",
            "info": "#2563eb",
            "success": "#15803d",
            "warning": "#b45309",
            "error": "#b91c1c",
        }
        color = colors.get(level, colors["info"])
        return (
            f'<span style="color:{color}">[{timestamp}] {escape(level.upper())}: '
            f"{escape(message)}</span>"
        )

    @staticmethod
    def _set_adjustment_value(item: QTableWidgetItem, text: str, value: float) -> None:
        item.setText("0" if value == 0 else text)
        item.setToolTip("")
        font = item.font()
        font.setBold(False)
        font.setPointSize(max(QApplication.font().pointSize(), 9))
        item.setFont(font)
        color = "#15803d" if value > 0 else "#b91c1c" if value < 0 else None
        item.setForeground(QBrush(QColor(color)) if color is not None else QBrush())

    def _resize_to_initial_content(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        viewport = self.scroll_area.viewport()
        chrome_width = self.width() - viewport.width()
        chrome_height = self.height() - viewport.height()
        hint = self.content.sizeHint()
        height = hint.height() + chrome_height + 4
        if self.advanced.is_expanded() and self.advanced_tabs.currentWidget() is self.presets:
            height = available.height()
        self.resize(
            min(max(820, hint.width() + chrome_width + 4), available.width()),
            min(height, available.height()),
        )

    def _schedule_resize_for_content(self) -> None:
        QTimer.singleShot(0, self._resize_to_initial_content)

    def _start_busy_phase(self) -> None:
        self.busy_timer.start()
        self.progress.hide()

    def _show_busy_progress(self) -> None:
        self.progress.show()

    def _stop_busy_phase(self) -> None:
        self.busy_timer.stop()
        self.progress.hide()
        self.progress_group.hide()

    def _preset_progress_text(self, event: ProgressEvent) -> str:
        row = self._preset_row(event.device_patch or "")
        if row is None:
            return f"Preset {event.device_patch}"
        name = self.preset_table.item(row, 2)
        if name and name.text():
            return f"Preset {event.device_patch}: {name.text()}"
        return f"Preset {event.device_patch}"

    def _snapshot_progress_text(self, event: ProgressEvent) -> str:
        text = f", snapshot {event.snapshot}/{event.snapshot_total}"
        row = self._preset_row(event.device_patch or "")
        if row is None or event.snapshot is None:
            return text
        name = self.preset_table.item(row, 3 + (event.snapshot - 1) * 2)
        return f"{text}: {name.text()}" if name and name.text() else text


def _path_row(field: QLineEdit, button: QPushButton) -> QWidget:
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(field)
    layout.addWidget(button)
    return widget


def _label(text: str, tooltip: str) -> QLabel:
    label = QLabel(text)
    label.setToolTip(tooltip)
    return label
