"""Let one assistant conversation name several devices.

Revision ID: 20260827_0016
Revises: 20260827_0015
Create Date: 2026-08-27

The assistant moved out of each device's inspector into a right-hand sidebar
shared by the whole workspace, so a conversation is no longer about exactly
one device or about all of them. This column carries the operator's chosen
set -- "SW1 and SW2" -- so the model can be told which devices are meant
without a UUID being pasted into the message.

An empty list is "every registered device", which is what every session
created before this revision was, so existing rows need no interpretation.
Server-side default included: rows inserted by an older API process during a
rolling restart would otherwise violate NOT NULL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_0016"
down_revision: str | None = "20260827_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "assistant_sessions",
        sa.Column(
            "scope_device_ids",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("assistant_sessions", "scope_device_ids")
