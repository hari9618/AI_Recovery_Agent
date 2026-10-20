"""Slack notifications for the sales team, through an incoming webhook.

Two moments are posted:

1. **Approval needed**: the agent investigated an at-risk deal and drafted a customer email that a human
   must approve. The message carries the deal, why it is at risk, who to call and the draft, with links
   into the app to review it.
2. **Decision made**: someone approved (the email is released) or rejected the recommendation.

Same rule as tracing: Slack is secondary to the business workflow. Every post is best-effort, bounded by
a timeout and never raises; its outcome is written to the audit log. Text that came from customers or the
model is escaped for Slack mrkdwn, so it cannot ping `@channel` or forge links.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select

from app.core.config import get_settings
from app.db import models as m
from app.db.session import get_sessionmaker
from app.domain.enums import ActorType, AuditResult
from app.services.audit import record_audit

logger = logging.getLogger(__name__)

WEBHOOK_PREFIX = "https://hooks.slack.com/"
MAX_SECTION = 2900  # Slack's limit is 3000 characters per section text
RISK_EMOJI = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}

_transport_override: httpx.AsyncBaseTransport | None = None


def set_slack_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Tests inject an `httpx.MockTransport` here; production uses the network."""
    global _transport_override  # noqa: PLW0603
    _transport_override = transport


@dataclass
class SlackDelivery:
    ok: bool
    status: int | None = None
    error: str | None = None
    skipped: bool = False


# ------------------------------------------------------------------------------------------- formatting
def escape(text: str | None) -> str:
    """Escape for Slack mrkdwn: `&`, `<`, `>` are the only control characters (mentions, links)."""
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def plain(text: str | None) -> str:
    """For plain_text fields and notification fallbacks: drop the angle brackets Slack uses for mentions."""
    return (text or "").replace("<", "‹").replace(">", "›")


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def inr(value: Decimal | float | int | None) -> str:
    """Indian digit grouping: 480000 -> ₹4,80,000."""
    if value is None:
        return "—"
    digits = str(int(Decimal(str(value))))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        head = re.sub(r"(\d)(?=(\d{2})+$)", r"\1,", head)
        digits = f"{head},{tail}"
    return f"₹{digits}"


def _quote(text: str, limit: int = 1800) -> str:
    return "\n".join(f">{line}" if line.strip() else ">" for line in _clip(escape(text), limit).splitlines())


def _link(app_url: str, path: str) -> str:
    return f"{app_url.rstrip('/')}{path}"


@dataclass
class DealContext:
    customer_id: uuid.UUID
    customer_name: str
    opportunity_name: str
    deal_value: Decimal
    stage: str
    owner: str | None = None
    risk_score: int | None = None
    risk_level: str | None = None
    reasons: list[str] = field(default_factory=list)
    contact_name: str | None = None
    contact_title: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None


def _deal_fields(deal: DealContext) -> list[dict[str, str]]:
    risk = (
        f"{deal.risk_score}/100 {deal.risk_level.title()}" if deal.risk_score is not None and deal.risk_level else "—"
    )
    contact = escape(deal.contact_name or "—")
    if deal.contact_title:
        contact += f", {escape(deal.contact_title)}"
    if deal.contact_phone:
        contact += f"\n📞 {escape(deal.contact_phone)}"
    return [
        {"type": "mrkdwn", "text": f"*Deal value*\n{inr(deal.deal_value)}"},
        {"type": "mrkdwn", "text": f"*Risk*\n{risk}"},
        {
            "type": "mrkdwn",
            "text": f"*Owner*\n{escape(deal.owner or 'Unassigned')} · {escape(deal.stage.replace('_', ' '))}",
        },
        {"type": "mrkdwn", "text": f"*Who to call*\n{contact}"},
    ]


