"""Diagnostics bundle and preflight workflow orchestration for the GUI."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Sequence

from PySide6.QtWidgets import QApplication, QMessageBox

from matchpatch.diagnostics import (
    DiagnosticCheck,
    DiagnosticSnapshot,
    build_diagnostic_snapshot,
    progress_event_to_dict,
    snapshot_to_text,
    write_diagnostic_bundle,
)
from matchpatch.gui.diagnostics_panel import preflight_checks_with_preset_table_selection
from matchpatch.gui.hardware_checks import PreflightOverlay
from matchpatch.gui.worker import PreflightWorker

PROCESSING_DOT_RED = "#dc2626"


def _show_preflight_overlay(window: object) -> None:
    gui_window: Any = window
    if not hasattr(gui_window, "preflight_overlay"):
        gui_window.preflight_overlay = PreflightOverlay(gui_window)
    target = gui_window.centralWidget() or gui_window
    gui_window.preflight_overlay.show_over(target)


def _hide_preflight_overlay(window: object) -> None:
    gui_window: Any = window
    if hasattr(gui_window, "preflight_overlay"):
        gui_window.preflight_overlay.hide()


class DiagnosticsWorkflowController:
    """Owns diagnostic snapshot, bundle, summary, and preflight workflows."""

    def __init__(
        self,
        window: object,
        *,
        worker_type: object = PreflightWorker,
        bundle_writer: Callable[..., Path] = write_diagnostic_bundle,
        summary_formatter: Callable[..., str] = snapshot_to_text,
        progress_formatter: Callable[..., dict[str, Any]] = progress_event_to_dict,
    ) -> None:
        self.window: Any = window
        self.worker_type: Any = worker_type
        self.bundle_writer = bundle_writer
        self.summary_formatter = summary_formatter
        self.progress_formatter = progress_formatter

    def current_snapshot(
        self,
        checks: Sequence[DiagnosticCheck] = (),
    ) -> DiagnosticSnapshot:
        window = self.window
        request = window._current_diagnostic_request()
        result = window.completed_result
        retained_csv_path = result.retained_csv_path if result is not None else None
        if retained_csv_path is None and window.retained_csv.text().strip():
            candidate = Path(window.retained_csv.text().strip())
            if candidate.is_file():
                retained_csv_path = candidate
        return build_diagnostic_snapshot(
            request,
            config_path=window.config_path.text().strip() or None,
            checks=checks,
            recent_progress=(
                self.progress_formatter(event)
                for event in window.log_controller.recent_progress_events
            ),
            recent_logs=window.log_controller.entries,
            retained_csv_path=retained_csv_path,
            result=result,
        )

    def export_bundle(self) -> None:
        window = self.window
        try:
            snapshot = window._current_diagnostic_snapshot()
        except Exception as exc:  # noqa: BLE001
            window.show_error(str(exc))
            return

        destination = window._choose_diagnostic_bundle_path()
        if destination is None:
            return

        bundle_path = (
            destination
            if destination.suffix.lower() == ".zip"
            else destination.with_name(f"{destination.name}.zip")
        )
        if bundle_path.exists():
            answer = QMessageBox.question(
                window,
                "Replace diagnostic bundle",
                f"Replace existing diagnostic bundle?\n\n{bundle_path}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        try:
            saved_path = self.bundle_writer(snapshot, destination)
        except Exception as exc:  # noqa: BLE001
            window.show_error(str(exc))
            return

        window._log(f"Diagnostic bundle exported: {saved_path}", "success")

    def copy_summary(self) -> None:
        window = self.window
        try:
            snapshot = window._current_diagnostic_snapshot()
        except Exception as exc:  # noqa: BLE001
            window.show_error(str(exc))
            return

        QApplication.clipboard().setText(self.summary_formatter(snapshot))
        window._log("Diagnostic summary copied", "success")

    def run_preflight_check(self) -> None:
        window = self.window
        if (
            window.worker is not None
            or window.hardware_check_worker is not None
            or window.optimization_worker is not None
            or window.preflight_worker is not None
        ):
            return
        try:
            request = window._current_diagnostic_request()
        except Exception as exc:  # noqa: BLE001
            window.show_error(str(exc))
            return

        window.diagnostics_panel.set_preflight_running(True)
        window.start_button.setEnabled(False)
        window.determine_parameters_button.setEnabled(False)
        window._set_phase("preflight_checks")
        window._log("Preflight check started", "info")
        _show_preflight_overlay(window)
        window._start_busy_phase()
        window.preflight_worker = self.worker_type(request, window)
        window.preflight_worker.completed.connect(window._preflight_completed)
        window.preflight_worker.failed.connect(window._preflight_failed)
        window.preflight_worker.finished.connect(window._preflight_finished)
        window.preflight_worker.finished.connect(window.preflight_worker.deleteLater)
        window.preflight_worker.start()

    def preflight_completed(self, checks: Sequence[DiagnosticCheck]) -> None:
        window = self.window
        window._stop_busy_phase()
        _hide_preflight_overlay(window)
        checks = window._preflight_checks_with_preset_table_selection(checks)
        failed_count = sum(1 for check in checks if check.status == "fail")
        warning_count = sum(1 for check in checks if check.status == "warning")
        if failed_count:
            window._set_phase("error")
            window._log(f"Preflight check completed with {failed_count} failure(s)", "error")
        elif warning_count:
            window._set_phase("ready")
            window._log(f"Preflight check completed with {warning_count} warning(s)", "warning")
        else:
            window._set_phase("ready")
            window._log("Preflight check passed", "success")
        window._show_preflight_results(checks)

    def preflight_checks_with_preset_table_selection(
        self,
        checks: Sequence[DiagnosticCheck],
    ) -> list[DiagnosticCheck]:
        return preflight_checks_with_preset_table_selection(
            checks,
            self.window._preset_table_selection_context(),
        )

    def preflight_failed(self, detail: str) -> None:
        window = self.window
        window._stop_busy_phase(PROCESSING_DOT_RED)
        _hide_preflight_overlay(window)
        window._set_phase("error")
        message = f"Preflight check failed: {detail}"
        window._log(message, "error")
        QMessageBox.critical(window, "Preflight check", message)

    def preflight_finished(self) -> None:
        window = self.window
        window.preflight_worker = None
        _hide_preflight_overlay(window)
        if hasattr(window, "diagnostics_panel"):
            window.diagnostics_panel.set_preflight_running(False)
        window._refresh_file_actions()

    def show_preflight_results(self, checks: Sequence[DiagnosticCheck]) -> None:
        self.window.diagnostics_panel.show_preflight_results(checks, parent=self.window)
