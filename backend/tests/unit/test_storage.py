from __future__ import annotations

import base64
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.core.errors import ArtifactError, ArtifactIntegrityError, SnapshotImmutableError
from app.core.security import EnvelopeCipher, MasterKeyProvider
from app.core.storage import EncryptedSnapshotStore


def store(tmp_path: Path) -> EncryptedSnapshotStore:
    provider = MasterKeyProvider(
        key_file=tmp_path / "unused",
        key_value=SecretStr(base64.urlsafe_b64encode(b"s" * 32).decode("ascii")),
    )
    return EncryptedSnapshotStore(
        tmp_path / "snapshots",
        EnvelopeCipher(provider, purpose="snapshots-test"),
    )


def test_snapshot_is_compressed_encrypted_and_round_trips(tmp_path: Path) -> None:
    snapshots = store(tmp_path)
    snapshot_id = uuid4()
    device_id = uuid4()
    content = "hostname fixture\n" + "interface GigabitEthernet1\n" * 100

    artifact = snapshots.put(snapshot_id=snapshot_id, device_id=device_id, content=content)
    raw = (tmp_path / "snapshots" / artifact.relative_path).read_bytes()

    assert content.encode() not in raw
    assert artifact.compressed_size < artifact.plaintext_size
    assert snapshots.get(
        snapshot_id=snapshot_id,
        device_id=device_id,
        relative_path=artifact.relative_path,
        expected_sha256=artifact.sha256,
    ) == content


def test_snapshot_create_never_overwrites_existing_artifact(tmp_path: Path) -> None:
    snapshots = store(tmp_path)
    snapshot_id = uuid4()
    device_id = uuid4()
    first = snapshots.put(snapshot_id=snapshot_id, device_id=device_id, content="first")
    path = tmp_path / "snapshots" / first.relative_path
    original = path.read_bytes()

    with pytest.raises(SnapshotImmutableError):
        snapshots.put(snapshot_id=snapshot_id, device_id=device_id, content="second")

    assert path.read_bytes() == original


def test_snapshot_detects_ciphertext_tampering(tmp_path: Path) -> None:
    snapshots = store(tmp_path)
    snapshot_id = uuid4()
    device_id = uuid4()
    artifact = snapshots.put(snapshot_id=snapshot_id, device_id=device_id, content="fixture")
    path = tmp_path / "snapshots" / artifact.relative_path
    raw = bytearray(path.read_bytes())
    raw[-1] ^= 1
    path.write_bytes(raw)

    with pytest.raises(ArtifactIntegrityError):
        snapshots.get(
            snapshot_id=snapshot_id,
            device_id=device_id,
            relative_path=artifact.relative_path,
            expected_sha256=artifact.sha256,
        )


def test_snapshot_rejects_path_traversal(tmp_path: Path) -> None:
    snapshots = store(tmp_path)
    with pytest.raises(ArtifactError):
        snapshots.get(
            snapshot_id=uuid4(),
            device_id=uuid4(),
            relative_path="../outside",
            expected_sha256="0" * 64,
        )

