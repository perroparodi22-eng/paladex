"""United Kingdom, official honey trade: HMRC Overseas Trade Statistics (OTS). One collector.

``uk_hmrc_honey``: HM Revenue & Customs, *Overseas Trade Statistics*, read through HMRC's open
uktradeinfo API (https://api.uktradeinfo.com, OData v4, no key, documented at
https://www.uktradeinfo.com/api-documentation/; content under the Open Government Licence v3.0).
Monthly UK imports and exports of natural honey (heading 0409; the UK publishes one CN8 line,
04090000 "Natural honey", and no national subdivision) by partner country: statistical value in
GBP and net mass in kg, as published. The UK left Eurostat's coverage in 2021, so this is the only
monthly official source for the UK.

Route (checked live on 2026-11-05)
----------------------------------
The API allows ``$filter``, ``$select``, ``$expand``, ``$apply``, ``$top``, ``$count`` and ``$format``
(``$orderby`` is refused with HTTP 403 and an HTML page "Your request has been rejected", the same
answer as the 60-requests-per-minute limit). Answers over 40,000 items are paginated with
``@odata.nextLink``. Per run:

* ``GET /Date?$filter=MonthId ge Y0001`` (about 5 KB): HMRC's month table ends at the newest month
  loaded (202608 on 2026-11-05). Nothing else is requested when that month is already stored.
* When a new month is out (once a month): ``/FlowType`` (the four flow types, checked by name),
  ``/Commodity?$filter=Hs4Code eq '0409'`` (the honey codes, checked by description),
  ``/Country`` with ``$select`` (26 KB: HMRC's partner codes, ISO alpha-2 and names), the GOV.UK
  content API for the release page (its publication date), and ONE OTS query::

      /OTS?$apply=filter((CommodityId eq 4090000) and MonthId ge 202301 and MonthId le 202608)
            /groupby((MonthId,FlowTypeId,SuppressionIndex,CommodityId,CountryId),
                     aggregate(Value with sum as Value,NetMass with sum as NetMass))

  OTS rows are published by partner AND port; the groupby sums the ports on HMRC's server (2,313
  rows, 330 KB for 2023-01..2026-08). Checked live: identical, row by row, to summing the 4,758
  per-port rows ourselves.

What is stored
--------------
* Reporter GBR, one trade row per partner, month and flow: imports valued **CIF** by **country of
  consignment** (HMRC: "the country from which the goods were originally dispatched to the UK
  without any commercial transaction in any intermediate country"; not necessarily the country of
  origin), exports valued **FOB** by declared country of destination. Currency GBP as published;
  USD/EUR come from ECB rates (``services.fx``, monthly average cross rate).
* HMRC splits each flow into "EU" and "Non-EU" flow types (EU trade: GB customs declarations plus
  Northern Ireland Intrastat). The split is kept in ``extra`` (``hmrc_flow_types`` on each partner
  row, ``eu`` / ``non_eu`` sub-totals on the total row), never as separate partner rows.
* Partner ``WLD``: the sum of every honey row HMRC publishes for the month (all partners, both flow
  types). The API has no total record; HMRC's own tables total the same rows. Low-value
  consignments (customs declarations of £873 or less) and Northern Ireland Intrastat estimates are
  aggregated by HMRC outside commodity codes, so they are not in any honey figure.
* IMPORT_UNIT_VALUE (CIF GBP / kg, origin = partner as country of consignment, market GBR) and
  EXPORT_UNIT_VALUE (FOB GBP / kg, origin GBR, market = partner) when at least
  ``MIN_UNIT_VALUE_WEIGHT_KG`` moved. None for the world total.
* Partners are mapped from HMRC's ISO alpha-2 code (``CountryCodeAlpha``; HMRC still uses XS for
  Serbia and XK for Kosovo) and cross-checked against HMRC's English name: a disagreement keeps the
  row in the total only, with a warning. HMRC's pseudo-partners (stores and provisions QR/QS,
  low-value aggregates ZY/QV, estimates QV, "Confidential Country", "Other ..." regions, Ceuta,
  Melilla, polar and oceanic regions) are not countries: they stay in the total
  (``extra["not_allocated"]``).
* Suppression. HMRC publishes a suppression index per row (0 = none; 1-5 as documented on the API
  page). No honey row of 2023-2026 is suppressed. Rows with index 3, 4 or 5 carry no published
  quantity: their weight is stored as unknown (never 0) and no unit value is derived.

Status and dates
----------------
* HMRC releases the first provisional estimate of month M about six weeks later and revises "all
  previously published" data of the open periods at every release. Release notes checked
  (2025-06 to 2026-08 months of account): the previous year stays open up to the release of the
  June figures (mid-August) and closes with the July figures (mid-September). So: the newest data
  year, and the year before while the newest month is January-June, are stored ``provisional``;
  earlier years ``published``. A status change, like any changed figure, is a new revision
  (``services.ingest``); a partner-month HMRC no longer shows is withdrawn and kept in the history.
  HMRC also makes unscheduled corrections to closed years (e.g. exports March 2024 onwards,
  15 January 2026), always on a release day, so every release re-reads the whole window.
* ``published_at``: the API gives no date. The release date of the newest month is read from the
  GOV.UK content API (``first_published_at`` of "UK overseas trade in goods statistics: <Month>
  <Year>", 2026-10-15 09:30 for August 2026) and given to the rows of the open periods that this
  release published or revised. Rows of closed years carry no publication date.

Schedule
--------
HMRC publishes on a weekday between the 11th and the 16th at 09:30 UK time (12 Nov 2026, 11 Dec
2026, 15 Jan 2027 per the release notes). The check runs on weekdays from the 11th to the 18th at
11:41 Rome time: one 6 KB request until the new month appears, then 6 requests (~390 KB).
Backfill: the newest data year and the three calendar years before it (2023-01..2026-08 on
2026-11-05). First live run (2026-11-05): 6 requests, 4,063 rows, 78 s (mostly ingest and ECB
conversion of the new rows); a run with nothing new: 1 request.

Cross-checks (2026-11-05, figures already in the database)
---------------------------------------------------------
* UN Comtrade / FAOSTAT, UK imports: HMRC 50,923.0 / 60,303.8 / 58,974.9 t (2023 / 2024 / 2025) against
  Comtrade 50,969.4 / 60,306.6 / 58,977.7 t and FAOSTAT 50,927.2 / 60,305.2 t: within 0.1 % (later HMRC
  corrections). In USD (ECB monthly cross rates) 111.7 / 124.3 / 130.2 M against Comtrade 111.7 / 123.1 /
  130.2 M. Exports: 2,272.3 / 2,323.7 t against FAOSTAT 2,274.3 / 2,324.2 t.
* Eurostat, EU member states' exports to GB against HMRC imports consigned from the EU: 4,433 vs 6,440 t
  (2023), 5,312 vs 6,306 t (2024), 5,948 vs 5,877 t (2025). Spain, Italy, Greece, Hungary, Bulgaria and
  Belgium (2024-25) agree within a few percent at the same unit values; the gap sits in cheap honey
  "consigned" from Germany, France and Poland (HMRC 2.2-3.7 EUR/kg against Eurostat's 4-10 EUR/kg), which
  points to non-EU honey dispatched from EU warehouses (outside the member states' export statistics);
  Eurostat's partner GB also excludes Northern Ireland (XI), which HMRC includes. Not resolved here.
* Exporters' own statistics against HMRC imports: Argentina (INDEC) shows 372 / 493 t to GBR in
  2024 / 2025 against HMRC 944 / 1,095 t, because INDEC masks GBR in most months (statistical secrecy);
  Brazil (Comex Stat) 999 / 850 t against 1,119 / 722 t (shipping lag, consignment basis); Chile 64.3 t
  against 64.1 t (2024). US Census imports from GBR 95 / 145 t against HMRC exports to the USA
  103 / 200 t (2024 / 2025).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from dateutil.parser import isoparse

from ..enums import DataStatus, PriceType, Reliability, SourceKind, TradeFlow, Variety
from ..models import PriceObservation, utcnow
from ..reference.countries import AGGREGATES, country_name, lookup_iso3
from .base import CollectContext, Collector, CollectorError, FetchResult, month_bounds
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

log = logging.getLogger(__name__)

API_BASE = "https://api.uktradeinfo.com"
DATE_URL = f"{API_BASE}/Date"
FLOWTYPE_URL = f"{API_BASE}/FlowType"
COMMODITY_URL = f"{API_BASE}/Commodity"
COUNTRY_URL = f"{API_BASE}/Country"
OTS_URL = f"{API_BASE}/OTS"
API_DOCS_URL = "https://www.uktradeinfo.com/api-documentation/"
GOVUK_CONTENT_URL = "https://www.gov.uk/api/content/government/statistics/uk-overseas-trade-in-goods-statistics-"
GOVUK_PAGE_URL = "https://www.gov.uk/government/statistics/uk-overseas-trade-in-goods-statistics-"
JSON_HEADERS = {"Accept": "application/json"}

HONEY_HS4 = "0409"
HONEY_CN8 = "04090000"
# The newest data year and this many calendar years before it.
BACKFILL_YEARS = 3
# Lower bound of the (small) Date table request, in years before today.
DATE_LOOKBACK_YEARS = 5
# The previous year stays open (provisional) while the newest month is January..this month.
PREVIOUS_YEAR_OPEN_UNTIL_MONTH = 6
# Bumped whenever the parsing changes: the window is then read again once.
PARSER_VERSION = 1
MAX_PAGES = 10

# FlowTypeId -> (flow, area). Checked against /FlowType at every pull.
FLOW_TYPES: dict[int, tuple[str, str]] = {
    1: ("import", "EU"), 2: ("export", "EU"), 3: ("import", "non-EU"), 4: ("export", "non-EU")}
FLOW_TYPE_NAMES = {1: "EU Imports", 2: "EU Exports", 3: "Non-EU Imports", 4: "Non-EU Exports"}
# Suppression indexes whose rows carry no published quantity (API documentation, OTS endpoint).
QUANTITY_SUPPRESSED = frozenset({3, 4, 5})

_MONTH_NAMES = ("january", "february", "march", "april", "may", "june", "july", "august", "september",
                "october", "november", "december")
# HMRC codes that are not ISO 3166-1 (or not countries).
_HMRC_ISO2_OVERRIDES = {"XS": "SRB", "XK": "XKX"}
_PSEUDO_ISO2 = frozenset({"QR", "QS", "QV", "ZY", "XO", "XA", "XR", "XC", "XL"})
_PSEUDO_AREAS = frozenset({"stores and provisions", "low value trade", "confidential region"})
# HMRC spellings the shared name resolver reads as another country.
_HMRC_NAMES = {_norm_name(k): v for k, v in {"Congo (Dem. Rep)": "COD"}.items()}

STATUS_BASIS = ("HMRC revises every open period at each monthly release: the newest data year, and the year "
                "before until the release of the June figures, are provisional; earlier years are final")
PARTNER_BASIS = {"import": "country of consignment (not necessarily the country of origin)",
                 "export": "country of destination as declared at export"}
VALUE_BASIS = {"import": "CIF", "export": "FOB"}
TOTAL_BASIS = ("sum of every OTS honey row HMRC publishes for the month (all partners and ports, EU and non-EU "
               "flow types); the API has no separate total record. Low-value consignments and NI Intrastat "
               "estimates are aggregated by HMRC outside commodity codes and are not included")


def today() -> date:
    """Reference date for the Date-table request (indirection so tests can pin it)."""
    return date.today()


# ===========================================================================
# Pure helpers (tested directly)
# ===========================================================================


def _int(v: Any) -> int | None:
    f = _num(v)
    return int(f) if f is not None and f == int(f) else None


def _values(content: bytes, what: str) -> tuple[list[dict], str | None]:
    """The `value` list of an OData answer and its `@odata.nextLink`. Fails loudly otherwise."""
    if content.lstrip()[:1] == b"<" or b"has been rejected" in content[:300]:
        snippet = re.sub(r"<[^>]+>|\s+", " ", content[:300].decode("utf-8", errors="replace")).strip()
        raise CollectorError(f"uktradeinfo {what}: not a JSON answer ({snippet[:160]!r}); rate limit or refused query?")
    doc = _load_json(content, f"uktradeinfo {what}")
    if not isinstance(doc, dict) or not isinstance(doc.get("value"), list):
        keys = sorted(doc)[:10] if isinstance(doc, dict) else type(doc).__name__
        raise CollectorError(f"uktradeinfo {what}: no 'value' list in the answer ({keys}); format changed?")
    rows = doc["value"]
    if not all(isinstance(r, dict) for r in rows):
        raise CollectorError(f"uktradeinfo {what}: records are not objects (format changed?)")
    nxt = doc.get("@odata.nextLink")
    return rows, nxt if isinstance(nxt, str) and nxt else None


def _require(rows: list[dict], keys: tuple[str, ...], what: str) -> None:
    missing = [k for k in keys if rows and not any(k in r for r in rows)]
    if missing:
        fields = sorted(set().union(*(r.keys() for r in rows)))[:20]
        raise CollectorError(f"uktradeinfo schema drift ({what}): field(s) {missing} missing (fields: {fields}); "
                             "nothing stored")


def parse_month_id(v: Any) -> Month | None:
    i = _int(v)
    if i is None or not 190001 <= i <= 210012 or not 1 <= i % 100 <= 12:
        return None
    return i // 100, i % 100


def parse_dates(content: bytes) -> list[Month]:
    """`/Date`: the months HMRC has loaded, sorted. Fails loudly when none is readable."""
    rows, _ = _values(content, "Date")
    _require(rows, ("MonthId",), "Date")
    months = sorted({m for m in (parse_month_id(r.get("MonthId")) for r in rows) if m})
    if not months:
        raise CollectorError("uktradeinfo Date: no readable month (format changed?)")
    return months


def check_flow_types(content: bytes) -> None:
    """`/FlowType` must still define 1-4 as EU/Non-EU Imports/Exports: the flow mapping depends on it."""
    rows, _ = _values(content, "FlowType")
    _require(rows, ("FlowTypeId", "FlowTypeDescription"), "FlowType")
    seen = {_int(r.get("FlowTypeId")): re.sub(r"\s+", " ", str(r.get("FlowTypeDescription") or "")).strip().lower()
            for r in rows}
    wrong = {i: seen.get(i) for i, name in FLOW_TYPE_NAMES.items() if seen.get(i) != name.lower()}
    if wrong:
        raise CollectorError(f"uktradeinfo FlowType changed: expected {FLOW_TYPE_NAMES}, got {wrong}; nothing stored")


@dataclass(frozen=True)
class HmrcCommodity:
    commodity_id: int
    cn8: str
    description: str


def parse_commodities(content: bytes) -> list[HmrcCommodity]:
    """`/Commodity?$filter=Hs4Code eq '0409'`: the CN8 lines of heading 0409. Fails loudly when
    04090000 is gone or a line is not honey."""
    rows, _ = _values(content, "Commodity")
    _require(rows, ("CommodityId", "Cn8Code", "Hs4Code"), "Commodity")
    out = []
    for r in rows:
        cid, cn8 = _int(r.get("CommodityId")), str(r.get("Cn8Code") or "").strip()
        desc = str(r.get("Cn8LongDescription") or r.get("Hs4Description") or "").strip()
        if str(r.get("Hs4Code") or "").strip() != HONEY_HS4:
            raise CollectorError(f"uktradeinfo Commodity ignored the heading filter (row {r!r:.120}); nothing stored")
        if cid is None or not re.fullmatch(r"\d{8}", cn8) or "honey" not in desc.lower():
            raise CollectorError(f"uktradeinfo Commodity: unexpected honey line {r!r:.160}; nothing stored")
        out.append(HmrcCommodity(cid, cn8, desc))
    if not any(c.cn8 == HONEY_CN8 for c in out):
        raise CollectorError(f"uktradeinfo Commodity: CN8 {HONEY_CN8} not found under heading {HONEY_HS4}; nothing stored")
    return sorted(out, key=lambda c: c.cn8)


@dataclass(frozen=True)
class HmrcCountry:
    country_id: int
    alpha: str
    name: str
    area: str


def parse_countries(content: bytes) -> dict[int, HmrcCountry]:
    rows, _ = _values(content, "Country")
    _require(rows, ("CountryId", "CountryCodeAlpha", "CountryName"), "Country")
    out = {}
    for r in rows:
        cid = _int(r.get("CountryId"))
        if cid is None:
            continue
        out[cid] = HmrcCountry(cid, str(r.get("CountryCodeAlpha") or "").strip().upper(),
                               re.sub(r"\s+", " ", str(r.get("CountryName") or "")).strip(),
                               re.sub(r"\s+", " ", str(r.get("Area1a") or "")).strip())
    if not out:
        raise CollectorError("uktradeinfo Country: no country (format changed?)")
    return out


def map_hmrc_country(alpha: Any, name: Any, area: Any = "") -> tuple[str | None, str]:
    """(ISO3 or None, how) for an HMRC partner. `how` is "iso2", "hmrc_code" (XS Serbia, XK Kosovo),
    "aggregate" (stores, low-value, estimates, confidential, regions, Ceuta / Melilla), "conflict"
    (the published name says another country) or "unknown"."""
    alpha = str(alpha or "").strip().upper()
    name = str(name or "").strip()
    norm = _norm_name(name)
    if (alpha in _PSEUDO_ISO2 or _norm_name(str(area or "")) in _PSEUDO_AREAS or norm.startswith("other ")
            or "confidential" in norm or (not alpha and not norm)):
        return None, "aggregate"
    if alpha in _HMRC_ISO2_OVERRIDES:
        iso3, how = _HMRC_ISO2_OVERRIDES[alpha], "hmrc_code"
    else:
        iso3 = lookup_iso3(alpha) if re.fullmatch(r"[A-Z]{2}", alpha) else None
        how = "iso2"
        if iso3 is None or iso3 in AGGREGATES:
            return None, "unknown"
    by_name = _HMRC_NAMES.get(norm) or resolve_country_name(name)
    if by_name is not None and by_name != iso3:
        return None, "conflict"
    return iso3, how


def hmrc_data_status(year: int, latest: Month) -> DataStatus:
    """Provisional for the open periods (see the module docstring), published for closed years."""
    ly, lm = latest
    if year >= ly or (year == ly - 1 and lm <= PREVIOUS_YEAR_OPEN_UNTIL_MONTH):
        return DataStatus.PROVISIONAL
    return DataStatus.PUBLISHED


def window_for(latest: Month) -> tuple[Month, Month]:
    return (latest[0] - BACKFILL_YEARS, 1), latest


def ots_params(commodity_ids: list[int], start: Month, end: Month) -> dict[str, str]:
    """The OTS query: honey rows of the window, ports summed on HMRC's server."""
    ids = " or ".join(f"CommodityId eq {i}" for i in sorted(commodity_ids))
    lo, hi = start[0] * 100 + start[1], end[0] * 100 + end[1]
    return {"$apply": (f"filter(({ids}) and MonthId ge {lo} and MonthId le {hi})"
                       "/groupby((MonthId,FlowTypeId,SuppressionIndex,CommodityId,CountryId),"
                       "aggregate(Value with sum as Value,NetMass with sum as NetMass))")}


