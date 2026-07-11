from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.schemas.common import APIModel


class ConfigSnapshotView(APIModel):
    id: UUID
    device_id: UUID
    sha256: str
    plaintext_size: int
    compressed_size: int
    ciphertext_size: int
    compression: str
    encryption: str
    source: str
    created_at: datetime


class ConfigSnapshotContentView(ConfigSnapshotView):
    content: str

