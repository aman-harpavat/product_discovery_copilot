from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_returns_healthy_status() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["service"] == "AI Product Discovery Copilot"
    assert payload["version"] == "0.1.0"
    assert "timestamp_utc" in payload
