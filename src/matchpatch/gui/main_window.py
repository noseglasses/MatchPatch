"""Main MatchPatch GUI window."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread
from PySide6.QtGui import QCloseEvent, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from matchpatch.config import config_value, load_config
from matchpatch.devices import get_device_profile, list_device_profiles
from matchpatch.gui.device_panels import HelixSettingsPanel
from matchpatch.gui.worker import NormalizationWorker
from matchpatch.normalize import apply_config, parse_args, request_from_args
from matchpatch.progress import ProgressEvent
from matchpatch.workflow import ImportRequest, NormalizationResult


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MatchPatch")
        self.resize(820, 860)
        self.worker_thread: QThread | None = None
        self.worker: NormalizationWorker | None = None
        self.device_panels: dict[str, HelixSettingsPanel] = {}

        content = QWidget()
        self.setCentralWidget(content)
        layout = QVBoxLayout(content)
        layout.addWidget(self._build_inputs())
        layout.addWidget(self._build_presets())
        layout.addWidget(self._build_device_settings())
        layout.addWidget(self._build_progress())
        self.start_button = QPushButton("Start normalization")
        self.start_button.clicked.connect(self.start_normalization)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_normalization)
        buttons = QHBoxLayout()
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)
        self._populate_devices()
        self.load_defaults()

    def _build_inputs(self) -> QGroupBox:
        group = QGroupBox("Normalization")
        form = QFormLayout(group)
        self.input_path = QLineEdit()
        input_browse = QPushButton("Browse")
        input_browse.clicked.connect(self.browse_input)
        form.addRow("Input patch", _path_row(self.input_path, input_browse))
        self.device = QComboBox()
        self.device.currentIndexChanged.connect(self.device_changed)
        form.addRow("Device", self.device)
        self.backend = QComboBox()
        self.backend.addItems(["loopback", "simulated", "hardware"])
        self.backend.currentTextChanged.connect(self.backend_changed)
        form.addRow("Backend", self.backend)
        self.config_path = QLineEdit()
        config_browse = QPushButton("Load config")
        config_browse.clicked.connect(self.browse_config)
        form.addRow("Config TOML", _path_row(self.config_path, config_browse))
        self.reference_di = QLineEdit()
        reference_browse = QPushButton("Browse")
        reference_browse.clicked.connect(self.browse_reference)
        form.addRow("Reference DI", _path_row(self.reference_di, reference_browse))
        self.target_lufs = QLineEdit("-16.0")
        form.addRow("Target LUFS", self.target_lufs)
        self.ignore_bad_lufs = QCheckBox()
        form.addRow("Ignore bad LUFS", self.ignore_bad_lufs)
        self.keep_temp = QCheckBox()
        form.addRow("Keep temporary files", self.keep_temp)
        self.limit = QSpinBox()
        self.limit.setRange(0, 128)
        self.limit.setSpecialValueText("All")
        form.addRow("Preset limit", self.limit)
        return group

    def _build_presets(self) -> QGroupBox:
        group = QGroupBox("Presets")
        layout = QVBoxLayout(group)
        self.preset_hint = QLabel("Choose an .hls or .hlx file.")
        self.preset_list = QListWidget()
        self.single_slot = QLineEdit()
        self.single_slot.setPlaceholderText("Temporary slot, for example 12A")
        self.single_slot.hide()
        layout.addWidget(self.preset_hint)
        layout.addWidget(self.preset_list)
        layout.addWidget(self.single_slot)
        return group

    def _build_device_settings(self) -> QGroupBox:
        group = QGroupBox("Device settings")
        layout = QVBoxLayout(group)
        self.device_stack = QStackedWidget()
        layout.addWidget(self.device_stack)
        return group

    def _build_progress(self) -> QGroupBox:
        group = QGroupBox("Progress")
        layout = QVBoxLayout(group)
        self.phase = QLabel("Ready")
        self.current = QLabel("")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.phase)
        layout.addWidget(self.current)
        layout.addWidget(self.progress)
        layout.addWidget(self.log)
        return group

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
        panel = self.device_panels.get(self.device.currentData())
        if panel is not None:
            panel.set_hardware_enabled(self.backend.currentText() != "loopback")

    def load_defaults(self) -> None:
        if not self.device.currentData():
            return

        try:
            config = load_config(self.config_path.text().strip() or None)
            self.backend.setCurrentText(
                config_value(config, "normalize", "backend", default="loopback")
            )
            args = apply_config(parse_args(self._base_argv("placeholder.hls")))
        except Exception as exc:  # noqa: BLE001
            self.show_error(str(exc))
            return

        self.backend.setCurrentText(args.backend)
        self.reference_di.setText(str(args.reference_di))
        self.target_lufs.setText(str(args.target_lufs))
        self.ignore_bad_lufs.setChecked(args.ignore_bad_lufs)
        panel = self.device_panels.get(args.device)
        if panel is not None:
            panel.populate(args)
        self.backend_changed()

    def load_assignments(self) -> None:
        self.preset_list.clear()
        path = Path(self.input_path.text())
        self.single_slot.setVisible(path.suffix.lower() == ".hlx")
        self.preset_list.setVisible(path.suffix.lower() != ".hlx")

        if path.suffix.lower() == ".hlx":
            self.preset_hint.setText("Choose the temporary Helix slot used during measurement.")
            return

        try:
            profile = get_device_profile(self.device.currentData())
            handler = profile.create_patch_file_handler(Path(__file__).resolve().parents[3])
            handler.validate_input(path)
            for assignment in handler.list_assignments(path):
                item = QListWidgetItem(f"{assignment.device_patch}  {assignment.name}")
                item.setData(Qt.ItemDataRole.UserRole, assignment.device_patch)
                item.setCheckState(Qt.CheckState.Checked)
                self.preset_list.addItem(item)
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
        self.phase.setText("Starting")
        self.worker_thread = QThread(self)
        self.worker = NormalizationWorker(request)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.update_progress)
        self.worker.import_requested.connect(self.confirm_import)
        self.worker.completed.connect(self.normalization_completed)
        self.worker.failed.connect(self.show_error)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_finished)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.start()

    def update_progress(self, event: ProgressEvent) -> None:
        if event.phase:
            self.phase.setText(event.phase.replace("_", " ").title())

        if event.device_patch:
            text = f"Preset {event.device_patch}"
            if event.snapshot is not None:
                text += f", snapshot {event.snapshot}/{event.snapshot_total}"
            self.current.setText(text)

        if event.preset_total and event.snapshot_total and event.preset_index:
            total = event.preset_total * event.snapshot_total
            snapshot = event.snapshot or 1
            value = (event.preset_index - 1) * event.snapshot_total + snapshot
            self.progress.setRange(0, total)
            self.progress.setValue(value)

        message = event.message or event.kind.replace("_", " ")
        if event.lufs is not None and event.crest_factor_db is not None:
            message += f": {event.lufs:.3f} LUFS, {event.crest_factor_db:.3f} dB crest"
        self.log.append(message)

    def confirm_import(self, request: ImportRequest) -> None:
        answer = QMessageBox.question(
            self,
            "Import processor file",
            request.message,
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        )
        if self.worker is not None:
            self.worker.answer_import(answer == QMessageBox.StandardButton.Ok)

    def normalization_completed(self, result: NormalizationResult) -> None:
        self.phase.setText("Completed")
        self.log.append(f"Output: {result.output_path}")
        QMessageBox.information(self, "MatchPatch", f"Adjusted file written:\n{result.output_path}")

    def show_error(self, message: str) -> None:
        self.phase.setText("Error")
        self.log.append(message)
        QMessageBox.critical(self, "MatchPatch error", message)

    def worker_finished(self) -> None:
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.worker = None
        self.worker_thread = None

    def cancel_normalization(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.phase.setText("Cancelling")

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.worker is not None:
            self.worker.cancel()
        if self.worker_thread is not None:
            self.worker_thread.quit()
            self.worker_thread.wait()
        super().closeEvent(event)

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
        argv.append(
            "--ignore-bad-lufs" if self.ignore_bad_lufs.isChecked() else "--no-ignore-bad-lufs"
        )
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
        for index in range(self.preset_list.count()):
            item = self.preset_list.item(index)
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(item.data(Qt.ItemDataRole.UserRole))
        return ",".join(selected)


def _path_row(field: QLineEdit, button: QPushButton) -> QWidget:
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(field)
    layout.addWidget(button)
    return widget
