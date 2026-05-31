from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from matchpatch.gui.main_window import MainWindow
from matchpatch.gui.worker import NormalizationWorker
from matchpatch.normalize import DEFAULT_REFERENCE_DI, DEFAULT_WINDOWS_PYTHON
from matchpatch.workflow import ImportRequest, NormalizationRequest


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


def test_main_window_starts_with_registry_device_and_loopback(app) -> None:
    window = MainWindow()

    assert window.device.currentData() == "helix"
    assert window.backend.currentText() == "loopback"
    assert window.device_stack.count() == 1
    assert not window.device_panels["helix"].audio_group.isEnabled()

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
