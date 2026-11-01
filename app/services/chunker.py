"""Text chunker service splitting text page by page with token awareness and clause boundary support."""

import logging
import re
from dataclasses import dataclass
from typing import Optional
import tiktoken
from app.services.pdf_parser import ParsedPDF

logger = logging.getLogger(__name__)

# Regex patterns for stripping repeated headers and footers across pages
HEADER_FOOTER_PATTERNS = [
    re.compile(r"(?i)^\s*Page\s+\d+\s+of\s+\d+\s*$", re.MULTILINE),
    re.compile(r"(?i)^\s*Kestrel Valley Institute of Technology \(fictional\)\s*$", re.MULTILINE),
    re.compile(r"(?i)^\s*(?:PUBLIC[^\n]*|CONFIDENTIAL[^\n]*)\s*$", re.MULTILINE),
    re.compile(r"(?i)^\s*Synthetic document for portfolio testing[^\n]*$", re.MULTILINE),
    re.compile(r"(?i)^\s*Doc control no\.:[^\n]*$", re.MULTILINE),
    re.compile(r"(?i)^\s*Version:\s*[^\n]*\|\s*Effective date:[^\n]*$", re.MULTILINE),
    re.compile(r"(?i)^\s*Issued by:\s*Kestrel Valley Institute of Technology[^\n]*$", re.MULTILINE),
    re.compile(r"(?i)^\s*[A-Za-z0-9\s,\-\:]+\(continued\)\s*$", re.MULTILINE),
]

# Regex to detect clause boundaries for chunk splitting
CLAUSE_SPLIT_REGEX = re.compile(
    r"(?m)(?=^[\s\-*•]*(?:(?:Amendment\s+to\s+)?Clause\s*\d+(?:\.\d+)?|Section\s*\d+(?:\.\d+)?|\d+\.\s+[A-Za-z]|(?:[A-Z][A-Za-z\s]{2,20}:)))"
)

# Regex to extract normalized clause reference (e.g. "Clause 4.2")
CLAUSE_EXTRACT_REGEX = re.compile(
    r"(?:Clause\s*(\d+(?:\.\d+)?))",
    re.IGNORECASE,
)


@dataclass
class DocumentChunk:
    """Represents an isolated chunk of text originating from a single page."""

    chunk_index: int  # 0-based sequential chunk index within the document
    page_number: int  # 1-based page number where the chunk originates
    text: str
    token_count: int
    clause_ref: Optional[str] = None


class ChunkerService:
    """Splits document text into configurable token-aware chunks per page.

    Invariants:
    1. Chunks NEVER combine text across different pages.
    2. One clause is NOT split across chunks when clause boundaries exist and fit token budget.
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

    def strip_headers_and_footers(self, text: str) -> str:
        """Strip repeated page headers and footers before chunking."""
        cleaned = text
        for pat in HEADER_FOOTER_PATTERNS:
            cleaned = pat.sub("", cleaned)
        return re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    def extract_clause_ref(self, text: str) -> Optional[str]:
        """Extract normalized clause reference (e.g. 'Clause 4.2' or 'Section 2') from text."""
        m = CLAUSE_EXTRACT_REGEX.search(text)
        if m:
            return f"Clause {m.group(1)}"
        m_sec = re.search(r"(?:Section\s*(\d+(?:\.\d+)?))", text, re.IGNORECASE)
        if m_sec:
            return f"Section {m_sec.group(1)}"
        m_num = re.search(r"^\s*(\d+(?:\.\d+)?)\.\s+[A-Za-z]", text, re.MULTILINE)
        if m_num:
            return f"Clause {m_num.group(1)}"
        return None

    def chunk_page(
        self,
        page_text: str,
        page_number: int,
        start_chunk_index: int = 0,
    ) -> list[DocumentChunk]:
        """Split a single page's text into token chunks with clause boundary awareness.

        Text is strictly confined to this page. Repeated page headers/footers
        are stripped before chunking.
        """
        cleaned_text = self.strip_headers_and_footers(page_text)
        if not cleaned_text:
            return []

        # Check if page has explicit clause boundaries or numbered sections
        has_clauses = bool(CLAUSE_EXTRACT_REGEX.search(cleaned_text)) or bool(
            re.search(r"(?m)^[\s\-*•]*(?:Section|\d+\.\s+[A-Za-z]|[A-Z][A-Za-z\s]{2,20}:)", cleaned_text)
        )

        if has_clauses:
            chunks: list[DocumentChunk] = []
            current_chunk_idx = start_chunk_index
            raw_splits = [s.strip() for s in CLAUSE_SPLIT_REGEX.split(cleaned_text) if s.strip()]

            # Merge very small split fragments (< 12 tokens) into the subsequent block so headings aren't orphaned
            merged_splits = []
            for s in raw_splits:
                if merged_splits and self.count_tokens(merged_splits[-1]) < 12:
                    merged_splits[-1] = merged_splits[-1] + "\n\n" + s
                else:
                    merged_splits.append(s)
            raw_splits = merged_splits

            # If leading block has no clause ref (e.g. heading), prepend to first clause
            if len(raw_splits) > 1 and self.extract_clause_ref(raw_splits[0]) is None:
                header_prefix = raw_splits[0] + "\n\n"
                raw_splits = raw_splits[1:]
                raw_splits[0] = header_prefix + raw_splits[0]

            for block in raw_splits:
                clause_ref = self.extract_clause_ref(block)
                block_tokens = self.encoding.encode(block)
                token_count = len(block_tokens)

                if token_count <= self.chunk_size_tokens:
                    chunks.append(
                        DocumentChunk(
                            chunk_index=current_chunk_idx,
                            page_number=page_number,
                            text=block,
                            token_count=token_count,
                            clause_ref=clause_ref,
                        )
                    )
                    current_chunk_idx += 1
                else:
                    # Very large clause exceeding chunk_size_tokens: split with overlap
                    step = self.chunk_size_tokens - self.chunk_overlap_tokens
                    sub_start = 0
                    while sub_start < token_count:
                        sub_end = min(sub_start + self.chunk_size_tokens, token_count)
                        sub_toks = block_tokens[sub_start:sub_end]
                        sub_txt = self.encoding.decode(sub_toks).strip()
                        if sub_txt:
                            chunks.append(
                                DocumentChunk(
                                    chunk_index=current_chunk_idx,
                                    page_number=page_number,
                                    text=sub_txt,
                                    token_count=len(sub_toks),
                                    clause_ref=clause_ref,
                                )
                            )
                            current_chunk_idx += 1
                        if sub_end >= token_count:
                            break
                        sub_start += step

            return chunks

        # Fallback to standard token-aware chunking for pages without clauses
        tokens = self.encoding.encode(cleaned_text)
        total_tokens = len(tokens)

        # If page fits within chunk size, produce a single chunk
        if total_tokens <= self.chunk_size_tokens:
            return [
                DocumentChunk(
                    chunk_index=start_chunk_index,
                    page_number=page_number,
                    text=cleaned_text,
                    token_count=total_tokens,
                    clause_ref=None,
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
                        clause_ref=None,
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
