"""Customers, opportunities (pipeline), conversations and leads."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.api.deps import PageDep, PrincipalDep, SessionDep, paginated
from app.core.errors import AppError, ErrorCode, NotFoundError
from app.db import models as m
from app.domain.conversation import PROMPT_VERSION
from app.domain.enums import (
    OPEN_STAGES,
    Channel,
    ActivityType,
    ActorType,
    CustomerStatus,
    LeadStatus,
    LLMCallStatus,
    OpportunityStage,
    SenderType,
)
from app.domain.heuristics import analyze_customer_messages
from app.llm.factory import get_llm_provider
from app.llm.ledger import llm_call_context
from app.services.audit import record_audit
from app.services.company import get_company_settings
from app.services.conversation_intelligence import analyze_conversation, load_conversation
from app.services.customer_intelligence import customer_profile
from app.services.risk_service import recompute_risks
from app.services.transcripts import transcript_hash

router = APIRouter(tags=["crm"])


# ------------------------------------------------------------------------------ customers
@router.get("/customers")
async def list_customers(
    principal: PrincipalDep, session: SessionDep, page: PageDep,
    q: str | None = Query(None, max_length=100), status: CustomerStatus | None = None, industry: str | None = None,
) -> dict:
    risk = (select(m.RevenueRisk.customer_id, func.max(m.RevenueRisk.risk_score).label("score"),
                   func.sum(m.RevenueRisk.revenue_at_risk).label("at_risk"))
            .where(m.RevenueRisk.company_id == principal.company_id, m.RevenueRisk.is_current.is_(True))
            .group_by(m.RevenueRisk.customer_id).subquery())
    pipeline = (select(m.Opportunity.customer_id, func.sum(m.Opportunity.amount).label("open_value"), func.count().label("open_deals"))
                .where(m.Opportunity.company_id == principal.company_id, m.Opportunity.stage.in_(OPEN_STAGES))
                .group_by(m.Opportunity.customer_id).subquery())
    query = (select(m.Customer, risk.c.score, risk.c.at_risk, pipeline.c.open_value, pipeline.c.open_deals, m.User.full_name)
             .outerjoin(risk, risk.c.customer_id == m.Customer.id).outerjoin(pipeline, pipeline.c.customer_id == m.Customer.id)
             .outerjoin(m.User, m.User.id == m.Customer.owner_id)
             .where(m.Customer.company_id == principal.company_id))
    if q:
        query = query.where(or_(m.Customer.name.ilike(f"%{q}%"), m.Customer.city.ilike(f"%{q}%")))
    if status:
        query = query.where(m.Customer.status == status)
    if industry:
        query = query.where(m.Customer.industry == industry)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await session.execute(
        query.order_by(risk.c.score.desc().nulls_last(), pipeline.c.open_value.desc().nulls_last(), m.Customer.name)
        .limit(page.limit).offset(page.offset)
    )).all()
    items = [{"id": str(c.id), "name": c.name, "industry": c.industry, "segment": c.segment.value, "status": c.status.value,
              "city": c.city, "owner": owner, "risk_score": score, "revenue_at_risk": float(at_risk or 0),
              "open_pipeline_value": float(ov or 0), "open_deals": int(od or 0), "is_synthetic": c.is_synthetic}
             for c, score, at_risk, ov, od, owner in rows]
    return paginated(items, int(total or 0), page)


@router.get("/customers/{customer_id}")
async def get_customer(customer_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> dict:
    return await customer_profile(session, principal.company_id, customer_id)


# ------------------------------------------------------------------------------ opportunities
@router.get("/opportunities/pipeline")
async def pipeline(principal: PrincipalDep, session: SessionDep, owner_id: uuid.UUID | None = None) -> dict:
    q = (select(m.Opportunity, m.Customer.name, m.User.full_name, m.RevenueRisk.risk_level, m.RevenueRisk.risk_score)
         .join(m.Customer, m.Customer.id == m.Opportunity.customer_id)
         .outerjoin(m.User, m.User.id == m.Opportunity.owner_id)
         .outerjoin(m.RevenueRisk, (m.RevenueRisk.opportunity_id == m.Opportunity.id) & m.RevenueRisk.is_current.is_(True))
         .where(m.Opportunity.company_id == principal.company_id,
                or_(m.Opportunity.stage.in_(OPEN_STAGES), m.Opportunity.closed_at >= datetime.now(UTC) - timedelta(days=90))))
    if owner_id:
        q = q.where(m.Opportunity.owner_id == owner_id)
    rows = (await session.execute(q.order_by(m.RevenueRisk.risk_score.desc().nulls_last(), m.Opportunity.amount.desc()))).all()
    stages: dict[str, dict] = {s.value: {"stage": s.value, "count": 0, "value": 0.0, "items": []} for s in OpportunityStage}
    for o, cname, owner, level, score in rows:
        col = stages[o.stage.value]
        col["count"] += 1
        col["value"] += float(o.amount)
        if len(col["items"]) < 40:
            col["items"].append({"id": str(o.id), "name": o.name, "customer_id": str(o.customer_id), "customer_name": cname,
                                 "owner": owner, "amount": float(o.amount), "risk_level": level.value if level else None,
                                 "risk_score": score, "expected_close_date": o.expected_close_date, "last_activity_at": o.last_activity_at,
                                 "closed_at": o.closed_at})
    return {"stages": list(stages.values())}


class OutcomeIn(BaseModel):
    outcome: Literal["closed_won", "closed_lost"]
    loss_reason: str | None = Field(None, max_length=255)


@router.post("/opportunities/{opportunity_id}/outcome")
async def set_outcome(opportunity_id: uuid.UUID, body: OutcomeIn, principal: PrincipalDep, session: SessionDep) -> dict:
    """Record a won/lost outcome. Recovered revenue is attributed only if a recovery action was executed earlier."""
    opp = await session.scalar(select(m.Opportunity).where(m.Opportunity.id == opportunity_id, m.Opportunity.company_id == principal.company_id))
    if opp is None:
        raise NotFoundError("opportunity", opportunity_id)
    if opp.stage not in OPEN_STAGES:
        raise AppError(ErrorCode.CONFLICT, f"Opportunity already {opp.stage.value}")
    now = datetime.now(UTC)
    previous = opp.stage.value
    opp.stage, opp.closed_at, opp.stage_changed_at = OpportunityStage(body.outcome), now, now
    opp.loss_reason = body.loss_reason if body.outcome == "closed_lost" else None
    await session.execute(m.RevenueRisk.__table__.update().where(m.RevenueRisk.opportunity_id == opp.id).values(is_current=False))
    session.add(m.Activity(company_id=principal.company_id, customer_id=opp.customer_id, opportunity_id=opp.id, user_id=principal.user_id,
                           type=ActivityType.STAGE_CHANGE, description=f"Stage changed {previous} → {body.outcome}", occurred_at=now))
    if body.outcome == "closed_won":
        customer = await session.get(m.Customer, opp.customer_id)
        if customer and customer.status == CustomerStatus.PROSPECT:
            customer.status = CustomerStatus.ACTIVE
    record_audit(session, company_id=principal.company_id, action="opportunity.outcome_recorded", actor_type=ActorType.USER,
                 actor_id=str(principal.user_id), actor_name=principal.name, entity_type="opportunity", entity_id=opp.id,
                 customer_id=opp.customer_id, input=body.model_dump(), output={"previous_stage": previous})
    await session.commit()
    return {"opportunity_id": str(opp.id), "stage": body.outcome}


# ------------------------------------------------------------------------------ conversations
@router.get("/conversations")
async def list_conversations(
    principal: PrincipalDep, session: SessionDep, page: PageDep,
    customer_id: uuid.UUID | None = None, open_deals_only: bool = False, q: str | None = Query(None, max_length=100),
) -> dict:
    query = (select(m.Conversation, m.Customer.name, m.Opportunity.stage)
             .join(m.Customer, m.Customer.id == m.Conversation.customer_id)
             .outerjoin(m.Opportunity, m.Opportunity.id == m.Conversation.opportunity_id)
             .where(m.Conversation.company_id == principal.company_id))
    if customer_id:
        query = query.where(m.Conversation.customer_id == customer_id)
    if open_deals_only:
        query = query.where(m.Opportunity.stage.in_(OPEN_STAGES))
    if q:
        query = query.where(or_(m.Customer.name.ilike(f"%{q}%"), m.Conversation.subject.ilike(f"%{q}%")))
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await session.execute(query.order_by(m.Conversation.last_message_at.desc()).limit(page.limit).offset(page.offset))).all()
    analyses = {
        a.conversation_id: a for a in (await session.scalars(
            select(m.ConversationAnalysis).where(m.ConversationAnalysis.conversation_id.in_([r[0].id for r in rows]),
                                                 m.ConversationAnalysis.prompt_version == PROMPT_VERSION)
            .order_by(m.ConversationAnalysis.created_at)
        )).all()
    }
    items = []
    for c, cname, stage in rows:
        a = analyses.get(c.id)
        items.append({"id": str(c.id), "customer_id": str(c.customer_id), "customer_name": cname, "subject": c.subject,
                      "channel": c.channel.value, "last_message_at": c.last_message_at, "last_sender": c.last_sender.value,
                      "deal_stage": stage.value if stage else None,
                      "analysis": {"status": a.status.value, "intent": a.intent, "sentiment": a.sentiment, "confidence": a.confidence,
                                   "model": a.model} if a else None})
    return paginated(items, int(total or 0), page)


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> dict:
    conv = await load_conversation(session, principal.company_id, conversation_id)
    customer = await session.get(m.Customer, conv.customer_id)
    digest = transcript_hash(conv.messages) if conv.messages else None
    analyses = (await session.scalars(
        select(m.ConversationAnalysis).where(m.ConversationAnalysis.conversation_id == conv.id)
        .order_by(m.ConversationAnalysis.created_at.desc())
    )).all()
    current = next((a for a in analyses if a.content_hash == digest and a.prompt_version == PROMPT_VERSION), None)
    heur = analyze_customer_messages([x.body for x in conv.messages if x.sender_type == SenderType.CUSTOMER])
    return {
        "id": str(conv.id), "customer": {"id": str(conv.customer_id), "name": customer.name if customer else None},
        "opportunity_id": str(conv.opportunity_id) if conv.opportunity_id else None, "subject": conv.subject,
        "channel": conv.channel.value, "is_synthetic": conv.is_synthetic,
        "messages": [{"id": str(x.id), "sender_type": x.sender_type.value, "sender_name": x.sender_name, "body": x.body,
                      "sent_at": x.sent_at} for x in conv.messages],
        "analysis": ({"status": current.status.value, "model": current.model, "created_at": current.created_at,
                      "trace_id": current.trace_id, "stale": False, **current.analysis} if current else None),
        "stale_analysis_exists": bool(analyses and not current),
        "heuristic": {"source": "keyword_heuristic", "intent": heur.intent, "price_objection": heur.price_objection,
                      "competitor_mentioned": heur.competitor_mentioned, "sentiment": heur.sentiment, "evidence": heur.evidence},
    }


class MessageIn(BaseModel):
    sender_type: Literal["customer", "rep"]
    sender_name: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=10_000)
    sent_at: datetime | None = None


class ConversationIn(BaseModel):
    customer_id: uuid.UUID
    opportunity_id: uuid.UUID | None = None
    channel: Literal["email", "call", "whatsapp", "meeting", "chat"] = "email"
    subject: str | None = Field(None, max_length=255)
    messages: list[MessageIn] = Field(min_length=1, max_length=200)


@router.post("/conversations", status_code=201)
async def create_conversation(body: ConversationIn, principal: PrincipalDep, session: SessionDep) -> dict:
    """Log a conversation (e.g. pasted email thread or call notes). Message text is stored as untrusted data."""
    customer = await session.scalar(select(m.Customer).where(m.Customer.id == body.customer_id, m.Customer.company_id == principal.company_id))
    if customer is None:
        raise NotFoundError("customer", body.customer_id)
    if body.opportunity_id and not await session.scalar(select(m.Opportunity.id).where(
            m.Opportunity.id == body.opportunity_id, m.Opportunity.customer_id == customer.id)):
        raise NotFoundError("opportunity", body.opportunity_id)
    now = datetime.now(UTC)
    times = [msg.sent_at or now for msg in body.messages]
    if any(t > now + timedelta(minutes=5) or t < now - timedelta(days=365) for t in times):
        raise AppError(ErrorCode.INVALID_REQUEST, "Message timestamps must be within the last year and not in the future")
    conv = m.Conversation(company_id=principal.company_id, customer_id=customer.id, opportunity_id=body.opportunity_id,
                          channel=Channel(body.channel), subject=body.subject, started_at=min(times), last_message_at=max(times),
                          last_sender=SenderType(body.messages[times.index(max(times))].sender_type))
    session.add(conv)
    await session.flush()
    for msg, t in zip(body.messages, times, strict=True):
        session.add(m.ConversationMessage(conversation_id=conv.id, sender_type=SenderType(msg.sender_type),
                                          sender_name=msg.sender_name, body=msg.body, sent_at=t))
        if msg.sender_type == "rep" and body.opportunity_id:
            session.add(m.Activity(company_id=principal.company_id, customer_id=customer.id, opportunity_id=body.opportunity_id,
                                   user_id=principal.user_id, type=ActivityType.EMAIL, description=f"Message to customer: {msg.body[:120]}",
                                   occurred_at=t))
    record_audit(session, company_id=principal.company_id, action="conversation.created", actor_type=ActorType.USER,
                 actor_id=str(principal.user_id), actor_name=principal.name, entity_type="conversation", entity_id=conv.id,
                 customer_id=customer.id, output={"messages": len(body.messages)})
    if body.opportunity_id:
        await recompute_risks(session, principal.company_id, await get_company_settings(session, principal.company_id),
                              opportunity_ids=[body.opportunity_id])
    await session.commit()
    return {"id": str(conv.id), "messages": len(body.messages)}


@router.post("/conversations/{conversation_id}/analyze")
async def analyze(conversation_id: uuid.UUID, principal: PrincipalDep, session: SessionDep, force: bool = False) -> dict:
    provider = get_llm_provider()
    with llm_call_context(company_id=principal.company_id):
        out = await analyze_conversation(session, provider, company_id=principal.company_id, conversation_id=conversation_id,
                                         force=force, actor_id=str(principal.user_id))
    conv = await session.get(m.Conversation, conversation_id)
    if conv and conv.opportunity_id and not out.cached:
        await recompute_risks(session, principal.company_id, await get_company_settings(session, principal.company_id),
                              opportunity_ids=[conv.opportunity_id])
    await session.commit()
    return out.as_dict()


class BatchAnalyzeIn(BaseModel):
    limit: int = Field(20, ge=1, le=200)
    open_deals_only: bool = True


@router.post("/conversations/analyze-batch")
async def analyze_batch(body: BatchAnalyzeIn, principal: PrincipalDep, session: SessionDep) -> dict:
    """Analyse conversations of open deals that have no current analysis (most at-risk first)."""
    provider = get_llm_provider()
    q = (select(m.Conversation).options(selectinload(m.Conversation.messages))
         .join(m.Opportunity, m.Opportunity.id == m.Conversation.opportunity_id)
         .outerjoin(m.RevenueRisk, (m.RevenueRisk.opportunity_id == m.Opportunity.id) & m.RevenueRisk.is_current.is_(True))
         .where(m.Conversation.company_id == principal.company_id))
    if body.open_deals_only:
        q = q.where(m.Opportunity.stage.in_(OPEN_STAGES))
    convs = (await session.scalars(q.order_by(m.RevenueRisk.risk_score.desc().nulls_last()))).all()
    done = (await session.execute(select(m.ConversationAnalysis.conversation_id, m.ConversationAnalysis.content_hash)
                                  .where(m.ConversationAnalysis.company_id == principal.company_id,
                                         m.ConversationAnalysis.prompt_version == PROMPT_VERSION))).all()
    done_set = {(c, h) for c, h in done}
    todo = [c for c in convs if c.messages and (c.id, transcript_hash(c.messages)) not in done_set][: body.limit]
    results = {"analyzed": 0, "fallback": 0, "errors": []}
    opp_ids = set()
    with llm_call_context(company_id=principal.company_id):
        for conv in todo:
            try:
                out = await analyze_conversation(session, provider, company_id=principal.company_id, conversation_id=conv.id,
                                                 actor_id=str(principal.user_id))
                results["analyzed" if out.status != LLMCallStatus.FALLBACK else "fallback"] += 1
                opp_ids.add(conv.opportunity_id)
                await session.commit()
            except AppError as exc:
                results["errors"].append({"conversation_id": str(conv.id), "error": exc.message})
                if exc.code in (ErrorCode.LLM_RATE_LIMITED, ErrorCode.LLM_NOT_CONFIGURED):
                    break
    if opp_ids:
        await recompute_risks(session, principal.company_id, await get_company_settings(session, principal.company_id),
                              opportunity_ids=[o for o in opp_ids if o])
        await session.commit()
    return results | {"remaining": max(len([c for c in convs if c.messages]) - len(done_set) - results["analyzed"], 0)}


# ------------------------------------------------------------------------------ leads
@router.get("/leads")
async def list_leads(principal: PrincipalDep, session: SessionDep, page: PageDep, status: LeadStatus | None = None,
                     unanswered: bool = False) -> dict:
    q = select(m.Lead, m.User.full_name).outerjoin(m.User, m.User.id == m.Lead.assigned_to).where(m.Lead.company_id == principal.company_id)
    if status:
        q = q.where(m.Lead.status == status)
    if unanswered:
        q = q.where(m.Lead.first_response_at.is_(None), m.Lead.status == LeadStatus.NEW)
    total = await session.scalar(select(func.count()).select_from(q.subquery()))
    rows = (await session.execute(q.order_by(m.Lead.received_at.desc()).limit(page.limit).offset(page.offset))).all()
    now = datetime.now(UTC)
    items = [{"id": str(x.id), "company_name": x.company_name, "contact_name": x.contact_name, "source": x.source.value,
              "status": x.status.value, "estimated_value": float(x.estimated_value) if x.estimated_value else None,
              "received_at": x.received_at, "first_response_at": x.first_response_at, "assigned_to": owner,
              "hours_without_response": round((now - x.received_at).total_seconds() / 3600, 1) if not x.first_response_at else None,
              "customer_id": str(x.customer_id) if x.customer_id else None} for x, owner in rows]
    return paginated(items, int(total or 0), page)