@dataclass
class OtsRow:
    month: Month
    flow_type: int
    suppression: int
    commodity_id: int
    country_id: int
    value: float | None
    net_mass: float | None

    @property
    def flow(self) -> str:
        return FLOW_TYPES[self.flow_type][0]

    @property
    def area(self) -> str:
        return FLOW_TYPES[self.flow_type][1]


@dataclass
class OtsParse:
    rows: list[OtsRow] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    bad: list[tuple[Month, str]] = field(default_factory=list)       # (month, flow) with an unusable row


_OTS_KEYS = ("MonthId", "FlowTypeId", "SuppressionIndex", "CommodityId", "CountryId", "Value", "NetMass")


def parse_ots(content: bytes, commodity_ids: set[int]) -> tuple[OtsParse, str | None]:
    """One page of the OTS groupby answer. Fails loudly on schema drift, on a row of another commodity
    (the filter was ignored) and on an unknown flow type. A row with an unusable value goes to `bad`."""
    rows, nxt = _values(content, "OTS")
    _require(rows, _OTS_KEYS, "OTS")
    out = OtsParse()
    for i, r in enumerate(rows):
        cid = _int(r.get("CommodityId"))
        if cid not in commodity_ids:
            raise CollectorError(f"uktradeinfo OTS ignored the commodity filter (row {i} is {r.get('CommodityId')!r}); "
                                 "nothing stored")
        ft = _int(r.get("FlowTypeId"))
        if ft not in FLOW_TYPES:
            raise CollectorError(f"uktradeinfo OTS: unknown FlowTypeId {r.get('FlowTypeId')!r}; nothing stored")
        month = parse_month_id(r.get("MonthId"))
        country = _int(r.get("CountryId"))
        si = _int(r.get("SuppressionIndex"))
        if month is None or country is None or si is None:
            out.problems.append(f"uktradeinfo OTS row {i}: unreadable month/country/suppression {r!r:.160}; skipped")
            if month is not None:
                out.bad.append((month, FLOW_TYPES[ft][0]))
            continue
        value, mass = _num(r.get("Value")), _num(r.get("NetMass"))
        mass_ok = si in QUANTITY_SUPPRESSED or (mass is not None and mass >= 0)
        if si in QUANTITY_SUPPRESSED:
            mass = None                                  # not published: never read as 0 kg
        if value is None or value < 0 or not mass_ok:
            out.problems.append(f"uktradeinfo OTS {month_label(month)} flow {ft} country {country}: unusable "
                                f"value={r.get('Value')!r} / kg={r.get('NetMass')!r}; not stored")
            out.bad.append((month, FLOW_TYPES[ft][0]))
            continue
        out.rows.append(OtsRow(month, ft, si, cid, country, round(value, 2),
                               None if mass is None else round(mass, 3)))
    return out, nxt


