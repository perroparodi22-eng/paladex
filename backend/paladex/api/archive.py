"""Historical archive API (/api/archive/...), Milestone 7c.

The archive compares a figure with the same figure in earlier years and shows what is stored
behind it. It never fills a gap, never mixes price types, sources or currencies, and every value
keeps its provenance (source, link, publication and collection dates, period, status).

Endpoints:
    GET /archive/prices/options   price types and the series that have data (origin, variety, market, colour)
    GET /archive/prices           one price series: average per year, and month by month for this
                                  year and the two before
    GET /archive/trade/options    reporters, flows and partners that have trade data
    GET /archive/trade            trade volume per year (one source per figure), and the same months
                                  of the two previous years
    GET /archive/production       production or colonies per year, per source
    GET /archive/news             news of a date range: articles and number per month
    GET /archive/quotes           every supplier quote over time, archived ones included
    GET /archive/revisions        every stored revision of a series (superseded values with dates)

How years are compared:
* A year's average is the mean of the months that exist, and the number of months is given.
  Customs unit values are weighted by the declared volume when every month carries one (value /
  weight over the year), as on the price pages.
* The change on the previous year compares the SAME months only. A year with data for
  January-August is compared with January-August of the year before, never with a full year.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from itertools import pairwise

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..enums import PriceType
from ..models import (
    NewsArticle,
    PriceObservation,
    ProductionStat,
    SupplierQuote,
    TradeFlowObservation,
)
from ..reference.countries import PRIORITY_ISO3
from .common import demo_clause, iso, source_brief, sources_by_id

router = APIRouter(prefix="/archive", tags=["archive"])

M = PriceObservation
P = ProductionStat
T = TradeFlowObservation
OVERLAY_YEARS = 3
CURRENCIES = ("ORIGINAL", "USD", "EUR")
NONE_TOKEN = "_none"         # "not specified" (NULL) market / colour, as on the price pages
# The page opens on the EU import unit value of Argentinian honey (Eurostat, monthly).
DEFAULT_PRICE = {"price_type": PriceType.IMPORT_UNIT_VALUE.value, "origin": "ARG", "variety": "unspecified",
                 "market": "EU27", "color_grade": None}
TYPE_ORDER = [PriceType.IMPORT_UNIT_VALUE.value, PriceType.WHOLESALE_BULK.value, PriceType.EXPORT_UNIT_VALUE.value,
              PriceType.PRODUCER.value, PriceType.RETAIL.value, PriceType.OTHER.value]
PERIODS_PER_YEAR = {"M": 12, "Q": 4, "A": 1}
STATUS_CAUTION = ("demo", "ai_assessment", "forecast", "estimate", "provisional", "user_entered", "published", "live")


def _priority(iso3: str | None) -> int:
    try:
        return PRIORITY_ISO3.index(iso3)  # type: ignore[arg-type]
    except ValueError:
        return len(PRIORITY_ISO3)


def _pct(curr: float | None, prev: float | None) -> float | None:
    if curr is None or prev is None or prev == 0:
        return None
    return round((curr - prev) / prev * 100, 2)


def _r(v: float | None, n: int = 4) -> float | None:
    return None if v is None else round(v, n)


def _most_cautious(statuses) -> str | None:
    found = {s for s in statuses if s}
    for s in STATUS_CAUTION:
        if s in found:
            return s
    return next(iter(found), None)


def _code(v: str | None, name: str) -> str | None:
    if v is None or v == "":
        return None
    c = v.strip().upper()
    if c == NONE_TOKEN.upper():
        return NONE_TOKEN
    if not (2 <= len(c) <= 10) or not c.replace("_", "").isalnum():
        raise HTTPException(422, f"Codice non valido ({name}) / invalid code ({name}): {v!r}")
    return c


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------


def _price_base(db: Session, small: bool) -> list:
    from .prices import bulk_unit_value_clause

    conds = [M.is_current.is_(True), demo_clause(M, db), M.origin_iso3.is_not(None)]
    if not small:
        conds.append(bulk_unit_value_clause(M))
    return conds


@router.get("/prices/options")
def price_options(price_type: str | None = Query(None), small: bool = Query(False), db: Session = Depends(get_db)):
    """Price types with data and, for the chosen one, every origin / variety / market / colour
    combination that has rows (with its period range and frequencies)."""
    base = _price_base(db, small)
    counts = dict(db.execute(select(M.price_type, func.count()).where(*base).group_by(M.price_type)).all())
    types = sorted(counts, key=lambda t: (TYPE_ORDER.index(t) if t in TYPE_ORDER else len(TYPE_ORDER), t))
    ptype = price_type if price_type in counts else next(iter(types), None)
    combos: dict[tuple, dict] = {}
    if ptype:
        q = (select(M.origin_iso3, M.variety, M.market_iso3, M.color_grade, M.frequency, func.count(),
                    func.min(M.period_label), func.max(M.period_label), func.max(M.period_start))
             .where(*base, M.price_type == ptype)
             .group_by(M.origin_iso3, M.variety, M.market_iso3, M.color_grade, M.frequency))
        for origin, variety, market, color, freq, n, first, last, last_start in db.execute(q):
            c = combos.setdefault((origin, variety, market, color), {
                "origin": origin, "variety": variety, "market": market, "color_grade": color, "rows": 0,
                "frequencies": set(), "first_period": first, "last_period": last, "_last_start": last_start})
            c["rows"] += n
            c["frequencies"].add(freq)
            c["first_period"] = min(c["first_period"], first)
            if last_start and (c["_last_start"] is None or last_start > c["_last_start"]):
                c["_last_start"], c["last_period"] = last_start, last
    out = []
    for c in combos.values():
        c.pop("_last_start")
        c["frequencies"] = sorted(c["frequencies"], key=lambda f: "DWMQA".find(f) if f in "DWMQA" else 9)
        out.append(c)
    out.sort(key=lambda c: (_priority(c["origin"]), c["origin"], c["variety"], c["market"] or "", c["color_grade"] or ""))
    default = None
    if ptype:
        want = DEFAULT_PRICE if ptype == DEFAULT_PRICE["price_type"] else None
        pick = next((c for c in out if want and (c["origin"], c["variety"], c["market"]) ==
                     (want["origin"], want["variety"], want["market"])), None)
        if pick is None and out:
            # Argentina first (Parodi's first origin), then the best-covered series of the type.
            pick = max(out, key=lambda c: (c["origin"] == "ARG", c["variety"] == "polyflora",
                                           "M" in c["frequencies"], c["rows"]))
        if pick is not None:
            default = {"price_type": ptype, "origin": pick["origin"], "variety": pick["variety"],
                       "market": pick["market"], "color_grade": None}
    return {"price_types": [{"key": t, "count": counts[t]} for t in types], "price_type": ptype,
            "combos": out, "default": default}


def _series_meta(s: dict) -> dict:
    keys = ("id", "source", "price_type", "origin_iso3", "origin_label", "market_iso3", "market_location", "variety",
            "variety_raw", "color_grade", "terms", "organic", "currency", "unit", "native_frequency", "freq",
            "n_points", "first_period", "last_period", "weighting", "published_at", "collected_at", "source_url",
            "data_status", "data_statuses", "reliability", "is_demo", "freshness", "fx_missing_points")
    return {k: s.get(k) for k in keys}


def _slot(label: str, freq: str) -> tuple[int, int]:
    """(year, slot in the year) of a period label: month 1-12, quarter 1-4, or 0 for a year."""
    y = int(label[:4])
    if freq == "M":
        return y, int(label[5:7])
    if freq == "Q":
        return y, int(label[-1])
    return y, 0


def _avg(points: list[dict]) -> tuple[float | None, str]:
    """Mean of point values: volume-weighted when every point carries a declared volume."""
    vals = [p for p in points if p.get("value") is not None]
    if not vals:
        return None, "simple"
    if all(p.get("volume_kg") for p in vals):
        w = sum(p["volume_kg"] for p in vals)
        return sum(p["value"] * p["volume_kg"] for p in vals) / w, "volume"
    return sum(p["value"] for p in vals) / len(vals), "simple"


def _point_brief(p: dict) -> dict:
    return {"period_label": p["period_label"], "value": p["value"], "low": p.get("low"), "high": p.get("high"),
            "n_points": p.get("n_points"), "expected_points": p.get("expected_points"),
            "volume_kg": p.get("volume_kg"), "published_at": p.get("published_at"),
            "collected_at": p.get("collected_at"), "source_url": p.get("source_url"),
            "data_status": p.get("data_status"), "is_demo": p.get("is_demo", False),
            "original": p.get("original")}


def year_table(points: list[dict], freq: str) -> list[dict]:
    """Average per year, its extremes and the change on the same months of the previous year."""
    by_year: dict[int, dict[int, dict]] = defaultdict(dict)
    for p in points:
        if p.get("value") is None:
            continue
        y, k = _slot(p["period_label"], freq)
        by_year[y][k] = p
    expected = PERIODS_PER_YEAR.get(freq, 1)
    out = []
    for y in sorted(by_year):
        pts = by_year[y]
        ordered = [pts[k] for k in sorted(pts)]
        avg, weighting = _avg(ordered)
        prev = by_year.get(y - 1) or {}
        common = sorted(set(pts) & set(prev))
        change = None
        if common:
            a, _ = _avg([pts[k] for k in common])
            b, _ = _avg([prev[k] for k in common])
            change = _pct(a, b)
        lo = min(ordered, key=lambda p: p["value"])
        hi = max(ordered, key=lambda p: p["value"])
        latest = max(ordered, key=lambda p: (p.get("published_at") or "", p.get("collected_at") or ""))
        pubs = [p["published_at"] for p in ordered if p.get("published_at")]
        cols = [p["collected_at"] for p in ordered if p.get("collected_at")]
        out.append({
            "year": y,
            "average": _r(avg),
            "weighting": weighting,
            "volume_kg": _r(sum(p["volume_kg"] for p in ordered), 1) if weighting == "volume" else None,
            "periods": len(ordered),
            "expected_periods": expected,
            "complete": len(ordered) >= expected,
            "first_period": ordered[0]["period_label"],
            "last_period": ordered[-1]["period_label"],
            "min": {"period_label": lo["period_label"], "value": lo["value"]},
            "max": {"period_label": hi["period_label"], "value": hi["value"]},
            # change on the previous year, computed on the periods both years have
            "change_pct": change,
            "change_periods": len(common),
            "change_same_periods_only": bool(common) and (len(common) < len(ordered) or len(common) < len(prev)),
            "data_status": _most_cautious(p.get("data_status") for p in ordered),
            "published_at": max(pubs) if pubs else None,
            "collected_at": max(cols) if cols else None,
            "source_url": latest.get("source_url"),
            "is_demo": any(p.get("is_demo") for p in ordered),
        })
    return out


def month_overlay(points: list[dict], freq: str, years: int = OVERLAY_YEARS) -> dict | None:
    """This year and the `years - 1` before, month by month (null where a month has no value)."""
    if freq != "M":
        return None
    by_year: dict[int, dict[int, dict]] = defaultdict(dict)
    for p in points:
        if p.get("value") is not None:
            y, m = _slot(p["period_label"], "M")
            by_year[y][m] = p
    if not by_year:
        return None
    latest = max(by_year)
    out = []
    for y in range(latest, latest - years, -1):
        months = by_year.get(y, {})
        out.append({"year": y, "months": len(months),
                    "points": [(_point_brief(months[m]) if m in months else None) for m in range(1, 13)]})
    return {"latest_year": latest, "years": out}


def _pick_series(series: list[dict], wanted: str | None) -> dict:
    if wanted:
        hit = next((s for s in series if s["id"] == wanted), None)
        if hit is not None:
            return hit
    # Monthly-based first, then the most recent, then the longest.
    return max(series, key=lambda s: (s["freq"] == "M", s["last_period"] or "", s["n_points"]))


@router.get("/prices")
def price_history(
    price_type: str = Query(...),
    origin: str = Query(...),
    variety: str | None = Query(None),
    market: str | None = Query(None, description="ISO3 / EU27; '_none' = not specified"),
    color: str | None = Query(None, description="colour grade; '_none' = not specified"),
    currency: str = Query("ORIGINAL"),
    series: str | None = Query(None, description="series id to analyse (default: the best-covered one)"),
    small: bool = Query(False, description="include customs unit values of consignments under 10 t"),
    db: Session = Depends(get_db),
):
    from .prices import _UNUSED_COLUMNS, build_series

    if price_type not in [p.value for p in PriceType]:
        raise HTTPException(422, "Tipo di prezzo non valido / invalid price type")
    ccy = currency.upper()
    if ccy not in CURRENCIES:
        raise HTTPException(422, "Valuta non valida (ORIGINAL, USD, EUR) / invalid currency")
    org = _code(origin, "origin")
    mk = _code(market, "market")
    conds = [*_price_base(db, small), M.price_type == price_type, M.origin_iso3 == org]
    if variety:
        conds.append(M.variety == variety)
    if mk:
        conds.append(M.market_iso3.is_(None) if mk == NONE_TOKEN else M.market_iso3 == mk)
    if color:
        conds.append(M.color_grade.is_(None) if color == NONE_TOKEN else M.color_grade == color)
    rows = list(db.scalars(select(M).where(*conds).options(*_UNUSED_COLUMNS)))
    filters = {"price_type": price_type, "origin": org, "variety": variety, "market": mk, "color": color,
               "currency": ccy, "small": small}
    if not rows:
        return {"available": False, "filters": filters, "series": [], "selected": None}
    all_series = build_series(db, rows, ccy, "M")  # type: ignore[arg-type]
    chosen = _pick_series(all_series, series)
    pts = chosen["points"]
    return {
        "available": True,
        "filters": filters,
        "series": [_series_meta(s) for s in all_series],
        "selected": {
            **_series_meta(chosen),
            "years": year_table(pts, chosen["freq"]),
            "overlay": month_overlay(pts, chosen["freq"]),
        },
    }


# ---------------------------------------------------------------------------
# Trade
# ---------------------------------------------------------------------------


@router.get("/trade/options")
def trade_options(db: Session = Depends(get_db)):
    """Reporters with their flows, frequencies and partners that have current rows."""
    from .alerts import trade_options as options

    return {"reporters": options(db)}


def _ytd(points: list[dict]) -> dict | None:
    """The months of the newest year compared with the same months of the two previous years."""
    months = {p["period_label"]: p for p in points if p.get("net_weight_kg") is not None}
    if not months:
        return None
    last = max(months)
    year, upto = int(last[:4]), int(last[5:7])
    out = []
    for y in range(year, year - OVERLAY_YEARS, -1):
        have = [months[f"{y}-{m:02d}"] for m in range(1, upto + 1) if f"{y}-{m:02d}" in months]
        complete = len(have) == upto
        pubs = [p["published_at"] for p in have if p.get("published_at")]
        out.append({
            "year": y, "months": len(have), "complete": complete,
            "net_weight_kg": _r(sum(p["net_weight_kg"] for p in have), 1) if complete else None,
            "usd_value": (_r(sum(p["usd_value"] for p in have), 2)
                          if complete and all(p.get("usd_value") is not None for p in have) else None),
            "data_status": _most_cautious(p.get("data_status") for p in have),
            "published_at": max(pubs) if pubs else None,
            "source_url": have[-1].get("source_url") if have else None,
            "is_demo": any(p.get("is_demo") for p in have),
        })
    for cur, prev in pairwise(out):
        cur["change_pct"] = _pct(cur["net_weight_kg"], prev["net_weight_kg"])
    out[-1]["change_pct"] = None
    return {"through_month": upto, "latest_label": last, "years": out}


@router.get("/trade")
def trade_history(
    reporter: str = Query("EU27"),
    partner: str = Query("WLD", description="partner ISO3; WLD = the reporter's total"),
    flow: str = Query("import"),
    db: Session = Depends(get_db),
):
    from .trade import Ctx, _flow, _iso, build_series

    ctx = Ctx(db)
    rep = _iso(reporter, "reporter")
    par = _iso(partner, "partner") or "WLD"
    fl = _flow(flow)
    annual = build_series(ctx, rep, fl, par, "A")
    monthly = build_series(ctx, rep, fl, par, "M")
    years_out = []
    for s in annual["series"]:
        by_year = {p["period_label"]: p for p in s["points"]}
        for p in s["points"]:
            prev = by_year.get(str(int(p["period_label"]) - 1))
            p["change_pct"] = _pct(p.get("net_weight_kg"), prev.get("net_weight_kg") if prev else None)
        years_out.append({"source": s["source"], "points": s["points"], "freshness": s["freshness"],
                          "is_demo": s["is_demo"], "expected_update": s.get("expected_update"),
                          "expected_update_en": s.get("expected_update_en")})
    ytd = []
    for s in monthly["series"]:
        block = _ytd(s["points"])
        if block:
            ytd.append({"source": s["source"], "freshness": s["freshness"], "is_demo": s["is_demo"], **block})
    return {
        "reporter": rep, "partner": par, "flow": fl,
        "reporter_names": annual["reporter_names"], "partner_names": annual["partner_names"],
        "total_scope": annual["total_scope"],
        "available": bool(years_out or ytd),
        "annual": years_out, "ytd": ytd,
        "excluded_partial": annual["excluded_partial"], "discrepancies": annual["discrepancies"],
        "providers": annual["providers"],
    }


# ---------------------------------------------------------------------------
# Production
# ---------------------------------------------------------------------------


@router.get("/production")
def production_history(
    country: str = Query("ARG"),
    metric: str = Query("production", pattern="^[a-z_]{2,40}$"),
    db: Session = Depends(get_db),
):
    from .countries import national_metric_clause

    iso3 = _code(country, "country")
    # per-region metrics (one figure per state) are not a national series: never mixed into one line
    base = [P.is_current.is_(True), demo_clause(P, db), national_metric_clause(P)]
    metrics = dict(db.execute(select(P.metric, func.count()).where(*base, P.country_iso3 == iso3)
                              .group_by(P.metric)).all())
    countries = [{"iso3": c, "rows": n, "last_period": last}
                 for c, n, last in db.execute(select(P.country_iso3, func.count(), func.max(P.period_label))
                                              .where(*base, P.metric == metric).group_by(P.country_iso3))]
    countries.sort(key=lambda c: (_priority(c["iso3"]), c["iso3"]))
    rows = list(db.scalars(select(P).where(*base, P.country_iso3 == iso3, P.metric == metric)
                           .order_by(P.source_id, P.period_start)))
    srcs = sources_by_id(db)
    groups: dict[tuple[int, str, str], list[ProductionStat]] = defaultdict(list)
    for r in rows:
        groups[(r.source_id, r.unit, r.frequency)].append(r)
    series = []
    for (sid, unit, freq), grp in groups.items():
        points = []
        prev_by_year: dict[int, float] = {}
        for r in grp:
            y = r.period_start.year
            prev = prev_by_year.get(y - 1)
            points.append({
                "period_label": r.period_label, "year": y, "value": r.value, "unit": r.unit, "flag": r.flag_raw,
                "change_pct": _pct(r.value, prev) if freq == "A" else None,
                "data_status": r.data_status, "published_at": iso(r.published_at), "collected_at": iso(r.collected_at),
                "source_url": r.source_url, "is_demo": r.is_demo, "revision": r.revision,
            })
            prev_by_year[y] = r.value
        src = srcs.get(sid)
        series.append({"source": source_brief(src), "unit": unit, "frequency": freq, "points": points,
                       "reliability": src.reliability if src else None,
                       "expected_update": src.expected_update if src else None,
                       "expected_update_en": src.expected_update_en if src else None,
                       "is_demo": any(p["is_demo"] for p in points)})
    series.sort(key=lambda s: (-len(s["points"]), (s["source"] or {}).get("key", "")))
    return {"country": iso3, "metric": metric, "available": bool(series), "series": series,
            "metrics": [{"key": k, "rows": n} for k, n in sorted(metrics.items())], "countries": countries}


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------


@router.get("/news")
def news_history(
    q: str | None = Query(None),
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None),
    country: str | None = Query(None),
    min_relevance: int = Query(0, ge=0, le=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Articles of a date range (newest first) and how many per month, with the span of the
    whole news archive so the page can say how far back it goes."""
    from .news import Filters, _duplicates_of, _sources, _when, serialize_article

    if from_ and to and from_ > to:
        raise HTTPException(422, "La data iniziale è dopo quella finale / start date after end date")
    f = Filters(db, q, country, None, None, from_, to, None, min_relevance, False)
    N = NewsArticle
    conds = f.all()
    total = db.scalar(select(func.count()).select_from(N).where(*conds)) or 0
    rows = list(db.scalars(select(N).where(*conds).order_by(_when().desc(), N.id.desc())
                           .offset((page - 1) * page_size).limit(page_size)))
    sources = _sources(db)
    dups = _duplicates_of(db, [a.id for a in rows if a.duplicate_count])
    month = func.strftime("%Y-%m", _when())
    months = [{"month": m, "count": n} for m, n in
              db.execute(select(month, func.count()).where(*conds).group_by(month).order_by(month)) if m]
    held = db.execute(select(func.min(_when()), func.max(_when()), func.count())
                      .where(demo_clause(N, db), N.duplicate_of_id.is_(None))).one()
    return {
        "items": [serialize_article(a, sources, dups.get(a.id)) for a in rows],
        "total": total, "page": page, "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if total else 0,
        "months": months,
        "filters": f.echo(),
        "archive": {"oldest": iso(held[0]), "newest": iso(held[1]), "articles": held[2] or 0},
    }


