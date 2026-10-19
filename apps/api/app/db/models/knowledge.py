from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import get_settings
from app.db.base import Base, Timestamps, UUIDPk, company_fk, pg_enum
from app.domain.enums import DocumentStatus, DocumentType

EMBEDDING_DIM = get_settings().embedding_dim


class KnowledgeSource(UUIDPk, Timestamps, Base):
    __tablename__ = "knowledge_sources"

    company_id: Mapped[uuid.UUID] = company_fk()
    name: Mapped[str] = mapped_column(sa.String(200))
    kind: Mapped[str] = mapped_column(sa.String(40))  # upload | seed | api
    description: Mapped[str | None] = mapped_column(sa.Text)


class Document(UUIDPk, Timestamps, Base):
    __tablename__ = "documents"
    __table_args__ = (
        sa.UniqueConstraint("company_id", "content_hash", name="uq_documents_company_hash"),
        sa.Index("ix_documents_company_type", "company_id", "document_type"),
    )

    company_id: Mapped[uuid.UUID] = company_fk()
    knowledge_source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("knowledge_sources.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(sa.String(255))
    document_type: Mapped[DocumentType] = mapped_column(pg_enum(DocumentType, "document_type"))
    version: Mapped[str] = mapped_column(sa.String(40), default="1.0")
    source: Mapped[str] = mapped_column(sa.String(255))  # filename or origin
    mime_type: Mapped[str] = mapped_column(sa.String(100))
    content_hash: Mapped[str] = mapped_column(sa.String(64))
    status: Mapped[DocumentStatus] = mapped_column(pg_enum(DocumentStatus, "document_status"))
    chunk_count: Mapped[int] = mapped_column(default=0)
    char_count: Mapped[int] = mapped_column(default=0)
    # Prompt-injection scan result: [{pattern, excerpt}]. Flagged docs are still indexed but their
    # chunks are marked so the agent treats them with extra suspicion and the UI shows a warning.
    injection_findings: Mapped[list[Any]] = mapped_column(default=list)
    error: Mapped[str | None] = mapped_column(sa.Text)
    is_active: Mapped[bool] = mapped_column(default=True)


class DocumentChunk(UUIDPk, Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        sa.Index("ix_document_chunks_company_type", "company_id", "document_type"),
        sa.Index(
            "ix_document_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    company_id: Mapped[uuid.UUID] = company_fk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    # Denormalised for metadata filtering without a join.
    document_type: Mapped[DocumentType] = mapped_column(pg_enum(DocumentType, "document_type"))
    chunk_index: Mapped[int]
    section: Mapped[str] = mapped_column(sa.String(255))
    content: Mapped[str] = mapped_column(sa.Text)
    char_count: Mapped[int]
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    flagged_injection: Mapped[bool] = mapped_column(default=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", default=dict)
