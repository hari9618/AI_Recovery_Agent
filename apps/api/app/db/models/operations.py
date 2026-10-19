"""Audit, LLM usage accounting, ingestion jobs and evaluation storage."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk, pg_enum, utcnow
from app.domain.enums import ActorType, AuditResult, EvalMode, EvalSuite, IngestionStatus, LLMCallStatus


class AuditLog(UUIDPk, Base):
    """Append-only record of every important action (user, agent or system)."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        sa.Index("ix_audit_logs_company_time", "company_id", "occurred_at"),
        sa.Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        sa.Index("ix_audit_logs_customer", "customer_id"),
    )

    # Nullable: some system events (e.g. failed auth) have no tenant.
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE")
    )
    occurred_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    actor_type: Mapped[ActorType] = mapped_column(pg_enum(ActorType, "actor_type"))
    actor_id: Mapped[str | None] = mapped_column(sa.String(100))
    actor_name: Mapped[str | None] = mapped_column(sa.String(200))
    action: Mapped[str] = mapped_column(sa.String(100))
    entity_type: Mapped[str | None] = mapped_column(sa.String(60))
    entity_id: Mapped[str | None] = mapped_column(sa.String(64))
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    agent: Mapped[str | None] = mapped_column(sa.String(80))
    tool: Mapped[str | None] = mapped_column(sa.String(80))
    input: Mapped[dict[str, Any] | None] = mapped_column()
    output: Mapped[dict[str, Any] | None] = mapped_column()
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    result: Mapped[AuditResult] = mapped_column(pg_enum(AuditResult, "audit_result"))
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    trace_id: Mapped[str | None] = mapped_column(sa.String(64))
    latency_ms: Mapped[int | None]


class LLMCall(UUIDPk, Base):
    """Local usage ledger — works even when Langfuse is not configured."""

    __tablename__ = "llm_calls"
    __table_args__ = (sa.Index("ix_llm_calls_company_time", "company_id", "created_at"),)

    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE")
    )
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    purpose: Mapped[str] = mapped_column(sa.String(80))
    provider: Mapped[str] = mapped_column(sa.String(40))
    model: Mapped[str] = mapped_column(sa.String(120))
    status: Mapped[LLMCallStatus] = mapped_column(pg_enum(LLMCallStatus, "llm_call_status"))
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    latency_ms: Mapped[int] = mapped_column(default=0)
    attempts: Mapped[int] = mapped_column(default=1)
    estimated_cost_usd: Mapped[float] = mapped_column(default=0.0)
    error: Mapped[str | None] = mapped_column(sa.Text)
    trace_id: Mapped[str | None] = mapped_column(sa.String(64))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class IngestionJob(UUIDPk, Timestamps, Base):
    __tablename__ = "ingestion_jobs"

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    entity: Mapped[str] = mapped_column(sa.String(40))
    filename: Mapped[str] = mapped_column(sa.String(255))
    status: Mapped[IngestionStatus] = mapped_column(pg_enum(IngestionStatus, "ingestion_status"))
    rows_total: Mapped[int] = mapped_column(default=0)
    rows_inserted: Mapped[int] = mapped_column(default=0)
    rows_updated: Mapped[int] = mapped_column(default=0)
    rows_duplicate: Mapped[int] = mapped_column(default=0)
    rows_rejected: Mapped[int] = mapped_column(default=0)
    # [{row, field, message}] capped to keep the record small
    errors: Mapped[list[Any]] = mapped_column(default=list)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class EvaluationRun(UUIDPk, Timestamps, Base):
    __tablename__ = "evaluation_runs"

    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    suite: Mapped[EvalSuite] = mapped_column(pg_enum(EvalSuite, "eval_suite"))
    mode: Mapped[EvalMode] = mapped_column(pg_enum(EvalMode, "eval_mode"))
    dataset_version: Mapped[str] = mapped_column(sa.String(40))
    model: Mapped[str | None] = mapped_column(sa.String(120))
    status: Mapped[str] = mapped_column(sa.String(20))  # running | completed | failed
    # {metric_name: {value, n, description}} — only measured values, never placeholders.
    metrics: Mapped[dict[str, Any]] = mapped_column(default=dict)
    cases_total: Mapped[int] = mapped_column(default=0)
    cases_passed: Mapped[int] = mapped_column(default=0)
    report_path: Mapped[str | None] = mapped_column(sa.String(500))
    notes: Mapped[str | None] = mapped_column(sa.Text)
    is_demo_data: Mapped[bool] = mapped_column(default=True)
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class EvaluationCase(UUIDPk, Base):
    __tablename__ = "evaluation_cases"
    __table_args__ = (sa.UniqueConstraint("suite", "case_key", name="uq_evaluation_cases_suite_key"),)

    suite: Mapped[EvalSuite] = mapped_column(pg_enum(EvalSuite, "eval_suite"))
    case_key: Mapped[str] = mapped_column(sa.String(120))
    description: Mapped[str] = mapped_column(sa.Text)
    input: Mapped[dict[str, Any]] = mapped_column(default=dict)
    expected: Mapped[dict[str, Any]] = mapped_column(default=dict)
    tags: Mapped[list[Any]] = mapped_column(default=list)


class EvaluationResult(UUIDPk, Base):
    __tablename__ = "evaluation_results"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("evaluation_runs.id", ondelete="CASCADE"), index=True
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("evaluation_cases.id", ondelete="CASCADE")
    )
    passed: Mapped[bool | None]
    scores: Mapped[dict[str, Any]] = mapped_column(default=dict)
    output: Mapped[dict[str, Any]] = mapped_column(default=dict)
    error: Mapped[str | None] = mapped_column(sa.Text)
    latency_ms: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
