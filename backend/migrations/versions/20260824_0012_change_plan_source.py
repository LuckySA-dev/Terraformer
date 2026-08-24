"""Add change_plans.source.

Revision ID: 20260824_0012
Revises: 20260824_0011
Create Date: 2026-08-24

Audit-only column distinguishing manually-drafted from AI-drafted Change
Plans. Does not alter validation, risk, or apply behavior -- see spec
docs/superpowers/specs/2026-08-24-phase-4-ai-assistant-design.md §2.6.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0012"
down_revision: str | None = "20260824_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SOURCE_VALUES = ("manual", "ai_generated")


def upgrade() -> None:
    op.add_column(
        "change_plans",
        sa.Column(
            "source",
            sa.Enum(*_SOURCE_VALUES, name="change_plan_source", native_enum=False, create_constraint=False),
            nullable=False,
            server_default="manual",
        ),
    )


def downgrade() -> None:
    op.drop_column("change_plans", "source")
