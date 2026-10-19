"""Semantic Embedding Benchmark and Retrieval Quality Evaluation Suite (Phase 5.1A).

This module provides a rigorous, offline evaluation benchmark to assess semantic retrieval
quality on a curated corpus of synthetic college policy queries, paraphrased target passages,
vocabulary-sharing hard negatives, and soft distractors.

CRITICAL GUARDRAILS:
- All benchmark examples are explicitly labeled synthetic and kept distinct from official
  institutional policies.
- Evaluates both pairwise cosine-similarity diagnostics and corpus-level ranking metrics
  (Recall@1, Recall@3, Recall@5, MRR) over a pooled candidate corpus.
- Evaluates MockEmbeddingService empirically to demonstrate baseline hash behavior.
- Real semantic models without locally available weights or approved API credentials are
  reported strictly as BLOCKED; zero results are fabricated.
- Purely offline, deterministic, and makes zero network calls or database modifications.
"""

import math
import json
import logging
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from app.services.embedding import BaseEmbeddingService, MockEmbeddingService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Expanded Synthetic College Policy Dataset (15 Topics, 45 Passages)
# ---------------------------------------------------------------------------
# Each item contains:
# - A natural language student query (informal / rephrased).
# - A semantically equivalent relevant passage (formal institutional policy, low keyword overlap).
# - A hard negative passage (high vocabulary/topic overlap with the query, but answers a different policy question).
# - A soft distractor passage (completely unrelated policy domain).

