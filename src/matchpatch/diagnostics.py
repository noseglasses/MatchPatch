"""Serializable diagnostic data for support and troubleshooting output."""

from __future__ import annotations

import csv
import json
import math
import os
import platform
import sys
import zipfile
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Sequence, cast

from matchpatch import __version__
from matchpatch.analysis import AnalysisOptions
from matchpatch.devices.base import NormalizationPolicy
from matchpatch.progress import ProgressEvent
from matchpatch.workflow import NormalizationRequest, NormalizationResult

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
DiagnosticStatus = Literal["pass", "warning", "fail", "skip"]


@dataclass(frozen=True)
class RuntimeInfo:
    matchpatch_version: str
    python_executable: str
    python_version: str
    platform: str
    runtime_mode: str = "python"

    @classmethod
    def current(cls, runtime_mode: str | None = None) -> RuntimeInfo:
        mode = runtime_mode or _current_runtime_mode()
        return cls(
            matchpatch_version=__version__,
            python_executable=sys.executable,
            python_version=platform.python_version(),
            platform=platform.platform(),
            runtime_mode=mode,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "matchpatch_version": self.matchpatch_version,
            "python_executable": self.python_executable,
            "python_version": self.python_version,
            "platform": self.platform,
            "runtime_mode": self.runtime_mode,
        }


@dataclass(frozen=True)
class EffectiveConfig:
    device: str
    backend: str
    input_path: str
    output_path: str | None
    diff_input_path: str | None
    reference_di: str
    custom_adjustments_path: str | None
    windows_python: str
    automation: bool
    defer_export: bool
    preset_set: str | None
    limit: int | None
    keep_temp: bool
    ignore_bad_lufs: bool
    target_lufs: float
    timeout: float | None
    audio_device: str | int | None
    sample_rate: int | None
    input_mapping: str | None
    output_mapping: str | None
    blocksize: int | None
    steering_output: str | None
    steering_channel: int | None
    preset_wait: float | None
    snapshot_wait: float | None
    measurement_wait: float | None
    pre_roll: float | None
    post_roll: float | None
    round_trip_latency: float | None
    play_recorded_output: bool
    record_device_output: bool
    playback_toggle_path: str | None
    recorded_output_dir: str | None
    snapshot_plan: tuple[tuple[str, tuple[int, ...]], ...]
    policy: dict[str, Any]
    analysis_options: dict[str, Any]

    @classmethod
    def from_request(cls, request: NormalizationRequest) -> EffectiveConfig:
        return cls(
            device=request.device,
            backend=request.backend,
            input_path=_path_text(request.input_path),
            output_path=_optional_path_text(request.output_path),
            diff_input_path=_optional_path_text(request.diff_input_path),
            reference_di=_path_text(request.reference_di),
            custom_adjustments_path=_optional_path_text(request.custom_adjustments_path),
            windows_python=request.windows_python,
            automation=request.automation,
            defer_export=request.defer_export,
            preset_set=request.preset_set,
            limit=request.limit,
            keep_temp=request.keep_temp,
            ignore_bad_lufs=request.ignore_bad_lufs,
            target_lufs=request.target_lufs,
            timeout=request.timeout,
            audio_device=request.audio_device,
            sample_rate=request.sample_rate,
            input_mapping=request.input_mapping,
            output_mapping=request.output_mapping,
            blocksize=request.blocksize,
            steering_output=request.steering_output,
            steering_channel=request.steering_channel,
            preset_wait=request.preset_wait,
            snapshot_wait=request.snapshot_wait,
            measurement_wait=request.measurement_wait,
            pre_roll=request.pre_roll,
            post_roll=request.post_roll,
            round_trip_latency=request.round_trip_latency,
            play_recorded_output=request.play_recorded_output,
            record_device_output=request.record_device_output,
            playback_toggle_path=_optional_path_text(request.playback_toggle_path),
            recorded_output_dir=_optional_path_text(request.recorded_output_dir),
            snapshot_plan=tuple(
                (patch, tuple(snapshots)) for patch, snapshots in request.snapshot_plan
            ),
            policy=normalization_policy_to_dict(request.policy),
            analysis_options=analysis_options_to_dict(request.analysis_options),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "device": self.device,
            "backend": self.backend,
            "input_path": self.input_path,
            "output_path": self.output_path,
            "diff_input_path": self.diff_input_path,
            "reference_di": self.reference_di,
            "custom_adjustments_path": self.custom_adjustments_path,
            "windows_python": self.windows_python,
            "automation": self.automation,
            "defer_export": self.defer_export,
            "preset_set": self.preset_set,
            "limit": self.limit,
            "keep_temp": self.keep_temp,
            "ignore_bad_lufs": self.ignore_bad_lufs,
            "target_lufs": self.target_lufs,
            "timeout": self.timeout,
            "audio_device": self.audio_device,
            "sample_rate": self.sample_rate,
            "input_mapping": self.input_mapping,
            "output_mapping": self.output_mapping,
            "blocksize": self.blocksize,
            "steering_output": self.steering_output,
            "steering_channel": self.steering_channel,
            "preset_wait": self.preset_wait,
            "snapshot_wait": self.snapshot_wait,
            "measurement_wait": self.measurement_wait,
            "pre_roll": self.pre_roll,
            "post_roll": self.post_roll,
            "round_trip_latency": self.round_trip_latency,
            "play_recorded_output": self.play_recorded_output,
            "record_device_output": self.record_device_output,
            "playback_toggle_path": self.playback_toggle_path,
            "recorded_output_dir": self.recorded_output_dir,
            "snapshot_plan": [
                {"patch": patch, "snapshots": list(snapshots)}
                for patch, snapshots in self.snapshot_plan
            ],
            "policy": self.policy,
            "analysis_options": self.analysis_options,
        }


