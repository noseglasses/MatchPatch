"""Preset table item roles and small role helpers."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidgetItem

PRESET_TABLE_CSV_DELIMITER = "|"
SNAPSHOT_TABLE_START_COLUMN = 3
SNAPSHOT_TABLE_COLUMN_STRIDE = 3
PRESET_TABLE_ATTENTION_ROLE = Qt.ItemDataRole.UserRole + 1
ADJUSTMENT_VALUE_ROLE = Qt.ItemDataRole.UserRole + 2
MANUAL_NAME_MODIFIED_ROLE = Qt.ItemDataRole.UserRole + 3
BAD_LUFS_HIGHLIGHT_ROLE = Qt.ItemDataRole.UserRole + 4
RECORDED_OUTPUT_PATH_ROLE = Qt.ItemDataRole.UserRole + 5
SNAPSHOT_OUTPUT_LEVELS_ROLE = Qt.ItemDataRole.UserRole + 6
NORMALIZATION_FOCUS_ROLE = Qt.ItemDataRole.UserRole + 7
IGNORED_SNAPSHOT_ROLE = Qt.ItemDataRole.UserRole + 8
SOLO_SNAPSHOT_ROLE = Qt.ItemDataRole.UserRole + 9
MEASURED_ADJUSTMENT_ROLE = Qt.ItemDataRole.UserRole + 10
SNAPSHOT_OUTPUT_PATHS_ROLE = Qt.ItemDataRole.UserRole + 11
PROCESSED_SNAPSHOT_ROLE = Qt.ItemDataRole.UserRole + 12
IGNORED_SNAPSHOT_REASONS_ROLE = Qt.ItemDataRole.UserRole + 13
OUTPUT_LEVEL_MIN_DB = -120.0
OUTPUT_LEVEL_MAX_DB = 20.0
ADJUSTMENT_MIN_DB = OUTPUT_LEVEL_MIN_DB - OUTPUT_LEVEL_MAX_DB
ADJUSTMENT_MAX_DB = OUTPUT_LEVEL_MAX_DB - OUTPUT_LEVEL_MIN_DB
CUSTOM_ADJUSTMENT_COLOR = "#2563eb"
IGNORE_REASON_PRESET = "P"
IGNORE_REASON_COMPARISON = "C"
IGNORE_REASON_REGEX = "R"
IGNORE_REASON_LABELS = {
    IGNORE_REASON_PRESET: "preset unchecked",
    IGNORE_REASON_COMPARISON: "unchanged compared with previous file",
    IGNORE_REASON_REGEX: "ignore regex",
}


def _snapshot_ignore_reasons(item: QTableWidgetItem | None) -> tuple[str, ...]:
    if item is None:
        return ()
    reasons = item.data(IGNORED_SNAPSHOT_REASONS_ROLE)
    if isinstance(reasons, tuple):
        return tuple(reason for reason in reasons if isinstance(reason, str))
    if item.data(IGNORED_SNAPSHOT_ROLE):
        return (IGNORE_REASON_REGEX,)
    return ()


def _snapshot_tooltip(is_solo: bool, ignore_reasons: tuple[str, ...] | bool) -> str:
    if isinstance(ignore_reasons, bool):
        reasons = (IGNORE_REASON_REGEX,) if ignore_reasons else ()
    else:
        reasons = ignore_reasons
    if is_solo and reasons:
        return "Solo snapshot; skipped during normalization: " + ", ".join(
            IGNORE_REASON_LABELS.get(reason, reason) for reason in reasons
        )
    if is_solo:
        return "Solo snapshot"
    if reasons:
        return "Skipped during normalization: " + ", ".join(
            IGNORE_REASON_LABELS.get(reason, reason) for reason in reasons
        )
    return ""
