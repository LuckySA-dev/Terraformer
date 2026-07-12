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


class DriverAuthenticationError(DriverError):
    code = "device_authentication_failed"
    status_code = 401
    default_message = "The device rejected the credential profile"


class DriverTimeoutError(DriverError):
    code = "device_timeout"
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
