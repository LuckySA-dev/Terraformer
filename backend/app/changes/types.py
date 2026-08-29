"""Pure, driver-agnostic value types for the change pipeline.

No I/O, no database session, no vendor knowledge -- keeps the pipeline's
shape testable without a device or a container.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from ipaddress import IPv4Network, ip_network

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


# An IOS trunk list is ids and ranges: "1,10,20-30". "ALL" and "NONE" are the
# two words the device uses instead of a list.
VLAN_LIST_PATTERN = re.compile(r"\d{1,4}(?:-\d{1,4})?(?:,\d{1,4}(?:-\d{1,4})?)*")
VLAN_ID_MIN = 1
VLAN_ID_MAX = 4094


def expand_vlan_list(text: str) -> frozenset[int]:
    """Every VLAN id a trunk list names, as a set.

    Comparison has to happen on the set rather than the text: IOS reorders and
    re-ranges what it is given, so "20,10" is read back as "10,20". A string
    comparison would call that a failed change and roll back one that worked.
    """
    cleaned = text.strip().upper()
    if cleaned in ("", "NONE"):
        return frozenset()
    if cleaned == "ALL":
        return frozenset(range(VLAN_ID_MIN, VLAN_ID_MAX + 1))
    ids: set[int] = set()
    for part in cleaned.split(","):
        low, _, high = part.partition("-")
        try:
            start = int(low)
            end = int(high) if high else start
        except ValueError:
            continue
        ids.update(range(start, end + 1))
    return frozenset(ids)


def vlan_list_issues(text: str, *, field: str) -> list[str]:
    """Rejects anything that is not a well-formed list of in-range VLAN ids."""
    cleaned = text.strip()
    if not VLAN_LIST_PATTERN.fullmatch(cleaned):
        return [f"{field} must be VLAN ids and ranges, for example 1,10,20-30"]
    for part in cleaned.split(","):
        low, _, high = part.partition("-")
        start, end = int(low), int(high) if high else int(low)
        if start > end:
            return [f"{field} range {part} runs backwards"]
        if not (VLAN_ID_MIN <= start and end <= VLAN_ID_MAX):
            return [f"{field} ids must be between {VLAN_ID_MIN} and {VLAN_ID_MAX}"]
    return []


def prefix_parts(target: str) -> tuple[str, str]:
    """Splits "10.10.0.0/16" into the dotted destination and mask IOS wants."""
    cleaned = target.strip()
    # The length is required rather than defaulted. ip_network reads a bare
    # "10.10.0.0" as a /32 host route, so an operator who meant a /16 would
    # get a route for a different prefix than the one they typed and no
    # warning about it -- the same failure the host-bits check exists to stop.
    if "/" not in cleaned:
        raise ValueError("a prefix length is required")
    network = ip_network(cleaned, strict=True)
    if not isinstance(network, IPv4Network):
        raise ValueError("only IPv4 prefixes are supported")
    return str(network.network_address), str(network.netmask)


def prefix_issues(target: str) -> list[str]:
    try:
        prefix_parts(target)
    except ValueError:
        # ip_network reports "has host bits set" for 10.10.0.5/16, which is the
        # most common way to get this wrong and worth saying back plainly.
        return [
            "destination must be an IPv4 prefix such as 10.10.0.0/16 -- the "
            f"prefix length is required and no host bits may be set (got {target!r})"
        ]
    return []
