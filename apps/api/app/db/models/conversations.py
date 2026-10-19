from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPk, company_fk, pg_enum
from app.domain.enums import Channel, LLMCallStatus, SenderType


class Conversation(UUIDPk, Timestamps, Base):
    __tablename__ = "conversations"
    __table_args__ = (sa.Index("ix_conversations_company_last", "company_id", "last_message_at"),)

    company_id: Mapped[uuid.UUID] = company_fk()
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("opportunities.id", ondelete="SET NULL"), index=True
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("contacts.id", ondelete="SET NULL")
    )
    channel: Mapped[Channel] = mapped_column(pg_enum(Channel, "conversation_channel"))
    subject: Mapped[str | None] = mapped_column(sa.String(255))
    started_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    last_message_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    last_sender: Mapped[SenderType] = mapped_column(pg_enum(SenderType, "sender_type"))
    is_synthetic: Mapped[bool] = mapped_column(default=False)

    messages: Mapped[list[ConversationMessage]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="ConversationMessage.sent_at"
    )


class ConversationMessage(UUIDPk, Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (sa.Index("ix_conversation_messages_conv_time", "conversation_id", "sent_at"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="CASCADE")
    )
    sender_type: Mapped[SenderType] = mapped_column(pg_enum(SenderType, "sender_type"))
    sender_name: Mapped[str] = mapped_column(sa.String(200))
    body: Mapped[str] = mapped_column(sa.Text)
    sent_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class ConversationAnalysis(UUIDPk, Base):
    """Cached LLM analysis of a conversation, keyed by a hash of its transcript.

    Re-analysis happens only when the transcript changes (new hash) or the prompt version changes.
    Frequently-queried fields are promoted to columns; the full validated output stays in `analysis`.
    """

    __tablename__ = "conversation_analyses"
    __table_args__ = (
        sa.UniqueConstraint(
            "conversation_id", "content_hash", "prompt_version", name="uq_conversation_analyses_hash"
        ),
    )

    company_id: Mapped[uuid.UUID] = company_fk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    content_hash: Mapped[str] = mapped_column(sa.String(64))
    prompt_version: Mapped[str] = mapped_column(sa.String(20))
    model: Mapped[str] = mapped_column(sa.String(120))
    status: Mapped[LLMCallStatus] = mapped_column(pg_enum(LLMCallStatus, "llm_call_status"))
    intent: Mapped[str | None] = mapped_column(sa.String(20))
    sentiment: Mapped[str | None] = mapped_column(sa.String(20))
    confidence: Mapped[float | None]
    analysis: Mapped[dict[str, Any]] = mapped_column(default=dict)
    trace_id: Mapped[str | None] = mapped_column(sa.String(64))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
