"""Deterministic knowledge-query planning.

Which policies matter for a deal follows directly from *why* it is at risk, so the queries are derived
from risk reason codes and detected objections with a lookup table — no LLM call, fully reproducible,
and easy to evaluate.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.enums import DocumentType as D


@dataclass(frozen=True)
class PlannedQuery:
    query: str
    doc_types: tuple[D, ...]
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {"query": self.query, "doc_types": [d.value for d in self.doc_types], "reason": self.reason}


_BY_SIGNAL: dict[str, PlannedQuery] = {
    "PRICE_OBJECTION": PlannedQuery(
        "discount approval limits and conditions when a customer says the price is too high",
        (D.DISCOUNT_POLICY, D.OBJECTION_HANDLING),
        "price objection",
    ),
    "COMPETITOR_MENTIONED": PlannedQuery(
        "customer shares a lower competing quotation from a competitor",
        (D.OBJECTION_HANDLING, D.DISCOUNT_POLICY),
        "competitor mentioned",
    ),
    "CUSTOMER_AWAITING_REPLY": PlannedQuery(
        "response time standard for customer questions and follow-up cadence after a quotation",
        (D.SALES_PLAYBOOK,),
        "customer waiting for reply",
    ),
    "QUOTE_UNANSWERED": PlannedQuery(
        "follow-up cadence after a quotation is sent", (D.SALES_PLAYBOOK,), "quote unanswered"
    ),
    "NO_RECENT_CONTACT": PlannedQuery(
        "deals at risk escalation when no contact for several days", (D.SALES_PLAYBOOK,), "no recent contact"
    ),
    "QUOTE_EXPIRING": PlannedQuery(
        "quotation validity and re-issuing expiring quotations", (D.PRICING_POLICY, D.SOP), "quote expiring"
    ),
    "QUOTE_EXPIRED": PlannedQuery(
        "expired quotation must be re-issued as a new version", (D.PRICING_POLICY, D.SOP), "quote expired"
    ),
    "HIGH_VALUE": PlannedQuery(
        "high-value deals customer-facing commercial communication review by sales manager",
        (D.SOP, D.SALES_PLAYBOOK),
        "high-value deal",
    ),
    "TIMING": PlannedQuery(
        "timing or budget objection phased rollout pilot", (D.OBJECTION_HANDLING,), "timing objection"
    ),
}
_ALWAYS = PlannedQuery(
    "follow-up email structure and what must never be written to customers",
    (D.COMMUNICATION_GUIDELINES,),
    "communication rules for any customer message",
)
PRIORITY = (
    "PRICE_OBJECTION",
    "COMPETITOR_MENTIONED",
    "HIGH_VALUE",
    "QUOTE_EXPIRED",
    "QUOTE_EXPIRING",
    "CUSTOMER_AWAITING_REPLY",
    "TIMING",
    "QUOTE_UNANSWERED",
    "NO_RECENT_CONTACT",
)


def plan_queries(
    reason_codes: list[str], objection_types: list[str], *, high_value: bool, max_queries: int = 4
) -> list[PlannedQuery]:
    signals = set(reason_codes)
    if "price" in objection_types:
        signals.add("PRICE_OBJECTION")
    if "competitor" in objection_types:
        signals.add("COMPETITOR_MENTIONED")
    if "timing" in objection_types:
        signals.add("TIMING")
    if high_value:
        signals.add("HIGH_VALUE")
    planned = [_BY_SIGNAL[s] for s in PRIORITY if s in signals]
    # The rule above keeps "always" last but guarantees it a slot.
    return [*planned[: max_queries - 1], _ALWAYS]
