from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Self, TypeVar, cast
from uuid import UUID, uuid4

from redis import Redis
from redis.client import Pipeline
from redis.exceptions import RedisError, WatchError

from app.core.config import Settings
from app.core.errors import AppError

_NAMESPACE = "connection-gate:v1"
_TRANSACTION_ATTEMPTS = 8
_T = TypeVar("_T")


class ConnectionOperation(StrEnum):
    CONNECTION_TEST = "connection_test"
    STRUCTURED_READ = "structured_read"
    TERMINAL = "terminal"


@dataclass(frozen=True, slots=True)
class ConnectionTarget:
    endpoint_digest: str
    credential_profile_id: UUID
    device_id: UUID | None

    def __post_init__(self) -> None:
        if len(self.endpoint_digest) != 64 or any(
            character not in "0123456789abcdef" for character in self.endpoint_digest
        ):
            raise ValueError("endpoint_digest must be a lowercase SHA-256 digest")

    @classmethod
    def from_endpoint(
        cls,
        *,
        host: str,
        port: int,
        credential_profile_id: UUID,
        device_id: UUID | None,
    ) -> Self:
        if not 1 <= port <= 65_535:
            raise ValueError("port must be between 1 and 65535")
        endpoint_digest = hashlib.sha256(
            f"{host.lower()}:{port}:{credential_profile_id}".encode()
        ).hexdigest()
        return cls(endpoint_digest, credential_profile_id, device_id)


@dataclass(frozen=True, slots=True)
class ConnectionPermit:
    identifier: str
    operation: ConnectionOperation
    target: ConnectionTarget


class ConnectionGateUnavailableError(AppError):
    code = "connection_gate_unavailable"
    status_code = 503
    default_message = "Connection admission is temporarily unavailable"


class DeviceConnectionRateLimitedError(AppError):
    code = "device_connection_rate_limited"
    status_code = 429
    default_message = "Too many device connection attempts"


class DeviceAuthenticationRateLimitedError(AppError):
    code = "device_authentication_rate_limited"
    status_code = 429
    default_message = "Device authentication is temporarily rate limited"


class DeviceConnectionLimitReachedError(AppError):
    code = "device_connection_limit_reached"
    status_code = 429
    default_message = "The device connection limit has been reached"


class TerminalSessionLimitReachedError(AppError):
    code = "terminal_session_limit_reached"
    status_code = 429
    default_message = "The terminal session limit has been reached"


