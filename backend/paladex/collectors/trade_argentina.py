"""Argentina, official honey data: monthly exports by destination (INDEC). One collector.

``ar_official_exports``: INDEC (Instituto Nacional de Estadística y Censos), *Sistema de consulta de
comercio exterior de bienes* (https://comex.indec.gob.ar). Monthly Argentine exports of natural honey,
NCM 04090000 (the only 8-digit honey line of the Mercosur nomenclature, "Miel natural"), by country of
destination: FOB value in USD and net weight in kg, as INDEC publishes them with its monthly trade
release (ICA, *Intercambio comercial argentino*), about 20 days after the month.

Route (checked live on 2026-11-05)
----------------------------------
INDEC's query system is a JavaScript application; its own back end answers keyless JSON at
``https://comexbe.indec.gob.ar/public-api`` (``Access-Control-Allow-Origin: *``, no login, no captcha).
INDEC's site licenses its material under Creative Commons BY-SA 4.0; nothing forbids automated use. The
endpoints are not a documented API, so every answer is checked (below). Per data year, two requests:

* ``search/?commerceType=export&year=Y&period=month&countryQuery=allCountries&products=["04090000"]
  &countries=[]``: one row per destination and month (``country`` {id, iso2, name}, ``month``,
  ``amount`` = FOB USD, ``weight`` = net kg, ``isConfidential``);
* the same with ``countryQuery=totalImported`` (the value INDEC's form also sends for "Total exportado"):
  INDEC's own monthly total, stored as partner ``WLD``.

``staticData`` (about 9 KB) gives the newest month loaded (``lastYear``/``lastMonth``) and, per year,
the "Última fecha de actualización" INDEC prints under every result (``yearsStatus[].export``).

What is stored
--------------
* One trade row per destination-month (reporter ARG, partner ISO3, flow export, FOB USD, net kg,
  frequency M), the published monthly total (partner WLD) and, when at least
  ``MIN_UNIT_VALUE_WEIGHT_KG`` was shipped, an EXPORT_UNIT_VALUE price row (FOB USD / net kg, origin
  ARG, market = destination). No unit value for the world total (as for UN Comtrade).
* Statistical secrecy (Ley 17.622, art. 10). A destination-month with fewer than three exporters comes
  back with ``isConfidential: true`` and 0 / 0, which INDEC's own interface shows as "s". Such a cell
  is never stored (its 0 is not a zero). INDEC adds the masked trade to a "Confidencial" destination
  (code 999, ISO2 "ZZ") that is part of its total. It is kept in the WLD row's ``extra``
  (``confidential_bucket``), together with the list of masked destinations. Italy is masked in 28 of
  the 34 months of 2023-2026 with shipments to Italy. The total always equals the visible destinations
  plus that bucket; a month where INDEC's two answers disagree is not stored and is asked again at the
  next run.
* Bulk or packaged. Not distinguished: INDEC (and ARCA's files) publish only the 8-digit NCM. The
  customs SIM suffixes that separate bulk honey from retail packs are not published
  (``extra["bulk_packaged_split"] = None``).
* Destinations are mapped by the ISO alpha-2 code INDEC publishes, cross-checked against its Spanish
  name (a disagreement skips the row with a warning). INDEC's own codes for territories, groupings and
  "undetermined" destinations (QM-QZ, XA-XZ) are not countries: they stay in the total
  (``extra["not_allocated"]`` of the WLD row).

Status and dates
----------------
* ``published_at`` = INDEC's "Última fecha de actualización" of the year, as a Buenos Aires date
  (``yearsStatus``: 2026-10-16 for 2026 data on 2026-11-05; 2025-04-16 for 2024). A row whose figure
  is unchanged keeps the date of its first publication.
* ``data_status``: INDEC's comex system flags no row. The ICA (checked on the September 2026 report)
  marks the previous year "* Dato provisorio" and the current year as estimates ("e", because the ICA
  adds an estimate for pending customs documents; the comex database holds the registered operations
  only). So the newest data year and the one before are stored ``provisional``, earlier years
  ``published``. A change of status is stored as a revision (``services.ingest``).
* Every changed figure becomes a revision; a destination-month that a fresh answer no longer shows
  (revised away, or masked since) is withdrawn and kept in the history.

Requests and schedule
---------------------
Each run reads ``staticData`` (1 request). A year is pulled (2 requests) only when its update date
changed, its newest month moved, its status changes (a new data year starts), or the parser changed.
A byte-identical answer is not parsed again. Backfill: the newest data year and the three calendar
years before it (2023-01..2026-09 on 2026-11-05: 9 requests). INDEC releases around the 18th-20th
(its observed update dates fall on the 16th-20th): the check runs on weekdays from the 14th to the
28th, in the evening in Italy (after INDEC's 16:00 Buenos Aires release).

Cross-check (2026-11-05)
------------------------
UN Comtrade's Argentina 2024 total (78,375 t, USD 170.8 M; the same figure FAOSTAT shows) equals the
sum of INDEC's VISIBLE destinations (78,375.3 t, USD 170,816,007.85): Comtrade leaves out INDEC's
"Confidencial" bucket (7,360.7 t, USD 15.5 M). INDEC's total is 85,736.0 t, USD 186.3 M. Same in 2025
(Comtrade 81,819.5 t; INDEC 90,614.3 t with 8,794.8 t confidential). Comtrade's 2023 figures predate
INDEC's revision of April 2026.

Routes not used
---------------
* ARCA (ex-AFIP) customs, "Información agregada de comercio exterior", monthly ZIP (www.arca.gob.ar
  resets connections from the development network; the www.afip.gob.ar mirror answers). Fresher (the
  October 2026 file was online on 2026-11-05), but each month is a 157 MB download, almost all of it a
  5.6 GB import file, to read a 1 MB export file. It counts declarations by registration date
  ("oficialización"), not shipments. Its destination detail also drops small groups: October 2026 shows
  3,693 t by destination out of a 5,795 t total. Its NCM is 8-digit too. A later option is a "flash"
  monthly total read from the first member of the ZIP (``total_expo_agregado_YYYYMM.lst``) while
  streaming.
* datos.gob.ar series ``75.3_IEM_0_M_22`` ("Exportaciones de miel", USD million): value only, no
  weight and no destination; its API answered ``count: 0`` on 2026-11-05, and the CSV distribution
  mixes release vintages.
* SAGyP honey bulletins (alimentosargentinos.magyp.gob.ar: HTTP 403 from here): irregular PDFs that
  republish INDEC. They could serve as secondary checks only.

Producer prices: ``ar_inta_honey_prices`` is NOT built
-----------------------------------------------------
INTA PROAPI's "Monitoreo de Precios de la Miel" (bulk honey prices received by producers, ARS/kg, export
drums vs domestic market, light vs dark since January 2024, by region) is published as PDF reports in
INTA's DSpace repository. It was not integrated because:

* ``repositorio.inta.gob.ar`` and ``inta.gob.ar`` reset every connection from the development network
  (2026-11-05). No real report could be captured, so its table layout could not be checked. A PDF
  parser written blind would guess, which the data rules forbid.
* The newest issue that web search finds is no. 19, the survey of the first ten days of January 2026
  (handle 20.500.12123/24990), after September and November 2025. Nothing later was found by November
  2026, so the series cannot be confirmed as current.
* SAGyP's "Monitor SIM" (https://magyp.gob.ar/monitorpreciosmiel, the weekly reference price paid to
  producers, ARS/kg excluding VAT and freight, light and dark honey) was checked live. Its API has two
  points for 2025 (second half of February: 2,025 ARS/kg light, 1,750 dark; second half of March:
  2,050 / 1,750) and none for 2026: discontinued.

To integrate the INTA series, the collector must run on a network that reaches repositorio.inta.gob.ar.
It must then capture a real report, verify the table layout, and read only the cells it can read
unambiguously.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, timedelta, timezone
from typing import Any

from dateutil.parser import isoparse

from ..enums import DataStatus, PriceType, Reliability, SourceKind, TradeFlow, Variety
from ..models import PriceObservation, utcnow
from ..reference.countries import AGGREGATES, country_name, lookup_iso3
from .base import CollectContext, Collector, CollectorError, FetchResult, month_bounds
from .trade_official import (
    MIN_UNIT_VALUE_WEIGHT_KG,
    _has_rows,
    _load_json,
    _load_state,
    _norm_name,
    _num,
    _retire_absent,
    _save_state,
    _warn_once,
    resolve_country_name,
)

log = logging.getLogger(__name__)

INDEC_API = "https://comexbe.indec.gob.ar/public-api"
INDEC_STATIC_URL = f"{INDEC_API}/staticData"
INDEC_SEARCH_URL = f"{INDEC_API}/search/"
INDEC_WEB_UI = "https://comex.indec.gob.ar/#/search"
JSON_HEADERS = {"Accept": "application/json"}

HONEY_NCM = "04090000"
COMMERCE_TYPE = "export"
QUERY_BY_DESTINATION = "allCountries"
QUERY_TOTAL = "totalImported"          # INDEC's form sends this value for "Total exportado" too
# The newest data year and this many calendar years before it.
BACKFILL_YEARS = 3
# Bumped whenever the parsing changes: answers already stored are then read again once.
PARSER_VERSION = 1

CONFIDENTIAL_CODE = "999"
CONFIDENTIAL_ISO2 = "ZZ"
# ISO 3166 user-assigned alpha-2 ranges: INDEC uses them for territories, groupings and
# "undetermined" destinations (e.g. QT "Territorios vinculados a Francia (América)", XK = territories
# linked to the USA in Oceania, not Kosovo). Never a country.
_USER_ASSIGNED_ISO2 = re.compile(r"(AA|Q[M-Z]|X[A-Z]|ZZ)")
# Argentina has used UTC-3 all year since 2009: INDEC's timestamps are Buenos Aires midnights.
_ART = timezone(timedelta(hours=-3))
# Tolerance of the "destinations + confidential bucket = INDEC total" check (sums of 2-decimal USD
# and 3-decimal kg figures; seen live: identical to 1e-8).
_SUM_TOLERANCE = 0.5

STATUS_BASIS = ("INDEC flags no row. Its ICA release marks the previous year '* dato provisorio' and the "
                "current year as estimates: both newest data years are stored as provisional, earlier "
                "years as published")
BULK_PACKAGED_NOTE = ("INDEC publishes the 8-digit NCM only: bulk and packaged honey are not separated "
                      "(the customs SIM suffixes are not published)")


# ===========================================================================
# Pure helpers (tested directly)
# ===========================================================================


@dataclass(frozen=True)
class IndecRelease:
    """What `staticData` says about the export data loaded in INDEC's system."""

    last_year: int
    last_month: int
    updates_raw: dict[int, str]             # year -> "Última fecha de actualización" as published
    updates: dict[int, date | None]         # the same as a Buenos Aires date

    @property
    def latest_label(self) -> str:
        return f"{self.last_year:04d}-{self.last_month:02d}"

    @property
    def signature(self) -> str:
        return f"{self.latest_label}|{self.updates_raw.get(self.last_year, '')}"


