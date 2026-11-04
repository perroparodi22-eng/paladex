"""Tests for collectors/trade_official.py: Brazil Comex Stat (br_comexstat) and the US Census
International Trade API (us_census_trade).

All fixtures in tests/fixtures/trade_official/ are RECONSTRUCTED from documentation (see the README
there); the numbers are illustrative. `build_fixtures.py` regenerates them.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import func, select

from paladex import config
from paladex.collectors import trade_official as to
from paladex.collectors.base import CollectorError
from paladex.enums import PriceType
from paladex.models import (
    AppSetting,
    CollectionRun,
    PriceObservation,
    RawDocument,
    Source,
    TradeFlowObservation,
)

FIX = Path(__file__).parent / "fixtures" / "trade_official"
SECRET = "c3n5u5-T0P-SECRET-k3y"
T, P = TradeFlowObservation, PriceObservation


def F(name: str) -> bytes:
    return (FIX / name).read_bytes()


# ---------------------------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def no_census_key(monkeypatch):
    """A developer's own .env must not change what these tests see (env beats .env)."""
    monkeypatch.setenv("PALADEX_CENSUS_API_KEY", "")


@pytest.fixture()
def census_key(db, monkeypatch):
    monkeypatch.setenv("PALADEX_CENSUS_API_KEY", SECRET)
    config.get_settings.cache_clear()
    yield SECRET
    config.get_settings.cache_clear()


@pytest.fixture()
def pin_today(monkeypatch):
    def _pin(d: date):
        monkeypatch.setattr(to, "today", lambda: d)
    _pin(date(2026, 11, 4))
    return _pin


def _static(spec):
    if callable(spec):
        return spec
    if isinstance(spec, bytes):
        spec = (200, spec)
    status, body, *ctype = spec
    headers = {"content-type": ctype[0]} if ctype else {"content-type": "application/json"}
    return lambda request: httpx.Response(status, content=body, headers=headers)


@pytest.fixture()
def run(db, monkeypatch):
    """Run a collector offline. `routes` maps a GET URL prefix (or a regex starting with '^') to
    bytes | (status, bytes[, content type]) | callable(request). `post` answers every Comex Stat
    POST /general (callable). The requests of the last run are in `run.sent`."""
    from paladex.collectors import base
    from paladex.collectors.runner import run_collector

    monkeypatch.setattr(base.time, "sleep", lambda *_: None)

    def _run(key: str, routes: dict, *, post=None, force: bool = False) -> dict:
        sent: list[httpx.Request] = []
        _run.sent = sent

        def recorded(handler):
            def side_effect(request):
                sent.append(request)
                return handler(request)
            return side_effect

        with respx.mock(assert_all_called=False) as mock:
            for url, spec in routes.items():
                route = (mock.route(method="GET", url__regex=url) if url.startswith("^")
                         else mock.route(method="GET", url__startswith=url))
                route.mock(side_effect=recorded(_static(spec)))
            if post is not None:
                mock.route(method="POST", url__startswith=to.COMEX_GENERAL_URL).mock(side_effect=recorded(post))
            mock.route().mock(side_effect=httpx.ConnectError("blocked in tests"))
            with httpx.Client(follow_redirects=True) as client:
                return run_collector(key, trigger="test", force=force, client=client)

    _run.sent = []
    return _run


def _rows(s, model, key: str, *, current: bool | None = None, **where):
    src = s.scalars(select(Source).where(Source.key == key)).one()
    q = select(model).where(model.source_id == src.id)
    if current is not None:
        q = q.where(model.is_current.is_(current))
    for k, v in where.items():
        q = q.where(getattr(model, k) == v)
    return s.scalars(q.order_by(model.id)).all()


def _state(s, key: str) -> dict:
    row = s.get(AppSetting, f"collector_state:{key}")
    return dict(row.value) if row else {}


def _no_duplicate_current(s) -> None:
    for model in (T, P):
        dup = s.execute(select(model.source_id, model.series_key, func.count()).where(model.is_current.is_(True))
                        .group_by(model.source_id, model.series_key).having(func.count() > 1)).all()
        assert dup == [], dup


# ---------------------------------------------------------------------------------------------
# Shared helpers and registration
# ---------------------------------------------------------------------------------------------


def test_registered_with_official_metadata():
    from paladex.collectors.registry import get_collector

    br, us = get_collector("br_comexstat"), get_collector("us_census_trade")
    assert br is not None and us is not None
    assert br.reliability == "official" and us.reliability == "official"
    assert br.category == us.category == "trade"
    assert br.requires_key is None
    assert us.requires_key == "census_api_key" and us.key_optional is True
    assert "GATS" in us.terms_note and "never be added" in us.terms_note


def test_month_windows_newest_first_and_capped():
    assert to.month_windows((2023, 10), (2026, 9), 12) == [
        ((2025, 10), (2026, 9)), ((2024, 10), (2025, 9)), ((2023, 10), (2024, 9))]
    assert to.month_windows((2026, 8), (2026, 10), 12) == [((2026, 8), (2026, 10))]
    assert to.month_windows((2026, 1), (2026, 1), 12) == [((2026, 1), (2026, 1))]
    assert to.month_windows((2026, 2), (2026, 1), 12) == []
    assert all(to._midx(b) - to._midx(a) < 12 for a, b in to.month_windows((2020, 1), (2026, 12), 12))


@pytest.mark.parametrize("name, iso", [
    ("United States", "USA"), ("Estados Unidos", "USA"), ("Países Baixos (Holanda)", "NLD"),
    ("Netherlands", "NLD"), ("Alemanha", "DEU"), ("Reino Unido", "GBR"), ("Taiwan (Formosa)", "TWN"),
    ("KOREA, SOUTH", "KOR"), ("TURKIYE", "TUR"), ("TURKEY", "TUR"), ("BURMA", "MMR"),
    ("Singapore", "SGP"), ("Cingapura", "SGP"), ("Arábia Saudita", "SAU"), ("NEW ZEALAND", "NZL"),
])
def test_country_names_resolve(name, iso):
    assert to.resolve_country_name(name) == iso


@pytest.mark.parametrize("name", ["Atlantis", "", None, "World", "TOTAL", "Ships' stores"])
def test_country_names_unknown_or_aggregate_are_none(name):
    assert to.resolve_country_name(name) is None


# ---------------------------------------------------------------------------------------------
# Brazil, Comex Stat: pure functions
# ---------------------------------------------------------------------------------------------


def comex_spec(**over) -> to.ComexSpec:
    base = dict(ncm_filter="ncm", country_detail="country", state_detail="state", ncm_detail="ncm",
                fob_metric="metricFOB", kg_metric="metricKG")
    base.update(over)
    return to.ComexSpec(**base)


def comex_doc(rows: list[dict]) -> bytes:
    return json.dumps({"data": {"list": rows}, "success": True, "message": None}).encode()


def test_parse_comex_updated_and_variants():
    rel = to.parse_comex_updated(F("comex_dates_updated_2026-10-06.json"))
    assert rel.latest == (2026, 9) and rel.released == date(2026, 10, 6)
    assert rel.signature == "2026-09|2026-10-06"
    rel2 = to.parse_comex_updated(json.dumps({"data": [{"dataAtualizacao": "x", "updated": "06/10/2026",
                                                        "year": "2026", "month": "09. September"}]}).encode())
    assert rel2.latest == (2026, 9) and rel2.released == date(2026, 10, 6)
    rel3 = to.parse_comex_updated(json.dumps({"data": {"year": 2026, "monthNumber": 9}}).encode())
    assert rel3.latest == (2026, 9) and rel3.released is None
    with pytest.raises(CollectorError, match="year/month"):
        to.parse_comex_updated(json.dumps({"data": {"updated": "2026-10-06"}}).encode())
    with pytest.raises(CollectorError, match="answered with an error"):
        to.parse_comex_updated(json.dumps({"success": False, "message": "manutenção"}).encode())
    with pytest.raises(CollectorError, match="not valid JSON"):
        to.parse_comex_updated(b"<html>maintenance</html>")


