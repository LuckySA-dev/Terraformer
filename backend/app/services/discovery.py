from __future__ import annotations

import socket
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from time import monotonic, sleep
from typing import Literal
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.models import Device, JobState, JobType
from app.repositories.jobs import JobRepository
from app.schemas.devices import DeviceCreate
from app.schemas.discovery import DiscoveryCandidate, DiscoveryRequest, DiscoveryResult
from app.services.devices import DeviceService

ProbeStatus = Literal["ssh", "open_tcp"]
PortProbe = Callable[[str, int, float], ProbeStatus | None]


def tcp_service_probe(address: str, port: int, timeout: float) -> ProbeStatus | None:
    deadline = monotonic() + timeout
    try:
        connection = socket.create_connection((address, port), timeout=timeout)
    except OSError:
        return None
    try:
        with connection:
            banner = bytearray()
            try:
                while len(banner) < 512:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        return "open_tcp"
                    connection.settimeout(remaining)
                    chunk = connection.recv(512 - len(banner))
                    if not chunk:
                        break
                    banner.extend(chunk)
                    if any(line.startswith(b"SSH-") for line in banner.splitlines()):
                        return "ssh"
            except TimeoutError:
                return "open_tcp"
    except OSError:
        return "open_tcp"
    return "open_tcp"


def run_discovery(
    request: DiscoveryRequest,
    *,
    connection_limit: int,
    probe: PortProbe = tcp_service_probe,
) -> dict[str, object]:
    addresses = [str(address) for address in request.network().hosts()]
    concurrency = min(request.concurrency, connection_limit)
    futures: list[tuple[str, int, Future[ProbeStatus | None]]] = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        for address in addresses:
            for port in request.ports:
                futures.append(
                    (
                        address,
                        port,
                        executor.submit(
                            probe,
                            address,
                            port,
                            request.connect_timeout_seconds,
                        ),
                    )
                )
                if request.probe_delay_ms:
                    sleep(request.probe_delay_ms / 1_000)
    results = [
        (address, port, future.result()) for address, port, future in futures
    ]
    candidates = [
        DiscoveryCandidate(management_address=address, port=port)
        for address, port, result in results
        if result == "ssh"
    ]
    open_endpoints = [
        DiscoveryCandidate(management_address=address, port=port)
        for address, port, result in results
        if result == "open_tcp"
    ]
    return DiscoveryResult(
        cidr=request.cidr,
        ports=request.ports,
        scanned_count=len(addresses) * len(request.ports),
        concurrency=concurrency,
        candidates=candidates,
        open_endpoints=open_endpoints,
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
