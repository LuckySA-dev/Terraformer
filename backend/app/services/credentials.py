from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ArtifactIntegrityError, ConflictError
from app.core.security import EnvelopeCipher
from app.core.time import new_uuid
from app.models import CredentialProfile
from app.repositories.credentials import CredentialProfileRepository
from app.schemas.credentials import CredentialProfileCreate, CredentialProfileUpdate


@dataclass(frozen=True, slots=True)
class CredentialMaterial:
    username: str
    password: str
    enable_password: str | None = None


class CredentialVault:
    def __init__(self, cipher: EnvelopeCipher) -> None:
        self._cipher = cipher

    def encrypt(self, profile_id: UUID, material: CredentialMaterial) -> bytes:
        plaintext = json.dumps(
            {
                "username": material.username,
                "password": material.password,
                "enable_password": material.enable_password,
                "version": 1,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return self._cipher.encrypt(plaintext, aad=self._aad(profile_id))

    def decrypt(self, profile: CredentialProfile) -> CredentialMaterial:
        plaintext = self._cipher.decrypt(
            profile.encrypted_secret,
            aad=self._aad(profile.id),
        )
        try:
            payload = json.loads(plaintext)
            if payload.get("version") != 1:
                raise ValueError("unsupported version")
            username = str(payload["username"])
            password = str(payload["password"])
            enable_password = payload.get("enable_password")
            if enable_password is not None:
                enable_password = str(enable_password)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            raise ArtifactIntegrityError("Credential profile payload is invalid") from exc
        if not username or not password:
            raise ArtifactIntegrityError("Credential profile payload is incomplete")
        return CredentialMaterial(
            username=username,
            password=password,
            enable_password=enable_password,
        )

    @staticmethod
    def _aad(profile_id: UUID) -> bytes:
        return f"credential-profile:v1:{profile_id}".encode()


class CredentialProfileService:
    def __init__(self, session: Session, vault: CredentialVault) -> None:
        self._session = session
        self._vault = vault
        self._profiles = CredentialProfileRepository(session)

    def list(self) -> list[CredentialProfile]:
        return self._profiles.list()

    def get(self, profile_id: UUID) -> CredentialProfile:
        return self._profiles.get(profile_id)

    def create(self, request: CredentialProfileCreate) -> CredentialProfile:
        if self._profiles.find_by_name(request.name) is not None:
            raise ConflictError("A credential profile with this name already exists")
        profile_id = new_uuid()
        material = CredentialMaterial(
            username=request.username.get_secret_value(),
            password=request.password.get_secret_value(),
            enable_password=_secret_value(request.enable_password),
        )
        profile = CredentialProfile(
            id=profile_id,
            name=request.name,
            encrypted_secret=self._vault.encrypt(profile_id, material),
            has_username=True,
            has_password=True,
            has_enable_password=material.enable_password is not None,
        )
        try:
            self._profiles.add(profile)
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise ConflictError("A credential profile with this name already exists") from exc
        return profile

    def update(
        self,
        profile_id: UUID,
        request: CredentialProfileUpdate,
    ) -> CredentialProfile:
        profile = self._profiles.get(profile_id, for_update=True)
        changes = request.model_fields_set
        if "name" in changes and request.name is not None:
            name = request.name.strip()
            existing = self._profiles.find_by_name(name)
            if existing is not None and existing.id != profile.id:
                raise ConflictError("A credential profile with this name already exists")
            profile.name = name
        secret_fields = {"username", "password", "enable_password", "clear_enable_password"}
        if changes & secret_fields:
            current = self._vault.decrypt(profile)
            username = _secret_value(request.username) or current.username
            password = _secret_value(request.password) or current.password
            enable_password = current.enable_password
            if request.clear_enable_password:
                enable_password = None
            elif "enable_password" in changes:
                enable_password = _secret_value(request.enable_password)
            material = CredentialMaterial(username, password, enable_password)
            profile.encrypted_secret = self._vault.encrypt(profile.id, material)
            profile.has_username = bool(username)
            profile.has_password = bool(password)
            profile.has_enable_password = enable_password is not None
        try:
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise ConflictError("A credential profile with this name already exists") from exc
        return profile

    def delete(self, profile_id: UUID) -> None:
        profile = self._profiles.get(profile_id)
        try:
            self._profiles.delete(profile)
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise ConflictError(
                "Credential profile is still assigned to one or more devices"
            ) from exc


def _secret_value(value: SecretStr | None) -> str | None:
    return value.get_secret_value() if value is not None else None

