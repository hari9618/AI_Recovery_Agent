"""Transcript rendering and hashing (shared by conversation analysis cache and the risk engine)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from app.services.text import sha256_hex


class MessageLike(Protocol):
    sender_type: object
    sender_name: str
    body: str
    sent_at: object


def render_transcript(messages: Sequence[MessageLike]) -> str:
    """Stable plain-text transcript. Role labels come from data, never from message text."""
    lines = []
    for msg in messages:
        role = getattr(msg.sender_type, "value", msg.sender_type)
        label = "CUSTOMER" if role == "customer" else "SALES_REP" if role == "rep" else "SYSTEM"
        when = msg.sent_at.strftime("%Y-%m-%d %H:%M") if hasattr(msg.sent_at, "strftime") else str(msg.sent_at)
        lines.append(f"[{when}] {label} ({msg.sender_name}): {msg.body.strip()}")
    return "\n".join(lines)


def transcript_hash(messages: Sequence[MessageLike]) -> str:
    return sha256_hex(render_transcript(messages))
