from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Literal, Never, Protocol

from app.core.errors import UnsupportedCapabilityError
from app.models import SafetyLevel, Vendor


class DriverCapability(StrEnum):
    CONNECT = "connect"
    FACTS = "facts"
    INTERFACES = "interfaces"
    NEIGHBORS = "neighbors"
    RUNNING_CONFIG = "running_config"
    ROUTING = "routing"
    ARP = "arp"
    MAC = "mac"
    RENDER = "render"
    VALIDATE = "validate"
    COMPARE = "compare"
    APPLY = "apply"
    POST_CHECK = "post_check"
    ROLLBACK = "rollback"


WRITE_CAPABILITIES = frozenset(
    {
        DriverCapability.RENDER,
        DriverCapability.VALIDATE,
        DriverCapability.COMPARE,
        DriverCapability.APPLY,
        DriverCapability.POST_CHECK,
        DriverCapability.ROLLBACK,
    }
)


@dataclass(frozen=True, slots=True)
class DriverCapabilitySet:
    supported: frozenset[DriverCapability]
    safety_level: SafetyLevel = SafetyLevel.READ_ONLY

    def __post_init__(self) -> None:
        if self.safety_level == SafetyLevel.READ_ONLY and self.supported & WRITE_CAPABILITIES:
            raise ValueError("A read-only driver cannot advertise write capabilities")

    def supports(self, capability: DriverCapability) -> bool:
        return capability in self.supported

    def records(self) -> list[dict[str, str | bool]]:
        return [
            {
                "name": capability.value,
                "supported": capability in self.supported,
                "safety_level": self.safety_level.value,
            }
            for capability in DriverCapability
        ]


@dataclass(frozen=True, slots=True)
class ConnectionParameters:
    host: str
    port: int
    username: str
    password: str
    enable_password: str | None = None
    connect_timeout_seconds: float = 10.0
    command_timeout_seconds: float = 30.0


@dataclass(frozen=True, slots=True)
class ConnectionTestResult:
    reachable: bool
    driver: str
    message: str
    latency_ms: int


@dataclass(frozen=True, slots=True)
class DeviceFacts:
    hostname: str | None = None
    vendor: str | None = None
    model: str | None = None
    serial_number: str | None = None
    os_version: str | None = None
    uptime: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass(frozen=True, slots=True)
class InterfaceFacts:
    name: str
    description: str | None = None
    admin_up: bool | None = None
    oper_up: bool | None = None
    mac_address: str | None = None
    ipv4_addresses: tuple[str, ...] = ()
    speed_mbps: int | None = None


type NeighborProtocol = Literal["cdp", "lldp"]


@dataclass(frozen=True, slots=True)
class NeighborFacts:
    protocol: NeighborProtocol
    local_interface: str
    remote_device_name: str
    remote_interface: str
    management_address: str | None = None
    platform: str | None = None


@dataclass(frozen=True, slots=True)
class DeviceObservations:
    facts: DeviceFacts
    interfaces: tuple[InterfaceFacts, ...]
    neighbors: tuple[NeighborFacts, ...]


class NetworkTransport(Protocol):
    def open(self) -> None: ...

    def close(self) -> None: ...

    def send_command(self, command: str) -> str: ...


class TransportFactory(Protocol):
    def __call__(self, parameters: ConnectionParameters) -> NetworkTransport: ...


class DeviceDriver(ABC):
    vendor: Vendor
    name: str

    @property
    @abstractmethod
    def capabilities(self) -> DriverCapabilitySet: ...

    @abstractmethod
    def test_connection(self, parameters: ConnectionParameters) -> ConnectionTestResult: ...

    def get_facts(self, parameters: ConnectionParameters) -> DeviceFacts:
        self._unsupported(DriverCapability.FACTS)

    def get_interfaces(self, parameters: ConnectionParameters) -> list[InterfaceFacts]:
        self._unsupported(DriverCapability.INTERFACES)

    def get_neighbors(self, parameters: ConnectionParameters) -> list[NeighborFacts]:
        self._unsupported(DriverCapability.NEIGHBORS)

    def collect_observations(self, parameters: ConnectionParameters) -> DeviceObservations:
        return DeviceObservations(
            facts=self.get_facts(parameters),
            interfaces=tuple(self.get_interfaces(parameters)),
            neighbors=tuple(self.get_neighbors(parameters)),
        )

    def get_running_config(self, parameters: ConnectionParameters) -> str:
        self._unsupported(DriverCapability.RUNNING_CONFIG)

    def apply_configuration(self, parameters: ConnectionParameters, commands: list[str]) -> None:
        del parameters, commands
        self._unsupported(DriverCapability.APPLY)

    def rollback(self, parameters: ConnectionParameters) -> None:
        del parameters
        self._unsupported(DriverCapability.ROLLBACK)

    def _unsupported(self, capability: DriverCapability) -> Never:
        raise UnsupportedCapabilityError(
            details={"driver": self.name, "capability": capability.value}
        )
