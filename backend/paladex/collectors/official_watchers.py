"""Origin-country official notice watchers: Brazil (MAPA), Argentina (SENASA, Boletín Oficial) and
India (DGFT).

Three keyless collectors, one ``Source`` each (reliability *official*, category *regulation*).
They read public government web pages, keep the items that concern honey (keyword filters in the
local language) and store them as ``RegulationItem`` rows through ``ctx.add_regulation``. That
writer is append-only: an item already stored (same source and ``reference``) is never rewritten,
so every run is idempotent.

* ``br_mapa_honey``: Brazil, Ministério da Agricultura e Pecuária (MAPA).
    (a) The MAPA news listing on gov.br (Plone), filtered for honey: "mel", "méis", "apícola",
        "apicultura", "apicultor" (but not the idiom "lua de mel"). Some news about the EU list of
        authorised third countries does not name honey in its listing text. These are items that
        say "União Europeia" together with "lista", "reinclusão", "habilitação", "2021/405",
        "antimicrobianos" and similar. The watcher opens them and keeps them when the article
        body names honey.
    (b) The Diário Oficial da União (DOU) search, Section 1: normative acts of MAPA (Portarias,
        Instruções Normativas, ...) whose title or published excerpt names honey.
* ``ar_senasa_honey``: Argentina.
    (a) The SENASA news listing on argentina.gob.ar, filtered for honey: "miel" (not "luna de
        miel"), "apícola", "apicultura", "apicultor", NCM 0409.00.00.
    (b) The SENASA Plan CREHA page, checked weekly. Each new "Lista EAR" PDF (residue-limit
        exceedances) is downloaded and kept when its text names honey. The honey lines are kept
        verbatim in ``extra["honey_rows"]``.
    (c) The Boletín Oficial, first section: the latest edition, plus catch-up of the business days
        missed since the last run. Notices of agriculture bodies (SAGyP, SENASA) and export-duty
        acts are opened and kept when their text names honey.
* ``in_dgft_honey``: India, Directorate General of Foreign Trade, notifications list, filtered
    for honey ("honey", but not "honey bee(s)"; ITC-HS 0409). For every new honey row the
    notification PDF is read for three values: the minimum export price
    (``extra["mep_usd_per_t"]``), the end of its validity (``extra["valid_until"]``) and the
    ``effective_date``. Each is stored only when the official text states it unambiguously. The
    MEP expiry date is what matters to a buyer: it is the bottom of Indian FOB offers. The real
    MEP notifications (checked Nov 2026) are scanned pages with no text layer: they are read by
    OCR (``services.ocr``, Tesseract, optional) at 300 and 400 dpi, and a value is stored only
    when both readings agree (``merge_ocr_terms``); OCR text never becomes ``summary_en``.

Field conventions
-----------------
* ``jurisdiction``: ISO 3166 alpha-2, upper case ("BR", "AR", "IN"), as "EU"/"US" elsewhere.
  ``countries``: ``[origin ISO3]``.
* ``doc_type`` follows simple, documented rules over the title and official text (see
  ``doc_type_for``). ``price_floor`` is used for minimum-export-price notices. ``export_rule`` is
  used for EU listing, certification, quota and drum rules. ``residue_alert`` is used for residue
  lists and controls. ``regulation`` is used for other normative acts in an official gazette.
  ``notice`` is used for everything else. The topics that drove the choice are kept in
  ``extra["topics"]``.
* Summaries are never written by AI and never translated. ``summary_en`` holds only official
  English text (DGFT: the operative sentences of the notification, verbatim). Portuguese and
  Spanish texts stay in ``extra["summary_original"]`` / ``extra["excerpt_original"]`` with
  ``extra["language"]``. ``summary_it`` is never set here.
* ``reference``: news items use the canonical URL path ("mapa:/agricultura/...",
  "senasa:/noticias/..."). DOU acts use "dou:<urlTitle>", Boletín Oficial notices use "BO-AR
  primera <id>", SENASA EAR lists use "SENASA Lista EAR <year> N°<nn>" and DGFT rows use "DGFT
  Notification No. <nn/yyyy-yy>". The same item found twice (two listing pages, two DOU queries)
  is stored once.

Verification status (read this before changing anything)
--------------------------------------------------------
Live check, 4 November 2026 (real captures in ``tests/fixtures/official_watchers/real/``): the
DGFT list URL and table ("Sl.No., Number, Year, Description, Date, CRT DT, Attachment"; bare
numbers such as "36" take the Year column), the DGFT notification PDFs (scans), the SENASA news
listing and Plan CREHA page, and the Lista EAR PDFs (list date printed in the page header) were
confirmed. ``www.boletinoficial.gob.ar`` reset every connection from the test network; an
unreachable feed is a warning (a "partial" run) as long as another feed of the collector worked.

When this module was first written, the sandbox could reach none of these hosts. URLs and layouts
came from ``docs/research/official_south_america.json`` and ``official_asia_turkey.json`` (both
"from_search_snippets") and from the public scrapers of these sites. **Unverified:**

* the SENASA news listing URL ``/senasa/noticias``, the Boletín Oficial dated section URL
  ``/seccion/primera/<yyyymmdd>`` (used only for catch-up), and the DGFT list URL
  ``/CP/?opt=notification`` (research says "REMEMBERED");
* the DOU search parameters (``q``, ``s``, ``exactDate``, ``sortType``, ``delta``) and the JSON
  in the ``<script id="_br_com_seatecnologia_in_buscadou_BuscaDouPortlet_params">`` element. These
  are as used by the open-source DOU client "Ro-DOU" (github.com/gestaogovbr/Ro-dou);
* the HTML markup of every listing (Plone on gov.br, the Poncho theme on argentina.gob.ar,
  ``linea-aviso`` blocks on the Boletín Oficial, the DGFT table columns).

The parsers therefore look for structure, not exact CSS: an item is a link to an article URL of
the expected shape, together with the date and summary inside its own block. The design is
**fail loud, never guess**:

* **Start-up probes.** Each listing must yield rows. Examples: at least one news link on the
  first page; at least one ``detalleAviso`` link in the latest Boletín Oficial edition; at least
  one numbered, dated row in the DGFT table; the DOU results script with a ``jsonArray``; at least
  one PDF link on the CREHA page. When a listing has no rows, or rows but no dates at all, the
  feed raises ``SchemaDrift`` and stores nothing from that page. The run then fails with a message
  that names the feed and the URL.
* **Independent feeds.** The feeds of one collector are independent. Each feed is committed
  (``ctx.checkpoint``) before the next one runs. A drifted feed still fails the run, but only
  after the others have been stored.
* **Raw pages are kept.** Every page and PDF read is archived by ``ctx.fetch``, so a fixed parser
  can be checked against the real bytes under ``data/raw/<source>/``.
* **Unparseable values stay empty.** A value the text does not state unambiguously (an MEP
  amount, a validity date) is left empty. The candidates found go in ``extra``, with a warning.
* **Dates are not lost.** Storing is final (append-only), so a news item whose listing gives no
  date is stored only once its article page has been read for the date; while that page cannot be
  read (or the per-run budget is spent) the item waits, and the feed keeps reading its back-fill
  pages until nothing is left over.
* **A crash is contained.** An unexpected error in one feed rolls back that feed's uncommitted
  rows and fails the run, but the other feeds still run and are stored.
* **No events are hard-coded.** Nothing about known events (EU de-listing of Brazil, the Indian
  MEP and its expiry, the Mercosur-EU quota) is written in this module. They are collected from
  the official pages at run time.

Politeness: at least ``POLITE_INTERVAL_S`` seconds between two requests to the same host, on top
of ``ctx.fetch``'s retries with back-off on 429/5xx. Each run follows only a few links
(``MAX_ARTICLE_FETCHES``, ``BO_MAX_DETAILS``, ``EAR_MAX_PDFS``, ``DGFT_MAX_PDFS``). Work left over
is kept in the collector state and done on the next run. Listings are parsed on every run even
when their bytes are unchanged: parsing is cheap, ``add_regulation`` de-duplicates, and follow-up
work that was postponed is resumed.
"""
from __future__ import annotations

import hashlib
import html as html_lib
import io
import json
import logging
import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag
from sqlalchemy import select

from ..enums import Reliability, SourceKind
from ..models import AppSetting, RegulationItem
from ..services import ocr
from .base import CollectContext, Collector, CollectorError, FetchResult, Offline

log = logging.getLogger(__name__)


def today() -> date:
    """Reference date for windows and catch-up (indirection so tests can pin it)."""
    return date.today()


class SchemaDrift(CollectorError):
    """The page answered, but not with the structure the watcher relies on. Nothing from it is stored."""


# Seconds between two requests to the same government host (ctx.fetch enforces >= 1.5 s).
POLITE_INTERVAL_S = 3.0
HTML_HEADERS = {"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"}
PDF_HEADERS = {"Accept": "application/pdf,*/*;q=0.5"}

MAX_ARTICLE_FETCHES = 8            # article pages opened per news feed and run
BODY_CHECKED_MAX = 500             # remembered "opened, no honey in the body" article URLs
PDF_MAX_PAGES = 30                 # pages of a PDF read for text
MAX_PDF_ATTEMPTS = 3               # runs that retry a PDF that cannot be downloaded
EXCERPT_MAX_CHARS = 1200


# ===========================================================================
# Text helpers
# ===========================================================================


def clean(value: Any) -> str:
    """Text as published: NFC (canonical composition only, so "Nº" or "µg" are not rewritten),
    non-breaking spaces replaced, whitespace collapsed. "" for non-strings."""
    if not isinstance(value, str):
        return ""
    value = unicodedata.normalize("NFC", value).replace("\xa0", " ").replace("\u200b", "")
    return re.sub(r"\s+", " ", value).strip()


def fold(value: Any) -> str:
    """Lower-case ASCII for keyword matching: accents dropped ("apícola" -> "apicola")."""
    s = unicodedata.normalize("NFKD", clean(value)).encode("ascii", "ignore").decode("ascii")
    return s.lower()


def strip_tags(value: Any) -> str:
    """Plain text from an HTML fragment (DOU excerpts carry <span class=highlight> tags)."""
    if not isinstance(value, str):
        return ""
    return clean(html_lib.unescape(re.sub(r"<[^>]+>", " ", value)))


@dataclass(frozen=True)
class KeywordSet:
    """Named regular expressions applied to folded text (see ``fold``)."""

    name: str
    patterns: tuple[tuple[str, re.Pattern[str]], ...]

    def matches(self, *texts: str | None) -> list[str]:
        text = fold(" ".join(t for t in texts if t))
        return [label for label, rx in self.patterns if rx.search(text)]


# Portuguese. "mel" as a word (never "melhoria", "Melo"), not the idiom "lua de mel" (honeymoon).
HONEY_PT = KeywordSet("honey_pt", (
    ("mel", re.compile(r"(?<!lua de )\b(?:mel|meis)\b")),
    ("apícola", re.compile(r"\bapicolas?\b")),
    ("apicultura", re.compile(r"\bapicultur\w*")),
    ("apicultor", re.compile(r"\bapicultor\w*")),
    ("NCM 0409", re.compile(r"\b0409\.?00\.?00\b|\bncm\s*0409\b")),
))

# Spanish. "miel" as a word, not "luna de miel".
HONEY_ES = KeywordSet("honey_es", (
    ("miel", re.compile(r"(?<!luna de )\bmiel(?:es)?\b")),
    ("apícola", re.compile(r"\bapicolas?\b")),
    ("apicultura", re.compile(r"\bapicultur\w*")),
    ("apicultor", re.compile(r"\bapicultor\w*")),
    ("NCM 0409", re.compile(r"\b0409\.?00\.?00\b|\b(?:ncm|posicion arancelaria|partida)\s*(?:n\.?\s*)?0409\b")),
))

# English. "honey", but not the insect ("honey bee", "honey-bees"; "honeybee" never matches).
HONEY_EN = KeywordSet("honey_en", (
    ("honey", re.compile(r"\bhoney\b(?![\s-]*bees?\b)")),
    ("ITC-HS 0409", re.compile(r"\b0409\s?00\s?00\b|\b(?:itc\s*\(?hs\)?|hs)\s*(?:code\s*)?0409\b")),
))

# Product words only (no tariff codes): used on the lines of a residue list.
_HONEY_PRODUCT_ES_RE = re.compile(r"(?<!luna de )\bmiel(?:es)?\b|\bapicolas?\b|\bpropoleos?\b")


