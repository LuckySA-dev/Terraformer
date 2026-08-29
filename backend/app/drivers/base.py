from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Literal, Never, Protocol

from app.changes.types import ChangeStepIntent, RenderedChange, same_interface
from app.core.errors import UnsupportedCapabilityError
from app.models import SafetyLevel, SSHCompatibility, Vendor


class DriverCapability(StrEnum):
    CONNECT = "connect"
    FACTS = "facts"
    INTERFACES = "interfaces"
    NEIGHBORS = "neighbors"
    RUNNING_CONFIG = "running_config"
    ROUTING = "routing"
    ARP = "arp"
    MAC = "mac"
    PING = "ping"
    TRACEROUTE = "traceroute"
    RENDER = "render"
    VALIDATE = "validate"
    COMPARE = "compare"
    APPLY = "apply"
    POST_CHECK = "post_check"
    ROLLBACK = "rollback"
    # Persists running-config to startup-config. A write, but not a change:
    # it alters no running state, has no inverse, and is an exec command
    # rather than a configuration one -- so it is its own capability instead
    # of a ChangeType.
    SAVE_CONFIG = "save_config"


class DiagnosticAction(StrEnum):
    ROUTING_TABLE = "routing_table"
    ARP_TABLE = "arp_table"
    MAC_TABLE = "mac_table"
    PING = "ping"
    TRACEROUTE = "traceroute"


DIAGNOSTIC_CAPABILITIES = {
    DiagnosticAction.ROUTING_TABLE: DriverCapability.ROUTING,
    DiagnosticAction.ARP_TABLE: DriverCapability.ARP,
    DiagnosticAction.MAC_TABLE: DriverCapability.MAC,
    DiagnosticAction.PING: DriverCapability.PING,
    DiagnosticAction.TRACEROUTE: DriverCapability.TRACEROUTE,
}


