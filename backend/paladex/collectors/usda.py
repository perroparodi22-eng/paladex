"""USDA honey data: AMS National Honey Report, FAS GATS (Census imports), NASS Quick Stats.

Three independent collectors share this module because they share USDA-specific helpers.
Endpoints, field names and the confidence of every detail are documented in
``docs/research/usda.json``. Parsers are pure functions so tests can call them directly.

``usda_honey_report``: AMS Market News *National Honey Report* (FVMHONEY, monthly PDF)
    * The keyless ESMIS API (USDA National Agricultural Library) lists releases (each one twice,
      under 'AMS' and 'AMS-SC'; deduplicated). The newest ``HONEY_BACKFILL_RELEASES`` PDFs are
      downloaded once and parsed, oldest first, so a corrected copy supersedes the original.
      ESMIS also files other AMS reports under FVMHONEY (a tomato and a watermelon report in
      2025): they are recognised from their title, remembered and ignored. ESMIS stopped at the
      Sept 30, 2025 issue (checked Nov 2026); later issues come only from the AMS URL.
    * The AMS "latest issue" URL is fetched on every run, because ESMIS may lag. Its file is
      overwritten each month, so every download is archived by hash. If ESMIS is down, this
      is the fallback.
    * Real issues (2023-2026, checked against the PDFs) print the price tables with horizontally
      compressed fonts, sometimes as two independent columns side by side (US beekeepers on the
      left, Canadian beekeepers + importers on the right), as pivot tables whose floral-source cell
      is left blank under the row it repeats, and in some months as pasted images. The PDF reader
      therefore rebuilds words from glyph positions, splits two-column page regions at their
      gutter, and the parser reads labels and floral sources from their column positions. Tables
      printed as images are reported, never guessed. The prices refer to the market month printed
      on page 1 ("HONEY MARKET FOR THE MONTH OF AUGUST 2025"), one month before the issue date.
    * The parser is versioned (``PARSER_VERSION``). Price types are kept apart:
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
import difflib
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

PARSER_VERSION = "fvmhoney/2026.11-2"

# Section keys
BEEKEEPER = "beekeeper"                     # prices paid to US beekeepers (producer prices)
CANADA = "canadian_beekeeper"               # prices paid to Canadian beekeepers (producer prices)
IMPORTER = "importer"                       # prices paid to importers, by origin (wholesale bulk)
ACE_IMPORTS = "ace_imports"                 # CBP ACE import tables by HTS-10 (kg, value)
EXPORTS = "exports"                         # US exports (not collected: not relevant, often stale)
NARRATIVE = "narrative"                     # market commentary (issues up to Dec 2024)
VISUAL = "visual"                           # weather maps / data visualisations (since 2025)
UNKNOWN = "unknown"                         # a price table we do not recognise -> warned, skipped
PRICE_SECTIONS = (BEEKEEPER, CANADA, IMPORTER)

# Price values: anything above this without "$" is cents (older issues print 190.00 / 210-225).
CENTS_THRESHOLD = 20.0
# Plausibility window for bulk honey in USD/lb; outside -> warned and skipped, never stored.
PRICE_MIN_USD_LB, PRICE_MAX_USD_LB = 0.30, 15.0
# A row whose first word starts within this many character widths of the table's label column
# (where the state / origin names are printed) names a new label; a row starting further right
# continues the label above it.
LABEL_COLUMN_TOLERANCE = 1.5
# A page region where at least this many lines sit on each side of a vertical gutter (and few
# lines straddle it) holds two independent text columns (e.g. US beekeepers | importers).
GUTTER_MIN_LINES = 3
# Share of a page covered by embedded images above which a price table without text is reported as
# "printed as an image" (the April and first May 2025 issues pasted the tables as pictures).
IMAGE_PAGE_SHARE = 0.05

_MONTH_NAMES = "January|February|March|April|May|June|July|August|September|October|November|December"
_MONTH_ABBR = "Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec"
_FULL_DATE = re.compile(rf"\b({_MONTH_NAMES})\s+(\d{{1,2}}),?\s+(\d{{4}})\b", re.I)
# "May 2026", "Feb 2025" (CBP tables print "Month: Feb 2025")
_MONTH_YEAR = re.compile(rf"\b({_MONTH_NAMES}|(?:{_MONTH_ABBR})\.?)\s+(\d{{4}})\b", re.I)
# "Volume XLV – Number 3" (page 1) and "Vol. XLV - Number 3" (running header of later pages)
_VOLUME = re.compile(r"\bVol(?:ume|\.)?\s+([IVXLCDM]+)\s*[-–—]?\s*(?:Number|No\.?)\s*(\d+)", re.I)
# "HONEY MARKET FOR THE MONTH OF FEBURARY 2025": the month the prices refer to (the issue is dated
# near the end of the following month). Spelling slips are real ("FEBURARY", "JANURARY").
_MARKET_MONTH = re.compile(r"\bhoney market for the month of\s+([A-Za-z]+)\.?,?\s+(\d{4})\b", re.I)
_CORRECTED = re.compile(r"\bcorrected\s+copy\b", re.I)
_TITLE = re.compile(r"\bnational\s+honey\s+report\b", re.I)
_MONTH_NUM = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}


def _month_number(name: str) -> int | None:
    """'February' / 'Feb' / 'Sept.' -> 2 / 2 / 9; None if not a month name."""
    n = name.strip().rstrip(".").lower()
    if n in _MONTH_NUM:
        return _MONTH_NUM[n]
    for full, num in _MONTH_NUM.items():
        if len(n) >= 3 and full.startswith(n):
            return num
    return None


_PRICE_NUM = r"\$?\s?(?:\d+(?:\.\d+)?|\.\d+)"         # "$1.91", "1.44", "$.91" (2023-24 issues)
_PRICE_TAIL = re.compile(
    rf"(?:(?<=\s)|^)(?P<low>{_PRICE_NUM})(?:\s*(?:-|–|—|to)\s*(?P<high>{_PRICE_NUM}))?\s*$"
)
_PRICE_LIKE = re.compile(r"\$\s?\.?\d|\b\d+\.\d{2}\b")
_PRICE_TOKEN = re.compile(r"^\$\s?\.?\d")
_PLACEHOLDER = re.compile(
    r"\b(no reports? issued|no report|too few (?:prices|sales|reports|trades)\b.*|"
    r"insufficient (?:data|prices|sales|trading)\b.*|"
    r"not available|no (?:sales|trading|market|prices) (?:reported|established)|none reported|n/a)\b",
    re.I,
)
_HEADER_WORDS = ("state", "floral", "color", "colour", "price", "origin", "province", "country", "source")
_ACE_NOTE = re.compile(r"^(?:\d+\.\s*)?(source|cif value|total value|note|notes|data source)\s*[:.]")
_HTS = re.compile(r"\b0409(?:\.?\d){6}\b")
_ACE_NUM = re.compile(r"^(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$|^[-–]{1,2}$")

# (section, pattern on the lower-cased line, max line length (0 = any))
_HEADINGS: list[tuple[str, re.Pattern, int]] = [
    (CANADA, re.compile(r"^prices paid to canadian beekeepers\b"), 0),
    (BEEKEEPER, re.compile(r"^prices paid to (?:u\.?\s?s\.?\s+)?beekeepers for (?:extracted|unprocessed|bulk)"), 0),
    (IMPORTER, re.compile(r"^prices paid to importers for\b"), 0),
    (NARRATIVE, re.compile(r"^colony,? honey plant,? and market conditions\b"), 80),
    (NARRATIVE, re.compile(r"^(?:honey )?market (?:conditions|commentary|summary|overview)\b"), 60),
    (ACE_IMPORTS, re.compile(r"^the import data is sourced from\b"), 0),
    (ACE_IMPORTS, re.compile(r"^(?:u\.?\s?s\.?\s+)?(?:honey\s+)?imports?\b.*\b(?:origin|country)\b"), 90),
    (ACE_IMPORTS, re.compile(r"^(?:u\.?\s?s\.?\s+)?honey imports\b"), 90),
    (EXPORTS, re.compile(r"^the export data is sourced from\b"), 0),
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
# Row labels misspelt in real issues (2024-2025). The corrected name is used for the series; the
# label as printed is kept in `extra["label_as_printed"]`. Only exact, unambiguous slips are listed.
_LABEL_TYPOS = {
    "orgeon": "OREGON", "louisana": "LOUISIANA", "flordia": "FLORIDA", "georiga": "GEORGIA",
    "uruguary": "URUGUAY", "wisconson": "WISCONSIN",
}
# Country names as CBP/AMS print them that the generic country vocabulary does not resolve.
_ORIGIN_ALIASES = {
    "burma (myanmar)": "MMR", "madagascar (malagasy)": "MDG", "north macedonia, republic of": "MKD",
    "yemen (aden)": "YEM", "dominican repuablic": "DOM", "macao (macau)": "MAC",
    "germany, fed. republic": "DEU", "germany, federal republic": "DEU", "turkiye": "TUR",
    "republic of south africa": "ZAF", "republic of yemen": "YEM", "korea, south": "KOR",
    "south korea": "KOR", "china(mainland)": "CHN", "china (mainland)": "CHN", "burma": "MMR",
    "russia": "RUS", "taiwan": "TWN", "vietnam": "VNM", "moldova": "MDA", "syria": "SYR",
    "kosovo": "XKX", "tanzania": "TZA", "laos": "LAO", "iran": "IRN", "bolivia": "BOL",
    "venezuela": "VEN", "czech republic": "CZE", "czechia": "CZE", "slovak republic": "SVK",
    "macedonia": "MKD", "north macedonia": "MKD", "macau": "MAC", "hong kong": "HKG",
    "ivory coast": "CIV", "cote d'ivoire": "CIV", "brunei": "BRN", "micronesia": "FSM",
    "congo (kinshasa)": "COD", "congo (brazzaville)": "COG", "united kingdom": "GBR",
    "united arab emirates": "ARE", "dominican republic": "DOM", "new zealand": "NZL",
}
# Floral descriptors USDA prints that the generic variety vocabulary spells differently.
_USDA_FLORAL_ALIASES = [
    (re.compile(r"\bhoney\s*dew\b", re.I), "honeydew"),
    (re.compile(r"^\s*mixed\s*$", re.I), "mixed flower"),
    (re.compile(r"\bmixed\s+flowers?\b", re.I), "mixed flower"),
    (re.compile(r"\bpolyfloral\b", re.I), "mixed flower"),
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
    """One text line of a report page (or of one column of it). Cells are separated by two or more
    spaces. Positions are in PDF points for PDF pages and in characters for text layouts."""

    page: int
    text: str
    indent: float = 0.0     # distance of the first word from the block's left edge, in characters
    x0: float = 0.0         # left edge of the first word
    char_w: float = 1.0     # typical character width (same unit as x0)
    block: int = 0          # text block id (a page column); table anchors restart in a new block
    word_x: tuple[float, ...] = ()      # left edge of every word of `text.split()`

    @property
    def cells(self) -> list[str]:
        return [c for c in re.split(r"\s{2,}", self.text.strip()) if c]

    @property
    def norm(self) -> str:
        return _collapse(self.text).lower()


@dataclass
class HoneyPrice:
    section: str                # BEEKEEPER | CANADA | IMPORTER
    label: str                  # state / province / origin country (misspellings corrected)
    origin_iso3: str
    market_iso3: str
    descriptor: str | None      # floral source as printed, colour and "organic" removed
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
    label_as_printed: str = ""
    floral_inherited: bool = False   # floral cell left blank under the row above (pivot-table layout)


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
    region: str | None = None   # Canadian province of a "QUEBEC, CANADA" row


@dataclass
class HoneyReportParse:
    issue_date: date | None = None
    volume: str | None = None
    number: int | None = None
    market_month: tuple[int, int] | None = None     # (year, month) the prices refer to
    market_month_printed: str | None = None
    corrected: bool = False                         # "Corrected Copy" banner on page 1
    title: str | None = None                        # first line of page 1
    prices: list[HoneyPrice] = field(default_factory=list)
    imports: list[HoneyImportRow] = field(default_factory=list)
    narrative: str | None = None
    sections: list[str] = field(default_factory=list)
    section_pages: dict[str, int] = field(default_factory=dict)
    section_rows: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    parser_version: str = PARSER_VERSION


class NotAHoneyReport(CollectorError):
    """The file is a valid PDF but another AMS report (ESMIS has filed tomato/watermelon reports
    under FVMHONEY)."""


# ------------------------------------------------------------------ text extraction (pdfplumber)


def _char_is_horizontal(c: dict) -> bool:
    """True for an unrotated glyph, whatever its horizontal/vertical scaling."""
    m = c.get("matrix") or (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    a, b, cc, d = (float(v) for v in m[:4])
    return a > 0 and d > 0 and abs(b) <= 0.05 * a and abs(cc) <= 0.05 * d


def chars_to_words(chars: list[dict]) -> list[dict]:
    """Rebuild words from pdfplumber chars using their own geometry.

    pdfplumber marks a glyph as not upright when its text matrix is scaled unevenly (the real
    FVMHONEY tables use horizontally compressed fonts) and then reads such glyphs as vertical text,
    which prints 'D A K O T A'. Here every unrotated glyph is horizontal: glyphs on one baseline
    form a word until a gap wider than 0.15 em, or a narrower gap holding a space glyph. (A space
    glyph alone does not split: the CBP tables draw one on top of the first digit of right-aligned
    numbers, '1 1,102'.) Rotated glyphs are dropped."""
    glyphs = [c for c in chars if c.get("text") and _char_is_horizontal(c)]
    rows: list[list[dict]] = []
    for c in sorted(glyphs, key=lambda c: (c["bottom"], c["x0"])):
        if rows and abs(c["bottom"] - rows[-1][0]["bottom"]) <= 0.6:
            rows[-1].append(c)
        else:
            rows.append([c])
    words: list[dict] = []
    for row in rows:
        row.sort(key=lambda c: c["x0"])
        spaces = [(c["x0"] + c["x1"]) / 2 for c in row if not str(c["text"]).strip()]
        cur: dict | None = None
        for c in row:
            text = str(c["text"])
            if not text.strip():
                continue
            size = float(c.get("size") or (c["bottom"] - c["top"]) or 1.0)
            em = max(size, cur["size"]) if cur is not None else size
            gap = c["x0"] - cur["x1"] if cur is not None else 0.0
            spaced = cur is not None and gap > 0.05 * em and any(cur["x1"] <= s <= c["x0"] for s in spaces)
            if cur is not None and gap <= 0.15 * em and not spaced:
                cur["text"] += text
                cur["x1"] = max(cur["x1"], float(c["x1"]))
                cur["top"] = min(cur["top"], float(c["top"]))
                cur["bottom"] = max(cur["bottom"], float(c["bottom"]))
                cur["size"] = max(cur["size"], size)
            else:
                cur = {"text": text, "x0": float(c["x0"]), "x1": float(c["x1"]), "top": float(c["top"]),
                       "bottom": float(c["bottom"]), "size": size}
                words.append(cur)
    return words


def dedupe_glyphs(chars: list[dict], tolerance: float = 1.0) -> list[dict]:
    """Drop a glyph drawn again at (almost) the same place with the same text (fake bold).
    A linear pass over glyphs sorted by text and position (pdfplumber's dedupe is much slower)."""
    out: list[dict] = []
    last: dict | None = None
    for c in sorted(chars, key=lambda c: (str(c.get("text")), round(float(c["top"]), 1), float(c["x0"]))):
        if (last is not None and c.get("text") == last.get("text") and str(c.get("text")).strip()
                and abs(float(c["top"]) - float(last["top"])) <= tolerance
                and abs(float(c["x0"]) - float(last["x0"])) <= tolerance):
            continue
        out.append(c)
        last = c
    return out


def _char_width(words: list[dict]) -> float:
    widths = sorted((w["x1"] - w["x0"]) / len(w["text"]) for w in words if len(w["text"]) >= 2)
    return widths[len(widths) // 2] if widths else 5.0


def _baseline(w: dict) -> float:
    return float(w["bottom"]) if "bottom" in w else float(w["top"])


def _rows_by_baseline(words: list[dict], tolerance: float) -> list[list[dict]]:
    rows: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (_baseline(w), w["x0"])):
        if rows and abs(_baseline(w) - _baseline(rows[-1][0])) <= tolerance:
            rows[-1].append(w)
        else:
            rows.append([w])
    return rows


def find_gutter(rows: list[list[dict]], width: float, gap: float) -> tuple[float, int, int] | None:
    """Find a vertical gutter that splits a run of rows into two independent text columns.

    `rows` are tight baseline rows (top to bottom), `gap` the widest space inside a cell. For each
    candidate x in the middle half of the page a row is X (a cell spans x), L / R (all cells on one
    side) or B (cells on both sides). A run of rows without X qualifies when it has at least
    GUTTER_MIN_LINES rows on each side and few straddling rows: two columns printed side by side
    rarely share baselines, while the columns of one table always do. Returns (x, first row, end
    row) for the run with most one-sided rows, x at the middle of the widest stretch of whitespace."""
    segs: list[list[list[float]]] = []
    for row in rows:
        ss: list[list[float]] = []
        for w in sorted(row, key=lambda w: w["x0"]):
            if ss and w["x0"] - ss[-1][1] <= gap:
                ss[-1][1] = max(ss[-1][1], w["x1"])
            else:
                ss.append([w["x0"], w["x1"]])
        segs.append(ss)
    found: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for xi in range(int(width * 0.25), int(width * 0.75) + 1):
        x = float(xi)
        cls = []
        for ss in segs:
            if any(s0 - 1.0 < x < s1 + 1.0 for s0, s1 in ss):
                cls.append("X")
            elif all(s1 <= x for _, s1 in ss):
                cls.append("L")
            elif all(s0 >= x for s0, _ in ss):
                cls.append("R")
            else:
                cls.append("B")
        i = 0
        while i < len(cls):
            if cls[i] == "X":
                i += 1
                continue
            j = i
            while j < len(cls) and cls[j] != "X":
                j += 1
            a, b = i, j
            run = cls[a:b]
            nl, nr, nb = run.count("L"), run.count("R"), run.count("B")
            if nl >= GUTTER_MIN_LINES and nr >= GUTTER_MIN_LINES and nb <= max(2, (nl + nr) // 4):
                found.setdefault((a, b), []).append((xi, nl + nr))
            i = j
    if not found:
        return None
    (a, b), hits = max(found.items(), key=lambda kv: (max(s for _, s in kv[1]), kv[0][1] - kv[0][0]))
    best = max(s for _, s in hits)
    xs = sorted(x for x, s in hits if s == best)
    groups: list[list[int]] = [[xs[0]]]
    for x in xs[1:]:
        if x == groups[-1][-1] + 1:
            groups[-1].append(x)
        else:
            groups.append([x])
    widest = max(groups, key=len)
    return (widest[0] + widest[-1]) / 2.0, a, b


def column_blocks(words: list[dict], width: float, gap: float, _depth: int = 0) -> list[list[dict]]:
    """Split a page's words into text blocks in reading order: full-width regions stay whole, a
    region printed in two columns becomes its left column followed by its right column."""
    if not words:
        return []
    rows = _rows_by_baseline(words, 0.5)        # tight: two columns are rarely on one baseline
    hit = find_gutter(rows, width, gap) if _depth < 6 else None
    if hit is None:
        return [words]
    x, a, b = hit
    band = [w for r in rows[a:b] for w in r]
    left = [w for w in band if w["x0"] + w["x1"] < 2 * x]
    right = [w for w in band if w["x0"] + w["x1"] >= 2 * x]
    above = [w for r in rows[:a] for w in r]
    below = [w for r in rows[b:] for w in r]
    return [*column_blocks(above, width, gap, _depth + 1), left, right,
            *column_blocks(below, width, gap, _depth + 1)]


def words_to_lines(words: list[dict], page: int = 1, *, y_tolerance: float = 3.0, block: int = 0,
                   char_w: float | None = None) -> list[ReportLine]:
    """Group words (dicts with text/x0/x1/top, optionally bottom) into `ReportLine`s.

    Words on the same baseline (within `y_tolerance`, less for small type) form a line. A horizontal
    gap wider than about one average character starts a new cell; it is written as two spaces.
    `indent` is the first word's distance from the block's leftmost word, in characters."""
    words = [w for w in words if str(w.get("text", "")).strip()]
    if not words:
        return []
    cw = char_w or _char_width(words)
    gap = max(2.0, 1.1 * cw)
    margin = min(w["x0"] for w in words)
    rows: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (_baseline(w), w["x0"])):
        if rows:
            first = rows[-1][0]
            tol = y_tolerance
            if "bottom" in w and "bottom" in first:
                tol = min(y_tolerance, 0.45 * min(w["bottom"] - w["top"], first["bottom"] - first["top"]))
            if abs(_baseline(w) - _baseline(first)) <= tol:
                rows[-1].append(w)
                continue
        rows.append([w])
    out: list[ReportLine] = []
    for row in rows:
        row.sort(key=lambda w: w["x0"])
        parts: list[str] = []
        xs: list[float] = []
        prev = None
        for w in row:
            if prev is not None:
                parts.append("  " if w["x0"] - prev["x1"] > gap else " ")
            tokens = str(w["text"]).split()
            step = (w["x1"] - w["x0"]) / max(1, len(str(w["text"])))
            pos = 0
            for t in tokens:
                k = str(w["text"]).find(t, pos)
                xs.append(w["x0"] + step * max(0, k))
                pos = max(0, k) + len(t)
            parts.append(" ".join(tokens))
            prev = w
        out.append(ReportLine(page, "".join(parts), round((row[0]["x0"] - margin) / cw, 1), x0=row[0]["x0"],
                              char_w=cw, block=block, word_x=tuple(xs)))
    return out


@dataclass
class PdfLayout:
    lines: list[ReportLine]
    image_share: dict[int, float]       # page -> share of the page covered by images
    pages: int


def pdf_layout(content: bytes) -> PdfLayout:
    """Extract text lines from a PDF: words rebuilt from glyph positions, columns split per page."""
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover - dependency is declared in pyproject
        raise CollectorError("pdfplumber is not installed") from exc
    try:
        lines: list[ReportLine] = []
        images: dict[int, float] = {}
        block = 0
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for pno, page in enumerate(pdf.pages, 1):
                area = float(page.width) * float(page.height) or 1.0
                images[pno] = sum(max(0.0, float(im["x1"]) - float(im["x0"])) *
                                  max(0.0, float(im["bottom"]) - float(im["top"])) for im in page.images) / area
                words = chars_to_words(dedupe_glyphs(page.chars))
                if not words:
                    continue
                cw = _char_width(words)
                for blk in column_blocks(words, float(page.width), 1.1 * cw):
                    block += 1
                    lines.extend(words_to_lines(blk, page=pno, block=block, char_w=cw))
            pages = len(pdf.pages)
        return PdfLayout(lines, images, pages)
    except CollectorError:
        raise
    except Exception as exc:  # noqa: BLE001 - pdfminer raises many exception types for bad files
        raise CollectorError(f"PDF could not be read ({type(exc).__name__}: {exc})") from exc


def pdf_to_lines(content: bytes) -> list[ReportLine]:
    """Extract text lines from a PDF (see `pdf_layout`)."""
    return pdf_layout(content).lines


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
        indent = float(len(raw) - len(raw.lstrip(" ")))
        xs = tuple(float(m.start()) for m in re.finditer(r"\S+", raw))
        out.append(ReportLine(page, raw.strip(), indent, x0=indent, char_w=1.0, block=page, word_x=xs))
    return out


# ------------------------------------------------------------------ line-level helpers (pure)


def parse_price_token(token: str) -> tuple[float, bool]:
    """'$1.90' -> (1.90, False); '1.44' -> (1.44, False); '$.91' -> (0.91, False);
    '190.00' / '210' -> (1.90/2.10, True: cents)."""
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


def _canonical_label(text: str) -> str:
    """A row label with a known misspelling corrected (case kept upper)."""
    t = _collapse(text)
    return _LABEL_TYPOS.get(t.lower().strip(" .:"), t)


def _geo(text: str, section: str) -> str | None:
    """Resolve a row label (state, province or country) for a price section."""
    t = _canonical_label(text).lower().strip(" .:")
    if section == BEEKEEPER:
        return "USA" if t in US_STATES else None
    if section == CANADA:
        return "CAN" if t in CA_PROVINCES or t == "canada" else None
    if section in (IMPORTER, ACE_IMPORTS):
        if len(t) <= 3:          # never resolve 2/3-letter tokens as country codes here
            return None
        iso = _ORIGIN_ALIASES.get(t) or lookup_iso3(t.title())
        # only countries of the reference list (a code without a name would show up as "GIN")
        return iso if iso and country_name(iso, "en") != iso else None
    return None


def ace_origin(label: str) -> tuple[str | None, str | None]:
    """CBP origin label -> (ISO3, Canadian province or None). 'QUEBEC, CANADA' -> ('CAN', 'QUEBEC');
    'Grand Total' -> ('WLD', None); unknown -> (None, None)."""
    t = _collapse(label)
    if re.fullmatch(r"(?i)(grand\s+)?total(\s+all\s+countries)?|world", t):
        return "WLD", None
    m = re.fullmatch(r"(?i)(.+?),\s*canada", t)      # "BRITISH COLUMBIA (INTERIOR), CANADA"
    if m and re.sub(r"\s*\(.*?\)", "", m.group(1)).strip().lower() in CA_PROVINCES:
        return "CAN", m.group(1).strip().upper()
    if t.lower() in CA_PROVINCES:                    # a province printed without ", CANADA"
        return "CAN", t.upper()
    return _geo(t, ACE_IMPORTS), None


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


# Colour grades as printed at the end of a descriptor ("Extra Light" alone is how several issues,
# and the HTS 0409.00.00.45 table title, abbreviate Extra Light Amber; there is no other grade it
# could mean). A colour range ("White / Extra Light") or two grades in one row is ambiguous.
_COLOR_SUFFIX = re.compile(
    r"(?P<g>water\s+white|extra\s+white|extra\s+light\s+amber|light\s+amber|dark\s+amber|"
    r"extra\s+light|white|amber|dark)(?:\s*(?:or|and|&)\s+(?P<q>lighter|whiter|darker))?",
    re.I,
)
_COLOR_TYPOS = {"whitte": "white"}
_COLORISH = re.compile(r"\b(?:white|amber|light|dark)\b", re.I)


def split_color(tokens: list[str]) -> tuple[list[str], str | None, int, str | None]:
    """Split descriptor tokens into (floral tokens, colour grade, index of the first colour token,
    problem). The colour is the trailing words of the descriptor; problem is set when the rest
    still holds colour words (two grades, a range, or text garbled in the PDF)."""
    norm = [_COLOR_TYPOS.get(t.lower(), t) for t in tokens]
    norm = [re.sub(r"^[Ll]t\.?$", "Light", t) for t in norm]
    norm = [re.sub(r"^[Ee]x\.?$", "Extra", t) for t in norm]
    grade, start = None, len(tokens)
    for k in range(min(5, len(norm)), 0, -1):
        cand = " ".join(norm[-k:])
        m = _COLOR_SUFFIX.fullmatch(cand)
        if m:
            g = _collapse(m.group("g")).lower()
            grade = "extra light amber" if g == "extra light" else g
            if m.group("q"):
                grade += " or darker" if m.group("q").lower() == "darker" else " or lighter"
            start = len(tokens) - k
            break
        if k == 1 and norm[-1].strip(".,;:()") in _COLOR_ABBR:
            grade, start = _COLOR_ABBR[norm[-1].strip(".,;:()")], len(tokens) - 1
    rest = tokens[:start]
    problem = None
    if grade is not None and (_COLORISH.search(" ".join(rest)) or
                              any(t.strip(".,;:()") in _COLOR_ABBR for t in rest)):
        problem = "more than one colour grade or a colour range"
    elif grade is None and _COLORISH.search(" ".join(rest)):
        problem = "colour grade not readable"
    return rest, grade, start, problem


def _floral(text: str) -> tuple[str | None, bool, str]:
    """Floral cell text -> (floral source or None, organic, Variety value)."""
    organic = bool(_ORGANIC.search(text))
    floral = _collapse(_ORGANIC.sub(" ", text)).strip(" ,;-") or None
    if floral and floral.lower() in ("(blank)", "blank"):
        floral = None
    if not floral:
        return None, organic, Variety.UNSPECIFIED.value
    t = floral
    for pattern, repl in _USDA_FLORAL_ALIASES:
        t = pattern.sub(repl, t)
    variety, _ = normalize_variety(t + (" organic" if organic else ""))
    return floral, organic, variety


def describe(descriptor: str) -> tuple[str | None, str | None, bool, str]:
    """Split a descriptor such as 'Organic  Mixed Flower  Light Amber' into
    (floral text or None, colour grade, organic, Variety value)."""
    rest, color, _, _ = split_color(descriptor.split())
    floral, organic, variety = _floral(" ".join(rest))
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


def _is_ace_title(norm: str) -> bool:
    if re.search(r"\d,\d{3}", norm):
        return False
    if re.match(r"^(?:natural|comb)\s+honey\b", norm) and len(norm) < 160:
        return True
    return "hts code" in norm and bool(_HTS.search(norm)) and len(norm) < 160


def _match_heading(norm: str, current: str | None) -> str | None:
    for section, pattern, max_len in _HEADINGS:
        if max_len and (len(norm) > max_len or norm.endswith(".")):
            continue
        if section == UNKNOWN and current == NARRATIVE:
            continue            # "Prices paid to ... were steady" is commentary, not a new table
        if pattern.search(norm):
            return section
    # An HTS table title outside the export section starts the import tables.
    if current not in (EXPORTS, ACE_IMPORTS) and _is_ace_title(norm) and _HTS.search(norm):
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
    """'ARGENTINA  694,418  $  1,857,205 ...' -> ('ARGENTINA', ['694,418', '1,857,205', ...]).
    The '$' printed in front of value cells is dropped."""
    tokens = []
    for t in text.split():
        if t == "$":
            continue
        tokens.append(t[1:] if t.startswith("$") and len(t) > 1 else t)
    nums: list[str] = []
    while tokens and _ACE_NUM.match(tokens[-1]):
        nums.insert(0, tokens.pop())
    return " ".join(tokens), nums


def market_month(text: str, issue: date | None) -> tuple[tuple[int, int] | None, str | None]:
    """Read 'HONEY MARKET FOR THE MONTH OF <MONTH> <YEAR>' -> ((year, month), as printed).

    A misspelt month ('FEBURARY') is accepted only when it is close to exactly one month name and
    that month is the issue month or one of the two months before it; otherwise (None, printed)."""
    m = _MARKET_MONTH.search(text)
    if not m:
        return None, None
    printed = f"{m.group(1)} {m.group(2)}"
    year, word = int(m.group(2)), m.group(1).lower()
    month = _MONTH_NUM.get(word)
    if month is None:
        close = difflib.get_close_matches(word, list(_MONTH_NUM), n=2, cutoff=0.8)
        if len(close) != 1:
            return None, printed
        month = _MONTH_NUM[close[0]]
    if issue is not None:
        lag = (issue.year - year) * 12 + issue.month - month
        if not 0 <= lag <= 2:
            return None, printed
    return (year, month), printed


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


@dataclass
class _PrevRow:
    """The previous data row of the current label group (for floral cells left blank)."""

    floral: str | None
    organic: bool
    has_floral_cell: bool
    color_x: float | None
    readable: bool = True       # False: the row was skipped, its floral source is not known


class _HoneyReportParser:
    """Line-by-line state machine. See `parse_honey_report_lines`."""

    def __init__(self) -> None:
        self.out = HoneyReportParse()
        self.section: str | None = None
        self.in_heading = False
        self.heading_lines: list[str] = []
        self.carry: tuple[str, str | None, str] | None = None   # (label, iso3, as printed)
        self.label_x: float | None = None                       # x of the label column ...
        self.label_block: int | None = None                     # ... in this text block
        self.prev: _PrevRow | None = None
        self.ace: _AceTable | None = None
        self.counts: Counter = Counter()                        # data rows per section
        self.placeholders: Counter = Counter()
        self.unknown_price_lines = 0
        self.narrative: list[list[str]] = []                    # blocks of lines
        self.ace_unknown: Counter = Counter()                   # import rows: origin not in the country list
        self.ace_misaligned: list[str] = []                     # import rows with blank / extra cells

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
        first_page = lines[0].page if lines else 1
        page1 = [ln for ln in lines if ln.page == first_page]
        if page1:
            self.out.title = _collapse(page1[0].text)[:120]
        for line in lines:
            m = _VOLUME.search(line.text)
            if m:
                self.out.volume, self.out.number = m.group(1).upper(), int(m.group(2))
                d = _FULL_DATE.search(line.text)
                if d:
                    self.out.issue_date = _date_from_match(d)
                    break
        if self.out.issue_date is None:
            for line in page1[:8]:
                d = _FULL_DATE.search(line.text)
                if d:
                    self.out.issue_date = _date_from_match(d)
                    break
        # Banner lines above the first table of page 1: market month, "Corrected Copy".
        for line in page1:
            if _match_heading(line.norm, None) in PRICE_SECTIONS:
                break
            if self.out.market_month_printed is None:
                self.out.market_month, self.out.market_month_printed = market_month(line.text, self.out.issue_date)
            if _CORRECTED.search(line.text):
                self.out.corrected = True
        if self.out.market_month_printed and self.out.market_month is None:
            self.warn(None, f"market month '{self.out.market_month_printed}' not readable "
                            f"or not consistent with the issue date")

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
        self.prev = None
        self.label_x = self.label_block = None
        if section not in self.out.sections:
            self.out.sections.append(section)
            self.out.section_pages[section] = line.page
        if section == UNKNOWN:
            self.warn(line, "unrecognised price section - rows skipped (layout change?)")
        elif section == NARRATIVE:
            self.narrative.append([_collapse(line.text)])
        elif section == ACE_IMPORTS:
            self.ace = None
            if _is_ace_title(line.norm):      # the heading is the table title itself
                self._ace_new_table(line)

    def _leave(self) -> None:
        if self.section == UNKNOWN and self.unknown_price_lines:
            self.warn(None, f"{self.unknown_price_lines} price-like line(s) skipped in an unrecognised section")
        self.unknown_price_lines = 0
        self._ace_close()

    def _finish(self) -> None:
        for s in self.out.sections:
            self.out.section_rows[s] = self.counts[s]
            if s in PRICE_SECTIONS and not self.counts[s] and not self.placeholders[s]:
                self.warn(None, f"section '{s}' found but no row could be parsed")
            if s == ACE_IMPORTS and not self.counts[s]:
                self.warn(None, "import tables found but no row could be parsed")
        if self.ace_unknown:
            names = ", ".join(sorted(self.ace_unknown))
            self.warn(None, f"import tables: {sum(self.ace_unknown.values())} row(s) of origins outside the "
                            f"country list skipped ({names[:300]})")
        if self.ace_misaligned:
            self.warn(None, f"import tables: {len(self.ace_misaligned)} row(s) whose cells do not match the "
                            f"column header skipped ({', '.join(self.ace_misaligned)[:300]})")
        paragraphs = ["\n".join(block[:1] + _reflow(block[1:])).strip() for block in self.narrative]
        # A narrative made only of headings carries no commentary.
        has_text = any(len(block) > 1 for block in self.narrative)
        self.out.narrative = "\n\n".join(p for p in paragraphs if p) if has_text else None

    # -------------------------------------------------------------- price tables
    def _split_label(self, body: str) -> tuple[str | None, str | None, int, str | None, str | None]:
        """(label, iso3, words used, label as printed, leftover glued to the label).

        A row starting in the label column always names a new label; when it is unknown, iso3 is
        None so the caller warns and skips it (it never inherits the label above)."""
        section = self.section or ""
        cells = [c for c in re.split(r"\s{2,}", body.strip()) if c]
        if not cells:
            return None, None, 0, None, None
        first = cells[0]
        iso = _geo(first, section)
        if iso:
            return _canonical_label(first), iso, len(first.split()), _collapse(first), None
        words = body.split()
        for n in range(min(4, len(words)), 0, -1):        # cells merged in the PDF: try word prefixes
            cand = " ".join(words[:n])
            iso = _geo(cand, section)
            if iso:
                return _canonical_label(cand), iso, n, cand, None
        # "CALIFORNIABuckwheat": an upper-case label glued to the floral source (Feb 2025 issue)
        m = re.fullmatch(r"([A-Z][A-Z.'&-]{2,})([A-Z][a-z][A-Za-z()'-]*)", words[0])
        if m:
            iso = _geo(m.group(1), section)
            if iso:
                return _canonical_label(m.group(1)), iso, 1, m.group(1), m.group(2)
        if _is_upper_label(first):
            # A label we do not know: US/CA region names are kept as printed (e.g. "DAKOTA");
            # an unknown origin country is returned without ISO3 so the caller can warn.
            return (_canonical_label(first), {BEEKEEPER: "USA", CANADA: "CAN"}.get(section), len(first.split()),
                    _collapse(first), None)
        # Mixed case ("Laos") or with punctuation ("KOREA, SOUTH"): still a new label, never a continuation.
        return _collapse(first), None, len(first.split()), _collapse(first), None

    def _starts_label_row(self, line: ReportLine, body: str) -> bool:
        tol = LABEL_COLUMN_TOLERANCE * line.char_w
        if self.label_x is not None and self.label_block == line.block:
            if line.x0 <= self.label_x + tol:
                self.label_x = min(self.label_x, line.x0)
                return True
            return False
        # First row of this text block: its content decides (a column may continue the table of
        # the previous column with a continuation row).
        cells = [c for c in re.split(r"\s{2,}", body.strip()) if c]
        first = cells[0] if cells else ""
        if self._split_label(body)[1] or _is_upper_label(first):
            self.label_x, self.label_block = line.x0, line.block
            return True
        return False

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
            self.prev = None
            self.warn(line, f"unparsed line in '{self.section}' table")
            return
        self.in_heading = False
        if ph is not None:
            body = line.text[: ph.start()]
        tokens = body.split()
        xs = list(line.word_x[: len(tokens)]) if len(line.word_x) >= len(tokens) else []
        label_row = bool(tokens) and self._starts_label_row(line, body)
        desc_tokens, desc_xs = tokens, xs
        if label_row:
            label, iso3, used, printed, leftover = self._split_label(body)
            if label is not None:
                self.carry = (label, iso3, printed or label)
                self.prev = None
            desc_tokens = ([leftover] if leftover else []) + tokens[used:]
            desc_xs = ([xs[0] + line.char_w * len(printed or "")] if leftover and xs else []) + xs[used:]
        if ph is not None:
            self.placeholders[self.section] += 1
            return
        if self.carry is None:
            self.warn(line, "price row without a state/origin label - skipped")
            return
        label, iso3, printed = self.carry
        if iso3 is None:
            self.warn(line, f"unknown origin '{label}' - row skipped")
            return
        if any(_PRICE_TOKEN.match(t) for t in desc_tokens):
            self.prev = _PrevRow(None, False, True, None, readable=False)
            self.warn(line, "row holds more than one price (two tables side by side?) - skipped")
            return
        # Floral source and colour first: a row skipped for its price still names the floral source
        # that the colour-only rows below it continue.
        rest, color, cstart, problem = split_color(desc_tokens)
        color_x = desc_xs[cstart] if len(desc_xs) == len(desc_tokens) and cstart < len(desc_xs) else None
        if problem or color is None:
            self.prev = _PrevRow(None, False, True, color_x, readable=False)
            self.warn(line, f"{problem or 'colour grade not recognised'} - row skipped")
            return
        inherited = False
        continues = (not label_row and not rest and self.prev is not None and self.prev.has_floral_cell
                     and color_x is not None and self.prev.color_x is not None
                     and color_x >= self.prev.color_x - LABEL_COLUMN_TOLERANCE * line.char_w)
        if rest:
            floral, organic, variety = _floral(" ".join(rest))
        elif not label_row and self.prev is not None and not self.prev.readable:
            # a colour-only row under a row that was skipped: its floral source is not known
            self.warn(line, "floral source of the row above not readable - row skipped")
            return
        elif continues:
            # Pivot-table layout: a row starting in the colour column belongs to the floral source above.
            floral, organic = self.prev.floral, self.prev.organic
            _, _, variety = _floral(" ".join(filter(None, [floral, "organic" if organic else ""])))
            inherited = True
        else:
            floral, organic, variety = None, False, Variety.UNSPECIFIED.value
        self.prev = _PrevRow(floral, organic, bool(rest) or inherited, color_x)
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
        self.counts[self.section] += 1
        self.out.prices.append(HoneyPrice(
            section=self.section, label=_collapse(label), origin_iso3=iso3,
            market_iso3="CAN" if self.section == CANADA else "USA",
            descriptor=floral, color_grade=color, organic=organic, variety=variety,
            low=low if high is not None else None, high=high, value=value, currency=currency,
            printed_in_cents=cents, terms=heading_terms(self.section, heading), heading=_collapse(heading)[:500],
            page=line.page, raw_line=_collapse(line.text), label_as_printed=printed, floral_inherited=inherited,
        ))

    def _label_only(self, line: ReportLine) -> bool:
        """A line holding only a group label (e.g. 'CALIFORNIA' above its rows)."""
        text = _collapse(line.text)
        if re.search(r"[,:;]", text) or text.endswith("."):
            return False
        same_block = self.label_x is not None and self.label_block == line.block
        if same_block and line.x0 > self.label_x + LABEL_COLUMN_TOLERANCE * line.char_w:
            return False
        iso = _geo(text, self.section or "")
        if iso or (not self.in_heading and _is_upper_label(text)):
            self.carry = (_canonical_label(text), iso if iso else {BEEKEEPER: "USA", CANADA: "CAN"}.get(self.section),
                          text)
            self.prev = None
            if not same_block:
                self.label_x, self.label_block = line.x0, line.block
            return True
        return False

    # -------------------------------------------------------------- CBP ACE import tables
    def _ace_new_table(self, line: ReportLine) -> None:
        self._ace_close()
        title = _collapse(line.text)
        color, _ = extract_color(re.sub(r"\(.*?\)", " ", title))
        if color is None and re.search(r"\bextra\s+light\b", title, re.I):
            color = "extra light amber"     # "Natural Honey, Not For Retail Sale, Extra Light (HTS 0409000045)"
        self.ace = _AceTable(title=title, hts=_hts_code(title), color=color,
                             organic=bool(_ORGANIC.search(title)), page=line.page)
        my = _MONTH_YEAR.search(title)
        if my:
            self.ace.month = (int(my.group(2)), _month_number(my.group(1)))

    def _ace_close(self) -> None:
        self.ace = None

    def _ace_line(self, line: ReportLine) -> None:
        norm, text = line.norm, line.text
        t = self.ace
        if t is not None and not t.rows and not t.hts and _hts_code(text) and not t.fields:
            t.hts = _hts_code(text)                        # title wrapped onto a second line
            t.title = _collapse(t.title + " " + text)
            if t.color is None:
                t.color, _ = extract_color(re.sub(r"\(.*?\)", " ", t.title))
            return
        if _is_ace_title(norm):
            self._ace_new_table(line)
            return
        if _ACE_NOTE.match(norm) or norm in ("country of origin", "country"):
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
            if t is not None and not _PLACEHOLDER.search(norm) and _month_number(norm) is None:
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
            # a blank cell (no '-') or a stray number: the columns cannot be matched unambiguously
            self.ace_misaligned.append(f"p.{line.page} {_collapse(label)} ({len(nums)}/{len(t.fields)} cells)")
            return
        label = _collapse(label)
        iso3, region = ace_origin(label)
        if not iso3:
            self.ace_unknown[label] += 1
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
            total_value=month_vals.get("total"), ytd=ytd, page=line.page, raw_line=_collapse(text), region=region,
        ))

    def _ace_month(self, t: _AceTable, text: str) -> None:
        my = _MONTH_YEAR.search(text)
        if my and t.month is None:
            num = _month_number(my.group(1))
            if num:
                t.month = (int(my.group(2)), num)

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


