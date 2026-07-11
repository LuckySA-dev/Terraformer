from fastapi import APIRouter

from app.api import credentials, devices, events, health, jobs, setup, snapshots

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(setup.router)
api_router.include_router(credentials.router)
api_router.include_router(devices.router)
api_router.include_router(snapshots.router)
api_router.include_router(events.router)
api_router.include_router(jobs.router)

