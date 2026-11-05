"""Official national trade statistics (government primary sources): two collectors.

* ``br_comexstat``: Brazil, MDIC/SECEX **Comex Stat** API (keyless JSON). Monthly exports of
  natural honey (NCM 04090000) by destination country and by state of production: FOB value in
  USD and net weight in kg, about one week after the month ends. Each destination-month gets one
  trade row (the states summed; the per-state split is kept in ``extra["states"]``) and, when at
  least 1 t was shipped, a derived **export unit value** (FOB USD / kg) with origin BRA and the
  destination as market.

* ``us_census_trade``: United States, **US Census Bureau International Trade API**
  (``timeseries/intltrade/imports/hs``; optional free key ``PALADEX_CENSUS_API_KEY``). Monthly US
  imports of HS 0409 by country of origin: customs value and kg of imports for consumption (the
  same basis as USDA FAS GATS), plus general imports, CIF value, dutiable value and calculated
  duty, with the HS-10 colour/organic lines in ``extra["hs10_lines"]``. One trade row per
  origin-month (and the published "total for all countries" as partner ``WLD``), plus a derived
  **import unit value** (customs value / kg) per origin when at least 1 t was imported.

Overlap with ``usda_fas_gats``. GATS republishes the same Census statistics through USDA, so the
two sources report the same flows. They are stored under different source keys and never merged.
Every row of ``us_census_trade`` carries ``extra["same_underlying_data_as"] = "usda_fas_gats"``.
The trade API already shows one source per figure (never a sum of sources). Any view that
combines price or trade series across sources must keep only one of the two for US imports. The
Census API adds what GATS lacks: every origin, the world total, general imports, the duty actually
assessed and no mandatory key.

Verification status. Comex Stat was checked against the live API on 2026-11-04 (real captures in
``tests/fixtures/trade_official/real_comex_*``); Census was written from
``docs/research/official_north_america_oceania.json`` / ``official_tariffs_trade_policy.json`` and
its fixtures are reconstructions (see the README there). Both collectors check the live API before
they trust it:

* Comex Stat: every run that pulls data first reads ``/general/filters``, ``/general/details``
  and ``/general/metrics``. If the honey query (filter ``ncm``, detail ``country``, metrics FOB
  and KG) can no longer be expressed, the run fails (``CollectorError``) and stores nothing.
  Response columns are mapped dynamically (code/name pairs, numbers as strings). A response that
  ignored the NCM filter is rejected. What the live API taught us: ``period`` is a year range plus
  a month range applied to every year (``comex_query_period``; a 2025-10..2026-09 query is empty,
  which is what the first live run met), errors come as ``{"error": {"code", "message"}}``, and
  ``POST /general`` is rate-limited for minutes at a time (one query per run, patient backoff).
* Census: every run reads ``variables.json``. A missing required variable fails the run. A
  missing optional one (CIF, duty, description) is dropped from the request, with a warning the
  first time. A response without a required column, or one that ignored the commodity filter, is
  rejected.

Freshness and revisions. Comex Stat is checked with one cheap ``GET /general/dates/updated``
(state stored in ``app_settings['collector_state:br_comexstat']``). Only a new release triggers a
re-pull of the trailing 3 months (36 months on the first run), always in ONE query.
Census is re-queried for the trailing 3 months (one small request after the ``variables.json``
probe). When the answer is byte-for-byte the same as before, nothing else is done. The full 36-month window is pulled again once a year after
the June annual revision. Every changed number is stored as a new revision (``services.ingest``),
and a flow the source no longer reports is withdrawn (kept in the history, never deleted).

Not implemented (future): the Comex Stat bulk files ``EXP_YYYY.csv``
(balanca.economia.gov.br/balanca/bd/comexstat-bd/ncm/) as a backfill fallback. Each yearly file is
hundreds of MB and is rewritten every month. Its column list and the PAIS.csv code-table path are
known only from memory (research confidence: from search snippets). The API covers the 36-month
backfill in three requests, so the fallback is not needed yet. Adding it safely needs a streamed
download (``ctx.client.stream`` + ``ctx.wait_for_host``) that keeps only ``CO_NCM == 04090000``
rows and archives only that extract via ``ctx.store_raw``, after the real file has been checked
once.
"""
from __future__ import annotations

import copy
import json
import logging
import math
import re
import time
import unicodedata
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dateutil.parser import isoparse
from sqlalchemy import select

from ..enums import DataStatus, PriceType, Reliability, SourceKind, TradeFlow, Variety
from ..models import AppSetting, PriceObservation, TradeFlowObservation, utcnow
from ..reference.countries import AGGREGATES, country_name, lookup_iso3
from .base import (
    CollectContext,
    Collector,
    CollectorError,
    MissingKey,
    Offline,
    month_bounds,
)

log = logging.getLogger(__name__)

JSON_HEADERS = {"Accept": "application/json"}

# A customs unit value says nothing about the bulk market on tiny consignments (samples, a few
# jars), so a price row is derived only from at least this much. The trade row is always kept.
# Same threshold as Eurostat Comext / TAXUD (collectors/eu.py).
MIN_UNIT_VALUE_WEIGHT_KG = 1_000.0

Month = tuple[int, int]


def today() -> date:
    """Reference date for the look-back windows (indirection so tests can pin it)."""
    return date.today()


# ===========================================================================
# Shared helpers
# ===========================================================================


