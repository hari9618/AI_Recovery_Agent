"""ORM models. Importing this package registers every table on `Base.metadata`."""

from app.db.models.conversations import Conversation, ConversationAnalysis, ConversationMessage
from app.db.models.crm import Activity, Contact, Customer, Followup, Lead
from app.db.models.intelligence import Action, AgentRun, ApprovalRequest, Recommendation, RevenueRisk
from app.db.models.knowledge import Document, DocumentChunk, KnowledgeSource
from app.db.models.operations import (
    AuditLog,
    EvaluationCase,
    EvaluationResult,
    EvaluationRun,
    IngestionJob,
    LLMCall,
)
from app.db.models.sales import Opportunity, Quote, QuoteItem
from app.db.models.tenancy import Company, User

__all__ = [
    "Action",
    "Activity",
    "AgentRun",
    "ApprovalRequest",
    "AuditLog",
    "Company",
    "Contact",
    "Conversation",
    "ConversationAnalysis",
    "ConversationMessage",
    "Customer",
    "Document",
    "DocumentChunk",
    "EvaluationCase",
    "EvaluationResult",
    "EvaluationRun",
    "Followup",
    "IngestionJob",
    "KnowledgeSource",
    "LLMCall",
    "Lead",
    "Opportunity",
    "Quote",
    "QuoteItem",
    "Recommendation",
    "RevenueRisk",
    "User",
]
