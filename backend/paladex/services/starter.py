"""Starter data: real, already-collected official data shipped with the application.

Without it a fresh installation opens on empty pages while the first collection from every
official source runs (30-40 minutes). The project therefore ships a compressed snapshot of a
real database built from a normal collection (``starter/paladex-starter.sqlite3.xz`` and its
description ``starter/paladex-starter.json``). ``python -m paladex serve`` merges it into the
local database once per snapshot version, before the server starts:

* only data is copied, with its complete original provenance: source, link, publication date,
  period, status, reliability and the original ``collected_at`` (when the figure was really
  collected). Nothing is re-dated and nothing is invented;
* local data always wins: an observation series the local database already holds is left
  untouched; a series it does not hold is copied whole, revision history included (the
  ``supersedes_id`` chain is remapped);
* exchange rates, reports, regulations and news are added only when missing (their unique keys);
* nothing user-specific is ever in the snapshot (no supplier quotes, alert rules, briefings,
  settings, collection runs, demo rows) and nothing local is ever deleted or overwritten;
* the scheduler's start-up collection then checks every source again from this computer:
  identical figures are recognised as unchanged (``services.ingest.record``), new or revised
  figures are added as usual, so the starter data is refreshed in place within the first run.
"""
from __future__ import annotations

import hashlib
import json
import logging
import lzma
import shutil
import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

FORMAT = 1
SETTING_KEY = "starter_data"

# Observation-like tables: identity = (source, series_key); copied as whole series.
SERIES_TABLES = ("price_observations", "trade_flows", "production_stats", "weather_observations", "tariff_measures")
# Tables with a natural unique key: rows are added when that key is missing (INSERT OR IGNORE).
UNIQUE_TABLES = ("reports", "regulations")
KEEP_TABLES = frozenset({"sources", "fx_rates", "news_articles", *SERIES_TABLES, *UNIQUE_TABLES})
# Source columns that describe the data held (not this computer's checks): merged forward.
SOURCE_DATA_FIELDS = ("latest_published_at", "latest_period_label", "latest_period_start", "last_new_data_at")
# Source columns about collection runs on the machine that built the snapshot: never shipped.
SOURCE_RUN_FIELDS = ("last_run_at", "last_run_status", "last_success_at")


def meta_path(xz_path: Path) -> Path:
    """``starter/paladex-starter.sqlite3.xz`` -> ``starter/paladex-starter.json``."""
    return xz_path.with_name(xz_path.name.split(".")[0] + ".json")


