from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.analysis.snapshot_builder import batfish_hostname, build_analysis_input
from app.analysis.types import Layer1Edge
from app.models import ExclusionReason, Vendor


class FakeDevice:
    def __init__(self, name: str, vendor: Vendor) -> None:
        self.id = uuid4()
        self.name = name
        self.vendor = vendor


def _snapshot(device_id: UUID, captured_at: datetime) -> object:
    return type(
        "Snap", (), {"id": uuid4(), "device_id": device_id, "created_at": captured_at}
    )()


def test_hostname_comes_from_the_configuration_not_the_record() -> None:
    """Batfish keys nodes on the configured hostname, lowercased."""
    config = "!\nversion 15.2\nhostname Core-SW-01\n!\n"
    assert batfish_hostname(config, fallback="whatever") == "core-sw-01"


def test_hostname_falls_back_when_the_configuration_has_none() -> None:
    assert batfish_hostname("!\nversion 15.2\n!\n", fallback="Edge Router") == "edge-router"


def test_unsupported_vendors_are_recorded_as_exclusions_not_dropped() -> None:
    cisco = FakeDevice("sw1", Vendor.CISCO_IOSXE)
    forti = FakeDevice("fw1", Vendor.FORTINET_FORTIOS)
    generic = FakeDevice("box", Vendor.GENERIC)
    now = datetime.now(UTC)

    result = build_analysis_input(
        devices=[cisco, forti, generic],
        latest_snapshot_for={cisco.id: _snapshot(cisco.id, now)},
        sanitized_content_for={},
        neighbors=[],
        max_devices=200,
    )

    assert len(result.configs) == 1
    reasons = {item.device_id: item.reason for item in result.excluded}
    assert reasons[forti.id] is ExclusionReason.UNSUPPORTED_VENDOR
    assert reasons[generic.id] is ExclusionReason.UNSUPPORTED_VENDOR


def test_devices_without_a_snapshot_are_recorded_as_exclusions() -> None:
    with_snap = FakeDevice("sw1", Vendor.CISCO_IOSXE)
    without = FakeDevice("sw2", Vendor.CISCO_IOSXE)
    now = datetime.now(UTC)

    result = build_analysis_input(
        devices=[with_snap, without],
        latest_snapshot_for={with_snap.id: _snapshot(with_snap.id, now)},
        sanitized_content_for={},
        neighbors=[],
        max_devices=200,
    )

    assert [item.reason for item in result.excluded] == [ExclusionReason.NO_SNAPSHOT]
    assert [item.device_id for item in result.excluded] == [without.id]


def test_layer1_edges_only_include_links_where_both_ends_are_analysed() -> None:
    """A neighbour whose remote device is excluded cannot form an edge."""
    sw1 = FakeDevice("sw1", Vendor.CISCO_IOSXE)
    sw2 = FakeDevice("sw2", Vendor.CISCO_IOSXE)
    now = datetime.now(UTC)
    neighbours = [
        type(
            "N",
            (),
            {
                "device_id": sw1.id,
                "local_interface": "GigabitEthernet0/1",
                "remote_device_name": "SW2",
                "remote_interface": "GigabitEthernet0/2",
            },
        )(),
        type(
            "N",
            (),
            {
                "device_id": sw1.id,
                "local_interface": "GigabitEthernet0/3",
                "remote_device_name": "unknown-box",
                "remote_interface": "eth0",
            },
        )(),
    ]

    result = build_analysis_input(
        devices=[sw1, sw2],
        latest_snapshot_for={
            sw1.id: _snapshot(sw1.id, now),
            sw2.id: _snapshot(sw2.id, now),
        },
        sanitized_content_for={sw1.id: "hostname sw1\n", sw2.id: "hostname sw2\n"},
        neighbors=neighbours,
        max_devices=200,
    )

    assert result.layer1_edges == (
        Layer1Edge("sw1", "GigabitEthernet0/1", "sw2", "GigabitEthernet0/2"),
    )


def test_config_age_range_is_reported() -> None:
    sw1 = FakeDevice("sw1", Vendor.CISCO_IOSXE)
    sw2 = FakeDevice("sw2", Vendor.CISCO_IOSXE)
    old = datetime(2026, 8, 1, tzinfo=UTC)
    new = datetime(2026, 8, 7, tzinfo=UTC)

    result = build_analysis_input(
        devices=[sw1, sw2],
        latest_snapshot_for={sw1.id: _snapshot(sw1.id, old), sw2.id: _snapshot(sw2.id, new)},
        sanitized_content_for={sw1.id: "hostname sw1\n", sw2.id: "hostname sw2\n"},
        neighbors=[],
        max_devices=200,
    )

    assert result.oldest_config_at == old
    assert result.newest_config_at == new


def test_device_count_over_the_bound_is_rejected() -> None:
    devices = [FakeDevice(f"sw{index}", Vendor.CISCO_IOSXE) for index in range(3)]
    now = datetime.now(UTC)

    with pytest.raises(ValueError, match="exceeds the analysis device bound"):
        build_analysis_input(
            devices=devices,
            latest_snapshot_for={item.id: _snapshot(item.id, now) for item in devices},
            sanitized_content_for={item.id: f"hostname {item.name}\n" for item in devices},
            neighbors=[],
            max_devices=2,
        )
