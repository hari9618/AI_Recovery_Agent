"""CSV/JSON ingestion: parse → validate → normalise → deduplicate → resolve entities → persist.

Nothing is inserted blindly. Each row is validated by a Pydantic model; failures are reported with
row number, field and message. Duplicates are detected within the file and against the database.
Entity resolution links rows to existing customers/users by normalised name or email.
"""

from __future__ import annotations

import csv
import io
import json
import re
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.db import models as m
from app.domain.enums import (
    ActivityType,
    ActorType,
    CustomerSegment,
    CustomerStatus,
    IngestionStatus,
    LeadSource,
    LeadStatus,
    OpportunityStage,
    QuoteStatus,
)
from app.services.audit import record_audit
from app.services.text import normalize_company_name, normalize_email

Entity = Literal["customers", "leads", "quotes", "sales_activities"]
MAX_ERRORS_STORED = 200
_DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d %b %Y", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S")


# ----------------------------------------------------------------------------------- normalisers
def parse_money(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    text = re.sub(r"[₹$,\s]|INR|Rs\.?", "", str(value), flags=re.I)
    multiplier = Decimal("1")
    if text.lower().endswith("l"):  # Indian lakh shorthand, e.g. 4.8L
        text, multiplier = text[:-1], Decimal("100000")
    elif text.lower().endswith("cr"):
        text, multiplier = text[:-2], Decimal("10000000")
    try:
        amount = Decimal(text) * multiplier
    except InvalidOperation as exc:
        raise ValueError(f"not a valid amount: {value!r}") from exc
    if amount < 0:
        raise ValueError("amount cannot be negative")
    return amount.quantize(Decimal("0.01"))


def parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    raise ValueError(f"unrecognised date {value!r} (use YYYY-MM-DD)")


def _enum(enum_cls: type, value: Any, default: Any = None) -> Any:
    if value in (None, ""):
        if default is None:
            raise ValueError("required")
        return default
    key = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    try:
        return enum_cls(key)
    except ValueError as exc:
        raise ValueError(f"must be one of {[e.value for e in enum_cls]}") from exc


# ----------------------------------------------------------------------------------- row models
class _Row(BaseModel):
    @field_validator("*", mode="before")
    @classmethod
    def _blank_to_none(cls, v: Any) -> Any:
        return None if isinstance(v, str) and not v.strip() else (v.strip() if isinstance(v, str) else v)


class CustomerRow(_Row):
    name: str = Field(min_length=2, max_length=200)
    industry: str = Field(min_length=2, max_length=100)
    segment: CustomerSegment = CustomerSegment.SMB
    status: CustomerStatus = CustomerStatus.PROSPECT
    city: str | None = None
    state: str | None = None
    website: str | None = None
    employee_count: int | None = Field(None, ge=1, le=10_000_000)
    owner_email: str | None = None

    _seg = field_validator("segment", mode="before")(lambda v: _enum(CustomerSegment, v, CustomerSegment.SMB))
    _st = field_validator("status", mode="before")(lambda v: _enum(CustomerStatus, v, CustomerStatus.PROSPECT))


class LeadRow(_Row):
    company_name: str = Field(min_length=2, max_length=200)
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    source: LeadSource
    status: LeadStatus = LeadStatus.NEW
    estimated_value: Decimal | None = None
    requirement: str | None = Field(None, max_length=2000)
    received_at: datetime
    assigned_to_email: str | None = None

    _src = field_validator("source", mode="before")(lambda v: _enum(LeadSource, v))
    _st = field_validator("status", mode="before")(lambda v: _enum(LeadStatus, v, LeadStatus.NEW))
    _val = field_validator("estimated_value", mode="before")(lambda v: parse_money(v))
    _rec = field_validator("received_at", mode="before")(lambda v: parse_datetime(v))

    @field_validator("contact_email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        if v is None:
            return None
        email = normalize_email(v)
        if email is None:
            raise ValueError("invalid email address")
        return email


class QuoteRow(_Row):
    quote_number: str = Field(min_length=2, max_length=40)
    customer_name: str = Field(min_length=2, max_length=200)
    opportunity_name: str | None = None
    total: Decimal
    subtotal: Decimal | None = None
    discount_pct: Decimal = Decimal("0")
    status: QuoteStatus = QuoteStatus.SENT
    sent_at: datetime | None = None
    valid_until: date | None = None

    _tot = field_validator("total", "subtotal", mode="before")(lambda v: parse_money(v))
    _st = field_validator("status", mode="before")(lambda v: _enum(QuoteStatus, v, QuoteStatus.SENT))
    _sent = field_validator("sent_at", mode="before")(lambda v: parse_datetime(v))
    _valid = field_validator("valid_until", mode="before")(
        lambda v: parse_datetime(v).date() if v not in (None, "") else None
    )

    @field_validator("discount_pct", mode="before")
    @classmethod
    def _disc(cls, v: Any) -> Decimal:
        d = Decimal(str(v).rstrip("%")) if v not in (None, "") else Decimal("0")
        if not Decimal("0") <= d <= Decimal("100"):
            raise ValueError("discount must be between 0 and 100")
        return d


class ActivityRow(_Row):
    customer_name: str = Field(min_length=2, max_length=200)
    type: ActivityType
    description: str = Field(min_length=2, max_length=2000)
    occurred_at: datetime
    user_email: str | None = None
    opportunity_name: str | None = None

    _t = field_validator("type", mode="before")(lambda v: _enum(ActivityType, v))
    _o = field_validator("occurred_at", mode="before")(lambda v: parse_datetime(v))


ROW_MODELS: dict[str, type[_Row]] = {
    "customers": CustomerRow,
    "leads": LeadRow,
    "quotes": QuoteRow,
    "sales_activities": ActivityRow,
}


# ----------------------------------------------------------------------------------- parsing
def parse_rows(filename: str, data: bytes) -> list[dict[str, Any]]:
    settings = get_settings()
    if len(data) > settings.upload_max_bytes:
        raise AppError(ErrorCode.VALIDATION_FAILED, "File too large")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AppError(ErrorCode.VALIDATION_FAILED, "File must be UTF-8 encoded") from exc
    lower = filename.lower()
    if lower.endswith(".json"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AppError(ErrorCode.VALIDATION_FAILED, f"Invalid JSON: {exc.msg} (line {exc.lineno})") from exc
        rows = payload.get("rows") if isinstance(payload, dict) else payload
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise AppError(ErrorCode.VALIDATION_FAILED, 'JSON must be a list of objects (or {"rows": [...]})')
    elif lower.endswith(".csv"):
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise AppError(ErrorCode.VALIDATION_FAILED, "CSV has no header row")
        rows = list(reader)
    else:
        raise AppError(ErrorCode.UNSUPPORTED_FILE, "Upload a .csv or .json file")
    if len(rows) > settings.ingest_max_rows:
        raise AppError(ErrorCode.VALIDATION_FAILED, f"Too many rows ({len(rows)} > {settings.ingest_max_rows})")
    return [{re.sub(r"\s+", "_", str(k).strip().lower()): v for k, v in r.items() if k is not None} for r in rows]


# ----------------------------------------------------------------------------------- persistence
class _Resolver:
    """Caches tenant lookups used for entity resolution."""

    def __init__(self, session: AsyncSession, company_id: uuid.UUID) -> None:
        self.s, self.cid = session, company_id
        self.customers: dict[str, m.Customer] = {}
        self.users: dict[str, uuid.UUID] = {}

    async def load(self) -> None:
        for c in (await self.s.scalars(select(m.Customer).where(m.Customer.company_id == self.cid))).all():
            self.customers[c.normalized_name] = c
        for u in (await self.s.execute(select(m.User.email, m.User.id).where(m.User.company_id == self.cid))).all():
            self.users[u[0].lower()] = u[1]

    def customer(self, name: str) -> m.Customer | None:
        return self.customers.get(normalize_company_name(name))

    def user(self, email: str | None) -> uuid.UUID | None:
        return self.users.get(email.lower()) if email else None


async def ingest_file(
    session: AsyncSession,
    *,
    company_id: uuid.UUID,
    entity: Entity,
    filename: str,
    data: bytes,
    actor_id: uuid.UUID | None,
) -> m.IngestionJob:
    if entity not in ROW_MODELS:
        raise AppError(ErrorCode.INVALID_REQUEST, f"Unknown entity '{entity}'")
    raw_rows = parse_rows(filename, data)
    resolver = _Resolver(session, company_id)
    await resolver.load()
    errors: list[dict[str, Any]] = []
    counts = {"inserted": 0, "updated": 0, "duplicate": 0, "rejected": 0}
    seen: set[str] = set()
    handler: Callable[..., Any] = {
        "customers": _customer,
        "leads": _lead,
        "quotes": _quote,
        "sales_activities": _activity,
    }[entity]
    for idx, raw in enumerate(raw_rows, start=2 if filename.lower().endswith(".csv") else 1):
        try:
            row = ROW_MODELS[entity].model_validate(raw)
        except ValidationError as exc:
            counts["rejected"] += 1
            errors += [
                {
                    "row": idx,
                    "field": ".".join(map(str, e["loc"])) or "-",
                    "message": e["msg"].removeprefix("Value error, "),
                }
                for e in exc.errors()
            ]
            continue
        try:
            outcome = await handler(session, company_id, row, resolver, seen)
        except ValueError as exc:
            counts["rejected"] += 1
            errors.append({"row": idx, "field": "-", "message": str(exc)})
            continue
        counts[outcome] += 1
    status = (
        IngestionStatus.FAILED
        if counts["rejected"] and not (counts["inserted"] or counts["updated"])
        else IngestionStatus.COMPLETED_WITH_ERRORS
        if counts["rejected"]
        else IngestionStatus.COMPLETED
    )
    job = m.IngestionJob(
        company_id=company_id,
        entity=entity,
        filename=filename[:255],
        status=status,
        rows_total=len(raw_rows),
        rows_inserted=counts["inserted"],
        rows_updated=counts["updated"],
        rows_duplicate=counts["duplicate"],
        rows_rejected=counts["rejected"],
        errors=errors[:MAX_ERRORS_STORED],
        uploaded_by=actor_id,
    )
    session.add(job)
    record_audit(
        session,
        company_id=company_id,
        action="data.ingested",
        actor_type=ActorType.USER,
        actor_id=str(actor_id) if actor_id else None,
        entity_type="ingestion_job",
        entity_id=job.id,
        input={"entity": entity, "filename": filename, "rows": len(raw_rows)},
        output=counts,
    )
    await session.flush()
    return job


async def _customer(s: AsyncSession, cid: uuid.UUID, r: CustomerRow, res: _Resolver, seen: set[str]) -> str:
    key = normalize_company_name(r.name)
    if key in seen:
        return "duplicate"
    seen.add(key)
    existing = res.customers.get(key)
    if existing is not None:  # entity resolution: same normalised name → update non-empty fields
        for field in ("industry", "city", "state", "website", "employee_count"):
            if getattr(r, field) is not None:
                setattr(existing, field, getattr(r, field))
        return "updated"
    customer = m.Customer(
        company_id=cid,
        name=r.name,
        normalized_name=key,
        industry=r.industry,
        segment=r.segment,
        status=r.status,
        city=r.city,
        state=r.state,
        website=r.website,
        employee_count=r.employee_count,
        owner_id=res.user(r.owner_email),
    )
    s.add(customer)
    res.customers[key] = customer
    return "inserted"


async def _lead(s: AsyncSession, cid: uuid.UUID, r: LeadRow, res: _Resolver, seen: set[str]) -> str:
    key = f"{normalize_company_name(r.company_name)}|{r.contact_email or r.contact_phone or r.contact_name or ''}|{r.received_at.date()}"
    if key in seen:
        return "duplicate"
    seen.add(key)
    if r.contact_email:
        dup = await s.scalar(
            select(m.Lead.id).where(
                m.Lead.company_id == cid,
                m.Lead.contact_email == r.contact_email,
                m.Lead.received_at >= r.received_at - timedelta(days=30),
                m.Lead.received_at <= r.received_at + timedelta(days=30),
            )
        )
        if dup:
            return "duplicate"
    customer = res.customer(r.company_name)
    contact_id = None
    if customer is not None and (r.contact_email or r.contact_name):
        await s.flush()
        contact = None
        if r.contact_email:
            contact = await s.scalar(
                select(m.Contact).where(m.Contact.customer_id == customer.id, m.Contact.email == r.contact_email)
            )
        if contact is None:  # entity resolution: the lead's person becomes a contact of the matched customer
            contact = m.Contact(
                company_id=cid,
                customer_id=customer.id,
                full_name=r.contact_name or r.contact_email or "Unknown",
                email=r.contact_email,
                phone=r.contact_phone,
            )
            s.add(contact)
            await s.flush()
        contact_id = contact.id
    s.add(
        m.Lead(
            company_id=cid,
            customer_id=customer.id if customer else None,
            contact_id=contact_id,
            company_name=r.company_name,
            contact_name=r.contact_name,
            contact_email=r.contact_email,
            contact_phone=r.contact_phone,
            source=r.source,
            status=r.status,
            industry=customer.industry if customer else None,
            estimated_value=r.estimated_value,
            requirement=r.requirement,
            received_at=r.received_at,
            assigned_to=res.user(r.assigned_to_email) or (customer.owner_id if customer else None),
        )
    )
    return "inserted"


async def _quote(s: AsyncSession, cid: uuid.UUID, r: QuoteRow, res: _Resolver, seen: set[str]) -> str:
    if r.quote_number in seen:
        return "duplicate"
    seen.add(r.quote_number)
    if await s.scalar(select(m.Quote.id).where(m.Quote.company_id == cid, m.Quote.quote_number == r.quote_number)):
        return "duplicate"
    customer = res.customer(r.customer_name)
    if customer is None:
        raise ValueError(f"customer '{r.customer_name}' not found — import customers first")
    await s.flush()
    opp_q = (
        select(m.Opportunity).where(m.Opportunity.customer_id == customer.id).order_by(m.Opportunity.created_at.desc())
    )
    if r.opportunity_name:
        opp_q = opp_q.where(m.Opportunity.name == r.opportunity_name)
    opp = await s.scalar(opp_q.limit(1))
    if opp is None:
        contact_id = await s.scalar(
            select(m.Contact.id)
            .where(m.Contact.customer_id == customer.id)
            .order_by(m.Contact.is_decision_maker.desc(), m.Contact.created_at)
            .limit(1)
        )
        opp = m.Opportunity(
            company_id=cid,
            customer_id=customer.id,
            owner_id=customer.owner_id,
            primary_contact_id=contact_id,
            name=r.opportunity_name or f"{customer.name} — imported quote {r.quote_number}",
            stage=OpportunityStage.PROPOSAL,
            amount=r.total,
            last_activity_at=r.sent_at,
            stage_changed_at=r.sent_at,
        )
        s.add(opp)
        await s.flush()
    subtotal = r.subtotal or (r.total / (1 - r.discount_pct / 100) if r.discount_pct < 100 else r.total)
    s.add(
        m.Quote(
            company_id=cid,
            opportunity_id=opp.id,
            customer_id=customer.id,
            quote_number=r.quote_number,
            status=r.status,
            subtotal=subtotal.quantize(Decimal("0.01")),
            discount_pct=r.discount_pct,
            total=r.total,
            sent_at=r.sent_at,
            valid_until=r.valid_until or ((r.sent_at + timedelta(days=30)).date() if r.sent_at else None),
        )
    )
    return "inserted"


async def _activity(s: AsyncSession, cid: uuid.UUID, r: ActivityRow, res: _Resolver, seen: set[str]) -> str:
    key = f"{normalize_company_name(r.customer_name)}|{r.type}|{r.occurred_at.isoformat()}|{r.description[:40]}"
    if key in seen:
        return "duplicate"
    seen.add(key)
    customer = res.customer(r.customer_name)
    if customer is None:
        raise ValueError(f"customer '{r.customer_name}' not found")
    await s.flush()
    opp_id = None
    if r.opportunity_name:
        opp_id = await s.scalar(
            select(m.Opportunity.id).where(
                m.Opportunity.customer_id == customer.id, m.Opportunity.name == r.opportunity_name
            )
        )
    s.add(
        m.Activity(
            company_id=cid,
            customer_id=customer.id,
            opportunity_id=opp_id,
            user_id=res.user(r.user_email),
            type=r.type,
            description=r.description,
            occurred_at=r.occurred_at,
            metadata_={"source": "import"},
        )
    )
    return "inserted"


def sample_headers() -> dict[str, list[str]]:
    return {k: list(v.model_fields) for k, v in ROW_MODELS.items()}
