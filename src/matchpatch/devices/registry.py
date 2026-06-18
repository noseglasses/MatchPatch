"""Registry of built-in audio processor profiles."""

from __future__ import annotations

from matchpatch.devices.available import DEVICE_PROFILES
from matchpatch.devices.base import DeviceProfile


def _profiles_by_name() -> dict[str, DeviceProfile]:
    profiles: dict[str, DeviceProfile] = {}
    for profile in DEVICE_PROFILES:
        _validate_profile(profile)
        if profile.name in profiles:
            raise ValueError(f"duplicate device profile name {profile.name!r}")
        profiles[profile.name] = profile
    return profiles


def _validate_profile(profile: DeviceProfile) -> None:
    if not isinstance(getattr(profile, "name", None), str) or not profile.name:
        raise ValueError("device profile name must be a non-empty string")
    if not isinstance(getattr(profile, "display_name", None), str) or not profile.display_name:
        raise ValueError(f"device profile {profile.name!r} must define a display name")
    if not callable(getattr(profile, "create_patch_file_handler", None)):
        raise ValueError(f"device profile {profile.name!r} must create patch file handlers")


def get_device_profile(name: str) -> DeviceProfile:
    profiles = _profiles_by_name()
    try:
        return profiles[name]
    except KeyError as exc:
        supported = ", ".join(sorted(profiles))
        raise ValueError(f"Unsupported device {name!r}; choose one of: {supported}") from exc


def list_device_profiles() -> list[DeviceProfile]:
    profiles = _profiles_by_name()
    return [profiles[profile.name] for profile in DEVICE_PROFILES]
