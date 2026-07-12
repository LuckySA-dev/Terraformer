from __future__ import annotations

import socket
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from time import sleep
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.models import Device, JobState, JobType
from app.repositories.jobs import JobRepository
from app.schemas.devices import DeviceCreate
from app.schemas.discovery import DiscoveryCandidate, DiscoveryRequest, DiscoveryResult
from app.services.devices import DeviceService

PortProbe = Callable[[str, int, float], bool]


def tcp_port_open(address: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((address, port), timeout=timeout):
            return True
    except OSError:
        return False


def run_discovery(
    request: DiscoveryRequest,
    *,
    connection_limit: int,
    probe: PortProbe = tcp_port_open,
) -> dict[str, object]:
    addresses = [str(address) for address in request.network().hosts()]
    concurrency = min(request.concurrency, connection_limit)
    futures: list[tuple[str, Future[bool]]] = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        for address in addresses:
            futures.append(
                (
                    address,
                    executor.submit(
                        probe,
                        address,
                        request.port,
                        request.connect_timeout_seconds,
                    ),
                )
            )
            if request.probe_delay_ms:
                sleep(request.probe_delay_ms / 1_000)
    candidates = [
        DiscoveryCandidate(management_address=address, port=request.port)
        for address, future in futures
        if future.result()
    ]
    return DiscoveryResult(
        cidr=request.cidr,
        port=request.port,
        scanned_count=len(addresses),
        concurrency=concurrency,
        candidates=candidates,
    ).model_dump(mode="json")


def approve_candidate(
    session: Session,
    *,
    job_id: UUID,
    request: DeviceCreate,
    devices: DeviceService,
) -> Device:
    job = JobRepository(session).get(job_id)
    if job.type != JobType.DISCOVER_SSH or job.state != JobState.SUCCEEDED:
        raise ConflictError("Only a completed discovery job can approve candidates")
    result = DiscoveryResult.model_validate(job.result)
    if not any(
        item.management_address == request.management_address and item.port == request.port
        for item in result.candidates
    ):
        raise ConflictError("The requested endpoint is not a discovery candidate")
    return devices.create(request, job_id=job.id)
