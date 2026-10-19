"""Provider-agnostic LLM interface.

Every LLM call in the application goes through `LLMProvider.complete`. Provider modules translate
to/from vendor SDKs; nothing else imports a vendor SDK.
"""

from __future__ import annotations

import abc
import json
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments_json: str

    def arguments(self) -> dict[str, Any]:
        """Parsed arguments; raises ValueError on invalid JSON (callers validate with Pydantic)."""
        parsed = json.loads(self.arguments_json or "{}")
        if not isinstance(parsed, dict):
            raise ValueError("tool arguments must be a JSON object")
        return parsed


@dataclass
class ChatMessage:
    role: Role
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            out["tool_calls"] = [
                {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": tc.arguments_json}}
                for tc in self.tool_calls
            ]
        if self.tool_call_id:
            out["tool_call_id"] = self.tool_call_id
        if self.name and self.role == "tool":
            out["name"] = self.name
        return out


@dataclass(frozen=True)
class ToolDefinition:
    """What the model sees about a tool. `parameters` is a JSON Schema object."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    estimated_cost_usd: float = 0.0

    def add(self, other: LLMUsage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.latency_ms += other.latency_ms
        self.estimated_cost_usd += other.estimated_cost_usd


@dataclass
class LLMResponse:
    content: str | None
    model: str
    usage: LLMUsage
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None


class LLMProvider(abc.ABC):
    """Abstract chat-completion provider."""

    name: str = "abstract"

    @property
    @abc.abstractmethod
    def model(self) -> str: ...

    @abc.abstractmethod
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
        """One model call.

        `response_model` requests JSON output matching that schema (provider decides strict vs
        json-object mode). `tools` enables tool calling. Raises `LLMError` with an LLM_* code.
        """
