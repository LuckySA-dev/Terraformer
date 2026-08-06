# EVE-NG and GNS3 Local-Lab Provider Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import EVE-NG and GNS3 projects as read-only observed topology while keeping device SSH access, provider secrets, and inventory registration separate.

**Architecture:** The backend owns encrypted provider profiles, exact-target network policy, provider-specific response adapters, and a normalized last-good projection. The Topology page polls only while mounted, displays stale data after provider failures, and allows explicit binding from an external node to an existing inventory device without creating or editing devices.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy/Alembic, `httpx` 0.28.1, stdlib `ipaddress/socket/ssl`, React 19, TanStack Query, Cytoscape, Pytest, Vitest.

## Global Constraints

- This plan depends on the Phase 1-2 readiness plan and its mandatory SSH trust path.
- Provider traffic is backend-only; provider credentials, cookies, certificates, and raw payloads never reach the browser or logs.
- Provider operations are read-only: version probe, projects, nodes, and links. EVE login/logout calls are allowed only to establish and destroy the bounded read session.
- Redirects are disabled. Public, multicast, unspecified, and broadcast targets fail closed.
- HTTP is allowed only for an exact loopback/private target with stored acknowledgment.
- Verified TLS is default. Pinned TLS trusts the explicitly confirmed certificate, not `verify=False`.
- Poll interval is 60 seconds by default and bounded to 30-300 seconds.
- Import never creates or modifies inventory devices and never infers binding from name, address, or console port.
- Failed refresh preserves the last successful projection and marks it stale.
- No emulator start/stop/reload/create/update/delete endpoint, scheduler, WebSocket topology stream, or new dependency.
- Do not change `docs/network-automation-final-plan.md`.

---

## File Structure

- `backend/app/models/entities.py`: provider profile plus normalized external node/link records.
- `backend/app/services/provider_profiles.py`: encrypted profile CRUD and separate provider credential vault.
- `backend/app/services/provider_network.py`: URL, resolution, HTTP acknowledgment, TLS, certificate-pin, redirect, size, and timeout boundary.
- `backend/app/providers/base.py`: normalized project/node/link types and four-operation adapter protocol.
- `backend/app/providers/eve_ng.py`, `gns3.py`: bounded vendor response mapping only.
- `backend/app/services/external_topology.py`: probe/import/replace-last-good/manual-bind orchestration.
- `backend/app/api/provider_profiles.py`, `external_topology.py`: authenticated REST contracts.
- `frontend/src/features/topology/ProviderProfilesDialog.tsx`: profile and certificate/HTTP acknowledgment flow.
- `frontend/src/features/topology/TopologyPage.tsx`: project selection, page-mounted polling, stale state, and explicit binding.

### Task 1: Persist encrypted provider profiles separately from device credentials

**Files:**
- Create: `backend/app/schemas/provider_profiles.py`
- Create: `backend/app/repositories/provider_profiles.py`
- Create: `backend/app/services/provider_profiles.py`
- Create: `backend/app/api/provider_profiles.py`
- Create: `backend/migrations/versions/20260806_0005_lab_provider_profiles.py`
- Modify: `backend/app/models/entities.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/api/router.py`
- Modify: `backend/app/container.py`
- Test: `backend/tests/unit/test_provider_profiles.py`
- Test: `backend/tests/integration/test_provider_profiles_vertical_slice.py`
- Test: `backend/tests/integration/test_migrations.py`

**Interfaces:**
- Consumes: existing `EnvelopeCipher`, repository/service/API patterns.
- Produces: `ProviderCredentialVault`, `ProviderProfileService`, and secret-free `ProviderProfileView`.

- [ ] **Step 1: Write failing encryption and API tests**

