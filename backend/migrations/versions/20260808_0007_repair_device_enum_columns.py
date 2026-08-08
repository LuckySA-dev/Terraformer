"""Repair devices.vendor / devices.ssh_compatibility on databases already at head.

Revision ID: 20260808_0007
Revises: 20260808_0006
Create Date: 2026-08-08

20260806_0005 originally failed on PostgreSQL: it dropped a CHECK constraint
that never existed, which aborts the transaction and takes the rest of the
migration with it. A database that was stamped past that failure — rather than
re-running it after the fix — is recorded at head while still carrying the old
column definitions:

- devices.vendor left at VARCHAR(11), too narrow for 'fortinet_fortios' (16),
  so registering a Fortinet device fails with "value too long".
- the pre-very_old_ssh CHECK constraint left in place, rejecting
  'very_old_ssh'.
- the canonical named constraints missing entirely.

This migration reconciles both columns with the ORM. It is idempotent and safe
on a database that is already correct, so it can run on any deployment without
the operator having to work out how theirs got there.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260808_0007"
down_revision: str | None = "20260808_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SSH_COMPAT_VALUES = ("modern", "cisco_legacy", "cisco_legacy_group1", "very_old_ssh")
_VENDOR_VALUES = ("cisco_iosxe", "fortinet_fortios", "generic")

_VENDOR_CONSTRAINTS = ("vendor", "ck_devices_vendor")
_SSH_COMPAT_CONSTRAINTS = ("ssh_compatibility", "ck_devices_ssh_compatibility")


def _enum(name: str, values: Sequence[str]) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=False)


def _condition(column: str, values: Sequence[str]) -> str:
    return "{} IN ({})".format(column, ", ".join(f"'{value}'" for value in values))


def _needs_repair(column: str, values: Sequence[str], candidates: Sequence[str]) -> bool:
    inspector = sa.inspect(op.get_bind())
    required_length = max(len(value) for value in values)
    for reflected in inspector.get_columns("devices"):
        if reflected["name"] != column:
            continue
        length = getattr(reflected["type"], "length", None)
        if length is not None and length < required_length:
            return True
    names = {
        constraint.get("name")
        for constraint in inspector.get_check_constraints("devices")
    }
    # The canonical constraint must exist, and no older spelling may survive.
    return candidates[1] not in names or candidates[0] in names


def _repair(column: str, values: Sequence[str], candidates: Sequence[str]) -> None:
    if not _needs_repair(column, values, candidates):
        return
    canonical = candidates[1]
    target = _enum(column, values)
    existing = _enum(column, values)

    if op.get_bind().dialect.name == "sqlite":
        present = {
            constraint.get("name")
            for constraint in sa.inspect(op.get_bind()).get_check_constraints("devices")
        }
        with op.batch_alter_table("devices", recreate="always") as batch:
            for name in candidates:
                if name in present:
                    batch.drop_constraint(name, type_="check")
            batch.alter_column(
                column, type_=target, existing_type=existing, existing_nullable=False
            )
            batch.create_check_constraint(canonical, _condition(column, values))
        return

    present = {
        constraint.get("name")
        for constraint in sa.inspect(op.get_bind()).get_check_constraints("devices")
    }
    for name in candidates:
        if name in present:
            op.drop_constraint(name, "devices", type_="check")
    op.alter_column(
        "devices", column, type_=target, existing_type=existing, existing_nullable=False
    )
    op.create_check_constraint(canonical, "devices", sa.text(_condition(column, values)))


def upgrade() -> None:
    _repair("ssh_compatibility", _SSH_COMPAT_VALUES, _SSH_COMPAT_CONSTRAINTS)
    _repair("vendor", _VENDOR_VALUES, _VENDOR_CONSTRAINTS)


def downgrade() -> None:
    # Nothing to undo: this only brings a database up to the shape 20260806_0005
    # was always meant to leave behind, which that migration's own downgrade
    # reverses.
    pass