SYNTHETIC_BENCHMARK_ITEMS = [
    {
        "id": "SEM-001",
        "topic": "Academic Misconduct / Cheating",
        "query": "What happens if a student is caught cheating during a semester exam?",
        "relevant_passage_id": "P-001-REL",
        "relevant_passage": (
            "Students found violating testing integrity or utilizing unauthorized aids will be awarded "
            "a grade of 'XF' denoting academic dishonesty and referred to the Disciplinary Committee for immediate suspension."
        ),
        "hard_negative_id": "P-001-HN",
        "hard_negative_passage": (
            "Faculty proctors assigned to semester exam halls must arrive thirty minutes prior to scheduled start times "
            "to inspect student ID cards and distribute examination answer booklets."
        ),
        "soft_distractor_id": "P-001-DIST",
        "soft_distractor_passage": (
            "Students may reserve group study rooms in the central library for a maximum of two consecutive hours per day."
        ),
        "notes": "Paraphrase uses 'testing integrity' and 'grade of XF'; hard negative shares 'semester exam' and 'student ID' vocabulary.",
    },
    {
        "id": "SEM-002",
        "topic": "Tuition Fee Refund Schedule",
        "query": "How much money do I get back if I withdraw from classes in the second week?",
        "relevant_passage_id": "P-002-REL",
        "relevant_passage": (
            "Written withdrawal requests submitted within the first fourteen calendar days of the term "
            "are eligible for an eighty percent reimbursement of assessed tuition charges."
        ),
        "hard_negative_id": "P-002-HN",
        "hard_negative_passage": (
            "Laboratory breakage fees and specialized equipment deposits are non-refundable after the second week "
            "of classes and will be forfeited to department maintenance accounts."
        ),
        "soft_distractor_id": "P-002-DIST",
        "soft_distractor_passage": (
            "Campus parking permits must be permanently displayed on the rear rearview mirror of registered motor vehicles."
        ),
        "notes": "Paraphrase uses 'fourteen calendar days' and 'eighty percent reimbursement'; hard negative shares 'second week' and fee vocabulary.",
    },
    {
        "id": "SEM-003",
        "topic": "Hostel Dormitory Curfew & Night Entry",
        "query": "What is the latest time residents can enter the dormitory at night?",
        "relevant_passage_id": "P-003-REL",
        "relevant_passage": (
            "All residential facility entry doors lock promptly at 10:00 PM; late admissions require security supervisor "
            "sign-in, parental notification, and biometric verification."
        ),
        "hard_negative_id": "P-003-HN",
        "hard_negative_passage": (
            "Hostel room electrical appliances must not exceed 500 watts per resident, and heating coils are strictly prohibited "
            "during overnight hours by campus fire marshals."
        ),
        "soft_distractor_id": "P-003-DIST",
        "soft_distractor_passage": (
            "Laboratory safety goggles and flame-retardant coats are mandatory for all chemistry practical experiments."
        ),
        "notes": "Paraphrase uses 'residential facility' and 'lock promptly at 10:00 PM'; hard negative shares 'hostel' and 'overnight hours'.",
    },
    {
        "id": "SEM-004",
        "topic": "Academic Probation & Minimum GPA",
        "query": "What GPA triggers an academic warning or suspension?",
        "relevant_passage_id": "P-004-REL",
        "relevant_passage": (
            "Undergraduate matriculants whose cumulative grade average falls beneath 2.00 will be placed on remedial status "
            "for one subsequent academic quarter before disqualification."
        ),
        "hard_negative_id": "P-004-HN",
        "hard_negative_passage": (
            "Student-athletes must maintain a minimum semester grade point average of 2.50 to retain varsity intercollegiate "
            "competition eligibility and team captaincy."
        ),
        "soft_distractor_id": "P-004-DIST",
        "soft_distractor_passage": (
            "Auditorium reservations for cultural student clubs must be requested at least ten business days in advance from Student Affairs."
        ),
        "notes": "Paraphrase uses 'cumulative grade average beneath 2.00' and 'remedial status'; hard negative shares GPA and threshold numbers.",
    },
    {
        "id": "SEM-005",
        "topic": "Degree Graduation Requirements",
        "query": "How many credits and what requirements are mandatory to earn a degree?",
        "relevant_passage_id": "P-005-REL",
        "relevant_passage": (
            "Baccalaureate degrees require successful fulfillment of 120 course credits, completion of all general education "
            "core requirements, and a minimum cumulative grade index of 2.0."
        ),
        "hard_negative_id": "P-005-HN",
        "hard_negative_passage": (
            "External transfer credits from accredited collegiate institutions are capped at 60 total semester hours and must receive "
            "prior written approval from the Department Chair."
        ),
        "soft_distractor_id": "P-005-DIST",
        "soft_distractor_passage": (
            "Infirmary visits requiring emergency medication or overnight observation will be billed directly to the student group health plan."
        ),
        "notes": "Paraphrase uses 'Baccalaureate degrees' and '120 course credits'; hard negative shares 'credits' and academic transfer rules.",
    },
    {
        "id": "SEM-006",
        "topic": "Grade Appeal & Re-evaluation",
        "query": "Can I challenge an unfair final exam grade given by an instructor?",
        "relevant_passage_id": "P-006-REL",
        "relevant_passage": (
            "Formal grade grievances alleging arbitrary evaluation must be filed in writing with the Academic Dean within ten business days "
            "of official term score publication."
        ),
        "hard_negative_id": "P-006-HN",
        "hard_negative_passage": (
            "Course instructors must submit verified final semester grades through the faculty web portal no later than 72 hours following "
            "the conclusion of the scheduled exam period."
        ),
        "soft_distractor_id": "P-006-DIST",
        "soft_distractor_passage": (
            "Cafeteria meal plans may be converted to dining debit points within the first five instructional days of each semester."
        ),
        "notes": "Paraphrase uses 'formal grade grievances' and 'arbitrary evaluation'; hard negative shares 'final semester grades' and 'exam period'.",
    },
    {
        "id": "SEM-007",
        "topic": "Medical Leave & Attendance Condonation",
        "query": "What medical proof is needed if illness causes me to miss classes for a week?",
        "relevant_passage_id": "P-007-REL",
        "relevant_passage": (
            "Absences exceeding three consecutive instructional days due to illness require a certified physician certificate submitted "
            "to the Health Services Center within five days of recovery."
        ),
        "hard_negative_id": "P-007-HN",
        "hard_negative_passage": (
            "All incoming students must complete mandatory immunization screenings, including tuberculosis skin testing, prior to residence hall move-in."
        ),
        "soft_distractor_id": "P-007-DIST",
        "soft_distractor_passage": (
            "Campus recreational gymnasium lockers are assigned on a first-come basis each September upon presentation of a valid student card."
        ),
        "notes": "Paraphrase uses 'certified physician certificate' and 'three consecutive days'; hard negative shares medical/immunization vocabulary.",
    },
    {
        "id": "SEM-008",
        "topic": "Library Overdue Fines & Lost Materials",
        "query": "How much will I be charged if I lose a borrowed library book?",
        "relevant_passage_id": "P-008-REL",
        "relevant_passage": (
            "Unreturned or damaged library volumes incur a mandatory replacement fee equal to current retail market value plus a twenty-five dollar "
            "non-refundable administrative processing charge."
        ),
        "hard_negative_id": "P-008-HN",
        "hard_negative_passage": (
            "Standard circulating books may be renewed online up to three consecutive loan cycles unless an active recall hold has been placed "
            "by another university patron."
        ),
        "soft_distractor_id": "P-008-DIST",
        "soft_distractor_passage": (
            "Motorcycles and electric scooters must be parked exclusively in designated asphalt bays adjacent to campus perimeter gates."
        ),
        "notes": "Paraphrase uses 'unreturned library volumes' and 'replacement fee'; hard negative shares 'library books' and loan renewal rules.",
    },
    {
        "id": "SEM-009",
        "topic": "Anti-Harassment & Ragging Redressal",
        "query": "Where do I report bullying or harassment by senior students?",
        "relevant_passage_id": "P-009-REL",
        "relevant_passage": (
            "Incidents involving intimidation, hazing, or verbal harassment must be reported immediately to the 24-hour Proctorial Anti-Hazing Cell "
            "or via the confidential online reporting portal."
        ),
        "hard_negative_id": "P-009-HN",
        "hard_negative_passage": (
            "Senior undergraduate peer mentors assist incoming freshmen with academic advising, course timetable selection, and campus orientation tours."
        ),
        "soft_distractor_id": "P-009-DIST",
        "soft_distractor_passage": (
            "Textbook buyback events are conducted bi-annually at the student union bookstore during the week preceding commencement."
        ),
        "notes": "Paraphrase uses 'intimidation, hazing' and 'Proctorial Anti-Hazing Cell'; hard negative shares 'senior students' and 'peer mentors'.",
    },
    {
        "id": "SEM-010",
        "topic": "Campus Parking Decal & Regulations",
        "query": "Do undergraduate commuter students need a permit to park on campus?",
        "relevant_passage_id": "P-010-REL",
        "relevant_passage": (
            "All non-residential students operating motor vehicles on institutional property must purchase an annual commuter parking decal "
            "and park strictly within yellow-striped commuter zones."
        ),
        "hard_negative_id": "P-010-HN",
        "hard_negative_passage": (
            "Visitor parking spaces located adjacent to the Administration Building require meter payment and are limited to a maximum stay of two hours."
        ),
        "soft_distractor_id": "P-010-DIST",
        "soft_distractor_passage": (
            "Chemistry laboratory hazardous waste containers must be sealed and labeled with hazard diamond placards prior to hazardous materials pickup."
        ),
        "notes": "Paraphrase uses 'commuter parking decal' and 'yellow-striped zones'; hard negative shares parking lot and meter vocabulary.",
    },
    {
        "id": "SEM-011",
        "topic": "Merit Scholarship Renewal Criteria",
        "query": "What academic standards must I maintain to keep my university scholarship?",
        "relevant_passage_id": "P-011-REL",
        "relevant_passage": (
            "Continuing institutional merit award disbursement requires cumulative grade point maintenance of 3.40 and completion of at least "
            "twenty-eight credit hours each consecutive academic year."
        ),
        "hard_negative_id": "P-011-HN",
        "hard_negative_passage": (
            "Endowed faculty research fellowship awards require submission of an annual scholarly progress monograph and financial expenditure reconciliation."
        ),
        "soft_distractor_id": "P-011-DIST",
        "soft_distractor_passage": (
            "Campus shuttle buses operate along the outer loop every fifteen minutes between 7:00 AM and 11:00 PM on official instructional days."
        ),
        "notes": "Paraphrase uses 'merit award disbursement' and 'cumulative 3.40'; hard negative shares 'award' and 'fellowship' terminology.",
    },
    {
        "id": "SEM-012",
        "topic": "Course Add/Drop & Withdrawal Deadlines",
        "query": "When is the absolute last day to drop a class without a failing mark?",
        "relevant_passage_id": "P-012-REL",
        "relevant_passage": (
            "Course enrollments may be discontinued with a non-punitive 'W' transcript notation up through the end of the eighth instructional week."
        ),
        "hard_negative_id": "P-012-HN",
        "hard_negative_passage": (
            "Auditing a course requires instructor consent and payment of the standard non-matriculated tuition fee, with zero transcript credit earned."
        ),
        "soft_distractor_id": "P-012-DIST",
        "soft_distractor_passage": (
            "Campus postal mailboxes are cleared once daily at 3:00 PM Monday through Friday by facility services personnel."
        ),
        "notes": "Paraphrase uses 'discontinued with a non-punitive W' and 'eighth instructional week'; hard negative shares course enrollment terms.",
    },
    {
        "id": "SEM-013",
        "topic": "Internship & Placement Attendance",
        "query": "Can graduating seniors miss class lectures to attend campus job interviews?",
        "relevant_passage_id": "P-013-REL",
        "relevant_passage": (
            "Approved corporate recruitment interviews qualify for authorized absence status up to a seasonal maximum of five course lecture sessions."
        ),
        "hard_negative_id": "P-013-HN",
        "hard_negative_passage": (
            "Recruiting company representatives must register booth spaces forty-eight hours before the annual Career Fair and remit all corporate sponsorship dues."
        ),
        "soft_distractor_id": "P-013-DIST",
        "soft_distractor_passage": (
            "Intramural badminton tournament registrations close the second Friday of October at the Student Life desk."
        ),
        "notes": "Paraphrase uses 'corporate recruitment interviews' and 'authorized absence status'; hard negative shares employer recruiting terms.",
    },
    {
        "id": "SEM-014",
        "topic": "Final Exam Absence & Make-up Policy",
        "query": "What happens if an emergency causes me to miss my final examination?",
        "relevant_passage_id": "P-014-REL",
        "relevant_passage": (
            "A documented incapacitating emergency on examination day allows submission of a petition for an Incomplete 'I' grade and scheduling of a makeup exam."
        ),
        "hard_negative_id": "P-014-HN",
        "hard_negative_passage": (
            "Final examination question papers and completed student answer scripts must be archived by academic departments for five years before shredding."
        ),
        "soft_distractor_id": "P-014-DIST",
        "soft_distractor_passage": (
            "Swimming pool access requires passing an annual aquatic swim proficiency test administered by the athletic department staff."
        ),
        "notes": "Paraphrase uses 'incapacitating emergency' and 'Incomplete I grade'; hard negative shares 'final examination' and archival terms.",
    },
    {
        "id": "SEM-015",
        "topic": "Residence Hall Room Change Request",
        "query": "How do I swap rooms or get a new roommate in the hostel?",
        "relevant_passage_id": "P-015-REL",
        "relevant_passage": (
            "Dormitory reassignment requests open during the third academic week and require mutual bilateral consent forms signed by both room occupants and the Warden."
        ),
        "hard_negative_id": "P-015-HN",
        "hard_negative_passage": (
            "Annual residential building maintenance shutdown and room pest fumigation occur immediately following commencement during summer recess."
        ),
        "soft_distractor_id": "P-015-DIST",
        "soft_distractor_passage": (
            "Campus radio station broadcasts originate from the Student Activity Center studio on frequency 88.7 FM during term time."
        ),
        "notes": "Paraphrase uses 'dormitory reassignment requests' and 'bilateral consent forms'; hard negative shares hostel building terms.",
    },
]


