"""Add very_old_ssh compatibility mode and fortinet_fortios vendor.

Revision ID: 20260806_0005
Revises: 20260806_0004
Create Date: 2026-08-06

Changes:
- Widens devices.vendor so 'fortinet_fortios' fits, and allows it.
- Extends the ssh_compatibility allowed values to include 'very_old_ssh'.
- Normalizes both columns onto explicitly named CHECK constraints.
- No data migration — all existing devices remain unaffected.

Why this migration is more involved than "drop one constraint, add another":

1. devices.vendor was created as sa.Enum("cisco_iosxe", "generic", ...), which
   sizes the column to the longest value — VARCHAR(11). 'fortinet_fortios' is
   16 characters. SQLite ignores VARCHAR length, but PostgreSQL rejects the
   insert outright, so the column has to be widened, not just re-constrained.
2. sa.Enum defaults to create_constraint=False, so devices.vendor never had a
   CHECK constraint under any name. Dropping a constraint that does not exist
   aborts the entire transaction on PostgreSQL, which is what broke
   `alembic upgrade head` in the container.
3. devices.ssh_compatibility was created with create_constraint=True *and* an
   explicitly named constraint, so a database can carry the type-bound name
   ('ssh_compatibility'), the explicit name ('ck_devices_ssh_compatibility'),
   or both. Every spelling has to be removed, or the old three-value
   constraint survives and rejects 'very_old_ssh'.
4. Type-bound CHECK constraints cannot be dropped by name inside
   batch_alter_table (alembic regenerates them from the column type). Moving
   the column to a create_constraint=False type is what actually clears them
   on SQLite.

downgrade() deliberately restores the *pre-0005* shape per dialect rather than
mirroring upgrade(), because 20260722_0003.downgrade() drops the constraint by
its original name and fails if a differently named one is left behind.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_0005"
down_revision: str | None = "20260806_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SSH_COMPAT_VALUES = ("modern", "cisco_legacy", "cisco_legacy_group1", "very_old_ssh")
_SSH_COMPAT_VALUES_OLD = ("modern", "cisco_legacy", "cisco_legacy_group1")

_VENDOR_VALUES = ("cisco_iosxe", "fortinet_fortios", "generic")
_VENDOR_VALUES_OLD = ("cisco_iosxe", "generic")

# Every spelling a column's CHECK constraint may carry, type-bound name first.
_VENDOR_CONSTRAINTS = ("vendor", "ck_devices_vendor")
_SSH_COMPAT_CONSTRAINTS = ("ssh_compatibility", "ck_devices_ssh_compatibility")


def _enum(name: str, values: Sequence[str], *, create_constraint: bool = False) -> sa.Enum:
    """A VARCHAR sized to the longest value.

    create_constraint=False matches the ORM definition in
    app/models/entities.py, so `alembic check` reports no drift.
    """
    return sa.Enum(
        *values,
        name=name,
        native_enum=False,
        create_constraint=create_constraint,
    )


def _condition(column: str, values: Sequence[str]) -> str:
    return "{} IN ({})".format(column, ", ".join(f"'{value}'" for value in values))


def _present_check_constraints(candidates: Sequence[str]) -> list[str]:
    present = {
        constraint.get("name")
        for constraint in sa.inspect(op.get_bind()).get_check_constraints("devices")
    }
    return [name for name in candidates if name in present]


def _retype(
    column: str,
    old_type: sa.Enum,
    new_type: sa.Enum,
    *,
    check_name: str | None,
    check_values: Sequence[str],
) -> None:
    """Replace a column's type and its CHECK constraint on either dialect."""
    candidates = _VENDOR_CONSTRAINTS if column == "vendor" else _SSH_COMPAT_CONSTRAINTS
    if op.get_bind().dialect.name == "sqlite":
        # recreate="always" rebuilds the table from the reflected schema, which
        # carries every existing CHECK forward unless it is dropped by name.
        # The names have to be resolved before the batch opens, because
        # dropping a name that is not there raises inside the batch.
        existing = _present_check_constraints(candidates)
        with op.batch_alter_table("devices", recreate="always") as batch:
            for name in existing:
                batch.drop_constraint(name, type_="check")
            batch.alter_column(
                column,
                type_=new_type,
                existing_type=old_type,
                existing_nullable=False,
            )
            if check_name is not None:
                batch.create_check_constraint(check_name, _condition(column, check_values))
        return

    for name in _present_check_constraints(candidates):
        op.drop_constraint(name, "devices", type_="check")
    op.alter_column(
        "devices",
        column,
        type_=new_type,
        existing_type=old_type,
        existing_nullable=False,
    )
    if check_name is not None:
        op.create_check_constraint(
            check_name, "devices", sa.text(_condition(column, check_values))
        )


def upgrade() -> None:
    _retype(
        "ssh_compatibility",
        _enum("ssh_compatibility", _SSH_COMPAT_VALUES_OLD),
        _enum("ssh_compatibility", _SSH_COMPAT_VALUES),
        check_name="ck_devices_ssh_compatibility",
        check_values=_SSH_COMPAT_VALUES,
    )
    _retype(
        "vendor",
        _enum("vendor", _VENDOR_VALUES_OLD),
        _enum("vendor", _VENDOR_VALUES),
        check_name="ck_devices_vendor",
        check_values=_VENDOR_VALUES,
    )


def downgrade() -> None:
    # Narrowing fails loudly if rows still hold the removed values; migrate or
    # delete those devices before downgrading.
    #
    # vendor returns to VARCHAR(11) with no CHECK constraint at all, which is
    # what 20260711_0001 created.
    _retype(
        "vendor",
        _enum("vendor", _VENDOR_VALUES),
        _enum("vendor", _VENDOR_VALUES_OLD),
        check_name=None,
        check_values=_VENDOR_VALUES_OLD,
    )
    # ssh_compatibility returns to whatever 20260722_0003 created for this
    # dialect, because that migration's downgrade() drops it by that name:
    # a type-bound 'ssh_compatibility' on SQLite, an explicitly named
    # 'ck_devices_ssh_compatibility' elsewhere.
    sqlite = op.get_bind().dialect.name == "sqlite"
    _retype(
        "ssh_compatibility",
        _enum("ssh_compatibility", _SSH_COMPAT_VALUES),
        _enum("ssh_compatibility", _SSH_COMPAT_VALUES_OLD, create_constraint=sqlite),
        check_name=None if sqlite else "ck_devices_ssh_compatibility",
        check_values=_SSH_COMPAT_VALUES_OLD,
    )
