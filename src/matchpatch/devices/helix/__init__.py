"""Backward-compatible import path for Line 6 Helix support."""

from __future__ import annotations

import sys

from matchpatch.devices.line6 import helix as _helix

sys.modules[__name__] = _helix
