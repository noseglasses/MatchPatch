"""Pipe-delimited CSV helpers for the editable preset table."""

from __future__ import annotations

import csv
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem

from matchpatch.gui.preset_table import snapshot_adjustment_column, snapshot_name_column
from matchpatch.gui.table_formatting import _format_adjustment, _parse_adjustment_display_text
from matchpatch.gui.table_roles import (
    ADJUSTMENT_VALUE_ROLE,
    BAD_LUFS_HIGHLIGHT_ROLE,
    IGNORED_SNAPSHOT_ROLE,
    PRESET_TABLE_CSV_DELIMITER,
)


@dataclass(frozen=True)
class PresetTableCsvLoadResult:
    accepted: int
    errors: list[str] = field(default_factory=list)


class PresetTableCsvCallbacks(Protocol):
    def validate_preset_name(self, name: str, /) -> None: ...

    def validate_snapshot_name(self, name: str, /) -> None: ...

    def is_solo_snapshot_name(self, name: str, /) -> bool: ...

    def is_ignored_snapshot_name(self, name: str, /) -> bool: ...

    def set_snapshot_name(
        self,
        item: QTableWidgetItem,
        name: str,
        is_solo: bool,
        is_ignored: bool = False,
        /,
    ) -> None: ...

    def set_ignored_snapshot_highlight(
        self,
        row: int,
        snapshot_index: int,
        ignored: bool,
        /,
    ) -> None: ...

    def set_adjustment_value(
        self,
        item: QTableWidgetItem,
        text: str,
        value: float,
        /,
    ) -> None: ...

    def mark_preset_adjusted(self, preset_id: str, /) -> None: ...


@dataclass(frozen=True)
class FunctionPresetTableCsvCallbacks:
    validate_preset_name_callback: Callable[[str], None]
    validate_snapshot_name_callback: Callable[[str], None]
    is_solo_snapshot_name_callback: Callable[[str], bool]
    is_ignored_snapshot_name_callback: Callable[[str], bool]
    set_snapshot_name_callback: Callable[[QTableWidgetItem, str, bool, bool], None]
    set_ignored_snapshot_highlight_callback: Callable[[int, int, bool], None]
    set_adjustment_value_callback: Callable[[QTableWidgetItem, str, float], None]
    mark_preset_adjusted_callback: Callable[[str], None]

    def validate_preset_name(self, name: str, /) -> None:
        self.validate_preset_name_callback(name)

    def validate_snapshot_name(self, name: str, /) -> None:
        self.validate_snapshot_name_callback(name)

    def is_solo_snapshot_name(self, name: str, /) -> bool:
        return self.is_solo_snapshot_name_callback(name)

    def is_ignored_snapshot_name(self, name: str, /) -> bool:
        return self.is_ignored_snapshot_name_callback(name)

    def set_snapshot_name(
        self,
        item: QTableWidgetItem,
        name: str,
        is_solo: bool,
        is_ignored: bool = False,
        /,
    ) -> None:
        self.set_snapshot_name_callback(item, name, is_solo, is_ignored)

    def set_ignored_snapshot_highlight(
        self,
        row: int,
        snapshot_index: int,
        ignored: bool,
        /,
    ) -> None:
        self.set_ignored_snapshot_highlight_callback(row, snapshot_index, ignored)

    def set_adjustment_value(
        self,
        item: QTableWidgetItem,
        text: str,
        value: float,
        /,
    ) -> None:
        self.set_adjustment_value_callback(item, text, value)

    def mark_preset_adjusted(self, preset_id: str, /) -> None:
        self.mark_preset_adjusted_callback(preset_id)


def preset_table_csv_headers(snapshot_count: int) -> list[str]:
    headers = ["preset_id", "preset_name"]
    for snapshot in range(1, snapshot_count + 1):
        headers.extend([f"snapshot_{snapshot}_name", f"snapshot_{snapshot}_adjustment"])
    return headers


def preset_table_csv_row(table: QTableWidget, row: int, snapshot_count: int) -> list[str]:
    preset_id_item = table.item(row, 1)
    preset_name_item = table.item(row, 2)
    values = [
        preset_id_item.text() if preset_id_item is not None else "",
        preset_name_item.text() if preset_name_item is not None else "",
    ]
    for snapshot_index in range(snapshot_count):
        name = table.item(row, snapshot_name_column(snapshot_index))
        adjustment = table.item(row, snapshot_adjustment_column(snapshot_index))
        values.extend(
            [
                name.text() if name is not None else "",
                _preset_table_csv_adjustment_value(adjustment),
            ]
        )
    return values


def load_preset_table_csv(
    path: Path,
    table: QTableWidget,
    snapshot_count: int,
    callbacks: PresetTableCsvCallbacks,
) -> PresetTableCsvLoadResult:
    errors: list[str] = []
    accepted = 0
    headers = preset_table_csv_headers(snapshot_count)
    current_rows = {
        item.text(): row
        for row in range(table.rowCount())
        if (item := table.item(row, 1)) is not None
    }

    with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.reader(csv_file, delimiter=PRESET_TABLE_CSV_DELIMITER)
        for line_number, row in enumerate(reader, start=1):
            if line_number == 1 and row == headers:
                continue
            if not row or all(not cell for cell in row):
                continue
            parsed = parse_preset_table_csv_row(
                row,
                line_number,
                headers,
                current_rows,
                snapshot_count,
                callbacks,
                errors,
            )
            if parsed is None:
                continue
            table_row, preset_name, snapshot_names, adjustments = parsed
            apply_preset_table_csv_row(
                table,
                table_row,
                preset_name,
                snapshot_names,
                adjustments,
                callbacks,
            )
            accepted += 1

    return PresetTableCsvLoadResult(accepted=accepted, errors=errors)


