"""Global overview — the "morning terminal" homepage (GET /api/overview?lang=it|en).

The owner reads this page every morning. Each block below is self-contained so the UI can
render (or honestly not render) it independently:

    status     data-source health: how many sources are current / late / failed, last check
    briefing   today's Briefing row if one exists, else a deterministic RULE-BASED summary
    prices     latest published point for up to 8 key price series (m/m, y/y, sparkline)
    news       top relevant, non-duplicate news
    reports    newest official reports
    trade      top importers / exporters for the latest available period
    countries  which priority countries have something going on, and why
    alerts     unread alert events
    quality    open data-quality issues by severity

Every block carries `updated_at` (newest `collected_at` of what it shows), the newest
publication date, the sources involved and `providers` (registered sources that would fill
it), so an empty block can say *which* source will provide the data.

Data rules honoured here (docs/DEVELOPING.md): nothing is invented — every number comes
from a stored row with its provenance; demo rows are filtered through `demo_clause`; price
types are never mixed in one computation; old data is labelled with its freshness and
never called "live"; the rule-based briefing is labelled `generator="rules"` (not AI).

Briefing content format (also the format an AI generator should store in `Briefing.content`):

    {"bullets": [{"kind": "price|report|trade|news|text", "text": str,
                  "source": source_brief | None, "publisher": str | None,
                  "date": iso | None, "period_label": str | None,
                  "url": str | None,          # original document / article
                  "link": str | None,         # in-app route
                  "is_demo": bool, "is_ai": bool}]}
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, defer

from ..db import get_db
from ..enums import PriceType, Reliability, RunStatus, SourceKind
from ..models import (
    AlertEvent,
    Briefing,
    CollectionRun,
    Country,
    DataQualityIssue,
    NewsArticle,
    PriceObservation,
    Report,
    Source,
    TradeFlowObservation,
    utcnow,
)
from ..reference.varieties import LABELS as VARIETY_LABELS
from ..services.corrections import briefs_by_id
from .common import demo_clause, freshness, iso, show_demo, source_brief
from .memo import cached
from .meta import PRICE_TYPE_LABELS

router = APIRouter(tags=["overview"])

# ---------------------------------------------------------------------------
# Tunables (kept together so the rules are easy to read and to explain)
# ---------------------------------------------------------------------------

TILE_COUNT = 8
ORIGIN_PRIORITY = ["ARG", "UKR", "CHN", "BRA", "VNM", "IND", "HUN", "ITA"]
VARIETY_PRIORITY = [
    "polyflora", "organic_polyflora", "acacia", "sunflower", "clover", "orange_blossom", "chestnut",
    "eucalyptus", "linden", "rapeseed", "honeydew", "buckwheat", "lavender", "dandelion", "manuka",
    "unspecified", "other",
]
PRICE_TYPE_PRIORITY = [
    PriceType.WHOLESALE_BULK, PriceType.PRODUCER, PriceType.IMPORT_UNIT_VALUE,
    PriceType.EXPORT_UNIT_VALUE, PriceType.RETAIL, PriceType.OTHER,
]
RELIABILITY_PRIORITY = [
    Reliability.OFFICIAL, Reliability.INDUSTRY, Reliability.TRADE_PRESS, Reliability.AGGREGATOR,
    Reliability.USER, Reliability.AI, Reliability.DEMO,
]

PRICE_HISTORY_DAYS = 400         # history each series needs before its newest point (m/m, y/y, sparkline)
PRICE_BULK_DAYS = 800            # one bulk query covers every series whose newest point is this recent
PRICE_RECENT_DAYS = 75           # a price move is "news" only if its period started this recently
PRICE_MOVE_MIN_PCT = 3.0         # briefing threshold for |m/m|
# Frequencies whose period-to-period change is a real "month" move. Weekly surveillance values
# (EU TAXUD, provisional, a few lots per cell) swing by tens of percent week to week: they are
# shown in the price explorer, never reported as a market move in the summary.
MOVE_FREQUENCIES = ("M",)
SPARK_POINTS = 13

REPORT_RECENT_DAYS = 14
NEWS_BRIEFING_DAYS = 3
NEWS_BLOCK_DAYS = 30
NEWS_MIN_RELEVANCE = 60
NEWS_COUNTRY_DAYS = 7
TRADE_MOVE_MIN_PCT = 10.0
TRADE_BRIEFING_NEW_DAYS = 30     # annual trade figures are "news" only when they arrived recently
TRADE_NEW_DATA_DAYS = 7
# Bullets per briefing rule (keeps the summary readable in two minutes).
BRIEFING_CAPS = {"prices": 3, "reports": 2, "trade": 2, "news": 3}
TRADE_PARTIAL_COVERAGE = 0.6     # latest period with < 60% of the previous period's reporters = partial

# When a source does not declare its own rhythm, judge an observation by its frequency.
FREQ_MAX_AGE_DAYS = {"D": 5, "W": 14, "M": 60, "Q": 150, "A": 550}

PSEUDO_AREAS = {"WLD", "EU27", "EU28", "EXTRA_EU", "INTRA_EU"}

# Sources that would fill each block (by Source.category), used for honest empty states.
PROVIDER_CATEGORIES = {
    "prices": ("prices",),
    "trade": ("trade",),
    "news": ("news",),
    "reports": ("reports", "prices", "production", "regulation"),
    "briefing": ("prices", "trade", "news", "reports", "production"),
    "countries": ("prices", "trade", "news"),
}

_MONTHS = {
    "it": ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"],
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
}
# Tells apart two tiles that differ only by period granularity (e.g. annual vs monthly unit values).
FREQ_WORDS = {
    "it": {"D": "giornaliero", "W": "settimanale", "M": "mensile", "Q": "trimestrale", "A": "annuale",
           "irregular": "irregolare"},
    "en": {"D": "daily", "W": "weekly", "M": "monthly", "Q": "quarterly", "A": "annual", "irregular": "irregular"},
}


def _term_parts(terms: str | None) -> list[str]:
    """'fusto da 3 q.li; media mensile' -> ['fusto da 3 q.li', 'media mensile']. Separators inside
    brackets do not split: 'US customs value / net kg (imports for consumption; excludes freight,
    insurance & duty), HS 0409 total' has two parts, not four half-sentences."""
    parts, depth, cur = [], 0, []
    for ch in terms or "":
        depth += (ch == "(") - (ch == ")")
        if ch in ";," and depth <= 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return [p.strip() for p in parts if p.strip()]


def _short(text: str, limit: int = 48) -> str:
    """`text` cut at a word boundary with an ellipsis, never in the middle of a word."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,;(") + "…"


# ---------------------------------------------------------------------------
# Small formatting helpers for the (language-specific) briefing sentences
# ---------------------------------------------------------------------------


def fmt_num(v: float, lang: str, digits: int = 0) -> str:
    s = f"{abs(v):,.{digits}f}"
    if lang == "it":
        s = s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return f"−{s}" if v < 0 else s


def fmt_pct(v: float, lang: str, digits: int = 1, signed: bool = True) -> str:
    body = fmt_num(abs(v), lang, digits)
    if not signed:
        return f"{body}%"
    return f"{'+' if v > 0 else '−' if v < 0 else ''}{body}%"


def fmt_date(d: date | datetime | None, lang: str) -> str:
    if d is None:
        return "—"
    return f"{d.day} {_MONTHS[lang][d.month - 1]} {d.year}"


def fmt_period(label: str | None, lang: str) -> str:
    if not label:
        return "—"
    if len(label) == 7 and label[4] == "-" and label[:4].isdigit() and label[5:].isdigit():
        m = int(label[5:])
        if 1 <= m <= 12:
            return f"{_MONTHS[lang][m - 1]} {label[:4]}"
    if len(label) == 7 and label[4:6] == "-Q":
        return f"{'T' if lang == 'it' else 'Q'}{label[6]} {label[:4]}"
    if m := re.fullmatch(r"(\d{4})-W(\d{1,2})", label):
        return f"settimana {int(m[2])} del {m[1]}" if lang == "it" else f"week {int(m[2])} of {m[1]}"
    return label


def _of_pct(pct_text: str, lang: str) -> str:
    """Italian 'del 18,5%' but 'dell'84,5%', 'dell'11%', 'dell'1,2%' (numbers read with a vowel first)."""
    if lang != "it":
        return ""
    whole = re.split(r"[,.]", pct_text.lstrip("+−-"))[0]
    return "dell'" if whole.startswith("8") or whole in ("1", "11") else "del "


def _vs_period(label: str | None, lang: str) -> str:
    """Italian 'rispetto al 2023' / 'rispetto a set 2025' / 'rispetto ad ago 2025'; English 'vs 2023'."""
    txt = fmt_period(label, lang)
    if lang != "it":
        return f"vs {txt}"
    if label and re.fullmatch(r"\d{4}", label):
        return f"rispetto al {txt}"
    return f"rispetto {'ad' if txt[:1].lower() in 'aeiou' else 'a'} {txt}"


