"""Run collectors, record CollectionRun rows, keep Source status up to date."""
from __future__ import annotations

import logging
import threading
import time
import traceback
from collections.abc import Callable
from datetime import timedelta
from typing import TypeVar

import httpx
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError

from ..config import get_settings
from ..db import session_scope
from ..enums import RunStatus
from ..models import CollectionRun, Source, utcnow
from .base import CollectContext, Collector, CollectorError, MissingKey, Offline, RunCounters
from .registry import all_collectors, get_collector

log = logging.getLogger(__name__)

# One collection at a time per source (scheduler + manual button can overlap).
_locks: dict[str, threading.Lock] = {}
_global_lock = threading.Lock()

# One SQLite writer at a time among collectors and the post-collection hooks. A collector keeps
# its write transaction open from the first archived download until its next checkpoint, across
# several (paced) HTTP calls; SQLite allows a single writer, so a second collector started
# meanwhile by the scheduler, the start-up catch-up or the "Aggiorna dati" button would otherwise
# fail with "database is locked" after the busy timeout and lose its run. Waiting is fine: every
# caller runs on a worker thread (scheduler pool, collect thread, CLI). Re-entrant so a caller may
# hold it across a collection and its hooks.
_write_lock = threading.RLock()

INTERRUPTED_ERROR = "interrupted (app stopped or database locked)"

_T = TypeVar("_T")


def _retry_if_locked(fn: Callable[[], _T], what: str, attempts: int = 4, delay: float = 2.0) -> _T:
    """Run `fn` (one short transaction), retrying a few times when SQLite reports the database as
    locked by another writer (e.g. an API request), so run bookkeeping is not lost."""
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == attempts:
                raise
            log.warning("database locked while %s (attempt %s/%s); retrying", what, attempt, attempts)
            time.sleep(delay * attempt)
    raise AssertionError("unreachable")  # pragma: no cover


def _lock_for(key: str) -> threading.Lock:
    with _global_lock:
        return _locks.setdefault(key, threading.Lock())


CONNECTIVITY_PROBES = ("https://www.ecb.europa.eu", "https://www.usda.gov", "https://www.google.com")


def is_online(timeout: float = 6.0) -> bool:
    for url in CONNECTIVITY_PROBES:
        try:
            httpx.head(url, timeout=timeout, follow_redirects=False)
            return True
        except httpx.HTTPError:
            continue
    return False


def run_collector(key: str, *, trigger: str = "manual", force: bool = False, client: httpx.Client | None = None) -> dict:
    collector = get_collector(key)
    if collector is None:
        raise KeyError(key)
    lock = _lock_for(key)
    if not lock.acquire(blocking=False):
        return {"source": key, "status": "already_running"}
    try:
        with _write_lock:
            return _run(collector, trigger=trigger, force=force, client=client)
    finally:
        lock.release()


def _open_run(collector: Collector, trigger: str) -> tuple[int, int] | None:
    """Create the CollectionRun row. Returns (source_id, run_id), or None if the source is disabled."""
    with session_scope() as session:
        source = session.scalars(select(Source).where(Source.key == collector.key)).one()
        if not source.enabled:
            return None
        run = CollectionRun(source_id=source.id, status=RunStatus.RUNNING.value, trigger=trigger, started_at=utcnow())
        session.add(run)
        session.flush()
        return source.id, run.id


def _finish_run(run_id: int, status: RunStatus, error: str | None, counters: RunCounters) -> None:
    with session_scope() as session:
        run = session.get(CollectionRun, run_id)
        source = session.get(Source, run.source_id)
        now = utcnow()
        run.finished_at = now
        run.status = status.value
        run.items_seen = counters.seen
        run.items_new = counters.new
        run.items_revised = counters.revised
        run.warnings = counters.warnings or None
        run.error = error
        source.last_run_at = now
        source.last_run_status = status.value
        if status in (RunStatus.SUCCESS, RunStatus.PARTIAL, RunStatus.NO_CHANGE):
            source.last_success_at = now
        if counters.new or counters.revised:
            source.last_new_data_at = now
        if counters.newest_published and (source.latest_published_at is None or counters.newest_published > source.latest_published_at):
            source.latest_published_at = counters.newest_published
        # The "latest period" only moves forward: a run that touched older periods only (a
        # re-released year, one dataset of several) must not make the source look older.
        if counters.newest_period_start:
            if source.latest_period_start is None or counters.newest_period_start >= source.latest_period_start:
                source.latest_period_start = counters.newest_period_start
                source.latest_period_label = counters.newest_period_label
        elif counters.newest_period_label and source.latest_period_start is None:
            source.latest_period_label = counters.newest_period_label  # collectors that only set a label


