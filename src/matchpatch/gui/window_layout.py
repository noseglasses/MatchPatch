"""Top-level widget builders for the MatchPatch main window."""

from __future__ import annotations

import re
from typing import Any, Protocol, cast

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPropertyAnimation,
    QSize,
    Qt,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QPixmap,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStyle,
    QTableWidget,
    QTabWidget,
    QTextEdit,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from matchpatch.devices.base import NormalizationPolicy
from matchpatch.gui.diagnostics_panel import DiagnosticsPanel
from matchpatch.gui.dialogs import ASSETS_DIR
from matchpatch.gui.help import HelpId
from matchpatch.gui.icons import (
    _advanced_icon,
    _fixed_size_pixmap,
    _normalization_icon,
)
from matchpatch.gui.log_panel import GuiLogController
from matchpatch.gui.loudness_widgets import LoudnessBar, LoudnessScale
from matchpatch.gui.preset_table import (
    AttentionFrameDelegate,
    ContentHeightTableWidget,
    PresetTableCallbacks,
    PresetTableController,
    refresh_preset_cell_widget_background,
    refresh_preset_item_background,
)
from matchpatch.gui.snapshot_header import SnapshotHeader

MEASUREMENT_TIMING_PRESETS: dict[str, dict[str, float]] = {
    "Default": {
        "pre_roll": 0.3,
        "post_roll": 0.5,
        "snapshot_wait": 1.0,
        "measurement_wait": 0.6,
        "preset_wait": 1.3,
        "round_trip_latency": 0.001,
    },
    "Fast": {
        "pre_roll": 0.01,
        "post_roll": 0.06,
        "snapshot_wait": 0.01,
        "measurement_wait": 0.47,
        "preset_wait": 0.21,
        "round_trip_latency": 0.001,
    },
}


class MainWindowLike(Protocol):
    def __getattr__(self, name: str) -> Any:  # noqa: ANN401
        raise AttributeError(name)

    def __setattr__(self, name: str, value: object, /) -> None: ...


TOOLBAR_ICON_SIZE = 20
TOOLBAR_VERTICAL_PADDING = 10
PRESET_EMPTY_LOGO_SIZE = QSize(360, 360)


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

    def __init__(self, document: QTextDocument) -> None:
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


