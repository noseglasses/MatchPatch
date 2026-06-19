"""Built-in device profile registration.

Adding a device should stay intentionally boring:

1. Create a sibling package under ``matchpatch.devices``.
2. Implement a ``DeviceProfile`` there.
3. Instantiate it in ``DEVICE_PROFILES`` below.

The registry reads only this list. There is no dynamic discovery layer.
"""

from __future__ import annotations

from matchpatch.devices.base import DeviceProfile
from matchpatch.devices.demo import DemoDeviceProfile
from matchpatch.devices.line6.helix import HelixDeviceProfile
from matchpatch.devices.line6.podgo import PodGoDeviceProfile

DEVICE_PROFILES: tuple[DeviceProfile, ...] = (
    HelixDeviceProfile(),
    PodGoDeviceProfile(),
    DemoDeviceProfile(),
)
