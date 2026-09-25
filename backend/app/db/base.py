"""SQLAlchemy declarative base and shared column mixins."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPk:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now(), nullable=False
    )


class TenantScoped:
    """Rows that always belong to exactly one tenant (strict RLS)."""

    __rls__ = "strict"
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)


class OptionallyTenantScoped:
    """Rows that are either public-corpus (tenant_id NULL) or tenant-private.

    Public corpus rows (e.g. ClinicalTrials.gov-derived trials) are readable by every tenant;
    tenant-private rows (e.g. the customer's internal asset XD-101) are visible only to their tenant.
    """

    __rls__ = "shared"
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True, nullable=True)
