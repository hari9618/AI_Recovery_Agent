"""Typed, explicit workflow state. No hidden memory: everything a node needs is in here."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class RevenueRecoveryState(TypedDict, total=False):
    # identity
    run_id: str
    company_id: str
    opportunity_id: str
    customer_id: str
    force: bool  # run the full workflow even when risk is LOW
    # gathered context (deterministic)
    crm_context: dict[str, Any]
    conversation_context: dict[str, Any]
    risk_analysis: dict[str, Any]
    # knowledge
    retrieval_queries: list[dict[str, Any]]
    retrieved_context: list[dict[str, Any]]
    withheld_evidence: list[dict[str, Any]]
    # reasoning (LLM) + checks (deterministic)
    recommendation: dict[str, Any]
    grounding: dict[str, Any]
    proposed_action: dict[str, Any]
    policy_check: dict[str, Any]
    approval_required: bool
    # persistence / execution
    recommendation_id: str
    approval_request_id: str
    internal_actions: list[dict[str, Any]]
    execution_result: dict[str, Any]
    verification_result: dict[str, Any]
    # bookkeeping
    status: str
    limitations: Annotated[list[str], operator.add]
    errors: Annotated[list[str], operator.add]
