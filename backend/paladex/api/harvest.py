"""Harvest & production intelligence API (/api/harvest/...), Milestone 5.

    GET /harvest/production          production by country: latest year, value and change on the year
                                     before, per source and unit, with the status the source gives
                                     (published / estimate / provisional) and any official forecast
    GET /harvest/production/{iso3}   one country's production series for the charts (per metric, source
                                     and unit, never merged)
    GET /harvest/weather             the honey regions (curated context), the last 12 months of NASA POWER
                                     temperature and precipitation per region with their anomalies, and the
                                     rule-based flags with the rules themselves
    GET /harvest/reports             harvest / production reports (Osservatorio Nazionale Miele, USDA,
                                     DG AGRI...) and news tagged production or weather

Three kinds of content are kept apart here and labelled so in the UI:

* DATA: production statistics and weather observations, each with its provenance (source, exact
  link or API query, publication / collection date, period, status, reliability);
* CONTEXT: varieties and flowering / harvest months of each region, curated by hand
  (``reference/regions.py``), never presented as collected data;
* AUTOMATIC ASSESSMENTS: the flags below, computed on the fly by fixed, published rules from the
  weather data. They are not data, are never stored, and every answer carries ``RULES`` so the
  page can show exactly how they are made.

Region values are the average of the region's points (1-4 NASA POWER grid points); the
precipitation of a region in % of normal is the points' mean precipitation over their mean
1991-2020 normal. Nothing is interpolated: a month without data stays empty.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from ..collectors.weather import (
    CITATION,
    last_complete_month,
    month_label,
    month_window,
    parse_month_label,
)
from ..db import get_db
from ..enums import DataStatus, RunStatus
from ..models import (
    CollectionRun,
    Country,
    NewsArticle,
    ProductionStat,
    Report,
    Source,
    WeatherObservation,
    utcnow,
)
from ..reference.regions import Region, all_regions, context, get_region
from ..reference.regions import countries as region_countries
from .common import demo_clause, freshness, iso, source_brief
from .countries import TONNES_PER_UNIT, production_section
from .reports import serialize_report
from .trade import RELIABILITY_ORDER, Ctx, most_cautious, sources_used

router = APIRouter(prefix="/harvest", tags=["harvest"])

WEATHER_SOURCE = "nasa_power_weather"
MONTHS_SHOWN = 12
RECENT_MONTHS = 3          # the table's "last 3 months"; a flag touching them is "recent"

# ---------------------------------------------------------------------------
# Rules of the automatic assessments (shown to the user as they are)
# ---------------------------------------------------------------------------

DROUGHT_MAX_PCT = 60.0
HEAT_MIN_ANOMALY_C = 2.0
WET_MIN_PCT = 160.0
MIN_RUN = {"drought_watch": 2, "heat_stress": 2, "wet_season": 2}
# A percentage of a tiny normal (dry season) says little: precipitation rules skip those months.
RULE_MIN_NORMAL_MM = 10.0
FLAG_ORDER = ("drought_watch", "heat_stress", "wet_season")
# Plausibility check (a data-quality caution, not a correction): a point-month with more than 5 times
# its normal rainfall AND more than 300 mm is "exceptional, to verify". Seen live on 4 Nov 2026: NASA
# POWER gives 3,100 mm for February 2026 at Sibari (Calabria), many days of 200-530 mm, while ARPACAL's
# stations recorded a historic but far smaller event (hundreds of mm). The value stays as published;
# flags built on it say so.
EXCEPTIONAL_RATIO = 5.0
EXCEPTIONAL_MIN_MM = 300.0

ASSESSMENT_LABEL = {"it": "Valutazione automatica (regole), non dati confermati",
                    "en": "Automatic assessment (rules), not confirmed data"}

RULES = [
    {
        "key": "drought_watch", "metric": "precip_pct", "operator": "<", "threshold": DROUGHT_MAX_PCT, "unit": "%",
        "min_months": MIN_RUN["drought_watch"], "flowering_only": True,
        "label_it": "Siccità da monitorare", "label_en": "Drought watch",
        "rule_it": "Pioggia sotto il 60% della normale 1991-2020 per almeno 2 mesi di fila, durante la fioritura della regione.",
        "rule_en": "Rainfall below 60% of the 1991-2020 normal for at least 2 months in a row, during the region's flowering season.",
        "why_it": "Con poca pioggia le piante producono meno nettare: il raccolto della stagione può calare.",
        "why_en": "With little rain plants secrete less nectar: the season's crop may fall.",
    },
    {
        "key": "heat_stress", "metric": "temp_anomaly_c", "operator": ">=", "threshold": HEAT_MIN_ANOMALY_C, "unit": "°C",
        "min_months": MIN_RUN["heat_stress"], "flowering_only": True,
        "label_it": "Stress da caldo", "label_en": "Heat stress",
        "rule_it": "Temperatura media di almeno 2 °C sopra la normale 1991-2020 per almeno 2 mesi di fila, durante la fioritura.",
        "rule_en": "Mean temperature at least 2 °C above the 1991-2020 normal for at least 2 months in a row, during flowering.",
        "why_it": "Il caldo prolungato riduce il nettare dei fiori e affatica le colonie.",
        "why_en": "Lasting heat reduces the flowers' nectar and wears the colonies out.",
    },
    {
        "key": "wet_season", "metric": "precip_pct", "operator": ">", "threshold": WET_MIN_PCT, "unit": "%",
        "min_months": MIN_RUN["wet_season"], "flowering_only": True,
        "label_it": "Stagione piovosa", "label_en": "Wet season",
        "rule_it": "Pioggia oltre il 160% della normale 1991-2020 per almeno 2 mesi di fila, durante la fioritura.",
        "rule_en": "Rainfall above 160% of the 1991-2020 normal for at least 2 months in a row, during flowering.",
        "why_it": "Con piogge abbondanti le api escono poco a bottinare e il nettare si diluisce.",
        "why_en": "With heavy rain bees forage little and the nectar is diluted.",
    },
]

RULES_SCOPE = {
    "it": ("Le regole guardano solo i mesi di fioritura indicati per ogni regione (contesto curato) negli ultimi "
           "12 mesi disponibili. I mesi con una pioggia normale sotto 10 mm non contano per le regole sulla pioggia "
           "(nella stagione secca pochi millimetri cambiano molto la percentuale). Un mese senza dati interrompe la "
           "serie. Valori della regione: media dei suoi punti NASA POWER. Controllo di plausibilità: un punto con oltre 5 "
           "volte la sua pioggia normale e oltre 300 mm nel mese è segnato «eccezionale, da verificare» (evento reale "
           "o errore della serie NASA: confrontare con le stazioni locali); il valore resta quello pubblicato."),
    "en": ("The rules only look at each region's flowering months (curated context) in the last 12 months available. "
           "Months whose normal rainfall is under 10 mm do not count for the rainfall rules (in the dry season a few "
           "millimetres change the percentage a lot). A month without data breaks the run. Region values: mean of "
           "its NASA POWER points. Plausibility check: a point with more than 5 times its normal rainfall and over "
           "300 mm in the month is marked \"exceptional, to verify\" (a real event or an error in the NASA series: "
           "compare with local stations); the value stays as published."),
}

# Report sources that discuss harvests and production (plus any source in these categories).
REPORT_SOURCES = ("onm_informamiele", "ec_honey_market", "usda_honey_report")
REPORT_CATEGORIES = ("production", "weather")
REPORTS_PER_SOURCE = 3
REPORTS_LIMIT = 9
NEWS_TOPICS = ("production", "weather")
NEWS_LIMIT = 10
NEWS_MIN_RELEVANCE = 35        # the News page's default "relevant only" cutoff (frontend MIN_RELEVANT_SCORE)


# ---------------------------------------------------------------------------
# Production
# ---------------------------------------------------------------------------


def _prod_point(r: ProductionStat) -> dict:
    """A table value; the source, unit and reliability are given once per series."""
    return {
        "period_label": r.period_label, "year": r.period_start.year, "value": r.value, "unit": r.unit,
        "flag_raw": r.flag_raw, "notes": r.notes, "source_url": r.source_url, "published_at": iso(r.published_at),
        "collected_at": iso(r.collected_at), "data_status": r.data_status, "is_demo": r.is_demo,
    }


def _tonnes(value: float | None, unit: str | None) -> float | None:
    f = TONNES_PER_UNIT.get((unit or "").lower())
    return round(value * f, 1) if value is not None and f is not None else None


def production_table(ctx: Ctx, scope: str = "monitored") -> dict:
    """Per country and per (source, unit): the newest year that is not a forecast, the year before
    (from the same source and unit, exactly one year earlier) and the change; a newer official
    forecast, if any, is reported apart."""
    P = ProductionStat
    monitored = set(region_countries())
    where = [P.is_current.is_(True), demo_clause(P, ctx.db), P.metric == "production", P.frequency == "A"]
    # the source coverage (to rank sources) is counted over every country, whatever the scope
    coverage: dict[int, set[str]] = defaultdict(set)
    for sid, iso3 in ctx.db.execute(select(P.source_id, P.country_iso3).where(*where).distinct()):
        coverage[sid].add(iso3)
    all_countries = {iso3 for c in coverage.values() for iso3 in c}
    if scope != "all":
        where.append(P.country_iso3.in_(sorted(monitored)))
    rows = ctx.db.scalars(select(P).where(*where).order_by(P.period_start))
    groups: dict[tuple[str, int, str], list[ProductionStat]] = defaultdict(list)
    for r in rows:
        groups[(r.country_iso3, r.source_id, r.unit)].append(r)
    regions_by_country: dict[str, list[str]] = defaultdict(list)
    for reg in all_regions():
        regions_by_country[reg.country_iso3].append(reg.key)
    by_country: dict[str, list[dict]] = defaultdict(list)
    for (iso3, sid, unit), items in groups.items():
        actual = [r for r in items if r.data_status != DataStatus.FORECAST.value]
        forecasts = [r for r in items if r.data_status == DataStatus.FORECAST.value]
        latest = actual[-1] if actual else None
        prev = next((r for r in reversed(actual[:-1]) if latest and r.period_start.year == latest.period_start.year - 1),
                    None)
        change = round(100.0 * (latest.value - prev.value) / prev.value, 1) if latest and prev and prev.value else None
        fc = [r for r in forecasts if latest is None or r.period_start > latest.period_start]
        src = ctx.source(sid)
        rel = RELIABILITY_ORDER.index(src.reliability) if src and src.reliability in RELIABILITY_ORDER else 99
        by_country[iso3].append({
            "source": ctx.brief(sid), "unit": unit, "reliability": src.reliability if src else None,
            "frequency": "A",
            "latest": _prod_point(latest) if latest else None,
            "previous": _prod_point(prev) if prev else None,
            "change_pct": change,
            "forecast": _prod_point(fc[-1]) if fc else None,
            "latest_t": _tonnes(latest.value, unit) if latest else None,
            "years": len(actual),
            # official sources first, then the newest year (IBGE's 2025 figure before FAOSTAT's 2024
            # one), then the source covering most countries
            "_rank": (rel, -(latest.period_start.year if latest else 0), -len(coverage[sid])),
        })
    out = []
    for iso3, series in by_country.items():
        series.sort(key=lambda s: s["_rank"])
        for s in series:
            s.pop("_rank")
        names = ctx.names(iso3)
        out.append({
            "iso3": iso3, **names, "monitored": iso3 in monitored, "regions": regions_by_country.get(iso3, []),
            "series": series,
            # the first series (most reliable, newest year, widest coverage) labels and orders the row
            "primary_t": series[0]["latest_t"], "primary_year": (series[0]["latest"] or {}).get("year"),
            "is_demo": any((s["latest"] or {}).get("is_demo") for s in series),
        })
    out.sort(key=lambda c: (c["primary_t"] is None, -(c["primary_t"] or 0), c["iso3"]))
    latest_values = [s["latest"] for c in out for s in c["series"] if s["latest"]]
    with_source = [{**s["latest"], "source": s["source"], "frequency": "A"} for c in out for s in c["series"] if s["latest"]]
    return {
        "available": bool(all_countries),
        "scope": "all" if scope == "all" else "monitored",
        "countries": out,
        "monitored": list(region_countries()),
        "countries_with_data": len(all_countries),
        "monitored_with_data": len(all_countries & monitored),
        "years": sorted({p["year"] for p in latest_values}),
        "sources": sources_used(ctx, with_source),
        "providers": ctx.providers("production"),
        "data_status": most_cautious(p["data_status"] for p in latest_values),
    }


@router.get("/production")
def harvest_production(scope: str = Query("monitored", pattern="^(monitored|all)$"), db: Session = Depends(get_db)):
    """`scope=monitored` (default): the countries with honey regions on this page; `all`: every country."""
    ctx = Ctx(db)
    return {**production_table(ctx, scope), "generated_at": iso(utcnow())}


@router.get("/production/{iso3}")
def harvest_production_country(iso3: str, db: Session = Depends(get_db)):
    code = iso3.strip().upper()
    country = db.get(Country, code) if code.isalpha() and len(code) == 3 else None
    if country is None:
        raise HTTPException(404, "Paese sconosciuto / unknown country")
    ctx = Ctx(db)
    section = production_section(ctx, code)
    rows = [p for m in section["metrics"] for s in m["series"] for p in s["points"]]
    return {
        "iso3": code, "name_it": country.name_it, "name_en": country.name_en,
        "regions": [r.key for r in all_regions() if r.country_iso3 == code],
        **section,
        "sources": sources_used(ctx, [s["latest"] for m in section["metrics"] for s in m["series"]]),
        "is_demo": any(p.get("is_demo") for p in rows),
    }


# ---------------------------------------------------------------------------
# Weather: region months, flags
# ---------------------------------------------------------------------------


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def region_month(region: Region, label: str, rows: dict[tuple[str, str], WeatherObservation]) -> dict:
    """One region-month: averages over the points that have this month (never filled in)."""
    ym = parse_month_label(label)
    m = ym[1] if ym else 0
    vals = [rows[(p.key, label)] for p in region.points if (p.key, label) in rows]
    pts = []
    for p in region.points:
        r = rows.get((p.key, label))
        if r is None:
            continue
        e = r.extra or {}
        normal = e.get("normal_precip_mm")
        pts.append({
            "exceptional": is_exceptional(r.precip_mm, normal),
            "point": p.key, "name": p.name, "temp_mean_c": r.temp_mean_c, "temp_anomaly_c": r.temp_anomaly_c,
            "precip_mm": r.precip_mm, "precip_anomaly_pct": r.precip_anomaly_pct,
            "normal_temp_c": e.get("normal_temp_c"), "normal_precip_mm": e.get("normal_precip_mm"),
            "basis": e.get("basis"), "nasa_sources": e.get("sources") or [], "data_status": r.data_status,
            "source_url": r.source_url, "collected_at": iso(r.collected_at), "last_seen_at": iso(r.last_seen_at),
            "revision": r.revision,
        })
    pairs = [(r.precip_mm, (r.extra or {}).get("normal_precip_mm")) for r in vals]
    pairs = [(pr, n) for pr, n in pairs if pr is not None and n is not None]
    normal_mm = _mean([n for _, n in pairs])
    pct = round(100.0 * sum(pr for pr, _ in pairs) / sum(n for _, n in pairs), 1) \
        if pairs and sum(n for _, n in pairs) >= 1.0 else None
    statuses = [r.data_status for r in vals]
    exceptional = [p["name"] for p in pts if p["exceptional"]]
    return {
        "period_label": label,
        "temp_mean_c": _mean([r.temp_mean_c for r in vals if r.temp_mean_c is not None]),
        "temp_anomaly_c": _mean([r.temp_anomaly_c for r in vals if r.temp_anomaly_c is not None]),
        "normal_temp_c": _mean([n for n in ((r.extra or {}).get("normal_temp_c") for r in vals) if n is not None]),
        "precip_mm": _mean([r.precip_mm for r in vals if r.precip_mm is not None]),
        "precip_normal_mm": normal_mm,
        "precip_pct": pct,
        "points_with_data": len(vals), "points_total": len(region.points),
        "data_status": most_cautious(statuses) if statuses else None,
        "exceptional_points": exceptional,
        "flowering": m in region.flowering_months, "harvest": m in region.harvest_months,
        "points": pts,
    }


def is_exceptional(precip_mm: float | None, normal_mm: float | None) -> bool:
    """The plausibility check above: far outside the point's own climate, to verify on the source."""
    return (precip_mm is not None and normal_mm is not None and normal_mm > 0
            and precip_mm > EXCEPTIONAL_RATIO * normal_mm and precip_mm > EXCEPTIONAL_MIN_MM)


