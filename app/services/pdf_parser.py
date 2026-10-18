"""PDF parser service extracting text page by page."""

import hashlib
import logging
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
                    # Attempt empty password decrypt if encrypted without pass
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

            pages_data: list[PageData] = []

            for idx, page in enumerate(reader.pages):
                one_based_page_num = idx + 1
                try:
                    page_text = page.extract_text() or ""
                except Exception as extract_exc:
                    logger.warning(
                        "Failed to extract text from page %d of %s: %s",
                        one_based_page_num,
                        file_name,
                        extract_exc,
                    )
                    page_text = ""

                cleaned_text = page_text.strip()
                pages_data.append(
                    PageData(
                        page_number=one_based_page_num,
                        text=cleaned_text,
                        char_count=len(cleaned_text),
                    )
                )

            logger.info(
                "Successfully parsed %s: %d pages extracted (hash: %s...)",
                file_name,
                total_pages,
                file_hash[:12],
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