```python
def test_provider_profile_response_and_database_never_expose_password(client, session):
    response = client.post("/api/lab-provider-profiles", json=provider_input())
    assert response.status_code == 201
    body = response.json()
    assert "password" not in body
    row = session.scalar(select(LabProviderProfile))
    assert b"fixture-password" not in row.encrypted_secret


def test_poll_interval_is_bounded(client):
    response = client.post("/api/lab-provider-profiles", json=provider_input(poll_interval_seconds=10))
    assert response.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `Set-Location backend; .\.venv\Scripts\python.exe -m pytest tests/unit/test_provider_profiles.py tests/integration/test_provider_profiles_vertical_slice.py tests/integration/test_migrations.py -q`

Expected: FAIL because provider profile types and table do not exist.

- [ ] **Step 3: Add model, enum, and migration**

```python
class LabProviderType(StrEnum):
    EVE_NG = "eve_ng"
    GNS3 = "gns3"

class ProviderTransportMode(StrEnum):
    VERIFIED_TLS = "verified_tls"
    PINNED_TLS = "pinned_tls"
    PRIVATE_HTTP = "private_http"

class LabProviderProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "lab_provider_profiles"
    name: Mapped[str] = mapped_column(String(100), unique=True)
    provider_type: Mapped[LabProviderType] = mapped_column(enum_type(LabProviderType, "lab_provider_type"))
    base_url: Mapped[str] = mapped_column(String(1024))
    encrypted_secret: Mapped[bytes] = mapped_column(LargeBinary)
    transport_mode: Mapped[ProviderTransportMode] = mapped_column(enum_type(ProviderTransportMode, "provider_transport_mode"))
    certificate_fingerprint: Mapped[str | None] = mapped_column(String(128))
    pinned_certificate_pem: Mapped[str | None] = mapped_column(Text)
    insecure_http_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    poll_interval_seconds: Mapped[int] = mapped_column(Integer, default=60)
    detected_version: Mapped[str | None] = mapped_column(String(128))
    last_result_code: Mapped[str | None] = mapped_column(String(100))
```

Add DB checks for poll range and transport requirements. `pinned_tls` requires PEM/fingerprint; `private_http` requires acknowledgment; other combinations reject.

- [ ] **Step 4: Reuse the cipher with a separate purpose**

```python
@dataclass(frozen=True, slots=True)
class ProviderCredentialMaterial:
    username: str | None
    password: str | None

class ProviderCredentialVault:
    def __init__(self, cipher: EnvelopeCipher) -> None:
        self._cipher = cipher

    def encrypt(self, profile_id: UUID, material: ProviderCredentialMaterial) -> bytes:
        payload = json.dumps({"version": 1, "username": material.username, "password": material.password}, separators=(",", ":"), sort_keys=True)
        return self._cipher.encrypt(payload.encode(), aad=f"provider-profile:v1:{profile_id}".encode())

    def decrypt(self, profile: LabProviderProfile) -> ProviderCredentialMaterial:
        payload = json.loads(self._cipher.decrypt(profile.encrypted_secret, aad=f"provider-profile:v1:{profile.id}".encode()))
        if payload.get("version") != 1:
            raise ArtifactIntegrityError("Provider credential payload is invalid")
        return ProviderCredentialMaterial(payload.get("username"), payload.get("password"))