def _meets(rule_key: str, md: dict) -> bool:
    if rule_key == "heat_stress":
        return md["temp_anomaly_c"] is not None and md["temp_anomaly_c"] >= HEAT_MIN_ANOMALY_C
    pct, normal = md["precip_pct"], md["precip_normal_mm"]
    if pct is None or normal is None or normal < RULE_MIN_NORMAL_MM:
        return False
    return pct < DROUGHT_MAX_PCT if rule_key == "drought_watch" else pct > WET_MIN_PCT


def _flag(key: str, run: list[dict], recent_from: str | None) -> dict:
    metric = "temp_anomaly_c" if key == "heat_stress" else "precip_pct"
    return {
        "rule": key, "months": [md["period_label"] for md in run],
        "values": [md[metric] for md in run], "metric": metric,
        "data_status": most_cautious(md["data_status"] for md in run),
        "recent": bool(recent_from) and run[-1]["period_label"] >= recent_from,
        # months whose value includes an exceptional point (plausibility check): verify
        "exceptional_months": [md["period_label"] for md in run if md.get("exceptional_points")]
        if metric == "precip_pct" else [],
    }


def evaluate_flags(region_months: list[dict], recent_from: str | None) -> list[dict]:
    """Apply RULES to a region's months (chronological). A run of qualifying flowering months long
    enough for the rule gives one flag; a month that does not qualify (or has no data) ends the run."""
    flags: list[dict] = []
    for rule in RULES:
        key = rule["key"]
        run: list[dict] = []
        for md in [*region_months, None]:          # None closes the last run
            if md is not None and md["flowering"] and _meets(key, md):
                run.append(md)
                continue
            if len(run) >= MIN_RUN[key]:
                flags.append(_flag(key, run, recent_from))
            run = []
    flags.sort(key=lambda f: (not f["recent"], FLAG_ORDER.index(f["rule"]), f["months"][0]))
    return flags


