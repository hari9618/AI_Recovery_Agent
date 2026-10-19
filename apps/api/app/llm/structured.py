"""Structured generation: call → validate → repair (re-ask with errors) → safe fallback.

Malformed model output is never accepted silently: each failed attempt is recorded in the local
`llm_calls` ledger and as an ERROR-level observation in Langfuse, and the final status
(`ok` / `repaired` / `fallback`) is returned to the caller so the UI can label the result.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import get_settings
from app.core.errors import ErrorCode, LLMError
from app.domain.enums import LLMCallStatus
from app.llm.base import ChatMessage, LLMProvider, LLMUsage
from app.llm.ledger import record_llm_call
from app.observability.tracing import get_tracer

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


@dataclass
class StructuredResult(Generic[T]):
    value: T | None
    status: LLMCallStatus
    model: str
    attempts: int
    usage: LLMUsage = field(default_factory=LLMUsage)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.value is not None and self.status in (LLMCallStatus.OK, LLMCallStatus.REPAIRED)


def parse_json_object(content: str | None) -> dict:
    if not content:
        raise ValueError("empty response")
    text = _FENCE.sub("", content.strip())
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in response")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("top-level JSON must be an object")
    return data


def _error_summary(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(f"{'.'.join(map(str, e['loc'])) or '<root>'}: {e['msg']}" for e in exc.errors()[:8])
    return str(exc)[:400]


async def generate_structured(
    provider: LLMProvider,
    messages: list[ChatMessage],
    response_model: type[T],
    *,
    purpose: str,
    fallback: Callable[[], T] | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> StructuredResult[T]:
    """Return a validated `response_model` instance, a labelled fallback, or raise on transport errors.

    Transport failures (timeout, rate limit, unavailable) raise `LLMError` after being recorded, so the
    caller can decide how to degrade. Validation failures are repaired up to
    `LLM_STRUCTURED_REPAIR_ATTEMPTS` times before falling back.
    """
    settings = get_settings()
    conversation = list(messages)
    usage = LLMUsage()
    errors: list[str] = []
    max_attempts = 1 + settings.llm_structured_repair_attempts

    for attempt in range(1, max_attempts + 1):
        try:
            response = await provider.complete(
                conversation, purpose=purpose, response_model=response_model,
                temperature=temperature, max_tokens=max_tokens,
            )
        except LLMError as exc:
            if exc.code != ErrorCode.LLM_INVALID_OUTPUT:
                await record_llm_call(purpose=purpose, provider=provider.name, model=provider.model,
                                      status=LLMCallStatus.ERROR, usage=usage, attempts=attempt, error=exc.message)
                raise
            errors.append(f"attempt {attempt}: provider schema validation failed")
            conversation = [*messages, ChatMessage(role="user", content=_repair_prompt(errors[-1]))]
            continue
        usage.add(response.usage)
        try:
            value = response_model.model_validate(parse_json_object(response.content))
        except (ValidationError, ValueError) as exc:
            summary = _error_summary(exc)
            errors.append(f"attempt {attempt}: {summary}")
            logger.warning("structured output invalid", extra={"purpose": purpose, "attempt": attempt, "error": summary})
            conversation = [
                *messages,
                ChatMessage(role="assistant", content=(response.content or "")[:4000]),
                ChatMessage(role="user", content=_repair_prompt(summary)),
            ]
            continue
        status = LLMCallStatus.OK if attempt == 1 else LLMCallStatus.REPAIRED
        await record_llm_call(purpose=purpose, provider=provider.name, model=response.model, status=status,
                              usage=usage, attempts=attempt, error="; ".join(errors) or None)
        return StructuredResult(value, status, response.model, attempt, usage, errors)

    # All attempts failed validation: never accept malformed output.
    with get_tracer().observation(
        f"structured_output_failure:{purpose}", as_type="guardrail", input={"errors": errors},
        metadata={"schema": response_model.__name__},
    ) as obs:
        obs.update(level="ERROR", status_message=f"{len(errors)} invalid attempts; using fallback")
    await record_llm_call(purpose=purpose, provider=provider.name, model=provider.model,
                          status=LLMCallStatus.FALLBACK, usage=usage, attempts=max_attempts, error="; ".join(errors))
    return StructuredResult(fallback() if fallback else None, LLMCallStatus.FALLBACK, provider.model,
                            max_attempts, usage, errors)


def _repair_prompt(error: str) -> str:
    return (
        "Your previous reply did not match the required JSON schema. Validation errors: "
        f"{error}. Reply again with ONLY the corrected JSON object — no prose, no code fences."
    )
