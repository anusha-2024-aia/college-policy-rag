"""JWT Token Generation, Cryptographic Verification, and Role Extraction.

Enforces Rule 5 and Phase 4 Identity Specification:
1. User role is derived EXCLUSIVELY from verified cryptographic JWT tokens,
   never from client-controlled request bodies, query strings, or unverified headers.
2. Missing token defaults to 'student' (principle of least privilege).
3. Tampered, expired, or alg=none tokens strictly yield HTTP 401 Unauthorized.
4. Uses Python standard library (hmac, hashlib, base64, json, time) with zero external dependencies.
"""

import base64
import hmac
import hashlib
import json
import logging
import time
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
    expires_in_seconds: Optional[int] = None,
    secret_key: Optional[str] = None,
    algorithm: Optional[str] = None,
) -> str:
    """Create a signed HMAC-SHA256 JWT access token for a given user role.

    Args:
        role: Validated role string ('student', 'faculty', 'admin').
        expires_in_seconds: Token TTL in seconds (defaults to settings.JWT_EXPIRE_SECONDS).
        secret_key: HMAC secret key (defaults to settings.JWT_SECRET_KEY).
        algorithm: Algorithm identifier (defaults to settings.JWT_ALGORITHM, e.g. 'HS256').

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
        "sub": clean_role,
        "role": clean_role,
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
) -> dict[str, Any]:
    """Verify cryptographic authenticity, signature, and expiration of a JWT access token.

    Security checks:
    - Rejects tokens with fewer or more than 3 segments.
    - Explicitly rejects tokens using 'alg': 'none' or any algorithm other than HS256.
    - Computes HMAC-SHA256 signature and performs constant-time comparison.
    - Verifies expiration timestamp (exp).
    - Validates that the 'role' claim is within permitted roles.

    Args:
        token: Raw JWT string.
        secret_key: Expected secret key.

    Returns:
        Decoded payload dictionary.

    Raises:
        AuthenticationError: If token is malformed, expired, tampered, or uses prohibited algorithms.
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

    # 5. Role claim validation
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

    Enforces Phase 4 specification:
    - Missing token -> 'student' (principle of least privilege).
    - Tampered or expired token -> HTTP 401 Unauthorized.
    - alg=none token -> HTTP 401 Unauthorized.
    - Valid token -> verified role claim ('student', 'faculty', 'admin').
    """
    if not authorization or not authorization.strip():
        # Missing token: default to student least privilege
        return "student"

    token = authorization.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()

    try:
        payload = verify_access_token(token)
        return payload["role"]
    except AuthenticationError as exc:
        logger.warning("Authentication failure: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication token verification failed: {exc}",
            headers={"WWW-Authenticate": "Bearer error=\"invalid_token\""},
        ) from exc