def _condition(flags: list[dict], has_data: bool) -> str:
    if not has_data:
        return "no_data"
    return flags[0]["rule"] if flags else "normal"


def _weather_collection(db: Session, src: Source | None) -> dict:
    if src is None:
        return {"state": "unknown", "last_run_at": None, "last_run_status": None, "enabled": False}
    running = db.scalar(select(func.count()).select_from(CollectionRun).where(
        CollectionRun.source_id == src.id, CollectionRun.status == RunStatus.RUNNING.value)) or 0
    state = "running" if running else ("never" if src.last_run_at is None else (src.last_run_status or "unknown"))
    return {"state": state, "last_run_at": iso(src.last_run_at), "last_run_status": src.last_run_status,
            "last_success_at": iso(src.last_success_at), "enabled": bool(src.enabled)}


def _weather_rows(db: Session) -> dict[tuple[str, str], WeatherObservation]:
    W = WeatherObservation
    rows: dict[tuple[str, str], WeatherObservation] = {}
    for r in db.scalars(select(W).where(W.is_current.is_(True), demo_clause(W, db), W.frequency == "M")):
        point = (r.extra or {}).get("point") or r.series_key.split("|", 1)[0]
        rows[(point, r.period_label)] = r
    return rows


def _window(rows: dict[tuple[str, str], WeatherObservation]) -> list[str]:
    """The MONTHS_SHOWN months ending with the newest month held (whatever its age: the page shows
    its period, never presents it as current)."""
    latest = max((label for _, label in rows), default=None)
    return [month_label(ym) for ym in month_window(parse_month_label(latest), MONTHS_SHOWN)] if latest else []


