"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.domain.enums import UserRole
from app.security.auth import Principal, get_principal, require_role

SessionDep = Annotated[AsyncSession, Depends(get_session)]
PrincipalDep = Annotated[Principal, Depends(get_principal)]
ManagerDep = Annotated[Principal, Depends(require_role(UserRole.MANAGER))]
AdminDep = Annotated[Principal, Depends(require_role(UserRole.ADMIN))]


class Page:
    def __init__(self, limit: int = Query(25, ge=1, le=200), offset: int = Query(0, ge=0)) -> None:
        self.limit, self.offset = limit, offset


PageDep = Annotated[Page, Depends()]


def paginated(items: list, total: int, page: Page) -> dict:
    return {"items": items, "total": total, "limit": page.limit, "offset": page.offset}
