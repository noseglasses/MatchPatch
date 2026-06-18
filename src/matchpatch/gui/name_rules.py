"""GUI adapters for device-owned preset and subdivision names."""

from __future__ import annotations

from collections.abc import Callable

from matchpatch.devices import get_device_profile
from matchpatch.gui.table_formatting import sanitize_helix_name, validate_helix_name


def profile_name_max_length(profile: object, attribute: str) -> int | None:
    naming_rules = getattr(profile, "naming_rules", None)
    source = naming_rules() if naming_rules is not None else profile
    value = getattr(source, attribute, None)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def device_name_max_length(device: object, attribute: str) -> int | None:
    profile = _profile_for_device(device)
    return None if profile is None else profile_name_max_length(profile, attribute)


def validate_preset_name_for_device(device: object, name: str) -> str:
    return _apply_name_rule(
        device,
        name,
        method_name="validate_preset_name",
        fallback=validate_helix_name,
        max_length_attribute="preset_name_max_length",
    )


def validate_subdivision_name_for_device(device: object, name: str) -> str:
    return _apply_name_rule(
        device,
        name,
        method_name="validate_subdivision_name",
        fallback=validate_helix_name,
        max_length_attribute="snapshot_name_max_length",
    )


def sanitize_preset_name_for_device(device: object, name: str) -> str:
    return _apply_name_rule(
        device,
        name,
        method_name="sanitize_preset_name",
        fallback=sanitize_helix_name,
        max_length_attribute="preset_name_max_length",
    )


def sanitize_subdivision_name_for_device(device: object, name: str) -> str:
    return _apply_name_rule(
        device,
        name,
        method_name="sanitize_subdivision_name",
        fallback=sanitize_helix_name,
        max_length_attribute="snapshot_name_max_length",
    )


def _apply_name_rule(
    device: object,
    name: str,
    *,
    method_name: str,
    fallback: Callable[[str, int | None], str],
    max_length_attribute: str,
) -> str:
    profile = _profile_for_device(device)
    method = getattr(profile, method_name, None) if profile is not None else None
    if method is not None:
        return method(name)
    max_length = None if profile is None else profile_name_max_length(profile, max_length_attribute)
    return fallback(name, max_length)


def _profile_for_device(device: object) -> object | None:
    if not device:
        return None
    try:
        return get_device_profile(str(device))
    except ValueError:
        return None
