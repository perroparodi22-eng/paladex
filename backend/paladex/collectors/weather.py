"""NASA POWER: monthly temperature and precipitation per honey region, with anomalies.

Source: NASA Langley Research Center, POWER project (https://power.larc.nasa.gov), community
"AG" (agroclimatology), parameters T2M (temperature at 2 m, °C) and PRECTOTCORR (bias-corrected
precipitation, mm/day). Free, no key. NASA shares Earth-science data fully and openly, private
industry included. The POWER Referencing Guide asks users to cite the project (``CITATION``) with
the service name, version and date accessed, and to tell the project when data are passed on to
others. Open-Meteo is deliberately NOT used: its free tier is non-commercial.

What the service really offers (checked live, 4 Nov 2026)
--------------------------------------------------------
* Monthly point API (``/api/temporal/monthly/point``): MERRA-2 reanalysis, monthly mean T2M and
  mean daily PRECTOTCORR (mm/day); month "13" is the annual value. Months not yet processed are
  ``-999`` (on 4 Nov 2026 the series ended with September 2026). Header ``sources: ["MERRA2"]``.
* Daily point API (``/api/temporal/daily/point``): MERRA-2 followed by the GEOS-IT near-real-time
  stream (header ``sources: ["MERRA2", "GEOSIT"]``). The FAQ gives a latency of 2-3 days for
  meteorology; the methodology says MERRA-2 reaches "within several months of real time" and the
  near-real-time stream fills the rest.
* Meteorology comes at the source resolution (MERRA-2: 0.5° x 0.625°). HTTP 422 = invalid request,
  429 = too many requests. No numeric rate limit is published; the docs warn that an application
  that keeps requesting the same location may be blocked.

How this collector works
------------------------
* For every point in ``reference/regions.py`` (1-4 per region) it keeps the last ``MONTHS_KEPT``
  complete months (never the month in progress: a month is complete only when all its days are in).
* Months the monthly API publishes are stored as ``published``. Newer months are computed from the
  daily API (mean of the daily T2M, sum of the daily PRECTOTCORR), only when EVERY day of the month
  is present, and stored as ``provisional``. When the monthly API later publishes such a month, the
  stored value gets a new revision (append-only: ``services.ingest``).
* Baseline: 1991-2020 normals computed from the SAME monthly series (mean temperature; mean of the
  monthly precipitation totals), so every anomaly is homogeneous with the data it is compared to.
  They come from one 1991-current monthly request per point, cached in ``app_settings``
  (``nasa_power_normals:<point key>``, with the query used). Each stored row also keeps its month's
  normal in ``extra``, so the cache is rebuilt without any request after a data-only copy of the
  database (the starter data ships no settings). A forced run recomputes them.
* Anomalies: ``temp_anomaly_c`` = temperature - normal (°C); ``precip_anomaly_pct`` = monthly
  precipitation as a PERCENTAGE OF NORMAL (100 = normal, 60 = 40 % below), only when the normal is
  at least ``MIN_NORMAL_PRECIP_MM`` (a percentage of an almost-zero normal says nothing).

Politeness (one request at a time, at least ``PACE_SECONDS`` apart)
-------------------------------------------------------------------
* A point is asked only for what it lacks: nothing when every month of the window is final; the
  daily API only for months not held at all; the monthly API only for the normals or when it may
  have published a month still held as provisional. MERRA-2 is processed for the whole globe at
  once, so the newest month seen in one monthly answer holds for every point: it is remembered
  (``nasa_power_monthly_status``) and re-probed with a single request at most every
  ``PROBE_INTERVAL_HOURS``. A start-up or manual "Aggiorna dati" run in the middle of the month
  therefore costs no request or one, never a re-download of every point.
* First run: 2 requests per point (monthly 1991-current + daily for the months after the newest
  MERRA-2 month); then about 1-2 per point and month.
* A 429 stops the run (what was collected is kept; it resumes at the next run);
  ``MAX_CONSECUTIVE_TROUBLE`` points in a row failing with a server error or a timeout stop it too
  (the service is down: no point in asking it for the remaining points). ``ctx.checkpoint()`` after
  every region, so an interrupted first run resumes where it stopped.
* Every row keeps the exact API query in ``source_url``, plus the point, coordinates, basis
  (monthly / daily), number of days, NASA sources and API version, and its normal in ``extra``.
"""
from __future__ import annotations

