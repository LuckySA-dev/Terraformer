from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from time import monotonic
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError, ConfigurationError, ConflictError
from app.core.logging import sanitize_text
from app.core.time import utc_now
from app.drivers import (
    ConnectionParameters,
    ConnectionTestResult,
    DiagnosticAction,
    DriverRegistry,
)
from app.drivers.ssh_compatibility import (
    SSH_COMPATIBILITY_POLICY_VERSION,
    enforce_compatibility_policy,
)
from app.models import (
    Device,
    DeviceStatus,
    EventSeverity,
    Interface,
    Neighbor,
    SSHCompatibility,
)
from app.repositories.credentials import CredentialProfileRepository
from app.repositories.devices import DeviceRepository
from app.repositories.events import EventRepository
from app.schemas.devices import DeviceConnectionFields, DeviceCreate, DeviceUpdate
from app.schemas.diagnostics import DiagnosticResult
from app.services.connection_gate import (
    ConnectionGateUnavailableError,
    ConnectionOperation,
    ConnectionPermit,
    ConnectionTarget,
    RedisConnectionGate,
)
from app.services.credentials import CredentialVault

_MAX_AUDIT_DURATION_MS = 86_400_000
_POLICY_ERROR_DETAILS = {"phase": "authorization", "retryable": False}
_AUDIT_PHASES = frozenset(
    {
        "authorization",
        "complete",
        "tcp_connection",
        "ssh_negotiation",
        "host_key_verification",
        "authentication",
        "pty_creation",
        "terminal_io",
    }
)
_POST_AUTHENTICATION_PHASES = frozenset({"pty_creation", "terminal_io"})


class LegacyModeDisabledByPolicyError(AppError):
    code = "legacy_mode_disabled_by_policy"
    status_code = 403
    default_message = "Legacy SSH compatibility is not authorized"


class LegacyGroup1DisabledByPolicyError(AppError):
    code = "legacy_group1_disabled_by_policy"
    status_code = 403
    default_message = "Group1 SSH compatibility is not authorized"


