"""User authentication, seeding, and administrative role management services."""

from __future__ import annotations

import hashlib
import logging
from typing import Optional
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.audit import AccessAudit
from app.core.security import hash_password, verify_password
from app.core.roles import validate_role, InvalidRoleError

logger = logging.getLogger(__name__)

# Pre-seeded demo credentials for the three required personas
DEMO_ACCOUNTS = [
    {
        "username": "student",
        "password": "StudentPass2026!",
        "role": "student",
    },
    {
        "username": "faculty",
        "password": "FacultyPass2026!",
        "role": "faculty",
    },
    {
        "username": "admin",
        "password": "AdminPass2026!",
        "role": "admin",
    },
]


def seed_default_users(db: Session) -> list[User]:
    """Idempotently seed the three demo accounts if they do not exist."""
    seeded: list[User] = []
    for account in DEMO_ACCOUNTS:
        existing = db.query(User).filter_by(username=account["username"]).first()
        if not existing:
            user = User(
                username=account["username"],
                password_hash=hash_password(account["password"]),
                role=account["role"],
                is_active=True,
            )
            db.add(user)
            seeded.append(user)
            logger.info("Seeded demo user account '%s' (role: %s)", account["username"], account["role"])
        else:
            seeded.append(existing)
    db.commit()
    return seeded


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    """Authenticate user with username and plaintext password."""
    if not username or not password:
        return None

    user = db.query(User).filter_by(username=username.strip().lower()).first()
    if not user:
        return None

    if not user.is_active:
        logger.warning("Authentication attempt for inactive user '%s'", username)
        return None

    if not verify_password(password, user.password_hash):
        logger.warning("Invalid password attempt for user '%s'", username)
        return None

    return user


def update_user_role(
    db: Session,
    admin_role: str,
    target_username_or_id: str,
    new_role: str,
) -> User:
    """Update user role with strict administrative authorization and audit logging."""
    if admin_role != "admin":
        raise PermissionError("Only administrative callers are authorized to modify user roles.")

    clean_new_role = validate_role(new_role)

    user = (
        db.query(User).filter(
            (User.id == target_username_or_id) | (User.username == target_username_or_id.lower())
        ).first()
    )
    if not user:
        raise ValueError(f"User '{target_username_or_id}' not found.")

    old_role = user.role
    user.role = clean_new_role

    # Audit log the role modification
    event_payload = f"role_change:{user.id}:{old_role}->{clean_new_role}"
    audit_hash = hashlib.sha256(event_payload.encode("utf-8")).hexdigest()

    audit_entry = AccessAudit(
        role="admin",
        query_hash=audit_hash,
        decision=f"role_changed:{old_role}->{clean_new_role}",
        blocked_candidates=0,
    )
    db.add(audit_entry)
    db.commit()
    db.refresh(user)

    logger.info("Admin changed user '%s' role from '%s' to '%s' (audit_id: %s)", user.username, old_role, clean_new_role, audit_entry.id)
    return user