def _run(collector: Collector, *, trigger: str, force: bool, client: httpx.Client | None) -> dict:
    settings = get_settings()
    opened = _retry_if_locked(lambda: _open_run(collector, trigger), f"starting {collector.key}")
    if opened is None:
        return {"source": collector.key, "status": RunStatus.SKIPPED.value, "error": "disabled"}
    source_id, run_id = opened

    status, error = RunStatus.SUCCESS, None
    ctx: CollectContext | None = None
    try:
        with session_scope() as session:
            source = session.get(Source, source_id)
            ctx = CollectContext(session, source, settings=settings, client=client, force=force)
            try:
                if collector.requires_key and not collector.key_optional and not collector.key_value(settings):
                    raise MissingKey(f"API key not configured ({collector.requires_key.upper()})")
                collector.collect(ctx)
                counters = ctx.counters
                if counters.warnings:
                    status = RunStatus.PARTIAL
                elif counters.new == 0 and counters.revised == 0:
                    status = RunStatus.NO_CHANGE
            except MissingKey as exc:
                session.rollback()
                status, error = RunStatus.SKIPPED, str(exc)
            except Offline as exc:
                session.rollback()
                if is_online():
                    # The PC is online, so this host specifically is unreachable (DNS name gone,
                    # TLS certificate rejected, connection refused): a failure of the source.
                    status, error = RunStatus.FAILED, f"Host unreachable while the internet connection works: {exc}"
                else:
                    status, error = RunStatus.OFFLINE, str(exc)
            except CollectorError as exc:
                session.rollback()
                status, error = RunStatus.FAILED, str(exc)
            except Exception as exc:  # noqa: BLE001 - a broken parser must not kill the app
                session.rollback()
                status, error = RunStatus.FAILED, f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=6)}"
                log.exception("Collector %s crashed", collector.key)
            finally:
                ctx.close()
    except Exception as exc:  # noqa: BLE001 - e.g. the final commit failed ("database is locked")
        log.exception("Collector %s: could not save the last batch", collector.key)
        status, error = RunStatus.FAILED, f"{type(exc).__name__} while saving the data: {exc}"
    counters = ctx.counters if ctx is not None else RunCounters()
    if status in (RunStatus.FAILED, RunStatus.OFFLINE, RunStatus.SKIPPED):
        # anything not checkpointed was rolled back: counts and freshness too
        counters.restore_committed()

    _retry_if_locked(lambda: _finish_run(run_id, status, error, counters), f"recording the {collector.key} run")

    result = {
        "source": collector.key, "status": status.value, "new": counters.new, "revised": counters.revised,
        "seen": counters.seen, "warnings": counters.warnings, "error": error,
    }
    log.info("collector %s -> %s (new=%s revised=%s)", collector.key, status.value, counters.new, counters.revised)
    return result


def run_all(*, trigger: str = "manual", force: bool = False, keys: list[str] | None = None) -> list[dict]:
    results = []
    if not is_online():
        with _write_lock, session_scope() as session:
            for c in all_collectors():
                if keys and c.key not in keys:
                    continue
                src = session.scalars(select(Source).where(Source.key == c.key)).first()
                if src is None or not src.enabled:
                    continue        # a source switched off is not run, online or not (as in `_open_run`)
                session.add(CollectionRun(source_id=src.id, status=RunStatus.OFFLINE.value, trigger=trigger,
                                          started_at=utcnow(), finished_at=utcnow(), error="No internet connection"))
                src.last_run_at = utcnow()
                src.last_run_status = RunStatus.OFFLINE.value
                results.append({"source": c.key, "status": RunStatus.OFFLINE.value})
        return results
    for c in all_collectors():
        if keys and c.key not in keys:
            continue
        try:
            results.append(run_collector(c.key, trigger=trigger, force=force))
        except Exception as exc:  # pragma: no cover - defensive
            results.append({"source": c.key, "status": "failed", "error": repr(exc)})
    post_collection_hooks()
    return results


def post_collection_hooks() -> None:
    """Things to recompute after new data: FX backfill, data quality, alerts, AI enrichment.
    Each hook is independent: one failing (e.g. "database is locked") never skips the others."""
    from ..services import fx

    # The database-wide passes write many rows in one transaction: serialised with collectors.
    with _write_lock:
        try:
            with session_scope() as session:
                fx.backfill_normalised_prices(session)
        except Exception:
            log.exception("FX backfill failed")
        try:
            from ..services import quality

            with session_scope() as session:
                quality.run_checks(session)
        except ImportError:
            pass
        except Exception:  # pragma: no cover
            log.exception("quality checks failed")
        try:
            from ..services import alerts

            with session_scope() as session:
                alerts.evaluate_all(session)
        except ImportError:
            pass
        except Exception:  # pragma: no cover
            log.exception("alert evaluation failed")
        try:
            from ..db import refresh_planner_stats

            refresh_planner_stats()      # query-planner statistics follow the new data (speed only)
        except Exception:  # pragma: no cover
            log.exception("planner statistics failed")
    # AI enrichment waits on the LLM provider between short per-batch commits: it runs outside
    # the lock so it never holds collectors back for minutes (its commits wait busy_timeout).
    try:
        from ..services import ai_enrich

        with session_scope() as session:
            ai_enrich.enrich_news(session)  # no-op when no AI provider is configured
    except ImportError:
        pass
    except Exception:  # pragma: no cover
        log.exception("AI news enrichment failed")
    # Without an AI provider: Italian headlines by machine translation (labelled as such), within
    # the free service's daily allowance. Same place and reason as above: it waits on a web service.
    try:
        from ..services import title_translate

        with session_scope() as session:
            title_translate.translate_pending(session)
    except Exception:  # pragma: no cover
        log.exception("headline translation failed")
    from ..api import memo

    memo.warm_in_background()      # in the server: rebuild the shared aggregates for the new data


def fail_interrupted_runs() -> int:
    """At start-up: runs still marked 'running' were interrupted (app closed, crash, or the
    database stayed locked). Record them as failed so they do not stay 'running' forever."""
    with session_scope() as session:
        res = session.execute(
            update(CollectionRun)
            .where(CollectionRun.status == RunStatus.RUNNING.value)
            .values(status=RunStatus.FAILED.value, error=INTERRUPTED_ERROR, finished_at=utcnow())
        )
        n = res.rowcount or 0
    if n:
        log.info("marked %s interrupted collection run(s) as failed", n)
    return n


def last_full_run_age_hours() -> float | None:
    with session_scope() as session:
        last = session.scalars(select(CollectionRun.finished_at).order_by(CollectionRun.finished_at.desc()).limit(1)).first()
    if last is None:
        return None
    return (utcnow() - last) / timedelta(hours=1)
