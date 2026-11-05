"""Background scheduling of collectors (APScheduler, in-process).

Each collector declares its own schedule. Jobs coalesce and never overlap. A collector job
missed while the computer was asleep (an office PC sleeping overnight or over a weekend, with
the app left open) runs exactly once when it wakes, however late: collector jobs have no misfire
limit (`misfire_grace_time=None`) and coalesce. Only the daily briefing keeps a bounded grace
(a stale briefing is not wanted). If the PC is offline when a job fires (typically right after
waking, before the network is up) the run is retried every 15 minutes, up to 8 times, instead of
being dropped until the next scheduled time. A start-up catch-up run is triggered when the last
collection is older than `startup_collect_if_older_than_hours`, and runs left 'running' by a
previous process are recorded as interrupted.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from .collectors.registry import all_collectors
from .config import get_settings

log = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None

TIMEZONE = "Europe/Rome"
JOB_DEFAULTS = {"coalesce": True, "max_instances": 1, "misfire_grace_time": 6 * 3600}
OFFLINE_RETRY_MINUTES = 15
OFFLINE_MAX_RETRIES = 8


def collector_job_kwargs(c) -> dict:
    """APScheduler `add_job` arguments for a collector's recurring job."""
    spec = dict(c.schedule)
    trigger = spec.pop("trigger", "interval")
    # No lateness limit: a run missed during sleep happens once on wake (coalesce=True).
    return {"func": _job, "trigger": trigger, "args": [c.key], "id": f"collect:{c.key}",
            "replace_existing": True, "coalesce": True, "misfire_grace_time": None, **spec}


def _schedule_offline_retry(key: str, attempt: int) -> bool:
    if _scheduler is None or attempt >= OFFLINE_MAX_RETRIES:
        return False
    # One id per attempt: APScheduler removes a fired one-off job right after submitting it, so
    # re-using the id of the job now running could remove the retry just added.
    _scheduler.add_job(
        _job, "date", run_date=datetime.now(_scheduler.timezone) + timedelta(minutes=OFFLINE_RETRY_MINUTES),
        args=[key, attempt + 1], id=f"retry:{key}:{attempt + 1}", replace_existing=True, misfire_grace_time=None,
    )
    return True


def _job(key: str, attempt: int = 0) -> None:
    from .collectors.runner import is_online, post_collection_hooks, run_collector

    if not is_online():
        if _schedule_offline_retry(key, attempt):
            log.info("offline: scheduled run of %s retried in %s min (attempt %s/%s)",
                     key, OFFLINE_RETRY_MINUTES, attempt + 1, OFFLINE_MAX_RETRIES)
        else:
            log.info("offline: skipping scheduled run of %s until its next scheduled time", key)
        return
    run_collector(key, trigger="schedule")
    post_collection_hooks()


def _daily_briefing() -> None:
    try:
        from .services.briefing import generate_daily
    except ImportError:
        return
    from .db import session_scope

    with session_scope() as s:
        generate_daily(s)


def start() -> BackgroundScheduler | None:
    global _scheduler
    settings = get_settings()
    if _scheduler is not None:
        return _scheduler
    from .collectors.runner import fail_interrupted_runs, last_full_run_age_hours

    # Measured before closing interrupted runs, which get finished_at = now.
    age = last_full_run_age_hours() if settings.scheduler_enabled else None
    try:
        fail_interrupted_runs()   # left 'running' by a previous process
    except Exception:  # pragma: no cover - never block start-up
        log.exception("could not close interrupted collection runs")
    if not settings.scheduler_enabled:
        return None
    sched = BackgroundScheduler(job_defaults=dict(JOB_DEFAULTS), timezone=TIMEZONE)
    for c in all_collectors():
        sched.add_job(**collector_job_kwargs(c))
    sched.add_job(_daily_briefing, "cron", hour=7, minute=0, id="briefing", replace_existing=True)
    sched.start()
    _scheduler = sched

    from .api.meta import start_collection

    if age is None or age > settings.startup_collect_if_older_than_hours:
        log.info("start-up catch-up collection (last run age: %s h)", age)
        start_collection(trigger="startup")
    return sched


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def jobs() -> list[dict]:
    if _scheduler is None:
        return []
    return [{"id": j.id, "next_run": j.next_run_time.isoformat() if j.next_run_time else None} for j in _scheduler.get_jobs()]
