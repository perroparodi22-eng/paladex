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

URL verification status (this module was first written in a sandbox without internet
access; see `verified` on each FeedSpec):
* verified    - URL format confirmed from the publisher's own documentation/page.
* listed      - URL listed by a third-party feed directory (Feedspot / Feeder).
* unverified  - inferred from the site's platform (e.g. WordPress `/feed/`, Arc XP
                `/arc/outboundfeeds/rss/`). If the first live run fails with HTTP 404 the
                source shows "failed" on the Fonti page and can be disabled there.

Live check (2026-11-04): Bee Culture, American Bee Journal and Apimondia return real
WordPress RSS 2.0 items; Food Safety News and FoodNavigator parse but rarely carry honey
items (the honey gate discards the rest, by design); the European Commission DG AGRI news
feed returns RSS 2.0 (30 items). Real captures are in tests/fixtures/news/real_*.xml.

Not included: Osservatorio Nazionale Miele / Informamiele (no public feed; news are covered
by the Italian Google News queries); European Parliament RSS (www.europarl.europa.eu/rss/...,
e.g. the AGRI committee feed listed by Feeder): every europarl.europa.eu page, the home page
included, answered HTTP 403 from its CloudFront firewall to our requests on 2026-11-04, so
the feed could not be verified and was replaced by the Commission's DG AGRI news feed; USDA
AMS (honey report is collected by the USDA collector, not as news).
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
ARCHIVE_ENTRY_AGE_DAYS = 3650      # feeds marked `archive`: the latest honey articles, up to ten years old


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
    name_en: str = ""            # English name ("" = `name`, already English)
    expected_max_age_days: int | None = 7
    expected_update: str = "Controllato ogni 3 ore; nuovi articoli quando l'editore pubblica"
    expected_update_en: str = "Checked every 3 hours; new articles whenever the publisher posts them"
    terms_note: str = ""
    verified: str = "unverified"  # verified | listed | unverified
    max_entry_age_days: int = DEFAULT_MAX_ENTRY_AGE_DAYS
    # National honey-sector feed: its items are tagged with `country` even when the text does not
    # name it (an Argentine farm paper writes "la miel", not "la miel argentina").
    home_tag: bool = False
    # A worldwide search about one country: only the items whose own text names `country` are kept
    # (a search engine also returns stories that merely mention the country somewhere in the article).
    require_country: bool = False
    # Google News searches are opt-in (see _GN_TERMS); True for the ones the owner asked for.
    on_by_default: bool = False


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
    "en-IN": ("en-IN", "IN", "IN:en", "inglese, edizione India"),
    "vi": ("vi", "VN", "VN:vi", "vietnamita"),
    "zh": ("zh-CN", "CN", "CN:zh-Hans", "cinese"),
    "th": ("th", "TH", "TH:th", "thailandese"),
    "ja": ("ja", "JP", "JP:ja", "giapponese"),
}
_EDITIONS_EN = {
    "en": "English, US edition", "en-GB": "English, UK edition", "it": "Italian",
    "es-AR": "Spanish, Argentina edition", "es-ES": "Spanish, Spain edition",
    "pt-BR": "Portuguese, Brazil edition", "de": "German",
    "en-IN": "English, India edition", "vi": "Vietnamese", "zh": "Chinese", "th": "Thai", "ja": "Japanese",
}


# Negative terms appended to every Google News search, by language: known noise named in
# docs/research/news.json (Miele appliances, Honey Singh, PayPal's "Honey" extension, "luna de
# miel"). The same exclusions as the GDELT queries; the honey gate still filters what slips through.
_GN_EXCLUDE = {
    "it": "-lavatrice -lavastoviglie -elettrodomestici",
    "en": '-"honey singh" -paypal',
    "es": '-"luna de miel"',
    "de": "-Miele",
}


def google_news_url(query: str, edition: str, *, window: str = "7d") -> str:
    hl, gl, ceid, _ = _EDITIONS[edition]
    q = f"{query} when:{window}" if window else query
    return f"https://news.google.com/rss/search?q={quote_plus(q)}&hl={hl}&gl={gl}&ceid={ceid}"


def _gn(key: str, label: str, query: str, edition: str, *, max_age: int | None = 5, label_en: str = "",
        window: str = "7d") -> FeedSpec:
    hl, gl, ceid, ed_label = _EDITIONS[edition]
    exclude = _GN_EXCLUDE.get(edition.split("-")[0])
    if exclude:
        query = f"{query} {exclude}"
    return FeedSpec(
        key=f"news_gn_{key}",
        name=f"Google News · {label} ({ed_label})",
        name_en=f"Google News · {label_en} ({_EDITIONS_EN[edition]})" if label_en else "",
        publisher="Google News (aggregatore)",
        url=google_news_url(query, edition, window=window),
        language=edition.split("-")[0],
        reliability=Reliability.AGGREGATOR,
        country=None,
        homepage=f"https://news.google.com/search?q={quote_plus(query)}&hl={hl}&gl={gl}&ceid={ceid}",
        family="google_news",
        expected_max_age_days=max_age,
        expected_update=f"Ricerca «{query}» controllata ogni 3 ore (articoli degli ultimi 7 giorni)",
        expected_update_en=f"Search «{query}» checked every 3 hours (articles from the last 7 days)",
        terms_note=_GN_TERMS,
        verified="verified",
        max_entry_age_days=30,
    )