WRITE_CAPABILITIES = frozenset(
    {
        DriverCapability.RENDER,
        DriverCapability.VALIDATE,
        DriverCapability.COMPARE,
        DriverCapability.APPLY,
        DriverCapability.POST_CHECK,
        DriverCapability.ROLLBACK,
        DriverCapability.SAVE_CONFIG,
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
    known_hosts: str = ""
    enable_password: str | None = None
    connect_timeout_seconds: float = 10.0
    command_timeout_seconds: float = 30.0
    ssh_compatibility: SSHCompatibility = SSHCompatibility.MODERN


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


@dataclass(frozen=True, slots=True)
class VlanFacts:
    """One row of the device's VLAN database.

    `ports` is the access-port membership the device itself reports, which is
    what makes a single `show vlan brief` enough to answer both "what is this
    VLAN called" and "which VLAN is this port in".
    """

    vlan_id: int
    name: str
    status: str
    ports: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SwitchportFacts:
    """One port's layer-2 configuration, as the device itself reports it.

    `show vlan brief` answers access-port membership but says nothing about a
    trunk. This is the one read that carries the administrative mode, the
    native VLAN and the allowed list together, which is what an allowed-VLAN
    change needs both to render its inverse and to refuse a port that is not
    a trunk.
    """

    name: str
    #: The administrative mode verbatim: "trunk", "static access",
    #: "dynamic auto", "dynamic desirable". Not normalised -- the inverse has
    #: to put back exactly what was there.
    mode: str
    access_vlan: int | None = None
    native_vlan: int | None = None
    #: The allowed list as IOS writes it ("ALL", "1-5,10,20"). Kept as text
    #: because that is the form the inverse command needs; expanding it to a
    #: set and rebuilding it would risk handing the device a different list
    #: than the one it had.
    trunk_allowed: str | None = None
    #: "dot1q" or "negotiate". Platforms that support ISL report "negotiate"
    #: until told otherwise and refuse `switchport mode trunk` while they do;
    #: platforms that only speak dot1q report it and reject the command that
    #: would set it. So it decides whether that command is sent at all.
    trunk_encapsulation: str | None = None

    def is_trunk(self) -> bool:
        return self.mode == "trunk"


@dataclass(frozen=True, slots=True)
class StaticRouteFacts:
    """One `ip route` line, split into the parts a change has to compare.

    Read from the running configuration rather than the routing table: a
    static route that is currently inactive (its next hop unreachable) is
    absent from `show ip route` but is still configured, and rolling back to
    "no route" when one was really there would lose it.
    """

    destination: str
    mask: str
    next_hop: str
    #: The configuration line exactly as the device printed it. The inverse is
    #: built from this rather than reassembled from the fields above, so a
    #: route carrying trailing options this parser does not model -- an
    #: administrative distance, `name`, `tag`, `permanent` -- is restored with
    #: them intact instead of silently losing them.
    raw: str = ""

    def as_command(self) -> str:
        return self.raw or f"ip route {self.destination} {self.mask} {self.next_hop}"


@dataclass(frozen=True, slots=True)
class ChangeContext:
    """The device state a change is rendered and validated against.

    An interface alone stopped being enough once VLANs arrived: renaming a
    VLAN targets the VLAN database and touches no interface, while moving an
    access port needs both the port and the VLAN table it moves between.
    `interface` is therefore optional, and each renderer asserts what it needs.
    """

    interface: InterfaceFacts | None = None
    vlans: tuple[VlanFacts, ...] = ()
    switchports: tuple[SwitchportFacts, ...] = ()
    static_routes: tuple[StaticRouteFacts, ...] = ()
    # What the device currently calls itself. Only a global change needs it,
    # and it is the sole source for that change's inverse.
    hostname: str | None = None

    def access_vlan_of(self, interface_name: str) -> VlanFacts | None:
        """Which VLAN currently holds this access port, per the device."""
        for vlan in self.vlans:
            if any(same_interface(port, interface_name) for port in vlan.ports):
                return vlan
        return None

    def vlan(self, vlan_id: int) -> VlanFacts | None:
        return next((vlan for vlan in self.vlans if vlan.vlan_id == vlan_id), None)

    def static_route(self, destination: str, mask: str) -> StaticRouteFacts | None:
        """The configured route for exactly this prefix, if there is one.

        Matched on destination and mask alone: two routes for the same prefix
        with different next hops are alternatives to each other, and replacing
        one means removing it, not adding beside it.
        """
        return next(
            (
                route
                for route in self.static_routes
                if route.destination == destination and route.mask == mask
            ),
            None,
        )

    def switchport_of(self, interface_name: str) -> SwitchportFacts | None:
        """This port's layer-2 configuration, matched on the short/long name."""
        return next(
            (port for port in self.switchports if same_interface(port.name, interface_name)),
            None,
        )


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


class ConfigurableTransport(NetworkTransport, Protocol):
    """A transport that can push a batch of config-mode commands.

    Deliberately not part of NetworkTransport itself: ScrapliGenericTransport
    wraps scrapli's GenericDriver, which has no config-mode/privilege-level
    model at all (confirmed -- 'send_configs' is not in its method list), so
    it cannot satisfy this even in principle. Only vendor drivers that
    declare DriverCapability.APPLY need a factory that produces one of these.
    """

    def send_config(self, commands: Sequence[str]) -> str: ...


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

    def run_diagnostic(
        self,
        parameters: ConnectionParameters,
        action: DiagnosticAction,
        target: str | None = None,
    ) -> str:
        del parameters, target
        self._unsupported(DIAGNOSTIC_CAPABILITIES[action])

    def get_vlans(self, parameters: ConnectionParameters) -> list[VlanFacts]:
        self._unsupported(DriverCapability.INTERFACES)

    def get_switchports(self, parameters: ConnectionParameters) -> list[SwitchportFacts]:
        self._unsupported(DriverCapability.INTERFACES)

    def get_static_routes(self, parameters: ConnectionParameters) -> list[StaticRouteFacts]:
        self._unsupported(DriverCapability.ROUTING)

    def render_change(self, step: ChangeStepIntent, context: ChangeContext) -> RenderedChange:
        del step, context
        self._unsupported(DriverCapability.RENDER)

    def validate_change(self, step: ChangeStepIntent, context: ChangeContext) -> list[str]:
        del step, context
        self._unsupported(DriverCapability.VALIDATE)

    def apply_configuration(self, parameters: ConnectionParameters, commands: list[str]) -> None:
        del parameters, commands
        self._unsupported(DriverCapability.APPLY)

    def save_configuration(self, parameters: ConnectionParameters) -> str:
        """Persist running-config to startup-config; returns the device's reply."""
        self._unsupported(DriverCapability.SAVE_CONFIG)

    def rollback(self, parameters: ConnectionParameters, commands: list[str]) -> None:
        del parameters, commands
        self._unsupported(DriverCapability.ROLLBACK)

    def _unsupported(self, capability: DriverCapability) -> Never:
        raise UnsupportedCapabilityError(
            details={"driver": self.name, "capability": capability.value}
        )