def test_resolve_comex_spec_from_metadata_and_drift():
    filters = to.parse_comex_names(F("comex_filters.json"), "filters")
    details = to.parse_comex_names(F("comex_details.json"), "details")
    metrics = to.parse_comex_names(F("comex_metrics.json"), "metrics")
    spec = to.resolve_comex_spec(filters, details, metrics)
    assert spec == comex_spec()
    body = to.comex_query_body(spec, (2025, 10), (2026, 9))
    assert body == {"flow": "export", "monthDetail": True, "period": {"from": "2025-10", "to": "2026-09"},
                    "filters": [{"filter": "ncm", "values": ["04090000"]}],
                    "details": ["country", "state", "ncm"], "metrics": ["metricFOB", "metricKG"]}
    # the server's own spelling wins (names are case-sensitive)
    assert to.resolve_comex_spec(["NCM"], ["Country"], ["MetricFob", "metricKG"]).country_detail == "Country"
    # no state detail: still expressible, country totals only
    assert to.resolve_comex_spec(filters, ["country"], metrics).state_detail is None
    with pytest.raises(CollectorError, match="metric KG"):
        to.resolve_comex_spec(filters, details, [m for m in metrics if m != "metricKG"])
    with pytest.raises(CollectorError, match="filter 'ncm'"):
        to.resolve_comex_spec([f for f in filters if f != "ncm"], details, metrics)
    with pytest.raises(CollectorError, match="no names"):
        to.parse_comex_names(json.dumps({"data": {"list": [{"text": "only text"}]}}).encode(), "metrics")


def test_real_comex_metadata_and_rate_limit_answer():
    """Real answers of 2026-11-04: dates/updated, filters, details, metrics and the HTTP 429 body."""
    rel = to.parse_comex_updated(F("real_comex_dates_updated_2026-10-06.json"))
    assert (rel.latest, rel.released, rel.raw) == ((2026, 9), date(2026, 10, 6), "2026-10-06")
    filters = to.parse_comex_names(F("real_comex_filters.json"), "filters")
    details = to.parse_comex_names(F("real_comex_details.json"), "details")
    metrics = to.parse_comex_names(F("real_comex_metrics.json"), "metrics")
    assert {"ncm", "country", "state", "heading"} <= set(filters) and filters == details
    assert metrics == ["metricFOB", "metricKG", "metricStatistic", "metricFreight", "metricInsurance", "metricCIF"]
    assert to.resolve_comex_spec(filters, details, metrics) == comex_spec()
    limited = F("real_comex_rate_limited_429.json")
    assert to.is_comex_rate_limited(429, limited) and to.is_comex_rate_limited(200, limited)
    assert "tente novamente" in to._comex_error_text(limited)
    with pytest.raises(CollectorError, match="answered with an error"):
        to.parse_comex_general(limited, comex_spec(), (2026, 9), (2026, 9))


def test_parse_comex_general_maps_columns_dynamically():
    rows = [
        # code/name pairs, ISO column, numbers as strings, month as "09"
        {"coAno": 2026, "coMes": "09", "noPaisIng": "Germany", "coPais": "023", "coPaisIsoa3": "DEU",
         "noUf": "Santa Catarina", "sgUf": "SC", "coNcm": "0409.00.00", "metricFOB": "1000.5", "metricKG": 250},
        {"coAno": 2026, "coMes": "9", "noPaisIng": "Estados Unidos", "coPais": "249", "noUf": "Piauí",
         "sgUf": "PI", "coNcm": "04090000", "metricFOB": 7000, "metricKG": "2000"},
        {"coAno": 2026, "coMes": "9", "noPaisIng": "Canada", "noUf": "Paraná", "sgUf": "PR",
         "coNcm": "04090000", "metricFOB": "n/d", "metricKG": "10"},                    # bad numbers
        {"coAno": 2025, "coMes": "1", "noPaisIng": "Canada", "noUf": "Paraná", "sgUf": "PR",
         "coNcm": "04090000", "metricFOB": 1, "metricKG": 1},                            # outside window
    ]
    out = to.parse_comex_general(comex_doc(rows), comex_spec(), (2026, 7), (2026, 9))
    assert [(r.period, r.country_iso3, r.country_name, r.country_code, r.state, r.state_code, r.fob_usd, r.kg)
            for r in out.rows] == [
        ("2026-09", "DEU", "Germany", "023", "Santa Catarina", "SC", 1000.5, 250.0),
        ("2026-09", None, "Estados Unidos", "249", "Piauí", "PI", 7000.0, 2000.0),
    ]
    assert [to.map_comex_partner(r) for r in out.rows] == ["DEU", "USA"]
    assert [(b.period, b.country_name) for b in out.bad_rows] == [("2026-09", "Canada")]
    assert any("outside the requested" in p for p in out.problems)
    assert any("invalid FOB" in p for p in out.problems)


def test_comex_query_period_uses_whole_years_across_a_year_boundary():
    """Comex Stat applies the month range of `period` to every year of its year range (live check
    2026-11-04): a span over a year boundary must ask for whole years."""
    assert to.comex_query_period((2026, 8), (2026, 10)) == ((2026, 8), (2026, 10))
    assert to.comex_query_period((2023, 10), (2026, 9)) == ((2023, 1), (2026, 12))
    assert to.comex_query_period((2026, 11), (2027, 1)) == ((2026, 1), (2027, 12))
    rows = [{"year": y, "monthNumber": m, "country": "Canada", "state": "Paraná", "coNcm": "04090000", "metricFOB": "10",
             "metricKG": "2"}
            for y, m in (("2026", "1"), ("2026", "11"), ("2026", "12"), ("2027", "1"))]
    out = to.parse_comex_general(comex_doc(rows), comex_spec(), (2026, 11), (2027, 1), query=((2026, 1), (2027, 12)))
    assert [r.period for r in out.rows] == ["2026-11", "2026-12", "2027-01"] and out.problems == []
    only_asked = to.parse_comex_general(comex_doc(rows[:1]), comex_spec(), (2026, 11), (2027, 1),
                                        query=((2026, 1), (2027, 12)))
    assert only_asked.rows == [] and only_asked.problems == []      # nothing in the window yet: not an error


def test_parse_comex_general_fails_loudly_on_drift():
    good = {"year": "2026", "monthNumber": "9", "country": "United States", "state": "Piauí",
            "coNcm": "04090000", "ncm": "Natural honey", "metricFOB": "1", "metricKG": "1"}
    no_kg = {k: v for k, v in good.items() if k != "metricKG"}
    with pytest.raises(CollectorError, match="KG"):
        to.parse_comex_general(comex_doc([no_kg]), comex_spec(), (2026, 9), (2026, 9))
    no_country = {k: v for k, v in good.items() if k != "country"}
    with pytest.raises(CollectorError, match="country"):
        to.parse_comex_general(comex_doc([no_country]), comex_spec(), (2026, 9), (2026, 9))
    sugar = {**good, "coNcm": "17019900", "ncm": "Other cane sugar"}
    with pytest.raises(CollectorError, match="ignored the NCM"):
        to.parse_comex_general(comex_doc([good, sugar]), comex_spec(), (2026, 9), (2026, 9))
    with pytest.raises(CollectorError, match="no record list"):
        to.parse_comex_general(json.dumps({"data": {"rows_v2": {}}, "success": True}).encode(), comex_spec(),
                               (2026, 9), (2026, 9))
    with pytest.raises(CollectorError, match="answered with an error"):
        to.parse_comex_general(json.dumps({"success": False, "message": "Invalid filter: ncm"}).encode(),
                               comex_spec(), (2026, 9), (2026, 9))
    assert to.parse_comex_general(comex_doc([]), comex_spec(), (2026, 9), (2026, 9)).rows == []


