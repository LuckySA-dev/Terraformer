"""Pure, driver-agnostic value types for the change pipeline.

No I/O, no database session, no vendor knowledge -- keeps the pipeline's
shape testable without a device or a container.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models import ChangeType


@dataclass(frozen=True, slots=True)
class ChangeStepIntent:
    """What the operator asked for, before rendering.

    Mirrors ChangeStep's pre-render fields as a plain in-memory value --
    not yet persisted, not yet rendered.
    """

    change_type: ChangeType
    target: str
    desired_value: str


@dataclass(frozen=True, slots=True)
class RenderedChange:
    commands: tuple[str, ...]
    inverse_commands: tuple[str, ...]


# `show vlan brief` abbreviates port names ("Gi1/0/1") while `show interfaces`
# spells them out ("GigabitEthernet1/0/1"), so the two have to be compared on
# a normalised form or every membership lookup silently misses.
_INTERFACE_PREFIXES = (
    ("twentyfivegige", "twe"),
    ("tengigabitethernet", "te"),
    ("fortygigabitethernet", "fo"),
    ("hundredgige", "hu"),
    ("gigabitethernet", "gi"),
    ("fastethernet", "fa"),
    ("ethernet", "et"),
    ("port-channel", "po"),
)


def normalize_interface_name(name: str) -> str:
    """Collapses long and short Cisco interface spellings onto one form."""
    lowered = name.strip().lower()
    for long_form, short_form in _INTERFACE_PREFIXES:
        if lowered.startswith(long_form):
            return short_form + lowered[len(long_form) :]
    return lowered


def same_interface(left: str, right: str) -> bool:
    return normalize_interface_name(left) == normalize_interface_name(right)
