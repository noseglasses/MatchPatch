"""Audio measurements compatible with the historical MatchPatch CSV format."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pyloudnorm as pyln

MINIMUM_LUFS_WINDOW_SECONDS = 0.4


@dataclass(frozen=True)
class AudioMeasurements:
    short_term_lufs: float
    crest_factor_db: float


@dataclass(frozen=True)
class AnalysisOptions:
    window_seconds: float = 3.0
    interval_seconds: float = 0.1
    minimum_valid_lufs: float = -100.0


def _as_float_audio(audio: np.ndarray) -> np.ndarray:
    result = np.asarray(audio, dtype=np.float64)

    if result.ndim == 1:
        result = result[:, np.newaxis]

    if result.ndim != 2 or result.shape[0] == 0:
        raise ValueError("Audio must contain frames and one or more channels")

    return result


def calculate_average_short_term_lufs(
    audio: np.ndarray,
    sample_rate: int,
    window_seconds: float = 3.0,
    interval_seconds: float = 0.1,
    minimum_valid_lufs: float = -100.0,
) -> float:
    """Average LUFS values from sliding three-second analysis windows."""

    samples = _as_float_audio(audio)
    window_frames = round(window_seconds * sample_rate)
    interval_frames = round(interval_seconds * sample_rate)

    if window_seconds < MINIMUM_LUFS_WINDOW_SECONDS:
        raise ValueError(f"LUFS window must be at least {MINIMUM_LUFS_WINDOW_SECONDS:g} s")

    if samples.shape[0] < window_frames:
        raise ValueError(f"Audio is shorter than the {window_seconds:g} s LUFS window")

    meter = pyln.Meter(sample_rate)
    values = []

    for end in range(window_frames, samples.shape[0] + 1, interval_frames):
        value = meter.integrated_loudness(samples[end - window_frames : end])

        if np.isfinite(value) and value > minimum_valid_lufs:
            values.append(float(value))

    if not values:
        raise ValueError("Could not collect valid short-term LUFS values")

    return float(np.mean(values))


def calculate_crest_factor_db(audio: np.ndarray) -> float:
    samples = _as_float_audio(audio)
    peak = float(np.max(np.abs(samples)))
    rms = float(np.sqrt(np.mean(np.square(samples))))

    if peak <= 0.0 or rms <= 0.0:
        raise ValueError("Could not calculate crest factor from silent audio")

    return float(20.0 * np.log10(peak / rms))


def analyze_audio(
    audio: np.ndarray,
    sample_rate: int,
    options: AnalysisOptions = AnalysisOptions(),
) -> AudioMeasurements:
    return AudioMeasurements(
        short_term_lufs=calculate_average_short_term_lufs(
            audio,
            sample_rate,
            options.window_seconds,
            options.interval_seconds,
            options.minimum_valid_lufs,
        ),
        crest_factor_db=calculate_crest_factor_db(audio),
    )
