"""FAOSTAT (FAO): world honey production, beehives, producer prices and trade, annual.

Source research: docs/research/fao.json. FAOSTAT has exactly one honey item, 1182 "Natural
honey" (no split by floral variety), plus item 1181 "Bees" (beehive counts). The data is
annual and about 12-24 months old: structural context (who produces how much, farm-gate prices,
who trades with whom), never a current market price.

How this collector works
------------------------
* **Change detection (no account).** Every run reads the public bulk catalogue
  ``datasets_E.json`` and compares each dataset's ``DateUpdate`` with the value stored in
  ``app_settings`` under ``faostat_dateupdate_<code>``. A dataset is (re)loaded only when its
  ``DateUpdate`` changed, when it was never loaded, or when the run is forced. The stored value is
  written in the same commit as the dataset's rows (``ctx.checkpoint()`` after each dataset), so a
  failed load is retried on the next run.
* **Default path: bulk downloads (no account).** The normalized CSV ZIP of each dataset (URL from
  the catalogue's ``FileLocation``) is streamed to a temporary file and its
  ``*_All_Data_(Normalized).csv`` member is read row by row with the ``csv`` module, keeping only
  the honey item codes; the archive is never extracted nor held in memory (TCL is ~267 MB).
  The honey rows are archived as a small ZIP extract (``RawDocument``) for audit.
  Datasets: QCL (production, beehives), PP (producer prices), TCL (trade totals per country).
  TM (bilateral trade matrix, ~410 MB) is too big for this path and is skipped.
* **Optional token API path.** When ``PALADEX_FAOSTAT_USERNAME`` / ``PALADEX_FAOSTAT_PASSWORD``
  are set, the collector logs in (``POST /auth/login``), caches the JWT for ``ExpiresIn - 60`` s,
  sends it as ``Authorization: Bearer`` (never in a URL), re-logs in once on HTTP 401/403, and
  runs narrow honey queries (``page_size``/``page_number`` paging; requests at least 1.5 s apart
  per host via ``ctx.fetch``, within the research's 1 request/s) for QCL, PP and TCL instead of
  the big ZIPs, plus TM bilateral flows (reporter x partner) for the
  ``TM_REPORTERS`` panel. TM's dimension names and element filter codes are unverified, so they
  are probed first (``/dimensions/TM/``, ``/codes/element/TM``) and the dataset fails loudly when
  the probe does not match. If the login is refused, the run warns and falls back to the bulk
  path (TM skipped).

What is stored
--------------
* QCL -> ``ProductionStat``: metric ``production`` (t) and ``colonies`` (number of beehives).
* PP -> ``PriceObservation`` with ``PriceType.PRODUCER`` (farm-gate, annual national average),
  per tonne (``unit="t"``, so ``price_per_kg`` is per kg). The USD element (5532) is used; the
  local-currency element (5530, LCU) only when FAO publishes no USD value for that country-year
  and the currency in use that year is known (``LOCAL_CURRENCY``), never guessed.
* TCL -> ``TradeFlowObservation`` reporter x ``WLD``; TM -> reporter x partner. Import/export
  quantity (t -> kg) and value (1000 USD -> USD). ``unit_value_per_kg`` is computed by the
  framework. Not turned into price observations: FAO trade is annual and derived from customs data
  that UN Comtrade already provides in more detail.
* Every row: ``published_at`` = dataset ``DateUpdate``; ``source_url`` = bulk ZIP URL or API query
  URL (no credentials); ``data_status`` from the FAOSTAT flag (``FLAG_STATUS``); the raw flag in
  ``ProductionStat.flag_raw`` / ``extra["flag"]``.

Areas: aggregates are skipped (FAO codes >= 5000, list codes such as ``5000>``, 351 "China" =
mainland + Hong Kong + Macao + Taiwan, and TCL's "excluding intra-trade" groups 265/269); 41
"China, mainland" is China. Areas map through ``Area Code (M49)`` when present, else the FAO code
(``lookup_fao``), else the name (``lookup_iso3``). Areas outside Paladex's country table are
skipped and reported once per run in a single warning.
"""
from __future__ import annotations

import csv
import dataclasses
import io
import json
import logging
import math
import os
import tempfile
import time
import zipfile
import zlib
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import IO, Any
from urllib.parse import urlencode, urlsplit

import httpx

