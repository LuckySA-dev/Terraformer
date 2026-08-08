from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.core.config import Settings
from app.core.errors import ConfigurationError
from app.drivers.ssh_compatibility import (
    ALGORITHM_OPTION_KEYS,
    SSH_COMPATIBILITY_POLICY_VERSION,
    SSHCompatibility,
    compatibility_policy,
    enforce_compatibility_policy,
)


def test_policy_version_is_3() -> None:
    assert SSH_COMPATIBILITY_POLICY_VERSION == 3


def test_approved_policy_is_versioned_and_additive() -> None:
    assert SSH_COMPATIBILITY_POLICY_VERSION == 3
    assert compatibility_policy(SSHCompatibility.MODERN).openssh_options == ()
    assert compatibility_policy(SSHCompatibility.CISCO_LEGACY).openssh_options == (
        "KexAlgorithms=+diffie-hellman-group14-sha1,diffie-hellman-group-exchange-sha1",
        "HostKeyAlgorithms=+ssh-rsa",
        "Ciphers=+aes256-cbc,aes192-cbc,aes128-cbc",
        "MACs=+hmac-sha1,hmac-sha1-96",
        "RequiredRSASize=768",
    )
    assert "diffie-hellman-group1-sha1" not in " ".join(
        compatibility_policy(SSHCompatibility.CISCO_LEGACY).openssh_options
    )
    group1_policy = compatibility_policy(SSHCompatibility.CISCO_LEGACY_GROUP1)
    assert group1_policy.version == 3
    assert group1_policy.openssh_options == (
        "KexAlgorithms=+diffie-hellman-group14-sha1,"
        "diffie-hellman-group-exchange-sha1,diffie-hellman-group1-sha1",
        "HostKeyAlgorithms=+ssh-rsa",
        "Ciphers=+aes256-cbc,aes192-cbc,aes128-cbc",
        "MACs=+hmac-sha1,hmac-sha1-96",
        "RequiredRSASize=768",
    )
    assert group1_policy.asyncssh_kex_algs is not None
    assert group1_policy.asyncssh_kex_algs.endswith(",diffie-hellman-group1-sha1")


def test_modern_mode_never_lowers_the_rsa_key_floor() -> None:
    """The relaxed key-size floor is a per-device exception, never a default."""
    assert compatibility_policy(SSHCompatibility.MODERN).openssh_options == ()


@pytest.mark.parametrize(
    "mode",
    [
        SSHCompatibility.CISCO_LEGACY,
        SSHCompatibility.CISCO_LEGACY_GROUP1,
        SSHCompatibility.VERY_OLD_SSH,
    ],
)
def test_legacy_modes_accept_undersized_rsa_host_keys(mode: SSHCompatibility) -> None:
    """Catalyst 2960/2960-X and ISR 1941 ship 512/768-bit RSA host keys.

    OpenSSH >= 9.1 rejects those before authentication no matter which
    algorithms are enabled, so the floor has to be lowered explicitly.
    """
    assert "RequiredRSASize=768" in compatibility_policy(mode).openssh_options


@pytest.mark.parametrize("prohibited", ["ssh-dss", "hmac-md5", "3des-cbc", "arcfour"])
@pytest.mark.parametrize(
    "mode",
    [
        SSHCompatibility.MODERN,
        SSHCompatibility.CISCO_LEGACY,
        SSHCompatibility.CISCO_LEGACY_GROUP1,
    ],
)
def test_policy_excludes_prohibited_algorithms_from_standard_modes(
    mode: SSHCompatibility, prohibited: str
) -> None:
    """Modes 1-3 must never include DSA, 3DES, MD5, or RC4."""
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


def test_arcfour_rc4_absent_from_all_modes() -> None:
    """RC4/arcfour must be absent from every mode including very_old_ssh."""
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
        assert "arcfour" not in rendered, f"arcfour found in {mode}"
        assert "rc4" not in rendered.lower(), f"RC4 found in {mode}"


def test_policy_is_immutable() -> None:
    policy = compatibility_policy(SSHCompatibility.CISCO_LEGACY)
    with pytest.raises(FrozenInstanceError):
        policy.version = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# very_old_ssh exact algorithm content tests
# ---------------------------------------------------------------------------


def test_very_old_openssh_options_are_additive() -> None:
    """Algorithm lists must extend the client defaults, never replace them.

    Scoped to the algorithm options: RequiredRSASize is a numeric key-size
    floor, not a list, so '+' does not apply to it.
    """
    policy = compatibility_policy(SSHCompatibility.VERY_OLD_SSH)
    algorithm_options = [
        opt for opt in policy.openssh_options if opt.split("=", 1)[0] in ALGORITHM_OPTION_KEYS
    ]
    assert len(algorithm_options) == len(ALGORITHM_OPTION_KEYS)
    for opt in algorithm_options:
        _key, value = opt.split("=", 1)
        assert value.startswith("+"), f"Option is not additive (missing '+'): {opt}"


