"""Preset table widget primitives and column helpers."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QItemSelectionModel, QModelIndex, QPersistentModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QFontMetrics, QIcon, QPainter, QPaintEvent, QPalette, QPen
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QWidget,
)

from matchpatch.devices.base import PatchFileAdjustments
from matchpatch.gui.results import (
    GainCorrectionEvent,
    ManualAdjustmentSnapshot,
    SnapshotMeasurementDisplay,
)
from matchpatch.gui.table_formatting import (
    _bad_lufs_adjustment,
    _bad_lufs_adjustment_display,
    _custom_adjustment_label_text,
    _format_adjustment,
    _format_snapshot_output_levels,
    _normalize_snapshot_output_levels,
    _normalize_snapshot_output_paths,
    _parse_adjustment_display_text,
    _parse_output_level_display_text,
    sanitize_helix_name,
)
from matchpatch.gui.table_roles import (
    ADJUSTMENT_MAX_DB,
    ADJUSTMENT_MIN_DB,
    ADJUSTMENT_VALUE_ROLE,
    BAD_LUFS_HIGHLIGHT_ROLE,
    IGNORE_REASON_COMPARISON,
    IGNORE_REASON_LABELS,
    IGNORE_REASON_PRESET,
    IGNORE_REASON_REGEX,
    IGNORED_SNAPSHOT_REASONS_ROLE,
    IGNORED_SNAPSHOT_ROLE,
    MANUAL_NAME_MODIFIED_ROLE,
    MEASURED_ADJUSTMENT_ROLE,
    NORMALIZATION_FOCUS_ROLE,
    OUTPUT_LEVEL_MAX_DB,
    OUTPUT_LEVEL_MIN_DB,
    PRESET_TABLE_ATTENTION_ROLE,
    PROCESSED_SNAPSHOT_ROLE,
    RECORDED_OUTPUT_PATH_ROLE,
    SNAPSHOT_OUTPUT_LEVELS_ROLE,
    SNAPSHOT_OUTPUT_PATHS_ROLE,
    SNAPSHOT_TABLE_COLUMN_STRIDE,
    SNAPSHOT_TABLE_START_COLUMN,
    SOLO_SNAPSHOT_ROLE,
    _snapshot_ignore_reasons,
    _snapshot_tooltip,
)

NORMALIZATION_FOCUS_BLUE = QColor("#2563eb")
BAD_LUFS_ROW_BACKGROUND = QColor("#fee2e2")
BAD_LUFS_FOREGROUND = QColor("#b91c1c")
NORMALIZATION_FOCUS_BACKGROUND = QColor("#dbeafe")
PROCESSED_SNAPSHOT_BACKGROUND = QColor("#dcfce7")
MANUAL_NAME_MODIFIED_BACKGROUND = QColor("#fef3c7")
IGNORED_SNAPSHOT_BACKGROUND = QColor("#e5e7eb")
IGNORED_SNAPSHOT_FOREGROUND = QColor("#4b5563")


@dataclass(frozen=True)
class _PresetSelectionState:
    checked_patches: frozenset[str]
    selected_patches: frozenset[str]
    current_patch: str | None


class PresetTableCallbacks(Protocol):
    def snapshot_count(self) -> int: ...

    def snapshot_count_for_estimate(self) -> int: ...

    def input_path_text(self) -> str: ...

    def validate_helix_name(self, name: str, max_length: int | None = None) -> str: ...

    def preset_name_max_length(self) -> int | None: ...

    def snapshot_name_max_length(self) -> int | None: ...

    def preset_table_csv_row(self, row: int) -> list[str]: ...

    def preset_table_clean_signature(self) -> tuple[tuple[str, ...], ...]: ...

    def preset_row(self, patch: str) -> int | None: ...

    def refresh_preset_measurement_time_estimate(self) -> None: ...

    def refresh_file_actions(self) -> None: ...

    def preset_table_modified_changed(self, modified: bool) -> None: ...

    def clear_manual_name_modified_highlights(self) -> None: ...

    def manual_adjustments_checked(self) -> bool: ...

    def set_preset_ignore_reason(self, row: int, active: bool) -> None: ...

    def clear_preset_adjustments(self, row: int) -> None: ...

    def refresh_adjustment_cell_widget(self, item: QTableWidgetItem) -> None: ...

    def refresh_snapshot_name_cell_widget(self, item: QTableWidgetItem) -> None: ...

    def set_snapshot_ignore_reason(
        self,
        row: int,
        snapshot_index: int,
        reason: str,
        active: bool,
    ) -> None: ...

    def is_solo_snapshot_name(self, name: str) -> bool: ...

    def is_ignored_snapshot_name(self, name: str) -> bool: ...

    def refresh_measurement_time_estimate(self) -> None: ...

    def refresh_preset_item_background(self, item: QTableWidgetItem) -> None: ...

    def refresh_preset_cell_widget_background(self, item: QTableWidgetItem) -> None: ...

    def show_error(self, message: str) -> None: ...


@dataclass
class PresetTableController:
    """Stateful controller for the existing preset table widget."""

    table: QTableWidget
    callbacks: PresetTableCallbacks
    adjusted_presets: set[str]
    modified: bool = False
    clean_signature: tuple[tuple[str, ...], ...] = ()

    def row_measured_snapshot_indexes(self, row: int) -> tuple[int, ...]:
        indexes = []
        for snapshot_index in range(self.callbacks.snapshot_count_for_estimate()):
            item = self.table.item(row, snapshot_name_column(snapshot_index))
            if item is None or not item.data(IGNORED_SNAPSHOT_ROLE):
                indexes.append(snapshot_index + 1)
        return tuple(indexes)

    def row_measured_snapshot_count(self, row: int) -> int:
        return len(self.row_measured_snapshot_indexes(row))

    def row_has_measured_snapshots(self, row: int) -> bool:
        return self.row_measured_snapshot_count(row) > 0

    def has_ignored_snapshot_cells(self) -> bool:
        for row in range(self.table.rowCount()):
            for snapshot_index in range(self.callbacks.snapshot_count_for_estimate()):
                item = self.table.item(row, snapshot_name_column(snapshot_index))
                if item is not None and item.data(IGNORED_SNAPSHOT_ROLE):
                    return True
        return False

    def checked_preset_rows(self) -> list[int]:
        rows = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                rows.append(row)
        return rows

    def selected_measurable_preset_rows(self) -> list[int]:
        if Path(self.callbacks.input_path_text()).suffix.lower() == ".hlx":
            candidate_rows = [0] if self.table.rowCount() else []
        else:
            checked_rows = self.checked_preset_rows()
            candidate_rows = checked_rows or list(range(self.table.rowCount()))
        return [row for row in candidate_rows if self.row_has_measured_snapshots(row)]

    def has_optimization_preset_selection(self) -> bool:
        if self.table.rowCount() == 0:
            return False
        if Path(self.callbacks.input_path_text()).suffix.lower() == ".hlx":
            return self.row_has_measured_snapshots(0)
        return any(self.row_has_measured_snapshots(row) for row in self.checked_preset_rows())

    def preset_selection_state(self) -> _PresetSelectionState:
        checked_patches: set[str] = set()
        for row in range(self.table.rowCount()):
            selected_item = self.table.item(row, 0)
            patch_item = self.table.item(row, 1)
            if (
                selected_item is not None
                and patch_item is not None
                and selected_item.checkState() == Qt.CheckState.Checked
            ):
                checked_patches.add(patch_item.text())

        selected_patches = set()
        for index in self.table.selectionModel().selectedIndexes():
            patch_item = self.table.item(index.row(), 1)
            if patch_item is not None:
                selected_patches.add(patch_item.text())
        current_patch = None
        current_row = self.table.currentRow()
        if current_row >= 0:
            current_item = self.table.item(current_row, 1)
            if current_item is not None:
                current_patch = current_item.text()
        return _PresetSelectionState(
            checked_patches=frozenset(checked_patches),
            selected_patches=frozenset(selected_patches),
            current_patch=current_patch,
        )

    def restore_preset_selection_state(self, state: _PresetSelectionState) -> None:
        signals_blocked = self.table.blockSignals(True)
        try:
            for row in range(self.table.rowCount()):
                selected_item = self.table.item(row, 0)
                patch_item = self.table.item(row, 1)
                if selected_item is None or patch_item is None:
                    continue
                selected_item.setCheckState(
                    Qt.CheckState.Checked
                    if patch_item.text() in state.checked_patches
                    else Qt.CheckState.Unchecked
                )
        finally:
            self.table.blockSignals(signals_blocked)

        selection_model = self.table.selectionModel()
        selection_model.clearSelection()
        for patch in state.selected_patches:
            row = self.callbacks.preset_row(patch)
            if row is None:
                continue
            selection_model.select(
                self.table.model().index(row, 0),
                QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
            )
        if state.current_patch is not None:
            current_row = self.callbacks.preset_row(state.current_patch)
            if current_row is not None:
                selection_model.setCurrentIndex(
                    self.table.model().index(current_row, 0),
                    QItemSelectionModel.SelectionFlag.NoUpdate,
                )
        self.callbacks.refresh_preset_measurement_time_estimate()

    def set_all_presets_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        with self.sorting_paused():
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 0)
                if item is not None:
                    item.setCheckState(state)

    def preset_table_has_unsaved_changes(self) -> bool:
        return self.modified or bool(self.adjusted_presets)

    def mark_preset_table_modified(self) -> None:
        self.modified = True
        self.callbacks.preset_table_modified_changed(self.modified)
        self.callbacks.refresh_file_actions()

    def reset_preset_table_modified(self) -> None:
        self.clean_signature = self.preset_table_content_signature()
        self.modified = False
        self.adjusted_presets.clear()
        self.callbacks.clear_manual_name_modified_highlights()
        self.callbacks.preset_table_modified_changed(self.modified)
        self.callbacks.refresh_file_actions()

    def preset_table_content_signature(self) -> tuple[tuple[str, ...], ...]:
        return tuple(
            tuple(self.callbacks.preset_table_csv_row(row)) for row in range(self.table.rowCount())
        )

    def table_adjustments(self) -> PatchFileAdjustments:
        preset_names = {}
        snapshot_names = {}
        gain_deltas = {}

        for row in range(self.table.rowCount()):
            patch_item = self.table.item(row, 1)
            preset_item = self.table.item(row, 2)
            if patch_item is None or preset_item is None:
                continue

            patch = patch_item.text()
            preset_names[patch] = self.callbacks.validate_helix_name(
                preset_item.text(),
                self.callbacks.preset_name_max_length(),
            )
            patch_snapshot_names = {}
            patch_gain_deltas = {}
            for snapshot_index in range(self.callbacks.snapshot_count()):
                name_item = self.table.item(row, snapshot_name_column(snapshot_index))
                adjustment_item = self.table.item(row, snapshot_adjustment_column(snapshot_index))
                if name_item is not None:
                    patch_snapshot_names[snapshot_index] = self.callbacks.validate_helix_name(
                        name_item.text(),
                        self.callbacks.snapshot_name_max_length(),
                    )
                if adjustment_item is not None:
                    if adjustment_item.data(IGNORED_SNAPSHOT_ROLE):
                        continue
                    if adjustment_item.data(BAD_LUFS_HIGHLIGHT_ROLE):
                        continue
                    stored_value = adjustment_item.data(ADJUSTMENT_VALUE_ROLE)
                    if isinstance(stored_value, (int, float)) and not isinstance(
                        stored_value, bool
                    ):
                        value = float(stored_value)
                    else:
                        try:
                            value = _parse_adjustment_display_text(adjustment_item.text())
                        except ValueError as exc:
                            raise ValueError(
                                f"Invalid gain adjustment: {adjustment_item.text()!r}"
                            ) from exc
                    if not math.isfinite(value):
                        raise ValueError(f"Invalid gain adjustment: {adjustment_item.text()!r}")
                    patch_gain_deltas[snapshot_index] = value
            snapshot_names[patch] = patch_snapshot_names
            gain_deltas[patch] = patch_gain_deltas

        return PatchFileAdjustments(preset_names, snapshot_names, gain_deltas)

    def preset_patches(self) -> list[str]:
        patches: list[str] = []
        for row in range(self.table.rowCount()):
            patch_item = self.table.item(row, 1)
            if patch_item is not None:
                patches.append(patch_item.text())
        return patches

    def configure_snapshot_columns(self, snapshot_count: int) -> None:
        labels = ["", "Preset", "Name"]
        for snapshot in range(1, snapshot_count + 1):
            labels.extend([str(snapshot), "Out (dB)", "Δ (dB)"])
        with self.sorting_paused():
            self.table.setColumnCount(len(labels))
            self.table.setHorizontalHeaderLabels(labels)
            header = self.table.horizontalHeader()
            header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            header.setStretchLastSection(False)
            checkbox_width = self.table.style().pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth)
            checkbox_spacing = self.table.style().pixelMetric(
                QStyle.PixelMetric.PM_CheckBoxLabelSpacing
            )
            selection_width = checkbox_width + checkbox_spacing * 2
            header.setMinimumSectionSize(selection_width)
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(0, selection_width)
            self.table.setColumnWidth(1, 52)
            self.table.setColumnWidth(2, 120)
            output_width = output_level_column_width(self.table)
            adjustment_width = adjustment_column_width(self.table)
            for snapshot_index in range(snapshot_count):
                self.table.setColumnWidth(snapshot_name_column(snapshot_index), 100)
                self.table.setColumnWidth(
                    snapshot_output_column(snapshot_index),
                    output_width,
                )
                self.table.setColumnWidth(
                    snapshot_adjustment_column(snapshot_index),
                    adjustment_width,
                )
            for column, tooltip in enumerate(
                [
                    "Include this preset in normalization.",
                    "Processor slot containing the preset.",
                    "Preset name read from the input file.",
                    *(
                        tooltip
                        for snapshot in range(1, snapshot_count + 1)
                        for tooltip in (
                            f"Name of snapshot {snapshot} read from the input file.",
                            f"Current output block level for snapshot {snapshot}.",
                            f"Calculated gain adjustment for snapshot {snapshot}.",
                        )
                    ),
                ]
            ):
                item = self.table.horizontalHeaderItem(column)
                if item is not None:
                    item.setToolTip(tooltip)
            for row in range(self.table.rowCount()):
                self.clear_preset_adjustments(row)
                self.refresh_snapshot_names(row)
                self.refresh_snapshot_output_levels(row)

    def manual_adjustments_toggled(self, checked: bool) -> None:
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.refresh_preset_table_editable_flags()

    def refresh_preset_table_editable_flags(self) -> None:
        single_preset = Path(self.callbacks.input_path_text()).suffix.lower() == ".hlx"
        for row in range(self.table.rowCount()):
            for column in range(self.table.columnCount()):
                item = self.table.item(row, column)
                if item is not None:
                    self.set_preset_item_editable(item, single_preset and column == 1)

    def manual_adjustments_enabled(self) -> bool:
        return self.callbacks.manual_adjustments_checked()

    def manual_adjustment_snapshots(self) -> list[ManualAdjustmentSnapshot]:
        snapshots: list[ManualAdjustmentSnapshot] = []
        for row in range(self.table.rowCount()):
            patch_item = self.table.item(row, 1)
            preset_item = self.table.item(row, 2)
            patch = patch_item.text().strip() if patch_item is not None else ""
            preset = preset_item.text().strip() if preset_item is not None else ""
            for snapshot_index in range(self.callbacks.snapshot_count()):
                adjustment_item = self.table.item(
                    row,
                    snapshot_adjustment_column(snapshot_index),
                )
                if adjustment_item is None or not adjustment_item.data(BAD_LUFS_HIGHLIGHT_ROLE):
                    continue
                name_item = self.table.item(
                    row,
                    snapshot_name_column(snapshot_index),
                )
                snapshot_name = name_item.text().strip() if name_item is not None else ""
                snapshots.append(
                    ManualAdjustmentSnapshot(
                        patch=patch,
                        preset=preset,
                        snapshot_index=snapshot_index,
                        snapshot_name=snapshot_name,
                    )
                )
        return snapshots

    def snapshot_position_for_gain_log(
        self,
        row: int,
        patch: str,
        label: str,
        snapshot_positions: Mapping[str, int],
    ) -> int:
        cursor = snapshot_positions.get(patch, 0)
        candidates = []
        for snapshot_index in range(self.callbacks.snapshot_count()):
            item = self.table.item(row, snapshot_name_column(snapshot_index))
            if item is not None and item.text() == label:
                candidates.append(snapshot_index)

        if len(candidates) == 1:
            return candidates[0]

        remaining_candidates = [candidate for candidate in candidates if candidate >= cursor]
        if len(remaining_candidates) == 1:
            return remaining_candidates[0]

        return cursor

    def apply_gain_correction_event(
        self,
        event: GainCorrectionEvent,
        snapshot_positions: dict[str, int],
        custom_adjustment_for_snapshot: Callable[[str, int], float | None],
    ) -> bool:
        row = self.callbacks.preset_row(event.patch)
        if row is None:
            return False

        selected = self.table.item(row, 0)
        if selected is None or selected.checkState() != Qt.CheckState.Checked:
            self.clear_preset_adjustments(row)
            return False

        label = event.snapshot_label
        snapshot_position = self.snapshot_position_for_gain_log(
            row,
            event.patch,
            label,
            snapshot_positions,
        )
        if snapshot_position >= self.callbacks.snapshot_count():
            return False
        name_item = self.table.item(row, snapshot_name_column(snapshot_position))
        output_item = self.table.item(row, snapshot_output_column(snapshot_position))
        adjustment_item = self.table.item(row, snapshot_adjustment_column(snapshot_position))
        if name_item is None or output_item is None or adjustment_item is None:
            return False

        if not name_item.text():
            self.set_snapshot_name(
                name_item,
                label,
                event.is_solo,
                self.callbacks.is_ignored_snapshot_name(label),
            )
        if name_item.data(IGNORED_SNAPSHOT_ROLE) or self.callbacks.is_ignored_snapshot_name(
            name_item.text() or label
        ):
            self.set_ignored_snapshot_highlight(row, snapshot_position, True)
            snapshot_positions[event.patch] = max(
                snapshot_positions.get(event.patch, 0),
                snapshot_position + 1,
            )
            return False

        if event.kind == "bad_lufs":
            adjustment = self._bad_lufs_adjustment_value(
                row,
                adjustment_item,
                output_item,
                event.detail,
            )
            self.set_bad_snapshot_measurement(
                row,
                snapshot_position,
                event.detail,
                adjustment=adjustment,
                append_detail=False,
            )
            self.adjusted_presets.add(event.patch)
            snapshot_positions[event.patch] = max(
                snapshot_positions.get(event.patch, 0),
                snapshot_position + 1,
            )
            return True

        output_level = event.before_db if event.before_db is not None else event.after_db
        if output_level is not None:
            self.set_output_level(output_item, output_level)

        actual_adjustment = event.delta_db
        if actual_adjustment is None:
            return False
        custom_adjustment = custom_adjustment_for_snapshot(event.patch, snapshot_position)
        display_adjustment = (
            actual_adjustment - custom_adjustment
            if custom_adjustment is not None
            else actual_adjustment
        )
        self.set_adjustment_value(
            adjustment_item,
            event.delta_text or _format_adjustment(display_adjustment),
            actual_adjustment,
            custom_adjustment,
            display_adjustment if custom_adjustment is not None else None,
        )
        self.callbacks.refresh_adjustment_cell_widget(adjustment_item)
        self.adjusted_presets.add(event.patch)
        snapshot_positions[event.patch] = max(
            snapshot_positions.get(event.patch, 0),
            snapshot_position + 1,
        )
        return True

    def _bad_lufs_adjustment_value(
        self,
        row: int,
        adjustment_item: QTableWidgetItem,
        output_item: QTableWidgetItem,
        detail: str | None,
    ) -> float | None:
        adjustment = None
        if adjustment_item.data(BAD_LUFS_HIGHLIGHT_ROLE):
            stored_adjustment = adjustment_item.data(MEASURED_ADJUSTMENT_ROLE)
            adjustment = (
                stored_adjustment
                if isinstance(stored_adjustment, (int, float))
                and not isinstance(stored_adjustment, bool)
                else None
            )
        if adjustment is None:
            preset_item = self.table.item(row, 2)
            output_paths = (
                preset_item.data(SNAPSHOT_OUTPUT_PATHS_ROLE) if preset_item is not None else ()
            )
            output_paths = output_paths if isinstance(output_paths, tuple) else ()
            adjustment = _bad_lufs_adjustment(detail, output_item.text(), output_paths)
        if adjustment is None and adjustment_item.data(BAD_LUFS_HIGHLIGHT_ROLE):
            try:
                adjustment = _parse_adjustment_display_text(adjustment_item.text())
            except ValueError:
                adjustment = None
        return adjustment

    def snapshot_output_levels(self, row: int, snapshot_index: int) -> tuple[float, ...]:
        output_item = self.table.item(row, snapshot_output_column(snapshot_index))
        return (
            _parse_output_level_display_text(output_item.text()) if output_item is not None else ()
        )

    def apply_snapshot_measurement_display(
        self,
        row: int,
        display: SnapshotMeasurementDisplay,
    ) -> bool:
        if display.snapshot_index < 0 or display.snapshot_index >= self.callbacks.snapshot_count():
            return False
        adjustment_item = self.table.item(
            row,
            snapshot_adjustment_column(display.snapshot_index),
        )
        if adjustment_item is None:
            return False
        if adjustment_item.data(IGNORED_SNAPSHOT_ROLE) or display.status == "ignored":
            self.set_adjustment_ignored(adjustment_item)
            if display.status == "ignored":
                self.set_ignored_snapshot_highlight(row, display.snapshot_index, True)
            return False
        if display.status == "implausible":
            self.set_bad_snapshot_measurement(
                row,
                display.snapshot_index,
                display.tooltip,
                adjustment=display.display_adjustment,
            )
            self.adjusted_presets.add(display.patch)
            return True
        if display.status != "measured":
            return False

        self.set_adjustment_value(
            adjustment_item,
            _format_adjustment(display.display_adjustment or 0.0),
            display.adjustment_value or 0.0,
            display.custom_adjustment,
            display.display_adjustment if display.custom_adjustment is not None else None,
        )
        self.callbacks.refresh_adjustment_cell_widget(adjustment_item)
        self.set_processed_snapshot_highlight(row, display.snapshot_index, True)
        self.adjusted_presets.add(display.patch)
        return True

    def apply_snapshot_measurement_failure(
        self,
        row: int,
        display: SnapshotMeasurementDisplay,
    ) -> bool:
        if display.snapshot_index < 0 or display.snapshot_index >= self.callbacks.snapshot_count():
            return False
        adjustment_item = self.table.item(
            row,
            snapshot_adjustment_column(display.snapshot_index),
        )
        if adjustment_item is not None and adjustment_item.data(IGNORED_SNAPSHOT_ROLE):
            self.set_adjustment_ignored(adjustment_item)
            return False
        self.set_bad_snapshot_measurement(row, display.snapshot_index, display.tooltip)
        self.adjusted_presets.add(display.patch)
        return True

    def manual_table_cell_double_click_target(
        self,
        row: int,
        column: int,
    ) -> QTableWidgetItem | None:
        single_preset_slot = (
            Path(self.callbacks.input_path_text()).suffix.lower() == ".hlx" and column == 1
        )
        if not single_preset_slot and (
            not self.manual_adjustments_enabled() or not is_manual_adjustment_column(column)
        ):
            return None
        return self.table.item(row, column)

    def manual_name_max_length(self, column: int) -> int | None:
        if column == 2:
            return self.callbacks.preset_name_max_length()
        if is_snapshot_name_column(column):
            return self.callbacks.snapshot_name_max_length()
        return None

    @staticmethod
    def set_preset_item_editable(item: QTableWidgetItem, editable: bool) -> None:
        set_preset_item_editable(item, editable)

    def finish_manual_cell_edit(
        self,
        row: int,
        column: int,
        value: str,
        *,
        commit: bool,
    ) -> bool:
        item = self.table.item(row, column)
        if not commit or item is None:
            return True

        before = item.text()
        if column == 1 and Path(self.callbacks.input_path_text()).suffix.lower() == ".hlx":
            item.setText(value.strip().upper())
        elif column == 2:
            item.setText(sanitize_helix_name(value, self.callbacks.preset_name_max_length()))
        elif is_snapshot_name_column(column):
            item.setText(sanitize_helix_name(value, self.callbacks.snapshot_name_max_length()))
        elif is_snapshot_adjustment_column(column):
            try:
                delta = float(value)
            except ValueError:
                self.callbacks.show_error(f"Invalid gain adjustment: {value!r}")
                return False
            if not math.isfinite(delta):
                self.callbacks.show_error(f"Invalid gain adjustment: {value!r}")
                return False
            self.set_adjustment_value(item, value, delta)
        if is_name_column(column) and item.text() != before:
            self.set_manual_name_modified(item, True)
        return True

    def preset_item_changed(self, item: QTableWidgetItem) -> None:
        if item.data(PRESET_TABLE_ATTENTION_ROLE):
            item.setData(PRESET_TABLE_ATTENTION_ROLE, None)
            self.table.viewport().update(self.table.visualItemRect(item))
        if item.column() == 0:
            self.callbacks.set_preset_ignore_reason(
                item.row(),
                item.checkState() != Qt.CheckState.Checked,
            )
            self.callbacks.refresh_preset_measurement_time_estimate()
            self.callbacks.refresh_file_actions()
        if Path(self.callbacks.input_path_text()).suffix.lower() == ".hlx" and item.column() == 1:
            normalized = item.text().strip().upper()
            if normalized != item.text():
                signals_blocked = self.table.blockSignals(True)
                try:
                    item.setText(normalized)
                finally:
                    self.table.blockSignals(signals_blocked)
            return

        if item.column() == 0 and item.checkState() != Qt.CheckState.Checked:
            self.callbacks.clear_preset_adjustments(item.row())
        elif self.manual_adjustments_enabled() and is_manual_adjustment_column(item.column()):
            if item.column() == 2:
                self._sanitize_item_text(item, self.callbacks.preset_name_max_length())
            elif is_snapshot_name_column(item.column()):
                self._snapshot_name_item_changed(item)
            elif is_snapshot_adjustment_column(item.column()):
                try:
                    value = float(item.text())
                except ValueError:
                    return
                self.set_adjustment_value(item, item.text(), value)
            if (
                self.preset_table_content_signature()
                != self.callbacks.preset_table_clean_signature()
            ):
                self.mark_preset_table_modified()

    def _snapshot_name_item_changed(self, item: QTableWidgetItem) -> None:
        self._sanitize_item_text(item, self.callbacks.snapshot_name_max_length())
        name_item = self.table.item(item.row(), 2)
        snapshot_index = (
            item.column() - SNAPSHOT_TABLE_START_COLUMN
        ) // SNAPSHOT_TABLE_COLUMN_STRIDE
        if name_item is not None:
            snapshot_names: list[str] = list(name_item.data(Qt.ItemDataRole.UserRole) or ())
            snapshot_names.extend("" for _ in range(snapshot_index + 1 - len(snapshot_names)))
            snapshot_names[snapshot_index] = item.text()
            name_item.setData(Qt.ItemDataRole.UserRole, tuple(snapshot_names))
        is_ignored = self.callbacks.is_ignored_snapshot_name(item.text())
        self.set_snapshot_name(
            item,
            item.text(),
            self.callbacks.is_solo_snapshot_name(item.text()),
            is_ignored,
        )
        self.set_snapshot_ignore_reason(
            item.row(),
            snapshot_index,
            IGNORE_REASON_REGEX,
            is_ignored,
        )
        self.callbacks.refresh_measurement_time_estimate()

    def _sanitize_item_text(self, item: QTableWidgetItem, max_length: int | None) -> None:
        sanitized = sanitize_helix_name(item.text(), max_length)
        if sanitized == item.text():
            return
        signals_blocked = self.table.blockSignals(True)
        try:
            item.setText(sanitized)
        finally:
            self.table.blockSignals(signals_blocked)

    def set_manual_name_modified(self, item: QTableWidgetItem, modified: bool) -> None:
        signals_blocked = self.table.blockSignals(True)
        try:
            item.setData(MANUAL_NAME_MODIFIED_ROLE, True if modified else None)
            self.callbacks.refresh_preset_item_background(item)
        finally:
            self.table.blockSignals(signals_blocked)

    def clear_manual_name_modified_highlights(self) -> None:
        for row in range(self.table.rowCount()):
            for column in range(self.table.columnCount()):
                item = self.table.item(row, column)
                if item is not None and item.data(MANUAL_NAME_MODIFIED_ROLE):
                    self.set_manual_name_modified(item, False)

    def refresh_preset_item_background(self, item: QTableWidgetItem) -> None:
        refresh_preset_item_background(item)

    def set_adjustment_value(
        self,
        item: QTableWidgetItem,
        text: str,
        value: float,
        custom_adjustment: float | None = None,
        display_value: float | None = None,
    ) -> None:
        if item.data(IGNORED_SNAPSHOT_ROLE):
            self.set_adjustment_ignored(item)
            return
        table = item.tableWidget()
        signals_blocked = table.blockSignals(True) if table is not None else False
        try:
            if custom_adjustment is None and display_value is None:
                display_value = value
                display_text = "0" if value == 0 else str(text)
            else:
                display_value = value if display_value is None else display_value
                display_text = _format_adjustment(display_value)
            if custom_adjustment is not None:
                display_text += f" ({_format_adjustment(custom_adjustment)})"
            item.setText(display_text)
            item.setData(ADJUSTMENT_VALUE_ROLE, value)
            item.setData(MEASURED_ADJUSTMENT_ROLE, None)
            item.setToolTip(
                f"Custom loudness adjustment: {_format_adjustment(custom_adjustment)}"
                if custom_adjustment is not None
                else ""
            )
            font = item.font()
            font.setBold(False)
            font.setPointSize(max(QApplication.font().pointSize(), 9))
            item.setFont(font)
            item.setForeground(
                QBrush(IGNORED_SNAPSHOT_FOREGROUND)
                if item.data(IGNORED_SNAPSHOT_ROLE)
                else QBrush()
            )
            if table is not None:
                table.removeCellWidget(item.row(), item.column())
                if custom_adjustment is not None:
                    self.callbacks.refresh_adjustment_cell_widget(item)
                else:
                    ensure_item_column_width(item)
        finally:
            if table is not None:
                table.blockSignals(signals_blocked)

    def set_output_level(self, item: QTableWidgetItem, value: str | float) -> None:
        table = item.tableWidget()
        signals_blocked = table.blockSignals(True) if table is not None else False
        try:
            text = value if isinstance(value, str) else f"{value:.1f}"
            item.setText(text)
            item.setToolTip(f"Current output block level: {text} dB" if text else "")
            font = item.font()
            font.setBold(False)
            font.setPointSize(max(QApplication.font().pointSize(), 9))
            item.setFont(font)
            item.setForeground(
                QBrush(IGNORED_SNAPSHOT_FOREGROUND)
                if item.data(IGNORED_SNAPSHOT_ROLE)
                else QBrush()
            )
            if table is not None:
                table.removeCellWidget(item.row(), item.column())
                ensure_item_column_width(item)
        finally:
            if table is not None:
                table.blockSignals(signals_blocked)

    def set_adjustment_pending(self, item: QTableWidgetItem) -> None:
        table = item.tableWidget()
        signals_blocked = table.blockSignals(True) if table is not None else False
        try:
            item.setText("?")
            item.setData(ADJUSTMENT_VALUE_ROLE, None)
            item.setData(MEASURED_ADJUSTMENT_ROLE, None)
            item.setData(RECORDED_OUTPUT_PATH_ROLE, None)
            item.setToolTip("This selected snapshot has not been measured yet.")
            font = item.font()
            font.setBold(False)
            font.setPointSize(max(QApplication.font().pointSize(), 9))
            item.setFont(font)
            item.setForeground(QBrush(QColor("#6b7280")))
            if table is not None:
                table.removeCellWidget(item.row(), item.column())
                ensure_item_column_width(item)
        finally:
            if table is not None:
                table.blockSignals(signals_blocked)

    def set_adjustment_ignored(self, item: QTableWidgetItem) -> None:
        table = item.tableWidget()
        signals_blocked = table.blockSignals(True) if table is not None else False
        try:
            item.setText("-")
            item.setData(ADJUSTMENT_VALUE_ROLE, None)
            item.setData(MEASURED_ADJUSTMENT_ROLE, None)
            item.setData(RECORDED_OUTPUT_PATH_ROLE, None)
            item.setToolTip("This snapshot is skipped during normalization.")
            font = item.font()
            font.setBold(False)
            font.setPointSize(max(QApplication.font().pointSize(), 9))
            item.setFont(font)
            item.setForeground(QBrush(IGNORED_SNAPSHOT_FOREGROUND))
            if table is not None:
                table.removeCellWidget(item.row(), item.column())
                ensure_item_column_width(item)
        finally:
            if table is not None:
                table.blockSignals(signals_blocked)

    def clear_preset_adjustments(self, row: int) -> None:
        patch = self.table.item(row, 1)
        if patch is not None:
            self.adjusted_presets.discard(patch.text())
        self.clear_bad_lufs_highlight(row)
        self.clear_processed_snapshot_highlight(row)
        for snapshot_index in range(self.callbacks.snapshot_count()):
            name_column = snapshot_name_column(snapshot_index)
            output_column = snapshot_output_column(snapshot_index)
            adjustment_column = snapshot_adjustment_column(snapshot_index)
            name = self.table.item(row, name_column)
            output = self.table.item(row, output_column)
            adjustment = self.table.item(row, adjustment_column)
            if name is None:
                name = QTableWidgetItem()
                self.table.setItem(row, name_column, name)
            if output is None:
                output = QTableWidgetItem()
                self.table.setItem(row, output_column, output)
            if adjustment is None:
                adjustment = QTableWidgetItem()
                self.table.setItem(row, adjustment_column, adjustment)
            name.setData(RECORDED_OUTPUT_PATH_ROLE, None)
            set_preset_item_editable(name, False)
            set_preset_item_editable(output, False)
            set_preset_item_editable(adjustment, False)
            self.set_output_level(output, "")
            adjustment.setData(RECORDED_OUTPUT_PATH_ROLE, None)
            self.set_adjustment_value(adjustment, "+0", 0)
        self.refresh_snapshot_output_levels(row)

    def mark_selected_preset_adjustments_pending(self, row: int) -> None:
        selected = self.table.item(row, 0)
        if selected is None or selected.checkState() != Qt.CheckState.Checked:
            return
        for snapshot_index in range(self.callbacks.snapshot_count()):
            item = self.table.item(row, snapshot_adjustment_column(snapshot_index))
            if item is not None:
                if item.data(IGNORED_SNAPSHOT_ROLE):
                    self.set_adjustment_ignored(item)
                    continue
                self.set_adjustment_pending(item)

    def set_bad_lufs_highlight(self, row: int, snapshot_index: int) -> None:
        signals_blocked = self.table.blockSignals(True)
        try:
            columns = (
                1,
                2,
                snapshot_name_column(snapshot_index),
                snapshot_output_column(snapshot_index),
                snapshot_adjustment_column(snapshot_index),
            )
            for column in columns:
                item = self.table.item(row, column)
                if item is not None:
                    item.setData(PROCESSED_SNAPSHOT_ROLE, None)
                    item.setData(BAD_LUFS_HIGHLIGHT_ROLE, True)
                    self.refresh_preset_item_background(item)
                    self.callbacks.refresh_preset_cell_widget_background(item)
        finally:
            self.table.blockSignals(signals_blocked)

    def set_bad_snapshot_measurement(
        self,
        row: int,
        snapshot_index: int,
        detail: str | None = None,
        *,
        adjustment: float | None = None,
        append_detail: bool = True,
    ) -> None:
        adjustment_item = self.table.item(
            row,
            snapshot_adjustment_column(snapshot_index),
        )
        if adjustment_item is None:
            return

        display_text, tooltip = _bad_lufs_adjustment_display(detail, adjustment=adjustment)
        if append_detail and detail and display_text == "Measurement failed ⚠️":
            tooltip = f"{tooltip}\n\nMeasurement detail: {detail}"
        adjustment_item.setText(display_text)
        adjustment_item.setData(ADJUSTMENT_VALUE_ROLE, None)
        adjustment_item.setData(MEASURED_ADJUSTMENT_ROLE, adjustment)
        adjustment_item.setToolTip(tooltip)
        adjustment_item.setForeground(QBrush(BAD_LUFS_FOREGROUND))
        font = adjustment_item.font()
        font.setBold(True)
        font.setPointSize(max(QApplication.font().pointSize(), 9))
        adjustment_item.setFont(font)
        self.callbacks.refresh_adjustment_cell_widget(adjustment_item)
        self.set_processed_snapshot_highlight(row, snapshot_index, False)
        self.set_bad_lufs_highlight(row, snapshot_index)

    def clear_bad_lufs_highlight(self, row: int) -> None:
        signals_blocked = self.table.blockSignals(True)
        try:
            for column in range(self.table.columnCount()):
                item = self.table.item(row, column)
                if item is not None:
                    item.setData(BAD_LUFS_HIGHLIGHT_ROLE, None)
                    self.refresh_preset_item_background(item)
                    self.callbacks.refresh_preset_cell_widget_background(item)
        finally:
            self.table.blockSignals(signals_blocked)

    def clear_bad_lufs_highlights(self) -> None:
        for row in range(self.table.rowCount()):
            self.clear_bad_lufs_highlight(row)

    def set_processed_snapshot_highlight(
        self,
        row: int,
        snapshot_index: int,
        processed: bool,
    ) -> None:
        signals_blocked = self.table.blockSignals(True)
        try:
            for column in (
                snapshot_name_column(snapshot_index),
                snapshot_output_column(snapshot_index),
                snapshot_adjustment_column(snapshot_index),
            ):
                item = self.table.item(row, column)
                if item is None:
                    continue
                if item.data(IGNORED_SNAPSHOT_ROLE) or item.data(BAD_LUFS_HIGHLIGHT_ROLE):
                    item.setData(PROCESSED_SNAPSHOT_ROLE, None)
                else:
                    item.setData(PROCESSED_SNAPSHOT_ROLE, True if processed else None)
                self.refresh_preset_item_background(item)
                self.callbacks.refresh_preset_cell_widget_background(item)
        finally:
            self.table.blockSignals(signals_blocked)

    def clear_processed_snapshot_highlight(self, row: int) -> None:
        signals_blocked = self.table.blockSignals(True)
        try:
            for column in range(self.table.columnCount()):
                item = self.table.item(row, column)
                if item is not None:
                    item.setData(PROCESSED_SNAPSHOT_ROLE, None)
                    self.refresh_preset_item_background(item)
                    self.callbacks.refresh_preset_cell_widget_background(item)
        finally:
            self.table.blockSignals(signals_blocked)

    def set_ignored_snapshot_highlight(
        self,
        row: int,
        snapshot_index: int,
        ignored: bool,
        reason: str = IGNORE_REASON_REGEX,
    ) -> None:
        self.set_snapshot_ignore_reason(row, snapshot_index, reason, ignored)

    def set_snapshot_ignore_reason(
        self,
        row: int,
        snapshot_index: int,
        reason: str,
        active: bool,
    ) -> None:
        name_item = self.table.item(row, snapshot_name_column(snapshot_index))
        reasons = _snapshot_ignore_reasons(name_item) if name_item is not None else ()
        if active:
            reasons = tuple(dict.fromkeys((*reasons, reason)))
        else:
            reasons = tuple(existing for existing in reasons if existing != reason)
        self.set_snapshot_ignore_reasons(row, snapshot_index, reasons)

    def set_snapshot_ignore_reasons(
        self,
        row: int,
        snapshot_index: int,
        reasons: tuple[str, ...],
    ) -> None:
        reasons = tuple(reason for reason in reasons if reason in IGNORE_REASON_LABELS)
        ignored = bool(reasons)
        signals_blocked = self.table.blockSignals(True)
        try:
            for column in (
                snapshot_name_column(snapshot_index),
                snapshot_output_column(snapshot_index),
                snapshot_adjustment_column(snapshot_index),
            ):
                item = self.table.item(row, column)
                if item is None:
                    continue
                item.setData(IGNORED_SNAPSHOT_REASONS_ROLE, reasons or None)
                item.setData(IGNORED_SNAPSHOT_ROLE, True if ignored else None)
                if ignored:
                    item.setData(PROCESSED_SNAPSHOT_ROLE, None)
                if column == snapshot_name_column(snapshot_index):
                    if ignored:
                        item.setData(RECORDED_OUTPUT_PATH_ROLE, None)
                    item.setToolTip(
                        _snapshot_tooltip(
                            bool(item.data(SOLO_SNAPSHOT_ROLE)),
                            reasons,
                        )
                    )
                item.setForeground(QBrush(IGNORED_SNAPSHOT_FOREGROUND) if ignored else QBrush())
                self.refresh_preset_item_background(item)
                if column == snapshot_name_column(snapshot_index):
                    self.callbacks.refresh_snapshot_name_cell_widget(item)
                self.callbacks.refresh_preset_cell_widget_background(item)
            adjustment = self.table.item(row, snapshot_adjustment_column(snapshot_index))
            if adjustment is not None:
                if ignored:
                    self.set_adjustment_ignored(adjustment)
                elif (
                    adjustment.text() in {"-", "Ignore"}
                    and adjustment.data(ADJUSTMENT_VALUE_ROLE) is None
                ):
                    self.set_adjustment_value(adjustment, "+0", 0)
        finally:
            self.table.blockSignals(signals_blocked)

    def set_preset_ignore_reason(self, row: int, active: bool) -> None:
        for snapshot_index in range(self.callbacks.snapshot_count()):
            self.set_snapshot_ignore_reason(row, snapshot_index, IGNORE_REASON_PRESET, active)

    def set_comparison_ignore_plan(
        self,
        changed_by_patch: Mapping[str, tuple[int, ...]],
    ) -> int:
        measurable = 0
        for row in range(self.table.rowCount()):
            patch_item = self.table.item(row, 1)
            if patch_item is None:
                continue
            changed = set(changed_by_patch.get(patch_item.text(), ()))
            for snapshot_index in range(self.callbacks.snapshot_count()):
                is_changed = snapshot_index + 1 in changed
                if is_changed:
                    measurable += 1
                self.set_snapshot_ignore_reason(
                    row,
                    snapshot_index,
                    IGNORE_REASON_COMPARISON,
                    not is_changed,
                )
        return measurable

    def clear_comparison_ignore_plan(self) -> None:
        for row in range(self.table.rowCount()):
            for snapshot_index in range(self.callbacks.snapshot_count()):
                self.set_snapshot_ignore_reason(
                    row,
                    snapshot_index,
                    IGNORE_REASON_COMPARISON,
                    False,
                )

    def set_snapshot_name(
        self,
        item: QTableWidgetItem,
        name: str,
        is_solo: bool,
        is_ignored: bool = False,
    ) -> None:
        table = item.tableWidget()
        signals_blocked = table.blockSignals(True) if table is not None else False
        try:
            item.setText(name)
            item.setIcon(QIcon())
            item.setData(SOLO_SNAPSHOT_ROLE, True if is_solo else None)
            item.setToolTip(
                _snapshot_tooltip(
                    is_solo,
                    _snapshot_ignore_reasons(item)
                    or ((IGNORE_REASON_REGEX,) if is_ignored else ()),
                )
            )
        finally:
            if table is not None:
                table.blockSignals(signals_blocked)
        self.callbacks.refresh_snapshot_name_cell_widget(item)

    def set_snapshot_names(self, row: int, snapshot_names: tuple[str, ...]) -> None:
        name_item = self.table.item(row, 2)
        if name_item is not None:
            name_item.setData(Qt.ItemDataRole.UserRole, snapshot_names)
        self.refresh_snapshot_names(row)

    def refresh_snapshot_names(self, row: int) -> None:
        name_item = self.table.item(row, 2)
        snapshot_names = name_item.data(Qt.ItemDataRole.UserRole) if name_item is not None else ()
        snapshot_names = snapshot_names if isinstance(snapshot_names, tuple) else ()
        for snapshot_index in range(self.callbacks.snapshot_count()):
            item = self.table.item(row, snapshot_name_column(snapshot_index))
            if item is not None:
                self.set_snapshot_name(item, "", False, False)
                self.set_snapshot_ignore_reason(row, snapshot_index, IGNORE_REASON_REGEX, False)
        for snapshot, name in enumerate(snapshot_names[: self.callbacks.snapshot_count()]):
            item = self.table.item(row, snapshot_name_column(snapshot))
            if item is not None:
                is_ignored = self.callbacks.is_ignored_snapshot_name(name)
                self.set_snapshot_name(
                    item,
                    name,
                    self.callbacks.is_solo_snapshot_name(name),
                    is_ignored,
                )
                self.set_snapshot_ignore_reason(row, snapshot, IGNORE_REASON_REGEX, is_ignored)

    def refresh_all_snapshot_names(self) -> None:
        for row in range(self.table.rowCount()):
            self.refresh_snapshot_names(row)

    def set_snapshot_output_levels(
        self,
        row: int,
        levels: object,
        output_paths: object = (),
    ) -> None:
        name_item = self.table.item(row, 2)
        if name_item is not None:
            name_item.setData(
                SNAPSHOT_OUTPUT_LEVELS_ROLE,
                _normalize_snapshot_output_levels(levels),
            )
            name_item.setData(
                SNAPSHOT_OUTPUT_PATHS_ROLE,
                _normalize_snapshot_output_paths(output_paths),
            )
        self.refresh_snapshot_output_levels(row)

    def refresh_snapshot_output_levels(self, row: int) -> None:
        name_item = self.table.item(row, 2)
        levels = name_item.data(SNAPSHOT_OUTPUT_LEVELS_ROLE) if name_item is not None else ()
        levels = levels if isinstance(levels, tuple) else ()
        for snapshot_index in range(self.callbacks.snapshot_count()):
            item = self.table.item(row, snapshot_output_column(snapshot_index))
            if item is not None:
                self.set_output_level(item, _format_snapshot_output_levels(levels, snapshot_index))

    @contextmanager
    def sorting_paused(self) -> Iterator[None]:
        sorting_enabled = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)
        try:
            yield
        finally:
            self.table.setSortingEnabled(sorting_enabled)


def snapshot_name_column(snapshot_index: int) -> int:
    return SNAPSHOT_TABLE_START_COLUMN + snapshot_index * SNAPSHOT_TABLE_COLUMN_STRIDE


def snapshot_output_column(snapshot_index: int) -> int:
    return snapshot_name_column(snapshot_index) + 1


def snapshot_adjustment_column(snapshot_index: int) -> int:
    return snapshot_name_column(snapshot_index) + 2


def is_snapshot_name_column(column: int) -> bool:
    return (
        column >= SNAPSHOT_TABLE_START_COLUMN
        and (column - SNAPSHOT_TABLE_START_COLUMN) % SNAPSHOT_TABLE_COLUMN_STRIDE == 0
    )


def is_snapshot_adjustment_column(column: int) -> bool:
    return (
        column >= SNAPSHOT_TABLE_START_COLUMN
        and (column - SNAPSHOT_TABLE_START_COLUMN) % SNAPSHOT_TABLE_COLUMN_STRIDE == 2
    )


def is_manual_adjustment_column(column: int) -> bool:
    return column == 2 or is_snapshot_name_column(column) or is_snapshot_adjustment_column(column)


def is_name_column(column: int) -> bool:
    return column == 2 or is_snapshot_name_column(column)


def adjustment_column_width(table: QTableWidget) -> int:
    sample = f"{ADJUSTMENT_MIN_DB:.1f}"
    padding = 14
    metrics = table.fontMetrics()
    return max(
        58,
        metrics.horizontalAdvance(sample) + padding,
        metrics.horizontalAdvance(f"+{ADJUSTMENT_MAX_DB:.1f}") + padding,
    )


def output_level_column_width(table: QTableWidget) -> int:
    padding = 14
    metrics = table.fontMetrics()
    return max(
        58,
        metrics.horizontalAdvance(f"{OUTPUT_LEVEL_MIN_DB:.1f}") + padding,
        metrics.horizontalAdvance(f"{OUTPUT_LEVEL_MAX_DB:.1f}") + padding,
    )


def set_preset_item_editable(item: QTableWidgetItem, editable: bool) -> None:
    flags = item.flags()
    if editable:
        flags |= Qt.ItemFlag.ItemIsEditable
    else:
        flags &= ~Qt.ItemFlag.ItemIsEditable
    item.setFlags(flags)


def refresh_preset_item_background(item: QTableWidgetItem) -> None:
    if item.data(BAD_LUFS_HIGHLIGHT_ROLE):
        item.setBackground(BAD_LUFS_ROW_BACKGROUND)
    elif item.data(PROCESSED_SNAPSHOT_ROLE):
        item.setBackground(PROCESSED_SNAPSHOT_BACKGROUND)
    elif item.data(NORMALIZATION_FOCUS_ROLE):
        item.setBackground(NORMALIZATION_FOCUS_BACKGROUND)
    elif item.data(MANUAL_NAME_MODIFIED_ROLE):
        item.setBackground(MANUAL_NAME_MODIFIED_BACKGROUND)
    elif item.data(IGNORED_SNAPSHOT_ROLE):
        item.setBackground(IGNORED_SNAPSHOT_BACKGROUND)
    else:
        item.setBackground(QBrush())


def ensure_item_column_width(item: QTableWidgetItem, padding: int = 18) -> None:
    table = item.tableWidget()
    if table is None:
        return
    metrics = QFontMetrics(item.font())
    text_width = metrics.horizontalAdvance(item.text()) + padding
    widget = table.cellWidget(item.row(), item.column())
    widget_width = widget.sizeHint().width() + 4 if widget is not None else 0
    required_width = max(text_width, widget_width)
    if table.columnWidth(item.column()) < required_width:
        table.setColumnWidth(item.column(), required_width)


def refresh_adjustment_cell_widget(item: QTableWidgetItem) -> None:
    table = item.tableWidget()
    if table is None:
        return
    table.removeCellWidget(item.row(), item.column())
    has_custom_adjustment = item.toolTip().startswith("Custom loudness adjustment:")
    if has_custom_adjustment:
        label = QLabel(_custom_adjustment_label_text(item.text()))
        style_table_cell_widget(label, item)
        style_adjustment_label(label, item)
        label.setContentsMargins(3, 0, 0, 0)
        label.setToolTip(item.toolTip())
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        table.setCellWidget(item.row(), item.column(), label)
    ensure_item_column_width(item)


def style_table_cell_widget(widget: QWidget, item: QTableWidgetItem) -> None:
    table = item.tableWidget()
    palette = widget.palette()
    background = item.background()
    if background.style() != Qt.BrushStyle.NoBrush:
        color = background.color()
    elif table is not None:
        color = table.palette().color(QPalette.ColorRole.Base)
    else:
        color = QApplication.palette().color(QPalette.ColorRole.Base)
    palette.setColor(QPalette.ColorRole.Window, color)
    palette.setColor(QPalette.ColorRole.Base, color)
    widget.setPalette(palette)
    widget.setAutoFillBackground(True)
    if isinstance(widget, SnapshotNameCellWidget):
        widget.setProperty(
            "normalizationSnapshotFocusRect",
            _normalization_snapshot_focus_rect_for_cell_widget(widget, item),
        )
    widget.update()


def style_adjustment_label(label: QLabel, item: QTableWidgetItem) -> None:
    label.setFont(item.font())
    foreground = item.foreground()
    color = foreground.color()
    if foreground.style() != Qt.BrushStyle.NoBrush and color.isValid():
        label.setStyleSheet(f"color: {color.name()};")
    else:
        label.setStyleSheet("")


def refresh_preset_cell_widget_background(item: QTableWidgetItem) -> None:
    table = item.tableWidget()
    if table is None:
        return
    widget = table.cellWidget(item.row(), item.column())
    if widget is not None:
        style_table_cell_widget(widget, item)


def refresh_snapshot_name_cell_widget(
    item: QTableWidgetItem,
    *,
    ignore_reason_icons: Mapping[str, QIcon],
    speaker_icon: QIcon,
    normalization_in_progress: Callable[[], bool],
    play_recording: Callable[[Path], None],
) -> None:
    table = item.tableWidget()
    if table is None:
        return
    is_solo = bool(item.data(SOLO_SNAPSHOT_ROLE))
    ignore_reasons = _snapshot_ignore_reasons(item)
    recorded_path = item.data(RECORDED_OUTPUT_PATH_ROLE)
    table.removeCellWidget(item.row(), item.column())
    if not is_solo and not recorded_path and not ignore_reasons:
        ensure_item_column_width(item)
        return

    name_text = item.text()
    if not is_solo:
        content = SnapshotNameCellWidget(table)
        style_table_cell_widget(content, item)
        layout = _snapshot_cell_layout(content)
        label = QLabel(escape(name_text))
        label.setFont(item.font())
        label.setToolTip(item.toolTip())
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(label, 1)
        _add_ignore_reason_icons(layout, content, ignore_reasons, ignore_reason_icons)
        if recorded_path:
            _add_recorded_output_button(
                layout,
                content,
                Path(recorded_path),
                speaker_icon=speaker_icon,
                normalization_in_progress=normalization_in_progress,
                play_recording=play_recording,
            )
        content.setToolTip(item.toolTip())
        table.setCellWidget(item.row(), item.column(), content)
        ensure_item_column_width(item)
        return

    label_text = f"{escape(name_text)} <span style='color: #f59e0b;'>★</span>"
    if not recorded_path and not ignore_reasons:
        label = SnapshotNameCellWidget(label_text)
        label.setContentsMargins(3, 0, 0, 0)
        label.setToolTip(item.toolTip())
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        style_table_cell_widget(label, item)
        table.setCellWidget(item.row(), item.column(), label)
        ensure_item_column_width(item)
        return

    content = SnapshotNameCellWidget(table)
    style_table_cell_widget(content, item)
    layout = _snapshot_cell_layout(content)
    label = QLabel(label_text)
    label.setFont(item.font())
    label.setContentsMargins(3, 0, 0, 0)
    label.setToolTip(item.toolTip())
    label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    layout.addWidget(label, 1)
    _add_ignore_reason_icons(layout, content, ignore_reasons, ignore_reason_icons)
    if recorded_path:
        _add_recorded_output_button(
            layout,
            content,
            Path(recorded_path),
            speaker_icon=speaker_icon,
            normalization_in_progress=normalization_in_progress,
            play_recording=play_recording,
        )
    content.setToolTip(item.toolTip())
    table.setCellWidget(item.row(), item.column(), content)
    ensure_item_column_width(item)


def _snapshot_cell_layout(parent: QWidget) -> QHBoxLayout:
    layout = QHBoxLayout(parent)
    layout.setContentsMargins(3, 0, 2, 0)
    layout.setSpacing(2)
    return layout


def _add_ignore_reason_icons(
    layout: QHBoxLayout,
    parent: QWidget,
    reasons: tuple[str, ...],
    ignore_reason_icons: Mapping[str, QIcon],
) -> None:
    for reason in reasons:
        label = QLabel(parent)
        label.setPixmap(ignore_reason_icons[reason].pixmap(18, 18))
        label.setFixedSize(20, 20)
        label.setToolTip(
            f"Skipped during normalization: {IGNORE_REASON_LABELS.get(reason, reason)}"
        )
        layout.addWidget(label)


def _add_recorded_output_button(
    layout: QHBoxLayout,
    parent: QWidget,
    path: Path,
    *,
    speaker_icon: QIcon,
    normalization_in_progress: Callable[[], bool],
    play_recording: Callable[[Path], None],
) -> None:
    button = QToolButton(parent)
    button.setIcon(speaker_icon)
    button.setAutoRaise(True)
    button.setIconSize(QSize(14, 14))
    button.setFixedSize(22, 22)
    button.setToolTip("Play recorded snapshot output.")
    button.setEnabled(not normalization_in_progress())
    button.clicked.connect(lambda checked=False, path=path: play_recording(path))
    layout.addWidget(button)


class AttentionFrameDelegate(QStyledItemDelegate):
    """Draw an attention frame around cells marked by the window."""

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        super().paint(painter, option, index)
        if not index.data(PRESET_TABLE_ATTENTION_ROLE):
            return

        painter.save()
        painter.setPen(QPen(QColor("#dc2626"), 3))
        painter.drawRect(option.rect.adjusted(1, 1, -2, -2))
        painter.restore()


def _normalization_snapshot_focus_rect_for_cell_widget(
    widget: QWidget,
    item: QTableWidgetItem,
) -> QRect | None:
    table = item.tableWidget()
    if not isinstance(table, ContentHeightTableWidget):
        return None
    snapshot_index = getattr(table, "_normalizing_snapshot", None)
    if snapshot_index is None:
        return None
    if item.column() != snapshot_name_column(snapshot_index):
        return None
    focus_rect = table._normalization_focus_rect(item.row(), snapshot_index)
    if focus_rect is None:
        return None
    local_rect = QRect(focus_rect.adjusted(0, 0, -1, -1))
    local_rect.translate(-widget.geometry().x(), -widget.geometry().y())
    return local_rect


class SnapshotNameCellWidget(QLabel):
    """Snapshot-name cell widget that keeps table group separators visible."""

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        focus_rect = self.property("normalizationSnapshotFocusRect")
        if isinstance(focus_rect, QRect):
            pen = QPen(NORMALIZATION_FOCUS_BLUE)
            pen.setWidth(3)
            painter.setPen(pen)
            painter.drawRect(focus_rect)
            return

        pen = QPen(self.palette().mid().color())
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawLine(0, 0, 0, self.height())


class ContentHeightTableWidget(QTableWidget):
    """Grow with preset rows until an internal scrollbar is more useful."""

    MAX_VISIBLE_ROWS = 12

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._normalizing_row: int | None = None
        self._normalizing_snapshot: int | None = None
        self.refresh_preset_item_background: Callable[[QTableWidgetItem], None] | None = None
        self.refresh_preset_cell_widget_background: Callable[[QTableWidgetItem], None] | None = None

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        self._paint_snapshot_group_separators()
        self._paint_normalization_focus()

    def set_normalization_focus(self, row: int, snapshot_index: int | None) -> None:
        previous_row = self._normalizing_row
        previous_snapshot = self._normalizing_snapshot
        self._normalizing_row = row
        self._normalizing_snapshot = snapshot_index
        self._refresh_normalization_focus_background(previous_row)
        self._refresh_normalization_focus_background(row)
        self._update_normalization_focus_rect(previous_row, previous_snapshot)
        self._update_normalization_focus_rect(row, snapshot_index)

    def clear_normalization_focus(self) -> None:
        if self._normalizing_row is None and self._normalizing_snapshot is None:
            return
        previous_row = self._normalizing_row
        previous_snapshot = self._normalizing_snapshot
        self._normalizing_row = None
        self._normalizing_snapshot = None
        self._refresh_normalization_focus_background(previous_row)
        self._update_normalization_focus_rect(previous_row, previous_snapshot)

    def clear_normalization_snapshot_focus(self, row: int) -> None:
        if self._normalizing_row != row or self._normalizing_snapshot is None:
            return
        previous_snapshot = self._normalizing_snapshot
        previous_columns = self._normalization_focus_columns(previous_snapshot)
        previous_rects = self._normalization_focus_cell_rects(row, previous_snapshot)
        self._normalizing_snapshot = None
        for column in previous_columns:
            item = self.item(row, column)
            if item is None:
                continue
            item.setData(NORMALIZATION_FOCUS_ROLE, None)
            self._refresh_preset_item_background(item)
            self._refresh_preset_cell_widget_background(item)
            widget = self.cellWidget(row, column)
            if widget is not None:
                widget.repaint()
        for rect in previous_rects:
            self.viewport().repaint(rect.adjusted(-3, -3, 3, 3))
        previous_rect = _united_rects(previous_rects)
        if previous_rect is not None:
            self.viewport().repaint(previous_rect.adjusted(-3, -3, 3, 3))

    def _refresh_normalization_focus_background(self, row: int | None) -> None:
        if row is None or not 0 <= row < self.rowCount():
            return
        focused = row == self._normalizing_row
        focus_columns = {1, 2}
        if focused:
            focus_columns.update(range(SNAPSHOT_TABLE_START_COLUMN, self.columnCount()))
        for column in range(self.columnCount()):
            item = self.item(row, column)
            if item is None:
                continue
            item.setData(
                NORMALIZATION_FOCUS_ROLE,
                True
                if focused and column in focus_columns and not item.data(IGNORED_SNAPSHOT_ROLE)
                else None,
            )
            self._refresh_preset_item_background(item)
            self._refresh_preset_cell_widget_background(item)
        self.viewport().update()

    def _refresh_preset_item_background(self, item: QTableWidgetItem) -> None:
        if self.refresh_preset_item_background is not None:
            self.refresh_preset_item_background(item)

    def _refresh_preset_cell_widget_background(self, item: QTableWidgetItem) -> None:
        if self.refresh_preset_cell_widget_background is not None:
            self.refresh_preset_cell_widget_background(item)

    def _update_normalization_focus_rect(
        self,
        row: int | None,
        snapshot_index: int | None,
    ) -> None:
        rect = self._normalization_focus_rect(row, snapshot_index)
        if rect is not None:
            self.viewport().update(rect.adjusted(-3, -3, 3, 3))

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        visible_rows = min(self.rowCount(), self.MAX_VISIBLE_ROWS)
        rows_height = sum(self.rowHeight(row) for row in range(visible_rows))
        frame_height = self.frameWidth() * 2
        hint.setHeight(
            max(
                self.minimumHeight(),
                self.horizontalHeader().sizeHint().height() + rows_height + frame_height,
            )
        )
        return hint

    def _paint_snapshot_group_separators(self) -> None:
        header = self.horizontalHeader()
        if self.columnCount() <= SNAPSHOT_TABLE_START_COLUMN:
            return

        painter = QPainter(self.viewport())
        pen = QPen(self.palette().mid().color())
        pen.setWidth(2)
        painter.setPen(pen)
        for logical_index in range(
            SNAPSHOT_TABLE_START_COLUMN,
            self.columnCount(),
            SNAPSHOT_TABLE_COLUMN_STRIDE,
        ):
            if self.isColumnHidden(logical_index):
                continue
            x = header.sectionViewportPosition(logical_index)
            if -pen.width() <= x <= self.viewport().width():
                painter.drawLine(x, 0, x, self.viewport().height())

    def _paint_normalization_focus(self) -> None:
        if self._normalizing_row is None:
            return
        snapshot_rect = self._normalization_focus_rect(
            self._normalizing_row,
            self._normalizing_snapshot,
        )
        if snapshot_rect is None:
            return

        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        snapshot_pen = QPen(NORMALIZATION_FOCUS_BLUE)
        snapshot_pen.setWidth(3)
        painter.setPen(snapshot_pen)
        painter.drawRect(snapshot_rect.adjusted(0, 0, -1, -1))

    def _normalization_focus_rect(
        self,
        row: int | None,
        snapshot_index: int | None,
    ) -> QRect | None:
        return _united_rects(self._normalization_focus_cell_rects(row, snapshot_index))

    def _normalization_focus_cell_rects(
        self,
        row: int | None,
        snapshot_index: int | None,
    ) -> tuple[QRect, ...]:
        if row is None or snapshot_index is None:
            return ()
        if not 0 <= row < self.rowCount():
            return ()

        rects = []
        for column in self._normalization_focus_columns(snapshot_index):
            if column >= self.columnCount() or self.isColumnHidden(column):
                continue
            cell_rect = self.visualRect(self.model().index(row, column))
            if not cell_rect.isValid():
                continue
            rects.append(cell_rect)
        return tuple(rects)

    @staticmethod
    def _normalization_focus_columns(snapshot_index: int) -> tuple[int, int, int]:
        return (
            snapshot_name_column(snapshot_index),
            snapshot_output_column(snapshot_index),
            snapshot_adjustment_column(snapshot_index),
        )

    @contextmanager
    def updates_paused(self) -> Iterator[None]:
        updates_enabled = self.updatesEnabled()
        self.setUpdatesEnabled(False)
        try:
            yield
        finally:
            self.setUpdatesEnabled(updates_enabled)
            self.viewport().update()


def _united_rects(rects: tuple[QRect, ...]) -> QRect | None:
    united = None
    for rect in rects:
        united = QRect(rect) if united is None else united.united(rect)
    return united
