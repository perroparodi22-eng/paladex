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
_EDITIONS_EN = {
    "en": "English, US edition", "en-GB": "English, UK edition", "it": "Italian",
    "es-AR": "Spanish, Argentina edition", "es-ES": "Spanish, Spain edition",
    "pt-BR": "Portuguese, Brazil edition", "de": "German",
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


def _gn(key: str, label: str, query: str, edition: str, *, max_age: int = 5, label_en: str = "") -> FeedSpec:
    hl, gl, ceid, ed_label = _EDITIONS[edition]
    exclude = _GN_EXCLUDE.get(edition.split("-")[0])
    if exclude:
        query = f"{query} {exclude}"
    return FeedSpec(
        key=f"news_gn_{key}",
        name=f"Google News · {label} ({ed_label})",
        name_en=f"Google News · {label_en} ({_EDITIONS_EN[edition]})" if label_en else "",
        publisher="Google News (aggregatore)",
        url=google_news_url(query, edition),
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

_KINDS = {
    # kind -> (Italian, English) description of what is read
    "tag": ("Sezione miele del sito (feed RSS dell'editore)", "The site's honey section (publisher's RSS feed)"),
    "search": ("Articoli del sito che citano il miele (feed RSS di ricerca dell'editore)",
               "The site's articles mentioning honey (publisher's search RSS feed)"),
    "association": ("Notizie dell'associazione di settore (feed RSS)", "News of the sector association (RSS feed)"),
    "general": ("Feed generale: si conservano solo gli articoli che parlano di miele o apicoltura",
                "General feed: only the articles about honey or beekeeping are kept"),
}


def _country(key: str, country: str, publisher: str, url: str, homepage: str, language: str, *, kind: str,
             label_it: str, label_en: str, reliability: Reliability = Reliability.TRADE_PRESS,
             publisher_en: str | None = None) -> FeedSpec:
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
    )


_IND = Reliability.INDUSTRY
COUNTRY_FEEDS: list[FeedSpec] = [
    # --- South America ------------------------------------------------------------------
    _country("ar_infocampo_miel", "ARG", "Infocampo", "https://www.infocampo.com.ar/tag/miel/feed/",
             "https://www.infocampo.com.ar/tag/miel/", "es", kind="tag",
             label_it="miele (Argentina)", label_en="honey (Argentina)"),
    _country("ar_bichos_miel", "ARG", "Bichos de Campo", "https://bichosdecampo.com/tag/miel/feed/",
             "https://bichosdecampo.com/tag/miel/", "es", kind="tag",
             label_it="miele (Argentina)", label_en="honey (Argentina)"),
    _country("uy_todoelcampo_miel", "URY", "Todo El Campo", "https://www.todoelcampo.com.uy/?s=miel&feed=rss2",
             "https://www.todoelcampo.com.uy/?s=miel", "es", kind="search",
             label_it="miele (Uruguay)", label_en="honey (Uruguay)"),
    _country("br_g1_agro", "BRA", "G1 Agronegócios (Globo)",
             "https://g1.globo.com/dynamo/economia/agronegocios/rss2.xml",
             "https://g1.globo.com/economia/agronegocios/", "pt", kind="general",
             label_it="agroalimentare (Brasile, filtrato: solo miele)",
             label_en="agribusiness (Brazil, filtered: honey only)"),
    _country("cl_portalagro_miel", "CHL", "Portal Agro Chile", "https://www.portalagrochile.cl/tag/miel/feed/",
             "https://www.portalagrochile.cl/tag/miel/", "es", kind="tag",
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
]
FEEDS += COUNTRY_FEEDS


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
        home = spec.country if spec.home_tag else None
        for item in items:
            if item["published_at"] is not None and item["published_at"] < oldest:
                ctx.counters.count("filtered")  # archive item, not news
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
