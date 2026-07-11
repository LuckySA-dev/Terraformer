"""Phase 0-1 safety foundation and first-device inventory.

Revision ID: 20260711_0001
Revises: None
Create Date: 2026-07-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260711_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("singleton_key", sa.String(length=64), nullable=False),
        sa.Column("master_password_hash", sa.String(length=512), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("singleton_key"),
    )
    op.create_table(
        "credential_profiles",
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("encrypted_secret", sa.LargeBinary(), nullable=False),
        sa.Column("secret_version", sa.Integer(), nullable=False),
        sa.Column("has_username", sa.Boolean(), nullable=False),
        sa.Column("has_password", sa.Boolean(), nullable=False),
        sa.Column("has_enable_password", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "devices",
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("management_address", sa.String(length=255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column(
            "vendor",
            sa.Enum("cisco_iosxe", "generic", name="vendor", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("unknown", "reachable", "unreachable", name="device_status", native_enum=False),
            nullable=False,
        ),
        sa.Column("credential_profile_id", sa.Uuid(), nullable=False),
        sa.Column("facts", sa.JSON(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=100), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("port >= 1 AND port <= 65535", name="ck_devices_valid_port"),
        sa.ForeignKeyConstraint(
            ["credential_profile_id"], ["credential_profiles.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("management_address", "port", name="uq_devices_address_port"),
    )
    op.create_index("ix_devices_credential_profile_id", "devices", ["credential_profile_id"])
    op.create_index("ix_devices_status", "devices", ["status"])
    op.create_table(
        "device_capabilities",
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("supported", sa.Boolean(), nullable=False),
        sa.Column(
            "safety_level",
            sa.Enum("D", name="safety_level", native_enum=False),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id", "name", name="uq_device_capability_name"),
    )
    op.create_index("ix_device_capabilities_device_id", "device_capabilities", ["device_id"])
    op.create_table(
        "interfaces",
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=True),
        sa.Column("admin_up", sa.Boolean(), nullable=True),
        sa.Column("oper_up", sa.Boolean(), nullable=True),
        sa.Column("mac_address", sa.String(length=64), nullable=True),
        sa.Column("ipv4_addresses", sa.JSON(), nullable=False),
        sa.Column("speed_mbps", sa.BigInteger(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id", "name", name="uq_interface_device_name"),
    )
    op.create_index("ix_interfaces_device_id", "interfaces", ["device_id"])
    op.create_table(
        "config_snapshots",
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_path", sa.String(length=1024), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("plaintext_size", sa.BigInteger(), nullable=False),
        sa.Column("compressed_size", sa.BigInteger(), nullable=False),
        sa.Column("ciphertext_size", sa.BigInteger(), nullable=False),
        sa.Column("compression", sa.String(length=32), nullable=False),
        sa.Column("encryption", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("plaintext_size >= 0", name="ck_snapshot_plaintext_size"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artifact_path"),
    )
    op.create_index(
        "ix_config_snapshots_device_created",
        "config_snapshots",
        ["device_id", "created_at"],
    )
    op.create_table(
        "jobs",
        sa.Column("rq_job_id", sa.String(length=64), nullable=True),
        sa.Column(
            "type",
            sa.Enum("refresh_device", "capture_config", name="job_type", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "state",
            sa.Enum(
                "queued",
                "started",
                "succeeded",
                "failed",
                "cancelled",
                name="job_state",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("input", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rq_job_id"),
    )
    op.create_index("ix_jobs_device_id", "jobs", ["device_id"])
    op.create_index("ix_jobs_state_created", "jobs", ["state", "created_at"])
    op.create_table(
        "events",
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column(
            "severity",
            sa.Enum("info", "warning", "error", name="event_severity", native_enum=False),
            nullable=False,
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_events_device_created", "events", ["device_id", "created_at"])
    op.create_index("ix_events_device_id", "events", ["device_id"])
    op.create_index("ix_events_job_id", "events", ["job_id"])

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION reject_config_snapshot_mutation() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'config snapshots are immutable';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER config_snapshots_immutable
            BEFORE UPDATE OR DELETE ON config_snapshots
            FOR EACH ROW EXECUTE FUNCTION reject_config_snapshot_mutation()
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS config_snapshots_immutable ON config_snapshots")
        op.execute("DROP FUNCTION IF EXISTS reject_config_snapshot_mutation()")
    op.drop_index("ix_events_job_id", table_name="events")
    op.drop_index("ix_events_device_id", table_name="events")
    op.drop_index("ix_events_device_created", table_name="events")
    op.drop_table("events")
    op.drop_index("ix_jobs_state_created", table_name="jobs")
    op.drop_index("ix_jobs_device_id", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_config_snapshots_device_created", table_name="config_snapshots")
    op.drop_table("config_snapshots")
    op.drop_index("ix_interfaces_device_id", table_name="interfaces")
    op.drop_table("interfaces")
    op.drop_index("ix_device_capabilities_device_id", table_name="device_capabilities")
    op.drop_table("device_capabilities")
    op.drop_index("ix_devices_status", table_name="devices")
    op.drop_index("ix_devices_credential_profile_id", table_name="devices")
    op.drop_table("devices")
    op.drop_table("credential_profiles")
    op.drop_table("app_settings")

