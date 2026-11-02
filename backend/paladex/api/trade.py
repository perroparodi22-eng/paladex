"""International trade API (/api/trade/...): natural honey, HS 0409.

Endpoints:
    GET /trade/facets    reporters, partners, years / months, sources and the default year per flow
    GET /trade/leaders   ranking of reporting countries for one flow and one year
    GET /trade/flows     partner breakdown (top N + others) of one reporter, one flow, one year
    GET /trade/series    time series of one reporter / partner / flow, one line per source

Data rules enforced here (docs/DEVELOPING.md):

* Current revisions only (`is_current`), demo rows only when demo display is on (`demo_clause`).
* **One source per figure.** Two sources reporting the same reporter / flow / period are never
  summed or averaged. A ranking may show different sources on different rows; every row names
  its own. A time series is returned per source, so disagreement stays visible.
* **Declared flows only.** A country's declared exports and what its customers declare as
  imports from it ("mirror data") differ (FOB vs CIF, timing, re-exports, confidential trade).
  They are never merged. The mirror view (`basis=mirror`) is a separate, labelled basis.
* **Totals.** A reporter's World row (partner `WLD`) is the total when it exists. Otherwise the
  partner rows are summed and the figure is flagged `summed_from_partners`. An annual total built
  from monthly rows is flagged `summed_from_months` and needs all twelve months; incomplete years
  are listed apart (`incomplete`) and never ranked against full years.
* **Values** use the USD value stored at ingest (`usd_value`, FX-normalised by `services.fx`), or
  the value itself when it was declared in USD. No exchange rate is guessed here: a total with an
  unconverted row has `usd_value = null` and `fx_missing = true`, and keeps its original value.
* **Unit value** (USD/kg) = USD value / net weight, computed only on rows that carry both. It is
  a customs average, not a market quotation.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Iterable, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, case, distinct, extract, func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..enums import SourceKind
from ..models import Country, Source, TradeFlowObservation
from .common import demo_clause, freshness, iso, source_brief

router = APIRouter(prefix="/trade", tags=["trade"])

T = TradeFlowObservation

FLOWS = ("import", "export")
# Pseudo-areas: never a "country" in a ranking or a partner breakdown.
PSEUDO_AREAS = frozenset({"WLD", "EU27", "EU28", "EXTRA_EU", "INTRA_EU"})
# Aggregates that may legitimately appear as a reporter (EU totals from Eurostat).
AGGREGATE_REPORTERS = frozenset({"EU27", "EU28"})
# Frequencies used for annual figures and time series. Weekly surveillance data (TAXUD) is
# provisional and covers extra-EU imports only, so it is not used to build annual totals.
TOTAL_FREQS = ("A", "M")
# Tie-break only (after completeness, World row and reliability): broadest consistent coverage first.
SOURCE_PREFERENCE = ("un_comtrade", "eurostat_comext", "usda_fas_gats")
RELIABILITY_ORDER = ("official", "industry", "trade_press", "aggregator", "user", "ai", "demo")
# Most cautious status wins when a figure combines rows with different statuses.
STATUS_CAUTION = ("demo", "ai_assessment", "forecast", "estimate", "provisional", "user_entered", "published", "live")
# A year is the default only if at least this share of the previous year's reporters is complete.
PARTIAL_COVERAGE = 0.6
# Two sources differing by more than this on the same period are reported as a discrepancy.
DISCREPANCY_THRESHOLD = 0.10
# World total vs sum of partners: a gap above this share is shown as "not allocated".
UNALLOCATED_MIN_SHARE = 0.005
# When a source declares no rhythm, judge freshness by the data's frequency.
FREQ_MAX_AGE_DAYS = {"A": 550, "M": 75, "W": 21}

Flow = Literal["import", "export"]
Metric = Literal["volume", "value"]


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------


@dataclass
class Agg:
    """Sum of trade rows plus the provenance of what was summed."""

    kg: float | None = None
    usd: float | None = None
    value: float | None = None
    kg_n: int = 0
    usd_n: int = 0
    val_n: int = 0
    pair_kg: float = 0.0
    pair_usd: float = 0.0
    n: int = 0
    periods: int = 0
    partners: int = 0
    start: date | None = None
    end: date | None = None
    label: str | None = None
    published_at: date | None = None
    collected_at: datetime | None = None
    is_demo: bool = False
    statuses: set[str] = field(default_factory=set)
    source_url: str | None = None
    currencies: set[str] = field(default_factory=set)
    value_basis: str | None = None

    @classmethod
    def from_row(cls, r) -> Agg:
        currencies = {c for c in (r.ccy_min, r.ccy_max) if c}
        return cls(
            kg=r.kg if r.kg_n else None, usd=r.usd if r.usd_n else None, value=r.val if r.val_n else None,
            kg_n=r.kg_n or 0, usd_n=r.usd_n or 0, val_n=r.val_n or 0,
            pair_kg=r.pair_kg or 0.0, pair_usd=r.pair_usd or 0.0, n=r.n or 0, periods=r.periods or 0,
            partners=getattr(r, "partners", 0) or 0, start=r.start, end=r.end, label=r.label,
            published_at=r.pub, collected_at=r.col, is_demo=bool(r.demo),
            statuses={s for s in (r.statuses or "").split(",") if s}, source_url=r.url,
            currencies=currencies, value_basis=r.vb,
        )

    def merge(self, other: Agg) -> Agg:
        def add(a, b):
            return b if a is None else a if b is None else a + b

        def mx(a, b):
            return b if a is None else a if b is None else max(a, b)

        def mn(a, b):
            return b if a is None else a if b is None else min(a, b)

        return Agg(
            kg=add(self.kg, other.kg), usd=add(self.usd, other.usd), value=add(self.value, other.value),
            kg_n=self.kg_n + other.kg_n, usd_n=self.usd_n + other.usd_n, val_n=self.val_n + other.val_n,
            pair_kg=self.pair_kg + other.pair_kg, pair_usd=self.pair_usd + other.pair_usd, n=self.n + other.n,
            periods=self.periods + other.periods, partners=max(self.partners, other.partners),
            start=mn(self.start, other.start), end=mx(self.end, other.end), label=self.label or other.label,
            published_at=mx(self.published_at, other.published_at), collected_at=mx(self.collected_at, other.collected_at),
            is_demo=self.is_demo or other.is_demo, statuses=self.statuses | other.statuses,
            source_url=self.source_url or other.source_url, currencies=self.currencies | other.currencies,
            value_basis=self.value_basis or other.value_basis,
        )

    @property
    def fx_missing(self) -> bool:
        return self.val_n > self.usd_n

    @property
    def usd_total(self) -> float | None:
        """USD total, or None when any summed row has no USD conversion."""
        return None if self.fx_missing or self.usd is None else self.usd

    @property
    def unit_value(self) -> float | None:
        return round(self.pair_usd / self.pair_kg, 4) if self.pair_kg > 0 and self.pair_usd > 0 else None

    @property
    def currency(self) -> str | None:
        return next(iter(self.currencies)) if len(self.currencies) == 1 else None

    @property
    def original_value(self) -> float | None:
        return self.value if self.currency else None

    @property
    def data_status(self) -> str | None:
        return most_cautious(self.statuses)


def most_cautious(statuses: Iterable[str | None]) -> str | None:
    found = {s for s in statuses if s}
    if not found:
        return None
    for s in STATUS_CAUTION:
        if s in found:
            return s
    return sorted(found)[0]


def _usd_expr():
    """USD value as stored at ingest, or the declared value when it is already in USD."""
    return func.coalesce(T.usd_value, case((T.currency == "USD", T.value), else_=None))


def _agg_columns() -> list:
    usd = _usd_expr()
    both = and_(T.net_weight_kg.is_not(None), usd.is_not(None))
    return [
        func.sum(T.net_weight_kg).label("kg"), func.count(T.net_weight_kg).label("kg_n"),
        func.sum(usd).label("usd"), func.count(usd).label("usd_n"),
        func.sum(T.value).label("val"), func.count(T.value).label("val_n"),
        func.sum(case((both, T.net_weight_kg), else_=0.0)).label("pair_kg"),
        func.sum(case((both, usd), else_=0.0)).label("pair_usd"),
        func.count().label("n"), func.count(distinct(T.period_start)).label("periods"),
        func.min(T.period_start).label("start"), func.max(T.period_end).label("end"),
        func.max(T.period_label).label("label"),
        func.max(T.published_at).label("pub"), func.max(T.collected_at).label("col"),
        func.max(case((T.is_demo.is_(True), 1), else_=0)).label("demo"),
        func.max(T.source_url).label("url"),
        func.group_concat(distinct(T.data_status)).label("statuses"),
        func.min(T.currency).label("ccy_min"), func.max(T.currency).label("ccy_max"),
        func.max(T.value_basis).label("vb"),
    ]


def base_where(db: Session) -> list:
    return [T.is_current.is_(True), demo_clause(T, db), T.hs_code.like("0409%")]


def _year_col():
    return extract("year", T.period_start)


def _partner_filter():
    """Countries, unknown partner codes and the World row; never partner groups (EU27, EXTRA_EU...)."""
    return T.partner_iso3.not_in(sorted(PSEUDO_AREAS - {"WLD"}))


def _is_world():
    return case((T.partner_iso3 == "WLD", 1), else_=0)


# ---------------------------------------------------------------------------
# Candidate totals: one per reporter x flow x year x source x frequency
# ---------------------------------------------------------------------------


@dataclass
class Candidate:
    reporter: str
    flow: str
    year: int
    source_id: int
    freq: str
    world: Agg | None = None
    parts: Agg | None = None

    @property
    def periods(self) -> int:
        return max(self.world.periods if self.world else 0, self.parts.periods if self.parts else 0)

    @property
    def complete(self) -> bool:
        return self.freq == "A" or self.periods >= 12

    @property
    def uses_world(self) -> bool:
        return self.world is not None and self.world.periods >= (self.parts.periods if self.parts else 0)

    @property
    def total(self) -> Agg:
        return self.world if self.uses_world else self.parts  # type: ignore[return-value]

    @property
    def summed_from_partners(self) -> bool:
        return not self.uses_world

    @property
    def summed_from_months(self) -> bool:
        return self.freq == "M"

    @property
    def partners_count(self) -> int:
        return self.parts.partners if self.parts else 0


class Ctx:
    """Per-request lookups: sources and country names."""

    def __init__(self, db: Session, today: date | None = None):
        self.db = db
        self.today = today or date.today()
        self.sources: dict[int, Source] = {s.id: s for s in db.scalars(select(Source))}
        self.countries: dict[str, Country] = {c.iso3: c for c in db.scalars(select(Country))}

    def source(self, sid: int | None) -> Source | None:
        return self.sources.get(sid) if sid is not None else None

    def brief(self, sid: int | None) -> dict | None:
        return source_brief(self.source(sid))

    def source_id(self, key: str) -> int | None:
        return next((s.id for s in self.sources.values() if s.key == key), None)

    def is_country(self, iso3: str | None) -> bool:
        return bool(iso3) and iso3 not in PSEUDO_AREAS and iso3 in self.countries

    def names(self, iso3: str) -> dict:
        c = self.countries.get(iso3)
        if c is not None:
            return {"name_it": c.name_it, "name_en": c.name_en}
        from ..reference.countries import AGGREGATES

        if iso3 in AGGREGATES:
            return {"name_it": AGGREGATES[iso3]["name_it"], "name_en": AGGREGATES[iso3]["name_en"]}
        return {"name_it": None, "name_en": None}

    def rank_key(self, c: Candidate) -> tuple:
        src = self.source(c.source_id)
        rel = RELIABILITY_ORDER.index(src.reliability) if src and src.reliability in RELIABILITY_ORDER else len(RELIABILITY_ORDER)
        pref = SOURCE_PREFERENCE.index(src.key) if src and src.key in SOURCE_PREFERENCE else len(SOURCE_PREFERENCE)
        return (c.complete, c.freq == "A", c.uses_world, -rel, -pref, c.partners_count, c.periods)

    def providers(self, category: str = "trade") -> list[dict]:
        out = [
            {"key": s.key, "name": s.name, "publisher": s.publisher, "enabled": s.enabled,
             "last_run_status": s.last_run_status, "expected_update": s.expected_update}
            for s in self.sources.values()
            if s.category == category and s.key != "demo" and s.kind != SourceKind.MANUAL.value
        ]
        return sorted(out, key=lambda p: (not p["enabled"], p["name"]))

    def freshness_for(self, sid: int, ref: date | None, freq: str | None) -> dict:
        """Source freshness; for a source without run metadata (demo, imported rows), judged
        from the newest data actually shown."""
        src = self.source(sid)
        if src is not None:
            f = freshness(src, self.today)
            if f["status"] != "never":
                return f
        return item_freshness(ref, src.expected_max_age_days if src else None, freq, self.today)


def item_freshness(ref: date | None, expected_days: int | None, freq: str | None, today: date) -> dict:
    if ref is None:
        return {"status": "never", "age_days": None, "reference_date": None}
    exp = expected_days or FREQ_MAX_AGE_DAYS.get(freq or "")
    age = (today - ref).days
    if not exp:
        status = "unknown"
    elif age <= exp:
        status = "current"
    elif age <= exp * 1.5:
        status = "aging"
    else:
        status = "stale"
    return {"status": status, "age_days": age, "reference_date": ref.isoformat()}


class Totals:
    """Candidate yearly totals built from SQL aggregates (fast even with every partner row)."""

    def __init__(self, ctx: Ctx, *, flows: Iterable[str] = FLOWS, reporters: Iterable[str] | None = None,
                 years: Iterable[int] | None = None, source_ids: Iterable[int] | None = None):
        self.ctx = ctx
        where = base_where(ctx.db) + [T.flow.in_(list(flows)), T.frequency.in_(TOTAL_FREQS), _partner_filter()]
        if reporters is not None:
            where.append(T.reporter_iso3.in_(list(reporters)))
        if years is not None:
            where.append(_year_col().in_(list(years)))
        if source_ids is not None:
            where.append(T.source_id.in_(list(source_ids)))
        q = (
            select(T.reporter_iso3.label("reporter"), T.flow.label("flow"), _year_col().label("year"),
                   T.source_id.label("sid"), T.frequency.label("freq"), _is_world().label("w"),
                   func.count(distinct(T.partner_iso3)).label("partners"), *_agg_columns())
            .where(*where)
            .group_by(T.reporter_iso3, T.flow, _year_col(), T.source_id, T.frequency, _is_world())
        )
        self.by_key: dict[tuple[str, str, int], list[Candidate]] = defaultdict(list)
        cands: dict[tuple, Candidate] = {}
        for r in ctx.db.execute(q):
            k = (r.reporter, r.flow, int(r.year), r.sid, r.freq)
            c = cands.get(k)
            if c is None:
                c = cands[k] = Candidate(r.reporter, r.flow, int(r.year), r.sid, r.freq)
                self.by_key[(r.reporter, r.flow, int(r.year))].append(c)
            agg = Agg.from_row(r)
            if r.w:
                c.world = agg
            else:
                c.parts = agg
        for lst in self.by_key.values():
            lst.sort(key=ctx.rank_key, reverse=True)

    def candidates(self, reporter: str, flow: str, year: int) -> list[Candidate]:
        return self.by_key.get((reporter, flow, year), [])

    def best(self, reporter: str, flow: str, year: int, *, complete_only: bool = True,
             source_id: int | None = None) -> Candidate | None:
        for c in self.candidates(reporter, flow, year):
            if source_id is not None and c.source_id != source_id:
                continue
            if complete_only and not c.complete:
                continue
            return c
        return None

    def same_basis(self, c: Candidate, year: int) -> Candidate | None:
        """The candidate of another year from the same source and frequency (for y/y)."""
        return next((x for x in self.candidates(c.reporter, c.flow, year)
                     if x.source_id == c.source_id and x.freq == c.freq), None)

    def years(self, flow: str | None = None) -> list[int]:
        return sorted({y for (_, f, y) in self.by_key if flow is None or f == flow})

    def reporters(self, flow: str | None = None, year: int | None = None) -> list[str]:
        return sorted({r for (r, f, y) in self.by_key
                       if (flow is None or f == flow) and (year is None or y == year)})

    def complete_reporters(self, flow: str, year: int) -> set[str]:
        return {r for (r, f, y), cs in self.by_key.items()
                if f == flow and y == year and self.ctx.is_country(r) and any(c.complete for c in cs)}

    def default_year(self, flow: str) -> int | None:
        """Latest year whose complete-reporter coverage is not obviously partial."""
        years = [y for y in self.years(flow) if self.complete_reporters(flow, y)]
        for y in reversed(years):
            prev = len(self.complete_reporters(flow, y - 1))
            if not prev or len(self.complete_reporters(flow, y)) >= PARTIAL_COVERAGE * prev:
                return y
        return years[-1] if years else None

    def latest_complete(self, reporter: str, flow: str) -> Candidate | None:
        for y in sorted({y for (r, f, y) in self.by_key if r == reporter and f == flow}, reverse=True):
            c = self.best(reporter, flow, y)
            if c is not None:
                return c
        return None


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def pct_change(curr: float | None, prev: float | None) -> float | None:
    if curr is None or prev is None or prev == 0:
        return None
    return round((curr - prev) / prev * 100, 2)


def _r(v: float | None, n: int = 2) -> float | None:
    return None if v is None else round(v, n)


def provenance(ctx: Ctx, sid: int, agg: Agg, freq: str, period_label: str | None = None) -> dict:
    src = ctx.source(sid)
    return {
        "source": ctx.brief(sid),
        "source_url": agg.source_url,
        "published_at": iso(agg.published_at),
        "collected_at": iso(agg.collected_at),
        "period_label": period_label or agg.label,
        "period_start": iso(agg.start),
        "period_end": iso(agg.end),
        "frequency": freq,
        "data_status": agg.data_status,
        "reliability": src.reliability if src else None,
        "is_demo": agg.is_demo,
    }


def figures(agg: Agg) -> dict:
    return {
        "net_weight_kg": _r(agg.kg, 1),
        "usd_value": _r(agg.usd_total, 2),
        "value": _r(agg.original_value, 2),
        "currency": agg.currency,
        "value_basis": agg.value_basis,
        "unit_value_usd_per_kg": agg.unit_value,
        "fx_missing": agg.fx_missing,
    }


def candidate_total(ctx: Ctx, c: Candidate, totals: Totals | None = None) -> dict:
    """A reporter's total for one year with its basis flags, provenance and y/y change."""
    agg = c.total
    out = {
        "iso3": c.reporter, **ctx.names(c.reporter),
        **figures(agg),
        "summed_from_partners": c.summed_from_partners,
        "summed_from_months": c.summed_from_months,
        "partners_count": c.partners_count if c.summed_from_partners else None,
        "months_count": c.periods if c.freq == "M" else None,
        "complete": c.complete,
        **provenance(ctx, c.source_id, agg, c.freq, period_label=str(c.year)),
        "year": c.year,
        "prev": None, "yoy_volume_pct": None, "yoy_value_pct": None,
    }
    if totals is not None:
        p = totals.same_basis(c, c.year - 1)
        if p is not None and p.complete:
            pa = p.total
            out["prev"] = {"year": p.year, "net_weight_kg": _r(pa.kg, 1), "usd_value": _r(pa.usd_total, 2),
                           "summed_from_partners": p.summed_from_partners, "is_demo": pa.is_demo}
            out["yoy_volume_pct"] = pct_change(agg.kg, pa.kg)
            out["yoy_value_pct"] = pct_change(agg.usd_total, pa.usd_total)
    return out


