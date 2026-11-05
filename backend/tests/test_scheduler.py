"""Scheduler: jobs missed while the PC slept run once on wake; offline runs are retried."""
from __future__ import annotations

import threading
from datetime import datetime, timedelta

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MISSED
from apscheduler.schedulers.background import BackgroundScheduler

from paladex import config, scheduler
from paladex.collectors import runner


class _Weekly:
    key = "t_weekly"
    schedule = {"trigger": "interval", "weeks": 1}   # like Comtrade's Sunday job: one fire per week


def test_job_missed_by_27_hours_runs_on_wake(db, monkeypatch):
    """The PC slept from Friday evening to Monday morning with the app open: the weekly job is
    ~27 h late and must still run once, not be dropped as 'missed'."""
    monkeypatch.setenv("PALADEX_SCHEDULER_ENABLED", "true")
    config.get_settings.cache_clear()
    ran = threading.Event()
    monkeypatch.setattr(scheduler, "_job", lambda key, attempt=0: ran.set())
    monkeypatch.setattr(scheduler, "all_collectors", lambda: [_Weekly()])
    monkeypatch.setattr(runner, "last_full_run_age_hours", lambda: 0.0)   # no start-up catch-up
    events: list[int] = []
    done = threading.Event()

    sched = scheduler.start()
    try:
        assert sched is not None

        def listener(ev):
            if ev.job_id == "collect:t_weekly":
                events.append(ev.code)
                done.set()

        sched.add_listener(listener, EVENT_JOB_EXECUTED | EVENT_JOB_MISSED | EVENT_JOB_ERROR)
        sched.modify_job("collect:t_weekly", next_run_time=datetime.now(sched.timezone) - timedelta(hours=27))
        assert done.wait(10)
    finally:
        scheduler.shutdown()
        config.get_settings.cache_clear()
    assert events == [EVENT_JOB_EXECUTED] and ran.is_set()


def test_offline_job_is_retried_instead_of_dropped(monkeypatch):
    sched = BackgroundScheduler(timezone="Europe/Rome")     # not started: added jobs stay pending
    monkeypatch.setattr(scheduler, "_scheduler", sched)
    monkeypatch.setattr(runner, "is_online", lambda *a, **k: False)
    ran: list = []
    monkeypatch.setattr(runner, "run_collector", lambda *a, **k: ran.append(a))

    scheduler._job("ecb_fx")
    jobs = sched.get_jobs()
    assert len(jobs) == 1 and jobs[0].id.startswith("retry:ecb_fx") and tuple(jobs[0].args) == ("ecb_fx", 1)
    assert jobs[0].misfire_grace_time is None and not ran

    # retries are bounded
    scheduler._job("ecb_fx", scheduler.OFFLINE_MAX_RETRIES)
    assert len(sched.get_jobs()) == 1


def test_collector_jobs_have_no_misfire_limit():
    kw = scheduler.collector_job_kwargs(_Weekly())
    assert kw["misfire_grace_time"] is None and kw["coalesce"] is True and kw["id"] == "collect:t_weekly"