@dataclass(frozen=True)
class CsvSummary:
    path: str
    exists: bool
    headers: tuple[str, ...] = ()
    row_count: int = 0
    preset_ids: tuple[str, ...] = ()
    device_patches: tuple[str, ...] = ()
    lufs_columns: tuple[str, ...] = ()
    valid_lufs_count: int = 0
    missing_lufs_count: int = 0
    bad_lufs_count: int = 0
    lufs_min: float | None = None
    lufs_max: float | None = None
    lufs_average: float | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "exists": self.exists,
            "headers": list(self.headers),
            "row_count": self.row_count,
            "preset_ids": list(self.preset_ids),
            "device_patches": list(self.device_patches),
            "lufs_columns": list(self.lufs_columns),
            "valid_lufs_count": self.valid_lufs_count,
            "missing_lufs_count": self.missing_lufs_count,
            "bad_lufs_count": self.bad_lufs_count,
            "lufs_min": self.lufs_min,
            "lufs_max": self.lufs_max,
            "lufs_average": self.lufs_average,
            "error": self.error,
        }


@dataclass(frozen=True)
class DiagnosticCheck:
    name: str
    status: DiagnosticStatus
    summary: str
    detail: str = ""


@dataclass(frozen=True)
class DiagnosticSnapshot:
    generated_at: str
    matchpatch_version: str
    python_executable: str
    python_version: str
    platform: str
    runtime_mode: str
    config_path: str | None
    request: dict[str, object]
    effective_config: dict[str, object]
    checks: list[DiagnosticCheck]
    recent_progress_events: list[dict[str, JsonValue]]
    recent_gui_log_lines: list[dict[str, str]]
    retained_csv: dict[str, object] | None = None
    result: dict[str, object] | None = None

    def to_dict(self) -> dict[str, Any]:
        return snapshot_to_dict(self)

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    def to_text(self) -> str:
        return snapshot_to_text(self)


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    status: str
    message: str
    details: dict[str, JsonValue] | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "details": self.details or {},
        }

    @classmethod
    def ok_check(
        cls,
        name: str,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> PreflightCheck:
        return cls(name, "ok", message, _json_ready_dict(details or {}))

    @classmethod
    def failed_check(
        cls,
        name: str,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> PreflightCheck:
        return cls(name, "failed", message, _json_ready_dict(details or {}))

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> PreflightCheck:
        details = data.get("details")
        return cls(
            name=str(data.get("name", "")),
            status=str(data.get("status", "")),
            message=str(data.get("message", "")),
            details=(
                _json_ready_dict(cast("Mapping[str, object]", details))
                if isinstance(details, Mapping)
                else {}
            ),
        )


def preflight_check_from_diagnostic(check: DiagnosticCheck) -> PreflightCheck:
    return PreflightCheck(
        name=check.name,
        status="ok" if check.status == "pass" else "failed",
        message=check.summary,
        details=_detail_text_to_dict(check.detail),
    )


def preflight_check_to_diagnostic(check: PreflightCheck) -> DiagnosticCheck:
    detail = ""
    if check.details:
        detail = json.dumps(check.details, sort_keys=True)
    return DiagnosticCheck(
        name=check.name,
        status="pass" if check.ok else "fail",
        summary=check.message,
        detail=detail,
    )


def _detail_text_to_dict(detail: str) -> dict[str, JsonValue]:
    if not detail:
        return {}
    parsed: dict[str, JsonValue] = {}
    for item in detail.split("; "):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        parsed[key] = _parse_detail_value(value)
    return parsed or {"detail": detail}


def _parse_detail_value(value: str) -> JsonValue:
    if value == "None":
        return None
    parsed = _parse_json_detail_value(value)
    if parsed is not None:
        return parsed
    parsed = _parse_sequence_detail_value(value)
    if parsed is not None:
        return parsed
    return _parse_numeric_detail_value(value)


def _parse_json_detail_value(value: str) -> JsonValue | None:
    if not value.startswith(("[", "{")):
        return None
    try:
        return _json_ready_value(json.loads(value))
    except json.JSONDecodeError:
        return None


def _parse_sequence_detail_value(value: str) -> list[JsonValue] | None:
    if not (
        (value.startswith("(") and value.endswith(")"))
        or (value.startswith("[") and value.endswith("]"))
    ):
        return None
    items = [item.strip() for item in value[1:-1].split(",") if item.strip()]
    return [_parse_detail_value(item) for item in items]


def _parse_numeric_detail_value(value: str) -> JsonValue:
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


@dataclass(frozen=True)
class HardwarePreflightResult:
    device: str
    backend: str
    checks: tuple[PreflightCheck, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    @property
    def failure_message(self) -> str | None:
        for check in self.checks:
            if not check.ok:
                return check.message
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "device": self.device,
            "backend": self.backend,
            "ok": self.ok,
            "checks": [check.to_dict() for check in self.checks],
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> HardwarePreflightResult:
        checks = data.get("checks")
        return cls(
            device=str(data.get("device", "")),
            backend=str(data.get("backend", "")),
            checks=tuple(
                PreflightCheck.from_dict(cast("Mapping[str, object]", item))
                for item in checks
                if isinstance(item, Mapping)
            )
            if isinstance(checks, list | tuple)
            else (),
        )

    @classmethod
    def from_diagnostic_checks(
        cls,
        device: str,
        backend: str,
        checks: Iterable[DiagnosticCheck],
    ) -> HardwarePreflightResult:
        return cls(
            device=device,
            backend=backend,
            checks=tuple(preflight_check_from_diagnostic(check) for check in checks),
        )

    @classmethod
    def from_json_payload(
        cls,
        data: object,
        *,
        device: str = "",
        backend: str = "",
    ) -> HardwarePreflightResult:
        if isinstance(data, list):
            return cls.from_diagnostic_checks(
                device,
                backend,
                (
                    diagnostic_check_from_dict(cast("Mapping[str, object]", item))
                    for item in data
                    if isinstance(item, Mapping)
                ),
            )
        if isinstance(data, Mapping):
            return cls.from_dict(cast("Mapping[str, object]", data))
        return cls(device=device, backend=backend, checks=())


def normalization_policy_to_dict(policy: NormalizationPolicy) -> dict[str, Any]:
    return {
        "snapshot_count": policy.snapshot_count,
        "solo_regex": policy.solo_regex,
        "ignore_snapshot_regex": policy.ignore_snapshot_regex,
        "ignore_preset_regex": policy.ignore_preset_regex,
        "solo_gain_bump_db": policy.solo_gain_bump_db,
        "crest_factor_reference_db": policy.crest_factor_reference_db,
        "crest_factor_correction_ratio": policy.crest_factor_correction_ratio,
        "max_crest_factor_correction_db": policy.max_crest_factor_correction_db,
        "gain_deadband_db": policy.gain_deadband_db,
    }


def analysis_options_to_dict(options: AnalysisOptions) -> dict[str, Any]:
    return {
        "window_seconds": options.window_seconds,
        "interval_seconds": options.interval_seconds,
        "minimum_valid_lufs": options.minimum_valid_lufs,
    }


def result_to_dict(result: NormalizationResult) -> dict[str, object]:
    return {
        "output_path": _optional_path_text(result.output_path),
        "temp_dir": _optional_path_text(result.temp_dir),
        "retained_csv_path": _optional_path_text(result.retained_csv_path),
    }


def request_diagnostics(request: NormalizationRequest) -> dict[str, object]:
    return {
        "device": request.device,
        "input_path": _path_text(request.input_path),
        "output_path": _optional_path_text(request.output_path),
        "diff_input_path": _optional_path_text(request.diff_input_path),
        "backend": request.backend,
        "windows_python": request.windows_python,
        "reference_di": _path_text(request.reference_di),
        "custom_adjustments_path": _optional_path_text(request.custom_adjustments_path),
        "automation": request.automation,
        "defer_export": request.defer_export,
        "preset_set": request.preset_set,
        "limit": request.limit,
        "keep_temp": request.keep_temp,
        "ignore_bad_lufs": request.ignore_bad_lufs,
        "target_lufs": request.target_lufs,
        "timeout": request.timeout,
        "audio_device": request.audio_device,
        "sample_rate": request.sample_rate,
        "input_mapping": request.input_mapping,
        "output_mapping": request.output_mapping,
        "blocksize": request.blocksize,
        "steering_output": request.steering_output,
        "steering_channel": request.steering_channel,
        "preset_wait": request.preset_wait,
        "snapshot_wait": request.snapshot_wait,
        "measurement_wait": request.measurement_wait,
        "pre_roll": request.pre_roll,
        "post_roll": request.post_roll,
        "round_trip_latency": request.round_trip_latency,
        "simulate_fail_presets": request.simulate_fail_presets,
        "play_recorded_output": request.play_recorded_output,
        "record_device_output": request.record_device_output,
        "playback_toggle_path": _optional_path_text(request.playback_toggle_path),
        "recorded_output_dir": _optional_path_text(request.recorded_output_dir),
        "snapshot_plan": [
            {"patch": patch, "snapshots": list(snapshots)}
            for patch, snapshots in request.snapshot_plan
        ],
        "policy": normalization_policy_to_dict(request.policy),
        "analysis_options": analysis_options_to_dict(request.analysis_options),
    }


def effective_config_from_request(request: NormalizationRequest) -> dict[str, object]:
    return EffectiveConfig.from_request(request).to_dict()


def diagnostic_check_to_dict(check: DiagnosticCheck) -> dict[str, str]:
    return {
        "name": check.name,
        "status": check.status,
        "summary": check.summary,
        "detail": check.detail,
    }


def diagnostic_check_from_dict(data: Mapping[str, object]) -> DiagnosticCheck:
    status = str(data.get("status", "fail"))
    if status == "ok":
        status = "pass"
    elif status == "failed":
        status = "fail"
    if status not in {"pass", "warning", "fail", "skip"}:
        status = "fail"
    detail = data.get("detail", "")
    if not detail and isinstance(data.get("details"), Mapping):
        detail = "; ".join(
            f"{key}={value}" for key, value in cast("Mapping[str, object]", data["details"]).items()
        )
    return DiagnosticCheck(
        name=str(data.get("name", "")),
        status=cast("DiagnosticStatus", status),
        summary=str(data.get("summary", data.get("message", ""))),
        detail=str(detail),
    )


def snapshot_to_dict(snapshot: DiagnosticSnapshot) -> dict[str, object]:
    return {
        "generated_at": snapshot.generated_at,
        "matchpatch_version": snapshot.matchpatch_version,
        "python_executable": snapshot.python_executable,
        "python_version": snapshot.python_version,
        "platform": snapshot.platform,
        "runtime_mode": snapshot.runtime_mode,
        "config_path": snapshot.config_path,
        "request": snapshot.request,
        "effective_config": snapshot.effective_config,
        "checks": [diagnostic_check_to_dict(check) for check in snapshot.checks],
        "recent_progress_events": list(snapshot.recent_progress_events),
        "recent_gui_log_lines": list(snapshot.recent_gui_log_lines),
        "retained_csv": snapshot.retained_csv,
        "result": snapshot.result,
        "runtime": {
            "matchpatch_version": snapshot.matchpatch_version,
            "python_executable": snapshot.python_executable,
            "python_version": snapshot.python_version,
            "platform": snapshot.platform,
            "runtime_mode": snapshot.runtime_mode,
        },
        "recent_logs": list(snapshot.recent_gui_log_lines),
        "recent_progress": list(snapshot.recent_progress_events),
    }


def snapshot_to_text(snapshot: DiagnosticSnapshot) -> str:
    lines = [
        f"MatchPatch: {snapshot.matchpatch_version}",
        f"Python: {snapshot.python_version} ({snapshot.python_executable})",
        f"Platform: {snapshot.platform}",
        f"Runtime mode: {snapshot.runtime_mode}",
    ]
    if snapshot.config_path is not None:
        lines.append(f"Config: {snapshot.config_path}")
    if snapshot.effective_config:
        config = snapshot.effective_config
        policy = config.get("policy")
        snapshot_count = policy.get("snapshot_count") if isinstance(policy, Mapping) else None
        lines.extend(
            [
                "",
                "Effective configuration:",
                f"  Device: {config.get('device')}",
                f"  Backend: {config.get('backend')}",
                f"  Input: {config.get('input_path')}",
                f"  Output: {config.get('output_path') or '(automatic/deferred)'}",
                f"  Reference DI: {config.get('reference_di')}",
                f"  Target LUFS: {config.get('target_lufs')}",
                f"  Snapshot count: {snapshot_count}",
            ]
        )
    if snapshot.checks:
        lines.append("")
        lines.append("Checks:")
        for check in snapshot.checks:
            lines.append(f"  {check.status.upper()} {check.name}: {check.summary}")
            if check.detail:
                lines.append(f"    {check.detail}")
    if snapshot.retained_csv is not None:
        csv_summary = snapshot.retained_csv
        lines.extend(
            [
                "",
                "Retained CSV:",
                f"  Path: {csv_summary.get('path')}",
                f"  Rows: {csv_summary.get('row_count') if csv_summary.get('exists') else 'missing'}",
                f"  LUFS cells: {csv_summary.get('valid_lufs_count')} valid, "
                f"{csv_summary.get('missing_lufs_count')} missing, "
                f"{csv_summary.get('bad_lufs_count')} bad",
            ]
        )
        if csv_summary.get("lufs_average") is not None:
            lines.append(
                f"  LUFS range: {csv_summary.get('lufs_min')} to {csv_summary.get('lufs_max')} "
                f"(avg {csv_summary.get('lufs_average')})"
            )
        if csv_summary.get("error") is not None:
            lines.append(f"  Error: {csv_summary.get('error')}")
    return "\n".join(lines)


def summarize_failed_checks(checks: Sequence[DiagnosticCheck] | Iterable[DiagnosticCheck]) -> str:
    summaries = [check.summary for check in checks if check.status == "fail" and check.summary]
    return "; ".join(summaries) if summaries else "Hardware check failed"


def progress_event_to_dict(event: ProgressEvent) -> dict[str, JsonValue]:
    return _json_ready_dict(asdict(event))


def summarize_csv(csv_path: Path, snapshot_count: int | None = None) -> dict[str, object]:
    return _summarize_csv_data(csv_path, snapshot_count).to_dict()


def _summarize_csv_data(csv_path: Path, snapshot_count: int | None = None) -> CsvSummary:
    path_text = _path_text(csv_path)
    if not csv_path.exists():
        return CsvSummary(path=path_text, exists=False, error="CSV file does not exist")

    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            headers = tuple(reader.fieldnames or ())
            rows = list(reader)
    except OSError as exc:
        return CsvSummary(path=path_text, exists=True, error=str(exc))

    lufs_columns, values, missing_lufs_count, bad_lufs_count = _count_csv_loudness_cells(
        headers, rows
    )
    preset_ids, device_patches = _summarize_csv_identifiers(rows)

    return CsvSummary(
        path=path_text,
        exists=True,
        headers=headers,
        row_count=len(rows),
        preset_ids=preset_ids,
        device_patches=device_patches,
        lufs_columns=lufs_columns,
        valid_lufs_count=len(values),
        missing_lufs_count=missing_lufs_count,
        bad_lufs_count=bad_lufs_count,
        lufs_min=min(values) if values else None,
        lufs_max=max(values) if values else None,
        lufs_average=(sum(values) / len(values)) if values else None,
    )


def _count_csv_loudness_cells(
    headers: tuple[str, ...],
    rows: list[dict[str, str]],
) -> tuple[tuple[str, ...], list[float], int, int]:
    lufs_columns = tuple(header for header in headers if _is_lufs_column(header))
    values: list[float] = []
    missing_lufs_count = 0
    bad_lufs_count = 0

    for row in rows:
        for column in lufs_columns:
            raw_value = row.get(column)
            if raw_value is None or raw_value.strip() == "":
                missing_lufs_count += 1
                continue
            value = _finite_float_or_none(raw_value)
            if value is None:
                bad_lufs_count += 1
            else:
                values.append(value)

    return lufs_columns, values, missing_lufs_count, bad_lufs_count


def _finite_float_or_none(value: str) -> float | None:
    try:
        result = float(value)
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def _summarize_csv_identifiers(
    rows: list[dict[str, str]],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return (
        _unique_text(row.get("Preset") for row in rows),
        _unique_text(row.get("DevicePatch") or row.get("HelixPreset") for row in rows)[:50],
    )


def build_diagnostic_snapshot(
    request: NormalizationRequest | None = None,
    *,
    config_path: str | None = None,
    checks: Sequence[DiagnosticCheck] = (),
    recent_progress_events: Sequence[Mapping[str, object]] = (),
    recent_gui_log_lines: Sequence[Mapping[str, str]] = (),
    retained_csv_path: Path | None = None,
    result: NormalizationResult | None = None,
    recent_logs: Iterable[Mapping[str, object] | tuple[object, object, object]] = (),
    recent_progress: Iterable[Mapping[str, object] | ProgressEvent] = (),
    runtime: RuntimeInfo | None = None,
) -> DiagnosticSnapshot:
    csv_path = retained_csv_path
    if csv_path is None and result is not None:
        csv_path = result.retained_csv_path
    runtime_info = runtime or RuntimeInfo.current()
    progress_events = tuple(recent_progress_events) + tuple(recent_progress)
    gui_log_lines = tuple(recent_gui_log_lines) + tuple(recent_logs)

    return DiagnosticSnapshot(
        generated_at=datetime.now(UTC).isoformat(),
        matchpatch_version=runtime_info.matchpatch_version,
        python_executable=runtime_info.python_executable,
        python_version=runtime_info.python_version,
        platform=runtime_info.platform,
        runtime_mode=runtime_info.runtime_mode,
        config_path=config_path,
        request=request_diagnostics(request) if request is not None else {},
        effective_config=effective_config_from_request(request) if request is not None else {},
        result=result_to_dict(result) if result is not None else None,
        retained_csv=summarize_csv(csv_path) if csv_path is not None else None,
        checks=list(checks),
        recent_gui_log_lines=list(_logs_to_dicts(gui_log_lines)),
        recent_progress_events=list(_progress_to_dicts(progress_events)),
    )


def write_diagnostic_bundle(snapshot: DiagnosticSnapshot, destination: Path) -> Path:
    """Write a diagnostic zip archive and return the final archive path."""

    bundle_path = _diagnostic_bundle_path(destination)
    bundle_path.parent.mkdir(parents=True, exist_ok=True)

    entries: list[tuple[str, str]] = [
        ("summary.txt", snapshot_to_text(snapshot)),
        ("diagnostics.json", json.dumps(snapshot_to_dict(snapshot), indent=2, sort_keys=True)),
        (
            "effective-config.json",
            json.dumps(snapshot.effective_config, indent=2, sort_keys=True),
        ),
        ("gui-log.txt", _format_gui_log(snapshot.recent_gui_log_lines)),
        (
            "progress-events.json",
            json.dumps(snapshot.recent_progress_events, indent=2, sort_keys=True),
        ),
    ]
    if snapshot.retained_csv is not None:
        entries.append(
            (
                "retained-csv-summary.json",
                json.dumps(snapshot.retained_csv, indent=2, sort_keys=True),
            )
        )

    try:
        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, content in entries:
                archive.writestr(name, content + "\n")
    except OSError as exc:
        raise OSError(f"Unable to write diagnostic bundle to {bundle_path}: {exc}") from exc

    return bundle_path


def _diagnostic_bundle_path(destination: Path) -> Path:
    if destination.exists() and destination.is_dir():
        raise ValueError(f"Diagnostic bundle destination is a directory: {destination}")
    if destination.suffix.lower() != ".zip":
        return destination.with_name(f"{destination.name}.zip")
    return destination


def _format_gui_log(log_lines: Sequence[Mapping[str, str]]) -> str:
    lines: list[str] = []
    for entry in log_lines:
        timestamp = entry.get("timestamp", "")
        level = entry.get("level", "")
        message = entry.get("message", "")
        lines.append(f"[{timestamp}] {level} {message}".rstrip())
    return "\n".join(lines)


def _current_runtime_mode() -> str:
    if getattr(sys, "frozen", False):
        return "frozen"
    if platform.system().lower() == "windows":
        return "windows"
    if os.environ.get("WSL_DISTRO_NAME") or "microsoft" in platform.release().lower():
        return "wsl"
    return "python"


def _path_text(path: Path) -> str:
    return str(path)


def _optional_path_text(path: Path | None) -> str | None:
    return str(path) if path is not None else None


def _is_lufs_column(header: str) -> bool:
    return header.startswith("LUFS") and header[4:].isdigit()


def _unique_text(values: Iterable[object | None]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return tuple(result)


def _logs_to_dicts(
    logs: Iterable[Mapping[str, object] | tuple[object, object, object]],
) -> tuple[dict[str, str], ...]:
    converted: list[dict[str, str]] = []
    for log in logs:
        if isinstance(log, Mapping):
            converted.append(
                {
                    "timestamp": str(log.get("timestamp", "")),
                    "level": str(log.get("level", "")),
                    "message": str(log.get("message", "")),
                }
            )
        else:
            timestamp, level, message = log
            converted.append(
                {
                    "timestamp": str(timestamp),
                    "level": str(level),
                    "message": str(message),
                }
            )
    return tuple(converted)


def _progress_to_dicts(
    progress: Iterable[Mapping[str, object] | ProgressEvent],
) -> tuple[dict[str, JsonValue], ...]:
    converted: list[dict[str, JsonValue]] = []
    for item in progress:
        if isinstance(item, ProgressEvent):
            converted.append(progress_event_to_dict(item))
        else:
            converted.append(_json_ready_dict(item))
    return tuple(converted)


def _json_ready_dict(values: Mapping[str, object]) -> dict[str, JsonValue]:
    return {str(key): _json_ready_value(value) for key, value in values.items()}


def _json_ready_value(value: object) -> JsonValue:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return _json_ready_dict(cast("Mapping[str, object]", value))
    if isinstance(value, tuple | list):
        return [_json_ready_value(item) for item in value]
    if isinstance(value, bool | int | float | str) or value is None:
        return value
    return str(value)