def _num(v: Any) -> float | None:
    """A finite number from a JSON number or a plain numeric string ('1234', '1234.5'), else None."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        f = float(v)
    elif isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            f = float(s)
        except ValueError:
            return None
    else:
        return None
    return f if math.isfinite(f) else None


def _sum_opt(values: Iterable[float | None]) -> float | None:
    """Sum, or None when any part is unknown (a partial sum is never presented as the total)."""
    vals = list(values)
    if not vals or any(v is None for v in vals):
        return None
    return float(sum(vals))


def _load_json(content: bytes, what: str) -> Any:
    try:
        return json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        snippet = content[:120].decode("utf-8", errors="replace").strip()
        raise CollectorError(f"{what}: response is not valid JSON ({exc}); starts with {snippet!r}") from exc


def _midx(ym: Month) -> int:
    return ym[0] * 12 + ym[1] - 1


def _from_idx(i: int) -> Month:
    return i // 12, i % 12 + 1


def shift_month(ym: Month, delta: int) -> Month:
    return _from_idx(_midx(ym) + delta)


def month_label(ym: Month) -> str:
    return f"{ym[0]:04d}-{ym[1]:02d}"


def parse_month_label(value: Any) -> Month | None:
    m = re.fullmatch(r"\s*(\d{4})-(\d{1,2})\s*", str(value or ""))
    if not m or not 1 <= int(m.group(2)) <= 12:
        return None
    return int(m.group(1)), int(m.group(2))


def month_windows(start: Month, end: Month, size: int) -> list[tuple[Month, Month]]:
    """Split the months start..end (inclusive) into windows of at most `size` months, newest first
    (so a late failure still leaves the most recent data stored)."""
    if _midx(start) > _midx(end):
        return []
    out = []
    hi = _midx(end)
    lo_limit = _midx(start)
    while hi >= lo_limit:
        lo = max(lo_limit, hi - size + 1)
        out.append((_from_idx(lo), _from_idx(hi)))
        hi = lo - 1
    return out


def _state_key(source_key: str) -> str:
    return f"collector_state:{source_key}"


def _load_state(ctx: CollectContext) -> dict:
    """Per-collector bookkeeping in `app_settings` (commits and rolls back with the data)."""
    row = ctx.session.get(AppSetting, _state_key(ctx.source.key))
    return copy.deepcopy(row.value) if row is not None and isinstance(row.value, dict) else {}


def _save_state(ctx: CollectContext, state: dict) -> None:
    row = ctx.session.get(AppSetting, _state_key(ctx.source.key))
    if row is None:
        ctx.session.add(AppSetting(key=_state_key(ctx.source.key), value=copy.deepcopy(state)))
    else:
        row.value = copy.deepcopy(state)        # a new object, so SQLAlchemy sees the JSON change
    ctx.session.flush()


def _warn_once(ctx: CollectContext, state: dict, token: str, message: str) -> None:
    """`ctx.warn` the first time `token` is met (remembered in the collector state), then only log.
    A condition that cannot change by itself (an unmapped partner) must not mark every run partial."""
    warned = state.setdefault("warned", [])
    if token in warned:
        log.info("[%s] %s", ctx.source.key, message)
        return
    warned.append(token)
    ctx.warn(message)


def _has_rows(ctx: CollectContext) -> bool:
    T = TradeFlowObservation
    return ctx.session.scalar(select(T.id).where(T.source_id == ctx.source.id).limit(1)) is not None


def _retire_absent(ctx: CollectContext, *, prefix: str, months: set[str], present: set[str],
                   price_key: Callable[[str, str], str]) -> list[str]:
    """Withdraw the current trade rows (and their unit values) of `months` that a fresh answer no
    longer contains. They stay in the history; only `is_current` is cleared (ingest.retire)."""
    if not months:
        return []
    T = TradeFlowObservation
    rows = ctx.session.execute(select(T.series_key, T.partner_iso3, T.period_label).where(
        T.source_id == ctx.source.id, T.is_current.is_(True), T.is_demo.is_(False),
        T.period_label.in_(sorted(months)), T.series_key.startswith(prefix),
    )).all()
    gone = []
    for key, partner, label in rows:
        if key in present:
            continue
        ctx.retire(T, key)
        ctx.retire(PriceObservation, price_key(partner, label))
        gone.append(f"{partner} {label}")
    return sorted(gone)


# ---------------------------------------------------------------------------
# Country names -> ISO3
# ---------------------------------------------------------------------------


def _norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# Names the shared country reference does not resolve: English as Comex Stat (language=en) and
# Census (upper case) publish them, plus Portuguese (Comex Stat's default language). ISO 3166-1
# alpha-3 values; a country outside the reference table is stored under its ISO3 code.
_EXTRA_NAMES_RAW: dict[str, str] = {
    # Portuguese names of countries in the reference table
    "Alemanha": "DEU", "Países Baixos": "NLD", "Holanda": "NLD", "Reino Unido": "GBR", "Bélgica": "BEL",
    "França": "FRA", "Espanha": "ESP", "Japão": "JPN", "Arábia Saudita": "SAU", "Emirados Árabes Unidos": "ARE",
    "Coreia do Sul": "KOR", "Coreia, República da": "KOR", "Formosa": "TWN", "Suíça": "CHE", "Dinamarca": "DNK",
    "Suécia": "SWE", "Noruega": "NOR", "Uruguai": "URY", "Paraguai": "PRY", "África do Sul": "ZAF",
    "Líbano": "LBN", "Jordânia": "JOR", "Catar": "QAT", "Kuweit": "KWT", "Omã": "OMN", "Iêmen": "YEM",
    "Egito": "EGY", "Marrocos": "MAR", "Argélia": "DZA", "Rússia": "RUS", "Romênia": "ROU", "Hungria": "HUN",
    "Sérvia": "SRB", "Croácia": "HRV", "Luxemburgo": "LUX", "Tchéquia": "CZE", "República Tcheca": "CZE",
    "Eslováquia": "SVK", "Eslovênia": "SVN", "Letônia": "LVA", "Lituânia": "LTU", "Chipre": "CYP",
    "Nova Zelândia": "NZL", "Tailândia": "THA", "Vietnã": "VNM", "Filipinas": "PHL", "Malásia": "MYS",
    "Indonésia": "IDN", "Irã": "IRN", "Belarus": "BLR", "Bielorrússia": "BLR", "Cazaquistão": "KAZ",
    "Quirguistão": "KGZ", "Paquistão": "PAK", "Mianmar": "MMR", "Macedônia do Norte": "MKD",
    "Bósnia-Herzegovina": "BIH", "Montenegro": "MNE", "Albânia": "ALB", "Moldávia": "MDA", "Etiópia": "ETH",
    "Quênia": "KEN", "Tanzânia": "TZA", "Austrália": "AUS", "Estônia": "EST", "Finlândia": "FIN",
    "Irlanda": "IRL", "Islândia": "ISL", "Grécia": "GRC", "Bulgária": "BGR", "Áustria": "AUT", "Polônia": "POL",
    "Itália": "ITA", "Canadá": "CAN", "México": "MEX", "Colômbia": "COL", "Peru": "PER", "Bolívia": "BOL",
    "Índia": "IND", "Turquia": "TUR", "Ucrânia": "UKR", "Hong Kong": "HKG",
    # English variants (Comex Stat / Census spelling)
    "Taiwan (Formosa)": "TWN", "Korea, South": "KOR", "Korea, Republic of": "KOR", "Burma": "MMR",
    "Russian Federation": "RUS", "Czech Republic": "CZE", "Bosnia-Herzegovina": "BIH", "Bosnia Herzegovina": "BIH",
    "Macedonia, North": "MKD", "Moldova, Republic of": "MDA", "Kyrgyz Republic": "KGZ",
    # Countries outside the reference table (stored under their ISO3 code)
    "Singapore": "SGP", "Cingapura": "SGP", "Macau": "MAC", "Macao": "MAC", "Panama": "PAN", "Panamá": "PAN",
    "Costa Rica": "CRI", "Honduras": "HND", "Dominican Republic": "DOM", "República Dominicana": "DOM",
    "Jamaica": "JAM", "Haiti": "HTI", "Trinidad and Tobago": "TTO", "Trinidad e Tobago": "TTO",
    "Bahamas": "BHS", "Barbados": "BRB", "Ecuador": "ECU", "Equador": "ECU", "Venezuela": "VEN",
    "Guyana": "GUY", "Guiana": "GUY", "Suriname": "SUR", "Angola": "AGO", "Mozambique": "MOZ",
    "Moçambique": "MOZ", "Cape Verde": "CPV", "Cabo Verde": "CPV", "Nigeria": "NGA", "Nigéria": "NGA",
    "Ghana": "GHA", "Gana": "GHA", "Senegal": "SEN", "Ivory Coast": "CIV", "Cote d'Ivoire": "CIV",
    "Costa do Marfim": "CIV", "Cameroon": "CMR", "Camarões": "CMR", "Libya": "LBY", "Líbia": "LBY",
    "Sudan": "SDN", "Uganda": "UGA", "Rwanda": "RWA", "Zambia": "ZMB", "Zimbabwe": "ZWE", "Madagascar": "MDG",
    "Mauritius": "MUS", "Namibia": "NAM", "Botswana": "BWA", "Malawi": "MWI", "Iraq": "IRQ", "Iraque": "IRQ",
    "Syria": "SYR", "Síria": "SYR", "Bahrain": "BHR", "Bahrein": "BHR", "Afghanistan": "AFG",
    "Bangladesh": "BGD", "Sri Lanka": "LKA", "Nepal": "NPL", "Cambodia": "KHM", "Camboja": "KHM",
    "Laos": "LAO", "Brunei": "BRN", "Mongolia": "MNG", "Mongólia": "MNG", "Korea, North": "PRK",
    "Uzbekistan": "UZB", "Uzbequistão": "UZB", "Tajikistan": "TJK", "Turkmenistan": "TKM", "Georgia": "GEO",
    "Geórgia": "GEO", "Armenia": "ARM", "Armênia": "ARM", "Azerbaijan": "AZE", "Azerbaijão": "AZE",
    "Iceland": "ISL", "Kosovo": "XKX", "Andorra": "AND", "Monaco": "MCO", "Liechtenstein": "LIE",
    "Gibraltar": "GIB", "Papua New Guinea": "PNG", "Fiji": "FJI", "New Caledonia": "NCL",
    "French Polynesia": "PYF", "Samoa": "WSM", "Tonga": "TON", "Greenland": "GRL", "Bermuda": "BMU",
    "Cayman Islands": "CYM", "Aruba": "ABW", "Curacao": "CUW", "Curaçao": "CUW",
    # English names exactly as Comex Stat publishes them (GET /general/filters/country?language=en,
    # 2026-11-04) that the forms above do not resolve. Isle of Man, Marshall Islands and England
    # were checked against the ISO alpha-3 Comex Stat gives itself (/tables/countries/{id}).
    "Isle of Man": "IMN", "Marshall Islands": "MHL", "England": "GBR", "Liberia": "LBR", "Benin": "BEN",
    "Bhutan": "BTN", "Burundi": "BDI", "Chad": "TCD", "Comoros": "COM", "Congo": "COG", "Cote D'Ivore": "CIV",
    "Djibouti": "DJI", "Dominica Island": "DMA", "East Timor": "TLS", "Equatorial Guinea": "GNQ",
    "Eritrea": "ERI", "Falkland Islands (Malvinas)": "FLK", "Faroe Islands": "FRO", "French Guyana": "GUF",
    "Gabon": "GAB", "Gambia": "GMB", "Grenada": "GRD", "Guadeloupe": "GLP", "Guam": "GUM", "Guernsey": "GGY",
    "Guinea": "GIN", "Guinea-Bissau": "GNB", "Jersey": "JEY", "Kiribati": "KIR", "Lesotho": "LSO",
    "Maldives": "MDV", "Mali": "MLI", "Martinique": "MTQ", "Mauritania": "MRT", "Mayotte": "MYT",
    "Micronesia": "FSM", "Montserrat": "MSR", "Nauru": "NRU", "Niger": "NER", "North Korea": "PRK",
    "Northern Marianas": "MNP", "Palau": "PLW", "Palestine": "PSE", "Puerto Rico": "PRI", "Reunion": "REU",
    "Saint Lucia": "LCA", "Saint Christopher and Nevis": "KNA", "St. Kitts and Nevis": "KNA",
    "Saint Vicent and the Granadines": "VCT", "San Marino": "SMR", "Seychelles": "SYC", "Sierra Leone": "SLE",
    "Solomon Islands": "SLB", "Somalia": "SOM", "South Sudan": "SSD", "Swaziland": "SWZ", "Togo": "TGO",
    "Tuvalu": "TUV", "Vanuatu": "VUT", "Vatican City": "VAT", "Virgin Islands (UK)": "VGB", "Anguilla": "AIA",
    "Antigua and Barbuda": "ATG", "Americana Samoa": "ASM", "Cook Islands": "COK", "Saint Helena": "SHN",
    "Saint Pierre and Miquelon": "SPM", "Sint Maarten": "SXM", "Turks and Caicos, Islands": "TCA",
    "Wallis and Futuna": "WLF", "São Tome and Principe": "STP",
}
_EXTRA_NAMES: dict[str, str] = {_norm_name(k): v for k, v in _EXTRA_NAMES_RAW.items()}


def resolve_country_name(name: Any) -> str | None:
    """ISO3 of a published country name (EN/PT/IT/ES, any case), or None when unknown.

    Tries the full name, then "A (B)" as A and as B, then "KOREA, SOUTH" as "SOUTH KOREA".
    Aggregates ("World", "Total") are never returned: totals are recognised explicitly.
    """
    if not isinstance(name, str) or not name.strip():
        return None
    name = name.strip()
    candidates = [name]
    m = re.fullmatch(r"(.*?)\s*\((.*?)\)\s*", name)
    if m:
        candidates += [m.group(1), m.group(2)]
    if "," in name:
        a, b = name.split(",", 1)
        candidates.append(f"{b} {a}")
    for cand in candidates:
        n = _norm_name(cand)
        if len(n) < 3:
            continue                # never treat a 2-letter fragment as an ISO2 code
        iso = _EXTRA_NAMES.get(n) or lookup_iso3(cand)
        if iso and iso not in AGGREGATES:
            return iso
    return None


# ===========================================================================
# 1) Brazil: MDIC/SECEX Comex Stat API
# ===========================================================================

COMEX_BASE = "https://api-comexstat.mdic.gov.br"
COMEX_UPDATED_URL = f"{COMEX_BASE}/general/dates/updated"
COMEX_FILTERS_URL = f"{COMEX_BASE}/general/filters"
COMEX_DETAILS_URL = f"{COMEX_BASE}/general/details"
COMEX_METRICS_URL = f"{COMEX_BASE}/general/metrics"
COMEX_GENERAL_URL = f"{COMEX_BASE}/general"
COMEX_QUERY_LANGUAGE = "en"                 # English country names (mapped to ISO3 below)
COMEX_SOURCE_URL = f"{COMEX_GENERAL_URL}?language={COMEX_QUERY_LANGUAGE}"
COMEX_WEB_UI = "https://comexstat.mdic.gov.br/en/geral"
HONEY_NCM = "04090000"
COMEX_BACKFILL_MONTHS = 36
COMEX_REPULL_MONTHS = 3                    # recent months are revised: re-pulled at every release
# The API answers HTTP 429 {"error": {"code": 429, "message": "... tente novamente em 10 segundos."}}
# but, seen live on 2026-11-04, keeps refusing POST /general for several minutes (the limit is
# shared by every client behind an address). One query per run, and a patient backoff:
# 15, 30, 60, then 120 s, about 12 minutes in all, before giving up until the next run.
COMEX_RATE_LIMIT_RETRIES = 8
COMEX_RATE_LIMIT_DELAY_S = 15.0
COMEX_RATE_LIMIT_MAX_DELAY_S = 120.0

# Candidate names (the server's own spelling, discovered at startup, wins).
_COMEX_NCM_FILTER = ("ncm",)
_COMEX_COUNTRY_DETAIL = ("country",)
_COMEX_STATE_DETAIL = ("state", "uf")
_COMEX_NCM_DETAIL = ("ncm",)
_COMEX_FOB_METRIC = ("metricFOB", "FOB")
_COMEX_KG_METRIC = ("metricKG", "KG")

# Response columns (mapped dynamically: names may come as code/name pairs, e.g. coNcm + ncm).
_COMEX_YEAR_KEYS = ("year", "coAno", "ano", "CO_ANO")
_COMEX_MONTH_KEYS = ("monthNumber", "coMes", "month", "mes", "CO_MES")
_COMEX_COUNTRY_NAME_KEYS = ("country", "noPaisIng", "noPaisEn", "noPais", "countryName", "pais", "NO_PAIS")
_COMEX_COUNTRY_CODE_KEYS = ("coPais", "countryCode", "coCountry", "idCountry", "CO_PAIS")
_COMEX_COUNTRY_ISO_KEYS = ("coPaisIsoa3", "countryIso3", "iso3", "CO_PAIS_ISOA3")
_COMEX_STATE_NAME_KEYS = ("state", "noUf", "stateName", "NO_UF")
_COMEX_STATE_CODE_KEYS = ("sgUf", "coUf", "stateCode", "uf", "SG_UF", "SG_UF_NCM")
_COMEX_NCM_CODE_KEYS = ("coNcm", "ncmCode", "CO_NCM")
_COMEX_NCM_NAME_KEYS = ("ncm", "noNcm", "noNcmIng", "noNcmEn")
_COMEX_FOB_KEYS = ("metricFOB", "vlFob", "VL_FOB", "FOB")
_COMEX_KG_KEYS = ("metricKG", "kgLiquido", "KG_LIQUIDO", "KG")

_RATE_LIMIT_RE = re.compile(r"too many|rate.?limit|limite de (requisi|acesso)|muitas requisi|try again|"
                            r"tente novamente|aguarde", re.IGNORECASE)


@dataclass(frozen=True)
class ComexRelease:
    latest: Month                   # newest month loaded in Comex Stat
    released: date | None           # the release ("updated") date, when the API gives it
    raw: str                        # as published, for the state signature

    @property
    def signature(self) -> str:
        return f"{month_label(self.latest)}|{self.raw}"


@dataclass(frozen=True)
class ComexSpec:
    """The honey query in the API's own vocabulary (discovered at startup)."""

    ncm_filter: str
    country_detail: str
    state_detail: str | None
    ncm_detail: str | None
    fob_metric: str
    kg_metric: str


