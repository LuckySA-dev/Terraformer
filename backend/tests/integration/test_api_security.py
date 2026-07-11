from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.models import CredentialProfile


def test_health_reports_ok_and_optional_worker_degradation(client, fake_queue) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    fake_queue.workers = False
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"]["worker"]["status"] == "unavailable"


def test_health_reports_unavailable_when_redis_is_down(client, fake_queue) -> None:
    fake_queue.available = False
    response = client.get("/api/health")

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"


def test_setup_session_and_logout_flow(client: TestClient) -> None:
    assert client.get("/api/setup").json() == {"configured": False}

    weak_secret = "LEAK-ME-NOT"
    weak = client.post("/api/setup", json={"master_password": weak_secret})
    assert weak.status_code == 422
    assert weak_secret not in weak.text

    password = "correct horse battery staple"
    configured = client.post("/api/setup", json={"master_password": password})
    assert configured.status_code == 201
    assert configured.json() == {"configured": True}
    assert client.post("/api/setup", json={"master_password": password}).status_code == 409

    invalid = client.post("/api/session", json={"master_password": "wrong password value"})
    assert invalid.status_code == 401
    assert "wrong password value" not in invalid.text

    login = client.post("/api/session", json={"master_password": password})
    assert login.status_code == 200
    assert login.json() == {"authenticated": True}
    assert "HttpOnly" in login.headers["set-cookie"]
    assert "SameSite=strict" in login.headers["set-cookie"]
    assert client.get("/api/session").json() == {"authenticated": True}

    logout = client.delete("/api/session")
    assert logout.status_code == 204
    assert client.get("/api/session").json() == {"authenticated": False}


def test_csrf_origin_checks_cover_setup_and_login(client: TestClient) -> None:
    rejected = client.post(
        "/api/setup",
        headers={"origin": "https://attacker.invalid"},
        json={"master_password": "correct horse battery staple"},
    )
    assert rejected.status_code == 403
    assert rejected.json()["error"]["code"] == "csrf_origin_rejected"

    cross_site = client.post(
        "/api/setup",
        headers={"sec-fetch-site": "cross-site"},
        json={"master_password": "correct horse battery staple"},
    )
    assert cross_site.status_code == 403

    trusted = client.post(
        "/api/setup",
        headers={"origin": "http://testserver"},
        json={"master_password": "correct horse battery staple"},
    )
    assert trusted.status_code == 201

    rejected_login = client.post(
        "/api/session",
        headers={"origin": "https://attacker.invalid"},
        json={"master_password": "correct horse battery staple"},
    )
    assert rejected_login.status_code == 403


def test_protected_routes_return_typed_authentication_error(client: TestClient) -> None:
    response = client.get("/api/devices")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"
    assert response.headers["x-request-id"] == response.json()["error"]["request_id"]


def test_credential_responses_are_metadata_only_and_database_is_encrypted(
    authenticated_client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    payload = {
        "name": "lab-readonly",
        "username": "device-admin",
        "password": "super-secret-fixture",
        "enable_password": "enable-secret-fixture",
    }
    response = authenticated_client.post("/api/credential-profiles", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {
        "id",
        "name",
        "has_username",
        "has_password",
        "has_enable_password",
        "created_at",
        "updated_at",
    }
    assert "device-admin" not in response.text
    assert "super-secret-fixture" not in response.text
    assert "enable-secret-fixture" not in response.text

    with session_factory() as session:
        profile = session.get(CredentialProfile, UUID(body["id"]))
        assert profile is not None
        encrypted = profile.encrypted_secret
        assert b"device-admin" not in encrypted
        assert b"super-secret-fixture" not in encrypted
        assert b"enable-secret-fixture" not in encrypted

    listing = authenticated_client.get("/api/credential-profiles")
    assert listing.status_code == 200
    assert listing.json()[0]["id"] == body["id"]
    assert "device-admin" not in listing.text


def test_validation_error_never_echoes_secret_input(authenticated_client: TestClient) -> None:
    secret = "LEAK-ME-NOT"
    response = authenticated_client.post(
        "/api/credential-profiles",
        json={"name": "invalid", "username": "user", "password": secret, "unexpected": secret},
    )
    assert response.status_code == 422
    assert secret not in response.text
