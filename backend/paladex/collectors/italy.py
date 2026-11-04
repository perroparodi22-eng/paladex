"""Italian honey price sources (four collectors, one Source row each).

* ``cciaa_cuneo_miele``  Camera di Commercio di Cuneo, monthly "Miele" wholesale price list
  (cuneoprezzi.it). Bulk drums ("fusto da 3 q.li") and 25 kg buckets, min/max EUR/kg.
* ``ismea_miele``        ISMEA Mercati average ORIGIN (producer) prices: weekly by variety
  (IDPagina 11024) and monthly by product (IDPagina 11025).
* ``onm_informamiele``   Osservatorio Nazionale Miele (informamiele.it): the monthly
  "rilevazione mensile" bulletins (stored as Reports, with the market paragraphs as narrative;
  EUR/kg ranges are extracted only when unambiguous and stored as *provisional*), plus the
  tables of the Annual Report PDF.
* ``cciaa_siena_miele``  Camera di Commercio di Arezzo-Siena weekly price list (PDF): honey
  lines only.

Source research: docs/research/italy.json. IMPORTANT: none of these hosts could be reached
while this module was written (the sandbox and the researcher were both blocked). URL
templates come from indexed real URLs, but page and table layouts are partly RECONSTRUCTED
from documentation and search snippets. For this reason every parser checks the structure it
relies on and raises `SchemaDrift` (a `CollectorError`, so the run is marked *failed* with a
clear message) instead of guessing. Whole documents are always archived by `ctx.fetch()`, so
they can be re-parsed with `--force` once a parser has been adjusted.

Conventions decided here (documented because the sources do not state them):

* Cuneo: the survey month is the month named in "mese di <mese> <anno>" when present,
  otherwise the month of the list date ("rilevazione mensile del 30 settembre 2023" ->
  2023-09). `published_at` is the list date. Drum (``fusto``) and bucket (``secchio``) rows
  are both WHOLESALE_BULK; `extra["packaging_code"]` / `extra["drum"]` let the UI keep drums
  only. Price unit is taken from the "U.M." column ("kg" or "q.le" -> unit "q").
* Cuneo back-fill: the yearly averages PDF ("Miele - medie YYYY") of the previous
  `CUNEO_BACKFILL_YEARS` complete years is read until a copy fetched on or after 1 April of
  the following year is held (last year's PDF is still being completed in January), then
  left alone (again only with --force). A monthly
  average is stored only where no monthly list observation exists for that item/month (gap
  filling), under its own series key and with `extra["statistic"]` = "monthly_average" or
  "annual_average", because an average is not a min-max quotation.
* ISMEA weekly period strings "YYYY-M-W" are read as year, month, week-of-month, with an
  ISO-8601-like rule: week W of month M is the W-th Monday-to-Sunday week whose THURSDAY
  falls in month M (just as an ISO week belongs to the year that holds its Thursday). The raw
  string is kept in `extra["period_raw"]` and the label is "YYYY-MM-S<W>" (S = settimana).
  The convention is NOT confirmed by ISMEA.
* ONM text extraction: only sentences of the market section that carry a bulk-market context
  word ("all'ingrosso", "fusto/fusti", "sfuso"), and only ranges written with an explicit
  "EUR/kg" unit ("tra 4 e 4,5 €/kg", "5,00-6,50 €/kg"). Inside a segment of a sentence
  (split at ";", "mentre", "invece") variety mentions and price mentions must alternate
  one-to-one, otherwise the segment is ambiguous and skipped. Single values ("attorno ai
  4,00 €/kg") are never stored. Packaging, organic and origin words belong to the pair whose
  own phrase holds them, to a parenthetical right after it ("6,5-6,7 €/kg (latta)"), or to
  the next pair when set off by a comma and leading into it (", in latta il castagno"); a
  qualifier that could belong to two pairs skips both. The origin is read only in the
  variety's own clause: a foreign honey named as context ("complice la concorrenza del miele
  ucraino, il millefiori ...") skips the pair instead of labelling it. Every extracted price
  is `provisional` and carries the note "estratto dal testo del bollettino" plus the sentence
  it came from.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from itertools import pairwise
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup
from sqlalchemy import select

from ..enums import DataStatus, PriceType, Reliability, SourceKind, Variety
from ..models import AppSetting, PriceObservation, RawDocument
from ..reference.countries import lookup_iso3
from ..reference.varieties import normalize_variety
from ..services.ingest import KG_PER_UNIT
from .base import (
    CollectContext,
    Collector,
    CollectorError,
    FetchResult,
    Offline,
    month_bounds,
    parse_date,
    year_bounds,
)

log = logging.getLogger(__name__)

CURRENCY = "EUR"
MARKET_ISO3 = "ITA"
# Plausibility window for an Italian honey price expressed per kg. Bulk drums trade around
# 3-12 EUR/kg and special monofloral honeys higher; a value outside this window almost
# certainly means a unit or column mix-up (e.g. a per-quintal price in a "kg" column).
MIN_PLAUSIBLE_PER_KG = 0.5
MAX_PLAUSIBLE_PER_KG = 60.0
TEXT_EXTRACT_NOTE = "estratto dal testo del bollettino"


def _today() -> date:
    """Indirection so tests can pin "today" (back-fill year ranges, archive years)."""
    return date.today()


class SchemaDrift(CollectorError):
    """The document no longer has the structure the parser relies on. Raised instead of
    storing numbers that could be wrong; the message says what was expected."""


# ===========================================================================
# Text helpers: cleaning, Italian dates and numbers, units
# ===========================================================================


def _clean(s: str | None) -> str:
    """NFKC, non-breaking spaces and typographic apostrophes normalised, whitespace collapsed."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", str(s)).replace("\xa0", " ")
    s = s.replace("’", "'").replace("‘", "'").replace("`", "'")
    return re.sub(r"\s+", " ", s).strip()


def _fold(s: str | None) -> str:
    """Lower-case ASCII version for keyword matching (accents and symbols such as € dropped)."""
    s = unicodedata.normalize("NFKD", _clean(s)).encode("ascii", "ignore").decode("ascii")
    return s.lower()


def _slug(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _fold(s)).strip("-")[:80] or "x"


def _soup(content: bytes | str) -> BeautifulSoup:
    return BeautifulSoup(content, "lxml")


def _decode(content: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


IT_MONTHS: dict[str, int] = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6,
    "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}
_IT_MONTH_ABBR: dict[str, int] = {
    "gen": 1, "feb": 2, "mar": 3, "apr": 4, "mag": 5, "giu": 6, "lug": 7, "ago": 8,
    "set": 9, "sett": 9, "ott": 10, "nov": 11, "dic": 12,
}
_MONTH_ALT = "|".join(IT_MONTHS)
_DATE_WORDS_RE = re.compile(rf"\b(\d{{1,2}})\s*(?:°|º)?\s+({_MONTH_ALT})\s+(\d{{4}})\b", re.I)
_DATE_ISO_RE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_DATE_NUM_RE = re.compile(r"(?<!\d)(\d{1,2})[./_-](\d{1,2})[./_-](\d{4})(?!\d)")
_MONTH_YEAR_RE = re.compile(rf"\b({_MONTH_ALT})[\s_-]+(\d{{4}})\b", re.I)


def it_month_number(token: str | None) -> int | None:
    """'settembre' / 'Set' / 'sett.' -> 9. None when the token is not an Italian month."""
    t = _fold(token).strip(" .")
    return IT_MONTHS.get(t) or _IT_MONTH_ABBR.get(t)


def _safe_date(y, m, d) -> date | None:
    try:
        return date(int(y), int(m), int(d))
    except (TypeError, ValueError):
        return None


def parse_it_date(text: str | None) -> date | None:
    """First date found in Italian text: '30 settembre 2023', '1° ottobre 2026',
    '08.04.2026', '08_04_2026', '30/09/2023' or ISO '2026-10-20'. None if there is none."""
    t = _clean(text)
    if not t:
        return None
    m = _DATE_WORDS_RE.search(t)
    if m:
        d = _safe_date(m.group(3), IT_MONTHS[m.group(2).lower()], m.group(1))
        if d:
            return d
    m = _DATE_ISO_RE.search(t)
    if m:
        d = _safe_date(m.group(1), m.group(2), m.group(3))
        if d:
            return d
    for m in _DATE_NUM_RE.finditer(t):
        d = _safe_date(m.group(3), m.group(2), m.group(1))
        if d:
            return d
    return None


def parse_it_month_year(text: str | None) -> tuple[int, int] | None:
    """'Agosto 2026' / 'agosto-2026' -> (2026, 8)."""
    m = _MONTH_YEAR_RE.search(_clean(text))
    if not m:
        return None
    return int(m.group(2)), IT_MONTHS[m.group(1).lower()]


# Cell contents that mean "no quotation" (never zero: no transactions were recorded).
MISSING_TOKENS = {
    "", "-", "--", "–", "—", "/", "*", "nd", "n.d.", "n.d", "n.q.", "nq", "n.q", "s.q.", "sq",
    "n.c.", "nc", "np", "n.p.", "non quotato", "non disponibile",
}
_TRAILING_UNIT_RE = re.compile(
    r"\s*(?:€|eur|euro)\s*(?:/\s*|al\s+|per\s+)?(?:kg|q\.?\s?li|q\.?le|ql|q|quintale|t)?\.?\s*$", re.I
)
_NUMBER_RE = re.compile(r"[+-]?(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?|[+-]?\d+\.\d+")


def parse_it_number(raw: str | None) -> float | None:
    """Italian number -> float. '7,50' 7.5 | '1.234,56' 1234.56 | '8,00 €/Kg' 8.0 |
    '€ 7,50' 7.5 | '0,0%' 0.0. Missing markers ('nd', '-', 'n.q.', '') -> None.
    Anything else raises ValueError (callers warn and skip that cell)."""
    s = _clean(raw)
    s = _TRAILING_UNIT_RE.sub("", s)
    s = re.sub(r"^(?:€|eur|euro)\s*", "", s, flags=re.I)
    s = s.rstrip("%").strip()
    if s.lower() in MISSING_TOKENS:
        return None
    if not _NUMBER_RE.fullmatch(s):
        raise ValueError(f"not a number: {raw!r}")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"[+-]?\d{1,3}(?:\.\d{3})+", s):
        s = s.replace(".", "")          # '1.500' = one thousand five hundred (Italian)
    return float(s)


def normalize_unit(raw: str | None) -> str | None:
    """Unit-of-measure cell -> 'kg' | 'q' (quintale = 100 kg) | 't'. None when unknown."""
    t = _fold(raw).strip(" .")
    t = re.sub(r"^(?:eur|euro)?\s*/\s*", "", t).strip(" .")
    if re.fullmatch(r"kg|kgs|chilo(?:grammo|grammi)?|kilo(?:grammo|grammi)?|1 ?kg", t):
        return "kg"
    if re.fullmatch(r"q|q\.?\s?l\.?[ei]?|qle|qli|quintal[ei]|100 ?kg", t):
        return "q"
    if re.fullmatch(r"t|ton|tonn|tonnellat[ae]", t):
        return "t"
    return None


def _unit_from_text(text: str | None) -> str | None:
    """Price unit stated in free text ('€/Kg', 'euro al kg', '€/q.le'). None when absent or
    when both per-kg and per-quintal wording appear (ambiguous)."""
    t = _fold(text)
    per_q = re.search(r"/\s*(?:q\.?\s?l[ie]|ql|q|quintale)\b|\b(?:al|per)\s+quintale\b", t)
    per_kg = re.search(r"/\s*kg\b|\b(?:al|per)\s+(?:kg|chilo)\b", t)
    if per_q and per_kg:
        return None
    return "q" if per_q else "kg" if per_kg else None


def _per_kg(value: float, unit: str) -> float:
    return value / KG_PER_UNIT[unit]


def _plausible(value: float | None, unit: str) -> bool:
    return value is None or MIN_PLAUSIBLE_PER_KG <= _per_kg(value, unit) <= MAX_PLAUSIBLE_PER_KG


def _vat_flag(text: str | None) -> bool | None:
    """True for 'IVA compresa/inclusa', False for 'IVA esclusa' / '+ IVA', None if unstated."""
    t = _fold(text).replace("i.v.a.", "iva").replace("i.v.a", "iva")
    if re.search(r"\biva\s+esclus|esclus\w*\s+(?:l'?\s*)?iva\b|\+\s*iva\b|\boltre\s+(?:l'?\s*)?iva\b", t):
        return False
    if re.search(r"\biva\s+(?:compres|inclus)|(?:compres|inclus)\w*\s+(?:l'?\s*)?iva\b", t):
        return True
    return None


def _vat_words(flag: bool | None) -> str:
    return {True: "IVA compresa", False: "IVA esclusa"}.get(flag, "IVA non indicata")


def _terms(*parts: str | None) -> str | None:
    s = "; ".join(p for p in parts if p)
    return s[:200] or None


# ===========================================================================
# Varieties, origins, packaging
# ===========================================================================

_GENERIC_HONEY_RE = re.compile(
    r"^(?:il\s+)?(?:miele|mieli|totale|totale mieli|media|italia|tutti i mieli|miele italiano|miele nazionale)$"
)


def normalize_it_variety(raw: str | None) -> tuple[str, bool]:
    """Italian label -> (Variety value, organic). Wraps `normalize_variety` with Italian
    specifics: 'alta montagna' honeys -> OTHER (not polyflora, even when the label says
    'Millefiori di alta montagna'); a generic 'Miele'/'Totale' row -> UNSPECIFIED. Callers
    always store the raw label in `variety_raw`."""
    text = _fold(raw)
    if not text:
        return Variety.UNSPECIFIED.value, False
    variety, organic = normalize_variety(_clean(raw))
    if "alta montagna" in text:
        return Variety.OTHER.value, organic
    if _GENERIC_HONEY_RE.match(text):
        return Variety.UNSPECIFIED.value, organic
    return variety, organic


