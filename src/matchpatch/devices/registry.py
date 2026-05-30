"""Registry of audio processor profiles."""

from __future__ import annotations

from matchpatch.devices.base import DeviceProfile
from matchpatch.devices.helix import HelixDeviceProfile

_PROFILES: dict[str, DeviceProfile] = {
    "helix": HelixDeviceProfile(),
}


def get_device_profile(name: str) -> DeviceProfile:
    try:
        return _PROFILES[name]
    except KeyError as exc:
        supported = ", ".join(sorted(_PROFILES))
        raise ValueError(f"Unsupported device {name!r}; choose one of: {supported}") from exc


def list_device_profiles() -> list[DeviceProfile]:
    return [_PROFILES[name] for name in sorted(_PROFILES)]
