from __future__ import annotations

from datetime import UTC, datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, create_engine, inspect, select
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings


class PostgresMigrationOp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, object | None, object | None]] = []

    def get_bind(self) -> SimpleNamespace:
        return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    def add_column(self, table: str, column: object) -> None:
        self.calls.append(("add_column", table, column, None))

    def create_check_constraint(self, name: str, table: str, condition: str) -> None:
        self.calls.append(("create_check_constraint", name, table, condition))

    def drop_constraint(self, name: str, table: str, type_: str) -> None:
        self.calls.append(("drop_constraint", name, table, type_))

    def drop_column(self, table: str, column: str) -> None:
        self.calls.append(("drop_column", table, column, None))


def test_postgresql_legacy_ssh_migration_manages_named_check_constraint(
    monkeypatch,
) -> None:
    path = Path(__file__).parents[2] / "migrations/versions/20260722_0003_legacy_ssh.py"
    spec = spec_from_file_location("legacy_ssh_migration", path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    operations = PostgresMigrationOp()
    monkeypatch.setattr(migration, "op", operations)

    migration.upgrade()
    migration.downgrade()

    assert operations.calls == [
        ("add_column", "devices", operations.calls[0][2], None),
        (
            "create_check_constraint",
            "ck_devices_ssh_compatibility",
            "devices",
            "ssh_compatibility IN ('modern', 'cisco_legacy', 'cisco_legacy_group1')",
        ),
        ("drop_constraint", "ck_devices_ssh_compatibility", "devices", "check"),
        ("drop_column", "devices", "ssh_compatibility", None),
    ]


def test_migration_chain_upgrade_and_downgrade(tmp_path: Path, monkeypatch) -> None:
    database = tmp_path / "migration.db"
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    root = Path(__file__).parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))

    try:
        command.upgrade(config, "head")
        engine = create_engine(url)
        tables = set(inspect(engine).get_table_names())
        assert {
            "alembic_version",
            "app_settings",
            "credential_profiles",
            "devices",
            "device_ssh_host_keys",
            "device_capabilities",
            "interfaces",
            "neighbors",
            "config_snapshots",
            "jobs",
            "events",
        }.issubset(tables)
        host_key_columns = {
            column["name"] for column in inspect(engine).get_columns("device_ssh_host_keys")
        }
        assert {
            "device_id",
            "algorithm",
            "public_key",
            "fingerprint",
            "confirmed_at",
            "confirmed_by",
        }.issubset(host_key_columns)
        assert any(
            constraint["column_names"] == ["device_id"]
            for constraint in inspect(engine).get_unique_constraints("device_ssh_host_keys")
        )
        engine.dispose()

        command.downgrade(config, "base")
        engine = create_engine(url)
        assert set(inspect(engine).get_table_names()) == {"alembic_version"}
        engine.dispose()
    finally:
        get_settings.cache_clear()


def test_legacy_ssh_migration_defaults_existing_devices_and_rejects_invalid_values(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = tmp_path / "legacy-ssh-migration.db"
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    root = Path(__file__).parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))

    try:
        command.upgrade(config, "20260712_0002")
        engine = create_engine(url)
        metadata = MetaData()
        metadata.reflect(engine)
        now = datetime.now(UTC)
        profile_id = uuid4()
        device_id = uuid4()
        with engine.begin() as connection:
            connection.execute(
                metadata.tables["credential_profiles"].insert(),
                {
                    "id": profile_id.hex,
                    "name": "legacy-ssh-profile",
                    "encrypted_secret": b"encrypted",
                    "secret_version": 1,
                    "has_username": True,
                    "has_password": True,
                    "has_enable_password": False,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            connection.execute(
                metadata.tables["devices"].insert(),
                {
                    "id": device_id.hex,
                    "name": "legacy-ssh-device",
                    "management_address": "192.0.2.22",
                    "port": 22,
                    "vendor": "cisco_iosxe",
                    "status": "unknown",
                    "credential_profile_id": profile_id.hex,
                    "facts": {},
                    "created_at": now,
                    "updated_at": now,
                },
            )
        engine.dispose()

        command.upgrade(config, "head")
        engine = create_engine(url)
        metadata = MetaData()
        metadata.reflect(engine)
        devices = metadata.tables["devices"]
        with engine.connect() as connection:
            assert connection.scalar(
                select(devices.c.ssh_compatibility).where(devices.c.id == device_id.hex)
            ) == "modern"
            with pytest.raises(IntegrityError):
                connection.execute(
                    devices.update()
                    .where(devices.c.id == device_id.hex)
                    .values(ssh_compatibility=None)
                )
            with pytest.raises(IntegrityError):
                connection.execute(
                    devices.update()
                    .where(devices.c.id == device_id.hex)
                    .values(ssh_compatibility="unknown")
                )
        engine.dispose()

        command.downgrade(config, "20260712_0002")
        engine = create_engine(url)
        assert "ssh_compatibility" not in {
            column["name"] for column in inspect(engine).get_columns("devices")
        }
        engine.dispose()
    finally:
        get_settings.cache_clear()
