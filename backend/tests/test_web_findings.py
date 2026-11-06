"""Other sources (non-official): web findings verified by Paladex on the page they cite.

The rule under test: a finding is stored ONLY if Paladex itself opens `source_url` and finds the quote
AND the number of `value_as_published` in the page text (HTML or PDF). Failures (page unreachable,
blocked, quote or number not found) are not stored and are listed in the run's warnings. Stored
findings are append-only (revisions), re-checked at most monthly, kept when the page later fails, and
never feed the map list. The optional AI web search goes through the same check, sends no company
name, respects the cap and records its usage.
"""
from __future__ import annotations

import json
from datetime import timedelta

import httpx
import pytest
import respx
from sqlalchemy import select

from paladex.collectors import runner
from paladex.collectors import web_findings as wf
from paladex.models import AppSetting, RawDocument, Source
from paladex.models_findings import WebFinding
from paladex.services import findings_ai as fa
from paladex.services import web_verify as wv

from conftest import fixture_bytes

PDF_URL = "https://apps.fas.example.gov/gain/AR2026-0012.pdf"
HTML_URL = "https://www.apicultores.example.ar/noticias/cosecha-2025"
NUMBERLESS_URL = "https://www.miel-news.example.com/argentina-exports"
DEAD_URL = "https://gone.example.org/brazil-honey-2025"
BLOCKED_URL = "https://paywalled.example.com/honey-market-2026"
CHALLENGE_URL = "https://www.protected.example.net/mexico-honey"

HTML_PAGE = """<!doctype html><html><head><title>Cosecha 2025</title>
<script>var production = "99.999 toneladas"; window.track();</script><style>.x{color:red}</style></head>
<body><nav>Inicio | Noticias</nav><article><h1>Balance de la cosecha 2025</h1>
<p>La Sociedad Argentina de Apicultores estima que la producción de miel de la campaña 2024/25 fue de
<b>72.000</b>&nbsp;toneladas, “una recuperación” respecto del año anterior.</p>
<p>Los productores recibieron en promedio 2,10 dólares por kilo.</p></article></body></html>"""

NUMBERLESS_PAGE = """<html><body><p>Argentine honey exports rose strongly in the first half of 2026, according to
customs data cited by exporters.</p><p>Prices remained firm.</p></body></html>"""

CHALLENGE_PAGE = """<html><head><title>Just a moment...</title></head><body>
<div id="cf-chl-widget">Checking your browser before accessing the site.</div>
<p>Enable JavaScript and cookies to continue</p></body></html>"""


def finding(**kw) -> dict:
    base = {
        "country_iso3": "ARG", "metric": "production", "period_label": "2026", "period_start": "2026-01-01",
        "period_end": "2026-12-31", "value": 75000, "unit": "t", "value_as_published": "75,000 metric tons",
        "status": "forecast", "kind": "usda_fas", "is_official": True, "publisher": "USDA FAS (Buenos Aires post)",
        "source_url": PDF_URL, "source_title": "Argentina: Honey Annual", "published_at": "2026-04-15", "language": "en",
        "quote": "Post forecasts marketing year 2026 honey production at 75,000 metric tons, up five percent from "
                 "the previous year",
        "also_reported_by": [], "notes": None,
    }
    base.update(kw)
    return base


