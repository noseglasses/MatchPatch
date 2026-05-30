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


def test_record_processed_audio_checks_and_records_with_config(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []
    recorded = np.ones((3, 2))
    sd = SimpleNamespace(
        query_devices=lambda: [],
        check_input_settings=lambda **kwargs: calls.append(("input", kwargs)),
        check_output_settings=lambda **kwargs: calls.append(("output", kwargs)),
        playrec=lambda reference, **kwargs: calls.append(("playrec", kwargs)) or recorded,
    )
    audio = load_audio(monkeypatch, sd)
    config = audio.AudioConfig("2", 48000, (1, 2), (3, 4), blocksize=64)

    assert audio.record_processed_audio(np.zeros((3, 2)), config) is recorded
    assert calls[0] == (
        "input",
        {"device": 2, "channels": 2, "dtype": "float32", "samplerate": 48000},
    )
    assert calls[2][1]["device"] == (2, 2)
    assert calls[2][1]["input_mapping"] == [1, 2]
    assert calls[2][1]["output_mapping"] == [3, 4]
