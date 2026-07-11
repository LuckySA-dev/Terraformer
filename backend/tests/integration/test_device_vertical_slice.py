from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.container import ApplicationContainer
from app.jobs import tasks
from app.models import ConfigSnapshot, Job


def _device_payload(profile_id: str) -> dict[str, object]:
    return {
        "name": "edge-rtr-01",
        "management_address": "192.0.2.10",
        "port": 22,
        "vendor": "cisco_iosxe",
        "credential_profile_id": profile_id,
    }


def test_first_device_refresh_snapshot_and_event_flow(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    session_factory: sessionmaker[Session],
    transport_factory,
    monkeypatch,
) -> None:
    payload = _device_payload(str(credential_profile["id"]))
    created = authenticated_client.post("/api/devices", json=payload)
    assert created.status_code == 201, created.text
    device = created.json()
    device_id = device["id"]
    assert device["status"] == "reachable"
    assert device["facts"] == {}
    supported = {item["name"]: item["supported"] for item in device["capabilities"]}
    assert supported["facts"] is True
    assert supported["interfaces"] is True
    assert supported["running_config"] is True
    assert supported["apply"] is False
    assert all(item["safety_level"] == "D" for item in device["capabilities"])
    assert transport_factory.parameters[-1].connect_timeout_seconds == 7
    assert transport_factory.parameters[-1].command_timeout_seconds == 41

    duplicate = authenticated_client.post("/api/devices", json=payload)
    assert duplicate.status_code == 409
    assert authenticated_client.patch(
        f"/api/devices/{device_id}", json={"name": None}
    ).status_code == 422

    queued_refresh = authenticated_client.post(f"/api/devices/{device_id}/refresh")
    assert queued_refresh.status_code == 202
    refresh_job_id = queued_refresh.json()["id"]
    monkeypatch.setattr(tasks, "get_default_container", lambda: container)
    refresh_result = tasks.execute_job(refresh_job_id)
    assert refresh_result["interface_count"] == 3

    facts = authenticated_client.get(f"/api/devices/{device_id}/facts")
    assert facts.status_code == 200
    assert facts.json()["facts"]["hostname"] == "edge-rtr-01"
    interfaces = authenticated_client.get(f"/api/devices/{device_id}/interfaces")
    assert interfaces.status_code == 200
    assert [item["name"] for item in interfaces.json()] == [
        "GigabitEthernet1",
        "GigabitEthernet2",
        "Loopback0",
    ]
    completed = authenticated_client.get(f"/api/jobs/{refresh_job_id}")
    assert completed.json()["state"] == "succeeded"

    queued_snapshot = authenticated_client.post(
        f"/api/devices/{device_id}/config-snapshots"
    )
    assert queued_snapshot.status_code == 202
    snapshot_job_id = queued_snapshot.json()["id"]
    snapshot_result = tasks.execute_job(snapshot_job_id)
    snapshot_id = str(snapshot_result["snapshot_id"])

    snapshots = authenticated_client.get(
        "/api/config-snapshots", params={"device_id": device_id}
    )
    assert snapshots.status_code == 200
    assert snapshots.json()[0]["id"] == snapshot_id
    snapshot = authenticated_client.get(f"/api/config-snapshots/{snapshot_id}")
    assert snapshot.status_code == 200
    assert "hostname edge-rtr-01" in snapshot.json()["content"]
    assert "SANITIZED_ENABLE_HASH" not in snapshot.text
    assert "SANITIZED_USER_HASH" not in snapshot.text
    assert "SANITIZED_COMMUNITY" not in snapshot.text
    assert snapshot.text.count("[REDACTED]") >= 3

    with session_factory() as session:
        stored = session.get(ConfigSnapshot, UUID(snapshot_id))
        assert stored is not None
        raw = (container.settings.snapshot_dir / stored.artifact_path).read_bytes()
        assert b"hostname edge-rtr-01" not in raw
        refresh_job = session.get(Job, UUID(refresh_job_id))
        assert refresh_job is not None
        assert refresh_job.input == {}

    events = authenticated_client.get("/api/events", params={"device_id": device_id})
    assert events.status_code == 200
    event_types = {event["event_type"] for event in events.json()}
    assert {
        "device.created",
        "device.refreshed",
        "config.snapshot_created",
        "job.succeeded",
    }.issubset(event_types)

    cannot_delete = authenticated_client.delete(f"/api/devices/{device_id}")
    assert cannot_delete.status_code == 409


def test_connection_failure_is_typed_and_does_not_create_device(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    transport_factory,
) -> None:
    transport_factory.open_error = type("AuthenticationFailed", (Exception,), {})()
    response = authenticated_client.post(
        "/api/devices", json=_device_payload(str(credential_profile["id"]))
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "device_authentication_failed"
    assert authenticated_client.get("/api/devices").json() == []


def test_queue_failure_marks_job_failed_and_returns_503(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    fake_queue,
    session_factory: sessionmaker[Session],
) -> None:
    created = authenticated_client.post(
        "/api/devices", json=_device_payload(str(credential_profile["id"]))
    )
    device_id = created.json()["id"]
    fake_queue.available = False

    response = authenticated_client.post(f"/api/devices/{device_id}/refresh")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "queue_unavailable"
    with session_factory() as session:
        job = session.query(Job).one()
        assert job.state.value == "failed"
        assert job.error_message == "The background job queue is unavailable"