# ---------------------------------------------------------------------------
# 2. Build Candidate Corpus from Benchmark Items
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BenchmarkPassage:
    """Passage in the pooled candidate corpus."""
    id: str
    text: str
    passage_type: str  # "relevant", "hard_negative", "soft_distractor"
    parent_topic: str


def build_pooled_corpus(items: list[dict] = SYNTHETIC_BENCHMARK_ITEMS) -> list[BenchmarkPassage]:
    """Compile all relevant passages, hard negatives, and soft distractors into a single corpus."""
    corpus: list[BenchmarkPassage] = []
    seen_ids = set()

    for item in items:
        for p_id, p_text, p_type in [
            (item["relevant_passage_id"], item["relevant_passage"], "relevant"),
            (item["hard_negative_id"], item["hard_negative_passage"], "hard_negative"),
            (item["soft_distractor_id"], item["soft_distractor_passage"], "soft_distractor"),
        ]:
            if p_id in seen_ids:
                raise ValueError(f"Duplicate passage ID detected: {p_id}")
            seen_ids.add(p_id)
            corpus.append(
                BenchmarkPassage(
                    id=p_id,
                    text=p_text,
                    passage_type=p_type,
                    parent_topic=item["topic"],
                )
            )

    return corpus


# ---------------------------------------------------------------------------
# 3. Math & Core Metric Functions
# ---------------------------------------------------------------------------

