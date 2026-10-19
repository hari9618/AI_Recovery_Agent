from decimal import Decimal

import pytest

from app.domain.enums import OpportunityStage, RiskLevel, SignalSource
from app.domain.risk import ReasonCode, RiskSignals, assess, level_for, purchase_probability
from app.domain.settings import CompanySettings, RiskThresholds

S = CompanySettings()


def sig(**kw) -> RiskSignals:
    base = {"stage": OpportunityStage.PROPOSAL, "deal_value": Decimal("500000")}
    return RiskSignals(**(base | kw))


def codes(a) -> set[ReasonCode]:
    return {r.code for r in a.reasons}


def test_healthy_deal_is_low_risk_with_no_revenue_at_risk():
    a = assess(sig(days_since_rep_contact=1, intent="high"), S)
    assert a.risk_level == RiskLevel.LOW
    assert a.risk_score == 0
    assert a.revenue_at_risk == 0
    assert a.recommended_next_step.startswith("No action")


@pytest.mark.parametrize(
    ("days", "points"), [(2, 0), (4, 10), (6.9, 10), (7, 18), (13, 18), (14, 25), (40, 25)]
)
def test_no_contact_bands(days, points):
    a = assess(sig(stage=OpportunityStage.QUALIFICATION, days_since_rep_contact=days), S)
    got = {r.code: r.points for r in a.reasons}.get(ReasonCode.NO_RECENT_CONTACT, 0)
    assert got == points


def test_customer_waiting_outranks_everything_for_next_step():
    a = assess(sig(customer_waiting_days=2, competitor_mentioned=True, days_since_rep_contact=8), S)
    assert a.recommended_next_step.startswith("Reply to the customer")
    assert ReasonCode.CUSTOMER_AWAITING_REPLY in codes(a)


def test_quote_expiry_rules():
    expiring = assess(sig(live_quote=True, days_since_quote=20, days_to_quote_expiry=2), S)
    assert ReasonCode.QUOTE_EXPIRING in codes(expiring)
    expired = assess(sig(live_quote=False, days_to_quote_expiry=-3), S)
    assert ReasonCode.QUOTE_EXPIRED in codes(expired)
    assert ReasonCode.QUOTE_EXPIRING not in codes(expired)
    fresh = assess(sig(live_quote=True, days_since_quote=1, days_to_quote_expiry=25), S)
    assert not codes(fresh) & {ReasonCode.QUOTE_EXPIRING, ReasonCode.QUOTE_EXPIRED, ReasonCode.QUOTE_UNANSWERED}


def test_overdue_followups_are_capped():
    one = assess(sig(overdue_followups=1), S)
    many = assess(sig(overdue_followups=10), S)
    pts = lambda a: {r.code: r.points for r in a.reasons}[ReasonCode.OVERDUE_FOLLOWUP]  # noqa: E731
    assert pts(one) == S.risk_weights.overdue_followup
    assert pts(many) == S.risk_weights.overdue_followup_cap


def test_high_intent_stalled_needs_both_intent_and_silence():
    assert ReasonCode.HIGH_INTENT_STALLED not in codes(assess(sig(intent="high", days_since_rep_contact=1), S))
    assert ReasonCode.HIGH_INTENT_STALLED in codes(assess(sig(intent="high", days_since_rep_contact=5), S))
    assert ReasonCode.HIGH_INTENT_STALLED not in codes(assess(sig(intent="medium", days_since_rep_contact=9), S))


def test_late_stage_only_amplifies_existing_risk():
    assert assess(sig(stage=OpportunityStage.NEGOTIATION), S).risk_score == 0
    a = assess(sig(stage=OpportunityStage.NEGOTIATION, price_objection=True), S)
    assert ReasonCode.LATE_STAGE in codes(a)


def test_vertex_like_scenario_is_critical_and_fully_explained():
    a = assess(
        sig(
            stage=OpportunityStage.NEGOTIATION, deal_value=Decimal("480000"),
            days_since_rep_contact=7, customer_waiting_days=5, live_quote=True, days_since_quote=7,
            days_to_quote_expiry=14, overdue_followups=1, intent="high", intent_source=SignalSource.LLM_ANALYSIS,
            competitor_mentioned=True, competitors=("Voltrix Systems",), competitor_source=SignalSource.LLM_ANALYSIS,
            price_objection=True, price_objection_source=SignalSource.LLM_ANALYSIS,
        ),
        S,
    )
    assert a.risk_level == RiskLevel.CRITICAL
    assert a.revenue_at_risk == Decimal("480000")
    assert a.risk_score == min(sum(r.points for r in a.reasons), 100)
    assert {ReasonCode.COMPETITOR_MENTIONED, ReasonCode.PRICE_OBJECTION, ReasonCode.HIGH_INTENT_STALLED} <= codes(a)
    competitor = next(r for r in a.reasons if r.code == ReasonCode.COMPETITOR_MENTIONED)
    assert competitor.source == SignalSource.LLM_ANALYSIS and "Voltrix" in competitor.label


def test_score_is_capped_and_deterministic():
    kw = dict(days_since_rep_contact=30, customer_waiting_days=10, live_quote=True, days_since_quote=30,
              days_to_quote_expiry=1, overdue_followups=5, competitor_mentioned=True, price_objection=True,
              intent="high", sentiment="negative", close_date_passed=True)
    a1, a2 = assess(sig(**kw), S), assess(sig(**kw), S)
    assert a1.risk_score == 100 and a1.raw_points > 100
    assert a1 == a2


def test_reasons_sorted_by_points_desc():
    a = assess(sig(days_since_rep_contact=15, price_objection=True, competitor_mentioned=True), S)
    pts = [r.points for r in a.reasons]
    assert pts == sorted(pts, reverse=True)


def test_closed_deals_are_rejected():
    with pytest.raises(ValueError):
        assess(sig(stage=OpportunityStage.CLOSED_WON), S)


def test_level_thresholds_are_configurable():
    custom = CompanySettings(risk_thresholds=RiskThresholds(critical=90, high=70, medium=50))
    assert level_for(80, S) == RiskLevel.CRITICAL
    assert level_for(80, custom) == RiskLevel.HIGH
    with pytest.raises(ValueError):
        RiskThresholds(critical=50, high=60, medium=10)


def test_probability_uses_stage_calibration_and_intent():
    p_base, parts = purchase_probability(sig(intent="medium"), S)
    assert parts["historical_calibration"] == 1.0  # no history → no calibration
    assert p_base == pytest.approx(0.45)
    p_cal, parts = purchase_probability(sig(intent="medium", historical_win_rate=0.6, historical_sample_size=50), S)
    assert parts["historical_calibration"] == pytest.approx(1.2)
    assert p_cal == pytest.approx(0.54)
    p_small_sample, _ = purchase_probability(sig(intent="medium", historical_win_rate=0.9, historical_sample_size=3), S)
    assert p_small_sample == pytest.approx(0.45)
    p_low, _ = purchase_probability(sig(intent="low"), S)
    p_high, _ = purchase_probability(sig(intent="high"), S)
    assert p_low < p_base < p_high


def test_weighted_revenue_is_value_times_probability():
    a = assess(sig(days_since_rep_contact=15, customer_waiting_days=4, overdue_followups=1), S)
    assert a.risk_level.rank >= RiskLevel.MEDIUM.rank
    assert a.weighted_revenue_at_risk == (a.revenue_at_risk * Decimal(str(a.purchase_probability))).quantize(Decimal("1"))
