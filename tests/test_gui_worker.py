from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtWidgets import QApplication

from matchpatch.diagnostics import DiagnosticCheck
from matchpatch.gui import worker as gui_worker
from matchpatch.gui.worker import HardwareCheckWorker, NormalizationWorker, PreflightWorker
from matchpatch.progress import ProgressEvent
from matchpatch.workflow import ImportRequest, NormalizationRequest, NormalizationResult


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    QCoreApplication.setOrganizationName("MatchPatchWorkerTests")
    QCoreApplication.setApplicationName("MatchPatchWorkerTests")
    yield instance


@pytest.fixture(autouse=True)
def isolated_qsettings(tmp_path):
    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, str(tmp_path))
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    QSettings().clear()
    yield
    QSettings().clear()


def _request() -> NormalizationRequest:
    return NormalizationRequest(
        device="helix",
        input_path=Path("input.hls"),
        backend="loopback",
        windows_python="python.exe",
        reference_di=Path("reference.wav"),
    )


def _process_until(app, predicate, *, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    app.processEvents()


def test_normalization_worker_cancel_unblocks_import_confirmation(app) -> None:
    worker = NormalizationWorker(_request())
    import_requests = []
    answers = []
    worker.import_requested.connect(import_requests.append)

    thread = threading.Thread(
        target=lambda: answers.append(
            worker._confirm_import(
                ImportRequest("measurement", "Line 6 Helix", Path("measurement.hls"))
            )
        )
    )
    thread.start()

    _process_until(app, lambda: bool(import_requests))
    assert thread.is_alive()

    worker.cancel()
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert answers == [False]


def test_normalization_worker_emits_cancelled_when_running_normalization_is_cancelled(
    monkeypatch, app
) -> None:
    worker = NormalizationWorker(_request())
    entered_normalization = threading.Event()
    allow_exit = threading.Event()
    cancelled = []
    failures = []
    completed = []

    def normalize(*args, **kwargs):
        entered_normalization.set()
        allow_exit.wait(timeout=1.0)
        raise RuntimeError("cancelled by user")

    monkeypatch.setattr(gui_worker, "normalize_presets", normalize)
    worker.cancelled.connect(lambda: cancelled.append(True))
    worker.failed.connect(failures.append)
    worker.completed.connect(completed.append)

    worker.start()
    assert entered_normalization.wait(timeout=1.0)
    worker.cancel()
    allow_exit.set()
    assert worker.wait(1000)
    _process_until(app, lambda: bool(cancelled))

    assert cancelled == [True]
    assert failures == []
    assert completed == []


def test_normalization_worker_non_cancellation_exception_emits_failed(monkeypatch) -> None:
    worker = NormalizationWorker(_request())
    failures = []
    cancelled = []

    def normalize(*args, **kwargs):
        raise RuntimeError("analysis exploded")

    monkeypatch.setattr(gui_worker, "normalize_presets", normalize)
    worker.failed.connect(failures.append)
    worker.cancelled.connect(lambda: cancelled.append(True))

    worker.run()

    assert failures == ["analysis exploded"]
    assert cancelled == []


def test_normalization_worker_forwards_progress_events(monkeypatch) -> None:
    worker = NormalizationWorker(_request())
    event = ProgressEvent("phase", message="Measuring")
    progress_events = []
    results = []

    def normalize(*args, on_progress, **kwargs):
        on_progress(event)
        return NormalizationResult(Path("adjusted.hls"), None)

    monkeypatch.setattr(gui_worker, "normalize_presets", normalize)
    worker.progress.connect(progress_events.append)
    worker.completed.connect(results.append)

    worker.run()

    assert progress_events == [event]
    assert results == [NormalizationResult(Path("adjusted.hls"), None)]


def test_normalization_worker_ignores_import_confirmation_after_cancellation(app) -> None:
    worker = NormalizationWorker(_request())
    import_requests = []
    answers = []
    worker.import_requested.connect(import_requests.append)

    thread = threading.Thread(
        target=lambda: answers.append(
            worker._confirm_import(
                ImportRequest("measurement", "Line 6 Helix", Path("measurement.hls"))
            )
        )
    )
    thread.start()

    _process_until(app, lambda: bool(import_requests))
    worker.cancel()
    worker.answer_import(True)
    thread.join(timeout=1.0)

    assert answers == [False]


def test_hardware_check_worker_success_emits_diagnostics_and_completed(monkeypatch) -> None:
    worker = HardwareCheckWorker(_request())
    checks = [DiagnosticCheck("audio_device", "pass", "Audio device resolved")]
    diagnostics = []
    completed = []
    failures = []

    monkeypatch.setattr(gui_worker, "collect_windows_hardware_diagnostics", lambda request: checks)
    worker.diagnostics_completed.connect(diagnostics.append)
    worker.completed.connect(lambda: completed.append(True))
    worker.failed.connect(failures.append)

    worker.run()

    assert diagnostics == [checks]
    assert completed == [True]
    assert failures == []


def test_hardware_check_worker_failed_checks_emit_diagnostics_and_failed(
    monkeypatch,
) -> None:
    worker = HardwareCheckWorker(_request())
    checks = [
        DiagnosticCheck(
            "audio_device",
            "fail",
            "No audio device matched",
            "audio_device=Line 6 Helix",
        )
    ]
    diagnostics = []
    completed = []
    failures = []

    monkeypatch.setattr(gui_worker, "collect_windows_hardware_diagnostics", lambda request: checks)
    worker.diagnostics_completed.connect(diagnostics.append)
    worker.completed.connect(lambda: completed.append(True))
    worker.failed.connect(failures.append)

    worker.run()

    assert diagnostics == [checks]
    assert completed == []
    assert failures == ["No audio device matched"]


def test_hardware_check_worker_unexpected_exception_emits_concise_failure(
    monkeypatch,
) -> None:
    worker = HardwareCheckWorker(_request())
    diagnostics = []
    failures = []

    def collect(request):
        raise RuntimeError("native worker missing")

    monkeypatch.setattr(gui_worker, "collect_windows_hardware_diagnostics", collect)
    worker.diagnostics_completed.connect(diagnostics.append)
    worker.failed.connect(failures.append)

    worker.run()

    assert diagnostics == []
    assert failures == ["native worker missing"]


def test_preflight_worker_success_emits_completed_checks(monkeypatch) -> None:
    worker = PreflightWorker(_request())
    checks = [DiagnosticCheck("input_file", "pass", "Input exists")]
    completed = []
    failures = []

    monkeypatch.setattr(gui_worker, "run_preflight_checks", lambda request: checks)
    worker.completed.connect(completed.append)
    worker.failed.connect(failures.append)

    worker.run()

    assert completed == [checks]
    assert failures == []


def test_preflight_worker_unexpected_exception_emits_failed(monkeypatch) -> None:
    worker = PreflightWorker(_request())
    completed = []
    failures = []

    def run_checks(request):
        raise RuntimeError("preflight crashed")

    monkeypatch.setattr(gui_worker, "run_preflight_checks", run_checks)
    worker.completed.connect(completed.append)
    worker.failed.connect(failures.append)

    worker.run()

    assert completed == []
    assert failures == ["preflight crashed"]


def test_preflight_worker_returns_failed_checks_as_results(monkeypatch) -> None:
    worker = PreflightWorker(_request())
    checks = [DiagnosticCheck("input_file", "fail", "Input file is missing", "path=input.hls")]
    completed = []
    failures = []

    monkeypatch.setattr(gui_worker, "run_preflight_checks", lambda request: checks)
    worker.completed.connect(completed.append)
    worker.failed.connect(failures.append)

    worker.run()

    assert completed == [checks]
    assert failures == []
