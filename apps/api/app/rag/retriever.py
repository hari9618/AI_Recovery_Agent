"""Hybrid retriever: BM25 ∥ pgvector → RRF → cross-encoder rerank → top-k evidence.

Only knowledge documents go through here (playbooks, policies, SOPs). Transactional data — deals,
quotes, timestamps — is always read from PostgreSQL directly.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db import models as m
from app.domain.enums import DocumentStatus, DocumentType
from app.observability.tracing import get_tracer
from app.rag.bm25 import BM25Index
from app.rag.fusion import reciprocal_rank_fusion
from app.rag.models import Embedder, Reranker


@dataclass
class Evidence:
    evidence_id: str  # short, prompt-friendly id: E1, E2, ...
    chunk_id: str
    document_id: str
    document_title: str
    document_type: str
    section: str
    version: str
    content: str
    flagged_injection: bool
    scores: dict[str, float | int | None]

    @property
    def retrieval_score(self) -> float:
        return float(self.scores.get("rerank") or self.scores.get("rrf") or 0.0)

    def as_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "retrieval_score": round(self.retrieval_score, 4)}


@dataclass
class RetrievalResult:
    query: str
    evidence: list[Evidence]
    sufficient: bool
    timings_ms: dict[str, int] = field(default_factory=dict)
    candidates: dict[str, int] = field(default_factory=dict)
    reranker: str | None = None

    @property
    def status(self) -> str:
        return "OK" if self.sufficient else "INSUFFICIENT_EVIDENCE"

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "status": self.status,
            "evidence": [e.as_dict() for e in self.evidence],
            "timings_ms": self.timings_ms,
            "candidates": self.candidates,
            "reranker": self.reranker,
        }


class _BM25Cache:
    """Per-tenant BM25 index, rebuilt when the tenant's corpus changes (chunk count / latest update)."""

    def __init__(self) -> None:
        self._entries: dict[uuid.UUID, tuple[tuple[Any, ...], BM25Index, dict[str, m.DocumentChunk]]] = {}
        self._lock = asyncio.Lock()

    async def get(self, session: AsyncSession, company_id: uuid.UUID) -> tuple[BM25Index, dict[str, Any]]:
        version = tuple(
            (
                await session.execute(
                    select(func.count(m.DocumentChunk.id), func.max(m.Document.updated_at))
                    .select_from(m.DocumentChunk)
                    .join(m.Document, m.Document.id == m.DocumentChunk.document_id)
                    .where(m.DocumentChunk.company_id == company_id, m.Document.is_active.is_(True))
                )
            ).one()
        )
        cached = self._entries.get(company_id)
        if cached and cached[0] == version:
            return cached[1], cached[2]
        async with self._lock:
            rows = (
                await session.execute(
                    select(m.DocumentChunk.id, m.DocumentChunk.content, m.DocumentChunk.document_type)
                    .join(m.Document, m.Document.id == m.DocumentChunk.document_id)
                    .where(
                        m.DocumentChunk.company_id == company_id,
                        m.Document.is_active.is_(True),
                        m.Document.status == DocumentStatus.INDEXED,
                    )
                )
            ).all()
            meta = {str(r.id): {"document_type": r.document_type} for r in rows}
            index = BM25Index.build({str(r.id): r.content for r in rows})
            self._entries[company_id] = (version, index, meta)
            return index, meta

    def clear(self) -> None:
        self._entries.clear()


BM25_CACHE = _BM25Cache()


