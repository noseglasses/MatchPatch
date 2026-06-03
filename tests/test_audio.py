from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

import numpy as np
import pytest


def load_audio(monkeypatch: pytest.MonkeyPatch, sounddevice: object):
    monkeypatch.setitem(sys.modules, "sounddevice", sounddevice)
    sys.modules.pop("matchpatch.audio", None)
    return importlib.import_module("matchpatch.audio")


def test_resolve_audio_device_prefers_unique_asio_match(monkeypatch) -> None:
    sd = SimpleNamespace(
        query_devices=lambda: [
            {"name": "Helix DirectSound", "hostapi": 0},
            {"name": "Helix ASIO", "hostapi": 1},
        ],
        query_hostapis=lambda index: [{"name": "MME"}, {"name": "ASIO"}][index],
    )
    audio = load_audio(monkeypatch, sd)

    assert audio.resolve_audio_device(None) is None
    assert audio.resolve_audio_device("3") == 3
    assert audio.resolve_audio_device("helix") == 1


def test_resolve_audio_device_reports_missing_and_ambiguous_matches(monkeypatch) -> None:
    sd = SimpleNamespace(
        query_devices=lambda: [
            {"name": "Processor A", "hostapi": 0},
            {"name": "Processor B", "hostapi": 0},
        ],
        query_hostapis=lambda index: {"name": "MME"},
    )
    audio = load_audio(monkeypatch, sd)

    with pytest.raises(ValueError, match="No audio device"):
        audio.resolve_audio_device("missing")

    with pytest.raises(ValueError, match="ambiguous"):
        audio.resolve_audio_device("processor")


def test_resolve_audio_device_accepts_unique_non_asio_match(monkeypatch) -> None:
    sd = SimpleNamespace(
        query_devices=lambda: [{"name": "USB Processor", "hostapi": 0}],
        query_hostapis=lambda index: {"name": "MME"},
    )
    audio = load_audio(monkeypatch, sd)

    assert audio.resolve_audio_device("usb") == 0


def test_prepare_audio_config_checks_settings_and_record_uses_resolved_device(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []
    recorded = np.ones((3, 2))
    sd = SimpleNamespace(
        query_devices=lambda: [],
        check_input_settings=lambda **kwargs: calls.append(("input", kwargs)),
        check_output_settings=lambda **kwargs: calls.append(("output", kwargs)),
        playrec=lambda reference, **kwargs: calls.append(("playrec", kwargs)) or recorded,
    )
    audio = load_audio(monkeypatch, sd)
    config = audio.AudioConfig(
        "2",
        48000,
        (1, 2),
        (3, 4),
        blocksize=64,
        pre_roll_seconds=0.0,
        post_roll_seconds=0.0,
        round_trip_latency_seconds=0.0,
    )

    prepared = audio.prepare_audio_config(config)
    np.testing.assert_array_equal(
        audio.record_processed_audio(np.zeros((3, 2)), prepared), recorded
    )
    assert calls[0] == (
        "input",
        {"device": 2, "channels": 2, "dtype": "float32", "samplerate": 48000},
    )
    assert calls[2][1]["device"] == (2, 2)
    assert calls[2][1]["input_mapping"] == [1, 2]
    assert calls[2][1]["output_mapping"] == [3, 4]
    assert prepared.device == 2


def test_validate_audio_device_available_checks_channel_counts(monkeypatch) -> None:
    devices = [
        {
            "name": "Helix ASIO",
            "hostapi": 0,
            "max_input_channels": 2,
            "max_output_channels": 4,
        }
    ]
    sd = SimpleNamespace(
        query_devices=lambda index=None: devices if index is None else devices[index],
        query_hostapis=lambda index: {"name": "ASIO"},
    )
    audio = load_audio(monkeypatch, sd)

    config = audio.AudioConfig("helix", 48000, (1, 2), (3, 4))
    assert audio.validate_audio_device_available(config).device == 0

    with pytest.raises(ValueError, match="output channels"):
        audio.validate_audio_device_available(audio.AudioConfig("helix", 48000, (1, 2), (3, 5)))


def test_record_processed_audio_pads_and_trims_fixed_latency(monkeypatch) -> None:
    playback = []
    recorded = np.arange(16, dtype=np.float32)[:, np.newaxis]
    sd = SimpleNamespace(
        query_devices=lambda: [],
        check_input_settings=lambda **kwargs: None,
        check_output_settings=lambda **kwargs: None,
        playrec=lambda reference, **kwargs: playback.append(reference) or recorded,
    )
    audio = load_audio(monkeypatch, sd)
    config = audio.AudioConfig(
        None,
        10,
        (1,),
        (2,),
        pre_roll_seconds=0.3,
        post_roll_seconds=0.5,
        round_trip_latency_seconds=0.2,
    )
    reference = np.array([[1.0], [2.0], [3.0], [4.0]], dtype=np.float32)

    actual = audio.record_processed_audio(reference, config)

    np.testing.assert_array_equal(
        playback[0],
        np.array(
            [[0.0], [0.0], [0.0], [1.0], [2.0], [3.0], [4.0], [0.0], [0.0], [0.0], [0.0], [0.0]],
            dtype=np.float32,
        ),
    )
    np.testing.assert_array_equal(actual, recorded[5:9])


def test_record_processed_audio_rejects_insufficient_post_roll(monkeypatch) -> None:
    audio = load_audio(monkeypatch, SimpleNamespace(query_devices=lambda: []))
    config = audio.AudioConfig(
        None,
        10,
        (1,),
        (2,),
        pre_roll_seconds=0.0,
        post_roll_seconds=0.1,
        round_trip_latency_seconds=0.2,
    )

    with pytest.raises(ValueError, match="post-roll"):
        audio.record_processed_audio(np.ones((4, 1)), config)
