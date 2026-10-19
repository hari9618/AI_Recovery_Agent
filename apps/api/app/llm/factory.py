"""Provider selection. Callers depend on `LLMProvider`, never on a concrete vendor class."""

from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.core.errors import ErrorCode, LLMError
from app.llm.base import LLMProvider


@lru_cache
def get_llm_provider() -> LLMProvider:
    """Return the configured provider or raise LLM_NOT_CONFIGURED (callers degrade gracefully)."""
    settings = get_settings()
    if not settings.llm_configured:
        raise LLMError(ErrorCode.LLM_NOT_CONFIGURED, "No LLM configured: set GROQ_API_KEY and GROQ_MODEL")
    if settings.llm_provider == "groq":
        from app.llm.groq_provider import GroqProvider  # noqa: PLC0415

        return GroqProvider(settings)
    raise LLMError(ErrorCode.LLM_NOT_CONFIGURED, f"Unknown LLM provider {settings.llm_provider!r}")


def llm_available() -> bool:
    try:
        get_llm_provider()
    except LLMError:
        return False
    return True
