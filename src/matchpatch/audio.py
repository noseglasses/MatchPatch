"""Native Windows duplex audio support shared by hardware profiles."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
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
    pre_roll_seconds: float = 1.0
    post_roll_seconds: float = 1.0
    round_trip_latency_seconds: float = 0.02


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


def prepare_audio_config(config: AudioConfig) -> AudioConfig:
    """Resolve and validate audio settings once before recording starts."""
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
    return replace(config, device=device)


def record_processed_audio(
    reference_audio: np.ndarray,
    config: AudioConfig,
) -> np.ndarray:
    device = resolve_audio_device(config.device)
    pre_roll_frames = round(config.pre_roll_seconds * config.sample_rate)
    post_roll_frames = round(config.post_roll_seconds * config.sample_rate)
    latency_frames = round(config.round_trip_latency_seconds * config.sample_rate)

    if min(pre_roll_frames, post_roll_frames, latency_frames) < 0:
        raise ValueError("Audio pre-roll, post-roll, and round-trip latency must not be negative")

    if latency_frames > post_roll_frames:
        raise ValueError("Audio post-roll must be at least as long as round-trip latency")

    reference = np.asarray(reference_audio)

    if reference.ndim != 2 or reference.shape[0] == 0:
        raise ValueError("Reference audio must contain frames and one or more channels")

    silence_shape = (pre_roll_frames + post_roll_frames, reference.shape[1])
    silence = np.zeros(silence_shape, dtype=reference.dtype)
    playback = np.concatenate(
        [silence[:pre_roll_frames], reference, silence[pre_roll_frames:]],
        axis=0,
    )

    recorded = sd.playrec(
        playback,
        samplerate=config.sample_rate,
        channels=len(config.input_mapping),
        dtype="float32",
        input_mapping=list(config.input_mapping),
        output_mapping=list(config.output_mapping),
        blocking=True,
        device=(device, device),
        blocksize=config.blocksize,
    )
    aligned_start = pre_roll_frames + latency_frames
    aligned_end = aligned_start + reference.shape[0]
    return recorded[aligned_start:aligned_end]