FEEDS: list[FeedSpec] = [
    # --- Google News searches targeted at the honey TRADE ------------------------------
    _gn("en_honey_prices", "prezzi del miele", '"honey prices" OR "honey price"', "en", label_en="honey prices"),
    _gn("en_honey_trade", "export e import di miele", '"honey exports" OR "honey imports" OR "honey shipments"', "en",
        label_en="honey exports and imports"),
    _gn("en_honey_tariffs", "dazi e antidumping sul miele",
        'honey (tariff OR tariffs OR "anti-dumping" OR antidumping OR countervailing)', "en", max_age=10,
        label_en="honey tariffs and anti-dumping"),
    _gn("en_honey_fraud", "miele adulterato e frodi",
        'honey (adulteration OR adulterated OR "fake honey" OR "honey fraud")', "en", max_age=10,
        label_en="honey adulteration and fraud"),
    _gn("en_honey_harvest", "raccolto e produzione di miele",
        'honey (harvest OR "honey production" OR "honey crop") beekeepers', "en", max_age=7,
        label_en="honey harvest and production"),
    _gn("en_eu_honey", "miele e politiche UE",
        'honey (EU OR "European Commission" OR "Breakfast Directive") (imports OR labelling OR regulation)',
        "en-GB", max_age=14, label_en="honey and EU policy"),
    _gn("it_prezzo_miele", "prezzo del miele", '"prezzo del miele" OR "prezzi del miele" OR "prezzo miele"', "it",
        max_age=10, label_en="honey price"),
    _gn("it_miele_import", "importazioni ed export di miele",
        'miele (importazioni OR importazione OR esportazioni OR export OR dazi)', "it", max_age=7,
        label_en="honey imports and exports"),
    _gn("it_miele_produzione", "produzione di miele in Italia",
        'miele (produzione OR raccolto OR apicoltori OR "miele falso")', "it", max_age=5,
        label_en="honey production in Italy"),
    _gn("es_precio_miel", "precio de la miel", '"precio de la miel" OR "precios de la miel" OR "precio miel"', "es-AR",
        max_age=10, label_en="honey price"),
    _gn("es_miel_exportacion", "exportación de miel",
        'miel (exportación OR exportaciones OR exportadores)', "es-AR", max_age=7, label_en="honey exports"),
    _gn("es_miel_argentina", "miel argentina exportaciones", 'miel argentina exportaciones', "es-AR", max_age=10,
        label_en="Argentine honey exports"),
    _gn("es_miel_espana", "miel en España (importaciones, etiquetado)",
        'miel (importaciones OR etiquetado OR "miel china" OR apicultores)', "es-ES", max_age=7,
        label_en="honey in Spain (imports, labelling)"),
    _gn("pt_mel_exportacao", "exportação de mel (Brasile)",
        '"exportação de mel" OR "exportações de mel" OR "preço do mel" OR "mel brasileiro"', "pt-BR", max_age=14,
        label_en="honey exports (Brazil)"),
    _gn("de_honig_markt", "mercato del miele in Germania",
        'Honig (Preis OR Preise OR Import OR Ernte OR Imker)', "de", max_age=7, label_en="honey market in Germany"),

    # --- Trade press ----------------------------------------------------------------------
    FeedSpec(
        key="news_bee_culture", name="Bee Culture – The Magazine of American Beekeeping",
        publisher="Bee Culture (Root Publications)", url="https://beeculture.com/feed/", language="en",
        reliability=Reliability.TRADE_PRESS, country="USA", homepage="https://beeculture.com/",
        expected_max_age_days=14, expected_update="Notizie e «Catch the Buzz» più volte a settimana; rivista mensile",
        expected_update_en="News and «Catch the Buzz» several times a week; monthly magazine",
        terms_note="Feed RSS dell'editore (titolo, estratto e link). Il testo completo resta sul sito dell'editore.",
        verified="verified",  # fetched live 2026-11-04: WordPress RSS 2.0 (www. redirects here)
    ),
    FeedSpec(
        key="news_american_bee_journal", name="American Bee Journal",
        publisher="Dadant & Sons", url="https://americanbeejournal.com/feed/", language="en",
        reliability=Reliability.TRADE_PRESS, country="USA", homepage="https://americanbeejournal.com/",
        expected_max_age_days=45, expected_update="Rivista mensile; articoli online irregolari",
        expected_update_en="Monthly magazine; online articles at irregular intervals",
        terms_note="Feed RSS dell'editore (titolo, estratto e link).",
        verified="verified",  # fetched live 2026-11-04: WordPress RSS 2.0, 10 items
    ),
    FeedSpec(
        key="news_apimondia", name="Apimondia – notizie", name_en="Apimondia – news",
        publisher="Apimondia (International Federation of Beekeepers' Associations)",
        url="https://apimondia.org/feed/", language="en", reliability=Reliability.INDUSTRY, country=None,
        homepage="https://apimondia.org/", expected_max_age_days=60,
        expected_update="Comunicati irregolari (alcuni al mese): congressi, frodi, standard",
        expected_update_en="Irregular press releases (a few a month): congresses, fraud, standards",
        terms_note="Feed RSS della federazione internazionale degli apicoltori.",
        verified="verified",  # fetched live 2026-11-04: WordPress RSS 2.0 (www. redirects here)
    ),
    FeedSpec(
        key="news_food_safety_news", name="Food Safety News (filtrato: solo miele)",
        name_en="Food Safety News (filtered: honey only)",
        publisher="Food Safety News (Marler Clark)", url="https://www.foodsafetynews.com/feed/", language="en",
        reliability=Reliability.TRADE_PRESS, country="USA", homepage="https://www.foodsafetynews.com/",
        expected_max_age_days=120,
        expected_update="Notizie quotidiane sulla sicurezza alimentare; quelle sul miele sono rare",
        expected_update_en="Daily food-safety news; items about honey are rare",
        terms_note="Feed generale: si conservano solo gli articoli che parlano di miele o apicoltura.",
        verified="verified",  # listed on foodsafetynews.com/subscribe-via-rss-feed/; fetched live 2026-11-04
    ),
    FeedSpec(
        key="news_foodnavigator", name="FoodNavigator (filtrato: solo miele)",
        name_en="FoodNavigator (filtered: honey only)",
        publisher="FoodNavigator (William Reed)", url="https://www.foodnavigator.com/arc/outboundfeeds/rss/",
        language="en", reliability=Reliability.TRADE_PRESS, country=None, homepage="https://www.foodnavigator.com/",
        expected_max_age_days=120,
        expected_update="Notizie quotidiane sull'industria alimentare europea; quelle sul miele sono rare",
        expected_update_en="Daily news on the European food industry; items about honey are rare",
        terms_note="Feed generale: si conservano solo gli articoli che parlano di miele o apicoltura.",
        verified="verified",  # Arc XP outbound RSS; fetched live 2026-11-04 (20 items, none about honey)
    ),
    # --- Official -----------------------------------------------------------------------
    FeedSpec(
        key="news_ec_agri",
        name="Commissione europea – DG Agricoltura, notizie (filtrato: solo miele)",
        name_en="European Commission – DG Agriculture and Rural Development, news (filtered: honey only)",
        publisher="European Commission – DG Agriculture and Rural Development",
        url="https://agriculture.ec.europa.eu/node/2/rss_en",
        language="en", reliability=Reliability.OFFICIAL, country=None,
        homepage="https://agriculture.ec.europa.eu/media/news_en",
        expected_max_age_days=None,
        expected_update="Notizie della DG Agricoltura più volte a settimana; quelle sul miele sono rare",
        expected_update_en="DG AGRI news several times a week; items about honey are rare",
        terms_note=("Feed ufficiale della Commissione europea (© Unione europea, riutilizzo consentito con "
                    "citazione della fonte). Si conservano solo le notizie su miele e apicoltura."),
        # RSS link of the official news page (agriculture.ec.europa.eu/media/news_en -> /node/2/rss_en);
        # fetched live on 2026-11-04: RSS 2.0, 30 items (tests/fixtures/news/real_ec_agri_news.xml).
        verified="verified",
    ),
]


