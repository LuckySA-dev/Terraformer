"""Assemble the configuration set and layer-1 topology for one analysis.

Deliberately free of Batfish and of database session handling: callers supply
already-resolved devices, snapshots and sanitized content. That keeps the
classification rules — which decide what the completeness disclosure reports —
testable without a container or a database.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from uuid import UUID

from app.analysis.types import AnalysisInput, DeviceConfig, ExcludedDevice, Layer1Edge
from app.core.errors import AnalysisTooManyDevicesError
from app.models import ConfigSnapshot, Device, ExclusionReason, Neighbor, Vendor

# Batfish can parse Cisco IOS/IOS-XE. FortiOS support is limited and the generic
# driver reads nothing, so both are excluded rather than parsed badly.
SUPPORTED_VENDORS = frozenset({Vendor.CISCO_IOSXE})

_HOSTNAME = re.compile(r"^\s*hostname\s+(\S+)\s*$", re.MULTILINE)
_UNSAFE_HOSTNAME_CHARS = re.compile(r"[^a-z0-9._-]+")

# Typed against the concrete ORM models rather than a Protocol: pyright only
# checks app/ (see [tool.pyright] include in pyproject.toml), so the unit
# tests' lightweight duck-typed fakes never need to satisfy these signatures
# statically, and Device.id etc. being Mapped[X] descriptors never becomes an
# issue here.


def batfish_hostname(config: str, *, fallback: str) -> str:
    """Return the node name Batfish will use for this configuration.

    Batfish keys nodes on the configured hostname, lowercased. Reading it from
    the configuration rather than from collected facts avoids a mismatch when
    the two disagree: the configuration is what Batfish actually parses.
    """
    match = _HOSTNAME.search(config)
    raw = match.group(1) if match is not None else fallback
    return _UNSAFE_HOSTNAME_CHARS.sub("-", raw.strip().lower()).strip("-")


def build_analysis_input(
    *,
    devices: Iterable[Device],
    latest_snapshot_for: Mapping[UUID, ConfigSnapshot],
    sanitized_content_for: Mapping[UUID, str],
    neighbors: Sequence[Neighbor],
    max_devices: int,
) -> AnalysisInput:
    device_list = list(devices)
    included = [
        device
        for device in device_list
        if device.vendor in SUPPORTED_VENDORS and device.id in latest_snapshot_for
    ]
    if len(included) > max_devices:
        # A typed AppError, not ValueError: AnalysisService.initialise only
        # converts AppError into a failed status, so an untyped exception here
        # would strand the snapshot in `parsing` and surface as a 500.
        raise AnalysisTooManyDevicesError(
            f"{len(included)} devices exceeds the analysis device bound of {max_devices}"
        )

    configs: list[DeviceConfig] = []
    excluded: list[ExcludedDevice] = []
    for device in device_list:
        if device.vendor not in SUPPORTED_VENDORS:
            excluded.append(ExcludedDevice(device.id, ExclusionReason.UNSUPPORTED_VENDOR))
            continue
        snapshot = latest_snapshot_for.get(device.id)
        if snapshot is None:
            excluded.append(ExcludedDevice(device.id, ExclusionReason.NO_SNAPSHOT))
            continue
        content = sanitized_content_for.get(device.id, "")
        configs.append(
            DeviceConfig(
                device_id=device.id,
                config_snapshot_id=snapshot.id,
                batfish_hostname=batfish_hostname(content, fallback=device.name),
                content=content,
                captured_at=snapshot.created_at,
            )
        )

    captured = [item.captured_at for item in configs]
    return AnalysisInput(
        configs=tuple(configs),
        excluded=tuple(excluded),
        layer1_edges=_layer1_edges(configs, neighbors),
        oldest_config_at=min(captured) if captured else None,
        newest_config_at=max(captured) if captured else None,
    )


def _layer1_edges(
    configs: Sequence[DeviceConfig], neighbors: Sequence[Neighbor]
) -> tuple[Layer1Edge, ...]:
    """Derive layer-1 edges from observed neighbours.

    Batfish accepts a layer-1 topology as snapshot input. Supplying observed
    CDP/LLDP links is what makes reachability meaningful on a switched campus,
    where most access ports carry no layer-3 address for Batfish to infer
    adjacency from.

    Only links whose both ends are in the analysed set can become edges: an edge
    naming a node Batfish has never seen would be silently ignored at best.
    """
    hostname_by_device = {item.device_id: item.batfish_hostname for item in configs}
    analysed_hostnames = set(hostname_by_device.values())

    edges: set[Layer1Edge] = set()
    for neighbor in neighbors:
        local = hostname_by_device.get(neighbor.device_id)
        if local is None:
            continue
        remote = batfish_hostname("", fallback=neighbor.remote_device_name)
        # CDP often reports a fully qualified name; Batfish uses the short one.
        remote = remote.split(".", 1)[0]
        if remote not in analysed_hostnames:
            continue
        edges.add(
            Layer1Edge(
                node1_hostname=local,
                node1_interface=neighbor.local_interface,
                node2_hostname=remote,
                node2_interface=neighbor.remote_interface,
            )
        )
    return tuple(sorted(edges, key=lambda edge: (edge.node1_hostname, edge.node1_interface)))