import calendar
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select

from ..api.common import get_setting, set_setting
from ..enums import DataStatus, Reliability, SourceKind
from ..models import WeatherObservation, utcnow
from ..reference.regions import Point, Region, all_regions
from .base import (
    CollectContext,
    Collector,
    CollectorError,
    FetchResult,
    Offline,
    month_bounds,
)

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
PACE_SECONDS = 1.5               # between two requests to power.larc.nasa.gov (never below the framework's)
PROBE_INTERVAL_HOURS = 24        # re-ask the monthly API for its newest month at most this often
MAX_CONSECUTIVE_TROUBLE = 3      # points in a row failing with HTTP 5xx / timeouts: stop the run
SETTING_PREFIX = "nasa_power_normals:"
STATUS_SETTING = "nasa_power_monthly_status"
NORMALS_VERSION = 1

# POWER Referencing Guide (https://power.larc.nasa.gov/docs/referencing/), as published on 4 Nov 2026.
CITATION = ("The data was obtained from National Aeronautics and Space Administration (NASA) Langley Research "
            "Center's Prediction Of Worldwide Energy Resources (POWER) project funded through the NASA Earth "
            "Science Division.")


def _today() -> date:
    """Indirection so tests can freeze the date the collector works from."""
    return date.today()


def _regions() -> tuple[Region, ...]:
    return all_regions()


class RateLimited(CollectorError):
    """NASA POWER answered 429 Too Many Requests (after the framework's retries)."""


class ServiceTrouble(CollectorError):
    """HTTP 5xx or a timeout (after the framework's retries): the service, not the request, failed."""


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
            if v is None or isinstance(v, bool) or not isinstance(v, (int, float)) or v == fill or v <= -998:
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


def newest_valid_month(monthly: dict[Month, tuple[float | None, float | None]]) -> Month | None:
    """The newest month with both values (the end of the MERRA-2 stream in this answer)."""
    return max((ym for ym, (t, p) in monthly.items() if t is not None and p is not None), default=None)


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
        n = cls(temp_c=list(d["temp_c"]), precip_mm=list(d["precip_mm"]), years=[int(y) for y in d["years"]])
        if not len(n.temp_c) == len(n.precip_mm) == len(n.years) == 12:
            raise ValueError("12 calendar months expected")
        return n


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


def month_window(last: Month, n: int = MONTHS_KEPT) -> list[Month]:
    """The `n` months ending with `last`, oldest first."""
    return [add_months(last, i) for i in range(-(n - 1), 1)]


def last_complete_month(today: date) -> Month:
    """The newest month whose last day is at least LATENCY_DAYS behind `today`."""
    ref = today - timedelta(days=LATENCY_DAYS)
    y, m = ref.year, ref.month
    if ref.day < days_in(y, m):
        y, m = add_months((y, m), -1)
    return y, m


def month_label(ym: Month) -> str:
    return f"{ym[0]:04d}-{ym[1]:02d}"


def parse_month_label(label: str | None) -> Month | None:
    try:
        y, m = (int(x) for x in str(label).split("-"))
    except (TypeError, ValueError):
        return None
    return (y, m) if 1 <= m <= 12 else None


def series_key(point: Point, ym: Month) -> str:
    return f"{point.key}|{month_label(ym)}"


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


@dataclass
class RunState:
    """What one run has learnt so far (never stored on the collector instance: it is shared)."""

    monthly_latest: Month | None = None    # newest month the monthly API publishes (same for every point)
    requests: int = 0