# ---------------------------------------------------------------------------
# Country feeds: one or two per honey country
# ---------------------------------------------------------------------------
#
# The publisher's own RSS feed of its honey section: a tag feed ("/tag/miel/feed/"), the site's
# search feed for the word honey ("?s=miel&feed=rss2", a standard WordPress feed) or, for a
# sector association, its whole news feed. Where a country has no honey-specific feed, the
# business / farm feed of a national outlet is read and the honey gate keeps the rare honey item.
# Every URL below was fetched on 2026-11-10 with the application's own User-Agent and returned a
# real feed; sites that answered with an anti-bot page or HTTP 403 were left out (among them
# Canal Rural, Agroklub, SPOS, Fermer.bg, Agro24, RNZ, The Western Producer, Euractiv).
# Items carry the feed's country as a tag (`home_tag`).
#
# All of Europe (the 39 countries of the reference region "Europe") was added the same way on
# 10 Nov 2026: the national beekeepers' association or a beekeeping portal where its feed answered,
# otherwise a national farm or business paper filtered by the honey gate. Left out because they
# answered with an anti-bot page or HTTP 403: Agriland search and That's Farming (Ireland), Boerderij
# and Foodlog (Netherlands), Zemědělec search (Czechia), the Slovak beekeepers' union, Agroklub
# (Croatia), Agrotim (North Macedonia), Monitor (Albania), Sinor (Bulgaria), Times of Malta,
# in-cyprus, Luxemburger Wort, Agroinvestor (Russia); VILT (Belgium) answers with 1,665 items per
# request and was left out as too heavy.

_KINDS = {
    # kind -> (Italian, English) description of what is read
    "tag": ("Sezione miele del sito (feed RSS dell'editore)", "The site's honey section (publisher's RSS feed)"),
    "search": ("Articoli del sito che citano il miele (feed RSS di ricerca dell'editore)",
               "The site's articles mentioning honey (publisher's search RSS feed)"),
    "association": ("Notizie dell'associazione di settore (feed RSS)", "News of the sector association (RSS feed)"),
    "sector": ("Portale di apicoltura (feed RSS dell'editore)", "Beekeeping portal (publisher's RSS feed)"),
    "general": ("Feed generale: si conservano solo gli articoli che parlano di miele o apicoltura",
                "General feed: only the articles about honey or beekeeping are kept"),
}


def _country(key: str, country: str, publisher: str, url: str, homepage: str, language: str, *, kind: str,
             label_it: str, label_en: str, reliability: Reliability = Reliability.TRADE_PRESS,
             publisher_en: str | None = None, archive: bool = False) -> FeedSpec:
    """`archive`: keep the feed's older entries too (ARCHIVE_ENTRY_AGE_DAYS instead of one year). For
    the honey feeds of countries where honey is written about once in a long while (South America,
    owner's request of 10 Nov 2026): the country page then shows the latest article it has, with
    its date, instead of nothing."""
    it, en = _KINDS[kind]
    rare = kind == "general"
    return FeedSpec(
        key=f"news_{key}", name=f"{publisher} – {label_it}", name_en=f"{publisher_en or publisher} – {label_en}",
        publisher=publisher, url=url, language=language, reliability=reliability, country=country,
        homepage=homepage,
        # honey items are irregular everywhere (weeks apart): no "stale" warning for these feeds
        expected_max_age_days=None,
        expected_update=("Controllato ogni 3 ore; le notizie sul miele sono rare" if rare
                         else "Controllato ogni 3 ore; nuovi articoli sul miele quando l'editore li pubblica"),
        expected_update_en=("Checked every 3 hours; honey items are rare" if rare
                            else "Checked every 3 hours; new honey articles whenever the publisher posts them"),
        terms_note=f"{it}. Si leggono titolo, estratto e link; il testo completo resta sul sito dell'editore.",
        verified="verified", home_tag=True,
        max_entry_age_days=ARCHIVE_ENTRY_AGE_DAYS if archive else DEFAULT_MAX_ENTRY_AGE_DAYS,
    )


