"""Document version graph, supersedes validation, and policy conflict detection service."""

import logging
import re
from dataclasses import dataclass
from typing import Optional
from app.models.document import Document
from app.schemas.qa import PassageEvidence, PolicyConflict

logger = logging.getLogger(__name__)


class VersionError(Exception):
    """Base exception for document version graph and relationship errors."""
    pass


class MissingSupersedesTargetError(VersionError):
    """Raised when a document's supersedes reference cannot be resolved."""
    pass


class CircularVersionError(VersionError):
    """Raised when a cycle is detected in document version relationships."""
    pass


class TemporalOrderError(VersionError):
    """Raised when an older document claims to supersede a newer document."""
    pass


@dataclass
class DocumentVersionStatus:
    """Version metadata and status for a specific document."""

    document_id: str
    file_name: str
    title: str
    effective_date: str
    is_superseded: bool
    is_partially_amended: bool = False
    amendment_scope: Optional[str] = None
    amended_by_id: Optional[str] = None
    amended_by_title: Optional[str] = None
    amended_by_file: Optional[str] = None
    is_amendment: bool = False
    amends_title: Optional[str] = None
    amends_file: Optional[str] = None
    superseded_by_id: Optional[str] = None
    superseded_by_title: Optional[str] = None
    superseded_by_file: Optional[str] = None
    supersedes_target: Optional[str] = None
    lineage_root_id: str = ""
    version_rank: int = 1


