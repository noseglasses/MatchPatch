"""MatchPatch package."""

from __future__ import annotations

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _version_from_pyproject() -> str:
    pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    with pyproject_path.open("rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)
    return str(pyproject["project"]["version"])


try:
    __version__ = version("matchpatch")
except PackageNotFoundError:  # pragma: no cover - fallback for direct source execution
    __version__ = _version_from_pyproject()
