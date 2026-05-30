from __future__ import annotations

import numpy as np
import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from matchpatch.analysis import (
    analyze_audio,
    calculate_average_short_term_lufs,
    calculate_crest_factor_db,
)


def test_crest_factor_for_sine_wave() -> None:
    sample_rate = 48000
    seconds = 4
    times = np.arange(sample_rate * seconds) / sample_rate
    audio = np.sin(2 * np.pi * 1000 * times)

    assert calculate_crest_factor_db(audio) == pytest.approx(3.0103, abs=0.001)


def test_lufs_requires_three_second_window() -> None:
    with pytest.raises(ValueError, match="shorter"):
        calculate_average_short_term_lufs(np.ones(100), 100)


@pytest.mark.parametrize("audio", [np.array([]), np.ones((2, 2, 2))])
def test_analysis_rejects_invalid_audio_shapes(audio: np.ndarray) -> None:
    with pytest.raises(ValueError, match="frames"):
        calculate_crest_factor_db(audio)


def test_crest_factor_rejects_silence() -> None:
    with pytest.raises(ValueError, match="silent"):
        calculate_crest_factor_db(np.zeros(100))


def test_lufs_rejects_silence() -> None:
    with pytest.raises(ValueError, match="valid"):
        calculate_average_short_term_lufs(np.zeros(400), 100)


def test_analyze_audio_returns_both_measurements() -> None:
    sample_rate = 100
    times = np.arange(sample_rate * 4) / sample_rate
    result = analyze_audio(np.sin(2 * np.pi * 5 * times), sample_rate)

    assert result.short_term_lufs < 0
    assert result.crest_factor_db == pytest.approx(3.0103, abs=0.01)


@given(
    samples=st.lists(
        st.floats(min_value=-100, max_value=100, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=100,
    ),
    scale=st.floats(min_value=0.01, max_value=100, allow_nan=False, allow_infinity=False),
)
def test_crest_factor_is_invariant_under_positive_scaling_and_channel_duplication(
    samples: list[float],
    scale: float,
) -> None:
    audio = np.asarray(samples, dtype=np.float64)
    assume(np.max(np.abs(audio)) > 1e-9)
    expected = calculate_crest_factor_db(audio)

    assert calculate_crest_factor_db(audio * scale) == pytest.approx(expected)
    assert calculate_crest_factor_db(np.column_stack((audio, audio))) == pytest.approx(expected)
