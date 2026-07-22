from __future__ import annotations

# pyright: reportPrivateUsage=false
import asyncio
from collections.abc import Callable
from socket import gaierror
from threading import Event as ThreadEvent
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import asyncssh
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from starlette.websockets import WebSocketDisconnect

from app.api import terminal as terminal_api
from app.container import ApplicationContainer
from app.drivers import ConnectionParameters
from app.drivers.ssh_errors import FAILURES as SSH_FAILURES
from app.models import Event, SSHCompatibility
from app.services.connection_gate import (
    ConnectionGateUnavailableError,
    DeviceAuthenticationRateLimitedError,
    DeviceConnectionLimitReachedError,
    TerminalSessionLimitReachedError,
)
from tests.fakes import FakeConnectionGate


class FakeTerminalSession:
    def __init__(
        self,
        *,
        outputs: list[str] | None = None,
        read_error: Exception | None = None,
        write_error: Exception | None = None,
    ) -> None:
        self.writes: list[str] = []
        self.sizes: list[tuple[int, int]] = []
        self.closed = False
        self.close_calls = 0
        self.read_calls = 0
        self._outputs = list(["edge-rtr-01# "] if outputs is None else outputs)
        self._read_error = read_error
        self._write_error = write_error
        self._input_received = asyncio.Event()

    async def read(self, _size: int) -> str:
        self.read_calls += 1
        if self._read_error is not None:
            raise self._read_error
        if self._outputs:
            return self._outputs.pop(0)
        await self._input_received.wait()
        return ""

    async def write(self, data: str) -> None:
        if self._write_error is not None:
            raise self._write_error
        self.writes.append(data)
        self._input_received.set()

    def resize(self, columns: int, rows: int) -> None:
        self.sizes.append((columns, rows))

    async def close(self) -> None:
        self.closed = True
        self.close_calls += 1
        self._input_received.set()


class FakeProcess:
    def __init__(self) -> None:
        self.stdout = self
        self.stdin = self
        self.closed = False
        self.writes: list[str] = []

    async def read(self, _size: int) -> str:
        return ""

    def write(self, data: str) -> None:
        self.writes.append(data)

    async def drain(self) -> None:
        return None

    def change_terminal_size(self, _columns: int, _rows: int) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


class FakeAsyncSSHConnection:
    def __init__(
        self,
        *,
        create_error: Exception | None = None,
        block_create: bool = False,
    ) -> None:
        self.process = FakeProcess()
        self.closed = False
        self.create_error = create_error
        self.block_create = block_create
        self.create_kwargs: dict[str, object] | None = None
        self.wait_closed_calls = 0

    async def create_process(self, **kwargs: object) -> FakeProcess:
        self.create_kwargs = kwargs
        if self.block_create:
            await asyncio.Event().wait()
        if self.create_error is not None:
            raise self.create_error
        return self.process

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        self.wait_closed_calls += 1
        return None


class FakeDirectWebSocket:
    def __init__(self, container: ApplicationContainer) -> None:
        self.app = SimpleNamespace(state=SimpleNamespace(container=container))
        self.cookies = {container.settings.session_cookie_name: container.session_tokens.issue()}
        self.headers = {"origin": "http://testserver"}
        self.messages: list[dict[str, object]] = []
        self.closed = False
        self._receive_calls = 0
        self._wait_forever = asyncio.Event()

    async def accept(self) -> None:
        return None

    async def receive_json(self) -> dict[str, object]:
        self._receive_calls += 1
        if self._receive_calls == 1:
            return {
                "type": "accept_direct_mode",
                "group1_risk_acknowledged": False,
            }
        await self._wait_forever.wait()
        raise AssertionError("unreachable")

    async def send_json(self, message: dict[str, object]) -> None:
        self.messages.append(message)

    async def close(self, **_kwargs: object) -> None:
        self.closed = True