```

Construct it with `EnvelopeCipher(key_provider, purpose="lab-provider-profiles")`. Responses expose only `has_username` and `has_password` booleans.

- [ ] **Step 5: Implement CRUD with no connection side effects**

Use `/api/lab-provider-profiles`. Create/update validates shape but does not contact the provider. Delete cascades only external topology records owned by that profile. Return stable typed conflicts; never raw SQL/cipher errors.

- [ ] **Step 6: Run tests and commit**

Run the Step 2 command. Expected: PASS.

```powershell
git add backend/app backend/migrations/versions/20260806_0005_lab_provider_profiles.py backend/tests
git commit -m "feat: add encrypted lab provider profiles"
```

### Task 2: Enforce the local-provider network and certificate boundary

**Files:**
- Create: `backend/app/services/provider_network.py`
- Create: `backend/app/schemas/provider_certificates.py`
- Modify: `backend/app/api/provider_profiles.py`
- Modify: `backend/app/core/errors.py`
- Modify: `backend/pyproject.toml`
- Modify: `backend/uv.lock`
- Test: `backend/tests/unit/test_provider_network.py`
- Test: `backend/tests/integration/test_provider_profiles_vertical_slice.py`

**Interfaces:**
- Consumes: stdlib URL/IP/DNS/TLS APIs and existing `httpx==0.28.1` currently in the dev group.
- Produces: `validate_provider_target(base_url, mode) -> ValidatedProviderTarget`, `ProviderHttpClient.get_json(path) -> object`, and 15-minute certificate candidates.

- [ ] **Step 1: Write failing trust-boundary tests**

```python
@pytest.mark.parametrize("url", [
    "https://198.51.100.10", "https://224.0.0.1", "https://0.0.0.0", "file:///tmp/x"
])
def test_rejects_non_local_provider_targets(url, fake_dns):
    with pytest.raises(ProviderURLRejectedError):
        validate_provider_target(url, ProviderTransportMode.VERIFIED_TLS, resolver=fake_dns)


def test_redirect_is_not_followed(fake_httpx):
    client = provider_client(response(status=302, headers={"location": "https://example.test"}))
    with pytest.raises(ProviderRedirectRejectedError):
        client.get_json("/v2/projects")


def test_pinned_tls_uses_confirmed_certificate_as_trust_anchor(fake_tls):
    context = pinned_ssl_context(CONFIRMED_PEM)
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED
```

Also test DNS results containing any public address, hostname revalidation before every request, private HTTP without acknowledgment, certificate change, invalid JSON, response larger than 2 MiB, and 5-second connect/15-second response timeouts.

- [ ] **Step 2: Run tests to verify they fail**

Run: `Set-Location backend; .\.venv\Scripts\python.exe -m pytest tests/unit/test_provider_network.py -q`

Expected: FAIL because the network boundary does not exist.

- [ ] **Step 3: Move existing httpx into runtime dependencies**

Keep version `0.28.1`; do not add another HTTP library. Run `uv lock` to update the lock metadata only.

- [ ] **Step 4: Implement URL and address validation**

```python
def address_allowed(value: str) -> bool:
    address = ip_address(value)
    return (address.is_private or address.is_loopback) and not (
        address.is_multicast or address.is_unspecified
    )
```

Normalize to `scheme://host:port` with no userinfo, query, fragment, or path other than a single trailing slash. Resolve with `socket.getaddrinfo`; require at least one result and require every result to pass `address_allowed`. Re-run immediately before each request. Set `follow_redirects=False` and reject every 3xx.

- [ ] **Step 5: Implement confirmed certificate pinning**

`POST /api/lab-provider-certificate-candidates` performs an unauthenticated TLS handshake to the exact target, returns only SHA-256 fingerprint and 15-minute candidate ID, and keeps PEM in Redis. Profile create with `pinned_tls` requires the candidate ID plus explicit confirmation; it stores PEM/fingerprint. Build a normal `ssl.create_default_context()`, call `load_verify_locations(cadata=pinned_certificate_pem)`, and keep `CERT_REQUIRED` plus hostname checking. Never call `verify=False`.

- [ ] **Step 6: Implement bounded JSON GET**

```python
class ProviderHttpClient:
    def get_json(self, path: str) -> object:
        if path not in self._allowed_paths:
            raise ProviderOperationRejectedError()
        response = self._client.get(path, headers={"accept": "application/json"})
        if response.is_redirect: raise ProviderRedirectRejectedError()
        if len(response.content) > 2 * 1024 * 1024: raise ProviderResponseTooLargeError()
        return response.json()
```

Map URL, route, TLS, certificate, auth, unavailable, rate-limit, version/schema, and malformed response to fixed sanitized codes. Log profile ID/code only.

- [ ] **Step 7: Run tests and commit**

