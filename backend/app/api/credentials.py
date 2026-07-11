from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Response, status

from app.api.dependencies import Authenticated, ContainerDependency, SessionDependency
from app.schemas.credentials import (
    CredentialProfileCreate,
    CredentialProfileUpdate,
    CredentialProfileView,
)
from app.services.credentials import CredentialProfileService

router = APIRouter(prefix="/credential-profiles", tags=["credential-profiles"])


def _service(
    session: SessionDependency,
    container: ContainerDependency,
) -> CredentialProfileService:
    return CredentialProfileService(session, container.credential_vault)


@router.get("", response_model=list[CredentialProfileView])
def list_profiles(
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    return _service(session, container).list()


@router.post("", response_model=CredentialProfileView, status_code=status.HTTP_201_CREATED)
def create_profile(
    request: CredentialProfileCreate,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    return _service(session, container).create(request)


@router.get("/{profile_id}", response_model=CredentialProfileView)
def get_profile(
    profile_id: UUID,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    return _service(session, container).get(profile_id)


@router.patch("/{profile_id}", response_model=CredentialProfileView)
def update_profile(
    profile_id: UUID,
    request: CredentialProfileUpdate,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    return _service(session, container).update(profile_id, request)


@router.delete(
    "/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_profile(
    profile_id: UUID,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
) -> Response:
    _service(session, container).delete(profile_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