def approval_requested_message(
    deal: DealContext,
    *,
    title: str,
    recommendation: str,
    subject: str | None,
    body: str | None,
    required_role: str,
    rules: list[str],
    confidence: float | None,
    grounding: dict[str, Any],
    approval_id: uuid.UUID,
    run_id: uuid.UUID | None,
    app_url: str,
) -> dict[str, Any]:
    emoji = RISK_EMOJI.get(deal.risk_level or "", "⚠️")
    header = _clip(f"{emoji} Deal at risk: {plain(deal.customer_name)}", 150)
    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": header, "emoji": True}},
        {"type": "section", "fields": _deal_fields(deal)},
    ]
    if deal.reasons:
        why = "\n".join(f"• {escape(r)}" for r in deal.reasons[:4])
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*Why it's at risk*\n{why}"}})
    blocks.append(
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": _clip(f"*🤖 AI recommendation: {escape(title)}*\n{escape(recommendation)}", MAX_SECTION),
            },
        }
    )
    if body:
        email = (
            f"*✉️ Draft email (not sent until approved)*\n*Subject:* {escape(subject or '(no subject)')}\n{_quote(body)}"
        )
        blocks += [
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn", "text": _clip(email, MAX_SECTION)}},
        ]
    verified = ""
    if grounding.get("total"):
        verified = f" · {grounding.get('supported', 0)}/{grounding['total']} policy claims verified"
    conf = f" · confidence {round(confidence * 100)}%" if confidence is not None else ""
    rule_text = ", ".join(escape(r) for r in rules[:3])
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": _clip(
                        f"Needs a *{escape(required_role.replace('_', ' '))}* to approve ({rule_text}){verified}{conf}",
                        1900,
                    ),
                }
            ],
        }
    )
    buttons: list[dict[str, Any]] = [
        {
            "type": "button",
            "style": "primary",
            "text": {"type": "plain_text", "text": "Review & approve"},
            "url": _link(app_url, "/approvals"),
            "action_id": f"review-{approval_id}",
        },
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Customer profile"},
            "url": _link(app_url, f"/customers/{deal.customer_id}"),
            "action_id": f"customer-{deal.customer_id}",
        },
    ]
    if run_id:
        buttons.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "What the agent did"},
                "url": _link(app_url, f"/agent-runs/{run_id}"),
                "action_id": f"run-{run_id}",
            }
        )
    blocks.append({"type": "actions", "elements": buttons})
    fallback = (
        f"{plain(deal.customer_name)}: {inr(deal.deal_value)} at risk. AI drafted a follow-up that needs approval."
    )
    return {"text": fallback, "blocks": blocks}


def _executed_lines(execution: dict[str, Any] | None) -> tuple[list[str], bool]:
    """Human-readable outcome of each tool the execution graph ran, and whether all succeeded."""
    lines: list[str] = []
    ok = bool(execution and execution.get("ok"))
    for r in (execution or {}).get("results", []):
        detail = ((r.get("data") or {}).get("detail")) or {}
        if not r.get("ok"):
            msg = (r.get("error") or {}).get("message", "failed")
            lines.append(f"❌ {escape(r.get('tool', 'action'))}: {escape(msg)}")
        elif r.get("tool") == "send_email":
            to = escape(str(detail.get("to", "")))
            if detail.get("delivered"):
                lines.append(f"✅ Email sent to {to}")
            else:
                lines.append(f"✅ Email released to the outbox for {to} (no email provider connected yet)")
        elif r.get("tool") == "offer_discount":
            lines.append(
                f"✅ Revised quote {escape(str(detail.get('quote_number', '')))} drafted at "
                f"{detail.get('discount_pct')}% off · new total {inr(detail.get('new_total'))}"
            )
        elif r.get("tool") == "escalate_to_manager":
            lines.append("✅ Escalated to the sales manager")
        else:
            lines.append(f"✅ {escape(str(r.get('tool', 'action')).replace('_', ' '))}")
    return lines, ok


