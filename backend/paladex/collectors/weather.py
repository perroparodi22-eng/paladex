"""NASA POWER: monthly temperature and precipitation per honey region, with anomalies.

Source: NASA Langley Research Center, POWER project (https://power.larc.nasa.gov), community
"AG" (agroclimatology), parameters T2M (temperature at 2 m, °C) and PRECTOTCORR (bias-corrected
precipitation, mm/day). Free, no key. NASA shares Earth-science data fully and openly, private
industry included; the POWER Referencing Guide asks users to cite the project, the service and
version and the date accessed, and to tell the project when data are passed on to others.
Open-Meteo is deliberately NOT used: its free tier is non-commercial.

What the service really offers (checked live, 4 Nov 2026)
--------------------------------------------------------
* Monthly point API (``/api/temporal/monthly/point``): MERRA-2 reanalysis, monthly mean T2M and
  mean daily PRECTOTCORR (mm/day); month "13" is the annual value. Months not yet processed are
  ``-999`` (on 4 Nov 2026 the series ended with September 2026). Header ``sources: ["MERRA2"]``.
* Daily point API (``/api/temporal/daily/point``): MERRA-2 followed by the GEOS-IT "quick-look"
  near-real-time stream, about 2-3 days behind real time (header ``sources: ["MERRA2", "GEOSIT"]``).
  POWER replaces the quick-look days with MERRA-2 within 2-3 months.
* HTTP 422 = invalid request, 429 = too many requests. No numeric rate limit is published; the
  docs warn that repeating requests for the same location can get a client blocked.

How this collector works
------------------------
* For every point in ``reference/regions.py`` (1-4 per region) it keeps the last
  ``MONTHS_KEPT`` complete months.
* Months the monthly API publishes are stored as ``published``. Recent months the monthly API
  does not have yet are computed from the daily API: mean of the daily T2M and sum of the daily
  PRECTOTCORR, only for months whose days are ALL available, and stored as ``provisional``
  (quick-look data). When the monthly API later publishes that month, the stored value becomes a
  new revision (append-only: ``services.ingest``). A month still in progress is never stored.
* Baseline: 1991-2020 normals computed from the SAME monthly series (mean temperature; mean of the
  monthly precipitation totals), so every anomaly is homogeneous with the data it is compared to.
  They are computed once per point from the 1991-current monthly request and cached in
  ``app_settings`` (``nasa_power_normals:<point key>``, with the query used); a forced run
  recomputes them.
* Anomalies: ``temp_anomaly_c`` = temperature - normal (°C); ``precip_anomaly_pct`` = monthly
  precipitation as a PERCENTAGE OF NORMAL (100 = normal, 60 = 40 % below), only when the normal
  is at least ``MIN_NORMAL_PRECIP_MM`` (a percentage of an almost-zero normal says nothing).
* Politeness: at least ``PACE_SECONDS`` between requests, one monthly and at most one daily
  request per point, and points that are already up to date are skipped (so a manual
  "Aggiorna dati" does not re-download everything). A 429 stops the run after saving what was
  collected; it resumes at the next run. ``ctx.checkpoint()`` after every region.
* Every row keeps the exact API query in ``source_url`` and the point, coordinates, basis
  (monthly / daily), number of days, NASA sources and API version, and the normals in ``extra``.
"""
from __future__ import annotations

import calendar
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select

from ..api.common import get_setting, set_setting
from ..enums import DataStatus, Reliability, SourceKind
from ..models import WeatherObservation, utcnow
from ..reference.regions import Point, Region, all_regions
from .base import CollectContext, Collector, CollectorError, Offline, month_bounds

log = logging.getLogger(__name__)

API_ROOT = "https://power.larc.nasa.gov/api/temporal"
MONTHLY_URL = API_ROOT + "/monthly/point"
DAILY_URL = API_ROOT + "/daily/point"
PARAMETERS = ("T2M", "PRECTOTCORR")
EXPECTED_UNITS = {"T2M": "C", "PRECTOTCORR": "mm/day"}
COMMUNITY = "AG"
FILL_VALUE = -999.0

