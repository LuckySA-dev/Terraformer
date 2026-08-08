from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from socket import gaierror
from time import monotonic
from typing import Protocol, cast
from uuid import UUID

import asyncssh
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.container import ApplicationContainer
from app.core.errors import AppError, ConfigurationError
from app.drivers import ConnectionParameters
from app.drivers.ssh_compatibility import (
    SSH_COMPATIBILITY_POLICY_VERSION,
    compatibility_policy,
    enforce_compatibility_policy,
)
from app.drivers.ssh_errors import FAILURES as SSH_FAILURES
from app.drivers.ssh_errors import SanitizedSSHFailure
from app.drivers.telnet import open_telnet_session
from app.models import ConsoleTransport, SSHCompatibility
from app.repositories.events import EventRepository
from app.services.connection_gate import (
    ConnectionOperation,
    ConnectionPermit,
    ConnectionTarget,
    RedisConnectionGate,
)
from app.services.devices import DeviceService

router = APIRouter()

_DIRECT_MODE_TIMEOUT_SECONDS = 30
_IDLE_TIMEOUT_SECONDS = 900
_MAX_INPUT_BYTES = 4_096
_MAX_OUTPUT_BYTES = 2_097_152
_OUTPUT_CHUNK_SIZE = 4_096
_MAX_AUDIT_DURATION_MS = 86_400_000


@dataclass(frozen=True, slots=True)
class _FailureSpec:
    message: str
    phase: str
    retryable: bool
    recommended_action: str | None = None


_FAILURES: dict[str, _FailureSpec | SanitizedSSHFailure] = {
    "direct_mode_required": _FailureSpec(
        "Confirm Direct Mode before opening the terminal.", "authorization", False
    ),
    "terminal_disabled_by_policy": _FailureSpec(
        "Device terminals are disabled by server policy.", "authorization", False
    ),
    "legacy_mode_disabled_by_policy": _FailureSpec(
        "Legacy SSH compatibility is not authorized.", "authorization", False
    ),
    "legacy_group1_disabled_by_policy": _FailureSpec(
        "Group1 SSH compatibility is not authorized.", "authorization", False
    ),
    "very_old_mode_disabled_by_policy": _FailureSpec(
        "Very old SSHv2 compatibility is not authorized.", "authorization", False
    ),
    "telnet_disabled_by_policy": _FailureSpec(
        "Telnet consoles are disabled by server policy.",
        "authorization",
        False,
        "Set TELNET_ENABLED=true only for an isolated virtual lab.",
    ),
    "telnet_requires_lab_device": _FailureSpec(
        "Telnet is only available for devices marked as lab devices.",
        "authorization",
        False,
    ),
    "telnet_direct_mode_required": _FailureSpec(
        "Confirm the cleartext Telnet warning before opening the console.",
        "authorization",
        False,
    ),
    "connection_gate_unavailable": _FailureSpec(
        "Connection admission is temporarily unavailable.", "authorization", True
    ),
    "device_connection_rate_limited": _FailureSpec(
        "Too many device connection attempts.", "authorization", True
    ),
    "device_authentication_rate_limited": _FailureSpec(
        "Device authentication is temporarily rate limited.", "authorization", False
    ),
    "device_connection_limit_reached": _FailureSpec(
        "The device connection limit has been reached.", "authorization", True
    ),
    "terminal_session_limit_reached": _FailureSpec(
        "The terminal session limit has been reached.", "authorization", True
    ),
    "not_found": _FailureSpec("The requested resource was not found.", "authorization", False),
    "terminal_shell_rejected": _FailureSpec(
        "The device rejected shell creation.",
        "pty_creation",
        False,
        "Verify the device permits PTY and shell creation.",
    ),
    "terminal_idle_timeout": _FailureSpec(
        "The terminal closed after the idle timeout.", "terminal_io", True
    ),
    "terminal_session_expired": _FailureSpec(
        "The terminal reached its maximum session duration.", "terminal_io", True
    ),
    "terminal_input_limit": _FailureSpec("Terminal input is too large.", "terminal_io", False),
    "terminal_output_limit": _FailureSpec(
        "Terminal output limit reached; open a new session.", "terminal_io", False
    ),
    "invalid_terminal_message": _FailureSpec("Invalid terminal message.", "terminal_io", False),
    "invalid_terminal_size": _FailureSpec("Invalid terminal size.", "terminal_io", False),
}