def indec_date(raw: Any) -> date | None:
    """INDEC's update timestamp ("2026-10-16T03:00:00.000Z") as a Buenos Aires date, else None."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        dt = isoparse(raw.strip())
    except (ValueError, OverflowError):
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(_ART)
    return dt.date()


def _int(v: Any) -> int | None:
    f = _num(v)
    return int(f) if f is not None and f == int(f) else None


def parse_static_data(content: bytes) -> IndecRelease:
    """`GET /public-api/staticData`: newest month loaded and the export update date of each year.
    Fails loudly when the keys the collector relies on are gone."""
    doc = _load_json(content, "INDEC staticData")
    if not isinstance(doc, dict):
        raise CollectorError(f"INDEC staticData: expected an object, got {type(doc).__name__} (format changed?)")
    year, month = _int(doc.get("lastYear")), _int(doc.get("lastMonth"))
    status = doc.get("yearsStatus")
    missing = [k for k, ok in (("lastYear", year is not None and 2000 <= year <= 2100),
                               ("lastMonth", month is not None and 1 <= month <= 12),
                               ("yearsStatus", isinstance(status, list))) if not ok]
    if missing:
        raise CollectorError(f"INDEC staticData: {', '.join(missing)} missing or unreadable (keys: "
                             f"{sorted(doc)[:20]}); format changed?")
    raw: dict[int, str] = {}
    for item in status:
        if not isinstance(item, dict):
            continue
        y = _int(item.get("year"))
        exp = item.get("export")
        if y is not None and isinstance(exp, str):
            raw[y] = exp.strip()
    if not raw:
        raise CollectorError("INDEC staticData: yearsStatus has no year with an export update date (format changed?)")
    return IndecRelease(last_year=year, last_month=month, updates_raw=raw,
                        updates={y: indec_date(v) for y, v in raw.items()})


def indec_data_status(year: int, last_year: int) -> DataStatus:
    """Provisional for INDEC's newest data year and the one before (see the module docstring)."""
    return DataStatus.PROVISIONAL if year >= last_year - 1 else DataStatus.PUBLISHED


