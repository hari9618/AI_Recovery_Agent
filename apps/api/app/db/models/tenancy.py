from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk, company_fk, pg_enum
from app.domain.enums import UserRole


class Company(UUIDPk, Timestamps, Base):
    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(sa.String(200))
    industry: Mapped[str] = mapped_column(sa.String(100))
    currency: Mapped[str] = mapped_column(sa.String(3), default="INR")
    timezone: Mapped[str] = mapped_column(sa.String(64), default="Asia/Kolkata")
    # Tenant-level thresholds (risk weights, policy limits). Validated by domain.settings.CompanySettings.
    settings: Mapped[dict[str, Any]] = mapped_column(default=dict)
    is_demo: Mapped[bool] = mapped_column(default=False)


class User(UUIDPk, Timestamps, Base):
    __tablename__ = "users"
    __table_args__ = (sa.UniqueConstraint("company_id", "email", name="uq_users_company_email"),)

    company_id: Mapped[uuid.UUID] = company_fk()
    email: Mapped[str] = mapped_column(sa.String(255))
    full_name: Mapped[str] = mapped_column(sa.String(200))
    role: Mapped[UserRole] = mapped_column(pg_enum(UserRole, "user_role"))
    # SHA-256 of the API token. Raw tokens are never stored.
    api_token_hash: Mapped[str | None] = mapped_column(sa.String(64), unique=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    region: Mapped[str | None] = mapped_column(sa.String(100))