def test_very_old_openssh_contains_group1_kex() -> None:
    policy = compatibility_policy(SSHCompatibility.VERY_OLD_SSH)
    kex = next(o for o in policy.openssh_options if o.startswith("KexAlgorithms="))
    assert "diffie-hellman-group1-sha1" in kex


def test_very_old_openssh_contains_dss_host_key() -> None:
    policy = compatibility_policy(SSHCompatibility.VERY_OLD_SSH)
    hka = next(o for o in policy.openssh_options if o.startswith("HostKeyAlgorithms="))
    assert "ssh-rsa" in hka
    assert "ssh-dss" in hka


def test_very_old_openssh_contains_3des_cipher() -> None:
    policy = compatibility_policy(SSHCompatibility.VERY_OLD_SSH)
    cipher = next(o for o in policy.openssh_options if o.startswith("Ciphers="))
    assert "3des-cbc" in cipher
    assert "aes256-cbc" in cipher  # modern AES must still come first


def test_very_old_openssh_contains_md5_macs() -> None:
    policy = compatibility_policy(SSHCompatibility.VERY_OLD_SSH)
    mac = next(o for o in policy.openssh_options if o.startswith("MACs="))
    assert "hmac-sha1" in mac
    assert "hmac-md5" in mac
    assert "hmac-md5-96" in mac


def test_very_old_asyncssh_kex_includes_group1() -> None:
    policy = compatibility_policy(SSHCompatibility.VERY_OLD_SSH)
    assert policy.asyncssh_kex_algs is not None
    assert "diffie-hellman-group1-sha1" in policy.asyncssh_kex_algs


def test_very_old_asyncssh_server_host_key_includes_dss() -> None:
    policy = compatibility_policy(SSHCompatibility.VERY_OLD_SSH)
    assert policy.asyncssh_server_host_key_algs is not None
    assert "ssh-rsa" in policy.asyncssh_server_host_key_algs
    assert "ssh-dss" in policy.asyncssh_server_host_key_algs


def test_very_old_asyncssh_encryption_includes_3des() -> None:
    policy = compatibility_policy(SSHCompatibility.VERY_OLD_SSH)
    assert policy.asyncssh_encryption_algs is not None
    assert "3des-cbc" in policy.asyncssh_encryption_algs
    assert "aes256-cbc" in policy.asyncssh_encryption_algs


def test_very_old_asyncssh_mac_includes_md5() -> None:
    policy = compatibility_policy(SSHCompatibility.VERY_OLD_SSH)
    assert policy.asyncssh_mac_algs is not None
    assert "hmac-md5" in policy.asyncssh_mac_algs
    assert "hmac-md5-96" in policy.asyncssh_mac_algs


def test_modern_has_no_legacy_overrides() -> None:
    policy = compatibility_policy(SSHCompatibility.MODERN)
    assert policy.openssh_options == ()
    assert policy.asyncssh_kex_algs is None
    assert policy.asyncssh_server_host_key_algs is None
    assert policy.asyncssh_encryption_algs is None
    assert policy.asyncssh_mac_algs is None


def test_no_automatic_fallback() -> None:
    """Modern policy must never produce legacy algorithm options."""
    policy = compatibility_policy(SSHCompatibility.MODERN)
    assert policy.openssh_options == ()
    # Calling modern after very_old must still return clean modern policy.
    _ = compatibility_policy(SSHCompatibility.VERY_OLD_SSH)
    policy2 = compatibility_policy(SSHCompatibility.MODERN)
    assert policy2.openssh_options == ()


def test_legacy_excludes_dsa_3des_md5() -> None:
    """cisco_legacy and cisco_legacy_group1 must never include DSA, 3DES, or MD5."""
    for mode in (SSHCompatibility.CISCO_LEGACY, SSHCompatibility.CISCO_LEGACY_GROUP1):
        policy = compatibility_policy(mode)
        rendered = " ".join(
            opt
            for opt in (
                *policy.openssh_options,
                policy.asyncssh_kex_algs,
                policy.asyncssh_server_host_key_algs,
                policy.asyncssh_encryption_algs,
                policy.asyncssh_mac_algs,
            )
            if opt is not None
        )
        assert "ssh-dss" not in rendered, f"ssh-dss found in {mode}"
        assert "3des-cbc" not in rendered, f"3des-cbc found in {mode}"
        assert "hmac-md5" not in rendered, f"hmac-md5 found in {mode}"


