"""LLM behaviour per evaluation scenario.

offline mode: a scripted provider returns schema-valid outputs built from the scenario spec (testing the
              orchestration, guardrails and database effects deterministically — not model quality).
live mode:    the real provider is used; only *injected failures* (timeout / malformed) are simulated so the
              failure-recovery cases stay meaningful.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from app.core.errors import ErrorCode, LLMError
from app.evaluation.doubles import ScriptedLLM
from app.llm.base import ChatMessage, LLMProvider, LLMResponse, ToolDefinition

GARBAGE = ["not json at all", '{"title": 1}', "[]"]


def _evidence_id(prompt: str, document_title: str) -> str | None:
    for line in prompt.splitlines():
        match = re.match(r"\[(E\d+)\] (.+?) \(v", line)
        if match and match.group(2) == document_title:
            return match.group(1)
    return None


def scripted_analysis(spec: dict[str, Any], customer_message: str) -> dict[str, Any]:
    msg = customer_message.lower()
    objections = []
    if "price" in msg or "budget" in msg:
        quote = next(
            (s for s in re.split(r"(?<=[.?!])\s+", customer_message) if "price" in s.lower() or "budget" in s.lower()),
            customer_message,
        )
        objections.append({"type": "price", "detail": "Customer wants a lower price", "quote": quote.strip()})
    competitors = (
        [{"name": "Voltrix Systems", "context": "quoted lower for a similar scope"}] if "voltrix" in msg else []
    )
    return {
        "intent": "high" if objections or "?" in msg else "medium",
        "buying_stage": "decision",
        "urgency": "medium",
        "budget_signal": "constrained" if objections else "unknown",
        "objections": objections,
        "competitor_mentions": competitors,
        "decision_maker_status": "engaged",
        "customer_waiting_on": "an answer" if "?" in msg else None,
        "next_action": "follow_up",
        "sentiment": "neutral",
        "summary": "Customer is evaluating the proposal. Scripted offline analysis.",
        "evidence_quotes": [customer_message.split(".")[0].strip()],
        "confidence": 0.85,
    }


def scripted_recommendation(spec: dict[str, Any]):
    def reply(messages: list[ChatMessage]) -> dict[str, Any]:
        prompt = messages[-1].content or ""
        claims, cited = [], []
        for title in spec["claims"]:
            eid = _evidence_id(prompt, title)
            if eid:
                claims.append({"claim": "Discounts above 10% require manager approval.", "evidence_ids": [eid]})
                cited.append(eid)
        if spec["bad_claim"]:
            eid = _evidence_id(prompt, "Discount Authority Policy") or "E1"
            claims.append({"claim": "Installation is always free of charge for every customer.", "evidence_ids": [eid]})
        action, discount = spec["action"], spec["discount"]
        body = None
        if spec["email"] and action in ("send_email", "offer_discount", "create_followup"):
            offer = (
                f" We can offer {discount:g}% off the current quotation."
                if action == "offer_discount" and discount
                else ""
            )
            invented = " The revised price is ₹3,99,999 if you confirm today." if spec["invented_number"] else ""
            body = (
                f"Hi Ritu,\n\nThank you for your message.{offer}{invented} Could we speak tomorrow at 11 am to finalise next steps?"
                "\n\nBest regards,\nEval Rep\nArcline Systems"
            )
        return {
            "title": "Follow up today with a clear next step",
            "what_happened": "Quotation sent; customer replied with a question.",
            "why_risky": "Customer is waiting and the deal is late-stage.",
            "recommendation": "Respond today with a concrete next step.",
            "primary_action": action,
            "proposed_discount_pct": discount if action == "offer_discount" else None,
            "email_subject": "Next steps on your quotation" if body else None,
            "email_body": body,
            "followup_title": "Call customer about the quotation",
            "followup_due_in_hours": 8,
            "expected_outcome": "Customer gets an answer and a next step.",
            "policy_claims": claims,
            "cited_evidence_ids": cited,
            "confidence": spec["confidence"],
            "injection_suspected": spec["injection"],
        }

    return reply


class FaultInjectingProvider(LLMProvider):
    """Wraps a real provider and injects the scenario's failures for specific purposes (live mode)."""

    def __init__(self, inner: LLMProvider, faults: dict[str, str]) -> None:
        self.inner, self.faults = inner, faults
        self.name = inner.name
        self._garbage = {p: list(GARBAGE) for p, f in faults.items() if f == "malformed"}

    @property
    def model(self) -> str:
        return self.inner.model

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        purpose: str,
        response_model: type[BaseModel] | None = None,
        tools: list[ToolDefinition] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        fault = self.faults.get(purpose)
        if fault == "timeout":
            raise LLMError(ErrorCode.LLM_TIMEOUT, f"injected timeout ({purpose})")
        if fault == "malformed" and self._garbage.get(purpose):
            from app.llm.base import LLMUsage  # noqa: PLC0415

            return LLMResponse(content=self._garbage[purpose].pop(0), model=self.model, usage=LLMUsage())
        return await self.inner.complete(
            messages,
            purpose=purpose,
            response_model=response_model,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )


def provider_for(spec: dict[str, Any], customer_message: str, *, live_provider: LLMProvider | None) -> LLMProvider:
    faults = {}
    if spec["analysis"] in ("timeout", "malformed"):
        faults["conversation_analysis"] = spec["analysis"]
    if spec["recommendation"] in ("timeout", "malformed"):
        faults["recommendation"] = spec["recommendation"]
    if live_provider is not None:
        return FaultInjectingProvider(live_provider, faults)

    def plan(kind: str, ok_reply: Any) -> list[Any]:
        mode = spec[kind]
        if mode == "timeout":
            return [LLMError(ErrorCode.LLM_TIMEOUT, "injected timeout")]
        if mode == "malformed":
            return list(GARBAGE)
        return [ok_reply]

    return ScriptedLLM(
        by_purpose={
            "conversation_analysis": plan("analysis", scripted_analysis(spec, customer_message)) * 2,
            "recommendation": plan("recommendation", scripted_recommendation(spec)),
        }
    )
