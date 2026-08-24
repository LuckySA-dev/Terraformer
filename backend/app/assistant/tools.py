from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.assistant.client import ToolSchema
from app.repositories.events import EventRepository
from app.schemas.devices import FactsView, InterfaceView, NeighborView
from app.schemas.events import EventView
from app.schemas.snapshots import ConfigSnapshotView
from app.services.devices import DeviceService
from app.services.snapshots import SnapshotService


class ReadOnlyToolError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ToolResult:
    name: str
    payload: dict[str, object]


_DEVICE_ID_PARAM = {"device_id": {"type": "string", "format": "uuid"}}

_FACTS_TOOL = ToolSchema(
    name="get_device_facts",
    description="Read a registered device's last-observed platform facts.",
    parameters={"type": "object", "properties": _DEVICE_ID_PARAM, "required": ["device_id"]},
)
_INTERFACES_TOOL = ToolSchema(
    name="get_device_interfaces",
    description="Read a registered device's last-observed interface inventory.",
    parameters={"type": "object", "properties": _DEVICE_ID_PARAM, "required": ["device_id"]},
)
_NEIGHBORS_TOOL = ToolSchema(
    name="get_device_neighbors",
    description="Read a registered device's last-observed CDP/LLDP neighbors.",
    parameters={"type": "object", "properties": _DEVICE_ID_PARAM, "required": ["device_id"]},
)
_SNAPSHOTS_TOOL = ToolSchema(
    name="list_config_snapshots",
    description=(
        "List recent configuration snapshot metadata for a device. "
        "Never returns raw config content."
    ),
    parameters={
        "type": "object",
        "properties": {**_DEVICE_ID_PARAM, "limit": {"type": "integer"}},
        "required": ["device_id"],
    },
)
_EVENTS_TOOL = ToolSchema(
    name="list_device_events",
    description="List recent sanitized event-timeline entries for a device.",
    parameters={
        "type": "object",
        "properties": {**_DEVICE_ID_PARAM, "limit": {"type": "integer"}},
        "required": ["device_id"],
    },
)

# There is no write tool defined anywhere in this module, in either Confirm
# or Auto mode -- see spec
# docs/superpowers/specs/2026-08-24-phase-4-ai-assistant-design.md §6.
READ_ONLY_TOOLS: tuple[ToolSchema, ...] = (
    _FACTS_TOOL,
    _INTERFACES_TOOL,
    _NEIGHBORS_TOOL,
    _SNAPSHOTS_TOOL,
    _EVENTS_TOOL,
)

# Deliberately NOT part of READ_ONLY_TOOLS and never routed through
# ToolDispatcher -- this keeps test_read_only_tools_never_include_a_write_tool
# meaningful. It is still not a device write: calling it only drafts and
# validates a DRAFT ChangePlan through the same pipeline a manual preview
# uses (app/changes/service.py's preview()), which itself performs no
# device write. A separate, human/mode-gated apply is required afterward.
PROPOSE_CHANGE_PLAN_TOOL = ToolSchema(
    name="propose_change_plan",
    description=(
        "Propose a Change Plan for a registered Cisco IOS/IOS-XE device's "
        "interface description or admin state. This only drafts and "
        "validates a plan for human review -- it never touches the device. "
        "A human must separately apply it before anything changes."
    ),
    parameters={
        "type": "object",
        "properties": {
            "device_id": {"type": "string", "format": "uuid"},
            "change_type": {
                "type": "string",
                "enum": ["interface_description", "interface_admin_state"],
            },
            "target": {"type": "string", "description": "Interface name, e.g. GigabitEthernet0/1"},
            "desired_value": {"type": "string"},
        },
        "required": ["device_id", "change_type", "target", "desired_value"],
    },
)


class ToolDispatcher:
    def __init__(
        self, *, devices: DeviceService, snapshots: SnapshotService, events: EventRepository
    ) -> None:
        self._devices = devices
        self._snapshots = snapshots
        self._events = events

    def dispatch(self, name: str, arguments: dict[str, object]) -> ToolResult:
        device_id = self._require_device_id(arguments)
        if name == _FACTS_TOOL.name:
            device = self._devices.get(device_id)
            view = FactsView(
                device_id=device_id, facts=device.facts, last_seen_at=device.last_seen_at
            )
            return ToolResult(name=name, payload=view.model_dump(mode="json"))
        if name == _INTERFACES_TOOL.name:
            interfaces = self._devices.list_interfaces(device_id)
            return ToolResult(
                name=name,
                payload={
                    "interfaces": [
                        InterfaceView.model_validate(i).model_dump(mode="json") for i in interfaces
                    ]
                },
            )
        if name == _NEIGHBORS_TOOL.name:
            neighbors = self._devices.list_neighbors(device_id)
            return ToolResult(
                name=name,
                payload={
                    "neighbors": [
                        NeighborView.model_validate(n).model_dump(mode="json") for n in neighbors
                    ]
                },
            )
        if name == _SNAPSHOTS_TOOL.name:
            limit = int(arguments.get("limit", 20))  # type: ignore[arg-type]
            snapshots = self._snapshots.list(device_id=device_id, limit=limit)
            return ToolResult(
                name=name,
                payload={
                    "snapshots": [
                        ConfigSnapshotView.model_validate(s).model_dump(mode="json")
                        for s in snapshots
                    ]
                },
            )
        if name == _EVENTS_TOOL.name:
            limit = int(arguments.get("limit", 20))  # type: ignore[arg-type]
            events = self._events.list(device_id=device_id, limit=limit)
            return ToolResult(
                name=name,
                payload={
                    "events": [EventView.model_validate(e).model_dump(mode="json") for e in events]
                },
            )
        raise ReadOnlyToolError(f"Unknown or unavailable tool: {name}")

    @staticmethod
    def _require_device_id(arguments: dict[str, object]) -> UUID:
        raw = arguments.get("device_id")
        if not isinstance(raw, str):
            raise ReadOnlyToolError("device_id is required")
        try:
            return UUID(raw)
        except ValueError as exc:
            raise ReadOnlyToolError("device_id must be a UUID") from exc
