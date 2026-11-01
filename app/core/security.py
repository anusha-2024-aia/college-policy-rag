"""Cryptographic password hashing and verification helpers."""

from __future__ import annotations

import logging
import hmac
import hashlib
import os

logger = logging.getLogger(__name__)

try:
    import bcrypt
    _HAS_BCRYPT = True
except ImportError:
    _HAS_BCRYPT = False


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt (or standard library scrypt fallback)."""
    if not password:
        raise ValueError("Password cannot be empty.")

    if _HAS_BCRYPT:
        salt = bcrypt.gensalt(rounds=12)
        return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

    # Fallback to standard library hashlib.scrypt if bcrypt is unavailable
    salt = os.urandom(16)
    key = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1)
    return f"scrypt${salt.hex()}${key.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a stored hashed password."""
    if not plain_password or not hashed_password:
        return False

    if hashed_password.startswith("$2b$") or hashed_password.startswith("$2a$") or hashed_password.startswith("$2y$"):
        if _HAS_BCRYPT:
            try:
                return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
            except Exception as exc:
                logger.warning("Error verifying bcrypt password: %s", exc)
                return False
        logger.error("Stored password is in bcrypt format but bcrypt library is missing.")
        return False

    if hashed_password.startswith("scrypt$"):
        try:
            parts = hashed_password.split("$")
            if len(parts) != 3:
                return False
            salt = bytes.fromhex(parts[1])
            expected_key = bytes.fromhex(parts[2])
            derived_key = hashlib.scrypt(plain_password.encode("utf-8"), salt=salt, n=16384, r=8, p=1)
            return hmac.compare_digest(derived_key, expected_key)
        except Exception as exc:
            logger.warning("Error verifying scrypt password: %s", exc)
            return False

    return False

