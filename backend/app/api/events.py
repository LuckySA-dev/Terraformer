from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query

from app.api.dependencies import Authenticated, SessionDependency
from app.repositories.events import EventRepository
from app.schemas.events import EventView

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[EventView])
def list_events(
    _auth: Authenticated,
    session: SessionDependency,
    device_id: UUID | None = None,
    job_id: UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
):
    return EventRepository(session).list(device_id=device_id, job_id=job_id, limit=limit)

