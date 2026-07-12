from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.core.config import get_settings


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
            "device_capabilities",
            "interfaces",
            "neighbors",
            "config_snapshots",
            "jobs",
            "events",
        }.issubset(tables)
        engine.dispose()

        command.downgrade(config, "base")
        engine = create_engine(url)
        assert set(inspect(engine).get_table_names()) == {"alembic_version"}
        engine.dispose()
    finally:
        get_settings.cache_clear()
