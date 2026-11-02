"""Honey news from RSS / Atom feeds.

Every feed in `FEEDS` becomes its own `Collector` subclass (and therefore its own row on
the "Fonti" page, with its own schedule, run history and freshness). Items are parsed with
feedparser from the bytes downloaded by `ctx.fetch` (so every raw feed is archived), then
handed to `services.news.ingest_article` through `ctx.add_news`, which applies the honey
relevance gate, de-duplication, tagging and scoring.

Feed families
-------------
* Google News RSS search (`news.google.com/rss/search?q=...&hl=..&gl=..&ceid=..`). The
  endpoint is public but not officially documented by Google; the format below
  (title "Headline - Outlet", `<source url=..>Outlet</source>`, description holding an
  `<a href>` plus the outlet name, links pointing at `news.google.com/rss/articles/...`) is
  the one widely documented by feed-reader vendors. We never follow the Google redirect:
  the publisher URL is used only when the feed carries it (see
  `services.news.google_news_real_url`). `when:7d` inside `q` limits results to the last
  week (documented search operator).
* Trade press / industry / official feeds (WordPress-style RSS 2.0 or Atom). General
  feeds (food safety, agriculture policy) are filtered by the honey gate, so most of their
  items are discarded by design.

URL verification status (this module was written in a sandbox without internet access;
see `verified` on each FeedSpec):
* verified    - URL format confirmed from the publisher's own documentation/page.
* listed      - URL listed by a third-party feed directory (Feedspot / Feeder).
* unverified  - inferred from the site's platform (e.g. WordPress `/feed/`, Arc XP
                `/arc/outboundfeeds/rss/`). If the first live run fails with HTTP 404 the
                source shows "failed" on the Fonti page and can be disabled there.

Not included (no public feed found): Osservatorio Nazionale Miele / Informamiele (news are
covered by the Italian Google News queries), EU DG AGRI newsroom (newsletters only; EU
policy is covered by the European Parliament AGRI feed and the EN-EU Google News query),
USDA AMS (honey report is collected by the USDA collector, not as news).
"""
from __future__ import annotations

import calendar
import re
import types
from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import feedparser
from sqlalchemy.exc import IntegrityError

from ..enums import Reliability, SourceKind
from ..models import utcnow
from ..services import news as news_service
from .base import CollectContext, Collector, CollectorError

FEED_ACCEPT = "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.9, */*;q=0.5"
DEFAULT_MAX_ENTRY_AGE_DAYS = 365   # older items in a feed (archives) are skipped


@dataclass(frozen=True)
class FeedSpec:
    key: str                     # Source.key (unique, <= 60 chars)
    name: str                    # shown on the Fonti page (Italian)
    publisher: str               # who publishes the feed
    url: str
    language: str                # ISO 639-1 of the feed content
    reliability: Reliability     # trade_press | aggregator | official | industry
    country: str | None          # ISO3 of the publisher's country (None = international)
    homepage: str
    family: str = "rss"          # "google_news" | "rss"
    expected_max_age_days: int | None = 7
    expected_update: str = "Controllato ogni 3 ore; nuovi articoli quando l'editore pubblica"
    terms_note: str = ""
    verified: str = "unverified"  # verified | listed | unverified
    max_entry_age_days: int = DEFAULT_MAX_ENTRY_AGE_DAYS


# ---------------------------------------------------------------------------
# Feed list
# ---------------------------------------------------------------------------

_GN_TERMS = (
    "DISATTIVATO DI DEFAULT: Google indica che i feed di Google News sono destinati a lettori di feed per uso "
    "personale e non commerciale. Attivarlo solo dopo aver valutato questi termini per l'uso aziendale. "
    "Aggregatore Google News: titoli e link agli articoli originali, il testo resta proprietà degli editori. "
    "Endpoint RSS pubblico ma non documentato ufficialmente da Google (può cambiare senza preavviso). "
    "Si legge solo il titolo e l'estratto del feed; l'articolo si apre sul sito dell'editore."
)
_EDITIONS = {
    # language -> (hl, gl, ceid, label)
    "en": ("en-US", "US", "US:en", "inglese, edizione USA"),
    "en-GB": ("en-GB", "GB", "GB:en", "inglese, edizione Regno Unito"),
    "it": ("it", "IT", "IT:it", "italiano"),
    "es-AR": ("es-419", "AR", "AR:es-419", "spagnolo, edizione Argentina"),
    "es-ES": ("es", "ES", "ES:es", "spagnolo, edizione Spagna"),
    "pt-BR": ("pt-BR", "BR", "BR:pt-419", "portoghese, edizione Brasile"),
    "de": ("de", "DE", "DE:de", "tedesco"),
}