BASELINE_START, BASELINE_END = 1991, 2020
BASELINE_LABEL = f"{BASELINE_START}-{BASELINE_END}"
MIN_BASELINE_YEARS = 25          # a calendar month needs at least this many valid years for a normal
MIN_NORMAL_PRECIP_MM = 1.0       # below this the "% of normal" is not computed
MONTHS_KEPT = 24                 # complete months stored per point
LATENCY_DAYS = 4                 # POWER meteorology is 2-3 days behind real time (FAQ), plus margin
RECHECK_PROVISIONAL_DAYS = 7     # re-ask for provisional months at most once a week
PACE_SECONDS = 2.0               # between two requests to power.larc.nasa.gov
SETTING_PREFIX = "nasa_power_normals:"
NORMALS_VERSION = 1

CITATION = ("The data was obtained from the National Aeronautics and Space Administration (NASA) Langley Research "
            "Center (LaRC) Prediction of Worldwide Energy Resource (POWER) Project funded through the NASA Earth "
            "Science/Applied Science Program.")


def _today() -> date:
    """Indirection so tests can freeze the date the collector works from."""
    return date.today()


def _regions() -> tuple[Region, ...]:
    return all_regions()


class RateLimited(CollectorError):
    """NASA POWER answered 429 Too Many Requests (after the framework's retries)."""


# ---------------------------------------------------------------------------
# Pure parsing / computing helpers (tested directly)
# ---------------------------------------------------------------------------

Month = tuple[int, int]   # (year, month)


@dataclass
class PowerDoc:
    """One POWER point answer: values per period key, with header metadata."""

    values: dict[str, dict[str, float | None]]          # parameter -> {period key: value | None}
    lat: float
    lon: float
    elevation: float | None
    api_version: str | None
    sources: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)


