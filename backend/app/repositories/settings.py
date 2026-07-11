from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AppSetting

LOCAL_ADMIN_KEY = "local_admin"


class SettingsRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_local_admin(self, *, for_update: bool = False) -> AppSetting | None:
        statement = select(AppSetting).where(AppSetting.singleton_key == LOCAL_ADMIN_KEY)
        if for_update:
            statement = statement.with_for_update()
        return self._session.scalar(statement)

    def add_local_admin(self, password_hash: str) -> AppSetting:
        setting = AppSetting(
            singleton_key=LOCAL_ADMIN_KEY,
            master_password_hash=password_hash,
        )
        self._session.add(setting)
        self._session.flush()
        return setting

