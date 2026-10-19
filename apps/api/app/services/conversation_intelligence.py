"""Conversation Intelligence: LLM analysis of transcripts with caching and verification.

- Cached by (conversation, transcript hash, prompt version) — re-analysis only when content changes.
- Verbatim-quote verification: quotes the model claims the customer said must appear in the transcript;
  unverifiable ones are dropped and reported (a cheap hallucination check).
- Low confidence is surfaced (needs_review) rather than hidden.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import NotFoundError
from app.db import models as m
from app.domain.conversation import PROMPT_VERSION, ConversationInsight
from app.domain.enums import ActorType, AuditResult, LLMCallStatus, SenderType
from app.llm.base import LLMProvider
from app.llm.ledger import llm_call_context
from app.llm.structured import generate_structured
from app.observability.tracing import get_tracer
from app.prompts.conversation import build_messages
from app.security.injection import scan_for_injection
from app.services.audit import record_audit
from app.services.transcripts import render_transcript, transcript_hash

logger = logging.getLogger(__name__)
LOW_CONFIDENCE = 0.6


def _norm(text: str) -> str:
    return re.sub(r"[\s\"'“”‘’]+", " ", text.lower()).strip(" .…")


def verify_quotes(insight: ConversationInsight, customer_text: str) -> tuple[ConversationInsight, list[str]]:
    """Drop quotes that do not appear verbatim (modulo whitespace/quotes/case) in the customer's messages."""
    haystack = _norm(customer_text)
    dropped: list[str] = []

    def ok(q: str) -> bool:
        good = bool(q.strip()) and _norm(q) in haystack
        if not good:
            dropped.append(q)
        return good

    cleaned = insight.model_copy(
        update={
            "evidence_quotes": [q for q in insight.evidence_quotes if ok(q)],
            "objections": [o for o in insight.objections if ok(o.quote)],
        }
    )
    return cleaned, dropped


@dataclass
class AnalysisOutcome:
    conversation_id: uuid.UUID
    status: LLMCallStatus
    cached: bool
    insight: ConversationInsight | None
    model: str
    dropped_quotes: list[str] = field(default_factory=list)
    injection_flags: list[dict[str, str]] = field(default_factory=list)
    needs_review: bool = False
    errors: list[str] = field(default_factory=list)
    analysis_id: uuid.UUID | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": str(self.conversation_id),
            "status": self.status.value,
            "cached": self.cached,
            "model": self.model,
            "insight": self.insight.model_dump() if self.insight else None,
            "dropped_quotes": self.dropped_quotes,
            "injection_flags": self.injection_flags,
            "needs_review": self.needs_review,
            "errors": self.errors,
        }


async def load_conversation(session: AsyncSession, company_id: uuid.UUID, conversation_id: uuid.UUID) -> m.Conversation:
    conv = await session.scalar(
        select(m.Conversation)
        .options(selectinload(m.Conversation.messages))
        .where(m.Conversation.id == conversation_id, m.Conversation.company_id == company_id)
    )
    if conv is None:
        raise NotFoundError("conversation", conversation_id)
    return conv


def _outcome_from_row(row: m.ConversationAnalysis, conversation_id: uuid.UUID) -> AnalysisOutcome:
    insight = ConversationInsight.from_stored(row.analysis) if row.analysis else None
    return AnalysisOutcome(
        conversation_id=conversation_id,
        status=row.status,
        cached=True,
        insight=insight,
        model=row.model,
        dropped_quotes=row.analysis.get("_dropped_quotes", []) if row.analysis else [],
        needs_review=bool(insight and insight.confidence < LOW_CONFIDENCE),
        analysis_id=row.id,
    )