def google_news_url(query: str, edition: str, *, window: str = "7d") -> str:
    hl, gl, ceid, _ = _EDITIONS[edition]
    q = f"{query} when:{window}" if window else query
    return f"https://news.google.com/rss/search?q={quote_plus(q)}&hl={hl}&gl={gl}&ceid={ceid}"


def _gn(key: str, label: str, query: str, edition: str, *, max_age: int = 5) -> FeedSpec:
    hl, gl, ceid, ed_label = _EDITIONS[edition]
    return FeedSpec(
        key=f"news_gn_{key}",
        name=f"Google News · {label} ({ed_label})",
        publisher="Google News (aggregatore)",
        url=google_news_url(query, edition),
        language=edition.split("-")[0],
        reliability=Reliability.AGGREGATOR,
        country=None,
        homepage=f"https://news.google.com/search?q={quote_plus(query)}&hl={hl}&gl={gl}&ceid={ceid}",
        family="google_news",
        expected_max_age_days=max_age,
        expected_update=f"Ricerca «{query}» controllata ogni 3 ore (articoli degli ultimi 7 giorni)",
        terms_note=_GN_TERMS,
        verified="verified",
        max_entry_age_days=30,
    )


FEEDS: list[FeedSpec] = [
    # --- Google News searches targeted at the honey TRADE ------------------------------
    _gn("en_honey_prices", "prezzi del miele", '"honey prices" OR "honey price"', "en"),
    _gn("en_honey_trade", "export e import di miele", '"honey exports" OR "honey imports" OR "honey shipments"', "en"),
    _gn("en_honey_tariffs", "dazi e antidumping sul miele",
        'honey (tariff OR tariffs OR "anti-dumping" OR antidumping OR countervailing)', "en", max_age=10),
    _gn("en_honey_fraud", "miele adulterato e frodi",
        'honey (adulteration OR adulterated OR "fake honey" OR "honey fraud")', "en", max_age=10),
    _gn("en_honey_harvest", "raccolto e produzione di miele",
        'honey (harvest OR "honey production" OR "honey crop") beekeepers', "en", max_age=7),
    _gn("en_eu_honey", "miele e politiche UE",
        'honey (EU OR "European Commission" OR "Breakfast Directive") (imports OR labelling OR regulation)',
        "en-GB", max_age=14),
    _gn("it_prezzo_miele", "prezzo del miele", '"prezzo del miele" OR "prezzi del miele" OR "prezzo miele"', "it",
        max_age=10),
    _gn("it_miele_import", "importazioni ed export di miele",
        'miele (importazioni OR importazione OR esportazioni OR export OR dazi)', "it", max_age=7),
    _gn("it_miele_produzione", "produzione di miele in Italia",
        'miele (produzione OR raccolto OR apicoltori OR "miele falso")', "it", max_age=5),
    _gn("es_precio_miel", "precio de la miel", '"precio de la miel" OR "precios de la miel" OR "precio miel"', "es-AR",
        max_age=10),
    _gn("es_miel_exportacion", "exportación de miel",
        'miel (exportación OR exportaciones OR exportadores)', "es-AR", max_age=7),
    _gn("es_miel_argentina", "miel argentina exportaciones", 'miel argentina exportaciones', "es-AR", max_age=10),
    _gn("es_miel_espana", "miel en España (importaciones, etiquetado)",
        'miel (importaciones OR etiquetado OR "miel china" OR apicultores)', "es-ES", max_age=7),
    _gn("pt_mel_exportacao", "exportação de mel (Brasile)",
        '"exportação de mel" OR "exportações de mel" OR "preço do mel" OR "mel brasileiro"', "pt-BR", max_age=14),
    _gn("de_honig_markt", "mercato del miele in Germania",
        'Honig (Preis OR Preise OR Import OR Ernte OR Imker)', "de", max_age=7),

    # --- Trade press ----------------------------------------------------------------------
    FeedSpec(
        key="news_bee_culture", name="Bee Culture – The Magazine of American Beekeeping",
        publisher="Bee Culture (Root Publications)", url="https://www.beeculture.com/feed/", language="en",
        reliability=Reliability.TRADE_PRESS, country="USA", homepage="https://www.beeculture.com/",
        expected_max_age_days=14, expected_update="Notizie e «Catch the Buzz» più volte a settimana; rivista mensile",
        terms_note="Feed RSS dell'editore (titolo, estratto e link). Il testo completo resta sul sito dell'editore.",
        verified="listed",  # Feedspot beekeeping directory lists beeculture.com/feed (WordPress)
    ),
    FeedSpec(
        key="news_american_bee_journal", name="American Bee Journal",
        publisher="Dadant & Sons", url="https://americanbeejournal.com/feed/", language="en",
        reliability=Reliability.TRADE_PRESS, country="USA", homepage="https://americanbeejournal.com/",
        expected_max_age_days=45, expected_update="Rivista mensile; articoli online irregolari",
        terms_note="Feed RSS dell'editore (titolo, estratto e link).",
        verified="unverified",  # WordPress site (?p= permalinks): standard /feed/ endpoint assumed
    ),
    FeedSpec(
        key="news_apimondia", name="Apimondia – notizie",
        publisher="Apimondia (International Federation of Beekeepers' Associations)",
        url="https://www.apimondia.org/feed/", language="en", reliability=Reliability.INDUSTRY, country=None,
        homepage="https://www.apimondia.org/", expected_max_age_days=60,
        expected_update="Comunicati irregolari (alcuni al mese): congressi, frodi, standard",
        terms_note="Feed RSS della federazione internazionale degli apicoltori.",
        verified="unverified",  # WordPress site (/category/news/, dated permalinks): /feed/ assumed
    ),
    FeedSpec(
        key="news_food_safety_news", name="Food Safety News (filtrato: solo miele)",
        publisher="Food Safety News (Marler Clark)", url="https://www.foodsafetynews.com/feed/", language="en",
        reliability=Reliability.TRADE_PRESS, country="USA", homepage="https://www.foodsafetynews.com/",
        expected_max_age_days=120,
        expected_update="Notizie quotidiane sulla sicurezza alimentare; quelle sul miele sono rare",
        terms_note="Feed generale: si conservano solo gli articoli che parlano di miele o apicoltura.",
        verified="verified",  # listed on foodsafetynews.com/subscribe-via-rss-feed/
    ),
    FeedSpec(
        key="news_foodnavigator", name="FoodNavigator (filtrato: solo miele)",
        publisher="FoodNavigator (William Reed)", url="https://www.foodnavigator.com/arc/outboundfeeds/rss/",
        language="en", reliability=Reliability.TRADE_PRESS, country=None, homepage="https://www.foodnavigator.com/",
        expected_max_age_days=120,
        expected_update="Notizie quotidiane sull'industria alimentare europea; quelle sul miele sono rare",
        terms_note="Feed generale: si conservano solo gli articoli che parlano di miele o apicoltura.",
        verified="unverified",  # Arc XP site (sitemaps under /arc/outboundfeeds/); standard Arc RSS path assumed
    ),
    # --- Official -----------------------------------------------------------------------
    FeedSpec(
        key="news_europarl_agri", name="Parlamento europeo – Commissione Agricoltura (filtrato: solo miele)",
        publisher="European Parliament", url="https://www.europarl.europa.eu/rss/committee/agri/en.xml",
        language="en", reliability=Reliability.OFFICIAL, country=None,
        homepage="https://www.europarl.europa.eu/committees/en/agri/home/highlights",
        expected_max_age_days=None,
        expected_update="Notizie della commissione AGRI più volte a settimana; quelle sul miele sono rare",
        terms_note="Feed ufficiale del Parlamento europeo. Si conservano solo le notizie su miele e apicoltura.",
        verified="listed",  # listed by the Feeder directory for the AGRI committee page
    ),
]


