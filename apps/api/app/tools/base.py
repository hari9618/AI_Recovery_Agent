"""Typed tool contracts, effect declarations and the invocation pipeline.

A tool is the only way an agent (or MCP client, or the copilot LLM) touches business data:

    validate input (Pydantic) → trace span → handler → validate output → audit → ToolResult envelope

Effects are declared once per tool; MCP annotations (readOnly / destructive / idempotent / openWorld)
are *derived* from them, never hand-written, so they cannot drift. Hints are not authorisation:
write tools additionally enforce tenant scope, and customer-facing tools require an approved
approval request id that the handler verifies in the database.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode, ErrorPayload
from app.domain.enums import ActorType, AuditResult
from app.observability.tracing import get_tracer
from app.services.audit import record_audit

logger = logging.getLogger(__name__)
I = TypeVar("I", bound=BaseModel)  # noqa: E741
O = TypeVar("O", bound=BaseModel)


@dataclass(frozen=True)
class Effects:
    writes_crm: bool = False
    customer_facing: bool = False
    financial: bool = False
    calls_llm: bool = False
    idempotent: bool = True

    @property
    def read_only(self) -> bool:
        return not (self.writes_crm or self.customer_facing or self.financial)

    def annotations(self) -> dict[str, bool]:
        return {
            "readOnlyHint": self.read_only,
            "destructiveHint": self.customer_facing or self.financial,
            "idempotentHint": self.idempotent,
            # LLM-calling and customer-facing tools reach outside the database.
            "openWorldHint": self.calls_llm or self.customer_facing,
        }


READ_ONLY = Effects()


class ToolDeps:
    """Lazily-resolved heavy dependencies; tests construct this with doubles."""

    def __init__(self, *, provider: Any = None, embedder: Any = None, reranker: Any = None, use_reranker: bool = True) -> None:
        self._provider, self._embedder, self._reranker, self._use_reranker = provider, embedder, reranker, use_reranker

    def llm(self):
        if self._provider is None:
            from app.llm.factory import get_llm_provider  # noqa: PLC0415

            self._provider = get_llm_provider()
        return self._provider

    def retriever(self):
        from app.rag.models import get_embedder, get_reranker  # noqa: PLC0415
        from app.rag.retriever import HybridRetriever  # noqa: PLC0415

        if self._embedder is None:
            self._embedder = get_embedder()
        if self._reranker is None and self._use_reranker:
            self._reranker = get_reranker()
        return HybridRetriever(self._embedder, self._reranker)


@dataclass
class ToolContext:
    session: AsyncSession
    company_id: uuid.UUID
    actor_type: ActorType = ActorType.AGENT
    actor_id: str | None = None
    actor_name: str | None = None
    agent: str | None = None
    agent_run_id: uuid.UUID | None = None
    deps: ToolDeps = field(default_factory=ToolDeps)
    audit_reads: bool = True


class ToolResult(BaseModel):
    ok: bool
    tool: str
    data: dict[str, Any] | None = None
    error: ErrorPayload | None = None
    provenance: dict[str, Any]
    limitations: list[str] = []
    latency_ms: int = 0


@dataclass
class Tool(Generic[I, O]):
    name: str
    title: str
    description: str
    input_model: type[I]
    output_model: type[O]
    handler: Callable[[ToolContext, I], Awaitable[O]]
    effects: Effects = READ_ONLY
    source: str = "postgres"
    untrusted_content: bool = False
    llm_exposed: bool = False
    mcp_name: str | None = None

    def llm_schema(self) -> dict[str, Any]:
        schema = self.input_model.model_json_schema()
        schema.pop("title", None)
        return schema


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool[Any, Any]] = {}

    def register(self, tool: Tool[Any, Any]) -> Tool[Any, Any]:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool {tool.name}")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool[Any, Any]:
        try:
            return self._tools[name]
        except KeyError:
            raise AppError(ErrorCode.INVALID_REQUEST, f"Unknown tool '{name}'") from None

    def all(self) -> list[Tool[Any, Any]]:
        return list(self._tools.values())

    def llm_tools(self) -> list[Tool[Any, Any]]:
        return [t for t in self._tools.values() if t.llm_exposed]

    def mcp_tools(self) -> list[Tool[Any, Any]]:
        return [t for t in self._tools.values() if t.mcp_name]

    async def invoke(self, name: str, args: dict[str, Any] | BaseModel, ctx: ToolContext) -> ToolResult:
        tool = self.get(name)
        provenance = {"source": tool.source, "untrusted_content": tool.untrusted_content, "effects": tool.effects.annotations()}
        started = time.perf_counter()
        raw_args = args.model_dump(mode="json") if isinstance(args, BaseModel) else dict(args or {})
        with get_tracer().observation(f"tool:{name}", as_type="tool", input=raw_args, metadata={"agent": ctx.agent}) as span:
            try:
                try:
                    parsed = args if isinstance(args, tool.input_model) else tool.input_model.model_validate(raw_args)
                except ValidationError as exc:
                    raise AppError(ErrorCode.INVALID_REQUEST, f"Invalid arguments for {name}: {_validation_summary(exc)}") from exc
                output = await tool.handler(ctx, parsed)
                if not isinstance(output, tool.output_model):
                    output = tool.output_model.model_validate(output)
                data = output.model_dump(mode="json")
                latency = int((time.perf_counter() - started) * 1000)
                limitations = data.pop("limitations", None) or []
                result = ToolResult(ok=True, tool=name, data=data, provenance=provenance, limitations=limitations, latency_ms=latency)
                span.update(output=_summarize(data))
                self._audit(ctx, tool, raw_args, data, AuditResult.SUCCESS, latency)
                return result
            except AppError as exc:
                err = exc
            except (OperationalError, DBAPIError) as exc:
                logger.exception("database error in tool", extra={"tool": name})
                err = AppError(ErrorCode.DATABASE_UNAVAILABLE, f"Database error in {name}: {exc.__class__.__name__}")
            except Exception as exc:  # noqa: BLE001 - tool boundary converts everything to the error contract
                logger.exception("tool failure", extra={"tool": name})
                err = AppError(ErrorCode.TOOL_FAILURE, f"{name} failed: {exc.__class__.__name__}")
            latency = int((time.perf_counter() - started) * 1000)
            span.error(err.message)
            result_kind = AuditResult.BLOCKED if err.code in (ErrorCode.POLICY_BLOCKED, ErrorCode.APPROVAL_REQUIRED, ErrorCode.FORBIDDEN) else AuditResult.FAILURE
            if err.code != ErrorCode.DATABASE_UNAVAILABLE:
                self._audit(ctx, tool, raw_args, err.to_payload().model_dump(mode="json"), result_kind, latency)
            return ToolResult(ok=False, tool=name, error=err.to_payload(), provenance=provenance, latency_ms=latency)

    def _audit(self, ctx: ToolContext, tool: Tool[Any, Any], args: dict[str, Any], output: dict[str, Any],
               result: AuditResult, latency: int) -> None:
        if tool.effects.read_only and not ctx.audit_reads and result == AuditResult.SUCCESS:
            return
        customer = args.get("customer_id") or output.get("customer_id")
        try:
            customer_uuid = uuid.UUID(str(customer)) if customer else None
        except ValueError:
            customer_uuid = None
        record_audit(
            ctx.session, company_id=ctx.company_id, action=f"tool.{tool.name}", actor_type=ctx.actor_type,
            actor_id=ctx.actor_id, actor_name=ctx.actor_name, agent=ctx.agent, tool=tool.name,
            entity_type=tool.name.split("_", 1)[-1], entity_id=args.get("opportunity_id") or args.get("recommendation_id"),
            customer_id=customer_uuid, input=args, output=_summarize(output), result=result,
            agent_run_id=ctx.agent_run_id, latency_ms=latency,
        )


def _validation_summary(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:5])


def _summarize(data: dict[str, Any], limit: int = 1500) -> dict[str, Any]:
    """Keep audit/trace payloads small: truncate long strings and lists."""
    def trim(v: Any) -> Any:
        if isinstance(v, str):
            return v if len(v) <= 300 else v[:300] + "…"
        if isinstance(v, list):
            return [trim(x) for x in v[:5]] + ([f"… {len(v) - 5} more"] if len(v) > 5 else [])
        if isinstance(v, dict):
            return {k: trim(x) for k, x in list(v.items())[:25]}
        return v
    return trim(data)


REGISTRY = ToolRegistry()
