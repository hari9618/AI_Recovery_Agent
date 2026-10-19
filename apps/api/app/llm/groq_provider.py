"""Groq implementation of LLMProvider (official `groq` async SDK).

This is the only module that imports `groq`. It maps SDK exceptions onto the application error
contract, records a Langfuse generation per call (model, tokens, latency, estimated cost) and
limits concurrency to avoid tripping Groq rate limits.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import groq
from pydantic import BaseModel

from app.core.config import Settings
from app.core.errors import ErrorCode, LLMError
from app.llm.base import ChatMessage, LLMProvider, LLMResponse, LLMUsage, ToolCall, ToolDefinition
from app.llm.pricing import estimate_cost_usd
from app.llm.schema import compact_schema_hint, strict_json_schema
from app.observability.tracing import get_tracer

logger = logging.getLogger(__name__)

# Models that accept `reasoning_effort` / `include_reasoning` (Groq reasoning models).
_REASONING_PREFIXES = ("openai/gpt-oss",)


class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(self, settings: Settings) -> None:
        if not settings.llm_configured or settings.groq_api_key is None or settings.groq_model is None:
            raise LLMError(ErrorCode.LLM_NOT_CONFIGURED, "Groq is not configured")
        self._settings = settings
        self._model = settings.groq_model
        self._client = groq.AsyncGroq(
            api_key=settings.groq_api_key.get_secret_value(),
            base_url=settings.groq_base_url,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,  # SDK retries 429/5xx/timeouts with backoff
        )
        self._semaphore = asyncio.Semaphore(settings.llm_max_concurrency)

    @property
    def model(self) -> str:
        return self._model

    def _is_reasoning_model(self) -> bool:
        return self._model.startswith(_REASONING_PREFIXES)

    def _request(
        self,
        messages: list[ChatMessage],
        response_model: type[BaseModel] | None,
        tools: list[ToolDefinition] | None,
        temperature: float | None,
        max_tokens: int | None,
    ) -> dict[str, Any]:
        msgs = [m.to_dict() for m in messages]
        req: dict[str, Any] = {
            "model": self._model,
            "temperature": self._settings.llm_temperature if temperature is None else temperature,
            "max_completion_tokens": max_tokens or self._settings.llm_max_output_tokens,
        }
        if self._is_reasoning_model():
            if self._settings.groq_reasoning_effort:
                req["reasoning_effort"] = self._settings.groq_reasoning_effort
            req["include_reasoning"] = False
        if response_model is not None:
            if self._settings.groq_structured_mode == "json_schema":
                req["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": response_model.__name__,
                        "strict": True,
                        "schema": strict_json_schema(response_model),
                    },
                }
            else:
                # json_object mode only guarantees syntactically valid JSON: describe the schema.
                hint = ChatMessage(
                    role="system",
                    content="Respond with a single JSON object that matches this JSON Schema exactly:\n"
                    + compact_schema_hint(response_model),
                )
                msgs.insert(1 if msgs and msgs[0]["role"] == "system" else 0, hint.to_dict())
                req["response_format"] = {"type": "json_object"}
        if tools:
            req["tools"] = [
                {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in tools
            ]
            req["tool_choice"] = "auto"
            req["parallel_tool_calls"] = False
        req["messages"] = msgs
        return req

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        purpose: str,
        response_model: type[BaseModel] | None = None,
        tools: list[ToolDefinition] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        req = self._request(messages, response_model, tools, temperature, max_tokens)
        tracer = get_tracer()
        model_params = {k: req[k] for k in ("temperature", "max_completion_tokens", "reasoning_effort") if k in req}
        with tracer.observation(
            f"groq:{purpose}", as_type="generation", input=req["messages"], model=self._model,
            model_parameters=model_params, metadata={"purpose": purpose, "structured": response_model is not None,
                                                     "tools": [t.name for t in tools or []]},
        ) as gen:
            started = time.perf_counter()
            try:
                async with self._semaphore:
                    completion = await self._client.chat.completions.create(**req)
            except groq.APITimeoutError as exc:
                gen.error(exc)
                raise LLMError(ErrorCode.LLM_TIMEOUT, f"Groq timed out after {self._settings.llm_timeout_seconds}s") from exc
            except groq.RateLimitError as exc:
                gen.error(exc)
                raise LLMError(ErrorCode.LLM_RATE_LIMITED, "Groq rate limit reached") from exc
            except groq.AuthenticationError as exc:
                gen.error(exc)
                raise LLMError(ErrorCode.LLM_NOT_CONFIGURED, "Groq rejected the API key") from exc
            except groq.BadRequestError as exc:
                gen.error(exc)
                body = str(getattr(exc, "body", "") or exc)
                if "json_validate_failed" in body or "tool_use_failed" in body:
                    raise LLMError(ErrorCode.LLM_INVALID_OUTPUT, "Model output failed schema validation",
                                   details={"provider_error": body[:500]}) from exc
                raise LLMError(ErrorCode.LLM_UNAVAILABLE, f"Groq rejected the request: {body[:300]}") from exc
            except (groq.APIConnectionError, groq.InternalServerError, groq.APIStatusError) as exc:
                gen.error(exc)
                raise LLMError(ErrorCode.LLM_UNAVAILABLE, f"Groq unavailable: {exc.__class__.__name__}") from exc
            latency_ms = int((time.perf_counter() - started) * 1000)

            choice = completion.choices[0]
            usage = LLMUsage(
                input_tokens=getattr(completion.usage, "prompt_tokens", 0) or 0,
                output_tokens=getattr(completion.usage, "completion_tokens", 0) or 0,
                latency_ms=latency_ms,
            )
            usage.estimated_cost_usd = estimate_cost_usd(self._model, usage.input_tokens, usage.output_tokens)
            tool_calls = [
                ToolCall(id=tc.id, name=tc.function.name, arguments_json=tc.function.arguments or "{}")
                for tc in (choice.message.tool_calls or [])
            ]
            gen.update(
                output=choice.message.content if not tool_calls else [tc.__dict__ for tc in tool_calls],
                usage_details={"input": usage.input_tokens, "output": usage.output_tokens},
                cost_details={"total": usage.estimated_cost_usd} if usage.estimated_cost_usd else None,
                metadata={"finish_reason": choice.finish_reason, "latency_ms": latency_ms},
            )
        return LLMResponse(
            content=choice.message.content,
            model=getattr(completion, "model", self._model) or self._model,
            usage=usage,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason,
        )