class HybridRetriever:
    def __init__(self, embedder: Embedder, reranker: Reranker | None) -> None:
        self.embedder = embedder
        self.reranker = reranker
        self.settings = get_settings()

    async def _vector_search(
        self,
        session: AsyncSession,
        company_id: uuid.UUID,
        query_vec: list[float],
        doc_types: list[DocumentType] | None,
        k: int,
    ) -> list[str]:
        distance = m.DocumentChunk.embedding.cosine_distance(query_vec)
        q = (
            select(m.DocumentChunk.id)
            .join(m.Document, m.Document.id == m.DocumentChunk.document_id)
            .where(
                m.DocumentChunk.company_id == company_id,
                m.Document.is_active.is_(True),
                m.Document.status == DocumentStatus.INDEXED,
            )
            .order_by(distance)
            .limit(k)
        )
        if doc_types:
            q = q.where(m.DocumentChunk.document_type.in_(doc_types))
        return [str(x) for x in (await session.scalars(q)).all()]

    async def search(
        self,
        session: AsyncSession,
        *,
        company_id: uuid.UUID,
        query: str,
        doc_types: list[DocumentType] | None = None,
        top_k: int | None = None,
    ) -> RetrievalResult:
        s = self.settings
        top_k = top_k or s.rag_top_k
        k = s.rag_candidate_k
        tracer = get_tracer()
        timings: dict[str, int] = {}
        with tracer.observation(
            "hybrid_retrieval",
            as_type="retriever",
            input={"query": query, "doc_types": [d.value for d in doc_types or []]},
        ) as root:
            t0 = time.perf_counter()

            async def lexical() -> list[str]:
                with tracer.observation("bm25", as_type="retriever", input={"query": query}) as span:
                    start = time.perf_counter()
                    index, meta = await BM25_CACHE.get(session, company_id)
                    allowed = (
                        {cid for cid, md in meta.items() if md["document_type"] in doc_types} if doc_types else None
                    )
                    hits = index.search(query, k, allowed)
                    timings["bm25"] = int((time.perf_counter() - start) * 1000)
                    span.update(output={"hits": len(hits), "top": hits[:3]})
                    return [h[0] for h in hits]

            async def dense(embedding: asyncio.Task[list[float]]) -> list[str]:
                with tracer.observation("vector", as_type="retriever", input={"query": query}) as span:
                    start = time.perf_counter()
                    qvec = await embedding
                    ids = await self._vector_search(session, company_id, qvec, doc_types, k)
                    timings["vector"] = int((time.perf_counter() - start) * 1000)
                    span.update(output={"hits": len(ids)})
                    return ids

            # Parallelism: query embedding (the slow, CPU-bound step) runs on a worker thread while BM25
            # scores in the event loop. The SQL calls stay sequential because one AsyncSession cannot run
            # concurrent queries.
            embedding_task = asyncio.create_task(self.embedder.aembed_query(query))
            bm25_ids = await lexical()
            vector_ids = await dense(embedding_task)
            fused = reciprocal_rank_fusion({"bm25": bm25_ids, "vector": vector_ids}, k=s.rag_rrf_k)[:k]
            timings["fusion"] = (
                int((time.perf_counter() - t0) * 1000) - timings.get("bm25", 0) - timings.get("vector", 0)
            )
            if not fused:
                root.update(output={"status": "INSUFFICIENT_EVIDENCE", "reason": "no candidates"})
                return RetrievalResult(query, [], False, timings, {"bm25": 0, "vector": 0, "fused": 0})

            ids = [uuid.UUID(f[0]) for f in fused]
            rows = (
                await session.execute(
                    select(m.DocumentChunk, m.Document.title, m.Document.version)
                    .join(m.Document, m.Document.id == m.DocumentChunk.document_id)
                    .where(m.DocumentChunk.id.in_(ids))
                )
            ).all()
            by_id = {str(r[0].id): r for r in rows}
            candidates = [(f, by_id[f[0]]) for f in fused if f[0] in by_id]

            rerank_scores: list[float | None] = [None] * len(candidates)
            if self.reranker is not None:
                with tracer.observation(
                    "rerank",
                    as_type="span",
                    input={"candidates": len(candidates)},
                    metadata={"model": self.reranker.name},
                ) as span:
                    start = time.perf_counter()
                    rerank_scores = list(await self.reranker.ascore(query, [c[1][0].content for c in candidates]))
                    timings["rerank"] = int((time.perf_counter() - start) * 1000)
                    span.update(output={"max": max(rerank_scores, default=0)})
                order = sorted(range(len(candidates)), key=lambda i: -(rerank_scores[i] or 0))
            else:
                order = list(range(len(candidates)))

            evidence: list[Evidence] = []
            for i in order[:top_k]:
                (doc_id, rrf, ranks), (chunk, title, version) = candidates[i]
                evidence.append(
                    Evidence(
                        evidence_id=f"E{len(evidence) + 1}",
                        chunk_id=doc_id,
                        document_id=str(chunk.document_id),
                        document_title=title,
                        document_type=chunk.document_type.value,
                        section=chunk.section,
                        version=version,
                        content=chunk.content,
                        flagged_injection=chunk.flagged_injection,
                        scores={
                            "rrf": round(rrf, 5),
                            "bm25_rank": ranks.get("bm25"),
                            "vector_rank": ranks.get("vector"),
                            "rerank": round(rerank_scores[i], 4) if rerank_scores[i] is not None else None,
                        },
                    )
                )
            if self.reranker is not None:
                evidence = [e for e in evidence if (e.scores["rerank"] or 0) >= s.rag_min_relevance]
                for n, e in enumerate(evidence, start=1):
                    e.evidence_id = f"E{n}"
            sufficient = bool(evidence)
            timings["total"] = int((time.perf_counter() - t0) * 1000)
            result = RetrievalResult(
                query,
                evidence,
                sufficient,
                timings,
                {"bm25": len(bm25_ids), "vector": len(vector_ids), "fused": len(fused)},
                self.reranker.name if self.reranker else None,
            )
            root.update(
                output={
                    "status": result.status,
                    "evidence": [
                        {"id": e.evidence_id, "doc": e.document_title, "section": e.section, "score": e.retrieval_score}
                        for e in evidence
                    ],
                    "timings_ms": timings,
                }
            )
            return result
