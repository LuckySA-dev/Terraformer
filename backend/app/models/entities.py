from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.errors import SnapshotImmutableError
from app.core.time import utc_now
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Vendor(StrEnum):
    CISCO_IOSXE = "cisco_iosxe"
    GENERIC = "generic"


class DeviceStatus(StrEnum):
    UNKNOWN = "unknown"
    REACHABLE = "reachable"
    UNREACHABLE = "unreachable"


class SafetyLevel(StrEnum):
    READ_ONLY = "D"


class JobType(StrEnum):
    REFRESH_DEVICE = "refresh_device"
    CAPTURE_CONFIG = "capture_config"
    DISCOVER_SSH = "discover_ssh"


class JobState(StrEnum):
    QUEUED = "queued"
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EventSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


def _enum_values(enum_class: type[StrEnum]) -> list[str]:
    return [item.value for item in enum_class]


def enum_type(enum_class: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum_class,
        name=name,
        native_enum=False,
        values_callable=_enum_values,
        validate_strings=True,
    )


class AppSetting(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "app_settings"

    singleton_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    master_password_hash: Mapped[str] = mapped_column(String(512), nullable=False)


class CredentialProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "credential_profiles"

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    encrypted_secret: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    secret_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    has_username: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    has_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    has_enable_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    devices: Mapped[list[Device]] = relationship(back_populates="credential_profile")


class Device(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "devices"
    __table_args__ = (
        UniqueConstraint("management_address", "port", name="uq_devices_address_port"),
        CheckConstraint("port >= 1 AND port <= 65535", name="ck_devices_valid_port"),
        Index("ix_devices_status", "status"),
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    management_address: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=22)
    vendor: Mapped[Vendor] = mapped_column(enum_type(Vendor, "vendor"), nullable=False)
    status: Mapped[DeviceStatus] = mapped_column(
        enum_type(DeviceStatus, "device_status"),
        nullable=False,
        default=DeviceStatus.UNKNOWN,
    )
    credential_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("credential_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    facts: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(100))

    credential_profile: Mapped[CredentialProfile] = relationship(back_populates="devices")
    capabilities: Mapped[list[DeviceCapability]] = relationship(
        back_populates="device",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    interfaces: Mapped[list[Interface]] = relationship(
        back_populates="device",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    neighbors: Mapped[list[Neighbor]] = relationship(
        back_populates="device",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    snapshots: Mapped[list[ConfigSnapshot]] = relationship(back_populates="device")


class DeviceCapability(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "device_capabilities"
    __table_args__ = (
        UniqueConstraint("device_id", "name", name="uq_device_capability_name"),
    )

    device_id: Mapped[UUID] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    supported: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    safety_level: Mapped[SafetyLevel] = mapped_column(
        enum_type(SafetyLevel, "safety_level"),
        nullable=False,
        default=SafetyLevel.READ_ONLY,
    )

    device: Mapped[Device] = relationship(back_populates="capabilities")


class Interface(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "interfaces"
    __table_args__ = (UniqueConstraint("device_id", "name", name="uq_interface_device_name"),)

    device_id: Mapped[UUID] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1024))
    admin_up: Mapped[bool | None] = mapped_column(Boolean)
    oper_up: Mapped[bool | None] = mapped_column(Boolean)
    mac_address: Mapped[str | None] = mapped_column(String(64))
    ipv4_addresses: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    speed_mbps: Mapped[int | None] = mapped_column(BigInteger)

    device: Mapped[Device] = relationship(back_populates="interfaces")


class Neighbor(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "neighbors"
    __table_args__ = (
        UniqueConstraint(
            "device_id",
            "protocol",
            "local_interface",
            "remote_device_name",
            "remote_interface",
            name="uq_neighbor_observation",
        ),
    )

    device_id: Mapped[UUID] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    protocol: Mapped[str] = mapped_column(String(16), nullable=False)
    local_interface: Mapped[str] = mapped_column(String(255), nullable=False)
    remote_device_name: Mapped[str] = mapped_column(String(255), nullable=False)
    remote_interface: Mapped[str] = mapped_column(String(255), nullable=False)
    management_address: Mapped[str | None] = mapped_column(String(255))
    platform: Mapped[str | None] = mapped_column(String(255))

    device: Mapped[Device] = relationship(back_populates="neighbors")


class ConfigSnapshot(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "config_snapshots"
    __table_args__ = (
        CheckConstraint("plaintext_size >= 0", name="ck_snapshot_plaintext_size"),
        Index("ix_config_snapshots_device_created", "device_id", "created_at"),
    )

    device_id: Mapped[UUID] = mapped_column(
        ForeignKey("devices.id", ondelete="RESTRICT"),
        nullable=False,
    )
    artifact_path: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    plaintext_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    compressed_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ciphertext_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    compression: Mapped[str] = mapped_column(String(32), nullable=False, default="gzip")
    encryption: Mapped[str] = mapped_column(String(32), nullable=False, default="AES-256-GCM")
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="running-config")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    device: Mapped[Device] = relationship(back_populates="snapshots")


@event.listens_for(ConfigSnapshot, "before_update", propagate=True)
def _reject_snapshot_update(  # pyright: ignore[reportUnusedFunction]
    *_: object,
) -> None:
    raise SnapshotImmutableError()


@event.listens_for(ConfigSnapshot, "before_delete", propagate=True)
def _reject_snapshot_delete(  # pyright: ignore[reportUnusedFunction]
    *_: object,
) -> None:
    raise SnapshotImmutableError()


class Job(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_state_created", "state", "created_at"),)

    rq_job_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    type: Mapped[JobType] = mapped_column(enum_type(JobType, "job_type"), nullable=False)
    state: Mapped[JobState] = mapped_column(
        enum_type(JobState, "job_state"),
        nullable=False,
        default=JobState.QUEUED,
    )
    device_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL"),
        index=True,
    )
    input: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Event(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_device_created", "device_id", "created_at"),)

    device_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL"),
        index=True,
    )
    job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"),
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[EventSeverity] = mapped_column(
        enum_type(EventSeverity, "event_severity"),
        nullable=False,
        default=EventSeverity.INFO,
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
