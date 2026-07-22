from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.container import ApplicationContainer
from app.jobs import tasks
from app.models import Event, Job


def test_bounded_discovery_requires_explicit_candidate_approval(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    response = authenticated_client.post(
        "/api/discovery-jobs",
        json={
            "cidr": "192.0.2.0/30",
            "ports": [22, 23],
            "concurrency": 2,
            "connect_timeout_seconds": 0.25,
            "probe_delay_ms": 10,
        },
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    duplicate = authenticated_client.post(
        "/api/discovery-jobs",
        json={"cidr": "198.51.100.0/30"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["message"] == "A discovery job is already active"
    monkeypatch.setattr(tasks, "get_default_container", lambda: container)
    monkeypatch.setattr(
        tasks,
        "run_discovery",
        lambda _request, *, connection_limit: {
            "cidr": "192.0.2.0/30",
            "ports": [22, 23],
            "scanned_count": 4,
            "concurrency": min(2, connection_limit),
            "candidates": [{"management_address": "192.0.2.1", "port": 22}],
            "open_endpoints": [{"management_address": "192.0.2.1", "port": 23}],
        },
    )
    tasks.execute_job(job_id)

    assert authenticated_client.get("/api/devices").json() == []
    completed = authenticated_client.get(f"/api/jobs/{job_id}")
    assert completed.status_code == 200
    assert completed.json()["result"]["candidates"] == [
        {"management_address": "192.0.2.1", "port": 22}
    ]
    with session_factory() as session:
        job = session.get(Job, UUID(job_id))
        assert job is not None
        assert "credential_profile_id" not in job.input

    rejected = authenticated_client.post(
        f"/api/discovery-jobs/{job_id}/approve",
        json={
            "name": "not-a-candidate",
            "management_address": "192.0.2.2",
            "port": 22,
            "vendor": "cisco_iosxe",
            "credential_profile_id": credential_profile["id"],
        },
    )
    assert rejected.status_code == 409
    assert authenticated_client.get("/api/devices").json() == []

    informational_only = authenticated_client.post(
        f"/api/discovery-jobs/{job_id}/approve",
        json={
            "name": "open-but-not-ssh",
            "management_address": "192.0.2.1",
            "port": 23,
            "vendor": "cisco_iosxe",
            "credential_profile_id": credential_profile["id"],
        },
    )
    assert informational_only.status_code == 409
    assert authenticated_client.get("/api/devices").json() == []

    approved = authenticated_client.post(
        f"/api/discovery-jobs/{job_id}/approve",
        json={
            "name": "discovered-edge",
            "management_address": "192.0.2.1",
            "port": 22,
            "vendor": "cisco_iosxe",
            "credential_profile_id": credential_profile["id"],
        },
    )
    assert approved.status_code == 201, approved.text
    assert approved.json()["management_address"] == "192.0.2.1"
    assert len(authenticated_client.get("/api/devices").json()) == 1
    with session_factory() as session:
        created_event = session.query(Event).filter_by(event_type="device.created").one()
        assert str(created_event.job_id) == job_id


def test_discovery_request_rejects_oversized_range(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.post(
        "/api/discovery-jobs",
        json={"cidr": "192.0.2.0/24"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_discovery_candidate_cannot_select_or_escalate_compatibility(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    transport_factory,
    monkeypatch,
) -> None:
    queued = authenticated_client.post(
        "/api/discovery-jobs",
        json={"cidr": "192.0.2.0/30"},
    )
    job_id = queued.json()["id"]
    monkeypatch.setattr(tasks, "get_default_container", lambda: container)
    monkeypatch.setattr(
        tasks,
        "run_discovery",
        lambda _request, *, connection_limit: {
            "cidr": "192.0.2.0/30",
            "ports": [22],
            "scanned_count": 2,
            "concurrency": min(2, connection_limit),
            "candidates": [
                {
                    "management_address": "192.0.2.1",
                    "port": 22,
                }
            ],
            "open_endpoints": [],
        },
    )
    tasks.execute_job(job_id)

    approved = authenticated_client.post(
        f"/api/discovery-jobs/{job_id}/approve",
        json={
            "name": "discovered-modern",
            "management_address": "192.0.2.1",
            "port": 22,
            "vendor": "cisco_iosxe",
            "credential_profile_id": credential_profile["id"],
        },
    )

    assert approved.status_code == 201, approved.text
    assert approved.json()["ssh_compatibility"] == "modern"
    assert transport_factory.parameters[-1].ssh_compatibility.value == "modern"
