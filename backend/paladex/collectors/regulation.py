"""Regulation watch: official legal documents that affect bulk honey imports into the US and EU.

Two keyless collectors. Both write ``RegulationItem`` rows through ``ctx.add_regulation``, which
is append-only: a document already stored (same source and reference) is never rewritten.

* ``us_federal_register``: the US Federal Register API v1. A few saved searches cover Commerce
  (ITA) antidumping notices on raw honey (Argentina, Brazil, India, Vietnam) and on honey from
  China, USITC and FDA notices on honey, and presidential tariff documents that mention honey or
  a honey origin. ``reference`` is the FR document number and ``summary_en`` is the official
  abstract, as published.
* ``eurlex_honey``: EU legislation from the Publications Office CELLAR SPARQL endpoint (the
  sanctioned machine channel behind EUR-Lex). It runs two queries: (a) acts whose English title
  mentions honey, and (b) acts that amend, are based on, correct or repeal the Honey Directive
  (32001L0110), the "Breakfast Directive" (32024L1438) or the third-country list regulation
  (32021R0405). ``reference`` is the CELEX number.

Verification status (read this before changing anything)
--------------------------------------------------------
Neither host could be reached while this module was written: sandbox egress was blocked. Every
endpoint, parameter and field name comes from ``docs/research/regulation.json``, which is marked
``from_memory_unverified``. The module is therefore defensive:

* Response shapes are validated on every run. If a response is not in the documented shape, the
  collector raises ``SchemaDrift`` and stores nothing from it. Rows that are merely malformed are
  skipped with ``ctx.warn``.
* Start-up probes check the assumptions that would otherwise fail silently:
    - Federal Register: the agency slugs used as filters are checked against ``/agencies``
      (at most monthly). Results that do not match the requested agency or type are dropped and
      reported. A request rejected because of the unverified optional fields is retried with the
      default fields. A missing ``effective_on`` key on final rules is reported.
    - CELLAR: a canary. Directive (EU) 2024/1438 is known to amend 32001L0110 and has "honey" in
      its English title, so the related-acts query (and the title query, when its window covers
      14 May 2024) must return it with a date and a title. If it does not, the CDM property names
      or the endpoint have changed: ``SchemaDrift``, nothing stored.
* No value is ever invented. Fields the source does not provide stay empty. Examples: CELLAR has
  no official abstract, so ``summary_en`` is None for EU acts; ``effective_date`` is None when
  the source gives none.

Federal Register relevance (checked against the live API, November 2026)
------------------------------------------------------------------------
``conditions[term]`` searches the full text, so a phrase search for "raw honey" also returns
notices on glycine, rebar, plywood ... whose footnotes cite a honey case ("See, e.g., Raw Honey
from the Socialist Republic of Vietnam ..."). A document is therefore stored only when:

* "honey" (not the insect) is in its title or official abstract; or
* for Commerce omnibus notices (initiation / opportunity to request / rescission of
  administrative reviews, which have no honey abstract), the search ``excerpts`` show a honey
  case listed with its case number ("ARGENTINA: Raw Honey, A-357-823"), not merely cited; or
* for presidential tariff documents, the title, abstract or excerpts mention honey or HTS 0409.
  The tariff annexes are printed as images in the Federal Register (``[GRAPHIC] [TIFF
  OMITTED]``) and are not searchable, and the full-text downloads redirect to a bot check, so
  a tariff action that does not name honey in its text is not stored (duty rates on 0409 come
  from the tariff collectors instead).

Future work (M5): for ITA "Final Results of Antidumping Duty Administrative Review" notices,
fetch ``full_text_xml_url`` (GPO XML), parse the ``<GPOTABLE>`` rows (exporter, weighted-average
margin, period of review) into a dedicated AD-rate table, and suggest ``SupplierQuote.duty_pct``
from it. Until then these notices are stored as RegulationItem rows only.
"""
from __future__ import annotations

import hashlib
import html
import json
import logging
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

from ..enums import Reliability, SourceKind
from ..models import AppSetting
from ..reference.countries import COUNTRY_KEYWORDS, countries
from .base import CollectContext, Collector, CollectorError, FetchResult, Offline

log = logging.getLogger(__name__)

JSON_HEADERS = {"Accept": "application/json"}


def today() -> date:
    """Reference date for look-back windows (indirection so tests can pin it)."""
    return date.today()


class SchemaDrift(CollectorError):
    """The source answered, but not in the documented shape. Nothing from it is stored."""


class SourceQueryError(CollectorError):
    """The source rejected one query (HTTP error or an error object). Other queries may still work."""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


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


def _snippet(content: bytes, n: int = 200) -> str:
    return re.sub(r"\s+", " ", content[:n].decode("utf-8", errors="replace")).strip()


def _load_json(content: bytes, what: str) -> Any:
    try:
        return json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise SchemaDrift(f"{what}: response is not JSON ({exc}); starts with {_snippet(content, 120)!r}") from exc


_TAG_RE = re.compile(r"<[^>]+>")


def clean_text(value: Any) -> str | None:
    """Plain text as published: HTML tags and entities removed, whitespace collapsed. None if empty."""
    if not isinstance(value, str):
        return None
    text = re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", value))).strip()
    return text or None


def parse_iso_date(value: Any) -> date | None:
    """`YYYY-MM-DD` (optionally followed by a time or zone, as SPARQL dates may be). None otherwise."""
    if not isinstance(value, str):
        return None
    m = re.match(r"^\s*(\d{4}-\d{2}-\d{2})", value)
    if not m:
        return None
    try:
        return date.fromisoformat(m.group(1))
    except ValueError:
        return None


