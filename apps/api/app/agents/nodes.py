"""Workflow nodes for the Revenue Recovery agent.

Each node: reads explicit state → calls registry tools (validated, traced, audited) → returns a partial
state update. LLM calls happen in exactly two places (conversation analysis via its tool, and
`recommend`); everything else is deterministic.
"""

from __future__ import annotations

import functools
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from langchain_core.runnables import RunnableConfig
from sqlalchemy import select

from app.agents.query_plan import plan_queries
from app.agents.state import RevenueRecoveryState
from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode, LLMError
from app.db import models as m
from app.domain.enums import ActionType, RecommendationStatus, UserRole
from app.domain.policy import ActionProposal, evaluate
from app.domain.settings import CompanySettings
from app.llm.structured import generate_structured
from app.observability.tracing import get_tracer
from app.prompts.recommendation import RecommendationDraft, build_messages
from app.rag.grounding import format_evidence, verify_claims
from app.rag.retriever import Evidence
from app.services.company import get_company_settings
from app.tools import REGISTRY, ToolContext, ToolResult

logger = logging.getLogger(__name__)
AGENT = "RevenueRecoveryAgent"
MAX_EVIDENCE = 8
StepSink = Callable[[dict[str, Any]], Awaitable[None]]
Node = Callable[[RevenueRecoveryState, RunnableConfig], Awaitable[dict[str, Any]]]


def _ctx(config: RunnableConfig) -> ToolContext:
    return config["configurable"]["ctx"]


def node(name: str) -> Callable[[Node], Node]:
    """Wrap a node with a Langfuse span, timing and a live step record."""

    def deco(fn: Node) -> Node:
        @functools.wraps(fn)
        async def wrapper(state: RevenueRecoveryState, config: RunnableConfig) -> dict[str, Any]:
            sink: StepSink | None = config["configurable"].get("step_sink")
            started = time.perf_counter()
            step: dict[str, Any] = {"node": name, "status": "running", "started_at": datetime.now(UTC).isoformat()}
            if sink:
                await sink(step)
            with get_tracer().observation(
                name, as_type="chain", input={k: state.get(k) for k in ("opportunity_id", "status")}
            ) as span:
                try:
                    update = await fn(state, config)
                except Exception as exc:
                    step.update(
                        status="failed", error=str(exc)[:300], latency_ms=int((time.perf_counter() - started) * 1000)
                    )
                    if sink:
                        await sink(step)
                    raise
                summary = update.pop("_summary", None)
                failed = update.get("status") == "failed"
                step.update(
                    status="failed" if failed else "completed",
                    summary=summary,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )
                span.update(
                    output={"summary": summary, "status": update.get("status")}, level="ERROR" if failed else None
                )
            if sink:
                await sink(step)
            return update

        return wrapper

    return deco


async def _tool(config: RunnableConfig, name: str, args: dict[str, Any]) -> ToolResult:
    return await REGISTRY.invoke(name, args, _ctx(config))


async def _settings(config: RunnableConfig) -> CompanySettings:
    ctx = _ctx(config)
    cached = config["configurable"].get("_settings")
    if cached is None:
        cached = await get_company_settings(ctx.session, ctx.company_id)
        config["configurable"]["_settings"] = cached
    return cached


# ---------------------------------------------------------------------------------------- nodes
@node("load_context")
async def load_context(state: RevenueRecoveryState, config: RunnableConfig) -> dict[str, Any]:
    res = await _tool(config, "get_opportunity", {"opportunity_id": state["opportunity_id"]})
    if not res.ok:
        return {"status": "failed", "errors": [f"get_opportunity: {res.error.message}"], "_summary": res.error.message}
    data = res.data or {}
    if data["stage"] in ("closed_won", "closed_lost"):
        return {"status": "failed", "errors": ["Opportunity is closed; nothing to recover"], "_summary": "deal closed"}
    return {
        "crm_context": data,
        "customer_id": data["customer_id"],
        "status": "running",
        "_summary": f"{data['customer_name']} · {data['stage']} · {data['currency']} {data['amount']:,.0f}",
    }