def fmt_tonnes(kg: float | None, lang: str) -> str:
    if kg is None:
        return "—"
    t = kg / 1000
    return f"{fmt_num(t, lang, 1 if t < 10 else 0)} t"


def pct_change(curr: float | None, prev: float | None) -> float | None:
    if curr is None or prev is None or prev == 0:
        return None
    return round((curr - prev) / prev * 100, 2)


def _rank(seq: list, value) -> int:
    try:
        return seq.index(value)
    except ValueError:
        return len(seq)


def item_freshness(ref: date | None, expected_days: int | None, frequency: str | None, today: date) -> dict:
    """Freshness of one observation: age of its publication (or period end) against the
    source's declared rhythm, or a default for its frequency."""
    if ref is None:
        return {"status": "never", "age_days": None, "reference_date": None, "expected_max_age_days": None}
    exp = expected_days or FREQ_MAX_AGE_DAYS.get(frequency or "")
    age = (today - ref).days
    if not exp:
        status = "unknown"
    elif age <= exp:
        status = "current"
    elif age <= exp * 1.5:
        status = "aging"
    else:
        status = "stale"
    return {"status": status, "age_days": age, "reference_date": ref.isoformat(), "expected_max_age_days": exp}


def _newest_refs(triples) -> dict[int, tuple[date | None, str | None]]:
    """(source_id, reference date, frequency) rows -> newest reference date per source."""
    out: dict[int, tuple[date | None, str | None]] = {}
    for sid, ref, freq in triples:
        if ref is not None and (sid not in out or out[sid][0] is None or ref > out[sid][0]):
            out[sid] = (ref, freq)
    return out


def _max(values) -> Any:
    vals = [v for v in values if v is not None]
    return max(vals) if vals else None


# ---------------------------------------------------------------------------
# Request context
# ---------------------------------------------------------------------------


# Columns no summary reads (the JSON `extra` alone is a third of the load time).
_UNREAD = (defer(PriceObservation.extra), defer(PriceObservation.value_hash), defer(PriceObservation.series_key))


def _detach(db: Session, objs) -> None:
    """Take loaded rows out of the request's session: they are shared read-only between requests
    (memo.py), so nothing done later in this session (a rollback expires its objects) may touch them."""
    for o in objs:
        if o in db:
            db.expunge(o)


def _mean_of(values) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


# A figure averaged from more rows than this is not offered for fixing in one tap.
MAX_FIX_ROWS = 6


class AveragedPoint:
    """Several stored rows of ONE series, product and period, shown as one figure: their simple
    average, as the Prezzi page shows it (prices._combine). The USDA report lists two lines for some
    origin / colour / month; picking one of them by row id made the tile, its month-on-month change
    and the daily summary disagree with Prezzi (a "-16,4% in a month" that was really -8,4%).
    Everything that is not a price (period, unit, currency, source, dates) is read from the newest
    row; `id` is None because no single stored row is the figure shown."""

    id = None
    _MEAN = ("price_per_kg", "usd_per_kg", "eur_per_kg", "price_value")

    def __init__(self, rows: list):
        self.rows = rows
        self._newest = rows[-1]
        for f in self._MEAN:
            setattr(self, f, _mean_of(getattr(r, f) for r in rows))
        lows = [r.price_low for r in rows if r.price_low is not None]
        highs = [r.price_high for r in rows if r.price_high is not None]
        self.price_low = sum(lows) / len(lows) if len(lows) == len(rows) else None
        self.price_high = sum(highs) / len(highs) if len(highs) == len(rows) else None
        self.is_demo = any(r.is_demo for r in rows)

    def __getattr__(self, name: str):
        if name.startswith("_") or name == "rows":
            raise AttributeError(name)
        return getattr(self._newest, name)


def _one_point_per_period(points: list) -> list:
    """`points` (one series, ascending period) with the rows of the same product and period
    replaced by their average (see AveragedPoint). Different products of one series (the source's
    own variety text differs) stay separate, as `same_product` expects."""
    groups: dict[tuple, list] = {}
    for p in points:
        groups.setdefault((p.period_start, _raw_key(p.variety_raw)), []).append(p)
    if len(groups) == len(points):
        return points
    return [g[0] if len(g) == 1 else AveragedPoint(g) for g in groups.values()]


@dataclass
class PriceSeries:
    key: tuple
    source_id: int
    price_type: str
    origin_iso3: str | None
    variety: str
    market_iso3: str | None
    market_location: str | None
    color_grade: str | None
    organic: bool
    currency: str
    terms: str | None              # packaging / basis: 300 kg drums and 25 kg tins are different products
    frequency: str                 # an annual average is never a point of a monthly series
    latest_start: date
    n_points: int
    points: list = field(default_factory=list)   # PriceObservation rows, ascending period

    @property
    def latest(self):
        return self.points[-1] if self.points else None


class Ctx:
    def __init__(self, db: Session, lang: str):
        self.db = db
        self.lang = lang
        self.today = date.today()
        self.now = utcnow()
        self.show_demo = show_demo(db)
        self.sources: dict[int, Source] = {s.id: s for s in db.scalars(select(Source))}
        self.countries: dict[str, Country] = {c.iso3: c for c in db.scalars(select(Country))}
        self._price_series: list[PriceSeries] | None = None
        self._hints: dict[tuple, str] | None = None
        self._trade: dict | None = None

    # -- labels ---------------------------------------------------------------
    def country(self, iso3: str | None) -> str:
        if not iso3:
            return "—"
        if iso3 == "WLD":
            return "Mondo" if self.lang == "it" else "World"
        if iso3 in ("EU27", "EU28"):
            return "Unione Europea" if self.lang == "it" else "European Union"
        c = self.countries.get(iso3)
        if c is None:
            return iso3
        return c.name_it if self.lang == "it" else c.name_en

    def variety(self, key: str | None) -> str:
        lab = VARIETY_LABELS.get(key or "")
        return lab[self.lang] if lab else (key or "—")

    def price_type(self, key: str) -> str:
        lab = PRICE_TYPE_LABELS.get(key)
        return lab[self.lang] if lab else key

    def source(self, source_id: int | None) -> Source | None:
        return self.sources.get(source_id) if source_id is not None else None

    def brief(self, source_id: int | None) -> dict | None:
        return source_brief(self.source(source_id))

    def providers(self, block: str) -> list[dict]:
        cats = PROVIDER_CATEGORIES.get(block, ())
        from .meta import RELIABILITY_RANK

        rows = [s for s in self.sources.values()
                if s.category in cats and s.key != "demo" and s.kind != SourceKind.MANUAL.value]
        # Enabled first, then official/government sources before industry, press and aggregators.
        rows.sort(key=lambda s: (not s.enabled, RELIABILITY_RANK.get(s.reliability, 9), s.name))
        return [{"key": s.key, "name": s.name, "name_en": s.name_en, "publisher": s.publisher, "enabled": s.enabled,
                 "last_run_status": s.last_run_status} for s in rows]

    def sources_used(self, source_ids, data_ref: dict[int, tuple[date | None, str | None]] | None = None) -> list[dict]:
        """Sources behind a block, with their freshness. When a source has no run metadata yet
        (e.g. the demo source, or rows imported by hand) its freshness is judged from the newest
        data the block actually shows (`data_ref`: source_id -> (reference date, frequency))."""
        out = []
        for sid in sorted({i for i in source_ids if i is not None}):
            s = self.source(sid)
            if s is None:
                continue
            f = freshness(s, self.today)
            ref = (data_ref or {}).get(sid)
            if f["status"] == "never" and ref and ref[0]:
                f = item_freshness(ref[0], s.expected_max_age_days, ref[1], self.today)
            out.append({**source_brief(s), "freshness": f})
        return out

    def obs_freshness(self, row) -> dict:
        src = self.source(row.source_id)
        ref = row.published_at or row.period_end
        return item_freshness(ref, src.expected_max_age_days if src else None, row.frequency, self.today)

    # -- shared analyses --------------------------------------------------------
    def price_series(self) -> list[PriceSeries]:
        """All current price series (one per source/type/origin/variety/market/grade/currency/
        terms/frequency, the same identity as the prices API) with the recent history needed
        for m/m, y/y and sparklines."""
        if self._price_series is not None:
            return self._price_series
        # Every recent observation of every series (about 17,000 rows): read once per database
        # state and day (memo.py), shared read-only by the overview, the briefing and the assistant.
        self._price_series = cached(self.db, "overview.price_series", (), self._load_price_series)
        return self._price_series

    def _load_price_series(self) -> list[PriceSeries]:
        P = PriceObservation
        cols = (P.source_id, P.price_type, P.origin_iso3, P.variety, P.market_iso3, P.market_location,
                P.color_grade, P.organic, P.currency, P.terms, P.frequency)
        n = len(cols)
        from .prices import bulk_unit_value_clause

        # Small customs consignments (< 10 t) are not bulk prices: kept out of the tiles and summary.
        base = (P.is_current.is_(True), demo_clause(P, self.db), bulk_unit_value_clause(P))
        series: dict[tuple, PriceSeries] = {}
        for row in self.db.execute(select(*cols, func.max(P.period_start), func.count()).where(*base).group_by(*cols)):
            key = tuple(row[:n])
            series[key] = PriceSeries(key, row[0], row[1], row[2], row[3], row[4], row[5], row[6], bool(row[7]),
                                      row[8], row[9], row[10], row[n], row[n + 1])

        def key_of(o: PriceObservation) -> tuple:
            return (o.source_id, o.price_type, o.origin_iso3, o.variety, o.market_iso3, o.market_location,
                    o.color_grade, o.organic, o.currency, o.terms, o.frequency)

        since = self.today - timedelta(days=PRICE_BULK_DAYS)
        for o in self.db.scalars(select(P).where(*base, P.period_start >= since).options(*_UNREAD)
                                 .order_by(P.period_start, P.id)):
            s = series.get(key_of(o))
            if s is not None:
                s.points.append(o)
        # Series whose needed history starts before the bulk window (long-stale series, every
        # annual-only series): ONE query loads each one's own last stretch, so y/y and the
        # sparkline are still right without a query per series.
        stale = {k: s for k, s in series.items() if s.latest_start - timedelta(days=PRICE_HISTORY_DAYS) < since}
        if stale:
            newest = (select(*cols, func.max(P.period_start).label("newest")).where(*base).group_by(*cols)
                      .having(func.max(P.period_start) < since + timedelta(days=PRICE_HISTORY_DAYS)).subquery())
            on = and_(*(c.is_not_distinct_from(newest.c[c.key]) for c in cols))
            q = (select(P).join(newest, on)
                 .where(*base, P.period_start < since,
                        P.period_start >= func.date(newest.c.newest, f"-{PRICE_HISTORY_DAYS} days"))
                 .options(*_UNREAD).order_by(P.period_start, P.id))
            older: dict[tuple, list] = defaultdict(list)
            for o in self.db.scalars(q):
                older[key_of(o)].append(o)
            for k, s in stale.items():
                need_from = s.latest_start - timedelta(days=PRICE_HISTORY_DAYS)
                # older rows all start before `since`, bulk rows on or after it: order is kept
                s.points = [o for o in older.get(k, ()) if o.period_start >= need_from] + s.points
        out = [s for s in series.values() if s.points]
        _detach(self.db, (o for s in out for o in s.points))
        for s in out:
            s.points = _one_point_per_period(s.points)
        return out

    def label_hint(self, s: PriceSeries) -> str | None:
        """What tells a series apart from others that would get the same tile label (same type,
        origin and variety): the first part of its terms they do not share (e.g. "fusto 300 kg"
        vs "secchio 25 kg"), else its period granularity ("annual" vs "monthly")."""
        if self._hints is None:
            self._hints = {}
            groups: dict[tuple, list[PriceSeries]] = defaultdict(list)
            for x in self.price_series():
                groups[(x.price_type, series_base_label(self, x))].append(x)
            for sibs in groups.values():
                if len(sibs) < 2:
                    continue
                shared = set.intersection(*(set(_term_parts(x.terms)) for x in sibs))
                freqs = {x.frequency for x in sibs}
                for x in sibs:
                    own = [p for p in _term_parts(x.terms) if p not in shared]
                    # the shortest distinguishing part ('HS 0409 total', 'secchio 25 kg'), whole words only
                    hint = _short(min(own, key=len)) if own else (FREQ_WORDS[self.lang].get(x.frequency, x.frequency)
                                                    if len(freqs) > 1 else None)
                    if hint:
                        self._hints[x.key] = hint
        return self._hints.get(s.key)


