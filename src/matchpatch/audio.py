"""Native Windows duplex audio support shared by hardware profiles."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import numpy as np

os.environ.setdefault("SD_ENABLE_ASIO", "1")

import sounddevice as sd  # noqa: E402


@dataclass(frozen=True)
class AudioConfig:
    device: str | int | None
    sample_rate: int
    input_mapping: tuple[int, int]
    output_mapping: tuple[int, int]
    blocksize: int = 0


def _matches_device(device: dict[str, Any], query: str) -> bool:
    return query.casefold() in str(device["name"]).casefold()


def resolve_audio_device(query: str | int | None) -> int | None:
    if query is None:
        return None

    if isinstance(query, int) or str(query).isdigit():
        return int(query)

    devices = sd.query_devices()
    matches = [index for index, device in enumerate(devices) if _matches_device(device, str(query))]

    if not matches:
        raise ValueError(f"No audio device matched {query!r}")

    asio_matches = [
        index
        for index in matches
        if "asio" in sd.query_hostapis(devices[index]["hostapi"])["name"].lower()
    ]

    if len(asio_matches) == 1:
        return asio_matches[0]

    if len(matches) == 1:
        return matches[0]

    raise ValueError(f"Audio device query {query!r} is ambiguous; use a numeric device ID")


def record_processed_audio(
    reference_audio: np.ndarray,
    config: AudioConfig,
) -> np.ndarray:
    device = resolve_audio_device(config.device)

    sd.check_input_settings(
        device=device,
        channels=len(config.input_mapping),
        dtype="float32",
        samplerate=config.sample_rate,
    )
    sd.check_output_settings(
        device=device,
        channels=len(config.output_mapping),
        dtype="float32",
        samplerate=config.sample_rate,
    )

    return sd.playrec(
        reference_audio,
        samplerate=config.sample_rate,
        channels=len(config.input_mapping),
        dtype="float32",
        input_mapping=list(config.input_mapping),
        output_mapping=list(config.output_mapping),
        blocking=True,
        device=(device, device),
        blocksize=config.blocksize,
    )