def approval_decided_message(
    deal: DealContext,
    *,
    decision: str,
    decided_by: str,
    note: str | None,
    subject: str | None,
    body: str | None,
    edited: bool,
    execution: dict[str, Any] | None,
    app_url: str,
) -> dict[str, Any]:
    if decision == "reject":
        text = f"❌ *{escape(decided_by)}* rejected the AI recommendation for *{escape(deal.customer_name)}*. Nothing was sent."
        if note:
            text += f"\n>{escape(_clip(note, 500))}"
        blocks: list[dict[str, Any]] = [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
        return {"text": plain(f"Recommendation for {deal.customer_name} rejected by {decided_by}"), "blocks": blocks}

    lines, ok = _executed_lines(execution)
    head = "✅" if ok else "⚠️"
    verb = "approved (with edits)" if edited else "approved"
    text = f"{head} *{escape(decided_by)}* {verb} the follow-up for *{escape(deal.customer_name)}* ({inr(deal.deal_value)})."
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
    if lines:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": _clip("\n".join(lines), MAX_SECTION)}})
    if body:
        email = f"*Subject:* {escape(subject or '(no subject)')}\n{_quote(body, 1500)}"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": _clip(email, MAX_SECTION)}})
    nudge = f"Next: {escape(deal.owner or 'the deal owner')}, follow up with a call"
    if deal.contact_name:
        nudge += f" to {escape(deal.contact_name)}"
        if deal.contact_phone:
            nudge += f" ({escape(deal.contact_phone)})"
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": _clip(nudge + ".", 1900)}]})
    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Open customer"},
                    "url": _link(app_url, f"/customers/{deal.customer_id}"),
                    "action_id": f"customer-{deal.customer_id}",
                }
            ],
        }
    )
    fallback = plain(f"{deal.customer_name}: follow-up {verb} by {decided_by}")
    return {"text": fallback, "blocks": blocks}


def test_message(company_name: str, app_url: str) -> dict[str, Any]:
    text = (
        f"👋 *Revenue Recovery is connected to this channel* for *{escape(company_name)}*.\n"
        "You'll get a message when the AI agent drafts a follow-up that needs approval, and another when someone decides."
    )
    return {
        "text": "Revenue Recovery is connected",
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": text}},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Open dashboard"},
                        "url": _link(app_url, "/dashboard"),
                        "action_id": "open-dashboard",
                    }
                ],
            },
        ],
    }


# ------------------------------------------------------------------------------------------- transport
async def post_to_slack(message: dict[str, Any]) -> SlackDelivery:
    settings = get_settings()
    if not settings.slack_configured:
        return SlackDelivery(ok=False, error="SLACK_WEBHOOK_URL is not set", skipped=True)
    url = settings.slack_webhook_url.get_secret_value().strip()  # type: ignore[union-attr]
    if not url.startswith(WEBHOOK_PREFIX):
        # Never post CRM data to an arbitrary host because of a typo or a tampered setting.
        return SlackDelivery(ok=False, error=f"SLACK_WEBHOOK_URL must start with {WEBHOOK_PREFIX}")
    try:
        async with httpx.AsyncClient(timeout=settings.slack_timeout_seconds, transport=_transport_override) as client:
            response = await client.post(url, json=message)
    except httpx.HTTPError as exc:
        logger.warning("slack post failed", extra={"error": exc.__class__.__name__})
        return SlackDelivery(ok=False, error=f"Slack unreachable: {exc.__class__.__name__}")
    if response.status_code == 200:
        return SlackDelivery(ok=True, status=200)
    return SlackDelivery(
        ok=False, status=response.status_code, error=f"Slack returned {response.status_code}: {response.text[:200]}"
    )


# ------------------------------------------------------------------------------------------- workflow hooks
async def _deal_context(session: Any, rec: m.Recommendation) -> DealContext:
    opp = await session.get(m.Opportunity, rec.opportunity_id)
    customer = await session.get(m.Customer, rec.customer_id)
    owner = await session.get(m.User, opp.owner_id) if opp and opp.owner_id else None
    contact = await session.get(m.Contact, opp.primary_contact_id) if opp and opp.primary_contact_id else None
    if contact is None and customer is not None:
        contact = await session.scalar(
            select(m.Contact)
            .where(m.Contact.customer_id == customer.id)
            .order_by(m.Contact.is_decision_maker.desc())
            .limit(1)
        )
    risk = await session.scalar(
        select(m.RevenueRisk)
        .where(m.RevenueRisk.opportunity_id == rec.opportunity_id, m.RevenueRisk.is_current.is_(True))
        .limit(1)
    )
    return DealContext(
        customer_id=rec.customer_id,
        customer_name=customer.name if customer else "Unknown customer",
        opportunity_name=opp.name if opp else "",
        deal_value=opp.amount if opp else Decimal("0"),
        stage=opp.stage.value if opp else "",
        owner=owner.full_name if owner else None,
        risk_score=risk.risk_score if risk else None,
        risk_level=risk.risk_level.value if risk else None,
        reasons=[r.get("label", "") for r in (risk.reason_codes if risk else [])],
        contact_name=contact.full_name if contact else None,
        contact_title=contact.title if contact else None,
        contact_phone=contact.phone if contact else None,
        contact_email=contact.email if contact else None,
    )


