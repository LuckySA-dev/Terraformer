from pathlib import Path

from app.core.config import Settings


def test_database_password_file_and_connection_limit_alias(
    tmp_path: Path,
    monkeypatch,
) -> None:
    password_file = tmp_path / "postgres.password"
    password_file.write_text("p@ss:/word", encoding="utf-8")
    monkeypatch.setenv("DATABASE_PASSWORD_FILE", str(password_file))
    monkeypatch.setenv("DATABASE_HOST", "db.internal")
    monkeypatch.setenv("DATABASE_USER", "app user")
    monkeypatch.setenv("DEVICE_CONNECTION_LIMIT", "12")

    settings = Settings(_env_file=None)

    assert settings.max_device_connections == 12
    assert settings.ssh_legacy_enabled is False
    assert settings.ssh_group1_enabled is False
    assert settings.ssh_terminal_enabled is True
    assert settings.terminal_pty_timeout_seconds == 10.0
    assert settings.terminal_max_duration_seconds == 3600
    assert settings.resolved_database_url() == (
        "postgresql+psycopg://app+user:p%40ss%3A%2Fword@db.internal:5432/terraformer"
    )
