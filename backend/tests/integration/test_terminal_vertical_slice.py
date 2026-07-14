from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from starlette.websockets import WebSocketDisconnect

from app.api import terminal as terminal_api
from app.container import ApplicationContainer
from app.drivers import ConnectionParameters
from app.models import Event


class FakeTerminalSession:
    def __init__(self) -> None:
        self.writes: list[str] = []
        self.sizes: list[tuple[int, int]] = []
        self.closed = False
        self._input_received = asyncio.Event()
        self._sent_prompt = False

    async def read(self, _size: int) -> str:
        if not self._sent_prompt:
            self._sent_prompt = True
            return "edge-rtr-01# "
        await self._input_received.wait()
        return ""

    async def write(self, data: str) -> None:
        self.writes.append(data)
        self._input_received.set()

    def resize(self, columns: int, rows: int) -> None:
        self.sizes.append((columns, rows))

    async def close(self) -> None:
        self.closed = True


def _register_device(client: TestClient, profile_id: str) -> str:
    response = client.post(
        "/api/devices",
        json={
            "name": "edge-rtr-01",
            "management_address": "192.0.2.10",
            "port": 22,
            "vendor": "cisco_iosxe",
            "credential_profile_id": profile_id,
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def test_terminal_requires_direct_mode_before_opening_ssh(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device_id = _register_device(authenticated_client, str(credential_profile["id"]))
    opened = False

    async def fake_open(
        _parameters: ConnectionParameters,
        *,
        strict_host_key: bool,
    ) -> FakeTerminalSession:
        nonlocal opened
        opened = True
        assert strict_host_key is True
        return FakeTerminalSession()

    monkeypatch.setattr(terminal_api, "_open_terminal", fake_open)
    with authenticated_client.websocket_connect(
        f"/ws/terminal/{device_id}", headers={"origin": "http://testserver"}
    ) as websocket:
        websocket.send_json({"type": "input", "data": "show version\r"})
        message = websocket.receive_json()

    assert message["code"] == "direct_mode_required"
    assert opened is False


def test_terminal_relays_pty_without_recording_commands(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device_id = _register_device(authenticated_client, str(credential_profile["id"]))
    fake = FakeTerminalSession()
    captured: list[ConnectionParameters] = []

    async def fake_open(
        parameters: ConnectionParameters,
        *,
        strict_host_key: bool,
    ) -> FakeTerminalSession:
        captured.append(parameters)
        assert strict_host_key is True
        return fake

    monkeypatch.setattr(terminal_api, "_open_terminal", fake_open)
    with authenticated_client.websocket_connect(
        f"/ws/terminal/{device_id}", headers={"origin": "http://testserver"}
    ) as websocket:
        websocket.send_json({"type": "accept_direct_mode"})
        assert websocket.receive_json() == {"type": "status", "status": "connecting"}
        assert websocket.receive_json() == {"type": "status", "status": "connected"}
        assert websocket.receive_json() == {"type": "output", "data": "edge-rtr-01# "}
        websocket.send_json({"type": "resize", "columns": 120, "rows": 40})
        websocket.send_json({"type": "input", "data": "show version\r"})
        assert websocket.receive_json() == {"type": "status", "status": "closed"}

    assert [(item.host, item.username, item.password) for item in captured] == [
        ("192.0.2.10", "lab-user", "fixture-password")
    ]
    assert fake.writes == ["show version\r"]
    assert fake.sizes == [(120, 40)]
    assert fake.closed is True
    with session_factory() as session:
        events = session.query(Event).filter(Event.event_type.like("terminal.%")).all()
    assert [event.event_type for event in events] == ["terminal.opened", "terminal.closed"]
    assert all("show version" not in str(event.details) for event in events)


def test_terminal_session_limit_is_enforced_by_the_server(
    authenticated_client: TestClient,
    container: ApplicationContainer,
) -> None:
    assert all(container.reserve_terminal_session() for _ in range(3))
    try:
        with authenticated_client.websocket_connect(
            "/ws/terminal/2ad0db14-5a87-4147-a4e7-c98f88322464",
            headers={"origin": "http://testserver"},
        ) as websocket:
            websocket.send_json({"type": "accept_direct_mode"})
            message = websocket.receive_json()
        assert message["code"] == "terminal_session_limit"
    finally:
        for _ in range(3):
            container.release_terminal_session()


def test_terminal_returns_typed_missing_device_error(
    authenticated_client: TestClient,
) -> None:
    with authenticated_client.websocket_connect(
        "/ws/terminal/2ad0db14-5a87-4147-a4e7-c98f88322464",
        headers={"origin": "http://testserver"},
    ) as websocket:
        websocket.send_json({"type": "accept_direct_mode"})
        assert websocket.receive_json() == {"type": "status", "status": "connecting"}
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
