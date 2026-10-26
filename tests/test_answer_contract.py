"""Tests for Phase 3: Answer Contract and Citation Verification."""

import json
import pytest
from app.core.database import SessionLocal
from app.services.retrieval import HybridRetrievalService
from app.services.embedding import MockEmbeddingService
from app.services.reranker import FlashRankRerankerService
from app.services.llm import MockLLMService
from app.services.qa import QAService
from app.schemas.qa import AskRequest, AnswerContract, PassageEvidence


@pytest.fixture
def qa_service():
    """Build QAService wired to test SQLite database with MockEmbeddingService and FlashRank."""
    db = SessionLocal()
    retrieval_service = HybridRetrievalService(
        db_session=db,
        embedding_service=MockEmbeddingService(),
        reranker_service=FlashRankRerankerService(),
    )
    llm_service = MockLLMService()
    return QAService(retrieval_service=retrieval_service, llm_service=llm_service)


def test_invalid_citations_dropped_and_renumbered(qa_service):
    """DONE WHEN Criterion 1: Verify invalid citations ([99], [42]) are dropped and valid ones renumbered sequentially."""
    hallucinating_llm = MockLLMService(
        custom_response=(
            "Under the current regulations, students must report 30 minutes early [1]. "
            "Fabricated rumours mention unverified rules [99] and non-existent regulations [42]."
        )
    )
    qa_custom = QAService(retrieval_service=qa_service.retrieval_service, llm_service=hallucinating_llm)

    request = AskRequest(question="How early must I report to the exam hall", role="student")
    response = qa_custom.answer(request)

    assert not response.abstained
    # Valid passage [1] survives; hallucinated [99] and [42] must be dropped from citations list
    citation_indices = [c.index for c in response.citations]
    assert 1 in citation_indices
    assert 99 not in citation_indices
    assert 42 not in citation_indices
    assert len(response.citations) == 1

    # Citation must point to real retrieved document and page
    cit = response.citations[0]
    assert cit.file_name == "examination_assessment_rules_2023.pdf"
    assert cit.page_number >= 1
    assert "30 minutes" in cit.snippet


def test_snippet_extraction_rejects_page_headers_and_banners():
    """DONE WHEN Criterion: Snippet must be the best-matching sentence, not a page header or synthetic banner."""
    noisy_passage_text = (
        "PUBLIC (synthetic)\n\n"
        "Circular No. KVIT/ACAD/2025/014: Amendment to Examination Rules\n\n"
        "Official amendment\n"
        "Page 1 of 3\n\n"
        "- Clause 4.2. In addition, a student must secure at least 21 marks out of 60 in the ESE."
    )
    answer_context = "The minimum mark required in the ESE is 21 marks out of 60."

    best = QAService._best_sentence(noisy_passage_text, answer_context)
    assert "PUBLIC (synthetic)" not in best
    assert "Page 1 of 3" not in best
    assert "Circular No." not in best
    assert "21 marks out of 60" in best


def test_abstain_path_unanswerable_and_low_confidence(qa_service):
    """DONE WHEN Criterion 2: Abstain when evidence is below threshold; canonical identical wording."""
    # Test 1: Out of corpus concept
    req_unanswerable = AskRequest(question="What is the warp drive engine protocol?", role="student")
    res_unanswerable = qa_service.answer(req_unanswerable)

    assert res_unanswerable.abstained is True
    assert res_unanswerable.answer == QAService.ABSTENTION_SENTENCE
    assert res_unanswerable.citations == []
    assert res_unanswerable.authoritative_sources == []
    assert res_unanswerable.historical_sources == []
    assert res_unanswerable.change_cards == []
    assert res_unanswerable.conflict is False

    # Test 2: Artificial high threshold triggers abstention with identical phrasing
    req_threshold = AskRequest(
        question="minimum attendance",
        role="student",
        abstention_threshold=0.99999,
    )
    res_threshold = qa_service.answer(req_threshold)

    assert res_threshold.abstained is True
    assert res_threshold.answer == QAService.ABSTENTION_SENTENCE
    assert res_threshold.citations == []


def test_conflict_path_1_active_supersession(qa_service):
    """DONE WHEN Criterion 3: Active conflict path leads with current rule, supersedes older rule, emits change cards."""
    request = AskRequest(question="minimum attendance", role="student")
    response = qa_service.answer(request)

    assert not response.abstained
    assert "75%" in response.answer
    assert response.conflict is True
    assert response.has_policy_conflict is True
    assert len(response.change_cards) > 0

    # Answer leads with current rule and identifies older rule as superseded / no longer in force
    answer_lower = response.answer.lower()
    assert "current policy" in answer_lower or "75%" in answer_lower
    assert "supersedes" in answer_lower or "previous policy" in answer_lower or "no longer in force" in answer_lower

    # Authoritative sources point to 2025; historical sources point to 2023
    assert len(response.authoritative_sources) >= 1
    assert 1 in response.authoritative_sources


def test_conflict_path_2_unchanged_clause(qa_service):
    """DONE WHEN Criterion 4: Unchanged clause path returns factual answer with conflict=False and empty change cards."""
    request = AskRequest(question="How early must I report to the exam hall", role="student")
    response = qa_service.answer(request)

    assert not response.abstained
    assert "30 minutes" in response.answer
    assert response.conflict is False
    assert response.has_policy_conflict is False
    assert len(response.change_cards) == 0
    assert response.historical_sources == []


def test_answer_contract_pydantic_schema_validation():
    """Verify AnswerContract Pydantic schema validation and JSON serialization/deserialization."""
    raw_json = json.dumps({
        "answer": "The minimum attendance requirement is 75% [1]. Older requirement was 80% [2].",
        "authoritative_sources": [1],
        "historical_sources": [2],
        "conflict": True,
        "change_cards": [],
        "as_of": "2025-07-01",
        "abstain": False,
        "abstain_reason": None,
    })

    contract = AnswerContract.model_validate_json(raw_json)
    assert contract.answer.startswith("The minimum attendance")
    assert contract.authoritative_sources == [1]
    assert contract.historical_sources == [2]
    assert contract.conflict is True
    assert contract.as_of == "2025-07-01"
    assert contract.abstain is False

    # Test markdown wrapper resilience in parse_answer_contract
    wrapped_json = f"```json\n{raw_json}\n```"
    parsed = QAService.parse_answer_contract(wrapped_json)
    assert parsed.conflict is True
    assert parsed.authoritative_sources == [1]