Run the Step 2 command plus Ruff/Pyright for the new module. Expected: PASS.

```powershell
git add backend/app backend/tests backend/pyproject.toml backend/uv.lock
git commit -m "feat: constrain local provider transport"
```

### Task 3: Implement bounded EVE-NG and GNS3 read adapters

**Files:**
- Create: `backend/app/providers/__init__.py`
- Create: `backend/app/providers/base.py`
- Create: `backend/app/providers/eve_ng.py`
- Create: `backend/app/providers/gns3.py`
- Create: `backend/tests/fixtures/providers/eve_ng/*.json`
- Create: `backend/tests/fixtures/providers/gns3/*.json`
- Create: `backend/tests/unit/test_eve_ng_provider.py`
- Create: `backend/tests/unit/test_gns3_provider.py`

**Interfaces:**
- Consumes: `ProviderHttpClient` and decrypted provider credentials.
- Produces: `LabProviderAdapter.probe()`, `list_projects()`, `list_nodes(project_id)`, `list_links(project_id)` returning normalized frozen dataclasses.

- [ ] **Step 1: Write failing contract tests**

```python
def test_gns3_maps_only_required_project_node_and_link_fields(fixture_client):
    adapter = GNS3Provider(fixture_client)
    project = adapter.list_projects()[0]
    nodes = adapter.list_nodes(project.id)
    links = adapter.list_links(project.id)
    assert nodes[0] == LabNode("n1", "Core-SW", "qemu", "started", 120, 80)
    assert links[0].endpoints == (LabEndpoint("n1", "Gi0/0"), LabEndpoint("n2", "Gi0/1"))


def test_eve_cookie_is_discarded_after_bounded_session(fake_client):
    with EVEProvider(fake_client, credentials()) as adapter:
        adapter.list_projects()
    assert fake_client.cookies == {}
```

Add malformed/missing/oversized/unexpected-field/version tests and assert no mutation path is accepted.

- [ ] **Step 2: Run tests to verify they fail**

Run: `Set-Location backend; .\.venv\Scripts\python.exe -m pytest tests/unit/test_eve_ng_provider.py tests/unit/test_gns3_provider.py -q`

Expected: FAIL because adapters do not exist.

- [ ] **Step 3: Define the narrow provider contract**

```python
from collections.abc import Sequence

class LabProviderAdapter(Protocol):
    def probe(self) -> ProviderProbe: raise NotImplementedError
    def list_projects(self) -> Sequence[LabProject]: raise NotImplementedError
    def list_nodes(self, project_id: str) -> Sequence[LabNode]: raise NotImplementedError
    def list_links(self, project_id: str) -> Sequence[LabLink]: raise NotImplementedError
```

Use frozen dataclasses for `ProviderProbe`, `LabProject`, `LabNode`, `LabEndpoint`, and `LabLink`. Bound identifiers/labels to 255 chars, at most 1,000 nodes and 2,000 links, and reject duplicate IDs or links referencing missing endpoints.

- [ ] **Step 4: Implement provider-specific mapping only**

GNS3 uses Basic authentication headers and GET endpoints for version, projects, nodes, and links. EVE creates one in-memory cookie session; authentication/logout are the only non-GET provider calls and cannot mutate labs. The adapters never expose raw dicts outside their modules.

- [ ] **Step 5: Run tests and commit**

Run the Step 2 command. Expected: PASS with fixture clients only.

```powershell
git add backend/app/providers backend/tests/fixtures/providers backend/tests/unit
git commit -m "feat: read EVE-NG and GNS3 topology"
```

### Task 4: Store last-good external topology and explicit inventory bindings

**Files:**
- Create: `backend/app/repositories/external_topology.py`
- Create: `backend/app/services/external_topology.py`
- Create: `backend/app/schemas/external_topology.py`
- Create: `backend/app/api/external_topology.py`
- Create: `backend/migrations/versions/20260806_0006_external_topology.py`
- Modify: `backend/app/models/entities.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/api/router.py`
- Test: `backend/tests/integration/test_external_topology_vertical_slice.py`
- Test: `backend/tests/integration/test_model_invariants.py`
- Test: `backend/tests/integration/test_migrations.py`

