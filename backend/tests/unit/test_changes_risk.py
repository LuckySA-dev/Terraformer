from __future__ import annotations

from app.changes.risk import classify_risk
from app.models import ChangeRisk, ChangeType


def test_taking_admin_state_from_up_to_down_is_high_risk() -> None:
    risk = classify_risk(
        ChangeType.INTERFACE_ADMIN_STATE,
        current_admin_up=True,
        current_oper_up=True,
        desired_value="down",
    )
    assert risk is ChangeRisk.HIGH


def test_bringing_a_down_interface_up_is_low_risk() -> None:
    risk = classify_risk(
        ChangeType.INTERFACE_ADMIN_STATE,
        current_admin_up=False,
        current_oper_up=False,
        desired_value="up",
    )
    assert risk is ChangeRisk.LOW


def test_description_change_on_a_live_interface_is_high_risk() -> None:
    """Touching a currently up/forwarding interface is high risk regardless
    of change type -- description edits are usually harmless, but this is
    the signal that the interface carries live traffic right now."""
    risk = classify_risk(
        ChangeType.INTERFACE_DESCRIPTION,
        current_admin_up=True,
        current_oper_up=True,
        desired_value="uplink to core",
    )
    assert risk is ChangeRisk.HIGH


def test_description_change_on_a_down_interface_is_low_risk() -> None:
    risk = classify_risk(
        ChangeType.INTERFACE_DESCRIPTION,
        current_admin_up=False,
        current_oper_up=False,
        desired_value="spare port",
    )
    assert risk is ChangeRisk.LOW