# Italian adjectives / country names that name a foreign ORIGIN of the honey.
_ORIGIN_WORDS: list[tuple[str, str]] = [
    (r"ungheres[ei]|ungheria", "HUN"), (r"argentin[oaie]", "ARG"), (r"ucrain[oaie]", "UKR"),
    (r"cines[ei]|cina", "CHN"), (r"rumen[oaie]|romen[oaie]|romania", "ROU"),
    (r"spagnol[oaie]|spagna", "ESP"), (r"bulgar[oaie]|bulgaria", "BGR"),
    (r"messican[oaie]|messico", "MEX"), (r"brasilian[oaie]|brasile", "BRA"),
    (r"uruguaian[oaie]|uruguay", "URY"), (r"cilen[oaie]|cile", "CHL"),
    (r"turc(?:o|a|hi|he)|turchia", "TUR"), (r"serb[oaie]|serbia", "SRB"),
    (r"moldav[oaie]|moldavia|moldova", "MDA"), (r"polacc(?:o|a|hi|he)|polonia", "POL"),
    (r"grec(?:o|a|i|he)|grecia", "GRC"), (r"frances[ei]|francia", "FRA"),
    (r"tedesc(?:o|a|hi|he)|germania", "DEU"), (r"vietnamit[aie]|vietnam", "VNM"),
    (r"indian[oaie]|india", "IND"), (r"croat[oaie]|croazia", "HRV"),
    (r"slovacc(?:o|a|hi|he)|slovacchia", "SVK"), (r"sloven[oaie]|slovenia", "SVN"),
    (r"austriac(?:o|a|i|he)|austria", "AUT"), (r"portoghes[ei]|portogallo", "PRT"),
    (r"neozelandes[ei]|nuova zelanda", "NZL"), (r"cuban[oaie]|cuba", "CUB"),
    (r"thailandes[ei]|thailandia", "THA"), (r"etiop[ei]|etiopia", "ETH"),
]
_ORIGIN_PATTERNS = [(re.compile(rf"\b({p})\b"), iso) for p, iso in _ORIGIN_WORDS]
_FOREIGN_GENERIC_RE = re.compile(
    r"\b(extra[- ]?ue|extracomunitari[oaie]|comunitari[oaie]|ester[oaie]|d'importazione|di importazione"
    r"|importat[oaie]|stranier[oaie])\b"
)
_ITALIAN_RE = re.compile(r"\b(italian[oaie])\b")


@dataclass
class Origin:
    iso3: str | None          # ISO3 when a single country is named
    label: str | None         # the words that named it
    foreign: bool             # a non-Italian origin is named (country may be unknown)
    ambiguous: bool           # several origins, or Italian and foreign together


def detect_origin(text: str | None) -> Origin:
    t = _fold(text)
    found: dict[str, str] = {}
    for rx, iso in _ORIGIN_PATTERNS:
        m = rx.search(t)
        if m:
            found.setdefault(iso, m.group(1))
    italian = bool(_ITALIAN_RE.search(t))
    generic = _FOREIGN_GENERIC_RE.search(t)
    if len(found) > 1:
        return Origin(None, ", ".join(found.values()), True, True)
    if found:
        iso, word = next(iter(found.items()))
        return Origin(iso, word, True, italian)
    if generic:
        return Origin(None, generic.group(1), True, italian)
    return Origin(None, None, False, False)


def classify_packaging(text: str | None) -> str:
    """Packaging wording -> code: fusto_3q | fusto_300kg | fusto | secchio_25kg | secchio |
    sfuso | non_specificato."""
    t = _fold(text)
    if "fust" in t:
        if re.search(r"\b3\s*q", t):
            return "fusto_3q"
        if re.search(r"\b300\s*kg", t):
            return "fusto_300kg"
        return "fusto"
    if re.search(r"secch|\blatt[ae]\b", t):
        return "secchio_25kg" if re.search(r"\b25\s*kg", t) else "secchio"
    if "sfuso" in t:
        return "sfuso"
    return "non_specificato"


# ===========================================================================
# HTML table helpers
# ===========================================================================


def _table_rows(table) -> list[list[str]]:
    """Rows of one <table> (nested tables excluded) as cleaned cell text; colspan expanded."""
    out: list[list[str]] = []
    for tr in table.find_all("tr"):
        if tr.find_parent("table") is not table:
            continue
        cells: list[str] = []
        for c in tr.find_all(["th", "td"], recursive=False):
            cells.append(_clean(c.get_text(" ", strip=True)))
            span = str(c.get("colspan") or "1")
            cells.extend([""] * (min(int(span), 20) - 1 if span.isdigit() else 0))
        if cells:
            out.append(cells)
    return out


def _map_header(cells: list[str], spec: dict[str, re.Pattern]) -> dict[str, int]:
    """Map logical column names to indexes; each header cell is used at most once."""
    mapping: dict[str, int] = {}
    for i, cell in enumerate(cells):
        f = _fold(cell)
        if not f:
            continue
        for key, rx in spec.items():
            if key not in mapping and rx.search(f):
                mapping[key] = i
                break
    return mapping


def _find_table(soup, spec: dict[str, re.Pattern], required: tuple[str, ...]):
    """First table having a header row (within its first rows) that maps every required
    column. Returns (table, rows, header_index, mapping) or None."""
    for table in soup.find_all("table"):
        rows = _table_rows(table)
        for i, r in enumerate(rows[:6]):
            mapping = _map_header(r, spec)
            if all(k in mapping for k in required):
                return table, rows, i, mapping
    return None


def _first_rows(soup, n: int = 3) -> list[list[str]]:
    return [(_table_rows(t) or [[]])[0] for t in soup.find_all("table")[:n]]


def _cell(row: list[str], mapping: dict[str, int], key: str) -> str:
    i = mapping.get(key)
    return row[i] if i is not None and i < len(row) else ""


# ===========================================================================
# PDF helpers
# ===========================================================================


def _open_pdf(content: bytes):
    import pdfplumber

    try:
        return pdfplumber.open(io.BytesIO(content))
    except Exception as exc:  # pdfminer raises several unrelated exception types
        raise CollectorError(f"not a readable PDF ({type(exc).__name__}: {exc})") from exc


def _pdf_lines(content: bytes) -> list[list[str]]:
    """Text lines per page (cleaned, empty lines dropped)."""
    with _open_pdf(content) as pdf:
        pages = []
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages.append([_clean(line) for line in text.splitlines() if _clean(line)])
    return pages


# ===========================================================================
# 1) CCIAA Cuneo — monthly "Miele" wholesale list
# ===========================================================================

CUNEO_BASE = "https://www.cuneoprezzi.it"
CUNEO_INDEX_URL = CUNEO_BASE + "/ingrosso/alimentari/"
CUNEO_LIST_URL = CUNEO_BASE + "/dataentry/site/ingrosso/lists/download/{fmt}?listCategory={id}"
CUNEO_LIST_PAGE_URL = CUNEO_BASE + "/ingrosso/ALIMENTARI/?listCategory={id}"
CUNEO_AVERAGES_URL = CUNEO_BASE + "/dataentry/site/ingrosso/medie/download/pdf?category=11&mYear={year}"
CUNEO_MAX_LISTS = 3            # newest lists re-checked per run (unchanged ones cost one request)
CUNEO_BACKFILL_YEARS = 5       # complete years read from the averages PDFs
# Last year's averages PDF keeps changing after New Year (the December list is dated 31 Dec and
# published days to weeks later): it is re-fetched on every run until one copy fetched on or
# after the 1st of this month of the following year is held, then left alone (again only with --force).
CUNEO_AVERAGES_SETTLE_MONTH = 4

CUNEO_SPEC: dict[str, re.Pattern] = {
    "product": re.compile(r"prodott|\bvoce\b|descrizion|variet|\bmerce\b|qualita"),
    "unit": re.compile(r"^u\.?\s*m\.?$|^um$|unita di misura|\bmisura\b"),
    "min": re.compile(r"\bmin"),
    "max": re.compile(r"\bmax"),
    "vat": re.compile(r"\biva\b|aliquota"),
}
_LISTCAT_RE = re.compile(r"listCategory=(\d+)", re.I)
_PACK_IN_PARENS_RE = re.compile(r"^(?P<name>.+?)\s*\((?P<pack>[^()]*)\)\s*$")
_PACK_AFTER_DASH_RE = re.compile(r"^(?P<name>.+?)\s*[-–]\s*(?P<pack>(?:in\s+)?(?:fust|secch|latt).*)$", re.I)
_PACK_WORD_RE = re.compile(r"fust|secch|latt|\bkg\b|q\.?\s?li|q\.?le|quintal|sfuso", re.I)


@dataclass
class CuneoListLink:
    list_category: int
    title: str
    list_date: date | None
    url: str


@dataclass
class CuneoList:
    title: str
    list_date: date
    period_year: int
    period_month: int
    basis_note: str | None
    vat_included: bool | None
    rows: list[dict]
    problems: list[str] = field(default_factory=list)
    no_quote: list[str] = field(default_factory=list)
    fmt: str = "html"


def split_cuneo_label(label: str) -> tuple[str, str | None]:
    """'Acacia (fusto da 3 q.li)' -> ('Acacia', 'fusto da 3 q.li'). Parentheses that do not
    describe packaging stay in the name ('Millefiori (biologico)')."""
    label = _clean(label)
    for rx in (_PACK_IN_PARENS_RE, _PACK_AFTER_DASH_RE):
        m = rx.match(label)
        if m and _PACK_WORD_RE.search(m.group("pack")):
            return _clean(m.group("name")), _clean(m.group("pack"))
    return label, None


def find_cuneo_lists(content: bytes | str, base_url: str = CUNEO_INDEX_URL) -> list[CuneoListLink]:
    """'Miele' lists linked from the ALIMENTARI index, newest first (by list date, then id).

    Raises SchemaDrift when the index has no 'listCategory=' link at all (layout changed);
    returns [] when there are lists but none for honey."""
    soup = _soup(content)
    anchors = [a for a in soup.find_all("a", href=True)]
    if not any(_LISTCAT_RE.search(a["href"]) for a in anchors):
        raise SchemaDrift(
            "Cuneo ALIMENTARI index: no link containing 'listCategory=' was found; the page layout has changed"
        )
    found: dict[int, CuneoListLink] = {}
    for a in anchors:
        m = _LISTCAT_RE.search(a["href"])
        if not m:
            continue
        text = _clean(a.get_text(" ")) or _clean(a.get("title"))
        row = a.find_parent(["tr", "li"])
        context = _clean(row.get_text(" ")) if row is not None else text
        if "miele" not in _fold(f"{text} {context}"):
            continue
        cid = int(m.group(1))
        list_date = parse_it_date(text) or parse_it_date(context)
        title = text if "miele" in _fold(text) else context
        prev = found.get(cid)
        if prev is None or (prev.list_date is None and list_date is not None):
            found[cid] = CuneoListLink(cid, title[:300], list_date, urljoin(base_url, a["href"]))
    return sorted(found.values(), key=lambda link: (link.list_date or date.min, link.list_category), reverse=True)


def _cuneo_title_and_date(lines: list[str], fallback_title: str | None) -> tuple[str, date | None]:
    """Prefer the 'rilevazione ... del <data>' line, then any 'Miele' line with a date, then
    the index link text."""
    for pick in (
        lambda ln: re.search(r"rilevazion", ln, re.I),
        lambda ln: re.search(r"miele", ln, re.I),
    ):
        for line in lines:
            if pick(line):
                d = parse_it_date(line)
                if d:
                    return line, d
    if fallback_title:
        d = parse_it_date(fallback_title)
        if d:
            return fallback_title, d
    title = next((ln for ln in lines if re.search(r"miele", ln, re.I)), fallback_title or "")
    return title, None


def _explicit_month(lines: list[str]) -> tuple[int, int] | None:
    for line in lines:
        m = re.search(rf"\bmese\s+di\s+({_MONTH_ALT})\s+(\d{{4}})", line, re.I)
        if m:
            return int(m.group(2)), IT_MONTHS[m.group(1).lower()]
    return None


def _basis_note(lines: list[str], title: str | None) -> str | None:
    """Lines outside the table that state the price basis (packaging, delivery, VAT)."""
    out: list[str] = []
    for line in lines:
        if line == title or len(line) > 300:
            continue
        f = _fold(line)
        if re.search(r"\biva\b|i\.v\.a|\bfranco\b|\bsfuso\b|\bfust[oi]\b", f) and line not in out:
            out.append(line)
    return " - ".join(out)[:500] or None


def _delivery_words(basis: str | None) -> str | None:
    m = re.search(r"\bfranco\s+[a-z' ]+?(?=\s*(?:-|,|;|\.|\biva\b|$))", _fold(basis))
    return m.group(0).strip() if m else None


def _packaging_from_basis(basis: str | None) -> str | None:
    m = re.search(
        r"(?:in\s+)?(fust[oi]\s+da\s+[\d,.]+\s*(?:q\.?\s?li|q\.?le|quintali|kg)|secchi[o]?\s+da\s+[\d,.]+\s*kg)",
        _clean(basis), re.I,
    )
    return m.group(1) if m else None


