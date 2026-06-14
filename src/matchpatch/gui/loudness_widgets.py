"""Loudness meter widgets and formatting helpers."""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPalette
from PySide6.QtWidgets import QProgressBar, QWidget

from matchpatch.gui.table_formatting import _interpolate_color

LOUDNESS_MINIMUM = -60.0
LOUDNESS_MAXIMUM = 0.0
LOUDNESS_SCALE = 10
LOUDNESS_YELLOW_DELTA = 3.0
LOUDNESS_RED_DELTA = 6.0
LOUDNESS_TARGET_GREEN = QColor("#16a34a")
LOUDNESS_WARNING_YELLOW = QColor("#eab308")
LOUDNESS_WARNING_RED = QColor("#dc2626")


class LoudnessBar(QProgressBar):
    """Display LUFS relative to the configured target with a target marker."""

    def __init__(self) -> None:
        super().__init__()
        self._target_lufs = -16.0
        self._default_highlight = self.palette().color(QPalette.ColorRole.Highlight)
        self.setTextVisible(False)
        self.setRange(
            round(LOUDNESS_MINIMUM * LOUDNESS_SCALE),
            round(LOUDNESS_MAXIMUM * LOUDNESS_SCALE),
        )

    def reset_loudness(self, target_lufs: float) -> None:
        self._target_lufs = target_lufs
        self.setValue(self.minimum())
        self._set_colors(self._default_highlight)
        self.update()

    def set_loudness(
        self,
        lufs: float,
        target_lufs: float,
        highlight: QColor | None = None,
    ) -> None:
        self._target_lufs = target_lufs
        self.setValue(
            max(
                self.minimum(),
                min(self.maximum(), round(lufs * LOUDNESS_SCALE)),
            )
        )
        if highlight is None:
            delta = lufs - target_lufs
            color = "#dc2626" if delta > 0 else "#2563eb" if delta < 0 else "#16a34a"
            highlight = QColor(color)
        self._set_colors(highlight)
        self.update()

    def _set_colors(self, highlight: QColor) -> None:
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Highlight, highlight)
        palette.setColor(QPalette.ColorRole.Text, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
        self.setPalette(palette)

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        span = self.maximum() - self.minimum()
        if span <= 0:
            return
        target_value = max(
            self.minimum(),
            min(self.maximum(), round(self._target_lufs * LOUDNESS_SCALE)),
        )
        x = round((target_value - self.minimum()) / span * (self.width() - 1))
        painter = QPainter(self)
        painter.setPen(QColor("#111827"))
        painter.drawLine(x, 0, x, self.height() - 1)


class LoudnessScale(QWidget):
    """Draw a shared LUFS scale aligned with the loudness bars."""

    def sizeHint(self) -> QSize:
        return QSize(200, 24)

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setPen(self.palette().color(QPalette.ColorRole.Text))
        baseline = 2
        painter.drawLine(0, baseline, self.width() - 1, baseline)
        for lufs in range(round(LOUDNESS_MINIMUM), round(LOUDNESS_MAXIMUM) + 1, 10):
            x = round(
                (lufs - LOUDNESS_MINIMUM)
                / (LOUDNESS_MAXIMUM - LOUDNESS_MINIMUM)
                * (self.width() - 1)
            )
            painter.drawLine(x, baseline, x, baseline + 4)
            text = f"{lufs} LUFS" if lufs == LOUDNESS_MAXIMUM else str(lufs)
            bounds = painter.fontMetrics().boundingRect(text)
            text_x = max(0, min(self.width() - bounds.width(), x - bounds.width() // 2))
            painter.drawText(text_x, baseline + 4 + bounds.height(), text)


def _loudness_text(lufs: float, target_lufs: float) -> str:
    delta = lufs - target_lufs
    direction = "above target" if delta > 0 else "below target" if delta < 0 else "on target"
    detail = f"{abs(delta):.1f} LUFS {direction}" if delta else direction
    return f"{lufs:.1f} LUFS ({detail})"


def _loudness_bar_color(lufs: float, target_lufs: float) -> QColor:
    delta = abs(lufs - target_lufs)
    if delta <= LOUDNESS_YELLOW_DELTA:
        return _interpolate_color(
            LOUDNESS_TARGET_GREEN,
            LOUDNESS_WARNING_YELLOW,
            delta / LOUDNESS_YELLOW_DELTA,
        )
    return _interpolate_color(
        LOUDNESS_WARNING_YELLOW,
        LOUDNESS_WARNING_RED,
        min((delta - LOUDNESS_YELLOW_DELTA) / (LOUDNESS_RED_DELTA - LOUDNESS_YELLOW_DELTA), 1.0),
    )
