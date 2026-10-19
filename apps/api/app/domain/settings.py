"""Tenant-configurable business thresholds.

Stored in `companies.settings` (JSONB) and validated here. Defaults are sensible for a mid-size
B2B seller; every number used by the risk / policy / ROI engines comes from this model so that
behaviour is explainable ("why did this need approval?") and changeable without a deploy.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from app.domain.enums import ActionType, OpportunityStage


class DayBand(BaseModel):
    """`points` are awarded when the measured value is >= `min_days`. Bands are evaluated highest first."""

    min_days: float
    points: int


class RiskWeights(BaseModel):
    no_contact: list[DayBand] = Field(
        default_factory=lambda: [
            DayBand(min_days=14, points=25),
            DayBand(min_days=7, points=18),
            DayBand(min_days=4, points=10),
        ]
    )
    quote_unanswered: list[DayBand] = Field(
        default_factory=lambda: [
            DayBand(min_days=10, points=15),
            DayBand(min_days=5, points=10),
            DayBand(min_days=3, points=6),
        ]
    )
    customer_awaiting_reply: list[DayBand] = Field(
        default_factory=lambda: [DayBand(min_days=3, points=20), DayBand(min_days=1, points=15)]
    )
    quote_expiring_within_days: int = 5
    quote_expiring: int = 10
    quote_expired: int = 14
    overdue_followup: int = 12
    overdue_followup_additional: int = 3
    overdue_followup_cap: int = 18
    competitor_mentioned: int = 10
    price_objection: int = 8
    high_intent_stalled: int = 10
    high_intent_stalled_min_days: float = 4
    negative_sentiment: int = 6
    low_intent: int = 5
    late_stage: int = 6
    close_date_passed: int = 8


class RiskThresholds(BaseModel):
    critical: int = 75
    high: int = 55
    medium: int = 35

    @model_validator(mode="after")
    def _ordered(self) -> RiskThresholds:
        if not (self.critical > self.high > self.medium > 0):
            raise ValueError("risk thresholds must satisfy critical > high > medium > 0")
        return self


class ProbabilityModel(BaseModel):
    """Purchase probability = stage base rate × win-rate calibration × intent multiplier (clamped)."""

    stage_base: dict[OpportunityStage, float] = Field(
        default_factory=lambda: {
            OpportunityStage.PROSPECTING: 0.10,
            OpportunityStage.QUALIFICATION: 0.25,
            OpportunityStage.PROPOSAL: 0.45,
            OpportunityStage.NEGOTIATION: 0.65,
        }
    )
    reference_win_rate: float = 0.5
    calibration_bounds: tuple[float, float] = (0.6, 1.4)
    intent_multiplier: dict[str, float] = Field(
        default_factory=lambda: {"high": 1.25, "medium": 1.0, "low": 0.6, "unknown": 1.0}
    )
    min_probability: float = 0.02
    max_probability: float = 0.95
    min_closed_deals_for_calibration: int = 10


class PolicyConfig(BaseModel):
    max_discount_without_approval_pct: Decimal = Decimal("10")
    max_discount_manager_pct: Decimal = Decimal("20")
    refund_approval_threshold: Decimal = Decimal("50000")
    high_value_deal_threshold: Decimal = Decimal("300000")
    min_confidence_for_auto: float = 0.7
    auto_send_email: bool = False
    auto_executable_actions: list[ActionType] = Field(
        default_factory=lambda: [
            ActionType.CREATE_FOLLOWUP,
            ActionType.SCHEDULE_REMINDER,
            ActionType.DRAFT_EMAIL,
            ActionType.LOG_ACTIVITY,
            ActionType.ESCALATE_TO_MANAGER,
        ]
    )
    customer_facing_actions: list[ActionType] = Field(
        default_factory=lambda: [ActionType.SEND_EMAIL, ActionType.OFFER_DISCOUNT, ActionType.ISSUE_REFUND]
    )
    followup_due_hours: int = 24


class ROIAssumptions(BaseModel):
    """Used ONLY for clearly-labelled estimates. Observed figures never use these."""

    minutes_saved_per_deal_review: float = 15
    minutes_saved_per_draft: float = 10
    minutes_saved_per_followup_created: float = 3
    assumed_recovery_rate: float = 0.15


class CompanySettings(BaseModel):
    risk_weights: RiskWeights = Field(default_factory=RiskWeights)
    risk_thresholds: RiskThresholds = Field(default_factory=RiskThresholds)
    probability: ProbabilityModel = Field(default_factory=ProbabilityModel)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    roi: ROIAssumptions = Field(default_factory=ROIAssumptions)

    @classmethod
    def from_json(cls, data: dict | None) -> CompanySettings:
        return cls.model_validate(data or {})
