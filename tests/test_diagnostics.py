from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from matchpatch.analysis import AnalysisOptions
from matchpatch.devices.base import NormalizationPolicy
from matchpatch.diagnostics import (
    DiagnosticCheck,
    EffectiveConfig,
    RuntimeInfo,
    build_diagnostic_snapshot,
    diagnostic_check_from_dict,
    diagnostic_check_to_dict,
    summarize_csv,
    write_diagnostic_bundle,
)
from matchpatch.workflow import NormalizationRequest, NormalizationResult


def test_effective_config_from_request_is_json_ready(tmp_path: Path) -> None:
    request = NormalizationRequest(
        device="helix",
        input_path=tmp_path / "input.hls",
        output_path=tmp_path / "output.hls",
        diff_input_path=tmp_path / "previous.hls",
        automation=False,
        preset_set="01A,01B",
        limit=2,
        keep_temp=True,
        ignore_bad_lufs=False,
        target_lufs=-18.0,
        backend="hardware",
        windows_python="C:/Python/python.exe",
        reference_di=tmp_path / "reference.wav",
        custom_adjustments_path=tmp_path / "custom.csv",
        audio_device="ASIO Helix",
        sample_rate=48000,
        input_mapping="1,2",
        output_mapping="3,4",
        blocksize=128,
        steering_output="Helix MIDI",
        steering_channel=2,
        preset_wait=1.2,
        snapshot_wait=0.5,
        measurement_wait=0.2,
        pre_roll=1.0,
        post_roll=1.5,
        round_trip_latency=0.03,
        play_recorded_output=True,
        record_device_output=True,
        playback_toggle_path=tmp_path / "toggle.txt",
        recorded_output_dir=tmp_path / "recordings",
        snapshot_plan=(("01A", (1, 3)),),
        policy=NormalizationPolicy(
            snapshot_count=3,
            solo_regex="solo",
            ignore_snapshot_regex="skip",
            solo_gain_bump_db=2.0,
        ),
        analysis_options=AnalysisOptions(
            window_seconds=2.5,
            interval_seconds=0.25,
            minimum_valid_lufs=-90.0,
        ),
    )

    config = EffectiveConfig.from_request(request)
    payload = config.to_dict()

    assert payload["input_path"] == str(tmp_path / "input.hls")
    assert payload["custom_adjustments_path"] == str(tmp_path / "custom.csv")
    assert payload["policy"]["snapshot_count"] == 3
    assert payload["policy"]["solo_regex"] == "solo"
    assert payload["analysis_options"]["window_seconds"] == 2.5
    assert payload["snapshot_plan"] == [{"patch": "01A", "snapshots": [1, 3]}]
    json.dumps(payload)


def test_summarize_csv_counts_lufs_cells_and_identifiers(tmp_path: Path) -> None:
    csv_path = tmp_path / "lufs_analysis.csv"
    csv_path.write_text(
        "Preset,DevicePatch,LUFS1,LUFS2,Note\n"
        "1,01A,-16.5,ERROR,kept\n"
        "2,01B,,SKIP,kept\n"
        "2,01B,-15.5,-14.0,duplicate\n",
        encoding="utf-8",
    )

    summary = summarize_csv(csv_path)

    assert summary["exists"] is True
    assert summary["row_count"] == 3
    assert summary["headers"] == ["Preset", "DevicePatch", "LUFS1", "LUFS2", "Note"]
    assert summary["preset_ids"] == ["1", "2"]
    assert summary["device_patches"] == ["01A", "01B"]
    assert summary["lufs_columns"] == ["LUFS1", "LUFS2"]
    assert summary["valid_lufs_count"] == 3
    assert summary["missing_lufs_count"] == 1
    assert summary["bad_lufs_count"] == 2
    assert summary["lufs_min"] == -16.5
    assert summary["lufs_max"] == -14.0
    assert summary["lufs_average"] == (-16.5 - 15.5 - 14.0) / 3


