from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.models import ConfigSnapshot


class ConfigSnapshotRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, snapshot: ConfigSnapshot) -> ConfigSnapshot:
        self._session.add(snapshot)
        self._session.flush()
        return snapshot

    def get(self, snapshot_id: UUID) -> ConfigSnapshot:
        snapshot = self._session.get(ConfigSnapshot, snapshot_id)
        if snapshot is None:
            raise NotFoundError(
                "Configuration snapshot not found",
                details={"resource": "config_snapshot", "id": str(snapshot_id)},
            )
        return snapshot

    def list(self, *, device_id: UUID | None = None, limit: int = 100) -> list[ConfigSnapshot]:
        statement = select(ConfigSnapshot)
        if device_id is not None:
            statement = statement.where(ConfigSnapshot.device_id == device_id)
        statement = statement.order_by(ConfigSnapshot.created_at.desc()).limit(limit)
        return list(self._session.scalars(statement))