**Interfaces:**
- Consumes: normalized adapter dataclasses from Task 3 and existing registered `Device` records.
- Produces: `ExternalTopologyService.refresh(profile_id, project_id) -> ExternalTopologyView` and `bind(node_id, device_id | None)`.

- [ ] **Step 1: Write failing replacement/binding tests**

```python
def test_failed_refresh_keeps_last_good_projection(client, seeded_projection, provider_failure):
    response = client.get(f"/api/lab-provider-profiles/{PROFILE}/projects/{PROJECT}/topology?refresh=true")
    assert response.status_code == 200
    assert response.json()["stale"] is True
    assert response.json()["last_error_code"] == "provider_unavailable"
    assert response.json()["nodes"] == seeded_projection["nodes"]


def test_binding_never_mutates_inventory(client, seeded_external_node, seeded_device, session):
    before = device_tuple(seeded_device)
    response = client.patch(f"/api/external-topology-nodes/{seeded_external_node.id}/binding", json={"device_id": str(seeded_device.id)})
    assert response.status_code == 200
    assert device_tuple(session.get(Device, seeded_device.id)) == before
```

Also test stable replacement preserves binding, removed external nodes are deleted only after successful import, duplicate IDs fail the transaction, and binding requires an existing device.

- [ ] **Step 2: Run tests to verify they fail**

Run: `Set-Location backend; .\.venv\Scripts\python.exe -m pytest tests/integration/test_external_topology_vertical_slice.py tests/integration/test_model_invariants.py tests/integration/test_migrations.py -q`

Expected: FAIL because external topology persistence does not exist.

- [ ] **Step 3: Add normalized records**

Create `ExternalTopologyNode` unique on `(provider_profile_id, project_id, external_node_id)` with label, node_type, observed_status, x, y, observed_at, and nullable `bound_device_id`. Create `ExternalTopologyLink` unique on `(provider_profile_id, project_id, external_link_id)` with source/target external node IDs and port labels. Add bounded column/check constraints and cascade only from provider profile.

- [ ] **Step 4: Implement atomic successful replacement**

Fetch and validate the complete projection before opening the replacement transaction. Upsert nodes by stable key while retaining `bound_device_id`, replace links, delete vanished nodes, set observed timestamp/version/result, then commit. On any provider/validation failure, roll back, store only sanitized profile result code, and return the prior projection as stale if it exists.

- [ ] **Step 5: Add authenticated APIs**

- `POST /api/lab-provider-profiles/{id}/probe`
- `GET /api/lab-provider-profiles/{id}/projects`
- `GET /api/lab-provider-profiles/{id}/projects/{project_id}/topology?refresh=true`
- `PATCH /api/external-topology-nodes/{node_id}/binding`

Project IDs are percent-decoded once and compared as bounded opaque identifiers. No inventory-create body or provider mutation route exists.

- [ ] **Step 6: Run tests and commit**

Run the Step 2 command. Expected: PASS.

```powershell
git add backend/app backend/migrations/versions/20260806_0006_external_topology.py backend/tests
git commit -m "feat: persist external lab topology"
```

### Task 5: Add provider UI, mounted polling, stale display, and verification