def find_dates(text: str | None, lang: str) -> list[tuple[int, date]]:
    """Every date written in `text`, with its position: dd/mm/yyyy, dd.mm.yyyy and dd-mm-yyyy
    (day first, as in BR, AR and IN), ISO yyyy-mm-dd, and long forms in the language ("3 de
    novembro de 2026", "Martes 03 de noviembre de 2026", "31st March, 2027", "June 30, 2027")."""
    t = fold(text)
    if not t:
        return []
    months = _MONTHS[lang]
    out: list[tuple[int, date]] = []

    def add(pos: int, y: int, m: int, d: int) -> None:
        try:
            out.append((pos, date(y, m, d)))
        except ValueError:
            pass

    for m in _ISO_DATE_RE.finditer(t):
        add(m.start(), int(m[1]), int(m[2]), int(m[3]))
    for m in _NUM_DATE_RE.finditer(t):
        if not any(p == m.start() or abs(p - m.start()) < 3 for p, _ in out):
            add(m.start(), int(m[3]), int(m[2]), int(m[1]))
    for m in _LONG_DMY_RE.finditer(t):
        mon = months.get(m["mon"].rstrip("."))
        if mon:
            add(m.start(), int(m["y"]), mon, int(m["d"]))
    if lang == "en":
        for m in _LONG_MDY_RE.finditer(t):
            mon = months.get(m["mon"].rstrip("."))
            if mon:
                add(m.start(), int(m["y"]), mon, int(m["d"]))
    out.sort(key=lambda pd: pd[0])
    return out


def parse_local_date(text: str | None, lang: str) -> date | None:
    """The first date written in `text` (see ``find_dates``), or None."""
    found = find_dates(text, lang)
    return found[0][1] if found else None


def _iso_prefix(value: Any) -> date | None:
    m = re.match(r"^\s*(\d{4})-(\d{2})-(\d{2})", value) if isinstance(value, str) else None
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


_PT_MONTHS = {"janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7,
              "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}
_ES_MONTHS = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
              "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}
_EN_MONTHS = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8,
              "september": 9, "october": 10, "november": 11, "december": 12, "jan": 1, "feb": 2, "mar": 3,
              "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12}
_MONTHS = {"pt": _PT_MONTHS, "es": _ES_MONTHS, "en": _EN_MONTHS}
# (?!\d), not \b: an ISO timestamp ("2026-11-02T15:20:00-03:00") is a date too.
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?!\d)")
_NUM_DATE_RE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b")
_LONG_DMY_RE = re.compile(r"\b(?P<d>\d{1,2})(?:st|nd|rd|th|o)?\s+(?:de\s+|of\s+)?(?P<mon>[a-z]{3,10}\.?),?\s+(?:de\s+|del\s+)?(?P<y>\d{4})\b")
_LONG_MDY_RE = re.compile(r"\b(?P<mon>[a-z]{3,10}\.?)\s+(?P<d>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<y>\d{4})\b")


def sentences_with(text: str, keywords: KeywordSet, max_n: int = 3, max_chars: int = EXCERPT_MAX_CHARS) -> str | None:
    """Up to `max_n` sentences of `text` that match `keywords`, verbatim (whitespace collapsed)."""
    parts = re.split(r"(?<=[.;:])\s+(?=[A-ZÁÉÍÓÚÑÇ0-9(\"“«])", clean(text))
    picked = [p for p in parts if keywords.matches(p)][:max_n]
    out = " … ".join(p[:600] for p in picked)
    return out[:max_chars] or None


# ===========================================================================
# Topics and document types
# ===========================================================================

_EU_PT_RE = re.compile(r"\buniao europeia\b|\bbloco europeu\b|\bcomissao europeia\b|\bdg sante\b|\bue\b")
_LISTING_PT_RE = re.compile(
    r"\blista\b|\bhabilit\w*|\breinclu\w*|\breabilit\w*|\b2021/405\b|\bantimicrobian\w*|\bauditori\w*"
    r"|\bexclu\w*|\bsuspens\w*|\bdescredenci\w*|\bpaises terceiros\b"
)
_TOPIC_RES: dict[str, dict[str, re.Pattern[str]]] = {
    "pt": {
        "residues": re.compile(r"\bresidu\w*|\bpncrc\b|\bcontaminant\w*|\bantibiotic\w*|\blimites? maximos?\b"),
        "export": re.compile(r"\bhabilit\w*|\bcertificad\w*|\bcertificac\w*|\brequisit\w*|\bexigenc\w*|\bcotas?\b"
                             r"|\btarifa\w*|\bembargo\w*|\bsuspens\w*|\bproib\w*|\b2021/405\b|\bcontingente\w*"),
    },
    "es": {
        "residues": re.compile(r"\bresidu\w*|\bear\b|\bcreha\b|\blmr\b|\bcontaminant\w*|\bantibiotic\w*"
                               r"|\boxitetraciclin\w*|\blimites? maximos?\b"),
        "export": re.compile(r"\bcertific\w*|\bcupos?\b|\bcontingente\w*|\btambor\w*|\bbarniz\b|\bbarnices\b"
                             r"|\bbisfenol\w*|\bbpa\b|\bhabilit\w*|\brequisit\w*|\bderechos? de exportacion\b"
                             r"|\barancel\w*|\breintegro\w*"),
    },
    "en": {
        "mep": re.compile(r"\bminimum export price\b|\bmep\b"),
        "residues": re.compile(r"\bresidue\w*|\bcontaminant\w*|\bantibiotic\w*"),
        "export": re.compile(r"\bexport policy\b|\bprohibit\w*|\brestrict\w*|\bfree subject to\b|\bexport\w*"),
    },
}
_NORMATIVE_PT_RE = re.compile(r"\b(?:portaria|instrucao normativa|resolucao|decreto|lei|deliberacao)\b")
_NORMATIVE_ES_RE = re.compile(r"\b(?:resolucion|decreto|disposicion|ley|decision administrativa)\b")


def topics_of(text: str, lang: str) -> list[str]:
    """Topic tags of an official text (folded match). "eu_listing" is Portuguese only: the EU list
    of third countries authorised to export honey (Reg. 2021/405)."""
    t = fold(text)
    tags = [name for name, rx in _TOPIC_RES[lang].items() if rx.search(t)]
    if lang == "pt" and _EU_PT_RE.search(t) and _LISTING_PT_RE.search(t):
        tags.append("eu_listing")
    return sorted(set(tags))


def doc_type_for(topics: Iterable[str], *, normative: bool) -> str:
    """price_floor > export_rule (EU listing) > residue_alert > export_rule > regulation (a
    normative act in an official gazette) > notice."""
    tags = set(topics)
    if "mep" in tags:
        return "price_floor"
    if "eu_listing" in tags:
        return "export_rule"
    if "residues" in tags:
        return "residue_alert"
    if "export" in tags:
        return "export_rule"
    return "regulation" if normative else "notice"


def is_eu_listing_pt(*texts: str | None) -> bool:
    """News that may concern the EU third-country list, whether or not it names honey."""
    t = fold(" ".join(x for x in texts if x))
    return bool(_EU_PT_RE.search(t) and _LISTING_PT_RE.search(t))


# ===========================================================================
# URLs, state, storage
# ===========================================================================

_TRACKING_PARAM_RE = re.compile(r"^(?:utm_|fbclid$|gclid$)")


def canonical_url(href: Any, base: str) -> str | None:
    """Absolute https URL without fragment, tracking parameters, trailing slash or Plone "/view"
    suffix. None for javascript:, mailto: and anchors."""
    if not isinstance(href, str) or not href.strip():
        return None
    href = href.strip()
    if href.startswith(("javascript:", "mailto:", "tel:", "#", "data:")):
        return None
    parts = urlsplit(urljoin(base, href))
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    path = re.sub(r"/view$", "", parts.path.rstrip("/")) or "/"
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING_PARAM_RE.match(k.lower())]
    return urlunsplit(("https", parts.netloc.lower(), path, urlencode(query), ""))


def url_reference(prefix: str, url: str) -> str:
    """Stable `reference` for an item identified by its URL (<= 200 characters)."""
    parts = urlsplit(url)
    key = parts.path + (f"?{parts.query}" if parts.query else "")
    ref = f"{prefix}:{key}"
    if len(ref) <= 200:
        return ref
    return f"{prefix}:{key[:150]}~{hashlib.sha1(url.encode()).hexdigest()[:16]}"


def _short_reference(prefix: str, ident: str) -> str:
    ref = f"{prefix}{ident}"
    if len(ref) <= 200:
        return ref
    return f"{prefix}{ident[:150]}~{hashlib.sha1(ident.encode()).hexdigest()[:16]}"


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


def _iso_date(value: Any) -> date | None:
    return _iso_prefix(value)


def _known_refs(ctx: CollectContext) -> set[str]:
    return set(ctx.session.scalars(select(RegulationItem.reference).where(RegulationItem.source_id == ctx.source.id)))


def _polite(ctx: CollectContext) -> None:
    ctx.MIN_INTERVAL_PER_HOST = max(ctx.MIN_INTERVAL_PER_HOST, POLITE_INTERVAL_S)


def _store(ctx: CollectContext, *, reference: str, jurisdiction: str, iso3: str, doc_type: str, title: str,
           url: str, published_at: date | None, extra: dict, status: str | None = None,
           effective_date: date | None = None, summary_en: str | None = None) -> bool:
    """Write one item (append-only). Returns True when it is new."""
    payload = {k: v for k, v in extra.items() if v not in (None, "", [], {})}
    _, is_new = ctx.add_regulation(
        reference=reference[:200], jurisdiction=jurisdiction, doc_type=doc_type, title=clean(title)[:1000],
        url=url[:1000], published_at=published_at, effective_date=effective_date, countries=[iso3],
        status=status, summary_en=summary_en, summary_it=None, summary_is_ai=False, extra=payload or None,
    )
    return is_new


def _snippet(content: bytes, n: int = 160) -> str:
    return re.sub(r"\s+", " ", content[:n].decode("utf-8", errors="replace")).strip()


class _FeedRunner:
    """Runs the independent feeds of one collector. Each feed is committed on its own.

    At the end:
    * the run fails (``CollectorError``) if any feed failed for another reason than an
      unreachable host (drift, HTTP error, crash; a crashed feed's uncommitted rows are rolled
      back);
    * if every feed failed only because a host could not be reached, the first ``Offline`` is
      re-raised, so the runner can tell "this PC is offline" from "this host is down";
    * if some feeds worked and the others only hit an unreachable host (the Boletín Oficial
      resets connections from some networks), the run is kept: each unreachable feed becomes a
      warning (a "partial" run) and is simply tried again on the next run."""

    def __init__(self, ctx: CollectContext):
        self.ctx = ctx
        self.errors: list[str] = []
        self.offline: list[Offline] = []
        self.offline_labels: list[str] = []
        self.ok = 0

    def run(self, label: str, fn: Callable[[], None]) -> None:
        try:
            fn()
        except Offline as exc:
            self.offline.append(exc)
            self.offline_labels.append(label)
            self.errors.append(f"{label}: {exc}")
        except CollectorError as exc:
            log.warning("[%s] feed %s failed: %s", self.ctx.source.key, label, exc)
            self.errors.append(f"{label}: {exc}")
        except Exception as exc:  # a parser bug in one feed must not skip the others (logged below)
            # Unexpected: whatever this feed wrote since the last checkpoint is not trusted (and the
            # session may need a rollback after a database error). The run still fails.
            log.exception("[%s] feed %s crashed", self.ctx.source.key, label)
            self.ctx.session.rollback()
            self.ctx.counters.restore_committed()
            self.errors.append(f"{label}: {type(exc).__name__}: {exc}")
        else:
            self.ok += 1
        self.ctx.checkpoint()

    def finish(self) -> None:
        if self.offline and not self.ok and len(self.offline) == len(self.errors):
            raise self.offline[0]
        if len(self.errors) > len(self.offline):
            raise CollectorError("; ".join(self.errors))
        for label, exc in zip(self.offline_labels, self.offline):
            self.ctx.warn(f"{label}: host unreachable ({exc}); this feed was skipped and is retried on the "
                          f"next run, the other feeds were read normally")


# ===========================================================================
# HTML helpers: generic news listing, article page, PDF text
# ===========================================================================


def _soup(content: bytes | str) -> BeautifulSoup:
    soup = BeautifulSoup(content, "lxml")
    for t in soup(["script", "style", "noscript", "template", "iframe", "svg"]):
        t.decompose()
    return soup


