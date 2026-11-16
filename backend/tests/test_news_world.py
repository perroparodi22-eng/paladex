"""Honey news country by country for the countries that had no news source (16 Nov 2026):
one Google News search each, kept only when the item names the country."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from paladex.collectors import news_feeds
from paladex.collectors.news_feeds import FEEDS, GOOGLE_WORLD_FEEDS, WORLD_NEWS_COUNTRIES, feed_spec
from paladex.models import NewsArticle, Source, utcnow
from paladex.reference.countries import countries
from paladex.services import news as ns


def _rss(*items: str) -> bytes:
    return ("<?xml version=\"1.0\" encoding=\"UTF-8\"?><rss version=\"2.0\"><channel><title>g</title>"
            + "".join(items) + "</channel></rss>").encode("utf-8")


def _item(title: str, outlet: str, n: int) -> str:
    when = (utcnow() - timedelta(days=n)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    return (f"<item><title>{title} - {outlet}</title><link>https://news.google.com/rss/articles/CBW{n}x</link>"
            f"<pubDate>{when}</pubDate><source url=\"https://o{n}.example\">{outlet}</source></item>")


def test_every_country_without_a_news_source_gets_one_search_switched_on(db):
    assert len(GOOGLE_WORLD_FEEDS) == len(WORLD_NEWS_COUNTRIES) == 70
    known = {c["iso3"] for c in countries() if c["region"]}        # the 130 countries with a page
    rows = {s.key: s for s in db.scalars(select(Source).where(Source.category == "news"))}
    for f in GOOGLE_WORLD_FEEDS:
        assert f.country in known and f.key == f"news_google_{f.country.lower()}_honey"
        assert f.family == "google_news" and f.require_country and not f.home_tag and f.country_words
        assert all(w == ns.fold(w) and '"' not in w for w in f.country_words), f.country_words
        assert f.url.startswith("https://news.google.com/rss/search?q=intitle%3A") and "when%3A1y" in f.url
        assert "titolare" in f.terms_note and f.name_en and f.language in {"en", "es", "fr", "pt"}
        assert rows[f.key].enabled is True and rows[f.key].country_iso3 == f.country
    # one news source at least for every country that has a page
    with_news = {f.country for f in FEEDS if f.country}
    assert known - with_news == set()
    assert len({f.key for f in FEEDS}) == len(FEEDS)
    # words that are also something else are left out: the US state, a first name
    assert "georgia" not in feed_spec("news_google_geo_honey").country_words
    assert "jordan" not in feed_spec("news_google_jor_honey").country_words


def test_a_world_search_keeps_the_items_about_its_country(db, run_with_routes):
    spec = feed_spec("news_google_jam_honey")
    body = _rss(
        _item("Jamaican honey exports to Canada rise", "Caribbean Business", 2),                      # named by its adjective
        _item("Portland bee farmers lose big after failed April honey flow", "Jamaica Observer", 3),   # a paper of the country
        _item("Bees starving in disastrous year for French honey", "Jamaica Gleaner", 4),             # about France
        _item("$1 billion Honey Bun expansion targets export growth", "Jamaica Gleaner", 5),          # a bakery
        _item("Honey Jamaica Suppliers, Trade & Prices | Market Overview 2026", "Tridge", 6),         # a directory page
        _item("Honey production in peril after the storm", "The Daily Planet", 7),                    # names no country
        _item("Big increase in Jamaican honey production expected", "Radio Jamaica News", 800),       # too old
    )
    res = run_with_routes(spec.key, {spec.url: (200, body, "application/rss+xml")})
    assert res["new"] == 2, res
    titles = {a.title: a for a in db.scalars(select(NewsArticle))}
    assert set(titles) == {"Jamaican honey exports to Canada rise",
                           "Portland bee farmers lose big after failed April honey flow"}
    assert all("JAM" in a.countries for a in titles.values())
    assert titles["Portland bee farmers lose big after failed April honey flow"].publisher == "Jamaica Observer"


def test_a_spanish_and_a_french_search_tag_their_country(db, run_with_routes):
    cu = feed_spec("news_google_cub_honey")
    body = _rss(_item("Empresa cubana impulsa productos derivados de la miel en el mercado chino", "CGTN Español", 12),
                _item("Luna de miel en La Habana: los mejores hoteles de Cuba", "Viajes Hoy", 13))
    assert run_with_routes(cu.key, {cu.url: (200, body, "application/rss+xml")})["new"] == 1
    cd = feed_spec("news_google_cod_honey")
    body = _rss(_item("Hausse de 11 % du prix de cinq litres de miel pur à Kinshasa", "ACP", 22),
                _item("Lune de miel à Kinshasa pour le couple présidentiel", "Actu People", 23))
    assert run_with_routes(cd.key, {cd.url: (200, body, "application/rss+xml")})["new"] == 1
    by_lang = {a.language: a for a in db.scalars(select(NewsArticle))}
    assert "CUB" in by_lang["es"].countries and "COD" in by_lang["fr"].countries


def test_mentions_matches_whole_words_without_accents_or_case():
    assert ns.mentions("Omani honey, turmeric exhibition opens in Salalah", ("oman", "omani"))
    assert ns.mentions("Miel: la República Dominicana exporta más", ("republica dominicana",))
    assert not ns.mentions("Romanian honey exports", ("oman", "omani"))
    assert not ns.mentions(None, ("oman",)) and not ns.mentions("Oman", ())


def test_not_honey_news_flavoured_drinks_a_bakery_a_tomb_and_a_honeymoon():
    for title, lang in (("Sunmai stops selling honey beer in glass bottles in Taiwan after price protest", "en"),
                        ("Coca-Cola Cambodia brews local pride with Jasmine Lychee Honey Tea", "en"),
                        ("Fuse Tea Launches a New Flavor: Green Tea with Lemon and Honey in Uzbekistan", "en"),
                        ("McDonald's summer menu: new hot honey, ranch and Korean BBQ dips", "en"),
                        ("Honey Bun profit falls four-fifths despite higher sales", "en"),
                        ("Scientists found 3,000-year-old honey in Egyptian tombs, and it was still edible", "en"),
                        ("Hondureño tomó \"miel del amor\" y muere en hospital de Danlí", "es"),
                        ("Lua de mel em Luanda: os melhores hotéis", "pt"),
                        ("Lune de miel à Dakar", "fr")):
        assert not ns.is_honey_related(title, language=lang), title
    for title, lang in (("Tea farmers in Kenya turn to honey production", "en"),
                        ("Oman's honey production tops 934,000 kgs in 2025", "en"),
                        ("Miel en Tunisie : jusqu'à 150 dinars le kilo", "fr"),
                        ("Mel de Angola chega ao mercado europeu", "pt")):
        assert ns.is_honey_related(title, language=lang), title
    assert ns.is_shop_listing("Honey in Saudi Arabia Trade", "The Observatory of Economic Complexity")
    assert ns.is_shop_listing("Honey Malawi Suppliers, Trade & Prices | Market Overview 2026", "Tridge")
    assert not ns.is_shop_listing("Oman honey output nears one million kilogrammes", "Oman Observer")


def test_google_searches_are_spaced_out(monkeypatch):
    clock = {"t": 1000.0}
    waits: list[float] = []

    def sleep(seconds):
        waits.append(round(seconds, 2))
        clock["t"] += seconds

    monkeypatch.setattr(news_feeds.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(news_feeds.time, "sleep", sleep)
    monkeypatch.setattr(news_feeds, "_google_last", None)
    news_feeds._google_pause()                 # the first search goes at once
    clock["t"] += 1.0
    news_feeds._google_pause()                 # one second later: waits for the rest of the gap
    clock["t"] += news_feeds.GOOGLE_MIN_GAP_S + 5
    news_feeds._google_pause()                 # long after: no wait
    assert waits == [news_feeds.GOOGLE_MIN_GAP_S - 1.0]
