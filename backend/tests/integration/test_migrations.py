from __future__ import annotations

import os
from datetime import UTC, datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, create_engine, inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.config import get_settings

# Every vendor and compatibility value the application may write, paired with
# the length that the column has to accommodate. 'fortinet_fortios' is 16
# characters; the column was originally VARCHAR(11), which SQLite silently
# tolerates and PostgreSQL rejects.
_ALL_VENDORS = ("cisco_iosxe", "fortinet_fortios", "generic")
_ALL_SSH_COMPATIBILITY = ("modern", "cisco_legacy", "cisco_legacy_group1", "very_old_ssh")


def _alembic_config(root: Path) -> Config:
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    return config


def _insert_device(
    connection: object,
    metadata: MetaData,
    *,
    index: int,
    vendor: str,
    compatibility: str,
) -> None:
    now = datetime.now(UTC)
    profile_id = uuid4()
    execute = connection.execute  # type: ignore[attr-defined]
    execute(
        metadata.tables["credential_profiles"].insert(),
        {
            "id": profile_id.hex,
            "name": f"profile-{index}",
            "encrypted_secret": b"encrypted",
            "secret_version": 1,
            "has_username": True,
            "has_password": True,
            "has_enable_password": False,
            "created_at": now,
            "updated_at": now,
        },
    )
    execute(
        metadata.tables["devices"].insert(),
        {
            "id": uuid4().hex,
            "name": f"device-{index}",
            "management_address": f"192.0.2.{index}",
            "port": 22,
            "vendor": vendor,
            "ssh_compatibility": compatibility,
            "status": "unknown",
            "credential_profile_id": profile_id.hex,
            "facts": {},
            "created_at": now,
            "updated_at": now,
        },
    )


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
            "analysis_snapshots",
            "analysis_snapshot_members",
            "analysis_findings",
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


def test_migrations_match_the_orm_models(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`alembic check` must be clean, which nothing verified before.

    Tests build their schema with Base.metadata.create_all(), so the ORM and
    the migration chain could disagree indefinitely without any test noticing.
    """
    database = tmp_path / "drift.db"
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    config = _alembic_config(Path(__file__).parents[2])
    try:
        command.upgrade(config, "head")
        command.check(config)
    finally:
        get_settings.cache_clear()


def test_change_plan_tables_exist_after_upgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "change_plans.db"
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    config = _alembic_config(Path(__file__).parents[2])
    try:
        command.upgrade(config, "head")
    finally:
        get_settings.cache_clear()

    engine = create_engine(url)
    table_names = set(inspect(engine).get_table_names())
    assert "change_plans" in table_names
    assert "change_steps" in table_names


def _assert_every_supported_value_is_writable(url: str) -> None:
    """A migrated database must accept every vendor/compatibility the app writes.

    Regression guard for 20260806_0005: the vendor column was left at
    VARCHAR(11) while 'fortinet_fortios' needs 16, and the pre-0005
    three-value CHECK constraint survived under its type-bound name and
    rejected 'very_old_ssh'.
    """
    engine = create_engine(url)
    metadata = MetaData()
    metadata.reflect(engine)
    devices = metadata.tables["devices"]

    vendor_length = devices.c.vendor.type.length
    assert vendor_length is None or vendor_length >= max(len(v) for v in _ALL_VENDORS)

    index = 10
    with engine.begin() as connection:
        for vendor in _ALL_VENDORS:
            for compatibility in _ALL_SSH_COMPATIBILITY:
                _insert_device(
                    connection,
                    metadata,
                    index=index,
                    vendor=vendor,
                    compatibility=compatibility,
                )
                index += 1

    # The widened column must still reject values outside the enum.
    for column, bad_value in (("vendor", "not_a_vendor"), ("ssh_compatibility", "not_a_mode")):
        with engine.begin() as connection, pytest.raises((IntegrityError, DBAPIError)):
            connection.execute(
                devices.update().where(devices.c.name == "device-10").values({column: bad_value})
            )
    engine.dispose()


def test_migrated_schema_accepts_every_supported_vendor_and_compatibility(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "supported-values.db"
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    try:
        command.upgrade(_alembic_config(Path(__file__).parents[2]), "head")
        _assert_every_supported_value_is_writable(url)
    finally:
        get_settings.cache_clear()


@pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES_URL"),
    reason="Set TEST_POSTGRES_URL to run migrations against a real PostgreSQL server",
)
def test_migration_chain_runs_on_postgresql(monkeypatch: pytest.MonkeyPatch) -> None:
    """SQLite hides the two failure modes this migration exists to fix.

    PostgreSQL enforces VARCHAR length and aborts the whole transaction when a
    DDL statement fails, so only a real server proves the chain applies.
    """
    url = os.environ["TEST_POSTGRES_URL"]
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    config = _alembic_config(Path(__file__).parents[2])
    try:
        engine = create_engine(url)
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        engine.dispose()

        # Reversibility is checked on an empty schema first. Downgrading with
        # data present is a different question: narrowing devices.vendor back to
        # VARCHAR(11) must refuse to truncate a stored 'fortinet_fortios', which
        # is asserted separately below.
        command.upgrade(config, "head")
        command.downgrade(config, "base")
        command.upgrade(config, "head")

        _assert_every_supported_value_is_writable(url)
    finally:
        get_settings.cache_clear()


@pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES_URL"),
    reason="Set TEST_POSTGRES_URL to run migrations against a real PostgreSQL server",
)
def test_downgrade_refuses_to_truncate_a_value_the_old_schema_cannot_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Downgrading past 20260806_0005 with a Fortinet device must fail loudly.

    'fortinet_fortios' is 16 characters and the pre-0005 column is VARCHAR(11).
    Silently truncating it would corrupt the vendor of a registered device, so
    the migration is expected to raise and leave the data alone.
    """
    url = os.environ["TEST_POSTGRES_URL"]
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    config = _alembic_config(Path(__file__).parents[2])
    try:
        engine = create_engine(url)
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        engine.dispose()

        command.upgrade(config, "head")
        engine = create_engine(url)
        metadata = MetaData()
        metadata.reflect(engine)
        with engine.begin() as connection:
            _insert_device(
                connection,
                metadata,
                index=90,
                vendor="fortinet_fortios",
                compatibility="modern",
            )
        engine.dispose()

        with pytest.raises(DBAPIError):
            command.downgrade(config, "20260806_0004")

        # The device must still be intact and readable.
        engine = create_engine(url)
        metadata = MetaData()
        metadata.reflect(engine)
        devices = metadata.tables["devices"]
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    select(devices.c.vendor).where(devices.c.name == "device-90")
                )
                == "fortinet_fortios"
            )
        engine.dispose()
    finally:
        get_settings.cache_clear()


@pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES_URL"),
    reason="Set TEST_POSTGRES_URL to run migrations against a real PostgreSQL server",
)
def test_repair_migration_fixes_a_database_stamped_past_the_broken_migration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A database stamped past 20260806_0005 reaches head with the old columns.

    The original 20260806_0005 aborted the transaction on PostgreSQL, and
    `alembic stamp` is the usual way operators get unstuck. That leaves the
    database recorded at head while devices.vendor is still VARCHAR(11), so
    registering a Fortinet device fails with "value too long". 20260808_0007
    repairs it. Reproduced here by stamping rather than upgrading.
    """
    url = os.environ["TEST_POSTGRES_URL"]
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    config = _alembic_config(Path(__file__).parents[2])
    try:
        engine = create_engine(url)
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        engine.dispose()

        # Reach the revision before the broken one, then skip over it.
        command.upgrade(config, "20260806_0004")
        command.stamp(config, "20260806_0005")
        command.upgrade(config, "20260808_0006")

        engine = create_engine(url)
        vendor_length = next(
            column["type"].length
            for column in inspect(engine).get_columns("devices")
            if column["name"] == "vendor"
        )
        assert vendor_length == 11, "expected the un-widened column this migration repairs"
        engine.dispose()

        command.upgrade(config, "head")

        engine = create_engine(url)
        metadata = MetaData()
        metadata.reflect(engine)
        assert metadata.tables["devices"].c.vendor.type.length >= len("fortinet_fortios")
        with engine.begin() as connection:
            _insert_device(
                connection,
                metadata,
                index=95,
                vendor="fortinet_fortios",
                compatibility="very_old_ssh",
            )
        engine.dispose()

        # Running it again on an already-correct database must be a no-op.
        command.downgrade(config, "20260808_0006")
        command.upgrade(config, "head")
        command.check(config)
    finally:
        get_settings.cache_clear()
