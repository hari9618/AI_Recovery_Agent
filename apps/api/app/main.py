"""FastAPI application factory."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import agent, audit, crm, dashboard, data, evaluations, knowledge, system
from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.logging import configure_logging
from app.db.session import get_engine
from app.observability.tracing import get_tracer

logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info("api starting", extra={"env": settings.environment, "llm_configured": settings.llm_configured,
                                       "langfuse": settings.langfuse_configured})
    yield
    get_tracer().flush()
    await get_engine().dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="AI Revenue Recovery Agent API",
        version="0.1.0",
        description="Finds, explains, prioritises and helps recover at-risk revenue. All AI output is grounded, "
                    "policy-checked and, for risky actions, human-approved.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        response.headers["x-content-type-options"] = "nosniff"
        logger.info("request", extra={"method": request.method, "path": request.url.path, "status": response.status_code,
                                      "ms": int((time.perf_counter() - started) * 1000), "request_id": request_id})
        return response

    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content={"error": exc.to_payload().model_dump(mode="json")})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"loc": ".".join(map(str, e["loc"])), "msg": e["msg"]} for e in exc.errors()[:10]]
        err = AppError(ErrorCode.INVALID_REQUEST, "Request validation failed", details={"errors": details})
        return JSONResponse(status_code=422, content={"error": err.to_payload().model_dump(mode="json")})

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error")
        err = AppError(ErrorCode.INTERNAL, "Internal server error")  # never leak internals to clients
        return JSONResponse(status_code=500, content={"error": err.to_payload().model_dump(mode="json")})

    for module in (system, dashboard, crm, agent, knowledge, data, audit, evaluations):
        app.include_router(module.router, prefix=settings.api_prefix)
    return app


app = create_app()
