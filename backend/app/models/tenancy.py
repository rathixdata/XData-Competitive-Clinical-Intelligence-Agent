"""Tenants, users, API keys, platform records (idempotency, usage, audit)."""

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
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScoped, Timestamps, UUIDPk, utcnow


class Tenant(UUIDPk, Timestamps, Base):
    __tablename__ = "tenants"
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    deployment_mode: Mapped[str] = mapped_column(String(20), default="multi_tenant")  # or "dedicated"
    # retention_days per data class, llm budget, allow_training (NFR-AI-002, default False)...
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)


class User(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "email"),)
    email: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str | None] = mapped_column(String(300))
    external_subject: Mapped[str | None] = mapped_column(String(300), index=True)
    roles: Mapped[list[str]] = mapped_column(ARRAY(String(40)), default=list)
    team: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    preferences: Mapped[dict] = mapped_column(JSONB, default=dict)


class ApiKey(UUIDPk, Timestamps, TenantScoped, Base):
    __tablename__ = "api_keys"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    key_prefix: Mapped[str] = mapped_column(String(16), index=True)
    key_hash: Mapped[str] = mapped_column(String(128))
    roles: Mapped[list[str]] = mapped_column(ARRAY(String(40)), default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IdempotencyRecord(TenantScoped, Base):
    __tablename__ = "idempotency_keys"
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    method: Mapped[str] = mapped_column(String(10))
    path: Mapped[str] = mapped_column(String(500))
    request_hash: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int] = mapped_column(Integer)
    response: Mapped[dict | list | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UsageRecord(UUIDPk, TenantScoped, Base):
    """Per-tenant/model/source usage telemetry for cost controls (Section 20)."""

    __tablename__ = "usage_records"
    kind: Mapped[str] = mapped_column(String(30))  # llm | embedding | rerank | source
    component: Mapped[str] = mapped_column(String(80))
    model: Mapped[str | None] = mapped_column(String(80))
    input_units: Mapped[int] = mapped_column(Integer, default=0)
    output_units: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class AuditLog(Base):
    """Append-only, hash-chained audit trail (NFR-AUD-001). UPDATE/DELETE blocked by DB trigger."""

    __tablename__ = "audit_log"
    __rls__ = "shared"
    __table_args__ = (Index("ix_audit_tenant_time", "tenant_id", "created_at"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_id: Mapped[str | None] = mapped_column(String(100))
    actor_type: Mapped[str] = mapped_column(String(20), default="user")  # user | system | api_key
    action: Mapped[str] = mapped_column(String(100), index=True)
    resource_type: Mapped[str] = mapped_column(String(60))
    resource_id: Mapped[str | None] = mapped_column(String(100))
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(String(64))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    prev_hash: Mapped[str | None] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )


class FeatureFlag(UUIDPk, Timestamps, Base):
    """Feature flags for new connectors / models / ranking changes (Section 20)."""

    __tablename__ = "feature_flags"
    __rls__ = "shared"
    __table_args__ = (UniqueConstraint("key", "tenant_id"),)
    key: Mapped[str] = mapped_column(String(100))
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str | None] = mapped_column(Text)
