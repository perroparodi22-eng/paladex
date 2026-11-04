"""GDELT DOC 2.0 collector.

Real captures (2026-11-04) are in fixtures/news/real_gdelt_*; the other payloads below are
reconstructed (see fixtures/news/README.md)."""
import json
import re
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from conftest import fixture_bytes
from paladex.collectors import news_gdelt
from paladex.models import AppSetting, NewsArticle, Source, utcnow

API = "https://api.gdeltproject.org/api/v2/doc/doc"
THROTTLE = (429, fixture_bytes("news/real_gdelt_throttle.txt"))


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


def _query_url_rx(q, timespan="7d"):
    return "^" + re.escape(news_gdelt.build_url(q.query, timespan)) + "$"


def _state(session_factory) -> dict:
    with session_factory() as s:
        row = s.get(AppSetting, news_gdelt.STATE_KEY)
        return dict(row.value) if row is not None else {}


def _set_state(session_factory, state: dict) -> None:
    with session_factory() as s:
        row = s.get(AppSetting, news_gdelt.STATE_KEY)
        if row is None:
            s.add(AppSetting(key=news_gdelt.STATE_KEY, value=state))
        else:
            row.value = state


@pytest.fixture()
def http_calls(monkeypatch):
    """URLs actually requested from GDELT (through CollectContext.fetch)."""
    from paladex.collectors import base

    calls = []
    real = base.CollectContext.fetch

    def spy(self, url, **kw):
        calls.append(url)
        return real(self, url, **kw)

    monkeypatch.setattr(base.CollectContext, "fetch", spy)
    return calls


@pytest.fixture()
def sleeps(monkeypatch):
    """Durations passed to time.sleep (sleeping is skipped in tests)."""
    out = []
    monkeypatch.setattr(news_gdelt.time, "sleep", lambda s: out.append(s))
    return out


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_parse_response_variants():
    assert news_gdelt.parse_response(b"{}") == []
    assert news_gdelt.parse_response(b"") == []
    items = news_gdelt.parse_response(_payload(ARTICLES))
    assert items[0]["language"] == "it" and items[0]["publisher"] == "example.it"
    assert items[0]["published_at"].isoformat() == "2026-11-02T09:15:00"
    assert items[1]["image_url"] is None
    with pytest.raises(news_gdelt.GdeltQueryError) as exc:
        news_gdelt.parse_response(THROTTLE[1])
    assert news_gdelt.is_throttle_text(str(exc.value))
    with pytest.raises(news_gdelt.GdeltQueryError) as exc:
        news_gdelt.parse_response(fixture_bytes("news/real_gdelt_too_short.txt"))
    assert not news_gdelt.is_throttle_text(str(exc.value)) and "too short" in str(exc.value)


def test_parse_real_capture():
    items = news_gdelt.parse_response(fixture_bytes("news/real_gdelt_honey_italian.json"))
    assert items, "the real capture holds articles"
    for it in items:
        assert it["url"].startswith("http") and it["title"]
        assert isinstance(it["published_at"], datetime)
        assert it["language"] == "it" and it["publisher"] and it["snippet"] is None


def test_build_url_encodes_query():
    url = news_gdelt.build_url('honey (price OR prices) sourcelang:italian', "1d")
    assert url.startswith(API) and "mode=ArtList" in url and "format=json" in url and "timespan=1d" in url
    assert "sourcelang%3Aitalian" in url


# ---------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------


def test_collector_end_to_end(run_with_routes, session_factory, http_calls):
    res = run_with_routes("news_gdelt", {API: _payload(ARTICLES)})
    assert res["status"] in ("success", "partial"), res
    assert len(http_calls) == news_gdelt.QUERIES_PER_RUN          # per-run budget
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


def test_rejected_queries_warn_and_fail_when_none_is_usable(run_with_routes, session_factory):
    # every query rejected -> failed; the message is explicit. Rejected queries rotate away.
    res = run_with_routes("news_gdelt", {API: (200, fixture_bytes("news/real_gdelt_too_short.txt"))})
    assert res["status"] == "failed" and "GDELT" in res["error"]
    assert any("too short" in w for w in res["warnings"])
    state = _state(session_factory)
    first = [q.key for q in news_gdelt.QUERIES[:news_gdelt.QUERIES_PER_RUN]]
    assert all(state["queries"][k]["last_try"] and "too short" in state["queries"][k]["last_error"] for k in first)
    assert news_gdelt.plan_queries(state)[0] == news_gdelt.QUERIES[news_gdelt.QUERIES_PER_RUN]


def test_google_news_feeds_are_opt_in(db):
    srcs = {s.key: s for s in db.scalars(select(Source).where(Source.category == "news"))}
    assert srcs["news_gdelt"].enabled is True
    gn = [s for k, s in srcs.items() if k.startswith("news_gn_")]
    assert gn and all(s.enabled is False for s in gn)
    assert all("personale" in (s.terms_note or "") for s in gn)


