from __future__ import annotations

from threading import Lock
from time import sleep

import pytest
from pydantic import ValidationError

from app.schemas.discovery import DiscoveryRequest
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


def test_discovery_caps_concurrency_and_returns_only_open_candidates() -> None:
    state = {"active": 0, "peak": 0}
    lock = Lock()

    def probe(address: str, port: int, timeout: float) -> bool:
        assert port == 22
        assert timeout == 0.25
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        sleep(0.05)
        with lock:
            state["active"] -= 1
        return address in {"192.0.2.2", "192.0.2.5"}

    result = run_discovery(
        DiscoveryRequest(
            cidr="192.0.2.0/29",
            concurrency=5,
            connect_timeout_seconds=0.25,
            probe_delay_ms=10,
        ),
        connection_limit=2,
        probe=probe,
    )

    assert result["scanned_count"] == 6
    assert result["concurrency"] == 2
    assert state["peak"] == 2
    assert result["candidates"] == [
        {"management_address": "192.0.2.2", "port": 22},
        {"management_address": "192.0.2.5", "port": 22},
    ]
