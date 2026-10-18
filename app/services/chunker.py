"""Text chunker service splitting text page by page with token awareness."""

import logging
from dataclasses import dataclass
import tiktoken
from app.services.pdf_parser import ParsedPDF

logger = logging.getLogger(__name__)


@dataclass
class DocumentChunk:
    """Represents an isolated chunk of text originating from a single page."""

    chunk_index: int  # 0-based sequential chunk index within the document
    page_number: int  # 1-based page number where the chunk originates
    text: str
    token_count: int


class ChunkerService:
    """Splits document text into configurable token-aware chunks per page.

    Invariant: Chunks NEVER combine text across different pages.
    """

    def __init__(
        self,
        chunk_size_tokens: int = 500,
        chunk_overlap_tokens: int = 80,
        encoding_name: str = "cl100k_base",
    ):
        if chunk_size_tokens <= 0:
            raise ValueError(f"chunk_size_tokens must be positive, got {chunk_size_tokens}")
        if chunk_overlap_tokens < 0:
            raise ValueError(f"chunk_overlap_tokens cannot be negative, got {chunk_overlap_tokens}")
        if chunk_overlap_tokens >= chunk_size_tokens:
            raise ValueError(
                f"chunk_overlap_tokens ({chunk_overlap_tokens}) must be strictly less "
                f"than chunk_size_tokens ({chunk_size_tokens})"
            )

        self.chunk_size_tokens = chunk_size_tokens
        self.chunk_overlap_tokens = chunk_overlap_tokens
        self.encoding = tiktoken.get_encoding(encoding_name)

    def count_tokens(self, text: str) -> int:
        """Count tokens in a string using configured encoding."""
        return len(self.encoding.encode(text))

    def chunk_page(
        self,
        page_text: str,
        page_number: int,
        start_chunk_index: int = 0,
    ) -> list[DocumentChunk]:
        """Split a single page's text into token chunks with overlap.

        Text is strictly confined to this page.
        """
        stripped_text = page_text.strip()
        if not stripped_text:
            return []

        tokens = self.encoding.encode(stripped_text)
        total_tokens = len(tokens)

        # If page fits within chunk size, produce a single chunk
        if total_tokens <= self.chunk_size_tokens:
            return [
                DocumentChunk(
                    chunk_index=start_chunk_index,
                    page_number=page_number,
                    text=stripped_text,
                    token_count=total_tokens,
                )
            ]

        chunks: list[DocumentChunk] = []
        step = self.chunk_size_tokens - self.chunk_overlap_tokens
        current_start = 0
        current_chunk_idx = start_chunk_index

        while current_start < total_tokens:
            current_end = min(current_start + self.chunk_size_tokens, total_tokens)
            chunk_tokens = tokens[current_start:current_end]
            chunk_text = self.encoding.decode(chunk_tokens).strip()

            if chunk_text:
                chunks.append(
                    DocumentChunk(
                        chunk_index=current_chunk_idx,
                        page_number=page_number,
                        text=chunk_text,
                        token_count=len(chunk_tokens),
                    )
                )
                current_chunk_idx += 1

            if current_end >= total_tokens:
                break

            current_start += step

        return chunks

    def chunk_document(self, parsed_pdf: ParsedPDF) -> list[DocumentChunk]:
        """Split an entire document into chunks, processing each page independently.

        Ensures text from different pages is never mixed into one chunk.
        """
        all_chunks: list[DocumentChunk] = []
        running_chunk_index = 0

        for page in parsed_pdf.pages:
            page_chunks = self.chunk_page(
                page_text=page.text,
                page_number=page.page_number,
                start_chunk_index=running_chunk_index,
            )
            all_chunks.extend(page_chunks)
            running_chunk_index += len(page_chunks)

        logger.info(
            "Generated %d chunks for document %s across %d pages (chunk_size=%d, overlap=%d)",
            len(all_chunks),
            parsed_pdf.file_name,
            parsed_pdf.total_pages,
            self.chunk_size_tokens,
            self.chunk_overlap_tokens,
        )

        return all_chunks
