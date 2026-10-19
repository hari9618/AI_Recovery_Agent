"""Unified customer intelligence profile — one place that answers "what's going on with this account?".

Everything numeric is read from PostgreSQL / the risk engine. AI-derived fields (intent, objections)
carry their source (`llm_analysis` vs `keyword_heuristic`) so the UI never presents a heuristic as AI.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import NotFoundError
from app.db import models as m
from app.domain.conversation import PROMPT_VERSION, ConversationInsight
from app.domain.enums import OPEN_STAGES, FollowupStatus, LLMCallStatus, RiskLevel, SenderType
from app.domain.heuristics import analyze_customer_messages
from app.services.risk_service import known_competitors
from app.services.transcripts import transcript_hash


def _days_ago(ts: datetime | None, now: datetime) -> float | None:
    return round((now - ts).total_seconds() / 86400, 1) if ts else None


def _f(v: Decimal | None) -> float | None:
    return float(v) if v is not None else None


async def _current_insight(session: AsyncSession, conv: m.Conversation) -> tuple[ConversationInsight | None, m.ConversationAnalysis | None]:
    if not conv.messages:
        return None, None
    row = await session.scalar(
        select(m.ConversationAnalysis).where(
            m.ConversationAnalysis.conversation_id == conv.id,
            m.ConversationAnalysis.content_hash == transcript_hash(conv.messages),
            m.ConversationAnalysis.prompt_version == PROMPT_VERSION,
        )
    )
    if row and row.status in (LLMCallStatus.OK, LLMCallStatus.REPAIRED) and row.analysis:
        return ConversationInsight.from_stored(row.analysis), row
    return None, row


async def customer_profile(session: AsyncSession, company_id: uuid.UUID, customer_id: uuid.UUID) -> dict[str, Any]:
    now = datetime.now(UTC)
    customer = await session.scalar(select(m.Customer).where(m.Customer.id == customer_id, m.Customer.company_id == company_id))
    if customer is None:
        raise NotFoundError("customer", customer_id)
    owner = await session.get(m.User, customer.owner_id) if customer.owner_id else None
    opps = (await session.scalars(
        select(m.Opportunity).where(m.Opportunity.customer_id == customer_id).order_by(m.Opportunity.created_at.desc())
    )).all()
    open_opps = [o for o in opps if o.stage in OPEN_STAGES]
    risks = (await session.scalars(
        select(m.RevenueRisk).where(m.RevenueRisk.customer_id == customer_id, m.RevenueRisk.is_current.is_(True))
    )).all()
    top_risk = max(risks, key=lambda r: r.risk_score, default=None)
    primary = next((o for o in open_opps if top_risk and o.id == top_risk.opportunity_id), open_opps[0] if open_opps else None)
    quotes = (await session.scalars(
        select(m.Quote).options(selectinload(m.Quote.items)).where(m.Quote.customer_id == customer_id).order_by(m.Quote.sent_at.desc().nulls_last())
    )).all()
    convs = (await session.scalars(
        select(m.Conversation).options(selectinload(m.Conversation.messages))
        .where(m.Conversation.customer_id == customer_id).order_by(m.Conversation.last_message_at.desc())
    )).all()

    competitor_names = await known_competitors(session, company_id)
    intent, intent_source, objections, competitors, summary = "unknown", "none", [], [], None
    conv_payload = []
    for conv in convs:
        insight, row = await _current_insight(session, conv)
        heur = None
        if insight is None:
            heur = analyze_customer_messages([x.body for x in conv.messages if x.sender_type == SenderType.CUSTOMER], competitor_names)
        conv_payload.append({
            "id": str(conv.id), "channel": conv.channel.value, "subject": conv.subject, "opportunity_id": str(conv.opportunity_id) if conv.opportunity_id else None,
            "started_at": conv.started_at, "last_message_at": conv.last_message_at, "last_sender": conv.last_sender.value,
            "message_count": len(conv.messages),
            "analysis": {"source": "llm_analysis", "status": row.status.value if row else None, "model": row.model if row else None,
                         **insight.model_dump()} if insight else
                        {"source": "keyword_heuristic", "status": row.status.value if row else "not_analyzed",
                         "intent": heur.intent if heur else "unknown", "price_objection": heur.price_objection if heur else False,
                         "competitor_mentioned": heur.competitor_mentioned if heur else False, "sentiment": heur.sentiment if heur else "unknown"},
        })
        if primary and conv.opportunity_id == primary.id and intent == "unknown":
            if insight:
                intent, intent_source, summary = insight.intent, "llm_analysis", insight.summary
                objections = [o.model_dump() for o in insight.objections]
                competitors = [c.model_dump() for c in insight.competitor_mentions]
            elif heur:
                intent, intent_source = heur.intent, "keyword_heuristic"
                objections = ([{"type": "price", "detail": "Price objection (keyword match)", "quote": heur.evidence.get("PRICE_OBJECTION", "")}]
                              if heur.price_objection else [])
                competitors = [{"name": n, "context": heur.evidence.get("COMPETITOR_MENTIONED", "")} for n in heur.competitors] or (
                    [{"name": "unnamed", "context": heur.evidence.get("COMPETITOR_MENTIONED", "")}] if heur.competitor_mentioned else [])

    last_contact = max((x.sent_at for c in convs for x in c.messages if x.sender_type == SenderType.REP), default=None)
    live_quote = next((q for q in quotes if primary and q.opportunity_id == primary.id), None)
    recs = (await session.scalars(
        select(m.Recommendation).where(m.Recommendation.customer_id == customer_id).order_by(m.Recommendation.created_at.desc()).limit(10)
    )).all()
    followups = (await session.scalars(
        select(m.Followup).where(m.Followup.customer_id == customer_id).order_by(m.Followup.due_at.desc()).limit(20)
    )).all()
    activities = (await session.scalars(
        select(m.Activity).where(m.Activity.customer_id == customer_id).order_by(m.Activity.occurred_at.desc()).limit(40)
    )).all()
    audit = (await session.scalars(
        select(m.AuditLog).where(m.AuditLog.customer_id == customer_id, m.AuditLog.company_id == company_id)
        .order_by(m.AuditLog.occurred_at.desc()).limit(30)
    )).all()
    contacts = (await session.scalars(select(m.Contact).where(m.Contact.customer_id == customer_id))).all()

    main_objection = objections[0]["type"] if objections else None
    return {
        "customer": {
            "id": str(customer.id), "name": customer.name, "industry": customer.industry, "segment": customer.segment.value,
            "status": customer.status.value, "city": customer.city, "state": customer.state, "website": customer.website,
            "employee_count": customer.employee_count, "lifetime_value": _f(customer.lifetime_value),
            "owner": owner.full_name if owner else None, "is_synthetic": customer.is_synthetic,
        },
        "summary": {
            "deal_value": _f(primary.amount) if primary else None,
            "open_pipeline_value": float(sum(o.amount for o in open_opps)),
            "lead_stage": primary.stage.value if primary else None,
            "intent": intent, "intent_source": intent_source,
            "purchase_probability": top_risk.purchase_probability if top_risk else None,
            "revenue_risk": top_risk.risk_level.value if top_risk else RiskLevel.LOW.value if open_opps else None,
            "risk_score": top_risk.risk_score if top_risk else None,
            "revenue_at_risk": _f(top_risk.revenue_at_risk) if top_risk else 0.0,
            "last_contact_days": _days_ago(last_contact, now),
            "last_quote_value": _f(live_quote.total) if live_quote else None,
            "last_quote_status": live_quote.status.value if live_quote else None,
            "main_objection": main_objection,
            "competitor_mentioned": bool(competitors),
            "competitors": competitors,
            "objections": objections,
            "ai_summary": summary,
            "recommended_action": top_risk.recommended_next_step if top_risk else None,
        },
        "contacts": [{"id": str(c.id), "name": c.full_name, "title": c.title, "email": c.email, "phone": c.phone,
                      "is_decision_maker": c.is_decision_maker} for c in contacts],
        "opportunities": [{"id": str(o.id), "name": o.name, "stage": o.stage.value, "amount": _f(o.amount),
                           "expected_close_date": o.expected_close_date, "last_activity_at": o.last_activity_at,
                           "competitor": o.competitor, "loss_reason": o.loss_reason} for o in opps],
        "quotes": [{"id": str(q.id), "quote_number": q.quote_number, "version": q.version, "status": q.status.value,
                    "subtotal": _f(q.subtotal), "discount_pct": _f(q.discount_pct), "total": _f(q.total), "sent_at": q.sent_at,
                    "valid_until": q.valid_until, "opportunity_id": str(q.opportunity_id),
                    "items": [{"sku": i.sku, "description": i.description, "quantity": _f(i.quantity),
                               "unit_price": _f(i.unit_price), "line_total": _f(i.line_total)} for i in q.items]} for q in quotes],
        "conversations": conv_payload,
        "risks": [{"id": str(r.id), "opportunity_id": str(r.opportunity_id), "risk_score": r.risk_score,
                   "risk_level": r.risk_level.value, "revenue_at_risk": _f(r.revenue_at_risk),
                   "weighted_revenue_at_risk": _f(r.weighted_revenue_at_risk), "purchase_probability": r.purchase_probability,
                   "reason_codes": r.reason_codes, "recommended_next_step": r.recommended_next_step,
                   "signals": r.signals, "computed_at": r.computed_at, "engine_version": r.engine_version} for r in risks],
        "recommendations": [recommendation_dict(r) for r in recs],
        "followups": [{"id": str(f.id), "title": f.title, "due_at": f.due_at, "status": f.status.value,
                       "overdue": f.status == FollowupStatus.PENDING and f.due_at < now, "created_by_agent": f.created_by_agent}
                      for f in followups],
        "timeline": [{"id": str(a.id), "type": a.type.value, "description": a.description, "occurred_at": a.occurred_at}
                     for a in activities],
        "audit": [audit_dict(a) for a in audit],
    }


def recommendation_dict(r: m.Recommendation) -> dict[str, Any]:
    return {
        "id": str(r.id), "opportunity_id": str(r.opportunity_id), "customer_id": str(r.customer_id),
        "agent_run_id": str(r.agent_run_id) if r.agent_run_id else None, "action_type": r.action_type.value,
        "status": r.status.value, "title": r.title, "what_happened": r.what_happened, "why_risky": r.why_risky,
        "recommendation": r.recommendation, "expected_outcome": r.expected_outcome, "evidence": r.evidence,
        "proposed_action": r.proposed_action, "draft_subject": r.draft_subject, "draft_body": r.draft_body,
        "confidence": r.confidence, "requires_approval": r.requires_approval, "approval_reasons": r.approval_reasons,
        "grounding": r.grounding, "limitations": r.limitations, "generated_by": r.generated_by, "model": r.model,
        "trace_id": r.trace_id, "created_at": r.created_at,
    }


def audit_dict(a: m.AuditLog) -> dict[str, Any]:
    return {
        "id": str(a.id), "occurred_at": a.occurred_at, "actor_type": a.actor_type.value, "actor_id": a.actor_id,
        "actor_name": a.actor_name, "action": a.action, "entity_type": a.entity_type, "entity_id": a.entity_id,
        "customer_id": str(a.customer_id) if a.customer_id else None, "agent": a.agent, "tool": a.tool,
        "input": a.input, "output": a.output, "approval_request_id": str(a.approval_request_id) if a.approval_request_id else None,
        "result": a.result.value, "agent_run_id": str(a.agent_run_id) if a.agent_run_id else None,
        "trace_id": a.trace_id, "latency_ms": a.latency_ms,
    }
