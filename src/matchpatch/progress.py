"""Structured progress events shared by CLI workers and the GUI."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ProgressEvent:
    kind: str
    message: str | None = None
    phase: str | None = None
    preset_id: int | None = None
    device_patch: str | None = None
    preset_index: int | None = None
    preset_total: int | None = None
    snapshot: int | None = None
    snapshot_total: int | None = None
    lufs: float | None = None
    crest_factor_db: float | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))

    @classmethod
    def from_json(cls, value: str) -> ProgressEvent:
        payload: Any = json.loads(value)

        if not isinstance(payload, dict):
            raise ValueError("Progress event must be a JSON object")

        try:
            return cls(**payload)
        except TypeError as exc:
            raise ValueError(f"Invalid progress event: {exc}") from exc
