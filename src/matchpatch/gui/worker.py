"""Background Qt worker for the blocking normalization workflow."""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QThread, Signal

from matchpatch.normalize import run_windows_analysis
from matchpatch.workflow import ImportRequest, NormalizationRequest, normalize_presets


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
