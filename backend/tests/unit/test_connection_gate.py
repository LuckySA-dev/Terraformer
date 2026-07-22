from __future__ import annotations

import base64
import hashlib
import math
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import WatchError

from app.container import ApplicationContainer
from app.core.config import Settings
from app.services.connection_gate import (
    ConnectionOperation,
    ConnectionTarget,
    RedisConnectionGate,
)
from tests.fakes import FakeConnectionGate


class FakeRedisPipeline:
    def __init__(self, store: FakeRedisStore) -> None:
        self._store = store
        self._queued: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self._buffering = False

    def __enter__(self) -> FakeRedisPipeline:
        return self

    def __exit__(self, *_args: object) -> None:
        self._queued.clear()

    def watch(self, *keys: str) -> None:
        self._store.keys_seen.update(keys)

    def time(self) -> tuple[int, int]:
        return self._store.time()

    def get(self, key: str) -> bytes | None:
        return self._store._get(key)

    def zcount(self, key: str, minimum: float | str, maximum: float | str) -> int:
        return self._store._zcount(key, minimum, maximum)

    def multi(self) -> None:
        self._buffering = True

    def delete(self, *keys: str) -> FakeRedisPipeline:
        return self._write("delete", keys)

    def expire(self, key: str, seconds: int) -> FakeRedisPipeline:
        return self._write("expire", (key, seconds))

    def set(
        self,
        key: str,
        value: str,
        *,
        ex: int | None = None,
    ) -> FakeRedisPipeline:
        return self._write("set", (key, value), {"ex": ex})

    def zadd(self, key: str, mapping: dict[str, float]) -> FakeRedisPipeline:
        return self._write("zadd", (key, mapping))

    def zrem(self, key: str, *members: str) -> FakeRedisPipeline:
        return self._write("zrem", (key, *members))

    def zremrangebyscore(
        self,
        key: str,
        minimum: float | str,
        maximum: float | str,
    ) -> FakeRedisPipeline:
        return self._write("zremrangebyscore", (key, minimum, maximum))

    def execute(self) -> list[object]:
        if self._store.watch_errors_remaining:
            self._store.watch_errors_remaining -= 1
            raise WatchError
        results = [self._store._write(name, args, kwargs) for name, args, kwargs in self._queued]
        self._queued.clear()
        return results

    def _write(
        self,
        name: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any] | None = None,
    ) -> FakeRedisPipeline:
        assert self._buffering, "writes must be queued after MULTI"
        self._queued.append((name, args, kwargs or {}))
        return self