async def _send_and_audit(
    session: Any, rec: m.Recommendation, approval_id: uuid.UUID, kind: str, message: dict[str, Any]
) -> SlackDelivery:
    delivery = await post_to_slack(message)
    if delivery.skipped:
        return delivery
    record_audit(
        session,
        company_id=rec.company_id,
        action="slack.notified",
        actor_type=ActorType.SYSTEM,
        actor_name="Slack",
        entity_type="approval_request",
        entity_id=approval_id,
        customer_id=rec.customer_id,
        tool="slack_webhook",
        input={"kind": kind},
        output={"status": delivery.status, "error": delivery.error},
        approval_request_id=approval_id,
        agent_run_id=rec.agent_run_id,
        result=AuditResult.SUCCESS if delivery.ok else AuditResult.FAILURE,
    )
    await session.commit()
    return delivery


async def notify_approval_requested(approval_id: uuid.UUID) -> SlackDelivery:
    """Post the 'approval needed' alert. Never raises."""
    settings = get_settings()
    if not settings.slack_configured:
        return SlackDelivery(ok=False, error="SLACK_WEBHOOK_URL is not set", skipped=True)
    try:
        async with get_sessionmaker()() as session:
            approval = await session.get(m.ApprovalRequest, approval_id)
            rec = await session.get(m.Recommendation, approval.recommendation_id) if approval else None
            if approval is None or rec is None:
                return SlackDelivery(ok=False, error="approval not found")
            deal = await _deal_context(session, rec)
            message = approval_requested_message(
                deal,
                title=rec.title,
                recommendation=rec.recommendation,
                subject=rec.draft_subject,
                body=rec.draft_body,
                required_role=approval.required_role,
                rules=[r.get("rule", "") for r in approval.reasons or []],
                confidence=rec.confidence,
                grounding=rec.grounding or {},
                approval_id=approval.id,
                run_id=rec.agent_run_id,
                app_url=settings.app_public_url,
            )
            return await _send_and_audit(session, rec, approval.id, "approval_requested", message)
    except Exception as exc:  # noqa: BLE001 - notifications must never break the workflow
        logger.warning("slack approval_requested notification failed", exc_info=True)
        return SlackDelivery(ok=False, error=exc.__class__.__name__)


async def notify_approval_decided(
    approval_id: uuid.UUID, *, decision: str, decided_by: str, execution: dict[str, Any] | None = None
) -> SlackDelivery:
    """Post the outcome of a human decision. Never raises."""
    settings = get_settings()
    if not settings.slack_configured:
        return SlackDelivery(ok=False, error="SLACK_WEBHOOK_URL is not set", skipped=True)
    try:
        async with get_sessionmaker()() as session:
            approval = await session.get(m.ApprovalRequest, approval_id)
            rec = await session.get(m.Recommendation, approval.recommendation_id) if approval else None
            if approval is None or rec is None:
                return SlackDelivery(ok=False, error="approval not found")
            deal = await _deal_context(session, rec)
            message = approval_decided_message(
                deal,
                decision=decision,
                decided_by=decided_by,
                note=approval.decision_note,
                subject=rec.draft_subject,
                body=rec.draft_body if decision == "approve" else None,
                edited=bool(approval.edited_payload),
                execution=execution,
                app_url=settings.app_public_url,
            )
            return await _send_and_audit(session, rec, approval.id, f"approval_{decision}", message)
    except Exception as exc:  # noqa: BLE001 - notifications must never break the workflow
        logger.warning("slack approval_decided notification failed", exc_info=True)
        return SlackDelivery(ok=False, error=exc.__class__.__name__)