def build_toolbar(window: MainWindowLike) -> None:
    parent = cast(QWidget, window)
    object_parent = cast(QObject, window)
    toolbar = QToolBar("File", parent)
    toolbar.setMovable(False)
    toolbar.setContentsMargins(0, 0, 0, 0)
    toolbar.setIconSize(QSize(TOOLBAR_ICON_SIZE, TOOLBAR_ICON_SIZE))
    window.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)

    window.open_action = QAction(
        window.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton),
        "Open",
        object_parent,
    )
    window.open_action.setToolTip("Open a Helix preset or setlist file.")
    window.open_action.setProperty("help_id", HelpId.OPEN_FILES)
    window.open_action.triggered.connect(window.browse_input)
    toolbar.addAction(window.open_action)

    window.save_action = QAction(
        window.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton),
        "Save",
        object_parent,
    )
    window.save_action.setToolTip("Save changes to the active Helix file.")
    window.save_action.setProperty("help_id", HelpId.SAVE_IMPORT)
    window.save_action.triggered.connect(window.save_active_file)
    toolbar.addAction(window.save_action)

    window.save_as_action = QAction(window._save_as_icon, "Save As", object_parent)
    window.save_as_action.setToolTip("Save the active Helix file under a new name.")
    window.save_as_action.setProperty("help_id", HelpId.SAVE_IMPORT)
    window.save_as_action.triggered.connect(window.save_active_file_as)
    toolbar.addAction(window.save_as_action)

    window.save_measurement_action = QAction(
        window._save_measurement_icon,
        "Save Measurement File",
        object_parent,
    )
    window.save_measurement_action.setToolTip(
        "Save the measurement Helix file generated by normalization."
    )
    window.save_measurement_action.setProperty("help_id", HelpId.MEASUREMENT_FILE)
    window.save_measurement_action.triggered.connect(window.save_measurement_file)
    toolbar.addAction(window.save_measurement_action)

    window.normalization_separator_action = toolbar.addSeparator()
    window.start_button = QToolButton(parent)
    window.start_button.setIcon(_normalization_icon())
    window.start_button.setToolTip("Start the guided preset-normalization workflow.")
    window.start_button.setProperty("help_id", HelpId.NORMALIZE_SETLIST)
    window.start_button.clicked.connect(window.start_normalization)
    window.cancel_button = QToolButton(parent)
    window.cancel_button.setIcon(
        window.style().standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton)
    )
    window.cancel_button.setToolTip("Stop the currently running normalization workflow.")
    window.cancel_button.setProperty("help_id", HelpId.PROGRESS_CANCEL)
    window.cancel_button.clicked.connect(window.cancel_normalization)
    window.start_cancel_stack = QStackedWidget(parent)
    window.start_cancel_stack.addWidget(window.start_button)
    window.start_cancel_stack.addWidget(window.cancel_button)
    window.normalization_action = toolbar.addWidget(window.start_cancel_stack)

    help_spacer = QWidget(parent)
    help_spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    window.help_spacer_action = toolbar.addWidget(help_spacer)

    window.device = QComboBox(parent)
    window.device.setToolTip("The audio processor profile used by this workflow.")
    window.device.setAccessibleName("Device")
    window.device.setProperty("help_id", HelpId.BACKENDS)
    window.device.currentIndexChanged.connect(window.device_changed)
    window.device_action = toolbar.addWidget(window.device)

    window.recording_separator_action = toolbar.addSeparator()

    window.record_output_button = QToolButton(parent)
    window.record_output_button.setIcon(window._record_icon)
    window.record_output_button.setCheckable(True)
    window.record_output_button.setChecked(True)
    window.record_output_button.setToolTip(
        "Record measured processor output for each snapshot during normalization."
    )
    window.record_output_button.setAccessibleName("Record measured output")
    window.record_output_button.setProperty("help_id", HelpId.RECORDED_OUTPUT)
    window.record_output_button.toggled.connect(window._record_output_toggle_changed)
    window.record_output_action = toolbar.addWidget(window.record_output_button)

    window.play_recorded_output_button = QToolButton(parent)
    window.play_recorded_output_button.setIcon(window._speaker_off_icon)
    window.play_recorded_output_button.setCheckable(True)
    window.play_recorded_output_button.setToolTip(
        "Play measured processor output through the computer speakers after each recording."
    )
    window.play_recorded_output_button.setAccessibleName("Play measured output")
    window.play_recorded_output_button.setProperty("help_id", HelpId.RECORDED_OUTPUT)
    window.play_recorded_output_button.toggled.connect(window._playback_toggle_changed)
    window.play_recorded_output_action = toolbar.addWidget(window.play_recorded_output_button)

    window.advanced_button = QToolButton(parent)
    window.advanced_button.setIcon(_advanced_icon())
    window.advanced_button.setCheckable(True)
    window.advanced_button.setChecked(True)
    window.advanced_button.setToolTip(
        "Show less frequently changed settings and diagnostic details."
    )
    window.advanced_button.setAccessibleName("Advanced")
    window.advanced_button.setProperty("help_id", HelpId.ADVANCED_SETTINGS)
    window.advanced_button.toggled.connect(window._set_advanced_visible)
    window.advanced_action = toolbar.addWidget(window.advanced_button)
    toolbar.addSeparator()

    window.help_action = QAction(
        window.style().standardIcon(QStyle.StandardPixmap.SP_DialogHelpButton),
        "Help",
        object_parent,
    )
    window.help_action.setToolTip("Open the guided MatchPatch usage instructions.")
    window.help_action.setProperty("help_id", HelpId.DOCS_INDEX)
    window.help_action.triggered.connect(window.show_help)
    toolbar.addAction(window.help_action)

    window.about_action = QAction(
        window.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation),
        "About",
        object_parent,
    )
    window.about_action.setToolTip("Show project version, license, and repository information.")
    window.about_action.triggered.connect(window.show_about)
    toolbar.addAction(window.about_action)

    square_button_size = toolbar.iconSize().width() + 14
    for button in (
        window.start_button,
        window.cancel_button,
        window.record_output_button,
        window.play_recorded_output_button,
        window.advanced_button,
    ):
        button.setAutoRaise(True)
        button.setIconSize(toolbar.iconSize())
        button.setFixedSize(square_button_size, square_button_size)
    window.start_cancel_stack.setFixedSize(square_button_size, square_button_size)
    for action in (
        window.open_action,
        window.save_action,
        window.save_as_action,
        window.save_measurement_action,
        window.help_action,
        window.about_action,
    ):
        button = toolbar.widgetForAction(action)
        if button is not None:
            button.setFixedSize(square_button_size, square_button_size)
    toolbar_content_height = max(
        window.start_cancel_stack.height(),
        window.device.sizeHint().height(),
        square_button_size,
    )
    toolbar.setFixedHeight(toolbar_content_height + TOOLBAR_VERTICAL_PADDING)
    for action in toolbar.actions():
        widget = toolbar.widgetForAction(action)
        if widget is not None and widget.toolTip():
            widget.setProperty("keep_tooltip_visible", True)
            widget.installEventFilter(object_parent)


def build_preset_advanced_splitter(window: MainWindowLike) -> QSplitter:
    splitter = QSplitter(Qt.Orientation.Horizontal)
    window.preset_advanced_splitter = splitter
    splitter.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
    splitter.setChildrenCollapsible(False)
    splitter.addWidget(window._build_presets())
    splitter.addWidget(window._build_advanced())
    splitter.setStretchFactor(0, 1)
    splitter.setStretchFactor(1, 0)
    return splitter


