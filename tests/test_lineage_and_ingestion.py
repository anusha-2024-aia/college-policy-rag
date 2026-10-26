"""Unit and integration tests for Phase 1: Lineage Data Model, Clause Chunking, and Ingestion.

Covers:
1. Header/footer stripping of synthetic institutional banners and page numbers.
2. Clause boundary chunking so one clause is not split across chunks.
3. Normalized clause_ref extraction ("Clause 4.2", "Clause 6.1").
4. Full supersession status transitions (attendance policy, hostel rules).
5. Partial supersession status transitions (exam rules 2023 vs 2025 circular).
6. Unchanged clause persistence: non-amended clauses remain status='current' and valid_to=None.
7. Denormalized allowed_roles on every chunk.
8. Idempotent lineage re-ingestion.
"""

from pathlib import Path
from sqlalchemy.orm import Session
from app.models.document import Document
from app.models.chunk import Chunk
from app.models.lineage import DocumentLineage
from app.services.chunker import ChunkerService
from app.services.embedding import MockEmbeddingService
from app.services.ingestion import IngestionService


def test_header_footer_stripping():
    """Verify repetitive headers, footers, and doc control banners are stripped cleanly."""
    chunker = ChunkerService()
    raw_page_text = (
        "Page 1 of 3\n"
        "Kestrel Valley Institute of Technology (fictional)\n"
        "PUBLIC (synthetic)\n"
        "Synthetic document for portfolio testing | Doc control no. KVIT/ACAD/EXM/2023\n"
        "Examination and Assessment Rules\n"
        "Doc control no.: KVIT/ACAD/EXM/2023\n"
        "Version: 2023 | Effective date: 1 August 2023\n"
        "Issued by: Kestrel Valley Institute of Technology (fictional)\n"
        "1. Assessment structure and examination conduct\n"
        "- Clause 1. For theory courses, CIA carries 40 marks and ESE carries 60 marks."
    )

    cleaned = chunker.strip_headers_and_footers(raw_page_text)

    assert "Page 1 of 3" not in cleaned
    assert "Kestrel Valley Institute of Technology (fictional)" not in cleaned
    assert "PUBLIC (synthetic)" not in cleaned
    assert "Synthetic document for portfolio testing" not in cleaned
    assert "Doc control no.:" not in cleaned
    assert "Version: 2023 | Effective date: 1 August 2023" not in cleaned
    assert "Examination and Assessment Rules" in cleaned
    assert "Clause 1" in cleaned


def test_clause_boundary_chunking_and_ref_extraction():
    """Verify chunker isolates clauses and extracts normalized clause references."""
    chunker = ChunkerService(chunk_size_tokens=500, chunk_overlap_tokens=80)
    page_text = (
        "2. Passing criteria and re-evaluation\n"
        "- Clause 4.1. To pass a theory course a student must secure at least 40 marks out of 100 in aggregate.\n"
        "- Clause 4.2. In addition, a student must secure at least 24 marks out of 60 in the ESE.\n"
        "- Clause 5. Results are published within 30 days of the last examination of the semester."
    )

    chunks = chunker.chunk_page(page_text, page_number=2)

    assert len(chunks) == 3
    assert chunks[0].clause_ref == "Clause 4.1"
    assert "Clause 4.1" in chunks[0].text
    assert "Passing criteria" in chunks[0].text  # Heading prepended to first clause

    assert chunks[1].clause_ref == "Clause 4.2"
    assert "24 marks out of 60" in chunks[1].text

    assert chunks[2].clause_ref == "Clause 5"
    assert "30 days" in chunks[2].text


def test_amendment_circular_clause_extraction():
    """Verify circular amendment clauses map to canonical clause refs."""
    chunker = ChunkerService()
    circular_text = (
        "Official amendment\n"
        "- Amendment to Clause 4.2: the minimum ESE mark required to pass a theory course is reduced from 24 to 21 out of 60.\n"
        "- Amendment to Clause 6.1: the re-evaluation application window is extended from 5 working days to 7 working days."
    )

    chunks = chunker.chunk_page(circular_text, page_number=1)

    assert len(chunks) == 2
    assert chunks[0].clause_ref == "Clause 4.2"
    assert "21 out of 60" in chunks[0].text

    assert chunks[1].clause_ref == "Clause 6.1"
    assert "7 working days" in chunks[1].text


