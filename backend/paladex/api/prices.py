"""Price intelligence API (/api/prices/...).

Rules enforced here (see docs/DEVELOPING.md):

* Only current revisions (`is_current`) and real rows unless demo display is on (`demo_clause`).
* One price type per chart request: `series`, `latest` and `compare` require a single
  `price_type`; wholesale quotes, producer prices, customs unit values and retail prices are
  never merged.
* Currency conversion uses the per-kg normalised columns stored at ingest
  (`price_per_kg`, `usd_per_kg`, `eur_per_kg`); no exchange rate is guessed here. A row
  without a stored conversion has `value = null` in that currency and keeps its original.
* Quarterly/annual aggregation averages the months that exist, with the number of months
  reported. Gaps are never filled, changes are never extrapolated. Customs unit values
  (import/export) are weighted by the declared volume when every observation carries one
  (value / weight over the period, `weighting="volume"`); every other price is a simple
  average (`weighting="simple"`). A weekly row counts in the month of its ISO Thursday.
* Rows of different period granularity (monthly vs quarterly vs annual) are separate series:
  an annual figure is never averaged with its own months.
* Disagreement between sources (>10% for the same origin/variety/colour/organic/type/market/
  period, one like-for-like line per source) is reported, not resolved.
* `compare` keeps markets apart (one bar per origin or variety AND market), never averages an
  aggregate (EU27, World ...) or a source's total line with its own components, never averages
  two sources that publish the same statistics (US Census and USDA FAS GATS, `SAME_DATA_SOURCES`),
  and never averages demo series with real ones.
"""
from __future__ import annotations

import calendar
import csv
import hashlib
import io
import math
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, defer

from ..db import get_db
from ..enums import DataStatus, PriceType
from ..models import Country, PriceObservation, Source
from ..reference.countries import PRIORITY_ISO3
from ..reference.varieties import LABELS as VARIETY_LABELS
from .common import demo_clause, get_setting, iso, source_brief

router = APIRouter(prefix="/prices", tags=["prices"])

M = PriceObservation
NONE_TOKEN = "_none"                     # filter/facet token for "not specified" (NULL)
DISCREPANCY_THRESHOLD = 0.10             # 10 % between sources
DEFAULT_COMPARE_WINDOW = 3               # months
MAX_CSV_ROWS = 100_000
# Sources that store the same underlying statistics: GATS republishes the US Census import figures
# (collectors/trade_official.py). A cross-source average keeps one of them, never both.
SAME_DATA_SOURCES = ("us_census_trade", "usda_fas_gats")

# Fallback publication rhythm (days) when a source has no `expected_max_age_days`.
DEFAULT_CADENCE_DAYS = {"D": 7, "W": 14, "irregular": 45, "M": 45, "Q": 120, "A": 400}
# Granularity rank: finer -> coarser. "irregular" dated quotes are bucketed by month.
FREQ_RANK = {"D": 0, "W": 1, "irregular": 1, "M": 2, "Q": 3, "A": 4}
RANK_FREQ = {2: "M", 3: "Q", 4: "A"}
# Most cautious status wins when an aggregated point mixes statuses.
STATUS_CAUTION = [
    DataStatus.DEMO, DataStatus.AI_ASSESSMENT, DataStatus.FORECAST, DataStatus.ESTIMATE,
    DataStatus.PROVISIONAL, DataStatus.USER_ENTERED, DataStatus.PUBLISHED, DataStatus.LIVE,
]
PRICE_TYPES = [p.value for p in PriceType]
# Customs unit values: value / weight, so a period's figure is weighted by the declared volume.
UNIT_VALUE_TYPES = frozenset({PriceType.IMPORT_UNIT_VALUE.value, PriceType.EXPORT_UNIT_VALUE.value})
# Aggregate areas used as market (or origin) and what they cover. `compare` never averages an
# aggregate with its own members (EU27 unit value + Italy's + Germany's would count Italy twice).
EU27_MEMBERS = frozenset({
    "AUT", "BEL", "BGR", "HRV", "CYP", "CZE", "DNK", "EST", "FIN", "FRA", "DEU", "GRC", "HUN", "IRL",
    "ITA", "LVA", "LTU", "LUX", "MLT", "NLD", "POL", "PRT", "ROU", "SVK", "SVN", "ESP", "SWE",
})
AGGREGATE_AREAS = frozenset({"EU27", "EU28", "EXTRA_EU", "INTRA_EU", "WLD"})
# Columns the series/latest/compare/discrepancy builders never read (about 20% of load time).
_UNUSED_COLUMNS = (defer(M.extra), defer(M.notes), defer(M.value_hash), defer(M.series_key))

Currency = Literal["USD", "EUR", "ORIGINAL"]


def _is_member(code: str | None, aggregate: str | None) -> bool:
    """True when the country `code` is part of the aggregate area `aggregate`."""
    if not code or code in AGGREGATE_AREAS or aggregate not in AGGREGATE_AREAS:
        return False
    if aggregate in ("EU27", "INTRA_EU"):
        return code in EU27_MEMBERS
    if aggregate == "EU28":
        return code in EU27_MEMBERS or code == "GBR"
    if aggregate == "EXTRA_EU":
        return code not in EU27_MEMBERS
    return True     # WLD covers every country


def _is_total_line(terms: str | None, variety_raw: Iterable[str | None] | str | None = None) -> bool:
    """A source's all-lines total (USDA FAS GATS 'HS 0409 total' next to its HTS-10 lines)."""
    raws = [variety_raw] if isinstance(variety_raw, str) or variety_raw is None else list(variety_raw)
    return bool(terms and terms.strip().lower().endswith("total")) or any(
        r and "(all lines)" in r.lower() for r in raws)


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


@dataclass
class PriceFilters:
    price_type: str | None
    origins: list[str]
    varieties: list[str]
    markets: list[str]
    sources: list[str]
    color_grades: list[str]
    date_from: date | None
    date_to: date | None
    include_small: bool = False


# Customs unit values of small consignments (samples, retail jars, a few drums) are not bulk
# prices: below this declared weight they are left out of series, latest values, comparisons and
# the overview unless the user asks for them (?small=true). Half a 20 t container.
MIN_BULK_UNIT_VALUE_KG = 10_000.0


def bulk_unit_value_clause(model):
    """SQL condition keeping quotations and bulk-size customs unit values (weight unknown = kept)."""
    return or_(
        model.price_type.not_in(UNIT_VALUE_TYPES),
        model.volume_kg.is_(None),
        model.volume_kg >= MIN_BULK_UNIT_VALUE_KG,
    )


def _split(values: list[str] | None) -> list[str]:
    """Accept both repeated params (?origin=ARG&origin=UKR) and comma lists (?origin=ARG,UKR)."""
    out: list[str] = []
    for v in values or []:
        out.extend(x.strip() for x in v.split(",") if x.strip())
    return out


