from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from app.api.dependencies import ContainerDependency, SessionDependency
from app.schemas.setup import MasterPasswordRequest, SessionStatus, SetupStatus
from app.services.setup import SessionService, SetupService

router = APIRouter(tags=["setup"])


@router.get("/setup", response_model=SetupStatus)
def setup_status(session: SessionDependency, container: ContainerDependency) -> SetupStatus:
    configured = SetupService(session, container.passwords).is_configured()
    return SetupStatus(configured=configured)


@router.post("/setup", response_model=SetupStatus, status_code=status.HTTP_201_CREATED)
def setup(
    request: MasterPasswordRequest,
    session: SessionDependency,
    container: ContainerDependency,
) -> SetupStatus:
    SetupService(session, container.passwords).configure(request.master_password.get_secret_value())
    return SetupStatus(configured=True)


@router.post("/session", response_model=SessionStatus)
def create_session(
    request: MasterPasswordRequest,
    response: Response,
    session: SessionDependency,
    container: ContainerDependency,
) -> SessionStatus:
    token = SessionService(session, container.passwords, container.session_tokens).authenticate(
        request.master_password.get_secret_value()
    )
    response.set_cookie(
        key=container.settings.session_cookie_name,
        value=token,
        max_age=container.settings.session_ttl_seconds,
        httponly=True,
        secure=container.settings.session_cookie_secure,
        samesite=container.settings.session_cookie_samesite,
        path="/",
    )
    return SessionStatus(authenticated=True)


@router.get("/session", response_model=SessionStatus)
def session_status(request: Request, container: ContainerDependency) -> SessionStatus:
    token = request.cookies.get(container.settings.session_cookie_name)
    authenticated = token is not None and container.session_tokens.verify(token) is not None
    return SessionStatus(authenticated=authenticated)


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(response: Response, container: ContainerDependency) -> Response:
    response.delete_cookie(
        key=container.settings.session_cookie_name,
        path="/",
        secure=container.settings.session_cookie_secure,
        samesite=container.settings.session_cookie_samesite,
        httponly=True,
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
