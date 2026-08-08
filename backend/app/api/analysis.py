from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, status

from app.analysis.service import AnalysisService
from app.api.dependencies import Authenticated, ContainerDependency, SessionDependency
from app.core.errors import AnalysisDisabledByPolicyError
from app.models import AnalysisSnapshot, FindingCategory, JobType
from app.repositories.analysis import AnalysisRepository
from app.schemas.analysis import AnalysisSnapshotView, FindingView
from app.schemas.jobs import JobView
from app.services.devices import DeviceService
from app.services.jobs import JobService
from app.services.snapshots import SnapshotService

router = APIRouter(prefix="/analysis-snapshots", tags=["analysis"])


def _require_enabled(container: ContainerDependency) -> None:
    if not container.settings.analysis_enabled:
        raise AnalysisDisabledByPolicyError()


def _service(session: SessionDependency, container: ContainerDependency) -> AnalysisService:
    devices = DeviceService(
        session,
        settings=container.settings,
        drivers=container.drivers,
        vault=container.credential_vault,
        host_key_trust=container.host_key_trust,
    )
    return AnalysisService(
        session,
        settings=container.settings,
        backend=container.analysis_client,
        snapshots=SnapshotService(
            session,
            store=container.snapshot_store,
            devices=devices,
            drivers=container.drivers,
        ),
    )


def _view(service: AnalysisService, snapshot: AnalysisSnapshot) -> AnalysisSnapshotView:
    return AnalysisSnapshotView(
        id=snapshot.id,
        status=snapshot.status,
        parse_warning_count=snapshot.parse_warning_count,
        findings_truncated=snapshot.findings_truncated,
        failure_code=snapshot.failure_code,
        completeness=service.completeness(snapshot),
        created_at=snapshot.created_at,
        updated_at=snapshot.updated_at,
    )


@router.post("", response_model=JobView, status_code=status.HTTP_202_ACCEPTED)
def start_analysis(
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    _require_enabled(container)
    # The snapshot row is created by the job, not here: a request rejected by
    # the one-at-a-time guard must not leave an orphan pending row.
    return JobService(session, container.queue).enqueue(
        job_type=JobType.ANALYZE_NETWORK,
    )


@router.get("", response_model=list[AnalysisSnapshotView])
def list_analysis_snapshots(
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    _require_enabled(container)
    service = _service(session, container)
    return [_view(service, snapshot) for snapshot in AnalysisRepository(session).list()]


@router.get("/{analysis_snapshot_id}", response_model=AnalysisSnapshotView)
def get_analysis_snapshot(
    analysis_snapshot_id: UUID,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    _require_enabled(container)
    service = _service(session, container)
    snapshot = AnalysisRepository(session).get(analysis_snapshot_id)
    return _view(service, snapshot)


@router.get("/{analysis_snapshot_id}/findings", response_model=list[FindingView])
def list_findings(
    analysis_snapshot_id: UUID,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
    category: FindingCategory | None = Query(default=None),
    device_id: UUID | None = Query(default=None),
):
    _require_enabled(container)
    return AnalysisRepository(session).list_findings(
        analysis_snapshot_id, category=category, device_id=device_id
    )
