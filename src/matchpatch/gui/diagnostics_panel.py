"""Diagnostics and preflight panel helpers."""

from __future__ import annotations

from html import escape
from typing import Sequence

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyle,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from matchpatch.diagnostics import DiagnosticCheck
from matchpatch.gui.advanced_settings import (
    PresetTableSelectionContext,
    selected_candidate_rows,
    selected_patch_snapshots,
)
from matchpatch.gui.help import HelpId
from matchpatch.workflow import NormalizationRequest


class DiagnosticsPanel(QWidget):
    """Diagnostics tab content with workflow-sensitive controls."""

    copy_summary_requested = Signal()
    export_bundle_requested = Signal()
    preflight_requested = Signal()

    def __init__(self, *, log_widget: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("help_id", HelpId.TROUBLESHOOTING)
        layout = QVBoxLayout(self)

        self.privacy_panel = QGroupBox("Privacy notice")
        self.privacy_panel.setStyleSheet(
            "QGroupBox {"
            "background: #eff6ff;"
            "border: 1px solid #3b82f6;"
            "border-radius: 6px;"
            "margin-top: 0.75em;"
            "padding: 10px;"
            "color: #1d4ed8;"
            "}"
            "QGroupBox::title {"
            "subcontrol-origin: margin;"
            "left: 8px;"
            "padding: 0 4px;"
            "color: #1d4ed8;"
            "}"
            "QLabel {"
            "color: #1d4ed8;"
            "}"
        )
        privacy_layout = QVBoxLayout(self.privacy_panel)
        self.privacy_notice = QLabel(
            "Diagnostic bundles are saved locally and may include file paths, effective "
            "settings, recent GUI log lines, progress events, hardware/audio/MIDI names, "
            "and safe CSV summaries. They do not include raw audio, preset or setlist "
            "file contents, adjusted output files, or full retained CSV contents. Review "
            "the ZIP before sharing and remove anything that reveals private names, "
            "client/project folders, setlist details, or other sensitive information."
        )
        self.privacy_notice.setWordWrap(True)
        privacy_layout.addWidget(self.privacy_notice)
        layout.addWidget(self.privacy_panel)

        form = QFormLayout()
        self.export_bundle_button = QPushButton("Export diagnostic bundle")
        self.export_bundle_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
        )
        self.export_bundle_button.setToolTip(
            "Save a support bundle with effective settings, GUI logs, and safe summaries."
        )
        self.export_bundle_button.clicked.connect(self.export_bundle_requested.emit)

        self.copy_summary_button = QPushButton("Copy diagnostic summary")
        self.copy_summary_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
        )
        self.copy_summary_button.setToolTip(
            "Copy resolved settings and diagnostic context to the clipboard."
        )
        self.copy_summary_button.clicked.connect(self.copy_summary_requested.emit)

        self.preflight_button = QPushButton("Run preflight check")
        self.preflight_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation)
        )
        self.preflight_button.setToolTip(
            "Validate setup and backend availability before starting measurement."
        )
        self.preflight_button.clicked.connect(self.preflight_requested.emit)

        form.addRow(
            _label("Preflight", "Validate setup before starting measurement."),
            _button_row(self.preflight_button),
        )
        form.addRow(
            _label("Diagnostics", "Support bundle with settings, logs, and safe summaries."),
            _button_row(self.copy_summary_button, self.export_bundle_button),
        )
        layout.addLayout(form)
        layout.addWidget(log_widget)

    def set_workflow_active(self, active: bool) -> None:
        self.copy_summary_button.setEnabled(not active)
        self.export_bundle_button.setEnabled(not active)
        self.preflight_button.setEnabled(not active)

    def set_preflight_running(self, running: bool) -> None:
        self.preflight_button.setText("Running..." if running else "Run preflight check")
        self.set_workflow_active(running)

    def show_preflight_results(
        self,
        checks: Sequence[DiagnosticCheck],
        *,
        parent: QWidget | None = None,
    ) -> None:
        dialog = QDialog(parent or self)
        dialog.setWindowTitle("Preflight check")
        layout = QVBoxLayout(dialog)

        headline = QLabel(preflight_headline(checks), dialog)
        headline_font = headline.font()
        headline_font.setBold(True)
        headline.setFont(headline_font)
        layout.addWidget(headline)

        details = QTextEdit(dialog)
        details.setReadOnly(True)
        details.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        details.setHtml(format_preflight_results_html(checks))
        details.setMinimumSize(560, 280)
        layout.addWidget(details)

        hint = QLabel(
            "Use Export diagnostic bundle to save these checks with settings and recent logs.",
            dialog,
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok, dialog)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec()


def preflight_headline(checks: Sequence[DiagnosticCheck]) -> str:
    if any(check.status == "fail" for check in checks):
        return "Preflight found setup problems."
    if any(check.status == "warning" for check in checks):
        return "Preflight completed with warnings."
    return "Preflight passed."


def format_preflight_results(checks: Sequence[DiagnosticCheck]) -> str:
    lines: list[str] = []
    for check in checks:
        lines.append(
            f"{check.status.upper()} {preflight_check_display_name(check)}: {check.summary}"
        )
        if check.status in {"fail", "warning"} and check.detail:
            lines.append(f"  {check.detail}")
    return "\n".join(lines)