# ---------------------------------------------------------------------------
# Rotation and per-query windows
# ---------------------------------------------------------------------------


def test_rotation_covers_every_query_in_a_few_runs(run_with_routes, session_factory, monkeypatch):
    asked = []
    real = news_gdelt.build_url
    monkeypatch.setattr(news_gdelt, "build_url", lambda q, t: asked.append(q) or real(q, t))
    runs = -(-len(news_gdelt.QUERIES) // news_gdelt.QUERIES_PER_RUN)
    for i in range(runs):
        before = len(asked)
        res = run_with_routes("news_gdelt", {API: b"{}"})
        assert res["status"] in ("success", "no_change"), res
        assert len(asked) - before == news_gdelt.QUERIES_PER_RUN
    assert set(asked) == {q.query for q in news_gdelt.QUERIES}
    # the first rounds never repeat a query before every query has been asked once
    assert len(set(asked[:len(news_gdelt.QUERIES)])) == len(news_gdelt.QUERIES)


def test_window_timespan_covers_the_gap_since_last_success():
    now = datetime(2026, 11, 2, 8, 0)
    assert news_gdelt.window_timespan(now - timedelta(hours=61), now, False) == "3d"   # weekend off
    assert news_gdelt.window_timespan(now - timedelta(hours=2), now, False) == "1d"
    assert news_gdelt.window_timespan(now - timedelta(hours=22), now, False) == "1d"   # + 2 h overlap = 24 h
    assert news_gdelt.window_timespan(now - timedelta(hours=23), now, False) == "2d"
    assert news_gdelt.window_timespan(None, now, False) == "7d"
    assert news_gdelt.window_timespan(now - timedelta(hours=2), now, True) == "7d"
    assert news_gdelt.window_timespan(now - timedelta(days=12), now, True) == "13d"   # force never shortens
    assert news_gdelt.window_timespan(now - timedelta(days=200), now, False) == "90d"  # DOC API keeps ~3 months
    assert news_gdelt.window_timespan(now + timedelta(hours=3), now, False) == "1d"    # clock skew


def test_each_query_window_reaches_back_to_its_own_last_answer(run_with_routes, session_factory, monkeypatch):
    q0, q1, q2 = news_gdelt.QUERIES[:3]
    now = utcnow()
    _set_state(session_factory, {"queries": {
        q0.key: {"last_ok": (now - timedelta(hours=61)).isoformat(), "last_try": "2000-01-01T00:00:00"},
        q1.key: {"last_ok": (now - timedelta(hours=5)).isoformat(), "last_try": "2000-01-01T00:00:00"},
        q2.key: {"last_ok": None, "last_try": "2000-01-01T00:00:00"},     # deferred since: never answered
    }})
    # the rest were asked recently: q0..q2 come first
    state = _state(session_factory)
    for q in news_gdelt.QUERIES[3:]:
        state["queries"][q.key] = {"last_ok": now.isoformat(), "last_try": now.isoformat()}
    _set_state(session_factory, state)
    spans = {}
    real = news_gdelt.build_url
    monkeypatch.setattr(news_gdelt, "build_url", lambda q, t: spans.setdefault(q, t) and real(q, t))
    res = run_with_routes("news_gdelt", {API: _payload(ARTICLES)})
    assert res["status"] == "success", res
    assert spans == {q0.query: "3d", q1.query: "1d", q2.query: "7d"}


def test_capped_long_window_is_reported(run_with_routes, session_factory, monkeypatch):
    q0 = news_gdelt.QUERIES[0]
    _set_state(session_factory, {"queries": {q0.key: {"last_ok": (utcnow() - timedelta(hours=61)).isoformat()}}})
    monkeypatch.setattr(news_gdelt, "MAX_RECORDS", len(ARTICLES))
    res = run_with_routes("news_gdelt", {API: _payload(ARTICLES)})
    assert res["status"] == "partial", res
    assert any(q0.label in w and "limite" in w and "3d" in w for w in res["warnings"]), res["warnings"]


def test_parse_response_repairs_stray_backslashes_only():
    body = (b'{"articles":[{"url":"https://x.example/a","title":"Honey \\x prices C:\\\\path \\u00e8 \\"q\\"",'
            b'"seendate":"20261102T091500Z"}]}')
    items = news_gdelt.parse_response(body)
    assert items[0]["title"] == 'Honey \\x prices C:\\path \u00e8 "q"'
    with pytest.raises(ValueError):
        news_gdelt.parse_response(b'{"articles":[{"url":"https://x.example/b","title":"Honey "prices""}]}')


def test_malformed_json_skips_only_that_query(run_with_routes, session_factory):
    bad = b'{"articles":[{"url":"https://x.example/b","title":"Honey "prices" fall","seendate":"20261102T091500Z"}]}'
    q0 = news_gdelt.QUERIES[0]
    res = run_with_routes("news_gdelt", {_query_url_rx(q0): bad, API: _payload(ARTICLES)})
    assert res["status"] == "partial", res
    assert any(q0.label in w for w in res["warnings"]), res["warnings"]
    with session_factory() as s:
        titles = {r.title for r in s.scalars(select(NewsArticle))}
    assert any("Argentina" in t for t in titles)          # the other queries still ran


# ---------------------------------------------------------------------------
# Throttling: spacing, retry once, defer, cool-down, fail only after a day
# ---------------------------------------------------------------------------


def test_requests_are_spaced_from_the_previous_answer(run_with_routes, sleeps, http_calls):
    res = run_with_routes("news_gdelt", {API: _payload(ARTICLES)})
    assert res["status"] in ("success", "partial"), res
    gaps = [s for s in sleeps if s >= news_gdelt.MIN_GAP_SECONDS - 1]
    assert len(gaps) >= len(http_calls) - 1 >= 2           # a full gap before every request but the first


def _db_write_possible() -> bool:
    """True when another connection could start writing now (no open write transaction)."""
    import sqlite3

    from paladex.db import get_engine

    con = sqlite3.connect(get_engine().url.database, timeout=0.2)
    try:
        con.execute("BEGIN IMMEDIATE")
        con.rollback()
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        con.close()


def test_waits_never_hold_the_database_write_lock(run_with_routes, monkeypatch):
    """Minutes of spacing / back-off must not lock out the other collectors and API writes."""
    q0 = news_gdelt.QUERIES[0]
    free = []
    monkeypatch.setattr(news_gdelt.time, "sleep", lambda s: free.append(_db_write_possible()))
    # first query answers (articles stored), the next one is refused -> retry wait
    res = run_with_routes("news_gdelt", {_query_url_rx(q0): _payload(ARTICLES), API: THROTTLE})
    assert res["status"] == "partial", res
    assert free and all(free), free


def test_throttled_run_retries_once_then_defers_as_partial(run_with_routes, session_factory, sleeps, http_calls):
    res = run_with_routes("news_gdelt", {API: THROTTLE})
    assert res["status"] == "partial", res                 # not failed: the queries are deferred
    assert len(http_calls) == news_gdelt.MAX_REFUSALS_PER_RUN   # first try + one retry, then stop
    assert news_gdelt.RETRY_WAIT_SECONDS in sleeps
    assert any("rinviate" in w and "limit requests" in w for w in res["warnings"]), res["warnings"]
    state = _state(session_factory)
    assert state["throttle_streak"] == 1 and state["throttled_since"]
    assert datetime.fromisoformat(state["cooldown_until"]) > utcnow()
    q0, q1, q2, q3 = news_gdelt.QUERIES[:4]
    assert not any(v.get("last_try") for v in state["queries"].values())   # no answer: window unchanged
    assert state["queries"][q0.key]["last_refused"]
    # the queries never sent stay first in line; the refused one goes to the back
    assert news_gdelt.plan_queries(state) == [q1, q2, q3]
    assert news_gdelt.plan_queries(state, budget=len(news_gdelt.QUERIES))[-1] == q0

    # a run during the cool-down sends nothing at all
    http_calls.clear()
    res2 = run_with_routes("news_gdelt", {API: _payload(ARTICLES)})
    assert res2["status"] == "partial" and http_calls == [], res2
    assert any("rallentare" in w for w in res2["warnings"])


def test_cooldown_grows_and_success_resets_it(run_with_routes, session_factory):
    _set_state(session_factory, {"queries": {}, "throttle_streak": 2,
                                 "throttled_since": (utcnow() - timedelta(hours=3)).isoformat(),
                                 "cooldown_until": (utcnow() - timedelta(minutes=1)).isoformat()})
    res = run_with_routes("news_gdelt", {API: THROTTLE})
    assert res["status"] == "partial", res
    state = _state(session_factory)
    assert state["throttle_streak"] == 3
    wait = datetime.fromisoformat(state["cooldown_until"]) - utcnow()
    assert timedelta(minutes=news_gdelt.COOLDOWN_MINUTES[2] - 2) < wait <= timedelta(minutes=news_gdelt.COOLDOWN_MINUTES[2])

    state["cooldown_until"] = (utcnow() - timedelta(minutes=1)).isoformat()
    _set_state(session_factory, state)
    res = run_with_routes("news_gdelt", {API: _payload(ARTICLES)})
    assert res["status"] == "success", res
    state = _state(session_factory)
    assert state["throttle_streak"] == 0 and state["throttled_since"] is None and state["cooldown_until"] is None


def test_refused_for_a_day_fails(run_with_routes, session_factory):
    _set_state(session_factory, {"queries": {}, "throttle_streak": 6,
                                 "throttled_since": (utcnow() - timedelta(hours=25)).isoformat(),
                                 "cooldown_until": (utcnow() - timedelta(minutes=1)).isoformat()})
    res = run_with_routes("news_gdelt", {API: THROTTLE})
    assert res["status"] == "failed" and "24 ore" in res["error"], res
    assert _state(session_factory)["throttle_streak"] == 7          # the state survives the failure


def test_throttle_text_with_http_200_is_a_refusal_not_a_rejection(run_with_routes, session_factory):
    res = run_with_routes("news_gdelt", {API: (200, THROTTLE[1])})
    assert res["status"] == "partial", res
    assert _state(session_factory)["throttle_streak"] == 1


def test_throttle_mid_run_keeps_earlier_answers_and_defers_the_rest(run_with_routes, session_factory, http_calls):
    q0, q1, q2 = news_gdelt.QUERIES[:3]
    res = run_with_routes("news_gdelt", {_query_url_rx(q0): _payload(ARTICLES), API: THROTTLE})
    assert res["status"] == "partial", res
    assert any(q1.label in w and q2.label in w and "rinviate" in w for w in res["warnings"]), res["warnings"]
    with session_factory() as s:
        assert any("Argentina" in r.title for r in s.scalars(select(NewsArticle)))
    state = _state(session_factory)
    assert state["queries"][q0.key]["last_ok"] and state["throttle_streak"] == 0   # GDELT did answer
    assert state["cooldown_until"]                                                  # but slow down
    nxt = news_gdelt.plan_queries(state)
    assert nxt[0] == q2 and q0 not in nxt and q1 not in nxt     # not sent: first; refused/answered: back


def test_connection_reset_while_online_is_deferred(run_with_routes, session_factory, monkeypatch):
    from paladex.collectors import runner

    monkeypatch.setattr(runner, "is_online", lambda *a, **k: True)
    res = run_with_routes("news_gdelt", {})          # every request: ConnectError (as a reset at TLS time)
    assert res["status"] == "partial", res
    assert _state(session_factory)["throttle_streak"] == 1


def test_offline_pc_is_reported_as_offline(run_with_routes):
    res = run_with_routes("news_gdelt", {})          # is_online() is False in tests
    assert res["status"] == "offline", res


def test_server_error_is_deferred(run_with_routes, session_factory):
    res = run_with_routes("news_gdelt", {API: (503, b"Service Unavailable")})
    assert res["status"] == "partial", res


# ---------------------------------------------------------------------------
# Query design
# ---------------------------------------------------------------------------


def test_queries_are_well_formed():
    keys = [q.key for q in news_gdelt.QUERIES]
    assert len(set(keys)) == len(keys)
    for q in news_gdelt.QUERIES:
        assert q.query.count("(") == q.query.count(")") and q.query.count('"') % 2 == 0, q.key
        # OR blocks cannot be nested
        depth = 0
        for ch in q.query:
            depth += ch == "("
            depth -= ch == ")"
            assert 0 <= depth <= 1, q.key
        # GDELT rejects keywords that are too short ("蜂蜜" is 2 characters): none below 3
        bare = re.sub(r'"[^"]*"', " ", q.query)
        for tok in re.findall(r"[^\s()\"]+", bare):
            if tok in ("OR", "-") or ":" in tok:
                continue
            assert len(tok.lstrip("-")) >= 3, (q.key, tok)
        assert "sourcelang:" in q.query or "sourcecountry:" in q.query, q.key
        # GDELT matches the English machine translation: native keywords find nothing
        assert q.query.isascii(), q.key


def test_queries_cover_the_honey_languages():
    langs = set(re.findall(r"sourcelang:(\w+)", " ".join(q.query for q in news_gdelt.QUERIES)))
    assert {"english", "italian", "spanish", "portuguese", "chinese", "vietnamese", "ukrainian", "serbian",
            "german"} <= langs
    assert any("sourcecountry:india" in q.query for q in news_gdelt.QUERIES)
    assert all(lang in news_gdelt._LANGUAGES for lang in langs)          # GDELT's names map to ISO codes


def test_short_reason_keeps_only_the_throttle_sentence():
    assert news_gdelt.short_reason(THROTTLE[1].decode()) == "Please limit requests to one every 5 seconds"
    assert news_gdelt.short_reason("Cannot reach api.gdeltproject.org: [Errno 104] Connection reset by peer") \
        == "Cannot reach api.gdeltproject.org: [Errno 104] Connection reset by peer"