class FakeRedisStore:
    def __init__(self) -> None:
        self.now = 1_000.0
        self.available = True
        self.watch_errors_remaining = 0
        self.keys_seen: set[str] = set()
        self._strings: dict[str, bytes] = {}
        self._sorted_sets: dict[str, dict[str, float]] = {}
        self._expires_at: dict[str, float] = {}
        self._lock = threading.RLock()

    def advance(self, seconds: float) -> None:
        self.now += seconds
        for key in list(self._expires_at):
            self._purge(key)

    def time(self) -> tuple[int, int]:
        self._ensure_available()
        seconds = math.floor(self.now)
        return seconds, round((self.now - seconds) * 1_000_000)

    def pipeline(self) -> FakeRedisPipeline:
        self._ensure_available()
        return LockedFakeRedisPipeline(self, self._lock)

    def delete(self, *keys: str) -> int:
        self._ensure_available()
        with self._lock:
            return int(self._write("delete", keys, {}))

    def _get(self, key: str) -> bytes | None:
        self.keys_seen.add(key)
        self._purge(key)
        return self._strings.get(key)

    def _zcount(self, key: str, minimum: float | str, maximum: float | str) -> int:
        self.keys_seen.add(key)
        self._purge(key)
        minimum_value, minimum_inclusive = self._bound(minimum, negative=True)
        maximum_value, maximum_inclusive = self._bound(maximum, negative=False)
        return sum(
            1
            for score in self._sorted_sets.get(key, {}).values()
            if (score > minimum_value or (minimum_inclusive and score == minimum_value))
            and (score < maximum_value or (maximum_inclusive and score == maximum_value))
        )

    def _write(self, name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> object:
        key = args[0]
        assert isinstance(key, str)
        self.keys_seen.add(key)
        self._purge(key)
        if name == "delete":
            removed = 0
            for item in args:
                assert isinstance(item, str)
                self.keys_seen.add(item)
                removed += int(item in self._strings or item in self._sorted_sets)
                self._strings.pop(item, None)
                self._sorted_sets.pop(item, None)
                self._expires_at.pop(item, None)
            return removed
        if name == "expire":
            seconds = args[1]
            assert isinstance(seconds, int)
            self._expires_at[key] = self.now + seconds
            return True
        if name == "set":
            value = args[1]
            assert isinstance(value, str)
            self._strings[key] = value.encode()
            seconds = kwargs["ex"]
            if seconds is not None:
                self._expires_at[key] = self.now + seconds
            return True
        if name == "zadd":
            mapping = args[1]
            assert isinstance(mapping, dict)
            self._sorted_sets.setdefault(key, {}).update(mapping)
            return len(mapping)
        if name == "zrem":
            sorted_set = self._sorted_sets.get(key, {})
            return sum(int(sorted_set.pop(member, None) is not None) for member in args[1:])
        if name == "zremrangebyscore":
            sorted_set = self._sorted_sets.get(key, {})
            minimum_value, minimum_inclusive = self._bound(args[1], negative=True)
            maximum_value, maximum_inclusive = self._bound(args[2], negative=False)
            members = [
                member
                for member, score in sorted_set.items()
                if (score > minimum_value or (minimum_inclusive and score == minimum_value))
                and (score < maximum_value or (maximum_inclusive and score == maximum_value))
            ]
            for member in members:
                del sorted_set[member]
            return len(members)
        raise AssertionError(f"unsupported fake Redis operation: {name}")

    def _purge(self, key: str) -> None:
        expires_at = self._expires_at.get(key)
        if expires_at is not None and expires_at <= self.now:
            self._strings.pop(key, None)
            self._sorted_sets.pop(key, None)
            self._expires_at.pop(key, None)

    @staticmethod
    def _bound(value: float | str, *, negative: bool) -> tuple[float, bool]:
        if value == "-inf":
            return -math.inf, True
        if value == "+inf":
            return math.inf, True
        if isinstance(value, str) and value.startswith("("):
            return float(value[1:]), False
        return float(value), True

    def _ensure_available(self) -> None:
        if not self.available:
            raise RedisConnectionError("fixture Redis unavailable")


class LockedFakeRedisPipeline(FakeRedisPipeline):
    def __init__(self, store: FakeRedisStore, lock: threading.RLock) -> None:
        super().__init__(store)
        self._lock = lock

    def __enter__(self) -> LockedFakeRedisPipeline:
        self._lock.acquire()
        return self

    def __exit__(self, *_args: object) -> None:
        super().__exit__(*_args)
        self._lock.release()


@pytest.fixture
def store() -> FakeRedisStore:
    return FakeRedisStore()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        max_device_connections=10,
        connection_permit_ttl_seconds=3_900,
    )


@pytest.fixture
def gate(store: FakeRedisStore, settings: Settings) -> RedisConnectionGate:
    return RedisConnectionGate(redis_client=store, settings=settings)  # type: ignore[arg-type]


def target(*, device_id: UUID | None = None, profile_id: UUID | None = None) -> ConnectionTarget:
    return ConnectionTarget.from_endpoint(
        host="ROUTER.EXAMPLE.invalid",
        port=22,
        credential_profile_id=profile_id or uuid4(),
        device_id=device_id,
    )


