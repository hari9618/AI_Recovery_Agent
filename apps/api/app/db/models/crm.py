from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import MONEY, Base, Timestamps, UUIDPk, company_fk, pg_enum
from app.domain.enums import (
    ActivityType,
    CustomerSegment,
    CustomerStatus,
    FollowupStatus,
    LeadSource,
    LeadStatus,
)


class Customer(UUIDPk, Timestamps, Base):
    __tablename__ = "customers"
    __table_args__ = (
        sa.Index("ix_customers_company_status", "company_id", "status"),
        sa.Index("ix_customers_company_name", "company_id", "normalized_name"),
    )

    company_id: Mapped[uuid.UUID] = company_fk()
    name: Mapped[str] = mapped_column(sa.String(200))
    # Lower-cased, punctuation/legal-suffix stripped name used for entity resolution on import.
    normalized_name: Mapped[str] = mapped_column(sa.String(200))
    industry: Mapped[str] = mapped_column(sa.String(100))
    segment: Mapped[CustomerSegment] = mapped_column(pg_enum(CustomerSegment, "customer_segment"))
    status: Mapped[CustomerStatus] = mapped_column(pg_enum(CustomerStatus, "customer_status"))
    city: Mapped[str | None] = mapped_column(sa.String(100))
    state: Mapped[str | None] = mapped_column(sa.String(100))
    country: Mapped[str] = mapped_column(sa.String(2), default="IN")
    website: Mapped[str | None] = mapped_column(sa.String(255))
    employee_count: Mapped[int | None]
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    lifetime_value: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    churned_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    external_ref: Mapped[str | None] = mapped_column(sa.String(100))
    is_synthetic: Mapped[bool] = mapped_column(default=False)


class Contact(UUIDPk, Timestamps, Base):
    __tablename__ = "contacts"
    __table_args__ = (sa.Index("ix_contacts_company_email", "company_id", "email"),)

    company_id: Mapped[uuid.UUID] = company_fk()
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    full_name: Mapped[str] = mapped_column(sa.String(200))
    email: Mapped[str | None] = mapped_column(sa.String(255))
    phone: Mapped[str | None] = mapped_column(sa.String(40))
    title: Mapped[str | None] = mapped_column(sa.String(120))
    is_decision_maker: Mapped[bool] = mapped_column(default=False)


class Lead(UUIDPk, Timestamps, Base):
    __tablename__ = "leads"
    __table_args__ = (
        sa.Index("ix_leads_company_status", "company_id", "status"),
        sa.Index("ix_leads_company_assigned", "company_id", "assigned_to"),
    )

    company_id: Mapped[uuid.UUID] = company_fk()
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="SET NULL"), index=True
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("contacts.id", ondelete="SET NULL")
    )
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    company_name: Mapped[str] = mapped_column(sa.String(200))
    contact_name: Mapped[str | None] = mapped_column(sa.String(200))
    contact_email: Mapped[str | None] = mapped_column(sa.String(255))
    contact_phone: Mapped[str | None] = mapped_column(sa.String(40))
    source: Mapped[LeadSource] = mapped_column(pg_enum(LeadSource, "lead_source"))
    status: Mapped[LeadStatus] = mapped_column(pg_enum(LeadStatus, "lead_status"))
    industry: Mapped[str | None] = mapped_column(sa.String(100))
    estimated_value: Mapped[Decimal | None] = mapped_column(MONEY)
    requirement: Mapped[str | None] = mapped_column(sa.Text)
    received_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    first_response_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    last_contact_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    is_synthetic: Mapped[bool] = mapped_column(default=False)


class Followup(UUIDPk, Timestamps, Base):
    __tablename__ = "followups"
    __table_args__ = (sa.Index("ix_followups_company_status_due", "company_id", "status", "due_at"),)

    company_id: Mapped[uuid.UUID] = company_fk()
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(sa.String(255))
    notes: Mapped[str | None] = mapped_column(sa.Text)
    due_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    status: Mapped[FollowupStatus] = mapped_column(pg_enum(FollowupStatus, "followup_status"))
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_by_agent: Mapped[bool] = mapped_column(default=False)
    recommendation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("recommendations.id", ondelete="SET NULL")
    )


class Activity(UUIDPk, Base):
    __tablename__ = "activities"
    __table_args__ = (
        sa.Index("ix_activities_customer_time", "customer_id", "occurred_at"),
        sa.Index("ix_activities_opportunity_time", "opportunity_id", "occurred_at"),
    )

    company_id: Mapped[uuid.UUID] = company_fk()
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="CASCADE")
    )
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("opportunities.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    type: Mapped[ActivityType] = mapped_column(pg_enum(ActivityType, "activity_type"))
    description: Mapped[str] = mapped_column(sa.Text)
    occurred_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", default=dict)
