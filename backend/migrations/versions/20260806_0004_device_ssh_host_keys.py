"""Add one pinned SSH host key per device.

Revision ID: 20260806_0004
Revises: 20260722_0003
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_0004"
down_revision: str | None = "20260722_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "device_ssh_host_keys",
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("algorithm", sa.String(length=64), nullable=False),
        sa.Column("public_key", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(length=128), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_by", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id", name="uq_device_ssh_host_key_device"),
    )
    op.create_index("ix_device_ssh_host_keys_device_id", "device_ssh_host_keys", ["device_id"])


def downgrade() -> None:
    op.drop_index("ix_device_ssh_host_keys_device_id", table_name="device_ssh_host_keys")
    op.drop_table("device_ssh_host_keys")
