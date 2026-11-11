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


def test_a_source_never_read_is_collected_at_start_even_after_a_recent_collection(db, monkeypatch):
    """A new version brings a new source two hours after the last collection: it is read at once,
    alone, instead of waiting for its weekly schedule."""
    from paladex.api import meta
    from paladex.models import Source, utcnow

    class _New:
        key = "t_new_source"
        schedule = {"trigger": "interval", "weeks": 1}

    class _Old(_New):
        key = "t_old_source"

    class _Off(_New):
        key = "t_off_source"

    for key, last, enabled in (("t_new_source", None, True), ("t_old_source", utcnow(), True), ("t_off_source", None, False)):
        db.add(Source(key=key, name=key, kind="api", reliability="official", category="prices", enabled=enabled, last_run_at=last))
    db.commit()
    monkeypatch.setenv("PALADEX_SCHEDULER_ENABLED", "true")
    config.get_settings.cache_clear()
    monkeypatch.setattr(scheduler, "_job", lambda key, attempt=0: None)
    monkeypatch.setattr(scheduler, "all_collectors", lambda: [_Old(), _New(), _Off()])
    monkeypatch.setattr(runner, "last_full_run_age_hours", lambda: 2.0)
    started: list = []
    monkeypatch.setattr(meta, "start_collection", lambda keys=None, force=False, trigger="manual": started.append((keys, trigger)) or True)
    assert scheduler.never_collected_keys() == ["t_new_source"]
    try:
        assert scheduler.start() is not None
    finally:
        scheduler.shutdown()
        config.get_settings.cache_clear()
    assert started == [(["t_new_source"], "startup")]


def test_the_page_is_always_checked_with_the_server_so_an_update_shows_at_once(db, tmp_path, monkeypatch):
    """index.html names the script files of the current build: a browser must ask for it at every
    visit (no-cache), or it goes on showing the previous version after an update."""
    from fastapi.testclient import TestClient

    from paladex.main import create_app

    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>Paladex</title>", encoding="utf-8")
    (tmp_path / "assets" / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setenv("PALADEX_FRONTEND_DIST", str(tmp_path))
    config.get_settings.cache_clear()
    try:
        client = TestClient(create_app(start_scheduler=False), base_url="http://127.0.0.1:8765")
        for path in ("/", "/prezzi", "/paesi/DEU"):
            r = client.get(path)
            assert r.status_code == 200 and "Paladex" in r.text and r.headers["cache-control"] == "no-cache", path
        assert client.get("/assets/index-abc123.js").status_code == 200
    finally:
        config.get_settings.cache_clear()
