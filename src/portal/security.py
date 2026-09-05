"""Password hashing (PBKDF2, standard library) and JWT sign-in tokens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
import time
from typing import Any

import jwt

from ..config import settings

log = logging.getLogger(__name__)

_ITERATIONS = 260_000
JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return "pbkdf2_sha256$%d$%s$%s" % (
        _ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, iterations, salt_b64, digest_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
    except (ValueError, TypeError):
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
    return hmac.compare_digest(digest, expected)


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


MIN_PASSWORD_LENGTH = 6


def password_problem(password: str) -> str | None:
    """Why a password is unacceptable, or None."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if password.strip() != password:
        return "Password must not start or end with spaces."
    return None


# --- JWT --------------------------------------------------------------------

_generated_secret: str | None = None


def jwt_secret() -> str:
    """JWT_SECRET from the environment, or one made up for this process."""
    global _generated_secret
    if settings.jwt_secret:
        return settings.jwt_secret
    if _generated_secret is None:
        _generated_secret = new_token(48)
        log.warning("JWT_SECRET is not set: using a random secret, so every sign-in ends when this server restarts")
    return _generated_secret


def issue_jwt(role: str, subject_id: int, version: int, days: int | None = None) -> str:
    """A signed token for one account. ``version`` is the account's
    token_version; bumping it in the database retires every token issued
    before, which is how a password change signs other devices out."""
    now = int(time.time())
    claims = {
        "sub": str(subject_id),
        "role": role,
        "ver": int(version),
        "jti": new_token(16),
        "iat": now,
        "exp": now + (days if days is not None else settings.session_days) * 86_400,
    }
    return jwt.encode(claims, jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_jwt(token: str | None) -> dict[str, Any] | None:
    """The claims of a valid, unexpired token, or None. Never raises."""
    if not token:
        return None
    try:
        claims = jwt.decode(
            token, jwt_secret(), algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "role", "ver", "jti", "exp"]},
        )
    except jwt.PyJWTError:
        return None
    if claims["role"] not in ("doctor", "student") or not str(claims["sub"]).isdigit():
        return None
    return claims
