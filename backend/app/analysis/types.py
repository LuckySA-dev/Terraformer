"""Types shared across the analysis package.

No Batfish or pandas type appears here or crosses this package's boundary. The
rest of the application depends on these dataclasses only, so the analysis
backend can be replaced without touching callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.models import ExclusionReason


@dataclass(frozen=True, slots=True)
class DeviceConfig:
    device_id: UUID
    config_snapshot_id: UUID
    batfish_hostname: str
    content: str
    captured_at: datetime


@dataclass(frozen=True, slots=True)
class ExcludedDevice:
    device_id: UUID
    reason: ExclusionReason


@dataclass(frozen=True, slots=True)
class Layer1Edge:
    node1_hostname: str
    node1_interface: str
    node2_hostname: str
    node2_interface: str


@dataclass(frozen=True, slots=True)
class AnalysisInput:
    configs: tuple[DeviceConfig, ...]
    excluded: tuple[ExcludedDevice, ...]
    layer1_edges: tuple[Layer1Edge, ...]
    oldest_config_at: datetime | None
    newest_config_at: datetime | None
