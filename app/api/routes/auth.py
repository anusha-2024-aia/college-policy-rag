"""Authentication API routes for role tokens and demo login."""

import logging
from fastapi import APIRouter, HTTPException, status
from app.core.config import settings
from app.core.auth import create_access_token
from app.core.roles import validate_role, InvalidRoleError
from app.schemas.auth import DemoLoginRequest, TokenResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/demo-login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Issue Role-Governed Demo JWT Token",
    description=(
        "Returns a cryptographically signed HMAC-SHA256 JWT access token for testing role-governed "
        "document retrieval and version-aware queries.\n\n"
        "**SECURITY ARCHITECTURE & HONEST DEMO LIMITATION**:\n"
        "This demo login endpoint provides zero-password role switching strictly to evaluate and "
        "benchmark role governance across Student, Faculty, and Admin personas.\n"
        "In a real-world enterprise production deployment, this endpoint would NOT exist. It would "
        "be replaced by an institutional Single Sign-On (SSO) gateway using OAuth2 / OpenID Connect "
        "(OIDC) protocols (e.g. Okta, Microsoft Entra ID / Azure AD, Keycloak, or Shibboleth/SAML) "
        "with multi-factor authentication (MFA) and verified directory claims."
    ),
)
def demo_login(payload: DemoLoginRequest) -> TokenResponse:
    """Issue a signed JWT access token for the requested role."""
    try:
        clean_role = validate_role(payload.role)
    except InvalidRoleError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    token = create_access_token(
        role=clean_role,
        expires_in_seconds=settings.JWT_EXPIRE_SECONDS,
    )

    logger.info("Issued demo JWT token for role '%s' (TTL: %d seconds)", clean_role, settings.JWT_EXPIRE_SECONDS)

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        role=clean_role,
        expires_in=settings.JWT_EXPIRE_SECONDS,
    )

