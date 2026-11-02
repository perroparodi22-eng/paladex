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

API facts (docs/research/news.json; confidence: from_search_snippets):
* GET https://api.gdeltproject.org/api/v2/doc/doc?query=..&mode=ArtList&format=json
  &maxrecords=250&sort=DateDesc&timespan=..
* Empty result -> "{}" (no "articles" key). Query errors and throttling come back as PLAIN
  TEXT, often with HTTP 200 — always check before parsing JSON.
* At most one request every 5 seconds: we space calls 6 s apart within one run.
* seendate is "YYYYMMDDTHHMMSSZ" (UTC) — when GDELT first saw the article.
* Operators: "exact phrase", (a OR b) — OR only inside parentheses —, -exclude,
  sourcelang:<language>. Very short or very common words can be rejected.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlencode

from sqlalchemy.exc import IntegrityError

from ..enums import Reliability, SourceKind
from .base import CollectContext, Collector, CollectorError

API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
MIN_SECONDS_BETWEEN_CALLS = 6.0
THROTTLE_TEXT = "limit requests"

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


# One saved search per language/market. Negative terms remove known noise (Miele appliances,
# Honey Singh, PayPal Honey, "luna de miel"). UNVERIFIED: every operator spelling is from
# third-party documentation — a rejected query is reported as a warning, not a failure.
QUERIES: list[GdeltQuery] = [
    GdeltQuery("en_trade", "inglese: commercio, prezzi, dazi, frodi",
               '(honey OR "raw honey") (export OR exports OR import OR imports OR price OR prices OR tariff OR '
               'antidumping OR "anti-dumping" OR adulteration OR adulterated OR beekeepers OR harvest) '
               'sourcelang:english -"honey singh" -paypal'),
    GdeltQuery("it", "italiano", 'miele (prezzo OR prezzi OR importazioni OR export OR esportazioni OR apicoltori OR '
               'frode OR dazi OR raccolto OR produzione) sourcelang:italian -lavatrice -lavastoviglie -elettrodomestici'),
    GdeltQuery("es", "spagnolo (Argentina, Spagna, Messico, Uruguay)",
               'miel (exportación OR exportaciones OR precio OR precios OR apicultores OR cosecha OR importaciones) '
               'sourcelang:spanish -"luna de miel"'),
    GdeltQuery("pt", "portoghese (Brasile)",
               '("exportação de mel" OR "exportações de mel" OR "preço do mel" OR apicultores OR "mel brasileiro") '
               'sourcelang:portuguese'),
    GdeltQuery("de", "tedesco", 'Honig (Preis OR Preise OR Import OR Imker OR Ernte OR Verfälschung) '
               'sourcelang:german -Miele'),
    GdeltQuery("zh", "cinese", '蜂蜜 (出口 OR 价格 OR 产量) sourcelang:chinese'),
    GdeltQuery("uk", "ucraino", 'мед (експорт OR ціна OR ціни OR пасічники OR врожай) sourcelang:ukrainian'),
    GdeltQuery("vi", "vietnamita", '"mật ong" (xuất khẩu OR giá OR "chống bán phá giá") sourcelang:vietnamese'),
    GdeltQuery("sr", "serbo", '("izvoz meda" OR pčelari OR pčelarstvo OR "cena meda") sourcelang:serbian'),
    GdeltQuery("en_india", "inglese: India", 'honey (export OR exports OR price OR antidumping) sourcecountry:india'),
]


def build_url(query: str, timespan: str) -> str:
    params = {"query": query, "mode": "ArtList", "format": "json", "maxrecords": 250,
              "sort": "DateDesc", "timespan": timespan}
    return f"{API_URL}?{urlencode(params)}"


def parse_seendate(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ")
    except ValueError:
        return None


class GdeltQueryError(Exception):
    """GDELT answered with plain text instead of JSON (bad query or throttling)."""


def parse_response(content: bytes) -> list[dict]:
    """Return ingestable items. Raises GdeltQueryError on a plain-text answer."""
    text = content.decode("utf-8", errors="replace").strip()
    if not text:
        return []
    if not text.startswith("{"):
        raise GdeltQueryError(text[:200])
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = json.loads(text, strict=False)   # payloads occasionally carry control characters
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


class GdeltNewsCollector(Collector):
    key = "news_gdelt"
    name = "GDELT – notizie mondiali sul miele (10 lingue)"
    publisher = "The GDELT Project"
    homepage = "https://www.gdeltproject.org/"
    kind = SourceKind.API
    reliability = Reliability.AGGREGATOR
    category = "news"
    expected_update = "Ricerca ogni 2 ore in 10 lingue (titoli e link; GDELT aggiorna l'indice ogni 15 minuti)"
    expected_max_age_days = 3
    terms_note = ("Fonte: The GDELT Project (gdeltproject.org) — uso commerciale consentito con citazione. "
                  "Si conservano solo titolo, link, testata e data; il testo degli articoli resta degli editori.")
    schedule = {"trigger": "cron", "hour": "*/2", "minute": 23}
    order = 79

    def collect(self, ctx: CollectContext) -> None:
        ctx.MIN_INTERVAL_PER_HOST = MIN_SECONDS_BETWEEN_CALLS   # per-run politeness for this host
        first_run = ctx.source.last_success_at is None
        timespan = "7d" if (first_run or ctx.force) else "1d"
        ok = 0
        for q in QUERIES:
            url = build_url(q.query, timespan)
            items = self._fetch_items(ctx, q, url)
            if items is None:
                continue
            ok += 1
            for item in items:
                try:
                    ctx.add_news(**item)
                    ctx.checkpoint()
                except IntegrityError:
                    ctx.session.rollback()
                    ctx.counters.new = ctx.counters.committed_new
                    ctx.counters.count("unchanged")
                except Exception as exc:  # noqa: BLE001 - one bad item must not lose the batch
                    ctx.session.rollback()
                    ctx.counters.new = ctx.counters.committed_new
                    ctx.warn(f"Articolo non salvato ({item['url'][:120]}): {type(exc).__name__}: {exc}"[:400])
        if ok == 0:
            raise CollectorError("GDELT: nessuna ricerca è andata a buon fine (vedi avvisi)")

    def _fetch_items(self, ctx: CollectContext, q: GdeltQuery, url: str) -> list[dict] | None:
        for attempt in (1, 2):
            doc = ctx.fetch(url, store=False, accept_status=(200, 429))
            try:
                if doc.status_code == 429:
                    raise GdeltQueryError(THROTTLE_TEXT)
                return parse_response(doc.content)
            except GdeltQueryError as exc:
                if THROTTLE_TEXT in str(exc).lower() and attempt == 1:
                    time.sleep(15)
                    continue
                ctx.warn(f"GDELT, ricerca «{q.label}» rifiutata: {exc}")
                return None
        return None