class DeviceService:
    def __init__(
        self,
        session: Session,
        *,
        settings: Settings,
        drivers: DriverRegistry,
        vault: CredentialVault,
        connection_gate: RedisConnectionGate | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._drivers = drivers
        self._vault = vault
        self._connection_gate = connection_gate
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
            ssh_compatibility=request.ssh_compatibility,
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
        group1_risk_acknowledged = bool(changes.pop("group1_risk_acknowledged", False))
        connection_fields = {
            "management_address",
            "port",
            "vendor",
            "credential_profile_id",
            "ssh_compatibility",
        }
        candidate = DeviceConnectionFields(
            management_address=changes.get("management_address", device.management_address),
            port=changes.get("port", device.port),
            vendor=changes.get("vendor", device.vendor),
            credential_profile_id=changes.get(
                "credential_profile_id", device.credential_profile_id
            ),
            ssh_compatibility=changes.get("ssh_compatibility", device.ssh_compatibility),
            group1_risk_acknowledged=group1_risk_acknowledged,
        )
        if changes.keys() & connection_fields:
            other = self._devices.find_by_endpoint(candidate.management_address, candidate.port)
            if other is not None and other.id != device.id:
                raise ConflictError("A device with this management endpoint already exists")
            self.test_connection(candidate, _commit=False)
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
        _commit: bool = True,
    ) -> ConnectionTestResult:
        with self.admitted_connection(
            device_id=device_id,
            host=request.management_address,
            port=request.port,
            profile_id=request.credential_profile_id,
            compatibility=request.ssh_compatibility,
            group1_risk_acknowledged=request.group1_risk_acknowledged,
            operation=ConnectionOperation.CONNECTION_TEST,
            _commit=_commit,
        ) as parameters:
            driver = self._drivers.get(request.vendor)
            try:
                result = driver.test_connection(parameters)
            except AppError as exc:
                if device_id is not None and exc.code not in {
                    LegacyModeDisabledByPolicyError.code,
                    LegacyGroup1DisabledByPolicyError.code,
                }:
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
                    if _commit:
                        self._session.commit()
                raise
        del parameters
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
            if _commit:
                self._session.commit()
        elif _commit:
            self._session.commit()
        return result

    def test_registered_device(self, device_id: UUID) -> ConnectionTestResult:
        device = self._devices.get(device_id)
        request = DeviceConnectionFields(
            management_address=device.management_address,
            port=device.port,
            vendor=device.vendor,
            credential_profile_id=device.credential_profile_id,
            ssh_compatibility=device.ssh_compatibility,
            group1_risk_acknowledged=(
                device.ssh_compatibility is SSHCompatibility.CISCO_LEGACY_GROUP1
            ),
        )
        return self.test_connection(request, device_id=device.id)

    def refresh(self, device_id: UUID, *, job_id: UUID | None = None) -> dict[str, object]:
        device = self._devices.get(device_id, for_update=True)
        with self.admitted_connection(
            device_id=device.id,
            host=device.management_address,
            port=device.port,
            profile_id=device.credential_profile_id,
            compatibility=device.ssh_compatibility,
            group1_risk_acknowledged=(
                device.ssh_compatibility is SSHCompatibility.CISCO_LEGACY_GROUP1
            ),
            operation=ConnectionOperation.STRUCTURED_READ,
        ) as parameters:
            driver = self._drivers.get(device.vendor)
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
        del parameters
        device.facts = observations.facts.as_dict()
        device.status = DeviceStatus.REACHABLE
        device.last_seen_at = utc_now()
        device.last_error_code = None
        self._devices.replace_interfaces(device, list(observations.interfaces))
        self._devices.replace_neighbors(device, list(observations.neighbors))
        self._devices.replace_capabilities(device, driver.capabilities)
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

    def run_diagnostic(
        self,
        device_id: UUID,
        action: DiagnosticAction,
        *,
        target: str | None = None,
        job_id: UUID,
    ) -> dict[str, object]:
        device = self._devices.get(device_id, for_update=True)
        with self.admitted_connection(
            device_id=device.id,
            host=device.management_address,
            port=device.port,
            profile_id=device.credential_profile_id,
            compatibility=device.ssh_compatibility,
            group1_risk_acknowledged=(
                device.ssh_compatibility is SSHCompatibility.CISCO_LEGACY_GROUP1
            ),
            operation=ConnectionOperation.STRUCTURED_READ,
        ) as parameters:
            driver = self._drivers.get(device.vendor)
            sanitized = sanitize_text(driver.run_diagnostic(parameters, action, target))
        del parameters
        output_limit = 65_536
        result = DiagnosticResult(
            device_id=device.id,
            action=action,
            target=target,
            output=sanitized[:output_limit],
            truncated=len(sanitized) > output_limit,
        )
        device.status = DeviceStatus.REACHABLE
        device.last_seen_at = utc_now()
        device.last_error_code = None
        self._devices.replace_capabilities(device, driver.capabilities)
        self._events.record(
            event_type="diagnostic.completed",
            message="An allowlisted read-only diagnostic completed",
            device_id=device.id,
            job_id=job_id,
            details={"action": action.value, "truncated": result.truncated},
        )
        self._session.commit()
        return result.model_dump(mode="json")

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

    @contextmanager
    def admitted_connection(
        self,
        *,
        device_id: UUID | None,
        host: str,
        port: int,
        profile_id: UUID,
        compatibility: SSHCompatibility,
        group1_risk_acknowledged: bool,
        operation: ConnectionOperation,
        _commit: bool = True,
    ) -> Iterator[ConnectionParameters]:
        started = monotonic()
        normalized_host = host.strip().lower()
        mode = SSHCompatibility(compatibility)
        try:
            enforce_compatibility_policy(
                mode,
                self._settings,
                group1_risk_acknowledged=group1_risk_acknowledged,
            )
        except ConfigurationError:
            error: AppError
            if not self._settings.ssh_legacy_enabled:
                error = LegacyModeDisabledByPolicyError(details=_POLICY_ERROR_DETAILS)
            else:
                error = LegacyGroup1DisabledByPolicyError(details=_POLICY_ERROR_DETAILS)
            self._audit_connection(
                device_id=device_id,
                compatibility=mode,
                group1_risk_acknowledged=group1_risk_acknowledged,
                operation=operation,
                phase="authorization",
                authorization_decision="denied",
                result_code=error.code,
                started=started,
            )
            if _commit:
                self._session.commit()
            raise error from None

        gate = self._connection_gate
        if gate is None:
            error = ConnectionGateUnavailableError()
            self._audit_connection(
                device_id=device_id,
                compatibility=mode,
                group1_risk_acknowledged=group1_risk_acknowledged,
                operation=operation,
                phase="authorization",
                authorization_decision="denied",
                result_code=error.code,
                started=started,
            )
            if _commit:
                self._session.commit()
            raise error

        target = ConnectionTarget.from_endpoint(
            host=normalized_host,
            port=port,
            credential_profile_id=profile_id,
            device_id=device_id,
        )
        permit: ConnectionPermit | None = None
        profile = None
        material = None
        parameters = None
        try:
            try:
                permit = gate.acquire(operation, target)
            except AppError as exc:
                self._audit_connection(
                    device_id=device_id,
                    compatibility=mode,
                    group1_risk_acknowledged=group1_risk_acknowledged,
                    operation=operation,
                    phase="authorization",
                    authorization_decision="denied",
                    result_code=exc.code,
                    started=started,
                )
                if _commit:
                    self._session.commit()
                raise

            profile = self._credentials.get(profile_id)
            material = self._vault.decrypt(profile)
            parameters = ConnectionParameters(
                host=normalized_host,
                port=port,
                username=material.username,
                password=material.password,
                enable_password=material.enable_password,
                connect_timeout_seconds=self._settings.ssh_connect_timeout_seconds,
                command_timeout_seconds=self._settings.ssh_command_timeout_seconds,
                ssh_compatibility=mode,
            )
            try:
                yield parameters
            except AppError as exc:
                failure_phase = exc.details.get("phase")
                if failure_phase == "authentication":
                    gate.authentication_failed(target)
                elif failure_phase in _POST_AUTHENTICATION_PHASES:
                    gate.authentication_succeeded(target)
                self._audit_connection(
                    device_id=device_id,
                    compatibility=mode,
                    group1_risk_acknowledged=group1_risk_acknowledged,
                    operation=operation,
                    phase=(
                        failure_phase
                        if isinstance(failure_phase, str) and failure_phase in _AUDIT_PHASES
                        else "complete"
                    ),
                    authorization_decision="allowed",
                    result_code=exc.code,
                    started=started,
                )
                if _commit:
                    self._session.commit()
                raise
            except Exception:
                self._audit_connection(
                    device_id=device_id,
                    compatibility=mode,
                    group1_risk_acknowledged=group1_risk_acknowledged,
                    operation=operation,
                    phase="complete",
                    authorization_decision="allowed",
                    result_code="internal_error",
                    started=started,
                )
                if _commit:
                    self._session.commit()
                raise
            else:
                gate.authentication_succeeded(target)
                self._audit_connection(
                    device_id=device_id,
                    compatibility=mode,
                    group1_risk_acknowledged=group1_risk_acknowledged,
                    operation=operation,
                    phase="complete",
                    authorization_decision="allowed",
                    result_code="success",
                    started=started,
                )
        finally:
            parameters = None
            material = None
            profile = None
            if permit is not None:
                gate.release(permit)

    def _audit_connection(
        self,
        *,
        device_id: UUID | None,
        compatibility: SSHCompatibility,
        group1_risk_acknowledged: bool,
        operation: ConnectionOperation,
        phase: str,
        authorization_decision: str,
        result_code: str,
        started: float,
    ) -> None:
        self._events.record(
            event_type="ssh.connection_admission",
            message="SSH connection admission completed",
            device_id=device_id,
            details={
                "principal": "local-admin",
                "requested_mode": compatibility.value,
                "group1_risk_acknowledged": group1_risk_acknowledged,
                "compatibility_policy_version": SSH_COMPATIBILITY_POLICY_VERSION,
                "operation": operation.value,
                "phase": phase,
                "policy_decision": authorization_decision,
                "duration_ms": min(
                    max(0, int((monotonic() - started) * 1_000)),
                    _MAX_AUDIT_DURATION_MS,
                ),
                "result_code": result_code,
            },
        )