def test_summarize_missing_csv_returns_serializable_error(tmp_path: Path) -> None:
    summary = summarize_csv(tmp_path / "missing.csv")

    assert summary == {
        "path": str(tmp_path / "missing.csv"),
        "exists": False,
        "headers": [],
        "row_count": 0,
        "preset_ids": [],
        "device_patches": [],
        "lufs_columns": [],
        "valid_lufs_count": 0,
        "missing_lufs_count": 0,
        "bad_lufs_count": 0,
        "lufs_min": None,
        "lufs_max": None,
        "lufs_average": None,
        "error": "CSV file does not exist",
    }


def test_diagnostic_check_round_trips_dict() -> None:
    check = DiagnosticCheck(
        name="midi_output",
        status="fail",
        summary="MIDI output query matched 0 ports",
        detail="query=Missing; match_count=0; matched_outputs=[]",
    )

    payload = diagnostic_check_to_dict(check)
    restored = diagnostic_check_from_dict(payload)

    assert payload == {
        "name": "midi_output",
        "status": "fail",
        "summary": "MIDI output query matched 0 ports",
        "detail": "query=Missing; match_count=0; matched_outputs=[]",
    }
    assert restored == check


def test_build_diagnostic_snapshot_outputs_json_and_text(tmp_path: Path) -> None:
    csv_path = tmp_path / "lufs_analysis.csv"
    csv_path.write_text("Preset,HelixPreset,LUFS1\n1,01A,-16.0\n", encoding="utf-8")
    request = NormalizationRequest(
        device="helix",
        input_path=tmp_path / "input.hls",
        backend="loopback",
        windows_python="python.exe",
        reference_di=tmp_path / "reference.wav",
        target_lufs=-17.0,
        policy=NormalizationPolicy(snapshot_count=1),
    )
    result = NormalizationResult(
        output_path=tmp_path / "output.hls",
        temp_dir=tmp_path / "temp",
        retained_csv_path=csv_path,
    )

    snapshot = build_diagnostic_snapshot(
        request=request,
        result=result,
        recent_logs=[("12:00", "INFO", "Started")],
        recent_progress=[{"kind": "temp_retained", "path": csv_path}],
        runtime=RuntimeInfo(
            matchpatch_version="test",
            python_executable="/python",
            python_version="3.12",
            platform="test-platform",
        ),
    )

    payload = json.loads(snapshot.to_json())
    text = snapshot.to_text()

    assert payload["runtime"]["matchpatch_version"] == "test"
    assert payload["effective_config"]["backend"] == "loopback"
    assert payload["result"]["retained_csv_path"] == str(csv_path)
    assert payload["retained_csv"]["device_patches"] == ["01A"]
    assert payload["recent_logs"] == [{"timestamp": "12:00", "level": "INFO", "message": "Started"}]
    assert payload["recent_progress"] == [{"kind": "temp_retained", "path": str(csv_path)}]
    assert "MatchPatch: test" in text
    assert "Device: helix" in text
    assert "Rows: 1" in text


