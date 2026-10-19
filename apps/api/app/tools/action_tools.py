"""Write tools. Every execution is recorded as an `actions` row and audited by the registry.

Customer-facing / financial tools (send_email, offer_discount) verify — inside the handler, against
the database — that an APPROVED approval request exists for the recommendation. That check does not
depend on the agent graph behaving correctly: even a buggy or prompt-injected caller cannot send an
email or grant a discount without a human decision on record.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.errors import AppError, ErrorCode, NotFoundError
from app.db import models as m
from app.domain.enums import (
    ActionStatus,
    ActionType,
    ActivityType,
    ApprovalStatus,
    FollowupStatus,
    QuoteStatus,
    RecommendationStatus,
    UserRole,
)
from app.tools.base import REGISTRY, Effects, Tool, ToolContext

WRITE = Effects(writes_crm=True, idempotent=False)


async def _opportunity(ctx: ToolContext, opportunity_id: uuid.UUID) -> m.Opportunity:
    opp = await ctx.session.scalar(
        select(m.Opportunity).where(m.Opportunity.id == opportunity_id, m.Opportunity.company_id == ctx.company_id)
    )
    if opp is None:
        raise NotFoundError("opportunity", opportunity_id)
    return opp


async def _recommendation(ctx: ToolContext, recommendation_id: uuid.UUID) -> m.Recommendation:
    rec = await ctx.session.scalar(
        select(m.Recommendation).where(
            m.Recommendation.id == recommendation_id, m.Recommendation.company_id == ctx.company_id
        )
    )
    if rec is None:
        raise NotFoundError("recommendation", recommendation_id)
    return rec


async def require_approved(
    ctx: ToolContext, recommendation_id: uuid.UUID, approval_request_id: uuid.UUID | None
) -> m.ApprovalRequest:
    if approval_request_id is None:
        raise AppError(ErrorCode.APPROVAL_REQUIRED, "This action requires an approved approval request")
    approval = await ctx.session.scalar(
        select(m.ApprovalRequest).where(
            m.ApprovalRequest.id == approval_request_id, m.ApprovalRequest.company_id == ctx.company_id
        )
    )
    if approval is None or approval.recommendation_id != recommendation_id:
        raise AppError(ErrorCode.APPROVAL_REQUIRED, "Approval request not found for this recommendation")
    if approval.status != ApprovalStatus.APPROVED:
        raise AppError(ErrorCode.APPROVAL_REQUIRED, f"Approval request is {approval.status.value}, not approved")
    return approval


def _record_action(
    ctx: ToolContext,
    action_type: ActionType,
    *,
    recommendation_id: uuid.UUID | None,
    approval: m.ApprovalRequest | None,
    input: dict[str, Any],
    result: dict[str, Any],  # noqa: A002
    value: Decimal | None,
    automated: bool,
) -> m.Action:
    action = m.Action(
        company_id=ctx.company_id,
        recommendation_id=recommendation_id,
        approval_request_id=approval.id if approval else None,
        action_type=action_type,
        status=ActionStatus.SUCCEEDED,
        input=input,
        result=result,
        automated=automated,
        executed_by=uuid.UUID(ctx.actor_id) if ctx.actor_id and _is_uuid(ctx.actor_id) else None,
        executed_at=datetime.now(UTC),
        opportunity_value=value,
    )
    ctx.session.add(action)
    return action


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


class ActionOut(BaseModel):
    action_id: str
    action_type: str
    status: str
    customer_id: str
    detail: dict[str, Any]


# --- create_followup / schedule_reminder ------------------------------------------------------------
class FollowupIn(BaseModel):
    opportunity_id: uuid.UUID
    title: str = Field(min_length=3, max_length=200)
    notes: str | None = Field(None, max_length=2000)
    due_in_hours: int = Field(24, ge=1, le=24 * 30)
    recommendation_id: uuid.UUID | None = None
    assign_to_manager: bool = False


async def _create_followup(ctx: ToolContext, a: FollowupIn, action_type: ActionType) -> ActionOut:
    opp = await _opportunity(ctx, a.opportunity_id)
    assignee = opp.owner_id
    if a.assign_to_manager:
        assignee = (
            await ctx.session.scalar(
                select(m.User.id)
                .where(m.User.company_id == ctx.company_id, m.User.role == UserRole.MANAGER, m.User.is_active.is_(True))
                .limit(1)
            )
            or assignee
        )
    followup = m.Followup(
        company_id=ctx.company_id,
        customer_id=opp.customer_id,
        opportunity_id=opp.id,
        assigned_to=assignee,
        title=a.title,
        notes=a.notes,
        due_at=datetime.now(UTC) + timedelta(hours=a.due_in_hours),
        status=FollowupStatus.PENDING,
        created_by_agent=ctx.agent is not None,
        recommendation_id=a.recommendation_id,
    )
    ctx.session.add(followup)
    await ctx.session.flush()
    action = _record_action(
        ctx,
        action_type,
        recommendation_id=a.recommendation_id,
        approval=None,
        input=a.model_dump(mode="json"),
        result={"followup_id": str(followup.id), "due_at": followup.due_at.isoformat()},
        value=opp.amount,
        automated=ctx.agent is not None,
    )
    await ctx.session.flush()
    return ActionOut(
        action_id=str(action.id),
        action_type=action_type.value,
        status=action.status.value,
        customer_id=str(opp.customer_id),
        detail={
            "followup_id": str(followup.id),
            "due_at": followup.due_at.isoformat(),
            "assigned_to": str(assignee) if assignee else None,
        },
    )


async def create_followup(ctx: ToolContext, a: FollowupIn) -> ActionOut:
    return await _create_followup(ctx, a, ActionType.CREATE_FOLLOWUP)


async def escalate_to_manager(ctx: ToolContext, a: FollowupIn) -> ActionOut:
    return await _create_followup(ctx, a.model_copy(update={"assign_to_manager": True}), ActionType.ESCALATE_TO_MANAGER)


# --- log_action ------------------------------------------------------------------------------------
class LogIn(BaseModel):
    opportunity_id: uuid.UUID
    description: str = Field(min_length=3, max_length=1000)
    recommendation_id: uuid.UUID | None = None


async def log_action(ctx: ToolContext, a: LogIn) -> ActionOut:
    opp = await _opportunity(ctx, a.opportunity_id)
    ctx.session.add(
        m.Activity(
            company_id=ctx.company_id,
            customer_id=opp.customer_id,
            opportunity_id=opp.id,
            user_id=None,
            type=ActivityType.AI_ACTION,
            description=a.description,
            occurred_at=datetime.now(UTC),
            metadata_={
                "agent": ctx.agent,
                "recommendation_id": str(a.recommendation_id) if a.recommendation_id else None,
            },
        )
    )
    action = _record_action(
        ctx,
        ActionType.LOG_ACTIVITY,
        recommendation_id=a.recommendation_id,
        approval=None,
        input=a.model_dump(mode="json"),
        result={"logged": True},
        value=None,
        automated=True,
    )
    await ctx.session.flush()
    return ActionOut(
        action_id=str(action.id),
        action_type=ActionType.LOG_ACTIVITY.value,
        status=action.status.value,
        customer_id=str(opp.customer_id),
        detail={"description": a.description},
    )


# --- draft_followup_message ------------------------------------------------------------------------
class DraftIn(BaseModel):
    recommendation_id: uuid.UUID
    subject: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=10, max_length=5000)


async def draft_followup_message(ctx: ToolContext, a: DraftIn) -> ActionOut:
    rec = await _recommendation(ctx, a.recommendation_id)
    rec.draft_subject, rec.draft_body = a.subject, a.body
    action = _record_action(
        ctx,
        ActionType.DRAFT_EMAIL,
        recommendation_id=rec.id,
        approval=None,
        input={"subject": a.subject},
        result={"stored_on_recommendation": True},
        value=None,
        automated=True,
    )
    await ctx.session.flush()
    return ActionOut(
        action_id=str(action.id),
        action_type=ActionType.DRAFT_EMAIL.value,
        status=action.status.value,
        customer_id=str(rec.customer_id),
        detail={"subject": a.subject},
    )


# --- request_human_approval ---------------------------------------------------------------------------
class ApprovalIn(BaseModel):
    recommendation_id: uuid.UUID
    reasons: list[dict[str, Any]] = Field(min_length=1)
    risk_summary: str = Field(min_length=3, max_length=2000)
    required_role: UserRole = UserRole.MANAGER


class ApprovalOut(BaseModel):
    approval_request_id: str
    status: str
    customer_id: str
    required_role: str


async def request_human_approval(ctx: ToolContext, a: ApprovalIn) -> ApprovalOut:
    rec = await _recommendation(ctx, a.recommendation_id)
    existing = await ctx.session.scalar(select(m.ApprovalRequest).where(m.ApprovalRequest.recommendation_id == rec.id))
    if existing is not None:
        return ApprovalOut(
            approval_request_id=str(existing.id),
            status=existing.status.value,
            customer_id=str(rec.customer_id),
            required_role=existing.required_role,
        )
    approval = m.ApprovalRequest(
        company_id=ctx.company_id,
        recommendation_id=rec.id,
        status=ApprovalStatus.PENDING,
        reasons=a.reasons,
        risk_summary=a.risk_summary,
        required_role=a.required_role.value,
    )
    ctx.session.add(approval)
    rec.status = RecommendationStatus.PENDING_APPROVAL
    await ctx.session.flush()
    return ApprovalOut(
        approval_request_id=str(approval.id),
        status=approval.status.value,
        customer_id=str(rec.customer_id),
        required_role=approval.required_role,
    )


# --- send_email (approval-gated, outbox transport) -------------------------------------------------------
class EmailIn(BaseModel):
    recommendation_id: uuid.UUID
    approval_request_id: uuid.UUID | None = None
    to: EmailStr
    subject: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=10, max_length=5000)


async def send_email(ctx: ToolContext, a: EmailIn) -> ActionOut:
    rec = await _recommendation(ctx, a.recommendation_id)
    approval = await require_approved(ctx, rec.id, a.approval_request_id)
    opp = await _opportunity(ctx, rec.opportunity_id)
    # No SMTP integration is configured in this project: messages go to an outbox recorded on the action.
    # This is stated explicitly in the result and the UI; nothing claims the email was delivered.
    result = {
        "transport": "outbox",
        "delivered": False,
        "to": a.to,
        "note": "Recorded in the outbox. No email provider is configured, so nothing was delivered.",
    }
    ctx.session.add(
        m.Activity(
            company_id=ctx.company_id,
            customer_id=opp.customer_id,
            opportunity_id=opp.id,
            user_id=None,
            type=ActivityType.EMAIL,
            description=f"Approved follow-up email queued (outbox): {a.subject}",
            occurred_at=datetime.now(UTC),
            metadata_={"approval_request_id": str(approval.id)},
        )
    )
    action = _record_action(
        ctx,
        ActionType.SEND_EMAIL,
        recommendation_id=rec.id,
        approval=approval,
        input={"to": a.to, "subject": a.subject, "body": a.body},
        result=result,
        value=opp.amount,
        automated=False,
    )
    opp.last_activity_at = datetime.now(UTC)
    await ctx.session.flush()
    return ActionOut(
        action_id=str(action.id),
        action_type=ActionType.SEND_EMAIL.value,
        status=action.status.value,
        customer_id=str(opp.customer_id),
        detail=result,
    )


# --- offer_discount (approval-gated; drafts a revised quote version) -----------------------------------------
class DiscountIn(BaseModel):
    recommendation_id: uuid.UUID
    approval_request_id: uuid.UUID | None = None
    discount_pct: Decimal = Field(gt=0, le=100)


async def offer_discount(ctx: ToolContext, a: DiscountIn) -> ActionOut:
    rec = await _recommendation(ctx, a.recommendation_id)
    approval = await require_approved(ctx, rec.id, a.approval_request_id)
    opp = await _opportunity(ctx, rec.opportunity_id)
    quote = await ctx.session.scalar(
        select(m.Quote)
        .options(selectinload(m.Quote.items))
        .where(m.Quote.opportunity_id == opp.id)
        .order_by(m.Quote.version.desc())
        .limit(1)
    )
    if quote is None:
        raise AppError(ErrorCode.CONFLICT, "Opportunity has no quotation to revise")
    revised = m.Quote(
        company_id=ctx.company_id,
        opportunity_id=opp.id,
        customer_id=opp.customer_id,
        quote_number=f"{quote.quote_number}-R{quote.version + 1}",
        version=quote.version + 1,
        status=QuoteStatus.DRAFT,
        subtotal=quote.subtotal,
        discount_pct=a.discount_pct,
        tax_pct=quote.tax_pct,
        total=(quote.subtotal * (1 - a.discount_pct / 100)).quantize(Decimal("1"), ROUND_HALF_UP),
        currency=quote.currency,
        valid_until=(datetime.now(UTC) + timedelta(days=30)).date(),
        is_synthetic=quote.is_synthetic,
    )
    ctx.session.add(revised)
    await ctx.session.flush()
    for item in quote.items:
        ctx.session.add(
            m.QuoteItem(
                quote_id=revised.id,
                position=item.position,
                sku=item.sku,
                description=item.description,
                quantity=item.quantity,
                unit_price=item.unit_price,
                discount_pct=item.discount_pct,
                line_total=item.line_total,
            )
        )
    result = {
        "revised_quote_id": str(revised.id),
        "quote_number": revised.quote_number,
        "discount_pct": float(a.discount_pct),
        "new_total": float(revised.total),
        "status": "draft (not sent to customer)",
    }
    action = _record_action(
        ctx,
        ActionType.OFFER_DISCOUNT,
        recommendation_id=rec.id,
        approval=approval,
        input={"discount_pct": float(a.discount_pct)},
        result=result,
        value=opp.amount,
        automated=False,
    )
    await ctx.session.flush()
    return ActionOut(
        action_id=str(action.id),
        action_type=ActionType.OFFER_DISCOUNT.value,
        status=action.status.value,
        customer_id=str(opp.customer_id),
        detail=result,
    )


# --- update_crm (narrow allow-list) -----------------------------------------------------------------------
class UpdateCrmIn(BaseModel):
    opportunity_id: uuid.UUID
    expected_close_date: datetime | None = None
    competitor: str | None = Field(None, max_length=120)
    recommendation_id: uuid.UUID | None = None


async def update_crm(ctx: ToolContext, a: UpdateCrmIn) -> ActionOut:
    opp = await _opportunity(ctx, a.opportunity_id)
    changes: dict[str, Any] = {}
    if a.expected_close_date:
        changes["expected_close_date"] = [str(opp.expected_close_date), a.expected_close_date.date().isoformat()]
        opp.expected_close_date = a.expected_close_date.date()
    if a.competitor:
        changes["competitor"] = [opp.competitor, a.competitor]
        opp.competitor = a.competitor
    if not changes:
        raise AppError(ErrorCode.INVALID_REQUEST, "No allowed field to update (expected_close_date, competitor)")
    action = _record_action(
        ctx,
        ActionType.UPDATE_CRM,
        recommendation_id=a.recommendation_id,
        approval=None,
        input=a.model_dump(mode="json"),
        result={"changes": changes},
        value=opp.amount,
        automated=ctx.agent is not None,
    )
    await ctx.session.flush()
    return ActionOut(
        action_id=str(action.id),
        action_type=ActionType.UPDATE_CRM.value,
        status=action.status.value,
        customer_id=str(opp.customer_id),
        detail={"changes": changes},
    )


for _tool in (
    Tool(
        "create_followup",
        "Create follow-up task",
        "Create an internal follow-up task for the deal owner (low risk, internal).",
        FollowupIn,
        ActionOut,
        create_followup,
        effects=WRITE,
        mcp_name="revenue.create_followup",
    ),
    Tool(
        "escalate_to_manager",
        "Escalate to manager",
        "Create a follow-up task assigned to the sales manager.",
        FollowupIn,
        ActionOut,
        escalate_to_manager,
        effects=WRITE,
    ),
    Tool(
        "log_action",
        "Log activity",
        "Record an AI action on the deal timeline.",
        LogIn,
        ActionOut,
        log_action,
        effects=WRITE,
    ),
    Tool(
        "draft_followup_message",
        "Store draft message",
        "Store a drafted follow-up email on a recommendation (not sent).",
        DraftIn,
        ActionOut,
        draft_followup_message,
        effects=WRITE,
    ),
    Tool(
        "request_human_approval",
        "Request human approval",
        "Open an approval request for a recommendation.",
        ApprovalIn,
        ApprovalOut,
        request_human_approval,
        effects=Effects(writes_crm=True, idempotent=True),
        mcp_name="revenue.request_approval",
    ),
    Tool(
        "send_email",
        "Send email",
        "Send an approved follow-up email (requires an approved approval request).",
        EmailIn,
        ActionOut,
        send_email,
        effects=Effects(writes_crm=True, customer_facing=True, idempotent=False),
    ),
    Tool(
        "offer_discount",
        "Offer discount",
        "Draft a revised quotation with an approved discount (requires approval).",
        DiscountIn,
        ActionOut,
        offer_discount,
        effects=Effects(writes_crm=True, financial=True, customer_facing=True, idempotent=False),
    ),
    Tool(
        "update_crm",
        "Update CRM",
        "Update allowed opportunity fields (expected close date, competitor).",
        UpdateCrmIn,
        ActionOut,
        update_crm,
        effects=WRITE,
    ),
):
    REGISTRY.register(_tool)
