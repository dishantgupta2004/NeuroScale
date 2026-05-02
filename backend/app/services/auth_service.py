"""
Auth service.

Signup creates a Company AND its first User in one transaction. The user
becomes admin of that company.
"""
from __future__ import annotations

import re

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import Company, User
from app.models.auth import LoginRequest, SignupRequest, TokenResponse
from app.utils.exceptions import ConflictError, UnauthorizedError
from app.utils.security import create_access_token, hash_password, verify_password


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    s = _SLUG_RE.sub("-", name.lower()).strip("-")
    return s[:60] or "company"


class AuthService:
    async def signup(self, db: AsyncSession, payload: SignupRequest) -> TokenResponse:
        # 1. Check email uniqueness
        existing = await db.execute(select(User).where(User.email == payload.email))
        if existing.scalar_one_or_none() is not None:
            raise ConflictError("Email already registered")

        # 2. Generate a unique slug for the company
        base_slug = _slugify(payload.company_name)
        slug = base_slug
        suffix = 1
        while True:
            r = await db.execute(select(Company).where(Company.slug == slug))
            if r.scalar_one_or_none() is None:
                break
            suffix += 1
            slug = f"{base_slug}-{suffix}"

        # 3. Create company + user atomically
        company = Company(name=payload.company_name, slug=slug)
        db.add(company)
        await db.flush()  # populate company.id

        user = User(
            email=payload.email,
            hashed_password=hash_password(payload.password),
            full_name=payload.full_name,
            company_id=company.id,
            is_admin=True,
        )
        db.add(user)
        await db.commit()

        logger.info(f"Signup: user={user.id} company={company.id} ({company.slug})")
        token = create_access_token(user_id=user.id, company_id=company.id)
        return TokenResponse(
            access_token=token, user_id=user.id, company_id=company.id
        )

    async def login(self, db: AsyncSession, payload: LoginRequest) -> TokenResponse:
        r = await db.execute(select(User).where(User.email == payload.email))
        user = r.scalar_one_or_none()
        if user is None or not verify_password(payload.password, user.hashed_password):
            raise UnauthorizedError("Invalid email or password")
        if not user.is_active:
            raise UnauthorizedError("Account disabled")

        token = create_access_token(user_id=user.id, company_id=user.company_id)
        return TokenResponse(
            access_token=token, user_id=user.id, company_id=user.company_id
        )


auth_service = AuthService()