def test_write_diagnostic_bundle_appends_zip_and_writes_stable_entries(tmp_path: Path) -> None:
    csv_path = tmp_path / "lufs_analysis.csv"
    csv_path.write_text("Preset,DevicePatch,LUFS1\n1,01A,-16.0\n", encoding="utf-8")
    request = NormalizationRequest(
        device="helix",
        input_path=tmp_path / "input.hls",
        output_path=tmp_path / "output.hls",
        backend="loopback",
        windows_python="python.exe",
        reference_di=tmp_path / "reference.wav",
        custom_adjustments_path=tmp_path / "custom.csv",
        target_lufs=-17.0,
        policy=NormalizationPolicy(snapshot_count=1),
    )
    snapshot = build_diagnostic_snapshot(
        request,
        config_path=str(tmp_path / "matchpatch.toml"),
        checks=[DiagnosticCheck("audio_device", "pass", "Audio device is available")],
        recent_progress_events=[{"kind": "phase", "message": "Measuring"}],
        recent_gui_log_lines=[{"timestamp": "12:00", "level": "INFO", "message": "Started"}],
        retained_csv_path=csv_path,
        runtime=RuntimeInfo(
            matchpatch_version="test",
            python_executable="/python",
            python_version="3.12",
            platform="test-platform",
        ),
    )

    bundle_path = write_diagnostic_bundle(snapshot, tmp_path / "nested" / "diagnostics")

    assert bundle_path == tmp_path / "nested" / "diagnostics.zip"
    assert bundle_path.exists()
    with zipfile.ZipFile(bundle_path) as archive:
        assert archive.namelist() == [
            "summary.txt",
            "diagnostics.json",
            "effective-config.json",
            "gui-log.txt",
            "progress-events.json",
            "retained-csv-summary.json",
        ]
        diagnostics = json.loads(archive.read("diagnostics.json"))
        effective_config = json.loads(archive.read("effective-config.json"))
        progress_events = json.loads(archive.read("progress-events.json"))
        retained_csv = json.loads(archive.read("retained-csv-summary.json"))
        gui_log = archive.read("gui-log.txt").decode("utf-8")

    assert diagnostics["config_path"] == str(tmp_path / "matchpatch.toml")
    assert diagnostics["checks"] == [
        {
            "name": "audio_device",
            "status": "pass",
            "summary": "Audio device is available",
            "detail": "",
        }
    ]
    assert effective_config["input_path"] == str(tmp_path / "input.hls")
    assert progress_events == [{"kind": "phase", "message": "Measuring"}]
    assert retained_csv["row_count"] == 1
    assert gui_log == "[12:00] INFO Started\n"


def test_write_diagnostic_bundle_omits_retained_csv_entry_when_absent(tmp_path: Path) -> None:
    request = NormalizationRequest(
        device="helix",
        input_path=tmp_path / "input.hls",
        backend="loopback",
        windows_python="python.exe",
        reference_di=tmp_path / "reference.wav",
    )
    snapshot = build_diagnostic_snapshot(request)

    bundle_path = write_diagnostic_bundle(snapshot, tmp_path / "diagnostics.zip")

    with zipfile.ZipFile(bundle_path) as archive:
        assert "retained-csv-summary.json" not in archive.namelist()
        json.loads(archive.read("diagnostics.json"))
        json.loads(archive.read("effective-config.json"))
        json.loads(archive.read("progress-events.json"))


def test_write_diagnostic_bundle_excludes_raw_files(tmp_path: Path) -> None:
    input_path = tmp_path / "input.hls"
    reference_path = tmp_path / "reference.wav"
    custom_path = tmp_path / "custom.csv"
    output_path = tmp_path / "output.hls"
    for path in (input_path, reference_path, custom_path, output_path):
        path.write_text(f"raw content from {path.name}", encoding="utf-8")
    request = NormalizationRequest(
        device="helix",
        input_path=input_path,
        output_path=output_path,
        backend="loopback",
        windows_python="python.exe",
        reference_di=reference_path,
        custom_adjustments_path=custom_path,
    )
    snapshot = build_diagnostic_snapshot(request)

    bundle_path = write_diagnostic_bundle(snapshot, tmp_path / "diagnostics.zip")

    with zipfile.ZipFile(bundle_path) as archive:
        names = set(archive.namelist())
        bundle_bytes = b"".join(archive.read(name) for name in names)

    assert names == {
        "summary.txt",
        "diagnostics.json",
        "effective-config.json",
        "gui-log.txt",
        "progress-events.json",
    }
    assert b"raw content from input.hls" not in bundle_bytes
    assert b"raw content from reference.wav" not in bundle_bytes
    assert b"raw content from custom.csv" not in bundle_bytes
    assert b"raw content from output.hls" not in bundle_bytes


def test_write_diagnostic_bundle_rejects_directory_destination(tmp_path: Path) -> None:
    snapshot = build_diagnostic_snapshot()

    with pytest.raises(ValueError, match="destination is a directory"):
        write_diagnostic_bundle(snapshot, tmp_path)