def assert_code(code: str, action: Any) -> None:
    with pytest.raises(Exception) as raised:
        action()
    assert getattr(raised.value, "code", None) == code


def test_connection_test_uses_a_rolling_five_attempt_window(
    gate: RedisConnectionGate,
    store: FakeRedisStore,
) -> None:
    connection_target = target()
    for _ in range(5):
        gate.release(gate.acquire(ConnectionOperation.CONNECTION_TEST, connection_target))

    assert_code(
        "device_connection_rate_limited",
        lambda: gate.acquire(ConnectionOperation.CONNECTION_TEST, connection_target),
    )

    store.advance(60)
    gate.release(gate.acquire(ConnectionOperation.CONNECTION_TEST, connection_target))


def test_terminal_uses_a_rolling_five_attempt_window_per_device(
    gate: RedisConnectionGate,
    store: FakeRedisStore,
) -> None:
    device_id = uuid4()
    first = target(device_id=device_id)
    same_device = replace(target(device_id=device_id), credential_profile_id=uuid4())
    for connection_target in [first, same_device, first, same_device, first]:
        gate.release(gate.acquire(ConnectionOperation.TERMINAL, connection_target))

    assert_code(
        "device_connection_rate_limited",
        lambda: gate.acquire(ConnectionOperation.TERMINAL, first),
    )

    store.advance(60)
    gate.release(gate.acquire(ConnectionOperation.TERMINAL, first))


def test_third_authentication_failure_starts_tuple_scoped_cooldown(
    gate: RedisConnectionGate,
    store: FakeRedisStore,
) -> None:
    blocked = target(device_id=uuid4())
    other = target(device_id=uuid4())
    for _ in range(3):
        gate.authentication_failed(blocked)

    assert_code(
        "device_authentication_rate_limited",
        lambda: gate.acquire(ConnectionOperation.STRUCTURED_READ, blocked),
    )
    gate.release(gate.acquire(ConnectionOperation.STRUCTURED_READ, other))

    store.advance(60)
    gate.release(gate.acquire(ConnectionOperation.STRUCTURED_READ, blocked))


def test_authentication_success_clears_only_its_tuple_failure_counter(
    gate: RedisConnectionGate,
) -> None:
    profile_id = uuid4()
    cleared = target(device_id=uuid4(), profile_id=profile_id)
    untouched = ConnectionTarget.from_endpoint(
        host="switch.example.invalid",
        port=22,
        credential_profile_id=profile_id,
        device_id=uuid4(),
    )
    for _ in range(2):
        gate.authentication_failed(cleared)
        gate.authentication_failed(untouched)

    gate.authentication_succeeded(cleared)
    gate.authentication_failed(cleared)
    gate.authentication_failed(untouched)

    permit = gate.acquire(ConnectionOperation.STRUCTURED_READ, cleared)
    gate.release(permit)
    assert_code(
        "device_authentication_rate_limited",
        lambda: gate.acquire(ConnectionOperation.STRUCTURED_READ, untouched),
    )


def test_global_connection_admission_is_atomic_under_concurrency(
    store: FakeRedisStore,
    settings: Settings,
) -> None:
    limited = settings.model_copy(update={"max_device_connections": 3})
    gate = RedisConnectionGate(redis_client=store, settings=limited)  # type: ignore[arg-type]
    barrier = threading.Barrier(10)

    def acquire() -> object:
        barrier.wait()
        try:
            return gate.acquire(ConnectionOperation.STRUCTURED_READ, target(device_id=uuid4()))
        except Exception as exc:
            return exc

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(lambda _index: acquire(), range(10)))

    permits = [result for result in results if not isinstance(result, Exception)]
    denials = [result for result in results if isinstance(result, Exception)]
    assert len(permits) == 3
    assert {getattr(error, "code", None) for error in denials} == {
        "device_connection_limit_reached"
    }


