from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from socket import gaierror
from typing import Protocol, cast
from uuid import UUID, uuid4

import asyncssh

from app.core.errors import (
    AppError,
    DriverConnectionError,
    DriverConnectionLostError,
    DriverConnectionRefusedError,
    DriverHostKeyUnknownError,
    DriverNameResolutionError,
    DriverSSHNegotiationError,
    DriverTimeoutError,
    HostKeyCandidateExpiredError,
    HostKeyCandidateMismatchError,
)
from app.core.time import utc_now
from app.drivers.ssh_compatibility import compatibility_policy
from app.models import SSHCompatibility
from app.schemas.devices import DeviceConnectionFields
from app.schemas.ssh_trust import HostKeyCandidateBinding, HostKeyCandidateView

_CANDIDATE_TTL_SECONDS = 15 * 60
_KEY_PREFIX = "ssh-host-key-candidate:v1:"


class RedisCandidateClient(Protocol):
    def setex(self, name: str, time: int, value: bytes) -> object: ...

    def get(self, name: str) -> object: ...

    def delete(self, *names: str) -> object: ...


@dataclass(frozen=True, slots=True)
class HostKeyMaterial:
    algorithm: str
    public_key: str
    fingerprint: str


@dataclass(frozen=True, slots=True)
class ResolvedHostKeyCandidate:
    id: UUID
    algorithm: str
    public_key: str
    fingerprint: str
    known_hosts: str


class HostKeyCandidateStore:
    def __init__(self, redis_client: RedisCandidateClient) -> None:
        self._redis = redis_client

    def create(
        self,
        request: DeviceConnectionFields,
        material: HostKeyMaterial,
    ) -> HostKeyCandidateView:
        candidate_id = uuid4()
        expires_at = utc_now() + timedelta(seconds=_CANDIDATE_TTL_SECONDS)
        payload = {
            "id": str(candidate_id),
            "binding": _binding_digest(request),
            "algorithm": material.algorithm,
            "public_key": material.public_key,
            "fingerprint": material.fingerprint,
            "expires_at": expires_at.isoformat(),
        }
        self._redis.setex(
            _key(candidate_id),
            _CANDIDATE_TTL_SECONDS,
            json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        )
        return HostKeyCandidateView(
            id=candidate_id,
            algorithm=material.algorithm,
            fingerprint=material.fingerprint,
            expires_at=expires_at,
        )

    def resolve(
        self,
        candidate_id: UUID,
        request: DeviceConnectionFields,
    ) -> ResolvedHostKeyCandidate:
        stored = self._redis.get(_key(candidate_id))
        if not isinstance(stored, bytes):
            raise HostKeyCandidateExpiredError()
        payload = cast(dict[str, str], json.loads(stored))
        try:
            expired = datetime.fromisoformat(payload["expires_at"]) <= utc_now()
        except (KeyError, ValueError):
            expired = True
        if expired:
            self.delete(candidate_id)
            raise HostKeyCandidateExpiredError()
        if payload["binding"] != _binding_digest(request):
            raise HostKeyCandidateMismatchError()
        public_key = payload["public_key"]
        return ResolvedHostKeyCandidate(
            id=candidate_id,
            algorithm=payload["algorithm"],
            public_key=public_key,
            fingerprint=payload["fingerprint"],
            known_hosts=known_hosts_line(request.management_address, request.port, public_key),
        )

    def delete(self, candidate_id: UUID) -> None:
        self._redis.delete(_key(candidate_id))


HostKeyProbe = Callable[[str, int, SSHCompatibility], Awaitable[HostKeyMaterial]]


class HostKeyTrustService:
    def __init__(
        self,
        store: HostKeyCandidateStore,
        *,
        probe: HostKeyProbe | None = None,
    ) -> None:
        self._store = store
        self._probe = probe or probe_host_key

    async def collect_candidate(
        self,
        request: DeviceConnectionFields,
    ) -> HostKeyCandidateView:
        material = await self._probe(
            request.management_address,
            request.port,
            request.ssh_compatibility,
        )
        return self._store.create(request, material)

    def resolve_candidate(
        self,
        candidate_id: UUID,
        request: DeviceConnectionFields,
    ) -> ResolvedHostKeyCandidate:
        return self._store.resolve(candidate_id, request)

    def delete_candidate(self, candidate_id: UUID) -> None:
        self._store.delete(candidate_id)


async def probe_host_key(host: str, port: int, mode: SSHCompatibility) -> HostKeyMaterial:
    policy = compatibility_policy(mode)
    values = {
        name: value
        for name, value in (
            ("kex_algs", policy.asyncssh_kex_algs),
            ("server_host_key_algs", policy.asyncssh_server_host_key_algs),
            ("encryption_algs", policy.asyncssh_encryption_algs),
            ("mac_algs", policy.asyncssh_mac_algs),
        )
        if value is not None
    }
    options = asyncssh.SSHClientConnectionOptions(config=None, **values)
    try:
        key = await asyncssh.get_server_host_key(host, port, options=options)
    except (asyncssh.Error, OSError) as exc:
        raise _probe_failure(exc) from None
    if key is None:
        raise DriverHostKeyUnknownError(details={"phase": "host_key_verification"})
    return HostKeyMaterial(
        algorithm=key.get_algorithm(),
        public_key=key.export_public_key("openssh").decode("ascii").strip(),
        fingerprint=key.get_fingerprint("sha256"),
    )


def _probe_failure(exc: asyncssh.Error | OSError) -> AppError:
    if isinstance(exc, TimeoutError):
        return DriverTimeoutError()
    if isinstance(exc, asyncssh.KeyExchangeFailed | asyncssh.ProtocolError):
        return DriverSSHNegotiationError()
    if isinstance(exc, asyncssh.ConnectionLost):
        return DriverConnectionLostError()
    if isinstance(exc, gaierror):
        return DriverNameResolutionError()
    if isinstance(exc, ConnectionRefusedError):
        return DriverConnectionRefusedError()
    return DriverConnectionError()


def _binding_digest(request: DeviceConnectionFields) -> str:
    binding = HostKeyCandidateBinding(
        management_address=request.management_address,
        port=request.port,
        vendor=request.vendor,
        credential_profile_id=request.credential_profile_id,
        ssh_compatibility=request.ssh_compatibility,
    )
    encoded = binding.model_dump_json().encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def known_hosts_line(host: str, port: int, public_key: str) -> str:
    endpoint = host if port == 22 else f"[{host}]:{port}"
    return f"{endpoint} {public_key}\n"


def _key(candidate_id: UUID) -> str:
    return f"{_KEY_PREFIX}{candidate_id}"