def search_params(year: int, query: str) -> dict[str, str]:
    """Query string of INDEC's search for honey exports of one year, by month."""
    return {"commerceType": COMMERCE_TYPE, "year": str(year), "period": "month", "countryQuery": query,
            "products": json.dumps([HONEY_NCM]), "countries": "[]"}


@dataclass
class IndecRow:
    month: int
    amount: float | None             # FOB USD (None on a masked or unreadable row)
    weight: float | None             # net kg
    confidential: bool = False
    country_id: str | None = None    # INDEC country code ("212"), destination rows only
    iso2: str | None = None
    name: str | None = None

    def label(self, year: int) -> str:
        return f"{year:04d}-{self.month:02d}"


@dataclass
class IndecParse:
    rows: list[IndecRow] = field(default_factory=list)       # visible rows with usable numbers
    masked: list[IndecRow] = field(default_factory=list)     # statistical secrecy ("s")
    bad: list[IndecRow] = field(default_factory=list)        # visible rows with unusable numbers
    problems: list[str] = field(default_factory=list)
    description: str | None = None                          # product description as published


def _flag(v: Any) -> bool:
    return v is True or v == 1 or (isinstance(v, str) and v.strip().lower() == "true")


def parse_indec_search(content: bytes, *, year: int, by_destination: bool) -> IndecParse:
    """Parse an INDEC `search` answer (honey exports of `year`, by month; by destination or total).

    Fails loudly (CollectorError) on an error answer, on schema drift (a required field gone from every
    row) and when a row is another product (the filter was ignored). A masked cell is kept apart, never
    as a zero. A visible row with unusable numbers, or 0 / 0 without INDEC's confidentiality flag (which
    could be a masked cell once the flag is gone), goes to `bad` with a problem."""
    what = "destination" if by_destination else "total"
    doc = _load_json(content, f"INDEC search ({what}, {year})")
    if isinstance(doc, dict):
        msg = doc.get("message") or doc.get("error") or doc
        raise CollectorError(f"INDEC search ({what}, {year}) answered an error: {str(msg)[:200]}")
    if not isinstance(doc, list):
        raise CollectorError(f"INDEC search ({what}, {year}): expected a list, got {type(doc).__name__}")
    out = IndecParse()
    if not doc:
        return out
    if not all(isinstance(r, dict) for r in doc):
        raise CollectorError(f"INDEC search ({what}, {year}): records are not objects (format changed?)")
    required = ("product", "month", "amount", "weight") + (("country",) if by_destination else ())
    missing = [k for k in required if not any(k in r for r in doc)]
    if by_destination and "country" not in missing and not any(
            isinstance(r.get("country"), dict) and "iso2" in r["country"] for r in doc):
        missing.append("country.iso2")
    if missing:
        raise CollectorError(f"INDEC schema drift ({what}, {year}): field(s) {missing} missing from the answer "
                             f"(fields: {sorted(set().union(*(r.keys() for r in doc)))[:20]}); nothing stored")
    if not by_destination and any("country" in r for r in doc):
        raise CollectorError(f"INDEC search (total, {year}) returned destination rows instead of the total; nothing stored")
    for i, r in enumerate(doc):
        product = r.get("product")
        pid = product.get("id") if isinstance(product, dict) else product
        digits = re.sub(r"\D", "", str(pid if pid is not None else ""))
        if digits.zfill(8) != HONEY_NCM:
            raise CollectorError(f"INDEC ignored the product filter (row {i} is {pid!r}, not {HONEY_NCM}); nothing stored")
        if out.description is None and isinstance(product, dict) and isinstance(product.get("description"), dict):
            out.description = product["description"].get("es") or None
        month = _int(r.get("month"))
        if month is None or not 1 <= month <= 12:
            out.problems.append(f"INDEC {year} row {i}: unreadable month {r.get('month')!r}; skipped")
            continue
        row = IndecRow(month=month, amount=None, weight=None, confidential=_flag(r.get("isConfidential")))
        if by_destination:
            c = r.get("country") if isinstance(r.get("country"), dict) else {}
            row.country_id = str(c.get("id")).strip() if c.get("id") not in (None, "") else None
            row.iso2 = str(c.get("iso2")).strip().upper() if c.get("iso2") not in (None, "") else None
            row.name = re.sub(r"\s+", " ", str(c.get("name"))).strip() if c.get("name") not in (None, "") else None
        who = f"{row.name or row.iso2 or row.country_id or 'total'}, {row.label(year)}"
        amount, weight = _num(r.get("amount")), _num(r.get("weight"))
        if row.confidential:
            if amount or weight:
                out.problems.append(f"INDEC {who}: marked confidential but carries numbers "
                                    f"({r.get('amount')!r} / {r.get('weight')!r}); ignored, as INDEC's own page does")
            out.masked.append(row)
            continue
        if amount is None or weight is None or amount < 0 or weight < 0:
            out.problems.append(f"INDEC {who}: unusable FOB={r.get('amount')!r} / kg={r.get('weight')!r}; not stored")
            out.bad.append(row)
            continue
        if amount == 0 and weight == 0:
            out.problems.append(f"INDEC {who}: 0 USD / 0 kg without the confidentiality flag; not stored")
            out.bad.append(row)
            continue
        row.amount, row.weight = round(amount, 2), round(weight, 3)
        out.rows.append(row)
    return out


