"""Knowledge base: documents, upload, hybrid search and grounded Q&A."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import ManagerDep, PrincipalDep, SessionDep
from app.core.config import get_settings
from app.core.errors import AppError, LLMError, NotFoundError
from app.db import models as m
from app.domain.enums import ActorType, DocumentType
from app.llm.factory import get_llm_provider
from app.llm.ledger import llm_call_context
from app.rag.grounding import answer_with_citations
from app.rag.ingestion import ingest_document
from app.rag.models import get_embedder, get_reranker
from app.rag.retriever import BM25_CACHE, HybridRetriever
from app.services.audit import record_audit

router = APIRouter(tags=["knowledge"])


def _retriever() -> HybridRetriever:
    return HybridRetriever(get_embedder(), get_reranker())


@router.get("/knowledge/documents")
async def documents(principal: PrincipalDep, session: SessionDep) -> dict:
    docs = (await session.scalars(select(m.Document).where(m.Document.company_id == principal.company_id)
                                  .order_by(m.Document.document_type, m.Document.title))).all()
    return {"items": [{"id": str(d.id), "title": d.title, "document_type": d.document_type.value, "version": d.version,
                       "source": d.source, "mime_type": d.mime_type, "status": d.status.value, "chunk_count": d.chunk_count,
                       "char_count": d.char_count, "injection_findings": d.injection_findings, "is_active": d.is_active,
                       "created_at": d.created_at, "error": d.error} for d in docs],
            "totals": {"documents": len(docs), "chunks": sum(d.chunk_count for d in docs),
                       "flagged": sum(1 for d in docs if d.injection_findings)}}


@router.get("/knowledge/documents/{document_id}")
async def document(document_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> dict:
    d = await session.scalar(select(m.Document).where(m.Document.id == document_id, m.Document.company_id == principal.company_id))
    if d is None:
        raise NotFoundError("document", document_id)
    chunks = (await session.scalars(select(m.DocumentChunk).where(m.DocumentChunk.document_id == d.id).order_by(m.DocumentChunk.chunk_index))).all()
    return {"id": str(d.id), "title": d.title, "document_type": d.document_type.value, "version": d.version, "source": d.source,
            "injection_findings": d.injection_findings, "is_active": d.is_active,
            "chunks": [{"index": c.chunk_index, "section": c.section, "content": c.content, "flagged_injection": c.flagged_injection,
                        "char_count": c.char_count} for c in chunks]}


@router.post("/knowledge/documents")
async def upload(principal: ManagerDep, session: SessionDep, file: UploadFile = File(...),
                 document_type: DocumentType | None = Form(None), title: str | None = Form(None)) -> dict:
    limit = get_settings().upload_max_bytes
    data = await file.read(limit + 1)
    result = await ingest_document(session, get_embedder(), company_id=principal.company_id, filename=file.filename or "upload.txt",
                                   data=data, document_type=document_type, title=title, actor_id=str(principal.user_id))
    await session.commit()
    BM25_CACHE.clear()
    return {"id": str(result.document.id), "title": result.document.title, "duplicate": result.duplicate, "chunks": result.chunks,
            "injection_findings": result.injection_findings, "status": result.document.status.value}


@router.patch("/knowledge/documents/{document_id}")
async def set_active(document_id: uuid.UUID, principal: ManagerDep, session: SessionDep, is_active: bool) -> dict:
    d = await session.scalar(select(m.Document).where(m.Document.id == document_id, m.Document.company_id == principal.company_id))
    if d is None:
        raise NotFoundError("document", document_id)
    d.is_active = is_active
    record_audit(session, company_id=principal.company_id, action="knowledge.document_" + ("activated" if is_active else "deactivated"),
                 actor_type=ActorType.USER, actor_id=str(principal.user_id), actor_name=principal.name, entity_type="document", entity_id=d.id)
    await session.commit()
    BM25_CACHE.clear()
    return {"id": str(d.id), "is_active": d.is_active}


class SearchIn(BaseModel):
    query: str = Field(min_length=3, max_length=500)
    document_types: list[DocumentType] | None = None
    top_k: int = Field(5, ge=1, le=10)


@router.post("/knowledge/search")
async def search(body: SearchIn, principal: PrincipalDep, session: SessionDep) -> dict:
    res = await _retriever().search(session, company_id=principal.company_id, query=body.query, doc_types=body.document_types, top_k=body.top_k)
    return res.as_dict()


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    document_types: list[DocumentType] | None = None


@router.post("/knowledge/ask")
async def ask(body: AskIn, principal: PrincipalDep, session: SessionDep) -> dict:
    """Grounded answer with verified citations. Works without an LLM (returns evidence only, labelled)."""
    try:
        provider = get_llm_provider()
    except LLMError:
        provider = None
    with llm_call_context(company_id=principal.company_id):
        try:
            answer = await answer_with_citations(session, retriever=_retriever(), provider=provider, company_id=principal.company_id,
                                                 question=body.question, doc_types=body.document_types)
        except LLMError as exc:
            raise AppError(exc.code, exc.message) from exc
    return answer.as_dict()


@router.get("/knowledge/stats")
async def stats(principal: PrincipalDep, session: SessionDep) -> dict:
    rows = (await session.execute(select(m.DocumentChunk.document_type, func.count()).where(
        m.DocumentChunk.company_id == principal.company_id).group_by(m.DocumentChunk.document_type))).all()
    return {"chunks_by_type": {t.value: n for t, n in rows}}

