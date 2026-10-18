"""Tests for PDF parser service, page extraction, and failure handling."""

import logging
from pathlib import Path
import pytest
from app.services.pdf_parser import PDFParserService, PDFParsingError
from tests.helpers import write_test_pdf


def test_pdf_parser_multi_page_extraction(tmp_path: Path):
    """Verify parser extracts page-by-page text with 1-based page numbers and computes file hash."""
    pdf_path = tmp_path / "sample_doc.pdf"
    write_test_pdf(
        pdf_path,
        [
            "Page 1: Architecture guidelines.",
            "Page 2: Security compliance rules.",
            "Page 3: Operational deployment.",
        ],
    )

    parser = PDFParserService()
    result = parser.parse_pdf(pdf_path)

    assert result.file_name == "sample_doc.pdf"
    assert result.total_pages == 3
    assert len(result.pages) == 3
    assert len(result.file_hash) == 64  # Valid SHA-256

    # Verify 1-based indexing and text content
    assert result.pages[0].page_number == 1
    assert "Page 1: Architecture guidelines." in result.pages[0].text

    assert result.pages[1].page_number == 2
    assert "Page 2: Security compliance rules." in result.pages[1].text

    assert result.pages[2].page_number == 3
    assert "Page 3: Operational deployment." in result.pages[2].text


def test_pdf_parser_empty_zero_byte_file(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    """Verify that a 0-byte file raises PDFParsingError and logs the filename."""
    empty_pdf = tmp_path / "zero_bytes.pdf"
    empty_pdf.touch()

    parser = PDFParserService()
    with caplog.at_level(logging.ERROR):
        with pytest.raises(PDFParsingError, match="zero_bytes.pdf"):
            parser.parse_pdf(empty_pdf)

    # Check that error was logged
    assert any("zero_bytes.pdf" in record.message for record in caplog.records)


def test_pdf_parser_corrupted_file(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    """Verify that a corrupted binary raises PDFParsingError and logs details."""
    corrupt_pdf = tmp_path / "corrupted.pdf"
    corrupt_pdf.write_bytes(b"%PDF-1.4\nInvalid non-pdf binary content that fails parsing\n")

    parser = PDFParserService()
    with caplog.at_level(logging.ERROR):
        with pytest.raises(PDFParsingError, match="corrupted.pdf"):
            parser.parse_pdf(corrupt_pdf)

    assert any("corrupted.pdf" in record.message for record in caplog.records)


def test_pdf_parser_non_existent_file(tmp_path: Path):
    """Verify that attempting to parse a non-existent file raises PDFParsingError."""
    parser = PDFParserService()
    with pytest.raises(PDFParsingError, match="does not exist"):
        parser.parse_pdf(tmp_path / "missing_file.pdf")
