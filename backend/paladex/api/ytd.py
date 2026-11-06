"""Year to date ("2026 finora"): the running year's monthly customs figures against THE SAME months
of the year before, from ONE source.

The annual figures lag (the last complete year is 2025, FAOSTAT's 2024), while monthly official data
run to the last few months (Eurostat, HMRC, US Census, INDEC, Comex Stat, Ukraine's customs...). The
pages lead with this fresher period; the rules keep it comparable:

* **Monthly rows only** (frequency M). Weekly surveillance data (TAXUD) are provisional and cover
  extra-EU imports only, as for the annual totals (trade.TOTAL_FREQS).
* **A month counts only when its total is published.** For a source that publishes the reporter's
  total (World row; EXTRA_EU for the EU aggregates) a month without it is a partial release and is
  left out, and said so: Eurostat's newest month often holds a handful of partners and no total
  (Italy, August 2026: 7 origins, 182 t against about 1,000 t in a normal month). A source that never
  publishes a total (Comex Stat, Chile's Aduana) is summed over its partners in every month of both
  years, and flagged.
* **No gaps.** The period runs from January to the last month M such that every month Jan..M counts.
* **Same months, same source.** The change is computed only when the previous year has every month
  Jan..M from the same source on the same basis; otherwise the figure is shown without a change.
  Two sources are never compared or added.
* **Fresh only.** The last month must be at most `MAX_LAG_MONTHS` before today, and a year with all
  twelve months is a full year (the annual figures show it): neither is presented as "so far".
* **One source per figure**: among the sources of a reporter, a comparable figure first, then the
  newest month, then the reporter's own official statistics, reliability and the usual preference.

Every figure carries its provenance (source, months, publication, status) like the annual totals.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from dateutil.relativedelta import relativedelta
from sqlalchemy import distinct, func, select

from .common import iso
from .memo import cached
from .trade import (
    AGGREGATE_REPORTERS,
    RELIABILITY_ORDER,
    SOURCE_PREFERENCE,
    Agg,
    Ctx,
    T,
    _agg_columns,
    _is_world,
    _partner_filter,
    base_where,
    pct_change,
    provenance,
    sources_used,
)

# The slowest monthly releases we hold are UN Comtrade's (2-4 months after the month) and INEGI's
# (about six weeks, revised monthly): a last month older than this is not "the year so far" any more.
MAX_LAG_MONTHS = 6
MIRROR_ROWS = 8


def _r(v: float | None, n: int = 2) -> float | None:
    return None if v is None else round(v, n)


def _window_start(today: date) -> date:
    """First month read: January of the year before last (covers year Y and Y-1 for Y = this year
    and, early in a year, last year)."""
    return date(today.year - 2, 1, 1)


def _min_last_month(today: date) -> date:
    return date(today.year, today.month, 1) - relativedelta(months=MAX_LAG_MONTHS)


# ---------------------------------------------------------------------------
# The computation (pure: months in, figure out)
# ---------------------------------------------------------------------------


@dataclass
class Months:
    """Monthly cells of ONE reporter x flow x source: month start -> {"w": total row, "p": partner sum}."""

    cells: dict[date, dict[str, Agg]] = field(default_factory=dict)

    def counted(self) -> tuple[dict[date, Agg], bool, dict[date, str]]:
        """(month -> figure counted, summed from partners, month -> why it is left out)."""
        has_total = any("w" in c for c in self.cells.values())
        counted: dict[date, Agg] = {}
        excluded: dict[date, str] = {}
        for ps, c in self.cells.items():
            if has_total:
                if "w" in c:
                    counted[ps] = c["w"]
                else:
                    excluded[ps] = "no_total"
            elif "p" in c:
                counted[ps] = c["p"]
        return counted, not has_total, excluded


@dataclass
class Ytd:
    year: int
    month_to: int
    current: Agg
    previous: Agg | None
    cur_months: list[Agg]
    prev_months: list[Agg]
    summed_from_partners: bool
    excluded: list[dict]
    prev_months_available: list[int]

    @property
    def comparable(self) -> bool:
        return self.previous is not None


def _strict_sum(aggs: list[Agg], attr: str) -> float | None:
    """Sum over the months, or None when any month lacks the figure (a partial sum is never shown)."""
    vals = [getattr(a, attr) for a in aggs]
    return None if not vals or any(v is None for v in vals) else sum(vals)


def _merge(aggs: list[Agg]) -> Agg:
    out = aggs[0]
    for a in aggs[1:]:
        out = out.merge(a)
    return out


def compute(counted: dict[date, Agg], today: date, *, summed_from_partners: bool = False,
            excluded: dict[date, str] | None = None) -> Ytd | None:
    """Year-to-date figure from the months that count (see the module rules), or None."""
    by_year: dict[int, dict[int, Agg]] = defaultdict(dict)
    for ps, agg in counted.items():
        by_year[ps.year][ps.month] = agg
    if not by_year:
        return None
    year = max(by_year)
    cur = by_year[year]
    if len(cur) >= 12:
        return None          # a full year: the annual figures are the freshest
    m = 0
    while m + 1 in cur:
        m += 1
    if m == 0 or date(year, m, 1) < _min_last_month(today):
        return None          # no January, or too old to be "the year so far"
    prev = by_year.get(year - 1, {})
    comparable = all(k in prev for k in range(1, m + 1))
    cur_months = [cur[k] for k in range(1, m + 1)]
    prev_months = [prev[k] for k in range(1, m + 1)] if comparable else []
    out_excluded = [{"month": f"{ps.year}-{ps.month:02d}", "reason": why}
                    for ps, why in sorted((excluded or {}).items()) if ps.year == year and ps.month > m]
    out_excluded += [{"month": f"{year}-{k:02d}", "reason": "after_gap"} for k in sorted(cur) if k > m + 1]
    out_excluded.sort(key=lambda e: e["month"])
    return Ytd(year=year, month_to=m, current=_merge(cur_months), previous=_merge(prev_months) if comparable else None,
               cur_months=cur_months, prev_months=prev_months, summed_from_partners=summed_from_partners,
               excluded=out_excluded, prev_months_available=sorted(prev))


def _figures(aggs: list[Agg]) -> dict:
    kg = _strict_sum(aggs, "kg")
    usd = None if any(a.usd_total is None for a in aggs) else sum(a.usd_total for a in aggs)
    return {
        "net_weight_kg": _r(kg, 1),
        "usd_value": _r(usd, 2),
        "unit_value_usd_per_kg": round(usd / kg, 4) if kg and usd else None,
        "fx_missing": any(a.fx_missing for a in aggs),
    }


def _months_label(year: int, month_to: int) -> str:
    """'2026-01/2026-09' (one month: '2026-01')."""
    return f"{year}-01/{year}-{month_to:02d}" if month_to > 1 else f"{year}-01"


def serialize(ctx: Ctx, y: Ytd, sid: int) -> dict:
    cur = _figures(y.cur_months)
    prev = _figures(y.prev_months) if y.previous is not None else None
    ref = y.current.published_at or y.current.end
    previous = None
    if prev is not None and y.previous is not None:
        previous = {**prev, "year": y.year - 1, "period_label": _months_label(y.year - 1, y.month_to),
                    "data_status": y.previous.data_status, "published_at": iso(y.previous.published_at),
                    "is_demo": y.previous.is_demo}
    return {
        "year": y.year,
        "prev_year": y.year - 1,
        "month_from": 1,
        "month_to": y.month_to,
        "months_count": y.month_to,
        "is_current_year": y.year == ctx.today.year,
        **cur,
        "comparable": previous is not None,
        "previous": previous,
        # months of the previous year this source has (shown when the change cannot be computed)
        "prev_months_available": y.prev_months_available if y.previous is None else None,
        "change_volume_pct": pct_change(cur["net_weight_kg"], prev["net_weight_kg"]) if prev else None,
        "change_value_pct": pct_change(cur["usd_value"], prev["usd_value"]) if prev else None,
        "change_unit_value_pct": pct_change(cur["unit_value_usd_per_kg"], prev["unit_value_usd_per_kg"]) if prev else None,
        "summed_from_partners": y.summed_from_partners,
        "partners_count": y.current.partners if y.summed_from_partners else None,
        "excluded_months": y.excluded,
        **provenance(ctx, sid, y.current, "M", period_label=_months_label(y.year, y.month_to)),
        "is_demo": y.current.is_demo or bool(y.previous and y.previous.is_demo),
        "freshness": ctx.freshness_for(sid, ref, "M"),
    }


def _choice_key(ctx: Ctx, reporter: str, sid: int, y: Ytd) -> tuple:
    src = ctx.source(sid)
    national = bool(src and src.country_iso3 == reporter and src.reliability == "official")
    rel = RELIABILITY_ORDER.index(src.reliability) if src and src.reliability in RELIABILITY_ORDER else len(RELIABILITY_ORDER)
    pref = SOURCE_PREFERENCE.index(src.key) if src and src.key in SOURCE_PREFERENCE else len(SOURCE_PREFERENCE)
    return (y.comparable, y.year, y.month_to, national, -rel, -pref)


# ---------------------------------------------------------------------------
# Reading the months (grouped SQL, once per database state: memo.py)
# ---------------------------------------------------------------------------


def _load_reporter_months(ctx: Ctx, since: date) -> dict[tuple[str, str, int], Months]:
    """(reporter, flow, source) -> monthly totals and partner sums, every reporter."""
    q = (select(T.reporter_iso3.label("reporter"), T.flow.label("flow"), T.source_id.label("sid"),
                T.period_start.label("ps"), _is_world().label("w"),
                func.count(distinct(T.partner_iso3)).label("partners"), *_agg_columns())
         .where(*base_where(ctx.db), T.frequency == "M", _partner_filter(), T.period_start >= since)
         .group_by(T.reporter_iso3, T.flow, T.source_id, T.period_start, _is_world()))
    out: dict[tuple[str, str, int], Months] = defaultdict(Months)
    for r in ctx.db.execute(q):
        out[(r.reporter, r.flow, r.sid)].cells.setdefault(r.ps, {})["w" if r.w else "p"] = Agg.from_row(r)
    return dict(out)


def reporter_months(ctx: Ctx) -> dict[tuple[str, str, int], Months]:
    since = _window_start(ctx.today)
    return cached(ctx.db, "ytd.reporter_months", (since.isoformat(),), lambda: _load_reporter_months(ctx, since))


def _load_partner_months(ctx: Ctx, partner: str, declared_flow: str, since: date) -> dict[tuple[str, int], dict[date, Agg]]:
    q = (select(T.reporter_iso3.label("reporter"), T.source_id.label("sid"), T.period_start.label("ps"), *_agg_columns())
         .where(*base_where(ctx.db), T.frequency == "M", T.flow == declared_flow, T.partner_iso3 == partner,
                T.reporter_iso3 != partner, T.period_start >= since)
         .group_by(T.reporter_iso3, T.source_id, T.period_start))
    out: dict[tuple[str, int], dict[date, Agg]] = defaultdict(dict)
    for r in ctx.db.execute(q):
        out[(r.reporter, r.sid)][r.ps] = Agg.from_row(r)
    return dict(out)


# ---------------------------------------------------------------------------
# What the pages ask for
# ---------------------------------------------------------------------------


def reporter_ytd(ctx: Ctx, reporter: str, flow: str) -> dict:
    """The reporter's own year-to-date figure for one flow (one source), or why there is none.

    status: "ok" | "no_monthly" (no monthly rows at all) | "full_year" (the newest monthly year is
    complete: the annual figure is the freshest) | "stale" (monthly data too old) | "incomplete"
    (no month with a published total, or no January)."""
    months = {sid: m for (rep, f, sid), m in reporter_months(ctx).items() if rep == reporter and f == flow}
    if not months:
        return {"status": "no_monthly", "figure": None, "last_month": None}
    best, best_key = None, None
    last_month: date | None = None
    full_year = False
    for sid, m in months.items():
        counted, summed, excluded = m.counted()
        if counted:
            newest = max(counted)
            if last_month is None or newest > last_month:
                last_month = newest
                full_year = sum(1 for ps in counted if ps.year == newest.year) >= 12
        y = compute(counted, ctx.today, summed_from_partners=summed, excluded=excluded)
        if y is None:
            continue
        k = _choice_key(ctx, reporter, sid, y)
        if best_key is None or k > best_key:
            best, best_key = (y, sid), k
    lm = f"{last_month.year}-{last_month.month:02d}" if last_month else None
    if best is None:
        if last_month is not None and last_month < _min_last_month(ctx.today):
            status = "stale"
        elif full_year:
            status = "full_year"
        else:
            status = "incomplete"
        return {"status": status, "figure": None, "last_month": lm}
    y, sid = best
    return {"status": "ok", "figure": {"iso3": reporter, **ctx.names(reporter), "flow": flow,
                                        **serialize(ctx, y, sid)}, "last_month": lm}


def mirror_ytd(ctx: Ctx, iso3: str, flow: str, limit: int = MIRROR_ROWS) -> dict | None:
    """What OTHER countries declare about trade with `iso3` this year so far, one row per declaring
    country and source (never added up). flow='export' -> importers declaring imports from iso3.

    A month counts for a declaring country only when its own total for that month is published
    (same rule as its own figures) AND it declares a row for `iso3`."""
    declared_flow = "import" if flow == "export" else "export"
    since = _window_start(ctx.today)
    partner_months = cached(ctx.db, "ytd.partner_months", (iso3, declared_flow, since.isoformat()),
                            lambda: _load_partner_months(ctx, iso3, declared_flow, since))
    rep_months = reporter_months(ctx)
    best: dict[str, tuple[tuple, Ytd, int]] = {}
    for (reporter, sid), cells in partner_months.items():
        if not ctx.is_country(reporter):
            continue
        own = rep_months.get((reporter, declared_flow, sid))
        if own is None:
            continue
        counted_own, _, excluded = own.counted()
        counted = {ps: agg for ps, agg in cells.items() if ps in counted_own}
        excl = {**excluded, **{ps: "no_total" for ps in cells if ps not in counted_own and ps not in excluded}}
        y = compute(counted, ctx.today, excluded=excl)
        if y is None:
            continue
        k = _choice_key(ctx, reporter, sid, y)
        if reporter not in best or k > best[reporter][0]:
            best[reporter] = (k, y, sid)
    rows = [{"iso3": rep, **ctx.names(rep), "link": f"/paesi/{rep}", **serialize(ctx, y, sid)}
            for rep, (_, y, sid) in best.items()]
    if not rows:
        return None
    rows.sort(key=lambda r: -(r["net_weight_kg"] or 0))
    return {"declared_flow": declared_flow, "rows": rows[:limit], "count": len(rows)}


def leaders_ytd(ctx: Ctx, flow: str, limit: int = 6) -> dict | None:
    """Reporting COUNTRIES with a year-to-date figure for one flow (each its own source and months),
    for the overview. Only the newest year is listed; the EU aggregates are left out (they contain
    their members: the list is of countries, as the annual ranking)."""
    reporters = sorted({rep for (rep, f, _) in reporter_months(ctx) if f == flow
                        and rep not in AGGREGATE_REPORTERS and ctx.is_country(rep)})
    rows = [r["figure"] for rep in reporters if (r := reporter_ytd(ctx, rep, flow))["figure"]]
    if not rows:
        return None
    year = max(r["year"] for r in rows)
    rows = [r for r in rows if r["year"] == year]
    rows.sort(key=lambda r: -(r["net_weight_kg"] or 0))
    return {
        "year": year, "prev_year": year - 1, "flow": flow, "rows": rows[:limit], "count": len(rows),
        "is_demo": any(r["is_demo"] for r in rows[:limit]),
        "sources": sources_used(ctx, rows[:limit]),
    }


__all__ = ["MAX_LAG_MONTHS", "Months", "Ytd", "compute", "leaders_ytd", "mirror_ytd", "reporter_ytd"]
