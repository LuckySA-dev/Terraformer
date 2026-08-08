from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote_plus

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "Network Automation Playground"
    app_env: str = "production"
    app_version: str = "0.1.0"
    log_level: str = "INFO"
    bind_host: str = "127.0.0.1"
    bind_port: int = 8000

    database_url: SecretStr | None = None
    database_host: str = "postgres"
    database_port: int = Field(default=5432, ge=1, le=65535)
    database_name: str = "terraformer"
    database_user: str = "terraformer"
    database_password: SecretStr | None = None
    database_password_file: Path | None = Path("/run/secrets/terraformer_postgres_password")

    redis_url: SecretStr = SecretStr("redis://redis:6379/0")
    rq_queue_name: str = "network-read"
    require_worker_for_readiness: bool = False

    master_key: SecretStr | None = None
    master_key_file: Path = Path("/run/secrets/terraformer_master_key")
    snapshot_dir: Path = Path("/data/snapshots")

    session_cookie_name: str = "terraformer_session"
    session_cookie_secure: bool = False
    session_cookie_samesite: Literal["strict", "lax", "none"] = "strict"
    session_ttl_seconds: int = Field(default=28_800, ge=300, le=604_800)
    csrf_trusted_origins: str = "http://127.0.0.1,http://localhost"

    ssh_connect_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    ssh_command_timeout_seconds: float = Field(default=30.0, gt=0, le=600)
    ssh_legacy_enabled: bool = False
    ssh_group1_enabled: bool = False
    ssh_very_old_enabled: bool = False
    ssh_terminal_enabled: bool = True

    # Read-only Batfish configuration analysis. Off by default: it requires an
    # extra container, and the documented resource floor assumes it is absent.
    analysis_enabled: bool = False
    batfish_host: str = "batfish"
    batfish_port: int = Field(default=9996, ge=1, le=65_535)
    analysis_query_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    analysis_parse_timeout_seconds: float = Field(default=600.0, gt=0, le=3600)
    # Enforced bounds that protect the host. They are not a claim that the
    # feature has been shown to work at this scale — see the design spec §8.4.
    analysis_max_devices: int = Field(default=200, ge=1, le=1000)
    analysis_max_findings: int = Field(default=1000, ge=1, le=100_000)
    analysis_retained_snapshots: int = Field(default=10, ge=1, le=100)

    terminal_pty_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    terminal_max_duration_seconds: int = Field(default=3600, ge=60, le=86400)
    max_device_connections: int = Field(
        default=10,
        ge=1,
        le=100,
        validation_alias=AliasChoices("DEVICE_CONNECTION_LIMIT", "MAX_DEVICE_CONNECTIONS"),
    )
    connection_test_rate_limit: int = Field(default=5, ge=1, le=100)
    terminal_open_rate_limit: int = Field(default=5, ge=1, le=100)
    connection_rate_window_seconds: int = Field(default=60, ge=1, le=3600)
    authentication_failure_limit: int = Field(default=3, ge=1, le=20)
    authentication_failure_window_seconds: int = Field(default=60, ge=1, le=3600)
    authentication_cooldown_seconds: int = Field(default=60, ge=1, le=3600)
    max_connections_per_device: int = Field(default=3, ge=1, le=100)
    max_terminal_sessions: int = Field(default=3, ge=1, le=20)
    max_terminal_sessions_per_device: int = Field(default=3, ge=1, le=20)
    connection_permit_ttl_seconds: int = Field(default=3900, ge=60, le=86_700)

    def trusted_origins(self) -> frozenset[str]:
        return frozenset(
            item.strip().rstrip("/")
            for item in self.csrf_trusted_origins.split(",")
            if item.strip()
        )

    @model_validator(mode="after")
    def validate_runtime_security(self) -> Settings:
        if self.session_cookie_samesite == "none" and not self.session_cookie_secure:
            raise ValueError("SameSite=None requires SESSION_COOKIE_SECURE=true")
        if self.app_env.lower() == "production" and not self.session_cookie_secure:
            # Local HTTP is supported; SameSite and loopback binding remain in force.
            pass
        minimum_permit_ttl = (
            self.ssh_connect_timeout_seconds
            + self.terminal_pty_timeout_seconds
            + self.terminal_max_duration_seconds
        )
        if self.connection_permit_ttl_seconds < minimum_permit_ttl:
            raise ValueError(
                "CONNECTION_PERMIT_TTL_SECONDS must cover SSH connect, terminal PTY, "
                "and maximum terminal duration timeouts"
            )
        return self

    def resolved_database_url(self) -> str:
        if self.database_url is not None:
            return self.database_url.get_secret_value()
        password = self._read_database_password()
        user = quote_plus(self.database_user)
        encoded_password = quote_plus(password)
        database = quote_plus(self.database_name)
        return (
            f"postgresql+psycopg://{user}:{encoded_password}@"
            f"{self.database_host}:{self.database_port}/{database}"
        )

    def resolved_redis_url(self) -> str:
        return self.redis_url.get_secret_value()

    def _read_database_password(self) -> str:
        if self.database_password is not None:
            return self.database_password.get_secret_value()
        path = self.database_password_file
        if path is None:
            raise ValueError("DATABASE_PASSWORD or DATABASE_PASSWORD_FILE is required")
        try:
            password = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ValueError(f"Unable to read database password file: {path}") from exc
        if not password:
            raise ValueError("Database password file is empty")
        return password


@lru_cache
def get_settings() -> Settings:
    return Settings()
