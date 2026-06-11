"""Help and About dialogs for the MatchPatch GUI."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QStyle,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from matchpatch import __version__
from matchpatch.gui.help import HelpId, resolve_help_url

PROJECT_URL = "https://github.com/noseglasses/MatchPatch"
ASSETS_DIR = Path(__file__).resolve().parents[3] / "docs" / "assets"


def _about_icon_blue(size: int) -> QColor:
    pixmap = (
        QApplication.style()
        .standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation)
        .pixmap(size, size)
    )
    image = pixmap.toImage()
    red_total = 0
    green_total = 0
    blue_total = 0
    count = 0
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            if color.alpha() <= 0:
                continue
            if 180 <= color.hue() <= 250 and color.saturation() >= 60 and color.value() >= 80:
                red_total += color.red()
                green_total += color.green()
                blue_total += color.blue()
                count += 1
    if count == 0:
        return QColor("#308cc6")
    return QColor(red_total // count, green_total // count, blue_total // count)


def _question_mark_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_about_icon_blue(64))
    painter.drawEllipse(4, 4, 56, 56)
    painter.setPen(QColor("#ffffff"))
    font = QFont()
    font.setBold(True)
    font.setPointSize(40)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "?")
    painter.end()
    return QIcon(pixmap)


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About MatchPatch")
        self.setProperty("help_id", HelpId.DOCS_INDEX)
        self.setWindowIcon(
            QApplication.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation)
        )
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        logo = QLabel()
        pixmap = QPixmap(str(ASSETS_DIR / "matchmatch-logo.png"))
        logo.setPixmap(
            pixmap.scaled(
                520,
                320,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(logo)
        details = QLabel(
            "<h2>MatchPatch</h2>"
            f"<p>Version {__version__}</p>"
            "<p>Automatic loudness alignment for audio-processor presets and snapshots.</p>"
            f'<p><a href="{resolve_help_url(HelpId.DOCS_INDEX).toString()}">'
            "Documentation</a></p>"
            f'<p><a href="{PROJECT_URL}">{PROJECT_URL}</a></p>'
            "<p>Copyright © 2026 MatchPatch contributors.</p>"
            "<p>Open source software released under the MIT License.</p>"
            "<p>Keep backups of original processor files. Generated measurement files are "
            "intended for measurement workflows only.</p>"
        )
        details.setOpenExternalLinks(True)
        details.setWordWrap(True)
        layout.addWidget(details)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class HelpDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("MatchPatch Help")
        self.setWindowIcon(_question_mark_icon())
        self.resize(680, 520)
        layout = QVBoxLayout(self)
        help_text = QTextBrowser()
        help_text.setOpenExternalLinks(True)
        help_text.setHtml(
            "<h2>Guided normalization</h2>"
            "<ol>"
            "<li>Open a Helix <code>.hls</code> setlist or <code>.hlx</code> preset from "
            "the toolbar.</li>"
            "<li>The default <b>hardware</b> backend steers and measures the connected Helix. "
            "Use <b>loopback</b> only for testing without hardware.</li>"
            "<li>Use the <b>Presets</b> panel to change preset selection. Expand "
            "<b>Advanced</b> to change device settings, miscellaneous policy values, "
            "or inspect the log.</li>"
            "<li>Start normalization and follow the import dialog for the generated measurement "
            "file.</li>"
            "<li>Use toolbar save or save-as to write the adjusted setlist or preset.</li>"
            "</ol>"
            "<h3>Progress</h3>"
            "<p>A pulsing green dot in the window footer means MatchPatch is working. "
            "The dot is grey while MatchPatch is idle and red after a measurement was "
            "cancelled. While presets are measured, a determinate progress pane shows "
            "the current preset and snapshot.</p>"
            "<h3>Temporary files</h3>"
            "<p>Enable <b>Keep temporary files</b> to retain the measurement CSV. "
            "Its exact path appears below the processing controls.</p>"
            f'<p>More documentation: <a href="{PROJECT_URL}">{PROJECT_URL}</a></p>'
        )
        layout.addWidget(help_text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
