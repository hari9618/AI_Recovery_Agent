"""Audit trail. Records are added to the caller's transaction so they commit (or roll back) with
the change they describe; failures to *write business data* therefore never leave orphan audit rows."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog
from app.domain.enums import ActorType, AuditResult

_MAX_PAYLOAD_CHARS = 8000


def _jsonable(value: Any) -> Any:
    """Make tool inputs/outputs JSON-safe and bounded in size."""
    if value is None:
        return None
    text = json.dumps(value, default=lambda o: str(o) if isinstance(o, (uuid.UUID, Decimal)) else repr(o))
    if len(text) > _MAX_PAYLOAD_CHARS:
        return {"truncated": True, "preview": text[:_MAX_PAYLOAD_CHARS]}
    return json.loads(text)


def record_audit(
    session: AsyncSession,
    *,
    company_id: uuid.UUID | None,
    action: str,
    actor_type: ActorType,
    result: AuditResult = AuditResult.SUCCESS,
    actor_id: str | None = None,
    actor_name: str | None = None,
    entity_type: str | None = None,
    entity_id: Any = None,
    customer_id: uuid.UUID | None = None,
    agent: str | None = None,
    tool: str | None = None,
    input: Any = None,  # noqa: A002
    output: Any = None,
    approval_request_id: uuid.UUID | None = None,
    agent_run_id: uuid.UUID | None = None,
    trace_id: str | None = None,
    latency_ms: int | None = None,
) -> AuditLog:
    row = AuditLog(
        company_id=company_id,
        actor_type=actor_type,
        actor_id=actor_id,
        actor_name=actor_name,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        customer_id=customer_id,
        agent=agent,
        tool=tool,
        input=_jsonable(input),
        output=_jsonable(output),
        approval_request_id=approval_request_id,
        result=result,
        agent_run_id=agent_run_id,
        trace_id=trace_id,
        latency_ms=latency_ms,
    )
    session.add(row)
    return row