def build_presets(window: MainWindowLike, callbacks: PresetTableCallbacks) -> QWidget:
    content = QWidget()
    content.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
    layout = QVBoxLayout(content)
    layout.setContentsMargins(0, 0, 0, 0)
    window.preset_hint = QLabel("Choose an .hls or .hlx file.")
    window.preset_hint.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
    window.preset_empty_state = window._build_preset_empty_state()
    window.preset_table = ContentHeightTableWidget()
    window.preset_table_controller = PresetTableController(
        window.preset_table,
        callbacks,
        window._adjusted_presets,
    )
    window.preset_table.refresh_preset_item_background = refresh_preset_item_background
    window.preset_table.refresh_preset_cell_widget_background = (
        refresh_preset_cell_widget_background
    )
    window.preset_table.setHorizontalHeader(SnapshotHeader(window.preset_table))
    window.preset_table.setItemDelegate(AttentionFrameDelegate(window.preset_table))
    window.preset_table.verticalHeader().hide()
    window.preset_table.setWordWrap(False)
    window.preset_table.setToolTip(
        "Select presets and inspect snapshot names and calculated output-gain adjustments."
    )
    window.preset_table.setProperty("help_id", HelpId.OPEN_FILES)
    window.preset_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    window._configure_snapshot_columns(window.snapshot_count)
    window.preset_table.cellDoubleClicked.connect(window._manual_table_cell_double_clicked)
    window.preset_table.itemChanged.connect(window.preset_table_controller.preset_item_changed)
    window.preset_table.setSortingEnabled(True)
    window.preset_table.setMinimumHeight(160)
    window.preset_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    window.preset_table.model().rowsInserted.connect(window._preset_table_size_changed)
    window.preset_table.model().rowsRemoved.connect(window._preset_table_size_changed)
    window.preset_table.model().modelReset.connect(window._preset_table_size_changed)
    window.preset_table.model().rowsInserted.connect(window._refresh_measurement_time_estimate)
    window.preset_table.model().rowsRemoved.connect(window._refresh_measurement_time_estimate)
    window.preset_table.model().modelReset.connect(window._refresh_measurement_time_estimate)
    window.preset_table.model().rowsInserted.connect(window._refresh_file_actions)
    window.preset_table.model().rowsRemoved.connect(window._refresh_file_actions)
    window.preset_table.model().modelReset.connect(window._refresh_file_actions)
    window.preset_table_note = QLabel("Only non-empty presets are listed.")
    window.preset_table_note.setTextFormat(Qt.TextFormat.RichText)
    window.preset_measurement_time_estimate = QLabel()
    window.preset_measurement_time_estimate.setWordWrap(True)
    window.preset_measurement_time_estimate.setToolTip(
        "Estimated total measurement time for the currently selected presets."
    )
    window.save_csv_button = QPushButton()
    window.save_csv_button.setIcon(window._save_as_icon)
    window.save_csv_button.setToolTip("Save the preset table as pipe-delimited CSV.")
    window.save_csv_button.setProperty("help_id", HelpId.MANUAL_CSV)
    window.save_csv_button.clicked.connect(window.save_preset_table_csv)
    window.load_csv_button = QPushButton()
    window.load_csv_button.setIcon(
        window.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton)
    )
    window.load_csv_button.setToolTip("Load preset-table content from pipe-delimited CSV.")
    window.load_csv_button.setProperty("help_id", HelpId.MANUAL_CSV)
    window.load_csv_button.clicked.connect(window.load_preset_table_csv)
    csv_button_size = max(
        window.save_csv_button.sizeHint().height(),
        window.load_csv_button.sizeHint().height(),
    )
    for button in (window.save_csv_button, window.load_csv_button):
        button.setFixedSize(csv_button_size, csv_button_size)
        button.setEnabled(False)
    window.preset_csv_controls = QWidget()
    preset_csv_layout = QHBoxLayout(window.preset_csv_controls)
    preset_csv_layout.setContentsMargins(0, 0, 0, 0)
    preset_csv_layout.setSpacing(4)
    window.preset_csv_label = QLabel("CSV: ")
    preset_csv_layout.addWidget(window.preset_csv_label)
    preset_csv_layout.addWidget(window.load_csv_button)
    preset_csv_layout.addWidget(window.save_csv_button)
    window.single_slot = QLineEdit()
    window.single_slot.setPlaceholderText("Temporary slot, for example 12A")
    window.single_slot.hide()
    window.preset_header = QWidget()
    preset_header = QHBoxLayout(window.preset_header)
    preset_header.setContentsMargins(0, 0, 0, 0)
    preset_header.addWidget(window.preset_hint)
    preset_header.addStretch()
    window.preset_help_button = window._help_tool_button(
        "Open help for presets",
        lambda: window.open_help_topic(window._preset_table_help_id()),
    )
    window.select_all_button = QPushButton("Select all")
    window.select_all_button.setIcon(
        window.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
    )
    window.select_all_button.setToolTip("Include every preset in this setlist.")
    window.select_all_button.setProperty("help_id", HelpId.SELECT_PRESETS)
    window.select_all_button.clicked.connect(lambda: window.set_all_presets_checked(True))
    window.manual_adjustments = QCheckBox("Edit manually")
    window.manual_adjustments.setToolTip(
        "Allow preset names, snapshot names, and gain adjustments to be edited manually."
    )
    window.manual_adjustments.setProperty("help_id", HelpId.MANUAL_EDITING)
    window.manual_adjustments.toggled.connect(window._manual_adjustments_toggled)
    window.show_legend_button = QPushButton("Show legend")
    window.show_legend_button.setToolTip("Show the preset table symbol legend.")
    window.show_legend_button.setProperty("help_id", HelpId.SNAPSHOTS_SOLOS_IGNORED)
    window.show_legend_button.clicked.connect(window.show_preset_table_legend)
    window.unselect_all_button = QPushButton("Unselect all")
    window.unselect_all_button.setIcon(
        window.style().standardIcon(QStyle.StandardPixmap.SP_DialogResetButton)
    )
    window.unselect_all_button.setToolTip("Exclude every preset in this setlist.")
    window.unselect_all_button.setProperty("help_id", HelpId.SELECT_PRESETS)
    window.unselect_all_button.clicked.connect(lambda: window.set_all_presets_checked(False))
    window.select_diff_button = QPushButton("Select changed")
    window.select_diff_button.setIcon(
        window.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton)
    )
    window.select_diff_button.setToolTip(
        "Choose another Helix file and skip snapshots whose loudness-affecting content is unchanged."
    )
    window.select_diff_button.setProperty("help_id", HelpId.SELECT_CHANGED)
    window.select_diff_button.clicked.connect(window.select_diff_presets)
    window.comparison_enabled = QCheckBox("Enabled")
    window.comparison_enabled.setToolTip(
        "Enable snapshot exclusions from the selected comparison file."
    )
    window.comparison_enabled.setProperty("help_id", HelpId.SELECT_CHANGED)
    window.comparison_enabled.setEnabled(False)
    window.comparison_enabled.toggled.connect(window._comparison_enabled_toggled)
    preset_header.addWidget(window.preset_help_button)
    preset_header.addWidget(window.select_all_button)
    preset_header.addWidget(window.unselect_all_button)
    preset_header.addWidget(window.select_diff_button)
    preset_header.addWidget(window.comparison_enabled)
    layout.addWidget(window.preset_header)
    layout.addWidget(window.preset_empty_state)
    layout.addWidget(window.preset_table)
    preset_table_note_row = QHBoxLayout()
    preset_table_note_row.addWidget(window.preset_table_note)
    preset_table_note_row.addStretch()
    preset_table_note_row.addWidget(window.show_legend_button)
    preset_table_note_row.addWidget(window.manual_adjustments)
    preset_table_note_row.addWidget(window.preset_csv_controls)
    layout.addLayout(preset_table_note_row)
    layout.addWidget(window.preset_measurement_time_estimate)
    layout.addWidget(window.single_slot)
    window.presets = content
    window._sync_preset_empty_state_height()
    window._show_preset_empty_state()
    return content


