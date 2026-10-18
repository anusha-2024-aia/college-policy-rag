"""Tests for token-aware chunker service and page boundary invariants."""

from pathlib import Path
import pytest
from app.services.chunker import ChunkerService
from app.services.pdf_parser import ParsedPDF, PageData


def test_chunker_initialization_validation():
    """Verify chunker raises errors on invalid token size or overlap arguments."""
    with pytest.raises(ValueError, match="chunk_size_tokens must be positive"):
        ChunkerService(chunk_size_tokens=0)

    with pytest.raises(ValueError, match="chunk_overlap_tokens cannot be negative"):
        ChunkerService(chunk_size_tokens=100, chunk_overlap_tokens=-5)

    with pytest.raises(ValueError, match="strictly less than chunk_size_tokens"):
        ChunkerService(chunk_size_tokens=100, chunk_overlap_tokens=100)


def test_page_isolation_invariant():
    """CRITICAL TEST: Verify that chunks NEVER combine text across different pages."""
    chunker = ChunkerService(chunk_size_tokens=50, chunk_overlap_tokens=10)

    parsed_doc = ParsedPDF(
        file_name="test_isolation.pdf",
        file_path=Path("test_isolation.pdf"),
        file_hash="mock_hash_123",
        total_pages=3,
        pages=[
            PageData(page_number=1, text="ALPHA_START " + "First page content. " * 15 + "ALPHA_END", char_count=300),
            PageData(page_number=2, text="BETA_START " + "Second page content. " * 15 + "BETA_END", char_count=300),
            PageData(page_number=3, text="GAMMA_START " + "Third page content. " * 15 + "GAMMA_END", char_count=300),
        ],
    )

    chunks = chunker.chunk_document(parsed_doc)

    assert len(chunks) > 3

    for chunk in chunks:
        # Page 1 chunks must ONLY contain ALPHA content
        if chunk.page_number == 1:
            assert "BETA" not in chunk.text
            assert "GAMMA" not in chunk.text
            assert "First page content" in chunk.text

        # Page 2 chunks must ONLY contain BETA content
        elif chunk.page_number == 2:
            assert "ALPHA" not in chunk.text
            assert "GAMMA" not in chunk.text
            assert "Second page content" in chunk.text

        # Page 3 chunks must ONLY contain GAMMA content
        elif chunk.page_number == 3:
            assert "ALPHA" not in chunk.text
            assert "BETA" not in chunk.text
            assert "Third page content" in chunk.text
        else:
            pytest.fail(f"Unexpected page number {chunk.page_number}")


def test_chunk_page_number_is_one_based():
    """Verify that page numbers are 1-based and correctly recorded."""
    chunker = ChunkerService(chunk_size_tokens=100, chunk_overlap_tokens=20)

    parsed_doc = ParsedPDF(
        file_name="one_based.pdf",
        file_path=Path("one_based.pdf"),
        file_hash="hash_1",
        total_pages=2,
        pages=[
            PageData(page_number=1, text="Text on page one.", char_count=17),
            PageData(page_number=2, text="Text on page two.", char_count=17),
        ],
    )

    chunks = chunker.chunk_document(parsed_doc)
    assert len(chunks) == 2
    assert chunks[0].page_number == 1
    assert chunks[1].page_number == 2


def test_chunk_size_and_overlap_behavior():
    """Verify that large text generates multiple overlapping chunks within limit."""
    chunk_size = 60
    chunk_overlap = 15
    chunker = ChunkerService(chunk_size_tokens=chunk_size, chunk_overlap_tokens=chunk_overlap)

    long_page_text = "The quick brown fox jumps over the lazy dog repeatedly to fill up tokens. " * 20
    chunks = chunker.chunk_page(long_page_text, page_number=1)

    assert len(chunks) > 1

    for c in chunks:
        assert c.token_count <= chunk_size
        assert c.page_number == 1

    # Check that adjacent chunks share text due to overlap
    first_chunk_words = set(chunks[0].text.split())
    second_chunk_words = set(chunks[1].text.split())
    overlap_words = first_chunk_words.intersection(second_chunk_words)
    assert len(overlap_words) > 0


def test_blank_page_produces_no_chunks():
    """Verify that pages with empty string or whitespace produce 0 chunks."""
    chunker = ChunkerService()
    assert chunker.chunk_page("", page_number=1) == []
    assert chunker.chunk_page("   \n\n\t  ", page_number=1) == []