def test_comex_rate_limit_detection():
    assert to.is_comex_rate_limited(429, b"")
    assert to.is_comex_rate_limited(200, F("comex_rate_limited.json"))
    assert to.is_comex_rate_limited(400, json.dumps({"success": False, "message": "Muitas requisições"}).encode())
    assert not to.is_comex_rate_limited(400, json.dumps({"success": False, "message": "Invalid filter"}).encode())
    assert not to.is_comex_rate_limited(200, F("comex_general_2023-10_2024-09.json"))


# ---------------------------------------------------------------------------------------------
# Brazil, Comex Stat: end to end
# ---------------------------------------------------------------------------------------------


def comex_routes(updated: str = "comex_dates_updated_2026-10-06.json", **over) -> dict:
    routes = {
        to.COMEX_UPDATED_URL: F(updated),
        to.COMEX_FILTERS_URL: F("comex_filters.json"),
        to.COMEX_DETAILS_URL: F("comex_details.json"),
        to.COMEX_METRICS_URL: F("comex_metrics.json"),
    }
    routes.update(over)
    return routes


BACKFILL = {w: F(f"comex_general_{w}.json") for w in ("2025-10_2026-09", "2024-10_2025-09", "2023-10_2024-09")}
# The backfill is ONE query for whole years (to.comex_query_period): 2023-10..2026-09 is asked as
# period 2023-01..2026-12. The three reconstructed pieces above answer it together.
BACKFILL_QUERY = "2023-01_2026-12"


def comex_post(windows: dict):
    """Answer POST /general by the requested period: {"2026-08_2026-10": bytes | callable}. The
    backfill query is answered by the BACKFILL pieces (overridable one by one) merged into one
    document; a piece that answers an error or a rate limit is returned as is."""
    def handler(request):
        body = json.loads(request.content)
        key = f"{body['period']['from']}_{body['period']['to']}"
        if key == BACKFILL_QUERY and key not in windows and all(w in windows for w in BACKFILL):
            merged: list = []
            for w in BACKFILL:
                spec = windows[w]
                if callable(spec):
                    resp = spec(request)
                    if resp.status_code != 200 or to.is_comex_rate_limited(resp.status_code, resp.content):
                        return resp
                    spec = resp.content
                merged += json.loads(spec)["data"]["list"]
            return httpx.Response(200, content=comex_doc(merged), headers={"content-type": "application/json"})
        if key not in windows:
            raise AssertionError(f"unexpected Comex Stat window {key}")
        spec = windows[key]
        if callable(spec):
            return spec(request)
        return httpx.Response(200, content=spec, headers={"content-type": "application/json"})
    return handler


def test_comex_backfill_end_to_end(run, session_factory):
    res = run("br_comexstat", comex_routes(), post=comex_post(BACKFILL))
    assert res["status"] == "success", res
    posts = [r for r in run.sent if r.method == "POST"]
    assert [json.loads(r.content)["period"] for r in posts] == [{"from": "2023-01", "to": "2026-12"}]   # one query
    assert all(r.url.params["language"] == "en" for r in posts)
    assert json.loads(posts[0].content)["filters"] == [{"filter": "ncm", "values": ["04090000"]}]

    with session_factory() as s:
        trades = _rows(s, T, "br_comexstat")
        assert len(trades) == 14
        assert all((t.reporter_iso3, t.flow, t.currency, t.frequency, t.value_basis, t.hs_code)
                   == ("BRA", "export", "USD", "M", "FOB", "0409") for t in trades)
        assert all(t.reliability == "official" and t.data_status == "published" for t in trades)
        assert all(t.published_at == date(2026, 10, 6) and t.source_url == to.COMEX_SOURCE_URL and t.raw_document_id
                   for t in trades)
        usa = _rows(s, T, "br_comexstat", partner_iso3="USA", period_label="2026-09")
        assert len(usa) == 1
        u = usa[0]
        assert (u.value, u.net_weight_kg) == (7_470_000, 2_100_000)        # three states summed
        assert (u.period_start, u.period_end) == (date(2026, 9, 1), date(2026, 9, 30))
        assert [(st["state"], st["fob_usd"], st["kg"]) for st in u.extra["states"]] == [
            ("Piauí", 4_260_000, 1_200_000), ("Ceará", 2_100_000, 600_000), ("Rio Grande do Sul", 1_110_000, 300_000)]
        assert u.extra["ncm"] == "04090000" and u.extra["state_detail"] is True
        assert u.extra["query"]["period"] == {"from": "2023-01", "to": "2026-12"}
        assert {t.partner_iso3 for t in trades} == {"USA", "CAN", "NLD", "SGP", "AUS", "DEU"}

        prices = _rows(s, P, "br_comexstat")
        assert len(prices) == 13
        assert {p.price_type for p in prices} == {PriceType.EXPORT_UNIT_VALUE}
        pu = _rows(s, P, "br_comexstat", market_iso3="USA", period_label="2026-09")
        assert len(pu) == 1
        p = pu[0]
        assert (p.origin_iso3, p.origin_label, p.currency, p.unit, p.variety, p.terms) == (
            "BRA", "Brazil", "USD", "kg", "unspecified", "FOB")
        assert p.price_value == round(7_470_000 / 2_100_000, 4) == p.usd_per_kg
        assert p.volume_kg == 2_100_000 and p.published_at == date(2026, 10, 6) and p.reliability == "official"
        assert p.extra["states"] and p.market_location == "United States"
        # under 1 t: trade row kept, no unit value
        assert _rows(s, T, "br_comexstat", partner_iso3="AUS") and not _rows(s, P, "br_comexstat", market_iso3="AUS")
        assert all(x.volume_kg >= to.MIN_UNIT_VALUE_WEIGHT_KG for x in prices)
        # a destination outside the country table is still stored under its ISO3 code
        assert [x.price_value for x in _rows(s, P, "br_comexstat", market_iso3="SGP")] == [4.5]

        raw = _rows(s, RawDocument, "br_comexstat")
        assert len(raw) == 1 and all(d.url == to.COMEX_SOURCE_URL for d in raw)
        assert "2023-10..2026-09" in (raw[0].title or "")
        st = _state(s, "br_comexstat")
        assert st["release"] == "2026-09|2026-10-06" and st["latest_month"] == "2026-09" and st["backfill_done"]
        assert st["spec"]["fob_metric"] == "metricFOB"
        n_trades, n_prices = len(trades), len(prices)

    # Same release: one cheap request, nothing pulled, nothing duplicated.
    res2 = run("br_comexstat", comex_routes(), post=comex_post(BACKFILL))
    assert res2["status"] == "no_change", res2
    assert [r.url.path for r in run.sent] == ["/general/dates/updated"]
    # A forced re-pull of identical data adds nothing either (idempotent).
    res3 = run("br_comexstat", comex_routes(), post=comex_post(BACKFILL), force=True)
    assert res3["status"] == "no_change" and res3["new"] == 0 and res3["revised"] == 0, res3
    with session_factory() as s:
        assert len(_rows(s, T, "br_comexstat")) == n_trades and len(_rows(s, P, "br_comexstat")) == n_prices
        _no_duplicate_current(s)


def test_real_comex_period_semantics_captures():
    """Real answers (2026-11-04): the original query over 2025-10..2026-09 came back empty, one
    month inside one year came back with rows. The whole-year query below holds 2025-10..2026-09."""
    assert to.parse_comex_general(F("real_comex_general_empty_2025-10_2026-09.json"), comex_spec(),
                                  (2025, 10), (2026, 9)).rows == []
    jan = json.loads(F("real_comex_general_2024-01_country.json"))["data"]["list"]
    usa = next(r for r in jan if r["country"] == "United States")
    assert (usa["year"], usa["metricFOB"], usa["metricKG"]) == ("2024", "2819777", "1017440")   # strings
    assert set(usa) == {"year", "country", "metricFOB", "metricKG"}       # monthDetail false: no month


