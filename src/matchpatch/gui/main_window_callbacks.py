"""Callback adapters used by the main GUI window."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from PySide6.QtWidgets import QTableWidgetItem

from matchpatch.devices.base import PatchFileAdjustments, normalize_regex_pattern
from matchpatch.gui.name_rules import (
    sanitize_preset_name_for_device,
    sanitize_subdivision_name_for_device,
    validate_preset_name_for_device,
    validate_subdivision_name_for_device,
)
from matchpatch.gui.preset_table import (
    PresetTableCallbacks,
    refresh_adjustment_cell_widget,
    refresh_preset_cell_widget_background,
    refresh_preset_item_background,
    refresh_snapshot_name_cell_widget,
)
from matchpatch.gui.preset_table_csv import preset_table_csv_row
from matchpatch.gui.save_workflow import SaveCallbacks, create_table_save_csv
from matchpatch.progress import ProgressEvent


class MainWindowSaveCallbacks(SaveCallbacks):
    def __init__(
        self,
        window: object,
        *,
        confirm_overwrite: Callable[[Path], bool] | None = None,
    ) -> None:
        self._window: Any = window
        self._confirm_overwrite = confirm_overwrite

    def confirm_overwrite(self, output_path: Path) -> bool:
        if self._confirm_overwrite is not None:
            return self._confirm_overwrite(output_path)
        return self._window._confirm_overwrite(output_path)

    def create_table_save_csv(self, directory: Path) -> Path:
        return create_table_save_csv(
            directory,
            snapshot_count=self._window.snapshot_count,
            patches=self._window.preset_table_controller.preset_patches(),
            target_lufs=self._window.target_lufs.text(),
        )

    def table_adjustments(self) -> PatchFileAdjustments:
        return self._window._table_adjustments()

    def update_progress(self, event: ProgressEvent) -> None:
        self._window.update_progress(event)


class MainWindowPresetTableCallbacks(PresetTableCallbacks):
    def __init__(self, window: object) -> None:
        self._window: Any = window

    def snapshot_count_for_estimate(self) -> int:
        return self._window._snapshot_count_for_estimate()

    def snapshot_count(self) -> int:
        return self._window.snapshot_count

    def input_path_text(self) -> str:
        return self._window.input_path.text()

    def validate_helix_name(self, name: str, max_length: int | None = None) -> str:
        return self._window._validate_helix_name(name, max_length)

    def validate_preset_name(self, name: str) -> str:
        return validate_preset_name_for_device(self._window.device.currentData(), name)

    def validate_subdivision_name(self, name: str) -> str:
        return validate_subdivision_name_for_device(self._window.device.currentData(), name)

    def sanitize_preset_name(self, name: str) -> str:
        return sanitize_preset_name_for_device(self._window.device.currentData(), name)

    def sanitize_subdivision_name(self, name: str) -> str:
        return sanitize_subdivision_name_for_device(self._window.device.currentData(), name)

    def preset_name_max_length(self) -> int | None:
        return self._window._preset_name_max_length()

    def snapshot_name_max_length(self) -> int | None:
        return self._window._snapshot_name_max_length()

    def preset_table_csv_row(self, row: int) -> list[str]:
        return preset_table_csv_row(
            self._window.preset_table,
            row,
            self._window.snapshot_count,
        )

    def preset_table_clean_signature(self) -> tuple[tuple[str, ...], ...]:
        return self._window._preset_table_clean_signature

    def preset_row(self, patch: str) -> int | None:
        return self._window._preset_row(patch)

    def refresh_preset_measurement_time_estimate(self) -> None:
        self._window._refresh_preset_measurement_time_estimate()

    def refresh_file_actions(self) -> None:
        self._window._refresh_file_actions()

    def preset_table_modified_changed(self, modified: bool) -> None:
        self._window._preset_table_modified = modified

    def clear_manual_name_modified_highlights(self) -> None:
        self._window.preset_table_controller.clear_manual_name_modified_highlights()

    def manual_adjustments_checked(self) -> bool:
        return (
            hasattr(self._window, "manual_adjustments")
            and self._window.manual_adjustments.isChecked()
        )

    def set_preset_ignore_reason(self, row: int, active: bool) -> None:
        self._window.preset_table_controller.set_preset_ignore_reason(row, active)

    def clear_preset_adjustments(self, row: int) -> None:
        self._window.preset_table_controller.clear_preset_adjustments(row)

    def refresh_adjustment_cell_widget(self, item: QTableWidgetItem) -> None:
        refresh_adjustment_cell_widget(item)

    def refresh_snapshot_name_cell_widget(self, item: QTableWidgetItem) -> None:
        refresh_snapshot_name_cell_widget(
            item,
            ignore_reason_icons=self._window._ignore_reason_icons,
            speaker_icon=self._window._speaker_icon,
            normalization_in_progress=self._window._normalization_in_progress,
            play_recording=self._window._play_recording,
        )

    def set_snapshot_ignore_reason(
        self,
        row: int,
        snapshot_index: int,
        reason: str,
        active: bool,
    ) -> None:
        self._window.preset_table_controller.set_snapshot_ignore_reason(
            row, snapshot_index, reason, active
        )

    def is_solo_snapshot_name(self, name: str) -> bool:
        try:
            solo_pattern = re.compile(normalize_regex_pattern(self._window.solo_regex.text()))
        except re.error:
            return False
        return solo_pattern.search(name) is not None

    def is_ignored_snapshot_name(self, name: str) -> bool:
        try:
            ignore_pattern = re.compile(
                normalize_regex_pattern(self._window.ignore_snapshot_regex.text())
            )
        except re.error:
            return False
        return ignore_pattern.search(name) is not None

    def is_ignored_preset_name(self, name: str) -> bool:
        try:
            pattern = re.compile(normalize_regex_pattern(self._window.ignore_preset_regex.text()))
        except re.error:
            return False
        return bool(pattern.pattern) and pattern.search(name) is not None

    def refresh_measurement_time_estimate(self) -> None:
        self._window._refresh_measurement_time_estimate()

    def refresh_preset_item_background(self, item: QTableWidgetItem) -> None:
        refresh_preset_item_background(item)

    def refresh_preset_cell_widget_background(self, item: QTableWidgetItem) -> None:
        refresh_preset_cell_widget_background(item)

    def show_error(self, message: str) -> None:
        self._window.show_error(message)
