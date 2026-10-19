"""Knowledge-document ingestion: validate → extract → scan → chunk → embed → store.

Uploads are untrusted: file type is checked by extension *and* content signature, size is capped,
text is extracted without executing anything, and instruction-like content is flagged.
"""

from __future__ import annotations

import io
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.db import models as m
from app.domain.enums import ActorType, DocumentStatus, DocumentType
from app.rag.chunking import chunk_markdown, chunk_plain, parse_front_matter
from app.rag.models import Embedder
from app.security.injection import scan_for_injection
from app.services.audit import record_audit
from app.services.text import sha256_hex

logger = logging.getLogger(__name__)

ALLOWED = {".md": "text/markdown", ".markdown": "text/markdown", ".txt": "text/plain", ".pdf": "application/pdf"}


@dataclass
class IngestResult:
    document: m.Document
    duplicate: bool
    chunks: int
    injection_findings: list[dict[str, str]]


def _safe_filename(name: str) -> str:
    base = Path(name.replace("\\", "/")).name
    return "".join(c for c in base if c.isalnum() or c in "-_. ")[:200] or "upload"


def extract_text(filename: str, data: bytes) -> tuple[str, str]:
    """Return (text, mime). Raises AppError(UNSUPPORTED_FILE / VALIDATION_FAILED)."""
    settings = get_settings()
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED:
        raise AppError(ErrorCode.UNSUPPORTED_FILE, f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED))}")
    if len(data) > settings.upload_max_bytes:
        raise AppError(ErrorCode.VALIDATION_FAILED, f"File exceeds {settings.upload_max_bytes // (1024 * 1024)} MB limit")
    if not data.strip():
        raise AppError(ErrorCode.VALIDATION_FAILED, "File is empty")
    if ext == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise AppError(ErrorCode.UNSUPPORTED_FILE, "File has a .pdf extension but is not a PDF")
        try:
            from pypdf import PdfReader  # noqa: PLC0415

            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise AppError(ErrorCode.VALIDATION_FAILED, "Encrypted PDFs are not supported")
            text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
        except AppError:
            raise
        except Exception as exc:  # malformed PDF
            raise AppError(ErrorCode.VALIDATION_FAILED, f"Could not read PDF: {exc.__class__.__name__}") from exc
        if not text.strip():
            raise AppError(ErrorCode.VALIDATION_FAILED, "PDF contains no extractable text (scanned images are not supported)")
        return text, ALLOWED[ext]
    if b"\x00" in data[:4096]:
        raise AppError(ErrorCode.UNSUPPORTED_FILE, "Binary content in a text file")
    try:
        return data.decode("utf-8-sig"), ALLOWED[ext]
    except UnicodeDecodeError as exc:
        raise AppError(ErrorCode.VALIDATION_FAILED, "Text files must be UTF-8 encoded") from exc


def _coerce_type(value: str | None) -> DocumentType | None:
    if not value:
        return None
    try:
        return DocumentType(value.strip().lower())
    except ValueError:
        return None


async def ingest_document(
    session: AsyncSession,
    embedder: Embedder,
    *,
    company_id: uuid.UUID,
    filename: str,
    data: bytes,
    document_type: DocumentType | None = None,
    title: str | None = None,
    source_id: uuid.UUID | None = None,
    actor_id: str | None = None,
) -> IngestResult:
    settings = get_settings()
    filename = _safe_filename(filename)
    text, mime = extract_text(filename, data)
    meta, body = parse_front_matter(text) if mime == "text/markdown" else ({}, text)
    digest = sha256_hex(body)

    existing = await session.scalar(
        select(m.Document).where(m.Document.company_id == company_id, m.Document.content_hash == digest)
    )
    if existing is not None:
        return IngestResult(existing, True, existing.chunk_count, existing.injection_findings)

    title = title or meta.get("title") or Path(filename).stem.replace("-", " ").title()
    doc_type = document_type or _coerce_type(meta.get("document_type")) or DocumentType.OTHER
    findings = [f.as_dict() for f in scan_for_injection(body)]
    if mime == "text/markdown":
        chunks = chunk_markdown(body, title=title, target_chars=settings.rag_chunk_target_chars,
                                overlap_chars=settings.rag_chunk_overlap_chars)
    else:
        chunks = chunk_plain(body, title=title, target_chars=settings.rag_chunk_target_chars,
                             overlap_chars=settings.rag_chunk_overlap_chars)
    if not chunks:
        raise AppError(ErrorCode.VALIDATION_FAILED, "Document produced no indexable text")

    doc = m.Document(
        company_id=company_id, knowledge_source_id=source_id, title=title[:255], document_type=doc_type,
        version=str(meta.get("version", "1.0"))[:40], source=filename, mime_type=mime, content_hash=digest,
        status=DocumentStatus.PENDING, char_count=len(body), injection_findings=findings,
    )
    session.add(doc)
    await session.flush()
    try:
        vectors = await embedder.aembed_documents([c.content for c in chunks])
    except Exception as exc:
        doc.status, doc.error = DocumentStatus.FAILED, f"embedding failed: {exc.__class__.__name__}"
        await session.flush()
        raise AppError(ErrorCode.TOOL_FAILURE, "Embedding model failed; document stored as FAILED") from exc

    for chunk, vector in zip(chunks, vectors, strict=True):
        chunk_findings = scan_for_injection(chunk.content)
        session.add(
            m.DocumentChunk(
                company_id=company_id, document_id=doc.id, document_type=doc_type, chunk_index=chunk.index,
                section=chunk.section[:255], content=chunk.content, char_count=len(chunk.content), embedding=vector,
                flagged_injection=bool(chunk_findings),
                metadata_={"title": title, "version": doc.version, "source": filename,
                           "effective_date": meta.get("effective_date"), "owner": meta.get("owner")},
            )
        )
    doc.status, doc.chunk_count = DocumentStatus.INDEXED, len(chunks)
    record_audit(
        session, company_id=company_id, action="knowledge.document_indexed", actor_type=ActorType.USER if actor_id else ActorType.SYSTEM,
        actor_id=actor_id, entity_type="document", entity_id=doc.id,
        output={"title": title, "chunks": len(chunks), "injection_findings": len(findings)},
    )
    await session.flush()
    return IngestResult(doc, False, len(chunks), findings)


async def ingest_directory(session: AsyncSession, embedder: Embedder, *, company_id: uuid.UUID, directory: Path) -> list[IngestResult]:
    source = m.KnowledgeSource(company_id=company_id, name="Seed knowledge base", kind="seed",
                               description=f"Loaded from {directory.name}/")
    session.add(source)
    await session.flush()
    results = []
    for path in sorted(directory.glob("*")):
        if path.suffix.lower() in ALLOWED:
            results.append(await ingest_document(session, embedder, company_id=company_id, filename=path.name,
                                                 data=path.read_bytes(), source_id=source.id))
    return results