@node("analyze_conversation")
async def analyze_conversation(state: RevenueRecoveryState, config: RunnableConfig) -> dict[str, Any]:
    conv_ids = state["crm_context"].get("conversation_ids", [])[:2]
    insights, limitations, latest_customer_msgs = [], [], []
    for cid in conv_ids:
        res = await _tool(config, "analyze_conversation", {"conversation_id": cid})
        if res.ok and res.data and res.data.get("insight"):
            insights.append(
                {
                    "conversation_id": cid,
                    "cached": res.data["cached"],
                    **res.data["insight"],
                    "injection_flags": res.data["injection_flags"],
                }
            )
            limitations += res.limitations
        else:
            reason = res.error.message if res.error else "analysis failed validation"
            limitations.append(f"Conversation analysis unavailable ({reason}); risk engine uses keyword heuristics.")
    if conv_ids:
        transcript = await _tool(config, "get_conversation", {"conversation_id": conv_ids[0]})
        if transcript.ok and transcript.data:
            lines = [ln for ln in transcript.data["transcript"].splitlines() if "] CUSTOMER (" in ln]
            latest_customer_msgs = lines[-3:]
    context = {
        "insights": insights,
        "latest_customer_messages": latest_customer_msgs,
        "source": "llm_analysis" if insights else "keyword_heuristic",
    }
    summary = (
        f"intent={insights[0]['intent']}, objections={[o['type'] for o in insights[0]['objections']]}"
        if insights
        else "no LLM analysis — heuristics only"
    )
    return {"conversation_context": context, "limitations": limitations, "_summary": summary}


@node("assess_risk")
async def assess_risk(state: RevenueRecoveryState, config: RunnableConfig) -> dict[str, Any]:
    res = await _tool(config, "calculate_revenue_risk", {"opportunity_id": state["opportunity_id"], "persist": True})
    if not res.ok:
        return {
            "status": "failed",
            "errors": [f"calculate_revenue_risk: {res.error.message}"],
            "_summary": res.error.message,
        }
    risk = res.data or {}
    update: dict[str, Any] = {
        "risk_analysis": risk,
        "_summary": f"{risk['risk_level'].upper()} {risk['risk_score']}/100 · at risk {risk['revenue_at_risk']:,.0f}",
    }
    if risk["risk_level"] == "low" and not state.get("force"):
        update["status"] = "no_action_needed"
    return update


@node("retrieve_knowledge")
async def retrieve_knowledge(state: RevenueRecoveryState, config: RunnableConfig) -> dict[str, Any]:
    settings = await _settings(config)
    risk = state["risk_analysis"]
    objections = [o["type"] for i in state["conversation_context"].get("insights", []) for o in i.get("objections", [])]
    high_value = Decimal(str(state["crm_context"]["amount"])) >= settings.policy.high_value_deal_threshold
    plan = plan_queries([r["code"] for r in risk.get("reasons", [])], objections, high_value=high_value)
    seen: dict[str, dict[str, Any]] = {}
    withheld: list[dict[str, Any]] = []
    for q in plan:
        res = await _tool(
            config,
            "search_knowledge_base",
            {"query": q.query, "document_types": [d.value for d in q.doc_types], "top_k": 3},
        )
        if not res.ok:
            continue
        for ev in (res.data or {}).get("evidence", []):
            if ev["flagged_injection"]:
                withheld.append(
                    {"document": ev["document"], "section": ev["section"], "reason": "possible prompt injection"}
                )
                continue
            if ev["chunk_id"] not in seen or ev["retrieval_score"] > seen[ev["chunk_id"]]["retrieval_score"]:
                seen[ev["chunk_id"]] = {**ev, "query_reason": q.reason}
    evidence = sorted(seen.values(), key=lambda e: -e["retrieval_score"])[:MAX_EVIDENCE]
    for i, ev in enumerate(evidence, start=1):
        ev["evidence_id"] = f"E{i}"
    limitations = [] if evidence else ["No relevant policy passages found (INSUFFICIENT_EVIDENCE)."]
    if withheld:
        limitations.append(f"{len(withheld)} passage(s) withheld: instruction-like text (possible prompt injection).")
    return {
        "retrieval_queries": [q.as_dict() for q in plan],
        "retrieved_context": evidence,
        "withheld_evidence": withheld,
        "limitations": limitations,
        "_summary": f"{len(plan)} queries → {len(evidence)} passages",
    }


def _evidence_objs(items: list[dict[str, Any]]) -> list[Evidence]:
    return [
        Evidence(
            e["evidence_id"],
            e["chunk_id"],
            "",
            e["document"],
            e["document_type"],
            e["section"],
            e["version"],
            e["content"],
            e["flagged_injection"],
            {"rerank": e["retrieval_score"]},
        )
        for e in items
    ]


