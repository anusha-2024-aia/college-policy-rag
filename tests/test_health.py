"""Tests for health check endpoint."""

from fastapi.testclient import TestClient


def test_health_check_returns_200(client: TestClient) -> None:
    """Verify that GET /health returns HTTP 200 and expected health data."""
    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["app"] == "Document RAG API"
    assert data["version"] == "0.1.0"
    assert "environment" in data