SEED_FINDINGS = [
    finding(),                                                      # PDF: found
    finding(metric="production", period_label="2024/25", period_start="2024-10-01", period_end="2025-09-30",
            value=72000, value_as_published="72.000 toneladas", status="estimate", kind="association",
            is_official=False, publisher="Sociedad Argentina de Apicultores", source_url=HTML_URL, language="es",
            quote="la producción de miel de la campaña 2024/25 fue de 72.000 toneladas, \"una recuperación\""),
    finding(metric="exports", period_label="2026-H1", period_start="2026-01-01", period_end="2026-06-30",
            value=45000, value_as_published="45,000 t", status="reported", kind="trade_press", is_official=False,
            publisher="Miel News", source_url=NUMBERLESS_URL,
            quote="Argentine honey exports rose strongly in the first half of 2026"),   # number not on the page
    finding(country_iso3="BRA", metric="production", period_label="2025", period_start="2025-01-01",
            period_end="2025-12-31", value=64000, value_as_published="64 mil toneladas", status="estimate",
            kind="association", is_official=False, publisher="ABEMEL", source_url=DEAD_URL,
            quote="a produção brasileira de mel chegou a 64 mil toneladas"),       # unreachable
    finding(country_iso3="CHL", metric="exports", period_label="2026", value=9000, value_as_published="9,000 t",
            status="reported", kind="market_report", is_official=False, publisher="Paywalled Market Letter",
            source_url=BLOCKED_URL, quote="Chilean honey exports could reach 9,000 t in 2026"),   # HTTP 403
    finding(country_iso3="MEX", metric="production", period_label="2025", value=60000,
            value_as_published="60,000 tonnes", status="reported", kind="news", is_official=False,
            publisher="Protected News", source_url=CHALLENGE_URL,
            quote="Mexico produced about 60,000 tonnes of honey in 2025"),          # anti-bot page
    finding(country_iso3="URY", kind="news", is_official=True, source_url="https://news.example.uy/x"),  # inconsistent
]
SEED = {"compiled_on": "2026-11-05", "method": "Manual web research (test fixture)", "findings": SEED_FINDINGS,
        "not_found": [{"country_iso3": "ITA", "searched": "ISMEA, CREA, Osservatorio Nazionale Miele 2025 production",
                       "result": "no 2025 national production figure published yet"}]}


def routes(**over) -> dict:
    r = {
        PDF_URL: (200, fixture_bytes("web_findings/ar_honey_annual.pdf"), "application/pdf"),
        HTML_URL: (200, HTML_PAGE.encode("utf-8"), "text/html; charset=utf-8"),
        NUMBERLESS_URL: (200, NUMBERLESS_PAGE.encode(), "text/html"),
        BLOCKED_URL: (403, b"<html><body>Forbidden</body></html>", "text/html"),
        CHALLENGE_URL: (200, CHALLENGE_PAGE.encode(), "text/html"),
    }
    r.update(over)
    return r


@pytest.fixture()
def seed_file(tmp_path, monkeypatch):
    path = tmp_path / "web_findings_seed.json"

    def write(data: dict) -> None:
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    write(SEED)
    monkeypatch.setattr(wf, "SEED_PATH", path)
    monkeypatch.setattr(wv, "_resolve", lambda host: [])        # no DNS in tests
    return write


@pytest.fixture()
def online(run_with_routes, monkeypatch):
    """The PC is online: an unrouted host is a failure of that host, not 'offline'."""
    monkeypatch.setattr(runner, "is_online", lambda *a, **k: True)
    return run_with_routes


def current(db, **where) -> list[WebFinding]:
    q = select(WebFinding).where(WebFinding.is_current.is_(True))
    for k, v in where.items():
        q = q.where(getattr(WebFinding, k) == v)
    db.expire_all()
    return db.scalars(q).all()


# ---------------------------------------------------------------------------
# Normalisation and number matching
# ---------------------------------------------------------------------------

def test_normalisation_quotes_dashes_spaces_case():
    assert wv.normalize("“Una  Recuperación” – 2024 /25") == '"una recuperación" - 2024 /25'
    assert wv.normalize("pro­du​ction") == "production"
    assert wv.normalize("７５,000") == "75,000"                       # NFKC full-width digits


def test_numbers_compared_by_digits_as_whole_numbers():
    assert wv.published_numbers("75.000 toneladas") == ["75000"]
    assert wv.published_numbers("US$ 1.2 billion") == ["12"]
    assert wv.published_numbers("70,000-75,000 t") == ["70000", "75000"]
    nums = wv.page_numbers("output was 75 000 t; exports 750,000 kg; 1.234,5 USD")
    assert "75000" in nums and "750000" in nums and "12345" in nums
    page = wv.PageText(True, doc_type="html", text="Exports reached 750,000 kg in 2025 according to customs data.")
    v = wv.check_text(page, "Exports reached 750,000 kg in 2025", "75,000 kg", checked_at=wv.datetime(2026, 11, 5))
    assert not v.ok and v.reason == wv.NUMBER_NOT_FOUND           # 75000 is not a part of 750000
    assert wv.published_numbers("1,14,570.24 MT") == ["11457024"]   # Indian grouping (lakh)
    assert wv.published_numbers("1 479.23 美元/t") == ["147923"] and wv.published_numbers("17.55 万t") == ["1755"]


