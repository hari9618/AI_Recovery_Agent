"""Domain enumerations shared by the ORM, API schemas, tools and the frontend contract."""

from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MANAGER = "manager"
    SALES_REP = "sales_rep"


class CustomerStatus(StrEnum):
    PROSPECT = "prospect"
    ACTIVE = "active"
    CHURNED = "churned"


class CustomerSegment(StrEnum):
    SMB = "smb"
    MID_MARKET = "mid_market"
    ENTERPRISE = "enterprise"


class LeadStatus(StrEnum):
    NEW = "new"
    CONTACTED = "contacted"
    QUALIFIED = "qualified"
    UNQUALIFIED = "unqualified"
    CONVERTED = "converted"
    LOST = "lost"


class LeadSource(StrEnum):
    WEBSITE = "website"
    REFERRAL = "referral"
    TRADE_SHOW = "trade_show"
    OUTBOUND = "outbound"
    PARTNER = "partner"
    INBOUND_CALL = "inbound_call"
    LINKEDIN = "linkedin"


class OpportunityStage(StrEnum):
    PROSPECTING = "prospecting"
    QUALIFICATION = "qualification"
    PROPOSAL = "proposal"
    NEGOTIATION = "negotiation"
    CLOSED_WON = "closed_won"
    CLOSED_LOST = "closed_lost"

    @property
    def is_open(self) -> bool:
        return self not in (OpportunityStage.CLOSED_WON, OpportunityStage.CLOSED_LOST)


OPEN_STAGES = tuple(s for s in OpportunityStage if s.is_open)


class QuoteStatus(StrEnum):
    DRAFT = "draft"
    SENT = "sent"
    VIEWED = "viewed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"


LIVE_QUOTE_STATUSES = (QuoteStatus.SENT, QuoteStatus.VIEWED)


class Channel(StrEnum):
    EMAIL = "email"
    CALL = "call"
    WHATSAPP = "whatsapp"
    MEETING = "meeting"
    CHAT = "chat"


class SenderType(StrEnum):
    CUSTOMER = "customer"
    REP = "rep"
    SYSTEM = "system"


class FollowupStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ActivityType(StrEnum):
    CALL = "call"
    EMAIL = "email"
    MEETING = "meeting"
    NOTE = "note"
    QUOTE_SENT = "quote_sent"
    STAGE_CHANGE = "stage_change"
    FOLLOWUP_COMPLETED = "followup_completed"
    AI_ACTION = "ai_action"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return _RISK_RANK[self]


_RISK_RANK = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2, RiskLevel.CRITICAL: 3}


class SignalSource(StrEnum):
    """Where a conversation-derived signal came from (shown to users for transparency)."""

    LLM_ANALYSIS = "llm_analysis"
    KEYWORD_HEURISTIC = "keyword_heuristic"
    CRM_DATA = "crm_data"
    NONE = "none"


class RecommendationStatus(StrEnum):
    PROPOSED = "proposed"
    PENDING_APPROVAL = "pending_approval"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class ActionType(StrEnum):
    CREATE_FOLLOWUP = "create_followup"
    SCHEDULE_REMINDER = "schedule_reminder"
    DRAFT_EMAIL = "draft_email"
    SEND_EMAIL = "send_email"
    UPDATE_CRM = "update_crm"
    LOG_ACTIVITY = "log_activity"
    OFFER_DISCOUNT = "offer_discount"
    ESCALATE_TO_MANAGER = "escalate_to_manager"
    ISSUE_REFUND = "issue_refund"
    NO_ACTION = "no_action"


class ActionStatus(StrEnum):
    PENDING = "pending"
    AWAITING_APPROVAL = "awaiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class AgentRunStatus(StrEnum):
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class DocumentType(StrEnum):
    SALES_PLAYBOOK = "sales_playbook"
    PRICING_POLICY = "pricing_policy"
    DISCOUNT_POLICY = "discount_policy"
    REFUND_POLICY = "refund_policy"
    COMPANY_POLICY = "company_policy"
    OBJECTION_HANDLING = "objection_handling"
    COMMUNICATION_GUIDELINES = "communication_guidelines"
    SOP = "sop"
    PRODUCT_DOCUMENTATION = "product_documentation"
    OTHER = "other"


class DocumentStatus(StrEnum):
    PENDING = "pending"
    INDEXED = "indexed"
    FAILED = "failed"


class ActorType(StrEnum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


class AuditResult(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    BLOCKED = "blocked"
    PENDING = "pending"


class IngestionStatus(StrEnum):
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"


class EvalSuite(StrEnum):
    RAG = "rag"
    AGENT = "agent"
    COPILOT = "copilot"


class EvalMode(StrEnum):
    """`live` = real Groq calls; `offline` = scripted LLM double (orchestration/policy only)."""

    LIVE = "live"
    OFFLINE = "offline"


class LLMCallStatus(StrEnum):
    OK = "ok"
    REPAIRED = "repaired"
    FALLBACK = "fallback"
    ERROR = "error"