class NasaPowerWeatherCollector(Collector):
    key = "nasa_power_weather"
    name = "NASA POWER — meteo mensile delle regioni del miele"
    publisher = "NASA Langley Research Center (POWER Project)"
    homepage = "https://power.larc.nasa.gov/"
    kind = SourceKind.API
    reliability = Reliability.OFFICIAL
    category = "weather"
    language = "en"
    # Source.expected_update is String(120)
    expected_update = "Mensile: mese concluso dopo 3-4 giorni (dati rapidi, provvisori); definitivi MERRA-2 dopo 1-2 mesi"
    expected_update_en = "Monthly: month just ended after 3-4 days (quick-look, provisional); final MERRA-2 data 1-2 months later"
    expected_max_age_days = 45
    terms_note = ("NASA Earth-science data are shared fully and openly, private industry included. Cite: NASA Langley "
                  "Research Center POWER Project (service, version, date accessed); POWER asks to be told when its data "
                  "are passed on to others. Free, no key; HTTP 429 when too many requests.")
    schedule = {"trigger": "cron", "day": 6, "hour": 6, "minute": 40}
    order = 75

    def collect(self, ctx: CollectContext) -> None:
        ctx.MIN_INTERVAL_PER_HOST = max(ctx.MIN_INTERVAL_PER_HOST, PACE_SECONDS)
        started = time.monotonic()
        window = month_window(last_complete_month(_today()))
        held = _stored_state(ctx, month_bounds(*window[0])[0])
        run = RunState(monthly_latest=None if ctx.force else _known_monthly_latest(ctx))
        updated = up_to_date = failed = trouble_in_a_row = 0
        stop = False
        for region in _regions():
            for point in region.points:
                try:
                    asked = self._collect_point(ctx, region, point, held.get(point.key, {}), window, run)
                except RateLimited as exc:
                    ctx.warn(f"NASA POWER ha limitato le richieste (429) a {point.name}: raccolta interrotta, "
                             f"riprende al prossimo aggiornamento ({exc})")
                    stop = True
                    break
                except Offline:
                    raise
                except ServiceTrouble as exc:
                    failed += 1
                    trouble_in_a_row += 1
                    ctx.warn(f"{region.key} / {point.name}: servizio non disponibile ({exc})")
                    if trouble_in_a_row >= MAX_CONSECUTIVE_TROUBLE:
                        ctx.warn(f"NASA POWER non risponde ({trouble_in_a_row} punti di fila): raccolta interrotta, "
                                 "riprende al prossimo aggiornamento")
                        stop = True
                        break
                    continue
                except CollectorError as exc:
                    failed += 1
                    ctx.warn(f"{region.key} / {point.name}: {exc}")
                    continue
                trouble_in_a_row = 0
                if asked:
                    updated += 1
                else:
                    up_to_date += 1
            ctx.checkpoint()
            if stop:
                break
        log.info("nasa_power_weather: %s points updated, %s already up to date, %s failed; %s requests in %.0f s",
                 updated, up_to_date, failed, run.requests, time.monotonic() - started)
        if updated == 0 and failed and not up_to_date:
            raise CollectorError(f"NASA POWER: nessun punto raccolto ({failed} errori)")

    # ------------------------------------------------------------------
    def _fetch(self, ctx: CollectContext, run: RunState, url: str, params: dict, title: str) -> FetchResult:
        """GET one POWER answer; only successful answers are archived as raw documents."""
        run.requests += 1
        try:
            doc = ctx.fetch(url, params=params, title=title, accept_status=(200, 422, 429, 500, 502, 503, 504),
                            store=False)
        except Offline:
            raise
        except CollectorError as exc:          # timeout after the framework's retries
            raise ServiceTrouble(str(exc)) from exc
        if doc.status_code == 429:
            raise RateLimited("HTTP 429")
        if doc.status_code >= 500:
            raise ServiceTrouble(f"HTTP {doc.status_code}")
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

    def _collect_point(self, ctx: CollectContext, region: Region, point: Point, held: dict[str, str],
                       window: list[Month], run: RunState) -> bool:
        """Bring one point up to date. Returns False when nothing had to be asked."""
        target = window[-1]
        normals, baseline_url = (None, None) if ctx.force else _cached_normals(ctx, point)
        if normals is None and not ctx.force:
            normals, baseline_url = _normals_from_rows(ctx, point)
            if normals is not None:
                _save_normals(ctx, point, normals, baseline_url, None, ["MERRA2"], rebuilt=True)
        status = {ym: held[month_label(ym)] for ym in window if month_label(ym) in held}
        pending = [ym for ym in window if status.get(ym) != DataStatus.PUBLISHED.value]   # missing or provisional
        if normals is not None and not pending and not ctx.force:
            return False

        # 1) Monthly API (MERRA-2): for the normals, or when it may now publish a month not final here.
        need_monthly = (normals is None or ctx.force
                        or (run.monthly_latest is None or pending[0] <= run.monthly_latest))
        published: set[Month] = set()
        asked = False
        if need_monthly:
            full = normals is None or ctx.force
            first_year = BASELINE_START if full else window[0][0]
            doc = self._fetch(ctx, run, MONTHLY_URL, self._point_params(point, str(first_year), str(target[0])),
                              f"NASA POWER monthly {point.name} {first_year}-{target[0]}")
            asked = True
            mdoc, monthly = parse_monthly(doc.content)
            self._check_point(mdoc, point, "monthly")
            newest = newest_valid_month(monthly)
            if newest is not None and (run.monthly_latest is None or newest > run.monthly_latest):
                run.monthly_latest = newest
                set_setting(ctx.session, STATUS_SETTING, {"latest": month_label(newest), "point": point.key,
                                                          "checked_at": utcnow().isoformat(timespec="seconds")})
            if full:
                normals = compute_normals(monthly)
                if all(t is None for t in normals.temp_c):
                    raise CollectorError(f"nessuna normale {BASELINE_LABEL} calcolabile (anni validi: {normals.years})")
                baseline_url = doc.url
                _save_normals(ctx, point, normals, doc.url, mdoc.api_version, mdoc.sources)
            for ym in window:
                t, p = monthly.get(ym, (None, None))
                if t is None or p is None:
                    continue
                y, m = ym
                v = MonthValue(y, m, temp_c=round(t, 2), precip_mm=round(monthly_total_mm(p, y, m), 1),
                               basis="monthly", days=days_in(y, m), precip_mm_day=p)
                self._store(ctx, region, point, v, normals, doc.url, doc.raw_document_id, mdoc, baseline_url,
                            DataStatus.PUBLISHED)
                published.add(ym)
            if published:
                for ym in window:
                    if ym < max(published) and ym not in published:
                        ctx.warn(f"{point.name}: {month_label(ym)} assente nella serie mensile NASA POWER")

        # 2) Daily API (quick-look): months neither published nor held, up to the target month.
        todo = [ym for ym in window if ym not in published and (ym not in status or ctx.force)
                and status.get(ym) != DataStatus.PUBLISHED.value]
        if not todo:
            return asked
        start = month_bounds(*todo[0])[0]
        end = month_bounds(*target)[1]
        ddoc_raw = self._fetch(ctx, run, DAILY_URL,
                               self._point_params(point, start.strftime("%Y%m%d"), end.strftime("%Y%m%d")),
                               f"NASA POWER daily {point.name} {start:%Y%m%d}-{end:%Y%m%d}")
        ddoc, daily = parse_daily(ddoc_raw.content)
        self._check_point(ddoc, point, "daily")
        complete, incomplete = months_from_daily(daily)
        for v in complete:
            ym = (v.year, v.month)
            if ym < todo[0] or ym > target or ym in published or status.get(ym) == DataStatus.PUBLISHED.value:
                continue      # never replace a MERRA-2 month with quick-look data
            self._store(ctx, region, point, v, normals, ddoc_raw.url, ddoc_raw.raw_document_id, ddoc, baseline_url,
                        DataStatus.PROVISIONAL)
        for ym, have, need in incomplete:
            if ym == target:
                # The service is a little later than usual: the month is collected at the next run.
                log.info("nasa_power_weather: %s %s not complete yet (%s/%s days)", point.key, month_label(ym), have, need)
            else:
                ctx.warn(f"{point.name}: {month_label(ym)} incompleto nei dati giornalieri ({have}/{need} giorni), non salvato")
        return True

    def _store(self, ctx: CollectContext, region: Region, point: Point, v: MonthValue, normals: Normals,
               url: str, raw_id: int | None, doc: PowerDoc, baseline_url: str | None, status: DataStatus) -> None:
        t_anom, p_pct, nt, npr = anomalies(v, normals)
        start, end = month_bounds(v.year, v.month)
        label = month_label((v.year, v.month))
        extra = {
            "point": point.key, "point_name": point.name, "lat": point.lat, "lon": point.lon,
            "basis": v.basis, "days": v.days, "sources": doc.sources, "api_version": doc.api_version,
            "community": COMMUNITY, "parameters": list(PARAMETERS),
            "normal_temp_c": nt, "normal_precip_mm": npr, "baseline": BASELINE_LABEL,
            "baseline_years": normals.years[v.month - 1], "baseline_url": baseline_url,
            "normals_version": NORMALS_VERSION,
        }
        if v.precip_mm_day is not None:
            extra["precip_mm_day"] = v.precip_mm_day
        notes = None
        if v.basis == "daily":
            notes = ("Computed from daily values (mean temperature, summed precipitation) of the near-real-time "
                     "stream; replaced by the final MERRA-2 monthly value when NASA POWER publishes it.")
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