def test_seed_format_status_describes_the_figure_is_official_the_page(monkeypatch):
    monkeypatch.setattr(wv, "_resolve", lambda host: [])
    # a news page reporting a statistics office's final figure: kept, shown as a non-official source
    f, problem = wf.parse_finding(finding(kind="news", is_official=False, status="official_final",
                                          value=None, value_low=20000, value_high=26000,
                                          value_as_published="20 mil a 26 mil toneladas"), {"ARG"})
    assert problem is None and f["status"] == "official_final" and f["is_official"] is False
    assert f["range"] == {"value_low": 20000.0, "value_high": 26000.0} and f["value"] is None
    # but a news page can never be an official publisher
    assert wf.parse_finding(finding(kind="news", is_official=True), {"ARG"})[1] == "a news publisher cannot be marked official"
    assert wf.parse_finding(finding(quote="too short"), {"ARG"})[1].startswith("the quote is missing")
    assert wf.parse_finding(finding(value_as_published="seventy thousand"), {"ARG"})[1].startswith("value_as_published")
    assert wf.parse_finding(finding(source_url="http://localhost:8765/api/quotes"), {"ARG"})[1].startswith("source_url not opened")


def test_only_public_web_addresses_are_opened(monkeypatch):
    monkeypatch.setattr(wv, "_resolve", lambda host: [])
    for bad in ("http://127.0.0.1:8765/api/quotes", "http://localhost/x", "http://intranet/x", "file:///etc/passwd",
                "http://192.168.1.10/x", "https://user:pw@example.org/x", "ftp://example.org/x"):
        assert wv.url_problem(bad), bad
    assert wv.url_problem("https://www.example.org/page") is None
    monkeypatch.setattr(wv, "_resolve", lambda host: ["10.0.0.5"])
    assert wv.url_problem("https://rebind.example.org/") == "the name points to a private or local network address"


# ---------------------------------------------------------------------------
# The collector: verification, storage, warnings
# ---------------------------------------------------------------------------

def test_seed_findings_verified_on_their_pages(db, online, seed_file):
    res = online("web_findings", routes())
    assert res["status"] == "partial", res
    assert res["new"] == 2
    w = " | ".join(res["warnings"])
    # each failure says why, and nothing of it is stored
    assert "ARG exports 2026-H1 (Miel News): not stored: the quote is there, but the number of '45,000 t' " \
           "(digits 45000) is not in the page" in w
    assert "BRA production 2025 (ABEMEL): not stored: page unreachable" in w
    assert "CHL exports 2026 (Paywalled Market Letter): not stored: the site refuses automated access (HTTP 403)" in w
    assert "MEX production 2025 (Protected News): not stored: the site answered with an anti-bot, login or " \
           "'access denied' page" in w
    assert "Seed finding 7 (URY production 2026): not stored, a news publisher cannot be marked official" in w

    rows = current(db)
    assert {(r.country_iso3, r.metric, r.period_label) for r in rows} == {("ARG", "production", "2026"),
                                                                          ("ARG", "production", "2024/25")}
    pdf = next(r for r in rows if r.source_url == PDF_URL)
    assert pdf.value == 75000 and pdf.unit == "t" and pdf.value_as_published == "75,000 metric tons"
    assert pdf.status == "forecast" and pdf.kind == "usda_fas" and pdf.is_official is True
    assert pdf.verified_at is not None and pdf.revision == 1 and pdf.is_demo is False
    v = pdf.verification
    assert v["ok"] and v["quote_found"] and v["number_found"] and v["number_in_quote"] and v["doc_type"] == "pdf"
    assert v["numbers"] == ["75000"] and v["pdf_pages"] == [2, 2] and v["checks"][-1]["ok"] is True
    assert pdf.extra["found_by"] == "seed" and pdf.extra["seed_compiled_on"] == "2026-11-05"
    # the HTML page: typographic quotes, a non-breaking space and <b> markup did not matter; the script's
    # "99.999 toneladas" is not page text
    html = next(r for r in rows if r.source_url == HTML_URL)
    assert html.verification["doc_type"] == "html" and html.status == "estimate" and html.is_official is False
    assert "99999" not in wv.page_numbers(wv.html_to_text(HTML_PAGE.encode()))
    # an excerpt of the page around the quote is archived, never the whole page
    raw = db.get(RawDocument, pdf.raw_document_id)
    assert raw.content_type.startswith("text/plain") and raw.url == PDF_URL and raw.path.endswith(".txt")
    from paladex.config import get_settings

    text = (get_settings().raw_dir / raw.path).read_text(encoding="utf-8")
    assert "75,000 metric tons" in text and "Paladex verification excerpt" in text
    assert raw.size_bytes < 5000