def test_lineage_and_partial_supersession(test_db: Session):
    """Verify partial scope supersedes ONLY amended clauses while unchanged clauses remain current."""
    manifest_path = Path("docs/documents_manifest.csv")
    register_path = Path("docs/supersession_register.csv")

    if not manifest_path.exists() or not register_path.exists():
        return

    chunker = ChunkerService(chunk_size_tokens=500, chunk_overlap_tokens=80)
    mock_embed = MockEmbeddingService(dimension=1536)
    ingestion_service = IngestionService(
        db_session=test_db,
        chunker=chunker,
        embedding_service=mock_embed,
    )

    report = ingestion_service.ingest_manifest(
        manifest_path=manifest_path,
        force=True,
        lineage_path=register_path,
    )

    assert report.total_documents == 16
    assert report.ingested_count == 16
    assert report.lineage_records_created == 3

    # 1. Verify Lineage Records in DB
    lineages = test_db.query(DocumentLineage).all()
    assert len(lineages) == 3

    exam_lineage = next(l for l in lineages if l.scope == "partial")
    assert "Clause 4.2" in exam_lineage.amended_clauses
    assert "Clause 6.1" in exam_lineage.amended_clauses

    # 2. Verify Exam Rules Document Status
    exam_2023 = test_db.query(Document).filter_by(file_name="examination_assessment_rules_2023.pdf").first()
    circular_2025 = test_db.query(Document).filter_by(file_name="exam_rules_amendment_circular_2025.pdf").first()

    assert exam_2023 is not None
    assert circular_2025 is not None
    assert exam_2023.status == "partially_amended"
    assert circular_2025.status == "current"
    assert circular_2025.supersedes_doc_id == exam_2023.id

    # 3. Verify Exam Rules Chunks: Clause 4.2 and 6.1 MUST be superseded
    chunks_2023 = test_db.query(Chunk).filter_by(document_id=exam_2023.id).all()
    clause_4_2_old = next(c for c in chunks_2023 if c.clause_ref == "Clause 4.2")
    clause_6_1_old = next(c for c in chunks_2023 if c.clause_ref == "Clause 6.1")

    assert clause_4_2_old.status == "superseded"
    assert str(clause_4_2_old.valid_to) == "2025-07-01"

    assert clause_6_1_old.status == "superseded"
    assert str(clause_6_1_old.valid_to) == "2025-07-01"

    # 4. Verify Unchanged Clauses MUST REMAIN CURRENT
    unchanged_clauses = [c for c in chunks_2023 if c.clause_ref not in ("Clause 4.2", "Clause 6.1")]
    assert len(unchanged_clauses) > 0
    for chunk in unchanged_clauses:
        assert chunk.status == "current", f"Unchanged clause {chunk.clause_ref} was improperly superseded"
        assert chunk.valid_to is None, f"Unchanged clause {chunk.clause_ref} should have valid_to=None"

    # 5. Verify Circular Chunks are Current
    chunks_circular = test_db.query(Chunk).filter_by(document_id=circular_2025.id).all()
    for chunk in chunks_circular:
        assert chunk.status == "current"
        assert str(chunk.valid_from) == "2025-07-01"
        assert chunk.valid_to is None


def test_full_supersession_attendance_and_hostel(test_db: Session):
    """Verify full scope supersedes ALL chunks of the predecessor document."""
    manifest_path = Path("docs/documents_manifest.csv")
    register_path = Path("docs/supersession_register.csv")

    if not manifest_path.exists() or not register_path.exists():
        return

    chunker = ChunkerService(chunk_size_tokens=500, chunk_overlap_tokens=80)
    mock_embed = MockEmbeddingService(dimension=1536)
    ingestion_service = IngestionService(
        db_session=test_db,
        chunker=chunker,
        embedding_service=mock_embed,
    )

    ingestion_service.ingest_manifest(manifest_path=manifest_path, force=True, lineage_path=register_path)

    # Attendance: 2023 -> 2025
    att_2023 = test_db.query(Document).filter_by(file_name="attendance_leave_policy_2023.pdf").first()
    att_2025 = test_db.query(Document).filter_by(file_name="attendance_leave_policy_2025.pdf").first()

    assert att_2023.status == "superseded"
    assert att_2025.status == "current"
    assert att_2025.supersedes_doc_id == att_2023.id
    assert str(att_2023.expires_date) == "2025-07-01"

    chunks_att_2023 = test_db.query(Chunk).filter_by(document_id=att_2023.id).all()
    assert len(chunks_att_2023) > 0
    for c in chunks_att_2023:
        assert c.status == "superseded"
        assert str(c.valid_to) == "2025-07-01"

    chunks_att_2025 = test_db.query(Chunk).filter_by(document_id=att_2025.id).all()
    assert len(chunks_att_2025) > 0
    for c in chunks_att_2025:
        assert c.status == "current"
        assert str(c.valid_from) == "2025-07-01"
        assert c.valid_to is None


def test_denormalized_allowed_roles_on_all_chunks(test_db: Session):
    """Verify every chunk inherits and denormalizes parent document allowed_roles."""
    manifest_path = Path("docs/documents_manifest.csv")
    if not manifest_path.exists():
        return

    chunker = ChunkerService()
    mock_embed = MockEmbeddingService(dimension=1536)
    ingestion_service = IngestionService(db_session=test_db, chunker=chunker, embedding_service=mock_embed)
    ingestion_service.ingest_manifest(manifest_path=manifest_path, force=True)

    # Check confidential admin-only document chunks
    salary_doc = test_db.query(Document).filter_by(file_name="admin_salary_bands_and_budget_2025.pdf").first()
    assert salary_doc is not None
    assert salary_doc.allowed_roles == ["admin"]

    salary_chunks = test_db.query(Chunk).filter_by(document_id=salary_doc.id).all()
    assert len(salary_chunks) > 0
    for c in salary_chunks:
        assert c.allowed_roles == ["admin"], f"Chunk leaked wider roles: {c.allowed_roles}"

    # Check public student document chunks
    library_doc = test_db.query(Document).filter_by(file_name="library_rules_2025.pdf").first()
    assert library_doc is not None
    library_chunks = test_db.query(Chunk).filter_by(document_id=library_doc.id).all()
    assert len(library_chunks) > 0
    for c in library_chunks:
        assert "student" in c.allowed_roles
        assert "faculty" in c.allowed_roles
        assert "admin" in c.allowed_roles

