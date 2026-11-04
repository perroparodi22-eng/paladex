"""Honey news from the GDELT DOC 2.0 API (https://www.gdeltproject.org).

Why GDELT is the backbone of the news feed
-----------------------------------------
* Its licence explicitly allows commercial use ("unlimited and unrestricted use for any
  academic, commercial, or governmental use"), with citation of the GDELT Project. Google
  News RSS, by contrast, is offered for personal, non-commercial use only, so those feeds
  are opt-in (see news_feeds.py).
* It covers 65 languages, so Argentine, Chinese, Ukrainian, Serbian, Vietnamese, Brazilian
  and Indian press are reached without per-country scrapers.

What we store: URL, headline, the time GDELT first saw the article, the outlet domain,
language and preview image. GDELT returns no article text, so there is no excerpt (and we
never fetch article bodies). Dedup, the honey gate, tagging and relevance are applied by
services.news exactly as for RSS feeds.

API facts
---------
* GET https://api.gdeltproject.org/api/v2/doc/doc?query=..&mode=ArtList&format=json
  &maxrecords=250&sort=DateDesc&timespan=..  (format=rss gives the same list as RSS; JSON
  is kept because it carries the language and the outlet domain as fields).
* Empty result -> "{}" (no "articles" key). Query errors come back as PLAIN TEXT with HTTP
  200 (e.g. "Your search contained a keyword that was too short." for the 2-character
  Chinese word 蜂蜜) — always check before parsing JSON.
* seendate is "YYYYMMDDTHHMMSSZ" (UTC) — when GDELT first saw the article.
* Operators: "exact phrase", (a OR b) — OR only inside parentheses, not nested —,
  -exclude, sourcelang:<language>, sourcecountry:<country>.
* The DOC API searches only the rolling last ~3 months.
* See `QUERIES` for what live tests (2026-11-04) showed about native-language keywords.

Rate limiting (live behaviour, 2026-11-04, plus third-party measurements from 2026)
-----------------------------------------------------------------------------------
* Too many requests -> HTTP 429 after ~10 s, plain text "Please limit requests to one every 5
  seconds or contact ... for larger queries. ..." (fixtures/news/real_gdelt_throttle.txt), no
  Retry-After. The real limit is much stricter than 5 s and depends on GDELT's load and on
  everyone sharing the IP: on our (shared) test connection a request 75 s after a successful
  answer, and another 120 s after one, were both refused; the first request after 7+ quiet
  minutes succeeded twice (answers take 14-16 s), but later ones after 8 and 10 quiet minutes
  were refused too. Third-party measurements (2026): 6 s spacing -> 1 of 7 accepted, 16 s
  -> 4 of 12, 60 s -> 3 of 8; after an accepted request the window stayed closed ~60 s;
  retrying quickly keeps it closed.
* A client that keeps asking is then not answered at all: the TLS handshake with
  api.gdeltproject.org is dropped after ~12 s ("Connection reset by peer"), for minutes, while
  gdeltproject.org's other hosts answer normally (seen 6 times in our tests, the last one after
  10 quiet minutes). A reset is therefore treated like a refusal, not as "offline", unless the
  PC really has no internet connection (checked once per run).

So each run makes few requests (`QUERIES_PER_RUN`), waits `MIN_GAP_SECONDS` after the end of
one answer before the next request (also across runs, via the saved state), retries a refused
request once after `RETRY_WAIT_SECONDS`, then defers the rest of the run's queries to the next
run and sets a cool-down that doubles after each fully refused run (`COOLDOWN_MINUTES`). A
deferred query is never lost: one that was not sent is first in line next time, a refused one
goes to the back of the rotation (so it cannot hold up the others), and its search window
reaches back to its own last successful answer. A run with deferred queries is "partial";
it fails only when GDELT has refused every request for `FAIL_AFTER_HOURS`. Nothing is left
uncommitted while waiting, so the pauses never lock other writers out of the database.
Runs are hourly with 3 queries each: every query is asked at least every few hours, and a run
lasts about 2 minutes (one more minute when a request is retried).

State (app_settings "collector_state:news_gdelt", committed with the articles):
  {"queries": {key: {"last_ok": iso, "last_try": iso, "last_refused": iso, "last_error": str|None}},
   "throttle_streak": int, "throttled_since": iso|None, "cooldown_until": iso|None,
   "last_request_end": iso}

Window: each query asks for the time since ITS last successful answer plus 2 hours of
overlap, in whole days (7 days the first time or on a forced run, at most 90), so a weekend
with the PC off, or a query deferred for a while, is still collected. A long window that hits
the 250-article cap is reported as a warning.
"""
from __future__ import annotations

