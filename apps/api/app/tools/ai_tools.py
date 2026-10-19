"""Tools that call the LLM (declared with `calls_llm=True`)."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel

from app.services.conversation_intelligence import analyze_conversation as run_analysis
from app.tools.base import REGISTRY, Effects, Tool, ToolContext


class AnalyzeIn(BaseModel):
    conversation_id: uuid.UUID
    force: bool = False


class AnalyzeOut(BaseModel):
    conversation_id: str
    status: str
    cached: bool
    model: str
    insight: dict[str, Any] | None
    needs_review: bool
    dropped_quotes: list[str]
    injection_flags: list[dict[str, str]]
    limitations: list[str] = []


async def analyze_conversation(ctx: ToolContext, a: AnalyzeIn) -> AnalyzeOut:
    out = await run_analysis(
        ctx.session,
        ctx.deps.llm(),
        company_id=ctx.company_id,
        conversation_id=a.conversation_id,
        force=a.force,
        actor_id=ctx.actor_id,
    )
    limitations = []
    if out.dropped_quotes:
        limitations.append(
            f"{len(out.dropped_quotes)} quote(s) from the model were not found in the transcript and were removed."
        )
    if out.injection_flags:
        limitations.append("Conversation contains instruction-like text (possible prompt injection).")
    if out.insight is None:
        limitations.append("LLM analysis failed validation; keyword heuristics are used instead.")
    return AnalyzeOut(
        conversation_id=str(out.conversation_id),
        status=out.status.value,
        cached=out.cached,
        model=out.model,
        insight=out.insight.model_dump() if out.insight else None,
        needs_review=out.needs_review,
        dropped_quotes=out.dropped_quotes,
        injection_flags=out.injection_flags,
        limitations=limitations,
    )


REGISTRY.register(
    Tool(
        "analyze_conversation",
        "Analyse conversation",
        "LLM analysis of a transcript: intent, objections, competitor mentions, sentiment (cached per transcript).",
        AnalyzeIn,
        AnalyzeOut,
        analyze_conversation,
        effects=Effects(writes_crm=True, calls_llm=True, idempotent=True),
        source="llm",
        untrusted_content=True,
    )
)
