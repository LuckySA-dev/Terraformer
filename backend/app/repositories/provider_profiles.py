from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.models import ProviderProfile


class ProviderProfileRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list(self) -> list[ProviderProfile]:
        statement = select(ProviderProfile).order_by(ProviderProfile.name)
        return list(self._session.scalars(statement))

    def get(self, profile_id: UUID, *, for_update: bool = False) -> ProviderProfile:
        statement = select(ProviderProfile).where(ProviderProfile.id == profile_id)
        if for_update:
            statement = statement.with_for_update()
        profile = self._session.scalar(statement)
        if profile is None:
            raise NotFoundError(
                "Provider profile not found",
                details={"resource": "provider_profile", "id": str(profile_id)},
            )
        return profile

    def find_by_name(self, name: str) -> ProviderProfile | None:
        return self._session.scalar(select(ProviderProfile).where(ProviderProfile.name == name))

    def add(self, profile: ProviderProfile) -> ProviderProfile:
        self._session.add(profile)
        self._session.flush()
        return profile

    def delete(self, profile: ProviderProfile) -> None:
        self._session.delete(profile)
        self._session.flush()
