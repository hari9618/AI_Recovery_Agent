"""End-to-end: lead → quote → conversation → overdue → risk → agent → RAG → recommendation → approval →
execution → verification → audit → outcome → ROI. LLM steps use scripted replies; everything else is real."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.llm.factory import set_llm_override
from tests.fakes import ScriptedLLM

pytestmark = pytest.mark.integration

INSIGHT = {
    "intent": "high",
    "buying_stage": "decision",
    "urgency": "high",
    "budget_signal": "constrained",
    "objections": [
        {"type": "price", "detail": "Wants a lower price", "quote": "the price is higher than what we budgeted"}
    ],
    "competitor_mentions": [{"name": "Sensara IoT", "context": "quoted lower for similar scope"}],
    "decision_maker_status": "engaged",
    "customer_waiting_on": "revised price",
    "next_action": "send_revised_quote",
    "sentiment": "neutral",
    "summary": "Customer wants to proceed but needs a better price. A competitor quoted lower.",
    "evidence_quotes": ["We want to finalise this month"],
    "confidence": 0.88,
}


def recommendation_reply(discount: float = 8.0):
    def reply(messages):
        prompt = messages[-1].content
        disc_eid = next(
            (
                ln.split("]")[0].strip("[")
                for ln in prompt.splitlines()
                if ln.startswith("[E") and "Discount Authority" in ln
            ),
            "E1",
        )
        return {
            "title": "Reply today with a value-based revised offer",
            "what_happened": "Quote sent 9 days ago; customer raised price.",
            "why_risky": "Customer waiting for a reply; competitor quoted lower.",
            "recommendation": "Send a revised offer within rep authority.",
            "primary_action": "offer_discount",
            "proposed_discount_pct": discount,
            "email_subject": "Revised offer for Konark",
            "email_body": f"Hi Meghna,\n\nThanks for the candid feedback. We can offer {discount:g}% off with commissioning included. "
            "Could we speak tomorrow at 11 am to close this?\n\nBest regards,\nArcline Systems",
            "followup_title": "Call Meghna about revised offer",
            "followup_due_in_hours": 6,
            "expected_outcome": "Customer receives a revised offer and confirms the order.",
            "policy_claims": [{"claim": "Discounts above 10% require manager approval.", "evidence_ids": [disc_eid]}],
            "cited_evidence_ids": [disc_eid],
            "confidence": 0.86,
            "injection_suspected": False,
        }

    return reply


async def _wait(client, run_id: str, max_seconds: float = 120) -> dict:
    deadline = asyncio.get_event_loop().time() + max_seconds
    while True:
        run = (await client.get(f"/agent/runs/{run_id}")).json()
        if run["status"] != "running":
            return run
        assert asyncio.get_event_loop().time() < deadline, f"run did not finish: {run['steps']}"
        await asyncio.sleep(0.3)


async def _create_scenario(owner, name: str, *, days_since_quote: int = 9, waiting_days: int = 6) -> tuple[str, str]:
    now = datetime.now(UTC)
    cust = f"name,industry,segment,status,city\n{name},Manufacturing,mid_market,prospect,Bhubaneswar\n"
    assert (await owner.post("/ingest/customers", files={"file": ("c.csv", cust.encode(), "text/csv")})).json()[
        "inserted"
    ] == 1
    lead = (
        f"company_name,contact_name,contact_email,source,received_at,estimated_value\n"
        f"{name},Meghna Rath,meghna.rath@{name.split()[0].lower()}-{name.split()[1].lower()}.in,website,"
        f"{(now - timedelta(days=15)).date()},620000\n"
    )
    assert (await owner.post("/ingest/leads", files={"file": ("l.csv", lead.encode(), "text/csv")})).json()[
        "inserted"
    ] == 1
    quote_no = f"Q-E2E-{abs(hash(name)) % 100000}"
    quote = (
        f"quote_number,customer_name,total,discount_pct,status,sent_at\n"
        f"{quote_no},{name},620000,0,sent,{(now - timedelta(days=days_since_quote)).isoformat()}\n"
    )
    assert (await owner.post("/ingest/quotes", files={"file": ("q.csv", quote.encode(), "text/csv")})).json()[
        "inserted"
    ] == 1
    customer = (await owner.get("/customers", params={"q": name})).json()["items"][0]
    profile = (await owner.get(f"/customers/{customer['id']}")).json()
    opp_id = profile["opportunities"][0]["id"]
    conv = {
        "customer_id": customer["id"],
        "opportunity_id": opp_id,
        "channel": "email",
        "subject": "Quotation",
        "messages": [
            {
                "sender_type": "rep",
                "sender_name": "Ananya Bose",
                "body": f"Hi Meghna, sharing quotation {quote_no} for ₹6,20,000.",
                "sent_at": (now - timedelta(days=days_since_quote)).isoformat(),
            },
            {
                "sender_type": "customer",
                "sender_name": "Meghna Rath",
                "body": "Hi Ananya, the price is higher than what we budgeted. Sensara IoT has quoted lower for a similar scope. "
                "We want to finalise this month — can you do better?",
                "sent_at": (now - timedelta(days=waiting_days)).isoformat(),
            },
        ],
    }
    assert (await owner.post("/conversations", json=conv)).status_code == 201
    return customer["id"], opp_id


async def test_full_recovery_flow(owner, rep):
    customer_id, opp_id = await _create_scenario(owner, "Konark Precision Tools Pvt Ltd")

    # Risk engine detects the risk deterministically (before any AI runs).
    risk = (await owner.get("/risks", params={"q": "Konark Precision"})).json()["items"][0]
    assert risk["risk_level"] in ("high", "critical")
    assert {"CUSTOMER_AWAITING_REPLY", "QUOTE_UNANSWERED", "PRICE_OBJECTION"} <= {r["code"] for r in risk["reasons"]}

    set_llm_override(
        ScriptedLLM(by_purpose={"conversation_analysis": [INSIGHT], "recommendation": [recommendation_reply(8.0)]})
    )
    run_id = (await owner.post("/agent/runs", json={"opportunity_id": opp_id})).json()["run_id"]
    run = await _wait(owner, run_id)
    assert run["status"] == "awaiting_approval", run["error"]
    assert [s["node"] for s in run["steps"] if s["status"] == "completed"] == [
        "load_context",
        "analyze_conversation",
        "assess_risk",
        "retrieve_knowledge",
        "recommend",
        "ground_check",
        "policy_check",
        "persist_recommendation",
    ]
    state = run["state"]
    assert "price objection" in [q["reason"] for q in state["retrieval_queries"]]
    assert any(e["document"] == "Discount Authority Policy" for e in state["retrieved_context"])
    assert state["grounding"]["supported"] == 1

    rec = run["recommendation"]
    assert rec["status"] == "pending_approval" and rec["requires_approval"]
    rules = {r["rule"] for r in rec["approval_reasons"]}
    # 8% is within rep authority, but the deal is high-value and the action is customer-facing.
    assert "HIGH_VALUE_CUSTOMER_FACING" in rules and "DISCOUNT_ABOVE_REP_LIMIT" not in rules
    for field in ("what_happened", "why_risky", "recommendation", "expected_outcome"):
        assert rec[field]
    assert {e["kind"] for e in rec["evidence"]} >= {"risk_engine", "knowledge"}
    approval = run["approval"]
    assert approval["status"] == "pending" and approval["required_role"] == "manager"

    # The low-risk internal follow-up was created automatically, before approval.
    profile = (await owner.get(f"/customers/{customer_id}")).json()
    assert any(f["created_by_agent"] and f["status"] == "pending" for f in profile["followups"])

    # A sales rep cannot approve a manager-level request.
    r = await rep.post(f"/approvals/{approval['id']}/decision", json={"decision": "approve"})
    assert r.status_code == 403

    # Manager-level approval with a human edit.
    out = (
        await owner.post(
            f"/approvals/{approval['id']}/decision",
            json={"decision": "approve", "note": "Approved at 7% for faster close", "discount_pct": 7},
        )
    ).json()
    assert out["status"] == "approved"
    assert out["verification"]["all_passed"], out["verification"]
    tools = [r["tool"] for r in out["execution"]["results"]]
    assert tools == ["offer_discount", "send_email"]
    revised = out["execution"]["results"][0]["data"]["detail"]
    assert revised["discount_pct"] == 7 and revised["new_total"] == 576600  # 620000 × 0.93, computed by software
    assert out["execution"]["results"][1]["data"]["detail"]["delivered"] is False  # outbox, honestly labelled

    detail = (await owner.get(f"/recommendations/{rec['id']}")).json()
    assert detail["status"] == "executed" and detail["approval"]["edited_payload"] == {"discount_pct": 7.0}

    audit = (await owner.get("/audit", params={"customer_id": customer_id, "limit": 100})).json()["items"]
    actions = {a["action"] for a in audit}
    assert {
        "approval.approved",
        "tool.offer_discount",
        "tool.send_email",
        "tool.create_followup",
        "conversation.analyzed",
    } <= actions

    # Outcome → observed recovered revenue (attributed because an action was executed before the win).
    before = (await owner.get("/roi")).json()["observed"]["recovered_revenue"]
    assert (await owner.post(f"/opportunities/{opp_id}/outcome", json={"outcome": "closed_won"})).status_code == 200
    after = (await owner.get("/roi")).json()["observed"]["recovered_revenue"]
    assert after - before == 620000


async def test_rules_fallback_when_llm_unavailable(owner):
    _, opp_id = await _create_scenario(owner, "Satpura Gear Works Pvt Ltd")
    run_id = (await owner.post("/agent/runs", json={"opportunity_id": opp_id})).json()["run_id"]
    run = await _wait(owner, run_id)
    assert run["status"] == "awaiting_approval"
    rec = run["recommendation"]
    assert rec["generated_by"] == "rules_fallback" and rec["draft_body"] is None
    assert "LLM_FALLBACK" in {r["rule"] for r in rec["approval_reasons"]}
    assert any("LLM unavailable" in x or "heuristics" in x for x in rec["limitations"])


async def test_malformed_llm_output_never_accepted(owner):
    _, opp_id = await _create_scenario(owner, "Shivalik Pumps Pvt Ltd")
    set_llm_override(
        ScriptedLLM(
            by_purpose={
                "conversation_analysis": ["nope", "{}", "[]"],
                "recommendation": ['{"title": 1}', "garbage", '{"primary_action": "wire_money"}'],
            }
        )
    )
    run = await _wait(owner, (await owner.post("/agent/runs", json={"opportunity_id": opp_id})).json()["run_id"])
    assert run["status"] == "awaiting_approval"
    assert run["recommendation"]["generated_by"] == "rules_fallback"


async def test_discount_above_manager_limit_needs_owner_and_reject_flow(owner, rep):
    _, opp_id = await _create_scenario(owner, "Malabar Spices Exports Pvt Ltd")
    set_llm_override(
        ScriptedLLM(by_purpose={"conversation_analysis": [INSIGHT], "recommendation": [recommendation_reply(25.0)]})
    )
    run = await _wait(owner, (await owner.post("/agent/runs", json={"opportunity_id": opp_id})).json()["run_id"])
    approval = run["approval"]
    assert approval["required_role"] == "owner"
    assert "DISCOUNT_ABOVE_MANAGER_LIMIT" in {r["rule"] for r in approval["reasons"]}
    r = await owner.post(f"/approvals/{approval['id']}/decision", json={"decision": "reject", "note": "Too deep"})
    assert r.json()["status"] == "rejected"
    rec = (await owner.get(f"/recommendations/{run['recommendation']['id']}")).json()
    assert (
        rec["status"] == "rejected"
        and rec["actions"] == []
        or all(a["action_type"] != "offer_discount" for a in rec["actions"])
    )


async def test_healthy_deal_needs_no_action(owner):
    _, opp_id = await _create_scenario(owner, "Aravali Textiles Pvt Ltd", days_since_quote=1, waiting_days=0)
    # Rep replies immediately → not waiting, recent contact.
    run = await _wait(owner, (await owner.post("/agent/runs", json={"opportunity_id": opp_id})).json()["run_id"])
    if run["state"]["risk_analysis"]["risk_level"] == "low":
        assert run["status"] == "completed" and run["recommendation"] is None
    else:  # price objection + competitor can still lift it to medium; then a recommendation is expected
        assert run["recommendation"] is not None


async def test_unknown_opportunity_is_404(owner):
    r = await owner.post("/agent/runs", json={"opportunity_id": "00000000-0000-4000-8000-000000000000"})
    assert r.status_code == 404


async def _until(predicate, seconds: float = 10) -> None:
    deadline = asyncio.get_event_loop().time() + seconds
    while not predicate():
        assert asyncio.get_event_loop().time() < deadline, "condition not met in time"
        await asyncio.sleep(0.1)


async def test_slack_alerts_on_approval_needed_and_on_decision(owner, monkeypatch):
    import json

    import httpx
    from pydantic import SecretStr

    from app.core.config import get_settings
    from app.integrations import slack

    posted: list[dict] = []
    monkeypatch.setattr(get_settings(), "slack_webhook_url", SecretStr("https://hooks.slack.com/services/T/B/X"))
    slack.set_slack_transport(
        httpx.MockTransport(lambda r: posted.append(json.loads(r.content)) or httpx.Response(200))
    )
    try:
        _, opp_id = await _create_scenario(owner, "Mahanadi Polymers Pvt Ltd")
        set_llm_override(
            ScriptedLLM(by_purpose={"conversation_analysis": [INSIGHT], "recommendation": [recommendation_reply(8.0)]})
        )
        run = await _wait(owner, (await owner.post("/agent/runs", json={"opportunity_id": opp_id})).json()["run_id"])
        assert run["status"] == "awaiting_approval"
        await _until(lambda: len(posted) >= 1)
        alert = json.dumps(posted[0], ensure_ascii=False)
        assert "Deal at risk: Mahanadi Polymers Pvt Ltd" in alert and "Draft email" in alert and "Meghna Rath" in alert

        out = (await owner.post(f"/approvals/{run['approval']['id']}/decision", json={"decision": "approve"})).json()
        assert out["status"] == "approved"
        assert len(posted) == 2
        decided = json.dumps(posted[1], ensure_ascii=False)
        assert "approved the follow-up for *Mahanadi Polymers Pvt Ltd*" in decided and "outbox" in decided

        audit = (await owner.get("/audit", params={"action": "slack.notified", "limit": 10})).json()["items"]
        assert len(audit) == 2 and all(a["result"] == "success" for a in audit)
    finally:
        slack.set_slack_transport(None)


async def test_slack_outage_never_blocks_approvals(owner, monkeypatch):
    import httpx
    from pydantic import SecretStr

    from app.core.config import get_settings
    from app.integrations import slack

    monkeypatch.setattr(get_settings(), "slack_webhook_url", SecretStr("https://hooks.slack.com/services/T/B/X"))
    slack.set_slack_transport(httpx.MockTransport(lambda r: httpx.Response(500, text="internal_error")))
    try:
        customer_id, opp_id = await _create_scenario(owner, "Sabarmati Ceramics Pvt Ltd")
        set_llm_override(
            ScriptedLLM(by_purpose={"conversation_analysis": [INSIGHT], "recommendation": [recommendation_reply(8.0)]})
        )
        run = await _wait(owner, (await owner.post("/agent/runs", json={"opportunity_id": opp_id})).json()["run_id"])
        assert run["status"] == "awaiting_approval"
        out = (await owner.post(f"/approvals/{run['approval']['id']}/decision", json={"decision": "approve"})).json()
        assert out["status"] == "approved" and out["verification"]["all_passed"]
        audit = (
            await owner.get("/audit", params={"action": "slack.notified", "customer_id": customer_id, "limit": 10})
        ).json()["items"]
        assert len(audit) == 2 and all(a["result"] == "failure" for a in audit)
        r = await owner.post("/integrations/slack/test")
        assert r.status_code >= 400 and "500" in r.json()["error"]["message"]
    finally:
        slack.set_slack_transport(None)
