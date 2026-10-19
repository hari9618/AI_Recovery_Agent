"""Demo-mode orchestration: synthetic CRM data + knowledge base + initial risk assessment."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import REPO_ROOT, get_settings
from app.demo.generator import generate_demo_dataset
from app.demo.loader import insert_demo_dataset
from app.domain.enums import ActorType
from app.domain.settings import CompanySettings
from app.rag.ingestion import ingest_directory
from app.rag.models import get_embedder
from app.rag.retriever import BM25_CACHE
from app.services.audit import record_audit
from app.services.risk_service import recompute_risks

logger = logging.getLogger(__name__)
KNOWLEDGE_DIR = REPO_ROOT / "data" / "knowledge"


async def load_demo(session: AsyncSession, *, seed: int | None = None) -> dict[str, Any]:
    """Replace the demo tenant with a fresh synthetic dataset. Returns counts and the demo company id.

    Nothing AI-generated is fabricated here: recommendations, analyses and evaluations only appear after
    the real pipelines run.
    """
    settings = get_settings()
    t0 = time.perf_counter()
    dataset = generate_demo_dataset(seed or settings.demo_seed, datetime.now(UTC), settings.demo_company_name)
    counts = await insert_demo_dataset(session, dataset)
    company_id = dataset.company["id"]
    docs = await ingest_directory(session, get_embedder(), company_id=company_id, directory=KNOWLEDGE_DIR)
    BM25_CACHE.clear()
    risks = await recompute_risks(session, company_id, CompanySettings())
    levels: dict[str, int] = {}
    for r in risks:
        levels[r.risk_level.value] = levels.get(r.risk_level.value, 0) + 1
    record_audit(
        session,
        company_id=company_id,
        action="demo.loaded",
        actor_type=ActorType.SYSTEM,
        output={"counts": counts, "documents": len(docs), "risk_levels": levels},
    )
    await session.commit()
    return {
        "company_id": str(company_id),
        "counts": counts,
        "documents_indexed": len(docs),
        "flagged_documents": [d.document.title for d in docs if d.injection_findings],
        "risk_levels": levels,
        "seconds": round(time.perf_counter() - t0, 1),
        "scenario": dataset.ground_truth.get("vertex"),
        "label": "synthetic_demo",
    }
