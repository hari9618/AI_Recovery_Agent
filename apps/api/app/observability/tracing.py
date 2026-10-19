"""Tracing facade over Langfuse (v3+ OpenTelemetry-based SDK).

Design rule: observability is secondary to correctness. Every call into Langfuse is wrapped so that a
missing configuration, network failure or SDK error degrades to a no-op handle — the business
workflow never sees an exception from here.

Usage::

    with tracer.trace("RevenueRecovery", user_id=..., session_id=..., input=...) as root:
        with tracer.observation("conversation_analysis", as_type="chain") as span:
            ...
            span.update(output=...)
        root.update(output=...)
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator
from functools import lru_cache
from typing import Any, Literal

from app.core.config import get_settings

logger = logging.getLogger(__name__)

ObservationType = Literal[
    "span", "generation", "agent", "tool", "chain", "retriever", "evaluator", "guardrail", "embedding"
]


class ObservationHandle:
    """Safe wrapper around a Langfuse observation; all methods swallow SDK errors."""

    def __init__(self, inner: Any | None = None) -> None:
        self._inner = inner

    @property
    def active(self) -> bool:
        return self._inner is not None

    @property
    def trace_id(self) -> str | None:
        return getattr(self._inner, "trace_id", None) if self._inner else None

    @property
    def id(self) -> str | None:
        return getattr(self._inner, "id", None) if self._inner else None

    def update(self, **kwargs: Any) -> None:
        if self._inner is None:
            return
        try:
            self._inner.update(**{k: v for k, v in kwargs.items() if v is not None})
        except Exception:  # noqa: BLE001 - observability must never raise
            logger.debug("langfuse update failed", exc_info=True)

    def error(self, exc: BaseException | str) -> None:
        self.update(level="ERROR", status_message=str(exc)[:500])

    def score(self, name: str, value: float | str, comment: str | None = None) -> None:
        if self._inner is None:
            return
        try:
            self._inner.score(name=name, value=value, comment=comment)
        except Exception:  # noqa: BLE001
            logger.debug("langfuse score failed", exc_info=True)


NULL_HANDLE = ObservationHandle(None)


class Tracer:
    def __init__(self, client: Any | None) -> None:
        self._client = client

    @property
    def enabled(self) -> bool:
        return self._client is not None

    @contextlib.contextmanager
    def observation(
        self,
        name: str,
        *,
        as_type: ObservationType = "span",
        input: Any = None,  # noqa: A002
        metadata: dict[str, Any] | None = None,
        model: str | None = None,
        model_parameters: dict[str, Any] | None = None,
    ) -> Iterator[ObservationHandle]:
        if self._client is None:
            yield NULL_HANDLE
            return
        stack = contextlib.ExitStack()
        try:
            kwargs: dict[str, Any] = {"name": name, "as_type": as_type, "input": input, "metadata": metadata}
            if as_type in ("generation", "embedding"):
                kwargs.update(model=model, model_parameters=model_parameters)
            inner = stack.enter_context(
                self._client.start_as_current_observation(**{k: v for k, v in kwargs.items() if v is not None})
            )
            handle = ObservationHandle(inner)
        except Exception:  # noqa: BLE001
            logger.debug("langfuse start_observation failed", exc_info=True)
            stack.close()
            yield NULL_HANDLE
            return
        try:
            yield handle
        except BaseException as exc:
            handle.error(exc)
            raise
        finally:
            try:
                stack.close()
            except Exception:  # noqa: BLE001
                logger.debug("langfuse end_observation failed", exc_info=True)

    @contextlib.contextmanager
    def trace(
        self,
        name: str,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        input: Any = None,  # noqa: A002
    ) -> Iterator[ObservationHandle]:
        """Root observation with trace-level attributes propagated to all children."""
        if self._client is None:
            yield NULL_HANDLE
            return
        stack = contextlib.ExitStack()
        try:
            from langfuse import propagate_attributes  # noqa: PLC0415

            stack.enter_context(
                propagate_attributes(
                    trace_name=name,
                    user_id=user_id,
                    session_id=session_id,
                    tags=tags,
                    metadata={k: str(v)[:200] for k, v in (metadata or {}).items()},
                )
            )
        except Exception:  # noqa: BLE001
            logger.debug("langfuse propagate_attributes failed", exc_info=True)
        try:
            with self.observation(name, as_type="agent", input=input, metadata=metadata) as root:
                yield root
        finally:
            try:
                stack.close()
            except Exception:  # noqa: BLE001
                logger.debug("langfuse propagate close failed", exc_info=True)

    def trace_url(self, trace_id: str | None) -> str | None:
        if self._client is None or not trace_id:
            return None
        try:
            return self._client.get_trace_url(trace_id=trace_id)
        except Exception:  # noqa: BLE001
            return None

    def score_trace(self, trace_id: str | None, name: str, value: float | str, comment: str | None = None) -> None:
        if self._client is None or not trace_id:
            return
        try:
            self._client.create_score(trace_id=trace_id, name=name, value=value, comment=comment)
        except Exception:  # noqa: BLE001
            logger.debug("langfuse create_score failed", exc_info=True)

    def flush(self) -> None:
        if self._client is None:
            return
        try:
            self._client.flush()
        except Exception:  # noqa: BLE001
            logger.debug("langfuse flush failed", exc_info=True)

    def health(self) -> dict[str, Any]:
        """Used by the Observability page. Never raises."""
        if self._client is None:
            return {"enabled": False, "reachable": None, "reason": "LANGFUSE_PUBLIC_KEY / SECRET_KEY not set"}
        try:
            return {"enabled": True, "reachable": bool(self._client.auth_check())}
        except Exception as exc:  # noqa: BLE001
            return {"enabled": True, "reachable": False, "reason": str(exc)[:200]}


@lru_cache
def get_tracer() -> Tracer:
    settings = get_settings()
    if not settings.langfuse_configured:
        return Tracer(None)
    try:
        from langfuse import Langfuse  # noqa: PLC0415

        client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key.get_secret_value() if settings.langfuse_secret_key else None,
            host=settings.langfuse_host,
            environment=settings.langfuse_environment,
        )
        return Tracer(client)
    except Exception:  # noqa: BLE001
        logger.warning("Langfuse initialisation failed; tracing disabled", exc_info=True)
        return Tracer(None)
