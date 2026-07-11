from __future__ import annotations

from collections.abc import Iterable

from app.core.errors import UnsupportedCapabilityError
from app.drivers.base import DeviceDriver
from app.models import Vendor


class DriverRegistry:
    def __init__(self, drivers: Iterable[DeviceDriver]) -> None:
        self._drivers = {driver.vendor: driver for driver in drivers}

    def get(self, vendor: Vendor) -> DeviceDriver:
        try:
            return self._drivers[vendor]
        except KeyError as exc:
            raise UnsupportedCapabilityError(
                "No driver is registered for this vendor",
                details={"vendor": vendor.value},
            ) from exc

