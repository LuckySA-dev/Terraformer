"""Scope assistant sessions to a device.

Revision ID: 20260827_0015
Revises: 20260827_0014
Create Date: 2026-08-27

Lets the assistant be opened from a device's own inspector with a
conversation that belongs to that device alone. NULL keeps the existing
workspace-wide behaviour, so every session created before this revision
stays exactly as it was. CASCADE because a chat about a device has no
meaning once the device is gone.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_0015"
down_revision: str | None = "20260827_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "assistant_sessions",
        sa.Column("device_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.create_index("ix_assistant_sessions_device_id", "assistant_sessions", ["device_id"])
    # SQLite cannot add a foreign key to an existing table with ALTER; the
    # batch path rebuilds it. Named so the batch rebuild can carry it.
    with op.batch_alter_table("assistant_sessions") as batch:
        batch.create_foreign_key(
            "fk_assistant_sessions_device_id",
            "devices",
            ["device_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    with op.batch_alter_table("assistant_sessions") as batch:
        batch.drop_constraint("fk_assistant_sessions_device_id", type_="foreignkey")
    op.drop_index("ix_assistant_sessions_device_id", table_name="assistant_sessions")
    op.drop_column("assistant_sessions", "device_id")