def test_real_comex_backfill_end_to_end(run, session_factory):
    """Real metadata and a trimmed real answer to the whole-year backfill query (2026-11-04)."""
    routes = comex_routes("real_comex_dates_updated_2026-10-06.json", **{
        to.COMEX_FILTERS_URL: F("real_comex_filters.json"), to.COMEX_DETAILS_URL: F("real_comex_details.json"),
        to.COMEX_METRICS_URL: F("real_comex_metrics.json")})
    res = run("br_comexstat", routes, post=comex_post({BACKFILL_QUERY: F("real_comex_general_2023-01_2026-12_trimmed.json")}))
    assert res["status"] == "success" and res["warnings"] == [], res
    posts = [json.loads(r.content) for r in run.sent if r.method == "POST"]
    assert [p["period"] for p in posts] == [{"from": "2023-01", "to": "2026-12"}]
    assert posts[0]["filters"] == [{"filter": "ncm", "values": ["04090000"]}]
    assert posts[0]["details"] == ["country", "state", "ncm"] and posts[0]["metrics"] == ["metricFOB", "metricKG"]
    with session_factory() as s:
        trades = _rows(s, T, "br_comexstat")
        assert len(trades) == 78                                      # destination-months 2023-10..2026-09
        assert min(t.period_label for t in trades) == "2024-01"      # 2023-01/02 rows of the answer dropped
        by = {(t.partner_iso3, t.period_label): t for t in trades}
        u = by[("USA", "2026-09")]
        assert (u.value, u.net_weight_kg, len(u.extra["states"])) == (2_432_659, 705_896, 8)
        assert u.published_at == date(2026, 10, 6) and u.extra["destination_name"] == "United States"
        assert (by[("USA", "2024-01")].value, by[("USA", "2024-01")].net_weight_kg) == (2_819_777, 1_017_440)
        # 2024 to the United States: the same totals UN Comtrade republishes for Brazil (78,637,770 USD, 29,984,910 kg)
        usa_2024 = [t for t in trades if t.partner_iso3 == "USA" and t.period_label.startswith("2024-")]
        assert len(usa_2024) == 12
        assert (sum(t.value for t in usa_2024), sum(t.net_weight_kg for t in usa_2024)) == (78_637_770, 29_984_910)
        assert (by[("DEU", "2026-09")].value, by[("DEU", "2026-09")].net_weight_kg) == (1_324_783, 422_469)
        assert (by[("CAN", "2026-08")].value, by[("CAN", "2026-08")].net_weight_kg) == (1_002_733, 282_690)
        # English names outside the shared country table are mapped too
        assert by[("IMN", "2024-12")].value == 127 and by[("MHL", "2026-09")].net_weight_kg == 198
        assert by[("BRA", "2024-02")].value == 21                    # "Brazil" as published destination
        prices = {(p.market_iso3, p.period_label): p for p in _rows(s, P, "br_comexstat")}
        assert prices[("USA", "2026-09")].price_value == round(2_432_659 / 705_896, 4) == 3.4462
        assert ("MHL", "2026-09") not in prices and ("BRA", "2024-02") not in prices   # under 1 t
        raw = _rows(s, RawDocument, "br_comexstat")
        assert len(raw) == 1 and raw[0].url == to.COMEX_SOURCE_URL


def test_comex_new_release_repulls_trailing_months_and_keeps_revisions(run, session_factory):
    assert run("br_comexstat", comex_routes(), post=comex_post(BACKFILL))["status"] == "success"
    res = run("br_comexstat", comex_routes("comex_dates_updated_2026-11-05.json"),
              post=comex_post({"2026-08_2026-10": F("comex_general_2026-08_2026-10.json")}))
    assert res["status"] == "partial", res                 # partial: a withdrawn flow is reported
    posts = [json.loads(r.content)["period"] for r in run.sent if r.method == "POST"]
    assert posts == [{"from": "2026-08", "to": "2026-10"}]     # only the trailing 3 months
    assert any("NLD 2026-09" in w for w in res["warnings"]), res["warnings"]
    with session_factory() as s:
        hist = _rows(s, T, "br_comexstat", partner_iso3="USA", period_label="2026-08")
        assert [(t.value, t.revision, t.is_current) for t in hist] == [(5_575_000, 1, False), (5_630_000, 2, True)]
        assert hist[1].supersedes_id == hist[0].id and hist[1].published_at == date(2026, 11, 5)
        ph = _rows(s, P, "br_comexstat", market_iso3="USA", period_label="2026-08")
        assert [(p.price_value, p.is_current) for p in ph] == [
            (round(5_575_000 / 1_600_000, 4), False), (round(5_630_000 / 1_600_000, 4), True)]
        # Germany 2026-08 revised below 1 t: trade revised, unit value withdrawn (kept in history)
        assert [t.net_weight_kg for t in _rows(s, T, "br_comexstat", current=True, partner_iso3="DEU",
                                               period_label="2026-08")] == [800]
        de_p = _rows(s, P, "br_comexstat", market_iso3="DEU", period_label="2026-08")
        assert len(de_p) == 1 and de_p[0].is_current is False and de_p[0].price_value == 3.8
        # Netherlands 2026-09 no longer published: withdrawn, never deleted
        nl = _rows(s, T, "br_comexstat", partner_iso3="NLD", period_label="2026-09")
        assert len(nl) == 1 and nl[0].is_current is False
        assert not _rows(s, P, "br_comexstat", current=True, market_iso3="NLD", period_label="2026-09")
        # untouched month: same row, first publication date kept
        u9 = _rows(s, T, "br_comexstat", partner_iso3="USA", period_label="2026-09")
        assert [(t.revision, t.is_current, t.published_at) for t in u9] == [(1, True, date(2026, 10, 6))]
        # the new month
        new = _rows(s, T, "br_comexstat", period_label="2026-10")
        assert {t.partner_iso3 for t in new} == {"USA", "CAN"} and all(t.published_at == date(2026, 11, 5) for t in new)
        assert _state(s, "br_comexstat")["latest_month"] == "2026-10"
        _no_duplicate_current(s)


def test_comex_rate_limit_backoff_then_success(run, session_factory, monkeypatch):
    from paladex.collectors import base

    sleeps: list[float] = []
    calls = {"n": 0}

    def flaky(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, content=b"", headers={"Retry-After": "3"})
        if calls["n"] in (2, 3):
            return httpx.Response(200, content=F("comex_rate_limited.json"))
        return httpx.Response(200, content=BACKFILL["2025-10_2026-09"])

    windows = dict(BACKFILL, **{"2025-10_2026-09": flaky})
    monkeypatch.setattr(base.time, "sleep", sleeps.append)      # after the harness's own no-op patch
    res = run("br_comexstat", comex_routes(), post=comex_post(windows))
    assert res["status"] == "success", res
    # HTTP 429, then two JSON rate-limit answers: the collector's own backoff, 15 s, 30 s, 60 s
    assert [x for x in sleeps if x >= to.COMEX_RATE_LIMIT_DELAY_S] == [15.0, 30.0, 60.0]
    assert sum(r.method == "POST" for r in run.sent) == 4               # no extra quick retries in between
    with session_factory() as s:
        assert len(_rows(s, T, "br_comexstat")) == 14
        assert len(_rows(s, RawDocument, "br_comexstat")) == 1          # rate-limit answers are not archived


def test_comex_persistent_rate_limit_fails_without_storing(run, session_factory):
    def always(request):
        return httpx.Response(200, content=F("comex_rate_limited.json"))

    res = run("br_comexstat", comex_routes(), post=comex_post({w: always for w in BACKFILL}))
    assert res["status"] == "failed" and "too many requests" in res["error"], res
    with session_factory() as s:
        assert _rows(s, T, "br_comexstat") == [] and _rows(s, RawDocument, "br_comexstat") == []
        assert _state(s, "br_comexstat") == {}


