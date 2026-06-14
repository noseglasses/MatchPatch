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
    GuiSettingsBinder,
    GuiSettingsState,
    PresetTableSelectionContext,
    append_optional_argument,
    diagnostic_request,
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


def _state(**overrides: object) -> GuiSettingsState:
    values = {
        "device": "helix",
        "input_path": "/tmp/input.hls",
        "backend": "loopback",
        "config_path": "",
        "custom_adjustments_path": "",
        "reference_di": "reference.wav",
        "target_lufs": "-18",
        "solo_gain_bump_db": "2.5",
        "solo_regex": "solo",
        "ignore_snapshot_regex": "",
        "snapshot_count": 4,
        "keep_temp": False,
        "device_arguments": ("--audio-device", "Helix"),
        "analysis_window": "0.4",
        "analysis_interval": "0.1",
        "pre_roll": "0.3",
        "post_roll": "0.5",
        "round_trip_latency": "0.01",
        "preset_wait": "1.3",
        "snapshot_wait": "1.0",
        "measurement_wait": "0.6",
        "selected_preset_set": "01A",
        "optimization_stability_runs": 3,
        "optimization_termination_tolerance": 10.0,
        "optimization_stability_tolerance": 2.0,
    }
    values.update(overrides)
    return GuiSettingsState(**values)


def test_gui_settings_state_builds_normalization_and_export_argv() -> None:
    state = _state(
        config_path="/tmp/matchpatch.toml",
        custom_adjustments_path="/tmp/custom.csv",
        keep_temp=True,
    )

    argv = state.build_argv()

    assert argv[:7] == [
        "--device",
        "helix",
        "-i",
        "/tmp/input.hls",
        "--automation",
        "--backend",
        "loopback",
    ]
    assert ["--config", "/tmp/matchpatch.toml"] == argv[
        argv.index("--config") : argv.index("--config") + 2
    ]
    assert ["--custom-adjustments-file", "/tmp/custom.csv"] == argv[
        argv.index("--custom-adjustments-file") : argv.index("--custom-adjustments-file") + 2
    ]
    assert ["--preset-set", "01A"] == argv[
        argv.index("--preset-set") : argv.index("--preset-set") + 2
    ]
    assert "--keep-temp" in argv
    assert "None" not in argv

    export_argv = _state(input_path="").build_config_export_argv()

    assert ["-i", "placeholder.hls"] == export_argv[
        export_argv.index("-i") : export_argv.index("-i") + 2
    ]
    assert "--preset-set" not in export_argv


def test_gui_settings_state_exports_current_config() -> None:
    config = _state(
        backend="hardware",
        reference_di="modified.wav",
        target_lufs="-18.5",
        device_arguments=(
            "--audio-device",
            "Modified Helix",
            "--sample-rate",
            "48000",
            "--input-mapping",
            "3,4",
            "--output-mapping",
            "5,6",
        ),
        pre_roll="0.7",
        preset_wait="1.2",
        optimization_stability_tolerance=0.25,
    ).active_config()

    assert config["normalize"]["backend"] == "hardware"
    assert config["normalize"]["reference_di"] == "modified.wav"
    assert config["normalize"]["target_lufs"] == -18.5
    assert config["analysis"]["pre_roll_seconds"] == 0.7
    assert config["measurement"]["stability_tolerance_percent"] == 0.25
    assert config["devices"]["helix"]["audio"]["device"] == "Modified Helix"
    assert config["devices"]["helix"]["audio"]["input_mapping"] == [3, 4]
    assert config["devices"]["helix"]["steering"]["preset_wait_seconds"] == 1.2


@dataclass(frozen=True)
class _ProgressPlan:
    preset_snapshots: tuple[tuple[str, tuple[int, ...]], ...]


def test_request_with_preset_table_selection_filters_checked_and_ignored_snapshots() -> None:
    request = NormalizationRequest(
        device="helix",
        input_path=Path("/tmp/input.hls"),
        backend="loopback",
        windows_python="python",
        reference_di=Path("/tmp/reference.wav"),
        output_path=Path("/tmp/output.hls"),
        preset_set=None,
        snapshot_plan=(),
    )

    filtered = request_with_preset_table_selection(
        request,
        PresetTableSelectionContext(
            has_table=True,
            row_count=2,
            checked_rows={1},
            has_ignored_snapshots=True,
            comparison_snapshot_plan=None,
            input_path="/tmp/input.hls",
            patch_at_row=lambda row: ("01A", "01B")[row],
            row_measured_snapshot_indexes=lambda row: ((0, 2), (1,))[row],
            measurement_progress_plan_for_request=lambda _request: None,
            progress_plan_factory=_ProgressPlan,
        ),
    )

    assert filtered.preset_set == "01B"
    assert filtered.snapshot_plan == (("01B", (1,)),)


def test_diagnostic_request_builds_state_request_and_applies_table_selection(
    tmp_path, monkeypatch
) -> None:
    state = _state(
        input_path=str(tmp_path / "input.hls"),
        config_path=str(tmp_path / "matchpatch.toml"),
        selected_preset_set="",
    )
    captured = {}
    request = _request(input_path=tmp_path / "input.hls", preset_set=None)

    def parse_args(argv):
        captured["argv"] = argv
        return SimpleNamespace(parsed=True)

    def apply_config(args):
        captured["parsed"] = args
        return SimpleNamespace(effective=True)

    def request_from_args(args):
        captured["effective"] = args
        return request

    monkeypatch.setattr("matchpatch.gui.advanced_settings.parse_args", parse_args)
    monkeypatch.setattr("matchpatch.gui.advanced_settings.apply_config", apply_config)
    monkeypatch.setattr("matchpatch.gui.advanced_settings.request_from_args", request_from_args)

    resolved = diagnostic_request(
        state,
        PresetTableSelectionContext(
            has_table=True,
            row_count=2,
            checked_rows={1},
            has_ignored_snapshots=True,
            comparison_snapshot_plan=None,
            input_path=str(tmp_path / "input.hls"),
            patch_at_row=lambda row: ("01A", "01B")[row],
            row_measured_snapshot_indexes=lambda row: ((1, 2), (2,))[row],
            measurement_progress_plan_for_request=lambda _request: None,
            progress_plan_factory=_ProgressPlan,
        ),
    )

    assert captured["argv"] == state.build_argv()
    assert ["--config", str(tmp_path / "matchpatch.toml")] == captured["argv"][
        captured["argv"].index("--config") : captured["argv"].index("--config") + 2
    ]
    assert captured["parsed"].parsed
    assert captured["effective"].effective
    assert resolved.preset_set == "01B"
    assert resolved.snapshot_plan == (("01B", (2,)),)


