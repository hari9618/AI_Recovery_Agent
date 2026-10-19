"""Structured output contract for conversation intelligence (validated with Pydantic).

The LLM must return exactly this shape; anything else is rejected, repaired via re-ask, or replaced
by a labelled fallback. `evidence_quotes` must be verbatim customer text — the service checks that
each quote actually appears in the transcript and drops (and reports) any that do not.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PROMPT_VERSION = "conv-v1"

Level = Literal["high", "medium", "low"]


class Objection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["price", "competitor", "timing", "authority", "need", "technical", "trust", "other"]
    detail: str = Field(description="One sentence describing the objection")
    quote: str = Field(description="Verbatim customer text that shows the objection")


class CompetitorMention(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(description="Competitor name as written by the customer, or 'unnamed'")
    context: str = Field(description="What the customer said about them, e.g. their quoted price")


class ConversationInsight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Level = Field(description="Customer's buying intent")
    buying_stage: Literal["awareness", "consideration", "evaluation", "decision", "post_purchase", "unknown"]
    urgency: Level
    budget_signal: Literal["positive", "constrained", "negative", "unknown"]
    objections: list[Objection]
    competitor_mentions: list[CompetitorMention]
    decision_maker_status: Literal["engaged", "not_engaged", "unknown"]
    customer_waiting_on: str | None = Field(
        description="What the customer is waiting for from us (answer/quote/revision), or null"
    )
    next_action: Literal[
        "follow_up", "answer_question", "send_revised_quote", "schedule_call", "escalate", "nurture", "no_action"
    ]
    sentiment: Literal["positive", "neutral", "negative"]
    summary: str = Field(description="Two sentences, factual, no speculation")
    evidence_quotes: list[str] = Field(description="Up to 3 verbatim customer quotes supporting the analysis")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in this analysis, 0–1")

    @property
    def has_price_objection(self) -> bool:
        return any(o.type == "price" for o in self.objections)

    @property
    def competitor_names(self) -> list[str]:
        return [c.name for c in self.competitor_mentions if c.name and c.name.lower() != "unnamed"]