def _brief_month(md: dict) -> dict:
    return {k: v for k, v in md.items() if k != "points"}


def _region_payload(ctx: Ctx, reg: Region, months: list[str], rows: dict, detail: bool) -> dict:
    series = [region_month(reg, label, rows) for label in months]
    recent_from = months[-RECENT_MONTHS] if len(months) >= RECENT_MONTHS else (months[0] if months else None)
    has_data = any(md["points_with_data"] for md in series)
    flags = evaluate_flags(series, recent_from) if has_data else []
    with_data = [md for md in series if md["points_with_data"]]
    out = {
        "key": reg.key, "country_iso3": reg.country_iso3,
        **{f"country_{k}": v for k, v in ctx.names(reg.country_iso3).items()},
        "name_it": reg.name_it, "name_en": reg.name_en,
        "lat": round(sum(p.lat for p in reg.points) / len(reg.points), 2),
        "lon": round(sum(p.lon for p in reg.points) / len(reg.points), 2),
        "points": [{"key": p.key, "name": p.name, "lat": p.lat, "lon": p.lon} for p in reg.points],
        "context": context(reg),
        "recent": [_brief_month(md) for md in series[-RECENT_MONTHS:]],
        "latest_period_label": with_data[-1]["period_label"] if with_data else None,
        "flags": flags,
        "condition": _condition(flags, has_data),
        "condition_recent": next((f["rule"] for f in flags if f["recent"]), None),
        "has_data": has_data,
    }
    if detail:
        out["months"] = series
    return out