# ---------------------------------------------------------------------------
# Parsing (pure functions)
# ---------------------------------------------------------------------------


def _struct_to_dt(st) -> datetime | None:
    if not st:
        return None
    try:
        return datetime.fromtimestamp(calendar.timegm(st), tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OverflowError):
        return None


def entry_image(entry: dict) -> str | None:
    """media:content -> media:thumbnail -> enclosure -> first <img> in the summary/content."""
    for m in entry.get("media_content") or []:
        medium, mtype = (m.get("medium") or ""), (m.get("type") or "")
        if (medium in ("", "image") and not mtype) or medium == "image" or mtype.startswith("image/"):
            url = news_service.normalise_image_url(m.get("url"))
            if url:
                return url
    for m in entry.get("media_thumbnail") or []:
        url = news_service.normalise_image_url(m.get("url"))
        if url:
            return url
    for enc in list(entry.get("enclosures") or []) + [
        lk for lk in (entry.get("links") or []) if lk.get("rel") == "enclosure"
    ]:
        if (enc.get("type") or "").startswith("image/"):
            url = news_service.normalise_image_url(enc.get("href") or enc.get("url"))
            if url:
                return url
    for html in [entry.get("summary")] + [c.get("value") for c in entry.get("content") or []]:
        url = news_service.first_image(html)
        if url:
            return url
    return None


