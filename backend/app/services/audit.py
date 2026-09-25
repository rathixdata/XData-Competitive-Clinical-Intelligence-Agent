"""Audit logging (NFR-AUD-001, Section 8.2: actor, timestamp, before/after, reason).

Rows are hash-chained per tenant so tampering (even by a DBA) is detectable, and the table
is protected against UPDATE/DELETE by a trigger (migration 0002).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.crypto import stable_hash
from app.core.request_context import current_request_meta
from app.models import AuditLog


def _json_safe(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple | set):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, uuid.UUID | datetime):
        return str(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return obj


def record(
    db: Session,
    *,
    action: str,
    resource_type: str,
    resource_id: Any = None,
    tenant_id: uuid.UUID | None = None,
    actor_id: str | None = None,
    actor_type: str = "user",
    before: dict | None = None,
    after: dict | None = None,
    reason: str | None = None,
) -> AuditLog:
    meta = current_request_meta()
    # Serialize hash-chain appends per tenant.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"audit:{tenant_id}"})
    prev = db.scalar(
        select(AuditLog.hash)
        .where(AuditLog.tenant_id.is_(None) if tenant_id is None else AuditLog.tenant_id == tenant_id)
        .order_by(AuditLog.id.desc())
        .limit(1)
    )
    now = datetime.now(UTC)
    body = {
        "tenant_id": str(tenant_id) if tenant_id else None,
        "actor_id": actor_id,
        "actor_type": actor_type,
        "action": action,
        "resource_type": resource_type,
        "resource_id": str(resource_id) if resource_id is not None else None,
        "before": _json_safe(before),
        "after": _json_safe(after),
        "reason": reason,
        "created_at": now.isoformat(),
        "prev_hash": prev,
    }
    entry = AuditLog(
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_type=actor_type,
        action=action,
        resource_type=resource_type,
        resource_id=body["resource_id"],
        before=body["before"],
        after=body["after"],
        reason=reason,
        request_id=meta.get("request_id"),
        ip=meta.get("ip"),
        user_agent=meta.get("user_agent"),
        prev_hash=prev,
        hash=stable_hash(body),
        created_at=now,
    )
    db.add(entry)
    db.flush()
    return entry


def verify_chain(db: Session, tenant_id: uuid.UUID | None) -> dict[str, Any]:
    """Recompute the hash chain; returns first broken link if any."""
    rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.tenant_id.is_(None) if tenant_id is None else AuditLog.tenant_id == tenant_id)
        .order_by(AuditLog.id)
    ).all()
    prev = None
    for r in rows:
        body = {
            "tenant_id": str(r.tenant_id) if r.tenant_id else None,
            "actor_id": r.actor_id,
            "actor_type": r.actor_type,
            "action": r.action,
            "resource_type": r.resource_type,
            "resource_id": r.resource_id,
            "before": r.before,
            "after": r.after,
            "reason": r.reason,
            "created_at": r.created_at.astimezone(UTC).isoformat(),
            "prev_hash": prev,
        }
        if r.prev_hash != prev or stable_hash(body) != r.hash:
            return {"valid": False, "broken_at": r.id, "checked": len(rows)}
        prev = r.hash
    return {"valid": True, "checked": len(rows)}
