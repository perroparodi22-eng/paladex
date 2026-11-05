"""Ukraine and Mexico, official honey exports by destination. Two collectors.

``ua_honey_exports``: Ukraine, **State Customs Service of Ukraine** (Держмитслужба), open dataset
"Знеособлена зведена інформація для статистичних цілей (англ)" on the national open-data portal
(https://data.gov.ua/dataset/scsu-bi-trade-src-en, CC BY 4.0, updated monthly). One gzipped CSV per
month (``BI_trade_YYYY-MM_EN``, ~10-11 MB, ~160,000 rows: every UKTZED code by partner country,
customs office and country of origin). Honey is UKTZED 0409 00 00 00 ("Natural honey", one 10-digit
line). Stored: monthly exports by destination, **customs value in USD and net kg** as published.

``mx_honey_exports``: Mexico, **INEGI** (with SAT, SE and Banxico), *Balanza Comercial de Mercancías
de México* (BCMM, Información de Interés Nacional), monthly OLAP cube "Balanza Comercial de
Mercancías de México Mensual (enero 2023 - ...)". Honey is fracción 0409.00.01 "Miel natural" (unit
of the tariff: kg; the only fracción of heading 04.09, NICO 00). Stored: monthly exports by country
of last known destination, **FOB value in USD and quantity in kg**, as published.

Routes (checked live on 2026-11-05)
-----------------------------------
Ukraine. ``GET data.gov.ua/api/3/action/package_show?id=scsu-bi-trade-src-en`` (CKAN, ~100 KB) lists
the monthly files with ``last_modified``, ``size`` and ``file_hash_sum`` (the MD5 of the .gz for the
2024-2026 files; the 2023 files' listed hashes match neither the .gz nor the CSV, their sizes do). A
download must have the listed size; its gzip CRC-32 is verified on decompression; an MD5 mismatch is
reported once. A month is downloaded only when its file changed (new resource id or hash), the parser
changed, its status changes or the run is forced. Only the header and the honey rows of each file are archived
(``ctx.store_raw``), never the 10 MB file. The customs service re-uploads files (2024-01..2026-05
re-published on 2026-10-28/29, 2026-06..2026-10 on 2026-11-03), so after the backfill at most
``UA_MAX_DOWNLOADS_PER_RUN`` changed files are read per run, newest first; the rest follow at the
next runs (a forced run re-reads every file of the window, 480 MB). The newest file is fresh: 2026-10
was online on 2026-11-03.

Rejected for Ukraine:
* State Statistics Service (Держстат, ukrstat.gov.ua / stat.gov.ua): during martial law its foreign
  trade releases by country and product have been postponed repeatedly (Law 2115-IX allows not
  publishing statistics whose quality cannot be ensured), and www.ukrstat.gov.ua serves an expired
  TLS certificate (verification fails; not worked around). Its official figures (customs data plus
  adjustments) can differ from the customs dataset.
* customs.gov.ua and its BI portal bi.customs.gov.ua answer "Access Denied" (Akamai, HTTP 403) from
  outside Ukraine: not worked around. The open-data files above are the same customs statistics.

Mexico. INEGI's "Consulta interactiva de datos" (the OLAP cube viewer, ASP pages under
``/sistemas/olap/``): no login, no captcha; INEGI's terms of free use ("Términos de libre uso de la
información del INEGI") allow reuse, including commercial, with attribution. The viewer is not a
documented API: the collector sends the same form fields the viewer's own JavaScript (CubeBrowser.js)
sends, an MDX axis expression in ``rows``, and reads the HTML result table; every answer is checked
(below). Per run:

* ``GET .../comex_bcmm_mensual2023.asp`` (25 KB): the cube's period ("enero 2023 - agosto 2026"), its
  status note ("Cifras ajustadas de enero 2023 a diciembre 2025, a partir de enero 2026 datos
  revisados") and the cube's server / database / name. Nothing else is requested when these are
  unchanged.
* When they change: per data year, ``POST .../MDXQueryDatos.asp`` with rows =
  ``CrossJoin({honey 0409.00.01}, {Exportaciones}, {[Año].&[Y]}, {[Mes].Members}, {Total + every
  country})`` and columns = ``{[Measures].AllMembers}`` ("Valor Total" USD, "Cantidad total" in the
  tariff unit), slicer US dollars. The viewer shows 33 rows a page: 4-5 pages a year (~57 KB each).
  The answer echoes the MDX it ran (``Lc_sql``): it must be exactly the query sent, every row must
  read "04.09.0001 (Kg) Miel natural." / "Exportaciones" / the year asked, and the rows read must
  equal the row count the viewer announces. Anything else fails loudly or leaves the year to the
  next run. INEGI's own CSV export (``/sistemas/olap/exporta/exporta.aspx``) answered a server error
  ("Index was outside the bounds of the array") even for the viewer's own form: not used.

Rejected for Mexico:
* SIAVI (Secretaría de Economía, economia-snci.gob.mx): discontinued; the host has no DNS address
  (updates suspended since 2022-2023 per the SNIEG trade committee minutes).
* Data México (SE): the API moved to https://www.economia.gob.mx/apidatamexico/tesseract/ (the old
  api.datamexico.org no longer resolves). Its foreign-trade cubes give value only (no weight) and
  stop at HS6, so no unit value: not used (it could cross-check values).

What is stored (both)
---------------------
* One trade row per destination-month: reporter UKR / MEX, partner ISO3, flow export, value USD, net
  kg, frequency M, ``data_status`` as below. Partner ``WLD``: Ukraine = the sum of every honey export
  row of the file (the dataset has no total record; unspecified partners included); Mexico = INEGI's
  published "Total" row.
* EXPORT_UNIT_VALUE (USD/kg, origin UKR/MEX, market = destination) when at least
  ``MIN_UNIT_VALUE_WEIGHT_KG`` was shipped. None for the world total.
* Every changed figure is a new revision; a destination-month a fresh answer no longer shows is
  withdrawn (kept in the history).

Ukraine specifics
-----------------
* Values: "Export USD" (customs value as declared; the dataset gives no FOB/CIF basis), "Netto kg".
  Rows are summed over customs offices and countries of origin (``State of origin``); exports of
  goods of non-Ukrainian origin (re-exports) are included, as in Ukraine's total, and kept apart in
  ``extra["non_ukrainian_origin"]``.
* A file row carries ONE net weight for imports and exports together. When a row has both flows
  (1 honey row in 2026-09: Poland, Khmelnytskyi office), the export weight is "Netto kg" minus the
  import weight, read from "Taxed import kg" ONLY when "Taxed import USD" equals "Import USD" (all of
  the row's imports are taxed, so their weight is known); otherwise the export weight is unknown
  (never guessed), the partner-month and the WLD row carry no weight and no unit value is derived.
  ``extra["kg_basis"]`` says which applies.
* Partners: ISO alpha-2 + English name as published ("PL Poland"), cross-checked against each other;
  "nan" / "Unspecified" stay in the total (``extra["not_allocated"]``).
* Status: the customs service marks no status and re-publishes the files of the current and previous
  years; the newest data year and the year before are stored ``provisional``, earlier years
  ``published``. ``published_at`` = the file's ``last_modified`` date on data.gov.ua (the version
  read).

Mexico specifics
----------------
* Confidentiality (LSNIEG arts. 37-38): a cell with one or two exporters shows "C" for value and
  quantity. It is never stored (a "C" is not a zero). INEGI's Total includes the masked trade:
  ``extra`` of the WLD row lists the masked destinations and the masked part (Total minus the visible
  destinations). Exports to the USA are masked in some months, e.g. 2025-02.
* Destinations are mapped from INEGI's Spanish names (the rows carry no codes); INEGI's groupings
  ("Europa", "Países no identificados", ...) stay in the total only.
* Status: the cube says which months carry "cifras ajustadas" (adjusted after INEGI's annual revision:
  stored ``published``) and from which month "datos revisados" (revised monthly: ``provisional``).
  ``published_at``: the cube shows no date, so none is stored.

Schedules
---------
Ukraine: Mon/Wed/Fri from the 2nd to the 14th, 10:17 Rome (the file of month M appeared on the 3rd of
M+1 in Nov 2026); 1 request (~100 KB) when no file changed. Mexico: weekdays from the 5th to the
25th, 16:43 Rome; 1 request (25 KB) when the cube did not change, otherwise ~4 pages per year to
re-read (the provisional year at a monthly update, every year when the adjusted range moves).

Cost: Ukraine's backfill (2023-01..2026-10) is 46 files, 480 MB, ~3 minutes (2 s of parsing a
file); the archive keeps 47 documents, 0.9 MB. Mexico's is 18 requests, 0.9 MB, ~100 s (INEGI answers
a page in ~5 s).

Cross-checks (2026-11-05, figures already in the database)
---------------------------------------------------------
* Ukraine vs UN Comtrade (Ukraine's own report): 2023 55,357.2 t / USD 121.38 M and 2024 85,812.3 t /
  USD 166.95 M against Comtrade 55,357.2 t / 121.38 M and 85,812.3 t / 166.95 M: identical (same
  customs base; within 16 kg and USD 634). 2025: 50,317.6 t / USD 125.44 M (not in Comtrade yet).
* Ukraine vs Eurostat (EU27 imports from UKR): exports to EU27 51,659 / 71,187 / 44,761 t (2023 /
  2024 / 2025) against Eurostat 45,817 / 54,019 / 53,296 t. The year-to-year shift (2024 above, 2025
  below) fits honey entering EU customs warehouses in 2024 and released for free circulation in 2025
  (the EU records extra-EU imports at release; Ukrainian honey has had a tariff-rate quota under the
  EU's trade measures since June 2024). Not verified: shown, not resolved.
* Ukraine vs US Census (imports from UKR): 2024 12,125 t against 12,273 t; 2025 2,994 t against 6,284 t
  (the US records the country of ORIGIN, Ukraine declares the DESTINATION: Ukrainian honey reaching the
  US through EU packers counts as an EU export here).
* Mexico vs UN Comtrade: Comtrade equals INEGI's VISIBLE destinations to the dollar (2023 USD 53.83 M /
  17,755.6 t; 2024 47.45 M / 15,303.7 t; 2025 65.92 M / 21,234.0 t): it leaves out INEGI's confidential
  cells, which INEGI's Total includes: 67.76 M / 22,337.8 t, 59.36 M / 19,641.2 t, 79.62 M / 25,906.7 t
  (about 4,300-4,700 t a year, ~20 %). Same pattern as Argentina's INDEC.
* Mexico vs US Census (imports from MEX): 2024 6,794 t (12 visible months) against 6,722 t; 2025
  7,727 t in 11 visible months (February masked) against 8,214 t.
* Mexico vs Eurostat: exports to Germany 7,695 t (2023, 11 visible months) / 4,855 t (2024) against
  Eurostat 7,738 / 5,078 t; 2025 8,161 t against Eurostat 5,407 t but Germany's own report to Comtrade
  7,900 t.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import html as html_lib
import io
import logging
import re
import zlib
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from dateutil.parser import isoparse

from ..enums import DataStatus, PriceType, Reliability, SourceKind, TradeFlow, Variety
from ..models import PriceObservation, utcnow
from ..reference.countries import AGGREGATES, country_name, lookup_iso3
from .base import (
    CollectContext,
    Collector,
    CollectorError,
    FetchResult,
    Offline,
    month_bounds,
)
from .trade_official import (
    MIN_UNIT_VALUE_WEIGHT_KG,
    Month,
    _has_rows,
    _load_json,
    _load_state,
    _norm_name,
    _num,
    _retire_absent,
    _save_state,
    _warn_once,
    month_label,
    resolve_country_name,
)
from .trade_uruguay_chile import resolve_es_country

log = logging.getLogger(__name__)

# ===========================================================================
# 1) Ukraine: State Customs Service open data (data.gov.ua)
# ===========================================================================

UA_PACKAGE_ID = "scsu-bi-trade-src-en"
UA_PACKAGE_URL = "https://data.gov.ua/api/3/action/package_show"
UA_DATASET_PAGE = f"https://data.gov.ua/dataset/{UA_PACKAGE_ID}"
UA_RESOURCE_RE = re.compile(r"BI_trade_(\d{4})-(\d{2})_EN")
UA_HONEY_CODE = "0409000000"
UA_BACKFILL_YEARS = 3                 # the newest data year and this many calendar years before it
UA_MAX_DOWNLOADS_PER_RUN = 12         # changed files read per run once the backfill is done
UA_MAX_FILE_BYTES = 80 * 1024 ** 2
UA_PARSER_VERSION = 1
# Columns the parser relies on (the file has 43).
UA_COLUMNS = ("Year", "Month", "State", "State of origin", "Customs", "HS Code 2", "HS Code 4", "HS Code 10",
              "Import USD", "Export USD", "Netto kg", "Taxed import USD", "Taxed import kg")
_UA_UNSPECIFIED = frozenset({"", "nan", "unspecified", "unknown"})

UA_STATUS_BASIS = ("The customs service marks no status and re-publishes the monthly files of the current and "
                   "previous years: the newest data year and the year before are stored as provisional, earlier "
                   "years as published")
UA_TOTAL_BASIS = ("sum of every honey export row of the month's file (all partners, customs offices and countries "
                  "of origin, unspecified partners included); the dataset has no separate total record")
UA_KG_NOTE = ("A file row has one net weight for imports and exports together. On a row with both flows the export "
              "weight is net kg minus 'Taxed import kg', only when 'Taxed import USD' equals 'Import USD'; "
              "otherwise it is unknown")


@dataclass(frozen=True)
class UaResource:
    month: Month
    resource_id: str
    name: str
    url: str
    last_modified: str            # as published (data.gov.ua, ISO timestamp)
    modified: date | None
    md5: str | None
    size: int | None

    @property
    def label(self) -> str:
        return month_label(self.month)

    @property
    def signature(self) -> str:
        return f"{self.resource_id}|{self.md5 or self.last_modified}"


def _ua_date(raw: Any) -> date | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return isoparse(raw.strip()).date()
    except (ValueError, OverflowError):
        return None


def parse_ua_package(content: bytes) -> tuple[dict[Month, UaResource], list[str]]:
    """CKAN ``package_show``: the monthly EN files by month (the newest upload when a month is listed
    twice) and notes about duplicates. Fails loudly when the answer or the file naming changed."""
    doc = _load_json(content, "data.gov.ua package_show")
    if not isinstance(doc, dict) or doc.get("success") is not True or not isinstance(doc.get("result"), dict):
        raise CollectorError(f"data.gov.ua package_show: unexpected answer ({str(doc)[:160]!r}); dataset gone?")
    res = doc["result"].get("resources")
    if not isinstance(res, list):
        raise CollectorError("data.gov.ua package_show: no 'resources' list (format changed?)")
    out: dict[Month, UaResource] = {}
    notes: list[str] = []
    for r in res:
        if not isinstance(r, dict):
            continue
        m = UA_RESOURCE_RE.fullmatch(str(r.get("name") or "").strip())
        if not m or not 1 <= int(m.group(2)) <= 12:
            continue
        url = str(r.get("url") or "").strip()
        if not url.startswith("https://"):
            notes.append(f"{r.get('name')}: no https download URL ({url[:80]!r}); ignored")
            continue
        md5 = str(r.get("file_hash_sum") or "").strip().lower()
        size = r.get("size")
        item = UaResource(month=(int(m.group(1)), int(m.group(2))), resource_id=str(r.get("id") or ""),
                          name=str(r.get("name")), url=url, last_modified=str(r.get("last_modified") or r.get("created") or ""),
                          modified=_ua_date(r.get("last_modified") or r.get("created")),
                          md5=md5 if re.fullmatch(r"[0-9a-f]{32}", md5) else None,
                          size=int(size) if isinstance(size, int) else None)
        prev = out.get(item.month)
        if prev is not None:
            keep, drop = (item, prev) if item.last_modified > prev.last_modified else (prev, item)
            notes.append(f"{item.name} is listed twice (resources {keep.resource_id} and {drop.resource_id}); "
                         f"the newest upload ({keep.last_modified[:10]}) is read")
            item = keep
        out[item.month] = item
    if not out:
        raise CollectorError("data.gov.ua package_show: no BI_trade_YYYY-MM_EN file found (naming changed?)")
    return out, notes


def ua_window(latest: Month) -> tuple[Month, Month]:
    return (latest[0] - UA_BACKFILL_YEARS, 1), latest


def ua_data_status(year: int, latest_year: int) -> DataStatus:
    return DataStatus.PROVISIONAL if year >= latest_year - 1 else DataStatus.PUBLISHED


def _ua_digits(v: Any) -> str | None:
    """A code as published ("4.0", "409000000.0", "0409000000") without its decimal part."""
    s = str(v or "").strip()
    if re.fullmatch(r"\d+(\.0+)?", s):
        return s.split(".")[0].lstrip("0") or "0"
    return None


@dataclass
class UaRow:
    partner: str                     # as published ("PL Poland")
    origin: str
    customs: str
    export_usd: float
    kg: float | None                 # export net kg (None when it cannot be told apart from imports)
    kg_basis: str                    # "netto" | "netto_minus_taxed_import" | "unknown_mixed_row"
    code: str                        # UKTZED code as published, 10 digits


@dataclass
class UaParse:
    rows: list[UaRow] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    extract: bytes = b""             # header + every honey row (both flows), CSV, for the archive
    honey_rows: int = 0
    import_rows: int = 0
    total_rows: int = 0


def parse_ua_month(gz: bytes, month: Month) -> UaParse:
    """One monthly file (gzipped CSV): its honey export rows. Fails loudly when the file is not a
    gzipped CSV of the expected layout or is another month."""
    try:
        text = gzip.decompress(gz).decode("utf-8-sig")
    except (OSError, EOFError, zlib.error) as exc:
        raise CollectorError(f"customs file {month_label(month)}: not a gzip file ({exc})") from exc
    except UnicodeDecodeError as exc:
        raise CollectorError(f"customs file {month_label(month)}: not UTF-8 text ({exc})") from exc
    reader = csv.reader(io.StringIO(text, newline=""))
    header = next(reader, None)
    if not header:
        raise CollectorError(f"customs file {month_label(month)}: empty")
    header = [h.strip() for h in header]
    missing = [c for c in UA_COLUMNS if c not in header]
    if missing:
        raise CollectorError(f"customs file schema drift ({month_label(month)}): column(s) {missing} missing "
                             f"(columns: {header[:20]}); nothing stored")
    ix = {c: header.index(c) for c in UA_COLUMNS}
    width = len(header)
    out = UaParse()
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    other_month = 0
    for row in reader:
        out.total_rows += 1
        if len(row) != width:
            if any("409" in c for c in row):
                out.problems.append(f"customs file {month_label(month)} row {out.total_rows}: {len(row)} fields "
                                    f"instead of {width}; skipped")
            continue
        if _ua_digits(row[ix["HS Code 2"]]) != "4":
            continue
        hs4 = _ua_digits(row[ix["HS Code 4"]]) or ""
        if not hs4.startswith("409"):
            continue
        code = (_ua_digits(row[ix["HS Code 10"]]) or "").zfill(10)
        if not code.startswith("0409"):
            out.problems.append(f"customs file {month_label(month)}: honey row with UKTZED {row[ix['HS Code 10']]!r}; skipped")
            continue
        writer.writerow(row)
        out.honey_rows += 1
        if (_num(row[ix["Year"]]), _num(row[ix["Month"]])) != (float(month[0]), float(month[1])):
            other_month += 1
            continue
        exp, imp = _num(row[ix["Export USD"]]), _num(row[ix["Import USD"]])
        kg = _num(row[ix["Netto kg"]])
        partner = re.sub(r"\s+", " ", row[ix["State"]]).strip()
        if exp is None or imp is None or kg is None or exp < 0 or imp < 0 or kg < 0:
            out.problems.append(f"customs {month_label(month)} {partner}: unusable Export USD / Import USD / Netto kg "
                                f"({row[ix['Export USD']]!r} / {row[ix['Import USD']]!r} / {row[ix['Netto kg']]!r}); "
                                "not stored")
            out.rows.append(UaRow(partner, "", "", float("nan"), None, "unusable", code))
            continue
        if imp > 0:
            out.import_rows += 1
        if exp <= 0:
            continue
        if imp == 0:
            ekg, basis = kg, "netto"
        else:
            t_usd, t_kg = _num(row[ix["Taxed import USD"]]), _num(row[ix["Taxed import kg"]])
            if t_usd is not None and t_kg is not None and abs(t_usd - imp) <= 0.01 and 0 <= t_kg <= kg:
                ekg, basis = kg - t_kg, "netto_minus_taxed_import"
            else:
                ekg, basis = None, "unknown_mixed_row"
        out.rows.append(UaRow(partner=partner, origin=re.sub(r"\s+", " ", row[ix["State of origin"]]).strip(),
                              customs=re.sub(r"\s+", " ", row[ix["Customs"]]).strip(), export_usd=exp,
                              kg=ekg, kg_basis=basis, code=code))
    if other_month and other_month == out.honey_rows:
        raise CollectorError(f"customs file {month_label(month)} holds another month's rows; nothing stored")
    if other_month:
        out.problems.append(f"customs file {month_label(month)}: {other_month} honey row(s) of another month; skipped")
    out.extract = buf.getvalue().encode("utf-8")
    return out


def map_ua_partner(raw: Any) -> tuple[str | None, str]:
    """(ISO3 or None, how) for a partner as published ("PL Poland"). `how`: "iso2", "unspecified",
    "conflict" (the name says another country) or "unknown"."""
    s = re.sub(r"\s+", " ", str(raw or "")).strip()
    if s.lower() in _UA_UNSPECIFIED:
        return None, "unspecified"
    m = re.fullmatch(r"([A-Z]{2}) (.+)", s)
    if not m:
        return None, "unknown"
    iso3 = lookup_iso3(m.group(1))
    if iso3 is None or iso3 in AGGREGATES:
        return None, "unknown"
    by_name = resolve_country_name(m.group(2))
    if by_name is not None and by_name != iso3:
        return None, "conflict"
    return iso3, "iso2"


@dataclass
class _UaAgg:
    iso3: str
    usd: float = 0.0
    kg: float | None = 0.0
    rows: int = 0
    names: list[str] = field(default_factory=list)
    customs: set[str] = field(default_factory=set)
    bases: set[str] = field(default_factory=set)
    foreign_usd: float = 0.0
    foreign_kg: float | None = 0.0

    def add(self, r: UaRow) -> None:
        self.usd += r.export_usd
        self.kg = None if self.kg is None or r.kg is None else self.kg + r.kg
        self.rows += 1
        if r.partner not in self.names:
            self.names.append(r.partner)
        if r.customs and r.customs.lower() != "nan":
            self.customs.add(r.customs)
        self.bases.add(r.kg_basis)
        if r.origin and not r.origin.startswith("UA "):
            self.foreign_usd += r.export_usd
            self.foreign_kg = None if self.foreign_kg is None or r.kg is None else self.foreign_kg + r.kg


class UaCustomsHoneyExportsCollector(Collector):
    key = "ua_honey_exports"
    name = "Ucraina – Servizio doganale statale: esportazioni di miele per destinazione (UKTZED 0409)"
    name_en = "Ukraine – State Customs Service: honey exports by destination (UKTZED 0409)"
    publisher = "State Customs Service of Ukraine (Держмитслужба), open data on data.gov.ua"
    homepage = UA_DATASET_PAGE
    kind = SourceKind.API
    reliability = Reliability.OFFICIAL
    category = "trade"
    country_iso3 = "UKR"
    language = "en"
    expected_update = "Mensile, nei primi giorni del mese successivo; i file degli ultimi due anni vengono ripubblicati"
    expected_update_en = "Monthly, in the first days of the following month; files of the last two years are re-published"
    expected_max_age_days = 45
    terms_note = ("Fonte: Servizio doganale statale dell'Ucraina, dataset aperto 'Знеособлена зведена інформація для "
                  "статистичних цілей' su data.gov.ua (licenza CC BY 4.0: citare la fonte). Customs value in USD and "
                  "net kg by destination, UKTZED 0409000000; summed over customs offices and countries of origin "
                  "(re-exports included). Data of customs declarations, not the State Statistics Service's "
                  "adjusted figures. The two newest data years are provisional; each change is kept as a revision. "
                  "Export unit values are derived (value / net kg), not market quotations.")
    # Mon/Wed/Fri from the 2nd to the 14th (Europe/Rome): one ~100 KB request when no file changed.
    schedule = {"trigger": "cron", "day": "2-14", "day_of_week": "mon,wed,fri", "hour": 10, "minute": 17}

    def collect(self, ctx: CollectContext) -> None:
        state = _load_state(ctx)
        pkg = ctx.fetch(UA_PACKAGE_URL, params={"id": UA_PACKAGE_ID}, headers={"Accept": "application/json"},
                        title="data.gov.ua: State Customs Service monthly trade files (package_show)")
        resources, notes = parse_ua_package(pkg.content)
        for n in notes:
            _warn_once(ctx, state, f"dup:{n[:60]}", f"data.gov.ua: {n}")
        latest = max(resources)
        start, end = ua_window(latest)
        months = sorted((m for m in resources if start <= m <= end), reverse=True)
        backfill = ctx.force or not _has_rows(ctx)
        done = state.setdefault("months", {})
        todo = [m for m in months if self._needs(ctx, done.get(month_label(m)), resources[m], latest)]
        if not backfill and len(todo) > UA_MAX_DOWNLOADS_PER_RUN:
            log.info("[%s] %d changed files; %d read now, the rest at the next runs", self.key, len(todo),
                     UA_MAX_DOWNLOADS_PER_RUN)
            todo = todo[:UA_MAX_DOWNLOADS_PER_RUN]
        for m in todo:
            res = resources[m]
            if self._pull_month(ctx, state, res, latest):
                done[res.label] = {"sig": res.signature, "status": ua_data_status(m[0], latest[0]).value,
                                   "parser": UA_PARSER_VERSION}
            _save_state(ctx, state)
            ctx.checkpoint()
        state.update({"latest": month_label(latest), "checked_at": utcnow().isoformat(timespec="seconds")})
        if not todo:
            log.info("[%s] no changed file (newest %s)", self.key, month_label(latest))
        _save_state(ctx, state)

    @staticmethod
    def _needs(ctx: CollectContext, rec: dict | None, res: UaResource, latest: Month) -> bool:
        if ctx.force or not rec:
            return True
        return (rec.get("sig") != res.signature or rec.get("parser") != UA_PARSER_VERSION
                or rec.get("status") != ua_data_status(res.month[0], latest[0]).value)

    def _pull_month(self, ctx: CollectContext, state: dict, res: UaResource, latest: Month) -> bool:
        if res.size and res.size > UA_MAX_FILE_BYTES:
            ctx.warn(f"customs file {res.name} is {res.size // 1024 ** 2} MB (limit {UA_MAX_FILE_BYTES // 1024 ** 2} MB); "
                     "not downloaded")
            return False
        doc = ctx.fetch(res.url, store=False, title=f"Ukraine customs {res.name}")
        if res.size is not None and len(doc.content) != res.size:
            ctx.warn(f"customs file {res.name}: {len(doc.content)} bytes downloaded, data.gov.ua lists {res.size} "
                     "(incomplete download or file replaced meanwhile); asked again at the next run")
            return False
        if res.md5 and hashlib.md5(doc.content).hexdigest() != res.md5:
            # Seen live: the 2023 files' listed hashes match neither the .gz nor the CSV (sizes do). The
            # gzip CRC-32 and length, checked on decompression, still guard against a corrupt download.
            _warn_once(ctx, state, f"md5:{res.resource_id}:{res.md5}",
                       f"customs file {res.name}: the MD5 data.gov.ua lists does not match the file (its size does); "
                       "the file's own gzip checksum is relied on")
        parsed = parse_ua_month(doc.content, res.month)
        for p in parsed.problems:
            ctx.warn(p)
        raw_id, _ = ctx.store_raw(res.url, parsed.extract, "text/csv",
                                  f"Ukraine customs {res.name}: header and UKTZED 0409 rows "
                                  f"({parsed.honey_rows} of {parsed.total_rows} rows)", res.modified)
        exports = [r for r in parsed.rows if r.kg_basis != "unusable"]
        unusable = len(parsed.rows) - len(exports)
        label = res.label
        if not exports and not unusable:
            # No honey exported (possible, never seen 2023-2026): nothing to store, earlier rows withdrawn.
            log.info("[%s] %s: no honey export row", self.key, label)
        status = ua_data_status(res.month[0], latest[0])
        p_start, p_end = month_bounds(*res.month)
        common = {"period_start": p_start, "period_end": p_end, "period_label": label, "frequency": "M",
                  "published_at": res.modified, "data_status": status, "reliability": Reliability.OFFICIAL,
                  "source_url": res.url, "raw_document_id": raw_id or None}
        base_extra = {"uktzed": UA_HONEY_CODE, "uktzed_description": "Natural honey", "file": res.name,
                      "resource_id": res.resource_id, "file_last_modified": res.last_modified or None,
                      "file_md5": res.md5, "status_basis": UA_STATUS_BASIS, "value_basis": "customs value, USD",
                      "dataset": UA_DATASET_PAGE}
        aggs: dict[str, _UaAgg] = {}
        not_allocated: list[dict] = []
        total = _UaAgg("WLD")
        for r in exports:
            total.add(r)
            iso, how = map_ua_partner(r.partner)
            if iso is None:
                not_allocated.append({"partner": r.partner, "usd": round(r.export_usd, 2),
                                      "kg": None if r.kg is None else round(r.kg, 3), "why": how})
                if how != "unspecified":
                    _warn_once(ctx, state, f"partner:{r.partner}:{how}",
                               f"customs partner {r.partner!r}: "
                               f"{'its name points to another country' if how == 'conflict' else 'no ISO3 mapping'}; "
                               "kept in the total only")
                continue
            aggs.setdefault(iso, _UaAgg(iso)).add(r)
        present: set[str] = set()
        for iso in sorted(aggs):
            present.add(self._store_partner(ctx, label, aggs[iso], common, base_extra))
        if exports and not unusable:
            present.add(self._store_total(ctx, label, total, common, base_extra, not_allocated, len(aggs)))
        elif unusable:
            ctx.warn(f"customs {label}: {unusable} unusable honey row(s); the world total of {label} is not stored")
        # A month with an unreadable row or an unmapped partner withdraws nothing (it might be one of them).
        unsure = unusable or any(x["why"] != "unspecified" for x in not_allocated)
        gone = [] if unsure else _retire_absent(
            ctx, prefix="uacustoms|UKR|", months={label}, present=present,
            price_key=lambda p, lab: f"{PriceType.EXPORT_UNIT_VALUE.value}|uacustoms|{p}|UKR|{lab}")
        if gone:
            ctx.warn(f"customs file {res.name} no longer shows honey exports for {', '.join(gone)}: withdrawn "
                     "(kept in the history)")
        return True

    @staticmethod
    def _kg_basis(agg: _UaAgg) -> str:
        if agg.kg is None:
            return "unknown: a row mixes imports and exports and the import weight cannot be read"
        if agg.bases == {"netto"}:
            return "net kg as published"
        return "net kg as published; on a row with imports too, net kg minus the taxed import kg"

    def _store_partner(self, ctx: CollectContext, label: str, agg: _UaAgg, common: dict, base_extra: dict) -> str:
        usd = round(agg.usd, 2)
        kg = None if agg.kg is None else round(agg.kg, 3)
        extra = {**base_extra, "partner_as_published": agg.names[0] if len(agg.names) == 1 else agg.names,
                 "mapped_by": "iso2", "file_rows": agg.rows, "customs_offices": sorted(agg.customs),
                 "kg_basis": self._kg_basis(agg), "kg_note": UA_KG_NOTE if agg.bases != {"netto"} else None,
                 "non_ukrainian_origin": ({"usd": round(agg.foreign_usd, 2),
                                           "kg": None if agg.foreign_kg is None else round(agg.foreign_kg, 3)}
                                          if agg.foreign_usd else None)}
        series = f"uacustoms|UKR|{agg.iso3}|export|{label}"
        ctx.add_trade(series_key=series, hs_code="0409", reporter_iso3="UKR", partner_iso3=agg.iso3,
                      flow=TradeFlow.EXPORT.value, currency="USD", value=usd, net_weight_kg=kg,
                      value_basis="customs value", extra=extra,
                      notes=("Esportazioni ucraine di miele naturale UKTZED 0409000000 (Servizio doganale statale, "
                             "dati aperti): valore doganale in USD e peso netto verso questa destinazione."),
                      **common)
        price_series = f"uacustoms|{agg.iso3}|UKR|{label}"
        if kg is not None and kg >= MIN_UNIT_VALUE_WEIGHT_KG and usd > 0:
            destination = country_name(agg.iso3, "en")
            ctx.add_price(series_key=price_series, price_type=PriceType.EXPORT_UNIT_VALUE,
                          variety=Variety.UNSPECIFIED.value, price_value=round(usd / kg, 4), currency="USD", unit="kg",
                          origin_iso3="UKR", origin_label="Ukraine", market_iso3=agg.iso3, market_location=destination,
                          terms="customs value", variety_raw="UKTZED 0409000000 Natural honey", volume_kg=kg,
                          notes=("Valore unitario all'esportazione = valore doganale / peso netto (dogane ucraine, "
                                 "UKTZED 0409). Dato doganale derivato, non una quotazione di mercato."),
                          extra={**extra, "usd": usd, "kg": kg}, **common)
        else:
            ctx.retire(PriceObservation, f"{PriceType.EXPORT_UNIT_VALUE.value}|{price_series}")
        return series

    def _store_total(self, ctx: CollectContext, label: str, total: _UaAgg, common: dict, base_extra: dict,
                     not_allocated: list[dict], partners: int) -> str:
        extra = {**base_extra, "total_of": UA_TOTAL_BASIS, "file_rows": total.rows, "partners": partners,
                 "not_allocated": not_allocated or None, "kg_basis": self._kg_basis(total),
                 "kg_note": UA_KG_NOTE if total.bases != {"netto"} else None,
                 "non_ukrainian_origin": ({"usd": round(total.foreign_usd, 2),
                                           "kg": None if total.foreign_kg is None else round(total.foreign_kg, 3)}
                                          if total.foreign_usd else None)}
        series = f"uacustoms|UKR|WLD|export|{label}"
        ctx.add_trade(series_key=series, hs_code="0409", reporter_iso3="UKR", partner_iso3="WLD",
                      flow=TradeFlow.EXPORT.value, currency="USD", value=round(total.usd, 2),
                      net_weight_kg=None if total.kg is None else round(total.kg, 3), value_basis="customs value",
                      extra=extra,
                      notes=("Totale delle esportazioni ucraine di miele UKTZED 0409000000: somma di tutte le righe del "
                             "file mensile delle dogane (tutte le destinazioni, comprese quelle non specificate)."),
                      **common)
        return series


# ===========================================================================
# 2) Mexico: INEGI, Balanza Comercial de Mercancías de México (monthly OLAP cube)
# ===========================================================================

INEGI_START_URL = "https://www.inegi.org.mx/sistemas/Olap/Proyectos/bd/continuas/comex/comex_bcmm_mensual2023.asp"
INEGI_QUERY_URL = "https://www.inegi.org.mx/sistemas/olap/consulta/general_ver4/MDXQueryDatos.asp"
INEGI_METADATA_URL = "https://www.inegi.org.mx/sistemas/olap/proyectos/bd/continuas/comex/metadatos/comex_bcmm_mensual.asp"
MX_HONEY_MEMBER = ("[Tarifa].[Tarifa].[DES CAPITULO].&[04].&[04]&[0409].&[04]&[0409]&[040900]"
                   ".&[04]&[0409]&[040900]&[04090001]")
MX_EXPORT_MEMBER = "[Tipo operación].[Tipo operación].&[2]"
MX_USD_MEMBER = "[Tipo moneda].[ID TIPO MONEDA].&[1]"
MX_HONEY_CAPTION = re.compile(r"04\.09\.0001\s*\(Kg\)\s*Miel natural", re.IGNORECASE)
MX_FRACCION = "0409.00.01"
MX_BACKFILL_YEARS = 3
MX_PARSER_VERSION = 1
MX_MAX_PAGES = 15
MX_RETRIES = 2
_MX_ENCODING = "cp1252"

_ES_MONTHS = {m: i + 1 for i, m in enumerate(("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                               "septiembre", "octubre", "noviembre", "diciembre"))}
# INEGI spellings that the shared Spanish resolver does not know (from INEGI's own country list, Nov 2026).
_INEGI_NAMES_RAW = {
    "Afganistán": "AFG", "Anguila": "AIA", "Antigua y Barbuda": "ATG", "Belice": "BLZ", "Bermudas": "BMU",
    "Bonaire, San Eustaquio y Saba": "BES", "Bután": "BTN", "Camboya": "KHM", "Ciudad del Vaticano": "VAT",
    "Corea del Norte": "PRK", "Costa de Marfil": "CIV", "Curazao": "CUW", "Estado de Micronesia": "FSM",
    "Federación Rusa": "RUS", "Fidji": "FJI", "Granada": "GRD", "Guadalupe y Dependencias": "GLP",
    "Guinea Ecuatorial": "GNQ", "Guyana Francesa": "GUF", "Isla Man": "IMN", "Isla Montserrat": "MSR",
    "Isla Nive": "NIU", "Isla Norfolk": "NFK", "Isla Reunión": "REU", "Islas Áland": "ALA", "Islas Caimán": "CYM",
    "Islas Cocos": "CCK", "Islas Comoras": "COM", "Islas Cook": "COK", "Islas Feroé": "FRO",
    "Islas Malvinas": "FLK", "Islas Marianas": "MNP", "Islas Marshall": "MHL", "Islas Navidad": "CXR",
    "Islas Pitcairns": "PCN", "Islas Salomón": "SLB", "Islas Svalbard y Jan Mayen": "SJM", "Islas Tokelau": "TKL",
    "Islas Turcas y Caicos": "TCA", "Islas Vírgenes (EU)": "VIR", "Islas Vírgenes (Reino Unido)": "VGB",
    "Islas Wallis y Futuna": "WLF", "Kenia": "KEN", "Maldivas": "MDV", "Mauricio": "MUS", "Nueva Caledonia": "NCL",
    "Países Bajos": "NLD", "Papúa Nueva Guinea": "PNG", "Polinesia Francesa": "PYF", "República Árabe Siria": "SYR",
    "República Centroafricana": "CAF", "República Checa": "CZE", "República de Laos": "LAO",
    "República del Congo": "COG", "Sahara Occidental": "ESH", "Samoa Americana": "ASM", "Samoa Occidental": "WSM",
    "San Bartolomé": "BLM", "San Cristóbal y Nieves": "KNA", "San Martín (Parte Francesa)": "MAF",
    "San Martín (parte Holandesa)": "SXM", "San Pedro y Miquelón": "SPM", "San Vicente y las Granadinas": "VCT",
    "Santa Elena": "SHN", "Santa Lucía": "LCA", "Santo Tome y Príncipe": "STP", "Sierra Leona": "SLE",
    "Singapur": "SGP", "Sudán del Sur": "SSD", "Suiza": "CHE", "Surinam": "SUR", "Swazilandia": "SWZ",
    "Tadjikistán": "TJK", "Territorios Autónomos de Palestina": "PSE", "Timor Oriental": "TLS",
    "Trinidad y Tobago": "TTO", "Túnez": "TUN", "Zaire": "COD", "Japón": "JPN", "Corea del Sur": "KOR",
    "Emiratos Árabes Unidos": "ARE", "Egipto": "EGY", "Marruecos": "MAR", "Kazajstán": "KAZ", "Irak": "IRQ",
    "Bielorrusia": "BLR", "Bosnia y Herzegovina": "BIH", "Hong Kong (Región Administrativa Especial de la República de China)": "HKG",
    "Isla Bouvet": "BVT", "Islas Heard y Mc Donald": "HMD", "Georgia del Sur e Islas Sandwich del Sur": "SGS",
    "Territorios del Reino Unido del Océano Índico": "IOT", "Territorios franceses Australes y Antárticos": "ATF",
    "Antártida": "ATA",
}
_INEGI_NAMES = {_norm_name(k): v for k, v in _INEGI_NAMES_RAW.items()}
# INEGI's groupings and unidentified partners: never a country.
_INEGI_AGGREGATES = frozenset(_norm_name(s) for s in (
    "América", "Asia", "Europa", "Islas del Pacífico", "Otros países no declarados de la UE",
    "Países no declarados del Resto de Europa", "Países no identificados", "Zona Neutral Irak-Arabia Saudita",
    "Territorios Franceses de Ultramar", "Antillas Neerlandesas", "Zona Canal de Panamá", "Islas Canal",
    "Franja de Gaza"))

MX_STATUS_BASIS = ("INEGI's cube: 'cifras ajustadas' (after the annual revision) are stored as published, 'datos "
                   "revisados' (revised every month) as provisional")
MX_CONFIDENTIAL_NOTE = ("Cells with one or two exporters are confidential ('C', LSNIEG arts. 37-38) and never stored; "
                        "INEGI's Total includes them")


@dataclass(frozen=True)
class InegiCube:
    server: str
    database: str
    cube: str
    first: Month
    last: Month
    adjusted_until: Month | None
    status_text: str

    @property
    def signature(self) -> str:
        return f"{self.server}|{self.database}|{self.cube}|{month_label(self.first)}|{month_label(self.last)}|{self.status_text}"


def _es_month(name: str, year: str) -> Month | None:
    m = _ES_MONTHS.get(_norm_name(name))
    return (int(year), m) if m else None


def _hidden(page: str, name: str) -> str | None:
    m = re.search(r'<input[^>]*name="' + re.escape(name) + r'"[^>]*value="([^"]*)"', page, re.IGNORECASE)
    return html_lib.unescape(m.group(1)).strip() if m else None


def _text(page: str) -> str:
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.DOTALL | re.IGNORECASE)
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", t))).replace("\xa0", " ").strip()


def parse_inegi_start(content: bytes) -> InegiCube:
    """The cube's start page: period, status note and connection. Fails loudly when they are gone."""
    page = content.decode(_MX_ENCODING, errors="replace")
    server, database, cube = (_hidden(page, k) for k in ("server", "database", "cube"))
    title = _hidden(page, "titulo_sin_consecutivo") or ""
    m = re.search(r"\((\w+)\s+(\d{4})\s*-\s*(\w+)\s+(\d{4})\)", title)
    first = _es_month(m.group(1), m.group(2)) if m else None
    last = _es_month(m.group(3), m.group(4)) if m else None
    if not (server and database and cube and first and last and "Balanza Comercial" in title):
        raise CollectorError(f"INEGI cube page changed: server/database/cube/period not found (title {title[:120]!r}); "
                             "nothing stored")
    text = _text(page)
    s = re.search(r"Cifras ajustadas de (\w+) (\d{4}) a (\w+) (\d{4})[^.]*\.", text, re.IGNORECASE)
    adjusted = _es_month(s.group(3), s.group(4)) if s else None
    status_text = s.group(0) if s else ""
    return InegiCube(server=server, database=database, cube=cube, first=first, last=last,
                     adjusted_until=adjusted, status_text=status_text)


