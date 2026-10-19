"""Isolated evaluation tenant and scenario materialisation.

Evaluations never touch the demo tenant: they run inside a dedicated "Eval Sandbox" company (rebuilt per
run), so tenant isolation keeps eval records out of the demo dashboards.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import REPO_ROOT
from app.db import models as m
from app.domain.enums import (
    ActivityType,
    Channel,
    CustomerSegment,
    CustomerStatus,
    FollowupStatus,
    OpportunityStage,
    QuoteStatus,
    SenderType,
    UserRole,
)
from app.rag.ingestion import ingest_directory
from app.rag.models import Embedder
from app.rag.retriever import BM25_CACHE
from app.security.auth import Principal
from app.services.text import normalize_company_name

SANDBOX_MARKER = {"eval_sandbox": True}


@dataclass
class Sandbox:
    company_id: uuid.UUID
    principals: dict[str, Principal]
    rep_id: uuid.UUID


async def create_sandbox(session: AsyncSession, embedder: Embedder) -> Sandbox:
    old = (
        await session.scalars(select(m.Company.id).where(m.Company.settings["eval_sandbox"].as_boolean().is_(True)))
    ).all()
    if old:
        await session.execute(delete(m.Company).where(m.Company.id.in_(old)))
    company = m.Company(
        name="Eval Sandbox (synthetic)", industry="Evaluation", currency="INR", settings=SANDBOX_MARKER, is_demo=False
    )
    session.add(company)
    await session.flush()
    principals: dict[str, Principal] = {}
    for role, name in (
        (UserRole.OWNER, "Eval Owner"),
        (UserRole.MANAGER, "Eval Manager"),
        (UserRole.SALES_REP, "Eval Rep"),
    ):
        user = m.User(company_id=company.id, email=f"{role.value}@eval.sandbox", full_name=name, role=role)
        session.add(user)
        await session.flush()
        principals[role.value] = Principal(user.id, company.id, role, name)
    await ingest_directory(session, embedder, company_id=company.id, directory=REPO_ROOT / "data" / "knowledge")
    await session.commit()
    BM25_CACHE.clear()
    return Sandbox(company.id, principals, principals["sales_rep"].user_id)


async def set_knowledge_active(session: AsyncSession, company_id: uuid.UUID, active: bool) -> None:
    await session.execute(update(m.Document).where(m.Document.company_id == company_id).values(is_active=active))
    await session.commit()
    BM25_CACHE.clear()


async def materialise(session: AsyncSession, sandbox: Sandbox, key: str, spec: dict[str, Any]) -> dict[str, Any]:
    """Create customer, contact, opportunity, quote, conversation and follow-ups for one scenario."""
    now = datetime.now(UTC)
    cid = sandbox.company_id
    name = f"Eval {key.replace('_', ' ').title()} Pvt Ltd"
    customer = m.Customer(
        company_id=cid,
        name=name,
        normalized_name=normalize_company_name(name),
        industry="Manufacturing",
        segment=CustomerSegment.MID_MARKET,
        status=CustomerStatus.PROSPECT,
        city="Pune",
        owner_id=sandbox.rep_id,
        is_synthetic=True,
    )
    session.add(customer)
    await session.flush()
    contact = m.Contact(
        company_id=cid,
        customer_id=customer.id,
        full_name="Ritu Sharma",
        title="Plant Head",
        is_decision_maker=True,
        email=f"ritu.sharma@{key.replace('_', '-')[:40]}.example.in" if spec["has_contact_email"] else None,
    )
    session.add(contact)
    await session.flush()
    stage = OpportunityStage(spec["stage"])
    quote_sent = now - timedelta(days=spec["days_since_quote"])
    opp = m.Opportunity(
        company_id=cid,
        customer_id=customer.id,
        owner_id=sandbox.rep_id,
        primary_contact_id=contact.id,
        name=f"{name} — monitoring rollout",
        stage=stage,
        amount=Decimal(spec["amount"]),
        expected_close_date=(now + timedelta(days=20)).date(),
        last_activity_at=quote_sent,
        stage_changed_at=quote_sent,
        closed_at=now if not stage.is_open else None,
        is_synthetic=True,
    )
    session.add(opp)
    await session.flush()
    valid_until = (quote_sent + timedelta(days=spec["quote_valid_days"])).date()
    status = QuoteStatus.EXPIRED if valid_until < now.date() else QuoteStatus.SENT
    quote = m.Quote(
        company_id=cid,
        opportunity_id=opp.id,
        customer_id=customer.id,
        quote_number=f"EV-{uuid.uuid4().hex[:8].upper()}",
        status=status,
        subtotal=Decimal(spec["amount"]),
        discount_pct=Decimal("0"),
        total=Decimal(spec["amount"]),
        sent_at=quote_sent,
        valid_until=valid_until,
        is_synthetic=True,
    )
    session.add(quote)
    await session.flush()
    session.add(
        m.QuoteItem(
            quote_id=quote.id,
            position=1,
            sku="PULSE-STD",
            description="Arcline Pulse Platform",
            quantity=Decimal(1),
            unit_price=Decimal(spec["amount"]),
            line_total=Decimal(spec["amount"]),
        )
    )
    conv = m.Conversation(
        company_id=cid,
        customer_id=customer.id,
        opportunity_id=opp.id,
        contact_id=contact.id,
        channel=Channel.EMAIL,
        subject="Quotation",
        started_at=quote_sent,
        last_message_at=quote_sent,
        last_sender=SenderType.REP,
        is_synthetic=True,
    )
    session.add(conv)
    await session.flush()
    session.add(
        m.ConversationMessage(
            conversation_id=conv.id,
            sender_type=SenderType.REP,
            sender_name="Eval Rep",
            body=f"Hi Ritu, sharing quotation {quote.quote_number} for the monitoring rollout.",
            sent_at=quote_sent,
        )
    )
    session.add(
        m.Activity(
            company_id=cid,
            customer_id=customer.id,
            opportunity_id=opp.id,
            user_id=sandbox.rep_id,
            type=ActivityType.QUOTE_SENT,
            description="Quotation sent",
            occurred_at=quote_sent,
        )
    )
    waiting = spec.get("customer_waiting_days")
    customer_at = now - timedelta(days=waiting) if waiting is not None else quote_sent + timedelta(hours=6)
    customer_at = max(customer_at, quote_sent + timedelta(minutes=5))
    session.add(
        m.ConversationMessage(
            conversation_id=conv.id,
            sender_type=SenderType.CUSTOMER,
            sender_name="Ritu Sharma",
            body=spec["customer_message"],
            sent_at=customer_at,
        )
    )
    conv.last_message_at, conv.last_sender = customer_at, SenderType.CUSTOMER
    if waiting is None:  # the rep answered after the customer's message
        reply_at = min(customer_at + timedelta(hours=3), now - timedelta(minutes=30))
        session.add(
            m.ConversationMessage(
                conversation_id=conv.id,
                sender_type=SenderType.REP,
                sender_name="Eval Rep",
                body="Thanks Ritu, happy to help. I'll call you tomorrow to go through it.",
                sent_at=reply_at,
            )
        )
        session.add(
            m.Activity(
                company_id=cid,
                customer_id=customer.id,
                opportunity_id=opp.id,
                user_id=sandbox.rep_id,
                type=ActivityType.EMAIL,
                description="Reply to customer",
                occurred_at=reply_at,
            )
        )
        conv.last_message_at, conv.last_sender = reply_at, SenderType.REP
    for i in range(spec.get("overdue_followups", 0)):
        session.add(
            m.Followup(
                company_id=cid,
                customer_id=customer.id,
                opportunity_id=opp.id,
                assigned_to=sandbox.rep_id,
                title=f"Follow up #{i + 1}",
                due_at=now - timedelta(days=1 + i),
                status=FollowupStatus.PENDING,
            )
        )
    await session.commit()
    return {
        "customer_id": customer.id,
        "opportunity_id": opp.id,
        "quote_id": quote.id,
        "conversation_id": conv.id,
        "customer_message": spec["customer_message"],
    }
