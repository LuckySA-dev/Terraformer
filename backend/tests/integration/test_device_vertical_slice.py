from __future__ import annotations

import traceback
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from scrapli.exceptions import ScrapliAuthenticationFailed, ScrapliTimeout, ScrapliValueError
from sqlalchemy.orm import Session, sessionmaker

from app.container import ApplicationContainer
from app.core.errors import DriverTerminalIOError, DriverTimeoutError
from app.jobs import tasks
from app.models import ConfigSnapshot, Device, Event, Job
from app.services.connection_gate import ConnectionOperation, ConnectionTarget
from app.services.devices import DeviceService


def _device_payload(
    client: TestClient,
    profile_id: str,
    **connection_changes: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "edge-rtr-01",
        "management_address": "192.0.2.10",
        "port": 22,
        "vendor": "cisco_iosxe",
        "credential_profile_id": profile_id,
    }
    payload.update(connection_changes)
    candidate = client.post(
        "/api/ssh-host-key-candidates",
        json={key: value for key, value in payload.items() if key != "name"},
    )
    assert candidate.status_code == 201, candidate.text
    payload["host_key_candidate_id"] = candidate.json()["id"]
    return payload


def _connection_edit_payload(
    client: TestClient,
    device: dict[str, object],
    changes: dict[str, object],
) -> dict[str, object]:
    connection = {
        key: device[key]
        for key in (
            "management_address",
            "port",
            "vendor",
            "credential_profile_id",
            "ssh_compatibility",
        )
    }
    connection.update(changes)
    candidate = client.post("/api/ssh-host-key-candidates", json=connection)
    assert candidate.status_code == 201, candidate.text
    return {**changes, "host_key_candidate_id": candidate.json()["id"]}


