"""LLM test doubles for unit/integration tests and the *offline* evaluation mode.

Never wired into the running application: the API resolves providers through `app.llm.factory`, and the
only way a double is used is an explicit `set_llm_override` (tests) or the offline eval runner, whose
results are labelled `offline` everywhere they are shown.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from app.llm.base import ChatMessage, LLMProvider, LLMResponse, LLMUsage, ToolCall, ToolDefinition

Reply = str | dict | BaseModel | Exception | list[ToolCall] | Callable[[list[ChatMessage]], Any]


class ScriptedLLM(LLMProvider):
    """Returns queued replies in order and records every request it receives."""

    name = "scripted"

    def __init__(self, replies: list[Reply] | None = None, *, by_purpose: dict[str, list[Reply]] | None = None) -> None:
        self._queue: deque[Reply] = deque(replies or [])
        self._by_purpose = {k: deque(v) for k, v in (by_purpose or {}).items()}
        self.calls: list[dict[str, Any]] = []

    @property
    def model(self) -> str:
        return "scripted-test-model"

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
        self.calls.append(
            {
                "purpose": purpose,
                "messages": messages,
                "response_model": response_model,
                "tools": [t.name for t in tools or []],
            }
        )
        queue = self._by_purpose.get(purpose) or self._queue
        if not queue:
            raise AssertionError(f"ScriptedLLM has no reply queued for purpose={purpose!r}")
        reply = queue.popleft()
        if callable(reply) and not isinstance(reply, (type, BaseModel)):
            reply = reply(messages)
        if isinstance(reply, Exception):
            raise reply
        usage = LLMUsage(input_tokens=100, output_tokens=50, latency_ms=5)
        if isinstance(reply, list):
            return LLMResponse(
                content=None, model=self.model, usage=usage, tool_calls=reply, finish_reason="tool_calls"
            )
        if isinstance(reply, BaseModel):
            reply = reply.model_dump_json()
        elif isinstance(reply, dict):
            reply = json.dumps(reply)
        return LLMResponse(content=reply, model=self.model, usage=usage, finish_reason="stop")
