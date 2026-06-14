"""Formatting and parsing helpers for preset table display values."""

from __future__ import annotations

import math
import re
from html import escape

from PySide6.QtGui import QColor

from matchpatch.gui.table_roles import CUSTOM_ADJUSTMENT_COLOR

HELIX_NAME_PATTERN = re.compile(r"""^[A-Za-z0-9\-_+=!@#$&()?:'",./ ]*$""")
HELIX_NAME_CHAR_PATTERN = re.compile(r"""[A-Za-z0-9\-_+=!@#$&()?:'",./ ]""")


def validate_helix_name(name: str, max_length: int | None = None) -> str:
    if HELIX_NAME_PATTERN.fullmatch(name) is None:
        raise ValueError(f"Invalid Helix name: {name!r}")
    if max_length is not None and len(name) > max_length:
        raise ValueError(f"Helix name exceeds {max_length} characters: {name!r}")
    return name


def sanitize_helix_name(name: str, max_length: int | None = None) -> str:
    sanitized = "".join(
        character for character in name if HELIX_NAME_CHAR_PATTERN.fullmatch(character)
    )
    return sanitized[:max_length] if max_length is not None else sanitized


def _format_adjustment(value: float) -> str:
    return "0" if value == 0 else f"{value:+g}"


def _parse_adjustment_display_text(text: str) -> float:
    parts = text.strip().split(" ", 1)
    value = float(parts[0])
    if len(parts) == 1:
        return value

    custom_text = parts[1].strip()
    if custom_text.startswith("(") and custom_text.endswith(")"):
        return value + float(custom_text[1:-1])
    return value


def _normalize_snapshot_output_levels(levels: object) -> tuple[tuple[float, ...], ...]:
    if not isinstance(levels, (list, tuple)):
        return ()

    normalized: list[tuple[float, ...]] = []
    for snapshot_levels in levels:
        if not isinstance(snapshot_levels, (list, tuple)):
            normalized.append(())
            continue
        values: list[float] = []
        for level in snapshot_levels:
            if isinstance(level, (int, float)) and not isinstance(level, bool):
                values.append(float(level))
        normalized.append(tuple(values))
    return tuple(normalized)


def _normalize_snapshot_output_paths(paths: object) -> tuple[str, ...]:
    if not isinstance(paths, (list, tuple)):
        return ()
    return tuple(path for path in paths if isinstance(path, str) and path)


def _format_snapshot_output_levels(
    levels: tuple[tuple[float, ...], ...],
    snapshot_index: int,
) -> str:
    if snapshot_index >= len(levels):
        return ""
    return ", ".join(f"{level:.1f}" for level in levels[snapshot_index])


def _bad_lufs_adjustment_display(
    detail: str | None,
    *,
    adjustment: float | None = None,
) -> tuple[str, str]:
    bad_output_gain = _bad_lufs_output_gain(detail)
    if bad_output_gain is None:
        return (
            "Measurement failed ⚠️",
            "This snapshot is missing a usable LUFS or crest-factor measurement, so "
            "MatchPatch cannot calculate a safe Line 6 Helix output block level adjustment.",
        )
    if adjustment is None:
        return (
            "Measurement failed ⚠️",
            f"Resulting output block level would be {bad_output_gain:g} dB, outside the "
            "Line 6 Helix supported range of -120.0 to +20.0 dB, but the current "
            "output block level is unavailable in the table so MatchPatch cannot "
            "display the corresponding adjustment.",
        )

    display = f"{_format_adjustment(adjustment)} ⚠️"
    return (
        display,
        f"Resulting output block level would be {bad_output_gain:g} dB, outside the "
        "Line 6 Helix supported range of -120.0 to +20.0 dB. This usually means the "
        "measurement recorded silence or produced an unusable LUFS value.",
    )


def _bad_lufs_output_gain(detail: str | None) -> float | None:
    if not detail:
        return None
    match = re.search(r"Implausible output gain (?P<value>[+-]?\d+(?:\.\d+)?) dB", detail)
    if match is None:
        return None
    value = float(match["value"])
    return value if math.isfinite(value) else None


def _bad_lufs_output_path(detail: str | None) -> str | None:
    if not detail:
        return None
    match = re.search(r"\b(?P<path>dsp[01]\.output[AB])\b", detail)
    return match["path"] if match is not None else None


def _bad_lufs_adjustment(
    detail: str | None,
    current_output_levels: str,
    output_paths: tuple[str, ...] = (),
) -> float | None:
    bad_output_gain = _bad_lufs_output_gain(detail)
    if bad_output_gain is None:
        return None
    levels = _parse_output_level_display_text(current_output_levels)
    if not levels:
        return None
    output_path = _bad_lufs_output_path(detail)
    if output_path is not None and output_paths:
        try:
            output_index = output_paths.index(output_path)
        except ValueError:
            return None
        if output_index >= len(levels):
            return None
        return round(bad_output_gain - levels[output_index], 1)
    level = levels[0]
    if any(not math.isclose(candidate, level, abs_tol=0.05) for candidate in levels[1:]):
        return None
    return round(bad_output_gain - level, 1)


def _parse_output_level_display_text(text: str) -> tuple[float, ...]:
    values = []
    for part in text.split(","):
        value = part.strip()
        if not value:
            continue
        try:
            parsed = float(value)
        except ValueError:
            continue
        if math.isfinite(parsed):
            values.append(parsed)
    return tuple(values)


def _custom_adjustment_label_text(text: str) -> str:
    match = re.fullmatch(r"(?P<display>.*) (?P<custom>\([^)]+\))", text)
    if match is None:
        return escape(text)
    return (
        f"{escape(match['display'])} "
        f"<span style='color: {CUSTOM_ADJUSTMENT_COLOR};'>{escape(match['custom'])}</span>"
    )


def _interpolate_color(start: QColor, end: QColor, fraction: float) -> QColor:
    return QColor(
        round(start.red() + (end.red() - start.red()) * fraction),
        round(start.green() + (end.green() - start.green()) * fraction),
        round(start.blue() + (end.blue() - start.blue()) * fraction),
    )
