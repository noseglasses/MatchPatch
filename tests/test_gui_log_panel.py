from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QComboBox, QTextEdit

from matchpatch.gui.log_panel import (
    GuiLogController,
    GuiLogEntry,
    format_log_entry,
    log_is_visible,
)
from matchpatch.progress import ProgressEvent


def test_format_log_entry_colors_and_escapes_message() -> None:
    html = format_log_entry(
        GuiLogEntry(
            timestamp="2026-06-15 12:00:00",
            level="warning",
            message="<bad & loud>",
        )
    )

    assert "#b45309" in html
    assert "WARNING" in html
    assert "&lt;bad &amp; loud&gt;" in html


def test_log_is_visible_uses_selected_minimum_level() -> None:
    assert log_is_visible("warning", "Info")
    assert not log_is_visible("debug", "Info")
    assert log_is_visible("success", "Info")
    assert not log_is_visible("warning", "Error")


def test_log_controller_appends_and_refreshes_filtered_entries(app) -> None:
    level_selector = QComboBox()
    level_selector.addItems(["Debug", "Info", "Warning", "Error"])
    level_selector.setCurrentText("Info")
    log_widget = QTextEdit()
    controller = GuiLogController(log_widget=log_widget, level_selector=level_selector)

    controller.append("hidden detail", "debug")
    controller.append("visible line", "info")

    assert [entry[2] for entry in controller.entries] == ["hidden detail", "visible line"]
    assert "hidden detail" not in log_widget.toHtml()
    assert "visible line" in log_widget.toHtml()

    level_selector.setCurrentText("Debug")
    controller.refresh()

    assert "hidden detail" in log_widget.toHtml()
    assert "visible line" in log_widget.toHtml()


def test_log_controller_retains_recent_progress_event_limit(app) -> None:
    level_selector = QComboBox()
    level_selector.addItems(["Debug", "Info", "Warning", "Error"])
    controller = GuiLogController(
        log_widget=QTextEdit(),
        level_selector=level_selector,
        progress_event_limit=3,
    )

    for index in range(5):
        controller.retain_progress_event(ProgressEvent("log", message=f"event-{index}"))

    assert [event.message for event in controller.recent_progress_events] == [
        "event-2",
        "event-3",
        "event-4",
    ]