_SHARED_FAILURE_MESSAGES = {
    "device_connection_timeout": "The device connection timed out.",
    "device_connection_failed": "Unable to connect to the device.",
    "device_connection_refused": "The device refused the SSH connection.",
    "device_connection_lost": "The device connection was lost.",
    "device_name_resolution_failed": "The device address could not be resolved.",
    "device_host_key_unknown": "The device SSH host key could not be verified.",
    "device_host_key_changed": "The device SSH host key has changed.",
    "legacy_ssh_negotiation_failed": "Unable to negotiate a compatible SSH session.",
    "device_authentication_failed": "The device rejected the credential profile.",
    "terminal_pty_rejected": "The device rejected terminal setup.",
    "terminal_transport_failed": "The device terminal transport failed.",
}
for _code in _SHARED_FAILURE_MESSAGES:
    _FAILURES[_code] = SSH_FAILURES[_code]


class _TerminalFailure(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)

    @property
    def spec(self) -> _FailureSpec | SanitizedSSHFailure:
        return _FAILURES[self.code]


@dataclass(frozen=True, slots=True)
class _TerminalTarget:
    device_id: UUID
    host: str
    port: int
    profile_id: UUID
    compatibility: SSHCompatibility
    console_transport: ConsoleTransport
    is_lab: bool


class TerminalSession(Protocol):
    async def read(self, size: int) -> str: ...

    async def write(self, data: str) -> None: ...

    def resize(self, columns: int, rows: int) -> None: ...

    async def close(self) -> None: ...


class AsyncSSHTerminalSession:
    def __init__(
        self,
        connection: asyncssh.SSHClientConnection,
        process: asyncssh.SSHClientProcess[str],
        *,
        close_timeout_seconds: float,
    ) -> None:
        self._connection = connection
        self._process = process
        self._close_timeout_seconds = close_timeout_seconds
        self._closed = False

    async def read(self, size: int) -> str:
        return await self._process.stdout.read(size)

    async def write(self, data: str) -> None:
        self._process.stdin.write(data)
        await self._process.stdin.drain()

    def resize(self, columns: int, rows: int) -> None:
        self._process.change_terminal_size(columns, rows)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._process.close()
            await asyncio.wait_for(self._process.wait_closed(), timeout=self._close_timeout_seconds)
        except (Exception, asyncio.CancelledError):  # noqa: S110
            pass  # Cleanup errors must not expose raw terminal or transport details.
        finally:
            await _close_connection(self._connection, self._close_timeout_seconds)


def _connection_failure_code(exc: asyncssh.Error | OSError) -> str:
    if isinstance(exc, TimeoutError):
        return "device_connection_timeout"
    if isinstance(exc, asyncssh.PermissionDenied):
        return "device_authentication_failed"
    if isinstance(exc, asyncssh.HostKeyNotVerifiable):
        reason = str(exc).casefold()
        if "host key is not trusted" in reason or ("host key" in reason and "changed" in reason):
            return "device_host_key_changed"
        return "device_host_key_unknown"
    if isinstance(exc, asyncssh.KeyExchangeFailed | asyncssh.ProtocolError):
        return "legacy_ssh_negotiation_failed"
    if isinstance(exc, asyncssh.ConnectionLost):
        return "device_connection_lost"
    if isinstance(exc, gaierror):
        return "device_name_resolution_failed"
    if isinstance(exc, ConnectionRefusedError):
        return "device_connection_refused"
    return "device_connection_failed"


def _telnet_failure_code(exc: OSError | TimeoutError) -> str:
    if isinstance(exc, TimeoutError):
        return "device_connection_timeout"
    if isinstance(exc, ConnectionRefusedError):
        return "device_connection_refused"
    if isinstance(exc, gaierror):
        return "device_name_resolution_failed"
    return "device_connection_failed"


async def _release_after_cancelled_acquire(
    gate: RedisConnectionGate,
    acquire_task: asyncio.Task[ConnectionPermit],
) -> None:
    try:
        acquired_permit = await acquire_task
    except BaseException:
        return  # Cancellation won before a permit existed.
    try:
        await asyncio.to_thread(gate.release, acquired_permit)
    except BaseException:  # noqa: S110
        pass  # The permit TTL is the final fail-safe if Redis becomes unavailable.


async def _await_cleanup(task: asyncio.Task[None]) -> None:
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue


