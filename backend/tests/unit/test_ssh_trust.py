from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.core.errors import HostKeyCandidateExpiredError, HostKeyCandidateMismatchError
from app.models import SSHCompatibility, Vendor
from app.schemas.ssh_trust import HostKeyCandidateRequest
from app.services.ssh_trust import (
    HostKeyCandidateStore,
    HostKeyMaterial,
    HostKeyTrustService,
)


class MemoryRedis:
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


def request(**changes: object) -> HostKeyCandidateRequest:
    values: dict[str, object] = {
        "management_address": "edge.example.test",
        "port": 22,
        "vendor": Vendor.CISCO_IOSXE,
        "credential_profile_id": uuid4(),
        "ssh_compatibility": SSHCompatibility.CISCO_LEGACY,
        "group1_risk_acknowledged": False,
    }
    values.update(changes)
    return HostKeyCandidateRequest.model_validate(values)


def test_candidate_is_bound_to_exact_endpoint_profile_and_mode() -> None:
    redis = MemoryRedis()
    expected = HostKeyMaterial(
        algorithm="ssh-rsa",
        public_key="ssh-rsa AAAAfixture",
        fingerprint="SHA256:fixture",
    )

    async def probe(_host: str, _port: int, _mode: SSHCompatibility) -> HostKeyMaterial:
        return expected

    service = HostKeyTrustService(
        HostKeyCandidateStore(redis),  # type: ignore[arg-type]
        probe=probe,
    )
    original = request()
    candidate = asyncio.run(service.collect_candidate(original))

    assert candidate.algorithm == "ssh-rsa"
    assert candidate.fingerprint == "SHA256:fixture"
    resolved = service.resolve_candidate(candidate.id, original)
    assert resolved.known_hosts == "edge.example.test ssh-rsa AAAAfixture\n"

    with pytest.raises(HostKeyCandidateMismatchError):
        service.resolve_candidate(candidate.id, request(port=2222))


def test_candidate_payload_contains_no_credentials() -> None:
    redis = MemoryRedis()

    async def probe(_host: str, _port: int, _mode: SSHCompatibility) -> HostKeyMaterial:
        return HostKeyMaterial("ssh-ed25519", "ssh-ed25519 AAAAfixture", "SHA256:safe")

    service = HostKeyTrustService(
        HostKeyCandidateStore(redis),  # type: ignore[arg-type]
        probe=probe,
    )
    asyncio.run(service.collect_candidate(request()))

    payload = json.loads(next(iter(redis.values.values())))
    assert set(payload) == {
        "id",
        "binding",
        "algorithm",
        "public_key",
        "fingerprint",
        "expires_at",
    }
    assert "password" not in json.dumps(payload).lower()


def test_expired_candidate_fails_closed_even_if_storage_retains_it() -> None:
    redis = MemoryRedis()

    async def probe(_host: str, _port: int, _mode: SSHCompatibility) -> HostKeyMaterial:
        return HostKeyMaterial("ssh-ed25519", "ssh-ed25519 AAAAfixture", "SHA256:safe")

    service = HostKeyTrustService(
        HostKeyCandidateStore(redis),  # type: ignore[arg-type]
        probe=probe,
    )
    original = request()
    candidate = asyncio.run(service.collect_candidate(original))
    key = next(iter(redis.values))
    payload = json.loads(redis.values[key])
    payload["expires_at"] = datetime(2000, 1, 1, tzinfo=UTC).isoformat()
    redis.values[key] = json.dumps(payload).encode()

    with pytest.raises(HostKeyCandidateExpiredError):
        service.resolve_candidate(candidate.id, original)
