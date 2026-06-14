"""Hardware-check decisions and presentation helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from matchpatch.diagnostics import DiagnosticCheck, summarize_failed_checks
from matchpatch.gui import diagnostics_panel as gui_diagnostics
from matchpatch.workflow import NormalizationRequest

_format_hardware_check_request_details = gui_diagnostics.format_hardware_check_request_details
_hardware_check_failure_details = gui_diagnostics.hardware_check_failure_details


@dataclass(frozen=True)
class HardwareCheckFailurePresentation:
    popup_message: str
    log_entries: tuple[tuple[str, str], ...]


class HardwareCheckOverlay(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("hardwareCheckOverlay")
        self.setAutoFillBackground(True)
        self.setStyleSheet(
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
        self.hide()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.addStretch()

        panel = QWidget(self)
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

    def show_over(self, target: QWidget) -> None:
        self.setGeometry(target.geometry())
        self.show()
        self.raise_()


def backend_check_enabled() -> bool:
    return os.getenv("QT_QPA_PLATFORM", "").lower() != "offscreen"


def backend_check_required(
    request: NormalizationRequest,
    *,
    available_backend: str | None,
    check_enabled: bool,
) -> bool:
    return check_enabled and request.backend == "hardware" and available_backend != request.backend


def completed_log_entries(checks: Sequence[DiagnosticCheck]) -> tuple[tuple[str, str], ...]:
    entries: list[tuple[str, str]] = [("Backend availability check completed", "success")]
    for check in checks:
        if check.status == "warning":
            entries.append((f"Hardware check warning: {check.summary}", "warning"))
            if check.detail:
                entries.append((f"Hardware check detail: {check.detail}", "info"))
        elif check.status == "pass" and check.detail:
            entries.append((f"Hardware check detail: {check.detail}", "info"))
    return tuple(entries)


def failure_presentation(
    *,
    request: NormalizationRequest | None,
    checks: Sequence[DiagnosticCheck],
    detail: str,
) -> HardwareCheckFailurePresentation:
    message = "No suitable device connected."
    detail = detail.strip()
    selected_values = _format_hardware_check_request_details(request)
    log_entries: list[tuple[str, str]] = []
    if checks:
        failed_checks = [check for check in checks if check.status == "fail"]
        for check in failed_checks:
            log_entries.append((f"Hardware check failed: {check.summary}", "error"))
            if check.detail:
                log_entries.append((f"Hardware check detail: {check.detail}", "info"))
        for check in checks:
            if check.status == "warning":
                log_entries.append((f"Hardware check warning: {check.summary}", "warning"))
                if check.detail:
                    log_entries.append((f"Hardware check detail: {check.detail}", "info"))
        if selected_values:
            log_entries.append((f"Hardware check selected values: {selected_values}", "info"))
        summary = summarize_failed_checks(checks)
    else:
        log_entries.append((f"{message} {detail}".strip(), "error"))
        if selected_values:
            log_entries.append((f"Hardware check selected values: {selected_values}", "info"))
        summary = detail

    popup_message = f"{message}\n\nConnect a compatible audio processor and try again."
    if summary:
        popup_message = f"{popup_message}\n\n{summary}"
    detail_lines = _hardware_check_failure_details(checks, detail)
    if detail_lines:
        popup_message = f"{popup_message}\n\nDetails:\n{detail_lines}"
    popup_message = (
        f"{popup_message}\n\nRun Preflight check or export a diagnostic bundle "
        "for more troubleshooting context."
    )
    return HardwareCheckFailurePresentation(
        popup_message=popup_message,
        log_entries=tuple(log_entries),
    )


__all__ = [
    "HardwareCheckFailurePresentation",
    "HardwareCheckOverlay",
    "backend_check_enabled",
    "backend_check_required",
    "completed_log_entries",
    "failure_presentation",
]
