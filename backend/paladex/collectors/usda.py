"""USDA honey data: AMS National Honey Report, FAS GATS (Census imports), NASS Quick Stats.

Three independent collectors share this module because they share USDA-specific helpers.
Endpoints, field names and the confidence of every detail are documented in
``docs/research/usda.json``. Parsers are pure functions so tests can call them directly.

``usda_honey_report``: AMS Market News *National Honey Report* (FVMHONEY, monthly PDF)
    * The keyless ESMIS API (USDA National Agricultural Library) lists releases. Each one
      becomes a `Report`, and the newest ``HONEY_BACKFILL_RELEASES`` PDFs are downloaded
      once and parsed.
    * The AMS "latest issue" URL is fetched on every run, because ESMIS may lag. Its file is
      overwritten each month, so every download is archived by hash. If ESMIS is down, this
      is the fallback.
    * The parser is versioned (``PARSER_VERSION``) and works on text lines, not on fixed
      column positions, so it survives the Jan-2025 layout change. That change dropped the
      narratives and switched prices from cents to dollars. Price types are kept apart:
        - prices paid to US beekeepers           -> PriceType.PRODUCER (market USA, by state)
        - prices paid to Canadian beekeepers     -> PriceType.PRODUCER (market CAN)
        - prices paid to importers, by origin    -> PriceType.WHOLESALE_BULK (market USA)
        - CBP/ACE import tables (kg, value)      -> PriceType.IMPORT_UNIT_VALUE (USD/kg)
      Prices are stored as published, in USD per lb; `add_price` also derives per kg.
      An unknown section or row produces a warning and is skipped; the parser never guesses.

``usda_fas_gats``: USDA FAS GATS ``censusImports`` (api.data.gov key, ``X-Api-Key`` header)
    * Monthly US imports of HS 0409 for the origins in ``GATS_PARTNERS``. ``dataReleaseDates``
      decides which months are new or revised. The first runs backfill about 36 months, in
      chunks per run.
    * One `TradeFlowObservation` is stored per origin and month (HS 0409 total). Value is the
      customs value of imports for consumption; the CIF figures are kept in ``extra``.
    * PriceType.IMPORT_UNIT_VALUE rows are derived per origin, both for the total and for
      each HS-10 line. Colour and organic status come from the HS-10 description.

``usda_nass_honey``: USDA NASS Quick Stats (``key=`` query parameter)
    * Annual national honey production, colonies, yield and stocks go to `ProductionStat`.
      The average price received goes to PriceType.PRODUCER (USD per lb).
"""
from __future__ import annotations

import calendar
import copy
import io
import logging
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import func, select

from ..enums import DataStatus, PriceType, Reliability, SourceKind, TradeFlow, Variety
from ..models import AppSetting, PriceObservation, ProductionStat, Report
from ..reference.countries import country_name, lookup_iso3
from ..reference.varieties import detect_color_grade, normalize_variety
from .base import (
    CollectContext,
    Collector,
    CollectorError,
    MissingKey,
    Offline,
    month_bounds,
    parse_date,
    year_bounds,
)

log = logging.getLogger(__name__)

LB_IN_KG = 0.45359237

# ---------------------------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------------------------


def _slug(text: str | None) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s or "na"


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _period_label(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def _long_date(d: date) -> str:
    return f"{calendar.month_name[d.month]} {d.day}, {d.year}"


def _state_key(source_key: str) -> str:
    return f"collector_state:{source_key}"


def _load_state(ctx: CollectContext) -> dict:
    """Small per-collector bookkeeping (e.g. which GATS releases were processed).

    Stored in `AppSetting` next to the data, so it commits and rolls back with it."""
    row = ctx.session.get(AppSetting, _state_key(ctx.source.key))
    return copy.deepcopy(row.value) if row is not None and isinstance(row.value, dict) else {}


def _save_state(ctx: CollectContext, state: dict) -> None:
    row = ctx.session.get(AppSetting, _state_key(ctx.source.key))
    if row is None:
        ctx.session.add(AppSetting(key=_state_key(ctx.source.key), value=copy.deepcopy(state)))
    else:
        row.value = copy.deepcopy(state)    # new object, so SQLAlchemy sees the JSON change
    ctx.session.flush()


def _ci_get(rec: dict, name: str) -> Any:
    """Dict lookup by exact key, then case-insensitively (APIs vary casing: hS10Code)."""
    if name in rec:
        return rec[name]
    low = name.lower()
    for k, v in rec.items():
        if isinstance(k, str) and k.lower() == low:
            return v
    return None


_COLOR_FULL = re.compile(
    r"\b(water\s+white|extra\s+white|extra\s+light\s+amber|light\s+amber|dark\s+amber|white|amber|dark)\b"
    r"(?:\s*(?:or|and|&)\s+(lighter|whiter|darker))?",
    re.I,
)
# Upper-case abbreviations used in some issues ("URUGUAY ELA 1.25-1.47"). Matched case-sensitively
# as whole tokens only ("la" is also an article in Spanish/Italian).
_COLOR_ABBR = {"WW": "water white", "EW": "extra white", "ELA": "extra light amber", "XLA": "extra light amber",
               "LA": "light amber", "DA": "dark amber"}


def extract_color(text: str | None) -> tuple[str | None, str]:
    """Find a USDA colour grade in `text`. Returns (grade, text without the grade).

    "Extra Light Amber" -> "extra light amber"; "White or lighter" -> "white or lighter";
    "ELA" -> "extra light amber". Unknown -> (None, text)."""
    if not text:
        return None, ""
    t = re.sub(r"\b[Ll]t\.?(?=\s)", "Light", text)
    t = re.sub(r"\b[Ee]x\.?(?=\s+[Ll]ight)", "Extra", t)
    m = _COLOR_FULL.search(t)
    if m:
        grade = _collapse(m.group(1)).lower()
        if m.group(2):
            grade += " or darker" if m.group(2).lower() == "darker" else " or lighter"
        return grade, _collapse(t[: m.start()] + " " + t[m.end():])
    tokens = t.split()
    for i, tok in enumerate(tokens):
        if tok.strip(".,;:()") in _COLOR_ABBR:
            return _COLOR_ABBR[tok.strip(".,;:()")], _collapse(" ".join(tokens[:i] + tokens[i + 1:]))
    return None, _collapse(t)


_ORGANIC = re.compile(r"\b(certified\s+(for\s+)?)?organic\b", re.I)


# =============================================================================================
# 1) AMS National Honey Report (FVMHONEY) - PDF parser (pure functions)
# =============================================================================================

PARSER_VERSION = "fvmhoney/2026.11-1"

# Section keys
BEEKEEPER = "beekeeper"                     # prices paid to US beekeepers (producer prices)
CANADA = "canadian_beekeeper"               # prices paid to Canadian beekeepers (producer prices)
IMPORTER = "importer"                       # prices paid to importers, by origin (wholesale bulk)
ACE_IMPORTS = "ace_imports"                 # CBP ACE import tables by HTS-10 (kg, value)
EXPORTS = "exports"                         # US exports (not collected: not relevant, often stale)
NARRATIVE = "narrative"                     # market commentary
VISUAL = "visual"                           # weather maps / data visualisations (since 2025)
UNKNOWN = "unknown"                         # a price table we do not recognise -> warned, skipped
PRICE_SECTIONS = (BEEKEEPER, CANADA, IMPORTER)

# Price values: anything above this without "$" is cents (older issues print 190.00 / 210-225).
CENTS_THRESHOLD = 20.0
# Plausibility window for bulk honey in USD/lb; outside -> warned and skipped, never stored.
PRICE_MIN_USD_LB, PRICE_MAX_USD_LB = 0.30, 15.0
# A first cell starting within this many character widths of the left margin is a label column.
LABEL_MAX_INDENT = 3.0

_MONTH_NAMES = "January|February|March|April|May|June|July|August|September|October|November|December"
_FULL_DATE = re.compile(rf"\b({_MONTH_NAMES})\s+(\d{{1,2}}),?\s+(\d{{4}})\b", re.I)
_MONTH_YEAR = re.compile(rf"\b({_MONTH_NAMES})\s+(\d{{4}})\b", re.I)
_VOLUME = re.compile(r"\bVolume\s+([IVXLCDM]+)\s*[-–—]?\s*(?:Number|No\.?)\s*(\d+)", re.I)
_MONTH_NUM = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}

_PRICE_NUM = r"\$?\s?\d+(?:\.\d+)?"
_PRICE_TAIL = re.compile(
    rf"(?:(?<=\s)|^)(?P<low>{_PRICE_NUM})(?:\s*(?:-|–|—|to)\s*(?P<high>{_PRICE_NUM}))?\s*$"
)
_PRICE_LIKE = re.compile(r"\$\s?\d|\b\d+\.\d{2}\b")
_PLACEHOLDER = re.compile(
    r"\b(no reports? issued|no report|too few (?:prices|sales|reports|trades)\b.*|"
    r"insufficient (?:data|prices|sales|trading)\b.*|"
    r"not available|no (?:sales|trading|market|prices) (?:reported|established)|none reported|n/a)\b",
    re.I,
)
_HEADER_WORDS = ("state", "floral", "color", "colour", "price", "origin", "province", "country", "source")
_ACE_NOTE = re.compile(r"^(source|cif value|total value|note|notes|data source)\s*[:.]")
_HTS = re.compile(r"\b0409(?:\.?\d){6}\b")
_ACE_NUM = re.compile(r"^(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$|^[-–]{1,2}$")

# (section, pattern on the lower-cased line, max line length (0 = any))
_HEADINGS: list[tuple[str, re.Pattern, int]] = [
    (CANADA, re.compile(r"^prices paid to canadian beekeepers\b"), 0),
    (BEEKEEPER, re.compile(r"^prices paid to (?:u\.?\s?s\.?\s+)?beekeepers for (?:extracted|unprocessed|bulk)"), 0),
    (IMPORTER, re.compile(r"^prices paid to importers for\b"), 0),
    (NARRATIVE, re.compile(r"^colony,? honey plant,? and market conditions\b"), 80),
    (NARRATIVE, re.compile(r"^(?:honey )?market (?:conditions|commentary|summary|overview)\b"), 60),
    (ACE_IMPORTS, re.compile(r"^(?:u\.?\s?s\.?\s+)?(?:honey\s+)?imports?\b.*\b(?:origin|country)\b"), 90),
    (ACE_IMPORTS, re.compile(r"^(?:u\.?\s?s\.?\s+)?honey imports\b"), 90),
    (EXPORTS, re.compile(r"^(?:u\.?\s?s\.?\s+)?(?:honey\s+)?exports?\b.*\b(?:destination|country)\b"), 90),
    (EXPORTS, re.compile(r"^(?:u\.?\s?s\.?\s+)?honey exports\b"), 90),
    (VISUAL, re.compile(r"^(?:temperature|precipitation|drought)\b|data visuali[sz]ation"), 110),
    (UNKNOWN, re.compile(r"^prices? (?:paid|received)\b"), 0),
]
_BOILERPLATE = [
    re.compile(r"^(?:usda\s+)?national honey report\b.{0,40}$"),
    re.compile(r"^(?:usda\b|u\.s\. department of agriculture|agricultural marketing service|"
               r"specialty crops market news)"),
    re.compile(r"(?:www\.|https?://|mymarketnews|@usda\.gov)"),
    re.compile(r"^for more information\b"),
]
_PAGE_HEADER = [_VOLUME, re.compile(r"^page\s+\d+(?:\s+of\s+\d+)?$", re.I)]

