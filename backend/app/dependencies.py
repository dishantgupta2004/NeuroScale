"""
Shared FastAPI dependencies.

The most important one is `get_current_user` — every protected route
depends on it to pull (user_id, company_id) from the JWT.
"""
from __future__ import annotations

from fastapi import Depends, Header

from app.models.auth import CurrentUser
from app.utils.exceptions import UnauthorizedError
from app.utils.security import decode_access_token


async def get_current_user(
    authorization: str | None = Header(default=None),
) -> CurrentUser:
    """
    Extracts and validates the JWT from the Authorization header.

    Expected: `Authorization: Bearer <token>`
    """
    if not authorization:
        raise UnauthorizedError("Missing Authorization header")

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise UnauthorizedError("Invalid Authorization header format")

    payload = decode_access_token(parts[1])
    return CurrentUser(
        user_id=payload["sub"],
        company_id=payload["company"],
    )


# Type alias for cleaner route signatures
CurrentUserDep = Depends(get_current_user)