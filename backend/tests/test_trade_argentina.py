"""Tests for collectors/trade_argentina.py: Argentina's official honey exports by destination
(INDEC, `ar_official_exports`).

The fixtures in tests/fixtures/trade_argentina/ are REAL captures of INDEC's query system
(2026-11-05, see the README there). Variants (a new release, a revision, a new data year, an
inconsistent month, schema drift) are built from them here, in code.
"""
from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import func, select

from paladex.collectors import trade_argentina as ta
from paladex.collectors.base import CollectorError
from paladex.enums import DataStatus, PriceType
from paladex.models import AppSetting, PriceObservation, RawDocument, Source, TradeFlowObservation

FIX = Path(__file__).parent / "fixtures" / "trade_argentina"
STATIC = "real_indec_staticData_2026-11-05.json"
YEARS = (2023, 2024, 2025, 2026)
BY, TOT = ta.QUERY_BY_DESTINATION, ta.QUERY_TOTAL
T, P = TradeFlowObservation, PriceObservation
KEY = "ar_official_exports"


def F(name: str) -> bytes:
    return (FIX / name).read_bytes()


def J(name: str):
    return json.loads(F(name))


def dumps(doc) -> bytes:
    return json.dumps(doc, ensure_ascii=False).encode()


def answer_file(year: int, query: str) -> str:
    return f"real_indec_exports_{year}_{'by_destination' if query == BY else 'total'}.json"


def real_answers() -> dict[tuple[int, str], bytes]:
    return {(y, q): F(answer_file(y, q)) for y in YEARS for q in (BY, TOT)}


def static_variant(last_year: int = 2026, last_month: int = 9, updates: dict[int, str] | None = None) -> bytes:
    doc = J(STATIC)
    doc["lastYear"], doc["lastMonth"] = last_year, last_month
    for year, stamp in (updates or {}).items():
        item = next((x for x in doc["yearsStatus"] if x["year"] == year), None)
        if item is None:
            doc["yearsStatus"].append({"year": year, "export": stamp, "import": stamp})
        else:
            item["export"] = stamp
    return dumps(doc)


# ---------------------------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------------------------


@pytest.fixture()
def run(db, monkeypatch):
    """Run the collector offline. `answers` maps (year, countryQuery) to bytes or (status, bytes).
    The requests of the last run are in `run.sent`."""
    from paladex.collectors import base
    from paladex.collectors.runner import run_collector

    monkeypatch.setattr(base.time, "sleep", lambda *_: None)

    def _run(answers: dict | None = None, *, static: bytes | tuple[int, bytes] | None = None,
             force: bool = False) -> dict:
        answers = real_answers() if answers is None else answers
        static = F(STATIC) if static is None else static
        sent: list[httpx.Request] = []
        _run.sent = sent

        def reply(spec) -> httpx.Response:
            status, body = spec if isinstance(spec, tuple) else (200, spec)
            return httpx.Response(status, content=body, headers={"content-type": "application/json; charset=utf-8"})

        def on_static(request):
            sent.append(request)
            return reply(static)

        def on_search(request):
            sent.append(request)
            p = request.url.params
            # Exactly what INDEC's own form sends for honey exports by month.
            assert (p["commerceType"], p["period"], p["countries"]) == ("export", "month", "[]")
            assert json.loads(p["products"]) == ["04090000"]
            key = (int(p["year"]), p["countryQuery"])
            if key not in answers:
                raise AssertionError(f"unexpected INDEC query {key}")
            return reply(answers[key])

        with respx.mock(assert_all_called=False) as mock:
            mock.route(method="GET", url__startswith=ta.INDEC_STATIC_URL).mock(side_effect=on_static)
            mock.route(method="GET", url__startswith=ta.INDEC_SEARCH_URL).mock(side_effect=on_search)
            mock.route().mock(side_effect=httpx.ConnectError("blocked in tests"))
            with httpx.Client(follow_redirects=True) as client:
                return run_collector(KEY, trigger="test", force=force, client=client)

    _run.sent = []
    return _run


def queries(sent) -> list[tuple[int, str]]:
    return [(int(r.url.params["year"]), r.url.params["countryQuery"]) for r in sent if "/search/" in r.url.path]


def _rows(s, model, *, current: bool | None = None, **where):
    src = s.scalars(select(Source).where(Source.key == KEY)).one()
    q = select(model).where(model.source_id == src.id)
    if current is not None:
        q = q.where(model.is_current.is_(current))
    for k, v in where.items():
        q = q.where(getattr(model, k) == v)
    return s.scalars(q.order_by(model.id)).all()


