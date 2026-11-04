"""Collection runner: serialised writers, run bookkeeping, freshness after rollbacks, offline vs
host-specific failures."""
from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import date, timedelta

import httpx
import pytest
import respx
from sqlalchemy import event, select
from sqlalchemy.exc import OperationalError

from paladex.api.common import freshness
from paladex.collectors import base, runner
from paladex.collectors.base import Collector
from paladex.enums import PriceType, Reliability, SourceKind
from paladex.models import CollectionRun, DataQualityIssue, PriceObservation, Source, utcnow
from paladex.services import quality


class _TestCollector(Collector):
    publisher = "Test"
    homepage = "https://example.org"
    kind = SourceKind.API
    reliability = Reliability.OFFICIAL
    category = "prices"

    def collect(self, ctx):  # pragma: no cover - overridden
        raise NotImplementedError


def _register(db, monkeypatch, *collectors: Collector) -> None:
    """Make `run_collector` find these collectors and give each a Source row."""
    by_key = {c.key: c for c in collectors}
    real = runner.get_collector
    monkeypatch.setattr(runner, "get_collector", lambda key: by_key.get(key) or real(key))
    for c in collectors:
        db.add(Source(key=c.key, name=c.key, publisher="Test", homepage="https://example.org", kind="api",
                      reliability="official", category="prices", expected_max_age_days=30, enabled=True))
    db.commit()


def _price(ctx, label: str, start: date, end: date, published: date, freq: str = "M") -> None:
    ctx.add_price(series_key=f"ARG|polyflora|{label}", price_type=PriceType.WHOLESALE_BULK, variety="polyflora",
                  price_value=5.0, currency="EUR", unit="kg", period_start=start, period_end=end,
                  period_label=label, frequency=freq, origin_iso3="ARG", published_at=published)


def _runs(session_factory) -> dict[str, CollectionRun]:
    with session_factory() as s:
        return {s.get(Source, r.source_id).key: r for r in s.scalars(select(CollectionRun))}


# ------------------------------------------------------------------------- F1 locking
def test_overlapping_collections_wait_instead_of_failing(db, monkeypatch, session_factory):
    """Collector A keeps its write transaction open across paced downloads; collector B, started
    meanwhile by another thread (scheduler job, start-up catch-up), must wait for it rather than
    fail with 'database is locked' and lose its run."""
    from paladex import db as dbmod

    started = threading.Event()

    class Slow(_TestCollector):
        key, name = "t_slow", "Slow"

        def collect(self, ctx):
            ctx.store_raw("https://example.org/page-1", b"page 1")   # write transaction open from here
            started.set()
            time.sleep(1.0)                                          # ... still paging before its checkpoint

    class Quick(_TestCollector):
        key, name = "t_quick", "Quick"

        def collect(self, ctx):
            pass

    _register(db, monkeypatch, Slow(), Quick())
    # SQLite gives up after busy_timeout (shortened here so the test is fast), and the lock alone
    # must do the job: no retry of the bookkeeping in this test.
    engine = dbmod.get_engine()
    event.listen(engine, "connect", lambda conn, _rec: conn.execute("PRAGMA busy_timeout=200"))
    engine.dispose()
    monkeypatch.setattr(runner, "_retry_if_locked", lambda fn, what, **kw: fn(), raising=False)

    out: dict = {}
    t = threading.Thread(target=lambda: out.update(slow=runner.run_collector("t_slow", trigger="test")))
    t.start()
    assert started.wait(5)
    quick = runner.run_collector("t_quick", trigger="schedule")
    t.join(10)

    assert quick["status"] == "no_change" and out["slow"]["status"] == "no_change"
    runs = _runs(session_factory)
    assert runs["t_quick"].status == "no_change" and runs["t_slow"].status == "no_change"
    assert runs["t_quick"].started_at >= runs["t_slow"].finished_at   # serialised, not interleaved


def test_run_bookkeeping_survives_a_locked_database(db, monkeypatch, session_factory):
    """An API write holding the database when a run starts or ends must not make the run vanish
    (no row) or stay 'running' forever."""

    class Quick(_TestCollector):
        key, name = "t_quick", "Quick"

        def collect(self, ctx):
            pass

    _register(db, monkeypatch, Quick())
    real = runner.session_scope
    calls = {"n": 0}

    @contextmanager
    def flaky_scope():
        calls["n"] += 1
        if calls["n"] in (1, 4):   # creating the run row, then recording its end
            raise OperationalError("INSERT ...", {}, sqlite3.OperationalError("database is locked"))
        with real() as s:
            yield s

    monkeypatch.setattr(runner, "session_scope", flaky_scope)
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    res = runner.run_collector("t_quick", trigger="test")
    assert res["status"] == "no_change"
    run = _runs(session_factory)["t_quick"]
    assert run.status == "no_change" and run.finished_at is not None


def test_fx_backfill_failure_does_not_skip_the_other_hooks(db, monkeypatch):
    from paladex.services import fx

    def boom(session, *a, **k):
        raise OperationalError("UPDATE price_observations", {}, sqlite3.OperationalError("database is locked"))

    called = []
    monkeypatch.setattr(fx, "backfill_normalised_prices", boom)
    monkeypatch.setattr(quality, "run_checks", lambda session, **k: called.append("quality"))
    runner.post_collection_hooks()
    assert called == ["quality"]


