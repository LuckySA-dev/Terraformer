from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.analysis.client import RawFinding
from app.container import ApplicationContainer
from app.core.errors import AnalysisNoConfigsError
from app.jobs import tasks
from app.models import FindingCategory
from tests.fakes import FakeBatfishClient


def _register_cisco(client: TestClient, profile_id: str, address: str) -> str:
    connection = {
        "management_address": address,
        "port": 22,
        "vendor": "cisco_iosxe",
        "credential_profile_id": profile_id,
        "ssh_compatibility": "modern",
    }
    candidate = client.post(
        "/api/ssh-host-key-candidates",
        json={key: value for key, value in connection.items() if key != "name"},
    )
    assert candidate.status_code == 201, candidate.text
    created = client.post(
        "/api/devices",
        json={
            "name": f"sw-{address}",
            **connection,
            "host_key_candidate_id": candidate.json()["id"],
        },
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _capture(client: TestClient, device_id: str, container: ApplicationContainer, monkeypatch) -> None:  # noqa: E501
    monkeypatch.setattr(tasks, "get_default_container", lambda: container)
    queued = client.post(f"/api/devices/{device_id}/config-snapshots")
    assert queued.status_code == 202, queued.text
    tasks.execute_job(queued.json()["id"])


def test_analysis_reports_completeness_including_excluded_devices(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    fake_batfish: FakeBatfishClient,
    monkeypatch,
) -> None:
    profile_id = str(credential_profile["id"])
    analysed = _register_cisco(authenticated_client, profile_id, "192.0.2.10")
    _register_cisco(authenticated_client, profile_id, "192.0.2.11")  # no snapshot
    _capture(authenticated_client, analysed, container, monkeypatch)

    queued = authenticated_client.post("/api/analysis-snapshots")
    assert queued.status_code == 202, queued.text
    tasks.execute_job(queued.json()["id"])

    listed = authenticated_client.get("/api/analysis-snapshots")
    assert listed.status_code == 200, listed.text
    snapshot = listed.json()[0]

    assert snapshot["status"] == "ready"
    assert snapshot["completeness"]["analysed_device_count"] == 1
    assert snapshot["completeness"]["registered_device_count"] == 2
    exclusions = {
        item["reason"]: item["count"] for item in snapshot["completeness"]["exclusions"]
    }
    assert exclusions["no_snapshot"] == 1


def test_only_sanitized_configuration_reaches_the_backend(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    fake_batfish: FakeBatfishClient,
    monkeypatch,
) -> None:
    """The running-config fixture contains secrets; none may reach Batfish."""
    profile_id = str(credential_profile["id"])
    device_id = _register_cisco(authenticated_client, profile_id, "192.0.2.10")
    _capture(authenticated_client, device_id, container, monkeypatch)

    queued = authenticated_client.post("/api/analysis-snapshots")
    tasks.execute_job(queued.json()["id"])

    sent = "\n".join(
        content for configs in fake_batfish.snapshots.values() for content in configs.values()
    )
    assert sent, "no configuration was handed to the backend"
    assert "SANITIZED_ENABLE_HASH" not in sent
    assert "SANITIZED_USER_HASH" not in sent
    assert "SANITIZED_COMMUNITY" not in sent
    assert "[REDACTED]" in sent


def test_findings_are_persisted_and_listable(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    fake_batfish: FakeBatfishClient,
    monkeypatch,
) -> None:
    fake_batfish.parse_findings_result = (
        RawFinding(
            category=FindingCategory.UNDEFINED_REFERENCE,
            # The fixture running-config declares "hostname edge-rtr-01"; that
            # is what batfish_hostname() reads, not the device's registered
            # display name.
            hostname="edge-rtr-01",
            structure_type="ipv4 access-list",
            structure_name="MISSING_ACL",
            detail="interface GigabitEthernet1 references an undefined structure",
            line_number=42,
        ),
    )
    profile_id = str(credential_profile["id"])
    device_id = _register_cisco(authenticated_client, profile_id, "192.0.2.10")
    _capture(authenticated_client, device_id, container, monkeypatch)

    queued = authenticated_client.post("/api/analysis-snapshots")
    tasks.execute_job(queued.json()["id"])
    snapshot_id = authenticated_client.get("/api/analysis-snapshots").json()[0]["id"]

    findings = authenticated_client.get(
        f"/api/analysis-snapshots/{snapshot_id}/findings",
        params={"category": "undefined_reference"},
    )

    assert findings.status_code == 200, findings.text
    assert findings.json()[0]["structure_name"] == "MISSING_ACL"
    assert findings.json()[0]["device_id"] == device_id


def test_analysis_without_any_snapshot_is_rejected(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    monkeypatch,
) -> None:
    _register_cisco(authenticated_client, str(credential_profile["id"]), "192.0.2.10")

    queued = authenticated_client.post("/api/analysis-snapshots")
    assert queued.status_code == 202
    monkeypatch.setattr(tasks, "get_default_container", lambda: container)
    job_id = queued.json()["id"]

    with pytest.raises(AnalysisNoConfigsError):
        tasks.execute_job(job_id)

    state = authenticated_client.get(f"/api/jobs/{job_id}").json()
    assert state["state"] == "failed"
    assert state["error_code"] == "analysis_no_configs"


def test_every_endpoint_fails_closed_when_analysis_is_disabled(
    authenticated_client: TestClient,
    container: ApplicationContainer,
) -> None:
    container.settings.analysis_enabled = False

    for method, path in (
        ("post", "/api/analysis-snapshots"),
        ("get", "/api/analysis-snapshots"),
    ):
        response = getattr(authenticated_client, method)(path)
        assert response.status_code == 403, (path, response.text)
        assert response.json()["error"]["code"] == "analysis_disabled_by_policy"


def test_only_one_analysis_may_be_active(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    monkeypatch,
) -> None:
    """Parsing is CPU- and memory-intensive and Batfish is a single instance."""
    profile_id = str(credential_profile["id"])
    device_id = _register_cisco(authenticated_client, profile_id, "192.0.2.10")
    _capture(authenticated_client, device_id, container, monkeypatch)

    first = authenticated_client.post("/api/analysis-snapshots")
    assert first.status_code == 202, first.text
    second = authenticated_client.post("/api/analysis-snapshots")

    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] == "conflict"
    assert "analysis" in second.json()["error"]["message"].lower()


def test_retention_keeps_only_the_configured_number_of_snapshots(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    monkeypatch,
) -> None:
    container.settings.analysis_retained_snapshots = 2
    profile_id = str(credential_profile["id"])
    device_id = _register_cisco(authenticated_client, profile_id, "192.0.2.10")
    _capture(authenticated_client, device_id, container, monkeypatch)

    for _ in range(3):
        queued = authenticated_client.post("/api/analysis-snapshots")
        tasks.execute_job(queued.json()["id"])

    assert len(authenticated_client.get("/api/analysis-snapshots").json()) == 2