def compute_cosine_similarity(vec_a: Sequence[float], vec_b: Sequence[float]) -> float:
    """Compute cosine similarity between two float vectors.

    cos_sim(a, b) = (a . b) / (||a|| * ||b||)
    Returns a clamped value in [-1.0, 1.0]. Returns 0.0 if either norm is zero.
    """
    if len(vec_a) != len(vec_b):
        raise ValueError(f"Vector dimensions do not match: {len(vec_a)} vs {len(vec_b)}")

    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    sim = dot_product / (norm_a * norm_b)
    return max(-1.0, min(1.0, float(sim)))


def rank_passages(
    query_vec: Sequence[float],
    candidate_vecs: Sequence[Sequence[float]],
    candidate_ids: Sequence[str],
) -> list[tuple[str, float]]:
    """Rank candidate passages descending by cosine similarity.

    Ties are resolved deterministically using candidate_id ascending.
    Returns: list of (candidate_id, similarity_score).
    """
    if len(candidate_vecs) != len(candidate_ids):
        raise ValueError("Candidate vectors and IDs count mismatch.")

    scored: list[tuple[str, float]] = []
    for c_id, c_vec in zip(candidate_ids, candidate_vecs):
        sim = compute_cosine_similarity(query_vec, c_vec)
        scored.append((c_id, sim))

    # Deterministic sort: similarity descending, then candidate_id ascending for ties
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored


def compute_retrieval_ranking_metrics(
    ranked_results: Sequence[tuple[str, float]],
    target_relevant_ids: Sequence[str],
    k_list: Sequence[int] = (1, 3, 5),
) -> dict:
    """Compute standard information retrieval ranking metrics for a single query.

    Args:
        ranked_results: Ordered list of (passage_id, score) from rank_passages.
        target_relevant_ids: List of ground-truth relevant passage IDs.
        k_list: Top-K cutoffs to evaluate (e.g. 1, 3, 5).

    Returns:
        dict containing:
        - "first_relevant_rank": int (1-based rank of first matching relevant item, or None)
        - "reciprocal_rank": float (1.0 / first_relevant_rank, or 0.0 if not found)
        - "recall_at_k": dict mapping k -> float (proportion of target items in top-k)
        - "hit_at_k": dict mapping k -> int (1 if any target is in top-k, else 0)
    """
    targets = set(target_relevant_ids)
    if not targets:
        return {
            "first_relevant_rank": None,
            "reciprocal_rank": 0.0,
            "recall_at_k": {k: 0.0 for k in k_list},
            "hit_at_k": {k: 0 for k in k_list},
        }

    ranked_ids = [r[0] for r in ranked_results]

    first_rank: Optional[int] = None
    for idx, pid in enumerate(ranked_ids, start=1):
        if pid in targets:
            first_rank = idx
            break

    rr = 1.0 / first_rank if first_rank is not None else 0.0

    hit_at_k = {}
    recall_at_k = {}
    for k in k_list:
        top_k_ids = set(ranked_ids[:k])
        hits = len(top_k_ids.intersection(targets))
        hit_at_k[k] = 1 if hits > 0 else 0
        recall_at_k[k] = hits / len(targets)

    return {
        "first_relevant_rank": first_rank,
        "reciprocal_rank": round(rr, 6),
        "recall_at_k": {k: round(v, 6) for k, v in recall_at_k.items()},
        "hit_at_k": hit_at_k,
    }


# ---------------------------------------------------------------------------
# 4. Candidate Model Catalog & Audit Specifications
# ---------------------------------------------------------------------------

@dataclass
class CandidateModelSpec:
    """Specification and deployment audit for an embedding candidate model."""
    name: str
    provider: str
    dimension: int
    local_dependencies: list[str]
    credential_env_var: Optional[str]
    storage_compatibility: str
    local_resource_needs: str
    estimated_pricing_or_cost: str
    current_status: str


CANDIDATE_MODEL_CATALOG: list[CandidateModelSpec] = [
    CandidateModelSpec(
        name="deterministic-mock-sha256",
        provider="MockEmbeddingService (Built-in)",
        dimension=1536,
        local_dependencies=["None (Standard Library)"],
        credential_env_var=None,
        storage_compatibility="Fully Compatible with current Vector(1536) schema",
        local_resource_needs="Negligible CPU/RAM",
        estimated_pricing_or_cost="Free ($0.00)",
        current_status="ACTIVE (Baseline / Mock)",
    ),
    CandidateModelSpec(
        name="text-embedding-3-small",
        provider="OpenAI API",
        dimension=1536,
        local_dependencies=["openai (installed: 3.35.1)", "httpx (installed: 0.28.1)"],
        credential_env_var="OPENAI_API_KEY",
        storage_compatibility="Fully Compatible with current Vector(1536) schema",
        local_resource_needs="Negligible local CPU; requires outbound HTTPS",
        estimated_pricing_or_cost="~$0.02 / 1M tokens (Unverified / Remote)",
        current_status="BLOCKED (No OPENAI_API_KEY configured in .env)",
    ),
    CandidateModelSpec(
        name="text-embedding-004",
        provider="Google Gemini REST API",
        dimension=768,
        local_dependencies=["httpx (installed: 0.28.1)"],
        credential_env_var="GEMINI_API_KEY",
        storage_compatibility="INCOMPATIBLE with Vector(1536) (Requires schema migration to Vector(768))",
        local_resource_needs="Negligible local CPU; requires outbound HTTPS",
        estimated_pricing_or_cost="Free tier available (quota limited: 20 req/day)",
        current_status="BLOCKED (Guarded against unauthorized quota usage in Phase 5.1A)",
    ),
    CandidateModelSpec(
        name="all-MiniLM-L6-v2",
        provider="HuggingFace / Local ONNX",
        dimension=384,
        local_dependencies=["onnxruntime (installed: 1.31.0)", "tokenizers (installed: 0.23.3)"],
        credential_env_var=None,
        storage_compatibility="INCOMPATIBLE with Vector(1536) (Requires parallel table or schema migration to Vector(384))",
        local_resource_needs="~50MB RAM, low CPU inference (~5-15ms/chunk)",
        estimated_pricing_or_cost="Free (100% offline local inference)",
        current_status="ACTIVE (Local ONNX Verified in models/embeddings/all-MiniLM-L6-v2)",
    ),
    CandidateModelSpec(
        name="bge-small-en-v1.5",
        provider="BAAI / Local ONNX",
        dimension=384,
        local_dependencies=["onnxruntime (installed)", "tokenizers (installed)"],
        credential_env_var=None,
        storage_compatibility="INCOMPATIBLE with Vector(1536) (Requires schema migration to Vector(384))",
        local_resource_needs="~130MB RAM, low CPU inference",
        estimated_pricing_or_cost="Free (100% offline local inference)",
        current_status="BLOCKED (Local weights not packaged in repo; downloading requires approval)",
    ),
]


# ---------------------------------------------------------------------------
# 5. Full Benchmark Runner & Evaluation Engine
# ---------------------------------------------------------------------------