def test_rerun_is_unchanged_without_reopening_pages_then_revision_on_change(db, online, seed_file):
    online("web_findings", routes())
    with respx.mock(assert_all_called=False) as mock:
        pdf_route = mock.get(PDF_URL).mock(return_value=httpx.Response(200, content=b"x"))
        mock.route().mock(side_effect=httpx.ConnectError("blocked in tests"))
        from paladex.collectors.runner import run_collector

        with httpx.Client() as client:
            res = run_collector("web_findings", trigger="test", client=client)
    assert res["new"] == 0 and res["revised"] == 0
    assert pdf_route.call_count == 0                       # verified less than a month ago: not opened again
    assert len(current(db)) == 2

    # The association revises its estimate (page and seed): a new revision, once verified on its page;
    # the old figure stays in history. The seed swaps the PDF's production figure for its exports figure.
    changed = [dict(f) for f in SEED_FINDINGS]
    changed[0].update(metric="exports", period_label="2025", period_start="2025-01-01", period_end="2025-12-31",
                      value=70400, value_as_published="70,400 metric tons", status="official_estimate",
                      quote="Exports in calendar year 2025 reached 70,400 metric tons")
    changed[1].update(value=73500, value_as_published="73.500 toneladas",
                      quote="la producción de miel de la campaña 2024/25 fue de 73.500 toneladas")
    seed_file({**SEED, "findings": changed})
    res = online("web_findings", routes(**{HTML_URL: (200, HTML_PAGE.replace("72.000", "73.500").encode(), "text/html")}))
    assert res["revised"] == 2 and res["new"] == 1        # HTML revised + PDF production withdrawn; PDF exports new
    rows = db.scalars(select(WebFinding).where(WebFinding.source_url == HTML_URL)).all()
    assert sorted((r.revision, r.is_current, r.value) for r in rows) == [(1, False, 72000), (2, True, 73500)]
    new = next(r for r in rows if r.is_current)
    assert new.supersedes_id == next(r.id for r in rows if not r.is_current)
    # the PDF production finding left the seed: withdrawn, kept in history
    old = db.scalars(select(WebFinding).where(WebFinding.source_url == PDF_URL,
                                              WebFinding.metric == "production")).one()
    assert old.is_current is False
    assert any("withdrawn from the seed" in w for w in res["warnings"])


def test_page_gone_later_keeps_the_finding_and_notes_the_failed_check(db, online, seed_file):
    online("web_findings", routes())
    for r in current(db):
        r.verified_at = r.verified_at - timedelta(days=40)      # due for the monthly re-check
    db.commit()
    res = online("web_findings", routes(**{PDF_URL: (404, b"not found", "text/html")}))
    pdf = current(db, source_url=PDF_URL)
    assert len(pdf) == 1 and pdf[0].revision == 1                # kept, not deleted, not revised
    v = pdf[0].verification
    assert v["ok"] is False and v["reason"] == "unreachable" and v["kept_after_failed_check"] is True
    assert [c["ok"] for c in v["checks"]] == [True, False] and v["last_ok_at"]
    assert any("ARG production 2026 (USDA FAS (Buenos Aires post)): re-check on its page failed, finding kept "
               "as last verified" in w and "page not found (HTTP 404)" in w for w in res["warnings"])
    # the HTML page still answers: its check is renewed
    html = current(db, source_url=HTML_URL)[0]
    assert [c["ok"] for c in html.verification["checks"]] == [True, True]


