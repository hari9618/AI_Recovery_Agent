"""Agent workflow evaluation: runs each scenario through the real workflow and scores it.

Metrics (fraction of applicable cases passing):
  workflow_completion       run ended in the expected (or expected graceful) state
  risk_detection_accuracy   deterministic risk level / reasons as expected
  approval_compliance       approval decision matches policy (offline: expectation; live: independent re-evaluation)
  policy_compliance         expected rules fired, excluded rules did not, and NO customer-facing action ran unapproved
  tool_selection_accuracy   the tools the workflow should call were called (from the audit trail)
  tool_argument_accuracy    key tool arguments were correct (ids, roles, policy doc types, discount)
  database_update_correctness  DB state after the run / decision matches expectations
  hallucination_detection   injected hallucinations were caught (offline) / hallucination_rate (live)
  failure_recovery          failure-injected cases degraded gracefully
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.errors import AppError
from app.db import models as m
from app.db.session import get_sessionmaker
from app.domain.enums import ActionType, ApprovalStatus, UserRole
from app.domain.policy import ActionProposal, evaluate
from app.domain.settings import CompanySettings
from app.evaluation.llm_plans import provider_for
from app.evaluation.sandbox import Sandbox, materialise, set_knowledge_active
from app.llm.base import LLMProvider
from app.services.agent_runner import decide_approval, run_recovery
from app.tools import ToolDeps

logger = logging.getLogger(__name__)
CUSTOMER_FACING = {ActionType.SEND_EMAIL, ActionType.OFFER_DISCOUNT}


def load_cases(path: Path) -> tuple[str, list[dict[str, Any]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["version"], data["cases"]


async def _tool_calls(run_id: str) -> list[m.AuditLog]:
    async with get_sessionmaker()() as s:
        return list(
            (
                await s.scalars(
                    select(m.AuditLog)
                    .where(m.AuditLog.agent_run_id == uuid.UUID(run_id), m.AuditLog.tool.is_not(None))
                    .order_by(m.AuditLog.occurred_at)
                )
            ).all()
        )


async def _no_unapproved_customer_actions(rec_id: str | None) -> bool:
    if not rec_id:
        return True
    async with get_sessionmaker()() as s:
        actions = (await s.scalars(select(m.Action).where(m.Action.recommendation_id == uuid.UUID(rec_id)))).all()
        for a in actions:
            if a.action_type in CUSTOMER_FACING:
                ap = await s.get(m.ApprovalRequest, a.approval_request_id) if a.approval_request_id else None
                if ap is None or ap.status != ApprovalStatus.APPROVED:
                    return False
    return True


def _expected_tools(run: dict[str, Any], rec: dict[str, Any] | None) -> set[str]:
    tools = {"get_opportunity"}
    status = run["status"]
    state = run.get("state") or {}
    if status == "failed" and not state.get("risk_analysis"):
        return tools
    tools |= {"analyze_conversation", "calculate_revenue_risk"}
    if not rec:
        return tools
    tools |= {"search_knowledge_base", "log_action"}
    if rec["status"] != "rejected" or state.get("policy_check", {}).get("allowed", True):
        tools.add("create_followup")
    if rec["requires_approval"]:
        tools.add("request_human_approval")
    if rec["action_type"] == "escalate_to_manager" and not rec["requires_approval"]:
        tools.add("escalate_to_manager")
    return tools


async def run_case(
    case: dict[str, Any], sandbox: Sandbox, *, live_provider: LLMProvider | None, settings: CompanySettings
) -> dict[str, Any]:
    exp, spec = case["expected"], case["llm"]
    offline = live_provider is None
    started = time.perf_counter()
    async with get_sessionmaker()() as s:
        refs = await materialise(s, sandbox, case["key"], case["crm"])
    if case["crm"].get("knowledge_disabled"):
        async with get_sessionmaker()() as s:
            await set_knowledge_active(s, sandbox.company_id, False)
    provider = provider_for(spec, refs["customer_message"], live_provider=live_provider)
    owner = sandbox.principals["owner"]
    try:
        result = await run_recovery(owner, refs["opportunity_id"], deps=ToolDeps(provider=provider))
    finally:
        if case["crm"].get("knowledge_disabled"):
            async with get_sessionmaker()() as s:
                await set_knowledge_active(s, sandbox.company_id, True)

    async with get_sessionmaker()() as s:
        run_row = await s.get(m.AgentRun, uuid.UUID(result["run_id"]))
        rec_row = await s.scalar(select(m.Recommendation).where(m.Recommendation.agent_run_id == run_row.id))
        approval = (
            await s.scalar(select(m.ApprovalRequest).where(m.ApprovalRequest.recommendation_id == rec_row.id))
            if rec_row
            else None
        )
        followup = (
            await s.scalar(select(m.Followup).where(m.Followup.recommendation_id == rec_row.id)) if rec_row else None
        )
        run = {
            "status": run_row.status.value,
            "state": run_row.state,
            "error": run_row.error,
            "trace_id": run_row.trace_id,
        }
        rec = None
        if rec_row:
            rec = {
                "id": str(rec_row.id),
                "status": rec_row.status.value,
                "requires_approval": rec_row.requires_approval,
                "action_type": rec_row.action_type.value,
                "rules": {r["rule"] for r in rec_row.approval_reasons},
                "generated_by": rec_row.generated_by,
                "limitations": rec_row.limitations,
                "grounding": rec_row.grounding,
                "proposed": rec_row.proposed_action,
                "confidence": rec_row.confidence,
            }
    state = run["state"] or {}
    risk = state.get("risk_analysis") or {}
    reasons = {r["code"]: r["points"] for r in risk.get("reasons", [])}
    status_map = {
        "awaiting_approval": "awaiting_approval",
        "completed": "completed",
        "failed": "failed",
        "needs_review": "needs_review",
    }
    checks: dict[str, bool | None] = {}

    checks["workflow_completion"] = (
        status_map.get(run["status"]) == exp.get("status", run["status"])
        if "status" in exp
        else run["status"] != "failed"
    )
    if "risk_levels" in exp or "reasons_include" in exp or "max_points" in exp:
        ok = True
        if "risk_levels" in exp:
            ok &= risk.get("risk_level") in exp["risk_levels"]
        if "reasons_include" in exp:
            ok &= set(exp["reasons_include"]) <= set(reasons)
        for code, cap in exp.get("max_points", {}).items():
            ok &= reasons.get(code, 0) <= cap
        checks["risk_detection_accuracy"] = ok
    if "recommendation" in exp:
        checks["database_update_correctness"] = (rec is not None) == exp["recommendation"]

    if rec is not None:
        if offline and "approval_required" in exp:
            approval_ok = rec["requires_approval"] == exp["approval_required"]
            if "required_role" in exp:
                approval_ok &= approval is not None and approval.required_role == exp["required_role"]
            checks["approval_compliance"] = approval_ok
        else:
            primary = rec["proposed"].get("primary", {})
            recheck = evaluate(
                ActionProposal(
                    ActionType(primary.get("action_type", rec["action_type"])),
                    deal_value=Decimal(str(case["crm"]["amount"])),
                    discount_pct=Decimal(str(primary["discount_pct"])) if primary.get("discount_pct") else None,
                    confidence=rec["confidence"],
                    policy_evidence_found=True,
                    unverified_claims=int(rec["grounding"].get("unverified_count", 0)),
                    injection_suspected="PROMPT_INJECTION_SUSPECTED" in rec["rules"],
                    generated_by_fallback=rec["generated_by"] == "rules_fallback",
                ),
                settings.policy,
            )
            # Policy may require approval for extra reasons (e.g. missing evidence); never less than the recheck.
            checks["approval_compliance"] = rec["requires_approval"] or not recheck.requires_approval
        policy_ok = await _no_unapproved_customer_actions(rec["id"])
        if (offline or not exp.get("offline_only")) and ("rules_include" in exp or "rules_exclude" in exp):
            policy_ok &= set(exp.get("rules_include", [])) <= rec["rules"] and not (
                set(exp.get("rules_exclude", [])) & rec["rules"]
            )
        checks["policy_compliance"] = policy_ok
        if "generated_by" in exp:
            checks["failure_recovery"] = rec["generated_by"] == exp["generated_by"]
        if "limitation_contains" in exp:
            checks["failure_recovery"] = any(
                exp["limitation_contains"] in x for x in rec["limitations"] + state.get("limitations", [])
            )
        if exp.get("hallucination_detected"):
            checks["hallucination_detection"] = int(rec["grounding"].get("unverified_count", 0)) > 0
        if offline and "auto_actions" in exp:
            checks["database_update_correctness"] = followup is not None and rec["status"] == exp.get(
                "recommendation_status", rec["status"]
            )
        elif "database_update_correctness" not in checks:
            checks["database_update_correctness"] = (followup is not None) == ("POLICY_BLOCKED" not in rec["rules"])
    elif exp.get("failure_injected"):
        checks["failure_recovery"] = run["status"] == exp.get("status") and exp.get("error_contains", "") in (
            run["error"] or ""
        )

    calls = await _tool_calls(result["run_id"])
    called = {c.tool for c in calls}
    expected_tools = _expected_tools(run, rec)
    checks["tool_selection_accuracy"] = expected_tools <= called and not ({"send_email", "offer_discount"} & called)
    arg_ok = True
    for c in calls:
        args = c.input or {}
        if c.tool in ("calculate_revenue_risk", "create_followup", "get_opportunity") and "opportunity_id" in args:
            arg_ok &= args["opportunity_id"] == str(refs["opportunity_id"])
        if c.tool == "request_human_approval" and approval is not None:
            arg_ok &= args.get("required_role") == approval.required_role
    if "PRICE_OBJECTION" in reasons and rec is not None:
        docs = [
            d for c in calls if c.tool == "search_knowledge_base" for d in (c.input or {}).get("document_types", [])
        ]
        arg_ok &= "discount_policy" in docs
    checks["tool_argument_accuracy"] = arg_ok

    decision_out: dict[str, Any] | None = None
    if case.get("decision") and approval is not None and "after_decision" in exp:
        d, after = case["decision"], exp["after_decision"]
        principal = sandbox.principals[UserRole(d["by"]).value]
        try:
            decision_out = await decide_approval(
                principal,
                approval.id,
                decision=d["decision"],
                note="eval",
                edits=d.get("edits"),
                deps=ToolDeps(provider=provider),
            )
            error = None
        except AppError as exc:
            error = exc.code.value
        db_ok = True
        if "decision_error" in after:
            db_ok &= error == after["decision_error"]
        else:
            async with get_sessionmaker()() as s:
                rec2 = await s.get(m.Recommendation, uuid.UUID(rec["id"]))
                actions = (await s.scalars(select(m.Action).where(m.Action.recommendation_id == rec2.id))).all()
                customer_actions = [a for a in actions if a.action_type in CUSTOMER_FACING]
                db_ok &= error is None and rec2.status.value == after["recommendation_status"]
                if "execution_ok" in after:
                    db_ok &= bool(decision_out and decision_out["execution"]["ok"]) == after["execution_ok"]
                if "actions" in after:
                    db_ok &= [
                        r["tool"] for r in (decision_out or {}).get("execution", {}).get("results", []) if r["ok"]
                    ] == after["actions"]
                if "revised_total" in after:
                    revised = await s.scalar(
                        select(m.Quote).where(m.Quote.opportunity_id == refs["opportunity_id"], m.Quote.version == 2)
                    )
                    db_ok &= revised is not None and float(revised.total) == after["revised_total"]
                if after.get("verification_passed"):
                    db_ok &= bool(decision_out and decision_out["verification"]["all_passed"])
                if after.get("no_customer_actions"):
                    db_ok &= not customer_actions
            checks["policy_compliance"] = checks.get(
                "policy_compliance", True
            ) and await _no_unapproved_customer_actions(rec["id"])
        checks["database_update_correctness"] = checks.get("database_update_correctness", True) and db_ok

    applicable = {k: v for k, v in checks.items() if v is not None}
    return {
        "case_key": case["key"],
        "description": case["description"],
        "tags": case["tags"],
        "passed": all(applicable.values()),
        "scores": applicable,
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "output": {
            "run_status": run["status"],
            "risk_level": risk.get("risk_level"),
            "risk_score": risk.get("risk_score"),
            "reasons": sorted(reasons),
            "recommendation": rec
            and {
                k: (sorted(v) if isinstance(v, set) else v)
                for k, v in rec.items()
                if k not in ("proposed", "grounding")
            },
            "grounding": rec and rec["grounding"],
            "tools_called": sorted(called),
            "expected_tools": sorted(expected_tools),
            "decision": decision_out and {"status": decision_out["status"]},
            "error": run["error"],
            "trace_id": run["trace_id"],
        },
        "expected": exp,
    }


def aggregate(results: list[dict[str, Any]], live: bool) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    names = sorted({k for r in results for k in r["scores"]})
    for name in names:
        vals = [r["scores"][name] for r in results if name in r["scores"]]
        metrics[name] = {"value": round(sum(vals) / len(vals), 4), "n": len(vals)}
    if live:
        graded = [r for r in results if r["output"].get("grounding")]
        total_claims = sum(int(r["output"]["grounding"].get("total", 0)) for r in graded)
        unverified = sum(int(r["output"]["grounding"].get("unverified_count", 0)) for r in graded)
        if total_claims:
            metrics["hallucination_rate"] = {
                "value": round(unverified / max(total_claims, 1), 4),
                "n": total_claims,
                "description": "unverified policy claims + unsupported email figures / policy claims",
            }
    metrics["case_pass_rate"] = {"value": round(sum(r["passed"] for r in results) / len(results), 4), "n": len(results)}
    return metrics