def _cuneo_finish(raw_rows: list[dict], context_lines: list[str], header_cells: list[str],
                  has_unit_col: bool, fallback_title: str | None, fmt: str) -> CuneoList:
    """Shared by the HTML and CSV parsers: date/period, basis, units and row validation."""
    title, list_date = _cuneo_title_and_date(context_lines, fallback_title)
    if list_date is None:
        raise SchemaDrift(
            "Cuneo honey list: survey date not found (expected a title such as "
            "'Miele - rilevazione mensile del 30 settembre 2023')"
        )
    year, month = _explicit_month(context_lines) or (list_date.year, list_date.month)
    basis = _basis_note(context_lines, title)
    vat_included = _vat_flag(basis)
    page_unit = None
    if not has_unit_col:
        page_unit = _unit_from_text(" ".join(header_cells + context_lines))
        if page_unit is None:
            raise SchemaDrift(
                "Cuneo honey list: no 'U.M.' column and no unambiguous '€/kg' or '€/q' wording; "
                "refusing to guess the price unit"
            )
    out = CuneoList(title=title, list_date=list_date, period_year=year, period_month=month,
                    basis_note=basis, vat_included=vat_included, rows=[], fmt=fmt)
    for raw in raw_rows:
        label = _clean(raw.get("label"))
        cells = [raw.get(k, "") for k in ("unit", "min", "max", "vat")]
        if not label or _fold(label) in ("prodotto", "totale"):
            continue
        if not any(_clean(c) for c in cells):
            continue                                   # section heading row
        try:
            low = parse_it_number(raw.get("min"))
            high = parse_it_number(raw.get("max"))
        except ValueError:
            out.problems.append(f"Cuneo '{label}': unparseable price ({raw.get('min')!r} / {raw.get('max')!r}); row skipped")
            continue
        if low is None and high is None:
            out.no_quote.append(label)                 # not quoted this month: missing, never zero
            continue
        unit = normalize_unit(raw.get("unit")) if has_unit_col else page_unit
        if unit is None:
            out.problems.append(f"Cuneo '{label}': unknown unit {raw.get('unit')!r}; row skipped")
            continue
        if low is not None and high is not None and low > high:
            out.problems.append(f"Cuneo '{label}': min {low} > max {high}; row skipped")
            continue
        value = round((low + high) / 2, 4) if low is not None and high is not None else (low if low is not None else high)
        if not (_plausible(low, unit) and _plausible(high, unit) and _plausible(value, unit)):
            out.problems.append(f"Cuneo '{label}': implausible price {low}-{high} EUR/{unit}; row skipped")
            continue
        name, pack = split_cuneo_label(label)
        packaging, pack_from = (pack, "label") if pack else (_packaging_from_basis(basis), "list_note")
        variety, organic = normalize_it_variety(name)
        origin = detect_origin(label)
        if origin.ambiguous:
            out.problems.append(f"Cuneo '{label}': ambiguous origin ({origin.label}); row skipped")
            continue
        try:
            vat_rate = parse_it_number(raw.get("vat"))
        except ValueError:
            vat_rate = None
        out.rows.append({
            "label": label, "name": name, "variety": variety, "organic": organic,
            "packaging": packaging, "packaging_from": pack_from if packaging else None,
            "packaging_code": classify_packaging(packaging), "unit": unit,
            "low": low, "high": high, "value": value, "vat_rate": vat_rate,
            "origin_iso3": origin.iso3 if origin.foreign else MARKET_ISO3,
            "origin_label": origin.label if origin.foreign else "Italia",
        })
    return out


def parse_cuneo_list_html(content: bytes | str, *, fallback_title: str | None = None) -> CuneoList:
    """Parse the 'download/html' version of a Cuneo honey list.

    Expected (reconstructed) layout: a title 'Miele - rilevazione mensile del <data>', a note
    such as 'Prodotto sfuso in fusti da 3 q.li - franco partenza dal magazzino IVA compresa'
    and a table Prodotto | U.M. | Prezzo min | Prezzo max | IVA %."""
    soup = _soup(content)
    found = _find_table(soup, CUNEO_SPEC, ("product", "min", "max"))
    if not found:
        raise SchemaDrift(
            "Cuneo honey list: no table with the columns Prodotto / Prezzo min / Prezzo max "
            f"(tables: {len(soup.find_all('table'))}; first rows: {_first_rows(soup)})"
        )
    table, rows, h, mapping = found
    raw_rows = [{k: _cell(r, mapping, k) for k in ("product", "unit", "min", "max", "vat")} for r in rows[h + 1:]]
    for r in raw_rows:
        r["label"] = r.pop("product")
    table.extract()                                    # what is left: title, notes
    context = [ln for ln in (_clean(x) for x in soup.get_text("\n").split("\n")) if ln]
    return _cuneo_finish(raw_rows, context, rows[h], "unit" in mapping, fallback_title, "html")


def parse_cuneo_list_csv(content: bytes | str, *, fallback_title: str | None = None) -> CuneoList:
    """Parse the 'download/csv' version (title/note lines, then a header row, then items)."""
    text = _decode(content) if isinstance(content, bytes) else content
    lines = text.splitlines()
    delimiter = max((";", "\t", ","), key=lambda d: sum(line.count(d) for line in lines[:40]))
    rows = [[_clean(c) for c in r] for r in csv.reader(lines, delimiter=delimiter)]
    h, mapping = -1, {}
    for i, r in enumerate(rows[:40]):
        candidate = _map_header(r, CUNEO_SPEC)
        if all(k in candidate for k in ("product", "min", "max")):
            h, mapping = i, candidate
            break
    if h < 0:
        raise SchemaDrift(
            f"Cuneo honey list (CSV): no header row with Prodotto / Prezzo min / Prezzo max (first rows: {rows[:3]})"
        )
    context = [" ".join(c for c in r if c) for r in rows[:h] if any(r)]
    raw_rows = []
    for r in rows[h + 1:]:
        raw = {k: _cell(r, mapping, k) for k in ("product", "unit", "min", "max", "vat")}
        raw["label"] = raw.pop("product")
        raw_rows.append(raw)
    return _cuneo_finish(raw_rows, context, rows[h], "unit" in mapping, fallback_title, "csv")


# ---- yearly averages PDF ("Miele - medie YYYY") ---------------------------


@dataclass
class CuneoAverages:
    year: int | None
    rows: list[dict]           # {label, name, variety, organic, packaging, packaging_code, unit, monthly{m: v}, annual}
    problems: list[str] = field(default_factory=list)
    method: str = "table"      # 'table' (ruled table) or 'words' (x-position bucketing)


def _month_of_header(cell: str | None) -> int | None:
    """Header cell -> 1..12 for a month, 0 for the annual mean ('Media'), None otherwise."""
    t = _fold(cell).strip(" .")
    if t in ("media", "media annua", "media annuale", "media anno"):
        return 0
    return it_month_number(t)


def _find_month_header(rows: list[list[str | None]]) -> tuple[int, dict[int, int], int | None] | None:
    for i, row in enumerate(rows[:6]):
        cmap: dict[int, int] = {}
        unit_col = None
        for j, cell in enumerate(row):
            k = _month_of_header(cell)
            if k is not None and k not in cmap.values():
                cmap[j] = k
            elif CUNEO_SPEC["unit"].search(_fold(cell)):
                unit_col = j
        if len({k for k in cmap.values() if k}) == 12:
            return i, cmap, unit_col
    return None


def _averages_row(label: str, cells: dict[int, str], unit: str, problems: list[str]) -> dict | None:
    """cells: {month(0=annual): text}. Malformed or implausible cells are dropped (warned)."""
    label = _clean(label)
    if not label or _month_of_header(label) is not None or _fold(label) in ("prodotto", "u.m."):
        return None
    monthly: dict[int, float] = {}
    annual = None
    for k, text in cells.items():
        try:
            v = parse_it_number(text)
        except ValueError:
            problems.append(f"Cuneo averages '{label}': unparseable cell {text!r} ({'media' if k == 0 else k}); cell skipped")
            continue
        if v is None:
            continue                                   # month without a quotation
        if not _plausible(v, unit):
            problems.append(f"Cuneo averages '{label}': implausible value {v} EUR/{unit}; cell skipped")
            continue
        if k == 0:
            annual = v
        else:
            monthly[k] = v
    if not monthly and annual is None:
        return None
    name, pack = split_cuneo_label(label)
    variety, organic = normalize_it_variety(name)
    return {"label": label, "name": name, "variety": variety, "organic": organic, "packaging": pack,
            "packaging_code": classify_packaging(pack), "unit": unit, "monthly": monthly, "annual": annual}