import copy
import json
import math
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlencode

import httpx
from sqlalchemy.exc import IntegrityError

from ..enums import Reliability, SourceKind
from ..models import AppSetting, utcnow
from .base import CollectContext, Collector, CollectorError, Offline

API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
THROTTLE_TEXT = "limit requests"
MAX_RECORDS = 250             # the DOC API's per-request maximum
FIRST_WINDOW_DAYS = 7         # first run of a query, or a forced run
WINDOW_OVERLAP_HOURS = 2      # absorbs GDELT's indexing delay
MAX_WINDOW_DAYS = 90          # the DOC API searches only the rolling last ~3 months

# Politeness / throttling (see the module docstring).
QUERIES_PER_RUN = 3           # per-run budget; the rotation covers every query over a few runs
MIN_GAP_SECONDS = 45.0        # from the END of one GDELT answer to the next request
RETRY_WAIT_SECONDS = 60.0     # a refused request is retried once, after this pause
MAX_REFUSALS_PER_RUN = 2      # after this many refused answers the rest of the run is deferred
COOLDOWN_MINUTES = (15, 30, 60, 120, 240)   # no request until then; grows after each fully refused run
FAIL_AFTER_HOURS = 24         # refused for this long without one usable answer -> the run fails
STATE_KEY = "collector_state:news_gdelt"

# End of the last GDELT answer in this process (monotonic clock); the saved state carries the
# same information across processes (CLI run right after the app's scheduled run).
_last_answer_end: float | None = None

# GDELT returns language names in English.
_LANGUAGES = {
    "english": "en", "italian": "it", "spanish": "es", "portuguese": "pt", "german": "de", "french": "fr",
    "chinese": "zh", "ukrainian": "uk", "russian": "ru", "vietnamese": "vi", "serbian": "sr", "croatian": "hr",
    "turkish": "tr", "romanian": "ro", "hungarian": "hu", "polish": "pl", "hindi": "hi",
}


@dataclass(frozen=True)
class GdeltQuery:
    key: str
    label: str          # Italian label (shown in run warnings)
    query: str


# GDELT machine-translates every non-English article into English and matches the query against
# that translation (DOC 2.0 documentation, "Search Across 65 Languages"). Live test, 2026-11-04,
# 7-day window: `miele sourcelang:italian` -> 0 articles, `honey sourcelang:italian` -> Italian
# articles. Native-language keywords therefore find nothing (and a 2-character one such as 蜂蜜 is
# rejected: "Your search contained a keyword that was too short."), so every search uses ENGLISH
# keywords and selects the press by original language (sourcelang:) or country (sourcecountry:).
# The honey gate then works on the original-language headline (services.news). Operators inside an
# OR block are allowed (the documentation ORs imagetag: operators), so several languages share one
# search: fewer requests per rotation. GDELT matches the whole article, so the market terms below
# keep recipes and generic food stories out without requiring the term in the headline.
_MARKET_TERMS = ("(price OR prices OR export OR exports OR import OR imports OR beekeepers OR beekeeping OR "
                 "harvest OR production OR adulterated OR adulteration OR fraud OR tariff OR tariffs OR "
                 '"anti-dumping")')

