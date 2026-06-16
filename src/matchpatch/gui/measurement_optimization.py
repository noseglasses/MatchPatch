"""Measurement optimization setup and result dialogs."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import Any

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, Signal
from PySide6.QtGui import QCloseEvent, QColor, QKeyEvent, QPainter, QPaintEvent, QPalette, QPen, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from matchpatch.gui.help import HelpId
from matchpatch.gui.icons import _speaker_icon
from matchpatch.measurement_optimizer import (
    TIMING_PARAMETERS,
    OptimizationProgress,
    StabilityStatistics,
    _parameters_by_duration_impact,
)

TOOLBAR_ICON_SIZE = 20


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


def _optimization_duration_estimate_seconds(settings: MeasurementOptimizationSettings) -> float:
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

    return total_runs * settings.stability_runs * _two_snapshot_optimization_run_seconds(values)


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

    total_seconds = _optimization_duration_estimate_seconds(settings)
    parameter_count = len(optimized_parameters)
    duration = escape(_format_duration(total_seconds))
    return (
        "Parameter optimization is running and can take some time. "
        f"Worst-case estimate: up to {total_runs} bisection checks across "
        f"{parameter_count} parameters, about <strong>{duration}</strong> "
        "of measurement time from the selected start values. Actual duration depends "
        "on the parameters and can be shorter."
    )


def _measurement_optimization_fixed_settings_rows(
    settings: MeasurementOptimizationSettings,
) -> tuple[tuple[str, str], ...]:
    labels_by_name = {parameter.name: parameter.label for parameter in TIMING_PARAMETERS}
    pinned_labels = [
        labels_by_name[name] for name in settings.pinned_parameters if name in labels_by_name
    ]
    pinned_text = ", ".join(pinned_labels) if pinned_labels else "none"
    return (
        ("Stability runs", f"{settings.stability_runs:g}"),
        ("Termination tolerance", f"{settings.termination_tolerance:g}%"),
        ("Stability tolerance", f"{settings.stability_tolerance:g}%"),
        ("Pinned timing parameters", pinned_text),
    )


def _measurement_optimization_parameters_by_priority(
    settings: MeasurementOptimizationSettings,
    *,
    include_pinned: bool = True,
) -> tuple[Any, ...]:
    values = _optimization_start_values_from_settings(settings)
    parameters = tuple(
        parameter
        for parameter in TIMING_PARAMETERS
        if include_pinned or parameter.name not in settings.pinned_parameters
    )
    return _parameters_by_duration_impact(values, parameters)


def _optimization_progress_event_total(settings: MeasurementOptimizationSettings) -> int:
    values = _optimization_start_values_from_settings(settings)
    optimized_parameters = tuple(
        parameter
        for parameter in TIMING_PARAMETERS
        if parameter.name not in settings.pinned_parameters
    )
    total_events = 2  # final stability started/completed
    for parameter in optimized_parameters:
        total_events += 2  # parameter started/completed
        total_events += _max_bisection_runs(
            values[parameter.name],
            parameter.lower_bound(values),
            settings.termination_tolerance,
        )
    return max(1, total_events)


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


class MeasurementOptimizationSetupDialog(QDialog):
    PARAMETER_TOOLTIPS = {
        "pre_roll": (
            "Seconds recorded before the analyzed snapshot audio. Increase this when the "
            "start of the note or reamp signal is being clipped."
        ),
        "post_roll": (
            "Seconds recorded after the analyzed snapshot audio. Increase this when the "
            "tail of the sound is being cut off."
        ),
        "round_trip_latency": (
            "Seconds between playback and the recorded processor output. This keeps "
            "analysis aligned with the actual hardware response."
        ),
        "preset_wait": (
            "Seconds to wait after changing presets before recording. Increase this "
            "when preset changes are not fully settled."
        ),
        "snapshot_wait": (
            "Seconds to wait after changing snapshots before recording. Increase this "
            "when snapshot changes are still settling."
        ),
        "measurement_wait": (
            "Seconds to wait after starting playback before the measured part is "
            "analyzed. Increase this when the useful audio starts later."
        ),
    }
    PIN_TOOLTIP = (
        "Keep this timing value fixed. Pinned parameters are copied into the result and "
        "are not optimized or bisected."
    )
    STABILITY_RUNS_TOOLTIP = (
        "How many repeat measurements a candidate timing value must survive before it "
        "counts as stable."
    )
    TERMINATION_TOLERANCE_TOOLTIP = (
        "How close the bisection search must get before accepting the best stable value."
    )
    STABILITY_TOLERANCE_TOOLTIP = (
        "Maximum allowed measurement variation between stability runs, expressed as a "
        "percentage of the measured loudness and crest-factor values."
    )
    OPTIMIZATION_PRESET_TOOLTIP = (
        "The parameter study measures this preset on the connected device, so the "
        "matching measurement preset or setlist must already be loaded there."
    )

    def __init__(
        self,
        settings: MeasurementOptimizationSettings,
        preset_label: str,
        preset_id: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Parameter study setup")
        self.setProperty("help_id", HelpId.OPTIMIZE_TIMING)
        self.resize(520, 360)
        self._parameter_inputs: dict[str, QDoubleSpinBox] = {}
        self._parameter_labels: dict[str, QLabel] = {}
        self._parameter_pins: dict[str, QCheckBox] = {}
        self._parameter_order = _measurement_optimization_parameters_by_priority(settings)
        self._parameter_input_order: list[QDoubleSpinBox] = []

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        for parameter in self._parameter_order:
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
            tooltip = self.PARAMETER_TOOLTIPS[parameter.name]
            row_widget.setToolTip(tooltip)
            input_widget.setToolTip(tooltip)
            input_widget.lineEdit().setToolTip(tooltip)
            parameter_label = QLabel(parameter.label)
            parameter_label.setToolTip(tooltip)
            pin_widget.setToolTip(self.PIN_TOOLTIP)
            row_layout.addWidget(input_widget)
            row_layout.addWidget(pin_widget)
            form.addRow(parameter_label, row_widget)
            self._parameter_inputs[parameter.name] = input_widget
            self._parameter_labels[parameter.name] = parameter_label
            self._parameter_input_order.append(input_widget)
            self._parameter_pins[parameter.name] = pin_widget

        self.stability_runs = QSpinBox()
        self.stability_runs.setRange(2, 50)
        self.stability_runs.setValue(settings.stability_runs)
        self.stability_runs.setToolTip(self.STABILITY_RUNS_TOOLTIP)
        self.stability_runs.lineEdit().setToolTip(self.STABILITY_RUNS_TOOLTIP)
        self._ignore_return_key_for_spin_box(self.stability_runs)
        self.stability_runs_label = QLabel("Stability runs")
        self.stability_runs_label.setToolTip(self.STABILITY_RUNS_TOOLTIP)
        form.addRow(self.stability_runs_label, self.stability_runs)

        self.termination_tolerance = QDoubleSpinBox()
        self.termination_tolerance.setRange(0.1, 100.0)
        self.termination_tolerance.setDecimals(1)
        self.termination_tolerance.setSuffix(" %")
        self.termination_tolerance.setValue(settings.termination_tolerance)
        self.termination_tolerance.setToolTip(self.TERMINATION_TOLERANCE_TOOLTIP)
        self.termination_tolerance.lineEdit().setToolTip(self.TERMINATION_TOLERANCE_TOOLTIP)
        self._ignore_return_key_for_spin_box(self.termination_tolerance)
        self.termination_tolerance_label = QLabel("Termination tolerance")
        self.termination_tolerance_label.setToolTip(self.TERMINATION_TOLERANCE_TOOLTIP)
        form.addRow(self.termination_tolerance_label, self.termination_tolerance)

        self.stability_tolerance = QDoubleSpinBox()
        self.stability_tolerance.setRange(0.0, 100.0)
        self.stability_tolerance.setDecimals(3)
        self.stability_tolerance.setSuffix(" %")
        self.stability_tolerance.setValue(settings.stability_tolerance)
        self.stability_tolerance.setToolTip(self.STABILITY_TOLERANCE_TOOLTIP)
        self.stability_tolerance.lineEdit().setToolTip(self.STABILITY_TOLERANCE_TOOLTIP)
        self._ignore_return_key_for_spin_box(self.stability_tolerance)
        self.stability_tolerance_label = QLabel("Stability tolerance")
        self.stability_tolerance_label.setToolTip(self.STABILITY_TOLERANCE_TOOLTIP)
        form.addRow(self.stability_tolerance_label, self.stability_tolerance)

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
        self.optimization_preset_hint.setToolTip(self.OPTIMIZATION_PRESET_TOOLTIP)
        layout.addWidget(self.optimization_preset_hint)

        buttons = QDialogButtonBox()
        self.cancel_button = buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.cancel_button.setToolTip(
            "Close this setup window without starting the parameter study."
        )
        self.run_button = buttons.addButton(
            "Run",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self.run_button.setDefault(True)
        self.run_button.setToolTip("Start the parameter study with these settings.")
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
                for parameter in self._parameter_order
                if self._parameter_pins[parameter.name].isChecked()
            ),
        )


@dataclass
class _ConvergenceCandidate:
    value: float
    stable: bool


@dataclass
class _ConvergenceRow:
    parameter: str
    label: str
    search_low: float
    search_high: float
    low: float | None = None
    high: float | None = None
    best: float | None = None
    iteration: int = 0
    completed: bool = False
    candidates: list[_ConvergenceCandidate] | None = None

    def __post_init__(self) -> None:
        if self.candidates is None:
            self.candidates = []


class OptimizationConvergencePlot(QWidget):
    def __init__(
        self,
        settings: MeasurementOptimizationSettings | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._rows: dict[str, _ConvergenceRow] = {}
        self._row_order: dict[str, int] = {}
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if settings is not None:
            self._populate_pending_rows(settings)

    def update_progress(self, event: OptimizationProgress) -> None:
        for result in event.results:
            row = self._ensure_row(
                result.parameter.name,
                result.parameter.label,
                result.value,
                result.value,
            )
            row.best = result.value
            row.low = result.value
            row.high = result.value
            row.completed = True

        if event.parameter is not None:
            label = _parameter_label(event.parameter)
            low = event.low if event.low is not None else event.candidate
            high = event.high if event.high is not None else event.candidate
            row = self._ensure_row(event.parameter, label, low, high)
            self._update_row_range(row, low, high, event.candidate, event.best)
            row.low = low
            row.high = high
            row.best = event.best
            row.iteration = event.iteration or row.iteration
            row.completed = event.kind == "parameter_completed"
            if event.candidate is not None and event.stable is not None:
                assert row.candidates is not None
                row.candidates.append(_ConvergenceCandidate(event.candidate, event.stable))

        self._refresh_size()
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rows = self._ordered_rows()
        if not rows:
            return

        palette = self.palette()
        text_color = palette.color(QPalette.ColorRole.Text)
        muted_color = palette.color(QPalette.ColorRole.Mid)
        track_color = QColor("#d1d5db")
        interval_color = QColor("#93c5fd")
        best_color = QColor("#2563eb")
        stable_color = QColor("#16a34a")
        unstable_color = QColor("#dc2626")

        metrics = painter.fontMetrics()
        label_width = min(170, max(115, self.width() // 4))
        value_width = 90
        track_left = label_width + 14
        track_right = max(track_left + 60, self.width() - value_width - 16)
        row_height = 30
        top = 18

        for index, row in enumerate(rows):
            y = top + index * row_height
            center_y = y + row_height // 2
            label = metrics.elidedText(row.label, Qt.TextElideMode.ElideRight, label_width)
            painter.setPen(text_color)
            painter.drawText(8, center_y + metrics.ascent() // 2 - 2, label)

            painter.setPen(QPen(track_color, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(track_left, center_y, track_right, center_y)

            low = row.low
            high = row.high
            if low is not None and high is not None:
                left = self._x_for_value(row, low, track_left, track_right)
                right = self._x_for_value(row, high, track_left, track_right)
                if left > right:
                    left, right = right, left
                painter.setPen(
                    QPen(interval_color, 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
                )
                painter.drawLine(left, center_y, right, center_y)

            assert row.candidates is not None
            for candidate in row.candidates:
                x = self._x_for_value(row, candidate.value, track_left, track_right)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(stable_color if candidate.stable else unstable_color)
                painter.drawEllipse(QPoint(x, center_y), 4, 4)

            if row.best is not None:
                x = self._x_for_value(row, row.best, track_left, track_right)
                painter.setPen(QPen(best_color, 2))
                painter.drawLine(x, center_y - 9, x, center_y + 9)

            painter.setPen(muted_color)
            value = ""
            if row.best is not None:
                value = f"{row.best:.6g} s"
            elif row.low is not None and row.high is not None:
                value = f"{row.low:.6g}-{row.high:.6g} s"
            painter.drawText(track_right + 12, center_y + metrics.ascent() // 2 - 2, value)

    def _populate_pending_rows(self, settings: MeasurementOptimizationSettings) -> None:
        values = _optimization_start_values_from_settings(settings)
        ordered_parameters = _measurement_optimization_parameters_by_priority(
            settings,
            include_pinned=False,
        )
        self._row_order = {
            parameter.name: index for index, parameter in enumerate(ordered_parameters)
        }
        for parameter in ordered_parameters:
            low = parameter.lower_bound(values)
            high = values[parameter.name]
            self._rows[parameter.name] = _ConvergenceRow(
                parameter.name,
                parameter.label,
                min(low, high),
                max(low, high),
            )
        self._refresh_size()

    def _ensure_row(
        self,
        parameter: str,
        label: str,
        low: float | None,
        high: float | None,
    ) -> _ConvergenceRow:
        row = self._rows.get(parameter)
        if row is not None:
            return row
        start_low = min(value for value in (low, high, 0.0) if value is not None)
        start_high = max(value for value in (low, high, 0.0) if value is not None)
        row = _ConvergenceRow(parameter, label, start_low, start_high)
        self._rows[parameter] = row
        return row

    def _update_row_range(
        self,
        row: _ConvergenceRow,
        *values: float | None,
    ) -> None:
        numeric_values = [value for value in values if value is not None]
        if not numeric_values:
            return
        row.search_low = min(row.search_low, *numeric_values)
        row.search_high = max(row.search_high, *numeric_values)

    def _ordered_rows(self) -> list[_ConvergenceRow]:
        return sorted(
            self._rows.values(),
            key=lambda row: (self._row_order.get(row.parameter, len(self._row_order)), row.label),
        )

    def _refresh_size(self) -> None:
        height = max(120, 34 + len(self._rows) * 30)
        if self.minimumHeight() != height:
            self.setMinimumHeight(height)
            self.updateGeometry()

    @staticmethod
    def _x_for_value(
        row: _ConvergenceRow,
        value: float,
        track_left: int,
        track_right: int,
    ) -> int:
        span = row.search_high - row.search_low
        if span <= 0:
            return (track_left + track_right) // 2
        fraction = (value - row.search_low) / span
        fraction = min(1.0, max(0.0, fraction))
        return round(track_left + fraction * (track_right - track_left))


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
        self._started_at = datetime.now()
        self._predicted_duration_seconds = (
            _optimization_duration_estimate_seconds(settings) if settings is not None else None
        )
        self._progress_events_seen = 0
        self._progress_total = (
            _optimization_progress_event_total(settings) if settings is not None else 0
        )
        self.setWindowTitle("Determine optimal parameters")
        self.setProperty("help_id", HelpId.OPTIMIZE_TIMING_RESULTS)
        self.resize(960, 560)
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
        self.content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.content_splitter.setChildrenCollapsible(False)
        self.main_panel = QWidget()
        main_layout = QVBoxLayout(self.main_panel)
        main_layout.setContentsMargins(0, 0, 0, 0)
        self.side_panel = QWidget()
        side_layout = QVBoxLayout(self.side_panel)
        side_layout.setContentsMargins(0, 0, 0, 0)
        self.content_splitter.addWidget(self.main_panel)
        self.content_splitter.addWidget(self.side_panel)
        self.content_splitter.setStretchFactor(0, 3)
        self.content_splitter.setStretchFactor(1, 2)
        fixed_settings_tooltip = (
            "Study-wide settings are shown here because they are not optimized or "
            "bisected while the parameter study is running."
        )
        self.fixed_settings_panel = QGroupBox("Fixed study settings")
        self.fixed_settings_panel.setToolTip(fixed_settings_tooltip)
        fixed_settings_layout = QFormLayout(self.fixed_settings_panel)
        self.fixed_settings_values: dict[str, QLabel] = {}
        rows = (
            _measurement_optimization_fixed_settings_rows(settings)
            if settings is not None
            else (
                ("Stability runs", "unknown"),
                ("Termination tolerance", "unknown"),
                ("Stability tolerance", "unknown"),
                ("Pinned timing parameters", "unknown"),
            )
        )
        for label_text, value_text in rows:
            label = QLabel(label_text)
            value = QLabel(value_text)
            value.setWordWrap(True)
            value.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
            label.setToolTip(fixed_settings_tooltip)
            value.setToolTip(fixed_settings_tooltip)
            fixed_settings_layout.addRow(label, value)
            self.fixed_settings_values[label_text] = value
        self.status = QLabel("Starting parameter study...")
        self.status.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.status.setWordWrap(True)
        main_layout.addWidget(self.status)
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
        main_layout.addWidget(self.table)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("Starting...")
        if self._progress_total > 0:
            self.progress_bar.setRange(0, self._progress_total)
            self.progress_bar.setValue(0)
        else:
            self.progress_bar.setRange(0, 0)
        main_layout.addWidget(self.progress_bar)
        self.convergence_plot = OptimizationConvergencePlot(settings)
        main_layout.addWidget(self.convergence_plot)
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
        self._set_runtime_notice_style("#eff6ff", "#3b82f6", "#1d4ed8")
        side_layout.addWidget(self.runtime_notice)
        side_layout.addWidget(self.fixed_settings_panel)
        self.info = QLabel(
            "Apply the optimized timing values or copy the TOML snippet to your config file."
        )
        self.info.setWordWrap(True)
        side_layout.addWidget(self.info)
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(False)
        self.result_text.setAcceptRichText(False)
        self.result_text.setPlaceholderText("Optimized TOML values will appear here.")
        side_layout.addWidget(self.result_text, 1)
        layout.addWidget(self.content_splitter, 1)
        self.content_splitter.setSizes([600, 340])
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
        self._advance_progress(event)
        self.convergence_plot.update_progress(event)
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
        self.result_text.setPlainText(toml_text)
        self.apply_button.setEnabled(bool(toml_text.strip()))
        self.set_status("Parameter study completed.")
        self._set_runtime_notice_finished(success=True)
        self._complete_progress("Completed")
        self.set_finished()

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def set_finished(self) -> None:
        self._finished = True
        if self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(1)
        elif self.progress_bar.value() < self.progress_bar.maximum():
            self.progress_bar.setFormat("%p%")
        self.action_button.setText("Close")
        self.action_button.setEnabled(True)

    def set_failed(self) -> None:
        self._set_runtime_notice_finished(success=False)
        self.set_finished()

    def _set_runtime_notice_finished(self, *, success: bool) -> None:
        if success:
            title = "Parameter optimization successfully finished"
            self._set_runtime_notice_style("#f0fdf4", "#22c55e", "#166534")
        else:
            title = "Parameter optimization failed"
            self._set_runtime_notice_style("#fef2f2", "#ef4444", "#991b1b")
        actual_seconds = (datetime.now() - self._started_at).total_seconds()
        actual_duration = escape(_format_duration(actual_seconds))
        predicted_duration = (
            escape(_format_duration(self._predicted_duration_seconds))
            if self._predicted_duration_seconds is not None
            else "unknown"
        )
        self.runtime_notice.setText(
            f"<strong>{title}</strong><br>"
            f"Actual duration: {actual_duration}<br>"
            f"Predicted duration: {predicted_duration}"
        )

    def _set_runtime_notice_style(
        self,
        background: str,
        border: str,
        text: str,
    ) -> None:
        self.runtime_notice.setStyleSheet(
            "QLabel {"
            f"background: {background};"
            f"border: 1px solid {border};"
            "border-radius: 6px;"
            "padding: 10px;"
            f"color: {text};"
            "}"
        )

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
        self.applied.emit(self.result_text.toPlainText())

    def _abort(self) -> None:
        self.action_button.setEnabled(False)
        self.set_status("Cancelling parameter study...")
        self.progress_bar.setFormat("Cancelling...")
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

    def _advance_progress(self, event: OptimizationProgress) -> None:
        if self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 1)
        self._progress_events_seen += 1
        maximum = max(1, self.progress_bar.maximum())
        self.progress_bar.setValue(min(maximum, self._progress_events_seen))
        if event.result_toml is None:
            self.progress_bar.setFormat("%p%")

    def _complete_progress(self, text: str) -> None:
        if self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(self.progress_bar.maximum())
        self.progress_bar.setFormat(text)


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