async def _acquire_terminal_permit(
    gate: RedisConnectionGate,
    target: ConnectionTarget,
) -> ConnectionPermit:
    acquire_task = asyncio.create_task(
        asyncio.to_thread(gate.acquire, ConnectionOperation.TERMINAL, target)
    )
    try:
        return await asyncio.shield(acquire_task)
    except asyncio.CancelledError:
        rollback_task = asyncio.create_task(_release_after_cancelled_acquire(gate, acquire_task))
        await _await_cleanup(rollback_task)
        raise


async def _open_terminal(
    parameters: ConnectionParameters,
    *,
    pty_timeout_seconds: float,
) -> TerminalSession:
    if not parameters.known_hosts.strip():
        raise _TerminalFailure("device_host_key_unknown")
    policy = compatibility_policy(parameters.ssh_compatibility)
    options: dict[str, object] = {
        "host": parameters.host,
        "port": parameters.port,
        "username": parameters.username,
        "password": parameters.password,
        "config": None,
        "client_keys": None,
        "agent_path": None,
        "preferred_auth": "password",
        "password_auth": True,
        "public_key_auth": False,
        "kbdint_auth": False,
        "host_based_auth": False,
        "gss_auth": False,
        "gss_kex": False,
        "disable_trivial_auth": True,
        "encoding": "utf-8",
        "errors": "replace",
        "known_hosts": asyncssh.import_known_hosts(parameters.known_hosts),
    }
    for name, value in (
        ("kex_algs", policy.asyncssh_kex_algs),
        ("server_host_key_algs", policy.asyncssh_server_host_key_algs),
        ("encryption_algs", policy.asyncssh_encryption_algs),
        ("mac_algs", policy.asyncssh_mac_algs),
    ):
        if value is not None:
            options[name] = value

    try:
        connection = await asyncio.wait_for(
            asyncssh.connect(**options), timeout=parameters.connect_timeout_seconds
        )
    except (asyncssh.Error, OSError) as exc:
        raise _TerminalFailure(_connection_failure_code(exc)) from None
    try:
        process = await asyncio.wait_for(
            connection.create_process(
                term_type="xterm-256color",
                term_size=(80, 24),
            ),
            timeout=pty_timeout_seconds,
        )
    except BaseException as exc:
        await _close_connection(connection, pty_timeout_seconds)
        if isinstance(exc, TimeoutError):
            raise _TerminalFailure("terminal_pty_rejected") from None
        if isinstance(exc, asyncssh.ChannelOpenError | asyncssh.ProcessError):
            raise _TerminalFailure("terminal_shell_rejected") from None
        if isinstance(exc, asyncssh.Error | OSError):
            raise _TerminalFailure("terminal_pty_rejected") from None
        raise
    return AsyncSSHTerminalSession(
        connection,
        process,
        close_timeout_seconds=pty_timeout_seconds,
    )


