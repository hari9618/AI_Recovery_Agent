"""Health, identity, settings and observability status."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import func, select, text

from app.api.deps import AdminDep, PrincipalDep, SessionDep
from app.core.config import get_settings
from app.db import models as m
from app.domain.enums import ActorType
from app.domain.settings import CompanySettings
from app.llm.pricing import price_for
from app.observability.tracing import get_tracer
from app.services.audit import record_audit
from app.services.company import get_company, get_company_settings, update_company_settings

router = APIRouter(tags=["system"])


@router.get("/health")
async def health(session: SessionDep) -> dict:
    """Unauthenticated liveness/readiness probe. Reports dependencies without exposing secrets."""
    settings = get_settings()
    db_ok = True
    try:
        await session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": db_ok, "llm_configured": settings.llm_configured,
            "llm_model": settings.groq_model if settings.llm_configured else None, "langfuse_configured": settings.langfuse_configured,
            "time": datetime.now(UTC)}


@router.get("/me")
async def me(principal: PrincipalDep, session: SessionDep) -> dict:
    company = await get_company(session, principal.company_id)
    return {"user_id": str(principal.user_id), "name": principal.name, "role": principal.role.value,
            "company": {"id": str(company.id), "name": company.name, "currency": company.currency, "is_demo": company.is_demo}}


@router.get("/settings")
async def read_settings(principal: PrincipalDep, session: SessionDep) -> dict:
    s = get_settings()
    company_settings = await get_company_settings(session, principal.company_id)
    return {
        "company": company_settings.model_dump(mode="json"),
        "llm": {"provider": s.llm_provider, "model": s.groq_model, "configured": s.llm_configured,
                "structured_mode": s.groq_structured_mode, "reasoning_effort": s.groq_reasoning_effort,
                "timeout_seconds": s.llm_timeout_seconds, "max_retries": s.llm_max_retries,
                "price_per_m_tokens": price_for(s.groq_model or "")},
        "rag": {"embedding_model": s.embedding_model, "reranker_model": s.reranker_model if s.reranker_enabled else None,
                "top_k": s.rag_top_k, "candidate_k": s.rag_candidate_k, "rrf_k": s.rag_rrf_k, "min_relevance": s.rag_min_relevance,
                "min_claim_support_xenc": s.rag_min_claim_support_xenc},
    }


@router.put("/settings")
async def write_settings(body: CompanySettings, principal: AdminDep, session: SessionDep) -> dict:
    before = await get_company_settings(session, principal.company_id)
    saved = await update_company_settings(session, principal.company_id, body)
    record_audit(session, company_id=principal.company_id, action="settings.updated", actor_type=ActorType.USER,
                 actor_id=str(principal.user_id), actor_name=principal.name, entity_type="company", entity_id=principal.company_id,
                 input={"before": before.model_dump(mode="json")}, output={"after": saved.model_dump(mode="json")})
    await session.commit()
    return saved.model_dump(mode="json")


@router.get("/observability/status")
async def observability_status(principal: PrincipalDep) -> dict:
    s = get_settings()
    return {"langfuse": get_tracer().health() | {"host": s.langfuse_host if s.langfuse_configured else None},
            "llm": {"configured": s.llm_configured, "model": s.groq_model}}


@router.get("/observability/usage")
async def observability_usage(principal: PrincipalDep, session: SessionDep, days: int = Query(30, ge=1, le=365)) -> dict:
    """LLM usage from the local ledger (independent of Langfuse)."""
    since = datetime.now(UTC) - timedelta(days=days)
    base = (m.LLMCall.company_id == principal.company_id, m.LLMCall.created_at >= since)
    rows = (await session.execute(
        select(m.LLMCall.purpose, m.LLMCall.model, m.LLMCall.status, func.count(), func.sum(m.LLMCall.input_tokens),
               func.sum(m.LLMCall.output_tokens), func.sum(m.LLMCall.estimated_cost_usd),
               func.percentile_cont(0.5).within_group(m.LLMCall.latency_ms), func.percentile_cont(0.95).within_group(m.LLMCall.latency_ms))
        .where(*base).group_by(m.LLMCall.purpose, m.LLMCall.model, m.LLMCall.status)
    )).all()
    daily = (await session.execute(
        select(func.date_trunc("day", m.LLMCall.created_at).label("d"), func.count(), func.sum(m.LLMCall.input_tokens + m.LLMCall.output_tokens),
               func.sum(m.LLMCall.estimated_cost_usd)).where(*base).group_by("d").order_by("d")
    )).all()
    runs = (await session.execute(
        select(m.AgentRun.status, func.count(), func.avg(m.AgentRun.latency_ms), func.sum(m.AgentRun.cost_usd))
        .where(m.AgentRun.company_id == principal.company_id, m.AgentRun.created_at >= since).group_by(m.AgentRun.status)
    )).all()
    recent = (await session.scalars(
        select(m.AgentRun).where(m.AgentRun.company_id == principal.company_id).order_by(m.AgentRun.created_at.desc()).limit(10)
    )).all()
    total_calls = sum(r[3] for r in rows)
    failed = sum(r[3] for r in rows if r[2].value in ("error", "fallback"))
    return {
        "window_days": days,
        "totals": {"llm_calls": total_calls, "input_tokens": int(sum(r[4] or 0 for r in rows)),
                   "output_tokens": int(sum(r[5] or 0 for r in rows)), "estimated_cost_usd": round(sum(r[6] or 0 for r in rows), 5),
                   "failure_rate": round(failed / total_calls, 4) if total_calls else None},
        "by_purpose": [{"purpose": r[0], "model": r[1], "status": r[2].value, "calls": r[3], "input_tokens": int(r[4] or 0),
                        "output_tokens": int(r[5] or 0), "estimated_cost_usd": round(r[6] or 0, 6),
                        "p50_latency_ms": round(r[7] or 0), "p95_latency_ms": round(r[8] or 0)} for r in rows],
        "daily": [{"day": d.date().isoformat(), "calls": n, "tokens": int(t or 0), "estimated_cost_usd": round(c or 0, 6)} for d, n, t, c in daily],
        "agent_runs": [{"status": s.value, "count": n, "avg_latency_ms": round(lat or 0), "cost_usd": round(c or 0, 5)} for s, n, lat, c in runs],
        "recent_runs": [{"id": str(r.id), "status": r.status.value, "created_at": r.created_at, "latency_ms": r.latency_ms,
                         "llm_calls": r.llm_calls, "tokens": r.input_tokens + r.output_tokens, "cost_usd": r.cost_usd,
                         "trace_id": r.trace_id, "trace_url": r.trace_url} for r in recent],
    }