def read_meta(xz_path: Path) -> dict | None:
    """The snapshot description, or None when no (valid) snapshot is shipped."""
    try:
        meta = json.loads(meta_path(xz_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(meta, dict) or meta.get("format") != FORMAT or not meta.get("sha256") or not xz_path.exists():
        return None
    return meta


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _columns(conn: sqlite3.Connection, table: str, schema: str = "main") -> list[str]:
    return [r[1] for r in conn.execute(f'PRAGMA {schema}.table_info("{table}")')]


def _tables(conn: sqlite3.Connection, schema: str = "main") -> set[str]:
    return {r[0] for r in conn.execute(f"SELECT name FROM {schema}.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Building the snapshot (developer command: python -m paladex starter-build --from <db>)
# ---------------------------------------------------------------------------

def build(src_db: Path, out_xz: Path) -> dict:
    """Write a compressed snapshot of the data tables of `src_db` (opened read-only; a running
    server may keep writing it) to `out_xz`, plus its JSON description next to it."""
    src_db, out_xz = Path(src_db), Path(out_xz)
    out_xz.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_xz.with_name(out_xz.name + ".tmp")
    tmp.unlink(missing_ok=True)
    src = sqlite3.connect(f"file:{src_db}?mode=ro", uri=True)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)                      # one consistent read transaction
    finally:
        src.close()
    try:
        tables = _tables(dst)
        missing = KEEP_TABLES - tables
        if missing:
            raise ValueError(f"{src_db} is not a Paladex database (missing tables: {sorted(missing)})")
        for t in tables - KEEP_TABLES:      # quotes, alerts, runs, settings, raw documents ... never shipped
            dst.execute(f'DELETE FROM "{t}"')
        for t in (*SERIES_TABLES, *UNIQUE_TABLES, "news_articles"):
            dst.execute(f'DELETE FROM "{t}" WHERE is_demo = 1')
            if "raw_document_id" in _columns(dst, t):
                dst.execute(f'UPDATE "{t}" SET raw_document_id = NULL')   # raw files are not shipped
        dst.execute("UPDATE news_articles SET duplicate_of_id = NULL "
                    "WHERE duplicate_of_id IS NOT NULL AND duplicate_of_id NOT IN (SELECT id FROM news_articles)")
        dst.execute("UPDATE sources SET " + ", ".join(f"{c} = NULL" for c in SOURCE_RUN_FIELDS))
        counts = {t: dst.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in sorted(KEEP_TABLES - {"sources"})}
        collected = [dst.execute(f'SELECT MAX(collected_at) FROM "{t}"').fetchone()[0]
                     for t in (*SERIES_TABLES, *UNIQUE_TABLES, "news_articles")]
        collected = [c for c in collected if c]
        dst.commit()
        dst.execute("PRAGMA journal_mode=DELETE")
        dst.execute("VACUUM")
    finally:
        dst.close()
    with open(tmp, "rb") as f, lzma.open(out_xz, "wb", preset=9) as g:
        shutil.copyfileobj(f, g, 1 << 20)
    tmp.unlink(missing_ok=True)
    meta = {
        "format": FORMAT,
        "sha256": _sha256(out_xz),
        "built_at": _utcnow_iso(),
        # The newest collection time in the snapshot: "these figures were collected up to ..."
        "data_collected_until": max(collected)[:19].replace(" ", "T") if collected else None,
        "counts": counts,
    }
    meta_path(out_xz).write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return meta


# ---------------------------------------------------------------------------
# Importing (python -m paladex serve, once per snapshot version)
# ---------------------------------------------------------------------------

def import_if_needed(progress: Callable[[str], None] | None = None) -> dict | None:
    """Merge the shipped snapshot into the local database unless this exact snapshot version was
    already merged. Returns the import summary, or None when there was nothing to do. Never
    raises: a failed import only means the first collection fills the pages, as before."""
    from ..config import get_settings
    from ..db import session_scope
    from ..models import AppSetting

    settings = get_settings()
    if not settings.starter_data_enabled:
        return None
    xz = settings.starter_data_path
    meta = read_meta(xz)
    if meta is None:
        return None
    with session_scope() as s:
        row = s.get(AppSetting, SETTING_KEY)
        done = row.value if row is not None else None
    if isinstance(done, dict) and done.get("sha256") == meta["sha256"]:
        return None
    try:
        if progress:
            progress("starting")
        return import_snapshot(xz, meta)
    except Exception:
        log.exception("Starter data import failed; the first collection will fill the database instead")
        return None


def import_snapshot(xz: Path, meta: dict) -> dict:
    from ..config import get_settings
    from ..db import SQLITE_BUSY_TIMEOUT_MS, session_scope
    from ..models import AppSetting

    settings = get_settings()
    if _sha256(xz) != meta["sha256"]:
        raise ValueError("starter data file does not match its description (incomplete download?)")
    tmp_dir = settings.data_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    snap = tmp_dir / "starter-import.sqlite3"
    snap.unlink(missing_ok=True)
    try:
        with lzma.open(xz, "rb") as f, open(snap, "wb") as g:
            shutil.copyfileobj(f, g, 1 << 20)
        conn = sqlite3.connect(settings.db_path, isolation_level=None)   # explicit transactions below
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute(f"PRAGMA busy_timeout={int(SQLITE_BUSY_TIMEOUT_MS)}")
            conn.execute("ATTACH DATABASE ? AS snap", (str(snap),))
            try:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    stats = merge(conn)
                    conn.execute("COMMIT")
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
            finally:
                conn.execute("DETACH DATABASE snap")
        finally:
            conn.close()
    finally:
        snap.unlink(missing_ok=True)

    summary = {
        "sha256": meta["sha256"],
        "built_at": meta.get("built_at"),
        "data_collected_until": meta.get("data_collected_until"),
        "imported_at": _utcnow_iso(),
        "inserted": stats["inserted"],
        "kept_local": stats["kept_local"],
    }
    with session_scope() as s:
        row = s.get(AppSetting, SETTING_KEY)
        if row is None:
            s.add(AppSetting(key=SETTING_KEY, value=summary))
        else:
            row.value = summary
    _after_import()
    return summary


def merge(conn: sqlite3.Connection) -> dict:
    """Merge the attached ``snap`` database into ``main`` (inside the caller's transaction)."""
    inserted: dict[str, int] = {}
    kept_local: dict[str, int] = {}
    main_tables, snap_tables = _tables(conn, "main"), _tables(conn, "snap")

    conn.execute("DROP TABLE IF EXISTS temp.starter_src_map")
    conn.execute("CREATE TEMP TABLE starter_src_map AS "
                 "SELECT s.id AS snap_id, m.id AS local_id FROM snap.sources s JOIN main.sources m ON m.key = s.key")

    def common(table: str) -> list[str]:
        snap_cols = set(_columns(conn, table, "snap"))
        return [c for c in _columns(conn, table, "main") if c in snap_cols]

    # 1. ECB exchange rates (unique per date and currency).
    if "fx_rates" in snap_tables and "fx_rates" in main_tables:
        cols = [c for c in common("fx_rates") if c != "id"]
        cl = ", ".join(f'"{c}"' for c in cols)
        cur = conn.execute(f'INSERT OR IGNORE INTO main.fx_rates ({cl}) SELECT {cl} FROM snap.fx_rates ORDER BY id')
        inserted["fx_rates"] = cur.rowcount

    # 2. Observation series: copied whole, only when the local database has no row of that series.
    for t in SERIES_TABLES:
        if t not in snap_tables or t not in main_tables:
            continue
        offset = conn.execute(f'SELECT COALESCE(MAX(id), 0) FROM main."{t}"').fetchone()[0]
        conn.execute("DROP TABLE IF EXISTS temp.starter_rows")
        conn.execute(
            f'CREATE TEMP TABLE starter_rows AS SELECT s.id AS id, mp.local_id AS local_source FROM snap."{t}" s '
            f"JOIN temp.starter_src_map mp ON mp.snap_id = s.source_id "
            f"WHERE s.is_demo = 0 AND NOT EXISTS (SELECT 1 FROM main.\"{t}\" l "
            f"WHERE l.series_key = s.series_key AND l.source_id = mp.local_id AND l.is_demo = 0)"
        )
        exprs = []
        cols = common(t)
        for c in cols:
            if c == "id":
                exprs.append(f"s.id + {int(offset)}")
            elif c == "source_id":
                exprs.append("r.local_source")
            elif c == "supersedes_id":   # revisions point inside their own series, copied whole
                exprs.append(f"CASE WHEN s.supersedes_id IS NULL THEN NULL ELSE s.supersedes_id + {int(offset)} END")
            elif c == "raw_document_id":
                exprs.append("NULL")
            else:
                exprs.append(f's."{c}"')
        cl = ", ".join(f'"{c}"' for c in cols)
        cur = conn.execute(f'INSERT INTO main."{t}" ({cl}) SELECT {", ".join(exprs)} FROM snap."{t}" s '
                           f"JOIN temp.starter_rows r ON r.id = s.id ORDER BY s.id")
        inserted[t] = cur.rowcount
        total = conn.execute(f'SELECT COUNT(*) FROM snap."{t}" WHERE is_demo = 0').fetchone()[0]
        kept_local[t] = total - cur.rowcount
        conn.execute("DROP TABLE temp.starter_rows")

    # 3. Reports and regulations: unique per source and report key / reference.
    for t in UNIQUE_TABLES:
        if t not in snap_tables or t not in main_tables:
            continue
        cols = [c for c in common(t) if c != "id"]
        exprs = ["mp.local_id" if c == "source_id" else "NULL" if c == "raw_document_id" else f's."{c}"' for c in cols]
        cl = ", ".join(f'"{c}"' for c in cols)
        cur = conn.execute(f'INSERT OR IGNORE INTO main."{t}" ({cl}) SELECT {", ".join(exprs)} FROM snap."{t}" s '
                           f"JOIN temp.starter_src_map mp ON mp.snap_id = s.source_id WHERE s.is_demo = 0 ORDER BY s.id")
        inserted[t] = cur.rowcount

    # 4. News (unique canonical URL); duplicate links re-pointed by URL afterwards.
    if "news_articles" in snap_tables and "news_articles" in main_tables:
        offset = int(conn.execute("SELECT COALESCE(MAX(id), 0) FROM main.news_articles").fetchone()[0])
        cols = common("news_articles")
        exprs = []
        for c in cols:
            if c == "id":
                exprs.append(f"s.id + {offset}")
            elif c == "source_id":
                exprs.append("mp.local_id")
            elif c == "duplicate_of_id":
                exprs.append("NULL")
            else:
                exprs.append(f's."{c}"')
        cl = ", ".join(f'"{c}"' for c in cols)
        cur = conn.execute(f'INSERT OR IGNORE INTO main.news_articles ({cl}) SELECT {", ".join(exprs)} '
                           f"FROM snap.news_articles s JOIN temp.starter_src_map mp ON mp.snap_id = s.source_id "
                           f"WHERE s.is_demo = 0 ORDER BY s.id")
        inserted["news_articles"] = cur.rowcount
        if "duplicate_of_id" in cols:
            conn.execute(
                f"UPDATE main.news_articles SET duplicate_of_id = ("
                f"  SELECT l.id FROM main.news_articles l JOIN snap.news_articles d ON d.canonical_url = l.canonical_url"
                f"  JOIN snap.news_articles s ON s.duplicate_of_id = d.id WHERE s.id = main.news_articles.id - {offset}) "
                f"WHERE id > {offset}"
            )

    # 5. What the sources' data looks like (newest publication / period held): carried forward
    #    only where the snapshot holds something newer. Run status stays this computer's own.
    main_cols = set(_columns(conn, "sources", "main"))
    fields = [f for f in SOURCE_DATA_FIELDS if f in main_cols and f in set(_columns(conn, "sources", "snap"))]
    if fields:
        snap_rows = conn.execute(
            f"SELECT mp.local_id, {', '.join('s.' + f for f in fields)} FROM snap.sources s "
            f"JOIN temp.starter_src_map mp ON mp.snap_id = s.id"
        ).fetchall()
        for local_id, *vals in snap_rows:
            new = dict(zip(fields, vals))
            cur_vals = dict(zip(fields, conn.execute(
                f"SELECT {', '.join(fields)} FROM main.sources WHERE id = ?", (local_id,)).fetchone()))
            upd: dict = {}
            for f in ("latest_published_at", "last_new_data_at"):
                if f in new and new[f] and (cur_vals.get(f) is None or str(new[f]) > str(cur_vals[f])):
                    upd[f] = new[f]
            if new.get("latest_period_start") and (
                cur_vals.get("latest_period_start") is None or str(new["latest_period_start"]) > str(cur_vals["latest_period_start"])
            ):
                upd["latest_period_start"] = new["latest_period_start"]
                if "latest_period_label" in new:
                    upd["latest_period_label"] = new["latest_period_label"]
            elif "latest_period_label" in fields and cur_vals.get("latest_period_label") is None and new.get("latest_period_label"):
                upd["latest_period_label"] = new["latest_period_label"]
            if upd:
                conn.execute(f"UPDATE main.sources SET {', '.join(f'{k} = ?' for k in upd)} WHERE id = ?",
                             (*upd.values(), local_id))
    conn.execute("DROP TABLE temp.starter_src_map")
    return {"inserted": inserted, "kept_local": kept_local}


def _after_import() -> None:
    """Recompute what derives from the data (EUR conversions, quality checks), as after a collection."""
    from ..db import session_scope

    try:
        from . import fx

        with session_scope() as s:
            fx.backfill_normalised_prices(s)
    except Exception:  # pragma: no cover - defensive
        log.exception("FX backfill after starter import failed")
    try:
        from . import quality

        with session_scope() as s:
            quality.run_checks(s)
    except Exception:  # pragma: no cover - defensive
        log.exception("quality checks after starter import failed")


def first_run_state(session) -> dict:
    """What the interface needs to explain the first minutes after installation."""
    from sqlalchemy import func, select

    from ..models import AppSetting, CollectionRun, PriceObservation, ProductionStat, TradeFlowObservation

    row = session.get(AppSetting, SETTING_KEY)
    starter = row.value if row is not None and isinstance(row.value, dict) else None
    q = select(CollectionRun.status, func.count()).where(CollectionRun.finished_at.is_not(None)).group_by(CollectionRun.status)
    if starter and starter.get("imported_at"):
        try:
            q = q.where(CollectionRun.finished_at >= datetime.fromisoformat(starter["imported_at"]))
        except ValueError:
            pass
    runs = {status: n for status, n in session.execute(q)}
    has_data = any(
        session.scalar(select(m.id).where(m.is_current.is_(True), m.is_demo.is_(False)).limit(1)) is not None
        for m in (PriceObservation, TradeFlowObservation, ProductionStat)
    )
    return {
        "has_data": has_data,
        # Collection runs finished on this computer (since the starter data was merged), by status.
        "local_runs": runs,
        "starter": {k: starter.get(k) for k in ("built_at", "data_collected_until", "imported_at")} if starter else None,
    }