def test_comex_schema_drift_fails_loudly(run, session_factory):
    metrics = json.loads(F("comex_metrics.json"))
    metrics["data"]["list"] = [m for m in metrics["data"]["list"] if m["id"] != "metricKG"]
    res = run("br_comexstat", comex_routes(**{to.COMEX_METRICS_URL: json.dumps(metrics).encode()}),
              post=comex_post(BACKFILL))
    assert res["status"] == "failed" and "metric KG" in res["error"], res
    assert not [r for r in run.sent if r.method == "POST"]          # nothing queried

    rows = [r for w in BACKFILL for r in json.loads(BACKFILL[w])["data"]["list"]]
    for r in rows:
        r.pop("metricKG")
    res2 = run("br_comexstat", comex_routes(), post=comex_post({BACKFILL_QUERY: comex_doc(rows)}))
    assert res2["status"] == "failed" and "KG" in res2["error"], res2

    doc = json.loads(F("comex_general_2025-10_2026-09.json"))
    doc["data"]["list"][3]["coNcm"] = "17019900"
    res3 = run("br_comexstat", comex_routes(),
               post=comex_post(dict(BACKFILL, **{"2025-10_2026-09": json.dumps(doc).encode()})))
    assert res3["status"] == "failed" and "ignored the NCM" in res3["error"], res3

    res4 = run("br_comexstat", comex_routes(), post=comex_post(dict(BACKFILL, **{
        "2025-10_2026-09": lambda r: httpx.Response(400, content=b'{"success":false,"message":"Invalid detail: state"}')})))
    assert res4["status"] == "failed" and "Invalid detail: state" in res4["error"], res4
    with session_factory() as s:
        assert _rows(s, T, "br_comexstat") == [] and _rows(s, P, "br_comexstat") == []


def test_comex_unknown_destination_and_bad_row(run, session_factory):
    doc = json.loads(F("comex_general_2025-10_2026-09.json"))
    rows = doc["data"]["list"]
    rows.append({"year": "2026", "monthNumber": "9", "country": "Atlantis", "state": "Bahia", "coNcm": "04090000",
                 "ncm": "Natural honey", "metricFOB": "5000", "metricKG": "1500"})
    # one unusable state row of the United States 2026-08: that destination-month is not stored
    rows.append({"year": "2026", "monthNumber": "8", "country": "United States", "state": "Bahia",
                 "coNcm": "04090000", "ncm": "Natural honey", "metricFOB": "1000", "metricKG": None})
    windows = dict(BACKFILL, **{"2025-10_2026-09": json.dumps(doc).encode()})
    res = run("br_comexstat", comex_routes(), post=comex_post(windows))
    assert res["status"] == "partial", res
    assert sum("Atlantis" in w for w in res["warnings"]) == 1
    assert any("invalid FOB" in w for w in res["warnings"])
    with session_factory() as s:
        assert not _rows(s, T, "br_comexstat", partner_iso3="USA", period_label="2026-08")     # partial sum never stored
        assert _rows(s, T, "br_comexstat", partner_iso3="CAN", period_label="2026-08")         # others are
        assert "Atlantis" in _state(s, "br_comexstat")["unknown_partners"]
    # Warned once: a forced re-pull of the same answer does not warn about Atlantis again.
    res2 = run("br_comexstat", comex_routes(), post=comex_post(windows), force=True)
    assert not any("Atlantis" in w for w in res2["warnings"]), res2


def test_comex_without_state_detail_and_release_date(run, session_factory):
    details = json.dumps({"data": {"list": [{"detail": "country"}, {"detail": "ncm"}]}, "success": True}).encode()
    updated = json.dumps({"data": {"year": 2026, "monthNumber": 9}, "success": True}).encode()
    doc = json.loads(F("comex_general_2025-10_2026-09.json"))
    agg: dict = {}
    for r in doc["data"]["list"]:                       # the API would sum the states itself
        k = (r["year"], r["monthNumber"], r["country"])
        a = agg.setdefault(k, {**{x: r[x] for x in ("year", "monthNumber", "country", "coNcm", "ncm")},
                               "metricFOB": 0, "metricKG": 0})
        a["metricFOB"] += float(r["metricFOB"])
        a["metricKG"] += float(r["metricKG"])
    windows = dict(BACKFILL, **{"2025-10_2026-09": comex_doc(list(agg.values()))})
    res = run("br_comexstat", comex_routes(**{to.COMEX_DETAILS_URL: details, to.COMEX_UPDATED_URL: updated}),
              post=comex_post(windows))
    assert res["status"] == "partial", res
    assert any("state" in w for w in res["warnings"]) and any("release date" in w for w in res["warnings"])
    posts = [json.loads(r.content) for r in run.sent if r.method == "POST"]
    assert posts[0]["details"] == ["country", "ncm"]
    with session_factory() as s:
        u = _rows(s, T, "br_comexstat", partner_iso3="USA", period_label="2026-09")[0]
        assert (u.value, u.net_weight_kg, u.published_at) == (7_470_000, 2_100_000, None)
        assert u.extra["state_detail"] is False and u.extra["states"] is None


# ---------------------------------------------------------------------------------------------
# US Census: pure functions
# ---------------------------------------------------------------------------------------------


def test_census_variable_probe():
    available = to.parse_census_variables(F("census_variables.json"))
    get_vars, optional_missing = to.census_get_list(available)
    assert get_vars[:8] == list(to.CENSUS_REQUIRED_VARS) and optional_missing == []
    assert {"GEN_CIF_MO", "CON_CIF_MO", "DUT_VAL_MO", "CAL_DUT_MO", "SUMMARY_LVL"} <= set(get_vars)
    get2, miss2 = to.census_get_list(available - {"CAL_DUT_MO"})
    assert "CAL_DUT_MO" not in get2 and miss2 == ["CAL_DUT_MO"]
    with pytest.raises(CollectorError, match="CON_QY1_MO"):
        to.census_get_list(available - {"CON_QY1_MO"})
    with pytest.raises(CollectorError, match="COMM_LVL"):
        to.census_get_list(available - {"COMM_LVL"})
    with pytest.raises(CollectorError, match="variables"):
        to.parse_census_variables(b'{"vars": []}')


def test_parse_census_table_and_imports():
    rows = to.parse_census_table(F("census_hs6_2025-11_2026-10.json"))
    assert rows[0]["CTY_CODE"] == "-" and rows[0]["I_COMMODITY"] == "040900" and rows[0]["time"] == "2025-11"
    assert to.parse_census_table(b"") == [] and to.parse_census_table(b"  \n") == []
    with pytest.raises(CollectorError, match="header"):
        to.parse_census_table(b'{"error": "x"}')
    with pytest.raises(CollectorError, match="does not match"):
        to.parse_census_table(b'[["A","B"],["1"]]')

    out = to.parse_census_imports(F("census_hs6_2025-11_2026-10.json"), level="HS6", start=(2025, 11), end=(2026, 10))
    arg = [r for r in out.records if r.cty_code == "3570" and r.period == "2026-08"]
    assert len(arg) == 1
    a = arg[0]
    assert (a.con_val, a.con_kg, a.gen_val, a.gen_kg, a.unit) == (13_650_000, 4_200_000, 13_786_500, 4_242_000, "KG")
    assert (a.con_cif, a.cal_dut, a.summary_lvl) == (round(13_650_000 * 1.045), 79_800, "DET")
    assert out.problems == []

    header = json.loads(F("census_hs6_2025-11_2026-10.json"))[0]
    def table(*rows):
        return json.dumps([header, *rows]).encode()
    base = json.loads(F("census_hs6_2025-11_2026-10.json"))[-1]
    sugar = list(base)
    sugar[2] = sugar[15] = "170199"
    with pytest.raises(CollectorError, match="ignored the commodity filter"):
        to.parse_census_imports(table(base, sugar), level="HS6", start=(2025, 11), end=(2026, 10))
    with pytest.raises(CollectorError, match="CON_VAL_MO"):
        drop = header.index("CON_VAL_MO")
        to.parse_census_imports(json.dumps([[h for i, h in enumerate(header) if i != drop],
                                            [v for i, v in enumerate(base) if i != drop]]).encode(),
                                level="HS6", start=(2025, 11), end=(2026, 10))
    tons = list(base)
    tons[header.index("UNIT_QY1")] = "T"
    bad_val = list(base)
    bad_val[header.index("CON_VAL_MO")] = "(D)"
    late = list(base)
    late[-1] = "2027-01"
    parsed = to.parse_census_imports(table(tons, bad_val, late), level="HS6", start=(2025, 11), end=(2026, 10))
    assert parsed.records == [] and len(parsed.bad) == 1 and len(parsed.problems) == 3