def _register_device(
    client: TestClient,
    profile_id: str,
    *,
    compatibility: SSHCompatibility = SSHCompatibility.MODERN,
) -> str:
    response = client.post(
        "/api/devices",
        json={
            "name": "edge-rtr-01",
            "management_address": "192.0.2.10",
            "port": 22,
            "vendor": "cisco_iosxe",
            "credential_profile_id": profile_id,
            "ssh_compatibility": compatibility.value,
            "group1_risk_acknowledged": (compatibility is SSHCompatibility.CISCO_LEGACY_GROUP1),
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _acknowledge(websocket: Any, *, group1: bool = False) -> None:
    websocket.send_json(
        {
            "type": "accept_direct_mode",
            "group1_risk_acknowledged": group1,
        }
    )


def _receive_error(websocket: Any) -> dict[str, object]:
    while True:
        message = websocket.receive_json()
        if message.get("type") == "error":
            return message


def _parameters(mode: SSHCompatibility) -> ConnectionParameters:
    return ConnectionParameters(
        host="192.0.2.10",
        port=22,
        username="lab-user",
        password="fixture-password",
        ssh_compatibility=mode,
    )


@pytest.mark.parametrize(
    ("mode", "algorithms"),
    [
        (SSHCompatibility.MODERN, {}),
        (
            SSHCompatibility.CISCO_LEGACY,
            {
                "kex_algs": ("+diffie-hellman-group14-sha1,diffie-hellman-group-exchange-sha1"),
                "server_host_key_algs": "+ssh-rsa",
                "encryption_algs": "+aes256-cbc,aes192-cbc,aes128-cbc",
                "mac_algs": "+hmac-sha1,hmac-sha1-96",
            },
        ),
        (
            SSHCompatibility.CISCO_LEGACY_GROUP1,
            {
                "kex_algs": (
                    "+diffie-hellman-group14-sha1,"
                    "diffie-hellman-group-exchange-sha1,"
                    "diffie-hellman-group1-sha1"
                ),
                "server_host_key_algs": "+ssh-rsa",
                "encryption_algs": "+aes256-cbc,aes192-cbc,aes128-cbc",
                "mac_algs": "+hmac-sha1,hmac-sha1-96",
            },
        ),
    ],
)
def test_open_terminal_uses_exact_password_only_request_scoped_policy(
    mode: SSHCompatibility,
    algorithms: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeAsyncSSHConnection()
    captured: dict[str, object] = {}

    async def fake_connect(**kwargs: object) -> FakeAsyncSSHConnection:
        captured.update(kwargs)
        return connection

    monkeypatch.setattr(terminal_api.asyncssh, "connect", fake_connect)
    session = asyncio.run(
        terminal_api._open_terminal(_parameters(mode), strict_host_key=True, pty_timeout_seconds=1)
    )
    asyncio.run(session.close())

    assert captured == {
        "host": "192.0.2.10",
        "port": 22,
        "username": "lab-user",
        "password": "fixture-password",
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
        **algorithms,
    }
    real_options = asyncssh.SSHClientConnectionOptions(**captured)
    assert real_options.preferred_auth == ["password"]
    assert real_options.password_auth is True
    assert real_options.public_key_auth is False
    assert real_options.kbdint_auth is False
    assert real_options.host_based_auth is False
    assert real_options.gss_auth is False
    assert real_options.gss_kex is False
    assert real_options.disable_trivial_auth is True
    assert "known_hosts" not in captured
    assert connection.create_kwargs == {
        "term_type": "xterm-256color",
        "term_size": (80, 24),
    }


@pytest.mark.parametrize("mode", list(SSHCompatibility))
def test_compatibility_never_weakens_strict_host_key_verification(
    mode: SSHCompatibility,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strict: dict[str, object] = {}
    relaxed: dict[str, object] = {}

    async def strict_connect(**kwargs: object) -> FakeAsyncSSHConnection:
        strict.update(kwargs)
        return FakeAsyncSSHConnection()

    monkeypatch.setattr(terminal_api.asyncssh, "connect", strict_connect)
    session = asyncio.run(
        terminal_api._open_terminal(_parameters(mode), strict_host_key=True, pty_timeout_seconds=1)
    )
    asyncio.run(session.close())

    async def relaxed_connect(**kwargs: object) -> FakeAsyncSSHConnection:
        relaxed.update(kwargs)
        return FakeAsyncSSHConnection()

    monkeypatch.setattr(terminal_api.asyncssh, "connect", relaxed_connect)
    session = asyncio.run(
        terminal_api._open_terminal(_parameters(mode), strict_host_key=False, pty_timeout_seconds=1)
    )
    asyncio.run(session.close())

    assert "known_hosts" not in strict
    assert relaxed["known_hosts"] is None


@pytest.mark.parametrize(
    ("connect", "expected_code"),
    [
        (
            lambda: asyncio.Event().wait(),
            "device_connection_timeout",
        ),
        (
            lambda: (_ for _ in ()).throw(
                asyncssh.KeyExchangeFailed("raw peer algorithms fixture-secret")
            ),
            "legacy_ssh_negotiation_failed",
        ),
        (
            lambda: (_ for _ in ()).throw(
                asyncssh.PermissionDenied("raw credential fixture-secret")
            ),
            "device_authentication_failed",
        ),
    ],
)
def test_open_terminal_maps_connection_failures_without_raw_details(
    connect: Callable[[], Any],
    expected_code: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_connect(**_kwargs: object) -> FakeAsyncSSHConnection:
        return await connect()

    monkeypatch.setattr(terminal_api.asyncssh, "connect", fake_connect)
    parameters = _parameters(SSHCompatibility.MODERN)
    object.__setattr__(parameters, "connect_timeout_seconds", 0.01)

    with pytest.raises(terminal_api._TerminalFailure) as captured:
        asyncio.run(
            terminal_api._open_terminal(parameters, strict_host_key=True, pty_timeout_seconds=1)
        )

    assert captured.value.code == expected_code
    assert "raw" not in str(captured.value)
    assert "fixture-secret" not in str(captured.value)


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (
            asyncssh.HostKeyNotVerifiable(
                "Host key is not trusted for host arbitrary-router.example "
                "peer list [ssh-ed25519] raw-host-key-marker"
            ),
            "device_host_key_changed",
        ),
        (
            gaierror(-2, "arbitrary-router.example raw-dns-marker was not resolved"),
            "device_name_resolution_failed",
        ),
        (
            ConnectionRefusedError(10061, "arbitrary-router.example raw-refused-marker"),
            "device_connection_refused",
        ),
        (OSError("arbitrary-router.example raw-generic-marker"), "device_connection_failed"),
    ],
)
def test_open_terminal_reuses_shared_sanitized_connection_failures(
    error: Exception,
    expected_code: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_connect(**_kwargs: object) -> FakeAsyncSSHConnection:
        raise error

    monkeypatch.setattr(terminal_api.asyncssh, "connect", fake_connect)

    with pytest.raises(terminal_api._TerminalFailure) as captured:
        asyncio.run(
            terminal_api._open_terminal(
                _parameters(SSHCompatibility.MODERN),
                strict_host_key=True,
                pty_timeout_seconds=1,
            )
        )

    failure = SSH_FAILURES[expected_code]
    assert captured.value.code == failure.code
    assert captured.value.spec is failure
    assert captured.value.spec.phase is failure.phase
    assert captured.value.spec.retryable is failure.retryable
    assert captured.value.spec.recommended_action == failure.recommended_action
    rendered = str(captured.value)
    assert "arbitrary-router.example" not in rendered
    assert "raw-" not in rendered


@pytest.mark.parametrize(
    ("connection", "expected_code"),
    [
        (FakeAsyncSSHConnection(block_create=True), "terminal_pty_rejected"),
        (
            FakeAsyncSSHConnection(
                create_error=asyncssh.ChannelOpenError(
                    asyncssh.OPEN_CONNECT_FAILED, "raw shell fixture-secret"
                )
            ),
            "terminal_shell_rejected",
        ),
    ],
)
def test_open_terminal_bounds_pty_and_sanitizes_shell_rejection(
    connection: FakeAsyncSSHConnection,
    expected_code: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_connect(**_kwargs: object) -> FakeAsyncSSHConnection:
        return connection

    monkeypatch.setattr(terminal_api.asyncssh, "connect", fake_connect)
    with pytest.raises(terminal_api._TerminalFailure) as captured:
        asyncio.run(
            terminal_api._open_terminal(
                _parameters(SSHCompatibility.MODERN),
                strict_host_key=True,
                pty_timeout_seconds=0.01,
            )
        )

    assert captured.value.code == expected_code
    assert connection.closed is True
    assert "fixture-secret" not in str(captured.value)


def test_open_terminal_closes_connection_before_unexpected_create_process_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeAsyncSSHConnection(
        create_error=RuntimeError("arbitrary-router.example raw-create-marker")
    )

    async def fake_connect(**_kwargs: object) -> FakeAsyncSSHConnection:
        return connection

    monkeypatch.setattr(terminal_api.asyncssh, "connect", fake_connect)

    with pytest.raises(RuntimeError, match="raw-create-marker"):
        asyncio.run(
            terminal_api._open_terminal(
                _parameters(SSHCompatibility.MODERN),
                strict_host_key=True,
                pty_timeout_seconds=1,
            )
        )

    assert connection.closed is True
    assert connection.wait_closed_calls == 1


def test_terminal_holds_permit_until_cancelled_pty_connection_closes(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    fake_connection_gate: FakeConnectionGate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device_id = _register_device(authenticated_client, str(credential_profile["id"]))
    fake_connection_gate.acquired.clear()
    fake_connection_gate.released.clear()

    async def exercise() -> tuple[FakeAsyncSSHConnection, BaseException]:
        create_started = asyncio.Event()
        close_started = asyncio.Event()
        allow_close = asyncio.Event()
        never_finish = asyncio.Event()

        class BlockingConnection(FakeAsyncSSHConnection):
            async def create_process(self, **kwargs: object) -> FakeProcess:
                self.create_kwargs = kwargs
                create_started.set()
                await never_finish.wait()
                return self.process

            def close(self) -> None:
                super().close()
                close_started.set()

            async def wait_closed(self) -> None:
                self.wait_closed_calls += 1
                await allow_close.wait()

        connection = BlockingConnection()

        async def fake_connect(**_kwargs: object) -> FakeAsyncSSHConnection:
            return connection

        monkeypatch.setattr(terminal_api.asyncssh, "connect", fake_connect)
        websocket = FakeDirectWebSocket(container)
        task = asyncio.create_task(
            terminal_api.terminal(websocket, UUID(device_id))  # type: ignore[arg-type]
        )
        await create_started.wait()
        task.cancel()
        close_waiter = asyncio.create_task(close_started.wait())
        done, _pending = await asyncio.wait(
            {task, close_waiter}, return_when=asyncio.FIRST_COMPLETED
        )
        assert close_waiter in done, "terminal exited before closing its SSH connection"
        assert fake_connection_gate.released == []
        allow_close.set()
        result = (await asyncio.gather(task, return_exceptions=True))[0]
        assert isinstance(result, BaseException)
        return connection, result

    connection, result = asyncio.run(exercise())

    assert isinstance(result, asyncio.CancelledError)
    assert connection.closed is True
    assert connection.wait_closed_calls == 1
    assert fake_connection_gate.released == fake_connection_gate.acquired
    assert len(fake_connection_gate.released) == 1


def test_terminal_cancellation_rolls_back_a_blocked_gate_acquire(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    fake_connection_gate: FakeConnectionGate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device_id = _register_device(authenticated_client, str(credential_profile["id"]))
    fake_connection_gate.acquired.clear()
    fake_connection_gate.released.clear()
    acquire_started = ThreadEvent()
    allow_acquire = ThreadEvent()
    original_acquire = fake_connection_gate.acquire
    decrypted = False
    opened = False

    def blocked_acquire(*args: object, **kwargs: object) -> object:
        acquire_started.set()
        if not allow_acquire.wait(1):
            raise AssertionError("test did not unblock gate acquisition")
        return original_acquire(*args, **kwargs)  # type: ignore[arg-type]

    def fake_parameters(*_args: object, **_kwargs: object) -> ConnectionParameters:
        nonlocal decrypted
        decrypted = True
        return _parameters(SSHCompatibility.MODERN)

    async def fake_open(*_args: object, **_kwargs: object) -> FakeTerminalSession:
        nonlocal opened
        opened = True
        return FakeTerminalSession()

    monkeypatch.setattr(fake_connection_gate, "acquire", blocked_acquire)
    monkeypatch.setattr(terminal_api, "_connection_parameters", fake_parameters)
    monkeypatch.setattr(terminal_api, "_open_terminal", fake_open)

    async def exercise() -> BaseException:
        websocket = FakeDirectWebSocket(container)
        task = asyncio.create_task(
            terminal_api.terminal(websocket, UUID(device_id))  # type: ignore[arg-type]
        )
        assert await asyncio.to_thread(acquire_started.wait, 1)
        task.cancel()
        allow_acquire.set()
        result = (await asyncio.gather(task, return_exceptions=True))[0]
        assert isinstance(result, BaseException)
        assert websocket.closed is True
        return result

    result = asyncio.run(exercise())

    assert isinstance(result, asyncio.CancelledError)
    assert decrypted is False
    assert opened is False
    assert fake_connection_gate.released == fake_connection_gate.acquired
    assert len(fake_connection_gate.released) == 1


def test_terminal_requires_direct_mode_before_policy_or_admission(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    fake_connection_gate: FakeConnectionGate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device_id = _register_device(authenticated_client, str(credential_profile["id"]))
    fake_connection_gate.acquired.clear()
    opened = False

    async def fake_open(*_args: object, **_kwargs: object) -> FakeTerminalSession:
        nonlocal opened
        opened = True
        return FakeTerminalSession()

    monkeypatch.setattr(terminal_api, "_open_terminal", fake_open)
    with authenticated_client.websocket_connect(
        f"/ws/terminal/{device_id}", headers={"origin": "http://testserver"}
    ) as websocket:
        websocket.send_json({"type": "input", "data": "show version\r"})
        message = websocket.receive_json()

    assert message["code"] == "direct_mode_required"
    assert fake_connection_gate.acquired == []
    assert opened is False


@pytest.mark.parametrize(
    "gate_error",
    [
        TerminalSessionLimitReachedError(),
        DeviceConnectionLimitReachedError(),
        DeviceAuthenticationRateLimitedError(),
        ConnectionGateUnavailableError(),
    ],
)
def test_gate_denials_happen_before_credentials_or_ssh(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    fake_connection_gate: FakeConnectionGate,
    gate_error: Exception,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device_id = _register_device(authenticated_client, str(credential_profile["id"]))
    fake_connection_gate.acquired.clear()
    fake_connection_gate.released.clear()
    fake_connection_gate.acquire_error = gate_error
    decrypted = False
    opened = False

    def fake_parameters(*_args: object, **_kwargs: object) -> ConnectionParameters:
        nonlocal decrypted
        decrypted = True
        return _parameters(SSHCompatibility.MODERN)

    async def fake_open(*_args: object, **_kwargs: object) -> FakeTerminalSession:
        nonlocal opened
        opened = True
        return FakeTerminalSession()

    monkeypatch.setattr(terminal_api, "_connection_parameters", fake_parameters)
    monkeypatch.setattr(terminal_api, "_open_terminal", fake_open)
    with authenticated_client.websocket_connect(
        f"/ws/terminal/{device_id}", headers={"origin": "http://testserver"}
    ) as websocket:
        _acknowledge(websocket)
        message = websocket.receive_json()

    assert message["code"] == gate_error.code  # type: ignore[attr-defined]
    assert decrypted is False
    assert opened is False
    assert fake_connection_gate.released == []


@pytest.mark.parametrize(
    ("mode", "group1_ack", "settings_change", "expected_code"),
    [
        (
            SSHCompatibility.MODERN,
            False,
            {"ssh_terminal_enabled": False},
            "terminal_disabled_by_policy",
        ),
        (
            SSHCompatibility.CISCO_LEGACY,
            False,
            {"ssh_legacy_enabled": False},
            "legacy_mode_disabled_by_policy",
        ),
        (
            SSHCompatibility.CISCO_LEGACY_GROUP1,
            True,
            {"ssh_group1_enabled": False},
            "legacy_group1_disabled_by_policy",
        ),
        (
            SSHCompatibility.CISCO_LEGACY_GROUP1,
            False,
            {},
            "legacy_group1_disabled_by_policy",
        ),
    ],
)
def test_terminal_policy_denials_happen_before_gate_and_ssh(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    fake_connection_gate: FakeConnectionGate,
    mode: SSHCompatibility,
    group1_ack: bool,
    settings_change: dict[str, bool],
    expected_code: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container.settings.ssh_legacy_enabled = True
    container.settings.ssh_group1_enabled = True
    device_id = _register_device(
        authenticated_client, str(credential_profile["id"]), compatibility=mode
    )
    fake_connection_gate.acquired.clear()
    for name, value in settings_change.items():
        setattr(container.settings, name, value)
    opened = False

    async def fake_open(*_args: object, **_kwargs: object) -> FakeTerminalSession:
        nonlocal opened
        opened = True
        return FakeTerminalSession()

    monkeypatch.setattr(terminal_api, "_open_terminal", fake_open)
    with authenticated_client.websocket_connect(
        f"/ws/terminal/{device_id}", headers={"origin": "http://testserver"}
    ) as websocket:
        _acknowledge(websocket, group1=group1_ack)
        message = websocket.receive_json()

    assert message["code"] == expected_code
    assert fake_connection_gate.acquired == []
    assert opened is False


def test_terminal_relays_pty_without_recording_commands(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    session_factory: sessionmaker[Session],
    fake_connection_gate: FakeConnectionGate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device_id = _register_device(authenticated_client, str(credential_profile["id"]))
    fake_connection_gate.acquired.clear()
    fake_connection_gate.released.clear()
    fake_connection_gate.authentication_successes.clear()
    fake = FakeTerminalSession()
    captured: list[ConnectionParameters] = []
    audit_recorded = ThreadEvent()
    closed_recorded = ThreadEvent()
    release_recorded = ThreadEvent()
    record_audit = terminal_api._record_connection_audit
    record_event = terminal_api._record_event
    release = fake_connection_gate.release

    def observed_audit(*args: object, **kwargs: object) -> None:
        record_audit(*args, **kwargs)  # type: ignore[arg-type]
        audit_recorded.set()

    def observed_event(
        event_container: ApplicationContainer,
        event_device_id: object,
        event_type: str,
        message: str,
    ) -> None:
        record_event(event_container, event_device_id, event_type, message)  # type: ignore[arg-type]
        if event_type == "terminal.closed":
            closed_recorded.set()

    def observed_release(permit: object) -> None:
        release(permit)  # type: ignore[arg-type]
        release_recorded.set()

    async def fake_open(
        parameters: ConnectionParameters,
        *,
        strict_host_key: bool,
        pty_timeout_seconds: float,
    ) -> FakeTerminalSession:
        captured.append(parameters)
        assert strict_host_key is True
        assert pty_timeout_seconds == 10
        return fake

    monkeypatch.setattr(terminal_api, "_open_terminal", fake_open)
    monkeypatch.setattr(terminal_api, "_record_connection_audit", observed_audit)
    monkeypatch.setattr(terminal_api, "_record_event", observed_event)
    monkeypatch.setattr(fake_connection_gate, "release", observed_release)
    with authenticated_client.websocket_connect(
        f"/ws/terminal/{device_id}", headers={"origin": "http://testserver"}
    ) as websocket:
        _acknowledge(websocket)
        assert websocket.receive_json() == {"type": "status", "status": "connecting"}
        assert websocket.receive_json() == {"type": "status", "status": "connected"}
        assert websocket.receive_json() == {"type": "output", "data": "edge-rtr-01# "}
        websocket.send_json({"type": "resize", "columns": 120, "rows": 40})
        websocket.send_json({"type": "input", "data": "show version\r"})
        assert websocket.receive_json() == {"type": "status", "status": "closed"}
        assert audit_recorded.wait(1)
        assert closed_recorded.wait(1)
        assert release_recorded.wait(1)

    assert [(item.host, item.username, item.password) for item in captured] == [
        ("192.0.2.10", "lab-user", "fixture-password")
    ]
    assert fake.writes == ["show version\r"]
    assert fake.sizes == [(120, 40)]
    assert fake.closed is True
    assert fake_connection_gate.authentication_successes == [
        fake_connection_gate.acquired[0].target
    ]
    assert fake_connection_gate.released == fake_connection_gate.acquired
    assert len(fake_connection_gate.released) == 1
    with session_factory() as session:
        events = session.query(Event).filter(Event.event_type.like("terminal.%")).all()
        admissions = (
            session.query(Event).filter(Event.event_type == "ssh.connection_admission").all()
        )
    assert [event.event_type for event in events] == ["terminal.opened", "terminal.closed"]
    assert all("show version" not in str(event.details) for event in events)
    terminal_admission = [
        event for event in admissions if event.details.get("operation") == "terminal"
    ]
    assert len(terminal_admission) == 1
    assert set(terminal_admission[0].details) == {
        "principal",
        "requested_mode",
        "group1_risk_acknowledged",
        "compatibility_policy_version",
        "operation",
        "phase",
        "policy_decision",
        "duration_ms",
        "result_code",
    }


@pytest.mark.parametrize(
    ("session", "send_input", "expected_code"),
    [
        (
            FakeTerminalSession(write_error=OSError("raw write fixture-secret")),
            True,
            "terminal_transport_failed",
        ),
        (
            FakeTerminalSession(read_error=OSError("raw output fixture-secret")),
            False,
            "terminal_transport_failed",
        ),
    ],
)
def test_terminal_io_failures_are_sanitized_and_release_once(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    fake_connection_gate: FakeConnectionGate,
    session_factory: sessionmaker[Session],
    session: FakeTerminalSession,
    send_input: bool,
    expected_code: str,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device_id = _register_device(authenticated_client, str(credential_profile["id"]))
    fake_connection_gate.acquired.clear()
    fake_connection_gate.released.clear()
    release_recorded = ThreadEvent()
    release = fake_connection_gate.release

    def observed_release(permit: object) -> None:
        release(permit)  # type: ignore[arg-type]
        release_recorded.set()

    async def fake_open(*_args: object, **_kwargs: object) -> FakeTerminalSession:
        return session

    monkeypatch.setattr(terminal_api, "_open_terminal", fake_open)
    monkeypatch.setattr(fake_connection_gate, "release", observed_release)
    with authenticated_client.websocket_connect(
        f"/ws/terminal/{device_id}", headers={"origin": "http://testserver"}
    ) as websocket:
        _acknowledge(websocket)
        assert websocket.receive_json()["status"] == "connecting"
        assert websocket.receive_json()["status"] == "connected"
        if send_input:
            websocket.send_json({"type": "input", "data": "fixture-command\r"})
        message = _receive_error(websocket)
        assert release_recorded.wait(1)

    assert message["code"] == expected_code
    rendered = repr(message)
    assert "fixture-secret" not in rendered
    assert "fixture-command" not in rendered
    assert session.closed is True
    assert fake_connection_gate.released == fake_connection_gate.acquired
    assert len(fake_connection_gate.released) == 1
    with session_factory() as database:
        events = database.query(Event).all()
    persisted = repr([(event.message, event.details) for event in events])
    assert "fixture-secret" not in persisted
    assert "fixture-command" not in persisted
    assert "fixture-secret" not in caplog.text
    assert "fixture-command" not in caplog.text


@pytest.mark.parametrize(
    ("failure_code", "expected_successes", "expected_failures"),
    [
        ("device_connection_failed", 0, 0),
        ("device_authentication_failed", 0, 1),
        ("terminal_pty_rejected", 1, 0),
    ],
)
def test_terminal_accounts_for_authentication_by_failure_phase(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    fake_connection_gate: FakeConnectionGate,
    failure_code: str,
    expected_successes: int,
    expected_failures: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device_id = _register_device(authenticated_client, str(credential_profile["id"]))
    fake_connection_gate.acquired.clear()
    fake_connection_gate.released.clear()
    fake_connection_gate.authentication_successes.clear()
    fake_connection_gate.authentication_failures.clear()
    release_recorded = ThreadEvent()
    release = fake_connection_gate.release

    def observed_release(permit: object) -> None:
        release(permit)  # type: ignore[arg-type]
        release_recorded.set()

    async def fake_open(*_args: object, **_kwargs: object) -> FakeTerminalSession:
        raise terminal_api._TerminalFailure(failure_code)

    monkeypatch.setattr(terminal_api, "_open_terminal", fake_open)
    monkeypatch.setattr(fake_connection_gate, "release", observed_release)
    with authenticated_client.websocket_connect(
        f"/ws/terminal/{device_id}", headers={"origin": "http://testserver"}
    ) as websocket:
        _acknowledge(websocket)
        assert websocket.receive_json()["status"] == "connecting"
        assert _receive_error(websocket)["code"] == failure_code
        assert release_recorded.wait(1)

    assert len(fake_connection_gate.authentication_successes) == expected_successes
    assert len(fake_connection_gate.authentication_failures) == expected_failures
    assert fake_connection_gate.released == fake_connection_gate.acquired


def test_terminal_input_output_idle_and_duration_limits_fail_closed(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    fake_connection_gate: FakeConnectionGate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device_id = _register_device(authenticated_client, str(credential_profile["id"]))
    release_completed = ThreadEvent()
    release = fake_connection_gate.release

    def observed_release(permit: object) -> None:
        release(permit)  # type: ignore[arg-type]
        release_completed.set()

    monkeypatch.setattr(fake_connection_gate, "release", observed_release)

    def run_case(
        session: FakeTerminalSession,
        *,
        input_data: str | None = None,
        expected_code: str,
    ) -> None:
        release_completed.clear()

        async def fake_open(*_args: object, **_kwargs: object) -> FakeTerminalSession:
            return session

        monkeypatch.setattr(terminal_api, "_open_terminal", fake_open)
        with authenticated_client.websocket_connect(
            f"/ws/terminal/{device_id}", headers={"origin": "http://testserver"}
        ) as websocket:
            _acknowledge(websocket)
            assert websocket.receive_json()["status"] == "connecting"
            assert websocket.receive_json()["status"] == "connected"
            if input_data is not None:
                websocket.send_json({"type": "input", "data": input_data})
            message = _receive_error(websocket)
            assert release_completed.wait(1)
        assert message["code"] == expected_code
        assert session.closed is True

    run_case(
        FakeTerminalSession(outputs=[]),
        input_data="x" * 4_097,
        expected_code="terminal_input_limit",
    )
    monkeypatch.setattr(terminal_api, "_MAX_OUTPUT_BYTES", 4)
    run_case(
        FakeTerminalSession(outputs=["12345"]),
        expected_code="terminal_output_limit",
    )
    monkeypatch.setattr(terminal_api, "_MAX_OUTPUT_BYTES", 2_097_152)
    monkeypatch.setattr(terminal_api, "_IDLE_TIMEOUT_SECONDS", 0.01)
    run_case(
        FakeTerminalSession(outputs=[]),
        expected_code="terminal_idle_timeout",
    )
    monkeypatch.setattr(terminal_api, "_IDLE_TIMEOUT_SECONDS", 900)
    container.settings.terminal_max_duration_seconds = 0.01  # type: ignore[assignment]
    run_case(
        FakeTerminalSession(outputs=[]),
        expected_code="terminal_session_expired",
    )
    assert len(fake_connection_gate.released) == len(fake_connection_gate.acquired)


def test_slow_websocket_send_prevents_the_next_ssh_read() -> None:
    first_send_started = asyncio.Event()
    allow_send = asyncio.Event()
    session = FakeTerminalSession(outputs=["one", "two"])

    class SlowWebSocket:
        async def send_json(self, _message: object) -> None:
            first_send_started.set()
            await allow_send.wait()

    async def exercise() -> None:
        task = asyncio.create_task(terminal_api._send(SlowWebSocket(), session))  # type: ignore[arg-type]
        await first_send_started.wait()
        assert session.read_calls == 1
        allow_send.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(exercise())


@pytest.mark.parametrize("shutdown", ["client_disconnect", "app_cancellation"])
def test_terminal_shutdown_cleanup_is_idempotent(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    fake_connection_gate: FakeConnectionGate,
    shutdown: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device_id = _register_device(authenticated_client, str(credential_profile["id"]))
    fake_connection_gate.acquired.clear()
    fake_connection_gate.released.clear()
    session = FakeTerminalSession(outputs=[])

    async def fake_open(*_args: object, **_kwargs: object) -> FakeTerminalSession:
        return session

    monkeypatch.setattr(terminal_api, "_open_terminal", fake_open)

    class FakeWebSocket:
        def __init__(self) -> None:
            self.app = SimpleNamespace(state=SimpleNamespace(container=container))
            self.cookies = {
                container.settings.session_cookie_name: container.session_tokens.issue()
            }
            self.headers = {"origin": "http://testserver"}
            self.connected = asyncio.Event()
            self.disconnect = asyncio.Event()
            self.receive_calls = 0
            self.close_calls = 0

        async def accept(self) -> None:
            return None

        async def receive_json(self) -> dict[str, object]:
            self.receive_calls += 1
            if self.receive_calls == 1:
                return {
                    "type": "accept_direct_mode",
                    "group1_risk_acknowledged": False,
                }
            await self.disconnect.wait()
            raise WebSocketDisconnect()

        async def send_json(self, message: dict[str, object]) -> None:
            if message == {"type": "status", "status": "connected"}:
                self.connected.set()

        async def close(self, **_kwargs: object) -> None:
            self.close_calls += 1

    async def exercise() -> FakeWebSocket:
        websocket = FakeWebSocket()
        task = asyncio.create_task(
            terminal_api.terminal(websocket, UUID(device_id))  # type: ignore[arg-type]
        )
        await asyncio.wait_for(websocket.connected.wait(), timeout=1)
        if shutdown == "client_disconnect":
            websocket.disconnect.set()
        else:
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return websocket

    websocket = asyncio.run(exercise())
    assert session.close_calls == 1
    assert websocket.close_calls == 1
    assert fake_connection_gate.released == fake_connection_gate.acquired
    assert len(fake_connection_gate.released) == 1


def test_terminal_returns_typed_missing_device_error(
    authenticated_client: TestClient,
) -> None:
    with authenticated_client.websocket_connect(
        "/ws/terminal/2ad0db14-5a87-4147-a4e7-c98f88322464",
        headers={"origin": "http://testserver"},
    ) as websocket:
        _acknowledge(websocket)
        message = websocket.receive_json()
    assert message["code"] == "not_found"


@pytest.mark.parametrize(
    ("client_fixture", "headers", "expected_code"),
    [
        ("client", {"origin": "http://testserver"}, 4401),
        ("authenticated_client", {"origin": "https://attacker.invalid"}, 4403),
    ],
)
def test_terminal_rejects_unauthenticated_or_cross_origin_clients(
    client_fixture: str,
    headers: dict[str, str],
    expected_code: int,
    request: pytest.FixtureRequest,
) -> None:
    test_client = request.getfixturevalue(client_fixture)
    assert isinstance(test_client, TestClient)
    with pytest.raises(WebSocketDisconnect) as disconnected:
        with test_client.websocket_connect(
            "/ws/terminal/2ad0db14-5a87-4147-a4e7-c98f88322464",
            headers=headers,
        ):
            pass
    assert disconnected.value.code == expected_code