def _state(s) -> dict:
    row = s.get(AppSetting, f"collector_state:{KEY}")
    return dict(row.value) if row else {}


def _no_duplicate_current(s) -> None:
    for model in (T, P):
        dup = s.execute(select(model.source_id, model.series_key, func.count()).where(model.is_current.is_(True))
                        .group_by(model.source_id, model.series_key).having(func.count() > 1)).all()
        assert dup == [], dup


# ---------------------------------------------------------------------------------------------
# Registration and pure functions
# ---------------------------------------------------------------------------------------------


def test_registered_with_official_metadata():
    from paladex.collectors.registry import get_collector

    c = get_collector(KEY)
    assert c is not None and isinstance(c, ta.ArIndecExportsCollector)
    assert (c.reliability, c.category, c.country_iso3, c.kind, c.requires_key) == ("official", "trade", "ARG", "api", None)
    assert 0 < len(c.expected_update) < 120 and 0 < len(c.expected_update_en) < 120
    assert c.schedule == {"trigger": "cron", "day": "14-28", "day_of_week": "mon-fri", "hour": 21, "minute": 35}
    assert "confidential" in c.terms_note and "BY-SA" in c.terms_note and "not market quotations" in c.terms_note
    # INTA producer prices are documented as not built: no such collector is registered.
    assert get_collector("ar_inta_honey_prices") is None
    assert "ar_inta_honey_prices" in ta.__doc__ and "repositorio.inta.gob.ar" in ta.__doc__


def test_parse_real_static_data_and_dates():
    rel = ta.parse_static_data(F(STATIC))
    assert (rel.last_year, rel.last_month, rel.latest_label) == (2026, 9, "2026-09")
    assert {y: rel.updates[y] for y in YEARS} == {
        2023: date(2026, 4, 20), 2024: date(2025, 4, 16), 2025: date(2026, 3, 19), 2026: date(2026, 10, 16)}
    assert rel.updates_raw[2026] == "2026-10-16T03:00:00.000Z"
    assert rel.signature == "2026-09|2026-10-16T03:00:00.000Z"
    # Buenos Aires dates (UTC-3): INDEC's timestamps are local midnights.
    assert ta.indec_date("2026-10-16T03:00:00.000Z") == date(2026, 10, 16)
    assert ta.indec_date("2026-10-16T02:59:00.000Z") == date(2026, 10, 15)
    assert ta.indec_date("2026-10-16") == date(2026, 10, 16)
    assert ta.indec_date("") is None and ta.indec_date(None) is None and ta.indec_date("pronto") is None


def test_parse_static_data_fails_loudly_on_drift():
    doc = J(STATIC)
    for drop, match in (("lastMonth", "lastMonth"), ("lastYear", "lastYear"), ("yearsStatus", "yearsStatus")):
        bad = {k: v for k, v in doc.items() if k != drop}
        with pytest.raises(CollectorError, match=match):
            ta.parse_static_data(dumps(bad))
    with pytest.raises(CollectorError, match="lastMonth"):
        ta.parse_static_data(dumps({**doc, "lastMonth": 13}))
    with pytest.raises(CollectorError, match="export update date"):
        ta.parse_static_data(dumps({**doc, "yearsStatus": [{"year": 2026, "exp": "x"}]}))
    with pytest.raises(CollectorError, match="not valid JSON"):
        ta.parse_static_data(b"<html>mantenimiento</html>")
    with pytest.raises(CollectorError, match="expected an object"):
        ta.parse_static_data(b"[]")