def parse_preset_table_csv_row(
    row: list[str],
    line_number: int,
    headers: list[str],
    current_rows: dict[str, int],
    snapshot_count: int,
    callbacks: PresetTableCsvCallbacks,
    errors: list[str],
) -> tuple[int, str, list[str], list[tuple[str, float]]] | None:
    expected_columns = len(headers)
    if len(row) != expected_columns:
        errors.append(f"Line {line_number}: expected {expected_columns} columns, got {len(row)}.")
        return None

    preset_id = row[0]
    table_row = current_rows.get(preset_id)
    if table_row is None:
        errors.append(
            f"Line {line_number}: preset ID {preset_id!r} is not listed in the current table."
        )
        return None

    preset_name = row[1]
    try:
        callbacks.validate_preset_name(preset_name)
    except ValueError as exc:
        errors.append(f"Line {line_number}: preset name is invalid: {exc}.")
        return None

    snapshot_names: list[str] = []
    adjustments: list[tuple[str, float]] = []
    for snapshot_index in range(snapshot_count):
        name = row[2 + snapshot_index * 2]
        adjustment_text = row[3 + snapshot_index * 2]
        try:
            callbacks.validate_snapshot_name(name)
        except ValueError as exc:
            errors.append(
                f"Line {line_number}: snapshot {snapshot_index + 1} name is invalid: {exc}."
            )
            return None
        try:
            adjustment = (
                0.0
                if adjustment_text in {"-", "Ignore"}
                else float(adjustment_text.split(" ", 1)[0])
            )
        except ValueError:
            errors.append(
                f"Line {line_number}: snapshot {snapshot_index + 1} adjustment "
                f"is not a floating point number: {adjustment_text!r}."
            )
            return None
        if not math.isfinite(adjustment):
            errors.append(
                f"Line {line_number}: snapshot {snapshot_index + 1} adjustment "
                f"is not finite: {adjustment_text!r}."
            )
            return None
        snapshot_names.append(name)
        adjustments.append((adjustment_text, adjustment))

    return table_row, preset_name, snapshot_names, adjustments


def apply_preset_table_csv_row(
    table: QTableWidget,
    row: int,
    preset_name: str,
    snapshot_names: list[str],
    adjustments: list[tuple[str, float]],
    callbacks: PresetTableCsvCallbacks,
) -> None:
    preset_item = table.item(row, 2)
    if preset_item is None:
        preset_item = QTableWidgetItem()
        table.setItem(row, 2, preset_item)
    preset_item.setText(preset_name)
    preset_item.setData(Qt.ItemDataRole.UserRole, tuple(snapshot_names))
    for snapshot_index, (adjustment_text, adjustment) in enumerate(adjustments):
        name_column = snapshot_name_column(snapshot_index)
        adjustment_column = snapshot_adjustment_column(snapshot_index)
        name_item = table.item(row, name_column)
        adjustment_item = table.item(row, adjustment_column)
        if name_item is None:
            name_item = QTableWidgetItem()
            table.setItem(row, name_column, name_item)
        if adjustment_item is None:
            adjustment_item = QTableWidgetItem()
            table.setItem(row, adjustment_column, adjustment_item)
        snapshot_name = snapshot_names[snapshot_index]
        is_ignored = callbacks.is_ignored_snapshot_name(snapshot_name)
        callbacks.set_snapshot_name(
            name_item,
            snapshot_name,
            callbacks.is_solo_snapshot_name(snapshot_name),
            is_ignored,
        )
        if is_ignored:
            callbacks.set_ignored_snapshot_highlight(row, snapshot_index, True)
            if adjustment_text in {"-", "Ignore"}:
                adjustment_item.setText(adjustment_text)
            continue
        callbacks.set_adjustment_value(adjustment_item, adjustment_text, adjustment)

    patch_item = table.item(row, 1)
    if patch_item is not None:
        callbacks.mark_preset_adjusted(patch_item.text())


def _preset_table_csv_adjustment_value(adjustment: QTableWidgetItem | None) -> str:
    if adjustment is None:
        return ""
    if adjustment.data(IGNORED_SNAPSHOT_ROLE):
        return adjustment.text()
    if adjustment.data(BAD_LUFS_HIGHLIGHT_ROLE):
        return adjustment.text()
    stored_value = adjustment.data(ADJUSTMENT_VALUE_ROLE)
    if isinstance(stored_value, (int, float)) and not isinstance(stored_value, bool):
        try:
            displayed_value = _parse_adjustment_display_text(adjustment.text())
        except ValueError:
            displayed_value = None
        if displayed_value == float(stored_value) and "(" not in adjustment.text():
            return adjustment.text()
        return _format_adjustment(float(stored_value))
    return _format_adjustment(_parse_adjustment_display_text(adjustment.text()))
