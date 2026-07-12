from __future__ import annotations

from uuid import UUID

import structlog

from app.container import get_default_container
from app.core.errors import AppError
from app.models import EventSeverity, JobType
from app.repositories.events import EventRepository
from app.repositories.jobs import JobRepository
from app.schemas.discovery import DiscoveryRequest
from app.services.devices import DeviceService
from app.services.discovery import run_discovery
from app.services.snapshots import SnapshotService

logger = structlog.get_logger(__name__)


def execute_job(job_id: str) -> dict[str, object]:
    parsed_job_id = UUID(job_id)
    container = get_default_container()
    with container.session_factory() as session:
        jobs = JobRepository(session)
        job = jobs.get(parsed_job_id, for_update=True)
        jobs.start(job)
        session.commit()

    try:
        with container.session_factory() as session:
            result: dict[str, object]
            devices = DeviceService(
                session,
                settings=container.settings,
                drivers=container.drivers,
                vault=container.credential_vault,
            )
            if job.type == JobType.REFRESH_DEVICE and job.device_id is not None:
                result = devices.refresh(job.device_id, job_id=job.id)
            elif job.type == JobType.CAPTURE_CONFIG and job.device_id is not None:
                snapshots = SnapshotService(
                    session,
                    store=container.snapshot_store,
                    devices=devices,
                    drivers=container.drivers,
                )
                snapshot = snapshots.capture(job.device_id, job_id=job.id)
                result = {"snapshot_id": str(snapshot.id), "device_id": str(snapshot.device_id)}
            elif job.type == JobType.DISCOVER_SSH and job.device_id is None:
                result = run_discovery(
                    DiscoveryRequest.model_validate(job.input),
                    connection_limit=container.settings.max_device_connections,
                )
            else:
                raise ValueError("Unsupported or incomplete job")
        with container.session_factory() as session:
            jobs = JobRepository(session)
            completed_job = jobs.get(parsed_job_id, for_update=True)
            jobs.succeed(completed_job, result)
            EventRepository(session).record(
                event_type="job.succeeded",
                message="Background device-read job completed",
                device_id=completed_job.device_id,
                job_id=completed_job.id,
                details={"job_type": completed_job.type.value},
            )
            session.commit()
        return result
    except Exception as exc:
        code = exc.code if isinstance(exc, AppError) else "job_execution_failed"
        message = exc.message if isinstance(exc, AppError) else "Background job execution failed"
        logger.exception("device_job_failed", job_id=job_id, error_code=code)
        with container.session_factory() as session:
            jobs = JobRepository(session)
            failed_job = jobs.get(parsed_job_id, for_update=True)
            jobs.fail(failed_job, code=code, message=message)
            EventRepository(session).record(
                event_type="job.failed",
                message=message,
                severity=EventSeverity.ERROR,
                device_id=failed_job.device_id,
                job_id=failed_job.id,
                details={"error_code": code},
            )
            session.commit()
        raise