def test_parse_real_search_answers():
    dest = ta.parse_indec_search(F(answer_file(2026, BY)), year=2026, by_destination=True)
    assert (len(dest.rows), len(dest.masked), dest.bad, dest.problems) == (66, 92, [], [])
    assert dest.description == "Miel natural"
    us = next(r for r in dest.rows if r.iso2 == "US" and r.month == 8)
    assert (us.amount, us.weight, us.country_id, us.name) == (15_140_656.83, 5_130_298.9, "212", "Estados Unidos")
    assert all(r.amount is None and r.weight is None for r in dest.masked)       # never a zero
    assert [r.month for r in dest.masked if r.iso2 == "IT"] == [3, 4, 6, 7, 8, 9]
    assert sorted(r.month for r in dest.rows if r.iso2 == "ZZ") == list(range(1, 10))   # the 999 bucket
    assert next(r.name for r in dest.masked if r.iso2 == "CZ") == "República Checa"   # "República Checa  "
    tot = ta.parse_indec_search(F(answer_file(2026, TOT)), year=2026, by_destination=False)
    assert [(r.month, r.amount, r.weight) for r in tot.rows][:2] == [(1, 13_966_239.59, 5_809_046.6),
                                                                    (2, 20_967_603.33, 8_582_370.2)]
    assert tot.masked == [] and tot.bad == [] and all(r.country_id is None for r in tot.rows)
    # INDEC's total = visible destinations + the confidential bucket, in every month of every year.
    for year in YEARS:
        d = ta.parse_indec_search(F(answer_file(year, BY)), year=year, by_destination=True)
        t = ta.parse_indec_search(F(answer_file(year, TOT)), year=year, by_destination=False)
        for row in t.rows:
            vis = [r for r in d.rows if r.month == row.month]
            assert abs(sum(r.amount for r in vis) - row.amount) < 0.01, (year, row.month)
            assert abs(sum(r.weight for r in vis) - row.weight) < 0.01, (year, row.month)


def test_parse_search_fails_loudly_and_flags_bad_rows():
    rows = J(answer_file(2026, BY))
    with pytest.raises(CollectorError, match="answered an error"):
        ta.parse_indec_search(dumps({"message": "Internal error"}), year=2026, by_destination=True)
    with pytest.raises(CollectorError, match="expected a list"):
        ta.parse_indec_search(b'"x"', year=2026, by_destination=True)
    with pytest.raises(CollectorError, match="not valid JSON"):
        ta.parse_indec_search(b"<html></html>", year=2026, by_destination=True)
    sugar = copy.deepcopy(rows)
    sugar[5]["product"]["id"] = "17019900"
    with pytest.raises(CollectorError, match="ignored the product filter"):
        ta.parse_indec_search(dumps(sugar), year=2026, by_destination=True)
    no_weight = [{k: v for k, v in r.items() if k != "weight"} for r in rows]
    with pytest.raises(CollectorError, match="schema drift.*weight"):
        ta.parse_indec_search(dumps(no_weight), year=2026, by_destination=True)
    no_iso = copy.deepcopy(rows)
    for r in no_iso:
        r["country"].pop("iso2")
    with pytest.raises(CollectorError, match="country.iso2"):
        ta.parse_indec_search(dumps(no_iso), year=2026, by_destination=True)
    with pytest.raises(CollectorError, match="destination rows instead of the total"):
        ta.parse_indec_search(dumps(rows), year=2026, by_destination=False)
    assert ta.parse_indec_search(b"[]", year=2027, by_destination=True).rows == []

    odd = copy.deepcopy(rows[:3])
    us = copy.deepcopy(next(r for r in rows if r["country"]["iso2"] == "US"))
    odd += [{**us, "month": 13}, {**us, "month": 4, "amount": "n/d"}, {**us, "month": 5, "amount": 0, "weight": 0},
            {**us, "month": 6, "amount": 10.0, "weight": 5.0, "isConfidential": True}]
    out = ta.parse_indec_search(dumps(odd), year=2026, by_destination=True)
    assert [r.month for r in out.bad] == [4, 5]
    assert any("unreadable month 13" in p for p in out.problems)
    assert any("unusable FOB" in p for p in out.problems)
    assert any("without the confidentiality flag" in p for p in out.problems)
    assert any("marked confidential but carries numbers" in p for p in out.problems)
    assert any(r.month == 6 and r.amount is None for r in out.masked)


@pytest.mark.parametrize("code, iso2, name, expected", [
    ("212", "US", "Estados Unidos", ("USA", "iso2")),
    ("438", "DE", "República Federal de Alemania", ("DEU", "iso2")),
    ("451", "CZ", "República Checa  ", ("CZE", "iso2")),
    ("417", "IT", "Italia", ("ITA", "iso2")),
    ("313", "TW", "Taiwán", ("TWN", "iso2")),
    ("109", "CD", "Congo, Rep. Democrática del ", ("COD", "iso2")),
    ("999", "ZZ", "Confidencial", (None, "confidential")),
    ("229", "QT", "Territorios vinculados a Francia (América)", (None, "aggregate")),
    ("511", "XK", "Teritorios vinculados a Estados Unidos(Australia)", (None, "aggregate")),   # not Kosovo
    ("298", "QZ", "Indeterminado (América)", (None, "aggregate")),
    ("508", "PN", "Teritorios vinculados al Reino Unido(Australia)", (None, "conflict")),
    ("241", "AN", "Antillas Holandesas (territorio vinculado a Países Bajos)", (None, "unknown")),
    ("777", "", "Sin nombre", (None, "unknown")),
])
def test_map_indec_country(code, iso2, name, expected):
    assert ta.map_indec_country(code, iso2, name) == expected


