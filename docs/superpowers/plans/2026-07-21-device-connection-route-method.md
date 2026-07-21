# Device Connection Route Method Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Return 405 rather than a UUID validation error when the POST-only candidate connection-test URL is opened with GET.

**Architecture:** Keep the existing static POST endpoint and constrain only the overlapping device-detail GET route with a UUID path converter. Prove the behavior through the real FastAPI router using an authenticated integration test.

**Tech Stack:** Python 3.12, FastAPI, Starlette routing, pytest, Ruff, Pyright

## Global Constraints

- Do not use Git commands, commits, pushes, branches, or history operations.
- Do not contact network devices; routine tests must remain network-free.
- Preserve the candidate POST request and response contract.
- Preserve all Safety Level D structured-write declarations.

---

### Task 1: Route-method regression

**Files:**
- Create: `backend/tests/integration/test_device_route_methods.py`
- Modify: `backend/app/api/devices.py`
- Modify: `docs/IMPLEMENTATION_STATUS.md`

**Interfaces:**
- Consumes: `POST /api/devices/connection-test` and `GET /api/devices/{device_id}`
- Produces: `GET /api/devices/connection-test` returns HTTP 405 with `Allow: POST`

- [x] **Step 1: Write the failing test**

```python
def test_connection_test_rejects_get_without_parsing_route_name_as_uuid(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.get("/api/devices/connection-test")

    assert response.status_code == 405
    assert response.headers["allow"] == "POST"
```

- [x] **Step 2: Run the test to verify RED**

Run:

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m pytest tests/integration/test_device_route_methods.py::test_connection_test_rejects_get_without_parsing_route_name_as_uuid -q
```

Expected: FAIL because the current response status is 422.

- [x] **Step 3: Implement the minimal route constraint**

```python
@router.get("/{device_id:uuid}", response_model=DeviceView)
def get_device(
    device_id: UUID,
```

- [x] **Step 4: Run the focused test to verify GREEN**

Run the Step 2 command again.

Expected: one passing test.

- [x] **Step 5: Run backend verification**

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m ruff format --check app/api/devices.py tests/integration/test_device_route_methods.py
.\.venv\Scripts\python.exe -m ruff check --no-cache .
.\.venv\Scripts\pyright.exe
.\.venv\Scripts\python.exe -m pytest
```

Expected: formatting, lint, and type checks pass; all routine tests pass with
the opt-in lab test skipped.

- [x] **Step 6: Record conservative evidence**

Add a dated verification row to `docs/IMPLEMENTATION_STATUS.md` describing the
405 route regression, network-free checks, and the fact that no hardware was
contacted. Do not alter capability support status.
