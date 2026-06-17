"""Registry of audio processor profiles."""

from __future__ import annotations

from collections.abc import Iterable
from importlib import metadata
from typing import Any

from matchpatch.devices.base import DeviceProfile
from matchpatch.devices.helix import HelixDeviceProfile

ENTRY_POINT_GROUP = "matchpatch.devices"

_PROFILES: dict[str, DeviceProfile] = {
    "helix": HelixDeviceProfile(),
}
_PLUGIN_LOAD_ERRORS: dict[str, str] = {}


def _entry_points() -> Iterable[metadata.EntryPoint]:
    entry_points = metadata.entry_points()
    if hasattr(entry_points, "select"):
        return entry_points.select(group=ENTRY_POINT_GROUP)
    return entry_points.get(ENTRY_POINT_GROUP, ())


def _profile_from_loaded(value: Any) -> list[DeviceProfile]:  # noqa: ANN401
    if isinstance(value, DeviceProfile):
        return [value]
    if isinstance(value, type) and issubclass(value, DeviceProfile):
        return [value()]
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        profiles = []
        for item in value:
            if not isinstance(item, DeviceProfile):
                raise TypeError("device entry point iterable must contain DeviceProfile instances")
            profiles.append(item)
        return profiles
    raise TypeError("device entry point must return a DeviceProfile, subclass, or iterable")


def _validate_profile(profile: DeviceProfile) -> None:
    if not isinstance(getattr(profile, "name", None), str) or not profile.name:
        raise ValueError("device profile name must be a non-empty string")
    if not isinstance(getattr(profile, "display_name", None), str) or not profile.display_name:
        raise ValueError(f"device profile {profile.name!r} must define a display name")
    if not callable(getattr(profile, "create_patch_file_handler", None)):
        raise ValueError(f"device profile {profile.name!r} must create patch file handlers")


def _plugin_profiles() -> dict[str, DeviceProfile]:
    profiles: dict[str, DeviceProfile] = {}
    _PLUGIN_LOAD_ERRORS.clear()
    for entry_point in _entry_points():
        try:
            loaded = entry_point.load()
            for profile in _profile_from_loaded(loaded):
                _validate_profile(profile)
                if profile.name in _PROFILES or profile.name in profiles:
                    raise ValueError(f"duplicate device profile name {profile.name!r}")
                profiles[profile.name] = profile
        except Exception as exc:  # noqa: BLE001
            _PLUGIN_LOAD_ERRORS[entry_point.name] = str(exc)
    return profiles


def _all_profiles() -> dict[str, DeviceProfile]:
    profiles = dict(_PROFILES)
    profiles.update(_plugin_profiles())
    return profiles


def get_device_profile(name: str) -> DeviceProfile:
    profiles = _all_profiles()
    try:
        return profiles[name]
    except KeyError as exc:
        supported = ", ".join(sorted(profiles))
        if _PLUGIN_LOAD_ERRORS:
            plugin_errors = "; ".join(
                f"{plugin}: {error}" for plugin, error in sorted(_PLUGIN_LOAD_ERRORS.items())
            )
            raise ValueError(
                f"Unsupported device {name!r}; choose one of: {supported}. "
                f"Device plugin load errors: {plugin_errors}"
            ) from exc
        raise ValueError(f"Unsupported device {name!r}; choose one of: {supported}") from exc


def list_device_profiles() -> list[DeviceProfile]:
    profiles = _all_profiles()
    return [profiles[name] for name in sorted(profiles)]


def plugin_load_errors() -> dict[str, str]:
    _plugin_profiles()
    return dict(_PLUGIN_LOAD_ERRORS)