def test_status_rule():
    assert ta.indec_data_status(2026, 2026) == DataStatus.PROVISIONAL
    assert ta.indec_data_status(2025, 2026) == DataStatus.PROVISIONAL
    assert ta.indec_data_status(2024, 2026) == DataStatus.PUBLISHED
    assert ta.indec_data_status(2025, 2027) == DataStatus.PUBLISHED
    assert ta.search_params(2026, BY) == {"commerceType": "export", "year": "2026", "period": "month",
                                          "countryQuery": "allCountries", "products": '["04090000"]', "countries": "[]"}


# ---------------------------------------------------------------------------------------------
# End to end on the real captures
# ---------------------------------------------------------------------------------------------


def test_real_backfill_end_to_end(run, session_factory):
    res = run()
    assert res["status"] == "success" and res["warnings"] == [], res
    assert res["new"] == 537
    assert run.sent[0].url.path == "/public-api/staticData"
    assert queries(run.sent) == [(y, q) for y in (2026, 2025, 2024, 2023) for q in (BY, TOT)]   # newest first

    with session_factory() as s:
        trades = _rows(s, T)
        assert len(trades) == 291                                   # 246 destination-months + 45 monthly totals
        assert {t.partner_iso3 for t in trades} == {"WLD", "USA", "DEU", "ESP", "JPN", "BEL", "NLD", "CHE", "GBR",
                                                    "ITA", "COL", "FRA", "CAN"}
        assert all((t.reporter_iso3, t.flow, t.currency, t.value_basis, t.frequency, t.hs_code, t.reliability)
                   == ("ARG", "export", "USD", "FOB", "M", "0409", "official") for t in trades)
        assert all(t.raw_document_id and t.source_url.startswith(ta.INDEC_SEARCH_URL + "?") for t in trades)
        by = {(t.partner_iso3, t.period_label): t for t in trades}

        us = by[("USA", "2026-08")]
        assert (us.value, us.net_weight_kg, us.unit_value_per_kg) == (15_140_656.83, 5_130_298.9, 2.9512)
        assert (us.period_start, us.period_end, us.published_at) == (date(2026, 8, 1), date(2026, 8, 31), date(2026, 10, 16))
        assert us.data_status == "provisional" and us.usd_value == 15_140_656.83
        assert "year=2026" in us.source_url and "countryQuery=allCountries" in us.source_url
        x = us.extra
        assert (x["indec_country_code"], x["indec_iso2"], x["destination_name"], x["mapped_by"]) == (
            "212", "US", "Estados Unidos", "iso2")
        assert x["bulk_packaged_split"] is None and x["ncm"] == "04090000" and x["indec_last_update"] == "2026-10-16"
        # Status and publication date follow the year: provisional for 2025-2026, published before.
        assert {(t.period_label[:4], t.data_status, t.published_at) for t in trades} == {
            ("2026", "provisional", date(2026, 10, 16)), ("2025", "provisional", date(2026, 3, 19)),
            ("2024", "published", date(2025, 4, 16)), ("2023", "published", date(2026, 4, 20))}

        # Masked cells are never stored: Italy is visible in 3 months of 2026 only.
        assert sorted(t.period_label for t in trades if t.partner_iso3 == "ITA" and t.period_label >= "2026") == [
            "2026-01", "2026-02", "2026-05"]
        w7 = by[("WLD", "2026-07")]
        assert (w7.value, w7.net_weight_kg) == (23_326_464.86, 8_317_307.9)
        assert "countryQuery=totalImported" in w7.source_url
        assert w7.extra["confidential_bucket"] == {"fob_usd": 2_602_649.51, "kg": 933_668.0, "indec_country_code": "999"}
        assert {m["iso3"] for m in w7.extra["masked_destinations"]} >= {"ITA", "DEU", "NLD", "BEL", "GBR", "CHE"}
        assert w7.extra["visible_destinations"] == 3 and w7.extra["sum_check"] == "ok"
        assert w7.extra["not_allocated"] is None

        # Cross-check with UN Comtrade 2024 (78,375,279.5 kg, USD 170,816,007.85 for Argentina): Comtrade's
        # total is INDEC's visible destinations; INDEC's total adds its "Confidencial" bucket.
        y24 = [t for t in trades if t.period_label.startswith("2024")]
        wld = [t for t in y24 if t.partner_iso3 == "WLD"]
        dest = [t for t in y24 if t.partner_iso3 != "WLD"]
        assert len(wld) == 12
        assert round(sum(t.net_weight_kg for t in wld), 2) == 85_736_012.88
        assert round(sum(t.value for t in wld), 2) == 186_316_696.62
        assert round(sum(t.value for t in dest), 2) == 170_816_007.85
        assert abs(sum(t.net_weight_kg for t in dest) - 78_375_279.5) < 10
        bucket = [t.extra["confidential_bucket"] for t in wld]
        assert round(sum(b["kg"] for b in bucket), 1) == 7_360_739.2
        assert round(sum(b["fob_usd"] for b in bucket), 2) == 15_500_688.77
        assert round(sum(t.net_weight_kg for t in dest) + sum(b["kg"] for b in bucket), 2) == 85_736_012.88

        prices = _rows(s, P)
        assert len(prices) == 246
        assert {p.price_type for p in prices} == {PriceType.EXPORT_UNIT_VALUE}
        assert all((p.origin_iso3, p.currency, p.unit, p.terms, p.variety) == ("ARG", "USD", "kg", "FOB", "unspecified")
                   for p in prices)
        assert all(p.volume_kg >= ta.MIN_UNIT_VALUE_WEIGHT_KG for p in prices)
        assert not [p for p in prices if p.market_iso3 == "WLD"]        # a total is not a market
        pu = _rows(s, P, market_iso3="USA", period_label="2026-08")[0]
        assert (pu.price_value, pu.usd_per_kg, pu.market_location, pu.origin_label) == (2.9512, 2.9512, "United States",
                                                                                        "Argentina")
        assert (pu.published_at, pu.data_status, pu.reliability) == (date(2026, 10, 16), "provisional", "official")

        raws = _rows(s, RawDocument)
        assert len(raws) == 9 and raws[0].url == ta.INDEC_STATIC_URL
        st = _state(s)
        assert st["years"] == {
            "2026": {"update": "2026-10-16T03:00:00.000Z", "status": "provisional", "parser": ta.PARSER_VERSION},
            "2025": {"update": "2026-03-19T03:00:00.000Z", "status": "provisional", "parser": ta.PARSER_VERSION},
            "2024": {"update": "2025-04-16T03:00:00.000Z", "status": "published", "parser": ta.PARSER_VERSION},
            "2023": {"update": "2026-04-20T03:00:00.000Z", "status": "published", "parser": ta.PARSER_VERSION}}
        assert (st["latest_month"], st["last_year"], st["release"]) == ("2026-09", 2026, "2026-09|2026-10-16T03:00:00.000Z")
        src = s.scalars(select(Source).where(Source.key == KEY)).one()
        assert (src.latest_published_at, src.latest_period_label) == (date(2026, 10, 16), "2026-09")
        _no_duplicate_current(s)


