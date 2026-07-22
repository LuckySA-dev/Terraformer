from __future__ import annotations

from time import monotonic

from app.core.errors import AppError
from app.drivers.base import (
    ConnectionParameters,
    ConnectionTestResult,
    DeviceDriver,
    DriverCapability,
    DriverCapabilitySet,
    NetworkTransport,
    TransportFactory,
)
from app.drivers.ssh_errors import ConnectionPhase, translate_ssh_error
from app.models import SafetyLevel, Vendor


def translate_transport_error(exc: Exception, *, phase: ConnectionPhase) -> AppError:
    return translate_ssh_error(exc, phase=phase)


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
        transport: NetworkTransport | None = None
        try:
            transport = self._transport_factory(parameters)
            transport.open()
        except Exception as exc:
            raise translate_transport_error(exc, phase=ConnectionPhase.TCP) from None
        finally:
            if transport is not None:
                try:
                    transport.close()
                except Exception:  # noqa: S110 - close must not mask the operation
                    pass
        return ConnectionTestResult(
            reachable=True,
            driver=self.name,
            message="SSH connection succeeded",
            latency_ms=max(0, int((monotonic() - started) * 1_000)),
        )