def _sort_key(metric: str):
    def key(row: dict):
        v = row["net_weight_kg"] if metric == "volume" else row["usd_value"]
        alt = row["usd_value"] if metric == "volume" else row["net_weight_kg"]
        return (v is None, -(v or 0), -(alt or 0))
    return key


def sources_used(ctx: Ctx, rows: Iterable[dict]) -> list[dict]:
    """Distinct sources behind a list of serialised rows, each with its freshness."""
    seen: dict[str, dict] = {}
    for r in rows:
        s = r.get("source")
        if not s:
            continue
        ref = r.get("published_at") or r.get("period_end")
        ref_d = date.fromisoformat(ref[:10]) if ref else None
        cur = seen.get(s["key"])
        if cur is None or (ref_d and (cur["_ref"] is None or ref_d > cur["_ref"])):
            sid = ctx.source_id(s["key"])
            seen[s["key"]] = {**s, "_ref": ref_d, "_freq": r.get("frequency"), "_sid": sid}
    out = []
    for s in seen.values():
        f = ctx.freshness_for(s["_sid"], s["_ref"], s["_freq"]) if s["_sid"] else None
        src = ctx.source(s["_sid"])
        out.append({k: v for k, v in s.items() if not k.startswith("_")} | {
            "freshness": f, "latest_published_at": iso(s["_ref"]),
            "expected_update": src.expected_update if src else None,
        })
    return out