def group_warnings(warnings: list[str]) -> list[str]:
    """Merge parser warnings that differ only by page and row ('p.1: colour grade not readable - row
    skipped [Valley Extra Light / Light $2.80]') into one line per message with a few examples, so
    one issue cannot fill the run's warning list."""
    groups: dict[str, list[tuple[str, str | None]]] = {}
    for w in warnings:
        m = re.fullmatch(r"(?:p\.(\d+): )?(.*?)(?: \[(.*)\])?", w, re.S)
        page, msg, snippet = m.groups() if m else (None, w, None)
        example = (f"p.{page} [{snippet}]" if page else f"[{snippet}]") if snippet else None
        groups.setdefault(msg, []).append((w, example))
    out: list[str] = []
    for msg, items in groups.items():
        if len(items) == 1:
            out.append(items[0][0])
            continue
        examples = [e for _, e in items if e]
        more = f", e.g. {'; '.join(examples[:3])}" if examples else ""
        out.append(f"{msg} ({len(items)}x{more})")
    return out


def parse_honey_report_lines(lines: list[ReportLine]) -> HoneyReportParse:
    """Parse the National Honey Report from text lines (pure; no I/O).

    Returns prices (producer / wholesale bulk, USD per lb as published), CBP import rows,
    the market narrative (if the issue has one), the issue date, the market month and warnings."""
    return _HoneyReportParser().run(lines)