def test_classify_census_country():
    c = to.classify_census_country
    assert c("-", "TOTAL FOR ALL COUNTRIES") == ("WLD", "total")
    assert c("0003", "EUROPEAN UNION", "CGP") == (None, "aggregate")
    assert c("5XXX", "ASIA") == (None, "aggregate")
    assert c("0014", "PACIFIC RIM COUNTRIES") == (None, "aggregate")
    assert c("1220", "CANADA", "CGP") == (None, "aggregate")       # SUMMARY_LVL says grouping
    assert c("3570", "ARGENTINA") == ("ARG", "code")
    assert c("4890", "TURKIYE") == ("TUR", "code")                  # renamed, still agrees with the table
    assert c("5590", "SINGAPORE") == ("SGP", "name")                # code not in the table: mapped by name
    assert c("6140", "NEW ZEALAND") == ("NZL", "name")              # code not in the table: mapped by name
    assert c("4801", "MONTENEGRO") == (None, "conflict")            # table and published name disagree
    assert c("5682", "TOKELAU") == (None, "unknown")
    assert c("-", "SOMETHING ELSE") == (None, "unknown")
    assert c("9999", "NOWHERE") == (None, "unknown")


def test_census_country_table_is_self_consistent():
    for code, (iso, name) in to.CENSUS_COUNTRIES.items():
        assert re.fullmatch(r"[1-7]\d{3}", code), code
        assert to.resolve_country_name(name) == iso, (code, name)
        assert to.classify_census_country(code, name) == (iso, "code")
    research = {"3570": "ARG", "3510": "BRA", "5330": "IND", "5520": "VNM", "5700": "CHN", "4623": "UKR",
                "2010": "MEX", "1220": "CAN", "3550": "URY", "5490": "THA", "4890": "TUR", "4370": "HUN",
                "4850": "ROU"}
    assert {k: to.CENSUS_COUNTRIES[k][0] for k in research} == research


# ---------------------------------------------------------------------------------------------
# US Census: end to end
# ---------------------------------------------------------------------------------------------

CENSUS_DATA = r"^https://api\.census\.gov/data/timeseries/intltrade/imports/hs\?"


def census_q(level: str, span: str, commodity: str | None = None) -> str:
    pat = CENSUS_DATA + rf"(?=.*[?&]COMM_LVL={level}(&|$))(?=.*[?&]time={re.escape(span.replace(' ', '+'))}(&|$))"
    if commodity:
        pat += rf"(?=.*[?&]I_COMMODITY={re.escape(commodity)}(&|$))"
    return pat


def census_routes(**over) -> dict:
    routes = {to.CENSUS_VARIABLES_URL: F("census_variables.json")}
    for span in ("2025-11_2026-10", "2024-11_2025-10", "2023-11_2024-10"):
        a, b = span.split("_")
        routes[census_q("HS6", f"from {a} to {b}")] = F(f"census_hs6_{span}.json")
        routes[census_q("HS10", f"from {a} to {b}")] = F(f"census_hs10_{span}.json")
    routes.update(over)
    return routes


def _data_requests(sent):
    return [r for r in sent if r.url.path.endswith("/imports/hs")]


def test_census_end_to_end_with_key_never_stored(census_key, run, session_factory, pin_today):
    res = run("us_census_trade", census_routes())
    assert res["status"] == "success", res
    data = _data_requests(run.sent)
    assert len(data) == 6 and all(r.url.params.get("key") == SECRET for r in data)
    assert next(r for r in run.sent if r.url.path.endswith("variables.json")).url.params.get("key") is None
    hs6 = [r for r in data if r.url.params["COMM_LVL"] == "HS6"]
    assert [r.url.params["time"] for r in hs6] == ["from 2025-11 to 2026-10", "from 2024-11 to 2025-10",
                                                   "from 2023-11 to 2024-10"]
    assert hs6[0].url.params["I_COMMODITY"] == "040900"
    assert set(hs6[0].url.params["get"].split(",")) >= set(to.CENSUS_REQUIRED_VARS) | {"CAL_DUT_MO", "CON_CIF_MO"}

    with session_factory() as s:
        trades = _rows(s, T, "us_census_trade")
        assert {t.partner_iso3 for t in trades} == {
            "WLD", "ARG", "BRA", "IND", "VNM", "UKR", "MEX", "CAN", "URY", "TUR", "NZL", "SGP"}   # no groupings
        assert all((t.reporter_iso3, t.flow, t.currency, t.value_basis, t.frequency, t.hs_code)
                   == ("USA", "import", "USD", "customs", "M", "0409") for t in trades)
        assert all(t.reliability == "official" and t.data_status == "published" and t.published_at is None
                   for t in trades)
        assert all(t.extra["same_underlying_data_as"] == "usda_fas_gats" for t in trades)
        arg = _rows(s, T, "us_census_trade", partner_iso3="ARG", period_label="2026-08")[0]
        assert (arg.value, arg.net_weight_kg, arg.unit_value_per_kg) == (13_650_000, 4_200_000, 3.25)
        assert arg.usd_value == 13_650_000
        x = arg.extra
        assert x["general_imports"] == {"value_usd": 13_786_500, "kg": 4_242_000}
        assert x["cif_value_usd"] == round(13_650_000 * 1.045) and x["calculated_duty_usd"] == 79_800
        assert x["effective_duty_rate"] == round(79_800 / 13_650_000, 6)
        assert x["cty_code"] == "3570" and x["mapped_by"] == "code" and x["value_field"] == "CON_VAL_MO"
        assert x["hs10_detail"] == "ok"
        assert [(ln["hs10"], ln["kg"], ln["value_usd"]) for ln in x["hs10_lines"]] == [
            ("0409000035", 2_500_000, 8_250_000), ("0409000045", 1_700_000, 5_400_000)]
        assert "hs10_sum_differs_from_total" not in x
        assert _rows(s, T, "us_census_trade", partner_iso3="SGP")[0].extra["mapped_by"] == "name"
        assert _rows(s, T, "us_census_trade", partner_iso3="VNM", period_label="2026-08")[0].extra[
            "hs10_missing_for_partner"] is True
        wld = _rows(s, T, "us_census_trade", partner_iso3="WLD", period_label="2026-08")[0]
        table = json.loads(F("census_hs6_2025-11_2026-10.json"))
        total = next(r for r in table if r[0] == "-" and r[-1] == "2026-08")
        assert wld.value == float(total[table[0].index("CON_VAL_MO")]) and wld.extra["mapped_by"] == "total"

        prices = _rows(s, P, "us_census_trade")
        assert {p.price_type for p in prices} == {PriceType.IMPORT_UNIT_VALUE}
        assert not [p for p in prices if p.origin_iso3 == "WLD"]          # a total is not an origin
        pa = _rows(s, P, "us_census_trade", origin_iso3="ARG", period_label="2026-08")[0]
        assert (pa.price_value, pa.usd_per_kg, pa.currency, pa.unit, pa.market_iso3, pa.variety) == (
            3.25, 3.25, "USD", "kg", "USA", "unspecified")
        assert pa.terms.endswith("HS 0409 total") and pa.volume_kg == 4_200_000
        assert pa.extra["same_underlying_data_as"] == "usda_fas_gats"
        assert pa.extra["cif_unit_value_usd_per_kg"] == round(round(13_650_000 * 1.045) / 4_200_000, 4)
        assert _rows(s, T, "us_census_trade", partner_iso3="TUR")                      # 600 kg: trade only
        assert not _rows(s, P, "us_census_trade", origin_iso3="TUR")
        assert [p.price_value for p in _rows(s, P, "us_census_trade", origin_iso3="SGP")] == [6.0]
        assert all(p.volume_kg >= to.MIN_UNIT_VALUE_WEIGHT_KG for p in prices)

        # The key is never stored: raw documents, row URLs, extras, state, run log.
        raws = _rows(s, RawDocument, "us_census_trade")
        assert len(raws) == 6
        stored = [d.url for d in raws] + [r.source_url for r in trades + prices]
        assert all(SECRET not in u and "key=" not in u for u in stored), stored
        assert all(u.startswith(to.CENSUS_URL + "?") for u in stored)
        blobs = [json.dumps(r.extra) for r in trades + prices] + [json.dumps(_state(s, "us_census_trade"))]
        blobs += [json.dumps([r.warnings, r.error]) for r in s.scalars(select(CollectionRun)).all()]
        assert all(SECRET not in b for b in blobs)
        st = _state(s, "us_census_trade")
        assert st["latest"] == "2026-08" and st["backfill_done"] and st["annual_refresh_year"] == 2026
        assert st["hs10_mode"] == "wildcard"