def test_selected_preset_set_and_small_parsers() -> None:
    assert selected_preset_set([0, 2], lambda row: ("01A", "", "03C")[row]) == "01A,03C"

    argv: list[str] = []
    append_optional_argument(argv, "--pre-roll", "0.3")
    append_optional_argument(argv, "--post-roll", "None")

    assert argv == ["--pre-roll", "0.3"]
    assert parse_config_channel_mapping("1, 2") == (1, 2)
    assert parse_config_channel_mapping([3, 4]) == (3, 4)
    with pytest.raises(ValueError):
        parse_config_channel_mapping([1])


def test_single_preset_uses_table_preset_id_for_normalization(monkeypatch, app) -> None:
    window = MainWindow()
    _mock_single_hlx_handler(monkeypatch)
    window.input_path.setText("/tmp/example.hlx")
    window.load_assignments()

    window.preset_table.item(0, 1).setText("12a")

    argv = GuiSettingsBinder.from_widgets(window).build_argv()
    assert argv[argv.index("--preset-set") + 1] == "12A"

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
        window.preset_table_controller.clear_preset_adjustments(row)

    window.preset_table_controller.set_ignored_snapshot_highlight(0, 0, True)
    window.preset_table_controller.set_ignored_snapshot_highlight(0, 1, True)
    window.preset_table_controller.set_ignored_snapshot_highlight(1, 0, True)

    argv = GuiSettingsBinder.from_widgets(window).build_argv()

    assert argv[argv.index("--preset-set") + 1] == "02C"

    window.close()


def test_normalization_request_includes_measurable_snapshot_plan(monkeypatch, app) -> None:
    window = MainWindow()
    monkeypatch.setattr(main_window.NormalizationWorker, "start", lambda self: None)
    window.snapshot_count_input.setValue(3)
    for row, preset_id in enumerate(("02B", "02C")):
        window.preset_table.insertRow(row)
        selected = QTableWidgetItem()
        selected.setCheckState(Qt.CheckState.Checked)
        window.preset_table.setItem(row, 0, selected)
        window.preset_table.setItem(row, 1, QTableWidgetItem(preset_id))
        window.preset_table.setItem(row, 2, QTableWidgetItem("Song"))
        window.preset_table_controller.clear_preset_adjustments(row)

    window.preset_table_controller.set_ignored_snapshot_highlight(0, 1, True)
    window.preset_table_controller.set_ignored_snapshot_highlight(1, 0, True)
    window.preset_table_controller.set_ignored_snapshot_highlight(1, 2, True)

    window._start_normalization_request(_request(preset_set="02B,02C"))

    assert window.worker is not None
    assert window.worker.request.snapshot_plan == (
        ("02B", (1, 3)),
        ("02C", (2,)),
    )

    window.worker_finished()
    window.close()


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
    argv = GuiSettingsBinder.from_widgets(window).build_argv()
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
        "Estimated measurement time per snapshot: 5.90 s (1 preset, 2 snapshots)"
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
        window.preset_table_controller.clear_preset_adjustments(row)

    window.preset_table_controller.set_ignored_snapshot_highlight(0, 0, True)
    window.preset_table_controller.set_ignored_snapshot_highlight(0, 1, True)
    window.preset_table_controller.set_ignored_snapshot_highlight(1, 0, True)
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


def test_config_export_dialog_defaults_to_default_config_path(tmp_path, monkeypatch, app) -> None:
    window = MainWindow()
    selected_path = tmp_path / "saved.toml"
    dialogs = []
    monkeypatch.setattr(main_window, "default_config_path", lambda: tmp_path / "config.toml")

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

        def layout(self):
            return None

        def exec(self):
            return True

        def selectedFiles(self):
            return [str(selected_path)]

    class CheckBox:
        def __init__(self, *args):
            self.args = args
            self.checked = False

        def setChecked(self, checked):
            self.checked = checked

        def isChecked(self):
            return self.checked

    monkeypatch.setattr(main_window, "QFileDialog", FileDialog)
    monkeypatch.setattr(main_window, "QCheckBox", CheckBox)

    assert window._choose_config_export_path() == (str(selected_path), False)
    assert dialogs[0].args[1] == "Export config"
    assert ("select_file", str(tmp_path / "config.toml")) in dialogs[0].settings

    window.close()


def test_gui_always_requests_bad_lufs_tolerance(app) -> None:
    window = MainWindow()

    assert not hasattr(window, "ignore_bad_lufs")
    assert not hasattr(window, "limit")
    assert "--limit" not in GuiSettingsBinder.from_widgets(window).build_argv()
    assert "--ignore-bad-lufs" not in GuiSettingsBinder.from_widgets(window).build_argv()
    assert "--no-ignore-bad-lufs" not in GuiSettingsBinder.from_widgets(window).build_argv()

    window.close()
