"""Add provider_profiles.provider_type.

Revision ID: 20260827_0014
Revises: 20260825_0013
Create Date: 2026-08-27

Selects which client adapter serves a profile (final plan section 9,
"Provider profile fields"). Everything speaking the OpenAI Chat Completions
wire format shares one adapter and differs only by base URL; Anthropic's own
API does not, so it gets its own. Existing rows are all OpenAI-compatible --
that was the only adapter before this revision -- so the server default
backfills them correctly.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_0014"
down_revision: str | None = "20260825_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROVIDER_TYPE_VALUES = ("openai_compatible", "anthropic")


def upgrade() -> None:
    op.add_column(
        "provider_profiles",
        sa.Column(
            "provider_type",
            sa.Enum(
                *_PROVIDER_TYPE_VALUES,
                name="provider_type",
                native_enum=False,
                create_constraint=False,
            ),
            nullable=False,
            server_default="openai_compatible",
        ),
    )


def downgrade() -> None:
    op.drop_column("provider_profiles", "provider_type")