@dataclass
class ItemEvaluationResult:
    """Comprehensive evaluation record for one benchmark query."""
    item_id: str
    topic: str
    query: str
    # Cosine similarities
    sim_relevant: float
    sim_hard_negative: float
    sim_soft_distractor: float
    # Separation deltas
    delta_hard_negative: float   # sim_relevant - sim_hard_negative
    delta_soft_distractor: float # sim_relevant - sim_soft_distractor
    separated_hard_negative: bool
    separated_soft_distractor: bool
    # Corpus ranking metrics
    corpus_rank_of_relevant: Optional[int]
    reciprocal_rank: float
    hit_at_1: int
    hit_at_3: int
    hit_at_5: int


@dataclass
class RetrievalBenchmarkReport:
    """Aggregated evaluation report across all queries and corpus passages."""
    model_name: str
    dimension: int
    is_mock: bool
    total_queries: int
    corpus_size: int
    # Cosine Similarity Diagnostics
    mean_sim_relevant: float
    mean_sim_hard_negative: float
    mean_sim_soft_distractor: float
    mean_delta_hard_negative: float
    mean_delta_soft_distractor: float
    hard_negative_separation_rate: float
    soft_distractor_separation_rate: float
    # Corpus Retrieval Ranking Metrics
    mrr: float
    recall_at_1: float
    recall_at_3: float
    recall_at_5: float
    # Itemized details
    item_results: list[ItemEvaluationResult] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def evaluate_retrieval_benchmark(
    service: BaseEmbeddingService,
    model_name: str,
    is_mock: bool = False,
    items: list[dict] = SYNTHETIC_BENCHMARK_ITEMS,
) -> RetrievalBenchmarkReport:
    """Run full Phase 5.1A evaluation: pairwise diagnostics AND corpus-level retrieval ranking."""
    corpus = build_pooled_corpus(items)
    corpus_ids = [p.id for p in corpus]
    corpus_texts = [p.text for p in corpus]

    # Pre-embed corpus passages (simulate vector store)
    corpus_vecs = service.embed_texts(corpus_texts)
    vec_by_id = {pid: vec for pid, vec in zip(corpus_ids, corpus_vecs)}

    item_results: list[ItemEvaluationResult] = []

    for item in items:
        q_vec = service.embed_query(item["query"])

        rel_vec = vec_by_id[item["relevant_passage_id"]]
        hn_vec = vec_by_id[item["hard_negative_id"]]
        dist_vec = vec_by_id[item["soft_distractor_id"]]

        sim_rel = compute_cosine_similarity(q_vec, rel_vec)
        sim_hn = compute_cosine_similarity(q_vec, hn_vec)
        sim_dist = compute_cosine_similarity(q_vec, dist_vec)

        delta_hn = sim_rel - sim_hn
        delta_dist = sim_rel - sim_dist

        # Rank all corpus passages
        ranked = rank_passages(q_vec, corpus_vecs, corpus_ids)
        rank_metrics = compute_retrieval_ranking_metrics(
            ranked_results=ranked,
            target_relevant_ids=[item["relevant_passage_id"]],
            k_list=(1, 3, 5),
        )

        item_results.append(
            ItemEvaluationResult(
                item_id=item["id"],
                topic=item["topic"],
                query=item["query"],
                sim_relevant=round(sim_rel, 6),
                sim_hard_negative=round(sim_hn, 6),
                sim_soft_distractor=round(sim_dist, 6),
                delta_hard_negative=round(delta_hn, 6),
                delta_soft_distractor=round(delta_dist, 6),
                separated_hard_negative=(sim_rel > sim_hn),
                separated_soft_distractor=(sim_rel > sim_dist),
                corpus_rank_of_relevant=rank_metrics["first_relevant_rank"],
                reciprocal_rank=rank_metrics["reciprocal_rank"],
                hit_at_1=rank_metrics["hit_at_k"][1],
                hit_at_3=rank_metrics["hit_at_k"][3],
                hit_at_5=rank_metrics["hit_at_k"][5],
            )
        )

    n = len(item_results)
    mean_sim_rel = sum(r.sim_relevant for r in item_results) / n if n > 0 else 0.0
    mean_sim_hn = sum(r.sim_hard_negative for r in item_results) / n if n > 0 else 0.0
    mean_sim_dist = sum(r.sim_soft_distractor for r in item_results) / n if n > 0 else 0.0
    mean_d_hn = sum(r.delta_hard_negative for r in item_results) / n if n > 0 else 0.0
    mean_d_dist = sum(r.delta_soft_distractor for r in item_results) / n if n > 0 else 0.0
    hn_sep_rate = sum(1 for r in item_results if r.separated_hard_negative) / n if n > 0 else 0.0
    dist_sep_rate = sum(1 for r in item_results if r.separated_soft_distractor) / n if n > 0 else 0.0

    mrr = sum(r.reciprocal_rank for r in item_results) / n if n > 0 else 0.0
    r1 = sum(r.hit_at_1 for r in item_results) / n if n > 0 else 0.0
    r3 = sum(r.hit_at_3 for r in item_results) / n if n > 0 else 0.0
    r5 = sum(r.hit_at_5 for r in item_results) / n if n > 0 else 0.0

    return RetrievalBenchmarkReport(
        model_name=model_name,
        dimension=service.dimension,
        is_mock=is_mock,
        total_queries=n,
        corpus_size=len(corpus),
        mean_sim_relevant=round(mean_sim_rel, 6),
        mean_sim_hard_negative=round(mean_sim_hn, 6),
        mean_sim_soft_distractor=round(mean_sim_dist, 6),
        mean_delta_hard_negative=round(mean_d_hn, 6),
        mean_delta_soft_distractor=round(mean_d_dist, 6),
        hard_negative_separation_rate=round(hn_sep_rate, 4),
        soft_distractor_separation_rate=round(dist_sep_rate, 4),
        mrr=round(mrr, 4),
        recall_at_1=round(r1, 4),
        recall_at_3=round(r3, 4),
        recall_at_5=round(r5, 4),
        item_results=item_results,
    )


