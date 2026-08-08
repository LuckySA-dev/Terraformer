from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from time import monotonic
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import (
    AppError,
    ConfigurationError,
    ConflictError,
    DriverHostKeyUnknownError,
    UnsupportedCapabilityError,
)
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
    ConsoleTransport,
    Device,
    DeviceStatus,
    EventSeverity,
    Interface,
    Neighbor,
    SSHCompatibility,
    Vendor,
)
from app.repositories.credentials import CredentialProfileRepository
from app.repositories.devices import DeviceRepository
from app.repositories.events import EventRepository
from app.repositories.ssh_trust import DeviceSSHHostKeyRepository
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
from app.services.ssh_trust import HostKeyTrustService, ResolvedHostKeyCandidate, known_hosts_line

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


class LegacyVeryOldDisabledByPolicyError(AppError):
    code = "very_old_mode_disabled_by_policy"
    status_code = 403
    default_message = "Very old SSHv2 compatibility is not authorized"


class DeviceService:
    def __init__(
        self,
        session: Session,
        *,
        settings: Settings,
        drivers: DriverRegistry,
        vault: CredentialVault,
        host_key_trust: HostKeyTrustService,
        connection_gate: RedisConnectionGate | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._drivers = drivers
        self._vault = vault
        self._host_key_trust = host_key_trust
        self._connection_gate = connection_gate
        self._devices = DeviceRepository(session)
        self._credentials = CredentialProfileRepository(session)
        self._events = EventRepository(session)
        self._host_keys = DeviceSSHHostKeyRepository(session)

    def list(self) -> list[Device]:
        return self._devices.list()

    def get(self, device_id: UUID) -> Device:
        return self._devices.get(device_id)

    def create(self, request: DeviceCreate, *, job_id: UUID | None = None) -> Device:
        if self._devices.find_by_endpoint(request.management_address, request.port) is not None:
            raise ConflictError("A device with this management endpoint already exists")
        result = self.test_connection(request, _commit=False)
        host_key = self._resolve_candidate(request)
        driver = self._drivers.get(request.vendor)
        device = Device(
            name=request.name.strip(),
            management_address=request.management_address,
            port=request.port,
            vendor=request.vendor,
            credential_profile_id=request.credential_profile_id,
            ssh_compatibility=request.ssh_compatibility,
            is_lab=request.is_lab,
            console_transport=request.console_transport,
            status=DeviceStatus.REACHABLE if result.reachable else DeviceStatus.UNREACHABLE,
            last_seen_at=utc_now() if result.reachable else None,
            facts={},
        )
        try:
            self._devices.add(device)
            self._host_keys.add(device.id, host_key)
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
        self._host_key_trust.delete_candidate(host_key.id)
        return self._devices.get(device.id)

    def update(self, device_id: UUID, request: DeviceUpdate) -> Device:
        device = self._devices.get(device_id, for_update=True)
        changes = request.model_dump(exclude_unset=True)
        group1_risk_acknowledged = bool(changes.pop("group1_risk_acknowledged", False))
        very_old_risk_acknowledged = bool(changes.pop("very_old_risk_acknowledged", False))
        host_key_candidate_id = changes.pop("host_key_candidate_id", None)
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
            very_old_risk_acknowledged=very_old_risk_acknowledged,
            host_key_candidate_id=host_key_candidate_id,
        )
        # Evaluate the telnet rule against the record as it will be after the
        # patch, so clearing is_lab and keeping telnet is rejected too.
        if (
            changes.get("console_transport", device.console_transport) is ConsoleTransport.TELNET
            and not changes.get("is_lab", device.is_lab)
        ):
            raise UnsupportedCapabilityError(
                "A telnet console is only available for devices marked as lab devices"
            )
        replacement_host_key: ResolvedHostKeyCandidate | None = None
        if changes.keys() & connection_fields:
            other = self._devices.find_by_endpoint(candidate.management_address, candidate.port)
            if other is not None and other.id != device.id:
                raise ConflictError("A device with this management endpoint already exists")
            self.test_connection(candidate, _commit=False)
            replacement_host_key = self._resolve_candidate(candidate)
        for field, value in changes.items():
            setattr(device, field, value.strip() if field == "name" else value)
        if changes.keys() & connection_fields:
            driver = self._drivers.get(device.vendor)
            device.status = DeviceStatus.REACHABLE
            device.last_seen_at = utc_now()
            device.last_error_code = None
            self._devices.replace_capabilities(device, driver.capabilities)
            if replacement_host_key is None:
                raise RuntimeError("Host-key replacement was not prepared")
            self._host_keys.replace(device.id, replacement_host_key)
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
        if replacement_host_key is not None:
            self._host_key_trust.delete_candidate(replacement_host_key.id)
        return self._devices.get(device.id)

    def repin_host_key(self, device_id: UUID, host_key_candidate_id: UUID) -> Device:
        """Replace a lab device's pinned SSH host key without editing the record.

        GNS3/EVE-NG nodes regenerate their host key on every restart, which
        otherwise looks identical to a man-in-the-middle and can only be
        cleared by deleting and recreating the device.

        Restricted to devices the operator explicitly marked as lab devices, so
        the pin on real hardware still cannot be replaced silently. The
        operator must have inspected and confirmed a fresh candidate first, and
        the connection is tested with the new key before it is stored.
        """
        device = self._devices.get(device_id, for_update=True)
        if not device.is_lab:
            raise UnsupportedCapabilityError(
                "Re-pinning is only available for devices marked as lab devices."
                " Verify the device identity and re-register it instead."
            )
        candidate = DeviceConnectionFields(
            management_address=device.management_address,
            port=device.port,
            vendor=device.vendor,
            credential_profile_id=device.credential_profile_id,
            ssh_compatibility=device.ssh_compatibility,
            group1_risk_acknowledged=(
                device.ssh_compatibility
                in (SSHCompatibility.CISCO_LEGACY_GROUP1, SSHCompatibility.VERY_OLD_SSH)
            ),
            very_old_risk_acknowledged=(
                device.ssh_compatibility is SSHCompatibility.VERY_OLD_SSH
            ),
            host_key_candidate_id=host_key_candidate_id,
        )
        replacement = self._resolve_candidate(candidate)
        self.test_connection(candidate, device_id=device.id, _commit=False)
        self._host_keys.replace(device.id, replacement)
        self._events.record(
            event_type="device.host_key_repinned",
            severity=EventSeverity.WARNING,
            message="Lab device SSH host key was re-pinned after explicit confirmation",
            device_id=device.id,
            details={"algorithm": replacement.algorithm, "fingerprint": replacement.fingerprint},
        )
        self._session.commit()
        self._host_key_trust.delete_candidate(replacement.id)
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
        _cisco_only_modes = {
            SSHCompatibility.CISCO_LEGACY,
            SSHCompatibility.CISCO_LEGACY_GROUP1,
        }
        _very_old_vendors = {Vendor.CISCO_IOSXE, Vendor.FORTINET_FORTIOS}
        if request.ssh_compatibility in _cisco_only_modes and request.vendor not in {
            Vendor.CISCO_IOSXE
        }:
            raise UnsupportedCapabilityError(
                "Cisco legacy SSH compatibility is only available for Cisco IOS/IOS-XE devices"
            )
        if (
            request.ssh_compatibility is SSHCompatibility.VERY_OLD_SSH
            and request.vendor not in _very_old_vendors
        ):
            raise UnsupportedCapabilityError(
                "Very old SSHv2 compatibility is only available for Cisco IOS/IOS-XE"
                " and Fortinet FortiOS devices"
            )
        with self.admitted_connection(
            device_id=device_id,
            host=request.management_address,
            port=request.port,
            profile_id=request.credential_profile_id,
            vendor=request.vendor,
            compatibility=request.ssh_compatibility,
            group1_risk_acknowledged=request.group1_risk_acknowledged,
            very_old_risk_acknowledged=request.very_old_risk_acknowledged,
            operation=ConnectionOperation.CONNECTION_TEST,
            host_key_candidate_id=request.host_key_candidate_id,
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
                device.ssh_compatibility
                in (SSHCompatibility.CISCO_LEGACY_GROUP1, SSHCompatibility.VERY_OLD_SSH)
            ),
            # The acknowledgment was recorded when this device was registered;
            # a re-test of a saved record carries it forward.
            very_old_risk_acknowledged=(
                device.ssh_compatibility is SSHCompatibility.VERY_OLD_SSH
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
            vendor=device.vendor,
            compatibility=device.ssh_compatibility,
            group1_risk_acknowledged=(
                device.ssh_compatibility
                in (SSHCompatibility.CISCO_LEGACY_GROUP1, SSHCompatibility.VERY_OLD_SSH)
            ),
            very_old_risk_acknowledged=(
                device.ssh_compatibility is SSHCompatibility.VERY_OLD_SSH
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
            vendor=device.vendor,
            compatibility=device.ssh_compatibility,
            group1_risk_acknowledged=(
                device.ssh_compatibility
                in (SSHCompatibility.CISCO_LEGACY_GROUP1, SSHCompatibility.VERY_OLD_SSH)
            ),
            very_old_risk_acknowledged=(
                device.ssh_compatibility is SSHCompatibility.VERY_OLD_SSH
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
        device_id: UUID,
        host: str,
        port: int,
    ) -> ConnectionParameters:
        host_key = self._host_keys.require(device_id)
        profile = self._credentials.get(profile_id)
        material = self._vault.decrypt(profile)
        return ConnectionParameters(
            host=host,
            port=port,
            username=material.username,
            password=material.password,
            known_hosts=known_hosts_line(host, port, host_key.public_key),
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
        vendor: Vendor,
        compatibility: SSHCompatibility,
        group1_risk_acknowledged: bool,
        very_old_risk_acknowledged: bool = False,
        operation: ConnectionOperation,
        host_key_candidate_id: UUID | None = None,
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
                very_old_risk_acknowledged=very_old_risk_acknowledged,
            )
        except ConfigurationError:
            error: AppError
            if not self._settings.ssh_legacy_enabled:
                error = LegacyModeDisabledByPolicyError(details=_POLICY_ERROR_DETAILS)
            elif mode is SSHCompatibility.VERY_OLD_SSH and (
                not self._settings.ssh_group1_enabled
                or not self._settings.ssh_very_old_enabled
                or not very_old_risk_acknowledged
            ):
                error = LegacyVeryOldDisabledByPolicyError(details=_POLICY_ERROR_DETAILS)
            else:
                error = LegacyGroup1DisabledByPolicyError(details=_POLICY_ERROR_DETAILS)
            self._audit_connection(
                device_id=device_id,
                compatibility=mode,
                group1_risk_acknowledged=group1_risk_acknowledged,
                very_old_risk_acknowledged=very_old_risk_acknowledged,
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

        if device_id is None:
            if host_key_candidate_id is None:
                raise DriverHostKeyUnknownError(details={"phase": "host_key_verification"})
            candidate_request = DeviceConnectionFields(
                management_address=normalized_host,
                port=port,
                vendor=vendor,
                credential_profile_id=profile_id,
                ssh_compatibility=mode,
                group1_risk_acknowledged=group1_risk_acknowledged,
                host_key_candidate_id=host_key_candidate_id,
            )
            candidate = self._host_key_trust.resolve_candidate(
                host_key_candidate_id,
                candidate_request,
            )
            pinned_known_hosts = candidate.known_hosts
        else:
            host_key = self._host_keys.require(device_id)
            pinned_known_hosts = known_hosts_line(normalized_host, port, host_key.public_key)

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
                known_hosts=pinned_known_hosts,
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
                    very_old_risk_acknowledged=very_old_risk_acknowledged,
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
                    very_old_risk_acknowledged=very_old_risk_acknowledged,
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
                    very_old_risk_acknowledged=very_old_risk_acknowledged,
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

    def _resolve_candidate(
        self,
        request: DeviceConnectionFields,
    ) -> ResolvedHostKeyCandidate:
        if request.host_key_candidate_id is None:
            raise DriverHostKeyUnknownError(details={"phase": "host_key_verification"})
        return self._host_key_trust.resolve_candidate(
            request.host_key_candidate_id,
            request,
        )

    def _audit_connection(
        self,
        *,
        device_id: UUID | None,
        compatibility: SSHCompatibility,
        group1_risk_acknowledged: bool,
        very_old_risk_acknowledged: bool = False,
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
                "very_old_risk_acknowledged": very_old_risk_acknowledged,
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
