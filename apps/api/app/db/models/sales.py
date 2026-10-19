from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import MONEY, Base, Timestamps, UUIDPk, company_fk, pg_enum
from app.domain.enums import OpportunityStage, QuoteStatus


class Opportunity(UUIDPk, Timestamps, Base):
    __tablename__ = "opportunities"
    __table_args__ = (
        sa.Index("ix_opportunities_company_stage", "company_id", "stage"),
        sa.Index("ix_opportunities_company_owner", "company_id", "owner_id"),
        sa.CheckConstraint("amount >= 0", name="amount_non_negative"),
    )

    company_id: Mapped[uuid.UUID] = company_fk()
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("leads.id", ondelete="SET NULL")
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    primary_contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("contacts.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(sa.String(255))
    stage: Mapped[OpportunityStage] = mapped_column(pg_enum(OpportunityStage, "opportunity_stage"))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(sa.String(3), default="INR")
    product_line: Mapped[str | None] = mapped_column(sa.String(120))
    expected_close_date: Mapped[date | None]
    last_activity_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    stage_changed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    loss_reason: Mapped[str | None] = mapped_column(sa.String(255))
    competitor: Mapped[str | None] = mapped_column(sa.String(120))
    is_synthetic: Mapped[bool] = mapped_column(default=False)


class Quote(UUIDPk, Timestamps, Base):
    __tablename__ = "quotes"
    __table_args__ = (
        sa.UniqueConstraint("company_id", "quote_number", name="uq_quotes_company_number"),
        sa.Index("ix_quotes_company_status", "company_id", "status"),
        sa.CheckConstraint("discount_pct >= 0 AND discount_pct <= 100", name="discount_range"),
    )

    company_id: Mapped[uuid.UUID] = company_fk()
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    quote_number: Mapped[str] = mapped_column(sa.String(40))
    version: Mapped[int] = mapped_column(default=1)
    status: Mapped[QuoteStatus] = mapped_column(pg_enum(QuoteStatus, "quote_status"))
    subtotal: Mapped[Decimal] = mapped_column(MONEY)
    discount_pct: Mapped[Decimal] = mapped_column(sa.Numeric(5, 2), default=Decimal("0"))
    tax_pct: Mapped[Decimal] = mapped_column(sa.Numeric(5, 2), default=Decimal("18"))
    total: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(sa.String(3), default="INR")
    sent_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    viewed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    valid_until: Mapped[date | None]
    responded_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    is_synthetic: Mapped[bool] = mapped_column(default=False)

    items: Mapped[list[QuoteItem]] = relationship(
        back_populates="quote", cascade="all, delete-orphan", order_by="QuoteItem.position"
    )


class QuoteItem(UUIDPk, Base):
    __tablename__ = "quote_items"

    quote_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("quotes.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int]
    sku: Mapped[str] = mapped_column(sa.String(40))
    description: Mapped[str] = mapped_column(sa.String(255))
    quantity: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2))
    unit_price: Mapped[Decimal] = mapped_column(MONEY)
    discount_pct: Mapped[Decimal] = mapped_column(sa.Numeric(5, 2), default=Decimal("0"))
    line_total: Mapped[Decimal] = mapped_column(MONEY)

    quote: Mapped[Quote] = relationship(back_populates="items")