def test_offline_pc_judges_nothing(db, run_with_routes, seed_file):
    res = run_with_routes("web_findings", {})                     # every host unreachable and no internet
    assert res["status"] == "offline"
    assert current(db) == []


def test_missing_seed_is_a_warning(db, online, seed_file, tmp_path, monkeypatch):
    monkeypatch.setattr(wf, "SEED_PATH", tmp_path / "nope.json")
    res = online("web_findings", {})
    assert res["status"] == "partial" and "seed file not found" in res["warnings"][0]


# ---------------------------------------------------------------------------
# API: own block on the country page, never in the map list
# ---------------------------------------------------------------------------

def test_api_country_block_listing_and_map_untouched(db, api, online, seed_file):
    before = api.get("/api/countries").json()
    online("web_findings", routes())
    after = api.get("/api/countries").json()
    assert after == before                                         # the map list never reads findings
    assert "findings" not in json.dumps(after["metrics"])

    p = api.get("/api/countries/ARG").json()
    b = p["web_findings"]
    assert b["available"] and b["count"] == 2 and b["is_official_statistics"] is False
    assert [m["metric"] for m in b["metrics"]] == ["production"]
    f = b["metrics"][0]["findings"]
    assert [x["period_label"] for x in f] == ["2026", "2024/25"]   # newest first
    assert f[0]["value_as_published"] == "75,000 metric tons" and f[0]["is_official"] is True
    assert f[0]["source_url"] == PDF_URL and f[0]["quote"].startswith("Post forecasts")
    assert f[0]["last_check"]["ok"] is True and f[0]["found_by"] == "seed"
    assert "verificato da Paladex" in b["note_it"] and "checked by Paladex" in b["note_en"]
    # nothing of it in the official parts of the profile
    assert not p["availability"]["production"] and all(s.get("key") != "web_findings" for s in p["sources"])

    ita = api.get("/api/countries/ITA").json()["web_findings"]
    assert ita["available"] is False and ita["metrics"] == []
    assert ita["not_found"] == [{"by": "seed", "searched": "ISMEA, CREA, Osservatorio Nazionale Miele 2025 production",
                                 "result": "no 2025 national production figure published yet", "on": "2026-11-05"}]

    lst = api.get("/api/findings", params={"country": "arg", "metric": "production"}).json()
    assert lst["count"] == 2
    assert api.get("/api/findings", params={"metric": "price"}).status_code == 422
    assert api.get("/api/findings").json()["count"] == 2
    src = next(s for s in api.get("/api/sources").json()["sources"] if s["key"] == "web_findings")
    assert src["counts"] == {"findings": 2} and src["category"] == "findings"


# ---------------------------------------------------------------------------
# The optional AI web search
# ---------------------------------------------------------------------------

AI_PAGE_URL = "https://www.beekeepers.example.it/news/miele-2025"
AI_PAGE = "<html><body><p>Secondo l'associazione, nel 2025 la produzione italiana di miele è stata di 23.500 tonnellate.</p></body></html>"


