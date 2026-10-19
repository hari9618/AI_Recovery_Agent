from decimal import Decimal

import pytest

from app.domain.enums import ActionType, UserRole
from app.domain.policy import ActionProposal, PolicyRule, evaluate
from app.domain.settings import PolicyConfig

CFG = PolicyConfig()


def rules(decision) -> set[PolicyRule]:
    return {f.rule for f in decision.findings}


@pytest.mark.parametrize(
    "action",
    [
        ActionType.CREATE_FOLLOWUP,
        ActionType.SCHEDULE_REMINDER,
        ActionType.DRAFT_EMAIL,
        ActionType.LOG_ACTIVITY,
        ActionType.ESCALATE_TO_MANAGER,
    ],
)
def test_low_risk_internal_actions_auto_execute(action):
    d = evaluate(ActionProposal(action, deal_value=Decimal("900000")), CFG)
    assert d.allowed and d.auto_execute and not d.requires_approval and d.findings == ()


def test_email_always_needs_approval_by_default():
    d = evaluate(ActionProposal(ActionType.SEND_EMAIL, deal_value=Decimal("50000")), CFG)
    assert d.requires_approval and not d.auto_execute
    assert rules(d) == {PolicyRule.CUSTOMER_FACING_NOT_AUTOMATED}
    assert d.required_role == UserRole.SALES_REP


def test_email_can_be_configured_safe_for_small_deals():
    cfg = PolicyConfig(
        auto_send_email=True, auto_executable_actions=[*CFG.auto_executable_actions, ActionType.SEND_EMAIL]
    )
    assert evaluate(ActionProposal(ActionType.SEND_EMAIL, deal_value=Decimal("50000")), cfg).auto_execute
    big = evaluate(ActionProposal(ActionType.SEND_EMAIL, deal_value=Decimal("480000")), cfg)
    assert big.requires_approval and PolicyRule.HIGH_VALUE_CUSTOMER_FACING in rules(big)


@pytest.mark.parametrize(
    ("pct", "rule", "role"),
    [
        (Decimal("10"), PolicyRule.ACTION_NOT_AUTOMATABLE, UserRole.SALES_REP),
        (Decimal("10.5"), PolicyRule.DISCOUNT_ABOVE_REP_LIMIT, UserRole.MANAGER),
        (Decimal("20"), PolicyRule.DISCOUNT_ABOVE_REP_LIMIT, UserRole.MANAGER),
        (Decimal("25"), PolicyRule.DISCOUNT_ABOVE_MANAGER_LIMIT, UserRole.OWNER),
    ],
)
def test_discount_authority_matrix(pct, rule, role):
    d = evaluate(ActionProposal(ActionType.OFFER_DISCOUNT, deal_value=Decimal("100000"), discount_pct=pct), CFG)
    assert d.requires_approval and rule in rules(d) and d.required_role == role


def test_vertex_discount_needs_manager_for_two_reasons():
    d = evaluate(
        ActionProposal(ActionType.OFFER_DISCOUNT, deal_value=Decimal("480000"), discount_pct=Decimal("12")), CFG
    )
    assert {PolicyRule.DISCOUNT_ABOVE_REP_LIMIT, PolicyRule.HIGH_VALUE_CUSTOMER_FACING} <= rules(d)
    assert d.required_role == UserRole.MANAGER


@pytest.mark.parametrize("pct", [Decimal("0"), Decimal("-5"), Decimal("150"), None])
def test_invalid_discounts_are_blocked(pct):
    d = evaluate(ActionProposal(ActionType.OFFER_DISCOUNT, discount_pct=pct), CFG)
    assert not d.allowed and not d.auto_execute and not d.requires_approval


def test_refund_rules():
    small = evaluate(ActionProposal(ActionType.ISSUE_REFUND, refund_amount=Decimal("20000")), CFG)
    big = evaluate(ActionProposal(ActionType.ISSUE_REFUND, refund_amount=Decimal("75000")), CFG)
    assert small.required_role == UserRole.MANAGER and PolicyRule.REFUND_REQUIRES_APPROVAL in rules(small)
    assert big.required_role == UserRole.OWNER and PolicyRule.REFUND_ABOVE_THRESHOLD in rules(big)


def test_low_confidence_forces_review_even_for_safe_actions():
    d = evaluate(ActionProposal(ActionType.CREATE_FOLLOWUP, confidence=0.4), CFG)
    assert d.requires_approval and PolicyRule.LOW_CONFIDENCE in rules(d)


def test_grounding_and_injection_guards():
    d = evaluate(
        ActionProposal(
            ActionType.OFFER_DISCOUNT,
            discount_pct=Decimal("5"),
            policy_evidence_found=False,
            unverified_claims=2,
            injection_suspected=True,
        ),
        CFG,
    )
    assert {
        PolicyRule.POLICY_EVIDENCE_INSUFFICIENT,
        PolicyRule.UNVERIFIED_CLAIMS,
        PolicyRule.PROMPT_INJECTION_SUSPECTED,
    } <= rules(d)
    assert d.required_role == UserRole.MANAGER


def test_fallback_recommendations_need_review():
    d = evaluate(ActionProposal(ActionType.CREATE_FOLLOWUP, generated_by_fallback=True), CFG)
    assert d.requires_approval and PolicyRule.LLM_FALLBACK in rules(d)


def test_thresholds_come_from_config():
    strict = PolicyConfig(max_discount_without_approval_pct=Decimal("5"))
    d = evaluate(ActionProposal(ActionType.OFFER_DISCOUNT, discount_pct=Decimal("8")), strict)
    assert PolicyRule.DISCOUNT_ABOVE_REP_LIMIT in rules(d)