# "honey" as a word, but not the insect: "honey bee(s)", "honey-bee" do not count ("honeybee"
# never matches because of the word boundary). Used to drop pollinator noise from broad searches.
HONEY_RE = re.compile(r"\bhoney\b(?![\s-]*bees?\b)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Country detection (title / abstract -> ISO3 list)
# ---------------------------------------------------------------------------

# Extra English names that legal texts use and that neither COUNTRY_KEYWORDS nor the reference
# names cover.
_EXTRA_EN_NAMES: dict[str, tuple[str, ...]] = {
    "VNM": ("viet nam",),
    "TUR": ("türkiye", "turkiye"),
    "RUS": ("russian federation",),
    "KOR": ("republic of korea",),
    "MDA": ("republic of moldova",),
    "CZE": ("czech republic",),
    "USA": ("united states of america",),
}

# Words that are also common nouns or names ("turkey" the bird, "chile" the pepper, a person
# called Jordan). They count only when capitalised (Turkey, TURKEY).
_CASE_SENSITIVE = frozenset({"turkey", "chile", "jordan"})

# Phrases that contain a country word but do not refer to that country. US federal documents
# talk about New Mexico and Indian tribes far more often than about Mexico or India.
_FALSE_FRIENDS = re.compile(
    r"\bnew mexico\b|\bamerican indians?\b|\bindian (?:tribes?|tribal|affairs|health|country|reservations?|lands?)\b",
    re.IGNORECASE,
)


def _build_country_matchers() -> list[tuple[str, re.Pattern[str] | None, re.Pattern[str] | None]]:
    words: dict[str, set[str]] = defaultdict(set)
    for iso3, kws in COUNTRY_KEYWORDS.items():
        words[iso3].update(k.lower() for k in kws)
    for c in countries():
        words[c["iso3"]].add(c["name_en"].lower())
    for iso3, names in _EXTRA_EN_NAMES.items():
        words[iso3].update(names)
    out: list[tuple[str, re.Pattern[str] | None, re.Pattern[str] | None]] = []
    for iso3 in sorted(words):
        plain = sorted((w for w in words[iso3] if w not in _CASE_SENSITIVE), key=len, reverse=True)
        cased = sorted(w for w in words[iso3] if w in _CASE_SENSITIVE)
        p = re.compile(r"(?<!\w)(?:" + "|".join(map(re.escape, plain)) + r")(?!\w)", re.IGNORECASE) if plain else None
        forms = [re.escape(f) for w in cased for f in (w.capitalize(), w.upper())]
        c = re.compile(r"(?<!\w)(?:" + "|".join(forms) + r")(?!\w)") if forms else None
        out.append((iso3, p, c))
    return out


_COUNTRY_MATCHERS = _build_country_matchers()


def detect_countries(*texts: str | None, exclude: Iterable[str] = ()) -> list[str]:
    """ISO3 codes of the countries named in `texts`, in order of first mention.

    Uses ``reference.countries.COUNTRY_KEYWORDS`` plus the English country names of the reference
    list. `exclude` drops codes that would be noise, e.g. "USA" for Federal Register documents,
    which all name US agencies."""
    text = "\n".join(t for t in texts if t)
    if not text:
        return []
    text = _FALSE_FRIENDS.sub(lambda m: " " * len(m.group(0)), text)
    skip = set(exclude)
    first: dict[str, int] = {}
    for iso3, plain, cased in _COUNTRY_MATCHERS:
        if iso3 in skip:
            continue
        hits = [m.start() for pat in (plain, cased) if pat is not None for m in (pat.search(text),) if m]
        if hits:
            first[iso3] = min(hits)
    return sorted(first, key=lambda k: (first[k], k))


# ===========================================================================
# 1) US Federal Register API v1
# ===========================================================================

FR_API_BASE = "https://www.federalregister.gov/api/v1"
FR_SEARCH_URL = f"{FR_API_BASE}/documents.json"
FR_AGENCIES_URL = f"{FR_API_BASE}/agencies"
FR_HOST = "www.federalregister.gov"

FR_PER_PAGE = 100
FR_MAX_PAGES = 20                 # 2,000 documents per query and run: far above honey volumes
FR_BACKFILL_DAYS = 3 * 365        # first run (or force): about three years of documents
FR_OVERLAP_DAYS = 7               # later runs: from the last complete run minus a week
FR_AGENCY_PROBE_DAYS = 30         # re-check the agency slugs at most monthly (every run while one is missing)

# Fields requested with fields[]. The "core" ones are believed to be the API defaults; the
# optional ones were unverified names (the live API accepts them all). If the API rejects them,
# the run falls back to the core set. "excerpts" is the search-hit highlighting
# (<span class="match">...</span>), used by the relevance rules.
FR_FIELDS: tuple[str, ...] = (
    "document_number", "title", "type", "abstract", "publication_date", "effective_on",
    "html_url", "pdf_url", "agencies", "action", "citation", "excerpts",
)
FR_OPTIONAL_FIELDS: tuple[str, ...] = ("effective_on", "action", "citation")
FR_CORE_FIELDS: tuple[str, ...] = tuple(f for f in FR_FIELDS if f not in FR_OPTIONAL_FIELDS)

# conditions[type][] codes -> the label the API returns in each result's "type" field.
FR_TYPE_CODES: dict[str, str] = {
    "RULE": "Rule", "PRORULE": "Proposed Rule", "NOTICE": "Notice", "PRESDOCU": "Presidential Document",
}
_FR_TYPE_TO_DOC_TYPE = {"Rule": "rule", "Proposed Rule": "proposed_rule", "Notice": "notice"}
# A factual reading of the document type, not a legal-status claim (we never say "in force").
_FR_TYPE_TO_STATUS = {"Rule": "final", "Proposed Rule": "proposed", "Notice": "published",
                      "Presidential Document": "published"}

_ANTIDUMPING_RE = re.compile(r"\banti-?dumping\b", re.IGNORECASE)
# "Georgia" in US federal documents is nearly always the US state, and "USA" is in every one.
_FR_EXCLUDE_COUNTRIES = ("USA", "GEO")

# A honey AD/CVD case *listed* in an omnibus notice: "ARGENTINA: Raw Honey, A-357-823",
# "Raw Honey A-351-857", "Raw Honey, 11 A-552-833" (a footnote number in between). A citation
# ("See, e.g., Raw Honey from ...: Final Results") has no case number after the product name.
_HONEY_CASE_RE = re.compile(r"\bhoney\b\s*,?\s*(?:\d{1,3}\s+)?(?P<case>[AC]-(?P<cc>\d{3})-\d{3})\b", re.IGNORECASE)
# Commerce case-number country prefixes of the honey orders (A-357-823 AR, A-351-857 BR,
# A-533-903 IN, A-552-833 VN, A-570-863 CN).
_CASE_COUNTRY = {"357": "ARG", "351": "BRA", "533": "IND", "552": "VNM", "570": "CHN"}
# HTS heading 0409 (natural honey) as printed: "0409", "0409.00.00", "0409 00 00".
_HTS_0409_RE = re.compile(r"(?<![\d.])0409(?:[.\s]?00(?:[.\s]?00)?)?(?![\d])")


class Keep(StrEnum):
    """Which results of a saved search are relevant enough to store (see the module docstring)."""

    HONEY = "honey"                  # title/abstract must mention honey
    HONEY_AD = "honey_ad"            # ... or the excerpts list a honey case number (omnibus notices)
    HONEY_TEXT = "honey_text"        # ... or the excerpts mention honey / HTS 0409 (presidential tariff docs)


@dataclass(frozen=True)
class FrQuery:
    qid: str
    label: str
    term: str                           # conditions[term] (full-text; quotes make a phrase)
    agencies: tuple[str, ...] = ()      # conditions[agencies][] slugs
    types: tuple[str, ...] = ()         # conditions[type][] codes (FR_TYPE_CODES)
    keep: Keep = Keep.HONEY

    @property
    def state_key(self) -> str:
        """Per-query bookkeeping key. Changing a query's definition changes the key, so the
        changed query starts with a fresh back-fill instead of an incremental window."""
        sig = repr((self.term, self.agencies, self.types, self.keep.value)).encode()
        return f"{self.qid}:{hashlib.sha1(sig).hexdigest()[:8]}"


# Saved searches (docs/research/regulation.json, "US Federal Register API v1" and recommendation).
FR_QUERIES: tuple[FrQuery, ...] = (
    # Commerce/ITA AD notices on the 2022 raw-honey orders (AR, BR, IN, VN), including the monthly
    # omnibus "Initiation of ... Administrative Reviews" notices that list honey exporters. The
    # full-text phrase also matches unrelated AD notices that cite a honey case: Keep.HONEY_AD.
    FrQuery("raw_honey", '"raw honey"', '"raw honey"', keep=Keep.HONEY_AD),
    # The 2001 order A-570-863 on honey from China.
    FrQuery("china_honey", "honey from China (AD order)", '"honey from the people\'s republic of china"',
            keep=Keep.HONEY_AD),
    # USITC: sunset reviews and determinations.
    FrQuery("itc_honey", "USITC + honey", "honey", agencies=("international-trade-commission",), keep=Keep.HONEY),
    # FDA: honey labelling guidance, standards, import notices.
    FrQuery("fda_honey", "FDA + honey", "honey", agencies=("food-and-drug-administration",), keep=Keep.HONEY),
    # Presidential tariff documents whose text mentions honey or HTS 0409. Words without quotes
    # are combined with AND, "|" is OR and parentheses group (verified live). "tariff" keeps out
    # proclamations that use "honey" as an endearment (Mother's Day).
    FrQuery("pres_tariff_honey", "presidential tariff documents mentioning honey or HTS 0409",
            "tariff (honey | 0409)", types=("PRESDOCU",), keep=Keep.HONEY_TEXT),
)


def fr_search_params(query: FrQuery, since: date, fields: Sequence[str] = FR_FIELDS,
                     per_page: int = FR_PER_PAGE) -> list[tuple[str, str]]:
    """Query parameters for documents.json. A list of pairs, because array parameters such as
    ``fields[]`` and ``conditions[agencies][]`` repeat. httpx percent-encodes the brackets, which
    the API accepts."""
    params: list[tuple[str, str]] = [
        ("per_page", str(per_page)),
        ("order", "newest"),
        ("conditions[term]", query.term),
        ("conditions[publication_date][gte]", since.isoformat()),
    ]
    params += [("conditions[agencies][]", a) for a in query.agencies]
    params += [("conditions[type][]", t) for t in query.types]
    params += [("fields[]", f) for f in fields]
    return params


def fr_since(last_complete: str | None, ref: date, force: bool = False) -> date:
    """Lower publication-date bound for one saved search: about three years on the first run or
    when forced, otherwise the last complete run minus a week (late indexing, corrections)."""
    last = parse_iso_date(last_complete)
    if last is None or force:
        return ref - timedelta(days=FR_BACKFILL_DAYS)
    return min(last, ref) - timedelta(days=FR_OVERLAP_DAYS)


@dataclass
class FrDocument:
    document_number: str
    title: str
    type_label: str | None
    abstract: str | None
    publication_date: date
    effective_on: date | None
    url: str                             # html_url (FR.gov rendition), else pdf_url (govinfo, official)
    pdf_url: str | None
    agency_slugs: tuple[str, ...]
    agency_names: tuple[str, ...]
    action: str | None
    citation: str | None
    has_effective_on_key: bool           # used by the 'effective_on' field-name probe
    excerpts: str | None = None          # search-hit excerpts as plain text (highlight tags removed)


@dataclass
class FrPage:
    count: int
    total_pages: int | None
    next_page_url: str | None
    documents: list[FrDocument]
    problems: list[str] = field(default_factory=list)


def _https_url(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip().startswith("https://") else None


def _fr_document(r: dict, i: int) -> tuple[FrDocument | None, list[str]]:
    """One search result -> FrDocument, plus soft problems. None when a required field is unusable."""
    problems: list[str] = []
    number = r.get("document_number")
    number = number.strip() if isinstance(number, str) else ""
    if not number or len(number) > 200:
        return None, [f"result {i} has no usable document_number; skipped"]
    title = clean_text(r.get("title"))
    if not title:
        return None, [f"document {number} has no title; skipped"]
    published = parse_iso_date(r.get("publication_date"))
    if published is None:
        return None, [f"document {number}: publication_date {r.get('publication_date')!r} is not a date; skipped"]
    url = _https_url(r.get("html_url")) or _https_url(r.get("pdf_url"))
    if url is None:
        return None, [f"document {number} has neither html_url nor pdf_url; skipped"]
    raw_eff = r.get("effective_on")
    effective = parse_iso_date(raw_eff) if raw_eff else None
    if raw_eff and effective is None:
        problems.append(f"document {number}: effective_on {raw_eff!r} is not a date; left empty")
    type_label = r.get("type") if isinstance(r.get("type"), str) else None
    if type_label is not None and type_label not in _FR_TYPE_TO_STATUS:
        problems.append(f"document {number}: unexpected type {type_label!r}; stored as a notice")
    slugs: list[str] = []
    names: list[str] = []
    agencies = r.get("agencies")
    if isinstance(agencies, list):
        for a in agencies:
            if isinstance(a, dict):
                if isinstance(a.get("slug"), str) and a["slug"]:
                    slugs.append(a["slug"])
                name = a.get("name") or a.get("raw_name")
                if isinstance(name, str) and name:
                    names.append(name)
    elif agencies is not None:
        problems.append(f"document {number}: 'agencies' is not a list; agency filter not checked")
    doc = FrDocument(
        document_number=number, title=title, type_label=type_label, abstract=clean_text(r.get("abstract")),
        publication_date=published, effective_on=effective, url=url, pdf_url=_https_url(r.get("pdf_url")),
        agency_slugs=tuple(slugs), agency_names=tuple(names), action=clean_text(r.get("action")),
        citation=clean_text(r.get("citation")), has_effective_on_key="effective_on" in r,
        excerpts=clean_text(r.get("excerpts")),
    )
    return doc, problems


def parse_fr_search(content: bytes) -> FrPage:
    """Parse one documents.json page.

    Raises ``SchemaDrift`` when the envelope is not the documented one (``count``, ``results``,
    ``next_page_url``) or when no result carries a ``document_number``, and ``SourceQueryError``
    when the API answers with an ``errors`` object. Malformed single results become problems."""
    obj = _load_json(content, "Federal Register search")
    if not isinstance(obj, dict):
        raise SchemaDrift(f"Federal Register search: expected a JSON object, got {type(obj).__name__}")
    if obj.get("errors"):
        raise SourceQueryError(f"Federal Register rejected the query: {json.dumps(obj['errors'])[:300]}")
    count = obj.get("count")
    if not isinstance(count, int) or isinstance(count, bool):
        raise SchemaDrift(f"Federal Register search: no integer 'count' (top-level keys: {sorted(obj)[:12]})")
    results = obj.get("results")
    if results is None and count == 0:
        results = []                     # an empty search may omit 'results'
    if not isinstance(results, list):
        raise SchemaDrift(f"Federal Register search: 'results' is {type(results).__name__}, expected a list "
                          f"(count={count}, keys: {sorted(obj)[:12]})")
    next_url = obj.get("next_page_url")
    if next_url is not None and not isinstance(next_url, str):
        raise SchemaDrift(f"Federal Register search: 'next_page_url' is {type(next_url).__name__}")
    total_pages = obj.get("total_pages") if isinstance(obj.get("total_pages"), int) else None

    documents: list[FrDocument] = []
    problems: list[str] = []
    keys_seen: set[str] = set()
    with_number = 0
    for i, r in enumerate(results):
        if not isinstance(r, dict):
            problems.append(f"result {i} is not an object; skipped")
            continue
        keys_seen.update(r)
        if isinstance(r.get("document_number"), str) and r["document_number"].strip():
            with_number += 1
        doc, doc_problems = _fr_document(r, i)
        problems += doc_problems
        if doc is not None:
            documents.append(doc)
    if results and with_number == 0:
        raise SchemaDrift(f"Federal Register search: none of the {len(results)} results has a 'document_number' "
                          f"(result keys: {sorted(keys_seen)[:15]})")
    return FrPage(count=count, total_pages=total_pages, next_page_url=next_url or None,
                  documents=documents, problems=problems)


def parse_fr_agencies(content: bytes) -> set[str] | None:
    """Slugs from /api/v1/agencies (a JSON array of agency objects). None if the shape is unexpected."""
    try:
        obj = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return None
    items = obj.get("results") if isinstance(obj, dict) else obj
    if not isinstance(items, list):
        return None
    slugs = {a["slug"] for a in items if isinstance(a, dict) and isinstance(a.get("slug"), str) and a["slug"]}
    return slugs or None


def fr_doc_type(doc: FrDocument) -> str:
    """RegulationItem.doc_type for a Federal Register document.

    tariff        presidential documents (EOs and proclamations; our searches only reach tariff ones)
    antidumping   'antidumping' in the title (ITA AD notices, incl. the omnibus review notices)
    rule / proposed_rule / notice   otherwise, from the FR document type"""
    if doc.type_label == "Presidential Document":
        return "tariff"
    if _ANTIDUMPING_RE.search(doc.title):
        return "antidumping"
    return _FR_TYPE_TO_DOC_TYPE.get(doc.type_label or "", "notice")


def fr_status(doc: FrDocument) -> str | None:
    return _FR_TYPE_TO_STATUS.get(doc.type_label or "")


def fr_honey_cases(doc: FrDocument) -> list[str]:
    """Honey AD/CVD case numbers listed in the search excerpts ("Raw Honey, A-357-823")."""
    out: list[str] = []
    for m in _HONEY_CASE_RE.finditer(doc.excerpts or ""):
        if m["case"].upper() not in out:
            out.append(m["case"].upper())
    return out


def fr_is_relevant(query: FrQuery, doc: FrDocument) -> tuple[bool, str]:
    """(keep?, reason). Reason 'agency'/'type' means the result does not match the filter the
    query asked for (the API may have ignored it); 'topic' means it is off-topic noise. Reasons
    for kept documents: 'title_abstract', 'listed_case' (omnibus notice listing a honey case
    number in the excerpts) and 'excerpt' (presidential document whose text names honey/0409)."""
    if query.types and doc.type_label and doc.type_label not in {FR_TYPE_CODES[t] for t in query.types}:
        return False, "type"
    if query.agencies and doc.agency_slugs and not set(query.agencies) & set(doc.agency_slugs):
        return False, "agency"
    if HONEY_RE.search(f"{doc.title}\n{doc.abstract or ''}"):
        return True, "title_abstract"
    if query.keep is Keep.HONEY_AD and fr_honey_cases(doc):
        return True, "listed_case"
    if query.keep is Keep.HONEY_TEXT and doc.excerpts and (HONEY_RE.search(doc.excerpts)
                                                          or _HTS_0409_RE.search(doc.excerpts)):
        return True, "excerpt"
    return False, "topic"


@dataclass
class _FrRun:
    """State shared by the queries of one run."""

    fields: tuple[str, ...] = FR_FIELDS
    rules_seen: int = 0
    rules_with_effective_key: int = 0


@dataclass
class _QueryStats:
    total: int = 0
    kept: int = 0
    off_filter: int = 0


class FederalRegisterCollector(Collector):
    key = "us_federal_register"
    name = "Federal Register USA: antidumping, dazi e avvisi sul miele"
    publisher = "Office of the Federal Register (NARA) / U.S. Government Publishing Office"
    homepage = "https://www.federalregister.gov/"
    kind = SourceKind.API
    reliability = Reliability.OFFICIAL
    category = "regulation"
    country_iso3 = "USA"
    language = "en"
    expected_update = "Ogni giorno lavorativo federale; i documenti sul miele sono occasionali: settimane senza novità sono normali"
    expected_update_en = "Every federal business day; honey items are event-driven, so weeks with no new document are normal"
    # Event-driven: AD reviews are yearly per order, tariff actions irregular. Two months without
    # a new honey document is plausible; longer deserves a look at the run log.
    expected_max_age_days = 60
    terms_note = ("Federal Register content is a US Government work (public domain). The FederalRegister.gov "
                  "rendition is not the official legal edition; the official edition is the govinfo PDF. "
                  "Abstracts are stored verbatim as published.")
    # The daily FR issue is online at about 06:00 ET (12:00 in Italy). A weekday run before the
    # 07:00 briefing picks up the previous business day's issue; the 7-day overlap closes gaps.
    schedule = {"trigger": "cron", "day_of_week": "mon-fri", "hour": 6, "minute": 40}

    def collect(self, ctx: CollectContext) -> None:
        t = today()
        state = _get_state(ctx.session, self.key)
        query_state: dict[str, str] = dict(state.get("queries") or {})
        missing_slugs = self._probe_agencies(ctx, state, t)
        run = _FrRun()
        attempted: list[str] = []
        failed: list[str] = []
        for q in FR_QUERIES:
            unavailable = sorted(set(q.agencies) & missing_slugs)
            if unavailable:
                ctx.warn(f"Federal Register: search '{q.label}' skipped: agency slug(s) {', '.join(unavailable)} "
                         f"not found in the agency list (renamed?)")
                continue
            attempted.append(q.label)
            since = fr_since(query_state.get(q.state_key), t, ctx.force)
            try:
                complete = self._run_query(ctx, q, since, run, completed_before=q.state_key in query_state)
            except SourceQueryError as exc:
                ctx.warn(str(exc))
                failed.append(q.label)
                complete = False
            if complete:
                query_state[q.state_key] = t.isoformat()
                state["queries"] = query_state
                _set_state(ctx.session, self.key, state)
            ctx.checkpoint()        # one batch per saved search
        if run.fields == FR_FIELDS and run.rules_seen and not run.rules_with_effective_key:
            ctx.warn(f"Federal Register returned no 'effective_on' key on any of {run.rules_seen} final rule(s): "
                     f"the field name (unverified) may be wrong, so effective dates are not being stored")
        if attempted and len(failed) == len(attempted):
            raise CollectorError(f"Every Federal Register search failed ({', '.join(failed)})")

    # ----------------------------------------------------------------- probes
    def _probe_agencies(self, ctx: CollectContext, state: dict, t: date) -> set[str]:
        """Check that the agency slugs used as filters still exist. Returns the missing ones.

        A guard, not data: if the agency list itself cannot be read, the run goes on with a
        warning (the in-band agency check in ``fr_is_relevant`` still applies)."""
        needed = sorted({a for q in FR_QUERIES for a in q.agencies})
        if not needed:
            return set()
        checked = parse_iso_date(state.get("agencies_checked"))
        known_missing = set(state.get("agencies_missing") or [])
        if not ctx.force and checked and not known_missing and 0 <= (t - checked).days < FR_AGENCY_PROBE_DAYS:
            return set()
        try:
            doc = ctx.fetch(FR_AGENCIES_URL, headers=JSON_HEADERS, accept_status=(200, 404), store=False)
        except Offline:
            raise
        except CollectorError as exc:
            ctx.warn(f"Federal Register agency check failed ({exc}); agency filters not verified this run")
            return set()
        slugs = parse_fr_agencies(doc.content) if doc.status_code == 200 else None
        if slugs is None:
            ctx.warn(f"Federal Register agency list unreadable (HTTP {doc.status_code}, starts with "
                     f"{_snippet(doc.content, 80)!r}); agency filters not verified this run")
            return set()
        missing = {a for a in needed if a not in slugs}
        state["agencies_checked"] = t.isoformat()
        state["agencies_missing"] = sorted(missing)
        _set_state(ctx.session, self.key, state)
        return missing

    # ---------------------------------------------------------------- queries
    def _run_query(self, ctx: CollectContext, q: FrQuery, since: date, run: _FrRun, *,
                   completed_before: bool = False) -> bool:
        """Run one saved search, following next_page_url. Returns True when it was read to the end.

        A page whose bytes were already archived is not re-ingested, but only for a search that
        has completed before: the archive is de-duplicated by content hash across all searches,
        and searches keep different subsets of the same results."""
        skip_unchanged = completed_before and not ctx.force
        url: str | None = FR_SEARCH_URL
        params: list[tuple[str, str]] | None = fr_search_params(q, since, run.fields)
        stats = _QueryStats()
        page_no = 0
        while url:
            page_no += 1
            if page_no > FR_MAX_PAGES:
                ctx.warn(f"Federal Register ({q.label}): stopped after {FR_MAX_PAGES} pages; older results not read")
                return False
            doc = ctx.fetch(url, params=params, headers=JSON_HEADERS, accept_status=(200, 400, 422),
                            title=f"Federal Register search: {q.label} since {since} (page {page_no})")
            if doc.status_code != 200:
                if page_no == 1 and run.fields != FR_CORE_FIELDS:
                    # The optional field names are unverified: retry this (and every later) search
                    # with the default fields only.
                    ctx.warn(f"Federal Register rejected the search '{q.label}' with the optional fields "
                             f"{', '.join(FR_OPTIONAL_FIELDS)} (HTTP {doc.status_code}: {_snippet(doc.content)}); "
                             f"retrying with the default fields (no effective dates)")
                    run.fields = FR_CORE_FIELDS
                    params = fr_search_params(q, since, run.fields)
                    page_no = 0
                    continue
                raise SourceQueryError(f"Federal Register search '{q.label}' failed: HTTP {doc.status_code}: "
                                       f"{_snippet(doc.content)}")
            page = parse_fr_search(doc.content)          # SchemaDrift propagates: fail loudly
            if not (doc.unchanged and skip_unchanged):   # identical bytes: already ingested last time
                for p in page.problems:
                    ctx.warn(f"Federal Register ({q.label}): {p}")
                for d in page.documents:
                    self._store(ctx, q, d, run, stats)
            url, params = page.next_page_url, None       # next_page_url carries every parameter
            if url is not None:
                parts = urlsplit(url)
                if parts.scheme != "https" or parts.netloc != FR_HOST or not parts.path.startswith("/api/v1/documents"):
                    ctx.warn(f"Federal Register ({q.label}): unexpected next_page_url {url[:120]!r}; paging stopped")
                    return False
        if stats.total and stats.off_filter == stats.total:
            ctx.warn(f"Federal Register ({q.label}): none of the {stats.total} results matched the requested "
                     f"agency/type filter; the API may have ignored it, so nothing was stored from this search")
        return True

    def _store(self, ctx: CollectContext, q: FrQuery, d: FrDocument, run: _FrRun, stats: _QueryStats) -> None:
        stats.total += 1
        if d.type_label == "Rule":
            run.rules_seen += 1
            run.rules_with_effective_key += int(d.has_effective_on_key)
        keep, reason = fr_is_relevant(q, d)
        if not keep:
            if reason in ("agency", "type"):
                stats.off_filter += 1
            return
        stats.kept += 1
        # Omnibus notices: the honey case numbers seen in the search excerpt (the excerpt is a
        # window of the text, so the notice may list more; countries are therefore not derived
        # from it and stay those named in the title/abstract).
        cases = fr_honey_cases(d) if reason == "listed_case" else []
        ctx.add_regulation(
            reference=d.document_number, jurisdiction="US", doc_type=fr_doc_type(d), title=d.title, url=d.url,
            published_at=d.publication_date, effective_date=d.effective_on,
            countries=detect_countries(d.title, d.abstract, exclude=_FR_EXCLUDE_COUNTRIES) or None,
            status=fr_status(d), summary_en=d.abstract, summary_is_ai=False,
            extra={"relevance": reason, "search": q.qid,
                   "honey_cases_in_excerpt": cases or None,
                   "honey_case_origins_in_excerpt": [_CASE_COUNTRY.get(c[2:5]) for c in cases] or None},
        )


# ===========================================================================
# 2) EU legislation: Publications Office CELLAR SPARQL endpoint
# ===========================================================================

CELLAR_SPARQL_URL = "https://publications.europa.eu/webapi/rdf/sparql"
SPARQL_JSON = "application/sparql-results+json"
CDM_NS = "http://publications.europa.eu/ontology/cdm#"
LANG_ENG = "http://publications.europa.eu/resource/authority/language/ENG"
EURLEX_URL = "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}"

EU_BACKFILL_DAYS = 5 * 365        # title search: about five years on the first run (or force)
EU_OVERLAP_DAYS = 180             # later runs: last complete run minus ~6 months (CELLAR indexing lag)
SPARQL_LIMIT = 1000

# Acts whose amendments and implementing acts we always want (CELEX -> short description).
WATCHED_ACTS: dict[str, str] = {
    "32001L0110": "Council Directive 2001/110/EC relating to honey (Honey Directive)",
    "32024L1438": "Directive (EU) 2024/1438 (origin labelling of honey blends)",
    "32021R0405": "Implementing Regulation (EU) 2021/405 (third countries authorised to export honey)",
}
# CDM properties linking an act to an earlier one (names from memory; the canary validates them).
RELATIONS: tuple[str, ...] = (
    "resource_legal_amends_resource_legal",
    "resource_legal_based_on_resource_legal",
    "resource_legal_corrects_resource_legal",
    "resource_legal_repeals_resource_legal",
)

# Self-check: Directive (EU) 2024/1438 of 14 May 2024 amends the Honey Directive, and its English
# title contains "relating to honey". Both queries must find it whenever their scope covers it.
CANARY_CELEX = "32024L1438"
CANARY_TARGET = "32001L0110"
CANARY_DATE = date(2024, 5, 14)

TITLE_VARS = ("celex", "date", "title")
RELATED_VARS = ("celex", "date", "target")

_SPARQL_PREFIXES = f"PREFIX cdm: <{CDM_NS}>\nPREFIX xsd: <http://www.w3.org/2001/XMLSchema#>\n"
_SPARQL_OPTIONALS = (
    "  OPTIONAL { ?work cdm:resource_legal_in-force ?inforce . }\n"
    "  OPTIONAL { ?work cdm:resource_legal_date_entry-into-force ?eif . }\n"
)


def build_title_query(since: date, limit: int = SPARQL_LIMIT) -> str:
    """Acts dated on/after `since` whose English expression title contains "honey".

    Only CELEX sector 3 (legislation), sector 2 (international agreements) and COM proposals
    (5yyyyPC) are asked for: parliamentary questions, case law and national measures also
    mention honey but are not regulation. The date filter comes first because a CONTAINS scan
    over every title would time out."""
    return (
        _SPARQL_PREFIXES
        + "SELECT DISTINCT ?celex ?date ?title ?inforce ?eif WHERE {\n"
        "  ?work cdm:resource_legal_id_celex ?celex ;\n"
        "        cdm:work_date_document ?date .\n"
        f'  FILTER(?date >= "{since.isoformat()}"^^xsd:date)\n'
        '  FILTER(REGEX(STR(?celex), "^(2|3|5[0-9]{4}PC)"))\n'
        "  ?expr cdm:expression_belongs_to_work ?work ;\n"
        f"        cdm:expression_uses_language <{LANG_ENG}> ;\n"
        "        cdm:expression_title ?title .\n"
        '  FILTER(CONTAINS(LCASE(STR(?title)), "honey"))\n'
        + _SPARQL_OPTIONALS
        + "}\nORDER BY DESC(?date)\n"
        f"LIMIT {limit}"
    )


def eu_title_since(last_complete: str | None, ref: date, force: bool = False) -> date:
    """Lower document-date bound for the title search: about five years on the first run (or
    when forced), otherwise the last complete run minus ~6 months, because CELLAR can index an
    act weeks after its document date."""
    last = parse_iso_date(last_complete)
    if last is None or force:
        return ref - timedelta(days=EU_BACKFILL_DAYS)
    return min(last, ref) - timedelta(days=EU_OVERLAP_DAYS)


def build_related_query(targets: Iterable[str], limit: int = SPARQL_LIMIT) -> str:
    """Acts that amend, are based on, correct or repeal any of `targets` (CELEX numbers).

    CELEX literals may be typed xsd:string or plain, so both forms are listed in VALUES (an exact
    lookup that uses the index, unlike FILTER(STR(...)) over every act). Not date-limited: the
    result is a few dozen acts. The English title is OPTIONAL so an act whose title is not indexed
    yet is still seen (it is stored once its title appears)."""
    tc_values = " ".join(f'"{c}" "{c}"^^xsd:string' for c in targets)
    rel_values = " ".join(f"cdm:{r}" for r in RELATIONS)
    return (
        _SPARQL_PREFIXES
        + "SELECT DISTINCT ?celex ?date ?title ?target ?rel ?inforce ?eif WHERE {\n"
        f"  VALUES ?tc {{ {tc_values} }}\n"
        f"  VALUES ?rel {{ {rel_values} }}\n"
        "  ?t cdm:resource_legal_id_celex ?tc .\n"
        "  ?work ?rel ?t ;\n"
        "        cdm:resource_legal_id_celex ?celex ;\n"
        "        cdm:work_date_document ?date .\n"
        "  BIND(STR(?tc) AS ?target)\n"
        "  OPTIONAL { ?expr cdm:expression_belongs_to_work ?work ;\n"
        f"                  cdm:expression_uses_language <{LANG_ENG}> ;\n"
        "                  cdm:expression_title ?title . }\n"
        + _SPARQL_OPTIONALS
        + "}\nORDER BY DESC(?date)\n"
        f"LIMIT {limit}"
    )


@dataclass
class SparqlResult:
    vars: list[str]
    rows: list[dict[str, str]]           # var -> lexical value (unbound variables are absent)
    problems: list[str] = field(default_factory=list)


_TERM_TYPES = frozenset({"literal", "typed-literal", "uri", "bnode"})   # 'typed-literal': older Virtuoso


def parse_sparql_json(content: bytes, required_vars: Sequence[str]) -> SparqlResult:
    """Validate and flatten W3C SPARQL 1.1 JSON results (``head.vars`` + ``results.bindings``).

    Raises ``SchemaDrift`` if the document is not a SELECT result in that format, if a required
    variable is missing from ``head.vars``, or if no binding is usable."""
    obj = _load_json(content, "CELLAR SPARQL")
    head = obj.get("head") if isinstance(obj, dict) else None
    variables = head.get("vars") if isinstance(head, dict) else None
    results = obj.get("results") if isinstance(obj, dict) else None
    bindings = results.get("bindings") if isinstance(results, dict) else None
    if not isinstance(variables, list) or not isinstance(bindings, list):
        keys = sorted(obj)[:10] if isinstance(obj, dict) else type(obj).__name__
        raise SchemaDrift(f"CELLAR SPARQL: not a SPARQL JSON SELECT result (expected head.vars and "
                          f"results.bindings; got {keys})")
    missing = [v for v in required_vars if v not in variables]
    if missing:
        raise SchemaDrift(f"CELLAR SPARQL: variables {missing} missing from head.vars {variables}")
    rows: list[dict[str, str]] = []
    problems: list[str] = []
    for i, b in enumerate(bindings):
        if not isinstance(b, dict):
            problems.append(f"binding {i} is not an object; skipped")
            continue
        row: dict[str, str] = {}
        bad = None
        for var, term in b.items():
            if not isinstance(term, dict) or term.get("type") not in _TERM_TYPES or not isinstance(term.get("value"), str):
                bad = var
                break
            row[var] = term["value"]
        if bad is not None:
            problems.append(f"binding {i}: malformed RDF term for ?{bad}; skipped")
            continue
        rows.append(row)
    if bindings and not rows:
        raise SchemaDrift(f"CELLAR SPARQL: none of the {len(bindings)} bindings is in the documented "
                          f"{{var: {{type, value}}}} form")
    return SparqlResult(vars=[str(v) for v in variables], rows=rows, problems=problems)


def sparql_incomplete(headers: dict[str, str]) -> bool:
    """CELLAR runs on Virtuoso, which answers a query that hit its time limit with HTTP 200 and
    *partial* results, flagged by ``X-SQL-State: S1TAT`` (Virtuoso "anytime query"; from memory)."""
    return any(k.lower() == "x-sql-state" and str(v).strip().upper() == "S1TAT" for k, v in headers.items())


_CELEX_RE = re.compile(r"^(?P<sector>[0-9CE])(?P<year>\d{4})(?P<type>[A-Z]{1,2})(?P<number>\d{4,6})"
                       r"(?P<suffix>[A-Z0-9()\-]*)$")


@dataclass(frozen=True)
class CelexInfo:
    celex: str
    sector: str          # 3 legislation, 2 international agreements, 5 preparatory acts, ...
    year: int
    type: str            # R regulation, L directive, D decision, PC COM proposal, A agreement, ...
    number: str
    suffix: str          # e.g. "R(01)" for a corrigendum, "(01)" for agreements

    @property
    def is_corrigendum(self) -> bool:
        return bool(re.search(r"R\(\d+\)", self.suffix))


def parse_celex(value: str | None) -> CelexInfo | None:
    v = (value or "").strip().upper()
    m = _CELEX_RE.match(v)
    if not m:
        return None
    return CelexInfo(celex=v, sector=m["sector"], year=int(m["year"]), type=m["type"], number=m["number"],
                     suffix=m["suffix"])


_SECTOR3_TYPES = {"R": "regulation", "L": "directive", "D": "decision", "H": "recommendation"}


def eu_doc_type(info: CelexInfo) -> str | None:
    """RegulationItem.doc_type from the CELEX sector and type letter. None = out of scope
    (consolidated texts, case law, questions, national measures ...)."""
    if info.sector == "3":
        return _SECTOR3_TYPES.get(info.type, "act")
    if info.sector == "2":
        return "decision" if info.type == "D" else "agreement"   # e.g. EU-Ukraine Association Committee decisions
    if info.sector == "5" and info.type == "PC":
        return "proposal"
    return None


def eurlex_url(celex: str) -> str:
    return EURLEX_URL.format(celex=celex)


@dataclass
class EuAct:
    info: CelexInfo
    date: date | None = None
    titles: set[str] = field(default_factory=set)
    targets: set[str] = field(default_factory=set)      # watched CELEX numbers this act relates to
    in_force_raw: set[str] = field(default_factory=set)
    entry_into_force: date | None = None

    @property
    def celex(self) -> str:
        return self.info.celex

    @property
    def title(self) -> str | None:
        # Several rows can carry title variants (with/without subtitle): keep the most complete.
        return max(self.titles, key=lambda s: (len(s), s)) if self.titles else None

    @property
    def in_force(self) -> bool | None:
        vals = {v.strip().lower() for v in self.in_force_raw}
        if vals & {"true", "1"}:
            return True
        if vals & {"false", "0"}:
            return False
        return None


def group_eu_acts(rows: Iterable[dict[str, str]]) -> tuple[dict[str, EuAct], list[str]]:
    """Merge SPARQL rows (one per title/relation/date combination) into one EuAct per CELEX."""
    acts: dict[str, EuAct] = {}
    problems: list[str] = []
    for row in rows:
        raw_celex = row.get("celex")
        info = parse_celex(raw_celex)
        if info is None:
            problems.append(f"unrecognised CELEX number {raw_celex!r}; row skipped")
            continue
        d = parse_iso_date(row.get("date"))
        if d is None:
            problems.append(f"{info.celex}: document date {row.get('date')!r} is not a date; row skipped")
            continue
        act = acts.setdefault(info.celex, EuAct(info=info))
        act.date = d if act.date is None else min(act.date, d)
        title = clean_text(row.get("title"))
        if title:
            act.titles.add(title)
        target = (row.get("target") or "").strip().upper()
        if target:
            act.targets.add(target)
        if row.get("inforce"):
            act.in_force_raw.add(row["inforce"])
        eif = parse_iso_date(row.get("eif"))
        if eif is not None:
            act.entry_into_force = eif if act.entry_into_force is None else min(act.entry_into_force, eif)
    return acts, problems


def eu_status(act: EuAct) -> str | None:
    """Status only where the source says it: proposals and corrigenda by CELEX, otherwise the
    CELLAR in-force flag when present."""
    if act.info.sector == "5":
        return "proposed"
    if act.info.is_corrigendum:
        return "corrigendum"
    if act.in_force is True:
        return "in_force"
    if act.in_force is False:
        return "no_longer_in_force"
    return None


def check_related_canary(acts: dict[str, EuAct]) -> None:
    act = acts.get(CANARY_CELEX)
    if act is None or CANARY_TARGET not in act.targets:
        raise SchemaDrift(
            f"CELLAR self-check failed: the related-acts query did not return {CANARY_CELEX} as related to "
            f"{CANARY_TARGET} (it amends the Honey Directive). The CDM property names used here (unverified) "
            f"or the endpoint have changed; nothing stored from this query")
    if act.date is None or not act.title or not HONEY_RE.search(act.title):
        raise SchemaDrift(
            f"CELLAR self-check failed: {CANARY_CELEX} came back without its document date or English title "
            f"(cdm:work_date_document / cdm:expression_title may have changed); nothing stored from this query")


def check_title_canary(acts: dict[str, EuAct], since: date) -> None:
    if since > CANARY_DATE:
        return                          # incremental window: the canary is out of scope
    if CANARY_CELEX not in acts:
        raise SchemaDrift(
            f"CELLAR self-check failed: the honey title query since {since} did not return {CANARY_CELEX} "
            f"(whose English title contains 'honey'). The title properties or the endpoint have changed; "
            f"nothing stored from this query")


class EurLexHoneyCollector(Collector):
    key = "eurlex_honey"
    name = "EUR-Lex: legislazione UE sul miele"
    publisher = "Publications Office of the European Union (CELLAR / EUR-Lex)"
    homepage = "https://eur-lex.europa.eu/"
    kind = SourceKind.API
    reliability = Reliability.OFFICIAL
    category = "regulation"
    language = "en"
    expected_update = "Controllo settimanale; gli atti UE sul miele sono rari e occasionali: mesi senza nuovi atti sono normali"
    expected_update_en = "Weekly check; EU honey acts are rare and event-driven, so months with no new act are normal"
    # Honey legislation changes a few times a year at most (2021/405 list amendments, 2024/1438
    # implementing acts). Six months without a new act is normal.
    expected_max_age_days = 180
    terms_note = ("© European Union, https://eur-lex.europa.eu. Reuse with acknowledgement (Commission Decision "
                  "2011/833/EU). Metadata from the CELLAR SPARQL endpoint; only the Official Journal is authentic. "
                  "The date shown is the act's document date (adoption/signature); OJ publication follows within days.")
    schedule = {"trigger": "cron", "day_of_week": "mon", "hour": 6, "minute": 20}

    def collect(self, ctx: CollectContext) -> None:
        t = today()
        state = _get_state(ctx.session, self.key)
        errors: list[str] = []

        # (a) Acts related to the watched acts. Runs first: its canary is the start-up probe of
        #     the CDM vocabulary.
        try:
            doc, res = self._select(ctx, build_related_query(WATCHED_ACTS), RELATED_VARS, "related acts")
        except SourceQueryError as exc:
            errors.append(str(exc))
        else:
            acts, problems = group_eu_acts(res.rows)
            incomplete = sparql_incomplete(doc.headers)
            if incomplete:
                ctx.warn("CELLAR (related acts): the endpoint returned partial results (query time limit); "
                         "self-check skipped, the rest will be read next run")
            else:
                check_related_canary(acts)
            if not (doc.unchanged and not ctx.force):
                for p in res.problems + problems:
                    ctx.warn(f"CELLAR (related acts): {p}")
                for act in acts.values():
                    self._store(ctx, act, require_honey=False)
            ctx.checkpoint()

        # (b) Acts with "honey" in the English title, date-limited.
        since = eu_title_since(state.get("title_complete"), t, ctx.force)
        try:
            doc, res = self._select(ctx, build_title_query(since), TITLE_VARS, f"honey titles since {since}")
        except SourceQueryError as exc:
            errors.append(str(exc))
        else:
            acts, problems = group_eu_acts(res.rows)
            incomplete = sparql_incomplete(doc.headers) or len(res.rows) >= SPARQL_LIMIT
            if incomplete:
                ctx.warn(f"CELLAR (honey titles): results incomplete (time limit or LIMIT {SPARQL_LIMIT} reached); "
                         f"the same window will be read again next run")
            else:
                check_title_canary(acts, since)
            if not (doc.unchanged and not ctx.force):
                for p in res.problems + problems:
                    ctx.warn(f"CELLAR (honey titles): {p}")
                for act in acts.values():
                    self._store(ctx, act, require_honey=True)
            if not incomplete:
                state["title_complete"] = t.isoformat()
                _set_state(ctx.session, self.key, state)
            ctx.checkpoint()

        if errors:
            raise CollectorError("; ".join(errors))

    def _select(self, ctx: CollectContext, query: str, required: Sequence[str], label: str
                ) -> tuple[FetchResult, SparqlResult]:
        doc = ctx.fetch(
            CELLAR_SPARQL_URL, params={"query": query, "format": SPARQL_JSON},
            headers={"Accept": f"{SPARQL_JSON}, application/json;q=0.9"},
            accept_status=(200, 400, 500), title=f"CELLAR SPARQL: {label}",
        )
        if doc.status_code != 200:
            # Virtuoso reports query compilation errors and time-outs as plain text.
            raise SourceQueryError(f"CELLAR SPARQL ({label}) answered HTTP {doc.status_code}: {_snippet(doc.content)}")
        return doc, parse_sparql_json(doc.content, required)     # SchemaDrift propagates

    def _store(self, ctx: CollectContext, act: EuAct, *, require_honey: bool) -> None:
        doc_type = eu_doc_type(act.info)
        if doc_type is None:
            return                      # out of scope (consolidated text, case law, question ...)
        title = act.title
        if not title:
            ctx.warn(f"CELLAR: {act.celex} has no English title yet; not stored (retried next run)")
            return
        if require_honey and not HONEY_RE.search(title):
            return                      # e.g. only "honeybees" in the title
        ctx.add_regulation(
            reference=act.celex, jurisdiction="EU", doc_type=doc_type, title=title, url=eurlex_url(act.celex),
            published_at=act.date, effective_date=act.entry_into_force,
            countries=detect_countries(title) or None, status=eu_status(act),
            summary_en=None,            # CELLAR carries no official abstract: never invent one
            summary_is_ai=False,
        )


__all__ = [
    "FR_CORE_FIELDS",
    "FR_FIELDS",
    "FR_QUERIES",
    "HONEY_RE",
    "WATCHED_ACTS",
    "EurLexHoneyCollector",
    "FederalRegisterCollector",
    "FrQuery",
    "Keep",
    "SchemaDrift",
    "SourceQueryError",
    "build_related_query",
    "build_title_query",
    "check_related_canary",
    "check_title_canary",
    "clean_text",
    "detect_countries",
    "eu_doc_type",
    "eu_status",
    "eu_title_since",
    "eurlex_url",
    "fr_doc_type",
    "fr_honey_cases",
    "fr_is_relevant",
    "fr_search_params",
    "fr_since",
    "fr_status",
    "group_eu_acts",
    "parse_celex",
    "parse_fr_agencies",
    "parse_fr_search",
    "parse_iso_date",
    "parse_sparql_json",
    "sparql_incomplete",
]