def _weather_meta(db: Session, rows: dict, months: list[str]) -> dict:
    src = db.scalars(select(Source).where(Source.key == WEATHER_SOURCE)).first()
    all_rows = list(rows.values())
    latest = months[-1] if months else None
    latest_rows = [r for (_, label), r in rows.items() if label == latest]
    expected = month_label(last_complete_month(date.today()))
    return {
        "available": bool(rows),
        "source": ({**source_brief(src), "freshness": freshness(src), "expected_update": src.expected_update,
                    "expected_update_en": src.expected_update_en, "terms_note": src.terms_note} if src else None),
        "collection": _weather_collection(db, src),
        "citation": CITATION,
        "accessed_at": iso(max((r.last_seen_at for r in all_rows), default=None)),
        # service versions of the answers behind the rows (POWER asks for service, version and date accessed)
        "api_versions": sorted({v for v in ((r.extra or {}).get("api_version") for r in all_rows) if v}),
        "months": months,
        "recent_months": months[-RECENT_MONTHS:],
        "latest_period_label": latest,
        "latest_data_status": most_cautious(r.data_status for r in latest_rows) if latest_rows else None,
        "expected_latest_period_label": expected,
        "behind_expected": bool(latest) and latest < month_label(_prev_month(expected)),
        "baseline": "1991-2020",
        "rules": RULES,
        "rules_scope_it": RULES_SCOPE["it"], "rules_scope_en": RULES_SCOPE["en"],
        "assessment_label_it": ASSESSMENT_LABEL["it"], "assessment_label_en": ASSESSMENT_LABEL["en"],
        "rule_min_normal_mm": RULE_MIN_NORMAL_MM,
        "exceptional_ratio": EXCEPTIONAL_RATIO, "exceptional_min_mm": EXCEPTIONAL_MIN_MM,
        "is_demo": any(r.is_demo for r in all_rows),
        "generated_at": iso(utcnow()),
    }