def _stored_state(ctx: CollectContext, since: date) -> dict[str, dict[str, str]]:
    """point key -> {period label: data_status} of the current rows from `since` on."""
    W = WeatherObservation
    rows = ctx.session.execute(
        select(W.series_key, W.period_label, W.data_status).where(
            W.source_id == ctx.source.id, W.is_current.is_(True), W.is_demo.is_(False), W.period_start >= since)
    )
    out: dict[str, dict[str, str]] = defaultdict(dict)
    for sk, label, status in rows:
        out[sk.split("|", 1)[0]][label] = status
    return out


def _known_monthly_latest(ctx: CollectContext) -> Month | None:
    """The newest MERRA-2 month seen by a recent run (within PROBE_INTERVAL_HOURS), else None."""
    raw = get_setting(ctx.session, STATUS_SETTING)
    if not isinstance(raw, dict):
        return None
    try:
        checked = datetime.fromisoformat(str(raw.get("checked_at")))
    except ValueError:
        return None
    if utcnow() - checked > timedelta(hours=PROBE_INTERVAL_HOURS):
        return None
    return parse_month_label(raw.get("latest"))


def _save_normals(ctx: CollectContext, point: Point, normals: Normals, url: str | None, api_version: str | None,
                  sources: list[str], rebuilt: bool = False) -> None:
    set_setting(ctx.session, SETTING_PREFIX + point.key, {
        "version": NORMALS_VERSION, "baseline": BASELINE_LABEL, "lat": point.lat, "lon": point.lon,
        **normals.to_json(), "source_url": url, "api_version": api_version, "sources": sources,
        "computed_at": utcnow().isoformat(timespec="seconds"), "rebuilt_from_rows": rebuilt,
    })


