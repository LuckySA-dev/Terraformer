"""Add read-only configuration analysis tables.

Revision ID: 20260808_0008
Revises: 20260806_0005
Create Date: 2026-08-08

Adds analysis_snapshots, analysis_snapshot_members and analysis_findings.

Also widens jobs.type from VARCHAR(14) to fit 'analyze_network' (15 chars).
jobs.type was created in 20260711_0001 sized to the two original JobType
values ('refresh_device', 'capture_config', both 14 chars). 'discover_ssh' and
'run_diagnostic' were added to the Python enum later without a migration, and
both happen to fit within 14 characters, so nothing broke. 'analyze_network' is
15 characters and does not fit: the same class of bug as the devices.vendor
VARCHAR(11) issue fixed in 20260806_0005/0007, caught here by `alembic check`
before it could reach PostgreSQL. No CHECK constraint exists on this column
(app.models.entities.enum_type does not set create_constraint), so only the
column width needs to change.

Note on down_revision: this migration was developed on a branch created before
20260808_0006 (lab devices) and 20260808_0007 (enum column repair) existed on
`main`. When these branches are reconciled, down_revision here must be updated
to point at whichever of those lands last, and this revision id must remain
after both in the chain.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260808_0008"
down_revision: str | None = "20260806_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JOB_TYPES_OLD = ("refresh_device", "capture_config", "discover_ssh", "run_diagnostic")
_JOB_TYPES_NEW = (*_JOB_TYPES_OLD, "analyze_network")


def _job_type(values: Sequence[str]) -> sa.Enum:
    # native_enum=False renders VARCHAR sized to the longest value; no
    # create_constraint here either, matching app.models.entities.enum_type.
    return sa.Enum(*values, name="job_type", native_enum=False)


def _widen_jobs_type(*, new_values: Sequence[str], old_values: Sequence[str]) -> None:
    new_type = _job_type(new_values)
    old_type = _job_type(old_values)
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("jobs", recreate="always") as batch:
            batch.alter_column(
                "type", type_=new_type, existing_type=old_type, existing_nullable=False
            )
        return
    op.alter_column("jobs", "type", type_=new_type, existing_type=old_type, existing_nullable=False)

_STATUS = ("pending", "parsing", "ready", "failed", "expired")
_EXCLUSION = ("no_snapshot", "unsupported_vendor")
_CATEGORY = (
    "parse_warning",
    "undefined_reference",
    "unused_structure",
    "topology_drift",
)
_SEVERITY = ("info", "warning", "error")


def _enum(name: str, values: Sequence[str]) -> sa.Enum:
    # create_constraint=False matches app/models/entities.py, so `alembic check`
    # reports no drift. Allowed values are enforced by explicit CHECK
    # constraints below, under canonical ck_<table>_<column> names.
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=False)


def upgrade() -> None:
    _widen_jobs_type(new_values=_JOB_TYPES_NEW, old_values=_JOB_TYPES_OLD)
    op.create_table(
        "analysis_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("status", _enum("analysis_status", _STATUS), nullable=False),
        sa.Column("device_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("observed_link_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("oldest_config_at", sa.DateTime(timezone=True)),
        sa.Column("newest_config_at", sa.DateTime(timezone=True)),
        sa.Column("parse_warning_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "findings_truncated", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("failure_code", sa.String(length=100)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ({})".format(", ".join(f"'{v}'" for v in _STATUS)),
            name="ck_analysis_snapshots_status",
        ),
    )
    op.create_table(
        "analysis_snapshot_members",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("analysis_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("config_snapshot_id", sa.Uuid()),
        sa.Column("batfish_hostname", sa.String(length=255)),
        sa.Column("exclusion_reason", _enum("exclusion_reason", _EXCLUSION)),
        sa.ForeignKeyConstraint(
            ["analysis_snapshot_id"], ["analysis_snapshots.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["config_snapshot_id"], ["config_snapshots.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "analysis_snapshot_id", "device_id", name="uq_analysis_member_device"
        ),
        sa.CheckConstraint(
            "exclusion_reason IS NULL OR exclusion_reason IN ({})".format(
                ", ".join(f"'{v}'" for v in _EXCLUSION)
            ),
            name="ck_analysis_snapshot_members_exclusion_reason",
        ),
    )
    op.create_index(
        "ix_analysis_snapshot_members_analysis_snapshot_id",
        "analysis_snapshot_members",
        ["analysis_snapshot_id"],
    )
    op.create_index(
        "ix_analysis_snapshot_members_device_id",
        "analysis_snapshot_members",
        ["device_id"],
    )
    op.create_table(
        "analysis_findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("analysis_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("category", _enum("finding_category", _CATEGORY), nullable=False),
        sa.Column("severity", _enum("event_severity", _SEVERITY), nullable=False),
        sa.Column("device_id", sa.Uuid()),
        sa.Column("structure_type", sa.String(length=100)),
        sa.Column("structure_name", sa.String(length=255)),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("line_number", sa.Integer()),
        sa.ForeignKeyConstraint(
            ["analysis_snapshot_id"], ["analysis_snapshots.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "category IN ({})".format(", ".join(f"'{v}'" for v in _CATEGORY)),
            name="ck_analysis_findings_category",
        ),
    )
    op.create_index(
        "ix_analysis_findings_analysis_snapshot_id",
        "analysis_findings",
        ["analysis_snapshot_id"],
    )
    op.create_index("ix_analysis_findings_device_id", "analysis_findings", ["device_id"])
    op.create_index(
        "ix_analysis_findings_snapshot_category",
        "analysis_findings",
        ["analysis_snapshot_id", "category"],
    )


def downgrade() -> None:
    op.drop_table("analysis_findings")
    op.drop_table("analysis_snapshot_members")
    op.drop_table("analysis_snapshots")
    # Narrows the column back. This fails loudly (does not truncate) if any
    # row still holds 'analyze_network', matching the precedent set by the
    # vendor/ssh_compatibility narrowing in 20260806_0005.
    _widen_jobs_type(new_values=_JOB_TYPES_OLD, old_values=_JOB_TYPES_NEW)
