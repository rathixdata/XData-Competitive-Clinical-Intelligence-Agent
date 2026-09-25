"""Canonical life-sciences entities, aliases and the relationship graph (FR-ENT-*)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
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

from app.db.base import Base, OptionallyTenantScoped, TenantScoped, Timestamps, UUIDPk

# Concept kinds represented in the generic ontology table.
CONCEPT_KINDS = (
    "target",
    "mechanism",
    "indication",
    "biomarker",
    "endpoint",
    "modality",
    "line_of_therapy",
    "conference",
    "kol",
)

ENTITY_TYPES = (
    "company",
    "asset",
    "trial",
    "publication",
    "regulatory_event",
    "disclosure",
    "catalyst",
    *CONCEPT_KINDS,
)

# Typed relationships (FR-ENT-003)
PREDICATES = (
    "develops",  # company -> asset
    "targets",  # asset -> target
    "has_mechanism",  # asset -> mechanism
    "has_modality",  # asset -> modality
    "evaluated_in",  # asset -> trial
    "studies",  # trial -> indication
    "uses_endpoint",  # trial -> endpoint
    "enrolls_biomarker",  # trial -> biomarker
    "competes_with",  # asset -> asset
    "authored",  # kol -> publication
    "mentions",  # publication -> asset/trial
    "received_regulatory_event",  # asset -> regulatory_event
    "sponsors",  # company -> trial
    "disclosed",  # company -> disclosure
    "indicated_for",  # asset -> indication
)


class Company(UUIDPk, Timestamps, OptionallyTenantScoped, Base):
    __tablename__ = "companies"
    canonical_name: Mapped[str] = mapped_column(String(300), index=True)
    website: Mapped[str | None] = mapped_column(String(300))
    identifiers: Mapped[dict] = mapped_column(JSONB, default=dict)  # cik, ticker, lei, duns
    status: Mapped[str] = mapped_column(String(20), default="active")
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class Asset(UUIDPk, Timestamps, OptionallyTenantScoped, Base):
    """A therapeutic asset. Internal customer assets are tenant-private (tenant_id set)."""

    __tablename__ = "assets"
    canonical_name: Mapped[str] = mapped_column(String(300), index=True)
    owner_company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id"))
    is_internal: Mapped[bool] = mapped_column(Boolean, default=False)
    modality: Mapped[str | None] = mapped_column(String(100))
    stage: Mapped[str | None] = mapped_column(String(40))
    # Configurable profile (FR-LND-003): mechanism, indication, population, biomarker, line_of_therapy,
    # endpoint, route, dosing, geography, milestones, strategic_notes, target(s) ...
    profile: Mapped[dict] = mapped_column(JSONB, default=dict)
    profile_version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="active")
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class AssetProfileVersion(UUIDPk, OptionallyTenantScoped, Base):
    __tablename__ = "asset_profile_versions"
    __table_args__ = (UniqueConstraint("asset_id", "version"),)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    profile: Mapped[dict] = mapped_column(JSONB)
    changed_by: Mapped[str | None] = mapped_column(String(100))
    reason: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Concept(UUIDPk, Timestamps, OptionallyTenantScoped, Base):
    """Target, Mechanism, Indication, Biomarker, Endpoint, Modality, Conference, KOL, ..."""

    __tablename__ = "concepts"
    __table_args__ = (Index("ix_concepts_kind_name", "kind", "canonical_name"),)
    kind: Mapped[str] = mapped_column(String(30))
    canonical_name: Mapped[str] = mapped_column(String(300))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("concepts.id"))
    codes: Mapped[dict] = mapped_column(JSONB, default=dict)  # MeSH, MONDO, HGNC, NCIt ...
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict)
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class Trial(UUIDPk, Timestamps, Base):
    """Canonical trial. Public corpus (no tenant)."""

    __tablename__ = "trials"
    __rls__ = "public"
    nct_id: Mapped[str | None] = mapped_column(String(20), unique=True)
    source_ids: Mapped[dict] = mapped_column(JSONB, default=dict)  # {"ctgov": "NCT..", "euct": ".."}
    title: Mapped[str] = mapped_column(Text)
    sponsor_company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id"))
    sponsor_name: Mapped[str | None] = mapped_column(String(300))
    phase: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str | None] = mapped_column(String(40))
    enrollment: Mapped[int | None] = mapped_column(Integer)
    start_date: Mapped[date | None] = mapped_column(Date)
    primary_completion_date: Mapped[date | None] = mapped_column(Date)
    completion_date: Mapped[date | None] = mapped_column(Date)
    current: Mapped[dict] = mapped_column(JSONB, default=dict)  # latest normalized record
    current_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Publication(UUIDPk, Timestamps, Base):
    __tablename__ = "publications"
    __rls__ = "public"
    pmid: Mapped[str | None] = mapped_column(String(20), unique=True)
    doi: Mapped[str | None] = mapped_column(String(200), index=True)
    title: Mapped[str] = mapped_column(Text)
    authors: Mapped[list] = mapped_column(JSONB, default=list)
    journal: Mapped[str | None] = mapped_column(String(300))
    pub_date: Mapped[date | None] = mapped_column(Date)
    abstract: Mapped[str | None] = mapped_column(Text)
    query_provenance: Mapped[list] = mapped_column(JSONB, default=list)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_documents.id"))


class RegulatoryEvent(UUIDPk, Timestamps, Base):
    __tablename__ = "regulatory_events"
    __rls__ = "public"
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    agency: Mapped[str] = mapped_column(String(20), default="FDA")
    event_type: Mapped[str] = mapped_column(String(40))  # APPROVAL | LABEL_CHANGED | SUPPLEMENT ...
    product_name: Mapped[str] = mapped_column(String(300))
    application_number: Mapped[str | None] = mapped_column(String(40), index=True)
    asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assets.id"))
    event_date: Mapped[date | None] = mapped_column(Date)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_documents.id"))


class Disclosure(UUIDPk, Timestamps, Base):
    """Corporate / SEC disclosure (FR-SRC-005)."""

    __tablename__ = "disclosures"
    __rls__ = "public"
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id"))
    form_type: Mapped[str | None] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extracted_entities: Mapped[list] = mapped_column(JSONB, default=list)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_documents.id"))


class Catalyst(UUIDPk, Timestamps, OptionallyTenantScoped, Base):
    __tablename__ = "catalysts"
    __table_args__ = (UniqueConstraint("dedupe_key"),)
    dedupe_key: Mapped[str] = mapped_column(String(200))
    event_type: Mapped[str] = mapped_column(String(40))  # PRIMARY_COMPLETION | READOUT | PDUFA | CONFERENCE ...
    title: Mapped[str] = mapped_column(Text)
    asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assets.id"), index=True)
    trial_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trials.id"), index=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id"))
    expected_date: Mapped[date | None] = mapped_column(Date, index=True)
    window_start: Mapped[date | None] = mapped_column(Date)
    window_end: Mapped[date | None] = mapped_column(Date)
    date_basis: Mapped[str] = mapped_column(String(20), default="SOURCED")  # SOURCED | INFERRED
    date_precision: Mapped[str] = mapped_column(String(10), default="day")  # day | month | quarter
    confidence: Mapped[str] = mapped_column(String(20), default="Verified")
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_documents.id"))
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    history: Mapped[list] = mapped_column(JSONB, default=list)  # prior dates with change timestamps
    status: Mapped[str] = mapped_column(String(20), default="upcoming")


class EntityAlias(UUIDPk, Timestamps, OptionallyTenantScoped, Base):
    __tablename__ = "entity_aliases"
    __table_args__ = (
        UniqueConstraint("entity_type", "alias_norm", "entity_id", "tenant_id"),
        Index("ix_alias_norm", "alias_norm"),
    )
    entity_type: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    alias: Mapped[str] = mapped_column(String(300))
    alias_norm: Mapped[str] = mapped_column(String(300))
    alias_type: Mapped[str] = mapped_column(String(30), default="synonym")
    # dev_code | generic | brand | legacy | abbreviation | spelling | synonym | canonical
    source: Mapped[str] = mapped_column(String(30), default="seed")  # seed | source | analyst
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    created_by: Mapped[str | None] = mapped_column(String(100))


class EntityLink(UUIDPk, Timestamps, OptionallyTenantScoped, Base):
    """Outcome of resolving a textual mention to a canonical entity (FR-ENT-002/004/005)."""

    __tablename__ = "entity_links"
    __table_args__ = (Index("ix_entity_links_status", "status"),)
    mention: Mapped[str] = mapped_column(String(300))
    mention_norm: Mapped[str] = mapped_column(String(300), index=True)
    entity_type: Mapped[str] = mapped_column(String(30))
    context_type: Mapped[str | None] = mapped_column(String(30))
    context_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    method: Mapped[str] = mapped_column(String(80))  # exact_alias | normalized_alias | fuzzy | analyst | none
    status: Mapped[str] = mapped_column(String(20))  # auto_linked | pending_review | approved | rejected | unresolved
    candidates: Mapped[list] = mapped_column(JSONB, default=list)
    reviewed_by: Mapped[str | None] = mapped_column(String(100))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_reason: Mapped[str | None] = mapped_column(Text)


class Relationship(UUIDPk, Timestamps, OptionallyTenantScoped, Base):
    __tablename__ = "relationships"
    __table_args__ = (
        UniqueConstraint("subject_id", "predicate", "object_id", "tenant_id", "valid_from"),
        Index("ix_rel_subject", "subject_id", "predicate"),
        Index("ix_rel_object", "object_id", "predicate"),
    )
    subject_type: Mapped[str] = mapped_column(String(30))
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    predicate: Mapped[str] = mapped_column(String(40))
    object_type: Mapped[str] = mapped_column(String(30))
    object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    method: Mapped[str] = mapped_column(String(120), default="source")
    status: Mapped[str] = mapped_column(String(20), default="verified")  # verified | proposed | rejected
    # Temporal validity (FR-ENT-006) - e.g. ownership changes over time.
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)


class ProfileFieldDefinition(UUIDPk, Timestamps, TenantScoped, Base):
    """Code-free configuration of internal asset profile fields (FR-LND-003)."""

    __tablename__ = "profile_field_definitions"
    __table_args__ = (UniqueConstraint("tenant_id", "key"),)
    key: Mapped[str] = mapped_column(String(60))
    label: Mapped[str] = mapped_column(String(120))
    field_type: Mapped[str] = mapped_column(String(20), default="text")  # text | number | date | enum | list
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    options: Mapped[list] = mapped_column(JSONB, default=list)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    entity_ids_kind: Mapped[str | None] = mapped_column(String(30))  # concept kind when field links to ontology
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(40)), default=list)
    description: Mapped[str | None] = mapped_column(Text)