def _cached_normals(ctx: CollectContext, point: Point) -> tuple[Normals | None, str | None]:
    raw = get_setting(ctx.session, SETTING_PREFIX + point.key)
    if not isinstance(raw, dict) or raw.get("version") != NORMALS_VERSION or raw.get("baseline") != BASELINE_LABEL:
        return None, None
    if raw.get("lat") != point.lat or raw.get("lon") != point.lon:
        return None, None   # the point moved: recompute
    try:
        return Normals.from_json(raw), raw.get("source_url")
    except (KeyError, TypeError, ValueError):
        return None, None


def _normals_from_rows(ctx: CollectContext, point: Point) -> tuple[Normals | None, str | None]:
    """Rebuild the normals from the stored rows of this point (each keeps its calendar month's normal
    in `extra`), e.g. after a data-only copy of the database. None unless all 12 months are there,
    for the same coordinates, baseline and normals version."""
    W = WeatherObservation
    rows = ctx.session.execute(
        select(W.period_start, W.extra).where(
            W.source_id == ctx.source.id, W.is_current.is_(True), W.is_demo.is_(False),
            W.series_key.like(point.key + "|%"))
    )
    temp: list[float | None] = [None] * 12
    prec: list[float | None] = [None] * 12
    years = [0] * 12
    url = None
    for start, extra in rows:
        e = extra if isinstance(extra, dict) else {}
        if (e.get("lat"), e.get("lon")) != (point.lat, point.lon) or e.get("normals_version") != NORMALS_VERSION \
                or e.get("baseline") != BASELINE_LABEL or not e.get("baseline_years"):
            continue
        m = start.month - 1
        temp[m], prec[m], years[m] = e.get("normal_temp_c"), e.get("normal_precip_mm"), int(e["baseline_years"])
        url = url or e.get("baseline_url")
    if not all(years):
        return None, None
    return Normals(temp_c=temp, precip_mm=prec, years=years), url
