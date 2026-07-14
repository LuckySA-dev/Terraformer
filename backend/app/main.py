from __future__ import annotations

from time import monotonic
from typing import cast
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp

from app.api.router import api_router
from app.api.terminal import router as terminal_router
from app.container import ApplicationContainer, get_default_container
from app.core.errors import AppError
from app.core.logging import configure_logging, redact_value

logger = structlog.get_logger(__name__)
_MAX_REQUEST_BYTES = 1_048_576


class SecurityAndRequestContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, container: ApplicationContainer) -> None:
        super().__init__(app)
        self._container = container

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid4())
        request.state.request_id = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = monotonic()

        rejected = self._validate_request(request, request_id)
        if rejected is not None:
            return rejected
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["referrer-policy"] = "no-referrer"
        logger.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=max(0, int((monotonic() - started) * 1_000)),
        )
        return response

    def _validate_request(self, request: Request, request_id: str) -> JSONResponse | None:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                too_large = int(content_length) > _MAX_REQUEST_BYTES
            except ValueError:
                too_large = True
            if too_large:
                return _error_response(
                    status_code=413,
                    code="request_too_large",
                    message="Request body exceeds the one-megabyte limit",
                    details={},
                    request_id=request_id,
                )
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return None
        origin = request.headers.get("origin")
        if (
            origin is not None
            and origin.rstrip("/") not in self._container.settings.trusted_origins()
        ):
            return _error_response(
                status_code=403,
                code="csrf_origin_rejected",
                message="The request origin is not trusted",
                details={},
                request_id=request_id,
            )
        if origin is None and request.headers.get("sec-fetch-site") == "cross-site":
            return _error_response(
                status_code=403,
                code="csrf_origin_rejected",
                message="Cross-site state-changing requests are not allowed",
                details={},
                request_id=request_id,
            )
        return None


def create_app(container: ApplicationContainer | None = None) -> FastAPI:
    active_container = container or get_default_container()
    configure_logging(active_container.settings.log_level)
    application = FastAPI(
        title=active_container.settings.app_name,
        version=active_container.settings.app_version,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    application.state.container = active_container
    application.add_middleware(SecurityAndRequestContextMiddleware, container=active_container)
    application.include_router(api_router)
    application.include_router(terminal_router)

    @application.exception_handler(AppError)
    async def handle_app_error(  # pyright: ignore[reportUnusedFunction]
        request: Request, exc: AppError
    ) -> JSONResponse:
        return _error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=_safe_details(exc.details),
            request_id=_request_id(request),
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(  # pyright: ignore[reportUnusedFunction]
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        errors = [
            {
                "location": ".".join(str(part) for part in error.get("loc", ())),
                "message": str(error.get("msg", "Invalid value")),
                "type": str(error.get("type", "validation_error")),
            }
            for error in exc.errors()
        ]
        return _error_response(
            status_code=422,
            code="validation_error",
            message="Request validation failed",
            details={"errors": errors},
            request_id=_request_id(request),
        )

    @application.exception_handler(Exception)
    async def handle_unexpected_error(  # pyright: ignore[reportUnusedFunction]
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.error(
            "unhandled_exception",
            method=request.method,
            path=request.url.path,
            error_type=type(exc).__name__,
        )
        return _error_response(
            status_code=500,
            code="internal_error",
            message="An internal error occurred",
            details={},
            request_id=_request_id(request),
        )

    return application


def _safe_details(details: dict[str, object]) -> dict[str, object]:
    sanitized = redact_value(details)
    return cast(dict[str, object], sanitized) if isinstance(sanitized, dict) else {}


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", uuid4()))


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, object],
    request_id: str,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details,
                "request_id": request_id,
            }
        },
        headers={"x-request-id": request_id},
    )


app = create_app()