def _crm_facts(state: RevenueRecoveryState) -> dict[str, Any]:
    c = state["crm_context"]
    return {
        k: c.get(k)
        for k in (
            "customer_name",
            "name",
            "stage",
            "amount",
            "currency",
            "owner",
            "primary_contact",
            "expected_close_date",
            "last_activity_at",
            "latest_quote",
            "pending_followups",
        )
    } | {"today": datetime.now(UTC).date().isoformat()}


def _risk_brief(state: RevenueRecoveryState) -> dict[str, Any]:
    r = state["risk_analysis"]
    return {
        "risk_score": r["risk_score"],
        "risk_level": r["risk_level"],
        "revenue_at_risk": r["revenue_at_risk"],
        "purchase_probability": r["purchase_probability"],
        "reasons": [x["label"] for x in r["reasons"]],
        "engine_next_step": r["recommended_next_step"],
    }


def rules_fallback(state: RevenueRecoveryState, reason: str) -> dict[str, Any]:
    """Deterministic recommendation used when the LLM is unavailable. Clearly labelled; always needs review."""
    r = state["risk_analysis"]
    c = state["crm_context"]
    labels = [x["label"] for x in r["reasons"][:4]]
    return {
        "title": r["recommended_next_step"],
        "what_happened": f"{c['customer_name']} — {c['name']} is in {c['stage']} worth {c['currency']} {c['amount']:,.0f}.",
        "why_risky": "Risk engine reasons: " + "; ".join(labels) if labels else "No risk reasons fired.",
        "recommendation": f"{r['recommended_next_step']}. (Generated by deterministic rules because the AI step was unavailable: {reason}.)",
        "primary_action": "create_followup",
        "proposed_discount_pct": None,
        "email_subject": None,
        "email_body": None,
        "followup_title": r["recommended_next_step"][:180],
        "followup_due_in_hours": 24,
        "expected_outcome": "An internal follow-up task is created for the deal owner.",
        "policy_claims": [],
        "cited_evidence_ids": [],
        "confidence": 0.5,
        "injection_suspected": False,
        "_generated_by": "rules_fallback",
        "_model": None,
    }


@node("recommend")
async def recommend(state: RevenueRecoveryState, config: RunnableConfig) -> dict[str, Any]:
    ctx = _ctx(config)
    settings = await _settings(config)
    evidence = state.get("retrieved_context", [])
    try:
        provider = ctx.deps.llm()
    except LLMError as exc:
        return {
            "recommendation": rules_fallback(state, exc.message),
            "limitations": [f"LLM unavailable: {exc.message}"],
            "_summary": "rules fallback (LLM not configured)",
        }
    policy = {
        k: str(v)
        for k, v in settings.policy.model_dump().items()
        if k not in ("auto_executable_actions", "customer_facing_actions")
    }
    conv = state.get("conversation_context", {})
    try:
        result = await generate_structured(
            provider,
            build_messages(
                crm_facts=_crm_facts(state),
                risk=_risk_brief(state),
                conversation=conv,
                policy=policy,
                evidence_block=format_evidence(_evidence_objs(evidence)) or "(no passages retrieved)",
            ),
            RecommendationDraft,
            purpose="recommendation",
            temperature=0.2,
        )
    except LLMError as exc:
        return {
            "recommendation": rules_fallback(state, exc.message),
            "limitations": [f"LLM call failed: {exc.message}"],
            "_summary": f"rules fallback ({exc.code.value})",
        }
    if not result.ok or result.value is None:
        return {
            "recommendation": rules_fallback(state, "model output failed validation"),
            "limitations": ["Recommendation output failed schema validation after repair attempts."],
            "_summary": "rules fallback (invalid output)",
        }
    draft = result.value.model_dump() | {"_generated_by": "llm", "_model": result.model, "_status": result.status.value}
    return {"recommendation": draft, "_summary": f"{draft['primary_action']} · confidence {draft['confidence']:.2f}"}


_NUM = re.compile(r"₹\s?\d[\d,]*|\b\d+(?:\.\d+)?\s?%")


