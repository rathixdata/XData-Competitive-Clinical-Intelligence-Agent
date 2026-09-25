"""Background tasks. Every task is idempotent so retries / duplicate deliveries are safe (FR-CHG-006)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, text

from app.alerts.dispatcher import build_digests, deliver_pending
from app.core.logging import configure_logging, get_logger
from app.core.metrics import QUEUE_TASKS
from app.db.session import session_scope
from app.models import (
    AskSession,
    ConnectorConfig,
    GeneratedArtifact,
    GenerationRecord,
    Notification,
    Tenant,
    UsageRecord,
)
from app.pipeline.ingest import ensure_connector_configs, run_connector
from app.pipeline.intelligence import process_pending_changes
from app.workers.celery_app import celery_app

configure_logging()
log = get_logger(__name__)


def _lock(db, name: str) -> bool:  # type: ignore[no-untyped-def]
    """Transaction-scoped advisory lock: prevents overlapping runs across worker replicas."""
    return bool(db.execute(text("SELECT pg_try_advisory_xact_lock(hashtext(:n))"), {"n": name}).scalar())


@celery_app.task(bind=True, max_retries=3, default_retry_delay=300)
def run_connector_task(self, key: str, trigger: str = "schedule", requested_by: str | None = None) -> str:  # type: ignore[no-untyped-def]
    try:
        run_id = run_connector(key, trigger=trigger, requested_by=requested_by)
        QUEUE_TASKS.labels("run_connector", "ok").inc()
        process_changes_task.apply_async(queue="intel")
        return str(run_id)
    except Exception as e:
        QUEUE_TASKS.labels("run_connector", "error").inc()
        log.exception("connector_task_failed", connector=key)
        raise self.retry(exc=e) from e


@celery_app.task
def dispatch_due_connectors() -> list[str]:
    due = []
    with session_scope(bypass_rls=True) as db:
        ensure_connector_configs(db)
        if not _lock(db, "dispatch_due_connectors"):
            return []
        now = datetime.now(UTC)
        for c in db.scalars(select(ConnectorConfig).where(ConnectorConfig.enabled.is_(True))).all():
            if c.next_run_at is None or c.next_run_at <= now:
                from croniter import croniter

                c.next_run_at = croniter(c.schedule_cron, now).get_next(datetime)
                due.append(c.key)
    for key in due:
        run_connector_task.apply_async(args=[key], queue="ingest")
    return due


@celery_app.task
def process_changes_task() -> dict[str, Any]:
    with session_scope(bypass_rls=True) as db:
        if not _lock(db, "process_changes"):
            return {"skipped": "locked"}
        stats = process_pending_changes()
    QUEUE_TASKS.labels("process_changes", "ok").inc()
    if stats.get("events"):
        deliver_alerts_task.apply_async(queue="alerts")
    return stats


@celery_app.task
def deliver_alerts_task() -> dict[str, int]:
    with session_scope(bypass_rls=True) as db:
        return deliver_pending(db)


@celery_app.task
def digest_task(cadence: str) -> int:
    n = 0
    with session_scope(bypass_rls=True) as db:
        tenant_ids = db.scalars(select(Tenant.id).where(Tenant.status == "active")).all()
    for tid in tenant_ids:
        with session_scope(tid) as db:
            n += len(build_digests(db, tid, cadence))
    deliver_alerts_task.apply_async(queue="alerts")
    return n


@celery_app.task
def retention_task() -> dict[str, int]:
    """Purge data classes per tenant retention policy (NFR-PRV-001). Audit log and raw artifacts are exempt."""
    defaults = {"ask_sessions": 365, "notifications": 180, "generation_records": 730, "usage_records": 730}
    stats: dict[str, int] = {}
    with session_scope(bypass_rls=True) as db:
        tenants = db.scalars(select(Tenant)).all()
        for t in tenants:
            cfg = {**defaults, **((t.settings or {}).get("retention_days") or {})}
            now = datetime.now(UTC)
            for model, cls, col in (("ask_sessions", AskSession, AskSession.updated_at),
                                    ("notifications", Notification, Notification.created_at),
                                    ("usage_records", UsageRecord, UsageRecord.created_at)):
                res = db.execute(delete(cls).where(cls.tenant_id == t.id, col < now - timedelta(days=int(cfg[model]))))
                stats[model] = stats.get(model, 0) + (res.rowcount or 0)
            # Generation records backing still-referenced artifacts are retained for auditability.
            res = db.execute(delete(GenerationRecord).where(
                GenerationRecord.tenant_id == t.id,
                GenerationRecord.created_at < now - timedelta(days=int(cfg["generation_records"])),
                ~GenerationRecord.id.in_(select(GeneratedArtifact.generation_id).where(
                    GeneratedArtifact.generation_id.is_not(None)))))
            stats["generation_records"] = stats.get("generation_records", 0) + (res.rowcount or 0)
    return stats
