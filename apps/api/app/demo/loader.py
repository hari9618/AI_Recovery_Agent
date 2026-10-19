"""Insert a generated DemoDataset into PostgreSQL (replacing any previous demo tenant)."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db import models as m
from app.demo.generator import DemoDataset, strip_private
from app.security.auth import hash_token

logger = logging.getLogger(__name__)
BATCH = 500


async def _bulk(session: AsyncSession, model: type, rows: Sequence[dict[str, Any]]) -> None:
    for i in range(0, len(rows), BATCH):
        await session.execute(insert(model), [strip_private(r) for r in rows[i : i + BATCH]])


async def delete_demo_tenants(session: AsyncSession) -> int:
    """Remove every demo company; FK cascades remove all of its rows."""
    ids = (await session.scalars(select(m.Company.id).where(m.Company.is_demo.is_(True)))).all()
    if ids:
        await session.execute(delete(m.Company).where(m.Company.id.in_(ids)))
    return len(ids)


async def insert_demo_dataset(session: AsyncSession, ds: DemoDataset) -> dict[str, int]:
    """Insert all CRM rows. Caller owns the transaction."""
    removed = await delete_demo_tenants(session)
    if removed:
        logger.info("removed previous demo tenant(s)", extra={"count": removed})

    owner_token = get_settings().demo_api_token.get_secret_value()
    for user in ds.users:
        if user["role"].value == "owner":
            user["api_token_hash"] = hash_token(owner_token)

    await _bulk(session, m.Company, [ds.company])
    await _bulk(session, m.User, ds.users)
    await _bulk(session, m.Customer, ds.customers)
    await _bulk(session, m.Contact, ds.contacts)
    await _bulk(session, m.Lead, ds.leads)
    await _bulk(session, m.Opportunity, ds.opportunities)
    await _bulk(session, m.Quote, ds.quotes)
    await _bulk(session, m.QuoteItem, ds.quote_items)
    await _bulk(session, m.Conversation, ds.conversations)
    await _bulk(session, m.ConversationMessage, ds.messages)
    await _bulk(session, m.Followup, ds.followups)
    await _bulk(session, m.Activity, ds.activities)
    return ds.counts()
