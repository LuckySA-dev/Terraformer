from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import SnapshotImmutableError
from app.models import (
    ConfigSnapshot,
    CredentialProfile,
    Device,
    DeviceStatus,
    SSHCompatibility,
    Vendor,
)


def test_snapshot_rows_reject_update_and_delete(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        profile = CredentialProfile(
            name="fixture",
            encrypted_secret=b"encrypted",
            has_username=True,
            has_password=True,
            has_enable_password=False,
        )
        session.add(profile)
        session.flush()
        device = Device(
            name="fixture",
            management_address="192.0.2.20",
            port=22,
            vendor=Vendor.CISCO_IOSXE,
            status=DeviceStatus.REACHABLE,
            credential_profile_id=profile.id,
            facts={},
        )
        session.add(device)
        session.flush()
        snapshot = ConfigSnapshot(
            id=uuid4(),
            device_id=device.id,
            artifact_path="fixture/path",
            sha256="0" * 64,
            plaintext_size=1,
            compressed_size=1,
            ciphertext_size=1,
        )
        session.add(snapshot)
        session.commit()

        snapshot.source = "changed"
        with pytest.raises(SnapshotImmutableError):
            session.flush()
        session.rollback()

        snapshot = session.get(ConfigSnapshot, snapshot.id)
        assert snapshot is not None
        session.delete(snapshot)
        with pytest.raises(SnapshotImmutableError):
            session.flush()
        session.rollback()


def test_device_compatibility_defaults_to_modern(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        profile = CredentialProfile(
            name="compatibility-fixture",
            encrypted_secret=b"encrypted",
        )
        session.add(profile)
        session.flush()
        device = Device(
            name="compatibility-fixture",
            management_address="192.0.2.21",
            vendor=Vendor.CISCO_IOSXE,
            credential_profile_id=profile.id,
            facts={},
        )
        session.add(device)
        session.flush()

        assert device.ssh_compatibility is SSHCompatibility.MODERN
