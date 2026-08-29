from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.assistant.client import ToolSchema
from app.repositories.changes import ChangeRepository
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

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100


def _bounded_limit(raw: object) -> int:
    """A model that asks for everything must not be able to have everything."""
    try:
        requested = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return _DEFAULT_LIMIT
    return max(1, min(requested, _MAX_LIMIT))

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

_LIST_DEVICES_TOOL = ToolSchema(
    name="list_devices",
    description=(
        "List every registered device: id, name, vendor, management address, reachability "
        "and when it was last observed. Start here -- every other tool needs a device_id, "
        "and this is the only way to learn one."
    ),
    parameters={"type": "object", "properties": {}},
)
_TOPOLOGY_TOOL = ToolSchema(
    name="get_topology",
    description=(
        "The whole network as this application has observed it: every registered device, "
        "and every CDP/LLDP adjacency between them. Links whose far end is not a "
        "registered device are returned separately as observed-only neighbours. This is "
        "evidence read from the devices, not a design document -- it is only as current as "
        "the last refresh of each device, which is reported per device."
    ),
    parameters={"type": "object", "properties": {}},
)
_CHANGE_PLANS_TOOL = ToolSchema(
    name="list_change_plans",
    description=(
        "Recent Change Plans, newest first, with what each one changed, its risk, whether "
        "it applied, and the failure code if it did not. Use it to answer what was changed "
        "recently and what a failure was, before proposing anything new. Omit device_id to "
        "see every device."
    ),
    parameters={
        "type": "object",
        "properties": {
            "device_id": {"type": "string", "format": "uuid"},
            "limit": {"type": "integer"},
        },
    },
)

# There is no write tool defined anywhere in this module, in either Confirm
# or Auto mode -- see spec
# docs/superpowers/specs/2026-08-24-phase-4-ai-assistant-design.md §6.
READ_ONLY_TOOLS: tuple[ToolSchema, ...] = (
    _LIST_DEVICES_TOOL,
    _TOPOLOGY_TOOL,
    _CHANGE_PLANS_TOOL,
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
                    "router_network_remove",
                    "router_rip_version",
                    "bgp_neighbor",
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
                    "process. router_network_remove: the same target and value, but withdraws "
                    "the statement; the process must already carry it. router_rip_version: "
                    "target is 'rip' and desired_value is '1' or '2'. bgp_neighbor: target is "
                    "the local process as 'bgp <asn>' and desired_value is "
                    "'<peer address> remote-as <asn>' -- a device runs one BGP process, so the "
                    "local AS must match the one already configured if there is one. "
                    "hostname: the device "
                    "itself is the target, so pass an empty target, and desired_value is the new "
                    "name."
                ),
            },
            "target": {
                "type": "string",
                "description": (
                    "An interface name such as GigabitEthernet0/1, a VLAN id such as 10 "
                    "when change_type is vlan_name, a destination prefix for static_route, a "
                    "routing process such as 'ospf 1' for router_network and "
                    "router_network_remove, 'rip' for router_rip_version, 'bgp <asn>' for "
                    "bgp_neighbor, or an empty string for hostname, which targets the device "
                    "itself."
                ),
            },
            "desired_value": {"type": "string"},
        },
        "required": ["device_id", "change_type", "target", "desired_value"],
    },
)


