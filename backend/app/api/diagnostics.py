from __future__ import annotations

from fastapi import APIRouter, status

from app.api.dependencies import Authenticated, ContainerDependency, SessionDependency
from app.core.errors import UnsupportedCapabilityError
from app.drivers import DIAGNOSTIC_CAPABILITIES
from app.models import JobType
from app.schemas.diagnostics import DiagnosticJobInput, DiagnosticRequest
from app.schemas.jobs import JobView
from app.services.devices import DeviceService
from app.services.jobs import JobService

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


@router.post("", response_model=JobView, status_code=status.HTTP_202_ACCEPTED)
def run_diagnostic(
    request: DiagnosticRequest,
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
    )
    device = devices.get(request.device_id)
    driver = container.drivers.get(device.vendor)
    capability = DIAGNOSTIC_CAPABILITIES[request.action]
    if not driver.capabilities.supports(capability):
        raise UnsupportedCapabilityError(
            details={"driver": driver.name, "capability": capability.value}
        )
    job_input = DiagnosticJobInput(action=request.action, target=request.target)
    return JobService(session, container.queue).enqueue(
        job_type=JobType.RUN_DIAGNOSTIC,
        device_id=device.id,
        input_data=job_input.model_dump(mode="json", exclude_none=True),
    )