class RedisConnectionGate:
    def __init__(self, *, redis_client: Redis, settings: Settings) -> None:
        self._redis = redis_client
        self._settings = settings

    def acquire(
        self,
        operation: ConnectionOperation,
        target: ConnectionTarget,
    ) -> ConnectionPermit:
        if operation is ConnectionOperation.TERMINAL and target.device_id is None:
            raise ConnectionGateUnavailableError()
        permit = ConnectionPermit(uuid4().hex, operation, target)
        cooldown_key = self._authentication_cooldown_key(target)
        rate_key, rate_limit = self._rate_limit(operation, target)
        active_keys = self._active_keys(permit)
        permit_key = self._permit_key(permit.identifier)
        watched_keys = [cooldown_key, permit_key, *active_keys]
        if rate_key is not None:
            watched_keys.append(rate_key)

        def admit(pipe: Pipeline) -> ConnectionPermit:
            now = self._pipeline_time(pipe)
            expiry = now + self._settings.connection_permit_ttl_seconds
            if pipe.get(cooldown_key) is not None:
                raise DeviceAuthenticationRateLimitedError()
            if rate_key is not None and self._zcount(
                pipe,
                rate_key,
                f"({now - self._settings.connection_rate_window_seconds}",
                "+inf",
            ) >= cast(int, rate_limit):
                raise DeviceConnectionRateLimitedError()

            global_key = self._global_active_key()
            if self._active_count(pipe, global_key, now) >= self._settings.max_device_connections:
                raise DeviceConnectionLimitReachedError()

            if operation is ConnectionOperation.TERMINAL:
                if (
                    self._active_count(pipe, self._terminal_active_key(), now)
                    >= self._settings.max_terminal_sessions
                ):
                    raise TerminalSessionLimitReachedError()
                terminal_device_key = self._terminal_device_active_key(
                    self._required_terminal_device_id(target)
                )
                if (
                    self._active_count(pipe, terminal_device_key, now)
                    >= self._settings.max_terminal_sessions_per_device
                ):
                    raise TerminalSessionLimitReachedError()

            if (
                target.device_id is not None
                and self._active_count(pipe, self._device_active_key(target.device_id), now)
                >= self._settings.max_connections_per_device
            ):
                raise DeviceConnectionLimitReachedError()

            pipe.multi()
            if rate_key is not None:
                cutoff = now - self._settings.connection_rate_window_seconds
                pipe.zremrangebyscore(rate_key, "-inf", cutoff)
                pipe.zadd(rate_key, {permit.identifier: now})
                pipe.expire(rate_key, self._settings.connection_rate_window_seconds)
            pipe.set(
                permit_key,
                "1",
                ex=self._settings.connection_permit_ttl_seconds,
            )
            for active_key in active_keys:
                pipe.zremrangebyscore(active_key, "-inf", now)
                pipe.zadd(active_key, {permit.identifier: expiry})
                pipe.expire(active_key, self._settings.connection_permit_ttl_seconds)
            return permit

        try:
            return self._transaction(watched_keys, admit)
        except AppError:
            raise
        except RedisError:
            raise ConnectionGateUnavailableError() from None

    def authentication_succeeded(self, target: ConnectionTarget) -> None:
        try:
            self._redis.delete(self._authentication_failures_key(target))
        except RedisError:
            raise ConnectionGateUnavailableError() from None

    def authentication_failed(self, target: ConnectionTarget) -> None:
        failures_key = self._authentication_failures_key(target)
        cooldown_key = self._authentication_cooldown_key(target)
        failure_identifier = uuid4().hex

        def record_failure(pipe: Pipeline) -> None:
            now = self._pipeline_time(pipe)
            cutoff = now - self._settings.authentication_failure_window_seconds
            failure_count = self._zcount(pipe, failures_key, f"({cutoff}", "+inf")
            pipe.multi()
            pipe.zremrangebyscore(failures_key, "-inf", cutoff)
            pipe.zadd(failures_key, {failure_identifier: now})
            pipe.expire(failures_key, self._settings.authentication_failure_window_seconds)
            if failure_count + 1 >= self._settings.authentication_failure_limit:
                pipe.set(
                    cooldown_key,
                    "1",
                    ex=self._settings.authentication_cooldown_seconds,
                )

        try:
            self._transaction([failures_key, cooldown_key], record_failure)
        except RedisError:
            raise ConnectionGateUnavailableError() from None

    def release(self, permit: ConnectionPermit) -> None:
        permit_key = self._permit_key(permit.identifier)
        active_keys = self._active_keys(permit)

        def release_permit(pipe: Pipeline) -> None:
            if pipe.get(permit_key) is None:
                return
            pipe.multi()
            pipe.delete(permit_key)
            for active_key in active_keys:
                pipe.zrem(active_key, permit.identifier)

        try:
            self._transaction([permit_key, *active_keys], release_permit)
        except RedisError:
            raise ConnectionGateUnavailableError() from None

    def _transaction(
        self,
        keys: Sequence[str],
        callback: Callable[[Pipeline], _T],
    ) -> _T:
        for _attempt in range(_TRANSACTION_ATTEMPTS):
            try:
                with self._redis.pipeline() as pipe:
                    pipe.watch(*keys)
                    result = callback(pipe)
                    pipe.execute()
                    return result
            except WatchError:
                continue
        raise ConnectionGateUnavailableError()

    @staticmethod
    def _pipeline_time(pipe: Pipeline) -> float:
        seconds, microseconds = cast(tuple[int, int], pipe.time())
        return float(seconds) + float(microseconds) / 1_000_000

    @staticmethod
    def _zcount(pipe: Pipeline, key: str, minimum: str, maximum: str) -> int:
        return int(cast(int, pipe.zcount(key, minimum, maximum)))

    def _active_count(self, pipe: Pipeline, key: str, now: float) -> int:
        return self._zcount(pipe, key, f"({now}", "+inf")

    def _rate_limit(
        self,
        operation: ConnectionOperation,
        target: ConnectionTarget,
    ) -> tuple[str | None, int | None]:
        if operation is ConnectionOperation.CONNECTION_TEST:
            return self._connection_test_rate_key(target), self._settings.connection_test_rate_limit
        if operation is ConnectionOperation.TERMINAL:
            return self._terminal_rate_key(
                self._required_terminal_device_id(target)
            ), self._settings.terminal_open_rate_limit
        return None, None

    def _active_keys(self, permit: ConnectionPermit) -> tuple[str, ...]:
        keys = [self._global_active_key()]
        device_id = permit.target.device_id
        if device_id is not None:
            keys.append(self._device_active_key(device_id))
        if permit.operation is ConnectionOperation.TERMINAL:
            keys.extend(
                (
                    self._terminal_active_key(),
                    self._terminal_device_active_key(
                        self._required_terminal_device_id(permit.target)
                    ),
                )
            )
        return tuple(keys)

    @staticmethod
    def _permit_key(identifier: str) -> str:
        return f"{_NAMESPACE}:permit:{identifier}"

    @staticmethod
    def _global_active_key() -> str:
        return f"{_NAMESPACE}:active:global"

    @staticmethod
    def _device_active_key(device_id: UUID) -> str:
        return f"{_NAMESPACE}:active:device:{device_id}"

    @staticmethod
    def _terminal_active_key() -> str:
        return f"{_NAMESPACE}:active:terminal:global"

    @staticmethod
    def _terminal_device_active_key(device_id: UUID) -> str:
        return f"{_NAMESPACE}:active:terminal:device:{device_id}"

    @staticmethod
    def _required_terminal_device_id(target: ConnectionTarget) -> UUID:
        if target.device_id is None:
            raise ConnectionGateUnavailableError()
        return target.device_id

    @staticmethod
    def _connection_test_rate_key(target: ConnectionTarget) -> str:
        return (
            f"{_NAMESPACE}:rate:connection-test:{target.endpoint_digest}:"
            f"{target.credential_profile_id}"
        )

    @staticmethod
    def _terminal_rate_key(device_id: UUID) -> str:
        return f"{_NAMESPACE}:rate:terminal:{device_id}"

    @staticmethod
    def _authentication_failures_key(target: ConnectionTarget) -> str:
        return f"{_NAMESPACE}:auth:failures:{target.endpoint_digest}:{target.credential_profile_id}"

    @staticmethod
    def _authentication_cooldown_key(target: ConnectionTarget) -> str:
        return f"{_NAMESPACE}:auth:cooldown:{target.endpoint_digest}:{target.credential_profile_id}"
