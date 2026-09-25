"""Landscapes, watchlists, proximity rules, saved views, alerts, reports."""

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

from app.db.base import Base, TenantScoped, Timestamps, UUIDPk, utcnow


class LandscapeTemplate(UUIDPk, Timestamps, Base):
    """Reusable therapeutic-area template; contains no customer-private data (FR-LND-005)."""

    __tablename__ = "landscape_templates"
    __rls__ = "public"
    name: Mapped[str] = mapped_column(String(200), unique=True)
    therapeutic_area: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)


class Landscape(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "landscapes"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    disease: Mapped[str | None] = mapped_column(String(200))
    indication_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    mechanism_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    biomarker_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    geographies: Mapped[list[str]] = mapped_column(ARRAY(String(40)), default=list)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | archived
    # materiality weights, band thresholds, pubmed queries, fda products, sec ciks, monitored fields...
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    template_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("landscape_templates.id"))
    created_by: Mapped[str | None] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer, default=1)


class LandscapeMember(UUIDPk, TenantScoped, Base):
    __tablename__ = "landscape_members"
    __table_args__ = (UniqueConstraint("landscape_id", "entity_type", "entity_id"),)
    landscape_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("landscapes.id", ondelete="CASCADE"), index=True)
    entity_type: Mapped[str] = mapped_column(String(30))  # asset | company | trial
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    role: Mapped[str] = mapped_column(String(20), default="competitor")  # customer | competitor | monitored
    added_by: Mapped[str | None] = mapped_column(String(100))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Watchlist(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "watchlists"
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(String(20), default="private")  # private | team | tenant
    team: Mapped[str | None] = mapped_column(String(100))
    landscape_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("landscapes.id"))
    alert_policy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class WatchlistItem(UUIDPk, TenantScoped, Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("watchlist_id", "item_type", "entity_id", "value"),)
    watchlist_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("watchlists.id", ondelete="CASCADE"), index=True)
    item_type: Mapped[str] = mapped_column(String(30))
    # company | asset | mechanism | indication | trial | kol | conference | regulatory_event
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    value: Mapped[str] = mapped_column(String(300), default="")
    added_by: Mapped[str | None] = mapped_column(String(100))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProximityRule(UUIDPk, Timestamps, TenantScoped, Base):
    """Weighted competitive-proximity dimensions (FR-LND-004)."""

    __tablename__ = "proximity_rules"
    landscape_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("landscapes.id"))
    name: Mapped[str] = mapped_column(String(200))
    # {"target": 0.3, "indication": 0.25, "line_of_therapy": 0.15, "biomarker": 0.15, "modality": 0.1, "geography": 0.05}
    weights: Mapped[dict] = mapped_column(JSONB)
    min_proximity: Mapped[float] = mapped_column(Float, default=0.35)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | active | retired
    version: Mapped[int] = mapped_column(Integer, default=1)
    test_results: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(100))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SavedView(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "saved_views"
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    name: Mapped[str] = mapped_column(String(200))
    view: Mapped[str] = mapped_column(String(30))  # feed | calendar | matrix | compare
    filters: Mapped[dict] = mapped_column(JSONB, default=dict)
    visibility: Mapped[str] = mapped_column(String(20), default="private")  # private | team | tenant
    team: Mapped[str | None] = mapped_column(String(100))


class AlertPolicy(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "alert_policies"
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    name: Mapped[str] = mapped_column(String(200))
    landscape_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("landscapes.id"))
    cadence: Mapped[str] = mapped_column(String(20), default="daily")  # immediate | daily | weekly
    min_score: Mapped[float] = mapped_column(Float, default=70.0)
    event_types: Mapped[list[str]] = mapped_column(ARRAY(String(40)), default=list)
    entity_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    watchlist_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("watchlists.id"))
    channels: Mapped[list[str]] = mapped_column(ARRAY(String(20)), default=lambda: ["web"])
    # Encrypted JSON: {"email": [...], "slack_webhook": "...", "teams_webhook": "...", "webhook_url": "..."}
    destinations_encrypted: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_digest_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Notification(UUIDPk, TenantScoped, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("tenant_id", "dedupe_key"),
        Index("ix_notif_status", "status", "next_attempt_at"),
    )
    dedupe_key: Mapped[str] = mapped_column(String(200))
    policy_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("alert_policies.id"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    intel_event_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    kind: Mapped[str] = mapped_column(String(20), default="alert")  # alert | digest | brief
    channel: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | sent | failed | dead | read
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotifiedEventState(TenantScoped, Base):
    """Last notified version of an intel event per policy - digest dedup (FR-ALT-005)."""

    __tablename__ = "notified_event_state"
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    policy_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    intel_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    version: Mapped[int] = mapped_column(Integer)
    notified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Report(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "reports"
    landscape_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("landscapes.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30), default="executive_brief")
    title: Mapped[str] = mapped_column(Text)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | in_review | approved | distributed
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("generated_artifacts.id"))
    edited_artifact_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    distribution_list: Mapped[list[str]] = mapped_column(ARRAY(String(320)), default=list)
    created_by: Mapped[str | None] = mapped_column(String(100))
    approved_by: Mapped[str | None] = mapped_column(String(100))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    distributed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
