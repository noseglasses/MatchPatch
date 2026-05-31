"""Two-tier header for compact snapshot columns."""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QPainter, QPaintEvent
from PySide6.QtWidgets import QHeaderView, QStyle, QStyleOptionHeader, QWidget


class SnapshotHeader(QHeaderView):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setMinimumHeight(48)

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        hint.setHeight(max(hint.height() * 2, 48))
        return hint

    def paintSection(self, painter: QPainter, rect: QRect, logical_index: int) -> None:
        if logical_index < 3:
            super().paintSection(painter, rect, logical_index)
            return

        lower = QRect(rect.x(), rect.y() + rect.height() // 2, rect.width(), rect.height() // 2)
        super().paintSection(painter, lower, logical_index)

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if self.count() <= 3:
            return

        left = self.sectionViewportPosition(3)
        right = self.sectionViewportPosition(self.count() - 1) + self.sectionSize(self.count() - 1)
        rect = QRect(left, 0, right - left, self.height() // 2)
        option = QStyleOptionHeader()
        option.rect = rect
        option.text = "Snapshots"
        option.textAlignment = Qt.AlignmentFlag.AlignCenter
        painter = QPainter(self.viewport())
        self.style().drawControl(QStyle.ControlElement.CE_Header, option, painter, self)