def parse_honey_report_pdf(content: bytes) -> HoneyReportParse:
    """Parse a National Honey Report PDF. Raises CollectorError if the file is unusable and
    NotAHoneyReport if it is another report."""
    if not content.lstrip()[:5].startswith(b"%PDF"):
        raise CollectorError("downloaded file is not a PDF")
    layout = pdf_layout(content)
    if not layout.lines:
        raise CollectorError("PDF contains no extractable text (scanned image?)")
    first_page = [ln for ln in layout.lines if ln.page == layout.lines[0].page]
    if not any(_TITLE.search(ln.text) for ln in first_page[:12]):
        raise NotAHoneyReport(f"not a National Honey Report (page 1 starts with '{first_page[0].text[:60]}')")
    parsed = parse_honey_report_lines(layout.lines)
    if not any(s in parsed.sections for s in (*PRICE_SECTIONS, ACE_IMPORTS)):
        raise CollectorError("no known National Honey Report section found (layout changed?)")
    # A price section without rows on a page carrying large images: the table is a picture.
    for section in PRICE_SECTIONS:
        page = parsed.section_pages.get(section)
        generic = f"section '{section}' found but no row could be parsed"
        if page is None or generic not in parsed.warnings:
            continue
        if layout.image_share.get(page, 0.0) >= IMAGE_PAGE_SHARE:
            parsed.warnings = [w for w in parsed.warnings if w != generic]
            parsed.warnings.append(f"p.{page}: the '{section}' price table is printed as an image in this PDF "
                                   "(not machine-readable) - no prices taken from it")
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
    """Parse an ESMIS `/api/v1/release/findBy...` page. Newest first; a release listed twice
    (ESMIS lists most FVMHONEY releases under both 'AMS' and 'AMS-SC') is kept once."""
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise CollectorError("ESMIS: unexpected response (no 'results' list)")
    out: list[EsmisRelease] = []
    warnings: list[str] = []
    seen: set[str] = set()
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
        rel = EsmisRelease(
            release_id=str(item.get("id") or ""), title=str(item.get("title") or "National Honey Report"),
            release_date=rd, pdf_url=pdfs[0] if pdfs else None, files=files,
        )
        ident = rel.release_id or rel.pdf_url or f"{rd.isoformat()}|{','.join(files)}"
        if ident in seen:
            continue
        seen.add(ident)
        out.append(rel)
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
ESMIS_MAX_PAGES = 2                 # ESMIS pages read for the first backfill (25 rows per page)
ESMIS_EMPTY_RETRIES = 3             # ESMIS sometimes answers with an empty list; retry, 5 s apart
REPORT_DATE_MATCH_DAYS = 4          # an AMS issue within this many days of an ESMIS release = same issue
# A customs unit value says nothing about the bulk market on tiny consignments (samples, a few jars:
# the Sep 2026 ACE table prints 61 kg from Ontario for $69,649), so a unit value is derived only from
# at least this much. Same threshold as Comtrade, Eurostat and the official trade collectors.
ACE_MIN_UNIT_VALUE_KG = 1_000.0


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
    expected_update = "Mensile (numero datato verso la fine del mese)"
    expected_update_en = "Monthly (issue dated near the end of the month)"
    expected_max_age_days = 40
    terms_note = (
        "US Government work (public domain, 17 USC 105). Cite 'USDA AMS Market News, National Honey "
        "Report'. Back issues via USDA National Agricultural Library ESMIS. Prices are published per "
        "pound (USD) for the market month printed on page 1; per-kg values are converted."
    )
    # Around month end (issue date) and the first days of the next month, morning and evening (Rome).
    schedule = {"trigger": "cron", "day": "1-5,25-31", "hour": "8,22", "minute": 40}
    order = 20

    def collect(self, ctx: CollectContext) -> None:
        errors: list[CollectorError] = []
        successes = 0
        state = _load_state(ctx)
        not_honey: dict[str, str] = state.setdefault("not_fvmhoney", {})

        # 1) ESMIS archive: download the newest releases not yet parsed (oldest first, so a corrected
        #    copy supersedes the original), then register every listed release.
        releases: list[EsmisRelease] = []
        listing_complete = False
        try:
            releases, listing_complete = self._esmis_releases(ctx, state)
            successes += 1
        except CollectorError as exc:
            errors.append(exc)
            ctx.warn(f"ESMIS archive unavailable ({exc}); using the AMS latest issue only")

        wanted = [r for r in releases[:HONEY_BACKFILL_RELEASES] if r.pdf_url]
        pending = 0
        for rel in sorted(wanted, key=lambda r: r.release_date):
            key = rel.release_date.isoformat()
            if rel.pdf_url in not_honey and not ctx.force:
                continue
            report = self._report(ctx, key)
            if report is not None and report.raw_document_id and not ctx.force:
                continue
            try:
                self._process_pdf(ctx, url=rel.pdf_url, report_key=key,
                                  title=f"{rel.title} – {_long_date(rel.release_date)}", release_date=rel.release_date)
                successes += 1
            except NotAHoneyReport as exc:
                not_honey[rel.pdf_url] = str(exc)[:200]
                _save_state(ctx, state)
                ctx.warn(f"ESMIS release of {key} ({rel.pdf_url}) is filed under FVMHONEY but {exc}; ignored")
                ctx.checkpoint()
            except CollectorError as exc:
                pending += 1
                errors.append(exc)
                ctx.warn(f"Issue of {key} ({rel.pdf_url}) not processed: {exc}")
        if releases and listing_complete and not pending and not state.get("esmis_backfill_done"):
            state["esmis_backfill_done"] = True         # later runs read only the first ESMIS page
            _save_state(ctx, state)

        for rel in releases:
            if rel.pdf_url in not_honey:
                continue
            ctx.add_report(
                report_key=rel.release_date.isoformat(),
                title=f"{rel.title} – {_long_date(rel.release_date)}",
                url=rel.pdf_url or (rel.files[0] if rel.files else ESMIS_PUBLICATION_URL),
                published_at=rel.release_date,
            )
        ctx.checkpoint()

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
    def _esmis_page(self, ctx: CollectContext, page: int) -> tuple[list[EsmisRelease], int]:
        doc = ctx.fetch(ESMIS_FVMHONEY_URL, params={"page": page}, headers={"Accept": "application/json"},
                        title=f"ESMIS – National Honey Report releases (page {page})")
        try:
            payload = doc.json()
        except ValueError as exc:
            raise CollectorError("ESMIS response is not JSON") from exc
        releases, warnings = parse_esmis_releases(payload)
        for w in warnings:
            ctx.warn(w)
        pager = payload.get("pager") if isinstance(payload, dict) else None
        total = int(pager.get("total_pages") or 1) if isinstance(pager, dict) else 1
        return releases, total

    def _esmis_releases(self, ctx: CollectContext, state: dict) -> tuple[list[EsmisRelease], bool]:
        """(releases newest first, True when every page the backfill needs was read)."""
        releases: list[EsmisRelease] = []
        total_pages = 1
        for attempt in range(ESMIS_EMPTY_RETRIES + 1):
            releases, total_pages = self._esmis_page(ctx, 0)
            if releases:
                break
            if attempt < ESMIS_EMPTY_RETRIES:
                ctx.checkpoint()        # do not hold the write lock (archived response) while waiting
                time.sleep(5)
        if not releases:
            ctx.warn("ESMIS returned an empty National Honey Report release list (transient?)")
            return [], False
        # First backfill (or a forced run): read further pages until the backfill window is covered.
        page, complete = 1, True
        while (len(releases) < HONEY_BACKFILL_RELEASES and page < min(total_pages, ESMIS_MAX_PAGES)
               and (ctx.force or not state.get("esmis_backfill_done"))):
            try:
                more, _ = self._esmis_page(ctx, page)
            except CollectorError as exc:
                ctx.warn(f"ESMIS page {page} unavailable ({exc}); older issues follow on a later run")
                complete = False
                break
            known = {r.release_id or r.pdf_url for r in releases}
            releases += [r for r in more if (r.release_id or r.pdf_url) not in known]
            page += 1
        releases.sort(key=lambda r: r.release_date, reverse=True)
        return releases, complete

    def _report(self, ctx: CollectContext, report_key: str) -> Report | None:
        return ctx.session.scalars(
            select(Report).where(Report.source_id == ctx.source.id, Report.report_key == report_key)
        ).first()

    def _report_with_file(self, ctx: CollectContext, raw_document_id: int) -> Report | None:
        return ctx.session.scalars(
            select(Report).where(Report.source_id == ctx.source.id, Report.raw_document_id == raw_document_id)
            .order_by(Report.id)
        ).first()

    def _already_parsed(self, ctx: CollectContext, raw_document_id: int) -> bool:
        return ctx.session.scalar(
            select(func.count(Report.id)).where(Report.source_id == ctx.source.id,
                                                Report.raw_document_id == raw_document_id)
        ) > 0

    @staticmethod
    def _issue_title(parsed: HoneyReportParse, issue: date) -> str:
        return f"National Honey Report – {_long_date(issue)}" + (" (corrected copy)" if parsed.corrected else "")

    @staticmethod
    def _market_label(parsed: HoneyReportParse) -> str | None:
        return _period_label(*parsed.market_month) if parsed.market_month else None

    def _process_pdf(self, ctx: CollectContext, *, url: str, report_key: str, title: str,
                     release_date: date) -> None:
        doc = ctx.fetch(url, title=title, published_at=release_date)
        if self._already_parsed(ctx, doc.raw_document_id) and not ctx.force:
            # same bytes already parsed under another report (e.g. ESMIS re-listed the same file)
            prev = self._report_with_file(ctx, doc.raw_document_id)
            ctx.add_report(report_key=report_key, title=prev.title if prev else title, url=url,
                           published_at=release_date, period_label=prev.period_label if prev else None,
                           raw_document_id=doc.raw_document_id)
            return
        parsed = parse_honey_report_pdf(doc.content)
        issue = parsed.issue_date or release_date
        if parsed.issue_date and abs((parsed.issue_date - release_date).days) > 31:
            ctx.warn(f"{title}: issue date printed in the PDF ({parsed.issue_date}) differs from the "
                     f"ESMIS release date ({release_date}); using the printed date")
        title = self._issue_title(parsed, issue)
        self._store(ctx, parsed, issue, title=title, source_url=doc.url, raw_document_id=doc.raw_document_id)
        report, _ = ctx.add_report(report_key=report_key, title=title, url=url, published_at=release_date,
                                   period_label=self._market_label(parsed),
                                   raw_document_id=doc.raw_document_id, narrative=parsed.narrative)
        if report.period_label is None and parsed.market_month:
            report.period_label = self._market_label(parsed)        # late metadata: filled, never changed
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
        title = self._issue_title(parsed, issue)
        report, _ = ctx.add_report(report_key=report_key, title=title, url=doc.url, published_at=issue,
                                   period_label=self._market_label(parsed),
                                   raw_document_id=doc.raw_document_id, narrative=parsed.narrative)
        if report.period_label is None and parsed.market_month:
            report.period_label = self._market_label(parsed)
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
        for w in group_warnings(parsed.warnings):
            ctx.warn(f"{title}: {w}")
        stored: set[str] = set()
        prices = parsed.prices
        if prices and parsed.market_month is None:
            ctx.warn(f"{title}: the market month ('Honey market for the month of ...') is missing or not "
                     f"readable; {len(prices)} price(s) skipped rather than dated by guess")
            prices = []
        if prices:
            ps, pe = month_bounds(*parsed.market_month)
            label = _period_label(*parsed.market_month)
        seen: Counter = Counter()
        for p in prices:
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
                       "issue_date": issue.isoformat(), "label_as_printed": p.label_as_printed or p.label,
                       "market_month_as_printed": parsed.market_month_printed,
                       "floral_source_from_row_above": p.floral_inherited,
                       "corrected_copy": parsed.corrected, **provenance},
            )
            stored.add(f"{price_type.value}|{series_key}")
        for r in parsed.imports:
            if (r.year, r.month) > (issue.year, issue.month):
                ctx.warn(f"{title}: import table month {r.year}-{r.month:02d} is after the issue date - skipped")
                continue
            if not r.kilograms or not r.value or r.kilograms < ACE_MIN_UNIT_VALUE_KG or r.value <= 0:
                continue
            ps_i, pe_i = month_bounds(r.year, r.month)
            m_label = _period_label(r.year, r.month)
            line_id = r.hts_code or _slug(r.table_title)
            place = f"|{_slug(r.region)}" if r.region else ""
            terms = "US customs value / net kg (CBP ACE; excludes freight, insurance & duty)"
            if r.hts_code:
                terms += f", HTS {r.hts_code}"
            origin_label = country_name(r.origin_iso3, "en") if r.origin_iso3 != "WLD" else "All origins"
            if r.region:
                origin_label = f"{origin_label} ({r.region.title()})"
            series_key = f"usda_fvmhoney|ace|{line_id}|{r.origin_iso3}{place}|{m_label}"
            ctx.add_price(
                series_key=series_key,
                price_type=PriceType.IMPORT_UNIT_VALUE, variety=Variety.UNSPECIFIED.value,
                price_value=round(r.value / r.kilograms, 4), currency="USD", unit="kg",
                period_start=ps_i, period_end=pe_i, period_label=m_label, frequency="M",
                volume_kg=r.kilograms, published_at=issue, source_url=source_url,
                raw_document_id=raw_document_id or None, origin_iso3=r.origin_iso3,
                origin_label=origin_label,
                market_iso3="USA", market_location="United States (port of entry)", variety_raw=r.table_title,
                color_grade=r.color_grade, organic=r.organic, terms=terms, data_status=DataStatus.PUBLISHED,
                notes=f"{title}, p.{r.page}: derived unit value = customs value / kilograms",
                extra={"parser_version": parsed.parser_version, "page": r.page, "raw_line": r.raw_line,
                       "hts_code": r.hts_code, "kilograms": r.kilograms, "value_usd": r.value,
                       "cif_value_usd": r.cif_value, "total_value_usd": r.total_value,
                       "landed_unit_value_usd_per_kg": round(r.total_value / r.kilograms, 4)
                       if r.total_value else None, "origin_as_printed": r.origin_label,
                       "year_to_date": r.ytd, "issue_date": issue.isoformat(), **provenance},
            )
            stored.add(f"{PriceType.IMPORT_UNIT_VALUE.value}|{series_key}")
        if parsed.corrected:
            self._withdraw_superseded(ctx, issue, raw_document_id, stored, title)

    def _withdraw_superseded(self, ctx: CollectContext, issue: date, raw_document_id: int, stored: set[str],
                             title: str) -> None:
        """A corrected copy replaces the earlier copy of the same issue: rows that only the earlier copy
        published (e.g. prices filed under a wrong month heading) stop being current (kept in history)."""
        P = PriceObservation
        earlier = set(ctx.session.scalars(select(P.series_key).where(
            P.source_id == ctx.source.id, P.published_at == issue, P.is_current.is_(True), P.is_demo.is_(False),
            P.raw_document_id.is_not(None), P.raw_document_id != raw_document_id,
        )).all())
        gone = sorted(earlier - stored)
        for key in gone:
            ctx.retire(P, key)
        if gone:
            ctx.warn(f"{title}: corrected copy - {len(gone)} row(s) published only by the earlier copy of this "
                     "issue were withdrawn (kept in the history)")


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
    expected_update = "Mensile, circa 5-6 settimane dopo il mese (pubblicazione Census FT-900)"
    expected_update_en = "Monthly, about 5-6 weeks after the month (Census FT-900 release)"
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
    expected_update = "Annuale (rapporto Honey a metà marzo; anno precedente rivisto)"
    expected_update_en = "Annual (Honey report, mid-March; prior year revised)"
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
    "PARSER_VERSION", "ReportLine", "HoneyPrice", "HoneyImportRow", "HoneyReportParse", "NotAHoneyReport",
    "words_to_lines", "chars_to_words", "dedupe_glyphs", "find_gutter", "column_blocks", "pdf_layout",
    "pdf_to_lines", "lines_from_text", "parse_honey_report_lines", "parse_honey_report_pdf", "parse_price_token",
    "split_price_tail", "split_color", "market_month", "ace_origin", "group_warnings", "extract_color", "describe",
    "parse_esmis_releases", "parse_gats_release_dates",
    "select_gats_months", "parse_gats_imports", "parse_gats_commodities", "hs10_attributes", "parse_nass_rows",
    "UsdaHoneyReportCollector", "UsdaFasGatsCollector", "UsdaNassHoneyCollector",
]
