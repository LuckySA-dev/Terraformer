from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies import Authenticated, ContainerDependency, SessionDependency
from app.changes.service import ChangeService
from app.core.errors import StructuredWritesDisabledError
from app.schemas.changes import ChangePlanRequest, ChangePlanView
from app.services.devices import DeviceService
from app.services.snapshots import SnapshotService


def _require_enabled(container: ContainerDependency) -> None:
    if not container.settings.structured_writes_enabled:
        raise StructuredWritesDisabledError()


# Applied to the whole router rather than per handler: the kill switch must
# hold for every change-plan route, including any added later.
router = APIRouter(
    prefix="/change-plans",
    tags=["changes"],
    dependencies=[Depends(_require_enabled)],
)


def _service(session: SessionDependency, container: ContainerDependency) -> ChangeService:
    # connection_gate is required here (unlike app/api/analysis.py's version of
    # this helper): preview() calls admitted_connection() directly in the
    # synchronous request path, not only from inside an async job -- omitting
    # it makes DeviceService.admitted_connection fail closed with
    # ConnectionGateUnavailableError on every call.
    devices = DeviceService(
        session,
        settings=container.settings,
        drivers=container.drivers,
        vault=container.credential_vault,
        host_key_trust=container.host_key_trust,
        connection_gate=container.connection_gate,
    )
    return ChangeService(
        session,
        settings=container.settings,
        drivers=container.drivers,
        devices=devices,
        snapshots=SnapshotService(
            session,
            store=container.snapshot_store,
            devices=devices,
            drivers=container.drivers,
        ),
    )


@router.post("", response_model=ChangePlanView, status_code=status.HTTP_201_CREATED)
def preview_change(
    request: ChangePlanRequest,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    return _service(session, container).preview(
        device_id=request.device_id,
        change_type=request.change_type,
        target=request.target,
        desired_value=request.desired_value,
    )


@router.get("/{change_plan_id}", response_model=ChangePlanView)
def get_change_plan(
    change_plan_id: UUID,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    return _service(session, container).get(change_plan_id)


@router.get("", response_model=list[ChangePlanView])
def list_change_plans(
    device_id: UUID,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    return _service(session, container).list_for_device(device_id)