def _flow(value: str | None, *, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    v = (value or "").lower()
    if v not in FLOWS:
        raise HTTPException(422, "flow must be 'import' or 'export'")
    return v


def _metric(value: str | None) -> str:
    v = (value or "volume").lower()
    if v not in ("volume", "value"):
        raise HTTPException(422, "metric must be 'volume' or 'value'")
    return v


def _iso(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    v = value.strip().upper()
    if not v.replace("_", "").isalnum() or not 2 <= len(v) <= 8:
        raise HTTPException(422, f"invalid {name} code")
    return v


# ---------------------------------------------------------------------------
# GET /trade/facets
# ---------------------------------------------------------------------------


@router.get("/facets")
def trade_facets(db: Session = Depends(get_db)):
    ctx = Ctx(db)
    where = base_where(db)
    totals = Totals(ctx)

    # Reporters with what each one declares
    rep: dict[str, dict] = {}
    rq = (select(T.reporter_iso3, T.flow, T.frequency, T.source_id, func.min(T.period_start), func.max(T.period_start),
                 func.count()).where(*where).group_by(T.reporter_iso3, T.flow, T.frequency, T.source_id))
    for reporter, flow, freq, sid, first, last, n in db.execute(rq):
        d = rep.setdefault(reporter, {"iso3": reporter, **ctx.names(reporter), "is_aggregate": reporter in AGGREGATE_REPORTERS,
                                      "flows": {}, "sources": set(), "rows": 0, "first_period": None, "last_period": None})
        fd = d["flows"].setdefault(flow, {"frequencies": set(), "years": set(), "rows": 0})
        fd["frequencies"].add(freq)
        fd["rows"] += n
        d["sources"].add(ctx.source(sid).key if ctx.source(sid) else str(sid))
        d["rows"] += n
        d["first_period"] = min(filter(None, [d["first_period"], first]))
        d["last_period"] = max(filter(None, [d["last_period"], last]))
    for (reporter, flow, year) in totals.by_key:
        if reporter in rep and flow in rep[reporter]["flows"]:
            rep[reporter]["flows"][flow]["years"].add(year)
    reporters = []
    for d in sorted(rep.values(), key=lambda x: -x["rows"]):
        reporters.append({
            **d, "sources": sorted(d["sources"]),
            "first_period": iso(d["first_period"]), "last_period": iso(d["last_period"]),
            "flows": {f: {"frequencies": sorted(v["frequencies"]), "years": sorted(v["years"]), "rows": v["rows"]}
                      for f, v in d["flows"].items()},
        })

    # Partners (countries only; World and groups are not partners in a breakdown)
    pq = (select(T.partner_iso3, T.flow, func.count(distinct(T.reporter_iso3)), func.count())
          .where(*where, T.partner_iso3.not_in(sorted(PSEUDO_AREAS))).group_by(T.partner_iso3, T.flow))
    pt: dict[str, dict] = {}
    for partner, flow, nrep, n in db.execute(pq):
        d = pt.setdefault(partner, {"iso3": partner, **ctx.names(partner), "known": ctx.is_country(partner),
                                    "rows": 0, "reported_by": {}})
        d["rows"] += n
        d["reported_by"][flow] = nrep
    partners = sorted(pt.values(), key=lambda x: -x["rows"])

    # Years and months
    years = []
    for y in totals.years():
        entry = {"year": y}
        for f in FLOWS:
            entry[f"{f}_reporters"] = len({r for r in totals.reporters(f, y) if ctx.is_country(r)})
            entry[f"{f}_complete"] = len(totals.complete_reporters(f, y))
        years.append(entry)
    mq = (select(T.period_label, T.flow, func.count(distinct(T.reporter_iso3)))
          .where(*where, T.frequency == "M").group_by(T.period_label, T.flow))
    months: dict[str, dict] = {}
    for label, flow, nrep in db.execute(mq):
        months.setdefault(label, {"period": label, "import_reporters": 0, "export_reporters": 0})[f"{flow}_reporters"] = nrep
    month_list = [months[k] for k in sorted(months, reverse=True)]

    # Sources
    sq = (select(T.source_id, T.frequency, func.min(T.period_start), func.max(T.period_start), func.max(T.period_label),
                 func.max(T.published_at), func.max(T.collected_at), func.count(), func.max(case((T.is_demo.is_(True), 1), else_=0)))
          .where(*where).group_by(T.source_id, T.frequency))
    src: dict[int, dict] = {}
    for sid, freq, first, last, last_label, pub, col, n, demo in db.execute(sq):
        s = ctx.source(sid)
        d = src.setdefault(sid, {**(source_brief(s) or {"key": str(sid)}), "frequencies": [], "rows": 0,
                                 "first_period": None, "last_period": None, "latest_period_label": None,
                                 "latest_published_at": None, "collected_at": None, "is_demo": False,
                                 "expected_update": s.expected_update if s else None, "_freq": freq})
        d["frequencies"].append(freq)
        d["rows"] += n
        d["is_demo"] = d["is_demo"] or bool(demo)
        if d["last_period"] is None or last > d["last_period"]:
            d["last_period"], d["latest_period_label"], d["_freq"] = last, last_label, freq
        d["first_period"] = min(filter(None, [d["first_period"], first]))
        d["latest_published_at"] = max(filter(None, [d["latest_published_at"], pub]), default=None)
        d["collected_at"] = max(filter(None, [d["collected_at"], col]), default=None)
    sources = []
    for sid, d in src.items():
        ref = d["latest_published_at"] or d["last_period"]
        sources.append({k: iso(v) for k, v in d.items() if not k.startswith("_")}
                       | {"frequencies": sorted(d["frequencies"]), "freshness": ctx.freshness_for(sid, ref, d["_freq"])})

    total_rows = sum(d["rows"] for d in rep.values())
    return {
        "total_rows": total_rows,
        "reporters": reporters,
        "partners": partners,
        "years": years,
        "months": month_list,
        "default_year": {f: totals.default_year(f) for f in FLOWS},
        "sources": sorted(sources, key=lambda s: -s["rows"]),
        "providers": ctx.providers(),
    }


# ---------------------------------------------------------------------------
# GET /trade/leaders
# ---------------------------------------------------------------------------


@router.get("/leaders")
def trade_leaders(
    flow: str = Query(..., description="export | import"),
    year: int | None = Query(None, description="Calendar year; default = latest year with broad coverage"),
    metric: str = Query("volume", description="volume | value (sort order)"),
    basis: str = Query("declared", description="declared (each country's own declarations) | mirror "
                                               "(exports rebuilt from what importers declare; flow=export only)"),
    limit: int = Query(50, ge=1, le=300),
    db: Session = Depends(get_db),
):
    flow = _flow(flow)
    metric = _metric(metric)
    if basis not in ("declared", "mirror"):
        raise HTTPException(422, "basis must be 'declared' or 'mirror'")
    if basis == "mirror" and flow != "export":
        raise HTTPException(422, "basis=mirror is only defined for flow=export")
    ctx = Ctx(db)
    src_flow = "import" if basis == "mirror" else flow
    totals = Totals(ctx, flows=[src_flow])
    years = [y for y in totals.years(src_flow) if totals.complete_reporters(src_flow, y)]
    default_year = totals.default_year(src_flow)
    year = year or default_year
    out = {
        "flow": flow, "basis": basis, "metric": metric, "year": year, "default_year": default_year,
        "available_years": years, "rows": [], "incomplete": [], "count": 0, "sources": [],
        "mixed_sources": False, "providers": ctx.providers(),
    }
    if year is None:
        return out

    if basis == "mirror":
        out.update(_mirror_leaders(ctx, year, metric, limit))
        return out

    totals_y = Totals(ctx, flows=[flow], years=[year - 1, year])
    rows, incomplete = [], []
    for reporter in totals_y.reporters(flow, year):
        if not ctx.is_country(reporter):
            continue
        best = totals_y.best(reporter, flow, year)
        if best is None:
            partial = totals_y.best(reporter, flow, year, complete_only=False)
            if partial is not None:
                agg = partial.total
                incomplete.append({"iso3": reporter, **ctx.names(reporter), "months_count": partial.periods,
                                   "net_weight_kg": _r(agg.kg, 1), "source": ctx.brief(partial.source_id),
                                   "is_demo": agg.is_demo, "period_end": iso(agg.end)})
            continue
        row = candidate_total(ctx, best, totals_y)
        row["link"] = f"/paesi/{reporter}"
        rows.append(row)
    rows.sort(key=_sort_key(metric))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    out.update(
        rows=rows[:limit], count=len(rows), incomplete=sorted(incomplete, key=lambda r: r["iso3"]),
        sources=sources_used(ctx, rows),
        mixed_sources=len({r["source"]["key"] for r in rows if r.get("source")}) > 1,
        summed_from_partners=sum(r["summed_from_partners"] for r in rows),
        summed_from_months=sum(r["summed_from_months"] for r in rows),
    )
    return out


def _mirror_leaders(ctx: Ctx, year: int, metric: str, limit: int) -> dict:
    """Exporters ranked by what importing countries declare as imports from them.

    Each importer contributes its best complete declaration of the year (one source each). The
    y/y change is like-for-like: only importers that declared both years count.
    """
    totals = Totals(ctx, flows=["import"], years=[year - 1, year])
    chosen: dict[str, Candidate] = {}
    for reporter in totals.reporters("import", year):
        if not ctx.is_country(reporter):
            continue
        c = totals.best(reporter, "import", year)
        if c is not None and c.parts is not None:
            chosen[reporter] = c
    if not chosen:
        return {"rows": [], "count": 0, "reporters": [], "sources": []}
    cur = _partner_aggs(ctx, "import", year, chosen)
    prev_chosen = {r: p for r, c in chosen.items()
                   if (p := totals.same_basis(c, year - 1)) is not None and p.complete and p.parts is not None}
    prev = _partner_aggs(ctx, "import", year - 1, prev_chosen) if prev_chosen else {}

    by_partner: dict[str, dict] = {}
    for reporter, parts in cur.items():
        c = chosen[reporter]
        for partner, agg in parts.items():
            if partner == reporter or not ctx.is_country(partner):
                continue
            d = by_partner.setdefault(partner, {"agg": None, "reporters": [], "lfl_cur": 0.0, "lfl_prev": 0.0,
                                                "lfl_n": 0, "sources": set(), "freqs": set()})
            d["agg"] = agg if d["agg"] is None else d["agg"].merge(agg)
            d["reporters"].append((reporter, agg.kg or 0.0))
            d["sources"].add(c.source_id)
            d["freqs"].add(c.freq)
            pa = prev.get(reporter, {}).get(partner)
            if pa is not None and pa.kg is not None and agg.kg is not None:
                d["lfl_cur"] += agg.kg
                d["lfl_prev"] += pa.kg
                d["lfl_n"] += 1
    rows = []
    for partner, d in by_partner.items():
        agg: Agg = d["agg"]
        sids = sorted(d["sources"])
        prov = provenance(ctx, sids[0], agg, "A" if d["freqs"] == {"A"} else "M", period_label=str(year))
        if len(sids) > 1:
            prov["source"] = None
        rows.append({
            "iso3": partner, **ctx.names(partner), **figures(agg), **prov,
            "sources_list": [ctx.brief(s) for s in sids],
            "reporters_count": len(d["reporters"]),
            "reporters": [r for r, _ in sorted(d["reporters"], key=lambda x: -x[1])][:6],
            "yoy_volume_pct": pct_change(d["lfl_cur"], d["lfl_prev"]) if d["lfl_n"] else None,
            "yoy_like_for_like_reporters": d["lfl_n"],
            "summed_from_partners": False, "summed_from_months": d["freqs"] != {"A"},
            "year": year, "link": f"/paesi/{partner}",
        })
    rows.sort(key=_sort_key(metric))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    rep_rows = [{"iso3": r, **ctx.names(r), "source": ctx.brief(c.source_id), "frequency": c.freq,
                 "published_at": iso(c.total.published_at), "period_end": iso(c.total.end)}
                for r, c in sorted(chosen.items())]
    src_rows = [{"source": ctx.brief(c.source_id), "published_at": iso(c.total.published_at),
                 "period_end": iso(c.total.end), "frequency": c.freq} for c in chosen.values()]
    return {"rows": rows[:limit], "count": len(rows), "reporters": rep_rows, "sources": sources_used(ctx, src_rows),
            "mixed_sources": len({c.source_id for c in chosen.values()}) > 1}


def _partner_aggs(ctx: Ctx, flow: str, year: int, chosen: dict[str, Candidate]) -> dict[str, dict[str, Agg]]:
    """Per reporter: partner -> aggregate, restricted to each reporter's chosen source/frequency."""
    if not chosen:
        return {}
    q = (
        select(T.reporter_iso3.label("reporter"), T.source_id.label("sid"), T.frequency.label("freq"),
               T.partner_iso3.label("partner"), *_agg_columns())
        .where(*base_where(ctx.db), T.flow == flow, _year_col() == year, T.reporter_iso3.in_(list(chosen)),
               T.partner_iso3.not_in(sorted(PSEUDO_AREAS)), T.frequency.in_(TOTAL_FREQS))
        .group_by(T.reporter_iso3, T.source_id, T.frequency, T.partner_iso3)
    )
    out: dict[str, dict[str, Agg]] = defaultdict(dict)
    for r in ctx.db.execute(q):
        c = chosen.get(r.reporter)
        if c is None or c.source_id != r.sid or c.freq != r.freq:
            continue
        out[r.reporter][r.partner] = Agg.from_row(r)
    return out


# ---------------------------------------------------------------------------
# GET /trade/flows
# ---------------------------------------------------------------------------


def partner_breakdown(ctx: Ctx, reporter: str, flow: str, year: int | None = None, *, top: int = 10,
                      metric: str = "volume", source_key: str | None = None) -> dict:
    """Top partners of one reporter for one flow and year, with shares, unit values and y/y."""
    totals = Totals(ctx, flows=[flow], reporters=[reporter])
    years_all = totals.years(flow)
    complete_years = [y for y in years_all if totals.best(reporter, flow, y) is not None]
    default_year = complete_years[-1] if complete_years else (years_all[-1] if years_all else None)
    year = year or default_year
    sid = ctx.source_id(source_key) if source_key else None
    if source_key and sid is None:
        raise HTTPException(422, f"unknown source '{source_key}'")
    out: dict = {
        "reporter": reporter, **ctx.names(reporter), "flow": flow, "year": year, "metric": metric,
        "default_year": default_year, "available_years": years_all, "complete_years": complete_years,
        "available": False, "rows": [], "others": None, "unallocated": None, "total": None,
        "alternatives": [], "providers": ctx.providers(),
    }
    if year is None:
        return out
    cands = totals.candidates(reporter, flow, year)
    out["alternatives"] = [
        {"source": ctx.brief(c.source_id), "frequency": c.freq, "months_count": c.periods if c.freq == "M" else None,
         "complete": c.complete, "has_partners": c.parts is not None}
        for c in cands
    ]
    pick = next((c for c in cands if c.parts is not None and (sid is None or c.source_id == sid) and c.complete), None) \
        or next((c for c in cands if c.parts is not None and (sid is None or c.source_id == sid)), None)
    if pick is None:
        # Only a World total (no breakdown) — the total is still worth showing.
        only = next((c for c in cands if sid is None or c.source_id == sid), None)
        if only is not None:
            out["total"] = candidate_total(ctx, only, totals)
            out.update(provenance(ctx, only.source_id, only.total, only.freq, period_label=str(year)))
        return out

    parts = _partner_aggs(ctx, flow, year, {reporter: pick}).get(reporter, {})
    prev_c = totals.same_basis(pick, year - 1)
    prev_parts = _partner_aggs(ctx, flow, year - 1, {reporter: prev_c}).get(reporter, {}) \
        if prev_c is not None and prev_c.complete else {}

    part_sum = pick.parts
    denom = pick.world if pick.uses_world else part_sum
    share_basis = "world_total" if pick.uses_world else "partner_sum"

    def share(v: float | None, d: float | None) -> float | None:
        return round(v / d * 100, 2) if v is not None and d else None

    rows = []
    for partner, agg in parts.items():
        pa = prev_parts.get(partner)
        rows.append({
            "iso3": partner, **ctx.names(partner), "known": ctx.is_country(partner) or partner == reporter,
            **figures(agg),
            "share_volume_pct": share(agg.kg, denom.kg if denom else None),
            "share_value_pct": share(agg.usd_total, denom.usd_total if denom else None),
            "prev_net_weight_kg": _r(pa.kg, 1) if pa else None,
            "yoy_volume_pct": pct_change(agg.kg, pa.kg) if pa else None,
            "months_count": agg.periods if pick.freq == "M" else None,
            **provenance(ctx, pick.source_id, agg, pick.freq, period_label=str(year)),
            "link": f"/paesi/{partner}" if ctx.is_country(partner) else None,
        })
    rows.sort(key=_sort_key(metric))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    head, tail = rows[:top], rows[top:]
    if tail:
        o_kg = sum(r["net_weight_kg"] or 0 for r in tail) if any(r["net_weight_kg"] is not None for r in tail) else None
        o_usd = None if any(r["fx_missing"] for r in tail) else sum(r["usd_value"] or 0 for r in tail)
        out["others"] = {"count": len(tail), "net_weight_kg": _r(o_kg, 1), "usd_value": _r(o_usd, 2),
                         "share_volume_pct": share(o_kg, denom.kg if denom else None),
                         "share_value_pct": share(o_usd, denom.usd_total if denom else None)}
    if pick.uses_world and pick.world.kg and part_sum.kg is not None:
        gap = pick.world.kg - part_sum.kg
        if gap > UNALLOCATED_MIN_SHARE * pick.world.kg:
            gap_usd = (pick.world.usd_total - part_sum.usd_total) if pick.world.usd_total is not None and part_sum.usd_total is not None else None
            out["unallocated"] = {"net_weight_kg": _r(gap, 1), "usd_value": _r(gap_usd, 2),
                                  "share_volume_pct": share(gap, pick.world.kg)}
    total = candidate_total(ctx, pick, totals)
    out.update(
        available=bool(rows), rows=head, partners_count=len(rows), total=total, share_basis=share_basis,
        frequency=pick.freq, months_count=pick.periods if pick.freq == "M" else None, complete=pick.complete,
        summed_from_months=pick.summed_from_months, source_key=ctx.source(pick.source_id).key if ctx.source(pick.source_id) else None,
        **provenance(ctx, pick.source_id, pick.total, pick.freq, period_label=str(year)),
        freshness=ctx.freshness_for(pick.source_id, pick.total.published_at or pick.total.end, pick.freq),
    )
    return out


@router.get("/flows")
def trade_flows(
    reporter: str = Query(..., description="ISO3 of the declaring country (or EU27)"),
    flow: str = Query("import"),
    year: int | None = Query(None),
    top: int = Query(10, ge=1, le=50),
    metric: str = Query("volume"),
    source: str | None = Query(None, description="Force one source key"),
    db: Session = Depends(get_db),
):
    ctx = Ctx(db)
    return partner_breakdown(ctx, _iso(reporter, "reporter"), _flow(flow), year, top=top, metric=_metric(metric),
                             source_key=source)


# ---------------------------------------------------------------------------
# GET /trade/series
# ---------------------------------------------------------------------------


def build_series(ctx: Ctx, reporter: str, flow: str, partner: str = "WLD", freq: str = "A",
                 years_back: int | None = None) -> dict:
    """One series per source. Partner 'WLD' = the reporter's total (World row, or sum of partners)."""
    where = base_where(ctx.db) + [T.reporter_iso3 == reporter, T.flow == flow, T.frequency.in_(TOTAL_FREQS)]
    total_mode = partner == "WLD"
    if total_mode:
        where.append(_partner_filter())
    else:
        where.append(T.partner_iso3 == partner)
    if years_back:
        where.append(T.period_start >= date(ctx.today.year - years_back, 1, 1))
    q = (select(T.source_id.label("sid"), T.frequency.label("freq"), T.period_start.label("ps"), _is_world().label("w"),
                func.count(distinct(T.partner_iso3)).label("partners"), *_agg_columns())
         .where(*where).group_by(T.source_id, T.frequency, T.period_start, _is_world()))
    # (sid, freq, period_start) -> {"w": Agg, "p": Agg}
    cells: dict[tuple, dict[str, Agg]] = defaultdict(dict)
    for r in ctx.db.execute(q):
        cells[(r.sid, r.freq, r.ps)]["w" if r.w else "p"] = Agg.from_row(r)

    def pick(cell: dict[str, Agg]) -> tuple[Agg, bool, int]:
        if "w" in cell:
            return cell["w"], False, 0
        p = cell["p"]
        return p, total_mode, p.partners

    per_source: dict[int, dict[str, dict]] = defaultdict(lambda: {"A": {}, "M": {}})
    for (sid, f, ps), cell in cells.items():
        agg, summed, n_partners = pick(cell)
        per_source[sid][f][ps] = (agg, summed, n_partners)

    series, excluded = [], []
    for sid, by_freq in per_source.items():
        points = []
        if freq == "M":
            for ps in sorted(by_freq["M"]):
                agg, summed, n_p = by_freq["M"][ps]
                points.append(_point(ctx, sid, agg, "M", agg.label, summed, n_p, False, None))
        else:
            years = sorted({ps.year for ps in by_freq["A"]} | {ps.year for ps in by_freq["M"]})
            for y in years:
                a = next(((agg, s, n) for ps, (agg, s, n) in by_freq["A"].items() if ps.year == y), None)
                if a is not None:
                    agg, summed, n_p = a
                    points.append(_point(ctx, sid, agg, "A", str(y), summed, n_p, False, None))
                    continue
                months = [(ps, v) for ps, v in by_freq["M"].items() if ps.year == y]
                if len(months) >= 12:
                    agg = months[0][1][0]
                    for _, (m_agg, _, _) in months[1:]:
                        agg = agg.merge(m_agg)
                    summed = any(s for _, (_, s, _) in months)
                    n_p = max(n for _, (_, _, n) in months)
                    points.append(_point(ctx, sid, agg, "A", str(y), summed, n_p, True, len(months)))
                elif months:
                    last = max(ps for ps, _ in months)
                    excluded.append({"source": ctx.brief(sid), "period_label": str(y), "months_count": len(months),
                                     "last_month": f"{last.year}-{last.month:02d}"})
        if not points:
            continue
        src = ctx.source(sid)
        newest = points[-1]
        ref = newest["published_at"] or newest["period_end"]
        series.append({
            "source": ctx.brief(sid), "frequency": freq, "points": points,
            "is_demo": any(p["is_demo"] for p in points),
            "freshness": ctx.freshness_for(sid, date.fromisoformat(ref[:10]) if ref else None, freq),
            "expected_update": src.expected_update if src else None,
        })
    series.sort(key=lambda s: (-len(s["points"]), s["source"]["key"] if s["source"] else ""))

    # Disagreement between sources on the same period is reported, never resolved.
    discrepancies = []
    by_period: dict[str, list[tuple[dict, dict]]] = defaultdict(list)
    for s in series:
        for p in s["points"]:
            by_period[p["period_label"]].append((s["source"], p))
    for label, items in sorted(by_period.items()):
        vals = [(src, p["net_weight_kg"]) for src, p in items if p["net_weight_kg"]]
        if len(vals) < 2:
            continue
        lo, hi = min(v for _, v in vals), max(v for _, v in vals)
        if lo > 0 and (hi - lo) / lo > DISCREPANCY_THRESHOLD:
            discrepancies.append({"period_label": label, "diff_pct": round((hi - lo) / lo * 100, 1),
                                  "values": [{"source": src, "net_weight_kg": v} for src, v in vals]})
    return {
        "reporter": reporter, "partner": partner, "flow": flow, "freq": freq,
        "reporter_names": ctx.names(reporter), "partner_names": ctx.names(partner),
        "available": bool(series), "series": series, "excluded_partial": excluded,
        "discrepancies": discrepancies, "providers": ctx.providers(),
    }


def _point(ctx: Ctx, sid: int, agg: Agg, freq: str, label: str | None, summed_partners: bool, n_partners: int,
           summed_months: bool, months: int | None) -> dict:
    return {
        "period_label": label, **figures(agg),
        "summed_from_partners": summed_partners, "partners_count": n_partners if summed_partners else None,
        "summed_from_months": summed_months, "months_count": months,
        **provenance(ctx, sid, agg, freq, period_label=label),
    }


@router.get("/series")
def trade_series(
    reporter: str = Query(...),
    partner: str = Query("WLD", description="Partner ISO3; WLD = the reporter's total"),
    flow: str = Query("import"),
    freq: str = Query("A", description="A (annual) | M (monthly)"),
    db: Session = Depends(get_db),
):
    f = (freq or "A").upper()
    if f not in TOTAL_FREQS:
        raise HTTPException(422, "freq must be A or M")
    ctx = Ctx(db)
    return build_series(ctx, _iso(reporter, "reporter"), _flow(flow), _iso(partner, "partner") or "WLD", f)


# ---------------------------------------------------------------------------
# Helpers used by the countries API
# ---------------------------------------------------------------------------


def latest_totals(ctx: Ctx, flow: str, reporters: Iterable[str] | None = None, totals: Totals | None = None) -> dict[str, dict]:
    """reporter -> latest complete yearly total (serialised), one source each."""
    totals = totals or Totals(ctx, flows=[flow], reporters=reporters)
    out = {}
    for reporter in totals.reporters(flow):
        if not ctx.is_country(reporter):
            continue
        c = totals.latest_complete(reporter, flow)
        if c is not None:
            out[reporter] = candidate_total(ctx, c, totals)
    return out


def mirror_declarations(ctx: Ctx, iso3: str, flow: str, limit: int = 10) -> dict:
    """What OTHER countries declare about trade with `iso3` (mirror view), latest complete year
    per declaring country. flow='export' -> importers declaring imports from iso3."""
    declared_flow = "import" if flow == "export" else "export"
    q = (select(T.reporter_iso3.label("reporter"), T.source_id.label("sid"), T.frequency.label("freq"),
                _year_col().label("year"), *_agg_columns())
         .where(*base_where(ctx.db), T.flow == declared_flow, T.partner_iso3 == iso3, T.frequency.in_(TOTAL_FREQS),
                T.reporter_iso3 != iso3)
         .group_by(T.reporter_iso3, T.source_id, T.frequency, _year_col()))
    by_rep: dict[str, list[tuple[int, str, int, Agg]]] = defaultdict(list)
    for r in ctx.db.execute(q):
        if not ctx.is_country(r.reporter):
            continue
        by_rep[r.reporter].append((int(r.year), r.freq, r.sid, Agg.from_row(r)))
    rows = []
    for reporter, items in by_rep.items():
        def key(it):
            y, f, sid, agg = it
            complete = f == "A" or agg.periods >= 12
            src = ctx.source(sid)
            rel = RELIABILITY_ORDER.index(src.reliability) if src and src.reliability in RELIABILITY_ORDER else 99
            return (complete, y, f == "A", -rel)
        y, f, sid, agg = max(items, key=key)
        complete = f == "A" or agg.periods >= 12
        rows.append({
            "iso3": reporter, **ctx.names(reporter), **figures(agg), "year": y, "complete": complete,
            "months_count": agg.periods if f == "M" else None, "summed_from_months": f == "M",
            **provenance(ctx, sid, agg, f, period_label=str(y)), "link": f"/paesi/{reporter}",
        })
    rows.sort(key=lambda r: (not r["complete"], -(r["net_weight_kg"] or 0)))
    return {"declared_flow": declared_flow, "rows": rows[:limit], "count": len(rows)}


__all__ = [
    "router", "Ctx", "Totals", "Candidate", "Agg", "candidate_total", "partner_breakdown", "build_series",
    "latest_totals", "mirror_declarations", "sources_used", "item_freshness", "PSEUDO_AREAS",
]
