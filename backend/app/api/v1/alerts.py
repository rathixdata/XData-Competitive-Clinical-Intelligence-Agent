"""/alerts: policies, preview, test, delivery history, in-app inbox (FR-ALT-001/004)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field, HttpUrl
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.alerts.channels import DeliveryError, deliver
from app.alerts.dispatcher import preview
from app.api.deps import Page, get_db, page_params, paged, require
from app.api.serialize import row, rows
from app.core.crypto import decrypt_json, encrypt_json
from app.core.errors import NotFound, ValidationFailed
from app.core.rbac import Perm
from app.core.security import Principal
from app.models import AlertPolicy, Notification
from app.services import audit

router = APIRouter(prefix="/alerts", tags=["alerts"])
Channel = Literal["web", "email", "slack", "teams", "webhook"]


class Destinations(BaseModel):
    email: list[EmailStr] = Field(default_factory=list)
    slack_webhook: HttpUrl | None = None
    teams_webhook: HttpUrl | None = None
    webhook_url: HttpUrl | None = None


class PolicyIn(BaseModel):
    name: str
    landscape_id: uuid.UUID | None = None
    cadence: Literal["immediate", "daily", "weekly"] = "daily"
    min_score: float = Field(70.0, ge=0, le=100)
    event_types: list[str] = Field(default_factory=list)
    entity_ids: list[uuid.UUID] = Field(default_factory=list)
    watchlist_id: uuid.UUID | None = None
    channels: list[Channel] = Field(default_factory=lambda: ["web"])
    destinations: Destinations = Field(default_factory=Destinations)
    active: bool = True


def _check_channels(body: PolicyIn) -> None:
    d = body.destinations
    need = {"email": bool(d.email), "slack": bool(d.slack_webhook), "teams": bool(d.teams_webhook),
            "webhook": bool(d.webhook_url), "web": True}
    missing = [c for c in body.channels if not need[c]]
    if missing:
        raise ValidationFailed(f"destinations missing for channels {missing}")


def _view(p: AlertPolicy) -> dict[str, Any]:
    d = decrypt_json(p.destinations_encrypted) or {}
    masked = {"email": d.get("email", []), **{k: ("configured" if d.get(k) else None)
                                              for k in ("slack_webhook", "teams_webhook", "webhook_url")}}
    return {**row(p), "destinations": masked}


@router.get("/policies")
def list_policies(p: Principal = Depends(require(Perm.EVENT_READ)), db: Session = Depends(get_db)) -> list[dict]:
    return [_view(x) for x in db.scalars(select(AlertPolicy).where(AlertPolicy.owner_id == p.user_id)
                                         .order_by(AlertPolicy.name)).all()]


@router.post("/policies", status_code=201)
def create_policy(body: PolicyIn, p: Principal = Depends(require(Perm.ALERT_WRITE)), db: Session = Depends(get_db)) -> dict:
    _check_channels(body)
    pol = AlertPolicy(tenant_id=p.tenant_id, owner_id=p.user_id, name=body.name, landscape_id=body.landscape_id,
                      cadence=body.cadence, min_score=body.min_score, event_types=body.event_types,
                      entity_ids=body.entity_ids, watchlist_id=body.watchlist_id, channels=list(body.channels),
                      destinations_encrypted=encrypt_json(body.destinations.model_dump(mode="json")), active=body.active)
    db.add(pol)
    db.flush()
    audit.record(db, action="alert_policy.create", resource_type="alert_policy", resource_id=pol.id,
                 tenant_id=p.tenant_id, actor_id=p.actor, after=_view(pol))
    return _view(pol)


@router.put("/policies/{policy_id}")
def update_policy(policy_id: uuid.UUID, body: PolicyIn, p: Principal = Depends(require(Perm.ALERT_WRITE)),
                  db: Session = Depends(get_db)) -> dict:
    pol = db.get(AlertPolicy, policy_id)
    if pol is None or pol.owner_id != p.user_id:
        raise NotFound("policy not found")
    _check_channels(body)
    before = _view(pol)
    for k in ("name", "landscape_id", "cadence", "min_score", "event_types", "entity_ids", "watchlist_id", "active"):
        setattr(pol, k, getattr(body, k))
    pol.channels = list(body.channels)
    pol.destinations_encrypted = encrypt_json(body.destinations.model_dump(mode="json"))
    audit.record(db, action="alert_policy.update", resource_type="alert_policy", resource_id=pol.id,
                 tenant_id=p.tenant_id, actor_id=p.actor, before=before, after=_view(pol))
    return _view(pol)


@router.delete("/policies/{policy_id}", status_code=204)
def delete_policy(policy_id: uuid.UUID, p: Principal = Depends(require(Perm.ALERT_WRITE)), db: Session = Depends(get_db)) -> None:
    pol = db.get(AlertPolicy, policy_id)
    if pol is None or pol.owner_id != p.user_id:
        raise NotFound("policy not found")
    pol.active = False
    audit.record(db, action="alert_policy.deactivate", resource_type="alert_policy", resource_id=pol.id,
                 tenant_id=p.tenant_id, actor_id=p.actor)


class PreviewIn(BaseModel):
    landscape_id: uuid.UUID | None = None
    cadence: Literal["immediate", "daily", "weekly"] = "daily"
    min_score: float = 70
    event_types: list[str] = Field(default_factory=list)
    entity_ids: list[uuid.UUID] = Field(default_factory=list)
    watchlist_id: uuid.UUID | None = None
    days: int = Field(90, ge=7, le=365)


@router.post("/policies/preview")
def preview_policy(body: PreviewIn, p: Principal = Depends(require(Perm.EVENT_READ)), db: Session = Depends(get_db)) -> dict:
    """Estimated alert volume from historical events (FR-ALT-001)."""
    return preview(db, p.tenant_id, body.model_dump(mode="json"), body.days)


@router.post("/policies/{policy_id}/test")
def test_policy(policy_id: uuid.UUID, p: Principal = Depends(require(Perm.ALERT_WRITE)), db: Session = Depends(get_db)) -> dict:
    pol = db.get(AlertPolicy, policy_id)
    if pol is None or pol.owner_id != p.user_id:
        raise NotFound("policy not found")
    dest = decrypt_json(pol.destinations_encrypted) or {}
    payload = {"title": f"TEST — XData alert policy '{pol.name}'", "verified_change": ["This is a test delivery."],
               "generated_at": datetime.now(UTC).isoformat()}
    results = {}
    for ch in pol.channels or ["web"]:
        try:
            deliver(ch, dest, payload)
            results[ch] = "sent"
        except (DeliveryError, KeyError, OSError) as e:
            results[ch] = f"failed: {e}"
    db.add(Notification(tenant_id=p.tenant_id, dedupe_key=f"test:{pol.id}:{datetime.now(UTC).isoformat()}",
                        policy_id=pol.id, user_id=p.user_id, kind="alert", channel="web", status="sent",
                        payload=payload, sent_at=datetime.now(UTC)))
    return {"results": results}


@router.get("/deliveries")
def deliveries(status: str | None = None, channel: str | None = None, page: Page = Depends(page_params),
               p: Principal = Depends(require(Perm.EVENT_READ)), db: Session = Depends(get_db)) -> dict:
    stmt = select(Notification).where(Notification.tenant_id == p.tenant_id,
                                      or_(Notification.user_id == p.user_id, Notification.user_id.is_(None)))
    if status:
        stmt = stmt.where(Notification.status == status)
    if channel:
        stmt = stmt.where(Notification.channel == channel)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.scalars(stmt.order_by(Notification.created_at.desc()).limit(page.limit).offset(page.offset)).all()
    return paged(rows(items), total, page)


@router.get("/inbox")
def inbox(unread_only: bool = False, p: Principal = Depends(require(Perm.EVENT_READ)), db: Session = Depends(get_db)) -> list[dict]:
    stmt = select(Notification).where(Notification.tenant_id == p.tenant_id, Notification.channel == "web",
                                      or_(Notification.user_id == p.user_id, Notification.user_id.is_(None)))
    if unread_only:
        stmt = stmt.where(Notification.status != "read")
    return rows(db.scalars(stmt.order_by(Notification.created_at.desc()).limit(100)).all())


@router.post("/inbox/{notification_id}/read")
def mark_read(notification_id: uuid.UUID, p: Principal = Depends(require(Perm.EVENT_READ)), db: Session = Depends(get_db)) -> dict:
    n = db.get(Notification, notification_id)
    if n is None or n.tenant_id != p.tenant_id or n.user_id not in (p.user_id, None):
        raise NotFound("notification not found")
    n.status = "read"
    return row(n)
