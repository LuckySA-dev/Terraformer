"""Add assistant_sessions and assistant_messages.

Revision ID: 20260824_0011
Revises: 20260824_0010
Create Date: 2026-08-24

Chat session/message persistence for the AI assistant (spec:
docs/superpowers/specs/2026-08-24-phase-4-ai-assistant-design.md).
auto_mode_acknowledged_at and auto_apply_count back the Auto-mode
risk-acknowledgment gate and per-session apply cap.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0011"
down_revision: str | None = "20260824_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MODE_VALUES = ("confirm", "auto")
_ROLE_VALUES = ("user", "assistant", "tool")


def _enum(name: str, values: Sequence[str]) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=False)


def upgrade() -> None:
    op.create_table(
        "assistant_sessions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "provider_profile_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("provider_profiles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "mode",
            _enum("assistant_session_mode", _MODE_VALUES),
            nullable=False,
            server_default="confirm",
        ),
        sa.Column("auto_mode_acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("auto_apply_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_assistant_sessions_provider_profile_id", "assistant_sessions", ["provider_profile_id"]
    )

    op.create_table(
        "assistant_messages",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("assistant_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", _enum("assistant_message_role", _ROLE_VALUES), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tool_calls", sa.JSON()),
        sa.Column("tool_results", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_assistant_messages_session_id", "assistant_messages", ["session_id"])


def downgrade() -> None:
    op.drop_table("assistant_messages")
    op.drop_table("assistant_sessions")
