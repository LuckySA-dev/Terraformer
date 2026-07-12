from __future__ import annotations

from time import monotonic

from app.core.errors import (
    AppError,
    DriverAuthenticationError,
    DriverConnectionError,
    DriverTimeoutError,
)
from app.drivers.base import (
    ConnectionParameters,
    ConnectionTestResult,
    DeviceDriver,
    DriverCapability,
    DriverCapabilitySet,
    TransportFactory,
)
from app.models import SafetyLevel, Vendor


def translate_transport_error(exc: Exception) -> Exception:
    if isinstance(exc, AppError):
        return exc
    class_name = type(exc).__name__.lower()
    if "auth" in class_name:
        return DriverAuthenticationError()
    if "timeout" in class_name:
        return DriverTimeoutError()
    return DriverConnectionError()


class GenericReadOnlyDriver(DeviceDriver):
    vendor = Vendor.GENERIC
    name = "generic_readonly"

    def __init__(self, transport_factory: TransportFactory) -> None:
        self._transport_factory = transport_factory
        self._capabilities = DriverCapabilitySet(
            supported=frozenset({DriverCapability.CONNECT}),
            safety_level=SafetyLevel.READ_ONLY,
        )

    @property
    def capabilities(self) -> DriverCapabilitySet:
        return self._capabilities

    def test_connection(self, parameters: ConnectionParameters) -> ConnectionTestResult:
        started = monotonic()
        transport = self._transport_factory(parameters)
        try:
            transport.open()
        except Exception as exc:
            raise translate_transport_error(exc) from exc
        finally:
            try:
                transport.close()
            except Exception:  # noqa: S110 - close is best-effort and must not mask the operation
                pass
        return ConnectionTestResult(
            reachable=True,
            driver=self.name,
            message="SSH connection succeeded",
            latency_ms=max(0, int((monotonic() - started) * 1_000)),
        )
