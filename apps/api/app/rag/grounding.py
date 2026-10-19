"""Grounded answering and citation validation.

The LLM drafts an answer as a list of claims, each citing evidence ids. We then verify every claim
deterministically:
  1. cited ids must exist in the retrieved set (no invented sources);
  2. the claim must be semantically supported by the cited text (embedding similarity ≥ threshold);
  3. every number in the claim (10%, ₹50,000, 30 days) must literally appear in the cited text.
Unsupported claims are reported, not silently kept. No supported claims → INSUFFICIENT_EVIDENCE.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domain.enums import DocumentType
from app.llm.base import LLMProvider, LLMUsage
from app.llm.structured import generate_structured
from app.observability.tracing import get_tracer
from app.prompts.grounded import LLMGroundedAnswer, build_messages
from app.rag.models import Embedder, cosine
from app.rag.retriever import Evidence, HybridRetriever, RetrievalResult

GroundedStatus = Literal["ANSWERED", "PARTIALLY_SUPPORTED", "INSUFFICIENT_EVIDENCE", "LLM_FALLBACK"]
_NUMBER = re.compile(r"₹?\d[\d,]*(?:\.\d+)?%?")


@dataclass
class VerifiedClaim:
    claim: str
    supported: bool
    evidence_id: str | None
    source_document: str | None
    source_section: str | None
    retrieval_score: float | None
    support_score: float
    problems: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__ | {"support_score": round(self.support_score, 4)}


@dataclass
class GroundedAnswer:
    question: str
    status: GroundedStatus
    answer: str
    claims: list[VerifiedClaim]
    evidence: list[Evidence]
    withheld_evidence: list[dict[str, str]]
    limitations: list[str]
    model: str | None = None
    usage: LLMUsage = field(default_factory=LLMUsage)
    retrieval: RetrievalResult | None = None

    @property
    def grounding_score(self) -> float:
        return sum(c.supported for c in self.claims) / len(self.claims) if self.claims else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "question": self.question, "status": self.status, "answer": self.answer,
            "claims": [c.as_dict() for c in self.claims], "grounding_score": round(self.grounding_score, 4),
            "evidence": [e.as_dict() for e in self.evidence], "withheld_evidence": self.withheld_evidence,
            "limitations": self.limitations, "model": self.model,
            "retrieval": self.retrieval.as_dict() if self.retrieval else None,
        }


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in _NUMBER.findall(text)}


def format_evidence(evidence: list[Evidence]) -> str:
    return "\n\n".join(
        f"[{e.evidence_id}] {e.document_title} (v{e.version}) — section: {e.section}\n{e.content}" for e in evidence
    )


async def verify_claims(embedder: Embedder, claims: list[tuple[str, list[str]]], evidence: list[Evidence],
                        min_support: float, trusted_context: str = "") -> list[VerifiedClaim]:
    """`trusted_context` (CRM facts) may supply numbers such as the deal value; policy numbers must be cited."""
    by_id = {e.evidence_id: e for e in evidence}
    texts = [c for c, _ in claims] + [e.content for e in evidence]
    vectors = await embedder.aembed_documents(texts) if texts else []
    claim_vecs, ev_vecs = vectors[: len(claims)], dict(zip([e.evidence_id for e in evidence], vectors[len(claims):], strict=True))
    out: list[VerifiedClaim] = []
    for (claim, ids), cvec in zip(claims, claim_vecs, strict=True):
        problems: list[str] = []
        valid = [i for i in dict.fromkeys(ids) if i in by_id]
        if len(valid) < len(set(ids)):
            problems.append(f"cites unknown evidence {sorted(set(ids) - set(valid))}")
        if not valid:
            problems.append("no valid citation")
            out.append(VerifiedClaim(claim, False, None, None, None, None, 0.0, problems))
            continue
        best = max(valid, key=lambda i: cosine(cvec, ev_vecs[i]))
        support = cosine(cvec, ev_vecs[best])
        cited_text = (" ".join(by_id[i].content for i in valid) + " " + trusted_context).replace(",", "")
        missing_numbers = {n for n in _numbers(claim) if n not in cited_text}
        if missing_numbers:
            problems.append(f"numbers not found in cited evidence: {sorted(missing_numbers)}")
        if support < min_support:
            problems.append(f"low semantic support ({support:.2f} < {min_support})")
        ev = by_id[best]
        out.append(VerifiedClaim(claim, not problems, ev.evidence_id, ev.document_title, ev.section,
                                 round(ev.retrieval_score, 4), support, problems))
    return out


async def answer_with_citations(
    session: AsyncSession,
    *,
    retriever: HybridRetriever,
    provider: LLMProvider | None,
    company_id: uuid.UUID,
    question: str,
    doc_types: list[DocumentType] | None = None,
    business_context: str | None = None,
    retrieval: RetrievalResult | None = None,
) -> GroundedAnswer:
    settings = get_settings()
    retrieval = retrieval or await retriever.search(session, company_id=company_id, query=question, doc_types=doc_types)
    usable = [e for e in retrieval.evidence if not (settings.rag_exclude_flagged_from_llm and e.flagged_injection)]
    withheld = [{"evidence_id": e.evidence_id, "document": e.document_title, "section": e.section,
                 "reason": "contains instruction-like text (possible prompt injection)"}
                for e in retrieval.evidence if e not in usable]
    limitations = [f"{len(withheld)} passage(s) withheld from the model: possible prompt injection"] if withheld else []

    if not usable:
        return GroundedAnswer(question, "INSUFFICIENT_EVIDENCE", "", [], [], withheld,
                              limitations + ["No knowledge passage was relevant enough to answer."], retrieval=retrieval)
    if provider is None:
        return GroundedAnswer(question, "LLM_FALLBACK", "", [], usable, withheld,
                              limitations + ["LLM not configured: showing retrieved evidence only."], retrieval=retrieval)

    with get_tracer().observation("grounded_answer", as_type="chain", input={"question": question}) as span:
        result = await generate_structured(provider, build_messages(question, format_evidence(usable), business_context),
                                           LLMGroundedAnswer, purpose="grounded_answer", temperature=0.0)
        if not result.ok or result.value is None:
            span.update(output={"status": "LLM_FALLBACK"}, level="WARNING")
            return GroundedAnswer(question, "LLM_FALLBACK", "", [], usable, withheld,
                                  limitations + ["The model's answer failed validation; showing evidence only."],
                                  result.model, result.usage, retrieval)
        draft = result.value
        if draft.injection_suspected:
            limitations.append("The model reported instruction-like text in the evidence and ignored it.")
        if draft.status == "insufficient_evidence" or not draft.claims:
            span.update(output={"status": "INSUFFICIENT_EVIDENCE"})
            return GroundedAnswer(question, "INSUFFICIENT_EVIDENCE", "", [], usable, withheld,
                                  limitations + ["The passages do not answer this question."], result.model, result.usage, retrieval)
        claims = await verify_claims(retriever.embedder, [(c.claim, c.evidence_ids) for c in draft.claims], usable,
                                     settings.rag_min_claim_support, business_context or "")
        supported = [c for c in claims if c.supported]
        status: GroundedStatus = (
            "INSUFFICIENT_EVIDENCE" if not supported else "ANSWERED" if len(supported) == len(claims) else "PARTIALLY_SUPPORTED"
        )
        if status == "PARTIALLY_SUPPORTED":
            limitations.append(f"{len(claims) - len(supported)} claim(s) could not be verified against the sources.")
        answer = draft.answer if status != "INSUFFICIENT_EVIDENCE" else ""
        span.update(output={"status": status, "claims": len(claims), "supported": len(supported)})
        span.score("grounding_score", len(supported) / len(claims))
        return GroundedAnswer(question, status, answer, claims, usable, withheld, limitations, result.model,
                              result.usage, retrieval)
