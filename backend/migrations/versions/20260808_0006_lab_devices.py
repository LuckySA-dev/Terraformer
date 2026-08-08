"""Mark lab devices and record their console transport.

Revision ID: 20260808_0006
Revises: 20260808_0008
Create Date: 2026-08-08

Changes:
- Adds devices.is_lab (default false) for virtual devices such as GNS3/EVE-NG.
- Adds devices.console_transport ('ssh' | 'telnet', default 'ssh').

Existing devices keep the safe defaults: not a lab device, SSH console. No
device becomes telnet-reachable as a result of this migration.

down_revision points at 20260808_0008 rather than its original
20260806_0005: this migration was developed on a branch that forked before
0008 (read-only Batfish analysis, also revising 0005) existed on `main`. 0008's
own docstring recorded that whichever of the two branches landed second would
need to repoint here — this is that repointing, done when merging this branch
into `main`. 0008 does not touch the `devices` table, so there is no ordering
requirement between them beyond giving the chain a single head.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260808_0006"
down_revision: str | None = "20260808_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSOLE_TRANSPORT_VALUES = ("ssh", "telnet")


def _console_transport_type() -> sa.Enum:
    return sa.Enum(
        *_CONSOLE_TRANSPORT_VALUES,
        name="console_transport",
        native_enum=False,
        create_constraint=False,
    )


def upgrade() -> None:
    columns = (
        sa.Column("is_lab", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "console_transport",
            _console_transport_type(),
            nullable=False,
            server_default="ssh",
        ),
    )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("devices", recreate="always") as batch:
            for column in columns:
                batch.add_column(column)
            batch.create_check_constraint(
                "ck_devices_console_transport",
                "console_transport IN ({})".format(
                    ", ".join(f"'{value}'" for value in _CONSOLE_TRANSPORT_VALUES)
                ),
            )
        return

    for column in columns:
        op.add_column("devices", column)
    op.create_check_constraint(
        "ck_devices_console_transport",
        "devices",
        sa.text(
            "console_transport IN ({})".format(
                ", ".join(f"'{value}'" for value in _CONSOLE_TRANSPORT_VALUES)
            )
        ),
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("devices", recreate="always") as batch:
            batch.drop_constraint("ck_devices_console_transport", type_="check")
            batch.drop_column("console_transport")
            batch.drop_column("is_lab")
        return

    op.drop_constraint("ck_devices_console_transport", "devices", type_="check")
    op.drop_column("devices", "console_transport")
    op.drop_column("devices", "is_lab")
