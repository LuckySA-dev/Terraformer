# Phase 4 AI Assistant (Single-Provider Slice) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a chat-first AI assistant against one generic OpenAI-compatible provider (BYOK), with read-only tools and AI-drafted Change Plans that flow through the existing Phase 3 pipeline unmodified.

**Architecture:** New `app/assistant/` backend module (client → tools → sanitizer → service → router) mirroring `app/changes/`'s shape, a WebSocket chat endpoint mirroring the existing Direct Mode terminal's streaming pattern, and a new `frontend/src/features/assistant/` feature folder reusing the Credential-profile CRUD pattern and a newly-extracted `ChangePlanCard`.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Pydantic, the official `openai` Python SDK (new dependency, pointed at a user-supplied `base_url`), React, TanStack Query, native WebSocket.

## Global Constraints

- No self-hosted model serving — BYOK `base_url` + API key only (spec §2.1)
- Single provider family this slice: generic OpenAI-compatible wire format only — no Anthropic/Gemini/native-Ollama adapters (spec §3 out of scope)
- The tool schema sent to the model never contains a write tool, in either mode (spec §6)
- AI-drafted Change Plans call `app/changes/service.py`'s existing `preview()` — no parallel/looser validation path (spec §2.6, §6)
- Destructive-command blocklist (`erase`/`reload`/`format`/`factory reset`) is unconditional, not mode-gated (spec §2.4)
- Confirm mode is the default and what every new `AssistantSession` starts in; Auto mode requires explicit one-time risk acknowledgment and is capped per session (spec §6)
- Feature sits behind `ai_gateway_enabled` (off by default), matching the `analysis_enabled`/`telnet_enabled`/`structured_writes_enabled` router-level `Depends` pattern in `app/api/changes.py`/`app/api/analysis.py`
- Secrets never enter AI context — tool results are scrubbed before serialization (spec §6, `docs/safety-model.md` §"Secret rules")
- Migrations are hand-authored `YYYYMMDD_NNNN_description.py` files with literal string revision ids (not autogenerate), chained off the current head `20260809_0009`
- **Deviation from spec, confirmed during planning:** the spec's "Auto mode relays console commands automatically" assumed a live cross-panel relay channel into an open terminal WebSocket. That channel does not exist (`TerminalSession`/`TerminalPanel` expose no send-a-command hook), and `AppShell` unmounts every non-active view — so a terminal session is not even alive while the Assistant page is showing. Task 14 implements blocklist-check + navigate-and-stage (command copied, user navigates to that device's terminal and sends it themselves) for **both** modes. Auto mode's "no per-step click" behavior applies only to Change Plan applies (Task 8), which are stateless REST calls, not live sessions. Live cross-panel relay is a real, larger follow-up, not built here.

---

## Task 1: ProviderProfile backend stack

**Files:**
- Modify: `backend/app/models/entities.py` (add `ProviderProfile` class, near `CredentialProfile`)
- Modify: `backend/app/models/__init__.py` (export `ProviderProfile`)
- Modify: `backend/app/core/config.py` (add `ai_gateway_enabled` setting)
- Modify: `backend/app/core/errors.py` (add `AIGatewayDisabledError`)
- Modify: `backend/app/container.py` (add `provider_key_vault` cached property)
- Modify: `backend/app/api/router.py` (register new router)
- Create: `backend/migrations/versions/20260824_0010_provider_profiles.py`
- Create: `backend/app/schemas/provider_profiles.py`
- Create: `backend/app/repositories/provider_profiles.py`
- Create: `backend/app/services/provider_profiles.py`
- Create: `backend/app/api/provider_profiles.py`
- Test: `backend/tests/integration/test_provider_profiles_api.py`

**Interfaces:**
- Produces: `ProviderProfile` model (`id`, `name`, `base_url`, `model_id`, `encrypted_api_key: bytes | None`, `context_limit_override: int | None`, `supports_streaming: bool`, `supports_tool_calling: bool`, timestamps); `ProviderKeyVault.encrypt(profile_id, material) -> bytes | None`, `ProviderKeyVault.decrypt(profile) -> ProviderKeyMaterial`; `ProviderProfileRepository` (`list`, `get`, `find_by_name`, `add`, `delete`); `ProviderProfileService` (`list()`, `get(id)`, `create(request)`, `update(id, request)`, `delete(id)`); `settings.ai_gateway_enabled: bool`. Later tasks (2, 4, 10) consume all of these.

- [ ] **Step 1: Write the failing integration test**

```python
# backend/tests/integration/test_provider_profiles_api.py
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _enable_ai_gateway(settings):
    settings.ai_gateway_enabled = True


def test_create_list_update_delete_provider_profile(client: TestClient) -> None:
    create = client.post(
        "/api/provider-profiles",
        json={
            "name": "Local Ollama",
            "base_url": "http://localhost:11434/v1",
            "model_id": "llama3.1",
            "api_key": None,
        },
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["name"] == "Local Ollama"
    assert body["has_api_key"] is False
    assert body["supports_streaming"] is False
    profile_id = body["id"]

    listed = client.get("/api/provider-profiles")
    assert listed.status_code == 200
    assert [p["id"] for p in listed.json()] == [profile_id]

    updated = client.patch(
        f"/api/provider-profiles/{profile_id}",
        json={"model_id": "llama3.2"},
    )
    assert updated.status_code == 200
    assert updated.json()["model_id"] == "llama3.2"

    deleted = client.delete(f"/api/provider-profiles/{profile_id}")
    assert deleted.status_code == 204
    assert client.get("/api/provider-profiles").json() == []


def test_provider_profiles_disabled_by_default(client: TestClient, settings) -> None:
    settings.ai_gateway_enabled = False
    response = client.get("/api/provider-profiles")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ai_gateway_disabled_by_policy"


def test_create_provider_profile_with_api_key_never_returns_it(client: TestClient) -> None:
    create = client.post(
        "/api/provider-profiles",
        json={
            "name": "Cloud",
            "base_url": "https://api.openai.com/v1",
            "model_id": "gpt-4o",
            "api_key": "sk-test-not-a-real-key",
        },
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["has_api_key"] is True
    assert "api_key" not in body
    assert "sk-test-not-a-real-key" not in create.text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_provider_profiles_api.py -v`
Expected: FAIL — `404` (no such route) or import error, since nothing exists yet.

- [ ] **Step 3: Add the setting and error class**

In `backend/app/core/config.py`, add next to `structured_writes_enabled`:

```python
    # AI assistant gateway (BYOK — this application never runs or bundles a
    # model server). Off by default, same defense-in-depth reasoning as
    # structured_writes_enabled: read-only tools and AI-drafted Change Plans
    # both terminate in this application's own real write pipeline.
    ai_gateway_enabled: bool = False
```

In `backend/app/core/errors.py`, add next to `StructuredWritesDisabledError`:

```python
class AIGatewayDisabledError(AppError):
    code = "ai_gateway_disabled_by_policy"
    status_code = 403
    default_message = "The AI assistant gateway is disabled by server policy"
```

- [ ] **Step 4: Add the model**

In `backend/app/models/entities.py`, add next to `CredentialProfile`:

```python
class ProviderProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "provider_profiles"

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    encrypted_api_key: Mapped[bytes | None] = mapped_column(LargeBinary)
    context_limit_override: Mapped[int | None] = mapped_column(Integer)
    supports_streaming: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    supports_tool_calling: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
```

Add `ProviderProfile` to the exports in `backend/app/models/__init__.py` next to `CredentialProfile`.

- [ ] **Step 5: Write the migration**

```python
# backend/migrations/versions/20260824_0010_provider_profiles.py
"""Add provider_profiles for the AI assistant gateway.

Revision ID: 20260824_0010
Revises: 20260809_0009
Create Date: 2026-08-24

BYOK provider profiles: a base URL, model id, and optional encrypted API key
(spec: docs/superpowers/specs/2026-08-24-phase-4-ai-assistant-design.md).
No key is required — "no-key local mode" is a valid configuration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0010"
down_revision: str | None = "20260809_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_profiles",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("model_id", sa.String(200), nullable=False),
        sa.Column("encrypted_api_key", sa.LargeBinary()),
        sa.Column("context_limit_override", sa.Integer()),
        sa.Column("supports_streaming", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("supports_tool_calling", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("provider_profiles")
```

- [ ] **Step 6: Write the key vault**

Create `backend/app/services/provider_profiles.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

from app.core.errors import ArtifactIntegrityError, NotFoundError
from app.core.security import EnvelopeCipher
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
    def __init__(self, repository: ProviderProfileRepository, vault: ProviderKeyVault) -> None:
        self._repository = repository
        self._vault = vault

    def list(self) -> list[ProviderProfile]:
        return self._repository.list()

    def get(self, profile_id: UUID) -> ProviderProfile:
        return self._repository.get(profile_id)

    def create(self, request: ProviderProfileCreate) -> ProviderProfile:
        profile = ProviderProfile(
            name=request.name,
            base_url=request.base_url,
            model_id=request.model_id,
            context_limit_override=request.context_limit_override,
        )
        profile = self._repository.add(profile)
        if request.api_key is not None:
            material = ProviderKeyMaterial(api_key=request.api_key.get_secret_value())
            profile.encrypted_api_key = self._vault.encrypt(profile.id, material)
        return profile

    def update(self, profile_id: UUID, request: ProviderProfileUpdate) -> ProviderProfile:
        profile = self._repository.get(profile_id, for_update=True)
        if request.name is not None:
            profile.name = request.name
        if request.base_url is not None:
            profile.base_url = request.base_url
        if request.model_id is not None:
            profile.model_id = request.model_id
        if request.context_limit_override is not None:
            profile.context_limit_override = request.context_limit_override
        if request.clear_api_key:
            profile.encrypted_api_key = None
        elif request.api_key is not None:
            material = ProviderKeyMaterial(api_key=request.api_key.get_secret_value())
            profile.encrypted_api_key = self._vault.encrypt(profile.id, material)
        return profile

    def delete(self, profile_id: UUID) -> None:
        profile = self._repository.get(profile_id)
        self._repository.delete(profile)
```

Note: `ProviderProfileRepository.get(..., for_update=False)` must exist before `update()` compiles — write it in Step 7 before running tests.

- [ ] **Step 7: Write schemas and repository**

Create `backend/app/schemas/provider_profiles.py`:

```python
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, SecretStr, field_validator

from app.schemas.common import APIModel


class ProviderProfileCreate(APIModel):
    name: str = Field(min_length=1, max_length=100)
    base_url: str = Field(min_length=1, max_length=500)
    model_id: str = Field(min_length=1, max_length=200)
    api_key: SecretStr | None = Field(default=None, max_length=4_096)
    context_limit_override: int | None = Field(default=None, ge=1, le=10_000_000)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name cannot be blank")
        return value

    @field_validator("base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        return value


class ProviderProfileUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    base_url: str | None = Field(default=None, min_length=1, max_length=500)
    model_id: str | None = Field(default=None, min_length=1, max_length=200)
    api_key: SecretStr | None = Field(default=None, max_length=4_096)
    clear_api_key: bool = False
    context_limit_override: int | None = Field(default=None, ge=1, le=10_000_000)


class ProviderProfileView(APIModel):
    id: UUID
    name: str
    base_url: str
    model_id: str
    has_api_key: bool
    context_limit_override: int | None
    supports_streaming: bool
    supports_tool_calling: bool
    created_at: datetime
    updated_at: datetime

    @field_validator("has_api_key", mode="before")
    @classmethod
    def _derive_has_api_key(cls, value: object) -> bool:
        # Allows constructing straight from the ORM row: pass
        # profile.encrypted_api_key is not None as this field at call sites
        # instead of exposing the raw bytes column on the schema at all.
        return bool(value)
```

Create `backend/app/repositories/provider_profiles.py`:

```python
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.models import ProviderProfile


class ProviderProfileRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list(self) -> list[ProviderProfile]:
        statement = select(ProviderProfile).order_by(ProviderProfile.name)
        return list(self._session.scalars(statement))

    def get(self, profile_id: UUID, *, for_update: bool = False) -> ProviderProfile:
        statement = select(ProviderProfile).where(ProviderProfile.id == profile_id)
        if for_update:
            statement = statement.with_for_update()
        profile = self._session.scalar(statement)
        if profile is None:
            raise NotFoundError(
                "Provider profile not found",
                details={"resource": "provider_profile", "id": str(profile_id)},
            )
        return profile

    def add(self, profile: ProviderProfile) -> ProviderProfile:
        self._session.add(profile)
        self._session.flush()
        return profile

    def delete(self, profile: ProviderProfile) -> None:
        self._session.delete(profile)
        self._session.flush()
```

Because `ProviderProfileView.has_api_key` needs `has_api_key=profile.encrypted_api_key is not None` at the point of construction (the ORM has no such attribute directly), the router builds the view explicitly rather than relying on bare `from_attributes` — see Step 8.

- [ ] **Step 8: Write the router and wire the container**

Create `backend/app/api/provider_profiles.py`:

```python
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.api.dependencies import Authenticated, ContainerDependency, SessionDependency
from app.core.errors import AIGatewayDisabledError
from app.repositories.provider_profiles import ProviderProfileRepository
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
    return ProviderProfileService(ProviderProfileRepository(session), container.provider_key_vault)


def _view(profile) -> ProviderProfileView:
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
    profile = _service(session, container).create(request)
    session.commit()
    return _view(profile)


@router.get("/{profile_id}", response_model=ProviderProfileView)
def get_profile(profile_id: UUID, _auth: Authenticated, session: SessionDependency, container: ContainerDependency):
    return _view(_service(session, container).get(profile_id))


@router.patch("/{profile_id}", response_model=ProviderProfileView)
def update_profile(
    profile_id: UUID,
    request: ProviderProfileUpdate,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    profile = _service(session, container).update(profile_id, request)
    session.commit()
    return _view(profile)


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_profile(
    profile_id: UUID,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
) -> Response:
    _service(session, container).delete(profile_id)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

In `backend/app/container.py`, add next to `credential_vault`:

```python
    @cached_property
    def provider_key_vault(self) -> ProviderKeyVault:
        return ProviderKeyVault(EnvelopeCipher(self.key_provider, purpose="provider-profiles"))
```

(Import `ProviderKeyVault` from `app.services.provider_profiles` at the top of `container.py`.)

In `backend/app/api/router.py`, add next to `credentials`:

```python
from app.api import provider_profiles
...
api_router.include_router(provider_profiles.router)
```

- [ ] **Step 9: Run the migration and the test**

Run: `cd backend && uv run alembic upgrade head`
Expected: applies `20260824_0010` cleanly.

Run: `cd backend && uv run pytest tests/integration/test_provider_profiles_api.py -v`
Expected: PASS (3 tests).

- [ ] **Step 10: Commit**

```bash
git add backend/app/models/entities.py backend/app/models/__init__.py \
  backend/app/core/config.py backend/app/core/errors.py backend/app/container.py \
  backend/app/api/router.py backend/app/api/provider_profiles.py \
  backend/app/schemas/provider_profiles.py backend/app/repositories/provider_profiles.py \
  backend/app/services/provider_profiles.py \
  backend/migrations/versions/20260824_0010_provider_profiles.py \
  backend/tests/integration/test_provider_profiles_api.py
git commit -m "feat: add provider profile CRUD behind ai_gateway_enabled"
```

---

## Task 2: AssistantSession + AssistantMessage models

**Files:**
- Modify: `backend/app/models/entities.py` (add `AssistantSessionMode`, `AssistantMessageRole` enums, `AssistantSession`, `AssistantMessage` models, near `ChangePlan`)
- Modify: `backend/app/models/__init__.py`
- Create: `backend/migrations/versions/20260824_0011_assistant_sessions.py`
- Create: `backend/app/schemas/assistant.py`
- Create: `backend/app/repositories/assistant.py`
- Test: `backend/tests/integration/test_assistant_repository.py`

**Interfaces:**
- Consumes: `ProviderProfile` (Task 1), the existing `enum_type(...)` helper already used by `ChangePlanStatus` in `app/models/entities.py`.
- Produces: `AssistantSession` (`id`, `provider_profile_id`, `mode: AssistantSessionMode`, `auto_mode_acknowledged_at: datetime | None`, `auto_apply_count: int`, timestamps, `messages` relationship); `AssistantMessage` (`id`, `session_id`, `role: AssistantMessageRole`, `content: str`, `tool_calls: dict | None`, `tool_results: dict | None`, timestamps); `AssistantSessionRepository` (`list`, `get`, `add`, `set_mode`, `record_auto_apply`); `AssistantMessageRepository` (`add`, `list_for_session`). Task 7 (chat service) and Task 8/9 (mode gating) consume these directly.

- [ ] **Step 1: Write the failing repository test**

```python
# backend/tests/integration/test_assistant_repository.py
from __future__ import annotations

from app.models import AssistantMessageRole, AssistantSessionMode, ProviderProfile
from app.repositories.assistant import AssistantMessageRepository, AssistantSessionRepository
from app.repositories.provider_profiles import ProviderProfileRepository


def test_create_session_defaults_to_confirm_mode(session_factory) -> None:
    with session_factory() as session:
        profile = ProviderProfileRepository(session).add(
            ProviderProfile(name="Local", base_url="http://localhost:11434/v1", model_id="llama3.1")
        )
        session.flush()
        created = AssistantSessionRepository(session).add(provider_profile_id=profile.id)
        session.commit()

        fetched = AssistantSessionRepository(session).get(created.id)
        assert fetched.mode is AssistantSessionMode.CONFIRM
        assert fetched.auto_apply_count == 0
        assert fetched.auto_mode_acknowledged_at is None