def preflight_check_display_name(check: DiagnosticCheck) -> str:
    display_names = {
        "preset_set": "Preset selection",
        "snapshot_plan": "Per-snapshot selection",
    }
    return display_names.get(check.name, check.name)


def format_preflight_results_html(checks: Sequence[DiagnosticCheck]) -> str:
    colors = {
        "pass": "#15803d",
        "skip": "#854d0e",
        "warning": "#a16207",
        "fail": "#dc2626",
    }
    blocks: list[str] = []
    for check in checks:
        color = colors.get(check.status, "#374151")
        status = escape(check.status.upper())
        name = escape(preflight_check_display_name(check))
        summary = escape(check.summary)
        detail = ""
        if check.status in {"fail", "warning"} and check.detail:
            detail = (
                f"<div style='margin-left: 1.5em; color: #374151;'>{escape(check.detail)}</div>"
            )
        blocks.append(
            "<div style='margin-bottom: 0.35em;'>"
            f"<span style='font-weight: 700; color: {color};'>{status}</span> "
            f"<span style='font-weight: 700;'>{name}</span>: {summary}"
            f"{detail}</div>"
        )
    return (
        "<div style='font-family: monospace; white-space: pre-wrap;'>" + "".join(blocks) + "</div>"
    )


def preflight_checks_with_preset_table_selection(
    checks: Sequence[DiagnosticCheck],
    context: PresetTableSelectionContext,
) -> list[DiagnosticCheck]:
    table_checks = preset_table_selection_preflight_checks(context)
    if not table_checks:
        return list(checks)
    replacements = {check.name: check for check in table_checks}
    merged = [replacements.get(check.name, check) for check in checks]
    existing_names = {check.name for check in merged}
    merged.extend(check for check in table_checks if check.name not in existing_names)
    return merged


def preset_table_selection_preflight_checks(
    context: PresetTableSelectionContext,
) -> list[DiagnosticCheck]:
    if not context.has_table or context.row_count == 0:
        return []

    checked_rows = set(context.checked_rows)
    visible_rows = sorted(context.visible_rows)
    has_unchecked_presets = any(row not in checked_rows for row in visible_rows)
    has_ignored_snapshots = context.has_ignored_snapshots
    comparison_snapshot_plan = context.comparison_snapshot_plan
    if comparison_snapshot_plan is not None:
        has_ignored_snapshots = True
    if not has_unchecked_presets and not has_ignored_snapshots:
        return []

    candidate_rows = selected_candidate_rows(context, has_unchecked_presets, has_ignored_snapshots)
    selected_patches, preset_snapshots = selected_patch_snapshots(
        context, candidate_rows, comparison_snapshot_plan
    )
    if not selected_patches:
        return []

    checks = [_preset_set_check(selected_patches)]
    if has_ignored_snapshots:
        checks.append(_snapshot_plan_check(selected_patches, preset_snapshots))
    return checks


def _preset_set_check(selected_patches: Sequence[str]) -> DiagnosticCheck:
    return DiagnosticCheck(
        "preset_set",
        "pass",
        (
            f"Preset selection includes {len(selected_patches)} preset(s): "
            f"{', '.join(selected_patches)}"
        ),
    )


def _snapshot_plan_check(
    selected_patches: Sequence[str],
    preset_snapshots: Sequence[tuple[str, tuple[int, ...]]],
) -> DiagnosticCheck:
    snapshot_total = sum(len(snapshots) for _patch, snapshots in preset_snapshots)
    if snapshot_total:
        return DiagnosticCheck(
            "snapshot_plan",
            "pass",
            (
                f"Per-snapshot selection includes {len(preset_snapshots)} preset(s) "
                f"and {snapshot_total} snapshot(s)"
            ),
        )
    return DiagnosticCheck(
        "snapshot_plan",
        "warning",
        (
            "Per-snapshot selection is configured but leaves no measurable "
            f"snapshots across {len(selected_patches)} selected preset(s)"
        ),
    )


def format_hardware_check_request_details(request: NormalizationRequest | None) -> str:
    if request is None:
        return ""
    values = {
        "backend": request.backend,
        "audio_device": request.audio_device,
        "sample_rate": request.sample_rate,
        "input_mapping": request.input_mapping,
        "output_mapping": request.output_mapping,
        "midi_output": request.steering_output,
    }
    return ", ".join(f"{name}={value}" for name, value in values.items() if value not in {None, ""})


def hardware_check_failure_details(
    checks: Sequence[DiagnosticCheck],
    fallback_detail: str,
) -> str:
    if not checks:
        return fallback_detail

    lines: list[str] = []
    for check in checks:
        if check.status != "fail":
            continue
        if check.detail:
            lines.append(check.detail)
    return "\n".join(lines)


def _label(text: str, tooltip: str) -> QLabel:
    label = QLabel(text)
    label.setToolTip(tooltip)
    return label


def _button_row(*buttons: QPushButton) -> QWidget:
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addStretch()
    for button in buttons:
        layout.addWidget(button)
    return widget
