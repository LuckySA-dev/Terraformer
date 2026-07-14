from __future__ import annotations

import asyncio
from typing import Protocol, cast
from uuid import UUID

import asyncssh
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.container import ApplicationContainer
from app.core.errors import AppError
from app.drivers import ConnectionParameters
from app.repositories.events import EventRepository
from app.services.devices import DeviceService

router = APIRouter()

_DIRECT_MODE_TIMEOUT_SECONDS = 30
_IDLE_TIMEOUT_SECONDS = 900
_MAX_INPUT_BYTES = 4_096
_MAX_OUTPUT_BYTES = 2_097_152
_OUTPUT_CHUNK_SIZE = 4_096


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
    ) -> None:
        self._connection = connection
        self._process = process

    async def read(self, size: int) -> str:
        return await self._process.stdout.read(size)

    async def write(self, data: str) -> None:
        self._process.stdin.write(data)
        await self._process.stdin.drain()

    def resize(self, columns: int, rows: int) -> None:
        self._process.change_terminal_size(columns, rows)

    async def close(self) -> None:
        self._process.close()
        await self._process.wait_closed()
        self._connection.close()
        await self._connection.wait_closed()


async def _open_terminal(
    parameters: ConnectionParameters,
    *,
    strict_host_key: bool,
) -> TerminalSession:
    options: dict[str, object] = {
        "host": parameters.host,
        "port": parameters.port,
        "username": parameters.username,
        "password": parameters.password,
        "connect_timeout": parameters.connect_timeout_seconds,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if not strict_host_key:
        options["known_hosts"] = None
    connection = await asyncssh.connect(**options)
    try:
        process = await connection.create_process(
            term_type="xterm-256color",
            term_size=(80, 24),
        )
    except BaseException:
        connection.close()
        await connection.wait_closed()
        raise
    return AsyncSSHTerminalSession(connection, process)


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
    session: TerminalSession | None = None
    opened = False
    reserved = False
    try:
        acknowledgement = await asyncio.wait_for(
            websocket.receive_json(), timeout=_DIRECT_MODE_TIMEOUT_SECONDS
        )
        if acknowledgement != {"type": "accept_direct_mode"}:
            await _send_error(websocket, "direct_mode_required", "Confirm Direct Mode first")
            return

        if not container.reserve_terminal_session():
            await _send_error(
                websocket,
                "terminal_session_limit",
                "Three terminal sessions are already active",
            )
            return
        reserved = True

        await websocket.send_json({"type": "status", "status": "connecting"})
        parameters = _connection_parameters(container, device_id)
        session = await _open_terminal(
            parameters,
            strict_host_key=container.settings.ssh_strict_host_key,
        )
        _record_event(container, device_id, "terminal.opened", "Direct Mode terminal opened")
        opened = True
        await websocket.send_json({"type": "status", "status": "connected"})
        await _relay(websocket, session)
    except TimeoutError:
        await _send_error(websocket, "terminal_timeout", "Terminal session timed out")
    except asyncssh.PermissionDenied:
        await _send_error(
            websocket,
            "device_authentication_failed",
            "The device rejected the credential profile",
        )
    except (asyncssh.Error, OSError):
        await _send_error(
            websocket,
            "device_connection_failed",
            "Unable to open the device terminal",
        )
    except AppError as exc:
        await _send_error(websocket, exc.code, exc.message)
    except WebSocketDisconnect:
        pass
    finally:
        try:
            if session is not None:
                await session.close()
        finally:
            if reserved:
                container.release_terminal_session()
            try:
                if opened:
                    _record_event(
                        container,
                        device_id,
                        "terminal.closed",
                        "Direct Mode terminal closed",
                    )
            finally:
                await _close_websocket(websocket)


def _connection_parameters(
    container: ApplicationContainer,
    device_id: UUID,
) -> ConnectionParameters:
    with container.session_factory() as database:
        service = DeviceService(
            database,
            settings=container.settings,
            drivers=container.drivers,
            vault=container.credential_vault,
        )
        device = service.get(device_id)
        return service.connection_parameters(
            profile_id=device.credential_profile_id,
            host=device.management_address,
            port=device.port,
        )


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


async def _relay(websocket: WebSocket, session: TerminalSession) -> None:
    receive = asyncio.create_task(_receive(websocket, session))
    send = asyncio.create_task(_send(websocket, session))
    done, pending = await asyncio.wait({receive, send}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    for task in done:
        task.result()


async def _receive(websocket: WebSocket, session: TerminalSession) -> None:
    while True:
        message_value: object = await asyncio.wait_for(
            websocket.receive_json(), timeout=_IDLE_TIMEOUT_SECONDS
        )
        if not isinstance(message_value, dict):
            await _send_error(websocket, "invalid_terminal_message", "Invalid terminal message")
            return
        message = cast(dict[str, object], message_value)
        message_type = message.get("type")
        if message_type == "input":
            data = message.get("data")
            if not isinstance(data, str) or len(data.encode("utf-8")) > _MAX_INPUT_BYTES:
                await _send_error(websocket, "terminal_input_limit", "Terminal input is too large")
                return
            await session.write(data)
        elif message_type == "resize":
            columns = message.get("columns")
            rows = message.get("rows")
            if not isinstance(columns, int) or not isinstance(rows, int):
                await _send_error(websocket, "invalid_terminal_size", "Invalid terminal size")
                return
            session.resize(max(20, min(columns, 300)), max(5, min(rows, 120)))
        else:
            await _send_error(websocket, "invalid_terminal_message", "Invalid terminal message")
            return


async def _send(websocket: WebSocket, session: TerminalSession) -> None:
    output_bytes = 0
    while True:
        output = await session.read(_OUTPUT_CHUNK_SIZE)
        if not output:
            await websocket.send_json({"type": "status", "status": "closed"})
            return
        output_bytes += len(output.encode("utf-8"))
        if output_bytes > _MAX_OUTPUT_BYTES:
            await _send_error(
                websocket,
                "terminal_output_limit",
                "Terminal output limit reached; open a new session",
            )
            return
        await websocket.send_json({"type": "output", "data": output})


async def _send_error(websocket: WebSocket, code: str, message: str) -> None:
    try:
        await websocket.send_json({"type": "error", "code": code, "message": message})
    except (RuntimeError, WebSocketDisconnect):
        pass


async def _close_websocket(websocket: WebSocket) -> None:
    try:
        await websocket.close()
    except (RuntimeError, WebSocketDisconnect):
        pass