# Order = priority when several queries are equally due (first run, or after a block).
QUERIES: list[GdeltQuery] = [
    GdeltQuery("en_trade", "inglese: commercio, prezzi, dazi, frodi",
               '(honey OR "raw honey") (export OR exports OR import OR imports OR price OR prices OR tariff OR '
               'antidumping OR "anti-dumping" OR adulteration OR adulterated OR beekeepers OR harvest) '
               'sourcelang:english -"honey singh" -paypal'),
    GdeltQuery("it", "italiano", f"honey {_MARKET_TERMS} sourcelang:italian"),
    GdeltQuery("es_pt", "spagnolo e portoghese (Argentina, Brasile, Messico, Uruguay, Spagna)",
               f"honey {_MARKET_TERMS} (sourcelang:spanish OR sourcelang:portuguese)"),
    GdeltQuery("zh_vi", "cinese e vietnamita", f"honey {_MARKET_TERMS} (sourcelang:chinese OR sourcelang:vietnamese)"),
    GdeltQuery("uk_sr", "ucraino, serbo e croato",
               f"honey {_MARKET_TERMS} (sourcelang:ukrainian OR sourcelang:serbian OR sourcelang:croatian)"),
    GdeltQuery("de_fr", "tedesco e francese", f"honey {_MARKET_TERMS} (sourcelang:german OR sourcelang:french)"),
    GdeltQuery("en_india", "India (tutte le lingue)",
               'honey (export OR exports OR price OR prices OR antidumping OR "anti-dumping") sourcecountry:india'),
]


def build_url(query: str, timespan: str) -> str:
    params = {"query": query, "mode": "ArtList", "format": "json", "maxrecords": MAX_RECORDS,
              "sort": "DateDesc", "timespan": timespan}
    return f"{API_URL}?{urlencode(params)}"


def window_timespan(last_success_at: datetime | None, now: datetime, force: bool) -> str:
    """Search window reaching back to the last successful answer (+ overlap), so the days the
    PC was off (weekends, holidays) or the query was deferred are still collected. Whole days,
    1 to MAX_WINDOW_DAYS; at least FIRST_WINDOW_DAYS on a first or forced run. Naive UTC."""
    if last_success_at is None:
        return f"{FIRST_WINDOW_DAYS}d"
    hours = (now - last_success_at).total_seconds() / 3600 + WINDOW_OVERLAP_HOURS
    days = max(1, math.ceil(hours / 24))
    if force:
        days = max(days, FIRST_WINDOW_DAYS)
    return f"{min(MAX_WINDOW_DAYS, days)}d"


