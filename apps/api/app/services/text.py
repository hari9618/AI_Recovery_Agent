"""Small, deterministic text utilities (normalisation, hashing)."""

from __future__ import annotations

import hashlib
import re
import unicodedata

_LEGAL_SUFFIXES = re.compile(
    r"\b(private limited|pvt\.? ltd\.?|pvt|limited|ltd\.?|llp|inc\.?|incorporated|corp\.?|co\.?|company)\s*$"
)


def normalize_company_name(name: str) -> str:
    """Canonical form for entity resolution: lower-case, ASCII, no punctuation or legal suffix.

    >>> normalize_company_name("Vertex Industrial Solutions Pvt. Ltd.")
    'vertex industrial solutions'
    """
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower().strip()
    text = text.replace("&", " and ")
    text = re.sub(r"[^\w\s.]", " ", text)
    for _ in range(2):  # "Foo Co. Pvt Ltd" -> strip twice
        text = _LEGAL_SUFFIXES.sub("", text.strip()).strip()
    text = text.replace(".", " ")
    return re.sub(r"\s+", " ", text).strip()


def normalize_email(email: str | None) -> str | None:
    if not email:
        return None
    email = email.strip().lower()
    return email if re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", email) else None


def sha256_hex(text: str | bytes) -> str:
    data = text.encode("utf-8") if isinstance(text, str) else text
    return hashlib.sha256(data).hexdigest()