def test_same_release_is_one_request_and_forced_rerun_is_idempotent(run, session_factory):
    assert run()["status"] == "success"
    with session_factory() as s:
        n = (len(_rows(s, T)), len(_rows(s, P)))
    res = run()
    assert res["status"] == "no_change" and res["seen"] == 0, res
    assert [r.url.path for r in run.sent] == ["/public-api/staticData"]
    res = run(force=True)
    assert res["status"] == "no_change" and res["new"] == 0 and res["revised"] == 0 and res["seen"] == 537, res
    assert len(queries(run.sent)) == 8
    with session_factory() as s:
        assert (len(_rows(s, T)), len(_rows(s, P))) == n
        assert len(_rows(s, RawDocument)) == 9                     # identical bytes are not archived twice
        _no_duplicate_current(s)


def _new_release_2026() -> tuple[bytes, bytes]:
    """INDEC's next release, built from the real 2026 answers: October added, the United States
    revised for September, Spain's September masked (its trade moved into the confidential bucket)."""
    dest, tot = J(answer_file(2026, BY)), J(answer_file(2026, TOT))
    us9 = next(r for r in dest if r["country"]["iso2"] == "US" and r["month"] == 9)
    es9 = next(r for r in dest if r["country"]["iso2"] == "ES" and r["month"] == 9)
    zz9 = next(r for r in dest if r["country"]["iso2"] == "ZZ" and r["month"] == 9)
    t9 = next(r for r in tot if r["month"] == 9)
    us9["amount"] += 100_000.0
    us9["weight"] += 20_000.0
    t9["amount"] += 100_000.0
    t9["weight"] += 20_000.0
    zz9["amount"] += es9["amount"]
    zz9["weight"] += es9["weight"]
    es9.update(amount=0, weight=0, isConfidential=True)
    oct_rows = [({**us9, "month": 10, "amount": 12_000_000.0, "weight": 4_000_000.0}),
                ({**zz9, "month": 10, "amount": 1_400_000.0, "weight": 500_000.0})]
    it = next(r for r in dest if r["country"]["iso2"] == "IT")
    oct_rows.append({**it, "month": 10, "amount": 0, "weight": 0, "isConfidential": True})
    dest += [copy.deepcopy(r) for r in oct_rows]
    tot.append({**copy.deepcopy(t9), "month": 10, "amount": 13_400_000.0, "weight": 4_500_000.0})
    return dumps(dest), dumps(tot)


