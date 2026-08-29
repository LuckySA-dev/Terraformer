"""Risk classification for a single change step.

Deliberately narrow: a change is HIGH risk when it plausibly interrupts
traffic that is flowing right now. Everything else is LOW. Not a
general-purpose risk engine -- extend the conditions here as new change
types arrive.
"""

from __future__ import annotations

from app.models import ChangeRisk, ChangeType


def classify_risk(
    change_type: ChangeType,
    *,
    current_admin_up: bool | None,
    current_oper_up: bool | None,
    desired_value: str,
    target: str = "",
    previous_value: str | None = None,
) -> ChangeRisk:
    """Classifies one step.

    `target` and `previous_value` are read only by the static-route rule,
    which has no interface state to judge and has to look at the prefix itself
    and at whether one was already routed. They carry defaults so the change
    types that predate them keep their existing call sites; no other rule
    consults them.
    """
    if change_type is ChangeType.INTERFACE_ADMIN_STATE and desired_value == "down":
        return ChangeRisk.HIGH
    # Renaming the device drops no frame. It has to be checked before the
    # shared "live interface" rule below, because a global change carries no
    # interface state and would otherwise fall through to whatever the
    # unrelated `current_*` arguments happen to hold.
    if change_type is ChangeType.HOSTNAME:
        return ChangeRisk.LOW
    # Renaming a VLAN is a label change in the VLAN database: it moves no
    # port and drops no frame, so it stays LOW even on a busy switch. Note
    # this covers naming an existing or new VLAN only -- there is no delete.
    if change_type is ChangeType.VLAN_NAME:
        return ChangeRisk.LOW
    # Moving an access port always cuts the traffic already on it, so a live
    # port is HIGH regardless of which VLAN it is going to. The shared rule
    # below would catch this too; it is spelled out because the reason is
    # specific to re-homing a port, not to touching a live interface.
    if change_type is ChangeType.INTERFACE_ACCESS_VLAN and current_oper_up is True:
        return ChangeRisk.HIGH
    # The allowed list replaces what is there rather than adding to it, so a
    # trunk carrying traffic loses every VLAN the new list omits. Spelled out
    # for the same reason as the access-port rule: the shared condition below
    # would catch it, but not for this reason.
    if change_type is ChangeType.INTERFACE_TRUNK_VLANS and current_oper_up is True:
        return ChangeRisk.HIGH
    if change_type is ChangeType.STATIC_ROUTE:
        return _static_route_risk(target, previous_value)
    if change_type is ChangeType.ROUTER_NETWORK:
        return _router_network_risk(desired_value, previous_value)
    # Withdrawing a network stops the process advertising it, so whatever was
    # reaching it through this device stops reaching it. There is no version of
    # that which is routine.
    if change_type is ChangeType.ROUTER_NETWORK_REMOVE:
        return ChangeRisk.HIGH
    # v1 and v2 do not interoperate, so changing it drops every adjacency the
    # process had; setting it on a process that does not exist starts RIP.
    if change_type is ChangeType.ROUTER_RIP_VERSION:
        return ChangeRisk.HIGH
    # A peering session can move or withdraw a large amount of reachability the
    # moment it comes up, and it is the classic way a lab loses its own path.
    if change_type is ChangeType.BGP_NEIGHBOR:
        return ChangeRisk.HIGH
    if current_admin_up is True and current_oper_up is True:
        return ChangeRisk.HIGH
    return ChangeRisk.LOW


def _static_route_risk(target: str, previous_value: str | None) -> ChangeRisk:
    """A static route carries no interface state, so it is judged on its own.

    Routing a prefix nothing routed before only adds a path. Replacing the
    next hop of a prefix that already had one moves whatever is using it, and
    a default route moves everything with no more specific match -- which, on
    a device reached over that same path, includes the session applying the
    change.
    """
    if target.strip() in ("0.0.0.0/0", "0.0.0.0 0.0.0.0"):
        return ChangeRisk.HIGH
    if previous_value is not None:
        return ChangeRisk.HIGH
    return ChangeRisk.LOW


def _router_network_risk(desired_value: str, previous_value: str | None) -> ChangeRisk:
    """A routing change is judged on reach, not on interface state.

    Adding a network to a process that is already running extends something
    the device was already doing. Starting a process puts the device into a
    routing domain it was not in, and a statement whose wildcard covers every
    address enables the protocol on every interface -- including the one the
    device is managed on, whose adjacency can move how it is reached.
    """
    if " ".join(desired_value.split()).startswith("0.0.0.0 255.255.255.255"):
        return ChangeRisk.HIGH
    if previous_value is None:
        return ChangeRisk.HIGH
    return ChangeRisk.LOW