def _entry_link(entry: dict) -> str | None:
    link = entry.get("link")
    if not link:
        for lk in entry.get("links") or []:
            if lk.get("rel", "alternate") == "alternate" and lk.get("href"):
                link = lk["href"]
                break
    if not link:
        guid = entry.get("id") or ""
        if guid.startswith(("http://", "https://")) and entry.get("guidislink", True):
            link = guid
    return link


def _google_snippet(description: str | None) -> str | None:
    """Google News descriptions are a link to the article (+ outlet name), sometimes a list
    of related headlines from other outlets. Neither is an excerpt: keep only real text
    outside links."""
    if not description:
        return None
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(description, "html.parser")
    for tag in soup.find_all(["a", "ol", "ul"]):
        tag.decompose()
    for tag in soup.find_all("font"):
        # current format: <font color="#6f6f6f">Outlet</font>; the older format put the
        # excerpt itself in <font size="-1">, which we keep
        if len(tag.get_text(" ", strip=True).split()) < 8:
            tag.decompose()
    text = news_service.strip_html(str(soup))
    return text if len(re.sub(r"[\W_]+", "", text)) >= 40 else None


def parse_feed(content: bytes, spec: FeedSpec | None = None) -> tuple[list[dict], list[str]]:
    """Parse RSS 2.0 / RSS 1.0 / Atom bytes into ingestable items.

    Returns (items, warnings). Raises CollectorError when the document is not a feed at all.
    Each item: {url, title, published_at, snippet, image_url, publisher, language}.
    """
    parsed = feedparser.parse(content)
    warnings: list[str] = []
    entries = parsed.get("entries") or []
    if parsed.get("bozo"):
        exc = parsed.get("bozo_exception")
        benign = isinstance(exc, (feedparser.CharacterEncodingOverride, feedparser.NonXMLContentType))
        if not entries:
            version = parsed.get("version") or ""
            head = content[:400].lower()
            if b"<html" in head or b"<!doctype html" in head:
                raise CollectorError("La risposta non è un feed RSS/Atom (pagina HTML ricevuta)")
            if not version:
                raise CollectorError(f"Feed non leggibile: {type(exc).__name__}: {exc}"[:300])
        elif not benign:
            warnings.append(f"Feed malformato ma leggibile ({type(exc).__name__}): {str(exc)[:160]}")
    if not entries and not parsed.get("version") and not parsed.get("feed"):
        raise CollectorError("Il documento non contiene un feed RSS/Atom")

    feed_lang = news_service.normalise_language((parsed.get("feed") or {}).get("language"))
    family = spec.family if spec else ("google_news" if b"news.google.com" in content[:3000] else "rss")
    default_publisher = spec.publisher if spec and family != "google_news" else None
    items: list[dict] = []
    for i, e in enumerate(entries):
        link = _entry_link(e)
        title = e.get("title") or ""
        if not link or not title.strip():
            warnings.append(f"Voce {i + 1} senza titolo o link: ignorata")
            continue
        summary = e.get("summary") or ""
        if not summary and e.get("content"):
            summary = e["content"][0].get("value") or ""
        published = _struct_to_dt(e.get("published_parsed") or e.get("updated_parsed") or e.get("created_parsed"))
        src = e.get("source") or {}
        if family == "google_news":
            publisher = (src.get("title") or "").strip() or None
            url = news_service.google_news_real_url(link, summary)
            snippet = _google_snippet(summary)
            if publisher:
                title = news_service.strip_publisher_suffix(news_service.strip_html(title), publisher)
            elif " - " in title:
                # "Headline - Outlet" without a <source> element
                head, _, tail = news_service.strip_html(title).rpartition(" - ")
                if head and 0 < len(tail.split()) <= 6:
                    title, publisher = head, tail
        else:
            publisher = (src.get("title") or "").strip() or default_publisher
            url = link
            snippet = summary
        items.append({
            "url": url,
            "title": title,
            "published_at": published,
            "snippet": snippet or None,
            "image_url": entry_image(e),
            "publisher": publisher,
            "language": news_service.normalise_language(e.get("language")) or feed_lang
            or (spec.language if spec else None),
        })
    return items, warnings


