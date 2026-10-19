"""In-process scheduler for single-service deployments (XDATA_INPROCESS_SCHEDULER=true).

Runs the same periodic jobs as Celery beat (see app/workers/celery_app.py) in a daemon thread of the API
process. Tasks execute eagerly (XDATA_CELERY_EAGER=true), so no broker or worker process is needed. The
tasks take Postgres advisory locks, so running several API replicas stays safe.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

from app.core.logging import get_logger

log = get_logger(__name__)

_stop = threading.Event()
_thread: threading.Thread | None = None


def _jobs() -> list[tuple[str, float, Callable[[], object]]]:
    from app.workers import tasks

    return [
        ("dispatch_due_connectors", 60, tasks.dispatch_due_connectors),
        ("process_changes", 60, tasks.process_changes_task),
        ("deliver_alerts", 30, tasks.deliver_alerts_task),
    ]


def _daily_jobs() -> list[tuple[str, int, int, int | None, Callable[[], object]]]:
    from app.workers import tasks

    # name, hour, minute, weekday (Mon=0) or None, fn - same times as the beat schedule (UTC)
    return [
        ("daily_digests", 6, 5, None, lambda: tasks.digest_task("daily")),
        ("weekly_digests", 6, 15, 0, lambda: tasks.digest_task("weekly")),
        ("retention_purge", 3, 30, None, tasks.retention_task),
    ]


def _run(name: str, fn: Callable[[], object]) -> None:
    try:
        result = fn()
        if result:
            log.info("scheduler_job", job=name, result=str(result)[:300])
    except Exception as e:  # noqa: BLE001 - one failing job must not stop the loop
        log.exception("scheduler_job_failed", job=name, error=str(e))


def _loop(initial_delay: float) -> None:
    jobs = _jobs()
    daily = _daily_jobs()
    last: dict[str, float] = {}
    # A restart after today's slot has passed must not re-run today's daily jobs (e.g. re-send digests).
    start_utc = datetime.now(UTC)
    last_day: dict[str, str] = {name: start_utc.date().isoformat() for name, hour, minute, _w, _f in daily
                                if (start_utc.hour, start_utc.minute) >= (hour, minute)}
    if _stop.wait(initial_delay):
        return
    while not _stop.is_set():
        now = time.monotonic()
        for name, every, fn in jobs:
            if now - last.get(name, 0.0) >= every:
                last[name] = now
                _run(name, fn)
        utc = datetime.now(UTC)
        for name, hour, minute, weekday, fn in daily:
            stamp = utc.date().isoformat()
            due = (utc.hour, utc.minute) >= (hour, minute) and (weekday is None or utc.weekday() == weekday)
            if due and last_day.get(name) != stamp:
                last_day[name] = stamp
                _run(name, fn)
        _stop.wait(5)


def start(initial_delay: float = 5.0) -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, args=(initial_delay,), name="xdata-scheduler", daemon=True)
    _thread.start()
    log.info("scheduler_started")


def stop() -> None:
    _stop.set()