def mx_data_status(month: Month, cube: InegiCube) -> DataStatus:
    if cube.adjusted_until is not None and month <= cube.adjusted_until:
        return DataStatus.PUBLISHED
    return DataStatus.PROVISIONAL


def mx_rows_expression(year: int) -> str:
    return (f"CrossJoin({{{MX_HONEY_MEMBER}}},{{{MX_EXPORT_MEMBER}}},{{[Año].&[{year}]}},{{[Mes].Members}},"
            "{[País].[País].[Total],[País].[País].[Pais].Members})")


def mx_expected_mdx(cube: InegiCube, year: int) -> str:
    return (f"select NON EMPTY {{[Measures].AllMembers}} on columns, NON EMPTY {mx_rows_expression(year)} on rows "
            f"from [{cube.cube}] where ({MX_USD_MEMBER})")


def mx_query_fields(cube: InegiCube, year: int, page: int) -> list[tuple[str, str]]:
    """The viewer's own form fields (CubeBrowser.js) for one page of honey exports of `year`."""
    return [("s", "est"), ("server", cube.server), ("database", cube.database), ("cube", cube.cube),
            ("columns", "{[Measures].AllMembers}"), ("rows", mx_rows_expression(year)),
            ("NomDimFila", "Tipo operación"), ("NomDimCol", "Measures"), ("Where_Tipo moneda", MX_USD_MEMBER),
            ("NumPagCol", "1"), ("NumPagFil", str(page)), ("Paq_PagCol", "0"), ("Paq_PagFil", str((page - 1) // 10)),
            ("level", "1"), ("DimVisible", "Measures|Tipo operación|Tipo moneda"), ("NDim", "7"),
            ("NomArch", "MDXQueryDatos.asp"), ("ed", "0,0,2")]


def mx_form_body(fields: list[tuple[str, str]]) -> bytes:
    return "&".join(quote(k.encode(_MX_ENCODING)) + "=" + quote(v.encode(_MX_ENCODING)) for k, v in fields).encode("ascii")


@dataclass
class InegiRow:
    month: Month
    partner: str                      # Spanish name as published ("Total" for the total)
    value: float | None               # USD (None when confidential)
    qty: float | None                 # kg
    confidential: bool = False


@dataclass
class InegiPage:
    rows: list[InegiRow] = field(default_factory=list)
    total_rows: int | None = None     # rows the viewer announces for the whole query
    per_page: int | None = None
    problems: list[str] = field(default_factory=list)


def _mx_number(s: str) -> float | None:
    s = s.strip()
    if not re.fullmatch(r"-?\d{1,3}(,\d{3})*(\.\d+)?|-?\d+(\.\d+)?", s):
        return None
    return float(s.replace(",", ""))


def _cell_text(cell: str) -> str:
    t = html_lib.unescape(re.sub(r"<[^>]+>", " ", cell)).replace("\xa0", " ")
    t = re.sub(r"&nbsp;?", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def parse_inegi_page(content: bytes, cube: InegiCube, year: int) -> InegiPage:
    """One page of the honey-exports query. Fails loudly when the viewer ran another query (``Lc_sql``),
    when the measures or a row's product / flow / year are not the ones asked, or on an error page."""
    page = content.decode(_MX_ENCODING, errors="replace")
    sql = re.search(r'name="Lc_sql"\s+value="(.*?)"\s*>', page, re.DOTALL)
    if sql is None:
        raise CollectorError(f"INEGI viewer answered no query echo for {year} (error page or format changed?): "
                             f"{_text(page)[:160]!r}")
    if re.sub(r"\s+", " ", html_lib.unescape(sql.group(1))).strip() != mx_expected_mdx(cube, year):
        raise CollectorError(f"INEGI viewer ran another query for {year} ({html_lib.unescape(sql.group(1))[:200]!r}); "
                             "nothing stored")
    out = InegiPage()
    act = re.search(r"Actualiza\('(\d*)','(\d*)','(\d*)','(\d*)'\)", page)
    if act and act.group(3) != "":
        out.total_rows, out.per_page = int(act.group(3)), int(act.group(4) or 0) or None
    elif act:
        out.total_rows = 0                       # NON EMPTY answer: no row at all
    heads = re.findall(r"ID=\[Measures\]\.\[([^\]]+)\]", page)
    if out.total_rows and (not heads or heads[:2] != ["Valor Total", "Cantidad total"][: len(heads[:2])]
                           or "Valor Total" not in heads or "Cantidad total" not in heads):
        raise CollectorError(f"INEGI viewer measures changed ({sorted(set(heads))}); expected Valor Total and "
                             "Cantidad total; nothing stored")
    for seg in re.split(r"<TR>", page, flags=re.IGNORECASE)[1:]:
        seg = re.split(r"</TR>", seg, flags=re.IGNORECASE)[0]
        values = re.findall(r'<TD CLASS="tdCenso"[^>]*>(.*?)</TD>', seg, re.DOTALL | re.IGNORECASE)
        if len(values) != 2:
            continue
        heads_ = [_cell_text(c) for c in re.findall(r'<TD class="tdSubtitulo"[^>]*>(.*?)</TD>', seg, re.DOTALL | re.IGNORECASE)]
        if len(heads_) < 5:
            out.problems.append(f"INEGI {year}: a data row without its 5 labels ({heads_!r}); skipped")
            continue
        product, flow, yr, mes, partner = (re.sub(r"^[+-]\s*", "", h) for h in heads_[-5:])
        if not MX_HONEY_CAPTION.search(product):
            raise CollectorError(f"INEGI viewer returned another product ({product!r}) for {year}; nothing stored")
        if flow != "Exportaciones" or yr != str(year):
            raise CollectorError(f"INEGI viewer returned {flow!r} {yr!r} instead of Exportaciones {year}; nothing stored")
        month = _es_month(mes, yr)
        if month is None:
            out.problems.append(f"INEGI {year}: unreadable month {mes!r}; row skipped")
            continue
        v, q = (_cell_text(c) for c in values)
        if v.upper() == "C" or q.upper() == "C":
            out.rows.append(InegiRow(month, partner, None, None, confidential=True))
            continue
        value, qty = _mx_number(v), _mx_number(q)
        if value is None or qty is None or value < 0 or qty < 0:
            out.problems.append(f"INEGI {month_label(month)} {partner}: unusable value / quantity {v!r} / {q!r}; "
                                "not stored")
            out.rows.append(InegiRow(month, partner, None, None))
            continue
        out.rows.append(InegiRow(month, partner, value, qty))
    return out


def map_inegi_partner(name: Any) -> tuple[str | None, str]:
    """(ISO3 or None, how) for an INEGI destination name. `how`: "name", "aggregate" or "unknown"."""
    s = re.sub(r"\s+", " ", str(name or "")).strip()
    norm = _norm_name(s)
    if not norm or norm in _INEGI_AGGREGATES:
        return None, "aggregate"
    iso = _INEGI_NAMES.get(norm) or resolve_es_country(s)
    if iso is None or iso in AGGREGATES:
        return None, "unknown"
    return iso, "name"


class MxInegiHoneyExportsCollector(Collector):
    key = "mx_honey_exports"
    name = "Messico – INEGI: esportazioni di miele per destinazione (fracción 0409.00.01)"
    name_en = "Mexico – INEGI: honey exports by destination (tariff item 0409.00.01)"
    publisher = "INEGI – Instituto Nacional de Estadística y Geografía (with SAT, SE and Banxico)"
    homepage = INEGI_START_URL
    kind = SourceKind.HTML
    reliability = Reliability.OFFICIAL
    category = "trade"
    country_iso3 = "MEX"
    language = "es"
    expected_update = "Mensile, circa sei settimane dopo il mese; i dati dell'anno in corso sono rivisti ogni mese"
    expected_update_en = "Monthly, about six weeks after the month; the running year's data are revised every month"
    expected_max_age_days = 75
    terms_note = ("Fonte: INEGI, Balanza Comercial de Mercancías de México (SAT, SE, Banxico, INEGI; Información de "
                  "Interés Nacional), consulta interattiva per fracción arancelaria (Términos de libre uso de la "
                  "información del INEGI: citare INEGI). FOB value in USD and quantity in kg by last known destination, "
                  "fracción 0409.00.01 'Miel natural'. Destinations with one or two exporters are confidential ('C') "
                  "and appear only in the total. 'Datos revisados' are provisional; each change is kept as a revision. "
                  "Export unit values are derived (FOB / kg), not market quotations.")
    # Weekdays from the 5th to the 25th (Europe/Rome); one 25 KB request when the cube did not change.
    schedule = {"trigger": "cron", "day": "5-25", "day_of_week": "mon-fri", "hour": 16, "minute": 43}

    def collect(self, ctx: CollectContext) -> None:
        state = _load_state(ctx)
        start = ctx.fetch(INEGI_START_URL, title="INEGI BCMM monthly cube (period and status)")
        cube = parse_inegi_start(start.content)
        if not cube.status_text:
            _warn_once(ctx, state, "no_status_note", "INEGI cube page has no 'Cifras ajustadas ...' note: every month "
                       "is stored as provisional until it is back")
        years = self._years_to_pull(ctx, state, cube)
        for y in years:
            if self._pull_year(ctx, state, cube, y):
                state.setdefault("years", {})[str(y)] = {"sig": cube.signature, "parser": MX_PARSER_VERSION}
            _save_state(ctx, state)
            ctx.checkpoint()
        state.update({"cube": cube.signature, "latest": month_label(cube.last),
                      "checked_at": utcnow().isoformat(timespec="seconds")})
        if not years:
            log.info("[%s] INEGI cube unchanged (%s); nothing to pull", self.key, month_label(cube.last))
        _save_state(ctx, state)

    @staticmethod
    def _years_to_pull(ctx: CollectContext, state: dict, cube: InegiCube) -> list[int]:
        """Newest first. Everything on a forced run, a first run or a parser change; otherwise, when the
        cube changed, the years that are not adjusted yet (revised every month) and every year when the
        adjusted range moved; and any year whose last pull did not complete."""
        lo = max(cube.first[0], cube.last[0] - MX_BACKFILL_YEARS)
        window = list(range(lo, cube.last[0] + 1))
        done = state.get("years") or {}
        if ctx.force or not _has_rows(ctx):
            return sorted(window, reverse=True)
        old = str(state.get("cube") or "")
        adjusted_moved = old.split("|")[5:] != cube.signature.split("|")[5:]
        todo = []
        for y in window:
            rec = done.get(str(y)) or {}
            if rec.get("parser") != MX_PARSER_VERSION or not rec or rec.get("sig") != cube.signature and (
                    adjusted_moved or y == cube.last[0]
                    or cube.adjusted_until is None or (y, 12) > cube.adjusted_until):
                todo.append(y)
        return sorted(todo, reverse=True)

    # ------------------------------------------------------------------ requests
    def _post(self, ctx: CollectContext, cube: InegiCube, year: int, page: int) -> FetchResult:
        """One POST of the viewer's form (``ctx.fetch`` sends JSON bodies only); same politeness."""
        host = urlsplit(INEGI_QUERY_URL).netloc
        body = mx_form_body(mx_query_fields(cube, year, page))
        attempt = 0
        while True:
            attempt += 1
            ctx.wait_for_host(host)
            try:
                resp = ctx.client.post(INEGI_QUERY_URL, content=body, headers={
                    "Content-Type": "application/x-www-form-urlencoded", "Referer": INEGI_START_URL})
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                if attempt > MX_RETRIES:
                    raise Offline(f"Cannot reach {host}: {exc}") from exc
                continue
            except httpx.TimeoutException as exc:
                if attempt > MX_RETRIES:
                    raise CollectorError(f"Timeout querying INEGI ({year}, page {page})") from exc
                continue
            finally:
                ctx.mark_host(host)
            if resp.status_code in (429, 502, 503, 504) and attempt <= MX_RETRIES:
                continue
            break
        if resp.status_code != 200:
            raise CollectorError(f"HTTP {resp.status_code} from INEGI's cube viewer ({year}, page {page})")
        url = f"{INEGI_QUERY_URL}#honey-exports-{year}-p{page}"
        raw_id, unchanged = ctx.store_raw(url, resp.content, resp.headers.get("content-type"),
                                          f"INEGI BCMM honey exports 0409.00.01 {year} by month and destination, page {page}")
        return FetchResult(url=url, status_code=200, content=resp.content, content_type=resp.headers.get("content-type"),
                           raw_document_id=raw_id, unchanged=unchanged)

    def _pull_year(self, ctx: CollectContext, state: dict, cube: InegiCube, year: int) -> bool:
        first = self._post(ctx, cube, year, 1)
        p1 = parse_inegi_page(first.content, cube, year)
        pages = [(first, p1)]
        total, per = p1.total_rows or 0, p1.per_page or 33
        n_pages = max(1, -(-total // per))
        if n_pages > MX_MAX_PAGES:
            raise CollectorError(f"INEGI announces {total} rows for honey exports {year} ({n_pages} pages); more than "
                                 f"{MX_MAX_PAGES} pages is not plausible: nothing stored")
        for n in range(2, n_pages + 1):
            doc = self._post(ctx, cube, year, n)
            pages.append((doc, parse_inegi_page(doc.content, cube, year)))
        rows = [r for _, p in pages for r in p.rows]
        for _, p in pages:
            for msg in p.problems:
                ctx.warn(msg)
        if len(rows) + sum(1 for _, p in pages for m in p.problems if "skipped" in m) != total:
            ctx.warn(f"INEGI {year}: {len(rows)} rows read, the viewer announced {total}; {year} asked again at the "
                     "next run")
            return False
        by_month: dict[Month, list[InegiRow]] = {}
        for r in rows:
            if r.month > cube.last:
                ctx.warn(f"INEGI returned {month_label(r.month)} after the cube's last month {month_label(cube.last)}; ignored")
                continue
            by_month.setdefault(r.month, []).append(r)
        src = {"source_url": INEGI_START_URL, "raw_document_id": first.raw_document_id or None}
        stored: set[str] = set()
        present: set[str] = set()
        for month in sorted(by_month):
            label = month_label(month)
            if self._store_month(ctx, state, cube, month, by_month[month], src, present):
                stored.add(label)
        gone = _retire_absent(ctx, prefix="inegi|MEX|", months=stored, present=present,
                              price_key=lambda p, lab: f"{PriceType.EXPORT_UNIT_VALUE.value}|inegi|{p}|MEX|{lab}")
        if gone:
            ctx.warn(f"INEGI no longer shows honey exports for {', '.join(gone)} (revised or now confidential): withdrawn "
                     "(kept in the history)")
        return True

    def _store_month(self, ctx: CollectContext, state: dict, cube: InegiCube, month: Month, rows: list[InegiRow],
                     src: dict, present: set[str]) -> bool:
        label = month_label(month)
        totals = [r for r in rows if _norm_name(r.partner) == "total"]
        if len(totals) != 1:
            ctx.warn(f"INEGI {label}: {len(totals)} Total rows; month not stored")
            return False
        total = totals[0]
        p_start, p_end = month_bounds(*month)
        common = {"period_start": p_start, "period_end": p_end, "period_label": label, "frequency": "M",
                  "published_at": None, "data_status": mx_data_status(month, cube), "reliability": Reliability.OFFICIAL,
                  **src}
        base_extra = {"fraccion": MX_FRACCION, "fraccion_description": "Miel natural", "tariff_unit": "kg",
                      "cube": cube.cube, "cube_period": f"{month_label(cube.first)}..{month_label(cube.last)}",
                      "cube_status_note": cube.status_text or None, "status_basis": MX_STATUS_BASIS,
                      "partner_basis": "country of last known destination", "metadata": INEGI_METADATA_URL}
        aggs: dict[str, list[InegiRow]] = {}
        masked: list[dict] = []
        not_allocated: list[dict] = []
        unsure = False
        vis_value = vis_qty = 0.0
        for r in rows:
            if r is total:
                continue
            iso, how = map_inegi_partner(r.partner)
            if r.confidential:
                masked.append({"name": r.partner, "iso3": iso})
                continue
            if r.value is None:
                unsure = True
                continue
            vis_value += r.value
            vis_qty += r.qty
            if iso is None:
                not_allocated.append({"name": r.partner, "usd": r.value, "kg": r.qty, "why": how})
                if how != "aggregate":
                    unsure = True
                    _warn_once(ctx, state, f"partner:{r.partner}", f"INEGI destination {r.partner!r} has no ISO3 "
                               "mapping; kept in the total only until trade_origins is checked")
                continue
            aggs.setdefault(iso, []).append(r)
        for iso in sorted(aggs):
            if any(m["iso3"] == iso for m in masked):
                ctx.warn(f"INEGI shows {iso} {label} both confidential and visible (two spellings); not stored")
                continue
            value = sum(r.value for r in aggs[iso])
            qty = sum(r.qty for r in aggs[iso])
            names = [r.partner for r in aggs[iso]]
            present.add(self._store_destination(ctx, label, iso, value, qty, names, common, base_extra))
        if total.confidential or total.value is None:
            ctx.warn(f"INEGI's total of honey exports {label} is confidential or unreadable: not stored")
            return not unsure
        gap_v, gap_q = round(total.value - vis_value, 2), round(total.qty - vis_qty, 3)
        extra = {**base_extra, "total_of": "INEGI's published Total (all destinations, confidential ones included)",
                 "confidential_destinations": masked or None,
                 "confidential_part": {"usd": gap_v, "kg": gap_q} if masked else None,
                 "visible_destinations": len(aggs), "not_allocated": not_allocated or None,
                 "confidentiality_note": MX_CONFIDENTIAL_NOTE}
        if not masked and (abs(gap_v) > 2 or abs(gap_q) > 2):
            extra["sum_check"] = f"visible destinations differ from the Total by {gap_v} USD / {gap_q} kg"
        series = f"inegi|MEX|WLD|export|{label}"
        ctx.add_trade(series_key=series, hs_code="0409", reporter_iso3="MEX", partner_iso3="WLD",
                      flow=TradeFlow.EXPORT.value, currency="USD", value=total.value, net_weight_kg=total.qty,
                      value_basis="FOB", extra=extra,
                      notes=("Totale delle esportazioni messicane di miele (fracción 0409.00.01) pubblicato da INEGI: "
                             "tutte le destinazioni, comprese quelle confidenziali (dettaglio in 'extra')."),
                      **common)
        present.add(series)
        return not unsure

    def _store_destination(self, ctx: CollectContext, label: str, iso: str, value: float, qty: float, names: list[str],
                           common: dict, base_extra: dict) -> str:
        extra = {**base_extra, "destination_name": names[0] if len(names) == 1 else names, "mapped_by": "name"}
        series = f"inegi|MEX|{iso}|export|{label}"
        ctx.add_trade(series_key=series, hs_code="0409", reporter_iso3="MEX", partner_iso3=iso,
                      flow=TradeFlow.EXPORT.value, currency="USD", value=value, net_weight_kg=qty, value_basis="FOB",
                      extra=extra,
                      notes=("Esportazioni messicane di miele naturale (fracción 0409.00.01, INEGI, Balanza Comercial de "
                             "Mercancías): valore FOB in USD e quantità in kg verso questa destinazione."),
                      **common)
        price_series = f"inegi|{iso}|MEX|{label}"
        if qty >= MIN_UNIT_VALUE_WEIGHT_KG and value > 0:
            ctx.add_price(series_key=price_series, price_type=PriceType.EXPORT_UNIT_VALUE,
                          variety=Variety.UNSPECIFIED.value, price_value=round(value / qty, 4), currency="USD",
                          unit="kg", origin_iso3="MEX", origin_label="Mexico", market_iso3=iso,
                          market_location=country_name(iso, "en"), terms="FOB",
                          variety_raw="Fracción 0409.00.01 Miel natural", volume_kg=qty,
                          notes=("Valore unitario all'esportazione = valore FOB / kg (INEGI, fracción 0409.00.01). Dato "
                                 "doganale derivato, non una quotazione di mercato."),
                          extra={**extra, "fob_usd": value, "kg": qty}, **common)
        else:
            ctx.retire(PriceObservation, f"{PriceType.EXPORT_UNIT_VALUE.value}|{price_series}")
        return series


__all__ = [
    "InegiCube",
    "MxInegiHoneyExportsCollector",
    "UaCustomsHoneyExportsCollector",
    "map_inegi_partner",
    "map_ua_partner",
    "mx_data_status",
    "parse_inegi_page",
    "parse_inegi_start",
    "parse_ua_month",
    "parse_ua_package",
    "ua_data_status",
]
