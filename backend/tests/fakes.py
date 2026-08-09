from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import uuid4

from app.analysis.client import FilterVerdict, InterfaceProperty, RawFinding, TraceResult
from app.analysis.types import Layer1Edge
from app.core.errors import AnalysisSnapshotExpiredError
from app.drivers.base import ConnectionParameters, NetworkTransport
from app.models import Job
from app.services.connection_gate import (
    ConnectionOperation,
    ConnectionPermit,
    ConnectionTarget,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    def setex(self, name: str, time: int, value: bytes) -> bool:
        del time
        self.values[name] = value
        return True

    def get(self, name: str) -> bytes | None:
        return self.values.get(name)

    def delete(self, *names: str) -> int:
        return sum(int(self.values.pop(name, None) is not None) for name in names)


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
        self.sent_config_batches: list[list[str]] = []

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

    def send_config(self, commands: Sequence[str]) -> str:
        batch = list(commands)
        self.sent_config_batches.append(batch)
        for command in batch:
            self.sent_commands.append(command)
            if self.command_error is not None:
                raise self.command_error
            if command in self.command_errors:
                raise self.command_errors[command]
        return "\n".join(self.commands.get(command, "") for command in batch)


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


class FakeBatfishClient:
    """In-memory analysis backend, typed against the AnalysisBackend Protocol.

    Records exactly what was handed to Batfish so tests can assert that no raw
    secret left the database.
    """

    def __init__(self) -> None:
        self.snapshots: dict[str, dict[str, str]] = {}
        self.layer1_edges: dict[str, tuple[Layer1Edge, ...]] = {}
        self.parse_findings_result: tuple[RawFinding, ...] = ()
        self.interface_properties_result: tuple[InterfaceProperty, ...] = ()
        self.trace_result: TraceResult | None = None
        self.filter_verdict: FilterVerdict | None = None
        self.init_error: Exception | None = None

    def init_snapshot(
        self, name: str, configs: Mapping[str, str], layer1_edges: Sequence[Layer1Edge]
    ) -> None:
        if self.init_error is not None:
            raise self.init_error
        self.snapshots[name] = dict(configs)
        self.layer1_edges[name] = tuple(layer1_edges)

    def snapshot_exists(self, name: str) -> bool:
        return name in self.snapshots

    def parse_findings(self, name: str) -> tuple[RawFinding, ...]:
        self._require(name)
        return self.parse_findings_result

    def interface_properties(self, name: str) -> tuple[InterfaceProperty, ...]:
        self._require(name)
        return self.interface_properties_result

    def traceroute(self, name: str, start_hostname: str, destination_ip: str) -> TraceResult:
        del start_hostname, destination_ip
        self._require(name)
        assert self.trace_result is not None, "set trace_result before calling traceroute"
        return self.trace_result

    def test_filter(
        self,
        name: str,
        hostname: str,
        filter_name: str,
        destination_ip: str,
        protocol: str,
        destination_port: int | None,
    ) -> FilterVerdict:
        del hostname, filter_name, destination_ip, protocol, destination_port
        self._require(name)
        assert self.filter_verdict is not None, "set filter_verdict before calling test_filter"
        return self.filter_verdict

    def forget(self, name: str) -> None:
        """Simulate the container losing a parsed snapshot on restart."""
        self.snapshots.pop(name, None)

    def _require(self, name: str) -> None:
        if name not in self.snapshots:
            raise AnalysisSnapshotExpiredError()
