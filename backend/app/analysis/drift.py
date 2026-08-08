"""Compare observed cabling against parsed configuration.

Deliberately narrow. CDP/LLDP report layer-2 neighbour and interface pairs,
while Batfish layer-3 edges report routed adjacencies; on a campus most observed
links are not layer-3 edges, so comparing those two would report large numbers
of false differences. Only two checks are made, both of which are answerable
from data the application actually holds:

1. An interface named in an observed link does not exist in the configuration.
2. The two ends of an observed link disagree on switchport mode or access VLAN.

Both describe the same real fault: cabled one way, configured another.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.analysis.client import InterfaceProperty, RawFinding
from app.analysis.types import Layer1Edge
from app.models import FindingCategory


def topology_drift_findings(
    edges: Sequence[Layer1Edge], properties: Sequence[InterfaceProperty]
) -> tuple[RawFinding, ...]:
    by_key = {(item.hostname.lower(), item.interface.lower()): item for item in properties}
    findings: list[RawFinding] = []

    for edge in edges:
        near = by_key.get((edge.node1_hostname.lower(), edge.node1_interface.lower()))
        far = by_key.get((edge.node2_hostname.lower(), edge.node2_interface.lower()))

        for hostname, interface, found in (
            (edge.node1_hostname, edge.node1_interface, near),
            (edge.node2_hostname, edge.node2_interface, far),
        ):
            if found is None:
                findings.append(
                    _drift(
                        hostname,
                        interface,
                        f"{interface} is reported by a neighbour discovery record"
                        " but does not appear in the parsed configuration",
                    )
                )
        if near is None or far is None:
            continue

        near_mode, far_mode = _mode(near), _mode(far)
        if near_mode != far_mode:
            findings.append(
                _drift(
                    edge.node1_hostname,
                    edge.node1_interface,
                    "Observed link ends disagree on switchport mode:"
                    f" {edge.node1_hostname} {edge.node1_interface} is {near_mode}"
                    f" and {edge.node2_hostname} {edge.node2_interface} is {far_mode}",
                )
            )
        elif (
            near_mode == "ACCESS"
            and near.access_vlan is not None
            and far.access_vlan is not None
            and near.access_vlan != far.access_vlan
        ):
            findings.append(
                _drift(
                    edge.node1_hostname,
                    edge.node1_interface,
                    "Observed link ends disagree on access VLAN:"
                    f" {edge.node1_hostname} {edge.node1_interface} uses"
                    f" {near.access_vlan} and {edge.node2_hostname}"
                    f" {edge.node2_interface} uses {far.access_vlan}",
                )
            )
    return tuple(findings)


def _drift(hostname: str, interface: str, detail: str) -> RawFinding:
    return RawFinding(
        category=FindingCategory.TOPOLOGY_DRIFT,
        hostname=hostname,
        structure_type="interface",
        structure_name=interface,
        detail=detail,
        line_number=None,
    )


def _mode(item: InterfaceProperty) -> str:
    return (item.switchport_mode or "UNKNOWN").upper()
