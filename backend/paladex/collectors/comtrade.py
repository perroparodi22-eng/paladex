"""UN Comtrade: international trade in natural honey (HS 0409), from official customs statistics.

Source research: docs/research/comtrade.json. How this collector works:

* **Without an API key** it uses the free public *preview* endpoint
  (``/public/v1/preview/C/{A|M}/HS``). Each call covers one reporter, one period and one flow,
  which keeps the answer far below the endpoint's 500-row cap. Calls are spaced at least
  ``KEYLESS_MIN_INTERVAL`` seconds apart, because the preview endpoint is rate-limited and
  the research recommends about one call every 2 s.
* **With a free key** (``PALADEX_COMTRADE_API_KEY``) it uses ``/data/v1/get/C/{A|M}/HS``. One
  call carries several reporters and up to 12 periods, so the whole panel takes a handful of
  calls, against a quota of 500 calls a day. The key travels only in the
  ``Ocp-Apim-Subscription-Key`` header. It never appears in a URL, so it never reaches
  ``source_url``, the raw-document archive, warnings or logs.
* **Data availability** (``getDa``, one call per frequency) lists which reporter/periods have
  been published and when they were last released. The collector uses it to skip periods that
  are not published yet or were not re-released since we last saw them, and to fill
  ``published_at``. If ``getDa`` is unavailable, it falls back to fetching the periods it does
  not hold yet plus the most recent ones (``*_RECHECK_*``).
* **Panel** (module constants below, all configurable): imports (flow M) of the main
  destination markets from *all* partners, which gives the origin breakdown, and exports
  (flow X) of the main origins to *all* partners.
* **Stored**:
  - one ``TradeFlowObservation`` per reporter x partner x flow x period. The World total is
    stored as partner ``"WLD"``. Partner groups such as the EU are skipped so nothing is counted
    twice. Residual and special areas ("Other Europe, nes", "Areas, nes", "Bunkers", "Free
    Zones"...: ``RESIDUAL_PARTNER_AREAS``) are part of the reporter's trade: they are stored as
    partner ``"M<code>"`` with ``extra.partner_residual_area``, logged at INFO (an expected
    condition, not a warning) and never ranked as countries; a partner code that is neither a
    country nor such an area is still a warning;
  - a derived customs **unit value** (``PriceType.IMPORT_UNIT_VALUE`` /
    ``EXPORT_UNIT_VALUE``, USD/kg) per country pair. It is a customs value divided by a weight,
    never a market quotation, so it is never stored as ``WHOLESALE_BULK``. None is derived from a
    weight UN Comtrade estimated (the trade row keeps it, as an estimate): see `unit_value`.
  Revisions published by UN Comtrade become new revisions through ``services.ingest``. A series a
  fresh answer no longer supports is withdrawn (``ctx.retire``: no longer current, kept in the
  history): a unit value whose re-released trade row lost its weight, a partner the re-release no
  longer reports, or a partner code now mapped to another ISO3 (keys use the derived ISO3, so the
  stable Comtrade ``partnerCode`` decides that it is the same partner).

Response format: rows are in the top-level ``data`` array and the total is in ``count``. Field
names follow the official client and the rOpenSci *comtradr* column mapping. That mapping
lists case variants of some fields (``isNetWgtEstimated`` / ``isnetWgtEstimated``,
``cifvalue`` / ``cifValue`` / ``CIFValue``), so every field is read case-insensitively.
"""
from __future__ import annotations

import json
import logging
import math
import re
import time
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, TypeVar
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import func, select