@router.get("/weather")
def harvest_weather(db: Session = Depends(get_db)):
    ctx = Ctx(db)
    rows = _weather_rows(db)
    months = _window(rows)
    regions = [_region_payload(ctx, reg, months, rows, detail=False) for reg in all_regions()]
    countries = [{"iso3": iso3, **ctx.names(iso3), "regions": [r["key"] for r in regions if r["country_iso3"] == iso3]}
                 for iso3 in region_countries()]
    return {**_weather_meta(db, rows, months), "regions": regions, "countries": countries,
            "regions_with_data": sum(1 for r in regions if r["has_data"])}


@router.get("/weather/{region_key}")
def harvest_weather_region(region_key: str, db: Session = Depends(get_db)):
    reg = get_region(region_key.strip().upper())
    if reg is None:
        raise HTTPException(404, "Regione sconosciuta / unknown region")
    ctx = Ctx(db)
    rows = _weather_rows(db)
    months = _window(rows)
    return {**_weather_meta(db, rows, months), "region": _region_payload(ctx, reg, months, rows, detail=True)}


def _prev_month(label: str) -> tuple[int, int]:
    y, m = parse_month_label(label) or (0, 1)
    return (y, m - 1) if m > 1 else (y - 1, 12)


# ---------------------------------------------------------------------------
# Reports and news
# ---------------------------------------------------------------------------


