from fastapi.testclient import TestClient


def test_connection_test_rejects_get_without_parsing_route_name_as_uuid(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.get("/api/devices/connection-test")

    assert response.status_code == 405
    assert response.headers["allow"] == "POST"
