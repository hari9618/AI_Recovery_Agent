"""Dashboard KPIs, revenue risks and ROI."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from app.api.deps import ManagerDep, PageDep, PrincipalDep, SessionDep, paginated
from app.domain.enums import ActorType, RiskLevel
from app.services.audit import record_audit
from app.services.company import get_company_settings
from app.services.reporting import at_risk_opportunities, dashboard_summary, roi_report
from app.services.risk_service import recompute_risks

router = APIRouter(tags=["revenue"])


@router.get("/dashboard/summary")
async def summary(principal: PrincipalDep, session: SessionDep) -> dict:
    return await dashboard_summary(session, principal.company_id)


@router.get("/risks")
async def list_risks(
    principal: PrincipalDep, session: SessionDep, page: PageDep,
    level: list[RiskLevel] | None = Query(None), owner_id: uuid.UUID | None = None, q: str | None = Query(None, max_length=100),
) -> dict:
    items, total = await at_risk_opportunities(session, principal.company_id, levels=level, owner_id=owner_id, search=q,
                                               limit=page.limit, offset=page.offset)
    return paginated(items, total, page)


@router.post("/risks/recompute")
async def recompute(principal: ManagerDep, session: SessionDep) -> dict:
    settings = await get_company_settings(session, principal.company_id)
    rows = await recompute_risks(session, principal.company_id, settings)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.risk_level.value] = counts.get(r.risk_level.value, 0) + 1
    record_audit(session, company_id=principal.company_id, action="risk.recomputed", actor_type=ActorType.USER,
                 actor_id=str(principal.user_id), actor_name=principal.name, output={"assessed": len(rows), "levels": counts})
    await session.commit()
    return {"assessed": len(rows), "levels": counts}


@router.get("/roi")
async def roi(principal: PrincipalDep, session: SessionDep) -> dict:
    return await roi_report(session, principal.company_id, await get_company_settings(session, principal.company_id))