def map_indec_country(code: Any, iso2: Any, name: Any) -> tuple[str | None, str]:
    """(ISO3 or None, how) for an INDEC destination. `how` is "iso2" (mapped), "confidential" (the
    999 bucket), "aggregate" (INDEC's codes for territories and groupings), "conflict" (the published
    name says another country) or "unknown"."""
    code = str(code or "").strip()
    iso2 = str(iso2 or "").strip().upper()
    norm = _norm_name(str(name or ""))
    if code == CONFIDENTIAL_CODE or iso2 == CONFIDENTIAL_ISO2 or norm == "confidencial":
        return None, "confidential"
    if not re.fullmatch(r"[A-Z]{2}", iso2):
        return None, "unknown"
    if _USER_ASSIGNED_ISO2.fullmatch(iso2):
        return None, "aggregate"
    iso3 = lookup_iso3(iso2)
    if iso3 is None or iso3 in AGGREGATES:
        return None, "unknown"
    by_name = resolve_country_name(name)
    if by_name is not None and by_name != iso3:
        return None, "conflict"
    return iso3, "iso2"


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(_SUM_TOLERANCE, 1e-7 * max(abs(a), abs(b)))


# ===========================================================================
# Collector
# ===========================================================================


@dataclass
class _DestAgg:
    iso3: str
    amount: float = 0.0
    weight: float = 0.0
    codes: list[str] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    iso2: list[str] = field(default_factory=list)


