from __future__ import annotations

from app.analysis.client import InterfaceProperty
from app.analysis.drift import topology_drift_findings
from app.analysis.types import Layer1Edge
from app.models import FindingCategory


def _edge() -> Layer1Edge:
    return Layer1Edge("sw1", "GigabitEthernet0/1", "sw2", "GigabitEthernet0/2")


def test_interface_seen_by_cdp_but_absent_from_configuration_is_reported() -> None:
    properties = [InterfaceProperty("sw2", "GigabitEthernet0/2", "ACCESS", 10)]

    findings = topology_drift_findings([_edge()], properties)

    assert len(findings) == 1
    assert findings[0].category is FindingCategory.TOPOLOGY_DRIFT
    assert "GigabitEthernet0/1" in findings[0].detail
    assert findings[0].hostname == "sw1"


def test_matching_access_vlans_produce_no_finding() -> None:
    properties = [
        InterfaceProperty("sw1", "GigabitEthernet0/1", "ACCESS", 10),
        InterfaceProperty("sw2", "GigabitEthernet0/2", "ACCESS", 10),
    ]

    assert topology_drift_findings([_edge()], properties) == ()


def test_access_vlan_mismatch_across_an_observed_link_is_reported() -> None:
    properties = [
        InterfaceProperty("sw1", "GigabitEthernet0/1", "ACCESS", 10),
        InterfaceProperty("sw2", "GigabitEthernet0/2", "ACCESS", 20),
    ]

    findings = topology_drift_findings([_edge()], properties)

    assert len(findings) == 1
    assert "access VLAN" in findings[0].detail
    assert "10" in findings[0].detail and "20" in findings[0].detail


def test_switchport_mode_mismatch_across_an_observed_link_is_reported() -> None:
    properties = [
        InterfaceProperty("sw1", "GigabitEthernet0/1", "ACCESS", 10),
        InterfaceProperty("sw2", "GigabitEthernet0/2", "TRUNK", None),
    ]

    findings = topology_drift_findings([_edge()], properties)

    assert len(findings) == 1
    assert "switchport mode" in findings[0].detail


def test_no_edges_produce_no_findings() -> None:
    assert topology_drift_findings([], []) == ()
