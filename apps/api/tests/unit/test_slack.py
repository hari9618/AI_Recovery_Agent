import json
import uuid
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import get_settings
from app.integrations import slack
from app.integrations.slack import DealContext, approval_decided_message, approval_requested_message, inr

WEBHOOK = "https://hooks.slack.com/services/T000/B000/XXXX"


def deal(**overrides) -> DealContext:
    base = dict(
        customer_id=uuid.uuid4(),
        customer_name="Vertex Industrial Solutions Pvt Ltd",
        opportunity_name="Vertex — Plant-wide monitoring",
        deal_value=Decimal("480000"),
        stage="negotiation",
        owner="Priya Nair",
        risk_score=94,
        risk_level="critical",
        reasons=["Customer has been waiting 5 days for a reply", "No follow-up for 7 days"],
        contact_name="Nikhil Rao",
        contact_title="Plant Head",
        contact_phone="+91 98450 12345",
    )
    return DealContext(**(base | overrides))


def requested(d: DealContext, **kw):
    args = dict(
        title="Send prompt email",
        recommendation="Reply today and ask for the competitor's written quote.",
        subject="Re: pricing",
        body="Hi Nikhil,\n\nThanks for sharing your budget.\n\nBest,\nPriya",
        required_role="manager",
        rules=["HIGH_VALUE_CUSTOMER_FACING"],
        confidence=0.92,
        grounding={"total": 4, "supported": 4},
        approval_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        app_url="http://localhost:3100",
    )
    return approval_requested_message(d, **(args | kw))


def text_of(message) -> str:
    return json.dumps(message, ensure_ascii=False)


def test_inr_uses_indian_grouping():
    assert inr(480000) == "₹4,80,000"
    assert inr(Decimal("65980000")) == "₹6,59,80,000"
    assert inr(999) == "₹999"


def test_approval_message_has_deal_reasons_contact_draft_and_links():
    d = deal()
    msg = requested(d)
    body = text_of(msg)
    assert msg["blocks"][0]["text"]["text"] == "🔴 Deal at risk: Vertex Industrial Solutions Pvt Ltd"
    for expected in (
        "₹4,80,000",
        "94/100 Critical",
        "Priya Nair",
        "+91 98450 12345",
        "waiting 5 days",
        "4/4 policy claims verified",
    ):
        assert expected in body
    assert ">Hi Nikhil," in body  # draft quoted
    urls = [e["url"] for b in msg["blocks"] if b["type"] == "actions" for e in b["elements"]]
    assert urls[0] == "http://localhost:3100/approvals"
    assert urls[1] == f"http://localhost:3100/customers/{d.customer_id}"
    assert all(len(b["text"]["text"]) <= 3000 for b in msg["blocks"] if b["type"] == "section" and "text" in b)


def test_untrusted_text_cannot_mention_or_link():
    msg = requested(deal(customer_name="Acme <!channel>"), body="Click <https://evil.example|here> & pay")
    body = text_of(msg)
    assert "<!channel>" not in body and "‹!channel›" in body
    assert "<https://evil" not in body and "&amp; pay" in body


def test_long_email_is_clipped_within_slack_limits():
    msg = requested(deal(), body="word " * 2000)
    for b in msg["blocks"]:
        if b["type"] == "section" and "text" in b:
            assert len(b["text"]["text"]) <= 3000


def test_decided_message_is_honest_about_outbox_and_rejections():
    execution = {
        "ok": True,
        "results": [
            {"tool": "send_email", "ok": True, "data": {"detail": {"to": "nikhil@vertex.in", "delivered": False}}}
        ],
    }
    approved = text_of(
        approval_decided_message(
            deal(),
            decision="approve",
            decided_by="Meera Raghavan",
            note=None,
            subject="Re",
            body="Hi",
            edited=True,
            execution=execution,
            app_url="http://x",
        )
    )
    assert "approved (with edits)" in approved and "outbox" in approved and "no email provider" in approved
    assert "+91 98450 12345" in approved  # nudge to call
    rejected = text_of(
        approval_decided_message(
            deal(),
            decision="reject",
            decided_by="Meera",
            note="Too early",
            subject=None,
            body=None,
            edited=False,
            execution=None,
            app_url="http://x",
        )
    )
    assert "rejected" in rejected and "Nothing was sent" in rejected and "Too early" in rejected


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(get_settings(), "slack_webhook_url", SecretStr(WEBHOOK))
    yield
    slack.set_slack_transport(None)


async def test_post_is_skipped_when_not_configured(monkeypatch):
    monkeypatch.setattr(get_settings(), "slack_webhook_url", None)
    out = await slack.post_to_slack({"text": "hi"})
    assert out.skipped and not out.ok


async def test_post_refuses_non_slack_hosts(monkeypatch):
    monkeypatch.setattr(get_settings(), "slack_webhook_url", SecretStr("https://attacker.example/hook"))
    out = await slack.post_to_slack({"text": "hi"})
    assert not out.ok and "hooks.slack.com" in out.error


async def test_post_success_and_failure_never_raise(configured):
    seen = []

    def ok(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), json.loads(request.content)))
        return httpx.Response(200, text="ok")

    slack.set_slack_transport(httpx.MockTransport(ok))
    assert (await slack.post_to_slack({"text": "hi"})).ok
    assert seen == [(WEBHOOK, {"text": "hi"})]

    slack.set_slack_transport(httpx.MockTransport(lambda r: httpx.Response(404, text="no_service")))
    bad = await slack.post_to_slack({"text": "hi"})
    assert not bad.ok and bad.status == 404 and "no_service" in bad.error

    def boom(request):
        raise httpx.ConnectError("down")

    slack.set_slack_transport(httpx.MockTransport(boom))
    down = await slack.post_to_slack({"text": "hi"})
    assert not down.ok and "ConnectError" in down.error
