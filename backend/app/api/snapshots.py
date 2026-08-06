from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query

from app.api.dependencies import Authenticated, ContainerDependency, SessionDependency
from app.schemas.snapshots import ConfigSnapshotContentView, ConfigSnapshotView
from app.services.devices import DeviceService
from app.services.snapshots import SnapshotService

router = APIRouter(prefix="/config-snapshots", tags=["config-snapshots"])


def _service(session: SessionDependency, container: ContainerDependency) -> SnapshotService:
    devices = DeviceService(
        session,
        settings=container.settings,
        drivers=container.drivers,
        vault=container.credential_vault,
        host_key_trust=container.host_key_trust,
    )
    return SnapshotService(
        session,
        store=container.snapshot_store,
        devices=devices,
        drivers=container.drivers,
    )


@router.get("", response_model=list[ConfigSnapshotView])
def list_snapshots(
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
    device_id: UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
):
    return _service(session, container).list(device_id=device_id, limit=limit)


@router.get("/{snapshot_id}", response_model=ConfigSnapshotContentView)
def get_snapshot(
    snapshot_id: UUID,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
) -> ConfigSnapshotContentView:
    snapshot, content = _service(session, container).get_sanitized_content(snapshot_id)
    metadata = ConfigSnapshotView.model_validate(snapshot).model_dump()
    return ConfigSnapshotContentView(**metadata, content=content)
