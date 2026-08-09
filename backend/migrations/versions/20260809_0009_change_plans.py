"""Add change_plans and change_steps for structured configuration writes.

Revision ID: 20260809_0009
Revises: 20260808_0007
Create Date: 2026-08-09

Adds change_plans and change_steps: the first structured write capability's
data model (spec: docs/superpowers/specs/2026-08-09-phase-3-safe-configuration-design.md).

jobs.type is NOT widened here. The new JobType member is 'apply_change' (12
characters), which fits inside the existing VARCHAR(15) sizing (set in
20260808_0008 to fit 'analyze_network', 15 characters) without further
change. Confirmed by `alembic check` after this migration, not assumed.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260809_0009"
down_revision: str | None = "20260808_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUS_VALUES = ("draft", "applying", "applied", "failed", "rolled_back", "rollback_failed")
_RISK_VALUES = ("low", "high")
_TYPE_VALUES = ("interface_description", "interface_admin_state")
_SAFETY_VALUES = ("D", "C")


def _enum(name: str, values: Sequence[str]) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=False)


def upgrade() -> None:
    op.create_table(
        "change_plans",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "device_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("devices.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", _enum("change_plan_status", _STATUS_VALUES), nullable=False),
        sa.Column("safety_level", _enum("safety_level", _SAFETY_VALUES), nullable=False),
        sa.Column("risk", _enum("change_risk", _RISK_VALUES), nullable=False),
        sa.Column(
            "pre_change_snapshot_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("config_snapshots.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "post_change_snapshot_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("config_snapshots.id", ondelete="RESTRICT"),
        ),
        sa.Column("failure_code", sa.String(100)),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_change_plans_device_id", "change_plans", ["device_id"])

    op.create_table(
        "change_steps",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "change_plan_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("change_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("change_type", _enum("change_type", _TYPE_VALUES), nullable=False),
        sa.Column("target", sa.String(64), nullable=False),
        sa.Column("previous_value", sa.String(255)),
        sa.Column("desired_value", sa.String(255), nullable=False),
        sa.Column("rendered_commands", sa.Text(), nullable=False),
        sa.Column("inverse_commands", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_change_steps_change_plan_id", "change_steps", ["change_plan_id"])


def downgrade() -> None:
    op.drop_table("change_steps")
    op.drop_table("change_plans")
