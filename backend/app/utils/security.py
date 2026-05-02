"""
Security utilities: JWT encode/decode + bcrypt password hashing.

JWT contents (claims):
    sub      : user_id
    company  : company_id (denormalized into token to skip a DB hit per request)
    exp      : standard expiry
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings
from app.utils.exceptions import UnauthorizedError


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _pwd_context.verify(plain, hashed)
    except Exception:
        # Bad hash format etc.
        return False


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------
def create_access_token(
    *,
    user_id: str,
    company_id: str,
    expires_delta: timedelta | None = None,
) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.jwt_expire_minutes)
    )
    payload: dict[str, Any] = {
        "sub": user_id,
        "company": company_id,
        "exp": expire,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Returns the decoded payload. Raises UnauthorizedError on any issue."""
    try:
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.jwt_algorithm]
        )
    except JWTError as e:
        raise UnauthorizedError(f"Invalid token: {e}") from e

    if "sub" not in payload or "company" not in payload:
        raise UnauthorizedError("Token missing required claims")
    return payload