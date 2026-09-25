"""Alert policies, previews, immediate alerts, digests, retries (FR-ALT-001/002/005)."""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.alerts.channels import DeliveryError, deliver
from app.core.config import get_settings
from app.core.crypto import decrypt_json
from app.core.logging import get_logger
from app.core.metrics import ALERT_DELIVERIES, PIPELINE_LATENCY
from app.models import (
    AlertPolicy,
    Claim,
    GeneratedArtifact,
    IntelligenceEvent,
    Notification,
    NotifiedEventState,
    WatchlistItem,
)

log = get_logger(__name__)
MAX_ATTEMPTS = 6


def _policy_entity_ids(db: Session, policy: AlertPolicy) -> set[uuid.UUID]:
    ids = set(policy.entity_ids or [])
    if policy.watchlist_id:
        ids |= {i for i in db.scalars(select(WatchlistItem.entity_id).where(
            WatchlistItem.watchlist_id == policy.watchlist_id)).all() if i}
    return ids


def matches(db: Session, policy: AlertPolicy, event: IntelligenceEvent, entity_ids: set[uuid.UUID] | None = None) -> bool:
    if not policy.active or event.materiality_score < policy.min_score:
        return False
    if policy.landscape_id and policy.landscape_id != event.landscape_id:
        return False
    if policy.event_types and event.primary_type not in policy.event_types and not (
            set(policy.event_types) & set(event.secondary_tags or [])):
        return False
    ids = entity_ids if entity_ids is not None else _policy_entity_ids(db, policy)
    if ids:
        ev_ids = {event.object_id, event.company_id, event.asset_id, *(event.related_entity_ids or []),
                  *(event.impacted_asset_ids or [])}
        if not ids & ev_ids:
            return False
    return event.status in ("published", "acknowledged", "escalated")


def preview(db: Session, tenant_id: uuid.UUID, criteria: dict[str, Any], days: int = 90) -> dict[str, Any]:
    """Estimate alert volume from historical events (FR-ALT-001 acceptance)."""
    since = datetime.now(UTC) - timedelta(days=days)
    policy = AlertPolicy(tenant_id=tenant_id, owner_id=uuid.uuid4(), name="preview", active=True,
                         cadence=criteria.get("cadence", "daily"), min_score=float(criteria.get("min_score", 70)),
                         event_types=criteria.get("event_types") or [], entity_ids=[uuid.UUID(str(x)) for x in criteria.get("entity_ids") or []],
                         landscape_id=uuid.UUID(str(criteria["landscape_id"])) if criteria.get("landscape_id") else None,
                         watchlist_id=uuid.UUID(str(criteria["watchlist_id"])) if criteria.get("watchlist_id") else None)
    ids = _policy_entity_ids(db, policy)
    events = db.scalars(select(IntelligenceEvent).where(IntelligenceEvent.tenant_id == tenant_id,
                                                        IntelligenceEvent.detected_at >= since)).all()
    hits = [e for e in events if matches(db, policy, e, ids)]
    weeks = max(1.0, days / 7)
    by_band = Counter(e.band for e in hits)
    by_type = Counter(e.primary_type for e in hits)
    per_week = round(len(hits) / weeks, 2)
    cadence = policy.cadence
    deliveries_per_week = per_week if cadence == "immediate" else (
        min(7.0, len({e.detected_at.date() for e in hits}) / weeks) if cadence == "daily" else
        min(1.0, len({e.detected_at.isocalendar()[:2] for e in hits}) / weeks))
    return {"window_days": days, "matching_events": len(hits), "events_per_week": per_week,
            "estimated_deliveries_per_week": round(deliveries_per_week, 2), "by_band": dict(by_band),
            "by_event_type": dict(by_type), "sample_event_ids": [str(e.id) for e in hits[:10]]}


def _statements(db: Session, artifact_id: uuid.UUID | None) -> dict[str, list[Claim]]:
    out: dict[str, list[Claim]] = {}
    if not artifact_id:
        return out
    for c in db.scalars(select(Claim).where(Claim.artifact_id == artifact_id).order_by(Claim.ordinal)).all():
        out.setdefault(c.statement_type, []).append(c)
    return out


