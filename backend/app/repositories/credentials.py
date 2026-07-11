from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.models import CredentialProfile


class CredentialProfileRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list(self) -> list[CredentialProfile]:
        statement = select(CredentialProfile).order_by(CredentialProfile.name)
        return list(self._session.scalars(statement))

    def get(self, profile_id: UUID, *, for_update: bool = False) -> CredentialProfile:
        statement = select(CredentialProfile).where(CredentialProfile.id == profile_id)
        if for_update:
            statement = statement.with_for_update()
        profile = self._session.scalar(statement)
        if profile is None:
            raise NotFoundError(
                "Credential profile not found",
                details={"resource": "credential_profile", "id": str(profile_id)},
            )
        return profile

    def find_by_name(self, name: str) -> CredentialProfile | None:
        return self._session.scalar(
            select(CredentialProfile).where(CredentialProfile.name == name)
        )

    def add(self, profile: CredentialProfile) -> CredentialProfile:
        self._session.add(profile)
        self._session.flush()
        return profile

    def delete(self, profile: CredentialProfile) -> None:
        self._session.delete(profile)
        self._session.flush()
