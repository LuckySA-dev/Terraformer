from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class AppError(Exception):
    code = "internal_error"
    status_code = 500
    default_message = "An internal error occurred"

    def __init__(
        self,
        message: str | None = None,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.details = dict(details or {})
        super().__init__(self.message)


class ConfigurationError(AppError):
    code = "configuration_error"
    default_message = "The service is not configured correctly"


class NotFoundError(AppError):
    code = "not_found"
    status_code = 404
    default_message = "The requested resource was not found"


class ConflictError(AppError):
    code = "conflict"
    status_code = 409
    default_message = "The request conflicts with existing state"


class SetupRequiredError(AppError):
    code = "setup_required"
    status_code = 428
    default_message = "First-run setup is required"


class AlreadyConfiguredError(ConflictError):
    code = "already_configured"
    default_message = "First-run setup has already been completed"


class AuthenticationRequiredError(AppError):
    code = "authentication_required"
    status_code = 401
    default_message = "Authentication is required"


class InvalidCredentialsError(AuthenticationRequiredError):
    code = "invalid_credentials"
    default_message = "The supplied credentials are invalid"


class DriverError(AppError):
    code = "driver_error"
    status_code = 502
    default_message = "The device operation failed"


class DriverConnectionError(DriverError):
    code = "device_connection_failed"
    default_message = "Unable to connect to the device"


class DriverConnectionRefusedError(DriverConnectionError):
    code = "device_connection_refused"
    default_message = "The device refused the SSH connection"


class DriverConnectionLostError(DriverConnectionError):
    code = "device_connection_lost"
    default_message = "The device connection was lost"


class DriverNameResolutionError(DriverConnectionError):
    code = "device_name_resolution_failed"
    default_message = "The device address could not be resolved"


class DriverAuthenticationError(DriverError):
    code = "device_authentication_failed"
    status_code = 401
    default_message = "The device rejected the credential profile"


class DriverHostKeyVerificationError(DriverConnectionError):
    default_message = "SSH host key verification failed"


class DriverHostKeyUnknownError(DriverHostKeyVerificationError):
    code = "device_host_key_unknown"
    default_message = "The device SSH host key is unknown"


class DriverHostKeyChangedError(DriverHostKeyVerificationError):
    code = "device_host_key_changed"
    default_message = "The device SSH host key has changed"


class HostKeyCandidateMismatchError(ConflictError):
    code = "host_key_candidate_mismatch"
    default_message = "The SSH host-key candidate does not match this connection"


class HostKeyCandidateExpiredError(ConflictError):
    code = "host_key_candidate_expired"
    default_message = "The SSH host-key candidate expired or is unavailable"


class DriverSSHNegotiationError(DriverConnectionError):
    code = "legacy_ssh_negotiation_failed"
    default_message = "SSH negotiation with the device failed"


class DriverTerminalPTYError(DriverConnectionError):
    code = "terminal_pty_rejected"
    default_message = "The device rejected terminal setup"


class DriverTerminalIOError(DriverConnectionError):
    code = "terminal_transport_failed"
    default_message = "The device terminal transport failed"


class DriverTimeoutError(DriverError):
    code = "device_connection_timeout"
    status_code = 504
    default_message = "The device operation timed out"


class DriverCommandRejectedError(DriverError):
    code = "device_command_rejected"
    default_message = "The device rejected a read-only command"


class UnsupportedCapabilityError(AppError):
    code = "unsupported_capability"
    status_code = 422
    default_message = "The selected driver does not support this capability"


class ArtifactError(AppError):
    code = "artifact_error"
    default_message = "The encrypted artifact could not be processed"


class ArtifactIntegrityError(ArtifactError):
    code = "artifact_integrity_error"
    default_message = "The encrypted artifact failed integrity verification"


class SnapshotImmutableError(ConflictError):
    code = "snapshot_immutable"
    default_message = "Configuration snapshots are immutable"


class QueueUnavailableError(AppError):
    code = "queue_unavailable"
    status_code = 503
    default_message = "The background job queue is unavailable"


class AnalysisDisabledByPolicyError(AppError):
    code = "analysis_disabled_by_policy"
    status_code = 403
    default_message = "Configuration analysis is disabled by server policy"


class AnalysisUnavailableError(AppError):
    code = "analysis_unavailable"
    status_code = 503
    default_message = "Configuration analysis support is not installed"


class AnalysisBackendUnavailableError(AppError):
    code = "analysis_backend_unavailable"
    status_code = 503
    default_message = "The analysis service is not reachable"


class AnalysisNoConfigsError(AppError):
    code = "analysis_no_configs"
    status_code = 422
    default_message = "No device has a configuration snapshot to analyse"


class AnalysisSnapshotExpiredError(ConflictError):
    code = "analysis_snapshot_expired"
    default_message = "The analysis snapshot is no longer loaded and must be re-parsed"


class AnalysisTimeoutError(AppError):
    code = "analysis_timeout"
    status_code = 504
    default_message = "The analysis query exceeded its time limit"
