"""Authentication API routes for credential verification, JWT issuance, and demo accounts."""

import logging
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.auth import create_access_token, get_current_role
from app.core.user_service import authenticate_user, DEMO_ACCOUNTS
from app.core.rate_limiter import login_rate_limiter
from app.schemas.auth import (
    LoginRequest,
    TokenResponse,
    DemoAccountsResponse,
    DemoAccountInfo,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate with Username and Password",
    description=(
        "Authenticates against server-side user credentials and issues a cryptographically signed "
        "HMAC-SHA256 JWT access token. The role is derived strictly from the server-side user record, "
        "never from client-supplied request bodies or headers."
    ),
)
def login(
    request: Request,
    payload: LoginRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    """Authenticate credentials and issue role-governed JWT access token."""
    # 1. Enforce rate limiting
    login_rate_limiter.check(request)

    # 2. Authenticate against server-side user record
    user = authenticate_user(db, payload.username, payload.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 3. Issue cryptographically signed token with server-derived role
    token = create_access_token(
        role=user.role,
        subject=user.username,
        expires_in_seconds=settings.JWT_EXPIRE_SECONDS,
    )

    logger.info("User '%s' authenticated successfully (role: '%s')", user.username, user.role)

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        role=user.role,
        expires_in=settings.JWT_EXPIRE_SECONDS,
        username=user.username,
        user_id=user.id,
    )


@router.get(
    "/demo-accounts",
    response_model=DemoAccountsResponse,
    status_code=status.HTTP_200_OK,
    summary="List Pre-Seeded Demo Accounts (DEMO_MODE only)",
    description=(
        "Returns the public demo credentials when DEMO_MODE=true so evaluators and recruiters "
        "can log in across Student, Faculty, and Admin personas without a passwordless role picker."
    ),
)
def get_demo_accounts() -> DemoAccountsResponse:
    """Return demo credentials when DEMO_MODE is active."""
    if not settings.DEMO_MODE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo accounts discovery is disabled when DEMO_MODE=false.",
        )

    account_infos = [
        DemoAccountInfo(
            username=acc["username"],
            password=acc["password"],
            role=acc["role"],
            description=f"Standard persona for {acc['role'].capitalize()} evaluation.",
        )
        for acc in DEMO_ACCOUNTS
    ]

    return DemoAccountsResponse(
        demo_mode=True,
        notice="DEMO MODE ACTIVE: Use these credentials with POST /auth/login. Zero-password role selection is prohibited.",
        accounts=account_infos,
    )


@router.get(
    "/me",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Get Authenticated Caller Identity",
    description="Returns verified role and claims from bearer token.",
)
def get_me(verified_role: str = Depends(get_current_role)) -> dict:
    """Return verified identity from active JWT."""
    return {
        "status": "authenticated",
        "role": verified_role,
    }


@router.post(
    "/demo-login",
    status_code=status.HTTP_400_BAD_REQUEST,
    summary="Deprecated Passwordless Demo Login",
    description="Prohibited in Phase 2. All authentication requires POST /auth/login with valid credentials.",
)
def deprecated_demo_login():
    """Explicitly reject passwordless role spoofing."""
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Passwordless role selection is prohibited. Please authenticate using POST /auth/login with valid credentials.",
    )
