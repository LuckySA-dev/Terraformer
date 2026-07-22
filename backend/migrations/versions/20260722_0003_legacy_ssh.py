"""Add per-device legacy SSH compatibility.

Revision ID: 20260722_0003
Revises: 20260712_0002
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260722_0003"
down_revision: str | None = "20260712_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    column = sa.Column(
        "ssh_compatibility",
        sa.Enum(
            "modern",
            "cisco_legacy",
            "cisco_legacy_group1",
            name="ssh_compatibility",
            native_enum=False,
            create_constraint=True,
        ),
        nullable=False,
        server_default="modern",
    )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("devices", recreate="always") as batch:
            batch.add_column(column)
    else:
        op.add_column("devices", column)


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("devices", recreate="always") as batch:
            batch.drop_constraint("ssh_compatibility", type_="check")
            batch.drop_column("ssh_compatibility")
    else:
        op.drop_column("devices", "ssh_compatibility")
