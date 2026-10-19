"""Prompt for conversation intelligence. Versioned via domain.conversation.PROMPT_VERSION."""

from __future__ import annotations

from app.llm.base import ChatMessage
from app.security.injection import UNTRUSTED_CONTENT_RULES, untrusted_block

SYSTEM = f"""\
You are a B2B sales-conversation analyst. You read one customer conversation and extract structured
signals that a revenue team uses to prioritise follow-ups.

{UNTRUSTED_CONTENT_RULES}

ANALYSIS RULES:
- Judge the CUSTOMER's state. Messages labelled SALES_REP are context only.
- intent: high = explicit buying signals (asks for PO/payment details, installation dates, says they want
  to proceed, internal deadline); medium = engaged but undecided; low = deprioritised, no timeline, on hold.
- objections: only what the customer actually raised. Each needs a verbatim `quote` copied exactly from
  the customer's message.
- competitor_mentions: named or unnamed competing vendors the customer mentioned; context = what they said
  (e.g. the competing price).
- customer_waiting_on: what the customer is still waiting for from the sales team, if their last
  question/request has not been answered; otherwise null.
- evidence_quotes: up to 3 short verbatim customer quotes (copy exactly, do not paraphrase).
- summary: two factual sentences; no speculation, no advice.
- confidence: lower it when the conversation is short, ambiguous or contradictory.
Return only the JSON object."""


def build_messages(transcript: str, *, customer_name: str, deal_context: str) -> list[ChatMessage]:
    user = (
        "USER REQUEST: Analyse the conversation below.\n\n"
        f"CRM CONTEXT (trusted, from our database): customer={customer_name}; {deal_context}\n\n"
        + untrusted_block("conversation", transcript)
    )
    return [ChatMessage(role="system", content=SYSTEM), ChatMessage(role="user", content=user)]
