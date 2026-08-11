from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_healthz_returns_stable_service_metadata() -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "pdos-api",
        "version": "0.1.0",
    }


def test_openapi_metadata_identifies_the_service() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "PDOS API"
    assert schema["info"]["version"] == "0.1.0"
