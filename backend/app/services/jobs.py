from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, QueueUnavailableError
from app.jobs.queue import JobQueue
from app.models import EventSeverity, Job, JobType
from app.repositories.devices import DeviceRepository
from app.repositories.events import EventRepository
from app.repositories.jobs import JobRepository

# Job types that must not run concurrently with themselves. Discovery touches
# many devices; analysis parses the whole configuration set and Batfish is a
# single instance.
_EXCLUSIVE_JOB_TYPES = {
    JobType.DISCOVER_SSH: "A discovery job is already active",
    JobType.ANALYZE_NETWORK: "An analysis job is already active",
}


class JobService:
    def __init__(self, session: Session, queue: JobQueue) -> None:
        self._session = session
        self._queue = queue
        self._jobs = JobRepository(session)
        self._devices = DeviceRepository(session)
        self._events = EventRepository(session)

    def get(self, job_id: UUID) -> Job:
        return self._jobs.get(job_id)

    def enqueue(
        self,
        *,
        job_type: JobType,
        device_id: UUID | None = None,
        input_data: dict[str, object] | None = None,
    ) -> Job:
        if job_type in _EXCLUSIVE_JOB_TYPES and self._jobs.has_active(job_type):
            raise ConflictError(_EXCLUSIVE_JOB_TYPES[job_type])
        if device_id is not None:
            self._devices.get(device_id)
        job = self._jobs.add(
            job_type=job_type,
            device_id=device_id,
            input_data=input_data,
        )
        self._events.record(
            event_type="job.queued",
            message="A background read job was queued",
            device_id=device_id,
            job_id=job.id,
            details={"job_type": job_type.value},
        )
        self._session.commit()
        try:
            rq_job_id = self._queue.enqueue(job)
        except QueueUnavailableError as exc:
            job = self._jobs.get(job.id, for_update=True)
            self._jobs.fail(job, code=exc.code, message=exc.message)
            self._events.record(
                event_type="job.failed",
                message=exc.message,
                severity=EventSeverity.ERROR,
                device_id=device_id,
                job_id=job.id,
                details={"error_code": exc.code},
            )
            self._session.commit()
            raise
        job = self._jobs.get(job.id, for_update=True)
        self._jobs.set_rq_id(job, rq_job_id)
        self._session.commit()
        return job
