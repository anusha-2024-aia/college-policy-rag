"""PDF parser service extracting text page by page with header/footer stripping."""

import hashlib
import logging
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from pypdf import PdfReader
from pypdf.errors import PdfReadError

logger = logging.getLogger(__name__)


class PDFParsingError(Exception):
    """Exception raised when PDF parsing fails."""
    pass


@dataclass
class PageData:
    """Extracted text and metadata for a single PDF page."""

    page_number: int  # 1-based page number
    text: str
    char_count: int


@dataclass
class ParsedPDF:
    """Result of parsing an entire PDF document."""

    file_name: str
    file_path: Path
    file_hash: str
    total_pages: int
    pages: list[PageData]


def _detect_repeating_lines(pages_text: list[str], threshold: float = 0.65) -> set[str]:
    """Identify header/footer lines that repeat across most pages.

    A line is considered a header or footer if it appears (case-insensitively,
    stripped) in at least `threshold` fraction of non-empty pages.

    Args:
        pages_text: Raw extracted text for each page.
        threshold: Fraction of pages a line must appear in to be suppressed.

    Returns:
        Set of normalised line strings to strip from all pages.
    """
    non_empty = [t for t in pages_text if t.strip()]
    if len(non_empty) < 2:
        return set()

    line_counts: Counter = Counter()
    for text in non_empty:
        # Use a set per page so duplicate lines within one page don't inflate counts
        page_lines = {ln.strip() for ln in text.splitlines() if ln.strip()}
        line_counts.update(page_lines)

    min_pages = max(2, int(len(non_empty) * threshold))
    repeating = {line for line, count in line_counts.items() if count >= min_pages}

    # Never strip lines that are substantial policy text (>80 chars) — only short
    # header/footer strings like "Kestrel Valley Institute of Technology", page nums, etc.
    repeating = {line for line in repeating if len(line) <= 100}

    # Also never strip lines containing sentence-ending punctuation (they're content)
    repeating = {
        line for line in repeating
        if not re.search(r"[.!?]\s*$", line) and not re.search(r"\d+\.\s+\w", line)
    }

    if repeating:
        logger.debug("Header/footer suppression detected %d repeating lines.", len(repeating))

    return repeating


def _strip_repeating_lines(text: str, repeating: set[str]) -> str:
    """Remove header/footer lines from page text."""
    if not repeating:
        return text
    cleaned_lines = [
        ln for ln in text.splitlines()
        if ln.strip() not in repeating
    ]
    return "\n".join(cleaned_lines).strip()


class PDFParserService:
    """Service for parsing PDF documents page by page."""

    @staticmethod
    def compute_file_hash(file_path: Path) -> str:
        """Compute SHA-256 hash of a file for integrity and idempotency."""
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()

    def parse_pdf(self, file_path: Path | str) -> ParsedPDF:
        """Parse PDF document page by page preserving 1-based page numbers.

        Automatically strips repeating header/footer lines detected across pages.

        Args:
            file_path: Path to the PDF file.

        Returns:
            ParsedPDF containing page-by-page extracted text and document metadata.

        Raises:
            PDFParsingError: If file is corrupted, unreadable, empty, or missing.
        """
        path = Path(file_path)
        file_name = path.name

        if not path.exists():
            error_msg = f"PDF file does not exist: {file_name}"
            logger.error(error_msg)
            raise PDFParsingError(error_msg)

        if path.stat().st_size == 0:
            error_msg = f"PDF file is completely empty (0 bytes): {file_name}"
            logger.error(error_msg)
            raise PDFParsingError(error_msg)

        try:
            file_hash = self.compute_file_hash(path)
        except OSError as exc:
            error_msg = f"Failed to read file for hashing: {file_name} ({exc})"
            logger.error(error_msg)
            raise PDFParsingError(error_msg) from exc

        try:
            reader = PdfReader(str(path))
            if reader.is_encrypted:
                try:
                    reader.decrypt("")
                except Exception as dec_exc:
                    error_msg = f"PDF file is password-protected or encrypted: {file_name} ({dec_exc})"
                    logger.error(error_msg)
                    raise PDFParsingError(error_msg) from dec_exc

            total_pages = len(reader.pages)
            if total_pages == 0:
                error_msg = f"PDF document contains zero pages: {file_name}"
                logger.error(error_msg)
                raise PDFParsingError(error_msg)

            # ── Pass 1: extract raw text from all pages ────────────────────────
            raw_pages: list[str] = []
            for idx, page in enumerate(reader.pages):
                one_based = idx + 1
                try:
                    page_text = page.extract_text() or ""
                except Exception as extract_exc:
                    logger.warning(
                        "Failed to extract text from page %d of %s: %s",
                        one_based,
                        file_name,
                        extract_exc,
                    )
                    page_text = ""
                raw_pages.append(page_text.strip())

            # ── Pass 2: detect and strip repeating header/footer lines ─────────
            repeating_lines = _detect_repeating_lines(raw_pages)

            # ── Pass 3: build final PageData objects ───────────────────────────
            pages_data: list[PageData] = []
            for idx, raw_text in enumerate(raw_pages):
                cleaned = _strip_repeating_lines(raw_text, repeating_lines)
                pages_data.append(
                    PageData(
                        page_number=idx + 1,
                        text=cleaned,
                        char_count=len(cleaned),
                    )
                )

            logger.info(
                "Successfully parsed %s: %d pages extracted (hash: %s...), "
                "%d header/footer lines suppressed.",
                file_name,
                total_pages,
                file_hash[:12],
                len(repeating_lines),
            )

            return ParsedPDF(
                file_name=file_name,
                file_path=path,
                file_hash=file_hash,
                total_pages=total_pages,
                pages=pages_data,
            )

        except PdfReadError as exc:
            error_msg = f"Corrupted or invalid PDF format in {file_name}: {exc}"
            logger.error(error_msg)
            raise PDFParsingError(error_msg) from exc
        except Exception as exc:
            error_msg = f"Unexpected failure parsing PDF {file_name}: {exc}"
            logger.error(error_msg)
            raise PDFParsingError(error_msg) from exc