def _group_lines(words: list[dict], tol: float = 3.0) -> list[tuple[float, list[dict]]]:
    lines: list[tuple[float, list[dict]]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(lines[-1][0] - w["top"]) <= tol:
            lines[-1][1].append(w)
        else:
            lines.append((w["top"], [w]))
    return [(top, sorted(ws, key=lambda w: w["x0"])) for top, ws in lines]


def _averages_from_words(page, unit: str, problems: list[str]) -> list[dict] | None:
    """Fallback for unruled tables: locate the month header words and assign each number to
    the nearest column centre. Returns None when the page has no month header."""
    lines = _group_lines(page.extract_words(keep_blank_chars=False, use_text_flow=False))
    header_idx, cols = None, {}
    for i, (_, words) in enumerate(lines):
        found: dict[int, tuple[float, float]] = {}     # month (0 = Media) -> (x centre, x0)
        for w in words:
            k = _month_of_header(w["text"])
            if k is not None and k not in found:
                found[k] = ((w["x0"] + w["x1"]) / 2, w["x0"])
        if len([k for k in found if k]) == 12:
            header_idx, cols = i, found
            break
    if header_idx is None:
        return None
    centres = sorted((c, k) for k, (c, _) in cols.items())
    spacing = min(b[0] - a[0] for a, b in pairwise(centres))
    label_right = min(x0 for _, x0 in cols.values()) - 1
    rows, pending = [], ""
    for _, words in lines[header_idx + 1:]:
        label = _clean(" ".join(w["text"] for w in words if w["x1"] <= label_right))
        values = [w for w in words if w["x1"] > label_right]
        if not values:
            pending = _clean(f"{pending} {label}")     # wrapped label: continues on next line
            continue
        label = _clean(f"{pending} {label}")
        pending = ""
        cells: dict[int, str] = {}
        for w in values:
            mid = (w["x0"] + w["x1"]) / 2
            c, k = min(centres, key=lambda ck: abs(ck[0] - mid))
            if abs(c - mid) > spacing * 0.6 or k in cells:
                problems.append(f"Cuneo averages '{label}': value {w['text']!r} not aligned with a column; row skipped")
                cells = {}
                break
            cells[k] = w["text"]
        if cells:
            row = _averages_row(label, cells, unit, problems)
            if row:
                rows.append(row)
    return rows


def parse_cuneo_averages_pdf(content: bytes, *, year: int | None = None) -> CuneoAverages:
    """Parse 'Miele - medie YYYY': Prodotto | Gen … Dic | Media, blank cells = no quote.

    The unit is taken from the PDF text when stated (€/kg or €/q); otherwise EUR/kg is
    assumed, as in the chamber's item list ('Miele | kg | mensile'), and the plausibility
    window rejects values that would only make sense per quintal."""
    with _open_pdf(content) as pdf:
        full = "\n".join(page.extract_text() or "" for page in pdf.pages)
        m = re.search(r"medi[ae]\D{0,40}?((?:19|20)\d{2})", full, re.I)
        pdf_year = int(m.group(1)) if m else None
        if year and pdf_year and pdf_year != year:
            raise SchemaDrift(f"Cuneo averages PDF: requested year {year} but the document is for {pdf_year}")
        unit = _unit_from_text(full) or "kg"
        result = CuneoAverages(year=year or pdf_year, rows=[])
        header_found = False
        for page in pdf.pages:
            page_done = False
            for tbl in page.extract_tables() or []:
                hdr = _find_month_header(tbl)
                if not hdr:
                    continue
                header_found = page_done = True
                h, cmap, unit_col = hdr
                label_col = next((j for j in range(len(tbl[h])) if j not in cmap and j != unit_col), 0)
                for r in tbl[h + 1:]:
                    cells = {k: (r[j] if j < len(r) else "") or "" for j, k in cmap.items()}
                    row_unit = unit
                    if unit_col is not None and unit_col < len(r) and _clean(r[unit_col]):
                        row_unit = normalize_unit(r[unit_col]) or ""
                        if not row_unit:
                            result.problems.append(f"Cuneo averages: unknown unit {r[unit_col]!r}; row skipped")
                            continue
                    label = (r[label_col] or "") if label_col < len(r) else ""
                    row = _averages_row(label, cells, row_unit, result.problems)
                    if row:
                        result.rows.append(row)
            if not page_done:
                rows = _averages_from_words(page, unit, result.problems)
                if rows is not None:
                    header_found = True
                    result.method = "words"
                    result.rows.extend(rows)
    if not header_found:
        raise SchemaDrift("Cuneo averages PDF: no header row with the twelve months (Gen ... Dic) was found")
    return result


class CuneoHoneyCollector(Collector):
    key = "cciaa_cuneo_miele"
    name = "CCIAA Cuneo - Listino prezzi all'ingrosso: Miele"
    publisher = "Camera di Commercio di Cuneo"
    homepage = CUNEO_INDEX_URL
    kind = SourceKind.HTML
    reliability = Reliability.INDUSTRY
    category = "prices"
    country_iso3 = "ITA"
    language = "it"
    expected_update = "Mensile (rilevazione di fine mese); controllo settimanale"
    expected_update_en = "Monthly (end-of-month survey); checked weekly"
    expected_max_age_days = 50
    terms_note = ("Listino camerale pubblico, prezzi indicativi all'ingrosso sulla piazza di Cuneo. "
                  "Nessuna licenza esplicita trovata: citare 'CCIAA Cuneo'.")
    schedule = {"trigger": "cron", "day_of_week": "tue", "hour": 7, "minute": 40}

    def collect(self, ctx: CollectContext) -> None:
        index = ctx.fetch(CUNEO_INDEX_URL, store=False)
        links = find_cuneo_lists(index.content, index.url)
        if not links:
            ctx.warn("Cuneo: the ALIMENTARI index lists no 'Miele' price list right now")
        for link in links[:CUNEO_MAX_LISTS]:
            self._import_list(ctx, link)
            ctx.checkpoint()
        self._backfill_averages(ctx)

    # -- monthly list ----------------------------------------------------------
    def _import_list(self, ctx: CollectContext, link: CuneoListLink) -> None:
        doc = parser = None
        errors = []
        for fmt, fn in (("html", parse_cuneo_list_html), ("csv", parse_cuneo_list_csv)):
            try:
                doc = ctx.fetch(CUNEO_LIST_URL.format(fmt=fmt, id=link.list_category),
                                title=link.title, published_at=link.list_date)
                parser = fn
                break
            except Offline:
                raise
            except CollectorError as exc:
                errors.append(f"{fmt}: {exc}")
        if doc is None:
            ctx.warn(f"Cuneo list {link.list_category} ({link.title}): download failed ({'; '.join(errors)})")
            return
        if doc.unchanged and not ctx.force:
            return
        parsed = parser(doc.content, fallback_title=link.title)    # SchemaDrift -> run fails loudly
        for p in parsed.problems:
            ctx.warn(p)
        if parsed.no_quote:
            log.info("Cuneo list %s: not quoted this month: %s", link.list_category, ", ".join(parsed.no_quote))
        if not parsed.rows:
            ctx.warn(f"Cuneo list {link.list_category} ({parsed.title}): no quoted honey item")
            return
        start, end = month_bounds(parsed.period_year, parsed.period_month)
        label = f"{parsed.period_year}-{parsed.period_month:02d}"
        delivery = _delivery_words(parsed.basis_note)
        for r in parsed.rows:
            vat = _vat_words(parsed.vat_included) + (f" (aliquota {r['vat_rate']:g}%)" if r["vat_rate"] else "")
            ctx.add_price(
                series_key=f"cuneo|{_slug(r['label'])}|{label}",
                price_type=PriceType.WHOLESALE_BULK,
                variety=r["variety"], variety_raw=r["name"][:200], organic=r["organic"],
                price_value=r["value"], price_low=r["low"], price_high=r["high"],
                currency=CURRENCY, unit=r["unit"],
                period_start=start, period_end=end, period_label=label, frequency="M",
                market_iso3=MARKET_ISO3, market_location="Cuneo",
                origin_iso3=r["origin_iso3"], origin_label=r["origin_label"],
                terms=_terms(r["packaging"] or "confezione non indicata", delivery, vat),
                published_at=parsed.list_date, source_url=doc.url, raw_document_id=doc.raw_document_id,
                data_status=DataStatus.PUBLISHED,
                extra={
                    "packaging": r["packaging"], "packaging_code": r["packaging_code"],
                    "packaging_from": r["packaging_from"], "drum": r["packaging_code"].startswith("fusto"),
                    "vat_included": parsed.vat_included, "vat_rate_pct": r["vat_rate"],
                    "basis_note": parsed.basis_note, "list_title": parsed.title,
                    "list_date": parsed.list_date.isoformat(), "list_category": link.list_category,
                    "list_page_url": CUNEO_LIST_PAGE_URL.format(id=link.list_category),
                    "format": parsed.fmt, "channel": "chamber_wholesale",
                },
            )

    # -- back-fill from the yearly averages PDFs ------------------------------------
    def _backfill_averages(self, ctx: CollectContext) -> None:
        """Read the averages PDF of each back-fill year until a copy fetched on or after the
        year's settle date is held. The PDF is a live document: the previous year's copy
        fetched in January may still lack December and its 'Media' covers fewer months, so it
        is fetched again on every run until then (unchanged bytes are not re-parsed; changed
        values become revisions). Until the settle date the annual mean is `provisional`; the
        first fetch on or after it re-reads the PDF, which publishes it."""
        today = _today()
        this_year = today.year
        state = _get_state(ctx.session, self.key)
        checked: dict[str, str] = dict(state.get("averages_checked") or {})
        attempted, failed, have_any = 0, 0, False
        for year in range(this_year - CUNEO_BACKFILL_YEARS, this_year):
            url = CUNEO_AVERAGES_URL.format(year=year)
            was_final = _averages_final(checked.get(str(year)), year)
            if not ctx.force and was_final and _raw_exists(ctx, url):
                have_any = True
                continue
            attempted += 1
            try:
                doc = ctx.fetch(url, title=f"Miele - medie {year}")
            except Offline:
                raise
            except CollectorError as exc:
                failed += 1
                log.info("Cuneo averages %s not available: %s", year, exc)
                continue
            have_any = True
            checked[str(year)] = today.isoformat()
            state["averages_checked"] = checked
            _set_state(ctx.session, self.key, state)
            final = _averages_final(checked[str(year)], year)
            if doc.unchanged and not ctx.force and (was_final or not final):
                continue
            try:
                parsed = parse_cuneo_averages_pdf(doc.content, year=year)
            except CollectorError as exc:
                ctx.warn(f"Cuneo averages {year}: {exc}; nothing stored")
                continue
            for p in parsed.problems:
                ctx.warn(p)
            self._store_averages(ctx, parsed, year, doc, final=final)
            ctx.checkpoint()
        if attempted and failed == attempted and not have_any:
            ctx.warn(f"Cuneo: no yearly averages PDF could be downloaded ({CUNEO_AVERAGES_URL})")

    def _store_averages(self, ctx: CollectContext, parsed: CuneoAverages, year: int, doc, *, final: bool = True) -> None:
        note = (f"Media pubblicata nel prospetto 'Miele - medie {year}' della CCIAA di Cuneo "
                "(valore medio, non un intervallo min-max)")
        annual_note = note if final else (
            f"{note}. Prospetto scaricato prima del 1/{CUNEO_AVERAGES_SETTLE_MONTH}/{year + 1}: la media annua "
            "può non comprendere ancora tutti i mesi (provvisoria)")
        for r in parsed.rows:
            slug = _slug(r["label"])
            common = dict(
                price_type=PriceType.WHOLESALE_BULK, variety=r["variety"], variety_raw=r["name"][:200],
                organic=r["organic"], currency=CURRENCY, unit=r["unit"],
                market_iso3=MARKET_ISO3, market_location="Cuneo", origin_iso3=MARKET_ISO3, origin_label="Italia",
                source_url=doc.url, raw_document_id=doc.raw_document_id, data_status=DataStatus.PUBLISHED,
                notes=note,
            )
            extra = {"packaging": r["packaging"], "packaging_code": r["packaging_code"],
                     "drum": r["packaging_code"].startswith("fusto"), "channel": "chamber_wholesale",
                     "averages_year": year, "parse_method": parsed.method}
            for month, value in sorted(r["monthly"].items()):
                label = f"{year}-{month:02d}"
                # gap filling only: a monthly list quotation (min-max) for this item wins
                if _series_exists(ctx, f"{PriceType.WHOLESALE_BULK.value}|cuneo|{slug}|{label}"):
                    continue
                start, end = month_bounds(year, month)
                ctx.add_price(series_key=f"cuneo-media|{slug}|{label}", price_value=value,
                              period_start=start, period_end=end, period_label=label, frequency="M",
                              terms=_terms(r["packaging"], "media mensile"),
                              extra={**extra, "statistic": "monthly_average"}, **common)
            if r["annual"] is not None:
                start, end = year_bounds(year)
                ctx.add_price(series_key=f"cuneo-media|{slug}|{year}", price_value=r["annual"],
                              period_start=start, period_end=end, period_label=str(year), frequency="A",
                              terms=_terms(r["packaging"], "media annua"),
                              extra={**extra, "statistic": "annual_average"},
                              **{**common, "notes": annual_note,
                                 "data_status": DataStatus.PUBLISHED if final else DataStatus.PROVISIONAL})


def _raw_exists(ctx: CollectContext, url: str) -> bool:
    return ctx.session.scalar(
        select(RawDocument.id).where(RawDocument.source_id == ctx.source.id, RawDocument.url == url).limit(1)
    ) is not None


def _averages_final(last_fetched: str | None, year: int) -> bool:
    """True when the 'medie {year}' PDF was last fetched (by `_today()`) on or after the settle
    date, so the copy held is the final one."""
    fetched = parse_date(last_fetched)
    return fetched is not None and fetched >= date(year + 1, CUNEO_AVERAGES_SETTLE_MONTH, 1)


def _get_state(session, key: str) -> dict:
    """Per-collector bookkeeping (not observations), same convention as the other collectors."""
    row = session.get(AppSetting, f"collector_state:{key}")
    return dict(row.value) if row is not None and isinstance(row.value, dict) else {}


def _set_state(session, key: str, value: dict) -> None:
    full_key = f"collector_state:{key}"
    value = json.loads(json.dumps(value))       # a fresh object, so the JSON column sees the change
    row = session.get(AppSetting, full_key)
    if row is None:
        session.add(AppSetting(key=full_key, value=value))
    else:
        row.value = value


def _series_exists(ctx: CollectContext, series_key: str) -> bool:
    return ctx.session.scalar(
        select(PriceObservation.id).where(
            PriceObservation.source_id == ctx.source.id, PriceObservation.series_key == series_key
        ).limit(1)
    ) is not None


# ===========================================================================
# 2) ISMEA Mercati — Api e Miele origin prices
# ===========================================================================

ISMEA_URL = "https://www.ismeamercati.it/flex/cm/pages/ServeBLOB.php/L/IT/IDPagina/{id}"
ISMEA_PAGES: dict[int, str] = {
    11024: "Prezzi medi all'origine - settimanali per varietà",
    11025: "Prezzi medi all'origine - mensili per prodotto",
}
ISMEA_SPEC: dict[str, re.Pattern] = {
    "product": re.compile(r"prodott|variet"),
    "market": re.compile(r"piazz|mercat"),
    "chg_year": re.compile(r"variaz.*anno|anno\s+prec"),
    "chg_prev": re.compile(r"variaz"),
    "period": re.compile(r"settiman|^mese\b|periodo|^data\b"),
    "price": re.compile(r"^prezz"),
}
_ISMEA_WEEK_RE = re.compile(r"(\d{4})\s*-\s*(\d{1,2})\s*-\s*(\d{1,2})")
_ISMEA_MONTH_RE = re.compile(r"(\d{4})\s*-\s*(\d{1,2})")


def ismea_week_bounds(year: int, month: int, week: int) -> tuple[date, date]:
    """Week `week` of `month`: the week-th Monday-Sunday week whose Thursday falls in the
    month (ISO-8601 rule applied to months). ValueError if that week does not exist."""
    if not (1 <= month <= 12 and 1 <= week <= 5):
        raise ValueError(f"invalid ISMEA week {year}-{month}-{week}")
    first = date(year, month, 1)
    first_thursday = first + timedelta(days=(3 - first.weekday()) % 7)
    start = first_thursday - timedelta(days=3) + timedelta(weeks=week - 1)
    if (start + timedelta(days=3)).month != month:
        raise ValueError(f"ISMEA week {year}-{month}-{week} does not exist (month has fewer weeks)")
    return start, start + timedelta(days=6)


def ismea_period(raw: str) -> dict:
    """'2026-6-4' (weekly) or '2026-6' (monthly) -> period fields. ValueError otherwise."""
    s = _clean(raw)
    m = _ISMEA_WEEK_RE.fullmatch(s)
    if m:
        y, mo, w = (int(x) for x in m.groups())
        start, end = ismea_week_bounds(y, mo, w)
        iso = start.isocalendar()
        return {"start": start, "end": end, "label": f"{y}-{mo:02d}-S{w}", "frequency": "W",
                "extra": {"period_raw": s, "iso_week": f"{iso.year}-W{iso.week:02d}",
                          "period_convention": "settimana del mese: settimana lun-dom il cui giovedì cade nel mese"}}
    m = _ISMEA_MONTH_RE.fullmatch(s)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if not 1 <= mo <= 12:
            raise ValueError(f"invalid ISMEA month {s!r}")
        start, end = month_bounds(y, mo)
        return {"start": start, "end": end, "label": f"{y}-{mo:02d}", "frequency": "M", "extra": {"period_raw": s}}
    raise ValueError(f"unrecognised ISMEA period {raw!r} (expected 'YYYY-M-W' or 'YYYY-M')")


@dataclass
class IsmeaTable:
    rows: list[dict]
    problems: list[str] = field(default_factory=list)
    vat_included: bool | None = None
    updated: date | None = None


def parse_ismea_prices(content: bytes | str) -> IsmeaTable:
    """Parse an ISMEA 'Api e Miele - Prezzi medi - Origine' page.

    Reconstructed table: Prodotto/Varietà | Piazza | Settimana (or Mese) | Prezzo
    ('8,00 €/Kg') | Variaz. su Sett. Prec. ('0,0%') | Variaz. su Sett. Anno Prec. ('nd')."""
    soup = _soup(content)
    found = _find_table(soup, ISMEA_SPEC, ("product", "period", "price"))
    if not found:
        if not soup.find_all("table"):
            viewer = soup.find("iframe") is not None or re.search(
                r"reportviewer|reportserver|ssrs", soup.decode(), re.I) is not None
            hint = "the page embeds an <iframe>/report viewer (SSRS?) instead of an HTML table" if viewer \
                else "the page has no <table>"
            raise SchemaDrift(f"ISMEA honey page: price table not found ({hint})")
        raise SchemaDrift(
            "ISMEA honey page: no table with Prodotto/Varietà, Settimana/Mese and Prezzo columns "
            f"(first rows: {_first_rows(soup)})"
        )
    _, rows, h, mapping = found
    page_text = _clean(soup.get_text(" "))
    header_unit = _unit_from_text(_cell(rows[h], mapping, "price"))
    page_unit = header_unit or _unit_from_text(page_text)
    out = IsmeaTable(rows=[], vat_included=_vat_flag(page_text))
    m = re.search(r"aggiornat[oia]\s+(?:al|il|a)\s+(.{6,30})", page_text, re.I)
    out.updated = parse_it_date(m.group(1)) if m else None
    pending: list[dict] = []
    for r in rows[h + 1:]:
        product, period_raw, price_raw = (_cell(r, mapping, k) for k in ("product", "period", "price"))
        if not product and not price_raw:
            continue
        try:
            price = parse_it_number(price_raw)
        except ValueError:
            out.problems.append(f"ISMEA '{product}' {period_raw}: unparseable price {price_raw!r}; row skipped")
            continue
        if price is None:
            continue                                   # 'nd': no quotation in that period
        try:
            period = ismea_period(period_raw)
        except ValueError as exc:
            out.problems.append(f"ISMEA '{product}': {exc}; row skipped")
            continue
        changes = {}
        for key in ("chg_prev", "chg_year"):
            try:
                changes[key] = parse_it_number(_cell(r, mapping, key)) if key in mapping else None
            except ValueError:
                changes[key] = None
        pending.append({"product": product, "market": _cell(r, mapping, "market") or "Italia",
                        "price": price, "cell_unit": _unit_from_text(price_raw), "period": period, **changes})
    if pending and page_unit is None and not any(p["cell_unit"] for p in pending):
        raise SchemaDrift("ISMEA honey page: the price unit (€/kg) is stated neither in the cells nor on the page")
    for p in pending:
        unit = p.pop("cell_unit") or page_unit
        if not _plausible(p["price"], unit):
            out.problems.append(f"ISMEA '{p['product']}': implausible price {p['price']} EUR/{unit}; row skipped")
            continue
        variety, organic = normalize_it_variety(p["product"])
        out.rows.append({**p, "unit": unit, "variety": variety, "organic": organic})
    return out


class IsmeaHoneyCollector(Collector):
    key = "ismea_miele"
    name = "ISMEA Mercati - Api e miele: prezzi medi all'origine"
    publisher = "ISMEA (Istituto di Servizi per il Mercato Agricolo Alimentare)"
    homepage = "https://www.ismeamercati.it/api-miele"
    kind = SourceKind.HTML
    reliability = Reliability.OFFICIAL
    category = "prices"
    country_iso3 = "ITA"
    language = "it"
    expected_update = "Settimanale (serie stagionale, aggiornamenti irregolari) e mensile"
    expected_update_en = "Weekly (seasonal series, irregular updates) and monthly"
    expected_max_age_days = 45
    terms_note = ("Pagine pubbliche ISMEA Mercati; termini di riuso non esplicitati. Citare sempre 'Fonte: ISMEA'. "
                  "Prezzi medi all'origine (rete di rilevatori ONM per conto ISMEA), non quotazioni in fusti.")
    schedule = {"trigger": "cron", "day_of_week": "fri", "hour": 8, "minute": 10}

    def collect(self, ctx: CollectContext) -> None:
        for page_id, page_name in ISMEA_PAGES.items():
            doc = ctx.fetch(ISMEA_URL.format(id=page_id), title=f"ISMEA Api e Miele - {page_name}")
            if doc.unchanged and not ctx.force:
                continue
            table = parse_ismea_prices(doc.content)   # SchemaDrift -> run fails loudly
            for p in table.problems:
                ctx.warn(p)
            if not table.rows:
                ctx.warn(f"ISMEA page {page_id}: no quoted row (the series may be paused out of season)")
                continue
            vat = table.vat_included if table.vat_included is not None else True
            vat_source = "page" if table.vat_included is not None else "research_documentation"
            for r in table.rows:
                period = r["period"]
                ctx.add_price(
                    series_key=f"ismea|{period['frequency']}|{_slug(r['product'])}|{_slug(r['market'])}|{period['label']}",
                    price_type=PriceType.PRODUCER,
                    variety=r["variety"], variety_raw=r["product"][:200], organic=r["organic"],
                    price_value=r["price"], currency=CURRENCY, unit=r["unit"],
                    period_start=period["start"], period_end=period["end"], period_label=period["label"],
                    frequency=period["frequency"],
                    market_iso3=MARKET_ISO3, market_location=r["market"][:120],
                    origin_iso3=MARKET_ISO3, origin_label="Italia",
                    terms=_terms("prezzo medio all'origine", _vat_words(vat)),
                    published_at=table.updated, source_url=doc.url, raw_document_id=doc.raw_document_id,
                    data_status=DataStatus.PUBLISHED,
                    notes=("Settimana ISMEA convertita in date con la convenzione Paladex (vedi extra); "
                           "da verificare con ISMEA") if period["frequency"] == "W" else None,
                    extra={**period["extra"], "ismea_page": page_id, "change_prev_pct": r["chg_prev"],
                           "change_prev_year_pct": r["chg_year"], "vat_included": vat, "vat_source": vat_source,
                           "channel": "ismea_origin"},
                )
            ctx.checkpoint()


# ===========================================================================
# 3) Osservatorio Nazionale Miele (informamiele.it)
# ===========================================================================

ONM_BASE = "https://www.informamiele.it"
ONM_FEED_URL = ONM_BASE + "/feed/"
ONM_WP_API_URL = ONM_BASE + "/wp-json/wp/v2/posts?search=rilevazione&per_page=20&_fields=id,date,link,title,content"
ONM_LISTING_URLS = (ONM_BASE + "/category/comunicati/", ONM_BASE + "/tutte-le-notizie/")
ONM_REPORT_ARCHIVE_URL = ONM_BASE + "/report-annuali-produzione-e-mercato/"
ONM_MAX_BULLETINS = 6

_ONM_MONTHLY_RE = re.compile(
    rf"\b({_MONTH_ALT})[\s_-]+(\d{{4}})[\s_-]+(?:rilevazione[\s_-]+mensile|indagine[\s_-]+(?:meteorologica[\s_-]+)?produttiva)",
    re.I,
)
_ONM_ANNUAL_RE = re.compile(r"report[\s_-]+annual|valore[\s_-]+della[\s_-]+terra", re.I)


@dataclass
class OnmPost:
    url: str
    title: str
    published: date | None
    content_html: str | None
    kind: str                        # monthly | annual | other
    ref_year: int | None = None
    ref_month: int | None = None
    season: int | None = None
    # the discovery response (feed / REST API) the post came from, kept so that the exact bytes
    # can be archived if `content_html` has to stand in for the bulletin page
    copy_doc: FetchResult | None = None


def _season_of(text: str | None) -> int | None:
    t = _clean(text)
    for rx in (r"stagione[\s_-]*((?:19|20)\d{2})", r"annual[ei]?[\s_-]*((?:19|20)\d{2})",
               r"report[\s_-]*((?:19|20)\d{2})"):
        m = re.search(rx, t, re.I)
        if m:
            return int(m.group(1))
    return None


def classify_onm_post(url: str, title: str | None) -> tuple[str, int | None, int | None, int | None]:
    """-> (kind, ref_year, ref_month, season). kind is 'monthly', 'annual' or 'other'."""
    path = unquote(urlparse(url).path)
    for text in (path, title or ""):
        m = _ONM_MONTHLY_RE.search(text)
        if m:
            return "monthly", int(m.group(2)), IT_MONTHS[m.group(1).lower()], None
    hay = f"{title or ''} {path.rsplit('/', 2)[-2] if path.count('/') >= 2 else path}"
    if _ONM_ANNUAL_RE.search(hay) and not re.search(r"prime[\s_-]+valutazion", hay, re.I):
        return "annual", None, None, _season_of(title) or _season_of(path)
    return "other", None, None, None


def _post(url: str, title: str, published: date | None, content_html: str | None) -> OnmPost:
    kind, y, m, season = classify_onm_post(url, title)
    return OnmPost(url=url, title=title, published=published, content_html=content_html,
                   kind=kind, ref_year=y, ref_month=m, season=season)


def discover_onm_from_feed(content: bytes, base_url: str | None = None) -> list[OnmPost]:
    """WordPress RSS (/feed/). Raises CollectorError when the document is not a usable feed."""
    import feedparser

    parsed = feedparser.parse(content)
    if not parsed.entries:
        reason = parsed.get("bozo_exception") or "no entries"
        raise CollectorError(f"not a usable RSS feed ({reason})")
    posts = []
    for e in parsed.entries:
        link = e.get("link")
        if not link:
            continue
        published = None
        for k in ("published_parsed", "updated_parsed"):
            if e.get(k):
                published = date(*e[k][:3])
                break
        content_html = (e.get("content") or [{}])[0].get("value") or e.get("summary")
        posts.append(_post(link, _clean(e.get("title")), published, content_html))
    return posts


def discover_onm_from_wp_json(content: bytes, base_url: str | None = None) -> list[OnmPost]:
    """WordPress REST API (/wp-json/wp/v2/posts?search=...)."""
    try:
        data = json.loads(_decode(content))
    except ValueError as exc:
        raise CollectorError(f"WordPress REST answer is not JSON: {exc}") from exc
    if not isinstance(data, list):
        raise CollectorError(f"WordPress REST answer is not a list of posts: {str(data)[:200]}")
    posts = []
    for item in data:
        if not isinstance(item, dict) or not item.get("link"):
            continue
        title = item.get("title")
        title = title.get("rendered") if isinstance(title, dict) else title
        body = item.get("content")
        body = body.get("rendered") if isinstance(body, dict) else body
        posts.append(_post(item["link"], _clean(_soup(title or "").get_text(" ")), parse_date(item.get("date")), body))
    return posts


def discover_onm_from_listing(content: bytes, base_url: str = ONM_BASE + "/") -> list[OnmPost]:
    """HTML category/news listing: anchors whose URL or text is a bulletin or annual report."""
    soup = _soup(content)
    host = urlparse(base_url).netloc
    posts: dict[str, OnmPost] = {}
    for a in soup.find_all("a", href=True):
        url = urljoin(base_url, a["href"])
        if urlparse(url).netloc != host or url.lower().endswith(".pdf"):
            continue
        title = _clean(a.get_text(" ")) or _clean(a.get("title"))
        post = _post(url, title, None, None)
        if post.kind == "other":
            continue
        container = a.find_parent(["article", "li"])
        t = container.find("time") if container is not None else None
        if t is not None:
            post.published = parse_date(t.get("datetime")) if t.get("datetime") else parse_it_date(t.get_text(" "))
        prev = posts.get(url)
        if prev is None or (len(title) > len(prev.title) and post.kind == prev.kind):
            if prev is not None and post.published is None:
                post.published = prev.published
            posts[url] = post
    return list(posts.values())


@dataclass
class OnmPage:
    title: str | None
    published: date | None
    market_paragraphs: list[str]
    has_market_section: bool
    price_basis: str | None


def parse_onm_post(content: bytes | str) -> OnmPage:
    """Bulletin post (full page or the bare post body from the feed/REST API).

    The market section is the run of paragraphs after a heading containing 'mercato'
    (h2-h6, or a paragraph that is only bold text) up to the next heading."""
    soup = _soup(content)
    title = None
    og = soup.find("meta", attrs={"property": "og:title"})
    if og is not None and og.get("content"):
        title = _clean(og["content"])
    elif soup.find("h1") is not None:
        title = _clean(soup.find("h1").get_text(" "))
    published = None
    meta = soup.find("meta", attrs={"property": "article:published_time"})
    if meta is not None and meta.get("content"):
        published = parse_date(meta["content"])
    if published is None:
        t = soup.find("time", attrs={"datetime": True})
        published = parse_date(t["datetime"]) if t is not None else None
    body = soup.select_one(".entry-content") or soup.find("article") or soup.find("main") or soup.body or soup
    paragraphs, all_paragraphs, seen = [], [], set()
    in_market = has_section = False
    for block in body.find_all(["h2", "h3", "h4", "h5", "h6", "p", "li", "h1"]):
        text = _clean(block.get_text(" ", strip=True))
        if not text or text in seen:
            continue
        seen.add(text)
        strong = block.find(["strong", "b"])
        is_heading = block.name.startswith("h") or (
            len(text) <= 80 and strong is not None and _clean(strong.get_text(" ")) == text
        )
        if is_heading:
            in_market = block.name != "h1" and "mercato" in _fold(text)
            has_section = has_section or in_market
            continue
        all_paragraphs.append(text)
        if in_market:
            paragraphs.append(text)
    if not has_section:
        # no explicit heading: fall back to paragraphs that talk about the market with prices
        paragraphs = [p for p in all_paragraphs if "mercato" in _fold(p) and re.search(r"€|euro", p, re.I)]
    body_fold = _fold(body.get_text(" "))
    basis = [w for w, rx in (("franco produttore", r"franco\s+produttore"),
                             ("IVA inclusa", r"\bi\.?v\.?a\.?\s+(?:inclusa|compresa)")) if re.search(rx, body_fold)]
    return OnmPage(title=title, published=published, market_paragraphs=paragraphs,
                   has_market_section=has_section, price_basis=", ".join(basis) or None)


# ---- extraction of prices from the market prose ------------------------------

_VARIETY_KEYWORDS = [
    "millefiori di alta montagna", "millefiori d'alta montagna", "alta montagna", "millefiori", "mille fiori",
    "acacia", "castagno", "tiglio", "agrumi", "arancio", "zagara", "girasole", "eucalipto", "melata",
    "sulla", "tarassaco", "lavanda", "colza", "trifoglio", "erica", "timo", "coriandolo", "rododendro",
    "ailanto", "corbezzolo", "cardo", "edera", "asfodelo", "marruca", "grano saraceno",
]
_VARIETY_TOKEN_RE = re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted(_VARIETY_KEYWORDS, key=len, reverse=True)) + r")\b")
# Generic words that stand where a variety would ("mieli monoflora 6,00-7,50"): they take
# part in the alternation check but are never stored.
_BLOCKER_TOKEN_RE = re.compile(r"\b(monoflora|monoflore|monofloreal[ei]|monofloral[ei]|uniflorali?|mieli scuri|mieli chiari)\b")
_NUM = r"\d{1,2}(?:,\d{1,2})?"
_EUR_KG = r"\s*(?:€|euro|eur)\s*(?:/|al|per)\s*(?:kg|chilo(?:grammo)?)\b"
_RANGE_TOKEN_RE = re.compile(
    rf"(?<![\d,.])(?:(?:tra|fra|da)\s+(?:i\s+|gli\s+)?)?({_NUM})\s*(?:-|–|—|÷|\be\b|\ba\b)\s*({_NUM})(?![\d,])({_EUR_KG})?"
)
_SINGLE_TOKEN_RE = re.compile(rf"(?<![\d,.])({_NUM})(?![\d,]){_EUR_KG}")
_BULK_CONTEXT_RE = re.compile(r"all'ingrosso|\bingrosso\b|\bfust[oi]\b|\bsfus[oi]\b")
_SEGMENT_SPLIT_RE = re.compile(r";|\bmentre\b|\binvece\b|\bal contrario\b")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-Ý«\"(])")


