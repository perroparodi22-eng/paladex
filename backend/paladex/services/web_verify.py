"""Verification of a web finding on the page it cites (the anti-fabrication rule of `web_findings`).

A finding (``models_findings.WebFinding``) is stored or shown ONLY when Paladex itself opened its
``source_url`` and found in the page text

* the ``quote``, and
* every number of ``value_as_published`` (its digits: "75.000 t", "75,000 t" and "75 000 t" all
  mean the digits 75000; each number must be a whole number of the page, never part of another).

Both sides are normalised the same way: Unicode NFKC, invisible characters (soft hyphen, zero-width
spaces) removed, typographic quotes and dashes made plain, whitespace collapsed, case ignored.
HTML pages are read as visible text (scripts, styles and templates removed); PDFs with pdfplumber
(the first ``MAX_PDF_PAGES`` pages). Nothing else is accepted: a spreadsheet, an image or a page that
needs a login fails, with its reason.

Failures are honest and never worked around: an unreachable page, a page that refuses automated
access (HTTP 401/403/429/451, anti-bot challenge pages) or one where the quote or the number is not
found is simply not verified. Only an excerpt of the page around the quote is archived, never the
whole page.

This module is pure (no HTTP, no database): the collector fetches the page and hands the bytes here.
"""
from __future__ import annotations

import io
import ipaddress
import logging
import re
import socket
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime
from urllib.parse import urlsplit

log = logging.getLogger(__name__)

MAX_PDF_PAGES = 200
MAX_DOCUMENT_BYTES = 40 * 1024 * 1024
MIN_QUOTE_CHARS = 15
EXCERPT_CHARS = 1500            # archived on each side of the quote
NUMBER_EXCERPT_CHARS = 300      # around the number, when it is outside the quote's excerpt
MAX_CHECKS_KEPT = 12            # history of checks kept in `verification`

METHOD = ("Paladex opened source_url and searched the page text for the quote and for every number of "
          "value_as_published (normalised: Unicode NFKC, whitespace collapsed, case ignored, typographic "
          "quotes and dashes made plain; numbers compared by their digits, as whole numbers).")

# Reason codes (shown in the run warnings and stored in `verification.reason`).
UNREACHABLE = "unreachable"
BLOCKED = "blocked"
UNSUPPORTED = "unsupported"
UNREADABLE = "unreadable"
QUOTE_NOT_FOUND = "quote_not_found"
NUMBER_NOT_FOUND = "number_not_found"
INVALID = "invalid"

# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

