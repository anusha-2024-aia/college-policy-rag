"""Pydantic schemas for Authentication, Login, and Role-Governed Access."""

from typing import Optional
from pydantic import BaseModel, Field, field_validator
from app.core.roles import PERMITTED_ROLES


class LoginRequest(BaseModel):
    """Payload for POST /auth/login."""

    username: str = Field(..., min_length=1, description="Registered username (e.g. 'student', 'faculty', 'admin')")
    password: str = Field(..., min_length=1, description="User plaintext password")


class TokenResponse(BaseModel):
    """Bearer JWT token issuance response."""

    access_token: str = Field(..., description="Cryptographically signed HMAC-SHA256 JWT access token")
    token_type: str = Field(default="bearer", description="Token type identifier")
    role: str = Field(..., description="Server-verified role embedded in JWT")
    expires_in: int = Field(..., description="Token validity duration in seconds")
    username: Optional[str] = Field(default=None, description="Authenticated username")
    user_id: Optional[str] = Field(default=None, description="Authenticated user UUID")


class DemoAccountInfo(BaseModel):
    """Pre-seeded demo credentials for recruiter and evaluation inspection."""

    username: str
    password: str
    role: str
    description: str


class DemoAccountsResponse(BaseModel):
    """Response schema for GET /auth/demo-accounts in DEMO_MODE."""

    demo_mode: bool
    notice: str
    accounts: list[DemoAccountInfo]


class RoleUpdateRequest(BaseModel):
    """Payload for administrative role update: POST /admin/users/{user_id}/role."""

    role: str = Field(..., description="New role for target user ('student', 'faculty', 'admin')")

    @field_validator("role")
    @classmethod
    def validate_new_role(cls, v: str) -> str:
        clean = (v or "").strip().lower()
        if clean not in PERMITTED_ROLES:
            raise ValueError(f"Invalid role '{v}'. Permitted roles are: {sorted(PERMITTED_ROLES)}")
        return clean


class UserResponse(BaseModel):
    """User profile response schema."""

    id: str
    username: str
    role: str
    is_active: bool
    created_at: Optional[str] = None
