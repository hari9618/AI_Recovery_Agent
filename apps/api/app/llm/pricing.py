"""Estimated LLM cost. Always labelled *estimated*: provider invoices are the source of truth.

Prices are USD per 1M tokens as published on console.groq.com/docs/models (checked 2026-10).
`LLM_PRICE_INPUT_PER_M` / `LLM_PRICE_OUTPUT_PER_M` override the table for any model.
"""

from __future__ import annotations

from app.core.config import get_settings

KNOWN_PRICES_PER_M: dict[str, tuple[float, float]] = {
    "openai/gpt-oss-120b": (0.15, 0.60),
    "openai/gpt-oss-20b": (0.075, 0.30),
    "openai/gpt-oss-safeguard-20b": (0.075, 0.30),
    "qwen/qwen3.8-27b": (0.80, 4.00),
}


def price_for(model: str) -> tuple[float, float] | None:
    settings = get_settings()
    if settings.llm_price_input_per_m is not None and settings.llm_price_output_per_m is not None:
        return settings.llm_price_input_per_m, settings.llm_price_output_per_m
    return KNOWN_PRICES_PER_M.get(model)


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    price = price_for(model)
    if price is None:
        return 0.0
    return round(input_tokens / 1e6 * price[0] + output_tokens / 1e6 * price[1], 6)
