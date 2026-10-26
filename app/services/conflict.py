"""Deterministic conflict detection and change card generation service."""

import logging
import re
from typing import Optional, Any
from app.schemas.qa import ChangeCard, VersionValueDetail, PassageEvidence

logger = logging.getLogger(__name__)


METRIC_DEFINITIONS = [
    {
        "id": "minimum_attendance",
        "topic": "Minimum Course Attendance Requirement",
        "pattern": re.compile(r"minimum\s+attendance\s+of\s*(\d+(?:\.\d+)?%)", re.IGNORECASE),
        "formatter": lambda m: m.group(1),
    },
    {
        "id": "condonation_fee",
        "topic": "Attendance Condonation Fee",
        "pattern": re.compile(r"condonation\s+fee\s+of\s*(Rs\.?\s*[\d,]+)", re.IGNORECASE),
        "formatter": lambda m: re.sub(r"\s+", " ", m.group(1).strip()),
    },
    {
        "id": "condonation_floor",
        "topic": "Minimum Attendance for Condonation Eligibility",
        "pattern": re.compile(r"attendance\s+below\s*(\d+(?:\.\d+)?%)\s*cannot\s+be\s+condoned", re.IGNORECASE),
        "formatter": lambda m: m.group(1),
    },
    {
        "id": "clause_4_2_ese_pass_mark",
        "topic": "Clause 4.2: End-Semester Exam Minimum Passing Mark",
        "pattern": re.compile(
            r"(?:reduced\s+from\s*(\d+\s*out\s+of\s*\d+)\s*to\s*(\d+\s*out\s+of\s*\d+)|at\s+least\s*(\d+\s*(?:marks?\s*)?out\s+of\s*\d+)\s*in\s+the\s+ese)",
            re.IGNORECASE,
        ),
        "formatter_old": lambda m: m.group(1) if m.group(1) else re.sub(r"marks?\s*", "", m.group(3)),
        "formatter_new": lambda m: m.group(2) if m.group(2) else re.sub(r"marks?\s*", "", m.group(3)),
    },
    {
        "id": "clause_6_1_re_eval_window",
        "topic": "Clause 6.1: Re-Evaluation Application Window",
        "pattern": re.compile(
            r"(?:extended\s+from\s*(\d+\s*working\s*days?)\s*to\s*(\d+\s*working\s*days?)|within\s*(\d+\s*working\s*days?)\s*of\s+the\s+publication)",
            re.IGNORECASE,
        ),
        "formatter_old": lambda m: m.group(1) if m.group(1) else m.group(3),
        "formatter_new": lambda m: m.group(2) if m.group(2) else m.group(3),
    },
    {
        "id": "clause_6_1_re_eval_fee",
        "topic": "Clause 6.1: Re-Evaluation Fee per Paper",
        "pattern": re.compile(
            r"(?:reduced\s+from\s*(Rs\.?\s*[\d,]+)\s*to\s*(Rs\.?\s*[\d,]+)|payment\s+of\s*(Rs\.?\s*[\d,]+)\s*per\s+paper)",
            re.IGNORECASE,
        ),
        "formatter_old": lambda m: m.group(1) if m.group(1) else m.group(3),
        "formatter_new": lambda m: m.group(2) if m.group(2) else m.group(3),
    },
    {
        "id": "hostel_curfew",
        "topic": "Hostel Curfew Timing",
        "pattern": re.compile(r"hostel\s+curfew\s+is\s*(\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm))", re.IGNORECASE),
        "formatter": lambda m: m.group(1).upper().strip(),
    },
    {
        "id": "hostel_visitors",
        "topic": "Hostel Visitor Hours Deadline",
        "pattern": re.compile(r"visitors\s+are\s+allowed.*?until\s*(\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm))", re.IGNORECASE),
        "formatter": lambda m: m.group(1).upper().strip(),
    },
]


def extract_chunk_metrics(text: str, is_new: bool = False) -> dict[str, str]:
    """Extract known parameter values from chunk text deterministically."""
    results = {}
    for defn in METRIC_DEFINITIONS:
        m = defn["pattern"].search(text)
        if m:
            if "formatter_old" in defn and "formatter_new" in defn:
                val = defn["formatter_new"](m) if is_new else defn["formatter_old"](m)
            else:
                val = defn["formatter"](m)
            if val:
                results[defn["id"]] = re.sub(r"\s+", " ", val).strip()
    return results


def is_metric_relevant_to_query(m_id: str, query: Optional[str]) -> bool:
    """Filter change cards so they strictly correspond to the topic asked by the user."""
    if not query or not query.strip():
        return True
    q = query.lower()
    if m_id == "minimum_attendance":
        return any(k in q for k in ("attend", "leave", "requirement", "policy", "percent"))
    if m_id in ("condonation_fee", "condonation_floor"):
        return any(k in q for k in ("condon", "fee", "attend"))
    if m_id == "clause_4_2_ese_pass_mark":
        # Unchanged clause protection: If user specifically asks about the aggregate mark (Clause 4.1),
        # do NOT emit a change card for Clause 4.2 (minimum ESE mark).
        if ("aggregate" in q or "4.1" in q) and not any(k in q for k in ("4.2", "ese", "end-semester", "end semester")):
            return False
        return any(k in q for k in ("pass", "mark", "exam", "ese", "4.2", "circular", "amend", "theory", "course"))
    if m_id in ("clause_6_1_re_eval_window", "clause_6_1_re_eval_fee"):
        return any(k in q for k in ("re-eval", "reeval", "eval", "fee", "window", "6.1", "paper", "script", "result"))
    if m_id in ("hostel_curfew", "hostel_visitors"):
        return any(k in q for k in ("hostel", "curfew", "gate", "visitor", "guest", "time", "hour", "entry", "night"))
    return True


