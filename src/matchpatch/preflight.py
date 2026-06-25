"""Preflight checks for validating setup before a measurement run."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from matchpatch.custom_adjustments import load_custom_adjustments_file
from matchpatch.devices import get_device_profile
from matchpatch.devices.base import DeviceProfile, DiagnosticsContext, PatchFileHandler
from matchpatch.diagnostics import DiagnosticCheck, effective_config_from_request
from matchpatch.normalize import (
    collect_hardware_diagnostics as collect_platform_hardware_diagnostics,
)
from matchpatch.workflow import PROJECT_DIR, NormalizationRequest

ProfileProvider = Callable[[str], DeviceProfile]
HardwareDiagnosticCollector = Callable[[NormalizationRequest], list[DiagnosticCheck]]


def run_preflight_checks(
    request: NormalizationRequest,
    *,
    get_profile: ProfileProvider = get_device_profile,
    collect_hardware_diagnostics: HardwareDiagnosticCollector | None = None,
) -> list[DiagnosticCheck]:
    """Validate likely failure points without writing measurement or output files."""

    checks: list[DiagnosticCheck] = []
    checks.append(_summarize_request_check(request))

    profile: DeviceProfile | None = None
    handler: PatchFileHandler | None = None
    try:
        profile = get_profile(request.device)
    except Exception as exc:  # noqa: BLE001
        checks.append(
            DiagnosticCheck(
                "device_profile",
                "fail",
                f"Selected device profile is unavailable: {request.device}",
                str(exc),
            )
        )
    else:
        checks.append(
            DiagnosticCheck(
                "device_profile",
                "pass",
                f"Selected device profile is available: {profile.display_name}",
            )
        )
        handler = profile.create_patch_file_handler(PROJECT_DIR)

    checks.append(_input_file_check(request.input_path))
    checks.append(_handler_input_check(handler, request.input_path))
    checks.append(_output_mode_check(handler, request))
    checks.append(_reference_di_check(request.reference_di))
    checks.append(_custom_adjustments_check(request))
    checks.append(_backend_check(request.backend, profile))
    checks.extend(_device_diagnostic_checks(request, profile, handler))
    checks.extend(
        _backend_specific_checks(
            request,
            collect_hardware_diagnostics=(
                collect_hardware_diagnostics or collect_platform_hardware_diagnostics
            ),
        )
    )
    checks.append(_preset_selection_check(request))
    checks.append(_snapshot_plan_check(request))
    return checks


def _summarize_request_check(request: NormalizationRequest) -> DiagnosticCheck:
    try:
        effective_config_from_request(request)
    except Exception as exc:  # noqa: BLE001
        return DiagnosticCheck(
            "request",
            "fail",
            "Request/configuration could not be summarized",
            str(exc),
        )
    return DiagnosticCheck(
        "request",
        "pass",
        "Request/configuration can be summarized",
        f"device={request.device}; backend={request.backend}",
    )


def _input_file_check(input_path: Path) -> DiagnosticCheck:
    if input_path.is_file():
        return DiagnosticCheck("input_file", "pass", "Input file exists", str(input_path))
    return DiagnosticCheck("input_file", "fail", f"Input file does not exist: {input_path}")


def _handler_input_check(
    handler: PatchFileHandler | None,
    input_path: Path,
) -> DiagnosticCheck:
    if handler is None:
        return DiagnosticCheck(
            "handler_input",
            "skip",
            "Input file type check skipped because the device profile is unavailable",
        )
    try:
        handler.validate_input(input_path)
    except Exception as exc:  # noqa: BLE001
        return DiagnosticCheck(
            "handler_input",
            "fail",
            "Device patch handler rejected the input file",
            str(exc),
        )
    return DiagnosticCheck("handler_input", "pass", "Device patch handler accepts the input file")


def _output_mode_check(
    handler: PatchFileHandler | None,
    request: NormalizationRequest,
) -> DiagnosticCheck:
    if request.automation:
        if request.output_path is not None:
            return DiagnosticCheck(
                "output_mode",
                "fail",
                "Automation mode must not use an explicit output path",
                str(request.output_path),
            )
        return DiagnosticCheck("output_mode", "pass", "Automation output mode is valid")

    if request.output_path is None:
        return DiagnosticCheck(
            "output_mode",
            "fail",
            "Manual output mode requires an output path",
        )
    if handler is None:
        return DiagnosticCheck(
            "output_mode",
            "skip",
            "Output path check skipped because the device profile is unavailable",
        )
    try:
        handler.validate_output(request.input_path, request.output_path)
    except Exception as exc:  # noqa: BLE001
        return DiagnosticCheck(
            "output_mode",
            "fail",
            "Device patch handler rejected the output path",
            str(exc),
        )
    return DiagnosticCheck("output_mode", "pass", "Manual output path is valid")


def _reference_di_check(reference_di: Path) -> DiagnosticCheck:
    if reference_di.is_file():
        return DiagnosticCheck("reference_di", "pass", "Reference DI exists", str(reference_di))
    return DiagnosticCheck("reference_di", "fail", f"Reference DI does not exist: {reference_di}")


def _custom_adjustments_check(request: NormalizationRequest) -> DiagnosticCheck:
    path = request.custom_adjustments_path
    if path is None:
        return DiagnosticCheck(
            "custom_adjustments",
            "skip",
            "No custom adjustments file configured",
        )
    if not path.is_file():
        return DiagnosticCheck(
            "custom_adjustments",
            "fail",
            f"Custom adjustments file does not exist: {path}",
        )
    try:
        load_custom_adjustments_file(path, request.policy.snapshot_count)
    except Exception as exc:  # noqa: BLE001
        return DiagnosticCheck(
            "custom_adjustments",
            "fail",
            "Custom adjustments file could not be parsed",
            str(exc),
        )
    return DiagnosticCheck("custom_adjustments", "pass", "Custom adjustments file parses")


def _backend_check(backend: str, profile: DeviceProfile | None) -> DiagnosticCheck:
    supported_backends = (
        profile.measurement_backends()
        if profile is not None and hasattr(profile, "measurement_backends")
        else ("hardware", "loopback", "simulated")
    )
    if backend in supported_backends:
        return DiagnosticCheck("backend", "pass", f"Backend is valid: {backend}")
    supported = ", ".join(supported_backends)
    return DiagnosticCheck(
        "backend",
        "fail",
        f"Backend must be one of {supported}: {backend}",
    )


def _device_diagnostic_checks(
    request: NormalizationRequest,
    profile: DeviceProfile | None,
    handler: PatchFileHandler | None,
) -> list[DiagnosticCheck]:
    if profile is None or handler is None:
        return []
    try:
        provider_factory = getattr(profile, "diagnostics_provider", None)
        if provider_factory is None:
            return []
        provider = provider_factory()
        if provider is None:
            return []
        context = DiagnosticsContext(
            request=request,
            profile=profile,
            handler=handler,
            resolved_settings=request.device_settings or {},
            project_dir=PROJECT_DIR,
        )
        return list(provider.run_checks(context))
    except Exception as exc:  # noqa: BLE001
        return [
            DiagnosticCheck(
                "device_diagnostics",
                "fail",
                "Device diagnostics provider failed",
                str(exc),
            )
        ]


def _backend_specific_checks(
    request: NormalizationRequest,
    *,
    collect_hardware_diagnostics: HardwareDiagnosticCollector,
) -> list[DiagnosticCheck]:
    if request.backend in {"loopback", "simulated"}:
        return [
            DiagnosticCheck(
                "hardware",
                "skip",
                f"Hardware diagnostics skipped for {request.backend} backend",
            )
        ]
    if request.backend != "hardware":
        return []
    return collect_hardware_diagnostics(request)


def _preset_selection_check(request: NormalizationRequest) -> DiagnosticCheck:
    if not request.preset_set:
        return DiagnosticCheck(
            "preset_set",
            "skip",
            "No preset selection configured; all presets are eligible",
        )
    presets = tuple(preset.strip() for preset in request.preset_set.split(",") if preset.strip())
    if not presets:
        return DiagnosticCheck("preset_set", "fail", "Preset selection is empty")
    return DiagnosticCheck(
        "preset_set",
        "pass",
        f"Preset selection includes {len(presets)} preset(s): {', '.join(presets)}",
    )


def _snapshot_plan_check(request: NormalizationRequest) -> DiagnosticCheck:
    if not request.snapshot_plan:
        return DiagnosticCheck(
            "snapshot_plan",
            "skip",
            "No per-snapshot selection configured; selected presets use all measurable snapshots",
        )
    snapshot_total = sum(len(snapshots) for _, snapshots in request.snapshot_plan)
    return DiagnosticCheck(
        "snapshot_plan",
        "pass",
        f"Per-snapshot selection includes {len(request.snapshot_plan)} preset(s) and {snapshot_total} snapshot(s)",
    )