def _page_title(soup: BeautifulSoup) -> str:
    return clean(soup.title.get_text(" ")) if soup.title else ""


_ROOT_SELECTORS = ("#content-core", "main", "[role=main]", "#content", "#main-content", "#main")


def _main_root(soup: BeautifulSoup) -> Tag:
    for sel in _ROOT_SELECTORS:
        el = soup.select_one(sel)
        if el is not None and el.find("a", href=True) is not None:
            return el
    return soup.body or soup


@dataclass
class ListedItem:
    url: str
    title: str
    published_at: date | None
    description: str | None = None
    section: str | None = None


@dataclass
class ListingPage:
    url: str
    title: str
    items: list[ListedItem]
    next_url: str | None
    problems: list[str] = field(default_factory=list)


_DATE_CLASS_RE = re.compile(r"data|date|published|byline|fecha|hora|time", re.I)
_DESC_CLASS_RE = re.compile(r"descri|summary|resumo|tilebody|lead|bajada|copete|teaser|excerpt|resumen", re.I)
_KICKER_CLASS_RE = re.compile(r"subtitulo|subtitle|kicker|chapeu|categoria|category|volanta|antetitulo", re.I)
_LEADING_DATE_RE = re.compile(r"^\s*(?:\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})(?:\s*(?:\d{1,2}h\d{2}|\d{1,2}:\d{2}))?\s*[-–—|]?\s*")
_HEADINGS = ("h1", "h2", "h3", "h4", "h5")


def _anchor_title(a: Tag) -> str:
    heading = a.find(_HEADINGS)
    if heading is not None and clean(heading.get_text(" ")):
        return clean(heading.get_text(" "))
    text = clean(a.get_text(" "))
    if text:
        return text
    return clean(a.get("title")) or clean(a.get("aria-label"))


def _anchor_score(a: Tag) -> tuple[int, int]:
    in_heading = a.find_parent(_HEADINGS) is not None or a.find(_HEADINGS) is not None
    return (1 if in_heading else 0, len(clean(a.get_text(" "))))


def _item_container(a: Tag, own_url: str, item_urls: set[str], base: str, root: Tag) -> Tag:
    """The largest ancestor of `a` (within `root`, at most 6 levels up) that links to no other item."""
    best: Tag = a
    node: Tag = a
    for _ in range(6):
        parent = node.parent
        if parent is None or parent is root or parent.name in ("body", "html", "[document]"):
            break
        others = {canonical_url(x.get("href"), base) for x in parent.find_all("a", href=True)} & item_urls
        if others - {own_url}:
            break
        best = parent
        node = parent
    return best


def _container_date(container: Tag, title: str, lang: str) -> date | None:
    for t in container.find_all("time"):
        d = _iso_prefix(t.get("datetime")) or parse_local_date(t.get_text(" "), lang)
        if d:
            return d
    for el in container.find_all(class_=_DATE_CLASS_RE):
        d = parse_local_date(el.get_text(" "), lang)
        if d:
            return d
    text = clean(container.get_text(" "))
    if title:
        text = text.replace(title, " ")
    return parse_local_date(text, lang)


def _container_description(container: Tag, title: str) -> str | None:
    candidates = [el for el in container.find_all(class_=_DESC_CLASS_RE)]
    candidates += [p for p in container.find_all("p")]
    for el in candidates:
        text = _LEADING_DATE_RE.sub("", clean(el.get_text(" ")))
        if len(text) >= 20 and text != title and title not in text:
            return text[:2000]
    return None


def _container_section(container: Tag, title: str) -> str | None:
    for el in container.find_all(class_=_KICKER_CLASS_RE):
        text = clean(el.get_text(" "))
        if text and text != title and len(text) <= 80:
            return text
    return None


def find_next_page(soup: BeautifulSoup, page_url: str) -> str | None:
    """The next listing page: a link to the same path whose Plone ``b_start:int`` / ``b_start`` or
    Drupal ``page`` parameter is the smallest value above the current one."""
    cur = urlsplit(page_url)
    cur_q = dict(parse_qsl(cur.query))
    best: tuple[int, str] | None = None
    for a in soup.find_all("a", href=True):
        u = urljoin(page_url, a["href"])
        p = urlsplit(u)
        if p.netloc.lower() != cur.netloc.lower() or p.path.rstrip("/") != cur.path.rstrip("/"):
            continue
        q = dict(parse_qsl(p.query))
        for name in ("b_start:int", "b_start", "page"):
            v, c = q.get(name, ""), cur_q.get(name, "0") or "0"
            if v.isdigit() and int(v) > (int(c) if c.isdigit() else 0):
                if best is None or int(v) < best[0]:
                    best = (int(v), u)
    return best[1] if best else None


def parse_listing(content: bytes | str, page_url: str, *, item_url_re: re.Pattern[str], lang: str,
                  label: str) -> ListingPage:
    """Items of a news listing page: every link whose canonical URL matches `item_url_re`, with
    the date, summary and section found in the link's own block.

    Raises ``SchemaDrift`` when the page holds no such link (layout or URL changed). The caller
    checks dates (``check_listing_dates``)."""
    soup = _soup(content)
    title = _page_title(soup)
    self_url = canonical_url(page_url, page_url)
    problems: list[str] = []

    def collect(root: Tag) -> dict[str, list[Tag]]:
        found: dict[str, list[Tag]] = {}
        for a in root.find_all("a", href=True):
            u = canonical_url(a["href"], page_url)
            if u is None or u == self_url or not item_url_re.match(u):
                continue
            found.setdefault(u, []).append(a)
        return found

    root = _main_root(soup)
    by_url = collect(root)
    if not by_url and root is not (soup.body or soup):
        root = soup.body or soup
        by_url = collect(root)
        if by_url:
            problems.append(f"{label}: items found only outside the main content area (layout changed?)")
    if not by_url:
        raise SchemaDrift(
            f"{label}: no item link matching {item_url_re.pattern!r} on {page_url} (page title {title!r}); "
            f"the page layout or its URL has changed. Starts with {_snippet(content.encode() if isinstance(content, str) else content)!r}"
        )
    item_urls = set(by_url)
    items: list[ListedItem] = []
    for u, anchors in by_url.items():
        best = max(anchors, key=_anchor_score)
        item_title = max((_anchor_title(a) for a in anchors), key=len)
        if len(item_title) < 8:
            problems.append(f"{label}: link {u} has no usable title; skipped")
            continue
        container = _item_container(best, u, item_urls, page_url, root)
        items.append(ListedItem(
            url=u, title=item_title[:1000], published_at=_container_date(container, item_title, lang),
            description=_container_description(container, item_title),
            section=_container_section(container, item_title),
        ))
    return ListingPage(url=page_url, title=title, items=items, next_url=find_next_page(soup, page_url),
                       problems=problems)


def check_listing_dates(page: ListingPage, label: str) -> None:
    """Probe: a listing of three or more items where no item has a date means the date markup
    changed. Storing undated official notices would hide how old they are."""
    if len(page.items) >= 3 and not any(i.published_at for i in page.items):
        raise SchemaDrift(f"{label}: none of the {len(page.items)} items on {page.url} has a readable date; "
                          f"the date markup has changed")


@dataclass
class ArticlePage:
    text: str
    published_at: date | None
    description: str | None


_ARTICLE_SELECTORS = ("#parent-fieldname-text", "#content-core", "#cuerpoDetalleAviso", "article", "main",
                      "[role=main]", "#content")
_META_DATE_SELECTORS = ('meta[property="article:published_time"]', 'meta[name="DC.date.created"]',
                        'meta[name="DC.date"]', 'meta[itemprop="datePublished"]', 'meta[name="date"]')


def parse_article(content: bytes | str, lang: str) -> ArticlePage:
    """Body text, publication date and official description of an article page."""
    soup = _soup(content)
    published: date | None = None
    for sel in _META_DATE_SELECTORS:
        m = soup.select_one(sel)
        if m is not None and m.get("content"):
            published = _iso_prefix(m["content"]) or parse_local_date(m["content"], lang)
            if published:
                break
    if published is None:
        for el in soup.find_all("time"):
            published = _iso_prefix(el.get("datetime")) or parse_local_date(el.get_text(" "), lang)
            if published:
                break
    if published is None:
        for el in soup.find_all(class_=re.compile(r"documentPublished|documentByLine|fecha|data-publicacao", re.I)):
            published = parse_local_date(el.get_text(" "), lang)
            if published:
                break
    description = None
    meta = soup.select_one('meta[name="description"]') or soup.select_one('meta[property="og:description"]')
    if meta is not None and clean(meta.get("content")):
        description = clean(meta.get("content"))[:2000]
    desc_el = soup.select_one(".documentDescription")
    if desc_el is not None and clean(desc_el.get_text(" ")):
        description = clean(desc_el.get_text(" "))[:2000]
    for t in soup(["nav", "footer", "header"]):
        t.decompose()
    text = ""
    for sel in _ARTICLE_SELECTORS:
        el = soup.select_one(sel)
        if el is not None and len(clean(el.get_text(" "))) >= 80:
            text = clean(el.get_text(" "))
            break
    if not text:
        text = clean((soup.body or soup).get_text(" "))
    return ArticlePage(text=text, published_at=published, description=description)


def pdf_text(content: bytes, max_pages: int = PDF_MAX_PAGES) -> str:
    """Text of a PDF ("" when it is not a PDF, is damaged, or is a scan without a text layer)."""
    if not content.lstrip()[:5].startswith(b"%PDF"):
        return ""
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(content)) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages[:max_pages])
    except Exception as exc:  # noqa: BLE001 - pdfminer raises many exception types on damaged files
        log.warning("PDF text extraction failed: %s", exc)
        return ""


# ===========================================================================
# Generic news-feed runner (MAPA, SENASA)
# ===========================================================================


@dataclass(frozen=True)
class NewsFeed:
    feed_id: str                         # extra["feed"] and the state key prefix
    label: str
    listing_url: str
    item_url_re: re.Pattern[str]
    lang: str
    ref_prefix: str
    jurisdiction: str
    iso3: str
    publisher: str
    keywords: KeywordSet
    pages: int                           # listing pages read on a normal run
    backfill_pages: int                  # ... on the first run or with --force
    # Folded listing text -> open the article and look for honey in its body.
    body_candidate: Callable[..., bool] | None = None


def run_news_feed(ctx: CollectContext, feed: NewsFeed, state: dict) -> None:
    """Read the listing (a few pages), keep honey items, store new ones. See the module docstring."""
    t = today()
    complete_key = f"{feed.feed_id}_complete"
    checked_key = f"{feed.feed_id}_body_checked"
    max_pages = feed.backfill_pages if (ctx.force or not state.get(complete_key)) else feed.pages
    url: str | None = feed.listing_url
    items: dict[str, ListedItem] = {}
    for page_no in range(1, max_pages + 1):
        if url is None:
            break
        doc = ctx.fetch(url, headers=HTML_HEADERS, title=f"{feed.label} (page {page_no})")
        page = parse_listing(doc.content, doc.url, item_url_re=feed.item_url_re, lang=feed.lang, label=feed.label)
        check_listing_dates(page, feed.label)
        for p in page.problems:
            ctx.warn(p)
        for it in page.items:
            items.setdefault(it.url, it)
        url = page.next_url

    known = _known_refs(ctx)
    checked: dict[str, str] = dict(state.get(checked_key) or {})
    budget = MAX_ARTICLE_FETCHES
    postponed = 0
    unread = 0
    for it in items.values():
        ref = url_reference(feed.ref_prefix, it.url)
        if ref in known:
            ctx.counters.count("unchanged")
            continue
        kws = feed.keywords.matches(it.title, it.description, it.section)
        matched_in = "listing"
        article: ArticlePage | None = None
        if not kws:
            if feed.body_candidate is None or not feed.body_candidate(it.title, it.description, it.section):
                continue
            if it.url in checked:
                continue
        # The article page is needed to look for honey in its body, or to read the date that the
        # listing does not give. Storing is final (append-only): an item stored without the date
        # its page states would stay undated for good, so it waits for a later run instead.
        if not kws or it.published_at is None:
            if budget <= 0:
                postponed += 1
                continue
            budget -= 1
            article = _open_article(ctx, feed, it)
            if article is None:
                unread += 1              # warned by _open_article; retried next run
                continue
        if not kws:
            kws = feed.keywords.matches(article.text)
            if not kws:
                checked[it.url] = t.isoformat()
                continue
            matched_in = "article"
        published = it.published_at or (article.published_at if article else None)
        description = it.description or (article.description if article else None)
        topic_text = " ".join(x for x in (it.title, description, it.section) if x)
        if matched_in == "article" and article is not None:
            topic_text += " " + article.text[:4000]
        topics = topics_of(topic_text, feed.lang)
        _store(
            ctx, reference=ref, jurisdiction=feed.jurisdiction, iso3=feed.iso3,
            doc_type=doc_type_for(topics, normative=False), title=it.title, url=it.url, published_at=published,
            extra={
                "feed": feed.feed_id, "publisher": feed.publisher, "language": feed.lang, "watcher": "html_page",
                "listing_url": feed.listing_url, "summary_original": description, "section": it.section,
                "keywords": kws, "matched_in": matched_in, "topics": topics,
                "excerpt_original": sentences_with(article.text, feed.keywords) if matched_in == "article" and article else None,
                "date_source": "article" if published and not it.published_at else None,
            },
        )
    if postponed:
        ctx.warn(f"{feed.label}: {postponed} article(s) to check were postponed to the next run "
                 f"(at most {MAX_ARTICLE_FETCHES} per run)")
    # Work left over (postponed or unreadable articles) may sit on a back-fill page beyond the
    # `pages` of a normal run: the feed stays in back-fill mode until nothing is left.
    if postponed or unread:
        state.pop(complete_key, None)
    else:
        state[complete_key] = t.isoformat()
    state[checked_key] = dict(sorted(checked.items(), key=lambda kv: kv[1])[-BODY_CHECKED_MAX:])