def test_per_device_connection_limit_is_three(gate: RedisConnectionGate) -> None:
    device_id = uuid4()
    connection_targets = [target(device_id=device_id) for _ in range(4)]
    permits = [
        gate.acquire(ConnectionOperation.STRUCTURED_READ, connection_target)
        for connection_target in connection_targets[:3]
    ]

    assert_code(
        "device_connection_limit_reached",
        lambda: gate.acquire(ConnectionOperation.STRUCTURED_READ, connection_targets[3]),
    )
    for permit in permits:
        gate.release(permit)


def test_global_and_per_device_terminal_limits_are_three(
    gate: RedisConnectionGate,
) -> None:
    one_device = uuid4()
    same_device_permits = [
        gate.acquire(ConnectionOperation.TERMINAL, target(device_id=one_device)) for _ in range(3)
    ]
    assert_code(
        "terminal_session_limit_reached",
        lambda: gate.acquire(ConnectionOperation.TERMINAL, target(device_id=one_device)),
    )
    for permit in same_device_permits:
        gate.release(permit)

    global_permits = [
        gate.acquire(ConnectionOperation.TERMINAL, target(device_id=uuid4())) for _ in range(3)
    ]
    assert_code(
        "terminal_session_limit_reached",
        lambda: gate.acquire(ConnectionOperation.TERMINAL, target(device_id=uuid4())),
    )
    for permit in global_permits:
        gate.release(permit)


def test_terminal_target_without_device_id_fails_closed(gate: RedisConnectionGate) -> None:
    assert_code(
        "connection_gate_unavailable",
        lambda: gate.acquire(ConnectionOperation.TERMINAL, target()),
    )


def test_expired_permit_restores_capacity_after_process_death(
    store: FakeRedisStore,
    settings: Settings,
) -> None:
    limited = settings.model_copy(
        update={"max_device_connections": 1, "connection_permit_ttl_seconds": 3_900}
    )
    gate = RedisConnectionGate(redis_client=store, settings=limited)  # type: ignore[arg-type]
    first = gate.acquire(ConnectionOperation.STRUCTURED_READ, target(device_id=uuid4()))
    assert first.identifier
    assert_code(
        "device_connection_limit_reached",
        lambda: gate.acquire(ConnectionOperation.STRUCTURED_READ, target(device_id=uuid4())),
    )

    store.advance(3_900)
    recovered = gate.acquire(ConnectionOperation.STRUCTURED_READ, target(device_id=uuid4()))
    gate.release(recovered)


def test_release_is_idempotent(gate: RedisConnectionGate) -> None:
    first = gate.acquire(ConnectionOperation.STRUCTURED_READ, target(device_id=uuid4()))
    gate.release(first)
    gate.release(first)

    permits = [
        gate.acquire(ConnectionOperation.STRUCTURED_READ, target(device_id=uuid4()))
        for _ in range(10)
    ]
    for permit in permits:
        gate.release(permit)


def test_release_removes_only_the_named_permit(
    store: FakeRedisStore,
    settings: Settings,
) -> None:
    limited = settings.model_copy(update={"max_device_connections": 2})
    gate = RedisConnectionGate(redis_client=store, settings=limited)  # type: ignore[arg-type]
    first = gate.acquire(ConnectionOperation.STRUCTURED_READ, target(device_id=uuid4()))
    second = gate.acquire(ConnectionOperation.STRUCTURED_READ, target(device_id=uuid4()))

    gate.release(first)
    gate.release(first)
    replacement = gate.acquire(ConnectionOperation.STRUCTURED_READ, target(device_id=uuid4()))
    assert_code(
        "device_connection_limit_reached",
        lambda: gate.acquire(ConnectionOperation.STRUCTURED_READ, target(device_id=uuid4())),
    )

    gate.release(second)
    gate.release(replacement)


