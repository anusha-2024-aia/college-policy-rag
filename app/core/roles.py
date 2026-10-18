"""Role-Based Access Control (RBAC) definitions, permitted roles, and SQL filter builders."""

from enum import Enum
from typing import Any
from sqlalchemy import or_, cast, func, select
from sqlalchemy.dialects.postgresql import JSONB

# Permitted roles in the Document RAG System
PERMITTED_ROLES: set[str] = {"student", "faculty", "admin"}


class UserRole(str, Enum):
    """Permitted user roles for document access authorization."""

    STUDENT = "student"
    FACULTY = "faculty"
    ADMIN = "admin"


class InvalidRoleError(ValueError):
    """Raised when an unrecognized or unauthorized role is supplied."""
    pass


def validate_role(role: str) -> str:
    """Validate and normalize user access role.

    Args:
        role: Raw role string (case-insensitive).

    Returns:
        Normalized lowercase role string.

    Raises:
        InvalidRoleError: If role is not in PERMITTED_ROLES.
    """
    if not role or not isinstance(role, str):
        raise InvalidRoleError(f"Role must be a non-empty string. Permitted roles are: {sorted(PERMITTED_ROLES)}")

    clean_role = role.strip().lower()
    if clean_role not in PERMITTED_ROLES:
        raise InvalidRoleError(
            f"Invalid role '{role}'. Permitted roles are: {sorted(PERMITTED_ROLES)}"
        )
    return clean_role


def build_role_filter(doc_model: Any, role: str, dialect_name: str = "sqlite"):
    """Construct an SQL filter expression that strictly restricts queries to documents accessible by role.

    Enforces that the document's allowed_roles array contains the specific role or the wildcard 'all'.

    Args:
        doc_model: SQLAlchemy Document ORM class.
        role: Validated role string ('student', 'faculty', or 'admin').
        dialect_name: Dialect of the current database engine ('postgresql' or 'sqlite').

    Returns:
        SQLAlchemy BinaryExpression / ClauseElement for query.filter().
    """
    clean_role = validate_role(role)

    if dialect_name == "postgresql":
        # Native PostgreSQL JSONB containment operator (@>)
        return or_(
            cast(doc_model.allowed_roles, JSONB).op("@>")(f'["{clean_role}"]'),
            cast(doc_model.allowed_roles, JSONB).op("@>")(f'["all"]'),
        )
    else:
        # SQLite json_each table-valued query for in-memory testing
        je = func.json_each(doc_model.allowed_roles).table_valued("value")
        return select(1).select_from(je).where(je.c.value.in_([clean_role, "all"])).exists()