from ..api.common import get_setting, set_setting
from ..enums import DataStatus, PriceType, Reliability, SourceKind, TradeFlow, Variety
from ..reference.countries import AGGREGATES, countries, lookup_fao, lookup_iso3
from .base import (
    CollectContext,
    Collector,
    CollectorError,
    FetchResult,
    Offline,
    parse_date,
    year_bounds,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Endpoints (docs/research/fao.json)
# ---------------------------------------------------------------------------
CATALOGUE_URL = "https://bulks-faostat.fao.org/production/datasets_E.json"   # public, no account
API_ROOT = "https://faostatservices.fao.org/api/v1"
API_LANG = "en"
LOGIN_URL = API_ROOT + "/auth/login"
SETTING_PREFIX = "faostat_dateupdate_"          # app_settings key: faostat_dateupdate_<code>

# ---------------------------------------------------------------------------
# What to collect
# ---------------------------------------------------------------------------
HONEY_ITEM = "1182"          # Natural honey (QCL, PP, TCL, TM)
BEES_ITEM = "1181"           # Bees: beehive stocks (QCL)
HS_CODE = "0409"             # HS heading matching FAO item 1182
DATASETS: tuple[str, ...] = ("QCL", "PP", "TCL", "TM")   # processing order; TM needs the API
BULK_ITEMS: dict[str, frozenset[str]] = {
    "QCL": frozenset({HONEY_ITEM, BEES_ITEM}),
    "PP": frozenset({HONEY_ITEM}),
    "TCL": frozenset({HONEY_ITEM}),
}
MIN_YEAR = 1991              # first year kept (post-1991 borders match the country table)
API_REFRESH_YEARS = 10       # API path, dataset already loaded: re-read the last N years only

# TM bilateral panel (API path only): reporter countries whose honey trade is read by partner.
# Destination markets (imports by origin) first, then origins (exports by destination).
TM_REPORTERS: tuple[str, ...] = (
    "ITA", "USA", "DEU", "ESP", "FRA", "BEL", "GBR", "JPN",
    "ARG", "CHN", "UKR", "BRA", "VNM", "IND", "MEX", "URY", "TUR", "HUN", "ROU", "SRB",
)

# API query templates. Element FILTER codes differ from the codes the rows print (2510 -> 5510).
API_QUERIES: dict[str, list[tuple[str, dict[str, str]]]] = {
    "QCL": [
        ("honey production", {"item": HONEY_ITEM, "element": "2510"}),       # rows print 5510
        ("beehive stocks", {"item": BEES_ITEM, "element": "2111"}),          # rows print "Stocks"
    ],
    "PP": [("honey producer prices", {"item": HONEY_ITEM, "element": "5532,5530"})],
    "TCL": [("honey trade", {"item": HONEY_ITEM, "element": "2610,2620,2910,2920"})],
}
API_COMMON_PARAMS: dict[str, str] = {
    "show_codes": "true", "show_unit": "true", "show_flags": "true", "show_notes": "true",
    "null_values": "false", "output_type": "objects",
}
API_PAGE_SIZE = 5000
API_MAX_PAGES = 40

# ---------------------------------------------------------------------------
# Download limits
# ---------------------------------------------------------------------------
DOWNLOAD_CHUNK = 1 << 20                 # 1 MiB
MAX_ZIP_BYTES = 2 * 1024 ** 3            # refuse anything above 2 GiB (TM, the largest, is ~410 MB)
DOWNLOAD_RETRIES = 2
NORMALIZED_SUFFIX = "_All_Data_(Normalized).csv"
REQUIRED_BULK_COLUMNS = ("Area Code", "Area", "Item Code", "Element Code", "Element", "Unit", "Value", "Flag")

# ---------------------------------------------------------------------------
# Areas
# ---------------------------------------------------------------------------
AGGREGATE_AREA_MIN = 5000                # 5000 World, 5100 Africa, 5707 EU27, 57070 ...
SKIP_AREA_CODES: dict[int, str] = {
    351: "China (aggregate of 41 mainland, 96 Hong Kong, 128 Macao, 214 Taiwan)",
    265: "China (excluding intra-trade)",
    269: "European Union (27) (excluding Croatia) (excluding intra-trade)",
}
# FAO areas mapped explicitly. Research: use 186 "Serbia and Montenegro" for Serbia before 2006
# and 272 "Serbia" from 2006 on.
AREA_OVERRIDES: dict[int, str] = {186: "SRB"}
_FAO_CODE_OF: dict[str, int] = {c["iso3"]: c["fao_code"] for c in countries() if c["fao_code"]}

# ---------------------------------------------------------------------------
# Flags -> data_status. Current FAOSTAT flags (harmonised, SDMX-style) plus unambiguous legacy ones.
# ---------------------------------------------------------------------------
FLAG_LABELS: dict[str, str] = {
    "A": "Official figure", "X": "Figure from international organizations", "B": "Time series break",
    "P": "Provisional value", "E": "Estimated value", "I": "Imputed value", "T": "Unofficial figure",
    "F": "Estimate (FAO)", "M": "Missing value (data cannot exist, not applicable)",
    "L": "Missing value; data exist but were not collected", "O": "Missing value",
    "W": "Official figure from country publications (legacy flag)", "*": "Unofficial figure (legacy flag)",
    "Im": "FAO imputation (legacy flag)", "Fc": "Calculated data (legacy flag)",
    "Fm": "Manual estimation (legacy flag)", "Fb": "Data obtained as a balance (legacy flag)",
    "Cv": "Calculated through a conversion factor (legacy flag)",
    "R": "Estimated using trading partners' data (legacy flag)", "NV": "Data not available (legacy flag)",
    "": "Official figure (no flag)",
}
FLAG_STATUS: dict[str, DataStatus] = {
    "": DataStatus.PUBLISHED, "A": DataStatus.PUBLISHED, "X": DataStatus.PUBLISHED, "B": DataStatus.PUBLISHED,
    "W": DataStatus.PUBLISHED,
    "P": DataStatus.PROVISIONAL,
    # Estimated, imputed or unofficial figures are never presented as official statistics.
    "E": DataStatus.ESTIMATE, "I": DataStatus.ESTIMATE, "T": DataStatus.ESTIMATE, "F": DataStatus.ESTIMATE,
    "*": DataStatus.ESTIMATE, "Im": DataStatus.ESTIMATE, "Fc": DataStatus.ESTIMATE, "Fm": DataStatus.ESTIMATE,
    "Fb": DataStatus.ESTIMATE, "Cv": DataStatus.ESTIMATE, "R": DataStatus.ESTIMATE,
}
MISSING_FLAGS = frozenset({"M", "L", "O", "NV"})     # no value: the row is skipped even if a number is printed
_STATUS_RANK = {DataStatus.PUBLISHED: 0, DataStatus.PROVISIONAL: 1, DataStatus.ESTIMATE: 2}

# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------
PRODUCTION_TO_T = {"t": 1.0, "tonnes": 1.0, "tonne": 1.0, "1000 t": 1000.0, "kg": 0.001}
COUNT_TO_NUMBER = {"no": 1.0, "an": 1.0, "head": 1.0, "number": 1.0,
                   "1000 no": 1000.0, "1000 an": 1000.0, "1000 head": 1000.0}
QUANTITY_TO_KG = {"t": 1000.0, "tonnes": 1000.0, "tonne": 1000.0, "1000 t": 1_000_000.0, "kg": 1.0}
VALUE_TO_USD = {"1000 usd": 1000.0, "1000 us$": 1000.0, "usd": 1.0, "us$": 1.0}
PRICE_USD_UNITS = frozenset({"usd", "us$", "usd/t", "usd/tonne", "us$/t", "us$/tonne"})
PRICE_LCU_UNITS = frozenset({"lcu", "lcu/t", "lcu/tonne"})

# Element codes as the ROWS print them (bulk files and API answers), plus the API filter codes.
PRODUCTION_ELEMENTS = frozenset({"5510", "2510"})
STOCKS_ELEMENTS = frozenset({"5111", "5112", "5114", "2111"})
PP_USD_ELEMENTS = frozenset({"5532"})
PP_LCU_ELEMENTS = frozenset({"5530"})
TRADE_ELEMENTS: dict[str, tuple[str, str]] = {   # code -> (flow, measure); display codes unverified
    "5610": ("import", "quantity"), "2610": ("import", "quantity"),
    "5622": ("import", "value"), "2620": ("import", "value"),
    "5910": ("export", "quantity"), "2910": ("export", "quantity"),
    "5922": ("export", "value"), "2920": ("export", "value"),
}
ANNUAL_MONTHS_CODE = "7021"   # PP "Annual value"

# Currency in which FAOSTAT's "Producer Price (LCU/tonne)" is expressed: the local currency in use
# that year. Only the CURRENT currency of each country is listed, from the first full year it was
# in use; earlier years (other currencies, euro transition years) are not converted, never guessed.
LOCAL_CURRENCY: dict[str, tuple[tuple[int, str], ...]] = {
    **{iso3: ((2002, "EUR"),) for iso3 in ("ITA", "ESP", "PRT", "FRA", "DEU", "BEL", "NLD", "LUX", "AUT",
                                           "IRL", "FIN", "GRC", "MNE")},
    "SVN": ((2007, "EUR"),), "CYP": ((2008, "EUR"),), "MLT": ((2008, "EUR"),), "SVK": ((2009, "EUR"),),
    "EST": ((2011, "EUR"),), "LVA": ((2014, "EUR"),), "LTU": ((2015, "EUR"),), "HRV": ((2023, "EUR"),),
    "BGR": ((1999, "BGN"), (2026, "EUR")),
    "ARG": ((1992, "ARS"),), "BRA": ((1995, "BRL"),), "URY": ((1994, "UYU"),), "CHL": ((1991, "CLP"),),
    "PRY": ((1991, "PYG"),), "BOL": ((1991, "BOB"),), "PER": ((1992, "PEN"),), "COL": ((1991, "COP"),),
    "MEX": ((1993, "MXN"),), "USA": ((1991, "USD"),), "CAN": ((1991, "CAD"),), "CUB": ((1991, "CUP"),),
    "GTM": ((1991, "GTQ"),), "SLV": ((2001, "USD"),), "NIC": ((1992, "NIO"),),
    "CHE": ((1991, "CHF"),), "GBR": ((1991, "GBP"),), "DNK": ((1991, "DKK"),), "SWE": ((1991, "SEK"),),
    "NOR": ((1991, "NOK"),), "POL": ((1995, "PLN"),), "CZE": ((1993, "CZK"),), "HUN": ((1991, "HUF"),),
    "ROU": ((2006, "RON"),), "SRB": ((2006, "RSD"),), "BIH": ((1998, "BAM"),), "MKD": ((1993, "MKD"),),
    "ALB": ((1991, "ALL"),), "UKR": ((1997, "UAH"),), "MDA": ((1994, "MDL"),), "BLR": ((2017, "BYN"),),
    "RUS": ((1998, "RUB"),), "TUR": ((2005, "TRY"),),
    "CHN": ((1991, "CNY"),), "HKG": ((1991, "HKD"),), "TWN": ((1991, "TWD"),), "IND": ((1991, "INR"),),
    "PAK": ((1991, "PKR"),), "VNM": ((1991, "VND"),), "THA": ((1991, "THB"),), "MMR": ((1991, "MMK"),),
    "MYS": ((1991, "MYR"),), "IDN": ((1991, "IDR"),), "PHL": ((1991, "PHP"),), "JPN": ((1991, "JPY"),),
    "KOR": ((1991, "KRW"),), "KAZ": ((1994, "KZT"),), "KGZ": ((1994, "KGS"),),
    "IRN": ((1991, "IRR"),), "ISR": ((1991, "ILS"),), "SAU": ((1991, "SAR"),), "ARE": ((1991, "AED"),),
    "JOR": ((1991, "JOD"),), "KWT": ((1992, "KWD"),), "QAT": ((1991, "QAR"),), "OMN": ((1991, "OMR"),),
    "LBN": ((1991, "LBP"),), "YEM": ((1991, "YER"),),
    "EGY": ((1991, "EGP"),), "MAR": ((1991, "MAD"),), "DZA": ((1991, "DZD"),), "TUN": ((1991, "TND"),),
    "ETH": ((1991, "ETB"),), "KEN": ((1991, "KES"),), "TZA": ((1991, "TZS"),), "ZAF": ((1991, "ZAR"),),
    "AUS": ((1991, "AUD"),), "NZL": ((1991, "NZD"),),
}


def _today() -> date:
    """Today's date (a function so tests can pin it)."""
    return date.today()


# =============================================================================================
# Pure helpers
# =============================================================================================


def _norm_unit(unit: str | None) -> str:
    return " ".join(str(unit or "").strip().lower().split())


def parse_value(raw: Any) -> float | None:
    """A FAOSTAT value: number or numeric text ('65286.000000'). None/'' -> None. Text that is not
    a number (or NaN/inf) raises ValueError."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        out = float(raw)
    else:
        s = str(raw).strip()            # a JSON boolean becomes "True": not a number -> ValueError
        if not s:
            return None
        out = float(s)                  # no comma tricks: "12,5" is malformed, never 125
    if math.isnan(out) or math.isinf(out):
        raise ValueError(f"non-finite value {raw!r}")
    return out


def flag_status(flag: str | None) -> tuple[str | None, bool]:
    """Map a FAOSTAT flag to a DataStatus value.

    Returns ``(status, known)``. ``status`` is None when the flag marks a missing value (the row
    must be skipped). An unknown flag maps to ``estimate`` (never presented as an official figure)
    with ``known=False`` so the caller can warn."""
    f = (flag or "").strip()
    if f in MISSING_FLAGS:
        return None, True
    if f in FLAG_STATUS:
        return FLAG_STATUS[f].value, True
    return DataStatus.ESTIMATE.value, False


def least_firm(*statuses: str | None) -> str:
    """The least firm of several data_status values (published < provisional < estimate)."""
    ranked = [DataStatus(s) for s in statuses if s]
    if not ranked:
        return DataStatus.PUBLISHED.value
    return max(ranked, key=lambda s: _STATUS_RANK.get(s, 2)).value


@dataclass(frozen=True)
class AreaMatch:
    iso3: str | None
    outcome: str            # ok | aggregate | unmapped | conflict | malformed
    canonical: bool = False  # the FAO code is the one the country table holds for this ISO3


def resolve_area(code: Any, m49: Any = None, name: Any = None) -> AreaMatch:
    """Map a FAOSTAT area to ISO3. Aggregates are refused; M49 first, then FAO code, then name."""
    c = str(code if code is not None else "").strip()
    nm = str(name or "").strip()
    if not c:
        if not nm:
            return AreaMatch(None, "malformed")
        iso = lookup_iso3(nm)
        return AreaMatch(iso, "ok") if iso and iso not in AGGREGATES else AreaMatch(None, "unmapped")
    if not c.isdigit():                       # list codes such as "5000>" (World > (List))
        return AreaMatch(None, "aggregate")
    n = int(c)
    if n >= AGGREGATE_AREA_MIN or n in SKIP_AREA_CODES:
        return AreaMatch(None, "aggregate")
    by_fao = AREA_OVERRIDES.get(n) or lookup_fao(n)
    canonical = by_fao is not None and _FAO_CODE_OF.get(by_fao) == n
    m = str(m49 or "").strip().lstrip("'")    # bulk files print M49 with a leading apostrophe ('032)
    by_m49 = None
    if m.isdigit() and int(m) > 0:
        by_m49 = lookup_iso3(int(m))
        if by_m49 in AGGREGATES:
            return AreaMatch(None, "aggregate")
    if by_m49 and by_fao and by_m49 != by_fao:
        return AreaMatch(None, "conflict")
    iso = by_m49 or by_fao
    if iso is None and nm:
        iso = lookup_iso3(nm)
        if iso in AGGREGATES:
            return AreaMatch(None, "aggregate")
    if iso is None:
        return AreaMatch(None, "unmapped")
    return AreaMatch(iso, "ok", canonical)


def local_currency(iso3: str, year: int) -> str | None:
    """ISO 4217 code of the local currency FAOSTAT's LCU values are in, or None if unknown."""
    out = None
    for since, code in LOCAL_CURRENCY.get(iso3, ()):
        if year >= since:
            out = code
    return out


def classify_trade_element(code: str, label: str) -> tuple[str, str] | None:
    """(flow, measure) for a trade element, from its code or, failing that, its label."""
    hit = TRADE_ELEMENTS.get(str(code).strip())
    if hit:
        return hit
    lab = (label or "").strip().lower()
    flow = "import" if lab.startswith("import") else "export" if lab.startswith("export") else None
    measure = "quantity" if "quantity" in lab else "value" if "value" in lab else None
    return (flow, measure) if flow and measure else None


@dataclass(frozen=True)
class CatalogueEntry:
    code: str
    name: str
    date_update: str          # as printed, e.g. "2026-10-02T00:00:00" (compared verbatim)
    file_location: str
    file_size: str | None = None
    file_rows: int | None = None

    @property
    def published(self) -> date | None:
        return parse_date(self.date_update[:10]) if self.date_update else None


def parse_catalogue(content: bytes) -> dict[str, CatalogueEntry]:
    """Parse ``datasets_E.json``: ``{"Datasets": {"Dataset": [{DatasetCode, DateUpdate,
    FileLocation, ...}]}}``. Raises CollectorError when the shape is not the documented one."""
    try:
        payload = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise CollectorError(f"FAOSTAT bulk catalogue is not JSON: {exc}") from exc
    datasets = payload.get("Datasets") if isinstance(payload, dict) else None
    items = datasets.get("Dataset") if isinstance(datasets, dict) else None
    if isinstance(items, dict):            # XML-to-JSON conversion: a single dataset is not a list
        items = [items]
    if not isinstance(items, list) or not items:
        keys = sorted(payload)[:10] if isinstance(payload, dict) else type(payload).__name__
        raise CollectorError(f"FAOSTAT bulk catalogue format changed: no Datasets.Dataset list (top level: {keys})")
    out: dict[str, CatalogueEntry] = {}
    for item in items:
        if not isinstance(item, dict) or not item.get("DatasetCode"):
            continue
        code = str(item["DatasetCode"]).strip()
        try:
            rows = int(item["FileRows"]) if item.get("FileRows") not in (None, "") else None
        except (TypeError, ValueError):
            rows = None
        out[code] = CatalogueEntry(
            code=code, name=str(item.get("DatasetName") or code),
            date_update=str(item.get("DateUpdate") or "").strip(),
            file_location=str(item.get("FileLocation") or "").strip(),
            file_size=str(item["FileSize"]) if item.get("FileSize") is not None else None, file_rows=rows,
        )
    if not out:
        raise CollectorError("FAOSTAT bulk catalogue format changed: no dataset carries a DatasetCode")
    if not any(e.date_update for e in out.values()):
        raise CollectorError("FAOSTAT bulk catalogue format changed: no DateUpdate field")
    return out


# --------------------------------------------------------------------------- rows


@dataclass
class FaoRow:
    """One FAOSTAT value, from a bulk CSV row or an API row, with its provenance."""

    dataset: str
    area_code: str
    area: str
    item_code: str
    element_code: str
    element: str
    year: int
    unit: str
    value: float | None
    value_raw: str
    flag: str
    source_url: str
    area_m49: str | None = None
    item: str | None = None
    flag_description: str | None = None
    note: str | None = None
    months_code: str | None = None
    months: str | None = None
    partner_code: str | None = None       # TM only
    partner: str | None = None
    partner_m49: str | None = None
    raw_document_id: int | None = None


@dataclass
class BulkExtract:
    """The honey rows of a bulk ZIP's normalized table, kept as read (strings)."""

    member: str
    header: list[str]
    rows: list[list[str]]
    rows_read: int
    encoding: str

    def to_zip_bytes(self) -> bytes:
        """A small, deterministic ZIP of the extract (archived as the RawDocument)."""
        text = io.StringIO()
        writer = csv.writer(text, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
        writer.writerow(self.header)
        writer.writerows(self.rows)
        name = self.member.replace(NORMALIZED_SUFFIX, "_honey_extract.csv")
        info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(info, text.getvalue().encode("utf-8"))
        return buf.getvalue()


def _normalized_member(zf: zipfile.ZipFile) -> str:
    names = [n for n in zf.namelist() if n.endswith(NORMALIZED_SUFFIX)]
    if len(names) != 1:
        listed = ", ".join(zf.namelist()[:10]) or "none"
        raise CollectorError(f"expected exactly one *{NORMALIZED_SUFFIX} member in the ZIP, found {len(names)} "
                             f"(members: {listed})")
    return names[0]


def _scan_member(zf: zipfile.ZipFile, member: str, wanted: frozenset[str], encoding: str) -> BulkExtract:
    with zf.open(member) as raw, io.TextIOWrapper(raw, encoding=encoding, newline="") as text:
        reader = csv.reader(text)
        header = next(reader, None)
        if not header:
            raise CollectorError(f"{member} is empty")
        header = [h.strip() for h in header]
        missing = [c for c in REQUIRED_BULK_COLUMNS if c not in header]
        if "Year" not in header and "Year Code" not in header:
            missing.append("Year")
        if missing:
            raise CollectorError(f"{member}: format changed, missing column(s) {missing}; header is {header}")
        idx = header.index("Item Code")
        rows: list[list[str]] = []
        n = 0
        for row in reader:
            n += 1
            if len(row) > idx and row[idx].strip().lstrip("'") in wanted:
                rows.append(row)
    return BulkExtract(member=member, header=header, rows=rows, rows_read=n, encoding=encoding)


def read_bulk_zip(source: str | os.PathLike[str] | IO[bytes], item_codes: Iterable[str]) -> BulkExtract:
    """Stream the normalized CSV inside a FAOSTAT bulk ZIP, keeping rows whose Item Code is wanted.

    The member is read through ``zipfile`` + ``io.TextIOWrapper`` + ``csv`` one row at a time; only
    the matching rows are kept. UTF-8 (BOM tolerated) is tried first, then Latin-1 (older files).
    Raises CollectorError for a broken archive or a changed layout (missing required columns)."""
    wanted = frozenset(str(c) for c in item_codes)
    try:
        zf = zipfile.ZipFile(source)
    except (zipfile.BadZipFile, OSError) as exc:
        raise CollectorError(f"not a valid ZIP file: {exc}") from exc
    with zf:
        member = _normalized_member(zf)
        for encoding in ("utf-8-sig", "latin-1"):
            try:
                return _scan_member(zf, member, wanted, encoding)
            except UnicodeDecodeError:
                log.info("FAOSTAT %s is not UTF-8; retrying as Latin-1", member)
                continue
            except csv.Error as exc:
                raise CollectorError(f"{member} is not readable CSV: {exc}") from exc
            except (zipfile.BadZipFile, EOFError, zlib.error) as exc:
                raise CollectorError(f"ZIP archive is damaged or truncated: {exc}") from exc
    raise CollectorError(f"{member} could not be decoded")  # pragma: no cover - latin-1 always decodes


def bulk_rows(extract: BulkExtract, dataset: str, source_url: str) -> tuple[list[FaoRow], list[str]]:
    """Turn a bulk extract into FaoRows. Returns (rows, malformed-row messages)."""
    h = {name: i for i, name in enumerate(extract.header)}
    year_col = "Year" if "Year" in h else "Year Code"
    out: list[FaoRow] = []
    bad: list[str] = []

    def get(row: list[str], col: str) -> str | None:
        i = h.get(col)
        return row[i].strip() if i is not None and i < len(row) else None

    for line, row in enumerate(extract.rows, start=1):
        if len(row) != len(extract.header):
            bad.append(f"row {line}: {len(row)} cells for {len(extract.header)} columns")
            continue
        raw_value = get(row, "Value") or ""
        try:
            year = int(get(row, year_col) or "")
            value = parse_value(raw_value)
        except ValueError:
            bad.append(f"{get(row, 'Area')} {get(row, 'Element')} {get(row, year_col)}: "
                       f"unreadable year/value {raw_value!r}")
            continue
        out.append(FaoRow(
            dataset=dataset, area_code=get(row, "Area Code") or "", area=get(row, "Area") or "",
            area_m49=get(row, "Area Code (M49)"), item_code=(get(row, "Item Code") or "").lstrip("'"),
            item=get(row, "Item"), element_code=get(row, "Element Code") or "", element=get(row, "Element") or "",
            year=year, unit=get(row, "Unit") or "", value=value, value_raw=raw_value, flag=get(row, "Flag") or "",
            flag_description=None, note=get(row, "Note") or None, months_code=get(row, "Months Code"),
            months=get(row, "Months"), source_url=source_url,
        ))
    return out, bad


def _dsd_key(payload: dict, dimension: str, kind: str) -> str | None:
    """Column key for a dimension's code/label column, from ``metadata.dsd``."""
    meta = payload.get("metadata") if isinstance(payload, dict) else None
    for col in (meta or {}).get("dsd") or []:
        if isinstance(col, dict) and col.get("dimension_id") == dimension and col.get("type") == kind and col.get("key"):
            return str(col["key"])
    return None


def _pick(row: dict, *keys: str | None) -> Any:
    for k in keys:
        if k and k in row and row[k] is not None and row[k] != "":
            return row[k]
    return None


def parse_api_rows(payload: Any, dataset: str, source_url: str, *, raw_document_id: int | None = None,
                   reporter_dim: str | None = None, partner_dim: str | None = None,
                   ) -> tuple[list[FaoRow], list[str]]:
    """Parse a FAOSTAT API ``/data`` answer (``output_type=objects``). Column names are taken from
    ``metadata.dsd`` when it describes them (TM reporter/partner), else the documented names.
    Raises CollectorError when the answer has no ``data`` list or rows lack the core columns."""
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        keys = sorted(payload)[:10] if isinstance(payload, dict) else type(payload).__name__
        raise CollectorError(f"FAOSTAT API {dataset}: unexpected answer, no 'data' list (keys: {keys})")
    if reporter_dim:
        area_code_keys = (_dsd_key(payload, reporter_dim, "code"), "Reporter Country Code", "Reporter Country Code (FAO)")
        area_keys = (_dsd_key(payload, reporter_dim, "label"), "Reporter Countries", "Reporter Country")
        area_m49_keys = ("Reporter Country Code (M49)",)
    else:
        area_code_keys = (_dsd_key(payload, "area", "code"), "Area Code", "Area Code (FAO)")
        area_keys = (_dsd_key(payload, "area", "label"), "Area")
        area_m49_keys = ("Area Code (M49)",)
    partner_code_keys = (_dsd_key(payload, partner_dim, "code"), "Partner Country Code",
                         "Partner Country Code (FAO)") if partner_dim else ()
    partner_keys = (_dsd_key(payload, partner_dim, "label"), "Partner Countries", "Partner Country") if partner_dim else ()

    out: list[FaoRow] = []
    bad: list[str] = []
    for i, row in enumerate(payload["data"], start=1):
        if not isinstance(row, dict):
            bad.append(f"row {i}: not an object")
            continue
        area_code, area = _pick(row, *area_code_keys), _pick(row, *area_keys)
        element_code, element = _pick(row, "Element Code"), _pick(row, "Element")
        year_raw, item_code = _pick(row, "Year", "Year Code"), _pick(row, "Item Code", "Item Code (FAO)")
        if i == 1:
            missing = [n for n, v in (("area code", area_code), ("area", area), ("element", element_code or element),
                                      ("item code", item_code), ("year", year_raw)) if v is None]
            if "Value" not in row or "Unit" not in row:
                missing.append("Value/Unit")
            if partner_dim and _pick(row, *partner_code_keys) is None and _pick(row, *partner_keys) is None:
                missing.append("partner")
            if missing:
                raise CollectorError(f"FAOSTAT API {dataset}: format changed, rows lack {missing}; "
                                     f"columns are {sorted(row)}")
        raw_value = row.get("Value")
        try:
            year = int(str(year_raw).strip())
            value = parse_value(raw_value)
        except (TypeError, ValueError):
            bad.append(f"{area} {element} {year_raw}: unreadable year/value {raw_value!r}")
            continue
        partner_code = partner = partner_m49 = None
        if partner_dim:
            partner_code = str(_pick(row, *partner_code_keys) or "").strip() or None
            partner = _pick(row, *partner_keys)
            partner_m49 = _pick(row, "Partner Country Code (M49)")
        out.append(FaoRow(
            dataset=dataset, area_code=str(area_code or "").strip(), area=str(area or "").strip(),
            area_m49=_pick(row, *area_m49_keys), item_code=str(item_code or "").strip(), item=_pick(row, "Item"),
            element_code=str(element_code or "").strip(), element=str(element or "").strip(), year=year,
            unit=str(row.get("Unit") or "").strip(), value=value, value_raw="" if raw_value is None else str(raw_value),
            flag=str(row.get("Flag") or "").strip(), flag_description=_pick(row, "Flag Description"),
            note=_pick(row, "Note"), months_code=_pick(row, "Months Code"), months=_pick(row, "Months"),
            partner_code=partner_code, partner=partner, partner_m49=partner_m49,
            source_url=source_url, raw_document_id=raw_document_id,
        ))
    return out, bad


# --------------------------------------------------------------------------- records


@dataclass
class Issues:
    """Problems collected during a run, reported as a few consolidated warnings."""

    malformed: dict[str, list[str]] = field(default_factory=dict)
    unmapped: dict[str, str] = field(default_factory=dict)          # FAO area code -> name
    conflicts: dict[str, str] = field(default_factory=dict)         # FAO area code -> name
    unknown_flags: dict[str, set[str]] = field(default_factory=dict)  # flag -> datasets
    bad_units: set[tuple[str, str, str]] = field(default_factory=set)  # (dataset, element, unit)
    duplicates: dict[str, list[str]] = field(default_factory=dict)
    skipped: Counter = field(default_factory=Counter)

    def bad(self, dataset: str, msgs: Iterable[str]) -> None:
        self.malformed.setdefault(dataset, []).extend(msgs)

    def area(self, match: AreaMatch, code: str, name: str) -> bool:
        """Record a non-country area; True when the row can be used."""
        if match.outcome == "ok":
            return True
        if match.outcome == "unmapped":
            self.unmapped.setdefault(code or name, name)
        elif match.outcome == "conflict":
            self.conflicts.setdefault(code, name)
        self.skipped[f"area {match.outcome}"] += 1
        return False

    def status(self, dataset: str, flag: str) -> str | None:
        status, known = flag_status(flag)
        if not known:
            self.unknown_flags.setdefault(flag, set()).add(dataset)
        if status is None:
            self.skipped["missing-value flag"] += 1
        return status


@dataclass
class ProductionRecord:
    iso3: str
    metric: str             # production | colonies
    year: int
    value: float
    unit: str               # t | number
    status: str
    row: FaoRow
    canonical: bool

    @property
    def key(self) -> tuple:
        return (self.iso3, self.metric, self.year)


@dataclass
class PriceRecord:
    iso3: str
    year: int
    value: float            # per tonne, in `currency`
    currency: str
    basis: str              # USD | LCU
    status: str
    row: FaoRow
    canonical: bool

    @property
    def key(self) -> tuple:
        return (self.iso3, self.year)


@dataclass
class TradeRecord:
    dataset: str
    reporter_iso3: str
    partner_iso3: str
    flow: str
    year: int
    net_weight_kg: float | None = None
    value_usd: float | None = None
    rows: dict[str, FaoRow] = field(default_factory=dict)    # measure -> row
    canonical: bool = True

    @property
    def key(self) -> tuple:
        return (self.reporter_iso3, self.partner_iso3, self.flow, self.year)

    @property
    def status(self) -> str:
        return least_firm(*(flag_status(r.flag)[0] for r in self.rows.values()))


def _dedup(records: list, dataset: str, issues: Issues) -> list:
    """Keep one record per key. Two FAO areas can map to the same country (e.g. a predecessor
    state): the area the country table names (canonical) wins, otherwise the first one seen."""
    best: dict[tuple, Any] = {}
    for rec in records:
        cur = best.get(rec.key)
        if cur is None:
            best[rec.key] = rec
            continue
        if rec.canonical and not cur.canonical:
            best[rec.key] = rec
        issues.duplicates.setdefault(dataset, []).append(f"{rec.key}")
    return list(best.values())


def _unit_factor(table: dict[str, float], unit: str, dataset: str, element: str, issues: Issues) -> float | None:
    factor = table.get(_norm_unit(unit))
    if factor is None:
        issues.bad_units.add((dataset, element, unit))
        issues.skipped["unknown unit"] += 1
    return factor


def _year_ok(row: FaoRow, issues: Issues) -> bool:
    if row.year < MIN_YEAR:
        issues.skipped["before MIN_YEAR"] += 1
        return False
    return True


def build_production(rows: list[FaoRow], issues: Issues) -> list[ProductionRecord]:
    """QCL rows -> production (item 1182, t) and colonies (item 1181 stocks, number)."""
    out: list[ProductionRecord] = []
    for r in rows:
        if r.item_code == HONEY_ITEM and (r.element_code in PRODUCTION_ELEMENTS or r.element.lower() == "production"):
            metric, table, unit = "production", PRODUCTION_TO_T, "t"
        elif r.item_code == BEES_ITEM and (r.element_code in STOCKS_ELEMENTS or r.element.lower() == "stocks"):
            metric, table, unit = "colonies", COUNT_TO_NUMBER, "number"
        else:
            issues.skipped[f"QCL other element {r.item_code}/{r.element_code}"] += 1
            continue
        if not _year_ok(r, issues):
            continue
        match = resolve_area(r.area_code, r.area_m49, r.area)
        if not issues.area(match, r.area_code, r.area):
            continue
        status = issues.status("QCL", r.flag)
        if status is None:
            continue
        if r.value is None:
            issues.skipped["empty value"] += 1
            continue
        if r.value < 0:
            issues.bad("QCL", [f"{r.area} {r.element} {r.year}: negative value {r.value_raw!r}"])
            continue
        factor = _unit_factor(table, r.unit, "QCL", r.element, issues)
        if factor is None:
            continue
        value = round(r.value * factor, 3 if metric == "production" else 0)
        out.append(ProductionRecord(match.iso3, metric, r.year, value, unit, status, r, match.canonical))
    return _dedup(out, "QCL", issues)


def build_prices(rows: list[FaoRow], issues: Issues) -> list[PriceRecord]:
    """PP rows -> one producer price per country-year: USD/t, else LCU/t in a known currency."""
    by_area: dict[tuple[str, int], dict[str, FaoRow]] = {}
    for r in rows:
        if r.item_code != HONEY_ITEM:
            continue
        lab = r.element.lower()
        if r.element_code in PP_USD_ELEMENTS or (not r.element_code and "usd/tonne" in lab):
            basis = "USD"
        elif r.element_code in PP_LCU_ELEMENTS or (not r.element_code and "lcu/tonne" in lab):
            basis = "LCU"
        else:
            issues.skipped[f"PP element {r.element_code}"] += 1     # SLC, price index ...
            continue
        if (r.months_code and r.months_code != ANNUAL_MONTHS_CODE) and (r.months or "").lower() != "annual value":
            issues.skipped["PP not annual"] += 1
            continue
        if not _year_ok(r, issues):
            continue
        by_area.setdefault((r.area_code or r.area, r.year), {})[basis] = r

    out: list[PriceRecord] = []
    for (_area, year), elems in by_area.items():
        # USD first; the local-currency value is only a fallback when no usable USD value exists.
        for basis in ("USD", "LCU"):
            r = elems.get(basis)
            if r is None:
                continue
            status = issues.status("PP", r.flag)
            if status is None:
                continue
            if r.value is None:
                issues.skipped["empty value"] += 1
                continue
            if r.value <= 0:
                issues.bad("PP", [f"{r.area} {r.element} {r.year}: non-positive price {r.value_raw!r}"])
                continue
            allowed = PRICE_USD_UNITS if basis == "USD" else PRICE_LCU_UNITS
            if _norm_unit(r.unit) not in allowed:
                issues.bad_units.add(("PP", r.element, r.unit))
                issues.skipped["unknown unit"] += 1
                continue
            match = resolve_area(r.area_code, r.area_m49, r.area)
            if not issues.area(match, r.area_code, r.area):
                break
            currency = "USD" if basis == "USD" else local_currency(match.iso3, year)
            if currency is None:
                issues.skipped["LCU currency unknown"] += 1
                continue
            out.append(PriceRecord(match.iso3, year, r.value, currency, basis, status, r, match.canonical))
            break           # USD found (or LCU fallback used): one price per country-year
    return _dedup(out, "PP", issues)


def build_trade(rows: list[FaoRow], dataset: str, issues: Issues) -> list[TradeRecord]:
    """TCL/TM rows -> one trade record per reporter x partner x flow x year (quantity + value)."""
    groups: dict[tuple, TradeRecord] = {}
    for r in rows:
        if r.item_code != HONEY_ITEM:
            continue
        kind = classify_trade_element(r.element_code, r.element)
        if kind is None:
            issues.skipped[f"{dataset} element {r.element_code}"] += 1
            continue
        flow_name, measure = kind
        if not _year_ok(r, issues):
            continue
        rep = resolve_area(r.area_code, r.area_m49, r.area)
        if not issues.area(rep, r.area_code, r.area):
            continue
        if dataset == "TM":
            part = resolve_area(r.partner_code, r.partner_m49, r.partner)
            if not issues.area(part, r.partner_code or "", r.partner or ""):
                continue
            partner_iso3, canonical = part.iso3, rep.canonical and part.canonical
            partner_key = r.partner_code or r.partner
        else:
            partner_iso3, canonical, partner_key = "WLD", rep.canonical, "WLD"
        if issues.status(dataset, r.flag) is None:
            continue
        if r.value is None:
            issues.skipped["empty value"] += 1
            continue
        if r.value < 0:
            issues.bad(dataset, [f"{r.area} {r.element} {r.year}: negative value {r.value_raw!r}"])
            continue
        table = QUANTITY_TO_KG if measure == "quantity" else VALUE_TO_USD
        factor = _unit_factor(table, r.unit, dataset, r.element, issues)
        if factor is None:
            continue
        flow = TradeFlow.IMPORT.value if flow_name == "import" else TradeFlow.EXPORT.value
        gkey = (r.area_code or r.area, partner_key, flow, r.year)
        rec = groups.get(gkey)
        if rec is None:
            rec = groups[gkey] = TradeRecord(dataset, rep.iso3, partner_iso3, flow, r.year, canonical=canonical)
        if measure == "quantity":
            rec.net_weight_kg = round(r.value * factor, 3)
        else:
            rec.value_usd = round(r.value * factor, 2)
        rec.rows[measure] = r
    return _dedup(list(groups.values()), dataset, issues)


# =============================================================================================
# Network helpers (private to this module)
# =============================================================================================


class _ApiUnavailable(Exception):
    """The FAOSTAT API cannot be used in this run (login refused, token rejected, host down)."""


# Process-wide token cache: username -> (access token, monotonic expiry). Tokens are never stored
# on disk or in the database; they last 60 minutes.
_TOKEN_CACHE: dict[str, tuple[str, float]] = {}


def _wait_turn(ctx: CollectContext, url: str) -> str:
    """Same per-host politeness as ``ctx.fetch`` for requests made outside it (login, streaming)."""
    host = urlsplit(url).netloc
    last = ctx._last_hit.get(host)
    if last is not None:
        wait = ctx.MIN_INTERVAL_PER_HOST - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
    return host


def _download_to_file(ctx: CollectContext, url: str, dest_dir: Path) -> tuple[Path, int]:
    """Stream ``url`` to a temporary file in ``dest_dir`` (never held in memory). Returns (path, bytes)."""
    attempt = 0
    while True:
        attempt += 1
        host = _wait_turn(ctx, url)
        tmp: str | None = None
        try:
            with ctx.client.stream("GET", url) as resp:
                if resp.status_code in (429, 502, 503, 504) and attempt <= DOWNLOAD_RETRIES:
                    time.sleep(5 * attempt)
                    continue
                if resp.status_code != 200:
                    raise CollectorError(f"HTTP {resp.status_code} for {url}")
                fd, tmp = tempfile.mkstemp(prefix="faostat-", suffix=".zip", dir=dest_dir)
                size = 0
                with os.fdopen(fd, "wb") as fh:
                    for chunk in resp.iter_bytes(DOWNLOAD_CHUNK):
                        size += len(chunk)
                        if size > MAX_ZIP_BYTES:
                            raise CollectorError(f"{url} is larger than {MAX_ZIP_BYTES // 1024 ** 2} MB; not downloaded")
                        fh.write(chunk)
                return Path(tmp), size
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            _unlink(tmp)
            if attempt > DOWNLOAD_RETRIES:
                raise Offline(f"Cannot reach {host}: {exc}") from exc
            time.sleep(2 * attempt)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            _unlink(tmp)
            if attempt > DOWNLOAD_RETRIES:
                raise CollectorError(f"Download of {url} failed: {type(exc).__name__}: {exc}") from exc
            time.sleep(2 * attempt)
        except BaseException:
            _unlink(tmp)
            raise
        finally:
            ctx._last_hit[host] = time.monotonic()


def _unlink(path: str | os.PathLike[str] | None) -> None:
    if path:
        try:
            os.unlink(path)
        except OSError:
            pass


class _FaostatApi:
    """Token-authenticated access to the FAOSTAT API (credentials never leave this object)."""

    def __init__(self, ctx: CollectContext, username: str, password: str):
        self.ctx = ctx
        self._username = username
        self._password = password

    def _login(self) -> str:
        ctx = self.ctx
        host = _wait_turn(ctx, LOGIN_URL)
        try:
            resp = ctx.client.post(LOGIN_URL, data={"username": self._username, "password": self._password},
                                   headers={"Accept": "application/json"})
        except httpx.HTTPError as exc:
            raise _ApiUnavailable(f"login request failed ({type(exc).__name__})") from None
        finally:
            ctx._last_hit[host] = time.monotonic()
        if resp.status_code != 200:
            kind = ""
            try:
                body = resp.json()
                kind = "".join(ch for ch in str(body.get("__type", "")) if ch.isalnum())[:60]
            except (ValueError, AttributeError):
                pass
            raise _ApiUnavailable(f"login refused (HTTP {resp.status_code}{': ' + kind if kind else ''})")
        try:
            result = resp.json()["AuthenticationResult"]
            token = str(result["AccessToken"])
            expires_in = int(result.get("ExpiresIn") or 3600)
        except (ValueError, KeyError, TypeError) as exc:
            raise _ApiUnavailable("login answer has no AuthenticationResult.AccessToken (format changed?)") from exc
        if not token:
            raise _ApiUnavailable("login answer carries an empty access token")
        _TOKEN_CACHE[self._username] = (token, time.monotonic() + max(expires_in - 60, 60))
        return token

    def token(self, refresh: bool = False) -> str:
        cached = _TOKEN_CACHE.get(self._username)
        if cached and not refresh and cached[1] > time.monotonic():
            return cached[0]
        _TOKEN_CACHE.pop(self._username, None)
        return self._login()

    def get(self, url: str, *, title: str, published_at: date | None) -> FetchResult:
        """GET with the Bearer token; one re-login on 401/403. Successful answers are archived."""
        ctx = self.ctx
        for attempt in (1, 2):
            headers = {"Authorization": f"Bearer {self.token(refresh=attempt == 2)}", "Accept": "application/json"}
            try:
                doc = ctx.fetch(url, headers=headers, title=title, accept_status=(200, 401, 403), store=False)
            except Offline as exc:
                raise _ApiUnavailable(str(exc)) from exc
            if doc.status_code == 200:
                # ctx._store_raw is the archive half of ctx.fetch: only successful answers are kept.
                raw_id, unchanged = ctx._store_raw(doc.url, doc.content, doc.content_type, title, published_at)
                return dataclasses.replace(doc, raw_document_id=raw_id, unchanged=unchanged)
            _TOKEN_CACHE.pop(self._username, None)
        raise _ApiUnavailable(f"the API refused the token twice (HTTP {doc.status_code})")

    def get_json(self, url: str, *, title: str, published_at: date | None) -> tuple[Any, FetchResult]:
        doc = self.get(url, title=title, published_at=published_at)
        try:
            return doc.json(), doc
        except ValueError as exc:
            raise CollectorError(f"FAOSTAT API answer is not JSON: {doc.url}") from exc


def _api_url(path: str, params: dict[str, Any]) -> str:
    """API URL with a readable query (commas kept, as FAOSTAT documents its code lists)."""
    return f"{API_ROOT}/{API_LANG}/{path}?{urlencode(params, safe=',')}"


# =============================================================================================
# Collector
# =============================================================================================


class _Snapshot:
    """Counter values to restore when one dataset is rolled back."""

    FIELDS = ("seen", "new", "revised", "newest_published", "newest_period_label", "newest_period_start")

    def __init__(self, ctx: CollectContext):
        self.values = {f: getattr(ctx.counters, f) for f in self.FIELDS}

    def restore(self, ctx: CollectContext) -> None:
        for f, v in self.values.items():
            setattr(ctx.counters, f, v)


class _FaostatRun:
    def __init__(self, ctx: CollectContext):
        self.ctx = ctx
        self.issues = Issues()
        self.failed: list[str] = []
        self.api: _FaostatApi | None = None
        user = (getattr(ctx.settings, "faostat_username", None) or "").strip()
        pw = getattr(ctx.settings, "faostat_password", None)
        pw = pw.get_secret_value() if hasattr(pw, "get_secret_value") else (pw or "")
        if user and pw:
            self.api = _FaostatApi(ctx, user, pw)
        elif user or pw:
            ctx.warn("FAOSTAT: only one of PALADEX_FAOSTAT_USERNAME / PALADEX_FAOSTAT_PASSWORD is set; "
                     "using the public bulk downloads")

    # ------------------------------------------------------------------ main loop
    def execute(self) -> None:
        ctx = self.ctx
        doc = ctx.fetch(CATALOGUE_URL, title="FAOSTAT bulk downloads catalogue (datasets_E.json)")
        catalogue = parse_catalogue(doc.content)
        missing = [c for c in DATASETS if c not in catalogue]
        if len(missing) == len(DATASETS):
            raise CollectorError(f"FAOSTAT bulk catalogue lists none of {list(DATASETS)} "
                                 f"(found {sorted(catalogue)[:15]})")
        ctx.checkpoint()        # keep the archived catalogue even if a dataset is rolled back later
        for code in DATASETS:
            entry = catalogue.get(code)
            if entry is None:
                ctx.warn(f"FAOSTAT {code}: not listed in the bulk catalogue any more; skipped")
                continue
            if code == "TM" and self.api is None:
                log.info("[%s] TM (bilateral trade, ~410 MB ZIP) needs the FAOSTAT API account; skipped", ctx.source.key)
                continue
            if not entry.date_update:
                self.failed.append(f"{code}: catalogue entry has no DateUpdate")
                continue
            seen = get_setting(ctx.session, SETTING_PREFIX + code)
            if seen == entry.date_update and not ctx.force:
                continue
            snapshot = _Snapshot(ctx)
            try:
                done = self.process(code, entry, first_load=seen is None or ctx.force)
            except Offline:
                raise
            except CollectorError as exc:
                ctx.session.rollback()
                snapshot.restore(ctx)
                self.failed.append(f"{code}: {exc}")
                continue
            if done:
                set_setting(ctx.session, SETTING_PREFIX + code, entry.date_update)
            ctx.checkpoint()
        self.report_issues()
        if self.failed:
            raise CollectorError("FAOSTAT dataset(s) failed: " + " | ".join(self.failed))

    def process(self, code: str, entry: CatalogueEntry, *, first_load: bool) -> bool:
        """Load one dataset. Returns False when it was skipped (DateUpdate then stays unrecorded)."""
        ctx = self.ctx
        if code == "TM":
            try:
                rows = self.api_tm_rows(entry, first_load=first_load)
            except _ApiUnavailable as exc:
                ctx.warn(f"FAOSTAT API unavailable ({exc}); bilateral trade (TM) not updated this run")
                self.api = None
                return False
            self.store_trade("TM", rows, entry, access="api")
            return True
        rows: list[FaoRow] | None = None
        access = "bulk"
        if self.api is not None:
            try:
                rows, access = self.api_rows(code, entry, first_load=first_load), "api"
            except _ApiUnavailable as exc:
                ctx.warn(f"FAOSTAT API unavailable ({exc}); this run uses the public bulk downloads "
                         "(bilateral trade TM skipped)")
                self.api = None
        if rows is None:
            rows = self.load_bulk(code, entry)
        if code == "QCL":
            self.store_production(rows, entry, access)
        elif code == "PP":
            self.store_prices(rows, entry, access)
        else:
            self.store_trade(code, rows, entry, access=access)
        return True

    # ------------------------------------------------------------------ bulk path
    def load_bulk(self, code: str, entry: CatalogueEntry) -> list[FaoRow]:
        """Stream the dataset's bulk ZIP, keep the honey rows, archive them, return FaoRows."""
        ctx = self.ctx
        url = entry.file_location
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not (parts.hostname or "").endswith("fao.org"):
            raise CollectorError(f"unexpected FileLocation {url!r} in the bulk catalogue")
        tmp_dir = ctx.settings.data_dir / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        path, size = _download_to_file(ctx, url, tmp_dir)
        try:
            extract = read_bulk_zip(path, BULK_ITEMS[code])
        finally:
            _unlink(path)
        log.info("[%s] %s: %d of %d rows kept from %s (%.1f MB, %s)", ctx.source.key, code, len(extract.rows),
                 extract.rows_read, extract.member, size / 1024 ** 2, extract.encoding)
        if not extract.rows:
            raise CollectorError(f"no honey rows (Item Code {sorted(BULK_ITEMS[code])}) in {extract.member}; "
                                 "format or item codes changed?")
        items = ", ".join(sorted(BULK_ITEMS[code]))
        title = f"FAOSTAT {code} bulk download: honey rows (items {items}) extracted from {extract.member}"
        raw_id, _unchanged = ctx._store_raw(url, extract.to_zip_bytes(), "application/zip", title, entry.published)
        rows, bad = bulk_rows(extract, code, url)
        for r in rows:
            r.raw_document_id = raw_id or None
        self.issues.bad(code, bad)
        return rows

    # ------------------------------------------------------------------ API path
    def _years(self, first_load: bool) -> str:
        last = _today().year - 1
        first = MIN_YEAR if first_load else max(MIN_YEAR, last - API_REFRESH_YEARS + 1)
        return ",".join(str(y) for y in range(first, last + 1))

    def _api_query(self, domain: str, params: dict[str, str], *, title: str, entry: CatalogueEntry,
                   reporter_dim: str | None = None, partner_dim: str | None = None) -> list[FaoRow]:
        """Run one data query, following pages (page_size / page_number) until a short page."""
        assert self.api is not None
        query = {**params, **API_COMMON_PARAMS}
        source_url = _api_url(f"data/{domain}", query)
        rows: list[FaoRow] = []
        first_sig = None
        for page in range(1, API_MAX_PAGES + 1):
            url = _api_url(f"data/{domain}", {**query, "page_size": API_PAGE_SIZE, "page_number": page})
            payload, doc = self.api.get_json(url, title=f"FAOSTAT API {domain} {title} (page {page})",
                                             published_at=entry.published)
            page_rows, bad = parse_api_rows(payload, domain, source_url, raw_document_id=doc.raw_document_id or None,
                                            reporter_dim=reporter_dim, partner_dim=partner_dim)
            self.issues.bad(domain, bad)
            data = payload["data"]
            sig = json.dumps(data[0], sort_keys=True) if data else None
            if page > 1 and sig is not None and sig == first_sig:
                log.info("[%s] FAOSTAT API ignored page_number for %s; one page kept", self.ctx.source.key, domain)
                break
            first_sig = first_sig or sig
            rows.extend(page_rows)
            if len(data) != API_PAGE_SIZE:      # short page, or paging ignored and everything sent
                break
        else:
            self.ctx.warn(f"FAOSTAT API {domain} {title}: more than {API_MAX_PAGES} pages; answer truncated")
        return rows

    def api_rows(self, code: str, entry: CatalogueEntry, *, first_load: bool) -> list[FaoRow]:
        years = self._years(first_load)
        rows: list[FaoRow] = []
        for title, params in API_QUERIES[code]:
            got = self._api_query(code, {**params, "year": years}, title=title, entry=entry)
            if not got:
                raise CollectorError(f"API query for {title} returned no rows (filter codes changed?)")
            rows.extend(got)
        return rows

    def api_tm_rows(self, entry: CatalogueEntry, *, first_load: bool) -> list[FaoRow]:
        """TM through the API: probe the (unverified) dimension and element codes, then one query per
        reporter of the panel."""
        assert self.api is not None
        pub = entry.published
        dims, _ = self.api.get_json(f"{API_ROOT}/{API_LANG}/dimensions/TM/", title="FAOSTAT API TM dimensions",
                                    published_at=pub)
        ids = [str(d.get("id")) for d in (dims.get("data") if isinstance(dims, dict) else None) or []
               if isinstance(d, dict) and d.get("id")]
        reporter_dim = next((i for i in ids if "reporter" in i.lower()), None)
        partner_dim = next((i for i in ids if "partner" in i.lower()), None)
        if not reporter_dim or not partner_dim:
            raise CollectorError(f"TM dimensions probe: no reporter/partner dimension (ids: {ids})")
        codes, _ = self.api.get_json(f"{API_ROOT}/{API_LANG}/codes/element/TM", title="FAOSTAT API TM element codes",
                                     published_at=pub)
        wanted: dict[tuple[str, str], str] = {}
        for c in (codes.get("data") if isinstance(codes, dict) else None) or []:
            if not isinstance(c, dict) or not c.get("code"):
                continue
            label = str(c.get("label") or "").strip().lower()
            for flow in ("import", "export"):
                for measure in ("quantity", "value"):
                    if label == f"{flow} {measure}":
                        wanted.setdefault((flow, measure), str(c["code"]))
        if len(wanted) != 4:
            raise CollectorError(f"TM element probe: expected import/export quantity/value, found {sorted(wanted)}")
        element = ",".join(wanted[k] for k in sorted(wanted))
        years = self._years(first_load)
        rows: list[FaoRow] = []
        for iso3 in TM_REPORTERS:
            fao = _FAO_CODE_OF.get(iso3)
            if fao is None:
                continue
            got = self._api_query("TM", {reporter_dim: str(fao), "item": HONEY_ITEM, "element": element, "year": years},
                                  title=f"honey bilateral trade, reporter {iso3}", entry=entry,
                                  reporter_dim=reporter_dim, partner_dim=partner_dim)
            stray = {r.area_code for r in got if r.area_code != str(fao)}
            if stray:
                raise CollectorError(f"TM query for reporter {fao} returned other reporters {sorted(stray)[:5]}: "
                                     f"the '{reporter_dim}' filter seems ignored")
            rows.extend(got)
        if not rows:
            raise CollectorError("TM queries returned no rows for any reporter (parameter names changed?)")
        return rows

    # ------------------------------------------------------------------ storage
    @staticmethod
    def _extra(r: FaoRow, entry: CatalogueEntry, access: str, **more: Any) -> dict:
        out = {
            "fao_dataset": entry.code, "fao_date_update": entry.date_update, "access": access,
            "fao_area_code": r.area_code, "fao_area": r.area, "fao_m49": (r.area_m49 or "").lstrip("'") or None,
            "fao_item_code": r.item_code, "fao_element_code": r.element_code, "fao_element": r.element,
            "fao_unit": r.unit, "value_as_published": r.value_raw, "flag": r.flag,
            "flag_description": r.flag_description or FLAG_LABELS.get(r.flag), "fao_note": r.note,
        }
        out.update(more)
        return {k: v for k, v in out.items() if v not in (None, "")}

    @staticmethod
    def _notes_flag(flag: str, desc: str | None) -> str:
        label = desc or FLAG_LABELS.get(flag) or "unknown flag"
        return f"flag {flag or '(none)'}: {label}"

    def store_production(self, rows: list[FaoRow], entry: CatalogueEntry, access: str) -> None:
        ctx = self.ctx
        records = build_production(rows, self.issues)
        if not records:
            raise CollectorError(f"none of the {len(rows)} honey rows gave a usable production figure "
                                 "(units, elements or flags changed?)")
        for rec in records:
            r = rec.row
            ps, pe = year_bounds(rec.year)
            what = "Natural honey production" if rec.metric == "production" else "Beehives (Bees, stocks)"
            ctx.add_production(
                series_key=f"faostat|QCL|{rec.iso3}|{rec.metric}|{rec.year}", country_iso3=rec.iso3,
                metric=rec.metric, value=rec.value, unit=rec.unit, period_start=ps, period_end=pe,
                period_label=str(rec.year), frequency="A", flag_raw=(r.flag or None) and r.flag[:20],
                data_status=rec.status, published_at=entry.published, source_url=r.source_url,
                raw_document_id=r.raw_document_id, notes=f"FAOSTAT QCL: {what}; {self._notes_flag(r.flag, r.flag_description)}",
                extra=self._extra(r, entry, access),
            )

    def store_prices(self, rows: list[FaoRow], entry: CatalogueEntry, access: str) -> None:
        ctx = self.ctx
        records = build_prices(rows, self.issues)
        if not records:
            raise CollectorError(f"none of the {len(rows)} honey rows gave a usable producer price "
                                 "(elements or units changed?)")
        for rec in records:
            r = rec.row
            ps, pe = year_bounds(rec.year)
            if rec.basis == "USD":
                note = "FAOSTAT PP: Producer Price (USD/tonne)"
            else:
                note = (f"FAOSTAT PP: Producer Price (LCU/tonne) in {rec.currency}; FAO publishes no USD value for "
                        f"this country-year (currency in use in {rec.year} per Paladex's currency reference)")
            ctx.add_price(
                series_key=f"faostat|PP|{rec.iso3}|{rec.year}", price_type=PriceType.PRODUCER,
                variety=Variety.UNSPECIFIED.value, variety_raw="Natural honey (FAOSTAT item 1182, all floral types)",
                price_value=rec.value, currency=rec.currency, unit="t", period_start=ps, period_end=pe,
                period_label=str(rec.year), frequency="A", origin_iso3=rec.iso3, origin_label=r.area[:120],
                market_iso3=rec.iso3, market_location=f"{r.area} (national average)"[:120],
                terms="farm-gate producer price, annual national average",
                notes=f"{note}. Farm-gate price, not an export/FOB price; {self._notes_flag(r.flag, r.flag_description)}",
                extra=self._extra(r, entry, access, price_basis=rec.basis, currency_note=(
                    None if rec.basis == "USD" else "LCU currency from Paladex reference table")),
                data_status=rec.status, published_at=entry.published, source_url=r.source_url,
                raw_document_id=r.raw_document_id,
            )

    def store_trade(self, code: str, rows: list[FaoRow], entry: CatalogueEntry, *, access: str) -> None:
        ctx = self.ctx
        records = build_trade(rows, code, self.issues)
        if not records:
            raise CollectorError(f"none of the {len(rows)} honey rows gave a usable trade figure "
                                 "(elements or units changed?)")
        for rec in records:
            if rec.net_weight_kg is None and rec.value_usd is None:
                continue
            ps, pe = year_bounds(rec.year)
            first = rec.rows.get("quantity") or rec.rows["value"]
            extra = self._extra(first, entry, access)
            for measure in ("quantity", "value"):           # per-measure provenance (flags may differ)
                r = rec.rows.get(measure)
                if r is not None:
                    extra[f"{measure}_element_code"] = r.element_code
                    extra[f"{measure}_unit"] = r.unit
                    extra[f"{measure}_as_published"] = r.value_raw
                    extra[f"flag_{measure}"] = r.flag
            for k in ("fao_element_code", "fao_element", "fao_unit", "value_as_published", "flag", "flag_description"):
                extra.pop(k, None)
            if code == "TM":
                extra.update({"fao_partner_code": first.partner_code, "fao_partner": first.partner})
            flags = ", ".join(f"{m} {self._notes_flag(r.flag, r.flag_description)}" for m, r in sorted(rec.rows.items()))
            what = "reporter total with the world" if code == "TCL" else "bilateral flow (reporter x partner)"
            ctx.add_trade(
                series_key=f"faostat|{code}|{rec.flow}|{rec.reporter_iso3}|{rec.partner_iso3}|{rec.year}",
                reporter_iso3=rec.reporter_iso3, partner_iso3=rec.partner_iso3, flow=rec.flow, currency="USD",
                period_start=ps, period_end=pe, period_label=str(rec.year), frequency="A",
                net_weight_kg=rec.net_weight_kg, value=rec.value_usd, hs_code=HS_CODE, value_basis=None,
                notes=(f"FAOSTAT {code}: Natural honey (item 1182), {what}, as reported by "
                       f"{first.area}. Values: imports generally c.i.f., exports f.o.b. (FAO). {flags}"),
                extra=extra, data_status=rec.status, published_at=entry.published, source_url=first.source_url,
                raw_document_id=first.raw_document_id,
            )

    # ------------------------------------------------------------------ warnings
    def report_issues(self) -> None:
        ctx, iss = self.ctx, self.issues
        for ds, msgs in iss.malformed.items():
            for m in msgs[:5]:
                ctx.warn(f"FAOSTAT {ds}: malformed row skipped: {m}")
            if len(msgs) > 5:
                ctx.warn(f"FAOSTAT {ds}: {len(msgs) - 5} more malformed rows skipped")
        for ds, keys in iss.duplicates.items():
            ctx.warn(f"FAOSTAT {ds}: {len(keys)} duplicate country-year row(s) from different FAO areas; "
                     f"one kept (e.g. {keys[0]})")
        for flag, dss in sorted(iss.unknown_flags.items()):
            ctx.warn(f"FAOSTAT: unknown flag {flag!r} in {sorted(dss)}; values stored as 'estimate'")
        for ds, element, unit in sorted(iss.bad_units):
            ctx.warn(f"FAOSTAT {ds}: unexpected unit {unit!r} for '{element}'; rows skipped")
        for code, name in sorted(iss.conflicts.items()):
            ctx.warn(f"FAOSTAT area {code} ({name}): M49 and FAO codes point to different countries; rows skipped")
        if iss.unmapped:
            names = sorted(f"{n} ({c})" for c, n in iss.unmapped.items())
            more = f" and {len(names) - 12} more" if len(names) > 12 else ""
            ctx.warn(f"FAOSTAT: {len(names)} area(s) not in Paladex's country table were skipped: "
                     f"{', '.join(names[:12])}{more}")
            log.info("[%s] FAOSTAT unmapped areas: %s", ctx.source.key, "; ".join(names))
        if iss.skipped:
            log.info("[%s] FAOSTAT rows skipped: %s", ctx.source.key, dict(iss.skipped))


class FaostatCollector(Collector):
    key = "faostat"
    name = "FAOSTAT — produzione, alveari, prezzi alla produzione e commercio di miele"
    publisher = "Food and Agriculture Organization of the United Nations (FAO), FAOSTAT"
    homepage = "https://www.fao.org/faostat/en/"
    kind = SourceKind.BULK_FILE
    reliability = Reliability.OFFICIAL
    category = "production"
    language = "en"
    # Source.expected_update is String(120)
    expected_update = "Annual per dataset (production ~Dec, year Y in Dec Y+1; prices/trade lag 1-2 yrs); checked weekly"
    # Each FAOSTAT dataset is released about once a year (QCL around December, PP and TCL on their
    # own dates). 450 days = one annual cycle plus ~3 months of slack for a late release.
    expected_max_age_days = 450
    terms_note = (
        "Source: FAO. FAOSTAT (QCL, PP, TCL, TM), [year of last update]. Licence: CC BY 4.0 under the FAO "
        "Statistical Database Terms of Use; commercial reuse allowed with attribution. Bulk downloads need no "
        "account; the optional API needs a free FAOSTAT Developer Portal account. Annual data, no split by "
        "honey variety; estimated/imputed values are flagged."
    )
    schedule = {"trigger": "cron", "day_of_week": "wed", "hour": 4, "minute": 50}   # weekly
    order = 70

    def collect(self, ctx: CollectContext) -> None:
        _FaostatRun(ctx).execute()


__all__ = [
    "API_ROOT",
    "CATALOGUE_URL",
    "DATASETS",
    "FLAG_STATUS",
    "LOGIN_URL",
    "MIN_YEAR",
    "TM_REPORTERS",
    "AreaMatch",
    "BulkExtract",
    "CatalogueEntry",
    "FaoRow",
    "FaostatCollector",
    "Issues",
    "build_prices",
    "build_production",
    "build_trade",
    "bulk_rows",
    "classify_trade_element",
    "flag_status",
    "least_firm",
    "local_currency",
    "parse_api_rows",
    "parse_catalogue",
    "parse_value",
    "read_bulk_zip",
    "resolve_area",
]