def test_transaction_retries_are_bounded_and_fail_closed(
    gate: RedisConnectionGate,
    store: FakeRedisStore,
) -> None:
    store.watch_errors_remaining = 7
    permit = gate.acquire(ConnectionOperation.STRUCTURED_READ, target(device_id=uuid4()))
    gate.release(permit)

    store.watch_errors_remaining = 8
    assert_code(
        "connection_gate_unavailable",
        lambda: gate.acquire(ConnectionOperation.STRUCTURED_READ, target(device_id=uuid4())),
    )


def test_expired_members_are_pruned_when_capacity_is_reused(
    store: FakeRedisStore,
    settings: Settings,
) -> None:
    limited = settings.model_copy(update={"max_device_connections": 1})
    gate = RedisConnectionGate(redis_client=store, settings=limited)  # type: ignore[arg-type]
    expired = gate.acquire(ConnectionOperation.STRUCTURED_READ, target(device_id=uuid4()))
    store.advance(limited.connection_permit_ttl_seconds)

    current = gate.acquire(ConnectionOperation.STRUCTURED_READ, target(device_id=uuid4()))

    active_members = {
        member
        for key, members in store._sorted_sets.items()
        if ":active:" in key
        for member in members
    }
    assert expired.identifier not in active_members
    gate.release(current)


def test_admission_without_authentication_failure_does_not_increment_failures(
    gate: RedisConnectionGate,
    store: FakeRedisStore,
) -> None:
    permit = gate.acquire(ConnectionOperation.STRUCTURED_READ, target(device_id=uuid4()))
    gate.release(permit)

    assert all(":auth:failures:" not in key for key in store.keys_seen)


@pytest.mark.parametrize(
    "action",
    [
        lambda gate, connection_target: gate.acquire(
            ConnectionOperation.STRUCTURED_READ, connection_target
        ),
        lambda gate, connection_target: gate.authentication_failed(connection_target),
        lambda gate, connection_target: gate.authentication_succeeded(connection_target),
    ],
)
def test_redis_errors_fail_closed_with_sanitized_code(
    gate: RedisConnectionGate,
    store: FakeRedisStore,
    action: Any,
) -> None:
    store.available = False
    assert_code("connection_gate_unavailable", lambda: action(gate, target(device_id=uuid4())))


def test_target_is_digested_before_redis_and_keys_contain_no_plaintext(
    gate: RedisConnectionGate,
    store: FakeRedisStore,
) -> None:
    profile_id = uuid4()
    device_id = uuid4()
    connection_target = ConnectionTarget.from_endpoint(
        host="Router.Example.Invalid",
        port=2222,
        credential_profile_id=profile_id,
        device_id=device_id,
    )
    expected = hashlib.sha256(f"router.example.invalid:2222:{profile_id}".encode()).hexdigest()
    assert connection_target.endpoint_digest == expected

    permit = gate.acquire(ConnectionOperation.CONNECTION_TEST, connection_target)
    gate.authentication_failed(connection_target)
    gate.release(permit)

    flattened = " ".join(store.keys_seen).lower()
    assert expected in flattened
    assert str(profile_id) in flattened
    assert str(device_id) in flattened
    assert "router.example.invalid" not in flattened
    assert "router.example.invalid:2222" not in flattened
    assert "fixture-password" not in flattened


def test_application_container_uses_an_injected_connection_gate() -> None:
    root_key = base64.urlsafe_b64encode(b"g" * 32).decode()
    settings = Settings(
        _env_file=None,
        app_env="test",
        master_key=SecretStr(root_key),
    )
    fake = FakeConnectionGate()

    container = ApplicationContainer(settings=settings, connection_gate=fake)

    assert container.connection_gate is fake


def test_fake_connection_gate_records_every_release_call() -> None:
    fake = FakeConnectionGate()
    permit = fake.acquire(ConnectionOperation.STRUCTURED_READ, target(device_id=uuid4()))

    fake.release(permit)
    fake.release(permit)

    assert fake.released == [permit, permit]
