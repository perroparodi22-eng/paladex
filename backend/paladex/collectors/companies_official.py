"""Honey exporters and importers BY COMPANY, from official sources that publish company-level data.

Four collectors (checked live on 2026-11-05; the research behind every rejected lead is in
docs/DATA_SOURCES.md and in ``api/companies.py``, which states per country what exists and why):

* ``uy_sie_honey_exporters``: Uruguay, **Uruguay XXI – Sistema de Información Estadística (SIE)**, the
  government export agency's query tool on Dirección Nacional de Aduanas data (refreshed every 48 h).
  Its "Por Empresa" view (``filtros.php?t=empresa``) with the NCM filter 0409 lists every company that
  exported natural honey in the SIE's five-year window, with the **exact FOB value in US$ per year**
  (2022 ... 2025 and the running year "2026 (ene - oct)") and the published "Total Detalle". One record
  per company and year (value > 0); the running year is year-to-date and ``provisional``. The SIE has
  no company view for imports (its import menu offers NCM, country and month only).

* ``uk_hmrc_honey_traders``: United Kingdom, **HM Revenue & Customs, UK Trade Info "Find UK traders"**
  (``api.uktradeinfo.com``, Import / Export entities): every business that imported or exported
  commodity code 04090000 (natural honey) in a month, with its registered name and address. HMRC
  publishes **no quantities or values** for traders (its own words: "for legal reasons"), so these are
  names only: one record per trader and month, ``measure_kind = none``, never ranked. Window: the last
  24 months HMRC has published.

* ``in_eic_honey_establishments``: India, **Export Inspection Council of India (EIC, Ministry of
  Commerce and Industry), "Commodity wise facilities"**: the establishments EIC has approved to process
  honey for export, with EIC approval number, validity and the markets they are approved for ("All
  Countries Including European Union" or "Non-EU"). Read from the JSON the EIC website itself loads
  (``eicindia.gov.in/api/facilities``, public, no login). A register: **names only, never ranked**
  (``registered_exporter``, ``measure_kind = none``); one record per establishment and month it is
  seen listed.

* ``ca_cid_honey_importers``: Canada, **Innovation, Science and Economic Development Canada (ISED),
  Canadian Importers Database (CID)**, product report HS6 040900 (data: Canada Border Services
  Agency): the "major importers" of natural honey in a year (the companies that together account for
  up to 80 % of the import value), in alphabetical order with city and province. **No value per
  company** (the CID publishes only aggregate concentration): names only, never ranked; individuals
  are excluded by the CID itself.

Privacy. Official lists can name private persons (sole traders). Only the name and the location as
published are stored: the SIE gives names only (its page also embeds an autocomplete list of every
exporter with an ID: never archived, never read); for HMRC the location is the last address line after
the street line and the postcode district (outward code), never the street or the full postcode; for
EIC the location is the Indian state only (from the published address), never the address; for the CID
the city and province, never the postal code. No tax or personal identification number is stored or
archived. Archived raw documents are reduced to what is stored (SIE: caption and result table; HMRC:
month, HMRC trader number, name, location; EIC and CID: the stored fields of the honey rows).

Revisions. Every changed figure or name is a new revision (``models_companies.record_company``); a
record the source no longer publishes for a period that was read again is withdrawn (kept in history).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from bs4 import BeautifulSoup
from sqlalchemy import select

from ..enums import DataStatus, Reliability, SourceKind
from ..models_companies import CompanyRecord, CompanyRole, MeasureKind, record_company, retire_companies
from .base import CollectContext, Collector, CollectorError, month_bounds
from .trade_uruguay_chile import (
    SIE_BASE,
    SIE_MONTHS,
    SIE_NCM,
    SIE_QUERY_URL,
    SieTable,
    _norm,
    parse_sie_options,
    parse_sie_table,
    sie_extract,
)

log = logging.getLogger(__name__)


def today() -> date:
    """Reference date (indirection so tests can pin it)."""
    return date.today()


def _clean(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _has_rows(ctx: CollectContext) -> bool:
    C = CompanyRecord
    return ctx.session.scalar(select(C.id).where(C.source_id == ctx.source.id).limit(1)) is not None


def _has_prefix(ctx: CollectContext, prefix: str) -> bool:
    """Whether the source already holds current records under `prefix` (e.g. this month's register)."""
    C = CompanyRecord
    return ctx.session.scalar(select(C.id).where(
        C.source_id == ctx.source.id, C.is_current.is_(True), C.series_key.startswith(prefix, autoescape=True),
    ).limit(1)) is not None


def _add(ctx: CollectContext, *, series_key: str, **fields) -> CompanyRecord:
    fields.setdefault("reliability", ctx.source.reliability)
    for k in ("reliability", "data_status", "role", "measure_kind"):
        if hasattr(fields.get(k), "value"):
            fields[k] = fields[k].value
    outcome, row = record_company(ctx.session, source_id=ctx.source.id, series_key=series_key, **fields)
    ctx.counters.count(outcome)
    ctx._track_period(fields.get("published_at"), fields.get("period_label"), fields.get("period_start"))
    return row


def _retire(ctx: CollectContext, prefix: str, keep: set[str]) -> list[str]:
    gone = retire_companies(ctx.session, source_id=ctx.source.id, prefix=prefix, keep=keep)
    ctx.counters.revised += len(gone)
    return gone


# ===========================================================================
# 1) Uruguay: Uruguay XXI SIE, honey exports by company (exact FOB US$ per year)
# ===========================================================================

SIE_COMPANY_MODE = "empresa"


@dataclass
class SieCompanyYear:
    company: str
    year: int
    value_usd: float
    total_usd: float                 # the published "Total Detalle" of that year
    first_month: int
    last_month: int
    running: bool                    # the running year column ("2026 (ene - oct)"): year-to-date
    column_label: str


def sie_company_years(table: SieTable, ref: date) -> tuple[list[SieCompanyYear], set[int], list[str]]:
    """The storable company-years of a ``t=empresa`` table: (records with a value > 0, the years that
    were read completely, problems). A year whose rows do not add up to the published total is not
    stored at all (``parse_sie_table`` blanks its total). Fails loudly when the table is not a company
    table (month rows: the company filter was ignored) or when the running year does not state its
    months."""
    labels = [label for label, _ in table.rows]
    if table.country:
        raise CollectorError(f"Uruguay XXI SIE by company: the answer is filtered on one destination "
                             f"({table.country!r}); nothing stored")
    if labels and all(_norm(label) in SIE_MONTHS for label in labels):
        raise CollectorError("Uruguay XXI SIE by company: the answer lists months, not companies (the 'Por Empresa' "
                             "view was ignored?); nothing stored")
    problems: list[str] = []
    dupes = {n for n in labels if labels.count(n) > 1}
    for n in sorted(dupes):
        problems.append(f"Uruguay XXI SIE by company: {n!r} appears more than once; its rows are not stored "
                        "(two companies cannot be told apart)")
    out: list[SieCompanyYear] = []
    complete: set[int] = set()
    for i, col in enumerate(table.columns):
        if not col.annotated and col.year >= ref.year:
            raise CollectorError(f"Uruguay XXI SIE by company: the running year column {col.label!r} does not state "
                                 "the months it covers (expected e.g. '2026 (ene - oct)'); nothing stored")
        total = table.total[i]
        if total is None:
            continue
        unreadable = False
        for name, values in table.rows:
            v = values[i]
            if v is None:
                unreadable = True
                continue
            if name in dupes or v <= 0:
                continue
            out.append(SieCompanyYear(company=_clean(name), year=col.year, value_usd=round(v, 2), total_usd=round(total, 2),
                                      first_month=col.first_month, last_month=col.last_month,
                                      running=col.annotated, column_label=col.label))
        if not unreadable and not dupes:
            complete.add(col.year)
    return out, complete, problems


class UySieHoneyExportersCollector(Collector):
    key = "uy_sie_honey_exporters"
    name = "Uruguay – Uruguay XXI (SIE, dati Dirección Nacional de Aduanas): esportatori di miele per azienda (NCM 0409)"
    publisher = "Uruguay XXI – Instituto de Promoción de Inversiones, Exportaciones e Imagen País (data: DNA, MEF)"
    homepage = SIE_BASE
    kind = SourceKind.HTML
    reliability = Reliability.OFFICIAL
    category = "companies"
    country_iso3 = "URY"
    language = "es"
    expected_update = "Controllo settimanale: il SIE si aggiorna ogni 48 ore; l'anno in corso è parziale e provvisorio"
    expected_update_en = "Checked weekly: the SIE is updated every 48 hours; the running year is year-to-date, provisional"
    expected_max_age_days = 40
    terms_note = ("Fuente: Uruguay XXI – Sistema de Información Estadística (SIE), 'Por Empresa' view filtered on NCM "
                  "0409, built on Dirección Nacional de Aduanas data. Public web tool, no reuse terms published. "
                  "Exact FOB value in US$ per company and year, as published; the running year is year-to-date and "
                  "provisional. Names as published (the SIE truncates long names); private persons can appear: only "
                  "the name is stored. The page's autocomplete list of exporters with their IDs is never archived.")
    # Weekly, after the destination check of uy_honey_exports (Wednesday 07:15 in Rome).
    schedule = {"trigger": "cron", "day_of_week": "wed", "hour": 7, "minute": 35}
    order = 61

    @staticmethod
    def _params(year: int) -> dict:
        # The SIE's own order (script.js `buscar`): t, pr, e, a, pa, cat, ncm. `e` (one company) stays empty.
        return {"t": SIE_COMPANY_MODE, "pr": "", "e": "", "a": str(year), "pa": "", "cat": "Todos", "ncm": SIE_NCM}

    def _fetch(self, ctx: CollectContext, year: int):
        # store=False: the whole page embeds the autocomplete list of every exporter with an ID; only the
        # caption and the result table are archived (sie_extract).
        return ctx.fetch(SIE_QUERY_URL, params=self._params(year), headers={"Accept": "text/html"}, store=False)

    def collect(self, ctx: CollectContext) -> None:
        ref = today()
        year = ref.year
        doc = self._fetch(ctx, year)
        years = [int(v) for v in parse_sie_options(doc.content, "anio") if v.isdigit()]
        if years and year not in years:          # early January: the new year is not offered yet
            year = max(years)
            doc = self._fetch(ctx, year)
        table = parse_sie_table(doc.content, "by company")
        if table.last_year != year:
            raise CollectorError(f"Uruguay XXI SIE by company: asked for the window ending {year}, got "
                                 f"{table.first_year}-{table.last_year}; nothing stored")
        for p in table.problems:
            ctx.warn(p)
        records, complete, problems = sie_company_years(table, ref)
        for p in problems:
            ctx.warn(p)
        if not records:
            ctx.warn(f"Uruguay XXI SIE returned no honey exporter for {table.first_year}-{table.last_year}")
            return
        raw_id, unchanged = ctx.store_raw(doc.url, sie_extract(doc.content), "text/html",
                                          title=f"Uruguay XXI SIE honey exports (NCM 0409) by company, {table.caption}")
        if unchanged and not ctx.force and _has_rows(ctx):
            log.info("[%s] SIE company table unchanged since the last run", self.key)
            return
        present: set[str] = set()
        for r in records:
            present.add(self._store(ctx, r, raw_id, doc.url, table.caption, year))
        for y in sorted(complete):
            prefix = f"uysie|URY|exporter|0409|{y}|"
            gone = _retire(ctx, prefix, {k for k in present if k.startswith(prefix)})
            if gone:
                ctx.warn(f"Uruguay XXI SIE no longer lists {len(gone)} honey exporter(s) for {y}: "
                         f"{', '.join(k.rsplit('|', 1)[-1] for k in gone[:10])}")

    def _store(self, ctx: CollectContext, r: SieCompanyYear, raw_id: int, url: str, caption: str, window: int) -> str:
        start = date(r.year, r.first_month, 1)
        end = month_bounds(r.year, r.last_month)[1]
        series = f"uysie|URY|exporter|0409|{r.year}|{r.company}"
        _add(ctx, series_key=series, country_iso3="URY", company_name=r.company, location=None,
             role=CompanyRole.EXPORTER, hs_code="0409", measure_kind=MeasureKind.EXACT_VALUE,
             value=r.value_usd, currency="USD", value_basis="FOB",
             period_start=start, period_end=end, period_label=str(r.year), frequency="YTD" if r.running else "A",
             published_at=None, source_url=url, raw_document_id=raw_id or None,
             data_status=DataStatus.PROVISIONAL if r.running else DataStatus.PUBLISHED, reliability=Reliability.OFFICIAL,
             notes=("Esportazioni di miele naturale NCM 0409 dell'azienda (Uruguay XXI, Sistema de Información "
                    "Estadística, dati della Dirección Nacional de Aduanas): valore FOB in USD dell'anno"
                    + (f", da gennaio al mese indicato ({r.column_label}), provvisorio." if r.running else ".")),
             extra={"ncm": SIE_NCM, "national_total_usd": r.total_usd, "column_label": r.column_label,
                    "months_covered": [r.first_month, r.last_month], "running_year": r.running,
                    "query": {"t": SIE_COMPANY_MODE, "a": window, "ncm": SIE_NCM}, "sie_caption": caption,
                    "web_ui": SIE_BASE})
        return series


# ===========================================================================
# 2) United Kingdom: HMRC UK Trade Info, traders by commodity code (names only)
# ===========================================================================

HMRC_API = "https://api.uktradeinfo.com"
HMRC_WEB_UI = "https://www.uktradeinfo.com/find-uk-traders/"
HMRC_COMMODITY_ID = 4090000          # CN8 04090000 "Natural honey" (api.uktradeinfo.com/Commodity)
HMRC_CN8 = "04090000"
HMRC_WINDOW_MONTHS = 24
HMRC_MAX_PAGES = 5
_UK_POSTCODE_RE = re.compile(r"^([A-Z]{1,2}\d[A-Z\d]?)\s*\d[A-Z]{2}$")
_HMRC_ROLES = {"Import": CompanyRole.IMPORTER, "Export": CompanyRole.EXPORTER}


def postcode_district(postcode: Any) -> str | None:
    """'SY11 3FL' -> 'SY11' (the outward code); anything that is not a UK postcode -> None."""
    m = _UK_POSTCODE_RE.match(_clean(postcode).upper())
    return m.group(1) if m else None


# A line that names a street, a building or a unit, not a town: never kept as the location.
_STREET_RE = re.compile(
    r"\d|\b(ROAD|RD|STREET|ST|LANE|LN|AVENUE|AVE|CLOSE|WAY|DRIVE|DR|TERRACE|TER|PLACE|PL|COURT|CT|CRESCENT|"
    r"GROVE|SQUARE|SQ|ROW|WALK|MEWS|GARDENS|HOUSE|UNIT|UNITS|BUILDING|CENTRE|CENTER|PARK|ESTATE|FARM|FLOOR|"
    r"SUITE|BLOCK|YARD|WHARF|QUAY|PO BOX)\b", re.IGNORECASE)


def hmrc_place(line: Any) -> str | None:
    """A published address line usable as a town-level place, or None (a street, a building, a
    number, a placeholder such as "-", or a fragment of one or two letters)."""
    x = _clean(line).strip(" ,.;-")
    if len(re.sub(r"[^A-Za-z]", "", x)) < 3 or _STREET_RE.search(x):
        return None
    return x


def hmrc_location(trader: dict) -> str | None:
    """Town-level location from HMRC's published address: the last address line after the first
    (street) line that names a place, and the postcode district. Never a street, a building or the
    full postcode: official lists can name private persons."""
    lines = [hmrc_place(trader.get(f"Address{i}")) for i in range(2, 6)]
    place = next((x for x in reversed(lines) if x), "")
    district = postcode_district(trader.get("PostCode"))
    parts = [p for p in (place, district) if p]
    return ", ".join(parts) if parts else None


@dataclass
class HmrcTraderMonth:
    role: CompanyRole
    month: tuple[int, int]
    trader_id: int
    name: str
    location: str | None


def parse_hmrc_traders(payload: Any, entity: str, *, first_month: int) -> tuple[list[HmrcTraderMonth], list[str]]:
    """Rows of one HMRC answer (``/Import`` or ``/Export`` filtered on commodity 4090000, Trader
    expanded). Fails loudly when the answer is not that list or is for another commodity."""
    if not isinstance(payload, dict) or not isinstance(payload.get("value"), list):
        raise CollectorError(f"HMRC {entity}: the answer has no 'value' list (API changed?)")
    role = _HMRC_ROLES[entity]
    out: list[HmrcTraderMonth] = []
    problems: list[str] = []
    for row in payload["value"]:
        if not isinstance(row, dict):
            raise CollectorError(f"HMRC {entity}: unexpected row {row!r}")
        if row.get("CommodityId") != HMRC_COMMODITY_ID:
            raise CollectorError(f"HMRC {entity}: a row is for commodity {row.get('CommodityId')!r}, not "
                                 f"{HMRC_COMMODITY_ID} (the filter was ignored?); nothing stored")
        mid = row.get("MonthId")
        if not isinstance(mid, int) or not (190001 <= mid <= 299912) or not 1 <= mid % 100 <= 12:
            problems.append(f"HMRC {entity}: unreadable month {mid!r}; row skipped")
            continue
        if mid < first_month:
            raise CollectorError(f"HMRC {entity}: month {mid} is before the requested window ({first_month}); "
                                 "the filter was ignored?; nothing stored")
        trader = row.get("Trader")
        tid = row.get("TraderId")
        name = _clean(trader.get("CompanyName")) if isinstance(trader, dict) else ""
        if not isinstance(tid, int) or not name:
            problems.append(f"HMRC {entity} {mid}: a row without trader number or name; skipped")
            continue
        out.append(HmrcTraderMonth(role=role, month=(mid // 100, mid % 100), trader_id=tid, name=name,
                                   location=hmrc_location(trader)))
    return out, problems


def hmrc_extract(rows: list[HmrcTraderMonth]) -> bytes:
    """What is archived of an HMRC answer: month, HMRC trader number, name and location (no street,
    no full postcode), sorted, so identical data gives identical bytes."""
    data = sorted(({"month": f"{r.month[0]}-{r.month[1]:02d}", "role": r.role.value, "trader_id": r.trader_id,
                    "name": r.name, "location": r.location} for r in rows),
                  key=lambda d: (d["role"], d["month"], d["trader_id"]))
    return json.dumps(data, ensure_ascii=False, indent=0).encode("utf-8")


def _shift(ym: tuple[int, int], months: int) -> tuple[int, int]:
    i = ym[0] * 12 + ym[1] - 1 + months
    return i // 12, i % 12 + 1


class UkHmrcHoneyTradersCollector(Collector):
    key = "uk_hmrc_honey_traders"
    name = "Regno Unito – HMRC (UK Trade Info): importatori ed esportatori di miele (codice 04090000), solo nomi"
    publisher = "HM Revenue & Customs (HMRC), UK Trade Info"
    homepage = HMRC_WEB_UI
    kind = SourceKind.API
    reliability = Reliability.OFFICIAL
    category = "companies"
    country_iso3 = "GBR"
    language = "en"
    expected_update = "Mensile (circa 6 settimane dopo il mese); controllo settimanale"
    expected_update_en = "Monthly (about 6 weeks after the month); checked weekly"
    expected_max_age_days = 80
    terms_note = ("HMRC UK Trade Info, 'Find UK traders' (api.uktradeinfo.com, open data). Businesses that imported or "
                  "exported commodity 04090000 in a month, with registered name and address. HMRC publishes no "
                  "quantities or values for traders, nor their VAT/EORI numbers or partner countries, and omits "
                  "traders who asked to be removed: names only, never ranked. Paladex stores the name and a "
                  "town-level location (last address line, postcode district), never the street or full postcode.")
    schedule = {"trigger": "cron", "day_of_week": "fri", "hour": 8, "minute": 20}
    order = 62

    def collect(self, ctx: CollectContext) -> None:
        ref = today()
        first = _shift((ref.year, ref.month), -HMRC_WINDOW_MONTHS)
        first_id = first[0] * 100 + first[1]
        rows: list[HmrcTraderMonth] = []
        urls: dict[str, str] = {}
        for entity in ("Import", "Export"):
            got, url = self._pull(ctx, entity, first_id)
            rows += got
            urls[entity] = url
        if not rows:
            ctx.warn(f"HMRC lists no honey (04090000) importer or exporter since {first[0]}-{first[1]:02d}")
            return
        raw_id, unchanged = ctx.store_raw(urls["Import"], hmrc_extract(rows), "application/json",
                                          title=f"HMRC traders of commodity {HMRC_CN8} (natural honey) since {first_id}")
        if unchanged and not ctx.force and _has_rows(ctx):
            log.info("[%s] HMRC trader lists unchanged since the last run", self.key)
            return
        seen: set[tuple[str, int, tuple[int, int]]] = set()
        present: set[str] = set()
        for r in rows:
            k = (r.role.value, r.trader_id, r.month)
            if k in seen:                       # the same trader twice in a month: one record
                continue
            seen.add(k)
            present.add(self._store(ctx, r, raw_id, urls["Import" if r.role == CompanyRole.IMPORTER else "Export"]))
        # Withdraw the trader-months of the months HMRC answered for that are no longer listed.
        latest = max(r.month for r in rows)
        ym = first
        while ym <= latest:
            label = f"{ym[0]}-{ym[1]:02d}"
            for role in (CompanyRole.IMPORTER, CompanyRole.EXPORTER):
                prefix = f"hmrc|GBR|{role.value}|{HMRC_CN8}|{label}|"
                gone = _retire(ctx, prefix, {k for k in present if k.startswith(prefix)})
                if gone:
                    ctx.warn(f"HMRC no longer lists {len(gone)} honey {role.value}(s) for {label}")
            ym = _shift(ym, 1)

    def _pull(self, ctx: CollectContext, entity: str, first_id: int) -> tuple[list[HmrcTraderMonth], str]:
        params: dict | None = {"$filter": f"CommodityId eq {HMRC_COMMODITY_ID} and MonthId ge {first_id}",
                               "$expand": "Trader"}
        url = f"{HMRC_API}/{entity}"
        out: list[HmrcTraderMonth] = []
        first_url = None
        for _ in range(HMRC_MAX_PAGES):
            doc = ctx.fetch(url, params=params, headers={"Accept": "application/json"}, store=False)
            first_url = first_url or doc.url
            try:
                payload = doc.json()
            except ValueError as exc:
                raise CollectorError(f"HMRC {entity}: the answer is not JSON ({exc})") from exc
            got, problems = parse_hmrc_traders(payload, entity, first_month=first_id)
            for p in problems:
                ctx.warn(p)
            out += got
            nxt = payload.get("@odata.nextLink")
            if not nxt:
                return out, first_url
            url, params = str(nxt), None
        raise CollectorError(f"HMRC {entity}: more than {HMRC_MAX_PAGES} pages of traders (40,000 rows each); "
                             "nothing stored")

    def _store(self, ctx: CollectContext, r: HmrcTraderMonth, raw_id: int, url: str) -> str:
        label = f"{r.month[0]}-{r.month[1]:02d}"
        start, end = month_bounds(*r.month)
        series = f"hmrc|GBR|{r.role.value}|{HMRC_CN8}|{label}|{r.trader_id}"
        what = "importato" if r.role == CompanyRole.IMPORTER else "esportato"
        _add(ctx, series_key=series, country_iso3="GBR", company_name=r.name, location=r.location,
             role=r.role, hs_code=HMRC_CN8, measure_kind=MeasureKind.NONE,
             period_start=start, period_end=end, period_label=label, frequency="M", published_at=None,
             source_url=url, raw_document_id=raw_id or None, data_status=DataStatus.PUBLISHED,
             reliability=Reliability.OFFICIAL,
             notes=(f"Azienda che ha {what} miele naturale (codice 04090000) nel mese, secondo le dichiarazioni "
                    "doganali (HMRC, UK Trade Info). HMRC non pubblica quantità né valori per azienda."),
             extra={"trader_id": r.trader_id, "cn8": HMRC_CN8, "web_ui": HMRC_WEB_UI})
        return series


# ===========================================================================
# 3) India: Export Inspection Council, establishments approved for honey export (register, names only)
# ===========================================================================

EIC_API = "https://eicindia.gov.in/api/facilities"
EIC_WEB_UI = "https://eicindia.gov.in/offerings/commodity-wise-facilities?tab=animal"
EIC_CATEGORY = "honey"
EIC_HS = "0409"

_IN_STATES = (
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat", "Haryana",
    "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
    "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura",
    "Uttar Pradesh", "Uttarakhand", "West Bengal", "Delhi", "Jammu and Kashmir", "Ladakh", "Chandigarh", "Puducherry",
)
_IN_STATE_RE = [(re.compile(r"\b" + re.escape(s).replace(r"\ ", r"\s+") + r"\b", re.IGNORECASE), s) for s in _IN_STATES]
# Abbreviations as EIC writes them ("Sonepat, (HR)- 131001", "Saharanpur-247340,U.P.", "Bijnor (UP)-246722").
_IN_STATE_RE += [(re.compile(r"\bU\.\s?P\b\.?|\bUP\b"), "Uttar Pradesh"), (re.compile(r"\bHR\b"), "Haryana"),
                 (re.compile(r"\bUttaranchal\b", re.IGNORECASE), "Uttarakhand"),
                 (re.compile(r"\bOrissa\b", re.IGNORECASE), "Odisha")]
# PIN code -> state, only for the two-digit prefixes that belong to one state (24xxxx and 26xxxx are
# shared by Uttar Pradesh and Uttarakhand, 40xxxx by Maharashtra and Goa...: no guess for those).
_IN_PIN2 = {"11": "Delhi", "12": "Haryana", "13": "Haryana", "14": "Punjab", "15": "Punjab", "17": "Himachal Pradesh",
            **{str(p): "Rajasthan" for p in range(30, 35)}, **{str(p): "Gujarat" for p in range(36, 40)},
            **{str(p): "Madhya Pradesh" for p in range(45, 49)}, **{str(p): "Karnataka" for p in range(56, 60)},
            **{str(p): "Kerala" for p in range(67, 70)}, **{str(p): "Odisha" for p in range(75, 78)}, "78": "Assam"}
_IN_PIN_RE = re.compile(r"(?<!\d)(\d{3})\s?(\d{3})(?!\d)")


def india_state(address: Any) -> str | None:
    """The Indian state of a published address: the state name (or EIC's abbreviation) written last in
    it, else the state of its PIN code when the PIN prefix belongs to a single state, else None. Only the
    state is kept: never the street, the village or the PIN."""
    text = _clean(address)
    best: tuple[int, str] | None = None
    for rx, state in _IN_STATE_RE:
        for m in rx.finditer(text):
            if best is None or m.end() > best[0]:
                best = (m.end(), state)
    if best:
        return best[1]
    pins = _IN_PIN_RE.findall(text)
    return _IN_PIN2.get(pins[-1][0][:2]) if pins else None


def _eic_date(s: Any) -> str | None:
    """'05/03/2027' or '19.02.2027' (day first, as EIC writes it) -> '2027-03-05'; anything else -> None."""
    m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", _clean(s))
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        return None


def _eic_eu(approved_for: str) -> bool | None:
    """EIC's market field: 'All Countries Including European Union' -> True, 'Non-EU' /
    'Non-European Union Countries Only' -> False, anything else -> None (unknown)."""
    t = re.sub(r"[\s-]+", " ", approved_for.lower())
    if re.search(r"\bnon\b", t):
        return False
    if "european union" in t or re.fullmatch(r"(all countries including )?eu", t):
        return True
    return None


@dataclass
class EicEstablishment:
    eic_id: int | None
    name: str
    state: str | None
    approval_no: str
    valid_until: str | None          # ISO date, None when EIC's date cannot be read
    valid_until_raw: str
    approved_for: str                # as published
    eu_approved: bool | None
    scope: str


def parse_eic_facilities(payload: Any) -> tuple[list[EicEstablishment], int, list[str]]:
    """The honey establishments of one EIC answer (the whole approved-facilities register): (active
    honey rows, rows in the answer, problems). Fails loudly when the answer is not that register."""
    if not isinstance(payload, list) or not payload:
        raise CollectorError("EIC approved facilities: the answer is not a non-empty list (API changed?); nothing stored")
    if not all(isinstance(r, dict) and "category_id" in r and "name" in r for r in payload):
        raise CollectorError("EIC approved facilities: rows without 'category_id' or 'name' (format changed?); "
                             "nothing stored")
    out: list[EicEstablishment] = []
    problems: list[str] = []
    seen: dict[str, EicEstablishment] = {}
    clash: set[str] = set()
    for r in payload:
        if _clean(r.get("category_id")).lower() != EIC_CATEGORY:
            continue
        if r.get("is_active") in (0, False, "0"):
            continue
        name, no = _clean(r.get("name")), _clean(r.get("approval_no"))
        if not name or not no:
            problems.append(f"EIC honey: a row without name or approval number ({name or no or r.get('id')!r}); skipped")
            continue
        approved_for = _clean(r.get("country"))
        e = EicEstablishment(eic_id=r.get("id") if isinstance(r.get("id"), int) else None, name=name,
                             state=india_state(r.get("address")), approval_no=no,
                             valid_until=_eic_date(r.get("valid_upto")), valid_until_raw=_clean(r.get("valid_upto")),
                             approved_for=approved_for, eu_approved=_eic_eu(approved_for), scope=_clean(r.get("scope")))
        if no in seen:
            if seen[no].name != name:
                clash.add(no)
            continue
        seen[no] = e
        out.append(e)
    for no in sorted(clash):
        problems.append(f"EIC honey: approval number {no!r} is listed for two different names; not stored")
    return [e for e in out if e.approval_no not in clash], len(payload), problems


def eic_extract(rows: list[EicEstablishment]) -> bytes:
    """What is archived of the EIC answer: the stored fields of the honey rows (no address), sorted."""
    data = sorted(({"approval_no": e.approval_no, "name": e.name, "state": e.state, "valid_upto": e.valid_until_raw,
                    "approved_for": e.approved_for, "scope": e.scope, "eic_id": e.eic_id} for e in rows),
                  key=lambda d: d["approval_no"])
    return json.dumps(data, ensure_ascii=False, indent=0).encode("utf-8")


class InEicHoneyEstablishmentsCollector(Collector):
    key = "in_eic_honey_establishments"
    name = "India – Export Inspection Council: stabilimenti autorizzati all'esportazione di miele (registro, solo nomi)"
    name_en = "India – Export Inspection Council: establishments approved for honey export (register, names only)"
    publisher = "Export Inspection Council of India (EIC), Ministry of Commerce and Industry"
    homepage = EIC_WEB_UI
    kind = SourceKind.API
    reliability = Reliability.OFFICIAL
    category = "companies"
    country_iso3 = "IND"
    language = "en"
    expected_update = "Registro aggiornato da EIC senza calendario; controllo settimanale"
    expected_update_en = "Register updated by EIC without a fixed calendar; checked weekly"
    expected_max_age_days = 40
    terms_note = ("Export Inspection Council of India, 'Commodity wise facilities' (eicindia.gov.in), read from the JSON "
                  "the public page itself loads. Establishments approved by EIC to process honey for export, with EIC "
                  "approval number, validity and markets (all countries including the EU, or non-EU only). A register: "
                  "no quantities or values, never ranked. Paladex keeps the name and the state, never the address.")
    schedule = {"trigger": "cron", "day_of_week": "tue", "hour": 8, "minute": 45}
    order = 63

    def collect(self, ctx: CollectContext) -> None:
        ref = today()
        label = f"{ref.year}-{ref.month:02d}"
        prefix = f"eic|IND|{CompanyRole.REGISTERED_EXPORTER.value}|{EIC_HS}|{label}|"
        doc = ctx.fetch(EIC_API, headers={"Accept": "application/json"}, store=False)
        try:
            payload = doc.json()
        except ValueError as exc:
            raise CollectorError(f"EIC approved facilities: the answer is not JSON ({exc})") from exc
        rows, total, problems = parse_eic_facilities(payload)
        for p in problems:
            ctx.warn(p)
        if not rows:
            ctx.warn(f"EIC lists no active honey establishment among its {total} approved facilities")
            return
        raw_id, unchanged = ctx.store_raw(doc.url, eic_extract(rows), "application/json",
                                          title=f"EIC establishments approved for honey export ({len(rows)}), {ref.isoformat()}")
        if unchanged and not ctx.force and _has_prefix(ctx, prefix):
            log.info("[%s] EIC honey register unchanged since the last run this month", self.key)
            return
        start, end = month_bounds(ref.year, ref.month)
        present: set[str] = set()
        for e in rows:
            series = prefix + e.approval_no
            present.add(series)
            markets = ("tutti i paesi, Unione europea compresa" if e.eu_approved
                       else "solo paesi extra-UE" if e.eu_approved is False else f"«{e.approved_for}»")
            _add(ctx, series_key=series, country_iso3="IND", company_name=e.name, location=e.state,
                 role=CompanyRole.REGISTERED_EXPORTER, hs_code=EIC_HS, measure_kind=MeasureKind.NONE,
                 period_start=start, period_end=end, period_label=label, frequency="register", published_at=None,
                 source_url=doc.url, raw_document_id=raw_id or None, data_status=DataStatus.PUBLISHED,
                 reliability=Reliability.OFFICIAL,
                 notes=("Stabilimento autorizzato dall'Export Inspection Council (ministero del Commercio indiano) a "
                        f"lavorare miele per l'esportazione, per: {markets}. Elenco ufficiale: nessuna quantità né "
                        "valore; presente nel registro nel mese indicato."),
                 extra={"register_no": e.approval_no, "approval_no": e.approval_no, "valid_until": e.valid_until,
                        "valid_until_published": e.valid_until_raw, "approved_for": e.approved_for,
                        "eu_approved": e.eu_approved, "scope": e.scope, "eic_id": e.eic_id, "web_ui": EIC_WEB_UI})
        gone = _retire(ctx, prefix, present)
        if gone:
            ctx.warn(f"EIC no longer lists {len(gone)} honey establishment(s) in {label}: "
                     f"{', '.join(k.rsplit('|', 1)[-1] for k in gone[:10])}")


# ===========================================================================
# 4) Canada: ISED Canadian Importers Database, major importers of HS6 040900 (names only)
# ===========================================================================

CID_REPORT_URL = "https://www.ised-isde.canada.ca/app/ixb/cid-bdic/productReport.html"
CID_HS6 = "040900"


@dataclass
class CidImporter:
    name: str
    city: str | None
    province: str | None

    @property
    def location(self) -> str | None:
        parts = [p for p in (self.city, self.province) if p]
        return ", ".join(parts) if parts else None


@dataclass
class CidReport:
    year: int
    importers: list[CidImporter]
    total_value_cad: float | None        # "All" row of the market-concentration table (all importers)
    listed_share_pct: float | None       # cumulative % of the concentration row for as many importers as listed
    problems: list[str]


def _num(s: str) -> float | None:
    x = re.sub(r"[,\s%$]", "", s)
    try:
        return float(x)
    except ValueError:
        return None


def parse_cid_report(content: bytes) -> CidReport:
    """Parse one CID product report (``productReport.html?hsCode=040900``): the year and the major
    importers (name, city, province; the postal code is not kept), plus the published import total.
    Fails loudly when the page is not the honey report or its importer table cannot be read."""
    soup = BeautifulSoup(content, "lxml")
    title = _clean(soup.title.get_text() if soup.title else "")
    if not title.startswith(CID_HS6):
        raise CollectorError(f"CID: the page is not the report for HS6 {CID_HS6} (title {title!r}); nothing stored")
    table = next((t for t in soup.find_all("table") if t.caption
                  and "major canadian importers" in _clean(t.caption.get_text()).lower()), None)
    if table is None:
        raise CollectorError("CID: no 'Major Canadian importers' table (page layout changed?); nothing stored")
    m = re.search(r"\bin\s+((?:19|20)\d{2})\b", _clean(table.caption.get_text()))
    if not m:
        raise CollectorError("CID: the importer table does not state its year (caption changed?); nothing stored")
    heads = [_clean(th.get_text()).lower() for th in table.find_all("th")]
    if len(heads) < 3 or not heads[0].startswith("company name") or heads[1] != "city" or heads[2] != "province":
        raise CollectorError(f"CID: unexpected importer table columns {heads!r}; nothing stored")
    importers: list[CidImporter] = []
    problems: list[str] = []
    body = table.find("tbody") or table
    for tr in body.find_all("tr"):
        cells = [_clean(td.get_text()) for td in tr.find_all("td")]
        if not cells:
            continue
        if len(cells) != len(heads) or not cells[0]:
            problems.append(f"CID: unreadable importer row {cells!r}; skipped")
            continue
        importers.append(CidImporter(name=cells[0], city=cells[1] or None, province=cells[2] or None))
    total = share = None
    conc = next((t for t in soup.find_all("table") if t.caption
                 and _clean(t.caption.get_text()).lower() == "market concentration"), None)
    if conc is not None:
        for tr in conc.find_all("tr"):
            cells = [_clean(td.get_text()) for td in tr.find_all("td")]
            if len(cells) != 3:
                continue
            if cells[0].lower() == "all":
                total = _num(cells[1])
            elif cells[0].isdigit() and int(cells[0]) == len(importers):
                share = _num(cells[2])
    return CidReport(year=int(m.group(1)), importers=importers, total_value_cad=total, listed_share_pct=share,
                     problems=problems)


def cid_extract(report: CidReport) -> bytes:
    """What is archived of the CID page: year, published total, and name, city, province of each importer."""
    data = {"hs6": CID_HS6, "year": report.year, "total_value_cad": report.total_value_cad,
            "listed_share_pct": report.listed_share_pct,
            "importers": [{"name": i.name, "city": i.city, "province": i.province} for i in report.importers]}
    return json.dumps(data, ensure_ascii=False, indent=0).encode("utf-8")


class CaCidHoneyImportersCollector(Collector):
    key = "ca_cid_honey_importers"
    name = "Canada – ISED, Canadian Importers Database: principali importatori di miele (HS 040900), solo nomi"
    name_en = "Canada – ISED, Canadian Importers Database: major honey importers (HS 040900), names only"
    publisher = "Innovation, Science and Economic Development Canada (ISED); data: Canada Border Services Agency"
    homepage = f"{CID_REPORT_URL}?hsCode={CID_HS6}"
    kind = SourceKind.HTML
    reliability = Reliability.OFFICIAL
    category = "companies"
    country_iso3 = "CAN"
    language = "en"
    expected_update = "Annuale (i dati di un anno escono circa 17 mesi dopo); controllo mensile"
    expected_update_en = "Annual (a year's data appear about 17 months later); checked monthly"
    expected_max_age_days = 730
    terms_note = ("ISED Canadian Importers Database, product report HS6 040900 (Open Government Licence - Canada). The "
                  "'major importers' are the companies that together account for up to 80% of the import value of the "
                  "year; the CID excludes individuals and publishes no value per company: names only, alphabetical, "
                  "never ranked. The importer is not necessarily the end user. Paladex keeps name, city and province, "
                  "not the postal code.")
    schedule = {"trigger": "cron", "day": "3", "hour": 9, "minute": 5}
    order = 64

    def collect(self, ctx: CollectContext) -> None:
        doc = ctx.fetch(CID_REPORT_URL, params={"hsCode": CID_HS6}, headers={"Accept": "text/html"}, store=False)
        report = parse_cid_report(doc.content)
        for p in report.problems:
            ctx.warn(p)
        if not report.importers:
            ctx.warn(f"CID lists no major honey importer for {report.year}")
            return
        raw_id, unchanged = ctx.store_raw(doc.url, cid_extract(report), "application/json",
                                          title=f"CID major importers of HS6 {CID_HS6} (natural honey), {report.year}")
        prefix = f"cacid|CAN|{CompanyRole.IMPORTER.value}|{CID_HS6}|{report.year}|"
        if unchanged and not ctx.force and _has_prefix(ctx, prefix):
            log.info("[%s] CID honey importers unchanged since the last run", self.key)
            return
        present: set[str] = set()
        dupes = {i.name for i in report.importers if sum(j.name == i.name for j in report.importers) > 1}
        for name in sorted(dupes):
            ctx.warn(f"CID: {name!r} is listed more than once for {report.year}; one record kept")
        for imp in report.importers:
            series = prefix + imp.name
            if series in present:
                continue
            present.add(series)
            _add(ctx, series_key=series, country_iso3="CAN", company_name=imp.name, location=imp.location,
                 role=CompanyRole.IMPORTER, hs_code=CID_HS6, measure_kind=MeasureKind.NONE,
                 period_start=date(report.year, 1, 1), period_end=date(report.year, 12, 31),
                 period_label=str(report.year), frequency="A", published_at=None, source_url=doc.url,
                 raw_document_id=raw_id or None, data_status=DataStatus.PUBLISHED, reliability=Reliability.OFFICIAL,
                 notes=("Tra i principali importatori di miele naturale (HS 040900) del Canada nell'anno: le aziende che "
                        "insieme fanno fino all'80% del valore importato (Canadian Importers Database, ISED, dati della "
                        "dogana). Nessun valore per azienda; l'importatore non è necessariamente l'utilizzatore finale."),
                 extra={"hs6": CID_HS6, "total_value_cad": report.total_value_cad,
                        "listed_importers": len({i.name for i in report.importers}),
                        "listed_share_pct": report.listed_share_pct, "web_ui": f"{CID_REPORT_URL}?hsCode={CID_HS6}"})
        gone = _retire(ctx, prefix, present)
        if gone:
            ctx.warn(f"CID no longer lists {len(gone)} honey importer(s) for {report.year}: "
                     f"{', '.join(k.rsplit('|', 1)[-1] for k in gone[:10])}")