@dataclass
class ComexRow:
    year: int
    month: int
    country_name: str | None
    country_code: str | None
    country_iso3: str | None        # ISO alpha-3 published by Comex Stat itself, if any
    state: str | None
    state_code: str | None
    fob_usd: float | None           # None only on a bad (unusable) row
    kg: float | None

    @property
    def period(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


@dataclass
class ComexParse:
    rows: list[ComexRow]
    problems: list[str]
    # Rows with unusable numbers: their destination-month is not stored (a partial sum of states
    # would be presented as the total). A bad row without a destination blocks its whole month.
    bad_rows: list[ComexRow] = field(default_factory=list)
    bad_months: set[str] = field(default_factory=set)


def _comex_error(doc: Any) -> str | None:
    """The error message of an answer: {"success": false, "message": ...} or {"error": {"code",
    "message"}} (the shape the live API uses for 400/429/500), else None."""
    if not isinstance(doc, dict):
        return None
    err = doc.get("error")
    if isinstance(err, dict):
        return str(err.get("message") or err.get("code") or err)
    if doc.get("success") is False:
        return str(doc.get("message") or err or "no message")
    return None


def _comex_payload(content: bytes, what: str) -> Any:
    doc = _load_json(content, f"Comex Stat {what}")
    msg = _comex_error(doc)
    if msg is not None:
        raise CollectorError(f"Comex Stat {what}: the API answered with an error ({msg[:200]})")
    return doc


def _comex_list(doc: Any, what: str) -> list:
    """The list of records in a Comex Stat answer: {"data": {"list": [...]}} or close variants."""
    data = doc.get("data", doc) if isinstance(doc, dict) else doc
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("list", "items", "results", "rows"):
            if isinstance(data.get(k), list):
                return data[k]
    raise CollectorError(f"Comex Stat {what}: no record list in the answer (keys: "
                         f"{sorted(doc)[:10] if isinstance(doc, dict) else type(doc).__name__}); format changed?")


def parse_comex_updated(content: bytes) -> ComexRelease:
    """`GET /general/dates/updated`: the newest month loaded and the release date."""
    doc = _comex_payload(content, "dates/updated")
    data = doc.get("data", doc) if isinstance(doc, dict) else doc
    if isinstance(data, list) and len(data) == 1:
        data = data[0]
    if not isinstance(data, dict):
        raise CollectorError(f"Comex Stat dates/updated: unexpected answer {str(doc)[:200]!r}")
    year = _int_from(_first(data, _COMEX_YEAR_KEYS))
    month = _month_from(_first(data, _COMEX_MONTH_KEYS))
    raw_date = _first(data, ("updated", "lastUpdate", "dateUpdated", "updatedAt", "date", "data"))
    if year is None or month is None:
        raise CollectorError(f"Comex Stat dates/updated: no year/month in {str(data)[:200]!r} (format changed?)")
    released = _parse_release_date(raw_date)
    return ComexRelease(latest=(year, month), released=released, raw=str(raw_date or ""))


def _first(rec: dict, keys: Iterable[str]) -> Any:
    for k in keys:
        if k in rec and rec[k] not in (None, ""):
            return rec[k]
    lower = {str(k).lower(): k for k in rec}
    for k in keys:
        real = lower.get(k.lower())
        if real is not None and rec[real] not in (None, ""):
            return rec[real]
    return None


def _int_from(v: Any) -> int | None:
    f = _num(v)
    return int(f) if f is not None and f == int(f) else None


def _month_from(v: Any) -> int | None:
    """9, "9", "09" or "09. September" -> 9."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        m = _int_from(v)
    else:
        mm = re.match(r"\s*(\d{1,2})\b", str(v or ""))
        m = int(mm.group(1)) if mm else None
    return m if m is not None and 1 <= m <= 12 else None


def _parse_release_date(v: Any) -> date | None:
    s = str(v or "").strip()
    if not s:
        return None
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)         # Brazilian dd/mm/yyyy
    try:
        if m:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        return isoparse(s).date()
    except (ValueError, OverflowError):
        return None


def parse_comex_names(content: bytes, what: str) -> list[str]:
    """Names offered by /general/filters, /general/details or /general/metrics (any of the usual
    shapes: a list of strings, or of objects with an id/filter/detail/metric field)."""
    doc = _comex_payload(content, what)
    data = doc.get("data", doc) if isinstance(doc, dict) else doc
    if isinstance(data, dict) and not any(isinstance(data.get(k), list) for k in ("list", "items", "results", "rows")):
        items: list = list(data.keys())              # {"data": {"country": {...}, ...}}
    else:
        items = _comex_list(doc, what)
    names: list[str] = []
    for it in items:
        if isinstance(it, str) and it.strip():
            names.append(it.strip())
        elif isinstance(it, dict):
            for k in ("filter", "detail", "metric", "id", "name", "value", "key", "code"):
                v = it.get(k)
                if isinstance(v, str) and v.strip() and v.strip() not in names:
                    names.append(v.strip())
    if not names:
        raise CollectorError(f"Comex Stat {what}: the list contains no names (format changed?)")
    return names


def _pick(available: list[str], candidates: Iterable[str]) -> str | None:
    """The API's own spelling of the first candidate it offers (exact match first: names are
    case-sensitive), else None."""
    cands = list(candidates)
    for c in cands:
        if c in available:
            return c
    lower = {a.lower(): a for a in available}
    for c in cands:
        if c.lower() in lower:
            return lower[c.lower()]
    return None


def resolve_comex_spec(filters: list[str], details: list[str], metrics: list[str]) -> ComexSpec:
    """Express the honey query with the names the API offers, or fail loudly."""
    ncm = _pick(filters, _COMEX_NCM_FILTER)
    country = _pick(details, _COMEX_COUNTRY_DETAIL)
    fob = _pick(metrics, _COMEX_FOB_METRIC)
    kg = _pick(metrics, _COMEX_KG_METRIC)
    missing = [what for what, got in (("filter 'ncm'", ncm), ("detail 'country'", country),
                                      ("metric FOB", fob), ("metric KG", kg)) if got is None]
    if missing:
        raise CollectorError(
            f"Comex Stat: the honey query can no longer be expressed: {', '.join(missing)} not offered "
            f"(filters: {filters[:25]}; details: {details[:25]}; metrics: {metrics[:25]}); nothing stored")
    return ComexSpec(ncm_filter=ncm, country_detail=country, state_detail=_pick(details, _COMEX_STATE_DETAIL),
                     ncm_detail=_pick(details, _COMEX_NCM_DETAIL), fob_metric=fob, kg_metric=kg)


def comex_query_body(spec: ComexSpec, start: Month, end: Month) -> dict:
    details = [spec.country_detail]
    if spec.state_detail:
        details.append(spec.state_detail)
    if spec.ncm_detail:
        details.append(spec.ncm_detail)            # lets us check the filter was applied
    return {
        "flow": "export", "monthDetail": True,
        "period": {"from": month_label(start), "to": month_label(end)},
        "filters": [{"filter": spec.ncm_filter, "values": [HONEY_NCM]}],
        "details": details,
        "metrics": [spec.fob_metric, spec.kg_metric],
    }


def is_comex_rate_limited(status: int, content: bytes) -> bool:
    if status == 429:
        return True
    try:
        doc = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return False
    if isinstance(doc, dict) and isinstance(doc.get("error"), dict) and str(doc["error"].get("code")) == "429":
        return True
    msg = _comex_error(doc)
    return bool(msg and _RATE_LIMIT_RE.search(msg))


def _comex_error_text(content: bytes) -> str:
    try:
        doc = json.loads(content.decode("utf-8-sig"))
        msg = _comex_error(doc)
        if msg is not None:
            return msg[:200]
        if isinstance(doc, dict):
            return str(doc.get("message") or doc)[:200]
    except (UnicodeDecodeError, ValueError):
        pass
    return content[:200].decode("utf-8", errors="replace").strip()


def month_label_span(body: dict) -> str:
    period = body.get("period") or {}
    return f"{period.get('from')}..{period.get('to')}"


def _key_in(keys: set[str], candidates: Iterable[str]) -> str | None:
    for c in candidates:
        if c in keys:
            return c
    lower = {k.lower(): k for k in keys}
    for c in candidates:
        if c.lower() in lower:
            return lower[c.lower()]
    return None


def comex_query_period(start: Month, end: Month) -> tuple[Month, Month]:
    """The `period` to send for the months start..end (inclusive).

    Comex Stat reads `period` as a year range AND a month range applied to every year (like its web
    form): {"from": "2025-10", "to": "2026-09"} means months 10..9 of 2025-2026, which is empty, and
    {"from": "2024-02", "to": "2025-03"} means February-March of 2024 and of 2025 (checked live on
    2026-11-04). Months of one year are asked as they are; a span over several years asks for whole
    years (January to December), and the rows outside start..end are dropped by the parser."""
    if start[0] == end[0]:
        return start, end
    return (start[0], 1), (end[0], 12)


def parse_comex_general(content: bytes, spec: ComexSpec, start: Month, end: Month,
                        query: tuple[Month, Month] | None = None) -> ComexParse:
    """Parse a `POST /general` answer into one row per month x country (x state).

    Fails loudly (CollectorError) on schema drift: no year/month/country/FOB/KG column, or rows of
    another product (the NCM filter was ignored). A row with unusable numbers is reported in
    `bad_rows` (its destination-month is then not stored, so a partial sum of states is never
    presented as the total); one without a destination marks its whole month bad. Rows outside
    start..end are dropped: silently when the `query` period asked for them (whole years, see
    `comex_query_period`), with a problem otherwise.
    """
    doc = _comex_payload(content, "general")
    items = _comex_list(doc, "general")
    out = ComexParse(rows=[], problems=[])
    rows = [r for r in items if isinstance(r, dict)]
    if len(rows) != len(items):
        out.problems.append(f"Comex Stat: {len(items) - len(rows)} record(s) are not objects; ignored")
    if not rows:
        return out
    keys: set[str] = set().union(*(r.keys() for r in rows))
    k_year, k_month = _key_in(keys, _COMEX_YEAR_KEYS), _key_in(keys, _COMEX_MONTH_KEYS)
    k_cname, k_ccode = _key_in(keys, _COMEX_COUNTRY_NAME_KEYS), _key_in(keys, _COMEX_COUNTRY_CODE_KEYS)
    k_ciso = _key_in(keys, _COMEX_COUNTRY_ISO_KEYS)
    k_fob = _key_in(keys, (spec.fob_metric, *_COMEX_FOB_KEYS))
    k_kg = _key_in(keys, (spec.kg_metric, *_COMEX_KG_KEYS))
    k_sname = _key_in(keys, (spec.state_detail or "state", *_COMEX_STATE_NAME_KEYS)) if spec.state_detail else None
    k_scode = _key_in(keys - {k_sname}, _COMEX_STATE_CODE_KEYS) if spec.state_detail else None
    k_ncode = _key_in(keys, _COMEX_NCM_CODE_KEYS)
    k_nname = _key_in(keys - {k_ncode}, (spec.ncm_detail or "ncm", *_COMEX_NCM_NAME_KEYS))
    missing = [n for n, k in (("year", k_year), ("month", k_month), ("FOB", k_fob), ("KG", k_kg)) if k is None]
    if k_cname is None and k_ccode is None and k_ciso is None:
        missing.append("country")
    if missing:
        raise CollectorError(f"Comex Stat schema drift: column(s) {missing} missing from the answer "
                             f"(columns: {sorted(keys)[:30]}); nothing stored")
    if spec.state_detail and k_sname is None and k_scode is None:
        out.problems.append("Comex Stat: the state detail was requested but no state column came back; "
                            "country totals stored without the state split")

    lo, hi = _midx(start), _midx(end)
    q_years = (query[0][0], query[1][0]) if query else (start[0], end[0])
    outside: set[str] = set()
    asked_for = 0                                    # rows of the query period outside start..end
    for i, r in enumerate(rows):
        # Product guard: every row must be NCM 04090000 when the product is echoed back.
        for k in (k_ncode, k_nname):
            if k is None or r.get(k) in (None, ""):
                continue
            v = str(r[k]).strip()
            digits = re.sub(r"\D", "", v)
            if (digits and len(digits) >= 4 and digits != HONEY_NCM) or (not digits and not re.search(r"honey|mel\b|miel", v, re.IGNORECASE)):
                raise CollectorError(f"Comex Stat ignored the NCM {HONEY_NCM} filter (row {i} is {v!r}); nothing stored")
        year, month = _int_from(r.get(k_year)), _month_from(r.get(k_month))
        if year is None or month is None:
            out.problems.append(f"Comex Stat row {i}: unreadable year/month {r.get(k_year)!r}/{r.get(k_month)!r}; skipped")
            continue
        label = f"{year:04d}-{month:02d}"
        if not lo <= _midx((year, month)) <= hi:
            if query and q_years[0] <= year <= q_years[1]:
                asked_for += 1
            else:
                outside.add(label)
            continue
        cname = str(r[k_cname]).strip() if k_cname and r.get(k_cname) not in (None, "") else None
        ccode = str(r[k_ccode]).strip() if k_ccode and r.get(k_ccode) not in (None, "") else None
        ciso = str(r[k_ciso]).strip().upper() if k_ciso and r.get(k_ciso) not in (None, "") else None
        if cname is None and ccode is None and ciso is None:
            out.problems.append(f"Comex Stat row {i} ({label}): no destination country; month {label} not stored")
            out.bad_months.add(label)
            continue
        fob, kg = _num(r.get(k_fob)), _num(r.get(k_kg))
        row = ComexRow(
            year=year, month=month, country_name=cname, country_code=ccode,
            country_iso3=ciso if ciso and re.fullmatch(r"[A-Z]{3}", ciso) else None,
            state=str(r[k_sname]).strip() if k_sname and r.get(k_sname) not in (None, "") else None,
            state_code=str(r[k_scode]).strip() if k_scode and r.get(k_scode) not in (None, "") else None,
            fob_usd=fob, kg=kg,
        )
        if fob is None or kg is None or fob < 0 or kg < 0:
            out.problems.append(f"Comex Stat row {i} ({label}, {cname or ccode}): invalid FOB={r.get(k_fob)!r} / "
                                f"KG={r.get(k_kg)!r}; that destination-month is not stored")
            out.bad_rows.append(row)
            continue
        out.rows.append(row)
    if outside:
        out.problems.append(f"Comex Stat returned months outside the requested {month_label(start)}..{month_label(end)} "
                            f"({', '.join(sorted(outside))}); ignored")
    if rows and not out.rows and not out.bad_rows and not out.bad_months and not asked_for:
        raise CollectorError("Comex Stat: no row of the answer could be read (format changed?); nothing stored")
    return out


def map_comex_partner(row: ComexRow) -> str | None:
    """ISO3 of a Comex Stat destination: the ISO alpha-3 the API publishes, else the name."""
    if row.country_iso3:
        return row.country_iso3
    return resolve_country_name(row.country_name)


@dataclass
class _ComexAgg:
    iso3: str
    period: str
    year: int
    month: int
    fob_usd: float = 0.0
    kg: float = 0.0
    names: list[str] = field(default_factory=list)
    codes: list[str] = field(default_factory=list)
    states: dict[str, dict] = field(default_factory=dict)


class BrComexStatCollector(Collector):
    key = "br_comexstat"
    name = "Brasile – MDIC/SECEX Comex Stat: esportazioni di miele (NCM 04090000)"
    publisher = "MDIC – Secretaria de Comércio Exterior (SECEX), Brazil"
    homepage = "https://comexstat.mdic.gov.br"
    kind = SourceKind.API
    reliability = Reliability.OFFICIAL
    category = "trade"
    country_iso3 = "BRA"
    language = "pt"
    expected_update = "Mensile, nella prima settimana dopo il mese (insieme al comunicato MDIC sulla bilancia commerciale)"
    expected_update_en = "Monthly, in the first week after the month (same day as the MDIC trade-balance release)"
    expected_max_age_days = 40
    terms_note = ("Fonte: MDIC/SECEX – Comex Stat. Brazilian federal open data (Lei 12.527/2011), free "
                  "reuse citing the source. FOB values in USD and net weight in kg, by destination and "
                  "state of production. The latest months are revised: the trailing three months are "
                  "pulled again at every release and each change is kept as a revision. Export unit "
                  "values are derived (FOB / net kg), not market quotations.")
    # One cheap freshness request a day; the data are pulled only when a new release appears.
    schedule = {"trigger": "cron", "hour": 9, "minute": 40}

    def collect(self, ctx: CollectContext) -> None:
        state = _load_state(ctx)
        release = self._probe_release(ctx)
        have_rows = _has_rows(ctx)
        if (have_rows and not ctx.force and state.get("backfill_done")
                and state.get("release") == release.signature):
            log.info("[%s] Comex Stat release %s unchanged; nothing to pull", self.key, release.signature)
            return
        if release.released is None:
            _warn_once(ctx, state, "no_release_date",
                       "Comex Stat dates/updated gave no release date; rows are stored without publication date")
        spec = self._discover(ctx, state)
        latest = release.latest
        if ctx.force or not have_rows or not state.get("backfill_done"):
            start = shift_month(latest, -(COMEX_BACKFILL_MONTHS - 1))
        else:
            # The trailing 3 months of this release, extended back to the first month not seen yet
            # when releases were missed (no gap), but never beyond the backfill window.
            prev = parse_month_label(state.get("latest_month")) or latest
            start = min(shift_month(latest, -(COMEX_REPULL_MONTHS - 1)), shift_month(prev, 1), key=_midx)
            start = max(start, shift_month(latest, -(COMEX_BACKFILL_MONTHS - 1)), key=_midx)
        # One query (see comex_query_period): fewer requests against a strict rate limit.
        self._pull_window(ctx, state, spec, release, start, latest)
        _save_state(ctx, state)                  # warn-once tokens and unknown partners
        ctx.checkpoint()
        state.update({
            "release": release.signature, "latest_month": month_label(latest),
            "release_date": release.released.isoformat() if release.released else None,
            "backfill_done": True, "spec": asdict(spec), "pulled_at": utcnow().isoformat(timespec="seconds"),
        })
        _save_state(ctx, state)

    # ------------------------------------------------------------------ probes
    def _probe_release(self, ctx: CollectContext) -> ComexRelease:
        doc = ctx.fetch(COMEX_UPDATED_URL, headers=JSON_HEADERS, store=False)
        return parse_comex_updated(doc.content)

    def _discover(self, ctx: CollectContext, state: dict) -> ComexSpec:
        names = {}
        for what, url in (("filters", COMEX_FILTERS_URL), ("details", COMEX_DETAILS_URL), ("metrics", COMEX_METRICS_URL)):
            doc = ctx.fetch(url, headers=JSON_HEADERS, store=False)
            names[what] = parse_comex_names(doc.content, what)
        spec = resolve_comex_spec(names["filters"], names["details"], names["metrics"])
        if spec.state_detail is None:
            _warn_once(ctx, state, "no_state_detail",
                       "Comex Stat no longer offers the 'state' detail: country totals are stored without the state split")
        return spec

    # ------------------------------------------------------------------ data
    def _post_general(self, ctx: CollectContext, body: dict, title: str) -> tuple[bytes, int, bool]:
        """POST the query with backoff on rate-limit answers. Returns (content, raw_id, unchanged).
        Only a usable answer is archived."""
        delay = COMEX_RATE_LIMIT_DELAY_S
        for attempt in range(COMEX_RATE_LIMIT_RETRIES + 1):
            # retries=0: the backoff below is the only one (the generic quick retries of ctx.fetch
            # would only add requests inside the window the API is refusing).
            doc = ctx.fetch(COMEX_GENERAL_URL, params={"language": COMEX_QUERY_LANGUAGE}, method="POST",
                            json_body=body, headers=JSON_HEADERS, accept_status=(200, 400, 429, 500), store=False,
                            retries=0)
            if not is_comex_rate_limited(doc.status_code, doc.content):
                if doc.status_code != 200:
                    raise CollectorError(f"Comex Stat rejected the honey query (HTTP {doc.status_code}: "
                                         f"{_comex_error_text(doc.content)}) for {month_label_span(body)}")
                raw_id, unchanged = ctx.store_raw(COMEX_SOURCE_URL, doc.content, doc.content_type, title=title)
                return doc.content, raw_id, unchanged
            if attempt == COMEX_RATE_LIMIT_RETRIES:
                break
            log.info("[%s] Comex Stat rate limit; waiting %.0f s before retrying", self.key, delay)
            time.sleep(delay)
            delay = min(delay * 2, COMEX_RATE_LIMIT_MAX_DELAY_S)
        raise CollectorError(f"Comex Stat kept answering 'too many requests' after {COMEX_RATE_LIMIT_RETRIES} "
                             f"retries ({title}); the data will be pulled on the next run")

    def _pull_window(self, ctx: CollectContext, state: dict, spec: ComexSpec, release: ComexRelease,
                     ws: Month, we: Month) -> None:
        qs, qe = comex_query_period(ws, we)
        body = comex_query_body(spec, qs, qe)
        title = f"Comex Stat honey exports {month_label(ws)}..{month_label(we)} {json.dumps(body, separators=(',', ':'))}"
        content, raw_id, unchanged = self._post_general(ctx, body, title)
        if unchanged and not ctx.force:
            log.info("[%s] %s..%s: same answer as already stored", self.key, month_label(ws), month_label(we))
            return
        parsed = parse_comex_general(content, spec, ws, we, query=(qs, qe))
        for p in parsed.problems:
            ctx.warn(p)
        if not parsed.rows and not parsed.bad_rows and not parsed.bad_months:
            ctx.warn(f"Comex Stat returned no honey export rows for {month_label(ws)}..{month_label(we)}")
            return
        # Months that cannot be fully trusted: not used to withdraw rows the answer seems to lack.
        unsure_months: set[str] = set(parsed.bad_months)
        blocked: set[tuple[str, str]] = set()           # (iso3, period) with an unusable row
        for bad in parsed.bad_rows:
            iso = map_comex_partner(bad)
            unsure_months.add(bad.period)
            if iso is None:
                parsed.bad_months.add(bad.period)
            else:
                blocked.add((iso, bad.period))
        aggs: dict[tuple[str, str], _ComexAgg] = {}
        for row in parsed.rows:
            if row.period in parsed.bad_months:
                continue
            iso = map_comex_partner(row)
            if iso is None:
                unsure_months.add(row.period)
                label = row.country_name or row.country_code or "?"
                state.setdefault("unknown_partners", {})[label] = row.country_code
                _warn_once(ctx, state, f"partner:{label}",
                           f"Comex Stat destination {label!r} (code {row.country_code}) has no ISO3 mapping; its rows "
                           "are skipped until it is added to trade_official._EXTRA_NAMES_RAW")
                continue
            if (iso, row.period) in blocked:
                continue
            agg = aggs.get((iso, row.period))
            if agg is None:
                agg = aggs[(iso, row.period)] = _ComexAgg(iso, row.period, row.year, row.month)
            agg.fob_usd += row.fob_usd
            agg.kg += row.kg
            if row.country_name and row.country_name not in agg.names:
                agg.names.append(row.country_name)
            if row.country_code and row.country_code not in agg.codes:
                agg.codes.append(row.country_code)
            if row.state or row.state_code:
                skey = row.state_code or row.state
                st = agg.states.setdefault(skey, {"state": row.state, "state_code": row.state_code,
                                                  "fob_usd": 0.0, "kg": 0.0})
                st["fob_usd"] += row.fob_usd
                st["kg"] += row.kg
        present: set[str] = set()
        query = {"period": body["period"], "details": body["details"], "metrics": body["metrics"],
                 "filters": body["filters"]}
        for (iso, period), agg in sorted(aggs.items(), key=lambda kv: (kv[0][1], kv[0][0])):
            present.add(self._store(ctx, release, raw_id, spec, query, agg))
        months = {r.period for r in parsed.rows} - unsure_months
        gone = _retire_absent(ctx, prefix="comexstat|BRA|", months=months, present=present,
                              price_key=lambda p, lab: f"{PriceType.EXPORT_UNIT_VALUE.value}|comexstat|{p}|BRA|{lab}")
        if gone:
            ctx.warn(f"Comex Stat release {release.raw or month_label(release.latest)} no longer reports "
                     f"{', '.join(gone)}: those rows are withdrawn (kept in the history)")

    def _store(self, ctx: CollectContext, release: ComexRelease, raw_id: int, spec: ComexSpec, query: dict,
               agg: _ComexAgg) -> str:
        p_start, p_end = month_bounds(agg.year, agg.month)
        states = sorted(({**v, "fob_usd": round(v["fob_usd"], 2), "kg": round(v["kg"], 3)} for v in agg.states.values()),
                        key=lambda s: -s["kg"])
        destination = agg.names[0] if agg.names else country_name(agg.iso3, "en")
        extra = {
            "ncm": HONEY_NCM, "destination_name": destination, "destination_codes": agg.codes or None,
            "state_detail": bool(spec.state_detail), "states": states or None,
            "release_latest_month": month_label(release.latest), "release_updated": release.raw or None,
            "query": query, "web_ui": COMEX_WEB_UI,
        }
        common = dict(period_start=p_start, period_end=p_end, period_label=agg.period, frequency="M",
                      published_at=release.released, source_url=COMEX_SOURCE_URL, raw_document_id=raw_id or None,
                      data_status=DataStatus.PUBLISHED, reliability=Reliability.OFFICIAL)
        series = f"comexstat|BRA|{agg.iso3}|export|{agg.period}"
        ctx.add_trade(
            series_key=series, hs_code="0409", reporter_iso3="BRA", partner_iso3=agg.iso3,
            flow=TradeFlow.EXPORT.value, currency="USD", value=round(agg.fob_usd, 2), net_weight_kg=round(agg.kg, 3),
            value_basis="FOB", extra=extra,
            notes=("Esportazioni brasiliane di miele naturale NCM 04090000 (MDIC/SECEX Comex Stat): valore FOB "
                   "in USD e peso netto, somma degli stati di produzione (dettaglio per stato in 'extra')."),
            **common,
        )
        price_series = f"comexstat|{agg.iso3}|BRA|{agg.period}"
        if agg.kg >= MIN_UNIT_VALUE_WEIGHT_KG and agg.fob_usd > 0:
            ctx.add_price(
                series_key=price_series, price_type=PriceType.EXPORT_UNIT_VALUE, variety=Variety.UNSPECIFIED.value,
                price_value=round(agg.fob_usd / agg.kg, 4), currency="USD", unit="kg", origin_iso3="BRA",
                origin_label="Brazil", market_iso3=agg.iso3, market_location=destination, terms="FOB",
                variety_raw="NCM 04090000 natural honey", volume_kg=round(agg.kg, 3),
                notes=("Valore unitario all'esportazione = valore FOB / peso netto (MDIC/SECEX Comex Stat, "
                       "NCM 04090000). Dato doganale derivato, non una quotazione di mercato."),
                extra={**extra, "fob_usd": round(agg.fob_usd, 2), "kg": round(agg.kg, 3)},
                **common,
            )
        else:
            # A revision can push a flow below the threshold: its earlier unit value is withdrawn.
            ctx.retire(PriceObservation, f"{PriceType.EXPORT_UNIT_VALUE.value}|{price_series}")
        return series


# ===========================================================================
# 2) United States: US Census Bureau International Trade API (imports, HS)
# ===========================================================================

CENSUS_URL = "https://api.census.gov/data/timeseries/intltrade/imports/hs"
CENSUS_VARIABLES_URL = f"{CENSUS_URL}/variables.json"
CENSUS_KEY_SIGNUP = "https://api.census.gov/data/key_signup.html"
HONEY_HS6 = "040900"
HONEY_HS10_WILDCARD = "0409*"
# Honey HTS-10 lines (research; confirm against the current HTSUS). Used only when the wildcard
# query is not supported: one request per line.
HONEY_HS10_CODES = ("0409000005", "0409000010", "0409000035", "0409000045", "0409000056", "0409000065")
CENSUS_BACKFILL_MONTHS = 36
CENSUS_REPULL_MONTHS = 3
CENSUS_MAX_MONTHS_PER_QUERY = 12
CENSUS_ANNUAL_REVISION = (6, 15)            # Census publishes the annual revision in early June
# Bumped whenever the parsing changes: answers already stored (unchanged since) are then read again
# once, so rows an older version could not read are not skipped forever as "already seen".
# 2: HS-6 rows without a quantity take their weight from the HS-10 lines (Nov 2026).
CENSUS_PARSER_VERSION = 2

# `get=` list from the research (official_north_america_oceania.json, official_tariffs_trade_policy.json).
CENSUS_REQUIRED_VARS = ("CTY_CODE", "CTY_NAME", "I_COMMODITY", "GEN_VAL_MO", "GEN_QY1_MO", "UNIT_QY1",
                        "CON_VAL_MO", "CON_QY1_MO")
CENSUS_OPTIONAL_VARS = ("I_COMMODITY_SDESC", "GEN_CIF_MO", "CON_CIF_MO", "DUT_VAL_MO", "CAL_DUT_MO", "SUMMARY_LVL")
CENSUS_PREDICATE_VARS = ("COMM_LVL",)       # used as a filter; must exist too
CENSUS_KG_UNIT = "KG"

# Census Schedule C country codes of the main honey origins, with the name Census publishes.
# This table is a CROSS-CHECK: the published name must agree with it (else the row is skipped
# with a warning). Codes not listed are mapped by their published name.
CENSUS_COUNTRIES: dict[str, tuple[str, str]] = {
    "1220": ("CAN", "CANADA"), "2010": ("MEX", "MEXICO"), "2050": ("GTM", "GUATEMALA"),
    "2110": ("SLV", "EL SALVADOR"), "2190": ("NIC", "NICARAGUA"), "3010": ("COL", "COLOMBIA"),
    "3330": ("PER", "PERU"), "3370": ("CHL", "CHILE"), "3510": ("BRA", "BRAZIL"), "3530": ("PRY", "PARAGUAY"),
    "3550": ("URY", "URUGUAY"), "3570": ("ARG", "ARGENTINA"), "4120": ("GBR", "UNITED KINGDOM"),
    "4210": ("NLD", "NETHERLANDS"), "4231": ("BEL", "BELGIUM"), "4279": ("FRA", "FRANCE"),
    "4280": ("DEU", "GERMANY"), "4330": ("AUT", "AUSTRIA"), "4370": ("HUN", "HUNGARY"),
    "4419": ("CHE", "SWITZERLAND"), "4550": ("POL", "POLAND"), "4621": ("RUS", "RUSSIA"),
    "4623": ("UKR", "UKRAINE"), "4641": ("MDA", "MOLDOVA"), "4700": ("ESP", "SPAIN"),
    "4710": ("PRT", "PORTUGAL"), "4759": ("ITA", "ITALY"), "4801": ("SRB", "SERBIA"),
    "4840": ("GRC", "GREECE"), "4850": ("ROU", "ROMANIA"), "4870": ("BGR", "BULGARIA"),
    "4890": ("TUR", "TURKEY"), "5081": ("ISR", "ISRAEL"), "5330": ("IND", "INDIA"),
    "5350": ("PAK", "PAKISTAN"), "5490": ("THA", "THAILAND"), "5520": ("VNM", "VIETNAM"),
    "5570": ("MYS", "MALAYSIA"), "5600": ("IDN", "INDONESIA"), "5700": ("CHN", "CHINA"),
    "5800": ("KOR", "KOREA, SOUTH"), "5820": ("HKG", "HONG KONG"), "5830": ("TWN", "TAIWAN"),
    "5880": ("JPN", "JAPAN"), "6021": ("AUS", "AUSTRALIA"), "6141": ("NZL", "NEW ZEALAND"),
}
_TOTAL_NAMES = {"total for all countries", "total all countries", "world total", "world"}

CENSUS_OVERLAP_NOTE = ("Same US Census statistics that USDA FAS GATS (usda_fas_gats) republishes: "
                       "never add or average the two sources.")


class CensusError(CollectorError):
    """The Census API refused or could not answer a query."""


@dataclass
class CensusRecord:
    cty_code: str
    cty_name: str
    commodity: str
    description: str | None
    year: int
    month: int
    unit: str
    gen_val: float | None
    gen_kg: float | None
    con_val: float | None
    con_kg: float | None
    gen_cif: float | None
    con_cif: float | None
    dut_val: float | None
    cal_dut: float | None
    summary_lvl: str | None

    @property
    def period(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


@dataclass
class CensusParse:
    records: list[CensusRecord]
    problems: list[str]
    bad: set[tuple[str, str]] = field(default_factory=set)   # (cty_code, period) with an unusable row


def parse_census_variables(content: bytes) -> set[str]:
    """Variable names listed by `variables.json` ({"variables": {"NAME": {...}, ...}})."""
    doc = _load_json(content, "Census variables.json")
    variables = doc.get("variables") if isinstance(doc, dict) else None
    if not isinstance(variables, dict) or not variables:
        raise CollectorError("Census variables.json has no 'variables' object (format changed?)")
    return {str(k) for k in variables}


def census_get_list(available: set[str]) -> tuple[list[str], list[str]]:
    """(variables to request, optional variables that are missing). Fails loudly when a required
    variable or predicate is gone."""
    missing = [v for v in (*CENSUS_REQUIRED_VARS, *CENSUS_PREDICATE_VARS) if v not in available]
    if missing:
        raise CollectorError(f"Census schema drift: variable(s) {missing} no longer listed in variables.json; "
                             "nothing stored")
    optional_missing = [v for v in CENSUS_OPTIONAL_VARS if v not in available]
    return [*CENSUS_REQUIRED_VARS, *(v for v in CENSUS_OPTIONAL_VARS if v in available)], optional_missing


def parse_census_table(content: bytes) -> list[dict[str, Any]]:
    """Census answers a JSON array of arrays whose first row is the header. A variable used both in
    `get=` and as a predicate comes back twice: the first column wins. Empty body (HTTP 204) = []."""
    if not content.strip():
        return []
    data = _load_json(content, "Census API")
    if not isinstance(data, list) or not data or not isinstance(data[0], list):
        raise CollectorError(f"Census API: expected an array of arrays with a header row, got {str(data)[:150]!r}")
    header = [str(h) for h in data[0]]
    index: dict[str, int] = {}
    for i, h in enumerate(header):
        index.setdefault(h, i)
    out = []
    for r in data[1:]:
        if not isinstance(r, list) or len(r) != len(header):
            raise CollectorError(f"Census API: a row does not match the {len(header)}-column header ({str(r)[:120]!r})")
        out.append({h: r[i] for h, i in index.items()})
    return out


def parse_census_imports(content: bytes, *, level: str, start: Month, end: Month) -> CensusParse:
    """Parse an imports/hs answer for HS 0409 (`level` "HS6" or "HS10").

    Fails loudly on schema drift (a required column or `time` missing) and when a row is another
    commodity (the filter was ignored). Malformed rows are reported; their country-month is not
    stored. Rows outside the requested months are dropped.
    """
    rows = parse_census_table(content)
    out = CensusParse(records=[], problems=[])
    if not rows:
        return out
    cols = set(rows[0])
    missing = [c for c in (*CENSUS_REQUIRED_VARS, "time") if c not in cols]
    if missing:
        raise CollectorError(f"Census schema drift: column(s) {missing} missing from the answer (columns: "
                             f"{sorted(cols)}); nothing stored")
    lo, hi = _midx(start), _midx(end)
    for i, r in enumerate(rows):
        commodity = re.sub(r"\D", "", str(r.get("I_COMMODITY") or ""))
        ok = commodity == HONEY_HS6 if level == "HS6" else (len(commodity) == 10 and commodity.startswith("0409"))
        if not ok:
            raise CollectorError(f"Census ignored the commodity filter ({level}: row {i} is {r.get('I_COMMODITY')!r}); "
                                 "nothing stored")
        ym = parse_month_label(r.get("time"))
        code = str(r.get("CTY_CODE") or "").strip()
        if ym is None:
            out.problems.append(f"Census row {i}: unreadable time {r.get('time')!r}; skipped")
            continue
        if not lo <= _midx(ym) <= hi:
            out.problems.append(f"Census row {i}: month {month_label(ym)} outside the requested window; ignored")
            continue
        rec = CensusRecord(
            cty_code=code, cty_name=str(r.get("CTY_NAME") or "").strip(), commodity=commodity,
            description=(str(r["I_COMMODITY_SDESC"]).strip() or None) if r.get("I_COMMODITY_SDESC") else None,
            year=ym[0], month=ym[1], unit=str(r.get("UNIT_QY1") or "").strip().upper(),
            gen_val=_num(r.get("GEN_VAL_MO")), gen_kg=_num(r.get("GEN_QY1_MO")),
            con_val=_num(r.get("CON_VAL_MO")), con_kg=_num(r.get("CON_QY1_MO")),
            gen_cif=_num(r.get("GEN_CIF_MO")), con_cif=_num(r.get("CON_CIF_MO")),
            dut_val=_num(r.get("DUT_VAL_MO")), cal_dut=_num(r.get("CAL_DUT_MO")),
            summary_lvl=(str(r["SUMMARY_LVL"]).strip().upper() or None) if r.get("SUMMARY_LVL") else None,
        )
        # Census does not total quantities at HS-6 for honey: the HS-6 rows carry unit "-" and
        # quantity 0 (checked live, Nov 2026). That 0 is "not reported", never a weight: it is
        # dropped here and the weight comes from the HS-10 lines (all in KG) in `_store`.
        weight_from_lines = level == "HS6" and rec.unit in ("", "-")
        if weight_from_lines:
            rec.unit, rec.con_kg, rec.gen_kg = "", None, None
        if (rec.con_val is None or rec.con_val < 0 or (rec.con_kg is None and not weight_from_lines)
                or (rec.con_kg is not None and rec.con_kg < 0)):
            out.problems.append(f"Census row {i} ({code} {rec.cty_name}, {rec.period}): invalid CON_VAL_MO="
                                f"{r.get('CON_VAL_MO')!r} / CON_QY1_MO={r.get('CON_QY1_MO')!r}; not stored")
            out.bad.add((code, rec.period))
            continue
        if rec.unit and rec.unit != CENSUS_KG_UNIT:
            out.problems.append(f"Census row {i} ({code} {rec.cty_name}, {rec.period}): quantity unit "
                                f"{rec.unit!r} is not {CENSUS_KG_UNIT}; not stored")
            out.bad.add((code, rec.period))
            continue
        out.records.append(rec)
    return out


def classify_census_country(code: str, name: str, summary_lvl: str | None = None) -> tuple[str | None, str]:
    """(ISO3 or "WLD" or None, how): how is "total", "code", "name", "aggregate", "conflict" or "unknown".

    The published total is "WLD". Country groupings (SUMMARY_LVL "CGP", codes like 0003 or 4XXX)
    are aggregates and skipped. A real Schedule C country code is four digits starting 1-7.
    """
    code = (code or "").strip().upper()
    norm = _norm_name(name or "")
    if norm in _TOTAL_NAMES or (code == "-" and not norm):
        return "WLD", "total"
    if code == "-":
        return None, "unknown"          # "-" with an unexpected name: never guessed to be the total
    if (summary_lvl or "").upper() == "CGP" or "X" in code or code.startswith("0"):
        return None, "aggregate"
    if not re.fullmatch(r"[1-7]\d{3}", code):
        return None, "unknown"
    by_name = resolve_country_name(name)
    entry = CENSUS_COUNTRIES.get(code)
    if entry is not None:
        iso, expected = entry
        if by_name == iso or (by_name is None and norm == _norm_name(expected)):
            return iso, "code"
        return None, "conflict"
    if by_name:
        return by_name, "name"
    return None, "unknown"


@dataclass
class _CensusQuery:
    public_url: str                 # without the key
    raw_id: int
    unchanged: bool
    content: bytes


@dataclass
class _CensusAgg:
    iso3: str
    period: str
    year: int
    month: int
    how: str
    codes: list[str] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    recs: list[CensusRecord] = field(default_factory=list)


def _drop_key(url: str) -> str:
    parts = urlsplit(url)
    pairs = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() != "key"]
    return urlunsplit(parts._replace(query=urlencode(pairs)))


def _scrub(text: str, secret: str | None) -> str:
    return text.replace(secret, "REDACTED") if secret else text


class UsCensusTradeCollector(Collector):
    key = "us_census_trade"
    name = "US Census Bureau – Importazioni USA di miele per origine (HS 0409)"
    publisher = "U.S. Census Bureau, Economic Indicators Division (International Trade)"
    homepage = "https://www.census.gov/data/developers/data-sets/international-trade.html"
    kind = SourceKind.API
    reliability = Reliability.OFFICIAL
    category = "trade"
    country_iso3 = "USA"
    language = "en"
    expected_update = "Mensile, circa 5 settimane dopo il mese (comunicato FT-900); revisione annuale a giugno"
    expected_update_en = "Monthly, about 5 weeks after the month (FT-900 release); annual revision in June"
    expected_max_age_days = 50
    terms_note = ("Source: U.S. Census Bureau, International Trade API (public domain). SAME underlying "
                  "statistics as USDA FAS GATS: the two sources must never be added together. Value = customs "
                  "value of imports for consumption (excludes freight, insurance and duty), as in GATS; general "
                  "imports, CIF value, dutiable value and calculated duty (excluding AD/CVD) are kept alongside. "
                  "Monthly figures are revised once a year (June). The API gives no release date: the "
                  "publication date stays empty and freshness is judged on the collection date. Optional free "
                  "key (PALADEX_CENSUS_API_KEY) for higher limits.")
    requires_key = "census_api_key"
    key_optional = True
    schedule = {"trigger": "cron", "day_of_week": "mon,thu", "hour": 16, "minute": 10}

    def collect(self, ctx: CollectContext) -> None:
        api_key = (self.key_value(ctx.settings) or "").strip() or None
        state = _load_state(ctx)
        get_vars = self._probe_variables(ctx, state)
        t = today()
        end = shift_month((t.year, t.month), -1)
        full = (ctx.force or not _has_rows(ctx) or not state.get("backfill_done")
                or self._annual_refresh_due(state, t))
        floor = shift_month(end, -(CENSUS_BACKFILL_MONTHS - 1))
        if full:
            start = floor
        else:
            latest = parse_month_label(state.get("latest")) or end
            start = max(shift_month(min(latest, end, key=_midx), -(CENSUS_REPULL_MONTHS - 1)), floor, key=_midx)
        newest = parse_month_label(state.get("latest"))
        reparse = ctx.force or not _has_rows(ctx) or state.get("parser_version") != CENSUS_PARSER_VERSION
        for ws, we in month_windows(start, end, CENSUS_MAX_MONTHS_PER_QUERY):
            got = self._pull_window(ctx, state, get_vars, api_key, ws, we, reparse=reparse)
            if got and (newest is None or _midx(got) > _midx(newest)):
                newest = got
            _save_state(ctx, state)
            ctx.checkpoint()
        if newest:
            state["latest"] = month_label(newest)
        if full:
            state["backfill_done"] = True
            if t >= date(t.year, *CENSUS_ANNUAL_REVISION):
                state["annual_refresh_year"] = t.year
        state["pulled_at"] = utcnow().isoformat(timespec="seconds")
        state["parser_version"] = CENSUS_PARSER_VERSION
        _save_state(ctx, state)

    @staticmethod
    def _annual_refresh_due(state: dict, t: date) -> bool:
        return t >= date(t.year, *CENSUS_ANNUAL_REVISION) and int(state.get("annual_refresh_year") or 0) < t.year

    # ------------------------------------------------------------------ probes
    def _probe_variables(self, ctx: CollectContext, state: dict) -> list[str]:
        # Metadata needs no key: none is sent.
        doc = ctx.fetch(CENSUS_VARIABLES_URL, headers=JSON_HEADERS, store=False)
        if doc.content.lstrip()[:1] == b"<":
            raise CollectorError("Census variables.json answered an HTML page instead of JSON (maintenance?)")
        get_vars, optional_missing = census_get_list(parse_census_variables(doc.content))
        if optional_missing:
            _warn_once(ctx, state, "optional_vars:" + ",".join(optional_missing),
                       f"Census variables.json no longer lists {optional_missing}: requested without them "
                       "(the related details stay empty)")
        return get_vars

    # ------------------------------------------------------------------ queries
    def _query(self, ctx: CollectContext, get_vars: list[str], level: str, commodity: str, ws: Month, we: Month,
               api_key: str | None) -> _CensusQuery | None:
        """One imports/hs query. None when Census has no matching row (HTTP 204)."""
        span = month_label(ws) if ws == we else f"from {month_label(ws)} to {month_label(we)}"
        params = {"get": ",".join(get_vars), "COMM_LVL": level, "I_COMMODITY": commodity, "time": span}
        if api_key:
            params["key"] = api_key         # Census accepts the key only as a query parameter: redacted on storage
        doc = ctx.fetch(CENSUS_URL, params=params, headers=JSON_HEADERS, store=False,
                        accept_status=(200, 204, 400, 401, 403, 404, 429))
        public_url = _drop_key(doc.url)
        if doc.status_code == 429:          # still limited after the polite retries: transient, not drift
            hint = "" if api_key else f"; a free key raises the limit (PALADEX_CENSUS_API_KEY, {CENSUS_KEY_SIGNUP})"
            raise CollectorError(f"The US Census API rate limit was reached{hint}; the data will be pulled on the next run")
        looks_html = doc.content.lstrip()[:1] == b"<"
        if doc.status_code in (401, 403) or (doc.status_code == 200 and looks_html):
            text = doc.content[:2000].decode("utf-8", errors="replace")
            if doc.status_code in (401, 403) or re.search(r"\bkey\b", text, re.IGNORECASE):
                if api_key:
                    raise CollectorError("The US Census API rejected the API key (invalid or not activated yet); "
                                         "check PALADEX_CENSUS_API_KEY")
                raise MissingKey("The US Census API refused a request without a key: set PALADEX_CENSUS_API_KEY "
                                 f"(free, {CENSUS_KEY_SIGNUP})")
            raise CensusError(f"Census answered an HTML page instead of data for {public_url} (maintenance?)")
        if doc.status_code in (400, 404):
            text = _scrub(doc.content[:300].decode("utf-8", errors="replace").strip(), api_key)
            raise CensusError(f"Census rejected the query (HTTP {doc.status_code}: {text!r}) for {public_url}")
        if doc.status_code == 204 or not doc.content.strip():
            return None
        title = f"US Census imports {level} {commodity} {span}"
        raw_id, unchanged = ctx.store_raw(public_url, doc.content, doc.content_type, title=title)
        return _CensusQuery(public_url=public_url, raw_id=raw_id, unchanged=unchanged, content=doc.content)

    def _pull_window(self, ctx: CollectContext, state: dict, get_vars: list[str], api_key: str | None,
                     ws: Month, we: Month, *, reparse: bool = False) -> Month | None:
        """Pull one window. Returns the newest month the answer contains (None if empty).
        `reparse`: read the answer even when it is unchanged since it was stored."""
        try:
            q = self._query(ctx, get_vars, "HS6", HONEY_HS6, ws, we, api_key)
        except CensusError as exc:
            raise CollectorError(f"{exc}; nothing stored for {month_label(ws)}..{month_label(we)}") from exc
        if q is None:
            log.info("[%s] no HS 0409 imports published for %s..%s", self.key, month_label(ws), month_label(we))
            return None
        if q.unchanged and not reparse:
            log.info("[%s] %s..%s: same answer as already stored", self.key, month_label(ws), month_label(we))
            return _newest_in(q.content)
        parsed = parse_census_imports(q.content, level="HS6", start=ws, end=we)
        for p in parsed.problems:
            ctx.warn(p)
        hs10, hs10_status = self._hs10_lines(ctx, state, get_vars, api_key, ws, we, bool(parsed.records))
        aggs: dict[tuple[str, str], _CensusAgg] = {}
        skipped_months: set[str] = {p for _, p in parsed.bad}
        for rec in parsed.records:
            iso, how = classify_census_country(rec.cty_code, rec.cty_name, rec.summary_lvl)
            if iso is None:
                if how != "aggregate":
                    skipped_months.add(rec.period)
                    self._report_unmapped(ctx, state, rec, how)
                continue
            agg = aggs.get((iso, rec.period))
            if agg is None:
                agg = aggs[(iso, rec.period)] = _CensusAgg(iso, rec.period, rec.year, rec.month, how)
            agg.recs.append(rec)
            if rec.cty_code not in agg.codes:
                agg.codes.append(rec.cty_code)
            if rec.cty_name not in agg.names:
                agg.names.append(rec.cty_name)
        present: set[str] = set()
        for (iso, period), agg in sorted(aggs.items(), key=lambda kv: (kv[0][1], kv[0][0])):
            if any((c, period) in parsed.bad for c in agg.codes):
                continue
            present.add(self._store(ctx, q, agg, hs10, hs10_status))
        months = {r.period for r in parsed.records} - skipped_months
        gone = _retire_absent(ctx, prefix="census|USA|", months=months, present=present,
                              price_key=lambda p, lab: f"{PriceType.IMPORT_UNIT_VALUE.value}|census|USA|{p}|0409|{lab}")
        if gone:
            ctx.warn(f"US Census no longer reports HS 0409 imports for {', '.join(gone)}: those rows are withdrawn "
                     "(kept in the history)")
        periods = [(r.year, r.month) for r in parsed.records]
        return max(periods, key=_midx) if periods else None

    def _report_unmapped(self, ctx: CollectContext, state: dict, rec: CensusRecord, how: str) -> None:
        unknown = state.setdefault("unknown_partners", {})
        unknown[rec.cty_code] = rec.cty_name
        if how == "conflict":
            iso, expected = CENSUS_COUNTRIES[rec.cty_code]
            msg = (f"Census country code {rec.cty_code} is published as {rec.cty_name!r}, but the code table says "
                   f"{expected!r} ({iso}); its rows are skipped until the table in trade_official.py is checked")
        else:
            msg = (f"Census country {rec.cty_code} {rec.cty_name!r} has no ISO3 mapping; its rows are skipped until it "
                   "is added to trade_official.CENSUS_COUNTRIES or _EXTRA_NAMES_RAW")
        _warn_once(ctx, state, f"partner:{rec.cty_code}:{rec.cty_name}", msg)

    def _hs10_lines(self, ctx: CollectContext, state: dict, get_vars: list[str], api_key: str | None,
                    ws: Month, we: Month, have_totals: bool) -> tuple[dict[tuple[str, str], list[CensusRecord]], str]:
        """HS-10 colour/organic lines of the window, by (CTY_CODE, period). Returns (lines, status).

        A query Census refuses for good (HTTP 400/404, an HTML page: `CensusError`) or an answer in an
        unexpected shape degrades to "unavailable": the totals are still stored. A transient failure
        (rate limit, server error, timeout, offline) propagates and fails the window instead,
        because a trade row stored without its lines could never get them later (append-only)."""
        if not have_totals:
            return {}, "none"
        errors: list[str] = []

        def lines_for(commodity: str) -> list[CensusRecord]:
            try:
                q = self._query(ctx, get_vars, "HS10", commodity, ws, we, api_key)
            except CensusError as exc:              # refused for good; transient errors propagate
                errors.append(f"{commodity}: {exc}")
                return []
            if q is None:
                return []
            try:
                return parse_census_imports(q.content, level="HS10", start=ws, end=we).records
            except CollectorError as exc:           # an HS-10 answer in an unexpected shape
                errors.append(f"{commodity}: {exc}")
                return []

        recs: list[CensusRecord] = []
        if state.get("hs10_mode", "wildcard") == "wildcard":
            recs = lines_for(HONEY_HS10_WILDCARD)
            # HS6 has rows, so HS-10 lines exist: nothing back means the prefix wildcard is unsupported.
            state["hs10_mode"] = "wildcard" if recs else "per_code"
            if not recs:
                log.info("[%s] HS-10 wildcard query gave nothing; switching to one query per HS-10 line", self.key)
        if state.get("hs10_mode") == "per_code":
            for code in HONEY_HS10_CODES:
                recs += lines_for(code)
        if not recs:
            detail = f" ({'; '.join(errors)[:300]})" if errors else ""
            _warn_once(ctx, state, "hs10_unavailable",
                       f"Census HS-10 honey lines unavailable{detail}; HS 0409 totals are stored without the line split")
            return {}, "unavailable"
        if errors:
            log.warning("[%s] some HS-10 queries failed: %s", self.key, "; ".join(errors)[:500])
        out: dict[tuple[str, str], list[CensusRecord]] = defaultdict(list)
        for r in recs:
            out[(r.cty_code, r.period)].append(r)
        return out, "ok"

    def _store(self, ctx: CollectContext, q: _CensusQuery, agg: _CensusAgg,
               hs10: dict[tuple[str, str], list[CensusRecord]], hs10_status: str) -> str:
        recs = agg.recs
        con_val = float(sum(r.con_val for r in recs))
        gen_val = _sum_opt(r.gen_val for r in recs)
        con_cif, gen_cif = _sum_opt(r.con_cif for r in recs), _sum_opt(r.gen_cif for r in recs)
        dut_val, cal_dut = _sum_opt(r.dut_val for r in recs), _sum_opt(r.cal_dut for r in recs)
        lines: list[dict] | None = None
        flags: dict[str, Any] = {}
        line_recs: list[CensusRecord] = []
        lines_agree = False
        if hs10_status == "ok":
            line_recs = [ln for c in agg.codes for ln in hs10.get((c, agg.period), [])]
            lines = [{"hs10": ln.commodity, "description": ln.description, "kg": ln.con_kg, "value_usd": ln.con_val,
                      "cif_value_usd": ln.con_cif, "calculated_duty_usd": ln.cal_dut}
                     for ln in sorted(line_recs, key=lambda x: x.commodity)]
            line_sum = sum(ln.con_val for ln in line_recs)
            if not line_recs:
                lines = None
                flags["hs10_missing_for_partner"] = True
            elif abs(line_sum - con_val) > max(0.01 * con_val, 1.0):
                flags["hs10_sum_differs_from_total"] = True
            else:
                lines_agree = True
        if all(r.con_kg is not None for r in recs):
            con_kg: float | None = float(sum(r.con_kg for r in recs))
            gen_kg = _sum_opt(r.gen_kg for r in recs)
            quantity_field = "CON_QY1_MO"
        elif lines_agree and all(ln.unit == CENSUS_KG_UNIT and ln.con_kg is not None for ln in line_recs):
            # HS-6 totals carry no quantity: the weight is the sum of the HS-10 lines (all in KG),
            # used only when their values add up to the HS-6 value.
            con_kg = float(sum(ln.con_kg for ln in line_recs))
            gen_kg = _sum_opt(ln.gen_kg for ln in line_recs)
            quantity_field = "CON_QY1_MO, sum of the HS-10 lines (Census gives no HS-6 quantity)"
            flags["quantity_from_hs10_lines"] = True
        else:
            con_kg, gen_kg = None, None   # value only: a weight is never guessed
            quantity_field = None
            flags["quantity_unavailable"] = True
        p_start, p_end = month_bounds(agg.year, agg.month)
        published_name = agg.names[0] if agg.names else ""
        label = country_name(agg.iso3, "en")
        if label == agg.iso3:
            label = published_name.title() if published_name else agg.iso3
        extra = {
            "cty_code": agg.codes[0] if len(agg.codes) == 1 else agg.codes, "cty_name": published_name,
            "mapped_by": agg.how, "hs6": HONEY_HS6,
            "same_underlying_data_as": "usda_fas_gats", "overlap_note": CENSUS_OVERLAP_NOTE,
            "value_field": "CON_VAL_MO", "quantity_field": quantity_field,
            "quantity_unit": CENSUS_KG_UNIT if con_kg is not None else None,
            "general_imports": {"value_usd": gen_val, "kg": gen_kg},
            "cif_value_usd": con_cif, "general_cif_value_usd": gen_cif,
            "dutiable_value_usd": dut_val, "calculated_duty_usd": cal_dut,
            "effective_duty_rate": round(cal_dut / con_val, 6) if cal_dut is not None and con_val > 0 else None,
            "duty_note": "calculated duty = Census estimate from HTS rate provisions; excludes AD/CVD, MPF and HMF",
            "hs10_detail": hs10_status, "hs10_lines": lines, **flags,
        }
        common = dict(period_start=p_start, period_end=p_end, period_label=agg.period, frequency="M",
                      published_at=None, source_url=q.public_url, raw_document_id=q.raw_id or None,
                      data_status=DataStatus.PUBLISHED, reliability=Reliability.OFFICIAL)
        series = f"census|USA|{agg.iso3}|import|0409|{agg.period}"
        ctx.add_trade(
            series_key=series, hs_code="0409", reporter_iso3="USA", partner_iso3=agg.iso3,
            flow=TradeFlow.IMPORT.value, currency="USD", value=con_val, net_weight_kg=con_kg, value_basis="customs",
            notes=("Importazioni USA per consumo di miele HS 0409 (US Census Bureau). Valore doganale (esclusi nolo, "
                   "assicurazione e dazi); importazioni generali, valore CIF e dazio calcolato in 'extra'. "
                   "Stessi dati di USDA FAS GATS: non sommare le due fonti."),
            extra=extra, **common,
        )
        price_series = f"census|USA|{agg.iso3}|0409|{agg.period}"
        if agg.iso3 == "WLD":
            return series                   # the world total is not a price "by origin"
        if con_kg is not None and con_kg >= MIN_UNIT_VALUE_WEIGHT_KG and con_val > 0:
            ctx.add_price(
                series_key=price_series, price_type=PriceType.IMPORT_UNIT_VALUE, variety=Variety.UNSPECIFIED.value,
                price_value=round(con_val / con_kg, 4), currency="USD", unit="kg", origin_iso3=agg.iso3,
                origin_label=label, market_iso3="USA", market_location="United States (all ports)",
                variety_raw="HS 0409 natural honey (all lines)",
                terms="US customs value / net kg (imports for consumption; excludes freight, insurance & duty), HS 0409 total",
                volume_kg=con_kg,
                notes=("Valore unitario all'importazione = valore doganale / peso netto (US Census Bureau, HS 0409, "
                       "importazioni per consumo). Dato doganale derivato, non una quotazione di mercato. "
                       "Stessi dati di USDA FAS GATS."),
                extra={"cty_code": extra["cty_code"], "same_underlying_data_as": "usda_fas_gats",
                       "overlap_note": CENSUS_OVERLAP_NOTE, "value_usd": con_val, "kg": con_kg,
                       "cif_unit_value_usd_per_kg": round(con_cif / con_kg, 4) if con_cif else None,
                       "general_unit_value_usd_per_kg": round(gen_val / gen_kg, 4) if gen_val and gen_kg else None,
                       "effective_duty_rate": extra["effective_duty_rate"]},
                **common,
            )
        else:
            ctx.retire(PriceObservation, f"{PriceType.IMPORT_UNIT_VALUE.value}|{price_series}")
        return series


def _newest_in(content: bytes) -> Month | None:
    """Newest `time` in an (unchanged) Census answer, for the state bookkeeping."""
    try:
        rows = parse_census_table(content)
    except CollectorError:
        return None
    months = [m for m in (parse_month_label(r.get("time")) for r in rows) if m]
    return max(months, key=_midx) if months else None


__all__ = [
    "CENSUS_COUNTRIES",
    "BrComexStatCollector",
    "UsCensusTradeCollector",
    "census_get_list",
    "classify_census_country",
    "comex_query_body",
    "is_comex_rate_limited",
    "map_comex_partner",
    "month_windows",
    "parse_census_imports",
    "parse_census_table",
    "parse_census_variables",
    "parse_comex_general",
    "parse_comex_names",
    "parse_comex_updated",
    "resolve_comex_spec",
    "resolve_country_name",
]
