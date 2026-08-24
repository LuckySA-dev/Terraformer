from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.assistant.client import AIProviderClient
from app.core.errors import ArtifactIntegrityError, ConflictError
from app.core.security import EnvelopeCipher
from app.core.time import new_uuid
from app.models import ProviderProfile
from app.repositories.provider_profiles import ProviderProfileRepository
from app.schemas.provider_profiles import ProviderProfileCreate, ProviderProfileUpdate


@dataclass(frozen=True, slots=True)
class ProviderKeyMaterial:
    api_key: str | None


class ProviderKeyVault:
    def __init__(self, cipher: EnvelopeCipher) -> None:
        self._cipher = cipher

    def encrypt(self, profile_id: UUID, material: ProviderKeyMaterial) -> bytes | None:
        if material.api_key is None:
            return None
        plaintext = json.dumps(
            {"api_key": material.api_key, "version": 1},
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return self._cipher.encrypt(plaintext, aad=self._aad(profile_id))

    def decrypt(self, profile: ProviderProfile) -> ProviderKeyMaterial:
        if profile.encrypted_api_key is None:
            return ProviderKeyMaterial(api_key=None)
        plaintext = self._cipher.decrypt(profile.encrypted_api_key, aad=self._aad(profile.id))
        try:
            payload = json.loads(plaintext)
            if payload.get("version") != 1:
                raise ValueError("unsupported version")
            api_key = payload.get("api_key")
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            raise ArtifactIntegrityError("Provider profile payload is invalid") from exc
        return ProviderKeyMaterial(api_key=str(api_key) if api_key is not None else None)

    @staticmethod
    def _aad(profile_id: UUID) -> bytes:
        return f"provider-profile:v1:{profile_id}".encode()


class ProviderProfileService:
    def __init__(self, session: Session, vault: ProviderKeyVault) -> None:
        self._session = session
        self._vault = vault
        self._profiles = ProviderProfileRepository(session)

    def list(self) -> list[ProviderProfile]:
        return self._profiles.list()

    def get(self, profile_id: UUID) -> ProviderProfile:
        return self._profiles.get(profile_id)

    def create(self, request: ProviderProfileCreate) -> ProviderProfile:
        if self._profiles.find_by_name(request.name) is not None:
            raise ConflictError("A provider profile with this name already exists")
        profile_id = new_uuid()
        api_key = request.api_key.get_secret_value() if request.api_key is not None else None
        profile = ProviderProfile(
            id=profile_id,
            name=request.name,
            base_url=request.base_url,
            model_id=request.model_id,
            context_limit_override=request.context_limit_override,
            encrypted_api_key=self._vault.encrypt(profile_id, ProviderKeyMaterial(api_key=api_key)),
        )
        try:
            self._profiles.add(profile)
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise ConflictError("A provider profile with this name already exists") from exc
        return profile

    def update(self, profile_id: UUID, request: ProviderProfileUpdate) -> ProviderProfile:
        profile = self._profiles.get(profile_id, for_update=True)
        changes = request.model_fields_set
        if "name" in changes and request.name is not None:
            name = request.name.strip()
            existing = self._profiles.find_by_name(name)
            if existing is not None and existing.id != profile.id:
                raise ConflictError("A provider profile with this name already exists")
            profile.name = name
        if "base_url" in changes and request.base_url is not None:
            profile.base_url = request.base_url
        if "model_id" in changes and request.model_id is not None:
            profile.model_id = request.model_id
        if "context_limit_override" in changes:
            profile.context_limit_override = request.context_limit_override
        if request.clear_api_key:
            profile.encrypted_api_key = None
        elif "api_key" in changes and request.api_key is not None:
            material = ProviderKeyMaterial(api_key=request.api_key.get_secret_value())
            profile.encrypted_api_key = self._vault.encrypt(profile.id, material)
        try:
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise ConflictError("A provider profile with this name already exists") from exc
        return profile

    def delete(self, profile_id: UUID) -> None:
        profile = self._profiles.get(profile_id)
        self._profiles.delete(profile)
        self._session.commit()

    async def probe_capabilities(
        self, profile_id: UUID, client: AIProviderClient
    ) -> ProviderProfile:
        profile = self._profiles.get(profile_id, for_update=True)
        material = self._vault.decrypt(profile)
        capabilities = await client.probe_capabilities(
            base_url=profile.base_url, api_key=material.api_key, model_id=profile.model_id
        )
        profile.supports_streaming = capabilities.supports_streaming
        profile.supports_tool_calling = capabilities.supports_tool_calling
        self._session.commit()
        return profile