# ---------------------------------------------------------------------------
# Supplier quotes
# ---------------------------------------------------------------------------


def _quote(q: SupplierQuote, today: date) -> dict:
    return {
        "id": q.id, "supplier_name": q.supplier_name, "origin_iso3": q.origin_iso3, "variety": q.variety,
        "variety_note": q.variety_note, "price_per_kg": q.price_per_kg, "currency": q.currency,
        "price_quoted": getattr(q, "price_quoted", None), "price_unit": getattr(q, "price_unit", None) or "kg",
        "quantity_kg": q.quantity_kg, "packaging": q.packaging, "incoterm": q.incoterm,
        "incoterm_place": q.incoterm_place, "destination": getattr(q, "destination", None),
        "date_received": iso(q.date_received), "valid_until": iso(q.valid_until),
        "expired": bool(q.valid_until and q.valid_until < today), "archived": bool(q.archived),
        "notes": q.notes, "is_demo": bool(q.is_demo), "data_status": "demo" if q.is_demo else "user_entered",
    }


@router.get("/quotes")
def quotes_history(
    origin: str | None = Query(None),
    variety: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """Every supplier quote over time (archived ones included), oldest first, with a summary per
    year that never averages different currencies or Incoterms together."""
    Q = SupplierQuote
    today = date.today()
    base = [demo_clause(Q, db)]
    origins = [{"iso3": o, "count": n} for o, n in
               db.execute(select(Q.origin_iso3, func.count()).where(*base).group_by(Q.origin_iso3))]
    origins.sort(key=lambda o: (_priority(o["iso3"]), o["iso3"]))
    org = _code(origin, "origin")
    conds = list(base)
    if org:
        conds.append(Q.origin_iso3 == org)
    varieties = [{"key": v, "count": n} for v, n in
                 db.execute(select(Q.variety, func.count()).where(*conds).group_by(Q.variety).order_by(func.count().desc()))]
    if variety:
        conds.append(Q.variety == variety)
    rows = list(db.scalars(select(Q).where(*conds).order_by(Q.date_received, Q.id)))
    groups: dict[tuple, list[SupplierQuote]] = defaultdict(list)
    for q in rows:
        groups[(q.date_received.year, q.currency, q.incoterm or "")].append(q)
    summary = []
    for (y, ccy, inc), grp in sorted(groups.items(), key=lambda kv: (-kv[0][0], kv[0][1], kv[0][2])):
        vals = [q.price_per_kg for q in grp]
        summary.append({"year": y, "currency": ccy, "incoterm": inc or None, "quotes": len(grp),
                        "suppliers": len({q.supplier_name for q in grp}), "min": _r(min(vals)), "max": _r(max(vals)),
                        "average": _r(sum(vals) / len(vals)), "is_demo": any(q.is_demo for q in grp)})
    return {"available": bool(rows), "total": len(rows), "origin": org, "variety": variety,
            "items": [_quote(q, today) for q in reversed(rows)], "summary": summary,
            "origins": origins, "varieties": varieties,
            "total_all": db.scalar(select(func.count()).select_from(Q).where(*base)) or 0}


# ---------------------------------------------------------------------------
# Revisions
# ---------------------------------------------------------------------------


def _chains(rows: list) -> dict[tuple[int, str], list]:
    chains: dict[tuple[int, str], list] = defaultdict(list)
    for r in rows:
        chains[(r.source_id, r.series_key)].append(r)
    return chains


def _revision_entry(r, kind: str) -> dict:
    base = {"id": r.id, "revision": r.revision, "is_current": r.is_current, "supersedes_id": r.supersedes_id,
            "published_at": iso(r.published_at), "collected_at": iso(r.collected_at),
            "last_seen_at": iso(r.last_seen_at), "data_status": r.data_status, "source_url": r.source_url,
            "is_demo": r.is_demo}
    if kind == "price":
        return {**base, "value": r.price_value, "low": r.price_low, "high": r.price_high, "currency": r.currency,
                "unit": r.unit, "volume_kg": r.volume_kg}
    if kind == "trade":
        return {**base, "value": r.net_weight_kg, "unit": "kg", "trade_value": r.value, "currency": r.currency}
    return {**base, "value": r.value, "unit": r.unit, "flag": r.flag_raw}


@router.get("/revisions")
def revision_history(
    kind: str = Query("price", pattern="^(price|trade|production)$"),
    # price series (as /archive/prices)
    price_type: str | None = Query(None), origin: str | None = Query(None), variety: str | None = Query(None),
    market: str | None = Query(None), color: str | None = Query(None), currency: str = Query("ORIGINAL"),
    series: str | None = Query(None),
    # trade
    reporter: str | None = Query(None), partner: str | None = Query(None), flow: str | None = Query(None),
    # production
    country: str | None = Query(None), metric: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """Every stored value of a series, period by period. A period is listed when the source
    revised it (several revisions) or withdrew it (no current value any more); the others hold
    only their first publication and are counted."""
    srcs = sources_by_id(db)
    if kind == "price":
        if not (price_type and origin):
            raise HTTPException(422, "Servono tipo di prezzo e origine / price_type and origin are required")
        from .prices import series_id, series_key

        ccy = currency.upper() if currency.upper() in CURRENCIES else "ORIGINAL"
        mk = _code(market, "market")
        conds = [demo_clause(M, db), M.price_type == price_type, M.origin_iso3 == _code(origin, "origin")]
        if variety:
            conds.append(M.variety == variety)
        if mk:
            conds.append(M.market_iso3.is_(None) if mk == NONE_TOKEN else M.market_iso3 == mk)
        if color:
            conds.append(M.color_grade.is_(None) if color == NONE_TOKEN else M.color_grade == color)
        rows = list(db.scalars(select(M).where(*conds).order_by(M.period_start, M.revision, M.id)))
        if series:
            rows = [r for r in rows if series_id(series_key(r, ccy)) == series]  # type: ignore[arg-type]
    elif kind == "trade":
        rep = _code(reporter or "", "reporter")
        if not rep:
            raise HTTPException(422, "Serve il paese dichiarante / reporter is required")
        par = _code(partner or "WLD", "partner")
        if par == "WLD":
            par_codes = ["EXTRA_EU"] if rep in ("EU27", "EU28") else ["WLD"]
        else:
            par_codes = [par]
        rows = list(db.scalars(select(T).where(demo_clause(T, db), T.reporter_iso3 == rep, T.partner_iso3.in_(par_codes),
                                               T.flow == (flow or "import"), T.hs_code.like("0409%"))
                               .order_by(T.period_start, T.revision, T.id)))
    else:
        iso3 = _code(country or "", "country")
        if not iso3:
            raise HTTPException(422, "Serve il paese / country is required")
        rows = list(db.scalars(select(P).where(demo_clause(P, db), P.country_iso3 == iso3,
                                               P.metric == (metric or "production"))
                               .order_by(P.period_start, P.revision, P.id)))
    periods = []
    stored_values = 0
    for (sid, _key), chain in _chains(rows).items():
        stored_values += len(chain)
        chain.sort(key=lambda r: (r.revision or 1, r.id))
        current = [r for r in chain if r.is_current]
        if len(chain) < 2 and current:
            continue
        entries = [_revision_entry(r, kind) for r in chain]
        for prev, cur in pairwise(entries):
            cur["change_pct"] = _pct(cur["value"], prev["value"])
        entries[0]["change_pct"] = None
        last = chain[-1]
        periods.append({
            "source": source_brief(srcs.get(sid)), "period_label": last.period_label,
            "period_start": iso(last.period_start), "frequency": last.frequency,
            "status": "withdrawn" if not current else "revised",
            "label": _row_label(last, kind),
            "revisions": entries,
        })
    periods.sort(key=lambda p: (p["period_start"] or "", p["label"] or ""), reverse=True)
    series_periods = len(_chains(rows))
    return {
        "kind": kind,
        "periods": periods,
        "counts": {"periods": series_periods, "stored_values": stored_values,
                   "revised": sum(1 for p in periods if p["status"] == "revised"),
                   "withdrawn": sum(1 for p in periods if p["status"] == "withdrawn")},
        "first_period": iso(min((r.period_start for r in rows), default=None)),
        "last_period": iso(max((r.period_start for r in rows), default=None)),
        "last_collected_at": iso(max((r.collected_at for r in rows), default=None)),
    }


def _row_label(r, kind: str) -> str | None:
    """What distinguishes rows of one period within a price series (e.g. the USDA HTS line)."""
    if kind == "price":
        return r.variety_raw or r.terms
    if kind == "trade":
        return f"{r.reporter_iso3} ← {r.partner_iso3}" if r.flow == "import" else f"{r.reporter_iso3} → {r.partner_iso3}"
    return None
