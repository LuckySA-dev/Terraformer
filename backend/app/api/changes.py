from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies import Authenticated, ContainerDependency, SessionDependency
from app.changes.service import ChangeService
from app.core.errors import (
    AutoApplyLimitReachedError,
    ChangePlanDeviceLockedError,
    ChangePlanNotDraftError,
    StructuredWritesDisabledError,
)
from app.models import AssistantSession, AssistantSessionMode, ChangePlanStatus, JobType
from app.repositories.assistant import (
    MAX_AUTO_APPLIES_PER_SESSION,
    AssistantSessionRepository,
)
from app.repositories.jobs import JobRepository
from app.schemas.changes import (
    ChangeApplyJobInput,
    ChangeApplyRequest,
    ChangePlanRequest,
    ChangePlanView,
)
from app.schemas.jobs import JobView
from app.services.devices import DeviceService
from app.services.jobs import JobService
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


@router.post(
    "/{change_plan_id}/apply", response_model=JobView, status_code=status.HTTP_202_ACCEPTED
)
def apply_change_plan(
    change_plan_id: UUID,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
    request: ChangeApplyRequest | None = None,
):
    plan = _service(session, container).get(change_plan_id)
    # An apply the operator clicked and an apply Auto mode fired look
    # identical by the time they reach this endpoint. Only the second one is
    # rate-limited, so the caller says which it is -- and the count that
    # limits it lives in the database, not the browser.
    assistant_session_id = request.assistant_session_id if request is not None else None
    chat_session: AssistantSession | None = None
    if assistant_session_id is not None:
        sessions = AssistantSessionRepository(session)
        chat_session = sessions.get(assistant_session_id, for_update=True)
        if chat_session.mode is AssistantSessionMode.AUTO:
            if chat_session.auto_apply_count >= MAX_AUTO_APPLIES_PER_SESSION:
                raise AutoApplyLimitReachedError()
        else:
            chat_session = None
    # Both checks must be synchronous, here, not only inside ChangeService.apply():
    # that method only runs once the job executes, which could be arbitrarily
    # later (or never observed by this request at all) -- a caller retrying
    # /apply on an already-applied plan must get 409 immediately, not a 202
    # for a job that will later discover the problem on its own.
    if plan.status is not ChangePlanStatus.DRAFT:
        raise ChangePlanNotDraftError()
    # The device-scoped lock check lives here, not in JobService: it needs
    # the typed ChangePlanDeviceLockedError (a changes-domain error), and
    # JobService is shared across discovery/analysis/diagnostics/refresh/
    # capture and stays domain-agnostic on purpose.
    if JobRepository(session).has_active(JobType.APPLY_CHANGE, device_id=plan.device_id):
        raise ChangePlanDeviceLockedError()
    job_input = ChangeApplyJobInput(change_plan_id=change_plan_id)
    job = JobService(session, container.queue).enqueue(
        job_type=JobType.APPLY_CHANGE,
        device_id=plan.device_id,
        input_data=job_input.model_dump(mode="json"),
    )
    # Counted only once the apply is actually queued, so a plan rejected by
    # the checks above does not burn part of the operator's allowance.
    if chat_session is not None:
        AssistantSessionRepository(session).record_auto_apply(chat_session)
        session.commit()
    return job
