"""Ingestion service orchestrating manifest parsing, PDF extraction, chunking, lineage, and storage."""

import csv
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Any
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.document import Document
from app.models.chunk import Chunk
from app.models.lineage import DocumentLineage
from app.services.manifest import ManifestService, ManifestError
from app.services.pdf_parser import PDFParserService, PDFParsingError
from app.services.chunker import ChunkerService
from app.services.embedding import BaseEmbeddingService, get_embedding_service
from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class DocumentIngestionResult:
    """Result of ingesting a single document."""

    file_name: str
    status: str  # "ingested", "skipped", "failed"
    total_pages: int = 0
    total_chunks: int = 0
    error_message: Optional[str] = None


@dataclass
class IngestionReport:
    """Summary report of an entire manifest ingestion run."""

    total_documents: int = 0
    ingested_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    total_chunks_created: int = 0
    lineage_records_created: int = 0
    document_results: list[DocumentIngestionResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class IngestionService:
    """Idempotent ingestion pipeline orchestrator with version lineage tracking."""

    def __init__(
        self,
        db_session: Session,
        manifest_service: Optional[ManifestService] = None,
        pdf_parser: Optional[PDFParserService] = None,
        chunker: Optional[ChunkerService] = None,
        embedding_service: Optional[BaseEmbeddingService] = None,
        semantic_embedding_service: Optional[Any] = None,
    ):
        self.db = db_session
        self.manifest_service = manifest_service or ManifestService()
        self.pdf_parser = pdf_parser or PDFParserService()
        self.chunker = chunker or ChunkerService(
            chunk_size_tokens=settings.CHUNK_SIZE_TOKENS,
            chunk_overlap_tokens=settings.CHUNK_OVERLAP_TOKENS,
        )
        self.embedding_service = embedding_service or get_embedding_service()
        self.semantic_embedding_service = semantic_embedding_service

    @property
    def semantic_embedder(self):
        """Lazily initialize ONNXEmbeddingService when semantic retrieval is enabled."""
        if self.semantic_embedding_service is None and settings.SEMANTIC_RETRIEVAL_ENABLED:
            try:
                from app.services.embedding_onnx import ONNXEmbeddingService
                self.semantic_embedding_service = ONNXEmbeddingService()
            except Exception as exc:
                logger.warning("Could not initialize ONNXEmbeddingService in ingestion: %s", exc)
        return self.semantic_embedding_service

    def extract_doc_version(self, file_name: str, text: Optional[str] = None) -> Optional[str]:
        """Extract document version from text headers or filename."""
        if text:
            m = re.search(r"Version:\s*([A-Za-z0-9\-]+)", text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        m = re.search(r"(\d{4}(?:-[a-z0-9]+)?)", file_name, re.IGNORECASE)
        if m:
            return m.group(1)
        return "1.0"

    def ingest_lineage(self, register_path: str | Path) -> int:
        """Parse supersession register and update document & chunk lineage idempotently."""
        path = Path(register_path)
        if not path.is_file():
            logger.warning("Supersession register not found at %s", path)
            return 0

        lineage_count = 0
        with open(path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                old_file = row["old_file"].strip()
                new_file = row["new_file"].strip()
                scope_raw = row.get("scope", "").strip()
                eff_date_str = row.get("effective_date", "").strip()
                eff_date = (
                    datetime.strptime(eff_date_str, "%Y-%m-%d").date()
                    if eff_date_str
                    else None
                )
                ev_page = (
                    int(row["evidence_page"].strip())
                    if row.get("evidence_page", "").strip()
                    else None
                )
                ev_text = row.get("evidence_text", "").strip()

                old_doc = self.db.query(Document).filter(Document.file_name == old_file).first()
                new_doc = self.db.query(Document).filter(Document.file_name == new_file).first()

                if not old_doc or not new_doc:
                    logger.warning("Lineage documents not found: old=%s, new=%s", old_file, new_file)
                    continue

                effective_date = eff_date or new_doc.effective_date

                # Determine scope and amended clauses
                if scope_raw.lower() == "full":
                    scope = "full"
                    amended_clauses = []
                else:
                    scope = "partial"
                    # Parse clause numbers from string e.g. "partial: Clause 4.2 and Clause 6.1 only"
                    clauses_found = re.findall(r"Clause\s*(\d+(?:\.\d+)?)", scope_raw, re.IGNORECASE)
                    amended_clauses = [f"Clause {c}" for c in clauses_found]

                # Idempotent upsert of DocumentLineage
                existing_lineage = (
                    self.db.query(DocumentLineage)
                    .filter(
                        DocumentLineage.old_doc_id == old_doc.id,
                        DocumentLineage.new_doc_id == new_doc.id,
                    )
                    .first()
                )
                if not existing_lineage:
                    existing_lineage = DocumentLineage(
                        old_doc_id=old_doc.id,
                        new_doc_id=new_doc.id,
                        scope=scope,
                        amended_clauses=amended_clauses,
                        evidence_page=ev_page,
                        evidence_text=ev_text,
                    )
                    self.db.add(existing_lineage)
                else:
                    existing_lineage.scope = scope
                    existing_lineage.amended_clauses = amended_clauses
                    existing_lineage.evidence_page = ev_page
                    existing_lineage.evidence_text = ev_text

                # Update successor/amendment document
                new_doc.supersedes_doc_id = old_doc.id
                new_doc.status = "current"
                new_doc.expires_date = None
                for c in new_doc.chunks:
                    c.status = "current"
                    c.valid_from = new_doc.effective_date
                    c.valid_to = None
                    c.allowed_roles = new_doc.allowed_roles

                # Update predecessor document based on scope
                if scope == "full":
                    old_doc.status = "superseded"
                    old_doc.expires_date = effective_date
                    for c in old_doc.chunks:
                        c.status = "superseded"
                        c.valid_to = effective_date
                        c.allowed_roles = old_doc.allowed_roles
                elif scope == "partial":
                    old_doc.status = "partially_amended"
                    old_doc.expires_date = None
                    for c in old_doc.chunks:
                        c.allowed_roles = old_doc.allowed_roles
                        if c.clause_ref and c.clause_ref in amended_clauses:
                            c.status = "superseded"
                            c.valid_to = effective_date
                        else:
                            c.status = "current"
                            c.valid_to = None

                lineage_count += 1

        # Ensure all active, non-superseded documents have consistent chunk roles & dates
        all_docs = self.db.query(Document).all()
        for doc in all_docs:
            if doc.status == "current":
                for c in doc.chunks:
                    c.allowed_roles = doc.allowed_roles
                    if not c.valid_from:
                        c.valid_from = doc.effective_date

        self.db.commit()
        logger.info("Successfully processed %d lineage entries from %s", lineage_count, path)
        return lineage_count

    def ingest_manifest(
        self,
        manifest_path: str | Path,
        force: bool = False,
        lineage_path: Optional[str | Path] = None,
    ) -> IngestionReport:
        """Process documents in the manifest with idempotent updates.

        Args:
            manifest_path: Path to the documents_manifest.csv file.
            force: When True, re-chunk and re-embed documents even if hash is unchanged.
            lineage_path: Optional path to supersession_register.csv.

        Returns:
            IngestionReport summarizing the results of all documents.
        """
        report = IngestionReport()

        try:
            records = self.manifest_service.parse_manifest(manifest_path)
        except ManifestError as exc:
            err = f"Failed to load manifest '{manifest_path}': {exc}"
            logger.error(err)
            report.errors.append(err)
            return report

        report.total_documents = len(records)
        is_postgres = self.db.bind is not None and self.db.bind.dialect.name == "postgresql"

        for row in records:
            file_name = Path(row.file).name
            try:
                # 1. Safely resolve PDF path
                resolved_pdf = self.manifest_service.resolve_pdf_path(row.file)

                # 2. Parse PDF page by page
                parsed_pdf = self.pdf_parser.parse_pdf(resolved_pdf)
                doc_version = self.extract_doc_version(
                    file_name,
                    parsed_pdf.pages[0].text if parsed_pdf.pages else None,
                )

                # 3. Check for existing document for idempotency
                existing_doc = (
                    self.db.query(Document)
                    .filter(Document.file_name == file_name)
                    .first()
                )

                # Check if document has not changed and force is not set
                if existing_doc and existing_doc.file_hash == parsed_pdf.file_hash and not force:
                    # Update metadata if manifest was changed
                    existing_doc.title = row.title
                    existing_doc.doc_version = doc_version
                    existing_doc.effective_date = row.effective_date
                    existing_doc.supersedes = row.supersedes
                    existing_doc.allowed_roles = row.allowed_roles
                    for c in existing_doc.chunks:
                        c.allowed_roles = row.allowed_roles
                    self.db.commit()

                    logger.info("Document '%s' is up to date (hash match). Skipping re-chunking.", file_name)
                    report.skipped_count += 1
                    report.document_results.append(
                        DocumentIngestionResult(
                            file_name=file_name,
                            status="skipped",
                            total_pages=existing_doc.total_pages,
                            total_chunks=existing_doc.total_chunks,
                        )
                    )
                    continue

                # 4. Generate chunks page by page (strict boundary isolation)
                chunks_data = self.chunker.chunk_document(parsed_pdf)
                chunk_texts = [c.text for c in chunks_data]

                # 5. Generate embeddings
                embeddings = self.embedding_service.embed_texts(chunk_texts) if chunk_texts else []
                sem_embedder = self.semantic_embedder
                sem_embeddings = (
                    sem_embedder.embed_texts(chunk_texts)
                    if sem_embedder and chunk_texts
                    else []
                )

                # 6. Database Transaction (Atomic Upsert)
                doc_record = existing_doc
                if not doc_record:
                    doc_record = Document(
                        file_name=file_name,
                        file_hash=parsed_pdf.file_hash,
                        title=row.title,
                        doc_version=doc_version,
                        effective_date=row.effective_date,
                        supersedes=row.supersedes,
                        allowed_roles=row.allowed_roles,
                        status="current",
                        total_pages=parsed_pdf.total_pages,
                        total_chunks=len(chunks_data),
                    )
                    self.db.add(doc_record)
                    self.db.flush()  # Obtain doc_record.id
                else:
                    # Clear existing chunks for this document to avoid duplicates
                    self.db.query(Chunk).filter(Chunk.document_id == doc_record.id).delete()
                    doc_record.file_hash = parsed_pdf.file_hash
                    doc_record.title = row.title
                    doc_record.doc_version = doc_version
                    doc_record.effective_date = row.effective_date
                    doc_record.supersedes = row.supersedes
                    doc_record.allowed_roles = row.allowed_roles
                    doc_record.status = "current"
                    doc_record.total_pages = parsed_pdf.total_pages
                    doc_record.total_chunks = len(chunks_data)

                # Bulk insert new chunks with clause_ref, validity, status, and denormalized allowed_roles
                db_chunks = []
                for idx, c in enumerate(chunks_data):
                    tsv_val = func.to_tsvector("english", c.text) if is_postgres else c.text
                    chunk_obj = Chunk(
                        document_id=doc_record.id,
                        chunk_index=c.chunk_index,
                        page_number=c.page_number,
                        text=c.text,
                        token_count=c.token_count,
                        clause_ref=c.clause_ref,
                        valid_from=doc_record.effective_date,
                        valid_to=None,
                        status="current",
                        allowed_roles=doc_record.allowed_roles or [],
                        embedding=embeddings[idx],
                        tsv=tsv_val,
                    )
                    db_chunks.append(chunk_obj)

                if db_chunks:
                    self.db.add_all(db_chunks)
                    self.db.flush()  # Populate chunk_obj.id

                    if sem_embeddings:
                        from app.models.chunk_semantic import ChunkSemantic
                        db_sem_records = []
                        for idx, chunk_obj in enumerate(db_chunks):
                            sem_obj = ChunkSemantic(
                                chunk_id=chunk_obj.id,
                                embedding=sem_embeddings[idx],
                                model_name="all-MiniLM-L6-v2",
                            )
                            db_sem_records.append(sem_obj)
                        if db_sem_records:
                            self.db.add_all(db_sem_records)

                self.db.commit()

                report.ingested_count += 1
                report.total_chunks_created += len(chunks_data)
                report.document_results.append(
                    DocumentIngestionResult(
                        file_name=file_name,
                        status="ingested",
                        total_pages=parsed_pdf.total_pages,
                        total_chunks=len(chunks_data),
                    )
                )
                logger.info(
                    "Successfully ingested '%s': %d pages, %d chunks stored.",
                    file_name,
                    parsed_pdf.total_pages,
                    len(chunks_data),
                )

            except (ManifestError, PDFParsingError) as err:
                self.db.rollback()
                msg = f"Failed to process '{file_name}': {err}"
                logger.error(msg)
                report.failed_count += 1
                report.errors.append(msg)
                report.document_results.append(
                    DocumentIngestionResult(
                        file_name=file_name,
                        status="failed",
                        error_message=str(err),
                    )
                )

            except Exception as err:
                self.db.rollback()
                msg = f"Unexpected system error ingesting '{file_name}': {err}"
                logger.exception(msg)
                report.failed_count += 1
                report.errors.append(msg)
                report.document_results.append(
                    DocumentIngestionResult(
                        file_name=file_name,
                        status="failed",
                        error_message=str(err),
                    )
                )

        # 7. Ingest supersession register & resolve lineage
        reg_file = lineage_path
        if reg_file is None:
            # Check default paths
            cand1 = Path(manifest_path).parent / "supersession_register.csv"
            cand2 = Path("docs/supersession_register.csv")
            if cand1.is_file():
                reg_file = cand1
            elif cand2.is_file():
                reg_file = cand2

        if reg_file and Path(reg_file).is_file():
            report.lineage_records_created = self.ingest_lineage(reg_file)

        return report
