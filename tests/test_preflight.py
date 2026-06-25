from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from matchpatch.devices.base import DiagnosticsContext
from matchpatch.diagnostics import DiagnosticCheck
from matchpatch.preflight import run_preflight_checks
from matchpatch.workflow import NormalizationRequest


class FakeHandler:
    def __init__(
        self,
        *,
        input_error: str | None = None,
        output_error: str | None = None,
    ) -> None:
        self.input_error = input_error
        self.output_error = output_error

    def validate_input(self, input_path: Path) -> None:
        if self.input_error is not None:
            raise ValueError(self.input_error)

    def validate_output(self, input_path: Path, output_path: Path) -> None:
        if self.output_error is not None:
            raise ValueError(self.output_error)


def _profile(
    handler: FakeHandler | None = None,
    *,
    backends: tuple[str, ...] = ("hardware", "loopback", "simulated"),
    diagnostics_provider: object | None = None,
) -> SimpleNamespace:
    handler = handler or FakeHandler()
    return SimpleNamespace(
        display_name="Fake Device",
        create_patch_file_handler=lambda project_dir: handler,
        measurement_backends=lambda: backends,
        diagnostics_provider=lambda: diagnostics_provider,
    )


def _request(tmp_path: Path, **kwargs: object) -> NormalizationRequest:
    input_path = tmp_path / "input.hls"
    reference_di = tmp_path / "reference.wav"
    input_path.write_text("{}", encoding="utf-8")
    reference_di.write_bytes(b"RIFF")
    values = dict(
        device="fake",
        input_path=input_path,
        backend="loopback",
        windows_python="python.exe",
        reference_di=reference_di,
        automation=True,
    )
    values.update(kwargs)
    return NormalizationRequest(**values)


def _statuses(checks: list[DiagnosticCheck]) -> dict[str, str]:
    return {check.name: check.status for check in checks}


class RecordingDiagnosticsProvider:
    def __init__(self) -> None:
        self.context: DiagnosticsContext | None = None

    def run_checks(self, context: DiagnosticsContext) -> list[DiagnosticCheck]:
        self.context = context
        return [
            DiagnosticCheck("device_storage", "pass", "Storage is writable"),
            DiagnosticCheck("device_firmware", "warning", "Firmware is unverified"),
            DiagnosticCheck("device_license", "fail", "License is missing"),
        ]


class FailingDiagnosticsProvider:
    def run_checks(self, context: DiagnosticsContext) -> list[DiagnosticCheck]:
        raise RuntimeError("diagnostic transport unavailable")


def test_loopback_preflight_skips_hardware(tmp_path: Path) -> None:
    checks = run_preflight_checks(_request(tmp_path), get_profile=lambda device: _profile())

    hardware = next(check for check in checks if check.name == "hardware")

    assert hardware.status == "skip"
    assert "loopback" in hardware.summary


def test_hardware_preflight_uses_platform_collector_by_default(
    tmp_path: Path,
    monkeypatch,
) -> None:
    expected = [DiagnosticCheck("audio_device", "pass", "Native hardware ready")]
    monkeypatch.setattr(
        "matchpatch.preflight.collect_platform_hardware_diagnostics",
        lambda request: expected,
    )

    checks = run_preflight_checks(
        _request(tmp_path, backend="hardware"),
        get_profile=lambda device: _profile(),
    )

    assert expected[0] in checks


def test_preflight_validates_backend_against_selected_profile(tmp_path: Path) -> None:
    checks = run_preflight_checks(
        _request(tmp_path, backend="offline"),
        get_profile=lambda device: _profile(backends=("offline",)),
    )

    backend = next(check for check in checks if check.name == "backend")
    assert backend.status == "pass"
    assert backend.summary == "Backend is valid: offline"

    checks = run_preflight_checks(
        _request(tmp_path, backend="hardware"),
        get_profile=lambda device: _profile(backends=("offline",)),
    )

    backend = next(check for check in checks if check.name == "backend")
    assert backend.status == "fail"
    assert backend.summary == "Backend must be one of offline: hardware"


def test_missing_input_returns_failed_check(tmp_path: Path) -> None:
    request = _request(tmp_path, input_path=tmp_path / "missing.hls")

    checks = run_preflight_checks(request, get_profile=lambda device: _profile())

    assert _statuses(checks)["input_file"] == "fail"


