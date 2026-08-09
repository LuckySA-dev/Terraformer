from __future__ import annotations

import os

import pytest

from app.changes.types import ChangeStepIntent
from app.drivers import CiscoIOSXEDriver, ConnectionParameters
from app.drivers.transport import ScrapliTransportFactory
from app.models import ChangeType

pytestmark = [
    pytest.mark.lab,
    pytest.mark.skipif(
        os.getenv("RUN_LAB_TESTS") != "1",
        reason="Set RUN_LAB_TESTS=1 explicitly to enable read-only lab access",
    ),
]


def test_apply_and_rollback_an_interface_description_on_a_real_lab_device() -> None:
    """Requires LAB_DEVICE_* vars (see test_cisco_iosxe_lab.py) plus
    LAB_TARGET_INTERFACE naming a real, currently-unused interface on that
    device -- never point this at a live uplink."""
    required = (
        "LAB_DEVICE_HOST",
        "LAB_DEVICE_USERNAME",
        "LAB_DEVICE_PASSWORD",
        "LAB_KNOWN_HOSTS_FILE",
        "LAB_TARGET_INTERFACE",
    )
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        pytest.skip(f"Missing opt-in lab variables: {', '.join(missing)}")
    if os.getenv("LAB_EXPECTED_PLATFORM") != "cisco_iosxe":
        pytest.fail("Set LAB_EXPECTED_PLATFORM=cisco_iosxe before opening a lab connection")

    host = os.environ["LAB_DEVICE_HOST"]
    port = int(os.getenv("LAB_DEVICE_PORT", "22"))
    known_hosts = open(os.environ["LAB_KNOWN_HOSTS_FILE"], encoding="utf-8").read()
    entries = [line for line in known_hosts.splitlines() if line and not line.startswith("#")]
    target = os.environ["LAB_TARGET_INTERFACE"]

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

    before = next(iface for iface in driver.get_interfaces(parameters) if iface.name == target)

    step = ChangeStepIntent(
        change_type=ChangeType.INTERFACE_DESCRIPTION,
        target=target,
        desired_value="terraformer-phase3-lab-check",
    )
    rendered = driver.render_change(step, before)
    assert driver.validate_change(step, before) == []

    driver.apply_configuration(parameters, list(rendered.commands))
    after = next(iface for iface in driver.get_interfaces(parameters) if iface.name == target)
    assert after.description == "terraformer-phase3-lab-check"

    driver.rollback(parameters, list(rendered.inverse_commands))
    restored = next(iface for iface in driver.get_interfaces(parameters) if iface.name == target)
    assert restored.description == before.description