def _sentences(paragraph: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(_clean(paragraph)) if s.strip()]


def _segment_tokens(segment: str) -> list[dict]:
    """Ordered tokens: subjects (variety keywords, generic blockers) and prices (ranges,
    single €/kg values). Positions refer to `segment` (already lower-case)."""
    tokens = []
    for m in _VARIETY_TOKEN_RE.finditer(segment):
        tokens.append({"t": "S", "pos": m.start(), "end": m.end(), "kw": m.group(1)})
    for m in _BLOCKER_TOKEN_RE.finditer(segment):
        tokens.append({"t": "S", "pos": m.start(), "end": m.end(), "kw": None})
    taken = []
    for m in _RANGE_TOKEN_RE.finditer(segment):
        tokens.append({"t": "R", "pos": m.start(), "end": m.end(), "lo": m.group(1), "hi": m.group(2),
                       "unit": bool(m.group(3))})
        taken.append((m.start(), m.end()))
    for m in _SINGLE_TOKEN_RE.finditer(segment):
        if not any(a <= m.start() < b for a, b in taken):
            tokens.append({"t": "R", "pos": m.start(), "end": m.end(), "lo": None, "hi": None, "unit": True})
    tokens.sort(key=lambda t: t["pos"])
    # the same variety named twice in a row ("il millefiori, cioè il millefiori convenzionale")
    collapsed: list[dict] = []
    for t in tokens:
        if collapsed and t["t"] == "S" and collapsed[-1]["t"] == "S" and t["kw"] and t["kw"] == collapsed[-1]["kw"]:
            collapsed[-1]["end"] = t["end"]
            continue
        collapsed.append(t)
    return collapsed


