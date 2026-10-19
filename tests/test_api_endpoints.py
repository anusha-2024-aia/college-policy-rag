"""Tests for document catalog, evaluations, and system stats API routes."""

import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_system_stats_endpoint():
    """Verify GET /system/stats returns valid schema and metrics."""
    response = client.get("/system/stats")
    assert response.status_code == 200
    data = response.json()
    assert "app_name" in data
    assert "total_docs" in data
    assert "total_chunks" in data
    assert "total_pages" in data
    assert isinstance(data["total_docs"], int)
    assert isinstance(data["semantic_retrieval_enabled"], bool)


def test_documents_list_endpoint():
    """Verify GET /documents returns document repository items."""
    response = client.get("/documents")
    assert response.status_code == 200
    data = response.json()
    assert "total_docs" in data
    assert "documents" in data
    assert isinstance(data["documents"], list)
    if data["total_docs"] > 0:
        doc = data["documents"][0]
        assert "file_name" in doc
        assert "title" in doc
        assert "allowed_roles" in doc


def test_documents_role_filter():
    """Verify GET /documents?role=student filters appropriately."""
    response = client.get("/documents?role=student")
    assert response.status_code == 200
    data = response.json()
    assert "documents" in data
    for d in data["documents"]:
        assert any("student" in r.lower() for r in d["allowed_roles"])


def test_evaluations_list_endpoint():
    """Verify GET /evaluations/reports returns discoverable reports."""
    response = client.get("/evaluations/reports")
    assert response.status_code == 200
    data = response.json()
    assert "reports" in data
    assert "total_count" in data
    assert data["total_count"] >= 0


def test_evaluations_detail_endpoint():
    """Verify GET /evaluations/reports/{filename} retrieves markdown and JSON."""
    list_resp = client.get("/evaluations/reports")
    reports = list_resp.json().get("reports", [])
    if reports:
        target_name = reports[0]["filename"]
        detail_resp = client.get(f"/evaluations/reports/{target_name}")
        assert detail_resp.status_code == 200
        detail_data = detail_resp.json()
        assert "markdown_content" in detail_data
        assert detail_data["filename"] == target_name