class ToolDispatcher:
    def __init__(
        self,
        *,
        devices: DeviceService,
        snapshots: SnapshotService,
        events: EventRepository,
        changes: ChangeRepository | None = None,
    ) -> None:
        self._devices = devices
        self._snapshots = snapshots
        self._events = events
        self._changes = changes

    def dispatch(self, name: str, arguments: dict[str, object]) -> ToolResult:
        # The network-wide tools take no device_id, so the requirement moved
        # from here into the tools that actually need one.
        if name == _LIST_DEVICES_TOOL.name:
            return ToolResult(name=name, payload=self._device_inventory())
        if name == _TOPOLOGY_TOOL.name:
            return ToolResult(name=name, payload=self._topology())
        if name == _CHANGE_PLANS_TOOL.name:
            return ToolResult(name=name, payload=self._change_plans(arguments))
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

    def _device_inventory(self) -> dict[str, object]:
        return {
            "devices": [
                {
                    "device_id": str(device.id),
                    "name": device.name,
                    "vendor": device.vendor.value,
                    "management_address": device.management_address,
                    "status": device.status.value,
                    "is_lab": device.is_lab,
                    "last_seen_at": (
                        device.last_seen_at.isoformat() if device.last_seen_at else None
                    ),
                    "hostname": device.facts.get("hostname"),
                    "model": device.facts.get("model"),
                }
                for device in self._devices.list()
            ]
        }

    def _topology(self) -> dict[str, object]:
        """The observed graph, correlated across every registered device.

        Neighbour records are stored per device, so a model asking "what does
        this network look like" would otherwise have to call one tool per
        device and correlate the far ends itself -- which it cannot do at all
        until it can enumerate the devices.
        """
        devices = self._devices.list()
        # A neighbour is matched to a registered device on its management
        # address first, since that is exact, then on a hostname prefix --
        # CDP reports "sw2.example.test" for a device named "SW2".
        by_address = {device.management_address: device for device in devices}
        by_name = {device.name.casefold(): device for device in devices}

        links: list[dict[str, object]] = []
        observed_only: list[dict[str, object]] = []
        for device in devices:
            for neighbor in self._devices.list_neighbors(device.id):
                far_end = by_address.get(neighbor.management_address or "") or by_name.get(
                    neighbor.remote_device_name.split(".", 1)[0].casefold()
                )
                record: dict[str, object] = {
                    "protocol": neighbor.protocol,
                    "local_device_id": str(device.id),
                    "local_device": device.name,
                    "local_interface": neighbor.local_interface,
                    "remote_name": neighbor.remote_device_name,
                    "remote_interface": neighbor.remote_interface,
                    "remote_management_address": neighbor.management_address,
                    "remote_platform": neighbor.platform,
                }
                if far_end is None:
                    observed_only.append(record)
                    continue
                links.append({**record, "remote_device_id": str(far_end.id)})

        return {
            "evidence": "OBSERVED",
            "note": (
                "Adjacencies come from CDP/LLDP as of each device's last refresh; "
                "last_seen_at says how current each one is. A device with no links may "
                "simply not have been refreshed."
            ),
            "devices": self._device_inventory()["devices"],
            "links": links,
            "observed_only_neighbours": observed_only,
        }

    def _change_plans(self, arguments: dict[str, object]) -> dict[str, object]:
        if self._changes is None:
            raise ReadOnlyToolError("Change history is unavailable in this deployment")
        limit = _bounded_limit(arguments.get("limit"))
        raw_device = arguments.get("device_id")
        if isinstance(raw_device, str) and raw_device:
            try:
                device_ids = [UUID(raw_device)]
            except ValueError as exc:
                raise ReadOnlyToolError("device_id must be a UUID") from exc
        else:
            device_ids = [device.id for device in self._devices.list()]

        plans: list[dict[str, object]] = []
        for device_id in device_ids:
            for plan in self._changes.list_by_device(device_id, limit=limit):
                step = plan.steps[0] if plan.steps else None
                plans.append(
                    {
                        "change_plan_id": str(plan.id),
                        "device_id": str(plan.device_id),
                        "status": plan.status.value,
                        "risk": plan.risk.value,
                        "source": plan.source.value,
                        "failure_code": plan.failure_code,
                        "created_at": plan.created_at.isoformat(),
                        "applied_at": plan.applied_at.isoformat() if plan.applied_at else None,
                        "change_type": step.change_type.value if step else None,
                        "target": step.target if step else None,
                        "previous_value": step.previous_value if step else None,
                        "desired_value": step.desired_value if step else None,
                    }
                )
        plans.sort(key=lambda item: str(item["created_at"]), reverse=True)
        return {"change_plans": plans[:limit]}

    @staticmethod
    def _require_device_id(arguments: dict[str, object]) -> UUID:
        raw = arguments.get("device_id")
        if not isinstance(raw, str):
            raise ReadOnlyToolError("device_id is required")
        try:
            return UUID(raw)
        except ValueError as exc:
            raise ReadOnlyToolError("device_id must be a UUID") from exc
