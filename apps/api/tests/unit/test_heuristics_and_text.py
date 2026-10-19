import pytest

from app.domain.heuristics import analyze_customer_messages
from app.services.text import normalize_company_name, normalize_email


def test_price_and_competitor_detection_with_evidence():
    h = analyze_customer_messages(
        [
            "Can you do better on the price? Our approved budget is around ₹4,30,000.",
            "Voltrix Systems has quoted ₹4,10,000 for a similar scope. We'd like to finalise this month.",
        ],
        known_competitors=["Voltrix Systems"],
    )
    assert h.price_objection and h.competitor_mentioned
    assert h.competitors == ["Voltrix Systems"]
    assert "price" in h.evidence["PRICE_OBJECTION"].lower()
    assert h.intent == "high"


def test_low_intent_detection():
    h = analyze_customer_messages(["This is not a priority right now. We will get back if things change."])
    assert h.intent == "low"
    assert not h.price_objection


def test_empty_input_is_unknown():
    assert analyze_customer_messages([]).intent == "unknown"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Vertex Industrial Solutions Pvt. Ltd.", "vertex industrial solutions"),
        ("VERTEX INDUSTRIAL SOLUTIONS PRIVATE LIMITED", "vertex industrial solutions"),
        ("Kaveri Agro Foods LLP", "kaveri agro foods"),
        ("Lotus Hotels & Resorts Ltd", "lotus hotels and resorts"),
        ("  Indus   Pharma  ", "indus pharma"),
    ],
)
def test_company_name_normalisation(raw, expected):
    assert normalize_company_name(raw) == expected


def test_email_normalisation():
    assert normalize_email("  Nikhil.D@VertexIndustrial.in ") == "nikhil.d@vertexindustrial.in"
    assert normalize_email("not-an-email") is None
    assert normalize_email(None) is None
