from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.core.config import Settings
from app.core.errors import ConfigurationError
from app.drivers.ssh_compatibility import (
    SSH_COMPATIBILITY_POLICY_VERSION,
    SSHCompatibility,
    compatibility_policy,
    enforce_compatibility_policy,
)


def test_approved_policy_is_versioned_and_additive() -> None:
    assert SSH_COMPATIBILITY_POLICY_VERSION == 1
    assert compatibility_policy(SSHCompatibility.MODERN).openssh_options == ()
    assert compatibility_policy(SSHCompatibility.CISCO_LEGACY).openssh_options == (
        "KexAlgorithms=+diffie-hellman-group14-sha1,diffie-hellman-group-exchange-sha1",
        "HostKeyAlgorithms=+ssh-rsa",
        "Ciphers=+aes256-cbc,aes192-cbc,aes128-cbc",
        "MACs=+hmac-sha1,hmac-sha1-96",
    )
    assert "diffie-hellman-group1-sha1" not in " ".join(
        compatibility_policy(SSHCompatibility.CISCO_LEGACY).openssh_options
    )
    assert compatibility_policy(SSHCompatibility.CISCO_LEGACY_GROUP1).version == 1
    assert compatibility_policy(
        SSHCompatibility.CISCO_LEGACY_GROUP1
    ).asyncssh_kex_algs.endswith(",diffie-hellman-group1-sha1")


@pytest.mark.parametrize("prohibited", ["ssh-dss", "hmac-md5", "3des-cbc", "arcfour"])
def test_policy_excludes_prohibited_algorithms(prohibited: str) -> None:
    for mode in SSHCompatibility:
        policy = compatibility_policy(mode)
        rendered = " ".join(
            option
            for option in (
                *policy.openssh_options,
                policy.asyncssh_kex_algs,
                policy.asyncssh_server_host_key_algs,
                policy.asyncssh_encryption_algs,
                policy.asyncssh_mac_algs,
            )
            if option is not None
        )
        assert prohibited not in rendered


def test_policy_is_immutable() -> None:
    policy = compatibility_policy(SSHCompatibility.CISCO_LEGACY)

    with pytest.raises(FrozenInstanceError):
        policy.version = 2  # type: ignore[misc]


def test_group1_requires_server_switch_and_request_acknowledgment() -> None:
    disabled = Settings(_env_file=None)

    with pytest.raises(ConfigurationError):
        enforce_compatibility_policy(
            SSHCompatibility.CISCO_LEGACY,
            disabled,
            group1_risk_acknowledged=False,
        )

    legacy_enabled = Settings(_env_file=None, ssh_legacy_enabled=True)
    enforce_compatibility_policy(
        SSHCompatibility.CISCO_LEGACY,
        legacy_enabled,
        group1_risk_acknowledged=False,
    )

    with pytest.raises(ConfigurationError):
        enforce_compatibility_policy(
            SSHCompatibility.CISCO_LEGACY_GROUP1,
            Settings(_env_file=None, ssh_legacy_enabled=True, ssh_group1_enabled=True),
            group1_risk_acknowledged=False,
        )

    enforce_compatibility_policy(
        SSHCompatibility.CISCO_LEGACY_GROUP1,
        Settings(_env_file=None, ssh_legacy_enabled=True, ssh_group1_enabled=True),
        group1_risk_acknowledged=True,
    )
