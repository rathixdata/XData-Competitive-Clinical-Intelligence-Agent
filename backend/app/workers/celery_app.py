"""Celery application: horizontally scalable workers for connectors, event processing, generation and
alert delivery (NFR-SCL-001). Separate queues let each stage scale independently."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

s = get_settings()
celery_app = Celery("xdata", broker=s.broker_url, backend=s.result_backend, include=["app.workers.tasks"])
celery_app.conf.update(
    task_default_queue="default",
    task_routes={
        "app.workers.tasks.run_connector_task": {"queue": "ingest"},
        "app.workers.tasks.process_changes_task": {"queue": "intel"},
        "app.workers.tasks.deliver_alerts_task": {"queue": "alerts"},
        "app.workers.tasks.digest_task": {"queue": "alerts"},
    },
    task_acks_late=True,  # at-least-once; every task is idempotent
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=60 * 60,
    task_soft_time_limit=55 * 60,
    broker_transport_options={"visibility_timeout": 2 * 60 * 60},
    result_expires=24 * 3600,
    timezone="UTC",
    task_always_eager=s.celery_eager,
    beat_schedule={
        # The dispatcher checks each connector's cron and enqueues due runs (schedules are DB-configurable).
        "dispatch-due-connectors": {"task": "app.workers.tasks.dispatch_due_connectors", "schedule": 60.0},
        # High-priority structured changes must reach alert eligibility within 15 minutes (NFR-ALT-001).
        "process-changes": {"task": "app.workers.tasks.process_changes_task", "schedule": 60.0},
        "deliver-alerts": {"task": "app.workers.tasks.deliver_alerts_task", "schedule": 30.0},
        "daily-digests": {"task": "app.workers.tasks.digest_task", "schedule": crontab(hour=6, minute=5),
                          "args": ["daily"]},
        "weekly-digests": {"task": "app.workers.tasks.digest_task", "schedule": crontab(hour=6, minute=15, day_of_week=1),
                           "args": ["weekly"]},
        "retention-purge": {"task": "app.workers.tasks.retention_task", "schedule": crontab(hour=3, minute=30)},
    },
)
