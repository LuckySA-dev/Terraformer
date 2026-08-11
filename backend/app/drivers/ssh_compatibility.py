from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.core.errors import ConfigurationError
from app.models import SSHCompatibility

# Increment this version whenever the approved algorithm set changes.
# Version 2: added very_old_ssh mode (ssh-dss, 3des-cbc, hmac-md5/hmac-md5-96).
# Version 3: added RequiredRSASize to the legacy modes.
SSH_COMPATIBILITY_POLICY_VERSION = 2

# ---------------------------------------------------------------------------
# Approved algorithm sets — all additive ('+' prefix), never replacement.
# ---------------------------------------------------------------------------

# OpenSSH 9.1 refuses RSA host keys below 1024 bits regardless of which
# algorithms are enabled, so no KexAlgorithms/HostKeyAlgorithms combination can
# reach a Catalyst 2960/2960-X or ISR 1941 that still presents its original
# 512- or 768-bit host key ("Bad server host key: Invalid key length"). 768 is
# the lowest value OpenSSH accepts here.
#
# This is a key-size floor, not an algorithm list, so it carries no '+' prefix
# and is deliberately excluded from the additive-only invariant.
_LEGACY_MIN_RSA_BITS = "RequiredRSASize=768"

# Option keys whose values must stay additive ('+'), so enabling a legacy
# device never removes a modern algorithm from the client's defaults.
ALGORITHM_OPTION_KEYS = ("KexAlgorithms", "HostKeyAlgorithms", "Ciphers", "MACs")

# Modes 1 + 2: shared base (no group1-sha1, no DSA, no 3DES, no MD5).
_LEGACY_OPENSSH_OPTIONS = (
    "KexAlgorithms=+diffie-hellman-group14-sha1,diffie-hellman-group-exchange-sha1",
    "HostKeyAlgorithms=+ssh-rsa",
    "Ciphers=+aes256-cbc,aes192-cbc,aes128-cbc",
    "MACs=+hmac-sha1,hmac-sha1-96",
    _LEGACY_MIN_RSA_BITS,
)
_LEGACY_ASYNCSSH_KEX = "+diffie-hellman-group14-sha1,diffie-hellman-group-exchange-sha1"

# Mode 3 (group1) additions on top of the legacy base.
_GROUP1_KEX_SUFFIX = ",diffie-hellman-group1-sha1"

# Mode 4 (very_old_ssh) additions on top of the group1 set.
# KEX: no new entries — group1-sha1 is already the most permissive needed.
# HostKey: add ssh-dss (DSA, legacy Cisco/Fortinet).
# Cipher: add 3des-cbc (after AES-CBC set).
# MACs: add hmac-md5 and hmac-md5-96 (after hmac-sha1-96).
_VERY_OLD_EXTRA_HOST_KEY = ",ssh-dss"
_VERY_OLD_EXTRA_CIPHER = ",3des-cbc"
_VERY_OLD_EXTRA_MAC = ",hmac-md5,hmac-md5-96"


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

    group1 = mode in (SSHCompatibility.CISCO_LEGACY_GROUP1, SSHCompatibility.VERY_OLD_SSH)
    # Values only (no 'KEY=' prefix) used for asyncssh fields and openssh assembly.
    kex_value = _LEGACY_ASYNCSSH_KEX + (_GROUP1_KEX_SUFFIX if group1 else "")
    asyncssh_host_key = "+ssh-rsa"
    asyncssh_cipher = "+aes256-cbc,aes192-cbc,aes128-cbc"
    asyncssh_mac = "+hmac-sha1,hmac-sha1-96"

    if mode is SSHCompatibility.VERY_OLD_SSH:
        asyncssh_host_key = "+ssh-rsa" + _VERY_OLD_EXTRA_HOST_KEY
        asyncssh_cipher = "+aes256-cbc,aes192-cbc,aes128-cbc" + _VERY_OLD_EXTRA_CIPHER
        asyncssh_mac = "+hmac-sha1,hmac-sha1-96" + _VERY_OLD_EXTRA_MAC

    return SSHCompatibilityPolicy(
        mode,
        SSH_COMPATIBILITY_POLICY_VERSION,
        (
            f"KexAlgorithms={kex_value}",
            f"HostKeyAlgorithms={asyncssh_host_key}",
            f"Ciphers={asyncssh_cipher}",
            f"MACs={asyncssh_mac}",
            _LEGACY_MIN_RSA_BITS,
        ),
        kex_value,
        asyncssh_host_key,
        asyncssh_cipher,
        asyncssh_mac,
    )



def enforce_compatibility_policy(
    mode: SSHCompatibility,
    settings: Settings,
    *,
    group1_risk_acknowledged: bool,
    very_old_risk_acknowledged: bool = False,
) -> None:
    """Raise ConfigurationError if the requested mode is not authorized.

    All checks run before any network attempt.  No automatic downgrade occurs.
    """
    if mode is SSHCompatibility.CISCO_LEGACY and not settings.ssh_legacy_enabled:
        raise ConfigurationError("Legacy SSH compatibility is disabled")

    if mode is SSHCompatibility.CISCO_LEGACY_GROUP1:
        if not settings.ssh_legacy_enabled:
            raise ConfigurationError("Legacy SSH compatibility is disabled")
        if not settings.ssh_group1_enabled:
            raise ConfigurationError("Group1 SSH compatibility is disabled")
        if not group1_risk_acknowledged:
            raise ConfigurationError("Group1 SSH compatibility requires acknowledgment")

    if mode is SSHCompatibility.VERY_OLD_SSH:
        if not settings.ssh_legacy_enabled:
            raise ConfigurationError(
                "Very old SSHv2 requires SSH_LEGACY_ENABLED to be true"
            )
        if not settings.ssh_group1_enabled:
            raise ConfigurationError(
                "Very old SSHv2 requires SSH_GROUP1_ENABLED to be true"
            )
        if not settings.ssh_very_old_enabled:
            raise ConfigurationError(
                "Very old SSHv2 compatibility is disabled (SSH_VERY_OLD_ENABLED)"
            )
        if not very_old_risk_acknowledged:
            raise ConfigurationError(
                "Very old SSHv2 compatibility requires per-request risk acknowledgment"
            )
