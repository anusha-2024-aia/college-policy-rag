"""PostgreSQL Row-Level Security (RLS) helpers and session context management.

Implements Layer 2 (L2) of the Defence-in-Depth security model:
1. Application connects as a non-owner role (kvit_app_user) without BYPASSRLS.
2. Inside each database transaction, executes `SET LOCAL app.current_role = :role`.
3. If app.current_role is unset or invalid, PostgreSQL RLS policies evaluate to FALSE/NULL,
   returning exactly 0 rows from chunks and documents.
"""

import logging
from pathlib import Path
from typing import Optional
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.roles import validate_role

logger = logging.getLogger(__name__)

RLS_SQL_PATH = Path("scripts/setup_postgres_rls.sql")


def set_session_role(session: Session, role: Optional[str]) -> None:
    """Set the transaction-scoped 'app.current_role' configuration parameter.

    Uses `SET LOCAL` so the setting automatically expires upon transaction commit or rollback,
    preventing any connection-pool role leakage.

    Args:
        session: Active SQLAlchemy Session.
        role: Verified user role string ('student', 'faculty', 'admin') or None.
    """
    if not settings.L2_RLS_ENABLED or not settings.SECURITY_ENFORCEMENT_ENABLED:
        return

    # Check database dialect
    bind = session.bind
    if bind is not None and bind.dialect.name == "postgresql":
        if role:
            clean_role = validate_role(role)
            session.execute(
                text("SELECT set_config('app.current_role', :role, true)"),
                {"role": clean_role},
            )
            logger.debug("Configured PostgreSQL transaction parameter app.current_role = '%s'", clean_role)
        else:
            session.execute(text("SELECT set_config('app.current_role', '', true)"))
            logger.debug("Reset PostgreSQL transaction parameter app.current_role to empty")


def evaluate_rls_policy(current_role_setting: Optional[str], allowed_roles: list[str]) -> bool:
    """Simulate PostgreSQL RLS policy logic in Python.

    Policy logic:
    `allowed_roles::jsonb ? current_setting('app.current_role', true) OR allowed_roles::jsonb ? 'all'`

    If current_role_setting is None or unset, current_setting('app.current_role', true) returns NULL,
    causing JSONB containment to fail and returning False (0 rows visible).
    """
    if not current_role_setting:
        return False

    clean = current_role_setting.strip().lower()
    normalized_allowed = [str(r).strip().lower() for r in (allowed_roles or [])]

    return clean in normalized_allowed or "all" in normalized_allowed