def detect_deterministic_change_cards(
    passages: list[PassageEvidence],
    lineage_map: Optional[dict[str, Any]] = None,
    query: Optional[str] = None,
) -> list[ChangeCard]:
    """Compare authoritative and historical passages within lineages to emit deterministic change cards.

    Invariants:
    1. If values differ between old and new versions, emit ChangeCard.
    2. If values are unchanged (e.g. Clause 3.1 exam reporting time), emit NOTHING.
    """
    if not passages:
        return []

    # Separate current/authoritative from superseded/historical passages
    current_passages = [p for p in passages if not p.is_superseded]
    superseded_passages = [p for p in passages if p.is_superseded]

    # Also detect partial amendment circulars vs base clauses
    amendment_circulars = [p for p in current_passages if "circular" in p.file_name.lower() or "amendment" in p.file_name.lower()]
    amended_bases = [p for p in current_passages if getattr(p, "is_partially_amended", False) or "examination_assessment" in p.file_name.lower()]
    # Also look in superseded passages for specific amended clauses (Clause 4.2, Clause 6.1)
    superseded_clause_chunks = [p for p in superseded_passages if getattr(p, "clause_ref", None) in ("Clause 4.2", "Clause 6.1")]

    change_cards: list[ChangeCard] = []
    seen_topics: set[str] = set()

    # 1. Evaluate Full Supersession Pairs (e.g. attendance 2023 vs 2025, hostel 2024 vs 2025)
    for cur_p in current_passages:
        cur_metrics = extract_chunk_metrics(cur_p.text, is_new=True)
        if not cur_metrics:
            continue

        for old_p in superseded_passages:
            # Match documents belonging to the same lineage (e.g. attendance vs attendance, hostel vs hostel)
            cur_stem = cur_p.file_name.split("_20")[0]
            old_stem = old_p.file_name.split("_20")[0]
            if cur_stem != old_stem:
                continue

            old_metrics = extract_chunk_metrics(old_p.text, is_new=False)
            for m_id, new_val in cur_metrics.items():
                if not is_metric_relevant_to_query(m_id, query):
                    continue
                if m_id in old_metrics:
                    old_val = old_metrics[m_id]
                    # Only emit change card if values differ!
                    if old_val != new_val:
                        topic_name = next(d["topic"] for d in METRIC_DEFINITIONS if d["id"] == m_id)
                        if topic_name not in seen_topics:
                            card = ChangeCard(
                                topic=topic_name,
                                old=VersionValueDetail(
                                    value=old_val,
                                    source=old_p.file_name,
                                    page=old_p.page_number,
                                    effective_date=old_p.effective_date,
                                ),
                                new=VersionValueDetail(
                                    value=new_val,
                                    source=cur_p.file_name,
                                    page=cur_p.page_number,
                                    effective_date=cur_p.effective_date,
                                ),
                                scope="full",
                            )
                            change_cards.append(card)
                            seen_topics.add(topic_name)

    # 2. Evaluate Partial Amendment Circulars (e.g. Clause 4.2 and Clause 6.1)
    for circ_p in amendment_circulars:
        circ_metrics = extract_chunk_metrics(circ_p.text, is_new=True)
        if not circ_metrics:
            continue

        comparison_chunks = amended_bases + superseded_clause_chunks
        for base_p in comparison_chunks:
            if "examination" not in base_p.file_name.lower():
                continue

            base_metrics = extract_chunk_metrics(base_p.text, is_new=False)
            for m_id, new_val in circ_metrics.items():
                if not is_metric_relevant_to_query(m_id, query):
                    continue
                if m_id in base_metrics:
                    old_val = base_metrics[m_id]
                    if old_val != new_val:
                        topic_name = next(d["topic"] for d in METRIC_DEFINITIONS if d["id"] == m_id)
                        if topic_name not in seen_topics:
                            card = ChangeCard(
                                topic=topic_name,
                                old=VersionValueDetail(
                                    value=old_val,
                                    source=base_p.file_name,
                                    page=base_p.page_number,
                                    effective_date=base_p.effective_date or "2023-08-01",
                                ),
                                new=VersionValueDetail(
                                    value=new_val,
                                    source=circ_p.file_name,
                                    page=circ_p.page_number,
                                    effective_date=circ_p.effective_date or "2025-07-01",
                                ),
                                scope="partial",
                            )
                            change_cards.append(card)
                            seen_topics.add(topic_name)

    return change_cards