def alert_payload(db: Session, event: IntelligenceEvent, *, prior_version: int | None = None) -> dict[str, Any]:
    """Appendix B high-priority alert contract."""
    s = get_settings()
    by_type = _statements(db, event.current_narrative_id)
    art = db.get(GeneratedArtifact, event.current_narrative_id) if event.current_narrative_id else None
    facts = by_type.get("FACT", [])
    why = [h for d in (event.score_components or {}).get("dimensions", {}).values() for h in d.get("rule_hits", [])][:6]
    evidence = sorted({(link.get("source_type"), link.get("uri")) for c in facts for link in c.evidence_links},
                      key=lambda x: str(x))
    band_prefix = {"Executive Alert": "EXECUTIVE ALERT", "High Priority": "HIGH PRIORITY"}.get(event.band, event.band.upper())
    return {
        "title": f"{band_prefix} — {event.title}",
        "event_id": str(event.id),
        "event_version": event.version,
        "affected_assets": [f"{m['asset_name']} (proximity {m['proximity']:.2f})" for m in event.impacted_assets or []],
        "verified_change": [c.statement for c in facts if c.section == "what_changed"],
        "why_flagged": why,
        "known": [c.statement for c in facts],
        "unknown": [c.statement for c in by_type.get("UNKNOWN", [])],
        "interpretation": [c.statement for c in by_type.get("INFERENCE", [])],
        "recommended_investigation": [c.statement for c in by_type.get("RECOMMENDED_INVESTIGATION", [])],
        "evidence": [f"{st}: {uri}" for st, uri in evidence if uri],
        "materiality": f"{event.materiality_score:.0f} / {event.band}",
        "review_status": f"{event.review_status}; evidence "
                         f"{'validated' if art and art.publishable else 'validation pending'}; "
                         f"{'analyst review pending' if event.review_status == 'Machine' else 'analyst reviewed'}",
        "update_summary": (event.update_summary or []) if prior_version else [],
        "link": f"{s.public_base_url}/events/{event.id}",
        "generated_at": datetime.now(UTC).isoformat(),
    }


def _enqueue(db: Session, policy: AlertPolicy, channel: str, events: list[IntelligenceEvent], payload: dict[str, Any],
             kind: str, dedupe_key: str) -> Notification | None:
    if db.scalar(select(Notification).where(Notification.tenant_id == policy.tenant_id,
                                            Notification.dedupe_key == dedupe_key)):
        return None
    n = Notification(tenant_id=policy.tenant_id, dedupe_key=dedupe_key, policy_id=policy.id, user_id=policy.owner_id,
                     intel_event_ids=[e.id for e in events], kind=kind, channel=channel,
                     status="pending", payload=payload, next_attempt_at=datetime.now(UTC))
    db.add(n)
    db.flush()
    return n


def _mark_notified(db: Session, policy: AlertPolicy, events: list[IntelligenceEvent]) -> None:
    for e in events:
        st = db.get(NotifiedEventState, (policy.tenant_id, policy.id, e.id))
        if st is None:
            db.add(NotifiedEventState(tenant_id=policy.tenant_id, policy_id=policy.id, intel_event_id=e.id,
                                      version=e.version))
        else:
            st.version, st.notified_at = e.version, datetime.now(UTC)
    db.flush()


def dispatch_immediate(db: Session, event: IntelligenceEvent) -> list[Notification]:
    policies = db.scalars(select(AlertPolicy).where(AlertPolicy.tenant_id == event.tenant_id,
                                                    AlertPolicy.active.is_(True),
                                                    AlertPolicy.cadence == "immediate")).all()
    created = []
    for p in policies:
        if not matches(db, p, event):
            continue
        prev = db.get(NotifiedEventState, (p.tenant_id, p.id, event.id))
        if prev and prev.version >= event.version:
            continue  # FR-ALT-005: no repeat unless materially updated
        payload = alert_payload(db, event, prior_version=prev.version if prev else None)
        for ch in p.channels or ["web"]:
            n = _enqueue(db, p, ch, [event], payload, "alert", f"alert:{p.id}:{event.id}:v{event.version}:{ch}")
            if n:
                created.append(n)
        _mark_notified(db, p, [event])
    if created and event.source_fetched_at:
        event.alert_eligible_at = event.alert_eligible_at or datetime.now(UTC)
        PIPELINE_LATENCY.labels("source_fetch_to_alert").observe(
            (event.alert_eligible_at - event.source_fetched_at).total_seconds())
    return created