# ---------------------------------------------------------------------------
# Collectors
# ---------------------------------------------------------------------------


class FeedCollector(Collector):
    """Base for one RSS/Atom feed. Concrete classes are generated from FEEDS below."""

    kind = SourceKind.RSS
    category = "news"
    order = 80

    @property
    @abstractmethod
    def feed(self) -> FeedSpec:
        ...

    def collect(self, ctx: CollectContext) -> None:
        spec = self.feed
        doc = ctx.fetch(spec.url, headers={"Accept": FEED_ACCEPT}, title=spec.name)
        if doc.unchanged and not ctx.force:
            return
        items, warnings = parse_feed(doc.content, spec)
        for w in warnings[:5]:
            ctx.warn(w)
        if len(warnings) > 5:
            ctx.warn(f"... e altri {len(warnings) - 5} avvisi di lettura del feed")
        oldest = utcnow() - timedelta(days=spec.max_entry_age_days)
        # The raw feed is committed first, then each article on its own: a failure on one
        # item (e.g. the same article stored concurrently by another feed) loses nothing else.
        ctx.checkpoint()
        for item in items:
            if item["published_at"] is not None and item["published_at"] < oldest:
                ctx.counters.count("filtered")  # archive item, not news
                continue
            try:
                ctx.add_news(**item)
                ctx.checkpoint()
            except IntegrityError:
                ctx.session.rollback()
                ctx.counters.new = ctx.counters.committed_new
                ctx.counters.count("unchanged")  # stored meanwhile by a concurrent run
            except Exception as exc:  # noqa: BLE001 - one bad item must not lose the batch
                ctx.session.rollback()
                ctx.counters.new = ctx.counters.committed_new
                ctx.warn(f"Articolo non salvato ({str(item.get('url', ''))[:120]}): {type(exc).__name__}: {exc}"[:400])


def _schedule(index: int) -> dict:
    """Every 3 hours, staggered: feeds are spread over the 3-hour cycle and the hour."""
    return {"trigger": "cron", "hour": f"{index % 3}-23/3", "minute": (7 + 11 * index) % 60}


def _make_collector(spec: FeedSpec, index: int) -> type[FeedCollector]:
    attrs = {
        "__module__": __name__,
        "__doc__": f"News feed: {spec.name} ({spec.url}) [URL {spec.verified}]",
        "key": spec.key,
        "name": spec.name,
        "publisher": spec.publisher,
        "homepage": spec.homepage,
        "reliability": spec.reliability,
        "country_iso3": spec.country,
        "language": spec.language,
        "expected_update": spec.expected_update,
        "expected_max_age_days": spec.expected_max_age_days,
        "terms_note": spec.terms_note,
        "schedule": _schedule(index),
        # Google News RSS is offered for personal, non-commercial use: opt-in from the Fonti page.
        "default_enabled": spec.family != "google_news",
        "feed": property(lambda self, _s=spec: _s),
    }
    name = "NewsFeed_" + re.sub(r"\W", "_", spec.key)
    return types.new_class(name, (FeedCollector,), {}, lambda ns: ns.update(attrs))


FEED_COLLECTORS: dict[str, type[FeedCollector]] = {}
for _i, _spec in enumerate(FEEDS):
    _cls = _make_collector(_spec, _i)
    globals()[_cls.__name__] = _cls
    FEED_COLLECTORS[_spec.key] = _cls
del _i, _spec, _cls


def feed_spec(key: str) -> FeedSpec | None:
    return next((f for f in FEEDS if f.key == key), None)
