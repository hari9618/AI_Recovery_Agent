"""Runs the Revenue Recovery workflows and owns their persistence.

- An `agent_runs` row is committed first, so even a crashed run is visible.
- Live progress: each node's step record is written through a *separate* short session, so the UI can
  poll progress without the main transaction committing half-finished business writes.
- Business writes (risk, recommendation, follow-up, approval, audit) commit together at the end.
- Approval decisions re-hydrate the saved state and run the execution graph.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import execution_graph, investigation_graph
from app.agents.state import RevenueRecoveryState
from app.core.errors import AppError, ErrorCode, NotFoundError
from app.db import models as m
from app.db.session import get_sessionmaker
from app.domain.enums import (
    ActionType,
    ActorType,
    AgentRunStatus,
    ApprovalStatus,
    AuditResult,
    RecommendationStatus,
    UserRole,
)
from app.domain.policy import ActionProposal, evaluate
from app.llm.ledger import llm_call_context
from app.observability.tracing import get_tracer
from app.security.auth import Principal
from app.services.audit import record_audit
from app.services.company import get_company_settings
from app.tools import ToolContext, ToolDeps

logger = logging.getLogger(__name__)
WORKFLOW = "revenue_recovery"
_STATUS_MAP = {
    "awaiting_approval": AgentRunStatus.AWAITING_APPROVAL,
    "executed": AgentRunStatus.COMPLETED,
    "no_action_needed": AgentRunStatus.COMPLETED,
    "blocked": AgentRunStatus.NEEDS_REVIEW,
    "failed": AgentRunStatus.FAILED,
}


class _StepSink:
    """Persists node progress immediately in its own transaction."""

    def __init__(self, run_id: uuid.UUID) -> None:
        self.run_id = run_id
        self.steps: list[dict[str, Any]] = []

    async def __call__(self, step: dict[str, Any]) -> None:
        existing = next((s for s in self.steps if s is step), None)
        if existing is None:
            self.steps.append(step)
        try:
            async with get_sessionmaker()() as s:
                run = await s.get(m.AgentRun, self.run_id)
                if run is not None:
                    run.steps = [dict(x) for x in self.steps]
                    await s.commit()
        except Exception:  # noqa: BLE001 - progress reporting must not break the run
            logger.warning("could not persist step progress", exc_info=True)


def _serialisable(state: dict[str, Any]) -> dict[str, Any]:
    import json  # noqa: PLC0415

    return json.loads(json.dumps(state, default=str))


async def create_run(principal: Principal, opportunity_id: uuid.UUID, workflow: str = WORKFLOW) -> uuid.UUID:
    async with get_sessionmaker()() as s:
        opp = await s.scalar(select(m.Opportunity).where(m.Opportunity.id == opportunity_id, m.Opportunity.company_id == principal.company_id))
        if opp is None:
            raise NotFoundError("opportunity", opportunity_id)
        run = m.AgentRun(company_id=principal.company_id, opportunity_id=opp.id, customer_id=opp.customer_id,
                         triggered_by=principal.user_id, workflow=workflow, status=AgentRunStatus.RUNNING, steps=[], state={})
        s.add(run)
        await s.commit()
        return run.id


async def _finalise_usage(session: AsyncSession, run: m.AgentRun) -> None:
    calls, tin, tout, cost = (await session.execute(
        select(func.count(), func.coalesce(func.sum(m.LLMCall.input_tokens), 0), func.coalesce(func.sum(m.LLMCall.output_tokens), 0),
               func.coalesce(func.sum(m.LLMCall.estimated_cost_usd), 0.0)).where(m.LLMCall.agent_run_id == run.id)
    )).one()
    run.llm_calls, run.input_tokens, run.output_tokens, run.cost_usd = int(calls), int(tin), int(tout), float(cost)


async def execute_run(run_id: uuid.UUID, principal: Principal, *, force: bool = False, deps: ToolDeps | None = None) -> dict[str, Any]:
    """Run the investigation graph for an existing `agent_runs` row. Never raises: failures are recorded."""
    tracer = get_tracer()
    sink = _StepSink(run_id)
    started = time.perf_counter()
    async with get_sessionmaker()() as session:
        run = await session.get(m.AgentRun, run_id)
        if run is None:
            raise NotFoundError("agent run", run_id)
        state: RevenueRecoveryState = {"run_id": str(run.id), "company_id": str(run.company_id),
                                       "opportunity_id": str(run.opportunity_id), "force": force, "limitations": [], "errors": []}
        final: dict[str, Any] = dict(state)
        with tracer.trace("RevenueRecovery", user_id=str(principal.user_id), session_id=str(run.id),
                          tags=["revenue-recovery", "investigation"], metadata={"opportunity_id": run.opportunity_id},
                          input={"opportunity_id": str(run.opportunity_id), "force": force}) as root, \
                llm_call_context(company_id=run.company_id, agent_run_id=run.id, trace_id=root.trace_id):
            ctx = ToolContext(session=session, company_id=run.company_id, actor_type=ActorType.AGENT, actor_id=str(principal.user_id),
                              actor_name=principal.name, agent="RevenueRecoveryAgent", agent_run_id=run.id, deps=deps or ToolDeps())
            try:
                final = await investigation_graph().ainvoke(
                    state, config={"configurable": {"ctx": ctx, "step_sink": sink, "trace_id": root.trace_id}})
                status = _STATUS_MAP.get(final.get("status", ""), AgentRunStatus.COMPLETED)
                error = "; ".join(final.get("errors", [])) or None
            except Exception as exc:  # noqa: BLE001 - recorded on the run, surfaced in the UI
                logger.exception("agent run failed", extra={"run_id": str(run_id)})
                await session.rollback()
                run = await session.get(m.AgentRun, run_id)
                status, error = AgentRunStatus.FAILED, f"{exc.__class__.__name__}: {exc}"[:2000]
                root.error(error)
            root.update(output={"status": status.value, "recommendation_id": final.get("recommendation_id"),
                                "approval_required": final.get("approval_required"), "risk_level": final.get("risk_analysis", {}).get("risk_level")})
            if final.get("grounding", {}).get("grounding_score") is not None:
                root.score("grounding_score", float(final["grounding"]["grounding_score"]))
            if final.get("recommendation"):
                root.score("recommendation_confidence", float(final["recommendation"].get("confidence", 0)))
            trace_id = root.trace_id
        assert run is not None
        run.status, run.error = status, error
        run.state = _serialisable({k: v for k, v in final.items() if k != "crm_context"} | {"crm_context": final.get("crm_context")})
        run.steps = [dict(x) for x in sink.steps]
        run.trace_id, run.trace_url = trace_id, tracer.trace_url(trace_id)
        run.latency_ms, run.finished_at = int((time.perf_counter() - started) * 1000), datetime.now(UTC)
        await _finalise_usage(session, run)
        record_audit(session, company_id=run.company_id, action="agent_run.finished", actor_type=ActorType.AGENT,
                     actor_id=str(principal.user_id), agent="RevenueRecoveryAgent", entity_type="agent_run", entity_id=run.id,
                     customer_id=run.customer_id, output={"status": status.value, "error": error,
                                                          "recommendation_id": final.get("recommendation_id")},
                     result=AuditResult.FAILURE if status == AgentRunStatus.FAILED else AuditResult.SUCCESS,
                     agent_run_id=run.id, trace_id=trace_id, latency_ms=run.latency_ms)
        await session.commit()
    tracer.flush()
    return {"run_id": str(run_id), "status": status.value, "error": error}


async def run_recovery(principal: Principal, opportunity_id: uuid.UUID, *, force: bool = False, deps: ToolDeps | None = None) -> dict[str, Any]:
    run_id = await create_run(principal, opportunity_id)
    return await execute_run(run_id, principal, force=force, deps=deps)


_ROLE_RANK = {UserRole.SALES_REP: 0, UserRole.MANAGER: 1, UserRole.ADMIN: 2, UserRole.OWNER: 3}


async def decide_approval(
    principal: Principal,
    approval_id: uuid.UUID,
    *,
    decision: str,
    note: str | None = None,
    edits: dict[str, Any] | None = None,
    deps: ToolDeps | None = None,
) -> dict[str, Any]:
    """approve | reject (optionally with human edits to subject/body/discount). Approve runs the execution graph."""
    if decision not in ("approve", "reject"):
        raise AppError(ErrorCode.INVALID_REQUEST, "decision must be 'approve' or 'reject'")
    tracer = get_tracer()
    async with get_sessionmaker()() as session:
        approval = await session.scalar(select(m.ApprovalRequest).where(
            m.ApprovalRequest.id == approval_id, m.ApprovalRequest.company_id == principal.company_id).with_for_update())
        if approval is None:
            raise NotFoundError("approval request", approval_id)
        if approval.status != ApprovalStatus.PENDING:
            raise AppError(ErrorCode.CONFLICT, f"Approval already {approval.status.value}")
        required = UserRole(approval.required_role)
        if _ROLE_RANK[principal.role] < _ROLE_RANK[required]:
            raise AppError(ErrorCode.FORBIDDEN, f"This approval requires role {required.value} or higher")
        rec = await session.get(m.Recommendation, approval.recommendation_id)
        assert rec is not None
        run = await session.get(m.AgentRun, rec.agent_run_id) if rec.agent_run_id else None
        approval.decided_by, approval.decided_at, approval.decision_note = principal.user_id, datetime.now(UTC), note

        if decision == "reject":
            approval.status, rec.status = ApprovalStatus.REJECTED, RecommendationStatus.REJECTED
            if run is not None:
                run.status = AgentRunStatus.COMPLETED
            record_audit(session, company_id=principal.company_id, action="approval.rejected", actor_type=ActorType.USER,
                         actor_id=str(principal.user_id), actor_name=principal.name, entity_type="approval_request", entity_id=approval.id,
                         customer_id=rec.customer_id, input={"note": note}, approval_request_id=approval.id, result=AuditResult.SUCCESS,
                         agent_run_id=rec.agent_run_id)
            await session.commit()
            return {"approval_id": str(approval.id), "status": "rejected"}

        state: dict[str, Any] = dict(run.state) if run and run.state else {}
        primary = dict(state.get("proposed_action", rec.proposed_action).get("primary", {}))
        if edits:
            allowed = {k: v for k, v in edits.items() if k in ("email_subject", "email_body", "discount_pct") and v is not None}
            primary |= allowed
            approval.edited_payload = allowed
            if "email_subject" in allowed:
                rec.draft_subject = allowed["email_subject"]
            if "email_body" in allowed:
                rec.draft_body = allowed["email_body"]
            if "discount_pct" in allowed and primary.get("action_type") == ActionType.OFFER_DISCOUNT.value:
                # A human edit is still subject to policy: re-evaluate the authority needed for the new discount.
                opp = await session.get(m.Opportunity, rec.opportunity_id)
                settings = await get_company_settings(session, principal.company_id)
                recheck = evaluate(ActionProposal(ActionType.OFFER_DISCOUNT, deal_value=opp.amount if opp else Decimal("0"),
                                                  discount_pct=Decimal(str(allowed["discount_pct"]))), settings.policy)
                if not recheck.allowed:
                    raise AppError(ErrorCode.POLICY_BLOCKED, "; ".join(f["message"] for f in recheck.reasons))
                if recheck.required_role and _ROLE_RANK[principal.role] < _ROLE_RANK[recheck.required_role]:
                    raise AppError(ErrorCode.FORBIDDEN, f"An edited discount of {allowed['discount_pct']}% requires role "
                                                        f"{recheck.required_role.value}")
        approval.status, rec.status = ApprovalStatus.APPROVED, RecommendationStatus.APPROVED
        record_audit(session, company_id=principal.company_id, action="approval.approved", actor_type=ActorType.USER,
                     actor_id=str(principal.user_id), actor_name=principal.name, entity_type="approval_request", entity_id=approval.id,
                     customer_id=rec.customer_id, input={"note": note, "edits": approval.edited_payload}, approval_request_id=approval.id,
                     result=AuditResult.SUCCESS, agent_run_id=rec.agent_run_id)
        await session.flush()

        exec_state: RevenueRecoveryState = {
            "run_id": str(rec.agent_run_id), "company_id": str(principal.company_id), "opportunity_id": str(rec.opportunity_id),
            "customer_id": str(rec.customer_id), "recommendation_id": str(rec.id), "approval_request_id": str(approval.id),
            "proposed_action": {"primary": primary, "internal": rec.proposed_action.get("internal", [])},
            "recommendation": {"title": rec.title}, "limitations": [], "errors": [],
        }
        with tracer.trace("RevenueRecovery.execute", user_id=str(principal.user_id), session_id=str(rec.agent_run_id),
                          tags=["revenue-recovery", "execution", "human-approved"],
                          input={"approval_id": str(approval.id), "edited": bool(approval.edited_payload)}) as root:
            ctx = ToolContext(session=session, company_id=principal.company_id, actor_type=ActorType.USER, actor_id=str(principal.user_id),
                              actor_name=principal.name, agent="RevenueRecoveryAgent", agent_run_id=rec.agent_run_id, deps=deps or ToolDeps())
            final = await execution_graph().ainvoke(exec_state, config={"configurable": {"ctx": ctx, "trace_id": root.trace_id}})
            root.update(output={"execution": final.get("execution_result"), "verification": final.get("verification_result")})
            root.score("human_approved", 1)
        if run is not None:
            run.status = AgentRunStatus.COMPLETED if final.get("status") == "executed" else AgentRunStatus.FAILED
            run.state = _serialisable({**state, "execution_result": final.get("execution_result"),
                                       "verification_result": final.get("verification_result"), "approval_decision": "approved"})
        await session.commit()
    tracer.flush()
    return {"approval_id": str(approval_id), "status": "approved", "execution": final.get("execution_result"),
            "verification": final.get("verification_result")}
