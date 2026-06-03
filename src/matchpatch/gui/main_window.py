"""Main MatchPatch GUI window."""

from __future__ import annotations

import csv
import json
import math
import re
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Iterator

from PySide6.QtCore import (
    QAbstractAnimation,
    QCoreApplication,
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
    QSize,
    QTimer,
)
from PySide6.QtGui import (
    QAction,
    QBrush,
    QCloseEvent,
    QColor,
    QFont,
    QIcon,
    QKeyEvent,
    QPainter,
    QPaintEvent,
    QPalette,
    QPen,
    QPixmap,
    QResizeEvent,
    QSyntaxHighlighter,
    Qt,
    QTextCharFormat,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGraphicsOpacityEffect,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from matchpatch.config import config_value, load_config
from matchpatch.devices import get_device_profile, list_device_profiles
from matchpatch.devices.base import PatchFileAdjustments
from matchpatch.gui.device_panels import HelixSettingsPanel
from matchpatch.gui.dialogs import ASSETS_DIR, AboutDialog, HelpDialog
from matchpatch.gui.snapshot_header import SnapshotHeader
from matchpatch.gui.worker import HardwareCheckWorker, NormalizationWorker
from matchpatch.normalize import (
    apply_config,
    parse_args,
    request_from_args,
)
from matchpatch.progress import ProgressEvent
from matchpatch.workflow import (
    ImportRequest,
    NormalizationRequest,
    NormalizationResult,
    export_adjusted_file,
)

GAIN_CORRECTION_PATTERN = re.compile(
    r"^\[GAIN\] (?P<patch>\d{2}[A-D]) (?P<label>.*?) \| "
    r"(?P<before>-?\d+(?:\.\d+)?) dB -> (?P<after>-?\d+(?:\.\d+)?) dB "
    r"\(Delta: (?P<delta>[+-]\d+(?:\.\d+)?) dB\)$"
)
GAIN_STABLE_PATTERN = re.compile(
    r"^\[GAIN\] (?P<patch>\d{2}[A-D]) (?P<label>.*?) \| "
    r"stable at (?P<after>-?\d+(?:\.\d+)?) dB "
    r"\(Delta: (?P<delta>[+-]\d+(?:\.\d+)?) dB\)$"
)
GAIN_BAD_LUFS_PATTERN = re.compile(
    r"^\[GAIN\] (?P<patch>\d{2}[A-D]) (?P<label>.*?) \| bad LUFS(?: \(.*\))?$"
)
BAD_LUFS_ROW_BACKGROUND = QColor("#fee2e2")
HELIX_NAME_PATTERN = re.compile(r"""^[A-Za-z0-9\-_+=!@#$&()?:'",./ ]*$""")
HELIX_NAME_CHAR_PATTERN = re.compile(r"""[A-Za-z0-9\-_+=!@#$&()?:'",./ ]""")
PRESET_TABLE_CSV_DELIMITER = "|"
PRESET_TABLE_ATTENTION_ROLE = Qt.ItemDataRole.UserRole + 1
PROCESSING_DOT_GREY = "#9ca3af"
PROCESSING_DOT_GREEN = "#16a34a"
PROCESSING_DOT_RED = "#dc2626"
LOUDNESS_MINIMUM = -60.0
LOUDNESS_MAXIMUM = 0.0
LOUDNESS_SCALE = 10
LOUDNESS_YELLOW_DELTA = 3.0
LOUDNESS_RED_DELTA = 6.0
LOUDNESS_TARGET_GREEN = QColor(PROCESSING_DOT_GREEN)
LOUDNESS_WARNING_YELLOW = QColor("#eab308")
LOUDNESS_WARNING_RED = QColor("#dc2626")
PHASE_ICON = {
    "ready": QStyle.StandardPixmap.SP_DialogApplyButton,
    "starting": QStyle.StandardPixmap.SP_MediaPlay,
    "preparing_measurement": QStyle.StandardPixmap.SP_BrowserReload,
    "waiting_for_measurement_import": QStyle.StandardPixmap.SP_MediaPause,
    "measuring": QStyle.StandardPixmap.SP_ComputerIcon,
    "applying": QStyle.StandardPixmap.SP_BrowserReload,
    "completed": QStyle.StandardPixmap.SP_DialogApplyButton,
    "waiting_for_adjusted_import": QStyle.StandardPixmap.SP_MediaPause,
    "error": QStyle.StandardPixmap.SP_MessageBoxWarning,
    "cancelling": QStyle.StandardPixmap.SP_MessageBoxWarning,
    "normalization_cancelled_by_user": QStyle.StandardPixmap.SP_MessageBoxWarning,
}
IN_PROGRESS_PHASES = {
    "starting",
    "preparing_measurement",
    "waiting_for_measurement_import",
    "measuring",
    "applying",
    "waiting_for_adjusted_import",
    "cancelling",
}


class SaveCancelled(Exception):
    """Raised internally when the user cancels a save operation."""


class AttentionFrameDelegate(QStyledItemDelegate):
    """Draw an attention frame around cells marked by the window."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        super().paint(painter, option, index)
        if not index.data(PRESET_TABLE_ATTENTION_ROLE):
            return

        painter.save()
        painter.setPen(QPen(QColor("#dc2626"), 3))
        painter.drawRect(option.rect.adjusted(1, 1, -2, -2))
        painter.restore()


def _phase_text(phase: str) -> str:
    if phase == "normalization_cancelled_by_user":
        return "Normalization cancelled by user"
    text = phase.replace("_", " ").title()
    return f"{text}..." if phase in IN_PROGRESS_PHASES else text


def _normalization_icon() -> QIcon:
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#475569"))
    painter.drawRoundedRect(5, 22, 22, 2, 1, 1)
    painter.drawRoundedRect(5, 8, 2, 16, 1, 1)
    for x, y, height, color in (
        (10, 15, 7, "#38bdf8"),
        (15, 11, 11, "#22c55e"),
        (20, 7, 15, "#f59e0b"),
    ):
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(x, y, 4, height, 1, 1)
    painter.end()
    return QIcon(pixmap)


def _advanced_icon() -> QIcon:
    pixmap = QPixmap(56, 56)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    font = QFont(QApplication.font())
    font.setPixelSize(50)
    painter.setFont(font)
    painter.setPen(QColor("#475569"))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "⚙")
    painter.end()
    return QIcon(pixmap)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MatchPatch")
        self.setWindowIcon(QIcon(str(ASSETS_DIR / "matchmatch-icon.png")))
        self.setMinimumWidth(620)
        screen = QApplication.primaryScreen()
        available_height = screen.availableGeometry().height() if screen is not None else 800
        self.resize(820, min(760, max(560, available_height - 100)))
        self.hardware_check_worker: HardwareCheckWorker | None = None
        self.worker: NormalizationWorker | None = None
        self.completed_request: NormalizationRequest | None = None
        self.completed_result: NormalizationResult | None = None
        self.device_panels: dict[str, HelixSettingsPanel] = {}
        self.snapshot_count = 4
        self.preset_snapshot_positions: dict[str, int] = {}
        self._adjusted_presets: set[str] = set()
        self._preset_table_modified = False
        self._preset_table_clean_signature: tuple[tuple[str, ...], ...] = ()
        self._loaded_input_path = ""
        self._preset_load_discard_confirmed = False
        self._manual_cell_editor: QLineEdit | None = None
        self._manual_cell_target: tuple[int, int] | None = None
        self.log_entries: list[tuple[str, str, str]] = []
        self._processing_dot_green = False

        self.input_path = QLineEdit()
        self.output_path = QLineEdit()
        self.backend = QComboBox()
        self.backend.addItems(["hardware", "loopback", "simulated"])
        self.backend.currentTextChanged.connect(self.backend_changed)
        self._build_toolbar()
        content = QWidget()
        self.content = content
        scroll = QScrollArea()
        self.scroll_area = scroll
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        self.setCentralWidget(scroll)
        self._build_footer()
        self._build_hardware_check_overlay()
        layout = QVBoxLayout(content)
        layout.addWidget(self._build_preset_advanced_splitter(), 1)
        layout.addWidget(self._build_progress())
        layout.addWidget(self._build_retained_csv())
        layout.addStretch()
        self._set_phase("ready")
        self._populate_devices()
        self.load_defaults()
        self._refresh_file_actions()
        QTimer.singleShot(0, self._resize_to_initial_content)

    def _build_hardware_check_overlay(self) -> None:
        overlay = QWidget(self)
        overlay.setObjectName("hardwareCheckOverlay")
        overlay.setAutoFillBackground(True)
        overlay.setStyleSheet(
            "QWidget#hardwareCheckOverlay {"
            "background-color: rgba(15, 23, 42, 170);"
            "}"
            "QWidget#hardwareCheckPanel {"
            "background: #ffffff;"
            "border: 1px solid #cbd5e1;"
            "border-radius: 6px;"
            "}"
            "QLabel#hardwareCheckTitle {"
            "font-weight: 600;"
            "color: #0f172a;"
            "}"
        )
        overlay.hide()

        outer = QVBoxLayout(overlay)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.addStretch()

        panel = QWidget(overlay)
        panel.setObjectName("hardwareCheckPanel")
        panel.setFixedWidth(340)
        panel.setMinimumHeight(150)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(20, 20, 20, 20)
        panel_layout.setSpacing(12)

        title = QLabel("Checking backend availability...")
        title.setObjectName("hardwareCheckTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail = QLabel("Looking for a suitable audio processor and MIDI output.")
        detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail.setWordWrap(True)
        progress = QProgressBar()
        progress.setRange(0, 0)
        progress.setTextVisible(False)
        progress.setFixedHeight(10)

        panel_layout.addWidget(title)
        panel_layout.addWidget(detail)
        panel_layout.addWidget(progress)
        outer.addWidget(panel, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch()

        self.hardware_check_overlay = overlay

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("File", self)
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(18, 18))
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)

        self.open_action = QAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton),
            "Open",
            self,
        )
        self.open_action.setToolTip("Open a Helix setlist or preset file.")
        self.open_action.triggered.connect(self.browse_input)
        toolbar.addAction(self.open_action)

        self.save_action = QAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton),
            "Save",
            self,
        )
        self.save_action.setToolTip("Save changes to the active Helix file.")
        self.save_action.triggered.connect(self.save_active_file)
        toolbar.addAction(self.save_action)

        self.save_as_action = QAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton),
            "Save As",
            self,
        )
        self.save_as_action.setToolTip("Save the active Helix file under a new name.")
        self.save_as_action.triggered.connect(self.save_active_file_as)
        toolbar.addAction(self.save_as_action)

        self.normalization_separator_action = toolbar.addSeparator()
        self.start_button = QToolButton(self)
        self.start_button.setIcon(_normalization_icon())
        self.start_button.setToolTip("Start the guided preset-normalization workflow.")
        self.start_button.clicked.connect(self.start_normalization)
        self.cancel_button = QToolButton(self)
        self.cancel_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton)
        )
        self.cancel_button.setToolTip("Stop the currently running normalization workflow.")
        self.cancel_button.clicked.connect(self.cancel_normalization)
        self.start_cancel_stack = QStackedWidget(self)
        self.start_cancel_stack.addWidget(self.start_button)
        self.start_cancel_stack.addWidget(self.cancel_button)
        self.normalization_action = toolbar.addWidget(self.start_cancel_stack)

        help_spacer = QWidget(self)
        help_spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.help_spacer_action = toolbar.addWidget(help_spacer)

        self.device = QComboBox(self)
        self.device.setToolTip("The audio processor profile used by this workflow.")
        self.device.setAccessibleName("Device")
        self.device.currentIndexChanged.connect(self.device_changed)
        self.device_action = toolbar.addWidget(self.device)

        self.advanced_button = QToolButton(self)
        self.advanced_button.setIcon(_advanced_icon())
        self.advanced_button.setCheckable(True)
        self.advanced_button.setToolTip(
            "Show less frequently changed settings and diagnostic details."
        )
        self.advanced_button.setAccessibleName("Advanced")
        self.advanced_button.toggled.connect(self._set_advanced_visible)
        self.advanced_action = toolbar.addWidget(self.advanced_button)
        toolbar.addSeparator()

        self.help_action = QAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogHelpButton),
            "Help",
            self,
        )
        self.help_action.setToolTip("Open the guided MatchPatch usage instructions.")
        self.help_action.triggered.connect(self.show_help)
        toolbar.addAction(self.help_action)

        self.about_action = QAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation),
            "About",
            self,
        )
        self.about_action.setToolTip(
            "Show project version, license, and repository information."
        )
        self.about_action.triggered.connect(self.show_about)
        toolbar.addAction(self.about_action)

        square_button_size = toolbar.iconSize().width() + 14
        for button in (self.start_button, self.cancel_button):
            button.setAutoRaise(True)
            button.setIconSize(toolbar.iconSize())
            button.setFixedSize(square_button_size, square_button_size)
        self.advanced_button.setAutoRaise(True)
        self.advanced_button.setIconSize(QSize(40, 40))
        self.advanced_button.setFixedSize(46, 46)
        self.start_cancel_stack.setFixedSize(square_button_size, square_button_size)
        for action in (self.help_action, self.about_action):
            button = toolbar.widgetForAction(action)
            if button is not None:
                button.setFixedSize(square_button_size, square_button_size)

    def _build_preset_advanced_splitter(self) -> QSplitter:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.preset_advanced_splitter = splitter
        splitter.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_presets())
        splitter.addWidget(self._build_advanced())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        return splitter

    def _build_presets(self) -> QWidget:
        content = QWidget()
        content.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        self.preset_hint = QLabel("Choose an .hls or .hlx file.")
        self.preset_hint.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.preset_empty_state = self._build_preset_empty_state()
        self.preset_table = ContentHeightTableWidget()
        self.preset_table.setHorizontalHeader(SnapshotHeader(self.preset_table))
        self.preset_table.setItemDelegate(AttentionFrameDelegate(self.preset_table))
        self.preset_table.verticalHeader().hide()
        self.preset_table.setWordWrap(False)
        self.preset_table.setToolTip(
            "Select presets and inspect snapshot names and calculated output-gain adjustments."
        )
        self.preset_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._configure_snapshot_columns(self.snapshot_count)
        self.preset_table.cellDoubleClicked.connect(self._manual_table_cell_double_clicked)
        self.preset_table.itemChanged.connect(self._preset_item_changed)
        self.preset_table.setSortingEnabled(True)
        self.preset_table.setMinimumHeight(160)
        self.preset_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.preset_table.model().rowsInserted.connect(self._preset_table_size_changed)
        self.preset_table.model().rowsRemoved.connect(self._preset_table_size_changed)
        self.preset_table.model().modelReset.connect(self._preset_table_size_changed)
        self.preset_table_note = QLabel("Only non-empty presets are listed.")
        self.save_csv_button = QPushButton()
        self.save_csv_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
        )
        self.save_csv_button.setToolTip("Save the preset table as pipe-delimited CSV.")
        self.save_csv_button.clicked.connect(self.save_preset_table_csv)
        self.load_csv_button = QPushButton()
        self.load_csv_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton)
        )
        self.load_csv_button.setToolTip("Load preset-table content from pipe-delimited CSV.")
        self.load_csv_button.clicked.connect(self.load_preset_table_csv)
        csv_button_size = max(
            self.save_csv_button.sizeHint().height(),
            self.load_csv_button.sizeHint().height(),
        )
        for button in (self.save_csv_button, self.load_csv_button):
            button.setFixedSize(csv_button_size, csv_button_size)
            button.setEnabled(False)
        self.preset_csv_controls = QWidget()
        preset_csv_layout = QHBoxLayout(self.preset_csv_controls)
        preset_csv_layout.setContentsMargins(0, 0, 0, 0)
        preset_csv_layout.setSpacing(4)
        self.preset_csv_label = QLabel("CSV: ")
        preset_csv_layout.addWidget(self.preset_csv_label)
        preset_csv_layout.addWidget(self.load_csv_button)
        preset_csv_layout.addWidget(self.save_csv_button)
        self.single_slot = QLineEdit()
        self.single_slot.setPlaceholderText("Temporary slot, for example 12A")
        self.single_slot.hide()
        self.preset_header = QWidget()
        preset_header = QHBoxLayout(self.preset_header)
        preset_header.setContentsMargins(0, 0, 0, 0)
        preset_header.addWidget(self.preset_hint)
        preset_header.addStretch()
        self.select_all_button = QPushButton("Select all")
        self.select_all_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
        )
        self.select_all_button.setToolTip("Include every preset in this setlist.")
        self.select_all_button.clicked.connect(lambda: self.set_all_presets_checked(True))
        self.manual_adjustments = QCheckBox("Edit content")
        self.manual_adjustments.setToolTip(
            "Allow preset names, snapshot names, and gain adjustments to be edited manually."
        )
        self.manual_adjustments.toggled.connect(self._manual_adjustments_toggled)
        self.unselect_all_button = QPushButton("Unselect all")
        self.unselect_all_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogResetButton)
        )
        self.unselect_all_button.setToolTip("Exclude every preset in this setlist.")
        self.unselect_all_button.clicked.connect(lambda: self.set_all_presets_checked(False))
        self.select_diff_button = QPushButton("Select changed")
        self.select_diff_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton)
        )
        self.select_diff_button.setToolTip(
            "Select presets whose loudness-affecting content differs from another setlist."
        )
        self.select_diff_button.clicked.connect(self.select_diff_presets)
        preset_header.addWidget(self.select_all_button)
        preset_header.addWidget(self.unselect_all_button)
        preset_header.addWidget(self.select_diff_button)
        layout.addWidget(self.preset_header)
        layout.addWidget(self.preset_empty_state)
        layout.addWidget(self.preset_table)
        preset_table_note_row = QHBoxLayout()
        preset_table_note_row.addWidget(self.preset_table_note)
        preset_table_note_row.addStretch()
        preset_table_note_row.addWidget(self.manual_adjustments)
        preset_table_note_row.addWidget(self.preset_csv_controls)
        layout.addLayout(preset_table_note_row)
        layout.addWidget(self.single_slot)
        self.presets = content
        self._sync_preset_empty_state_height()
        self._show_preset_empty_state()
        return content

    def _build_preset_empty_state(self) -> QWidget:
        pane = QWidget()
        pane.setAutoFillBackground(True)
        pane.setStyleSheet("background: white;")
        pane.setMinimumHeight(160)
        pane.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(pane)
        layout.setContentsMargins(32, 4, 32, 4)
        layout.setSpacing(1)
        layout.addStretch(1)

        logo = QLabel()
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_pixmap = QPixmap(str(ASSETS_DIR / "matchmatch-logo.png"))
        if not logo_pixmap.isNull():
            logo.setPixmap(
                logo_pixmap.scaled(
                    720,
                    360,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        self.preset_empty_logo = logo
        layout.addWidget(logo)

        open_button = QToolButton()
        open_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
        open_button.setIconSize(QSize(72, 72))
        open_button.setText("Open setlist/preset file")
        open_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        open_button.setAutoRaise(True)
        open_button.setToolTip("Open a Helix setlist or preset file.")
        open_button.clicked.connect(self.browse_input)
        self.preset_empty_open_button = open_button
        layout.addWidget(open_button, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(1)
        return pane

    def _sync_preset_empty_state_height(self) -> None:
        table_height = max(
            self.preset_table.minimumHeight(),
            self.preset_table.horizontalHeader().sizeHint().height()
            + self.preset_table.verticalHeader().defaultSectionSize()
            * self.preset_table.MAX_VISIBLE_ROWS
            + self.preset_table.frameWidth() * 2,
        )
        row_height = max(
            self.preset_header.sizeHint().height(),
            self.preset_table_note.sizeHint().height(),
            self.preset_csv_controls.sizeHint().height(),
            self.manual_adjustments.sizeHint().height(),
        )
        spacing = self.presets.layout().spacing() if self.presets.layout() is not None else 0
        self.preset_empty_state.setMinimumHeight(table_height + row_height * 2 + spacing * 2)

    def _show_preset_empty_state(self) -> None:
        self.preset_header.hide()
        self.preset_empty_state.show()
        self.preset_table.hide()
        self.preset_table_note.hide()
        self.preset_csv_controls.hide()
        self.single_slot.hide()
        self.select_all_button.hide()
        self.unselect_all_button.hide()
        self.select_diff_button.hide()
        self.manual_adjustments.hide()
        self.presets.show()
        self._refresh_preset_advanced_splitter_visibility()

    def _show_loaded_preset_state(self, *, single_preset: bool) -> None:
        self.preset_empty_state.hide()
        self.preset_header.show()
        self.single_slot.hide()
        self.preset_table.show()
        self.preset_table.setColumnHidden(0, single_preset)
        self.preset_table_note.setVisible(not single_preset)
        self.preset_csv_controls.show()
        self.select_all_button.setVisible(not single_preset)
        self.unselect_all_button.setVisible(not single_preset)
        self.select_diff_button.setVisible(not single_preset)
        self.manual_adjustments.setVisible(not single_preset)
        self.manual_adjustments.setChecked(False)
        self.presets.show()
        self._refresh_preset_advanced_splitter_visibility()

    def _build_device_settings(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        self.device_stack = QStackedWidget()
        layout.addWidget(self.device_stack)
        self.device_settings = content
        return content

    def _build_progress(self) -> QWidget:
        pane = QWidget()
        self.progress_group = pane
        pane.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)
        self.current = QLabel("")
        self.preset_progress = QProgressBar()
        self.preset_progress.setRange(0, 1)
        self.measured_loudness = LoudnessBar()
        self.loudness_scale = LoudnessScale()
        meters = QWidget()
        meter_layout = QGridLayout(meters)
        meter_layout.setContentsMargins(0, 0, 0, 0)
        meter_layout.setHorizontalSpacing(8)
        meter_layout.setVerticalSpacing(2)
        self.measured_loudness_reading = QLabel()
        meter_layout.addWidget(self.measured_loudness_reading, 0, 0)
        meter_layout.addWidget(self.measured_loudness, 0, 1)
        meter_layout.addWidget(self.loudness_scale, 1, 1)
        meter_layout.setColumnStretch(1, 1)
        layout.addWidget(self.current)
        layout.addWidget(meters)
        layout.addWidget(self.preset_progress)
        self._reset_loudness_bars()
        pane.hide()
        return pane

    def _build_retained_csv(self) -> QWidget:
        pane = QWidget()
        self.retained_csv_pane = pane
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)
        self.retained_csv_label = _label(
            "Retained CSV", "Exact measurement CSV path when temporary files are retained."
        )
        self.retained_csv = QLineEdit()
        self.retained_csv.setReadOnly(True)
        layout.addWidget(self.retained_csv_label)
        layout.addWidget(self.retained_csv)
        pane.hide()
        return pane

    def _build_footer(self) -> None:
        self.phase_icon = QLabel()
        self.phase_icon.setFixedSize(16, 16)
        self.phase = QLabel()
        self.processing_dot = QLabel()
        self.processing_dot.setFixedSize(14, 14)
        self.processing_dot.setToolTip(
            "Grey when idle; pulses green while processing; red when a measurement was cancelled."
        )
        self.processing_dot_effect = QGraphicsOpacityEffect(self.processing_dot)
        self.processing_dot.setGraphicsEffect(self.processing_dot_effect)
        self.busy_animation = QPropertyAnimation(self.processing_dot_effect, b"opacity", self)
        self.busy_animation.setDuration(2000)
        self.busy_animation.setLoopCount(-1)
        self.busy_animation.setEasingCurve(QEasingCurve.Type.InOutSine)
        self.busy_animation.setKeyValueAt(0.0, 0.2)
        self.busy_animation.setKeyValueAt(0.5, 1.0)
        self.busy_animation.setKeyValueAt(1.0, 0.2)
        self._set_processing_dot(False)
        footer = self.statusBar()
        footer.setSizeGripEnabled(False)
        footer.addWidget(self.phase_icon)
        footer.addWidget(self.phase)
        footer.addPermanentWidget(self.processing_dot)

    def _build_log(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        filter_row = QHBoxLayout()
        filter_row.addWidget(
            _label("Minimum log level", "Hide log entries below the selected severity.")
        )
        self.log_level = QComboBox()
        self.log_level.addItems(["Debug", "Info", "Warning", "Error"])
        self.log_level.setCurrentText("Info")
        self.log_level.currentTextChanged.connect(self._refresh_log)
        filter_row.addWidget(self.log_level)
        filter_row.addStretch()
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(140)
        self.log_section = self.log
        layout.addLayout(filter_row)
        layout.addWidget(self.log)
        return content

    def _build_metadata(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        self.metadata_text = QTextEdit()
        self.metadata_text.setReadOnly(True)
        self.metadata_text.setMinimumHeight(180)
        self.metadata_text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.metadata_text.setFont(QFont("monospace"))
        self.metadata_highlighter = JsonSyntaxHighlighter(self.metadata_text.document())
        layout.addWidget(self.metadata_text)
        self._set_metadata({})
        return content

    def _build_advanced(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        self.advanced_tabs = CurrentPageHeightTabWidget()
        self.advanced_tabs.addTab(self._build_device_settings(), "Device")
        self.advanced_tabs.addTab(self._build_files(), "Files")
        self.advanced_tabs.addTab(self._build_lufs(), "LUFS")
        self.advanced_tabs.addTab(self._build_misc(), "Misc")
        self.advanced_tabs.addTab(self._build_metadata(), "Meta Data")
        self.advanced_tabs.addTab(self._build_log(), "Log")
        self.advanced_tabs.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.advanced_tabs.currentChanged.connect(self._schedule_resize_for_content)
        layout.addWidget(self.advanced_tabs)
        self.advanced = content
        self.advanced.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.advanced.setToolTip("Show less frequently changed settings and diagnostic details.")
        self.advanced.setVisible(self.advanced_button.isChecked())
        return self.advanced

    def _build_files(self) -> QWidget:
        content = QWidget()
        form = QFormLayout(content)
        self.config_path = QLineEdit()
        config_browse = QPushButton("Browse")
        config_browse.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
        config_browse.setToolTip("Choose an optional TOML configuration file.")
        config_browse.clicked.connect(self.browse_config)
        form.addRow(
            _label("Config file", "Optional TOML file providing saved MatchPatch defaults."),
            _path_row(self.config_path, config_browse),
        )
        self.reference_di = QLineEdit()
        reference_browse = QPushButton("Browse")
        reference_browse.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton)
        )
        reference_browse.setToolTip("Choose the clean DI WAV used for evaluation measurements.")
        reference_browse.clicked.connect(self.browse_reference)
        form.addRow(
            _label("Reference DI", "Clean guitar DI WAV replayed through each preset."),
            _path_row(self.reference_di, reference_browse),
        )
        self.keep_temp = QCheckBox()
        form.addRow(
            _label(
                "Keep temporary files",
                "Retain the measurement CSV for inspection after processing.",
            ),
            self.keep_temp,
        )
        return content

    def _set_advanced_visible(self, visible: bool) -> None:
        if hasattr(self, "advanced"):
            self.advanced.setVisible(visible)
            self._refresh_preset_advanced_splitter_visibility()
            if visible:
                self._fit_advanced_splitter_width()
            self._schedule_resize_for_content()

    def _refresh_preset_advanced_splitter_visibility(self) -> None:
        if hasattr(self, "preset_advanced_splitter") and hasattr(self, "advanced"):
            self.preset_advanced_splitter.setVisible(
                not self.presets.isHidden() or not self.advanced.isHidden()
            )

    def _fit_advanced_splitter_width(self) -> None:
        if not hasattr(self, "preset_advanced_splitter") or self.presets.isHidden():
            return
        advanced_width = self.advanced.sizeHint().width()
        splitter_width = self.preset_advanced_splitter.width()
        if advanced_width <= 0 or splitter_width <= 0:
            return
        self.preset_advanced_splitter.setSizes(
            [max(0, splitter_width - advanced_width), advanced_width]
        )

    def _build_misc(self) -> QWidget:
        content = QWidget()
        form = QFormLayout(content)
        self.snapshot_count_input = QSpinBox()
        self.snapshot_count_input.setRange(1, 8)
        self.snapshot_count_input.setValue(self.snapshot_count)
        self.snapshot_count_input.valueChanged.connect(self._snapshot_count_changed)
        form.addRow(
            _label("Snapshots", "Number of snapshots to measure and normalize."),
            self.snapshot_count_input,
        )
        return content

    def _build_lufs(self) -> QWidget:
        content = QWidget()
        form = QFormLayout(content)
        self.target_lufs = QLineEdit("-16.0")
        form.addRow(
            _label("Target LUFS", "Desired loudness used to calculate snapshot gain corrections."),
            self.target_lufs,
        )
        self.solo_gain_bump_db = QLineEdit("3.0")
        form.addRow(
            _label(
                "Solo boost (dB)", "Additional output gain added to snapshots identified as solos."
            ),
            self.solo_gain_bump_db,
        )
        self.solo_regex = QLineEdit(r"(?i)\bsolo\b")
        self.solo_regex.setToolTip(
            "Case-insensitive regular expression used to identify solo snapshots."
        )
        form.addRow(
            _label(
                "Solo snapshot regex", "Regular expression used to identify solo snapshot names."
            ),
            self.solo_regex,
        )
        return content

    def _populate_devices(self) -> None:
        for profile in list_device_profiles():
            self.device.addItem(profile.display_name, profile.name)
            if profile.name == "helix":
                panel = HelixSettingsPanel(self.backend)
                self.device_panels[profile.name] = panel
                self.device_stack.addWidget(panel)

    def browse_input(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose patch file", filter="Patches (*.hls *.hlx)"
        )
        if not path or path == self.input_path.text():
            return
        if not self._confirm_discard_preset_table_changes():
            return
        self._preset_load_discard_confirmed = True
        self.input_path.setText(path)
        try:
            self.load_assignments()
        finally:
            self._preset_load_discard_confirmed = False

    def _confirm_discard_preset_table_changes(self) -> bool:
        if not self._preset_table_has_unsaved_changes():
            return True
        answer = QMessageBox.question(
            self,
            "Discard preset table changes",
            "The preset table contains unsaved changes. Opening another preset or setlist "
            "file will discard them.\n\nDiscard the changes and continue?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer in {QMessageBox.StandardButton.Discard, QMessageBox.StandardButton.Yes}

    def _choose_save_as_path(self, *, accept_label: str = "Save as") -> Path | None:
        suffix = Path(self.input_path.text()).suffix.lower()
        if suffix not in {".hls", ".hlx"}:
            self.show_error("Open a Helix .hls or .hlx file before saving")
            return None
        file_filter = (
            f"Helix {suffix} (*{suffix})" if suffix in {".hls", ".hlx"} else "Patches (*.hls *.hlx)"
        )
        dialog = QFileDialog(self, "Save Helix file as")
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog)
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptOpen)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        dialog.setNameFilter(file_filter)
        dialog.setLabelText(QFileDialog.DialogLabel.Accept, accept_label)
        path = dialog.selectedFiles()[0] if dialog.exec() and dialog.selectedFiles() else ""
        if not path:
            return None
        save_path = Path(path)
        if save_path.suffix.lower() != suffix:
            self.show_error(f"Saved file must use the {suffix} extension")
            return None
        return save_path

    def browse_output(self) -> None:
        path = self._choose_save_as_path(accept_label="Save")
        if path is not None:
            self.output_path.setText(str(path))

    def save_preset_table_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save preset table CSV",
            filter="Preset table CSV (*.csv)",
        )
        if not path:
            return

        csv_path = Path(path)
        if csv_path.suffix.lower() != ".csv":
            csv_path = csv_path.with_suffix(".csv")

        try:
            with csv_path.open("w", encoding="utf-8", newline="") as csv_file:
                writer = csv.writer(csv_file, delimiter=PRESET_TABLE_CSV_DELIMITER)
                writer.writerow(self._preset_table_csv_headers())
                for row in range(self.preset_table.rowCount()):
                    writer.writerow(self._preset_table_csv_row(row))
        except OSError as exc:
            self.show_error(f"Could not save preset table CSV: {exc}")
            return

        self._log(f"Preset table CSV saved: {csv_path}", "success")

    def load_preset_table_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load preset table CSV",
            filter="Preset table CSV (*.csv)",
        )
        if not path:
            return

        try:
            before = self._preset_table_content_signature()
            adjusted_before = set(self._adjusted_presets)
            with self._sorting_paused():
                accepted, errors = self._load_preset_table_csv(Path(path))
        except OSError as exc:
            self.show_error(f"Could not load preset table CSV: {exc}")
            return
        if self._preset_table_content_signature() != before:
            self._mark_preset_table_modified()
        else:
            self._adjusted_presets = adjusted_before
            self._refresh_file_actions()

        for error in errors:
            self._log(error, "error")
        if errors:
            QMessageBox.critical(self, "Preset table CSV errors", "\n".join(errors))
        self._log(f"Preset table CSV loaded: {path} ({accepted} row(s) applied)", "success")

    def _load_preset_table_csv(self, path: Path) -> tuple[int, list[str]]:
        errors: list[str] = []
        accepted = 0
        headers = self._preset_table_csv_headers()
        current_rows = {
            item.text(): row
            for row in range(self.preset_table.rowCount())
            if (item := self.preset_table.item(row, 1)) is not None
        }

        with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
            reader = csv.reader(csv_file, delimiter=PRESET_TABLE_CSV_DELIMITER)
            for line_number, row in enumerate(reader, start=1):
                if line_number == 1 and row == headers:
                    continue
                if not row or all(not cell for cell in row):
                    continue
                parsed = self._parse_preset_table_csv_row(
                    row,
                    line_number,
                    headers,
                    current_rows,
                    errors,
                )
                if parsed is None:
                    continue
                table_row, preset_name, snapshot_names, adjustments = parsed
                self._apply_preset_table_csv_row(
                    table_row,
                    preset_name,
                    snapshot_names,
                    adjustments,
                )
                accepted += 1

        return accepted, errors

    def _parse_preset_table_csv_row(
        self,
        row: list[str],
        line_number: int,
        headers: list[str],
        current_rows: dict[str, int],
        errors: list[str],
    ) -> tuple[int, str, list[str], list[tuple[str, float]]] | None:
        expected_columns = len(headers)
        if len(row) != expected_columns:
            errors.append(
                f"Line {line_number}: expected {expected_columns} columns, got {len(row)}."
            )
            return None

        preset_id = row[0]
        table_row = current_rows.get(preset_id)
        if table_row is None:
            errors.append(
                f"Line {line_number}: preset ID {preset_id!r} is not listed in the current table."
            )
            return None

        preset_name = row[1]
        try:
            self._validate_helix_name(preset_name, self._preset_name_max_length())
        except ValueError as exc:
            errors.append(f"Line {line_number}: preset name is invalid: {exc}.")
            return None

        snapshot_names: list[str] = []
        adjustments: list[tuple[str, float]] = []
        for snapshot_index in range(self.snapshot_count):
            name = row[2 + snapshot_index * 2]
            adjustment_text = row[3 + snapshot_index * 2]
            try:
                self._validate_helix_name(name, self._snapshot_name_max_length())
            except ValueError as exc:
                errors.append(
                    f"Line {line_number}: snapshot {snapshot_index + 1} name is invalid: {exc}."
                )
                return None
            try:
                adjustment = float(adjustment_text)
            except ValueError:
                errors.append(
                    f"Line {line_number}: snapshot {snapshot_index + 1} adjustment "
                    f"is not a floating point number: {adjustment_text!r}."
                )
                return None
            if not math.isfinite(adjustment):
                errors.append(
                    f"Line {line_number}: snapshot {snapshot_index + 1} adjustment "
                    f"is not finite: {adjustment_text!r}."
                )
                return None
            snapshot_names.append(name)
            adjustments.append((adjustment_text, adjustment))

        return table_row, preset_name, snapshot_names, adjustments

    def _apply_preset_table_csv_row(
        self,
        row: int,
        preset_name: str,
        snapshot_names: list[str],
        adjustments: list[tuple[str, float]],
    ) -> None:
        preset_item = self.preset_table.item(row, 2)
        if preset_item is None:
            preset_item = QTableWidgetItem()
            self.preset_table.setItem(row, 2, preset_item)
        preset_item.setText(preset_name)
        preset_item.setData(Qt.ItemDataRole.UserRole, tuple(snapshot_names))
        for snapshot_index, (adjustment_text, adjustment) in enumerate(adjustments):
            name_item = self.preset_table.item(row, 3 + snapshot_index * 2)
            adjustment_item = self.preset_table.item(row, 4 + snapshot_index * 2)
            if name_item is None:
                name_item = QTableWidgetItem()
                self.preset_table.setItem(row, 3 + snapshot_index * 2, name_item)
            if adjustment_item is None:
                adjustment_item = QTableWidgetItem()
                self.preset_table.setItem(row, 4 + snapshot_index * 2, adjustment_item)
            self._set_snapshot_name(
                name_item,
                snapshot_names[snapshot_index],
                self._is_solo_snapshot_name(snapshot_names[snapshot_index]),
            )
            self._set_adjustment_value(adjustment_item, adjustment_text, adjustment)

        patch_item = self.preset_table.item(row, 1)
        if patch_item is not None:
            self._adjusted_presets.add(patch_item.text())

    def _preset_table_csv_headers(self) -> list[str]:
        headers = ["preset_id", "preset_name"]
        for snapshot in range(1, self.snapshot_count + 1):
            headers.extend([f"snapshot_{snapshot}_name", f"snapshot_{snapshot}_adjustment"])
        return headers

    def _preset_table_csv_row(self, row: int) -> list[str]:
        values = [
            self.preset_table.item(row, 1).text() if self.preset_table.item(row, 1) else "",
            self.preset_table.item(row, 2).text() if self.preset_table.item(row, 2) else "",
        ]
        for column in range(3, self.preset_table.columnCount(), 2):
            name = self.preset_table.item(row, column)
            adjustment = self.preset_table.item(row, column + 1)
            values.extend(
                [
                    name.text() if name is not None else "",
                    adjustment.text() if adjustment is not None else "",
                ]
            )
        return values

    def _is_solo_snapshot_name(self, name: str) -> bool:
        try:
            solo_pattern = re.compile(self.solo_regex.text())
        except re.error:
            return False
        return solo_pattern.search(name) is not None

    def show_help(self) -> None:
        HelpDialog(self).exec()

    def show_about(self) -> None:
        AboutDialog(self).exec()

    def browse_reference(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose reference DI", filter="Audio (*.wav)")
        if path:
            self.reference_di.setText(path)

    def browse_config(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose config", filter="TOML (*.toml)")
        if path:
            self.config_path.setText(path)
            self.load_defaults()

    def device_changed(self) -> None:
        name = self.device.currentData()
        panel = self.device_panels.get(name)
        if panel is not None:
            self.device_stack.setCurrentWidget(panel)
        self.load_defaults()

    def backend_changed(self) -> None:
        if self.backend.currentText() == "loopback":
            self.device_settings.setToolTip(
                "Audio and MIDI settings are editable but unused by the loopback backend."
            )
        else:
            self.device_settings.setToolTip("")

    def load_defaults(self) -> None:
        if not self.device.currentData():
            return

        try:
            config = load_config(self.config_path.text().strip() or None)
            self.backend.setCurrentText(
                config_value(config, "normalize", "backend", default="hardware")
            )
            args = apply_config(parse_args(self._base_argv("placeholder.hls")))
        except Exception as exc:  # noqa: BLE001
            self.show_error(str(exc))
            return

        self.backend.setCurrentText(args.backend)
        self.reference_di.setText(str(args.reference_di))
        self.target_lufs.setText(str(args.target_lufs))
        self.solo_gain_bump_db.setText(str(args.policy.solo_gain_bump_db))
        self.solo_regex.setText(args.policy.solo_regex)
        profile = get_device_profile(args.device)
        self.snapshot_count_input.setMaximum(getattr(profile, "max_snapshot_count", None) or 999)
        self.snapshot_count_input.setValue(args.policy.snapshot_count)
        panel = self.device_panels.get(args.device)
        if panel is not None:
            panel.populate(args)
        self.backend_changed()

    def load_assignments(self) -> None:
        path = Path(self.input_path.text())
        if (
            not self._preset_load_discard_confirmed
            and self._loaded_input_path
            and str(path) != self._loaded_input_path
            and not self._confirm_discard_preset_table_changes()
        ):
            self.input_path.setText(self._loaded_input_path)
            return

        self._discard_completed_export()
        self.preset_snapshot_positions.clear()
        self._clear_bad_lufs_highlights()
        self._load_metadata()
        is_single_preset = path.suffix.lower() == ".hlx"
        self._show_loaded_preset_state(single_preset=is_single_preset)
        self._set_preset_csv_buttons_enabled(False)
        self.presets.updateGeometry()
        self._schedule_resize_for_content()

        if path.suffix.lower() == ".hlx":
            try:
                profile = get_device_profile(self.device.currentData())
                handler = profile.create_patch_file_handler(Path(__file__).resolve().parents[3])
                handler.validate_input(path)
                assignments = handler.list_assignments(path)
            except Exception as exc:  # noqa: BLE001
                self._show_preset_empty_state()
                self.presets.updateGeometry()
                self._schedule_resize_for_content()
                self.show_error(str(exc))
                return

            self._adjusted_presets.clear()
            self._populate_single_preset_table(path, assignments[0] if assignments else None)
            self._loaded_input_path = str(path)
            self._set_active_file(path)
            self._reset_preset_table_modified()
            self._refresh_file_actions()
            self._set_preset_csv_buttons_enabled(self.preset_table.rowCount() > 0)
            self.preset_hint.setText(
                "Enter the temporary Helix slot used during measurement in the Preset column."
            )
            QTimer.singleShot(0, self._fit_advanced_splitter_width)
            self.presets.updateGeometry()
            self._schedule_resize_for_content()
            return

        try:
            profile = get_device_profile(self.device.currentData())
            handler = profile.create_patch_file_handler(Path(__file__).resolve().parents[3])
            handler.validate_input(path)
            with self._sorting_paused():
                self._adjusted_presets.clear()
                self.preset_table.setRowCount(0)
                for assignment in handler.list_assignments(path):
                    row = self.preset_table.rowCount()
                    self.preset_table.insertRow(row)
                    selected = QTableWidgetItem()
                    selected.setCheckState(Qt.CheckState.Checked)
                    self.preset_table.setItem(row, 0, selected)
                    self.preset_table.setItem(row, 1, QTableWidgetItem(assignment.device_patch))
                    self.preset_table.setItem(row, 2, QTableWidgetItem(assignment.name))
                    self._clear_preset_adjustments(row)
                    self._set_snapshot_names(row, assignment.snapshot_names)
                self._refresh_preset_table_editable_flags()
        except Exception as exc:  # noqa: BLE001
            self._show_preset_empty_state()
            self.presets.updateGeometry()
            self._schedule_resize_for_content()
            self.show_error(str(exc))
            return

        self._loaded_input_path = str(path)
        self._set_active_file(path)
        self._reset_preset_table_modified()
        self._refresh_file_actions()
        self.preset_hint.setText("Select the presets to normalize.")
        self._set_preset_csv_buttons_enabled(self.preset_table.rowCount() > 0)
        QTimer.singleShot(0, self._fit_advanced_splitter_width)
        self._schedule_resize_for_content()

    def _set_preset_csv_buttons_enabled(self, enabled: bool) -> None:
        if hasattr(self, "load_csv_button"):
            self.load_csv_button.setEnabled(enabled)
        if hasattr(self, "save_csv_button"):
            self.save_csv_button.setEnabled(enabled)

    def _populate_single_preset_table(self, path: Path, assignment: object | None = None) -> None:
        preset_name = str(getattr(assignment, "name", "") or path.stem)
        snapshot_names = getattr(assignment, "snapshot_names", ())
        if not isinstance(snapshot_names, tuple):
            snapshot_names = tuple(snapshot_names)
        with self._sorting_paused():
            self.preset_table.setRowCount(0)
            self.preset_table.insertRow(0)
            selected = QTableWidgetItem()
            selected.setCheckState(Qt.CheckState.Checked)
            self.preset_table.setItem(0, 0, selected)
            self.preset_table.setItem(0, 1, QTableWidgetItem())
            self.preset_table.setItem(0, 2, QTableWidgetItem(preset_name))
            self._clear_preset_adjustments(0)
            self._set_snapshot_names(0, snapshot_names)
            self._refresh_preset_table_editable_flags()

    def _load_metadata(self) -> None:
        path = Path(self.input_path.text())
        if not path.exists():
            self._set_metadata({})
            return

        try:
            profile = get_device_profile(self.device.currentData())
            handler = profile.create_patch_file_handler(Path(__file__).resolve().parents[3])
            handler.validate_input(path)
            self._set_metadata(handler.metadata(path))
        except Exception as exc:  # noqa: BLE001
            self._set_metadata({"error": str(exc)})

    def _set_metadata(self, metadata: dict[str, object]) -> None:
        self.metadata_text.setPlainText(json.dumps(metadata, indent=2, ensure_ascii=False))

    def start_normalization(self) -> None:
        if not self._validate_single_preset_slot_for_run():
            return

        if self._preset_table_has_unsaved_changes() and not self._prompt_save_before_normalization():
            return

        try:
            args = apply_config(parse_args(self._build_argv()))
            request = replace(request_from_args(args), defer_export=True)
            if request.backend == "hardware":
                self._start_hardware_check(request)
                return
        except Exception as exc:  # noqa: BLE001
            self.show_error(str(exc))
            return

        self._start_normalization_request(request)

    def _start_normalization_request(self, request: NormalizationRequest) -> None:
        try:
            if not self._confirm_automation_overwrites(request):
                return
        except Exception as exc:  # noqa: BLE001
            self.show_error(str(exc))
            return

        self.start_button.setEnabled(False)
        self.start_cancel_stack.setCurrentWidget(self.cancel_button)
        self._discard_completed_export()
        self.log.clear()
        self.log_entries.clear()
        self.preset_snapshot_positions.clear()
        self._clear_bad_lufs_highlights()
        self._adjusted_presets.clear()
        with self._sorting_paused():
            for row in range(self.preset_table.rowCount()):
                self._clear_preset_adjustments(row)
        self.retained_csv.clear()
        self.retained_csv_pane.hide()
        self._reset_loudness_bars()
        self._set_phase("starting")
        self._log("Normalization started", "info")
        self._log(f"Backend: {getattr(request, 'backend', 'unknown')}", "info")
        self._start_busy_phase()
        self.completed_request = request
        self.worker = NormalizationWorker(request, self)
        self.worker.progress.connect(self.update_progress)
        self.worker.import_requested.connect(self.confirm_import)
        self.worker.completed.connect(self.normalization_completed)
        self.worker.cancelled.connect(self.normalization_cancelled)
        self.worker.failed.connect(self.show_error)
        self.worker.finished.connect(self.worker_finished)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def _start_hardware_check(self, request: NormalizationRequest) -> None:
        if self.hardware_check_worker is not None:
            return

        self.start_button.setEnabled(False)
        self._show_hardware_check_overlay()
        self._set_phase("starting")
        self._log("Checking backend availability", "info")
        self.hardware_check_worker = HardwareCheckWorker(request, self)
        self.hardware_check_worker.completed.connect(
            lambda checked_request=request: self._hardware_check_completed(checked_request)
        )
        self.hardware_check_worker.failed.connect(self._hardware_check_failed)
        self.hardware_check_worker.finished.connect(self._hardware_check_finished)
        self.hardware_check_worker.finished.connect(self.hardware_check_worker.deleteLater)
        self.hardware_check_worker.start()

    def _hardware_check_completed(self, request: NormalizationRequest) -> None:
        self._hide_hardware_check_overlay()
        self.start_button.setEnabled(True)
        self._log("Backend availability check completed", "success")
        self._start_normalization_request(request)

    def _hardware_check_failed(self, detail: str) -> None:
        self._hide_hardware_check_overlay()
        self.start_button.setEnabled(True)
        self._set_phase("ready")
        message = "No suitable device connected."
        detail = detail.strip()
        self._log(f"{message} {detail}".strip(), "error")
        QMessageBox.critical(
            self,
            "Error",
            f"{message}\n\nConnect a compatible audio processor and try again.",
        )

    def _hardware_check_finished(self) -> None:
        self.hardware_check_worker = None

    def _show_hardware_check_overlay(self) -> None:
        self._position_hardware_check_overlay()
        self.hardware_check_overlay.show()
        self.hardware_check_overlay.raise_()

    def _hide_hardware_check_overlay(self) -> None:
        self.hardware_check_overlay.hide()

    def _position_hardware_check_overlay(self) -> None:
        central = self.centralWidget()
        if central is None:
            self.hardware_check_overlay.setGeometry(self.rect())
        else:
            self.hardware_check_overlay.setGeometry(central.geometry())

    def _confirm_automation_overwrites(self, request: NormalizationRequest) -> bool:
        if not getattr(request, "automation", False):
            return True

        profile = get_device_profile(request.device)
        handler = profile.create_patch_file_handler(Path(__file__).resolve().parents[3])
        input_path = request.input_path.resolve()
        for postfix, description in (("_measurement", "measurement"),):
            output_path = handler.automation_output_path(input_path, postfix)
            if not output_path.exists():
                continue

            answer = QMessageBox.question(
                self,
                "Overwrite generated file",
                f"The {description} file already exists:\n{output_path}\n\nOverwrite it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False

        return True

    def update_progress(self, event: ProgressEvent) -> None:
        if event.phase:
            self._set_phase(event.phase)
            self._hide_progress()
            if event.phase in {
                "completed",
                "waiting_for_measurement_import",
                "waiting_for_adjusted_import",
            }:
                self._stop_busy_phase()
            else:
                self._start_busy_phase()
            if event.phase == "measuring":
                self._show_indeterminate_progress(event.message or "Preparing measurement...")

        if event.kind == "measurement_preparation":
            self._show_indeterminate_progress(event.message or "Preparing measurement...")

        if event.preset_total and event.snapshot_total and event.preset_index:
            progress_was_hidden = self.progress_group.isHidden()
            self.progress_group.show()
            if progress_was_hidden:
                self._schedule_resize_for_content()
            total = event.preset_total * event.snapshot_total
            snapshot = event.snapshot or 1
            value = (event.preset_index - 1) * event.snapshot_total + snapshot
            self.preset_progress.setRange(0, total)
            self.preset_progress.setValue(value)
        elif event.kind == "measurement_completed":
            self._hide_progress()

        if event.lufs is not None:
            if event.device_patch:
                text = self._preset_progress_text(event)
                if event.snapshot is not None:
                    text += self._snapshot_progress_text(event)
                self.current.setText(text)
            target_lufs = self._target_lufs()
            self.measured_loudness.set_loudness(
                event.lufs,
                target_lufs,
                _loudness_bar_color(
                    event.lufs,
                    target_lufs,
                ),
            )
            self.measured_loudness_reading.setText(_loudness_text(event.lufs, target_lufs))

        message = event.message or event.kind.replace("_", " ")
        if event.kind == "log":
            self._apply_gain_correction(message)
        if event.lufs is not None and event.crest_factor_db is not None:
            message += f": {event.lufs:.3f} LUFS, {event.crest_factor_db:.3f} dB crest"
        if event.kind == "temp_retained" and event.path:
            self.retained_csv.setText(event.path)
            self.retained_csv_pane.show()

        if "bad LUFS" in message or message.startswith("[WARNING]"):
            level = "warning"
        else:
            level = "error" if event.kind in {"error_log", "preset_failed"} else "debug"
        self._log(message, level)

    def _show_indeterminate_progress(self, message: str) -> None:
        progress_was_hidden = self.progress_group.isHidden()
        self.current.setText(message)
        self.preset_progress.setRange(0, 0)
        self.progress_group.show()
        if progress_was_hidden:
            self._schedule_resize_for_content()

    def _hide_progress(self) -> None:
        if self.progress_group.isHidden():
            return
        self.progress_group.hide()
        self._schedule_resize_for_content()

    def confirm_import(self, request: ImportRequest) -> None:
        self._stop_busy_phase()
        answer = QMessageBox.question(
            self,
            "Import preset/setlist file",
            request.message,
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        )
        if self.worker is not None:
            self.worker.answer_import(answer == QMessageBox.StandardButton.Ok)

    def normalization_completed(self, result: NormalizationResult) -> None:
        self._stop_busy_phase()
        self._set_phase("completed")
        if (
            result.retained_csv_path is not None
            and self.completed_request is not None
            and self.completed_request.keep_temp
        ):
            self.retained_csv.setText(str(result.retained_csv_path))
            self.retained_csv_pane.show()
        self.completed_result = result
        if result.retained_csv_path is not None:
            self._mark_preset_table_modified()
        self._log("Measurement completed; save the active file to write adjustments", "success")

    def export_output(self) -> None:
        self.save_active_file()

    def save_active_file(self) -> bool:
        active_path = Path(self.input_path.text().strip())
        if not self.input_path.text().strip():
            self.show_error("Open a Helix .hls or .hlx file before saving")
            return False
        return self._save_to_path(active_path)

    def save_active_file_as(self) -> bool:
        output_path = self._choose_save_as_path()
        if output_path is None:
            return False
        return self._save_to_path(output_path, make_active=True)

    def _save_to_path(self, output_path: Path, *, make_active: bool = True) -> bool:
        request = self.completed_request
        result = self.completed_result
        if not self.input_path.text().strip():
            self.show_error("Open a Helix .hls or .hlx file before saving")
            return False
        if not self._preset_table_has_unsaved_changes():
            if make_active and output_path != Path(self.input_path.text()):
                try:
                    self._copy_active_file_to(output_path)
                except SaveCancelled:
                    return False
                except Exception as exc:  # noqa: BLE001
                    self.show_error(str(exc))
                    return False
                self._activate_saved_file(output_path)
            return True

        if request is None:
            try:
                request = replace(request_from_args(apply_config(parse_args(self._build_argv()))))
            except Exception as exc:  # noqa: BLE001
                self.show_error(str(exc))
                return False

        csv_path = result.retained_csv_path if result is not None else None
        temporary_csv: Path | None = None
        if csv_path is None:
            try:
                temporary_csv = self._create_table_save_csv(output_path.parent)
                csv_path = temporary_csv
            except Exception as exc:  # noqa: BLE001
                self.show_error(str(exc))
                return False

        try:
            profile = get_device_profile(request.device)
            handler = profile.create_patch_file_handler(Path(__file__).resolve().parents[3])
            handler.validate_output(request.input_path, output_path)
        except Exception as exc:  # noqa: BLE001
            self.show_error(str(exc))
            return False

        if not self._confirm_overwrite(output_path):
            return False

        replace_target = output_path.resolve() == request.input_path.resolve()
        export_path = output_path
        temporary_output: Path | None = None
        if replace_target:
            temporary = tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                suffix=output_path.suffix,
                dir=output_path.parent,
                delete=False,
            )
            temporary.close()
            temporary_output = Path(temporary.name)
            export_path = temporary_output
        try:
            export_adjusted_file(
                request,
                csv_path,
                export_path,
                adjustments=self._table_adjustments(),
                on_progress=self.update_progress,
            )
            if temporary_output is not None:
                temporary_output.replace(output_path)
        except Exception as exc:  # noqa: BLE001
            if temporary_output is not None:
                temporary_output.unlink(missing_ok=True)
            self.show_error(str(exc))
            return False
        finally:
            if temporary_csv is not None:
                temporary_csv.unlink(missing_ok=True)

        self._set_phase("completed")
        self._log(f"Saved: {output_path.resolve()}", "success")
        if make_active:
            self._activate_saved_file(output_path)
        else:
            self._reset_preset_table_modified()
            self._refresh_file_actions()
        return True

    def _copy_active_file_to(self, output_path: Path) -> None:
        input_path = Path(self.input_path.text())
        if not self._confirm_overwrite(output_path):
            raise SaveCancelled
        shutil.copy2(input_path, output_path)

    def _activate_saved_file(self, path: Path) -> None:
        self.input_path.setText(str(path))
        self._preset_load_discard_confirmed = True
        try:
            self.load_assignments()
        finally:
            self._preset_load_discard_confirmed = False

    def _set_active_file(self, path: Path) -> None:
        filename = path.name if str(path) else ""
        self.setWindowTitle(filename or "MatchPatch")

    def _refresh_file_actions(self) -> None:
        has_file = bool(self.input_path.text().strip())
        if hasattr(self, "save_action"):
            self.save_action.setEnabled(has_file and self._preset_table_has_unsaved_changes())
        if hasattr(self, "save_as_action"):
            self.save_as_action.setEnabled(has_file)
        if hasattr(self, "start_button"):
            self.start_button.setEnabled(bool(self._loaded_input_path) and self.worker is None)

    def _prompt_save_before_normalization(self) -> bool:
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Save changes")
        dialog.setText("The preset table contains changes. Save them before starting normalization?")
        save_button = dialog.addButton(QMessageBox.StandardButton.Save)
        save_as_button = dialog.addButton("Save As", QMessageBox.ButtonRole.AcceptRole)
        dialog.addButton(QMessageBox.StandardButton.Cancel)
        dialog.setDefaultButton(save_button)
        dialog.exec()
        clicked = dialog.clickedButton()
        if clicked is save_button:
            return self.save_active_file()
        if clicked is save_as_button:
            return self.save_active_file_as()
        return False

    def _confirm_overwrite(self, output_path: Path) -> bool:
        if not output_path.exists():
            return True
        answer = QMessageBox.question(
            self,
            "Overwrite file",
            f"The file already exists:\n{output_path}\n\nOverwrite it?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _create_table_save_csv(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            suffix=".matchpatch-save.csv",
            dir=directory,
            delete=False,
        )
        with temporary:
            fieldnames = ["DevicePatch"]
            for snapshot in range(1, self.snapshot_count + 1):
                fieldnames.extend([f"LUFS{snapshot}", f"CrestFactor{snapshot}"])
            writer = csv.DictWriter(temporary, fieldnames=fieldnames)
            writer.writeheader()
            for row in range(self.preset_table.rowCount()):
                patch_item = self.preset_table.item(row, 1)
                if patch_item is None:
                    continue
                csv_row = {"DevicePatch": patch_item.text()}
                for snapshot in range(1, self.snapshot_count + 1):
                    csv_row[f"LUFS{snapshot}"] = self.target_lufs.text() or "-16.0"
                    csv_row[f"CrestFactor{snapshot}"] = "12.0"
                writer.writerow(csv_row)
        return Path(temporary.name)

    def show_error(self, message: str) -> None:
        self._stop_busy_phase()
        self._set_phase("error")
        self._log(message, "error")
        QMessageBox.critical(self, "Error", message)

    def normalization_cancelled(self) -> None:
        self._stop_busy_phase(PROCESSING_DOT_RED)
        self._set_phase("normalization_cancelled_by_user")
        self._log("Normalization cancelled by user", "warning")

    def worker_finished(self) -> None:
        self._stop_busy_phase(self._processing_dot_color)
        self.start_cancel_stack.setCurrentWidget(self.start_button)
        self.worker = None
        self._refresh_file_actions()

    def _discard_completed_export(self) -> None:
        if (
            self.completed_request is not None
            and not self.completed_request.keep_temp
            and self.completed_result is not None
            and self.completed_result.temp_dir is not None
        ):
            shutil.rmtree(self.completed_result.temp_dir, ignore_errors=True)
        self.completed_request = None
        self.completed_result = None
        self.retained_csv.clear()
        self.retained_csv_pane.hide()

    def cancel_normalization(self) -> None:
        if self.worker is not None and self._confirm_cancellation():
            self.worker.cancel()
            self._set_phase("cancelling")
            self._log("Cancellation requested", "warning")
            self._start_busy_phase()

    def _confirm_cancellation(self) -> bool:
        answer = QMessageBox.question(
            self,
            "Cancel measurement",
            "A measurement is currently running. Do you want to cancel it?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.hardware_check_worker is not None:
            event.ignore()
            return
        if self._preset_table_has_unsaved_changes() and not self._confirm_discard_preset_table_changes():
            event.ignore()
            return
        if self.worker is not None:
            if not self._confirm_cancellation():
                event.ignore()
                return
            self.worker.cancel()
        if self.worker is not None:
            self.worker.wait()
        self._discard_completed_export()
        super().closeEvent(event)
        QApplication.quit()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if hasattr(self, "hardware_check_overlay") and self.hardware_check_overlay.isVisible():
            self._position_hardware_check_overlay()

    def _base_argv(self, input_path: str) -> list[str]:
        argv = [
            "--device",
            self.device.currentData(),
            "-i",
            input_path,
            "--automation",
            "--backend",
            self.backend.currentText(),
        ]
        if self.config_path.text().strip():
            argv.extend(["--config", self.config_path.text().strip()])
        return argv

    def _build_argv(self) -> list[str]:
        argv = self._base_argv(self.input_path.text().strip())
        argv.extend(["--reference-di", self.reference_di.text()])
        argv.extend(["--target-lufs", self.target_lufs.text()])
        argv.extend(["--solo-gain-bump-db", self.solo_gain_bump_db.text()])
        argv.extend(["--solo-regex", self.solo_regex.text()])
        argv.extend(["--snapshot-count", str(self.snapshot_count_input.value())])
        if self.keep_temp.isChecked():
            argv.append("--keep-temp")
        preset_set = self._selected_preset_set()
        if preset_set:
            argv.extend(["--preset-set", preset_set])

        panel = self.device_panels.get(self.device.currentData())
        if panel is not None:
            panel.append_arguments(argv)
        return argv

    def _selected_preset_set(self) -> str:
        if Path(self.input_path.text()).suffix.lower() == ".hlx":
            return self._single_preset_slot_text()

        selected = []
        for row in range(self.preset_table.rowCount()):
            selected_item = self.preset_table.item(row, 0)
            patch_item = self.preset_table.item(row, 1)
            if (
                selected_item is not None
                and patch_item is not None
                and selected_item.checkState() == Qt.CheckState.Checked
            ):
                selected.append(patch_item.text())
        return ",".join(selected)

    def _single_preset_slot_text(self) -> str:
        item = self.preset_table.item(0, 1)
        return item.text().strip().upper() if item is not None else ""

    def _validate_single_preset_slot_for_run(self) -> bool:
        if Path(self.input_path.text()).suffix.lower() != ".hlx":
            return True

        slot = self._single_preset_slot_text()
        if not slot:
            self._highlight_preset_cell(0, 1)
            QMessageBox.warning(
                self,
                "Preset ID required",
                "Enter the temporary Helix preset ID in the Preset column before running normalization.",
            )
            return False

        try:
            self._parse_single_helix_preset_slot(slot)
        except ValueError as exc:
            self.show_error(str(exc))
            self._highlight_preset_cell(0, 1)
            return False

        return True

    def _parse_single_helix_preset_slot(self, slot: str) -> int:
        profile = get_device_profile(self.device.currentData())
        handler = profile.create_patch_file_handler(Path(__file__).resolve().parents[3])
        preset_ids = handler.parse_patch_set(slot)
        if len(preset_ids) != 1:
            raise ValueError("Enter exactly one Helix preset ID for a .hlx file.")

        preset_id = preset_ids[0]
        if preset_id < 1 or preset_id > 128:
            raise ValueError("Helix preset ID must be between 01A and 32D.")
        return preset_id

    def _highlight_preset_cell(self, row: int, column: int) -> None:
        item = self.preset_table.item(row, column)
        if item is None:
            return

        signals_blocked = self.preset_table.blockSignals(True)
        try:
            item.setData(PRESET_TABLE_ATTENTION_ROLE, True)
        finally:
            self.preset_table.blockSignals(signals_blocked)
        self.preset_table.setCurrentCell(row, column)
        self.preset_table.scrollToItem(item)
        self.preset_table.viewport().update(self.preset_table.visualItemRect(item))
        QTimer.singleShot(2500, lambda: self._clear_preset_cell_highlight(row, column))

    def _clear_preset_cell_highlight(self, row: int, column: int) -> None:
        item = self.preset_table.item(row, column)
        if item is None:
            return

        signals_blocked = self.preset_table.blockSignals(True)
        try:
            item.setData(PRESET_TABLE_ATTENTION_ROLE, None)
        finally:
            self.preset_table.blockSignals(signals_blocked)
        self.preset_table.viewport().update(self.preset_table.visualItemRect(item))

    def set_all_presets_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        with self._sorting_paused():
            for row in range(self.preset_table.rowCount()):
                item = self.preset_table.item(row, 0)
                if item is not None:
                    item.setCheckState(state)

    def select_diff_presets(self) -> None:
        input_path = Path(self.input_path.text())
        suffix = input_path.suffix.lower()
        if suffix != ".hls":
            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose previous setlist",
            filter=f"Helix setlist (*{suffix})",
        )
        if not path:
            return

        previous_input_path = Path(path)
        if previous_input_path.suffix.lower() != suffix:
            self.show_error(f"Diff file must use the {suffix} extension")
            return

        try:
            profile = get_device_profile(self.device.currentData())
            handler = profile.create_patch_file_handler(Path(__file__).resolve().parents[3])
            diff_ids = {
                handler.format_patch_id(preset_id)
                for preset_id in handler.diff_preset_ids(input_path, previous_input_path)
            }
        except Exception as exc:  # noqa: BLE001
            self.show_error(str(exc))
            return

        selected_count = 0
        with self._sorting_paused():
            for row in range(self.preset_table.rowCount()):
                selected_item = self.preset_table.item(row, 0)
                patch_item = self.preset_table.item(row, 1)
                if selected_item is None or patch_item is None:
                    continue
                selected = patch_item.text() in diff_ids
                selected_item.setCheckState(
                    Qt.CheckState.Checked if selected else Qt.CheckState.Unchecked
                )
                if selected:
                    selected_count += 1

        self._log(
            f"Selected {selected_count} preset(s) changed since {previous_input_path}",
            "success",
        )

    def _manual_adjustments_toggled(self, checked: bool) -> None:
        self.preset_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._refresh_preset_table_editable_flags()

    def _refresh_preset_table_editable_flags(self) -> None:
        single_preset = Path(self.input_path.text()).suffix.lower() == ".hlx"
        for row in range(self.preset_table.rowCount()):
            for column in range(self.preset_table.columnCount()):
                item = self.preset_table.item(row, column)
                if item is not None:
                    self._set_preset_item_editable(item, single_preset and column == 1)

    @staticmethod
    def _is_manual_adjustment_column(column: int) -> bool:
        return column == 2 or column >= 3

    @staticmethod
    def _set_preset_item_editable(item: QTableWidgetItem, editable: bool) -> None:
        flags = item.flags()
        if editable:
            flags |= Qt.ItemFlag.ItemIsEditable
        else:
            flags &= ~Qt.ItemFlag.ItemIsEditable
        item.setFlags(flags)

    def _manual_adjustments_enabled(self) -> bool:
        return hasattr(self, "manual_adjustments") and self.manual_adjustments.isChecked()

    def _manual_table_cell_double_clicked(self, row: int, column: int) -> None:
        single_preset_slot = Path(self.input_path.text()).suffix.lower() == ".hlx" and column == 1
        if not single_preset_slot and (
            not self._manual_adjustments_enabled()
            or not self._is_manual_adjustment_column(column)
        ):
            return

        item = self.preset_table.item(row, column)
        if item is None:
            return

        self._start_manual_cell_edit(row, column, item)

    def _start_manual_cell_edit(self, row: int, column: int, item: QTableWidgetItem) -> None:
        self._finish_manual_cell_edit(commit=True)
        editor = QLineEdit(self.preset_table.viewport())
        max_length = self._manual_name_max_length(column)
        if max_length is not None:
            editor.setMaxLength(max_length)
        editor.setText(item.text())
        editor.selectAll()
        editor.setFrame(False)
        editor.setGeometry(self.preset_table.visualItemRect(item))
        editor.installEventFilter(self)
        editor.returnPressed.connect(lambda: self._finish_manual_cell_edit(commit=True))
        editor.show()
        editor.setFocus(Qt.FocusReason.MouseFocusReason)
        self._manual_cell_editor = editor
        self._manual_cell_target = (row, column)

    def _finish_manual_cell_edit(self, *, commit: bool) -> None:
        editor = self._manual_cell_editor
        target = self._manual_cell_target
        if editor is None or target is None:
            return

        row, column = target
        item = self.preset_table.item(row, column)
        if commit and item is not None:
            value = editor.text()
            if column == 1 and Path(self.input_path.text()).suffix.lower() == ".hlx":
                item.setText(value.strip().upper())
            elif column == 2:
                item.setText(self._sanitize_helix_name(value, self._preset_name_max_length()))
            elif column % 2:
                item.setText(self._sanitize_helix_name(value, self._snapshot_name_max_length()))
            else:
                try:
                    delta = float(value)
                except ValueError:
                    self.show_error(f"Invalid gain adjustment: {value!r}")
                    editor.setFocus(Qt.FocusReason.OtherFocusReason)
                    editor.selectAll()
                    return
                if not math.isfinite(delta):
                    self.show_error(f"Invalid gain adjustment: {value!r}")
                    editor.setFocus(Qt.FocusReason.OtherFocusReason)
                    editor.selectAll()
                    return
                self._set_adjustment_value(item, value, delta)

        self._manual_cell_editor = None
        self._manual_cell_target = None
        editor.removeEventFilter(self)
        editor.deleteLater()

    def _manual_name_max_length(self, column: int) -> int | None:
        if column == 2:
            return self._preset_name_max_length()
        if column % 2:
            return self._snapshot_name_max_length()
        return None

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._manual_cell_editor:
            if event.type() == QEvent.Type.KeyPress:
                key = event.key() if isinstance(event, QKeyEvent) else None
                if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
                    self._finish_manual_cell_edit(commit=True)
                    return True
                if key == Qt.Key.Key_Escape:
                    self._finish_manual_cell_edit(commit=False)
                    return True
            if event.type() == QEvent.Type.FocusOut:
                editor = self._manual_cell_editor
                QTimer.singleShot(
                    0,
                    lambda: (
                        self._finish_manual_cell_edit(commit=True)
                        if editor is self._manual_cell_editor
                        else None
                    ),
                )
        return super().eventFilter(watched, event)

    def _table_adjustments(self) -> PatchFileAdjustments:
        preset_names = {}
        snapshot_names = {}
        gain_deltas = {}

        for row in range(self.preset_table.rowCount()):
            patch_item = self.preset_table.item(row, 1)
            preset_item = self.preset_table.item(row, 2)
            if patch_item is None or preset_item is None:
                continue

            patch = patch_item.text()
            preset_names[patch] = self._validate_helix_name(
                preset_item.text(),
                self._preset_name_max_length(),
            )
            patch_snapshot_names = {}
            patch_gain_deltas = {}
            for snapshot_index, column in enumerate(range(3, self.preset_table.columnCount(), 2)):
                name_item = self.preset_table.item(row, column)
                adjustment_item = self.preset_table.item(row, column + 1)
                if name_item is not None:
                    patch_snapshot_names[snapshot_index] = self._validate_helix_name(
                        name_item.text(),
                        self._snapshot_name_max_length(),
                    )
                if adjustment_item is not None:
                    if adjustment_item.text() == "⚠️":
                        continue
                    try:
                        value = float(adjustment_item.text())
                    except ValueError as exc:
                        raise ValueError(
                            f"Invalid gain adjustment: {adjustment_item.text()!r}"
                        ) from exc
                    if not math.isfinite(value):
                        raise ValueError(f"Invalid gain adjustment: {adjustment_item.text()!r}")
                    patch_gain_deltas[snapshot_index] = value
            snapshot_names[patch] = patch_snapshot_names
            gain_deltas[patch] = patch_gain_deltas

        return PatchFileAdjustments(preset_names, snapshot_names, gain_deltas)

    @staticmethod
    def _validate_helix_name(name: str, max_length: int | None = None) -> str:
        if HELIX_NAME_PATTERN.fullmatch(name) is None:
            raise ValueError(f"Invalid Helix name: {name!r}")
        if max_length is not None and len(name) > max_length:
            raise ValueError(f"Helix name exceeds {max_length} characters: {name!r}")
        return name

    def _set_phase(self, phase: str) -> None:
        self.phase.setText(_phase_text(phase))
        standard_pixmap = PHASE_ICON.get(phase.lower())
        icon = (
            self.style().standardIcon(standard_pixmap) if standard_pixmap is not None else QIcon()
        )
        self.phase_icon.setPixmap(icon.pixmap(16, 16))

    def _apply_gain_correction(self, message: str) -> None:
        match = (
            GAIN_CORRECTION_PATTERN.match(message)
            or GAIN_STABLE_PATTERN.match(message)
            or GAIN_BAD_LUFS_PATTERN.match(message)
        )
        if match is None:
            return

        row = self._preset_row(match["patch"])
        if row is None:
            return

        selected = self.preset_table.item(row, 0)
        if selected is None or selected.checkState() != Qt.CheckState.Checked:
            self._clear_preset_adjustments(row)
            return

        snapshot_position = self.preset_snapshot_positions.get(match["patch"], 0)
        if snapshot_position >= self.snapshot_count:
            return

        label = match["label"]
        is_solo = label.endswith(" (S)")
        if is_solo:
            label = label[:-4]
        name_column = 3 + snapshot_position * 2
        adjustment_column = name_column + 1
        name_item = self.preset_table.item(row, name_column)
        adjustment_item = self.preset_table.item(row, adjustment_column)
        if name_item is None or adjustment_item is None:
            return
        if not name_item.text():
            self._set_snapshot_name(name_item, label, is_solo)
        if match.re is GAIN_BAD_LUFS_PATTERN:
            adjustment_item.setText("⚠️")
            adjustment_item.setToolTip("This snapshot produced an unusable LUFS measurement.")
            adjustment_item.setForeground(QBrush(QColor("#b45309")))
            font = adjustment_item.font()
            font.setBold(True)
            font.setPointSize(max(font.pointSize(), QApplication.font().pointSize(), 9) + 5)
            adjustment_item.setFont(font)
            self._set_bad_lufs_highlight(row)
            self._adjusted_presets.add(match["patch"])
            self.preset_snapshot_positions[match["patch"]] = snapshot_position + 1
            return

        adjustment = match["delta"]
        self._set_adjustment_value(
            adjustment_item,
            adjustment,
            float(match["delta"]),
        )
        self._adjusted_presets.add(match["patch"])
        self.preset_snapshot_positions[match["patch"]] = snapshot_position + 1

    def _configure_snapshot_columns(self, snapshot_count: int) -> None:
        self.snapshot_count = snapshot_count
        labels = ["", "Preset", "Name"]
        for snapshot in range(1, snapshot_count + 1):
            labels.extend([str(snapshot), "Δ (dB)"])
        with self._sorting_paused():
            self.preset_table.setColumnCount(len(labels))
            self.preset_table.setHorizontalHeaderLabels(labels)
            header = self.preset_table.horizontalHeader()
            header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            header.setStretchLastSection(False)
            checkbox_width = self.style().pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth)
            checkbox_spacing = self.style().pixelMetric(QStyle.PixelMetric.PM_CheckBoxLabelSpacing)
            selection_width = checkbox_width + checkbox_spacing * 2
            header.setMinimumSectionSize(selection_width)
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
            self.preset_table.setColumnWidth(0, selection_width)
            self.preset_table.setColumnWidth(1, 52)
            self.preset_table.setColumnWidth(2, 120)
            for column in range(3, len(labels), 2):
                self.preset_table.setColumnWidth(column, 100)
                self.preset_table.setColumnWidth(column + 1, 62)
            for column, tooltip in enumerate(
                [
                    "Include this preset in normalization.",
                    "Processor slot containing the preset.",
                    "Preset name read from the input file.",
                    *(
                        tooltip
                        for snapshot in range(1, snapshot_count + 1)
                        for tooltip in (
                            f"Name of snapshot {snapshot} read from the input file.",
                            f"Calculated gain adjustment for snapshot {snapshot}.",
                        )
                    ),
                ]
            ):
                item = self.preset_table.horizontalHeaderItem(column)
                if item is not None:
                    item.setToolTip(tooltip)
            for row in range(self.preset_table.rowCount()):
                self._clear_preset_adjustments(row)
                self._refresh_snapshot_names(row)

    def _snapshot_count_changed(self, snapshot_count: int) -> None:
        if hasattr(self, "preset_table"):
            self._configure_snapshot_columns(snapshot_count)

    @contextmanager
    def _sorting_paused(self) -> Iterator[None]:
        sorting_enabled = self.preset_table.isSortingEnabled()
        self.preset_table.setSortingEnabled(False)
        try:
            yield
        finally:
            self.preset_table.setSortingEnabled(sorting_enabled)

    def _clear_preset_adjustments(self, row: int) -> None:
        patch = self.preset_table.item(row, 1)
        if patch is not None:
            self._adjusted_presets.discard(patch.text())
        self._clear_bad_lufs_highlight(row)
        for column in range(3, self.preset_table.columnCount(), 2):
            name = self.preset_table.item(row, column)
            adjustment = self.preset_table.item(row, column + 1)
            if name is None:
                name = QTableWidgetItem()
                self.preset_table.setItem(row, column, name)
            if adjustment is None:
                adjustment = QTableWidgetItem()
                self.preset_table.setItem(row, column + 1, adjustment)
            self._set_preset_item_editable(
                name,
                False,
            )
            self._set_preset_item_editable(
                adjustment,
                False,
            )
            self._set_adjustment_value(adjustment, "+0", 0)

    def _set_bad_lufs_highlight(self, row: int) -> None:
        for column in range(self.preset_table.columnCount()):
            item = self.preset_table.item(row, column)
            if item is not None:
                item.setBackground(BAD_LUFS_ROW_BACKGROUND)

    def _clear_bad_lufs_highlight(self, row: int) -> None:
        for column in range(self.preset_table.columnCount()):
            item = self.preset_table.item(row, column)
            if item is not None:
                item.setBackground(QBrush())

    def _clear_bad_lufs_highlights(self) -> None:
        for row in range(self.preset_table.rowCount()):
            self._clear_bad_lufs_highlight(row)

    def _set_snapshot_names(self, row: int, snapshot_names: tuple[str, ...]) -> None:
        name_item = self.preset_table.item(row, 2)
        if name_item is not None:
            name_item.setData(Qt.ItemDataRole.UserRole, snapshot_names)
        self._refresh_snapshot_names(row)

    def _refresh_snapshot_names(self, row: int) -> None:
        name_item = self.preset_table.item(row, 2)
        snapshot_names = name_item.data(Qt.ItemDataRole.UserRole) if name_item is not None else ()
        snapshot_names = snapshot_names if isinstance(snapshot_names, tuple) else ()
        try:
            solo_pattern = re.compile(self.solo_regex.text())
        except re.error:
            solo_pattern = None
        for column in range(3, self.preset_table.columnCount(), 2):
            item = self.preset_table.item(row, column)
            if item is not None:
                self._set_snapshot_name(item, "", False)
        for snapshot, name in enumerate(snapshot_names[: self.snapshot_count]):
            item = self.preset_table.item(row, 3 + snapshot * 2)
            if item is not None:
                self._set_snapshot_name(
                    item,
                    name,
                    solo_pattern is not None and solo_pattern.search(name) is not None,
                )

    @staticmethod
    def _set_snapshot_name(item: QTableWidgetItem, name: str, is_solo: bool) -> None:
        table = item.tableWidget()
        signals_blocked = table.blockSignals(True) if table is not None else False
        try:
            item.setText(name)
            item.setIcon(QIcon())
            item.setToolTip("Solo snapshot" if is_solo else "")
        finally:
            if table is not None:
                table.blockSignals(signals_blocked)
        if table is None:
            return
        if not is_solo:
            table.removeCellWidget(item.row(), item.column())
            return
        label = QLabel(f"{escape(name)} <span style='color: #f59e0b;'>★</span>")
        label.setContentsMargins(3, 0, 0, 0)
        label.setToolTip("Solo snapshot")
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        table.setCellWidget(item.row(), item.column(), label)

    def _preset_item_changed(self, item: QTableWidgetItem) -> None:
        if item.data(PRESET_TABLE_ATTENTION_ROLE):
            item.setData(PRESET_TABLE_ATTENTION_ROLE, None)
            self.preset_table.viewport().update(self.preset_table.visualItemRect(item))
        if Path(self.input_path.text()).suffix.lower() == ".hlx" and item.column() == 1:
            normalized = item.text().strip().upper()
            if normalized != item.text():
                signals_blocked = self.preset_table.blockSignals(True)
                try:
                    item.setText(normalized)
                finally:
                    self.preset_table.blockSignals(signals_blocked)
            return

        if item.column() == 0 and item.checkState() != Qt.CheckState.Checked:
            self._clear_preset_adjustments(item.row())
        elif self._manual_adjustments_enabled() and self._is_manual_adjustment_column(
            item.column()
        ):
            if item.column() == 2:
                sanitized = self._sanitize_helix_name(
                    item.text(),
                    self._preset_name_max_length(),
                )
                if sanitized != item.text():
                    signals_blocked = self.preset_table.blockSignals(True)
                    try:
                        item.setText(sanitized)
                    finally:
                        self.preset_table.blockSignals(signals_blocked)
            elif item.column() % 2:
                sanitized = self._sanitize_helix_name(
                    item.text(),
                    self._snapshot_name_max_length(),
                )
                if sanitized != item.text():
                    signals_blocked = self.preset_table.blockSignals(True)
                    try:
                        item.setText(sanitized)
                    finally:
                        self.preset_table.blockSignals(signals_blocked)
                name_item = self.preset_table.item(item.row(), 2)
                if name_item is not None:
                    snapshot_names = list(name_item.data(Qt.ItemDataRole.UserRole) or ())
                    snapshot_index = (item.column() - 3) // 2
                    snapshot_names.extend(
                        "" for _ in range(snapshot_index + 1 - len(snapshot_names))
                    )
                    snapshot_names[snapshot_index] = item.text()
                    name_item.setData(Qt.ItemDataRole.UserRole, tuple(snapshot_names))
                try:
                    solo_pattern = re.compile(self.solo_regex.text())
                except re.error:
                    solo_pattern = None
                self._set_snapshot_name(
                    item,
                    item.text(),
                    solo_pattern is not None and solo_pattern.search(item.text()) is not None,
                )
            else:
                try:
                    value = float(item.text())
                except ValueError:
                    return
                self._set_adjustment_value(item, item.text(), value)
            if self._preset_table_content_signature() != self._preset_table_clean_signature:
                self._mark_preset_table_modified()

    def _preset_name_max_length(self) -> int | None:
        return self._current_profile_name_max_length("preset_name_max_length")

    def _snapshot_name_max_length(self) -> int | None:
        return self._current_profile_name_max_length("snapshot_name_max_length")

    def _current_profile_name_max_length(self, attribute: str) -> int | None:
        device = self.device.currentData() if hasattr(self, "device") else None
        if not device:
            return None
        try:
            profile = get_device_profile(device)
        except ValueError:
            return None
        value = getattr(profile, attribute, None)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    @staticmethod
    def _sanitize_helix_name(name: str, max_length: int | None = None) -> str:
        sanitized = "".join(
            character for character in name if HELIX_NAME_CHAR_PATTERN.fullmatch(character)
        )
        return sanitized[:max_length] if max_length is not None else sanitized

    def _preset_row(self, patch: str) -> int | None:
        for row in range(self.preset_table.rowCount()):
            item = self.preset_table.item(row, 1)
            if item is not None and item.text() == patch:
                return row
        return None

    def _log(self, message: str, level: str) -> None:
        timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
        self.log_entries.append((timestamp, level, message))
        if self._log_is_visible(level):
            self.log.append(self._format_log_entry(timestamp, level, message))

    def _refresh_log(self) -> None:
        self.log.clear()
        for timestamp, level, message in self.log_entries:
            if self._log_is_visible(level):
                self.log.append(self._format_log_entry(timestamp, level, message))

    def _log_is_visible(self, level: str) -> bool:
        priorities = {"debug": 10, "info": 20, "success": 20, "warning": 30, "error": 40}
        selected = self.log_level.currentText().lower()
        return priorities.get(level, 20) >= priorities[selected]

    @staticmethod
    def _format_log_entry(timestamp: str, level: str, message: str) -> str:
        colors = {
            "debug": "#6b7280",
            "info": "#2563eb",
            "success": "#15803d",
            "warning": "#b45309",
            "error": "#b91c1c",
        }
        color = colors.get(level, colors["info"])
        return (
            f'<span style="color:{color}">[{timestamp}] {escape(level.upper())}: '
            f"{escape(message)}</span>"
        )

    @staticmethod
    def _set_adjustment_value(item: QTableWidgetItem, text: str, value: float) -> None:
        table = item.tableWidget()
        signals_blocked = table.blockSignals(True) if table is not None else False
        try:
            item.setText("0" if value == 0 else text)
            item.setToolTip("")
            font = item.font()
            font.setBold(False)
            font.setPointSize(max(QApplication.font().pointSize(), 9))
            item.setFont(font)
            color = "#15803d" if value > 0 else "#b91c1c" if value < 0 else None
            item.setForeground(QBrush(QColor(color)) if color is not None else QBrush())
        finally:
            if table is not None:
                table.blockSignals(signals_blocked)

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
        QTimer.singleShot(0, self._resize_to_content_when_settled)

    def _resize_to_content_when_settled(self) -> None:
        for _ in range(3):
            QCoreApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
        self._resize_to_initial_content()

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
        waiting_text = f"waiting for signal (target {target_lufs:.1f} LUFS)"
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
        name = self.preset_table.item(row, 3 + (event.snapshot - 1) * 2)
        return f"{text}: {name.text()}" if name and name.text() else text

    def _preset_table_has_unsaved_changes(self) -> bool:
        return self._preset_table_modified or bool(self._adjusted_presets)

    def _mark_preset_table_modified(self) -> None:
        self._preset_table_modified = True
        self._refresh_file_actions()

    def _reset_preset_table_modified(self) -> None:
        self._preset_table_clean_signature = self._preset_table_content_signature()
        self._preset_table_modified = False
        self._adjusted_presets.clear()
        self._refresh_file_actions()

    def _preset_table_content_signature(self) -> tuple[tuple[str, ...], ...]:
        return tuple(
            tuple(self._preset_table_csv_row(row))
            for row in range(self.preset_table.rowCount())
        )


class CurrentPageHeightTabWidget(QTabWidget):
    """Size vertically for the selected page instead of the tallest page."""

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        current = self.currentWidget()
        if current is not None:
            hint.setHeight(current.sizeHint().height() + self.tabBar().sizeHint().height())
        return hint

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        current = self.currentWidget()
        if current is not None:
            hint.setHeight(
                current.minimumSizeHint().height() + self.tabBar().minimumSizeHint().height()
            )
        return hint


class JsonSyntaxHighlighter(QSyntaxHighlighter):
    """Lightweight JSON highlighting for the metadata tab."""

    _TOKEN_PATTERN = re.compile(
        r"(?P<key>\"(?:\\.|[^\"\\])*\"(?=\s*:))|"
        r"(?P<string>\"(?:\\.|[^\"\\])*\")|"
        r"(?P<number>-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b)|"
        r"(?P<boolean>\btrue\b|\bfalse\b)|"
        r"(?P<null>\bnull\b)|"
        r"(?P<punctuation>[{}\[\],:])"
    )

    def __init__(self, document: object) -> None:
        super().__init__(document)
        self.formats = {
            "key": self._format("#7c3aed", bold=True),
            "string": self._format("#15803d"),
            "number": self._format("#b45309"),
            "boolean": self._format("#2563eb", bold=True),
            "null": self._format("#6b7280", italic=True),
            "punctuation": self._format("#374151"),
        }

    @staticmethod
    def _format(color: str, *, bold: bool = False, italic: bool = False) -> QTextCharFormat:
        text_format = QTextCharFormat()
        text_format.setForeground(QColor(color))
        if bold:
            text_format.setFontWeight(QFont.Weight.Bold)
        text_format.setFontItalic(italic)
        return text_format

    def highlightBlock(self, text: str) -> None:
        for match in self._TOKEN_PATTERN.finditer(text):
            token = match.lastgroup
            if token is None:
                continue
            self.setFormat(match.start(), match.end() - match.start(), self.formats[token])


class ContentHeightTableWidget(QTableWidget):
    """Grow with preset rows until an internal scrollbar is more useful."""

    MAX_VISIBLE_ROWS = 12

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        visible_rows = min(self.rowCount(), self.MAX_VISIBLE_ROWS)
        rows_height = sum(self.rowHeight(row) for row in range(visible_rows))
        frame_height = self.frameWidth() * 2
        hint.setHeight(
            max(
                self.minimumHeight(),
                self.horizontalHeader().sizeHint().height() + rows_height + frame_height,
            )
        )
        return hint


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


def _interpolate_color(start: QColor, end: QColor, fraction: float) -> QColor:
    return QColor(
        round(start.red() + (end.red() - start.red()) * fraction),
        round(start.green() + (end.green() - start.green()) * fraction),
        round(start.blue() + (end.blue() - start.blue()) * fraction),
    )


def _path_row(field: QLineEdit, button: QPushButton) -> QWidget:
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(field)
    layout.addWidget(button)
    return widget


def _label(text: str, tooltip: str) -> QLabel:
    label = QLabel(text)
    label.setToolTip(tooltip)
    return label
