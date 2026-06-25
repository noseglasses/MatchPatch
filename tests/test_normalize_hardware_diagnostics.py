from __future__ import annotations

import argparse
import sys

from matchpatch import normalize


def _hardware_args(**overrides: object) -> argparse.Namespace:
    values = dict(
        device="helix",
        backend="hardware",
        audio_device="Helix",
        steering_output="Helix",
        steering_channel=2,
        sample_rate=48000,
        input_mapping=(1, 2),
        output_mapping=(3, 4),
        blocksize=128,
        preset_wait=None,
        snapshot_wait=None,
        measurement_wait=None,
        pre_roll=0.2,
        post_roll=0.1,
        round_trip_latency=0.02,
        timeout=5,
    )
    values.update(overrides)
    return argparse.Namespace(**values)


def test_collect_hardware_diagnostics_uses_native_macos_collector(monkeypatch) -> None:
    expected = [normalize.DiagnosticCheck("audio_device", "pass", "ok")]
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(
        normalize,
        "collect_macos_hardware_diagnostics",
        lambda args: expected,
    )
    monkeypatch.setattr(
        normalize,
        "collect_windows_hardware_diagnostics",
        lambda args: (_ for _ in ()).throw(AssertionError("Windows collector should not run")),
    )

    assert normalize.collect_hardware_diagnostics(_hardware_args()) == expected


def test_collect_macos_hardware_diagnostics_validates_audio_and_midi(monkeypatch) -> None:
    captured = {}

    def fake_validate_audio_device_available(config):
        captured["audio_config"] = config
        return config

    monkeypatch.setitem(
        sys.modules,
        "matchpatch.audio",
        argparse.Namespace(
            AudioConfig=argparse.Namespace,
            validate_audio_device_available=fake_validate_audio_device_available,
        ),
    )
    monkeypatch.setattr("matchpatch.midi.midi_output_names", lambda: ["Helix CoreMIDI"])

    checks = normalize.collect_macos_hardware_diagnostics(_hardware_args())

    assert [check.name for check in checks] == [
        "device_profile",
        "audio_device",
        "midi_output",
    ]
    assert [check.status for check in checks] == ["pass", "pass", "pass"]
    assert captured["audio_config"].device == "Helix"
    assert captured["audio_config"].input_mapping == (1, 2)
    assert captured["audio_config"].output_mapping == (3, 4)
    assert "output=Helix CoreMIDI" in checks[2].detail


def test_collect_macos_hardware_diagnostics_reports_channel_capacity_failure(
    monkeypatch,
) -> None:
    def fake_validate_audio_device_available(config):
        raise ValueError("'Helix' has 2 output channels; need channel 4")

    monkeypatch.setitem(
        sys.modules,
        "matchpatch.audio",
        argparse.Namespace(
            AudioConfig=argparse.Namespace,
            validate_audio_device_available=fake_validate_audio_device_available,
        ),
    )
    monkeypatch.setattr("matchpatch.midi.midi_output_names", lambda: ["Helix CoreMIDI"])

    checks = normalize.collect_macos_hardware_diagnostics(_hardware_args())

    audio_check = next(check for check in checks if check.name == "audio_device")
    midi_check = next(check for check in checks if check.name == "midi_output")
    assert audio_check.status == "fail"
    assert "need channel 4" in audio_check.summary
    assert midi_check.status == "pass"
