"""Tenant-scoped intelligence: events, generated artifacts, claims, feedback, governance."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
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

from app.db.base import Base, TenantScoped, Timestamps, UUIDPk, utcnow

STATEMENT_TYPES = ("FACT", "INFERENCE", "UNKNOWN", "RECOMMENDED_INVESTIGATION")
CONFIDENCE_LABELS = ("Verified", "High", "Medium", "Low", "Not applicable")
REVIEW_STATUSES = ("Machine", "Analyst-reviewed", "Approved")
BANDS = ("Archive", "Feed", "Analyst Review", "High Priority", "Executive Alert")
FEEDBACK_LABELS = (
    "USEFUL",
    "NOT_USEFUL",
    "MATERIAL",
    "NOT_MATERIAL",
    "WRONG_MAPPING",
    "INCORRECT_INTERPRETATION",
    "ALREADY_KNOWN",
    "ESCALATE",
)


class IntelligenceEvent(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "intelligence_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "fingerprint"),
        Index("ix_intel_tenant_score", "tenant_id", "materiality_score"),
        Index("ix_intel_tenant_detected", "tenant_id", "detected_at"),
        Index("ix_intel_facets", "facet_terms", postgresql_using="gin"),
    )
    fingerprint: Mapped[str] = mapped_column(String(64))
    landscape_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("landscapes.id"), index=True)
    object_type: Mapped[str] = mapped_column(String(30))
    object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    source: Mapped[str] = mapped_column(String(30))
    primary_type: Mapped[str] = mapped_column(String(40))
    secondary_tags: Mapped[list[str]] = mapped_column(ARRAY(String(40)), default=list)
    title: Mapped[str] = mapped_column(Text)
    change_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    related_entity_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    # Normalized filter facets, e.g. "indication:non small cell lung cancer", "mechanism:target x inhibitor"
    facet_terms: Mapped[list[str]] = mapped_column(ARRAY(String(200)), default=list)
    company_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    asset_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    impacted_asset_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    impacted_assets: Mapped[list] = mapped_column(JSONB, default=list)  # [{asset_id, name, path, rationale, proximity}]
    materiality_score: Mapped[float] = mapped_column(Float, default=0.0)
    band: Mapped[str] = mapped_column(String(30), default="Archive")
    score_components: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="new")
    # new | pending_validation | published | blocked | acknowledged | escalated | archived
    review_status: Mapped[str] = mapped_column(String(30), default="Machine")
    version: Mapped[int] = mapped_column(Integer, default=1)
    update_summary: Mapped[list] = mapped_column(JSONB, default=list)  # what changed since prior version
    current_narrative_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    publication_blocked_reason: Mapped[str | None] = mapped_column(Text)
    # Pipeline telemetry for NFR-ALT-001 (source fetch -> event -> alert)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    alert_eligible_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[str | None] = mapped_column(String(100))


class GenerationRecord(UUIDPk, TenantScoped, Base):
    """Model governance record for every generated artifact (FR-AI-007, NFR-AI-001)."""

    __tablename__ = "generation_records"
    workflow: Mapped[str] = mapped_column(String(60))  # impact_narrative | ask | executive_brief | evidence_validation
    workflow_version: Mapped[str] = mapped_column(String(20))
    prompt_id: Mapped[str] = mapped_column(String(80))
    prompt_version: Mapped[str] = mapped_column(String(20))
    prompt_hash: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(80))
    served_model: Mapped[str | None] = mapped_column(String(80))
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    retrieval_set: Mapped[list] = mapped_column(JSONB, default=list)  # [{evidence_id, chunk_id, content_hash, ...}]
    retrieval_set_hash: Mapped[str | None] = mapped_column(String(64))
    embedding_model: Mapped[str | None] = mapped_column(String(80))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    request_id: Mapped[str | None] = mapped_column(String(100))
    stop_reason: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="succeeded")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GeneratedArtifact(UUIDPk, Timestamps, TenantScoped, Base):
    """A narrative / answer / brief. Human edits create a new row with parent_id -> original (FR-FBK-002)."""

    __tablename__ = "generated_artifacts"
    kind: Mapped[str] = mapped_column(String(30))  # impact_narrative | ask_answer | executive_brief
    intel_event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("intelligence_events.id"), index=True)
    content: Mapped[dict] = mapped_column(JSONB)
    generation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("generation_records.id"))
    validation_generation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    validation: Mapped[dict] = mapped_column(JSONB, default=dict)
    publishable: Mapped[bool] = mapped_column(Boolean, default=False)
    review_status: Mapped[str] = mapped_column(String(30), default="Machine")
    is_human_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    edited_by: Mapped[str | None] = mapped_column(String(100))
    edit_reason: Mapped[str | None] = mapped_column(Text)
    model_workflow_version: Mapped[str] = mapped_column(String(80))
    evidence_snapshot_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)


class Claim(UUIDPk, TenantScoped, Base):
    """Claim-level output (Section 12.1)."""

    __tablename__ = "claims"
    artifact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("generated_artifacts.id", ondelete="CASCADE"), index=True)
    intel_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(String(40))
    statement: Mapped[str] = mapped_column(Text)
    statement_type: Mapped[str] = mapped_column(String(30))
    confidence: Mapped[str] = mapped_column(String(20))
    evidence_ids: Mapped[list[str]] = mapped_column(ARRAY(String(80)), default=list)
    evidence_links: Mapped[list] = mapped_column(JSONB, default=list)
    affected_entities: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    validation_status: Mapped[str] = mapped_column(String(20), default="not_checked")
    # supported | partially_supported | unsupported | not_checked | not_applicable
    validation_detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    original_statement_type: Mapped[str | None] = mapped_column(String(30))
    review_status: Mapped[str] = mapped_column(String(30), default="Machine")
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    model_workflow_version: Mapped[str] = mapped_column(String(80))


class Feedback(UUIDPk, TenantScoped, Base):
    __tablename__ = "feedback"
    __table_args__ = (Index("ix_feedback_event", "tenant_id", "intel_event_id"),)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    intel_event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("intelligence_events.id"))
    claim_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    label: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    event_version: Mapped[int] = mapped_column(Integer, default=1)
    band_at_feedback: Mapped[str | None] = mapped_column(String(30))
    score_at_feedback: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class FeedbackDataset(UUIDPk, TenantScoped, Base):
    """Curated, versioned, frozen feedback set for model improvement (FR-FBK-003)."""

    __tablename__ = "feedback_datasets"
    __table_args__ = (UniqueConstraint("tenant_id", "name", "version"),)
    name: Mapped[str] = mapped_column(String(120))
    version: Mapped[int] = mapped_column(Integer)
    criteria: Mapped[dict] = mapped_column(JSONB, default=dict)
    records: Mapped[list] = mapped_column(JSONB, default=list)  # frozen copies (not references) of labels
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ModelRelease(UUIDPk, TenantScoped, Base):
    """Ranking / threshold / prompt release with traceable training data (FR-MAT-005)."""

    __tablename__ = "model_releases"
    component: Mapped[str] = mapped_column(String(40))  # materiality_thresholds | ranker | prompt
    version: Mapped[str] = mapped_column(String(40))
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("feedback_datasets.id"))
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    evaluation: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="candidate")  # candidate | promoted | retired
    promoted_by: Mapped[str | None] = mapped_column(String(100))
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AskSession(UUIDPk, Timestamps, TenantScoped, Base):
    """Ask-the-Landscape conversation memory; bound to one user + tenant (FR-QA-005)."""

    __tablename__ = "ask_sessions"
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    landscape_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("landscapes.id"))
    context: Mapped[dict] = mapped_column(JSONB, default=dict)  # referents, active filters
    title: Mapped[str | None] = mapped_column(Text)


class AskTurn(UUIDPk, TenantScoped, Base):
    __tablename__ = "ask_turns"
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ask_sessions.id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(Text)
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("generated_artifacts.id"))
    resolved_context: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
