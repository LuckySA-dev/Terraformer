from __future__ import annotations

from collections.abc import Mapping
from uuid import uuid4

from app.drivers.base import ConnectionParameters, NetworkTransport
from app.models import Job
from app.services.connection_gate import (
    ConnectionOperation,
    ConnectionPermit,
    ConnectionTarget,
)


class FakeTransport(NetworkTransport):
    def __init__(
        self,
        commands: Mapping[str, str],
        *,
        open_error: Exception | None = None,
        command_error: Exception | None = None,
        command_errors: Mapping[str, Exception] | None = None,
    ) -> None:
        self.commands = dict(commands)
        self.open_error = open_error
        self.command_error = command_error
        self.command_errors = dict(command_errors or {})
        self.opened = False
        self.closed = False
        self.close_calls = 0
        self.sent_commands: list[str] = []

    def open(self) -> None:
        if self.open_error is not None:
            raise self.open_error
        self.opened = True

    def close(self) -> None:
        self.close_calls += 1
        self.closed = True

    def send_command(self, command: str) -> str:
        self.sent_commands.append(command)
        if self.command_error is not None:
            raise self.command_error
        if command in self.command_errors:
            raise self.command_errors[command]
        return self.commands[command]


class FakeTransportFactory:
    def __init__(
        self,
        commands: Mapping[str, str],
        *,
        factory_error: Exception | None = None,
        open_error: Exception | None = None,
        command_error: Exception | None = None,
        command_errors: Mapping[str, Exception] | None = None,
    ) -> None:
        self.commands = dict(commands)
        self.factory_error = factory_error
        self.open_error = open_error
        self.command_error = command_error
        self.command_errors = dict(command_errors or {})
        self.parameters: list[ConnectionParameters] = []
        self.transports: list[FakeTransport] = []

    def __call__(self, parameters: ConnectionParameters) -> FakeTransport:
        self.parameters.append(parameters)
        if self.factory_error is not None:
            raise self.factory_error
        transport = FakeTransport(
            self.commands,
            open_error=self.open_error,
            command_error=self.command_error,
            command_errors=self.command_errors,
        )
        self.transports.append(transport)
        return transport


class FakeQueue:
    def __init__(self, *, available: bool = True, workers: bool = True) -> None:
        self.available = available
        self.workers = workers
        self.enqueued: list[str] = []

    def enqueue(self, job: Job) -> str:
        if not self.available:
            from app.core.errors import QueueUnavailableError

            raise QueueUnavailableError()
        self.enqueued.append(str(job.id))
        return f"rq-{job.id}"

    def ping(self) -> bool:
        return self.available

    def has_workers(self) -> bool:
        return self.available and self.workers


class FakeConnectionGate:
    def __init__(self) -> None:
        self.acquired: list[ConnectionPermit] = []
        self.released: list[ConnectionPermit] = []
        self.authentication_successes: list[ConnectionTarget] = []
        self.authentication_failures: list[ConnectionTarget] = []
        self.acquire_error: Exception | None = None

    def acquire(
        self,
        operation: ConnectionOperation,
        target: ConnectionTarget,
    ) -> ConnectionPermit:
        if self.acquire_error is not None:
            raise self.acquire_error
        permit = ConnectionPermit(uuid4().hex, operation, target)
        self.acquired.append(permit)
        return permit

    def authentication_succeeded(self, target: ConnectionTarget) -> None:
        self.authentication_successes.append(target)

    def authentication_failed(self, target: ConnectionTarget) -> None:
        self.authentication_failures.append(target)

    def release(self, permit: ConnectionPermit) -> None:
        self.released.append(permit)
