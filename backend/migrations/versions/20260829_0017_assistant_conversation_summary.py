"""Let a long conversation be compacted instead of truncated.

Revision ID: 20260829_0017
Revises: 20260827_0016
Create Date: 2026-08-29

A conversation that outgrew its context budget used to have its oldest turns
dropped, which loses what was established in them -- the device that turned out
to be the one at fault, the value that was already checked. These two columns
hold a summary of the turns that have been folded away and how many of the
session's oldest messages it stands for, so the model keeps what was learned
rather than only what was said most recently.

`summarised_message_count` counts from the oldest message in the session.
Messages are only ever appended and are deleted only with their session, so a
count is stable; it needs no foreign key of its own and cannot dangle.

Existing sessions have never been compacted, which is exactly what 0 and NULL
mean, so no row needs interpreting. The count carries a server-side default so
an older API process still inserting rows during a rolling restart cannot
violate NOT NULL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260829_0017"
down_revision: str | None = "20260827_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("assistant_sessions", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column(
        "assistant_sessions",
        sa.Column(
            "summarised_message_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("assistant_sessions", "summarised_message_count")
    op.drop_column("assistant_sessions", "summary")