# ---------------------------------------------------------------------------
# Price analysis
# ---------------------------------------------------------------------------


def _find_point(points: list, target: date, tolerance_days: int):
    best, best_d = None, None
    for p in points:
        d = abs((p.period_start - target).days)
        if d <= tolerance_days and (best_d is None or d < best_d):
            best, best_d = p, d
    return best


def _tolerance(freq: str) -> int:
    return {"D": 4, "W": 4, "M": 16, "Q": 46, "A": 120}.get(freq, 16)


def _raw_key(raw: str | None) -> str | None:
    return " ".join(raw.casefold().split()) if raw else None


def same_product(points: list, last) -> list:
    """The points of a series that quote the same product as `last`. One series (source, type, origin,
    variety bucket, market, grade, terms) can hold several products of one variety bucket: CCIAA Cuneo
    lists 'Millefiori di Alta Montagna' (6.75 EUR/kg) and 'Rododendro' (8.00) both as 'other' every
    month, and a change from one to the other is not a price move. Matched on the source's own
    variety text (case and spacing ignored); a series without that text is one product."""
    key = _raw_key(last.variety_raw)
    if key is None:
        return points
    return [p for p in points if _raw_key(p.variety_raw) == key]


def series_changes(s: PriceSeries) -> dict:
    """m/m and y/y on the native per-kg price (same currency, same series, same product — never mixed)."""
    last = s.latest
    freq = last.frequency
    prev_m = prev_y = None
    earlier = same_product(s.points[:-1], last)
    if freq in ("D", "W", "M"):
        prev_m = _find_point(earlier, last.period_start - relativedelta(months=1), _tolerance(freq))
    if freq in ("D", "W", "M", "Q", "A"):
        prev_y = _find_point(earlier, last.period_start - relativedelta(years=1), _tolerance(freq))
    return {
        "mom_pct": pct_change(last.price_per_kg, prev_m.price_per_kg) if prev_m else None,
        "mom_period_label": prev_m.period_label if prev_m else None,
        "yoy_pct": pct_change(last.price_per_kg, prev_y.price_per_kg) if prev_y else None,
        "yoy_period_label": prev_y.period_label if prev_y else None,
    }


