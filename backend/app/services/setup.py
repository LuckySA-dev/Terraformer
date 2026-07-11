from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AlreadyConfiguredError, InvalidCredentialsError, SetupRequiredError
from app.core.security import PasswordService, SessionTokenService
from app.repositories.settings import SettingsRepository


class SetupService:
    def __init__(self, session: Session, passwords: PasswordService) -> None:
        self._session = session
        self._passwords = passwords
        self._settings = SettingsRepository(session)

    def is_configured(self) -> bool:
        return self._settings.get_local_admin() is not None

    def configure(self, master_password: str) -> None:
        if self._settings.get_local_admin(for_update=True) is not None:
            raise AlreadyConfiguredError()
        password_hash = self._passwords.hash(master_password)
        try:
            self._settings.add_local_admin(password_hash)
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise AlreadyConfiguredError() from exc


class SessionService:
    def __init__(
        self,
        session: Session,
        passwords: PasswordService,
        tokens: SessionTokenService,
    ) -> None:
        self._session = session
        self._passwords = passwords
        self._tokens = tokens
        self._settings = SettingsRepository(session)

    def authenticate(self, master_password: str) -> str:
        setting = self._settings.get_local_admin(for_update=True)
        if setting is None:
            raise SetupRequiredError()
        if not self._passwords.verify(setting.master_password_hash, master_password):
            raise InvalidCredentialsError()
        if self._passwords.needs_rehash(setting.master_password_hash):
            setting.master_password_hash = self._passwords.hash(master_password)
            self._session.commit()
        return self._tokens.issue()

