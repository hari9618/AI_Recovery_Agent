"""Revenue Risk Engine — deterministic, explainable scoring. No I/O, no LLM.

`assess(signals, settings)` turns measured facts about one open opportunity into a 0–100 score,
a level, money at risk and a list of reason codes. Each reason states how many points it added and
the evidence values it used, so the score can always be reproduced and explained.

The LLM never produces a number here. Conversation-derived signals (intent, competitor mention,
price objection) are *inputs* — taken from stored LLM analysis when available or from a labelled
keyword heuristic otherwise — and every reason records which source it came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any

from app.domain.enums import OpportunityStage, RiskLevel, SignalSource
from app.domain.settings import CompanySettings, DayBand

ENGINE_VERSION = "1.0.0"


class ReasonCode(StrEnum):
    CUSTOMER_AWAITING_REPLY = "CUSTOMER_AWAITING_REPLY"
    NO_RECENT_CONTACT = "NO_RECENT_CONTACT"
    QUOTE_UNANSWERED = "QUOTE_UNANSWERED"
    QUOTE_EXPIRING = "QUOTE_EXPIRING"
    QUOTE_EXPIRED = "QUOTE_EXPIRED"
    OVERDUE_FOLLOWUP = "OVERDUE_FOLLOWUP"
    COMPETITOR_MENTIONED = "COMPETITOR_MENTIONED"
    PRICE_OBJECTION = "PRICE_OBJECTION"
    HIGH_INTENT_STALLED = "HIGH_INTENT_STALLED"
    NEGATIVE_SENTIMENT = "NEGATIVE_SENTIMENT"
    LOW_INTENT = "LOW_INTENT"
    LATE_STAGE = "LATE_STAGE"
    CLOSE_DATE_PASSED = "CLOSE_DATE_PASSED"


# When several reasons fire, the next step is chosen from the highest-priority reason present.
NEXT_STEP_PRIORITY: tuple[tuple[ReasonCode, str], ...] = (
    (ReasonCode.CUSTOMER_AWAITING_REPLY, "Reply to the customer today — they are waiting for an answer"),
    (ReasonCode.COMPETITOR_MENTIONED, "Call today to address the competing offer before the customer decides"),
    (ReasonCode.QUOTE_EXPIRED, "Re-confirm interest and re-issue the expired quotation"),
    (ReasonCode.QUOTE_EXPIRING, "Contact the customer before the quotation expires"),
    (ReasonCode.HIGH_INTENT_STALLED, "Follow up today — buying intent is high but the deal has stalled"),
    (ReasonCode.PRICE_OBJECTION, "Address the price objection with a value-based follow-up"),
    (ReasonCode.OVERDUE_FOLLOWUP, "Complete the overdue follow-up task"),
    (ReasonCode.QUOTE_UNANSWERED, "Follow up on the outstanding quotation"),
    (ReasonCode.NO_RECENT_CONTACT, "Re-engage the customer with a check-in"),
    (ReasonCode.CLOSE_DATE_PASSED, "Update the expected close date and confirm the decision timeline"),
)


@dataclass(frozen=True)
class RiskSignals:
    """Measured facts about one open opportunity. All durations are in days (fractional)."""

    stage: OpportunityStage
    deal_value: Decimal
    days_since_rep_contact: float | None = None
    customer_waiting_days: float | None = None
    live_quote: bool = False
    days_since_quote: float | None = None
    days_to_quote_expiry: float | None = None
    overdue_followups: int = 0
    close_date_passed: bool = False
    intent: str = "unknown"  # high | medium | low | unknown
    intent_source: SignalSource = SignalSource.NONE
    competitor_mentioned: bool = False
    competitors: tuple[str, ...] = ()
    competitor_source: SignalSource = SignalSource.NONE
    price_objection: bool = False
    price_objection_source: SignalSource = SignalSource.NONE
    sentiment: str = "unknown"  # positive | neutral | negative | unknown
    sentiment_source: SignalSource = SignalSource.NONE
    historical_win_rate: float | None = None
    historical_sample_size: int = 0
    evidence: dict[str, str] = field(default_factory=dict)  # optional quotes per reason code

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in self.__dict__.items():
            if isinstance(value, Decimal):
                value = float(value)
            elif isinstance(value, StrEnum):
                value = value.value
            elif isinstance(value, tuple):
                value = list(value)
            out[key] = value
        return out


@dataclass(frozen=True)
class Reason:
    code: ReasonCode
    label: str
    points: int
    source: SignalSource
    evidence: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "label": self.label,
            "points": self.points,
            "source": self.source.value,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class RiskAssessment:
    risk_score: int
    risk_level: RiskLevel
    revenue_at_risk: Decimal
    weighted_revenue_at_risk: Decimal
    purchase_probability: float
    probability_breakdown: dict[str, float]
    reasons: tuple[Reason, ...]
    recommended_next_step: str
    raw_points: int
    engine_version: str = ENGINE_VERSION


def _band_points(value: float | None, bands: list[DayBand]) -> int:
    if value is None:
        return 0
    for band in sorted(bands, key=lambda b: b.min_days, reverse=True):
        if value >= band.min_days:
            return band.points
    return 0


def _days(value: float) -> str:
    whole = int(value)
    return f"{whole} day{'s' if whole != 1 else ''}" if whole >= 1 else f"{int(value * 24)} hours"


def purchase_probability(signals: RiskSignals, settings: CompanySettings) -> tuple[float, dict[str, float]]:
    """Stage base rate × historical calibration × intent multiplier, clamped."""
    model = settings.probability
    base = model.stage_base.get(signals.stage, 0.0)
    calibration = 1.0
    if signals.historical_win_rate is not None and signals.historical_sample_size >= model.min_closed_deals_for_calibration:
        low, high = model.calibration_bounds
        calibration = min(max(signals.historical_win_rate / model.reference_win_rate, low), high)
    intent_mult = model.intent_multiplier.get(signals.intent, 1.0)
    probability = min(max(base * calibration * intent_mult, model.min_probability), model.max_probability)
    return round(probability, 4), {
        "stage_base": base,
        "historical_calibration": round(calibration, 4),
        "intent_multiplier": intent_mult,
    }


def _collect_reasons(s: RiskSignals, settings: CompanySettings) -> list[Reason]:
    w = settings.risk_weights
    reasons: list[Reason] = []

    def add(code: ReasonCode, label: str, points: int, source: SignalSource, **evidence: Any) -> None:
        if points > 0:
            if code.value in s.evidence:
                evidence["excerpt"] = s.evidence[code.value]
            reasons.append(Reason(code, label, points, source, evidence))

    if s.customer_waiting_days is not None:
        add(ReasonCode.CUSTOMER_AWAITING_REPLY, f"Customer has been waiting {_days(s.customer_waiting_days)} for a reply",
            _band_points(s.customer_waiting_days, w.customer_awaiting_reply), SignalSource.CRM_DATA,
            waiting_days=round(s.customer_waiting_days, 1))
    if s.days_since_rep_contact is not None:
        add(ReasonCode.NO_RECENT_CONTACT, f"No follow-up from the sales team for {_days(s.days_since_rep_contact)}",
            _band_points(s.days_since_rep_contact, w.no_contact), SignalSource.CRM_DATA,
            days_since_contact=round(s.days_since_rep_contact, 1))
    if s.live_quote and s.days_since_quote is not None:
        add(ReasonCode.QUOTE_UNANSWERED, f"Quotation sent {_days(s.days_since_quote)} ago without a decision",
            _band_points(s.days_since_quote, w.quote_unanswered), SignalSource.CRM_DATA,
            days_since_quote=round(s.days_since_quote, 1))
    if s.days_to_quote_expiry is not None:
        if s.days_to_quote_expiry < 0:
            add(ReasonCode.QUOTE_EXPIRED, f"Quotation expired {_days(-s.days_to_quote_expiry)} ago", w.quote_expired,
                SignalSource.CRM_DATA, days_since_expiry=round(-s.days_to_quote_expiry, 1))
        elif s.live_quote and s.days_to_quote_expiry <= w.quote_expiring_within_days:
            add(ReasonCode.QUOTE_EXPIRING, f"Quotation expires in {_days(s.days_to_quote_expiry)}", w.quote_expiring,
                SignalSource.CRM_DATA, days_to_expiry=round(s.days_to_quote_expiry, 1))
    if s.overdue_followups > 0:
        points = min(w.overdue_followup + w.overdue_followup_additional * (s.overdue_followups - 1), w.overdue_followup_cap)
        plural = "s" if s.overdue_followups > 1 else ""
        add(ReasonCode.OVERDUE_FOLLOWUP, f"{s.overdue_followups} overdue follow-up task{plural}", points,
            SignalSource.CRM_DATA, overdue_count=s.overdue_followups)
    if s.competitor_mentioned:
        names = f" ({', '.join(s.competitors)})" if s.competitors else ""
        add(ReasonCode.COMPETITOR_MENTIONED, f"Customer mentioned a competitor{names}", w.competitor_mentioned,
            s.competitor_source, competitors=list(s.competitors))
    if s.price_objection:
        add(ReasonCode.PRICE_OBJECTION, "Customer raised a price objection", w.price_objection, s.price_objection_source)
    if s.intent == "high" and (s.days_since_rep_contact or 0) >= w.high_intent_stalled_min_days:
        add(ReasonCode.HIGH_INTENT_STALLED, "High buying intent, but the deal has stalled", w.high_intent_stalled,
            s.intent_source, intent=s.intent)
    if s.intent == "low":
        add(ReasonCode.LOW_INTENT, "Customer shows low buying intent", w.low_intent, s.intent_source, intent=s.intent)
    if s.sentiment == "negative":
        add(ReasonCode.NEGATIVE_SENTIMENT, "Negative customer sentiment", w.negative_sentiment, s.sentiment_source)
    if s.close_date_passed:
        add(ReasonCode.CLOSE_DATE_PASSED, "Expected close date has passed", w.close_date_passed, SignalSource.CRM_DATA)
    # Late stage only amplifies a deal that already shows at least one risk reason.
    if reasons and s.stage in (OpportunityStage.PROPOSAL, OpportunityStage.NEGOTIATION):
        add(ReasonCode.LATE_STAGE, f"Late-stage deal ({s.stage.value}) — more revenue is close to being lost",
            w.late_stage, SignalSource.CRM_DATA, stage=s.stage.value)
    return reasons


def level_for(score: int, settings: CompanySettings) -> RiskLevel:
    t = settings.risk_thresholds
    if score >= t.critical:
        return RiskLevel.CRITICAL
    if score >= t.high:
        return RiskLevel.HIGH
    if score >= t.medium:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def assess(signals: RiskSignals, settings: CompanySettings) -> RiskAssessment:
    """Score one open opportunity. Pure and deterministic."""
    if not signals.stage.is_open:
        raise ValueError("risk is only assessed for open opportunities")
    reasons = sorted(_collect_reasons(signals, settings), key=lambda r: r.points, reverse=True)
    raw = sum(r.points for r in reasons)
    score = min(raw, 100)
    level = level_for(score, settings)
    probability, breakdown = purchase_probability(signals, settings)
    at_risk = signals.deal_value if level.rank >= RiskLevel.MEDIUM.rank else Decimal("0")
    weighted = (at_risk * Decimal(str(probability))).quantize(Decimal("1"))
    present = {r.code for r in reasons}
    next_step = next((step for code, step in NEXT_STEP_PRIORITY if code in present), "No action needed — keep the normal cadence")
    return RiskAssessment(
        risk_score=score,
        risk_level=level,
        revenue_at_risk=at_risk,
        weighted_revenue_at_risk=weighted,
        purchase_probability=probability,
        probability_breakdown=breakdown,
        reasons=tuple(reasons),
        recommended_next_step=next_step,
        raw_points=raw,
    )