_IND = Reliability.INDUSTRY
COUNTRY_FEEDS: list[FeedSpec] = [
    # --- South America ------------------------------------------------------------------
    _country("ar_infocampo_miel", "ARG", "Infocampo", "https://www.infocampo.com.ar/tag/miel/feed/",
             "https://www.infocampo.com.ar/tag/miel/", "es", kind="tag", archive=True,
             label_it="miele (Argentina)", label_en="honey (Argentina)"),
    _country("ar_bichos_miel", "ARG", "Bichos de Campo", "https://bichosdecampo.com/tag/miel/feed/",
             "https://bichosdecampo.com/tag/miel/", "es", kind="tag", archive=True,
             label_it="miele (Argentina)", label_en="honey (Argentina)"),
    _country("uy_todoelcampo_miel", "URY", "Todo El Campo", "https://www.todoelcampo.com.uy/?s=miel&feed=rss2",
             "https://www.todoelcampo.com.uy/?s=miel", "es", kind="search", archive=True,
             label_it="miele (Uruguay)", label_en="honey (Uruguay)"),
    _country("br_g1_agro", "BRA", "G1 Agronegócios (Globo)",
             "https://g1.globo.com/dynamo/economia/agronegocios/rss2.xml",
             "https://g1.globo.com/economia/agronegocios/", "pt", kind="general",
             label_it="agroalimentare (Brasile, filtrato: solo miele)",
             label_en="agribusiness (Brazil, filtered: honey only)"),
    _country("cl_portalagro_miel", "CHL", "Portal Agro Chile", "https://www.portalagrochile.cl/tag/miel/feed/",
             "https://www.portalagrochile.cl/tag/miel/", "es", kind="tag", archive=True,
             label_it="miele (Cile)", label_en="honey (Chile)"),
    _country("mx_imagenagro_miel", "MEX", "Imagen Agropecuaria",
             "https://imagenagropecuaria.com/?s=miel&feed=rss2", "https://imagenagropecuaria.com/?s=miel", "es",
             kind="search", label_it="miele (Messico)", label_en="honey (Mexico)"),
    # --- Europe -------------------------------------------------------------------------
    _country("es_agropopular_miel", "ESP", "Agropopular", "https://www.agropopular.com/tag/miel/feed/",
             "https://www.agropopular.com/tag/miel/", "es", kind="tag",
             label_it="miele (Spagna)", label_en="honey (Spain)"),
    _country("es_agroinformacion_miel", "ESP", "Agroinformación",
             "https://agroinformacion.com/?s=miel&feed=rss2", "https://agroinformacion.com/?s=miel", "es",
             kind="search", label_it="miele (Spagna)", label_en="honey (Spain)"),
    _country("it_terraevita_miele", "ITA", "Terra e Vita (Edagricole)",
             "https://terraevita.edagricole.it/tag/miele/feed/", "https://terraevita.edagricole.it/tag/miele/",
             "it", kind="tag", label_it="miele (Italia)", label_en="honey (Italy)",
             publisher_en='"Terra e Vita" (Edagricole)'),
    _country("it_coldiretti_miele", "ITA", "Coldiretti", "https://www.coldiretti.it/tag/miele/feed",
             "https://www.coldiretti.it/tag/miele", "it", kind="tag", reliability=_IND,
             label_it="miele (Italia)", label_en="honey (Italy)"),
    _country("it_unaapi", "ITA", "Unaapi – Unione Nazionale Associazioni Apicoltori Italiani",
             "https://www.unaapi.it/feed/", "https://www.unaapi.it/", "it", kind="association", reliability=_IND,
             label_it="notizie (Italia)", label_en="news (Italy)"),
    _country("fr_unaf", "FRA", "UNAF – Union Nationale de l'Apiculture Française",
             "https://www.unaf-apiculture.info/feed/", "https://www.unaf-apiculture.info/", "fr",
             kind="association", reliability=_IND, label_it="notizie (Francia)", label_en="news (France)"),
    _country("de_imkerbund", "DEU", "Deutscher Imkerbund", "https://deutscherimkerbund.de/feed/",
             "https://deutscherimkerbund.de/", "de", kind="association", reliability=_IND,
             label_it="notizie (Germania)", label_en="news (Germany)"),
    _country("ua_landlord_med", "UKR", "Landlord", "https://landlord.ua/?s=%D0%BC%D0%B5%D0%B4&feed=rss2",
             "https://landlord.ua/?s=%D0%BC%D0%B5%D0%B4", "uk", kind="search",
             label_it="miele (Ucraina)", label_en="honey (Ukraine)"),
    _country("ua_agronews_med", "UKR", "AgroNews.ua", "https://agronews.ua/tag/med/feed/",
             "https://agronews.ua/tag/med/", "uk", kind="tag",
             label_it="miele (Ucraina)", label_en="honey (Ukraine)"),
    _country("hu_magyarmezo_mez", "HUN", "Magyar Mezőgazdaság", "https://magyarmezogazdasag.hu/tag/mez/feed/",
             "https://magyarmezogazdasag.hu/tag/mez/", "hu", kind="tag",
             label_it="miele (Ungheria)", label_en="honey (Hungary)"),
    _country("ro_agroteca_miere", "ROU", "Agroteca", "https://agroteca.ro/?s=miere&feed=rss2",
             "https://agroteca.ro/?s=miere", "ro", kind="search",
             label_it="miele (Romania)", label_en="honey (Romania)"),
    _country("ro_agrobiznes_miere", "ROU", "AgroBiznes", "https://agrobiznes.ro/?s=miere&feed=rss2",
             "https://agrobiznes.ro/?s=miere", "ro", kind="search",
             label_it="miele (Romania)", label_en="honey (Romania)"),
    _country("rs_agropress_med", "SRB", "Agropress", "https://agropress.org.rs/?s=med&feed=rss2",
             "https://agropress.org.rs/?s=med", "sr", kind="search",
             label_it="miele (Serbia)", label_en="honey (Serbia)"),
    _country("rs_agronews_pcelarstvo", "SRB", "AgroNews.rs", "https://www.agronews.rs/tag/pcelarstvo/feed/",
             "https://www.agronews.rs/tag/pcelarstvo/", "sr", kind="tag",
             label_it="apicoltura (Serbia)", label_en="beekeeping (Serbia)"),
    _country("tr_dailysabah_business", "TUR", "Daily Sabah", "https://www.dailysabah.com/rssFeed/business",
             "https://www.dailysabah.com/business", "en", kind="general",
             label_it="economia (Turchia, filtrato: solo miele)", label_en="business (Türkiye, filtered: honey only)"),
    # --- North America and Oceania --------------------------------------------------------
    _country("ca_honeycouncil", "CAN", "Canadian Honey Council", "https://honeycouncil.ca/feed/",
             "https://honeycouncil.ca/", "en", kind="association", reliability=_IND,
             label_it="notizie (Canada)", label_en="news (Canada)"),
    _country("ca_alberta_beekeepers", "CAN", "Alberta Beekeepers Commission",
             "https://www.albertabeekeepers.ca/feed/", "https://www.albertabeekeepers.ca/", "en",
             kind="association", reliability=_IND, label_it="notizie (Canada)", label_en="news (Canada)"),
    _country("nz_farmersweekly_apiculture", "NZL", "Farmers Weekly NZ",
             "https://www.farmersweekly.co.nz/tag/apiculture/feed/",
             "https://www.farmersweekly.co.nz/tag/apiculture/", "en", kind="tag",
             label_it="apicoltura (Nuova Zelanda)", label_en="apiculture (New Zealand)"),
    _country("au_ahbic", "AUS", "Australian Honey Bee Industry Council", "https://honeybee.org.au/feed/",
             "https://honeybee.org.au/", "en", kind="association", reliability=_IND,
             label_it="notizie (Australia)", label_en="news (Australia)"),
    # --- Asia ---------------------------------------------------------------------------
    _country("in_businessline_agri", "IND", "The Hindu BusinessLine",
             "https://www.thehindubusinessline.com/economy/agri-business/feeder/default.rss",
             "https://www.thehindubusinessline.com/economy/agri-business/", "en", kind="general",
             label_it="agroalimentare (India, filtrato: solo miele)",
             label_en="agri-business (India, filtered: honey only)"),
    _country("vn_vietnamplus_business", "VNM", "VietnamPlus (Vietnam News Agency)",
             "https://en.vietnamplus.vn/rss/business-11.rss", "https://en.vietnamplus.vn/business/", "en",
             kind="general", label_it="economia (Vietnam, filtrato: solo miele)",
             label_en="business (Vietnam, filtered: honey only)"),
    _country("cn_ecns", "CHN", "ECNS (China News Service)", "http://www.ecns.cn/rss/rss.xml",
             "http://www.ecns.cn/", "en", kind="general",
             label_it="notizie (Cina, filtrato: solo miele)", label_en="news (China, filtered: honey only)"),
    # --- The rest of South America (10 Nov 2026): all 10 countries of the region ------------------
    # Left out (anti-bot page or HTTP 403): Productiva C&M and the ministry (Paraguay), El Impulso,
    # Últimas Noticias, Efecto Cocuyo (Venezuela), La Hora and El Comercio's search (Ecuador), CNA
    # (Brazil), LR21 and the Sociedad Apícola Uruguaya (Uruguay), Las2orillas (Colombia).
    _country("br_sebrae_mel", "BRA", "Agência Sebrae de Notícias", "https://agenciasebrae.com.br/tag/mel/feed/",
             "https://agenciasebrae.com.br/tag/mel/", "pt", kind="tag", archive=True, reliability=_IND,
             label_it="miele (Brasile)", label_en="honey (Brazil)"),
    _country("cl_portalagro_apicultura", "CHL", "Portal Agro Chile",
             "https://www.portalagrochile.cl/tag/apicultura/feed/", "https://www.portalagrochile.cl/tag/apicultura/",
             "es", kind="tag", archive=True, label_it="apicoltura (Cile)", label_en="beekeeping (Chile)"),
    _country("uy_todoelcampo_apicultura", "URY", "Todo El Campo",
             "https://www.todoelcampo.com.uy/?s=apicultura&feed=rss2", "https://www.todoelcampo.com.uy/?s=apicultura",
             "es", kind="search", archive=True, label_it="apicoltura (Uruguay)", label_en="beekeeping (Uruguay)"),
    # Colombia, Paraguay, Venezuela: honey is rarely in the news. Regional papers' beekeeping searches
    # and the state agencies' are read, and older articles are kept (`archive`), so the country page
    # shows the latest one it has, with its date.
    _country("co_lanacion_apicultura", "COL", "La Nación (Huila)", "https://www.lanacion.com.co/?s=apicultura&feed=rss2",
             "https://www.lanacion.com.co/?s=apicultura", "es", kind="search", archive=True,
             label_it="apicoltura (Colombia)", label_en="beekeeping (Colombia)", publisher_en='"La Nación" (Huila)'),
    _country("co_boyaca7dias_apicultura", "COL", "Boyacá Sie7e Días",
             "https://boyaca7dias.com.co/?s=apicultura&feed=rss2", "https://boyaca7dias.com.co/?s=apicultura", "es",
             kind="search", archive=True, label_it="apicoltura (Colombia)", label_en="beekeeping (Colombia)"),
    _country("co_elcampesino_apicultura", "COL", "El Campesino", "https://www.elcampesino.co/tag/apicultura/feed/",
             "https://www.elcampesino.co/tag/apicultura/", "es", kind="tag", archive=True,
             label_it="apicoltura (Colombia)", label_en="beekeeping (Colombia)"),
    _country("pe_inforegion_miel", "PER", "Inforegión", "https://www.inforegion.pe/?s=miel&feed=rss2",
             "https://www.inforegion.pe/?s=miel", "es", kind="search", archive=True, label_it="miele (Perù)", label_en="honey (Peru)"),
    _country("pe_agroperu_miel", "PER", "Agro Perú Informa", "https://www.agroperu.pe/?s=miel&feed=rss2",
             "https://www.agroperu.pe/?s=miel", "es", kind="search", archive=True, label_it="miele (Perù)", label_en="honey (Peru)"),
    _country("ec_cronica_miel", "ECU", "Crónica (Loja)", "https://cronica.com.ec/?s=miel&feed=rss2",
             "https://cronica.com.ec/?s=miel", "es", kind="search", archive=True, label_it="miele (Ecuador)", label_en="honey (Ecuador)"),
    _country("ec_elnorte_miel", "ECU", "El Norte", "https://www.elnorte.ec/?s=miel&feed=rss2",
             "https://www.elnorte.ec/?s=miel", "es", kind="search", archive=True, label_it="miele (Ecuador)", label_en="honey (Ecuador)"),
    _country("bo_abi_miel", "BOL", "ABI – Agencia Boliviana de Información", "https://abi.bo/?s=miel&feed=rss2",
             "https://abi.bo/?s=miel", "es", kind="search", archive=True, reliability=Reliability.OFFICIAL,
             label_it="miele (Bolivia)", label_en="honey (Bolivia)"),
    _country("bo_publiagro_miel", "BOL", "PubliAgro", "https://publiagro.com.bo/?s=miel&feed=rss2",
             "https://publiagro.com.bo/?s=miel", "es", kind="search", archive=True, label_it="miele (Bolivia)", label_en="honey (Bolivia)"),
    _country("py_ip_apicultura", "PRY", "Agencia IP (Agencia de Información Paraguaya)",
             "https://www.ip.gov.py/ip/?s=apicultura&feed=rss2", "https://www.ip.gov.py/ip/?s=apicultura", "es",
             kind="search", archive=True, reliability=Reliability.OFFICIAL,
             label_it="apicoltura (Paraguay)", label_en="beekeeping (Paraguay)"),
    _country("py_mades_miel", "PRY", "MADES – Ministerio del Ambiente y Desarrollo Sostenible",
             "https://www.mades.gov.py/?s=miel&feed=rss2", "https://www.mades.gov.py/?s=miel", "es", kind="search", archive=True,
             reliability=Reliability.OFFICIAL, label_it="miele (Paraguay)", label_en="honey (Paraguay)"),
    _country("ve_barquisimeto_apicultura", "VEN", "Noticias Barquisimeto",
             "https://www.noticiasbarquisimeto.com/?s=apicultura&feed=rss2",
             "https://www.noticiasbarquisimeto.com/?s=apicultura", "es", kind="search", archive=True,
             label_it="apicoltura (Venezuela)", label_en="beekeeping (Venezuela)"),
    _country("ve_lanacionweb_apicultura", "VEN", "La Nación (Táchira)",
             "https://lanacionweb.com/?s=apicultura&feed=rss2", "https://lanacionweb.com/?s=apicultura", "es",
             kind="search", archive=True, label_it="apicoltura (Venezuela)", label_en="beekeeping (Venezuela)",
             publisher_en='"La Nación" (Táchira)'),
    _country("ve_fedeagro", "VEN", "Fedeagro", "https://fedeagro.org/feed/", "https://fedeagro.org/", "es",
             kind="general", reliability=_IND, label_it="agricoltura (Venezuela, filtrato: solo miele)",
             label_en="farming (Venezuela, filtered: honey only)"),
    # --- The rest of Europe (10 Nov 2026) -------------------------------------------------------
    _country("gb_scottish_beekeepers", "GBR", "Scottish Beekeepers' Association",
             "https://www.scottishbeekeepers.org.uk/feed", "https://www.scottishbeekeepers.org.uk/", "en",
             kind="association", reliability=_IND, label_it="notizie (Regno Unito)", label_en="news (United Kingdom)"),
    _country("gb_farmersguardian", "GBR", "Farmers Guardian", "https://www.farmersguardian.com/feeds/rss",
             "https://www.farmersguardian.com/", "en", kind="general",
             label_it="agricoltura (Regno Unito, filtrato: solo miele)",
             label_en="farming (United Kingdom, filtered: honey only)"),
    _country("ie_fibka", "IRL", "Federation of Irish Beekeepers' Associations", "https://irishbeekeeping.ie/feed/",
             "https://irishbeekeeping.ie/", "en", kind="association", reliability=_IND,
             label_it="notizie (Irlanda)", label_en="news (Ireland)"),
    _country("ie_agriland", "IRL", "Agriland", "https://www.agriland.ie/feed/", "https://www.agriland.ie/", "en",
             kind="general", label_it="agricoltura (Irlanda, filtrato: solo miele)",
             label_en="farming (Ireland, filtered: honey only)"),
    _country("pt_fnap", "PRT", "FNAP – Federação Nacional dos Apicultores de Portugal", "https://fnap.pt/feed/",
             "https://fnap.pt/", "pt", kind="association", reliability=_IND,
             label_it="notizie (Portogallo)", label_en="news (Portugal)"),
    _country("pt_cap", "PRT", "CAP – Confederação dos Agricultores de Portugal", "https://www.cap.pt/feed",
             "https://www.cap.pt/", "pt", kind="general", reliability=_IND,
             label_it="agricoltura (Portogallo, filtrato: solo miele)",
             label_en="farming (Portugal, filtered: honey only)"),
    _country("nl_nbv", "NLD", "Nederlandse Bijenhoudersvereniging (NBV)", "https://www.bijenhouders.nl/feed/",
             "https://www.bijenhouders.nl/", "nl", kind="association", reliability=_IND,
             label_it="notizie (Paesi Bassi)", label_en="news (Netherlands)"),
    _country("nl_bijenstichting", "NLD", "Bijenstichting", "https://www.bijenstichting.nl/feed/",
             "https://www.bijenstichting.nl/", "nl", kind="association", reliability=_IND,
             label_it="notizie (Paesi Bassi)", label_en="news (Netherlands)"),
    _country("be_sillonbelge", "BEL", "Le Sillon Belge", "https://www.sillonbelge.be/rss.xml",
             "https://www.sillonbelge.be/", "fr", kind="general",
             label_it="agricoltura (Belgio, filtrato: solo miele)", label_en="farming (Belgium, filtered: honey only)"),
    _country("be_landbouwleven", "BEL", "Landbouwleven", "https://www.landbouwleven.be/rss.xml",
             "https://www.landbouwleven.be/", "nl", kind="general",
             label_it="agricoltura (Belgio, filtrato: solo miele)", label_en="farming (Belgium, filtered: honey only)"),
    _country("lu_fual", "LUX", "FUAL – Fédération des Unions d'Apiculteurs du Grand-Duché de Luxembourg",
             "https://www.apis.lu/rss", "https://www.apis.lu/", "de", kind="association", reliability=_IND,
             label_it="notizie (Lussemburgo)", label_en="news (Luxembourg)"),
    _country("at_imkereizentrum", "AUT", "OÖ Imkereizentrum (Landesverband für Bienenzucht Oberösterreich)",
             "https://www.imkereizentrum.at/feed/", "https://www.imkereizentrum.at/", "de", kind="association",
             reliability=_IND, label_it="notizie (Austria)", label_en="news (Austria)"),
    _country("at_blickinsland_honig", "AUT", "Blick ins Land", "https://www.blickinsland.at/?s=honig&feed=rss2",
             "https://www.blickinsland.at/?s=honig", "de", kind="search",
             label_it="miele (Austria)", label_en="honey (Austria)"),
    _country("ch_bienen", "CHE", "BienenSchweiz", "https://www.bienen.ch/feed/", "https://www.bienen.ch/", "de",
             kind="association", reliability=_IND, label_it="notizie (Svizzera)", label_en="news (Switzerland)"),
    _country("ch_bienenzeitung", "CHE", "Schweizerische Bienen-Zeitung", "https://www.bienenzeitung.ch/feed/",
             "https://www.bienenzeitung.ch/", "de", kind="sector",
             label_it="notizie (Svizzera)", label_en="news (Switzerland)"),
    _country("pl_portalpszczelarski", "POL", "Portal Pszczelarski", "https://www.portalpszczelarski.pl/rss",
             "https://www.portalpszczelarski.pl/", "pl", kind="sector",
             label_it="notizie (Polonia)", label_en="news (Poland)"),
    _country("pl_agronews_miod", "POL", "AgroNews", "https://agronews.com.pl/?s=mi%C3%B3d&feed=rss2",
             "https://agronews.com.pl/?s=mi%C3%B3d", "pl", kind="search",
             label_it="miele (Polonia)", label_en="honey (Poland)"),
    _country("cz_agroportal24h", "CZE", "Agroportal24h", "https://www.agroportal24h.cz/rss",
             "https://www.agroportal24h.cz/", "cs", kind="general",
             label_it="agricoltura (Cechia, filtrato: solo miele)", label_en="farming (Czechia, filtered: honey only)"),
    _country("cz_zemedelec", "CZE", "Zemědělec", "https://zemedelec.cz/feed/", "https://zemedelec.cz/", "cs",
             kind="general", label_it="agricoltura (Cechia, filtrato: solo miele)",
             label_en="farming (Czechia, filtered: honey only)"),
    _country("sk_polnoinfo", "SVK", "Poľnoinfo", "https://polnoinfo.sk/feed/", "https://polnoinfo.sk/", "sk",
             kind="general", label_it="agricoltura (Slovacchia, filtrato: solo miele)",
             label_en="farming (Slovakia, filtered: honey only)"),
    _country("sk_rno", "SVK", "Roľnícke noviny", "https://rno.sk/feed/", "https://rno.sk/", "sk", kind="general",
             label_it="agricoltura (Slovacchia, filtrato: solo miele)",
             label_en="farming (Slovakia, filtered: honey only)"),
    _country("si_czs", "SVN", "Čebelarska zveza Slovenije", "https://www.czs.si/feed/", "https://www.czs.si/", "sl",
             kind="association", reliability=_IND, label_it="notizie (Slovenia)", label_en="news (Slovenia)"),
    _country("hr_pcelarstvo", "HRV", "Pčelarstvo.hr", "https://www.pcelarstvo.hr/feed/",
             "https://www.pcelarstvo.hr/", "hr", kind="sector", label_it="notizie (Croazia)", label_en="news (Croatia)"),
    _country("hr_savjetodavna_med", "HRV", "Savjetodavna služba (Ministarstvo poljoprivrede)",
             "https://www.savjetodavna.hr/?s=med&feed=rss2", "https://www.savjetodavna.hr/?s=med", "hr",
             kind="search", reliability=Reliability.OFFICIAL, label_it="miele (Croazia)", label_en="honey (Croatia)"),
    _country("ba_capital_med", "BIH", "Capital.ba", "https://www.capital.ba/tag/med/feed/",
             "https://www.capital.ba/tag/med/", "bs", kind="tag",
             label_it="miele (Bosnia ed Erzegovina)", label_en="honey (Bosnia and Herzegovina)"),
    _country("ba_agroportal_med", "BIH", "Agroportal.ba", "https://agroportal.ba/?s=med&feed=rss2",
             "https://agroportal.ba/?s=med", "bs", kind="search",
             label_it="miele (Bosnia ed Erzegovina)", label_en="honey (Bosnia and Herzegovina)"),
    _country("me_pcelarstvo", "MNE", "Savez pčelarskih organizacija Crne Gore", "https://www.pcelarstvo.me/feed/",
             "https://www.pcelarstvo.me/", "sr", kind="association", reliability=_IND,
             label_it="notizie (Montenegro)", label_en="news (Montenegro)"),
    _country("mk_pari", "MKD", "Pari", "https://www.pari.com.mk/feed/", "https://www.pari.com.mk/", "mk",
             kind="general", label_it="economia (Macedonia del Nord, filtrato: solo miele)",
             label_en="business (North Macedonia, filtered: honey only)"),
    _country("al_agroweb_mjalte", "ALB", "AgroWeb", "https://agroweb.org/?s=mjalt&feed=rss2",
             "https://agroweb.org/?s=mjalt", "sq", kind="search", label_it="miele (Albania)", label_en="honey (Albania)"),
    _country("gr_omse", "GRC", "ΟΜΣΕ – Federation of Greek Beekeepers' Associations", "https://www.omse.gr/feed/",
             "https://www.omse.gr/", "el", kind="association", reliability=_IND,
             label_it="notizie (Grecia)", label_en="news (Greece)"),
    _country("gr_agronews", "GRC", "Agronews.gr", "https://www.agronews.gr/rss", "https://www.agronews.gr/", "el",
             kind="general", label_it="agricoltura (Grecia, filtrato: solo miele)",
             label_en="farming (Greece, filtered: honey only)"),
    _country("bg_agrozona", "BGR", "Agrozona", "https://agrozona.bg/feed/", "https://agrozona.bg/", "bg",
             kind="general", label_it="agricoltura (Bulgaria, filtrato: solo miele)",
             label_en="farming (Bulgaria, filtered: honey only)"),
    _country("bg_agrotv", "BGR", "Agro TV", "https://agrotv.bg/feed/", "https://agrotv.bg/", "bg", kind="general",
             label_it="agricoltura (Bulgaria, filtrato: solo miele)", label_en="farming (Bulgaria, filtered: honey only)"),
    _country("md_agrobiznes_miere", "MDA", "AgroBiznes Moldova", "https://agrobiznes.md/?s=miere&feed=rss2",
             "https://agrobiznes.md/?s=miere", "ro", kind="search", label_it="miele (Moldavia)", label_en="honey (Moldova)"),
    _country("by_belta", "BLR", "BelTA", "https://belta.by/rss", "https://belta.by/", "ru", kind="general",
             label_it="notizie (Bielorussia, filtrato: solo miele)", label_en="news (Belarus, filtered: honey only)"),
    _country("ru_interfax", "RUS", "Interfax", "https://www.interfax.ru/rss.asp", "https://www.interfax.ru/", "ru",
             kind="general", label_it="notizie (Russia, filtrato: solo miele)",
             label_en="news (Russia, filtered: honey only)"),
    _country("lt_delfi_agro", "LTU", "Delfi Agro", "https://www.delfi.lt/rss/feeds/agro.xml",
             "https://www.delfi.lt/agro/", "lt", kind="general",
             label_it="agricoltura (Lituania, filtrato: solo miele)", label_en="farming (Lithuania, filtered: honey only)"),
    _country("lv_la", "LVA", "Latvijas Avīze", "https://www.la.lv/feed", "https://www.la.lv/", "lv", kind="general",
             label_it="notizie (Lettonia, filtrato: solo miele)", label_en="news (Latvia, filtered: honey only)"),
    _country("ee_mesinike_liit", "EST", "Eesti Mesinike Liit", "https://www.mesinikeliit.ee/feed/",
             "https://www.mesinikeliit.ee/", "et", kind="association", reliability=_IND,
             label_it="notizie (Estonia)", label_en="news (Estonia)"),
    _country("ee_pollumajandus", "EST", "Põllumajandus.ee", "https://www.pollumajandus.ee/rss",
             "https://www.pollumajandus.ee/", "et", kind="general",
             label_it="agricoltura (Estonia, filtrato: solo miele)", label_en="farming (Estonia, filtered: honey only)"),
    _country("fi_maaseuduntulevaisuus", "FIN", "Maaseudun Tulevaisuus", "https://www.maaseuduntulevaisuus.fi/rss",
             "https://www.maaseuduntulevaisuus.fi/", "fi", kind="general",
             label_it="agricoltura (Finlandia, filtrato: solo miele)", label_en="farming (Finland, filtered: honey only)"),
    _country("fi_kaytannonmaamies", "FIN", "Käytännön Maamies", "https://www.kaytannonmaamies.fi/feed/",
             "https://www.kaytannonmaamies.fi/", "fi", kind="general",
             label_it="agricoltura (Finlandia, filtrato: solo miele)", label_en="farming (Finland, filtered: honey only)"),
    _country("se_biodlarna", "SWE", "Sveriges Biodlares Riksförbund", "https://www.biodlarna.se/feed/",
             "https://www.biodlarna.se/", "sv", kind="association", reliability=_IND,
             label_it="notizie (Svezia)", label_en="news (Sweden)"),
    _country("se_biodlingsforetagarna", "SWE", "Biodlingsföretagarna", "https://www.biodlingsforetagarna.se/feed/",
             "https://www.biodlingsforetagarna.se/", "sv", kind="association", reliability=_IND,
             label_it="notizie (Svezia)", label_en="news (Sweden)"),
    _country("no_e24", "NOR", "E24", "https://e24.no/rss2/", "https://e24.no/", "no", kind="general",
             label_it="economia (Norvegia, filtrato: solo miele)", label_en="business (Norway, filtered: honey only)"),
    _country("dk_landbrugsavisen", "DNK", "LandbrugsAvisen", "https://landbrugsavisen.dk/rss.xml",
             "https://landbrugsavisen.dk/", "da", kind="general",
             label_it="agricoltura (Danimarca, filtrato: solo miele)", label_en="farming (Denmark, filtered: honey only)"),
    _country("cy_cyprusmail", "CYP", "Cyprus Mail", "https://cyprus-mail.com/feed", "https://cyprus-mail.com/", "en",
             kind="general", label_it="notizie (Cipro, filtrato: solo miele)",
             label_en="news (Cyprus, filtered: honey only)"),
    _country("mt_newsbook_honey", "MLT", "Newsbook Malta", "https://newsbook.com.mt/en/?s=honey&feed=rss2",
             "https://newsbook.com.mt/en/?s=honey", "en", kind="search", label_it="miele (Malta)", label_en="honey (Malta)"),
]
FEEDS += COUNTRY_FEEDS


