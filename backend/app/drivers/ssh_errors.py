from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from scrapli.exceptions import (
    ScrapliAuthenticationFailed,
    ScrapliModuleNotFound,
    ScrapliTimeout,
    ScrapliTransportPluginError,
    ScrapliValueError,
)

from app.core.errors import (
    AppError,
    ConfigurationError,
    DriverAuthenticationError,
    DriverCommandRejectedError,
    DriverConnectionError,
    DriverHostKeyVerificationError,
    DriverSSHNegotiationError,
    DriverTerminalIOError,
    DriverTerminalPTYError,
    DriverTimeoutError,
)
from app.drivers.ssh_compatibility import SSHCompatibilityPolicy

_PASSWORD_ONLY_OPTIONS = (
    "IdentityAgent=none",
    "IdentitiesOnly=yes",
    "PreferredAuthentications=password",
    "PasswordAuthentication=yes",
    "PubkeyAuthentication=no",
    "KbdInteractiveAuthentication=no",
    "HostbasedAuthentication=no",
    "GSSAPIAuthentication=no",
    "NumberOfPasswordPrompts=1",
)
_NEGOTIATION_MARKERS = (
    "no matching key exchange",
    "no matching host key",
    "no matching cipher",
    "no matching mac",
)
_HOST_KEY_MARKERS = (
    "host key verification failed",
    "remote host identification has changed",
    "host key is known for",
    "host key is unknown",
    "host key has changed",
    "host key is not known",
    "host key is not trusted",
)
_TIMEOUT_MARKERS = ("timed out connecting", "operation timed out", "connection timed out")
_TCP_MARKERS = (
    "no route to host",
    "could not resolve address",
    "could not resolve hostname",
    "connection refused",
    "network is unreachable",
)
_CONFIGURATION_MARKERS = (
    "bad ssh configuration",
    "bad configuration option",
)


class ConnectionPhase(StrEnum):
    TCP = "tcp_connection"
    NEGOTIATION = "ssh_negotiation"
    HOST_KEY = "host_key_verification"
    AUTHENTICATION = "authentication"
    PTY = "pty_creation"
    TERMINAL_IO = "terminal_io"


@dataclass(frozen=True, slots=True)
class SanitizedSSHFailure:
    code: str
    phase: ConnectionPhase
    retryable: bool
    recommended_action: str | None


FAILURES = {
    "device_connection_failed": SanitizedSSHFailure(
        "device_connection_failed",
        ConnectionPhase.TCP,
        True,
        "Verify device reachability and that SSH is listening on the configured port.",
    ),
    "device_timeout": SanitizedSSHFailure(
        "device_timeout",
        ConnectionPhase.TCP,
        True,
        "Retry after verifying device reachability and network latency.",
    ),
    "device_authentication_failed": SanitizedSSHFailure(
        "device_authentication_failed",
        ConnectionPhase.AUTHENTICATION,
        False,
        "Verify the selected credential profile and device login policy.",
    ),
    "device_host_key_verification_failed": SanitizedSSHFailure(
        "device_host_key_verification_failed",
        ConnectionPhase.HOST_KEY,
        False,
        "Verify the saved SSH host key for this device.",
    ),
    "legacy_ssh_negotiation_failed": SanitizedSSHFailure(
        "legacy_ssh_negotiation_failed",
        ConnectionPhase.NEGOTIATION,
        False,
        "Verify the saved compatibility mode for this device.",
    ),
    "terminal_pty_rejected": SanitizedSSHFailure(
        "terminal_pty_rejected",
        ConnectionPhase.PTY,
        False,
        "Verify the device permits PTY and shell creation.",
    ),
    "terminal_transport_failed": SanitizedSSHFailure(
        "terminal_transport_failed",
        ConnectionPhase.TERMINAL_IO,
        True,
        "Retry the device operation after checking connectivity.",
    ),
    "device_command_rejected": SanitizedSSHFailure(
        "device_command_rejected",
        ConnectionPhase.TERMINAL_IO,
        False,
        None,
    ),
    "configuration_error": SanitizedSSHFailure(
        "configuration_error",
        ConnectionPhase.TCP,
        False,
        None,
    ),
}

_ERROR_TYPES: dict[str, type[AppError]] = {
    "device_connection_failed": DriverConnectionError,
    "device_timeout": DriverTimeoutError,
    "device_authentication_failed": DriverAuthenticationError,
    "device_host_key_verification_failed": DriverHostKeyVerificationError,
    "legacy_ssh_negotiation_failed": DriverSSHNegotiationError,
    "terminal_pty_rejected": DriverTerminalPTYError,
    "terminal_transport_failed": DriverTerminalIOError,
    "device_command_rejected": DriverCommandRejectedError,
    "configuration_error": ConfigurationError,
}

_PHASE_FAILURE_CODES = {
    ConnectionPhase.TCP: "device_connection_failed",
    ConnectionPhase.NEGOTIATION: "legacy_ssh_negotiation_failed",
    ConnectionPhase.HOST_KEY: "device_host_key_verification_failed",
    ConnectionPhase.AUTHENTICATION: "device_authentication_failed",
    ConnectionPhase.PTY: "terminal_pty_rejected",
    ConnectionPhase.TERMINAL_IO: "terminal_transport_failed",
}


def password_only_openssh_options(policy: SSHCompatibilityPolicy) -> tuple[str, ...]:
    return tuple(
        item
        for option in (*_PASSWORD_ONLY_OPTIONS, *policy.openssh_options)
        for item in ("-o", option)
    )


def translate_ssh_error(exc: Exception, *, phase: ConnectionPhase) -> AppError:
    failure = FAILURES[_PHASE_FAILURE_CODES[phase]]
    if isinstance(exc, AppError):
        failure = FAILURES.get(exc.code, failure)
        if failure.code in {"device_timeout", "configuration_error"}:
            failure = replace(failure, phase=phase)
    elif isinstance(exc, ScrapliTimeout):
        failure = replace(FAILURES["device_timeout"], phase=phase)
    elif isinstance(exc, ScrapliAuthenticationFailed):
        message = str(exc).lower()
        if any(marker in message for marker in _NEGOTIATION_MARKERS):
            failure = FAILURES["legacy_ssh_negotiation_failed"]
        elif any(marker in message for marker in _HOST_KEY_MARKERS):
            failure = FAILURES["device_host_key_verification_failed"]
        elif any(marker in message for marker in _TIMEOUT_MARKERS):
            failure = replace(FAILURES["device_timeout"], phase=phase)
        elif any(marker in message for marker in _CONFIGURATION_MARKERS):
            failure = replace(FAILURES["configuration_error"], phase=phase)
        elif any(marker in message for marker in _TCP_MARKERS):
            failure = FAILURES["device_connection_failed"]
        else:
            failure = FAILURES["device_authentication_failed"]
    elif isinstance(
        exc,
        ScrapliValueError | ScrapliModuleNotFound | ScrapliTransportPluginError,
    ):
        failure = replace(FAILURES["configuration_error"], phase=phase)

    details: dict[str, str | bool] = {
        "phase": failure.phase.value,
        "retryable": failure.retryable,
    }
    if failure.recommended_action is not None:
        details["recommended_action"] = failure.recommended_action
    return _ERROR_TYPES[failure.code](details=details)
