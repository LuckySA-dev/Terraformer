from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api.dependencies import Authenticated, ContainerDependency, SessionDependency
from app.schemas.jobs import JobView
from app.services.jobs import JobService

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobView)
def get_job(
    job_id: UUID,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    return JobService(session, container.queue).get(job_id)

