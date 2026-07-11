from __future__ import annotations

from functools import cached_property, lru_cache

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.database import create_database_engine, create_session_factory
from app.core.security import (
    EnvelopeCipher,
    MasterKeyProvider,
    PasswordService,
    SessionTokenService,
)
from app.core.storage import EncryptedSnapshotStore
from app.drivers import CiscoIOSXEDriver, DriverRegistry, GenericReadOnlyDriver
from app.drivers.transport import ScrapliGenericTransportFactory, ScrapliTransportFactory
from app.jobs.queue import JobQueue, RQJobQueue
from app.services.credentials import CredentialVault


class ApplicationContainer:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        session_factory: sessionmaker[Session] | None = None,
        drivers: DriverRegistry | None = None,
        queue: JobQueue | None = None,
        key_provider: MasterKeyProvider | None = None,
        snapshot_store: EncryptedSnapshotStore | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._session_factory = session_factory
        self._drivers = drivers
        self._queue = queue
        self.key_provider = key_provider or MasterKeyProvider(
            key_file=self.settings.master_key_file,
            key_value=self.settings.master_key,
        )
        self.passwords = PasswordService()
        self._snapshot_store = snapshot_store

    @cached_property
    def session_factory(self) -> sessionmaker[Session]:
        if self._session_factory is not None:
            return self._session_factory
        return create_session_factory(create_database_engine(self.settings))

    @cached_property
    def drivers(self) -> DriverRegistry:
        if self._drivers is not None:
            return self._drivers
        transport_factory = ScrapliTransportFactory(
            strict_host_key=self.settings.ssh_strict_host_key
        )
        return DriverRegistry(
            [
                CiscoIOSXEDriver(transport_factory),
                GenericReadOnlyDriver(
                    ScrapliGenericTransportFactory(
                        strict_host_key=self.settings.ssh_strict_host_key
                    )
                ),
            ]
        )

    @cached_property
    def queue(self) -> JobQueue:
        if self._queue is not None:
            return self._queue
        return RQJobQueue(
            redis_url=self.settings.resolved_redis_url(),
            queue_name=self.settings.rq_queue_name,
        )

    @cached_property
    def credential_vault(self) -> CredentialVault:
        return CredentialVault(EnvelopeCipher(self.key_provider, purpose="credential-profiles"))

    @cached_property
    def snapshot_store(self) -> EncryptedSnapshotStore:
        if self._snapshot_store is not None:
            return self._snapshot_store
        return EncryptedSnapshotStore(
            self.settings.snapshot_dir,
            EnvelopeCipher(self.key_provider, purpose="config-snapshots"),
        )

    @cached_property
    def session_tokens(self) -> SessionTokenService:
        return SessionTokenService(
            self.key_provider,
            ttl_seconds=self.settings.session_ttl_seconds,
        )


@lru_cache
def get_default_container() -> ApplicationContainer:
    return ApplicationContainer()