def build_digests(db: Session, tenant_id: uuid.UUID, cadence: str, now: datetime | None = None) -> list[Notification]:
    now = now or datetime.now(UTC)
    window = timedelta(days=1 if cadence == "daily" else 7)
    created: list[Notification] = []
    for p in db.scalars(select(AlertPolicy).where(AlertPolicy.tenant_id == tenant_id, AlertPolicy.active.is_(True),
                                                  AlertPolicy.cadence == cadence)).all():
        since = p.last_digest_at or (now - window)
        candidates = db.scalars(select(IntelligenceEvent).where(
            IntelligenceEvent.tenant_id == tenant_id,
            IntelligenceEvent.updated_at > since,
            IntelligenceEvent.status.in_(("published", "acknowledged", "escalated")),
        ).order_by(IntelligenceEvent.materiality_score.desc())).all()
        ids = _policy_entity_ids(db, p)
        chosen, items = [], []
        for e in candidates:
            if not matches(db, p, e, ids):
                continue
            prev = db.get(NotifiedEventState, (p.tenant_id, p.id, e.id))
            if prev and prev.version >= e.version:
                continue  # already notified at this version
            chosen.append(e)
            items.append(alert_payload(db, e, prior_version=prev.version if prev else None))
        if chosen:
            period = f"{since.date().isoformat()}..{now.date().isoformat()}"
            payload = {"title": f"{cadence.capitalize()} intelligence digest ({len(chosen)} developments) {period}",
                       "items": items, "generated_at": now.isoformat()}
            for ch in p.channels or ["web"]:
                n = _enqueue(db, p, ch, chosen, payload, "digest", f"digest:{p.id}:{period}:{ch}")
                if n:
                    created.append(n)
            _mark_notified(db, p, chosen)
        p.last_digest_at = now
    db.flush()
    return created


def deliver_pending(db: Session, limit: int = 100) -> dict[str, int]:
    """Deliver due notifications with exponential-backoff retry; failures are logged (FR-ALT-004)."""
    now = datetime.now(UTC)
    rows = db.scalars(select(Notification).where(
        Notification.status.in_(("pending", "failed")),
        and_(Notification.next_attempt_at.is_not(None), Notification.next_attempt_at <= now),
    ).order_by(Notification.created_at).limit(limit).with_for_update(skip_locked=True)).all()
    stats = Counter()
    for n in rows:
        policy = db.get(AlertPolicy, n.policy_id) if n.policy_id else None
        dest = decrypt_json(policy.destinations_encrypted) if policy and policy.destinations_encrypted else {}
        if n.kind == "brief":
            dest = {"email": (n.payload or {}).get("recipients", [])}
        n.attempts += 1
        try:
            deliver(n.channel, dest or {}, n.payload)
            n.status, n.sent_at, n.next_attempt_at, n.last_error = "sent", now, None, None
            ALERT_DELIVERIES.labels(n.channel, "sent").inc()
            stats["sent"] += 1
        except (DeliveryError, KeyError, OSError) as e:
            n.last_error = str(e)[:500]
            if n.attempts >= MAX_ATTEMPTS:
                n.status, n.next_attempt_at = "dead", None
                ALERT_DELIVERIES.labels(n.channel, "dead").inc()
                stats["dead"] += 1
            else:
                n.status = "failed"
                n.next_attempt_at = now + timedelta(minutes=2 ** n.attempts)
                ALERT_DELIVERIES.labels(n.channel, "retry").inc()
                stats["retry"] += 1
            log.warning("alert_delivery_failed", channel=n.channel, attempts=n.attempts, error=n.last_error)
    db.flush()
    return dict(stats)
