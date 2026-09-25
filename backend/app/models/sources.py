"""Source documents (raw immutable artifacts), snapshots, change events, connectors."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk, utcnow


class SourceDocument(UUIDPk, Base):
    """Immutable, content-addressed raw artifact (FR-SRC-008). Never updated after insert."""

    __tablename__ = "source_documents"
    __rls__ = "public"
    __table_args__ = (
        UniqueConstraint("source", "source_object_id", "checksum"),
        Index("ix_srcdoc_object", "source", "source_object_id"),
    )
    source: Mapped[str] = mapped_column(String(30))  # ctgov | pubmed | openfda_label | openfda_drugsfda | sec | ...
    source_object_id: Mapped[str] = mapped_column(String(200))
    uri: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(80), default="application/json")
    checksum: Mapped[str] = mapped_column(String(64))  # sha256 of raw bytes
    storage_key: Mapped[str] = mapped_column(String(300))
    byte_size: Mapped[int] = mapped_column(BigInteger)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_last_updated: Mapped[str | None] = mapped_column(String(40))
    connector_key: Mapped[str] = mapped_column(String(40))
    connector_version: Mapped[str] = mapped_column(String(20))
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # Rights metadata (Section 21: licensing) - license, redistribution allowed, attribution, disclaimer
    rights: Mapped[dict] = mapped_column(JSONB, default=dict)
    query_provenance: Mapped[dict] = mapped_column(JSONB, default=dict)
    title: Mapped[str | None] = mapped_column(Text)


class SourceSnapshot(UUIDPk, Base):
    """A versioned normalized state of a monitored object (FR-CHG-001)."""

    __tablename__ = "source_snapshots"
    __rls__ = "public"
    __table_args__ = (
        UniqueConstraint("object_type", "object_id", "version"),
        Index("ix_snapshot_object", "object_type", "object_id", "version"),
    )
    object_type: Mapped[str] = mapped_column(String(30))  # trial | label | drug_application | publication | disclosure
    object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    source: Mapped[str] = mapped_column(String(30))
    source_object_id: Mapped[str] = mapped_column(String(200))
    source_document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_documents.id"))
    version: Mapped[int] = mapped_column(Integer)
    normalized: Mapped[dict] = mapped_column(JSONB)
    normalized_hash: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(String(10), default="1")
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_last_updated: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChangeEvent(UUIDPk, Base):
    """A normalized, deduplicated, typed change between two snapshots (FR-CHG-002/004/006)."""

    __tablename__ = "change_events"
    __rls__ = "public"
    __table_args__ = (Index("ix_change_object", "object_type", "object_id", "detected_at"),)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    object_type: Mapped[str] = mapped_column(String(30))
    object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    source: Mapped[str] = mapped_column(String(30))
    field: Mapped[str] = mapped_column(String(80))
    change_type: Mapped[str] = mapped_column(String(40), index=True)
    secondary_tags: Mapped[list[str]] = mapped_column(ARRAY(String(40)), default=list)
    old_value: Mapped[dict | list | str | int | float | None] = mapped_column(JSONB)
    new_value: Mapped[dict | list | str | int | float | None] = mapped_column(JSONB)
    magnitude: Mapped[dict] = mapped_column(JSONB, default=dict)
    diff_detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    from_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_snapshots.id"))
    to_snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_snapshots.id"))
    suppressed: Mapped[bool] = mapped_column(Boolean, default=False)
    suppression_reason: Mapped[str | None] = mapped_column(String(200))
    source_fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class ConnectorConfig(UUIDPk, Timestamps, Base):
    __tablename__ = "connector_configs"
    __rls__ = "public"
    key: Mapped[str] = mapped_column(String(40), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    schedule_cron: Mapped[str] = mapped_column(String(60), default="0 */4 * * *")
    adapter_version: Mapped[str] = mapped_column(String(20))
    rate_limit_per_sec: Mapped[float] = mapped_column(Float, default=1.0)
    freshness_slo_hours: Mapped[int] = mapped_column(Integer, default=24)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
    checkpoint: Mapped[dict] = mapped_column(JSONB, default=dict)
    credentials_encrypted: Mapped[str | None] = mapped_column(Text)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[str | None] = mapped_column(String(100))


class ConnectorRun(UUIDPk, Base):
    __tablename__ = "connector_runs"
    __rls__ = "public"
    __table_args__ = (Index("ix_runs_key_started", "connector_key", "started_at"),)
    connector_key: Mapped[str] = mapped_column(String(40))
    adapter_version: Mapped[str] = mapped_column(String(20))
    trigger: Mapped[str] = mapped_column(String(20), default="schedule")  # schedule | manual | backfill
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | succeeded | partial | failed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    records_fetched: Mapped[int] = mapped_column(Integer, default=0)
    records_new: Mapped[int] = mapped_column(Integer, default=0)
    records_changed: Mapped[int] = mapped_column(Integer, default=0)
    records_unchanged: Mapped[int] = mapped_column(Integer, default=0)
    changes_emitted: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    error_detail: Mapped[list] = mapped_column(JSONB, default=list)
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    requested_by: Mapped[str | None] = mapped_column(String(100))
    message: Mapped[str | None] = mapped_column(Text)