_FUSTO_RE = re.compile(r"\bfust[oi]\b")
_SECCHIO_RE = re.compile(r"\bsecch|\blatt[ae]\b")
_ORGANIC_RE = re.compile(r"\bbiologic[oaie]\b|\bbio\b")
# A parenthetical right after a pair's own phrase belongs to that pair: "4-4,5 €/kg (fusto)".
_TRAIL_PAREN_RE = re.compile(r"\s*\(([^)]*)\)")
# Words between two pairs belong to the NEXT pair only when set off by a comma and leading
# straight into it ("4-4,5 €/kg, in latta il castagno"); "4-4,5 €/kg in fusto, il castagno"
# could be either pair's.
_LEAD_QUALIFIER_RE = re.compile(r",\s*(?:in|di)\s+\w+[^,]*$")
# Price-first pairs ("6,50 €/kg per il castagno ungherese"): the words after the variety, up to
# the next punctuation or conjunction, are its own adjectives.
_ADJ_ZONE_END_RE = re.compile(r"[,;:().]|\s(?:e|ed|o|oppure|ma)\s")


def _packaging_in(text: str) -> tuple[bool, bool]:
    """(names a drum, names a tin/bucket)."""
    return bool(_FUSTO_RE.search(text)), bool(_SECCHIO_RE.search(text))


def _names_qualifier(text: str) -> bool:
    """A packaging, organic or origin word: something that must be attributed to one pair."""
    return (any(_packaging_in(text)) or bool(_ORGANIC_RE.search(text))
            or detect_origin(text).foreign or bool(_ITALIAN_RE.search(_fold(text))))


def _pair_tokens(tokens: list[dict], segment: str) -> list[dict] | None:
    """Pair subjects with prices when they alternate one-to-one (S R S R ... or R S R S ...).

    Returns one dict per pair with its `subject` and `price` tokens and the bounds
    [`start`, `end`) of the pair's own phrase in `segment` ("il castagno tra 6,5 e 6,7 €/kg";
    for a price-first pair it runs on over the variety's adjectives: "6,50 €/kg per il
    castagno ungherese"), or None when the tokens do not alternate. The text around the
    phrases is attributed by `_attribute_pairs`."""
    kinds = [t["t"] for t in tokens]
    if not kinds or "S" not in kinds or "R" not in kinds or len(kinds) % 2:
        return None
    first = kinds[0]
    if any(k != (first if i % 2 == 0 else ("R" if first == "S" else "S")) for i, k in enumerate(kinds)):
        return None
    pairs = []
    for i in range(0, len(tokens), 2):
        a, b = tokens[i], tokens[i + 1]
        subject, price = (a, b) if first == "S" else (b, a)
        end = b["end"]
        if first == "R":
            limit = tokens[i + 2]["pos"] if i + 2 < len(tokens) else len(segment)
            stop = _ADJ_ZONE_END_RE.search(segment, end, limit)
            end = stop.start() if stop else limit
        pairs.append({"subject": subject, "price": price, "start": a["pos"], "end": end})
    return pairs


def _attribute_pairs(segment: str, pairs: list[dict]) -> None:
    """Give each pair the text around its own phrase that belongs to it.

    * `trail`: a parenthetical right after the phrase ("(fusto)", "(bio)", "(ungherese)").
    * `lead`: for the first pair, the segment text before it (context of the whole segment);
      for a later pair, the end of the gap after the previous pair, only when it is set off
      by a comma and leads straight into this pair (", in latta il castagno").
    * `gap`: what is left of the gap before a later pair. A packaging, organic or origin
      word there could belong to either neighbour, so both are flagged `ambiguous`.
    * After the last pair, an organic or foreign-origin word cannot be placed either: the
      last pair is flagged `ambiguous`. A packaging word there is left to the sentence-level
      fallback of `extract_onm_prices`."""
    for i, p in enumerate(pairs):
        limit = pairs[i + 1]["start"] if i + 1 < len(pairs) else len(segment)
        m = _TRAIL_PAREN_RE.match(segment, p["end"], limit)
        p["trail"] = m.group(0) if m else ""
        p["after"] = m.end() if m else p["end"]
        p["ambiguous"] = False
    pairs[0]["lead"], pairs[0]["gap"] = segment[:pairs[0]["start"]], ""
    for prev, p in pairwise(pairs):
        gap = segment[prev["after"]:p["start"]]
        m = _LEAD_QUALIFIER_RE.search(gap)
        p["gap"], p["lead"] = (gap[:m.start()], gap[m.start():]) if m else (gap, "")
        if _names_qualifier(p["gap"]):
            prev["ambiguous"] = p["ambiguous"] = True
    tail = segment[pairs[-1]["after"]:]
    if _ORGANIC_RE.search(tail) or detect_origin(tail).foreign:
        pairs[-1]["ambiguous"] = True


def _pair_origin(attr: str, subject_at: int, segment_context: str) -> Origin | None:
    """The origin named on a pair, or None when the pair must be skipped.

    Only the subject's own clause counts: text before the last comma, colon or bracket ahead
    of the subject is context ("complice la concorrenza del miele ucraino, il millefiori
    ..."). A foreign origin named there, or in the context shared by the segment, but not on
    the pair itself makes the pair ambiguous: it is neither given that origin nor Italy."""
    cut = max(attr.rfind(c, 0, subject_at) for c in ",:(")
    core_start = cut + 1
    origin = detect_origin(attr[core_start:])
    if origin.ambiguous:
        return None
    if not origin.foreign and (detect_origin(attr[:core_start]).foreign or detect_origin(segment_context).foreign):
        return None
    return origin


def _decide_packaging(*texts: str) -> str | None:
    """The first text that names a packaging decides; None when it names drums and tins together."""
    for text in texts:
        fusto, secchio = _packaging_in(text)
        if fusto and secchio:
            return None                      # drums and tins named together: which one?
        if fusto or secchio:
            return "fusto" if fusto else "secchio"
    return "non_specificato"


def extract_onm_prices(paragraphs: list[str]) -> list[dict]:
    """EUR/kg ranges with their variety, from market paragraphs, only when unambiguous.

    Rules: the sentence must carry a bulk context ("all'ingrosso", "fusto/fusti", "sfuso");
    the range must be written with an explicit €/kg unit; in each segment variety mentions
    and prices must alternate one-to-one. Packaging, organic and origin are read from the
    pair's own text: its phrase, a parenthetical right after it, and the words leading into
    it (see `_attribute_pairs`); a qualifier that could belong to two pairs skips both. The
    origin is Italy unless the subject's own clause names exactly one foreign origin (see
    `_pair_origin`). Packaging falls back to the segment's opening words, then to the
    sentence, only while no packaging word is tied to a single pair or opens a later segment.
    Each dict: variety, variety_raw, organic, low, high, origin_iso3, origin_label,
    packaging_code, sentence."""
    found: list[dict] = []
    for paragraph in paragraphs:
        for sentence in _sentences(paragraph):
            s = _clean(sentence).lower()
            if not _BULK_CONTEXT_RE.search(s):
                continue
            segments = []
            for k, segment in enumerate(_SEGMENT_SPLIT_RE.split(s)):
                pairs = _pair_tokens(_segment_tokens(segment), segment)
                if pairs:
                    _attribute_pairs(segment, pairs)
                    segments.append((k, segment, pairs))
            pair_level = [t for _, segment, pairs in segments for i, p in enumerate(pairs)
                          for t in (segment[p["start"]:p["end"]], p["trail"], p["gap"], p["lead"] if i else "")]
            pair_level += [pairs[0]["lead"] for k, _, pairs in segments if k > 0]
            fallback = not any(any(_packaging_in(t)) for t in pair_level)
            for _, segment, pairs in segments:
                segment_context = pairs[0]["lead"]
                for i, p in enumerate(pairs):
                    subject, price = p["subject"], p["price"]
                    if p["ambiguous"] or subject["kw"] is None or price["lo"] is None or not price["unit"]:
                        continue
                    low, high = parse_it_number(price["lo"]), parse_it_number(price["hi"])
                    if low is None or high is None or low > high or not (_plausible(low, "kg") and _plausible(high, "kg")):
                        continue
                    attr = p["lead"] + segment[p["start"]:p["end"]] + p["trail"]
                    shared = segment_context if i else ""
                    origin = _pair_origin(attr, len(p["lead"]) + subject["pos"] - p["start"], shared)
                    if origin is None:
                        continue
                    packaging = _decide_packaging(attr, *((segment_context, s) if fallback else ()))
                    if packaging is None:
                        continue
                    variety, organic = normalize_it_variety(subject["kw"])
                    named_organic = bool(_ORGANIC_RE.search(attr))
                    if not (organic or named_organic) and _ORGANIC_RE.search(shared):
                        continue                     # 'bio' opens the segment, not said of this pair
                    organic = organic or named_organic
                    found.append({
                        "variety": variety, "variety_raw": subject["kw"], "organic": organic,
                        "low": low, "high": high,
                        "origin_iso3": origin.iso3 if origin.foreign else MARKET_ISO3,
                        "origin_label": origin.label if origin.foreign else "Italia",
                        "packaging_code": packaging, "sentence": _clean(sentence),
                    })
    # The same variety/organic/origin/packaging twice with different numbers is ambiguous.
    by_key: dict[tuple, list[dict]] = {}
    for f in found:
        key = (f["variety_raw"], f["organic"], f["origin_iso3"], f["origin_label"], f["packaging_code"])
        by_key.setdefault(key, []).append(f)
    out = []
    for group in by_key.values():
        if len({(g["low"], g["high"]) for g in group}) == 1:
            out.append(group[0])
    return out


# ---- Annual Report PDF --------------------------------------------------------


@dataclass
class OnmAnnualLink:
    url: str
    title: str
    season: int | None
    published: date | None = None


def find_onm_annual_pdfs(content: bytes | str, base_url: str, *, published: date | None = None,
                         title: str | None = None) -> list[OnmAnnualLink]:
    """Annual-report PDF links ('REPORT-Annuale-2024.pdf', '...stagione-2025.pdf',
    'Report-2023-Il-Valore-della-Terra.pdf'); 'Prime Valutazioni' reports are excluded."""
    soup = _soup(content)
    links: dict[str, OnmAnnualLink] = {}
    for a in soup.find_all("a", href=True):
        url = urljoin(base_url, a["href"])
        fname = unquote(urlparse(url).path.rsplit("/", 1)[-1])
        if not fname.lower().endswith(".pdf"):
            continue
        text = _clean(a.get_text(" "))
        hay = f"{fname} {text}"
        if not _ONM_ANNUAL_RE.search(hay) or re.search(r"prime[\s_-]*valutazion", hay, re.I):
            continue
        season = _season_of(fname) or _season_of(text) or (_season_of(title) if title else None)
        links.setdefault(url, OnmAnnualLink(url, text or fname, season, published))
    return list(links.values())


