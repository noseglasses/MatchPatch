"""Preset-table legend dialog construction."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from matchpatch.gui.help import HelpId
from matchpatch.gui.preset_table import (
    BAD_LUFS_ROW_BACKGROUND,
    IGNORED_SNAPSHOT_BACKGROUND,
    NORMALIZATION_FOCUS_BACKGROUND,
    NORMALIZATION_FOCUS_BLUE,
    PROCESSED_SNAPSHOT_BACKGROUND,
)
from matchpatch.gui.table_roles import (
    IGNORE_REASON_COMPARISON,
    IGNORE_REASON_PRESET,
    IGNORE_REASON_REGEX,
)


def build_preset_table_legend_dialog(
    *,
    parent: QWidget,
    ignore_reason_icons: Mapping[str, QIcon],
) -> QDialog:
    dialog = QDialog(parent)
    dialog.setWindowTitle("Preset table legend")
    dialog.setProperty("help_id", HelpId.SNAPSHOTS_SOLOS_IGNORED)
    layout = QVBoxLayout(dialog)

    marker_heading = QLabel("Snapshot markers", dialog)
    marker_font = marker_heading.font()
    marker_font.setBold(True)
    marker_heading.setFont(marker_font)
    layout.addWidget(marker_heading)

    grid = QGridLayout()
    grid.setColumnStretch(1, 1)
    marker_rows: tuple[tuple[QLabel, str], ...] = (
        (
            _legend_star_label(dialog),
            "Solo snapshot: solo gain bump applies; normal loudness matching is skipped.",
        ),
        (
            _legend_ignore_icon_label(IGNORE_REASON_PRESET, dialog, ignore_reason_icons),
            "Ignored because the whole preset is unchecked.",
        ),
        (
            _legend_ignore_icon_label(IGNORE_REASON_COMPARISON, dialog, ignore_reason_icons),
            "Ignored because comparison with another Helix file found no relevant snapshot changes.",
        ),
        (
            _legend_ignore_icon_label(IGNORE_REASON_REGEX, dialog, ignore_reason_icons),
            "Ignored because the snapshot name matches the ignored-snapshot regex.",
        ),
    )
    for row, (symbol, text) in enumerate(marker_rows):
        symbol.setFixedSize(30, 24)
        symbol.setAlignment(Qt.AlignmentFlag.AlignCenter)
        description = QLabel(text, dialog)
        description.setWordWrap(True)
        grid.addWidget(symbol, row, 0, Qt.AlignmentFlag.AlignTop)
        grid.addWidget(description, row, 1)
    layout.addLayout(grid)

    color_heading = QLabel("Snapshot cell colors", dialog)
    color_heading.setFont(marker_font)
    layout.addWidget(color_heading)
    color_grid = QGridLayout()
    color_grid.setColumnStretch(1, 1)
    color_rows: tuple[tuple[QLabel, str], ...] = (
        (_legend_color_swatch(QColor("#ffffff"), dialog), "White: initial state."),
        (
            _legend_color_swatch(NORMALIZATION_FOCUS_BACKGROUND, dialog),
            "Light blue: preset in progress.",
        ),
        (
            _legend_color_swatch(
                NORMALIZATION_FOCUS_BACKGROUND,
                dialog,
                outlined=True,
            ),
            "Light blue with blue outline: snapshot in progress.",
        ),
        (
            _legend_color_swatch(PROCESSED_SNAPSHOT_BACKGROUND, dialog),
            "Light green: snapshot successfully normalized.",
        ),
        (
            _legend_color_swatch(BAD_LUFS_ROW_BACKGROUND, dialog),
            "Light red: snapshot normalization error.",
        ),
        (_legend_color_swatch(IGNORED_SNAPSHOT_BACKGROUND, dialog), "Grey: ignored."),
    )
    for row, (swatch, text) in enumerate(color_rows):
        description = QLabel(text, dialog)
        description.setWordWrap(True)
        color_grid.addWidget(swatch, row, 0, Qt.AlignmentFlag.AlignTop)
        color_grid.addWidget(description, row, 1)
    layout.addLayout(color_grid)

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dialog)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    return dialog


def _legend_star_label(parent: QWidget) -> QLabel:
    label = QLabel("<span style='color: #f59e0b;'>★</span>", parent)
    label.setObjectName("legendSoloIcon")
    label.setTextFormat(Qt.TextFormat.RichText)
    font = label.font()
    font.setPointSize(max(font.pointSize() + 4, QApplication.font().pointSize() + 4))
    label.setFont(font)
    return label


def _legend_ignore_icon_label(
    reason: str,
    parent: QWidget,
    ignore_reason_icons: Mapping[str, QIcon],
) -> QLabel:
    label = QLabel(parent)
    label.setObjectName(f"legendIgnoreIcon{reason}")
    label.setPixmap(ignore_reason_icons[reason].pixmap(18, 18))
    return label


def _legend_color_swatch(
    color: QColor,
    parent: QWidget,
    *,
    outlined: bool = False,
) -> QLabel:
    label = QLabel(parent)
    label.setObjectName("legendColorSwatch")
    pixmap = QPixmap(30, 18)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = pixmap.rect().adjusted(1, 1, -2, -2)
    painter.setBrush(color)
    painter.setPen(QPen(NORMALIZATION_FOCUS_BLUE if outlined else QColor("#d1d5db"), 2))
    painter.drawRoundedRect(rect, 2, 2)
    painter.end()
    label.setPixmap(pixmap)
    return label
