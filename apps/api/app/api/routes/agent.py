"""Agent runs, recommendations, approvals and the copilot."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import ManagerDep, PageDep, PrincipalDep, SessionDep, paginated
from app.core.errors import NotFoundError
from app.db import models as m
from app.domain.enums import AgentRunStatus, ApprovalStatus, RecommendationStatus, RiskLevel
from app.llm.factory import get_llm_provider
from app.security.auth import Principal
from app.services.agent_runner import create_run, decide_approval, execute_run
from app.services.copilot import ask_copilot
from app.services.customer_intelligence import recommendation_dict
from app.services.reporting import at_risk_opportunities

router = APIRouter(tags=["agent"])
logger = logging.getLogger(__name__)
_background: set[asyncio.Task[Any]] = set()  # keep references so tasks are not garbage-collected


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)


def _run_dict(r: m.AgentRun, customer_name: str | None = None, include_state: bool = False) -> dict[str, Any]:
    out = {"id": str(r.id), "opportunity_id": str(r.opportunity_id) if r.opportunity_id else None,
           "customer_id": str(r.customer_id) if r.customer_id else None, "customer_name": customer_name,
           "workflow": r.workflow, "status": r.status.value, "steps": r.steps, "error": r.error, "trace_id": r.trace_id,
           "trace_url": r.trace_url, "llm_calls": r.llm_calls, "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
           "cost_usd": r.cost_usd, "latency_ms": r.latency_ms, "created_at": r.created_at, "finished_at": r.finished_at}
    if include_state:
        out["state"] = r.state
    return out


class RunIn(BaseModel):
    opportunity_id: uuid.UUID
    force: bool = Field(False, description="Run the full workflow even when the deal is low risk")


@router.post("/agent/runs", status_code=202)
async def start_run(body: RunIn, principal: PrincipalDep) -> dict:
    run_id = await create_run(principal, body.opportunity_id)
    _spawn(execute_run(run_id, principal, force=body.force))
    return {"run_id": str(run_id), "status": "running"}


class BatchIn(BaseModel):
    levels: list[RiskLevel] = Field(default_factory=lambda: [RiskLevel.CRITICAL])
    limit: int = Field(5, ge=1, le=25)


async def _run_batch(principal: Principal, run_ids: list[uuid.UUID]) -> None:
    for run_id in run_ids:  # sequential: keeps within LLM rate limits and keeps traces readable
        try:
            await execute_run(run_id, principal)
        except Exception:  # noqa: BLE001
            logger.exception("batch run failed", extra={"run_id": str(run_id)})


@router.post("/agent/runs/batch", status_code=202)
async def start_batch(body: BatchIn, principal: ManagerDep, session: SessionDep) -> dict:
    items, _ = await at_risk_opportunities(session, principal.company_id, levels=body.levels, limit=body.limit)
    run_ids = [await create_run(principal, uuid.UUID(i["opportunity_id"])) for i in items]
    _spawn(_run_batch(principal, run_ids))
    return {"run_ids": [str(r) for r in run_ids], "count": len(run_ids)}


@router.get("/agent/runs")
async def list_runs(principal: PrincipalDep, session: SessionDep, page: PageDep, status: AgentRunStatus | None = None,
                    opportunity_id: uuid.UUID | None = None) -> dict:
    q = (select(m.AgentRun, m.Customer.name).outerjoin(m.Customer, m.Customer.id == m.AgentRun.customer_id)
         .where(m.AgentRun.company_id == principal.company_id))
    if status:
        q = q.where(m.AgentRun.status == status)
    if opportunity_id:
        q = q.where(m.AgentRun.opportunity_id == opportunity_id)
    total = await session.scalar(select(func.count()).select_from(q.subquery()))
    rows = (await session.execute(q.order_by(m.AgentRun.created_at.desc()).limit(page.limit).offset(page.offset))).all()
    return paginated([_run_dict(r, n) for r, n in rows], int(total or 0), page)


@router.get("/agent/runs/{run_id}")
async def get_run(run_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> dict:
    run = await session.scalar(select(m.AgentRun).where(m.AgentRun.id == run_id, m.AgentRun.company_id == principal.company_id))
    if run is None:
        raise NotFoundError("agent run", run_id)
    customer = await session.get(m.Customer, run.customer_id) if run.customer_id else None
    rec = await session.scalar(select(m.Recommendation).where(m.Recommendation.agent_run_id == run.id))
    approval = await session.scalar(select(m.ApprovalRequest).where(m.ApprovalRequest.recommendation_id == rec.id)) if rec else None
    return _run_dict(run, customer.name if customer else None, include_state=True) | {
        "recommendation": recommendation_dict(rec) if rec else None,
        "approval": _approval_dict(approval) if approval else None,
    }


# ------------------------------------------------------------------------------ recommendations
@router.get("/recommendations")
async def list_recommendations(principal: PrincipalDep, session: SessionDep, page: PageDep,
                               status: list[RecommendationStatus] | None = Query(None)) -> dict:
    q = (select(m.Recommendation, m.Customer.name, m.Opportunity.amount, m.RevenueRisk.risk_level, m.RevenueRisk.risk_score)
         .join(m.Customer, m.Customer.id == m.Recommendation.customer_id)
         .join(m.Opportunity, m.Opportunity.id == m.Recommendation.opportunity_id)
         .outerjoin(m.RevenueRisk, m.RevenueRisk.id == m.Recommendation.risk_id)
         .where(m.Recommendation.company_id == principal.company_id))
    if status:
        q = q.where(m.Recommendation.status.in_(status))
    total = await session.scalar(select(func.count()).select_from(q.subquery()))
    rows = (await session.execute(q.order_by(m.Recommendation.created_at.desc()).limit(page.limit).offset(page.offset))).all()
    items = [recommendation_dict(r) | {"customer_name": cname, "deal_value": float(amount),
                                       "risk_level": level.value if level else None, "risk_score": score}
             for r, cname, amount, level, score in rows]
    return paginated(items, int(total or 0), page)


@router.get("/recommendations/{recommendation_id}")
async def get_recommendation(recommendation_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> dict:
    rec = await session.scalar(select(m.Recommendation).where(m.Recommendation.id == recommendation_id,
                                                              m.Recommendation.company_id == principal.company_id))
    if rec is None:
        raise NotFoundError("recommendation", recommendation_id)
    customer = await session.get(m.Customer, rec.customer_id)
    approval = await session.scalar(select(m.ApprovalRequest).where(m.ApprovalRequest.recommendation_id == rec.id))
    actions = (await session.scalars(select(m.Action).where(m.Action.recommendation_id == rec.id).order_by(m.Action.created_at))).all()
    return recommendation_dict(rec) | {
        "customer_name": customer.name if customer else None,
        "approval": _approval_dict(approval) if approval else None,
        "actions": [{"id": str(a.id), "action_type": a.action_type.value, "status": a.status.value, "automated": a.automated,
                     "result": a.result, "executed_at": a.executed_at, "error": a.error} for a in actions],
    }


# ------------------------------------------------------------------------------ approvals
def _approval_dict(a: m.ApprovalRequest) -> dict[str, Any]:
    return {"id": str(a.id), "recommendation_id": str(a.recommendation_id), "status": a.status.value, "reasons": a.reasons,
            "risk_summary": a.risk_summary, "required_role": a.required_role, "decided_by": str(a.decided_by) if a.decided_by else None,
            "decided_at": a.decided_at, "decision_note": a.decision_note, "edited_payload": a.edited_payload, "created_at": a.created_at}


@router.get("/approvals")
async def list_approvals(principal: PrincipalDep, session: SessionDep, page: PageDep,
                         status: ApprovalStatus | None = ApprovalStatus.PENDING) -> dict:
    q = (select(m.ApprovalRequest, m.Recommendation, m.Customer.name, m.Opportunity.amount, m.User.full_name)
         .join(m.Recommendation, m.Recommendation.id == m.ApprovalRequest.recommendation_id)
         .join(m.Customer, m.Customer.id == m.Recommendation.customer_id)
         .join(m.Opportunity, m.Opportunity.id == m.Recommendation.opportunity_id)
         .outerjoin(m.User, m.User.id == m.ApprovalRequest.decided_by)
         .where(m.ApprovalRequest.company_id == principal.company_id))
    if status:
        q = q.where(m.ApprovalRequest.status == status)
    total = await session.scalar(select(func.count()).select_from(q.subquery()))
    rows = (await session.execute(q.order_by(m.ApprovalRequest.created_at.desc()).limit(page.limit).offset(page.offset))).all()
    items = [_approval_dict(a) | {"customer_name": cname, "deal_value": float(amount), "decided_by_name": decider,
                                  "recommendation": recommendation_dict(rec)} for a, rec, cname, amount, decider in rows]
    return paginated(items, int(total or 0), page)


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject"]
    note: str | None = Field(None, max_length=1000)
    email_subject: str | None = Field(None, min_length=3, max_length=200)
    email_body: str | None = Field(None, min_length=10, max_length=5000)
    discount_pct: float | None = Field(None, gt=0, le=100)


@router.post("/approvals/{approval_id}/decision")
async def decide(approval_id: uuid.UUID, body: DecisionIn, principal: PrincipalDep) -> dict:
    edits = {k: v for k, v in body.model_dump().items() if k in ("email_subject", "email_body", "discount_pct") and v is not None}
    return await decide_approval(principal, approval_id, decision=body.decision, note=body.note, edits=edits or None)


# ------------------------------------------------------------------------------ copilot
class CopilotIn(BaseModel):
    question: str = Field(min_length=3, max_length=2000)


@router.post("/copilot/ask")
async def copilot(body: CopilotIn, principal: PrincipalDep, session: SessionDep) -> dict:
    result = await ask_copilot(session, get_llm_provider(), company_id=principal.company_id, actor_id=str(principal.user_id),
                               actor_name=principal.name, question=body.question)
    await session.commit()
    return result
