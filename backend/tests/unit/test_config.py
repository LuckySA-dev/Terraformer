from pathlib import Path

import pytest
from pydantic import ValidationError

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


def test_connection_gate_defaults_and_environment(monkeypatch) -> None:
    defaults = Settings(_env_file=None)
    assert defaults.connection_test_rate_limit == 5
    assert defaults.terminal_open_rate_limit == 5
    assert defaults.connection_rate_window_seconds == 60
    assert defaults.authentication_failure_limit == 3
    assert defaults.authentication_failure_window_seconds == 60
    assert defaults.authentication_cooldown_seconds == 60
    assert defaults.max_connections_per_device == 3
    assert defaults.max_terminal_sessions == 3
    assert defaults.max_terminal_sessions_per_device == 3
    assert defaults.connection_permit_ttl_seconds == 3_900

    values = {
        "CONNECTION_TEST_RATE_LIMIT": "7",
        "TERMINAL_OPEN_RATE_LIMIT": "8",
        "CONNECTION_RATE_WINDOW_SECONDS": "70",
        "AUTHENTICATION_FAILURE_LIMIT": "4",
        "AUTHENTICATION_FAILURE_WINDOW_SECONDS": "80",
        "AUTHENTICATION_COOLDOWN_SECONDS": "90",
        "MAX_CONNECTIONS_PER_DEVICE": "5",
        "MAX_TERMINAL_SESSIONS": "6",
        "MAX_TERMINAL_SESSIONS_PER_DEVICE": "7",
        "CONNECTION_PERMIT_TTL_SECONDS": "4_000",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    configured = Settings(_env_file=None)
    assert configured.connection_test_rate_limit == 7
    assert configured.terminal_open_rate_limit == 8
    assert configured.connection_rate_window_seconds == 70
    assert configured.authentication_failure_limit == 4
    assert configured.authentication_failure_window_seconds == 80
    assert configured.authentication_cooldown_seconds == 90
    assert configured.max_connections_per_device == 5
    assert configured.max_terminal_sessions == 6
    assert configured.max_terminal_sessions_per_device == 7
    assert configured.connection_permit_ttl_seconds == 4_000


def test_max_device_connections_accepts_the_documented_environment_name(monkeypatch) -> None:
    monkeypatch.delenv("DEVICE_CONNECTION_LIMIT", raising=False)
    monkeypatch.setenv("MAX_DEVICE_CONNECTIONS", "9")

    assert Settings(_env_file=None).max_device_connections == 9


def test_connection_gate_settings_are_exposed_to_both_backend_services() -> None:
    root = Path(__file__).parents[3]
    environment = (root / ".env.example").read_text(encoding="utf-8")
    compose = (root / "deploy" / "compose.yml").read_text(encoding="utf-8")
    for name in (
        "CONNECTION_TEST_RATE_LIMIT",
        "TERMINAL_OPEN_RATE_LIMIT",
        "CONNECTION_RATE_WINDOW_SECONDS",
        "MAX_DEVICE_CONNECTIONS",
        "AUTHENTICATION_FAILURE_LIMIT",
        "AUTHENTICATION_FAILURE_WINDOW_SECONDS",
        "AUTHENTICATION_COOLDOWN_SECONDS",
        "MAX_CONNECTIONS_PER_DEVICE",
        "MAX_TERMINAL_SESSIONS",
        "MAX_TERMINAL_SESSIONS_PER_DEVICE",
        "CONNECTION_PERMIT_TTL_SECONDS",
    ):
        assert name in environment
        assert name in compose


def test_connection_permit_ttl_accepts_the_full_terminal_boundary() -> None:
    settings = Settings(
        _env_file=None,
        ssh_connect_timeout_seconds=11,
        terminal_pty_timeout_seconds=12,
        terminal_max_duration_seconds=100,
        connection_permit_ttl_seconds=123,
    )

    assert settings.connection_permit_ttl_seconds == 123


def test_connection_permit_ttl_rejects_one_second_below_full_terminal_boundary() -> None:
    with pytest.raises(ValidationError, match="CONNECTION_PERMIT_TTL_SECONDS"):
        Settings(
            _env_file=None,
            ssh_connect_timeout_seconds=11,
            terminal_pty_timeout_seconds=12,
            terminal_max_duration_seconds=100,
            connection_permit_ttl_seconds=122,
        )