US_STATES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut", "delaware", "florida",
    "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine",
    "maryland", "massachusetts", "michigan", "minnesota", "mississippi", "missouri", "montana", "nebraska",
    "nevada", "new hampshire", "new jersey", "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina", "south dakota", "tennessee", "texas",
    "utah", "vermont", "virginia", "washington", "west virginia", "wisconsin", "wyoming",
}
CA_PROVINCES = {
    "alberta", "british columbia", "manitoba", "new brunswick", "newfoundland", "newfoundland and labrador",
    "nova scotia", "ontario", "prince edward island", "quebec", "saskatchewan",
}
# Floral descriptors USDA prints that the generic variety vocabulary spells differently.
_USDA_FLORAL_ALIASES = [
    (re.compile(r"\bhoney\s*dew\b", re.I), "honeydew"),
    (re.compile(r"^\s*mixed\s*$", re.I), "mixed flower"),
    (re.compile(r"\bmixed\s+flowers?\b", re.I), "mixed flower"),
]
# Phrases from the table headings that describe the trade terms (kept verbatim, in order).
_TERM_PHRASES = [
    "duty paid", "containers included", "containers exchanged or returned", "ex-dock or point of entry",
    "f.o.b. shipping point", "f.o.b. or delivered nearby", "prompt delivery & payment",
    "duty and crossing charges extra", "in volumes of 10,000 pounds or greater", "in 55 gallon drums",
]
_TERMS_BASE = {
    BEEKEEPER: "bulk extracted honey, paid to beekeepers",
    CANADA: "bulk unprocessed honey, paid to Canadian beekeepers",
    IMPORTER: "bulk honey, paid to importers",
}


@dataclass(frozen=True)
class ReportLine:
    """One text line of a report page. Columns are separated by two or more spaces."""

    page: int
    text: str
    indent: float = 0.0     # distance of the first word from the page's left margin, in characters

    @property
    def cells(self) -> list[str]:
        return [c for c in re.split(r"\s{2,}", self.text.strip()) if c]

    @property
    def norm(self) -> str:
        return _collapse(self.text).lower()


@dataclass
class HoneyPrice:
    section: str                # BEEKEEPER | CANADA | IMPORTER
    label: str                  # state / province / origin country, as printed
    origin_iso3: str
    market_iso3: str
    descriptor: str | None      # floral source / descriptor as printed, colour removed
    color_grade: str | None
    organic: bool
    variety: str
    low: float | None
    high: float | None
    value: float                # the single price, or the mid-point of a range
    currency: str
    printed_in_cents: bool
    terms: str
    heading: str
    page: int
    raw_line: str
    unit: str = "lb"


@dataclass
class HoneyImportRow:
    """One origin row of a CBP/ACE import table (one table per HTS-10 category)."""

    hts_code: str | None
    table_title: str
    color_grade: str | None
    organic: bool
    origin_label: str
    origin_iso3: str
    year: int
    month: int
    kilograms: float | None
    value: float | None         # customs value, USD
    cif_value: float | None     # cost of insurance and freight, USD
    total_value: float | None   # value + CIF value, USD
    ytd: dict
    page: int
    raw_line: str


@dataclass
class HoneyReportParse:
    issue_date: date | None = None
    volume: str | None = None
    number: int | None = None
    prices: list[HoneyPrice] = field(default_factory=list)
    imports: list[HoneyImportRow] = field(default_factory=list)
    narrative: str | None = None
    sections: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    parser_version: str = PARSER_VERSION


# ------------------------------------------------------------------ text extraction (pdfplumber)


