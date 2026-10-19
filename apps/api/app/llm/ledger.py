"""Local LLM usage ledger (`llm_calls` table).

Works independently of Langfuse so cost/latency/token dashboards function even when tracing is
off. The tenant / agent-run association comes from a context variable set by the caller, so
deeply nested code does not need to thread IDs through every signature.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

from app.domain.enums import LLMCallStatus
from app.llm.base import LLMUsage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMCallContext:
    company_id: uuid.UUID | None = None
    agent_run_id: uuid.UUID | None = None
    trace_id: str | None = None


_DEFAULT_CONTEXT = LLMCallContext()  # frozen dataclass: safe as a shared default
_ctx: contextvars.ContextVar[LLMCallContext] = contextvars.ContextVar("llm_call_context", default=_DEFAULT_CONTEXT)
# Tests and offline evaluation can disable persistence.
_enabled: contextvars.ContextVar[bool] = contextvars.ContextVar("llm_ledger_enabled", default=True)


@contextlib.contextmanager
def llm_call_context(**kwargs: object) -> Iterator[LLMCallContext]:
    current = _ctx.get()
    new = LLMCallContext(**{**current.__dict__, **{k: v for k, v in kwargs.items() if v is not None}})
    token = _ctx.set(new)
    try:
        yield new
    finally:
        _ctx.reset(token)


@contextlib.contextmanager
def ledger_disabled() -> Iterator[None]:
    token = _enabled.set(False)
    try:
        yield
    finally:
        _enabled.reset(token)


async def record_llm_call(
    *,
    purpose: str,
    provider: str,
    model: str,
    status: LLMCallStatus,
    usage: LLMUsage,
    attempts: int = 1,
    error: str | None = None,
) -> None:
    """Persist one logical call. Never raises: accounting must not break the workflow."""
    if not _enabled.get():
        return
    ctx = _ctx.get()
    try:
        from app.db.models import LLMCall  # noqa: PLC0415
        from app.db.session import get_sessionmaker  # noqa: PLC0415

        async with get_sessionmaker()() as session:
            session.add(
                LLMCall(
                    company_id=ctx.company_id,
                    agent_run_id=ctx.agent_run_id,
                    purpose=purpose,
                    provider=provider,
                    model=model,
                    status=status,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    latency_ms=usage.latency_ms,
                    attempts=attempts,
                    estimated_cost_usd=usage.estimated_cost_usd,
                    error=(error or None) and error[:2000],
                    trace_id=ctx.trace_id,
                )
            )
            await session.commit()
    except Exception:  # noqa: BLE001
        logger.warning("failed to record llm call", exc_info=True)
