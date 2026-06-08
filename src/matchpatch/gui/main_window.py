"""Main MatchPatch GUI window."""

from __future__ import annotations

import csv
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any, Iterator

from PySide6.QtCore import (
    QAbstractAnimation,
    QCoreApplication,
    QEasingCurve,
    QEvent,
    QItemSelectionModel,
    QModelIndex,
    QObject,
    QPropertyAnimation,
    QRect,
    QSize,
    QThread,
    QTimer,
    Signal,
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
    QPainterPath,
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
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
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

from matchpatch.config import Config, config_value, default_config, export_config, load_config
from matchpatch.custom_adjustments import CustomAdjustments, load_custom_adjustments_file
from matchpatch.devices import get_device_profile, list_device_profiles
from matchpatch.devices.base import NormalizationPolicy, PatchFileAdjustments
from matchpatch.gui.device_panels import HelixSettingsPanel
from matchpatch.gui.dialogs import ASSETS_DIR, AboutDialog, HelpDialog
from matchpatch.gui.snapshot_header import SnapshotHeader
from matchpatch.gui.worker import (
    HardwareCheckWorker,
    MeasurementOptimizationWorker,
    NormalizationWorker,
)
from matchpatch.measurement_optimizer import (
    TIMING_PARAMETERS,
    OptimizationProgress,
    StabilityStatistics,
)
from matchpatch.normalize import (
    apply_config,
    parse_args,
    request_from_args,
    wsl_path_to_windows,
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
    r"(?:\S+\s+)?(?P<before>-?\d+(?:\.\d+)?) dB -> (?P<after>-?\d+(?:\.\d+)?) dB "
    r"\(Delta: (?P<delta>[+-]\d+(?:\.\d+)?) dB\)$"
)
GAIN_STABLE_PATTERN = re.compile(
    r"^\[GAIN\] (?P<patch>\d{2}[A-D]) (?P<label>.*?) \| "
    r"stable at (?:\S+\s+)?(?P<after>-?\d+(?:\.\d+)?) dB "
    r"\(Delta: (?P<delta>[+-]\d+(?:\.\d+)?) dB\)$"
)
GAIN_BAD_LUFS_PATTERN = re.compile(
    r"^\[GAIN\] (?P<patch>\d{2}[A-D]) (?P<label>.*?) \| "
    r"(?:bad LUFS|measurement unavailable)(?: \((?P<detail>.*)\))?$"
)
GAIN_PRESET_SYNC_PATTERN = re.compile(r"^\[GAIN\] (?P<patch>\d{2}[A-D]): synchronized\b")
BAD_LUFS_ROW_BACKGROUND = QColor("#fee2e2")
BAD_LUFS_FOREGROUND = QColor("#b91c1c")
NORMALIZATION_FOCUS_BLUE = QColor("#2563eb")
NORMALIZATION_FOCUS_BACKGROUND = QColor("#dbeafe")
MANUAL_NAME_MODIFIED_BACKGROUND = QColor("#fef3c7")
IGNORED_SNAPSHOT_BACKGROUND = QColor("#e5e7eb")
IGNORED_SNAPSHOT_FOREGROUND = QColor("#4b5563")
HELIX_NAME_PATTERN = re.compile(r"""^[A-Za-z0-9\-_+=!@#$&()?:'",./ ]*$""")
HELIX_NAME_CHAR_PATTERN = re.compile(r"""[A-Za-z0-9\-_+=!@#$&()?:'",./ ]""")
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


@dataclass(frozen=True)
class _PresetSelectionState:
    checked_patches: frozenset[str]
    selected_patches: frozenset[str]
    current_patch: str | None


@dataclass(frozen=True)
class MeasurementOptimizationSettings:
    pre_roll: float
    post_roll: float
    round_trip_latency: float
    preset_wait: float
    snapshot_wait: float
    measurement_wait: float
    stability_runs: int
    termination_tolerance: float
    stability_tolerance: float
    pinned_parameters: tuple[str, ...] = ()


def _optimization_start_values_from_settings(
    settings: MeasurementOptimizationSettings,
    parameters: tuple[Any, ...] = TIMING_PARAMETERS,
) -> dict[str, float]:
    values = {parameter.name: float(getattr(settings, parameter.name)) for parameter in parameters}
    for parameter in parameters:
        values[parameter.name] = max(
            values[parameter.name],
            parameter.lower_bound(values),
            parameter.stable_start(values),
        )
    return values


def _max_bisection_runs(
    start: float,
    low: float,
    termination_tolerance_percent: float,
) -> int:
    tolerance = abs(start) * termination_tolerance_percent / 100.0
    if tolerance == 0:
        tolerance = termination_tolerance_percent / 1000.0
    if start - low <= tolerance:
        return 0
    return max(0, math.ceil(math.log2((start - low) / tolerance)))


def _optimization_duration_estimate(settings: MeasurementOptimizationSettings) -> str:
    values = _optimization_start_values_from_settings(settings)
    optimized_parameters = tuple(
        parameter
        for parameter in TIMING_PARAMETERS
        if parameter.name not in settings.pinned_parameters
    )
    total_runs = 0
    for parameter in optimized_parameters:
        start = values[parameter.name]
        bisection_runs = _max_bisection_runs(
            start,
            parameter.lower_bound(values),
            settings.termination_tolerance,
        )
        total_runs += bisection_runs

    total_seconds = (
        total_runs * settings.stability_runs * _two_snapshot_optimization_run_seconds(values)
    )
    parameter_count = len(optimized_parameters)
    duration = escape(_format_duration(total_seconds))
    return (
        "Parameter optimization is running and can take some time. "
        f"Worst-case estimate: up to {total_runs} bisection checks across "
        f"{parameter_count} parameters, about <strong>{duration}</strong> "
        "of measurement time from the selected start values. Actual duration depends "
        "on the parameters and can be shorter."
    )


def _two_snapshot_optimization_run_seconds(values: dict[str, float]) -> float:
    snapshot_capture_seconds = (
        values["snapshot_wait"]
        + values["measurement_wait"]
        + values["pre_roll"]
        + values["post_roll"]
        + values["round_trip_latency"]
    )
    return 2 * values["preset_wait"] + 2 * snapshot_capture_seconds


def _format_duration(seconds: float) -> str:
    rounded = max(0, math.ceil(seconds))
    minutes, remaining_seconds = divmod(rounded, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} h {minutes} min"
    if minutes:
        return f"{minutes} min {remaining_seconds} s"
    return f"{remaining_seconds} s"


def _format_short_seconds(seconds: float) -> str:
    if seconds < 10:
        return f"{seconds:.2f} s"
    if seconds < 60:
        return f"{seconds:.1f} s"
    return _format_duration(seconds)


@dataclass(frozen=True)
class _MeasurementProgressEstimate:
    preset_wait: float
    snapshot_wait: float
    measurement_wait: float
    pre_roll: float
    post_roll: float
    round_trip_latency: float
    reference_audio_seconds: float = 0.0

    @classmethod
    def from_request(cls, request: NormalizationRequest) -> _MeasurementProgressEstimate:
        return cls(
            preset_wait=_float_or_zero(request.preset_wait),
            snapshot_wait=_float_or_zero(request.snapshot_wait),
            measurement_wait=_float_or_zero(request.measurement_wait),
            pre_roll=_float_or_zero(request.pre_roll),
            post_roll=_float_or_zero(request.post_roll),
            round_trip_latency=_float_or_zero(request.round_trip_latency),
            reference_audio_seconds=_reference_audio_seconds(request.reference_di),
        )

    @property
    def snapshot_seconds(self) -> float:
        return (
            self.snapshot_wait
            + self.measurement_wait
            + self.pre_roll
            + self.post_roll
            + self.round_trip_latency
            + self.reference_audio_seconds
        )

    def total_seconds(self, preset_total: int, snapshot_total: int) -> float:
        return (
            preset_total * self.preset_wait + preset_total * snapshot_total * self.snapshot_seconds
        )

    def total_seconds_for_counts(self, preset_total: int, measured_snapshot_total: int) -> float:
        return preset_total * self.preset_wait + measured_snapshot_total * self.snapshot_seconds

    def seconds_per_snapshot(self, preset_total: int, snapshot_total: int) -> float:
        measured_snapshots = max(1, preset_total) * max(1, snapshot_total)
        return self.total_seconds(preset_total, snapshot_total) / measured_snapshots

    def seconds_per_measured_snapshot(
        self,
        preset_total: int,
        measured_snapshot_total: int,
    ) -> float:
        return self.total_seconds_for_counts(
            preset_total,
            measured_snapshot_total,
        ) / max(1, measured_snapshot_total)

    def remaining_seconds(
        self, event: ProgressEvent, preset_total: int, snapshot_total: int
    ) -> float:
        completed_presets = max(0, (event.preset_index or 1) - 1)
        completed_snapshots = completed_presets * snapshot_total
        if event.snapshot is not None:
            completed_snapshots += max(0, event.snapshot - 1)
            if event.kind == "snapshot_completed":
                completed_snapshots += 1
        remaining_preset_waits = (
            preset_total - completed_presets
            if event.snapshot is None
            else preset_total - (event.preset_index or 1)
        )
        remaining_snapshots = max(0, preset_total * snapshot_total - completed_snapshots)
        return max(0, remaining_preset_waits) * self.preset_wait + (
            remaining_snapshots * self.snapshot_seconds
        )

    def remaining_seconds_for_plan(
        self,
        event: ProgressEvent,
        plan: _MeasurementProgressPlan,
    ) -> float:
        completed_presets = max(0, (event.preset_index or 1) - 1)
        completed_snapshots = plan.completed_snapshots(event)
        remaining_preset_waits = (
            plan.preset_total - completed_presets
            if event.snapshot is None
            else plan.preset_total - (event.preset_index or 1)
        )
        remaining_snapshots = max(0, plan.measured_snapshot_total - completed_snapshots)
        return max(0, remaining_preset_waits) * self.preset_wait + (
            remaining_snapshots * self.snapshot_seconds
        )


@dataclass(frozen=True)
class _MeasurementProgressPlan:
    preset_snapshots: tuple[tuple[str, tuple[int, ...]], ...]

    @property
    def preset_total(self) -> int:
        return len(self.preset_snapshots)

    @property
    def measured_snapshot_total(self) -> int:
        return sum(len(snapshots) for _, snapshots in self.preset_snapshots)

    def completed_snapshots(self, event: ProgressEvent) -> int:
        if not self.preset_snapshots:
            return 0

        preset_index = max(1, event.preset_index or 1)
        completed = sum(
            len(snapshots) for _, snapshots in self.preset_snapshots[: preset_index - 1]
        )
        current = self._snapshots_for_event(event)
        if event.snapshot is not None:
            completed += sum(1 for snapshot in current if snapshot < event.snapshot)
            if event.kind == "snapshot_completed" and event.snapshot in current:
                completed += 1
        return completed

    def progress_value(self, event: ProgressEvent) -> int:
        completed = self.completed_snapshots(event)
        if event.kind == "snapshot_started" and event.snapshot in self._snapshots_for_event(event):
            return completed + 1
        return completed

    def _snapshots_for_event(self, event: ProgressEvent) -> tuple[int, ...]:
        if event.device_patch:
            for patch, snapshots in self.preset_snapshots:
                if patch == event.device_patch:
                    return snapshots

        preset_index = event.preset_index or 1
        if 1 <= preset_index <= len(self.preset_snapshots):
            return self.preset_snapshots[preset_index - 1][1]
        return ()


def _float_or_zero(value: float | None) -> float:
    return float(value) if value is not None else 0.0


def _reference_audio_seconds(path: Path | str) -> float:
    try:
        import soundfile as sf

        info = sf.info(str(path))
    except Exception:  # noqa: BLE001
        return 0.0

    if info.frames <= 0 or info.samplerate <= 0:
        return 0.0
    return max(0.0, info.frames / info.samplerate)


PRESET_TABLE_CSV_DELIMITER = "|"
SNAPSHOT_TABLE_START_COLUMN = 3
SNAPSHOT_TABLE_COLUMN_STRIDE = 3
PRESET_TABLE_ATTENTION_ROLE = Qt.ItemDataRole.UserRole + 1
ADJUSTMENT_VALUE_ROLE = Qt.ItemDataRole.UserRole + 2
MANUAL_NAME_MODIFIED_ROLE = Qt.ItemDataRole.UserRole + 3
BAD_LUFS_HIGHLIGHT_ROLE = Qt.ItemDataRole.UserRole + 4
RECORDED_OUTPUT_PATH_ROLE = Qt.ItemDataRole.UserRole + 5
SNAPSHOT_OUTPUT_LEVELS_ROLE = Qt.ItemDataRole.UserRole + 6
NORMALIZATION_FOCUS_ROLE = Qt.ItemDataRole.UserRole + 7
IGNORED_SNAPSHOT_ROLE = Qt.ItemDataRole.UserRole + 8
CUSTOM_ADJUSTMENT_COLOR = "#2563eb"
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
TOOLBAR_ICON_SIZE = 20
PRESET_EMPTY_LOGO_SIZE = QSize(360, 360)


def _fixed_size_pixmap(source: QPixmap, size: QSize) -> QPixmap:
    screen = QApplication.primaryScreen()
    ratio = screen.devicePixelRatio() if screen else 1.0
    physical_size = QSize(
        min(source.width(), max(1, round(size.width() * ratio))),
        min(source.height(), max(1, round(size.height() * ratio))),
    )
    pixmap = source.scaled(
        physical_size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


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

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        super().paint(painter, option, index)
        if not index.data(PRESET_TABLE_ATTENTION_ROLE):
            return

        painter.save()
        painter.setPen(QPen(QColor("#dc2626"), 3))
        painter.drawRect(option.rect.adjusted(1, 1, -2, -2))
        painter.restore()


WINDOWS_PLAYBACK_CODE = (
    "from pathlib import Path\n"
    "import sys\n"
    "import soundfile as sf\n"
    "from matchpatch.audio import play_audio\n"
    "audio, sample_rate = sf.read(Path(sys.argv[1]), dtype='float32', always_2d=True)\n"
    "play_audio(audio, sample_rate)\n"
)


def _windows_playback_path(path: Path) -> str:
    text = str(path)
    if re.match(r"^[A-Za-z]:[\\/]", text) or text.startswith("\\\\") or os.name == "nt":
        return text
    return wsl_path_to_windows(path)


class AudioPlaybackWorker(QThread):
    failed = Signal(str)

    def __init__(
        self,
        path: Path,
        parent: QObject | None = None,
        *,
        windows_python: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.path = path
        self.windows_python = windows_python

    def run(self) -> None:
        try:
            if self.windows_python:
                windows_path = _windows_playback_path(self.path)
                completed = subprocess.run(
                    [self.windows_python, "-c", WINDOWS_PLAYBACK_CODE, windows_path],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                if completed.stderr.strip():
                    self.failed.emit(completed.stderr.strip())
                return

            import soundfile as sf

            from matchpatch.audio import play_audio

            audio, sample_rate = sf.read(self.path, dtype="float32", always_2d=True)
            play_audio(audio, sample_rate)
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            self.failed.emit(detail or str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


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


def _speaker_icon(*, enabled: bool = True) -> QIcon:
    pixmap = QPixmap(56, 56)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    speaker_color = QColor("#475569" if enabled else "#9ca3af")
    painter.setBrush(speaker_color)
    body = QPainterPath()
    body.moveTo(11, 24)
    body.lineTo(21, 24)
    body.lineTo(34, 13)
    body.lineTo(34, 43)
    body.lineTo(21, 32)
    body.lineTo(11, 32)
    body.closeSubpath()
    painter.drawPath(body)
    if enabled:
        painter.setPen(QPen(QColor("#2563eb"), 4))
        painter.drawArc(35, 19, 10, 18, -45 * 16, 90 * 16)
        painter.drawArc(38, 13, 16, 30, -45 * 16, 90 * 16)
    else:
        painter.setPen(QPen(QColor("#6b7280"), 5))
        painter.drawLine(13, 44, 48, 12)
    painter.end()
    return QIcon(pixmap)


def _record_icon(*, recording: bool = True) -> QIcon:
    pixmap = QPixmap(56, 56)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#991b1b" if recording else "#6b7280"), 2))
    painter.setBrush(QColor("#dc2626" if recording else "#9ca3af"))
    painter.drawEllipse(14, 14, 28, 28)
    painter.end()
    return QIcon(pixmap)


def _save_as_icon() -> QIcon:
    pixmap = QPixmap(56, 56)
    pixmap.fill(Qt.GlobalColor.transparent)

    save_pixmap = (
        QApplication.style()
        .standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
        .pixmap(pixmap.size())
    )

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.drawPixmap(0, 0, save_pixmap)

    painter.save()
    painter.translate(42, 40)
    painter.rotate(-35)
    painter.setPen(QPen(QColor("#92400e"), 1))
    painter.setBrush(QColor("#fbbf24"))
    painter.drawRoundedRect(-4, -14, 8, 24, 2, 2)
    painter.setBrush(QColor("#fef3c7"))
    tip = QPainterPath()
    tip.moveTo(-4, -14)
    tip.lineTo(0, -21)
    tip.lineTo(4, -14)
    tip.closeSubpath()
    painter.drawPath(tip)
    painter.setBrush(QColor("#475569"))
    painter.drawRoundedRect(-4, 9, 8, 5, 1, 1)
    painter.restore()

    painter.end()
    return QIcon(pixmap)


def _save_measurement_icon() -> QIcon:
    pixmap = QPixmap(56, 56)
    pixmap.fill(Qt.GlobalColor.transparent)

    save_pixmap = (
        QApplication.style()
        .standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
        .pixmap(pixmap.size())
    )

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.drawPixmap(0, 0, save_pixmap)

    painter.setPen(QPen(QColor("#334155"), 1))
    painter.setBrush(QColor("#f8fafc"))
    painter.drawRoundedRect(29, 27, 22, 22, 4, 4)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#38bdf8"))
    painter.drawRoundedRect(34, 38, 3, 7, 1, 1)
    painter.setBrush(QColor("#22c55e"))
    painter.drawRoundedRect(39, 34, 3, 11, 1, 1)
    painter.setBrush(QColor("#f59e0b"))
    painter.drawRoundedRect(44, 31, 3, 14, 1, 1)
    painter.setPen(QPen(QColor("#475569"), 1))
    painter.drawLine(33, 45, 48, 45)
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
        self.optimization_worker: MeasurementOptimizationWorker | None = None
        self.optimization_dialog: MeasurementOptimizationDialog | None = None
        self.playback_worker: AudioPlaybackWorker | None = None
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
        self._custom_adjustments: CustomAdjustments = {}
        self.log_entries: list[tuple[str, str, str]] = []
        self._processing_dot_green = False
        self._loading_defaults = False
        self._available_backend: str | None = None
        self._pending_backend_check_request: NormalizationRequest | None = None
        self._pending_backend_check_action = "normalization"
        self._pending_optimization_preset_id: int | None = None
        self._pending_optimization_settings: MeasurementOptimizationSettings | None = None
        self._optimization_stability_runs = 3
        self._optimization_termination_tolerance = 10.0
        self._optimization_stability_tolerance = 2.0
        self._last_measurement_optimization_settings: MeasurementOptimizationSettings | None = None
        self._measurement_progress_estimate: _MeasurementProgressEstimate | None = None
        self._measurement_progress_plan: _MeasurementProgressPlan | None = None
        self._deferred_gain_correction_logs: list[str] = []
        self._deferred_gain_correction_patch: str | None = None
        self._playback_toggle_path: Path | None = None
        self._recording_paths: dict[tuple[str, int], Path] = {}
        self._save_as_icon = _save_as_icon()
        self._save_measurement_icon = _save_measurement_icon()
        self._speaker_icon = _speaker_icon(enabled=True)
        self._speaker_off_icon = _speaker_icon(enabled=False)
        self._record_icon = _record_icon(recording=True)
        self._record_off_icon = _record_icon(recording=False)

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
        scroll.setFrameShape(QFrame.Shape.NoFrame)
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
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setIconSize(QSize(TOOLBAR_ICON_SIZE, TOOLBAR_ICON_SIZE))
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
            self._save_as_icon,
            "Save As",
            self,
        )
        self.save_as_action.setToolTip("Save the active Helix file under a new name.")
        self.save_as_action.triggered.connect(self.save_active_file_as)
        toolbar.addAction(self.save_as_action)

        self.save_measurement_action = QAction(
            self._save_measurement_icon,
            "Save Measurement File",
            self,
        )
        self.save_measurement_action.setToolTip(
            "Save the measurement Helix file generated by normalization."
        )
        self.save_measurement_action.triggered.connect(self.save_measurement_file)
        toolbar.addAction(self.save_measurement_action)

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

        self.record_output_button = QToolButton(self)
        self.record_output_button.setIcon(self._record_icon)
        self.record_output_button.setCheckable(True)
        self.record_output_button.setChecked(True)
        self.record_output_button.setToolTip(
            "Record measured processor output for each snapshot during normalization."
        )
        self.record_output_button.setAccessibleName("Record measured output")
        self.record_output_button.toggled.connect(self._record_output_toggle_changed)
        self.record_output_action = toolbar.addWidget(self.record_output_button)

        self.play_recorded_output_button = QToolButton(self)
        self.play_recorded_output_button.setIcon(self._speaker_off_icon)
        self.play_recorded_output_button.setCheckable(True)
        self.play_recorded_output_button.setToolTip(
            "Play measured processor output through the computer speakers after each recording."
        )
        self.play_recorded_output_button.setAccessibleName("Play measured output")
        self.play_recorded_output_button.toggled.connect(self._playback_toggle_changed)
        self.play_recorded_output_action = toolbar.addWidget(self.play_recorded_output_button)

        self.advanced_button = QToolButton(self)
        self.advanced_button.setIcon(_advanced_icon())
        self.advanced_button.setCheckable(True)
        self.advanced_button.setChecked(True)
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
        self.about_action.setToolTip("Show project version, license, and repository information.")
        self.about_action.triggered.connect(self.show_about)
        toolbar.addAction(self.about_action)

        square_button_size = toolbar.iconSize().width() + 14
        for button in (
            self.start_button,
            self.cancel_button,
            self.record_output_button,
            self.play_recorded_output_button,
            self.advanced_button,
        ):
            button.setAutoRaise(True)
            button.setIconSize(toolbar.iconSize())
            button.setFixedSize(square_button_size, square_button_size)
        self.start_cancel_stack.setFixedSize(square_button_size, square_button_size)
        for action in (
            self.open_action,
            self.save_action,
            self.save_as_action,
            self.save_measurement_action,
            self.help_action,
            self.about_action,
        ):
            button = toolbar.widgetForAction(action)
            if button is not None:
                button.setFixedSize(square_button_size, square_button_size)
        toolbar_content_height = max(
            self.start_cancel_stack.height(),
            self.device.sizeHint().height(),
            square_button_size,
        )
        toolbar.setFixedHeight(toolbar_content_height + 4)

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
        self.preset_table.model().rowsInserted.connect(self._refresh_measurement_time_estimate)
        self.preset_table.model().rowsRemoved.connect(self._refresh_measurement_time_estimate)
        self.preset_table.model().modelReset.connect(self._refresh_measurement_time_estimate)
        self.preset_table_note = QLabel(
            "Only non-empty presets are listed. Solo snapshots are marked with a "
            "<span style='color: #f59e0b;'>★</span>."
        )
        self.preset_table_note.setTextFormat(Qt.TextFormat.RichText)
        self.preset_measurement_time_estimate = QLabel()
        self.preset_measurement_time_estimate.setWordWrap(True)
        self.preset_measurement_time_estimate.setToolTip(
            "Estimated total measurement time for the currently selected presets."
        )
        self.save_csv_button = QPushButton()
        self.save_csv_button.setIcon(self._save_as_icon)
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
        self.manual_adjustments = QCheckBox("Edit manually")
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
        layout.addWidget(self.preset_measurement_time_estimate)
        layout.addWidget(self.single_slot)
        self.presets = content
        self._sync_preset_empty_state_height()
        self._show_preset_empty_state()
        return content

    def _build_preset_empty_state(self) -> QWidget:
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
        self.preset_empty_logo = logo
        layout.addWidget(logo, 0, Qt.AlignmentFlag.AlignHCenter)

        file_dialog_title = QLabel("Open setlist/preset file")
        file_dialog_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        file_dialog_title.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        title_font = file_dialog_title.font()
        title_font.setPointSize(
            max(title_font.pointSize() + 2, QApplication.font().pointSize() + 2)
        )
        file_dialog_title.setFont(title_font)
        self.preset_empty_file_dialog_title = file_dialog_title
        layout.addWidget(file_dialog_title)

        file_dialog = QFileDialog(pane, "Choose patch file")
        file_dialog.setOption(QFileDialog.Option.DontUseNativeDialog)
        file_dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptOpen)
        file_dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
        file_dialog.setNameFilter("Patches (*.hls *.hlx)")
        file_dialog.setToolTip("Open a Helix setlist or preset file.")
        file_dialog.setWindowFlags(Qt.WindowType.Widget)
        file_dialog.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        file_dialog.fileSelected.connect(self._open_input_path)
        self.preset_empty_file_dialog = file_dialog
        layout.addWidget(file_dialog, 3)
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
            self.preset_measurement_time_estimate.sizeHint().height(),
            self.preset_csv_controls.sizeHint().height(),
            self.manual_adjustments.sizeHint().height(),
        )
        spacing = self.presets.layout().spacing() if self.presets.layout() is not None else 0
        self.preset_empty_state.setMinimumHeight(table_height + row_height * 3 + spacing * 3 + 4)

    def _show_preset_empty_state(self) -> None:
        self.preset_header.hide()
        self.preset_empty_state.show()
        self.preset_table.hide()
        self.preset_table_note.hide()
        self.preset_measurement_time_estimate.hide()
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
        self.preset_measurement_time_estimate.show()
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
        self.measurement_panel_separator = QFrame()
        self.measurement_panel_separator.setFrameShape(QFrame.Shape.HLine)
        self.measurement_panel_separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(self.measurement_panel_separator)
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
        self.advanced_tabs.addTab(self._build_measurement(), "Measurement")
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
        self.config_export_button = QPushButton("Export")
        self.config_export_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
        )
        self.config_export_button.setToolTip(
            "Save a TOML configuration file populated with the active GUI values."
        )
        self.config_export_button.clicked.connect(self.export_config)
        form.addRow(
            _label("Config", "Optional TOML file providing saved MatchPatch defaults."),
            _path_row(self.config_path, config_browse, self.config_export_button),
        )
        self.custom_adjustments_path = QLineEdit()
        custom_adjustments_browse = QPushButton("Browse")
        custom_adjustments_browse.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton)
        )
        custom_adjustments_browse.setToolTip(
            "Choose an optional CSV of per-preset snapshot loudness target bumps."
        )
        custom_adjustments_browse.clicked.connect(self.browse_custom_adjustments)
        form.addRow(
            _label(
                "Custom adjustments",
                "Optional CSV mapping preset IDs to per-snapshot target loudness bumps.",
            ),
            _path_row(self.custom_adjustments_path, custom_adjustments_browse),
        )
        self.reference_di = QLineEdit()
        self.reference_di.textChanged.connect(self._refresh_measurement_time_estimate)
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
        self.snapshot_count_input.valueChanged.connect(self._refresh_measurement_time_estimate)
        form.addRow(
            _label("Snapshots", "Number of snapshots to measure and normalize."),
            self.snapshot_count_input,
        )
        return content

    def _build_measurement(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        preset_row = QHBoxLayout()
        preset_row.addWidget(_label("Parameters", "Choose a measurement timing preset."))
        self.measurement_parameter_preset = QComboBox()
        self.measurement_parameter_preset.addItems(list(MEASUREMENT_TIMING_PRESETS))
        self.measurement_parameter_preset.currentTextChanged.connect(
            self._measurement_parameter_preset_changed
        )
        preset_row.addWidget(self.measurement_parameter_preset)
        self.apply_measurement_parameters_button = QPushButton("Apply")
        self.apply_measurement_parameters_button.clicked.connect(
            self.apply_measurement_parameter_preset
        )
        preset_row.addWidget(self.apply_measurement_parameters_button)
        preset_row.addStretch()
        layout.addLayout(preset_row)

        form = QFormLayout()
        layout.addLayout(form)

        self.analysis_window = QLineEdit("3.0")
        form.addRow(
            _label(
                "Analysis window (s)",
                "LUFS analysis window used during measurements; not optimized automatically.",
            ),
            self.analysis_window,
        )
        self.analysis_interval = QLineEdit("0.1")
        form.addRow(
            _label(
                "Analysis interval (s)",
                "Step size between LUFS analysis windows; not optimized automatically.",
            ),
            self.analysis_interval,
        )
        self.pre_roll = QLineEdit(str(MEASUREMENT_TIMING_PRESETS["Default"]["pre_roll"]))
        form.addRow(
            _label("Pre-roll (s)", "Silence recorded before the reference DI playback."),
            self.pre_roll,
        )
        self.post_roll = QLineEdit(str(MEASUREMENT_TIMING_PRESETS["Default"]["post_roll"]))
        form.addRow(
            _label("Post-roll (s)", "Silence recorded after the reference DI playback."),
            self.post_roll,
        )
        self.round_trip_latency = QLineEdit(
            str(MEASUREMENT_TIMING_PRESETS["Default"]["round_trip_latency"])
        )
        form.addRow(
            _label("Round-trip latency (s)", "Recorded signal offset caused by audio I/O latency."),
            self.round_trip_latency,
        )
        self.preset_wait = QLineEdit(str(MEASUREMENT_TIMING_PRESETS["Default"]["preset_wait"]))
        form.addRow(
            _label("Preset wait (s)", "Pause after switching presets before continuing."),
            self.preset_wait,
        )
        self.snapshot_wait = QLineEdit(str(MEASUREMENT_TIMING_PRESETS["Default"]["snapshot_wait"]))
        form.addRow(
            _label("Snapshot wait (s)", "Pause after switching snapshots before continuing."),
            self.snapshot_wait,
        )
        self.measurement_wait = QLineEdit(
            str(MEASUREMENT_TIMING_PRESETS["Default"]["measurement_wait"])
        )
        form.addRow(
            _label(
                "Measurement wait (s)", "Pause before capturing loudness after a snapshot change."
            ),
            self.measurement_wait,
        )
        self.measurement_time_estimate = QLabel()
        self.measurement_time_estimate.setWordWrap(True)
        self.measurement_time_estimate.setToolTip(
            "Estimated total measurement timing divided by loaded presets and snapshots."
        )
        layout.addWidget(self.measurement_time_estimate)
        for timing_input in (
            self.pre_roll,
            self.post_roll,
            self.round_trip_latency,
            self.preset_wait,
            self.snapshot_wait,
            self.measurement_wait,
        ):
            timing_input.textChanged.connect(self._refresh_measurement_time_estimate)
        self._refresh_measurement_time_estimate()
        self.determine_parameters_button = QPushButton("Determine optimal parameters")
        self.determine_parameters_button.clicked.connect(self.determine_optimal_parameters)
        layout.addWidget(self.determine_parameters_button)
        layout.addStretch()
        return content

    def _measurement_parameter_preset_changed(self, preset_name: str) -> None:
        if preset_name != "Fast":
            return
        QMessageBox.warning(
            self,
            "Fast measurement parameters",
            "Fast measurement parameters can lead to unstable measurements when effects "
            "with trails are used. Reverb and delay may make one snapshot's output bleed "
            "into the next snapshot's measurement.\n\nUse Default parameters or determine optimized parameters for your snapshots that are using trails if unsure.",
        )

    def apply_measurement_parameter_preset(self) -> None:
        preset_name = self.measurement_parameter_preset.currentText()
        values = MEASUREMENT_TIMING_PRESETS.get(preset_name)
        if values is None:
            return
        self._apply_measurement_timing_values(values)

    def _apply_measurement_timing_values(self, values: dict[str, object]) -> None:
        device = self.device.currentData()
        panel = self.device_panels.get(device)
        for name, value in values.items():
            text = str(value)
            getattr(self, name).setText(text)
            if panel is not None and hasattr(panel, name):
                getattr(panel, name).setText(text)

    def _refresh_measurement_time_estimate(self) -> None:
        if not hasattr(self, "measurement_time_estimate"):
            return

        try:
            estimate = _MeasurementProgressEstimate(
                preset_wait=self._timing_input_value(self.preset_wait),
                snapshot_wait=self._timing_input_value(self.snapshot_wait),
                measurement_wait=self._timing_input_value(self.measurement_wait),
                pre_roll=self._timing_input_value(self.pre_roll),
                post_roll=self._timing_input_value(self.post_roll),
                round_trip_latency=self._timing_input_value(self.round_trip_latency),
                reference_audio_seconds=_reference_audio_seconds(self.reference_di.text()),
            )
        except ValueError:
            self.measurement_time_estimate.setText(
                "Estimated measurement time per snapshot: invalid timing value"
            )
            self._refresh_preset_measurement_time_estimate(None)
            return

        preset_total = self._loaded_preset_count_for_estimate()
        measured_snapshot_total = self._loaded_snapshot_count_for_estimate()
        seconds = estimate.seconds_per_measured_snapshot(
            preset_total,
            measured_snapshot_total,
        )
        self.measurement_time_estimate.setText(
            "Estimated measurement time per snapshot: "
            f"{_format_short_seconds(seconds)} "
            f"({preset_total} preset{'s' if preset_total != 1 else ''}, "
            f"{measured_snapshot_total} snapshot"
            f"{'s' if measured_snapshot_total != 1 else ''})"
        )
        self._refresh_preset_measurement_time_estimate(estimate)

    def _refresh_preset_measurement_time_estimate(
        self, estimate: _MeasurementProgressEstimate | None = None
    ) -> None:
        if not hasattr(self, "preset_measurement_time_estimate"):
            return

        if estimate is None:
            try:
                estimate = _MeasurementProgressEstimate(
                    preset_wait=self._timing_input_value(self.preset_wait),
                    snapshot_wait=self._timing_input_value(self.snapshot_wait),
                    measurement_wait=self._timing_input_value(self.measurement_wait),
                    pre_roll=self._timing_input_value(self.pre_roll),
                    post_roll=self._timing_input_value(self.post_roll),
                    round_trip_latency=self._timing_input_value(self.round_trip_latency),
                    reference_audio_seconds=_reference_audio_seconds(self.reference_di.text()),
                )
            except ValueError:
                self.preset_measurement_time_estimate.setText(
                    "Estimated total measurement time for selected presets: invalid timing value"
                )
                return

        preset_total = self._selected_preset_count_for_estimate()
        measured_snapshot_total = self._selected_snapshot_count_for_estimate()
        seconds = estimate.total_seconds_for_counts(preset_total, measured_snapshot_total)
        self.preset_measurement_time_estimate.setText(
            "Estimated total measurement time for selected presets: "
            f"{_format_short_seconds(seconds)} "
            f"({preset_total} preset{'s' if preset_total != 1 else ''}, "
            f"{measured_snapshot_total} snapshot"
            f"{'s' if measured_snapshot_total != 1 else ''})"
        )

    @staticmethod
    def _timing_input_value(widget: QLineEdit) -> float:
        value = float(widget.text())
        if not math.isfinite(value):
            raise ValueError
        return max(0.0, value)

    def _loaded_preset_count_for_estimate(self) -> int:
        if not hasattr(self, "preset_table"):
            return 1
        return max(
            1,
            sum(
                1
                for row in range(self.preset_table.rowCount())
                if self._row_has_measured_snapshots(row)
            ),
        )

    def _selected_preset_count_for_estimate(self) -> int:
        if not hasattr(self, "preset_table") or self.preset_table.rowCount() == 0:
            return 1
        return max(1, len(self._selected_measurable_preset_rows()))

    def _loaded_snapshot_count_for_estimate(self) -> int:
        if not hasattr(self, "preset_table") or self.preset_table.rowCount() == 0:
            return self._snapshot_count_for_estimate()
        return max(
            1,
            sum(
                self._row_measured_snapshot_count(row)
                for row in range(self.preset_table.rowCount())
            ),
        )

    def _selected_snapshot_count_for_estimate(self) -> int:
        if not hasattr(self, "preset_table") or self.preset_table.rowCount() == 0:
            return self._snapshot_count_for_estimate()
        return max(
            1,
            sum(
                self._row_measured_snapshot_count(row)
                for row in self._selected_measurable_preset_rows()
            ),
        )

    def _snapshot_count_for_estimate(self) -> int:
        if hasattr(self, "snapshot_count_input"):
            return max(1, self.snapshot_count_input.value())
        return max(1, self.snapshot_count)

    def _row_measured_snapshot_indexes(self, row: int) -> tuple[int, ...]:
        indexes = []
        for snapshot_index in range(self._snapshot_count_for_estimate()):
            item = self.preset_table.item(row, self._snapshot_name_column(snapshot_index))
            if item is None or not item.data(IGNORED_SNAPSHOT_ROLE):
                indexes.append(snapshot_index + 1)
        return tuple(indexes)

    def _row_measured_snapshot_count(self, row: int) -> int:
        return len(self._row_measured_snapshot_indexes(row))

    def _row_has_measured_snapshots(self, row: int) -> bool:
        return self._row_measured_snapshot_count(row) > 0

    def _checked_preset_rows(self) -> list[int]:
        rows = []
        for row in range(self.preset_table.rowCount()):
            item = self.preset_table.item(row, 0)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                rows.append(row)
        return rows

    def _selected_measurable_preset_rows(self) -> list[int]:
        if not hasattr(self, "preset_table"):
            return []
        if Path(self.input_path.text()).suffix.lower() == ".hlx":
            candidate_rows = [0] if self.preset_table.rowCount() else []
        else:
            checked_rows = self._checked_preset_rows()
            candidate_rows = checked_rows or list(range(self.preset_table.rowCount()))
        return [row for row in candidate_rows if self._row_has_measured_snapshots(row)]

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
        self.solo_regex.setMaximumWidth(220)
        self.solo_regex.setToolTip(
            "Case-insensitive regular expression used to identify solo snapshots."
        )
        self.ignore_snapshot_regex = QLineEdit(NormalizationPolicy().ignore_snapshot_regex)
        self.ignore_snapshot_regex.setMaximumWidth(260)
        self.ignore_snapshot_regex.setToolTip(
            "Regular expression used to identify snapshots skipped during normalization."
        )
        self.ignore_snapshot_regex.textChanged.connect(self._refresh_all_snapshot_names)
        self.ignore_snapshot_regex.textChanged.connect(self._refresh_measurement_time_estimate)
        snapshot_regexes = QGroupBox("Snapshot name regex")
        snapshot_regex_layout = QFormLayout(snapshot_regexes)
        snapshot_regex_layout.setContentsMargins(8, 8, 8, 8)
        snapshot_regex_layout.setSpacing(6)
        snapshot_regex_layout.addRow(_label("Solo", self.solo_regex.toolTip()), self.solo_regex)
        snapshot_regex_layout.addRow(
            _label("Ignored", self.ignore_snapshot_regex.toolTip()),
            self.ignore_snapshot_regex,
        )
        form.addRow(snapshot_regexes)
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
        self._open_input_path(path)

    def _open_input_path(self, path: str) -> None:
        if not path or path == self.input_path.text():
            return
        if (
            self._preset_table_has_unsaved_changes()
            and not self._prompt_save_or_discard_preset_table_changes(
                "opening another preset or setlist file"
            )
        ):
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

    def _choose_measurement_save_path(self) -> Path | None:
        input_path = Path(self.input_path.text())
        suffix = input_path.suffix.lower()
        if suffix not in {".hls", ".hlx"}:
            self.show_error("Open a Helix .hls or .hlx file before saving a measurement file")
            return None
        file_filter = f"Helix {suffix} (*{suffix})"
        suggested_path = input_path.with_name(input_path.stem + "_measurement" + suffix)
        dialog = QFileDialog(self, "Save measurement file")
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog)
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        dialog.setNameFilter(file_filter)
        dialog.selectFile(str(suggested_path))
        dialog.setLabelText(QFileDialog.DialogLabel.Accept, "Save")
        path = dialog.selectedFiles()[0] if dialog.exec() and dialog.selectedFiles() else ""
        if not path:
            return None
        save_path = Path(path)
        if save_path.suffix.lower() != suffix:
            self.show_error(f"Measurement file must use the {suffix} extension")
            return None
        return save_path

    def browse_output(self) -> None:
        path = self._choose_save_as_path(accept_label="Save")
        if path is not None:
            self.output_path.setText(str(path))

    def save_measurement_file(self) -> bool:
        if not self._loaded_input_path:
            self.show_error("Open a Helix .hls or .hlx file before saving a measurement file")
            return False
        if not self._validate_single_preset_slot_for_run():
            return False

        output_path = self._choose_measurement_save_path()
        if output_path is None:
            return False

        try:
            args = apply_config(parse_args(self._build_argv()))
            request = request_from_args(args)
            profile = get_device_profile(request.device)
            handler = profile.create_patch_file_handler(Path(__file__).resolve().parents[3])
            handler.validate_output(request.input_path, output_path)
        except Exception as exc:  # noqa: BLE001
            self.show_error(str(exc))
            return False

        if not self._confirm_overwrite(output_path):
            return False

        try:
            handler.create_measurement_file(request.input_path, output_path)
        except Exception as exc:  # noqa: BLE001
            self.show_error(str(exc))
            return False

        self._log(f"Measurement file saved: {output_path.resolve()}", "success")
        return True

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

        self._reset_preset_table_modified()
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
                adjustment = (
                    0.0
                    if adjustment_text in {"-", "Ignore"}
                    else float(adjustment_text.split(" ", 1)[0])
                )
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
            name_column = self._snapshot_name_column(snapshot_index)
            adjustment_column = self._snapshot_adjustment_column(snapshot_index)
            name_item = self.preset_table.item(row, name_column)
            adjustment_item = self.preset_table.item(row, adjustment_column)
            if name_item is None:
                name_item = QTableWidgetItem()
                self.preset_table.setItem(row, name_column, name_item)
            if adjustment_item is None:
                adjustment_item = QTableWidgetItem()
                self.preset_table.setItem(row, adjustment_column, adjustment_item)
            self._set_snapshot_name(
                name_item,
                snapshot_names[snapshot_index],
                self._is_solo_snapshot_name(snapshot_names[snapshot_index]),
                self._is_ignored_snapshot_name(snapshot_names[snapshot_index]),
            )
            if self._is_ignored_snapshot_name(snapshot_names[snapshot_index]):
                self._set_ignored_snapshot_highlight(row, snapshot_index, True)
                continue
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
        for snapshot_index in range(self.snapshot_count):
            name = self.preset_table.item(row, self._snapshot_name_column(snapshot_index))
            adjustment = self.preset_table.item(
                row,
                self._snapshot_adjustment_column(snapshot_index),
            )
            adjustment_value = ""
            if adjustment is not None:
                if adjustment.data(IGNORED_SNAPSHOT_ROLE):
                    adjustment_value = adjustment.text()
                elif adjustment.data(BAD_LUFS_HIGHLIGHT_ROLE):
                    adjustment_value = adjustment.text()
                else:
                    stored_value = adjustment.data(ADJUSTMENT_VALUE_ROLE)
                    if isinstance(stored_value, (int, float)) and not isinstance(
                        stored_value, bool
                    ):
                        try:
                            displayed_value = _parse_adjustment_display_text(adjustment.text())
                        except ValueError:
                            displayed_value = None
                        if displayed_value == float(stored_value) and "(" not in adjustment.text():
                            adjustment_value = adjustment.text()
                        else:
                            adjustment_value = _format_adjustment(float(stored_value))
                    else:
                        adjustment_value = _format_adjustment(
                            _parse_adjustment_display_text(adjustment.text())
                        )
            values.extend(
                [
                    name.text() if name is not None else "",
                    adjustment_value,
                ]
            )
        return values

    def _is_solo_snapshot_name(self, name: str) -> bool:
        try:
            solo_pattern = re.compile(self.solo_regex.text())
        except re.error:
            return False
        return solo_pattern.search(name) is not None

    def _is_ignored_snapshot_name(self, name: str) -> bool:
        try:
            ignore_pattern = re.compile(self.ignore_snapshot_regex.text())
        except re.error:
            return False
        return ignore_pattern.search(name) is not None

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

    def export_config(self) -> None:
        selection = self._choose_config_export_path()
        if selection is None:
            return
        path, save_default = selection
        config = default_config() if save_default else self._active_gui_config()
        message = "Saved default configuriation" if save_default else "Saved current configuration"

        try:
            saved_path = export_config(path, config)
        except Exception as exc:  # noqa: BLE001
            self.show_error(f"Could not export config: {exc}")
            return

        self.config_path.setText(str(saved_path))
        QMessageBox.information(self, "Export config", f"{message}:\n{saved_path}")

    def _choose_config_export_path(self) -> tuple[str, bool] | None:
        dialog = QFileDialog(self, "Export config")
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog)
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        dialog.setNameFilter("TOML (*.toml)")
        dialog.selectFile(str(Path(self.config_path.text().strip() or "matchpatch.toml")))
        dialog.setLabelText(QFileDialog.DialogLabel.Accept, "Save")
        save_default = QCheckBox("Save default configuration", dialog)
        save_default.setChecked(False)
        layout = dialog.layout()
        if isinstance(layout, QGridLayout):
            layout.addWidget(save_default, layout.rowCount(), 0, 1, -1)
        elif layout is not None:
            layout.addWidget(save_default)
        path = dialog.selectedFiles()[0] if dialog.exec() and dialog.selectedFiles() else ""
        if not path:
            return None
        return path, save_default.isChecked()

    def _active_gui_config(self) -> Config:
        args = apply_config(parse_args(self._build_config_export_argv()))
        config = default_config()
        config["normalize"] = {
            "backend": args.backend,
            "windows_python": str(args.windows_python),
            "reference_di": str(args.reference_di),
            "custom_adjustments_file": (
                str(args.custom_adjustments_file) if args.custom_adjustments_file else None
            ),
            "target_lufs": args.target_lufs,
        }
        if args.timeout is not None:
            config["normalize"]["timeout_seconds"] = args.timeout
        config["analysis"] = {
            "window_seconds": args.analysis_options.window_seconds,
            "interval_seconds": args.analysis_options.interval_seconds,
            "minimum_valid_lufs": args.analysis_options.minimum_valid_lufs,
            "pre_roll_seconds": args.pre_roll,
            "post_roll_seconds": args.post_roll,
            "round_trip_latency_seconds": args.round_trip_latency,
        }
        config["measurement"] = {
            "stability_runs": self._optimization_stability_runs,
            "termination_tolerance_percent": self._optimization_termination_tolerance,
            "stability_tolerance_percent": self._optimization_stability_tolerance,
        }
        config["policy"] = {
            "measured_snapshots": args.policy.snapshot_count,
            "solo_regex": args.policy.solo_regex,
            "ignore_snapshot_regex": args.policy.ignore_snapshot_regex,
            "solo_gain_bump_db": args.policy.solo_gain_bump_db,
            "crest_factor_reference_db": args.policy.crest_factor_reference_db,
            "crest_factor_correction_ratio": args.policy.crest_factor_correction_ratio,
            "max_crest_factor_correction_db": args.policy.max_crest_factor_correction_db,
            "gain_deadband_db": args.policy.gain_deadband_db,
        }
        devices = config["devices"]
        assert isinstance(devices, dict)
        devices[args.device] = {
            "audio": {
                "device": args.audio_device,
                "sample_rate": args.sample_rate,
                "input_mapping": list(_parse_config_channel_mapping(args.input_mapping)),
                "output_mapping": list(_parse_config_channel_mapping(args.output_mapping)),
                "blocksize": args.blocksize,
            },
            "steering": {
                "output": args.steering_output,
                "channel": args.steering_channel,
                "preset_wait_seconds": args.preset_wait,
                "snapshot_wait_seconds": args.snapshot_wait,
                "measurement_wait_seconds": args.measurement_wait,
            },
        }
        return config

    def browse_custom_adjustments(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose custom adjustments CSV",
            filter="CSV (*.csv)",
        )
        if not path:
            return
        try:
            load_custom_adjustments_file(Path(path), self.snapshot_count_input.value())
        except Exception as exc:  # noqa: BLE001
            self.show_error(f"Could not parse custom adjustments CSV: {exc}")
            return
        self.custom_adjustments_path.setText(path)

    def device_changed(self) -> None:
        name = self.device.currentData()
        panel = self.device_panels.get(name)
        if panel is not None:
            self.device_stack.setCurrentWidget(panel)
        self.load_defaults()

    def backend_changed(self) -> None:
        self._refresh_backend_tooltip()
        if not self._loading_defaults:
            self._available_backend = None

    def _refresh_backend_tooltip(self) -> None:
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
            self._loading_defaults = True
            try:
                self.backend.setCurrentText(
                    config_value(config, "normalize", "backend", default="hardware")
                )
            finally:
                self._loading_defaults = False
            args = apply_config(parse_args(self._base_argv("placeholder.hls")))
        except Exception as exc:  # noqa: BLE001
            self.show_error(str(exc))
            return

        self._loading_defaults = True
        try:
            self.backend.setCurrentText(args.backend)
        finally:
            self._loading_defaults = False
        self.reference_di.setText(str(args.reference_di))
        self.custom_adjustments_path.setText(
            str(args.custom_adjustments_file) if args.custom_adjustments_file else ""
        )
        self.target_lufs.setText(str(args.target_lufs))
        self.solo_gain_bump_db.setText(str(args.policy.solo_gain_bump_db))
        self.solo_regex.setText(args.policy.solo_regex)
        self.ignore_snapshot_regex.setText(args.policy.ignore_snapshot_regex)
        self.analysis_window.setText(str(args.analysis_options.window_seconds))
        self.analysis_interval.setText(str(args.analysis_options.interval_seconds))
        self._optimization_stability_runs = int(
            config_value(config, "measurement", "stability_runs", default=3)
        )
        self._optimization_termination_tolerance = float(
            config_value(
                config,
                "measurement",
                "termination_tolerance_percent",
                default=10.0,
            )
        )
        self._optimization_stability_tolerance = float(
            config_value(
                config,
                "measurement",
                "stability_tolerance_percent",
                default=2.0,
            )
        )
        profile = get_device_profile(args.device)
        self.snapshot_count_input.setMaximum(getattr(profile, "max_snapshot_count", None) or 999)
        self.snapshot_count_input.setValue(args.policy.snapshot_count)
        panel = self.device_panels.get(args.device)
        if panel is not None:
            panel.populate(args)
        device_steering = ("devices", args.device, "steering")
        default_timing = MEASUREMENT_TIMING_PRESETS["Default"]
        self._apply_measurement_timing_values(
            {
                "pre_roll": config_value(
                    config,
                    "analysis",
                    "pre_roll_seconds",
                    default=default_timing["pre_roll"],
                ),
                "post_roll": config_value(
                    config,
                    "analysis",
                    "post_roll_seconds",
                    default=default_timing["post_roll"],
                ),
                "round_trip_latency": config_value(
                    config,
                    "analysis",
                    "round_trip_latency_seconds",
                    default=default_timing["round_trip_latency"],
                ),
                "preset_wait": config_value(
                    config,
                    *device_steering,
                    "preset_wait_seconds",
                    default=default_timing["preset_wait"],
                ),
                "snapshot_wait": config_value(
                    config,
                    *device_steering,
                    "snapshot_wait_seconds",
                    default=default_timing["snapshot_wait"],
                ),
                "measurement_wait": config_value(
                    config,
                    *device_steering,
                    "measurement_wait_seconds",
                    default=default_timing["measurement_wait"],
                ),
            }
        )
        self._refresh_backend_tooltip()

    def _backend_check_enabled(self) -> bool:
        return os.getenv("QT_QPA_PLATFORM", "").lower() != "offscreen"

    def _backend_check_required(self, request: NormalizationRequest) -> bool:
        return (
            self._backend_check_enabled()
            and request.backend == "hardware"
            and self._available_backend != request.backend
        )

    def load_assignments(self) -> None:
        path = Path(self.input_path.text())
        if (
            not self._preset_load_discard_confirmed
            and self._loaded_input_path
            and str(path) != self._loaded_input_path
            and self._preset_table_has_unsaved_changes()
            and not self._prompt_save_or_discard_preset_table_changes(
                "opening another preset or setlist file"
            )
        ):
            self.input_path.setText(self._loaded_input_path)
            return

        self._discard_completed_export()
        self.preset_snapshot_positions.clear()
        self._recording_paths.clear()
        self._clear_bad_lufs_highlights()
        self._clear_normalization_focus()
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
                    self._set_snapshot_output_levels(
                        row,
                        getattr(assignment, "snapshot_output_levels", ()),
                    )
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

    def _load_custom_adjustments(self, request: NormalizationRequest) -> CustomAdjustments:
        if request.custom_adjustments_path is None:
            return {}
        return load_custom_adjustments_file(
            request.custom_adjustments_path,
            request.policy.snapshot_count,
        )

    def _populate_single_preset_table(self, path: Path, assignment: object | None = None) -> None:
        preset_name = str(getattr(assignment, "name", "") or path.stem)
        snapshot_names = getattr(assignment, "snapshot_names", ())
        if not isinstance(snapshot_names, tuple):
            snapshot_names = tuple(snapshot_names)
        snapshot_output_levels = getattr(assignment, "snapshot_output_levels", ())
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
            self._set_snapshot_output_levels(0, snapshot_output_levels)
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

        if self.preset_table.rowCount() and not self._selected_measurable_preset_rows():
            QMessageBox.warning(
                self,
                "No measurable snapshots",
                "Every selected preset has all snapshots ignored. Adjust the ignore regex or select a preset with at least one measurable snapshot.",
            )
            return

        if (
            self._preset_table_has_unsaved_changes()
            and not self._prompt_save_before_normalization()
        ):
            return

        try:
            args = apply_config(parse_args(self._build_argv()))
            request = self._request_with_audio_capture_options(
                replace(request_from_args(args), defer_export=True)
            )
            self._custom_adjustments = self._load_custom_adjustments(request)
        except Exception as exc:  # noqa: BLE001
            self.show_error(str(exc))
            return

        if self._backend_check_required(request):
            self._start_hardware_check(request, action="normalization")
            return

        self._available_backend = request.backend
        self._start_normalization_request(request)

    def determine_optimal_parameters(self) -> None:
        if not self._validate_single_preset_slot_for_run():
            return

        try:
            args = apply_config(parse_args(self._build_argv()))
            request = self._request_with_audio_capture_options(
                replace(request_from_args(args), defer_export=True),
                record_device_output=False,
            )
            preset_id = self._optimization_preset_id(request)
        except Exception as exc:  # noqa: BLE001
            self.show_error(str(exc))
            return

        settings = self._show_measurement_optimization_setup(request, preset_id)
        if settings is None:
            return
        request = self._request_with_measurement_optimization_settings(request, settings)
        self._apply_measurement_optimization_settings(settings)

        if self._backend_check_required(request):
            self._start_hardware_check(
                request,
                action="optimization",
                optimization_preset_id=preset_id,
                optimization_settings=settings,
            )
            return

        self.determine_parameters_button.setEnabled(False)
        self._available_backend = request.backend
        self._start_measurement_optimization_request(request, preset_id, settings)

    def _start_measurement_optimization_request(
        self,
        request: NormalizationRequest,
        preset_id: int,
        settings: MeasurementOptimizationSettings,
    ) -> None:
        self.start_button.setEnabled(True)
        self.determine_parameters_button.setEnabled(False)
        self._last_measurement_optimization_settings = settings
        self.optimization_dialog = MeasurementOptimizationDialog(settings, self)
        self.optimization_dialog.set_play_recorded_output(
            self.play_recorded_output_button.isChecked()
        )
        self.optimization_dialog.play_recorded_output_changed.connect(
            self.play_recorded_output_button.setChecked
        )
        self.optimization_dialog.cancelled.connect(self._cancel_measurement_optimization)
        self.optimization_dialog.applied.connect(self._apply_measurement_optimization_result)
        self.optimization_dialog.show()
        self.optimization_worker = MeasurementOptimizationWorker(
            request,
            preset_id,
            settings.stability_runs,
            settings.termination_tolerance,
            settings.stability_tolerance,
            settings.pinned_parameters,
            self,
        )
        self.optimization_worker.progress.connect(self._update_measurement_optimization)
        self.optimization_worker.completed.connect(self._measurement_optimization_completed)
        self.optimization_worker.cancelled.connect(self._measurement_optimization_cancelled)
        self.optimization_worker.failed.connect(self._measurement_optimization_failed)
        self.optimization_worker.finished.connect(self._measurement_optimization_finished)
        self.optimization_worker.finished.connect(self.optimization_worker.deleteLater)
        self.optimization_worker.start()

    def _request_with_audio_capture_options(
        self,
        request: NormalizationRequest,
        *,
        record_device_output: bool | None = None,
    ) -> NormalizationRequest:
        return replace(
            request,
            play_recorded_output=self.play_recorded_output_button.isChecked(),
            record_device_output=(
                self.record_output_button.isChecked()
                if record_device_output is None
                else record_device_output
            ),
            playback_toggle_path=self._ensure_playback_toggle_path(),
        )

    def _ensure_playback_toggle_path(self) -> Path:
        if self._playback_toggle_path is None:
            temporary = tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                prefix="matchpatch_playback_",
                suffix=".txt",
                delete=False,
            )
            self._playback_toggle_path = Path(temporary.name)
            temporary.close()
        self._write_playback_toggle()
        return self._playback_toggle_path

    def _playback_toggle_changed(self, checked: bool) -> None:
        self.play_recorded_output_button.setIcon(
            self._speaker_icon if checked else self._speaker_off_icon
        )
        self._write_playback_toggle(checked)

    def _record_output_toggle_changed(self, checked: bool) -> None:
        self.record_output_button.setIcon(self._record_icon if checked else self._record_off_icon)

    def _write_playback_toggle(self, checked: bool | None = None) -> None:
        if self._playback_toggle_path is None:
            return
        enabled = self.play_recorded_output_button.isChecked() if checked is None else checked
        try:
            self._playback_toggle_path.write_text("1" if enabled else "0", encoding="utf-8")
        except OSError as exc:
            self._log(f"Could not update playback toggle: {exc}", "warning")

    def _show_measurement_optimization_setup(
        self,
        request: NormalizationRequest,
        preset_id: int,
        initial_settings: MeasurementOptimizationSettings | None = None,
    ) -> MeasurementOptimizationSettings | None:
        preset_label = get_device_profile(request.device).format_patch_id(preset_id)
        settings = (
            initial_settings
            or self._last_measurement_optimization_settings
            or MeasurementOptimizationSettings(
                pre_roll=float(request.pre_roll if request.pre_roll is not None else 0.2),
                post_roll=float(request.post_roll if request.post_roll is not None else 0.1),
                round_trip_latency=float(
                    request.round_trip_latency if request.round_trip_latency is not None else 0.02
                ),
                preset_wait=float(request.preset_wait if request.preset_wait is not None else 0.5),
                snapshot_wait=float(
                    request.snapshot_wait if request.snapshot_wait is not None else 0.2
                ),
                measurement_wait=float(
                    request.measurement_wait if request.measurement_wait is not None else 0.1
                ),
                stability_runs=self._optimization_stability_runs,
                termination_tolerance=self._optimization_termination_tolerance,
                stability_tolerance=self._optimization_stability_tolerance,
            )
        )
        dialog = MeasurementOptimizationSetupDialog(
            settings,
            preset_label,
            preset_id,
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            cancelled_settings = dialog.settings()
            if cancelled_settings != settings:
                self._last_measurement_optimization_settings = cancelled_settings
            return None
        return dialog.settings()

    def _request_with_measurement_optimization_settings(
        self,
        request: NormalizationRequest,
        settings: MeasurementOptimizationSettings,
    ) -> NormalizationRequest:
        return replace(
            request,
            pre_roll=settings.pre_roll,
            post_roll=settings.post_roll,
            round_trip_latency=settings.round_trip_latency,
            preset_wait=settings.preset_wait,
            snapshot_wait=settings.snapshot_wait,
            measurement_wait=settings.measurement_wait,
        )

    def _apply_measurement_optimization_settings(
        self, settings: MeasurementOptimizationSettings
    ) -> None:
        self.pre_roll.setText(f"{settings.pre_roll:g}")
        self.post_roll.setText(f"{settings.post_roll:g}")
        self.round_trip_latency.setText(f"{settings.round_trip_latency:g}")
        self.preset_wait.setText(f"{settings.preset_wait:g}")
        self.snapshot_wait.setText(f"{settings.snapshot_wait:g}")
        self.measurement_wait.setText(f"{settings.measurement_wait:g}")
        self._optimization_stability_runs = settings.stability_runs
        self._optimization_termination_tolerance = settings.termination_tolerance
        self._optimization_stability_tolerance = settings.stability_tolerance

    def _optimization_preset_id(self, request: NormalizationRequest) -> int:
        preset_set = request.preset_set or self._selected_preset_set()
        if not preset_set:
            raise ValueError("Select at least one preset before determining optimal parameters")

        profile = get_device_profile(request.device)
        handler = profile.create_patch_file_handler(Path(__file__).resolve().parents[3])
        return handler.parse_patch_set(preset_set)[0]

    def _update_measurement_optimization(self, event: OptimizationProgress) -> None:
        if self.optimization_dialog is not None:
            self.optimization_dialog.update_progress(event)

    def _measurement_optimization_completed(self, toml_text: str) -> None:
        if self.optimization_dialog is not None:
            self.optimization_dialog.set_result(toml_text)

    def _apply_measurement_optimization_result(self, toml_text: str) -> None:
        try:
            config = tomllib.loads(toml_text)
        except tomllib.TOMLDecodeError as exc:
            self.show_error(f"Could not apply optimized parameters: {exc}")
            return

        device = self.device.currentData()
        applied = False
        for parameter in TIMING_PARAMETERS:
            table_path = tuple(device if part == "{device}" else part for part in parameter.table)
            value = _nested_config_value(config, (*table_path, parameter.key))
            if value is None:
                continue
            getattr(self, parameter.name).setText(str(value))
            panel = self.device_panels.get(device)
            if panel is not None and hasattr(panel, parameter.name):
                getattr(panel, parameter.name).setText(str(value))
            applied = True

        if not applied:
            self.show_error("Optimized parameters did not contain measurement timing values")
            return
        QMessageBox.information(
            self,
            "Apply optimized parameters",
            "Applied optimized timing parameters to Advanced > Measurement.",
        )

    def _measurement_optimization_cancelled(self) -> None:
        if self.optimization_dialog is not None:
            self.optimization_dialog.set_status("Parameter study cancelled.")
            self.optimization_dialog.set_finished()

    def _measurement_optimization_failed(self, detail: str) -> None:
        if self.optimization_dialog is not None:
            self.optimization_dialog.set_status(f"Parameter study failed: {detail}")
            self.optimization_dialog.set_finished()
        else:
            self.show_error(detail)

    def _measurement_optimization_finished(self) -> None:
        self.optimization_worker = None
        self.determine_parameters_button.setEnabled(True)

    def _cancel_measurement_optimization(self) -> None:
        if self.optimization_worker is not None:
            self.optimization_worker.cancel()

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
        self._deferred_gain_correction_logs.clear()
        self._deferred_gain_correction_patch = None
        self._clear_bad_lufs_highlights()
        self._clear_normalization_focus()
        self._adjusted_presets.clear()
        with self._sorting_paused():
            for row in range(self.preset_table.rowCount()):
                self._clear_preset_adjustments(row)
                self._mark_selected_preset_adjustments_pending(row)
        self.retained_csv.clear()
        self.retained_csv_pane.hide()
        self._reset_loudness_bars()
        self._set_phase("starting")
        self._log("Normalization started", "info")
        self._log(f"Backend: {getattr(request, 'backend', 'unknown')}", "info")
        if self._custom_adjustments:
            self._log(
                f"Custom adjustments loaded: {request.custom_adjustments_path}",
                "info",
            )
        self._start_busy_phase()
        self.completed_request = request
        self._measurement_progress_estimate = _MeasurementProgressEstimate.from_request(request)
        self._measurement_progress_plan = self._measurement_progress_plan_for_request(request)
        self.worker = NormalizationWorker(request, self)
        self.worker.progress.connect(self.update_progress)
        self.worker.import_requested.connect(self.confirm_import)
        self.worker.completed.connect(self.normalization_completed)
        self.worker.cancelled.connect(self.normalization_cancelled)
        self.worker.failed.connect(self.show_error)
        self.worker.finished.connect(self.worker_finished)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def _measurement_progress_plan_for_request(
        self,
        request: NormalizationRequest,
    ) -> _MeasurementProgressPlan | None:
        if not hasattr(self, "preset_table") or self.preset_table.rowCount() == 0:
            return None

        requested_patches = None
        if request.preset_set:
            requested_patches = {patch.strip().upper() for patch in request.preset_set.split(",")}

        preset_snapshots = []
        for row in range(self.preset_table.rowCount()):
            patch_item = self.preset_table.item(row, 1)
            if patch_item is None:
                continue
            patch = patch_item.text().strip().upper()
            if not patch:
                continue
            if requested_patches is not None and patch not in requested_patches:
                continue
            snapshots = self._row_measured_snapshot_indexes(row)
            if snapshots:
                preset_snapshots.append((patch, snapshots))

        if not preset_snapshots:
            return None
        return _MeasurementProgressPlan(tuple(preset_snapshots))

    def _start_hardware_check(
        self,
        request: NormalizationRequest,
        *,
        action: str,
        optimization_preset_id: int | None = None,
        optimization_settings: MeasurementOptimizationSettings | None = None,
    ) -> None:
        if self.hardware_check_worker is not None or self.worker is not None:
            return

        self.start_button.setEnabled(False)
        self.determine_parameters_button.setEnabled(False)
        self._show_hardware_check_overlay()
        self._set_phase("starting")
        self._log("Checking backend availability", "info")
        self.hardware_check_worker = HardwareCheckWorker(request, self)
        self._pending_backend_check_request = request
        self._pending_backend_check_action = action
        self._pending_optimization_preset_id = optimization_preset_id
        self._pending_optimization_settings = optimization_settings
        self.hardware_check_worker.completed.connect(self._hardware_check_completed)
        self.hardware_check_worker.failed.connect(self._hardware_check_failed)
        self.hardware_check_worker.finished.connect(self._hardware_check_finished)
        self.hardware_check_worker.finished.connect(self.hardware_check_worker.deleteLater)
        self.hardware_check_worker.start()

    def _hardware_check_completed(self) -> None:
        self._hide_hardware_check_overlay()
        request = self._pending_backend_check_request
        action = self._pending_backend_check_action
        optimization_preset_id = self._pending_optimization_preset_id
        optimization_settings = self._pending_optimization_settings
        self._pending_backend_check_request = None
        self._pending_backend_check_action = "normalization"
        self._pending_optimization_preset_id = None
        self._pending_optimization_settings = None
        if request is not None:
            self._available_backend = request.backend
        self._log("Backend availability check completed", "success")
        if request is not None and action == "optimization":
            if optimization_settings is None:
                setup_preset_id = (
                    optimization_preset_id
                    if optimization_preset_id is not None
                    else self._optimization_preset_id(request)
                )
                optimization_settings = self._show_measurement_optimization_setup(
                    request, setup_preset_id
                )
                if optimization_settings is None:
                    self.start_button.setEnabled(True)
                    self.determine_parameters_button.setEnabled(True)
                    self._set_phase("ready")
                    return
                request = self._request_with_measurement_optimization_settings(
                    request, optimization_settings
                )
                self._apply_measurement_optimization_settings(optimization_settings)
            self._start_measurement_optimization_request(
                request,
                optimization_preset_id
                if optimization_preset_id is not None
                else self._optimization_preset_id(request),
                optimization_settings,
            )
            return
        if request is not None:
            self._start_normalization_request(request)
            return
        self.start_button.setEnabled(True)
        self.determine_parameters_button.setEnabled(True)
        self._set_phase("ready")

    def _hardware_check_failed(self, detail: str) -> None:
        self._hide_hardware_check_overlay()
        request = self._pending_backend_check_request
        action = self._pending_backend_check_action
        optimization_preset_id = self._pending_optimization_preset_id
        optimization_settings = self._pending_optimization_settings
        self._pending_backend_check_request = None
        self._pending_backend_check_action = "normalization"
        self._pending_optimization_preset_id = None
        self._pending_optimization_settings = None
        self.start_button.setEnabled(True)
        self.determine_parameters_button.setEnabled(True)
        self._set_phase("ready")
        message = "No suitable device connected."
        detail = detail.strip()
        self._log(f"{message} {detail}".strip(), "error")
        QMessageBox.critical(
            self,
            "Error",
            f"{message}\n\nConnect a compatible audio processor and try again.",
        )
        if (
            request is not None
            and action == "optimization"
            and optimization_preset_id is not None
            and optimization_settings is not None
        ):
            QTimer.singleShot(
                0,
                lambda: self._restore_measurement_optimization_setup(
                    request,
                    optimization_preset_id,
                    optimization_settings,
                ),
            )

    def _hardware_check_finished(self) -> None:
        self.hardware_check_worker = None

    def _restore_measurement_optimization_setup(
        self,
        request: NormalizationRequest,
        preset_id: int,
        settings: MeasurementOptimizationSettings,
    ) -> None:
        if self.hardware_check_worker is not None:
            QTimer.singleShot(
                0,
                lambda: self._restore_measurement_optimization_setup(
                    request,
                    preset_id,
                    settings,
                ),
            )
            return

        restored_settings = self._show_measurement_optimization_setup(
            request,
            preset_id,
            settings,
        )
        if restored_settings is None:
            return

        retry_request = self._request_with_measurement_optimization_settings(
            request,
            restored_settings,
        )
        self._apply_measurement_optimization_settings(restored_settings)
        if self._backend_check_required(retry_request):
            self._start_hardware_check(
                retry_request,
                action="optimization",
                optimization_preset_id=preset_id,
                optimization_settings=restored_settings,
            )
            return

        self._available_backend = retry_request.backend
        self._start_measurement_optimization_request(
            retry_request,
            preset_id,
            restored_settings,
        )

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
            if event.phase == "completed":
                self._apply_deferred_gain_correction_logs()
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
            plan = self._measurement_progress_plan
            if plan is not None:
                total = max(1, plan.measured_snapshot_total)
                value = min(total, plan.progress_value(event))
            else:
                total = event.preset_total * event.snapshot_total
                snapshot = event.snapshot or 1
                value = (event.preset_index - 1) * event.snapshot_total + snapshot
            self.preset_progress.setRange(0, total)
            self.preset_progress.setValue(value)
            self._update_measurement_progress_format(event)
        elif event.kind == "measurement_completed":
            self._hide_progress()

        self._update_normalization_focus(event)

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
            self._handle_gain_correction_log(message)
        elif event.kind == "snapshot_completed":
            with self.preset_table.updates_paused():
                self._apply_snapshot_measurement(event)
        elif event.kind == "snapshot_failed":
            with self.preset_table.updates_paused():
                self._apply_snapshot_measurement_failure(event)
        elif event.kind == "preset_completed":
            self._apply_deferred_gain_correction_logs(event.device_patch)
        if event.lufs is not None and event.crest_factor_db is not None:
            message += f": {event.lufs:.3f} LUFS, {event.crest_factor_db:.3f} dB crest"
        if event.kind == "temp_retained" and event.path:
            self.retained_csv.setText(event.path)
            self.retained_csv_pane.show()
        if event.kind == "snapshot_recorded" and event.path:
            self._set_recorded_output(event)

        if (
            "bad LUFS" in message
            or "measurement unavailable" in message
            or message.startswith("[WARNING]")
        ):
            level = "warning"
        else:
            level = "error" if event.kind in {"error_log", "preset_failed"} else "debug"
        self._log(message, level)

    def _update_normalization_focus(self, event: ProgressEvent) -> None:
        if event.kind in {"measurement_completed", "preset_failed"} or (
            event.kind == "phase"
            and event.phase
            in {
                "completed",
                "error",
                "waiting_for_measurement_import",
                "waiting_for_adjusted_import",
                "normalization_cancelled_by_user",
            }
        ):
            self._clear_normalization_focus()
            return

        if event.kind == "preset_completed":
            self._set_normalization_focus(event.device_patch, None)
            return

        if event.kind == "preset_started":
            self._set_normalization_focus(event.device_patch, None)
            return

        if event.kind in {"snapshot_completed", "snapshot_failed"}:
            self._clear_normalization_snapshot_focus(event.device_patch)
            return

        if event.kind == "snapshot_started":
            self._set_normalization_focus(event.device_patch, event.snapshot)

    def _set_normalization_focus(self, device_patch: str | None, snapshot: int | None) -> None:
        if device_patch is None:
            return
        row = self._preset_row(device_patch)
        if row is None:
            return
        snapshot_index = None if snapshot is None else snapshot - 1
        if snapshot_index is not None and not 0 <= snapshot_index < self.snapshot_count:
            snapshot_index = None
        if snapshot_index is not None:
            item = self.preset_table.item(row, self._snapshot_name_column(snapshot_index))
            if item is not None and item.data(IGNORED_SNAPSHOT_ROLE):
                snapshot_index = None
        self.preset_table.set_normalization_focus(row, snapshot_index)

    def _clear_normalization_focus(self) -> None:
        if hasattr(self, "preset_table"):
            self.preset_table.clear_normalization_focus()

    def _clear_normalization_snapshot_focus(self, device_patch: str | None) -> None:
        if device_patch is None:
            return
        row = self._preset_row(device_patch)
        if row is None:
            return
        self.preset_table.clear_normalization_snapshot_focus(row)

    def _set_recorded_output(self, event: ProgressEvent) -> None:
        if not event.device_patch or event.snapshot is None or event.path is None:
            return
        row = self._preset_row(event.device_patch)
        if row is None:
            return
        column = self._snapshot_adjustment_column(event.snapshot - 1)
        item = self.preset_table.item(row, column)
        if item is None:
            return
        if item.data(IGNORED_SNAPSHOT_ROLE):
            self._set_adjustment_ignored(item)
            return
        path = Path(event.path)
        item.setData(RECORDED_OUTPUT_PATH_ROLE, str(path))
        self._recording_paths[(event.device_patch, event.snapshot - 1)] = path
        self._refresh_adjustment_cell_widget(item)

    def _refresh_adjustment_cell_widget(self, item: QTableWidgetItem) -> None:
        table = item.tableWidget()
        if table is None:
            return
        table.removeCellWidget(item.row(), item.column())
        recorded_path = item.data(RECORDED_OUTPUT_PATH_ROLE)
        has_custom_adjustment = item.toolTip().startswith("Custom loudness adjustment:")
        if not recorded_path:
            if has_custom_adjustment:
                label = QLabel(_custom_adjustment_label_text(item.text()))
                self._style_adjustment_cell_widget(label, item)
                self._style_adjustment_label(label, item)
                label.setContentsMargins(3, 0, 0, 0)
                label.setToolTip(item.toolTip())
                label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                table.setCellWidget(item.row(), item.column(), label)
            return

        content = QWidget(table)
        self._style_adjustment_cell_widget(content, item)
        layout = QHBoxLayout(content)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(2)
        label = QLabel(
            _custom_adjustment_label_text(item.text()) if has_custom_adjustment else item.text()
        )
        self._style_adjustment_label(label, item)
        label.setToolTip(item.toolTip())
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(label, 1)
        if recorded_path:
            button = QToolButton(content)
            button.setIcon(self._speaker_icon)
            button.setAutoRaise(True)
            button.setIconSize(QSize(14, 14))
            button.setFixedSize(22, 22)
            button.setToolTip("Play recorded snapshot output.")
            button.setEnabled(not self._normalization_in_progress())
            button.clicked.connect(
                lambda checked=False, path=Path(recorded_path): self._play_recording(path)
            )
            layout.addWidget(button)
        table.setCellWidget(item.row(), item.column(), content)

    @staticmethod
    def _style_adjustment_cell_widget(widget: QWidget, item: QTableWidgetItem) -> None:
        MainWindow._style_table_cell_widget(widget, item)

    @staticmethod
    def _style_table_cell_widget(widget: QWidget, item: QTableWidgetItem) -> None:
        table = item.tableWidget()
        palette = widget.palette()
        background = item.background()
        if background.style() != Qt.BrushStyle.NoBrush:
            color = background.color()
        elif table is not None:
            color = table.palette().color(QPalette.ColorRole.Base)
        else:
            color = QApplication.palette().color(QPalette.ColorRole.Base)
        palette.setColor(QPalette.ColorRole.Window, color)
        palette.setColor(QPalette.ColorRole.Base, color)
        widget.setPalette(palette)
        widget.setAutoFillBackground(True)
        widget.update()

    @staticmethod
    def _style_adjustment_label(label: QLabel, item: QTableWidgetItem) -> None:
        label.setFont(item.font())
        foreground = item.foreground()
        color = foreground.color()
        if foreground.style() != Qt.BrushStyle.NoBrush and color.isValid():
            label.setStyleSheet(f"color: {color.name()};")
        else:
            label.setStyleSheet("")

    def _play_recording(self, path: Path) -> None:
        if self._normalization_in_progress():
            return
        if self.playback_worker is not None and self.playback_worker.isRunning():
            return
        windows_python = self.completed_request.windows_python if self.completed_request else None
        self.playback_worker = AudioPlaybackWorker(path, self, windows_python=windows_python)
        self.playback_worker.failed.connect(self.show_error)
        self.playback_worker.finished.connect(self._playback_finished)
        self.playback_worker.finished.connect(self.playback_worker.deleteLater)
        self.playback_worker.start()

    def _playback_finished(self) -> None:
        self.playback_worker = None

    def _normalization_in_progress(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def _refresh_recorded_output_buttons(self) -> None:
        for row in range(self.preset_table.rowCount()):
            for snapshot_index in range(self.snapshot_count):
                item = self.preset_table.item(row, self._snapshot_adjustment_column(snapshot_index))
                if item is not None and item.data(RECORDED_OUTPUT_PATH_ROLE):
                    self._refresh_adjustment_cell_widget(item)

    def _show_indeterminate_progress(self, message: str) -> None:
        progress_was_hidden = self.progress_group.isHidden()
        self.current.setText(message)
        self.preset_progress.setRange(0, 0)
        self.preset_progress.resetFormat()
        self.progress_group.show()
        if progress_was_hidden:
            self._schedule_resize_for_content()

    def _hide_progress(self) -> None:
        if self.progress_group.isHidden():
            return
        self.preset_progress.resetFormat()
        self.progress_group.hide()
        self._schedule_resize_for_content()

    def _update_measurement_progress_format(self, event: ProgressEvent) -> None:
        estimate = self._measurement_progress_estimate
        if estimate is None or event.preset_total is None or event.snapshot_total is None:
            self.preset_progress.resetFormat()
            return

        plan = self._measurement_progress_plan
        if plan is not None:
            total_seconds = estimate.total_seconds_for_counts(
                plan.preset_total,
                plan.measured_snapshot_total,
            )
            remaining_seconds = estimate.remaining_seconds_for_plan(event, plan)
        else:
            total_seconds = estimate.total_seconds(event.preset_total, event.snapshot_total)
            remaining_seconds = estimate.remaining_seconds(
                event,
                event.preset_total,
                event.snapshot_total,
            )
        self.preset_progress.setFormat(
            "%p% | total "
            f"{_format_duration(total_seconds)} | ETA {_format_duration(remaining_seconds)}"
        )

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
        self._show_normalization_completion_popup()

    def _show_normalization_completion_popup(self) -> None:
        save_message = (
            'You need to save the setlist or preset with "Save" or "Save As", then import '
            "the saved file on your device."
        )
        manual_targets = self._manual_adjustment_targets()
        if manual_targets:
            target_lines = "\n".join(f"- {target}" for target in manual_targets)
            QMessageBox.warning(
                self,
                "Normalization completed with errors",
                "Normalization completed with errors.\n\n"
                "For the highlighted presets/snapshots, manual modifications are required "
                "to adjust the gain staging so there is enough headroom to raise the output "
                "level if necessary.\n\n"
                f"{target_lines}\n\n"
                f"{save_message}",
            )
            return

        QMessageBox.information(
            self,
            "Normalization completed",
            f"Normalization completed successfully.\n\n{save_message}",
        )

    def _manual_adjustment_targets(self) -> list[str]:
        targets: list[str] = []
        for row in range(self.preset_table.rowCount()):
            patch_item = self.preset_table.item(row, 1)
            preset_item = self.preset_table.item(row, 2)
            patch = patch_item.text().strip() if patch_item is not None else ""
            preset = preset_item.text().strip() if preset_item is not None else ""
            prefix = " ".join(part for part in (patch, preset) if part)
            for snapshot_index in range(self.snapshot_count):
                adjustment_item = self.preset_table.item(
                    row,
                    self._snapshot_adjustment_column(snapshot_index),
                )
                if adjustment_item is None or not adjustment_item.data(BAD_LUFS_HIGHLIGHT_ROLE):
                    continue
                name_item = self.preset_table.item(
                    row,
                    self._snapshot_name_column(snapshot_index),
                )
                snapshot_name = name_item.text().strip() if name_item is not None else ""
                snapshot_label = f"snapshot {snapshot_index + 1}"
                if snapshot_name:
                    snapshot_label = f"{snapshot_label} ({snapshot_name})"
                targets.append(f"{prefix}: {snapshot_label}" if prefix else snapshot_label)
        return targets

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
        preserved_preset_selection = self._preset_selection_state()
        if not self.input_path.text().strip():
            self.show_error("Open a Helix .hls or .hlx file before saving")
            return False
        if not self._preset_table_has_unsaved_changes():
            if make_active and output_path != Path(self.input_path.text()):
                preserved_single_preset_slot = (
                    self._single_preset_slot_text()
                    if Path(self.input_path.text()).suffix.lower() == ".hlx"
                    else None
                )
                try:
                    self._copy_active_file_to(output_path)
                except SaveCancelled:
                    return False
                except Exception as exc:  # noqa: BLE001
                    self.show_error(str(exc))
                    return False
                self._activate_saved_file(
                    output_path,
                    preserved_single_preset_slot=preserved_single_preset_slot,
                    preserved_preset_selection=preserved_preset_selection,
                )
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
            preserved_single_preset_slot = (
                self._single_preset_slot_text()
                if request.input_path.suffix.lower() == ".hlx"
                else None
            )
            self._activate_saved_file(
                output_path,
                preserved_single_preset_slot=preserved_single_preset_slot,
                preserved_preset_selection=preserved_preset_selection,
            )
        else:
            self._reset_preset_table_modified()
            self._refresh_file_actions()
        return True

    def _copy_active_file_to(self, output_path: Path) -> None:
        input_path = Path(self.input_path.text())
        if not self._confirm_overwrite(output_path):
            raise SaveCancelled
        shutil.copy2(input_path, output_path)

    def _activate_saved_file(
        self,
        path: Path,
        *,
        preserved_single_preset_slot: str | None = None,
        preserved_preset_selection: _PresetSelectionState | None = None,
    ) -> None:
        self.input_path.setText(str(path))
        self._preset_load_discard_confirmed = True
        try:
            self.load_assignments()
        finally:
            self._preset_load_discard_confirmed = False
        if preserved_preset_selection is not None and path.suffix.lower() != ".hlx":
            self._restore_preset_selection_state(preserved_preset_selection)
        if preserved_single_preset_slot is None or path.suffix.lower() != ".hlx":
            return
        item = self.preset_table.item(0, 1)
        if item is None:
            return
        signals_blocked = self.preset_table.blockSignals(True)
        try:
            item.setText(preserved_single_preset_slot)
        finally:
            self.preset_table.blockSignals(signals_blocked)
        self._reset_preset_table_modified()

    def _set_active_file(self, path: Path) -> None:
        filename = path.name if str(path) else ""
        self.setWindowTitle(filename or "MatchPatch")

    def _refresh_file_actions(self) -> None:
        has_file = bool(self.input_path.text().strip())
        if hasattr(self, "save_action"):
            self.save_action.setEnabled(has_file and self._preset_table_has_unsaved_changes())
        if hasattr(self, "save_as_action"):
            self.save_as_action.setEnabled(has_file)
        if hasattr(self, "save_measurement_action"):
            self.save_measurement_action.setEnabled(bool(self._loaded_input_path))
        if hasattr(self, "start_button"):
            self.start_button.setEnabled(bool(self._loaded_input_path) and self.worker is None)
        if hasattr(self, "record_output_button"):
            self.record_output_button.setEnabled(bool(self._loaded_input_path))
        if hasattr(self, "play_recorded_output_button"):
            self.play_recorded_output_button.setEnabled(True)

    def _prompt_save_before_normalization(self) -> bool:
        result = self._prompt_save_or_discard_preset_table_changes("starting normalization")
        if result == "discard":
            self._discard_preset_table_changes()
            return True
        return bool(result)

    def _prompt_save_or_discard_preset_table_changes(self, action: str) -> bool | str:
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Save changes")
        dialog.setText(f"The preset table contains changes. Save them before {action}?")
        save_button = dialog.addButton(QMessageBox.StandardButton.Save)
        save_as_button = dialog.addButton("Save As", QMessageBox.ButtonRole.AcceptRole)
        discard_button = dialog.addButton(QMessageBox.StandardButton.Discard)
        dialog.addButton(QMessageBox.StandardButton.Cancel)
        dialog.setDefaultButton(save_button)
        dialog.exec()
        clicked = dialog.clickedButton()
        if clicked is save_button:
            return self.save_active_file()
        if clicked is save_as_button:
            return self.save_active_file_as()
        if clicked is discard_button:
            return "discard"
        return False

    def _discard_preset_table_changes(self) -> None:
        preserved_preset_selection = self._preset_selection_state()
        self._preset_load_discard_confirmed = True
        try:
            self.load_assignments()
        finally:
            self._preset_load_discard_confirmed = False
        if Path(self.input_path.text()).suffix.lower() != ".hlx":
            self._restore_preset_selection_state(preserved_preset_selection)

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
        self._measurement_progress_estimate = None
        self._measurement_progress_plan = None
        self._clear_normalization_focus()
        self._apply_deferred_gain_correction_logs()
        self._refresh_recorded_output_buttons()
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
        if (
            self._preset_table_has_unsaved_changes()
            and not self._confirm_discard_preset_table_changes()
        ):
            event.ignore()
            return
        if self.worker is not None:
            if not self._confirm_cancellation():
                event.ignore()
                return
            self.worker.cancel()
        if self.optimization_worker is not None:
            self.optimization_worker.cancel()
        if self.worker is not None:
            self.worker.wait()
        if self.optimization_worker is not None:
            self.optimization_worker.wait()
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
        if hasattr(self, "custom_adjustments_path") and self.custom_adjustments_path.text().strip():
            argv.extend(["--custom-adjustments-file", self.custom_adjustments_path.text().strip()])
        return argv

    def _build_argv(self) -> list[str]:
        argv = self._base_argv(self.input_path.text().strip())
        self._append_gui_config_arguments(argv)
        preset_set = self._selected_preset_set()
        if preset_set:
            argv.extend(["--preset-set", preset_set])
        return argv

    def _build_config_export_argv(self) -> list[str]:
        argv = self._base_argv(self.input_path.text().strip() or "placeholder.hls")
        self._append_gui_config_arguments(argv)
        return argv

    def _append_gui_config_arguments(self, argv: list[str]) -> None:
        argv.extend(["--reference-di", self.reference_di.text()])
        argv.extend(["--target-lufs", self.target_lufs.text()])
        argv.extend(["--solo-gain-bump-db", self.solo_gain_bump_db.text()])
        argv.extend(["--solo-regex", self.solo_regex.text()])
        argv.extend(["--ignore-snapshot-regex", self.ignore_snapshot_regex.text()])
        argv.extend(["--snapshot-count", str(self.snapshot_count_input.value())])
        if self.keep_temp.isChecked():
            argv.append("--keep-temp")

        panel = self.device_panels.get(self.device.currentData())
        if panel is not None:
            panel.append_arguments(argv)
        _append_optional_argument(argv, "--analysis-window", self.analysis_window.text())
        _append_optional_argument(argv, "--analysis-interval", self.analysis_interval.text())
        _append_optional_argument(argv, "--pre-roll", self.pre_roll.text())
        _append_optional_argument(argv, "--post-roll", self.post_roll.text())
        _append_optional_argument(argv, "--round-trip-latency", self.round_trip_latency.text())
        _append_optional_argument(argv, "--preset-wait", self.preset_wait.text())
        _append_optional_argument(argv, "--snapshot-wait", self.snapshot_wait.text())
        _append_optional_argument(argv, "--measurement-wait", self.measurement_wait.text())

    def _selected_preset_set(self) -> str:
        selected = []
        for row in self._selected_measurable_preset_rows():
            patch_item = self.preset_table.item(row, 1)
            if patch_item is not None and patch_item.text().strip():
                selected.append(patch_item.text())
        return ",".join(selected)

    def _preset_selection_state(self) -> _PresetSelectionState:
        checked_patches: set[str] = set()
        for row in range(self.preset_table.rowCount()):
            selected_item = self.preset_table.item(row, 0)
            patch_item = self.preset_table.item(row, 1)
            if (
                selected_item is not None
                and patch_item is not None
                and selected_item.checkState() == Qt.CheckState.Checked
            ):
                checked_patches.add(patch_item.text())

        selected_patches = {
            self.preset_table.item(index.row(), 1).text()
            for index in self.preset_table.selectionModel().selectedIndexes()
            if self.preset_table.item(index.row(), 1) is not None
        }
        current_patch = None
        current_row = self.preset_table.currentRow()
        if current_row >= 0:
            current_item = self.preset_table.item(current_row, 1)
            if current_item is not None:
                current_patch = current_item.text()
        return _PresetSelectionState(
            checked_patches=frozenset(checked_patches),
            selected_patches=frozenset(selected_patches),
            current_patch=current_patch,
        )

    def _restore_preset_selection_state(self, state: _PresetSelectionState) -> None:
        signals_blocked = self.preset_table.blockSignals(True)
        try:
            for row in range(self.preset_table.rowCount()):
                selected_item = self.preset_table.item(row, 0)
                patch_item = self.preset_table.item(row, 1)
                if selected_item is None or patch_item is None:
                    continue
                selected_item.setCheckState(
                    Qt.CheckState.Checked
                    if patch_item.text() in state.checked_patches
                    else Qt.CheckState.Unchecked
                )
        finally:
            self.preset_table.blockSignals(signals_blocked)

        selection_model = self.preset_table.selectionModel()
        selection_model.clearSelection()
        for patch in state.selected_patches:
            row = self._preset_row(patch)
            if row is None:
                continue
            selection_model.select(
                self.preset_table.model().index(row, 0),
                QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
            )
        if state.current_patch is None:
            self._refresh_preset_measurement_time_estimate()
            return
        current_row = self._preset_row(state.current_patch)
        if current_row is not None:
            selection_model.setCurrentIndex(
                self.preset_table.model().index(current_row, 0),
                QItemSelectionModel.SelectionFlag.NoUpdate,
            )
        self._refresh_preset_measurement_time_estimate()

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
        return (
            column == 2
            or MainWindow._is_snapshot_name_column(column)
            or MainWindow._is_snapshot_adjustment_column(column)
        )

    @staticmethod
    def _is_name_column(column: int) -> bool:
        return column == 2 or MainWindow._is_snapshot_name_column(column)

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
            not self._manual_adjustments_enabled() or not self._is_manual_adjustment_column(column)
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
            before = item.text()
            if column == 1 and Path(self.input_path.text()).suffix.lower() == ".hlx":
                item.setText(value.strip().upper())
            elif column == 2:
                item.setText(self._sanitize_helix_name(value, self._preset_name_max_length()))
            elif self._is_snapshot_name_column(column):
                item.setText(self._sanitize_helix_name(value, self._snapshot_name_max_length()))
            elif self._is_snapshot_adjustment_column(column):
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
            if self._is_name_column(column) and item.text() != before:
                self._set_manual_name_modified(item, True)

        self._manual_cell_editor = None
        self._manual_cell_target = None
        editor.removeEventFilter(self)
        editor.deleteLater()

    def _manual_name_max_length(self, column: int) -> int | None:
        if column == 2:
            return self._preset_name_max_length()
        if self._is_snapshot_name_column(column):
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
            for snapshot_index in range(self.snapshot_count):
                name_item = self.preset_table.item(row, self._snapshot_name_column(snapshot_index))
                adjustment_item = self.preset_table.item(
                    row,
                    self._snapshot_adjustment_column(snapshot_index),
                )
                if name_item is not None:
                    patch_snapshot_names[snapshot_index] = self._validate_helix_name(
                        name_item.text(),
                        self._snapshot_name_max_length(),
                    )
                if adjustment_item is not None:
                    if adjustment_item.data(IGNORED_SNAPSHOT_ROLE):
                        continue
                    if adjustment_item.data(BAD_LUFS_HIGHLIGHT_ROLE):
                        continue
                    stored_value = adjustment_item.data(ADJUSTMENT_VALUE_ROLE)
                    if isinstance(stored_value, (int, float)) and not isinstance(
                        stored_value, bool
                    ):
                        value = float(stored_value)
                    else:
                        try:
                            value = _parse_adjustment_display_text(adjustment_item.text())
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

    def _handle_gain_correction_log(self, message: str) -> None:
        sync_match = GAIN_PRESET_SYNC_PATTERN.match(message)
        if sync_match is not None:
            self._apply_deferred_gain_correction_logs(sync_match["patch"])
            return

        match = self._gain_correction_match(message)
        if match is None:
            return

        patch = match["patch"]
        if (
            self._deferred_gain_correction_patch is not None
            and patch != self._deferred_gain_correction_patch
        ):
            self._apply_deferred_gain_correction_logs(self._deferred_gain_correction_patch)
        self._deferred_gain_correction_logs.append(message)
        self._deferred_gain_correction_patch = patch

    def _apply_deferred_gain_correction_logs(self, device_patch: str | None = None) -> None:
        remaining: list[str] = []
        remaining_patches: set[str] = set()
        for message in self._deferred_gain_correction_logs:
            match = self._gain_correction_match(message)
            if (
                device_patch is not None
                and match is not None
                and match.groupdict().get("patch") != device_patch
            ):
                remaining.append(message)
                remaining_patches.add(match["patch"])
                continue
            self._apply_gain_correction(message)
        self._deferred_gain_correction_logs = remaining
        self._deferred_gain_correction_patch = next(iter(remaining_patches), None)

    @staticmethod
    def _is_gain_correction_log(message: str) -> bool:
        return MainWindow._gain_correction_match(message) is not None

    @staticmethod
    def _gain_correction_match(message: str) -> re.Match[str] | None:
        return (
            GAIN_CORRECTION_PATTERN.match(message)
            or GAIN_STABLE_PATTERN.match(message)
            or GAIN_BAD_LUFS_PATTERN.match(message)
        )

    def _apply_gain_correction(self, message: str) -> None:
        match = self._gain_correction_match(message)
        if match is None:
            return

        row = self._preset_row(match["patch"])
        if row is None:
            return

        selected = self.preset_table.item(row, 0)
        if selected is None or selected.checkState() != Qt.CheckState.Checked:
            self._clear_preset_adjustments(row)
            return

        label = match["label"]
        is_solo = label.endswith(" (S)")
        if is_solo:
            label = label[:-4]
        snapshot_position = self._snapshot_position_for_gain_log(row, match["patch"], label)
        if snapshot_position >= self.snapshot_count:
            return
        name_column = self._snapshot_name_column(snapshot_position)
        output_column = self._snapshot_output_column(snapshot_position)
        adjustment_column = self._snapshot_adjustment_column(snapshot_position)
        name_item = self.preset_table.item(row, name_column)
        output_item = self.preset_table.item(row, output_column)
        adjustment_item = self.preset_table.item(row, adjustment_column)
        if name_item is None or output_item is None or adjustment_item is None:
            return
        if not name_item.text():
            self._set_snapshot_name(
                name_item,
                label,
                is_solo,
                self._is_ignored_snapshot_name(label),
            )
        if name_item.data(IGNORED_SNAPSHOT_ROLE) or self._is_ignored_snapshot_name(
            name_item.text() or label
        ):
            self._set_ignored_snapshot_highlight(row, snapshot_position, True)
            self.preset_snapshot_positions[match["patch"]] = max(
                self.preset_snapshot_positions.get(match["patch"], 0),
                snapshot_position + 1,
            )
            return
        if match.re is GAIN_BAD_LUFS_PATTERN:
            detail = match.groupdict().get("detail")
            adjustment = _bad_lufs_adjustment(detail, output_item.text())
            if adjustment is None and adjustment_item.data(BAD_LUFS_HIGHLIGHT_ROLE):
                try:
                    adjustment = _parse_adjustment_display_text(adjustment_item.text())
                except ValueError:
                    adjustment = None
            display_text, tooltip = _bad_lufs_adjustment_display(
                detail,
                adjustment=adjustment,
            )
            adjustment_item.setText(display_text)
            adjustment_item.setData(ADJUSTMENT_VALUE_ROLE, None)
            adjustment_item.setToolTip(tooltip)
            adjustment_item.setForeground(QBrush(BAD_LUFS_FOREGROUND))
            font = adjustment_item.font()
            font.setBold(True)
            font.setPointSize(max(QApplication.font().pointSize(), 9))
            adjustment_item.setFont(font)
            self._refresh_adjustment_cell_widget(adjustment_item)
            self._set_bad_lufs_highlight(row, snapshot_position)
            self._adjusted_presets.add(match["patch"])
            self.preset_snapshot_positions[match["patch"]] = max(
                self.preset_snapshot_positions.get(match["patch"], 0),
                snapshot_position + 1,
            )
            return

        output_level = match.groupdict().get("before") or match.groupdict().get("after")
        if output_level is not None:
            self._set_output_level(output_item, output_level)

        actual_adjustment = float(match["delta"])
        custom_adjustment = self._custom_adjustment_for_snapshot(
            match["patch"],
            snapshot_position,
        )
        display_adjustment = (
            actual_adjustment - custom_adjustment
            if custom_adjustment is not None
            else actual_adjustment
        )
        self._set_adjustment_value(
            adjustment_item,
            _format_adjustment(display_adjustment)
            if custom_adjustment is not None
            else match["delta"],
            actual_adjustment,
            custom_adjustment,
            display_adjustment if custom_adjustment is not None else None,
        )
        self._refresh_adjustment_cell_widget(adjustment_item)
        self._adjusted_presets.add(match["patch"])
        self.preset_snapshot_positions[match["patch"]] = max(
            self.preset_snapshot_positions.get(match["patch"], 0),
            snapshot_position + 1,
        )

    def _snapshot_position_for_gain_log(self, row: int, patch: str, label: str) -> int:
        cursor = self.preset_snapshot_positions.get(patch, 0)
        candidates = []
        for snapshot_index in range(self.snapshot_count):
            item = self.preset_table.item(row, self._snapshot_name_column(snapshot_index))
            if item is not None and item.text() == label:
                candidates.append(snapshot_index)

        if len(candidates) == 1:
            return candidates[0]

        remaining_candidates = [candidate for candidate in candidates if candidate >= cursor]
        if len(remaining_candidates) == 1:
            return remaining_candidates[0]

        return cursor

    def _apply_snapshot_measurement(self, event: ProgressEvent) -> None:
        if event.device_patch is None or event.snapshot is None or event.lufs is None:
            return

        row = self._preset_row(event.device_patch)
        if row is None:
            return

        selected = self.preset_table.item(row, 0)
        if selected is None or selected.checkState() != Qt.CheckState.Checked:
            return

        snapshot_index = event.snapshot - 1
        if snapshot_index < 0 or snapshot_index >= self.snapshot_count:
            return

        adjustment_column = self._snapshot_adjustment_column(snapshot_index)
        adjustment_item = self.preset_table.item(row, adjustment_column)
        if adjustment_item is None:
            return
        if adjustment_item.data(IGNORED_SNAPSHOT_ROLE):
            self._set_adjustment_ignored(adjustment_item)
            return

        policy = self._normalization_policy()
        gain_delta = self._measurement_gain_delta(event, policy)

        name_item = self.preset_table.item(row, self._snapshot_name_column(snapshot_index))
        is_solo = name_item is not None and self._is_solo_snapshot_name(name_item.text())
        is_ignored = name_item is not None and self._is_ignored_snapshot_name(name_item.text())
        if is_ignored:
            self._set_ignored_snapshot_highlight(row, snapshot_index, True)
            self._set_adjustment_ignored(adjustment_item)
            return
        if is_solo:
            gain_delta += policy.solo_gain_bump_db

        custom_adjustment = self._custom_adjustment_for_snapshot(event.device_patch, snapshot_index)
        if custom_adjustment is not None:
            gain_delta += custom_adjustment
        display_adjustment = (
            gain_delta - custom_adjustment if custom_adjustment is not None else gain_delta
        )
        implausible_output_gain = self._implausible_snapshot_output_gain(
            event.device_patch,
            snapshot_index,
            gain_delta,
        )
        if implausible_output_gain is not None:
            self._set_bad_snapshot_measurement(
                row,
                snapshot_index,
                f"Implausible output gain {implausible_output_gain:g} dB",
                adjustment=display_adjustment,
            )
            self._adjusted_presets.add(event.device_patch)
            return

        self._set_adjustment_value(
            adjustment_item,
            _format_adjustment(display_adjustment),
            gain_delta,
            custom_adjustment,
            display_adjustment if custom_adjustment is not None else None,
        )
        self._refresh_adjustment_cell_widget(adjustment_item)
        self._adjusted_presets.add(event.device_patch)

    def _apply_snapshot_measurement_failure(self, event: ProgressEvent) -> None:
        if event.device_patch is None or event.snapshot is None:
            return

        row = self._preset_row(event.device_patch)
        if row is None:
            return

        selected = self.preset_table.item(row, 0)
        if selected is None or selected.checkState() != Qt.CheckState.Checked:
            return

        snapshot_index = event.snapshot - 1
        if snapshot_index < 0 or snapshot_index >= self.snapshot_count:
            return

        adjustment_item = self.preset_table.item(
            row,
            self._snapshot_adjustment_column(snapshot_index),
        )
        if adjustment_item is not None and adjustment_item.data(IGNORED_SNAPSHOT_ROLE):
            self._set_adjustment_ignored(adjustment_item)
            return
        self._set_bad_snapshot_measurement(row, snapshot_index, event.message)
        self._adjusted_presets.add(event.device_patch)

    def _set_bad_snapshot_measurement(
        self,
        row: int,
        snapshot_index: int,
        detail: str | None = None,
        *,
        adjustment: float | None = None,
    ) -> None:
        adjustment_item = self.preset_table.item(
            row,
            self._snapshot_adjustment_column(snapshot_index),
        )
        if adjustment_item is None:
            return

        display_text, tooltip = _bad_lufs_adjustment_display(detail, adjustment=adjustment)
        if detail and display_text == "Measurement failed ⚠️":
            tooltip = f"{tooltip}\n\nMeasurement detail: {detail}"
        adjustment_item.setText(display_text)
        adjustment_item.setData(ADJUSTMENT_VALUE_ROLE, None)
        adjustment_item.setToolTip(tooltip)
        adjustment_item.setForeground(QBrush(BAD_LUFS_FOREGROUND))
        font = adjustment_item.font()
        font.setBold(True)
        font.setPointSize(max(QApplication.font().pointSize(), 9))
        adjustment_item.setFont(font)
        self._refresh_adjustment_cell_widget(adjustment_item)
        self._set_bad_lufs_highlight(row, snapshot_index)

    def _implausible_snapshot_output_gain(
        self,
        patch: str,
        snapshot_index: int,
        gain_delta: float,
    ) -> float | None:
        row = self._preset_row(patch)
        if row is None:
            return None
        item = self.preset_table.item(row, self._snapshot_output_column(snapshot_index))
        if item is None:
            return None
        for value in _parse_output_level_display_text(item.text()):
            output_gain = round(value + gain_delta, 2)
            if not -120.0 <= output_gain <= 20.0:
                return output_gain
        return None

    def _normalization_policy(self) -> NormalizationPolicy:
        if self.completed_request is not None:
            return self.completed_request.policy
        return NormalizationPolicy(snapshot_count=self.snapshot_count)

    def _measurement_gain_delta(
        self,
        event: ProgressEvent,
        policy: NormalizationPolicy,
    ) -> float:
        crest_factor_correction = 0.0
        if event.crest_factor_db is not None:
            crest_factor_correction = min(
                max(
                    (policy.crest_factor_reference_db - event.crest_factor_db)
                    * policy.crest_factor_correction_ratio,
                    0.0,
                ),
                policy.max_crest_factor_correction_db,
            )
        return round(self._target_lufs() - event.lufs - crest_factor_correction, 1)

    def _custom_adjustment_for_snapshot(
        self,
        patch: str,
        snapshot_index: int,
    ) -> float | None:
        preset_adjustments = self._custom_adjustments.get(patch)
        if preset_adjustments is None and Path(self.input_path.text()).suffix.lower() == ".hlx":
            preset_adjustments = self._custom_adjustments.get(self._single_preset_slot_text())
        if preset_adjustments is None:
            return None
        return preset_adjustments.get(snapshot_index)

    def _configure_snapshot_columns(self, snapshot_count: int) -> None:
        self.snapshot_count = snapshot_count
        labels = ["", "Preset", "Name"]
        for snapshot in range(1, snapshot_count + 1):
            labels.extend([str(snapshot), "Out (dB)", "Δ (dB)"])
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
            output_width = self._output_level_column_width()
            adjustment_width = self._adjustment_column_width()
            for snapshot_index in range(snapshot_count):
                self.preset_table.setColumnWidth(self._snapshot_name_column(snapshot_index), 100)
                self.preset_table.setColumnWidth(
                    self._snapshot_output_column(snapshot_index),
                    output_width,
                )
                self.preset_table.setColumnWidth(
                    self._snapshot_adjustment_column(snapshot_index),
                    adjustment_width,
                )
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
                            f"Current output block level for snapshot {snapshot}.",
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
                self._refresh_snapshot_output_levels(row)

    def _snapshot_count_changed(self, snapshot_count: int) -> None:
        if hasattr(self, "preset_table"):
            self._configure_snapshot_columns(snapshot_count)

    def _adjustment_column_width(self) -> int:
        sample = "+12.5 (+12.5)"
        padding = 18
        return max(92, self.preset_table.fontMetrics().horizontalAdvance(sample) + padding)

    def _output_level_column_width(self) -> int:
        sample = "Out (dB)"
        value_sample = "-60.0, -60.0"
        padding = 18
        metrics = self.preset_table.fontMetrics()
        return max(
            64,
            metrics.horizontalAdvance(sample) + padding,
            metrics.horizontalAdvance(value_sample) + padding,
        )

    @staticmethod
    def _snapshot_name_column(snapshot_index: int) -> int:
        return SNAPSHOT_TABLE_START_COLUMN + snapshot_index * SNAPSHOT_TABLE_COLUMN_STRIDE

    @staticmethod
    def _snapshot_output_column(snapshot_index: int) -> int:
        return MainWindow._snapshot_name_column(snapshot_index) + 1

    @staticmethod
    def _snapshot_adjustment_column(snapshot_index: int) -> int:
        return MainWindow._snapshot_name_column(snapshot_index) + 2

    @staticmethod
    def _is_snapshot_name_column(column: int) -> bool:
        return (
            column >= SNAPSHOT_TABLE_START_COLUMN
            and (column - SNAPSHOT_TABLE_START_COLUMN) % SNAPSHOT_TABLE_COLUMN_STRIDE == 0
        )

    @staticmethod
    def _is_snapshot_adjustment_column(column: int) -> bool:
        return (
            column >= SNAPSHOT_TABLE_START_COLUMN
            and (column - SNAPSHOT_TABLE_START_COLUMN) % SNAPSHOT_TABLE_COLUMN_STRIDE == 2
        )

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
        for snapshot_index in range(self.snapshot_count):
            name_column = self._snapshot_name_column(snapshot_index)
            output_column = self._snapshot_output_column(snapshot_index)
            adjustment_column = self._snapshot_adjustment_column(snapshot_index)
            name = self.preset_table.item(row, name_column)
            output = self.preset_table.item(row, output_column)
            adjustment = self.preset_table.item(row, adjustment_column)
            if name is None:
                name = QTableWidgetItem()
                self.preset_table.setItem(row, name_column, name)
            if output is None:
                output = QTableWidgetItem()
                self.preset_table.setItem(row, output_column, output)
            if adjustment is None:
                adjustment = QTableWidgetItem()
                self.preset_table.setItem(row, adjustment_column, adjustment)
            self._set_preset_item_editable(
                name,
                False,
            )
            self._set_preset_item_editable(
                output,
                False,
            )
            self._set_preset_item_editable(
                adjustment,
                False,
            )
            self._set_output_level(output, "")
            adjustment.setData(RECORDED_OUTPUT_PATH_ROLE, None)
            self._set_adjustment_value(adjustment, "+0", 0)
        self._refresh_snapshot_output_levels(row)

    def _mark_selected_preset_adjustments_pending(self, row: int) -> None:
        selected = self.preset_table.item(row, 0)
        if selected is None or selected.checkState() != Qt.CheckState.Checked:
            return
        for snapshot_index in range(self.snapshot_count):
            item = self.preset_table.item(row, self._snapshot_adjustment_column(snapshot_index))
            if item is not None:
                if item.data(IGNORED_SNAPSHOT_ROLE):
                    self._set_adjustment_ignored(item)
                    continue
                self._set_adjustment_pending(item)

    @staticmethod
    def _set_adjustment_pending(item: QTableWidgetItem) -> None:
        table = item.tableWidget()
        signals_blocked = table.blockSignals(True) if table is not None else False
        try:
            item.setText("?")
            item.setData(ADJUSTMENT_VALUE_ROLE, None)
            item.setData(RECORDED_OUTPUT_PATH_ROLE, None)
            item.setToolTip("This selected snapshot has not been measured yet.")
            font = item.font()
            font.setBold(False)
            font.setPointSize(max(QApplication.font().pointSize(), 9))
            item.setFont(font)
            item.setForeground(QBrush(QColor("#6b7280")))
            if table is not None:
                table.removeCellWidget(item.row(), item.column())
        finally:
            if table is not None:
                table.blockSignals(signals_blocked)

    def _set_bad_lufs_highlight(self, row: int, snapshot_index: int) -> None:
        signals_blocked = self.preset_table.blockSignals(True)
        try:
            columns = (
                1,
                2,
                self._snapshot_name_column(snapshot_index),
                self._snapshot_output_column(snapshot_index),
                self._snapshot_adjustment_column(snapshot_index),
            )
            for column in columns:
                item = self.preset_table.item(row, column)
                if item is not None:
                    item.setData(BAD_LUFS_HIGHLIGHT_ROLE, True)
                    self._refresh_preset_item_background(item)
                    self._refresh_preset_cell_widget_background(item)
        finally:
            self.preset_table.blockSignals(signals_blocked)

    def _clear_bad_lufs_highlight(self, row: int) -> None:
        signals_blocked = self.preset_table.blockSignals(True)
        try:
            for column in range(self.preset_table.columnCount()):
                item = self.preset_table.item(row, column)
                if item is not None:
                    item.setData(BAD_LUFS_HIGHLIGHT_ROLE, None)
                    self._refresh_preset_item_background(item)
                    self._refresh_preset_cell_widget_background(item)
        finally:
            self.preset_table.blockSignals(signals_blocked)

    def _clear_bad_lufs_highlights(self) -> None:
        for row in range(self.preset_table.rowCount()):
            self._clear_bad_lufs_highlight(row)

    def _set_ignored_snapshot_highlight(
        self,
        row: int,
        snapshot_index: int,
        ignored: bool,
    ) -> None:
        signals_blocked = self.preset_table.blockSignals(True)
        try:
            for column in (
                self._snapshot_name_column(snapshot_index),
                self._snapshot_output_column(snapshot_index),
                self._snapshot_adjustment_column(snapshot_index),
            ):
                item = self.preset_table.item(row, column)
                if item is None:
                    continue
                item.setData(IGNORED_SNAPSHOT_ROLE, True if ignored else None)
                item.setForeground(QBrush(IGNORED_SNAPSHOT_FOREGROUND) if ignored else QBrush())
                self._refresh_preset_item_background(item)
                self._refresh_preset_cell_widget_background(item)
            adjustment = self.preset_table.item(
                row,
                self._snapshot_adjustment_column(snapshot_index),
            )
            if adjustment is not None:
                if ignored:
                    self._set_adjustment_ignored(adjustment)
                elif (
                    adjustment.text() in {"-", "Ignore"}
                    and adjustment.data(ADJUSTMENT_VALUE_ROLE) is None
                ):
                    self._set_adjustment_value(adjustment, "+0", 0)
        finally:
            self.preset_table.blockSignals(signals_blocked)

    @staticmethod
    def _set_adjustment_ignored(item: QTableWidgetItem) -> None:
        table = item.tableWidget()
        signals_blocked = table.blockSignals(True) if table is not None else False
        try:
            item.setText("-")
            item.setData(ADJUSTMENT_VALUE_ROLE, None)
            item.setData(RECORDED_OUTPUT_PATH_ROLE, None)
            item.setToolTip("This snapshot is skipped during normalization.")
            font = item.font()
            font.setBold(False)
            font.setPointSize(max(QApplication.font().pointSize(), 9))
            item.setFont(font)
            item.setForeground(QBrush(IGNORED_SNAPSHOT_FOREGROUND))
            if table is not None:
                table.removeCellWidget(item.row(), item.column())
        finally:
            if table is not None:
                table.blockSignals(signals_blocked)

    def _set_manual_name_modified(self, item: QTableWidgetItem, modified: bool) -> None:
        signals_blocked = self.preset_table.blockSignals(True)
        try:
            item.setData(MANUAL_NAME_MODIFIED_ROLE, True if modified else None)
            self._refresh_preset_item_background(item)
        finally:
            self.preset_table.blockSignals(signals_blocked)

    def _clear_manual_name_modified_highlights(self) -> None:
        for row in range(self.preset_table.rowCount()):
            for column in range(self.preset_table.columnCount()):
                item = self.preset_table.item(row, column)
                if item is not None and item.data(MANUAL_NAME_MODIFIED_ROLE):
                    self._set_manual_name_modified(item, False)

    @staticmethod
    def _refresh_preset_item_background(item: QTableWidgetItem) -> None:
        if item.data(BAD_LUFS_HIGHLIGHT_ROLE):
            item.setBackground(BAD_LUFS_ROW_BACKGROUND)
        elif item.data(NORMALIZATION_FOCUS_ROLE):
            item.setBackground(NORMALIZATION_FOCUS_BACKGROUND)
        elif item.data(MANUAL_NAME_MODIFIED_ROLE):
            item.setBackground(MANUAL_NAME_MODIFIED_BACKGROUND)
        elif item.data(IGNORED_SNAPSHOT_ROLE):
            item.setBackground(IGNORED_SNAPSHOT_BACKGROUND)
        else:
            item.setBackground(QBrush())

    @staticmethod
    def _refresh_preset_cell_widget_background(item: QTableWidgetItem) -> None:
        table = item.tableWidget()
        if table is None:
            return
        widget = table.cellWidget(item.row(), item.column())
        if widget is not None:
            MainWindow._style_table_cell_widget(widget, item)

    def _set_snapshot_names(self, row: int, snapshot_names: tuple[str, ...]) -> None:
        name_item = self.preset_table.item(row, 2)
        if name_item is not None:
            name_item.setData(Qt.ItemDataRole.UserRole, snapshot_names)
        self._refresh_snapshot_names(row)

    def _set_snapshot_output_levels(self, row: int, levels: object) -> None:
        name_item = self.preset_table.item(row, 2)
        if name_item is not None:
            name_item.setData(
                SNAPSHOT_OUTPUT_LEVELS_ROLE, _normalize_snapshot_output_levels(levels)
            )
        self._refresh_snapshot_output_levels(row)

    def _refresh_snapshot_output_levels(self, row: int) -> None:
        name_item = self.preset_table.item(row, 2)
        levels = name_item.data(SNAPSHOT_OUTPUT_LEVELS_ROLE) if name_item is not None else ()
        levels = levels if isinstance(levels, tuple) else ()
        for snapshot_index in range(self.snapshot_count):
            item = self.preset_table.item(row, self._snapshot_output_column(snapshot_index))
            if item is not None:
                self._set_output_level(item, _format_snapshot_output_levels(levels, snapshot_index))

    def _refresh_snapshot_names(self, row: int) -> None:
        name_item = self.preset_table.item(row, 2)
        snapshot_names = name_item.data(Qt.ItemDataRole.UserRole) if name_item is not None else ()
        snapshot_names = snapshot_names if isinstance(snapshot_names, tuple) else ()
        try:
            solo_pattern = re.compile(self.solo_regex.text())
        except re.error:
            solo_pattern = None
        try:
            ignore_pattern = re.compile(self.ignore_snapshot_regex.text())
        except re.error:
            ignore_pattern = None
        for snapshot_index in range(self.snapshot_count):
            item = self.preset_table.item(row, self._snapshot_name_column(snapshot_index))
            if item is not None:
                self._set_snapshot_name(item, "", False, False)
                self._set_ignored_snapshot_highlight(row, snapshot_index, False)
        for snapshot, name in enumerate(snapshot_names[: self.snapshot_count]):
            item = self.preset_table.item(row, self._snapshot_name_column(snapshot))
            if item is not None:
                is_ignored = ignore_pattern is not None and ignore_pattern.search(name) is not None
                self._set_snapshot_name(
                    item,
                    name,
                    solo_pattern is not None and solo_pattern.search(name) is not None,
                    is_ignored,
                )
                self._set_ignored_snapshot_highlight(row, snapshot, is_ignored)

    def _refresh_all_snapshot_names(self) -> None:
        if not hasattr(self, "preset_table"):
            return
        for row in range(self.preset_table.rowCount()):
            self._refresh_snapshot_names(row)

    @staticmethod
    def _set_snapshot_name(
        item: QTableWidgetItem,
        name: str,
        is_solo: bool,
        is_ignored: bool = False,
    ) -> None:
        table = item.tableWidget()
        signals_blocked = table.blockSignals(True) if table is not None else False
        try:
            item.setText(name)
            item.setIcon(QIcon())
            item.setToolTip(_snapshot_tooltip(is_solo, is_ignored))
        finally:
            if table is not None:
                table.blockSignals(signals_blocked)
        if table is None:
            return
        if not is_solo:
            table.removeCellWidget(item.row(), item.column())
            return
        label = SnapshotNameCellWidget(f"{escape(name)} <span style='color: #f59e0b;'>★</span>")
        label.setContentsMargins(3, 0, 0, 0)
        label.setToolTip(item.toolTip())
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        MainWindow._style_table_cell_widget(label, item)
        table.setCellWidget(item.row(), item.column(), label)

    def _preset_item_changed(self, item: QTableWidgetItem) -> None:
        if item.data(PRESET_TABLE_ATTENTION_ROLE):
            item.setData(PRESET_TABLE_ATTENTION_ROLE, None)
            self.preset_table.viewport().update(self.preset_table.visualItemRect(item))
        if item.column() == 0:
            self._refresh_preset_measurement_time_estimate()
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
            elif self._is_snapshot_name_column(item.column()):
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
                    snapshot_index = (
                        item.column() - SNAPSHOT_TABLE_START_COLUMN
                    ) // SNAPSHOT_TABLE_COLUMN_STRIDE
                    snapshot_names.extend(
                        "" for _ in range(snapshot_index + 1 - len(snapshot_names))
                    )
                    snapshot_names[snapshot_index] = item.text()
                    name_item.setData(Qt.ItemDataRole.UserRole, tuple(snapshot_names))
                try:
                    solo_pattern = re.compile(self.solo_regex.text())
                except re.error:
                    solo_pattern = None
                try:
                    ignore_pattern = re.compile(self.ignore_snapshot_regex.text())
                except re.error:
                    ignore_pattern = None
                is_ignored = (
                    ignore_pattern is not None and ignore_pattern.search(item.text()) is not None
                )
                self._set_snapshot_name(
                    item,
                    item.text(),
                    solo_pattern is not None and solo_pattern.search(item.text()) is not None,
                    is_ignored,
                )
                snapshot_index = (
                    item.column() - SNAPSHOT_TABLE_START_COLUMN
                ) // SNAPSHOT_TABLE_COLUMN_STRIDE
                self._set_ignored_snapshot_highlight(item.row(), snapshot_index, is_ignored)
                self._refresh_measurement_time_estimate()
            elif self._is_snapshot_adjustment_column(item.column()):
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
        if (
            Path(self.input_path.text()).suffix.lower() == ".hlx"
            and self.preset_table.rowCount() == 1
        ):
            return 0
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
    def _set_adjustment_value(
        item: QTableWidgetItem,
        text: str,
        value: float,
        custom_adjustment: float | None = None,
        display_value: float | None = None,
    ) -> None:
        if item.data(IGNORED_SNAPSHOT_ROLE):
            MainWindow._set_adjustment_ignored(item)
            return
        table = item.tableWidget()
        signals_blocked = table.blockSignals(True) if table is not None else False
        try:
            if custom_adjustment is None and display_value is None:
                display_value = value
                display_text = "0" if value == 0 else str(text)
            else:
                display_value = value if display_value is None else display_value
                display_text = _format_adjustment(display_value)
            if custom_adjustment is not None:
                display_text += f" ({_format_adjustment(custom_adjustment)})"
            item.setText(display_text)
            item.setData(ADJUSTMENT_VALUE_ROLE, value)
            item.setToolTip(
                f"Custom loudness adjustment: {_format_adjustment(custom_adjustment)}"
                if custom_adjustment is not None
                else ""
            )
            font = item.font()
            font.setBold(False)
            font.setPointSize(max(QApplication.font().pointSize(), 9))
            item.setFont(font)
            item.setForeground(
                QBrush(IGNORED_SNAPSHOT_FOREGROUND)
                if item.data(IGNORED_SNAPSHOT_ROLE)
                else QBrush()
            )
            if table is not None:
                table.removeCellWidget(item.row(), item.column())
                if custom_adjustment is not None:
                    label = QLabel(
                        f"{escape(_format_adjustment(display_value))} "
                        f"<span style='color: {CUSTOM_ADJUSTMENT_COLOR};'>"
                        f"({escape(_format_adjustment(custom_adjustment))})"
                        f"</span>"
                    )
                    MainWindow._style_adjustment_cell_widget(label, item)
                    MainWindow._style_adjustment_label(label, item)
                    label.setContentsMargins(3, 0, 0, 0)
                    label.setToolTip(item.toolTip())
                    label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                    table.setCellWidget(item.row(), item.column(), label)
        finally:
            if table is not None:
                table.blockSignals(signals_blocked)

    @staticmethod
    def _set_output_level(item: QTableWidgetItem, value: str | float) -> None:
        table = item.tableWidget()
        signals_blocked = table.blockSignals(True) if table is not None else False
        try:
            if isinstance(value, str):
                text = value
            else:
                text = f"{value:.1f}"
            item.setText(text)
            item.setToolTip(f"Current output block level: {text} dB" if text else "")
            font = item.font()
            font.setBold(False)
            font.setPointSize(max(QApplication.font().pointSize(), 9))
            item.setFont(font)
            item.setForeground(
                QBrush(IGNORED_SNAPSHOT_FOREGROUND)
                if item.data(IGNORED_SNAPSHOT_ROLE)
                else QBrush()
            )
            if table is not None:
                table.removeCellWidget(item.row(), item.column())
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
        name = self.preset_table.item(row, self._snapshot_name_column(event.snapshot - 1))
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
        self._clear_manual_name_modified_highlights()
        self._refresh_file_actions()

    def _preset_table_content_signature(self) -> tuple[tuple[str, ...], ...]:
        return tuple(
            tuple(self._preset_table_csv_row(row)) for row in range(self.preset_table.rowCount())
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


class SnapshotNameCellWidget(QLabel):
    """Snapshot-name cell widget that keeps table group separators visible."""

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        pen = QPen(self.palette().mid().color())
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawLine(0, 0, 0, self.height())


class ContentHeightTableWidget(QTableWidget):
    """Grow with preset rows until an internal scrollbar is more useful."""

    MAX_VISIBLE_ROWS = 12

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._normalizing_row: int | None = None
        self._normalizing_snapshot: int | None = None

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        self._paint_snapshot_group_separators()
        self._paint_normalization_focus()

    def set_normalization_focus(self, row: int, snapshot_index: int | None) -> None:
        previous_row = self._normalizing_row
        previous_snapshot = self._normalizing_snapshot
        self._normalizing_row = row
        self._normalizing_snapshot = snapshot_index
        self._refresh_normalization_focus_background(previous_row)
        self._refresh_normalization_focus_background(row)
        self._update_normalization_focus_rect(previous_row, previous_snapshot)
        self._update_normalization_focus_rect(row, snapshot_index)

    def clear_normalization_focus(self) -> None:
        if self._normalizing_row is None and self._normalizing_snapshot is None:
            return
        previous_row = self._normalizing_row
        previous_snapshot = self._normalizing_snapshot
        self._normalizing_row = None
        self._normalizing_snapshot = None
        self._refresh_normalization_focus_background(previous_row)
        self._update_normalization_focus_rect(previous_row, previous_snapshot)

    def clear_normalization_snapshot_focus(self, row: int) -> None:
        if self._normalizing_row != row or self._normalizing_snapshot is None:
            return
        previous_snapshot = self._normalizing_snapshot
        previous_columns = self._normalization_focus_columns(previous_snapshot)
        previous_rects = self._normalization_focus_cell_rects(row, previous_snapshot)
        self._normalizing_snapshot = None
        for column in previous_columns:
            item = self.item(row, column)
            if item is None:
                continue
            item.setData(NORMALIZATION_FOCUS_ROLE, None)
            MainWindow._refresh_preset_item_background(item)
            MainWindow._refresh_preset_cell_widget_background(item)
            widget = self.cellWidget(row, column)
            if widget is not None:
                widget.repaint()
        for rect in previous_rects:
            self.viewport().repaint(rect.adjusted(-3, -3, 3, 3))
        previous_rect = _united_rects(previous_rects)
        if previous_rect is not None:
            self.viewport().repaint(previous_rect.adjusted(-3, -3, 3, 3))

    def _refresh_normalization_focus_background(self, row: int | None) -> None:
        if row is None or not 0 <= row < self.rowCount():
            return
        focused = row == self._normalizing_row
        focus_columns = {1, 2}
        if focused:
            focus_columns.update(range(SNAPSHOT_TABLE_START_COLUMN, self.columnCount()))
        for column in range(self.columnCount()):
            item = self.item(row, column)
            if item is None:
                continue
            item.setData(
                NORMALIZATION_FOCUS_ROLE,
                True
                if focused and column in focus_columns and not item.data(IGNORED_SNAPSHOT_ROLE)
                else None,
            )
            MainWindow._refresh_preset_item_background(item)
            MainWindow._refresh_preset_cell_widget_background(item)
        self.viewport().update()

    def _update_normalization_focus_rect(
        self,
        row: int | None,
        snapshot_index: int | None,
    ) -> None:
        rect = self._normalization_focus_rect(row, snapshot_index)
        if rect is not None:
            self.viewport().update(rect.adjusted(-3, -3, 3, 3))

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

    def _paint_snapshot_group_separators(self) -> None:
        header = self.horizontalHeader()
        if self.columnCount() <= SNAPSHOT_TABLE_START_COLUMN:
            return

        painter = QPainter(self.viewport())
        pen = QPen(self.palette().mid().color())
        pen.setWidth(2)
        painter.setPen(pen)
        for logical_index in range(
            SNAPSHOT_TABLE_START_COLUMN,
            self.columnCount(),
            SNAPSHOT_TABLE_COLUMN_STRIDE,
        ):
            if self.isColumnHidden(logical_index):
                continue
            x = header.sectionViewportPosition(logical_index)
            if -pen.width() <= x <= self.viewport().width():
                painter.drawLine(x, 0, x, self.viewport().height())

    def _paint_normalization_focus(self) -> None:
        if self._normalizing_row is None:
            return
        snapshot_rect = self._normalization_focus_rect(
            self._normalizing_row,
            self._normalizing_snapshot,
        )
        if snapshot_rect is None:
            return

        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        snapshot_pen = QPen(NORMALIZATION_FOCUS_BLUE)
        snapshot_pen.setWidth(3)
        painter.setPen(snapshot_pen)
        painter.drawRect(snapshot_rect.adjusted(0, 0, -1, -1))

    def _normalization_focus_rect(
        self,
        row: int | None,
        snapshot_index: int | None,
    ) -> QRect | None:
        return _united_rects(self._normalization_focus_cell_rects(row, snapshot_index))

    def _normalization_focus_cell_rects(
        self,
        row: int | None,
        snapshot_index: int | None,
    ) -> tuple[QRect, ...]:
        if row is None or snapshot_index is None:
            return ()
        if not 0 <= row < self.rowCount():
            return ()

        rects = []
        for column in self._normalization_focus_columns(snapshot_index):
            if column >= self.columnCount() or self.isColumnHidden(column):
                continue
            cell_rect = self.visualRect(self.model().index(row, column))
            if not cell_rect.isValid():
                continue
            rects.append(cell_rect)
        return tuple(rects)

    @staticmethod
    def _normalization_focus_columns(snapshot_index: int) -> tuple[int, int, int]:
        return (
            MainWindow._snapshot_name_column(snapshot_index),
            MainWindow._snapshot_output_column(snapshot_index),
            MainWindow._snapshot_adjustment_column(snapshot_index),
        )

    @contextmanager
    def updates_paused(self) -> Iterator[None]:
        updates_enabled = self.updatesEnabled()
        self.setUpdatesEnabled(False)
        try:
            yield
        finally:
            self.setUpdatesEnabled(updates_enabled)
            self.viewport().update()


def _united_rects(rects: tuple[QRect, ...]) -> QRect | None:
    united = None
    for rect in rects:
        united = QRect(rect) if united is None else united.united(rect)
    return united


class MeasurementOptimizationSetupDialog(QDialog):
    def __init__(
        self,
        settings: MeasurementOptimizationSettings,
        preset_label: str,
        preset_id: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Parameter study setup")
        self.resize(520, 360)
        self._parameter_inputs: dict[str, QDoubleSpinBox] = {}
        self._parameter_pins: dict[str, QCheckBox] = {}
        self._parameter_input_order: list[QDoubleSpinBox] = []

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        for parameter in TIMING_PARAMETERS:
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            input_widget = QDoubleSpinBox()
            input_widget.setRange(0.0, 3600.0)
            input_widget.setDecimals(6)
            input_widget.setSingleStep(0.01)
            input_widget.setSuffix(" s")
            input_widget.setValue(float(getattr(settings, parameter.name)))
            input_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self._ignore_return_key_for_spin_box(input_widget)
            pin_widget = QCheckBox("Pin")
            pin_widget.setChecked(parameter.name in settings.pinned_parameters)
            pin_widget.setToolTip(
                "Use this value as the optimal value and skip optimizing this parameter."
            )
            row_layout.addWidget(input_widget)
            row_layout.addWidget(pin_widget)
            form.addRow(parameter.label, row_widget)
            self._parameter_inputs[parameter.name] = input_widget
            self._parameter_input_order.append(input_widget)
            self._parameter_pins[parameter.name] = pin_widget

        self.stability_runs = QSpinBox()
        self.stability_runs.setRange(2, 50)
        self.stability_runs.setValue(settings.stability_runs)
        self._ignore_return_key_for_spin_box(self.stability_runs)
        form.addRow("Stability runs", self.stability_runs)

        self.termination_tolerance = QDoubleSpinBox()
        self.termination_tolerance.setRange(0.1, 100.0)
        self.termination_tolerance.setDecimals(1)
        self.termination_tolerance.setSuffix(" %")
        self.termination_tolerance.setValue(settings.termination_tolerance)
        self._ignore_return_key_for_spin_box(self.termination_tolerance)
        form.addRow("Termination tolerance", self.termination_tolerance)

        self.stability_tolerance = QDoubleSpinBox()
        self.stability_tolerance.setRange(0.0, 100.0)
        self.stability_tolerance.setDecimals(3)
        self.stability_tolerance.setSuffix(" %")
        self.stability_tolerance.setValue(settings.stability_tolerance)
        self._ignore_return_key_for_spin_box(self.stability_tolerance)
        form.addRow("Stability tolerance", self.stability_tolerance)

        self.optimization_preset_hint = QLabel(
            "Optimization will use preset "
            f"{preset_label} (preset number {preset_id}). "
            "Before running it, make sure the matching measurement preset or setlist "
            "is already loaded on the device. You can save one from the main window "
            'toolbar with "Save Measurement File".'
        )
        self.optimization_preset_hint.setTextFormat(Qt.TextFormat.PlainText)
        self.optimization_preset_hint.setWordWrap(True)
        self.optimization_preset_hint.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.optimization_preset_hint.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout.addWidget(self.optimization_preset_hint)

        buttons = QDialogButtonBox()
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.run_button = buttons.addButton(
            "Run",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self.run_button.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _ignore_return_key_for_spin_box(self, spin_box: QAbstractSpinBox) -> None:
        spin_box.installEventFilter(self)
        spin_box.lineEdit().installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.KeyPress:
            key = event.key() if isinstance(event, QKeyEvent) else None
            if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
                if self._focus_next_parameter_input(watched):
                    return True
                return True
        return super().eventFilter(watched, event)

    def _focus_next_parameter_input(self, watched: QObject) -> bool:
        for index, input_widget in enumerate(self._parameter_input_order[:-1]):
            if watched not in {input_widget, input_widget.lineEdit()}:
                continue
            next_input = self._parameter_input_order[index + 1]
            next_input.setFocus(Qt.FocusReason.TabFocusReason)
            next_input.lineEdit().selectAll()
            return True
        return False

    def settings(self) -> MeasurementOptimizationSettings:
        return MeasurementOptimizationSettings(
            pre_roll=self._parameter_inputs["pre_roll"].value(),
            post_roll=self._parameter_inputs["post_roll"].value(),
            round_trip_latency=self._parameter_inputs["round_trip_latency"].value(),
            preset_wait=self._parameter_inputs["preset_wait"].value(),
            snapshot_wait=self._parameter_inputs["snapshot_wait"].value(),
            measurement_wait=self._parameter_inputs["measurement_wait"].value(),
            stability_runs=self.stability_runs.value(),
            termination_tolerance=self.termination_tolerance.value(),
            stability_tolerance=self.stability_tolerance.value(),
            pinned_parameters=tuple(
                parameter.name
                for parameter in TIMING_PARAMETERS
                if self._parameter_pins[parameter.name].isChecked()
            ),
        )


class MeasurementOptimizationDialog(QDialog):
    cancelled = Signal()
    applied = Signal(str)
    play_recorded_output_changed = Signal(bool)

    def __init__(
        self,
        settings: MeasurementOptimizationSettings | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._finished = False
        self.setWindowTitle("Determine optimal parameters")
        self.resize(640, 520)
        layout = QVBoxLayout(self)
        toolbar = QToolBar("Measurement", self)
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(TOOLBAR_ICON_SIZE, TOOLBAR_ICON_SIZE))
        self._speaker_icon = _speaker_icon(enabled=True)
        self._speaker_off_icon = _speaker_icon(enabled=False)
        self.play_recorded_output_button = QToolButton(self)
        self.play_recorded_output_button.setIcon(self._speaker_off_icon)
        self.play_recorded_output_button.setCheckable(True)
        self.play_recorded_output_button.setAutoRaise(True)
        self.play_recorded_output_button.setIconSize(toolbar.iconSize())
        button_size = toolbar.iconSize().width() + 14
        self.play_recorded_output_button.setFixedSize(button_size, button_size)
        self.play_recorded_output_button.setToolTip(
            "Play measured processor output through the computer speakers after each recording."
        )
        self.play_recorded_output_button.toggled.connect(self._playback_toggle_changed)
        self.play_recorded_output_button.toggled.connect(self.play_recorded_output_changed)
        toolbar.addWidget(self.play_recorded_output_button)
        layout.addWidget(toolbar)
        self.status = QLabel("Starting parameter study...")
        self.status.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Parameter", "Value", "Status", "Latest stats"])
        self.table.verticalHeader().hide()
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(3, 900)
        layout.addWidget(self.table)
        self.runtime_notice = QLabel(
            _optimization_duration_estimate(settings)
            if settings is not None
            else "Parameter optimization is running and can take some time. Actual duration "
            "depends on the parameters and can be shorter."
        )
        self.runtime_notice.setWordWrap(True)
        self.runtime_notice.setTextFormat(Qt.TextFormat.RichText)
        self.runtime_notice.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.runtime_notice.setStyleSheet(
            "QLabel {"
            "background: #eff6ff;"
            "border: 1px solid #3b82f6;"
            "border-radius: 6px;"
            "padding: 10px;"
            "color: #1d4ed8;"
            "}"
        )
        layout.addWidget(self.runtime_notice)
        self.info = QLabel("Apply the optimized timing values or copy the TOML snippet.")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        self.result = QTextEdit()
        self.result.setReadOnly(False)
        self.result.setAcceptRichText(False)
        self.result.setPlaceholderText("Optimized TOML values will appear here.")
        layout.addWidget(self.result)
        buttons = QDialogButtonBox()
        self.action_button = buttons.addButton(
            "Abort",
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        self.cancel_button = self.action_button
        self.apply_button = buttons.addButton(
            "Apply",
            QDialogButtonBox.ButtonRole.ApplyRole,
        )
        self.apply_button.setEnabled(False)
        self.action_button.clicked.connect(self._request_action)
        self.apply_button.clicked.connect(self._apply_result)
        layout.addWidget(buttons)

    def set_play_recorded_output(self, checked: bool) -> None:
        self.play_recorded_output_button.setChecked(checked)

    def _playback_toggle_changed(self, checked: bool) -> None:
        self.play_recorded_output_button.setIcon(
            self._speaker_icon if checked else self._speaker_off_icon
        )

    def update_progress(self, event: OptimizationProgress) -> None:
        self.set_status(event.message)
        for result in event.results:
            self._set_result_row(
                result.parameter.label,
                f"{result.value:.6g}",
                "Stable" if result.stable else "Unstable at optimization start",
                _statistics_text(result.statistics),
            )
        if event.parameter is not None:
            status = "Scanning"
            if event.stable is not None:
                status = "Stable" if event.stable else "Unstable"
            value = "" if event.candidate is None else f"{event.candidate:.6g}"
            self._set_result_row(
                _parameter_label(event.parameter),
                value,
                status,
                _statistics_text(event.statistics),
            )
        if event.result_toml is not None:
            self.set_result(event.result_toml)

    def set_result(self, toml_text: str) -> None:
        self.result.setPlainText(toml_text)
        self.apply_button.setEnabled(bool(toml_text.strip()))
        self.set_status("Parameter study completed.")
        self.set_finished()

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def set_finished(self) -> None:
        self._finished = True
        self.action_button.setText("Close")
        self.action_button.setEnabled(True)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._finished:
            if self._confirm_close():
                super().closeEvent(event)
                return
        elif self._confirm_abort():
            self._abort()
            event.accept()
            return
        event.ignore()

    def _request_action(self) -> None:
        if self._finished:
            self.close()
        elif self._confirm_abort():
            self._abort()

    def _apply_result(self) -> None:
        self.applied.emit(self.result.toPlainText())

    def _abort(self) -> None:
        self.action_button.setEnabled(False)
        self.set_status("Cancelling parameter study...")
        self.cancelled.emit()
        self.accept()

    def _confirm_abort(self) -> bool:
        answer = QMessageBox.question(
            self,
            "Abort parameter study",
            "A parameter optimization is currently running. Do you want to abort it?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _confirm_close(self) -> bool:
        answer = QMessageBox.question(
            self,
            "Close parameter study",
            "Do you really want to close the parameter optimization window?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _set_result_row(self, parameter: str, value: str, status: str, statistics: str) -> None:
        row = self._row_for_parameter(parameter)
        for column, text in enumerate((parameter, value, status, statistics)):
            item = self.table.item(row, column)
            if item is None:
                item = QTableWidgetItem()
                self.table.setItem(row, column, item)
            item.setText(text)

    def _row_for_parameter(self, parameter: str) -> int:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.text() == parameter:
                return row
        row = self.table.rowCount()
        self.table.insertRow(row)
        return row


def _parameter_label(name: str) -> str:
    labels = {
        "analysis_window": "Analysis window",
        "analysis_interval": "Analysis interval",
        "pre_roll": "Pre-roll",
        "post_roll": "Post-roll",
        "round_trip_latency": "Round-trip latency",
        "preset_wait": "Preset wait",
        "snapshot_wait": "Snapshot wait",
        "measurement_wait": "Measurement wait",
    }
    return labels.get(name, name)


def _statistics_text(statistics: StabilityStatistics | None) -> str:
    if statistics is None:
        return ""
    return (
        f"tol {statistics.tolerance_percent:.3g}%; "
        f"S1 LUFS mean {statistics.snapshot1_lufs_mean:.3f}, "
        f"std {statistics.snapshot1_lufs_std:.4f}, "
        f"maxdev {statistics.snapshot1_lufs_max_deviation:.4f} <= "
        f"{statistics.snapshot1_lufs_tolerance:.4f}; "
        f"S1 crest mean {statistics.snapshot1_crest_mean:.3f}, "
        f"std {statistics.snapshot1_crest_std:.4f}, "
        f"maxdev {statistics.snapshot1_crest_max_deviation:.4f} <= "
        f"{statistics.snapshot1_crest_tolerance:.4f}; "
        f"S2 LUFS mean {statistics.snapshot2_lufs_mean:.3f}, "
        f"std {statistics.snapshot2_lufs_std:.4f}, "
        f"maxdev {statistics.snapshot2_lufs_max_deviation:.4f} <= "
        f"{statistics.snapshot2_lufs_tolerance:.4f}; "
        f"S2 crest mean {statistics.snapshot2_crest_mean:.3f}, "
        f"std {statistics.snapshot2_crest_std:.4f}, "
        f"maxdev {statistics.snapshot2_crest_max_deviation:.4f} <= "
        f"{statistics.snapshot2_crest_tolerance:.4f}"
    )


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


def _format_adjustment(value: float) -> str:
    return "0" if value == 0 else f"{value:+g}"


def _normalize_snapshot_output_levels(levels: object) -> tuple[tuple[float, ...], ...]:
    if not isinstance(levels, (list, tuple)):
        return ()

    normalized: list[tuple[float, ...]] = []
    for snapshot_levels in levels:
        if not isinstance(snapshot_levels, (list, tuple)):
            normalized.append(())
            continue
        values: list[float] = []
        for level in snapshot_levels:
            if isinstance(level, (int, float)) and not isinstance(level, bool):
                values.append(float(level))
        normalized.append(tuple(values))
    return tuple(normalized)


def _format_snapshot_output_levels(
    levels: tuple[tuple[float, ...], ...],
    snapshot_index: int,
) -> str:
    if snapshot_index >= len(levels):
        return ""
    return ", ".join(f"{level:.1f}" for level in levels[snapshot_index])


def _snapshot_tooltip(is_solo: bool, is_ignored: bool) -> str:
    if is_solo and is_ignored:
        return "Solo snapshot; skipped during normalization"
    if is_solo:
        return "Solo snapshot"
    if is_ignored:
        return "Skipped during normalization"
    return ""


def _bad_lufs_adjustment_display(
    detail: str | None,
    *,
    adjustment: float | None = None,
) -> tuple[str, str]:
    bad_output_gain = _bad_lufs_output_gain(detail)
    if bad_output_gain is None:
        return (
            "Measurement failed ⚠️",
            "This snapshot is missing a usable LUFS or crest-factor measurement, so "
            "MatchPatch cannot calculate a safe Line 6 Helix output block level adjustment.",
        )
    if adjustment is None:
        return (
            "Measurement failed ⚠️",
            f"Resulting output block level would be {bad_output_gain:g} dB, outside the "
            "Line 6 Helix supported range of -120.0 to +20.0 dB, but the current "
            "output block level is unavailable in the table so MatchPatch cannot "
            "display the corresponding adjustment.",
        )

    display = f"{_format_adjustment(adjustment)} ⚠️"
    return (
        display,
        f"Resulting output block level would be {bad_output_gain:g} dB, outside the "
        "Line 6 Helix supported range of -120.0 to +20.0 dB. This usually means the "
        "measurement recorded silence or produced an unusable LUFS value.",
    )


def _bad_lufs_output_gain(detail: str | None) -> float | None:
    if not detail:
        return None
    match = re.search(r"Implausible output gain (?P<value>[+-]?\d+(?:\.\d+)?) dB", detail)
    if match is None:
        return None
    value = float(match["value"])
    return value if math.isfinite(value) else None


def _bad_lufs_adjustment(detail: str | None, current_output_levels: str) -> float | None:
    bad_output_gain = _bad_lufs_output_gain(detail)
    if bad_output_gain is None:
        return None
    levels = _parse_output_level_display_text(current_output_levels)
    if len(levels) != 1:
        return None
    return round(bad_output_gain - levels[0], 1)


def _parse_output_level_display_text(text: str) -> tuple[float, ...]:
    values = []
    for part in text.split(","):
        value = part.strip()
        if not value:
            continue
        try:
            parsed = float(value)
        except ValueError:
            continue
        if math.isfinite(parsed):
            values.append(parsed)
    return tuple(values)


def _custom_adjustment_label_text(text: str) -> str:
    match = re.fullmatch(r"(?P<display>.*) (?P<custom>\([^)]+\))", text)
    if match is None:
        return escape(text)
    return (
        f"{escape(match['display'])} "
        f"<span style='color: {CUSTOM_ADJUSTMENT_COLOR};'>{escape(match['custom'])}</span>"
    )


def _parse_adjustment_display_text(text: str) -> float:
    parts = text.strip().split(" ", 1)
    value = float(parts[0])
    if len(parts) == 1:
        return value

    custom_text = parts[1].strip()
    if custom_text.startswith("(") and custom_text.endswith(")"):
        return value + float(custom_text[1:-1])
    return value


def _interpolate_color(start: QColor, end: QColor, fraction: float) -> QColor:
    return QColor(
        round(start.red() + (end.red() - start.red()) * fraction),
        round(start.green() + (end.green() - start.green()) * fraction),
        round(start.blue() + (end.blue() - start.blue()) * fraction),
    )


def _path_row(field: QLineEdit, *buttons: QPushButton) -> QWidget:
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(field)
    for button in buttons:
        layout.addWidget(button)
    return widget


def _append_optional_argument(argv: list[str], name: str, value: object) -> None:
    text = "" if value is None else str(value).strip()
    if text and text != "None":
        argv.extend([name, text])


def _nested_config_value(config: dict[str, Any], path: tuple[str, ...]) -> object | None:
    value: object = config
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _parse_config_channel_mapping(value: object) -> tuple[int, int]:
    if isinstance(value, str):
        parsed = [int(item.strip()) for item in value.split(",") if item.strip()]
    elif isinstance(value, (list, tuple)):
        parsed = [item for item in value if isinstance(item, int)]
    else:
        raise ValueError("Channel mapping must contain two positive IDs")
    if len(parsed) != 2:
        raise ValueError("Channel mapping must contain two positive IDs")
    return parsed[0], parsed[1]


def _label(text: str, tooltip: str) -> QLabel:
    label = QLabel(text)
    label.setToolTip(tooltip)
    return label
