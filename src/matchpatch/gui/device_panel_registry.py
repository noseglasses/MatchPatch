"""GUI-only registry for optional device settings panel plugins."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from importlib import metadata
from typing import Any, Protocol

from PySide6.QtWidgets import QWidget

from matchpatch.devices.base import DeviceProfile

ENTRY_POINT_GROUP = "matchpatch.device_gui_panels"

_LOG = logging.getLogger(__name__)
_PLUGIN_LOAD_ERRORS: dict[str, str] = {}


class DevicePanelFactory(Protocol):
    device_name: str

    def create_panel(self, profile: DeviceProfile, backend_selector: QWidget) -> QWidget | None: ...


def _entry_points() -> Iterable[metadata.EntryPoint]:
    entry_points = metadata.entry_points()
    if hasattr(entry_points, "select"):
        return entry_points.select(group=ENTRY_POINT_GROUP)
    return entry_points.get(ENTRY_POINT_GROUP, ())


def _panel_factory_from_loaded(value: Any) -> DevicePanelFactory:  # noqa: ANN401
    factory = value
    if not _has_factory_shape(factory) and callable(value):
        factory = value()
    if not _has_factory_shape(factory):
        raise TypeError("device GUI panel entry point must define device_name and create_panel")
    return factory


def _has_factory_shape(value: object) -> bool:
    return isinstance(getattr(value, "device_name", None), str) and callable(
        getattr(value, "create_panel", None)
    )


def create_plugin_settings_panel(
    profile: DeviceProfile,
    backend_selector: QWidget,
) -> QWidget | None:
    _PLUGIN_LOAD_ERRORS.clear()
    for entry_point in _entry_points():
        try:
            factory = _panel_factory_from_loaded(entry_point.load())
            if factory.device_name == profile.name:
                return factory.create_panel(profile, backend_selector)
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            _PLUGIN_LOAD_ERRORS[entry_point.name] = message
            _LOG.warning("Device GUI panel plugin %s failed to load: %s", entry_point.name, message)
    return None


def plugin_load_errors() -> dict[str, str]:
    return dict(_PLUGIN_LOAD_ERRORS)