@dataclass
class _Year:
    """One pulled year: the two answers and what came out of them."""

    year: int
    status: DataStatus
    published: date | None
    published_raw: str
    by_dest: FetchResult
    total: FetchResult
    present: set[str] = field(default_factory=set)
    unsure: set[str] = field(default_factory=set)       # months not used to withdraw rows
    stored: set[str] = field(default_factory=set)       # months stored
    blocked: set[str] = field(default_factory=set)      # months not stored (inconsistent answers)


class ArIndecExportsCollector(Collector):
    key = "ar_official_exports"
    name = "Argentina – INDEC: esportazioni di miele per destinazione (NCM 04090000)"
    name_en = "Argentina – INDEC: honey exports by destination (NCM 04090000)"
    publisher = "INDEC – Instituto Nacional de Estadística y Censos (Argentina)"
    homepage = "https://comex.indec.gob.ar/#/search"
    kind = SourceKind.API
    reliability = Reliability.OFFICIAL
    category = "trade"
    country_iso3 = "ARG"
    language = "es"
    expected_update = "Mensile, verso il 20 del mese successivo (comunicato INDEC sull'interscambio, ICA)"
    expected_update_en = "Monthly, around the 20th of the following month (INDEC trade release, ICA)"
    expected_max_age_days = 40
    terms_note = ("Fonte: INDEC, Sistema de consulta de comercio exterior de bienes (material del sito INDEC "
                  "con licenza Creative Commons BY-SA 4.0: citare INDEC). FOB value in USD and net weight in "
                  "kg by destination, NCM 04090000 (bulk and packaged honey are not separated). Destinations "
                  "with fewer than three exporters are confidential (Ley 17.622) and appear only in the "
                  "total. The newest data year and the previous one are provisional and revised at every "
                  "release; each change is kept as a revision. Export unit values are derived (FOB / net kg), "
                  "not market quotations.")
    # Weekdays from the 14th to the 28th (INDEC releases around the 18th-20th), after INDEC's 16:00
    # Buenos Aires release; one 9 KB request when nothing is new (Europe/Rome time).
    schedule = {"trigger": "cron", "day": "14-28", "day_of_week": "mon-fri", "hour": 21, "minute": 35}

    def collect(self, ctx: CollectContext) -> None:
        state = _load_state(ctx)
        static = ctx.fetch(INDEC_STATIC_URL, headers=JSON_HEADERS, title="INDEC comex staticData (release dates)")
        release = parse_static_data(static.content)
        years = self._years_to_pull(ctx, state, release)
        for year in years:
            if self._pull_year(ctx, state, release, year):
                # Only a year stored completely is recorded: anything else is asked again next time.
                state.setdefault("years", {})[str(year)] = {
                    "update": release.updates_raw.get(year, ""),
                    "status": indec_data_status(year, release.last_year).value, "parser": PARSER_VERSION}
                if year == release.last_year:
                    state["latest_month"] = release.latest_label
            _save_state(ctx, state)
            ctx.checkpoint()
        state.update({"release": release.signature, "last_year": release.last_year,
                      "checked_at": utcnow().isoformat(timespec="seconds")})
        if years:
            state["pulled_at"] = utcnow().isoformat(timespec="seconds")
        else:
            log.info("[%s] INDEC release %s unchanged; nothing to pull", self.key, release.signature)
        _save_state(ctx, state)

    # ------------------------------------------------------------------ plan
    @staticmethod
    def _years_to_pull(ctx: CollectContext, state: dict, release: IndecRelease) -> list[int]:
        """Years of the window that need the two data requests, newest first: a new update date, a
        new newest month, a change of status (a new data year), a parser change, or an earlier pull
        that did not complete."""
        window = list(range(release.last_year - BACKFILL_YEARS, release.last_year + 1))
        if ctx.force or not _has_rows(ctx):
            return sorted(window, reverse=True)
        done = state.get("years") or {}
        todo = []
        for y in window:
            rec = done.get(str(y)) or {}
            if (rec.get("update") != release.updates_raw.get(y, "")
                    or rec.get("status") != indec_data_status(y, release.last_year).value
                    or rec.get("parser") != PARSER_VERSION
                    or (y == release.last_year and state.get("latest_month") != release.latest_label)):
                todo.append(y)
        return sorted(todo, reverse=True)

    # ------------------------------------------------------------------ data
    def _fetch(self, ctx: CollectContext, year: int, query: str) -> FetchResult:
        what = "by destination" if query == QUERY_BY_DESTINATION else "total"
        return ctx.fetch(INDEC_SEARCH_URL, params=search_params(year, query), headers=JSON_HEADERS,
                         title=f"INDEC honey exports NCM {HONEY_NCM} {year} by month, {what}")

    def _pull_year(self, ctx: CollectContext, state: dict, release: IndecRelease, year: int) -> bool:
        """Pull and store one year. False when something must be asked again at the next run."""
        status = indec_data_status(year, release.last_year)
        published_raw = release.updates_raw.get(year, "")
        published = release.updates.get(year)
        if published is None:
            _warn_once(ctx, state, f"no_update_date:{year}",
                       f"INDEC gives no readable update date for {year} ({published_raw!r}): rows of {year} are "
                       "stored without publication date")
        by_dest = self._fetch(ctx, year, QUERY_BY_DESTINATION)
        total = self._fetch(ctx, year, QUERY_TOTAL)
        rec = (state.get("years") or {}).get(str(year)) or {}
        reparse = ctx.force or rec.get("parser") != PARSER_VERSION or rec.get("status") != status.value
        if by_dest.unchanged and total.unchanged and not reparse:
            log.info("[%s] %s: same answers as already stored", self.key, year)
            return True
        dest = parse_indec_search(by_dest.content, year=year, by_destination=True)
        tot = parse_indec_search(total.content, year=year, by_destination=False)
        for p in dest.problems + tot.problems:
            ctx.warn(p)
        if not (dest.rows or dest.masked or dest.bad or tot.rows):
            ctx.warn(f"INDEC returned no honey export rows for {year}; asked again at the next run")
            return False
        y = _Year(year=year, status=status, published=published, published_raw=published_raw,
                  by_dest=by_dest, total=total)
        months = sorted({r.month for r in dest.rows + dest.masked + dest.bad + tot.rows + tot.masked + tot.bad})
        if year == release.last_year and months and months[-1] > release.last_month:
            late = [m for m in months if m > release.last_month]
            ctx.warn(f"INDEC returned {year} months {late} after its newest month {release.latest_label}; ignored")
            months = [m for m in months if m <= release.last_month]
        for m in months:
            self._store_month(ctx, state, y, dest, tot, m)
        gone = _retire_absent(ctx, prefix="indec|ARG|", months=y.stored - y.unsure, present=y.present,
                              price_key=lambda p, lab: f"{PriceType.EXPORT_UNIT_VALUE.value}|indec|{p}|ARG|{lab}")
        if gone:
            ctx.warn(f"INDEC no longer shows honey exports for {', '.join(gone)} (revised or now confidential): "
                     "those rows are withdrawn (kept in the history)")
        return not y.blocked

    def _store_month(self, ctx: CollectContext, state: dict, y: _Year, dest: IndecParse, tot: IndecParse,
                     month: int) -> None:
        label = f"{y.year:04d}-{month:02d}"
        visible = [r for r in dest.rows if r.month == month]
        masked = [r for r in dest.masked if r.month == month]
        bad = [r for r in dest.bad if r.month == month]
        totals = [r for r in tot.rows if r.month == month]
        total_masked = any(r.month == month for r in tot.masked)
        if len(totals) > 1 or any(r.month == month for r in tot.bad):
            ctx.warn(f"INDEC total for {label} is not one readable row; month not stored, asked again at the next run")
            y.blocked.add(label)
            return
        total = totals[0] if totals else None
        # INDEC's total = visible destinations + the confidential bucket (masked cells carry nothing).
        sum_check = "not possible (unreadable destination row)" if bad else (
            "not possible (total confidential)" if total_masked else "ok")
        if not bad and not total_masked:
            s_amount = sum(r.amount for r in visible)
            s_weight = sum(r.weight for r in visible)
            t_amount, t_weight = (total.amount, total.weight) if total else (0.0, 0.0)
            if not (_close(s_amount, t_amount) and _close(s_weight, t_weight)):
                ctx.warn(f"INDEC destinations of {label} add up to {s_amount:,.2f} USD / {s_weight:,.3f} kg but its "
                         f"total says {t_amount:,.2f} USD / {t_weight:,.3f} kg; month not stored, asked again at "
                         "the next run")
                y.blocked.add(label)
                return
        if bad:
            y.unsure.add(label)
        common = self._common(y, label)
        aggs: dict[str, _DestAgg] = {}
        bucket = {"fob_usd": 0.0, "kg": 0.0, "rows": 0}
        not_allocated: list[dict] = []
        masked_list: list[dict] = []
        masked_iso: set[str] = set()
        for r in masked:
            iso, how = map_indec_country(r.country_id, r.iso2, r.name)
            masked_list.append({"iso3": iso, "name": r.name, "indec_country_code": r.country_id, "iso2": r.iso2})
            if iso:
                masked_iso.add(iso)
        for r in visible:
            iso, how = map_indec_country(r.country_id, r.iso2, r.name)
            if how == "confidential":
                bucket["fob_usd"] += r.amount
                bucket["kg"] += r.weight
                bucket["rows"] += 1
                continue
            if iso is None:
                not_allocated.append({"name": r.name, "indec_country_code": r.country_id, "iso2": r.iso2,
                                      "fob_usd": r.amount, "kg": r.weight, "why": how})
                self._report_unmapped(ctx, state, r, how)
                if how != "aggregate":
                    y.unsure.add(label)
                continue
            agg = aggs.setdefault(iso, _DestAgg(iso))
            agg.amount += r.amount
            agg.weight += r.weight
            for lst, v in ((agg.codes, r.country_id), (agg.names, r.name), (agg.iso2, r.iso2)):
                if v and v not in lst:
                    lst.append(v)
        for r in bad:
            iso, _ = map_indec_country(r.country_id, r.iso2, r.name)
            if iso:
                aggs.pop(iso, None)               # a partial sum is never stored as the destination's figure
        stored = 0
        for iso in sorted(aggs):
            if iso in masked_iso:
                ctx.warn(f"INDEC shows {iso} {label} both masked and visible (two INDEC codes); not stored")
                y.unsure.add(label)
                continue
            y.present.add(self._store_destination(ctx, y, label, aggs[iso], common))
            stored += 1
        if total is not None and not total_masked:
            y.present.add(self._store_total(ctx, y, label, total, common, bucket=bucket, masked=masked_list,
                                            not_allocated=not_allocated, visible=stored, sum_check=sum_check))
        y.stored.add(label)

    def _report_unmapped(self, ctx: CollectContext, state: dict, r: IndecRow, how: str) -> None:
        label = f"{r.name or '?'} ({r.iso2 or '?'}, INDEC {r.country_id or '?'})"
        if how == "aggregate":
            _warn_once(ctx, state, f"aggregate:{r.country_id}:{r.iso2}",
                       f"INDEC destination {label} is a territory or grouping, not a country: kept only in the total")
            return
        state.setdefault("unknown_partners", {})[str(r.country_id)] = {"iso2": r.iso2, "name": r.name, "how": how}
        why = "its published name points to another country" if how == "conflict" else "it has no ISO3 mapping"
        _warn_once(ctx, state, f"partner:{r.country_id}:{r.iso2}:{how}",
                   f"INDEC destination {label}: {why}; its rows stay in the total only until trade_argentina "
                   "is checked")

    def _common(self, y: _Year, label: str) -> dict:
        p_start, p_end = month_bounds(y.year, int(label[5:]))
        return {"period_start": p_start, "period_end": p_end, "period_label": label, "frequency": "M",
                "published_at": y.published, "data_status": y.status, "reliability": Reliability.OFFICIAL}

    def _extra(self, y: _Year, query: str) -> dict:
        return {
            "ncm": HONEY_NCM, "ncm_description": "Miel natural",
            "indec_last_update": y.published.isoformat() if y.published else None,
            "indec_last_update_raw": y.published_raw or None,
            "status_basis": STATUS_BASIS,
            "bulk_packaged_split": None, "bulk_packaged_note": BULK_PACKAGED_NOTE,
            "query": {"commerceType": COMMERCE_TYPE, "year": y.year, "period": "month", "countryQuery": query,
                      "products": [HONEY_NCM]},
            "web_ui": INDEC_WEB_UI,
        }

    def _store_destination(self, ctx: CollectContext, y: _Year, label: str, agg: _DestAgg, common: dict) -> str:
        fob, kg = round(agg.amount, 2), round(agg.weight, 3)
        destination = country_name(agg.iso3, "en")
        if destination == agg.iso3:
            destination = agg.names[0] if agg.names else agg.iso3
        extra = {
            **self._extra(y, QUERY_BY_DESTINATION),
            "destination_name": agg.names[0] if len(agg.names) == 1 else agg.names,
            "indec_country_code": agg.codes[0] if len(agg.codes) == 1 else agg.codes,
            "indec_iso2": agg.iso2[0] if len(agg.iso2) == 1 else agg.iso2, "mapped_by": "iso2",
        }
        src = {"source_url": y.by_dest.url, "raw_document_id": y.by_dest.raw_document_id or None}
        series = f"indec|ARG|{agg.iso3}|export|{label}"
        ctx.add_trade(
            series_key=series, hs_code="0409", reporter_iso3="ARG", partner_iso3=agg.iso3,
            flow=TradeFlow.EXPORT.value, currency="USD", value=fob, net_weight_kg=kg, value_basis="FOB",
            extra=extra,
            notes=("Esportazioni argentine di miele naturale NCM 04090000 (INDEC, sistema di consulta del commercio "
                   "estero): valore FOB in USD e peso netto verso questa destinazione."),
            **src, **common,
        )
        price_series = f"indec|{agg.iso3}|ARG|{label}"
        if kg >= MIN_UNIT_VALUE_WEIGHT_KG and fob > 0:
            ctx.add_price(
                series_key=price_series, price_type=PriceType.EXPORT_UNIT_VALUE, variety=Variety.UNSPECIFIED.value,
                price_value=round(fob / kg, 4), currency="USD", unit="kg", origin_iso3="ARG",
                origin_label="Argentina", market_iso3=agg.iso3, market_location=destination, terms="FOB",
                variety_raw="NCM 04090000 Miel natural (bulk and packaged together)", volume_kg=kg,
                notes=("Valore unitario all'esportazione = valore FOB / peso netto (INDEC, NCM 04090000). "
                       "Dato doganale derivato, non una quotazione di mercato."),
                extra={**extra, "fob_usd": fob, "kg": kg}, **src, **common,
            )
        else:
            # A revision can push a flow below the threshold: its earlier unit value is withdrawn.
            ctx.retire(PriceObservation, f"{PriceType.EXPORT_UNIT_VALUE.value}|{price_series}")
        return series

    def _store_total(self, ctx: CollectContext, y: _Year, label: str, total: IndecRow, common: dict, *,
                     bucket: dict, masked: list[dict], not_allocated: list[dict], visible: int,
                     sum_check: str) -> str:
        extra = {
            **self._extra(y, QUERY_TOTAL),
            "total_of": "all destinations, including those under statistical secrecy",
            "confidential_bucket": ({"fob_usd": round(bucket["fob_usd"], 2), "kg": round(bucket["kg"], 3),
                                     "indec_country_code": CONFIDENTIAL_CODE} if bucket["rows"] else None),
            "masked_destinations": masked or None,
            "not_allocated": not_allocated or None,
            "visible_destinations": visible,
            "sum_check": sum_check,
        }
        series = f"indec|ARG|WLD|export|{label}"
        ctx.add_trade(
            series_key=series, hs_code="0409", reporter_iso3="ARG", partner_iso3="WLD",
            flow=TradeFlow.EXPORT.value, currency="USD", value=total.amount, net_weight_kg=total.weight,
            value_basis="FOB", extra=extra, source_url=y.total.url, raw_document_id=y.total.raw_document_id or None,
            notes=("Totale delle esportazioni argentine di miele NCM 04090000 pubblicato da INDEC: tutte le "
                   "destinazioni, comprese quelle coperte dal segreto statistico (dettaglio in 'extra')."),
            **common,
        )
        return series


__all__ = [
    "ArIndecExportsCollector",
    "IndecParse",
    "IndecRelease",
    "IndecRow",
    "indec_data_status",
    "indec_date",
    "map_indec_country",
    "parse_indec_search",
    "parse_static_data",
    "search_params",
]
