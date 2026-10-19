"""Integration fixtures: a real PostgreSQL (+pgvector) test database, migrated with Alembic, loaded once
with the synthetic demo tenant. LLM calls use scripted doubles; embeddings/reranking use the real
local models."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.errors import ErrorCode, LLMError
from app.db import models as m
from app.db.session import get_engine, get_sessionmaker
from app.domain.enums import UserRole
from app.llm.factory import set_llm_override
from app.main import create_app
from app.security.auth import hash_token
from app.services.demo import load_demo
from tests.fakes import ScriptedLLM

API_ROOT = Path(__file__).resolve().parents[2]
REP_TOKEN = "test-rep-token"
OTHER_TENANT_TOKEN = "test-other-tenant-token"


class UnavailableLLM(ScriptedLLM):
    """Default for integration tests: behaves like an unconfigured provider."""

    async def complete(self, *args, **kwargs):
        raise LLMError(ErrorCode.LLM_NOT_CONFIGURED, "LLM disabled in tests")


@pytest.fixture(autouse=True)
def _default_llm():
    set_llm_override(UnavailableLLM())
    yield
    set_llm_override(None)


@pytest.fixture(scope="session")
async def demo(request) -> dict:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    # Migrate with the real Alembic migration (also proves the migration applies cleanly).
    env = os.environ | {"DATABASE_URL": get_settings().database_url}
    subprocess.run(  # noqa: ASYNC221 - one-off migration during test setup
        [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=API_ROOT, env=env, check=True, capture_output=True
    )
    async with get_sessionmaker()() as s:
        info = await load_demo(s)
    company_id = uuid.UUID(info["company_id"])
    async with get_sessionmaker()() as s:
        rep = await s.scalar(select(m.User).where(m.User.company_id == company_id, m.User.role == UserRole.SALES_REP))
        rep.api_token_hash = hash_token(REP_TOKEN)
        other = m.Company(name="Other Tenant Ltd", industry="Retail", currency="INR", settings={}, is_demo=False)
        s.add(other)
        await s.flush()
        s.add(
            m.User(
                company_id=other.id,
                email="owner@othertenant.in",
                full_name="Other Owner",
                role=UserRole.OWNER,
                api_token_hash=hash_token(OTHER_TENANT_TOKEN),
            )
        )
        await s.commit()
    return info


def _client(token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()),
        base_url="http://test/api/v1",
        headers={"Authorization": f"Bearer {token}"},
        timeout=120,
    )


@pytest.fixture
async def owner(demo) -> httpx.AsyncClient:
    async with _client(get_settings().demo_api_token.get_secret_value()) as c:
        yield c


@pytest.fixture
async def rep(demo) -> httpx.AsyncClient:
    async with _client(REP_TOKEN) as c:
        yield c


@pytest.fixture
async def other_tenant(demo) -> httpx.AsyncClient:
    async with _client(OTHER_TENANT_TOKEN) as c:
        yield c


@pytest.fixture
async def anon(demo) -> httpx.AsyncClient:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://test/api/v1") as c:
        yield c
