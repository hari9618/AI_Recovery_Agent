"""RAG evaluation.

offline (no LLM needed, deterministic):
  retrieval_hit_rate@k      an expected (document, section) appears in the retrieved evidence
  retrieval_mrr             mean reciprocal rank of the first expected passage
  insufficient_evidence_accuracy  unanswerable questions return INSUFFICIENT_EVIDENCE at retrieval
  injection_withholding     poisoned passages, when retrieved, are withheld from the LLM context

live (Groq answers + Ragas judge):
  ragas: faithfulness, answer_relevancy, context_precision, context_recall (reference-based)
  custom: policy_fact_accuracy, citation_accuracy, grounding_score, insufficient_evidence_accuracy,
          injection_resistance
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from app.db.session import get_sessionmaker
from app.llm.base import LLMProvider
from app.rag.grounding import answer_with_citations
from app.rag.retriever import HybridRetriever

logger = logging.getLogger(__name__)


def load_questions(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _hit_rank(evidence: list[dict[str, Any]], expected: list[list[str]]) -> int | None:
    targets = {(d.lower(), s.lower()) for d, s in expected}
    for rank, e in enumerate(evidence, start=1):
        if (e["document_title"].lower(), e["section"].lower()) in targets:
            return rank
    return None


def _facts_ok(answer: str, groups: list[list[str]]) -> bool:
    text = answer.lower().replace("₹", "")
    return all(any(alt.lower().replace("₹", "") in text for alt in group) for group in groups)


async def run_offline_case(q: dict[str, Any], retriever: HybridRetriever, company_id: uuid.UUID) -> dict[str, Any]:
    started = time.perf_counter()
    async with get_sessionmaker()() as s:
        res = await retriever.search(s, company_id=company_id, query=q["question"])
        grounded = await answer_with_citations(s, retriever=retriever, provider=None, company_id=company_id,
                                               question=q["question"], retrieval=res)
    evidence = [e.as_dict() for e in res.evidence]
    scores: dict[str, Any] = {}
    if q["expect"] == "answered":
        rank = _hit_rank(evidence, q["expected_sources"])
        scores["retrieval_hit_rate"] = rank is not None
        scores["retrieval_mrr"] = round(1 / rank, 4) if rank else 0.0
    if q["expect"] == "insufficient":
        scores["insufficient_evidence_accuracy"] = not res.sufficient
    if "injection" in q["tags"]:
        poisoned = [e for e in res.evidence if e.flagged_injection]
        scores["injection_withholding"] = all(
            any(w["evidence_id"] == p.evidence_id for w in grounded.withheld_evidence) for p in poisoned)
    passed = all(v is True or (isinstance(v, float) and v > 0) for v in scores.values())
    return {"case_key": q["key"], "description": q["question"], "tags": q["tags"], "passed": passed, "scores": scores,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "output": {"status": res.status, "top": [(e["document_title"], e["section"], e["retrieval_score"]) for e in evidence[:3]]},
            "expected": {"expect": q["expect"], "sources": q["expected_sources"]}}


async def run_live_case(q: dict[str, Any], retriever: HybridRetriever, company_id: uuid.UUID, provider: LLMProvider,
                        ragas_metrics: dict[str, Any] | None) -> dict[str, Any]:
    started = time.perf_counter()
    async with get_sessionmaker()() as s:
        ans = await answer_with_citations(s, retriever=retriever, provider=provider, company_id=company_id, question=q["question"])
    scores: dict[str, Any] = {}
    answered = ans.status in ("ANSWERED", "PARTIALLY_SUPPORTED")
    if q["expect"] == "answered":
        scores["answered_rate"] = answered
        scores["policy_fact_accuracy"] = answered and _facts_ok(ans.answer, q["required_facts"])
        expected_docs = {d.lower() for d, _ in q["expected_sources"]}
        supported = [c for c in ans.claims if c.supported]
        scores["citation_accuracy"] = (sum(1 for c in supported if (c.source_document or "").lower() in expected_docs) / len(supported)
                                       if supported else 0.0)
        scores["grounding_score"] = round(ans.grounding_score, 4)
    if q["expect"] == "insufficient":
        scores["insufficient_evidence_accuracy"] = ans.status == "INSUFFICIENT_EVIDENCE"
    if q.get("forbidden_facts"):
        text = (ans.answer + " " + " ".join(c.claim for c in ans.claims)).lower()
        scores["injection_resistance"] = not any(f.lower() in text for f in q["forbidden_facts"])

    if ragas_metrics and answered and q.get("reference"):
        contexts = [e.content for e in ans.evidence]
        for name, metric in ragas_metrics.items():
            try:
                if name == "faithfulness":
                    r = await metric.ascore(user_input=q["question"], response=ans.answer, retrieved_contexts=contexts)
                elif name == "answer_relevancy":
                    r = await metric.ascore(user_input=q["question"], response=ans.answer)
                elif name == "context_precision":
                    r = await metric.ascore(user_input=q["question"], reference=q["reference"], retrieved_contexts=contexts)
                else:  # context_recall
                    r = await metric.ascore(user_input=q["question"], retrieved_contexts=contexts, reference=q["reference"])
                scores[f"ragas_{name}"] = round(float(r.value), 4)
            except Exception as exc:  # noqa: BLE001 - a judge failure must not abort the suite; it is recorded
                logger.warning("ragas metric failed", extra={"metric": name, "error": str(exc)[:200]})
                scores[f"ragas_{name}_error"] = str(exc)[:200]
    binary = [v for k, v in scores.items() if isinstance(v, bool)]
    return {"case_key": q["key"], "description": q["question"], "tags": q["tags"], "passed": all(binary) if binary else None,
            "scores": scores, "latency_ms": int((time.perf_counter() - started) * 1000),
            "output": {"status": ans.status, "answer": ans.answer, "claims": [c.as_dict() for c in ans.claims],
                       "withheld": ans.withheld_evidence, "limitations": ans.limitations},
            "expected": {"expect": q["expect"], "reference": q.get("reference"), "required_facts": q.get("required_facts")}}


def build_ragas_metrics() -> dict[str, Any]:
    """Ragas judge = the configured Groq model via its OpenAI-compatible endpoint; embeddings = local fastembed."""
    from openai import AsyncOpenAI  # noqa: PLC0415
    from ragas.embeddings import BaseRagasEmbedding  # noqa: PLC0415
    from ragas.llms import llm_factory  # noqa: PLC0415
    from ragas.metrics.collections import AnswerRelevancy, ContextPrecision, ContextRecall, Faithfulness  # noqa: PLC0415

    from app.core.config import get_settings  # noqa: PLC0415
    from app.rag.models import get_embedder  # noqa: PLC0415

    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.groq_api_key.get_secret_value(), base_url=settings.groq_base_url or "https://api.groq.com/openai/v1")
    llm = llm_factory(settings.groq_model, provider="openai", client=client, max_tokens=4096)
    embedder = get_embedder()

    class FastEmbedRagas(BaseRagasEmbedding):
        def embed_text(self, text: str, **kwargs: Any) -> list[float]:
            return embedder.embed_query(text)

        async def aembed_text(self, text: str, **kwargs: Any) -> list[float]:
            return await embedder.aembed_query(text)

    return {
        "faithfulness": Faithfulness(llm=llm),
        "answer_relevancy": AnswerRelevancy(llm=llm, embeddings=FastEmbedRagas()),
        "context_precision": ContextPrecision(llm=llm),
        "context_recall": ContextRecall(llm=llm),
    }


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    names = sorted({k for r in results for k, v in r["scores"].items() if isinstance(v, (bool, int, float))})
    for name in names:
        vals = [float(r["scores"][name]) for r in results if isinstance(r["scores"].get(name), (bool, int, float))]
        if vals:
            metrics[name] = {"value": round(sum(vals) / len(vals), 4), "n": len(vals)}
    return metrics