def _open_article(ctx: CollectContext, feed: NewsFeed, it: ListedItem) -> ArticlePage | None:
    try:
        doc = ctx.fetch(it.url, headers=HTML_HEADERS, title=it.title[:300], published_at=it.published_at)
    except Offline:
        raise
    except CollectorError as exc:
        ctx.warn(f"{feed.label}: article {it.url} could not be read ({exc}); retried next run")
        return None
    return parse_article(doc.content, feed.lang)


# ===========================================================================
# 1) Brazil: MAPA news + Diário Oficial da União
# ===========================================================================

MAPA_NEWS_URL = "https://www.gov.br/agricultura/pt-br/assuntos/noticias"
MAPA_ITEM_RE = re.compile(r"^https://www\.gov\.br/agricultura/pt-br/assuntos/noticias/(?!@@|\+\+)(?!rss$|RSS$)[^?#]+$")
MAPA_PUBLISHER = "Ministério da Agricultura e Pecuária (MAPA), gov.br"

MAPA_NEWS = NewsFeed(
    feed_id="mapa_news", label="MAPA news (gov.br)", listing_url=MAPA_NEWS_URL, item_url_re=MAPA_ITEM_RE,
    lang="pt", ref_prefix="mapa", jurisdiction="BR", iso3="BRA", publisher=MAPA_PUBLISHER, keywords=HONEY_PT,
    pages=2, backfill_pages=5, body_candidate=is_eu_listing_pt,
)

# DOU search (Imprensa Nacional). Parameters and the results <script> as used by Ro-DOU (unverified here).
DOU_SEARCH_URL = "https://www.in.gov.br/consulta/-/buscar/dou"
DOU_ITEM_BASE = "https://www.in.gov.br/web/dou/-/"
DOU_SCRIPT_ID = "_br_com_seatecnologia_in_buscadou_BuscaDouPortlet_params"
DOU_QUERIES: tuple[str, ...] = ('"mel"', '"apícola"', '"apicultura"')
DOU_SECTION = "do1"                  # Section 1: normative acts
DOU_PAGE_SIZE = 100
DOU_PUBLISHER = "Imprensa Nacional, Diário Oficial da União (DOU), Seção 1"
_MAPA_HIERARCHY_RE = re.compile(r"\bagricultura\b|\bmapa\b")


def dou_window(last_complete: str | None, ref: date, force: bool = False) -> str:
    """``exactDate`` of the DOU search: the last year on the first run (or when forced), otherwise
    the shortest window ("semana", "mes", "ano") that still overlaps the last complete run."""
    last = _iso_date(last_complete)
    if force or last is None:
        return "ano"
    gap = (ref - last).days
    if gap <= 5:
        return "semana"
    if gap <= 25:
        return "mes"
    return "ano"


@dataclass
class DouAct:
    url_title: str
    title: str
    published_at: date | None
    section: str | None
    art_type: str | None
    hierarchy: str
    excerpt: str
    edition: str | None
    page: str | None

    @property
    def url(self) -> str:
        return DOU_ITEM_BASE + self.url_title

    @property
    def is_mapa(self) -> bool:
        return bool(_MAPA_HIERARCHY_RE.search(fold(self.hierarchy)) or re.search(r"\bmapa\b", fold(self.title)))


def parse_dou_search(content: bytes, url: str | None = None) -> tuple[list[DouAct], list[str]]:
    """Results of one DOU search page, from the JSON in the results <script>.

    Raises ``SchemaDrift`` when the script, its JSON or its ``jsonArray`` is missing, or when no
    result carries ``urlTitle`` and ``title``. An empty ``jsonArray`` is a valid answer. `url`
    (the page read) is named in the error."""
    soup = BeautifulSoup(content, "lxml")
    where = f"DOU search ({url})" if url else "DOU search"
    tag = soup.find("script", id=DOU_SCRIPT_ID)
    if tag is None:
        raise SchemaDrift(f"{where}: the results script #{DOU_SCRIPT_ID} is missing (page title "
                          f"{_page_title(soup)!r}); the search page has changed")
    try:
        obj = json.loads(tag.string or tag.get_text() or "")
    except ValueError as exc:
        raise SchemaDrift(f"{where}: the results script is not JSON ({exc})") from exc
    arr = obj.get("jsonArray") if isinstance(obj, dict) else None
    if not isinstance(arr, list):
        keys = sorted(obj)[:10] if isinstance(obj, dict) else type(obj).__name__
        raise SchemaDrift(f"{where}: no 'jsonArray' list in the results script (keys: {keys})")
    acts: list[DouAct] = []
    problems: list[str] = []
    for i, r in enumerate(arr):
        if not isinstance(r, dict):
            problems.append(f"DOU result {i} is not an object; skipped")
            continue
        url_title = r.get("urlTitle")
        title = strip_tags(r.get("title"))
        # Slugs such as "portaria-sda/mapa-n-1.266-de-16-de-abril-de-2025-623774851" (one "/" is usual).
        if (not isinstance(url_title, str) or not re.fullmatch(r"[\w.\-]+(?:/[\w.\-]+)*", url_title.strip())
                or ".." in url_title or not title):
            problems.append(f"DOU result {i} has no usable urlTitle/title; skipped")
            continue
        hierarchy = r.get("hierarchyStr")
        if not isinstance(hierarchy, str):
            hl = r.get("hierarchyList")
            hierarchy = "/".join(str(x) for x in hl) if isinstance(hl, list) else ""
        published = parse_local_date(r.get("pubDate"), "pt") if isinstance(r.get("pubDate"), str) else None
        if published is None:
            problems.append(f"DOU act {url_title}: pubDate {r.get('pubDate')!r} is not a date")
        acts.append(DouAct(
            url_title=url_title.strip(), title=title, published_at=published,
            section=clean(r.get("pubName")) or None, art_type=clean(r.get("artType")) or None,
            hierarchy=clean(hierarchy), excerpt=strip_tags(r.get("content")),
            edition=clean(str(r.get("editionNumber") or "")) or None, page=clean(str(r.get("numberPage") or "")) or None,
        ))
    if arr and not acts:
        raise SchemaDrift(f"{where}: none of the {len(arr)} results has 'urlTitle' and 'title' "
                          f"(keys of the first: {sorted(arr[0])[:12] if isinstance(arr[0], dict) else type(arr[0]).__name__})")
    return acts, problems


class BrMapaHoneyCollector(Collector):
    key = "br_mapa_honey"
    name = "MAPA Brasile: avvisi e norme sul miele (lista UE, residui, export)"
    name_en = "MAPA Brazil: honey notices and rules (EU list, residues, exports)"
    publisher = "Ministério da Agricultura e Pecuária (MAPA), Brasil; Imprensa Nacional (Diário Oficial da União)"
    homepage = "https://www.gov.br/agricultura/pt-br"
    kind = SourceKind.HTML
    reliability = Reliability.OFFICIAL
    category = "regulation"
    country_iso3 = "BRA"
    language = "pt"
    expected_update = "Controllo giornaliero; gli avvisi sul miele sono occasionali: settimane senza novità sono normali"
    expected_update_en = "Daily check; honey notices are event-driven, so weeks with no new item are normal"
    expected_max_age_days = 120
    terms_note = (
        "Brazilian federal government content (gov.br, Diário Oficial da União): public information, reuse with "
        "attribution. PAGE WATCHER: it reads the MAPA news listing and the DOU search page as HTML. Their layout "
        "was reconstructed without live access and may need adjustment; a run fails with a clear message when "
        "the expected structure is not found. Texts are kept verbatim in Portuguese (never machine-translated). "
        "Only honey items are kept, including EU third-country list news whose article body names honey."
    )
    schedule = {"trigger": "cron", "hour": 6, "minute": 50}

    def collect(self, ctx: CollectContext) -> None:
        _polite(ctx)
        state = _get_state(ctx.session, self.key)
        runner = _FeedRunner(ctx)

        def news() -> None:
            run_news_feed(ctx, MAPA_NEWS, state)
            _set_state(ctx.session, self.key, state)

        def dou() -> None:
            self._dou(ctx, state)
            _set_state(ctx.session, self.key, state)

        runner.run(MAPA_NEWS.label, news)
        runner.run("Diário Oficial da União (DOU search)", dou)
        runner.finish()

    def _dou(self, ctx: CollectContext, state: dict) -> None:
        t = today()
        window = dou_window(state.get("dou_complete"), t, ctx.force)
        for q in DOU_QUERIES:
            params = {"q": q, "s": DOU_SECTION, "exactDate": window, "sortType": "0", "delta": str(DOU_PAGE_SIZE)}
            doc = ctx.fetch(DOU_SEARCH_URL, params=params, headers=HTML_HEADERS, title=f"DOU search {q} ({window})")
            acts, problems = parse_dou_search(doc.content, doc.url)  # SchemaDrift propagates
            for p in problems:
                ctx.warn(p)
            if len(acts) >= DOU_PAGE_SIZE:
                ctx.warn(f"DOU search {q} ({window}): {len(acts)} results, the page limit; older acts may be missing")
            for act in acts:
                self._store_act(ctx, act, q, window)
        state["dou_complete"] = t.isoformat()

    def _store_act(self, ctx: CollectContext, act: DouAct, query: str, window: str) -> None:
        if not act.is_mapa:
            return                       # another body's act: out of scope for this watcher
        kws = HONEY_PT.matches(act.title, act.excerpt)
        if not kws:
            return                       # the search engine matched something that is not honey
        normative = bool(_NORMATIVE_PT_RE.search(fold(f"{act.art_type or ''} {act.title}")))
        topics = topics_of(f"{act.title} {act.excerpt}", "pt")
        _store(
            ctx, reference=_short_reference("dou:", act.url_title), jurisdiction="BR", iso3="BRA",
            doc_type=doc_type_for(topics, normative=normative), title=act.title, url=act.url,
            published_at=act.published_at, status="published",
            extra={
                "feed": "dou", "publisher": DOU_PUBLISHER, "language": "pt", "watcher": "html_page",
                "art_type": act.art_type, "issuing_body": act.hierarchy, "dou_section": act.section,
                "edition": act.edition, "page": act.page, "excerpt_original": act.excerpt[:EXCERPT_MAX_CHARS],
                "keywords": kws, "topics": topics, "search": {"q": query, "window": window},
            },
        )


# ===========================================================================
# 2) Argentina: SENASA news, Plan CREHA "Lista EAR", Boletín Oficial
# ===========================================================================

SENASA_NEWS_URL = "https://www.argentina.gob.ar/senasa/noticias"        # UNVERIFIED listing URL
SENASA_ITEM_RE = re.compile(r"^https://www\.argentina\.gob\.ar/(?:[a-z0-9-]+/)?noticias/[a-z0-9][a-z0-9-]*$")
SENASA_PUBLISHER = "SENASA (Servicio Nacional de Sanidad y Calidad Agroalimentaria), argentina.gob.ar"
SENASA_CREHA_URL = "https://www.argentina.gob.ar/node/106753"           # Plan CREHA (from research)

