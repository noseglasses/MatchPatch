"""Measurement-optimization workflow orchestration for the GUI."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QDialog, QMessageBox

from matchpatch.devices import get_device_profile
from matchpatch.gui.advanced_settings import (
    GuiSettingsBinder,
    nested_config_value,
    request_with_measurement_optimization_settings,
    selected_preset_set,
)
from matchpatch.gui.measurement_optimization import (
    MeasurementOptimizationDialog,
    MeasurementOptimizationSettings,
    MeasurementOptimizationSetupDialog,
)
from matchpatch.gui.worker import MeasurementOptimizationWorker
from matchpatch.measurement_optimizer import TIMING_PARAMETERS, OptimizationProgress
from matchpatch.workflow import NormalizationRequest


class MeasurementOptimizationWorkflowController:
    """Owns setup, worker wiring, and result handling for parameter studies."""

    def __init__(
        self,
        window: object,
        *,
        setup_dialog_type: object = MeasurementOptimizationSetupDialog,
        result_dialog_type: object = MeasurementOptimizationDialog,
        worker_type: object = MeasurementOptimizationWorker,
    ) -> None:
        self.window: Any = window
        self.setup_dialog_type: Any = setup_dialog_type
        self.result_dialog_type: Any = result_dialog_type
        self.worker_type: Any = worker_type

    def determine_optimal_parameters(self) -> None:
        window = self.window
        if not window._validate_single_preset_slot_for_run():
            return

        try:
            settings_state = GuiSettingsBinder.from_widgets(window)
            request = settings_state.with_audio_capture_options(
                settings_state.normalization_request(defer_export=True),
                record_device_output=False,
                playback_toggle_path=window._ensure_playback_toggle_path(),
            )
            preset_id = window._optimization_preset_id(request)
        except Exception as exc:  # noqa: BLE001
            window.show_error(str(exc))
            return

        settings = window._show_measurement_optimization_setup(request, preset_id)
        if settings is None:
            return
        request = window._request_with_measurement_optimization_settings(request, settings)
        window._apply_measurement_optimization_settings(settings)

        if window._backend_check_required(request):
            window._start_hardware_check(
                request,
                action="optimization",
                optimization_preset_id=preset_id,
                optimization_settings=settings,
            )
            return

        window.determine_parameters_button.setEnabled(False)
        window._available_backend = request.backend
        window._start_measurement_optimization_request(request, preset_id, settings)

    def start_request(
        self,
        request: NormalizationRequest,
        preset_id: int,
        settings: MeasurementOptimizationSettings,
    ) -> None:
        window = self.window
        window.start_button.setEnabled(True)
        window.determine_parameters_button.setEnabled(False)
        window._last_measurement_optimization_settings = settings
        window.optimization_dialog = self.result_dialog_type(settings, window)
        window.optimization_dialog.set_play_recorded_output(
            window.play_recorded_output_button.isChecked()
        )
        window.optimization_dialog.play_recorded_output_changed.connect(
            window.play_recorded_output_button.setChecked
        )
        window.optimization_dialog.cancelled.connect(window._cancel_measurement_optimization)
        window.optimization_dialog.applied.connect(window._apply_measurement_optimization_result)
        window.optimization_dialog.show()
        window.optimization_worker = self.worker_type(
            request,
            preset_id,
            settings.stability_runs,
            settings.termination_tolerance,
            settings.stability_tolerance,
            settings.pinned_parameters,
            window,
        )
        window.optimization_worker.progress.connect(window._update_measurement_optimization)
        window.optimization_worker.completed.connect(window._measurement_optimization_completed)
        window.optimization_worker.cancelled.connect(window._measurement_optimization_cancelled)
        window.optimization_worker.failed.connect(window._measurement_optimization_failed)
        window.optimization_worker.finished.connect(window._measurement_optimization_finished)
        window.optimization_worker.finished.connect(window.optimization_worker.deleteLater)
        window.optimization_worker.start()

    def show_setup(
        self,
        request: NormalizationRequest,
        preset_id: int,
        initial_settings: MeasurementOptimizationSettings | None = None,
    ) -> MeasurementOptimizationSettings | None:
        window = self.window
        preset_label = get_device_profile(request.device).format_patch_id(preset_id)
        settings = (
            initial_settings
            or window._last_measurement_optimization_settings
            or MeasurementOptimizationSettings(
                pre_roll=float(request.pre_roll if request.pre_roll is not None else 0.2),
                post_roll=float(request.post_roll if request.post_roll is not None else 0.1),
                round_trip_latency=float(
                    request.round_trip_latency if request.round_trip_latency is not None else 0.02
                ),
                preset_wait=float(request.preset_wait if request.preset_wait is not None else 0.5),
                snapshot_wait=float(
                    request.snapshot_wait if request.snapshot_wait is not None else 0.2
                ),
                measurement_wait=float(
                    request.measurement_wait if request.measurement_wait is not None else 0.1
                ),
                stability_runs=window._optimization_stability_runs,
                termination_tolerance=window._optimization_termination_tolerance,
                stability_tolerance=window._optimization_stability_tolerance,
            )
        )
        dialog = self.setup_dialog_type(
            settings,
            preset_label,
            preset_id,
            window,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            cancelled_settings = dialog.settings()
            if cancelled_settings != settings:
                window._last_measurement_optimization_settings = cancelled_settings
            return None
        return dialog.settings()

    @staticmethod
    def request_with_settings(
        request: NormalizationRequest,
        settings: MeasurementOptimizationSettings,
    ) -> NormalizationRequest:
        return request_with_measurement_optimization_settings(request, settings)

    def apply_settings(self, settings: MeasurementOptimizationSettings) -> None:
        window = self.window
        window.pre_roll.setText(f"{settings.pre_roll:g}")
        window.post_roll.setText(f"{settings.post_roll:g}")
        window.round_trip_latency.setText(f"{settings.round_trip_latency:g}")
        window.preset_wait.setText(f"{settings.preset_wait:g}")
        window.snapshot_wait.setText(f"{settings.snapshot_wait:g}")
        window.measurement_wait.setText(f"{settings.measurement_wait:g}")
        window._optimization_stability_runs = settings.stability_runs
        window._optimization_termination_tolerance = settings.termination_tolerance
        window._optimization_stability_tolerance = settings.stability_tolerance

    def preset_id(self, request: NormalizationRequest) -> int:
        window = self.window
        preset_set = request.preset_set or selected_preset_set(
            window._selected_measurable_preset_rows(),
            window._preset_patch_at_row,
        )
        if not preset_set:
            raise ValueError("Select at least one preset before determining optimal parameters")

        profile = get_device_profile(request.device)
        handler = profile.create_patch_file_handler(Path(__file__).resolve().parents[3])
        return handler.parse_patch_set(preset_set)[0]

    def update_progress(self, event: OptimizationProgress) -> None:
        if self.window.optimization_dialog is not None:
            self.window.optimization_dialog.update_progress(event)

    def completed(self, toml_text: str) -> None:
        if self.window.optimization_dialog is not None:
            self.window.optimization_dialog.set_result(toml_text)

    def apply_result(self, toml_text: str) -> None:
        window = self.window
        try:
            config = tomllib.loads(toml_text)
        except tomllib.TOMLDecodeError as exc:
            window.show_error(f"Could not apply optimized parameters: {exc}")
            return

        device = window.device.currentData()
        applied = False
        for parameter in TIMING_PARAMETERS:
            table_path = tuple(device if part == "{device}" else part for part in parameter.table)
            value = nested_config_value(config, (*table_path, parameter.key))
            if value is None:
                continue
            getattr(window, parameter.name).setText(str(value))
            panel = window.device_panels.get(device)
            if panel is not None and hasattr(panel, parameter.name):
                getattr(panel, parameter.name).setText(str(value))
            applied = True

        if not applied:
            window.show_error("Optimized parameters did not contain measurement timing values")
            return
        QMessageBox.information(
            window,
            "Apply optimized parameters",
            "Applied optimized timing parameters to Advanced > Timing.",
        )

    def cancelled(self) -> None:
        if self.window.optimization_dialog is not None:
            self.window.optimization_dialog.set_status("Parameter study cancelled.")
            self.window.optimization_dialog.set_finished()

    def failed(self, detail: str) -> None:
        if self.window.optimization_dialog is not None:
            self.window.optimization_dialog.set_status(f"Parameter study failed: {detail}")
            self.window.optimization_dialog.set_failed()
        else:
            self.window.show_error(detail)

    def finished(self) -> None:
        self.window.optimization_worker = None
        self.window._refresh_file_actions()

    def cancel(self) -> None:
        if self.window.optimization_worker is not None:
            self.window.optimization_worker.cancel()
