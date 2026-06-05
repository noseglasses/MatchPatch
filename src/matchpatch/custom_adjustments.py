"""Custom per-preset snapshot loudness target bumps."""

from __future__ import annotations

import csv
import math
from pathlib import Path

CustomAdjustments = dict[str, dict[int, float]]


def load_custom_adjustments_file(path: Path, snapshot_count: int) -> CustomAdjustments:
    """Load custom dB target bumps from a preset/snapshot CSV."""
    adjustments: CustomAdjustments = {}
    expected_columns = snapshot_count + 1

    with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        sample = csv_file.read(4096)
        csv_file.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(csv_file, dialect)
        for line_number, row in enumerate(reader, start=1):
            if not row or all(not cell.strip() for cell in row):
                continue
            if len(row) != expected_columns:
                raise ValueError(
                    f"Line {line_number}: expected {expected_columns} columns, got {len(row)}"
                )

            preset_id = row[0].strip().upper()
            if not preset_id:
                raise ValueError(f"Line {line_number}: preset ID is empty")
            if preset_id in adjustments:
                raise ValueError(f"Line {line_number}: duplicate preset ID {preset_id!r}")

            preset_adjustments: dict[int, float] = {}
            for snapshot_index, cell in enumerate(row[1:]):
                text = cell.strip()
                if not text:
                    continue
                try:
                    value = float(text)
                except ValueError as exc:
                    raise ValueError(
                        f"Line {line_number}: snapshot {snapshot_index + 1} "
                        f"custom adjustment is not a floating point number: {text!r}"
                    ) from exc
                if not math.isfinite(value):
                    raise ValueError(
                        f"Line {line_number}: snapshot {snapshot_index + 1} "
                        f"custom adjustment is not finite: {text!r}"
                    )
                preset_adjustments[snapshot_index] = value

            adjustments[preset_id] = preset_adjustments

    return adjustments
