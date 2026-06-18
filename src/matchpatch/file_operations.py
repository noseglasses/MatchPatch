"""Device-neutral workflows for processor file split/join operations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from matchpatch.devices import get_device_profile
from matchpatch.devices.base import DeviceProfile

PROJECT_DIR = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class JoinPresetFilesResult:
    output_path: Path


@dataclass(frozen=True)
class SplitSetlistFileResult:
    created_paths: list[Path]


def join_preset_files(
    device: str,
    preset_paths: list[Path],
    output_path: Path,
    *,
    slot_ids: list[int] | None = None,
    log_callback: Callable[[str], None] | None = None,
    get_profile: Callable[[str], DeviceProfile] = get_device_profile,
) -> JoinPresetFilesResult:
    profile = get_profile(device)
    handler = profile.create_patch_file_handler(PROJECT_DIR)
    handler.set_log_callback(log_callback)
    capabilities = handler.file_capabilities()

    if not capabilities.joins_presets_to_setlist:
        raise ValueError(f"{profile.display_name} does not support joining preset files")
    if handler.file_kind(output_path) != "setlist":
        raise ValueError(f"Join output must be a {profile.terminology().setlist} file")

    for preset_path in preset_paths:
        if handler.file_kind(preset_path) != "preset":
            raise ValueError(f"Join input must be {profile.terminology().preset} files")

    handler.join_preset_files(preset_paths, output_path, slot_ids=slot_ids)
    return JoinPresetFilesResult(output_path=output_path)


def split_setlist_file(
    device: str,
    input_path: Path,
    output_dir: Path,
    *,
    selected_ids: list[int] | None = None,
    original_filenames: Mapping[int, str] | None = None,
    log_callback: Callable[[str], None] | None = None,
    get_profile: Callable[[str], DeviceProfile] = get_device_profile,
) -> SplitSetlistFileResult:
    profile = get_profile(device)
    handler = profile.create_patch_file_handler(PROJECT_DIR)
    handler.set_log_callback(log_callback)
    capabilities = handler.file_capabilities()

    if not capabilities.splits_setlist_to_presets:
        raise ValueError(f"{profile.display_name} does not support splitting setlist files")
    if selected_ids is not None and not capabilities.exports_selected_setlist_slots:
        raise ValueError(f"{profile.display_name} does not support selected setlist export")
    if handler.file_kind(input_path) != "setlist":
        raise ValueError(f"Split input must be a {profile.terminology().setlist} file")

    created_paths = handler.split_setlist_file(
        input_path,
        output_dir,
        selected_ids=selected_ids,
        original_filenames=original_filenames,
    )
    return SplitSetlistFileResult(created_paths=created_paths)
