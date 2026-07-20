from __future__ import annotations

from collections.abc import Iterator
from threading import Lock
from time import sleep

import pytest
from pydantic import ValidationError

from app.schemas.discovery import DiscoveryRequest
from app.services import discovery as discovery_service
from app.services.discovery import run_discovery


@pytest.mark.parametrize(
    "cidr",
    [
        "192.0.2.0/24",
        "127.0.0.0/30",
        "fe80::/126",
        "192.0.2.1/30",
        "0.0.0.0/30",
        "240.0.0.0/30",
    ],
)
def test_discovery_rejects_unsafe_or_unbounded_ranges(cidr: str) -> None:
    with pytest.raises(ValidationError):
        DiscoveryRequest(cidr=cidr)


def test_discovery_normalizes_ports_and_bounds_endpoint_count() -> None:
    request = DiscoveryRequest(cidr="192.0.2.0/26", ports=[22, 2222, 22, 23])

    assert request.ports == [22, 2222, 23]
    assert len(list(request.network().hosts())) * len(request.ports) <= 256


@pytest.mark.parametrize(
    "ports",
    [[], [22, 23, 2222, 2200, 2022], [0], [65_536]],
)
def test_discovery_rejects_unsafe_port_lists(ports: list[int]) -> None:
    with pytest.raises(ValidationError):
        DiscoveryRequest(cidr="192.0.2.0/30", ports=ports)


def test_discovery_caps_concurrency_and_classifies_endpoints() -> None:
    state = {"active": 0, "peak": 0}
    lock = Lock()

    def probe(address: str, port: int, timeout: float) -> str | None:
        assert port in {22, 23}
        assert timeout == 0.25
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        sleep(0.05)
        with lock:
            state["active"] -= 1
        if (address, port) == ("192.0.2.2", 22):
            return "ssh"
        if (address, port) == ("192.0.2.5", 23):
            return "open_tcp"
        return None

    result = run_discovery(
        DiscoveryRequest(
            cidr="192.0.2.0/29",
            ports=[22, 23],
            concurrency=5,
            connect_timeout_seconds=0.25,
            probe_delay_ms=10,
        ),
        connection_limit=2,
        probe=probe,
    )

    assert result["ports"] == [22, 23]
    assert result["scanned_count"] == 12
    assert result["concurrency"] == 2
    assert state["peak"] == 2
    assert result["candidates"] == [
        {"management_address": "192.0.2.2", "port": 22},
    ]
    assert result["open_endpoints"] == [
        {"management_address": "192.0.2.5", "port": 23},
    ]


class BannerSocket:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks: Iterator[bytes] = iter(chunks)

    def __enter__(self) -> BannerSocket:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def settimeout(self, _timeout: float) -> None:
        pass

    def recv(self, size: int) -> bytes:
        assert 0 < size <= 512
        return next(self._chunks, b"")

    def send(self, _data: bytes) -> int:
        raise AssertionError("discovery must not send bytes")

    def sendall(self, _data: bytes) -> None:
        raise AssertionError("discovery must not send bytes")


def probe_with_chunks(monkeypatch, chunks: list[bytes]) -> str | None:
    connection = BannerSocket(chunks)
    monkeypatch.setattr(
        discovery_service.socket,
        "create_connection",
        lambda *_args, **_kwargs: connection,
    )
    return discovery_service.tcp_service_probe("192.0.2.1", 22, 0.25)


def test_passive_probe_identifies_split_ssh_banner(monkeypatch) -> None:
    assert probe_with_chunks(monkeypatch, [b"SS", b"H-2.0-OpenSSH_fixture\r\n"]) == "ssh"


def test_passive_probe_keeps_non_ssh_banner_informational(monkeypatch) -> None:
    assert probe_with_chunks(monkeypatch, [b"220 fixture FTP service\r\n"]) == "open_tcp"
    assert probe_with_chunks(monkeypatch, [b""]) == "open_tcp"


def test_passive_probe_ignores_closed_endpoint(monkeypatch) -> None:
    def connection_refused(*_args: object, **_kwargs: object) -> None:
        raise ConnectionRefusedError

    monkeypatch.setattr(
        discovery_service.socket,
        "create_connection",
        connection_refused,
    )

    assert discovery_service.tcp_service_probe("192.0.2.1", 22, 0.25) is None


def test_passive_probe_keeps_read_failure_informational(monkeypatch) -> None:
    connection = BannerSocket([])

    def reset_during_read(_size: int) -> bytes:
        raise ConnectionResetError

    monkeypatch.setattr(connection, "recv", reset_during_read)
    monkeypatch.setattr(
        discovery_service.socket,
        "create_connection",
        lambda *_args, **_kwargs: connection,
    )

    assert discovery_service.tcp_service_probe("192.0.2.1", 22, 0.25) == "open_tcp"


def test_passive_probe_uses_one_absolute_deadline(monkeypatch) -> None:
    connection = BannerSocket([b"SS", b"H-2.0-too-late\r\n"])
    clock = iter([10.0, 10.1, 10.3])
    monkeypatch.setattr(discovery_service, "monotonic", lambda: next(clock))
    monkeypatch.setattr(
        discovery_service.socket,
        "create_connection",
        lambda *_args, **_kwargs: connection,
    )

    assert discovery_service.tcp_service_probe("192.0.2.1", 22, 0.25) == "open_tcp"