def test_interrupted_runs_are_closed_at_start_up(db, session_factory):
    from paladex import scheduler

    src = db.scalars(select(Source).where(Source.key == "ecb_fx")).one()
    db.add(CollectionRun(source_id=src.id, status="running", trigger="schedule", started_at=utcnow() - timedelta(hours=2)))
    db.commit()
    scheduler.start()   # scheduler disabled in tests: only the start-up clean-up runs
    run = _runs(session_factory)["ecb_fx"]
    assert run.status == "failed" and run.finished_at is not None
    assert run.error.startswith("interrupted")
    assert "interrotto" in quality.explain_error(run.error)["it"]


# ------------------------------------------------------------- F2 freshness after rollback
def test_rolled_back_rows_do_not_make_the_source_look_current(db, monkeypatch, session_factory):
    class Drift(_TestCollector):
        key, name = "t_drift", "Drift"

        def collect(self, ctx):
            _price(ctx, "2026-09", date(2026, 9, 1), date(2026, 9, 30), published=date(2026, 10, 2))
            ctx.checkpoint()   # September is safely stored
            _price(ctx, "2026-10", date(2026, 10, 1), date(2026, 10, 31), published=date(2026, 11, 2))
            raise ValueError("format drift on page 2")   # October is rolled back

    _register(db, monkeypatch, Drift())
    res = runner.run_collector("t_drift", trigger="test")
    assert res["status"] == "failed" and res["new"] == 1
    with session_factory() as s:
        assert [p.period_label for p in s.scalars(select(PriceObservation))] == ["2026-09"]
        src = s.scalars(select(Source).where(Source.key == "t_drift")).one()
        assert src.latest_published_at == date(2026, 10, 2)
        assert src.latest_period_label == "2026-09"
        assert freshness(src, today=date(2026, 11, 4))["reference_date"] == "2026-10-02"


def test_failure_before_any_checkpoint_leaves_freshness_untouched(db, monkeypatch, session_factory):
    class Drift(_TestCollector):
        key, name = "t_drift", "Drift"

        def collect(self, ctx):
            _price(ctx, "2026-10", date(2026, 10, 1), date(2026, 10, 31), published=date(2026, 11, 2))
            raise ValueError("format drift")

    _register(db, monkeypatch, Drift())
    assert runner.run_collector("t_drift", trigger="test")["status"] == "failed"
    with session_factory() as s:
        assert s.scalars(select(PriceObservation)).first() is None
        src = s.scalars(select(Source).where(Source.key == "t_drift")).one()
        assert src.latest_published_at is None and src.latest_period_label is None
        assert freshness(src, today=date(2026, 11, 4))["status"] == "never"


def test_latest_period_label_never_moves_backwards(db, monkeypatch, session_factory):
    periods = [("2026-09", date(2026, 9, 1), date(2026, 9, 30), "M"),
               ("2023", date(2023, 1, 1), date(2023, 12, 31), "A")]   # e.g. a re-released year only

    class Lists(_TestCollector):
        key, name = "t_lists", "Lists"

        def collect(self, ctx):
            label, start, end, freq = periods.pop(0)
            _price(ctx, label, start, end, published=date(2026, 10, 15), freq=freq)

    _register(db, monkeypatch, Lists())
    assert runner.run_collector("t_lists", trigger="test")["status"] == "success"
    assert runner.run_collector("t_lists", trigger="test")["status"] == "success"
    with session_factory() as s:
        src = s.scalars(select(Source).where(Source.key == "t_lists")).one()
        assert src.latest_period_label == "2026-09" and src.latest_period_start == date(2026, 9, 1)


# --------------------------------------------------------- F3 offline vs host unreachable
CERT_ERROR = "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate"


def _run_ecb_failing(monkeypatch, online: bool) -> dict:
    monkeypatch.setattr(base.time, "sleep", lambda *_: None)
    monkeypatch.setattr(runner, "is_online", lambda *a, **k: online)
    with respx.mock() as mock:
        mock.route().mock(side_effect=httpx.ConnectError(CERT_ERROR))
        with httpx.Client() as client:
            return runner.run_collector("ecb_fx", trigger="test", client=client)


def test_unreachable_host_while_online_is_a_failure(db, monkeypatch, session_factory):
    res = _run_ecb_failing(monkeypatch, online=True)
    assert res["status"] == "failed"
    assert "internet connection works" in res["error"]
    with session_factory() as s:
        quality.run_checks(s)
    with session_factory() as s:
        issue = s.scalars(select(DataQualityIssue).where(DataQualityIssue.dedup_key == "collect:ecb_fx")).one()
        assert issue.issue_type == "collection_failed" and issue.resolved_at is None
        assert "certificato di sicurezza" in issue.message_it
        src = s.scalars(select(Source).where(Source.key == "ecb_fx")).one()
        assert src.last_run_status == "failed"


def test_no_internet_stays_offline_and_raises_no_issue(db, monkeypatch, session_factory):
    res = _run_ecb_failing(monkeypatch, online=False)
    assert res["status"] == "offline"
    with session_factory() as s:
        quality.run_checks(s)
    with session_factory() as s:
        assert s.scalars(select(DataQualityIssue).where(DataQualityIssue.dedup_key == "collect:ecb_fx")).first() is None


@pytest.mark.parametrize("error, word", [
    ("Host unreachable while the internet connection works: Cannot reach x.org: [Errno -2] Name or service not known",
     "non esiste più"),
    ("Host unreachable while the internet connection works: Cannot reach x.org: [Errno 111] Connection refused",
     "la connessione internet funziona"),
    ("HTTP 404 for https://example.org/classlist/health-certificate.pdf", "non si trova più"),
])
def test_explain_error_names_the_precise_reason(error, word):
    assert word in quality.explain_error(error)["it"]
