"""Audit trail."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import PageDep, PrincipalDep, SessionDep, paginated
from app.db import models as m
from app.domain.enums import ActorType, AuditResult
from app.services.customer_intelligence import audit_dict

router = APIRouter(tags=["audit"])


@router.get("/audit")
async def audit_log(
    principal: PrincipalDep,
    session: SessionDep,
    page: PageDep,
    actor_type: ActorType | None = None,
    result: AuditResult | None = None,
    customer_id: uuid.UUID | None = None,
    agent_run_id: uuid.UUID | None = None,
    action: str | None = Query(None, max_length=100),
    include_reads: bool = Query(False, description="Include read-only tool calls"),
) -> dict:
    q = select(m.AuditLog).where(m.AuditLog.company_id == principal.company_id)
    if actor_type:
        q = q.where(m.AuditLog.actor_type == actor_type)
    if result:
        q = q.where(m.AuditLog.result == result)
    if customer_id:
        q = q.where(m.AuditLog.customer_id == customer_id)
    if agent_run_id:
        q = q.where(m.AuditLog.agent_run_id == agent_run_id)
    if action:
        q = q.where(m.AuditLog.action.ilike(f"%{action}%"))
    if not include_reads:
        q = q.where(
            m.AuditLog.tool.is_(None)
            | m.AuditLog.tool.notin_(
                [
                    "get_customer",
                    "get_lead",
                    "get_opportunity",
                    "get_quote",
                    "get_conversation",
                    "get_customer_history",
                    "get_customer_intelligence",
                    "get_at_risk_opportunities",
                    "get_recovery_report",
                    "get_sales_policy",
                    "search_knowledge_base",
                ]
            )
        )
    total = await session.scalar(select(func.count()).select_from(q.subquery()))
    rows = (
        await session.scalars(q.order_by(m.AuditLog.occurred_at.desc()).limit(page.limit).offset(page.offset))
    ).all()
    names = {
        c.id: c.name
        for c in (
            await session.scalars(
                select(m.Customer).where(m.Customer.id.in_({r.customer_id for r in rows if r.customer_id}))
            )
        ).all()
    }
    return paginated([audit_dict(r) | {"customer_name": names.get(r.customer_id)} for r in rows], int(total or 0), page)
