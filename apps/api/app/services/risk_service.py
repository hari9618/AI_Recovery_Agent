"""Builds RiskSignals from PostgreSQL and persists RiskAssessments.

All measurements are deterministic SQL/Python. Queries are batched per company (a handful of
round-trips regardless of pipeline size) so a full recompute stays fast.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models as m
from app.domain.conversation import PROMPT_VERSION, ConversationInsight
from app.domain.enums import (
    LIVE_QUOTE_STATUSES,
    OPEN_STAGES,
    ActivityType,
    FollowupStatus,
    LLMCallStatus,
    OpportunityStage,
    QuoteStatus,
    SenderType,
    SignalSource,
)
from app.domain.heuristics import analyze_customer_messages
from app.domain.risk import RiskAssessment, RiskSignals, assess
from app.domain.settings import CompanySettings
from app.services.transcripts import transcript_hash

REP_TOUCH_TYPES = (ActivityType.CALL, ActivityType.EMAIL, ActivityType.MEETING, ActivityType.QUOTE_SENT)
HISTORY_WINDOW_DAYS = 365


def _days_between(later: datetime, earlier: datetime) -> float:
    return max((later - earlier).total_seconds() / 86400, 0.0)


@dataclass
class _ConvSignals:
    intent: str = "unknown"
    intent_source: SignalSource = SignalSource.NONE
    competitor: bool = False
    competitors: tuple[str, ...] = ()
    competitor_source: SignalSource = SignalSource.NONE
    price: bool = False
    price_source: SignalSource = SignalSource.NONE
    sentiment: str = "unknown"
    sentiment_source: SignalSource = SignalSource.NONE
    evidence: dict[str, str] | None = None


_INTENT_ORDER = {"unknown": -1, "low": 0, "medium": 1, "high": 2}


def merge_conversation_signals(
    llm: list[ConversationInsight], heuristic_texts: list[str], competitor_names: list[str]
) -> _ConvSignals:
    """Combine LLM analyses (preferred) with keyword heuristics for un-analysed conversations."""
    out = _ConvSignals(evidence={})
    assert out.evidence is not None
    for insight in llm:
        if _INTENT_ORDER[insight.intent] > _INTENT_ORDER[out.intent]:
            out.intent, out.intent_source = insight.intent, SignalSource.LLM_ANALYSIS
        if insight.competitor_mentions:
            out.competitor, out.competitor_source = True, SignalSource.LLM_ANALYSIS
            out.competitors = tuple(dict.fromkeys([*out.competitors, *insight.competitor_names]))
            out.evidence.setdefault("COMPETITOR_MENTIONED", insight.competitor_mentions[0].context)
        if insight.has_price_objection:
            out.price, out.price_source = True, SignalSource.LLM_ANALYSIS
            quote = next(o.quote for o in insight.objections if o.type == "price")
            out.evidence.setdefault("PRICE_OBJECTION", quote)
        if out.sentiment != "negative":
            out.sentiment, out.sentiment_source = insight.sentiment, SignalSource.LLM_ANALYSIS
    if heuristic_texts:
        h = analyze_customer_messages(heuristic_texts, competitor_names)
        if out.intent_source == SignalSource.NONE:
            out.intent, out.intent_source = h.intent, SignalSource.KEYWORD_HEURISTIC
        if h.competitor_mentioned and not out.competitor:
            out.competitor, out.competitor_source = True, SignalSource.KEYWORD_HEURISTIC
            out.competitors = tuple(h.competitors)
        if h.price_objection and not out.price:
            out.price, out.price_source = True, SignalSource.KEYWORD_HEURISTIC
        if out.sentiment_source == SignalSource.NONE:
            out.sentiment, out.sentiment_source = h.sentiment, SignalSource.KEYWORD_HEURISTIC
        for code, text in h.evidence.items():
            out.evidence.setdefault(code, text)
    return out


async def historical_win_rates(
    session: AsyncSession, company_id: uuid.UUID, now: datetime
) -> dict[str | None, tuple[float, int]]:
    """Win rate of deals closed in the last year, per customer segment plus overall (key None)."""
    since = now - timedelta(days=HISTORY_WINDOW_DAYS)
    won = func.count().filter(m.Opportunity.stage == OpportunityStage.CLOSED_WON)
    rows = (
        await session.execute(
            select(m.Customer.segment, won, func.count())
            .join(m.Customer, m.Customer.id == m.Opportunity.customer_id)
            .where(
                m.Opportunity.company_id == company_id,
                m.Opportunity.stage.in_((OpportunityStage.CLOSED_WON, OpportunityStage.CLOSED_LOST)),
                m.Opportunity.closed_at >= since,
            )
            .group_by(m.Customer.segment)
        )
    ).all()
    rates: dict[str | None, tuple[float, int]] = {}
    total_won = total = 0
    for segment, w, n in rows:
        rates[segment.value] = (w / n if n else 0.0, n)
        total_won, total = total_won + w, total + n
    rates[None] = (total_won / total if total else 0.0, total)
    return rates


async def known_competitors(session: AsyncSession, company_id: uuid.UUID) -> list[str]:
    """Competitor names recorded on this tenant's opportunities (used by the keyword heuristic)."""
    rows = await session.scalars(
        select(m.Opportunity.competitor)
        .where(m.Opportunity.company_id == company_id, m.Opportunity.competitor.is_not(None))
        .distinct()
    )
    return [c for c in rows.all() if c]