def test_census_trailing_window_unchanged_and_forced_rerun(run, session_factory, pin_today):
    assert run("us_census_trade", census_routes())["status"] == "success"
    with session_factory() as s:
        n = (len(_rows(s, T, "us_census_trade")), len(_rows(s, P, "us_census_trade")))
    trailing = census_routes(**{
        census_q("HS6", "from 2026-06 to 2026-10"): F("census_hs6_2026-06_2026-10.json"),
        census_q("HS10", "from 2026-06 to 2026-10"): F("census_hs10_2026-06_2026-10.json"),
    })
    # A few days later, before the next release: the trailing 3 months are asked again; same numbers.
    res = run("us_census_trade", trailing)
    assert res["status"] == "no_change" and res["new"] == 0 and res["revised"] == 0, res
    assert [r.url.params["time"] for r in _data_requests(run.sent) if r.url.params["COMM_LVL"] == "HS6"] == [
        "from 2026-06 to 2026-10"]
    # Next check: the same bytes again -> nothing else is requested (no HS-10 query).
    res2 = run("us_census_trade", trailing)
    assert res2["status"] == "no_change", res2
    assert len(_data_requests(run.sent)) == 1
    # Forced: the full window again, still nothing new (idempotent).
    res3 = run("us_census_trade", trailing, force=True)
    assert res3["status"] == "no_change" and res3["new"] == 0 and res3["revised"] == 0, res3
    with session_factory() as s:
        assert (len(_rows(s, T, "us_census_trade")), len(_rows(s, P, "us_census_trade"))) == n
        _no_duplicate_current(s)


def test_census_new_release_revisions_and_withdrawals(run, session_factory, pin_today):
    assert run("us_census_trade", census_routes())["status"] == "success"
    pin_today(date(2026, 12, 8))
    res = run("us_census_trade", census_routes(**{
        census_q("HS6", "from 2026-06 to 2026-11"): F("census_hs6_2026-06_2026-11.json"),
        census_q("HS10", "from 2026-06 to 2026-11"): F("census_hs10_2026-06_2026-11.json"),
    }))
    assert res["status"] == "partial" and res["new"] > 0 and res["revised"] > 0, res
    assert any("UKR 2026-07" in w for w in res["warnings"]), res["warnings"]
    with session_factory() as s:
        hist = _rows(s, T, "us_census_trade", partner_iso3="ARG", period_label="2026-07")
        assert [(t.value, t.revision, t.is_current) for t in hist] == [(12_160_000, 1, False), (12_350_000, 2, True)]
        ph = _rows(s, P, "us_census_trade", origin_iso3="ARG", period_label="2026-07")
        assert [(p.price_value, p.is_current) for p in ph] == [(3.2, False), (3.25, True)]
        # India cut to 800 kg: trade revised, unit value withdrawn but kept in the history
        assert [t.net_weight_kg for t in _rows(s, T, "us_census_trade", current=True, partner_iso3="IND",
                                               period_label="2026-07")] == [800]
        ind_p = _rows(s, P, "us_census_trade", origin_iso3="IND", period_label="2026-07")
        assert [(p.price_value, p.is_current) for p in ind_p] == [(2.15, False)]
        # Ukraine 2026-07 no longer reported: withdrawn, not deleted
        ukr = _rows(s, T, "us_census_trade", partner_iso3="UKR", period_label="2026-07")
        assert [t.is_current for t in ukr] == [False]
        assert not _rows(s, P, "us_census_trade", current=True, origin_iso3="UKR", period_label="2026-07")
        # unchanged month untouched; new month present
        assert [t.revision for t in _rows(s, T, "us_census_trade", partner_iso3="ARG", period_label="2026-08")] == [1]
        assert {t.partner_iso3 for t in _rows(s, T, "us_census_trade", period_label="2026-09")} == {"WLD", "ARG", "BRA"}
        assert _state(s, "us_census_trade")["latest"] == "2026-09"
        _no_duplicate_current(s)


def test_census_keyless_run_sends_no_key(run, session_factory, pin_today):
    res = run("us_census_trade", census_routes())
    assert res["status"] == "success", res
    assert all("key" not in r.url.params for r in run.sent)


def test_census_key_errors(run, session_factory, pin_today, monkeypatch):
    html = (200, F("census_invalid_key.html"), "text/html")
    # Keyless and Census demands a key: skipped with instructions, nothing stored.
    res = run("us_census_trade", {to.CENSUS_VARIABLES_URL: F("census_variables.json"), CENSUS_DATA: html})
    assert res["status"] == "skipped" and "PALADEX_CENSUS_API_KEY" in res["error"], res
    # With a bad key: failed, and the key never appears in the message.
    monkeypatch.setenv("PALADEX_CENSUS_API_KEY", SECRET)
    config.get_settings.cache_clear()
    res2 = run("us_census_trade", {to.CENSUS_VARIABLES_URL: F("census_variables.json"), CENSUS_DATA: html})
    assert res2["status"] == "failed" and "rejected the API key" in res2["error"] and SECRET not in res2["error"]
    # An error text that echoes the request (key included) is scrubbed.
    echo = (400, f"error: unknown predicate variable: 'COMM_LVL' in time=...&key={SECRET}".encode(), "text/plain")
    res3 = run("us_census_trade", {to.CENSUS_VARIABLES_URL: F("census_variables.json"), CENSUS_DATA: echo})
    assert res3["status"] == "failed" and "unknown predicate" in res3["error"], res3
    assert SECRET not in res3["error"] and "key=REDACTED" in res3["error"]
    # A 500 is reported with the URL redacted by the framework.
    res4 = run("us_census_trade", {to.CENSUS_VARIABLES_URL: F("census_variables.json"), CENSUS_DATA: (500, b"oops")})
    assert res4["status"] == "failed" and SECRET not in res4["error"], res4
    config.get_settings.cache_clear()
    with session_factory() as s:
        assert _rows(s, T, "us_census_trade") == []


def test_census_schema_drift_fails_loudly(run, session_factory, pin_today):
    variables = json.loads(F("census_variables.json"))
    del variables["variables"]["CON_QY1_MO"]
    res = run("us_census_trade", census_routes(**{to.CENSUS_VARIABLES_URL: json.dumps(variables).encode()}))
    assert res["status"] == "failed" and "CON_QY1_MO" in res["error"], res
    assert not _data_requests(run.sent)

    rows = json.loads(F("census_hs6_2025-11_2026-10.json"))
    drop = rows[0].index("CON_VAL_MO")
    no_val = [[v for i, v in enumerate(r) if i != drop] for r in rows]
    res2 = run("us_census_trade", census_routes(**{
        census_q("HS6", "from 2025-11 to 2026-10"): json.dumps(no_val).encode()}))
    assert res2["status"] == "failed" and "CON_VAL_MO" in res2["error"], res2

    rows = json.loads(F("census_hs6_2025-11_2026-10.json"))
    for r in rows[1:]:
        r[2] = r[15] = "1701"
    res3 = run("us_census_trade", census_routes(**{
        census_q("HS6", "from 2025-11 to 2026-10"): json.dumps(rows).encode()}))
    assert res3["status"] == "failed" and "ignored the commodity filter" in res3["error"], res3
    with session_factory() as s:
        assert _rows(s, T, "us_census_trade") == [] and _rows(s, P, "us_census_trade") == []


