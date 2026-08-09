from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.core.logging import sanitize_text
from app.core.time import utc_now
from app.models import Job, JobState, JobType

_TERMINAL_STATES = frozenset({JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED})


class JobRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(
        self,
        *,
        job_type: JobType,
        device_id: UUID | None,
        input_data: dict[str, object] | None = None,
    ) -> Job:
        job = Job(
            type=job_type,
            device_id=device_id,
            state=JobState.QUEUED,
            input=input_data or {},
        )
        self._session.add(job)
        self._session.flush()
        return job

    def get(self, job_id: UUID, *, for_update: bool = False) -> Job:
        statement = select(Job).where(Job.id == job_id)
        if for_update:
            statement = statement.with_for_update()
        job = self._session.scalar(statement)
        if job is None:
            raise NotFoundError(
                "Job not found",
                details={"resource": "job", "id": str(job_id)},
            )
        return job

    def has_active(self, job_type: JobType, *, device_id: UUID | None = None) -> bool:
        statement = (
            select(Job.id)
            .where(
                Job.type == job_type,
                Job.state.in_((JobState.QUEUED, JobState.STARTED)),
            )
            .limit(1)
        )
        if device_id is not None:
            statement = statement.where(Job.device_id == device_id)
        return self._session.scalar(statement) is not None

    def set_rq_id(self, job: Job, rq_job_id: str) -> None:
        job.rq_job_id = rq_job_id
        self._session.flush()

    def start(self, job: Job) -> None:
        if job.state != JobState.QUEUED:
            raise ConflictError(
                "Only queued jobs can be started",
                details={"state": job.state.value},
            )
        job.state = JobState.STARTED
        job.started_at = utc_now()
        self._session.flush()

    def succeed(self, job: Job, result: dict[str, object]) -> None:
        if job.state in _TERMINAL_STATES:
            raise ConflictError("Job has already completed")
        job.state = JobState.SUCCEEDED
        job.result = result
        job.finished_at = utc_now()
        self._session.flush()

    def fail(self, job: Job, *, code: str, message: str) -> None:
        if job.state in _TERMINAL_STATES:
            return
        job.state = JobState.FAILED
        job.error_code = code[:100]
        job.error_message = sanitize_text(message)[:4_000]
        job.finished_at = utc_now()
        self._session.flush()