@dataclass
class OnmAnnualTables:
    variety_rows: list[dict] = field(default_factory=list)
    variety_caption: str | None = None
    import_rows: list[dict] = field(default_factory=list)
    import_caption: str | None = None
    problems: list[str] = field(default_factory=list)


_TEXT_ROW_RE = re.compile(r"^(?P<label>[^\d]+?)\s+(?P<nums>(?:(?:\d+(?:[.,]\d+)?|n\.?d\.?|-|–)(?:\s+|$))+)$", re.I)
_SKIP_ROW_LABELS = re.compile(r"^(media|totale|media generale|italia|nord|centro|sud|isole|altri|altri paesi)\b")


def _is_caption(kind: str, line: str) -> bool:
    f = _fold(line)
    if not re.search(r"\bprezz", f):
        return False
    is_import = bool(re.search(r"import", f) and re.search(r"origine|paese|provenienza", f))
    if kind == "import":
        return is_import
    regional = re.search(r"\b(nord|centro|sud|isole|regione|regionale|regionali|biologic\w*)\b", f)
    return not re.search(r"import", f) and not regional and bool(re.search(r"ingrosso|fust", f))


def _value_columns(line: str, *, allow_single: bool) -> list[str] | None:
    """Price columns of a header line, in order: min / max / avg ('Media'), or a single
    'value' column ('Prezzo', '€/kg') when `allow_single`. Lines with digits are not headers."""
    f = _fold(line)
    if re.search(r"\d", f):
        return None
    cols = []
    for name, rx in (("min", r"\bmin(?:imo)?\b"), ("max", r"\bmax(?:imo)?\b"), ("avg", r"\bmedi[ao]\b")):
        m = re.search(rx, f)
        if m:
            cols.append((m.start(), name))
    if cols:
        return [name for _, name in sorted(cols)]
    if allow_single and re.search(r"\bprezz|/\s*kg\b", f):
        return ["value"]
    return None


def _parse_text_table(lines: list[str], start: int, problems: list[str], what: str) -> list[dict] | None:
    """Header within 3 lines after the caption, then 'Label n n n' rows until the first line
    that is not a row. A row with a different count of values than the header is skipped.
    A min/max/media header is preferred to a single-price header, so that a units line
    under the caption ('Euro al kg, IVA inclusa') is never taken for the header."""
    window = range(start, min(start + 3, len(lines)))
    for allow_single in (False, True):
        hit = next(((j, c) for j in window if (c := _value_columns(lines[j], allow_single=allow_single))), None)
        if hit:
            j, cols = hit
            break
    else:
        return None
    rows: list[dict] = []
    misses = 0
    for line in lines[j + 1:]:
        m = _TEXT_ROW_RE.match(line)
        if not m:
            if rows or misses >= 1:
                break
            misses += 1                                # tolerate one unit line such as "(€/kg)"
            continue
        label, tokens = _clean(m.group("label")), m.group("nums").split()
        if len(tokens) != len(cols):
            problems.append(f"ONM annual report, {what} '{label}': {len(tokens)} values for {len(cols)} columns; row skipped")
            continue
        try:
            values = dict(zip(cols, (parse_it_number(t) for t in tokens), strict=True))
        except ValueError:
            problems.append(f"ONM annual report, {what} '{label}': unparseable values {tokens}; row skipped")
            continue
        rows.append({"label": label, **values})
    return rows


def _price_triplet(row: dict) -> tuple[float | None, float | None, float | None]:
    low, high = row.get("min"), row.get("max")
    value = row.get("avg") or row.get("value")
    if value is None and low is not None and high is not None:
        value = round((low + high) / 2, 4)
    return low, high, value


def parse_onm_annual_pdf(content: bytes) -> OnmAnnualTables:
    """'Prezzi all'ingrosso ... per varietà' and 'Prezzi del miele d'importazione per paese di
    origine' tables, read only when unambiguous: exactly one caption of each kind followed by
    a Min/Max/Media header and 'Label n n n' rows. Rows whose label is not a variety (resp. a
    country) are skipped with a problem note."""
    out = OnmAnnualTables()
    pages = _pdf_lines(content)
    for kind in ("variety", "import"):
        candidates = []
        for lines in pages:
            for i, line in enumerate(lines):
                if _is_caption(kind, line):
                    tbl = _parse_text_table(lines, i + 1, out.problems, kind)
                    if tbl:
                        candidates.append((line, tbl))
        if not candidates:
            continue
        if len(candidates) > 1:
            out.problems.append(f"ONM annual report: {len(candidates)} '{kind}' price tables match; ambiguous, none imported")
            continue
        caption, rows = candidates[0]
        for r in rows:
            low, high, value = _price_triplet(r)
            if value is None or _SKIP_ROW_LABELS.match(_fold(r["label"])):
                continue
            if low is not None and high is not None and low > high:
                out.problems.append(f"ONM annual report, {kind} '{r['label']}': min > max; row skipped")
                continue
            if not all(_plausible(v, "kg") for v in (low, high, value)):
                out.problems.append(f"ONM annual report, {kind} '{r['label']}': implausible EUR/kg; row skipped")
                continue
            row = {"label": r["label"], "low": low, "high": high, "value": value}
            if kind == "variety":
                variety, organic = normalize_it_variety(r["label"])
                if variety == Variety.UNSPECIFIED.value:
                    out.problems.append(f"ONM annual report: '{r['label']}' is not a variety; row skipped")
                    continue
                out.variety_rows.append({**row, "variety": variety, "organic": organic})
                out.variety_caption = caption
            else:
                iso3 = lookup_iso3(r["label"])
                if not iso3 or len(iso3) != 3 or iso3 in ("WLD", "ITA"):
                    out.problems.append(f"ONM annual report: '{r['label']}' is not a recognised origin country; row skipped")
                    continue
                out.import_rows.append({**row, "origin_iso3": iso3})
                out.import_caption = caption
    return out


class OnmInformamieleCollector(Collector):
    key = "onm_informamiele"
    name = "Osservatorio Nazionale Miele - Rilevazione mensile e Report annuale"
    publisher = "Osservatorio Nazionale Miele"
    homepage = "https://www.informamiele.it/monitoraggio-produzione-e-mercato/"
    kind = SourceKind.HTML
    reliability = Reliability.INDUSTRY
    category = "reports"
    country_iso3 = "ITA"
    language = "it"
    expected_update = "Mensile (circa 3 settimane dopo il mese); Report annuale a marzo"
    expected_update_en = "Monthly (about 3 weeks after the month); annual report in March"
    expected_max_age_days = 60
    terms_note = ("© Osservatorio Nazionale Miele. Pagine pubbliche: dal 2023 solo sintesi; le tabelle complete "
                  "sono su Mieleinforma (registrazione). Prezzi estratti dal testo = provvisori, da verificare. "
                  "Uso interno; chiedere il consenso ONM per la ridistribuzione.")
    schedule = {"trigger": "cron", "day_of_week": "mon", "hour": 8, "minute": 20}

    def collect(self, ctx: CollectContext) -> None:
        posts = self._discover(ctx)
        monthly = sorted((p for p in posts if p.kind == "monthly"),
                         key=lambda p: (p.ref_year, p.ref_month), reverse=True)
        seen: set[tuple[int, int]] = set()
        for post in monthly:
            if (post.ref_year, post.ref_month) in seen:
                continue
            seen.add((post.ref_year, post.ref_month))
            if len(seen) > ONM_MAX_BULLETINS:
                break
            self._bulletin(ctx, post)
            ctx.checkpoint()
        self._annual(ctx, posts)
        ctx.checkpoint()

    # -- discovery: RSS feed, then WP REST API, then HTML listings ---------------
    def _discover(self, ctx: CollectContext) -> list[OnmPost]:
        attempts = [("feed", ONM_FEED_URL, discover_onm_from_feed),
                    ("wp-json", ONM_WP_API_URL, discover_onm_from_wp_json)]
        attempts += [("listing", url, discover_onm_from_listing) for url in ONM_LISTING_URLS]
        errors, collected, any_ok = [], [], False
        for name, url, parser in attempts:
            try:
                doc = ctx.fetch(url, store=False)
                posts = parser(doc.content, doc.url)
            except Offline:
                raise
            except CollectorError as exc:
                errors.append(f"{name}: {exc}")
                continue
            for p in posts:
                p.copy_doc = doc
            any_ok = True
            collected.extend(posts)
            if any(p.kind == "monthly" for p in posts):
                log.info("ONM bulletins discovered via %s", name)
                return collected
            errors.append(f"{name}: no 'rilevazione mensile' post")
        if not any_ok:
            raise CollectorError("ONM: bulletins could not be discovered (" + "; ".join(errors) + ")")
        ctx.warn("ONM: no 'rilevazione mensile' bulletin found (" + "; ".join(errors) + ")")
        return collected

    # -- monthly bulletin -----------------------------------------------------------
    def _bulletin(self, ctx: CollectContext, post: OnmPost) -> None:
        raw_id, parsed_from = None, post.url
        try:
            doc = ctx.fetch(post.url, title=post.title, published_at=post.published)
            if doc.unchanged and not ctx.force:
                return
            page, raw_id = parse_onm_post(doc.content), doc.raw_document_id
        except Offline:
            raise
        except CollectorError as exc:
            if not post.content_html:
                ctx.warn(f"ONM bulletin {post.url}: download failed ({exc})")
                return
            # The text comes from the discovery response: archive exactly those bytes (only
            # now, so discovery does not store the feed on every run) and point to them.
            src = post.copy_doc
            if src is not None:
                raw_id, _ = ctx.store_raw(src.url, src.content, src.content_type,
                                          title=f"{post.title} (copia da feed/API, pagina non disponibile)",
                                          published_at=post.published)
                raw_id, parsed_from = raw_id or None, src.url
            ctx.warn(f"ONM bulletin {post.url}: page unavailable ({exc}); text and prices taken from the "
                     f"feed/API copy {parsed_from if src is not None else '(not archived)'}")
            page = parse_onm_post(post.content_html)
        y, m = post.ref_year, post.ref_month
        period = f"{y}-{m:02d}"
        published = page.published or post.published
        narrative = "\n\n".join(page.market_paragraphs) or None
        ctx.add_report(report_key=f"rilevazione-mensile-{period}", title=post.title or page.title or period,
                       url=post.url, published_at=published, period_label=period,
                       raw_document_id=raw_id, narrative=narrative)
        if not page.has_market_section:
            ctx.warn(f"ONM bulletin {period}: no 'Mercato' section heading found"
                     + ("; market paragraphs taken by keyword" if narrative else "; no market text stored"))
        start, end = month_bounds(y, m)
        for p in extract_onm_prices(page.market_paragraphs):
            org = "bio" if p["organic"] else "conv"
            origin_key = p["origin_iso3"] or _slug(p["origin_label"])
            ctx.add_price(
                series_key=f"onm|{period}|{_slug(p['variety_raw'])}|{org}|{origin_key}|{p['packaging_code']}",
                price_type=PriceType.WHOLESALE_BULK,
                variety=p["variety"], variety_raw=p["variety_raw"], organic=p["organic"],
                price_value=round((p["low"] + p["high"]) / 2, 4), price_low=p["low"], price_high=p["high"],
                currency=CURRENCY, unit="kg",
                period_start=start, period_end=end, period_label=period, frequency="M",
                market_iso3=MARKET_ISO3, market_location="Italia (rilevazione ONM)",
                origin_iso3=p["origin_iso3"], origin_label=p["origin_label"],
                terms=_terms(p["packaging_code"].replace("_", " "), "mercato all'ingrosso", page.price_basis),
                published_at=published, source_url=post.url, raw_document_id=raw_id,
                data_status=DataStatus.PROVISIONAL,
                notes=f"{TEXT_EXTRACT_NOTE}: «{p['sentence'][:600]}»",
                extra={"context_sentence": p["sentence"], "packaging_code": p["packaging_code"],
                       "drum": p["packaging_code"] == "fusto", "extraction": "regex", "needs_review": True,
                       "price_basis": page.price_basis, "parsed_from": parsed_from},
            )

    # -- Annual Report ------------------------------------------------------------------
    def _annual(self, ctx: CollectContext, posts: list[OnmPost]) -> None:
        annual_posts = [p for p in posts if p.kind == "annual"]
        dates = {p.season: p.published for p in annual_posts if p.season and p.published}
        links: dict[str, OnmAnnualLink] = {}
        for p in annual_posts:
            if p.content_html:
                for link in find_onm_annual_pdfs(p.content_html, p.url, published=p.published, title=p.title):
                    links.setdefault(link.url, link)
        try:
            archive = ctx.fetch(ONM_REPORT_ARCHIVE_URL, store=False)
            for link in find_onm_annual_pdfs(archive.content, archive.url):
                links.setdefault(link.url, link)
        except Offline:
            raise
        except CollectorError as exc:
            ctx.warn(f"ONM annual reports archive unavailable ({exc})")
        candidates = [link for link in links.values() if link.season]
        if candidates:
            newest = max(candidates, key=lambda link: (link.season, link.published or date.min))
            newest.published = newest.published or dates.get(newest.season)
            self._annual_pdf(ctx, newest)
        elif links:
            ctx.warn("ONM annual report PDF found but its season could not be determined: " + ", ".join(links))
        # announcement posts (e.g. when the full text is only on Mieleinforma)
        for p in annual_posts:
            if p.season:
                ctx.add_report(report_key=f"report-annuale-{p.season}", title=p.title, url=p.url,
                               published_at=p.published, period_label=str(p.season))

    def _annual_pdf(self, ctx: CollectContext, link: OnmAnnualLink) -> None:
        doc = ctx.fetch(link.url, title=link.title, published_at=link.published)
        if doc.unchanged and not ctx.force:
            return
        season = link.season
        ctx.add_report(report_key=f"report-annuale-{season}", title=f"Report annuale ONM - stagione {season}",
                       url=link.url, published_at=link.published, period_label=str(season),
                       raw_document_id=doc.raw_document_id)
        try:
            tables = parse_onm_annual_pdf(doc.content)
        except CollectorError as exc:
            ctx.warn(f"ONM annual report {season}: {exc}; registered without prices")
            return
        for p in tables.problems:
            ctx.warn(p)
        if not tables.variety_rows and not tables.import_rows:
            ctx.warn(f"ONM annual report {season}: price tables not recognised; registered without prices")
            return
        start, end = year_bounds(season)
        common = dict(price_type=PriceType.WHOLESALE_BULK, currency=CURRENCY, unit="kg",
                      period_start=start, period_end=end, period_label=str(season), frequency="A",
                      market_iso3=MARKET_ISO3, market_location="Italia (Report annuale ONM)",
                      published_at=link.published, source_url=link.url, raw_document_id=doc.raw_document_id,
                      data_status=DataStatus.PUBLISHED)
        for r in tables.variety_rows:
            ctx.add_price(series_key=f"onm-annuale|{season}|varieta|{_slug(r['label'])}",
                          variety=r["variety"], variety_raw=r["label"][:200], organic=r["organic"],
                          price_value=r["value"], price_low=r["low"], price_high=r["high"],
                          origin_iso3=MARKET_ISO3, origin_label="Italia",
                          terms=_terms(tables.variety_caption),
                          extra={"table": tables.variety_caption, "statistic": "annual", "channel": "producer_to_packer"},
                          **common)
        import_variety, _ = normalize_it_variety(tables.import_caption or "")
        if import_variety == Variety.OTHER.value:
            import_variety = Variety.UNSPECIFIED.value     # caption names no variety
        for r in tables.import_rows:
            ctx.add_price(series_key=f"onm-annuale|{season}|import|{r['origin_iso3']}",
                          variety=import_variety, variety_raw=None, organic=False,
                          price_value=r["value"], price_low=r["low"], price_high=r["high"],
                          origin_iso3=r["origin_iso3"], origin_label=r["label"][:120],
                          terms=_terms(tables.import_caption),
                          extra={"table": tables.import_caption, "statistic": "annual", "channel": "import"},
                          **common)


