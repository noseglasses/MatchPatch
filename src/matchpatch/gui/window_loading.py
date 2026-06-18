"""File, metadata, and device-default loading for the main GUI window."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QTableWidgetItem

from matchpatch.config import config_value, load_config
from matchpatch.custom_adjustments import CustomAdjustments, load_custom_adjustments_file
from matchpatch.devices import get_device_profile
from matchpatch.devices.base import DeviceProfile
from matchpatch.gui.advanced_settings import GuiSettingsBinder
from matchpatch.gui.window_layout import MEASUREMENT_TIMING_PRESETS
from matchpatch.normalize import apply_config, parse_args
from matchpatch.workflow import NormalizationRequest


class WindowLoadingController:
    def __init__(
        self,
        window: object,
        *,
        get_profile: Callable[[str], DeviceProfile] = get_device_profile,
    ) -> None:
        self.window: Any = window
        self.get_profile = get_profile

    def device_changed(self) -> None:
        window = self.window
        name = window.device.currentData()
        panel = window.device_panels.get(name)
        if panel is not None:
            window.device_stack.setCurrentWidget(panel)
        self.refresh_backend_choices()
        window.load_defaults()

    def backend_changed(self) -> None:
        window = self.window
        window._refresh_backend_tooltip()
        if not window._loading_defaults:
            window._available_backend = None

    def refresh_backend_tooltip(self) -> None:
        window = self.window
        if window.backend.currentText() == "loopback":
            window.device_settings.setToolTip(
                "Audio and MIDI settings are editable but unused by the loopback backend."
            )
        else:
            window.device_settings.setToolTip("")

    def refresh_backend_choices(self) -> None:
        window = self.window
        device = window.device.currentData()
        if not device:
            return
        profile = self.get_profile(device)
        current = window.backend.currentText() or "hardware"
        backends = profile.measurement_backends()
        if not backends:
            backends = ("hardware",)
        signals_blocked = window.backend.blockSignals(True)
        try:
            window.backend.clear()
            window.backend.addItems(list(backends))
            window.backend.setCurrentText(current if current in backends else backends[0])
        finally:
            window.backend.blockSignals(signals_blocked)

    def load_defaults(self) -> None:
        window = self.window
        if not window.device.currentData():
            return

        try:
            config = load_config(window.config_path.text().strip() or None)
            window._loading_defaults = True
            try:
                window.backend.setCurrentText(
                    config_value(config, "normalize", "backend", default="hardware")
                )
            finally:
                window._loading_defaults = False
            args = apply_config(
                parse_args(GuiSettingsBinder.from_widgets(window).base_argv("placeholder.hls"))
            )
        except Exception as exc:  # noqa: BLE001
            window.show_error(str(exc))
            return

        window._loading_defaults = True
        try:
            window.backend.setCurrentText(args.backend)
        finally:
            window._loading_defaults = False
        window.reference_di.setText(str(args.reference_di))
        window.custom_adjustments_path.setText(
            str(args.custom_adjustments_file) if args.custom_adjustments_file else ""
        )
        window.target_lufs.setText(str(args.target_lufs))
        window.solo_gain_bump_db.setText(str(args.policy.solo_gain_bump_db))
        window.solo_regex.setText(args.policy.solo_regex)
        window.ignore_snapshot_regex.setText(args.policy.ignore_snapshot_regex)
        window.ignore_preset_regex.setText(args.policy.ignore_preset_regex)
        window.analysis_window.setText(str(args.analysis_options.window_seconds))
        window.analysis_interval.setText(str(args.analysis_options.interval_seconds))
        window._optimization_stability_runs = int(
            config_value(config, "measurement", "stability_runs", default=3)
        )
        window._optimization_termination_tolerance = float(
            config_value(
                config,
                "measurement",
                "termination_tolerance_percent",
                default=10.0,
            )
        )
        window._optimization_stability_tolerance = float(
            config_value(
                config,
                "measurement",
                "stability_tolerance_percent",
                default=2.0,
            )
        )
        profile = self.get_profile(args.device)
        window.snapshot_count_input.setMaximum(getattr(profile, "max_snapshot_count", None) or 999)
        window.snapshot_count_input.setValue(args.policy.snapshot_count)
        panel = window.device_panels.get(args.device)
        if panel is not None:
            panel.populate(args)
        device_steering = ("devices", args.device, "steering")
        default_timing = MEASUREMENT_TIMING_PRESETS["Default"]
        window._apply_measurement_timing_values(
            {
                "pre_roll": config_value(
                    config,
                    "analysis",
                    "pre_roll_seconds",
                    default=default_timing["pre_roll"],
                ),
                "post_roll": config_value(
                    config,
                    "analysis",
                    "post_roll_seconds",
                    default=default_timing["post_roll"],
                ),
                "round_trip_latency": config_value(
                    config,
                    "analysis",
                    "round_trip_latency_seconds",
                    default=default_timing["round_trip_latency"],
                ),
                "preset_wait": config_value(
                    config,
                    *device_steering,
                    "preset_wait_seconds",
                    default=default_timing["preset_wait"],
                ),
                "snapshot_wait": config_value(
                    config,
                    *device_steering,
                    "snapshot_wait_seconds",
                    default=default_timing["snapshot_wait"],
                ),
                "measurement_wait": config_value(
                    config,
                    *device_steering,
                    "measurement_wait_seconds",
                    default=default_timing["measurement_wait"],
                ),
            }
        )
        window._refresh_backend_tooltip()

    def load_assignments(self) -> None:
        window = self.window
        path = Path(window.input_path.text())
        if (
            not window._preset_load_discard_confirmed
            and window._loaded_input_path
            and str(path) != window._loaded_input_path
            and window._preset_table_has_unsaved_changes()
            and not window._prompt_save_or_discard_preset_table_changes(
                "opening another preset or setlist file"
            )
        ):
            window.input_path.setText(window._loaded_input_path)
            return

        window._discard_completed_export()
        window.preset_snapshot_positions.clear()
        window._recording_paths.clear()
        window.preset_table_controller.clear_bad_lufs_highlights()
        window._clear_normalization_focus()
        window._reset_comparison_file_selection()
        window._load_metadata()
        is_single_preset = path.suffix.lower() == ".hlx"
        window._show_loaded_preset_state(single_preset=is_single_preset)
        window._set_preset_csv_buttons_enabled(False)
        window.presets.updateGeometry()
        window._schedule_resize_for_content()

        if path.suffix.lower() == ".hlx":
            self._load_single_preset_assignments(path)
            return

        self._load_setlist_assignments(path)

    def _load_single_preset_assignments(self, path: Path) -> None:
        window = self.window
        try:
            profile = self.get_profile(window.device.currentData())
            handler = profile.create_patch_file_handler(Path(__file__).resolve().parents[3])
            if handler.file_kind(path) == "unknown":
                self._show_no_assignments_loaded()
                return
            handler.validate_input(path)
            assignments = handler.list_assignments(path)
        except Exception as exc:  # noqa: BLE001
            self._show_no_assignments_loaded()
            window.show_error(str(exc))
            return

        window._adjusted_presets.clear()
        window._populate_single_preset_table(path, assignments[0] if assignments else None)
        window._loaded_input_path = str(path)
        window._set_active_file(path)
        window._store_recent_file(path)
        window._reset_preset_table_modified()
        window._refresh_file_actions()
        window._set_preset_csv_buttons_enabled(window.preset_table.rowCount() > 0)
        window.preset_hint.setText(
            "Enter the temporary Helix slot used during measurement in the Preset column."
        )
        QTimer.singleShot(0, window._fit_advanced_splitter_width)
        window.presets.updateGeometry()
        window._schedule_resize_for_content()

    def _load_setlist_assignments(self, path: Path) -> None:
        window = self.window
        try:
            profile = self.get_profile(window.device.currentData())
            handler = profile.create_patch_file_handler(Path(__file__).resolve().parents[3])
            if handler.file_kind(path) == "unknown":
                self._show_no_assignments_loaded()
                return
            handler.validate_input(path)
            with window._sorting_paused():
                window._adjusted_presets.clear()
                window.preset_table.setRowCount(0)
                for assignment in handler.list_assignments(path):
                    row = window.preset_table.rowCount()
                    window.preset_table.insertRow(row)
                    selected = QTableWidgetItem()
                    selected.setCheckState(Qt.CheckState.Checked)
                    window.preset_table.setItem(row, 0, selected)
                    window.preset_table.setItem(row, 1, QTableWidgetItem(assignment.device_patch))
                    window.preset_table.setItem(row, 2, QTableWidgetItem(assignment.name))
                    window.preset_table_controller.set_preset_original_filename(
                        row,
                        getattr(assignment, "original_filename", None),
                    )
                    window.preset_table_controller.clear_preset_adjustments(row)
                    window.preset_table_controller.refresh_preset_name(row)
                    window.preset_table_controller.set_snapshot_names(
                        row, assignment.snapshot_names
                    )
                    window.preset_table_controller.set_snapshot_output_levels(
                        row,
                        getattr(assignment, "snapshot_output_levels", ()),
                        getattr(assignment, "snapshot_output_paths", ()),
                    )
                window._refresh_preset_table_editable_flags()
        except Exception as exc:  # noqa: BLE001
            self._show_no_assignments_loaded()
            window.show_error(str(exc))
            return

        window._loaded_input_path = str(path)
        window._set_active_file(path)
        window._store_recent_file(path)
        window._reset_preset_table_modified()
        window._refresh_file_actions()
        window.preset_hint.setText("Select the presets to normalize.")
        window._set_preset_csv_buttons_enabled(window.preset_table.rowCount() > 0)
        QTimer.singleShot(0, window._fit_advanced_splitter_width)
        window._schedule_resize_for_content()

    def _show_no_assignments_loaded(self) -> None:
        window = self.window
        window._show_preset_empty_state()
        window.presets.updateGeometry()
        window._schedule_resize_for_content()

    @staticmethod
    def load_custom_adjustments(request: NormalizationRequest) -> CustomAdjustments:
        if request.custom_adjustments_path is None:
            return {}
        return load_custom_adjustments_file(
            request.custom_adjustments_path,
            request.policy.snapshot_count,
        )

    def populate_single_preset_table(self, path: Path, assignment: object | None = None) -> None:
        window = self.window
        preset_name = str(getattr(assignment, "name", "") or path.stem)
        snapshot_names = getattr(assignment, "snapshot_names", ())
        if not isinstance(snapshot_names, tuple):
            snapshot_names = tuple(snapshot_names)
        snapshot_output_levels = getattr(assignment, "snapshot_output_levels", ())
        snapshot_output_paths = getattr(assignment, "snapshot_output_paths", ())
        with window._sorting_paused():
            window.preset_table.setRowCount(0)
            window.preset_table.insertRow(0)
            selected = QTableWidgetItem()
            selected.setCheckState(Qt.CheckState.Checked)
            window.preset_table.setItem(0, 0, selected)
            window.preset_table.setItem(0, 1, QTableWidgetItem())
            window.preset_table.setItem(0, 2, QTableWidgetItem(preset_name))
            window.preset_table_controller.set_preset_original_filename(0, path.name)
            window.preset_table_controller.clear_preset_adjustments(0)
            window.preset_table_controller.refresh_preset_name(0)
            window.preset_table_controller.set_snapshot_names(0, snapshot_names)
            window.preset_table_controller.set_snapshot_output_levels(
                0, snapshot_output_levels, snapshot_output_paths
            )
            window._refresh_preset_table_editable_flags()

    def load_metadata(self) -> None:
        window = self.window
        path = Path(window.input_path.text())
        if not path.exists():
            window._set_metadata({})
            return

        try:
            profile = self.get_profile(window.device.currentData())
            handler = profile.create_patch_file_handler(Path(__file__).resolve().parents[3])
            handler.validate_input(path)
            window._set_metadata(handler.metadata(path))
        except Exception as exc:  # noqa: BLE001
            window._set_metadata({"error": str(exc)})

    def set_metadata(self, metadata: dict[str, object]) -> None:
        self.window.metadata_text.setPlainText(json.dumps(metadata, indent=2, ensure_ascii=False))