**Files:**
- Create: `frontend/src/features/topology/ProviderProfilesDialog.tsx`
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/api/network.ts`
- Modify: `frontend/src/features/topology/topology.ts`
- Modify: `frontend/src/features/topology/TopologyPage.tsx`
- Modify: `frontend/src/styles.css`
- Create: `frontend/tests/provider-profiles-dialog.test.tsx`
- Modify: `frontend/tests/topology-page.test.tsx`
- Modify: `docs/development.md`
- Modify: `docs/lab-test-guide.md`
- Modify: `docs/IMPLEMENTATION_STATUS.md`
- Modify: `docs/CAPABILITY_MATRIX.md`

**Interfaces:**
- Consumes: Task 4 REST contracts.
- Produces: secret-safe provider management, project selection, polling cleanup, external graph labels, and explicit binding UI.

- [ ] **Step 1: Write failing UI tests**

```tsx
it('polls only while topology is mounted and uses the saved interval', async () => {
  vi.useFakeTimers();
  const view = renderTopology({ poll_interval_seconds: 60 });
  await vi.advanceTimersByTimeAsync(60_000);
  expect(refreshTopology).toHaveBeenCalledTimes(2); // initial + one poll
  view.unmount();
  await vi.advanceTimersByTimeAsync(60_000);
  expect(refreshTopology).toHaveBeenCalledTimes(2);
});

it('labels provider nodes and requires manual binding', async () => {
  renderTopology({ externalNode: unboundNode });
  expect(screen.getByText(/external provider/i)).toBeVisible();
  expect(createDevice).not.toHaveBeenCalled();
  await user.selectOptions(screen.getByLabelText(/bind existing device/i), DEVICE_ID);
  expect(bindNode).toHaveBeenCalledWith(unboundNode.id, DEVICE_ID);
});
```

Add private HTTP acknowledgment, certificate fingerprint confirmation, password non-redisplay, stale alert, virtual label, and observed/manual/external legend tests.

- [ ] **Step 2: Run tests to verify they fail**

Run: `Set-Location frontend; npm.cmd test -- --run tests/provider-profiles-dialog.test.tsx tests/topology-page.test.tsx`

Expected: FAIL because provider UI/types do not exist.

- [ ] **Step 3: Add minimal provider profile UI**

Use native URL/text/password/select/number inputs. For pinned TLS, collect and display fingerprint then require a checkbox before save. For private HTTP, show the cleartext credential warning and require acknowledgment. Never prefill or return stored passwords.

- [ ] **Step 4: Merge external elements into the existing graph**

Extend `TopologyElement.data.kind` with `external`. Prefix IDs with `external:<profile>:<project>:<node>`, use provider-supplied positions when finite, label external links with supplied port pairs, and preserve `registered`, `observed`, and `manual-unverified` distinctions. A binding changes visual association only; it does not replace the external record or inventory node.

- [ ] **Step 5: Poll with existing TanStack Query only**

Set `refetchInterval` to the saved 30-300 second profile value and rely on component unmount cleanup. On stale response, retain graph data and show timestamp plus sanitized Retry guidance. Do not add a scheduler, background worker, WebSocket, or browser secret storage.

- [ ] **Step 6: Document exact connectivity without changing host networking**

Add same-host VM and management-LAN examples. Mention `host.docker.internal` only when the emulator API/SSH service is published on the host. State that Terraformer never creates routes, firewall rules, bridges, TAP/cloud interfaces, or NAT.

- [ ] **Step 7: Run complete verification and commit**

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m ruff check --no-cache .
.\.venv\Scripts\pyright.exe
.\.venv\Scripts\python.exe -m pytest
Set-Location ..\frontend
npm.cmd run verify
Set-Location ..
docker compose -f deploy/compose.yml config --quiet
docker compose -f deploy/compose.dev.yml config --quiet
node .gitnexus/run.cjs detect-changes -r "C:\Users\User\Desktop\Coding\Terraformer" --scope compare --base-ref main
```

Expected: all routine tests pass without network access; scope contains provider profile/import/topology UI only.

```powershell
git add frontend/src frontend/tests docs/development.md docs/lab-test-guide.md docs/IMPLEMENTATION_STATUS.md docs/CAPABILITY_MATRIX.md
git commit -m "feat: show read-only local lab topology"
```

Keep both providers `Automated verification passed; virtual-lab validation pending` until an explicitly authorized provider run is recorded. A pass for one provider does not promote the other.