async def build_signals(
    session: AsyncSession,
    company_id: uuid.UUID,
    *,
    now: datetime | None = None,
    opportunity_ids: list[uuid.UUID] | None = None,
) -> dict[uuid.UUID, tuple[m.Opportunity, RiskSignals]]:
    now = now or datetime.now(UTC)
    await session.flush()  # sessions run with autoflush off; make pending CRM writes visible to these queries
    opp_q = select(m.Opportunity).where(m.Opportunity.company_id == company_id, m.Opportunity.stage.in_(OPEN_STAGES))
    if opportunity_ids:
        opp_q = opp_q.where(m.Opportunity.id.in_(opportunity_ids))
    opps = (await session.scalars(opp_q)).all()
    if not opps:
        return {}
    ids = [o.id for o in opps]

    segments = dict(
        (await session.execute(
            select(m.Customer.id, m.Customer.segment).where(m.Customer.id.in_({o.customer_id for o in opps}))
        )).all()
    )
    win_rates = await historical_win_rates(session, company_id, now)
    competitors = await known_competitors(session, company_id)

    quotes_by_opp: dict[uuid.UUID, m.Quote] = {}
    for q in (await session.scalars(
        select(m.Quote).where(m.Quote.opportunity_id.in_(ids)).order_by(m.Quote.sent_at.asc().nulls_first())
    )).all():
        quotes_by_opp[q.opportunity_id] = q  # latest by sent_at wins

    rep_touch: dict[uuid.UUID, datetime] = dict(
        (await session.execute(
            select(m.Activity.opportunity_id, func.max(m.Activity.occurred_at))
            .where(m.Activity.opportunity_id.in_(ids), m.Activity.type.in_(REP_TOUCH_TYPES), m.Activity.user_id.is_not(None))
            .group_by(m.Activity.opportunity_id)
        )).all()
    )
    overdue: dict[uuid.UUID, int] = dict(
        (await session.execute(
            select(m.Followup.opportunity_id, func.count())
            .where(m.Followup.opportunity_id.in_(ids), m.Followup.status == FollowupStatus.PENDING, m.Followup.due_at < now)
            .group_by(m.Followup.opportunity_id)
        )).all()
    )

    convs = (await session.scalars(select(m.Conversation).where(m.Conversation.opportunity_id.in_(ids)))).all()
    conv_ids = [c.id for c in convs]
    messages: dict[uuid.UUID, list[m.ConversationMessage]] = defaultdict(list)
    if conv_ids:
        for msg in (await session.scalars(
            select(m.ConversationMessage).where(m.ConversationMessage.conversation_id.in_(conv_ids)).order_by(m.ConversationMessage.sent_at)
        )).all():
            messages[msg.conversation_id].append(msg)
    analyses: dict[tuple[uuid.UUID, str], ConversationInsight] = {}
    if conv_ids:
        for a in (await session.scalars(
            select(m.ConversationAnalysis).where(
                m.ConversationAnalysis.conversation_id.in_(conv_ids),
                m.ConversationAnalysis.prompt_version == PROMPT_VERSION,
                m.ConversationAnalysis.status.in_((LLMCallStatus.OK, LLMCallStatus.REPAIRED)),
            )
        )).all():
            analyses[(a.conversation_id, a.content_hash)] = ConversationInsight.from_stored(a.analysis)
    convs_by_opp: dict[uuid.UUID, list[m.Conversation]] = defaultdict(list)
    for c in convs:
        convs_by_opp[c.opportunity_id].append(c)  # type: ignore[index]

    result: dict[uuid.UUID, tuple[m.Opportunity, RiskSignals]] = {}
    for opp in opps:
        opp_msgs = sorted((msg for c in convs_by_opp[opp.id] for msg in messages[c.id]), key=lambda x: x.sent_at)
        quote = quotes_by_opp.get(opp.id)
        rep_times = [x.sent_at for x in opp_msgs if x.sender_type == SenderType.REP]
        # Rep touches: logged calls/emails/meetings, rep messages, and sending a quotation.
        candidates = (rep_touch.get(opp.id), max(rep_times, default=None), quote.sent_at if quote else None)
        last_rep = max([t for t in candidates if t], default=None)
        # Customer is waiting if their messages came after our last reply.
        waiting_since = next(
            (x.sent_at for x in opp_msgs if x.sender_type == SenderType.CUSTOMER and (last_rep is None or x.sent_at > last_rep)),
            None,
        )
        llm_insights, heuristic_texts = [], []
        for c in convs_by_opp[opp.id]:
            insight = analyses.get((c.id, transcript_hash(messages[c.id]))) if messages[c.id] else None
            if insight:
                llm_insights.append(insight)
            else:
                heuristic_texts += [x.body for x in messages[c.id] if x.sender_type == SenderType.CUSTOMER]
        conv_sig = merge_conversation_signals(llm_insights, heuristic_texts, competitors)

        live = bool(quote and quote.status in LIVE_QUOTE_STATUSES)
        expiry_days = None
        if quote and quote.valid_until and quote.status in (*LIVE_QUOTE_STATUSES, QuoteStatus.EXPIRED):
            expiry_days = (quote.valid_until - now.date()).days + 0.0
        deal_value = quote.total if live and quote else opp.amount
        segment = segments.get(opp.customer_id)
        rate, sample = win_rates.get(segment.value if segment else None) or win_rates.get(None, (0.0, 0))
        if sample < 10:
            rate, sample = win_rates.get(None, (0.0, 0))
        reference_time = last_rep or opp.created_at
        signals = RiskSignals(
            stage=opp.stage,
            deal_value=Decimal(deal_value),
            days_since_rep_contact=_days_between(now, reference_time) if reference_time else None,
            customer_waiting_days=_days_between(now, waiting_since) if waiting_since else None,
            live_quote=live,
            days_since_quote=_days_between(now, quote.sent_at) if live and quote and quote.sent_at else None,
            days_to_quote_expiry=expiry_days,
            overdue_followups=overdue.get(opp.id, 0),
            close_date_passed=bool(opp.expected_close_date and opp.expected_close_date < now.date()),
            intent=conv_sig.intent,
            intent_source=conv_sig.intent_source,
            competitor_mentioned=conv_sig.competitor or bool(opp.competitor),
            competitors=conv_sig.competitors or ((opp.competitor,) if opp.competitor else ()),
            competitor_source=conv_sig.competitor_source if conv_sig.competitor else SignalSource.CRM_DATA,
            price_objection=conv_sig.price,
            price_objection_source=conv_sig.price_source,
            sentiment=conv_sig.sentiment,
            sentiment_source=conv_sig.sentiment_source,
            historical_win_rate=rate,
            historical_sample_size=sample,
            evidence=conv_sig.evidence or {},
        )
        result[opp.id] = (opp, signals)
    return result


