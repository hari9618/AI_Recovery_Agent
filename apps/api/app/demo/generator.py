"""Deterministic synthetic B2B dataset generator.

Produces plain dict rows (keyed by ORM column name) for every CRM table. Determinism: the same
`seed` and `now` always produce the same rows; dates are relative to `now` so the demo stays fresh.

Volumes (defaults): 320 customers, 520+ leads, 270 opportunities, 200+ quotes, 340+ conversations.
Every row carries `is_synthetic=True` where the table supports it.
"""

from __future__ import annotations

import random
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from faker import Faker

from app.demo import catalog as cat
from app.demo.conversation_templates import ARCHETYPES, STAGE_ARCHETYPES, SUBJECTS
from app.domain.enums import (
    ActivityType,
    Channel,
    CustomerSegment,
    CustomerStatus,
    FollowupStatus,
    LeadSource,
    LeadStatus,
    OpportunityStage,
    QuoteStatus,
    SenderType,
    UserRole,
)
from app.services.text import normalize_company_name

Row = dict[str, Any]
QUOTE_ARCHETYPES = {"quote_question", "price_objection", "competitor", "high_intent", "timing_delay", "won"}
# How long ago the last message of a conversation happened, per archetype (days).
STALENESS: dict[str, tuple[float, float]] = {
    "engaged": (0.2, 3),
    "quote_question": (2, 8),
    "price_objection": (1, 7),
    "competitor": (1, 6),
    "unanswered": (1, 6),
    "ghosting": (4, 18),
    "high_intent": (0.2, 3),
    "timing_delay": (3, 15),
}
OPEN_STAGE_MIX = (
    (OpportunityStage.PROSPECTING, 26),
    (OpportunityStage.QUALIFICATION, 34),
    (OpportunityStage.PROPOSAL, 55),
    (OpportunityStage.NEGOTIATION, 45),
)
VERTEX_NAME = "Vertex Industrial Solutions Pvt Ltd"


def _money(value: Decimal | float | int) -> Decimal:
    return Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def format_inr(value: Decimal) -> str:
    """Indian digit grouping, e.g. 480000 -> ₹4,80,000."""
    digits = str(int(value))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        head = re.sub(r"(\d)(?=(\d{2})+$)", r"\1,", head)
        digits = f"{head},{tail}"
    return f"₹{digits}"


@dataclass
class DemoDataset:
    company: Row
    users: list[Row] = field(default_factory=list)
    customers: list[Row] = field(default_factory=list)
    contacts: list[Row] = field(default_factory=list)
    leads: list[Row] = field(default_factory=list)
    opportunities: list[Row] = field(default_factory=list)
    quotes: list[Row] = field(default_factory=list)
    quote_items: list[Row] = field(default_factory=list)
    conversations: list[Row] = field(default_factory=list)
    messages: list[Row] = field(default_factory=list)
    followups: list[Row] = field(default_factory=list)
    activities: list[Row] = field(default_factory=list)
    # Generator-side ground truth for tests/evals only (never loaded into the product tables).
    ground_truth: dict[str, Any] = field(default_factory=dict)

    def counts(self) -> dict[str, int]:
        return {k: len(v) for k, v in self.__dict__.items() if isinstance(v, list)}


