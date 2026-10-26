"""Pydantic schemas for Demo Authentication and JWT Token Exchange."""

from pydantic import BaseModel, Field, field_validator
from app.core.roles import PERMITTED_ROLES, validate_role


class DemoLoginRequest(BaseModel):
    """Payload for POST /auth/demo-login."""

    role: str = Field(
        default="student",
        description="Target user role for demo token issuance ('student', 'faculty', 'admin')",
    )

    @field_validator("role")
    @classmethod
    def validate_requested_role(cls, v: str) -> str:
        clean = (v or "").strip().lower()
        if clean not in PERMITTED_ROLES:
            raise ValueError(f"Invalid role '{v}'. Permitted roles are: {sorted(PERMITTED_ROLES)}")
        return clean


class TokenResponse(BaseModel):
    """Bearer JWT token issuance response."""

    access_token: str = Field(..., description="Signed HMAC-SHA256 JWT access token")
    token_type: str = Field(default="bearer", description="Token type identifier")
    role: str = Field(..., description="Authorized role embedded in verified token")
    expires_in: int = Field(..., description="Token validity duration in seconds")