async def recompute_risks(
    session: AsyncSession,
    company_id: uuid.UUID,
    settings: CompanySettings,
    *,
    now: datetime | None = None,
    opportunity_ids: list[uuid.UUID] | None = None,
) -> list[m.RevenueRisk]:
    """Assess open opportunities and persist results (previous rows kept as history)."""
    now = now or datetime.now(UTC)
    signals = await build_signals(session, company_id, now=now, opportunity_ids=opportunity_ids)
    stale = update(m.RevenueRisk).where(m.RevenueRisk.company_id == company_id, m.RevenueRisk.is_current.is_(True))
    if opportunity_ids:
        stale = stale.where(m.RevenueRisk.opportunity_id.in_(opportunity_ids))
    await session.execute(stale.values(is_current=False))
    rows: list[m.RevenueRisk] = []
    for opp, sig in signals.values():
        a = assess(sig, settings)
        rows.append(to_row(company_id, opp, sig, a, now))
    session.add_all(rows)
    await session.flush()
    return rows


def to_row(company_id: uuid.UUID, opp: m.Opportunity, sig: RiskSignals, a: RiskAssessment, now: datetime) -> m.RevenueRisk:
    return m.RevenueRisk(
        company_id=company_id,
        opportunity_id=opp.id,
        customer_id=opp.customer_id,
        risk_score=a.risk_score,
        risk_level=a.risk_level,
        revenue_at_risk=a.revenue_at_risk,
        weighted_revenue_at_risk=a.weighted_revenue_at_risk,
        purchase_probability=a.purchase_probability,
        reason_codes=[r.as_dict() for r in a.reasons],
        signals={**sig.as_dict(), "probability_breakdown": a.probability_breakdown, "raw_points": a.raw_points},
        recommended_next_step=a.recommended_next_step,
        engine_version=a.engine_version,
        is_current=True,
        computed_at=now,
    )

