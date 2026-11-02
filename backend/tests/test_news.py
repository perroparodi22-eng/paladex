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
    assert rows["news_europarl_agri"].reliability == "official"
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
    res = run_with_routes("news_bee_culture", {"https://www.beeculture.com/feed/": fixture_bytes("news/rss2_wordpress.xml")})
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
    res = run_with_routes("news_apimondia", {"https://www.apimondia.org/feed/": (200, fixture_bytes("news/not_a_feed.html"), "text/html")})
    assert res["status"] == "failed" and "HTML" in res["error"]


def test_collector_offline(run_with_routes):
    res = run_with_routes("news_bee_culture", {})
    assert res["status"] == "offline"


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
