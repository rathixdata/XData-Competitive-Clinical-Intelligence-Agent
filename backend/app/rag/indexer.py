"""Evidence indexing: chunk -> embed -> store with full provenance (source doc, snapshot, field path)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.connectors.base import TextSection
from app.core.config import get_settings
from app.core.crypto import sha256_hex
from app.models import DocumentChunk, SourceDocument
from app.rag.chunking import chunk_text
from app.rag.embeddings import get_embedder


def embedding_text(title: str | None, section: str | None, text: str) -> str:
    """Contextual header prepended for embedding only (stored text stays verbatim for citation)."""
    head = " | ".join(x for x in (title, section.replace("_", " ") if section else None) if x)
    return f"{head}\n{text}" if head else text


def index_sections(
    db: Session,
    *,
    source_document: SourceDocument,
    object_type: str,
    object_id: uuid.UUID | None,
    sections: Sequence[TextSection],
    snapshot_id: uuid.UUID | None = None,
    entity_ids: list[uuid.UUID] | None = None,
    published_at: datetime | None = None,
    tenant_id: uuid.UUID | None = None,
    meta: dict | None = None,
) -> int:
    s = get_settings()
    embedder = get_embedder()
    existing = set(
        db.scalars(
            select(DocumentChunk.chunk_index).where(
                DocumentChunk.source_document_id == source_document.id,
                DocumentChunk.embedding_model == embedder.model_name,
            )
        ).all()
    )
    rows: list[DocumentChunk] = []
    idx = 0
    for sec in sections:
        for ch in chunk_text(sec.text, s.rag_chunk_tokens, s.rag_chunk_overlap):
            if idx not in existing:
                rows.append(
                    DocumentChunk(
                        tenant_id=tenant_id,
                        source_document_id=source_document.id,
                        snapshot_id=snapshot_id,
                        object_type=object_type,
                        object_id=object_id,
                        source=source_document.source,
                        chunk_index=idx,
                        section=sec.section,
                        field_path=sec.field_path,
                        title=sec.title or source_document.title,
                        text=ch.text,
                        content_hash=sha256_hex(ch.text),
                        token_count=ch.token_count,
                        char_start=ch.char_start,
                        char_end=ch.char_end,
                        uri=source_document.uri,
                        published_at=published_at or source_document.published_at,
                        retrieved_at=source_document.retrieved_at,
                        entity_ids=list(entity_ids or []),
                        embedding_model=embedder.model_name,
                        meta={**(meta or {}), "rights": source_document.rights},
                    )
                )
            idx += 1
    if not rows:
        return 0
    vectors = embedder.embed_documents([embedding_text(r.title, r.section, r.text) for r in rows])
    for r, v in zip(rows, vectors, strict=True):
        r.embedding = v
    # Older snapshots of this object stay indexed (temporal questions) but are no longer "current".
    if object_id is not None:
        db.execute(
            update(DocumentChunk)
            .where(DocumentChunk.object_id == object_id, DocumentChunk.source_document_id != source_document.id,
                   DocumentChunk.is_current.is_(True))
            .values(is_current=False)
        )
    db.add_all(rows)
    db.flush()
    return len(rows)


def reembed_all(db: Session, batch: int = 256) -> int:
    """Re-embed chunks after an embedding-model upgrade (run as a maintenance task)."""
    embedder = get_embedder()
    n = 0
    while True:
        rows = db.scalars(
            select(DocumentChunk).where(DocumentChunk.embedding_model != embedder.model_name).limit(batch)
        ).all()
        if not rows:
            return n
        vecs = embedder.embed_documents([embedding_text(r.title, r.section, r.text) for r in rows])
        for r, v in zip(rows, vecs, strict=True):
            r.embedding, r.embedding_model = v, embedder.model_name
        db.flush()
        n += len(rows)
