"""Static reference data for the synthetic demo tenant ("Arcline Systems").

Arcline is a fictional B2B company selling industrial monitoring hardware, a SaaS platform and
services. Nothing here is specific to the engines: risk, policy and RAG are domain-agnostic, the
catalog only makes the demo believable. All companies and competitors below are fictional.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    unit_price: Decimal
    kind: str  # hardware | software | service


PRODUCTS: tuple[Product, ...] = (
    Product("ARC-GW-200", "Arcline Edge Gateway GW-200", Decimal("38500"), "hardware"),
    Product("ARC-EM-3P", "Three-phase Energy Meter EM-3P", Decimal("14200"), "hardware"),
    Product("ARC-VS-10", "Wireless Vibration Sensor VS-10", Decimal("9800"), "hardware"),
    Product("ARC-TH-05", "Temperature & Humidity Sensor TH-05", Decimal("4600"), "hardware"),
    Product("PULSE-STD", "Arcline Pulse Platform — Standard (per site / year)", Decimal("120000"), "software"),
    Product("PULSE-ENT", "Arcline Pulse Platform — Enterprise (per site / year)", Decimal("240000"), "software"),
    Product("SVC-INSTALL", "Installation & commissioning (per site)", Decimal("45000"), "service"),
    Product("SVC-AMC", "Annual maintenance contract (per site)", Decimal("60000"), "service"),
    Product("SVC-TRAIN", "Operator training (per batch of 15)", Decimal("18000"), "service"),
)
PRODUCT_BY_SKU = {p.sku: p for p in PRODUCTS}

PRODUCT_LINES = (
    "Energy monitoring",
    "Condition monitoring",
    "Cold-chain monitoring",
    "Pulse platform subscription",
    "Plant-wide monitoring",
)

COMPETITORS = ("Voltrix Systems", "Sensara IoT", "GridSense Technologies", "Plantwise Automation")

# --- team -------------------------------------------------------------------------------
OWNER = ("Meera Raghavan", "meera.raghavan@arclinesystems.in", "owner", "All India")
MANAGERS = (("Arjun Mehta", "arjun.mehta@arclinesystems.in", "manager", "West & South"),)
REPS = (
    ("Priya Nair", "West"),
    ("Rohan Kulkarni", "West"),
    ("Sneha Iyer", "South"),
    ("Karan Malhotra", "North"),
    ("Ananya Bose", "East"),
    ("Vikram Shetty", "South"),
    ("Farhan Qureshi", "North"),
    ("Divya Menon", "South"),
)

# --- customers ----------------------------------------------------------------------------
INDUSTRIES: dict[str, tuple[str, ...]] = {
    "Manufacturing": (
        "Precision Castings",
        "Engineering Works",
        "Forgings",
        "Auto Components",
        "Polymers",
        "Fabricators",
    ),
    "Pharmaceuticals": ("Pharma", "Life Sciences", "Formulations", "Biologics"),
    "Logistics & Warehousing": ("Logistics", "Cold Chain", "Warehousing", "Freight Solutions"),
    "Hospitality": ("Hotels & Resorts", "Hospitality Group", "Residency Hotels"),
    "Healthcare": ("Multispeciality Hospitals", "Healthcare", "Diagnostics"),
    "Commercial Real Estate": ("Business Parks", "Realty", "Infra Developers", "Tech Parks"),
    "Food Processing": ("Agro Foods", "Dairy", "Food Products", "Beverages"),
    "Retail": ("Retail", "Supermarkets", "Hypermart"),
    "Data Centers": ("Data Systems", "Cloud Infra", "Datacenters"),
    "Education": ("Education Society", "Institute of Technology", "Group of Institutions"),
    "Textiles": ("Textiles", "Spinning Mills", "Fabrics"),
}

NAME_STEMS = (
    "Kaveri",
    "Sahyadri",
    "Indus",
    "Narmada",
    "Aravali",
    "Deccan",
    "Konark",
    "Shivalik",
    "Vindhya",
    "Godavari",
    "Nilgiri",
    "Malabar",
    "Coromandel",
    "Satpura",
    "Tapti",
    "Meridian",
    "Northgate",
    "Brightline",
    "Silverline",
    "Bluestone",
    "Crestwood",
    "Evergreen",
    "Summit",
    "Pinnacle",
    "Horizon",
    "Keystone",
    "Trident",
    "Orion",
    "Zenith",
    "Vardhman",
    "Balaji",
    "Annapurna",
    "Suvidha",
    "Pragati",
    "Unnati",
    "Sanghvi",
    "Bharat",
    "Jyoti",
    "Navkar",
    "Ratnagiri",
    "Kesari",
    "Prabhat",
    "Samrat",
    "Sunrise",
    "Greenfield",
    "Lotus",
    "Mahalaxmi",
    "Shubham",
    "Amrit",
    "Om Sai",
    "Sterling",
    "Everest",
    "Cauvery",
    "Hindustan",
    "Pioneer",
    "Riverside",
    "Westbay",
    "Eastwind",
    "Sapphire",
    "Emerald",
    "Garuda",
    "Tirupati",
    "Agastya",
    "Saraswati",
    "Kalinga",
    "Magadh",
    "Vijaya",
    "Chola",
    "Pallava",
    "Rajhans",
    "Kohinoor",
    "Siddhi",
    "Akshar",
    "Parijat",
    "Neelkanth",
    "Triveni",
    "Sangam",
    "Utkal",
)
LEGAL_SUFFIXES = ("Pvt Ltd", "Pvt Ltd", "Pvt Ltd", "Ltd", "LLP", "")

CITIES: tuple[tuple[str, str], ...] = (
    ("Pune", "Maharashtra"),
    ("Mumbai", "Maharashtra"),
    ("Nashik", "Maharashtra"),
    ("Aurangabad", "Maharashtra"),
    ("Bengaluru", "Karnataka"),
    ("Mysuru", "Karnataka"),
    ("Chennai", "Tamil Nadu"),
    ("Coimbatore", "Tamil Nadu"),
    ("Hyderabad", "Telangana"),
    ("Ahmedabad", "Gujarat"),
    ("Vadodara", "Gujarat"),
    ("Surat", "Gujarat"),
    ("Gurugram", "Haryana"),
    ("Noida", "Uttar Pradesh"),
    ("Ludhiana", "Punjab"),
    ("Jaipur", "Rajasthan"),
    ("Kolkata", "West Bengal"),
    ("Bhubaneswar", "Odisha"),
    ("Kochi", "Kerala"),
    ("Indore", "Madhya Pradesh"),
)
REGION_BY_STATE = {
    "Maharashtra": "West",
    "Gujarat": "West",
    "Madhya Pradesh": "West",
    "Rajasthan": "North",
    "Karnataka": "South",
    "Tamil Nadu": "South",
    "Telangana": "South",
    "Kerala": "South",
    "Haryana": "North",
    "Uttar Pradesh": "North",
    "Punjab": "North",
    "West Bengal": "East",
    "Odisha": "East",
}

CONTACT_TITLES = (
    "Plant Head",
    "Head of Maintenance",
    "Facilities Manager",
    "Energy Manager",
    "Operations Director",
    "Procurement Manager",
    "Chief Engineer",
    "General Manager — Projects",
    "Purchase Head",
    "CFO",
    "Head of Engineering",
    "Admin & Facilities Lead",
    "Quality Head",
    "IT Infrastructure Manager",
)
DECISION_MAKER_TITLES = {"Plant Head", "Operations Director", "CFO", "General Manager — Projects", "Purchase Head"}

LOSS_REASONS = (
    "Chose competitor on price",
    "Budget frozen for the year",
    "No decision — project deprioritised",
    "Went with incumbent vendor",
    "Lost contact after quote",
    "Requirement changed",
)
