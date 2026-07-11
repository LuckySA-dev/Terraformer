from __future__ import annotations

import gzip
import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from app.core.errors import ArtifactError, ArtifactIntegrityError, SnapshotImmutableError
from app.core.security import EnvelopeCipher

_SNAPSHOT_MAGIC = b"TFSP1"


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    relative_path: str
    sha256: str
    plaintext_size: int
    compressed_size: int
    ciphertext_size: int


class EncryptedSnapshotStore:
    """Immutable local artifacts: UTF-8 bytes -> gzip -> AES-256-GCM."""

    def __init__(self, root: Path, cipher: EnvelopeCipher) -> None:
        self._root = root.resolve()
        self._cipher = cipher

    def put(self, *, snapshot_id: UUID, device_id: UUID, content: str) -> StoredArtifact:
        plaintext = content.encode("utf-8")
        compressed = gzip.compress(plaintext, compresslevel=9, mtime=0)
        aad = self._aad(snapshot_id=snapshot_id, device_id=device_id)
        encrypted = _SNAPSHOT_MAGIC + self._cipher.encrypt(compressed, aad=aad)
        relative_path = Path(str(device_id)) / f"{snapshot_id}.snapshot"
        destination = self._safe_path(relative_path)
        if destination.exists():
            raise SnapshotImmutableError()
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._atomic_create(destination, encrypted)
        return StoredArtifact(
            relative_path=relative_path.as_posix(),
            sha256=hashlib.sha256(plaintext).hexdigest(),
            plaintext_size=len(plaintext),
            compressed_size=len(compressed),
            ciphertext_size=len(encrypted),
        )

    def get(
        self,
        *,
        snapshot_id: UUID,
        device_id: UUID,
        relative_path: str,
        expected_sha256: str,
    ) -> str:
        path = self._safe_path(Path(relative_path))
        try:
            encrypted = path.read_bytes()
        except OSError as exc:
            raise ArtifactError("Unable to read the encrypted snapshot") from exc
        if not encrypted.startswith(_SNAPSHOT_MAGIC):
            raise ArtifactIntegrityError("The snapshot artifact header is invalid")
        aad = self._aad(snapshot_id=snapshot_id, device_id=device_id)
        compressed = self._cipher.decrypt(encrypted[len(_SNAPSHOT_MAGIC) :], aad=aad)
        try:
            plaintext = gzip.decompress(compressed)
        except (gzip.BadGzipFile, EOFError, OSError) as exc:
            raise ArtifactIntegrityError("The snapshot compression stream is invalid") from exc
        digest = hashlib.sha256(plaintext).hexdigest()
        if not secrets_compare(digest, expected_sha256):
            raise ArtifactIntegrityError("The snapshot content hash does not match")
        try:
            return plaintext.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ArtifactIntegrityError("The snapshot is not valid UTF-8") from exc

    def _safe_path(self, relative_path: Path) -> Path:
        if relative_path.is_absolute():
            raise ArtifactError("Absolute artifact paths are not allowed")
        resolved = (self._root / relative_path).resolve()
        try:
            resolved.relative_to(self._root)
        except ValueError as exc:
            raise ArtifactError("Artifact path escapes the snapshot directory") from exc
        return resolved

    @staticmethod
    def _aad(*, snapshot_id: UUID, device_id: UUID) -> bytes:
        return f"snapshot:v1:{snapshot_id}:{device_id}".encode()

    @staticmethod
    def _atomic_create(destination: Path, content: bytes) -> None:
        file_descriptor, temporary_name = tempfile.mkstemp(
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(file_descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary_name, 0o600)
            try:
                # Linking a fully-fsynced temporary inode is atomic and never replaces an
                # existing immutable artifact. The temp file is on the same filesystem.
                os.link(temporary_name, destination)
            except FileExistsError as exc:
                raise SnapshotImmutableError() from exc
            os.unlink(temporary_name)
        except BaseException:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise


def secrets_compare(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left, right)
