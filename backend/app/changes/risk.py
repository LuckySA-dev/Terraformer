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
