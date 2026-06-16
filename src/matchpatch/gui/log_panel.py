"""GUI log formatting, filtering, and recent progress retention."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import Iterable

from PySide6.QtWidgets import QComboBox, QTextEdit

from matchpatch.progress import ProgressEvent

LOG_PRIORITIES = {"debug": 10, "info": 20, "success": 20, "warning": 30, "error": 40}
LOG_COLORS = {
    "debug": "#6b7280",
    "info": "#2563eb",
    "success": "#15803d",
    "warning": "#b45309",
    "error": "#b91c1c",
}


@dataclass(frozen=True)
class GuiLogEntry:
    timestamp: str
    level: str
    message: str

    @classmethod
    def current(cls, message: str, level: str) -> GuiLogEntry:
        timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
        return cls(timestamp=timestamp, level=level, message=message)

    def as_tuple(self) -> tuple[str, str, str]:
        return self.timestamp, self.level, self.message


def log_is_visible(level: str, selected_level: str) -> bool:
    selected = selected_level.lower()
    return LOG_PRIORITIES.get(level, LOG_PRIORITIES["info"]) >= LOG_PRIORITIES[selected]


def format_log_entry(entry: GuiLogEntry) -> str:
    color = LOG_COLORS.get(entry.level, LOG_COLORS["info"])
    return (
        f'<span style="color:{color}">[{entry.timestamp}] {escape(entry.level.upper())}: '
        f"{escape(entry.message)}</span>"
    )


class GuiLogController:
    def __init__(
        self,
        *,
        log_widget: QTextEdit,
        level_selector: QComboBox,
        progress_event_limit: int = 100,
    ) -> None:
        self.log_widget = log_widget
        self.level_selector = level_selector
        self.entries: list[tuple[str, str, str]] = []
        self.recent_progress_events: deque[ProgressEvent] = deque(maxlen=progress_event_limit)

    def append(self, message: str, level: str) -> None:
        entry = GuiLogEntry.current(message, level)
        self.entries.append(entry.as_tuple())
        if self.is_visible(level):
            self.log_widget.append(format_log_entry(entry))

    def clear_entries(self) -> None:
        self.entries.clear()
        self.log_widget.clear()

    def refresh(self) -> None:
        self.log_widget.clear()
        for entry in self.gui_log_entries():
            if self.is_visible(entry.level):
                self.log_widget.append(format_log_entry(entry))

    def is_visible(self, level: str) -> bool:
        return log_is_visible(level, self.level_selector.currentText())

    def gui_log_entries(self) -> Iterable[GuiLogEntry]:
        for timestamp, level, message in self.entries:
            yield GuiLogEntry(timestamp=timestamp, level=level, message=message)

    def retain_progress_event(self, event: ProgressEvent) -> None:
        self.recent_progress_events.append(event)

    def clear_progress_events(self) -> None:
        self.recent_progress_events.clear()
