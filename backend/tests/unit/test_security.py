from __future__ import annotations

import base64
from pathlib import Path

import pytest
from pydantic import SecretStr

from app.core.errors import ArtifactIntegrityError, ConfigurationError
from app.core.security import (
    EnvelopeCipher,
    MasterKeyProvider,
    PasswordService,
    SessionTokenService,
)


def provider(tmp_path: Path) -> MasterKeyProvider:
    value = base64.urlsafe_b64encode(b"m" * 32).decode("ascii")
    return MasterKeyProvider(key_file=tmp_path / "unused", key_value=SecretStr(value))


def test_argon2id_hash_and_verify() -> None:
    passwords = PasswordService()
    encoded = passwords.hash("correct horse battery staple")

    assert encoded.startswith("$argon2id$")
    assert passwords.verify(encoded, "correct horse battery staple") is True
    assert passwords.verify(encoded, "wrong password") is False
    assert "correct horse battery staple" not in encoded


def test_envelope_uses_random_nonce_and_authenticated_aad(tmp_path: Path) -> None:
    cipher = EnvelopeCipher(provider(tmp_path), purpose="unit-test")
    first = cipher.encrypt(b"sensitive", aad=b"record:1")
    second = cipher.encrypt(b"sensitive", aad=b"record:1")

    assert first != second
    assert b"sensitive" not in first
    assert cipher.decrypt(first, aad=b"record:1") == b"sensitive"
    with pytest.raises(ArtifactIntegrityError):
        cipher.decrypt(first, aad=b"record:2")


def test_envelope_detects_tampering(tmp_path: Path) -> None:
    cipher = EnvelopeCipher(provider(tmp_path), purpose="unit-test")
    envelope = bytearray(cipher.encrypt(b"sensitive", aad=b"record:1"))
    envelope[-1] ^= 1

    with pytest.raises(ArtifactIntegrityError):
        cipher.decrypt(bytes(envelope), aad=b"record:1")


def test_master_key_rejects_wrong_length(tmp_path: Path) -> None:
    key_file = tmp_path / "master.key"
    key_file.write_text(base64.urlsafe_b64encode(b"short").decode("ascii"), encoding="utf-8")

    with pytest.raises(ConfigurationError):
        MasterKeyProvider(key_file=key_file).get_key()


def test_session_tokens_are_signed_and_expire(tmp_path: Path) -> None:
    tokens = SessionTokenService(provider(tmp_path), ttl_seconds=60)
    token = tokens.issue()

    assert tokens.verify(token) is not None
    payload, signature = token.split(".")
    replacement = "A" if signature[0] != "A" else "B"
    assert tokens.verify(f"{payload}.{replacement}{signature[1:]}") is None
    expired = SessionTokenService(provider(tmp_path), ttl_seconds=-1).issue()
    assert tokens.verify(expired) is None
