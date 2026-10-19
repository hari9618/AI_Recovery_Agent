"""Authentication & authorisation boundary.

Authentication-ready design: requests carry `Authorization: Bearer <token>`; the SHA-256 of the
token is looked up in `users.api_token_hash`, yielding a `Principal` (user, company, role). Every
service call receives the principal and scopes queries by `principal.company_id`, which is the
tenant isolation boundary. Swapping in OIDC/JWT later only changes `resolve_principal`.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.db.models import User
from app.db.session import get_session
from app.domain.enums import UserRole

_ROLE_RANK = {UserRole.SALES_REP: 0, UserRole.MANAGER: 1, UserRole.ADMIN: 2, UserRole.OWNER: 3}


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    company_id: uuid.UUID
    role: UserRole
    name: str

    def has_role(self, minimum: UserRole) -> bool:
        return _ROLE_RANK[self.role] >= _ROLE_RANK[minimum]

    def require(self, minimum: UserRole, action: str) -> None:
        if not self.has_role(minimum):
            raise AppError(
                ErrorCode.FORBIDDEN,
                f"'{action}' requires role {minimum.value} or higher (you are {self.role.value})",
            )


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


async def resolve_principal(session: AsyncSession, token: str) -> Principal:
    digest = hash_token(token)
    user = await session.scalar(select(User).where(User.api_token_hash == digest, User.is_active.is_(True)))
    # compare_digest keeps the comparison constant-time even though the lookup is by hash.
    if user is None or not hmac.compare_digest(user.api_token_hash or "", digest):
        raise AppError(ErrorCode.UNAUTHENTICATED, "Invalid or expired API token")
    return Principal(user_id=user.id, company_id=user.company_id, role=user.role, name=user.full_name)


async def get_principal(request: Request, session: AsyncSession = Depends(get_session)) -> Principal:
    token = _bearer(request)
    if not token:
        raise AppError(ErrorCode.UNAUTHENTICATED, "Missing bearer token")
    principal = await resolve_principal(session, token)
    request.state.principal = principal
    return principal


def require_role(minimum: UserRole):
    """Route dependency enforcing a minimum role."""

    async def _dep(principal: Principal = Depends(get_principal)) -> Principal:
        principal.require(minimum, "this operation")
        return principal

    return _dep
