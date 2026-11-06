"""Paladex online copy, step 1: a copy of a database without any private data.

    python scripts/mirror/prepare_db.py <source.sqlite3> <copy.sqlite3>

The source is opened read-only (a running server may keep writing it) and copied with SQLite's
backup API, which reads one consistent snapshot. Then, in the COPY only:

* every table that is not market data, reference data or the bookkeeping of the sources is
  emptied: supplier quotes, alert rules and events, and any table added later that is not
  listed in KEEP below (new tables are private until someone decides otherwise);
* demonstration rows are deleted and the demo switch and the language preference are removed;
* stored daily briefings marked private are deleted;
* settings whose name suggests private or secret content are removed.

Market figures are not touched: values, revisions and provenance stay exactly as collected.
Prints a JSON summary of what was removed.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

# Tables the read-only market pages need (data, reference lists, source status, data quality).
# `correction_events` (corrections made by a person, synced through git) is deliberately NOT kept:
# a corrected figure is a row of the series tables above, and its "corrected by <name> on <date>"
# (author, date, reason, official value) is stored on that row (`extra.correction`), which is what
# the API shows. The events table would add only the notes, the original wording given to the AI and
# the computers' ids, which the phone copy does not need. A "doubtful figure" flag is a data-quality
# issue (kept, with its author and reason).
KEEP = {
    "countries", "sources", "collection_runs", "raw_documents", "fx_rates",
    "price_observations", "trade_flows", "production_stats", "weather_observations", "tariff_measures",
    "company_records",          # official company lists (public sources only: Uruguay XXI, HMRC)
    "web_findings",             # figures found on public web pages, each verified on its page (non-official panel)
    "reports", "news_articles", "regulations", "data_quality_issues", "app_settings", "briefings",
}
# Settings removed from the copy (preferences of the computer, and anything that sounds private).
DROP_SETTINGS = {"show_demo", "language"}
PRIVATE_SETTING = re.compile(r"quote|alert|assistant|secret|token|password|api_?key|credential", re.I)


def _tables(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]


def _truthy(v) -> bool:
    return v in (1, True, "1", "true", "True")


def prepare(src: Path, dst: Path) -> dict:
    if not src.is_file():
        raise SystemExit(f"database not found: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    for p in (dst, dst.with_name(dst.name + "-wal"), dst.with_name(dst.name + "-shm")):
        p.unlink(missing_ok=True)
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    d = sqlite3.connect(dst)
    try:
        s.backup(d)
    finally:
        s.close()
    out: dict = {"emptied": {}, "demo_rows_deleted": {}, "settings_removed": [], "private_briefings_deleted": 0}
    try:
        tables = _tables(d)
        if "price_observations" not in tables or "sources" not in tables:
            raise SystemExit(f"{src} is not a Paladex database")
        for t in tables:
            if t not in KEEP:
                n = d.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                d.execute(f'DELETE FROM "{t}"')
                out["emptied"][t] = n
        for t in tables:
            if t in KEEP and "is_demo" in _columns(d, t):
                n = d.execute(f'DELETE FROM "{t}" WHERE is_demo = 1').rowcount
                if n:
                    out["demo_rows_deleted"][t] = n
        if "app_settings" in tables:
            for (key,) in d.execute("SELECT key FROM app_settings").fetchall():
                if key in DROP_SETTINGS or PRIVATE_SETTING.search(key):
                    d.execute("DELETE FROM app_settings WHERE key = ?", (key,))
                    out["settings_removed"].append(key)
        if "briefings" in tables:
            cols = _columns(d, "briefings")
            flag_cols = [c for c in cols if c in ("private", "is_private")]
            for row in d.execute(f'SELECT id, content{"".join(", " + c for c in flag_cols)} FROM briefings').fetchall():
                bid, content, *flags = row
                private = any(_truthy(f) for f in flags)
                try:
                    c = json.loads(content) if isinstance(content, str) else content
                    private = private or (isinstance(c, dict) and _truthy(c.get("private")))
                except ValueError:
                    pass
                if private:
                    d.execute("DELETE FROM briefings WHERE id = ?", (bid,))
                    out["private_briefings_deleted"] += 1
        d.commit()
        out["kept"] = {t: d.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in _tables(d) if t in KEEP}
    finally:
        d.close()
    return out


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    print(json.dumps(prepare(Path(sys.argv[1]), Path(sys.argv[2])), indent=1, sort_keys=True))
