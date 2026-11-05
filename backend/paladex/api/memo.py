"""Heavy read-only aggregates, kept while the database is unchanged.

The trade totals behind /trade/facets, /countries, the trade rankings and the overview read every
trade row (more than 100,000) and take most of a second to build. They depend only on what the
database holds (and on today's date, for freshness), so they are built once and reused until
something is written.

"Something was written" is SQLite's own change counter: ``PRAGMA data_version`` on a dedicated
connection that never writes changes whenever ANY other connection commits — this server's
requests, a collection run here or from the command line in another process, the starter data,
a demo seed, a setting. Every entry is keyed by that counter, read BEFORE the computation (an
entry is never older than its key: a commit during the computation only makes it newer), and by
the day; a new counter empties the store. Nothing is cached while the request's own connection
holds uncommitted writes, and nothing at all for a database that is not a SQLite file.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from collections import OrderedDict
from collections.abc import Callable, Hashable
from datetime import date
from typing import TypeVar

from sqlalchemy.orm import Session

log = logging.getLogger(__name__)
V = TypeVar("V")

MAX_ENTRIES = 48
MAX_BYTES = 64 * 1024 * 1024     # rendered answers (bytes) kept at most, all entries together

_lock = threading.Lock()
_watch: dict = {"engine": None, "path": None, "inode": None, "conn": None, "version": None}
_store: OrderedDict[tuple, object] = OrderedDict()


def _reset_watch(engine, path: str | None) -> None:
    conn = _watch.get("conn")
    if conn is not None:
        try:
            conn.close()
        except sqlite3.Error:  # pragma: no cover
            pass
    _watch.update(engine=engine, path=path, inode=None, conn=None, version=None)
    _store.clear()


def _inode(path: str) -> tuple[int, int] | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_dev, st.st_ino)


def _version(db: Session) -> tuple | None:
    """(engine identity, data version) of the session's database, or None when it cannot be told
    (not a SQLite file, the counter unreadable): then nothing is cached."""
    try:
        engine = db.get_bind()
        if engine.dialect.name != "sqlite":
            return None
        path = engine.url.database
        if not path or path == ":memory:" or path.startswith("file:"):
            return None
    except Exception:  # pragma: no cover - defensive
        return None
    ino = _inode(path)
    if ino is None:
        return None
    with _lock:
        if _watch["engine"] is not engine or _watch["path"] != path or _watch["inode"] != ino:
            _reset_watch(engine, path)
            _watch["inode"] = ino
        try:
            if _watch["conn"] is None:
                conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=5)
                _watch["conn"] = conn
            v = _watch["conn"].execute("PRAGMA data_version").fetchone()[0]
        except sqlite3.Error as e:  # busy, file gone ...: compute without the store
            log.debug("data_version unavailable: %s", e)
            _reset_watch(engine, path)
            return None
        if v != _watch["version"]:
            _store.clear()
            _watch["version"] = v
        return (id(engine), path, v)


def _writing(db: Session) -> bool:
    """True when the session's connection has uncommitted changes (its reads would not be the
    committed state the counter describes)."""
    try:
        if db.new or db.dirty or db.deleted:
            return True
        if not db.in_transaction():
            return False
        return bool(db.connection().connection.dbapi_connection.in_transaction)
    except Exception:  # pragma: no cover - defensive
        return True


def cached(db: Session, name: str, params: Hashable, compute: Callable[[], V]) -> V:
    """`compute()`'s value for (`name`, `params`), reused while the database and the day are
    unchanged. The value is shared between requests: callers must not modify it."""
    version = _version(db)
    if version is None or _writing(db):
        return compute()
    key = (version, date.today().isoformat(), name, params)
    with _lock:
        if key in _store:
            _store.move_to_end(key)
            return _store[key]  # type: ignore[return-value]
    value = compute()
    with _lock:
        if _watch["version"] == version[2]:
            _store[key] = value
            while len(_store) > MAX_ENTRIES or (len(_store) > 1 and _bytes() > MAX_BYTES):
                _store.popitem(last=False)
    return value


def _bytes() -> int:
    return sum(len(v) for v in _store.values() if isinstance(v, (bytes, bytearray)))


def clear() -> None:
    """Forget every entry (tests; never needed for correctness)."""
    with _lock:
        _store.clear()


def _warm_prices(db: Session) -> None:
    """The price page's default view of every price type (3 years, USD, monthly), as the interface
    asks for it (frontend prices/utils.ts rangeFrom)."""
    from . import prices

    today = date.today()
    idx = today.year * 12 + today.month - 1 - 35
    start = f"{idx // 12}-{idx % 12 + 1:02d}"

    def filters(price_type: str | None, frm: str | None = None):
        return prices.price_filters(price_type=price_type, origin=None, variety=None, market=None, source=None,
                                    color_grade=None, date_from=frm, date_to=None, small=False)

    types = [p["key"] for p in json.loads(prices.facets(f=filters(None), db=db).body)["price_types"] if p["count"]]
    for t in types:
        prices.facets(f=filters(t), db=db)
        prices.series(f=filters(t, start), currency="USD", freq="M", ids=None, db=db)
        prices.latest(f=filters(t), currency="USD", freq="M", db=db)


# ---------------------------------------------------------------------------
# Warm-up: build the shared aggregates in the background, so the first visit after the server
# starts, or after a collection brought new data, does not wait for them either.
# ---------------------------------------------------------------------------

_warm = {"enabled": False, "running": False}


def enable_warming() -> None:
    """Called by the server at start-up (never by the command-line tools, whose process ends)."""
    _warm["enabled"] = True


def warm_in_background() -> None:
    if not _warm["enabled"] or _warm["running"]:
        return
    _warm["running"] = True
    threading.Thread(target=_warm_now, name="paladex-warm", daemon=True).start()


def _warm_now() -> None:
    try:
        from ..db import session_factory
        from . import countries, overview, trade

        with session_factory()() as db:
            trade.trade_facets(db=db)          # every trade total (also the countries map's)
            countries.list_countries(db=db)
            overview.overview(lang="it", db=db)
            _warm_prices(db)
    except Exception:  # pragma: no cover - a warm-up never matters for correctness
        log.debug("warm-up failed", exc_info=True)
    finally:
        _warm["running"] = False