def release_slug(month: Month) -> str:
    return f"{_MONTH_NAMES[month[1] - 1]}-{month[0]}"


def parse_govuk_release(content: bytes, month: Month) -> date | None:
    """Publication date (UK local date) of HMRC's OTS release for `month` from the GOV.UK content
    API, or None when the page is not that release."""
    try:
        doc = _load_json(content, "GOV.UK content")
    except CollectorError:
        return None
    if not isinstance(doc, dict):
        return None
    title = str(doc.get("title") or "").lower()
    if "overseas trade in goods statistics" not in title or _MONTH_NAMES[month[1] - 1] not in title \
            or str(month[0]) not in title:
        return None
    raw = doc.get("first_published_at") or (doc.get("details") or {}).get("first_public_at")
    try:
        return isoparse(str(raw)).date() if raw else None
    except (ValueError, OverflowError):
        return None


# ===========================================================================
# Collector
# ===========================================================================


@dataclass
class _Agg:
    iso3: str
    value: float = 0.0
    kg: float | None = 0.0
    by_area: dict[str, dict] = field(default_factory=dict)
    cn8: dict[str, dict] = field(default_factory=dict)
    countries: list[HmrcCountry] = field(default_factory=list)
    suppression: set[int] = field(default_factory=set)
    how: str = "iso2"

    def add(self, row: OtsRow, cn8: str) -> None:
        self.value += row.value
        self.kg = None if self.kg is None or row.net_mass is None else self.kg + row.net_mass
        for bucket in (self.by_area.setdefault(row.area, {"value_gbp": 0.0, "kg": 0.0}),
                       self.cn8.setdefault(cn8, {"value_gbp": 0.0, "kg": 0.0})):
            bucket["value_gbp"] = round(bucket["value_gbp"] + row.value, 2)
            bucket["kg"] = None if bucket["kg"] is None or row.net_mass is None else round(bucket["kg"] + row.net_mass, 3)
        self.suppression.add(row.suppression)


