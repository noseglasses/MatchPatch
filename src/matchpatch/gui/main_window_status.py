from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from matchpatch.gui.preset_table import snapshot_name_column
from matchpatch.progress import ProgressEvent

PROCESSING_DOT_GREY = "#9ca3af"
PROCESSING_DOT_GREEN = "#16a34a"
PROCESSING_DOT_RED = "#dc2626"


class MainWindowStatusMixin:
    def __getattr__(self, name: str) -> Any:  # noqa: ANN401
        raise AttributeError(name)

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
