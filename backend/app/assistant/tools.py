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
        "Propose a Change Plan for a registered Cisco IOS/IOS-XE device. "
        "This only drafts and validates a plan for human review -- it never "
        "touches the device. A human must separately apply it before "
        "anything changes. One plan covers exactly one change on one device: "
        "to change several things, or several devices, propose several plans. "
        "To put a port in a VLAN that does not exist yet, propose the "
        "vlan_name plan first, then the interface_access_vlan plan."
    ),
    parameters={
        "type": "object",
        "properties": {
            "device_id": {"type": "string", "format": "uuid"},
            "change_type": {
                "type": "string",
                "enum": [
                    "interface_description",
                    "interface_admin_state",
                    "vlan_name",
                    "interface_access_vlan",
                    "interface_trunk_vlans",
                    "static_route",
                    "router_network",
                    "hostname",
                ],
                "description": (
                    "interface_description: target is an interface, desired_value is free text. "
                    "interface_admin_state: target is an interface, desired_value is 'up' or "
                    "'down'. vlan_name: target is a VLAN id, desired_value is the VLAN name "
                    "(creates the VLAN if it does not exist). interface_access_vlan: target is "
                    "an interface, desired_value is the VLAN id to move that access port into. "
                    "interface_trunk_vlans: target is an interface, desired_value is the list of "
                    "VLANs the trunk carries such as '1,10,20-30' -- it replaces the whole list, "
                    "so include every VLAN the link must keep carrying. static_route: target "
                    "is a destination prefix in CIDR form such as 10.10.0.0/16 (the prefix "
                    "length is required), desired_value is the next hop as an IPv4 address or "
                    "an exit interface name. router_network: target is a routing process -- "
                    "'rip', or 'ospf <id>' / 'eigrp <id>' -- and desired_value is one network "
                    "statement for that protocol ('10.0.0.0 0.0.0.255 area 0' for ospf, "
                    "'10.0.0.0 0.0.255.255' for eigrp, '10.0.0.0' for rip). If the process is "
                    "not running this starts it, and the rollback then removes the whole "
                    "process. hostname: the device "
                    "itself is the target, so pass an empty target, and desired_value is the new "
                    "name."
                ),
            },
            "target": {
                "type": "string",
                "description": (
                    "An interface name such as GigabitEthernet0/1, a VLAN id such as 10 "
                    "when change_type is vlan_name, a destination prefix for static_route, a "
                    "routing process such as 'ospf 1' for router_network, or an empty string "
                    "for hostname, which targets the device itself."
                ),
            },
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