SENASA_NEWS = NewsFeed(
    feed_id="senasa_news", label="SENASA news (argentina.gob.ar)", listing_url=SENASA_NEWS_URL,
    item_url_re=SENASA_ITEM_RE, lang="es", ref_prefix="senasa", jurisdiction="AR", iso3="ARG",
    publisher=SENASA_PUBLISHER, keywords=HONEY_ES, pages=2, backfill_pages=4,
)

EAR_CHECK_DAYS = 7                   # the CREHA page is read at most weekly
EAR_MAX_PDFS = 12                    # new EAR PDFs downloaded per run
_EAR_FILE_RE = re.compile(r"(?<![a-z])ear[_-]?(?P<n>\d{1,2})[_-](?P<y>\d{2}|\d{4})(?!\d)", re.I)
_EAR_TEXT_NO_RE = re.compile(r"\b(?:n\s*[o.]?\s*|nro\.?\s*|numero\s+)(\d{1,2})\b")
_EAR_TEXT_YEAR_RE = re.compile(r"\b(20\d{2})\b")

BO_HOST = "https://www.boletinoficial.gob.ar"
BO_LATEST_URL = f"{BO_HOST}/seccion/primera"                            # latest edition (from research)
BO_DATED_URL = BO_HOST + "/seccion/primera/{ymd}"                      # UNVERIFIED: catch-up only
BO_DETAIL_URL = BO_HOST + "/detalleAviso/primera/{aviso_id}/{ymd}"
BO_PUBLISHER = "Boletín Oficial de la República Argentina, primera sección"
BO_MAX_DETAILS = 15                  # notices opened per run
BO_CATCHUP_DAYS = 5                  # business days read back when runs were missed
BO_PENDING_MAX = 200
BO_REJECTED_MAX = 3000
_BO_AVISO_RE = re.compile(r"/detalleAviso/primera/(\d+)/(\d{8})")
_BO_GDE_RE = re.compile(r"^[A-Z]{2,}-\d{4}-\d+-APN-")
# Notices worth opening: agriculture bodies, export duties, or honey already in the listing text.
_BO_PREFILTER_RE = re.compile(r"agricultura|ganaderia|senasa|sanidad y calidad agroalimentaria|exportacion"
                              r"|apicol|(?<!luna de )\bmiel\b")


_EAR_IMPO_RE = re.compile(r"\bimpo\b|\bimportad")


@dataclass
class EarLink:
    url: str
    text: str
    number: int | None
    year: int | None
    listed_date: date | None
    kind: str | None = None              # "Impo": the separate list of imported products under surveillance

    @property
    def reference(self) -> str:
        if self.number is not None and self.year is not None:
            # The domestic lists keep the plain form; the import list has its own numbering.
            kind = f"{self.kind} " if self.kind else ""
            return f"SENASA Lista EAR {kind}{self.year} N°{self.number:02d}"
        return url_reference("senasa-ear", self.url)

    @property
    def title(self) -> str:
        if len(self.text) >= 8 and re.search(r"\bear\b", fold(self.text)):
            return self.text
        if self.number is not None and self.year is not None:
            return f"SENASA, Lista EAR Año {self.year} N°{self.number:02d}"
        return self.text or self.url.rsplit("/", 1)[-1]


def find_ear_links(content: bytes | str, page_url: str) -> tuple[list[EarLink], int]:
    """("Lista EAR" PDF links, number of PDF links on the page). A link is an EAR list when its
    file name looks like ``ear_09-25_producto.pdf`` or its text names "EAR"."""
    soup = _soup(content)
    links: dict[str, EarLink] = {}
    pdfs = 0
    for a in soup.find_all("a", href=True):
        u = canonical_url(a["href"], page_url)
        if u is None or not urlsplit(u).path.lower().endswith(".pdf"):
            continue
        pdfs += 1
        text = clean(a.get_text(" ")) or clean(a.get("title"))
        fname = urlsplit(u).path.rsplit("/", 1)[-1]
        m = _EAR_FILE_RE.search(fname)
        if not m and not re.search(r"\bear\b", fold(text)):
            continue
        number = int(m["n"]) if m else None
        year = (2000 + int(m["y"]) if len(m["y"]) == 2 else int(m["y"])) if m else None
        ft = fold(text)
        if number is None:
            nm = _EAR_TEXT_NO_RE.search(ft)
            number = int(nm[1]) if nm else None
        if year is None:
            ym = _EAR_TEXT_YEAR_RE.search(ft)
            year = int(ym[1]) if ym else None
        context = clean(a.parent.get_text(" ")) if a.parent is not None else text
        kind = "Impo" if _EAR_IMPO_RE.search(ft) or _EAR_IMPO_RE.search(fname.lower().replace("_", " ")) else None
        links.setdefault(u, EarLink(url=u, text=text, number=number, year=year,
                                    listed_date=parse_local_date(context, "es"), kind=kind))
    return list(links.values()), pdfs


@dataclass
class EarPdf:
    text_ok: bool
    honey_rows: list[str]
    list_date: date | None
    title: str | None = None             # "LISTA EAR AÑO 2026 N° 09 - Por Producto", as printed
    list_year: int | None = None
    list_number: int | None = None


_EAR_TITLE_RE = re.compile(r"\blista\s+ear\b.*?\bano\s+(?P<y>20\d{2})\s+n\D{0,3}(?P<n>\d{1,3})\b")
_DMY_RE = re.compile(r"(?<![\d/])(\d{1,2}/\d{1,2}/20\d{2})(?![\d/])")


def parse_ear_pdf(content: bytes) -> EarPdf:
    """Lines of a "Lista EAR" that name honey, verbatim, and the list date when the header states it.

    The real lists print the date alone in the page header, before the title line ("Coordinación
    General de Vigilancia ... Plan CREHA Animal 08/10/2026", then "LISTA EAR AÑO 2026 N° 09 - Por
    Producto"; older lists put it on its own first line). It is taken when the header holds exactly
    one dd/mm/yyyy date (or one after "Fecha"), in the list's year or the next one."""
    text = pdf_text(content)
    lines = [clean(x) for x in text.splitlines() if clean(x)]
    if sum(len(x) for x in lines) < 40:
        return EarPdf(text_ok=False, honey_rows=[], list_date=None)
    honey = [x for x in lines if _HONEY_PRODUCT_ES_RE.search(fold(x))]
    title_idx = next((i for i, x in enumerate(lines[:15]) if _EAR_TITLE_RE.search(fold(x))), None)
    title = lines[title_idx] if title_idx is not None else None
    tm = _EAR_TITLE_RE.search(fold(title)) if title else None
    list_year, list_number = (int(tm["y"]), int(tm["n"])) if tm else (None, None)
    head_lines = lines[: title_idx + 1] if title_idx is not None else lines[:6]
    head = fold(" ".join(head_lines))
    m = re.search(r"fecha[^:0-9]{0,30}:?\s*(\d{1,2}/\d{1,2}/\d{4})", fold(" ".join(lines[:15])))
    candidates = [m[1]] if m else list(dict.fromkeys(_DMY_RE.findall(head)))
    list_date = parse_local_date(candidates[0], "es") if len(candidates) == 1 else None
    if list_date and list_year and list_date.year not in (list_year, list_year + 1):
        list_date = None                 # a date of another year is not this list's date
    return EarPdf(text_ok=True, honey_rows=honey, list_date=list_date, title=title,
                  list_year=list_year, list_number=list_number)


@dataclass
class BoAviso:
    aviso_id: str
    pub_date: date
    lines: list[str]
    rubro: str | None = None
    attempts: int = 0

    @property
    def url(self) -> str:
        return BO_DETAIL_URL.format(aviso_id=self.aviso_id, ymd=f"{self.pub_date:%Y%m%d}")

    @property
    def reference(self) -> str:
        return f"BO-AR primera {self.aviso_id}"

    @property
    def gde(self) -> str | None:
        return next((x for x in self.lines if _BO_GDE_RE.match(x)), None)

    @property
    def organism(self) -> str:
        return self.lines[0] if self.lines else ""

    @property
    def norm(self) -> str | None:
        return next((x for x in self.lines[1:] if not _BO_GDE_RE.match(x)), None)

    @property
    def title(self) -> str:
        return " — ".join(x for x in (self.organism, self.norm) if x) or f"Boletín Oficial, aviso {self.aviso_id}"

    def to_state(self) -> dict:
        return {"id": self.aviso_id, "date": self.pub_date.isoformat(), "lines": self.lines[:4], "rubro": self.rubro,
                "attempts": self.attempts}

    @classmethod
    def from_state(cls, d: Any) -> BoAviso | None:
        if not isinstance(d, dict) or not str(d.get("id", "")).isdigit():
            return None
        pub = _iso_date(d.get("date"))
        if pub is None:
            return None
        lines = [clean(x) for x in d.get("lines") or [] if isinstance(x, str)]
        return cls(aviso_id=str(d["id"]), pub_date=pub, lines=lines, rubro=d.get("rubro") or None,
                   attempts=int(d.get("attempts") or 0))


def _bo_rubro(a: Tag) -> str | None:
    prev = a.find_previous(lambda t: isinstance(t, Tag) and (
        t.name in ("h3", "h4", "h5", "h6") or any("rubro" in c.lower() for c in t.get("class") or [])))
    return clean(prev.get_text(" "))[:120] or None if prev is not None else None


def parse_bo_section(content: bytes | str, *, require: bool = True, url: str | None = None) -> list[BoAviso]:
    """Notices (avisos) listed on a Boletín Oficial first-section page.

    With ``require``, raises ``SchemaDrift`` when there is none: the latest edition always has
    notices, so an empty list means the layout changed. `url` (the page read) is named in the error."""
    soup = _soup(content)
    out: dict[str, BoAviso] = {}
    for a in soup.find_all("a", href=True):
        m = _BO_AVISO_RE.search(a["href"])
        if not m:
            continue
        aviso_id, ymd = m.groups()
        try:
            pub = date(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:]))
        except ValueError:
            continue
        lines = [clean(p.get_text(" ")) for p in a.find_all(["p", "h3", "h4", "h5", "span", "div"], recursive=True)
                 if p.find(["p", "h3", "h4", "h5", "div"]) is None]
        lines = [x for x in dict.fromkeys(lines) if x] or [clean(s) for s in a.stripped_strings if clean(s)]
        if aviso_id not in out:
            out[aviso_id] = BoAviso(aviso_id=aviso_id, pub_date=pub, lines=lines[:6], rubro=_bo_rubro(a))
    if require and not out:
        raise SchemaDrift(f"Boletín Oficial: no notice link (/detalleAviso/primera/<id>/<yyyymmdd>) on the section "
                          f"page {url or ''} (page title {_page_title(soup)!r}); the layout has changed")
    return list(out.values())


_BO_BODY_SELECTORS = ("#cuerpoDetalleAviso", "#detalleAviso", ".cuerpo-aviso", "#contenidoAviso")


def parse_bo_detail(content: bytes | str) -> tuple[str, bool]:
    """(text of the notice, True when found in a known notice container)."""
    soup = _soup(content)
    for sel in _BO_BODY_SELECTORS:
        el = soup.select_one(sel)
        if el is not None and clean(el.get_text(" ")):
            return clean(el.get_text(" ")), True
    for t in soup(["nav", "footer", "header"]):
        t.decompose()
    return parse_article(str(soup), "es").text, False


def bo_catchup_days(last_read: date | None, latest: date, max_days: int = BO_CATCHUP_DAYS) -> list[date]:
    """Business days strictly between the last edition read and the latest one (most recent
    `max_days`), oldest first. None before the first run: there is no back-fill."""
    if last_read is None or last_read >= latest:
        return []
    days: list[date] = []
    d = latest - timedelta(days=1)
    while d > last_read and len(days) < max_days:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return sorted(days)