def run_phase_5_1a_audit(output_dir: Optional[str] = "eval/results") -> dict:
    """Execute Phase 5.1A strengthened semantic retrieval audit.

    1. Evaluates MockEmbeddingService empirically across the expanded 15-item / 45-passage corpus.
    2. Reports separate pairwise diagnostics (vs. hard negatives & distractors) and corpus ranking metrics.
    3. Formats candidate model feasibility catalog, noting blocked models without fabrication.
    4. Writes results to JSON in eval/results/.
    """
    logger.info("Executing Phase 5.1A Strengthened Semantic Retrieval Evaluation Audit...")

    mock_service = MockEmbeddingService(dimension=1536)
    mock_report = evaluate_retrieval_benchmark(
        service=mock_service,
        model_name="deterministic-mock-sha256",
        is_mock=True,
    )

    catalog_dicts = [asdict(spec) for spec in CANDIDATE_MODEL_CATALOG]

    audit_payload = {
        "audit_name": "Phase 5.1A: Strengthened Semantic Retrieval Evaluation & Dimension Strategy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dataset_metadata": {
            "total_queries": len(SYNTHETIC_BENCHMARK_ITEMS),
            "total_corpus_passages": len(SYNTHETIC_BENCHMARK_ITEMS) * 3,
            "relevant_passages": len(SYNTHETIC_BENCHMARK_ITEMS),
            "hard_negatives": len(SYNTHETIC_BENCHMARK_ITEMS),
            "soft_distractors": len(SYNTHETIC_BENCHMARK_ITEMS),
            "label_disclaimer": "All benchmark examples are explicitly synthetic and distinct from official institutional policies.",
        },
        "mock_embedding_evaluation": asdict(mock_report),
        "real_models_status": {
            "status": "BLOCKED",
            "reason": (
                "No real bi-encoder embedding weights are available locally in the repo/environment without "
                "downloading weights or installing packages (torch/fastembed). Remote APIs (OpenAI, Gemini) "
                "are held per safety guardrails against unapproved quota consumption or paid calls."
            ),
            "fabricated_results": None,
        },
        "candidate_model_specifications": catalog_dicts,
        "empirical_conclusions": {
            "mock_hash_limitation": (
                f"On a 45-passage corpus, MockEmbeddingService achieved Recall@1 of {mock_report.recall_at_1 * 100:.1f}%, "
                f"Recall@5 of {mock_report.recall_at_5 * 100:.1f}%, and MRR of {mock_report.mrr:.4f}. "
                f"Its mean separation delta against vocabulary-sharing hard negatives was {mock_report.mean_delta_hard_negative:.6f}, "
                f"with a hard-negative separation rate of {mock_report.hard_negative_separation_rate * 100:.1f}%. "
                "This empirically confirms that deterministic hash vectors exhibit no semantic discernment "
                "and perform indistinguishably from random chance on both ranking and pairwise tasks."
            ),
            "dimension_recommendation": (
                "Retain existing Vector(1536) database schema until an approved real semantic model is selected. "
                "OpenAI text-embedding-3-small preserves Vector(1536) directly. "
                "If an offline local model (e.g. 384-dim ONNX) or Gemini (768-dim) is preferred, "
                "implement a dual-collection or parallel table architecture in Phase 5.2 rather than a destructive in-place migration."
            ),
        },
    }

    if output_dir:
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        json_file = out_path / f"semantic_retrieval_benchmark_{ts_str}.json"
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(audit_payload, f, indent=2)
        logger.info("Saved Phase 5.1A audit JSON to: %s", json_file)

    return audit_payload