def _month_end(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def parse_period_bound(value: str | None, *, end: bool) -> date | None:
    """'2026', '2026-09', '2026-Q3' or '2026-09-15' -> first (or last) day of that period."""
    if not value:
        return None
    s = value.strip()
    try:
        if re.fullmatch(r"\d{4}", s):
            y = int(s)
            return date(y, 12, 31) if end else date(y, 1, 1)
        if mm := re.fullmatch(r"(\d{4})-(\d{1,2})", s):
            y, m = int(mm[1]), int(mm[2])
            return _month_end(y, m) if end else date(y, m, 1)
        if mq := re.fullmatch(r"(\d{4})-?Q([1-4])", s, re.IGNORECASE):
            y, q = int(mq[1]), int(mq[2])
            return _month_end(y, q * 3) if end else date(y, q * 3 - 2, 1)
        return date.fromisoformat(s)
    except ValueError as exc:
        raise HTTPException(422, f"Invalid period '{value}'. Use YYYY, YYYY-MM, YYYY-Qn or YYYY-MM-DD.") from exc


def price_filters(
    price_type: str | None = Query(None, description="One PriceType value"),
    origin: list[str] | None = Query(None, description="ISO3 of the honey's origin (repeatable). '_none' = not specified"),
    variety: list[str] | None = Query(None),
    market: list[str] | None = Query(None, description="ISO3 of the market where the price is observed"),
    source: list[str] | None = Query(None, description="Source key"),
    color_grade: list[str] | None = Query(None),
    date_from: str | None = Query(None, alias="from", description="YYYY, YYYY-MM, YYYY-Qn or ISO date"),
    date_to: str | None = Query(None, alias="to"),
    small: bool = Query(False, description="Include customs unit values of consignments under 10 t"),
) -> PriceFilters:
    if price_type is not None and price_type not in PRICE_TYPES:
        raise HTTPException(422, f"Unknown price_type '{price_type}'. Allowed: {', '.join(PRICE_TYPES)}")
    return PriceFilters(
        price_type=price_type,
        origins=[o.upper() if o != NONE_TOKEN else o for o in _split(origin)],
        varieties=_split(variety),
        markets=[o.upper() if o != NONE_TOKEN else o for o in _split(market)],
        sources=_split(source),
        color_grades=_split(color_grade),
        date_from=parse_period_bound(date_from, end=False),
        date_to=parse_period_bound(date_to, end=True),
        include_small=small,
    )


def _require_type(f: PriceFilters) -> str:
    if not f.price_type:
        raise HTTPException(422, "price_type is required: different kinds of price are never mixed in one series.")
    return f.price_type


def _in_or_null(col, values: list[str]):
    real = [v for v in values if v != NONE_TOKEN]
    conds = []
    if real:
        conds.append(col.in_(real))
    if NONE_TOKEN in values:
        conds.append(col.is_(None))
    return or_(*conds)


def _source_ids(db: Session, keys: list[str]) -> list[int]:
    if not keys:
        return []
    return list(db.scalars(select(Source.id).where(Source.key.in_(keys))))


def apply_filters(q, f: PriceFilters, db: Session, *, skip: Iterable[str] = (), use_from: bool = True):
    """Current, demo-aware rows matching `f`. `skip` drops dimensions (used for facet counts)."""
    skip = set(skip)
    q = q.where(M.is_current.is_(True), demo_clause(M, db))
    if not f.include_small:
        q = q.where(bulk_unit_value_clause(M))
    if f.price_type and "price_type" not in skip:
        q = q.where(M.price_type == f.price_type)
    if f.origins and "origin" not in skip:
        q = q.where(_in_or_null(M.origin_iso3, f.origins))
    if f.varieties and "variety" not in skip:
        q = q.where(M.variety.in_(f.varieties))
    if f.markets and "market" not in skip:
        q = q.where(_in_or_null(M.market_iso3, f.markets))
    if f.sources and "source" not in skip:
        q = q.where(M.source_id.in_(_source_ids(db, f.sources)))
    if f.color_grades and "color_grade" not in skip:
        q = q.where(_in_or_null(M.color_grade, f.color_grades))
    if "period" not in skip:
        # A row belongs to the window when its period overlaps it.
        if f.date_from and use_from:
            q = q.where(M.period_end >= f.date_from)
        if f.date_to:
            q = q.where(M.period_start <= f.date_to)
    return q


def _currency(value: str | None) -> Currency:
    v = (value or "USD").upper()
    if v not in ("USD", "EUR", "ORIGINAL"):
        raise HTTPException(422, "currency must be USD, EUR or original")
    return v  # type: ignore[return-value]


def _freq(value: str | None) -> str:
    v = (value or "M").upper()
    if v not in ("M", "Q", "A"):
        raise HTTPException(422, "freq must be M, Q or A")
    return v


# ---------------------------------------------------------------------------
# Periods
# ---------------------------------------------------------------------------


def bucket(d: date, freq: str) -> tuple[str, date, date]:
    """(label, start, end) of the period of frequency `freq` containing `d`."""
    if freq == "A":
        return str(d.year), date(d.year, 1, 1), date(d.year, 12, 31)
    if freq == "Q":
        q = (d.month - 1) // 3 + 1
        return f"{d.year}-Q{q}", date(d.year, q * 3 - 2, 1), _month_end(d.year, q * 3)
    return f"{d.year}-{d.month:02d}", date(d.year, d.month, 1), _month_end(d.year, d.month)


def shift_label(label: str, freq: str, steps: int) -> str:
    """Move a bucket label by `steps` periods of `freq` ('2026-01', M, -1 -> '2025-12')."""
    if freq == "A":
        return str(int(label) + steps)
    if freq == "Q":
        y, q = int(label[:4]), int(label[-1])
        idx = y * 4 + (q - 1) + steps
        return f"{idx // 4}-Q{idx % 4 + 1}"
    y, m = int(label[:4]), int(label[5:7])
    idx = y * 12 + (m - 1) + steps
    return f"{idx // 12}-{idx % 12 + 1:02d}"


PERIODS_PER_YEAR = {"M": 12, "Q": 4, "A": 1}


# ---------------------------------------------------------------------------
# Conversion & series building
# ---------------------------------------------------------------------------


def _r(v: float | None, n: int = 4) -> float | None:
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(v, n)


def convert_row(r: PriceObservation, currency: Currency) -> dict:
    """Per-kg value/low/high of a row in `currency`, from the stored normalised fields.

    `price_per_kg` is the per-kg price in the source currency; `usd_per_kg`/`eur_per_kg` are
    the FX-normalised versions written at ingest. Low/high are scaled by the same factor
    (stored per-kg value / published value), so the unit and the FX rate are applied exactly
    as they were for the main value.
    """
    if currency == "ORIGINAL" or r.currency == currency:
        base, ccy = r.price_per_kg, r.currency
    else:
        base, ccy = (r.usd_per_kg if currency == "USD" else r.eur_per_kg), currency
    if base is None:
        return {"value": None, "low": None, "high": None, "currency": ccy, "fx_missing": True}
    factor = base / r.price_value if r.price_value else None
    low = r.price_low * factor if (factor is not None and r.price_low is not None) else None
    high = r.price_high * factor if (factor is not None and r.price_high is not None) else None
    return {"value": base, "low": low, "high": high, "currency": ccy, "fx_missing": False}


def _most_cautious(statuses: Iterable[str]) -> str | None:
    st = set(statuses)
    for s in STATUS_CAUTION:
        if s.value in st:
            return s.value
    return next(iter(st), None)


def _mean(vals: list[float]) -> float | None:
    return sum(vals) / len(vals) if vals else None


def _wmean(pairs: list[tuple[float, float]]) -> float | None:
    """Weighted mean of (value, weight) pairs: for unit values, total value / total weight."""
    total = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / total if pairs and total > 0 else None


def _row_weight(r: PriceObservation) -> float | None:
    """Declared volume behind a customs unit value (None for quotations, or when not declared)."""
    return r.volume_kg if r.price_type in UNIT_VALUE_TYPES and r.volume_kg and r.volume_kg > 0 else None


def _bucket_date(r: PriceObservation) -> date:
    """Date that decides a row's month: an ISO week (Monday start) counts in the month of its
    Thursday, where most of its days fall, so week 36/2026 (31 Aug - 6 Sep) is September."""
    return r.period_start + timedelta(days=3) if r.frequency == "W" else r.period_start


def _bucket_date_sql():
    """`_bucket_date` in SQL (an ISO 'YYYY-MM-DD' string)."""
    return case((M.frequency == "W", func.date(M.period_start, "+3 days")), else_=func.date(M.period_start))


def _combine(items: list[dict], label: str, start: date, end: date, expected: int | None) -> dict:
    """Average of `items` (already converted): volume-weighted when every item carries a declared
    volume (customs unit values), else a simple average. Low/high only when every item has them."""
    have = [i for i in items if i["value"] is not None]
    weighted = bool(have) and all(i.get("weight") for i in have)
    lows = [i["low"] for i in have if i["low"] is not None]
    highs = [i["high"] for i in have if i["high"] is not None]
    o_items = [i for i in items if i.get("original")]
    origs = [i["original"] for i in o_items]
    original = None
    if origs and len({(o["currency"], o["unit"]) for o in origs}) == 1:
        ol = [o["low"] for o in origs if o["low"] is not None]
        oh = [o["high"] for o in origs if o["high"] is not None]
        o_weighted = all(i.get("weight") for i in o_items)
        original = {
            "value": _r(_wmean([(i["original"]["value"], i["weight"]) for i in o_items]) if o_weighted
                        else _mean([o["value"] for o in origs])),
            "low": _r(_mean(ol)) if len(ol) == len(origs) else None,
            "high": _r(_mean(oh)) if len(oh) == len(origs) else None,
            "currency": origs[0]["currency"], "unit": origs[0]["unit"],
        }
    latest = max(items, key=lambda i: (i["period_start"], i["published_at"] or "", i["collected_at"] or ""))
    pubs = [i["published_at"] for i in items if i["published_at"]]
    cols = [i["collected_at"] for i in items if i["collected_at"]]
    value = (_wmean([(i["value"], i["weight"]) for i in have]) if weighted
             else _mean([i["value"] for i in have]))
    return {
        "period_label": label,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "value": _r(value),
        "low": _r(_mean(lows)) if have and len(lows) == len(have) else None,
        "high": _r(_mean(highs)) if have and len(highs) == len(have) else None,
        "original": original,
        "n_points": len(have),
        "expected_points": expected,
        "weighting": "volume" if weighted else "simple",
        "volume_kg": _r(sum(i["weight"] for i in have), 1) if weighted else None,
        "periods": sorted({p for i in items for p in i.get("periods", [i["period_label"]])}),
        "fx_missing": len(items) - len(have),
        "published_at": max(pubs) if pubs else None,
        "collected_at": max(cols) if cols else None,
        "source_url": latest["source_url"],
        "fx_date": latest.get("fx_date"),
        "data_status": _most_cautious(i["data_status"] for i in items),
        "is_demo": any(i["is_demo"] for i in items),
    }


def _row_item(r: PriceObservation, currency: Currency) -> dict:
    c = convert_row(r, currency)
    return {
        "period_label": r.period_label,
        "period_start": r.period_start,
        "value": c["value"], "low": c["low"], "high": c["high"], "currency": c["currency"],
        "original": {"value": r.price_value, "low": r.price_low, "high": r.price_high,
                     "currency": r.currency, "unit": r.unit},
        "weight": _row_weight(r),
        "published_at": iso(r.published_at), "collected_at": iso(r.collected_at),
        "source_url": r.source_url, "fx_date": iso(r.fx_date),
        "data_status": r.data_status, "is_demo": r.is_demo,
    }


def series_key(r: PriceObservation, currency: Currency) -> tuple:
    # market_location keeps apart prices that differ only by state/province (e.g. USDA producer
    # prices: origin = market = USA for every state), as in overview.py and countries.py.
    key = (r.source_id, r.price_type, r.origin_iso3, r.market_iso3, r.market_location, r.variety, r.color_grade,
           r.terms, bool(r.organic))
    bf = _base_freq(r.frequency)
    if bf != "M":
        # Annual / quarterly rows never merge with monthly ones (UN Comtrade publishes both for one
        # pair): an annual figure averaged with its own months is not a price. Monthly-based series
        # (D, W, irregular, M) keep their ids.
        key += (bf,)
    return key + ((r.currency,) if currency == "ORIGINAL" else ())


def _series_key_sql(currency: Currency) -> list:
    """SQL expressions of `series_key`, in the same order (used to bound queries per series)."""
    cols = [M.source_id, M.price_type, M.origin_iso3, M.market_iso3, M.market_location, M.variety, M.color_grade,
            M.terms, func.coalesce(M.organic, False), case((M.frequency == "Q", "Q"), (M.frequency == "A", "A"), else_="M")]
    return cols + ([M.currency] if currency == "ORIGINAL" else [])


def _key_from_sql(row, currency: Currency) -> tuple:
    """`series_key` rebuilt from a row of `_series_key_sql` columns."""
    key = tuple(row[:8]) + (bool(row[8]),)
    if row[9] != "M":
        key += (row[9],)
    return key + ((row[10],) if currency == "ORIGINAL" else ())


def series_id(key: tuple) -> str:
    return hashlib.sha1("|".join("" if k is None else str(k) for k in key).encode()).hexdigest()[:12]


def _base_freq(f: str | None) -> str:
    """Bucket frequency of a row: daily, weekly and irregular quotes are bucketed by month."""
    return RANK_FREQ[max(FREQ_RANK.get(f, 2), 2)]  # type: ignore[arg-type]


def native_freq(rows: list[PriceObservation]) -> str:
    return max((r.frequency for r in rows), key=lambda f: FREQ_RANK.get(f, 2))


def _eff_freq(nat: str, freq: str) -> tuple[str, str]:
    """(base bucket frequency, effective output frequency) of a series of native frequency `nat`."""
    base_rank = max(FREQ_RANK.get(nat, 2), 2)
    return RANK_FREQ[base_rank], RANK_FREQ[max(base_rank, FREQ_RANK[freq])]


def build_points(rows: list[PriceObservation], currency: Currency, freq: str) -> tuple[list[dict], str]:
    """Rows of one series -> points at `freq` (or the series' own, coarser frequency)."""
    base_f, eff_f = _eff_freq(native_freq(rows), freq)

    # 1) collapse raw rows into their own monthly/quarterly/annual period
    base_groups: dict[str, list[dict]] = defaultdict(list)
    base_bounds: dict[str, tuple[date, date]] = {}
    finest: dict[str, str] = {}
    for r in rows:
        label, s, e = bucket(_bucket_date(r), base_f)
        base_groups[label].append(_row_item(r, currency))
        base_bounds[label] = (s, e)
        rf = _base_freq(r.frequency)
        if FREQ_RANK[rf] < FREQ_RANK[finest.get(label, base_f)]:
            finest[label] = rf
    base_points = []
    for label in sorted(base_groups):
        s, e = base_bounds[label]
        # Defence in depth: a bucket built from finer rows always says how many it expected.
        fin = finest.get(label, base_f)
        exp = PERIODS_PER_YEAR[base_f] // PERIODS_PER_YEAR[fin] if fin != base_f else None
        p = _combine(base_groups[label], label, s, e, exp)
        p["_start"] = s
        base_points.append(p)
    if eff_f == base_f:
        for p in base_points:
            p.pop("_start")
        return base_points, eff_f

    # 2) average the available sub-periods (never fills a missing month); unit values stay
    #    weighted by each month's volume
    expected = PERIODS_PER_YEAR[base_f] // PERIODS_PER_YEAR[eff_f]
    groups: dict[str, list[dict]] = defaultdict(list)
    bounds: dict[str, tuple[date, date]] = {}
    for p in base_points:
        label, s, e = bucket(p.pop("_start"), eff_f)
        p["period_start"] = date.fromisoformat(p["period_start"])
        p["weight"] = p["volume_kg"]
        groups[label].append(p)
        bounds[label] = (s, e)
    out = []
    for label in sorted(groups):
        s, e = bounds[label]
        out.append(_combine(groups[label], label, s, e, expected))
    return out, eff_f


def _series_weighting(points: list[dict]) -> str:
    kinds = {p["weighting"] for p in points if p["value"] is not None}
    return kinds.pop() if len(kinds) == 1 else ("mixed" if kinds else "simple")


def _freshness_of(latest: PriceObservation, source: Source | None, freq: str, today: date | None = None) -> dict:
    """Age of the newest point against the source's own publication rhythm."""
    today = today or date.today()
    ref = latest.published_at or latest.period_end
    cadence = source.expected_max_age_days if source and source.expected_max_age_days else None
    basis = "source"
    if not cadence:
        cadence, basis = DEFAULT_CADENCE_DAYS.get(freq, 45), "frequency"
    age = (today - ref).days
    status = "current" if age <= cadence else "aging" if age <= cadence * 1.5 else "stale"
    return {"status": status, "age_days": age, "reference_date": ref.isoformat(),
            "expected_max_age_days": cadence, "basis": basis}


def _priority_rank(iso3: str | None) -> int:
    try:
        return PRIORITY_ISO3.index(iso3)  # type: ignore[arg-type]
    except ValueError:
        return len(PRIORITY_ISO3)


def build_series(db: Session, rows: list[PriceObservation], currency: Currency, freq: str,
                 points_for: set[str] | None = None) -> list[dict]:
    """One entry per series. With `points_for`, only those series ids carry their points; the
    others carry metadata only (`points_omitted`), which is much cheaper to build and ship."""
    sources = {s.id: s for s in db.scalars(select(Source))}
    groups: dict[tuple, list[PriceObservation]] = defaultdict(list)
    for r in rows:
        groups[series_key(r, currency)].append(r)
    out = []
    for key, grp in groups.items():
        sid = series_id(key)
        grp.sort(key=lambda r: (r.period_start, r.published_at or date.min))
        nat = native_freq(grp)
        omitted = points_for is not None and sid not in points_for
        if omitted:
            eff = _eff_freq(nat, freq)[1]
            labels = sorted({bucket(_bucket_date(r), eff)[0] for r in grp})
            points: list[dict] = []
            meta = {"n_points": len(labels), "first_period": labels[0], "last_period": labels[-1],
                    "weighting": None, "fx_missing_points": None,
                    "has_range": any(r.price_low is not None and r.price_high is not None for r in grp)}
        else:
            points, eff = build_points(grp, currency, freq)
            meta = {"n_points": len(points), "first_period": points[0]["period_label"],
                    "last_period": points[-1]["period_label"], "weighting": _series_weighting(points),
                    "fx_missing_points": sum(1 for p in points if p["value"] is None),
                    "has_range": any(p["low"] is not None and p["high"] is not None for p in points)}
        latest_row = max(grp, key=lambda r: (r.period_start, r.published_at or date.min, r.collected_at))
        src = sources.get(latest_row.source_id)
        pubs = [r.published_at for r in grp if r.published_at]
        out.append({
            "id": sid,
            "source": source_brief(src),
            "price_type": latest_row.price_type,
            "origin_iso3": latest_row.origin_iso3,
            "origin_label": latest_row.origin_label,
            "market_iso3": latest_row.market_iso3,
            "market_location": latest_row.market_location,
            "variety": latest_row.variety,
            "variety_raw": sorted({r.variety_raw for r in grp if r.variety_raw}),
            "color_grade": latest_row.color_grade,
            "terms": latest_row.terms,
            "organic": bool(latest_row.organic),
            "currency": latest_row.currency if currency == "ORIGINAL" else currency,
            "unit": "kg",
            "native_frequency": nat,
            "freq": eff,
            "n_points": meta["n_points"],
            "first_period": meta["first_period"],
            "last_period": meta["last_period"],
            "weighting": meta["weighting"],
            "published_at": iso(max(pubs)) if pubs else None,
            "collected_at": iso(max(r.collected_at for r in grp)),
            "source_url": latest_row.source_url,
            "data_status": _most_cautious(r.data_status for r in grp),
            "data_statuses": sorted({r.data_status for r in grp}),
            "reliability": latest_row.reliability,
            "is_demo": any(r.is_demo for r in grp),
            "has_range": meta["has_range"],
            "fx_missing_points": meta["fx_missing_points"],
            "freshness": _freshness_of(latest_row, src, nat),
            "points": points,
            "points_omitted": omitted,
        })
    out.sort(key=lambda s: (_priority_rank(s["origin_iso3"]), s["origin_iso3"] or "~", s["variety"],
                            s["color_grade"] or "", (s["source"] or {}).get("key", ""), s["id"]))
    return out


def _sources_summary(series: list[dict]) -> list[dict]:
    by: dict[str, dict] = {}
    for s in series:
        src = s["source"] or {"key": "?", "name": "?"}
        e = by.setdefault(src["key"], {**src, "n_series": 0, "published_at": None, "collected_at": None,
                                        "source_url": None, "is_demo": False, "freshness": None})
        e["n_series"] += 1
        e["is_demo"] = e["is_demo"] or s["is_demo"]
        if s["published_at"] and (e["published_at"] is None or s["published_at"] > e["published_at"]):
            e["published_at"], e["source_url"] = s["published_at"], s["source_url"] or e["source_url"]
        if e["collected_at"] is None or (s["collected_at"] or "") > e["collected_at"]:
            e["collected_at"] = s["collected_at"]
        # the freshest series speaks for the source
        f = s["freshness"]
        if e["freshness"] is None or f["age_days"] < e["freshness"]["age_days"]:
            e["freshness"] = f
        e["source_url"] = e["source_url"] or s["source_url"]
    return list(by.values())


# ---------------------------------------------------------------------------
# Discrepancies
# ---------------------------------------------------------------------------


def find_discrepancies(db: Session, rows: list[PriceObservation], currency: Currency,
                       threshold: float = DISCREPANCY_THRESHOLD) -> list[dict]:
    """Same origin, variety, colour, organic status, price type, market and period from >= 2
    sources differing > threshold.

    Like for like only: within one source, rows of different lines (`terms`: a total and its
    HTS-10 sub-lines, drums vs buckets ...) are never averaged together. Each source contributes
    ONE line: its total/aggregate line when it has one (largest declared volume, or terms ending
    in "total"), and its other lines are listed apart (`other_lines`), not compared. Values are
    compared per kg in a common currency (USD when `currency` is 'original'); customs unit values
    are volume-weighted within the period. Demo rows are only compared with demo rows. Nothing is
    resolved: every source's value is returned with its provenance.
    """
    cmp_ccy: Currency = "USD" if currency == "ORIGINAL" else currency
    sources = {s.id: s for s in db.scalars(select(Source))}
    groups: dict[tuple, dict[int, dict[str | None, list[PriceObservation]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list)))
    for r in rows:
        label, _, _ = bucket(_bucket_date(r), _base_freq(r.frequency))
        gk = (r.price_type, r.origin_iso3, r.variety, r.color_grade, bool(r.organic), r.market_iso3, label, r.is_demo)
        groups[gk][r.source_id][r.terms].append(r)

    def line_value(rs: list[PriceObservation]) -> tuple[float | None, int, str]:
        pairs = [(v, _row_weight(r)) for r in rs if (v := convert_row(r, cmp_ccy)["value"]) is not None]
        if pairs and all(w for _, w in pairs):
            return _wmean(pairs), len(pairs), "volume"     # type: ignore[arg-type]
        return _mean([v for v, _ in pairs]), len(pairs), "simple"

    def line_rank(item: tuple[str | None, list[PriceObservation]]) -> tuple:
        terms, rs = item
        vols = [r.volume_kg for r in rs]
        full = all(v is not None and v > 0 for v in vols)
        return (full, sum(vols) if full else 0.0, _is_total_line(terms), len(rs), terms or "")  # type: ignore[arg-type]

    out = []
    for (pt, origin, variety, color, organic, market, label, demo), by_src in groups.items():
        if len(by_src) < 2:
            continue
        entries = []
        for sid, lines in by_src.items():
            valued = {t: rs for t, rs in lines.items() if any(convert_row(r, cmp_ccy)["value"] is not None for r in rs)}
            if not valued:
                continue
            terms, rs = max(valued.items(), key=line_rank)
            value, n, weighting = line_value(rs)
            others = []
            for t, ors in sorted(valued.items(), key=lambda x: x[0] or ""):
                if t != terms:
                    ov, on, _ = line_value(ors)
                    others.append({"terms": t, "value": _r(ov), "n_rows": on})
            latest = max(rs, key=lambda r: (r.published_at or date.min, r.collected_at))
            entries.append({
                "source": source_brief(sources.get(sid)),
                "value": _r(value),
                "n_rows": n,
                "weighting": weighting,
                "color_grades": [color] if color else [],
                "terms": [terms] if terms else [],
                "other_lines": others,
                "published_at": iso(latest.published_at),
                "collected_at": iso(latest.collected_at),
                "source_url": latest.source_url,
                "data_status": _most_cautious(r.data_status for r in rs),
                "is_demo": demo,
            })
        if len(entries) < 2:
            continue
        lo, hi = min(e["value"] for e in entries), max(e["value"] for e in entries)
        if lo <= 0 or (hi - lo) / lo <= threshold:
            continue
        entries.sort(key=lambda e: e["value"])
        out.append({
            "price_type": pt, "origin_iso3": origin, "variety": variety, "color_grade": color, "organic": organic,
            "market_iso3": market, "period_label": label, "currency": cmp_ccy, "unit": "kg",
            "min": lo, "max": hi, "spread_pct": round((hi - lo) / lo * 100, 1),
            "threshold_pct": round(threshold * 100), "is_demo": demo, "entries": entries,
        })
    out.sort(key=lambda d: (d["period_label"], d["spread_pct"]), reverse=True)
    return out


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


def _rows(db: Session, f: PriceFilters, *conds, **kw) -> list[PriceObservation]:
    q = apply_filters(select(M), f, db, **kw).where(*conds).options(*_UNUSED_COLUMNS)
    return list(db.scalars(q.order_by(M.period_start, M.id)))


def _latest_rows(db: Session, f: PriceFilters, currency: Currency) -> list[PriceObservation]:
    """Only the recent stretch of each series that `latest` needs: rows from 1 January of the year
    before the series' newest period (minus a week, for ISO weeks counted by their Thursday). That
    covers the previous and the year-ago point at M, Q and A. Bounded per series in SQL, so a
    series last seen years ago keeps its own last stretch."""
    inner = apply_filters(select(M.id.label("id"), M.period_start.label("ps"), func.max(M.period_start).over(
        partition_by=_series_key_sql(currency)).label("max_ps")), f, db, use_from=False).subquery()
    keep = select(inner.c.id).where(inner.c.ps >= func.date(inner.c.max_ps, "start of year", "-1 year", "-7 days"))
    return list(db.scalars(select(M).where(M.id.in_(keep)).options(*_UNUSED_COLUMNS).order_by(M.period_start, M.id)))


def _series_index(db: Session, f: PriceFilters, currency: Currency) -> dict[str, dict]:
    """Every series matching `f`, from one grouped query: id -> dimensions and newest period label
    (as `build_series` would label it), without loading the rows."""
    cols = _series_key_sql(currency)
    newest = func.max(_bucket_date_sql())
    demo = func.max(case((M.is_demo.is_(True), 1), else_=0))
    out = {}
    for row in db.execute(apply_filters(select(*cols, newest, demo), f, db).group_by(*cols)):
        key = _key_from_sql(row, currency)
        last = row[-2] if isinstance(row[-2], date) else date.fromisoformat(str(row[-2])[:10])
        out[series_id(key)] = {"source_id": row[0], "origin_iso3": row[2], "market_iso3": row[3], "variety": row[5],
                               "is_demo": bool(row[-1]), "last_period": bucket(last, row[9])[0]}
    return out


@router.get("/facets")
def facets(f: PriceFilters = Depends(price_filters), db: Session = Depends(get_db)):
    """What exists, with counts, so the interface only offers filters that have data.

    Price-type counts ignore the other filters (the type selector is always complete); every
    other facet applies all filters except its own dimension.
    """
    sources = {s.id: s for s in db.scalars(select(Source))}
    countries = {c.iso3: c for c in db.scalars(select(Country))}

    def counts(col, dim: str):
        q = apply_filters(select(col, func.count()).group_by(col), f, db, skip=(dim,))
        return [(k, n) for k, n in db.execute(q)]

    pt_q = select(M.price_type, func.count(), func.min(M.period_start), func.max(M.period_end)).where(
        M.is_current.is_(True), demo_clause(M, db)).group_by(M.price_type)
    pt_counts = {k: (n, lo, hi) for k, n, lo, hi in db.execute(pt_q)}
    price_types = [{"key": k, "count": pt_counts.get(k, (0,))[0],
                    "min_period": iso(pt_counts[k][1]) if k in pt_counts else None,
                    "max_period": iso(pt_counts[k][2]) if k in pt_counts else None} for k in PRICE_TYPES]

    def country_facet(col, dim):
        out = []
        for k, n in counts(col, dim):
            c = countries.get(k) if k else None
            out.append({"key": k or NONE_TOKEN, "count": n, "priority": bool(c and c.priority),
                        "name_it": c.name_it if c else None, "name_en": c.name_en if c else None})
        out.sort(key=lambda x: (_priority_rank(None if x["key"] == NONE_TOKEN else x["key"]), -x["count"], x["key"]))
        return out

    src_facet = []
    for sid, n in counts(M.source_id, "source"):
        s = sources.get(sid)
        if s:
            src_facet.append({**source_brief(s), "count": n, "expected_update": s.expected_update,
                              "expected_update_en": s.expected_update_en,
                              "latest_published_at": iso(s.latest_published_at)})
    src_facet.sort(key=lambda x: -x["count"])

    base = apply_filters(select(M), f, db).subquery()
    total, lo, hi, n_usd, n_eur, n_range = db.execute(select(
        func.count(), func.min(base.c.period_start), func.max(base.c.period_end),
        func.count(base.c.usd_per_kg), func.count(base.c.eur_per_kg), func.count(base.c.price_low),
    )).one()
    demo_n = db.scalar(select(func.count()).select_from(base).where(base.c.is_demo.is_(True))) or 0
    ccy = db.execute(select(base.c.currency, func.count()).group_by(base.c.currency)).all()
    freqs = db.execute(select(base.c.frequency, func.count()).group_by(base.c.frequency)).all()

    return {
        "scoped_to": f.price_type,
        "total": total,
        "price_types": price_types,
        "origins": country_facet(M.origin_iso3, "origin"),
        "markets": country_facet(M.market_iso3, "market"),
        "varieties": sorted(({"key": k, "count": n} for k, n in counts(M.variety, "variety")), key=lambda x: -x["count"]),
        "sources": src_facet,
        "color_grades": sorted(({"key": k or NONE_TOKEN, "count": n} for k, n in counts(M.color_grade, "color_grade")),
                               key=lambda x: -x["count"]),
        "currencies": [{"key": k, "count": n} for k, n in ccy],
        "frequencies": [{"key": k, "count": n} for k, n in freqs],
        "conversions": {"USD": n_usd, "EUR": n_eur},
        "has_ranges": bool(n_range),
        "demo_rows": demo_n,
        "period": {"min": iso(lo), "max": iso(hi)},
    }


@router.get("/series")
def series(
    f: PriceFilters = Depends(price_filters),
    currency: str = Query("USD", description="USD | EUR | original"),
    freq: str = Query("M", description="M | Q | A"),
    ids: list[str] | None = Query(None, description="Series ids whose points to return (repeatable or comma list); "
                                                    "others come back as metadata only. Default: every series."),
    db: Session = Depends(get_db),
):
    """Time series for ONE price type, one line per (source, origin, market, market location, variety, colour,
    terms, organic, and period granularity when coarser than monthly)."""
    pt = _require_type(f)
    ccy, fq = _currency(currency), _freq(freq)
    if f.date_from and fq != "M":
        # widen to the start of the quarter/year so the first bucket is not artificially partial
        f.date_from = bucket(f.date_from, fq)[1]
    rows = _rows(db, f)
    want = set(_split(ids)) if ids else None
    data = build_series(db, rows, ccy, fq, points_for=want)
    return {
        "price_type": pt,
        "currency": "original" if ccy == "ORIGINAL" else ccy,
        "unit": "kg",
        "freq": fq,
        "from": iso(f.date_from),
        "to": iso(f.date_to),
        "aggregation": "mean_of_available_months" if fq != "M" else "monthly_mean_of_observations",
        "weighting": "volume_for_unit_values" if pt in UNIT_VALUE_TYPES else "simple",
        "series": data,
        "sources": _sources_summary(data),
        "discrepancies": find_discrepancies(db, rows, ccy),
        "today": date.today().isoformat(),
    }


def _point_ref(p: dict | None) -> dict | None:
    if p is None:
        return None
    return {"period_label": p["period_label"], "value": p["value"], "n_points": p["n_points"],
            "published_at": p["published_at"]}


def _pct(curr: float | None, prev: float | None) -> float | None:
    if curr is None or prev is None or prev == 0:
        return None
    return round((curr - prev) / prev * 100, 2)


@router.get("/latest")
def latest(
    f: PriceFilters = Depends(price_filters),
    currency: str = Query("USD"),
    freq: str = Query("M"),
    db: Session = Depends(get_db),
):
    """Latest point per series, with change vs the previous period and vs a year earlier.

    Changes are computed only against the exact previous period and the exact same period one
    year earlier; when either is missing the change is null (never extrapolated). `from` is
    ignored here so the year-ago comparison is always available when it exists; `to` acts as
    an "as of" date. Only each series' recent stretch is loaded (`_latest_rows`), so series-level
    lists such as `variety_raw` describe that stretch.
    """
    pt = _require_type(f)
    ccy, fq = _currency(currency), _freq(freq)
    rows = _latest_rows(db, f, ccy)
    out = []
    for s in build_series(db, rows, ccy, fq):
        pts = {p["period_label"]: p for p in s["points"]}
        last = s["points"][-1]
        eff = s["freq"]
        prev = pts.get(shift_label(last["period_label"], eff, -1))
        year_ago = pts.get(shift_label(last["period_label"], eff, -PERIODS_PER_YEAR[eff]))
        fr = s["freshness"]
        out.append({
            "series_id": s["id"],
            **{k: s[k] for k in ("source", "price_type", "origin_iso3", "origin_label", "market_iso3",
                                 "market_location", "variety", "variety_raw", "color_grade", "terms", "organic",
                                 "currency", "unit", "native_frequency", "freq", "reliability", "is_demo")},
            "latest": last,
            "period_label": last["period_label"],
            "published_at": last["published_at"],
            "collected_at": last["collected_at"],
            "source_url": last["source_url"],
            "data_status": last["data_status"],
            "previous": _point_ref(prev),
            "year_ago": _point_ref(year_ago),
            "change_prev_pct": _pct(last["value"], prev["value"] if prev else None),
            "change_yoy_pct": _pct(last["value"], year_ago["value"] if year_ago else None),
            "freshness": fr,
            "is_stale": fr["status"] in ("aging", "stale"),
        })
    return {"price_type": pt, "currency": "original" if ccy == "ORIGINAL" else ccy, "unit": "kg", "freq": fq,
            "rows": out, "today": date.today().isoformat()}


@router.get("/compare")
def compare(
    f: PriceFilters = Depends(price_filters),
    by: str = Query("origin", description="origin | variety"),
    period: str = Query("latest", description="'latest' or YYYY-MM"),
    window: int = Query(DEFAULT_COMPARE_WINDOW, ge=1, le=24, description="months back from the reference month"),
    currency: str = Query("USD"),
    db: Session = Depends(get_db),
):
    """One bar per origin (or variety) AND market: each series' latest point inside the window.

    Every bar states its own period(s). When several series fall under one bar (e.g. two
    varieties from Argentina sold in the USA) the bar is their simple average and lists its
    components. Never averaged together (each left out is listed in `excluded` with a reason):
    different markets (separate bars); demo and real series (separate bars, `is_demo`); a
    source's all-lines total and its own sub-lines (`component_of_total`); US Census and USDA FAS
    GATS, which publish the same Census statistics (`same_underlying_data`: per origin/market the
    source with the newer period is kept, Census on a tie); an aggregate market
    such as EU27 when bars for its member states are shown (`aggregate_of_shown_markets`); an
    aggregate origin inside a variety bar that holds its member origins (`aggregate_of_shown_origins`).
    `key` stays the origin (or variety) code; `id` is unique per bar.
    """
    pt = _require_type(f)
    if by not in ("origin", "variety"):
        raise HTTPException(422, "by must be origin or variety")
    ccy = _currency(currency)
    if ccy == "ORIGINAL":
        raise HTTPException(422, "compare needs a common currency (USD or EUR)")
    f.date_from = None
    if period == "latest":
        newest = db.scalar(apply_filters(select(func.max(_bucket_date_sql())), f, db))
        anchor = None if newest is None else date.fromisoformat(str(newest)[:10])
        if anchor is None:
            return {"by": by, "price_type": pt, "currency": ccy, "unit": "kg", "period": period, "window_months": window,
                    "anchor_period": None, "window_from": None, "window_to": None, "bars": [], "excluded": []}
    else:
        anchor = parse_period_bound(period, end=False)
    anchor_label = bucket(anchor, "M")[0]
    win_from = date.fromisoformat(shift_label(anchor_label, "M", -(window - 1)) + "-01")
    win_to = bucket(anchor, "M")[2]
    f_all = PriceFilters(**{**f.__dict__, "date_from": None, "date_to": win_to})
    sources = {s.id: s for s in db.scalars(select(Source))}
    index = _series_index(db, f_all, ccy)       # every series up to the window end (one grouped query)
    # Bars only need the window's rows (an ISO week counts by its Thursday: start 6 days early).
    all_series = build_series(db, _rows(db, f_all, M.period_start >= win_from - timedelta(days=6)), ccy, "M")

    def bar_key(c: dict) -> str:
        return (c["origin_iso3"] or NONE_TOKEN) if by == "origin" else c["variety"]

    excluded: list[dict] = []

    def exclude(c: dict, reason: str, last_period: str | None) -> None:
        excluded.append({"key": bar_key(c), "series_id": c["series_id"], "variety": c["variety"],
                         "origin_iso3": c["origin_iso3"], "market_iso3": c["market_iso3"], "source": c["source"],
                         "last_period": last_period, "is_demo": bool(c.get("is_demo")), "reason": reason})

    comps: list[dict] = []
    built = set()
    for s in all_series:
        built.add(s["id"])
        in_win = [p for p in s["points"] if p["value"] is not None and win_from.isoformat() <= p["period_start"] <= win_to.isoformat()]
        if not in_win:
            exclude({**s, "series_id": s["id"]}, "no_point_in_window", index.get(s["id"], {}).get("last_period", s["last_period"]))
            continue
        p = in_win[-1]
        comps.append({
            "series_id": s["id"], "origin_iso3": s["origin_iso3"], "variety": s["variety"],
            "color_grade": s["color_grade"], "terms": s["terms"], "organic": s["organic"], "market_iso3": s["market_iso3"],
            "market_location": s["market_location"], "native_frequency": s["native_frequency"],
            "source": s["source"], "period_label": p["period_label"], "value": p["value"], "low": p["low"], "high": p["high"],
            "published_at": p["published_at"], "source_url": p["source_url"], "data_status": p["data_status"],
            "is_demo": p["is_demo"], "freshness": s["freshness"],
            "_line": (s["source"] or {}).get("key"), "_total": _is_total_line(s["terms"], s["variety_raw"]),
        })
    for sid, meta in index.items():
        if sid not in built:
            exclude({**meta, "series_id": sid, "source": source_brief(sources.get(meta["source_id"]))},
                    "no_point_in_window", meta["last_period"])

    # 1) A source's all-lines total replaces its own sub-lines (USDA FAS GATS: HS 0409 total vs its
    #    HTS-10 colour/organic lines): averaging both would count the same imports twice.
    with_total = {(c["_line"], c["origin_iso3"], c["market_iso3"], c["is_demo"]) for c in comps if c["_total"]}
    kept = []
    for c in comps:
        if not c["_total"] and (c["_line"], c["origin_iso3"], c["market_iso3"], c["is_demo"]) in with_total:
            exclude(c, "component_of_total", c["period_label"])
        else:
            kept.append(c)
    # 1b) US Census and USDA FAS GATS publish the SAME Census statistics (trade_official.py): keep one
    #     source per origin/market, never both (the newer period wins; on a tie Census, which covers
    #     every origin). Every component of the other source is listed in `excluded`.
    same: dict[tuple, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for c in kept:
        if c["_line"] in SAME_DATA_SOURCES:
            same[(c["origin_iso3"], c["market_iso3"], c["is_demo"])][c["_line"]].append(c)
    drop: set[int] = set()
    for g in same.values():
        if len(g) == 2:
            newest = {k: max(x["period_label"] for x in v) for k, v in g.items()}
            loser = "usda_fas_gats" if newest["us_census_trade"] >= newest["usda_fas_gats"] else "us_census_trade"
            drop.update(id(x) for x in g[loser])
    if drop:
        for c in kept:
            if id(c) in drop:
                exclude(c, "same_underlying_data", c["period_label"])
        kept = [c for c in kept if id(c) not in drop]
    # 2) One bar per origin/variety AND market; demo and real series are never averaged together.
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for c in kept:
        groups[(bar_key(c), c["market_iso3"], bool(c["is_demo"]))].append(c)
    # 3) An aggregate market (EU27, extra-EU, World) is left out when its own members have bars.
    for gk in [g for g in groups if g[1] in AGGREGATE_AREAS]:
        if any(k == gk[0] and d == gk[2] and _is_member(m, gk[1]) for k, m, d in groups):
            for c in groups.pop(gk):
                exclude(c, "aggregate_of_shown_markets", c["period_label"])
    # 4) Inside a variety bar, an aggregate origin is left out when its member origins are there.
    if by == "variety":
        for gk, cs in groups.items():
            agg = [c for c in cs if c["origin_iso3"] in AGGREGATE_AREAS
                   and any(_is_member(o["origin_iso3"], c["origin_iso3"]) for o in cs)]
            for c in agg:
                exclude(c, "aggregate_of_shown_origins", c["period_label"])
            groups[gk] = [c for c in cs if c not in agg]
    bars = []
    for (key, market, demo), cs in groups.items():
        if not cs:
            continue
        cs = [{k: v for k, v in c.items() if not k.startswith("_")} for c in cs]
        vals = [c["value"] for c in cs]
        periods = sorted({c["period_label"] for c in cs})
        terms = sorted({c["terms"] for c in cs if c["terms"]})
        bars.append({
            "key": key, "id": f"{key}|{market or NONE_TOKEN}|{'demo' if demo else 'real'}",
            "origin_iso3": cs[0]["origin_iso3"] if by == "origin" else None,
            "variety": key if by == "variety" else None, "market_iso3": market,
            "value": _r(_mean(vals)), "min": min(vals), "max": max(vals), "n_series": len(cs),
            "period_label": periods[-1], "period_labels": periods, "mixed_periods": len(periods) > 1,
            "terms": terms, "mixed_terms": len(terms) > 1,
            "is_demo": demo,
            "sources": list({(c["source"] or {}).get("key"): c["source"] for c in cs}.values()),
            "components": sorted(cs, key=lambda c: -c["value"]),
        })
    bars.sort(key=lambda b: (-b["value"], b["id"]))
    excluded.sort(key=lambda e: (_priority_rank(e["origin_iso3"]), e["origin_iso3"] or "~", e["variety"] or "",
                                 (e["source"] or {}).get("key", ""), e["series_id"]))
    have = {b["key"] for b in bars}
    excluded = [e for e in excluded if e["key"] not in have] + [e for e in excluded if e["key"] in have]
    return {"by": by, "price_type": pt, "currency": ccy, "unit": "kg", "period": period, "window_months": window,
            "anchor_period": anchor_label, "window_from": win_from.isoformat(), "window_to": win_to.isoformat(),
            "bars": bars, "excluded": excluded}


@router.get("/discrepancies")
def discrepancies(
    f: PriceFilters = Depends(price_filters),
    currency: str = Query("USD"),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """Cases where two or more sources disagree by more than 10% (price_type optional)."""
    ccy = _currency(currency)
    items = find_discrepancies(db, _rows(db, f), ccy)
    return {"threshold_pct": round(DISCREPANCY_THRESHOLD * 100), "currency": "USD" if ccy == "ORIGINAL" else ccy,
            "total": len(items), "items": items[:limit]}


# ---------------------------------------------------------------------------
# Raw observations (table + CSV)
# ---------------------------------------------------------------------------

CSV_COLUMNS: list[tuple[str, str, str]] = [
    ("period_label", "Periodo", "Period"),
    ("period_start", "Inizio periodo", "Period start"),
    ("period_end", "Fine periodo", "Period end"),
    ("frequency", "Frequenza", "Frequency"),
    ("price_type", "Tipo di prezzo", "Price type"),
    ("origin_name", "Origine", "Origin"),
    ("origin_iso3", "Codice origine", "Origin code"),
    ("origin_label", "Origine (testo della fonte)", "Origin (source text)"),
    ("market_name", "Mercato", "Market"),
    ("market_location", "Località del mercato", "Market location"),
    ("variety_name", "Varietà", "Variety"),
    ("variety_raw", "Varietà (testo della fonte)", "Variety (source text)"),
    ("color_grade", "Colore", "Colour grade"),
    ("organic", "Biologico", "Organic"),
    ("terms", "Condizioni di vendita", "Terms"),
    ("price_low", "Prezzo minimo (come pubblicato)", "Low (as published)"),
    ("price_value", "Prezzo (come pubblicato)", "Price (as published)"),
    ("price_high", "Prezzo massimo (come pubblicato)", "High (as published)"),
    ("currency", "Valuta", "Currency"),
    ("unit", "Unità di misura", "Unit"),
    ("price_per_kg", "Prezzo al kg (valuta originale)", "Price per kg (original currency)"),
    ("usd_per_kg", "USD al kg", "USD per kg"),
    ("eur_per_kg", "EUR al kg", "EUR per kg"),
    ("fx_date", "Data del cambio", "FX rate date"),
    ("volume_kg", "Volume (kg)", "Volume (kg)"),
    ("data_status", "Stato del dato", "Data status"),
    ("reliability", "Affidabilità", "Reliability"),
    ("source_name", "Fonte", "Source"),
    ("publisher", "Editore", "Publisher"),
    ("source_url", "Documento originale", "Original document"),
    ("published_at", "Data di pubblicazione", "Published"),
    ("collected_at", "Data di raccolta", "Collected"),
    ("revision", "Revisione", "Revision"),
    ("is_demo", "Dato dimostrativo", "Demo data"),
    ("notes", "Note", "Notes"),
]
_NUMERIC = {"price_low", "price_value", "price_high", "price_per_kg", "usd_per_kg", "eur_per_kg", "volume_kg"}


def _serialize_obs(r: PriceObservation, src: Source | None) -> dict:
    return {
        "id": r.id, "source": source_brief(src), "price_type": r.price_type,
        "origin_iso3": r.origin_iso3, "origin_label": r.origin_label,
        "market_iso3": r.market_iso3, "market_location": r.market_location,
        "variety": r.variety, "variety_raw": r.variety_raw, "color_grade": r.color_grade, "organic": bool(r.organic),
        "terms": r.terms, "price_low": r.price_low, "price_value": r.price_value, "price_high": r.price_high,
        "currency": r.currency, "unit": r.unit, "price_per_kg": r.price_per_kg, "usd_per_kg": r.usd_per_kg,
        "eur_per_kg": r.eur_per_kg, "fx_date": iso(r.fx_date), "volume_kg": r.volume_kg,
        "period_label": r.period_label, "period_start": iso(r.period_start), "period_end": iso(r.period_end),
        "frequency": r.frequency, "published_at": iso(r.published_at), "collected_at": iso(r.collected_at),
        "source_url": r.source_url, "data_status": r.data_status, "reliability": r.reliability,
        "revision": r.revision, "is_demo": r.is_demo, "notes": r.notes,
    }


def _csv_safe(v: str) -> str:
    """Neutralise spreadsheet formulas in text that came from external documents."""
    return "'" + v if v and v[0] in "=+-@\t\r" else v


def _csv(rows: list[PriceObservation], sources: dict[int, Source], countries: dict[str, Country], lang: str) -> str:
    from .meta import PRICE_TYPE_LABELS, RELIABILITY_LABELS, STATUS_LABELS

    it = lang == "it"
    sep = ";" if it else ","          # Italian Excel expects ';' and a decimal comma
    yes, no = ("Sì", "No") if it else ("Yes", "No")
    pt_labels = {k.value: v[lang] for k, v in PRICE_TYPE_LABELS.items()}
    st_labels = {k.value: v[lang] for k, v in STATUS_LABELS.items()}
    rel_labels = {k.value: v[lang] for k, v in RELIABILITY_LABELS.items()}

    def cname(code: str | None) -> str:
        if not code:
            return ""
        c = countries.get(code)
        return (c.name_it if it else c.name_en) if c else code

    def num(v: float | None) -> str:
        if v is None:
            return ""
        s = f"{v:.6f}".rstrip("0").rstrip(".")
        return s.replace(".", ",") if it else s

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=sep, lineterminator="\r\n")
    w.writerow([it_h if it else en_h for _, it_h, en_h in CSV_COLUMNS])
    for r in rows:
        src = sources.get(r.source_id)
        rec = {
            **_serialize_obs(r, src),
            "price_type": pt_labels.get(r.price_type, r.price_type),
            "origin_name": cname(r.origin_iso3), "market_name": cname(r.market_iso3),
            "variety_name": VARIETY_LABELS.get(r.variety, {}).get(lang, r.variety),
            "organic": yes if r.organic else no,
            "data_status": st_labels.get(r.data_status, r.data_status),
            "reliability": rel_labels.get(r.reliability, r.reliability),
            "source_name": src.name if src else "", "publisher": (src.publisher or "") if src else "",
            "collected_at": r.collected_at.strftime("%Y-%m-%d %H:%M") if r.collected_at else "",
            "is_demo": ("SÌ — NON REALE" if it else "YES — NOT REAL") if r.is_demo else no,
        }
        line = []
        for key, _, _ in CSV_COLUMNS:
            v = rec.get(key)
            if key in _NUMERIC:
                line.append(num(v))
            elif v is None:
                line.append("")
            else:
                line.append(_csv_safe(str(v)))
        w.writerow(line)
    return "﻿" + buf.getvalue()


@router.get("/observations")
def observations(
    f: PriceFilters = Depends(price_filters),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    sort: str = Query("-period", description="-period | period"),
    format: str = Query("json", description="json | csv"),
    lang: str | None = Query(None, description="it | en (CSV headers and labels)"),
    db: Session = Depends(get_db),
):
    """Raw rows exactly as collected, with full provenance. `format=csv` exports every matching row."""
    q = apply_filters(select(M), f, db)
    order = [M.period_start.asc() if sort == "period" else M.period_start.desc(),
             M.origin_iso3, M.variety, M.color_grade, M.source_id, M.id]
    sources = {s.id: s for s in db.scalars(select(Source))}
    if format == "csv":
        lang = lang if lang in ("it", "en") else get_setting(db, "language", "it")
        rows = list(db.scalars(q.order_by(*order).limit(MAX_CSV_ROWS)))
        countries = {c.iso3: c for c in db.scalars(select(Country))}
        body = _csv(rows, sources, countries, lang or "it")
        stem = "prezzi-miele" if lang == "it" else "honey-prices"
        name = f"paladex-{stem}{'-' + f.price_type if f.price_type else ''}-{datetime.now():%Y%m%d}.csv"
        return Response(content=body.encode("utf-8"), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})
    if format != "json":
        raise HTTPException(422, "format must be json or csv")
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(*order).offset((page - 1) * page_size).limit(page_size)).all()
    return {"total": total, "page": page, "page_size": page_size, "pages": max(1, math.ceil(total / page_size)),
            "rows": [_serialize_obs(r, sources.get(r.source_id)) for r in rows]}