def test_new_release_pulls_only_the_latest_year_and_keeps_revisions(run, session_factory):
    assert run()["status"] == "success"
    dest, tot = _new_release_2026()
    answers = {**real_answers(), (2026, BY): dest, (2026, TOT): tot}
    res = run(answers, static=static_variant(last_month=10, updates={2026: "2026-11-19T03:00:00.000Z"}))
    assert res["status"] == "partial", res                          # partial: a withdrawn flow is reported
    assert queries(run.sent) == [(2026, BY), (2026, TOT)]
    assert any("ESP 2026-09" in w for w in res["warnings"]), res["warnings"]
    with session_factory() as s:
        hist = _rows(s, T, partner_iso3="USA", period_label="2026-09")
        assert [(t.value, t.revision, t.is_current) for t in hist] == [
            (16_939_536.56, 1, False), (17_039_536.56, 2, True)]
        assert hist[1].supersedes_id == hist[0].id and hist[1].published_at == date(2026, 11, 19)
        assert [p.is_current for p in _rows(s, P, market_iso3="USA", period_label="2026-09")] == [False, True]
        # Spain, September: now confidential, so withdrawn (kept in the history), never set to zero
        es = _rows(s, T, partner_iso3="ESP", period_label="2026-09")
        assert len(es) == 1 and es[0].is_current is False and es[0].value == 1_573_643.8
        assert not _rows(s, P, current=True, market_iso3="ESP", period_label="2026-09")
        w9 = _rows(s, T, current=True, partner_iso3="WLD", period_label="2026-09")[0]
        assert "ESP" in {m["iso3"] for m in w9.extra["masked_destinations"]}
        # An untouched month keeps its row and its first publication date
        assert [(t.revision, t.published_at) for t in _rows(s, T, partner_iso3="USA", period_label="2026-08")] == [
            (1, date(2026, 10, 16))]
        new = _rows(s, T, period_label="2026-10")
        assert {(t.partner_iso3, t.value, t.published_at) for t in new} == {
            ("USA", 12_000_000.0, date(2026, 11, 19)), ("WLD", 13_400_000.0, date(2026, 11, 19))}
        w10 = next(t for t in new if t.partner_iso3 == "WLD")
        assert [m["iso3"] for m in w10.extra["masked_destinations"]] == ["ITA"]
        assert w10.extra["confidential_bucket"]["kg"] == 500_000.0
        st = _state(s)
        assert st["latest_month"] == "2026-10" and st["years"]["2026"]["update"] == "2026-11-19T03:00:00.000Z"
        _no_duplicate_current(s)


