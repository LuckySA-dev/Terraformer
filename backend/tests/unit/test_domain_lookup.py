from __future__ import annotations

import pytest

from app.changes.types import ChangeStepIntent
from app.core.errors import UnsupportedCapabilityError
from app.drivers.base import ChangeContext
from app.drivers.cisco_iosxe import CiscoIOSXEDriver
from app.models import ChangeType
from tests.fakes import FakeTransportFactory


def _driver(output: str = "") -> CiscoIOSXEDriver:
    return CiscoIOSXEDriver(
        FakeTransportFactory({"show running-config | include ip domain.lookup": output})
    )


def _step(value: str) -> ChangeStepIntent:
    return ChangeStepIntent(change_type=ChangeType.DOMAIN_LOOKUP, target="", desired_value=value)


def test_absence_of_the_line_reads_as_enabled() -> None:
    # Lookup is the IOS default, so it is only written to the config when it
    # is off. "Nothing in the config" therefore means on, not unconfigured.
    assert _driver("").get_domain_lookup(object()) is True  # type: ignore[arg-type]


def test_the_no_form_reads_as_disabled() -> None:
    assert _driver("no ip domain-lookup").get_domain_lookup(object()) is False  # type: ignore[arg-type]


def test_the_older_spelling_without_a_hyphen_also_reads_as_disabled() -> None:
    assert _driver("no ip domain lookup").get_domain_lookup(object()) is False  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("desired", "current", "commands", "inverse"),
    [
        ("off", True, ("no ip domain-lookup",), ("ip domain-lookup",)),
        ("on", False, ("ip domain-lookup",), ("no ip domain-lookup",)),
        # Re-applying what is already set still has to roll back to it.
        ("off", False, ("no ip domain-lookup",), ("no ip domain-lookup",)),
    ],
)
def test_rollback_restores_what_the_device_reported(
    desired: str, current: bool, commands: tuple[str, ...], inverse: tuple[str, ...]
) -> None:
    rendered = _driver().render_change(_step(desired), ChangeContext(domain_lookup=current))
    assert rendered.commands == commands
    assert rendered.inverse_commands == inverse


def test_an_unreadable_current_value_is_refused_rather_than_guessed() -> None:
    with pytest.raises(UnsupportedCapabilityError):
        _driver().render_change(_step("off"), ChangeContext(domain_lookup=None))


@pytest.mark.parametrize("value", ["", "yes", "disable", "0", "on\nreload"])
def test_only_on_and_off_are_accepted(value: str) -> None:
    assert _driver().validate_change(_step(value), ChangeContext(domain_lookup=True))
