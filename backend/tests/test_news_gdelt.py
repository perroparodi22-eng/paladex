"""GDELT DOC 2.0 collector (reconstructed responses; see fixtures/news/README.md)."""
import json

from sqlalchemy import select

from paladex.collectors import news_gdelt
from paladex.models import NewsArticle, Source

API = "https://api.gdeltproject.org/api/v2/doc/doc"


def _payload(articles):
    return json.dumps({"articles": articles}).encode()


ARTICLES = [
    {"url": "https://www.example.it/economia/miele-prezzi-ingrosso-2026", "url_mobile": "",
     "title": "Miele, prezzi all'ingrosso in calo per l'import dall'Argentina", "seendate": "20261102T091500Z",
     "socialimage": "https://www.example.it/img/miele.jpg", "domain": "example.it", "language": "Italian",
     "sourcecountry": "Italy"},
    {"url": "https://news.example.com/honey-singh-concert", "title": "Honey Singh announces world tour",
     "seendate": "20261102T081500Z", "socialimage": "", "domain": "example.com", "language": "English",
     "sourcecountry": "India"},
    {"url": "https://www.example.cn/a/123", "title": "中国蜂蜜出口量增长", "seendate": "20261101T120000Z",
     "socialimage": "", "domain": "example.cn", "language": "Chinese", "sourcecountry": "China"},
]


def test_parse_response_variants():
    assert news_gdelt.parse_response(b"{}") == []
    assert news_gdelt.parse_response(b"") == []
    items = news_gdelt.parse_response(_payload(ARTICLES))
    assert items[0]["language"] == "it" and items[0]["publisher"] == "example.it"
    assert items[0]["published_at"].isoformat() == "2026-11-02T09:15:00"
    assert items[1]["image_url"] is None
    try:
        news_gdelt.parse_response(b"Please limit requests to one every 5 seconds")
    except news_gdelt.GdeltQueryError as exc:
        assert "limit requests" in str(exc)
    else:
        raise AssertionError("plain text must raise")


def test_build_url_encodes_query():
    url = news_gdelt.build_url('miele (prezzo OR prezzi) sourcelang:italian', "1d")
    assert url.startswith(API) and "mode=ArtList" in url and "format=json" in url and "timespan=1d" in url
    assert "sourcelang%3Aitalian" in url


def test_collector_end_to_end(run_with_routes, session_factory):
    res = run_with_routes("news_gdelt", {API: _payload(ARTICLES)})
    assert res["status"] in ("success", "partial"), res
    with session_factory() as s:
        rows = s.scalars(select(NewsArticle)).all()
        titles = {r.title for r in rows}
        assert "Honey Singh announces world tour" not in titles        # noise filtered
        assert any("Argentina" in t for t in titles)
        assert any("蜂蜜" in t for t in titles)                        # non-Latin honey term passes gate
        it = next(r for r in rows if "Argentina" in r.title)
        assert it.snippet is None and it.language == "it" and "ARG" in (it.countries or [])
    # second identical run: nothing new
    res2 = run_with_routes("news_gdelt", {API: _payload(ARTICLES)})
    assert res2["new"] == 0


def test_rejected_queries_warn_but_do_not_fail(run_with_routes):
    # every query rejected -> failed; the message is explicit
    res = run_with_routes("news_gdelt", {API: (200, b"Your search contained a phrase that was too short")})
    assert res["status"] == "failed" and "GDELT" in res["error"]


def test_google_news_feeds_are_opt_in(db):
    srcs = {s.key: s for s in db.scalars(select(Source).where(Source.category == "news"))}
    assert srcs["news_gdelt"].enabled is True
    gn = [s for k, s in srcs.items() if k.startswith("news_gn_")]
    assert gn and all(s.enabled is False for s in gn)
    assert all("personale" in (s.terms_note or "") for s in gn)