def test_new_data_year_promotes_the_year_before_last_to_published(run, session_factory):
    assert run()["status"] == "success"
    # January 2027 is published: 2025 is no longer one of the two provisional years. 2027's answers
    # are the real January 2026 rows, re-asked as 2027.
    dest = [r for r in J(answer_file(2026, BY)) if r["month"] == 1]
    tot = [r for r in J(answer_file(2026, TOT)) if r["month"] == 1]
    answers = {**real_answers(), (2027, BY): dumps(dest), (2027, TOT): dumps(tot)}
    res = run(answers, static=static_variant(2027, 1, {2027: "2027-02-19T03:00:00.000Z"}))
    assert res["status"] == "success", res
    assert queries(run.sent) == [(2027, BY), (2027, TOT), (2025, BY), (2025, TOT)]   # 2026 and 2024 unchanged
    with session_factory() as s:
        y25 = [t for t in _rows(s, T) if t.period_label.startswith("2025")]
        assert {(t.data_status, t.is_current, t.revision) for t in y25} == {("provisional", False, 1),
                                                                            ("published", True, 2)}
        cur = [t for t in y25 if t.is_current]
        old = [t for t in y25 if not t.is_current]
        assert sorted((t.series_key, t.value, t.net_weight_kg) for t in cur) == sorted(
            (t.series_key, t.value, t.net_weight_kg) for t in old)        # same figures, firmer status
        assert all(p.data_status == "published" for p in _rows(s, P, current=True) if p.period_label.startswith("2025"))
        assert {t.data_status for t in _rows(s, T, current=True) if t.period_label.startswith("2026")} == {"provisional"}
        y27 = _rows(s, T, current=True, period_label="2027-01")
        assert {t.data_status for t in y27} == {"provisional"} and {t.published_at for t in y27} == {date(2027, 2, 19)}
        st = _state(s)
        assert st["latest_month"] == "2027-01" and st["years"]["2025"]["status"] == "published"
        assert set(st["years"]) == {"2023", "2024", "2025", "2026", "2027"}
        _no_duplicate_current(s)


def test_inconsistent_month_is_not_stored_and_asked_again(run, session_factory):
    tot = J(answer_file(2026, TOT))
    next(r for r in tot if r["month"] == 9)["amount"] += 1_000.0
    res = run({**real_answers(), (2026, TOT): dumps(tot)})
    assert res["status"] == "partial", res
    assert any("2026-09" in w and "add up to" in w for w in res["warnings"]), res["warnings"]
    with session_factory() as s:
        assert not _rows(s, T, period_label="2026-09")             # neither destinations nor total
        assert _rows(s, T, partner_iso3="USA", period_label="2026-08")
        st = _state(s)
        assert set(st["years"]) == {"2025", "2024", "2023"} and "latest_month" not in st
    # Next run, INDEC's answers agree again: only 2026 is asked again, and September is stored.
    res = run()
    assert res["status"] == "success", res
    assert queries(run.sent) == [(2026, BY), (2026, TOT)]
    with session_factory() as s:
        assert {t.partner_iso3 for t in _rows(s, T, period_label="2026-09")} == {
            "WLD", "USA", "ESP", "JPN", "NLD", "DEU", "CHE"}
        assert _state(s)["latest_month"] == "2026-09"


def test_unmapped_unreadable_and_conflicting_rows(run, session_factory):
    dest, tot = J(answer_file(2026, BY)), J(answer_file(2026, TOT))
    tmpl = next(r for r in dest if r["country"]["iso2"] == "US" and r["month"] == 8)

    def add(month: int, cid: str, iso2: str, name: str, amount, weight):
        dest.append({**copy.deepcopy(tmpl), "country": {"name": name, "iso2": iso2, "id": cid}, "month": month,
                     "amount": amount, "weight": weight})
        if isinstance(amount, (int, float)):
            t = next(r for r in tot if r["month"] == month)
            t["amount"] += amount
            t["weight"] += weight

    add(8, "298", "QZ", "Indeterminado (América)", 2_000.0, 1_000.0)          # a grouping: total only
    add(4, "508", "PN", "Teritorios vinculados al Reino Unido(Australia)", 500.0, 100.0)   # name disagrees
    add(5, "424", "PL", "Polonia", 0, 0)                                       # 0 / 0 without the flag
    de9 = next(r for r in dest if r["country"]["iso2"] == "DE" and r["month"] == 9)
    de9["amount"] = "n/d"                                                      # unreadable
    answers = {**real_answers(), (2026, BY): dumps(dest), (2026, TOT): dumps(tot)}
    res = run(answers)
    assert res["status"] == "partial", res
    w = res["warnings"]
    assert sum("Indeterminado" in x and "kept only in the total" in x for x in w) == 1
    assert sum("PN" in x and "another country" in x for x in w) == 1
    assert any("Polonia" in x and "without the confidentiality flag" in x for x in w)
    assert any("República Federal de Alemania, 2026-09" in x and "unusable" in x for x in w)
    with session_factory() as s:
        w8 = _rows(s, T, partner_iso3="WLD", period_label="2026-08")[0]
        assert w8.extra["not_allocated"] == [{"name": "Indeterminado (América)", "indec_country_code": "298",
                                              "iso2": "QZ", "fob_usd": 2_000.0, "kg": 1_000.0, "why": "aggregate"}]
        assert w8.net_weight_kg == round(7_623_979.1 + 1_000.0, 3) and w8.extra["sum_check"] == "ok"
        assert not _rows(s, T, partner_iso3="DEU", period_label="2026-09")   # never a partial figure
        w9 = _rows(s, T, partner_iso3="WLD", period_label="2026-09")[0]
        assert w9.extra["sum_check"] == "not possible (unreadable destination row)"
        assert w9.value == 23_686_271.62                                     # INDEC's own total is still stored
        assert not _rows(s, T, partner_iso3="POL")
        assert "508" in _state(s)["unknown_partners"]
    # Warned once: a forced re-run does not repeat the territory and mapping warnings (the data
    # problems of the answer itself are reported again).
    res2 = run(answers, force=True)
    assert not any("Indeterminado" in x or "PN" in x for x in res2["warnings"]), res2["warnings"]
    assert any("unusable" in x for x in res2["warnings"])


