"""Run collectors, record CollectionRun rows, keep Source status up to date."""
from __future__ import annotations

import logging
import threading
import traceback
from datetime import timedelta

import httpx
from sqlalchemy import select

from ..config import get_settings
from ..db import session_scope
from ..enums import RunStatus
from ..models import CollectionRun, Source, utcnow
from .base import CollectContext, Collector, CollectorError, MissingKey, Offline
from .registry import all_collectors, get_collector

log = logging.getLogger(__name__)

# One collection at a time per source (scheduler + manual button can overlap).
_locks: dict[str, threading.Lock] = {}
_global_lock = threading.Lock()


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
        return _run(collector, trigger=trigger, force=force, client=client)
    finally:
        lock.release()


def _run(collector: Collector, *, trigger: str, force: bool, client: httpx.Client | None) -> dict:
    settings = get_settings()
    with session_scope() as session:
        source = session.scalars(select(Source).where(Source.key == collector.key)).one()
        if not source.enabled:
            return {"source": collector.key, "status": RunStatus.SKIPPED.value, "error": "disabled"}
        run = CollectionRun(source_id=source.id, status=RunStatus.RUNNING.value, trigger=trigger, started_at=utcnow())
        session.add(run)
        session.flush()
        run_id = run.id

    status, error = RunStatus.SUCCESS, None
    counters = None
    with session_scope() as session:
        source = session.get(Source, source.id)
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
        counters = ctx.counters
        if status in (RunStatus.FAILED, RunStatus.OFFLINE, RunStatus.SKIPPED):
            # anything not checkpointed was rolled back
            counters.new = counters.committed_new
            counters.revised = counters.committed_revised

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
        if counters.newest_period_label:
            source.latest_period_label = counters.newest_period_label

    result = {
        "source": collector.key, "status": status.value, "new": counters.new, "revised": counters.revised,
        "seen": counters.seen, "warnings": counters.warnings, "error": error,
    }
    log.info("collector %s -> %s (new=%s revised=%s)", collector.key, status.value, counters.new, counters.revised)
    return result


def run_all(*, trigger: str = "manual", force: bool = False, keys: list[str] | None = None) -> list[dict]:
    results = []
    if not is_online():
        with session_scope() as session:
            for c in all_collectors():
                if keys and c.key not in keys:
                    continue
                src = session.scalars(select(Source).where(Source.key == c.key)).first()
                if src is None:
                    continue
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
    """Things to recompute after new data: FX backfill, data quality, alerts."""
    from ..services import fx

    with session_scope() as session:
        fx.backfill_normalised_prices(session)
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


def last_full_run_age_hours() -> float | None:
    with session_scope() as session:
        last = session.scalars(select(CollectionRun.finished_at).order_by(CollectionRun.finished_at.desc()).limit(1)).first()
    if last is None:
        return None
    return (utcnow() - last) / timedelta(hours=1)
