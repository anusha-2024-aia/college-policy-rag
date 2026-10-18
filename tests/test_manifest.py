"""Tests for manifest parsing, validation schemas, and path traversal protection."""

from datetime import date
from pathlib import Path
import pytest
from app.schemas.manifest import DocumentManifestRow
from app.services.manifest import ManifestService, ManifestError


def test_valid_manifest_row_parsing():
    """Verify DocumentManifestRow correctly validates and cleans valid data."""
    row = DocumentManifestRow(
        file="data/raw_pdfs/handbook.pdf",
        title="Employee Handbook",
        effective_date=date(2025, 1, 1),
        supersedes="Handbook 2024",
        allowed_roles="admin;hr;legal",
    )
    assert row.file == "data/raw_pdfs/handbook.pdf"
    assert row.title == "Employee Handbook"
    assert row.effective_date == date(2025, 1, 1)
    assert row.supersedes == "Handbook 2024"
    assert row.allowed_roles == ["admin", "hr", "legal"]


def test_manifest_roles_with_comma_and_spaces():
    """Verify that comma-separated roles with mixed whitespace are cleanly parsed."""
    row = DocumentManifestRow(
        file="test.pdf",
        title="Test",
        effective_date=date(2025, 1, 1),
        allowed_roles="admin, legal , hr ",
    )
    assert row.allowed_roles == ["admin", "legal", "hr"]


def test_manifest_clean_empty_supersedes():
    """Verify that empty, None, or 'none' strings for supersedes are normalized to None."""
    for empty_val in ["", "  ", None, "None", "null"]:
        row = DocumentManifestRow(
            file="test.pdf",
            title="Test",
            effective_date=date(2025, 1, 1),
            supersedes=empty_val,
        )
        assert row.supersedes is None


def test_manifest_invalid_file_extension():
    """Verify that non-PDF files are rejected."""
    with pytest.raises(ValueError, match="must be a PDF document"):
        DocumentManifestRow(
            file="document.docx",
            title="Document",
            effective_date=date(2025, 1, 1),
        )


def test_manifest_missing_headers(tmp_path: Path):
    """Verify that CSV with missing columns raises ManifestError."""
    bad_csv = tmp_path / "bad_manifest.csv"
    bad_csv.write_text("file,title\nfoo.pdf,Foo\n", encoding="utf-8")

    service = ManifestService(base_dir=tmp_path)
    with pytest.raises(ManifestError, match="Manifest missing required columns"):
        service.parse_manifest(bad_csv)


def test_manifest_file_not_found(tmp_path: Path):
    """Verify that non-existent manifest file raises ManifestError."""
    service = ManifestService(base_dir=tmp_path)
    with pytest.raises(ManifestError, match="Manifest file not found"):
        service.parse_manifest(tmp_path / "non_existent.csv")


def test_manifest_path_traversal_prevention(tmp_path: Path):
    """Verify that directory traversal attempts are blocked."""
    service = ManifestService(base_dir=tmp_path / "sandbox")
    (tmp_path / "sandbox").mkdir()

    # Attempt to resolve ../../etc/passwd or similar
    with pytest.raises(ManifestError, match="path traversal detected"):
        service.resolve_pdf_path("../../escape.pdf", allowed_base=tmp_path / "sandbox")
