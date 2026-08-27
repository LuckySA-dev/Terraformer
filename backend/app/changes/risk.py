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
) -> ChangeRisk:
    if change_type is ChangeType.INTERFACE_ADMIN_STATE and desired_value == "down":
        return ChangeRisk.HIGH
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
    if current_admin_up is True and current_oper_up is True:
        return ChangeRisk.HIGH
    return ChangeRisk.LOW
