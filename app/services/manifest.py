"""Manifest loader and validator service."""

import csv
from pathlib import Path
from typing import Optional
from app.schemas.manifest import DocumentManifestRow


class ManifestError(Exception):
    """Exception raised when document manifest is missing or invalid."""
    pass


class ManifestService:
    """Service for parsing and validating documents manifest CSV."""

    REQUIRED_HEADERS = {"file", "title", "effective_date", "supersedes", "allowed_roles"}

    def __init__(self, base_dir: Optional[Path] = None):
        # Default base directory for raw PDF resolution
        self.base_dir = (base_dir or Path.cwd()).resolve()

    def parse_manifest(self, manifest_path: str | Path) -> list[DocumentManifestRow]:
        """Read and validate documents manifest CSV.

        Args:
            manifest_path: Path to the documents_manifest.csv file.

        Returns:
            List of validated DocumentManifestRow objects.

        Raises:
            ManifestError: If the file does not exist, headers are missing, or rows are invalid.
        """
        path = Path(manifest_path)
        if not path.is_absolute():
            path = (self.base_dir / path).resolve()

        if not path.exists():
            raise ManifestError(f"Manifest file not found at: {path}")

        records: list[DocumentManifestRow] = []

        try:
            with open(path, mode="r", encoding="utf-8-sig") as csv_file:
                reader = csv.DictReader(csv_file)
                if not reader.fieldnames:
                    raise ManifestError(f"Manifest file {path.name} is empty or has no header row.")

                normalized_headers = {h.strip() for h in reader.fieldnames if h}
                missing = self.REQUIRED_HEADERS - normalized_headers
                if missing:
                    raise ManifestError(
                        f"Manifest missing required columns: {sorted(missing)}. "
                        f"Found: {sorted(normalized_headers)}"
                    )

                for row_idx, raw_row in enumerate(reader, start=2):
                    cleaned_row = {
                        k.strip(): v.strip() if isinstance(v, str) else v
                        for k, v in raw_row.items()
                        if k
                    }

                    try:
                        record = DocumentManifestRow(**cleaned_row)
                        records.append(record)
                    except Exception as exc:
                        raise ManifestError(
                            f"Validation failed on row {row_idx} of {path.name}: {exc}"
                        ) from exc

        except OSError as exc:
            raise ManifestError(f"Failed to read manifest file {path.name}: {exc}") from exc

        return records

    def resolve_pdf_path(self, file_path_str: str, allowed_base: Optional[Path] = None) -> Path:
        """Safely resolve PDF file path preventing directory traversal.

        Args:
            file_path_str: Relative or absolute path specified in manifest.
            allowed_base: Base directory to restrict file resolution.

        Returns:
            Resolved absolute Path.

        Raises:
            ManifestError: If path attempts directory traversal or file does not exist.
        """
        base = (allowed_base or self.base_dir).resolve()
        candidate = Path(file_path_str)

        if candidate.is_absolute():
            resolved = candidate.resolve()
        else:
            resolved = (base / candidate).resolve()

        # Path traversal guard: ensure resolved path is within base
        try:
            resolved.relative_to(base)
        except ValueError as exc:
            raise ManifestError(
                f"Security violation: path traversal detected for '{file_path_str}' "
                f"which resolves outside base directory '{base}'"
            ) from exc

        if not resolved.exists():
            raise ManifestError(f"PDF document does not exist at resolved path: {resolved}")

        return resolved