# ===========================================================================
# 4) CCIAA Arezzo-Siena — weekly price list (PDF), honey lines
# ===========================================================================

SIENA_BASE = "https://www.as.camcom.it"
SIENA_INDEX_URL = SIENA_BASE + "/pubblicazioni-e-listini-prezzi/prezzi"
SIENA_ARCHIVE_URL = SIENA_BASE + "/listini-settimanali-provincia-siena-anno-{year}"
_SIENA_FILE_RE = re.compile(r"n[\s._°º]*(\d{1,3})[\s._-]*del[\s._-]*(\d{1,2})[\s._-](\d{1,2})[\s._-](\d{4})", re.I)
_SIENA_ARCHIVE_RE = re.compile(r"listin\w*-settimanal\w*-provincia-siena-anno-(\d{4})", re.I)
_SIENA_HEADER_RE = re.compile(r"\bda\s+euro\b.*\ba\s+euro\b|\bmin\w*\b.*\bmax\w*\b|prezzo\s+minimo", re.I)
_SIENA_LIST_RE = re.compile(r"listino\s+(?:prezzi\s+)?n\.?\s*[°º]?\s*(\d{1,3})\s+del\s+(\S+(?:\s+\w+\s+\d{4})?)", re.I)
_HONEY_LINE_RE = re.compile(
    r"^(?P<label>miel[ei]\b.*?)\s+(?:(?P<unit>kg\.?|q\.?\s?l[ie]\.?|ql|q|quintale|€/kg|euro/kg)\s+)?"
    r"(?P<n1>\d+(?:[.,]\d+)?|-|n\.?q\.?)(?:\s+(?P<n2>\d+(?:[.,]\d+)?|-|n\.?q\.?))?$",
    re.I,
)


@dataclass
class SienaLink:
    url: str
    number: int | None
    list_date: date
    title: str


@dataclass
class SienaList:
    number: int | None
    list_date: date | None
    rows: list[dict]
    problems: list[str] = field(default_factory=list)
    vat_included: bool | None = None


def find_siena_pdfs(content: bytes | str, base_url: str = SIENA_INDEX_URL) -> tuple[list[SienaLink], list[str]]:
    """Weekly list PDFs linked from a page (newest first) and yearly archive pages found."""
    soup = _soup(content)
    links: dict[str, SienaLink] = {}
    archives: list[tuple[int, str]] = []
    for a in soup.find_all("a", href=True):
        url = urljoin(base_url, a["href"])
        path = unquote(urlparse(url).path)
        text = _clean(a.get_text(" "))
        if path.lower().endswith(".pdf"):
            fname = path.rsplit("/", 1)[-1]
            if "listino" not in _fold(f"{fname} {text}"):
                continue
            m = _SIENA_FILE_RE.search(fname) or _SIENA_FILE_RE.search(text)
            number, d = (int(m.group(1)), _safe_date(m.group(4), m.group(3), m.group(2))) if m else (None, parse_it_date(text))
            if d is not None:
                links.setdefault(url, SienaLink(url, number, d, text or fname))
        else:
            m = _SIENA_ARCHIVE_RE.search(path)
            if m and url not in [u for _, u in archives]:
                archives.append((int(m.group(1)), url))
    ordered = sorted(links.values(), key=lambda link: (link.list_date, link.number or 0), reverse=True)
    return ordered, [u for _, u in sorted(archives, reverse=True)]


def _price_type_from_wording(text: str | None) -> tuple[PriceType | None, str | None]:
    t = _fold(text)
    kinds = []
    if re.search(r"\bal\s+consumo\b|\bal\s+dettaglio\b", t):
        kinds.append((PriceType.RETAIL, "prezzi al consumo"))
    if re.search(r"alla\s+produzione|franco\s+produttore|all'origine|pagati\s+ai\s+produttori", t):
        kinds.append((PriceType.PRODUCER, "prezzi alla produzione"))
    if re.search(r"ingrosso", t):
        kinds.append((PriceType.WHOLESALE_BULK, "prezzi all'ingrosso"))
    return kinds[0] if len(kinds) == 1 else (None, None)


def parse_siena_pdf(content: bytes) -> SienaList:
    """Honey lines of a weekly list: 'Miele millefiori  kg  6,00  7,00' under columns
    'u. misura | da Euro | a Euro'. Each row carries the price type stated by its section
    heading, else by the list title, else wholesale (it is a chamber wholesale list)."""
    pages = _pdf_lines(content)
    lines = [ln for page in pages for ln in page]
    full = "\n".join(lines)
    m = _SIENA_LIST_RE.search(full)
    number, list_date = (int(m.group(1)), parse_it_date(m.group(2))) if m else (None, None)
    out = SienaList(number=number, list_date=list_date, rows=[], vat_included=_vat_flag(full))
    header_found = False
    section = None
    honey: list[tuple[str, re.Match, str | None]] = []
    for line in lines:
        if _SIENA_HEADER_RE.search(line):
            header_found = True
            continue
        hm = _HONEY_LINE_RE.match(line)
        if hm:
            honey.append((line, hm, section))
        elif not re.search(r"\d", line) and len(line) <= 90 and (line.isupper() or line.endswith(":")):
            section = line
    if honey and not header_found:
        raise SchemaDrift("Siena price list: honey line(s) found but no 'da Euro / a Euro' (or min/max) "
                          "column header; the column layout has changed")
    head_type, head_words = _price_type_from_wording(" ".join(lines[:12]))
    for line, hm, sec in honey:
        label = _clean(hm.group("label"))
        unit = normalize_unit(hm.group("unit")) if hm.group("unit") else None
        if unit is None:
            out.problems.append(f"Siena '{line}': unit of measure missing or unknown; row skipped")
            continue
        try:
            n1, n2 = parse_it_number(hm.group("n1")), parse_it_number(hm.group("n2"))
        except ValueError:
            out.problems.append(f"Siena '{line}': unparseable price; row skipped")
            continue
        if n1 is None and n2 is None:
            continue                                       # not quoted this week
        low, high = (n1, n2) if n2 is not None else (None, None)
        value = round((n1 + n2) / 2, 4) if n1 is not None and n2 is not None else (n1 if n1 is not None else n2)
        if low is not None and high is not None and low > high:
            out.problems.append(f"Siena '{line}': min > max; row skipped")
            continue
        if not all(_plausible(v, unit) for v in (low, high, value)):
            out.problems.append(f"Siena '{line}': implausible price; row skipped")
            continue
        sec_type, sec_words = _price_type_from_wording(sec)
        price_type, words, basis = (sec_type, sec_words, "section") if sec_type else \
            (head_type, head_words, "title") if head_type else \
            (PriceType.WHOLESALE_BULK, "listino camerale (tipo di prezzo non indicato)", "default")
        variety, organic = normalize_it_variety(label)
        out.rows.append({"label": label, "variety": variety, "organic": organic, "unit": unit,
                         "low": low, "high": high, "value": value, "price_type": price_type,
                         "price_type_words": words, "price_type_basis": basis, "section": sec})
    return out


class SienaHoneyCollector(Collector):
    key = "cciaa_siena_miele"
    name = "CCIAA Arezzo-Siena - Listino settimanale (provincia di Siena): miele"
    publisher = "Camera di Commercio di Arezzo-Siena"
    homepage = SIENA_INDEX_URL
    kind = SourceKind.PDF
    reliability = Reliability.INDUSTRY
    category = "prices"
    country_iso3 = "ITA"
    language = "it"
    expected_update = "Settimanale (listino del mercoledì)"
    expected_update_en = "Weekly (Wednesday price list)"
    expected_max_age_days = 21
    terms_note = ("Listino pubblico a titolo puramente informativo (in parte rilevato dall'ufficio prezzi, in parte da "
                  "una commissione). Prezzi locali, non quotazioni in fusti: solo come controllo di coerenza.")
    schedule = {"trigger": "cron", "day_of_week": "thu", "hour": 9, "minute": 5}

    def collect(self, ctx: CollectContext) -> None:
        link = self._discover(ctx)[0]
        doc = ctx.fetch(link.url, title=link.title, published_at=link.list_date)
        if doc.unchanged and not ctx.force:
            return
        parsed = parse_siena_pdf(doc.content)           # SchemaDrift -> run fails loudly
        for p in parsed.problems:
            ctx.warn(p)
        list_date = parsed.list_date or link.list_date
        if parsed.list_date and parsed.list_date != link.list_date:
            ctx.warn(f"Siena list {link.url}: date in the PDF ({parsed.list_date}) differs from the file name "
                     f"({link.list_date}); the PDF date is used")
        number = parsed.number or link.number
        if not parsed.rows:
            ctx.warn(f"Siena list n. {number} del {list_date:%d.%m.%Y}: no honey line found")
            return
        start = list_date - timedelta(days=list_date.weekday())
        iso = list_date.isocalendar()
        label = f"{iso.year}-W{iso.week:02d}"
        for r in parsed.rows:
            ctx.add_price(
                series_key=f"siena|{_slug(r['label'])}|{label}",
                price_type=r["price_type"],
                variety=r["variety"], variety_raw=r["label"][:200], organic=r["organic"],
                price_value=r["value"], price_low=r["low"], price_high=r["high"],
                currency=CURRENCY, unit=r["unit"],
                period_start=start, period_end=start + timedelta(days=6), period_label=label, frequency="W",
                market_iso3=MARKET_ISO3, market_location="Siena",
                origin_iso3=MARKET_ISO3, origin_label="Italia",
                terms=_terms(f"listino settimanale n. {number} del {list_date:%d.%m.%Y}", r["price_type_words"],
                             "confezione non indicata", _vat_words(parsed.vat_included)),
                published_at=list_date, source_url=doc.url, raw_document_id=doc.raw_document_id,
                data_status=DataStatus.PUBLISHED,
                extra={"list_number": number, "list_date": list_date.isoformat(), "section": r["section"],
                       "price_type_basis": r["price_type_basis"], "packaging": None,
                       "packaging_code": "non_specificato", "vat_included": parsed.vat_included,
                       "channel": "chamber_local"},
            )

    def _discover(self, ctx: CollectContext) -> list[SienaLink]:
        errors: list[str] = []
        links: list[SienaLink] = []
        archives: list[str] = []
        try:
            index = ctx.fetch(SIENA_INDEX_URL, store=False)
            links, archives = find_siena_pdfs(index.content, index.url)
        except Offline:
            raise
        except CollectorError as exc:
            errors.append(f"index: {exc}")
        if not links:
            year = _today().year
            for url in (archives or [SIENA_ARCHIVE_URL.format(year=year), SIENA_ARCHIVE_URL.format(year=year - 1)])[:2]:
                try:
                    page = ctx.fetch(url, store=False)
                    links, _ = find_siena_pdfs(page.content, page.url)
                except Offline:
                    raise
                except CollectorError as exc:
                    errors.append(f"{url}: {exc}")
                    continue
                if links:
                    break
        if not links:
            raise SchemaDrift("Siena: no weekly price-list PDF link (listino_prezzi_n_..._del_....pdf) found ("
                              + ("; ".join(errors) or "pages fetched but no matching links") + ")")
        return links