def test_first_device_refresh_snapshot_and_event_flow(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    session_factory: sessionmaker[Session],
    transport_factory,
    monkeypatch,
) -> None:
    payload = _device_payload(authenticated_client, str(credential_profile["id"]))
    created = authenticated_client.post("/api/devices", json=payload)
    assert created.status_code == 201, created.text
    device = created.json()
    device_id = device["id"]
    assert device["status"] == "reachable"
    assert device["facts"] == {}
    supported = {item["name"]: item["supported"] for item in device["capabilities"]}
    assert supported["facts"] is True
    assert supported["interfaces"] is True
    assert supported["neighbors"] is True
    assert supported["running_config"] is True
    assert supported["routing"] is True
    assert supported["arp"] is True
    assert supported["mac"] is True
    assert supported["ping"] is True
    assert supported["traceroute"] is True
    assert supported["apply"] is False
    assert all(item["safety_level"] == "D" for item in device["capabilities"])
    assert transport_factory.parameters[-1].connect_timeout_seconds == 7
    assert transport_factory.parameters[-1].command_timeout_seconds == 41

    duplicate = authenticated_client.post("/api/devices", json=payload)
    assert duplicate.status_code == 409
    assert (
        authenticated_client.patch(f"/api/devices/{device_id}", json={"name": None}).status_code
        == 422
    )

    queued_refresh = authenticated_client.post(f"/api/devices/{device_id}/refresh")
    assert queued_refresh.status_code == 202
    refresh_job_id = queued_refresh.json()["id"]
    monkeypatch.setattr(tasks, "get_default_container", lambda: container)
    refresh_result = tasks.execute_job(refresh_job_id)
    assert refresh_result["interface_count"] == 3
    assert refresh_result["neighbor_count"] == 2
    assert len(transport_factory.transports) == 2
    assert transport_factory.transports[-1].sent_commands == [
        "show version",
        "show interfaces",
        "show cdp neighbors detail",
        "show lldp neighbors detail",
    ]

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
    neighbors = authenticated_client.get(f"/api/devices/{device_id}/neighbors")
    assert neighbors.status_code == 200
    assert [(item["protocol"], item["remote_device_name"]) for item in neighbors.json()] == [
        ("cdp", "dist-sw-01.example.test"),
        ("lldp", "access-sw-01.example.test"),
    ]
    assert neighbors.json()[0]["management_address"] == "198.51.100.2"
    completed = authenticated_client.get(f"/api/jobs/{refresh_job_id}")
    assert completed.json()["state"] == "succeeded"

    queued_snapshot = authenticated_client.post(f"/api/devices/{device_id}/config-snapshots")
    assert queued_snapshot.status_code == 202
    snapshot_job_id = queued_snapshot.json()["id"]
    snapshot_result = tasks.execute_job(snapshot_job_id)
    snapshot_id = str(snapshot_result["snapshot_id"])

    snapshots = authenticated_client.get("/api/config-snapshots", params={"device_id": device_id})
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
    transport_factory.open_error = ScrapliAuthenticationFailed("Permission denied")
    response = authenticated_client.post(
        "/api/devices", json=_device_payload(authenticated_client, str(credential_profile["id"]))
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "device_authentication_failed"
    assert authenticated_client.get("/api/devices").json() == []


@pytest.mark.parametrize("vendor", ["cisco_iosxe", "generic"])
@pytest.mark.parametrize(
    ("factory_error", "expected_status", "expected_error"),
    [
        (
            ScrapliValueError(
                "raw-constructor-marker edge-rtr-01.example.test fixture-password "
                "peer-offered-ssh-rsa"
            ),
            500,
            {
                "code": "configuration_error",
                "message": "The service is not configured correctly",
                "details": {"phase": "tcp_connection", "retryable": False},
            },
        ),
        (
            RuntimeError(
                "raw-constructor-marker edge-rtr-01.example.test fixture-password "
                "peer-offered-ssh-rsa"
            ),
            502,
            {
                "code": "device_connection_failed",
                "message": "Unable to connect to the device",
                "details": {
                    "phase": "tcp_connection",
                    "retryable": True,
                    "recommended_action": (
                        "Verify device reachability and that SSH is listening "
                        "on the configured port."
                    ),
                },
            },
        ),
    ],
)
def test_transport_constructor_failure_is_sanitized_in_api_and_logs(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    transport_factory,
    capsys,
    vendor: str,
    factory_error: Exception,
    expected_status: int,
    expected_error: dict[str, object],
) -> None:
    prohibited = (
        type(factory_error).__name__,
        "raw-constructor-marker",
        "edge-rtr-01.example.test",
        "fixture-password",
        "peer-offered-ssh-rsa",
    )
    transport_factory.factory_error = factory_error
    payload = _device_payload(
        authenticated_client,
        str(credential_profile["id"]),
        vendor=vendor,
    )
    capsys.readouterr()

    response = authenticated_client.post("/api/devices", json=payload)
    captured_logs = capsys.readouterr()

    assert response.status_code == expected_status
    assert response.json()["error"] == {
        **expected_error,
        "request_id": response.headers["x-request-id"],
    }
    rendered = response.text + captured_logs.out + captured_logs.err
    assert all(raw not in rendered for raw in prohibited)
    assert authenticated_client.get("/api/devices").json() == []


def test_negotiation_failure_api_contains_only_fixed_safe_fields(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    transport_factory,
) -> None:
    prohibited = (
        "raw-offer-marker",
        "edge-rtr-01.example.test",
        "fixture-password",
        "ScrapliAuthenticationFailed",
    )
    transport_factory.open_error = ScrapliAuthenticationFailed(
        "No matching host key type found for edge-rtr-01.example.test, "
        "their offer: raw-offer-marker fixture-password"
    )

    response = authenticated_client.post(
        "/api/devices", json=_device_payload(authenticated_client, str(credential_profile["id"]))
    )

    assert response.status_code == 502
    assert response.json()["error"] == {
        "code": "legacy_ssh_negotiation_failed",
        "message": "SSH negotiation with the device failed",
        "details": {
            "phase": "ssh_negotiation",
            "retryable": False,
            "recommended_action": (
                "The device and this client share no usable SSH algorithm. Select a"
                " higher SSH compatibility mode for this device. Older Cisco switches"
                " and routers often also need a regenerated 2048-bit host key."
            ),
        },
        "request_id": response.headers["x-request-id"],
    }
    assert all(value not in response.text for value in prohibited)


@pytest.mark.parametrize(
    ("command_error", "expected_error", "expected_code", "expected_message", "raw_marker"),
    [
        (
            ScrapliAuthenticationFailed("Permission denied raw-worker-auth-marker"),
            DriverTerminalIOError,
            "terminal_transport_failed",
            "The device terminal transport failed",
            "raw-worker-auth-marker",
        ),
        (
            ScrapliTimeout("Timed out connecting to host raw-worker-timeout-marker"),
            DriverTimeoutError,
            "device_connection_timeout",
            "The device operation timed out",
            "raw-worker-timeout-marker",
        ),
    ],
)
def test_background_driver_failure_does_not_log_raw_exception(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    session_factory: sessionmaker[Session],
    transport_factory,
    monkeypatch,
    command_error: Exception,
    expected_error: type[Exception],
    expected_code: str,
    expected_message: str,
    raw_marker: str,
) -> None:
    records: list[dict[str, object]] = []

    class RecordingLogger:
        def exception(self, event: str, **kwargs: object) -> None:
            records.append({"event": event, "traceback": traceback.format_exc(), **kwargs})

        def error(self, event: str, **kwargs: object) -> None:
            records.append({"event": event, **kwargs})

    created = authenticated_client.post(
        "/api/devices",
        json=_device_payload(authenticated_client, str(credential_profile["id"])),
    )
    job = authenticated_client.post(f"/api/devices/{created.json()['id']}/refresh")
    transport_factory.command_error = command_error
    monkeypatch.setattr(tasks, "get_default_container", lambda: container)
    monkeypatch.setattr(tasks, "logger", RecordingLogger())

    with pytest.raises(expected_error) as captured:
        tasks.execute_job(job.json()["id"])

    assert records == [
        {
            "event": "device_job_failed",
            "job_id": job.json()["id"],
            "error_code": expected_code,
            "phase": "terminal_io",
        }
    ]
    for prohibited in (
        raw_marker,
        type(command_error).__name__,
        expected_error.__name__,
    ):
        assert prohibited not in repr(records)
    rq_exc_info = "".join(traceback.format_exception(captured.type, captured.value, captured.tb))
    assert raw_marker not in rq_exc_info
    with session_factory() as session:
        stored = session.get(Job, UUID(job.json()["id"]))
        assert stored is not None
        assert stored.error_code == expected_code
        assert stored.error_message == expected_message


def test_queue_failure_marks_job_failed_and_returns_503(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    fake_queue,
    session_factory: sessionmaker[Session],
) -> None:
    created = authenticated_client.post(
        "/api/devices", json=_device_payload(authenticated_client, str(credential_profile["id"]))
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


def test_device_test_create_and_registered_paths_default_to_modern_and_retest(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    transport_factory,
    fake_connection_gate,
) -> None:
    payload = _device_payload(authenticated_client, str(credential_profile["id"]))

    candidate = authenticated_client.post(
        "/api/devices/connection-test",
        json={key: value for key, value in payload.items() if key != "name"},
    )
    created = authenticated_client.post("/api/devices", json=payload)
    registered = authenticated_client.post(f"/api/devices/{created.json()['id']}/test-connection")

    assert candidate.status_code == 200, candidate.text
    assert created.status_code == 201, created.text
    assert registered.status_code == 200, registered.text
    assert created.json()["ssh_compatibility"] == "modern"
    assert [item.ssh_compatibility.value for item in transport_factory.parameters] == [
        "modern",
        "modern",
        "modern",
    ]
    assert [permit.operation for permit in fake_connection_gate.acquired] == [
        ConnectionOperation.CONNECTION_TEST,
        ConnectionOperation.CONNECTION_TEST,
        ConnectionOperation.CONNECTION_TEST,
    ]
    assert fake_connection_gate.released == fake_connection_gate.acquired


@pytest.mark.parametrize("endpoint", ["/api/devices", "/api/devices/connection-test"])
def test_non_cisco_connection_requests_reject_cisco_legacy_modes(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    transport_factory,
    endpoint: str,
) -> None:
    payload = {
        "name": "invalid-legacy-device",
        "management_address": "192.0.2.10",
        "port": 22,
        "vendor": "generic",
        "credential_profile_id": credential_profile["id"],
        "ssh_compatibility": "cisco_legacy",
    }
    if endpoint.endswith("connection-test"):
        payload.pop("name")
    call_count = len(transport_factory.parameters)

    response = authenticated_client.post(endpoint, json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsupported_capability"
    assert "Cisco legacy SSH compatibility is only available" in response.text
    assert len(transport_factory.parameters) == call_count


def test_generic_modern_connection_test_remains_allowed(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
) -> None:
    payload = _device_payload(
        authenticated_client,
        str(credential_profile["id"]),
        vendor="generic",
        ssh_compatibility="modern",
    )
    payload.pop("name")

    response = authenticated_client.post("/api/devices/connection-test", json=payload)

    assert response.status_code == 200, response.text


def test_update_rejects_legacy_mode_combined_with_existing_non_cisco_vendor(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    transport_factory,
) -> None:
    payload = _device_payload(
        authenticated_client,
        str(credential_profile["id"]),
        vendor="generic",
    )
    created = authenticated_client.post("/api/devices", json=payload).json()
    container.settings.ssh_legacy_enabled = True
    call_count = len(transport_factory.parameters)

    response = authenticated_client.patch(
        f"/api/devices/{created['id']}",
        json={"ssh_compatibility": "cisco_legacy"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsupported_capability"
    assert "Cisco legacy SSH compatibility is only available" in response.text
    assert len(transport_factory.parameters) == call_count
    stored = authenticated_client.get(f"/api/devices/{created['id']}").json()
    assert (stored["vendor"], stored["ssh_compatibility"], stored["status"]) == (
        "generic",
        "modern",
        "reachable",
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("management_address", "192.0.2.11"),
        ("port", 2222),
        ("vendor", "generic"),
        ("ssh_compatibility", "cisco_legacy"),
    ],
)
def test_connection_relevant_edit_retests_before_save(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    transport_factory,
    field: str,
    value: object,
) -> None:
    created = authenticated_client.post(
        "/api/devices", json=_device_payload(authenticated_client, str(credential_profile["id"]))
    )
    if field == "ssh_compatibility":
        container.settings.ssh_legacy_enabled = True
    call_count = len(transport_factory.parameters)

    updated = authenticated_client.patch(
        f"/api/devices/{created.json()['id']}",
        json=_connection_edit_payload(
            authenticated_client,
            created.json(),
            {field: value},
        ),
    )

    assert updated.status_code == 200, updated.text
    assert updated.json()[field] == value
    assert len(transport_factory.parameters) == call_count + 1


def test_credential_profile_edit_retests_before_save(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    transport_factory,
) -> None:
    created = authenticated_client.post(
        "/api/devices", json=_device_payload(authenticated_client, str(credential_profile["id"]))
    )
    replacement = authenticated_client.post(
        "/api/credential-profiles",
        json={
            "name": "replacement-readonly",
            "username": "replacement-user",
            "password": "replacement-password",
        },
    )
    call_count = len(transport_factory.parameters)

    updated = authenticated_client.patch(
        f"/api/devices/{created.json()['id']}",
        json=_connection_edit_payload(
            authenticated_client,
            created.json(),
            {"credential_profile_id": replacement.json()["id"]},
        ),
    )

    assert updated.status_code == 200, updated.text
    assert updated.json()["credential_profile_id"] == replacement.json()["id"]
    assert len(transport_factory.parameters) == call_count + 1


def test_connection_edit_commits_only_the_exact_tuple_that_was_tested(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    transport_factory,
    monkeypatch,
) -> None:
    created = authenticated_client.post(
        "/api/devices", json=_device_payload(authenticated_client, str(credential_profile["id"]))
    ).json()
    replacement = authenticated_client.post(
        "/api/credential-profiles",
        json={
            "name": "atomic-retest-profile",
            "username": "atomic-retest-user",
            "password": "atomic-retest-password",
        },
    ).json()
    container.settings.ssh_legacy_enabled = True
    device_id = UUID(created["id"])
    committed_tuples: list[tuple[object, ...]] = []
    original_commit = Session.commit

    def record_committed_tuple(session: Session) -> None:
        device = session.get(Device, device_id)
        if device is not None:
            committed_tuples.append(
                (
                    device.management_address,
                    device.port,
                    device.vendor.value,
                    str(device.credential_profile_id),
                    device.ssh_compatibility.value,
                )
            )
        original_commit(session)

    monkeypatch.setattr(Session, "commit", record_committed_tuple)
    requested_tuple = (
        "192.0.2.77",
        2222,
        "cisco_iosxe",
        replacement["id"],
        "cisco_legacy",
    )

    changes = {
        "management_address": requested_tuple[0],
        "port": requested_tuple[1],
        "vendor": requested_tuple[2],
        "credential_profile_id": requested_tuple[3],
        "ssh_compatibility": requested_tuple[4],
    }
    updated = authenticated_client.patch(
        f"/api/devices/{created['id']}",
        json=_connection_edit_payload(authenticated_client, created, changes),
    )

    assert updated.status_code == 200, updated.text
    tested = transport_factory.parameters[-1]
    saved_tuple = (
        updated.json()["management_address"],
        updated.json()["port"],
        updated.json()["vendor"],
        updated.json()["credential_profile_id"],
        updated.json()["ssh_compatibility"],
    )
    assert saved_tuple == requested_tuple
    assert (tested.host, tested.port, tested.username, tested.ssh_compatibility.value) == (
        requested_tuple[0],
        requested_tuple[1],
        "atomic-retest-user",
        requested_tuple[4],
    )
    assert committed_tuples == [requested_tuple]


@pytest.mark.parametrize(
    "field",
    [
        "management_address",
        "port",
        "vendor",
        "credential_profile_id",
        "ssh_compatibility",
    ],
)
def test_failed_edit_retest_does_not_mutate_saved_device(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    session_factory: sessionmaker[Session],
    transport_factory,
    field: str,
) -> None:
    created = authenticated_client.post(
        "/api/devices", json=_device_payload(authenticated_client, str(credential_profile["id"]))
    ).json()
    values: dict[str, object] = {
        "management_address": "192.0.2.99",
        "port": 2222,
        "vendor": "generic",
        "ssh_compatibility": "cisco_legacy",
    }
    if field == "credential_profile_id":
        replacement = authenticated_client.post(
            "/api/credential-profiles",
            json={
                "name": "failed-retest-profile",
                "username": "replacement-user",
                "password": "replacement-password",
            },
        )
        values[field] = replacement.json()["id"]
    if field == "ssh_compatibility":
        container.settings.ssh_legacy_enabled = True
    transport_factory.open_error = ScrapliAuthenticationFailed("denied")
    with session_factory() as session:
        admission_count = (
            session.query(Event).filter_by(event_type="ssh.connection_admission").count()
        )

    failed = authenticated_client.patch(
        f"/api/devices/{created['id']}",
        json=_connection_edit_payload(
            authenticated_client,
            created,
            {field: values[field]},
        ),
    )
    stored = authenticated_client.get(f"/api/devices/{created['id']}").json()
    with session_factory() as session:
        persisted_admission_count = (
            session.query(Event).filter_by(event_type="ssh.connection_admission").count()
        )

    assert failed.status_code == 401
    assert persisted_admission_count == admission_count
    for field in (
        "management_address",
        "port",
        "vendor",
        "credential_profile_id",
        "ssh_compatibility",
        "status",
        "last_error_code",
    ):
        assert stored[field] == created[field]


def test_policy_denials_precede_transport_and_preserve_saved_status(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    transport_factory,
    fake_connection_gate,
) -> None:
    created = authenticated_client.post(
        "/api/devices", json=_device_payload(authenticated_client, str(credential_profile["id"]))
    ).json()
    transport_count = len(transport_factory.parameters)
    permit_count = len(fake_connection_gate.acquired)

    legacy = authenticated_client.patch(
        f"/api/devices/{created['id']}",
        json={"ssh_compatibility": "cisco_legacy"},
    )

    assert legacy.status_code == 403
    assert legacy.json()["error"]["code"] == "legacy_mode_disabled_by_policy"
    stored = authenticated_client.get(f"/api/devices/{created['id']}").json()
    assert stored["ssh_compatibility"] == "modern"
    assert stored["status"] == "reachable"
    assert len(transport_factory.parameters) == transport_count
    assert len(fake_connection_gate.acquired) == permit_count

    container.settings.ssh_legacy_enabled = True
    container.settings.ssh_group1_enabled = True
    group1 = authenticated_client.post(
        "/api/devices/connection-test",
        json={
            **{
                key: value
                for key, value in _device_payload(
                    authenticated_client, str(credential_profile["id"])
                ).items()
                if key != "name"
            },
            "ssh_compatibility": "cisco_legacy_group1",
        },
    )
    assert group1.status_code == 403
    assert group1.json()["error"]["code"] == "legacy_group1_disabled_by_policy"
    assert len(transport_factory.parameters) == transport_count
    assert len(fake_connection_gate.acquired) == permit_count

    container.settings.ssh_group1_enabled = False
    disabled_group1 = authenticated_client.post(
        "/api/devices/connection-test",
        json={
            **{
                key: value
                for key, value in _device_payload(
                    authenticated_client, str(credential_profile["id"])
                ).items()
                if key != "name"
            },
            "ssh_compatibility": "cisco_legacy_group1",
            "group1_risk_acknowledged": True,
        },
    )
    assert disabled_group1.status_code == 403
    assert disabled_group1.json()["error"]["code"] == "legacy_group1_disabled_by_policy"
    assert len(transport_factory.parameters) == transport_count
    assert len(fake_connection_gate.acquired) == permit_count


def test_admission_happens_before_decryption_and_auth_accounting_is_tuple_scoped(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    transport_factory,
    fake_connection_gate,
    monkeypatch,
) -> None:
    vault = container.credential_vault
    original_decrypt = vault.decrypt

    def checked_decrypt(profile):
        assert len(fake_connection_gate.acquired) > len(fake_connection_gate.released)
        return original_decrypt(profile)

    monkeypatch.setattr(vault, "decrypt", checked_decrypt)
    transport_factory.open_error = ScrapliAuthenticationFailed("denied")

    failed = authenticated_client.post(
        "/api/devices", json=_device_payload(authenticated_client, str(credential_profile["id"]))
    )

    assert failed.status_code == 401
    assert fake_connection_gate.authentication_failures == [fake_connection_gate.acquired[0].target]
    assert fake_connection_gate.authentication_successes == []
    assert fake_connection_gate.released == fake_connection_gate.acquired
    assert len(fake_connection_gate.released) == 1
    assert "192.0.2.10" not in fake_connection_gate.acquired[0].target.endpoint_digest

    transport_factory.open_error = None
    succeeded = authenticated_client.post(
        "/api/devices", json=_device_payload(authenticated_client, str(credential_profile["id"]))
    )

    assert succeeded.status_code == 201, succeeded.text
    assert fake_connection_gate.authentication_successes == [
        fake_connection_gate.acquired[1].target
    ]
    assert (
        fake_connection_gate.authentication_failures[0]
        == fake_connection_gate.authentication_successes[0]
    )


def test_terminal_io_failure_after_auth_clears_prior_tuple_failures(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    transport_factory,
    fake_connection_gate,
    monkeypatch,
) -> None:
    created = authenticated_client.post(
        "/api/devices", json=_device_payload(authenticated_client, str(credential_profile["id"]))
    ).json()
    fake_connection_gate.acquired.clear()
    fake_connection_gate.released.clear()
    fake_connection_gate.authentication_failures.clear()
    fake_connection_gate.authentication_successes.clear()
    prior_target = ConnectionTarget.from_endpoint(
        host=created["management_address"],
        port=created["port"],
        credential_profile_id=UUID(created["credential_profile_id"]),
        device_id=UUID(created["id"]),
    )
    active_failure_tuples = {prior_target}
    fake_connection_gate.authentication_failures.append(prior_target)

    def clear_prior_failures(target: ConnectionTarget) -> None:
        active_failure_tuples.discard(target)
        fake_connection_gate.authentication_successes.append(target)

    monkeypatch.setattr(
        fake_connection_gate,
        "authentication_succeeded",
        clear_prior_failures,
    )
    transport_factory.command_error = ScrapliTimeout("timed out")
    monkeypatch.setattr(tasks, "get_default_container", lambda: container)
    job = authenticated_client.post(f"/api/devices/{created['id']}/refresh").json()

    with pytest.raises(DriverTimeoutError):
        tasks.execute_job(job["id"])

    assert len(fake_connection_gate.acquired) == 1
    assert fake_connection_gate.released == fake_connection_gate.acquired
    assert fake_connection_gate.authentication_failures == [prior_target]
    assert fake_connection_gate.authentication_successes == [prior_target]
    assert active_failure_tuples == set()


def test_audit_failure_still_releases_the_permit_once(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    fake_connection_gate,
    monkeypatch,
) -> None:
    def fail_audit(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(DeviceService, "_audit_connection", fail_audit)

    response = authenticated_client.post(
        "/api/devices", json=_device_payload(authenticated_client, str(credential_profile["id"]))
    )

    assert response.status_code == 500
    assert len(fake_connection_gate.acquired) == 1
    assert fake_connection_gate.released == fake_connection_gate.acquired


def test_refresh_and_snapshot_each_use_one_structured_read_permit(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    fake_connection_gate,
    monkeypatch,
) -> None:
    created = authenticated_client.post(
        "/api/devices", json=_device_payload(authenticated_client, str(credential_profile["id"]))
    ).json()
    fake_connection_gate.acquired.clear()
    fake_connection_gate.released.clear()
    fake_connection_gate.authentication_successes.clear()
    monkeypatch.setattr(tasks, "get_default_container", lambda: container)

    refresh_job = authenticated_client.post(f"/api/devices/{created['id']}/refresh").json()
    tasks.execute_job(refresh_job["id"])
    snapshot_job = authenticated_client.post(
        f"/api/devices/{created['id']}/config-snapshots"
    ).json()
    tasks.execute_job(snapshot_job["id"])

    assert [permit.operation for permit in fake_connection_gate.acquired] == [
        ConnectionOperation.STRUCTURED_READ,
        ConnectionOperation.STRUCTURED_READ,
    ]
    assert fake_connection_gate.released == fake_connection_gate.acquired
    assert fake_connection_gate.authentication_successes == [
        permit.target for permit in fake_connection_gate.acquired
    ]


def test_connection_admission_audit_uses_only_the_approved_metadata_allowlist(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    session_factory: sessionmaker[Session],
) -> None:
    created = authenticated_client.post(
        "/api/devices", json=_device_payload(authenticated_client, str(credential_profile["id"]))
    )
    assert created.status_code == 201, created.text
    registered = authenticated_client.post(f"/api/devices/{created.json()['id']}/test-connection")
    assert registered.status_code == 200, registered.text

    with session_factory() as session:
        events = (
            session.query(Event)
            .filter_by(event_type="ssh.connection_admission")
            .order_by(Event.created_at)
            .all()
        )
    event = next(item for item in events if item.device_id == UUID(created.json()["id"]))

    assert str(event.device_id) == created.json()["id"]
    assert set(event.details) == {
        "principal",
        "requested_mode",
        "group1_risk_acknowledged",
        "very_old_risk_acknowledged",
        "compatibility_policy_version",
        "operation",
        "phase",
        "policy_decision",
        "duration_ms",
        "result_code",
    }
    assert event.details["principal"] == "local-admin"
    assert event.details["requested_mode"] == "modern"
    assert event.details["operation"] == "connection_test"
    assert event.details["policy_decision"] == "allowed"
    assert event.details["result_code"] == "success"
    assert isinstance(event.details["duration_ms"], int)
    assert all(set(item.details) == set(event.details) for item in events)
    for item in events:
        rendered = repr(item.details)
        for prohibited in (
            "192.0.2.10",
            "edge-rtr-01",
            "fixture-password",
            "peer_algorithms",
            "negotiated_algorithm",
            "terminal_content",
        ):
            assert prohibited not in rendered
