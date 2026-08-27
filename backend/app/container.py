from __future__ import annotations

from functools import cached_property, lru_cache

from redis import Redis
from sqlalchemy.orm import Session, sessionmaker

from app.analysis.client import AnalysisBackend, build_backend
from app.assistant.anthropic_client import AnthropicClient
from app.assistant.client import AIProviderClient, OpenAICompatibleClient
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
from app.models import ProviderType
from app.services.connection_gate import RedisConnectionGate
from app.services.credentials import CredentialVault
from app.services.provider_profiles import ProviderKeyVault
from app.services.ssh_trust import HostKeyCandidateStore, HostKeyProbe, HostKeyTrustService


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
        connection_gate: RedisConnectionGate | None = None,
        host_key_candidate_store: HostKeyCandidateStore | None = None,
        host_key_probe: HostKeyProbe | None = None,
        analysis_client: AnalysisBackend | None = None,
        ai_provider_client: AIProviderClient | None = None,
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
        self._connection_gate = connection_gate
        self._host_key_candidate_store = host_key_candidate_store
        self._host_key_probe = host_key_probe
        self._analysis_client = analysis_client
        self._ai_provider_client = ai_provider_client

    @cached_property
    def session_factory(self) -> sessionmaker[Session]:
        if self._session_factory is not None:
            return self._session_factory
        return create_session_factory(create_database_engine(self.settings))

    @cached_property
    def drivers(self) -> DriverRegistry:
        if self._drivers is not None:
            return self._drivers
        transport_factory = ScrapliTransportFactory()
        return DriverRegistry(
            [
                CiscoIOSXEDriver(transport_factory),
                GenericReadOnlyDriver(
                    ScrapliGenericTransportFactory()
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
    def connection_gate(self) -> RedisConnectionGate:
        if self._connection_gate is not None:
            return self._connection_gate
        return RedisConnectionGate(
            redis_client=Redis.from_url(self.settings.resolved_redis_url()),
            settings=self.settings,
        )

    @cached_property
    def host_key_trust(self) -> HostKeyTrustService:
        store = self._host_key_candidate_store or HostKeyCandidateStore(
            Redis.from_url(self.settings.resolved_redis_url())
        )
        return HostKeyTrustService(store, probe=self._host_key_probe)

    @cached_property
    def credential_vault(self) -> CredentialVault:
        return CredentialVault(EnvelopeCipher(self.key_provider, purpose="credential-profiles"))

    @cached_property
    def provider_key_vault(self) -> ProviderKeyVault:
        return ProviderKeyVault(EnvelopeCipher(self.key_provider, purpose="provider-profiles"))

    @cached_property
    def snapshot_store(self) -> EncryptedSnapshotStore:
        if self._snapshot_store is not None:
            return self._snapshot_store
        return EncryptedSnapshotStore(
            self.settings.snapshot_dir,
            EnvelopeCipher(self.key_provider, purpose="config-snapshots"),
        )

    @cached_property
    def analysis_client(self) -> AnalysisBackend:
        if self._analysis_client is not None:
            return self._analysis_client
        return build_backend(self.settings)

    @cached_property
    def ai_provider_client(self) -> AIProviderClient:
        if self._ai_provider_client is not None:
            return self._ai_provider_client
        return OpenAICompatibleClient()

    @cached_property
    def anthropic_provider_client(self) -> AIProviderClient:
        return AnthropicClient()

    def ai_client_for(self, provider_type: ProviderType) -> AIProviderClient:
        """Pick the adapter that speaks this profile's wire format."""
        if provider_type is ProviderType.ANTHROPIC:
            return self.anthropic_provider_client
        return self.ai_provider_client

    @cached_property
    def session_tokens(self) -> SessionTokenService:
        return SessionTokenService(
            self.key_provider,
            ttl_seconds=self.settings.session_ttl_seconds,
        )


@lru_cache
def get_default_container() -> ApplicationContainer:
    return ApplicationContainer()
