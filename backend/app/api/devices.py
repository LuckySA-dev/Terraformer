from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Response, status

from app.api.dependencies import Authenticated, ContainerDependency, SessionDependency
from app.models import Interface, JobType, Neighbor
from app.schemas.devices import (
    ConnectionTestView,
    DeviceConnectionFields,
    DeviceCreate,
    DeviceUpdate,
    DeviceView,
    FactsView,
    InterfaceView,
    NeighborView,
    RoutingProcessView,
    RoutingView,
    StaticRouteView,
)
from app.schemas.jobs import JobView
from app.schemas.ssh_trust import HostKeyRepinRequest
from app.services.devices import DeviceService
from app.services.jobs import JobService

router = APIRouter(prefix="/devices", tags=["devices"])


def _service(session: SessionDependency, container: ContainerDependency) -> DeviceService:
    return DeviceService(
        session,
        settings=container.settings,
        drivers=container.drivers,
        vault=container.credential_vault,
        host_key_trust=container.host_key_trust,
        connection_gate=container.connection_gate,
    )


@router.get("", response_model=list[DeviceView])
def list_devices(
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    return _service(session, container).list()


@router.post("", response_model=DeviceView, status_code=status.HTTP_201_CREATED)
def create_device(
    request: DeviceCreate,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    return _service(session, container).create(request)


@router.post("/connection-test", response_model=ConnectionTestView)
def test_connection(
    request: DeviceConnectionFields,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    return _service(session, container).test_connection(request)


@router.get("/{device_id}", response_model=DeviceView)
def get_device(
    device_id: UUID,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    return _service(session, container).get(device_id)


@router.patch("/{device_id}", response_model=DeviceView)
def update_device(
    device_id: UUID,
    request: DeviceUpdate,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    return _service(session, container).update(device_id, request)


@router.delete(
    "/{device_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_device(
    device_id: UUID,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
) -> Response:
    _service(session, container).delete(device_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{device_id}/ssh-host-key/repin", response_model=DeviceView)
def repin_host_key(
    device_id: UUID,
    request: HostKeyRepinRequest,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    """Re-pin a lab device's SSH host key after it was regenerated."""
    return _service(session, container).repin_host_key(device_id, request.host_key_candidate_id)


@router.post("/{device_id}/test-connection", response_model=ConnectionTestView)
def test_registered_device(
    device_id: UUID,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    return _service(session, container).test_registered_device(device_id)


@router.post("/{device_id}/refresh", response_model=JobView, status_code=status.HTTP_202_ACCEPTED)
def refresh_device(
    device_id: UUID,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    return JobService(session, container.queue).enqueue(
        job_type=JobType.REFRESH_DEVICE,
        device_id=device_id,
    )


@router.get("/{device_id}/facts", response_model=FactsView)
def get_facts(
    device_id: UUID,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
) -> FactsView:
    device = _service(session, container).get(device_id)
    return FactsView(device_id=device.id, facts=device.facts, last_seen_at=device.last_seen_at)


@router.get("/{device_id}/interfaces", response_model=list[InterfaceView])
def get_interfaces(
    device_id: UUID,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
) -> list[Interface]:
    return _service(session, container).list_interfaces(device_id)


@router.get("/{device_id}/routing", response_model=RoutingView)
def get_routing(
    device_id: UUID,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
) -> RoutingView:
    """Read the device's routing configuration.

    Live, not stored: unlike interfaces and neighbors there is no table
    behind this, so every call opens a connection. That is also why it is one
    route returning both halves rather than two.
    """
    routes, processes = _service(session, container).read_routing(device_id)
    return RoutingView(
        static_routes=[
            StaticRouteView(
                destination=route.destination,
                mask=route.mask,
                next_hop=route.next_hop,
                command=route.as_command(),
            )
            for route in routes
        ],
        processes=[
            RoutingProcessView(name=process.name, statements=list(process.statements))
            for process in processes
        ],
    )


@router.get("/{device_id}/neighbors", response_model=list[NeighborView])
def get_neighbors(
    device_id: UUID,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
) -> list[Neighbor]:
    return _service(session, container).list_neighbors(device_id)


@router.post(
    "/{device_id}/config-snapshots",
    response_model=JobView,
    status_code=status.HTTP_202_ACCEPTED,
)
def capture_config(
    device_id: UUID,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    return JobService(session, container.queue).enqueue(
        job_type=JobType.CAPTURE_CONFIG,
        device_id=device_id,
    )