def parse_seendate(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ")
    except ValueError:
        return None


class GdeltQueryError(Exception):
    """GDELT answered with plain text instead of JSON (bad query or throttling)."""


# A backslash that does not start a valid JSON escape (e.g. a title containing "\x"): valid
# escapes are matched as pairs first, so "\\x" (an escaped backslash) is left alone.
_JSON_ESCAPE = re.compile(r'\\(?:(["\\/bfnrt]|u[0-9a-fA-F]{4})|)')


def _escape_stray_backslashes(text: str) -> str:
    return _JSON_ESCAPE.sub(lambda m: m.group(0) if m.group(1) else "\\\\", text)


def parse_response(content: bytes) -> list[dict]:
    """Return ingestable items. Raises GdeltQueryError on a plain-text answer and ValueError
    (json.JSONDecodeError) on JSON that cannot be read even after repair."""
    text = content.decode("utf-8", errors="replace").strip()
    if not text:
        return []
    if not text.startswith("{"):
        raise GdeltQueryError(text[:200])
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            data = json.loads(text, strict=False)   # payloads occasionally carry control characters
        except json.JSONDecodeError:
            # stray backslashes in a title: escaped, so the text stays exactly as GDELT sent it.
            # Anything else (e.g. an unescaped quote) still raises.
            data = json.loads(_escape_stray_backslashes(text), strict=False)
    articles = data.get("articles", [])
    if not isinstance(articles, list):
        raise CollectorError("GDELT: campo 'articles' inatteso (formato cambiato?)")
    items = []
    for a in articles:
        if not isinstance(a, dict) or not a.get("url") or not a.get("title"):
            continue
        items.append({
            "url": a["url"],
            "title": a["title"],
            "published_at": parse_seendate(a.get("seendate")),
            "snippet": None,
            "image_url": a.get("socialimage") or None,
            "publisher": a.get("domain") or None,
            "language": _LANGUAGES.get(str(a.get("language") or "").strip().lower()),
        })
    return items


def is_throttle_text(text: str | None) -> bool:
    return THROTTLE_TEXT in (text or "").lower()


def short_reason(text: str | None) -> str:
    """GDELT's refusal for a warning: the first sentence of the throttle text (the rest is
    contact details and links), otherwise the start of the message."""
    text = " ".join((text or "").split())
    if is_throttle_text(text):
        m = re.search(r"[^.]*limit requests[^.]*?seconds", text, re.I)
        return m.group(0).strip() if m else text[:80]
    return text[:120]


# ---------------------------------------------------------------------------
# State (rotation, cool-down, spacing) in app_settings
# ---------------------------------------------------------------------------


def load_state(session) -> dict:
    row = session.get(AppSetting, STATE_KEY)
    state = copy.deepcopy(row.value) if row is not None and isinstance(row.value, dict) else {}
    if not isinstance(state.get("queries"), dict):
        state["queries"] = {}
    return state


def save_state(session, state: dict) -> None:
    row = session.get(AppSetting, STATE_KEY)
    if row is None:
        session.add(AppSetting(key=STATE_KEY, value=copy.deepcopy(state)))
    else:
        row.value = copy.deepcopy(state)        # a new object, so SQLAlchemy sees the JSON change
    session.flush()


def _dt(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def plan_queries(state: dict, budget: int = QUERIES_PER_RUN) -> list[GdeltQuery]:
    """The `budget` queries asked least recently (never-asked first, then in `QUERIES` order).
    A query that was not sent because the run stopped keeps its place at the front; a refused
    one goes to the back, so a query GDELT keeps refusing cannot hold up the others (its window
    still reaches back to its last answer, so nothing is lost)."""
    qs = state.get("queries") or {}

    def asked(i: int) -> str:
        q = qs.get(QUERIES[i].key) or {}
        return max(q.get("last_try") or "", q.get("last_refused") or "")

    order = sorted(range(len(QUERIES)), key=lambda i: (asked(i), i))
    return [QUERIES[i] for i in order[:budget]]


def cooldown_minutes(streak: int) -> int:
    return COOLDOWN_MINUTES[min(max(streak - 1, 0), len(COOLDOWN_MINUTES) - 1)]


def _internet_works() -> bool:
    from .runner import is_online   # lazy: runner imports the registry, which imports this module

    return is_online()


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


class GdeltNewsCollector(Collector):
    key = "news_gdelt"
    name = "GDELT – notizie mondiali sul miele (11 lingue)"
    publisher = "The GDELT Project"
    homepage = "https://www.gdeltproject.org/"
    kind = SourceKind.API
    reliability = Reliability.AGGREGATOR
    category = "news"
    expected_update = "Ogni ora, 3 ricerche a rotazione: tutte le lingue in poche ore (titoli e link)"
    expected_update_en = "Hourly, 3 searches in rotation: every language within a few hours (headlines and links)"
    expected_max_age_days = 3
    terms_note = ("Fonte: The GDELT Project (gdeltproject.org) — uso commerciale consentito con citazione. "
                  "Si conservano solo titolo, link, testata e data; il testo degli articoli resta degli editori. "
                  "GDELT limita la frequenza delle richieste: le ricerche rifiutate vengono ripetute "
                  "all'esecuzione successiva.")
    schedule = {"trigger": "cron", "minute": 23}
    order = 79

    def collect(self, ctx: CollectContext) -> None:
        ctx.MIN_INTERVAL_PER_HOST = MIN_GAP_SECONDS   # floor for ctx.fetch's own per-host spacing
        now = utcnow()
        state = load_state(ctx.session)
        cooldown = _dt(state.get("cooldown_until"))
        if cooldown is not None and now < cooldown:
            # A request now would only extend GDELT's block: wait for the next run.
            self._finish_refused(ctx, state, now, [q.label for q in plan_queries(state)],
                                 f"GDELT ha chiesto di rallentare: nessuna richiesta fino alle "
                                 f"{cooldown:%H:%M} UTC")
            return

        ok, answered, refusals = 0, 0, 0
        deferred: list[str] = []
        last_refusal = ""
        internet_checked = False
        for q in plan_queries(state):
            if refusals >= MAX_REFUSALS_PER_RUN:
                deferred.append(q.label)
                continue
            qstate = state["queries"].setdefault(q.key, {})
            asked_at = utcnow()
            timespan = window_timespan(_dt(qstate.get("last_ok")), asked_at, ctx.force)
            url = build_url(q.query, timespan)
            kind, payload = self._ask(ctx, url, state)
            while kind in ("refused", "unreachable", "server_error"):
                if kind == "unreachable" and not internet_checked:
                    internet_checked = True
                    if not _internet_works():
                        raise Offline(f"GDELT: {payload}")
                refusals += 1
                last_refusal = payload
                qstate["last_refused"] = asked_at.isoformat(timespec="seconds")
                if refusals >= MAX_REFUSALS_PER_RUN:
                    break
                ctx.checkpoint()                 # never wait with an open write transaction
                time.sleep(RETRY_WAIT_SECONDS)
                asked_at = utcnow()
                kind, payload = self._ask(ctx, url, state)
            if kind in ("refused", "unreachable", "server_error"):
                deferred.append(q.label)
                continue

            answered += 1
            qstate["last_try"] = asked_at.isoformat(timespec="seconds")
            if kind != "ok":
                qstate["last_error"] = str(payload)[:300]
                if kind == "rejected":
                    ctx.warn(f"GDELT, ricerca «{q.label}» rifiutata: {payload}"[:400])
                else:
                    ctx.warn(f"GDELT, ricerca «{q.label}»: risposta JSON non leggibile, saltata ({payload})"[:400])
                save_state(ctx.session, state)
                ctx.checkpoint()
                continue
            ok += 1
            items = payload
            if len(items) >= MAX_RECORDS and timespan != "1d":
                # newest first: a capped catch-up window may miss its oldest articles. Say so.
                ctx.warn(f"GDELT, ricerca «{q.label}»: raggiunto il limite di {MAX_RECORDS} articoli sulla "
                         f"finestra di {timespan}; gli articoli più vecchi del periodo potrebbero mancare")
            self._store(ctx, items)
            # the window moves forward only once the articles are committed
            qstate["last_ok"] = asked_at.isoformat(timespec="seconds")
            qstate["last_error"] = None
            save_state(ctx.session, state)
            ctx.checkpoint()

        if refusals:
            if ok:
                state["throttle_streak"] = 0
                state["throttled_since"] = None
            else:
                state["throttle_streak"] = int(state.get("throttle_streak") or 0) + 1
                state["throttled_since"] = state.get("throttled_since") or now.isoformat(timespec="seconds")
            state["cooldown_until"] = (utcnow() + timedelta(minutes=cooldown_minutes(state["throttle_streak"]))
                                       ).isoformat(timespec="seconds")
        else:
            state["throttle_streak"] = 0
            state["throttled_since"] = None
            state["cooldown_until"] = None

        if deferred and ok == 0 and answered == 0:
            self._finish_refused(ctx, state, now, deferred,
                                 f"GDELT ha rifiutato le richieste («{short_reason(last_refusal)}»)")
            return
        save_state(ctx.session, state)
        ctx.checkpoint()
        if deferred:
            ctx.warn(f"GDELT ha chiesto di rallentare («{short_reason(last_refusal)}»): {len(deferred)} "
                     f"ricerche rinviate alla prossima esecuzione ({', '.join(deferred)})"[:500])
        if ok == 0 and not deferred:
            raise CollectorError("GDELT: nessuna ricerca è andata a buon fine (vedi avvisi)")

    # ------------------------------------------------------------------ helpers
    def _finish_refused(self, ctx: CollectContext, state: dict, now: datetime, deferred: list[str],
                        why: str) -> None:
        """No usable answer this run because GDELT is throttling us: keep the state, report
        "partial" (the queries are deferred), or fail once this has lasted FAIL_AFTER_HOURS."""
        save_state(ctx.session, state)
        ctx.checkpoint()
        since = _dt(state.get("throttled_since"))
        if since is not None and now - since >= timedelta(hours=FAIL_AFTER_HOURS):
            raise CollectorError(f"GDELT rifiuta le richieste dal {since:%d/%m/%Y %H:%M} UTC "
                                 f"(più di {FAIL_AFTER_HOURS} ore): {why}"[:500])
        ctx.warn(f"{why}; ricerche rinviate alla prossima esecuzione: {', '.join(deferred)}"[:500])

    def _ask(self, ctx: CollectContext, url: str, state: dict) -> tuple[str, object]:
        """One request, spaced from the previous answer. Returns (kind, payload):
        ok -> items; refused / unreachable / server_error -> message (retry later);
        rejected / unreadable -> message (GDELT answered: this query is done for this run)."""
        global _last_answer_end
        ctx.checkpoint()     # nothing uncommitted while waiting: other writers are never locked out
        self._wait_turn(state)
        try:
            doc = ctx.fetch(url, store=False, accept_status=(200, 429, 500, 502, 503, 504), retries=0)
        except Offline as exc:
            return "unreachable", str(exc)
        except httpx.TransportError as exc:     # e.g. connection reset while reading the answer
            return "unreachable", f"{type(exc).__name__}: {exc}"
        except CollectorError as exc:
            if str(exc).startswith("Timeout"):
                return "unreachable", str(exc)
            return "rejected", str(exc)          # another HTTP status (e.g. 404): the API changed
        finally:
            _last_answer_end = time.monotonic()
            state["last_request_end"] = utcnow().isoformat(timespec="seconds")
        if doc.status_code == 429:
            return "refused", doc.text.strip()[:200] or "HTTP 429"
        if doc.status_code >= 500:
            return "server_error", f"HTTP {doc.status_code}"
        try:
            return "ok", parse_response(doc.content)
        except GdeltQueryError as exc:
            return ("refused" if is_throttle_text(str(exc)) else "rejected"), str(exc)
        except ValueError as exc:               # json.JSONDecodeError
            return "unreadable", str(exc)

    @staticmethod
    def _wait_turn(state: dict) -> None:
        """Sleep until MIN_GAP_SECONDS have passed since the end of the previous GDELT answer
        (this process, or a previous run whose end is in the saved state)."""
        waits = []
        if _last_answer_end is not None:
            waits.append(MIN_GAP_SECONDS - (time.monotonic() - _last_answer_end))
        last_end = _dt(state.get("last_request_end"))
        if last_end is not None:
            waits.append(MIN_GAP_SECONDS - (utcnow() - last_end).total_seconds())
        wait = min(max(waits, default=0.0), MIN_GAP_SECONDS)
        if wait > 0:
            time.sleep(wait)

    @staticmethod
    def _store(ctx: CollectContext, items: list[dict]) -> None:
        for item in items:
            try:
                ctx.add_news(**item)
                ctx.checkpoint()
            except IntegrityError:
                ctx.session.rollback()
                ctx.counters.restore_committed()
                ctx.counters.count("unchanged")
            except Exception as exc:  # noqa: BLE001 - one bad item must not lose the batch
                ctx.session.rollback()
                ctx.counters.restore_committed()
                ctx.warn(f"Articolo non salvato ({item['url'][:120]}): {type(exc).__name__}: {exc}"[:400])
