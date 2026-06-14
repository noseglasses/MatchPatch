from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QColor

from matchpatch.gui import table_formatting, table_roles


def test_adjustment_display_round_trips_custom_adjustments() -> None:
    assert table_formatting._format_adjustment(0) == "0"
    assert table_formatting._format_adjustment(2.5) == "+2.5"
    assert table_formatting._format_adjustment(-3.0) == "-3"
    assert table_formatting._parse_adjustment_display_text("+2.5 (-0.5)") == 2.0


def test_snapshot_output_levels_filter_invalid_values() -> None:
    levels = table_formatting._normalize_snapshot_output_levels(
        [[-12, True, "-9", -6.5], "bad", (0, 1)]
    )

    assert levels == ((-12.0, -6.5), (), (0.0, 1.0))
    assert table_formatting._format_snapshot_output_levels(levels, 0) == "-12.0, -6.5"
    assert table_formatting._format_snapshot_output_levels(levels, 99) == ""


def test_bad_lufs_adjustment_uses_named_output_path() -> None:
    detail = "Implausible output gain +21.5 dB for dsp1.outputB"

    assert table_formatting._bad_lufs_output_gain(detail) == 21.5
    assert table_formatting._bad_lufs_output_path(detail) == "dsp1.outputB"
    assert (
        table_formatting._bad_lufs_adjustment(
            detail,
            "-3.0, -6.0",
            ("dsp0.outputA", "dsp1.outputB"),
        )
        == 27.5
    )


def test_custom_adjustment_label_escapes_and_colors_custom_part() -> None:
    assert table_formatting._custom_adjustment_label_text("<b> (+1)") == (
        f"&lt;b&gt; <span style='color: {table_roles.CUSTOM_ADJUSTMENT_COLOR};'>(+1)</span>"
    )


def test_helix_names_validate_and_sanitize() -> None:
    assert table_formatting.validate_helix_name("Clean + Lead", 20) == "Clean + Lead"
    assert table_formatting.sanitize_helix_name("Bad*Name🙂", 7) == "BadName"
    with pytest.raises(ValueError, match="Invalid Helix name"):
        table_formatting.validate_helix_name("Bad*Name")


def test_interpolate_color_uses_channel_rounding() -> None:
    assert table_formatting._interpolate_color(QColor("#000000"), QColor("#ffffff"), 0.5) == QColor(
        128,
        128,
        128,
    )


def test_snapshot_tooltip_describes_combined_ignore_reasons() -> None:
    assert (
        table_roles._snapshot_tooltip(
            True,
            (table_roles.IGNORE_REASON_PRESET, table_roles.IGNORE_REASON_REGEX),
        )
        == "Solo snapshot; skipped during normalization: preset unchecked, ignore regex"
    )
