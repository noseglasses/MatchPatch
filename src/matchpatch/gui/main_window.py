"""Main MatchPatch GUI window."""

from __future__ import annotations

import csv
import math
import re
import tempfile
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence, cast

from PySide6.QtCore import (
    QAbstractAnimation,
    QCoreApplication,
    QEvent,
    QObject,
    QPoint,
    QSettings,
    QSize,
    QTimer,
)
from PySide6.QtGui import (
    QCloseEvent,
    QHelpEvent,
    QIcon,
    QKeyEvent,
    QResizeEvent,
    Qt,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QSplitter,
    QStyle,
    QTableWidgetItem,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from matchpatch.config import (
    Config,
    default_config,
    default_config_path,
    export_config,
)
from matchpatch.custom_adjustments import CustomAdjustments, load_custom_adjustments_file
from matchpatch.devices import get_device_profile, list_device_profiles
from matchpatch.devices.base import (
    NormalizationPolicy,
    PatchFileAdjustments,
    normalize_regex_pattern,
)
from matchpatch.diagnostics import (
    DiagnosticCheck,
    DiagnosticSnapshot,
    progress_event_to_dict,
    snapshot_to_text,
    write_diagnostic_bundle,
)
from matchpatch.gui import diagnostics_panel as gui_diagnostics
from matchpatch.gui import (
    file_operations_workflow,
    file_type_filters,
    multi_hlx_workflow,
    save_dialogs,
    window_layout,
    window_state,
)
from matchpatch.gui import help as gui_help
from matchpatch.gui.advanced_settings import (
    GuiSettingsBinder,
    PresetTableSelectionContext,
    diagnostic_request,
)
from matchpatch.gui.device_panels import create_settings_panel
from matchpatch.gui.diagnostics_panel import (
    preset_table_selection_preflight_checks,
)
from matchpatch.gui.diagnostics_workflow import DiagnosticsWorkflowController
from matchpatch.gui.dialogs import ASSETS_DIR, AboutDialog, _question_mark_icon
from matchpatch.gui.hardware_checks import (
    HardwareCheckOverlay,
    backend_check_enabled,
    backend_check_required,
    completed_log_entries,
    failure_presentation,
)
from matchpatch.gui.help import HelpId
from matchpatch.gui.icons import (
    _ignore_reason_icon,
    _record_icon,
    _save_as_icon,
    _save_measurement_icon,
    _speaker_icon,
    _tooltip_size_hint,
    _visible_tooltip_position,
)
from matchpatch.gui.log_panel import GuiLogController
from matchpatch.gui.main_window_callbacks import (
    MainWindowPresetTableCallbacks,
    MainWindowSaveCallbacks,
)
from matchpatch.gui.measurement_optimization import (
    MeasurementOptimizationDialog,
    MeasurementOptimizationSettings,
    MeasurementOptimizationSetupDialog,
    _format_duration,
    _format_short_seconds,
)
from matchpatch.gui.measurement_optimization import (
    _optimization_progress_event_total as _optimization_progress_event_total,
)
from matchpatch.gui.name_rules import (
    device_name_max_length,
    validate_preset_name_for_device,
    validate_subdivision_name_for_device,
)
from matchpatch.gui.normalization_workflow import NormalizationWorkflowController
from matchpatch.gui.optimization_workflow import MeasurementOptimizationWorkflowController
from matchpatch.gui.playback import AudioPlaybackWorker
from matchpatch.gui.preset_table import (
    _PresetSelectionState,
    refresh_snapshot_name_cell_widget,
    snapshot_name_column,
)
from matchpatch.gui.preset_table_csv import (
    FunctionPresetTableCsvCallbacks,
    preset_table_csv_headers,
    preset_table_csv_row,
)
from matchpatch.gui.preset_table_csv import (
    load_preset_table_csv as load_preset_table_csv_file,
)
from matchpatch.gui.progress_widgets import (
    MeasurementProgressEstimate,
    MeasurementProgressPlan,
    phase_text,
    reference_audio_seconds,
)
from matchpatch.gui.results import (
    gain_correction_match,
    gain_preset_sync_patch,
    manual_adjustment_targets,
    parse_gain_correction_log,
    snapshot_measurement_display,
    snapshot_measurement_failure_display,
)
from matchpatch.gui.save_workflow import (
    SaveCancelled,
    SaveContext,
    SaveWorkflow,
)
from matchpatch.gui.table_formatting import (
    sanitize_helix_name,
    validate_helix_name,
)
from matchpatch.gui.table_legend import build_preset_table_legend_dialog
from matchpatch.gui.table_roles import (
    IGNORE_REASON_COMPARISON,
    IGNORE_REASON_PRESET,
    IGNORE_REASON_PRESET_REGEX,
    IGNORE_REASON_REGEX,
    PRESET_TABLE_ATTENTION_ROLE,
    PRESET_TABLE_CSV_DELIMITER,
    RECORDED_OUTPUT_PATH_ROLE,
)
from matchpatch.gui.window_layout import (
    MEASUREMENT_TIMING_PRESETS,
    TOOLBAR_ICON_SIZE,
    build_advanced,
    build_device_settings,
    build_diagnostics,
    build_files,
    build_footer,
    build_log,
    build_lufs,
    build_measurement,
    build_metadata,
    build_misc,
    build_preset_advanced_splitter,
    build_preset_empty_state,
    build_presets,
    build_progress,
    build_retained_csv,
    build_toolbar,
)
from matchpatch.gui.window_loading import WindowLoadingController
from matchpatch.gui.window_state import (
    FileActionState,
    active_file_title,
    file_action_state,
    recent_file_items,
    recent_file_paths,
    store_recent_file,
)
from matchpatch.gui.worker import (
    HardwareCheckWorker,
    MeasurementOptimizationWorker,
    NormalizationWorker,
    PreflightWorker,
)
from matchpatch.measurement_optimizer import (
    OptimizationProgress,
)
from matchpatch.progress import ProgressEvent
from matchpatch.workflow import (
    ImportRequest,
    NormalizationRequest,
    NormalizationResult,
    export_adjusted_file,
)

_format_hardware_check_request_details = gui_diagnostics.format_hardware_check_request_details
_format_preflight_results = gui_diagnostics.format_preflight_results
_format_preflight_results_html = gui_diagnostics.format_preflight_results_html
_hardware_check_failure_details = gui_diagnostics.hardware_check_failure_details
_preflight_check_display_name = gui_diagnostics.preflight_check_display_name
_preflight_headline = gui_diagnostics.preflight_headline

__all__ = ["MainWindow"]

MAX_RECENT_FILES = window_state.MAX_RECENT_FILES
TOOLBAR_VERTICAL_PADDING = window_layout.TOOLBAR_VERTICAL_PADDING

PROCESSING_DOT_GREY = "#9ca3af"
PROCESSING_DOT_GREEN = "#16a34a"
PROCESSING_DOT_RED = "#dc2626"
PHASE_ICON = {
    "ready": QStyle.StandardPixmap.SP_DialogApplyButton,
    "starting": QStyle.StandardPixmap.SP_MediaPlay,
    "preflight_checks": QStyle.StandardPixmap.SP_BrowserReload,
    "preparing_measurement": QStyle.StandardPixmap.SP_BrowserReload,
    "waiting_for_measurement_import": QStyle.StandardPixmap.SP_MediaPause,
    "measuring": QStyle.StandardPixmap.SP_ComputerIcon,
    "applying": QStyle.StandardPixmap.SP_BrowserReload,
    "completed": QStyle.StandardPixmap.SP_DialogApplyButton,
    "waiting_for_adjusted_import": QStyle.StandardPixmap.SP_MediaPause,
    "error": QStyle.StandardPixmap.SP_MessageBoxWarning,
    "cancelling": QStyle.StandardPixmap.SP_MessageBoxWarning,
    "normalization_cancelled_by_user": QStyle.StandardPixmap.SP_MessageBoxWarning,
}


class MainWindow(QMainWindow):
    def __getattr__(self, name: str) -> Any:  # noqa: ANN401
        raise AttributeError(name)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MatchPatch")
        self.setWindowIcon(QIcon(str(ASSETS_DIR / "matchmatch-icon.png")))
        self.setMinimumWidth(620)
        screen = QApplication.primaryScreen()
        available_height = screen.availableGeometry().height() if screen is not None else 800
        self.resize(820, min(760, max(560, available_height - 100)))
        self.hardware_check_worker: HardwareCheckWorker | None = None
        self.worker: NormalizationWorker | None = None
        self.optimization_worker: MeasurementOptimizationWorker | None = None
        self.preflight_worker: PreflightWorker | None = None
        self.optimization_dialog: MeasurementOptimizationDialog | None = None
        self.playback_worker: AudioPlaybackWorker | None = None
        self.completed_request: NormalizationRequest | None = None
        self.completed_result: NormalizationResult | None = None
        self._last_hardware_diagnostic_checks: list[DiagnosticCheck] = []
        self.device_panels: dict[str, Any] = {}
        self.snapshot_count = 4
        self.preset_snapshot_positions: dict[str, int] = {}
        self._adjusted_presets: set[str] = set()
        self._preset_table_modified = False
        self._preset_table_clean_signature: tuple[tuple[str, ...], ...] = ()
        self._loaded_input_path = ""
        self._staged_joined_setlist_path: Path | None = None
        self._multi_hlx_output_paths_by_id: dict[int, Path] = {}
        self._multi_hlx_input_count = 0
        self._preset_load_discard_confirmed = False
        self._manual_cell_editor: QLineEdit | None = None
        self._manual_cell_target: tuple[int, int] | None = None
        self._custom_adjustments: CustomAdjustments = {}
        self.log_controller: GuiLogController
        self.log_entries: list[tuple[str, str, str]] = []
        self.diagnostics_controller = DiagnosticsWorkflowController(
            self,
            worker_type=PreflightWorker,
            bundle_writer=write_diagnostic_bundle,
            summary_formatter=snapshot_to_text,
            progress_formatter=progress_event_to_dict,
        )
        self.loading_controller = WindowLoadingController(self)
        self.normalization_controller = NormalizationWorkflowController(
            self,
            worker_type=NormalizationWorker,
        )
        self._recent_progress_events: deque[ProgressEvent] = deque(maxlen=100)
        self._processing_dot_green = False
        self._loading_defaults = False
        self._available_backend: str | None = None
        self._pending_backend_check_request: NormalizationRequest | None = None
        self._pending_backend_check_action = "normalization"
        self._pending_optimization_preset_id: int | None = None
        self._pending_optimization_settings: MeasurementOptimizationSettings | None = None
        self._comparison_input_path: Path | None = None
        self._comparison_changed_by_patch: dict[str, tuple[int, ...]] | None = None
        self._optimization_stability_runs = 3
        self._optimization_termination_tolerance = 10.0
        self._optimization_stability_tolerance = 2.0
        self._last_measurement_optimization_settings: MeasurementOptimizationSettings | None = None
        self.optimization_controller = MeasurementOptimizationWorkflowController(
            self,
            setup_dialog_type=MeasurementOptimizationSetupDialog,
            result_dialog_type=MeasurementOptimizationDialog,
            worker_type=MeasurementOptimizationWorker,
        )
        self._measurement_progress_estimate: MeasurementProgressEstimate | None = None
        self._measurement_progress_plan: MeasurementProgressPlan | None = None
        self._deferred_gain_correction_logs: list[str] = []
        self._deferred_gain_correction_patch: str | None = None
        self._playback_toggle_path: Path | None = None
        self._recording_paths: dict[tuple[str, int], Path] = {}
        self._save_as_icon = _save_as_icon()
        self._save_measurement_icon = _save_measurement_icon()
        self._speaker_icon = _speaker_icon(enabled=True)
        self._speaker_off_icon = _speaker_icon(enabled=False)
        self._record_icon = _record_icon(recording=True)
        self._record_off_icon = _record_icon(recording=False)
        self._ignore_reason_icons = {
            reason: _ignore_reason_icon(reason)
            for reason in (
                IGNORE_REASON_PRESET,
                IGNORE_REASON_COMPARISON,
                IGNORE_REASON_REGEX,
                IGNORE_REASON_PRESET_REGEX,
            )
        }
        self._startup_resize_done = False
        self.settings = QSettings()

        self.input_path = QLineEdit()
        self.output_path = QLineEdit()
        self.backend = QComboBox()
        self.backend.currentTextChanged.connect(self.backend_changed)
        self._build_toolbar()
        content = QWidget()
        self.content = content
        scroll = QScrollArea()
        self.scroll_area = scroll
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        self.setCentralWidget(scroll)
        self._build_footer()
        self._build_hardware_check_overlay()
        layout = QVBoxLayout(content)
        layout.addWidget(self._build_preset_advanced_splitter(), 1)
        layout.addWidget(self._build_progress())
        layout.addWidget(self._build_retained_csv())
        layout.addStretch()
        self._set_phase("ready")
        self._populate_devices()
        self.load_defaults()
        self._refresh_file_actions()
        QTimer.singleShot(0, self._resize_to_initial_content_once)

    def _build_hardware_check_overlay(self) -> None:
        self.hardware_check_overlay = HardwareCheckOverlay(self)

    def _build_toolbar(self) -> None:
        build_toolbar(self)

    def _build_preset_advanced_splitter(self) -> QSplitter:
        return build_preset_advanced_splitter(self)

    def _build_presets(self) -> QWidget:
        return build_presets(self, MainWindowPresetTableCallbacks(self))

    def _build_preset_empty_state(self) -> QWidget:
        return build_preset_empty_state(self)

    def _sync_preset_empty_state_height(self) -> None:
        table_height = max(
            self.preset_table.minimumHeight(),
            self.preset_table.horizontalHeader().sizeHint().height()
            + self.preset_table.verticalHeader().defaultSectionSize()
            * self.preset_table.MAX_VISIBLE_ROWS
            + self.preset_table.frameWidth() * 2,
        )
        row_height = max(
            self.preset_header.sizeHint().height(),
            self.preset_table_note.sizeHint().height(),
            self.preset_measurement_time_estimate.sizeHint().height(),
            self.preset_csv_controls.sizeHint().height(),
            self.manual_adjustments.sizeHint().height(),
            self.show_legend_button.sizeHint().height(),
        )
        presets_layout = self.presets.layout()
        spacing = presets_layout.spacing() if presets_layout is not None else 0
        self.preset_empty_state.setMinimumHeight(table_height + row_height * 3 + spacing + 2)

    def _show_preset_empty_state(self) -> None:
        self.preset_header.hide()
        self.preset_empty_state.show()
        self.preset_table.hide()
        self.preset_table_note.hide()
        self.preset_measurement_time_estimate.hide()
        self.preset_csv_controls.hide()
        self.single_slot.hide()
        self.select_all_button.hide()
        self.unselect_all_button.hide()
        self.select_diff_button.hide()
        self.comparison_enabled.hide()
        self.show_legend_button.hide()
        self.manual_adjustments.hide()
        self.presets.show()
        self._refresh_preset_advanced_splitter_visibility()

    def _show_loaded_preset_state(self, *, single_preset: bool) -> None:
        self.preset_empty_state.hide()
        self.preset_header.show()
        self.single_slot.hide()
        self.preset_table.show()
        self.preset_measurement_time_estimate.show()
        self.preset_table.setColumnHidden(0, single_preset)
        self.preset_table_note.setVisible(not single_preset)
        self.preset_csv_controls.show()
        self.select_all_button.setVisible(not single_preset)
        self.unselect_all_button.setVisible(not single_preset)
        self.select_diff_button.show()
        self.comparison_enabled.show()
        self.show_legend_button.show()
        self.manual_adjustments.setVisible(not single_preset)
        self.manual_adjustments.setChecked(False)
        self.presets.show()
        self._refresh_preset_advanced_splitter_visibility()

    def _build_device_settings(self) -> QWidget:
        return build_device_settings(self)

    def _build_progress(self) -> QWidget:
        return build_progress(self)

    def _build_retained_csv(self) -> QWidget:
        return build_retained_csv(self)

    def _build_footer(self) -> None:
        build_footer(self)

    def _build_log(self) -> QWidget:
        return build_log(self)

    def _build_metadata(self) -> QWidget:
        return build_metadata(self)

    def _build_advanced(self) -> QWidget:
        return build_advanced(self)

    def _build_files(self) -> QWidget:
        return build_files(self)

    def _build_diagnostics(self) -> QWidget:
        return build_diagnostics(self)

    def _set_advanced_visible(self, visible: bool) -> None:
        if hasattr(self, "advanced"):
            self.advanced.setVisible(visible)
            self._refresh_preset_advanced_splitter_visibility()
            if visible:
                self._fit_advanced_splitter_width()
            self._schedule_resize_for_content()

    def _refresh_preset_advanced_splitter_visibility(self) -> None:
        if hasattr(self, "preset_advanced_splitter") and hasattr(self, "advanced"):
            self.preset_advanced_splitter.setVisible(
                not self.presets.isHidden() or not self.advanced.isHidden()
            )

    def _fit_advanced_splitter_width(self) -> None:
        if not hasattr(self, "preset_advanced_splitter") or self.presets.isHidden():
            return
        advanced_width = self.advanced.sizeHint().width()
        splitter_width = self.preset_advanced_splitter.width()
        if advanced_width <= 0 or splitter_width <= 0:
            return
        self.preset_advanced_splitter.setSizes(
            [max(0, splitter_width - advanced_width), advanced_width]
        )

    def _build_misc(self) -> QWidget:
        return build_misc(self)

    def _build_measurement(self) -> QWidget:
        return build_measurement(self)

    def _measurement_parameter_preset_changed(self, preset_name: str) -> None:
        if preset_name != "Fast":
            return
        QMessageBox.warning(
            self,
            "Fast measurement parameters",
            "Fast measurement parameters can lead to unstable measurements when effects "
            "with trails are used. Reverb and delay may make one snapshot's output bleed "
            "into the next snapshot's measurement.\n\nUse Default parameters or determine optimized parameters for your snapshots that are using trails if unsure.",
        )

    def apply_measurement_parameter_preset(self) -> None:
        preset_name = self.measurement_parameter_preset.currentText()
        values = MEASUREMENT_TIMING_PRESETS.get(preset_name)
        if values is None:
            return
        self._apply_measurement_timing_values(values)

    def _apply_measurement_timing_values(self, values: dict[str, float]) -> None:
        device = self.device.currentData()
        panel = self.device_panels.get(device)
        for name, value in values.items():
            text = str(value)
            getattr(self, name).setText(text)
            if panel is not None and hasattr(panel, name):
                getattr(panel, name).setText(text)

    def _refresh_measurement_time_estimate(self) -> None:
        if not hasattr(self, "measurement_time_estimate"):
            return

        try:
            estimate = MeasurementProgressEstimate(
                preset_wait=self._timing_input_value(self.preset_wait),
                snapshot_wait=self._timing_input_value(self.snapshot_wait),
                measurement_wait=self._timing_input_value(self.measurement_wait),
                pre_roll=self._timing_input_value(self.pre_roll),
                post_roll=self._timing_input_value(self.post_roll),
                round_trip_latency=self._timing_input_value(self.round_trip_latency),
                reference_audio_seconds=reference_audio_seconds(self.reference_di.text()),
            )
        except ValueError:
            self.measurement_time_estimate.setText(
                "Estimated measurement time per snapshot: invalid timing value"
            )
            self._refresh_preset_measurement_time_estimate(None)
            return

        preset_total = self._loaded_preset_count_for_estimate()
        measured_snapshot_total = self._loaded_snapshot_count_for_estimate()
        seconds = estimate.seconds_per_measured_snapshot(
            preset_total,
            measured_snapshot_total,
        )
        self.measurement_time_estimate.setText(
            "Estimated measurement time per snapshot: "
            f"{_format_short_seconds(seconds)} "
            f"({preset_total} preset{'s' if preset_total != 1 else ''}, "
            f"{measured_snapshot_total} snapshot"
            f"{'s' if measured_snapshot_total != 1 else ''})"
        )
        self._refresh_preset_measurement_time_estimate(estimate)

    def _refresh_preset_measurement_time_estimate(
        self, estimate: MeasurementProgressEstimate | None = None
    ) -> None:
        if not hasattr(self, "preset_measurement_time_estimate"):
            return

        if estimate is None:
            try:
                estimate = MeasurementProgressEstimate(
                    preset_wait=self._timing_input_value(self.preset_wait),
                    snapshot_wait=self._timing_input_value(self.snapshot_wait),
                    measurement_wait=self._timing_input_value(self.measurement_wait),
                    pre_roll=self._timing_input_value(self.pre_roll),
                    post_roll=self._timing_input_value(self.post_roll),
                    round_trip_latency=self._timing_input_value(self.round_trip_latency),
                    reference_audio_seconds=reference_audio_seconds(self.reference_di.text()),
                )
            except ValueError:
                self.preset_measurement_time_estimate.setText(
                    "Estimated total measurement time for selected presets: invalid timing value"
                )
                return

        preset_total = self._selected_preset_count_for_estimate()
        measured_snapshot_total = self._selected_snapshot_count_for_estimate()
        seconds = estimate.total_seconds_for_counts(preset_total, measured_snapshot_total)
        self.preset_measurement_time_estimate.setText(
            "Estimated total measurement time for selected presets: "
            f"{_format_short_seconds(seconds)} "
            f"({preset_total} preset{'s' if preset_total != 1 else ''}, "
            f"{measured_snapshot_total} snapshot"
            f"{'s' if measured_snapshot_total != 1 else ''})"
        )
        self._refresh_file_actions()

    @staticmethod
    def _timing_input_value(widget: QLineEdit) -> float:
        value = float(widget.text())
        if not math.isfinite(value):
            raise ValueError
        return max(0.0, value)

    def _loaded_preset_count_for_estimate(self) -> int:
        if not hasattr(self, "preset_table"):
            return 1
        return max(
            1,
            sum(
                1
                for row in range(self.preset_table.rowCount())
                if self._row_has_measured_snapshots(row)
            ),
        )

    def _selected_preset_count_for_estimate(self) -> int:
        if not hasattr(self, "preset_table") or self.preset_table.rowCount() == 0:
            return 1
        return max(1, len(self._selected_measurable_preset_rows()))

    def _loaded_snapshot_count_for_estimate(self) -> int:
        if not hasattr(self, "preset_table") or self.preset_table.rowCount() == 0:
            return self._snapshot_count_for_estimate()
        return max(
            1,
            sum(
                self._row_measured_snapshot_count(row)
                for row in range(self.preset_table.rowCount())
            ),
        )

    def _selected_snapshot_count_for_estimate(self) -> int:
        if not hasattr(self, "preset_table") or self.preset_table.rowCount() == 0:
            return self._snapshot_count_for_estimate()
        return max(
            1,
            sum(
                self._row_measured_snapshot_count(row)
                for row in self._selected_measurable_preset_rows()
            ),
        )

    def _snapshot_count_for_estimate(self) -> int:
        if hasattr(self, "snapshot_count_input"):
            return max(1, self.snapshot_count_input.value())
        return max(1, self.snapshot_count)

    def _row_measured_snapshot_indexes(self, row: int) -> tuple[int, ...]:
        return self.preset_table_controller.row_measured_snapshot_indexes(row)

    def _row_measured_snapshot_count(self, row: int) -> int:
        return self.preset_table_controller.row_measured_snapshot_count(row)

    def _row_has_measured_snapshots(self, row: int) -> bool:
        return self.preset_table_controller.row_has_measured_snapshots(row)

    def _has_ignored_snapshot_cells(self) -> bool:
        if not hasattr(self, "preset_table"):
            return False
        return self.preset_table_controller.has_ignored_snapshot_cells()

    def _checked_preset_rows(self) -> list[int]:
        return self.preset_table_controller.checked_preset_rows()

    def _selected_measurable_preset_rows(self) -> list[int]:
        if not hasattr(self, "preset_table"):
            return []
        return self.preset_table_controller.selected_measurable_preset_rows()

    def _has_optimization_preset_selection(self) -> bool:
        if not hasattr(self, "preset_table") or self.preset_table.rowCount() == 0:
            return False
        return self.preset_table_controller.has_optimization_preset_selection()

    def _build_lufs(self) -> QWidget:
        return build_lufs(self)

    def _populate_devices(self) -> None:
        for profile in list_device_profiles():
            self.device.addItem(profile.display_name, profile.name)
            panel = create_settings_panel(profile, self.backend)
            if panel is not None:
                self.device_panels[profile.name] = panel
                self.device_stack.addWidget(panel)
        self.loading_controller.refresh_backend_choices()

    def browse_input(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Choose patch file",
            filter=file_type_filters.open_patch_filter_for_device(self.device.currentData()),
        )
        multi_hlx_workflow.open_input_paths(self._multi_hlx_window(), paths)

    def _recent_file_paths(self) -> list[str]:
        return recent_file_paths(self.settings)

    def _store_recent_file(self, path: Path) -> None:
        store_recent_file(self.settings, path)
        self._refresh_recent_files_selector()

    def _refresh_recent_files_selector(self) -> None:
        if not hasattr(self, "recent_files"):
            return
        signals_blocked = self.recent_files.blockSignals(True)
        try:
            self.recent_files.clear()
            self.recent_files.addItem("Open recent file...", "")
            for item in recent_file_items(self.settings):
                self.recent_files.addItem(item.label, item.path)
            self.recent_files.setCurrentIndex(0)
            self.recent_files.setEnabled(self.recent_files.count() > 1)
        finally:
            self.recent_files.blockSignals(signals_blocked)

    def _recent_file_activated(self, index: int) -> None:
        path = self.recent_files.itemData(index) if hasattr(self, "recent_files") else ""
        if not path:
            self._refresh_recent_files_selector()
            return
        self._open_input_path(str(path))
        self._refresh_recent_files_selector()

    def _open_input_path(self, path: str) -> None:
        if not path or path == self.input_path.text():
            return
        if (
            self._preset_table_has_unsaved_changes()
            and not self._prompt_save_or_discard_preset_table_changes(
                "opening another preset or setlist file"
            )
        ):
            return
        self._preset_load_discard_confirmed = True
        self._staged_joined_setlist_path = None
        self._multi_hlx_output_paths_by_id = {}
        self._multi_hlx_input_count = 0
        self.input_path.setText(path)
        try:
            self.load_assignments()
        finally:
            self._preset_load_discard_confirmed = False

    def _confirm_discard_preset_table_changes(self) -> bool:
        if not self._preset_table_has_unsaved_changes():
            return True
        answer = QMessageBox.question(
            self,
            "Discard preset table changes",
            "The preset table contains unsaved changes. Opening another preset or setlist "
            "file will discard them.\n\nDiscard the changes and continue?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer in {QMessageBox.StandardButton.Discard, QMessageBox.StandardButton.Yes}

    def _choose_save_as_path(self, *, accept_label: str = "Save as") -> Path | None:
        return save_dialogs.choose_save_as_path(
            self,
            input_path_text=self.input_path.text(),
            device_name=self.device.currentData(),
            show_error=self.show_error,
            accept_label=accept_label,
        )

    def _choose_measurement_save_path(self) -> Path | None:
        return save_dialogs.choose_measurement_save_path(
            self,
            input_path=Path(self.input_path.text()),
            device_name=self.device.currentData(),
            show_error=self.show_error,
        )

    def browse_output(self) -> None:
        path = self._choose_save_as_path(accept_label="Save")
        if path is not None:
            self.output_path.setText(str(path))

    def save_measurement_file(self) -> bool:
        if not self._loaded_input_path:
            self.show_error("Open a Helix .hls or .hlx file before saving a measurement file")
            return False
        if not self._validate_single_preset_slot_for_run():
            return False

        output_path = self._choose_measurement_save_path()
        if output_path is None:
            return False

        try:
            request = GuiSettingsBinder.from_widgets(self).normalization_request()
            self._save_workflow().save_measurement_file(
                request,
                output_path,
                confirm_overwrite=self._confirm_overwrite,
            )
        except SaveCancelled:
            return False
        except Exception as exc:  # noqa: BLE001
            self.show_error(str(exc))
            return False

        self._log(f"Measurement file saved: {output_path.resolve()}", "success")
        return True

    def save_preset_table_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save preset table CSV",
            filter="Preset table CSV (*.csv)",
        )
        if not path:
            return

        csv_path = Path(path)
        if csv_path.suffix.lower() != ".csv":
            csv_path = csv_path.with_suffix(".csv")

        try:
            with csv_path.open("w", encoding="utf-8", newline="") as csv_file:
                writer = csv.writer(csv_file, delimiter=PRESET_TABLE_CSV_DELIMITER)
                writer.writerow(preset_table_csv_headers(self.snapshot_count))
                for row in range(self.preset_table.rowCount()):
                    writer.writerow(
                        preset_table_csv_row(self.preset_table, row, self.snapshot_count)
                    )
        except OSError as exc:
            self.show_error(f"Could not save preset table CSV: {exc}")
            return

        self._reset_preset_table_modified()
        self._log(f"Preset table CSV saved: {csv_path}", "success")

    def load_preset_table_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load preset table CSV",
            filter="Preset table CSV (*.csv)",
        )
        if not path:
            return

        try:
            before = self._preset_table_content_signature()
            adjusted_before = set(self._adjusted_presets)
            with self._sorting_paused():
                result = load_preset_table_csv_file(
                    Path(path),
                    self.preset_table,
                    self.snapshot_count,
                    self._preset_table_csv_callbacks(),
                )
                accepted, errors = result.accepted, result.errors
        except OSError as exc:
            self.show_error(f"Could not load preset table CSV: {exc}")
            return
        if self._preset_table_content_signature() != before:
            self._mark_preset_table_modified()
        else:
            self._adjusted_presets.clear()
            self._adjusted_presets.update(adjusted_before)
            self._reset_preset_table_modified()
            self._refresh_file_actions()

        for error in errors:
            self._log(error, "error")
        if errors:
            QMessageBox.critical(self, "Preset table CSV errors", "\n".join(errors))
        self._log(f"Preset table CSV loaded: {path} ({accepted} row(s) applied)", "success")

    def _preset_table_csv_callbacks(self) -> FunctionPresetTableCsvCallbacks:
        return FunctionPresetTableCsvCallbacks(
            validate_preset_name_callback=self._validate_preset_table_csv_preset_name,
            validate_snapshot_name_callback=self._validate_preset_table_csv_snapshot_name,
            is_solo_snapshot_name_callback=self._is_solo_snapshot_name,
            is_ignored_snapshot_name_callback=self._is_ignored_snapshot_name,
            set_snapshot_name_callback=self.preset_table_controller.set_snapshot_name,
            set_ignored_snapshot_highlight_callback=self.preset_table_controller.set_ignored_snapshot_highlight,
            set_adjustment_value_callback=self.preset_table_controller.set_adjustment_value,
            mark_preset_adjusted_callback=self._adjusted_presets.add,
        )

    def _validate_preset_table_csv_preset_name(self, name: str) -> None:
        validate_preset_name_for_device(self.device.currentData(), name)

    def _validate_preset_table_csv_snapshot_name(self, name: str) -> None:
        validate_subdivision_name_for_device(self.device.currentData(), name)

    def _is_solo_snapshot_name(self, name: str) -> bool:
        try:
            solo_pattern = re.compile(normalize_regex_pattern(self.solo_regex.text()))
        except re.error:
            return False
        return solo_pattern.search(name) is not None

    def _is_ignored_snapshot_name(self, name: str) -> bool:
        try:
            ignore_pattern = re.compile(normalize_regex_pattern(self.ignore_snapshot_regex.text()))
        except re.error:
            return False
        return ignore_pattern.search(name) is not None

    def show_help(self) -> bool:
        return self.open_help_topic(HelpId.DOCS_INDEX)

    def open_help_topic(self, help_id: str) -> bool:
        return gui_help.open_help(help_id)

    def _help_tool_button(self, tooltip: str, callback: Callable[[], object]) -> QToolButton:
        button = QToolButton(self)
        button.setIcon(_question_mark_icon(TOOLBAR_ICON_SIZE))
        button.setIconSize(QSize(TOOLBAR_ICON_SIZE, TOOLBAR_ICON_SIZE))
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(callback)
        return button

    def _open_current_advanced_help(self) -> bool:
        return self.open_help_topic(self._current_advanced_help_id())

    def _current_advanced_help_id(self) -> str:
        tab_help_id = self.advanced_tabs.tabBar().tabData(self.advanced_tabs.currentIndex())
        return tab_help_id if isinstance(tab_help_id, str) else HelpId.ADVANCED_SETTINGS

    def open_focused_help(self) -> bool:
        return self.open_help_topic(self._focused_help_id() or HelpId.QUICK_START)

    def _focused_help_id(self) -> str | None:
        return self._help_id_for_widget(QApplication.focusWidget())

    def _help_id_for_widget(self, widget: QObject | None) -> str | None:
        if widget is self.start_button:
            return self._normalization_help_id()
        if widget is self.preset_table:
            return self._preset_table_help_id()
        if hasattr(self, "advanced_tabs") and widget is self.advanced_tabs.tabBar():
            tab_help_id = self.advanced_tabs.tabBar().tabData(self.advanced_tabs.currentIndex())
            return tab_help_id if isinstance(tab_help_id, str) else None

        current = widget
        while current is not None:
            help_id = current.property("help_id")
            if isinstance(help_id, str) and help_id:
                return help_id
            current = current.parent()
        return None

    def _normalization_help_id(self) -> str:
        suffix = Path(self.input_path.text()).suffix.lower() if self._loaded_input_path else ""
        if suffix == ".hls":
            return HelpId.NORMALIZE_SETLIST
        if suffix == ".hlx":
            return HelpId.NORMALIZE_SINGLE_PRESET
        return HelpId.QUICK_START

    def _preset_table_help_id(self) -> str:
        suffix = Path(self.input_path.text()).suffix.lower() if self._loaded_input_path else ""
        if suffix == ".hls":
            return HelpId.NORMALIZE_SETLIST
        if suffix == ".hlx":
            return HelpId.NORMALIZE_SINGLE_PRESET
        return HelpId.OPEN_FILES

    def show_about(self) -> None:
        AboutDialog(self).exec()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_F1:
            self.open_focused_help()
            event.accept()
            return
        super().keyPressEvent(event)

    def browse_reference(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose reference DI", filter="Audio (*.wav)")
        if path:
            self.reference_di.setText(path)

    def browse_config(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose config", filter="TOML (*.toml)")
        if path:
            self.config_path.setText(path)
            self.load_defaults()

    def export_config(self) -> None:
        selection = self._choose_config_export_path()
        if selection is None:
            return
        path, save_default = selection
        config = default_config() if save_default else self._active_gui_config()
        message = "Saved default configuriation" if save_default else "Saved current configuration"

        try:
            saved_path = export_config(path, config)
        except Exception as exc:  # noqa: BLE001
            self.show_error(f"Could not export config: {exc}")
            return

        self.config_path.setText(str(saved_path))
        QMessageBox.information(self, "Export config", f"{message}:\n{saved_path}")

    def _choose_config_export_path(self) -> tuple[str, bool] | None:
        dialog = QFileDialog(self, "Export config")
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog)
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        dialog.setNameFilter("TOML (*.toml)")
        dialog.selectFile(str(Path(self.config_path.text().strip() or default_config_path())))
        dialog.setLabelText(QFileDialog.DialogLabel.Accept, "Save")
        save_default = QCheckBox("Save default configuration", dialog)
        save_default.setChecked(False)
        layout = dialog.layout()
        if isinstance(layout, QGridLayout):
            layout.addWidget(save_default, layout.rowCount(), 0, 1, -1)
        elif layout is not None:
            layout.addWidget(save_default)
        path = dialog.selectedFiles()[0] if dialog.exec() and dialog.selectedFiles() else ""
        if not path:
            return None
        return path, save_default.isChecked()

    def _choose_diagnostic_bundle_path(self) -> Path | None:
        dialog = QFileDialog(self, "Export diagnostic bundle")
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog)
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        dialog.setNameFilter("Zip archives (*.zip)")
        dialog.selectFile("matchpatch-diagnostics.zip")
        dialog.setLabelText(QFileDialog.DialogLabel.Accept, "Save")
        path = dialog.selectedFiles()[0] if dialog.exec() and dialog.selectedFiles() else ""
        return Path(path) if path else None

    def _current_diagnostic_request(self) -> NormalizationRequest:
        return diagnostic_request(
            GuiSettingsBinder.from_widgets(self),
            self._preset_table_selection_context(),
            completed_request=self.completed_request,
        )

    def _preset_table_selection_context(self) -> PresetTableSelectionContext:
        comparison_snapshot_plan = (
            self._comparison_changed_by_patch
            if hasattr(self, "comparison_enabled")
            and self.comparison_enabled.isChecked()
            and self._comparison_changed_by_patch is not None
            else None
        )
        return PresetTableSelectionContext(
            has_table=hasattr(self, "preset_table"),
            row_count=self.preset_table.rowCount() if hasattr(self, "preset_table") else 0,
            checked_rows=set(self._checked_preset_rows()),
            has_ignored_snapshots=self._has_ignored_snapshot_cells(),
            comparison_snapshot_plan=comparison_snapshot_plan,
            input_path=self.input_path.text(),
            patch_at_row=self._preset_patch_at_row,
            row_measured_snapshot_indexes=self._row_measured_snapshot_indexes,
            measurement_progress_plan_for_request=self._measurement_progress_plan_for_request,
            progress_plan_factory=MeasurementProgressPlan,
        )

    def _preset_patch_at_row(self, row: int) -> str | None:
        patch_item = self.preset_table.item(row, 1)
        return patch_item.text() if patch_item is not None else None

    def _current_diagnostic_snapshot(
        self,
        checks: Sequence[DiagnosticCheck] = (),
    ) -> DiagnosticSnapshot:
        self.diagnostics_controller.progress_formatter = progress_event_to_dict
        return self.diagnostics_controller.current_snapshot(checks)

    def export_diagnostic_bundle(self) -> None:
        self.diagnostics_controller.bundle_writer = write_diagnostic_bundle
        self.diagnostics_controller.export_bundle()

    def copy_diagnostic_summary(self) -> None:
        self.diagnostics_controller.summary_formatter = snapshot_to_text
        self.diagnostics_controller.copy_summary()

    def run_preflight_check(self) -> None:
        self.diagnostics_controller.worker_type = PreflightWorker
        self.diagnostics_controller.run_preflight_check()

    def _preflight_completed(self, checks: Sequence[DiagnosticCheck]) -> None:
        self.diagnostics_controller.preflight_completed(checks)

    def _preflight_checks_with_preset_table_selection(
        self,
        checks: Sequence[DiagnosticCheck],
    ) -> list[DiagnosticCheck]:
        return self.diagnostics_controller.preflight_checks_with_preset_table_selection(checks)

    def _preset_table_selection_preflight_checks(self) -> list[DiagnosticCheck]:
        return preset_table_selection_preflight_checks(self._preset_table_selection_context())

    def _preflight_failed(self, detail: str) -> None:
        self.diagnostics_controller.preflight_failed(detail)

    def _preflight_finished(self) -> None:
        self.diagnostics_controller.preflight_finished()

    def _show_preflight_results(self, checks: Sequence[DiagnosticCheck]) -> None:
        self.diagnostics_controller.show_preflight_results(checks)

    def _active_gui_config(self) -> Config:
        return GuiSettingsBinder.from_widgets(self).active_config()

    def browse_custom_adjustments(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose custom adjustments CSV",
            filter="CSV (*.csv)",
        )
        if not path:
            return
        try:
            load_custom_adjustments_file(Path(path), self.snapshot_count_input.value())
        except Exception as exc:  # noqa: BLE001
            self.show_error(f"Could not parse custom adjustments CSV: {exc}")
            return
        self.custom_adjustments_path.setText(path)

    def device_changed(self) -> None:
        self.loading_controller.device_changed()

    def backend_changed(self) -> None:
        self.loading_controller.backend_changed()

    def _refresh_backend_tooltip(self) -> None:
        self.loading_controller.refresh_backend_tooltip()

    def load_defaults(self) -> None:
        self.loading_controller.get_profile = get_device_profile
        self.loading_controller.load_defaults()

    def _backend_check_enabled(self) -> bool:
        return backend_check_enabled()

    def _backend_check_required(self, request: NormalizationRequest) -> bool:
        return backend_check_required(
            request,
            available_backend=self._available_backend,
            check_enabled=self._backend_check_enabled(),
        )

    def load_assignments(self) -> None:
        self.loading_controller.get_profile = get_device_profile
        self.loading_controller.load_assignments()

    def _set_preset_csv_buttons_enabled(self, enabled: bool) -> None:
        if hasattr(self, "load_csv_button"):
            self.load_csv_button.setEnabled(enabled)
        if hasattr(self, "save_csv_button"):
            self.save_csv_button.setEnabled(enabled)

    def _load_custom_adjustments(self, request: NormalizationRequest) -> CustomAdjustments:
        return self.loading_controller.load_custom_adjustments(request)

    def _populate_single_preset_table(self, path: Path, assignment: object | None = None) -> None:
        self.loading_controller.populate_single_preset_table(path, assignment)

    def _load_metadata(self) -> None:
        self.loading_controller.get_profile = get_device_profile
        self.loading_controller.load_metadata()

    def _set_metadata(self, metadata: dict[str, object]) -> None:
        self.loading_controller.set_metadata(metadata)

    def start_normalization(self) -> None:
        self.normalization_controller.start_normalization()

    def determine_optimal_parameters(self) -> None:
        self.optimization_controller.determine_optimal_parameters()

    def _start_measurement_optimization_request(
        self,
        request: NormalizationRequest,
        preset_id: int,
        settings: MeasurementOptimizationSettings,
    ) -> None:
        self.optimization_controller.worker_type = MeasurementOptimizationWorker
        self.optimization_controller.result_dialog_type = MeasurementOptimizationDialog
        self.optimization_controller.start_request(request, preset_id, settings)

    def _ensure_playback_toggle_path(self) -> Path:
        if self._playback_toggle_path is None:
            temporary = tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                prefix="matchpatch_playback_",
                suffix=".txt",
                delete=False,
            )
            self._playback_toggle_path = Path(temporary.name)
            temporary.close()
        self._write_playback_toggle()
        return self._playback_toggle_path

    def _playback_toggle_changed(self, checked: bool) -> None:
        self.play_recorded_output_button.setIcon(
            self._speaker_icon if checked else self._speaker_off_icon
        )
        self._write_playback_toggle(checked)

    def _record_output_toggle_changed(self, checked: bool) -> None:
        self.record_output_button.setIcon(self._record_icon if checked else self._record_off_icon)

    def _write_playback_toggle(self, checked: bool | None = None) -> None:
        if self._playback_toggle_path is None:
            return
        enabled = self.play_recorded_output_button.isChecked() if checked is None else checked
        try:
            self._playback_toggle_path.write_text("1" if enabled else "0", encoding="utf-8")
        except OSError as exc:
            self._log(f"Could not update playback toggle: {exc}", "warning")

    def _show_measurement_optimization_setup(
        self,
        request: NormalizationRequest,
        preset_id: int,
        initial_settings: MeasurementOptimizationSettings | None = None,
    ) -> MeasurementOptimizationSettings | None:
        self.optimization_controller.setup_dialog_type = MeasurementOptimizationSetupDialog
        return self.optimization_controller.show_setup(request, preset_id, initial_settings)

    def _request_with_measurement_optimization_settings(
        self,
        request: NormalizationRequest,
        settings: MeasurementOptimizationSettings,
    ) -> NormalizationRequest:
        return self.optimization_controller.request_with_settings(request, settings)

    def _apply_measurement_optimization_settings(
        self, settings: MeasurementOptimizationSettings
    ) -> None:
        self.optimization_controller.apply_settings(settings)

    def _optimization_preset_id(self, request: NormalizationRequest) -> int:
        return self.optimization_controller.preset_id(request)

    def _update_measurement_optimization(self, event: OptimizationProgress) -> None:
        self.optimization_controller.update_progress(event)

    def _measurement_optimization_completed(self, toml_text: str) -> None:
        self.optimization_controller.completed(toml_text)

    def _apply_measurement_optimization_result(self, toml_text: str) -> None:
        self.optimization_controller.apply_result(toml_text)

    def _measurement_optimization_cancelled(self) -> None:
        self.optimization_controller.cancelled()

    def _measurement_optimization_failed(self, detail: str) -> None:
        self.optimization_controller.failed(detail)

    def _measurement_optimization_finished(self) -> None:
        self.optimization_controller.finished()

    def _cancel_measurement_optimization(self) -> None:
        self.optimization_controller.cancel()

    def _start_normalization_request(self, request: NormalizationRequest) -> None:
        self.normalization_controller.worker_type = NormalizationWorker
        self.normalization_controller.start_request(request)

    def _measurement_progress_plan_for_request(
        self,
        request: NormalizationRequest,
    ) -> MeasurementProgressPlan | None:
        if not hasattr(self, "preset_table") or self.preset_table.rowCount() == 0:
            return None

        requested_patches = None
        if request.preset_set:
            requested_patches = {patch.strip().upper() for patch in request.preset_set.split(",")}

        preset_snapshots = []
        for row in range(self.preset_table.rowCount()):
            patch_item = self.preset_table.item(row, 1)
            if patch_item is None:
                continue
            patch = patch_item.text().strip().upper()
            if not patch:
                continue
            if requested_patches is not None and patch not in requested_patches:
                continue
            snapshots = self._row_measured_snapshot_indexes(row)
            if snapshots:
                preset_snapshots.append((patch, snapshots))

        if not preset_snapshots:
            return None
        return MeasurementProgressPlan(tuple(preset_snapshots))

    def _start_hardware_check(
        self,
        request: NormalizationRequest,
        *,
        action: str,
        optimization_preset_id: int | None = None,
        optimization_settings: MeasurementOptimizationSettings | None = None,
    ) -> None:
        if self.hardware_check_worker is not None or self.worker is not None:
            return

        self.start_button.setEnabled(False)
        self.determine_parameters_button.setEnabled(False)
        if hasattr(self, "diagnostics_panel"):
            self.diagnostics_panel.set_workflow_active(True)
        self._show_hardware_check_overlay()
        self._set_phase("starting")
        self._log("Checking backend availability", "info")
        self.hardware_check_worker = HardwareCheckWorker(request, self)
        self._pending_backend_check_request = request
        self._pending_backend_check_action = action
        self._pending_optimization_preset_id = optimization_preset_id
        self._pending_optimization_settings = optimization_settings
        self._last_hardware_diagnostic_checks = []
        self.hardware_check_worker.diagnostics_completed.connect(
            self._hardware_check_diagnostics_completed
        )
        self.hardware_check_worker.completed.connect(self._hardware_check_completed)
        self.hardware_check_worker.failed.connect(self._hardware_check_failed)
        self.hardware_check_worker.finished.connect(self._hardware_check_finished)
        self.hardware_check_worker.finished.connect(self.hardware_check_worker.deleteLater)
        self.hardware_check_worker.start()

    def _hardware_check_diagnostics_completed(self, checks: Sequence[DiagnosticCheck]) -> None:
        self._last_hardware_diagnostic_checks = list(checks)

    def _hardware_check_completed(self) -> None:
        self._hide_hardware_check_overlay()
        request = self._pending_backend_check_request
        action = self._pending_backend_check_action
        optimization_preset_id = self._pending_optimization_preset_id
        optimization_settings = self._pending_optimization_settings
        self._pending_backend_check_request = None
        self._pending_backend_check_action = "normalization"
        self._pending_optimization_preset_id = None
        self._pending_optimization_settings = None
        if request is not None:
            self._available_backend = request.backend
        for message, level in completed_log_entries(self._last_hardware_diagnostic_checks):
            self._log(message, level)
        if request is not None and action == "optimization":
            if optimization_settings is None:
                setup_preset_id = (
                    optimization_preset_id
                    if optimization_preset_id is not None
                    else self._optimization_preset_id(request)
                )
                optimization_settings = self._show_measurement_optimization_setup(
                    request, setup_preset_id
                )
                if optimization_settings is None:
                    self.start_button.setEnabled(True)
                    self._refresh_file_actions()
                    self._set_phase("ready")
                    return
                request = self._request_with_measurement_optimization_settings(
                    request, optimization_settings
                )
                self._apply_measurement_optimization_settings(optimization_settings)
            self._start_measurement_optimization_request(
                request,
                optimization_preset_id
                if optimization_preset_id is not None
                else self._optimization_preset_id(request),
                optimization_settings,
            )
            return
        if request is not None:
            self._start_normalization_request(request)
            return
        self.start_button.setEnabled(True)
        self._refresh_file_actions()
        self._set_phase("ready")

    def _hardware_check_failed(self, detail: str) -> None:
        self._hide_hardware_check_overlay()
        request = self._pending_backend_check_request
        action = self._pending_backend_check_action
        optimization_preset_id = self._pending_optimization_preset_id
        optimization_settings = self._pending_optimization_settings
        self._pending_backend_check_request = None
        self._pending_backend_check_action = "normalization"
        self._pending_optimization_preset_id = None
        self._pending_optimization_settings = None
        self.start_button.setEnabled(True)
        self._refresh_file_actions()
        self._set_phase("ready")
        presentation = failure_presentation(
            request=request,
            checks=self._last_hardware_diagnostic_checks,
            detail=detail,
        )
        for message, level in presentation.log_entries:
            self._log(message, level)
        QMessageBox.critical(
            self,
            "Error",
            presentation.popup_message,
        )
        if (
            request is not None
            and action == "optimization"
            and optimization_preset_id is not None
            and optimization_settings is not None
        ):
            QTimer.singleShot(
                0,
                lambda: self._restore_measurement_optimization_setup(
                    request,
                    optimization_preset_id,
                    optimization_settings,
                ),
            )

    def _hardware_check_finished(self) -> None:
        self.hardware_check_worker = None
        self._refresh_file_actions()

    def _restore_measurement_optimization_setup(
        self,
        request: NormalizationRequest,
        preset_id: int,
        settings: MeasurementOptimizationSettings,
    ) -> None:
        if self.hardware_check_worker is not None:
            QTimer.singleShot(
                0,
                lambda: self._restore_measurement_optimization_setup(
                    request,
                    preset_id,
                    settings,
                ),
            )
            return

        restored_settings = self._show_measurement_optimization_setup(
            request,
            preset_id,
            settings,
        )
        if restored_settings is None:
            return

        retry_request = self._request_with_measurement_optimization_settings(
            request,
            restored_settings,
        )
        self._apply_measurement_optimization_settings(restored_settings)
        if self._backend_check_required(retry_request):
            self._start_hardware_check(
                retry_request,
                action="optimization",
                optimization_preset_id=preset_id,
                optimization_settings=restored_settings,
            )
            return

        self._available_backend = retry_request.backend
        self._start_measurement_optimization_request(
            retry_request,
            preset_id,
            restored_settings,
        )

    def _show_hardware_check_overlay(self) -> None:
        target = self.centralWidget() or self
        self.hardware_check_overlay.show_over(target)

    def _hide_hardware_check_overlay(self) -> None:
        self.hardware_check_overlay.hide()

    def _position_hardware_check_overlay(self) -> None:
        target = self.centralWidget() or self
        self.hardware_check_overlay.setGeometry(target.geometry())

    def _confirm_automation_overwrites(self, request: NormalizationRequest) -> bool:
        return self.normalization_controller.confirm_automation_overwrites(request)

    def update_progress(self, event: ProgressEvent) -> None:
        self.normalization_controller.update_progress(event)

    def _update_normalization_focus(self, event: ProgressEvent) -> None:
        self.normalization_controller.update_normalization_focus(event)

    def _set_normalization_focus(self, device_patch: str | None, snapshot: int | None) -> None:
        self.normalization_controller.set_normalization_focus(device_patch, snapshot)

    def _clear_normalization_focus(self) -> None:
        self.normalization_controller.clear_normalization_focus()

    def _clear_normalization_snapshot_focus(self, device_patch: str | None) -> None:
        self.normalization_controller.clear_normalization_snapshot_focus(device_patch)

    def _set_recorded_output(self, event: ProgressEvent) -> None:
        self.normalization_controller.set_recorded_output(event)

    def _play_recording(self, path: Path) -> None:
        if self._normalization_in_progress():
            return
        if self.playback_worker is not None and self.playback_worker.isRunning():
            return
        windows_python = self.completed_request.windows_python if self.completed_request else None
        self.playback_worker = AudioPlaybackWorker(path, self, windows_python=windows_python)
        self.playback_worker.failed.connect(self.show_error)
        self.playback_worker.finished.connect(self._playback_finished)
        self.playback_worker.finished.connect(self.playback_worker.deleteLater)
        self.playback_worker.start()

    def _playback_finished(self) -> None:
        self.playback_worker = None

    def _normalization_in_progress(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def _refresh_recorded_output_buttons(self) -> None:
        for row in range(self.preset_table.rowCount()):
            for snapshot_index in range(self.snapshot_count):
                item = self.preset_table.item(row, snapshot_name_column(snapshot_index))
                if item is not None and item.data(RECORDED_OUTPUT_PATH_ROLE):
                    self._refresh_snapshot_name_cell_widget(item)

    def _show_indeterminate_progress(self, message: str) -> None:
        progress_was_hidden = self.progress_group.isHidden()
        self.current.setText(message)
        self.preset_progress.setRange(0, 0)
        self.preset_progress.resetFormat()
        self.progress_group.show()
        if progress_was_hidden:
            self._schedule_resize_for_content()

    def _hide_progress(self) -> None:
        if self.progress_group.isHidden():
            return
        self.preset_progress.resetFormat()
        self.progress_group.hide()
        self._schedule_resize_for_content()

    def _update_measurement_progress_format(self, event: ProgressEvent) -> None:
        estimate = self._measurement_progress_estimate
        if estimate is None or event.preset_total is None or event.snapshot_total is None:
            self.preset_progress.resetFormat()
            return

        plan = self._measurement_progress_plan
        if plan is not None:
            total_seconds = estimate.total_seconds_for_counts(
                plan.preset_total,
                plan.measured_snapshot_total,
            )
            remaining_seconds = estimate.remaining_seconds_for_plan(event, plan)
        else:
            total_seconds = estimate.total_seconds(event.preset_total, event.snapshot_total)
            remaining_seconds = estimate.remaining_seconds(
                event,
                event.preset_total,
                event.snapshot_total,
            )
        self.preset_progress.setFormat(
            "%p% | total "
            f"{_format_duration(total_seconds)} | ETA {_format_duration(remaining_seconds)}"
        )

    def confirm_import(self, request: ImportRequest) -> None:
        self.normalization_controller.confirm_import(request)

    def normalization_completed(self, result: NormalizationResult) -> None:
        self.normalization_controller.completed(result)

    def _show_normalization_completion_popup(self) -> None:
        self.normalization_controller.show_completion_popup()

    def _manual_adjustment_targets(self) -> list[str]:
        return manual_adjustment_targets(self.preset_table_controller.manual_adjustment_snapshots())

    def export_output(self) -> None:
        self.save_active_file()

    def save_active_file(self) -> bool:
        active_path = Path(self.input_path.text().strip())
        if not self.input_path.text().strip():
            self.show_error("Open a Helix .hls or .hlx file before saving")
            return False
        if self._multi_hlx_output_paths_by_id:
            return multi_hlx_workflow.save_multi_hlx_files(self._multi_hlx_window())
        if active_path == self._staged_joined_setlist_path:
            return self.save_active_file_as()
        return self._save_to_path(active_path)

    def save_active_file_as(self) -> bool:
        output_path = self._choose_save_as_path()
        if output_path is None:
            return False
        return self._save_to_path(output_path, make_active=True)

    def _save_to_path(self, output_path: Path, *, make_active: bool = True) -> bool:
        request = self.completed_request
        result = self.completed_result
        table_has_unsaved_changes = self._preset_table_has_unsaved_changes()
        preserved_preset_selection = self._preset_selection_state()
        if not self.input_path.text().strip():
            self.show_error("Open a Helix .hls or .hlx file before saving")
            return False

        if table_has_unsaved_changes and request is None:
            try:
                request = GuiSettingsBinder.from_widgets(self).normalization_request()
            except Exception as exc:  # noqa: BLE001
                self.show_error(str(exc))
                return False

        try:
            save_result = self._save_workflow().save_adjusted_file(
                SaveContext(
                    input_path=Path(self.input_path.text()),
                    output_path=output_path,
                    completed_request=request,
                    completed_result=result,
                    table_has_unsaved_changes=table_has_unsaved_changes,
                    make_active=make_active,
                ),
                MainWindowSaveCallbacks(self),
            )
        except SaveCancelled:
            return False
        except Exception as exc:  # noqa: BLE001
            self.show_error(str(exc))
            return False

        if not save_result.saved_table_changes:
            if save_result.copied_active_file:
                preserved_single_preset_slot = (
                    self._single_preset_slot_text()
                    if Path(self.input_path.text()).suffix.lower() == ".hlx"
                    else None
                )
                self._activate_saved_file(
                    output_path,
                    preserved_single_preset_slot=preserved_single_preset_slot,
                    preserved_preset_selection=preserved_preset_selection,
                )
            return True

        self._set_phase("completed")
        self._log(f"Saved: {output_path.resolve()}", "success")
        if make_active:
            self._activate_saved_file_without_reloading_preset_table(output_path)
        else:
            self._reset_preset_table_modified()
            self._refresh_file_actions()
        return True

    def _save_workflow(self) -> SaveWorkflow:
        return SaveWorkflow(get_profile=get_device_profile, export_file=export_adjusted_file)

    def _activate_saved_file(
        self,
        path: Path,
        *,
        preserved_single_preset_slot: str | None = None,
        preserved_preset_selection: _PresetSelectionState | None = None,
    ) -> None:
        self.input_path.setText(str(path))
        self._preset_load_discard_confirmed = True
        try:
            self.load_assignments()
        finally:
            self._preset_load_discard_confirmed = False
        if preserved_preset_selection is not None and path.suffix.lower() != ".hlx":
            self._restore_preset_selection_state(preserved_preset_selection)
        if preserved_single_preset_slot is None or path.suffix.lower() != ".hlx":
            return
        item = self.preset_table.item(0, 1)
        if item is None:
            return
        signals_blocked = self.preset_table.blockSignals(True)
        try:
            item.setText(preserved_single_preset_slot)
        finally:
            self.preset_table.blockSignals(signals_blocked)
        self._reset_preset_table_modified()

    def _activate_saved_file_without_reloading_preset_table(self, path: Path) -> None:
        self.input_path.setText(str(path))
        self._loaded_input_path = str(path)
        self._staged_joined_setlist_path = None
        self._multi_hlx_output_paths_by_id = {}
        self._multi_hlx_input_count = 0
        self._set_active_file(path)
        self._store_recent_file(path)
        self._load_metadata()
        self._reset_preset_table_modified()
        self._refresh_file_actions()

    def _mark_joined_setlist_staged(self, path: Path) -> None:
        multi_hlx_workflow.mark_joined_setlist_staged(self._multi_hlx_window(), path)

    def _multi_hlx_window(self) -> multi_hlx_workflow.MultiHlxWindow:
        return cast(multi_hlx_workflow.MultiHlxWindow, self)

    def _set_active_file(self, path: Path) -> None:
        self.setWindowTitle(active_file_title(path))

    def _refresh_file_actions(self) -> None:
        action_state = self._current_file_action_state()
        self._apply_file_action_state(action_state)

    def _current_file_action_state(self) -> FileActionState:
        has_loaded_file = bool(self._loaded_input_path)
        return file_action_state(
            has_file=bool(self.input_path.text().strip()),
            has_loaded_file=has_loaded_file,
            preset_table_modified=self._preset_table_has_unsaved_changes(),
            has_preset_selection=hasattr(self, "determine_parameters_button")
            and self._has_optimization_preset_selection(),
            normalization_active=self.worker is not None,
            hardware_check_active=self.hardware_check_worker is not None,
            optimization_active=self.optimization_worker is not None,
            preflight_active=self.preflight_worker is not None,
        )

    def _apply_file_action_state(self, action_state: FileActionState) -> None:
        self._set_optional_widget_enabled("save_action", action_state.save_enabled)
        self._set_optional_widget_enabled("save_as_action", action_state.save_as_enabled)
        self._set_optional_widget_enabled(
            "save_measurement_action",
            action_state.save_measurement_enabled,
        )
        file_operations_workflow.apply_file_operation_action_state(
            cast(file_operations_workflow.FileOperationWindow, self),
            action_state,
            get_profile=get_device_profile,
            project_dir=Path(__file__).resolve().parents[3],
        )
        self._set_optional_widget_enabled("start_button", action_state.start_enabled)
        self._set_optional_widget_enabled(
            "run_normalization_action",
            action_state.start_enabled,
        )
        self._refresh_determine_parameters_action(action_state)
        self._set_optional_widget_enabled(
            "record_output_button",
            action_state.record_output_enabled,
        )
        self._set_optional_widget_enabled(
            "play_recorded_output_button",
            action_state.play_recorded_output_enabled,
        )
        if hasattr(self, "diagnostics_panel"):
            self.diagnostics_panel.set_workflow_active(action_state.workflow_active)

    def _set_optional_widget_enabled(self, name: str, enabled: bool) -> None:
        widget = getattr(self, name, None)
        if widget is not None:
            widget.setEnabled(enabled)

    def _refresh_determine_parameters_action(self, action_state: FileActionState) -> None:
        if not hasattr(self, "determine_parameters_button"):
            return
        self.determine_parameters_button.setEnabled(action_state.determine_enabled)
        if not hasattr(self, "determine_parameters_hint"):
            return
        if action_state.determine_enabled:
            self.determine_parameters_hint.hide()
            return
        self.determine_parameters_hint.setText(action_state.determine_hint)
        self.determine_parameters_hint.show()

    def _prompt_save_before_normalization(self) -> bool:
        result = self._prompt_save_or_discard_preset_table_changes("starting normalization")
        if result == "discard":
            self._discard_preset_table_changes()
            return True
        return bool(result)

    def _prompt_save_or_discard_preset_table_changes(self, action: str) -> bool | str:
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Save changes")
        dialog.setText(f"The preset table contains changes. Save them before {action}?")
        save_button = dialog.addButton(QMessageBox.StandardButton.Save)
        save_as_button = dialog.addButton("Save As", QMessageBox.ButtonRole.AcceptRole)
        discard_button = dialog.addButton(QMessageBox.StandardButton.Discard)
        dialog.addButton(QMessageBox.StandardButton.Cancel)
        dialog.setDefaultButton(save_button)
        dialog.exec()
        clicked = dialog.clickedButton()
        if clicked is save_button:
            return self.save_active_file()
        if clicked is save_as_button:
            return self.save_active_file_as()
        if clicked is discard_button:
            return "discard"
        return False

    def _discard_preset_table_changes(self) -> None:
        preserved_preset_selection = self._preset_selection_state()
        self._preset_load_discard_confirmed = True
        try:
            self.load_assignments()
        finally:
            self._preset_load_discard_confirmed = False
        if Path(self.input_path.text()).suffix.lower() != ".hlx":
            self._restore_preset_selection_state(preserved_preset_selection)

    def _confirm_overwrite(self, output_path: Path) -> bool:
        if not output_path.exists():
            return True
        answer = QMessageBox.question(
            self,
            "Overwrite file",
            f"The file already exists:\n{output_path}\n\nOverwrite it?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def show_error(self, message: str) -> None:
        self._stop_busy_phase()
        self._set_phase("error")
        self._log(message, "error")
        QMessageBox.critical(self, "Error", message)

    def normalization_cancelled(self) -> None:
        self.normalization_controller.cancelled()

    def worker_finished(self) -> None:
        self.normalization_controller.worker_finished()

    def _discard_completed_export(self) -> None:
        self.normalization_controller.discard_completed_export()

    def cancel_normalization(self) -> None:
        self.normalization_controller.cancel_normalization()

    def _confirm_cancellation(self) -> bool:
        return self.normalization_controller.confirm_cancellation()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.hardware_check_worker is not None or self.preflight_worker is not None:
            event.ignore()
            return
        if (
            self._preset_table_has_unsaved_changes()
            and not self._confirm_discard_preset_table_changes()
        ):
            event.ignore()
            return
        if self.worker is not None:
            if not self._confirm_cancellation():
                event.ignore()
                return
            self.worker.cancel()
        if self.optimization_worker is not None:
            self.optimization_worker.cancel()
        if self.worker is not None:
            self.worker.wait()
        if self.optimization_worker is not None:
            self.optimization_worker.wait()
        self._discard_completed_export()
        super().closeEvent(event)
        QApplication.quit()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if hasattr(self, "hardware_check_overlay") and self.hardware_check_overlay.isVisible():
            self._position_hardware_check_overlay()

    def _preset_selection_state(self) -> _PresetSelectionState:
        return self.preset_table_controller.preset_selection_state()

    def _restore_preset_selection_state(self, state: _PresetSelectionState) -> None:
        self.preset_table_controller.restore_preset_selection_state(state)

    def _single_preset_slot_text(self) -> str:
        item = self.preset_table.item(0, 1)
        return item.text().strip().upper() if item is not None else ""

    def _validate_single_preset_slot_for_run(self) -> bool:
        if Path(self.input_path.text()).suffix.lower() != ".hlx":
            return True

        slot = self._single_preset_slot_text()
        if not slot:
            self._highlight_preset_cell(0, 1)
            QMessageBox.warning(
                self,
                "Preset ID required",
                "Enter the temporary Helix preset ID in the Preset column before running normalization.",
            )
            return False

        try:
            self._parse_single_helix_preset_slot(slot)
        except ValueError as exc:
            self.show_error(str(exc))
            self._highlight_preset_cell(0, 1)
            return False

        return True

    def _parse_single_helix_preset_slot(self, slot: str) -> int:
        profile = get_device_profile(self.device.currentData())
        handler = profile.create_patch_file_handler(Path(__file__).resolve().parents[3])
        preset_ids = handler.parse_patch_set(slot)
        if len(preset_ids) != 1:
            raise ValueError("Enter exactly one Helix preset ID for a .hlx file.")

        preset_id = preset_ids[0]
        if preset_id < 1 or preset_id > 128:
            raise ValueError("Helix preset ID must be between 01A and 32D.")
        return preset_id

    def _highlight_preset_cell(self, row: int, column: int) -> None:
        item = self.preset_table.item(row, column)
        if item is None:
            return

        signals_blocked = self.preset_table.blockSignals(True)
        try:
            item.setData(PRESET_TABLE_ATTENTION_ROLE, True)
        finally:
            self.preset_table.blockSignals(signals_blocked)
        self.preset_table.setCurrentCell(row, column)
        self.preset_table.scrollToItem(item)
        self.preset_table.viewport().update(self.preset_table.visualItemRect(item))
        QTimer.singleShot(2500, lambda: self._clear_preset_cell_highlight(row, column))

    def _clear_preset_cell_highlight(self, row: int, column: int) -> None:
        item = self.preset_table.item(row, column)
        if item is None:
            return

        signals_blocked = self.preset_table.blockSignals(True)
        try:
            item.setData(PRESET_TABLE_ATTENTION_ROLE, None)
        finally:
            self.preset_table.blockSignals(signals_blocked)
        self.preset_table.viewport().update(self.preset_table.visualItemRect(item))

    def set_all_presets_checked(self, checked: bool) -> None:
        self.preset_table_controller.set_all_presets_checked(checked)

    def select_diff_presets(self) -> None:
        input_path = Path(self.input_path.text())
        suffix = input_path.suffix.lower()
        if suffix not in {".hls", ".hlx"}:
            return

        file_kind = "preset" if suffix == ".hlx" else "setlist"
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"Choose previous {file_kind}",
            filter=f"Helix {file_kind} (*{suffix})",
        )
        if not path:
            return

        previous_input_path = Path(path)
        if previous_input_path.suffix.lower() != suffix:
            self.show_error(f"Diff file must use the {suffix} extension")
            return

        try:
            profile = get_device_profile(self.device.currentData())
            handler = profile.create_patch_file_handler(Path(__file__).resolve().parents[3])
            diff_snapshot_ids = getattr(handler, "diff_snapshot_ids", None)
            if diff_snapshot_ids is None:
                diff_snapshots = {
                    preset_id: tuple(range(1, self.snapshot_count + 1))
                    for preset_id in handler.diff_preset_ids(input_path, previous_input_path)
                }
            else:
                diff_snapshots = diff_snapshot_ids(
                    input_path,
                    previous_input_path,
                    self.snapshot_count,
                )
            changed_by_patch = {
                handler.format_patch_id(preset_id): tuple(snapshots)
                for preset_id, snapshots in diff_snapshots.items()
            }
        except Exception as exc:  # noqa: BLE001
            self.show_error(str(exc))
            return

        self._comparison_input_path = previous_input_path
        self._comparison_changed_by_patch = changed_by_patch
        signals_blocked = self.comparison_enabled.blockSignals(True)
        try:
            self.comparison_enabled.setEnabled(True)
            self.comparison_enabled.setChecked(True)
        finally:
            self.comparison_enabled.blockSignals(signals_blocked)
        measurable_snapshots = self._apply_comparison_ignore_plan()

        self._log(
            (
                f"Marked unchanged snapshots from {previous_input_path}; "
                f"{measurable_snapshots} changed snapshot(s) remain measurable"
            ),
            "success",
        )

    def _comparison_enabled_toggled(self, enabled: bool) -> None:
        if enabled:
            if self._comparison_changed_by_patch is None:
                return
            measurable_snapshots = self._apply_comparison_ignore_plan()
            source = f" from {self._comparison_input_path}" if self._comparison_input_path else ""
            self._log(
                (
                    f"Enabled comparison-based snapshot exclusions{source}; "
                    f"{measurable_snapshots} changed snapshot(s) remain measurable"
                ),
                "success",
            )
            return

        self._clear_comparison_ignore_plan()
        self._log("Disabled comparison-based snapshot exclusions", "info")

    def _apply_comparison_ignore_plan(self) -> int:
        changed_by_patch = self._comparison_changed_by_patch or {}
        with self._sorting_paused():
            measurable_snapshots = self.preset_table_controller.set_comparison_ignore_plan(
                changed_by_patch
            )
        self._refresh_measurement_time_estimate()
        return measurable_snapshots

    def _clear_comparison_ignore_plan(self) -> None:
        with self._sorting_paused():
            self.preset_table_controller.clear_comparison_ignore_plan()
        self._refresh_measurement_time_estimate()

    def _reset_comparison_file_selection(self) -> None:
        self._comparison_input_path = None
        self._comparison_changed_by_patch = None
        if not hasattr(self, "comparison_enabled"):
            return
        signals_blocked = self.comparison_enabled.blockSignals(True)
        try:
            self.comparison_enabled.setChecked(False)
            self.comparison_enabled.setEnabled(False)
        finally:
            self.comparison_enabled.blockSignals(signals_blocked)

    def show_preset_table_legend(self) -> None:
        build_preset_table_legend_dialog(
            parent=self,
            ignore_reason_icons=self._ignore_reason_icons,
        ).exec()

    def _manual_adjustments_toggled(self, checked: bool) -> None:
        self.preset_table_controller.manual_adjustments_toggled(checked)

    def _refresh_preset_table_editable_flags(self) -> None:
        self.preset_table_controller.refresh_preset_table_editable_flags()

    def _manual_adjustments_enabled(self) -> bool:
        return self.preset_table_controller.manual_adjustments_enabled()

    def _manual_table_cell_double_clicked(self, row: int, column: int) -> None:
        item = self.preset_table_controller.manual_table_cell_double_click_target(row, column)
        if item is None:
            return

        self._start_manual_cell_edit(row, column, item)

    def _start_manual_cell_edit(self, row: int, column: int, item: QTableWidgetItem) -> None:
        self._finish_manual_cell_edit(commit=True)
        editor = QLineEdit(self.preset_table.viewport())
        max_length = self._manual_name_max_length(column)
        if max_length is not None:
            editor.setMaxLength(max_length)
        editor.setText(item.text())
        editor.selectAll()
        editor.setFrame(False)
        editor.setGeometry(self.preset_table.visualItemRect(item))
        editor.installEventFilter(self)
        editor.returnPressed.connect(lambda: self._finish_manual_cell_edit(commit=True))
        editor.show()
        editor.setFocus(Qt.FocusReason.MouseFocusReason)
        self._manual_cell_editor = editor
        self._manual_cell_target = (row, column)

    def _finish_manual_cell_edit(self, *, commit: bool) -> None:
        editor = self._manual_cell_editor
        target = self._manual_cell_target
        if editor is None or target is None:
            return

        row, column = target
        if not self.preset_table_controller.finish_manual_cell_edit(
            row,
            column,
            editor.text(),
            commit=commit,
        ):
            editor.setFocus(Qt.FocusReason.OtherFocusReason)
            editor.selectAll()
            return

        self._manual_cell_editor = None
        self._manual_cell_target = None
        editor.removeEventFilter(self)
        editor.deleteLater()

    def _manual_name_max_length(self, column: int) -> int | None:
        return self.preset_table_controller.manual_name_max_length(column)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            event.type() == QEvent.Type.ToolTip
            and watched.property("keep_tooltip_visible")
            and isinstance(watched, QWidget)
        ):
            text = watched.toolTip()
            if not text:
                QToolTip.hideText()
                return True
            if isinstance(event, QHelpEvent):
                anchor = event.globalPos() + QPoint(12, 20)
            else:
                anchor = watched.mapToGlobal(watched.rect().bottomLeft())
            screen = QApplication.screenAt(anchor) or QApplication.primaryScreen()
            available = (
                screen.availableGeometry()
                if screen is not None
                else self.screen().availableGeometry()
            )
            position = _visible_tooltip_position(anchor, _tooltip_size_hint(text), available)
            QToolTip.showText(position, text, watched, watched.rect())
            return True
        if watched is self._manual_cell_editor:
            if event.type() == QEvent.Type.KeyPress:
                key = event.key() if isinstance(event, QKeyEvent) else None
                if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
                    self._finish_manual_cell_edit(commit=True)
                    return True
                if key == Qt.Key.Key_Escape:
                    self._finish_manual_cell_edit(commit=False)
                    return True
            if event.type() == QEvent.Type.FocusOut:
                editor = self._manual_cell_editor
                QTimer.singleShot(
                    0,
                    lambda: (
                        self._finish_manual_cell_edit(commit=True)
                        if editor is self._manual_cell_editor
                        else None
                    ),
                )
        return super().eventFilter(watched, event)

    def _table_adjustments(self) -> PatchFileAdjustments:
        return self.preset_table_controller.table_adjustments()

    @staticmethod
    def _validate_helix_name(name: str, max_length: int | None = None) -> str:
        return validate_helix_name(name, max_length)

    def _set_phase(self, phase: str) -> None:
        self.phase.setText(phase_text(phase))
        standard_pixmap = PHASE_ICON.get(phase.lower())
        icon = (
            self.style().standardIcon(standard_pixmap) if standard_pixmap is not None else QIcon()
        )
        self.phase_icon.setPixmap(icon.pixmap(16, 16))

    def _handle_gain_correction_log(self, message: str) -> None:
        sync_patch = gain_preset_sync_patch(message)
        if sync_patch is not None:
            self._apply_deferred_gain_correction_logs(sync_patch)
            return

        parsed = parse_gain_correction_log(message)
        if parsed is None:
            return

        if (
            self._deferred_gain_correction_patch is not None
            and parsed.patch != self._deferred_gain_correction_patch
        ):
            self._apply_deferred_gain_correction_logs(self._deferred_gain_correction_patch)
        self._deferred_gain_correction_logs.append(message)
        self._deferred_gain_correction_patch = parsed.patch

    def _apply_deferred_gain_correction_logs(self, device_patch: str | None = None) -> None:
        remaining: list[str] = []
        remaining_patches: set[str] = set()
        for message in self._deferred_gain_correction_logs:
            match = gain_correction_match(message)
            if (
                device_patch is not None
                and match is not None
                and match.groupdict().get("patch") != device_patch
            ):
                remaining.append(message)
                remaining_patches.add(match["patch"])
                continue
            self._apply_gain_correction(message)
        self._deferred_gain_correction_logs = remaining
        self._deferred_gain_correction_patch = next(iter(remaining_patches), None)

    def _apply_gain_correction(self, message: str) -> None:
        parsed = parse_gain_correction_log(message)
        if parsed is None:
            return
        self.preset_table_controller.apply_gain_correction_event(
            parsed,
            self.preset_snapshot_positions,
            self._custom_adjustment_for_snapshot,
        )

    def _snapshot_position_for_gain_log(self, row: int, patch: str, label: str) -> int:
        return self.preset_table_controller.snapshot_position_for_gain_log(
            row,
            patch,
            label,
            self.preset_snapshot_positions,
        )

    def _apply_snapshot_measurement(self, event: ProgressEvent) -> None:
        if event.device_patch is None or event.snapshot is None or event.lufs is None:
            return

        row = self._preset_row(event.device_patch)
        if row is None:
            return

        selected = self.preset_table.item(row, 0)
        if selected is None or selected.checkState() != Qt.CheckState.Checked:
            return

        snapshot_index = event.snapshot - 1
        if snapshot_index < 0 or snapshot_index >= self.snapshot_count:
            return

        policy = self._normalization_policy()

        name_item = self.preset_table.item(row, snapshot_name_column(snapshot_index))
        is_solo = name_item is not None and self._is_solo_snapshot_name(name_item.text())
        is_ignored = name_item is not None and self._is_ignored_snapshot_name(name_item.text())

        custom_adjustment = self._custom_adjustment_for_snapshot(event.device_patch, snapshot_index)
        display = snapshot_measurement_display(
            event,
            policy=policy,
            target_lufs=self._target_lufs(),
            output_levels=self.preset_table_controller.snapshot_output_levels(
                row,
                snapshot_index,
            ),
            is_solo=is_solo,
            is_ignored=is_ignored,
            custom_adjustment=custom_adjustment,
        )
        if display is None:
            return
        self.preset_table_controller.apply_snapshot_measurement_display(row, display)

    def _apply_snapshot_measurement_failure(self, event: ProgressEvent) -> None:
        if event.device_patch is None or event.snapshot is None:
            return

        row = self._preset_row(event.device_patch)
        if row is None:
            return

        selected = self.preset_table.item(row, 0)
        if selected is None or selected.checkState() != Qt.CheckState.Checked:
            return

        snapshot_index = event.snapshot - 1
        if snapshot_index < 0 or snapshot_index >= self.snapshot_count:
            return

        display = snapshot_measurement_failure_display(event)
        if display is not None:
            self.preset_table_controller.apply_snapshot_measurement_failure(row, display)

    def _set_bad_snapshot_measurement(
        self,
        row: int,
        snapshot_index: int,
        detail: str | None = None,
        *,
        adjustment: float | None = None,
    ) -> None:
        self.preset_table_controller.set_bad_snapshot_measurement(
            row,
            snapshot_index,
            detail,
            adjustment=adjustment,
        )

    def _normalization_policy(self) -> NormalizationPolicy:
        if self.completed_request is not None:
            return self.completed_request.policy
        return NormalizationPolicy(snapshot_count=self.snapshot_count)

    def _custom_adjustment_for_snapshot(
        self,
        patch: str,
        snapshot_index: int,
    ) -> float | None:
        preset_adjustments = self._custom_adjustments.get(patch)
        if preset_adjustments is None and Path(self.input_path.text()).suffix.lower() == ".hlx":
            preset_adjustments = self._custom_adjustments.get(self._single_preset_slot_text())
        if preset_adjustments is None:
            return None
        return preset_adjustments.get(snapshot_index)

    def _configure_snapshot_columns(self, snapshot_count: int) -> None:
        self.snapshot_count = snapshot_count
        self.preset_table_controller.configure_snapshot_columns(snapshot_count)

    def _snapshot_count_changed(self, snapshot_count: int) -> None:
        if hasattr(self, "preset_table"):
            self._configure_snapshot_columns(snapshot_count)
            if (
                hasattr(self, "comparison_enabled")
                and self.comparison_enabled.isChecked()
                and self._comparison_changed_by_patch is not None
            ):
                self._apply_comparison_ignore_plan()

    @contextmanager
    def _sorting_paused(self) -> Iterator[None]:
        with self.preset_table_controller.sorting_paused():
            yield

    def _refresh_all_snapshot_names(self) -> None:
        if not hasattr(self, "preset_table"):
            return
        self.preset_table_controller.refresh_all_snapshot_names()

    def _refresh_all_preset_names(self) -> None:
        if not hasattr(self, "preset_table"):
            return
        self.preset_table_controller.refresh_all_preset_names()

    def _refresh_snapshot_name_cell_widget(self, item: QTableWidgetItem) -> None:
        refresh_snapshot_name_cell_widget(
            item,
            ignore_reason_icons=self._ignore_reason_icons,
            speaker_icon=self._speaker_icon,
            normalization_in_progress=self._normalization_in_progress,
            play_recording=self._play_recording,
        )

    def _preset_name_max_length(self) -> int | None:
        return self._current_profile_name_max_length("preset_name_max_length")

    def _snapshot_name_max_length(self) -> int | None:
        return self._current_profile_name_max_length("snapshot_name_max_length")

    def _current_profile_name_max_length(self, attribute: str) -> int | None:
        device = self.device.currentData() if hasattr(self, "device") else None
        return device_name_max_length(device, attribute)

    @staticmethod
    def _sanitize_helix_name(name: str, max_length: int | None = None) -> str:
        return sanitize_helix_name(name, max_length)

    def _preset_row(self, patch: str) -> int | None:
        for row in range(self.preset_table.rowCount()):
            item = self.preset_table.item(row, 1)
            if item is not None and item.text() == patch:
                return row
        if (
            Path(self.input_path.text()).suffix.lower() == ".hlx"
            and self.preset_table.rowCount() == 1
        ):
            return 0
        return None

    def _log(self, message: str, level: str) -> None:
        self.log_controller.append(message, level)

    def _refresh_log(self) -> None:
        self.log_controller.refresh()

    def _resize_to_initial_content(self) -> None:
        if self.isMaximized() or self.isFullScreen():
            return
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        viewport = self.scroll_area.viewport()
        chrome_width = self.width() - viewport.width()
        chrome_height = self.height() - viewport.height()
        hint = self.content.sizeHint()
        height = hint.height() + chrome_height + 4
        self.resize(
            min(max(820, hint.width() + chrome_width + 4), available.width()),
            min(height, available.height()),
        )

    def _resize_to_initial_content_once(self) -> None:
        if self._startup_resize_done:
            return
        self._startup_resize_done = True
        self._resize_to_initial_content()

    def _schedule_resize_for_content(self) -> None:
        for widget in (
            self.presets,
            self.advanced_tabs,
            self.advanced,
            self.preset_advanced_splitter,
            self.content,
        ):
            layout = widget.layout()
            if layout is not None:
                layout.invalidate()
            widget.updateGeometry()
        for _ in range(3):
            QCoreApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)

    def _preset_table_size_changed(self) -> None:
        self.preset_table.updateGeometry()
        self.presets.updateGeometry()
        self._schedule_resize_for_content()

    def _start_busy_phase(self) -> None:
        if self.busy_animation.state() != QAbstractAnimation.State.Running:
            self._set_processing_dot(True)
            self.busy_animation.start()

    def _stop_busy_phase(self, color: str = PROCESSING_DOT_GREY) -> None:
        self.busy_animation.stop()
        self.processing_dot_effect.setOpacity(1.0)
        self._set_processing_dot(color == PROCESSING_DOT_GREEN, color)
        self._hide_progress()

    def _set_processing_dot(self, green: bool, color: str | None = None) -> None:
        self._processing_dot_green = green
        color = color or (PROCESSING_DOT_GREEN if green else PROCESSING_DOT_GREY)
        self._processing_dot_color = color
        self.processing_dot.setStyleSheet(f"background-color: {color}; border-radius: 7px;")

    def _reset_loudness_bars(self) -> None:
        target_lufs = self._target_lufs()
        self.current.clear()
        self.measured_loudness.reset_loudness(target_lufs)
        waiting_text = f"Waiting for signal (target {target_lufs:.1f} LUFS)"
        self.measured_loudness_reading.setText(waiting_text)

    def _target_lufs(self) -> float:
        try:
            return float(self.target_lufs.text())
        except (AttributeError, ValueError):
            return -16.0

    def _preset_progress_text(self, event: ProgressEvent) -> str:
        row = self._preset_row(event.device_patch or "")
        if row is None:
            return f"Preset {event.device_patch}"
        name = self.preset_table.item(row, 2)
        if name and name.text():
            return f"Preset {event.device_patch}: {name.text()}"
        return f"Preset {event.device_patch}"

    def _snapshot_progress_text(self, event: ProgressEvent) -> str:
        text = f", snapshot {event.snapshot}/{event.snapshot_total}"
        row = self._preset_row(event.device_patch or "")
        if row is None or event.snapshot is None:
            return text
        name = self.preset_table.item(row, snapshot_name_column(event.snapshot - 1))
        return f"{text}: {name.text()}" if name and name.text() else text

    def _preset_table_has_unsaved_changes(self) -> bool:
        return self.preset_table_controller.preset_table_has_unsaved_changes()

    def _mark_preset_table_modified(self) -> None:
        self.preset_table_controller.mark_preset_table_modified()
        self._preset_table_modified = self.preset_table_controller.modified

    def _reset_preset_table_modified(self) -> None:
        self.preset_table_controller.reset_preset_table_modified()
        self._preset_table_clean_signature = self.preset_table_controller.clean_signature
        self._preset_table_modified = self.preset_table_controller.modified

    def _preset_table_content_signature(self) -> tuple[tuple[str, ...], ...]:
        return self.preset_table_controller.preset_table_content_signature()