class ArSenasaHoneyCollector(Collector):
    key = "ar_senasa_honey"
    name = "SENASA Argentina: residui (Lista EAR), export e Boletín Oficial sul miele"
    name_en = "SENASA Argentina: residues (EAR list), exports and Official Gazette notices on honey"
    publisher = ("SENASA (Servicio Nacional de Sanidad y Calidad Agroalimentaria); Secretaría de Agricultura, "
                 "Ganadería y Pesca; Boletín Oficial de la República Argentina")
    homepage = "https://www.argentina.gob.ar/senasa"
    kind = SourceKind.HTML
    reliability = Reliability.OFFICIAL
    category = "regulation"
    country_iso3 = "ARG"
    language = "es"
    expected_update = "Controllo giornaliero (Lista EAR settimanale); gli avvisi sul miele sono occasionali"
    expected_update_en = "Daily check (EAR residue lists weekly); honey notices are event-driven"
    expected_max_age_days = 120
    terms_note = (
        "Argentine government content (argentina.gob.ar, Boletín Oficial): public information, reuse with "
        "attribution. PAGE WATCHER: it reads the SENASA news listing, the Plan CREHA page (Lista EAR PDFs) and "
        "the Boletín Oficial first section as HTML. The SENASA listing URL and the Boletín Oficial catch-up URL "
        "are unverified, and every layout was reconstructed without live access, so it may need adjustment; a "
        "run fails with a clear message when the expected structure is not found. Texts are kept verbatim in "
        "Spanish (never machine-translated)."
    )
    # The Boletín Oficial is out early in the Argentine morning: 13:25 in Italy reads the same day's edition.
    schedule = {"trigger": "cron", "hour": 13, "minute": 25}

    def collect(self, ctx: CollectContext) -> None:
        _polite(ctx)
        state = _get_state(ctx.session, self.key)
        runner = _FeedRunner(ctx)

        def wrap(fn: Callable[[], None]) -> Callable[[], None]:
            def inner() -> None:
                fn()
                _set_state(ctx.session, self.key, state)
            return inner

        runner.run(SENASA_NEWS.label, wrap(lambda: run_news_feed(ctx, SENASA_NEWS, state)))
        runner.run("SENASA Plan CREHA (Lista EAR)", wrap(lambda: self._ear(ctx, state)))
        runner.run("Boletín Oficial (primera sección)", wrap(lambda: self._boletin(ctx, state)))
        runner.finish()

    # ------------------------------------------------------------- Lista EAR
    def _ear(self, ctx: CollectContext, state: dict) -> None:
        t = today()
        last = _iso_date(state.get("ear_checked"))
        if not ctx.force and last is not None and 0 <= (t - last).days < EAR_CHECK_DAYS:
            return
        doc = ctx.fetch(SENASA_CREHA_URL, headers=HTML_HEADERS, title="SENASA Plan CREHA")
        links, pdf_count = find_ear_links(doc.content, doc.url)
        if pdf_count == 0:
            raise SchemaDrift(f"SENASA Plan CREHA page ({doc.url}): no PDF link at all; the page moved or its "
                              f"layout changed")
        if not links:
            ctx.warn(f"SENASA Plan CREHA page: {pdf_count} PDF link(s) but none is a 'Lista EAR'; the lists may "
                     f"have moved to another page")
        known = _known_refs(ctx)
        files: dict[str, str] = dict(state.get("ear_files") or {})
        budget = EAR_MAX_PDFS
        complete = True
        for link in links:
            if link.reference in known or files.get(link.url) == "no_honey":
                continue
            if budget <= 0:
                complete = False
                break
            budget -= 1
            try:
                pdoc = ctx.fetch(link.url, headers=PDF_HEADERS, title=link.title, published_at=link.listed_date)
            except Offline:
                raise
            except CollectorError as exc:
                ctx.warn(f"SENASA Lista EAR {link.url} could not be downloaded ({exc}); retried next run")
                complete = False
                continue
            ear = parse_ear_pdf(pdoc.content)
            if ear.text_ok and not ear.honey_rows:
                files[link.url] = "no_honey"
                continue
            if not ear.text_ok:
                ctx.warn(f"SENASA Lista EAR {link.url}: no text could be read (scanned PDF?); stored unchecked")
            elif ear.list_date is None and link.listed_date is None:
                ctx.warn(f"SENASA Lista EAR {link.url}: no list date printed on the page or in the PDF header; "
                         f"stored without a publication date")
            if ear.list_year and link.year and ear.list_year != link.year or (
                    ear.list_number and link.number and ear.list_number != link.number):
                ctx.warn(f"SENASA Lista EAR {link.url}: the PDF title {ear.title!r} does not match the link "
                         f"{link.text!r} (number/year from the link kept)")
            _store(
                ctx, reference=link.reference, jurisdiction="AR", iso3="ARG", doc_type="residue_alert",
                title=link.title, url=link.url, published_at=ear.list_date or link.listed_date,
                extra={
                    "feed": "creha_ear", "publisher": SENASA_PUBLISHER, "language": "es", "watcher": "html_page",
                    "listing_url": SENASA_CREHA_URL, "pdf_url": link.url, "list_number": link.number,
                    "list_year": link.year, "list_kind": link.kind, "pdf_title": ear.title,
                    "date_source": "pdf_header" if ear.list_date else ("listing" if link.listed_date else None),
                    "honey_rows": ear.honey_rows[:50],
                    "honey_row_count": len(ear.honey_rows) if ear.text_ok else None,
                    "honey_mentioned": True if ear.text_ok else None,
                    "note": None if ear.text_ok else "PDF text could not be read; open the official list",
                    "raw_document_id": pdoc.raw_document_id or None, "topics": ["residues"],
                },
            )
            known.add(link.reference)        # a second rendering of the same list is not downloaded
            files[link.url] = "stored"
        if complete:
            state["ear_checked"] = t.isoformat()
        state["ear_files"] = dict(list(files.items())[-500:])

    # ------------------------------------------------------- Boletín Oficial
    def _boletin(self, ctx: CollectContext, state: dict) -> None:
        doc = ctx.fetch(BO_LATEST_URL, headers=HTML_HEADERS, title="Boletín Oficial, primera sección (latest edition)")
        avisos = parse_bo_section(doc.content, url=doc.url)           # SchemaDrift propagates
        latest = max(a.pub_date for a in avisos)
        last_read = _iso_date(state.get("bo_last_edition"))
        listed = list(avisos)
        days = bo_catchup_days(last_read, latest)
        failed = 0
        for d in days:
            url = BO_DATED_URL.format(ymd=f"{d:%Y%m%d}")
            try:
                ddoc = ctx.fetch(url, headers=HTML_HEADERS, accept_status=(200, 404),
                                 title=f"Boletín Oficial, primera sección {d.isoformat()}")
            except Offline:
                raise
            except CollectorError as exc:
                ctx.warn(f"Boletín Oficial catch-up {d.isoformat()} failed ({exc})")
                failed += 1
                continue
            day_avisos = [a for a in parse_bo_section(ddoc.content, require=False) if a.pub_date == d] \
                if ddoc.status_code == 200 else []
            if not day_avisos:
                failed += 1              # a holiday, or the dated URL pattern (unverified) is wrong
            listed += day_avisos
        if len(days) >= 2 and failed == len(days):
            ctx.warn(f"Boletín Oficial: none of the {len(days)} missed editions could be read from "
                     f"{BO_DATED_URL.format(ymd='<yyyymmdd>')} (unverified URL pattern); those days were skipped")

        known = _known_refs(ctx)
        rejected: list[str] = [str(x) for x in state.get("bo_rejected") or []]
        rejected_set = set(rejected)
        queue: dict[str, BoAviso] = {}
        for d in state.get("bo_pending") or []:
            a = BoAviso.from_state(d)
            if a is not None:
                queue[a.aviso_id] = a
        for a in listed:
            if _BO_PREFILTER_RE.search(fold(" ".join(a.lines + [a.rubro or ""]))):
                queue.setdefault(a.aviso_id, a)
        pending: list[BoAviso] = []
        budget = BO_MAX_DETAILS
        for a in queue.values():
            if a.reference in known or a.aviso_id in rejected_set:
                continue
            if budget <= 0:
                pending.append(a)
                continue
            budget -= 1
            try:
                ddoc = ctx.fetch(a.url, headers=HTML_HEADERS, title=a.title[:300], published_at=a.pub_date)
            except Offline:
                raise
            except CollectorError as exc:
                a.attempts += 1
                if a.attempts < MAX_PDF_ATTEMPTS:
                    pending.append(a)
                ctx.warn(f"Boletín Oficial notice {a.url} could not be read ({exc})")
                continue
            text, in_container = parse_bo_detail(ddoc.content)
            if not in_container:
                ctx.warn(f"Boletín Oficial notice {a.url}: notice body container not found; read the page text")
            kws = HONEY_ES.matches(" ".join(a.lines), text)
            if not kws:
                rejected.append(a.aviso_id)
                rejected_set.add(a.aviso_id)
                continue
            topics = topics_of(f"{a.title} {text[:6000]}", "es")
            normative = bool(_NORMATIVE_ES_RE.search(fold(a.norm or a.title)))
            _store(
                ctx, reference=a.reference, jurisdiction="AR", iso3="ARG",
                doc_type=doc_type_for(topics, normative=normative), title=a.title, url=a.url,
                published_at=a.pub_date, status="published",
                extra={
                    "feed": "boletin_oficial", "publisher": BO_PUBLISHER, "language": "es", "watcher": "html_page",
                    "organism": a.organism, "norm": a.norm, "gde_number": a.gde, "rubro": a.rubro,
                    "excerpt_original": sentences_with(text, HONEY_ES), "keywords": kws, "topics": topics,
                    "raw_document_id": ddoc.raw_document_id or None,
                },
            )
        if len(pending) > BO_PENDING_MAX:
            ctx.warn(f"Boletín Oficial: {len(pending) - BO_PENDING_MAX} notice(s) to check were dropped (backlog full)")
        state["bo_pending"] = [a.to_state() for a in pending[:BO_PENDING_MAX]]
        state["bo_rejected"] = rejected[-BO_REJECTED_MAX:]
        state["bo_last_edition"] = max(latest, last_read).isoformat() if last_read else latest.isoformat()


# ===========================================================================
# 3) India: DGFT notifications (minimum export price on natural honey)
# ===========================================================================

DGFT_LIST_URL = "https://www.dgft.gov.in/CP/?opt=notification"          # "REMEMBERED" in research
DGFT_PUBLISHER = "Directorate General of Foreign Trade (DGFT), Ministry of Commerce & Industry, Government of India"
DGFT_MAX_PDFS = 10
# Notification numbers as the real list prints them (checked live, Nov 2026):
#   "nn/yyyy-yy", "nn/yyyy.yy" (in a corrigendum)   -> number / financial year
#   "nn/2023"                                       -> Foreign Trade Policy 2023 series (FY 2023-24)
#   "nn" with Year "yyyy-yy" (or "yyyy")            -> bare number; the year is in the Year column
_NOTIF_NO_RE = re.compile(r"\b(\d{1,3})\s*/\s*(20\d{2})\s*[-–.]\s*(\d{2}|20\d{2})\b")
_NOTIF_FTP_RE = re.compile(r"\b(\d{1,3})\s*/\s*(20\d{2})\b(?!\s*[-–.]\s*\d)")
_BARE_NO_RE = re.compile(r"^\s*(?:no\.?\s*)?(\d{1,3})\s*$", re.I)
_FY_RE = re.compile(r"^\s*(20\d{2})\s*[-–]\s*(\d{2}|20\d{2})\s*$")
_YEAR_ONLY_RE = re.compile(r"^\s*(20\d{2})\s*$")
_CORRIGENDUM_RE = re.compile(r"\bcorrigendum\b", re.I)
_DGFT_HEADER_SYNONYMS: dict[str, tuple[str, ...]] = {
    "number": ("notification no", "notification number", "notification", "number", "no.", "no"),
    "description": ("description", "subject", "title", "details", "particulars"),
    "date": ("date", "dated", "notification date", "issue date"),
    "year": ("year",),
    "attachment": ("attachment", "download", "file", "pdf", "view", "link", "document"),
}


@dataclass
class DgftNotification:
    number: str | None                   # normalised "nn/yyyy-yy" or "nn/yyyy" (two-digit number at least)
    number_raw: str
    description: str
    notified_on: date | None
    year: str | None
    pdf_url: str | None
    corrigendum: bool = False            # a corrigendum TO notification `number`, not the notification

    @property
    def reference(self) -> str:
        if self.number and self.corrigendum:
            on = f" of {self.notified_on:%d.%m.%Y}" if self.notified_on else ""
            return f"DGFT Corrigendum{on} to Notification No. {self.number}"
        if self.number:
            return f"DGFT Notification No. {self.number}"
        ident = self.pdf_url or f"{self.description}|{self.notified_on}"
        return f"DGFT Notification {hashlib.sha1(ident.encode()).hexdigest()[:16]}"


