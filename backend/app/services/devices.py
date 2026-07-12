from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError, ConflictError
from app.core.time import utc_now
from app.drivers import ConnectionParameters, ConnectionTestResult, DriverRegistry
from app.models import Device, DeviceStatus, EventSeverity, Interface, Neighbor
from app.repositories.credentials import CredentialProfileRepository
from app.repositories.devices import DeviceRepository
from app.repositories.events import EventRepository
from app.schemas.devices import DeviceConnectionFields, DeviceCreate, DeviceUpdate
from app.services.credentials import CredentialVault


class DeviceService:
    def __init__(
        self,
        session: Session,
        *,
        settings: Settings,
        drivers: DriverRegistry,
        vault: CredentialVault,
    ) -> None:
        self._session = session
        self._settings = settings
        self._drivers = drivers
        self._vault = vault
        self._devices = DeviceRepository(session)
        self._credentials = CredentialProfileRepository(session)
        self._events = EventRepository(session)

    def list(self) -> list[Device]:
        return self._devices.list()

    def get(self, device_id: UUID) -> Device:
        return self._devices.get(device_id)

    def create(self, request: DeviceCreate, *, job_id: UUID | None = None) -> Device:
        if self._devices.find_by_endpoint(request.management_address, request.port) is not None:
            raise ConflictError("A device with this management endpoint already exists")
        result = self.test_connection(request)
        driver = self._drivers.get(request.vendor)
        device = Device(
            name=request.name.strip(),
            management_address=request.management_address,
            port=request.port,
            vendor=request.vendor,
            credential_profile_id=request.credential_profile_id,
            status=DeviceStatus.REACHABLE if result.reachable else DeviceStatus.UNREACHABLE,
            last_seen_at=utc_now() if result.reachable else None,
            facts={},
        )
        try:
            self._devices.add(device)
            self._devices.replace_capabilities(device, driver.capabilities)
            self._events.record(
                event_type="device.created",
                message="Device was registered after a successful connection test",
                device_id=device.id,
                job_id=job_id,
                details={"vendor": device.vendor.value, "driver": driver.name},
            )
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise ConflictError("A device with this management endpoint already exists") from exc
        return self._devices.get(device.id)

    def update(self, device_id: UUID, request: DeviceUpdate) -> Device:
        device = self._devices.get(device_id, for_update=True)
        changes = request.model_dump(exclude_unset=True)
        connection_fields = {"management_address", "port", "vendor", "credential_profile_id"}
        candidate = DeviceConnectionFields(
            management_address=changes.get("management_address", device.management_address),
            port=changes.get("port", device.port),
            vendor=changes.get("vendor", device.vendor),
            credential_profile_id=changes.get(
                "credential_profile_id", device.credential_profile_id
            ),
        )
        if changes.keys() & connection_fields:
            other = self._devices.find_by_endpoint(candidate.management_address, candidate.port)
            if other is not None and other.id != device.id:
                raise ConflictError("A device with this management endpoint already exists")
            self.test_connection(candidate)
        for field, value in changes.items():
            setattr(device, field, value.strip() if field == "name" else value)
        if changes.keys() & connection_fields:
            driver = self._drivers.get(device.vendor)
            device.status = DeviceStatus.REACHABLE
            device.last_seen_at = utc_now()
            device.last_error_code = None
            self._devices.replace_capabilities(device, driver.capabilities)
        self._events.record(
            event_type="device.updated",
            message="Device metadata was updated",
            device_id=device.id,
            details={"fields": sorted(changes)},
        )
        try:
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise ConflictError("Device update conflicts with existing data") from exc
        return self._devices.get(device.id)

    def delete(self, device_id: UUID) -> None:
        device = self._devices.get(device_id)
        try:
            self._devices.delete(device)
            self._session.commit()
        except (IntegrityError, ConflictError) as exc:
            self._session.rollback()
            raise ConflictError(
                "Device cannot be deleted while immutable snapshots reference it"
            ) from exc

    def test_connection(
        self,
        request: DeviceConnectionFields,
        *,
        device_id: UUID | None = None,
    ) -> ConnectionTestResult:
        driver = self._drivers.get(request.vendor)
        parameters = self.connection_parameters(
            profile_id=request.credential_profile_id,
            host=request.management_address,
            port=request.port,
        )
        try:
            result = driver.test_connection(parameters)
        except AppError as exc:
            if device_id is not None:
                device = self._devices.get(device_id, for_update=True)
                device.status = DeviceStatus.UNREACHABLE
                device.last_error_code = exc.code
                self._events.record(
                    event_type="device.connection_failed",
                    severity=EventSeverity.ERROR,
                    message=exc.message,
                    device_id=device.id,
                    details={"error_code": exc.code},
                )
                self._session.commit()
            raise
        if device_id is not None:
            device = self._devices.get(device_id, for_update=True)
            device.status = DeviceStatus.REACHABLE
            device.last_seen_at = utc_now()
            device.last_error_code = None
            self._events.record(
                event_type="device.connection_succeeded",
                message="Device connection test succeeded",
                device_id=device.id,
                details={"driver": driver.name, "latency_ms": result.latency_ms},
            )
            self._session.commit()
        return result

    def test_registered_device(self, device_id: UUID) -> ConnectionTestResult:
        device = self._devices.get(device_id)
        request = DeviceConnectionFields(
            management_address=device.management_address,
            port=device.port,
            vendor=device.vendor,
            credential_profile_id=device.credential_profile_id,
        )
        return self.test_connection(request, device_id=device.id)

    def refresh(self, device_id: UUID, *, job_id: UUID | None = None) -> dict[str, object]:
        device = self._devices.get(device_id, for_update=True)
        driver = self._drivers.get(device.vendor)
        parameters = self.connection_parameters(
            profile_id=device.credential_profile_id,
            host=device.management_address,
            port=device.port,
        )
        try:
            observations = driver.collect_observations(parameters)
        except AppError as exc:
            device.status = DeviceStatus.UNREACHABLE
            device.last_error_code = exc.code
            self._events.record(
                event_type="device.refresh_failed",
                severity=EventSeverity.ERROR,
                message=exc.message,
                device_id=device.id,
                job_id=job_id,
                details={"error_code": exc.code},
            )
            self._session.commit()
            raise
        device.facts = observations.facts.as_dict()
        device.status = DeviceStatus.REACHABLE
        device.last_seen_at = utc_now()
        device.last_error_code = None
        self._devices.replace_interfaces(device, list(observations.interfaces))
        self._devices.replace_neighbors(device, list(observations.neighbors))
        self._events.record(
            event_type="device.refreshed",
            message="Device facts, interfaces, and neighbors were refreshed",
            device_id=device.id,
            job_id=job_id,
            details={
                "interface_count": len(observations.interfaces),
                "neighbor_count": len(observations.neighbors),
            },
        )
        self._session.commit()
        return {
            "device_id": str(device.id),
            "interface_count": len(observations.interfaces),
            "neighbor_count": len(observations.neighbors),
        }

    def list_interfaces(self, device_id: UUID) -> list[Interface]:
        return self._devices.list_interfaces(device_id)

    def list_neighbors(self, device_id: UUID) -> list[Neighbor]:
        return self._devices.list_neighbors(device_id)

    def connection_parameters(
        self,
        *,
        profile_id: UUID,
        host: str,
        port: int,
    ) -> ConnectionParameters:
        profile = self._credentials.get(profile_id)
        material = self._vault.decrypt(profile)
        return ConnectionParameters(
            host=host,
            port=port,
            username=material.username,
            password=material.password,
            enable_password=material.enable_password,
            connect_timeout_seconds=self._settings.ssh_connect_timeout_seconds,
            command_timeout_seconds=self._settings.ssh_command_timeout_seconds,
        )
