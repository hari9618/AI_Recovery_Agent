"""A closed error contract shared by the API, the tools and the MCP server.

Every failure that crosses a boundary is projected to::

    {"code": ..., "category": ..., "message": ..., "retryable": bool, "remediation": ..., "details": {...}}

`retryable` is derived from the code (not chosen at the raise site) so callers — including
LLM agents deciding whether to call a tool again — get a consistent signal.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class ErrorCode(StrEnum):
    INVALID_REQUEST = "invalid_request"
    NOT_FOUND = "not_found"
    UNAUTHENTICATED = "unauthenticated"
    FORBIDDEN = "forbidden"
    CONFLICT = "conflict"
    VALIDATION_FAILED = "validation_failed"
    LLM_NOT_CONFIGURED = "llm_not_configured"
    LLM_TIMEOUT = "llm_timeout"
    LLM_UNAVAILABLE = "llm_unavailable"
    LLM_RATE_LIMITED = "llm_rate_limited"
    LLM_INVALID_OUTPUT = "llm_invalid_output"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    POLICY_BLOCKED = "policy_blocked"
    APPROVAL_REQUIRED = "approval_required"
    DATABASE_UNAVAILABLE = "database_unavailable"
    TOOL_FAILURE = "tool_failure"
    UNSUPPORTED_FILE = "unsupported_file"
    INTERNAL = "internal_error"


class ErrorCategory(StrEnum):
    INVALID_INPUT = "invalid_input"
    NOT_FOUND = "not_found"
    ACCESS = "access"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    GUARDRAIL = "guardrail"
    EXECUTION = "execution_failure"


_CATEGORY: dict[ErrorCode, ErrorCategory] = {
    ErrorCode.INVALID_REQUEST: ErrorCategory.INVALID_INPUT,
    ErrorCode.VALIDATION_FAILED: ErrorCategory.INVALID_INPUT,
    ErrorCode.UNSUPPORTED_FILE: ErrorCategory.INVALID_INPUT,
    ErrorCode.CONFLICT: ErrorCategory.INVALID_INPUT,
    ErrorCode.NOT_FOUND: ErrorCategory.NOT_FOUND,
    ErrorCode.UNAUTHENTICATED: ErrorCategory.ACCESS,
    ErrorCode.FORBIDDEN: ErrorCategory.ACCESS,
    ErrorCode.LLM_NOT_CONFIGURED: ErrorCategory.UNAVAILABLE,
    ErrorCode.LLM_UNAVAILABLE: ErrorCategory.UNAVAILABLE,
    ErrorCode.LLM_RATE_LIMITED: ErrorCategory.UNAVAILABLE,
    ErrorCode.DATABASE_UNAVAILABLE: ErrorCategory.UNAVAILABLE,
    ErrorCode.LLM_TIMEOUT: ErrorCategory.TIMEOUT,
    ErrorCode.INSUFFICIENT_EVIDENCE: ErrorCategory.GUARDRAIL,
    ErrorCode.POLICY_BLOCKED: ErrorCategory.GUARDRAIL,
    ErrorCode.APPROVAL_REQUIRED: ErrorCategory.GUARDRAIL,
    ErrorCode.LLM_INVALID_OUTPUT: ErrorCategory.EXECUTION,
    ErrorCode.TOOL_FAILURE: ErrorCategory.EXECUTION,
    ErrorCode.INTERNAL: ErrorCategory.EXECUTION,
}

RETRYABLE_CODES = frozenset(
    {
        ErrorCode.LLM_TIMEOUT,
        ErrorCode.LLM_UNAVAILABLE,
        ErrorCode.LLM_RATE_LIMITED,
        ErrorCode.LLM_INVALID_OUTPUT,
        ErrorCode.DATABASE_UNAVAILABLE,
    }
)

HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.INVALID_REQUEST: 400,
    ErrorCode.VALIDATION_FAILED: 422,
    ErrorCode.UNSUPPORTED_FILE: 415,
    ErrorCode.CONFLICT: 409,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.UNAUTHENTICATED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.LLM_NOT_CONFIGURED: 503,
    ErrorCode.LLM_UNAVAILABLE: 503,
    ErrorCode.LLM_RATE_LIMITED: 429,
    ErrorCode.DATABASE_UNAVAILABLE: 503,
    ErrorCode.LLM_TIMEOUT: 504,
    ErrorCode.INSUFFICIENT_EVIDENCE: 422,
    ErrorCode.POLICY_BLOCKED: 403,
    ErrorCode.APPROVAL_REQUIRED: 409,
    ErrorCode.LLM_INVALID_OUTPUT: 502,
    ErrorCode.TOOL_FAILURE: 500,
    ErrorCode.INTERNAL: 500,
}

_DEFAULT_REMEDIATION: dict[ErrorCode, str] = {
    ErrorCode.LLM_NOT_CONFIGURED: "Set GROQ_API_KEY and GROQ_MODEL in .env and restart the API.",
    ErrorCode.LLM_TIMEOUT: "Retry; if it persists, lower LLM_MAX_OUTPUT_TOKENS or pick a faster model.",
    ErrorCode.LLM_RATE_LIMITED: "Wait and retry; Groq rate limits reset per minute.",
    ErrorCode.DATABASE_UNAVAILABLE: "Check DATABASE_URL and that PostgreSQL is running.",
    ErrorCode.NOT_FOUND: "Check the identifier; it may belong to another company.",
    ErrorCode.INSUFFICIENT_EVIDENCE: "Add or update the relevant policy document in the Knowledge Base.",
    ErrorCode.APPROVAL_REQUIRED: "Approve or reject the request in the Approval Center.",
}


class ErrorPayload(BaseModel):
    code: ErrorCode
    category: ErrorCategory
    message: str
    retryable: bool
    remediation: str | None = None
    details: dict[str, Any] | None = None


class AppError(Exception):
    """Base class for every error that crosses a module boundary."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        remediation: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        self.remediation = remediation or _DEFAULT_REMEDIATION.get(code)

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE_CODES

    @property
    def http_status(self) -> int:
        return HTTP_STATUS.get(self.code, 500)

    def to_payload(self) -> ErrorPayload:
        return ErrorPayload(
            code=self.code,
            category=_CATEGORY.get(self.code, ErrorCategory.EXECUTION),
            message=self.message,
            retryable=self.retryable,
            remediation=self.remediation,
            details=self.details,
        )


class NotFoundError(AppError):
    def __init__(self, entity: str, entity_id: object) -> None:
        super().__init__(ErrorCode.NOT_FOUND, f"{entity} {entity_id} not found", details={"entity": entity})


class LLMError(AppError):
    """Raised by LLM providers. Always carries one of the LLM_* codes."""
