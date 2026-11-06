"""Policy change intelligence and version diff routes (Phase 7)."""

from __future__ import annotations

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_role
from app.core.rls import set_session_role
from app.schemas.qa import PolicyDiffResponse
from app.services.clause_diff import ClauseDiffService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/policies", tags=["Policies"])


@router.get(
    "/{lineage_id}/diff",
    response_model=PolicyDiffResponse,
    status_code=status.HTTP_200_OK,
    summary="Compute Clause-Level Policy Diff",
    description=(
        "Returns deterministic change cards and clause-level deltas across versions "
        "for the specified policy lineage. Strictly enforces role authorization."
    ),
)
def get_policy_diff(
    lineage_id: str,
    from_date: Optional[str] = Query(None, alias="from", description="Target start date (YYYY-MM-DD)"),
    to_date: Optional[str] = Query(None, alias="to", description="Target end date (YYYY-MM-DD)"),
    verified_role: str = Depends(get_current_role),
    db: Session = Depends(get_db),
) -> PolicyDiffResponse:
    """Retrieve clause-level differences across document versions with role governance."""
    set_session_role(db, verified_role)
    diff_service = ClauseDiffService(db)

    lineage = diff_service.get_lineage_by_identifier(lineage_id)
    if not lineage:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Policy lineage '{lineage_id}' not found.",
        )

    # 4-Layer RBAC governance check
    old_doc = lineage.old_document
    new_doc = lineage.new_document

    clean_role = verified_role.lower().strip()
    old_roles = [str(r).lower() for r in (old_doc.allowed_roles if old_doc else [])]
    new_roles = [str(r).lower() for r in (new_doc.allowed_roles if new_doc else [])]

    # Verify authorization
    if old_roles and clean_role not in old_roles and "all" not in old_roles:
        logger.warning("Role '%s' denied access to predecessor in lineage '%s'", clean_role, lineage_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: Role '{verified_role}' is not authorized to inspect this policy lineage.",
        )

    if new_roles and clean_role not in new_roles and "all" not in new_roles:
        logger.warning("Role '%s' denied access to successor in lineage '%s'", clean_role, lineage_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: Role '{verified_role}' is not authorized to inspect this policy lineage.",
        )

    try:
        diff_result = diff_service.diff_lineage(lineage, from_date=from_date, to_date=to_date)
        return diff_result
    except Exception as exc:
        logger.error("Failed to compute policy diff for lineage '%s': %s", lineage_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error computing policy diff: {str(exc)}",
        )

