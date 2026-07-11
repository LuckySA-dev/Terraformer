from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from pydantic import SecretStr

from app.core.errors import ArtifactIntegrityError, ConfigurationError
from app.core.time import utc_now

_KEY_BYTES = 32
_NONCE_BYTES = 12
_ENVELOPE_VERSION = b"TFEN1"


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


class MasterKeyProvider:
    """Loads a 256-bit root key from a mounted secret file or a secret environment value."""

    def __init__(self, *, key_file: Path, key_value: SecretStr | None = None) -> None:
        self._key_file = key_file
        self._key_value = key_value
        self._cached: bytes | None = None

    def get_key(self) -> bytes:
        if self._cached is not None:
            return self._cached
        raw = self._read_secret()
        key = self._decode_key(raw)
        self._cached = key
        return key

    def derive_key(self, purpose: str) -> bytes:
        if not purpose or len(purpose) > 128:
            raise ConfigurationError("Invalid encryption key purpose")
        return HKDF(
            algorithm=hashes.SHA256(),
            length=_KEY_BYTES,
            salt=b"terraformer-backend-v1",
            info=purpose.encode("utf-8"),
        ).derive(self.get_key())

    def _read_secret(self) -> bytes:
        if self._key_value is not None:
            return self._key_value.get_secret_value().strip().encode("ascii")
        try:
            return self._key_file.read_bytes().strip()
        except OSError as exc:
            raise ConfigurationError(
                "Unable to load the master key",
                details={"setting": "MASTER_KEY_FILE"},
            ) from exc

    @staticmethod
    def _decode_key(raw: bytes) -> bytes:
        if len(raw) == _KEY_BYTES:
            return raw
        try:
            decoded = base64.urlsafe_b64decode(raw + b"=" * (-len(raw) % 4))
        except (ValueError, binascii.Error) as exc:
            raise ConfigurationError("Master key must be raw or URL-safe base64") from exc
        if len(decoded) != _KEY_BYTES:
            raise ConfigurationError("Master key must decode to exactly 32 bytes")
        return decoded


class EnvelopeCipher:
    """Versioned AES-256-GCM envelope using a purpose-derived key and caller-supplied AAD."""

    def __init__(self, key_provider: MasterKeyProvider, *, purpose: str) -> None:
        self._key_provider = key_provider
        self._purpose = purpose

    def encrypt(self, plaintext: bytes, *, aad: bytes) -> bytes:
        nonce = secrets.token_bytes(_NONCE_BYTES)
        cipher = AESGCM(self._key_provider.derive_key(self._purpose))
        ciphertext = cipher.encrypt(nonce, plaintext, aad)
        return _ENVELOPE_VERSION + nonce + ciphertext

    def decrypt(self, envelope: bytes, *, aad: bytes) -> bytes:
        minimum_length = len(_ENVELOPE_VERSION) + _NONCE_BYTES + 16
        if len(envelope) < minimum_length or not envelope.startswith(_ENVELOPE_VERSION):
            raise ArtifactIntegrityError("The encrypted envelope has an invalid format")
        offset = len(_ENVELOPE_VERSION)
        nonce = envelope[offset : offset + _NONCE_BYTES]
        ciphertext = envelope[offset + _NONCE_BYTES :]
        cipher = AESGCM(self._key_provider.derive_key(self._purpose))
        try:
            return cipher.decrypt(nonce, ciphertext, aad)
        except InvalidTag as exc:
            raise ArtifactIntegrityError() from exc


class PasswordService:
    def __init__(self) -> None:
        self._hasher = PasswordHasher(
            time_cost=3,
            memory_cost=65_536,
            parallelism=4,
            hash_len=32,
            salt_len=16,
            type=Type.ID,
        )

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, encoded_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(encoded_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, encoded_hash: str) -> bool:
        try:
            return self._hasher.check_needs_rehash(encoded_hash)
        except InvalidHashError:
            return True


@dataclass(frozen=True, slots=True)
class SessionClaims:
    issued_at: int
    expires_at: int
    nonce: str


class SessionTokenService:
    def __init__(self, key_provider: MasterKeyProvider, *, ttl_seconds: int) -> None:
        self._signing_key = key_provider.derive_key("local-session-signing")
        self._ttl_seconds = ttl_seconds

    def issue(self) -> str:
        issued_at = int(utc_now().timestamp())
        payload = {
            "iat": issued_at,
            "exp": issued_at + self._ttl_seconds,
            "nonce": secrets.token_urlsafe(16),
            "v": 1,
        }
        encoded_payload = _b64url_encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
        signature = hmac.new(
            self._signing_key,
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        return f"{encoded_payload}.{_b64url_encode(signature)}"

    def verify(self, token: str) -> SessionClaims | None:
        try:
            encoded_payload, encoded_signature = token.split(".", 1)
            actual = _b64url_decode(encoded_signature)
            expected = hmac.new(
                self._signing_key,
                encoded_payload.encode("ascii"),
                hashlib.sha256,
            ).digest()
            if not hmac.compare_digest(actual, expected):
                return None
            payload: dict[str, Any] = json.loads(_b64url_decode(encoded_payload))
            if payload.get("v") != 1:
                return None
            issued_at = int(payload["iat"])
            expires_at = int(payload["exp"])
            nonce = str(payload["nonce"])
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, binascii.Error):
            return None
        now = int(utc_now().timestamp())
        if issued_at > now + 60 or expires_at <= now or expires_at <= issued_at:
            return None
        return SessionClaims(issued_at=issued_at, expires_at=expires_at, nonce=nonce)
