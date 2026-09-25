"""RAG evidence index: chunked, embedded, lexically indexed source content."""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Computed, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import get_settings
from app.db.base import Base, OptionallyTenantScoped, UUIDPk, utcnow

EMBEDDING_DIM = get_settings().embedding_dim


class DocumentChunk(UUIDPk, OptionallyTenantScoped, Base):
    """A retrievable evidence unit.

    ``tenant_id`` NULL => public corpus, visible to all tenants. Tenant-private content (future R3
    internal documents, analyst notes) is isolated by RLS and by the retriever's filter.
    """

    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("source_document_id", "chunk_index", "embedding_model"),
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
        Index("ix_chunks_entities", "entity_ids", postgresql_using="gin"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_chunks_object", "object_type", "object_id"),
    )
    source_document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_documents.id"), index=True)
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_snapshots.id"))
    object_type: Mapped[str] = mapped_column(String(30))
    object_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    source: Mapped[str] = mapped_column(String(30), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(120))  # e.g. "eligibility", "primary_outcomes", "abstract"
    field_path: Mapped[str | None] = mapped_column(String(200))
    title: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    token_count: Mapped[int] = mapped_column(Integer)
    char_start: Mapped[int] = mapped_column(Integer, default=0)
    char_end: Mapped[int] = mapped_column(Integer, default=0)
    uri: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    entity_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    # False once a newer snapshot of the same object is indexed; history stays retrievable (FR-QA-003).
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    embedding_model: Mapped[str] = mapped_column(String(80))
    tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', coalesce(title, '') || ' ' || text)", persisted=True),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