async def analyze_conversation(
    session: AsyncSession,
    provider: LLMProvider,
    *,
    company_id: uuid.UUID,
    conversation_id: uuid.UUID,
    force: bool = False,
    actor_id: str | None = None,
) -> AnalysisOutcome:
    conv = await load_conversation(session, company_id, conversation_id)
    if not conv.messages:
        return AnalysisOutcome(
            conversation_id,
            LLMCallStatus.FALLBACK,
            False,
            None,
            provider.model,
            errors=["conversation has no messages"],
        )
    digest = transcript_hash(conv.messages)
    if not force:
        cached = await session.scalar(
            select(m.ConversationAnalysis).where(
                m.ConversationAnalysis.conversation_id == conv.id,
                m.ConversationAnalysis.content_hash == digest,
                m.ConversationAnalysis.prompt_version == PROMPT_VERSION,
            )
        )
        if cached is not None:
            return _outcome_from_row(cached, conv.id)

    customer = await session.get(m.Customer, conv.customer_id)
    opp = await session.get(m.Opportunity, conv.opportunity_id) if conv.opportunity_id else None
    deal_context = f"deal stage={opp.stage.value}, value={opp.currency} {opp.amount}" if opp else "no open deal linked"
    transcript = render_transcript(conv.messages)
    customer_text = "\n".join(x.body for x in conv.messages if x.sender_type == SenderType.CUSTOMER)
    injection = [f.as_dict() for f in scan_for_injection(transcript)]

    tracer = get_tracer()
    with (
        tracer.observation(
            "conversation_analysis",
            as_type="chain",
            input={"conversation_id": str(conv.id), "messages": len(conv.messages), "content_hash": digest[:12]},
            metadata={"prompt_version": PROMPT_VERSION},
        ) as span,
        llm_call_context(company_id=company_id, trace_id=span.trace_id),
    ):
        result = await generate_structured(
            provider,
            build_messages(
                transcript, customer_name=customer.name if customer else "unknown", deal_context=deal_context
            ),
            ConversationInsight,
            purpose="conversation_analysis",
        )
        dropped: list[str] = []
        insight = result.value
        if insight is not None:
            insight, dropped = verify_quotes(insight, customer_text)
        span.update(
            output={
                "status": result.status.value,
                "intent": insight.intent if insight else None,
                "dropped_quotes": len(dropped),
                "injection_flags": len(injection),
            },
            level="WARNING" if (dropped or injection or result.status == LLMCallStatus.FALLBACK) else None,
        )
        trace_id = span.trace_id

    payload: dict[str, Any] = insight.model_dump() if insight else {}
    if insight is not None:
        payload["_dropped_quotes"] = dropped
    row = m.ConversationAnalysis(
        company_id=company_id,
        conversation_id=conv.id,
        content_hash=digest,
        prompt_version=PROMPT_VERSION,
        model=result.model,
        status=result.status,
        intent=insight.intent if insight else None,
        sentiment=insight.sentiment if insight else None,
        confidence=insight.confidence if insight else None,
        analysis=payload,
        trace_id=trace_id,
        created_at=datetime.now(UTC),
    )
    # Replace a previous row for the same hash/version (force re-analysis).
    existing = await session.scalar(
        select(m.ConversationAnalysis).where(
            m.ConversationAnalysis.conversation_id == conv.id,
            m.ConversationAnalysis.content_hash == digest,
            m.ConversationAnalysis.prompt_version == PROMPT_VERSION,
        )
    )
    if existing is not None:
        await session.delete(existing)
        await session.flush()
    session.add(row)
    record_audit(
        session,
        company_id=company_id,
        action="conversation.analyzed",
        actor_type=ActorType.AGENT,
        actor_id=actor_id,
        agent="ConversationIntelligence",
        entity_type="conversation",
        entity_id=conv.id,
        customer_id=conv.customer_id,
        input={"content_hash": digest, "prompt_version": PROMPT_VERSION},
        output={
            "status": result.status.value,
            "intent": payload.get("intent"),
            "confidence": payload.get("confidence"),
            "dropped_quotes": len(dropped),
            "injection_flags": injection,
        },
        result=AuditResult.SUCCESS if result.ok else AuditResult.FAILURE,
        trace_id=trace_id,
    )
    await session.flush()
    return AnalysisOutcome(
        conversation_id=conv.id,
        status=result.status,
        cached=False,
        insight=insight,
        model=result.model,
        dropped_quotes=dropped,
        injection_flags=injection,
        needs_review=bool(insight is None or insight.confidence < LOW_CONFIDENCE),
        errors=result.errors,
        analysis_id=row.id,
    )


async def latest_analysis(session: AsyncSession, conversation: m.Conversation) -> m.ConversationAnalysis | None:
    """Most recent analysis for a conversation (any hash); callers compare hashes to detect staleness."""
    return await session.scalar(
        select(m.ConversationAnalysis)
        .where(m.ConversationAnalysis.conversation_id == conversation.id)
        .order_by(m.ConversationAnalysis.created_at.desc())
        .limit(1)
    )
