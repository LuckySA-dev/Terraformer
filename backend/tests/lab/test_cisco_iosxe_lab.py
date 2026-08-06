from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.drivers import CiscoIOSXEDriver, ConnectionParameters
from app.drivers.transport import ScrapliTransportFactory

pytestmark = [
    pytest.mark.lab,
    pytest.mark.skipif(
        os.getenv("RUN_LAB_TESTS") != "1",
        reason="Set RUN_LAB_TESTS=1 explicitly to enable read-only lab access",
    ),
]


def test_read_only_cisco_observations_from_opt_in_lab() -> None:
    required = (
        "LAB_DEVICE_HOST",
        "LAB_DEVICE_USERNAME",
        "LAB_DEVICE_PASSWORD",
        "LAB_KNOWN_HOSTS_FILE",
    )
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        pytest.skip(f"Missing opt-in lab variables: {', '.join(missing)}")
    if os.getenv("LAB_EXPECTED_PLATFORM") != "cisco_iosxe":
        pytest.fail("Set LAB_EXPECTED_PLATFORM=cisco_iosxe before opening a lab connection")
    host = os.environ["LAB_DEVICE_HOST"]
    port = int(os.getenv("LAB_DEVICE_PORT", "22"))
    known_hosts = Path(os.environ["LAB_KNOWN_HOSTS_FILE"]).read_text(encoding="utf-8")
    entries = [line for line in known_hosts.splitlines() if line and not line.startswith("#")]
    expected_endpoint = host if port == 22 else f"[{host}]:{port}"
    if len(entries) != 1 or entries[0].split(maxsplit=1)[0] != expected_endpoint:
        pytest.fail("LAB_KNOWN_HOSTS_FILE must contain exactly the selected device endpoint")
    driver = CiscoIOSXEDriver(ScrapliTransportFactory())
    parameters = ConnectionParameters(
        host=host,
        port=port,
        username=os.environ["LAB_DEVICE_USERNAME"],
        password=os.environ["LAB_DEVICE_PASSWORD"],
        known_hosts=entries[0] + "\n",
        enable_password=os.getenv("LAB_DEVICE_ENABLE_PASSWORD"),
        connect_timeout_seconds=10,
        command_timeout_seconds=30,
    )
    connection = driver.test_connection(parameters)
    observations = driver.collect_observations(parameters)
    running_config = driver.get_running_config(parameters)

    assert connection.reachable is True
    assert observations.facts.vendor == "Cisco"
    assert observations.facts.hostname
    assert observations.interfaces
    assert all(interface.name for interface in observations.interfaces)
    assert all(
        neighbor.local_interface and neighbor.remote_device_name
        for neighbor in observations.neighbors
    )
    assert running_config.strip()
