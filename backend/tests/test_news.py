"""Global news: canonicalisation, honey gate, dedup, tagging, relevance, feed parsing,
collectors end-to-end, LLM providers, AI enrichment and the /api/news endpoints."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import httpx
import pytest
import respx
from sqlalchemy import select

from conftest import fixture_bytes
from paladex.models import NewsArticle, Source, utcnow
from paladex.services import news as ns

FIXED_NOW = datetime(2026, 11, 2, 8, 0, 0)


@pytest.fixture()
def frozen_now(monkeypatch):
    """Pin 'now' for age filters/dedup so the static fixtures stay deterministic."""
    from paladex.collectors import news_feeds

    monkeypatch.setattr(news_feeds, "utcnow", lambda: FIXED_NOW)
    monkeypatch.setattr(ns, "utcnow", lambda: FIXED_NOW)
    return FIXED_NOW


def _source(db, key="news_gn_en_honey_prices") -> Source:
    return db.scalars(select(Source).where(Source.key == key)).one()


def _ingest(db, source=None, **kw):
    kw.setdefault("published_at", utcnow() - timedelta(hours=2))
    return ns.ingest_article(db, source or _source(db), **kw)


# ---------------------------------------------------------------------------
# URL canonicalisation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url,expected", [
    ("https://www.example.com/news/honey-prices/?utm_source=rss&utm_medium=feed&id=7#comments",
     "https://example.com/news/honey-prices?id=7"),
    ("http://example.com/a/b/?fbclid=XYZ&gclid=abc&b=2&a=1", "https://example.com/a/b?a=1&b=2"),
    ("https://m.example.com/story/amp/", "https://example.com/story"),
    ("https://example.com/story.amp.html", "https://example.com/story.html"),
    ("https://example.com/amp/story/123", "https://example.com/story/123"),
    ("https://example.com/story?outputType=amp", "https://example.com/story"),
    ("https://www-example-com.cdn.ampproject.org/c/s/www.example.com/story/amp?utm_campaign=x",
     "https://example.com/story"),
    ("https://www.google.com/amp/s/www.example.com/story/amp/", "https://example.com/story"),
    ("https://news.google.com/news/url?sa=t&url=https://www.example.com/x?utm_source=gn", "https://example.com/x"),
    ("https://news.google.com/rss/articles/CBMiABC?oc=5", "https://news.google.com/rss/articles/CBMiABC"),
])
def test_canonicalize_url(url, expected):
    assert ns.canonicalize_url(url) == expected


def test_clean_url_keeps_clickable_link():
    assert ns.clean_url("https://www.example.com/x/?utm_source=a&p=1#top") == "https://www.example.com/x/?p=1"


def test_google_news_real_url_only_from_feed_fields():
    gn = "https://news.google.com/rss/articles/CBMiXYZ?oc=5"
    # new format: description only links back to Google -> keep the Google link (never fetched)
    desc = f'<a href="{gn}" target="_blank">Headline</a>&nbsp;&nbsp;<font color="#6f6f6f">Outlet</font>'
    assert ns.google_news_real_url(gn, desc) == gn
    # description carries the publisher URL -> use it
    desc2 = '<a href="https://www.outlet.example/story">Headline</a>'
    assert ns.google_news_real_url(gn, desc2) == "https://www.outlet.example/story"


# ---------------------------------------------------------------------------
# Honey gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text,lang", [
    ("Argentine honey exports rise", "en"),
    ("Prezzo del miele in calo", "it"),
    ("Precio de la miel argentina", "es"),
    ("Honigpreise steigen", "de"),
    ("Exportação de mel cresce", "pt"),
    ("Gli apicoltori lanciano l'allarme", "it"),
    ("Beekeepers report heavy winter losses", "en"),
    ("Apicultores entrerrianos reclaman", "es"),
    ("Varroa mite spreads to new region", "en"),
    ("Mānuka exports to China", "en"),
    ("Colony losses: bee colonies down 20%", "en"),
    ("Pollination contracts: almond growers pay more for bees", "en"),
    ("Imports under HS 0409 jumped", "en"),
    ("Melata di bosco, annata scarsa", "it"),
])
def test_gate_accepts_honey(text, lang):
    assert ns.is_honey_related(text, language=lang)


@pytest.mark.parametrize("text,lang", [
    ("Honey Singh announces world tour", "en"),
    ("Mel Gibson's new film breaks records", "en"),
    ("Wind pollination in grasses explained", "en"),
    ("Our honeymoon in the Maldives", "en"),
    ("New API pricing for developers", "en"),
    ("Hive mind: crypto traders pile in", "en"),
    ("Honey badger caught on camera", "en"),
])
def test_gate_rejects_non_honey(text, lang):
    assert not ns.is_honey_related(text, language=lang)


def test_ingest_filtered_not_stored(db):
    art, outcome = _ingest(db, url="https://example.com/singh", title="Honey Singh announces world tour")
    assert art is None and outcome == "filtered"
    assert db.scalar(select(NewsArticle.id)) is None


# ---------------------------------------------------------------------------
# Tagging & relevance
# ---------------------------------------------------------------------------


def test_country_tagging_word_boundaries_and_exclusions():
    assert ns.tag_countries("Chinese and Argentine honey flood the market") == ["CHN", "ARG"]
    assert ns.tag_countries("Indiana beekeepers meet") == []
    assert ns.tag_countries("Honey-glazed turkey breast recipe") == []
    assert ns.tag_countries("Turkey's honey exports rise") == ["TUR"]
    assert ns.tag_countries("New Mexico honey festival") == []
    assert "MEX" in ns.tag_countries("Miel de México y Yucatán")
    assert ns.tag_countries("Dazi Usa sul miele") == ["USA"]
    assert ns.tag_countries("Si usa il miele per dolcificare") == []
    assert ns.tag_countries("Precio: US$ 3.000 por tonelada") == []
    assert ns.tag_countries("U.S. honey imports") == ["USA"]
    assert ns.tag_countries("Miele ucraino e ungherese") == ["UKR", "HUN"]
    assert ns.tag_countries("Import dall'Ucraina e dall'Ungheria") == ["UKR", "HUN"]


def test_topic_tagging_multilingual():
    assert set(ns.tag_topics("US sets anti-dumping duties on honey")) >= {"tariffs"}
    assert set(ns.tag_topics("Prezzo del miele: quotazioni in calo")) >= {"prices"}
    assert set(ns.tag_topics("Exportaciones de miel: récord")) >= {"trade"}
    assert set(ns.tag_topics("Miele falso: sciroppo di riso nei vasetti")) >= {"adulteration"}
    assert set(ns.tag_topics("Siccità e gelate: raccolto di miele dimezzato")) >= {"production", "weather"}
    assert set(ns.tag_topics("EU bans honey imports from the region")) >= {"import_restrictions"}
    assert set(ns.tag_topics("Glyphosate residues found in honey")) >= {"quality"}
    assert set(ns.tag_topics("Breakfast Directive: new honey labelling rules")) >= {"policy"}
    assert set(ns.tag_topics("Honey packer acquires rival company")) >= {"companies"}
    assert set(ns.tag_topics("Varroa and colony losses")) >= {"colony_health"}
    # excerpt-only matches are weaker
    assert ns.tag_topics("Honey news", "prices went up")["prices"] < 1.0


def test_relevance_ordering():
    trade = ns.analyse("US imposes anti-dumping duties on honey from Argentina and Vietnam")
    prices = ns.analyse("Prezzo del miele: crollo delle quotazioni del millefiori argentino", language="it")
    hobby = ns.analyse("Backyard beekeeper teaches school children about bees and honey")
    health = ns.analyse("7 health benefits of honey for sore throat")
    recipe = ns.analyse("Honey garlic chicken recipe")
    assert trade.score >= 60 and prices.score >= 60
    assert trade.score > hobby.score and prices.score > hobby.score
    assert hobby.score < 35 and health.score < 20 and recipe.score < 20
    assert "origins=ARG" in trade.reason and "topics=tariffs" in trade.reason
    assert "penalties=recipe" in recipe.reason
    assert ns.relevance_level(trade.score) == "high"


def test_explain_reason_bilingual():
    r = "topics=prices,tariffs; origins=ARG,CHN; markets=USA; eu; bulk; source=official; penalties=recipe"
    it, en = ns.explain_reason(r, "it"), ns.explain_reason(r, "en")
    assert "Prezzi" in it and "Dazi e antidumping" in it and "Argentina" in it and "Cina" in it
    assert "Prices" in en and "China" in en and "European Union" in en and "recipe" in en


# ---------------------------------------------------------------------------
# Ingestion: snippet/image, exact + fuzzy dedup, window
# ---------------------------------------------------------------------------


def test_ingest_cleans_snippet_and_image(db):
    html = ('<p><img src="https://cdn.example/pic.jpg" width="600"/></p><p>Packers report bulk honey '
            + "prices rising sharply this month " * 40 + "</p><p>The post X appeared first on Y.</p>")
    art, outcome = _ingest(db, url="https://example.com/a?utm_source=x", title="Bulk honey prices rise",
                           snippet=html, language="en-US")
    assert outcome == "new"
    assert art.image_url == "https://cdn.example/pic.jpg"
    assert "<" not in art.snippet and "appeared first" not in art.snippet
    assert len(art.snippet) <= ns.SNIPPET_MAX_CHARS and art.snippet.endswith("…")
    assert art.language == "en"
    assert art.url == "https://example.com/a" and art.canonical_url == "https://example.com/a"
    assert "prices" in art.topics


def test_exact_url_is_unchanged(db):
    a1, o1 = _ingest(db, url="https://www.example.com/x?utm_source=a", title="Honey exports to the US jump")
    a2, o2 = _ingest(db, url="https://example.com/x/#top", title="Honey exports to the US jump (updated)")
    assert (o1, o2) == ("new", "unchanged") and a1.id == a2.id
    assert db.scalar(select(NewsArticle.title).where(NewsArticle.id == a1.id)) == "Honey exports to the US jump"


def test_duplicate_exact_title_and_fuzzy(db):
    src_a = _source(db, "news_gn_en_honey_prices")
    src_b = _source(db, "news_gn_en_honey_trade")
    orig, o1 = _ingest(db, src_a, url="https://outlet-a.example/1", publisher="Outlet A",
                       title="Argentina honey exports surge as prices climb - Outlet A")
    dup, o2 = _ingest(db, src_b, url="https://outlet-b.example/2", publisher="Outlet B",
                      title="Argentina Honey Exports Surge as Prices Climb")
    fuzzy, o3 = _ingest(db, src_b, url="https://outlet-c.example/3", publisher="Outlet C",
                        title="Argentina honey exports surge as prices climb again")
    assert (o1, o2, o3) == ("new", "duplicate", "duplicate")
    assert dup.duplicate_of_id == orig.id and fuzzy.duplicate_of_id == orig.id
    assert orig.duplicate_count == 2
    assert orig.title == "Argentina honey exports surge as prices climb"  # outlet suffix removed


def test_duplicate_window_and_short_titles(db):
    now = utcnow()
    a, _ = _ingest(db, url="https://a.example/1", title="Honey market weekly update from the Pampas",
                   published_at=now - timedelta(days=12))
    b, ob = _ingest(db, url="https://b.example/2", title="Honey market weekly update from the Pampas",
                    published_at=now - timedelta(days=1))
    assert ob == "new" and b.duplicate_of_id is None  # same headline, 11 days apart: a new story
    # token_set_ratio of a subset title would be 100, but very different lengths are not duplicates
    c, oc = _ingest(db, url="https://c.example/3", title="Honey prices")
    d, od = _ingest(db, url="https://d.example/4", title="Honey prices rise in Argentina amid long drought and frost")
    assert oc == "new" and od == "new"


# ---------------------------------------------------------------------------
# Feed parsing
# ---------------------------------------------------------------------------


def _spec(key):
    from paladex.collectors import news_feeds

    return news_feeds.feed_spec(key)


def test_parse_google_news_format():
    from paladex.collectors.news_feeds import parse_feed

    items, warnings = parse_feed(fixture_bytes("news/google_news_en.xml"), _spec("news_gn_en_honey_prices"))
    assert warnings == []
    first = items[0]
    assert first["title"] == "Argentine honey export prices slide as US demand cools"
    assert first["publisher"] == "Example Wire"
    assert first["url"].startswith("https://news.google.com/rss/articles/")
    assert first["snippet"] is None and first["language"] == "en"
    assert first["published_at"] == datetime(2026, 11, 1, 14, 12)
    # cluster description (list of other outlets' headlines) is not used as an excerpt
    assert items[2]["snippet"] is None
    # older format: real URL + excerpt are in the feed -> used, no fetching
    old = items[5]
    assert old["url"].startswith("https://www.marketwatch.test/story/china-honey-output-forecast")
    assert "Henan" in old["snippet"]


def test_parse_rss2_wordpress():
    from paladex.collectors.news_feeds import parse_feed

    items, _ = parse_feed(fixture_bytes("news/rss2_wordpress.xml"), _spec("news_bee_culture"))
    assert len(items) == 4
    assert items[0]["image_url"].endswith("/drums.jpg")          # media:content
    assert items[1]["image_url"].endswith("/varroa.jpg")         # enclosure
    assert items[3]["image_url"] is None                          # tracking pixel ignored
    assert items[0]["publisher"] == "Bee Culture (Root Publications)"


def test_parse_atom():
    from paladex.collectors.news_feeds import parse_feed

    items, _ = parse_feed(fixture_bytes("news/atom.xml"), _spec("news_apimondia"))
    assert items[0]["url"] == "https://federation.example/news/2026/authenticity-testing#top"
    assert items[0]["published_at"] == datetime(2026, 10, 31, 7, 0)  # +01:00 converted to UTC
    assert items[0]["image_url"] == "https://federation.example/img/lab-testing.jpg"
    assert items[1]["published_at"] == datetime(2026, 10, 20, 10, 0)  # falls back to <updated>


def test_parse_malformed_and_not_a_feed():
    from paladex.collectors.base import CollectorError
    from paladex.collectors.news_feeds import parse_feed

    items, warnings = parse_feed(fixture_bytes("news/malformed_rss.xml"), _spec("news_bee_culture"))
    assert len(items) == 2 and warnings and "malformato" in warnings[0]
    with pytest.raises(CollectorError):
        parse_feed(fixture_bytes("news/not_a_feed.html"), _spec("news_bee_culture"))


def test_every_feed_is_its_own_source(db):
    from paladex.collectors.news_feeds import FEEDS

    keys = {f.key for f in FEEDS}
    assert len(keys) == len(FEEDS) >= 15
    rows = {s.key: s for s in db.scalars(select(Source).where(Source.category == "news"))}
    assert keys <= set(rows)
    gn = rows["news_gn_it_prezzo_miele"]
    assert gn.reliability == "aggregator" and gn.kind == "rss" and gn.language == "it"
    assert rows["news_ec_agri"].reliability == "official"
    assert all(len(k) <= 60 for k in keys)


# ---------------------------------------------------------------------------
# Collectors end-to-end (offline)
# ---------------------------------------------------------------------------


def test_google_news_collector_end_to_end(run_with_routes, session_factory, frozen_now):
    # Google News feeds are opt-in (personal-use terms): the owner enables them on /fonti.
    with session_factory() as s:
        s.scalars(select(Source).where(Source.key == "news_gn_en_honey_prices")).one().enabled = True
    routes = {r"^https://news\.google\.com/rss/search": (200, fixture_bytes("news/google_news_en.xml"),
                                                        "application/rss+xml; charset=utf-8")}
    res = run_with_routes("news_gn_en_honey_prices", routes)
    assert res["status"] == "success", res
    with session_factory() as s:
        rows = list(s.scalars(select(NewsArticle).order_by(NewsArticle.id)))
        titles = [r.title for r in rows]
        assert not any("Singh" in t for t in titles)              # gate
        assert not any("Old honey market" in t for t in titles)   # older than 30 days
        assert any("Hot honey glazed chicken" in t for t in titles)  # honey, but low relevance
        orig = next(r for r in rows if r.publisher == "Example Wire")
        dup = next(r for r in rows if r.publisher == "Agri Daily Test")
        assert dup.duplicate_of_id == orig.id and orig.duplicate_count == 1
        recipe = next(r for r in rows if "chicken" in r.title)
        duties = next(r for r in rows if "anti-dumping" in r.title)
        assert duties.relevance_score > recipe.relevance_score
        assert set(duties.countries) >= {"VNM", "IND", "USA"} and "tariffs" in duties.topics
        src = s.scalars(select(Source).where(Source.key == "news_gn_en_honey_prices")).one()
        assert src.last_run_status == "success" and str(src.latest_published_at) == "2026-11-01"
    # same bytes again -> nothing new
    res2 = run_with_routes("news_gn_en_honey_prices", routes)
    assert res2["status"] == "no_change" and res2["new"] == 0


def test_rss_collector_end_to_end(run_with_routes, session_factory, frozen_now):
    res = run_with_routes("news_bee_culture", {"https://beeculture.com/feed/": fixture_bytes("news/rss2_wordpress.xml")})
    assert res["status"] == "success" and res["new"] == 3, res  # "Subscribe" item filtered
    with session_factory() as s:
        rows = {r.title: r for r in s.scalars(select(NewsArticle))}
        crop = rows["National honey crop down 15% as packers bid up bulk white honey"]
        assert crop.url == "https://www.testbeemag.example/2026/11/honey-crop-down/"
        assert crop.image_url.endswith("drums.jpg") and "Argentina" in crop.snippet
        assert {"ARG", "BRA"} <= set(crop.countries)
        club = rows["Backyard beekeeping club opens its garden to school children"]
        assert club.relevance_score < crop.relevance_score


def test_collector_malformed_feed_is_partial(run_with_routes, frozen_now):
    res = run_with_routes("news_foodnavigator", {"https://www.foodnavigator.com/": fixture_bytes("news/malformed_rss.xml")})
    assert res["status"] == "partial" and res["new"] == 2


def test_collector_html_instead_of_feed_fails(run_with_routes):
    res = run_with_routes("news_apimondia", {"https://apimondia.org/feed/": (200, fixture_bytes("news/not_a_feed.html"), "text/html")})
    assert res["status"] == "failed" and "HTML" in res["error"]


def test_collector_offline(run_with_routes):
    res = run_with_routes("news_bee_culture", {})
    assert res["status"] == "offline"


# ---------------------------------------------------------------------------
# Real captures (2026-11-04, fixtures/news/real_*.xml)
# ---------------------------------------------------------------------------

REAL_NOW = datetime(2026, 11, 4, 19, 0)


@pytest.fixture()
def real_now(monkeypatch):
    from paladex.collectors import news_feeds

    monkeypatch.setattr(news_feeds, "utcnow", lambda: REAL_NOW)
    monkeypatch.setattr(ns, "utcnow", lambda: REAL_NOW)
    return REAL_NOW


def test_real_ec_agri_feed_parses_and_is_filtered(run_with_routes, session_factory, real_now):
    from paladex.collectors.news_feeds import parse_feed

    spec = _spec("news_ec_agri")
    items, warnings = parse_feed(fixture_bytes("news/real_ec_agri_news.xml"), spec)
    assert warnings == [] and len(items) == 4
    first = items[0]
    assert first["title"] == "EU agri-food exports stable as imports decline slightly"
    assert first["url"].startswith("https://agriculture.ec.europa.eu/media/news/")
    assert first["published_at"] == datetime(2026, 10, 29, 10, 54, 43)    # +0100 -> UTC
    assert first["language"] == "en" and first["publisher"].startswith("European Commission")
    assert first["image_url"].endswith(".jpg")                               # <enclosure>
    # general agriculture news: nothing about honey, so nothing is stored (by design)
    res = run_with_routes("news_ec_agri", {spec.url: fixture_bytes("news/real_ec_agri_news.xml")})
    assert res["status"] == "no_change" and res["seen"] == 4 and res["new"] == 0, res


def test_real_bee_culture_items_without_podcast_boilerplate(run_with_routes, session_factory, real_now):
    res = run_with_routes("news_bee_culture", {"https://beeculture.com/feed/": fixture_bytes("news/real_beeculture.xml")})
    assert res["status"] == "success" and res["new"] == 3, res
    with session_factory() as s:
        rows = {r.title: r for r in s.scalars(select(NewsArticle))}
    assert set(rows) == {"Beekeeping is a Crime", "The Past One Hundred Years Of Beekeeping",
                         "Microplastics and Honey Bee Health"}
    for r in rows.values():
        assert r.publisher == "Bee Culture (Root Publications)" and r.language == "en"
        assert r.url.startswith("https://beeculture.com/") and r.published_at.year == 2026
        assert "Click Here" not in r.snippet and "Read along below" not in r.snippet
    assert rows["The Past One Hundred Years Of Beekeeping"].snippet.startswith("Are We Any Better Off? By: James E. Tew")


def test_real_apimondia_items_gate_and_tags(run_with_routes, session_factory, real_now):
    res = run_with_routes("news_apimondia", {"https://apimondia.org/feed/": fixture_bytes("news/real_apimondia.xml")})
    assert res["status"] == "success" and res["new"] == 3, res
    with session_factory() as s:
        rows = {r.title: r for r in s.scalars(select(NewsArticle))}
    # "farmers are renting more beehives ... pollination": beekeeping news, no longer filtered out
    brazil = rows["Brazil, More Beehives to Mitigate El Niño Effects"]
    assert "BRA" in brazil.countries and "first appeared on" not in brazil.snippet
    # Apimondia's congress is not a legislature
    congress = rows["Save the Date: the 50th Apimondia Congress, Dubai 2027"]
    assert "policy" not in (congress.topics or [])
    visit = rows["Apimondia: Official Visit of the President to Romania and Moldova"]
    assert visit.countries[:2] == ["ROU", "MDA"]


def test_real_american_bee_journal_garbage_containers_are_not_trade(run_with_routes, session_factory, real_now):
    res = run_with_routes("news_american_bee_journal",
                          {"https://americanbeejournal.com/feed/": fixture_bytes("news/real_american_bee_journal.xml")})
    assert res["status"] == "success" and res["new"] == 2, res
    with session_factory() as s:
        rows = list(s.scalars(select(NewsArticle)))
    nest = next(r for r in rows if "Just One Big Bee Nest" in r.title)
    assert "trade" not in (nest.topics or []) and "bulk" not in nest.relevance_reason
    sioux = next(r for r in rows if r.title.startswith("SIOUX HONEY ASSOCIATION"))
    assert "companies" in sioux.topics and sioux.relevance_score > nest.relevance_score
    assert sioux.publisher == "Dadant & Sons"


def test_freight_containers_still_tag_trade():
    assert "trade" in ns.tag_topics("US honey imports", "Imports rose 6 percent; 202 containers arrived")
    assert "trade" in ns.tag_topics("Argentine exporters", "shipping containers of bulk honey left Buenos Aires")
    assert "trade" not in ns.tag_topics("Yellowjackets", "yellowjackets buzzing the garbage containers")


@pytest.mark.parametrize("text", ["Honey producers urge Congress to act on tariffs",
                                  "El Congreso aprobó la ley de etiquetado de la miel"])
def test_legislature_congress_is_still_policy(text):
    assert "policy" in ns.tag_topics(text)


@pytest.mark.parametrize("text", ["Save the Date: the 50th Apimondia Congress, Dubai 2027",
                                  "the 50th Apimondia International Apicultural Congress",
                                  "Congreso Internacional de Apicultura en Mendoza"])
def test_beekeeping_congress_is_not_policy(text):
    assert "policy" not in ns.tag_topics(text)


def test_beehive_is_bee_context_only():
    assert ns.is_honey_related("Farmers rent more beehives", "heavy rain raises concerns about pollination")
    assert not ns.is_honey_related("Ministers return to the Beehive", "The cabinet met in Wellington")


# ---------------------------------------------------------------------------
# LLM providers (respx, no real calls)
# ---------------------------------------------------------------------------


def _settings(**kw):
    from paladex.config import Settings

    return Settings(_env_file=None, **kw)


def test_llm_unavailable_without_key():
    from paladex.services import llm

    with pytest.raises(llm.LLMUnavailable):
        llm.complete_json("s", "u", settings=_settings(llm_provider="anthropic", anthropic_api_key=None))
    with pytest.raises(llm.LLMUnavailable):
        llm.complete_json("s", "u", settings=_settings(llm_provider="none"))


def test_anthropic_request_format():
    from paladex.services import llm

    s = _settings(llm_provider="anthropic", anthropic_api_key="sk-ant-TEST", anthropic_model="claude-test-model")
    reply = {"content": [{"type": "text", "text": 'Here you go:\n```json\n{"articles": [{"id": 1}],}\n```'}],
             "stop_reason": "end_turn"}
    with respx.mock(assert_all_called=True) as m:
        route = m.post(llm.ANTHROPIC_URL).mock(return_value=httpx.Response(200, json=reply))
        out = llm.complete_json("SYSTEM", "USER", {"articles": []}, max_tokens=321, settings=s)
    assert out == {"articles": [{"id": 1}]}
    req = route.calls[0].request
    assert req.headers["x-api-key"] == "sk-ant-TEST"
    assert req.headers["anthropic-version"] == "2023-06-01"
    assert "authorization" not in req.headers
    body = json.loads(req.content)
    assert body["model"] == "claude-test-model" and body["max_tokens"] == 321
    assert body["system"].startswith("SYSTEM") and '"articles"' in body["system"]
    assert body["messages"] == [{"role": "user", "content": "USER"}]


def test_openai_request_format():
    from paladex.services import llm

    s = _settings(llm_provider="openai", openai_api_key="sk-oa-TEST", openai_model="gpt-test",
                  anthropic_api_key="sk-ant-SHOULD-NOT-LEAK")
    reply = {"choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}]}
    with respx.mock(assert_all_called=True) as m:
        route = m.post(llm.OPENAI_URL).mock(return_value=httpx.Response(200, json=reply))
        assert llm.complete_json("SYS", "USR", None, max_tokens=50, settings=s) == {"ok": True}
    req = route.calls[0].request
    assert req.headers["authorization"] == "Bearer sk-oa-TEST"
    assert "x-api-key" not in req.headers and b"SHOULD-NOT-LEAK" not in req.content
    body = json.loads(req.content)
    assert body["model"] == "gpt-test" and body["response_format"] == {"type": "json_object"}
    assert body["max_completion_tokens"] == 50
    assert body["messages"][0]["role"] == "system" and body["messages"][1] == {"role": "user", "content": "USR"}


def test_llm_retries_once_then_errors_without_leaking_key(monkeypatch):
    from paladex.services import llm

    monkeypatch.setattr(llm.time, "sleep", lambda *_: None)
    s = _settings(llm_provider="anthropic", anthropic_api_key="sk-ant-SECRET")
    ok = {"content": [{"type": "text", "text": '{"a": 1}'}]}
    with respx.mock() as m:
        route = m.post(llm.ANTHROPIC_URL).mock(side_effect=[httpx.Response(529, json={"error": {"message": "overloaded"}}),
                                                            httpx.Response(200, json=ok)])
        assert llm.complete_json("s", "u", settings=s) == {"a": 1}
        assert route.call_count == 2
    with respx.mock() as m:
        route = m.post(llm.ANTHROPIC_URL).mock(return_value=httpx.Response(500, json={"error": {"message": "boom"}}))
        with pytest.raises(llm.LLMError) as exc:
            llm.complete_json("s", "u", settings=s)
        assert route.call_count == 2 and "SECRET" not in str(exc.value) and "boom" in str(exc.value)
    with respx.mock() as m:
        route = m.post(llm.ANTHROPIC_URL).mock(return_value=httpx.Response(401, json={"error": {"message": "bad key"}}))
        with pytest.raises(llm.LLMError):
            llm.complete_json("s", "u", settings=s)
        assert route.call_count == 1  # auth errors are not retried


def test_extract_json_variants():
    from paladex.services import llm

    assert llm.extract_json('{"a": 1}') == {"a": 1}
    assert llm.extract_json('Sure! {"a": [1, 2,],} Hope it helps') == {"a": [1, 2]}
    assert llm.extract_json('```\n[{"id": 3}]\n```') == {"items": [{"id": 3}]}
    with pytest.raises(llm.LLMError):
        llm.extract_json("no json here")


# ---------------------------------------------------------------------------
# AI enrichment (mocked LLM)
# ---------------------------------------------------------------------------


@pytest.fixture()
def llm_on(monkeypatch, db):
    from paladex import config

    monkeypatch.setenv("PALADEX_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("PALADEX_ANTHROPIC_API_KEY", "sk-ant-TEST")
    monkeypatch.setenv("PALADEX_ANTHROPIC_MODEL", "claude-test")
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


def test_enrich_noop_without_llm(db, monkeypatch):
    from paladex.services import ai_enrich, llm

    _ingest(db, url="https://x.example/1", title="US honey prices fall as imports from Argentina rise")
    db.commit()
    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: pytest.fail("LLM must not be called"))
    stats = ai_enrich.enrich_news(db)
    assert stats["enabled"] is False and stats["processed"] == 0


def test_enrich_flow_with_mocked_llm(db, llm_on, monkeypatch):
    from paladex.services import ai_enrich, llm

    a, _ = _ingest(db, url="https://x.example/1", title="US honey prices fall as imports from Argentina rise",
                   snippet="Bulk white honey traded at 2.10 dollars per pound, down from 2.40 a year earlier, packers said.")
    b, _ = _ingest(db, url="https://x.example/2", title="Prezzo del miele: crollo delle quotazioni in Ucraina",
                   language="it")
    low, _ = _ingest(db, url="https://x.example/3", title="Honey garlic chicken recipe")
    db.commit()
    calls = []

    def fake(system, user, schema_hint=None, max_tokens=1024, **kw):
        calls.append(user)
        assert "Use ONLY information" in system
        ids = [x["id"] for x in json.loads(user.split("\n", 1)[1])]
        assert low.id not in ids  # low relevance articles are not sent
        return {"articles": [
            {"id": a.id, "title_it": "Prezzi del miele USA in calo con l'aumento delle importazioni dall'Argentina",
             "title_en": a.title, "summary_it": "Il miele bianco sfuso è scambiato a 2.10 dollari la libbra, contro 2.40.",
             "summary_en": "Bulk honey traded at 2.10 USD/lb, 25% lower than last year."},  # 25 is invented
            {"id": b.id, "title_it": b.title, "title_en": "Honey price: quotations collapse in Ukraine",
             "summary_it": "Le quotazioni del miele in Ucraina sono in forte calo. Informazioni limitate: la fonte fornisce solo il titolo.",
             "summary_en": "Honey quotations in Ukraine are falling sharply. Limited information: the source provides only the headline."},
        ]}

    monkeypatch.setattr(llm, "complete_json", fake)
    stats = ai_enrich.enrich_news(db)
    assert stats["processed"] == 2 and len(calls) == 1
    db.refresh(a)
    db.refresh(b)
    assert a.summary_it.startswith("Il miele") and a.summary_en is None  # number guard rejected "25%"
    assert a.ai_model == "anthropic:claude-test" and a.ai_processed_at is not None
    assert b.title_en == "Honey price: quotations collapse in Ukraine"
    assert a.snippet.startswith("Bulk white honey")  # the source excerpt is never touched
    # second run: nothing left to do
    calls.clear()
    assert ai_enrich.enrich_news(db)["candidates"] == 0 and calls == []


def test_translate_article(db, llm_on, monkeypatch):
    from paladex.services import ai_enrich, llm

    a, _ = _ingest(db, url="https://x.example/9", title="Honey exports from Brazil hit a record")
    db.commit()
    monkeypatch.setattr(llm, "complete_json", lambda *args, **kw: {"articles": [
        {"id": a.id, "title_it": "Export di miele dal Brasile a livello record",
         "summary_it": "Le esportazioni di miele dal Brasile hanno raggiunto un record."}]})
    out = ai_enrich.translate_article(db, a.id, "it")
    assert out.title_it == "Export di miele dal Brasile a livello record" and out.ai_model == "anthropic:claude-test"
    with pytest.raises(LookupError):
        ai_enrich.translate_article(db, 999999, "it")


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@pytest.fixture()
def news_rows(db):
    now = utcnow()
    gn = _source(db, "news_gn_en_honey_prices")
    it = _source(db, "news_gn_it_prezzo_miele")
    bc = _source(db, "news_bee_culture")
    rows = {}
    rows["duties"], _ = ns.ingest_article(db, gn, url="https://a.example/duties", publisher="Outlet A",
                                          title="US sets anti-dumping duties on honey from Vietnam and India",
                                          published_at=now - timedelta(days=1))
    rows["duties_dup"], _ = ns.ingest_article(db, gn, url="https://b.example/duties", publisher="Outlet B",
                                              title="US sets anti-dumping duties on honey from Vietnam and India",
                                              published_at=now - timedelta(days=1, hours=-3))
    rows["prezzo"], _ = ns.ingest_article(db, it, url="https://c.example/prezzo", publisher="Testata IT",
                                          title="Prezzo del miele argentino in calo, quotazioni ai minimi",
                                          published_at=now - timedelta(days=3), language="it")
    rows["varroa"], _ = ns.ingest_article(db, bc, url="https://d.example/varroa",
                                          title="Varroa: colony losses climb after a warm autumn",
                                          snippet="Beekeepers in Ontario reported heavier than usual colony losses.",
                                          published_at=now - timedelta(days=20))
    rows["recipe"], _ = ns.ingest_article(db, gn, url="https://e.example/recipe", title="Honey garlic chicken recipe",
                                          published_at=now - timedelta(days=2))
    db.commit()
    return rows


def test_api_list_default_and_duplicates(api, news_rows):
    r = api.get("/api/news")
    assert r.status_code == 200
    data = r.json()
    ids = [i["id"] for i in data["items"]]
    assert news_rows["duties_dup"].id not in ids and data["total"] == 4
    duties = next(i for i in data["items"] if i["id"] == news_rows["duties"].id)
    assert duties["duplicate_count"] == 1
    assert [o["publisher"] for o in duties["duplicate_outlets"]] == ["Outlet B"]
    assert duties["source"]["key"] == "news_gn_en_honey_prices" and duties["reliability"] == "aggregator"
    assert duties["relevance_level"] == "high" and "Dazi" in duties["relevance_reason_it"]
    assert duties["display"]["it"]["needs_translation"] is True and duties["display"]["en"]["title_is_ai"] is False
    assert data["llm_enabled"] is False and data["updated"]["sources_total"] >= 15
    # newest first
    assert ids[0] == news_rows["duties"].id
    r2 = api.get("/api/news", params={"include_duplicates": "true"})
    items = {i["id"]: i for i in r2.json()["items"]}
    assert r2.json()["total"] == 5 and items[news_rows["duties_dup"].id]["duplicate_of"]["publisher"] == "Outlet A"


def test_api_filters(api, news_rows):
    def ids(**params):
        return {i["id"] for i in api.get("/api/news", params=params).json()["items"]}

    assert ids(country="ARG") == {news_rows["prezzo"].id}
    assert ids(country="VNM,ARG") == {news_rows["duties"].id, news_rows["prezzo"].id}
    assert ids(topic="tariffs") == {news_rows["duties"].id}
    assert ids(source="news_bee_culture") == {news_rows["varroa"].id}
    assert ids(lang="it") == {news_rows["prezzo"].id}
    assert ids(q="varroa autumn") == {news_rows["varroa"].id}
    assert ids(q="Ontario") == {news_rows["varroa"].id}          # excerpt search
    assert ids(q="100%_") == set()                                # LIKE wildcards escaped
    assert news_rows["recipe"].id not in ids(min_relevance=35)
    d_from = (utcnow() - timedelta(days=10)).date().isoformat()
    assert news_rows["varroa"].id not in ids(**{"from": d_from})
    d_to = (utcnow() - timedelta(days=10)).date().isoformat()
    assert ids(to=d_to) == {news_rows["varroa"].id}
    assert api.get("/api/news", params={"topic": "nope"}).status_code == 400
    assert api.get("/api/news", params={"country": "A;B"}).status_code == 400


def test_api_facets_and_pagination(api, news_rows):
    data = api.get("/api/news", params={"country": "ARG", "page_size": 1}).json()
    assert data["total"] == 1 and data["pages"] == 1
    countries = {c["key"]: c["count"] for c in data["facets"]["countries"]}
    # the country facet ignores its own filter (so alternatives stay visible)
    assert countries.get("VNM") == 1 and countries.get("ARG") == 1
    topics = {t["key"]: t["count"] for t in data["facets"]["topics"]}
    assert topics["prices"] == 1 and topics["tariffs"] == 0      # other facets respect the country filter
    assert len(data["facets"]["topics"]) == len(ns.TOPICS)
    srcs = {s["key"]: s["count"] for s in data["facets"]["sources"]}
    assert srcs == {"news_gn_it_prezzo_miele": 1}
    p1 = api.get("/api/news", params={"page_size": 2, "page": 1}).json()
    p2 = api.get("/api/news", params={"page_size": 2, "page": 2}).json()
    assert p1["pages"] == 2 and len(p1["items"]) == 2 and len(p2["items"]) == 2
    assert not {i["id"] for i in p1["items"]} & {i["id"] for i in p2["items"]}
    rel = api.get("/api/news", params={"sort": "relevance"}).json()["items"]
    assert [i["relevance_score"] for i in rel] == sorted((i["relevance_score"] for i in rel), reverse=True)


def test_api_detail_topics_translate(api, news_rows):
    d = api.get(f"/api/news/{news_rows['duties_dup'].id}").json()
    assert d["duplicate_of_id"] == news_rows["duties"].id
    assert [x["publisher"] for x in d["duplicates"]] == ["Outlet A", "Outlet B"]
    assert [x["is_this"] for x in d["duplicates"]] == [False, True]
    assert api.get("/api/news/999999").status_code == 404
    t = api.get("/api/news/topics").json()
    assert {x["key"] for x in t["topics"]} == set(ns.TOPICS) and t["topics"][0]["it"]
    r = api.post(f"/api/news/{news_rows['duties'].id}/translate", params={"lang": "it"})
    assert r.status_code == 409 and "IA" in r.json()["detail"]
    assert api.post(f"/api/news/{news_rows['duties'].id}/translate", params={"lang": "fr"}).status_code == 422


def test_api_translate_with_llm(api, news_rows, llm_on, monkeypatch):
    from paladex.services import llm

    aid = news_rows["duties"].id
    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: {"articles": [
        {"id": aid, "title_it": "Gli USA fissano dazi antidumping sul miele da Vietnam e India",
         "summary_it": "Gli Stati Uniti hanno fissato dazi antidumping sul miele proveniente da Vietnam e India."}]})
    r = api.post(f"/api/news/{aid}/translate", params={"lang": "it"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["display"]["it"]["title_is_ai"] is True and body["display"]["it"]["summary_is_ai"] is True
    assert body["ai_model"] == "anthropic:claude-test"


def test_runner_hook_calls_enrich(db, monkeypatch):
    from paladex.collectors import runner
    from paladex.services import ai_enrich

    called = []
    monkeypatch.setattr(ai_enrich, "enrich_news", lambda session, *a, **k: called.append(True) or {})
    runner.post_collection_hooks()
    assert called == [True]


# ---------------------------------------------------------------------------
# Regression tests: non-Latin scripts (F1), gate noise (F4, F10), USA over-tagging (F9)
# ---------------------------------------------------------------------------


def test_chinese_headline_is_tagged_and_scored():
    r = ns.analyse("中国蜂蜜出口价格下跌，美国反倾销税影响", language="zh")
    assert {"CHN", "USA"} <= set(r.countries)
    assert {"prices", "trade", "tariffs"} <= set(r.topics)
    assert r.score >= 60
    assert ns.tag_countries("中国和越南的蜂蜜") == ["CHN", "VNM"]
    assert "IND" not in ns.tag_countries("印度尼西亚蜂蜜进口")       # Indonesia is not India
    assert ns.analyse("中国蜂蜜出口十万吨", language="zh").factors["bulk"] is True
    assert ns.analyse("欧盟蜂蜜进口新规", language="zh").factors["eu"] is True


def test_ukrainian_russian_serbian_headlines_are_tagged():
    uk = ns.analyse("Україна стала лідером з експорту меду в ЄС", language="uk")
    assert "UKR" in uk.countries and "trade" in uk.topics and uk.factors["eu"] is True
    assert uk.score >= 35
    ru = ns.analyse("Россия: цены на мёд выросли, экспорт в Китай растёт", language="ru")
    assert {"RUS", "CHN"} <= set(ru.countries) and {"prices", "trade"} <= set(ru.topics)
    sr = ns.analyse("Srbija: izvoz meda u EU porastao", language="sr")
    assert "SRB" in sr.countries and "trade" in sr.topics
    sr_cyr = ns.analyse("Србија повећала извоз меда", language="sr")
    assert sr_cyr.is_honey and "SRB" in sr_cyr.countries and "trade" in sr_cyr.topics
    assert "tariffs" in ns.tag_topics("США ввели антидемпінгове мито на китайський мед")
    assert ns.tag_countries("Италия и Венгрия") == ["ITA", "HUN"]
    assert ns.tag_countries("Вʼєтнам") == ["VNM"]                       # Ukrainian apostrophe U+02BC
    assert ns.tag_countries("Индивидуальные пасечники") == []            # "инди..." is not India


@pytest.mark.parametrize("title", ["Giá bán mật ong tăng mạnh", "Nhật Bản nhập khẩu mật ong Việt Nam"])
def test_vietnamese_ban_is_not_an_import_ban(title):
    assert ns.is_honey_related(title, language="vi")
    assert "import_restrictions" not in ns.tag_topics(title)


def test_english_ban_still_tagged():
    assert "import_restrictions" in ns.tag_topics("Ban on Chinese honey extended")
    assert "import_restrictions" in ns.tag_topics("BAN ON HONEY IMPORTS")


def test_enrich_includes_foreign_script_items_below_medium(db, llm_on, monkeypatch):
    from paladex.services import ai_enrich, llm

    gd = _source(db, "news_gdelt")
    zh, _ = _ingest(db, gd, url="https://x.example/zh", title="蜂蜜节在杭州举行", language="zh")
    low, _ = _ingest(db, url="https://x.example/en", title="Honey garlic chicken recipe")
    db.commit()
    assert zh.relevance_score < ai_enrich.MIN_RELEVANCE
    sent = []

    def fake(system, user, schema_hint=None, max_tokens=1024, **kw):
        sent.extend(x["id"] for x in json.loads(user.split("\n", 1)[1]))
        return {"articles": []}

    monkeypatch.setattr(llm, "complete_json", fake)
    ai_enrich.enrich_news(db)
    assert zh.id in sent and low.id not in sent


@pytest.mark.parametrize("text,lang", [
    ("Miele raises prices on dishwashers amid US tariffs", "en"),
    ("Miele taglia 1.300 posti: la produzione di lavatrici si sposta in Polonia", "it"),
    ("PayPal Honey extension accused of fraud by YouTubers", "en"),
    ("PayPal's Honey price tracker", "en"),
    ("Luna de miel en el Caribe: precios para 2027", "es"),
    ("FDA warns consumers about honey products laced with sildenafil", "en"),
    ("Мед. заклади отримали нове обладнання", "uk"),
])
def test_gate_rejects_known_noise(text, lang):
    assert not ns.is_honey_related(text, language=lang)


@pytest.mark.parametrize("text,lang", [
    ("Miele, crollano i prezzi all'origine", "it"),
    ("Miele argentino: export in crescita", "it"),
    ("FDA import alert on adulterated honey from India", "en"),
    ("Українські пасічники продають мед.", "uk"),
])
def test_gate_keeps_honey_next_to_noise_rules(text, lang):
    assert ns.is_honey_related(text, language=lang)


def test_google_news_queries_carry_noise_exclusions():
    from urllib.parse import parse_qs, urlsplit

    from paladex.collectors.news_feeds import FEEDS

    seen = set()
    for f in FEEDS:
        if f.family != "google_news":
            continue
        q = parse_qs(urlsplit(f.url).query)["q"][0]
        seen.add(f.language)
        if f.language == "it":
            assert "-lavatrice" in q and "-lavastoviglie" in q and "-elettrodomestici" in q, q
        elif f.language == "en":
            assert '-"honey singh"' in q and "-paypal" in q, q
        elif f.language == "es":
            assert '-"luna de miel"' in q, q
        elif f.language == "de":
            assert "-Miele" in q, q
    assert {"it", "en", "es", "de"} <= seen


@pytest.mark.parametrize("text", ["我国蜂产品出口创新高", "洋槐蜜出口价格上涨", "蜜蜂养殖户收入下降",
                                  "Бджолярі скаржаться на низькі закупівельні ціни",
                                  "Бджола під загрозою: пасіки гинуть"])
def test_gate_non_latin_bee_terms(text):
    assert ns.honey_terms(text)


@pytest.mark.parametrize("text", ["闺蜜一起去度蜜月", "甜蜜的生活", "Медична реформа", "Медовий місяць"])
def test_gate_non_latin_lookalikes(text):
    assert ns.honey_terms(text) == []


def test_country_tagging_continental_american_and_foreign_fda():
    assert ns.tag_countries("South American honey production hit by drought") == []
    assert ns.tag_countries("Latin American honey exporters eye EU market") == []
    assert ns.tag_countries("Brazil and other South American honey exporters") == ["BRA"]
    assert ns.tag_countries("Philippine FDA warns against unregistered honey products") == []
    assert ns.tag_countries("Thai FDA seizes fake honey") == ["THA"]
    assert ns.tag_countries("FDA honey import alert") == ["USA"]
    assert ns.tag_countries("American Honey Producers Association") == ["USA"]


# ---------------------------------------------------------------------------
# Regression tests: fuzzy dedup guards (F2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("first,second", [
    ("US sets anti-dumping duties on honey from Vietnam", "US sets anti-dumping duties on honey from Brazil"),
    ("Honey prices rise in Argentina this week", "Honey prices fall in Argentina this week"),
    ("EU honey imports from Ukraine hit record", "EU honey imports from China hit record"),
    ("Prezzo del miele in calo", "Prezzo del miele in aumento"),
    ("Commerce issues preliminary determination in honey anti-dumping case",
     "Commerce issues final determination in honey anti-dumping case"),
    ("Honey import duty raised to 12% on Chinese honey", "Honey import duty raised to 15% on Chinese honey"),
])
def test_fuzzy_dedup_keeps_different_stories_apart(db, first, second):
    _, oa = _ingest(db, url="https://a.example/1", title=first)
    b, ob = _ingest(db, url="https://b.example/2", title=second)
    assert (oa, ob) == ("new", "new") and b.duplicate_of_id is None


def test_fuzzy_dedup_still_merges_same_direction_rewording(db):
    _, oa = _ingest(db, url="https://a.example/1", title="Honey prices rise in Argentina as drought cuts the harvest")
    _, ob = _ingest(db, url="https://b.example/2", title="Honey prices climb in Argentina as drought cuts the harvest")
    assert (oa, ob) == ("new", "duplicate")


def test_api_country_filter_keeps_story_differing_only_by_origin(api, db):
    now = utcnow()
    _ingest(db, url="https://a.example/vn", title="US sets anti-dumping duties on honey from Vietnam",
            published_at=now - timedelta(hours=5))
    br, _ = _ingest(db, url="https://b.example/br", title="US sets anti-dumping duties on honey from Brazil",
                    published_at=now - timedelta(hours=2))
    db.commit()
    data = api.get("/api/news", params={"country": "BRA"}).json()
    assert [i["id"] for i in data["items"]] == [br.id]
    assert "BRA" in {c["key"] for c in data["facets"]["countries"]}


# ---------------------------------------------------------------------------
# Regression tests: AI number guard (F5)
# ---------------------------------------------------------------------------

_FIXTURE_SOURCE = ("US honey prices fall as imports from Argentina rise\n"
                   "Bulk white honey traded at 2.10 dollars per pound, down from 2.40 a year earlier, packers said.")


@pytest.mark.parametrize("source,output,ok", [
    ("US honey imports in 2026: Argentina leads", "Argentina accounts for 20% of US honey imports", False),
    ("US honey imports in 2026: Argentina leads", "Imports rose 6 percent; 202 containers arrived", False),
    ("Bulk honey at 2.10 dollars per pound", "Honey traded at $210 per tonne", False),
    ("Bulk honey at 2.10 dollars per pound", "Il miele a 21,0 dollari", False),
    ("Bulk honey at 2.10 dollars per pound", "Honey at 1 dollar", False),
    ("Exports of 3,000 tonnes", "Esportazioni di 30 tonnellate", False),
    (_FIXTURE_SOURCE, "Bulk honey traded at 2.10 USD/lb, 10% lower than last year.", False),
    (_FIXTURE_SOURCE, "Il miele bianco sfuso è scambiato a 2.10 dollari la libbra, contro 2.40.", True),
    ("Bulk honey at 2.10 dollars per pound", "Miele sfuso a 2,10 dollari la libbra", True),
    ("Exports of 3,000 tonnes", "Esportazioni di 3.000 tonnellate", True),
    ("Exports of 3,000 tonnes", "Exports of 3000 tonnes", True),
    ("Prices up 20 % this year", "Prices up 20% this year", True),
    ("In 2025 15 tonnes were exported", "15 tonnes exported in 2025", True),
    ("Honey prices, 2026, 12 percent higher", "Prices 12 percent higher in 2026", True),
    ("Export di 1 200 tonnellate", "Exports of 1,200 tonnes", True),
    ("Export di 1 200 tonnellate", "Export di 1.200 tonnellate", True),
    ("Honey news", None, True),
])
def test_ai_number_guard(source, output, ok):
    from paladex.services import ai_enrich

    assert ai_enrich._numbers_ok(output, source) is ok


# ---------------------------------------------------------------------------
# Regression tests: excerpt gap-fill (F7) and one enrichment pass at a time (F8)
# ---------------------------------------------------------------------------


def test_feed_excerpt_fills_gap_left_by_gdelt(db):
    gd = _source(db, "news_gdelt")
    fsn = _source(db, "news_food_safety_news")
    url = "https://www.foodsafetynews.com/2026/11/eu-action-finds-widespread-honey-fraud/"
    pub = (utcnow() - timedelta(hours=6)).replace(microsecond=0)
    a, o1 = ns.ingest_article(db, gd, url=url, title="EU action finds widespread honey fraud", published_at=pub,
                              publisher="foodsafetynews.com")
    assert o1 == "new" and a.snippet is None and not a.countries
    score_before = a.relevance_score
    a.summary_it = "Un'azione UE rileva frodi diffuse sul miele. Informazioni limitate: la fonte fornisce solo il titolo."
    a.title_it = "Un'azione UE rileva frodi diffuse sul miele"
    a.ai_processed_at = utcnow()
    db.commit()
    b, o2 = ns.ingest_article(
        db, fsn, url=url, title="EU action finds widespread honey fraud (updated)", publisher="Food Safety News",
        published_at=pub - timedelta(days=1),
        snippet="Almost half of honey samples imported into the EU from China, Turkey and Ukraine were suspected "
                "of being adulterated with cheap sugar syrups, according to the European Commission.")
    assert o2 == "unchanged" and b.id == a.id
    assert b.snippet.startswith("Almost half of honey samples")
    assert {"CHN", "TUR", "UKR"} <= set(b.countries)
    assert "trade" in b.topics and "adulteration" in b.topics
    assert b.relevance_score > score_before
    # provenance as first stored
    assert b.source_id == gd.id and b.published_at == pub and b.title == "EU action finds widespread honey fraud"
    assert b.url == url and b.publisher == "foodsafetynews.com"
    # the AI summary was written from the headline only: it is dropped and re-queued (titles kept)
    assert b.ai_processed_at is None and b.summary_it is None
    assert b.title_it == "Un'azione UE rileva frodi diffuse sul miele"
    # a later copy never overwrites an excerpt we already hold
    c, o3 = ns.ingest_article(db, fsn, url=url, title="x", snippet="Something else entirely about honey " * 3)
    assert o3 == "unchanged" and c.snippet.startswith("Almost half of honey samples")


def test_enrich_runs_are_not_concurrent(db, llm_on, monkeypatch):
    import threading

    from paladex.db import session_scope
    from paladex.services import ai_enrich, llm

    for i, origin in enumerate(("Argentina", "Brazil", "Vietnam", "Ukraine")):
        _ingest(db, url=f"https://x.example/c{i}", title=f"Honey export prices from {origin} hit record high")
    db.commit()
    entered, release = threading.Event(), threading.Event()
    sent = []

    def fake(system, user, schema_hint=None, max_tokens=1024, **kw):
        ids = [x["id"] for x in json.loads(user.split("\n", 1)[1])]
        sent.extend(ids)
        entered.set()
        release.wait(timeout=5)
        return {"articles": [{"id": i, "title_it": "Titolo"} for i in ids]}

    monkeypatch.setattr(llm, "complete_json", fake)
    results = {}

    def first():
        with session_scope() as s:
            results["first"] = ai_enrich.enrich_news(s)

    t = threading.Thread(target=first)
    t.start()
    assert entered.wait(timeout=5)
    try:
        with session_scope() as s:
            results["second"] = ai_enrich.enrich_news(s)
    finally:
        release.set()
        t.join(timeout=10)
    assert results["second"].get("skipped") == "already_running"
    assert results["first"]["processed"] == 4
    assert len(sent) == len(set(sent)) == 4