@dataclass
class _Pull:
    latest: Month
    release_date: date | None
    release_url: str | None
    ots: list[FetchResult]
    commodities: dict[int, HmrcCommodity]
    countries: dict[int, HmrcCountry]
    present: dict[str, set[str]] = field(default_factory=lambda: {"import": set(), "export": set()})
    unsure: dict[str, set[str]] = field(default_factory=lambda: {"import": set(), "export": set()})


class UkHmrcHoneyCollector(Collector):
    key = "uk_hmrc_honey"
    name = "Regno Unito – HMRC: importazioni ed esportazioni di miele per paese (NC8 04090000)"
    name_en = "United Kingdom – HMRC: honey imports and exports by country (CN8 04090000)"
    publisher = "HM Revenue & Customs (United Kingdom) – Overseas Trade Statistics"
    homepage = "https://www.uktradeinfo.com/trade-data/"
    kind = SourceKind.API
    reliability = Reliability.OFFICIAL
    category = "trade"
    country_iso3 = "GBR"
    language = "en"
    expected_update = "Mensile, verso metà mese, circa 6 settimane dopo il mese (HMRC, Overseas Trade Statistics)"
    expected_update_en = "Monthly, mid-month, about 6 weeks after the month (HMRC Overseas Trade Statistics)"
    expected_max_age_days = 40
    terms_note = ("Fonte: HM Revenue & Customs, Overseas Trade Statistics (API uktradeinfo, Open Government Licence "
                  "v3.0: cite HMRC). Statistical value in GBP and net kg, CN8 04090000 (bulk and packaged honey are "
                  "not separated). Imports are CIF by country of consignment (not necessarily the origin), exports "
                  "FOB by destination. The current year (and the previous one until the June figures) is "
                  "provisional and revised at every release; each change is kept as a revision. Unit values are "
                  "derived (value / net kg), not market quotations.")
    # Weekdays from the 11th to the 18th (HMRC publishes between the 11th and the 16th at 09:30 UK
    # time); one 5 KB request when nothing is new (Europe/Rome time).
    schedule = {"trigger": "cron", "day": "11-18", "day_of_week": "mon-fri", "hour": 11, "minute": 41}

    def collect(self, ctx: CollectContext) -> None:
        state = _load_state(ctx)
        lower = (today().year - DATE_LOOKBACK_YEARS) * 100 + 1
        dates = ctx.fetch(DATE_URL, params={"$filter": f"MonthId ge {lower}"}, headers=JSON_HEADERS,
                          title="HMRC uktradeinfo: months loaded (Date)")
        latest = parse_dates(dates.content)[-1]
        start, _ = window_for(latest)
        state["checked_at"] = utcnow().isoformat(timespec="seconds")
        if not (ctx.force or not _has_rows(ctx) or state.get("latest_month") != month_label(latest)
                or state.get("parser") != PARSER_VERSION or state.get("window_start") != month_label(start)):
            log.info("[%s] HMRC newest month %s already stored; nothing to pull", self.key, month_label(latest))
            _save_state(ctx, state)
            return
        pull = self._pull(ctx, state, latest)
        newest = self._store_all(ctx, state, pull)
        state.update({"latest_month": month_label(newest), "window_start": month_label(start),
                      "parser": PARSER_VERSION, "pulled_at": utcnow().isoformat(timespec="seconds"),
                      "release": {"month": month_label(latest),
                                  "published": pull.release_date.isoformat() if pull.release_date else None,
                                  "url": pull.release_url}})
        _save_state(ctx, state)
        ctx.checkpoint()

    # ------------------------------------------------------------------ fetch
    def _pull(self, ctx: CollectContext, state: dict, latest: Month) -> _Pull:
        start, end = window_for(latest)
        release_date, release_url = self._release(ctx, state, latest)
        check_flow_types(ctx.fetch(FLOWTYPE_URL, headers=JSON_HEADERS, title="HMRC uktradeinfo: flow types").content)
        commodities = parse_commodities(ctx.fetch(
            COMMODITY_URL, params={"$filter": f"Hs4Code eq '{HONEY_HS4}'"}, headers=JSON_HEADERS,
            title=f"HMRC uktradeinfo: commodity codes under heading {HONEY_HS4}").content)
        countries = parse_countries(ctx.fetch(
            COUNTRY_URL, params={"$select": "CountryId,CountryCodeAlpha,CountryName,Area1a"}, headers=JSON_HEADERS,
            title="HMRC uktradeinfo: partner country codes").content)
        pages = [ctx.fetch(OTS_URL, params=ots_params([c.commodity_id for c in commodities], start, end),
                           headers=JSON_HEADERS,
                           title=f"HMRC OTS honey (heading {HONEY_HS4}) {month_label(start)}..{month_label(end)}, "
                                 "by month, flow type and partner")]
        while True:
            _, nxt = _values(pages[-1].content, "OTS")
            if not nxt:
                break
            if len(pages) >= MAX_PAGES:
                raise CollectorError(f"uktradeinfo OTS: more than {MAX_PAGES} pages for honey; nothing stored")
            pages.append(ctx.fetch(nxt, headers=JSON_HEADERS, title=f"HMRC OTS honey, page {len(pages) + 1}"))
        return _Pull(latest=latest, release_date=release_date, release_url=release_url, ots=pages,
                     commodities={c.commodity_id: c for c in commodities}, countries=countries)

    def _release(self, ctx: CollectContext, state: dict, latest: Month) -> tuple[date | None, str | None]:
        """Publication date of the release that brought `latest` (GOV.UK). Never fatal."""
        slug = release_slug(latest)
        page = GOVUK_PAGE_URL + slug
        rec = state.get("release") or {}
        if rec.get("month") == month_label(latest) and rec.get("published"):
            return date.fromisoformat(rec["published"]), rec.get("url")
        try:
            doc = ctx.fetch(GOVUK_CONTENT_URL + slug, headers=JSON_HEADERS, accept_status=(200, 404),
                            title=f"GOV.UK: UK overseas trade in goods statistics {slug} (release date)")
        except CollectorError as exc:
            doc = None
            _warn_once(ctx, state, f"release:{slug}", f"HMRC release page for {slug} unreachable ({exc}): rows of the "
                       "open periods are stored without publication date")
        published = parse_govuk_release(doc.content, latest) if doc is not None and doc.status_code == 200 else None
        if doc is not None and published is None:
            _warn_once(ctx, state, f"release:{slug}", f"No GOV.UK release page with a date for HMRC OTS {slug}: rows of "
                       "the open periods are stored without publication date")
        return published, (page if published else None)

    # ------------------------------------------------------------------ store
    def _store_all(self, ctx: CollectContext, state: dict, pull: _Pull) -> Month:
        ids = set(pull.commodities)
        parsed = OtsParse()
        for page in pull.ots:
            p, _ = parse_ots(page.content, ids)
            parsed.rows += p.rows
            parsed.problems += p.problems
            parsed.bad += p.bad
        for msg in parsed.problems:
            ctx.warn(msg)
        start, end = window_for(pull.latest)
        rows = [r for r in parsed.rows if start <= r.month <= end]
        if len(rows) != len(parsed.rows):
            ctx.warn(f"uktradeinfo OTS returned months outside {month_label(start)}..{month_label(end)}; ignored")
        if not rows:
            raise CollectorError(f"uktradeinfo OTS: no honey rows for {month_label(start)}..{month_label(end)}; "
                                 "nothing stored")
        for si in sorted({r.suppression for r in rows} - {0}):
            _warn_once(ctx, state, f"suppression:{si}",
                       f"HMRC suppression index {si} on honey rows: "
                       + ("quantities not published (stored as unknown)" if si in QUANTITY_SUPPRESSED
                          else "partner detail may be withheld (kept as published)"))
        months = sorted({r.month for r in rows})
        newest = months[-1]
        if newest != pull.latest:
            ctx.warn(f"HMRC lists {month_label(pull.latest)} as loaded but publishes no honey row for it yet "
                     f"(newest: {month_label(newest)}); asked again at the next run")
        bad = set(parsed.bad)
        for month in reversed(months):
            for flow in ("import", "export"):
                self._store_month(ctx, state, pull, month, flow, [r for r in rows if r.month == month and r.flow == flow],
                                  bad=(month, flow) in bad)
        for flow in ("import", "export"):
            done = {month_label(m) for m in months} - pull.unsure[flow]

            def price_key(partner: str, label: str, flow=flow) -> str:
                if flow == "import":
                    return f"{PriceType.IMPORT_UNIT_VALUE.value}|hmrc|{partner}|GBR|{label}"
                return f"{PriceType.EXPORT_UNIT_VALUE.value}|hmrc|GBR|{partner}|{label}"

            gone = _retire_absent(ctx, prefix=f"hmrc|GBR|{flow}|", months=done, present=pull.present[flow],
                                  price_key=price_key)
            if gone:
                ctx.warn(f"HMRC no longer shows UK honey {flow}s for {', '.join(gone)}: those rows are withdrawn "
                         "(kept in the history)")
        return newest

    def _store_month(self, ctx: CollectContext, state: dict, pull: _Pull, month: Month, flow: str,
                     rows: list[OtsRow], *, bad: bool) -> None:
        label = month_label(month)
        if bad:
            pull.unsure[flow].add(label)
        if not rows:
            return
        status = hmrc_data_status(month[0], pull.latest)
        p_start, p_end = month_bounds(*month)
        common = {"period_start": p_start, "period_end": p_end, "period_label": label, "frequency": "M",
                  "published_at": pull.release_date if status == DataStatus.PROVISIONAL else None,
                  "data_status": status, "reliability": Reliability.OFFICIAL}
        aggs: dict[str, _Agg] = {}
        total = _Agg("WLD")
        not_allocated: list[dict] = []
        for r in rows:
            cn8 = pull.commodities[r.commodity_id].cn8
            total.add(r, cn8)
            c = pull.countries.get(r.country_id) or HmrcCountry(r.country_id, "", "", "")
            iso3, how = map_hmrc_country(c.alpha, c.name, c.area)
            if iso3 is None:
                not_allocated.append({"hmrc_country_id": c.country_id, "hmrc_code": c.alpha or None,
                                      "name": c.name or None, "flow_type": FLOW_TYPE_NAMES[r.flow_type],
                                      "value_gbp": r.value, "kg": r.net_mass, "why": how})
                self._report_unmapped(ctx, state, c, how)
                if how != "aggregate":
                    pull.unsure[flow].add(label)
                continue
            agg = aggs.setdefault(iso3, _Agg(iso3, how=how))
            agg.add(r, cn8)
            if c not in agg.countries:
                agg.countries.append(c)
        if bad:
            ctx.warn(f"HMRC honey {flow}s of {label} include an unusable row: the month's total is not stored "
                     "and no row of that month is withdrawn")
        for iso3 in sorted(aggs):
            pull.present[flow].add(self._store_partner(ctx, pull, label, flow, aggs[iso3], common))
        if not bad:
            pull.present[flow].add(self._store_total(ctx, pull, label, flow, total, common,
                                                     not_allocated=not_allocated, partners=len(aggs)))

    def _report_unmapped(self, ctx: CollectContext, state: dict, c: HmrcCountry, how: str) -> None:
        label = f"{c.name or '?'} ({c.alpha or '-'}, HMRC {c.country_id})"
        if how == "aggregate":
            _warn_once(ctx, state, f"aggregate:{c.country_id}",
                       f"HMRC partner {label} is not a country: kept only in the total")
            return
        state.setdefault("unknown_partners", {})[str(c.country_id)] = {"code": c.alpha, "name": c.name, "how": how}
        why = "its published name points to another country" if how == "conflict" else "it has no ISO3 mapping"
        _warn_once(ctx, state, f"partner:{c.country_id}:{how}",
                   f"HMRC partner {label}: {why}; its rows stay in the total only until trade_uk is checked")

    def _extra(self, pull: _Pull, flow: str, agg: _Agg) -> dict:
        return {
            "cn8": sorted(agg.cn8) if len(agg.cn8) != 1 else next(iter(agg.cn8)),
            "cn8_lines": agg.cn8 if len(agg.cn8) > 1 else None,
            "commodity_description": "Natural honey",
            "hmrc_flow_types": sorted({FLOW_TYPE_NAMES[i] for i, (f, a) in FLOW_TYPES.items()
                                       if f == flow and a in agg.by_area}),
            "suppression_index": sorted(agg.suppression) if len(agg.suppression) > 1 else next(iter(agg.suppression)),
            "partner_basis": PARTNER_BASIS[flow],
            "status_basis": STATUS_BASIS,
            "release": {"newest_month": month_label(pull.latest),
                        "published": pull.release_date.isoformat() if pull.release_date else None,
                        "page": pull.release_url},
            "bulk_packaged_split": None,
            "api_docs": API_DOCS_URL,
        }

    def _store_partner(self, ctx: CollectContext, pull: _Pull, label: str, flow: str, agg: _Agg, common: dict) -> str:
        value, kg = round(agg.value, 2), None if agg.kg is None else round(agg.kg, 3)
        name = country_name(agg.iso3, "en")
        if name == agg.iso3:
            name = agg.countries[0].name if agg.countries else agg.iso3
        codes = [c.country_id for c in agg.countries]
        extra = {
            **self._extra(pull, flow, agg),
            "hmrc_country_id": codes[0] if len(codes) == 1 else codes,
            "hmrc_code": agg.countries[0].alpha if len(agg.countries) == 1 else [c.alpha for c in agg.countries],
            "partner_name": agg.countries[0].name if len(agg.countries) == 1 else [c.name for c in agg.countries],
            "hmrc_area": agg.countries[0].area if agg.countries else None,
            "mapped_by": agg.how,
            "eu_split": agg.by_area if len(agg.by_area) > 1 else None,
        }
        src = {"source_url": pull.ots[0].url, "raw_document_id": pull.ots[0].raw_document_id or None}
        what = ("Importazioni britanniche di miele naturale (NC8 04090000) da questo paese di spedizione "
                "(HMRC, Overseas Trade Statistics): valore statistico CIF in sterline e peso netto."
                if flow == "import" else
                "Esportazioni britanniche di miele naturale (NC8 04090000) verso questa destinazione "
                "(HMRC, Overseas Trade Statistics): valore statistico FOB in sterline e peso netto.")
        series = f"hmrc|GBR|{flow}|{agg.iso3}|{label}"
        ctx.add_trade(series_key=series, hs_code=HONEY_HS4, reporter_iso3="GBR", partner_iso3=agg.iso3,
                      flow=TradeFlow.IMPORT.value if flow == "import" else TradeFlow.EXPORT.value, currency="GBP",
                      value=value, net_weight_kg=kg, value_basis=VALUE_BASIS[flow], extra=extra, notes=what,
                      **src, **common)
        if flow == "import":
            ptype, origin, origin_label, market, market_label = (PriceType.IMPORT_UNIT_VALUE, agg.iso3, name, "GBR",
                                                                 "United Kingdom")
        else:
            ptype, origin, origin_label, market, market_label = (PriceType.EXPORT_UNIT_VALUE, "GBR", "United Kingdom",
                                                                 agg.iso3, name)
        price_series = f"hmrc|{origin}|{market}|{label}"
        if kg is not None and kg >= MIN_UNIT_VALUE_WEIGHT_KG and value > 0:
            ctx.add_price(
                series_key=price_series, price_type=ptype, variety=Variety.UNSPECIFIED.value,
                price_value=round(value / kg, 4), currency="GBP", unit="kg", origin_iso3=origin,
                origin_label=origin_label, market_iso3=market, market_location=market_label, terms=VALUE_BASIS[flow],
                variety_raw="CN8 04090000 Natural honey (bulk and packaged together)", volume_kg=kg,
                notes=(f"Valore unitario all'{'importazione' if flow == 'import' else 'esportazione'} = valore "
                       f"{VALUE_BASIS[flow]} / peso netto (HMRC, NC8 04090000"
                       + (", paese di spedizione" if flow == "import" else "")
                       + "). Dato doganale derivato, non una quotazione di mercato."),
                extra={**extra, "value_gbp": value, "kg": kg}, **src, **common,
            )
        else:
            # A revision can push a flow below the threshold: its earlier unit value is withdrawn.
            ctx.retire(PriceObservation, f"{ptype.value}|{price_series}")
        return series

    def _store_total(self, ctx: CollectContext, pull: _Pull, label: str, flow: str, total: _Agg, common: dict, *,
                     not_allocated: list[dict], partners: int) -> str:
        extra = {
            **self._extra(pull, flow, total),
            "total_basis": TOTAL_BASIS,
            "eu": total.by_area.get("EU"),
            "non_eu": total.by_area.get("non-EU"),
            "not_allocated": not_allocated or None,
            "partner_rows": partners,
        }
        series = f"hmrc|GBR|{flow}|WLD|{label}"
        ctx.add_trade(
            series_key=series, hs_code=HONEY_HS4, reporter_iso3="GBR", partner_iso3="WLD",
            flow=TradeFlow.IMPORT.value if flow == "import" else TradeFlow.EXPORT.value, currency="GBP",
            value=round(total.value, 2), net_weight_kg=None if total.kg is None else round(total.kg, 3),
            value_basis=VALUE_BASIS[flow], extra=extra, source_url=pull.ots[0].url,
            raw_document_id=pull.ots[0].raw_document_id or None,
            notes=(f"Totale delle {'importazioni' if flow == 'import' else 'esportazioni'} britanniche di miele NC8 "
                   "04090000: somma di tutte le righe pubblicate da HMRC per il mese (UE ed extra-UE, dettaglio "
                   "in 'extra')."),
            **common,
        )
        return series


__all__ = [
    "HmrcCommodity",
    "HmrcCountry",
    "OtsParse",
    "OtsRow",
    "UkHmrcHoneyCollector",
    "check_flow_types",
    "hmrc_data_status",
    "map_hmrc_country",
    "ots_params",
    "parse_commodities",
    "parse_countries",
    "parse_dates",
    "parse_govuk_release",
    "parse_month_id",
    "parse_ots",
    "release_slug",
    "window_for",
]