from ..enums import DataStatus, PriceType, Reliability, SourceKind, TradeFlow, Variety
from ..models import PriceObservation, RawDocument, TradeFlowObservation
from ..reference.countries import lookup_iso3
from .base import (
    CollectContext,
    Collector,
    CollectorError,
    FetchResult,
    Offline,
    month_bounds,
    year_bounds,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Endpoints (URL templates verified against UN Comtrade's official client, comtradeapicall 1.3.2)
# ---------------------------------------------------------------------------
API_ROOT = "https://comtradeapi.un.org"
PREVIEW_URL = API_ROOT + "/public/v1/preview/C/{freq}/HS"       # keyless, at most 500 rows per call
KEYED_URL = API_ROOT + "/data/v1/get/C/{freq}/HS"               # free key, up to 100k rows per call
GETDA_PUBLIC_URL = API_ROOT + "/public/v1/getDa/C/{freq}/HS"    # data availability, keyless
GETDA_KEYED_URL = API_ROOT + "/data/v1/getDa/C/{freq}/HS"       # data availability, keyed
PARTNER_REF_URL = API_ROOT + "/files/v1/app/reference/partnerAreas.json"  # partner codes / ISO / isGroup
KEY_HEADER = "Ocp-Apim-Subscription-Key"

# HS 0409 "Natural honey" has a single 6-digit subheading (040900) carrying the same values, so we
# query the 4-digit code only and accept either code in the answer.
HS_CODE = "0409"
ACCEPTED_CMD_CODES = frozenset({"0409", "040900"})

# ---------------------------------------------------------------------------
# Panel (edit here to widen or narrow the collection)
# ---------------------------------------------------------------------------
# ISO3 -> UN Comtrade reporter code. Comtrade codes differ from ISO numeric for some countries
# (USA 842, France 251, India 699, Switzerland 757, Norway 579).
IMPORT_MARKETS: dict[str, int] = {
    "ITA": 380, "DEU": 276, "ESP": 724, "BEL": 56, "FRA": 251, "GBR": 826,
    "USA": 842, "JPN": 392, "SAU": 682, "NLD": 528, "POL": 616,
}
EXPORT_ORIGINS: dict[str, int] = {
    "ARG": 32, "CHN": 156, "UKR": 804, "SRB": 688, "BRA": 76, "VNM": 704, "IND": 699, "MEX": 484,
    "URY": 858, "TUR": 792, "HUN": 348, "ROU": 642, "CHL": 152, "NZL": 554, "CAN": 124,
    "ESP": 724, "DEU": 276,
}
ANNUAL_YEARS = 8                # annual window: the last N complete years
ANNUAL_RECHECK_YEARS = 3        # without getDa: always re-fetch the N most recent years (revisions)
MONTHLY_MONTHS_KEYED = 24       # monthly window with a key (imports and exports, whole panel)
MONTHLY_MONTHS_KEYLESS = 12     # monthly window without a key (imports of KEYLESS_MONTHLY_MARKETS only)
MONTHLY_RECHECK_MONTHS = 6      # keyless without getDa: always re-fetch the N most recent months
KEYLESS_MONTHLY_MARKETS: tuple[str, ...] = ("ITA", "DEU", "USA")

# ---------------------------------------------------------------------------
# Limits and politeness
# ---------------------------------------------------------------------------
PREVIEW_MAX_RECORDS = 500       # hard cap of the preview endpoint
KEYED_MAX_RECORDS = 100_000     # safe free-tier maximum per call
KEYED_MAX_PERIODS_PER_CALL = 12  # comtradr docs: monthly queries are limited to 12 periods
KEYED_MAX_REPORTERS_PER_CALL = 6
KEYLESS_MIN_INTERVAL = 2.0      # seconds between keyless calls (ctx.fetch alone guarantees 1.5 s)
KEYED_MIN_INTERVAL = 1.1        # free key: 1 call/s (ctx.fetch's 1.5 s already satisfies it)
QUOTA_STATUSES = (403, 429)     # APIM: 429 = rate limit, 403 = daily quota exhausted
# getDa's lastReleased may be date-only (midnight, as in the documented sample) or on another clock,
# while our last fetch time has hours. A re-release later on the day we last fetched must still count
# as newer, so the comparison allows this much slack (it costs at most a re-fetch or two: last_seen_at
# moves past it on the re-fetch).
RELEASE_SLACK = timedelta(days=1)

# Unit values are derived only for flows of at least this many kg. Tiny consignments (samples,
# retail parcels, mis-keyed weights) give extreme USD/kg values that would only add noise to the
# price series. The trade row itself is always stored.
MIN_UNIT_VALUE_KG = 1_000.0

# Partner codes that are groups of countries. Their rows would double count the country rows.
# Partner 0 (World) is a group too, but it is kept and stored as "WLD". More groups are detected
# through `isGroup` in the partner reference file when it is available.
AGGREGATE_PARTNER_CODES = frozenset({97})   # 97 = European Union

# Residual and special partner areas: not countries, not groups of countries. Their rows are part
# of the reporter's trade (they make the partners add up to the World total), so they are stored
# under partner "M{code}"; they are expected, so they are logged at INFO and never make a run
# "partial". Any partner code outside the country table stays out of country rankings (api.trade
# `is_country`). Codes and descriptions as in Comtrade's partnerAreas.json, read on 2026-11-04.
# Checked before any ISO lookup: the reference file gives 492 "Europe EU, nes" the ISO3 of Monaco.
# 490 "Other Asia, nes" is NOT here: Comtrade uses it for Taiwan (see resolve_partner).
RESIDUAL_PARTNER_AREAS: dict[int, str] = {
    129: "Caribbean, nes", 221: "Eastern Europe, nes", 290: "Northern Africa, nes", 471: "CACM, nes",
    472: "Africa CAMEU region, nes", 473: "LAIA, nes", 492: "Europe EU, nes", 527: "Oceania, nes",
    536: "Neutral Zone", 568: "Other Europe, nes", 577: "Other Africa, nes", 636: "Rest of America, nes",
    637: "North America and Central America, nes", 697: "Europe EFTA, nes", 837: "Bunkers", 838: "Free Zones",
    839: "Special Categories", 879: "Western Asia, nes", 899: "Areas, nes",
}
# The same kinds of area recognised by description, for a code not listed above.
_RESIDUAL_DESC_RE = re.compile(r"\bnes\b|\bbunkers?\b|\bfree zones?\b|\bspecial categor", re.IGNORECASE)

FLOW_BY_CODE: dict[str, str] = {"M": TradeFlow.IMPORT.value, "X": TradeFlow.EXPORT.value}
# Three-letter codes that look like ISO3 but are not countries.
_NON_COUNTRY_ISO3 = frozenset({"WLD", "EUR", "EUU", "XXX", "NES", "ZZZ"})
_ISO3_RE = re.compile(r"^[A-Z]{3}$")
_RELEASE_FIELDS = ("lastreleased", "publicationdate", "lastupdated", "firstreleased")


def _today() -> date:
    """Today's date (a function so tests can pin it)."""
    return date.today()


# ---------------------------------------------------------------------------
# Small parsing helpers (pure)
# ---------------------------------------------------------------------------


def _ci(row: dict) -> dict[str, Any]:
    """Case-insensitive view of a JSON row. Comtrade spells some fields in several ways
    (cifvalue / cifValue / CIFValue). When more than one variant is present, a non-null value
    wins over null."""
    out: dict[str, Any] = {}
    for k, v in row.items():
        lk = str(k).lower()
        if v is not None or lk not in out:
            out[lk] = v
    return out


def _first(ci: dict[str, Any], *names: str) -> Any:
    for n in names:
        v = ci.get(n)
        if v is not None and v != "":
            return v
    return None


def _num(value: Any) -> float | None:
    """Parse a numeric field. None/'' -> None; a non-numeric value raises ValueError."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise ValueError(f"boolean where a number was expected: {value!r}")
    out = float(value)
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def _flag(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    if s in ("true", "1", "yes", "y"):
        return True
    if s in ("false", "0", "no", "n"):
        return False
    return None


def _int_code(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return int(f) if f.is_integer() else None


def _str_code(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    s = str(value).strip()
    return s or None


def _clean_iso3(raw: Any) -> str | None:
    """A real ISO3 country code, or None (Comtrade uses pseudo codes like 'W00', 'S19', '_X ')."""
    if not isinstance(raw, str):
        return None
    s = raw.strip().upper()
    return s if _ISO3_RE.match(s) and s not in _NON_COUNTRY_ISO3 else None


def _lookup_country(code: int) -> str | None:
    iso = lookup_iso3(code)
    return iso if iso and len(iso) == 3 and iso != "WLD" else None


def _parse_dt(value: Any) -> datetime | None:
    """Parse a release timestamp as naive UTC (the convention of the models' DateTime columns)."""
    if value is None or value == "":
        return None
    from dateutil import parser as dparser

    try:
        dt = dparser.parse(str(value))
    except (ValueError, OverflowError):
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt


@dataclass(frozen=True)
class Period:
    freq: str        # "A" | "M"
    code: str        # as Comtrade writes it: "2025" | "202608"
    label: str       # as stored: "2025" | "2026-08"
    start: date
    end: date


def parse_period(value: Any, freq_hint: str | None = None) -> Period | None:
    """'2025' -> annual, '202608' -> monthly. None when malformed or inconsistent with freq_hint."""
    s = _str_code(value)
    if s is None:
        return None
    p: Period | None = None
    if re.fullmatch(r"\d{4}", s):
        y = int(s)
        if 1900 <= y <= 2100:
            p = Period("A", s, s, *year_bounds(y))
    elif re.fullmatch(r"\d{6}", s):
        y, m = int(s[:4]), int(s[4:])
        if 1900 <= y <= 2100 and 1 <= m <= 12:
            p = Period("M", s, f"{y}-{m:02d}", *month_bounds(y, m))
    if p is None or (freq_hint and freq_hint.upper() in ("A", "M") and p.freq != freq_hint.upper()):
        return None
    return p


def annual_periods(today: date, years: int) -> list[str]:
    """The last `years` complete years, newest first."""
    return [str(today.year - i) for i in range(1, years + 1)]


def monthly_periods(today: date, months: int) -> list[str]:
    """The `months` months before the current one, newest first (e.g. 202610, 202609, ...)."""
    out, y, m = [], today.year, today.month
    for _ in range(months):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(f"{y}{m:02d}")
    return out


def value_basis(flow_code: str, primary: float | None, cif: float | None, fob: float | None) -> str | None:
    """Which valuation `primaryValue` is in.

    Comtrade convention: imports are valued CIF and exports FOB. When `cifvalue` / `fobvalue`
    are present we check which one `primaryValue` matches, because some reporters value imports
    FOB. When both are present and neither matches, the basis is reported as 'primary' (unknown).
    """
    if primary is None:
        return None
    conventional = "CIF" if flow_code == "M" else "FOB"
    if cif is None and fob is None:
        return conventional
    candidates = (("CIF", cif), ("FOB", fob)) if flow_code == "M" else (("FOB", fob), ("CIF", cif))
    for basis, v in candidates:
        if v is not None and math.isclose(v, primary, rel_tol=1e-6, abs_tol=0.5):
            return basis
    return "primary"


def redact_url(url: str) -> str:
    """Drop any key-bearing query parameter. The collector never puts the key in a URL; this
    is a second safeguard so a key can never end up in `source_url`."""
    parts = urlsplit(url)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    kept = [(k, v) for k, v in pairs if k.lower() not in ("subscription-key", "subscription_key", "token")]
    if len(kept) == len(pairs):
        return url
    return urlunsplit(parts._replace(query=urlencode(kept, safe=",")))


# ---------------------------------------------------------------------------
# Response parsing (pure)
# ---------------------------------------------------------------------------


@dataclass
class Envelope:
    rows: list[Any]
    count: int | None
    error: str | None


def parse_envelope(content: bytes) -> Envelope:
    """Parse the JSON wrapper {"count": N, "data": [...], "error": ""}.

    Raises CollectorError when the document is unusable (not JSON, no `data` array, or an error
    message with no data).
    """
    try:
        obj = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise CollectorError(f"UN Comtrade response is not JSON ({exc.__class__.__name__})") from exc
    if not isinstance(obj, dict):
        raise CollectorError("UN Comtrade response is not a JSON object")
    error = obj.get("error") or obj.get("message")
    error = str(error).strip()[:300] if error else None
    if "data" not in obj:
        raise CollectorError(f"UN Comtrade response has no 'data' field{': ' + error if error else ''}")
    data = obj.get("data")
    if data is None:
        if error:
            raise CollectorError(f"UN Comtrade error: {error}")
        data = []
    if not isinstance(data, list):
        raise CollectorError("UN Comtrade 'data' is not a list")
    if error and not data:
        raise CollectorError(f"UN Comtrade error: {error}")
    return Envelope(rows=data, count=_int_code(obj.get("count")), error=error)


@dataclass(frozen=True)
class PartnerInfo:
    iso3: str | None
    desc: str | None
    is_group: bool


def parse_partner_reference(content: bytes) -> dict[int, PartnerInfo]:
    """partnerAreas.json -> {code: PartnerInfo}. The file may start with a UTF-8 BOM and uses
    capitalised keys (PartnerCode, PartnerCodeIsoAlpha3...), so keys are matched case-insensitively."""
    try:
        obj = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise CollectorError(f"partner reference is not JSON ({exc.__class__.__name__})") from exc
    rows = obj.get("results") if isinstance(obj, dict) else None
    if not isinstance(rows, list):
        raise CollectorError("partner reference has no 'results' list")
    out: dict[int, PartnerInfo] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        ci = _ci(r)
        code = _int_code(_first(ci, "partnercode", "id"))
        if code is None:
            continue
        if code in out and _first(ci, "entryexpireddate"):
            continue  # keep the current entry over an expired historical one
        out[code] = PartnerInfo(
            iso3=_clean_iso3(_first(ci, "partnercodeisoalpha3")),
            desc=_first(ci, "partnerdesc", "text"),
            is_group=_flag(ci.get("isgroup")) is True,
        )
    return out


def parse_availability(content: bytes) -> dict[tuple[int, str], datetime | None]:
    """getDa -> {(reporterCode, period): last release timestamp or None}."""
    env = parse_envelope(content)
    out: dict[tuple[int, str], datetime | None] = {}
    for r in env.rows:
        if not isinstance(r, dict):
            continue
        ci = _ci(r)
        code = _int_code(ci.get("reportercode"))
        period = parse_period(ci.get("period"))
        if code is None or period is None:
            continue
        released = next((d for d in (_parse_dt(ci.get(f)) for f in _RELEASE_FIELDS) if d is not None), None)
        key = (code, period.code)
        prev = out.get(key)
        if key not in out or (released is not None and (prev is None or released > prev)):
            out[key] = released
    return out


def resolve_partner(code: int, iso_raw: Any, ref: dict[int, PartnerInfo] | None) -> tuple[str | None, bool]:
    """Map a Comtrade partner to (iso3, known).

    * 0 -> ("WLD", True)
    * a group of countries (EU, ...) -> (None, True): the caller skips the row
    * otherwise: partnerISO from the row, then our own code table (which knows the Comtrade
      quirks 842, 251, 699, 757, 579 and 490 'Other Asia, nes' = Taiwan), then the reference file
    * a residual area ("Other Europe, nes", "Bunkers", ...: RESIDUAL_PARTNER_AREAS) or a code still
      unknown -> (f"M{code}", False); `is_residual_partner` tells the two apart
    """
    if code == 0:
        return "WLD", True
    info = (ref or {}).get(code)
    if code in AGGREGATE_PARTNER_CODES or (info is not None and info.is_group):
        return None, True
    if code in RESIDUAL_PARTNER_AREAS:
        return f"M{code}", False
    iso = _clean_iso3(iso_raw) or _lookup_country(code) or (info.iso3 if info else None)
    if iso:
        return iso, True
    return f"M{code}", False


def is_residual_partner(code: int, desc: Any) -> bool:
    """True for a residual or special area (not a country): a listed code, or a description such as
    "Other Africa, nes", "Bunkers", "Free Zones", "Special Categories"."""
    return code in RESIDUAL_PARTNER_AREAS or (isinstance(desc, str) and bool(_RESIDUAL_DESC_RE.search(desc)))


@dataclass
class TradeRecord:
    freq: str
    flow: str                    # TradeFlow value
    flow_code: str               # "M" | "X"
    reporter_code: int
    reporter_iso3: str
    reporter_desc: str | None
    partner_code: int
    partner_iso3: str
    partner_desc: str | None
    partner_known: bool
    period: Period
    value: float | None          # USD
    value_basis: str | None
    net_weight_kg: float | None
    weight_estimated: bool
    published_at: date | None
    extra: dict[str, Any]

    @property
    def series_key(self) -> str:
        return f"{HS_CODE}|{self.freq}|{self.flow}|{self.reporter_iso3}|{self.partner_iso3}|{self.period.code}"

    @property
    def data_status(self) -> str:
        return (DataStatus.ESTIMATE if self.weight_estimated else DataStatus.PUBLISHED).value


@dataclass
class ParseResult:
    records: list[TradeRecord] = field(default_factory=list)
    raw_count: int = 0
    reported_count: int | None = None
    malformed: list[str] = field(default_factory=list)
    unknown_partners: dict[int, str | None] = field(default_factory=dict)
    residual_partners: dict[int, str | None] = field(default_factory=dict)   # "nes" areas, bunkers...
    skipped_aggregates: int = 0
    skipped_breakdown: int = 0       # partner2 / customs procedure / transport sub-totals
    skipped_other: int = 0           # other flows (re-imports...) or other commodities
    # "flow='M' cmd=409" -> rows: the RAW values of rows rejected as another flow/commodity, so a format
    # change (a number instead of a string, a label instead of a code) shows in the warning.
    other_samples: dict[str, int] = field(default_factory=dict)
    envelope_error: str | None = None
    # Which partners the answer carries, whatever became of their rows (kept, sub-total, malformed...):
    # (reporterCode, period code) -> partnerCodes. store() uses it to tell a partner the source no longer
    # reports from one we merely could not read. `unplaced` counts rows that could not be placed at all.
    answered: dict[tuple[int, str], set[int]] = field(default_factory=dict)
    unplaced: int = 0
    group_partners: set[tuple[int, str, int]] = field(default_factory=set)  # (reporter, period, partner) skipped as groups


def _is_total(value: Any, total: str) -> bool:
    s = _str_code(value)
    return s is None or s.upper() == total


def _row_to_record(row: Any, ref: dict[int, PartnerInfo] | None, res: ParseResult, idx: int) -> TradeRecord | None:
    if not isinstance(row, dict):
        res.malformed.append(f"row {idx}: not a JSON object")
        res.unplaced += 1
        return None
    ci = _ci(row)
    where = f"row {idx} (reporter {ci.get('reportercode')}, partner {ci.get('partnercode')}, period {ci.get('period')})"

    freq_hint = _str_code(ci.get("freqcode"))
    raw_period = ci.get("period")
    if raw_period in (None, "") and ci.get("refyear") is not None:
        ref_year, ref_month = _int_code(ci.get("refyear")), _int_code(ci.get("refmonth"))
        if (freq_hint or "").upper() == "M" and ref_year and ref_month and 1 <= ref_month <= 12:
            raw_period = f"{ref_year}{ref_month:02d}"
        elif (freq_hint or "").upper() == "A" and ref_year:
            raw_period = str(ref_year)
    period = parse_period(raw_period, freq_hint)
    reporter_code = _int_code(ci.get("reportercode"))
    partner_code = _int_code(ci.get("partnercode"))
    if period is None or reporter_code is None or partner_code is None:
        res.unplaced += 1
    else:
        res.answered.setdefault((reporter_code, period.code), set()).add(partner_code)

    flow_code = (_str_code(ci.get("flowcode")) or "").upper()
    cmd = _str_code(ci.get("cmdcode"))
    if flow_code not in FLOW_BY_CODE or (cmd is not None and cmd not in ACCEPTED_CMD_CODES):
        res.skipped_other += 1
        sample = f"flow={ci.get('flowcode')!r} cmd={ci.get('cmdcode')!r}"
        res.other_samples[sample] = res.other_samples.get(sample, 0) + 1
        return None
    # We ask for totals only (partner2Code=0, customsCode=C00, motCode=0). Sub-total rows would
    # duplicate the same series key, so they are never stored.
    if not (_is_total(ci.get("partner2code"), "0") and _is_total(ci.get("customscode"), "C00")
            and _is_total(ci.get("motcode"), "0")):
        res.skipped_breakdown += 1
        return None

    if period is None:
        res.malformed.append(f"{where}: missing or invalid period {raw_period!r}")
        return None
    if reporter_code is None or partner_code is None:
        res.malformed.append(f"{where}: missing reporter or partner code")
        return None
    reporter_iso3 = _clean_iso3(ci.get("reporteriso")) or _lookup_country(reporter_code)
    if reporter_iso3 is None:
        res.malformed.append(f"{where}: unknown reporter code {reporter_code}")
        return None
    partner_iso3, known = resolve_partner(partner_code, ci.get("partneriso"), ref)
    if partner_iso3 is None:
        res.skipped_aggregates += 1
        res.group_partners.add((reporter_code, period.code, partner_code))
        return None
    ref_info = (ref or {}).get(partner_code)
    partner_desc = _first(ci, "partnerdesc") or (ref_info.desc if ref_info else None)
    residual = not known and is_residual_partner(partner_code, partner_desc)
    if residual:
        partner_desc = partner_desc or RESIDUAL_PARTNER_AREAS.get(partner_code)
        res.residual_partners.setdefault(partner_code, partner_desc)
    elif not known:
        res.unknown_partners.setdefault(partner_code, partner_desc)

    try:
        primary = _num(ci.get("primaryvalue"))
        cif = _num(ci.get("cifvalue"))
        fob = _num(ci.get("fobvalue"))
        net_raw = _num(ci.get("netwgt"))
        qty = _num(ci.get("qty"))
    except (TypeError, ValueError) as exc:
        res.malformed.append(f"{where}: non-numeric value ({exc})")
        return None
    if any(v is not None and v < 0 for v in (primary, net_raw)):
        res.malformed.append(f"{where}: negative value or weight")
        return None
    # Comtrade writes 0 or null when the weight was not reported. A shipment worth money cannot
    # weigh 0 kg, so 0 is treated as "not available" (the raw value is kept in `extra`).
    net_kg = net_raw if net_raw else None
    if primary is None and net_kg is None:
        res.malformed.append(f"{where}: neither value nor net weight given")
        return None

    weight_est = _flag(ci.get("isnetwgtestimated")) is True
    extra: dict[str, Any] = {
        "reporter_code": reporter_code,
        "partner_code": partner_code,
        "partner_desc": partner_desc,
        "cmd_code": cmd,
        "classification": _first(ci, "classificationcode"),
        "cifvalue": cif,
        "fobvalue": fob,
        "net_wgt_raw": net_raw,
        "qty": qty,
        "qty_unit_code": _int_code(ci.get("qtyunitcode")),
        "is_net_wgt_estimated": _flag(ci.get("isnetwgtestimated")),
        "is_qty_estimated": _flag(ci.get("isqtyestimated")),
        "is_reported": _flag(ci.get("isreported")),
        "is_aggregate": _flag(ci.get("isaggregate")),
        "legacy_estimation_flag": _first(ci, "legacyestimationflag"),
        "partner_unmapped": None if known else True,
        "partner_residual_area": True if residual else None,     # not a country: never ranked as one
    }
    released = next((d for d in (_parse_dt(ci.get(f)) for f in _RELEASE_FIELDS) if d is not None), None)
    return TradeRecord(
        freq=period.freq,
        flow=FLOW_BY_CODE[flow_code],
        flow_code=flow_code,
        reporter_code=reporter_code,
        reporter_iso3=reporter_iso3,
        reporter_desc=_first(ci, "reporterdesc"),
        partner_code=partner_code,
        partner_iso3=partner_iso3,
        partner_desc=partner_desc,
        partner_known=known,
        period=period,
        value=primary,
        value_basis=value_basis(flow_code, primary, cif, fob),
        net_weight_kg=net_kg,
        weight_estimated=weight_est,
        published_at=released.date() if released else None,
        extra={k: v for k, v in extra.items() if v is not None},
    )


def parse_records(content: bytes, partner_ref: dict[int, PartnerInfo] | None = None) -> ParseResult:
    """Parse one data response into TradeRecords. A malformed row is reported in `malformed` and
    skipped; an unusable document raises CollectorError."""
    env = parse_envelope(content)
    res = ParseResult(raw_count=len(env.rows), reported_count=env.count, envelope_error=env.error)
    seen: set[str] = set()
    for i, row in enumerate(env.rows):
        rec = _row_to_record(row, partner_ref, res, i)
        if rec is None:
            continue
        if rec.series_key in seen:
            res.malformed.append(f"row {i}: duplicate row for {rec.series_key}; first one kept")
            continue
        seen.add(rec.series_key)
        res.records.append(rec)
    return res


def unit_value(rec: TradeRecord) -> float | None:
    """Customs unit value in USD/kg for one country pair, or None when it must not be derived:
    the World total, an unmapped partner, a re-import from itself, a missing value or weight, a
    flow under MIN_UNIT_VALUE_KG, or a net weight that UN Comtrade estimated (``isNetWgtEstimated``).
    An estimated weight is imputed from the value with a standard unit value, so value / weight only
    gives back that factor (2.9459 USD/kg for every partner of the US in Aug 2026): never a price."""
    if rec.partner_iso3 == "WLD" or not rec.partner_known or rec.partner_iso3 == rec.reporter_iso3:
        return None
    if rec.weight_estimated:
        return None
    if not rec.value or not rec.net_weight_kg or rec.net_weight_kg < MIN_UNIT_VALUE_KG:
        return None
    return round(rec.value / rec.net_weight_kg, 4)


def no_unit_value_reason(rec: TradeRecord) -> str:
    """Why `unit_value(rec)` is None, in words (for the warning when an earlier unit value is withdrawn)."""
    if not rec.partner_known:
        return "partner not mapped to a country"
    if rec.weight_estimated:
        return "net weight estimated by UN Comtrade"
    if not rec.value:
        return "value not reported"
    if not rec.net_weight_kg:
        return "net weight not reported"
    if rec.net_weight_kg < MIN_UNIT_VALUE_KG:
        return f"net weight {rec.net_weight_kg:,.0f} kg < {MIN_UNIT_VALUE_KG:,.0f} kg"
    return "no unit value derivable"


def unit_value_price_type(flow_code: str) -> PriceType:
    return PriceType.IMPORT_UNIT_VALUE if flow_code == "M" else PriceType.EXPORT_UNIT_VALUE


def unit_value_series(freq: str, reporter_iso3: str, partner_iso3: str, period_code: str) -> str:
    """Series key of the unit value derived from one trade row, as passed to `ctx.add_price`."""
    return f"{HS_CODE}|{freq}|{reporter_iso3}|{partner_iso3}|{period_code}"


def stored_unit_value_key(flow_code: str, freq: str, reporter_iso3: str, partner_iso3: str, period_code: str) -> str:
    """The same key as stored: `ctx.add_price` prefixes the price type, which carries the flow."""
    return f"{unit_value_price_type(flow_code).value}|{unit_value_series(freq, reporter_iso3, partner_iso3, period_code)}"


T = TypeVar("T")


def _chunks(items: list[T], size: int) -> Iterable[list[T]]:
    for i in range(0, len(items), max(1, size)):
        yield items[i:i + size]


def plan_batches(
    needed: dict[str, set[T]], max_reporters: int, max_periods: int
) -> list[tuple[tuple[T, ...], tuple[str, ...]]]:
    """Group {period: {reporters}} into keyed API calls of (reporters, periods).

    Periods that need the same set of reporters share calls, so a call never asks for a
    reporter/period pair that is not needed. The result is deterministic (sorted).
    """
    by_reporters: dict[frozenset, list[str]] = defaultdict(list)
    for period, reporters in needed.items():
        if reporters:
            by_reporters[frozenset(reporters)].append(period)
    out: list[tuple[tuple[T, ...], tuple[str, ...]]] = []
    for reporters, periods in sorted(by_reporters.items(), key=lambda kv: (sorted(kv[0]), sorted(kv[1]))):
        for pchunk in _chunks(sorted(periods), max_periods):
            for rchunk in _chunks(sorted(reporters), max_reporters):
                out.append((tuple(rchunk), tuple(pchunk)))
    return out


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


class _KeyRejected(Exception):
    """HTTP 401 on a keyed call: the configured key is invalid or not subscribed."""


class _QuotaReached(Exception):
    """HTTP 403/429 after ctx.fetch's own retries: stop politely and keep what we have."""


@dataclass
class _Segment:
    freq: str                        # "A" | "M"
    flow_code: str                   # "M" | "X"
    reporters: dict[str, int]        # iso3 -> Comtrade code
    periods: list[str]               # newest first
    recheck: set[str]                # periods re-fetched even if held (when getDa is unavailable)


class _ComtradeRun:
    """State for one collection run (the Collector instance itself is shared and stateless)."""

    def __init__(self, ctx: CollectContext, api_key: str | None, *,
                 partner_ref: dict[int, PartnerInfo] | None = None, warned_partners: set[int] | None = None):
        self.ctx = ctx
        self.api_key = api_key
        self.keyed = bool(api_key)
        self.headers = {"Accept": "application/json"}
        if api_key:
            self.headers[KEY_HEADER] = api_key
        self.today = _today()
        self._partner_ref = partner_ref
        self.warned_partners: set[int] = warned_partners if warned_partners is not None else set()
        self._warned_breakdown = False
        self._warned_other = False
        self._last_call: float | None = None
        self.availability: dict[str, dict[tuple[int, str], datetime | None] | None] = {}
        self.ok_calls = 0
        self.failed_calls = 0
        self.last_error: str | None = None

    # ----------------------------------------------------------------- plan
    def segments(self) -> list[_Segment]:
        annual = annual_periods(self.today, ANNUAL_YEARS)
        monthly = monthly_periods(self.today, MONTHLY_MONTHS_KEYED if self.keyed else MONTHLY_MONTHS_KEYLESS)

        def recheck(periods: list[str], n: int) -> set[str]:
            # With a key, re-pulling the whole window costs only a few calls, so do it.
            return set(periods) if self.keyed else set(periods[:n])

        segs = [
            _Segment("A", "M", dict(IMPORT_MARKETS), annual, recheck(annual, ANNUAL_RECHECK_YEARS)),
            _Segment("A", "X", dict(EXPORT_ORIGINS), annual, recheck(annual, ANNUAL_RECHECK_YEARS)),
        ]
        if self.keyed:
            segs.append(_Segment("M", "M", dict(IMPORT_MARKETS), monthly, recheck(monthly, MONTHLY_RECHECK_MONTHS)))
            segs.append(_Segment("M", "X", dict(EXPORT_ORIGINS), monthly, recheck(monthly, MONTHLY_RECHECK_MONTHS)))
        else:
            markets = {iso: IMPORT_MARKETS[iso] for iso in KEYLESS_MONTHLY_MARKETS if iso in IMPORT_MARKETS}
            segs.append(_Segment("M", "M", markets, monthly, recheck(monthly, MONTHLY_RECHECK_MONTHS)))
        return [s for s in segs if s.reporters and s.periods]

    def held(self) -> dict[tuple[str, str, str, str], datetime]:
        """(reporter, flow, freq, period_label) -> when we last saw that data (max last_seen_at)."""
        t = TradeFlowObservation
        rows = self.ctx.session.execute(
            select(t.reporter_iso3, t.flow, t.frequency, t.period_label, func.max(t.last_seen_at))
            .where(t.source_id == self.ctx.source.id, t.is_current.is_(True), t.is_demo.is_(False))
            .group_by(t.reporter_iso3, t.flow, t.frequency, t.period_label)
        ).all()
        return {(r, f, fr, pl): ts for r, f, fr, pl, ts in rows}

    def needed_periods(self, seg: _Segment, held: dict) -> list[tuple[str, int, list[str]]]:
        avail = self.availability.get(seg.freq)
        flow = FLOW_BY_CODE[seg.flow_code]
        out = []
        for iso3, code in seg.reporters.items():
            periods = []
            for p in seg.periods:
                seen = held.get((iso3, flow, seg.freq, parse_period(p).label))
                if self.ctx.force:
                    need = True
                elif avail is not None:
                    if (code, p) not in avail:
                        continue            # not published by this reporter yet
                    released = avail[(code, p)]
                    if released is None:    # published, release time unknown
                        need = seen is None or p in seg.recheck
                    else:                   # new, or re-released since we last saw it (RELEASE_SLACK:
                        # a date-only lastReleased later on the day of our last fetch is still newer)
                        need = seen is None or released + RELEASE_SLACK > seen
                else:
                    need = seen is None or p in seg.recheck
                if need:
                    periods.append(p)
            out.append((iso3, code, periods))
        return out

    # -------------------------------------------------------------- execute
    def execute(self) -> None:
        segs = self.segments()
        for freq in ("A", "M"):
            fsegs = [s for s in segs if s.freq == freq]
            if fsegs:
                codes = sorted({c for s in fsegs for c in s.reporters.values()})
                periods = sorted({p for s in fsegs for p in s.periods})
                self.availability[freq] = self.load_availability(freq, codes, periods)
        held = self.held()
        for seg in segs:
            needed = self.needed_periods(seg, held)
            if self.keyed:
                by_period: dict[str, set[tuple[str, int]]] = defaultdict(set)
                for iso3, code, periods in needed:
                    for p in periods:
                        by_period[p].add((iso3, code))
                batches = plan_batches(by_period, KEYED_MAX_REPORTERS_PER_CALL, KEYED_MAX_PERIODS_PER_CALL)
                for reporters, periods in batches:
                    self.fetch_and_store(seg.freq, seg.flow_code, list(reporters), list(periods))
                    self.ctx.checkpoint()
            else:
                for iso3, code, periods in needed:
                    for p in periods:
                        self.fetch_and_store(seg.freq, seg.flow_code, [(iso3, code)], [p])
                    if periods:
                        self.ctx.checkpoint()   # one reporter done: keep it even if a later call fails

    # ----------------------------------------------------------------- http
    def _pace(self) -> None:
        interval = KEYED_MIN_INTERVAL if self.keyed else KEYLESS_MIN_INTERVAL
        if self._last_call is not None:
            wait = interval - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)

    def _redact(self, text: str) -> str:
        return text.replace(self.api_key, "***") if self.api_key else text

    def request(self, url: str, *, title: str, headers: dict | None = None) -> FetchResult:
        """GET through ctx.fetch (which also retries 429/5xx). Raises _KeyRejected or _QuotaReached
        for 401/403/429 answers, and CollectorError / Offline as ctx.fetch does."""
        self._pace()
        try:
            doc = self.ctx.fetch(url, headers=self.headers if headers is None else headers, title=title,
                                 accept_status=(200, 401, *QUOTA_STATUSES))
        finally:
            self._last_call = time.monotonic()
        if doc.status_code == 200:
            return doc
        if doc.status_code == 401 and self.keyed:
            raise _KeyRejected()
        snippet = self._redact(" ".join(doc.text.split()))[:160]
        raise _QuotaReached(
            f"UN Comtrade refused further requests (HTTP {doc.status_code}{': ' + snippet if snippet else ''}). "
            "Stopped early: data collected so far is kept, the remaining periods will be fetched on the next run."
        )

    def partner_ref(self) -> dict[int, PartnerInfo]:
        """Partner reference table, loaded once per run on first use. It enriches the mapping (ISO3
        for partners missing from our country table, `isGroup`). The mapping decides the series keys,
        so it must not flip between runs: when the file cannot be fetched, the last archived copy is
        used; only when there is none does the run continue without it, with a warning."""
        if self._partner_ref is None:
            self._partner_ref = {}
            try:
                doc = self.request(PARTNER_REF_URL, title="UN Comtrade partner areas (reference)", headers={})
                self._partner_ref = parse_partner_reference(doc.content)
            except Offline:
                raise
            except (CollectorError, _QuotaReached, _KeyRejected) as exc:
                reason = self._redact(str(exc))[:160]
                archived = self._archived_partner_ref()
                if archived is not None:
                    self._partner_ref, fetched_at = archived
                    log.info("[%s] partner reference unavailable (%s); using the copy archived on %s",
                             self.ctx.source.key, reason, fetched_at)
                else:
                    self.ctx.warn(f"UN Comtrade partner reference (partnerAreas.json) unavailable and never archived "
                                  f"({reason}): partners without an ISO code in the answer are stored under their "
                                  "Comtrade code (M###) this run, and only known groups of countries are skipped")
        return self._partner_ref

    def _archived_partner_ref(self) -> tuple[dict[int, PartnerInfo], datetime] | None:
        """The most recent archived partnerAreas.json that still parses (refused answers are archived
        under the same URL too, so a few are tried, newest first)."""
        ctx = self.ctx
        docs = ctx.session.scalars(
            select(RawDocument).where(RawDocument.source_id == ctx.source.id, RawDocument.url == PARTNER_REF_URL)
            .order_by(RawDocument.fetched_at.desc(), RawDocument.id.desc()).limit(5)
        ).all()
        for d in docs:
            try:
                ref = parse_partner_reference((ctx.settings.raw_dir / d.path).read_bytes())
            except (OSError, CollectorError):
                continue
            if ref:
                return ref, d.fetched_at
        return None

    def load_availability(self, freq: str, codes: list[int], periods: list[str]) -> dict | None:
        """One getDa call per frequency. Returns None when the answer is missing or unusable, in
        which case the caller falls back to "fetch what is missing plus recent periods"."""
        base = (GETDA_KEYED_URL if self.keyed else GETDA_PUBLIC_URL).format(freq=freq)
        query = urlencode({"reporterCode": ",".join(str(c) for c in codes), "period": ",".join(periods)}, safe=",")
        try:
            doc = self.request(f"{base}?{query}", title=f"UN Comtrade data availability ({freq})")
            avail = parse_availability(doc.content)
        except Offline:
            raise
        except CollectorError as exc:
            log.info("[%s] getDa %s unavailable, falling back: %s", self.ctx.source.key, freq, exc)
            return None
        # An empty answer is not trusted (it would silently skip everything); fall back instead.
        return avail or None

    def data_url(self, freq: str, flow_code: str, codes: list[int], periods: list[str]) -> str:
        params = {
            "reporterCode": ",".join(str(c) for c in codes),
            "period": ",".join(periods),
            "cmdCode": HS_CODE,
            "flowCode": flow_code,
            # No partnerCode: all partners, including World (0).
            "partner2Code": "0",
            "customsCode": "C00",
            "motCode": "0",
            "maxRecords": str(KEYED_MAX_RECORDS if self.keyed else PREVIEW_MAX_RECORDS),
            "format": "JSON",
            "breakdownMode": "classic",
            "includeDesc": "true",
        }
        base = (KEYED_URL if self.keyed else PREVIEW_URL).format(freq=freq)
        return f"{base}?{urlencode(params, safe=',')}"

    def _fail(self, msg: str) -> None:
        self.failed_calls += 1
        self.last_error = msg
        self.ctx.warn(msg)

    def fetch_and_store(self, freq: str, flow_code: str, reporters: list[tuple[str, int]], periods: list[str]) -> None:
        label = f"{freq}/{flow_code} {'+'.join(iso for iso, _ in reporters)} {','.join(periods)}"
        ref = self.partner_ref()
        url = self.data_url(freq, flow_code, [code for _, code in reporters], periods)
        try:
            doc = self.request(url, title=f"UN Comtrade HS {HS_CODE} {label}")
        except Offline:
            raise
        except CollectorError as exc:
            self._fail(f"UN Comtrade {label}: request failed ({self._redact(str(exc))[:200]})")
            return
        # Parse even when the bytes are unchanged: it is cheap, and ingest then bumps
        # `last_seen_at`. The getDa skip logic relies on that, so a dataset re-released without
        # honey changes is not fetched again on every run.
        try:
            result = parse_records(doc.content, ref)
        except CollectorError as exc:
            self._fail(f"UN Comtrade {label}: unusable response ({exc})")
            return
        self.ok_calls += 1

        cap = KEYED_MAX_RECORDS if self.keyed else PREVIEW_MAX_RECORDS
        truncated = result.raw_count >= cap or (result.reported_count or 0) > result.raw_count
        if truncated:
            if self.keyed and len(reporters) > 1:
                half = len(reporters) // 2
                self.fetch_and_store(freq, flow_code, reporters[:half], periods)
                self.fetch_and_store(freq, flow_code, reporters[half:], periods)
                return
            if self.keyed and len(periods) > 1:
                half = len(periods) // 2
                self.fetch_and_store(freq, flow_code, reporters, periods[:half])
                self.fetch_and_store(freq, flow_code, reporters, periods[half:])
                return
            self.ctx.warn(f"UN Comtrade {label}: answer reached the {cap}-row cap and may be incomplete; "
                          "rows received are stored, partner coverage may be partial")
        self.store(result, doc, label, complete=not truncated)

    # ---------------------------------------------------------------- store
    def store(self, result: ParseResult, doc: FetchResult, label: str, *, complete: bool = True) -> None:
        """Store one answer. `complete` is False when it hit the row cap (some partners may be missing)."""
        ctx = self.ctx
        for msg in result.malformed[:10]:
            ctx.warn(f"UN Comtrade {label}: {msg}")
        if len(result.malformed) > 10:
            ctx.warn(f"UN Comtrade {label}: {len(result.malformed) - 10} more malformed rows skipped")
        if result.envelope_error:
            ctx.warn(f"UN Comtrade {label}: API message alongside data: {result.envelope_error}")
        for code, desc in sorted(result.residual_partners.items()):
            if code not in self.warned_partners:
                self.warned_partners.add(code)
                log.info("[%s] UN Comtrade partner %s (%s) is a residual area, not a country; stored as partner "
                         "'M%s' (kept out of country rankings)", ctx.source.key, code, desc or "no description", code)
        for code, desc in sorted(result.unknown_partners.items()):
            if code not in self.warned_partners:
                self.warned_partners.add(code)
                ctx.warn(f"UN Comtrade partner code {code} ({desc or 'no description'}) is not a known "
                         f"country; stored as partner 'M{code}'")
        if result.skipped_breakdown and not self._warned_breakdown:
            self._warned_breakdown = True
            ctx.warn(f"UN Comtrade {label}: {result.skipped_breakdown} sub-total rows (partner2/customs/"
                     "transport breakdown) were returned despite the filters and skipped")
        # The request pins cmdCode and flowCode, so a row of another flow/commodity is unexpected: if
        # every row is rejected that way, the format has most likely changed (409 instead of "0409",
        # "Import" instead of "M") and the run must not look healthy while no trade data arrives.
        sample = "; ".join(list(result.other_samples)[:3]) or "none"
        if result.raw_count and not result.records and not result.malformed and not result.skipped_breakdown:
            ctx.warn(f"UN Comtrade {label}: {result.raw_count} rows received but none kept (other flow/commodity: "
                     f"{result.skipped_other}, group partners: {result.skipped_aggregates}; e.g. {sample}); "
                     "response format may have changed")
        elif result.skipped_other and not self._warned_other:
            self._warned_other = True
            ctx.warn(f"UN Comtrade {label}: {result.skipped_other} rows of another flow or commodity were returned "
                     f"despite the filters and skipped (e.g. {sample})")
        if result.skipped_aggregates:
            log.debug("[%s] %s: skipped %d group-partner rows", ctx.source.key, label, result.skipped_aggregates)

        source_url = redact_url(doc.url)
        avail = self.availability.get
        no_uv: dict[str, TradeRecord] = {}       # unit-value key -> record that no longer supports one
        for rec in result.records:
            released = (avail(rec.freq) or {}).get((rec.reporter_code, rec.period.code))
            published = rec.published_at or (released.date() if released else None)
            common = dict(
                source_url=source_url, published_at=published, raw_document_id=doc.raw_document_id or None,
                data_status=rec.data_status,
            )
            p = rec.period
            ctx.add_trade(
                series_key=rec.series_key, reporter_iso3=rec.reporter_iso3, partner_iso3=rec.partner_iso3,
                flow=rec.flow, currency="USD", period_start=p.start, period_end=p.end, period_label=p.label,
                frequency=rec.freq, net_weight_kg=rec.net_weight_kg, value=rec.value, hs_code=HS_CODE,
                value_basis=rec.value_basis, extra=rec.extra, **common,
            )
            uv = unit_value(rec)
            if uv is None:
                if rec.partner_iso3 != "WLD":     # the World total never has a unit value
                    no_uv[stored_unit_value_key(rec.flow_code, rec.freq, rec.reporter_iso3, rec.partner_iso3,
                                                p.code)] = rec
                continue
            is_import = rec.flow_code == "M"
            # imports: the partner is the origin and the reporter the market; exports: the reverse
            origin, market = rec.partner_iso3, rec.reporter_iso3
            if not is_import:
                origin, market = market, origin
            origin_label = (rec.partner_desc if is_import else rec.reporter_desc) or origin
            ctx.add_price(
                series_key=unit_value_series(rec.freq, rec.reporter_iso3, rec.partner_iso3, p.code),
                price_type=unit_value_price_type(rec.flow_code),
                variety=Variety.UNSPECIFIED.value, variety_raw="HS 0409 natural honey (all floral types)",
                price_value=uv, currency="USD", unit="kg",
                period_start=p.start, period_end=p.end, period_label=p.label, frequency=rec.freq,
                origin_iso3=origin, origin_label=str(origin_label)[:120], market_iso3=market,
                terms=f"{rec.value_basis or 'customs'} customs value / net weight",
                volume_kg=rec.net_weight_kg,
                notes=("Derived customs unit value (UN Comtrade, reporter side): value / net weight. "
                       "Not a market quotation."),
                extra={"trade_series_key": rec.series_key, "flow": rec.flow, "reporter_iso3": rec.reporter_iso3,
                       "partner_iso3": rec.partner_iso3, "value_usd": rec.value, "net_weight_kg": rec.net_weight_kg},
                **common,
            )
        self.retire_unit_values(no_uv, label)
        self.retire_withdrawn(result, label, complete=complete)

    def retire_unit_values(self, no_uv: dict[str, TradeRecord], label: str) -> None:
        """A re-released trade row that no longer supports a unit value (weight now missing or under
        MIN_UNIT_VALUE_KG, partner unmapped...) must not leave the earlier unit value standing as the
        latest published price next to a trade row that contradicts it."""
        if not no_uv:
            return
        ctx, po = self.ctx, PriceObservation
        held: set[str] = set()
        for chunk in _chunks(list(no_uv), 500):
            held.update(ctx.session.scalars(select(po.series_key).where(
                po.source_id == ctx.source.id, po.is_current.is_(True), po.is_demo.is_(False),
                po.series_key.in_(chunk))).all())
        withdrawn = [f"{rec.partner_iso3} {rec.period.label} ({no_unit_value_reason(rec)})"
                     for key, rec in no_uv.items() if key in held and ctx.retire(po, key)]
        if withdrawn:
            more = f" and {len(withdrawn) - 8} more" if len(withdrawn) > 8 else ""
            ctx.warn(f"UN Comtrade {label}: earlier unit value withdrawn for {len(withdrawn)} partner(s) whose "
                     f"re-released figures no longer support one: {', '.join(withdrawn[:8])}{more}")

    def retire_withdrawn(self, result: ParseResult, label: str, *, complete: bool) -> None:
        """Withdraw stored series that a fresh answer no longer supports, so they do not stay current
        next to the figures that replace them:

        * the same Comtrade partner code (stable, unlike the ISO3 derived from it) now arrives under
          another key, e.g. 'M894' -> 'ZMB' once the partner reference loads, or is now classed as a
          group of countries: the old series would count that partner twice;
        * when the answer is complete (under the row cap, every row placed): a partner the source no
          longer reports for that reporter and period (reallocated or withdrawn). A partner whose row
          is only unreadable or a sub-total is still in `answered`, so it is never withdrawn.

        Only reporter/period pairs with rows in this answer are considered, so an empty answer
        withdraws nothing. A withdrawn trade row takes its unit value with it."""
        if not result.records:
            return
        ctx, t = self.ctx, TradeFlowObservation
        flow_code, freq = result.records[0].flow_code, result.records[0].freq
        received: dict[tuple[str, str], dict[str, TradeRecord]] = defaultdict(dict)  # (reporter, period) -> key -> rec
        for rec in result.records:
            received[(rec.reporter_iso3, rec.period.label)][rec.series_key] = rec
        stored = ctx.session.scalars(select(t).where(
            t.source_id == ctx.source.id, t.is_current.is_(True), t.is_demo.is_(False),
            t.flow == FLOW_BY_CODE[flow_code], t.frequency == freq,
            t.reporter_iso3.in_(sorted({r for r, _ in received})),
            t.period_label.in_(sorted({pl for _, pl in received})),
        ).order_by(t.id)).all()
        may_drop = complete and result.unplaced == 0
        remapped: list[str] = []
        dropped: list[str] = []
        for row in stored:
            group = received.get((row.reporter_iso3, row.period_label))
            if group is None or row.series_key in group:
                continue
            sample = next(iter(group.values()))
            reporter_code, period_code = sample.reporter_code, sample.period.code
            code = (row.extra or {}).get("partner_code")
            now = next((r.partner_iso3 for r in group.values() if r.partner_code == code), None)
            if now is None and (reporter_code, period_code, code) in result.group_partners:
                now = "group of countries, not stored"
            if now is not None:
                remapped.append(f"partner {code} {row.period_label}: {row.partner_iso3} -> {now}")
            elif may_drop and code not in result.answered.get((reporter_code, period_code), set()):
                dropped.append(f"{row.partner_iso3} {row.period_label}")
            else:
                continue
            ctx.retire(t, row.series_key)
            ctx.retire(PriceObservation,
                       stored_unit_value_key(flow_code, freq, row.reporter_iso3, row.partner_iso3, period_code))
        if remapped:
            more = f" and {len(remapped) - 6} more" if len(remapped) > 6 else ""
            ctx.warn(f"UN Comtrade {label}: {len(remapped)} series withdrawn because their Comtrade partner code now "
                     f"maps differently (left current, they would count the partner twice): "
                     f"{', '.join(remapped[:6])}{more}")
        if dropped:
            more = f" and {len(dropped) - 8} more" if len(dropped) > 8 else ""
            ctx.warn(f"UN Comtrade {label}: {len(dropped)} partner series no longer in the source's answer were "
                     f"withdrawn with their unit values (earlier values stay in the history): "
                     f"{', '.join(dropped[:8])}{more}")


def retire_estimated_unit_values(ctx: CollectContext) -> int:
    """Unit values stored before `unit_value` refused estimated weights (their only `estimate` price
    rows: `TradeRecord.data_status`) are withdrawn once: no longer current, kept in the history. A
    period the source does not re-release would otherwise keep them current indefinitely."""
    po = PriceObservation
    keys = ctx.session.scalars(select(po.series_key).where(
        po.source_id == ctx.source.id, po.is_current.is_(True), po.is_demo.is_(False),
        po.data_status == DataStatus.ESTIMATE.value)).all()
    n = sum(1 for key in keys if ctx.retire(po, key))
    if n:
        ctx.warn(f"UN Comtrade: {n} earlier unit value(s) derived from net weights that UN Comtrade estimated were "
                 "withdrawn (kept in the history): an estimated weight gives back Comtrade's estimation factor, "
                 "not a price")
        ctx.checkpoint()
    return n


class ComtradeCollector(Collector):
    key = "un_comtrade"
    name = "UN Comtrade — commercio internazionale di miele (HS 0409)"
    name_en = "UN Comtrade — international honey trade (HS 0409)"
    publisher = "United Nations Statistics Division (UN Comtrade)"
    homepage = "https://comtradeplus.un.org/"
    kind = SourceKind.API
    reliability = Reliability.OFFICIAL
    category = "trade"
    language = "en"
    # Source.expected_update is String(120)
    expected_update = "Continuo, per paese: annuali 6–12+ mesi dopo la fine dell'anno; mensili 2–4 mesi dopo (UE/USA)"
    expected_update_en = "Rolling, per country: annual 6–12+ months after year end; monthly 2–4 months later (EU/US)"
    expected_max_age_days = 120
    terms_note = ("Source: UN Comtrade (© United Nations). Internal analysis is allowed; re-publishing the raw "
                  "data outside the company needs a Premium Pro subscription (small extracts up to 100,000 records "
                  "and free public visualisations excepted). Free key: 500 calls/day; keyless preview: 500 rows/call.")
    requires_key = "comtrade_api_key"
    key_optional = True                 # the keyless public preview still covers the core panel
    schedule = {"trigger": "cron", "day_of_week": "sun", "hour": 5, "minute": 40}   # weekly
    order = 60

    def collect(self, ctx: CollectContext) -> None:
        retire_estimated_unit_values(ctx)
        api_key = (self.key_value(ctx.settings) or "").strip() or None
        run = _ComtradeRun(ctx, api_key)
        try:
            try:
                run.execute()
            except _KeyRejected:
                ctx.warn("UN Comtrade rejected the configured API key (HTTP 401). Check PALADEX_COMTRADE_API_KEY; "
                         "this run falls back to the keyless public preview.")
                keyless = _ComtradeRun(ctx, None, partner_ref=run._partner_ref, warned_partners=run.warned_partners)
                keyless.ok_calls, keyless.failed_calls = run.ok_calls, run.failed_calls
                run = keyless
                run.execute()
        except _QuotaReached as stop:
            ctx.warn(str(stop))
            return
        if run.ok_calls == 0 and run.failed_calls > 0:
            raise CollectorError(f"All {run.failed_calls} UN Comtrade requests failed; last: {run.last_error}")