@node("ground_check")
async def ground_check(state: RevenueRecoveryState, config: RunnableConfig) -> dict[str, Any]:
    ctx = _ctx(config)
    settings = get_settings()
    rec = state["recommendation"]
    evidence = _evidence_objs(state.get("retrieved_context", []))
    known_ids = {e.evidence_id for e in evidence}
    claims = [(c["claim"], c["evidence_ids"]) for c in rec.get("policy_claims", [])]
    trusted = str(_crm_facts(state)) + " " + str(state.get("conversation_context", {}))
    verified = []
    if claims:
        retriever = ctx.deps.retriever()
        verified = [
            v.as_dict()
            for v in await verify_claims(
                retriever.embedder,
                claims,
                evidence,
                settings.rag_min_claim_support,
                trusted,
                retriever.reranker,
                settings.rag_min_claim_support_xenc,
            )
        ]
    bad_cites = sorted(set(rec.get("cited_evidence_ids", [])) - known_ids)
    corpus = (trusted + " " + " ".join(e.content for e in evidence)).replace(",", "").replace(" ", "")
    email_numbers = {n.replace(",", "").replace(" ", "") for n in _NUM.findall(rec.get("email_body") or "")}
    unknown_numbers = sorted(n for n in email_numbers if n not in corpus and n.rstrip("%") not in corpus)
    unverified = sum(1 for v in verified if not v["supported"]) + len(bad_cites) + len(unknown_numbers)
    grounding = {
        "claims": verified,
        "supported": sum(1 for v in verified if v["supported"]),
        "total": len(verified),
        "invalid_citations": bad_cites,
        "unsupported_numbers_in_email": unknown_numbers,
        "unverified_count": unverified,
        "grounding_score": (sum(1 for v in verified if v["supported"]) / len(verified)) if verified else None,
    }
    limitations = []
    if unknown_numbers:
        limitations.append(f"Draft email contains figures not found in CRM data or sources: {unknown_numbers}")
    return {
        "grounding": grounding,
        "limitations": limitations,
        "_summary": f"{grounding['supported']}/{grounding['total']} claims supported, {unverified} unverified items",
    }


@node("policy_check")
async def policy_check(state: RevenueRecoveryState, config: RunnableConfig) -> dict[str, Any]:
    settings = await _settings(config)
    rec = state["recommendation"]
    action = ActionType(rec["primary_action"])
    evidence_types = {e["document_type"] for e in state.get("retrieved_context", [])}
    conv_injection = any(i.get("injection_flags") for i in state.get("conversation_context", {}).get("insights", []))
    proposal = ActionProposal(
        action_type=action,
        deal_value=Decimal(str(state["crm_context"]["amount"])),
        discount_pct=Decimal(str(rec["proposed_discount_pct"]))
        if rec.get("proposed_discount_pct") is not None
        else None,
        confidence=float(rec.get("confidence", 0)),
        policy_evidence_found=bool(evidence_types & {"discount_policy", "pricing_policy", "refund_policy"}),
        unverified_claims=int(state.get("grounding", {}).get("unverified_count", 0)),
        injection_suspected=bool(rec.get("injection_suspected")) or conv_injection,
        generated_by_fallback=rec.get("_generated_by") == "rules_fallback",
    )
    decision = evaluate(proposal, settings.policy)
    # When the AI also drafted a customer email alongside a non-email action, sending it is gated too.
    if (
        action != ActionType.SEND_EMAIL
        and rec.get("email_body")
        and decision.allowed
        and not decision.requires_approval
    ):
        email_decision = evaluate(
            ActionProposal(ActionType.SEND_EMAIL, deal_value=proposal.deal_value, confidence=proposal.confidence),
            settings.policy,
        )
        if email_decision.requires_approval:
            decision = email_decision
    proposed = {
        "primary": {
            "action_type": action.value,
            "discount_pct": rec.get("proposed_discount_pct"),
            "email_subject": rec.get("email_subject"),
            "email_body": rec.get("email_body"),
            "to": (state["crm_context"].get("primary_contact") or {}).get("email"),
        },
        "internal": [
            {
                "action_type": ActionType.CREATE_FOLLOWUP.value,
                "title": rec["followup_title"],
                "due_in_hours": max(1, min(int(rec.get("followup_due_in_hours", 24)), 72)),
            }
        ],
    }
    return {
        "policy_check": decision.as_dict(),
        "approval_required": decision.requires_approval,
        "proposed_action": proposed,
        "_summary": (
            "BLOCKED"
            if not decision.allowed
            else f"approval required ({decision.required_role.value if decision.required_role else '-'})"
            if decision.requires_approval
            else "auto-executable"
        ),
    }


