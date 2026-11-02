"""Background scheduling of collectors (APScheduler, in-process).

Each collector declares its own schedule. Jobs coalesce and never overlap; if the computer
was asleep the job runs once when it wakes (misfire grace 6 h). A start-up catch-up run is
triggered when the last collection is older than `startup_collect_if_older_than_hours`.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from .collectors.registry import all_collectors
from .config import get_settings

log = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None


def _job(key: str) -> None:
    from .collectors.runner import is_online, post_collection_hooks, run_collector

    if not is_online():
        log.info("offline: skipping scheduled run of %s", key)
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
    if not settings.scheduler_enabled or _scheduler is not None:
        return _scheduler
    sched = BackgroundScheduler(
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 6 * 3600},
        timezone="Europe/Rome",
    )
    for c in all_collectors():
        spec = dict(c.schedule)
        trigger = spec.pop("trigger", "interval")
        sched.add_job(_job, trigger, args=[c.key], id=f"collect:{c.key}", replace_existing=True, **spec)
    sched.add_job(_daily_briefing, "cron", hour=7, minute=0, id="briefing", replace_existing=True)
    sched.start()
    _scheduler = sched

    from .collectors.runner import last_full_run_age_hours
    from .api.meta import start_collection

    age = last_full_run_age_hours()
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