def _series_sort_key(s: PriceSeries, today: date) -> tuple:
    recent = s.latest_start >= today - timedelta(days=PRICE_HISTORY_DAYS // 2)
    # A value corrected by a person (reliability 'user') keeps its series' place: ranked by the
    # reliability of the source's own rows, so a correction never swaps the tile for another series.
    rel = next((p.reliability for p in reversed(s.points) if p.reliability != "user"),
               s.latest.reliability if s.latest else None)
    return (not recent, _rank(VARIETY_PRIORITY, s.variety), _rank(RELIABILITY_PRIORITY, rel),
            -s.latest_start.toordinal(), -s.n_points)


def select_tiles(series: list[PriceSeries], today: date, n: int = TILE_COUNT) -> list[PriceSeries]:
    """Up to `n` key series: one wholesale-bulk series per priority origin first, then other
    wholesale series, then other price types (each tile is labelled with its type)."""
    chosen: list[PriceSeries] = []
    taken: set[tuple] = set()

    def take(s: PriceSeries) -> None:
        if len(chosen) < n and s.key not in taken:
            chosen.append(s)
            taken.add(s.key)

    def best_for(pool: list[PriceSeries], origin: str) -> PriceSeries | None:
        cands = sorted((s for s in pool if s.origin_iso3 == origin and s.key not in taken),
                       key=lambda s: _series_sort_key(s, today))
        return cands[0] if cands else None

    wholesale = [s for s in series if s.price_type == PriceType.WHOLESALE_BULK.value]
    others = sorted((s for s in series if s.price_type != PriceType.WHOLESALE_BULK.value),
                    key=lambda s: _rank(PRICE_TYPE_PRIORITY, s.price_type))
    for pool in (wholesale, others):
        for origin in ORIGIN_PRIORITY:
            s = best_for(pool, origin)
            if s:
                take(s)
        rest = sorted((s for s in pool if s.key not in taken),
                      key=lambda s: (_rank(ORIGIN_PRIORITY, s.origin_iso3),) + _series_sort_key(s, today))
        for s in rest:
            take(s)
    return chosen


def series_base_label(ctx: Ctx, s: PriceSeries) -> str:
    origin = ctx.country(s.origin_iso3) if s.origin_iso3 else (s.latest.origin_label or ctx.country(s.market_iso3))
    return f"{origin} · {ctx.variety(s.variety)}"


def series_label(ctx: Ctx, s: PriceSeries) -> str:
    """'Italia · Millefiori', plus a short hint (packaging, granularity) when another series of the
    same type would get the same label."""
    hint = ctx.label_hint(s)
    return f"{series_base_label(ctx, s)} ({hint})" if hint else series_base_label(ctx, s)


def _corrections_of(ctx: Ctx, model, rows) -> dict[int, dict]:
    """{row id: "corrected by ..."} for the rows corrected by a person (shared rows are detached and
    carry no `extra`: one query by primary key, none when no row is corrected)."""
    stored = [x for r in rows if r is not None for x in _stored_rows(r)]
    ids = [r.id for r in stored if r.reliability == "user"]
    return briefs_by_id(ctx.db, model, ids) if ids else {}


def _stored_rows(point) -> list:
    """The stored row(s) behind a point: itself, or the rows an AveragedPoint averages."""
    return point.rows if isinstance(point, AveragedPoint) else [point]


def _source_periods(ctx: Ctx) -> dict[int, set[str]]:
    """Periods ('2026-08', '2026-Q3', '2026') for which each source has price rows, from the loaded
    series (recent history only: see `_tile_comparisons`)."""
    got = getattr(ctx, "_src_periods", None)
    if got is None:
        got = defaultdict(set)
        for x in ctx.price_series():
            for p in x.points:
                d = p.period_start + timedelta(days=3) if p.frequency == "W" else p.period_start
                if p.frequency == "A":
                    got[x.source_id].add(str(d.year))
                elif p.frequency == "Q":
                    got[x.source_id].add(f"{d.year}-Q{(d.month - 1) // 3 + 1}")
                else:
                    got[x.source_id].add(f"{d.year}-{d.month:02d}")
        ctx._src_periods = got  # type: ignore[attr-defined]
    return got


def _tile_comparisons(ctx: Ctx, s: PriceSeries, ch: dict) -> dict:
    """What the simple view says when the month-before or year-before figure is missing: the newest
    earlier figure of the SAME series and product (with its own date, never called "a month ago"),
    and, for each missing period, whether the source published anything for it at all (False: a gap
    in the source, e.g. no USDA report for that month; None: not known)."""
    last = s.latest
    earlier = next((p for p in reversed(same_product(s.points[:-1], last)) if p.price_per_kg), None)
    out: dict[str, Any] = {
        "earlier_period_label": earlier.period_label if earlier else None,
        "earlier_pct": pct_change(last.price_per_kg, earlier.price_per_kg) if earlier else None,
        "mom_missing": None, "yoy_missing": None,
    }
    f = last.frequency
    if f not in ("M", "Q", "A"):
        return out                     # weekly or daily quotes: compared within tolerance, no gap label
    step = {"M": relativedelta(months=1), "Q": relativedelta(months=3), "A": relativedelta(years=1)}[f]
    known_from = ctx.today - timedelta(days=PRICE_BULK_DAYS)
    periods = _source_periods(ctx).get(s.source_id, set())

    def missing(d: date) -> dict:
        label = str(d.year) if f == "A" else f"{d.year}-Q{(d.month - 1) // 3 + 1}" if f == "Q" else f"{d.year}-{d.month:02d}"
        return {"period_label": label, "source_has_period": (label in periods) if d >= known_from else None}

    if ch["mom_pct"] is None and f != "A":
        out["mom_missing"] = missing(last.period_start - step)
    if ch["yoy_pct"] is None:
        out["yoy_missing"] = missing(last.period_start - relativedelta(years=1))
    return out


def _tile(ctx: Ctx, s: PriceSeries, corrections: dict[int, dict] | None = None) -> dict:
    last = s.latest
    ch = series_changes(s)
    spark = [{"period_label": p.period_label, "value": round(p.price_per_kg, 4)}
             for p in same_product(s.points, last)[-SPARK_POINTS:]]
    return {
        "id": "|".join("" if k is None else str(k) for k in s.key),
        # the stored row shown (what a person can correct, POST /api/corrections); None when the
        # figure is the average of several rows of the period (`averaged_rows`)
        "row_id": last.id,
        "averaged_rows": len(last.rows) if isinstance(last, AveragedPoint) else None,
        # the rows averaged (few): a person who fixes the figure fixes each of them (11 Nov 2026)
        "row_ids": [r.id for r in last.rows] if isinstance(last, AveragedPoint) and len(last.rows) <= MAX_FIX_ROWS else None,
        "label": series_label(ctx, s),
        "label_hint": ctx.label_hint(s),
        "origin_iso3": s.origin_iso3, "origin_label": last.origin_label, "variety": s.variety,
        "variety_raw": last.variety_raw, "price_type": s.price_type, "market_iso3": s.market_iso3,
        "market_location": s.market_location, "color_grade": s.color_grade, "organic": s.organic,
        "terms": last.terms,
        "usd_per_kg": last.usd_per_kg, "eur_per_kg": last.eur_per_kg,
        "price_per_kg": last.price_per_kg, "currency": last.currency,
        "price_value": last.price_value, "price_low": last.price_low, "price_high": last.price_high,
        "unit": last.unit, "fx_date": iso(last.fx_date),
        "change_basis": "native_per_kg",
        **ch,
        **_tile_comparisons(ctx, s, ch),
        "spark": spark,
        "freshness": ctx.obs_freshness(last),
        # provenance
        "source": ctx.brief(s.source_id), "source_url": last.source_url,
        "published_at": iso(last.published_at), "collected_at": iso(last.collected_at),
        "period_label": last.period_label, "period_start": iso(last.period_start),
        "period_end": iso(last.period_end), "frequency": last.frequency,
        "data_status": last.data_status, "reliability": last.reliability, "is_demo": last.is_demo,
        "correction": next((c for c in ((corrections or {}).get(r.id) for r in _stored_rows(last)) if c), None),
        "link": _prices_link(s),
    }


def _prices_link(s: PriceSeries) -> str:
    parts = [f"price_type={s.price_type}", f"variety={s.variety}"]
    if s.origin_iso3:
        parts.insert(0, f"origin={s.origin_iso3}")
    return "/prezzi?" + "&".join(parts)


def block_prices(ctx: Ctx) -> dict:
    chosen = select_tiles(ctx.price_series(), ctx.today)
    corrections = _corrections_of(ctx, PriceObservation, [s.latest for s in chosen])
    tiles = [_tile(ctx, s, corrections) for s in chosen]
    types = sorted({t["price_type"] for t in tiles})
    return {
        "items": tiles,
        "price_types": types,
        "mixed_price_types": len(types) > 1,
        "series_available": len(ctx.price_series()),
        "updated_at": iso(_max(t["collected_at"] for t in tiles)),
        "latest_published_at": iso(_max(t["published_at"] for t in tiles)),
        "sources": ctx.sources_used((s.source_id for s in chosen), _newest_refs(
            (s.source_id, s.latest.published_at or s.latest.period_end, s.latest.frequency) for s in chosen)),
        "providers": ctx.providers("prices"),
        "link": "/prezzi",
    }


# ---------------------------------------------------------------------------
# Trade analysis
# ---------------------------------------------------------------------------


def _is_country(ctx: Ctx, iso3: str | None) -> bool:
    return bool(iso3) and iso3 not in PSEUDO_AREAS and iso3 in ctx.countries


def _year_before(start: date) -> date:
    return start - relativedelta(years=1)


def _step_before(start: date, freq: str) -> date:
    """The period just before `start` (previous year for annual data, previous month for monthly)."""
    return start - (relativedelta(years=1) if freq == "A" else relativedelta(months=1))


def _rank_flow(ctx: Ctx, rows: list, flow: str, period: date, prev: date) -> dict | None:
    """Top reporters for one flow in one period, from WLD rows or (fallback) the sum of partners."""
    flow_rows = [r for r in rows if r.flow == flow and _is_country(ctx, r.reporter_iso3)]
    if not flow_rows:
        return None
    world = [r for r in flow_rows if r.partner_iso3 == "WLD"]
    basis = "world_rows" if any(r.period_start == period for r in world) else "sum_partners"
    use = world if basis == "world_rows" else [r for r in flow_rows if _is_country(ctx, r.partner_iso3)]
    return _aggregate(ctx, use, key_attr="reporter_iso3", period=period, prev=prev, basis=basis)


def _aggregate(ctx: Ctx, rows: list, key_attr: str, period: date, prev: date, basis: str) -> dict | None:
    cur: dict[str, dict] = defaultdict(lambda: {"kg": 0.0, "usd": 0.0, "has_kg": False, "has_usd": False,
                                                 "partners": set(), "rows": []})
    old: dict[str, float] = defaultdict(float)
    old_has: set[str] = set()
    for r in rows:
        k = getattr(r, key_attr)
        if r.period_start == period:
            a = cur[k]
            if r.net_weight_kg is not None:
                a["kg"] += r.net_weight_kg
                a["has_kg"] = True
            if r.usd_value is not None:
                a["usd"] += r.usd_value
                a["has_usd"] = True
            a["partners"].add(r.partner_iso3 if key_attr == "reporter_iso3" else r.reporter_iso3)
            a["rows"].append(r)
        elif r.period_start == prev and r.net_weight_kg is not None:
            old[k] += r.net_weight_kg
            old_has.add(k)
    if not cur:
        return None
    corrections = _corrections_of(ctx, TradeFlowObservation, [r for a in cur.values() for r in a["rows"]])
    items = []
    for k, a in cur.items():
        kg = a["kg"] if a["has_kg"] else None
        usd = a["usd"] if a["has_usd"] else None
        prev_kg = old[k] if k in old_has else None
        items.append({
            "iso3": k, "name": ctx.country(k), "net_weight_kg": kg, "usd_value": usd,
            "unit_value_usd_per_kg": round(usd / kg, 3) if kg and usd else None,
            "prev_net_weight_kg": prev_kg, "yoy_pct": pct_change(kg, prev_kg),
            "partners_count": len(a["partners"]) if basis != "world_rows" else None,
            "is_demo": any(r.is_demo for r in a["rows"]),
            "data_status": a["rows"][0].data_status,
            # includes a value corrected by a person: who, when, why, the official value of that row
            "correction": next((corrections[r.id] for r in a["rows"] if r.id in corrections), None),
            "link": f"/paesi/{k}",
        })
    items.sort(key=lambda i: (i["net_weight_kg"] is None, -(i["net_weight_kg"] or 0), -(i["usd_value"] or 0)))
    used = [r for a in cur.values() for r in a["rows"]]
    return {
        "basis": basis,
        "items": items[:5],
        "count": len(items),
        "published_at": iso(_max(r.published_at for r in used)),
        "updated_at": iso(_max(r.collected_at for r in used)),
        "is_demo": any(r.is_demo for r in used),
        "data_status": used[0].data_status if used else None,
        "source_url": next((r.source_url for r in used if r.source_url), None),
    }


def _choose_source_and_period(ctx: Ctx, rows: list, flow: str, freq: str) -> tuple[int, date, date, bool] | None:
    """Pick the source with the widest reporter coverage for `flow`, and its latest period
    that is not obviously partial (fewer than 60% of the previous period's reporters)."""
    cover: dict[int, dict[date, set]] = defaultdict(lambda: defaultdict(set))
    for r in rows:
        if r.flow == flow and _is_country(ctx, r.reporter_iso3):
            cover[r.source_id][r.period_start].add(r.reporter_iso3)
    if not cover:
        return None

    def score(sid: int) -> tuple:
        periods = cover[sid]
        latest = max(periods)
        src = ctx.source(sid)
        return (len(periods[latest]), -_rank(RELIABILITY_PRIORITY, src.reliability if src else None), latest)

    sid = max(cover, key=score)
    periods = cover[sid]
    latest = max(periods)
    before = _step_before(latest, freq)
    partial = False
    if before in periods and len(periods[latest]) < TRADE_PARTIAL_COVERAGE * len(periods[before]):
        latest, partial = before, True
    return sid, latest, _year_before(latest), partial


def trade_analysis(ctx: Ctx) -> dict:
    if ctx._trade is not None:
        return ctx._trade
    # Thousands of partner rows: read once per database state (memo.py), shared read-only.
    ctx._trade = cached(ctx.db, "overview.trade_analysis", (), lambda: _load_trade_analysis(ctx))
    return ctx._trade


def _load_trade_analysis(ctx: Ctx) -> dict:
    T = TradeFlowObservation
    base = (T.is_current.is_(True), demo_clause(T, ctx.db), T.hs_code.like("0409%"))
    freq = None
    for f in ("A", "M"):
        if ctx.db.scalar(select(func.count()).select_from(T).where(*base, T.frequency == f)):
            freq = f
            break
    if freq is None:
        return {"freq": None}
    latest = ctx.db.scalar(select(func.max(T.period_start)).where(*base, T.frequency == freq))
    since = latest - (relativedelta(years=3) if freq == "A" else relativedelta(months=26))
    rows = list(ctx.db.scalars(select(T).where(*base, T.frequency == freq, T.period_start >= since)
                               .options(defer(T.extra), defer(T.value_hash), defer(T.series_key))))
    _detach(ctx.db, rows)
    return {"freq": freq, "rows": rows}


def _period_label_for(rows: list, start: date) -> str | None:
    return next((r.period_label for r in rows if r.period_start == start), None)


def block_trade(ctx: Ctx) -> dict:
    ta = trade_analysis(ctx)
    out: dict[str, Any] = {"available": False, "frequency": ta["freq"], "importers": None, "exporters": None,
                           "ytd": None, "providers": ctx.providers("trade"), "link": "/commercio"}
    if ta["freq"] is None:
        out.update(updated_at=None, sources=[])
        return out
    rows, freq = ta["rows"], ta["freq"]
    used_sources: set[int] = set()
    for flow, key in (("import", "importers"), ("export", "exporters")):
        pick = _choose_source_and_period(ctx, rows, flow, freq)
        if pick is None:
            continue
        sid, period, prev, partial = pick
        src_rows = [r for r in rows if r.source_id == sid]
        ranked = _rank_flow(ctx, src_rows, flow, period, prev)
        if ranked:
            ranked.update(source=ctx.brief(sid), period_label=_period_label_for(src_rows, period),
                          prev_period_label=_period_label_for(src_rows, prev), partial_latest=partial,
                          flow=flow, freshness=_trade_freshness(ctx, src_rows, period))
            out[key] = ranked
            used_sources.add(sid)
    # No export declarations at all: rebuild "main origins" from what importers declared (mirror data).
    if out["exporters"] is None and out["importers"] is not None:
        pick = _choose_source_and_period(ctx, rows, "import", freq)
        if pick:
            sid, period, prev, partial = pick
            src_rows = [r for r in rows if r.source_id == sid and r.flow == "import"
                        and _is_country(ctx, r.reporter_iso3) and _is_country(ctx, r.partner_iso3)]
            mirror = _aggregate(ctx, src_rows, key_attr="partner_iso3", period=period, prev=prev, basis="mirror_imports")
            if mirror:
                mirror.update(source=ctx.brief(sid), period_label=_period_label_for(src_rows, period),
                              prev_period_label=_period_label_for(src_rows, prev), partial_latest=partial,
                              flow="export", freshness=_trade_freshness(ctx, src_rows, period),
                              reporters_count=len({r.reporter_iso3 for r in src_rows if r.period_start == period}))
                out["exporters"] = mirror
    blocks = [b for b in (out["importers"], out["exporters"]) if b]
    out["ytd"] = _trade_ytd(ctx)
    ytd_rows = [r for side in (out["ytd"] or {}).values() for r in side["rows"]]
    out["available"] = bool(blocks) or bool(ytd_rows)
    out["updated_at"] = _max([b["updated_at"] for b in blocks] + [r["collected_at"] for r in ytd_rows])
    out["latest_published_at"] = _max(b["published_at"] for b in blocks)
    out["sources"] = ctx.sources_used(used_sources, _newest_refs(
        (r.source_id, r.published_at or r.period_end, r.frequency) for r in rows if r.source_id in used_sources))
    return out


def _trade_ytd(ctx: Ctx) -> dict | None:
    """The year so far from the monthly customs data, ahead of the annual ranking (ytd.py): each
    country with its own source and months against THE SAME months of the year before; rows are
    listed side by side, never added up or compared across sources."""
    from .trade import Ctx as TradeCtx
    from .ytd import leaders_ytd

    tctx = TradeCtx(ctx.db, today=ctx.today)
    out = {}
    for flow, key in (("import", "importers"), ("export", "exporters")):
        side = leaders_ytd(tctx, flow)
        if side is None:
            continue
        for r in side["rows"]:
            r["name"] = ctx.country(r["iso3"])
            r["link"] = f"/paesi/{r['iso3']}"
        out[key] = side
    return out or None


def _trade_freshness(ctx: Ctx, rows: list, period: date) -> dict:
    sample = next((r for r in rows if r.period_start == period), None)
    if sample is None:
        return item_freshness(None, None, None, ctx.today)
    ref = _max(r.published_at for r in rows if r.period_start == period) or sample.period_end
    src = ctx.source(sample.source_id)
    return item_freshness(ref, src.expected_max_age_days if src else None, sample.frequency, ctx.today)


# ---------------------------------------------------------------------------
# News / reports
# ---------------------------------------------------------------------------


def _news_when(a: NewsArticle) -> datetime:
    return a.published_at or a.collected_at


def _news_title(a: NewsArticle, lang: str) -> tuple[str, bool]:
    """Title in the requested language. Returns (title, is_ai_translation)."""
    translated = a.title_it if lang == "it" else a.title_en
    if a.language and a.language[:2] == lang:
        return a.title, False
    if translated:
        return translated, translated.strip() != a.title.strip()
    return a.title, False


def _news_item(ctx: Ctx, a: NewsArticle) -> dict:
    title, title_ai = _news_title(a, ctx.lang)
    summary = a.summary_it if ctx.lang == "it" else a.summary_en
    src = ctx.source(a.source_id)
    return {
        "id": a.id, "title": title, "original_title": a.title, "title_is_ai": title_ai,
        "summary": summary, "summary_is_ai": bool(summary),
        "publisher": a.publisher or (src.publisher if src else None) or (src.name if src else None),
        "source": source_brief(src), "url": a.url, "image_url": a.image_url, "language": a.language,
        "published_at": iso(a.published_at), "collected_at": iso(a.collected_at),
        "countries": a.countries or [], "topics": a.topics or [],
        "relevance_score": a.relevance_score, "duplicate_count": a.duplicate_count,
        "ai_model": a.ai_model, "is_demo": a.is_demo,
    }


def _news_base(ctx: Ctx):
    N = NewsArticle
    return (N.duplicate_of_id.is_(None), demo_clause(N, ctx.db))


def _news_since(since: datetime):
    N = NewsArticle
    return or_(N.published_at >= since, (N.published_at.is_(None)) & (N.collected_at >= since))


def block_news(ctx: Ctx) -> dict:
    N = NewsArticle
    since = ctx.now - timedelta(days=NEWS_BLOCK_DAYS)
    rows = list(ctx.db.scalars(
        select(N).where(*_news_base(ctx), N.relevance_score >= NEWS_MIN_RELEVANCE, _news_since(since))
        .order_by(func.coalesce(N.published_at, N.collected_at).desc(), N.relevance_score.desc()).limit(8)
    ))
    week = ctx.now - timedelta(days=NEWS_COUNTRY_DAYS)
    collected_week = ctx.db.scalar(select(func.count()).select_from(N).where(*_news_base(ctx), _news_since(week))) or 0
    total = ctx.db.scalar(select(func.count()).select_from(N).where(*_news_base(ctx))) or 0
    return {
        "items": [_news_item(ctx, a) for a in rows],
        "min_relevance": NEWS_MIN_RELEVANCE,
        "window_days": NEWS_BLOCK_DAYS,
        "collected_last_7_days": collected_week,
        "total_stored": total,
        "updated_at": iso(_max(a.collected_at for a in rows)) or iso(
            ctx.db.scalar(select(func.max(N.collected_at)).where(*_news_base(ctx)))),
        "sources": ctx.sources_used((a.source_id for a in rows), _newest_refs(
            (a.source_id, _news_when(a).date(), None) for a in rows)),
        "providers": ctx.providers("news"),
        "link": "/notizie",
    }


def _report_ref_date(r: Report) -> date:
    return r.published_at or r.collected_at.date()


def block_reports(ctx: Ctx) -> dict:
    R = Report
    rows = list(ctx.db.scalars(
        select(R).where(demo_clause(R, ctx.db))
        .order_by(func.coalesce(R.published_at, func.date(R.collected_at)).desc(), R.collected_at.desc()).limit(6)
    ))
    items = []
    for r in rows:
        src = ctx.source(r.source_id)
        summary = r.summary_it if ctx.lang == "it" else r.summary_en
        ref = _report_ref_date(r)
        items.append({
            "id": r.id, "title": r.title, "period_label": r.period_label,
            "published_at": iso(r.published_at), "collected_at": iso(r.collected_at), "url": r.url,
            "source": source_brief(src), "summary": summary, "summary_is_ai": bool(summary) and r.summary_is_ai,
            "is_new": (ctx.today - ref).days <= REPORT_RECENT_DAYS, "is_demo": r.is_demo,
            "freshness": item_freshness(r.published_at, src.expected_max_age_days if src else None, None, ctx.today)
            if r.published_at else item_freshness(None, None, None, ctx.today),
        })
    return {
        "items": items,
        "new_count": sum(1 for i in items if i["is_new"]),
        "recent_days": REPORT_RECENT_DAYS,
        "updated_at": iso(_max(r.collected_at for r in rows)),
        "latest_published_at": iso(_max(r.published_at for r in rows)),
        "sources": ctx.sources_used((r.source_id for r in rows), _newest_refs(
            (r.source_id, r.published_at, None) for r in rows)),
        "providers": ctx.providers("reports"),
        "link": "/notizie",
    }


# ---------------------------------------------------------------------------
# Briefing
# ---------------------------------------------------------------------------

_T = {
    "it": {
        "up": "in rialzo", "down": "in calo",
        "price": "{label} — {ptype}: {dir} {of}{pct} in un mese, a {value} {cur}/kg ({period}).",
        "report": "Nuovo report ufficiale: «{title}».",
        # "{rep} — ..." avoids Italian article/preposition agreement ("degli Stati Uniti", "dall'Argentina").
        "trade_imp": "{rep} — importazioni di miele con origine {par}, {period}: {t} ({pct} {prev}).",
        "trade_exp": "{rep} — esportazioni di miele con destinazione {par}, {period}: {t} ({pct} {prev}).",
        "trade_imp_wld": "{rep} — importazioni totali di miele, {period}: {t} ({pct} {prev}).",
        "trade_exp_wld": "{rep} — esportazioni totali di miele, {period}: {t} ({pct} {prev}).",
        "rule_reports": "Report ufficiali pubblicati negli ultimi {n} giorni",
        "rule_prices": "Variazioni di prezzo mensili di almeno il {n}% (ultimo dato pubblicato)",
        "rule_trade": "Variazioni annue del commercio di almeno il {n}% tra i flussi principali (dati arrivati negli ultimi {d} giorni)",
        "rule_news": "Notizie rilevanti (punteggio ≥ {n}) degli ultimi {d} giorni",
        "nothing": "Nessuna novità rilevante nei dati raccolti: nessun nuovo report ufficiale, nessuna "
                   "variazione di prezzo o di commercio sopra le soglie e nessuna notizia rilevante recente.",
        "no_data": "Nessun dato ancora raccolto: la sintesi comparirà dopo il primo aggiornamento delle fonti.",
    },
    "en": {
        "up": "up", "down": "down",
        "price": "{label} — {ptype}: {dir} {of}{pct} month on month, at {value} {cur}/kg ({period}).",
        "report": "New official report: “{title}”.",
        "trade_imp": "{rep} honey imports from {par} in {period}: {t} ({pct} {prev}).",
        "trade_exp": "{rep} honey exports to {par} in {period}: {t} ({pct} {prev}).",
        "trade_imp_wld": "{rep} total honey imports in {period}: {t} ({pct} {prev}).",
        "trade_exp_wld": "{rep} total honey exports in {period}: {t} ({pct} {prev}).",
        "rule_reports": "Official reports published in the last {n} days",
        "rule_prices": "Monthly price changes of at least {n}% (latest published data)",
        "rule_trade": "Year-on-year trade changes of at least {n}% among the main flows (data received in the last {d} days)",
        "rule_news": "Relevant news (score ≥ {n}) from the last {d} days",
        "nothing": "Nothing notable in the collected data: no new official report, no price or trade "
                   "change above the thresholds and no recent relevant news.",
        "no_data": "No data collected yet: the summary will appear after the first source update.",
    },
}


def _bullet(kind: str, text: str, *, source: dict | None = None, publisher: str | None = None,
            date_: Any = None, period_label: str | None = None, url: str | None = None, link: str | None = None,
            is_demo: bool = False, is_ai: bool = False, data_status: str | None = None, **extra) -> dict:
    return {"kind": kind, "text": text, "source": source,
            "publisher": publisher or (source or {}).get("publisher") or (source or {}).get("name"),
            "date": iso(date_), "period_label": period_label, "url": url, "link": link,
            "is_demo": is_demo, "is_ai": is_ai, "data_status": data_status, **extra}


def _briefing_prices(ctx: Ctx) -> list[dict]:
    tr = _T[ctx.lang]
    recent_from = ctx.today - timedelta(days=PRICE_RECENT_DAYS)
    moves = []
    for s in ctx.price_series():
        if s.latest_start < recent_from or s.frequency not in MOVE_FREQUENCIES:
            continue
        ch = series_changes(s)
        if ch["mom_pct"] is not None and abs(ch["mom_pct"]) >= PRICE_MOVE_MIN_PCT:
            moves.append((s, ch))
    # Wholesale quotations first, then other price types; largest moves first within each.
    moves.sort(key=lambda m: (m[0].price_type != PriceType.WHOLESALE_BULK.value, -abs(m[1]["mom_pct"])))
    out = []
    for s, ch in moves[:BRIEFING_CAPS["prices"]]:
        last = s.latest
        text = tr["price"].format(
            label=series_label(ctx, s), ptype=ctx.price_type(s.price_type).lower(),
            dir=tr["up"] if ch["mom_pct"] > 0 else tr["down"], pct=fmt_pct(abs(ch["mom_pct"]), ctx.lang, signed=False),
            of=_of_pct(fmt_pct(abs(ch["mom_pct"]), ctx.lang, signed=False), ctx.lang),
            value=fmt_num(last.price_per_kg, ctx.lang, 2), cur=last.currency, period=fmt_period(last.period_label, ctx.lang),
        )
        out.append(_bullet(
            "price", text, source=ctx.brief(s.source_id), date_=last.published_at, period_label=last.period_label,
            url=last.source_url, link=_prices_link(s), is_demo=last.is_demo, data_status=last.data_status,
            change_pct=ch["mom_pct"], price_type=s.price_type, origin_iso3=s.origin_iso3,
            # the figures of the sentence, for the interface's simple view (frontend lib/plain.ts)
            market_iso3=s.market_iso3, variety=s.variety, color_grade=s.color_grade, terms=last.terms,
            value_per_kg=round(last.price_per_kg, 4), currency=last.currency,
            prev_period_label=ch["mom_period_label"],
        ))
    return out


def _briefing_reports(ctx: Ctx) -> list[dict]:
    R = Report
    since = ctx.today - timedelta(days=REPORT_RECENT_DAYS)
    rows = ctx.db.scalars(
        select(R).where(demo_clause(R, ctx.db),
                        or_(R.published_at >= since, R.published_at.is_(None) & (R.collected_at >= datetime.combine(since, datetime.min.time()))))
        .order_by(func.coalesce(R.published_at, func.date(R.collected_at)).desc()).limit(BRIEFING_CAPS["reports"])
    )
    tr = _T[ctx.lang]
    return [
        _bullet("report", tr["report"].format(title=r.title), source=ctx.brief(r.source_id), date_=r.published_at,
                period_label=r.period_label, url=r.url, link="/notizie", is_demo=r.is_demo)
        for r in rows
    ]


def _briefing_trade(ctx: Ctx) -> list[dict]:
    ta = trade_analysis(ctx)
    if ta["freq"] is None:
        return []
    rows, freq = ta["rows"], ta["freq"]
    tr = _T[ctx.lang]
    arrived_since = ctx.now - timedelta(days=TRADE_BRIEFING_NEW_DAYS)
    cands = []
    for flow in ("import", "export"):
        pick = _choose_source_and_period(ctx, rows, flow, freq)
        if pick is None:
            continue
        sid, period, prev, _partial = pick
        cur = {(r.reporter_iso3, r.partner_iso3): r for r in rows
               if r.source_id == sid and r.flow == flow and r.period_start == period and _is_country(ctx, r.reporter_iso3)}
        old = {(r.reporter_iso3, r.partner_iso3): r for r in rows
               if r.source_id == sid and r.flow == flow and r.period_start == prev}
        flows = [r for r in cur.values() if r.net_weight_kg and (r.partner_iso3 == "WLD" or _is_country(ctx, r.partner_iso3))]
        top = sorted(flows, key=lambda r: -r.net_weight_kg)[:10]          # the main flows only
        for r in top:
            if r.collected_at < arrived_since:
                continue                                                  # old figure: not today's news
            p = old.get((r.reporter_iso3, r.partner_iso3))
            ch = pct_change(r.net_weight_kg, p.net_weight_kg if p else None)
            if ch is not None and abs(ch) >= TRADE_MOVE_MIN_PCT:
                cands.append((abs(r.net_weight_kg - p.net_weight_kg), r, p, ch))
    cands.sort(key=lambda c: -c[0])
    out = []
    for _, r, p, ch in cands[:BRIEFING_CAPS["trade"]]:
        wld = r.partner_iso3 == "WLD"
        tmpl = tr[("trade_imp" if r.flow == "import" else "trade_exp") + ("_wld" if wld else "")]
        text = tmpl.format(rep=ctx.country(r.reporter_iso3), par=ctx.country(r.partner_iso3),
                           period=fmt_period(r.period_label, ctx.lang), t=fmt_tonnes(r.net_weight_kg, ctx.lang),
                           pct=fmt_pct(ch, ctx.lang), prev=_vs_period(p.period_label, ctx.lang))
        out.append(_bullet("trade", text, source=ctx.brief(r.source_id), date_=r.published_at,
                           period_label=r.period_label, url=r.source_url, link="/commercio", is_demo=r.is_demo,
                           data_status=r.data_status, change_pct=ch,
                           # the figures of the sentence, for the interface's simple view
                           flow=r.flow, reporter_iso3=r.reporter_iso3, partner_iso3=r.partner_iso3,
                           net_weight_kg=r.net_weight_kg, prev_period_label=p.period_label))
    return out


def _briefing_news(ctx: Ctx) -> list[dict]:
    N = NewsArticle
    since = ctx.now - timedelta(days=NEWS_BRIEFING_DAYS)
    rows = ctx.db.scalars(
        select(N).where(*_news_base(ctx), N.relevance_score >= NEWS_MIN_RELEVANCE, _news_since(since))
        .order_by(N.relevance_score.desc(), func.coalesce(N.published_at, N.collected_at).desc())
        .limit(BRIEFING_CAPS["news"])
    )
    out = []
    for a in rows:
        item = _news_item(ctx, a)
        out.append(_bullet("news", item["title"], source=item["source"], publisher=item["publisher"],
                           date_=a.published_at or a.collected_at, url=a.url, link="/notizie", is_demo=a.is_demo,
                           is_ai=item["title_is_ai"]))
    return out


def _normalise_stored_bullets(content: Any) -> list[dict]:
    """Accept the documented format, plus a few tolerant variants (sections, plain strings)."""
    items: list = []
    if isinstance(content, dict):
        if isinstance(content.get("bullets"), list):
            items = content["bullets"]
        elif isinstance(content.get("items"), list):
            items = content["items"]
        elif isinstance(content.get("sections"), list):
            for sec in content["sections"]:
                if isinstance(sec, dict):
                    items.extend(sec.get("bullets") or sec.get("items") or [])
    elif isinstance(content, list):
        items = content
    out = []
    for it in items:
        if isinstance(it, str) and it.strip():
            out.append(_bullet("text", it.strip()))
        elif isinstance(it, dict) and (it.get("text") or it.get("title")):
            src = it.get("source") if isinstance(it.get("source"), dict) else None
            out.append(_bullet(
                str(it.get("kind") or "text"), str(it.get("text") or it.get("title")), source=src,
                publisher=it.get("publisher") or (it.get("source") if isinstance(it.get("source"), str) else None),
                date_=it.get("date") or it.get("published_at"), period_label=it.get("period_label"),
                url=it.get("url"), link=it.get("link"), is_demo=bool(it.get("is_demo")), is_ai=bool(it.get("is_ai")),
            ))
    return out


def block_briefing(ctx: Ctx) -> dict:
    tr = _T[ctx.lang]
    stored = ctx.db.scalars(
        select(Briefing).where(Briefing.briefing_date == ctx.today, Briefing.language == ctx.lang)
    ).first()
    rules = [
        {"key": "prices", "text": tr["rule_prices"].format(n=fmt_num(PRICE_MOVE_MIN_PCT, ctx.lang))},
        {"key": "reports", "text": tr["rule_reports"].format(n=REPORT_RECENT_DAYS)},
        {"key": "trade", "text": tr["rule_trade"].format(n=fmt_num(TRADE_MOVE_MIN_PCT, ctx.lang), d=TRADE_BRIEFING_NEW_DAYS)},
        {"key": "news", "text": tr["rule_news"].format(n=NEWS_MIN_RELEVANCE, d=NEWS_BRIEFING_DAYS)},
    ]
    if stored is not None:
        bullets = _normalise_stored_bullets(stored.content)
        is_ai = stored.generator != "rules"
        for b in bullets:
            b["is_ai"] = b["is_ai"] or is_ai
        return {
            "generator": stored.generator, "is_ai": is_ai, "stored": True,
            "briefing_date": iso(stored.briefing_date), "generated_at": iso(stored.generated_at),
            "bullets": bullets, "rules": [] if is_ai else rules, "empty_message": tr["nothing"] if not bullets else None,
            "has_any_data": True, "providers": ctx.providers("briefing"),
            "sources": ctx.sources_used([]),
        }
    groups = {
        "prices": _briefing_prices(ctx),
        "reports": _briefing_reports(ctx),
        "trade": _briefing_trade(ctx),
        "news": _briefing_news(ctx),
    }
    for r in rules:
        r["count"] = len(groups[r["key"]])
    bullets = groups["prices"] + groups["reports"] + groups["trade"] + groups["news"]
    has_any = bool(ctx.price_series()) or trade_analysis(ctx)["freq"] is not None or bool(
        ctx.db.scalar(select(func.count()).select_from(Report).where(demo_clause(Report, ctx.db)))) or bool(
        ctx.db.scalar(select(func.count()).select_from(NewsArticle).where(*_news_base(ctx))))
    src_ids = {b["source"]["key"] for b in bullets if b.get("source")}
    return {
        "generator": "rules", "is_ai": False, "stored": False,
        "briefing_date": iso(ctx.today), "generated_at": iso(ctx.now),
        "bullets": bullets, "rules": rules,
        "empty_message": None if bullets else (tr["nothing"] if has_any else tr["no_data"]),
        "has_any_data": has_any,
        "is_demo": any(b["is_demo"] for b in bullets),
        "providers": ctx.providers("briefing"),
        "sources": [x for x in ctx.sources_used(ctx.sources) if x["key"] in src_ids],
    }


# ---------------------------------------------------------------------------
# Countries
# ---------------------------------------------------------------------------

_CT = {
    "it": {"news": "{n} notizie negli ultimi 7 giorni", "news1": "1 notizia negli ultimi 7 giorni",
           "price": "{variety}: {pct} in un mese ({period})", "trade": "Nuovi dati di commercio ({period})"},
    "en": {"news": "{n} news items in the last 7 days", "news1": "1 news item in the last 7 days",
           "price": "{variety}: {pct} month on month ({period})", "trade": "New trade data ({period})"},
}


def block_countries(ctx: Ctx) -> dict:
    tr = _CT[ctx.lang]
    priority = [c.iso3 for c in ctx.countries.values() if c.priority]
    pset = set(priority)
    N = NewsArticle
    news_count: dict[str, int] = defaultdict(int)
    since = ctx.now - timedelta(days=NEWS_COUNTRY_DAYS)
    for (countries,) in ctx.db.execute(select(N.countries).where(*_news_base(ctx), _news_since(since))):
        for iso3 in set(countries or []):
            if iso3 in pset:
                news_count[iso3] += 1

    price_move: dict[str, tuple[float, PriceSeries, dict]] = {}
    recent_from = ctx.today - timedelta(days=PRICE_RECENT_DAYS)
    for s in ctx.price_series():
        if s.origin_iso3 not in pset or s.latest_start < recent_from or s.frequency not in MOVE_FREQUENCIES:
            continue
        ch = series_changes(s)
        if ch["mom_pct"] is None:
            continue
        best = price_move.get(s.origin_iso3)
        if best is None or abs(ch["mom_pct"]) > abs(best[0]):
            price_move[s.origin_iso3] = (ch["mom_pct"], s, ch)

    T = TradeFlowObservation
    trade_new: dict[str, str] = {}
    tsince = ctx.now - timedelta(days=TRADE_NEW_DATA_DAYS)
    newest: dict[str, tuple[date, str]] = {}
    # Grouped in SQL: after a back-fill every row is "collected this week" (119k rows to read otherwise).
    # Each period's newest collection time is kept once per database state (memo.py); a period
    # counts when it was collected since `tsince` (same groups, same order as a filtered query).
    for col in (T.reporter_iso3, T.partner_iso3):
        def grouped(col=col) -> list[tuple]:
            return [tuple(r) for r in ctx.db.execute(
                select(col, T.period_label, T.period_start, func.max(T.collected_at))
                .where(T.is_current.is_(True), demo_clause(T, ctx.db), col.in_(sorted(pset)))
                .group_by(col, T.period_label, T.period_start))]

        for iso3, label, start, collected in cached(ctx.db, "overview.trade_collected", (col.key, tuple(sorted(pset))),
                                                    grouped):
            if collected is None or collected < tsince:
                continue
            if iso3 not in newest or start > newest[iso3][0]:
                newest[iso3] = (start, label)        # the newest period wins
    trade_new = {iso3: label for iso3, (_, label) in newest.items()}

    items = []
    for iso3 in priority:
        reasons = []
        n_news = news_count.get(iso3, 0)
        s_news = min(n_news, 5) * 4
        if n_news:
            reasons.append({"kind": "news", "text": tr["news1"] if n_news == 1 else tr["news"].format(n=n_news),
                            "link": f"/notizie?country={iso3}"})
        s_price = 0.0
        if iso3 in price_move:
            mom, s, _ch = price_move[iso3]
            s_price = min(abs(mom), 10) * 2
            reasons.append({"kind": "price", "text": tr["price"].format(
                variety=ctx.variety(s.variety), pct=fmt_pct(mom, ctx.lang),
                period=fmt_period(s.latest.period_label, ctx.lang)),
                "link": _prices_link(s), "change_pct": mom, "is_demo": s.latest.is_demo})
        s_trade = 0
        if iso3 in trade_new:
            s_trade = 8
            reasons.append({"kind": "trade", "text": tr["trade"].format(period=fmt_period(trade_new[iso3], ctx.lang)),
                            "link": "/commercio"})
        score = round(s_news + s_price + s_trade)
        if score <= 0:
            continue
        items.append({"iso3": iso3, "name": ctx.country(iso3), "score": score,
                      "components": {"news": n_news, "price_mom_pct": price_move[iso3][0] if iso3 in price_move else None,
                                     "new_trade_period": trade_new.get(iso3)},
                      "reasons": reasons, "link": f"/paesi/{iso3}"})
    items.sort(key=lambda i: (-i["score"], i["name"]))
    return {
        "items": items[:8],
        "priority_count": len(priority),
        "scoring": {"news_points_each": 4, "news_cap": 5, "price_points_per_pct": 2, "price_cap_pct": 10,
                    "new_trade_points": 8, "news_days": NEWS_COUNTRY_DAYS, "price_recent_days": PRICE_RECENT_DAYS,
                    "trade_new_days": TRADE_NEW_DATA_DAYS},
        "updated_at": iso(ctx.now),
        "providers": ctx.providers("countries"),
        "link": "/paesi",
    }


# ---------------------------------------------------------------------------
# Status, alerts, quality
# ---------------------------------------------------------------------------


def block_status(ctx: Ctx) -> dict:
    srcs = [s for s in ctx.sources.values() if s.key != "demo" and s.kind != SourceKind.MANUAL.value]
    enabled = [s for s in srcs if s.enabled]
    counts = {"total": len(enabled), "disabled": len(srcs) - len(enabled), "current": 0, "aging": 0, "stale": 0,
              "never": 0, "unknown": 0, "failed": 0, "offline": 0, "skipped": 0}
    rows = []
    for s in enabled:
        f = freshness(s, ctx.today)
        counts[f["status"]] += 1
        if s.last_run_status == RunStatus.FAILED.value:
            counts["failed"] += 1
        elif s.last_run_status == RunStatus.OFFLINE.value:
            counts["offline"] += 1
        elif s.last_run_status == RunStatus.SKIPPED.value:
            counts["skipped"] += 1
        rows.append({"key": s.key, "name": s.name, "name_en": s.name_en, "publisher": s.publisher, "category": s.category,
                     "freshness": f, "last_run_status": s.last_run_status, "last_run_at": iso(s.last_run_at),
                     "latest_published_at": iso(s.latest_published_at)})
    last_run = ctx.db.scalars(
        select(CollectionRun).where(CollectionRun.status != RunStatus.RUNNING.value)
        .order_by(CollectionRun.started_at.desc()).limit(1)
    ).first()
    running = bool(ctx.db.scalar(select(func.count()).select_from(CollectionRun).where(
        CollectionRun.status == RunStatus.RUNNING.value, CollectionRun.started_at >= ctx.now - timedelta(hours=2))))
    order = {"failed": 0, "stale": 1, "aging": 2, "never": 3, "unknown": 4, "current": 5}
    rows.sort(key=lambda r: (order.get("failed" if r["last_run_status"] == "failed" else r["freshness"]["status"], 9), r["name"]))
    return {
        "counts": counts,
        "last_check_at": iso(_max(s.last_run_at for s in srcs)),
        "newest_data_at": iso(_max(s.last_new_data_at for s in srcs)),
        "newest_published_at": iso(_max(s.latest_published_at for s in srcs)),
        "offline": bool(last_run and last_run.status == RunStatus.OFFLINE.value),
        "collection_running": running,
        "never_collected": all(s.last_run_at is None for s in srcs),
        "sources": rows,
        "link": "/fonti",
    }


def block_alerts(ctx: Ctx) -> dict:
    A = AlertEvent
    unread = ctx.db.scalar(select(func.count()).select_from(A).where(A.read.is_(False))) or 0
    rows = ctx.db.scalars(select(A).where(A.read.is_(False)).order_by(A.triggered_at.desc()).limit(6)).all()
    sev = {"critical": 0, "warning": 1, "info": 2}
    items = [{
        "id": e.id, "severity": e.severity, "triggered_at": iso(e.triggered_at),
        "title": e.title_it if ctx.lang == "it" else e.title_en,
        "body": e.body_it if ctx.lang == "it" else e.body_en,
        "link": e.link, "ref_type": e.ref_type, "ref_id": e.ref_id,
    } for e in sorted(rows, key=lambda e: (sev.get(e.severity, 3), -e.triggered_at.timestamp()))]
    return {"unread": unread, "items": items, "updated_at": iso(_max(e.triggered_at for e in rows)), "link": "/avvisi"}


def block_quality(ctx: Ctx) -> dict:
    Q = DataQualityIssue
    counts = {"info": 0, "warning": 0, "critical": 0}
    for sev, n in ctx.db.execute(select(Q.severity, func.count()).where(Q.resolved_at.is_(None)).group_by(Q.severity)):
        counts[sev] = counts.get(sev, 0) + n
    latest = ctx.db.scalar(select(func.max(Q.last_seen_at)).where(Q.resolved_at.is_(None)))
    return {"open": sum(counts.values()), "by_severity": counts, "updated_at": iso(latest), "link": "/fonti"}


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get("/overview")
def overview(lang: str = Query("it", pattern="^(it|en)$"), db: Session = Depends(get_db)) -> dict:
    ctx = Ctx(db, lang)
    demo_present = any(
        db.scalar(select(func.count()).select_from(m).where(m.is_demo.is_(True))) for m in (PriceObservation, TradeFlowObservation)
    )
    return {
        "lang": lang,
        "today": iso(ctx.today),
        "generated_at": iso(ctx.now),
        "show_demo": ctx.show_demo,
        "demo_rows_present": bool(demo_present),
        "status": block_status(ctx),
        "briefing": block_briefing(ctx),
        "prices": block_prices(ctx),
        "news": block_news(ctx),
        "reports": block_reports(ctx),
        "trade": block_trade(ctx),
        "countries": block_countries(ctx),
        "alerts": block_alerts(ctx),
        "quality": block_quality(ctx),
    }
