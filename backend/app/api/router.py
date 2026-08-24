from fastapi import APIRouter

from app.api import (
    analysis,
    assistant,
    changes,
    credentials,
    devices,
    diagnostics,
    discovery,
    events,
    health,
    jobs,
    provider_profiles,
    setup,
    snapshots,
    ssh_trust,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(setup.router)
api_router.include_router(credentials.router)
api_router.include_router(provider_profiles.router)
api_router.include_router(assistant.sessions_router)
api_router.include_router(devices.router)
api_router.include_router(diagnostics.router)
api_router.include_router(discovery.router)
api_router.include_router(snapshots.router)
api_router.include_router(ssh_trust.router)
api_router.include_router(analysis.router)
api_router.include_router(changes.router)
api_router.include_router(events.router)
api_router.include_router(jobs.router)
