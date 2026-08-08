from __future__ import annotations

import base64
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.container import ApplicationContainer
from app.core.config import Settings
from app.core.security import MasterKeyProvider
from app.drivers import CiscoIOSXEDriver, DriverRegistry, GenericReadOnlyDriver
from app.main import create_app
from app.models import Base, SSHCompatibility
from app.services.ssh_trust import HostKeyCandidateStore, HostKeyMaterial
from tests.fakes import (
    FakeBatfishClient,
    FakeConnectionGate,
    FakeQueue,
    FakeRedis,
    FakeTransportFactory,
)


@pytest.fixture
def fixture_dir() -> Path:
    return Path(__file__).parent / "fixtures" / "cisco_iosxe"


@pytest.fixture
def sanitized_outputs(fixture_dir: Path) -> dict[str, str]:
    return {
        "show version": (fixture_dir / "show_version.txt").read_text(encoding="utf-8"),
        "show interfaces": (fixture_dir / "show_interfaces.txt").read_text(encoding="utf-8"),
        "show cdp neighbors detail": (fixture_dir / "show_cdp_neighbors_detail.txt").read_text(
            encoding="utf-8"
        ),
        "show lldp neighbors detail": (fixture_dir / "show_lldp_neighbors_detail.txt").read_text(
            encoding="utf-8"
        ),
        "show ip route": (fixture_dir / "show_ip_route.txt").read_text(encoding="utf-8"),
        "ping 198.51.100.10 repeat 3 timeout 1": (fixture_dir / "ping.txt").read_text(
            encoding="utf-8"
        ),
        "show running-config": (fixture_dir / "running_config.txt").read_text(encoding="utf-8"),
    }


@pytest.fixture
def engine() -> Iterator[Engine]:
    db_engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(db_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(db_engine)
    yield db_engine
    Base.metadata.drop_all(db_engine)
    db_engine.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def transport_factory(sanitized_outputs: dict[str, str]) -> FakeTransportFactory:
    return FakeTransportFactory(sanitized_outputs)


@pytest.fixture
def fake_queue() -> FakeQueue:
    return FakeQueue()


@pytest.fixture
def fake_connection_gate() -> FakeConnectionGate:
    return FakeConnectionGate()


@pytest.fixture
def fake_batfish() -> FakeBatfishClient:
    return FakeBatfishClient()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    root_key = base64.urlsafe_b64encode(b"k" * 32).decode("ascii")
    return Settings(
        app_env="test",
        database_url=SecretStr("sqlite+pysqlite:///:memory:"),
        redis_url=SecretStr("redis://unused/0"),
        master_key=SecretStr(root_key),
        snapshot_dir=tmp_path / "snapshots",
        session_cookie_secure=False,
        csrf_trusted_origins="http://testserver,http://127.0.0.1",
        ssh_connect_timeout_seconds=7,
        ssh_command_timeout_seconds=41,
        # Exercised in most integration tests; explicitly disabled where the
        # kill switch itself is under test.
        analysis_enabled=True,
    )


@pytest.fixture
def container(
    settings: Settings,
    session_factory: sessionmaker[Session],
    transport_factory: FakeTransportFactory,
    fake_queue: FakeQueue,
    fake_connection_gate: FakeConnectionGate,
    fake_batfish: FakeBatfishClient,
) -> ApplicationContainer:
    key_provider = MasterKeyProvider(
        key_file=settings.master_key_file,
        key_value=settings.master_key,
    )
    cisco = CiscoIOSXEDriver(transport_factory)
    generic = GenericReadOnlyDriver(transport_factory)

    async def host_key_probe(
        _host: str,
        _port: int,
        _mode: SSHCompatibility,
    ) -> HostKeyMaterial:
        return HostKeyMaterial(
            "ssh-ed25519",
            "ssh-ed25519 AAAAfixture",
            "SHA256:fixture-host-key",
        )

    return ApplicationContainer(
        settings=settings,
        session_factory=session_factory,
        drivers=DriverRegistry([cisco, generic]),
        queue=fake_queue,
        key_provider=key_provider,
        connection_gate=fake_connection_gate,  # type: ignore[arg-type]
        host_key_candidate_store=HostKeyCandidateStore(FakeRedis()),
        host_key_probe=host_key_probe,
        analysis_client=fake_batfish,  # type: ignore[arg-type]
    )


@pytest.fixture
def client(container: ApplicationContainer) -> Iterator[TestClient]:
    with TestClient(create_app(container), raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def authenticated_client(client: TestClient) -> TestClient:
    password = "correct horse battery staple"
    response = client.post("/api/setup", json={"master_password": password})
    assert response.status_code == 201
    response = client.post("/api/session", json={"master_password": password})
    assert response.status_code == 200
    return client


@pytest.fixture
def credential_profile(authenticated_client: TestClient) -> dict[str, object]:
    response = authenticated_client.post(
        "/api/credential-profiles",
        json={
            "name": "lab-readonly",
            "username": "lab-user",
            "password": "fixture-password",
            "enable_password": "fixture-enable",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()
