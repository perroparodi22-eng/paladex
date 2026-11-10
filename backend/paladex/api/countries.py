"""Country intelligence API (/api/countries...).

    GET /countries          every reference country: priority flag, coordinates, ISO numeric code
                            (for the world map), data-availability flags and headline metrics
                            (latest declared exports / imports, latest production, news in 30 days)
    GET /countries/{iso3}   country profile: reference info, curated context (clearly labelled as
                            background, not collected data), production series, exports / imports
                            (declared totals, top partners, mirror declarations), latest prices by
                            price type, recent news, regulations, and the explicit list of what is
                            NOT available and which source would provide it.

Data rules (docs/DEVELOPING.md): nothing is invented — a missing section is reported in
`missing`, never filled; one source per figure (production series are per source and per unit,
prices are grouped by price type and never mixed); demo rows only via `demo_clause`; every figure
carries its provenance.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session, defer

from ..db import get_db
from ..enums import PriceType
from ..models import (
    Country,
    NewsArticle,
    PriceObservation,
    ProductionStat,
    RegulationItem,
    TradeFlowObservation,
    utcnow,
)
from ..reference.countries import PRIORITY_ISO3
from ..services import news as news_service
from ..services.corrections import row_correction
from .common import demo_clause, iso
from .findings import country_block as web_findings_block   # non-official web findings: own block, never mixed
from .memo import cached
from .trade import (
    FLOWS,
    PSEUDO_AREAS,
    RELIABILITY_ORDER,
    Ctx,
    Totals,
    base_where,
    build_series,
    candidate_total,
    latest_totals,
    mirror_declarations,
    most_cautious,
    partner_breakdown,
    sources_used,
)
from .ytd import mirror_ytd, reporter_ytd

router = APIRouter(prefix="/countries", tags=["countries"])

NEWS_DAYS = 30
NEWS_LIMIT = 8
NEWS_HIGHLIGHTS = 2               # "one or two per country": the trade news that matter most
NEWS_HIGHLIGHT_DAYS = 365         # trade stories about one country are months apart (each shows its date)
NEWS_HIGHLIGHT_MIN_RELEVANCE = 35  # services.news.relevance_level: "medium" or higher
REG_LIMIT = 10
PRICE_ROWS_PER_TYPE = 10
TOP_PARTNERS = 8
METRIC_ORDER = ["production", "colonies", "yield_per_colony", "producer_price", "stocks"]
PRICE_TYPE_ORDER = [p.value for p in (PriceType.WHOLESALE_BULK, PriceType.PRODUCER, PriceType.IMPORT_UNIT_VALUE,
                                      PriceType.EXPORT_UNIT_VALUE, PriceType.RETAIL, PriceType.OTHER)]
# Units a production volume can be shown in, converted to tonnes for the map.
TONNES_PER_UNIT = {"t": 1.0, "tonnes": 1.0, "tonne": 1.0, "kg": 0.001}
# Sources that publish prices BY ORIGIN for many countries (bulk quotes, customs unit values):
# listed first when a country's prices are missing.
ORIGIN_PRICE_SOURCES = ("usda_honey_report", "un_comtrade", "eurostat_comext", "usda_fas_gats")
# Which source categories would fill each section (for honest empty states).
SECTION_CATEGORIES = {
    "production": "production", "exports": "trade", "imports": "trade", "prices": "prices",
    "news": "news", "regulations": "regulation",
}
CONTEXT_NOTE = {
    "it": "Informazioni di contesto (non dati raccolti): conoscenze di settore curate, non aggiornate automaticamente.",
    "en": "Background information (not collected data): curated industry knowledge, not updated automatically.",
}


def _country_ref(c: Country) -> dict:
    return {"iso3": c.iso3, "iso2": c.iso2, "m49": c.m49, "name_it": c.name_it, "name_en": c.name_en,
            "region": c.region, "lat": c.lat, "lon": c.lon, "priority": bool(c.priority)}


def _news_since() -> datetime:
    return utcnow() - timedelta(days=NEWS_DAYS)


def _news_when():
    return func.coalesce(NewsArticle.published_at, NewsArticle.collected_at)


def _json_contains(column, code: str):
    """JSON list column contains `code` (an ISO3 validated against the reference table)."""
    return cast(column, String).like(f'%"{code}"%')


# ---------------------------------------------------------------------------
# Production
# ---------------------------------------------------------------------------


def national_metric_clause(P=ProductionStat):
    """Country-level metrics only. A `*_by_region` metric (IBGE: Brazil's 27 states, the state in
    `extra.region`) holds one figure per region and year under the same country: grouped by metric it
    would make one series jumping from state to state, with a 'latest' and a year-on-year change taken
    across different states. Only a view that groups by region may read it."""
    return ~P.metric.like("%\\_by\\_region", escape="\\")


def _production_rows(ctx: Ctx, iso3: str | None = None, metric: str | None = None) -> list[ProductionStat]:
    P = ProductionStat
    q = select(P).where(P.is_current.is_(True), demo_clause(P, ctx.db))
    if iso3:
        q = q.where(P.country_iso3 == iso3)
    q = q.where(P.metric == metric) if metric else q.where(national_metric_clause(P))
    # `extra` (JSON) and the revision bookkeeping are never read here: not loaded (a third of the time)
    q = q.options(defer(P.extra), defer(P.value_hash), defer(P.series_key))
    return list(ctx.db.scalars(q.order_by(P.period_start)))


def _source_rank(ctx: Ctx, sid: int) -> int:
    src = ctx.source(sid)
    return RELIABILITY_ORDER.index(src.reliability) if src and src.reliability in RELIABILITY_ORDER else len(RELIABILITY_ORDER)


def latest_production(ctx: Ctx) -> dict[str, dict]:
    """iso3 -> latest production volume (tonnes) from ONE source per country.

    Sources covering more countries come first (comparable figures across the map), then the
    more reliable, then the more recent."""
    rows = [r for r in _production_rows(ctx, metric="production") if (r.unit or "").lower() in TONNES_PER_UNIT
            and r.frequency == "A"]
    coverage: dict[int, set[str]] = defaultdict(set)
    latest: dict[tuple[str, int], ProductionStat] = {}
    for r in rows:
        coverage[r.source_id].add(r.country_iso3)
        k = (r.country_iso3, r.source_id)
        if k not in latest or r.period_start > latest[k].period_start:
            latest[k] = r
    out: dict[str, dict] = {}
    for (iso3, sid), r in latest.items():
        key = (len(coverage[sid]), -_source_rank(ctx, sid), r.period_start)
        cur = out.get(iso3)
        if cur is None or key > cur["_key"]:
            out[iso3] = {
                "_key": key, "value_t": round(r.value * TONNES_PER_UNIT[r.unit.lower()], 1), "unit": "t",
                "unit_as_published": r.unit, "year": r.period_start.year, **_obs_provenance(ctx, r),
            }
    for v in out.values():
        v.pop("_key")
    return out


def _obs_provenance(ctx: Ctx, r) -> dict:
    return {
        "row_id": r.id,      # the stored row (what a person can correct, POST /api/corrections)
        "source": ctx.brief(r.source_id), "source_url": r.source_url, "published_at": iso(r.published_at),
        "collected_at": iso(r.collected_at), "period_label": r.period_label, "period_start": iso(r.period_start),
        "period_end": iso(r.period_end), "frequency": r.frequency, "data_status": r.data_status,
        "reliability": r.reliability, "is_demo": r.is_demo,
        "correction": row_correction(r),      # "corrected by ..." (services/corrections.py), else None
    }


# When a source releases year Y of its annual production series, from its own published calendar
# (sources registry, `expected_update`): FAOSTAT publishes production of year Y in December Y+1.
ANNUAL_RELEASE = {"faostat": {"lag_years": 1, "month": 12}}


def _next_release(ctx: Ctx, sid: int, newest: ProductionStat) -> dict | None:
    """The next year of an annual series and when its source says it comes out ("the 2025 figure
    is expected in December 2026"), so the newest year is read as the latest available, not as old."""
    src = ctx.source(sid)
    rule = ANNUAL_RELEASE.get(src.key) if src else None
    if rule is None or newest.frequency != "A":
        return None
    year = newest.period_start.year + 1
    due = date(year + rule["lag_years"], rule["month"], 1)
    return {"year": year, "expected": f"{due.year}-{due.month:02d}", "overdue": due < date(ctx.today.year, ctx.today.month, 1)}


def production_section(ctx: Ctx, iso3: str) -> dict:
    """Series per metric, unit and source — never merged across sources or units."""
    rows = _production_rows(ctx, iso3=iso3)
    groups: dict[tuple[str, str, int], list[ProductionStat]] = defaultdict(list)
    for r in rows:
        groups[(r.metric, r.unit, r.source_id)].append(r)
    metrics: dict[str, dict] = {}
    for (metric, unit, sid), items in groups.items():
        items.sort(key=lambda r: r.period_start)
        m = metrics.setdefault(metric, {"metric": metric, "series": []})
        points = [{
            "period_label": r.period_label, "value": r.value, "unit": r.unit, "flag_raw": r.flag_raw,
            "notes": r.notes, **_obs_provenance(ctx, r),
        } for r in items]
        newest = items[-1]
        m["series"].append({
            "source": ctx.brief(sid), "unit": unit, "frequency": newest.frequency, "points": points,
            "latest": points[-1], "is_demo": any(r.is_demo for r in items),
            "freshness": ctx.freshness_for(sid, newest.published_at or newest.period_end, newest.frequency),
            "next_release": _next_release(ctx, sid, newest),
        })
    ordered = sorted(metrics.values(), key=lambda m: (METRIC_ORDER.index(m["metric"]) if m["metric"] in METRIC_ORDER
                                                      else len(METRIC_ORDER), m["metric"]))
    for m in ordered:
        # The series with the NEWEST year first (a national 2025 figure before FAOSTAT's 2024), then the
        # longer, then the more reliable.
        m["series"].sort(key=lambda s: (-int((s["latest"]["period_start"] or "0000")[:4]), -len(s["points"]),
                                        _source_rank(ctx, ctx.source_id(s["source"]["key"]) or 0)))
    return {"available": bool(ordered), "metrics": ordered, "providers": ctx.providers("production", country=iso3)}


# ---------------------------------------------------------------------------
# Trade
# ---------------------------------------------------------------------------


def trade_section(ctx: Ctx, iso3: str, totals: Totals) -> dict:
    out = {}
    for flow in FLOWS:
        series = build_series(ctx, iso3, flow, "WLD", "A")
        latest_c = totals.latest_complete(iso3, flow)
        partners = partner_breakdown(ctx, iso3, flow, latest_c.year if latest_c else None, top=TOP_PARTNERS) \
            if latest_c else None
        mirror = mirror_declarations(ctx, iso3, flow)
        latest = candidate_total(ctx, latest_c, totals) if latest_c is not None else None
        own = reporter_ytd(ctx, iso3, flow)
        out[flow] = {
            "available": bool(series["series"]),
            "latest": latest,
            "series": series["series"],
            "excluded_partial": series["excluded_partial"],
            "discrepancies": series["discrepancies"],
            "partners": partners if partners and partners.get("available") else None,
            "mirror": mirror if mirror["rows"] else None,
            # The year so far from monthly data (ytd.py): the country's own figure, else what its
            # partners declare month by month; each with its source and months, never added up.
            "ytd": {"own": own["figure"], "status": own["status"], "last_month": own["last_month"],
                    "mirror": mirror_ytd(ctx, iso3, flow) if own["figure"] is None else None},
        }
    out["providers"] = section_providers(ctx, "exports", iso3)
    out["providers_import"] = section_providers(ctx, "imports", iso3)
    return out


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------


def prices_section(ctx: Ctx, iso3: str) -> dict:
    """Latest observation of each price series whose ORIGIN is the country, grouped by price type.
    Customs unit values of lots under 10 t are left out, as on the price pages (a 1.16 t lot from
    Chile at 8.48 USD/kg is not a bulk price)."""
    from .prices import bulk_unit_value_clause

    P = PriceObservation
    rows = ctx.db.scalars(
        select(P).where(P.is_current.is_(True), demo_clause(P, ctx.db), P.origin_iso3 == iso3,
                        bulk_unit_value_clause(P))
        .order_by(P.period_start.desc(), P.id.desc())
    )
    latest: dict[tuple, PriceObservation] = {}
    counts: dict[tuple, int] = defaultdict(int)
    for r in rows:
        k = (r.price_type, r.source_id, r.variety, r.market_iso3, r.market_location, r.color_grade, r.organic,
             r.currency, r.unit, r.terms)
        counts[k] += 1
        if k not in latest:
            latest[k] = r
    groups: dict[str, list[dict]] = defaultdict(list)
    for k, r in latest.items():
        groups[r.price_type].append({
            "price_type": r.price_type, "variety": r.variety, "variety_raw": r.variety_raw,
            "market_iso3": r.market_iso3, "market_location": r.market_location, "color_grade": r.color_grade,
            "organic": r.organic, "terms": r.terms, "price_value": r.price_value, "price_low": r.price_low,
            "price_high": r.price_high, "currency": r.currency, "unit": r.unit, "price_per_kg": r.price_per_kg,
            "usd_per_kg": r.usd_per_kg, "eur_per_kg": r.eur_per_kg, "observations": counts[k],
            **_obs_provenance(ctx, r),
        })
    out = []
    for pt in sorted(groups, key=lambda t: PRICE_TYPE_ORDER.index(t) if t in PRICE_TYPE_ORDER else 99):
        items = sorted(groups[pt], key=lambda x: (x["period_start"] or "", x["variety"] or ""), reverse=True)
        out.append({"price_type": pt, "rows": items[:PRICE_ROWS_PER_TYPE], "count": len(items),
                    "latest_period_label": items[0]["period_label"] if items else None,
                    "link": f"/prezzi?tipo={pt}&origini={iso3}"})
    return {"available": bool(out), "groups": out, "providers": price_providers(ctx, iso3)}


DECLARED_TRADE_SOURCES = ("un_comtrade", "eurostat_comext")


def _able(ctx: Ctx, providers: list[dict], iso3: str, kind: str) -> list[dict]:
    """Leave out a provider whose stored data shows it never produces this kind: an export-only
    collector (Uruguay's, Chile's) never fills an IMPORT block, a trade collector storing no prices never
    fills a price block. Kept: sources holding this kind of data (for this country or others) and
    sources that have stored nothing yet."""
    db = ctx.db
    T, P = TradeFlowObservation, PriceObservation
    # (each DISTINCT reads a whole table: once per database state, memo.py)
    if kind == "prices":
        have_ids = cached(db, "countries.sources_with", (kind,), lambda: set(db.scalars(select(P.source_id).distinct())))
    else:
        have_ids = cached(db, "countries.sources_with", (kind,),
                          lambda: set(db.scalars(select(T.source_id).where(T.flow == kind).distinct())))
    if not hasattr(ctx, "_sources_with_rows"):
        ctx._sources_with_rows = cached(db, "countries.sources_with_rows", (), lambda: {
            sid for model in (T, P, ProductionStat) for sid in db.scalars(select(model.source_id).distinct())})
    have = {s.key for sid in have_ids if (s := ctx.source(sid))}
    ran = {s.key for sid in ctx._sources_with_rows if (s := ctx.source(sid))}
    return [p for p in providers if p["key"] in have or p["key"] not in ran]


def section_providers(ctx: Ctx, key: str, iso3: str) -> list[dict]:
    """Sources that would fill one profile section for this country."""
    if key == "prices":
        return price_providers(ctx, iso3)
    if key in ("exports", "imports"):
        # Customs data declared by the country itself: the global datasets come first (a national
        # import series such as USDA GATS only answers for that country's imports).
        return _able(ctx, ctx.providers("trade", country=iso3, prefer=DECLARED_TRADE_SOURCES,
                                        country_first=key == "imports"), iso3, key[:-1])
    return ctx.providers(SECTION_CATEGORIES[key], country=iso3)


def price_providers(ctx: Ctx, iso3: str) -> list[dict]:
    """Price lists about the country, then sources publishing prices by origin (customs unit
    values are stored as prices by the trade collectors), then the other price lists."""
    return _able(ctx, ctx.providers(("prices", "trade"), country=iso3, prefer=ORIGIN_PRICE_SOURCES), iso3, "prices")


# ---------------------------------------------------------------------------
# News and regulations
# ---------------------------------------------------------------------------


def _news_item(ctx: Ctx, a: NewsArticle) -> dict:
    return {
        "id": a.id, "title": a.title, "title_it": a.title_it, "title_en": a.title_en, "language": a.language,
        "publisher": a.publisher, "url": a.url, "published_at": iso(a.published_at), "collected_at": iso(a.collected_at),
        "snippet": a.snippet, "summary_it": a.summary_it, "summary_en": a.summary_en, "ai_model": a.ai_model,
        "relevance_score": a.relevance_score, "duplicate_count": a.duplicate_count, "topics": a.topics or [],
        # what the article is about, in words: a headline in Ukrainian or Hungarian is still placed
        "topic_labels": {lng: [news_service.TOPICS[k][lng] for k in (a.topics or []) if k in news_service.TOPICS]
                         for lng in ("it", "en")},
        "source": ctx.brief(a.source_id), "is_demo": a.is_demo,
    }


def news_highlights(ctx: Ctx, iso3: str) -> list[dict]:
    """The one or two news items that matter most for this country's honey trade: articles of the
    last NEWS_HIGHLIGHT_DAYS days tagged with the country AND a trade topic (exports and imports,
    prices, duties, import restrictions), ranked by `services.news.importance`."""
    A = NewsArticle
    now = utcnow()
    since = now - timedelta(days=NEWS_HIGHLIGHT_DAYS)
    base = (demo_clause(A, ctx.db), A.duplicate_of_id.is_(None),
            A.relevance_score >= NEWS_HIGHLIGHT_MIN_RELEVANCE, _json_contains(A.countries, iso3))

    def trade(rows) -> list[NewsArticle]:
        return [a for a in rows
                if iso3 in (a.countries or []) and set(a.topics or []) & set(news_service.TRADE_TOPICS)]

    picked = trade(ctx.db.scalars(select(A).where(*base, _news_when() >= since)))
    picked.sort(key=lambda a: (-news_service.importance(a.relevance_score, a.duplicate_count,
                                                         a.published_at or a.collected_at, now), -a.id))
    if not picked:
        # Nothing in the period (a country whose honey trade is rarely written about): the latest
        # trade stories we hold, however old. Each line shows its own date, and the page says when
        # the newest article is not recent (`news.latest_at`).
        picked = trade(ctx.db.scalars(select(A).where(*base).order_by(_news_when().desc(), A.id.desc())
                                      .limit(NEWS_LIMIT * 4)))
    chosen: list[NewsArticle] = []
    for a in picked:
        when = a.published_at or a.collected_at
        # two outlets on the same story are one highlight: the second line is for another story
        if any(news_service.same_story(a.title_norm or "", when, c.title_norm or "", c.published_at or c.collected_at)
               for c in chosen):
            continue
        chosen.append(a)
        if len(chosen) >= NEWS_HIGHLIGHTS:
            break
    return [_news_item(ctx, a) for a in chosen]


def news_section(ctx: Ctx, iso3: str) -> dict:
    A = NewsArticle
    q = (select(A).where(demo_clause(A, ctx.db), A.duplicate_of_id.is_(None), _json_contains(A.countries, iso3))
         .order_by(_news_when().desc(), A.id.desc()).limit(NEWS_LIMIT * 4))
    items, seen = [], set()
    for a in ctx.db.scalars(q):
        if iso3 not in (a.countries or []):
            continue
        key = a.title_norm or a.title
        if key in seen:
            continue
        seen.add(key)
        items.append(_news_item(ctx, a))
        if len(items) >= NEWS_LIMIT:
            break
    highlights = news_highlights(ctx, iso3)
    since = _news_since()
    count_30d = sum(
        1 for c in ctx.db.scalars(
            select(A.countries).where(demo_clause(A, ctx.db), A.duplicate_of_id.is_(None), _news_when() >= since,
                                      _json_contains(A.countries, iso3)))
        if iso3 in (c or [])
    )
    dates = [d for d in (i["published_at"] or i["collected_at"] for i in items + highlights) if d]
    return {"available": bool(items), "items": items, "count_30d": count_30d, "days": NEWS_DAYS,
            "highlights": highlights, "highlight_days": NEWS_HIGHLIGHT_DAYS,
            # date of the newest article shown: the page says so when it is old ("latest news: July 2022")
            "latest_at": max(dates) if dates else None,
            "link": f"/notizie?country={iso3}", "providers": ctx.providers("news", country=iso3)}


def regulations_section(ctx: Ctx, country: Country) -> dict:
    R = RegulationItem
    codes = [c for c in (country.iso2, country.iso3) if c]
    q = (select(R).where(demo_clause(R, ctx.db), or_(_json_contains(R.countries, country.iso3), R.jurisdiction.in_(codes)))
         .order_by(R.published_at.desc().nulls_last(), R.id.desc()).limit(REG_LIMIT * 3))
    items = []
    for r in ctx.db.scalars(q):
        mentioned = country.iso3 in (r.countries or [])
        if not mentioned and r.jurisdiction not in codes:
            continue
        items.append({
            "id": r.id, "jurisdiction": r.jurisdiction, "doc_type": r.doc_type, "reference": r.reference,
            "title": r.title, "status": r.status, "published_at": iso(r.published_at),
            "effective_date": iso(r.effective_date), "url": r.url, "summary_it": r.summary_it,
            "summary_en": r.summary_en, "summary_is_ai": r.summary_is_ai, "source": ctx.brief(r.source_id),
            "collected_at": iso(r.collected_at), "is_demo": r.is_demo,
            "match": "mentioned" if mentioned else "jurisdiction",
        })
        if len(items) >= REG_LIMIT:
            break
    return {"available": bool(items), "items": items, "providers": ctx.providers("regulation", country=country.iso3)}


def context_section(country: Country) -> dict:
    p = country.profile or {}
    return {
        "available": bool(p),
        "label_it": CONTEXT_NOTE["it"], "label_en": CONTEXT_NOTE["en"],
        "is_collected_data": False,
        "varieties": p.get("varieties") or [],
        "harvest": p.get("harvest") or p.get("harvest_months"),
        "notes_it": p.get("notes_it"), "notes_en": p.get("notes_en"),
        "refs": p.get("refs") or [],
    }


# ---------------------------------------------------------------------------
# GET /countries
# ---------------------------------------------------------------------------


@router.get("")
def list_countries(db: Session = Depends(get_db)):
    ctx = Ctx(db)
    totals = Totals(ctx)
    exports = latest_totals(ctx, "export", totals=totals)
    imports = latest_totals(ctx, "import", totals=totals)
    # every production row of every country: one answer per database state (memo.py)
    production = cached(db, "countries.latest_production", (), lambda: latest_production(ctx))

    # Availability counts (one grouped query each, over every price and trade row: once per database state)
    P, T, A, R, S = PriceObservation, TradeFlowObservation, NewsArticle, RegulationItem, ProductionStat
    price_counts, prod_counts, trade_rep, mirror = cached(db, "countries.availability", (), lambda: _availability(db))

    news_30d: dict[str, int] = defaultdict(int)
    news_latest: dict[str, datetime] = {}
    news_any: set[str] = set()
    for countries, when in db.execute(select(A.countries, _news_when()).where(demo_clause(A, db), A.duplicate_of_id.is_(None),
                                                                              A.countries.is_not(None))):
        for c in countries or []:
            news_any.add(c)
            if when and when >= _news_since():
                news_30d[c] += 1
            if when and (c not in news_latest or when > news_latest[c]):
                news_latest[c] = when
    news_demo = bool(db.scalar(select(func.count()).select_from(A).where(demo_clause(A, db), A.is_demo.is_(True))))
    reg_counts: dict[str, int] = defaultdict(int)
    for countries, jur in db.execute(select(R.countries, R.jurisdiction).where(demo_clause(R, db))):
        for c in set(countries or []):
            reg_counts[c] += 1

    out = []
    for c in db.scalars(select(Country).order_by(Country.name_it)):
        reg_n = reg_counts.get(c.iso3, 0)
        flows = trade_rep.get(c.iso3, set())
        out.append({
            **_country_ref(c),
            "available": {
                "production": bool(prod_counts.get(c.iso3)),
                "exports": "export" in flows, "imports": "import" in flows,
                "exports_mirror": "export" in mirror.get(c.iso3, set()),
                "imports_mirror": "import" in mirror.get(c.iso3, set()),
                "prices": bool(price_counts.get(c.iso3)),
                "news": c.iso3 in news_any,
                "regulations": bool(reg_n),
                "context": bool(c.profile),
            },
            "metrics": {
                "exports": _headline(exports.get(c.iso3)),
                "imports": _headline(imports.get(c.iso3)),
                "production": production.get(c.iso3),
                "news_30d": {"count": news_30d.get(c.iso3, 0), "latest_at": iso(news_latest.get(c.iso3)),
                             "days": NEWS_DAYS} if c.iso3 in news_any else None,
                "prices_count": price_counts.get(c.iso3, 0),
                "regulations_count": reg_n,
            },
        })

    def meta(items: list[dict]) -> dict:
        items = [i for i in items if i]
        return {
            "countries": len(items),
            "years": sorted({i.get("year") for i in items if i.get("year")}),
            "sources": sources_used(ctx, items),
            "is_demo": any(i.get("is_demo") for i in items),
            "data_status": most_cautious(i.get("data_status") for i in items),
        }

    return {
        "countries": out,
        "priority": PRIORITY_ISO3,
        "metrics": {
            "exports": {**meta(list(exports.values())), "unit": "kg",
                        "providers": ctx.providers("trade", prefer=DECLARED_TRADE_SOURCES)},
            "imports": {**meta(list(imports.values())), "unit": "kg",
                        "providers": ctx.providers("trade", prefer=DECLARED_TRADE_SOURCES)},
            "production": {**meta(list(production.values())), "unit": "t", "providers": ctx.providers("production")},
            "news": {"countries": sum(1 for v in news_30d.values() if v), "days": NEWS_DAYS, "is_demo": news_demo,
                     "sources": [], "years": [], "providers": ctx.providers("news")},
        },
    }


def _availability(db: Session) -> tuple[dict, dict, dict[str, set[str]], dict[str, set[str]]]:
    P, T, S = PriceObservation, TradeFlowObservation, ProductionStat
    price_counts = dict(db.execute(select(P.origin_iso3, func.count()).where(P.is_current.is_(True), demo_clause(P, db))
                                   .group_by(P.origin_iso3)).all())
    prod_counts = dict(db.execute(select(S.country_iso3, func.count()).where(S.is_current.is_(True), demo_clause(S, db))
                                  .group_by(S.country_iso3)).all())
    trade_rep: dict[str, set[str]] = defaultdict(set)
    for reporter, flow in db.execute(select(T.reporter_iso3, T.flow).where(*base_where(db)).distinct()):
        trade_rep[reporter].add(flow)
    mirror: dict[str, set[str]] = defaultdict(set)
    for partner, flow in db.execute(select(T.partner_iso3, T.flow).where(*base_where(db),
                                                                         T.partner_iso3.not_in(sorted(PSEUDO_AREAS))).distinct()):
        mirror[partner].add("export" if flow == "import" else "import")
    return price_counts, prod_counts, dict(trade_rep), dict(mirror)


def _headline(total: dict | None) -> dict | None:
    if not total:
        return None
    keep = ("net_weight_kg", "usd_value", "unit_value_usd_per_kg", "year", "period_label", "source", "source_url",
            "published_at", "collected_at", "period_end", "frequency", "data_status", "is_demo",
            "summed_from_partners", "summed_from_months", "partners_count", "months_count", "yoy_volume_pct")
    return {k: total.get(k) for k in keep}


# ---------------------------------------------------------------------------
# GET /countries/{iso3}
# ---------------------------------------------------------------------------


@router.get("/{iso3}")
def country_profile(iso3: str, db: Session = Depends(get_db)):
    code = iso3.strip().upper()
    country = db.get(Country, code) if code.isalpha() and len(code) == 3 else None
    if country is None:
        raise HTTPException(404, "Paese sconosciuto / unknown country")
    ctx = Ctx(db)
    totals = Totals(ctx, reporters=[code])

    production = production_section(ctx, code)
    trade = trade_section(ctx, code, totals)
    prices = prices_section(ctx, code)
    news = news_section(ctx, code)
    regulations = regulations_section(ctx, country)
    context = context_section(country)

    availability = {
        "production": production["available"],
        "exports": trade["export"]["available"], "imports": trade["import"]["available"],
        "exports_mirror": trade["export"]["mirror"] is not None,
        "imports_mirror": trade["import"]["mirror"] is not None,
        "prices": prices["available"], "news": news["available"], "regulations": regulations["available"],
        "context": context["available"],
    }
    missing = []
    for key in ("production", "exports", "imports", "prices", "news", "regulations"):
        if not availability[key]:
            mirror_key = f"{key}_mirror" if key in ("exports", "imports") else None
            missing.append({
                "key": key, "category": SECTION_CATEGORIES[key],
                "partial_alternative": mirror_key if mirror_key and availability.get(mirror_key) else None,
                "providers": section_providers(ctx, key, code),
            })
    if not context["available"]:
        missing.append({"key": "context", "category": None, "partial_alternative": None, "providers": []})

    # Every source behind the figures on this page, with its freshness
    prov_rows: list[dict] = []
    for m in production["metrics"]:
        prov_rows += [s["latest"] for s in m["series"]]
    for flow in FLOWS:
        prov_rows += [s["points"][-1] for s in trade[flow]["series"] if s["points"]]
    for g in prices["groups"]:
        prov_rows += g["rows"]
    any_demo = any(r.get("is_demo") for r in prov_rows) or any(i["is_demo"] for i in news["items"]) \
        or any(i["is_demo"] for i in regulations["items"])

    return {
        "country": {**_country_ref(country), "region": country.region},
        "availability": availability,
        "production": production,
        "trade": trade,
        "prices": prices,
        "news": news,
        "regulations": regulations,
        "context": context,
        # Other sources (non-official): verified web findings, apart from every official figure above
        # (not in `availability`, `missing`, `sources` or the map list).
        "web_findings": web_findings_block(db, code),
        "missing": missing,
        "sources": sources_used(ctx, prov_rows),
        "is_demo": any_demo,
        "generated_at": iso(utcnow()),
        "today": date.today().isoformat(),
    }