def _parse_power(content: bytes, what: str) -> PowerDoc:
    try:
        data = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CollectorError(f"NASA POWER {what}: answer is not JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise CollectorError(f"NASA POWER {what}: unexpected answer")
    try:
        params = data["properties"]["parameter"]
        coords = data["geometry"]["coordinates"]
    except (KeyError, TypeError) as exc:
        msgs = data.get("messages") or data.get("detail") or data.get("errors")
        raise CollectorError(f"NASA POWER {what}: unexpected structure ({msgs or exc})") from exc
    meta = data.get("parameters") or {}
    for p, unit in EXPECTED_UNITS.items():
        if p not in params:
            raise CollectorError(f"NASA POWER {what}: parameter {p} missing from the answer")
        got = (meta.get(p) or {}).get("units")
        if got is not None and got != unit:
            raise CollectorError(f"NASA POWER {what}: {p} is in {got!r}, expected {unit!r}")
    fill = (data.get("header") or {}).get("fill_value", FILL_VALUE)
    values: dict[str, dict[str, float | None]] = {}
    for p in PARAMETERS:
        series = params[p]
        if not isinstance(series, dict):
            raise CollectorError(f"NASA POWER {what}: {p} is not a series")
        out: dict[str, float | None] = {}
        for k, v in series.items():
            if v is None or not isinstance(v, (int, float)) or v == fill or v <= -998:
                out[str(k)] = None
            else:
                out[str(k)] = float(v)
        values[p] = out
    header = data.get("header") or {}
    api = header.get("api") or {}
    return PowerDoc(
        values=values, lon=float(coords[0]), lat=float(coords[1]),
        elevation=float(coords[2]) if len(coords) > 2 and coords[2] is not None else None,
        api_version=api.get("version"), sources=list(header.get("sources") or []),
        messages=[str(m) for m in (data.get("messages") or [])],
    )


def parse_monthly(content: bytes) -> tuple[PowerDoc, dict[Month, tuple[float | None, float | None]]]:
    """Monthly answer -> {(year, month): (T2M °C, PRECTOTCORR mm/day)}. Month 13 (annual) is dropped;
    fill values (-999) become None."""
    doc = _parse_power(content, "monthly")
    out: dict[Month, tuple[float | None, float | None]] = {}
    keys = set(doc.values["T2M"]) | set(doc.values["PRECTOTCORR"])
    for k in keys:
        if len(k) != 6 or not k.isdigit():
            continue
        y, m = int(k[:4]), int(k[4:])
        if not 1 <= m <= 12:
            continue
        out[(y, m)] = (doc.values["T2M"].get(k), doc.values["PRECTOTCORR"].get(k))
    return doc, dict(sorted(out.items()))


def parse_daily(content: bytes) -> tuple[PowerDoc, dict[date, tuple[float | None, float | None]]]:
    """Daily answer -> {day: (T2M °C, PRECTOTCORR mm/day)}; fill values become None."""
    doc = _parse_power(content, "daily")
    out: dict[date, tuple[float | None, float | None]] = {}
    keys = set(doc.values["T2M"]) | set(doc.values["PRECTOTCORR"])
    for k in keys:
        try:
            d = datetime.strptime(k, "%Y%m%d").date()
        except ValueError:
            continue
        out[d] = (doc.values["T2M"].get(k), doc.values["PRECTOTCORR"].get(k))
    return doc, dict(sorted(out.items()))


def days_in(y: int, m: int) -> int:
    return calendar.monthrange(y, m)[1]


def monthly_total_mm(rate_mm_day: float, y: int, m: int) -> float:
    """POWER publishes monthly precipitation as the mean daily rate: total = rate x days."""
    return rate_mm_day * days_in(y, m)


@dataclass
class Normals:
    temp_c: list[float | None]        # index 0 = January
    precip_mm: list[float | None]
    years: list[int]                  # valid years per calendar month

    def to_json(self) -> dict:
        return {"temp_c": self.temp_c, "precip_mm": self.precip_mm, "years": self.years}

    @classmethod
    def from_json(cls, d: dict) -> Normals:
        return cls(temp_c=list(d["temp_c"]), precip_mm=list(d["precip_mm"]), years=list(d["years"]))


def compute_normals(monthly: dict[Month, tuple[float | None, float | None]],
                    start: int = BASELINE_START, end: int = BASELINE_END) -> Normals:
    """1991-2020 normals per calendar month from the monthly series: mean temperature and the mean
    of the monthly precipitation totals. A month with fewer than MIN_BASELINE_YEARS complete years
    gets no normal (None), never a partial one."""
    temps: dict[int, list[float]] = defaultdict(list)
    precs: dict[int, list[float]] = defaultdict(list)
    for (y, m), (t, p) in monthly.items():
        if not start <= y <= end or t is None or p is None:
            continue
        temps[m].append(t)
        precs[m].append(monthly_total_mm(p, y, m))
    out = Normals(temp_c=[], precip_mm=[], years=[])
    for m in range(1, 13):
        n = min(len(temps[m]), len(precs[m]))
        out.years.append(n)
        if n < MIN_BASELINE_YEARS:
            out.temp_c.append(None)
            out.precip_mm.append(None)
            continue
        out.temp_c.append(round(sum(temps[m]) / len(temps[m]), 2))
        out.precip_mm.append(round(sum(precs[m]) / len(precs[m]), 1))
    return out


@dataclass
class MonthValue:
    year: int
    month: int
    temp_c: float
    precip_mm: float
    basis: str                 # "monthly" (monthly API) | "daily" (computed from the daily API)
    days: int
    precip_mm_day: float | None = None


def months_from_daily(daily: dict[date, tuple[float | None, float | None]]) -> tuple[list[MonthValue], list[tuple[Month, int, int]]]:
    """Aggregate the daily series per calendar month. Returns (complete months, incomplete months as
    ((y, m), days with data, days in month)). Only months with every day present are complete."""
    by: dict[Month, list[tuple[float, float]]] = defaultdict(list)
    seen: set[Month] = set()
    for d, (t, p) in daily.items():
        seen.add((d.year, d.month))
        if t is not None and p is not None:
            by[(d.year, d.month)].append((t, p))
    complete: list[MonthValue] = []
    incomplete: list[tuple[Month, int, int]] = []
    for ym in sorted(seen):
        vals = by.get(ym, [])
        need = days_in(*ym)
        if len(vals) == need:
            complete.append(MonthValue(
                ym[0], ym[1], temp_c=round(sum(v[0] for v in vals) / need, 2),
                precip_mm=round(sum(v[1] for v in vals), 1), basis="daily", days=need,
            ))
        else:
            incomplete.append((ym, len(vals), need))
    return complete, incomplete


def anomalies(v: MonthValue, normals: Normals) -> tuple[float | None, float | None, float | None, float | None]:
    """(temp anomaly °C, precipitation % of normal, normal temp, normal precip mm)."""
    nt = normals.temp_c[v.month - 1]
    npr = normals.precip_mm[v.month - 1]
    t_anom = round(v.temp_c - nt, 2) if nt is not None else None
    p_pct = round(100.0 * v.precip_mm / npr, 1) if npr is not None and npr >= MIN_NORMAL_PRECIP_MM else None
    return t_anom, p_pct, nt, npr


def add_months(ym: Month, n: int) -> Month:
    idx = ym[0] * 12 + (ym[1] - 1) + n
    return idx // 12, idx % 12 + 1


def last_complete_month(today: date) -> Month:
    """The newest month whose last day is at least LATENCY_DAYS behind `today`."""
    ref = today - timedelta(days=LATENCY_DAYS)
    y, m = ref.year, ref.month
    if ref.day < days_in(y, m):
        y, m = add_months((y, m), -1)
    return y, m


def month_label(ym: Month) -> str:
    return f"{ym[0]:04d}-{ym[1]:02d}"


def series_key(point: Point, ym: Month) -> str:
    return f"{point.key}|{month_label(ym)}"


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


class NasaPowerWeatherCollector(Collector):
    key = "nasa_power_weather"
    name = "NASA POWER — meteo mensile delle regioni del miele"
    publisher = "NASA Langley Research Center (POWER Project)"
    homepage = "https://power.larc.nasa.gov/"
    kind = SourceKind.API
    reliability = Reliability.OFFICIAL
    category = "weather"
    language = "en"
    expected_update = ("Ogni mese: mese appena concluso disponibile dopo 3-4 giorni (dati rapidi, provvisori); "
                       "dati definitivi MERRA-2 dopo circa 2 mesi")
    expected_update_en = ("Monthly: the month just ended is available after 3-4 days (quick-look, provisional); "
                          "final MERRA-2 data after about 2 months")
    expected_max_age_days = 45
    terms_note = ("NASA Earth-science data are shared fully and openly, private industry included. Cite: NASA Langley "
                  "Research Center POWER Project (service, version, date accessed); POWER asks to be told when its data "
                  "are passed on to others. Free, no key; HTTP 429 when too many requests.")
    schedule = {"trigger": "cron", "day": 6, "hour": 6, "minute": 40}
    order = 75

    def collect(self, ctx: CollectContext) -> None:
        # Be gentle with the service: slower than the framework's default pace.
        ctx.MIN_INTERVAL_PER_HOST = max(ctx.MIN_INTERVAL_PER_HOST, PACE_SECONDS)
        today = _today()
        target = last_complete_month(today)
        window_start = add_months(target, -(MONTHS_KEPT - 1))
        state = _stored_state(ctx, month_bounds(*window_start)[0])
        regions = _regions()
        done = failed = skipped = 0
        stopped = False
        for region in regions:
            for point in region.points:
                if not ctx.force and _up_to_date(ctx, point, state.get(point.key), target):
                    skipped += 1
                    continue
                try:
                    self._collect_point(ctx, region, point, target, window_start, today)
                    done += 1
                except RateLimited as exc:
                    ctx.warn(f"NASA POWER ha limitato le richieste (429) a {point.name}: raccolta interrotta, "
                             f"riprende al prossimo aggiornamento ({exc})")
                    stopped = True
                    break
                except Offline:
                    raise
                except CollectorError as exc:
                    failed += 1
                    ctx.warn(f"{region.key} / {point.name}: {exc}")
            ctx.checkpoint()
            if stopped:
                break
        log.info("nasa_power_weather: %s points collected, %s up to date, %s failed", done, skipped, failed)
        if done == 0 and failed and not skipped:
            raise CollectorError(f"NASA POWER: nessun punto raccolto ({failed} errori)")

    # ------------------------------------------------------------------
    def _fetch(self, ctx: CollectContext, url: str, params: dict, title: str):
        """GET one POWER answer; only successful answers are archived as raw documents."""
        doc = ctx.fetch(url, params=params, title=title, accept_status=(200, 422, 429), store=False)
        if doc.status_code == 429:
            raise RateLimited("HTTP 429")
        if doc.status_code == 422:
            raise CollectorError(f"richiesta rifiutata (422): {doc.text[:300]}")
        doc.raw_document_id, doc.unchanged = ctx.store_raw(doc.url, doc.content, doc.content_type, title)
        return doc

    def _point_params(self, point: Point, start: str, end: str) -> dict:
        return {"parameters": ",".join(PARAMETERS), "community": COMMUNITY, "longitude": f"{point.lon:.2f}",
                "latitude": f"{point.lat:.2f}", "start": start, "end": end, "format": "JSON"}

    def _check_point(self, doc: PowerDoc, point: Point, what: str) -> None:
        if abs(doc.lat - point.lat) > 0.01 or abs(doc.lon - point.lon) > 0.01:
            raise CollectorError(f"{what}: answer is for {doc.lat},{doc.lon}, not for {point.lat},{point.lon}")

    def _collect_point(self, ctx: CollectContext, region: Region, point: Point, target: Month,
                       window_start: Month, today: date) -> None:
        normals, baseline_url = _cached_normals(ctx, point)
        if normals is None or ctx.force:
            doc = self._fetch(ctx, MONTHLY_URL, self._point_params(point, str(BASELINE_START), str(today.year)),
                              f"NASA POWER monthly {point.name} {BASELINE_START}-{today.year}")
            mdoc, monthly = parse_monthly(doc.content)
            self._check_point(mdoc, point, "monthly")
            normals = compute_normals(monthly)
            if all(t is None for t in normals.temp_c):
                raise CollectorError(f"nessuna normale {BASELINE_LABEL} calcolabile (anni validi: {normals.years})")
            baseline_url = doc.url
            set_setting(ctx.session, SETTING_PREFIX + point.key, {
                "version": NORMALS_VERSION, "baseline": BASELINE_LABEL, "lat": point.lat, "lon": point.lon,
                **normals.to_json(), "source_url": doc.url, "api_version": mdoc.api_version,
                "sources": mdoc.sources, "computed_at": utcnow().isoformat(timespec="seconds"),
            })
        else:
            doc = self._fetch(ctx, MONTHLY_URL, self._point_params(point, str(window_start[0]), str(today.year)),
                              f"NASA POWER monthly {point.name} {window_start[0]}-{today.year}")
            mdoc, monthly = parse_monthly(doc.content)
            self._check_point(mdoc, point, "monthly")

        # 1) months the monthly API publishes (MERRA-2): published
        published: list[MonthValue] = []
        for (y, m), (t, p) in monthly.items():
            if (y, m) < window_start or (y, m) > target:
                continue
            if t is None or p is None:
                continue
            published.append(MonthValue(y, m, temp_c=round(t, 2), precip_mm=round(monthly_total_mm(p, y, m), 1),
                                        basis="monthly", days=days_in(y, m), precip_mm_day=p))
        for v in published:
            self._store(ctx, region, point, v, normals, doc.url, doc.raw_document_id, mdoc, baseline_url,
                        DataStatus.PUBLISHED)
        have = {(v.year, v.month) for v in published}
        if have:
            ym = window_start
            while ym < max(have):
                if ym not in have:
                    ctx.warn(f"{point.name}: {month_label(ym)} assente nella serie mensile NASA POWER")
                ym = add_months(ym, 1)

        # 2) newer months: computed from the daily API (quick-look), provisional
        latest_pub = max(((v.year, v.month) for v in published), default=add_months(window_start, -1))
        first_gap = add_months(latest_pub, 1)
        if first_gap > target:
            return
        start = month_bounds(*first_gap)[0]
        ddoc_raw = self._fetch(ctx, DAILY_URL, self._point_params(point, start.strftime("%Y%m%d"), today.strftime("%Y%m%d")),
                               f"NASA POWER daily {point.name} {start:%Y%m%d}-{today:%Y%m%d}")
        ddoc, daily = parse_daily(ddoc_raw.content)
        self._check_point(ddoc, point, "daily")
        complete, incomplete = months_from_daily(daily)
        for v in complete:
            if (v.year, v.month) > target or (v.year, v.month) < first_gap:
                continue
            self._store(ctx, region, point, v, normals, ddoc_raw.url, ddoc_raw.raw_document_id, ddoc, baseline_url,
                        DataStatus.PROVISIONAL)
        for ym, have, need in incomplete:
            # The month in progress (or just ended, still inside the service latency) is expected to be
            # incomplete; an older gap is not.
            if ym < target:
                ctx.warn(f"{point.name}: {month_label(ym)} incompleto nei dati giornalieri ({have}/{need} giorni), non salvato")

    def _store(self, ctx: CollectContext, region: Region, point: Point, v: MonthValue, normals: Normals,
               url: str, raw_id: int | None, doc: PowerDoc, baseline_url: str | None, status: DataStatus) -> None:
        t_anom, p_pct, nt, npr = anomalies(v, normals)
        start, end = month_bounds(v.year, v.month)
        label = month_label((v.year, v.month))
        extra = {
            "point": point.key, "point_name": point.name, "lat": point.lat, "lon": point.lon,
            "basis": v.basis, "days": v.days, "sources": doc.sources, "api_version": doc.api_version,
            "community": COMMUNITY, "parameters": list(PARAMETERS),
            "normal_temp_c": nt, "normal_precip_mm": npr,
            "baseline_years": normals.years[v.month - 1], "baseline_url": baseline_url,
        }
        if v.precip_mm_day is not None:
            extra["precip_mm_day"] = v.precip_mm_day
        notes = None
        if v.basis == "daily":
            notes = ("Computed from daily values (mean temperature, summed precipitation) of the near-real-time "
                     "stream; NASA POWER replaces it with final MERRA-2 data within 2-3 months.")
        ctx.add_weather(
            series_key=series_key(point, (v.year, v.month)), region_key=region.key, country_iso3=region.country_iso3,
            period_start=start, period_end=end, period_label=label, frequency="M",
            temp_mean_c=v.temp_c, precip_mm=v.precip_mm, temp_anomaly_c=t_anom, precip_anomaly_pct=p_pct,
            baseline=BASELINE_LABEL, data_status=status, reliability=Reliability.OFFICIAL,
            source_url=url, raw_document_id=raw_id or None, notes=notes, extra=extra,
        )
        c = ctx.counters
        if c.newest_period_start is None or start > c.newest_period_start:
            c.newest_period_start = start
            c.newest_period_label = label


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------


@dataclass
class PointState:
    months: dict[str, str] = field(default_factory=dict)      # period label -> data_status
    provisional_seen: datetime | None = None                  # oldest last_seen_at among provisional rows


def _stored_state(ctx: CollectContext, since: date) -> dict[str, PointState]:
    W = WeatherObservation
    rows = ctx.session.execute(
        select(W.series_key, W.period_label, W.data_status, W.last_seen_at).where(
            W.source_id == ctx.source.id, W.is_current.is_(True), W.is_demo.is_(False), W.period_start >= since)
    )
    out: dict[str, PointState] = {}
    for sk, label, status, seen in rows:
        pk = sk.split("|", 1)[0]
        st = out.setdefault(pk, PointState())
        st.months[label] = status
        if status == DataStatus.PROVISIONAL.value and (st.provisional_seen is None or seen < st.provisional_seen):
            st.provisional_seen = seen
    return out


def _cached_normals(ctx: CollectContext, point: Point) -> tuple[Normals | None, str | None]:
    raw = get_setting(ctx.session, SETTING_PREFIX + point.key)
    if not isinstance(raw, dict) or raw.get("version") != NORMALS_VERSION or raw.get("baseline") != BASELINE_LABEL:
        return None, None
    if raw.get("lat") != point.lat or raw.get("lon") != point.lon:
        return None, None   # the point moved: recompute
    try:
        return Normals.from_json(raw), raw.get("source_url")
    except (KeyError, TypeError):
        return None, None


def _up_to_date(ctx: CollectContext, point: Point, st: PointState | None, target: Month) -> bool:
    """True when nothing new can be expected yet for this point: the newest complete month is stored,
    the normals are cached and provisional months were re-checked within RECHECK_PROVISIONAL_DAYS."""
    if st is None or month_label(target) not in st.months:
        return False
    if _cached_normals(ctx, point)[0] is None:
        return False
    if st.provisional_seen is not None and utcnow() - st.provisional_seen > timedelta(days=RECHECK_PROVISIONAL_DAYS):
        return False
    return True
