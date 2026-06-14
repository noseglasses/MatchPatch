from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication, QWidget

from matchpatch.diagnostics import DiagnosticCheck
from matchpatch.gui.hardware_checks import (
    HardwareCheckOverlay,
    backend_check_enabled,
    backend_check_required,
    completed_log_entries,
    failure_presentation,
)
from matchpatch.normalize import DEFAULT_REFERENCE_DI, DEFAULT_WINDOWS_PYTHON
from matchpatch.workflow import NormalizationRequest


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _request(**kwargs) -> NormalizationRequest:
    values = dict(
        device="helix",
        input_path=Path("input.hls"),
        backend="hardware",
        windows_python=str(DEFAULT_WINDOWS_PYTHON),
        reference_di=DEFAULT_REFERENCE_DI,
        automation=False,
    )
    values.update(kwargs)
    return NormalizationRequest(**values)


def test_backend_check_enabled_ignores_offscreen_qt(monkeypatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    assert not backend_check_enabled()

    monkeypatch.setenv("QT_QPA_PLATFORM", "xcb")
    assert backend_check_enabled()


def test_backend_check_required_matrix() -> None:
    request = _request(backend="hardware")

    assert backend_check_required(request, available_backend=None, check_enabled=True)
    assert not backend_check_required(request, available_backend="hardware", check_enabled=True)
    assert not backend_check_required(request, available_backend=None, check_enabled=False)
    assert not backend_check_required(
        _request(backend="loopback"),
        available_backend=None,
        check_enabled=True,
    )


def test_completed_log_entries_include_warnings_and_pass_details() -> None:
    entries = completed_log_entries(
        [
            DiagnosticCheck("audio_device", "pass", "Audio device resolved", "Line 6"),
            DiagnosticCheck("midi_output", "warning", "MIDI output missing", "No MIDI"),
        ]
    )

    assert entries == (
        ("Backend availability check completed", "success"),
        ("Hardware check detail: Line 6", "info"),
        ("Hardware check warning: MIDI output missing", "warning"),
        ("Hardware check detail: No MIDI", "info"),
    )


def test_failure_presentation_formats_failed_checks_and_selected_values() -> None:
    presentation = failure_presentation(
        request=_request(
            audio_device="Line 6 Helix",
            sample_rate=48000,
            input_mapping="1,2",
            output_mapping="3,4",
            steering_output="Helix MIDI",
        ),
        checks=[
            DiagnosticCheck(
                "audio_device",
                "fail",
                "No audio device matched",
                "audio_device=Line 6 Helix",
            )
        ],
        detail="fallback",
    )

    assert "No suitable device connected" in presentation.popup_message
    assert "No audio device matched" in presentation.popup_message
    assert "audio_device=Line 6 Helix" in presentation.popup_message
    assert "Preflight check" in presentation.popup_message
    assert ("Hardware check failed: No audio device matched", "error") in presentation.log_entries
    assert any(
        message.startswith("Hardware check selected values:")
        and "backend=hardware" in message
        and "sample_rate=48000" in message
        and level == "info"
        for message, level in presentation.log_entries
    )


def test_failure_presentation_keeps_string_fallback_error() -> None:
    presentation = failure_presentation(
        request=_request(),
        checks=[],
        detail="legacy failure",
    )

    assert "legacy failure" in presentation.popup_message
    assert ("No suitable device connected. legacy failure", "error") in presentation.log_entries


def test_hardware_check_overlay_positions_over_target(app) -> None:
    parent = QWidget()
    target = QWidget(parent)
    target.setGeometry(QRect(10, 20, 300, 200))
    overlay = HardwareCheckOverlay(parent)
    parent.show()

    overlay.show_over(target)
    app.processEvents()

    assert overlay.isVisible()
    assert overlay.geometry() == target.geometry()
    parent.close()
