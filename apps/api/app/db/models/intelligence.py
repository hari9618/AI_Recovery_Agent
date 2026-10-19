"""Risk assessments, agent runs, recommendations, approvals and executed actions."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import MONEY, Base, Timestamps, UUIDPk, company_fk, pg_enum, utcnow
from app.domain.enums import (
    ActionStatus,
    ActionType,
    AgentRunStatus,
    ApprovalStatus,
    RecommendationStatus,
    RiskLevel,
)


class RevenueRisk(UUIDPk, Base):
    """Output of the deterministic Revenue Risk Engine for one opportunity at one point in time.

    History is kept; exactly one row per opportunity has `is_current = true`.
    """

    __tablename__ = "revenue_risks"
    __table_args__ = (
        sa.Index("ix_revenue_risks_current_level", "company_id", "is_current", "risk_level"),
        sa.Index(
            "uq_revenue_risks_one_current",
            "opportunity_id",
            unique=True,
            postgresql_where=sa.text("is_current"),
        ),
        sa.CheckConstraint("risk_score BETWEEN 0 AND 100", name="score_range"),
    )

    company_id: Mapped[uuid.UUID] = company_fk()
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    risk_score: Mapped[int]
    risk_level: Mapped[RiskLevel] = mapped_column(pg_enum(RiskLevel, "risk_level"))
    revenue_at_risk: Mapped[Decimal] = mapped_column(MONEY)
    weighted_revenue_at_risk: Mapped[Decimal] = mapped_column(MONEY)
    purchase_probability: Mapped[float]
    # [{code, label, points, evidence:{...}, source}] — see domain.risk.ReasonCode
    reason_codes: Mapped[list[Any]] = mapped_column(default=list)
    # Raw signal values the score was computed from (for reproducibility).
    signals: Mapped[dict[str, Any]] = mapped_column(default=dict)
    recommended_next_step: Mapped[str] = mapped_column(sa.String(255))
    engine_version: Mapped[str] = mapped_column(sa.String(20))
    is_current: Mapped[bool] = mapped_column(default=True)
    computed_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class AgentRun(UUIDPk, Timestamps, Base):
    __tablename__ = "agent_runs"
    __table_args__ = (sa.Index("ix_agent_runs_company_created", "company_id", "created_at"),)

    company_id: Mapped[uuid.UUID] = company_fk()
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("opportunities.id", ondelete="SET NULL"), index=True
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="SET NULL")
    )
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    workflow: Mapped[str] = mapped_column(sa.String(60))
    status: Mapped[AgentRunStatus] = mapped_column(pg_enum(AgentRunStatus, "agent_run_status"))
    # Ordered node log: [{node, status, started_at, latency_ms, summary, error}]
    steps: Mapped[list[Any]] = mapped_column(default=list)
    # Final serialisable RevenueRecoveryState snapshot (for audit / resume of execution graph).
    state: Mapped[dict[str, Any]] = mapped_column(default=dict)
    error: Mapped[str | None] = mapped_column(sa.Text)
    trace_id: Mapped[str | None] = mapped_column(sa.String(64))
    trace_url: Mapped[str | None] = mapped_column(sa.String(500))
    llm_calls: Mapped[int] = mapped_column(default=0)
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    cost_usd: Mapped[float] = mapped_column(default=0.0)
    latency_ms: Mapped[int | None]
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class Recommendation(UUIDPk, Timestamps, Base):
    __tablename__ = "recommendations"
    __table_args__ = (sa.Index("ix_recommendations_company_status", "company_id", "status"),)

    company_id: Mapped[uuid.UUID] = company_fk()
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    risk_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("revenue_risks.id", ondelete="SET NULL")
    )
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("agent_runs.id", ondelete="SET NULL"), index=True
    )
    action_type: Mapped[ActionType] = mapped_column(pg_enum(ActionType, "action_type"))
    status: Mapped[RecommendationStatus] = mapped_column(pg_enum(RecommendationStatus, "recommendation_status"))
    title: Mapped[str] = mapped_column(sa.String(255))
    # Explainability block — WHAT happened / WHY risky / WHAT we recommend / WHAT happens if approved.
    what_happened: Mapped[str] = mapped_column(sa.Text)
    why_risky: Mapped[str] = mapped_column(sa.Text)
    recommendation: Mapped[str] = mapped_column(sa.Text)
    expected_outcome: Mapped[str] = mapped_column(sa.Text)
    # [{kind: crm|conversation|knowledge, ref, label, quote, source_document, source_section, score}]
    evidence: Mapped[list[Any]] = mapped_column(default=list)
    proposed_action: Mapped[dict[str, Any]] = mapped_column(default=dict)
    draft_subject: Mapped[str | None] = mapped_column(sa.String(255))
    draft_body: Mapped[str | None] = mapped_column(sa.Text)
    confidence: Mapped[float]
    requires_approval: Mapped[bool] = mapped_column(default=False)
    # [{rule, message}] from the deterministic policy engine
    approval_reasons: Mapped[list[Any]] = mapped_column(default=list)
    grounding: Mapped[dict[str, Any]] = mapped_column(default=dict)
    limitations: Mapped[list[Any]] = mapped_column(default=list)
    generated_by: Mapped[str] = mapped_column(sa.String(40), default="llm")
    model: Mapped[str | None] = mapped_column(sa.String(120))
    trace_id: Mapped[str | None] = mapped_column(sa.String(64))


class ApprovalRequest(UUIDPk, Timestamps, Base):
    __tablename__ = "approval_requests"
    __table_args__ = (sa.Index("ix_approval_requests_company_status", "company_id", "status"),)

    company_id: Mapped[uuid.UUID] = company_fk()
    recommendation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("recommendations.id", ondelete="CASCADE"), unique=True
    )
    status: Mapped[ApprovalStatus] = mapped_column(pg_enum(ApprovalStatus, "approval_status"))
    reasons: Mapped[list[Any]] = mapped_column(default=list)
    risk_summary: Mapped[str] = mapped_column(sa.Text)
    required_role: Mapped[str] = mapped_column(sa.String(20), default="manager")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(sa.Text)
    # Human edits applied before approval (subject/body/discount/etc.).
    edited_payload: Mapped[dict[str, Any] | None] = mapped_column()


class Action(UUIDPk, Timestamps, Base):
    __tablename__ = "actions"
    __table_args__ = (sa.Index("ix_actions_company_status", "company_id", "status"),)

    company_id: Mapped[uuid.UUID] = company_fk()
    recommendation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("recommendations.id", ondelete="SET NULL"), index=True
    )
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("approval_requests.id", ondelete="SET NULL")
    )
    action_type: Mapped[ActionType] = mapped_column(pg_enum(ActionType, "action_type"))
    status: Mapped[ActionStatus] = mapped_column(pg_enum(ActionStatus, "action_status"))
    input: Mapped[dict[str, Any]] = mapped_column(default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(default=dict)
    automated: Mapped[bool] = mapped_column(default=False)
    executed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    executed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(sa.Text)
    # Opportunity value at the time of action; used by ROI attribution if the deal is later won.
    opportunity_value: Mapped[Decimal | None] = mapped_column(MONEY)
