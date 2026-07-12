"""Add observed CDP and LLDP neighbor records.

Revision ID: 20260712_0002
Revises: 20260711_0001
Create Date: 2026-07-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260712_0002"
down_revision: str | None = "20260711_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "neighbors",
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("protocol", sa.String(length=16), nullable=False),
        sa.Column("local_interface", sa.String(length=255), nullable=False),
        sa.Column("remote_device_name", sa.String(length=255), nullable=False),
        sa.Column("remote_interface", sa.String(length=255), nullable=False),
        sa.Column("management_address", sa.String(length=255), nullable=True),
        sa.Column("platform", sa.String(length=255), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "device_id",
            "protocol",
            "local_interface",
            "remote_device_name",
            "remote_interface",
            name="uq_neighbor_observation",
        ),
    )
    op.create_index("ix_neighbors_device_id", "neighbors", ["device_id"])


def downgrade() -> None:
    op.drop_index("ix_neighbors_device_id", table_name="neighbors")
    op.drop_table("neighbors")
