"""Add provider_profiles for the AI assistant gateway.

Revision ID: 20260824_0010
Revises: 20260809_0009
Create Date: 2026-08-24

BYOK provider profiles: a base URL, model id, and optional encrypted API key
(spec: docs/superpowers/specs/2026-08-24-phase-4-ai-assistant-design.md).
No key is required -- "no-key local mode" is a valid configuration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0010"
down_revision: str | None = "20260809_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_profiles",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("model_id", sa.String(200), nullable=False),
        sa.Column("encrypted_api_key", sa.LargeBinary()),
        sa.Column("context_limit_override", sa.Integer()),
        sa.Column("supports_streaming", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("supports_tool_calling", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("provider_profiles")