def _explain_evidence(state: RevenueRecoveryState) -> list[dict[str, Any]]:
    rec = state["recommendation"]
    cited = set(rec.get("cited_evidence_ids", [])) | {
        i for c in rec.get("policy_claims", []) for i in c["evidence_ids"]
    }
    crm = [
        {
            "kind": "risk_engine",
            "label": r["label"],
            "points": r["points"],
            "source": r["source"],
            "quote": r.get("evidence", {}).get("excerpt"),
        }
        for r in state["risk_analysis"]["reasons"]
    ]
    conv = [
        {"kind": "conversation", "label": "Customer said", "quote": q}
        for i in state.get("conversation_context", {}).get("insights", [])[:1]
        for q in i.get("evidence_quotes", [])[:3]
    ]
    knowledge = [
        {
            "kind": "knowledge",
            "evidence_id": e["evidence_id"],
            "label": e["section"],
            "source_document": e["document"],
            "source_section": e["section"],
            "version": e["version"],
            "retrieval_score": e["retrieval_score"],
            "quote": e["content"][:600],
            "cited": e["evidence_id"] in cited,
        }
        for e in state.get("retrieved_context", [])
    ]
    return crm + conv + knowledge


@node("persist_recommendation")
async def persist_recommendation(state: RevenueRecoveryState, config: RunnableConfig) -> dict[str, Any]:
    ctx = _ctx(config)
    rec, decision = state["recommendation"], state["policy_check"]
    blocked = not decision["allowed"]
    status = (
        RecommendationStatus.REJECTED
        if blocked
        else RecommendationStatus.PENDING_APPROVAL
        if state["approval_required"]
        else RecommendationStatus.APPROVED
    )
    limitations = list(dict.fromkeys(state.get("limitations", [])))
    row = m.Recommendation(
        company_id=ctx.company_id,
        opportunity_id=uuid.UUID(state["opportunity_id"]),
        customer_id=uuid.UUID(state["customer_id"]),
        risk_id=uuid.UUID(state["risk_analysis"]["risk_id"]) if state["risk_analysis"].get("risk_id") else None,
        agent_run_id=uuid.UUID(state["run_id"]),
        action_type=ActionType(rec["primary_action"]),
        status=status,
        title=rec["title"][:255],
        what_happened=rec["what_happened"],
        why_risky=rec["why_risky"],
        recommendation=rec["recommendation"],
        expected_outcome=rec["expected_outcome"],
        evidence=_explain_evidence(state),
        proposed_action=state["proposed_action"],
        draft_subject=None,
        draft_body=None,
        confidence=float(rec["confidence"]),
        requires_approval=state["approval_required"],
        approval_reasons=decision["reasons"],
        grounding=state.get("grounding", {}),
        limitations=limitations,
        generated_by=rec.get("_generated_by", "llm"),
        model=rec.get("_model"),
        trace_id=config["configurable"].get("trace_id"),
    )
    ctx.session.add(row)
    await ctx.session.flush()
    rid = str(row.id)
    internal: list[dict[str, Any]] = []
    if rec.get("email_subject") and rec.get("email_body"):
        r = await _tool(
            config,
            "draft_followup_message",
            {"recommendation_id": rid, "subject": rec["email_subject"], "body": rec["email_body"]},
        )
        internal.append({"tool": "draft_followup_message", "ok": r.ok})
    if not blocked:
        task = state["proposed_action"]["internal"][0]
        r = await _tool(
            config,
            "create_followup",
            {
                "opportunity_id": state["opportunity_id"],
                "title": task["title"],
                "notes": rec["recommendation"][:1800],
                "due_in_hours": task["due_in_hours"],
                "recommendation_id": rid,
            },
        )
        internal.append({"tool": "create_followup", "ok": r.ok, **(r.data or {}).get("detail", {})})
    r = await _tool(
        config,
        "log_action",
        {
            "opportunity_id": state["opportunity_id"],
            "recommendation_id": rid,
            "description": f"AI recovery analysis: {rec['title'][:200]}",
        },
    )
    internal.append({"tool": "log_action", "ok": r.ok})
    update: dict[str, Any] = {"recommendation_id": rid, "internal_actions": internal}
    if blocked:
        update["status"] = "blocked"
    elif state["approval_required"]:
        role = decision.get("required_role") or UserRole.MANAGER.value
        risk = state["risk_analysis"]
        summary = (
            f"{risk['risk_level'].upper()} risk ({risk['risk_score']}/100), {state['crm_context']['currency']} "
            f"{risk['revenue_at_risk']:,.0f} at risk. Proposed: {rec['primary_action']}."
        )
        r = await _tool(
            config,
            "request_human_approval",
            {"recommendation_id": rid, "reasons": decision["reasons"], "risk_summary": summary, "required_role": role},
        )
        if not r.ok:
            raise AppError(
                ErrorCode.TOOL_FAILURE, f"Could not open approval request: {r.error.message if r.error else ''}"
            )
        update |= {"approval_request_id": r.data["approval_request_id"], "status": "awaiting_approval"}
    return update | {"_summary": f"recommendation {rid[:8]} · {update.get('status', 'auto-execute')}"}