def normalise_notification_number(text: str, year: str | None = None) -> str | None:
    """"nn/yyyy-yy" (financial-year series) or "nn/yyyy" (the FTP 2023 series), as printed.

    A bare number ("7") takes its year from the list's Year column (`year`): "2026-27" gives
    "07/2026-27", "2023" gives "07/2023". Anything else gives None."""
    t = clean(text)
    m = _NOTIF_NO_RE.search(t)
    if m:
        return f"{int(m[1]):02d}/{m[2]}-{m[3][-2:]}"
    m = _NOTIF_FTP_RE.search(t)
    if m:
        return f"{int(m[1]):02d}/{m[2]}"
    m = _BARE_NO_RE.match(t)
    if m and year:
        fy = _FY_RE.match(clean(year))
        if fy:
            return f"{int(m[1]):02d}/{fy[1]}-{fy[2][-2:]}"
        y = _YEAR_ONLY_RE.match(clean(year))
        if y:
            return f"{int(m[1]):02d}/{y[1]}"
    return None


def _header_map(cells: list[str]) -> dict[str, int]:
    found: dict[str, int] = {}
    for i, raw in enumerate(cells):
        h = fold(raw).strip(" :")
        for col, names in _DGFT_HEADER_SYNONYMS.items():
            if col in found:
                continue
            if any(h == n or (len(n) > 3 and n in h) for n in names):
                if col == "number" and "date" in h:
                    continue
                found[col] = i
                break
    return found


def _row_pdf(row: Tag, base: str) -> str | None:
    for a in row.find_all("a", href=True):
        u = canonical_url(a["href"], base)
        if u and (urlsplit(u).path.lower().endswith(".pdf") or "content.dgft" in u or "download" in u.lower()):
            return u
    return None


def parse_dgft_notifications(content: bytes | str, page_url: str) -> tuple[list[DgftNotification], list[str]]:
    """Rows of the DGFT notifications table.

    The table is the one whose header names a number, a description and a date column (synonyms in
    ``_DGFT_HEADER_SYNONYMS``; the live page has "Sl.No., Number, Year, Description, Date, CRT DT,
    Attachment"). Without such a header, rows are read by content instead: a cell shaped like
    "nn/yyyy-yy", a date cell, and the longest cell as description. Raises ``SchemaDrift`` when no
    row has a notification number, or none has a date. Problems are reported for honey rows only."""
    soup = _soup(content)
    problems: list[str] = []
    out: list[DgftNotification] = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header_row = next((r for r in rows if r.find("th") is not None), None)
        cols = _header_map([clean(c.get_text(" ")) for c in header_row.find_all(["th", "td"])]) if header_row else {}
        mapped = {"number", "description", "date"} <= set(cols)
        for r in rows:
            if r is header_row:
                continue
            cells = r.find_all("td")
            if not cells:
                continue
            texts = [clean(c.get_text(" ")) for c in cells]
            if mapped and len(texts) > max(cols["number"], cols["description"], cols["date"]):
                number_raw = texts[cols["number"]]
                description = texts[cols["description"]]
                notified = parse_local_date(texts[cols["date"]], "en")
                year = texts[cols["year"]] if "year" in cols and cols["year"] < len(texts) else None
            else:
                number_idx = next((i for i, x in enumerate(texts) if _NOTIF_NO_RE.fullmatch(x.replace("No.", "").strip())
                                   or (_NOTIF_NO_RE.search(x) and len(x) <= 30)), None)
                if number_idx is None:
                    continue
                number_raw = texts[number_idx]
                date_idx = next((i for i, x in enumerate(texts) if i != number_idx and len(x) <= 40
                                 and parse_local_date(x, "en")), None)
                notified = parse_local_date(texts[date_idx], "en") if date_idx is not None else None
                description = max((x for i, x in enumerate(texts) if i not in (number_idx, date_idx)), key=len, default="")
                year = None
            if not description and not number_raw:
                continue
            out.append(DgftNotification(
                number=normalise_notification_number(number_raw, year), number_raw=number_raw,
                description=description, notified_on=notified, year=clean(year) or None, pdf_url=_row_pdf(r, page_url),
                corrigendum=bool(_CORRIGENDUM_RE.search(number_raw)),
            ))
    if not out:
        raise SchemaDrift(f"DGFT notifications: no table row found on {page_url} (page title "
                          f"{_page_title(soup)!r}); the page layout or URL has changed")
    if not any(n.number for n in out):
        raise SchemaDrift(f"DGFT notifications: {len(out)} rows but none with a notification number like "
                          f"'nn/yyyy-yy'; the table columns have changed")
    if not any(n.notified_on for n in out):
        raise SchemaDrift(f"DGFT notifications: {len(out)} rows but none with a readable date; the date "
                          f"column or its format has changed")
    for n in out:
        # Only honey rows matter; an odd number on another product's row is not worth a warning.
        if n.number is None and dgft_is_honey(n):
            problems.append(f"DGFT row {n.number_raw!r} (year {n.year!r}): notification number not recognised")
    return out, problems


def dgft_is_honey(n: DgftNotification) -> bool:
    return bool(HONEY_EN.matches(n.description))


# Minimum export price: "US$ 1,234 per MT", "USD 1234/MT", "US $ 2345 per metric tonne" (or per kg),
# and the real DGFT wordings "US $ <n> per Metric Ton (PMT)", "US$ <n> F.O.B per Metric Ton",
# "US Dollar <n> FOB per Metric Ton".
_FOB = r"F\.?\s?O\.?\s?B\b\.?"


def _money_re(suffix: str = "") -> str:
    return (rf"(?:US\s?\$|USD|US\s?dollars?|U\.S\.\s?\$)\s*(?P<val{suffix}>[0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:/-)?\s*"
            rf"(?:{_FOB}\s*)?"
            rf"(?:/|per|a)\s*(?P<unit{suffix}>M\.?T\.?|metric\s+tonnes?|metric\s+tons?|tonnes?|tons?|kgs?|kilograms?)(?![a-z])")


_MEP_VALUE_RE = re.compile(_money_re(), re.I)
_MEP_FROM_TO_RE = re.compile(r"\bfrom\s+" + _money_re("1") + r"[^.;]{0,60}?\bto\s+" + _money_re("2"), re.I)
_DATE_EN = (r"(?:\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?[A-Za-z]{3,9}\.?,?\s+\d{4}|\d{1,2}[./-]\d{1,2}[./-]\d{4}"
            r"|[A-Za-z]{3,9}\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})")
_UNTIL = r"(?:till|until|up\s*to|upto)"
_VALID_RE = re.compile(rf"\b{_UNTIL}\s+(?:the\s+)?(?P<d>{_DATE_EN})", re.I)
_EXTENDED_RE = re.compile(rf"\bextend(?:ed|s|ing)?\b[^.;]{{0,220}}?\b{_UNTIL}\s+(?:the\s+)?(?P<d>{_DATE_EN})", re.I)
_EFFECT_FROM_RE = re.compile(rf"\bwith\s+effect\s+from\s+(?:the\s+)?(?P<d>{_DATE_EN})"
                             rf"|\bcomes?\s+into\s+force\s+(?:on|from)\s+(?:the\s+)?(?P<d2>{_DATE_EN})"
                             rf"|\bw\.\s?e\.\s?f\.?\s*(?:the\s+)?(?P<d3>{_DATE_EN})", re.I)
_IMMEDIATE_RE = re.compile(r"\b(?:with|into)\s+immediate\s+effect\b", re.I)   # "come into immediate effect" too
_FOB_RE = re.compile(rf"\b{_FOB}")
_AMOUNT_FOB_RE = re.compile(rf"(?<![\d.,])(\d[\d,]*(?:\.\d+)?)\s*{_FOB}")
# The operative paragraph that closes every DGFT notification ("2. Effect of this Notification:
# ..."). It states the outcome in prose, outside the "Existing / Revised policy condition" table.
_EFFECT_SECTION_RE = re.compile(r"\beffect\s+of\s+this\s+notification\b\s*:?", re.I)
_SECTION_END_RE = re.compile(r"\(\s*issued\s+from\b|\bdirector\s+general\s+of\s+foreign\s+trade\b", re.I)
_EN_MONTH_NAMES = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
# OCR of a superscript ordinal: "31st" read as "31*", "31%", "31‘'", "31" + "8", "5!", "54", "8t" ...
# Only a one- or two-digit day directly followed by such noise and a month name is rewritten.
_OCR_ORDINAL_RE = re.compile(rf"(?<![\w.,/])(?P<d>[0-3]?\d)(?P<junk>[^\s]{{1,4}}?)\s*(?={_EN_MONTH_NAMES}\b)")


def normalise_ocr_ordinals(text: str) -> str:
    """'till 318' December' -> 'till 31 December' (OCR text only). A day that is not
    1-31 ("34St March") is left as it is, so that date is simply not read."""
    def fix(m: re.Match[str]) -> str:
        day = int(m["d"])
        junk = m["junk"]
        if not 1 <= day <= 31 or re.fullmatch(r"(?:st|nd|rd|th)", junk, re.I):
            return m.group(0)
        if len(m["d"]) == 1 and junk[0].isdigit():      # "31 December" is not day 3 + noise "1"
            return m.group(0)
        if junk.isalpha() and junk.lower() not in {"s", "st", "sq", "t"}:
            return m.group(0)
        return f"{day} "
    return _OCR_ORDINAL_RE.sub(fix, text)


def _per_tonne(value: str, unit: str) -> float | None:
    try:
        v = float(value.replace(",", ""))
    except ValueError:
        return None
    return round(v * 1000, 4) if unit.lower().startswith(("kg", "kilogram")) else v


@dataclass
class MepTerms:
    mep_usd_per_t: float | None = None
    mep_values_found: list[float] = field(default_factory=list)
    valid_until: date | None = None
    validity_dates_found: list[date] = field(default_factory=list)
    effective_date: date | None = None
    effective_basis: str | None = None
    basis: str | None = None             # "FOB" when the text says so next to the price
    excerpt: str | None = None
    problems: list[str] = field(default_factory=list)


def _mep_values(t: str) -> list[float]:
    values: list[float] = []
    for m in _MEP_VALUE_RE.finditer(t):
        v = _per_tonne(m["val"], m["unit"])
        if v is not None and v not in values:
            values.append(v)
    return values


def _resolve_mep(t: str, values: list[float]) -> tuple[float | None, str | None]:
    """(MEP, problem): the single amount, else the new one of a "from X ... to Y" phrase."""
    if len(values) == 1:
        return values[0], None
    if len(values) > 1:
        changes = {_per_tonne(m["val2"], m["unit2"]) for m in _MEP_FROM_TO_RE.finditer(t)} - {None}
        if len(changes) == 1:
            return changes.pop(), None
        return None, f"several minimum export prices in the text ({values}); none stored"
    return None, None


def _validity_dates(t: str) -> list[date]:
    out: list[date] = []
    for m in _VALID_RE.finditer(t):
        d = parse_local_date(m["d"], "en")
        if d and d not in out:
            out.append(d)
    return out


def _resolve_validity(t: str) -> tuple[date | None, str | None]:
    """(validity end, problem): the date after "extended ... till", else the single "till" date."""
    extended = {d for m in _EXTENDED_RE.finditer(t) if (d := parse_local_date(m["d"], "en"))}
    if len(extended) == 1:
        return next(iter(extended)), None
    if len(extended) > 1:
        return None, f"several 'extended till' dates ({sorted(extended)}); validity not stored"
    found = _validity_dates(t)
    if len(found) == 1:
        return found[0], None
    if len(found) > 1:
        return None, f"several validity dates ({found}); validity not stored"
    return None, None


def effect_section(text: str) -> str | None:
    """The "Effect of this Notification" paragraph (up to the signature), or None."""
    m = _EFFECT_SECTION_RE.search(text)
    if not m:
        return None
    rest = text[m.end():]
    end = _SECTION_END_RE.search(rest)
    return (rest[: end.start()] if end else rest).strip() or None


