"""Background Qt worker for the blocking normalization workflow."""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QThread, Signal

from matchpatch.normalize import (
    check_windows_hardware,
    run_windows_analysis,
    run_windows_optimization,
)
from matchpatch.workflow import ImportRequest, NormalizationRequest, normalize_presets


class HardwareCheckWorker(QThread):
    completed = Signal()
    failed = Signal(str)

    def __init__(self, request: NormalizationRequest, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.request = request

    def run(self) -> None:
        try:
            check_windows_hardware(self.request)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        else:
            self.completed.emit()


class NormalizationWorker(QThread):
    progress = Signal(object)
    import_requested = Signal(object)
    completed = Signal(object)
    cancelled = Signal()
    failed = Signal(str)

    def __init__(self, request: NormalizationRequest, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.request = request
        self._confirmation = threading.Event()
        self._confirmation_answer = False
        self._cancelled = False

    def run(self) -> None:
        try:
            result = normalize_presets(
                self.request,
                run_analysis=lambda request, preset_ids, csv_path, callback: run_windows_analysis(
                    request,
                    preset_ids,
                    csv_path,
                    callback,
                    lambda: self._cancelled,
                ),
                on_progress=self.progress.emit,
                confirm_import=self._confirm_import,
            )
        except Exception as exc:  # noqa: BLE001
            if self._cancelled:
                self.cancelled.emit()
            else:
                self.failed.emit(str(exc))
        else:
            self.completed.emit(result)

    def answer_import(self, confirmed: bool) -> None:
        self._confirmation_answer = confirmed
        self._confirmation.set()

    def cancel(self) -> None:
        self._cancelled = True
        self.answer_import(False)

    def _confirm_import(self, request: ImportRequest) -> bool:
        if self._cancelled:
            return False

        self._confirmation_answer = False
        self._confirmation.clear()
        self.import_requested.emit(request)
        self._confirmation.wait()
        return self._confirmation_answer and not self._cancelled


class MeasurementOptimizationWorker(QThread):
    progress = Signal(object)
    completed = Signal(str)
    cancelled = Signal()
    failed = Signal(str)

    def __init__(
        self,
        request: NormalizationRequest,
        preset_id: int,
        stability_runs: int,
        termination_tolerance: float,
        stability_tolerance: float,
        pinned_parameters: tuple[str, ...] = (),
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.request = request
        self.preset_id = preset_id
        self.stability_runs = stability_runs
        self.termination_tolerance = termination_tolerance
        self.stability_tolerance = stability_tolerance
        self.pinned_parameters = pinned_parameters
        self._cancelled = False

    def run(self) -> None:
        try:
            result = run_windows_optimization(
                self.request,
                self.preset_id,
                stability_runs=self.stability_runs,
                termination_tolerance=self.termination_tolerance,
                stability_tolerance=self.stability_tolerance,
                pinned_parameters=self.pinned_parameters,
                on_progress=self.progress.emit,
                cancel_requested=lambda: self._cancelled,
            )
        except Exception as exc:  # noqa: BLE001
            if self._cancelled:
                self.cancelled.emit()
            else:
                self.failed.emit(str(exc))
        else:
            self.completed.emit(result)

    def cancel(self) -> None:
        self._cancelled = True