# ---------------------------------------------------------------------------
# China, India, Vietnam: Google News searches (owner's request, 10 Nov 2026)
# ---------------------------------------------------------------------------
#
# Three of the origins that matter most had no honey news: their trade press has no honey feed and
# the general business feeds above (ECNS, BusinessLine, VietnamPlus) carried no honey item. The
# owner asked to use "normal Google" for them and to keep it updating. So, unlike the generic Google
# News searches at the top of this file (opt-in), these five are ON by default:
#   * an English search per country, whole year, kept only when the headline itself names the
#     country (`require_country`): Google also returns stories that mention it in passing;
#   * a search in Vietnamese and one in Chinese (last 90 days), tagged with the country
#     (`home_tag`): the national press does not name its own country.
# Google's note on its feeds (personal, non-commercial readers) is shown on the Fonti page for
# these too, where each can be switched off. Headline and link only; the link opens the article
# through Google News.
_GN_NOISE = '-"honey trap" -"honey-trap" -"honey pot" -scrap -"market size" -site:oec.world'
_GN_OWNER_NOTE = ("Attivata su richiesta del titolare (10 e 15 nov 2026) per avere notizie dei paesi asiatici "
                  "(Cina, India, Vietnam, Thailandia, Giappone); si può spegnere da questa pagina. ")


