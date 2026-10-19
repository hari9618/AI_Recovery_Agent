"""Policy Engine — deterministic guardrails deciding what may run automatically.

Inputs are facts (action type, amounts, confidence, grounding status); thresholds come from
`CompanySettings.policy`. The LLM never decides whether approval is needed. Every decision lists the
rules that fired so the UI can answer "WHY is human approval required?".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any

from app.domain.enums import ActionType, UserRole
from app.domain.settings import PolicyConfig


class PolicyRule(StrEnum):
    INVALID_ACTION = "INVALID_ACTION"
    DISCOUNT_ABOVE_REP_LIMIT = "DISCOUNT_ABOVE_REP_LIMIT"
    DISCOUNT_ABOVE_MANAGER_LIMIT = "DISCOUNT_ABOVE_MANAGER_LIMIT"
    REFUND_REQUIRES_APPROVAL = "REFUND_REQUIRES_APPROVAL"
    REFUND_ABOVE_THRESHOLD = "REFUND_ABOVE_THRESHOLD"
    HIGH_VALUE_CUSTOMER_FACING = "HIGH_VALUE_CUSTOMER_FACING"
    CUSTOMER_FACING_NOT_AUTOMATED = "CUSTOMER_FACING_NOT_AUTOMATED"
    ACTION_NOT_AUTOMATABLE = "ACTION_NOT_AUTOMATABLE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    POLICY_EVIDENCE_INSUFFICIENT = "POLICY_EVIDENCE_INSUFFICIENT"
    UNVERIFIED_CLAIMS = "UNVERIFIED_CLAIMS"
    PROMPT_INJECTION_SUSPECTED = "PROMPT_INJECTION_SUSPECTED"
    LLM_FALLBACK = "LLM_FALLBACK"


@dataclass(frozen=True)
class ActionProposal:
    action_type: ActionType
    deal_value: Decimal = Decimal("0")
    discount_pct: Decimal | None = None
    refund_amount: Decimal | None = None
    confidence: float = 1.0
    policy_evidence_found: bool = True
    unverified_claims: int = 0
    injection_suspected: bool = False
    generated_by_fallback: bool = False


@dataclass(frozen=True)
class PolicyFinding:
    rule: PolicyRule
    message: str
    required_role: UserRole | None = None
    blocking: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule.value,
            "message": self.message,
            "required_role": self.required_role.value if self.required_role else None,
            "blocking": self.blocking,
        }


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    requires_approval: bool
    auto_execute: bool
    required_role: UserRole | None
    findings: tuple[PolicyFinding, ...] = field(default_factory=tuple)

    @property
    def reasons(self) -> list[dict[str, Any]]:
        return [f.as_dict() for f in self.findings]

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "requires_approval": self.requires_approval,
            "auto_execute": self.auto_execute,
            "required_role": self.required_role.value if self.required_role else None,
            "reasons": self.reasons,
        }


_ROLE_ORDER = [UserRole.SALES_REP, UserRole.MANAGER, UserRole.ADMIN, UserRole.OWNER]
COMMERCIAL_ACTIONS = {ActionType.OFFER_DISCOUNT, ActionType.ISSUE_REFUND}


def _money(v: Decimal) -> str:
    return f"{v:,.0f}"


def evaluate(proposal: ActionProposal, config: PolicyConfig) -> PolicyDecision:
    """Decide whether `proposal` may execute automatically, needs approval (and by whom) or is blocked."""
    f: list[PolicyFinding] = []
    a = proposal.action_type

    if a == ActionType.OFFER_DISCOUNT:
        d = proposal.discount_pct
        if d is None or d <= 0 or d > 100:
            f.append(
                PolicyFinding(
                    PolicyRule.INVALID_ACTION, f"Discount must be between 0 and 100% (got {d})", blocking=True
                )
            )
        elif d > config.max_discount_manager_pct:
            f.append(
                PolicyFinding(
                    PolicyRule.DISCOUNT_ABOVE_MANAGER_LIMIT,
                    f"Discount {d}% exceeds the manager limit of {config.max_discount_manager_pct}%; owner approval required",
                    UserRole.OWNER,
                )
            )
        elif d > config.max_discount_without_approval_pct:
            f.append(
                PolicyFinding(
                    PolicyRule.DISCOUNT_ABOVE_REP_LIMIT,
                    f"Discount {d}% is above the {config.max_discount_without_approval_pct}% a sales rep may offer; manager approval required",
                    UserRole.MANAGER,
                )
            )
    if a == ActionType.ISSUE_REFUND:
        r = proposal.refund_amount
        if r is None or r <= 0:
            f.append(PolicyFinding(PolicyRule.INVALID_ACTION, "Refund amount must be positive", blocking=True))
        elif r > config.refund_approval_threshold:
            f.append(
                PolicyFinding(
                    PolicyRule.REFUND_ABOVE_THRESHOLD,
                    f"Refund {_money(r)} exceeds {_money(config.refund_approval_threshold)}; owner approval required",
                    UserRole.OWNER,
                )
            )
        else:
            f.append(
                PolicyFinding(
                    PolicyRule.REFUND_REQUIRES_APPROVAL, "Sales reps cannot approve refunds", UserRole.MANAGER
                )
            )

    customer_facing = a in config.customer_facing_actions
    if customer_facing and proposal.deal_value >= config.high_value_deal_threshold:
        f.append(
            PolicyFinding(
                PolicyRule.HIGH_VALUE_CUSTOMER_FACING,
                f"High-value deal ({_money(proposal.deal_value)} ≥ {_money(config.high_value_deal_threshold)}): "
                "customer-facing actions need manager review",
                UserRole.MANAGER,
            )
        )
    if a == ActionType.SEND_EMAIL and not config.auto_send_email:
        f.append(
            PolicyFinding(
                PolicyRule.CUSTOMER_FACING_NOT_AUTOMATED,
                "Customer emails are drafted by AI and sent only after human approval",
                UserRole.SALES_REP,
            )
        )
    if (
        a not in config.auto_executable_actions
        and a not in (ActionType.SEND_EMAIL, ActionType.NO_ACTION)
        and not any(
            x.rule
            in (
                PolicyRule.DISCOUNT_ABOVE_REP_LIMIT,
                PolicyRule.DISCOUNT_ABOVE_MANAGER_LIMIT,
                PolicyRule.REFUND_ABOVE_THRESHOLD,
                PolicyRule.REFUND_REQUIRES_APPROVAL,
            )
            for x in f
        )
    ):
        f.append(
            PolicyFinding(
                PolicyRule.ACTION_NOT_AUTOMATABLE,
                f"'{a.value}' is not configured for automatic execution",
                UserRole.SALES_REP,
            )
        )
    if proposal.confidence < config.min_confidence_for_auto:
        f.append(
            PolicyFinding(
                PolicyRule.LOW_CONFIDENCE,
                f"AI confidence {proposal.confidence:.2f} is below {config.min_confidence_for_auto:.2f}; human review required",
                UserRole.SALES_REP,
            )
        )
    if a in COMMERCIAL_ACTIONS and not proposal.policy_evidence_found:
        f.append(
            PolicyFinding(
                PolicyRule.POLICY_EVIDENCE_INSUFFICIENT,
                "No supporting policy document was found for this commercial action",
                UserRole.MANAGER,
            )
        )
    if proposal.unverified_claims:
        f.append(
            PolicyFinding(
                PolicyRule.UNVERIFIED_CLAIMS,
                f"{proposal.unverified_claims} policy statement(s) in the recommendation could not be verified against sources",
                UserRole.MANAGER,
            )
        )
    if proposal.injection_suspected:
        f.append(
            PolicyFinding(
                PolicyRule.PROMPT_INJECTION_SUSPECTED,
                "Source content contained instruction-like text; a human must review",
                UserRole.MANAGER,
            )
        )
    if proposal.generated_by_fallback and a != ActionType.NO_ACTION:
        f.append(
            PolicyFinding(
                PolicyRule.LLM_FALLBACK,
                "Recommendation produced by rules fallback (AI unavailable)",
                UserRole.SALES_REP,
            )
        )

    blocked = any(x.blocking for x in f)
    needs = [x for x in f if not x.blocking and x.required_role is not None]
    role = max((x.required_role for x in needs if x.required_role), key=_ROLE_ORDER.index, default=None)
    requires_approval = bool(needs) and not blocked
    auto = not blocked and not requires_approval and a in config.auto_executable_actions
    return PolicyDecision(
        allowed=not blocked,
        requires_approval=requires_approval,
        auto_execute=auto,
        required_role=role,
        findings=tuple(f),
    )