def ai_answer(findings: list[dict], stop="end_turn", searches=2, text=None) -> dict:
    return {
        "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
        "content": [
            {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search", "input": {"query": "produzione miele Italia 2025"}},
            {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_1",
             "content": [{"type": "web_search_result", "url": AI_PAGE_URL, "title": "Miele 2025", "encrypted_content": "abc"}]},
            *([{"type": "text", "text": text if text is not None else json.dumps(
                {"findings": findings, "searched": "Italian honey production 2025"})}] if stop != "pause_turn" else []),
        ],
        "stop_reason": stop,
        "usage": {"input_tokens": 12000, "output_tokens": 900, "server_tool_use": {"web_search_requests": searches}},
    }


@pytest.fixture()
def ai_on(db, api, monkeypatch):
    monkeypatch.setenv("PALADEX_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("PALADEX_ANTHROPIC_API_KEY", "sk-ant-test-key")
    from paladex import config

    config.get_settings.cache_clear()
    monkeypatch.setattr(fa.time, "sleep", lambda *_: None)
    monkeypatch.setattr(wf, "today", lambda: wv.datetime(2026, 11, 5).date())
    return api


def test_ai_search_is_off_by_default(db, online, seed_file, ai_on):
    st = ai_on.get("/api/findings/ai").json()
    assert st["enabled"] is False and st["enabled_by"] == "default" and st["will_run"] is False
    res = online("web_findings", {**routes(), ("POST", fa.llm.ANTHROPIC_URL): (500, b"must not be called")})
    assert not any("AI web search" in w for w in res["warnings"])
    assert db.get(AppSetting, fa.AI_USAGE_SETTING) is None


def test_ai_findings_go_through_the_same_check(db, online, seed_file, ai_on, monkeypatch):
    seed_file({**SEED, "findings": [], "not_found": []})
    monkeypatch.setattr("paladex.reference.countries.PRIORITY_ISO3", ["ITA", "ESP"])
    assert ai_on.put("/api/findings/ai", json={"enabled": True, "max_searches": 3}).json()["will_run"] is True
    good = finding(country_iso3="ITA", period_label="2025", period_start="2025-01-01", period_end="2025-12-31",
                   value=23500, value_as_published="23.500 tonnellate", status="estimate", kind="association",
                   is_official=False, publisher="Associazione apicoltori (test)", source_url=AI_PAGE_URL, language="it",
                   quote="nel 2025 la produzione italiana di miele è stata di 23.500 tonnellate")
    invented = {**good, "metric": "exports", "value": 9000, "value_as_published": "9.000 tonnellate",
                "quote": "le esportazioni italiane di miele sono state di 9.000 tonnellate"}
    old = {**good, "period_label": "2023", "period_start": "2023-01-01", "period_end": "2023-12-31"}
    other = {**good, "country_iso3": "FRA"}
    calls: list[dict] = []

    def answer(request):
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            return httpx.Response(200, json=ai_answer([], stop="pause_turn", searches=1))
        return httpx.Response(200, json=ai_answer([good, invented, old, other], searches=2))

    with respx.mock(assert_all_called=False) as mock:
        mock.post(fa.llm.ANTHROPIC_URL).mock(side_effect=answer)
        mock.get(AI_PAGE_URL).mock(return_value=httpx.Response(200, content=AI_PAGE.encode(),
                                                                headers={"content-type": "text/html"}))
        mock.route().mock(side_effect=httpx.ConnectError("blocked in tests"))
        with httpx.Client() as client:
            res = runner.run_collector("web_findings", trigger="test", client=client)

    # one country (the cap of 3 searches was used by Italy: 1 + 2), resumed once after pause_turn
    assert len(calls) == 2
    first = calls[0]
    assert first["model"] == "claude-haiku-5-5"
    assert first["tools"] == [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}]
    assert calls[1]["messages"][-1]["role"] == "assistant"          # the paused turn sent back unchanged
    sent = json.dumps(calls).lower()
    assert "parodi" not in sent and "italy" in sent and "ita" in sent
    # only the figure found on its page is stored
    rows = current(db)
    assert len(rows) == 1 and rows[0].value == 23500 and rows[0].country_iso3 == "ITA"
    assert rows[0].extra["found_by"] == "ai_web_search" and rows[0].extra["model"] == "claude-haiku-5-5"
    assert rows[0].extra["search_queries"] == ["produzione miele Italia 2025", "produzione miele Italia 2025"]
    w = " | ".join(res["warnings"])
    assert "ITA exports 2025 (Associazione apicoltori (test)): not stored: the quote is not in the page text" in w
    assert "period 2023 is older than 2025" in w and "country FRA is not the one searched (ITA)" in w
    # usage recorded: requests, searches, tokens and the cost at the list prices
    st = ai_on.get("/api/findings/ai").json()
    run = st["runs"][0]
    assert run["requests"] == 2 and run["searches"] == 3 and run["input_tokens"] == 24000 and run["output_tokens"] == 1800
    assert run["cost_usd"] == pytest.approx(3 * 0.01 + 24000 * 0.10 / 1e6 + 1800 * 0.50 / 1e6)
    assert run["countries"] == [{"iso3": "ITA", "searches": 3, "proposed": 4, "stored": 1}]
    assert run["proposed"] == 4 and run["stored"] == 1
    state = db.get(AppSetting, fa.AI_STATE_SETTING).value
    assert state["ITA"]["searched_at"] == "2026-11-05" and state["ITA"]["stored"] == 1

    # next week: Italy has a recent finding and was just searched; Spain is next
    calls.clear()
    with respx.mock(assert_all_called=False) as mock:
        mock.post(fa.llm.ANTHROPIC_URL).mock(side_effect=lambda req: (calls.append(json.loads(req.content)), httpx.Response(
            200, json=ai_answer([], searches=1)))[1])
        mock.route().mock(side_effect=httpx.ConnectError("blocked in tests"))
        with httpx.Client() as client:
            runner.run_collector("web_findings", trigger="test", client=client)
    assert len(calls) == 1 and "Spain" in calls[0]["messages"][0]["content"]
    es = ai_on.get("/api/countries/ESP").json()["web_findings"]
    assert es["not_found"] == [{"by": "ai_web_search", "searched": "Italian honey production 2025", "result": "",
                                "on": "2026-11-05"}]


def test_ai_provider_error_stops_the_search_and_says_so(db, online, seed_file, ai_on, monkeypatch):
    seed_file({**SEED, "findings": [], "not_found": []})
    monkeypatch.setattr("paladex.reference.countries.PRIORITY_ISO3", ["ITA", "ESP"])
    ai_on.put("/api/findings/ai", json={"enabled": True})
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(fa.llm.ANTHROPIC_URL).mock(return_value=httpx.Response(401, json={"error": {"message": "bad key"}}))
        mock.route().mock(side_effect=httpx.ConnectError("blocked in tests"))
        with httpx.Client() as client:
            res = runner.run_collector("web_findings", trigger="test", client=client)
    assert route.call_count == 1                                 # stopped at the first error
    assert any("AI web search stopped at Italy: Anthropic: API key not valid" in w for w in res["warnings"])
    assert "sk-ant-test-key" not in json.dumps(res)


def test_ai_settings_and_cost_estimate(db, api, monkeypatch):
    st = api.get("/api/findings/ai").json()
    assert st["unavailable"] == "no_key" and st["max_searches"] == 20 and st["openai_supported"] is False
    e = st["estimate"]
    # Claude Haiku 5.5 ($0.10 / $0.50 per million tokens) + web search ($10 per 1,000), 2026-11-05
    assert e["prices_checked_on"] == "2026-11-05" and e["web_search_usd_per_1000"] == 10.0
    assert e["input_usd_per_mtok"] == 0.10 and e["output_usd_per_mtok"] == 0.50
    assert e["per_search_usd"] == 0.013 and e["per_run_usd"] == 0.26 and e["per_month_usd"] == 1.13
    st = api.put("/api/findings/ai", json={"enabled": True, "max_searches": 40}).json()
    assert st["enabled"] and st["enabled_by"] == "setting" and st["estimate"]["per_run_usd"] == 0.52
    assert api.put("/api/findings/ai", json={"max_searches": 0}).status_code == 422
    monkeypatch.setenv("PALADEX_LLM_PROVIDER", "openai")
    monkeypatch.setenv("PALADEX_OPENAI_API_KEY", "sk-test")
    from paladex import config

    config.get_settings.cache_clear()
    assert api.get("/api/findings/ai").json()["unavailable"] == "provider_not_supported"


def test_source_registered_keyless_weekly(db):
    src = db.scalars(select(Source).where(Source.key == "web_findings")).one()
    assert src.category == "findings" and src.requires_key is None and src.reliability == "aggregator"
    c = wf.WebFindingsCollector
    assert c.schedule["trigger"] == "cron" and "day_of_week" in c.schedule
    assert c.expected_update and c.expected_update_en and c.terms_note