@node("execute_action")
async def execute_action(state: RevenueRecoveryState, config: RunnableConfig) -> dict[str, Any]:
    """Execute the primary action. Customer-facing tools re-verify the approval in the database."""
    ctx = _ctx(config)
    primary = state["proposed_action"]["primary"]
    action = ActionType(primary["action_type"])
    rid, approval_id = state["recommendation_id"], state.get("approval_request_id")
    results: list[dict[str, Any]] = []

    async def run(name: str, args: dict[str, Any]) -> bool:
        r = await _tool(config, name, args)
        results.append(
            {"tool": name, "ok": r.ok, "data": r.data, "error": r.error.model_dump(mode="json") if r.error else None}
        )
        return r.ok

    ok = True
    if action == ActionType.OFFER_DISCOUNT:
        ok = await run(
            "offer_discount",
            {"recommendation_id": rid, "approval_request_id": approval_id, "discount_pct": primary["discount_pct"]},
        )
    elif action == ActionType.ESCALATE_TO_MANAGER:
        ok = await run(
            "escalate_to_manager",
            {
                "opportunity_id": state["opportunity_id"],
                "recommendation_id": rid,
                "title": f"Manager review: {state['recommendation']['title'][:150]}",
                "due_in_hours": 24,
            },
        )
    wants_email = bool(primary.get("email_body")) and action in (ActionType.SEND_EMAIL, ActionType.OFFER_DISCOUNT)
    if ok and wants_email and primary.get("to"):
        ok = await run(
            "send_email",
            {
                "recommendation_id": rid,
                "approval_request_id": approval_id,
                "to": primary["to"],
                "subject": primary["email_subject"],
                "body": primary["email_body"],
            },
        )
    elif ok and wants_email:
        ok = False  # never skip silently: the approved email could not be sent
        results.append(
            {
                "tool": "send_email",
                "ok": False,
                "error": {"message": "No contact email on the opportunity; add a contact and re-run"},
            }
        )

    rec = await ctx.session.get(m.Recommendation, uuid.UUID(rid))
    if rec is not None:
        rec.status = RecommendationStatus.EXECUTED if ok else RecommendationStatus.FAILED
    return {
        "execution_result": {"ok": ok, "results": results},
        "status": "executed" if ok else "failed",
        "errors": [] if ok else [f"execution failed: {[r['error'] for r in results if not r['ok']]}"],
        "_summary": f"{action.value}: {'ok' if ok else 'failed'} ({len(results)} tool calls)",
    }


@node("verify")
async def verify(state: RevenueRecoveryState, config: RunnableConfig) -> dict[str, Any]:
    """Re-read the database to confirm the intended effects actually exist."""
    ctx = _ctx(config)
    rid = uuid.UUID(state["recommendation_id"])
    checks: list[dict[str, Any]] = []
    actions = (await ctx.session.scalars(select(m.Action).where(m.Action.recommendation_id == rid))).all()
    for res in state.get("execution_result", {}).get("results", []):
        if res["ok"] and res.get("data", {}).get("action_id"):
            found = next((a for a in actions if str(a.id) == res["data"]["action_id"]), None)
            checks.append(
                {"check": f"{res['tool']} recorded", "passed": bool(found and found.status.value == "succeeded")}
            )
    followup = await ctx.session.scalar(select(m.Followup).where(m.Followup.recommendation_id == rid))
    checks.append({"check": "follow-up task exists", "passed": followup is not None})
    rec = await ctx.session.get(m.Recommendation, rid)
    expected = "executed" if state.get("execution_result", {}).get("ok") else "failed"
    checks.append({"check": f"recommendation marked {expected}", "passed": bool(rec and rec.status.value == expected)})
    passed = all(c["passed"] for c in checks)
    return {
        "verification_result": {"checks": checks, "all_passed": passed},
        "_summary": f"{sum(c['passed'] for c in checks)}/{len(checks)} checks passed",
    }
