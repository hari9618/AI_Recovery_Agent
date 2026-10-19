"""Dashboard KPIs, at-risk lists, recovery report and ROI.

Provenance rule: every figure is either OBSERVED (a query over recorded data), ESTIMATED (observed
counts × explicit, displayed assumptions) or reflects SYNTHETIC demo data. Nothing is hard-coded.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models as m
from app.domain.enums import (
    ActionStatus,
    ApprovalStatus,
    FollowupStatus,
    LeadStatus,
    OpportunityStage,
    RiskLevel,
)
from app.domain.settings import CompanySettings

HIGH_LEVELS = (RiskLevel.HIGH, RiskLevel.CRITICAL)
UNANSWERED_LEAD_HOURS = 4


def _f(v: Any) -> float:
    return float(v or 0)


async def at_risk_opportunities(
    session: AsyncSession,
    company_id: uuid.UUID,
    *,
    levels: list[RiskLevel] | None = None,
    owner_id: uuid.UUID | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    q = (
        select(m.RevenueRisk, m.Opportunity, m.Customer, m.User.full_name)
        .join(m.Opportunity, m.Opportunity.id == m.RevenueRisk.opportunity_id)
        .join(m.Customer, m.Customer.id == m.RevenueRisk.customer_id)
        .outerjoin(m.User, m.User.id == m.Opportunity.owner_id)
        .where(m.RevenueRisk.company_id == company_id, m.RevenueRisk.is_current.is_(True))
    )
    if levels:
        q = q.where(m.RevenueRisk.risk_level.in_(levels))
    if owner_id:
        q = q.where(m.Opportunity.owner_id == owner_id)
    if search:
        q = q.where(m.Customer.name.ilike(f"%{search.strip()[:100]}%"))
    total = await session.scalar(select(func.count()).select_from(q.subquery()))
    rows = (
        await session.execute(
            q.order_by(m.RevenueRisk.risk_score.desc(), m.RevenueRisk.revenue_at_risk.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    pending = {
        r[0]: r[1]
        for r in (
            await session.execute(
                select(m.Recommendation.opportunity_id, m.Recommendation.status)
                .where(
                    m.Recommendation.company_id == company_id,
                    m.Recommendation.opportunity_id.in_([r.Opportunity.id for r in rows]),
                )
                .order_by(m.Recommendation.created_at)
            )
        ).all()
    }
    items = [
        {
            "risk_id": str(r.id),
            "opportunity_id": str(o.id),
            "opportunity_name": o.name,
            "customer_id": str(c.id),
            "customer_name": c.name,
            "industry": c.industry,
            "owner": owner,
            "stage": o.stage.value,
            "deal_value": _f(o.amount),
            "risk_score": r.risk_score,
            "risk_level": r.risk_level.value,
            "revenue_at_risk": _f(r.revenue_at_risk),
            "weighted_revenue_at_risk": _f(r.weighted_revenue_at_risk),
            "purchase_probability": r.purchase_probability,
            "reasons": r.reason_codes,
            "recommended_next_step": r.recommended_next_step,
            "computed_at": r.computed_at,
            "latest_recommendation_status": pending[o.id].value if o.id in pending else None,
        }
        for r, o, c, owner in rows
    ]
    return items, int(total or 0)


async def dashboard_summary(session: AsyncSession, company_id: uuid.UUID) -> dict[str, Any]:
    now = datetime.now(UTC)
    company = await session.get(m.Company, company_id)
    cur = and_(m.RevenueRisk.company_id == company_id, m.RevenueRisk.is_current.is_(True))

    by_level = {
        lvl.value: {"count": n, "revenue_at_risk": _f(v), "deal_value": _f(dv)}
        for lvl, n, v, dv in (
            await session.execute(
                select(
                    m.RevenueRisk.risk_level,
                    func.count(),
                    func.sum(m.RevenueRisk.revenue_at_risk),
                    func.sum(m.Opportunity.amount),
                )
                .join(m.Opportunity, m.Opportunity.id == m.RevenueRisk.opportunity_id)
                .where(cur)
                .group_by(m.RevenueRisk.risk_level)
            )
        ).all()
    }
    for lvl in RiskLevel:
        by_level.setdefault(lvl.value, {"count": 0, "revenue_at_risk": 0.0, "deal_value": 0.0})
    high_value = sum(by_level[lvl.value]["revenue_at_risk"] for lvl in HIGH_LEVELS)
    weighted = _f(
        await session.scalar(
            select(func.sum(m.RevenueRisk.weighted_revenue_at_risk)).where(
                cur, m.RevenueRisk.risk_level.in_(HIGH_LEVELS)
            )
        )
    )

    reason_rows = (
        await session.execute(
            select(
                func.jsonb_array_elements(m.RevenueRisk.reason_codes, type_=JSONB)["code"].astext.label("code"),
                m.RevenueRisk.revenue_at_risk,
            ).where(cur, m.RevenueRisk.risk_level.in_(HIGH_LEVELS))
        )
    ).all()
    reasons: dict[str, dict[str, float]] = {}
    for code, value in reason_rows:
        bucket = reasons.setdefault(code, {"count": 0, "revenue_at_risk": 0.0})
        bucket["count"] += 1
        bucket["revenue_at_risk"] += _f(value)

    overdue_q = select(func.count()).where(
        m.Followup.company_id == company_id, m.Followup.status == FollowupStatus.PENDING, m.Followup.due_at < now
    )
    overdue = int(await session.scalar(overdue_q) or 0)
    unanswered_leads = int(
        await session.scalar(
            select(func.count()).where(
                m.Lead.company_id == company_id,
                m.Lead.status == LeadStatus.NEW,
                m.Lead.first_response_at.is_(None),
                m.Lead.received_at < now - timedelta(hours=UNANSWERED_LEAD_HOURS),
            )
        )
        or 0
    )
    open_pipeline = _f(
        await session.scalar(
            select(func.sum(m.Opportunity.amount)).where(
                m.Opportunity.company_id == company_id,
                m.Opportunity.stage.notin_((OpportunityStage.CLOSED_WON, OpportunityStage.CLOSED_LOST)),
            )
        )
    )

    by_rep = [
        {"owner": name, "at_risk_deals": n, "revenue_at_risk": _f(v)}
        for name, n, v in (
            await session.execute(
                select(m.User.full_name, func.count(), func.sum(m.RevenueRisk.revenue_at_risk))
                .select_from(m.RevenueRisk)
                .join(m.Opportunity, m.Opportunity.id == m.RevenueRisk.opportunity_id)
                .join(m.User, m.User.id == m.Opportunity.owner_id)
                .where(cur, m.RevenueRisk.risk_level.in_(HIGH_LEVELS))
                .group_by(m.User.full_name)
            )
        ).all()
    ]
    overdue_by_rep = dict(
        (
            await session.execute(
                select(m.User.full_name, func.count())
                .select_from(m.Followup)
                .join(m.User, m.User.id == m.Followup.assigned_to)
                .where(
                    m.Followup.company_id == company_id,
                    m.Followup.status == FollowupStatus.PENDING,
                    m.Followup.due_at < now,
                )
                .group_by(m.User.full_name)
            )
        ).all()
    )
    names = {r["owner"] for r in by_rep} | set(overdue_by_rep)
    reps = sorted(
        [
            {
                "owner": n,
                "at_risk_deals": next((r["at_risk_deals"] for r in by_rep if r["owner"] == n), 0),
                "revenue_at_risk": next((r["revenue_at_risk"] for r in by_rep if r["owner"] == n), 0.0),
                "overdue_followups": overdue_by_rep.get(n, 0),
            }
            for n in names
        ],
        key=lambda r: -r["revenue_at_risk"],
    )

    actions = await _action_stats(session, company_id)
    recovered = await recovered_revenue(session, company_id)
    pending_approvals = int(
        await session.scalar(
            select(func.count()).where(
                m.ApprovalRequest.company_id == company_id, m.ApprovalRequest.status == ApprovalStatus.PENDING
            )
        )
        or 0
    )
    recs = int(await session.scalar(select(func.count()).where(m.Recommendation.company_id == company_id)) or 0)
    last_risk = await session.scalar(select(func.max(m.RevenueRisk.computed_at)).where(cur))
    top, _ = await at_risk_opportunities(session, company_id, levels=list(HIGH_LEVELS), limit=8)

    return {
        "data_provenance": "synthetic_demo" if company and company.is_demo else "observed",
        "currency": company.currency if company else "INR",
        "risk_computed_at": last_risk,
        "kpis": {
            "revenue_at_risk": high_value,
            "weighted_revenue_at_risk": weighted,
            "revenue_recovered": recovered["revenue"],
            "recovered_deals": recovered["deals"],
            "high_risk_opportunities": sum(by_level[lvl.value]["count"] for lvl in HIGH_LEVELS),
            "critical_opportunities": by_level[RiskLevel.CRITICAL.value]["count"],
            "overdue_followups": overdue,
            "unanswered_leads": unanswered_leads,
            "open_pipeline_value": open_pipeline,
            "ai_recommendations": recs,
            "ai_actions": actions["total"],
            "automation_success_rate": actions["automation_success_rate"],
            "pending_approvals": pending_approvals,
        },
        "risk_distribution": by_level,
        "risk_reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1]["revenue_at_risk"])),
        "reps": reps,
        "top_risks": top,
        "actions": actions,
    }


async def _action_stats(session: AsyncSession, company_id: uuid.UUID) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(m.Action.automated, m.Action.status, func.count())
            .where(m.Action.company_id == company_id)
            .group_by(m.Action.automated, m.Action.status)
        )
    ).all()
    total = sum(n for *_, n in rows)
    auto_ok = sum(n for a, s, n in rows if a and s == ActionStatus.SUCCEEDED)
    auto_fail = sum(n for a, s, n in rows if a and s == ActionStatus.FAILED)
    return {
        "total": total,
        "by_status": {f"{'auto' if a else 'approved'}:{s.value}": n for a, s, n in rows},
        "automation_success_rate": round(auto_ok / (auto_ok + auto_fail), 4) if (auto_ok + auto_fail) else None,
    }


async def recovered_revenue(session: AsyncSession, company_id: uuid.UUID) -> dict[str, Any]:
    """Deals won *after* a recovery action was executed on them (attribution rule, observed)."""
    first_action = (
        select(m.Recommendation.opportunity_id.label("opp_id"), func.min(m.Action.executed_at).label("acted_at"))
        .join(m.Recommendation, m.Recommendation.id == m.Action.recommendation_id)
        .where(m.Action.company_id == company_id, m.Action.status == ActionStatus.SUCCEEDED)
        .group_by(m.Recommendation.opportunity_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(m.Opportunity.id, m.Opportunity.amount)
            .join(first_action, first_action.c.opp_id == m.Opportunity.id)
            .where(
                m.Opportunity.stage == OpportunityStage.CLOSED_WON, m.Opportunity.closed_at >= first_action.c.acted_at
            )
        )
    ).all()
    return {"deals": len(rows), "revenue": float(sum(Decimal(a) for _, a in rows))}


async def roi_report(session: AsyncSession, company_id: uuid.UUID, settings: CompanySettings) -> dict[str, Any]:
    company = await session.get(m.Company, company_id)
    a = settings.roi
    analyzed = int(
        await session.scalar(
            select(func.count(func.distinct(m.RevenueRisk.opportunity_id))).where(
                m.RevenueRisk.company_id == company_id
            )
        )
        or 0
    )
    summary = await dashboard_summary(session, company_id)
    k = summary["kpis"]
    runs = int(await session.scalar(select(func.count()).where(m.AgentRun.company_id == company_id)) or 0)
    drafts = int(
        await session.scalar(
            select(func.count()).where(
                m.Recommendation.company_id == company_id, m.Recommendation.draft_body.is_not(None)
            )
        )
        or 0
    )
    agent_followups = int(
        await session.scalar(
            select(func.count()).where(m.Followup.company_id == company_id, m.Followup.created_by_agent.is_(True))
        )
        or 0
    )
    cost = _f(
        await session.scalar(select(func.sum(m.LLMCall.estimated_cost_usd)).where(m.LLMCall.company_id == company_id))
    )
    hours = (
        runs * a.minutes_saved_per_deal_review
        + drafts * a.minutes_saved_per_draft
        + agent_followups * a.minutes_saved_per_followup_created
    ) / 60
    return {
        "data_provenance": "synthetic_demo" if company and company.is_demo else "observed",
        "observed": {
            "opportunities_analyzed": analyzed,
            "high_risk_opportunities": k["high_risk_opportunities"],
            "revenue_at_risk": k["revenue_at_risk"],
            "agent_runs": runs,
            "recommendations": k["ai_recommendations"],
            "drafts_generated": drafts,
            "followups_created_by_agent": agent_followups,
            "actions_executed": summary["actions"]["total"],
            "opportunities_recovered": k["recovered_deals"],
            "recovered_revenue": k["revenue_recovered"],
            "llm_cost_usd_estimated": round(cost, 4),
        },
        "estimated": {
            "hours_saved": round(hours, 1),
            "potential_recovery_if_assumed_rate": round(k["revenue_at_risk"] * a.assumed_recovery_rate, 0),
            "assumptions": a.model_dump(),
            "method": "hours = agent_runs × review minutes + drafts × drafting minutes + follow-ups × task minutes; "
            "potential recovery = current high/critical revenue at risk × assumed recovery rate",
        },
    }
