from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.container import ApplicationContainer
from app.jobs import tasks
from app.models import Event, Job
from app.services.connection_gate import ConnectionOperation


def _device_payload(profile_id: str, *, vendor: str = "cisco_iosxe") -> dict[str, object]:
    return {
        "name": f"{vendor}-diagnostic-target",
        "management_address": "192.0.2.30" if vendor == "cisco_iosxe" else "192.0.2.31",
        "port": 22,
        "vendor": vendor,
        "credential_profile_id": profile_id,
    }


def test_allowlisted_diagnostic_runs_as_sanitized_background_job(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    session_factory: sessionmaker[Session],
    transport_factory,
    monkeypatch,
) -> None:
    created = authenticated_client.post(
        "/api/devices",
        json=_device_payload(str(credential_profile["id"])),
    )
    assert created.status_code == 201, created.text
    device_id = created.json()["id"]

    queued = authenticated_client.post(
        "/api/diagnostics",
        json={"device_id": device_id, "action": "routing_table"},
    )
    assert queued.status_code == 202, queued.text
    job_id = queued.json()["id"]
    with session_factory() as session:
        stored = session.get(Job, UUID(job_id))
        assert stored is not None
        assert stored.input == {"action": "routing_table"}

    transport_factory.commands["show ip route"] += "x" * 65_536
    monkeypatch.setattr(tasks, "get_default_container", lambda: container)
    result = tasks.execute_job(job_id)

    assert result["action"] == "routing_table"
    assert result["truncated"] is True
    assert len(str(result["output"])) == 65_536
    assert "192.0.2.0/24" in str(result["output"])
    assert "SANITIZED_COMMUNITY" not in str(result["output"])
    assert "[REDACTED]" in str(result["output"])
    assert transport_factory.transports[-1].sent_commands == ["show ip route"]
    completed = authenticated_client.get(f"/api/jobs/{job_id}")
    assert completed.json()["state"] == "succeeded"
    with session_factory() as session:
        event = session.query(Event).filter_by(event_type="diagnostic.completed").one()
        assert str(event.device_id) == device_id
        assert str(event.job_id) == job_id
        assert event.details == {"action": "routing_table", "truncated": True}


def test_diagnostic_rejects_unknown_action_and_unsupported_driver(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
) -> None:
    invalid = authenticated_client.post(
        "/api/diagnostics",
        json={"device_id": "2ad0db14-5a87-4147-a4e7-c98f88322464", "action": "reload"},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"

    created = authenticated_client.post(
        "/api/devices",
        json=_device_payload(str(credential_profile["id"]), vendor="generic"),
    )
    assert created.status_code == 201, created.text
    unsupported = authenticated_client.post(
        "/api/diagnostics",
        json={"device_id": created.json()["id"], "action": "routing_table"},
    )
    assert unsupported.status_code == 422
    assert unsupported.json()["error"]["code"] == "unsupported_capability"


def test_diagnostic_requires_authentication(client: TestClient) -> None:
    response = client.post(
        "/api/diagnostics",
        json={
            "device_id": "2ad0db14-5a87-4147-a4e7-c98f88322464",
            "action": "routing_table",
        },
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_ping_requires_one_valid_target_and_uses_bounded_command(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    transport_factory,
    monkeypatch,
) -> None:
    created = authenticated_client.post(
        "/api/devices",
        json=_device_payload(str(credential_profile["id"])),
    )
    device_id = created.json()["id"]
    injection = authenticated_client.post(
        "/api/diagnostics",
        json={
            "device_id": device_id,
            "action": "ping",
            "target": "198.51.100.10;reload",
        },
    )
    assert injection.status_code == 422

    queued = authenticated_client.post(
        "/api/diagnostics",
        json={"device_id": device_id, "action": "ping", "target": "198.51.100.10"},
    )
    assert queued.status_code == 202, queued.text
    monkeypatch.setattr(tasks, "get_default_container", lambda: container)
    result = tasks.execute_job(queued.json()["id"])

    assert result["target"] == "198.51.100.10"
    assert "Success rate is 100 percent" in str(result["output"])
    assert transport_factory.transports[-1].sent_commands == [
        "ping 198.51.100.10 repeat 3 timeout 1"
    ]


def test_diagnostic_uses_one_structured_read_permit(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    fake_connection_gate,
    monkeypatch,
) -> None:
    created = authenticated_client.post(
        "/api/devices",
        json=_device_payload(str(credential_profile["id"])),
    ).json()
    fake_connection_gate.acquired.clear()
    fake_connection_gate.released.clear()
    monkeypatch.setattr(tasks, "get_default_container", lambda: container)
    queued = authenticated_client.post(
        "/api/diagnostics",
        json={"device_id": created["id"], "action": "routing_table"},
    )

    tasks.execute_job(queued.json()["id"])

    assert [permit.operation for permit in fake_connection_gate.acquired] == [
        ConnectionOperation.STRUCTURED_READ
    ]
    assert fake_connection_gate.released == fake_connection_gate.acquired
