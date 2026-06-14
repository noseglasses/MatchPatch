"""Normalization workflow orchestration for the GUI."""

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QMessageBox

from matchpatch.devices import get_device_profile
from matchpatch.gui.advanced_settings import GuiSettingsBinder
from matchpatch.gui.loudness_widgets import _loudness_bar_color, _loudness_text
from matchpatch.gui.preset_table import snapshot_name_column
from matchpatch.gui.progress_widgets import MeasurementProgressEstimate
from matchpatch.gui.table_roles import IGNORED_SNAPSHOT_ROLE, RECORDED_OUTPUT_PATH_ROLE
from matchpatch.gui.worker import NormalizationWorker
from matchpatch.progress import ProgressEvent
from matchpatch.workflow import ImportRequest, NormalizationRequest, NormalizationResult

PROCESSING_DOT_RED = "#dc2626"


class NormalizationWorkflowController:
    """Owns normalization start, progress routing, and worker lifecycle."""

    def __init__(
        self,
        window: object,
        *,
        worker_type: object = NormalizationWorker,
    ) -> None:
        self.window: Any = window
        self.worker_type: Any = worker_type

    def start_normalization(self) -> None:
        window = self.window
        if not window._validate_single_preset_slot_for_run():
            return

        if window.preset_table.rowCount() and not window._selected_measurable_preset_rows():
            QMessageBox.warning(
                window,
                "No measurable snapshots",
                "Every selected preset has all snapshots ignored. Adjust the ignore regex or select a preset with at least one measurable snapshot.",
            )
            return

        if (
            window._preset_table_has_unsaved_changes()
            and not window._prompt_save_before_normalization()
        ):
            return

        try:
            settings_state = GuiSettingsBinder.from_widgets(window)
            request = settings_state.with_audio_capture_options(
                settings_state.normalization_request(defer_export=True),
                playback_toggle_path=window._ensure_playback_toggle_path(),
            )
            window._custom_adjustments = window._load_custom_adjustments(request)
        except Exception as exc:  # noqa: BLE001
            window.show_error(str(exc))
            return

        if window._backend_check_required(request):
            window._start_hardware_check(request, action="normalization")
            return

        window._available_backend = request.backend
        window._start_normalization_request(request)

    def start_request(self, request: NormalizationRequest) -> None:
        window = self.window
        try:
            if not window._confirm_automation_overwrites(request):
                return
        except Exception as exc:  # noqa: BLE001
            window.show_error(str(exc))
            return

        window.start_button.setEnabled(False)
        if hasattr(window, "diagnostics_panel"):
            window.diagnostics_panel.set_workflow_active(True)
        window.start_cancel_stack.setCurrentWidget(window.cancel_button)
        window._discard_completed_export()
        window.log_controller.clear_entries()
        window.log_controller.clear_progress_events()
        window.preset_snapshot_positions.clear()
        window._deferred_gain_correction_logs.clear()
        window._deferred_gain_correction_patch = None
        window.preset_table_controller.clear_bad_lufs_highlights()
        window._clear_normalization_focus()
        window._adjusted_presets.clear()
        with window._sorting_paused():
            for row in range(window.preset_table.rowCount()):
                window.preset_table_controller.clear_preset_adjustments(row)
                window.preset_table_controller.mark_selected_preset_adjustments_pending(row)
        window.retained_csv.clear()
        window.retained_csv_pane.hide()
        window._reset_loudness_bars()
        window._set_phase("starting")
        window._log("Normalization started", "info")
        window._log(f"Backend: {getattr(request, 'backend', 'unknown')}", "info")
        if request.backend == window._available_backend:
            for check in window._last_hardware_diagnostic_checks:
                if check.status == "warning":
                    window._log(f"Hardware check warning: {check.summary}", "warning")
                    if check.detail:
                        window._log(f"Hardware check detail: {check.detail}", "info")
                elif check.status == "pass" and check.detail:
                    window._log(f"Hardware check detail: {check.detail}", "info")
        if window._custom_adjustments:
            window._log(
                f"Custom adjustments loaded: {request.custom_adjustments_path}",
                "info",
            )
        window._start_busy_phase()
        progress_plan = window._measurement_progress_plan_for_request(request)
        if progress_plan is not None:
            request = replace(request, snapshot_plan=progress_plan.preset_snapshots)
        window.completed_request = request
        window._measurement_progress_estimate = MeasurementProgressEstimate.from_request(request)
        window._measurement_progress_plan = progress_plan
        window.worker = self.worker_type(request, window)
        window.worker.progress.connect(window.update_progress)
        window.worker.import_requested.connect(window.confirm_import)
        window.worker.completed.connect(window.normalization_completed)
        window.worker.cancelled.connect(window.normalization_cancelled)
        window.worker.failed.connect(window.show_error)
        window.worker.finished.connect(window.worker_finished)
        window.worker.finished.connect(window.worker.deleteLater)
        window.worker.start()

    def confirm_automation_overwrites(self, request: NormalizationRequest) -> bool:
        window = self.window
        if not getattr(request, "automation", False):
            return True

        profile = get_device_profile(request.device)
        handler = profile.create_patch_file_handler(Path(__file__).resolve().parents[3])
        input_path = request.input_path.resolve()
        for postfix, description in (("_measurement", "measurement"),):
            output_path = handler.automation_output_path(input_path, postfix)
            if not output_path.exists():
                continue

            answer = QMessageBox.question(
                window,
                "Overwrite generated file",
                f"The {description} file already exists:\n{output_path}\n\nOverwrite it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False

        return True

    def update_progress(self, event: ProgressEvent) -> None:
        window = self.window
        window.log_controller.retain_progress_event(event)
        if event.phase:
            window._set_phase(event.phase)
            window._hide_progress()
            if event.phase == "completed":
                window._apply_deferred_gain_correction_logs()
            if event.phase in {
                "completed",
                "waiting_for_measurement_import",
                "waiting_for_adjusted_import",
            }:
                window._stop_busy_phase()
            else:
                window._start_busy_phase()
            if event.phase == "measuring":
                window._show_indeterminate_progress(event.message or "Preparing measurement...")

        if event.kind == "measurement_preparation":
            window._show_indeterminate_progress(event.message or "Preparing measurement...")

        if event.preset_total and event.snapshot_total and event.preset_index:
            progress_was_hidden = window.progress_group.isHidden()
            window.progress_group.show()
            if progress_was_hidden:
                window._schedule_resize_for_content()
            plan = window._measurement_progress_plan
            if plan is not None:
                total = max(1, plan.measured_snapshot_total)
                value = min(total, plan.progress_value(event))
            else:
                total = event.preset_total * event.snapshot_total
                snapshot = event.snapshot or 1
                value = (event.preset_index - 1) * event.snapshot_total + snapshot
            window.preset_progress.setRange(0, total)
            window.preset_progress.setValue(value)
            window._update_measurement_progress_format(event)
        elif event.kind == "measurement_completed":
            window._hide_progress()

        window._update_normalization_focus(event)

        if event.lufs is not None:
            if event.device_patch:
                text = window._preset_progress_text(event)
                if event.snapshot is not None:
                    text += window._snapshot_progress_text(event)
                window.current.setText(text)
            target_lufs = window._target_lufs()
            window.measured_loudness.set_loudness(
                event.lufs,
                target_lufs,
                _loudness_bar_color(
                    event.lufs,
                    target_lufs,
                ),
            )
            window.measured_loudness_reading.setText(_loudness_text(event.lufs, target_lufs))

        message = event.message or event.kind.replace("_", " ")
        if event.kind == "log":
            window._handle_gain_correction_log(message)
        elif event.kind == "snapshot_completed":
            with window.preset_table.updates_paused():
                window._apply_snapshot_measurement(event)
        elif event.kind == "snapshot_failed":
            with window.preset_table.updates_paused():
                window._apply_snapshot_measurement_failure(event)
        elif event.kind == "preset_completed":
            window._apply_deferred_gain_correction_logs(event.device_patch)
        if event.lufs is not None and event.crest_factor_db is not None:
            message += f": {event.lufs:.3f} LUFS, {event.crest_factor_db:.3f} dB crest"
        if event.kind == "temp_retained" and event.path:
            window.retained_csv.setText(event.path)
            window.retained_csv_pane.show()
        if event.kind == "snapshot_recorded" and event.path:
            window._set_recorded_output(event)

        if (
            "bad LUFS" in message
            or "measurement unavailable" in message
            or message.startswith("[WARNING]")
        ):
            level = "warning"
        else:
            level = "error" if event.kind in {"error_log", "preset_failed"} else "debug"
        window._log(message, level)

    def update_normalization_focus(self, event: ProgressEvent) -> None:
        window = self.window
        if event.kind in {"measurement_completed", "preset_failed"} or (
            event.kind == "phase"
            and event.phase
            in {
                "completed",
                "error",
                "waiting_for_measurement_import",
                "waiting_for_adjusted_import",
                "normalization_cancelled_by_user",
            }
        ):
            window._clear_normalization_focus()
            return

        if event.kind == "preset_completed":
            window._set_normalization_focus(event.device_patch, None)
            return

        if event.kind == "preset_started":
            window._set_normalization_focus(event.device_patch, None)
            return

        if event.kind in {"snapshot_completed", "snapshot_failed"}:
            window._clear_normalization_snapshot_focus(event.device_patch)
            return

        if event.kind == "snapshot_started":
            window._set_normalization_focus(event.device_patch, event.snapshot)

    def set_normalization_focus(self, device_patch: str | None, snapshot: int | None) -> None:
        window = self.window
        if device_patch is None:
            return
        row = window._preset_row(device_patch)
        if row is None:
            return
        snapshot_index = None if snapshot is None else snapshot - 1
        if snapshot_index is not None and not 0 <= snapshot_index < window.snapshot_count:
            snapshot_index = None
        if snapshot_index is not None:
            item = window.preset_table.item(row, snapshot_name_column(snapshot_index))
            if item is not None and item.data(IGNORED_SNAPSHOT_ROLE):
                snapshot_index = None
        window.preset_table.set_normalization_focus(row, snapshot_index)

    def clear_normalization_focus(self) -> None:
        if hasattr(self.window, "preset_table"):
            self.window.preset_table.clear_normalization_focus()

    def clear_normalization_snapshot_focus(self, device_patch: str | None) -> None:
        window = self.window
        if device_patch is None:
            return
        row = window._preset_row(device_patch)
        if row is None:
            return
        window.preset_table.clear_normalization_snapshot_focus(row)

    def set_recorded_output(self, event: ProgressEvent) -> None:
        window = self.window
        if not event.device_patch or event.snapshot is None or event.path is None:
            return
        row = window._preset_row(event.device_patch)
        if row is None:
            return
        column = snapshot_name_column(event.snapshot - 1)
        item = window.preset_table.item(row, column)
        if item is None:
            return
        if item.data(IGNORED_SNAPSHOT_ROLE):
            return
        path = Path(event.path)
        item.setData(RECORDED_OUTPUT_PATH_ROLE, str(path))
        window._recording_paths[(event.device_patch, event.snapshot - 1)] = path
        window._refresh_snapshot_name_cell_widget(item)

    def confirm_import(self, request: ImportRequest) -> None:
        window = self.window
        window._stop_busy_phase()
        answer = QMessageBox.question(
            window,
            "Import preset/setlist file",
            request.message,
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        )
        if window.worker is not None:
            window.worker.answer_import(answer == QMessageBox.StandardButton.Ok)

    def completed(self, result: NormalizationResult) -> None:
        window = self.window
        window._stop_busy_phase()
        window._set_phase("completed")
        if (
            result.retained_csv_path is not None
            and window.completed_request is not None
            and window.completed_request.keep_temp
        ):
            window.retained_csv.setText(str(result.retained_csv_path))
            window.retained_csv_pane.show()
        window.completed_result = result
        if result.retained_csv_path is not None:
            window._mark_preset_table_modified()
        window._log("Measurement completed; save the active file to write adjustments", "success")
        window._show_normalization_completion_popup()

    def show_completion_popup(self) -> None:
        window = self.window
        save_message = (
            'You need to save the setlist or preset with "Save" or "Save As", then import '
            "the saved file on your device."
        )
        manual_targets = window._manual_adjustment_targets()
        if manual_targets:
            target_lines = "\n".join(f"- {target}" for target in manual_targets)
            QMessageBox.warning(
                window,
                "Normalization completed with errors",
                "Normalization completed with errors.\n\n"
                "For the highlighted presets/snapshots, manual modifications are required "
                "to adjust the gain staging so there is enough headroom to raise the output "
                "level if necessary.\n\n"
                f"{target_lines}\n\n"
                f"{save_message}",
            )
            return

        QMessageBox.information(
            window,
            "Normalization completed",
            f"Normalization completed successfully.\n\n{save_message}",
        )

    def cancelled(self) -> None:
        self.window._stop_busy_phase(PROCESSING_DOT_RED)
        self.window._set_phase("normalization_cancelled_by_user")
        self.window._log("Normalization cancelled by user", "warning")

    def worker_finished(self) -> None:
        window = self.window
        window._stop_busy_phase(window._processing_dot_color)
        window.start_cancel_stack.setCurrentWidget(window.start_button)
        window.worker = None
        window._measurement_progress_estimate = None
        window._measurement_progress_plan = None
        window._clear_normalization_focus()
        window._apply_deferred_gain_correction_logs()
        window._refresh_recorded_output_buttons()
        window._refresh_file_actions()

    def discard_completed_export(self) -> None:
        window = self.window
        if (
            window.completed_request is not None
            and not window.completed_request.keep_temp
            and window.completed_result is not None
            and window.completed_result.temp_dir is not None
        ):
            shutil.rmtree(window.completed_result.temp_dir, ignore_errors=True)
        window.completed_request = None
        window.completed_result = None
        window.retained_csv.clear()
        window.retained_csv_pane.hide()

    def cancel_normalization(self) -> None:
        window = self.window
        if window.worker is not None and window._confirm_cancellation():
            window.worker.cancel()
            window._set_phase("cancelling")
            window._log("Cancellation requested", "warning")
            window._start_busy_phase()

    def confirm_cancellation(self) -> bool:
        answer = QMessageBox.question(
            self.window,
            "Cancel measurement",
            "A measurement is currently running. Do you want to cancel it?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes
