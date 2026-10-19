"""Ingestion service orchestrating manifest parsing, PDF extraction, chunking, and storage."""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.document import Document
from app.models.chunk import Chunk
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
    document_results: list[DocumentIngestionResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class IngestionService:
    """Idempotent ingestion pipeline orchestrator."""

    def __init__(
        self,
        db_session: Session,
        manifest_service: Optional[ManifestService] = None,
        pdf_parser: Optional[PDFParserService] = None,
        chunker: Optional[ChunkerService] = None,
        embedding_service: Optional[BaseEmbeddingService] = None,
        semantic_embedding_service: Optional[any] = None,
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

    def ingest_manifest(
        self,
        manifest_path: str | Path,
        force: bool = False,
    ) -> IngestionReport:
        """Process documents in the manifest with idempotent updates.

        Args:
            manifest_path: Path to the documents_manifest.csv file.
            force: When True, re-chunk and re-embed documents even if hash is unchanged.

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
                    existing_doc.effective_date = row.effective_date
                    existing_doc.supersedes = row.supersedes
                    existing_doc.allowed_roles = row.allowed_roles
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
                        effective_date=row.effective_date,
                        supersedes=row.supersedes,
                        allowed_roles=row.allowed_roles,
                        status="ingested",
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
                    doc_record.effective_date = row.effective_date
                    doc_record.supersedes = row.supersedes
                    doc_record.allowed_roles = row.allowed_roles
                    doc_record.status = "ingested"
                    doc_record.total_pages = parsed_pdf.total_pages
                    doc_record.total_chunks = len(chunks_data)

                # Bulk insert new chunks
                db_chunks = []
                for idx, c in enumerate(chunks_data):
                    tsv_val = func.to_tsvector("english", c.text) if is_postgres else c.text
                    chunk_obj = Chunk(
                        document_id=doc_record.id,
                        chunk_index=c.chunk_index,
                        page_number=c.page_number,
                        text=c.text,
                        token_count=c.token_count,
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

        return report
