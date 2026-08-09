"""Risk classification for a single change step.

Deliberately narrow for this slice: a change is HIGH risk if it takes admin
state from up to down, or if it targets an interface that is currently up
(admin and operational) -- both are signals the interface carries live
traffic right now. Everything else is LOW. Not a general-purpose risk
engine; extend the conditions here as later Phase 3 slices add change types.
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
    if current_admin_up is True and current_oper_up is True:
        return ChangeRisk.HIGH
    return ChangeRisk.LOW
