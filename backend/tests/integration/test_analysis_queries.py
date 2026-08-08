from __future__ import annotations

from fastapi.testclient import TestClient

from app.analysis.client import FilterVerdict, TraceHop, TraceResult
from app.container import ApplicationContainer
from app.jobs import tasks
from tests.fakes import FakeBatfishClient
from tests.integration.test_analysis_vertical_slice import _capture, _register_cisco


def _ready_snapshot(
    client: TestClient, profile_id: str, container: ApplicationContainer, monkeypatch
) -> tuple[str, str]:
    device_id = _register_cisco(client, profile_id, "192.0.2.10")
    _capture(client, device_id, container, monkeypatch)
    queued = client.post("/api/analysis-snapshots")
    tasks.execute_job(queued.json()["id"])
    return device_id, client.get("/api/analysis-snapshots").json()[0]["id"]


def test_path_check_returns_hops_a_disposition_and_the_disclosure(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    fake_batfish: FakeBatfishClient,
    monkeypatch,
) -> None:
    fake_batfish.trace_result = TraceResult(
        disposition="DENIED_IN",
        hops=(TraceHop("edge-rtr-01", "DENIED", "ACL BLOCK_GUEST line 20"),),
    )
    profile_id = str(credential_profile["id"])
    device_id, snapshot_id = _ready_snapshot(
        authenticated_client, profile_id, container, monkeypatch
    )

    response = authenticated_client.post(
        f"/api/analysis-snapshots/{snapshot_id}/path-checks",
        json={"source_device_id": device_id, "destination_ip": "198.51.100.10"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["disposition"] == "DENIED_IN"
    assert body["hops"][0]["hostname"] == "edge-rtr-01"
    assert body["evidence"] == "INFERRED"
    assert body["completeness"]["analysed_device_count"] == 1


def test_path_check_rejects_a_non_exact_ipv4_destination(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    monkeypatch,
) -> None:
    profile_id = str(credential_profile["id"])
    device_id, snapshot_id = _ready_snapshot(
        authenticated_client, profile_id, container, monkeypatch
    )

    # 0.0.0.0 is a rejected test value here (unspecified address), not a bind
    # address.
    rejected_destinations = (
        "198.51.100.0/24",
        "not-an-ip",
        "example.test",
        "127.0.0.1",
        "0.0.0.0",  # noqa: S104
    )
    for destination in rejected_destinations:
        response = authenticated_client.post(
            f"/api/analysis-snapshots/{snapshot_id}/path-checks",
            json={"source_device_id": device_id, "destination_ip": destination},
        )
        assert response.status_code == 422, (destination, response.text)


def test_filter_check_reports_the_matching_line(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    fake_batfish: FakeBatfishClient,
    monkeypatch,
) -> None:
    fake_batfish.filter_verdict = FilterVerdict(
        permitted=False, matched_line_index=3, matched_line="deny ip any any"
    )
    profile_id = str(credential_profile["id"])
    device_id, snapshot_id = _ready_snapshot(
        authenticated_client, profile_id, container, monkeypatch
    )

    response = authenticated_client.post(
        f"/api/analysis-snapshots/{snapshot_id}/filter-checks",
        json={
            "device_id": device_id,
            "filter_name": "BLOCK_GUEST",
            "destination_ip": "198.51.100.10",
            "protocol": "tcp",
            "destination_port": 443,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["permitted"] is False
    assert response.json()["matched_line"] == "deny ip any any"


def test_a_lost_snapshot_is_reported_as_expired_rather_than_reparsed(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    fake_batfish: FakeBatfishClient,
    monkeypatch,
) -> None:
    """Re-parsing inside a synchronous request would hide minutes of work."""
    profile_id = str(credential_profile["id"])
    device_id, snapshot_id = _ready_snapshot(
        authenticated_client, profile_id, container, monkeypatch
    )
    fake_batfish.forget(snapshot_id)

    response = authenticated_client.post(
        f"/api/analysis-snapshots/{snapshot_id}/path-checks",
        json={"source_device_id": device_id, "destination_ip": "198.51.100.10"},
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "analysis_snapshot_expired"
    assert (
        authenticated_client.get(f"/api/analysis-snapshots/{snapshot_id}").json()["status"]
        == "expired"
    )


def test_queries_fail_closed_when_analysis_is_disabled(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    monkeypatch,
) -> None:
    profile_id = str(credential_profile["id"])
    device_id, snapshot_id = _ready_snapshot(
        authenticated_client, profile_id, container, monkeypatch
    )
    container.settings.analysis_enabled = False

    response = authenticated_client.post(
        f"/api/analysis-snapshots/{snapshot_id}/path-checks",
        json={"source_device_id": device_id, "destination_ip": "198.51.100.10"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "analysis_disabled_by_policy"
