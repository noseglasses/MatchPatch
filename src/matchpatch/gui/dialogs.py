"""Help and About dialogs for the MatchPatch GUI."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
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

PROJECT_URL = "https://github.com/noseglasses/MatchPatch"
ASSETS_DIR = Path(__file__).resolve().parents[3] / "doc" / "assets"


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About MatchPatch")
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
                180,
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
            f'<p><a href="{PROJECT_URL}">{PROJECT_URL}</a></p>'
            "<p>Copyright © 2026 MatchPatch contributors.</p>"
            "<p>Open source software released under the MIT License.</p>"
            "<p>Keep backups of original processor files. Generated reamp files are "
            "intended for measurement workflows.</p>"
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
        self.setWindowIcon(
            QApplication.style().standardIcon(QStyle.StandardPixmap.SP_DialogHelpButton)
        )
        self.resize(680, 520)
        layout = QVBoxLayout(self)
        help_text = QTextBrowser()
        help_text.setOpenExternalLinks(True)
        help_text.setHtml(
            "<h2>Guided normalization</h2>"
            "<ol>"
            "<li>Choose a Helix <code>.hls</code> setlist or <code>.hlx</code> preset.</li>"
            "<li>Use <b>loopback</b> for testing without hardware. Use <b>hardware</b> "
            "when the Helix and native Windows audio environment are available.</li>"
            "<li>Expand <b>Advanced</b> and use its tabs to change preset selection, "
            "device settings, miscellaneous policy values, or inspect the log.</li>"
            "<li>Start normalization and follow the import dialogs for generated "
            "reamp and adjusted files.</li>"
            "</ol>"
            "<h3>Progress</h3>"
            "<p>An animated progress bar means MatchPatch is working on a phase whose "
            "duration cannot be estimated yet. Preset and snapshot measurements use "
            "determinate progress when totals are known.</p>"
            "<h3>Temporary files</h3>"
            "<p>Enable <b>Keep temporary files</b> to retain the measurement CSV. "
            "Its exact path appears in the Progress area.</p>"
            f'<p>More documentation: <a href="{PROJECT_URL}">{PROJECT_URL}</a></p>'
        )
        layout.addWidget(help_text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
