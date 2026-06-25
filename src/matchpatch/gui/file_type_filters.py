"""Qt file-filter helpers built from device-owned file type metadata."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from matchpatch.devices import get_device_profile
from matchpatch.devices.base import DeviceFileType

PROJECT_DIR = Path(__file__).resolve().parents[3]


def current_device_file_types(device: str) -> tuple[DeviceFileType, ...]:
    try:
        profile = get_device_profile(device)
        handler = profile.create_patch_file_handler(PROJECT_DIR)
        return handler.file_types()
    except Exception:  # noqa: BLE001
        return ()


def openable_extensions_for_device(device: str) -> tuple[str, ...]:
    return tuple(
        extension
        for file_type in current_device_file_types(device)
        if file_type.can_open
        for extension in file_type.normalized_extensions()
    )


def open_patch_filter(file_types: Sequence[DeviceFileType]) -> str:
    patterns = [
        pattern
        for file_type in file_types
        if file_type.can_open
        for pattern in file_type.patterns()
    ]
    return f"Patches ({' '.join(patterns)})" if patterns else "Patches (*.hls *.hlx)"


def open_patch_filter_for_device(device: str) -> str:
    return open_patch_filter(current_device_file_types(device))


def save_file_filter(
    file_types: Sequence[DeviceFileType],
    suffix: str,
    fallback: str,
) -> str | None:
    file_type = _file_type_for_suffix(file_types, suffix)
    if file_type is None:
        return None if file_types else fallback
    patterns = tuple(f"*{extension}" for extension in file_type.normalized_extensions())
    return f"{file_type.description} ({' '.join(patterns)})"


def helix_save_file_filter(device: str, suffix: str) -> str | None:
    fallback = f"Helix {suffix} (*{suffix})" if suffix in {".hls", ".hlx"} else ""
    return save_file_filter(current_device_file_types(device), suffix, fallback)


def _file_type_for_suffix(
    file_types: Sequence[DeviceFileType],
    suffix: str,
) -> DeviceFileType | None:
    normalized_suffix = suffix.lower()
    for file_type in file_types:
        if not file_type.can_save:
            continue
        if normalized_suffix in file_type.normalized_extensions():
            return file_type
    return None
