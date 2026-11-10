"""Regression tests for the round of 10 Nov 2026: country news feeds and "most important" ranking,
plus the bugs found in the review (partial months shown as totals, month-on-month from one of
several rows, a period end shown as a publication date, HTTP 500 on huge numbers, search folding)."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from paladex.collectors.base import month_bounds
from paladex.models import PriceObservation, Source, utcnow
from paladex.services import ingest
from paladex.services import news as ns
from test_api_overview import add_price_series, month_start
from test_api_overview import make_source as make_price_source
from test_ytd import CY, PY, M, get, make_source, month


def _news_source(db, key: str) -> Source:
    return db.scalars(select(Source).where(Source.key == key)).one()


# ---------------------------------------------------------------------------
# Country feeds
# ---------------------------------------------------------------------------


def test_country_feeds_are_registered_one_or_two_per_country(db):
    from paladex.collectors.news_feeds import COUNTRY_FEEDS, FEEDS

    assert len({f.key for f in FEEDS}) == len(FEEDS)
    per_country: dict[str, int] = {}
    for f in COUNTRY_FEEDS:
        assert f.home_tag and f.country and f.verified == "verified" and f.url.startswith(("https://", "http://"))
        assert len(f.key) <= 60 and len(f.name) <= 200 and f.name_en
        per_country[f.country] = per_country.get(f.country, 0) + 1
    assert all(1 <= n <= 3 for n in per_country.values()), per_country
    assert len(COUNTRY_FEEDS) == 93 and len(per_country) == 57
    # the origins the importer watches and its own markets are covered
    assert {"ARG", "UKR", "BRA", "MEX", "URY", "HUN", "ROU", "SRB", "CHN", "VNM", "IND", "TUR", "ITA", "ESP"} <= set(per_country)
    src = _news_source(db, "news_ar_infocampo_miel")
    assert src.category == "news" and src.country_iso3 == "ARG" and src.enabled


def test_a_national_feed_tags_its_country_even_when_the_text_does_not_name_it(db):
    src = _news_source(db, "news_ar_infocampo_miel")
    a, outcome = ns.ingest_article(db, src, url="https://ar.example/miel-1", language="es", home_country="ARG",
                                   title="La miel sube de precio y los exportadores esperan más embarques",
                                   published_at=utcnow() - timedelta(hours=3))
    assert outcome == "new" and a.countries == ["ARG"] and "origins=ARG" in a.relevance_reason
    # a country the text names comes first; the feed's own country is added after it
    b, _ = ns.ingest_article(db, src, url="https://ar.example/miel-2", language="es", home_country="ARG",
                             title="Brasil vuelve a exportar miel a la Unión Europea",
                             published_at=utcnow() - timedelta(hours=2))
    assert b.countries[0] == "BRA" and "ARG" in b.countries
    # without the feed's country nothing is added
    c, _ = ns.ingest_article(db, _news_source(db, "news_bee_culture"), url="https://us.example/honey-1",
                             title="Honey prices firm as packers look for white honey",
                             published_at=utcnow() - timedelta(hours=1))
    assert c.countries is None


def test_honey_gate_reads_hungarian_romanian_and_serbian():
    assert ns.is_honey_related("Rekordalacsony a méz felvásárlási ára", language="hu")
    assert ns.is_honey_related("Bajban a magyar méhészek: olcsó importméz árasztja el a piacot", language="hu")
    assert not ns.is_honey_related("Új mez a válogatottnak", language="hu")           # "mez" = a sports jersey
    assert not ns.is_honey_related("A mezőgazdaság helyzete 2026-ban", language="hu")  # "mező" = field
    assert ns.is_honey_related("Piața mierii din România, sub presiunea importurilor", language="ro")
    assert ns.is_honey_related("Otkupna cena za med veća nego lane", language="sr")
    assert not ns.is_honey_related("Med school applications rise again", language="en")
    a = ns.analyse("Piața mierii din România, sub presiunea falsurilor și a importurilor", language="ro",
                   home_country="ROU")
    assert "trade" in a.topics and a.countries == ["ROU"]


# ---------------------------------------------------------------------------
# "Most important" ranking and the country highlights
# ---------------------------------------------------------------------------


def test_importance_is_score_plus_outlets_minus_age():
    now = utcnow()
    fresh = ns.importance(60, 0, now, now)
    assert fresh == 60.0
    assert ns.importance(60, 2, now, now) == 66.0 and ns.importance(60, 9, now, now) == 69.0   # outlets capped
    assert ns.importance(80, 0, now - timedelta(days=10), now) == 65.0
    assert ns.importance(None, None, None, now) == 0.0


def _article(db, src, url, title, days_ago, **kw):
    a, _ = ns.ingest_article(db, src, url=url, title=title, published_at=utcnow() - timedelta(days=days_ago), **kw)
    return a


def test_news_sort_top_ranks_the_period_and_days_is_counted_by_the_server(api, db):
    bc = _news_source(db, "news_bee_culture")
    old_big = _article(db, bc, "https://x.example/1", "US sets anti-dumping duties on honey imports from Vietnam and India", 25)
    new_mid = _article(db, bc, "https://x.example/2", "Honey prices rise in Argentina as exports grow", 1)
    weak = _article(db, bc, "https://x.example/3", "Beekeepers meet for the autumn honey show", 1)
    ancient = _article(db, bc, "https://x.example/4", "Honey exports from Ukraine hit a record, prices fall", 200)
    db.commit()
    assert old_big.relevance_score > new_mid.relevance_score > weak.relevance_score

    data = api.get("/api/news", params={"sort": "top", "days": 30, "page_size": 5}).json()
    ids = [i["id"] for i in data["items"]]
    assert ancient.id not in ids and data["days"] == 30 and data["sort"] == "top" and data["total"] == 3
    # a fresh trade story beats a bigger one that is 25 days old (1.5 points a day)
    assert ids[0] == new_mid.id and set(ids) == {new_mid.id, old_big.id, weak.id}
    now = utcnow()
    scores = [ns.importance(i["relevance_score"], i["duplicate_count"], datetime.fromisoformat(i["published_at"]), now)
              for i in data["items"]]
    assert scores == sorted(scores, reverse=True)
    # second page of the ranking, and the plain list is untouched by `days` unless asked
    page2 = api.get("/api/news", params={"sort": "top", "days": 30, "page_size": 2, "page": 2}).json()
    assert [i["id"] for i in page2["items"]] == ids[2:4]
    assert api.get("/api/news").json()["total"] == 4
    assert api.get("/api/news", params={"days": 0}).status_code == 422


def test_country_page_leads_with_one_or_two_trade_stories(api, db):
    ar = _news_source(db, "news_ar_infocampo_miel")
    trade1 = _article(db, ar, "https://ar.example/t1", "Las exportaciones de miel argentina crecen 20% y sube el precio",
                      4, language="es", home_country="ARG")
    trade2 = _article(db, ar, "https://ar.example/t2", "Estados Unidos mantiene los aranceles antidumping a la miel argentina",
                      20, language="es", home_country="ARG")
    trade3 = _article(db, ar, "https://ar.example/t3", "Exportadores de miel piden menos retenciones", 100,
                      language="es", home_country="ARG")
    bees = _article(db, ar, "https://ar.example/b1", "El Niño amenaza a las abejas: recomendaciones para las colmenas", 1,
                    language="es", home_country="ARG")
    old = _article(db, ar, "https://ar.example/o1", "Récord de exportaciones de miel a Japón", 400, language="es",
                   home_country="ARG")
    db.commit()

    news = get(api, "/api/countries/ARG")["news"]
    top = [n["id"] for n in news["highlights"]]
    assert len(top) == 2 and trade1.id in top and bees.id not in top and old.id not in top
    assert top[0] == trade1.id and set(top) <= {trade1.id, trade2.id, trade3.id}
    assert news["highlight_days"] == 365 and news["count_30d"] == 3
    assert [n["id"] for n in news["items"]][0] == bees.id        # the plain list stays newest first
    # a country nobody wrote about has no highlights and says which sources would bring news
    fra = get(api, "/api/countries/FRA")["news"]
    assert fra["highlights"] == [] and fra["available"] is False
    assert any(p["key"] == "news_fr_unaf" for p in fra["providers"])


# ---------------------------------------------------------------------------
# Trade: a month published without the reporter's total is never shown as a total
# ---------------------------------------------------------------------------


def test_partial_month_is_left_out_of_the_monthly_series_the_archive_and_alerts(api, db):
    if M >= 12:
        return
    eurostat = make_source(db, "eurostat_partial_t")
    comex = make_source(db, "br_comex_partial_t", country="BRA")
    for yy, last in ((PY, 12), (CY, M)):
        for m in range(1, last + 1):
            month(db, eurostat, "ITA", "WLD", yy, m, 2_000_000, flow="import")
            month(db, eurostat, "ITA", "ARG", yy, m, 500_000, flow="import")
            month(db, comex, "BRA", "USA", yy, m, 300_000)
            month(db, comex, "BRA", "DEU", yy, m, 100_000)
    month(db, eurostat, "ITA", "ARG", CY, M + 1, 100_000, flow="import")     # newest month: one partner, no total
    month(db, comex, "BRA", "USA", CY, M + 1, 300_000)                       # a source that never has totals
    db.commit()

    s = get(api, "/api/trade/series?reporter=ITA&flow=import&freq=M")
    labels = [p["period_label"] for p in s["series"][0]["points"]]
    partial = f"{CY}-{M + 1:02d}"
    assert partial not in labels and labels[-1] == f"{CY}-{M:02d}"
    assert s["excluded_months"] == [{"source": s["series"][0]["source"], "month": partial, "reason": "no_total",
                                     "partners_count": 1}]
    # one partner's own series still has that month (it is a real figure for that partner)
    arg = get(api, "/api/trade/series?reporter=ITA&partner=ARG&flow=import&freq=M")
    assert arg["series"][0]["points"][-1]["period_label"] == partial and arg["excluded_months"] == []
    # partner sums stay for a source that never publishes a total
    bra = get(api, "/api/trade/series?reporter=BRA&flow=export&freq=M")
    assert bra["series"][0]["points"][-1]["period_label"] == partial and bra["excluded_months"] == []
    assert bra["series"][0]["points"][-1]["summed_from_partners"] is True

    # the archive's "year so far" now agrees with the country page
    arch = get(api, "/api/archive/trade?reporter=ITA&flow=import")
    ytd = arch["ytd"][0]
    assert ytd["through_month"] == M and ytd["years"][0]["net_weight_kg"] == 2_000_000 * M
    assert ytd["years"][0]["change_pct"] == 0.0 and arch["excluded_months"][0]["month"] == partial
    own = get(api, "/api/countries/ITA")["trade"]["import"]["ytd"]["own"]
    assert own["net_weight_kg"] == ytd["years"][0]["net_weight_kg"]

    # and a trade alert no longer fires on the partial month
    r = api.post("/api/alerts/preview", json={"alert_type": "trade_change", "params": {
        "reporter": "ITA", "partner": "WLD", "flow": "import", "freq": "M", "threshold_pct": 20}})
    assert r.status_code == 200 and r.json()["total"] == 0 and r.json()["items"] == []


def test_source_line_shows_a_publication_date_only_when_the_source_gave_one():
    from paladex.api.trade import Ctx, sources_used

    class _Ctx:
        def source_id(self, key):
            return None

        def source(self, sid):
            return None

    rows = [{"source": {"key": "a", "name": "A"}, "published_at": None, "period_end": "2024-12-31", "frequency": "A"},
            {"source": {"key": "b", "name": "B"}, "published_at": "2025-03-10", "period_end": "2024-12-31", "frequency": "A"},
            {"source": {"key": "b", "name": "B"}, "published_at": None, "period_end": "2025-12-31", "frequency": "A"}]
    out = {s["key"]: s for s in sources_used(_Ctx(), rows)}        # type: ignore[arg-type]
    assert out["a"]["latest_published_at"] is None                 # was shown as "published 31 Dec 2024"
    assert out["b"]["latest_published_at"] == "2025-03-10"
    assert Ctx is not None


# ---------------------------------------------------------------------------
# Overview: several rows of one month count as their average, as on the Prezzi page
# ---------------------------------------------------------------------------


def _extra_row(db, src, origin, variety, value, months_back, n):
    start = month_start(months_back)
    _, end = month_bounds(start.year, start.month)
    ingest.record(
        db, PriceObservation, source_id=src.id,
        series_key=f"wholesale_bulk|{origin}|{variety}|USD|None|{start:%Y-%m}|line{n}",
        price_type="wholesale_bulk", origin_iso3=origin, origin_label=origin, market_iso3="USA", variety=variety,
        terms=None, price_value=value, currency="USD", unit="kg", price_per_kg=value, usd_per_kg=value,
        eur_per_kg=round(value / 1.1, 4), period_start=start, period_end=end, period_label=f"{start:%Y-%m}",
        frequency="M", published_at=end + timedelta(days=10), source_url="https://example.org/report.pdf",
        data_status="published", reliability=src.reliability,
    )


def test_two_rows_of_one_month_are_averaged_in_the_tile_and_its_changes(api, db):
    usda = make_price_source(db, "usda_two_lines_t", "prices")
    add_price_series(db, usda, "IND", "polyflora", [2.80, 2.36])       # two months ago, last month
    _extra_row(db, usda, "IND", "polyflora", 2.30, 2, 2)                # a second line two months ago
    _extra_row(db, usda, "IND", "polyflora", 2.44, 1, 2)                # and a second line last month
    db.commit()

    tile = next(t for t in get(api, "/api/overview?lang=it")["prices"]["items"] if t["origin_iso3"] == "IND")
    assert tile["price_per_kg"] == 2.4 and tile["averaged_rows"] == 2 and tile["row_id"] is None
    # (2.36 + 2.44) / 2 = 2.40 against (2.80 + 2.30) / 2 = 2.55: -5.9%, not 2.44 vs 2.80 (-12.9%)
    assert tile["mom_pct"] == round((2.40 / 2.55 - 1) * 100, 2)
    assert [p["period_label"] for p in tile["spark"]] == sorted({p["period_label"] for p in tile["spark"]})
    assert tile["earlier_period_label"] != tile["period_label"]


# ---------------------------------------------------------------------------
# Small ones
# ---------------------------------------------------------------------------


def test_a_number_beyond_64_bits_is_a_bad_request_not_a_server_error(api):
    huge = 9223372036854775808
    for path in (f"/api/news/{huge}", f"/api/prices/observations?page={huge}", f"/api/reports?page={huge}",
                 f"/api/regulations?page={huge}", f"/api/news?page={huge}"):
        assert api.get(path).status_code in (404, 422), path


def test_search_does_not_glue_letters_across_characters_it_cannot_read():
    from paladex.api.search import _fold

    assert _fold("è€ñ") == "e n" and _fold("Türkiye") == "turkiye" and _fold("Côte d’Ivoire") == "cote d ivoire"
    assert _fold("  Miele  d'acacia ") == "miele d acacia"


# ---------------------------------------------------------------------------
# All of Europe (second part of the round)
# ---------------------------------------------------------------------------


def test_every_european_country_has_one_or_two_news_feeds():
    from paladex.collectors.news_feeds import COUNTRY_FEEDS
    from paladex.reference.countries import countries

    europe = {c["iso3"] for c in countries() if c.get("region") == "Europe"}
    per_country: dict[str, int] = {}
    for f in COUNTRY_FEEDS:
        per_country[f.country] = per_country.get(f.country, 0) + 1
    assert len(europe) == 39 and not europe - set(per_country), sorted(europe - set(per_country))
    assert all(1 <= per_country[c] <= 3 for c in europe)
    south_america = {c["iso3"] for c in countries() if c.get("region") == "South America"}
    assert len(south_america) == 10 and not south_america - set(per_country)
    assert all(1 <= per_country[c] <= 3 for c in south_america)
    # South America: the honey feeds keep older articles, so a country page always has its latest one
    from paladex.collectors.news_feeds import ARCHIVE_ENTRY_AGE_DAYS
    old = {f.country for f in COUNTRY_FEEDS if f.max_entry_age_days == ARCHIVE_ENTRY_AGE_DAYS}
    assert old == south_america


def test_honey_gate_reads_the_other_european_languages():
    honey = [("Ceny miodu w skupie spadają, pszczelarze alarmują", "pl", "prices"),
             ("Polska pasieka w kryzysie", "pl", None),
             ("Včelaři hlásí slabou snůšku, ceny medu porostou", "cs", "prices"),
             ("Slovenskí včelári: dovoz lacného medu ničí trh", "sk", "trade"),
             ("Čebelarji: letina medu letos slaba", "sl", None),
             ("Nederlandse imkers: honing uit China overspoelt de markt", "nl", None),
             ("Svensk honung: biodlare larmar om fusk", "sv", None),
             ("Dansk honning under pres fra billig import", "da", "trade"),
             ("Birøktere frykter import av billig honning", "no", "trade"),
             ("Hunajan tuonti kasvoi, mehiläishoitajat huolissaan", "fi", "trade"),
             ("Lietuvos bitininkai: medaus kainos krenta", "lt", "prices"),
             ("Latvijas biškopji: medus imports aug", "lv", "trade"),
             ("Eesti mesinikud: mee hind langeb", "et", None),
             ("Εξαγωγές μελιού: οι μελισσοκόμοι ζητούν ελέγχους", "el", "trade"),
             ("Износът на български мед расте, цените падат", "bg", "trade"),
             ("Çmimi i mjaltit rritet", "sq", None),
             ("Cijena meda raste, pčelari zadovoljni", "hr", "prices")]
    for title, lang, topic in honey:
        a = ns.analyse(title, language=lang)
        assert a.is_honey, title
        assert topic is None or topic in a.topics, (title, a.topics)
    # the same letters in another language are not honey
    for title, lang in [("Elektros kaina Lietuvoje pirmadienį pasieks aukščiausią lygį", "lt"),   # Polish "pasieka"
                        ("Noregur er mjaltaþjónaland Norðurlanda, sjálfvirkar mjaltir", "is"),      # Albanian "mjaltë"
                        ("Honing your negotiation skills", "en"),                                    # Dutch "honing"
                        ("Cebelitarık Boğazı'nda tatbikat", "tr"),                                   # Slovenian "čebel*"
                        ("Miodrag Kostić kupuje fabriku", "sr"), ("Biskop Anders besöker Uppsala", "sv"),
                        ("Medusa attack hits hospital", "en"), ("Tre mesi di pioggia", "it"),
                        ("La cena de Navidad", "es"), ("Τα μέλη της επιτροπής συναντήθηκαν", "el"),
                        ("Il a pris la décision", "fr"), ("Med school rankings 2026", "en")]:
        assert not ns.is_honey_related(title, language=lang), title


# ---------------------------------------------------------------------------
# South America: the latest article a country has, however old, with its date
# ---------------------------------------------------------------------------


def test_an_archive_feed_keeps_old_articles_and_a_normal_feed_does_not(db, run_with_routes):
    from paladex.collectors.news_feeds import feed_spec

    def rss(link_prefix: str) -> tuple:
        body = f"""<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>t</title>
        <item><title>La miel de Colombia cumple altos estándares internacionales</title>
          <link>{link_prefix}/miel-estandares</link><pubDate>Tue, 12 Jul 2022 14:00:00 +0000</pubDate></item>
        </channel></rss>"""
        return 200, body.encode("utf-8"), "application/rss+xml"

    old = feed_spec("news_co_elcampesino_apicultura")
    normal = feed_spec("news_es_agropopular_miel")
    assert old.max_entry_age_days == 3650 and normal.max_entry_age_days == 365
    res = run_with_routes(old.key, {old.url: rss("https://co.example")})
    assert res["new"] == 1
    res = run_with_routes(normal.key, {normal.url: rss("https://es.example")})
    assert res["new"] == 0          # a 2022 article is not news for a feed that publishes every week


def test_country_page_shows_the_latest_trade_story_however_old(api, db):
    src = _news_source(db, "news_co_elcampesino_apicultura")
    old_trade = _article(db, src, "https://co.example/exporta", "Colombia exporta miel a Europa por primera vez",
                         900, language="es", home_country="COL")
    older_trade = _article(db, src, "https://co.example/precio", "Sube el precio de la miel en Colombia", 1500,
                           language="es", home_country="COL")
    old_bees = _article(db, src, "https://co.example/abejas", "Las colmenas de abejas han aumentado un 53%", 700,
                        language="es", home_country="COL")
    db.commit()
    news = get(api, "/api/countries/COL")["news"]
    assert [n["id"] for n in news["highlights"]] == [old_trade.id, older_trade.id]      # newest first, no time limit
    assert news["count_30d"] == 0 and [n["id"] for n in news["items"]][0] == old_bees.id
    assert news["latest_at"][:10] == old_bees.published_at.date().isoformat()
    # as soon as there is a trade story of the last year, only the period's stories lead
    fresh = _article(db, src, "https://co.example/nuevo", "Exportaciones de miel colombiana crecen 30%", 10,
                     language="es", home_country="COL")
    db.commit()
    news = get(api, "/api/countries/COL")["news"]
    assert [n["id"] for n in news["highlights"]] == [fresh.id] and news["latest_at"][:10] == fresh.published_at.date().isoformat()


def test_replaced_feeds_are_removed_when_never_used_and_switched_off_otherwise(db):
    from paladex.models import NewsArticle
    from paladex.reference.seed import RETIRED_SOURCES, seed_reference_data

    unused = Source(key="news_py_ip", name="x", publisher="x", kind="rss", reliability="official", category="news")
    used = Source(key="news_co_agronegocios", name="y", publisher="y", kind="rss", reliability="trade_press", category="news")
    db.add_all([unused, used])
    db.flush()
    a, _ = ns.ingest_article(db, used, url="https://co.example/x", title="Miel: exportaciones en alza",
                             published_at=utcnow() - timedelta(days=2))
    db.commit()
    seed_reference_data(db)
    db.commit()
    keys = {s.key: s for s in db.scalars(select(Source).where(Source.key.in_(RETIRED_SOURCES)))}
    assert set(keys) == {"news_co_agronegocios"} and keys["news_co_agronegocios"].enabled is False
    assert db.get(NewsArticle, a.id) is not None