class DemoDataGenerator:
    def __init__(self, *, seed: int, now: datetime, company_name: str = "Arcline Systems") -> None:
        if now.tzinfo is None:
            raise ValueError("`now` must be timezone-aware")
        self.rng = random.Random(seed)
        self.fake = Faker("en_IN")
        self.fake.seed_instance(seed)
        self.now = now
        self.company_id = uuid.UUID(int=self.rng.getrandbits(128), version=4)
        self.company_name = company_name
        self._quote_seq = 1000
        self._used_names: set[str] = set()
        self.ds: DemoDataset

    # ------------------------------------------------------------------ helpers
    def _id(self) -> uuid.UUID:
        return uuid.UUID(int=self.rng.getrandbits(128), version=4)

    def _ago(self, days: float) -> datetime:
        return self.now - timedelta(days=days)

    def _business_hour(self, dt: datetime) -> datetime:
        # Snap to 09:30–18:30 IST (04:00–13:00 UTC) so timestamps look like office activity.
        return dt.replace(hour=self.rng.randint(4, 12), minute=self.rng.choice((0, 5, 10, 20, 30, 40, 45, 50)))

    def _base(self) -> Row:
        return {"id": self._id(), "company_id": self.company_id}

    # ------------------------------------------------------------------ build
    def build(self) -> DemoDataset:
        self.ds = DemoDataset(
            company={
                "id": self.company_id,
                "name": self.company_name,
                "industry": "Industrial IoT & Energy Monitoring",
                "currency": "INR",
                "timezone": "Asia/Kolkata",
                "settings": {},
                "is_demo": True,
            }
        )
        self._build_users()
        self._build_vertex_scenario()
        self._build_open_pipeline()
        self._build_closed_history()
        self._build_extra_leads_and_prospects()
        self._build_account_management()
        return self.ds

    def _build_users(self) -> None:
        def user(name: str, email: str, role: UserRole, region: str) -> Row:
            return {
                **self._base(),
                "full_name": name,
                "email": email,
                "role": role,
                "region": region,
                "is_active": True,
                "api_token_hash": None,
            }

        name, email, _, region = cat.OWNER
        self.owner = user(name, email, UserRole.OWNER, region)
        self.ds.users.append(self.owner)
        for name, email, _, region in cat.MANAGERS:
            self.ds.users.append(user(name, email, UserRole.MANAGER, region))
        self.reps: list[Row] = []
        for name, region in cat.REPS:
            first, last = name.lower().split()
            rep = user(name, f"{first}.{last}@arclinesystems.in", UserRole.SALES_REP, region)
            self.reps.append(rep)
            self.ds.users.append(rep)
        self.reps_by_region: dict[str, list[Row]] = {}
        for rep in self.reps:
            self.reps_by_region.setdefault(rep["region"], []).append(rep)

    # ------------------------------------------------------------------ entities
    def _new_customer(
        self,
        *,
        status: CustomerStatus,
        name: str | None = None,
        industry: str | None = None,
        city: tuple[str, str] | None = None,
    ) -> Row:
        industry = industry or self.rng.choice(list(cat.INDUSTRIES))
        if name is None:
            for _ in range(50):
                stem = self.rng.choice(cat.NAME_STEMS)
                core = self.rng.choice(cat.INDUSTRIES[industry])
                suffix = self.rng.choice(cat.LEGAL_SUFFIXES)
                name = " ".join(p for p in (stem, core, suffix) if p)
                if name not in self._used_names:
                    break
        assert name is not None
        self._used_names.add(name)
        city_name, state = city or self.rng.choice(cat.CITIES)
        region = cat.REGION_BY_STATE[state]
        owner = self.rng.choice(self.reps_by_region.get(region) or self.reps)
        segment = self.rng.choices(
            (CustomerSegment.SMB, CustomerSegment.MID_MARKET, CustomerSegment.ENTERPRISE), (45, 40, 15)
        )[0]
        employees = {
            CustomerSegment.SMB: (40, 250),
            CustomerSegment.MID_MARKET: (250, 1500),
            CustomerSegment.ENTERPRISE: (1500, 12000),
        }[segment]
        slug = re.sub(r"[^a-z]", "", name.lower().replace("pvt ltd", "").replace("llp", ""))[:22]
        customer = {
            **self._base(),
            "name": name,
            "normalized_name": normalize_company_name(name),
            "industry": industry,
            "segment": segment,
            "status": status,
            "city": city_name,
            "state": state,
            "country": "IN",
            "website": f"https://www.{slug}.in",
            "employee_count": self.rng.randint(*employees),
            "owner_id": owner["id"],
            "lifetime_value": Decimal("0"),
            "churned_at": None,
            "external_ref": None,
            "is_synthetic": True,
            "_domain": f"{slug}.in",
            "_short": " ".join(name.split()[:2]),
        }
        self.ds.customers.append(customer)
        contacts = [self._new_contact(customer, decision_maker=True)]
        for _ in range(self.rng.choice((0, 1, 1, 2))):
            contacts.append(self._new_contact(customer, decision_maker=False))
        customer["_contacts"] = contacts
        return customer

    def _new_contact(
        self, customer: Row, *, decision_maker: bool, name: str | None = None, title: str | None = None
    ) -> Row:
        full_name = name or f"{self.fake.first_name()} {self.fake.last_name()}"
        first, *rest = full_name.lower().split()
        title = title or (
            self.rng.choice(sorted(cat.DECISION_MAKER_TITLES))
            if decision_maker
            else self.rng.choice([t for t in cat.CONTACT_TITLES if t not in cat.DECISION_MAKER_TITLES])
        )
        contact = {
            **self._base(),
            "customer_id": customer["id"],
            "full_name": full_name,
            "email": f"{first}.{rest[-1] if rest else 'office'}@{customer['_domain']}",
            "phone": f"+91 9{self.rng.randint(100000000, 999999999)}",
            "title": title,
            "is_decision_maker": title in cat.DECISION_MAKER_TITLES,
        }
        self.ds.contacts.append(contact)
        return contact

    def _new_lead(
        self,
        customer: Row | None,
        *,
        status: LeadStatus,
        received: datetime,
        first_response: datetime | None,
        last_contact: datetime | None,
        value: Decimal | None,
        requirement: str,
        contact: Row | None = None,
        company_name: str | None = None,
        industry: str | None = None,
    ) -> Row:
        owner_id = customer["owner_id"] if customer else self.rng.choice(self.reps)["id"]
        lead = {
            **self._base(),
            "customer_id": customer["id"] if customer else None,
            "contact_id": contact["id"] if contact else None,
            "assigned_to": owner_id,
            "company_name": customer["name"] if customer else company_name,
            "contact_name": contact["full_name"] if contact else f"{self.fake.first_name()} {self.fake.last_name()}",
            "contact_email": contact["email"] if contact else None,
            "contact_phone": contact["phone"] if contact else f"+91 9{self.rng.randint(100000000, 999999999)}",
            "source": self.rng.choices(list(LeadSource), (30, 18, 10, 12, 8, 12, 10))[0],
            "status": status,
            "industry": customer["industry"] if customer else industry,
            "estimated_value": value,
            "requirement": requirement,
            "received_at": received,
            "first_response_at": first_response,
            "last_contact_at": last_contact,
            "is_synthetic": True,
        }
        self.ds.leads.append(lead)
        return lead

    def _quote_lines(self, sites: int, line: str) -> list[tuple[cat.Product, int, Decimal]]:
        p = cat.PRODUCT_BY_SKU
        lines: list[tuple[cat.Product, int, Decimal]] = [(p["ARC-GW-200"], sites, Decimal("0"))]
        if line in ("Energy monitoring", "Plant-wide monitoring"):
            lines.append((p["ARC-EM-3P"], sites * self.rng.randint(3, 9), Decimal("0")))
        if line in ("Condition monitoring", "Plant-wide monitoring"):
            lines.append((p["ARC-VS-10"], sites * self.rng.randint(4, 12), Decimal("0")))
        if line == "Cold-chain monitoring":
            lines.append((p["ARC-TH-05"], sites * self.rng.randint(8, 20), Decimal("0")))
        platform = p["PULSE-ENT"] if sites >= 4 and self.rng.random() < 0.5 else p["PULSE-STD"]
        lines.append((platform, sites, Decimal("0")))
        lines.append((p["SVC-INSTALL"], sites, Decimal("0")))
        if self.rng.random() < 0.4:
            lines.append((p["SVC-AMC"], sites, Decimal("0")))
        if self.rng.random() < 0.3:
            lines.append((p["SVC-TRAIN"], self.rng.randint(1, 3), Decimal("0")))
        return lines

    def _make_quote(
        self,
        opp: Row,
        customer: Row,
        *,
        lines: list[tuple[cat.Product, int, Decimal]],
        discount_pct: Decimal,
        status: QuoteStatus,
        sent_at: datetime | None,
        validity_days: int = 30,
        version: int = 1,
    ) -> Row:
        self._quote_seq += 1
        quote_id = self._id()
        subtotal = Decimal("0")
        for pos, (product, qty, line_disc) in enumerate(lines, start=1):
            line_total = _money(product.unit_price * qty * (1 - line_disc / 100))
            subtotal += line_total
            self.ds.quote_items.append(
                {
                    "id": self._id(),
                    "quote_id": quote_id,
                    "position": pos,
                    "sku": product.sku,
                    "description": product.name,
                    "quantity": Decimal(qty),
                    "unit_price": product.unit_price,
                    "discount_pct": line_disc,
                    "line_total": line_total,
                }
            )
        total = _money(subtotal * (1 - discount_pct / 100))
        quote = {
            "id": quote_id,
            "company_id": self.company_id,
            "opportunity_id": opp["id"],
            "customer_id": customer["id"],
            "quote_number": f"Q-{self.now.year}-{self._quote_seq:04d}",
            "version": version,
            "status": status,
            "subtotal": subtotal,
            "discount_pct": discount_pct,
            "tax_pct": Decimal("18"),
            "total": total,
            "currency": "INR",
            "sent_at": sent_at,
            "viewed_at": sent_at + timedelta(hours=self.rng.randint(2, 40))
            if sent_at and status != QuoteStatus.SENT
            else None,
            "valid_until": (sent_at + timedelta(days=validity_days)).date() if sent_at else None,
            "responded_at": None,
            "is_synthetic": True,
        }
        self.ds.quotes.append(quote)
        return quote

    def _conversation(
        self,
        *,
        customer: Row,
        contact: Row,
        opp: Row | None,
        rep: Row,
        archetype: str,
        end_at: datetime,
        fill: dict[str, str],
        channel: Channel | None = None,
        variant: int | None = None,
    ) -> Row:
        scripts = ARCHETYPES[archetype]
        script = scripts[variant if variant is not None else self.rng.randrange(len(scripts))]
        start = end_at - timedelta(days=script[-1][1])
        conv_id = self._id()
        last_sender = SenderType.CUSTOMER
        last_at = start
        for sender, offset, text in script:
            sent_at = start + timedelta(days=offset)
            is_customer = sender == "customer"
            self.ds.messages.append(
                {
                    "id": self._id(),
                    "conversation_id": conv_id,
                    "sender_type": SenderType.CUSTOMER if is_customer else SenderType.REP,
                    "sender_name": contact["full_name"] if is_customer else rep["full_name"],
                    "body": text.format(**fill),
                    "sent_at": sent_at,
                }
            )
            last_sender = SenderType.CUSTOMER if is_customer else SenderType.REP
            last_at = sent_at
        conv = {
            "id": conv_id,
            "company_id": self.company_id,
            "customer_id": customer["id"],
            "opportunity_id": opp["id"] if opp else None,
            "contact_id": contact["id"],
            "channel": channel or self.rng.choices((Channel.EMAIL, Channel.WHATSAPP, Channel.CHAT), (70, 25, 5))[0],
            "subject": self.rng.choice(SUBJECTS[archetype]),
            "started_at": start,
            "last_message_at": last_at,
            "last_sender": last_sender,
            "is_synthetic": True,
            "_archetype": archetype,
            "_rep_times": [start + timedelta(days=o) for s, o, _ in script if s == "rep"],
        }
        self.ds.conversations.append(conv)
        return conv

    def _activity(
        self,
        customer: Row,
        opp: Row | None,
        user: Row | None,
        type_: ActivityType,
        description: str,
        at: datetime,
        **meta: Any,
    ) -> None:
        self.ds.activities.append(
            {
                **self._base(),
                "customer_id": customer["id"],
                "opportunity_id": opp["id"] if opp else None,
                "user_id": user["id"] if user else None,
                "type": type_,
                "description": description,
                "occurred_at": at,
                "metadata_": meta,
            }
        )

    def _fill(
        self, customer: Row, contact: Row, rep: Row, amount: Decimal, quote_no: str, line: str, sites: int
    ) -> dict[str, str]:
        competitor = self.rng.choice(cat.COMPETITORS)
        return {
            "c": contact["full_name"].split()[0],
            "r": rep["full_name"].split()[0],
            "company": customer["_short"],
            "line": line.lower(),
            "amount": format_inr(amount),
            "quote_no": quote_no,
            "competitor": competitor,
            "comp_amount": format_inr(_money(amount * Decimal(self.rng.uniform(0.78, 0.9)) / 1000) * 1000),
            "target_amount": format_inr(_money(amount * Decimal(self.rng.uniform(0.82, 0.92)) / 1000) * 1000),
            "sites": str(sites),
            "city": customer["city"],
        }

    # ------------------------------------------------------------------ scenarios
    def _build_vertex_scenario(self) -> None:
        """The primary demo flow (Day 1 lead … Day 9 silence). Today is day 10."""
        customer = self._new_customer(
            status=CustomerStatus.PROSPECT, name=VERTEX_NAME, industry="Manufacturing", city=("Pune", "Maharashtra")
        )
        customer["segment"] = CustomerSegment.MID_MARKET
        customer["employee_count"] = 850
        customer["website"] = "https://www.vertexindustrial.in"
        customer["_domain"] = "vertexindustrial.in"
        rep = next(r for r in self.reps if r["full_name"] == "Priya Nair")
        customer["owner_id"] = rep["id"]
        # Replace the auto-generated contacts with named ones.
        for c in customer["_contacts"]:
            self.ds.contacts.remove(c)
        nikhil = self._new_contact(customer, decision_maker=True, name="Nikhil Deshpande", title="Plant Head")
        sunita = self._new_contact(customer, decision_maker=False, name="Sunita Joshi", title="Procurement Manager")
        customer["_contacts"] = [nikhil, sunita]

        day = lambda n, h=6: self._ago(10 - n).replace(hour=h, minute=30, second=0, microsecond=0)  # noqa: E731
        p = cat.PRODUCT_BY_SKU
        lines = [
            (p["PULSE-STD"], 1, Decimal("0")),
            (p["SVC-INSTALL"], 3, Decimal("0")),
            (p["ARC-GW-200"], 4, Decimal("0")),
            (p["ARC-EM-3P"], 5, Decimal("0")),
        ]
        lead = self._new_lead(
            customer,
            status=LeadStatus.CONVERTED,
            received=day(1, 5),
            first_response=day(1, 7),
            last_contact=day(3),
            value=Decimal("480000"),
            contact=nikhil,
            requirement="Energy and condition monitoring across 3 plants in Chakan and Ranjangaon",
        )
        opp = {
            **self._base(),
            "customer_id": customer["id"],
            "lead_id": lead["id"],
            "owner_id": rep["id"],
            "primary_contact_id": nikhil["id"],
            "name": "Vertex — Plant-wide energy monitoring (3 sites)",
            "stage": OpportunityStage.NEGOTIATION,
            "amount": Decimal("480000"),
            "currency": "INR",
            "product_line": "Plant-wide monitoring",
            "expected_close_date": (self.now + timedelta(days=12)).date(),
            "last_activity_at": day(3),
            "stage_changed_at": day(5),
            "closed_at": None,
            "loss_reason": None,
            "competitor": None,
            "is_synthetic": True,
        }
        self.ds.opportunities.append(opp)
        quote = self._make_quote(
            opp,
            customer,
            lines=lines,
            discount_pct=Decimal("0"),
            status=QuoteStatus.VIEWED,
            sent_at=day(3),
            validity_days=21,
        )
        assert quote["total"] == Decimal("480000"), quote["total"]
        conv_id = self._id()
        transcript = [
            (
                "rep",
                day(2, 8),
                "Hi Nikhil, thanks for your time on the call today. As discussed, we'll cover energy metering and gateway connectivity for all three plants, with Pulse dashboards for your maintenance team. I'll send the quotation tomorrow.",
            ),
            (
                "customer",
                day(2, 10),
                "Thanks Priya. Please include installation for all three sites. We want this live before the next quarter's energy audit.",
            ),
            (
                "rep",
                day(3, 6),
                f"Hi Nikhil, please find attached quotation {quote['quote_number']} for ₹4,80,000 covering 3 sites (gateways, energy meters, installation and the Pulse platform). The quote is valid for 21 days.",
            ),
            (
                "customer",
                day(5, 9),
                "Hi Priya, we went through the quote with our finance team. The solution fits well, but can you do better on the price? Our approved budget is around ₹4,30,000. We are keen to close this quickly.",
            ),
            (
                "customer",
                day(6, 7),
                "Also, to be transparent — Voltrix Systems has quoted ₹4,10,000 for a similar scope. We actually prefer your dashboard and the alerting, but I need to justify the difference to management. We'd like to finalise by the end of this month.",
            ),
        ]
        for sender, at, text in transcript:
            self.ds.messages.append(
                {
                    "id": self._id(),
                    "conversation_id": conv_id,
                    "sender_type": SenderType.CUSTOMER if sender == "customer" else SenderType.REP,
                    "sender_name": nikhil["full_name"] if sender == "customer" else rep["full_name"],
                    "body": text,
                    "sent_at": at,
                }
            )
        self.ds.conversations.append(
            {
                "id": conv_id,
                "company_id": self.company_id,
                "customer_id": customer["id"],
                "opportunity_id": opp["id"],
                "contact_id": nikhil["id"],
                "channel": Channel.EMAIL,
                "subject": "Quotation for plant-wide energy monitoring",
                "started_at": day(2, 8),
                "last_message_at": day(6, 7),
                "last_sender": SenderType.CUSTOMER,
                "is_synthetic": True,
                "_archetype": "vertex",
                "_rep_times": [day(2, 8), day(3, 6)],
            }
        )
        self._activity(
            customer, opp, rep, ActivityType.NOTE, "Inbound lead from website: monitoring for 3 plants", day(1, 5)
        )
        self._activity(
            customer,
            opp,
            rep,
            ActivityType.CALL,
            "Discovery call with Nikhil Deshpande (Plant Head) — 3 sites, wants go-live before energy audit",
            day(2, 7),
            duration_min=35,
        )
        self._activity(
            customer,
            opp,
            rep,
            ActivityType.QUOTE_SENT,
            f"Quotation {quote['quote_number']} sent (₹4,80,000)",
            day(3, 6),
            quote_id=str(quote["id"]),
        )
        self._activity(
            customer, opp, None, ActivityType.STAGE_CHANGE, "Stage changed Proposal → Negotiation", day(5, 10)
        )
        self.ds.followups.append(
            {
                **self._base(),
                "customer_id": customer["id"],
                "opportunity_id": opp["id"],
                "assigned_to": rep["id"],
                "title": "Respond to Vertex pricing question",
                "notes": "Customer asked for better pricing on 3-site quote",
                "due_at": day(6, 12),
                "status": FollowupStatus.PENDING,
                "completed_at": None,
                "created_by_agent": False,
                "recommendation_id": None,
            }
        )
        self.ds.ground_truth["vertex"] = {
            "customer_id": str(customer["id"]),
            "opportunity_id": str(opp["id"]),
            "quote_id": str(quote["id"]),
            "conversation_id": str(conv_id),
            "expected_risk_level": "critical",
        }

    def _build_open_pipeline(self) -> None:
        for stage, count in OPEN_STAGE_MIX:
            for _ in range(count):
                existing = [c for c in self.ds.customers if c["status"] == CustomerStatus.ACTIVE]
                upsell = existing and self.rng.random() < 0.12
                customer = self.rng.choice(existing) if upsell else self._new_customer(status=CustomerStatus.PROSPECT)
                self._open_opportunity(customer, stage)

    def _open_opportunity(self, customer: Row, stage: OpportunityStage) -> None:
        rep = next(r for r in self.reps if r["id"] == customer["owner_id"])
        contact = customer["_contacts"][0]
        archetype = self.rng.choice(STAGE_ARCHETYPES[stage.value])
        line = self.rng.choice(cat.PRODUCT_LINES)
        sites = self.rng.choices((1, 2, 3, 4, 6, 8), (30, 25, 18, 12, 9, 6))[0]
        lines = self._quote_lines(sites, line)
        stale = self.rng.uniform(*STALENESS[archetype])
        end_at = self._business_hour(self._ago(stale))
        has_quote = stage in (OpportunityStage.PROPOSAL, OpportunityStage.NEGOTIATION)
        script_len = max(o for _, o, _ in ARCHETYPES[archetype][0])
        conv_start = end_at - timedelta(days=script_len)
        received = conv_start - timedelta(days=self.rng.uniform(5, 40))
        opp = {
            **self._base(),
            "customer_id": customer["id"],
            "lead_id": None,
            "owner_id": rep["id"],
            "primary_contact_id": contact["id"],
            "name": f"{customer['_short']} — {line}",
            "stage": stage,
            "amount": Decimal("0"),
            "currency": "INR",
            "product_line": line,
            "expected_close_date": (self.now + timedelta(days=self.rng.randint(-10, 75))).date(),
            "last_activity_at": None,
            "stage_changed_at": conv_start,
            "closed_at": None,
            "loss_reason": None,
            "competitor": None,
            "is_synthetic": True,
        }
        quote = None
        discount = self.rng.choices((Decimal("0"), Decimal("5"), Decimal("8"), Decimal("10")), (55, 20, 15, 10))[0]
        if has_quote:
            status = QuoteStatus.VIEWED if self.rng.random() < 0.6 else QuoteStatus.SENT
            # Some quotes were sent long enough ago to be expiring / expired.
            validity = self.rng.choice((30, 30, 21, 15))
            sent_at = (
                conv_start if archetype in QUOTE_ARCHETYPES else conv_start - timedelta(days=self.rng.uniform(2, 10))
            )
            quote = self._make_quote(
                opp,
                customer,
                lines=lines,
                discount_pct=discount,
                status=status,
                sent_at=sent_at,
                validity_days=validity,
            )
            if quote["valid_until"] and quote["valid_until"] < self.now.date():
                quote["status"] = QuoteStatus.EXPIRED
            opp["amount"] = quote["total"]
        else:
            opp["amount"] = _money(sum(p.unit_price * q for p, q, _ in lines) * (1 - discount / 100))
        self.ds.opportunities.append(opp)
        fill = self._fill(
            customer, contact, rep, opp["amount"], quote["quote_number"] if quote else "(draft)", line, sites
        )
        conv = self._conversation(
            customer=customer, contact=contact, opp=opp, rep=rep, archetype=archetype, end_at=end_at, fill=fill
        )
        if archetype == "competitor":
            opp["competitor"] = fill["competitor"] if self.rng.random() < 0.5 else None
        rep_times = conv["_rep_times"] or [received + timedelta(hours=self.rng.randint(2, 30))]
        opp["last_activity_at"] = max(rep_times)
        lead = self._new_lead(
            customer,
            status=LeadStatus.CONVERTED if stage != OpportunityStage.PROSPECTING else LeadStatus.QUALIFIED,
            received=received,
            first_response=received + timedelta(hours=self.rng.uniform(1, 30)),
            last_contact=max(rep_times),
            value=opp["amount"],
            contact=contact,
            requirement=f"{line} for {sites} site(s)",
        )
        opp["lead_id"] = lead["id"]
        self._activity(
            customer,
            opp,
            rep,
            ActivityType.CALL,
            f"Discovery call with {contact['full_name']}",
            received + timedelta(days=1),
        )
        if quote and quote["sent_at"]:
            self._activity(
                customer,
                opp,
                rep,
                ActivityType.QUOTE_SENT,
                f"Quotation {quote['quote_number']} sent ({format_inr(quote['total'])})",
                quote["sent_at"],
                quote_id=str(quote["id"]),
            )
        for t in rep_times:
            self._activity(customer, opp, rep, ActivityType.EMAIL, f"Email to {contact['full_name']}", t)
        # Follow-ups: stale archetypes tend to have overdue ones.
        overdue_bias = {
            "ghosting": 0.7,
            "quote_question": 0.75,
            "price_objection": 0.6,
            "competitor": 0.6,
            "unanswered": 0.7,
            "timing_delay": 0.5,
        }.get(archetype, 0.15)
        if self.rng.random() < 0.8:
            overdue = self.rng.random() < overdue_bias
            due = (
                self._ago(self.rng.uniform(1, max(stale, 1.5)))
                if overdue
                else self.now + timedelta(days=self.rng.uniform(0.5, 6))
            )
            self.ds.followups.append(
                {
                    **self._base(),
                    "customer_id": customer["id"],
                    "opportunity_id": opp["id"],
                    "assigned_to": rep["id"],
                    "title": self.rng.choice(
                        (
                            "Follow up on quotation",
                            "Call to discuss proposal",
                            "Share revised proposal",
                            "Check decision timeline",
                            "Send case study",
                        )
                    ),
                    "notes": None,
                    "due_at": due,
                    "status": FollowupStatus.PENDING,
                    "completed_at": None,
                    "created_by_agent": False,
                    "recommendation_id": None,
                }
            )
        if self.rng.random() < 0.5:
            done_at = conv["started_at"] - timedelta(days=self.rng.uniform(0.5, 4))
            self.ds.followups.append(
                {
                    **self._base(),
                    "customer_id": customer["id"],
                    "opportunity_id": opp["id"],
                    "assigned_to": rep["id"],
                    "title": "Initial discovery follow-up",
                    "notes": None,
                    "due_at": done_at,
                    "status": FollowupStatus.COMPLETED,
                    "completed_at": done_at,
                    "created_by_agent": False,
                    "recommendation_id": None,
                }
            )

    def _build_closed_history(self) -> None:
        for won in [True] * 60 + [False] * 50:
            customer = self._new_customer(status=CustomerStatus.ACTIVE if won else CustomerStatus.PROSPECT)
            rep = next(r for r in self.reps if r["id"] == customer["owner_id"])
            contact = customer["_contacts"][0]
            line = self.rng.choice(cat.PRODUCT_LINES)
            sites = self.rng.choices((1, 2, 3, 4, 6), (35, 28, 18, 12, 7))[0]
            lines = self._quote_lines(sites, line)
            closed_at = self._business_hour(self._ago(self.rng.uniform(15, 360)))
            sent_at = closed_at - timedelta(days=self.rng.uniform(5, 40))
            received = sent_at - timedelta(days=self.rng.uniform(10, 45))
            opp = {
                **self._base(),
                "customer_id": customer["id"],
                "lead_id": None,
                "owner_id": rep["id"],
                "primary_contact_id": contact["id"],
                "name": f"{customer['_short']} — {line}",
                "stage": OpportunityStage.CLOSED_WON if won else OpportunityStage.CLOSED_LOST,
                "amount": Decimal("0"),
                "currency": "INR",
                "product_line": line,
                "expected_close_date": closed_at.date(),
                "last_activity_at": closed_at,
                "stage_changed_at": closed_at,
                "closed_at": closed_at,
                "loss_reason": None if won else self.rng.choice(cat.LOSS_REASONS),
                "competitor": None,
                "is_synthetic": True,
            }
            discount = self.rng.choices((Decimal("0"), Decimal("5"), Decimal("10"), Decimal("12")), (40, 30, 22, 8))[0]
            has_quote = True  # lost deals in this dataset all reached the quotation stage
            if has_quote:
                quote = self._make_quote(
                    opp,
                    customer,
                    lines=lines,
                    discount_pct=discount,
                    status=QuoteStatus.ACCEPTED
                    if won
                    else self.rng.choice((QuoteStatus.REJECTED, QuoteStatus.EXPIRED)),
                    sent_at=sent_at,
                )
                quote["responded_at"] = closed_at if won else None
                opp["amount"] = quote["total"]
            else:
                opp["amount"] = _money(sum(p.unit_price * q for p, q, _ in lines))
            if not won and opp["loss_reason"] == "Chose competitor on price":
                opp["competitor"] = self.rng.choice(cat.COMPETITORS)
            self.ds.opportunities.append(opp)
            lead = self._new_lead(
                customer,
                status=LeadStatus.CONVERTED if won else LeadStatus.LOST,
                received=received,
                first_response=received + timedelta(hours=self.rng.uniform(1, 48)),
                last_contact=closed_at,
                value=opp["amount"],
                contact=contact,
                requirement=f"{line} for {sites} site(s)",
            )
            opp["lead_id"] = lead["id"]
            fill = self._fill(customer, contact, rep, opp["amount"], "(final)", line, sites)
            if opp["competitor"]:
                fill["competitor"] = opp["competitor"]
            self._conversation(
                customer=customer,
                contact=contact,
                opp=opp,
                rep=rep,
                archetype="won" if won else "lost",
                end_at=closed_at,
                fill=fill,
                variant=None if won else (0 if opp["competitor"] else 1),
            )
            self._activity(
                customer,
                opp,
                rep,
                ActivityType.STAGE_CHANGE,
                f"Deal {'won' if won else 'lost'}" + ("" if won else f": {opp['loss_reason']}"),
                closed_at,
            )
            if won:
                customer["lifetime_value"] = opp["amount"]
                if self.rng.random() < 0.3:
                    customer["status"] = CustomerStatus.CHURNED
                    customer["churned_at"] = closed_at + timedelta(days=self.rng.uniform(120, 300))
                    if customer["churned_at"] > self.now:
                        customer["status"], customer["churned_at"] = CustomerStatus.ACTIVE, None

    def _build_extra_leads_and_prospects(self) -> None:
        """Leads that have not (yet) become opportunities, including unanswered inbound leads."""
        plan = (
            (LeadStatus.NEW, 55),
            (LeadStatus.CONTACTED, 70),
            (LeadStatus.UNQUALIFIED, 55),
            (LeadStatus.LOST, 40),
            (LeadStatus.QUALIFIED, 30),
        )
        for status, count in plan:
            for _ in range(count):
                received = self._business_hour(self._ago(self.rng.uniform(0.3, 60 if status != LeadStatus.NEW else 6)))
                industry = self.rng.choice(list(cat.INDUSTRIES))
                line = self.rng.choice(cat.PRODUCT_LINES)
                value = _money(self.rng.uniform(80, 1800) * 1000) if self.rng.random() < 0.7 else None
                needs_customer = status in (LeadStatus.CONTACTED, LeadStatus.QUALIFIED) and self.rng.random() < 0.75
                customer = (
                    self._new_customer(status=CustomerStatus.PROSPECT, industry=industry) if needs_customer else None
                )
                contact = customer["_contacts"][0] if customer else None
                responded = status != LeadStatus.NEW or self.rng.random() < 0.35
                first_response = received + timedelta(hours=self.rng.uniform(1, 72)) if responded else None
                if first_response and first_response > self.now:
                    first_response = None
                name = None
                if customer is None:
                    stem = self.rng.choice(cat.NAME_STEMS)
                    name = f"{stem} {self.rng.choice(cat.INDUSTRIES[industry])}"
                lead = self._new_lead(
                    customer,
                    status=status,
                    received=received,
                    first_response=first_response,
                    last_contact=first_response,
                    value=value,
                    contact=contact,
                    company_name=name,
                    industry=industry,
                    requirement=f"Enquiry: {line.lower()}",
                )
                if customer and contact and self.rng.random() < 0.4:
                    rep = next(r for r in self.reps if r["id"] == customer["owner_id"])
                    fill = self._fill(customer, contact, rep, value or Decimal("250000"), "(draft)", line, 2)
                    end = min(received + timedelta(days=self.rng.uniform(1, 5)), self.now - timedelta(hours=3))
                    self._conversation(
                        customer=customer,
                        contact=contact,
                        opp=None,
                        rep=rep,
                        archetype=self.rng.choice(("unanswered", "engaged")),
                        end_at=end,
                        fill=fill,
                    )
                    lead["last_contact_at"] = end

    def _build_account_management(self) -> None:
        active = [c for c in self.ds.customers if c["status"] == CustomerStatus.ACTIVE]
        for customer in self.rng.sample(active, k=min(30, len(active))):
            rep = next(r for r in self.reps if r["id"] == customer["owner_id"])
            contact = customer["_contacts"][0]
            fill = self._fill(customer, contact, rep, Decimal("60000"), "(renewal)", "AMC renewal", 1)
            end = self._business_hour(self._ago(self.rng.uniform(1, 40)))
            self._conversation(
                customer=customer,
                contact=contact,
                opp=None,
                rep=rep,
                archetype="account_management",
                end_at=end,
                fill=fill,
            )


def strip_private(row: Row) -> Row:
    """Drop generator-only keys (prefixed with `_`) before inserting."""
    return {k: v for k, v in row.items() if not k.startswith("_")}


def generate_demo_dataset(seed: int, now: datetime, company_name: str = "Arcline Systems") -> DemoDataset:
    return DemoDataGenerator(seed=seed, now=now, company_name=company_name).build()


__all__ = ["VERTEX_NAME", "DemoDataset", "format_inr", "generate_demo_dataset", "strip_private"]
