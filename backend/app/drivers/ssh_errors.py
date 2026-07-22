from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from scrapli.exceptions import (
    ScrapliAuthenticationFailed,
    ScrapliConnectionError,
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
    DriverConnectionLostError,
    DriverConnectionRefusedError,
    DriverHostKeyChangedError,
    DriverHostKeyUnknownError,
    DriverHostKeyVerificationError,
    DriverNameResolutionError,
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
_HOST_KEY_CHANGED_MARKERS = (
    "remote host identification has changed",
    "host key has changed",
)
_HOST_KEY_UNKNOWN_MARKERS = (
    "host key is known for",
    "host key is unknown",
    "host key is not known",
    "host key is not trusted",
)
_HOST_KEY_MARKERS = ("host key verification failed",)
_TIMEOUT_MARKERS = ("timed out connecting", "operation timed out", "connection timed out")
_CONNECTION_REFUSED_MARKERS = ("connection refused",)
_NAME_RESOLUTION_MARKERS = (
    "could not resolve address",
    "could not resolve hostname",
)
_CONNECTION_LOST_MARKERS = (
    "connection reset",
    "connection closed",
    "closed by remote host",
    "encountered eof reading from transport",
)
_TCP_MARKERS = ("no route to host", "network is unreachable")
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
    "device_connection_timeout": SanitizedSSHFailure(
        "device_connection_timeout",
        ConnectionPhase.TCP,
        True,
        "Retry after verifying device reachability and network latency.",
    ),
    "device_connection_refused": SanitizedSSHFailure(
        "device_connection_refused",
        ConnectionPhase.TCP,
        False,
        "Verify that SSH is listening on the configured device port.",
    ),
    "device_connection_lost": SanitizedSSHFailure(
        "device_connection_lost",
        ConnectionPhase.TCP,
        True,
        "Retry after checking device reachability and SSH availability.",
    ),
    "device_name_resolution_failed": SanitizedSSHFailure(
        "device_name_resolution_failed",
        ConnectionPhase.TCP,
        False,
        "Verify the configured device address.",
    ),
    "device_authentication_failed": SanitizedSSHFailure(
        "device_authentication_failed",
        ConnectionPhase.AUTHENTICATION,
        False,
        "Verify the selected credential profile and device login policy.",
    ),
    "device_host_key_indeterminate": SanitizedSSHFailure(
        "device_connection_failed",
        ConnectionPhase.HOST_KEY,
        False,
        "Verify the saved SSH host key for this device.",
    ),
    "device_host_key_unknown": SanitizedSSHFailure(
        "device_host_key_unknown",
        ConnectionPhase.HOST_KEY,
        False,
        "Verify and enroll the device SSH host key.",
    ),
    "device_host_key_changed": SanitizedSSHFailure(
        "device_host_key_changed",
        ConnectionPhase.HOST_KEY,
        False,
        "Verify the device identity before replacing its saved SSH host key.",
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
    "device_connection_timeout": DriverTimeoutError,
    "device_connection_refused": DriverConnectionRefusedError,
    "device_connection_lost": DriverConnectionLostError,
    "device_name_resolution_failed": DriverNameResolutionError,
    "device_authentication_failed": DriverAuthenticationError,
    "device_host_key_unknown": DriverHostKeyUnknownError,
    "device_host_key_changed": DriverHostKeyChangedError,
    "legacy_ssh_negotiation_failed": DriverSSHNegotiationError,
    "terminal_pty_rejected": DriverTerminalPTYError,
    "terminal_transport_failed": DriverTerminalIOError,
    "device_command_rejected": DriverCommandRejectedError,
    "configuration_error": ConfigurationError,
}

_PHASE_FAILURE_CODES = {
    ConnectionPhase.TCP: "device_connection_failed",
    ConnectionPhase.NEGOTIATION: "legacy_ssh_negotiation_failed",
    ConnectionPhase.HOST_KEY: "device_host_key_indeterminate",
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
    if phase is ConnectionPhase.TERMINAL_IO and isinstance(
        exc,
        DriverConnectionError
        | DriverAuthenticationError
        | ScrapliAuthenticationFailed
        | ScrapliConnectionError,
    ):
        failure = FAILURES["terminal_transport_failed"]
    elif isinstance(exc, AppError):
        if type(exc) is DriverHostKeyVerificationError:
            failure = FAILURES["device_host_key_indeterminate"]
        else:
            failure = FAILURES.get(exc.code, failure)
        if failure.code in {"device_connection_timeout", "configuration_error"}:
            failure = replace(failure, phase=phase)
    elif isinstance(exc, ScrapliTimeout):
        failure = replace(FAILURES["device_connection_timeout"], phase=phase)
    elif isinstance(exc, ScrapliConnectionError):
        message = str(exc).lower()
        if any(marker in message for marker in _CONNECTION_LOST_MARKERS):
            failure = replace(FAILURES["device_connection_lost"], phase=phase)
    elif isinstance(exc, ScrapliAuthenticationFailed):
        message = str(exc).lower()
        if any(marker in message for marker in _NEGOTIATION_MARKERS):
            failure = FAILURES["legacy_ssh_negotiation_failed"]
        elif any(marker in message for marker in _HOST_KEY_CHANGED_MARKERS):
            failure = FAILURES["device_host_key_changed"]
        elif any(marker in message for marker in _HOST_KEY_UNKNOWN_MARKERS):
            failure = FAILURES["device_host_key_unknown"]
        elif any(marker in message for marker in _HOST_KEY_MARKERS):
            failure = FAILURES["device_host_key_indeterminate"]
        elif any(marker in message for marker in _TIMEOUT_MARKERS):
            failure = replace(FAILURES["device_connection_timeout"], phase=phase)
        elif any(marker in message for marker in _CONFIGURATION_MARKERS):
            failure = replace(FAILURES["configuration_error"], phase=phase)
        elif any(marker in message for marker in _CONNECTION_REFUSED_MARKERS):
            failure = FAILURES["device_connection_refused"]
        elif any(marker in message for marker in _NAME_RESOLUTION_MARKERS):
            failure = FAILURES["device_name_resolution_failed"]
        elif any(marker in message for marker in _CONNECTION_LOST_MARKERS):
            failure = FAILURES["device_connection_lost"]
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
    error_type = (
        DriverHostKeyVerificationError
        if failure is FAILURES["device_host_key_indeterminate"]
        else _ERROR_TYPES[failure.code]
    )
    return error_type(details=details)