@router.websocket("/ws/terminal/{device_id}")
async def terminal(websocket: WebSocket, device_id: UUID) -> None:
    container: ApplicationContainer = websocket.app.state.container
    token = websocket.cookies.get(container.settings.session_cookie_name)
    if token is None or container.session_tokens.verify(token) is None:
        await websocket.close(code=4401, reason="Authentication required")
        return
    origin = websocket.headers.get("origin")
    if origin is None or origin.rstrip("/") not in container.settings.trusted_origins():
        await websocket.close(code=4403, reason="Origin rejected")
        return

    await websocket.accept()
    gate = container.connection_gate
    target: _TerminalTarget | None = None
    gate_target: ConnectionTarget | None = None
    permit: ConnectionPermit | None = None
    parameters: ConnectionParameters | None = None
    session: TerminalSession | None = None
    relay_tasks: set[asyncio.Task[None]] = set()
    opened = False
    cleaned = False
    group1_acknowledged = False
    very_old_acknowledged = False
    started = monotonic()
    audit_phase = "authorization"
    audit_decision = "denied"
    audit_result = "direct_mode_required"
    cancelled: asyncio.CancelledError | None = None

    async def cleanup() -> None:
        nonlocal cleaned, parameters, permit, session, target, gate_target
        if cleaned:
            return
        cleaned = True
        for task in relay_tasks:
            task.cancel()
        if relay_tasks:
            await asyncio.gather(*relay_tasks, return_exceptions=True)
        if session is not None:
            try:
                await session.close()
            except (Exception, asyncio.CancelledError):  # noqa: S110
                pass  # Cleanup errors must not expose raw terminal or transport details.
            session = None
        if target is not None:
            try:
                await asyncio.to_thread(
                    _record_connection_audit,
                    container,
                    target,
                    group1_acknowledged,
                    very_old_acknowledged,
                    audit_phase,
                    audit_decision,
                    audit_result,
                    started,
                )
            except (Exception, asyncio.CancelledError):  # noqa: S110
                pass  # Cleanup errors must not expose raw terminal or transport details.
        if opened:
            try:
                await asyncio.to_thread(
                    _record_event,
                    container,
                    device_id,
                    "terminal.closed",
                    "Direct Mode terminal closed",
                )
            except (Exception, asyncio.CancelledError):  # noqa: S110
                pass  # Cleanup errors must not expose raw terminal or transport details.
        await _close_websocket(websocket)
        if permit is not None:
            try:
                await asyncio.to_thread(gate.release, permit)
            except (Exception, asyncio.CancelledError):  # noqa: S110
                pass  # Cleanup errors must not expose raw terminal or transport details.
            permit = None
        parameters = None
        gate_target = None
        target = None

    try:
        try:
            acknowledgement = await asyncio.wait_for(
                websocket.receive_json(), timeout=_DIRECT_MODE_TIMEOUT_SECONDS
            )
        except TimeoutError:
            raise _TerminalFailure("direct_mode_required") from None
        if not isinstance(acknowledgement, dict):
            raise _TerminalFailure("direct_mode_required")
        acknowledgement_data = cast(dict[str, object], acknowledgement)
        if acknowledgement_data.get("type") != "accept_direct_mode":
            raise _TerminalFailure("direct_mode_required")
        group1_value: object = acknowledgement_data.get("group1_risk_acknowledged", False)
        if not isinstance(group1_value, bool):
            raise _TerminalFailure("direct_mode_required")
        group1_acknowledged = group1_value
        very_old_value: object = acknowledgement_data.get("very_old_risk_acknowledged", False)
        if not isinstance(very_old_value, bool):
            raise _TerminalFailure("direct_mode_required")
        very_old_acknowledged = very_old_value
        telnet_value: object = acknowledgement_data.get("telnet_cleartext_acknowledged", False)
        if not isinstance(telnet_value, bool):
            raise _TerminalFailure("direct_mode_required")
        telnet_acknowledged = telnet_value

        target = await asyncio.to_thread(_terminal_target, container, device_id)
        if not container.settings.ssh_terminal_enabled:
            raise _TerminalFailure("terminal_disabled_by_policy")
        if target.console_transport is ConsoleTransport.TELNET:
            # All three checks run before any socket is opened.
            if not container.settings.telnet_enabled:
                raise _TerminalFailure("telnet_disabled_by_policy")
            if not target.is_lab:
                raise _TerminalFailure("telnet_requires_lab_device")
            if not telnet_acknowledged:
                raise _TerminalFailure("telnet_direct_mode_required")
        try:
            enforce_compatibility_policy(
                target.compatibility,
                container.settings,
                group1_risk_acknowledged=group1_acknowledged,
                very_old_risk_acknowledged=very_old_acknowledged,
            )
        except ConfigurationError:
            if not container.settings.ssh_legacy_enabled:
                raise _TerminalFailure("legacy_mode_disabled_by_policy") from None
            if (
                target.compatibility is SSHCompatibility.VERY_OLD_SSH
                and (
                    not container.settings.ssh_group1_enabled
                    or not container.settings.ssh_very_old_enabled
                    or not very_old_acknowledged
                )
            ):
                raise _TerminalFailure("very_old_mode_disabled_by_policy") from None
            raise _TerminalFailure("legacy_group1_disabled_by_policy") from None

        gate_target = ConnectionTarget.from_endpoint(
            host=target.host,
            port=target.port,
            credential_profile_id=target.profile_id,
            device_id=target.device_id,
        )
        permit = await _acquire_terminal_permit(gate, gate_target)
        audit_decision = "allowed"
        await websocket.send_json({"type": "status", "status": "connecting"})
        if target.console_transport is ConsoleTransport.TELNET:
            # Credentials are deliberately never decrypted or sent for Telnet:
            # the link is cleartext, so the operator types them into the
            # session exactly as they would on a console cable.
            try:
                session = await open_telnet_session(
                    target.host,
                    target.port,
                    connect_timeout_seconds=container.settings.ssh_connect_timeout_seconds,
                    close_timeout_seconds=container.settings.terminal_pty_timeout_seconds,
                )
            except (OSError, TimeoutError) as exc:
                raise _TerminalFailure(_telnet_failure_code(exc)) from None
        else:
            parameters = await asyncio.to_thread(_connection_parameters, container, target)
            session = await _open_terminal(
                parameters,
                pty_timeout_seconds=container.settings.terminal_pty_timeout_seconds,
            )
        await asyncio.to_thread(gate.authentication_succeeded, gate_target)
        _record_event(container, device_id, "terminal.opened", "Direct Mode terminal opened")
        opened = True
        await websocket.send_json({"type": "status", "status": "connected"})
        try:
            await asyncio.wait_for(
                _relay(websocket, session, relay_tasks),
                timeout=container.settings.terminal_max_duration_seconds,
            )
        except TimeoutError:
            raise _TerminalFailure("terminal_session_expired") from None
        audit_phase = "complete"
        audit_result = "success"
    except _TerminalFailure as exc:
        audit_phase = exc.spec.phase
        audit_result = exc.code
        if permit is not None and gate_target is not None:
            if exc.spec.phase == "authentication":
                try:
                    await asyncio.to_thread(gate.authentication_failed, gate_target)
                except AppError as gate_error:
                    exc = _TerminalFailure(gate_error.code)
                    audit_phase = exc.spec.phase
                    audit_result = exc.code
            elif exc.spec.phase in {"pty_creation", "terminal_io"} and not opened:
                try:
                    await asyncio.to_thread(gate.authentication_succeeded, gate_target)
                except AppError as gate_error:
                    exc = _TerminalFailure(gate_error.code)
                    audit_phase = exc.spec.phase
                    audit_result = exc.code
        await _send_error(websocket, exc.code)
    except AppError as exc:
        code = exc.code if exc.code in _FAILURES else "terminal_transport_failed"
        failure = _TerminalFailure(code)
        audit_phase = failure.spec.phase
        audit_result = failure.code
        await _send_error(websocket, failure.code)
    except WebSocketDisconnect:
        audit_phase = "terminal_io"
        audit_result = "success" if opened else "terminal_transport_failed"
    except asyncio.CancelledError as exc:
        cancelled = exc
        audit_phase = "terminal_io"
        audit_result = "terminal_transport_failed"
    except Exception:
        failure = _TerminalFailure("terminal_transport_failed")
        audit_phase = failure.spec.phase
        audit_result = failure.code
        await _send_error(websocket, failure.code)
    finally:
        cleanup_task = asyncio.create_task(cleanup())
        try:
            await asyncio.shield(cleanup_task)
        except asyncio.CancelledError as exc:
            cancelled = cancelled or exc
            await cleanup_task
        if cancelled is not None:
            raise cancelled