def build_preset_empty_state(window: MainWindowLike) -> QWidget:
    pane = QWidget()
    pane.setObjectName("presetEmptyState")
    pane.setAutoFillBackground(True)
    pane.setStyleSheet("QWidget#presetEmptyState { background: #fefefe; border: none; }")
    pane.setMinimumHeight(160)
    pane.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    layout = QVBoxLayout(pane)
    layout.setContentsMargins(32, 4, 32, 4)
    layout.setSpacing(1)
    layout.addStretch(1)

    logo = QLabel()
    logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
    logo.setFixedSize(PRESET_EMPTY_LOGO_SIZE)
    logo_pixmap = QPixmap(str(ASSETS_DIR / "matchmatch-logo.png"))
    if not logo_pixmap.isNull():
        logo.setPixmap(_fixed_size_pixmap(logo_pixmap, PRESET_EMPTY_LOGO_SIZE))
    window.preset_empty_logo = logo
    layout.addWidget(logo, 0, Qt.AlignmentFlag.AlignHCenter)

    recent_files = QComboBox(pane)
    recent_files.setToolTip("Open a recently loaded Helix setlist or preset file.")
    recent_files.setMaximumWidth(340)
    recent_files.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
    recent_files.activated.connect(window._recent_file_activated)
    window.recent_files = recent_files
    window._refresh_recent_files_selector()

    open_button = QToolButton(pane)
    open_button.setText("Open preset/setlist")
    open_button.setIcon(window.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
    open_button.setIconSize(QSize(64, 64))
    open_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
    open_button.setToolTip("Open a Helix preset or setlist file.")
    open_button.setProperty("help_id", HelpId.OPEN_FILES)
    open_button.setMinimumSize(260, 124)
    open_button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
    open_button.setAutoRaise(True)
    open_button.clicked.connect(window.browse_input)
    window.preset_empty_open_button = open_button
    layout.addWidget(open_button, 0, Qt.AlignmentFlag.AlignHCenter)
    layout.addWidget(recent_files, 0, Qt.AlignmentFlag.AlignHCenter)
    layout.addStretch(1)
    return pane


def build_device_settings(window: MainWindowLike) -> QWidget:
    content = QWidget()
    content.setProperty("help_id", HelpId.BACKENDS)
    layout = QVBoxLayout(content)
    window.device_stack = QStackedWidget()
    layout.addWidget(window.device_stack)
    window.device_settings = content
    return content


def build_progress(window: MainWindowLike) -> QWidget:
    pane = QWidget()
    window.progress_group = pane
    pane.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
    layout = QVBoxLayout(pane)
    layout.setContentsMargins(0, 0, 0, 0)
    window.measurement_panel_separator = QFrame()
    window.measurement_panel_separator.setFrameShape(QFrame.Shape.HLine)
    window.measurement_panel_separator.setFrameShadow(QFrame.Shadow.Sunken)
    layout.addWidget(window.measurement_panel_separator)
    window.current = QLabel("")
    window.preset_progress = QProgressBar()
    window.preset_progress.setRange(0, 1)
    window.measured_loudness = LoudnessBar()
    window.loudness_scale = LoudnessScale()
    meters = QWidget()
    meter_layout = QGridLayout(meters)
    meter_layout.setContentsMargins(0, 0, 0, 0)
    meter_layout.setHorizontalSpacing(8)
    meter_layout.setVerticalSpacing(2)
    window.measured_loudness_reading = QLabel()
    meter_layout.addWidget(window.measured_loudness_reading, 0, 0)
    meter_layout.addWidget(window.measured_loudness, 0, 1)
    meter_layout.addWidget(window.loudness_scale, 1, 1)
    meter_layout.setColumnStretch(1, 1)
    layout.addWidget(window.current)
    layout.addWidget(meters)
    layout.addWidget(window.preset_progress)
    window._reset_loudness_bars()
    pane.hide()
    return pane


def build_retained_csv(window: MainWindowLike) -> QWidget:
    pane = QWidget()
    window.retained_csv_pane = pane
    layout = QVBoxLayout(pane)
    layout.setContentsMargins(0, 0, 0, 0)
    window.retained_csv_label = _label(
        "Retained CSV", "Exact measurement CSV path when temporary files are retained."
    )
    window.retained_csv = QLineEdit()
    window.retained_csv.setReadOnly(True)
    layout.addWidget(window.retained_csv_label)
    layout.addWidget(window.retained_csv)
    pane.hide()
    return pane


def build_footer(window: MainWindowLike) -> None:
    object_parent = cast(QObject, window)
    window.phase_icon = QLabel()
    window.phase_icon.setFixedSize(16, 16)
    window.phase = QLabel()
    window.processing_dot = QLabel()
    window.processing_dot.setFixedSize(14, 14)
    window.processing_dot.setToolTip(
        "Grey when idle; pulses green while processing; red when a measurement was cancelled."
    )
    window.processing_dot_effect = QGraphicsOpacityEffect(window.processing_dot)
    window.processing_dot.setGraphicsEffect(window.processing_dot_effect)
    window.busy_animation = QPropertyAnimation(
        window.processing_dot_effect, b"opacity", object_parent
    )
    window.busy_animation.setDuration(2000)
    window.busy_animation.setLoopCount(-1)
    window.busy_animation.setEasingCurve(QEasingCurve.Type.InOutSine)
    window.busy_animation.setKeyValueAt(0.0, 0.2)
    window.busy_animation.setKeyValueAt(0.5, 1.0)
    window.busy_animation.setKeyValueAt(1.0, 0.2)
    window._set_processing_dot(False)
    footer = window.statusBar()
    footer.setSizeGripEnabled(False)
    footer.addWidget(window.phase_icon)
    footer.addWidget(window.phase)
    footer.addPermanentWidget(window.processing_dot)


def build_log(window: MainWindowLike) -> QWidget:
    content = QGroupBox("Log")
    content.setProperty("help_id", HelpId.TROUBLESHOOTING)
    layout = QVBoxLayout(content)
    filter_row = QHBoxLayout()
    filter_row.addWidget(
        _label("Minimum log level", "Hide log entries below the selected severity.")
    )
    window.log_level = QComboBox()
    window.log_level.addItems(["Debug", "Info", "Warning", "Error"])
    window.log_level.setCurrentText("Info")
    window.log_level.currentTextChanged.connect(window._refresh_log)
    filter_row.addWidget(window.log_level)
    filter_row.addStretch()
    window.log = QTextEdit()
    window.log.setReadOnly(True)
    window.log.setMinimumHeight(140)
    window.log_section = window.log
    window.log_controller = GuiLogController(
        log_widget=window.log,
        level_selector=window.log_level,
    )
    window.log_entries = window.log_controller.entries
    window._recent_progress_events = window.log_controller.recent_progress_events
    layout.addLayout(filter_row)
    layout.addWidget(window.log)
    return content


def build_metadata(window: MainWindowLike) -> QWidget:
    content = QWidget()
    content.setProperty("help_id", HelpId.METADATA)
    layout = QVBoxLayout(content)
    window.metadata_text = QTextEdit()
    window.metadata_text.setReadOnly(True)
    window.metadata_text.setMinimumHeight(180)
    window.metadata_text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
    window.metadata_text.setFont(QFont("monospace"))
    window.metadata_highlighter = JsonSyntaxHighlighter(window.metadata_text.document())
    layout.addWidget(window.metadata_text)
    window._set_metadata({})
    return content


def build_advanced(window: MainWindowLike) -> QWidget:
    content = QWidget()
    layout = QVBoxLayout(content)
    layout.setContentsMargins(0, 0, 0, 0)
    window.advanced_tabs = CurrentPageHeightTabWidget()
    device_tab_index = window.advanced_tabs.addTab(window._build_device_settings(), "Device")
    files_tab_index = window.advanced_tabs.addTab(window._build_files(), "Files")
    timing_tab_index = window.advanced_tabs.addTab(window._build_measurement(), "Timing")
    lufs_tab_index = window.advanced_tabs.addTab(window._build_lufs(), "LUFS")
    misc_tab_index = window.advanced_tabs.addTab(window._build_misc(), "Misc")
    metadata_tab_index = window.advanced_tabs.addTab(window._build_metadata(), "Meta Data")
    diagnostics_tab_index = window.advanced_tabs.addTab(window._build_diagnostics(), "Diagnostics")
    tab_bar = window.advanced_tabs.tabBar()
    tab_bar.setTabData(device_tab_index, HelpId.BACKENDS)
    tab_bar.setTabData(files_tab_index, HelpId.FILES_TAB)
    tab_bar.setTabData(timing_tab_index, HelpId.TIMING)
    tab_bar.setTabData(lufs_tab_index, HelpId.LUFS_LOUDNESS)
    tab_bar.setTabData(misc_tab_index, HelpId.SNAPSHOT_COUNT)
    tab_bar.setTabData(metadata_tab_index, HelpId.METADATA)
    tab_bar.setTabData(diagnostics_tab_index, HelpId.TROUBLESHOOTING)
    window.advanced_tabs.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
    window.advanced_tabs.currentChanged.connect(window._schedule_resize_for_content)
    advanced_header = QHBoxLayout()
    advanced_header.setContentsMargins(0, 0, 0, 0)
    advanced_header.addStretch()
    window.advanced_help_button = window._help_tool_button(
        "Open help for current advanced tab",
        window._open_current_advanced_help,
    )
    advanced_header.addWidget(window.advanced_help_button)
    layout.addLayout(advanced_header)
    layout.addWidget(window.advanced_tabs)
    window.advanced = content
    window.advanced.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
    window.advanced.setToolTip("Show less frequently changed settings and diagnostic details.")
    window.advanced.setVisible(window.advanced_button.isChecked())
    return window.advanced


def build_files(window: MainWindowLike) -> QWidget:
    content = QWidget()
    content.setProperty("help_id", HelpId.FILES_TAB)
    form = QFormLayout(content)
    window.config_path = QLineEdit()
    config_browse = QPushButton("Browse")
    config_browse.setIcon(window.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
    config_browse.setToolTip("Choose an optional TOML configuration file.")
    config_browse.clicked.connect(window.browse_config)
    window.config_export_button = QPushButton("Export")
    window.config_export_button.setIcon(
        window.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
    )
    window.config_export_button.setToolTip(
        "Save a TOML configuration file populated with the active GUI values."
    )
    window.config_export_button.clicked.connect(window.export_config)
    form.addRow(
        _label("Config", "Optional TOML file providing saved MatchPatch defaults."),
        _path_row(window.config_path, config_browse, window.config_export_button),
    )
    window.custom_adjustments_path = QLineEdit()
    window.custom_adjustments_path.setProperty("help_id", HelpId.CUSTOM_ADJUSTMENTS)
    custom_adjustments_browse = QPushButton("Browse")
    custom_adjustments_browse.setIcon(
        window.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton)
    )
    custom_adjustments_browse.setToolTip(
        "Choose an optional CSV of per-preset snapshot loudness target bumps."
    )
    custom_adjustments_browse.setProperty("help_id", HelpId.CUSTOM_ADJUSTMENTS)
    custom_adjustments_browse.clicked.connect(window.browse_custom_adjustments)
    form.addRow(
        _label(
            "Custom adjustments",
            "Optional CSV mapping preset IDs to per-snapshot target loudness bumps.",
        ),
        _path_row(window.custom_adjustments_path, custom_adjustments_browse),
    )
    window.reference_di = QLineEdit()
    window.reference_di.setProperty("help_id", HelpId.REFERENCE_DI)
    window.reference_di.textChanged.connect(window._refresh_measurement_time_estimate)
    reference_browse = QPushButton("Browse")
    reference_browse.setIcon(window.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
    reference_browse.setToolTip("Choose the clean DI WAV used for evaluation measurements.")
    reference_browse.setProperty("help_id", HelpId.REFERENCE_DI)
    reference_browse.clicked.connect(window.browse_reference)
    form.addRow(
        _label("Reference DI", "Clean guitar DI WAV replayed through each preset."),
        _path_row(window.reference_di, reference_browse),
    )
    window.keep_temp = QCheckBox()
    form.addRow(
        _label(
            "Keep temporary files",
            "Retain the measurement CSV for inspection after processing.",
        ),
        window.keep_temp,
    )
    return content


def build_diagnostics(window: MainWindowLike) -> QWidget:
    window.diagnostics_panel = DiagnosticsPanel(
        log_widget=window._build_log(),
        parent=cast(QWidget, window),
    )
    window.diagnostics_panel.export_bundle_requested.connect(window.export_diagnostic_bundle)
    window.diagnostics_panel.copy_summary_requested.connect(window.copy_diagnostic_summary)
    window.diagnostics_panel.preflight_requested.connect(window.run_preflight_check)

    window.diagnostics_privacy_panel = window.diagnostics_panel.privacy_panel
    window.diagnostics_privacy_notice = window.diagnostics_panel.privacy_notice
    window.diagnostic_bundle_button = window.diagnostics_panel.export_bundle_button
    window.diagnostic_summary_button = window.diagnostics_panel.copy_summary_button
    window.preflight_button = window.diagnostics_panel.preflight_button
    return window.diagnostics_panel


def build_misc(window: MainWindowLike) -> QWidget:
    content = QWidget()
    content.setProperty("help_id", HelpId.SNAPSHOT_COUNT)
    form = QFormLayout(content)
    window.snapshot_count_input = QSpinBox()
    window.snapshot_count_input.setProperty("help_id", HelpId.SNAPSHOT_COUNT)
    window.snapshot_count_input.setRange(1, 8)
    window.snapshot_count_input.setValue(window.snapshot_count)
    window.snapshot_count_input.valueChanged.connect(window._snapshot_count_changed)
    window.snapshot_count_input.valueChanged.connect(window._refresh_measurement_time_estimate)
    form.addRow(
        _label("Snapshots", "Number of snapshots to measure and normalize."),
        window.snapshot_count_input,
    )
    return content


def build_measurement(window: MainWindowLike) -> QWidget:
    content = QWidget()
    content.setProperty("help_id", HelpId.TIMING)
    layout = QVBoxLayout(content)
    preset_row = QHBoxLayout()
    preset_row.addWidget(_label("Parameters", "Choose a measurement timing preset."))
    window.measurement_parameter_preset = QComboBox()
    window.measurement_parameter_preset.setProperty("help_id", HelpId.TIMING)
    window.measurement_parameter_preset.addItems(list(MEASUREMENT_TIMING_PRESETS))
    window.measurement_parameter_preset.currentTextChanged.connect(
        window._measurement_parameter_preset_changed
    )
    preset_row.addWidget(window.measurement_parameter_preset)
    window.apply_measurement_parameters_button = QPushButton("Apply")
    window.apply_measurement_parameters_button.clicked.connect(
        window.apply_measurement_parameter_preset
    )
    preset_row.addWidget(window.apply_measurement_parameters_button)
    preset_row.addStretch()
    layout.addLayout(preset_row)

    form = QFormLayout()
    layout.addLayout(form)

    window.analysis_window = QLineEdit("3.0")
    form.addRow(
        _label(
            "Analysis window (s)",
            "LUFS analysis window used during measurements; not optimized automatically.",
        ),
        window.analysis_window,
    )
    window.analysis_interval = QLineEdit("0.1")
    form.addRow(
        _label(
            "Analysis interval (s)",
            "Step size between LUFS analysis windows; not optimized automatically.",
        ),
        window.analysis_interval,
    )
    window.pre_roll = QLineEdit(str(MEASUREMENT_TIMING_PRESETS["Default"]["pre_roll"]))
    form.addRow(
        _label("Pre-roll (s)", "Silence recorded before the reference DI playback."),
        window.pre_roll,
    )
    window.post_roll = QLineEdit(str(MEASUREMENT_TIMING_PRESETS["Default"]["post_roll"]))
    form.addRow(
        _label("Post-roll (s)", "Silence recorded after the reference DI playback."),
        window.post_roll,
    )
    window.round_trip_latency = QLineEdit(
        str(MEASUREMENT_TIMING_PRESETS["Default"]["round_trip_latency"])
    )
    window.preset_wait = QLineEdit(str(MEASUREMENT_TIMING_PRESETS["Default"]["preset_wait"]))
    window.snapshot_wait = QLineEdit(str(MEASUREMENT_TIMING_PRESETS["Default"]["snapshot_wait"]))
    form.addRow(
        _label("Snapshot wait (s)", "Pause after switching snapshots before continuing."),
        window.snapshot_wait,
    )
    window.measurement_wait = QLineEdit(
        str(MEASUREMENT_TIMING_PRESETS["Default"]["measurement_wait"])
    )
    form.addRow(
        _label("Measurement wait (s)", "Pause before capturing loudness after a snapshot change."),
        window.measurement_wait,
    )
    form.addRow(
        _label("Preset wait (s)", "Pause after switching presets before continuing."),
        window.preset_wait,
    )
    form.addRow(
        _label("Round-trip latency (s)", "Recorded signal offset caused by audio I/O latency."),
        window.round_trip_latency,
    )
    window.measurement_time_estimate = QLabel()
    window.measurement_time_estimate.setWordWrap(True)
    window.measurement_time_estimate.setToolTip(
        "Estimated total measurement timing divided by loaded presets and snapshots."
    )
    layout.addWidget(window.measurement_time_estimate)
    for timing_input in (
        window.pre_roll,
        window.post_roll,
        window.round_trip_latency,
        window.preset_wait,
        window.snapshot_wait,
        window.measurement_wait,
    ):
        timing_input.textChanged.connect(window._refresh_measurement_time_estimate)
    window._refresh_measurement_time_estimate()
    window.determine_parameters_button = QPushButton("Determine optimal parameters")
    window.determine_parameters_button.setProperty("help_id", HelpId.OPTIMIZE_TIMING)
    window.determine_parameters_button.clicked.connect(window.determine_optimal_parameters)
    layout.addWidget(window.determine_parameters_button)
    window.determine_parameters_hint = QLabel()
    window.determine_parameters_hint.setWordWrap(True)
    window.determine_parameters_hint.setTextFormat(Qt.TextFormat.PlainText)
    window.determine_parameters_hint.setSizePolicy(
        QSizePolicy.Policy.Preferred,
        QSizePolicy.Policy.Maximum,
    )
    layout.addWidget(window.determine_parameters_hint)
    layout.addStretch()
    return content


def build_lufs(window: MainWindowLike) -> QWidget:
    content = QWidget()
    content.setProperty("help_id", HelpId.LUFS_LOUDNESS)
    form = QFormLayout(content)
    window.target_lufs = QLineEdit("-16.0")
    window.target_lufs.setProperty("help_id", HelpId.LUFS_LOUDNESS)
    form.addRow(
        _label("Target LUFS", "Desired loudness used to calculate snapshot gain corrections."),
        window.target_lufs,
    )
    window.solo_gain_bump_db = QLineEdit("3.0")
    form.addRow(
        _label("Solo boost (dB)", "Additional output gain added to snapshots identified as solos."),
        window.solo_gain_bump_db,
    )
    window.solo_regex = QLineEdit(NormalizationPolicy().solo_regex)
    window.solo_regex.setProperty("help_id", HelpId.SNAPSHOTS_SOLOS_IGNORED)
    window.solo_regex.setMaximumWidth(220)
    window.solo_regex.setToolTip(
        "Case-insensitive regular expression used to identify solo snapshots."
    )
    window.ignore_snapshot_regex = QLineEdit(NormalizationPolicy().ignore_snapshot_regex)
    window.ignore_snapshot_regex.setProperty("help_id", HelpId.SNAPSHOTS_SOLOS_IGNORED)
    window.ignore_snapshot_regex.setMaximumWidth(260)
    window.ignore_snapshot_regex.setToolTip(
        "Regular expression used to identify snapshots skipped during normalization."
    )
    window.ignore_snapshot_regex.textChanged.connect(window._refresh_all_snapshot_names)
    window.ignore_snapshot_regex.textChanged.connect(window._refresh_measurement_time_estimate)
    snapshot_regexes = QGroupBox("Snapshot name regex")
    snapshot_regex_layout = QFormLayout(snapshot_regexes)
    snapshot_regex_layout.setContentsMargins(8, 8, 8, 8)
    snapshot_regex_layout.setSpacing(6)
    snapshot_regex_layout.addRow(_label("Solo", window.solo_regex.toolTip()), window.solo_regex)
    snapshot_regex_layout.addRow(
        _label("Ignored", window.ignore_snapshot_regex.toolTip()),
        window.ignore_snapshot_regex,
    )
    form.addRow(snapshot_regexes)
    return content


def _path_row(field: QLineEdit, *buttons: QPushButton) -> QWidget:
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(field)
    for button in buttons:
        layout.addWidget(button)
    return widget


def _button_row(*buttons: QPushButton) -> QWidget:
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addStretch()
    for button in buttons:
        layout.addWidget(button)
    return widget


def _label(text: str, tooltip: str) -> QLabel:
    label = QLabel(text)
    label.setToolTip(tooltip)
    return label


__all__ = [
    "MEASUREMENT_TIMING_PRESETS",
    "PRESET_EMPTY_LOGO_SIZE",
    "TOOLBAR_ICON_SIZE",
    "TOOLBAR_VERTICAL_PADDING",
    "CurrentPageHeightTabWidget",
    "JsonSyntaxHighlighter",
    "build_advanced",
    "build_device_settings",
    "build_diagnostics",
    "build_files",
    "build_footer",
    "build_log",
    "build_lufs",
    "build_measurement",
    "build_metadata",
    "build_misc",
    "build_preset_advanced_splitter",
    "build_preset_empty_state",
    "build_presets",
    "build_progress",
    "build_retained_csv",
    "build_toolbar",
]