def parse_mep_terms(text: str, notified_on: date | None, *, ocr: bool = False) -> MepTerms:
    """Minimum export price, validity end and effective date from the text of a DGFT notification.

    Only what the text states unambiguously is returned:
    * MEP: the single US$ amount per tonne (or per kg, converted); if several, the new one of a
      "from US$ X ... to US$ Y" phrase; otherwise None, with the candidates listed.
    * validity end: the date after "extended ... till/up to"; otherwise the single date after
      "till/until/up to"; otherwise None, with the candidates listed.
    * effective date: "with effect from <date>" / "w.e.f. <date>" / "comes into force on <date>";
      "with immediate effect" / "come into immediate effect" means the notification date
      (``effective_basis`` says which).
    The MEP and the validity are read first from the closing "Effect of this Notification"
    paragraph, which states the outcome; real amendments also print the superseded condition
    ("Existing Policy condition ... till <old date>") in a table. The whole text is the
    fallback. `ocr` marks OCR text: superscript ordinals misread by OCR are normalised first."""
    t = clean(normalise_ocr_ordinals(text) if ocr else text)
    terms = MepTerms()
    if not t:
        return terms
    values = _mep_values(t)
    terms.mep_values_found = values
    effect = effect_section(t)
    mep, problem = _resolve_mep(effect, _mep_values(effect)) if effect else (None, None)
    if mep is None:
        mep, problem = _resolve_mep(t, values)
    terms.mep_usd_per_t = mep
    if problem:
        terms.problems.append(problem)
    # FOB: written next to a price ("US$ 1,111 per MT FOB"), or right after the amount of the
    # MEP ("US Dollar <n> FOB per Metric Ton" in a table cell whose currency OCR split off).
    fob = any(_FOB_RE.search(t[max(0, m.start() - 150): m.end() + 150]) for m in _MEP_VALUE_RE.finditer(t))
    fob = fob or (mep is not None and mep in {float(x.replace(",", "")) for x in _AMOUNT_FOB_RE.findall(t)})
    terms.basis = "FOB" if fob and values else None

    terms.validity_dates_found = _validity_dates(t)
    until, problem = _resolve_validity(effect) if effect else (None, None)
    if until is None:
        until, problem = _resolve_validity(t)
    terms.valid_until = until
    if problem:
        terms.problems.append(problem)

    effective = {d for m in _EFFECT_FROM_RE.finditer(t)
                 if (d := parse_local_date(m["d"] or m["d2"] or m["d3"], "en"))}
    if len(effective) == 1:
        terms.effective_date = next(iter(effective))
        terms.effective_basis = "with effect from"
    elif len(effective) > 1:
        terms.problems.append(f"several effective dates ({sorted(effective)}); effective date not stored")
    elif _IMMEDIATE_RE.search(t) and notified_on is not None:
        terms.effective_date = notified_on
        terms.effective_basis = "with immediate effect (notification date)"

    terms.excerpt = sentences_with(t, KeywordSet("mep", (
        ("mep", re.compile(r"\bminimum export price\b|\bmep\b")),
        ("honey", re.compile(r"\bhoney\b(?![\s-]*bees?\b)")),
    )), max_n=2)
    return terms


def merge_ocr_terms(a: MepTerms, b: MepTerms) -> MepTerms:
    """Terms read from two independent OCR passes (two resolutions) of the same scan. A value is
    kept only when both readings give it; a disagreement leaves it empty, with a problem that
    names both readings. The candidate lists and the excerpt are those of the first reading."""
    out = MepTerms(mep_values_found=a.mep_values_found, validity_dates_found=a.validity_dates_found,
                   excerpt=a.excerpt, problems=list(a.problems))
    for name, label in (("mep_usd_per_t", "minimum export price"), ("valid_until", "validity end"),
                        ("effective_date", "effective date"), ("basis", "price basis")):
        va, vb = getattr(a, name), getattr(b, name)
        if va == vb:
            setattr(out, name, va)
        else:
            out.problems.append(f"OCR readings disagree on the {label} ({va!r} vs {vb!r}); not stored")
    out.effective_basis = a.effective_basis if out.effective_date is not None else None
    return out


class InDgftHoneyCollector(Collector):
    key = "in_dgft_honey"
    name = "DGFT India: prezzo minimo all'export (MEP) e regole export sul miele"
    name_en = "DGFT India: minimum export price (MEP) and export rules for honey"
    publisher = DGFT_PUBLISHER
    homepage = "https://www.dgft.gov.in/"
    kind = SourceKind.HTML
    reliability = Reliability.OFFICIAL
    category = "regulation"
    country_iso3 = "IND"
    language = "en"
    expected_update = "Controllo giornaliero; le notifiche sul miele escono a intervalli irregolari, spesso a fine trimestre"
    expected_update_en = "Daily check; honey notifications are irregular, often near a quarter end"
    # MEP notices have come 3 to 9 months apart; a year without one deserves a look at the run log.
    expected_max_age_days = 300
    terms_note = (
        "Government of India content (DGFT notifications, Gazette of India): public information. PAGE WATCHER: it "
        "reads the DGFT notifications list as HTML (table layout checked live in Nov 2026) and the notification "
        "PDFs; it may need adjustment, and a run fails with a clear message when the table is not found. The MEP "
        "notifications are scanned pages without a text layer: their minimum export price, validity and effective "
        "date are read by OCR (Tesseract, optional) at two resolutions and stored only when both readings agree "
        "(extra.terms_text_source = 'ocr'); without Tesseract they are left empty. Values are left empty when the "
        "text is ambiguous or unreadable. The official notification is authoritative."
    )
    schedule = {"trigger": "cron", "hour": 7, "minute": 5}

    def collect(self, ctx: CollectContext) -> None:
        _polite(ctx)
        state = _get_state(ctx.session, self.key)
        doc = ctx.fetch(DGFT_LIST_URL, headers=HTML_HEADERS, title="DGFT notifications")
        rows, problems = parse_dgft_notifications(doc.content, doc.url)     # SchemaDrift: run fails
        for p in problems[:10]:
            ctx.warn(p)
        honey = sorted((n for n in rows if dgft_is_honey(n)), key=lambda n: n.notified_on or date.min)
        known = _known_refs(ctx)
        attempts: dict[str, int] = {k: int(v) for k, v in (state.get("pdf_attempts") or {}).items()}
        budget = DGFT_MAX_PDFS
        postponed = 0
        for n in honey:
            ref = n.reference
            if ref in known:
                ctx.counters.count("unchanged")
                continue
            known.add(ref)
            pdf: FetchResult | None = None
            pdf_error: str | None = None
            if n.pdf_url:
                if budget <= 0:
                    postponed += 1
                    continue
                budget -= 1
                try:
                    pdf = ctx.fetch(n.pdf_url, headers=PDF_HEADERS, title=f"DGFT Notification {n.number_raw}",
                                    published_at=n.notified_on)
                except CollectorError as exc:         # Offline included: the PDF host may differ
                    pdf_error = str(exc)
                if pdf is not None and not pdf.content.lstrip()[:5].startswith(b"%PDF"):
                    pdf_error, pdf = f"not a PDF (starts with {_snippet(pdf.content, 60)!r})", None
                if pdf is None:
                    attempts[ref] = attempts.get(ref, 0) + 1
                    if attempts[ref] < MAX_PDF_ATTEMPTS:
                        ctx.warn(f"DGFT Notification {n.number_raw}: PDF not available ({pdf_error}); "
                                 f"retried next run ({attempts[ref]}/{MAX_PDF_ATTEMPTS})")
                        continue
                    ctx.warn(f"DGFT Notification {n.number_raw}: PDF still not available after "
                             f"{MAX_PDF_ATTEMPTS} runs ({pdf_error}); stored without its terms")
            self._store(ctx, n, pdf, pdf_error)
            attempts.pop(ref, None)
        if postponed:
            ctx.warn(f"DGFT: {postponed} honey notification PDF(s) postponed to the next run "
                     f"(at most {DGFT_MAX_PDFS} per run)")
        state["pdf_attempts"] = attempts
        state["list_checked"] = today().isoformat()
        _set_state(ctx.session, self.key, state)

    def _read_terms(self, ctx: CollectContext, n: DgftNotification, pdf: FetchResult) -> tuple[str, MepTerms, str | None]:
        """(text, terms, text source) of a notification PDF. Source "pdf_text" (text layer),
        "ocr" (scanned page read by Tesseract at two resolutions) or None (nothing readable)."""
        text = pdf_text(pdf.content)
        if text.strip():
            return text, parse_mep_terms(text, n.notified_on), "pdf_text"
        if not ocr.available():
            ctx.warn(f"DGFT Notification {n.number_raw}: the PDF is a scanned image without a text layer and OCR "
                     f"is not installed (install Tesseract, see paladex/services/ocr.py); MEP terms not read")
            return "", MepTerms(), None
        try:
            first = ocr.ocr_pdf(pdf.content, dpi=ocr.DEFAULT_DPI)
            second = ocr.ocr_pdf(pdf.content, dpi=ocr.SECOND_DPI)
        except ocr.OcrError as exc:
            ctx.warn(f"DGFT Notification {n.number_raw}: scanned PDF, OCR failed ({exc}); MEP terms not read")
            return "", MepTerms(), None
        a = parse_mep_terms(first, n.notified_on, ocr=True)
        b = parse_mep_terms(second, n.notified_on, ocr=True)
        return first, merge_ocr_terms(a, b), "ocr"

    def _store(self, ctx: CollectContext, n: DgftNotification, pdf: FetchResult | None, pdf_error: str | None) -> None:
        text, terms, source = self._read_terms(ctx, n, pdf) if pdf is not None else ("", MepTerms(), None)
        if pdf is not None and source == "pdf_text" and len(clean(text)) < 40:
            ctx.warn(f"DGFT Notification {n.number_raw}: almost no text in the PDF; MEP terms may be missing")
        for p in terms.problems:
            ctx.warn(f"DGFT Notification {n.number_raw}: {p}")
        topics = topics_of(f"{n.description} {text[:6000]}", "en")
        is_mep = "mep" in topics_of(n.description, "en") or terms.mep_usd_per_t is not None
        doc_type = "price_floor" if is_mep else doc_type_for([x for x in topics if x != "mep"], normative=True)
        _store(
            ctx, reference=n.reference, jurisdiction="IN", iso3="IND", doc_type=doc_type,
            title=n.description or f"DGFT Notification No. {n.number_raw}", url=n.pdf_url or DGFT_LIST_URL,
            published_at=n.notified_on, effective_date=terms.effective_date, status="published",
            # summary_en is official text verbatim: OCR text is not, so it goes to extra only.
            summary_en=terms.excerpt if source == "pdf_text" else None,
            extra={
                "feed": "dgft_notifications", "publisher": DGFT_PUBLISHER, "language": "en", "watcher": "html_page",
                "listing_url": DGFT_LIST_URL, "notification_number": n.number or n.number_raw, "year": n.year,
                "corrigendum": n.corrigendum or None,
                "pdf_url": n.pdf_url, "raw_document_id": pdf.raw_document_id if pdf is not None else None,
                "mep_usd_per_t": terms.mep_usd_per_t, "mep_currency": "USD" if terms.mep_usd_per_t else None,
                "mep_unit": "t" if terms.mep_usd_per_t else None, "mep_basis": terms.basis,
                "valid_until": terms.valid_until.isoformat() if terms.valid_until else None,
                "effective_basis": terms.effective_basis,
                "mep_values_found": terms.mep_values_found if len(terms.mep_values_found) > 1 else None,
                "validity_dates_found": [d.isoformat() for d in terms.validity_dates_found]
                if len(terms.validity_dates_found) > 1 else None,
                "terms_parsed": source is not None, "terms_text_source": source,
                "ocr_engine": ocr.engine_version() if source == "ocr" else None,
                "ocr_dpi": [ocr.DEFAULT_DPI, ocr.SECOND_DPI] if source == "ocr" else None,
                "ocr_excerpt": terms.excerpt if source == "ocr" else None,
                "pdf_error": pdf_error if pdf is None else None, "topics": topics,
            },
        )


__all__ = [
    "BO_DATED_URL",
    "BO_LATEST_URL",
    "DGFT_LIST_URL",
    "DOU_QUERIES",
    "DOU_SEARCH_URL",
    "HONEY_EN",
    "HONEY_ES",
    "HONEY_PT",
    "MAPA_NEWS_URL",
    "SENASA_CREHA_URL",
    "SENASA_NEWS_URL",
    "ArSenasaHoneyCollector",
    "BrMapaHoneyCollector",
    "InDgftHoneyCollector",
    "SchemaDrift",
    "bo_catchup_days",
    "canonical_url",
    "dgft_is_honey",
    "doc_type_for",
    "dou_window",
    "effect_section",
    "find_dates",
    "find_ear_links",
    "is_eu_listing_pt",
    "merge_ocr_terms",
    "normalise_notification_number",
    "normalise_ocr_ordinals",
    "parse_article",
    "parse_bo_detail",
    "parse_bo_section",
    "parse_dgft_notifications",
    "parse_dou_search",
    "parse_ear_pdf",
    "parse_listing",
    "parse_local_date",
    "parse_mep_terms",
    "topics_of",
    "url_reference",
]
