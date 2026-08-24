from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.dependencies import Authenticated, ContainerDependency, SessionDependency
from app.assistant.client import AIProviderConnectionError
from app.core.errors import AIGatewayDisabledError
from app.models import ProviderProfile
from app.schemas.provider_profiles import (
    ProviderProfileCreate,
    ProviderProfileUpdate,
    ProviderProfileView,
)
from app.services.provider_profiles import ProviderProfileService


def _require_enabled(container: ContainerDependency) -> None:
    if not container.settings.ai_gateway_enabled:
        raise AIGatewayDisabledError()


router = APIRouter(
    prefix="/provider-profiles",
    tags=["provider-profiles"],
    dependencies=[Depends(_require_enabled)],
)


def _service(session: SessionDependency, container: ContainerDependency) -> ProviderProfileService:
    return ProviderProfileService(session, container.provider_key_vault)


def _view(profile: ProviderProfile) -> ProviderProfileView:
    return ProviderProfileView(
        id=profile.id,
        name=profile.name,
        base_url=profile.base_url,
        model_id=profile.model_id,
        has_api_key=profile.encrypted_api_key is not None,
        context_limit_override=profile.context_limit_override,
        supports_streaming=profile.supports_streaming,
        supports_tool_calling=profile.supports_tool_calling,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


@router.get("", response_model=list[ProviderProfileView])
def list_profiles(_auth: Authenticated, session: SessionDependency, container: ContainerDependency):
    return [_view(p) for p in _service(session, container).list()]


@router.post("", response_model=ProviderProfileView, status_code=status.HTTP_201_CREATED)
def create_profile(
    request: ProviderProfileCreate,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    return _view(_service(session, container).create(request))


@router.get("/{profile_id}", response_model=ProviderProfileView)
def get_profile(
    profile_id: UUID,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    return _view(_service(session, container).get(profile_id))


@router.patch("/{profile_id}", response_model=ProviderProfileView)
def update_profile(
    profile_id: UUID,
    request: ProviderProfileUpdate,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    return _view(_service(session, container).update(profile_id, request))


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_profile(
    profile_id: UUID,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
) -> Response:
    _service(session, container).delete(profile_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{profile_id}/probe", response_model=ProviderProfileView)
async def probe_profile(
    profile_id: UUID,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    try:
        profile = await _service(session, container).probe_capabilities(
            profile_id, container.ai_provider_client
        )
    except AIProviderConnectionError as exc:
        raise HTTPException(
            status_code=502, detail="Could not reach the configured endpoint"
        ) from exc
    return _view(profile)