def words_to_lines(words: list[dict], page: int = 1, *, y_tolerance: float = 3.0) -> list[ReportLine]:
    """Group pdfplumber words (dicts with text/x0/x1/top) into `ReportLine`s.

    Words on the same baseline (within `y_tolerance`) form a line. A horizontal gap wider
    than about one average character starts a new column; it is written as two spaces.
    `indent` is the first word's distance from the page's leftmost word, in characters."""
    words = [w for w in words if str(w.get("text", "")).strip()]
    if not words:
        return []
    widths = sorted((w["x1"] - w["x0"]) / len(w["text"]) for w in words if len(w["text"]) >= 2)
    char_w = widths[len(widths) // 2] if widths else 5.0
    gap = max(2.0, 1.1 * char_w)
    margin = min(w["x0"] for w in words)
    rows: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if rows and abs(w["top"] - rows[-1][0]["top"]) <= y_tolerance:
            rows[-1].append(w)
        else:
            rows.append([w])
    out: list[ReportLine] = []
    for row in rows:
        row.sort(key=lambda w: w["x0"])
        parts = [row[0]["text"]]
        for prev, cur in zip(row, row[1:]):
            parts.append("  " if cur["x0"] - prev["x1"] > gap else " ")
            parts.append(cur["text"])
        out.append(ReportLine(page, "".join(parts), round((row[0]["x0"] - margin) / char_w, 1)))
    return out


def pdf_to_lines(content: bytes) -> list[ReportLine]:
    """Extract text lines from a PDF with pdfplumber word coordinates."""
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover - dependency is declared in pyproject
        raise CollectorError("pdfplumber is not installed") from exc
    try:
        out: list[ReportLine] = []
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for pno, page in enumerate(pdf.pages, 1):
                words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
                out.extend(words_to_lines(words, page=pno))
        return out
    except Exception as exc:  # noqa: BLE001 - pdfminer raises many exception types for bad files
        raise CollectorError(f"PDF could not be read ({type(exc).__name__}: {exc})") from exc


def lines_from_text(text: str) -> list[ReportLine]:
    """Build `ReportLine`s from a plain-text layout (form feed = new page). Used for tests and
    for the TXT twin of the report should AMS publish one again."""
    out: list[ReportLine] = []
    page = 1
    for raw in text.replace("\r\n", "\n").split("\n"):
        while raw.startswith("\f"):
            page += 1
            raw = raw[1:]
        if "\f" in raw:     # page break in the middle of a line: keep the text, count the page
            page += raw.count("\f")
            raw = raw.replace("\f", "")
        if not raw.strip():
            continue
        out.append(ReportLine(page, raw.strip(), float(len(raw) - len(raw.lstrip(" ")))))
    return out


# ------------------------------------------------------------------ line-level helpers (pure)


def parse_price_token(token: str) -> tuple[float, bool]:
    """'$1.90' -> (1.90, False); '1.44' -> (1.44, False); '190.00' / '210' -> (1.90/2.10, True: cents)."""
    dollars = "$" in token
    value = float(token.replace("$", "").replace(",", "").strip())
    if not dollars and value > CENTS_THRESHOLD:
        return round(value / 100.0, 4), True
    return value, False


_FOOTNOTE_TAIL = re.compile(r"\s*(?:\*+|\(\w\)|\d/)\s*$")


def _is_price_token(token: str) -> bool:
    """A bare integer of 4+ digits without '$' is a year or a quantity, never a price."""
    t = token.replace(" ", "")
    return "$" in t or "." in t or len(t) <= 3


def split_price_tail(text: str) -> tuple[str, tuple[float, float | None, bool] | None]:
    """Split a table line into (text before the price, (low, high, printed_in_cents)).
    Returns (text, None) when the line does not end in a price or price range.
    A trailing footnote marker ('*', '(a)', '1/') is ignored."""
    stripped = _FOOTNOTE_TAIL.sub("", text.rstrip())
    m = _PRICE_TAIL.search(stripped)
    if not m or not all(_is_price_token(t) for t in (m.group("low"), m.group("high")) if t):
        return text, None
    low, c1 = parse_price_token(m.group("low"))
    high, c2 = (None, c1)
    if m.group("high"):
        high, c2 = parse_price_token(m.group("high"))
    return stripped[: m.start()].rstrip(), (low, high, c1 or c2)


def _geo(text: str, section: str) -> str | None:
    """Resolve a row label (state, province or country) for a price section."""
    t = _collapse(text).lower().strip(" .:")
    if section == BEEKEEPER:
        return "USA" if t in US_STATES else None
    if section == CANADA:
        return "CAN" if t in CA_PROVINCES else None
    if section in (IMPORTER, ACE_IMPORTS):
        if len(t) <= 3:          # never resolve 2/3-letter tokens as country codes here
            return None
        return lookup_iso3(text.title())
    return None


_UPPER_WORD = re.compile(r"^[A-Z][A-Z.'&/-]*$")


def _is_upper_label(text: str) -> bool:
    """An UPPER-CASE row label such as 'NORTH DAKOTA' or 'DAKOTA' (not a colour like 'ELA')."""
    words = text.split()
    if not words or len(words) > 4 or not all(_UPPER_WORD.match(w) for w in words):
        return False
    if not any(len(w.strip(".")) >= 3 for w in words):
        return False
    color, rest = extract_color(text)
    if color and not rest.strip():
        return False
    return _collapse(text).lower() not in ("organic", "mixed", "honey dew", "honeydew")


def _split_label(body: str, indent: float, section: str) -> tuple[str | None, str | None, str]:
    """Return (label, iso3, rest). label None = the row continues the previous label.

    Only an indented row continues the previous label. A row starting in the label column
    always names a new label; when it is unknown, iso3 is None so the caller warns and skips it."""
    cells = [c for c in re.split(r"\s{2,}", body.strip()) if c]
    if not cells:
        return None, None, ""
    if indent >= LABEL_MAX_INDENT:
        return None, None, " ".join(cells)
    first = cells[0]
    iso = _geo(first, section)
    if iso:
        return first, iso, " ".join(cells[1:])
    words = body.split()
    for n in range(min(4, len(words)), 0, -1):        # cells merged in the PDF: try word prefixes
        cand = " ".join(words[:n])
        iso = _geo(cand, section)
        if iso:
            return cand, iso, " ".join(words[n:])
    if _is_upper_label(first):
        # A label we do not know: US/CA region names are kept as printed (e.g. "DAKOTA");
        # an unknown origin country is returned without ISO3 so the caller can warn.
        return first, {BEEKEEPER: "USA", CANADA: "CAN"}.get(section), " ".join(cells[1:])
    # Mixed case ("Laos") or with punctuation ("KOREA, SOUTH"): still a new label, never a continuation.
    return first, None, " ".join(cells[1:])


def describe(descriptor: str) -> tuple[str | None, str | None, bool, str]:
    """Split a descriptor such as 'Organic  Mixed Flower  Light Amber' into
    (floral text or None, colour grade, organic, Variety value)."""
    color, rest = extract_color(descriptor)
    organic = bool(_ORGANIC.search(rest))
    floral = _collapse(_ORGANIC.sub(" ", rest)).strip(" ,;-") or None
    if not floral:
        return None, color, organic, Variety.UNSPECIFIED.value
    text = floral
    for pattern, repl in _USDA_FLORAL_ALIASES:
        text = pattern.sub(repl, text)
    variety, _ = normalize_variety(text + (" organic" if organic else ""))
    return floral, color, organic, variety


def heading_currency(heading: str) -> str | None:
    h = _collapse(heading).lower()
    if re.search(r"\bu\.?\s?s\.?\s+(?:currency|dollars?|funds)\b", h) or "us dollar" in h:
        return "USD"
    if "canadian currency" in h or "canadian dollar" in h or "currency of country of origin" in h:
        return "CAD"
    return None


def heading_terms(section: str, heading: str) -> str:
    h = _collapse(heading).lower()
    found = [p for p in _TERM_PHRASES if p in h]
    return ", ".join([_TERMS_BASE[section], *found, "per lb as published"])[:200]


def _is_column_header(norm: str) -> bool:
    hits = sum(1 for w in _HEADER_WORDS if re.search(rf"\b{w}\b", norm))
    return hits >= 2 and not any(ch.isdigit() for ch in norm)


def _match_heading(norm: str, current: str | None) -> str | None:
    for section, pattern, max_len in _HEADINGS:
        if max_len and (len(norm) > max_len or norm.endswith(".")):
            continue
        if section == UNKNOWN and current == NARRATIVE:
            continue            # "Prices paid to ... were steady" is commentary, not a new table
        if pattern.search(norm):
            return section
    # An HTS table title outside the export section starts the import tables.
    if current != EXPORTS and re.match(r"^natural honey\b", norm) and _HTS.search(norm) and len(norm) < 160:
        return ACE_IMPORTS
    return None


def _hts_code(text: str) -> str | None:
    m = _HTS.search(text)
    return re.sub(r"\D", "", m.group(0)) if m else None


def _ace_fields(norm: str) -> list[str]:
    names = {"kilograms": "kg", "cif value": "cif", "total value": "total", "value": "value"}
    return [names[m] for m in re.findall(r"kilograms|cif value|total value|value", norm)]


def _ace_number(token: str) -> float | None:
    if re.fullmatch(r"[-–]{1,2}", token):
        return None
    return float(token.replace(",", ""))


def _split_numeric_tail(text: str) -> tuple[str, list[str]]:
    tokens = text.split()
    nums: list[str] = []
    while tokens and _ACE_NUM.match(tokens[-1]):
        nums.insert(0, tokens.pop())
    return " ".join(tokens), nums


# ------------------------------------------------------------------ the parser


@dataclass
class _AceTable:
    title: str
    hts: str | None
    color: str | None
    organic: bool
    page: int
    month: tuple[int, int] | None = None
    fields: list[str] | None = None
    rows: int = 0
    warned_month: bool = False


class _HoneyReportParser:
    """Line-by-line state machine. See `parse_honey_report_lines`."""

    def __init__(self) -> None:
        self.out = HoneyReportParse()
        self.section: str | None = None
        self.in_heading = False
        self.heading_lines: list[str] = []
        self.carry: tuple[str, str | None] | None = None   # (label, iso3) for continuation rows
        self.ace: _AceTable | None = None
        self.counts: Counter = Counter()                    # data rows per section
        self.placeholders: Counter = Counter()
        self.unknown_price_lines = 0
        self.narrative: list[list[str]] = []                # blocks of lines

    # -------------------------------------------------------------- driver
    def run(self, lines: list[ReportLine]) -> HoneyReportParse:
        self._parse_header(lines)
        for line in lines:
            norm = line.norm
            if not norm or any(p.search(line.text) for p in _PAGE_HEADER):
                continue
            new_section = _match_heading(norm, self.section)
            if new_section:
                self._enter(new_section, line)
                continue
            if self.section != NARRATIVE and len(norm) < 100 and any(p.search(norm) for p in _BOILERPLATE):
                continue
            if self.section in PRICE_SECTIONS:
                self._price_line(line)
            elif self.section == ACE_IMPORTS:
                self._ace_line(line)
            elif self.section == NARRATIVE:
                self._narrative_line(line)
            elif self.section == UNKNOWN:
                self.unknown_price_lines += bool(_PRICE_LIKE.search(line.text))
            elif self.section is None:
                if _PRICE_LIKE.search(line.text):
                    self.warn(line, "price-like text outside any recognised section")
            # EXPORTS / VISUAL: intentionally ignored
        self._leave()
        self._finish()
        return self.out

    def warn(self, line: ReportLine | None, msg: str) -> None:
        where = f"p.{line.page}: " if line is not None else ""
        snippet = f" [{_collapse(line.text)[:90]}]" if line is not None else ""
        text = f"{where}{msg}{snippet}"
        if text not in self.out.warnings:
            self.out.warnings.append(text)

    # -------------------------------------------------------------- header / sections
    def _parse_header(self, lines: list[ReportLine]) -> None:
        for line in lines:
            m = _VOLUME.search(line.text)
            if m:
                self.out.volume, self.out.number = m.group(1).upper(), int(m.group(2))
                d = _FULL_DATE.search(line.text)
                if d:
                    self.out.issue_date = _date_from_match(d)
                    return
        first_page = lines[0].page if lines else 1
        for line in [ln for ln in lines if ln.page == first_page][:8]:
            d = _FULL_DATE.search(line.text)
            if d:
                self.out.issue_date = _date_from_match(d)
                return

    def _enter(self, section: str, line: ReportLine) -> None:
        if section == self.section and section != ACE_IMPORTS:
            # repeated heading ("... (continued)" on the next page): keep the group label
            self.in_heading = True
            self.heading_lines.append(line.text.strip())
            return
        self._leave()
        self.section = section
        self.in_heading = True
        self.heading_lines = [line.text.strip()]
        self.carry = None
        if section not in self.out.sections:
            self.out.sections.append(section)
        if section == UNKNOWN:
            self.warn(line, "unrecognised price section - rows skipped (layout change?)")
        elif section == NARRATIVE:
            self.narrative.append([_collapse(line.text)])
        elif section == ACE_IMPORTS:
            self.ace = None
            if re.match(r"^natural honey\b", line.norm):      # the heading is the table title itself
                self._ace_new_table(line)

    def _leave(self) -> None:
        if self.section == UNKNOWN and self.unknown_price_lines:
            self.warn(None, f"{self.unknown_price_lines} price-like line(s) skipped in an unrecognised section")
        self.unknown_price_lines = 0
        self._ace_close()

    def _finish(self) -> None:
        for s in self.out.sections:
            if s in PRICE_SECTIONS and not self.counts[s] and not self.placeholders[s]:
                self.warn(None, f"section '{s}' found but no row could be parsed")
            if s == ACE_IMPORTS and not self.counts[s]:
                self.warn(None, "import tables found but no row could be parsed")
        paragraphs = ["\n".join(block[:1] + _reflow(block[1:])).strip() for block in self.narrative]
        # A narrative made only of headings carries no commentary.
        has_text = any(len(block) > 1 for block in self.narrative)
        self.out.narrative = "\n\n".join(p for p in paragraphs if p) if has_text else None

    # -------------------------------------------------------------- price tables
    def _price_line(self, line: ReportLine) -> None:
        norm = line.norm
        body, price = split_price_tail(line.text)
        ph = None if price else _PLACEHOLDER.search(line.text)
        if price is None and ph is None:
            if _is_column_header(norm):
                self.in_heading = False
                return
            if self._label_only(line):
                self.in_heading = False
                return
            if self.in_heading:
                self.heading_lines.append(line.text.strip())
                return
            # e.g. the first half of a wrapped label: what follows must not inherit the previous origin
            self.carry = None
            self.warn(line, f"unparsed line in '{self.section}' table")
            return
        self.in_heading = False
        if ph is not None:
            body = line.text[: ph.start()]
        label, iso3, rest = _split_label(body, line.indent, self.section)
        if label is not None:
            self.carry = (label, iso3)
        if ph is not None:
            self.placeholders[self.section] += 1
            return
        if self.carry is None:
            self.warn(line, "price row without a state/origin label - skipped")
            return
        label, iso3 = self.carry
        if iso3 is None:
            self.warn(line, f"unknown origin '{label}' - row skipped")
            return
        low, high, cents = price
        if high is not None and high < low:
            self.warn(line, "price range with low > high - skipped")
            return
        value = round((low + high) / 2, 4) if high is not None else low
        if not (PRICE_MIN_USD_LB <= low <= PRICE_MAX_USD_LB) or (high is not None and high > PRICE_MAX_USD_LB):
            self.warn(line, f"implausible price {low}{'-' + str(high) if high else ''} per lb - skipped")
            return
        heading = " ".join(self.heading_lines)
        currency = "USD"
        if self.section == CANADA:
            currency = heading_currency(heading)
            if currency is None:
                self.warn(line, "currency of the Canadian table not stated in its heading - row skipped")
                return
        floral, color, organic, variety = describe(rest)
        self.counts[self.section] += 1
        self.out.prices.append(HoneyPrice(
            section=self.section, label=_collapse(label), origin_iso3=iso3,
            market_iso3="CAN" if self.section == CANADA else "USA",
            descriptor=floral, color_grade=color, organic=organic, variety=variety,
            low=low if high is not None else None, high=high, value=value, currency=currency,
            printed_in_cents=cents, terms=heading_terms(self.section, heading), heading=_collapse(heading)[:500],
            page=line.page, raw_line=_collapse(line.text),
        ))

    def _label_only(self, line: ReportLine) -> bool:
        """A line holding only a group label (e.g. 'CALIFORNIA' above its rows)."""
        text = _collapse(line.text)
        if line.indent >= LABEL_MAX_INDENT or re.search(r"[,:;]", text) or text.endswith("."):
            return False
        iso = _geo(text, self.section)
        if iso or (not self.in_heading and _is_upper_label(text)):
            self.carry = (text, iso if iso else {BEEKEEPER: "USA", CANADA: "CAN"}.get(self.section))
            return True
        return False

    # -------------------------------------------------------------- CBP ACE import tables
    def _ace_new_table(self, line: ReportLine) -> None:
        self._ace_close()
        title = _collapse(line.text)
        color, _ = extract_color(re.sub(r"\(.*?\)", " ", title))
        self.ace = _AceTable(title=title, hts=_hts_code(title), color=color,
                             organic=bool(_ORGANIC.search(title)), page=line.page)
        my = _MONTH_YEAR.search(title)
        if my:
            self.ace.month = (int(my.group(2)), _MONTH_NUM[my.group(1).lower()])

    def _ace_close(self) -> None:
        self.ace = None

    def _ace_line(self, line: ReportLine) -> None:
        norm, text = line.norm, line.text
        if re.match(r"^natural honey\b", norm) and len(norm) < 160:
            self._ace_new_table(line)
            return
        if _ACE_NOTE.match(norm):
            return
        t = self.ace
        if t is not None and not t.rows and not t.hts and _hts_code(text) and not t.fields:
            t.hts = _hts_code(text)                        # title wrapped onto a second line
            t.title = _collapse(t.title + " " + text)
            return
        if "kilograms" in norm:
            if t is None:
                self.warn(line, "import column header outside a table")
                return
            t.fields = _ace_fields(norm)
            self._ace_month(t, text)
            return
        if _MONTH_YEAR.search(text) and not re.search(r"\d,\d{3}", text):
            if t is not None:
                self._ace_month(t, text)
            return
        label, nums = _split_numeric_tail(text)
        if not nums:
            if t is not None and not _PLACEHOLDER.search(norm):
                self.warn(line, "unparsed line in an import table")
            return
        if t is None or not t.fields:
            self.warn(line, "import row without a table title / column header - skipped")
            return
        if t.month is None:
            if not t.warned_month:
                self.warn(line, f"import table '{t.title[:60]}' has no month - table skipped")
                t.warned_month = True
            return
        if len(nums) != len(t.fields):
            self.warn(line, f"import row has {len(nums)} numbers, header has {len(t.fields)} columns - skipped")
            return
        label = _collapse(label)
        if re.fullmatch(r"(?i)(grand\s+)?total(\s+all\s+countries)?|world", label):
            iso3 = "WLD"
        else:
            iso3 = _geo(label, ACE_IMPORTS)
        if not iso3:
            self.warn(line, f"unknown country of origin '{label}' in import table - skipped")
            return
        month_vals: dict[str, float | None] = {}
        ytd: dict[str, float | None] = {}
        target = month_vals
        for i, (fname, tok) in enumerate(zip(t.fields, nums)):
            if fname == "kg" and i > 0:
                target = ytd
            target[fname] = _ace_number(tok)
        t.rows += 1
        self.counts[ACE_IMPORTS] += 1
        self.out.imports.append(HoneyImportRow(
            hts_code=t.hts, table_title=t.title, color_grade=t.color, organic=t.organic,
            origin_label=label, origin_iso3=iso3, year=t.month[0], month=t.month[1],
            kilograms=month_vals.get("kg"), value=month_vals.get("value"), cif_value=month_vals.get("cif"),
            total_value=month_vals.get("total"), ytd=ytd, page=line.page, raw_line=_collapse(text),
        ))

    def _ace_month(self, t: _AceTable, text: str) -> None:
        my = _MONTH_YEAR.search(text)
        if my and t.month is None:
            t.month = (int(my.group(2)), _MONTH_NUM[my.group(1).lower()])

    # -------------------------------------------------------------- narrative
    def _narrative_line(self, line: ReportLine) -> None:
        text = _collapse(line.text)
        if _is_upper_label(text) or (_geo(text, BEEKEEPER) and len(text) < 30):
            self.narrative.append([text])                   # regional sub-heading
        elif self.narrative:
            self.narrative[-1].append(text)


def _reflow(lines: list[str]) -> list[str]:
    """Join wrapped lines into one paragraph (handles words hyphenated across lines)."""
    if not lines:
        return []
    text = ""
    for ln in lines:
        if text.endswith("-") and ln[:1].islower():
            text = text[:-1] + ln
        else:
            text = f"{text} {ln}" if text else ln
    return [text]


def _date_from_match(m: re.Match) -> date | None:
    try:
        return date(int(m.group(3)), _MONTH_NUM[m.group(1).lower()], int(m.group(2)))
    except ValueError:
        return None


def parse_honey_report_lines(lines: list[ReportLine]) -> HoneyReportParse:
    """Parse the National Honey Report from text lines (pure; no I/O).

    Returns prices (producer / wholesale bulk, USD per lb as published), CBP import rows,
    the market narrative (if the issue has one), the issue date and parser warnings."""
    return _HoneyReportParser().run(lines)


def parse_honey_report_pdf(content: bytes) -> HoneyReportParse:
    """Parse a National Honey Report PDF. Raises CollectorError if the file is unusable."""
    if not content.lstrip()[:5].startswith(b"%PDF"):
        raise CollectorError("downloaded file is not a PDF")
    lines = pdf_to_lines(content)
    if not lines:
        raise CollectorError("PDF contains no extractable text (scanned image?)")
    parsed = parse_honey_report_lines(lines)
    if not any(s in parsed.sections for s in (*PRICE_SECTIONS, ACE_IMPORTS)):
        raise CollectorError("no known National Honey Report section found (layout changed?)")
    return parsed


# ------------------------------------------------------------------ ESMIS release list (pure)


@dataclass(frozen=True)
class EsmisRelease:
    release_id: str
    title: str
    release_date: date
    pdf_url: str | None
    files: tuple[str, ...] = ()


def parse_esmis_releases(payload: Any) -> tuple[list[EsmisRelease], list[str]]:
    """Parse an ESMIS `/api/v1/release/findBy...` page. Newest first."""
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise CollectorError("ESMIS: unexpected response (no 'results' list)")
    out: list[EsmisRelease] = []
    warnings: list[str] = []
    for item in payload["results"]:
        if not isinstance(item, dict):
            continue
        # 'YYYY-MM-DDTHH:MM:SS+0000' - really US Eastern wall-clock time; the date is what we need
        raw_dt = str(item.get("release_datetime") or "")
        rd = parse_date(raw_dt[:10]) if re.match(r"\d{4}-\d{2}-\d{2}", raw_dt) else None
        if rd is None:
            warnings.append(f"ESMIS release {item.get('id')!r} without a usable release_datetime - skipped")
            continue
        files = tuple(f for f in (item.get("files") or []) if isinstance(f, str) and f.startswith("http"))
        pdfs = sorted((f for f in files if urlparse(f).path.lower().endswith(".pdf")),
                      key=lambda u: "fvmhoney" not in u.lower())
        out.append(EsmisRelease(
            release_id=str(item.get("id") or ""), title=str(item.get("title") or "National Honey Report"),
            release_date=rd, pdf_url=pdfs[0] if pdfs else None, files=files,
        ))
    out.sort(key=lambda r: r.release_date, reverse=True)
    return out, warnings


# ------------------------------------------------------------------ collector

ESMIS_FVMHONEY_URL = "https://esmis.nal.usda.gov/api/v1/release/findByIdentifier/FVMHONEY"
ESMIS_PUBLICATION_URL = "https://esmis.nal.usda.gov/publication/national-honey-report"
AMS_LATEST_URL = "https://www.ams.usda.gov/mnreports/fvmhoney.pdf"
AMS_MIRROR_URL = "https://ams-prod.azureedge.us/mnreports/fvmhoney.pdf"
# In-app link to a report's archived original (served by api/reports.py, byte for byte as downloaded).
ARCHIVED_REPORT_FILE_URL = "/api/reports/{report_id}/file"
HONEY_BACKFILL_RELEASES = 24        # newest ESMIS issues downloaded and parsed
ESMIS_EMPTY_RETRIES = 3             # ESMIS sometimes answers with an empty list; retry, 5 s apart
REPORT_DATE_MATCH_DAYS = 4          # an AMS issue within this many days of an ESMIS release = same issue


class UsdaHoneyReportCollector(Collector):
    key = "usda_honey_report"
    name = "USDA AMS – National Honey Report (prezzi miele USA)"
    publisher = "USDA Agricultural Marketing Service (AMS), Specialty Crops Market News"
    homepage = "https://mymarketnews.ams.usda.gov/viewReport/2901"
    kind = SourceKind.PDF
    reliability = Reliability.OFFICIAL
    category = "prices"
    country_iso3 = "USA"
    language = "en"
    expected_update = "Monthly (issue dated near the end of the month)"
    expected_max_age_days = 40
    terms_note = (
        "US Government work (public domain, 17 USC 105). Cite 'USDA AMS Market News, National Honey "
        "Report'. Back issues via USDA National Agricultural Library ESMIS. Prices are published per "
        "pound (USD); per-kg values are converted."
    )
    # Around month end (issue date) and the first days of the next month, morning and evening (Rome).
    schedule = {"trigger": "cron", "day": "1-5,25-31", "hour": "8,22", "minute": 40}
    order = 20

    def collect(self, ctx: CollectContext) -> None:
        errors: list[CollectorError] = []
        successes = 0

        # 1) ESMIS archive: register every listed release, download the newest ones not yet parsed.
        releases: list[EsmisRelease] = []
        try:
            releases = self._esmis_releases(ctx)
            successes += 1
        except CollectorError as exc:
            errors.append(exc)
            ctx.warn(f"ESMIS archive unavailable ({exc}); using the AMS latest issue only")

        for rel in releases:
            ctx.add_report(
                report_key=rel.release_date.isoformat(),
                title=f"{rel.title} – {_long_date(rel.release_date)}",
                url=rel.pdf_url or (rel.files[0] if rel.files else ESMIS_PUBLICATION_URL),
                published_at=rel.release_date,
                period_label=_period_label(rel.release_date.year, rel.release_date.month),
            )
        ctx.checkpoint()

        wanted = [r for r in releases[:HONEY_BACKFILL_RELEASES] if r.pdf_url]
        for rel in sorted(wanted, key=lambda r: r.release_date):    # oldest first: newer issues supersede
            report = self._report(ctx, rel.release_date.isoformat())
            if report is not None and report.raw_document_id and not ctx.force:
                continue
            try:
                self._process_pdf(ctx, url=rel.pdf_url, report_key=rel.release_date.isoformat(),
                                  title=f"{rel.title} – {_long_date(rel.release_date)}",
                                  release_date=rel.release_date)
                successes += 1
            except CollectorError as exc:
                errors.append(exc)
                ctx.warn(f"Issue of {rel.release_date.isoformat()} ({rel.pdf_url}) not processed: {exc}")

        # 2) AMS "latest issue" URL (ESMIS may lag; the AMS file is overwritten every month).
        try:
            self._process_latest(ctx)
            successes += 1
        except CollectorError as exc:
            errors.append(exc)
            ctx.warn(f"AMS latest issue not processed: {exc}")

        if successes == 0 and errors:
            if all(isinstance(e, Offline) for e in errors):
                raise errors[0]
            raise CollectorError("; ".join(str(e) for e in errors)[:1000])

    # -------------------------------------------------------------- steps
    def _esmis_releases(self, ctx: CollectContext) -> list[EsmisRelease]:
        for attempt in range(ESMIS_EMPTY_RETRIES + 1):
            doc = ctx.fetch(ESMIS_FVMHONEY_URL, params={"page": 0}, headers={"Accept": "application/json"},
                            title="ESMIS – National Honey Report releases")
            try:
                payload = doc.json()
            except ValueError as exc:
                raise CollectorError("ESMIS response is not JSON") from exc
            releases, warnings = parse_esmis_releases(payload)
            for w in warnings:
                ctx.warn(w)
            if releases:
                return releases
            if attempt < ESMIS_EMPTY_RETRIES:
                ctx.checkpoint()        # do not hold the write lock (archived response) while waiting
                time.sleep(5)
        ctx.warn("ESMIS returned an empty National Honey Report release list (transient?)")
        return []

    def _report(self, ctx: CollectContext, report_key: str) -> Report | None:
        return ctx.session.scalars(
            select(Report).where(Report.source_id == ctx.source.id, Report.report_key == report_key)
        ).first()

    def _already_parsed(self, ctx: CollectContext, raw_document_id: int) -> bool:
        return ctx.session.scalar(
            select(func.count(Report.id)).where(Report.source_id == ctx.source.id,
                                                Report.raw_document_id == raw_document_id)
        ) > 0

    def _process_pdf(self, ctx: CollectContext, *, url: str, report_key: str, title: str,
                     release_date: date) -> None:
        doc = ctx.fetch(url, title=title, published_at=release_date)
        if self._already_parsed(ctx, doc.raw_document_id) and not ctx.force:
            # same bytes already parsed under another report (e.g. via the AMS latest URL)
            ctx.add_report(report_key=report_key, title=title, url=url, raw_document_id=doc.raw_document_id)
            return
        parsed = parse_honey_report_pdf(doc.content)
        issue = parsed.issue_date or release_date
        if parsed.issue_date and abs((parsed.issue_date - release_date).days) > 31:
            ctx.warn(f"{title}: issue date printed in the PDF ({parsed.issue_date}) differs from the "
                     f"ESMIS release date ({release_date}); using the printed date")
        self._store(ctx, parsed, issue, title=title, source_url=doc.url, raw_document_id=doc.raw_document_id)
        ctx.add_report(report_key=report_key, title=title, url=url, published_at=release_date,
                       period_label=_period_label(issue.year, issue.month),
                       raw_document_id=doc.raw_document_id, narrative=parsed.narrative)
        ctx.checkpoint()

    def _process_latest(self, ctx: CollectContext) -> None:
        doc = None
        first_error: CollectorError | None = None
        for url in (AMS_LATEST_URL, AMS_MIRROR_URL):
            try:
                doc = ctx.fetch(url, title="National Honey Report (latest issue)")
                break
            except CollectorError as exc:
                first_error = first_error or exc
        if doc is None:
            raise first_error or CollectorError("AMS latest issue unavailable")
        if self._already_parsed(ctx, doc.raw_document_id) and not ctx.force:
            return
        parsed = parse_honey_report_pdf(doc.content)
        if parsed.issue_date is None:
            raise CollectorError("issue date not found in the page header; refusing to guess the period")
        issue = parsed.issue_date
        report_key = self._report_key_near(ctx, issue) or issue.isoformat()
        title = f"National Honey Report – {_long_date(issue)}"
        report, _ = ctx.add_report(report_key=report_key, title=title, url=doc.url, published_at=issue,
                                   period_label=_period_label(issue.year, issue.month),
                                   raw_document_id=doc.raw_document_id, narrative=parsed.narrative)
        # AMS overwrites this URL every month: each price links to the archived copy of the exact file
        # it was parsed from; the AMS URL is kept in `extra["fetched_from"]` (and as the report's URL).
        # (If the matched report already archives other bytes, e.g. the ESMIS copy of the issue, the
        # link would not serve these bytes, so the fetched URL is kept.)
        source_url = (ARCHIVED_REPORT_FILE_URL.format(report_id=report.id)
                      if report.raw_document_id == doc.raw_document_id else doc.url)
        self._store(ctx, parsed, issue, title=title, source_url=source_url, raw_document_id=doc.raw_document_id,
                    fetched_from=doc.url)
        ctx.checkpoint()

    def _report_key_near(self, ctx: CollectContext, d: date) -> str | None:
        rows = ctx.session.scalars(select(Report).where(
            Report.source_id == ctx.source.id,
            Report.published_at >= d - timedelta(days=REPORT_DATE_MATCH_DAYS),
            Report.published_at <= d + timedelta(days=REPORT_DATE_MATCH_DAYS),
        )).all()
        rows.sort(key=lambda r: abs((r.published_at - d).days))
        return rows[0].report_key if rows else None

    def _store(self, ctx: CollectContext, parsed: HoneyReportParse, issue: date, *, title: str,
               source_url: str, raw_document_id: int, fetched_from: str | None = None) -> None:
        provenance = {"fetched_from": fetched_from} if fetched_from else {}
        for w in parsed.warnings:
            ctx.warn(f"{title}: {w}")
        if issue.day < 15:
            ctx.warn(f"{title}: issue dated early in the month; prices are assigned to {issue:%Y-%m} "
                     "(the issue month) as printed")
        ps, pe = month_bounds(issue.year, issue.month)
        label = _period_label(issue.year, issue.month)
        seen: Counter = Counter()
        for p in parsed.prices:
            price_type = PriceType.WHOLESALE_BULK if p.section == IMPORTER else PriceType.PRODUCER
            base = (f"usda_fvmhoney|{p.section}|{_slug(p.label)}|{_slug(p.descriptor)}|{_slug(p.color_grade)}|"
                    f"{'organic' if p.organic else 'conventional'}|{label}")
            seen[base] += 1
            series_key = base if seen[base] == 1 else f"{base}|{seen[base]}"
            place = p.label.title()
            if p.section == IMPORTER:
                origin_label = country_name(p.origin_iso3, "en") or place
                market_location = "United States (ex-dock / point of entry)"
            else:
                origin_label, market_location = place, place
            ctx.add_price(
                series_key=series_key, price_type=price_type, variety=p.variety, price_value=p.value,
                currency=p.currency, unit=p.unit, period_start=ps, period_end=pe, period_label=label,
                frequency="M", price_low=p.low, price_high=p.high,
                published_at=issue, source_url=source_url, raw_document_id=raw_document_id or None,
                origin_iso3=p.origin_iso3, origin_label=origin_label, market_iso3=p.market_iso3,
                market_location=market_location, variety_raw=p.descriptor, color_grade=p.color_grade,
                organic=p.organic, terms=p.terms, data_status=DataStatus.PUBLISHED,
                notes=f"{title}, p.{p.page}: {p.heading[:160]}",
                extra={"parser_version": parsed.parser_version, "page": p.page, "raw_line": p.raw_line,
                       "printed_in_cents": p.printed_in_cents, "report_section": p.section,
                       "issue_date": issue.isoformat(), "label_as_printed": p.label, **provenance},
            )
        for r in parsed.imports:
            if (r.year, r.month) > (issue.year, issue.month):
                ctx.warn(f"{title}: import table month {r.year}-{r.month:02d} is after the issue date - skipped")
                continue
            if not r.kilograms or not r.value or r.kilograms <= 0 or r.value <= 0:
                continue
            ps_i, pe_i = month_bounds(r.year, r.month)
            m_label = _period_label(r.year, r.month)
            line_id = r.hts_code or _slug(r.table_title)
            terms = "US customs value / net kg (CBP ACE; excludes freight, insurance & duty)"
            if r.hts_code:
                terms += f", HTS {r.hts_code}"
            ctx.add_price(
                series_key=f"usda_fvmhoney|ace|{line_id}|{r.origin_iso3}|{m_label}",
                price_type=PriceType.IMPORT_UNIT_VALUE, variety=Variety.UNSPECIFIED.value,
                price_value=round(r.value / r.kilograms, 4), currency="USD", unit="kg",
                period_start=ps_i, period_end=pe_i, period_label=m_label, frequency="M",
                volume_kg=r.kilograms, published_at=issue, source_url=source_url,
                raw_document_id=raw_document_id or None, origin_iso3=r.origin_iso3,
                origin_label=country_name(r.origin_iso3, "en") if r.origin_iso3 != "WLD" else "All origins",
                market_iso3="USA", market_location="United States (port of entry)", variety_raw=r.table_title,
                color_grade=r.color_grade, organic=r.organic, terms=terms, data_status=DataStatus.PUBLISHED,
                notes=f"{title}, p.{r.page}: derived unit value = customs value / kilograms",
                extra={"parser_version": parsed.parser_version, "page": r.page, "raw_line": r.raw_line,
                       "hts_code": r.hts_code, "kilograms": r.kilograms, "value_usd": r.value,
                       "cif_value_usd": r.cif_value, "total_value_usd": r.total_value,
                       "landed_unit_value_usd_per_kg": round(r.total_value / r.kilograms, 4)
                       if r.total_value else None,
                       "year_to_date": r.ytd, "issue_date": issue.isoformat(), **provenance},
            )


# =============================================================================================
# 2) USDA FAS GATS - Census monthly US imports by origin (HS 0409)
# =============================================================================================

GATS_BASE = "https://api.fas.usda.gov/api/gats"
GATS_RELEASES_URL = f"{GATS_BASE}/census/data/imports/dataReleaseDates"
GATS_IMPORTS_URL = GATS_BASE + "/censusImports/partnerCode/{partner}/year/{year}/month/{month}"
GATS_COMMODITIES_URL = f"{GATS_BASE}/commodities"
# GATS partner codes are FAS's own, NOT ISO (verified against /api/gats/countries, see research).
GATS_PARTNERS: dict[str, str] = {
    "AR": "ARG", "BR": "BRA", "CH": "CHN", "IN": "IND", "VM": "VNM", "UP": "UKR", "R1": "SRB", "UY": "URY",
    "MX": "MEX", "CA": "CAN", "TH": "THA", "TU": "TUR", "MD": "MDA", "RO": "ROU", "BU": "BGR", "HU": "HUN",
    "TW": "TWN", "N1": "NZL", "I1": "ITA", "SP": "ESP", "GM": "DEU",
}
GATS_UOM_KG = 47                    # censusUOMId1 for honey (HS6 040900 reference list)
GATS_WINDOW_MONTHS = 36             # months kept in sync with GATS (initial backfill + revisions)
GATS_MAX_MONTHS_PER_RUN = 18        # each month = one call per partner; the rest follows next run
GATS_MIN_RATE_REMAINING = 30        # stop early if the shared api.data.gov hourly quota runs low
GATS_HS10_REFRESH_DAYS = 30


@dataclass(frozen=True)
class GatsRelease:
    yyyymm: str
    year: int
    month: int
    timestamp: str              # releaseTimeStamp as published (naive, US Eastern)
    released: date | None


@dataclass
class GatsLine:
    hs10: str
    kg: float
    value: float                # customs value of imports for consumption, USD
    cif_total: float | None     # consumptionCIFValue = customs value + freight & insurance
    cif_charges: float | None   # cifValue = freight & insurance only
    general_kg: float | None    # general imports (quantity1 / value), kept for reference
    general_value: float | None


def _dec(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


def parse_gats_release_dates(payload: Any) -> list[GatsRelease]:
    """One record per statistical month; newest month first; latest timestamp per month."""
    if not isinstance(payload, list):
        raise CollectorError("GATS dataReleaseDates: unexpected response (not a list)")
    best: dict[str, GatsRelease] = {}
    for rec in payload:
        if not isinstance(rec, dict):
            continue
        ym = str(_ci_get(rec, "statisticalYearMonth") or "").strip()
        if not re.fullmatch(r"\d{6}", ym) or not 1 <= int(ym[4:]) <= 12:
            continue
        ptype = _ci_get(rec, "productType")
        reporter = _ci_get(rec, "reporterCode")
        if (ptype and str(ptype).upper() != "M") or (reporter and str(reporter).upper() not in ("US", "USA")):
            continue
        ts = str(_ci_get(rec, "releaseTimeStamp") or "").strip()
        rel = GatsRelease(ym, int(ym[:4]), int(ym[4:]), ts, parse_date(ts[:10]) if ts else None)
        if ym not in best or ts > best[ym].timestamp:
            best[ym] = rel
    if not best:
        raise CollectorError("GATS dataReleaseDates: no monthly release found")
    return sorted(best.values(), key=lambda r: r.yyyymm, reverse=True)


def select_gats_months(releases: list[GatsRelease], processed: dict[str, str], *,
                       window: int, cap: int) -> list[GatsRelease]:
    """Months to (re)fetch: within the newest `window` months, whose release timestamp differs
    from the one already processed (new month or a Census revision). Newest first, max `cap`."""
    recent = sorted(releases, key=lambda r: r.yyyymm, reverse=True)[:window]
    return [r for r in recent if processed.get(r.yyyymm) != r.timestamp][:cap]


def parse_gats_imports(payload: Any, *, partner: str, yyyymm: str) -> tuple[list[GatsLine], int, list[str]]:
    """Keep the HS 0409 lines of one partner-month listing. Returns (lines, records, warnings)."""
    if not isinstance(payload, list):
        if isinstance(payload, dict) and any(k in payload for k in ("error", "message", "errors")):
            raise CollectorError(f"GATS {partner} {yyyymm}: API error {str(payload)[:200]}")
        raise CollectorError(f"GATS {partner} {yyyymm}: unexpected response (not a list)")
    by_code: dict[str, GatsLine] = {}
    warnings: list[str] = []
    for rec in payload:
        if not isinstance(rec, dict):
            continue
        hs = re.sub(r"\D", "", str(_ci_get(rec, "hS10Code") or ""))
        if not hs.startswith("0409"):
            continue
        d = str(_ci_get(rec, "date") or "").strip()
        if d and d[:6] != yyyymm:
            warnings.append(f"GATS {partner} {yyyymm}: HS {hs} dated {d} - skipped")
            continue
        cc = str(_ci_get(rec, "countryCode") or "").strip().upper()
        if cc and cc != partner:
            warnings.append(f"GATS {partner} {yyyymm}: HS {hs} has countryCode {cc} - skipped")
            continue
        uom = _ci_get(rec, "censusUOMId1")
        if uom is None or str(uom).split(".")[0] != str(GATS_UOM_KG):
            warnings.append(f"GATS {partner} {yyyymm}: HS {hs} quantity unit {uom!r} is not kg - skipped")
            continue
        kg, val = _dec(_ci_get(rec, "consumptionQuantity1")), _dec(_ci_get(rec, "consumptionValue"))
        if kg is None or val is None:
            warnings.append(f"GATS {partner} {yyyymm}: HS {hs} without consumption quantity/value - skipped")
            continue
        cif_total, cif = _dec(_ci_get(rec, "consumptionCIFValue")), _dec(_ci_get(rec, "cifValue"))
        gkg, gval = _dec(_ci_get(rec, "quantity1")), _dec(_ci_get(rec, "value"))
        line = by_code.get(hs)
        if line is None:
            by_code[hs] = GatsLine(hs, float(kg), float(val), _f(cif_total), _f(cif), _f(gkg), _f(gval))
        else:   # the same HS-10 twice (should not happen): add up
            line.kg += float(kg)
            line.value += float(val)
            line.cif_total = _sum_opt(line.cif_total, cif_total)
            line.cif_charges = _sum_opt(line.cif_charges, cif)
            line.general_kg = _sum_opt(line.general_kg, gkg)
            line.general_value = _sum_opt(line.general_value, gval)
    return sorted(by_code.values(), key=lambda ln: ln.hs10), len(payload), warnings


def _f(v: Decimal | None) -> float | None:
    return float(v) if v is not None else None


def _sum_opt(a: float | None, b: Decimal | float | None) -> float | None:
    return None if a is None or b is None else a + float(b)


def parse_gats_commodities(payload: Any) -> dict[str, str]:
    """HS-10 code -> description for honey lines (codes starting 0409)."""
    if not isinstance(payload, list):
        raise CollectorError("GATS commodities: unexpected response (not a list)")
    out: dict[str, str] = {}
    for rec in payload:
        if not isinstance(rec, dict):
            continue
        code = re.sub(r"\D", "", str(_ci_get(rec, "hS10Code") or _ci_get(rec, "commodityCode") or ""))
        if len(code) != 10 or not code.startswith("0409"):
            continue
        desc = _ci_get(rec, "commodityDescription") or _ci_get(rec, "commodityName") or _ci_get(rec, "description")
        if desc:
            out[code] = _collapse(str(desc))
    return out


def hs10_attributes(description: str | None) -> tuple[str | None, bool]:
    """Colour grade and organic flag encoded in an HS-10 description (None/False if absent)."""
    if not description:
        return None, False
    color, _ = extract_color(description)
    return color, bool(_ORGANIC.search(description))


class UsdaFasGatsCollector(Collector):
    key = "usda_fas_gats"
    name = "USDA FAS GATS – Importazioni USA di miele per origine (Census)"
    publisher = "USDA Foreign Agricultural Service (data: US Census Bureau)"
    homepage = "https://apps.fas.usda.gov/gats/"
    kind = SourceKind.API
    reliability = Reliability.OFFICIAL
    category = "trade"
    country_iso3 = "USA"
    language = "en"
    expected_update = "Monthly, about 5-6 weeks after the month (Census FT-900 release)"
    expected_max_age_days = 70
    terms_note = (
        "US Census Bureau trade statistics via the USDA FAS GATS API (api.data.gov key). US Government "
        "public data. Values are customs values of imports for consumption (exclude freight, insurance "
        "and duty); CIF values are kept alongside. Monthly figures are revised annually by Census."
    )
    requires_key = "data_gov_api_key"
    schedule = {"trigger": "cron", "day_of_week": "wed", "hour": 15, "minute": 20}
    order = 30

    def collect(self, ctx: CollectContext) -> None:
        api_key = self.key_value(ctx.settings)
        if not api_key:
            raise MissingKey("API key not configured (DATA_GOV_API_KEY)")
        headers = {"X-Api-Key": api_key, "Accept": "application/json"}
        doc = ctx.fetch(GATS_RELEASES_URL, headers=headers, accept_status=(200, 401, 403),
                        title="GATS – Census import release dates")
        if doc.status_code in (401, 403):
            raise CollectorError(f"api.data.gov rejected the API key (HTTP {doc.status_code})")
        try:
            releases = parse_gats_release_dates(doc.json())
        except ValueError as exc:
            raise CollectorError("GATS dataReleaseDates is not JSON") from exc

        state = _load_state(ctx)
        # Months that left the sync window can no longer be revised by us: forget them.
        oldest = min(r.yyyymm for r in releases[:GATS_WINDOW_MONTHS])
        processed: dict[str, str] = {k: v for k, v in state.get("processed", {}).items() if k >= oldest}
        todo = select_gats_months(releases, processed, window=GATS_WINDOW_MONTHS, cap=GATS_MAX_MONTHS_PER_RUN)
        if not todo:
            return
        # Commit the archived release calendar: no write lock is held during the long downloads below.
        ctx.checkpoint()
        descriptions = _Hs10Descriptions(ctx, headers, state)
        for rel in todo:
            complete, stop = self._collect_month(ctx, rel, headers, descriptions)
            if complete:
                processed[rel.yyyymm] = rel.timestamp
                state["processed"] = processed
            _save_state(ctx, state)
            ctx.checkpoint()
            if stop:
                break
        pending = len(select_gats_months(releases, processed, window=GATS_WINDOW_MONTHS, cap=10_000))
        if pending:
            log.info("[%s] %d month(s) still to fetch in later runs", self.key, pending)

    def _collect_month(self, ctx: CollectContext, rel: GatsRelease, headers: dict,
                       descriptions: _Hs10Descriptions) -> tuple[bool, bool]:
        """Fetch one statistical month for every partner. Returns (complete, stop_run)."""
        complete = True
        ps, pe = month_bounds(rel.year, rel.month)
        label = _period_label(rel.year, rel.month)
        partners = list(GATS_PARTNERS.items())
        for i, (code, iso3) in enumerate(partners):
            url = GATS_IMPORTS_URL.format(partner=code, year=rel.year, month=rel.month)
            try:
                # ~1 MB per partner-month for big partners: not archived (only the honey lines are kept)
                res = ctx.fetch(url, headers=headers, store=False)
                lines, n_records, warnings = parse_gats_imports(res.json(), partner=code, yyyymm=rel.yyyymm)
            except Offline:
                raise
            except (CollectorError, ValueError) as exc:
                ctx.warn(f"GATS {code} {label}: {exc}")
                complete = False
                continue
            for w in warnings:
                ctx.warn(w)
            if self._store(ctx, rel, code, iso3, url, lines, n_records, descriptions, ps, pe, label):
                complete = False        # per-HS-10 unit values deferred: the month is fetched again
            # One commit per partner-month, so the SQLite write lock is never held across downloads.
            # The month is marked processed only by `collect` once every partner is complete.
            ctx.checkpoint()
            remaining = str(_ci_get(res.headers, "x-ratelimit-remaining") or "")
            if remaining.isdigit() and int(remaining) < GATS_MIN_RATE_REMAINING:
                ctx.warn(f"api.data.gov quota nearly used up ({remaining} calls left this hour); "
                         "remaining months will be fetched on the next run")
                return complete and i == len(partners) - 1, True
        return complete, False

    def _store(self, ctx: CollectContext, rel: GatsRelease, code: str, iso3: str, url: str,
               lines: list[GatsLine], n_records: int, descriptions: _Hs10Descriptions,
               ps: date, pe: date, label: str) -> bool:
        """Store one partner-month. Returns True when per-HS-10 unit values were deferred because
        the HS-10 descriptions could not be loaded (the month must be fetched again)."""
        kg = sum(ln.kg for ln in lines)
        value = sum(ln.value for ln in lines)
        cif_total = None if any(ln.cif_total is None for ln in lines) else sum(ln.cif_total for ln in lines)
        cif_charges = None if any(ln.cif_charges is None for ln in lines) else sum(ln.cif_charges for ln in lines)
        partner_name = country_name(iso3, "en")
        no_honey = not lines
        common = dict(published_at=rel.released, source_url=url, data_status=DataStatus.PUBLISHED)
        ctx.add_trade(
            series_key=f"usda_gats|USA|{iso3}|import|0409|{rel.yyyymm}", reporter_iso3="USA",
            partner_iso3=iso3, flow=TradeFlow.IMPORT.value, currency="USD", period_start=ps, period_end=pe,
            period_label=label, frequency="M", net_weight_kg=kg, value=value, hs_code="0409",
            value_basis="customs",
            notes=("US imports for consumption of HS 0409 (Census via USDA FAS GATS). Value = customs value "
                   "(excludes freight, insurance, duty); CIF in extra."
                   + (" No HS 0409 line in this partner-month listing: recorded as zero." if no_honey else "")),
            extra={"gats_partner_code": code, "release_timestamp": rel.timestamp,
                   "quantity_field": "consumptionQuantity1", "value_field": "consumptionValue",
                   "cif_value_usd": cif_total, "cif_charges_usd": cif_charges,
                   "general_imports": {"kg": _sum_or_none(ln.general_kg for ln in lines),
                                       "value_usd": _sum_or_none(ln.general_value for ln in lines)},
                   "hs10_lines": [{"hs10": ln.hs10, "description": descriptions.get(ln.hs10), "kg": ln.kg,
                                   "value_usd": ln.value, "cif_value_usd": ln.cif_total} for ln in lines],
                   "no_honey_lines": no_honey, "partner_records": n_records},
            **common,
        )
        # Unit-value series this listing still supports (as passed to add_price); any other current
        # one of this partner-month was withdrawn by a Census revision (line dropped or now zero).
        published = {f"usda_gats|USA|{iso3}|{ln.hs10}|{rel.yyyymm}" for ln in lines if ln.kg > 0 and ln.value > 0}
        if kg > 0 and value > 0:
            published.add(f"usda_gats|USA|{iso3}|0409|{rel.yyyymm}")
        self._withdraw_unpublished(ctx, rel, code, iso3, label, published)
        if kg <= 0 or value <= 0:
            return False
        deferred = False
        base_terms = "US customs value / net kg (imports for consumption; excludes freight, insurance & duty)"
        ctx.add_price(
            series_key=f"usda_gats|USA|{iso3}|0409|{rel.yyyymm}", price_type=PriceType.IMPORT_UNIT_VALUE,
            variety=Variety.UNSPECIFIED.value, price_value=round(value / kg, 4), currency="USD", unit="kg",
            period_start=ps, period_end=pe, period_label=label, frequency="M", volume_kg=kg,
            origin_iso3=iso3, origin_label=partner_name, market_iso3="USA",
            market_location="United States (all ports)", variety_raw="HS 0409 natural honey (all lines)",
            terms=f"{base_terms}, HS 0409 total",
            notes="Derived: customs value / kilograms (Census via USDA FAS GATS)",
            extra={"gats_partner_code": code, "value_usd": value, "kg": kg,
                   "cif_unit_value_usd_per_kg": round(cif_total / kg, 4) if cif_total else None,
                   "release_timestamp": rel.timestamp},
            **common,
        )
        for ln in lines:
            if ln.kg <= 0 or ln.value <= 0:
                continue
            desc = descriptions.get(ln.hs10)
            if desc is None and descriptions.failed:
                # Colour/organic/description are not revision fields: a row stored without them now
                # would keep them missing for good. Wait for a run where the descriptions load.
                deferred = True
                continue
            color, organic = hs10_attributes(desc)
            ctx.add_price(
                series_key=f"usda_gats|USA|{iso3}|{ln.hs10}|{rel.yyyymm}", price_type=PriceType.IMPORT_UNIT_VALUE,
                variety=Variety.UNSPECIFIED.value, price_value=round(ln.value / ln.kg, 4), currency="USD",
                unit="kg", period_start=ps, period_end=pe, period_label=label, frequency="M", volume_kg=ln.kg,
                origin_iso3=iso3, origin_label=partner_name, market_iso3="USA",
                market_location="United States (all ports)", variety_raw=desc or f"HTS {ln.hs10}",
                color_grade=color, organic=organic, terms=f"{base_terms}, HTS {ln.hs10}",
                notes="Derived: customs value / kilograms for one HTS-10 line (Census via USDA FAS GATS)",
                extra={"gats_partner_code": code, "hs10": ln.hs10, "hs10_description": desc,
                       "value_usd": ln.value, "kg": ln.kg,
                       "cif_unit_value_usd_per_kg": round(ln.cif_total / ln.kg, 4) if ln.cif_total else None,
                       "release_timestamp": rel.timestamp},
                **common,
            )
        return deferred

    def _withdraw_unpublished(self, ctx: CollectContext, rel: GatsRelease, code: str, iso3: str, label: str,
                              published: set[str]) -> None:
        """Withdraw the current unit values of this partner-month that the listing no longer supports.
        They stay in the history (never deleted); the current trade row lists the remaining lines."""
        pt = PriceType.IMPORT_UNIT_VALUE.value
        prefix, suffix = f"{pt}|usda_gats|USA|{iso3}|", f"|{rel.yyyymm}"
        P = PriceObservation
        current = ctx.session.scalars(select(P.series_key).where(
            P.source_id == ctx.source.id, P.price_type == pt, P.origin_iso3 == iso3, P.period_label == label,
            P.is_current.is_(True), P.is_demo.is_(False),
        )).all()
        gone = sorted(k for k in current
                      if k.startswith(prefix) and k.endswith(suffix) and k[len(pt) + 1:] not in published)
        for key in gone:
            ctx.retire(P, key)
        if gone:
            codes = ", ".join(k[len(prefix):-len(suffix)] for k in gone)
            ctx.warn(f"GATS {code} {label}: the Census release of {rel.timestamp} no longer reports a quantity and "
                     f"value for HS {codes}; the unit value(s) published earlier are withdrawn (kept in the history)")


def _sum_or_none(values) -> float | None:
    vals = list(values)
    return None if not vals or any(v is None for v in vals) else sum(vals)


class _Hs10Descriptions:
    """HS-10 descriptions of honey lines, from GATS /commodities (~7.6 MB, not hard-coded).

    Cached in the collector state and refreshed every `GATS_HS10_REFRESH_DAYS` days, or once
    per run when an unknown 0409 code shows up. When the list cannot be loaded (`failed`), a
    warning is logged and the per-HS-10 unit values without a description are deferred to a later
    run (colour/organic are never guessed, nor stored as missing for good). A code the loaded list
    simply does not have is stored without colour."""

    def __init__(self, ctx: CollectContext, headers: dict, state: dict):
        self.ctx, self.headers, self.state = ctx, headers, state
        self.fetched_this_run = False
        self.failed = False
        fetched = parse_date(state.get("hs10_fetched"))
        if fetched is None or (date.today() - fetched).days > GATS_HS10_REFRESH_DAYS:
            self._refresh()

    def get(self, code: str) -> str | None:
        table = self.state.get("hs10", {})
        if code not in table and not self.fetched_this_run:
            self._refresh()
            table = self.state.get("hs10", {})
        return table.get(code)

    def _refresh(self) -> None:
        self.fetched_this_run = True
        try:
            doc = self.ctx.fetch(GATS_COMMODITIES_URL, headers=self.headers, store=False)
            table = parse_gats_commodities(doc.json())
        except (CollectorError, ValueError) as exc:
            self.failed = True
            self.ctx.warn(f"GATS HS-10 descriptions unavailable ({exc}); per-HS-10 unit values deferred "
                          "to a later run")
            return
        if not table:
            self.failed = True
            self.ctx.warn("GATS commodities list has no 0409 line; per-HS-10 unit values deferred to a later run")
            return
        self.state["hs10"] = table
        self.state["hs10_fetched"] = date.today().isoformat()


# =============================================================================================
# 3) USDA NASS Quick Stats - annual US honey production, colonies, yield, stocks, price
# =============================================================================================

NASS_API_URL = "https://quickstats.nass.usda.gov/api/api_GET/"
NASS_PUBLIC_URL = "https://quickstats.nass.usda.gov/"
NASS_BACKFILL_FROM = 2000
NASS_REFRESH_YEARS = 4              # later runs re-read the last years (NASS revises the prior year)
NASS_SUPPRESSED = {"(D)", "(NA)", "(Z)", "(X)", "(S)", "(L)", "(H)", ""}  # NASS suppression codes


@dataclass
class NassObservation:
    kind: str                   # production | colonies | yield_per_colony | stocks | price
    year: int
    value: float                # normalised: t | number | kg/colony | t | USD per lb
    unit: str
    raw_value: str
    raw_unit: str
    short_desc: str
    class_desc: str
    reference_period: str
    color_grade: str | None
    data_status: str
    load_date: date | None
    cv_pct: str | None


def _nass_value(raw: Any) -> float | None:
    s = str(raw or "").strip()
    if s.upper() in NASS_SUPPRESSED:
        return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def _nass_status(rec: dict) -> str:
    text = " ".join(str(rec.get(k) or "") for k in ("reference_period_desc", "short_desc", "statisticcat_desc")).upper()
    if "FORECAST" in text:
        return DataStatus.FORECAST.value
    if "PRELIMINARY" in text or "PROJECTED" in text:
        return DataStatus.PROVISIONAL.value
    return DataStatus.PUBLISHED.value


def parse_nass_rows(payload: Any) -> tuple[list[NassObservation], Counter]:
    """Classify Quick Stats HONEY rows (national, survey, totals). Returns (observations, skipped
    reasons). Exact honey `short_desc` strings are unverified, so rows are classified from
    statisticcat/unit/class/reference-period, never from short_desc."""
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        if isinstance(payload, dict) and "error" in payload:
            raise CollectorError(f"NASS error: {payload['error']}")
        raise CollectorError("NASS: unexpected response (no 'data' list)")
    out: list[NassObservation] = []
    skipped: Counter = Counter()
    seen: dict[tuple, NassObservation] = {}
    for rec in payload["data"]:
        if not isinstance(rec, dict):
            continue
        up = {k: str(rec.get(k) or "").strip().upper() for k in (
            "source_desc", "agg_level_desc", "domain_desc", "statisticcat_desc", "unit_desc", "class_desc",
            "reference_period_desc", "prodn_practice_desc", "util_practice_desc", "commodity_desc")}
        if up["commodity_desc"] not in ("HONEY", ""):
            skipped["other commodity"] += 1
            continue
        if up["source_desc"] not in ("SURVEY", "") or up["agg_level_desc"] not in ("NATIONAL", ""):
            skipped["not national survey"] += 1
            continue
        if up["domain_desc"] not in ("TOTAL", ""):
            skipped["domain not TOTAL"] += 1
            continue
        if not all(up[k] in ("", "ALL PRODUCTION PRACTICES", "ALL UTILIZATION PRACTICES")
                   for k in ("prodn_practice_desc", "util_practice_desc")):
            skipped["practice / channel split"] += 1
            continue
        try:
            year = int(str(rec.get("year") or "").strip())
        except ValueError:
            skipped["no year"] += 1
            continue
        value = _nass_value(rec.get("Value"))
        if value is None:
            skipped["suppressed / missing value"] += 1
            continue
        stat, unit, cls, ref = up["statisticcat_desc"], up["unit_desc"], up["class_desc"], up["reference_period_desc"]
        annual = ref in ("YEAR", "MARKETING YEAR", "")
        all_cls = cls in ("ALL CLASSES", "BEE COLONIES", "")
        kind = norm_value = norm_unit = None
        color = None
        if unit == "LB / COLONY" and annual and all_cls:
            kind, norm_value, norm_unit = "yield_per_colony", round(value * LB_IN_KG, 3), "kg/colony"
        elif stat == "PRODUCTION" and unit == "LB" and annual and all_cls:
            kind, norm_value, norm_unit = "production", round(value * LB_IN_KG / 1000, 3), "t"
        elif stat.startswith("INVENTORY") and unit == "COLONIES" and annual and all_cls:
            kind, norm_value, norm_unit = "colonies", value, "number"
        elif stat == "STOCKS" and unit == "LB" and all_cls:
            kind, norm_value, norm_unit = "stocks", round(value * LB_IN_KG / 1000, 3), "t"
        elif stat == "PRICE RECEIVED" and unit in ("$ / LB", "CENTS / LB") and annual:
            if cls not in ("ALL CLASSES", ""):
                color = detect_color_grade(cls)
                if color is None:
                    skipped["price for an unknown class"] += 1
                    continue
            kind, norm_unit = "price", "USD/lb"
            norm_value = round(value / 100.0, 4) if unit == "CENTS / LB" else value
        if kind is None:
            skipped[f"{stat or '?'} / {unit or '?'} / {ref or '?'}"] += 1
            continue
        obs = NassObservation(
            kind=kind, year=year, value=norm_value, unit=norm_unit, raw_value=str(rec.get("Value")),
            raw_unit=unit, short_desc=str(rec.get("short_desc") or ""), class_desc=cls, reference_period=ref,
            color_grade=color, data_status=_nass_status(rec),
            load_date=parse_date(str(rec.get("load_time") or "")[:10] or None), cv_pct=rec.get("CV (%)") or None,
        )
        ident = (kind, year, color)
        if ident in seen:
            if seen[ident].value != obs.value:
                skipped["conflicting duplicate"] += 1
            continue
        seen[ident] = obs
        out.append(obs)
    out.sort(key=lambda o: (o.kind, o.year))
    return out, skipped


class UsdaNassHoneyCollector(Collector):
    key = "usda_nass_honey"
    name = "USDA NASS – Produzione di miele USA (Quick Stats)"
    publisher = "USDA National Agricultural Statistics Service (NASS)"
    homepage = "https://quickstats.nass.usda.gov/"
    kind = SourceKind.API
    reliability = Reliability.OFFICIAL
    category = "production"
    country_iso3 = "USA"
    language = "en"
    expected_update = "Annual (Honey report, mid-March; prior year revised)"
    expected_max_age_days = 400
    terms_note = (
        "This product uses the NASS API but is not endorsed or certified by NASS. "
        "US Government public data (USDA NASS Quick Stats)."
    )
    requires_key = "usda_nass_api_key"
    schedule = {"trigger": "cron", "day": 20, "hour": 16, "minute": 10}
    order = 40

    def collect(self, ctx: CollectContext) -> None:
        api_key = self.key_value(ctx.settings)
        if not api_key:
            raise MissingKey("API key not configured (USDA_NASS_API_KEY)")
        have = ctx.session.scalar(
            select(func.count(ProductionStat.id)).where(ProductionStat.source_id == ctx.source.id)
        ) or 0
        first_year = NASS_BACKFILL_FROM if (have == 0 or ctx.force) else date.today().year - NASS_REFRESH_YEARS
        query = {"commodity_desc": "HONEY", "source_desc": "SURVEY", "agg_level_desc": "NATIONAL",
                 "year__GE": str(first_year), "format": "JSON"}
        doc = ctx.fetch(NASS_API_URL, params={"key": api_key, **query}, accept_status=(200, 400, 401, 403, 413),
                        title=f"NASS Quick Stats – HONEY national survey since {first_year}")
        body = doc.text[:300]
        if doc.status_code in (401, 403) or "unauthorized" in body.lower():
            raise CollectorError("NASS rejected the API key")
        if doc.status_code == 400:
            raise CollectorError(f"NASS returned no rows for the honey query (HTTP 400: {body})")
        if doc.status_code == 413:
            raise CollectorError("NASS query exceeds the 50,000-record limit")
        if doc.unchanged and not ctx.force:
            return
        try:
            payload = doc.json()
        except ValueError as exc:
            raise CollectorError("NASS response is not JSON") from exc
        observations, skipped = parse_nass_rows(payload)
        if not observations:
            raise CollectorError(f"NASS: no usable honey row (skipped: {dict(skipped)})")
        if skipped.get("conflicting duplicate"):
            ctx.warn(f"NASS: {skipped['conflicting duplicate']} conflicting duplicate row(s) ignored")
        log.info("[%s] skipped NASS rows: %s", self.key, dict(skipped))
        api_query = NASS_API_URL + "?" + "&".join(f"{k}={v}" for k, v in query.items())
        for o in observations:
            ps, pe = year_bounds(o.year)
            extra = {"short_desc": o.short_desc, "unit_desc": o.raw_unit, "value_as_published": o.raw_value,
                     "class_desc": o.class_desc, "reference_period_desc": o.reference_period,
                     "cv_pct": o.cv_pct, "api_query": api_query}
            common = dict(published_at=o.load_date, source_url=NASS_PUBLIC_URL, data_status=o.data_status,
                          raw_document_id=doc.raw_document_id or None)
            if o.kind == "price":
                ctx.add_price(
                    series_key=f"usda_nass|USA|national|{_slug(o.color_grade or 'all-classes')}|{o.year}",
                    price_type=PriceType.PRODUCER, variety=Variety.UNSPECIFIED.value, price_value=o.value,
                    currency="USD", unit="lb", period_start=ps, period_end=pe, period_label=str(o.year),
                    frequency="A", origin_iso3="USA", origin_label="United States", market_iso3="USA",
                    market_location="United States (national average)", color_grade=o.color_grade,
                    terms="average price received by US producers, all marketing channels, per lb",
                    notes=f"NASS Quick Stats: {o.short_desc}", extra=extra, **common,
                )
            else:
                note = f"NASS Quick Stats: {o.short_desc}"
                if o.kind == "stocks":
                    note += f" (reference period: {o.reference_period or 'as published'})"
                ctx.add_production(
                    series_key=f"usda_nass|USA|{o.kind}|{o.year}", country_iso3="USA", metric=o.kind,
                    value=o.value, unit=o.unit, period_start=ps, period_end=pe, period_label=str(o.year),
                    frequency="A", notes=note, extra=extra, **common,
                )


__all__ = [
    "PARSER_VERSION", "ReportLine", "HoneyPrice", "HoneyImportRow", "HoneyReportParse", "words_to_lines",
    "pdf_to_lines", "lines_from_text", "parse_honey_report_lines", "parse_honey_report_pdf", "parse_price_token",
    "split_price_tail", "extract_color", "describe", "parse_esmis_releases", "parse_gats_release_dates",
    "select_gats_months", "parse_gats_imports", "parse_gats_commodities", "hs10_attributes", "parse_nass_rows",
    "UsdaHoneyReportCollector", "UsdaFasGatsCollector", "UsdaNassHoneyCollector",
]
