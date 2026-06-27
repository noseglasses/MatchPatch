"""Runtime resource paths for installed and source-tree MatchPatch builds."""

from __future__ import annotations

import os
import shutil
from importlib.resources import files
from pathlib import Path

RESOURCE_ROOT = "_resources"
REFERENCE_DI_NAME = "DI_Strandberg_Boden_Fusion_Bridge_Humbucker.wav"


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resource_path(*parts: str) -> Path:
    """Resolve a packaged resource, falling back to the source tree if needed."""
    packaged_path = _packaged_resource_path(*parts)
    if packaged_path.exists():
        return packaged_path

    source_path = project_root() / Path(*parts)
    if source_path.exists():
        return source_path

    return packaged_path


def reference_di_path() -> Path:
    return resource_path("audio", "reference-di", REFERENCE_DI_NAME)


def _packaged_resource_path(*parts: str) -> Path:
    resource = files("matchpatch").joinpath(RESOURCE_ROOT, *parts)
    if isinstance(resource, Path):
        return resource

    target = _cache_root().joinpath(*parts)
    if target.exists():
        return target

    if resource.is_dir():
        target.mkdir(parents=True, exist_ok=True)
        for child in resource.iterdir():
            child_target = _packaged_resource_path(*parts, child.name)
            if child_target.parent != target:
                child_target.parent.mkdir(parents=True, exist_ok=True)
        return target

    if not resource.is_file():
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    with resource.open("rb") as resource_file:
        with target.open("wb") as target_file:
            shutil.copyfileobj(resource_file, target_file)
    return target


def _cache_root() -> Path:
    base = os.getenv("MATCHPATCH_RESOURCE_CACHE")
    if base:
        return Path(base).expanduser()

    if os.name == "nt":
        appdata = os.getenv("LOCALAPPDATA")
        if appdata:
            return Path(appdata) / "MatchPatch" / "resources"

    xdg_cache_home = os.getenv("XDG_CACHE_HOME")
    if xdg_cache_home:
        return Path(xdg_cache_home) / "matchpatch" / "resources"
    return Path.home() / ".cache" / "matchpatch" / "resources"
