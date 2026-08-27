"""Move model selection from provider_profiles to assistant_sessions.

Revision ID: 20260825_0013
Revises: 20260824_0012
Create Date: 2026-08-25

A provider profile is now just a connection (base_url + optional encrypted
key): one key legitimately serves many models (an OpenAI key reaches every
OpenAI model, an Anthropic key every Claude model), so pinning one model_id
to the profile forced a separate profile -- and a duplicated key -- per
model. The model is chosen per chat session instead. Capability probing
moves with it: it now runs once at session-creation time against the
chosen model, rather than once per profile. Existing sessions are
backfilled from their profile's old values so an in-progress conversation
keeps working unchanged.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0013"
down_revision: str | None = "20260824_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("assistant_sessions", sa.Column("model_id", sa.String(200)))
    op.add_column("assistant_sessions", sa.Column("context_limit_override", sa.Integer()))
    op.add_column(
        "assistant_sessions",
        sa.Column("supports_streaming", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "assistant_sessions",
        sa.Column("supports_tool_calling", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite has no UPDATE...FROM; a correlated subquery does the same
        # backfill. Its ALTER TABLE also can't add a NOT NULL constraint to
        # an existing column directly, hence the batch (recreate) below.
        op.execute(
            """
            UPDATE assistant_sessions
            SET model_id = (
                    SELECT model_id FROM provider_profiles
                    WHERE provider_profiles.id = assistant_sessions.provider_profile_id
                ),
                context_limit_override = (
                    SELECT context_limit_override FROM provider_profiles
                    WHERE provider_profiles.id = assistant_sessions.provider_profile_id
                ),
                supports_streaming = (
                    SELECT supports_streaming FROM provider_profiles
                    WHERE provider_profiles.id = assistant_sessions.provider_profile_id
                ),
                supports_tool_calling = (
                    SELECT supports_tool_calling FROM provider_profiles
                    WHERE provider_profiles.id = assistant_sessions.provider_profile_id
                )
            """
        )
        with op.batch_alter_table("assistant_sessions", recreate="always") as batch:
            batch.alter_column("model_id", existing_type=sa.String(200), nullable=False)
    else:
        op.execute(
            """
            UPDATE assistant_sessions
            SET model_id = provider_profiles.model_id,
                context_limit_override = provider_profiles.context_limit_override,
                supports_streaming = provider_profiles.supports_streaming,
                supports_tool_calling = provider_profiles.supports_tool_calling
            FROM provider_profiles
            WHERE provider_profiles.id = assistant_sessions.provider_profile_id
            """
        )
        op.alter_column("assistant_sessions", "model_id", nullable=False)

    op.drop_column("provider_profiles", "model_id")
    op.drop_column("provider_profiles", "context_limit_override")
    op.drop_column("provider_profiles", "supports_streaming")
    op.drop_column("provider_profiles", "supports_tool_calling")


def downgrade() -> None:
    # Structural revert only (matches sibling migrations): the empty-string
    # default just satisfies existing rows, since every real insert path in
    # the pre-this-migration code always supplied model_id explicitly.
    op.add_column(
        "provider_profiles",
        sa.Column("model_id", sa.String(200), nullable=False, server_default=""),
    )
    op.add_column("provider_profiles", sa.Column("context_limit_override", sa.Integer()))
    op.add_column(
        "provider_profiles",
        sa.Column("supports_streaming", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "provider_profiles",
        sa.Column("supports_tool_calling", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.drop_column("assistant_sessions", "model_id")
    op.drop_column("assistant_sessions", "context_limit_override")
    op.drop_column("assistant_sessions", "supports_streaming")
    op.drop_column("assistant_sessions", "supports_tool_calling")