def _terminal_target(
    container: ApplicationContainer,
    device_id: UUID,
) -> _TerminalTarget:
    with container.session_factory() as database:
        service = DeviceService(
            database,
            settings=container.settings,
            drivers=container.drivers,
            vault=container.credential_vault,
            host_key_trust=container.host_key_trust,
        )
        device = service.get(device_id)
        return _TerminalTarget(
            device.id,
            device.management_address.strip().lower(),
            device.port,
            device.credential_profile_id,
            device.ssh_compatibility,
            device.console_transport,
            device.is_lab,
        )


def _connection_parameters(
    container: ApplicationContainer,
    target: _TerminalTarget,
) -> ConnectionParameters:
    with container.session_factory() as database:
        service = DeviceService(
            database,
            settings=container.settings,
            drivers=container.drivers,
            vault=container.credential_vault,
            host_key_trust=container.host_key_trust,
        )
        parameters = service.connection_parameters(
            device_id=target.device_id,
            profile_id=target.profile_id,
            host=target.host,
            port=target.port,
        )
        return replace(parameters, ssh_compatibility=target.compatibility)


def _record_event(
    container: ApplicationContainer,
    device_id: UUID,
    event_type: str,
    message: str,
) -> None:
    with container.session_factory() as database:
        EventRepository(database).record(
            event_type=event_type,
            message=message,
            device_id=device_id,
            details={"mode": "direct"},
        )
        database.commit()


