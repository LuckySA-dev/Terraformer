from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.logging import sanitize_text
from app.core.storage import EncryptedSnapshotStore
from app.core.time import new_uuid
from app.drivers import DriverRegistry
from app.models import ConfigSnapshot
from app.repositories.devices import DeviceRepository
from app.repositories.events import EventRepository
from app.repositories.snapshots import ConfigSnapshotRepository
from app.services.devices import DeviceService


class SnapshotService:
    def __init__(
        self,
        session: Session,
        *,
        store: EncryptedSnapshotStore,
        devices: DeviceService,
        drivers: DriverRegistry,
    ) -> None:
        self._session = session
        self._store = store
        self._device_service = devices
        self._drivers = drivers
        self._devices = DeviceRepository(session)
        self._snapshots = ConfigSnapshotRepository(session)
        self._events = EventRepository(session)

    def capture(self, device_id: UUID, *, job_id: UUID | None = None) -> ConfigSnapshot:
        device = self._devices.get(device_id, for_update=True)
        driver = self._drivers.get(device.vendor)
        parameters = self._device_service.connection_parameters(
            profile_id=device.credential_profile_id,
            host=device.management_address,
            port=device.port,
        )
        content = driver.get_running_config(parameters)
        snapshot_id = new_uuid()
        artifact = self._store.put(
            snapshot_id=snapshot_id,
            device_id=device.id,
            content=content,
        )
        snapshot = ConfigSnapshot(
            id=snapshot_id,
            device_id=device.id,
            artifact_path=artifact.relative_path,
            sha256=artifact.sha256,
            plaintext_size=artifact.plaintext_size,
            compressed_size=artifact.compressed_size,
            ciphertext_size=artifact.ciphertext_size,
        )
        self._snapshots.add(snapshot)
        self._events.record(
            event_type="config.snapshot_created",
            message="An immutable running-configuration snapshot was captured",
            device_id=device.id,
            job_id=job_id,
            details={"snapshot_id": str(snapshot.id), "sha256": snapshot.sha256},
        )
        self._session.commit()
        return snapshot

    def list(self, *, device_id: UUID | None = None, limit: int = 100) -> list[ConfigSnapshot]:
        if device_id is not None:
            self._devices.get(device_id)
        return self._snapshots.list(device_id=device_id, limit=limit)

    def get(self, snapshot_id: UUID) -> ConfigSnapshot:
        return self._snapshots.get(snapshot_id)

    def get_sanitized_content(self, snapshot_id: UUID) -> tuple[ConfigSnapshot, str]:
        snapshot = self._snapshots.get(snapshot_id)
        content = self._store.get(
            snapshot_id=snapshot.id,
            device_id=snapshot.device_id,
            relative_path=snapshot.artifact_path,
            expected_sha256=snapshot.sha256,
        )
        return snapshot, sanitize_text(content)
