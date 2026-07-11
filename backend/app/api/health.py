from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.dependencies import ContainerDependency

router = APIRouter(tags=["health"])


@router.get("/health")
def health(container: ContainerDependency) -> JSONResponse:
    checks: dict[str, dict[str, Any]] = {}
    try:
        with container.session_factory() as session:
            session.execute(text("SELECT 1"))
        checks["database"] = {"status": "ok"}
        database_ok = True
    except Exception:
        checks["database"] = {"status": "unavailable"}
        database_ok = False

    redis_ok = container.queue.ping()
    checks["redis"] = {"status": "ok" if redis_ok else "unavailable"}
    worker_ok = redis_ok and container.queue.has_workers()
    checks["worker"] = {"status": "ok" if worker_ok else "unavailable"}

    required_ok = database_ok and redis_ok
    if container.settings.require_worker_for_readiness:
        required_ok = required_ok and worker_ok
    if not required_ok:
        status = "unavailable"
    elif worker_ok:
        status = "ok"
    else:
        status = "degraded"
    status_code = 200 if required_ok else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": status,
            "version": container.settings.app_version,
            "checks": checks,
        },
    )
