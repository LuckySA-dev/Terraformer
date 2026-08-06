from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from app.api.dependencies import Authenticated, ContainerDependency, SessionDependency
from app.models import JobType
from app.schemas.devices import DeviceCreate, DeviceView
from app.schemas.discovery import DiscoveryRequest
from app.schemas.jobs import JobView
from app.services.devices import DeviceService
from app.services.discovery import approve_candidate
from app.services.jobs import JobService

router = APIRouter(prefix="/discovery-jobs", tags=["discovery"])


@router.post("", response_model=JobView, status_code=status.HTTP_202_ACCEPTED)
def start_discovery(
    request: DiscoveryRequest,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    return JobService(session, container.queue).enqueue(
        job_type=JobType.DISCOVER_SSH,
        input_data=request.model_dump(mode="json"),
    )


@router.post("/{job_id}/approve", response_model=DeviceView, status_code=status.HTTP_201_CREATED)
def approve_discovery_candidate(
    job_id: UUID,
    request: DeviceCreate,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    devices = DeviceService(
        session,
        settings=container.settings,
        drivers=container.drivers,
        vault=container.credential_vault,
        host_key_trust=container.host_key_trust,
        connection_gate=container.connection_gate,
    )
    return approve_candidate(session, job_id=job_id, request=request, devices=devices)