def test_group1_absent_from_legacy_base() -> None:
    policy = compatibility_policy(SSHCompatibility.CISCO_LEGACY)
    rendered = " ".join(opt for opt in policy.openssh_options if opt is not None)
    assert "diffie-hellman-group1-sha1" not in rendered
    if policy.asyncssh_kex_algs is not None:
        assert "diffie-hellman-group1-sha1" not in policy.asyncssh_kex_algs


def test_policy_version_consistent_across_non_modern_modes() -> None:
    """All non-modern modes must carry the current policy version."""
    for mode in SSHCompatibility:
        if mode is SSHCompatibility.MODERN:
            continue
        assert compatibility_policy(mode).version == SSH_COMPATIBILITY_POLICY_VERSION


# ---------------------------------------------------------------------------
# Kill-switch and acknowledgment enforcement tests
# ---------------------------------------------------------------------------


def test_very_old_server_switch_defaults_false() -> None:
    settings = Settings(_env_file=None)
    assert settings.ssh_very_old_enabled is False


def test_very_old_missing_ack_fails() -> None:
    all_enabled = Settings(
        _env_file=None,
        ssh_legacy_enabled=True,
        ssh_group1_enabled=True,
        ssh_very_old_enabled=True,
    )
    with pytest.raises(ConfigurationError):
        enforce_compatibility_policy(
            SSHCompatibility.VERY_OLD_SSH,
            all_enabled,
            group1_risk_acknowledged=True,
            very_old_risk_acknowledged=False,
        )


def test_very_old_missing_legacy_switch_fails() -> None:
    with pytest.raises(ConfigurationError):
        enforce_compatibility_policy(
            SSHCompatibility.VERY_OLD_SSH,
            Settings(
                _env_file=None,
                ssh_legacy_enabled=False,
                ssh_group1_enabled=True,
                ssh_very_old_enabled=True,
            ),
            group1_risk_acknowledged=True,
            very_old_risk_acknowledged=True,
        )


def test_very_old_missing_group1_switch_fails() -> None:
    with pytest.raises(ConfigurationError):
        enforce_compatibility_policy(
            SSHCompatibility.VERY_OLD_SSH,
            Settings(
                _env_file=None,
                ssh_legacy_enabled=True,
                ssh_group1_enabled=False,
                ssh_very_old_enabled=True,
            ),
            group1_risk_acknowledged=True,
            very_old_risk_acknowledged=True,
        )


def test_very_old_missing_very_old_switch_fails() -> None:
    with pytest.raises(ConfigurationError):
        enforce_compatibility_policy(
            SSHCompatibility.VERY_OLD_SSH,
            Settings(
                _env_file=None,
                ssh_legacy_enabled=True,
                ssh_group1_enabled=True,
                ssh_very_old_enabled=False,
            ),
            group1_risk_acknowledged=True,
            very_old_risk_acknowledged=True,
        )


def test_very_old_all_switches_and_ack_succeeds() -> None:
    # Must not raise.
    enforce_compatibility_policy(
        SSHCompatibility.VERY_OLD_SSH,
        Settings(
            _env_file=None,
            ssh_legacy_enabled=True,
            ssh_group1_enabled=True,
            ssh_very_old_enabled=True,
        ),
        group1_risk_acknowledged=True,
        very_old_risk_acknowledged=True,
    )


def test_group1_requires_server_switch_and_request_acknowledgment() -> None:
    """Existing group1 enforcement still works with new signature."""
    disabled = Settings(_env_file=None)

    with pytest.raises(ConfigurationError):
        enforce_compatibility_policy(
            SSHCompatibility.CISCO_LEGACY,
            disabled,
            group1_risk_acknowledged=False,
            very_old_risk_acknowledged=False,
        )

    legacy_enabled = Settings(_env_file=None, ssh_legacy_enabled=True)
    enforce_compatibility_policy(
        SSHCompatibility.CISCO_LEGACY,
        legacy_enabled,
        group1_risk_acknowledged=False,
        very_old_risk_acknowledged=False,
    )

    with pytest.raises(ConfigurationError):
        enforce_compatibility_policy(
            SSHCompatibility.CISCO_LEGACY_GROUP1,
            Settings(_env_file=None, ssh_legacy_enabled=True, ssh_group1_enabled=True),
            group1_risk_acknowledged=False,
            very_old_risk_acknowledged=False,
        )

    with pytest.raises(ConfigurationError):
        enforce_compatibility_policy(
            SSHCompatibility.CISCO_LEGACY_GROUP1,
            Settings(_env_file=None, ssh_legacy_enabled=True, ssh_group1_enabled=False),
            group1_risk_acknowledged=True,
            very_old_risk_acknowledged=False,
        )

    enforce_compatibility_policy(
        SSHCompatibility.CISCO_LEGACY_GROUP1,
        Settings(_env_file=None, ssh_legacy_enabled=True, ssh_group1_enabled=True),
        group1_risk_acknowledged=True,
        very_old_risk_acknowledged=False,
    )
