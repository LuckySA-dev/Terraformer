from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.core.errors import ConfigurationError
from app.models import SSHCompatibility

SSH_COMPATIBILITY_POLICY_VERSION = 1

_LEGACY_OPENSSH_OPTIONS = (
    "KexAlgorithms=+diffie-hellman-group14-sha1,diffie-hellman-group-exchange-sha1",
    "HostKeyAlgorithms=+ssh-rsa",
    "Ciphers=+aes256-cbc,aes192-cbc,aes128-cbc",
    "MACs=+hmac-sha1,hmac-sha1-96",
)
_LEGACY_ASYNCSSH_KEX = "+diffie-hellman-group14-sha1,diffie-hellman-group-exchange-sha1"


@dataclass(frozen=True, slots=True)
class SSHCompatibilityPolicy:
    mode: SSHCompatibility
    version: int
    openssh_options: tuple[str, ...]
    asyncssh_kex_algs: str | None
    asyncssh_server_host_key_algs: str | None
    asyncssh_encryption_algs: str | None
    asyncssh_mac_algs: str | None


def compatibility_policy(mode: SSHCompatibility) -> SSHCompatibilityPolicy:
    if mode is SSHCompatibility.MODERN:
        return SSHCompatibilityPolicy(
            mode,
            SSH_COMPATIBILITY_POLICY_VERSION,
            (),
            None,
            None,
            None,
            None,
        )

    group1 = mode is SSHCompatibility.CISCO_LEGACY_GROUP1
    return SSHCompatibilityPolicy(
        mode,
        SSH_COMPATIBILITY_POLICY_VERSION,
        _LEGACY_OPENSSH_OPTIONS
        + (("KexAlgorithms=+diffie-hellman-group1-sha1",) if group1 else ()),
        _LEGACY_ASYNCSSH_KEX + (",diffie-hellman-group1-sha1" if group1 else ""),
        "+ssh-rsa",
        "+aes256-cbc,aes192-cbc,aes128-cbc",
        "+hmac-sha1,hmac-sha1-96",
    )


def enforce_compatibility_policy(
    mode: SSHCompatibility,
    settings: Settings,
    *,
    group1_risk_acknowledged: bool,
) -> None:
    if mode is SSHCompatibility.CISCO_LEGACY and not settings.ssh_legacy_enabled:
        raise ConfigurationError("Legacy SSH compatibility is disabled")
    if mode is SSHCompatibility.CISCO_LEGACY_GROUP1:
        if not settings.ssh_legacy_enabled:
            raise ConfigurationError("Legacy SSH compatibility is disabled")
        if not settings.ssh_group1_enabled:
            raise ConfigurationError("Group1 SSH compatibility is disabled")
        if not group1_risk_acknowledged:
            raise ConfigurationError("Group1 SSH compatibility requires acknowledgment")
