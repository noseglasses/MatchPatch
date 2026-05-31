from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtGui import Qt
from PySide6.QtWidgets import (
    QApplication,
    QHeaderView,
    QLabel,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidgetItem,
)

from matchpatch.gui.main_window import MainWindow
from matchpatch.gui.worker import NormalizationWorker
from matchpatch.normalize import DEFAULT_REFERENCE_DI, DEFAULT_WINDOWS_PYTHON
from matchpatch.progress import ProgressEvent
from matchpatch.workflow import ImportRequest, NormalizationRequest, NormalizationResult


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


def test_main_window_starts_with_registry_device_and_loopback(app) -> None:
    window = MainWindow()

    assert window.device.currentData() == "helix"
    assert window.backend.currentText() == "loopback"
    assert window.general.title() == "General"
    assert not window.advanced.is_expanded()
    assert window.advanced.content.isHidden()
    assert [window.advanced_tabs.tabText(index) for index in range(4)] == [
        "Presets",
        "Device",
        "Misc",
        "Log",
    ]
    assert not window.findChildren(QMenuBar)
    assert "Setlist/Preset file" in [label.text() for label in window.general.findChildren(QLabel)]
    assert {"Help", "About"} <= {
        button.text() for button in window.general.findChildren(QPushButton)
    }
    assert window.log_level.currentText() == "Info"
    assert window.device_stack.count() == 1
    assert window.device_panels["helix"].audio_group.isEnabled()
    assert window.progress.parent().sizePolicy().verticalPolicy() == QSizePolicy.Policy.Maximum
    assert not hasattr(window, "ignore_bad_lufs")
    assert window.preset_table.verticalHeader().isHidden()

    window.close()


def test_initial_window_size_avoids_scrollbar_for_collapsed_layout(app) -> None:
    window = MainWindow()
    window.show()
    app.processEvents()
    window._resize_to_initial_content()
    app.processEvents()

    assert not window.scroll_area.verticalScrollBar().isVisible()

    window.close()


def test_log_section_and_busy_progress(app) -> None:
    window = MainWindow()

    assert window.log_section is window.log
    window._start_busy_phase()
    window._show_busy_progress()
    assert window.progress.minimum() == 0
    assert window.progress.maximum() == 0
    window.update_progress(
        ProgressEvent(
            "preset_started",
            device_patch="01A",
            preset_index=1,
            preset_total=2,
            snapshot_total=4,
        )
    )
    assert window.progress.maximum() == 8

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
""",
        encoding="utf-8",
    )
    window = MainWindow()
    window.config_path.setText(str(config_path))
    window.load_defaults()

    assert window.backend.currentText() == "hardware"
    assert window.target_lufs.text() == "-18.0"
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
    assert window.preset_table.item(0, 4).text() == "+0 dB"
    window.set_all_presets_checked(True)
    assert all(
        window.preset_table.item(row, 0).checkState() == Qt.CheckState.Checked
        for row in range(window.preset_table.rowCount())
    )

    window.close()


def test_gain_log_updates_preset_correction_columns(app) -> None:
    window = MainWindow()
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
    assert window.preset_table.horizontalHeaderItem(4).text() == "Δ"
    assert window.preset_table.item(0, 3).text() == "Solo 🎸"
    assert window.preset_table.item(0, 4).text() == "+11.1 dB"
    assert window.preset_table.item(0, 5).text() == "Clean"
    assert window.preset_table.item(0, 6).text() == "+0.0 dB"
    assert window.preset_table.item(0, 7).text() == "Rhythm"
    assert window.preset_table.item(0, 8).text() == "-2.0 dB"
    assert window.preset_table.item(0, 4).foreground().color().name() == "#15803d"
    assert window.preset_table.item(0, 8).foreground().color().name() == "#b91c1c"
    assert all(
        window.preset_table.horizontalHeader().sectionResizeMode(column)
        == QHeaderView.ResizeMode.Interactive
        for column in range(window.preset_table.columnCount())
    )

    window.close()


def test_snapshot_names_are_preloaded_and_bad_lufs_is_marked(app) -> None:
    window = MainWindow()
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

    window.close()


def test_implausible_gain_warning_is_marked_as_bad_lufs(app) -> None:
    window = MainWindow()
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

    assert window.preset_table.item(0, 3).text() == "Solo 🎸"
    assert window.preset_table.item(0, 4).text() == "⚠️"

    window.close()


def test_gui_always_requests_bad_lufs_tolerance(app) -> None:
    window = MainWindow()

    assert not hasattr(window, "ignore_bad_lufs")
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


def test_completion_logs_output_without_redundant_popup(tmp_path, monkeypatch, app) -> None:
    window = MainWindow()
    popups = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: popups.append(args))

    window.normalization_completed(NormalizationResult(tmp_path / "adjusted.hls", None))

    assert popups == []
    assert "adjusted.hls" in window.log.toHtml()

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
            worker._confirm_import(ImportRequest("reamp", "Line 6 Helix", Path("reamp.hls")))
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
