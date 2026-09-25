"""Connector health / source freshness (FR-SRC-007, NFR-REL-001, US-008)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ConnectorConfig, ConnectorRun


def connector_health(db: Session) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    out = []
    for c in db.scalars(select(ConnectorConfig).order_by(ConnectorConfig.key)).all():
        last = db.scalar(select(ConnectorRun).where(ConnectorRun.connector_key == c.key)
                         .order_by(ConnectorRun.started_at.desc()).limit(1))
        recent_failures = db.scalar(select(func.count()).select_from(ConnectorRun).where(
            ConnectorRun.connector_key == c.key, ConnectorRun.status == "failed",
            ConnectorRun.started_at >= func.now() - func.make_interval(0, 0, 1))) or 0
        age_h = (now - c.last_success_at).total_seconds() / 3600 if c.last_success_at else None
        if not c.enabled:
            state = "disabled"
        elif c.last_success_at is None:
            state = "never_run"
        elif age_h is not None and age_h > c.freshness_slo_hours:
            state = "stale"
        elif last is not None and last.status == "failed":
            state = "failing"
        elif last is not None and last.status == "partial":
            state = "degraded"
        else:
            state = "healthy"
        out.append({
            "key": c.key, "display_name": c.display_name, "enabled": c.enabled, "adapter_version": c.adapter_version,
            "schedule_cron": c.schedule_cron, "rate_limit_per_sec": c.rate_limit_per_sec,
            "freshness_slo_hours": c.freshness_slo_hours,
            "last_success_at": c.last_success_at.isoformat() if c.last_success_at else None,
            "next_run_at": c.next_run_at.isoformat() if c.next_run_at else None,
            "hours_since_success": round(age_h, 1) if age_h is not None else None,
            "state": state, "stale": state in ("stale", "never_run", "failing"),
            "failures_last_7d": recent_failures,
            "last_run": {"id": str(last.id), "status": last.status, "started_at": last.started_at.isoformat(),
                         "finished_at": last.finished_at.isoformat() if last.finished_at else None,
                         "records_fetched": last.records_fetched, "records_new": last.records_new,
                         "records_changed": last.records_changed, "changes_emitted": last.changes_emitted,
                         "errors": last.errors, "message": last.message} if last else None,
            "settings": c.settings,
        })
    return out


def health_summary(db: Session) -> dict[str, Any]:
    h = connector_health(db)
    return {"connectors": len(h), "healthy": sum(1 for x in h if x["state"] == "healthy"),
            "stale_or_failing": [{"key": x["key"], "display_name": x["display_name"], "state": x["state"],
                                  "hours_since_success": x["hours_since_success"]} for x in h if x["stale"] and x["enabled"]],
            "banner": ("Some sources are stale or failing; intelligence may be incomplete."
                       if any(x["stale"] and x["enabled"] for x in h) else None)}