_INVISIBLE = re.compile("[­​‌‍⁠﻿]")
_PLAIN = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'", "´": "'", "`": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"', "«": '"', "»": '"',
    "‹": "'", "›": "'",
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-", "−": "-",
    "﹘": "-", "﹣": "-", "－": "-",
})
_WS = re.compile(r"\s+")


def display_text(s: str | None) -> str:
    """NFKC, invisible characters removed, plain quotes and dashes, whitespace collapsed (case kept)."""
    s = unicodedata.normalize("NFKC", s or "")
    s = _INVISIBLE.sub("", s).translate(_PLAIN)
    return _WS.sub(" ", s).strip()


def normalize(s: str | None) -> str:
    """`display_text`, case-folded: the form quotes are compared in."""
    return display_text(s).casefold()


# A number as written in a page: 75000, 75,000, 75.000, 75 000, 1.234,5, 1,2, Indian 1,14,570.24 ...
# (never inside another number).
_NUM_RE = re.compile(r"(?<![\d])(?:\d{1,2}(?:,\d{2})+,\d{3}(?:\.\d+)?|\d{1,3}(?:[ .,']\d{3})+(?:[.,]\d+)?"
                     r"|\d+(?:[.,]\d+)?)(?![\d])")


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def published_numbers(value_as_published: str | None) -> list[str]:
    """The digit strings of every number in `value_as_published` ("US$ 1.2 billion" -> ["12"])."""
    out: list[str] = []
    for m in _NUM_RE.finditer(display_text(value_as_published)):
        d = _digits(m.group(0))
        if d and d not in out:
            out.append(d)
    return out


def page_numbers(text: str) -> dict[str, int]:
    """Digit string -> first position of every number of the page. A number written with spaces
    between groups ("75 000") is also read as its separate parts, so no reading is lost."""
    out: dict[str, int] = {}
    for m in _NUM_RE.finditer(text):
        tok = m.group(0)
        out.setdefault(_digits(tok), m.start())
        if " " in tok:
            pos = m.start()
            for part in tok.split(" "):
                d = _digits(part)
                if d:
                    out.setdefault(d, pos)
                pos += len(part) + 1
    return out


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

_BLOCK_TAGS = ("p", "div", "br", "li", "ul", "ol", "td", "th", "tr", "table", "thead", "tbody", "tfoot", "caption",
               "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "header", "footer", "nav", "aside", "main",
               "blockquote", "pre", "dd", "dt", "dl", "figure", "figcaption", "title", "option", "hr", "address",
               "summary", "details", "form", "fieldset", "legend", "label")
_DROP_TAGS = ("script", "style", "noscript", "template", "svg", "iframe", "object", "embed", "canvas")

# Anti-bot / login interstitials (looked for in the raw page when the quote is not found).
_BLOCK_MARKERS = (
    "cf-chl", "cf_chl", "just a moment...", "attention required! | cloudflare", "checking your browser",
    "enable javascript and cookies to continue", "verify you are human", "are you a robot", "captcha",
    "incapsula incident", "request unsuccessful. incapsula", "pardon our interruption", "access denied",
    "please log in", "please sign in", "datadome", "perimeterx", "px-captcha", "bot detection",
)


@dataclass
class PageText:
    ok: bool
    doc_type: str | None = None            # pdf | html | text
    text: str = ""                         # display_text of the page
    reason: str | None = None
    detail: str | None = None
    pdf_pages: tuple[int, int] | None = None   # (read, total)
    raw_head: str = ""                     # lower-cased beginning of the raw page (challenge detection)


def doc_type(content: bytes, content_type: str | None) -> str | None:
    ctype = (content_type or "").lower()
    head = content[:2048].lstrip().lower()
    if content[:1024].lstrip().startswith(b"%pdf") or b"%PDF-" in content[:1024]:
        return "pdf"
    if "pdf" in ctype:
        return None                        # announced as a PDF but is not one (error page?)
    if (b"<html" in head or b"<!doctype html" in head or b"<body" in head or b"<head" in head
            or "html" in ctype or "xhtml" in ctype):
        return "html"
    if ctype.startswith("text/") or (not ctype and not _looks_binary(content)):
        return "text"
    return None


def _looks_binary(content: bytes) -> bool:
    sample = content[:4096]
    return b"\x00" in sample or content[:4] in (b"PK\x03\x04", b"\xd0\xcf\x11\xe0", b"\x89PNG", b"GIF8")


def _decode(content: bytes) -> str:
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def html_to_text(content: bytes) -> str:
    """Visible text of an HTML page: scripts, styles and templates removed, one space between blocks
    (inline markup such as <b>75</b>,000 stays "75,000")."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(content, "lxml")
    for tag in soup(list(_DROP_TAGS)):
        tag.decompose()
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.insert_before("\n")
        tag.insert_after("\n")
    return display_text(soup.get_text(""))


def pdf_to_text(content: bytes) -> tuple[str, int, int]:
    import pdfplumber

    parts: list[str] = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        total = len(pdf.pages)
        for page in pdf.pages[:MAX_PDF_PAGES]:
            try:
                parts.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001 - one unreadable page does not hide the others
                parts.append("")
            try:
                page.close()
            except Exception:  # noqa: BLE001 - older pdfplumber versions
                pass
    return display_text("\n".join(parts)), min(total, MAX_PDF_PAGES), total


def extract_text(content: bytes, content_type: str | None) -> PageText:
    if len(content) > MAX_DOCUMENT_BYTES:
        return PageText(False, reason=UNSUPPORTED, detail=f"document too large ({len(content) // (1024 * 1024)} MB)")
    kind = doc_type(content, content_type)
    head = _decode(content[:200_000]).lower()
    if kind is None:
        return PageText(False, reason=UNSUPPORTED, raw_head=head,
                        detail=f"not a web page or PDF (content type {content_type or 'unknown'})")
    if kind == "pdf":
        try:
            text, read, total = pdf_to_text(content)
        except Exception as exc:  # noqa: BLE001 - a broken PDF fails this finding only
            return PageText(False, doc_type="pdf", reason=UNREADABLE, detail=f"PDF could not be read ({type(exc).__name__})")
        if not text:
            return PageText(False, doc_type="pdf", reason=UNREADABLE, pdf_pages=(read, total),
                            detail="the PDF has no text layer (scanned image?)")
        return PageText(True, doc_type="pdf", text=text, pdf_pages=(read, total))
    if kind == "html":
        return PageText(True, doc_type="html", text=html_to_text(content), raw_head=head)
    return PageText(True, doc_type="text", text=display_text(_decode(content)), raw_head=head)


def looks_blocked(page: PageText) -> bool:
    """An anti-bot challenge, a login wall or an 'access denied' page instead of the content."""
    if page.doc_type == "pdf":
        return False
    return len(page.text) < 4000 and any(m in page.raw_head for m in _BLOCK_MARKERS)


def http_failure(status: int) -> tuple[str, str] | None:
    """(reason, detail) for an HTTP status that is not a page, None for a 2xx/3xx answer."""
    if status < 400:
        return None
    if status in (401, 407):
        return BLOCKED, f"the page needs a login (HTTP {status})"
    if status in (403, 429, 451):
        return BLOCKED, f"the site refuses automated access (HTTP {status})"
    if status in (404, 410):
        return UNREACHABLE, f"page not found (HTTP {status})"
    return UNREACHABLE, f"the site answered HTTP {status}"


# ---------------------------------------------------------------------------
# Addresses Paladex may open
# ---------------------------------------------------------------------------

def _resolve(host: str) -> list[str]:
    try:
        return sorted({ai[4][0] for ai in socket.getaddrinfo(host, None)})
    except (OSError, UnicodeError):
        return []          # unknown here (e.g. resolved by a proxy): the fetch itself will tell


def url_problem(url: str | None) -> str | None:
    """Why `url` must not be opened (None when it may): only public http(s) web addresses. A page,
    a model's answer or a seed entry can never make Paladex read this computer or its network."""
    try:
        parts = urlsplit(url or "")
        host = (parts.hostname or "").rstrip(".").lower()
    except ValueError:
        return "not a valid web address"
    if parts.scheme not in ("http", "https") or not host:
        return "not an http(s) web address"
    if parts.username or parts.password:
        return "web addresses with credentials are not opened"
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        ip = None
    if ip is not None:
        return None if ip.is_global else "a private or local network address"
    if "." not in host or host.endswith((".local", ".localhost", ".internal", ".lan", ".home", ".arpa")):
        return "a private or local network address"
    for addr in _resolve(host):
        try:
            if not ipaddress.ip_address(addr.split("%")[0]).is_global:
                return "the name points to a private or local network address"
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# The check itself
# ---------------------------------------------------------------------------

@dataclass
class Verification:
    ok: bool
    checked_at: datetime
    reason: str | None = None
    detail: str | None = None
    url: str | None = None                 # the address asked for
    final_url: str | None = None           # after redirects
    http_status: int | None = None
    doc_type: str | None = None
    text_chars: int | None = None
    pdf_pages: list[int] | None = None
    quote_found: bool | None = None
    numbers: list[str] = field(default_factory=list)   # digits of value_as_published
    numbers_found: list[str] = field(default_factory=list)
    number_found: bool | None = None
    number_in_quote: bool | None = None
    excerpt: str | None = None             # archived as the raw document (not stored in `verification`)

    def record(self) -> dict:
        """What is stored in `verification` (JSON): everything but the excerpt."""
        d = asdict(self)
        d.pop("excerpt", None)
        d["checked_at"] = self.checked_at.replace(microsecond=0).isoformat()
        return d


def _find(text: str, quote: str) -> tuple[int, int] | None:
    """(start, length) of `quote` in `text` (both display_text), ignoring case; None if absent."""
    q = quote.casefold()
    low = text.casefold()
    i = low.find(q)
    if i < 0:
        return None
    m = re.search(re.escape(quote), text, re.IGNORECASE)
    if m:
        return m.start(), m.end() - m.start()
    # case folding changed lengths (e.g. "ß" -> "ss"): position by proportion, close enough for an excerpt
    ratio = len(text) / max(1, len(low))
    return int(i * ratio), len(quote)


def _dehyphenate(text: str) -> str:
    """'pro- duction' -> 'production' (words hyphenated at a line end in a PDF)."""
    return re.sub(r"(\w)- (\w)", r"\1\2", text)


def make_excerpt(text: str, at: tuple[int, int], number_at: int | None) -> str:
    start, length = at
    a, b = max(0, start - EXCERPT_CHARS), min(len(text), start + length + EXCERPT_CHARS)
    parts = [f"[characters {a}-{b} of {len(text)}]", ("…" if a else "") + text[a:b] + ("…" if b < len(text) else "")]
    if number_at is not None and not (a <= number_at < b):
        na, nb = max(0, number_at - NUMBER_EXCERPT_CHARS), min(len(text), number_at + NUMBER_EXCERPT_CHARS)
        parts += [f"[the number: characters {na}-{nb}]", "…" + text[na:nb] + "…"]
    return "\n".join(parts)


def check_text(page: PageText, quote: str, value_as_published: str, *, checked_at: datetime,
               url: str | None = None, final_url: str | None = None, http_status: int | None = None) -> Verification:
    """Look for the quote and the number(s) in an extracted page."""
    v = Verification(ok=False, checked_at=checked_at, url=url, final_url=final_url, http_status=http_status,
                     doc_type=page.doc_type, text_chars=len(page.text) if page.ok else None,
                     pdf_pages=list(page.pdf_pages) if page.pdf_pages else None)
    if not page.ok:
        v.reason, v.detail = page.reason, page.detail
        return v
    q = display_text(quote)
    v.numbers = published_numbers(value_as_published)
    if len(q) < MIN_QUOTE_CHARS:
        v.reason, v.detail = INVALID, f"the quote is too short to prove anything (under {MIN_QUOTE_CHARS} characters)"
        return v
    if not v.numbers:
        v.reason, v.detail = INVALID, f"value_as_published {value_as_published!r} contains no number"
        return v
    text = page.text
    at = _find(text, q)
    if at is None and page.doc_type == "pdf":
        text = _dehyphenate(page.text)
        at = _find(text, q)
    v.quote_found = at is not None
    if at is None:
        if looks_blocked(page):
            v.reason, v.detail = BLOCKED, "the site answered with an anti-bot, login or 'access denied' page"
        else:
            where = f" (first {page.pdf_pages[0]} of {page.pdf_pages[1]} pages read)" if page.pdf_pages and page.pdf_pages[0] < page.pdf_pages[1] else ""
            v.reason, v.detail = QUOTE_NOT_FOUND, f"the quote is not in the page text{where}"
        return v
    numbers = page_numbers(text)
    v.numbers_found = [d for d in v.numbers if d in numbers]
    v.number_found = len(v.numbers_found) == len(v.numbers)
    quote_numbers = page_numbers(q)
    v.number_in_quote = all(d in quote_numbers for d in v.numbers)
    if not v.number_found:
        missing = [d for d in v.numbers if d not in numbers]
        v.reason, v.detail = NUMBER_NOT_FOUND, (f"the quote is there, but the number of {value_as_published!r} "
                                                f"(digits {', '.join(missing)}) is not in the page")
        return v
    number_at = None if v.number_in_quote else numbers.get(v.numbers[0])
    v.excerpt = make_excerpt(text, at, number_at)
    v.ok = True
    return v


def add_check(previous: dict | None, v: Verification) -> dict:
    """`verification` after one more check: the latest check in full, the history of the checks
    (newest last, capped) and the time of the last successful one. Returns a NEW dict."""
    prev = dict(previous or {})
    checks = list(prev.get("checks") or [])
    checks.append({"at": v.record()["checked_at"], "ok": v.ok, "reason": v.reason})
    out = {"method": METHOD, **v.record(), "checks": checks[-MAX_CHECKS_KEPT:]}
    out["last_ok_at"] = out["checked_at"] if v.ok else prev.get("last_ok_at")
    if not v.ok and previous:
        out["kept_after_failed_check"] = True
    return out


def failed(reason: str, detail: str, *, checked_at: datetime, url: str | None = None,
           http_status: int | None = None, final_url: str | None = None) -> Verification:
    return Verification(ok=False, checked_at=checked_at, reason=reason, detail=detail, url=url,
                        http_status=http_status, final_url=final_url)