def _record_connection_audit(
    container: ApplicationContainer,
    target: _TerminalTarget,
    group1_risk_acknowledged: bool,
    very_old_risk_acknowledged: bool,
    phase: str,
    decision: str,
    result_code: str,
    started: float,
) -> None:
    with container.session_factory() as database:
        EventRepository(database).record(
            event_type="ssh.connection_admission",
            message="SSH connection admission completed",
            device_id=target.device_id,
            details={
                "principal": "local-admin",
                "requested_mode": target.compatibility.value,
                "group1_risk_acknowledged": group1_risk_acknowledged,
                "very_old_risk_acknowledged": very_old_risk_acknowledged,
                "console_transport": target.console_transport.value,
                "compatibility_policy_version": SSH_COMPATIBILITY_POLICY_VERSION,
                "operation": ConnectionOperation.TERMINAL.value,
                "phase": phase,
                "policy_decision": decision,
                "duration_ms": min(
                    max(0, int((monotonic() - started) * 1_000)),
                    _MAX_AUDIT_DURATION_MS,
                ),
                "result_code": result_code,
            },
        )
        database.commit()


async def _relay(
    websocket: WebSocket,
    session: TerminalSession,
    tasks: set[asyncio.Task[None]],
) -> None:
    tasks.update(
        {
            asyncio.create_task(_receive(websocket, session)),
            asyncio.create_task(_send(websocket, session)),
        }
    )
    done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in done:
        task.result()


async def _receive(websocket: WebSocket, session: TerminalSession) -> None:
    while True:
        try:
            message_value: object = await asyncio.wait_for(
                websocket.receive_json(), timeout=_IDLE_TIMEOUT_SECONDS
            )
        except TimeoutError:
            raise _TerminalFailure("terminal_idle_timeout") from None
        if not isinstance(message_value, dict):
            raise _TerminalFailure("invalid_terminal_message")
        message = cast(dict[str, object], message_value)
        message_type = message.get("type")
        if message_type == "input":
            data = message.get("data")
            if not isinstance(data, str) or len(data.encode("utf-8")) > _MAX_INPUT_BYTES:
                raise _TerminalFailure("terminal_input_limit")
            await session.write(data)
        elif message_type == "resize":
            columns = message.get("columns")
            rows = message.get("rows")
            if not isinstance(columns, int) or not isinstance(rows, int):
                raise _TerminalFailure("invalid_terminal_size")
            session.resize(max(20, min(columns, 300)), max(5, min(rows, 120)))
        else:
            raise _TerminalFailure("invalid_terminal_message")


async def _send(websocket: WebSocket, session: TerminalSession) -> None:
    output_bytes = 0
    while True:
        output = await session.read(_OUTPUT_CHUNK_SIZE)
        if not output:
            await websocket.send_json({"type": "status", "status": "closed"})
            return
        output_bytes += len(output.encode("utf-8"))
        if output_bytes > _MAX_OUTPUT_BYTES:
            raise _TerminalFailure("terminal_output_limit")
        await websocket.send_json({"type": "output", "data": output})


async def _send_error(websocket: WebSocket, code: str) -> None:
    spec = _FAILURES[code]
    if isinstance(spec, SanitizedSSHFailure):
        message = _SHARED_FAILURE_MESSAGES[code]
        phase = spec.phase.value
    else:
        message = spec.message
        phase = spec.phase
    payload: dict[str, object] = {
        "type": "error",
        "code": code,
        "message": message,
        "phase": phase,
        "retryable": spec.retryable,
    }
    if spec.recommended_action is not None:
        payload["recommended_action"] = spec.recommended_action
    try:
        await websocket.send_json(payload)
    except (OSError, RuntimeError, WebSocketDisconnect):
        pass


async def _close_connection(
    connection: asyncssh.SSHClientConnection,
    timeout_seconds: float,
) -> None:
    async def close() -> None:
        try:
            connection.close()
            await asyncio.wait_for(connection.wait_closed(), timeout=timeout_seconds)
        except (Exception, asyncio.CancelledError):  # noqa: S110
            pass  # Cleanup errors must not expose raw terminal or transport details.

    await _await_cleanup(asyncio.create_task(close()))


async def _close_websocket(websocket: WebSocket) -> None:
    try:
        await websocket.close()
    except (OSError, RuntimeError, WebSocketDisconnect):
        pass
