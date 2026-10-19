"""Tenant settings access."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.db.models import Company
from app.domain.settings import CompanySettings


async def get_company(session: AsyncSession, company_id: uuid.UUID) -> Company:
    company = await session.get(Company, company_id)
    if company is None:
        raise NotFoundError("company", company_id)
    return company


async def get_company_settings(session: AsyncSession, company_id: uuid.UUID) -> CompanySettings:
    return CompanySettings.from_json((await get_company(session, company_id)).settings)


async def update_company_settings(session: AsyncSession, company_id: uuid.UUID, settings: CompanySettings) -> CompanySettings:
    company = await get_company(session, company_id)
    company.settings = settings.model_dump(mode="json")
    await session.flush()
    return settings