def run_phase_5_2a_audit(output_dir: Optional[str] = "eval/results") -> dict:
    """Execute Phase 5.2A comparative evaluation between Mock and Local ONNX embedding models."""
    logger.info("Executing Phase 5.2A Comparative Retrieval Benchmark...")

    # 1. Baseline Mock Evaluation
    mock_service = MockEmbeddingService(dimension=1536)
    mock_report = evaluate_retrieval_benchmark(
        service=mock_service,
        model_name="deterministic-mock-sha256",
        is_mock=True,
    )

    # 2. Local ONNX Model Evaluation
    onnx_report = None
    onnx_path = Path("models/embeddings/all-MiniLM-L6-v2/model.onnx")
    if onnx_path.exists():
        from app.services.embedding_onnx import ONNXEmbeddingService
        onnx_service = ONNXEmbeddingService()
        onnx_report = evaluate_retrieval_benchmark(
            service=onnx_service,
            model_name="all-MiniLM-L6-v2 (Local ONNX)",
            is_mock=False,
        )

    catalog_dicts = [asdict(spec) for spec in CANDIDATE_MODEL_CATALOG]

    audit_payload = {
        "audit_name": "Phase 5.2A: Local Embedding Engine and Unit Verification",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dataset_metadata": {
            "total_queries": len(SYNTHETIC_BENCHMARK_ITEMS),
            "total_corpus_passages": len(SYNTHETIC_BENCHMARK_ITEMS) * 3,
            "relevant_passages": len(SYNTHETIC_BENCHMARK_ITEMS),
            "hard_negatives": len(SYNTHETIC_BENCHMARK_ITEMS),
            "soft_distractors": len(SYNTHETIC_BENCHMARK_ITEMS),
            "label_disclaimer": "All benchmark examples are explicitly synthetic and distinct from official institutional policies.",
        },
        "baseline_mock_evaluation": asdict(mock_report),
        "local_onnx_evaluation": asdict(onnx_report) if onnx_report else None,
        "candidate_model_specifications": catalog_dicts,
        "comparative_summary": {
            "mock_mrr": mock_report.mrr,
            "onnx_mrr": onnx_report.mrr if onnx_report else None,
            "mock_recall_at_5": mock_report.recall_at_5,
            "onnx_recall_at_5": onnx_report.recall_at_5 if onnx_report else None,
            "mock_hard_neg_sep_rate": mock_report.hard_negative_separation_rate,
            "onnx_hard_neg_sep_rate": onnx_report.hard_negative_separation_rate if onnx_report else None,
        },
    }

    if output_dir:
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        json_file = out_path / f"semantic_retrieval_benchmark_phase5_2a_{ts_str}.json"
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(audit_payload, f, indent=2)
        logger.info("Saved Phase 5.2A audit JSON to: %s", json_file)

    return audit_payload


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = run_phase_5_2a_audit()
    mock_eval = results["baseline_mock_evaluation"]
    onnx_eval = results["local_onnx_evaluation"]

    print("\n" + "=" * 78)
    print(" PHASE 5.2A: LOCAL ONNX VS MOCK HASH RETRIEVAL BENCHMARK COMPARISON")
    print("=" * 78)
    print(f"{'Metric':<35} | {'Mock Hash (1536-dim)':<18} | {'ONNX MiniLM (384-dim)':<20}")
    print("-" * 78)
    print(f"{'Recall@1 (Hit@1)':<35} | {mock_eval['recall_at_1'] * 100:>16.1f}% | {onnx_eval['recall_at_1'] * 100:>18.1f}%")
    print(f"{'Recall@3 (Hit@3)':<35} | {mock_eval['recall_at_3'] * 100:>16.1f}% | {onnx_eval['recall_at_3'] * 100:>18.1f}%")
    print(f"{'Recall@5 (Hit@5)':<35} | {mock_eval['recall_at_5'] * 100:>16.1f}% | {onnx_eval['recall_at_5'] * 100:>18.1f}%")
    print(f"{'Mean Reciprocal Rank (MRR)':<35} | {mock_eval['mrr']:>17.4f} | {onnx_eval['mrr']:>19.4f}")
    print(f"{'Hard Negative Sep. Rate':<35} | {mock_eval['hard_negative_separation_rate'] * 100:>16.1f}% | {onnx_eval['hard_negative_separation_rate'] * 100:>18.1f}%")
    print(f"{'Soft Distractor Sep. Rate':<35} | {mock_eval['soft_distractor_separation_rate'] * 100:>16.1f}% | {onnx_eval['soft_distractor_separation_rate'] * 100:>18.1f}%")
    print(f"{'Mean Sim Relevant':<35} | {mock_eval['mean_sim_relevant']:>+17.4f} | {onnx_eval['mean_sim_relevant']:>+19.4f}")
    print(f"{'Mean Sim Hard Negative':<35} | {mock_eval['mean_sim_hard_negative']:>+17.4f} | {onnx_eval['mean_sim_hard_negative']:>+19.4f}")
    print(f"{'Mean Sim Soft Distractor':<35} | {mock_eval['mean_sim_soft_distractor']:>+17.4f} | {onnx_eval['mean_sim_soft_distractor']:>+19.4f}")
    print(f"{'Mean Delta vs Hard Negative':<35} | {mock_eval['mean_delta_hard_negative']:>+17.4f} | {onnx_eval['mean_delta_hard_negative']:>+19.4f}")
    print("=" * 78)
