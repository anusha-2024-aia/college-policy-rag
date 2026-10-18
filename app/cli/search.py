"""Inspection CLI for hybrid retrieval stages (vector, keyword, fused, reranked)."""

import argparse
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
from app.core.database import SessionLocal
from app.services.embedding import get_embedding_service
from app.services.reranker import get_reranker_service
from app.services.retrieval import HybridRetrievalService


def parse_args() -> argparse.Namespace:
    """Parse search CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Inspect hybrid retrieval results across Vector, Keyword, Fused (RRF), and Reranked stages."
    )
    parser.add_argument(
        "query",
        type=str,
        help="Search query string",
    )
    parser.add_argument(
        "--stage",
        type=str,
        choices=["all", "vector", "keyword", "fused", "reranked"],
        default="all",
        help="Retrieval stage to display (default: all)",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=settings.RETRIEVAL_K,
        help=f"Initial candidates count for vector and keyword search (default: {settings.RETRIEVAL_K})",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=settings.RERANKER_TOP_N,
        help=f"Final reranked results count (default: {settings.RERANKER_TOP_N})",
    )
    parser.add_argument(
        "--k-rrf",
        type=int,
        default=settings.RRF_K,
        help=f"Reciprocal Rank Fusion constant (default: {settings.RRF_K})",
    )
    parser.add_argument(
        "--role",
        type=str,
        choices=["student", "faculty", "admin"],
        default="student",
        help="Simulated user access role (student, faculty, or admin; default: student)",
    )
    parser.add_argument(
        "--mock-embeddings",
        action="store_true",
        help="Force use of deterministic mock embeddings",
    )
    parser.add_argument(
        "--mock-reranker",
        action="store_true",
        help="Force use of deterministic mock reranker",
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        help="Optional database URL override (e.g., sqlite:///data/local.db)",
    )
    return parser.parse_args()


def truncate(text: str, max_len: int = 90) -> str:
    """Format single-line text preview."""
    clean = " ".join(text.split())
    return clean[:max_len] + "..." if len(clean) > max_len else clean


def main() -> None:
    """Execute search query and display multi-stage diagnostics."""
    args = parse_args()

    # Database session setup
    if args.db_url:
        custom_engine = create_engine(args.db_url)
        CustomSession = sessionmaker(bind=custom_engine)
        db = CustomSession()
    else:
        try:
            db = SessionLocal()
        except Exception as exc:
            print(f"[ERROR] Could not connect to database: {exc}")
            sys.exit(1)

    embedding_svc = get_embedding_service(force_mock=args.mock_embeddings)
    reranker_svc = get_reranker_service(force_mock=args.mock_reranker)

    retrieval_svc = HybridRetrievalService(
        db_session=db,
        embedding_service=embedding_svc,
        reranker_service=reranker_svc,
        rrf_k=args.k_rrf,
    )

    try:
        response = retrieval_svc.retrieve(
            query=args.query,
            top_k=args.k,
            top_n=args.top_n,
            k_rrf=args.k_rrf,
            role=args.role,
        )
    finally:
        db.close()

    print("=" * 90)
    print(" Document RAG - Hybrid Retrieval Inspection")
    print("=" * 90)
    print(f" Query:        '{response.query}'")
    print(f" User Role:    {args.role.upper()} (allowed_roles filter applied in SQL)")
    print(f" Initial K:    {args.k}")
    print(f" RRF Constant: {args.k_rrf}")
    print(f" Final Top N:  {args.top_n}")
    print("=" * 90)

    # 1. Vector Search Results
    if args.stage in ("all", "vector"):
        print("\n[STAGE 1: Dense Vector Search (pgvector Cosine Similarity)]")
        print(f" Timing: {response.diagnostics.timings_ms.get('vector_search_ms', 0):.2f} ms | Total Candidates: {len(response.vector_results)}")
        print("-" * 90)
        if not response.vector_results:
            print("  No vector search matches found.")
        else:
            print(f" {'Rank':<5} | {'Score':<8} | {'File Name':<30} | {'Page':<5} | {'Passage Preview'}")
            print("-" * 90)
            for c in response.vector_results[:args.top_n]:
                print(f" #{c.rank:<4} | {c.score:<8.4f} | {c.file_name:<30} | p.{c.page_number:<3} | {truncate(c.text)}")

    # 2. Keyword Search Results
    if args.stage in ("all", "keyword"):
        print("\n[STAGE 2: Sparse Keyword Search (PostgreSQL ts_rank / BM25)]")
        print(f" Timing: {response.diagnostics.timings_ms.get('keyword_search_ms', 0):.2f} ms | Total Matches: {len(response.keyword_results)}")
        print("-" * 90)
        if not response.keyword_results:
            print("  No keyword search matches found.")
        else:
            print(f" {'Rank':<5} | {'Score':<8} | {'File Name':<30} | {'Page':<5} | {'Passage Preview'}")
            print("-" * 90)
            for c in response.keyword_results[:args.top_n]:
                print(f" #{c.rank:<4} | {c.score:<8.4f} | {c.file_name:<30} | p.{c.page_number:<3} | {truncate(c.text)}")

    # 3. RRF Fused Results
    if args.stage in ("all", "fused"):
        print(f"\n[STAGE 3: Reciprocal Rank Fusion (k_rrf={args.k_rrf})]")
        print(f" Timing: {response.diagnostics.timings_ms.get('rrf_fusion_ms', 0):.2f} ms | Fused Candidates: {len(response.fused_results)}")
        print("-" * 90)
        if not response.fused_results:
            print("  No fused candidates available.")
        else:
            print(f" {'Rank':<5} | {'RRF Score':<10} | {'Vec/Key Ranks':<14} | {'File Name':<26} | {'Page':<5} | {'Preview'}")
            print("-" * 90)
            for c in response.fused_results[:args.top_n]:
                ranks_str = f"v:{c.vector_rank or '-'} / k:{c.keyword_rank or '-'}"
                print(f" #{c.fused_rank:<4} | {c.rrf_score:<10.6f} | {ranks_str:<14} | {c.file_name:<26} | p.{c.page_number:<3} | {truncate(c.text, 50)}")

    # 4. Reranked Results
    if args.stage in ("all", "reranked"):
        print(f"\n[STAGE 4: Final Reranked Passages (Top {args.top_n})]")
        print(f" Timing: {response.diagnostics.timings_ms.get('reranking_ms', 0):.2f} ms | Final Returned: {len(response.reranked_results)}")
        print("-" * 90)
        if not response.reranked_results:
            print("  No reranked passages returned.")
        else:
            print(f" {'Rank':<5} | {'Score':<8} | {'File Name':<30} | {'Page':<5} | {'Passage Preview'}")
            print("-" * 90)
            for c in response.reranked_results:
                print(f" #{c.final_rank:<4} | {c.rerank_score:<8.4f} | {c.file_name:<30} | p.{c.page_number:<3} | {truncate(c.text)}")

    print("\n" + "=" * 90)
    print(f" Total Hybrid Retrieval Time: {response.diagnostics.timings_ms.get('total_retrieval_ms', 0):.2f} ms")
    print("=" * 90)


if __name__ == "__main__":
    main()