def _gn_country(key: str, country: str, label: str, label_en: str, query: str, edition: str, *,
                window: str, native: bool) -> FeedSpec:
    import dataclasses

    spec = _gn(key, label, query, edition, max_age=None, label_en=label_en, window=window)
    months = "dell'ultimo anno" if window == "1y" else "degli ultimi 90 giorni"
    months_en = "from the last year" if window == "1y" else "from the last 90 days"
    return dataclasses.replace(
        spec, key=f"news_google_{key}", country=country, home_tag=native, require_country=not native,
        on_by_default=True, max_entry_age_days=DEFAULT_MAX_ENTRY_AGE_DAYS,
        expected_update=f"Ricerca su Google controllata ogni 3 ore (articoli {months})",
        expected_update_en=f"Google News search checked every 3 hours (articles {months_en})",
        terms_note=_GN_OWNER_NOTE + _GN_TERMS.replace("DISATTIVATO DI DEFAULT: ", ""),
    )


GOOGLE_COUNTRY_FEEDS: list[FeedSpec] = [
    _gn_country("in_honey", "IND", "miele in India (export, prezzi)", "honey in India (exports, prices)",
                'intitle:honey (India OR Indian OR APEDA) (export OR exports OR price OR prices OR "anti-dumping" '
                f'OR adulteration OR beekeepers OR production) {_GN_NOISE}', "en-IN", window="1y", native=False),
    _gn_country("vn_honey", "VNM", "miele in Vietnam (export, dazi)", "honey in Vietnam (exports, duties)",
                'intitle:honey (Vietnam OR Vietnamese) (export OR exports OR price OR prices OR "anti-dumping" '
                f'OR tariff OR tariffs OR beekeepers OR production) {_GN_NOISE}', "en", window="1y", native=False),
    _gn_country("vn_mat_ong", "VNM", "miele in Vietnam, stampa vietnamita", "honey in Vietnam, Vietnamese press",
                '"mật ong" (xuất khẩu OR "giá mật ong" OR "chống bán phá giá" OR "sản lượng" OR "người nuôi ong")',
                "vi", window="90d", native=True),
    _gn_country("cn_honey", "CHN", "miele in Cina (export, prezzi)", "honey in China (exports, prices)",
                'intitle:honey (China OR Chinese) (export OR exports OR imports OR production OR price OR prices '
                f'OR adulteration OR tariff OR beekeepers) {_GN_NOISE}', "en", window="1y", native=False),
    _gn_country("cn_fengmi", "CHN", "miele in Cina, stampa cinese", "honey in China, Chinese press",
                "蜂蜜 (出口 OR 价格 OR 产量 OR 蜂农 OR 养蜂)", "zh", window="90d", native=True),
    # 15 Nov 2026, owner: "fill in India, Vietnam and Thailand, make sure Asian countries have all
    # information needed". Thailand (an origin) and Japan (Asia's main honey importer) had no news
    # source at all; same pattern as above. The honey gate reads Thai and Japanese since this date.
    _gn_country("th_honey", "THA", "miele in Thailandia (export, prezzi)", "honey in Thailand (exports, prices)",
                'intitle:honey (Thailand OR Thai) (export OR exports OR price OR prices OR longan OR tariff '
                f'OR beekeepers OR production) {_GN_NOISE}', "en", window="1y", native=False),
    _gn_country("th_nam_phueng", "THA", "miele in Thailandia, stampa thailandese", "honey in Thailand, Thai press",
                '"น้ำผึ้ง" (ส่งออก OR ราคา OR ผู้เลี้ยงผึ้ง OR ผลผลิต OR ลำไย)', "th", window="90d", native=True),
    # No English search for Japan: its first real run returned only product listings (a barbecue
    # sauce, a shampoo, keycaps), none of them news.
    _gn_country("jp_hachimitsu", "JPN", "miele in Giappone, stampa giapponese", "honey in Japan, Japanese press",
                "(はちみつ OR 蜂蜜 OR ハチミツ) (輸入 OR 価格 OR 養蜂 OR 生産量 OR 国産)", "ja", window="90d", native=True),
]
FEEDS += GOOGLE_COUNTRY_FEEDS


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
        # An archive feed is read again even when its file has not changed: its older entries were
        # skipped while it was an ordinary feed, and re-reading costs a few look-ups (known links are
        # counted as unchanged).
        if doc.unchanged and not ctx.force and spec.max_entry_age_days <= DEFAULT_MAX_ENTRY_AGE_DAYS:
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
        home = spec.country if spec.home_tag else None
        for item in items:
            if item["published_at"] is not None and item["published_at"] < oldest:
                ctx.counters.count("filtered")  # archive item, not news
                continue
            if spec.family == "google_news" and news_service.is_shop_listing(item.get("title"), item.get("publisher")):
                ctx.counters.count("filtered")  # a product page or a social post, not an article
                continue
            if spec.require_country and spec.country not in news_service.tag_countries(
                    f"{news_service.strip_html(item['title'])}\n{news_service.strip_html(item.get('snippet') or '')}"):
                ctx.counters.count("filtered")  # the search matched, but the item is not about the country
                continue
            try:
                ctx.add_news(**item, home_country=home)
                ctx.checkpoint()
            except IntegrityError:
                ctx.session.rollback()
                ctx.counters.restore_committed()
                ctx.counters.count("unchanged")  # stored meanwhile by a concurrent run
            except Exception as exc:  # noqa: BLE001 - one bad item must not lose the batch
                ctx.session.rollback()
                ctx.counters.restore_committed()
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
        "name_en": spec.name_en,
        "publisher": spec.publisher,
        "homepage": spec.homepage,
        "reliability": spec.reliability,
        "country_iso3": spec.country,
        "language": spec.language,
        "expected_update": spec.expected_update,
        "expected_update_en": spec.expected_update_en,
        "expected_max_age_days": spec.expected_max_age_days,
        "terms_note": spec.terms_note,
        "schedule": _schedule(index),
        # Google News RSS is offered for personal, non-commercial use: opt-in from the Fonti page.
        "default_enabled": spec.family != "google_news" or spec.on_by_default,
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
