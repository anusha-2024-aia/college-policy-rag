"""JWT Token Generation, Cryptographic Verification, and Role Extraction.

Enforces Phase 2 Hardened Identity Specification:
1. User role is derived EXCLUSIVELY from verified cryptographic JWT tokens issued from server-side user records.
2. Missing, empty, tampered, expired, wrong audience, or alg=none tokens strictly yield HTTP 401 Unauthorized.
3. Tokens include pinned algorithm (HS256), short TTL (exp), unique identifier (jti), issuer (iss), audience (aud), and subject (sub).
4. Uses Python standard library (hmac, hashlib, base64, json, time, uuid) with zero external dependencies.
"""

from __future__ import annotations

import base64
import hmac
import hashlib
import json
import logging
import time
import uuid
from typing import Any, Optional
from fastapi import Header, HTTPException, status
from app.core.config import settings
from app.core.roles import PERMITTED_ROLES, validate_role, InvalidRoleError

logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Raised when JWT verification fails due to expiration, signature mismatch, or tampering."""
    pass


def _base64url_encode(data: bytes) -> str:
    """Encode bytes into base64url string without trailing padding."""
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _base64url_decode(data: str) -> bytes:
    """Decode base64url string adding necessary padding."""
    rem = len(data) % 4
    if rem > 0:
        data += "=" * (4 - rem)
    return base64.urlsafe_b64decode(data.encode("utf-8"))


def create_access_token(
    role: str,
    subject: Optional[str] = None,
    expires_in_seconds: Optional[int] = None,
    secret_key: Optional[str] = None,
    algorithm: Optional[str] = None,
    issuer: Optional[str] = None,
    audience: Optional[str] = None,
    jti: Optional[str] = None,
) -> str:
    """Create a cryptographically signed HMAC-SHA256 JWT access token for a given user role.

    Args:
        role: Validated role string ('student', 'faculty', 'admin').
        subject: User identifier or username (defaults to role).
        expires_in_seconds: Token TTL in seconds (defaults to settings.JWT_EXPIRE_SECONDS).
        secret_key: HMAC secret key (defaults to settings.JWT_SECRET_KEY).
        algorithm: Algorithm identifier (defaults to settings.JWT_ALGORITHM, e.g. 'HS256').
        issuer: Token issuer claim (defaults to settings.JWT_ISSUER).
        audience: Token audience claim (defaults to settings.JWT_AUDIENCE).
        jti: Unique JWT ID for replay prevention (defaults to fresh UUID4).

    Returns:
        Encoded and signed JWT string ({header}.{payload}.{signature}).
    """
    clean_role = validate_role(role)
    ttl = expires_in_seconds if expires_in_seconds is not None else settings.JWT_EXPIRE_SECONDS
    key = (secret_key or settings.JWT_SECRET_KEY).encode("utf-8")
    alg = algorithm or settings.JWT_ALGORITHM

    now = int(time.time())
    header = {"alg": alg, "typ": "JWT"}
    payload = {
        "sub": subject or clean_role,
        "role": clean_role,
        "iss": issuer or settings.JWT_ISSUER,
        "aud": audience or settings.JWT_AUDIENCE,
        "jti": jti or str(uuid.uuid4()),
        "iat": now,
        "exp": now + ttl,
    }

    header_b64 = _base64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _base64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")

    signature = hmac.new(key, signing_input, hashlib.sha256).digest()
    sig_b64 = _base64url_encode(signature)

    return f"{header_b64}.{payload_b64}.{sig_b64}"


def verify_access_token(
    token: str,
    secret_key: Optional[str] = None,
    expected_issuer: Optional[str] = None,
    expected_audience: Optional[str] = None,
) -> dict[str, Any]:
    """Verify cryptographic authenticity, signature, claims, and expiration of a JWT access token.

    Security checks:
    - Rejects tokens with fewer or more than 3 segments.
    - Explicitly rejects tokens using 'alg': 'none' or any algorithm other than HS256.
    - Computes HMAC-SHA256 signature and performs constant-time comparison.
    - Verifies expiration timestamp (exp).
    - Verifies audience (aud) and issuer (iss) if configured.
    - Validates that the 'role' claim is within permitted roles.

    Args:
        token: Raw JWT string.
        secret_key: Expected secret key.
        expected_issuer: Expected issuer claim (defaults to settings.JWT_ISSUER).
        expected_audience: Expected audience claim (defaults to settings.JWT_AUDIENCE).

    Returns:
        Decoded payload dictionary.

    Raises:
        AuthenticationError: If token is malformed, expired, tampered, wrong audience, or prohibited algorithms.
    """
    if not token or not isinstance(token, str):
        raise AuthenticationError("Authentication token is missing or empty.")

    clean_token = token.strip()
    parts = clean_token.split(".")
    if len(parts) != 3:
        raise AuthenticationError(f"Malformed JWT token: expected 3 segments, got {len(parts)}.")

    header_b64, payload_b64, sig_b64 = parts

    # 1. Decode header and verify algorithm
    try:
        header_raw = _base64url_decode(header_b64).decode("utf-8")
        header = json.loads(header_raw)
    except Exception as exc:
        raise AuthenticationError(f"Unable to decode JWT header: {exc}") from exc

    alg = str(header.get("alg", "")).upper()
    if alg == "NONE" or alg != settings.JWT_ALGORITHM.upper():
        raise AuthenticationError(f"Prohibited or unsupported JWT algorithm: '{alg}'. Only HS256 is permitted.")

    # 2. Verify HMAC-SHA256 signature
    key = (secret_key or settings.JWT_SECRET_KEY).encode("utf-8")
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    expected_sig = hmac.new(key, signing_input, hashlib.sha256).digest()
    expected_sig_b64 = _base64url_encode(expected_sig)

    if not hmac.compare_digest(sig_b64, expected_sig_b64):
        raise AuthenticationError("JWT signature verification failed: token has been tampered with or corrupted.")

    # 3. Decode and validate payload
    try:
        payload_raw = _base64url_decode(payload_b64).decode("utf-8")
        payload = json.loads(payload_raw)
    except Exception as exc:
        raise AuthenticationError(f"Unable to decode JWT payload: {exc}") from exc

    # 4. Expiration check
    exp = payload.get("exp")
    if exp is None:
        raise AuthenticationError("JWT payload is missing required 'exp' claim.")

    current_time = int(time.time())
    if current_time > int(exp):
        raise AuthenticationError(f"JWT token expired at {exp} (current time: {current_time}).")

    # 5. Audience check
    req_aud = expected_audience or settings.JWT_AUDIENCE
    token_aud = payload.get("aud")
    if token_aud and req_aud and token_aud != req_aud:
        raise AuthenticationError(f"JWT audience mismatch: expected '{req_aud}', got '{token_aud}'.")

    # 6. Issuer check
    req_iss = expected_issuer or settings.JWT_ISSUER
    token_iss = payload.get("iss")
    if token_iss and req_iss and token_iss != req_iss:
        raise AuthenticationError(f"JWT issuer mismatch: expected '{req_iss}', got '{token_iss}'.")

    # 7. Role claim validation
    role = payload.get("role")
    if not role:
        raise AuthenticationError("JWT payload is missing required 'role' claim.")

    try:
        clean_role = validate_role(str(role))
        payload["role"] = clean_role
    except InvalidRoleError as exc:
        raise AuthenticationError(f"JWT contains unauthorized role claim: {exc}") from exc

    return payload


def get_current_role(
    authorization: Optional[str] = Header(None),
) -> str:
    """FastAPI Dependency: Extract and cryptographically verify caller role from Bearer JWT.

    Strict security enforcement (Phase 2):
    - Missing or empty token -> HTTP 401 Unauthorized (never defaults to student).
    - Tampered or expired token -> HTTP 401 Unauthorized.
    - alg=none token -> HTTP 401 Unauthorized.
    - Wrong audience/issuer -> HTTP 401 Unauthorized.
    - Valid token -> verified role claim ('student', 'faculty', 'admin').
    """
    if not authorization or not authorization.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided. Missing Bearer authorization token.",
            headers={"WWW-Authenticate": 'Bearer error="missing_token"'},
        )

    token = authorization.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format. Expected 'Bearer <token>'.",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )

    try:
        payload = verify_access_token(token)
        return payload["role"]
    except AuthenticationError as exc:
        logger.warning("Authentication failure: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication token verification failed: {exc}",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        ) from exc