class DocumentVersionService:
    """Manages document version lineages, relationship validation, and policy conflict detection."""

    def build_version_graph(
        self, documents: list[Document], strict_validation: bool = True
    ) -> dict[str, DocumentVersionStatus]:
        """Construct and validate the version graph for a collection of documents.

        Args:
            documents: List of Document ORM models.
            strict_validation: If True, raises exceptions for missing targets, cycles,
                               or temporal order violations. If False, logs warnings.

        Returns:
            Dictionary mapping document_id to DocumentVersionStatus.
        """
        # Lookups for resolving targets by ID, file_name, or title
        by_id: dict[str, Document] = {d.id: d for d in documents}
        by_file: dict[str, Document] = {d.file_name: d for d in documents}
        by_title: dict[str, Document] = {d.title: d for d in documents}

        # Successor mapping: predecessor_id -> successor Document (the newer doc that supersedes it)
        successor_map: dict[str, Document] = {}
        # Predecessor mapping: successor_id -> predecessor Document
        predecessor_map: dict[str, Document] = {}
        # Partial amendment mappings:
        partial_amendment_map: dict[str, tuple[Document, Optional[str]]] = {}
        amendment_of_map: dict[str, tuple[Document, Optional[str]]] = {}

        for doc in documents:
            raw_target = (doc.supersedes or "").strip()
            if not raw_target:
                continue

            # Check if this relationship represents a partial amendment
            is_partial = False
            scope_str: Optional[str] = None
            if raw_target.lower().startswith("partial:"):
                is_partial = True
                parts = raw_target.split(":", 2)
                if len(parts) == 3:
                    scope_str = parts[1].strip()
                    target_ref = parts[2].strip()
                else:
                    target_ref = parts[1].strip()
            else:
                target_ref = raw_target

            # Resolve target by title, file_name, or ID
            target_doc = by_title.get(target_ref) or by_file.get(target_ref) or by_id.get(target_ref)
            if not target_doc:
                msg = (
                    f"Document '{doc.title}' ({doc.file_name}) supersedes target '{target_ref}' "
                    "which does not exist in the collection."
                )
                if strict_validation:
                    raise MissingSupersedesTargetError(msg)
                logger.warning(msg)
                continue

            # Temporal order validation: predecessor effective_date must be <= successor effective_date
            if target_doc.effective_date and doc.effective_date:
                if target_doc.effective_date > doc.effective_date:
                    msg = (
                        f"Temporal violation: Document '{doc.title}' (effective {doc.effective_date}) "
                        f"claims to supersede '{target_doc.title}' which has a later effective date "
                        f"({target_doc.effective_date})."
                    )
                    if strict_validation:
                        raise TemporalOrderError(msg)
                    logger.warning(msg)

            if is_partial:
                partial_amendment_map[target_doc.id] = (doc, scope_str)
                amendment_of_map[doc.id] = (target_doc, scope_str)
                predecessor_map[doc.id] = target_doc
            else:
                successor_map[target_doc.id] = doc
                predecessor_map[doc.id] = target_doc

        # Cycle detection using DFS
        visited: set[str] = set()
        rec_stack: set[str] = set()

        def detect_cycle(current_id: str, path: list[str]) -> None:
            visited.add(current_id)
            rec_stack.add(current_id)

            successor = successor_map.get(current_id) or (
                partial_amendment_map[current_id][0] if current_id in partial_amendment_map else None
            )
            if successor:
                succ_id = successor.id
                if succ_id in rec_stack:
                    cycle_names = [by_id[nid].title for nid in path + [succ_id]]
                    msg = f"Circular document version relationship detected: {' -> '.join(cycle_names)}"
                    if strict_validation:
                        raise CircularVersionError(msg)
                    logger.error(msg)
                elif succ_id not in visited:
                    detect_cycle(succ_id, path + [succ_id])

            rec_stack.remove(current_id)

        for doc_id in by_id:
            if doc_id not in visited:
                detect_cycle(doc_id, [doc_id])

        # Compute version status for all documents
        status_map: dict[str, DocumentVersionStatus] = {}

        for doc in documents:
            is_superseded = doc.id in successor_map
            successor = successor_map.get(doc.id)

            is_partially_amended = doc.id in partial_amendment_map
            amended_by = partial_amendment_map.get(doc.id)

            is_amendment = doc.id in amendment_of_map
            amends = amendment_of_map.get(doc.id)

            # Determine lineage root (earliest ancestor) and version rank
            curr = doc
            rank = 1
            while curr.id in predecessor_map:
                curr = predecessor_map[curr.id]
                rank += 1
            root_id = curr.id

            eff_date_str = doc.effective_date.isoformat() if doc.effective_date else ""

            status_map[doc.id] = DocumentVersionStatus(
                document_id=doc.id,
                file_name=doc.file_name,
                title=doc.title,
                effective_date=eff_date_str,
                is_superseded=is_superseded,
                is_partially_amended=is_partially_amended,
                amendment_scope=amended_by[1] if amended_by else (amends[1] if amends else None),
                amended_by_id=amended_by[0].id if amended_by else None,
                amended_by_title=amended_by[0].title if amended_by else None,
                amended_by_file=amended_by[0].file_name if amended_by else None,
                is_amendment=is_amendment,
                amends_title=amends[0].title if amends else None,
                amends_file=amends[0].file_name if amends else None,
                superseded_by_id=successor.id if successor else None,
                superseded_by_title=successor.title if successor else None,
                superseded_by_file=successor.file_name if successor else None,
                supersedes_target=(doc.supersedes or "").strip() or None,
                lineage_root_id=root_id,
                version_rank=rank,
            )

        return status_map

    def detect_conflicts(
        self,
        passages: list[PassageEvidence],
        version_statuses: dict[str, DocumentVersionStatus],
    ) -> tuple[bool, list[PolicyConflict]]:
        """Identify policy conflicts when evidence contains both active and superseded documents in the same lineage.

        Args:
            passages: Retrieved context passages.
            version_statuses: Version status lookup by document_id or file_name.

        Returns:
            Tuple of (has_conflict: bool, list_of_conflicts).
        """
        if not passages:
            return False, []

        # Map file_name to status for quick passage lookup
        status_by_file: dict[str, DocumentVersionStatus] = {
            s.file_name: s for s in version_statuses.values()
        }

        # Group passages by lineage root
        passages_by_lineage: dict[str, list[PassageEvidence]] = {}
        for p in passages:
            status = status_by_file.get(p.file_name)
            if status:
                lineage_id = status.lineage_root_id
                passages_by_lineage.setdefault(lineage_id, []).append(p)

        # Determine relevant lineages based on top retrieval score
        top_passage = passages[0]
        top_status = status_by_file.get(top_passage.file_name)
        top_lineage_id = top_status.lineage_root_id if top_status else None
        top_score = top_passage.score

        # Only evaluate lineages that are relevant to the query (either matching top lineage or close in relevance)
        relevant_lineages = {
            lid for lid, l_passages in passages_by_lineage.items()
            if (lid == top_lineage_id) or (max((p.score for p in l_passages), default=0.0) >= max(0.05, top_score * 0.7))
        }

        conflicts: list[PolicyConflict] = []

        for lineage_id in relevant_lineages:
            lineage_passages = passages_by_lineage[lineage_id]
            # Separate active vs superseded passages in this lineage
            active_passages = [
                p for p in lineage_passages
                if not status_by_file.get(p.file_name, DocumentVersionStatus("", "", "", "", False)).is_superseded
            ]
            superseded_passages = [
                p for p in lineage_passages
                if status_by_file.get(p.file_name, DocumentVersionStatus("", "", "", "", False)).is_superseded
            ]

            # 1. Full supersession conflict
            if active_passages and superseded_passages:
                cur_p = active_passages[0]
                old_p = superseded_passages[0]
                cur_status = status_by_file[cur_p.file_name]
                old_status = status_by_file[old_p.file_name]

                conflict = PolicyConflict(
                    current_title=cur_status.title,
                    current_file=cur_p.file_name,
                    current_effective_date=cur_status.effective_date,
                    current_citation_index=cur_p.index,
                    superseded_title=old_status.title,
                    superseded_file=old_p.file_name,
                    superseded_effective_date=old_status.effective_date,
                    superseded_citation_index=old_p.index,
                    description=(
                        f"Policy '{old_status.title}' (effective {old_status.effective_date}) "
                        f"has been superseded by '{cur_status.title}' (effective {cur_status.effective_date})."
                    ),
                )
                conflicts.append(conflict)

            # 2. Partial amendment conflict
            amendment_passages = [
                p for p in active_passages
                if status_by_file.get(p.file_name, DocumentVersionStatus("", "", "", "", False)).is_amendment
            ]
            amended_passages = [
                p for p in active_passages
                if status_by_file.get(p.file_name, DocumentVersionStatus("", "", "", "", False)).is_partially_amended
            ]

            if amendment_passages and amended_passages:
                for amen_p in amendment_passages:
                    amen_stat = status_by_file[amen_p.file_name]
                    scope_text = amen_stat.amendment_scope or ""
                    clause_ids = re.findall(r"\b\d+\.\d+\b", scope_text)
                    reported_pairs: set[tuple[str, str]] = set()

                    for base_p in amended_passages:
                        pair_key = (amen_p.file_name, base_p.file_name)
                        if pair_key in reported_pairs:
                            continue

                        touches_clause = False
                        if clause_ids:
                            for c in clause_ids:
                                if re.search(r"\b(?:clause|section|sec\.|cl\.)?\s*[-:]?\s*" + re.escape(c) + r"\b", base_p.text, re.IGNORECASE):
                                    touches_clause = True
                                    break
                        else:
                            touches_clause = True

                        if touches_clause:
                            base_stat = status_by_file[base_p.file_name]
                            scope_desc = f" ({amen_stat.amendment_scope})" if amen_stat.amendment_scope else ""
                            conflict = PolicyConflict(
                                current_title=amen_stat.title,
                                current_file=amen_p.file_name,
                                current_effective_date=amen_stat.effective_date,
                                current_citation_index=amen_p.index,
                                superseded_title=base_stat.title,
                                superseded_file=base_p.file_name,
                                superseded_effective_date=base_stat.effective_date,
                                superseded_citation_index=base_p.index,
                                description=(
                                    f"Provisions in '{base_stat.title}' (effective {base_stat.effective_date}) "
                                    f"amended{scope_desc} by '{amen_stat.title}' (effective {amen_stat.effective_date})."
                                ),
                            )
                            conflicts.append(conflict)
                            reported_pairs.add(pair_key)
                            break

        return len(conflicts) > 0, conflicts