def test_invalid_handler_input_returns_failed_check(tmp_path: Path) -> None:
    checks = run_preflight_checks(
        _request(tmp_path),
        get_profile=lambda device: _profile(FakeHandler(input_error="bad extension")),
    )

    check = next(check for check in checks if check.name == "handler_input")
    assert check.status == "fail"
    assert check.detail == "bad extension"


def test_missing_reference_di_returns_failed_check(tmp_path: Path) -> None:
    request = _request(tmp_path, reference_di=tmp_path / "missing.wav")

    checks = run_preflight_checks(request, get_profile=lambda device: _profile())

    assert _statuses(checks)["reference_di"] == "fail"


def test_custom_adjustment_parse_failure_returns_failed_check(tmp_path: Path) -> None:
    custom_adjustments = tmp_path / "custom.csv"
    custom_adjustments.write_text("01A,not-a-number,,,\n", encoding="utf-8")
    request = _request(tmp_path, custom_adjustments_path=custom_adjustments)

    checks = run_preflight_checks(request, get_profile=lambda device: _profile())

    check = next(check for check in checks if check.name == "custom_adjustments")
    assert check.status == "fail"
    assert "not a floating point number" in check.detail


def test_hardware_backend_includes_windows_checks(tmp_path: Path) -> None:
    hardware_checks = [
        DiagnosticCheck("windows_audio", "pass", "Audio device resolved"),
        DiagnosticCheck("windows_midi", "warning", "MIDI output ambiguous"),
    ]

    checks = run_preflight_checks(
        _request(tmp_path, backend="hardware"),
        get_profile=lambda device: _profile(),
        collect_hardware_diagnostics=lambda request: hardware_checks,
    )

    assert [check for check in checks if check.name.startswith("windows_")] == hardware_checks


def test_device_diagnostics_provider_contributes_checks(tmp_path: Path) -> None:
    provider = RecordingDiagnosticsProvider()
    request = _request(
        tmp_path,
        backend="hardware",
        device_settings={"sample_rate": 48000},
    )
    hardware_checks = [DiagnosticCheck("windows_audio", "pass", "Audio device resolved")]

    checks = run_preflight_checks(
        request,
        get_profile=lambda device: _profile(diagnostics_provider=provider),
        collect_hardware_diagnostics=lambda request: hardware_checks,
    )

    assert provider.context is not None
    assert provider.context.request is request
    assert provider.context.handler is not None
    assert provider.context.resolved_settings == {"sample_rate": 48000}
    assert [check.name for check in checks[8:12]] == [
        "device_storage",
        "device_firmware",
        "device_license",
        "windows_audio",
    ]
    assert _statuses(checks)["device_storage"] == "pass"
    assert _statuses(checks)["device_firmware"] == "warning"
    assert _statuses(checks)["device_license"] == "fail"


def test_device_diagnostics_provider_exception_returns_failed_check(tmp_path: Path) -> None:
    checks = run_preflight_checks(
        _request(tmp_path),
        get_profile=lambda device: _profile(diagnostics_provider=FailingDiagnosticsProvider()),
    )

    check = next(check for check in checks if check.name == "device_diagnostics")
    assert check.status == "fail"
    assert check.summary == "Device diagnostics provider failed"
    assert check.detail == "diagnostic transport unavailable"


def test_preflight_check_ordering(tmp_path: Path) -> None:
    request = _request(
        tmp_path,
        snapshot_plan=(("01A", (1, 3)),),
        output_path=tmp_path / "output.hls",
        automation=False,
    )

    checks = run_preflight_checks(request, get_profile=lambda device: _profile())

    assert [check.name for check in checks] == [
        "request",
        "device_profile",
        "input_file",
        "handler_input",
        "output_mode",
        "reference_di",
        "custom_adjustments",
        "backend",
        "hardware",
        "preset_set",
        "snapshot_plan",
    ]
    assert checks[-2].summary == "No preset selection configured; all presets are eligible"
    assert checks[-1].summary == "Per-snapshot selection includes 1 preset(s) and 2 snapshot(s)"


def test_preflight_reports_preset_selection(tmp_path: Path) -> None:
    request = _request(tmp_path, preset_set="01A,01C")

    checks = run_preflight_checks(request, get_profile=lambda device: _profile())

    check = next(check for check in checks if check.name == "preset_set")
    assert check.status == "pass"
    assert check.summary == "Preset selection includes 2 preset(s): 01A, 01C"
