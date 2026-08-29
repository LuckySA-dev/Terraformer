"""Order replayed messages by an explicit sequence, not by their timestamp.

Revision ID: 20260829_0018
Revises: 20260829_0017
Create Date: 2026-08-29

A conversation is replayed to the model by reading its messages back in order,
and that order was `ORDER BY created_at`. created_at comes from a Python
`datetime.now()` at insert time, whose resolution is coarse enough that
consecutive inserts frequently share a value -- measured at 941 distinct values
out of 2000 consecutive calls inside the application container. SQL leaves the
order of tied rows unspecified.

Two messages of one turn landing in the same microsecond could therefore replay
in either order, and one of those orders puts a tool result ahead of the
assistant turn that announced it -- which the provider chat APIs reject
outright. Intermittent, invisible until it happened, and impossible to
reproduce on demand.

The sequence is per session and assigned at insert. Existing rows are
backfilled in created_at order, which is the best available reconstruction and
matches whatever order they have been replaying in until now; ties among them
keep whatever order the backfill sees, which is no worse than today.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260829_0018"
down_revision: str | None = "20260829_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "assistant_messages",
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
    )
    # Window functions are available on both supported backends (PostgreSQL,
    # and SQLite from 3.25), so one statement covers the backfill.
    op.execute(
        sa.text(
            """
            UPDATE assistant_messages
            SET sequence = ordered.position
            FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY session_id ORDER BY created_at, id
                ) AS position
                FROM assistant_messages
            ) AS ordered
            WHERE assistant_messages.id = ordered.id
            """
        )
        if op.get_bind().dialect.name != "sqlite"
        # SQLite has no UPDATE ... FROM before 3.33 and no guarantee the
        # bundled build has it, so the same result is expressed as a
        # correlated subquery.
        else sa.text(
            """
            UPDATE assistant_messages
            SET sequence = (
                SELECT COUNT(*)
                FROM assistant_messages AS earlier
                WHERE earlier.session_id = assistant_messages.session_id
                  AND (
                      earlier.created_at < assistant_messages.created_at
                      OR (
                          earlier.created_at = assistant_messages.created_at
                          AND earlier.id <= assistant_messages.id
                      )
                  )
            )
            """
        )
    )
    op.create_index(
        "ix_assistant_messages_session_sequence",
        "assistant_messages",
        ["session_id", "sequence"],
    )


def downgrade() -> None:
    op.drop_index("ix_assistant_messages_session_sequence", table_name="assistant_messages")
    op.drop_column("assistant_messages", "sequence")