def test_census_optional_variable_missing_is_warned_once(run, session_factory, pin_today):
    variables = json.loads(F("census_variables.json"))
    del variables["variables"]["CAL_DUT_MO"]
    routes = census_routes(**{to.CENSUS_VARIABLES_URL: json.dumps(variables).encode()})
    res = run("us_census_trade", routes)
    assert res["status"] == "partial" and sum("CAL_DUT_MO" in w for w in res["warnings"]) == 1, res
    assert all("CAL_DUT_MO" not in r.url.params["get"] for r in _data_requests(run.sent))
    with session_factory() as s:
        assert _rows(s, T, "us_census_trade")                   # data stored all the same
    res2 = run("us_census_trade", routes, force=True)
    assert not any("CAL_DUT_MO" in w for w in res2["warnings"]), res2


def test_census_hs10_falls_back_to_one_query_per_line(run, session_factory, pin_today):
    def per_line(request):
        code = request.url.params["I_COMMODITY"]
        span = request.url.params["time"].replace("from ", "").replace(" to ", "_")
        hs10 = json.loads(F(f"census_hs10_{span}.json"))
        rows = [r for r in hs10[1:] if r[2] == code]
        if not rows:
            return httpx.Response(204, content=b"")
        return httpx.Response(200, content=json.dumps([hs10[0], *rows]).encode())

    wildcard = r"(?=.*I_COMMODITY=0409%2A)"
    routes = census_routes()
    routes = {k: v for k, v in routes.items() if "COMM_LVL=HS10" not in k}
    routes[CENSUS_DATA + r"(?=.*COMM_LVL=HS10)" + wildcard] = (204, b"")         # wildcard not supported
    routes[CENSUS_DATA + r"(?=.*COMM_LVL=HS10)"] = per_line
    res = run("us_census_trade", routes)
    assert res["status"] == "success", res
    per_code = [r.url.params["I_COMMODITY"] for r in _data_requests(run.sent) if r.url.params["COMM_LVL"] == "HS10"]
    assert per_code[0] == "0409*" and set(per_code[1:7]) == set(to.HONEY_HS10_CODES)
    with session_factory() as s:
        arg = _rows(s, T, "us_census_trade", partner_iso3="ARG", period_label="2026-08")[0]
        assert [ln["hs10"] for ln in arg.extra["hs10_lines"]] == ["0409000035", "0409000045"]
        assert _state(s, "us_census_trade")["hs10_mode"] == "per_code"


def test_census_hs10_unavailable_keeps_totals(run, session_factory, pin_today):
    routes = census_routes()
    routes = {k: v for k, v in routes.items() if "COMM_LVL=HS10" not in k}
    routes[CENSUS_DATA + r"(?=.*COMM_LVL=HS10)"] = (400, b"error: unknown predicate value", "text/plain")
    res = run("us_census_trade", routes)
    assert res["status"] == "partial" and sum("HS-10" in w for w in res["warnings"]) == 1, res
    with session_factory() as s:
        arg = _rows(s, T, "us_census_trade", partner_iso3="ARG", period_label="2026-08")[0]
        assert arg.value == 13_650_000 and arg.extra["hs10_detail"] == "unavailable" and arg.extra["hs10_lines"] is None
        assert _rows(s, P, "us_census_trade", origin_iso3="ARG", period_label="2026-08")


def test_census_unmapped_partner_is_skipped_and_warned_once(run, session_factory, pin_today):
    rows = json.loads(F("census_hs6_2025-11_2026-10.json"))
    template = rows[-1]
    tokelau = list(template)
    tokelau[0], tokelau[1] = "5682", "ATLANTIS"  # no such country: warned once, skipped
    clash = list(template)
    clash[0], clash[1] = "4801", "MONTENEGRO"
    rows += [tokelau, clash]
    routes = census_routes(**{census_q("HS6", "from 2025-11 to 2026-10"): json.dumps(rows).encode()})
    res = run("us_census_trade", routes)
    assert res["status"] == "partial", res
    assert sum("ATLANTIS" in w for w in res["warnings"]) == 1
    assert sum("MONTENEGRO" in w and "code table" in w for w in res["warnings"]) == 1
    with session_factory() as s:
        partners = {t.partner_iso3 for t in _rows(s, T, "us_census_trade")}
        assert "SRB" not in partners and "MNE" not in partners and "BTN" not in partners
        assert _state(s, "us_census_trade")["unknown_partners"] == {"5682": "ATLANTIS", "4801": "MONTENEGRO"}
    res2 = run("us_census_trade", routes, force=True)
    assert not any("ATLANTIS" in w or "MONTENEGRO" in w for w in res2["warnings"]), res2


def test_census_annual_revision_triggers_full_window_once(run, session_factory, pin_today):
    assert run("us_census_trade", census_routes())["status"] == "success"          # backfill on 2026-11-04
    with session_factory() as s:
        assert _state(s, "us_census_trade")["annual_refresh_year"] == 2026
    nothing_new = census_routes(**{CENSUS_DATA: (204, b"")})

    def hs6_spans():
        return [r.url.params["time"] for r in _data_requests(run.sent) if r.url.params["COMM_LVL"] == "HS6"]

    pin_today(date(2027, 3, 1))                      # before the June revision: trailing window only
    assert run("us_census_trade", nothing_new)["status"] == "no_change"
    assert hs6_spans() == ["from 2026-06 to 2027-02"]
    pin_today(date(2027, 6, 20))                     # after it: the whole 36-month window, once
    assert run("us_census_trade", nothing_new)["status"] == "no_change"
    assert hs6_spans() == ["from 2026-06 to 2027-05", "from 2025-06 to 2026-05", "from 2024-06 to 2025-05"]
    with session_factory() as s:
        assert _state(s, "us_census_trade")["annual_refresh_year"] == 2027
    pin_today(date(2027, 7, 1))
    run("us_census_trade", nothing_new)
    # still no month after 2026-08: the trailing window grows (13 months -> two queries), no full refresh
    assert hs6_spans() == ["from 2026-07 to 2027-06", "2026-06"]
    assert to.UsCensusTradeCollector._annual_refresh_due({"annual_refresh_year": 2026}, date(2026, 6, 14)) is False
    assert to.UsCensusTradeCollector._annual_refresh_due({}, date(2026, 6, 15)) is True


def test_census_transient_hs10_failure_fails_the_window(run, session_factory, pin_today):
    """A row stored without its HS-10 lines could never get them later (append-only), so a
    transient HS-10 failure fails the window instead of storing totals without lines."""
    routes = census_routes()
    routes = {k: v for k, v in routes.items() if "COMM_LVL=HS10" not in k}
    routes[CENSUS_DATA + r"(?=.*COMM_LVL=HS10)"] = (500, b"Internal Server Error", "text/plain")
    res = run("us_census_trade", routes)
    assert res["status"] == "failed" and "HTTP 500" in res["error"], res
    with session_factory() as s:
        assert _rows(s, T, "us_census_trade") == [] and _rows(s, RawDocument, "us_census_trade") == []
        assert "hs10_mode" not in _state(s, "us_census_trade")
    # Next run, the HS-10 query works again: the window is stored complete.
    res2 = run("us_census_trade", census_routes())
    assert res2["status"] == "success", res2
    with session_factory() as s:
        arg = _rows(s, T, "us_census_trade", partner_iso3="ARG", period_label="2026-08")[0]
        assert arg.extra["hs10_detail"] == "ok" and len(arg.extra["hs10_lines"]) == 2


def test_census_rate_limit_message(run, session_factory, pin_today):
    limited = (429, b"Too Many Requests", "text/plain")
    res = run("us_census_trade", {to.CENSUS_VARIABLES_URL: F("census_variables.json"), CENSUS_DATA: limited})
    assert res["status"] == "failed" and "rate limit" in res["error"] and "PALADEX_CENSUS_API_KEY" in res["error"], res