def _json_contains(column, code: str):
    return cast(column, String).like(f'%"{code}"%')


@router.get("/reports")
def harvest_reports(db: Session = Depends(get_db)):
    ctx = Ctx(db)
    report_sids = [s.id for s in ctx.sources.values() if s.key in REPORT_SOURCES or s.category in REPORT_CATEGORIES]
    picked: list[Report] = []
    per_source: dict[int, int] = defaultdict(int)
    if report_sids:
        q = (select(Report).where(demo_clause(Report, db), Report.source_id.in_(report_sids))
             .order_by(Report.published_at.desc().nulls_last(), Report.collected_at.desc(), Report.id.desc()))
        for r in db.scalars(q):
            if per_source[r.source_id] >= REPORTS_PER_SOURCE:
                continue
            per_source[r.source_id] += 1
            picked.append(r)
            if len(picked) >= REPORTS_LIMIT:
                break
    reports = [serialize_report(r, ctx.source(r.source_id), None) for r in picked]

    A = NewsArticle
    when = func.coalesce(A.published_at, A.collected_at)
    q = (select(A).where(demo_clause(A, db), A.duplicate_of_id.is_(None), A.relevance_score >= NEWS_MIN_RELEVANCE,
                         or_(*[_json_contains(A.topics, t) for t in NEWS_TOPICS]))
         .order_by(when.desc(), A.id.desc()).limit(NEWS_LIMIT * 4))
    news, seen = [], set()
    for a in db.scalars(q):
        topics = [t for t in (a.topics or []) if t in NEWS_TOPICS]
        key = a.title_norm or a.title
        if not topics or key in seen:
            continue
        seen.add(key)
        news.append({
            "id": a.id, "title": a.title, "title_it": a.title_it, "title_en": a.title_en, "language": a.language,
            "publisher": a.publisher, "url": a.url, "published_at": iso(a.published_at), "collected_at": iso(a.collected_at),
            "snippet": a.snippet, "summary_it": a.summary_it, "summary_en": a.summary_en, "ai_model": a.ai_model,
            "countries": a.countries or [], "topics": a.topics or [], "harvest_topics": topics,
            "relevance_score": a.relevance_score, "source": ctx.brief(a.source_id), "is_demo": a.is_demo,
        })
        if len(news) >= NEWS_LIMIT:
            break
    return {
        "reports": reports,
        "news": news,
        "report_providers": [p for p in ctx.providers(("reports", "prices", *REPORT_CATEGORIES), prefer=REPORT_SOURCES)
                             if p["key"] in REPORT_SOURCES or (ctx.sources[ctx.source_id(p["key"])].category in REPORT_CATEGORIES)],
        "news_providers": ctx.providers("news"),
        "news_link": "/notizie?topic=production,weather",
        "news_min_relevance": NEWS_MIN_RELEVANCE,
        "is_demo": any(r["is_demo"] for r in reports) or any(n["is_demo"] for n in news),
    }
