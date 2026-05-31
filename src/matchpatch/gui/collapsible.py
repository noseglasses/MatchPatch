"""Disclosure-style collapsible sections for compact GUI layouts."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QPushButton, QVBoxLayout, QWidget


class CollapsibleSection(QWidget):
    def __init__(self, title: str, content: QWidget, *, expanded: bool = False) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.toggle_button = QPushButton()
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(expanded)
        self.toggle_button.setFlat(True)
        self.toggle_button.setStyleSheet("text-align: left; font-weight: bold; padding: 6px;")
        self.toggle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.content = QFrame()
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(8, 4, 8, 8)
        content_layout.addWidget(content)
        layout.addWidget(self.toggle_button)
        layout.addWidget(self.content)
        self.toggle_button.toggled.connect(self.set_expanded)
        self.title = title
        self.set_expanded(expanded)

    def is_expanded(self) -> bool:
        return self.toggle_button.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        self.toggle_button.setChecked(expanded)
        self.content.setVisible(expanded)
        marker = "v" if expanded else ">"
        self.toggle_button.setText(f"{marker} {self.title}")