def test_messages_persist_in_order(session_factory) -> None:
    with session_factory() as session:
        profile = ProviderProfileRepository(session).add(
            ProviderProfile(name="Local", base_url="http://localhost:11434/v1", model_id="llama3.1")
        )
        session.flush()
        sessions = AssistantSessionRepository(session)
        chat_session = sessions.add(provider_profile_id=profile.id)
        session.flush()

        messages = AssistantMessageRepository(session)
        messages.add(session_id=chat_session.id, role=AssistantMessageRole.USER, content="hello")
        messages.add(session_id=chat_session.id, role=AssistantMessageRole.ASSISTANT, content="hi there")
        session.commit()

        history = messages.list_for_session(chat_session.id)
        assert [m.role for m in history] == [AssistantMessageRole.USER, AssistantMessageRole.ASSISTANT]
        assert [m.content for m in history] == ["hello", "hi there"]


def test_set_mode_requires_acknowledgment_timestamp_for_auto(session_factory) -> None:
    with session_factory() as session:
        profile = ProviderProfileRepository(session).add(
            ProviderProfile(name="Local", base_url="http://localhost:11434/v1", model_id="llama3.1")
        )
        session.flush()
        sessions = AssistantSessionRepository(session)
        chat_session = sessions.add(provider_profile_id=profile.id)
        session.flush()

        sessions.set_mode(chat_session, AssistantSessionMode.AUTO)
        session.commit()

        fetched = sessions.get(chat_session.id)
        assert fetched.mode is AssistantSessionMode.AUTO
        assert fetched.auto_mode_acknowledged_at is not None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_assistant_repository.py -v`
Expected: FAIL — `ImportError: cannot import name 'AssistantSessionMode'`.

- [ ] **Step 3: Add the enums and models**

In `backend/app/models/entities.py`, add near `ChangePlan`:

```python
class AssistantSessionMode(str, Enum):
    CONFIRM = "confirm"
    AUTO = "auto"


class AssistantMessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class AssistantSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "assistant_sessions"

    provider_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    mode: Mapped[AssistantSessionMode] = mapped_column(
        enum_type(AssistantSessionMode, "assistant_session_mode"),
        nullable=False,
        default=AssistantSessionMode.CONFIRM,
    )
    auto_mode_acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auto_apply_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    messages: Mapped[list[AssistantMessage]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="AssistantMessage.created_at",
    )


class AssistantMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "assistant_messages"

    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("assistant_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[AssistantMessageRole] = mapped_column(
        enum_type(AssistantMessageRole, "assistant_message_role"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_calls: Mapped[dict[str, object] | None] = mapped_column(JSON)
    tool_results: Mapped[dict[str, object] | None] = mapped_column(JSON)

    session: Mapped[AssistantSession] = relationship(back_populates="messages")
```

Add `AssistantSessionMode`, `AssistantMessageRole`, `AssistantSession`, `AssistantMessage` to `backend/app/models/__init__.py`'s exports.

- [ ] **Step 4: Write the migration**

```python
# backend/migrations/versions/20260824_0011_assistant_sessions.py
"""Add assistant_sessions and assistant_messages.

Revision ID: 20260824_0011
Revises: 20260824_0010
Create Date: 2026-08-24

Chat session/message persistence for the AI assistant (spec:
docs/superpowers/specs/2026-08-24-phase-4-ai-assistant-design.md).
auto_mode_acknowledged_at and auto_apply_count back the Auto-mode
risk-acknowledgment gate and per-session apply cap.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0011"
down_revision: str | None = "20260824_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MODE_VALUES = ("confirm", "auto")
_ROLE_VALUES = ("user", "assistant", "tool")


def _enum(name: str, values: Sequence[str]) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=False)


def upgrade() -> None:
    op.create_table(
        "assistant_sessions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "provider_profile_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("provider_profiles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "mode",
            _enum("assistant_session_mode", _MODE_VALUES),
            nullable=False,
            server_default="confirm",
        ),
        sa.Column("auto_mode_acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("auto_apply_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_assistant_sessions_provider_profile_id", "assistant_sessions", ["provider_profile_id"])

    op.create_table(
        "assistant_messages",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("assistant_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", _enum("assistant_message_role", _ROLE_VALUES), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tool_calls", sa.JSON()),
        sa.Column("tool_results", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_assistant_messages_session_id", "assistant_messages", ["session_id"])


def downgrade() -> None:
    op.drop_table("assistant_messages")
    op.drop_table("assistant_sessions")
```

- [ ] **Step 5: Write the repositories**

Create `backend/app/repositories/assistant.py`:

```python
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.time import utc_now
from app.models import AssistantMessage, AssistantMessageRole, AssistantSession, AssistantSessionMode


class AssistantSessionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list(self) -> list[AssistantSession]:
        statement = select(AssistantSession).order_by(AssistantSession.created_at.desc())
        return list(self._session.scalars(statement))

    def get(self, session_id: UUID, *, for_update: bool = False) -> AssistantSession:
        statement = select(AssistantSession).where(AssistantSession.id == session_id)
        if for_update:
            statement = statement.with_for_update()
        chat_session = self._session.scalar(statement)
        if chat_session is None:
            raise NotFoundError(
                "Assistant session not found",
                details={"resource": "assistant_session", "id": str(session_id)},
            )
        return chat_session

    def add(self, *, provider_profile_id: UUID) -> AssistantSession:
        chat_session = AssistantSession(provider_profile_id=provider_profile_id)
        self._session.add(chat_session)
        self._session.flush()
        return chat_session

    def set_mode(self, chat_session: AssistantSession, mode: AssistantSessionMode) -> None:
        chat_session.mode = mode
        if mode is AssistantSessionMode.AUTO:
            chat_session.auto_mode_acknowledged_at = utc_now()
            chat_session.auto_apply_count = 0
        self._session.flush()

    def record_auto_apply(self, chat_session: AssistantSession) -> None:
        chat_session.auto_apply_count += 1
        self._session.flush()


class AssistantMessageRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(
        self,
        *,
        session_id: UUID,
        role: AssistantMessageRole,
        content: str,
        tool_calls: dict[str, object] | None = None,
        tool_results: dict[str, object] | None = None,
    ) -> AssistantMessage:
        message = AssistantMessage(
            session_id=session_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
            tool_results=tool_results,
        )
        self._session.add(message)
        self._session.flush()
        return message

    def list_for_session(self, session_id: UUID) -> list[AssistantMessage]:
        statement = (
            select(AssistantMessage)
            .where(AssistantMessage.session_id == session_id)
            .order_by(AssistantMessage.created_at)
        )
        return list(self._session.scalars(statement))
```

`utc_now` — reuse the existing helper already imported by `TimestampMixin` in `app/models/base.py` (`app.core.time.utc_now` or wherever that mixin's import points; match its actual import path exactly rather than assuming `app.core.time`).

- [ ] **Step 6: Write schemas**

Create `backend/app/schemas/assistant.py`:

```python
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.models import AssistantMessageRole, AssistantSessionMode
from app.schemas.common import APIModel


class AssistantSessionCreate(APIModel):
    provider_profile_id: UUID


class AssistantSessionView(APIModel):
    id: UUID
    provider_profile_id: UUID
    mode: AssistantSessionMode
    auto_apply_count: int
    created_at: datetime
    updated_at: datetime


class AssistantMessageView(APIModel):
    id: UUID
    session_id: UUID
    role: AssistantMessageRole
    content: str
    tool_calls: dict[str, object] | None
    tool_results: dict[str, object] | None
    created_at: datetime


class SetAssistantModeRequest(APIModel):
    mode: AssistantSessionMode
    risk_acknowledged: bool = Field(default=False)
```

(`SetAssistantModeRequest.risk_acknowledged` is validated by the service in Task 7/9, not here — a schema-level check can't see the session's current mode.)

- [ ] **Step 7: Run the migration and the test**

Run: `cd backend && uv run alembic upgrade head`
Expected: applies `20260824_0011` cleanly.

Run: `cd backend && uv run pytest tests/integration/test_assistant_repository.py -v`
Expected: PASS (3 tests).

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/entities.py backend/app/models/__init__.py \
  backend/app/repositories/assistant.py backend/app/schemas/assistant.py \
  backend/migrations/versions/20260824_0011_assistant_sessions.py \
  backend/tests/integration/test_assistant_repository.py
git commit -m "feat: add assistant session and message persistence"
```

---

## Task 3: `ChangePlan.source` column

**Files:**
- Modify: `backend/app/models/entities.py` (add `ChangePlanSource` enum, `source` column on `ChangePlan`)
- Modify: `backend/app/repositories/changes.py` (`create()` gains a `source` kwarg)
- Modify: `backend/app/changes/service.py` (`preview()` gains a `source` kwarg, default `ChangePlanSource.MANUAL`)
- Modify: `backend/app/schemas/changes.py` (add `source` to `ChangePlanView`)
- Create: `backend/migrations/versions/20260824_0012_change_plan_source.py`
- Test: Modify `backend/tests/integration/test_changes_vertical_slice.py`

**Interfaces:**
- Produces: `ChangePlanSource` enum (`MANUAL`, `AI_GENERATED`); `ChangeService.preview(..., source: ChangePlanSource = ChangePlanSource.MANUAL)`; `ChangeRepository.create(..., source: ChangePlanSource)`. Task 8 (AI → Change Plan integration) is the only other caller — it passes `source=ChangePlanSource.AI_GENERATED` and nothing else about the pipeline changes.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/integration/test_changes_vertical_slice.py`:

```python
def test_preview_defaults_source_to_manual(client, ...):  # reuse this file's existing fixtures/setup
    response = client.post(
        "/api/change-plans",
        json={
            "device_id": str(device.id),
            "change_type": "interface_description",
            "target": "GigabitEthernet0/1",
            "desired_value": "uplink",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["source"] == "manual"


def test_service_preview_accepts_ai_generated_source(session_factory, container, device) -> None:
    from app.changes.service import ChangeService
    from app.models import ChangePlanSource

    with session_factory() as session:
        service = ChangeService(
            session,
            settings=container.settings,
            drivers=container.drivers,
            devices=DeviceRepository(session),
            snapshots=SnapshotService(session, store=container.snapshot_store, devices=DeviceRepository(session), drivers=container.drivers),
        )
        plan = service.preview(
            device_id=device.id,
            change_type=ChangeType.INTERFACE_DESCRIPTION,
            target="GigabitEthernet0/1",
            desired_value="ai-drafted uplink",
            source=ChangePlanSource.AI_GENERATED,
        )
        assert plan.source is ChangePlanSource.AI_GENERATED
```

Adapt the exact fixture names (`device`, `container`, imports) to match whatever this file already uses elsewhere for its existing `preview`/`apply` tests — copy its existing test's setup rather than reintroducing new fixtures.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_changes_vertical_slice.py -k "source" -v`
Expected: FAIL — `TypeError: preview() got an unexpected keyword argument 'source'` / `AttributeError: ChangePlanSource`.

- [ ] **Step 3: Add the enum and column**

In `backend/app/models/entities.py`, add near `ChangePlanStatus`:

```python
class ChangePlanSource(str, Enum):
    MANUAL = "manual"
    AI_GENERATED = "ai_generated"
```

Add to `ChangePlan` (after `risk`):

```python
    source: Mapped[ChangePlanSource] = mapped_column(
        enum_type(ChangePlanSource, "change_plan_source"),
        nullable=False,
        default=ChangePlanSource.MANUAL,
    )
```

Export `ChangePlanSource` from `backend/app/models/__init__.py`.

- [ ] **Step 4: Write the migration**

```python
# backend/migrations/versions/20260824_0012_change_plan_source.py
"""Add change_plans.source.

Revision ID: 20260824_0012
Revises: 20260824_0011
Create Date: 2026-08-24

Audit-only column distinguishing manually-drafted from AI-drafted Change
Plans. Does not alter validation, risk, or apply behavior — see spec
docs/superpowers/specs/2026-08-24-phase-4-ai-assistant-design.md §2.6.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0012"
down_revision: str | None = "20260824_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SOURCE_VALUES = ("manual", "ai_generated")


def upgrade() -> None:
    op.add_column(
        "change_plans",
        sa.Column(
            "source",
            sa.Enum(*_SOURCE_VALUES, name="change_plan_source", native_enum=False, create_constraint=False),
            nullable=False,
            server_default="manual",
        ),
    )


def downgrade() -> None:
    op.drop_column("change_plans", "source")
```

- [ ] **Step 5: Thread `source` through the repository and service**

In `backend/app/repositories/changes.py`, extend `create()`:

```python
    def create(
        self,
        *,
        device_id: UUID,
        safety_level: SafetyLevel,
        risk: ChangeRisk,
        source: ChangePlanSource = ChangePlanSource.MANUAL,
    ) -> ChangePlan:
        plan = ChangePlan(
            device_id=device_id,
            status=ChangePlanStatus.DRAFT,
            safety_level=safety_level,
            risk=risk,
            source=source,
        )
        self._session.add(plan)
        self._session.flush()
        return plan
```

In `backend/app/changes/service.py`, extend `preview()`'s signature and the one call site that constructs the plan:

```python
    def preview(
        self,
        *,
        device_id: UUID,
        change_type: ChangeType,
        target: str,
        desired_value: str,
        source: ChangePlanSource = ChangePlanSource.MANUAL,
    ) -> ChangePlan:
        ...  # unchanged body up to the plan = self._changes.create(...) call
        plan = self._changes.create(
            device_id=device.id,
            safety_level=driver.capabilities.safety_level,
            risk=risk,
            source=source,
        )
        ...  # unchanged rest of the method
```

Everything between `def preview(...)` and the `plan = self._changes.create(...)` line, and everything after it, is unchanged — only the signature and that one call gain `source`.

- [ ] **Step 6: Add `source` to the response schema**

In `backend/app/schemas/changes.py`, add `source: ChangePlanSource` to `ChangePlanView` (same position as `risk`). `app/api/changes.py`'s `preview_change` handler needs no change — it already returns whatever `.preview()` returns, and manual callers never pass `source`, so they keep getting `"manual"` by default.

- [ ] **Step 7: Run the tests**

Run: `cd backend && uv run alembic upgrade head`
Run: `cd backend && uv run pytest tests/integration/test_changes_vertical_slice.py -v`
Expected: PASS, including the two new tests and every pre-existing test in this file (a regression here means the default-argument threading broke an existing manual caller).

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/entities.py backend/app/models/__init__.py \
  backend/app/repositories/changes.py backend/app/changes/service.py \
  backend/app/schemas/changes.py \
  backend/migrations/versions/20260824_0012_change_plan_source.py \
  backend/tests/integration/test_changes_vertical_slice.py
git commit -m "feat: distinguish AI-generated Change Plans via a source column"
```

---

## Task 4: AI provider client (openai SDK wrapper)

**Files:**
- Modify: `backend/pyproject.toml` (add `openai` dependency)
- Create: `backend/app/assistant/__init__.py` (empty)
- Create: `backend/app/assistant/client.py`
- Modify: `backend/app/container.py` (add `ai_provider_client` cached property, accept constructor override)
- Modify: `backend/app/services/provider_profiles.py` (add `probe_capabilities`)
- Modify: `backend/app/api/provider_profiles.py` (add `POST /provider-profiles/{id}/probe`)
- Test: `backend/tests/unit/test_assistant_client.py`
- Test: Modify `backend/tests/integration/test_provider_profiles_api.py` (probe endpoint, using a fake client)

**Interfaces:**
- Consumes: `ProviderProfile`/`ProviderProfileService` (Task 1).
- Produces: `ChatMessage`, `ToolSchema`, `ToolCallRequest`, `ChatChunk`, `ProviderCapabilities`, `AIProviderConnectionError`, `AIProviderClient` (Protocol: `probe_capabilities(*, base_url, api_key, model_id) -> ProviderCapabilities`, `stream_chat(*, base_url, api_key, model_id, messages, tools) -> AsyncIterator[ChatChunk]`), `OpenAICompatibleClient` (real implementation). Tasks 5, 7, 8 depend on this Protocol; test doubles for those tasks implement the same Protocol as a `FakeAIProviderClient`, following this codebase's existing `FakeBatfishClient` pattern.

- [ ] **Step 1: Add the dependency**

In `backend/pyproject.toml`, add `"openai>=1.50,<2"` to the main dependency list, next to `"httpx==0.28.1"`. Confirm `pytest-asyncio` is already a dev dependency (this codebase's FastAPI app is async, so it almost certainly is); if it's missing, add `"pytest-asyncio"` to the dev dependency group and an `asyncio_mode = "auto"` (or matching existing convention) entry under `[tool.pytest.ini_options]`.

Run: `cd backend && uv sync`

- [ ] **Step 2: Write the failing client test**

```python
# backend/tests/unit/test_assistant_client.py
from __future__ import annotations

import json

import httpx
import pytest

from app.assistant.client import AIProviderConnectionError, ChatMessage, OpenAICompatibleClient


def _sse_body(chunks: list[dict[str, object]]) -> bytes:
    body = ""
    for chunk in chunks:
        body += f"data: {json.dumps(chunk)}\n\n"
    body += "data: [DONE]\n\n"
    return body.encode("utf-8")


@pytest.mark.asyncio
async def test_stream_chat_yields_tokens_then_done() -> None:
    chunks = [
        {"id": "1", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"content": "Hel"}}]},
        {"id": "1", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"content": "lo"}}]},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse_body(chunks), headers={"content-type": "text/event-stream"})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = OpenAICompatibleClient(http_client=http_client)

    received = [
        chunk
        async for chunk in client.stream_chat(
            base_url="http://fake/v1",
            api_key=None,
            model_id="test-model",
            messages=[ChatMessage(role="user", content="hi")],
            tools=None,
        )
    ]

    assert [c.content for c in received if c.type == "token"] == ["Hel", "lo"]
    assert received[-1].type == "done"


@pytest.mark.asyncio
async def test_stream_chat_raises_connection_error_on_network_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = OpenAICompatibleClient(http_client=http_client)

    with pytest.raises(AIProviderConnectionError):
        async for _chunk in client.stream_chat(
            base_url="http://fake/v1",
            api_key=None,
            model_id="test-model",
            messages=[ChatMessage(role="user", content="hi")],
            tools=None,
        ):
            pass


@pytest.mark.asyncio
async def test_probe_capabilities_reports_tool_calling_support() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "1",
                "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "pong"}, "finish_reason": "stop"}],
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = OpenAICompatibleClient(http_client=http_client)

    capabilities = await client.probe_capabilities(base_url="http://fake/v1", api_key=None, model_id="test-model")

    assert capabilities.supports_streaming is True
    assert capabilities.supports_tool_calling is True


@pytest.mark.asyncio
async def test_probe_capabilities_falls_back_when_tools_param_rejected() -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(400, json={"error": {"message": "tools not supported"}})
        return httpx.Response(
            200,
            json={
                "id": "1",
                "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "pong"}, "finish_reason": "stop"}],
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = OpenAICompatibleClient(http_client=http_client)

    capabilities = await client.probe_capabilities(base_url="http://fake/v1", api_key=None, model_id="test-model")

    assert capabilities.supports_tool_calling is False
    assert capabilities.supports_streaming is True
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_assistant_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.assistant'`.

- [ ] **Step 4: Write the client**

Create `backend/app/assistant/__init__.py` (empty).

Create `backend/app/assistant/client.py`:

```python
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol

import httpx
from openai import APIConnectionError, APIStatusError, AsyncOpenAI
from pydantic import BaseModel

_PROBE_TOOL = {
    "type": "function",
    "function": {
        "name": "_capability_probe",
        "description": "Unused -- presence alone tests whether the endpoint accepts tool schemas.",
        "parameters": {"type": "object", "properties": {}},
    },
}


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None


class ToolSchema(BaseModel):
    name: str
    description: str
    parameters: dict[str, object]


@dataclass(frozen=True, slots=True)
class ToolCallRequest:
    id: str
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True, slots=True)
class ChatChunk:
    type: Literal["token", "tool_call", "done"]
    content: str | None = None
    tool_call: ToolCallRequest | None = None


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    supports_streaming: bool
    supports_tool_calling: bool


class AIProviderConnectionError(Exception):
    pass


class AIProviderClient(Protocol):
    async def probe_capabilities(
        self, *, base_url: str, api_key: str | None, model_id: str
    ) -> ProviderCapabilities: ...

    def stream_chat(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model_id: str,
        messages: list[ChatMessage],
        tools: list[ToolSchema] | None,
    ) -> AsyncIterator[ChatChunk]: ...


def _to_openai_tool(tool: ToolSchema) -> dict[str, object]:
    return {
        "type": "function",
        "function": {"name": tool.name, "description": tool.description, "parameters": tool.parameters},
    }


class OpenAICompatibleClient:
    """Thin translation layer over the official openai SDK, pointed at a
    caller-supplied base_url. This process never runs or bundles a model --
    every call is a proxy to whatever endpoint the ProviderProfile names."""

    def __init__(self, *, http_client: httpx.AsyncClient | None = None) -> None:
        self._http_client = http_client

    def _client(self, *, base_url: str, api_key: str | None) -> AsyncOpenAI:
        return AsyncOpenAI(base_url=base_url, api_key=api_key or "not-required", http_client=self._http_client)

    async def probe_capabilities(
        self, *, base_url: str, api_key: str | None, model_id: str
    ) -> ProviderCapabilities:
        client = self._client(base_url=base_url, api_key=api_key)
        try:
            await client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                tools=[_PROBE_TOOL],
                tool_choice="none",
            )
        except APIConnectionError as exc:
            raise AIProviderConnectionError(str(exc)) from exc
        except APIStatusError as exc:
            if exc.status_code in (400, 404, 422):
                return await self._probe_without_tools(client, model_id)
            raise AIProviderConnectionError(str(exc)) from exc
        return ProviderCapabilities(supports_streaming=True, supports_tool_calling=True)

    async def _probe_without_tools(self, client: AsyncOpenAI, model_id: str) -> ProviderCapabilities:
        try:
            await client.chat.completions.create(
                model=model_id, messages=[{"role": "user", "content": "ping"}], max_tokens=1
            )
        except (APIConnectionError, APIStatusError) as exc:
            raise AIProviderConnectionError(str(exc)) from exc
        return ProviderCapabilities(supports_streaming=True, supports_tool_calling=False)

    async def stream_chat(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model_id: str,
        messages: list[ChatMessage],
        tools: list[ToolSchema] | None,
    ) -> AsyncIterator[ChatChunk]:
        client = self._client(base_url=base_url, api_key=api_key)
        payload_messages = [m.model_dump(exclude_none=True) for m in messages]
        kwargs: dict[str, object] = {"model": model_id, "messages": payload_messages, "stream": True}
        if tools:
            kwargs["tools"] = [_to_openai_tool(t) for t in tools]
        try:
            stream = await client.chat.completions.create(**kwargs)
            async for event in stream:
                delta = event.choices[0].delta
                if delta.content:
                    yield ChatChunk(type="token", content=delta.content)
                if delta.tool_calls:
                    for call in delta.tool_calls:
                        if call.function is None:
                            continue
                        yield ChatChunk(
                            type="tool_call",
                            tool_call=ToolCallRequest(
                                id=call.id or "",
                                name=call.function.name or "",
                                arguments=json.loads(call.function.arguments or "{}"),
                            ),
                        )
        except APIConnectionError as exc:
            raise AIProviderConnectionError(str(exc)) from exc
        yield ChatChunk(type="done")
```

- [ ] **Step 5: Run the client tests**

Run: `cd backend && uv run pytest tests/unit/test_assistant_client.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Wire the container and add the probe endpoint**

In `backend/app/container.py`, add next to `analysis_client`'s `@cached_property`:

```python
    @cached_property
    def ai_provider_client(self) -> AIProviderClient:
        return OpenAICompatibleClient()
```

Add `ai_provider_client: AIProviderClient | None = None` to `ApplicationContainer.__init__`'s parameters (matching how `analysis_client` is accepted as an optional override for tests), storing it and falling back to the `@cached_property` only when not supplied.

In `backend/app/services/provider_profiles.py`, add to `ProviderProfileService`:

```python
    async def probe_capabilities(self, profile_id: UUID, client: AIProviderClient) -> ProviderProfile:
        profile = self._repository.get(profile_id, for_update=True)
        material = self._vault.decrypt(profile)
        capabilities = await client.probe_capabilities(
            base_url=profile.base_url, api_key=material.api_key, model_id=profile.model_id
        )
        profile.supports_streaming = capabilities.supports_streaming
        profile.supports_tool_calling = capabilities.supports_tool_calling
        return profile
```

(`AIProviderConnectionError` propagates uncaught to the router, which maps it to a 502 -- see the router addition below.)

In `backend/app/api/provider_profiles.py`, add:

```python
from app.assistant.client import AIProviderConnectionError


@router.post("/{profile_id}/probe", response_model=ProviderProfileView)
async def probe_profile(
    profile_id: UUID,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    try:
        profile = await _service(session, container).probe_capabilities(profile_id, container.ai_provider_client)
    except AIProviderConnectionError as exc:
        raise HTTPException(status_code=502, detail="Could not reach the configured endpoint") from exc
    session.commit()
    return _view(profile)
```

(Import `HTTPException` from `fastapi` at the top of the file.)

- [ ] **Step 7: Add an integration test for the probe endpoint using a fake client**

Add to `backend/tests/integration/test_provider_profiles_api.py`:

```python
class _FakeProviderClient:
    async def probe_capabilities(self, *, base_url: str, api_key: str | None, model_id: str):
        from app.assistant.client import ProviderCapabilities

        return ProviderCapabilities(supports_streaming=True, supports_tool_calling=True)

    async def stream_chat(self, **_kwargs):
        return
        yield  # pragma: no cover -- makes this an async generator; unused here


def test_probe_updates_capability_flags(client: TestClient, container) -> None:
    container.ai_provider_client = _FakeProviderClient()
    create = client.post(
        "/api/provider-profiles",
        json={"name": "Probed", "base_url": "http://localhost:11434/v1", "model_id": "llama3.1"},
    )
    profile_id = create.json()["id"]

    probed = client.post(f"/api/provider-profiles/{profile_id}/probe")
    assert probed.status_code == 200, probed.text
    assert probed.json()["supports_streaming"] is True
    assert probed.json()["supports_tool_calling"] is True
```

Run: `cd backend && uv run pytest tests/integration/test_provider_profiles_api.py backend/tests/unit/test_assistant_client.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/app/assistant/ \
  backend/app/container.py backend/app/services/provider_profiles.py \
  backend/app/api/provider_profiles.py \
  backend/tests/unit/test_assistant_client.py backend/tests/integration/test_provider_profiles_api.py
git commit -m "feat: add OpenAI-compatible provider client and capability probe"
```

---

## Task 5: Read-only tool registry

**Files:**
- Create: `backend/app/assistant/tools.py`
- Test: `backend/tests/unit/test_assistant_tools.py`

**Interfaces:**
- Consumes: `ToolSchema` (Task 4); `DeviceService.get`, `DeviceService.list_interfaces`, `DeviceService.list_neighbors` (`app/services/devices.py:489,492`, and `.get` used the same way `app/api/devices.py:145` uses it); `SnapshotService.list(*, device_id=None, limit=100)` (`app/services/snapshots.py:79`); `EventRepository(session).list(device_id=None, job_id=None, limit=100)` (`app/repositories/events.py`, called exactly this way in `app/api/events.py:22`); response schemas `FactsView`, `InterfaceView`, `NeighborView` (`app/schemas/devices.py`), `ConfigSnapshotView` (`app/schemas/snapshots.py` — the metadata-only variant, not `ConfigSnapshotContentView`, so raw config text never enters AI context), `EventView` (`app/schemas/events.py`).
- Produces: `READ_ONLY_TOOLS: tuple[ToolSchema, ...]` (5 tools, no write tool — ever); `ToolDispatcher(devices, snapshots, events)` with `.dispatch(name, arguments) -> ToolResult`; `ReadOnlyToolError`. Task 7 (chat service) is the only consumer.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_assistant_tools.py
from __future__ import annotations

from uuid import uuid4

import pytest

from app.assistant.tools import READ_ONLY_TOOLS, ReadOnlyToolError, ToolDispatcher


def test_read_only_tools_never_include_a_write_tool() -> None:
    write_markers = ("apply", "delete", "create", "update", "set", "write", "send")
    for tool in READ_ONLY_TOOLS:
        lowered_name = tool.name.lower()
        assert not any(marker in lowered_name for marker in write_markers), tool.name


def test_dispatch_facts_returns_device_facts(monkeypatch: pytest.MonkeyPatch) -> None:
    device_id = uuid4()

    class _FakeDevice:
        facts = {"hostname": "edge-01"}
        last_seen_at = None

    class _FakeDevices:
        def get(self, requested_id):
            assert requested_id == device_id
            return _FakeDevice()

        def list_interfaces(self, requested_id):
            raise AssertionError("not called")

        def list_neighbors(self, requested_id):
            raise AssertionError("not called")

    dispatcher = ToolDispatcher(devices=_FakeDevices(), snapshots=None, events=None)  # type: ignore[arg-type]
    result = dispatcher.dispatch("get_device_facts", {"device_id": str(device_id)})

    assert result.name == "get_device_facts"
    assert result.payload["facts"] == {"hostname": "edge-01"}


def test_dispatch_rejects_missing_device_id() -> None:
    dispatcher = ToolDispatcher(devices=None, snapshots=None, events=None)  # type: ignore[arg-type]
    with pytest.raises(ReadOnlyToolError):
        dispatcher.dispatch("get_device_facts", {})


def test_dispatch_unknown_tool_raises() -> None:
    dispatcher = ToolDispatcher(devices=None, snapshots=None, events=None)  # type: ignore[arg-type]
    with pytest.raises(ReadOnlyToolError):
        dispatcher.dispatch("apply_change_plan", {"device_id": str(uuid4())})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_assistant_tools.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.assistant.tools'`.

- [ ] **Step 3: Write the tool registry**

```python
# backend/app/assistant/tools.py
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.assistant.client import ToolSchema
from app.repositories.events import EventRepository
from app.schemas.devices import FactsView, InterfaceView, NeighborView
from app.schemas.events import EventView
from app.schemas.snapshots import ConfigSnapshotView
from app.services.devices import DeviceService
from app.services.snapshots import SnapshotService


class ReadOnlyToolError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ToolResult:
    name: str
    payload: dict[str, object]


_DEVICE_ID_PARAM = {"device_id": {"type": "string", "format": "uuid"}}

_FACTS_TOOL = ToolSchema(
    name="get_device_facts",
    description="Read a registered device's last-observed platform facts.",
    parameters={"type": "object", "properties": _DEVICE_ID_PARAM, "required": ["device_id"]},
)
_INTERFACES_TOOL = ToolSchema(
    name="get_device_interfaces",
    description="Read a registered device's last-observed interface inventory.",
    parameters={"type": "object", "properties": _DEVICE_ID_PARAM, "required": ["device_id"]},
)
_NEIGHBORS_TOOL = ToolSchema(
    name="get_device_neighbors",
    description="Read a registered device's last-observed CDP/LLDP neighbors.",
    parameters={"type": "object", "properties": _DEVICE_ID_PARAM, "required": ["device_id"]},
)
_SNAPSHOTS_TOOL = ToolSchema(
    name="list_config_snapshots",
    description="List recent configuration snapshot metadata for a device. Never returns raw config content.",
    parameters={
        "type": "object",
        "properties": {**_DEVICE_ID_PARAM, "limit": {"type": "integer"}},
        "required": ["device_id"],
    },
)
_EVENTS_TOOL = ToolSchema(
    name="list_device_events",
    description="List recent sanitized event-timeline entries for a device.",
    parameters={
        "type": "object",
        "properties": {**_DEVICE_ID_PARAM, "limit": {"type": "integer"}},
        "required": ["device_id"],
    },
)

# There is no write tool defined anywhere in this module, in either Confirm
# or Auto mode -- see spec docs/superpowers/specs/2026-08-24-phase-4-ai-assistant-design.md §6.
READ_ONLY_TOOLS: tuple[ToolSchema, ...] = (
    _FACTS_TOOL,
    _INTERFACES_TOOL,
    _NEIGHBORS_TOOL,
    _SNAPSHOTS_TOOL,
    _EVENTS_TOOL,
)


class ToolDispatcher:
    def __init__(self, *, devices: DeviceService, snapshots: SnapshotService, events: EventRepository) -> None:
        self._devices = devices
        self._snapshots = snapshots
        self._events = events

    def dispatch(self, name: str, arguments: dict[str, object]) -> ToolResult:
        device_id = self._require_device_id(arguments)
        if name == _FACTS_TOOL.name:
            device = self._devices.get(device_id)
            view = FactsView(device_id=device_id, facts=device.facts, last_seen_at=device.last_seen_at)
            return ToolResult(name=name, payload=view.model_dump(mode="json"))
        if name == _INTERFACES_TOOL.name:
            interfaces = self._devices.list_interfaces(device_id)
            return ToolResult(
                name=name,
                payload={"interfaces": [InterfaceView.model_validate(i).model_dump(mode="json") for i in interfaces]},
            )
        if name == _NEIGHBORS_TOOL.name:
            neighbors = self._devices.list_neighbors(device_id)
            return ToolResult(
                name=name,
                payload={"neighbors": [NeighborView.model_validate(n).model_dump(mode="json") for n in neighbors]},
            )
        if name == _SNAPSHOTS_TOOL.name:
            limit = int(arguments.get("limit", 20))
            snapshots = self._snapshots.list(device_id=device_id, limit=limit)
            return ToolResult(
                name=name,
                payload={"snapshots": [ConfigSnapshotView.model_validate(s).model_dump(mode="json") for s in snapshots]},
            )
        if name == _EVENTS_TOOL.name:
            limit = int(arguments.get("limit", 20))
            events = self._events.list(device_id=device_id, limit=limit)
            return ToolResult(
                name=name,
                payload={"events": [EventView.model_validate(e).model_dump(mode="json") for e in events]},
            )
        raise ReadOnlyToolError(f"Unknown or unavailable tool: {name}")

    @staticmethod
    def _require_device_id(arguments: dict[str, object]) -> UUID:
        raw = arguments.get("device_id")
        if not isinstance(raw, str):
            raise ReadOnlyToolError("device_id is required")
        try:
            return UUID(raw)
        except ValueError as exc:
            raise ReadOnlyToolError("device_id must be a UUID") from exc
```

Confirm the exact field name on `EventView`/`Event` used for its type discriminator (`event_type` vs `type`) by checking `backend/app/schemas/events.py` before finalizing this file — `model_validate(e).model_dump(mode="json")` is shape-agnostic and doesn't require knowing the field name in advance, so this only matters if you hand-serialize instead.

- [ ] **Step 4: Run the tests**

Run: `cd backend && uv run pytest tests/unit/test_assistant_tools.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/assistant/tools.py backend/tests/unit/test_assistant_tools.py
git commit -m "feat: add read-only tool registry for the AI assistant"
```

---

## Task 6: Context sanitizer

**Files:**
- Create: `backend/app/assistant/sanitize.py`
- Test: `backend/tests/unit/test_assistant_sanitize.py`

**Interfaces:**
- Produces: `scrub_secrets(payload: object) -> object`. Task 7 (chat service) applies this to every `ToolResult.payload` before it is serialized into a `ChatMessage` sent back to the model.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_assistant_sanitize.py
from __future__ import annotations

from app.assistant.sanitize import scrub_secrets


def test_scrub_secrets_removes_credential_shaped_keys() -> None:
    payload = {
        "facts": {"hostname": "r1"},
        "encrypted_secret": "abc",
        "nested": {"api_key": "xyz", "ok": 1},
    }
    assert scrub_secrets(payload) == {"facts": {"hostname": "r1"}, "nested": {"ok": 1}}


def test_scrub_secrets_handles_lists_and_scalars() -> None:
    assert scrub_secrets([{"password": "x", "name": "a"}]) == [{"name": "a"}]
    assert scrub_secrets("plain string") == "plain string"
    assert scrub_secrets(42) == 42


def test_scrub_secrets_is_case_insensitive() -> None:
    assert scrub_secrets({"API_Key": "x", "Token": "y", "ok": 1}) == {"ok": 1}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_assistant_sanitize.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write the sanitizer**

```python
# backend/app/assistant/sanitize.py
from __future__ import annotations

_SECRET_KEY_MARKERS = ("password", "secret", "api_key", "apikey", "token", "encrypted_")


def scrub_secrets(payload: object) -> object:
    """Recursively strips any dict key that looks credential-shaped before
    a tool result is serialized into AI context. Defense in depth: every
    read-only tool in app/assistant/tools.py already builds its payload
    from the same APIModel view schemas already served over the public
    REST API (never raw ORM rows or vault-decrypted material), so this
    should never actually find anything on the tools shipped today -- it
    exists to catch a future tool added without that discipline."""
    if isinstance(payload, dict):
        return {key: scrub_secrets(value) for key, value in payload.items() if not _looks_like_secret_key(key)}
    if isinstance(payload, list):
        return [scrub_secrets(item) for item in payload]
    return payload


def _looks_like_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _SECRET_KEY_MARKERS)
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && uv run pytest tests/unit/test_assistant_sanitize.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/assistant/sanitize.py backend/tests/unit/test_assistant_sanitize.py
git commit -m "feat: add defense-in-depth secret scrubbing for AI tool results"
```

---

## Task 7: Chat service + WebSocket endpoint

**Files:**
- Create: `backend/app/assistant/service.py`
- Create: `backend/app/api/assistant.py`
- Modify: `backend/app/core/errors.py` (add `AutoModeRequiresAcknowledgmentError`)
- Modify: `backend/app/main.py` (register the new WebSocket router, mirroring `terminal_router`)
- Test: `backend/tests/unit/test_assistant_service.py`
- Test: `backend/tests/integration/test_assistant_websocket.py`

**Interfaces:**
- Consumes: `AIProviderClient`, `ChatMessage`, `ToolCallRequest` (Task 4); `READ_ONLY_TOOLS`, `ToolDispatcher`, `ReadOnlyToolError` (Task 5); `scrub_secrets` (Task 6); `AssistantSessionRepository`, `AssistantMessageRepository` (Task 2); `ProviderProfileRepository`, `ProviderKeyVault` (Task 1); the WebSocket auth/origin-check pattern from `app/api/terminal.py:341-351`.
- Produces: `AssistantEvent` (`type: Literal["token","tool_call","tool_result","done","error"]`, `content`, `tool_name`, `tool_payload`, `error_code`); `AssistantChatService.handle_user_message(session_id, content) -> AsyncIterator[AssistantEvent]`, `.set_mode(session_id, mode, *, risk_acknowledged) -> AssistantSession`; the `/ws/assistant/{session_id}` endpoint. Tasks 8 and 9 extend `handle_user_message`'s tool-result branch and the final-reply branch respectively — both are named, real extension points in this task's code, not placeholders.

- [ ] **Step 1: Write the failing service test**

```python
# backend/tests/unit/test_assistant_service.py
from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest

from app.assistant.client import ChatChunk, ChatMessage, ToolCallRequest, ToolSchema
from app.assistant.service import AssistantChatService
from app.assistant.tools import ReadOnlyToolError, ToolResult
from app.models import AssistantMessageRole, AssistantSessionMode


class _FakeSessions:
    def __init__(self, chat_session):
        self._chat_session = chat_session

    def get(self, session_id, *, for_update: bool = False):
        return self._chat_session

    def set_mode(self, chat_session, mode):
        chat_session.mode = mode


class _FakeMessages:
    def __init__(self):
        self.added: list[dict[str, object]] = []

    def add(self, *, session_id, role, content, tool_calls=None, tool_results=None):
        self.added.append({"role": role, "content": content})

    def list_for_session(self, session_id):
        return []


class _FakeProfiles:
    def __init__(self, profile):
        self._profile = profile

    def get(self, profile_id):
        return self._profile


class _FakeVault:
    def decrypt(self, profile):
        from app.services.provider_profiles import ProviderKeyMaterial

        return ProviderKeyMaterial(api_key=None)


class _FakeProviderClient:
    def __init__(self, rounds: list[list[ChatChunk]]):
        self._rounds = rounds
        self.calls = 0

    async def probe_capabilities(self, **_kwargs):
        raise AssertionError("not used")

    async def stream_chat(self, **_kwargs) -> AsyncIterator[ChatChunk]:
        chunks = self._rounds[self.calls]
        self.calls += 1
        for chunk in chunks:
            yield chunk


class _FakeToolDispatcher:
    def dispatch(self, name, arguments):
        if name == "boom":
            raise ReadOnlyToolError("no such device")
        return ToolResult(name=name, payload={"facts": {"hostname": "r1"}})


def _profile():
    class _Profile:
        id = uuid4()
        base_url = "http://fake/v1"
        model_id = "test-model"
        supports_tool_calling = True

    return _Profile()


def _session():
    class _Session:
        id = uuid4()
        provider_profile_id = uuid4()
        mode = AssistantSessionMode.CONFIRM

    return _Session()


@pytest.mark.asyncio
async def test_handle_user_message_streams_tokens_then_done() -> None:
    provider = _FakeProviderClient([[ChatChunk(type="token", content="Hi"), ChatChunk(type="token", content="!")]])
    service = AssistantChatService(
        session=None,  # type: ignore[arg-type]
        provider_client=provider,
        sessions=_FakeSessions(_session()),
        messages=_FakeMessages(),
        profiles=_FakeProfiles(_profile()),
        vault=_FakeVault(),
        tools=_FakeToolDispatcher(),  # type: ignore[arg-type]
    )

    events = [e async for e in service.handle_user_message(uuid4(), "hello")]

    assert [e.content for e in events if e.type == "token"] == ["Hi", "!"]
    assert events[-1].type == "done"


@pytest.mark.asyncio
async def test_handle_user_message_dispatches_a_tool_call_then_continues() -> None:
    provider = _FakeProviderClient(
        [
            [ChatChunk(type="tool_call", tool_call=ToolCallRequest(id="1", name="get_device_facts", arguments={"device_id": "x"}))],
            [ChatChunk(type="token", content="Done")],
        ]
    )
    service = AssistantChatService(
        session=None,  # type: ignore[arg-type]
        provider_client=provider,
        sessions=_FakeSessions(_session()),
        messages=_FakeMessages(),
        profiles=_FakeProfiles(_profile()),
        vault=_FakeVault(),
        tools=_FakeToolDispatcher(),  # type: ignore[arg-type]
    )

    events = [e async for e in service.handle_user_message(uuid4(), "check the device")]

    tool_events = [e for e in events if e.type == "tool_result"]
    assert len(tool_events) == 1
    assert tool_events[0].tool_payload == {"facts": {"hostname": "r1"}}
    assert provider.calls == 2
    assert events[-1].type == "done"


@pytest.mark.asyncio
async def test_handle_user_message_reports_tool_errors_without_crashing() -> None:
    provider = _FakeProviderClient(
        [
            [ChatChunk(type="tool_call", tool_call=ToolCallRequest(id="1", name="boom", arguments={"device_id": "x"}))],
            [ChatChunk(type="token", content="Sorry")],
        ]
    )
    service = AssistantChatService(
        session=None,  # type: ignore[arg-type]
        provider_client=provider,
        sessions=_FakeSessions(_session()),
        messages=_FakeMessages(),
        profiles=_FakeProfiles(_profile()),
        vault=_FakeVault(),
        tools=_FakeToolDispatcher(),  # type: ignore[arg-type]
    )

    events = [e async for e in service.handle_user_message(uuid4(), "check a bad device")]

    tool_events = [e for e in events if e.type == "tool_result"]
    assert tool_events[0].tool_payload == {"error": "no such device"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_assistant_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.assistant.service'`.

- [ ] **Step 3: Write the error class**

In `backend/app/core/errors.py`, add:

```python
class AutoModeRequiresAcknowledgmentError(AppError):
    code = "auto_mode_requires_acknowledgment"
    status_code = 409
    default_message = "Confirm the risk before enabling Auto mode"
```

- [ ] **Step 4: Write the chat service**

```python
# backend/app/assistant/service.py
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy.orm import Session

from app.assistant.client import AIProviderClient, ChatMessage, ToolCallRequest
from app.assistant.sanitize import scrub_secrets
from app.assistant.tools import READ_ONLY_TOOLS, ReadOnlyToolError, ToolDispatcher
from app.core.errors import AutoModeRequiresAcknowledgmentError
from app.models import AssistantMessageRole, AssistantSessionMode
from app.repositories.assistant import AssistantMessageRepository, AssistantSessionRepository
from app.repositories.provider_profiles import ProviderProfileRepository
from app.services.provider_profiles import ProviderKeyVault

_MAX_TOOL_ROUNDS_PER_TURN = 5


@dataclass(frozen=True, slots=True)
class AssistantEvent:
    type: Literal["token", "tool_call", "tool_result", "done", "error"]
    content: str | None = None
    tool_name: str | None = None
    tool_payload: dict[str, object] | None = None
    error_code: str | None = None


class AssistantChatService:
    def __init__(
        self,
        session: Session,
        *,
        provider_client: AIProviderClient,
        sessions: AssistantSessionRepository,
        messages: AssistantMessageRepository,
        profiles: ProviderProfileRepository,
        vault: ProviderKeyVault,
        tools: ToolDispatcher,
    ) -> None:
        self._session = session
        self._provider_client = provider_client
        self._sessions = sessions
        self._messages = messages
        self._profiles = profiles
        self._vault = vault
        self._tools = tools

    async def handle_user_message(self, session_id: UUID, content: str) -> AsyncIterator[AssistantEvent]:
        chat_session = self._sessions.get(session_id)
        profile = self._profiles.get(chat_session.provider_profile_id)
        material = self._vault.decrypt(profile)

        self._messages.add(session_id=session_id, role=AssistantMessageRole.USER, content=content)
        self._session.commit()

        history = self._build_history(session_id)
        tool_schemas = list(READ_ONLY_TOOLS) if profile.supports_tool_calling else None

        for _round in range(_MAX_TOOL_ROUNDS_PER_TURN):
            reply_text = ""
            pending_tool_calls: list[ToolCallRequest] = []
            async for chunk in self._provider_client.stream_chat(
                base_url=profile.base_url,
                api_key=material.api_key,
                model_id=profile.model_id,
                messages=history,
                tools=tool_schemas,
            ):
                if chunk.type == "token" and chunk.content:
                    reply_text += chunk.content
                    yield AssistantEvent(type="token", content=chunk.content)
                elif chunk.type == "tool_call" and chunk.tool_call is not None:
                    pending_tool_calls.append(chunk.tool_call)

            if reply_text:
                self._messages.add(session_id=session_id, role=AssistantMessageRole.ASSISTANT, content=reply_text)
                self._session.commit()
                history.append(ChatMessage(role="assistant", content=reply_text))

            if not pending_tool_calls:
                yield AssistantEvent(type="done")
                return

            for call in pending_tool_calls:
                yield AssistantEvent(type="tool_call", tool_name=call.name, tool_payload=call.arguments)
                try:
                    result = self._tools.dispatch(call.name, call.arguments)
                    payload = scrub_secrets(result.payload)
                except ReadOnlyToolError as exc:
                    payload = {"error": str(exc)}
                assert isinstance(payload, dict)
                yield AssistantEvent(type="tool_result", tool_name=call.name, tool_payload=payload)
                self._messages.add(
                    session_id=session_id,
                    role=AssistantMessageRole.TOOL,
                    content=json.dumps(payload),
                    tool_results=payload,
                )
                self._session.commit()
                history.append(ChatMessage(role="tool", content=json.dumps(payload), tool_call_id=call.id))

        yield AssistantEvent(
            type="error",
            error_code="tool_round_limit_exceeded",
            content="The assistant made too many tool calls in one turn and was stopped.",
        )

    def _build_history(self, session_id: UUID) -> list[ChatMessage]:
        stored = self._messages.list_for_session(session_id)
        return [ChatMessage(role=m.role.value, content=m.content) for m in stored]

    def set_mode(self, session_id: UUID, mode: AssistantSessionMode, *, risk_acknowledged: bool) -> object:
        chat_session = self._sessions.get(session_id, for_update=True)
        if mode is AssistantSessionMode.AUTO and not risk_acknowledged:
            raise AutoModeRequiresAcknowledgmentError()
        self._sessions.set_mode(chat_session, mode)
        self._session.commit()
        return chat_session
```

- [ ] **Step 5: Run the service tests**

Run: `cd backend && uv run pytest tests/unit/test_assistant_service.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Write the WebSocket endpoint**

```python
# backend/app/api/assistant.py
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.assistant.service import AssistantChatService, AssistantEvent
from app.assistant.tools import ToolDispatcher
from app.core.errors import AutoModeRequiresAcknowledgmentError
from app.models import AssistantSessionMode
from app.repositories.assistant import AssistantMessageRepository, AssistantSessionRepository
from app.repositories.events import EventRepository
from app.repositories.provider_profiles import ProviderProfileRepository
from app.services.devices import DeviceService
from app.services.snapshots import SnapshotService

router = APIRouter()


def _event_to_frame(event: AssistantEvent) -> dict[str, object]:
    frame: dict[str, object] = {"type": event.type}
    if event.content is not None:
        frame["content"] = event.content
    if event.tool_name is not None:
        frame["tool"] = event.tool_name
    if event.tool_payload is not None:
        frame["payload"] = event.tool_payload
    if event.error_code is not None:
        frame["code"] = event.error_code
    return frame


@router.websocket("/ws/assistant/{session_id}")
async def assistant_chat(websocket: WebSocket, session_id: str) -> None:
    container = websocket.app.state.container
    if not container.settings.ai_gateway_enabled:
        await websocket.close(code=4403, reason="AI gateway disabled by policy")
        return
    token = websocket.cookies.get(container.settings.session_cookie_name)
    if token is None or container.session_tokens.verify(token) is None:
        await websocket.close(code=4401, reason="Authentication required")
        return
    origin = websocket.headers.get("origin")
    if origin is None or origin.rstrip("/") not in container.settings.trusted_origins():
        await websocket.close(code=4403, reason="Origin rejected")
        return

    await websocket.accept()
    try:
        session_uuid = UUID(session_id)
    except ValueError:
        await websocket.close(code=4400, reason="Invalid session id")
        return

    with container.session_factory() as db_session:
        service = AssistantChatService(
            db_session,
            provider_client=container.ai_provider_client,
            sessions=AssistantSessionRepository(db_session),
            messages=AssistantMessageRepository(db_session),
            profiles=ProviderProfileRepository(db_session),
            vault=container.provider_key_vault,
            tools=ToolDispatcher(
                devices=DeviceService(
                    db_session,
                    settings=container.settings,
                    drivers=container.drivers,
                    vault=container.credential_vault,
                    host_key_trust=container.host_key_trust,
                ),
                snapshots=SnapshotService(
                    db_session, store=container.snapshot_store, devices=DeviceService(
                        db_session, settings=container.settings, drivers=container.drivers,
                        vault=container.credential_vault, host_key_trust=container.host_key_trust,
                    ), drivers=container.drivers,
                ),
                events=EventRepository(db_session),
            ),
        )
        try:
            while True:
                message = await websocket.receive_json()
                message_type = message.get("type")
                if message_type == "user_message":
                    content = message.get("content")
                    if not isinstance(content, str) or not content.strip():
                        await websocket.send_json({"type": "error", "code": "invalid_message", "message": "content is required"})
                        continue
                    async for event in service.handle_user_message(session_uuid, content):
                        await websocket.send_json(_event_to_frame(event))
                elif message_type == "set_mode":
                    mode_value = message.get("mode")
                    risk_acknowledged = bool(message.get("risk_acknowledged", False))
                    try:
                        service.set_mode(session_uuid, AssistantSessionMode(mode_value), risk_acknowledged=risk_acknowledged)
                        await websocket.send_json({"type": "mode_changed", "mode": mode_value})
                    except AutoModeRequiresAcknowledgmentError:
                        await websocket.send_json(
                            {"type": "error", "code": "auto_mode_requires_acknowledgment", "message": "Confirm the risk before enabling Auto mode"}
                        )
                    except ValueError:
                        await websocket.send_json({"type": "error", "code": "invalid_message", "message": "unknown mode"})
                else:
                    await websocket.send_json({"type": "error", "code": "invalid_message", "message": "unknown message type"})
        except WebSocketDisconnect:
            return
```

`DeviceService`'s exact constructor keyword set (`settings`, `drivers`, `vault`, `host_key_trust`, ...) was only partially observed via `app/api/devices.py:27-33`'s `_service()` helper — read that helper's full body before finalizing this step and match every keyword it passes, since a missing required keyword is a hard failure at request time, not a silent gap. Reuse that exact helper (import and call `devices._service`-style construction, or factor a shared constructor helper into `app/services/devices.py` if one doesn't already exist) rather than re-deriving the keyword list twice by hand as written above.

In `backend/app/main.py`, add next to `terminal_router`:

```python
from app.api.assistant import router as assistant_router
...
    application.include_router(assistant_router)
```

- [ ] **Step 7: Write a WebSocket integration test**

```python
# backend/tests/integration/test_assistant_websocket.py
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _enable_ai_gateway(settings):
    settings.ai_gateway_enabled = True


def test_assistant_chat_streams_a_reply(client: TestClient, authenticated_cookies, container) -> None:
    from app.assistant.client import ChatChunk

    class _FakeClient:
        async def probe_capabilities(self, **_kwargs):
            raise AssertionError("not used")

        async def stream_chat(self, **_kwargs):
            yield ChatChunk(type="token", content="Hello")
            yield ChatChunk(type="token", content=" there")

    container.ai_provider_client = _FakeClient()

    profile = client.post(
        "/api/provider-profiles",
        json={"name": "Local", "base_url": "http://localhost:11434/v1", "model_id": "llama3.1"},
    ).json()
    chat_session_id = ...  # created via whatever session-creation path Task 11's frontend/Task 7 backend exposes

    with client.websocket_connect(f"/ws/assistant/{chat_session_id}", cookies=authenticated_cookies) as ws:
        ws.send_json({"type": "user_message", "content": "hi"})
        frames = [ws.receive_json() for _ in range(3)]

    assert [f["content"] for f in frames if f["type"] == "token"] == ["Hello", " there"]
    assert frames[-1]["type"] == "done"
```

This test needs an `AssistantSession` row to exist before it can connect — either add a minimal `POST /api/assistant-sessions` endpoint as part of this task (`AssistantSessionCreate`/`AssistantSessionView` schemas already exist from Task 2) or create the row directly via `AssistantSessionRepository` in the test's own setup. Adding the thin CRUD endpoint is the smaller, more broadly useful choice — do that: mirror `provider_profiles.py`'s `create_profile` shape exactly (`POST /api/assistant-sessions`, `GET /api/assistant-sessions`, both gated by the same `_require_enabled` dependency), and use it from this test instead of reaching into the repository directly.

Also confirm the exact name of the existing authenticated-cookies test fixture (`authenticated_cookies` above is a placeholder name — find the real one, likely already used by `tests/integration/test_provider_profiles_api.py`'s `Authenticated` dependency indirectly via `client`, or a dedicated login-flow fixture used by `tests/integration/test_terminal_websocket.py` if that file exists as prior art for testing an authenticated WebSocket route) before writing this test for real.

Run: `cd backend && uv run pytest tests/integration/test_assistant_websocket.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/assistant/service.py backend/app/api/assistant.py \
  backend/app/core/errors.py backend/app/main.py \
  backend/tests/unit/test_assistant_service.py backend/tests/integration/test_assistant_websocket.py
git commit -m "feat: add AI assistant chat service and WebSocket endpoint"
```

---

## Task 8: AI → Change Plan integration

**Files:**
- Modify: `backend/app/assistant/tools.py` (add `PROPOSE_CHANGE_PLAN_TOOL`, kept separate from `READ_ONLY_TOOLS`)
- Modify: `backend/app/assistant/service.py` (special-case this tool name; accept an optional `ChangeService`)
- Modify: `backend/app/api/assistant.py` (construct and pass `ChangeService` only when `structured_writes_enabled`)
- Test: extend `backend/tests/unit/test_assistant_service.py`

**Interfaces:**
- Consumes: `ChangeService.preview(..., source=ChangePlanSource.AI_GENERATED)` (Task 3); `ChangeValidationError`, `AppError` (`app/core/errors.py`).
- Produces: `PROPOSE_CHANGE_PLAN_TOOL: ToolSchema`. This is deliberately not in `READ_ONLY_TOOLS` and is never routed through `ToolDispatcher` — it stays a distinct, separately-reviewed path so `test_read_only_tools_never_include_a_write_tool` (Task 5) keeps meaning what it says. It is still not a "write" in the device sense: `.preview()` performs no device write, only render/validate/snapshot/persist-as-DRAFT — the same guarantee a manual preview already has.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/unit/test_assistant_service.py`:

```python
class _FakeChanges:
    def __init__(self, plan=None, error=None):
        self._plan = plan
        self._error = error

    def preview(self, **_kwargs):
        if self._error is not None:
            raise self._error
        return self._plan


def _fake_plan():
    from app.models import ChangePlanSource, ChangePlanStatus, ChangeRisk, SafetyLevel

    class _Step:
        target = "GigabitEthernet0/1"
        desired_value = "ai-drafted uplink"
        rendered_commands = "interface GigabitEthernet0/1\n description ai-drafted uplink"

    class _Plan:
        id = uuid4()
        status = ChangePlanStatus.DRAFT
        risk = ChangeRisk.LOW
        safety_level = SafetyLevel.BEST_EFFORT
        source = ChangePlanSource.AI_GENERATED
        steps = [_Step()]

    return _Plan()


@pytest.mark.asyncio
async def test_propose_change_plan_tool_creates_a_draft_plan() -> None:
    provider = _FakeProviderClient(
        [
            [
                ChatChunk(
                    type="tool_call",
                    tool_call=ToolCallRequest(
                        id="1",
                        name="propose_change_plan",
                        arguments={
                            "device_id": str(uuid4()),
                            "change_type": "interface_description",
                            "target": "GigabitEthernet0/1",
                            "desired_value": "ai-drafted uplink",
                        },
                    ),
                )
            ],
            [ChatChunk(type="token", content="Proposed.")],
        ]
    )
    service = AssistantChatService(
        session=None,  # type: ignore[arg-type]
        provider_client=provider,
        sessions=_FakeSessions(_session()),
        messages=_FakeMessages(),
        profiles=_FakeProfiles(_profile()),
        vault=_FakeVault(),
        tools=_FakeToolDispatcher(),  # type: ignore[arg-type]
        changes=_FakeChanges(plan=_fake_plan()),  # type: ignore[arg-type]
    )

    events = [e async for e in service.handle_user_message(uuid4(), "set the uplink description")]

    proposed = [e for e in events if e.type == "change_plan_proposed"]
    assert len(proposed) == 1
    assert proposed[0].tool_payload["status"] == "draft"
    assert proposed[0].tool_payload["steps"][0]["desired_value"] == "ai-drafted uplink"


@pytest.mark.asyncio
async def test_propose_change_plan_surfaces_validation_failure_without_crashing() -> None:
    from app.core.errors import ChangeValidationError

    provider = _FakeProviderClient(
        [
            [
                ChatChunk(
                    type="tool_call",
                    tool_call=ToolCallRequest(
                        id="1",
                        name="propose_change_plan",
                        arguments={
                            "device_id": str(uuid4()),
                            "change_type": "interface_description",
                            "target": "GigabitEthernet0/1",
                            "desired_value": "bad\nvalue",
                        },
                    ),
                )
            ],
            [ChatChunk(type="token", content="Sorry, that failed validation.")],
        ]
    )
    service = AssistantChatService(
        session=None,  # type: ignore[arg-type]
        provider_client=provider,
        sessions=_FakeSessions(_session()),
        messages=_FakeMessages(),
        profiles=_FakeProfiles(_profile()),
        vault=_FakeVault(),
        tools=_FakeToolDispatcher(),  # type: ignore[arg-type]
        changes=_FakeChanges(error=ChangeValidationError(details={"issues": ["desired_value must be printable"]})),  # type: ignore[arg-type]
    )

    events = [e async for e in service.handle_user_message(uuid4(), "set a bad description")]

    tool_events = [e for e in events if e.type == "tool_result"]
    assert "issues" in tool_events[0].tool_payload
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_assistant_service.py -k propose -v`
Expected: FAIL — `TypeError: AssistantChatService.__init__() got an unexpected keyword argument 'changes'`.

- [ ] **Step 3: Add the tool schema**

In `backend/app/assistant/tools.py`, add (not inside `READ_ONLY_TOOLS`):

```python
PROPOSE_CHANGE_PLAN_TOOL = ToolSchema(
    name="propose_change_plan",
    description=(
        "Propose a Change Plan for a registered Cisco IOS/IOS-XE device's "
        "interface description or admin state. This only drafts and "
        "validates a plan for human review -- it never touches the device. "
        "A human must separately apply it before anything changes."
    ),
    parameters={
        "type": "object",
        "properties": {
            "device_id": {"type": "string", "format": "uuid"},
            "change_type": {"type": "string", "enum": ["interface_description", "interface_admin_state"]},
            "target": {"type": "string", "description": "Interface name, e.g. GigabitEthernet0/1"},
            "desired_value": {"type": "string"},
        },
        "required": ["device_id", "change_type", "target", "desired_value"],
    },
)
```

- [ ] **Step 4: Extend the chat service**

In `backend/app/assistant/service.py`:

```python
from app.assistant.tools import PROPOSE_CHANGE_PLAN_TOOL, READ_ONLY_TOOLS, ReadOnlyToolError, ToolDispatcher
from app.changes.service import ChangeService
from app.core.errors import AppError, ChangeValidationError
from app.models import ChangePlanSource, ChangeType
```

Add `changes: ChangeService | None = None` to `__init__`'s parameters and store it as `self._changes`.

Change the tool-schema assembly:

```python
        tool_schemas: list[ToolSchema] | None = list(READ_ONLY_TOOLS) if profile.supports_tool_calling else None
        if tool_schemas is not None and self._changes is not None:
            tool_schemas = [*tool_schemas, PROPOSE_CHANGE_PLAN_TOOL]
```

Change the tool-call handling loop's body (replace the existing `try`/`except ReadOnlyToolError` block) with:

```python
            for call in pending_tool_calls:
                yield AssistantEvent(type="tool_call", tool_name=call.name, tool_payload=call.arguments)
                if call.name == PROPOSE_CHANGE_PLAN_TOOL.name and self._changes is not None:
                    payload = self._propose_change_plan(call.arguments)
                    event_type = "change_plan_proposed" if "plan_id" in payload else "tool_result"
                else:
                    try:
                        result = self._tools.dispatch(call.name, call.arguments)
                        payload = scrub_secrets(result.payload)
                    except ReadOnlyToolError as exc:
                        payload = {"error": str(exc)}
                    event_type = "tool_result"
                assert isinstance(payload, dict)
                yield AssistantEvent(type=event_type, tool_name=call.name, tool_payload=payload)
                self._messages.add(
                    session_id=session_id,
                    role=AssistantMessageRole.TOOL,
                    content=json.dumps(payload),
                    tool_results=payload,
                )
                self._session.commit()
                history.append(ChatMessage(role="tool", content=json.dumps(payload), tool_call_id=call.id))
```

Add the helper method:

```python
    def _propose_change_plan(self, arguments: dict[str, object]) -> dict[str, object]:
        assert self._changes is not None
        try:
            device_id = UUID(str(arguments["device_id"]))
            change_type = ChangeType(str(arguments["change_type"]))
            target = str(arguments["target"])
            desired_value = str(arguments["desired_value"])
        except (KeyError, ValueError) as exc:
            return {"error": f"Malformed change plan proposal: {exc}"}
        try:
            plan = self._changes.preview(
                device_id=device_id,
                change_type=change_type,
                target=target,
                desired_value=desired_value,
                source=ChangePlanSource.AI_GENERATED,
            )
        except AppError as exc:
            payload: dict[str, object] = {"error": str(exc)}
            if isinstance(exc, ChangeValidationError):
                payload["issues"] = exc.details.get("issues", [])
            return payload
        return {
            "plan_id": str(plan.id),
            "status": plan.status.value,
            "risk": plan.risk.value,
            "safety_level": plan.safety_level.value,
            "steps": [
                {"target": s.target, "desired_value": s.desired_value, "rendered_commands": s.rendered_commands}
                for s in plan.steps
            ],
        }
```

Confirm `AppError` is the actual common base class `NotFoundError`/`ChangeValidationError`/`ChangeVendorUnsupportedError` all inherit from (it is, per `app/core/errors.py`'s `ChangeValidationError(AppError)` seen in Task 1's research) before relying on one `except AppError` clause to catch every pipeline rejection.

- [ ] **Step 5: Wire `ChangeService` into the WebSocket endpoint**

In `backend/app/api/assistant.py`, construct `ChangeService` the same way `app/api/changes.py`'s own `_service()` helper does (reuse that helper if it's importable, rather than re-deriving its keyword list), and pass it only when enabled:

```python
        changes = None
        if container.settings.structured_writes_enabled:
            from app.changes.service import ChangeService

            changes = ChangeService(
                db_session,
                settings=container.settings,
                drivers=container.drivers,
                devices=DeviceService(
                    db_session, settings=container.settings, drivers=container.drivers,
                    vault=container.credential_vault, host_key_trust=container.host_key_trust,
                ),
                snapshots=SnapshotService(
                    db_session, store=container.snapshot_store,
                    devices=DeviceService(
                        db_session, settings=container.settings, drivers=container.drivers,
                        vault=container.credential_vault, host_key_trust=container.host_key_trust,
                    ),
                    drivers=container.drivers,
                ),
            )
        service = AssistantChatService(
            db_session,
            provider_client=container.ai_provider_client,
            sessions=AssistantSessionRepository(db_session),
            messages=AssistantMessageRepository(db_session),
            profiles=ProviderProfileRepository(db_session),
            vault=container.provider_key_vault,
            tools=ToolDispatcher(...),  # unchanged from Task 7
            changes=changes,
        )
```

Match `ChangeService`'s actual constructor keywords exactly (`app/changes/service.py`'s `__init__`) rather than the guess above -- read it before finalizing this step.

- [ ] **Step 6: Run the tests**

Run: `cd backend && uv run pytest tests/unit/test_assistant_service.py -v`
Expected: PASS (5 tests total in this file).

- [ ] **Step 7: Commit**

```bash
git add backend/app/assistant/tools.py backend/app/assistant/service.py backend/app/api/assistant.py \
  backend/tests/unit/test_assistant_service.py
git commit -m "feat: let the assistant propose Change Plans through the existing pipeline"
```

---

## Task 9: Destructive-command blocklist for staged console suggestions

**Files:**
- Create: `backend/app/assistant/blocklist.py`
- Modify: `backend/app/api/assistant.py` (add `POST /assistant-sessions/{id}/stage-command`)
- Modify: `backend/app/core/errors.py` (add `BlockedCommandError`)
- Test: `backend/tests/unit/test_assistant_blocklist.py`
- Test: extend `backend/tests/integration/test_assistant_websocket.py`

**Interfaces:**
- Produces: `contains_blocked_command(text: str) -> bool`; `POST /api/assistant-sessions/{session_id}/stage-command` (body: `{"command": str}`, returns `{"allowed": true}` or a 422 `blocked_command` error). Task 14 (frontend console-suggestion card) calls this endpoint before ever offering the "Open in terminal" navigation for a specific command, in both Confirm and Auto mode — the check is unconditional per the Global Constraints.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_assistant_blocklist.py
from __future__ import annotations

import pytest

from app.assistant.blocklist import contains_blocked_command


@pytest.mark.parametrize(
    "text",
    [
        "erase startup-config",
        "reload",
        "format flash:",
        "factory-reset",
        "factory reset",
        "Reload",
        "please ERASE the config",
    ],
)
def test_blocked_commands_are_detected(text: str) -> None:
    assert contains_blocked_command(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "interface GigabitEthernet0/1",
        "description uplink to core",
        "show running-config",
        "no shutdown",
    ],
)
def test_ordinary_commands_are_not_flagged(text: str) -> None:
    assert contains_blocked_command(text) is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_assistant_blocklist.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write the blocklist**

```python
# backend/app/assistant/blocklist.py
from __future__ import annotations

import re

# Unconditional floor, not mode-gated -- spec
# docs/superpowers/specs/2026-08-24-phase-4-ai-assistant-design.md §2.4,
# mirroring docs/network-automation-final-plan.md §7's
# "Wizard/AI block คำสั่ง erase, reload, format และ factory reset" with no
# Auto-mode exception. Applies only to AI-suggested commands staged through
# this module -- it does not and cannot restrict what a human freely types
# into an already-open Direct Mode terminal on their own initiative.
_BLOCKED_PATTERNS = (
    re.compile(r"\berase\b", re.IGNORECASE),
    re.compile(r"\breload\b", re.IGNORECASE),
    re.compile(r"\bformat\b", re.IGNORECASE),
    re.compile(r"\bfactory[\s-]?reset\b", re.IGNORECASE),
)


def contains_blocked_command(text: str) -> bool:
    return any(pattern.search(text) for pattern in _BLOCKED_PATTERNS)
```

- [ ] **Step 4: Add the error class and endpoint**

In `backend/app/core/errors.py`:

```python
class BlockedCommandError(AppError):
    code = "blocked_command"
    status_code = 422
    default_message = "This command matches a blocked pattern (erase/reload/format/factory-reset)"
```

In `backend/app/api/assistant.py`, add (on the existing REST-style router used for `assistant-sessions` CRUD from Task 7 Step 7, not the WebSocket router):

```python
from app.assistant.blocklist import contains_blocked_command
from app.core.errors import BlockedCommandError
from app.schemas.common import APIModel


class StageCommandRequest(APIModel):
    command: str


@sessions_router.post("/{session_id}/stage-command")
def stage_command(
    session_id: UUID,
    request: StageCommandRequest,
    _auth: Authenticated,
):
    if contains_blocked_command(request.command):
        raise BlockedCommandError()
    return {"allowed": True}
```

`session_id` is accepted but unused beyond path validation in this slice (no per-session staging state is persisted) -- it keeps the URL consistent with the rest of the assistant-sessions resource and leaves room for a future audit-log entry without a breaking API change.

- [ ] **Step 5: Run the tests**

Run: `cd backend && uv run pytest tests/unit/test_assistant_blocklist.py -v`
Expected: PASS (11 parametrized cases).

- [ ] **Step 6: Commit**

```bash
git add backend/app/assistant/blocklist.py backend/app/api/assistant.py backend/app/core/errors.py \
  backend/tests/unit/test_assistant_blocklist.py
git commit -m "feat: enforce the destructive-command blocklist for staged AI console suggestions"
```

---

## Task 10: Frontend — API client, AppShell wiring, Provider profile management

**Files:**
- Modify: `frontend/src/types/api.ts` (add `ProviderProfile`, `ProviderProfileInput`, `AssistantSession`, `AssistantSessionMode`)
- Modify: `frontend/src/api/network.ts` (add `providerProfiles`, `createProviderProfile`, `updateProviderProfile`, `deleteProviderProfile`, `probeProviderProfile`, `assistantSessions`, `createAssistantSession`)
- Modify: `frontend/src/components/AppShell.tsx` (add `'assistant'` to `ViewId`, nav button, lazy-loaded content branch)
- Create: `frontend/src/features/assistant/AssistantPage.tsx` (shell only this task — session list placeholder, provider profile modal trigger; chat transcript lands in Task 12)
- Create: `frontend/src/features/assistant/ProviderProfileList.tsx`
- Create: `frontend/src/features/assistant/ProviderProfileForm.tsx`
- Test: `frontend/tests/assistant-page.test.tsx`

**Interfaces:**
- Consumes: `apiRequest`/`ApiError` (`frontend/src/api/client.ts`); the `Modal` component; the exact clone source `frontend/src/features/inventory/CredentialList.tsx` / `CredentialForm.tsx` / the `credentialDialog` union pattern in `InventoryPage.tsx:44-48,169-170,458-538`.
- Produces: `api.providerProfiles()`, `api.createProviderProfile(input)`, `api.updateProviderProfile(id, input)`, `api.deleteProviderProfile(id)`, `api.probeProviderProfile(id)`, `api.assistantSessions()`, `api.createAssistantSession(providerProfileId)`; `<AssistantPage />` mounted from `AppShell` at `view === 'assistant'`. Task 12 renders the chat transcript inside this same page once a session is selected/created.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/tests/assistant-page.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { api } from '../src/api/network';
import { AssistantPage } from '../src/features/assistant/AssistantPage';
import type { ProviderProfile } from '../src/types/api';

vi.mock('../src/api/network', () => ({
  api: {
    providerProfiles: vi.fn(),
    createProviderProfile: vi.fn(),
    updateProviderProfile: vi.fn(),
    deleteProviderProfile: vi.fn(),
    probeProviderProfile: vi.fn(),
    assistantSessions: vi.fn(),
    createAssistantSession: vi.fn(),
  },
}));

const profile: ProviderProfile = {
  id: '2ad0db14-5a87-4147-a4e7-c98f88322464',
  name: 'Local Ollama',
  base_url: 'http://localhost:11434/v1',
  model_id: 'llama3.1',
  has_api_key: false,
  context_limit_override: null,
  supports_streaming: false,
  supports_tool_calling: false,
  created_at: '2026-08-24T00:00:00Z',
  updated_at: '2026-08-24T00:00:00Z',
};

function TestProviders({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function renderAssistant() {
  render(<AssistantPage />, { wrapper: TestProviders });
}

beforeEach(() => {
  vi.mocked(api.assistantSessions).mockResolvedValue([]);
  vi.mocked(api.providerProfiles).mockResolvedValue([profile]);
});

it('opens the provider profile list from the header button', async () => {
  const user = userEvent.setup();
  renderAssistant();

  await user.click(screen.getByRole('button', { name: 'Provider profile' }));

  const dialog = await screen.findByRole('dialog', { name: 'Provider profiles' });
  expect(within(dialog).getByText('Local Ollama')).toBeVisible();
});

it('shows an empty state and offers to create the first profile', async () => {
  vi.mocked(api.providerProfiles).mockResolvedValue([]);
  const user = userEvent.setup();
  renderAssistant();

  await user.click(screen.getByRole('button', { name: 'Provider profile' }));

  expect(await screen.findByText('No provider profiles yet')).toBeVisible();
});

it('creates a profile with an optional API key', async () => {
  vi.mocked(api.createProviderProfile).mockResolvedValue({ ...profile, id: 'new-id' });
  const user = userEvent.setup();
  renderAssistant();

  await user.click(screen.getByRole('button', { name: 'Provider profile' }));
  await user.click(await screen.findByRole('button', { name: /new profile/i }));
  await user.type(screen.getByLabelText('Profile name'), 'Cloud');
  await user.type(screen.getByLabelText('Base URL'), 'https://api.openai.com/v1');
  await user.type(screen.getByLabelText('Model ID'), 'gpt-4o');
  await user.click(screen.getByRole('button', { name: 'Save changes' }));

  expect(api.createProviderProfile).toHaveBeenCalledWith(
    expect.objectContaining({ name: 'Cloud', base_url: 'https://api.openai.com/v1', model_id: 'gpt-4o' }),
  );
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npm test -- assistant-page.test.tsx --run`
Expected: FAIL — module not found.

- [ ] **Step 3: Add types and API methods**

In `frontend/src/types/api.ts`, add:

```ts
export interface ProviderProfile {
  id: string;
  name: string;
  base_url: string;
  model_id: string;
  has_api_key: boolean;
  context_limit_override: number | null;
  supports_streaming: boolean;
  supports_tool_calling: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProviderProfileInput {
  name: string;
  base_url: string;
  model_id: string;
  api_key?: string;
  context_limit_override?: number;
}

export type AssistantSessionMode = 'confirm' | 'auto';

export interface AssistantSession {
  id: string;
  provider_profile_id: string;
  mode: AssistantSessionMode;
  auto_apply_count: number;
  created_at: string;
  updated_at: string;
}
```

In `frontend/src/api/network.ts`, add:

```ts
  providerProfiles: () => apiRequest<ProviderProfile[]>('/provider-profiles'),
  createProviderProfile: (input: ProviderProfileInput) =>
    apiRequest<ProviderProfile>('/provider-profiles', { method: 'POST', body: json(input) }),
  updateProviderProfile: (id: string, input: Partial<ProviderProfileInput>) =>
    apiRequest<ProviderProfile>(`/provider-profiles/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: json(input),
    }),
  deleteProviderProfile: async (id: string): Promise<void> => {
    await apiRequest<unknown>(`/provider-profiles/${encodeURIComponent(id)}`, { method: 'DELETE' });
  },
  probeProviderProfile: (id: string) =>
    apiRequest<ProviderProfile>(`/provider-profiles/${encodeURIComponent(id)}/probe`, { method: 'POST' }),
  assistantSessions: () => apiRequest<AssistantSession[]>('/assistant-sessions'),
  createAssistantSession: (providerProfileId: string) =>
    apiRequest<AssistantSession>('/assistant-sessions', {
      method: 'POST',
      body: json({ provider_profile_id: providerProfileId }),
    }),
```

- [ ] **Step 4: Clone `ProviderProfileList`/`ProviderProfileForm` from `CredentialList`/`CredentialForm`**

Create `frontend/src/features/assistant/ProviderProfileList.tsx`, structurally identical to `frontend/src/features/inventory/CredentialList.tsx` (toolbar with "New profile" button, `AppState kind="empty"` message `"No provider profiles yet"` when the list is empty, one row per profile with edit/delete icon buttons) with `ProviderProfile` substituted for `CredentialProfile` and its display fields (`name`, `base_url`, `model_id`) substituted for the credential fields shown per row.

Create `frontend/src/features/assistant/ProviderProfileForm.tsx`, structurally identical to `frontend/src/features/inventory/CredentialForm.tsx` (`react-hook-form` + `zod`, edit mode relaxes required fields since the API never returns the key back) with fields `name` (label "Profile name"), `base_url` (label "Base URL"), `model_id` (label "Model ID"), and an optional `api_key` field with the same show/hide toggle `CredentialForm` already has for `password`.

- [ ] **Step 5: Write `AssistantPage` (shell)**

```tsx
// frontend/src/features/assistant/AssistantPage.tsx
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { KeyRound } from 'lucide-react';
import { useState } from 'react';
import { api } from '../../api/network';
import { Button } from '../../components/ui/Button';
import { Modal } from '../../components/ui/Modal';
import { AppState } from '../../components/ui/AppState';
import { QueryErrorState } from '../../components/ui/QueryErrorState';
import { ProviderProfileList } from './ProviderProfileList';
import { ProviderProfileForm } from './ProviderProfileForm';
import type { ProviderProfile, ProviderProfileInput } from '../../types/api';

type ProviderDialog =
  | { mode: 'list' }
  | { mode: 'create' }
  | { mode: 'edit'; profile: ProviderProfile }
  | null;

export function AssistantPage() {
  const queryClient = useQueryClient();
  const [providerDialog, setProviderDialog] = useState<ProviderDialog>(null);
  const [deleteTarget, setDeleteTarget] = useState<ProviderProfile>();

  const profiles = useQuery({ queryKey: ['provider-profiles'], queryFn: api.providerProfiles, retry: false });
  const sessions = useQuery({ queryKey: ['assistant-sessions'], queryFn: api.assistantSessions, retry: false });

  const saveProfile = useMutation({
    mutationFn: ({ input, current }: { input: Partial<ProviderProfileInput>; current?: ProviderProfile }) =>
      current !== undefined
        ? api.updateProviderProfile(current.id, input)
        : api.createProviderProfile({
            name: input.name ?? '',
            base_url: input.base_url ?? '',
            model_id: input.model_id ?? '',
            ...(input.api_key !== undefined ? { api_key: input.api_key } : {}),
          }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['provider-profiles'] });
      setProviderDialog(null);
    },
  });

  const deleteProfile = useMutation({
    mutationFn: (profile: ProviderProfile) => api.deleteProviderProfile(profile.id),
    onSuccess: async () => {
      setDeleteTarget(undefined);
      await queryClient.invalidateQueries({ queryKey: ['provider-profiles'] });
    },
  });

  return (
    <div className="assistant-page">
      <header className="assistant-page__header">
        <h1>Assistant</h1>
        <Button onClick={() => setProviderDialog({ mode: 'list' })}>
          <KeyRound size={16} /> Provider profile
        </Button>
      </header>

      {/* Session list / transcript land in Task 12; this task only ships the
          shell and the provider-profile management modal. */}
      {sessions.isPending ? (
        <AppState kind="loading" title="Loading sessions" message="Reading assistant session metadata…" compact />
      ) : sessions.isError ? (
        <QueryErrorState error={sessions.error} onRetry={() => void sessions.refetch()} compact />
      ) : null}

      <Modal
        open={providerDialog !== null}
        title={
          providerDialog?.mode === 'edit'
            ? 'Edit provider profile'
            : providerDialog?.mode === 'create'
              ? 'New provider profile'
              : 'Provider profiles'
        }
        description={
          providerDialog?.mode === 'list'
            ? 'BYOK endpoints this application proxies to. No model runs in this application.'
            : 'Point at any OpenAI-compatible endpoint -- OpenAI itself, a self-hosted Ollama, or another compatible server.'
        }
        onClose={() => setProviderDialog(null)}
      >
        {providerDialog?.mode === 'list' ? (
          profiles.isPending ? (
            <AppState kind="loading" title="Loading profiles" message="Reading provider profile metadata…" compact />
          ) : profiles.isError ? (
            <QueryErrorState error={profiles.error} onRetry={() => void profiles.refetch()} compact />
          ) : (
            <ProviderProfileList
              profiles={profiles.data}
              onCreate={() => setProviderDialog({ mode: 'create' })}
              onEdit={(profile) => setProviderDialog({ mode: 'edit', profile })}
              onDelete={setDeleteTarget}
            />
          )
        ) : providerDialog?.mode === 'create' || providerDialog?.mode === 'edit' ? (
          <ProviderProfileForm
            {...(providerDialog.mode === 'edit' ? { profile: providerDialog.profile } : {})}
            onCancel={() => setProviderDialog(null)}
            onSubmit={(input) => saveProfile.mutateAsync({ input, ...(providerDialog.mode === 'edit' ? { current: providerDialog.profile } : {}) }).then(() => undefined)}
            error={saveProfile.error?.message}
          />
        ) : null}
      </Modal>

      <Modal
        open={deleteTarget !== undefined}
        title="Remove provider profile?"
        description="Assistant sessions using this profile will need a different one to keep chatting."
        onClose={() => setDeleteTarget(undefined)}
        size="small"
        footer={
          <>
            <Button onClick={() => setDeleteTarget(undefined)}>Cancel</Button>
            <Button
              variant="danger"
              busy={deleteProfile.isPending}
              onClick={() => {
                if (deleteTarget !== undefined) deleteProfile.mutate(deleteTarget);
              }}
            >
              Remove profile
            </Button>
          </>
        }
      >
        <div className="delete-summary">
          <div className="device-avatar"><KeyRound size={20} /></div>
          <div><strong>{deleteTarget?.name}</strong></div>
        </div>
        {deleteProfile.error === null ? null : (
          <div className="form-error" role="alert">{deleteProfile.error.message}</div>
        )}
      </Modal>
    </div>
  );
}
```

- [ ] **Step 6: Wire `AppShell`**

In `frontend/src/components/AppShell.tsx`: add `'assistant'` to the `ViewId` union; add `const AssistantPage = lazy(() => import('../features/assistant/AssistantPage').then((m) => ({ default: m.AssistantPage })));` next to the other lazy imports; add one nav `<button>` following the exact shape of the existing four (icon: `Bot` from `lucide-react`, label `"Assistant"`, `onClick={() => setView('assistant')}`); add one more branch to the content switch rendering `<Suspense fallback={...}><AssistantPage /></Suspense>` for `view === 'assistant'`.

- [ ] **Step 7: Run the tests**

Run: `cd frontend && npm test -- assistant-page.test.tsx --run`
Expected: PASS (3 tests).

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/types/api.ts frontend/src/api/network.ts frontend/src/components/AppShell.tsx \
  frontend/src/features/assistant/AssistantPage.tsx frontend/src/features/assistant/ProviderProfileList.tsx \
  frontend/src/features/assistant/ProviderProfileForm.tsx frontend/tests/assistant-page.test.tsx
git commit -m "feat: add Assistant nav item and provider profile management UI"
```

---

## Task 11: Extract `ChangePlanCard` for reuse in chat

**Files:**
- Create: `frontend/src/features/inventory/ChangePlanCard.tsx`
- Modify: `frontend/src/features/inventory/DeviceInspector.tsx` (replace the inline preview JSX at lines 632-668 with `<ChangePlanCard .../>`)
- Test: `frontend/tests/change-plan-card.test.tsx`
- Test: confirm `frontend/tests/inventory-page.test.tsx`'s Configure-tab coverage (if any) still passes unmodified

**Interfaces:**
- Consumes: `ChangePlan`, `ChangeStep` types (`frontend/src/types/api.ts:336-368`).
- Produces: `<ChangePlanCard plan={plan} onApply={(planId) => void} applyBusy={boolean} applyError={string | undefined} applySuccess={boolean} />`. Task 12 imports this directly into the chat transcript for `change_plan_proposed` events — same component, same props, no chat-specific fork.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/tests/change-plan-card.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChangePlanCard } from '../src/features/inventory/ChangePlanCard';
import type { ChangePlan } from '../src/types/api';

const plan: ChangePlan = {
  id: 'a1b2c3d4-df32-4a9e-9df0-6e6f8a2b6a11',
  device_id: '2ad0db14-5a87-4147-a4e7-c98f88322464',
  status: 'draft',
  safety_level: 'C',
  risk: 'low',
  failure_code: null,
  applied_at: null,
  steps: [
    {
      id: 'step-1',
      change_type: 'interface_description',
      target: 'GigabitEthernet0/1',
      previous_value: null,
      desired_value: 'uplink',
      rendered_commands: 'interface GigabitEthernet0/1\n description uplink',
      inverse_commands: 'interface GigabitEthernet0/1\n no description',
    },
  ],
  created_at: '2026-08-24T00:00:00Z',
  updated_at: '2026-08-24T00:00:00Z',
};

it('renders risk, safety level, and the rendered commands', () => {
  render(<ChangePlanCard plan={plan} onApply={vi.fn()} applyBusy={false} applySuccess={false} />);

  expect(screen.getByText('low risk')).toBeVisible();
  expect(screen.getByText(/Safety level C/)).toBeVisible();
  expect(screen.getByText(/interface GigabitEthernet0\/1/)).toBeVisible();
});

it('calls onApply with the plan id when clicked', async () => {
  const user = userEvent.setup();
  const onApply = vi.fn();
  render(<ChangePlanCard plan={plan} onApply={onApply} applyBusy={false} applySuccess={false} />);

  await user.click(screen.getByRole('button', { name: /apply/i }));

  expect(onApply).toHaveBeenCalledWith(plan.id);
});

it('disables Apply once the plan is no longer a draft', () => {
  render(<ChangePlanCard plan={{ ...plan, status: 'applied' }} onApply={vi.fn()} applyBusy={false} applySuccess={false} />);

  expect(screen.getByRole('button', { name: /apply/i })).toBeDisabled();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npm test -- change-plan-card.test.tsx --run`
Expected: FAIL — module not found.

- [ ] **Step 3: Extract the component**

Create `frontend/src/features/inventory/ChangePlanCard.tsx` from `DeviceInspector.tsx:632-668`'s existing JSX, wrapped as a standalone component with exactly the prop surface that JSX already touches (`plan`, and the four `apply.*` fields it reads — no device or query context needed, confirmed during planning research):

```tsx
import { Check, ShieldCheck } from 'lucide-react';
import { Badge } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import type { ChangePlan } from '../../types/api';

interface ChangePlanCardProps {
  plan: ChangePlan;
  onApply: (planId: string) => void;
  applyBusy: boolean;
  applyError?: string | undefined;
  applySuccess: boolean;
}

export function ChangePlanCard({ plan, onApply, applyBusy, applyError, applySuccess }: ChangePlanCardProps) {
  return (
    <div className="configure-preview">
      <div>
        <Badge tone={plan.risk === 'high' ? 'danger' : 'success'}>{plan.risk} risk</Badge>
        <Badge tone="neutral">Safety level {plan.safety_level} · best effort</Badge>
      </div>
      {plan.steps.map((step) => (
        <div key={step.id} className="configure-preview__step">
          <p>
            {step.target}: <span className="mono">{step.previous_value ?? '(none)'}</span> →{' '}
            <span className="mono">{step.desired_value}</span>
          </p>
          <pre>{step.rendered_commands}</pre>
        </div>
      ))}
      <Button
        variant="primary"
        size="small"
        onClick={() => onApply(plan.id)}
        busy={applyBusy}
        disabled={plan.status !== 'draft'}
      >
        <ShieldCheck size={14} /> Apply
      </Button>
      {applyError === undefined ? null : (
        <div className="form-error" role="alert">{applyError}</div>
      )}
      {applySuccess ? (
        <div className="mini-result mini-result--success" role="status">
          <Check size={14} />
          <span>Apply queued. The status below updates when the worker finishes.</span>
        </div>
      ) : null}
    </div>
  );
}
```

- [ ] **Step 4: Use it from `DeviceInspector`'s Configure tab**

In `frontend/src/features/inventory/DeviceInspector.tsx`, replace the JSX block at lines 632-668 (the `{plan === null ? null : (<div className="configure-preview">...)}` block) with:

```tsx
{plan === null ? null : (
  <ChangePlanCard
    plan={plan}
    onApply={(planId) => apply.mutate(planId)}
    applyBusy={apply.isPending}
    applyError={apply.error?.message}
    applySuccess={apply.isSuccess}
  />
)}
```

Add `import { ChangePlanCard } from './ChangePlanCard';` near the top of the file. No other change to `ConfigureTab` — its `plan`/`apply` state and mutations are untouched, only the rendering of the preview is delegated.

- [ ] **Step 5: Run the tests**

Run: `cd frontend && npm test -- change-plan-card.test.tsx inventory-page.test.tsx --run`
Expected: PASS. The `inventory-page.test.tsx` run is the regression check — it must show the same pass count as before this extraction; a failure here means the extraction changed Configure-tab behavior, not just its location.

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/inventory/ChangePlanCard.tsx frontend/src/features/inventory/DeviceInspector.tsx \
  frontend/tests/change-plan-card.test.tsx
git commit -m "refactor: extract ChangePlanCard for reuse in the assistant chat transcript"
```

---

## Task 12: Chat transcript, WebSocket client, streaming, mode toggle

**Files:**
- Create: `frontend/src/features/assistant/useAssistantChat.ts`
- Create: `frontend/src/features/assistant/ChatTranscript.tsx`
- Create: `frontend/src/features/assistant/ModeToggle.tsx`
- Modify: `frontend/src/features/assistant/AssistantPage.tsx` (mount session creation + `ChatTranscript` once a provider profile exists)
- Test: `frontend/tests/use-assistant-chat.test.ts`
- Test: extend `frontend/tests/assistant-page.test.tsx`

**Interfaces:**
- Consumes: `ChangePlanCard` (Task 11); `api.createAssistantSession` (Task 10); native `WebSocket`.
- Produces: `useAssistantChat(sessionId: string | undefined)` returning `{ transcript: AssistantTranscriptEntry[], sendMessage(content: string): void, mode: AssistantSessionMode, setMode(mode, riskAcknowledged): void, connectionState: 'connecting' | 'open' | 'closed', pendingModeError: string | undefined }`; `<ChatTranscript entries={...} />`; `<ModeToggle mode={...} onRequestChange={...} />`. No other task consumes these — this is the leaf of the frontend chain.

- [ ] **Step 1: Write the failing hook test**

```ts
// frontend/tests/use-assistant-chat.test.ts
import { act, renderHook, waitFor } from '@testing-library/react';
import { useAssistantChat } from '../src/features/assistant/useAssistantChat';

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: string[] = [];
  readyState = 0;

  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() {
    this.readyState = 3;
    this.onclose?.();
  }

  emitOpen() {
    this.readyState = 1;
    this.onopen?.();
  }

  emitMessage(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal('WebSocket', FakeWebSocket);
});

it('connects to the session-scoped endpoint and streams tokens into one transcript entry', async () => {
  const { result } = renderHook(() => useAssistantChat('session-1'));

  await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
  const socket = FakeWebSocket.instances[0]!;
  expect(socket.url).toContain('/ws/assistant/session-1');
  act(() => socket.emitOpen());

  act(() => result.current.sendMessage('hello'));
  expect(JSON.parse(socket.sent[0]!)).toEqual({ type: 'user_message', content: 'hello' });

  act(() => socket.emitMessage({ type: 'token', content: 'Hi' }));
  act(() => socket.emitMessage({ type: 'token', content: ' there' }));
  act(() => socket.emitMessage({ type: 'done' }));

  const assistantEntry = result.current.transcript.find((e) => e.role === 'assistant');
  expect(assistantEntry?.content).toBe('Hi there');
});

it('surfaces change_plan_proposed as a distinct transcript entry', async () => {
  const { result } = renderHook(() => useAssistantChat('session-1'));
  await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
  const socket = FakeWebSocket.instances[0]!;
  act(() => socket.emitOpen());

  act(() =>
    socket.emitMessage({
      type: 'change_plan_proposed',
      tool: 'propose_change_plan',
      payload: { plan_id: 'p1', status: 'draft', risk: 'low', safety_level: 'C', steps: [] },
    }),
  );

  const planEntry = result.current.transcript.find((e) => e.role === 'change_plan');
  expect(planEntry?.plan?.plan_id).toBe('p1');
});

it('rejects switching to auto mode without acknowledgment and surfaces the error', async () => {
  const { result } = renderHook(() => useAssistantChat('session-1'));
  await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
  const socket = FakeWebSocket.instances[0]!;
  act(() => socket.emitOpen());

  act(() => result.current.setMode('auto', false));
  act(() =>
    socket.emitMessage({ type: 'error', code: 'auto_mode_requires_acknowledgment', message: 'Confirm the risk before enabling Auto mode' }),
  );

  expect(result.current.pendingModeError).toBe('Confirm the risk before enabling Auto mode');
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npm test -- use-assistant-chat.test.ts --run`
Expected: FAIL — module not found.

- [ ] **Step 3: Write `useAssistantChat`**

```ts
// frontend/src/features/assistant/useAssistantChat.ts
import { useCallback, useEffect, useRef, useState } from 'react';
import type { AssistantSessionMode } from '../../types/api';

export interface ChangePlanPayload {
  plan_id: string;
  status: string;
  risk: string;
  safety_level: string;
  steps: { target: string; desired_value: string; rendered_commands: string }[];
}

export interface AssistantTranscriptEntry {
  id: string;
  role: 'user' | 'assistant' | 'tool' | 'change_plan';
  content?: string;
  toolName?: string;
  toolPayload?: Record<string, unknown>;
  plan?: ChangePlanPayload;
}

type ServerFrame =
  | { type: 'token'; content: string }
  | { type: 'tool_call'; tool: string; payload?: Record<string, unknown> }
  | { type: 'tool_result'; tool: string; payload: Record<string, unknown> }
  | { type: 'change_plan_proposed'; tool: string; payload: ChangePlanPayload }
  | { type: 'done' }
  | { type: 'mode_changed'; mode: AssistantSessionMode }
  | { type: 'error'; code: string; message: string };

let nextEntryId = 0;
const newEntryId = () => `entry-${(nextEntryId += 1)}`;

export function useAssistantChat(sessionId: string | undefined) {
  const socketRef = useRef<WebSocket | null>(null);
  const [transcript, setTranscript] = useState<AssistantTranscriptEntry[]>([]);
  const [mode, setModeState] = useState<AssistantSessionMode>('confirm');
  const [connectionState, setConnectionState] = useState<'connecting' | 'open' | 'closed'>('connecting');
  const [pendingModeError, setPendingModeError] = useState<string>();
  const streamingEntryId = useRef<string | null>(null);

  useEffect(() => {
    if (sessionId === undefined) return undefined;
    const socket = new WebSocket(`${window.location.origin.replace(/^http/, 'ws')}/ws/assistant/${sessionId}`);
    socketRef.current = socket;
    socket.onopen = () => setConnectionState('open');
    socket.onclose = () => setConnectionState('closed');
    socket.onmessage = (event) => {
      const frame = JSON.parse(event.data) as ServerFrame;
      if (frame.type === 'token') {
        setTranscript((current) => {
          if (streamingEntryId.current !== null) {
            return current.map((entry) =>
              entry.id === streamingEntryId.current
                ? { ...entry, content: (entry.content ?? '') + frame.content }
                : entry,
            );
          }
          const id = newEntryId();
          streamingEntryId.current = id;
          return [...current, { id, role: 'assistant', content: frame.content }];
        });
      } else if (frame.type === 'change_plan_proposed') {
        setTranscript((current) => [...current, { id: newEntryId(), role: 'change_plan', plan: frame.payload }]);
      } else if (frame.type === 'tool_result') {
        setTranscript((current) => [
          ...current,
          { id: newEntryId(), role: 'tool', toolName: frame.tool, toolPayload: frame.payload },
        ]);
      } else if (frame.type === 'done') {
        streamingEntryId.current = null;
      } else if (frame.type === 'mode_changed') {
        setModeState(frame.mode);
        setPendingModeError(undefined);
      } else if (frame.type === 'error') {
        setPendingModeError(frame.message);
      }
    };
    return () => socket.close();
  }, [sessionId]);

  const sendMessage = useCallback((content: string) => {
    setTranscript((current) => [...current, { id: newEntryId(), role: 'user', content }]);
    socketRef.current?.send(JSON.stringify({ type: 'user_message', content }));
  }, []);

  const setMode = useCallback((nextMode: AssistantSessionMode, riskAcknowledged: boolean) => {
    socketRef.current?.send(JSON.stringify({ type: 'set_mode', mode: nextMode, risk_acknowledged: riskAcknowledged }));
  }, []);

  return { transcript, sendMessage, mode, setMode, connectionState, pendingModeError };
}
```

- [ ] **Step 4: Run the hook tests**

Run: `cd frontend && npm test -- use-assistant-chat.test.ts --run`
Expected: PASS (3 tests).

- [ ] **Step 5: Write `ChatTranscript` and `ModeToggle`**

```tsx
// frontend/src/features/assistant/ChatTranscript.tsx
import { ChangePlanCard } from '../inventory/ChangePlanCard';
import type { AssistantTranscriptEntry } from './useAssistantChat';

interface ChatTranscriptProps {
  entries: AssistantTranscriptEntry[];
  onApplyPlan: (planId: string) => void;
  applyBusyPlanId?: string;
}

export function ChatTranscript({ entries, onApplyPlan, applyBusyPlanId }: ChatTranscriptProps) {
  return (
    <div className="chat-transcript" role="log" aria-label="Assistant conversation">
      {entries.map((entry) => {
        if (entry.role === 'change_plan' && entry.plan) {
          return (
            <div key={entry.id} className="chat-transcript__entry chat-transcript__entry--plan">
              <ChangePlanCard
                plan={{
                  id: entry.plan.plan_id,
                  device_id: '',
                  status: entry.plan.status as never,
                  safety_level: entry.plan.safety_level as never,
                  risk: entry.plan.risk as never,
                  failure_code: null,
                  applied_at: null,
                  steps: entry.plan.steps.map((step, index) => ({
                    id: `${entry.id}-step-${index}`,
                    change_type: 'interface_description',
                    target: step.target,
                    previous_value: null,
                    desired_value: step.desired_value,
                    rendered_commands: step.rendered_commands,
                    inverse_commands: '',
                  })),
                  created_at: '',
                  updated_at: '',
                }}
                onApply={onApplyPlan}
                applyBusy={applyBusyPlanId === entry.plan.plan_id}
                applySuccess={false}
              />
            </div>
          );
        }
        return (
          <div key={entry.id} className={`chat-transcript__entry chat-transcript__entry--${entry.role}`}>
            {entry.content}
          </div>
        );
      })}
    </div>
  );
}
```

```tsx
// frontend/src/features/assistant/ModeToggle.tsx
import { useState } from 'react';
import { Button } from '../../components/ui/Button';
import { Modal } from '../../components/ui/Modal';
import type { AssistantSessionMode } from '../../types/api';

interface ModeToggleProps {
  mode: AssistantSessionMode;
  onRequestChange: (mode: AssistantSessionMode, riskAcknowledged: boolean) => void;
}

export function ModeToggle({ mode, onRequestChange }: ModeToggleProps) {
  const [confirmingAuto, setConfirmingAuto] = useState(false);

  return (
    <div className="mode-toggle">
      <Button variant={mode === 'confirm' ? 'primary' : undefined} onClick={() => onRequestChange('confirm', false)}>
        Confirm
      </Button>
      <Button variant={mode === 'auto' ? 'primary' : undefined} onClick={() => setConfirmingAuto(true)}>
        Auto
      </Button>

      <Modal
        open={confirmingAuto}
        title="Enable Auto mode?"
        description="The assistant will apply Change Plans and stage console commands without asking you to confirm each one, up to a per-session limit. You are choosing to accept that risk."
        onClose={() => setConfirmingAuto(false)}
        size="small"
        footer={
          <>
            <Button onClick={() => setConfirmingAuto(false)}>Cancel</Button>
            <Button
              variant="danger"
              onClick={() => {
                onRequestChange('auto', true);
                setConfirmingAuto(false);
              }}
            >
              I understand the risk -- enable Auto
            </Button>
          </>
        }
      />
    </div>
  );
}
```

- [ ] **Step 6: Wire into `AssistantPage`, including Auto-mode auto-apply**

Confirm-mode requires a click on `ChangePlanCard`'s existing Apply button (unchanged). Auto mode must apply a proposed plan **without** waiting for that click — a plain `onApplyPlan` prop wired to a button alone does not satisfy that, so track which plan ids have already been auto-applied (a plan proposed while already in Confirm mode, then later switched to Auto, must not retroactively auto-fire) and drive the same mutation from an effect:

```tsx
const applyChangePlan = useMutation({ mutationFn: api.applyChangePlan });
const autoAppliedPlanIds = useRef(new Set<string>());
// ponytail: session-lifetime in-memory cap, not server-enforced yet -- fine
// for a single-user local app where the operator watching the chat *is*
// the trust boundary; upgrade to a server-checked AssistantSession.auto_apply_count
// (already a column, see Task 2) if this ever needs to hold across tabs/restarts.
const MAX_AUTO_APPLIES_PER_SESSION = 5;

useEffect(() => {
  if (chat.mode !== 'auto') return;
  const unapplied = chat.transcript.filter(
    (entry): entry is typeof entry & { plan: NonNullable<typeof entry.plan> } =>
      entry.role === 'change_plan' && entry.plan !== undefined && !autoAppliedPlanIds.current.has(entry.plan.plan_id),
  );
  for (const entry of unapplied) {
    if (autoAppliedPlanIds.current.size >= MAX_AUTO_APPLIES_PER_SESSION) {
      chat.setMode('confirm', false);
      break;
    }
    autoAppliedPlanIds.current.add(entry.plan.plan_id);
    applyChangePlan.mutate(entry.plan.plan_id);
  }
}, [chat.mode, chat.transcript]);
```

Then mount, alongside session creation (a "New chat" button running `useMutation({ mutationFn: () => api.createAssistantSession(selectedProfileId) })` once a provider profile is selected):

```tsx
<ModeToggle mode={chat.mode} onRequestChange={chat.setMode} />
<ChatTranscript
  entries={chat.transcript}
  onApplyPlan={(planId) => applyChangePlan.mutate(planId)}
/>
<form onSubmit={(event) => { event.preventDefault(); chat.sendMessage(draft); setDraft(''); }}>
  <input value={draft} onChange={(event) => setDraft(event.target.value)} aria-label="Message" />
  <Button type="submit">Send</Button>
</form>
```

`ChangePlanCard`'s own Apply button stays clickable even in Auto mode (harmless double-submit guard: `plan.status !== 'draft'` already disables it once the auto-fired apply has moved the plan out of `draft`).

Known trim, noted rather than silently dropped: this task ships "create a new chat and converse in it," not a full multi-session browse/switch list. `AssistantSession`/`AssistantMessage` are still fully persisted (Task 2), so listing and resuming past sessions is a small, separable follow-up against data that already exists — it just isn't built in this slice's UI.

- [ ] **Step 7: Run the full frontend suite**

Run: `cd frontend && npm run typecheck && npm run lint && npm test -- --run`
Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/assistant/useAssistantChat.ts frontend/src/features/assistant/ChatTranscript.tsx \
  frontend/src/features/assistant/ModeToggle.tsx frontend/src/features/assistant/AssistantPage.tsx \
  frontend/tests/use-assistant-chat.test.ts frontend/tests/assistant-page.test.tsx
git commit -m "feat: add chat transcript, streaming, and the Confirm/Auto mode toggle"
```

---

## Task 13: Console suggestion card (blocklist-checked navigate-and-stage)

**Files:**
- Modify: `backend/app/assistant/service.py` (add a system prompt instructing the model to fence suggested console commands)
- Modify: `frontend/src/features/assistant/ChatTranscript.tsx` (detect fenced code blocks in assistant entries, render a `ConsoleSuggestionCard` for each)
- Create: `frontend/src/features/assistant/ConsoleSuggestionCard.tsx`
- Modify: `frontend/src/components/AppShell.tsx` (extend the existing `focusDeviceInInventory`/`focusDeviceId` cross-page mechanism — already used by `TopologyPage`'s `onFocusDevice` — to also carry an optional staged command)
- Modify: `frontend/src/features/inventory/InventoryPage.tsx` (accept and forward a `stagedCommand` prop to wherever the terminal input lives, alongside its existing `focusDeviceId` prop)
- Modify: `frontend/src/features/assistant/AssistantPage.tsx` (pass an `onOpenInTerminal` callback into `ChatTranscript`)
- Test: `frontend/tests/console-suggestion-card.test.tsx`

**Interfaces:**
- Consumes: `POST /assistant-sessions/{id}/stage-command` (Task 9); `AppShell`'s existing `focusDeviceId`/`focusDeviceInInventory` mechanism (`frontend/src/components/AppShell.tsx`, used today by `TopologyPage onFocusDevice={focusDeviceInInventory}` and `InventoryPage focusDeviceId={focusDeviceId}`).
- Produces: `<ConsoleSuggestionCard command={string} deviceId={string} sessionId={string} onOpenInTerminal={(deviceId, command) => void} />`.

Read `AppShell.tsx`'s current `focusDeviceInInventory` implementation in full before this task (it was only observed as a call-site shape during planning, `onFocusDevice={focusDeviceInInventory}`, not its body) — extending its signature to also carry a staged command must not change `TopologyPage`'s existing call, which passes no command and must keep working exactly as today.

- [ ] **Step 1: Add the system prompt (closes a gap from Task 7)**

Task 7's `_build_history` had no system message, so the model was never told to fence suggested commands -- add one. In `backend/app/assistant/service.py`, change `_build_history`:

```python
    def _build_history(self, session_id: UUID) -> list[ChatMessage]:
        stored = self._messages.list_for_session(session_id)
        system = ChatMessage(
            role="system",
            content=(
                "You are a read-only network assistant. You can inspect "
                "registered devices with the provided tools and propose a "
                "Change Plan with propose_change_plan, but you can never "
                "apply anything yourself -- a human always reviews and "
                "confirms every change. When you suggest a command for a "
                "human to run in a device's console terminal, always put it "
                "in a fenced code block (```) by itself, with no other text "
                "inside the fence."
            ),
        )
        return [system, *(ChatMessage(role=m.role.value, content=m.content) for m in stored)]
```

Run: `cd backend && uv run pytest tests/unit/test_assistant_service.py -v`
Expected: still PASS -- `_FakeMessages.list_for_session` returns `[]` in the existing tests, so this only prepends one more history entry the fakes don't assert against.

- [ ] **Step 2: Write the failing frontend test**

```tsx
// frontend/tests/console-suggestion-card.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { api } from '../src/api/network';
import { ConsoleSuggestionCard } from '../src/features/assistant/ConsoleSuggestionCard';

vi.mock('../src/api/network', () => ({
  api: { stageCommand: vi.fn() },
}));

it('checks the blocklist before offering to open the terminal', async () => {
  vi.mocked(api.stageCommand).mockResolvedValue({ allowed: true });
  const onOpen = vi.fn();
  const user = userEvent.setup();
  render(
    <ConsoleSuggestionCard
      command="interface GigabitEthernet0/1"
      deviceId="dev-1"
      sessionId="session-1"
      onOpenInTerminal={onOpen}
    />,
  );

  await user.click(screen.getByRole('button', { name: /open in terminal/i }));

  expect(api.stageCommand).toHaveBeenCalledWith('session-1', 'interface GigabitEthernet0/1');
  expect(onOpen).toHaveBeenCalledWith('dev-1', 'interface GigabitEthernet0/1');
});

it('shows a withheld notice instead of a working button for a blocked command', async () => {
  vi.mocked(api.stageCommand).mockRejectedValue(
    Object.assign(new Error('This command matches a blocked pattern (erase/reload/format/factory-reset)'), {
      code: 'blocked_command',
    }),
  );
  const onOpen = vi.fn();
  const user = userEvent.setup();
  render(
    <ConsoleSuggestionCard command="erase startup-config" deviceId="dev-1" sessionId="session-1" onOpenInTerminal={onOpen} />,
  );

  await user.click(screen.getByRole('button', { name: /open in terminal/i }));

  expect(await screen.findByText(/withheld/i)).toBeVisible();
  expect(onOpen).not.toHaveBeenCalled();
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd frontend && npm test -- console-suggestion-card.test.tsx --run`
Expected: FAIL — module not found.

- [ ] **Step 4: Add the API method and component**

In `frontend/src/api/network.ts`, add:

```ts
  stageCommand: (sessionId: string, command: string) =>
    apiRequest<{ allowed: boolean }>(`/assistant-sessions/${encodeURIComponent(sessionId)}/stage-command`, {
      method: 'POST',
      body: json({ command }),
    }),
```

Create `frontend/src/features/assistant/ConsoleSuggestionCard.tsx`:

```tsx
import { useState } from 'react';
import { api } from '../../api/network';
import { Button } from '../../components/ui/Button';

interface ConsoleSuggestionCardProps {
  command: string;
  deviceId: string;
  sessionId: string;
  onOpenInTerminal: (deviceId: string, command: string) => void;
}

export function ConsoleSuggestionCard({ command, deviceId, sessionId, onOpenInTerminal }: ConsoleSuggestionCardProps) {
  const [withheld, setWithheld] = useState(false);
  const [checking, setChecking] = useState(false);

  return (
    <div className="console-suggestion">
      <pre>{command}</pre>
      {withheld ? (
        <p className="form-error" role="alert">
          This command was withheld because it matches a blocked pattern (erase/reload/format/factory-reset).
          Direct Mode itself still lets you type it manually if you choose to.
        </p>
      ) : (
        <Button
          busy={checking}
          onClick={async () => {
            setChecking(true);
            try {
              await api.stageCommand(sessionId, command);
              onOpenInTerminal(deviceId, command);
            } catch {
              setWithheld(true);
            } finally {
              setChecking(false);
            }
          }}
        >
          Open in terminal
        </Button>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Detect fenced code blocks in `ChatTranscript`**

In `frontend/src/features/assistant/ChatTranscript.tsx`, add a helper and use it for `role === 'assistant'` entries:

```tsx
function splitFencedBlocks(content: string): { text: string; commands: string[] } {
  const commands: string[] = [];
  const text = content.replace(/```[a-z]*\n([\s\S]*?)```/g, (_match, code: string) => {
    commands.push(code.trim());
    return '';
  });
  return { text: text.trim(), commands };
}
```

Extend `ChatTranscriptProps` with `deviceId: string; sessionId: string; onOpenInTerminal: (deviceId: string, command: string) => void;`, and in the assistant-entry branch, render `splitFencedBlocks(entry.content ?? '').text` as before plus one `<ConsoleSuggestionCard key={...} command={cmd} deviceId={deviceId} sessionId={sessionId} onOpenInTerminal={onOpenInTerminal} />` per extracted command.

- [ ] **Step 6: Wire cross-page navigation**

Read `frontend/src/components/AppShell.tsx`'s current `focusDeviceInInventory` function and `focusDeviceId` state in full. Extend the state to `{ deviceId: string; stagedCommand?: string } | undefined` (or add a sibling `stagedCommand` state next to the existing `focusDeviceId` one -- match whichever shape keeps `TopologyPage`'s existing `onFocusDevice={focusDeviceInInventory}` call compiling unchanged, since that call passes only a device id today). Pass the resulting staged command down through to `<InventoryPage focusDeviceId={...} stagedCommand={...} />`. In `InventoryPage.tsx`, forward `stagedCommand` to wherever `TerminalPanel` is rendered inside `DeviceInspector`'s Terminal tab, pre-filling (not auto-sending) the terminal's input with it once, on mount, for the focused device only.

In `AssistantPage.tsx`, pass `onOpenInTerminal={(deviceId, command) => onFocusDeviceWithCommand(deviceId, command)}` down into `ChatTranscript`, where `onFocusDeviceWithCommand` is a prop `AssistantPage` itself receives from `AppShell` (mirroring how `TopologyPage` receives `onFocusDevice`).

- [ ] **Step 7: Run the tests**

Run: `cd frontend && npm test -- console-suggestion-card.test.tsx --run`
Expected: PASS (2 tests).

Run: `cd frontend && npm run typecheck && npm run lint && npm test -- --run`
Expected: all green, including `topology-page.test.tsx`'s existing `onFocusDevice`-related assertions (unmodified call shape).

- [ ] **Step 8: Commit**

```bash
git add backend/app/assistant/service.py frontend/src/api/network.ts \
  frontend/src/features/assistant/ConsoleSuggestionCard.tsx frontend/src/features/assistant/ChatTranscript.tsx \
  frontend/src/components/AppShell.tsx frontend/src/features/inventory/InventoryPage.tsx \
  frontend/src/features/assistant/AssistantPage.tsx frontend/tests/console-suggestion-card.test.tsx
git commit -m "feat: stage AI-suggested console commands for human review instead of live relay"
```

---

## Task 14: Safety docs, `.env.example`, and end-to-end verification

**Files:**
- Modify: `docs/safety-model.md` (§"Secret rules" gains an AI-context line; new subsection documenting the Auto-mode acknowledgment/cap mechanism and the destructive-command blocklist scope)
- Modify: `docs/network-automation-final-plan.md` (mark the Phase 4 slice actually delivered vs. deferred, matching how the Phase 3 interface-slice precedent was annotated, if such an annotation convention exists there — check first)
- Modify: `.env.example` (add `AI_GATEWAY_ENABLED=false` next to `STRUCTURED_WRITES_ENABLED`)
- Test: `backend/tests/integration/test_assistant_full_flow.py` (end-to-end: create provider profile → probe → create session → send message via a fake provider client that requests `propose_change_plan` → apply the resulting plan → assert `ChangePlan.source == "ai_generated"`)

**Interfaces:**
- Consumes: everything from Tasks 1–13. This task adds no new production code, only documentation and one integration test tying the whole slice together.

- [ ] **Step 1: Write the end-to-end test**

```python
# backend/tests/integration/test_assistant_full_flow.py
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _enable_flags(settings):
    settings.ai_gateway_enabled = True
    settings.structured_writes_enabled = True


def test_ai_generated_change_plan_is_tagged_and_applies_through_the_normal_pipeline(
    client: TestClient, container, device
) -> None:
    from app.assistant.client import ChatChunk, ToolCallRequest

    class _FakeClient:
        def __init__(self):
            self.calls = 0

        async def probe_capabilities(self, **_kwargs):
            from app.assistant.client import ProviderCapabilities

            return ProviderCapabilities(supports_streaming=True, supports_tool_calling=True)

        async def stream_chat(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                yield ChatChunk(
                    type="tool_call",
                    tool_call=ToolCallRequest(
                        id="1",
                        name="propose_change_plan",
                        arguments={
                            "device_id": str(device.id),
                            "change_type": "interface_description",
                            "target": "GigabitEthernet0/1",
                            "desired_value": "ai-drafted uplink",
                        },
                    ),
                )
            else:
                yield ChatChunk(type="token", content="Proposed the change above.")

    container.ai_provider_client = _FakeClient()

    profile_id = client.post(
        "/api/provider-profiles",
        json={"name": "Fake", "base_url": "http://fake/v1", "model_id": "test-model"},
    ).json()["id"]
    client.post(f"/api/provider-profiles/{profile_id}/probe")
    session_id = client.post("/api/assistant-sessions", json={"provider_profile_id": profile_id}).json()["id"]

    with client.websocket_connect(f"/ws/assistant/{session_id}") as ws:
        ws.send_json({"type": "user_message", "content": "set the uplink description"})
        frames = []
        while True:
            frame = ws.receive_json()
            frames.append(frame)
            if frame["type"] == "done":
                break

    proposed = next(f for f in frames if f["type"] == "change_plan_proposed")
    plan_id = proposed["payload"]["plan_id"]

    plan_response = client.get(f"/api/change-plans?device_id={device.id}")
    plan = next(p for p in plan_response.json() if p["id"] == plan_id)
    assert plan["source"] == "ai_generated"
```

Adapt `device`/authenticated-`client` fixture usage to match whatever `test_changes_vertical_slice.py` already establishes for a registered, structured-writes-ready device — reuse its setup rather than reintroducing a new one.

- [ ] **Step 2: Run it, expect it to fail first, then pass once wired**

Run: `cd backend && uv run pytest tests/integration/test_assistant_full_flow.py -v`
Expected: PASS once Tasks 1–13 are all committed (this test exercises no new production code, so a failure here means an integration gap between two already-"complete" tasks, not a missing feature).

- [ ] **Step 3: Update `docs/safety-model.md`**

In the `## Secret rules` section, add one line to the existing bullet list: `- AI context and tool results (app/assistant/) join this list -- see the AI context boundary note below.`

Add a new subsection after `## Secret rules`:

```markdown
## AI assistant boundary

- The tool schema sent to the model never includes a write tool, in Confirm
  or Auto mode. `app/assistant/tools.py`'s `READ_ONLY_TOOLS` wraps only
  existing read endpoints; `propose_change_plan` drafts a `DRAFT` Change
  Plan through the same pipeline a manual preview uses and never touches a
  device by itself.
- Tool results pass through `app/assistant/sanitize.py`'s `scrub_secrets`
  before they are serialized into model context, on top of already being
  built from the same response schemas already served over the public REST
  API.
- Auto mode is opt-in per `AssistantSession`, requires one explicit risk
  acknowledgment, always resets to Confirm for a new session, and is capped
  by `auto_apply_count` before it requires re-acknowledgment.
- The destructive-command blocklist (`erase`/`reload`/`format`/`factory
  reset`, `app/assistant/blocklist.py`) is unconditional in both modes. It
  governs only what this application will stage from an AI suggestion; it
  does not and cannot restrict a human typing directly into an already-open
  Direct Mode terminal on their own initiative.
```

- [ ] **Step 4: Update `.env.example`**

Add next to `STRUCTURED_WRITES_ENABLED`:

```
AI_GATEWAY_ENABLED=false
```

- [ ] **Step 5: Run the full verification suite**

Run: `cd backend && uv run ruff check && uv run pyright && uv run pytest`
Run: `cd frontend && npm run typecheck && npm run lint && npm test -- --run && npm run build`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add backend/tests/integration/test_assistant_full_flow.py docs/safety-model.md .env.example
git commit -m "docs: document the AI assistant safety boundary and add an end-to-end proof"
```
