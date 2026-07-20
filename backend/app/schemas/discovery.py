from __future__ import annotations

from ipaddress import IPv4Network, ip_network
from typing import Annotated, cast

from pydantic import Field, field_validator

from app.schemas.common import APIModel

_MAX_DISCOVERY_ADDRESSES = 64
Port = Annotated[int, Field(ge=1, le=65_535)]


class DiscoveryRequest(APIModel):
    cidr: str
    ports: list[Port] = Field(default_factory=lambda: [22], min_length=1, max_length=4)
    concurrency: int = Field(default=4, ge=1, le=10)
    connect_timeout_seconds: float = Field(default=0.5, gt=0, le=5)
    probe_delay_ms: int = Field(default=50, ge=10, le=1_000)

    @field_validator("ports", mode="before")
    @classmethod
    def normalize_ports(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        normalized: list[object] = []
        for port in cast(list[object], value):
            if port not in normalized:
                normalized.append(port)
        return normalized

    @field_validator("cidr")
    @classmethod
    def validate_cidr(cls, value: str) -> str:
        try:
            network = ip_network(value.strip(), strict=True)
        except ValueError as exc:
            raise ValueError("cidr must be an exact IPv4 network") from exc
        if not isinstance(network, IPv4Network):
            raise ValueError("only IPv4 discovery is implemented")
        if network.num_addresses > _MAX_DISCOVERY_ADDRESSES:
            raise ValueError("cidr may contain at most 64 addresses")
        if (
            network.is_loopback
            or network.is_link_local
            or network.is_multicast
            or network.network_address.is_unspecified
            or network.network_address.is_reserved
        ):
            raise ValueError("non-routable special-purpose discovery is blocked")
        return str(network)

    def network(self) -> IPv4Network:
        network = ip_network(self.cidr, strict=True)
        if not isinstance(network, IPv4Network):  # pragma: no cover - validator guarantees this
            raise ValueError("only IPv4 discovery is implemented")
        return network


class DiscoveryCandidate(APIModel):
    management_address: str
    port: int


class DiscoveryResult(APIModel):
    cidr: str
    ports: list[int]
    scanned_count: int
    concurrency: int
    candidates: list[DiscoveryCandidate]
    open_endpoints: list[DiscoveryCandidate]