def test_failures_store_nothing_or_keep_earlier_years(run, session_factory):
    res = run(static=b"<html>Sitio en mantenimiento</html>")
    assert res["status"] == "failed" and "not valid JSON" in res["error"], res
    res = run(static=dumps({k: v for k, v in J(STATIC).items() if k != "lastMonth"}))
    assert res["status"] == "failed" and "lastMonth" in res["error"], res
    res = run({**real_answers(), (2026, BY): dumps({"message": "Error interno"})})
    assert res["status"] == "failed" and "answered an error" in res["error"], res
    res = run({**real_answers(), (2026, BY): (500, b"Internal Server Error")})
    assert res["status"] == "failed" and "HTTP 500" in res["error"], res
    with session_factory() as s:
        assert _rows(s, T) == [] and _rows(s, P) == [] and _state(s) == {}

    # A late failure (2025 ignores the product filter) keeps the year already stored.
    bad = J(answer_file(2025, BY))
    bad[0]["product"]["id"] = "17019900"
    res = run({**real_answers(), (2025, BY): dumps(bad)})
    assert res["status"] == "failed" and "ignored the product filter" in res["error"], res
    with session_factory() as s:
        assert {t.period_label[:4] for t in _rows(s, T)} == {"2026"}
        assert set(_state(s)["years"]) == {"2026"}
    res = run()
    assert res["status"] == "success", res
    assert queries(run.sent) == [(y, q) for y in (2025, 2024, 2023) for q in (BY, TOT)]
    with session_factory() as s:
        assert len(_rows(s, T)) == 291
        _no_duplicate_current(s)


def test_empty_year_late_month_and_confidential_total(run, session_factory):
    dest, tot = J(answer_file(2026, BY)), J(answer_file(2026, TOT))
    # A month after INDEC's own newest month (2026-09) is ignored, with a warning.
    us9 = next(r for r in dest if r["country"]["iso2"] == "US" and r["month"] == 9)
    dest.append({**copy.deepcopy(us9), "month": 10})
    tot.append({**copy.deepcopy(next(r for r in tot if r["month"] == 9)), "month": 10, "amount": us9["amount"],
                "weight": us9["weight"]})
    # A whole-NCM total under statistical secrecy (never seen for honey): no WLD row, destinations kept.
    t8 = next(r for r in tot if r["month"] == 8)
    t8.update(amount=0, weight=0, isConfidential=True)
    answers = {**real_answers(), (2026, BY): dumps(dest), (2026, TOT): dumps(tot), (2023, BY): b"[]",
               (2023, TOT): b"[]"}
    res = run(answers)
    assert res["status"] == "partial", res
    assert any("months [10] after its newest month 2026-09" in w for w in res["warnings"]), res["warnings"]
    assert any("no honey export rows for 2023" in w for w in res["warnings"]), res["warnings"]
    with session_factory() as s:
        assert not _rows(s, T, period_label="2026-10")
        assert not _rows(s, T, partner_iso3="WLD", period_label="2026-08")
        us8 = _rows(s, T, partner_iso3="USA", period_label="2026-08")
        assert [t.value for t in us8] == [15_140_656.83]
        assert not [t for t in _rows(s, T) if t.period_label.startswith("2023")]
        assert set(_state(s)["years"]) == {"2026", "2025", "2024"}
    # The empty year is asked again at the next run, and only that year.
    res = run()
    assert queries(run.sent) == [(2023, BY), (2023, TOT)]
    assert res["status"] == "success", res
