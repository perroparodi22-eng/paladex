"""Tests for collectors/trade_uk.py: United Kingdom honey imports and exports by partner (HMRC
Overseas Trade Statistics through the uktradeinfo API, `uk_hmrc_honey`).

The fixtures in tests/fixtures/trade_uk/ are REAL captures (2026-11-05, see the README there).
Variants (an earlier release, a new month, a revision, suppression, unmapped partners, schema drift)
are built from them here, in code.
"""
from __future__ import annotations

import copy
import json
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import func, select

from paladex.collectors import trade_uk as tu
from paladex.collectors.base import CollectorError
from paladex.enums import DataStatus, PriceType
from paladex.models import (
    AppSetting,
    FxRate,
    PriceObservation,
    RawDocument,
    Source,
    TradeFlowObservation,
)

FIX = Path(__file__).parent / "fixtures" / "trade_uk"
FILES = {
    "date": "real_hmrc_date_2026-11-05.json",
    "govuk": "real_govuk_ots_release_august-2026.json",
    "flowtype": "real_hmrc_flowtype.json",
    "commodity": "real_hmrc_commodity_0409.json",
    "country": "real_hmrc_country.json",
    "ots": "real_hmrc_ots_honey_202301-202608.json",
}
ROUTES = {"date": tu.DATE_URL, "govuk": tu.GOVUK_CONTENT_URL, "flowtype": tu.FLOWTYPE_URL,
          "commodity": tu.COMMODITY_URL, "country": tu.COUNTRY_URL, "ots": tu.OTS_URL}
T, P = TradeFlowObservation, PriceObservation
KEY = "uk_hmrc_honey"
N_REAL = 4063           # 2,401 trade rows + 1,662 unit values


def F(name: str) -> bytes:
    return (FIX / FILES.get(name, name)).read_bytes()


def J(name: str):
    return json.loads(F(name))


def dumps(doc) -> bytes:
    return json.dumps(doc, ensure_ascii=False).encode()


def ots_upto(month_id: int) -> dict:
    doc = J("ots")
    doc["value"] = [r for r in doc["value"] if r["MonthId"] <= month_id]
    return doc


def date_upto(month_id: int) -> bytes:
    doc = J("date")
    doc["value"] = [r for r in doc["value"] if r["MonthId"] <= month_id]
    return dumps(doc)


def govuk_for(month: str, year: int, published: str) -> bytes:
    doc = J("govuk")
    doc["title"] = f"UK overseas trade in goods statistics: {month} {year}"
    doc["first_published_at"] = published
    return dumps(doc)


# ---------------------------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------------------------


@pytest.fixture()
def run(db, monkeypatch):
    """Run the collector offline. `answers` overrides the real captures by name (bytes or
    (status, bytes)). The requests of the last run are in `run.sent`."""
    from paladex.collectors import base
    from paladex.collectors.runner import run_collector

    monkeypatch.setattr(base.time, "sleep", lambda *_: None)
    monkeypatch.setattr(tu, "today", lambda: date(2026, 11, 5))

    def _run(force: bool = False, **answers) -> dict:
        sent: list[httpx.Request] = []
        _run.sent = sent

        def handler(name):
            def reply(request):
                sent.append(request)
                spec = answers.get(name, F(name))
                if isinstance(spec, dict):
                    spec = dumps(spec)
                status, body = spec if isinstance(spec, tuple) else (200, spec)
                return httpx.Response(status, content=body, headers={"content-type": "application/json; charset=utf-8"})
            return reply

        with respx.mock(assert_all_called=False) as mock:
            for name, url in ROUTES.items():
                mock.route(method="GET", url__startswith=url).mock(side_effect=handler(name))
            mock.route().mock(side_effect=httpx.ConnectError("blocked in tests"))
            with httpx.Client(follow_redirects=True) as client:
                return run_collector(KEY, trigger="test", force=force, client=client)

    _run.sent = []
    return _run


def names(sent) -> list[str]:
    out = []
    for r in sent:
        url = str(r.url)
        out.append(next(n for n, u in ROUTES.items() if url.startswith(u)))
    return out


def _rows(s, model, *, current: bool | None = True, **where):
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
    from paladex.collectors.registry import COLLECTOR_MODULES, get_collector

    assert "paladex.collectors.trade_uk" in COLLECTOR_MODULES
    c = get_collector(KEY)
    assert c is not None and isinstance(c, tu.UkHmrcHoneyCollector)
    assert (c.reliability, c.category, c.country_iso3, c.kind, c.requires_key) == ("official", "trade", "GBR", "api", None)
    assert 0 < len(c.expected_update) < 120 and 0 < len(c.expected_update_en) < 120
    assert c.schedule == {"trigger": "cron", "day": "11-18", "day_of_week": "mon-fri", "hour": 11, "minute": 41}
    assert "Open Government Licence" in c.terms_note and "consignment" in c.terms_note
    assert "not market quotations" in c.terms_note


def test_parse_real_answers():
    months = tu.parse_dates(F("date"))
    assert months[0] == (2021, 1) and months[-1] == (2026, 8) and len(months) == 68
    tu.check_flow_types(F("flowtype"))
    com = tu.parse_commodities(F("commodity"))
    assert com == [tu.HmrcCommodity(4090000, "04090000", "Natural honey")]
    countries = tu.parse_countries(F("country"))
    assert len(countries) == 263 and countries[720] == tu.HmrcCountry(720, "CN", "China", "Asia and Oceania")
    parsed, nxt = tu.parse_ots(F("ots"), {4090000})
    assert nxt is None and parsed.problems == [] and parsed.bad == [] and len(parsed.rows) == 2313
    assert {r.suppression for r in parsed.rows} == {0}               # nothing suppressed in 2023-2026
    assert {r.month for r in parsed.rows} == {(y, m) for y in range(2023, 2027) for m in range(1, 13)
                                              if (y, m) <= (2026, 8)}
    imp24 = [r for r in parsed.rows if r.month[0] == 2024 and r.flow == "import"]
    assert (sum(r.net_mass for r in imp24), sum(r.value for r in imp24)) == (60_303_816.0, 97_023_258.0)
    assert tu.release_slug((2026, 8)) == "august-2026"
    assert tu.parse_govuk_release(F("govuk"), (2026, 8)) == date(2026, 10, 15)
    assert tu.parse_govuk_release(F("govuk"), (2026, 9)) is None    # another month's page is not this release
    p = tu.ots_params([4090000], (2023, 1), (2026, 8))["$apply"]
    assert p.startswith("filter((CommodityId eq 4090000) and MonthId ge 202301 and MonthId le 202608)/groupby(")


def test_parsers_fail_loudly_on_drift():
    rejected = b"Your request has been rejected. Please make sure you haven't exceeded the rate limit"
    with pytest.raises(CollectorError, match="rate limit or refused"):
        tu.parse_dates(rejected)
    doc = J("ots")
    for r in doc["value"]:
        r.pop("NetMass")
    with pytest.raises(CollectorError, match="schema drift.*NetMass"):
        tu.parse_ots(dumps(doc), {4090000})
    doc = J("ots")
    doc["value"][5]["CommodityId"] = 4070000
    with pytest.raises(CollectorError, match="ignored the commodity filter"):
        tu.parse_ots(dumps(doc), {4090000})
    doc = J("ots")
    doc["value"][5]["FlowTypeId"] = 7
    with pytest.raises(CollectorError, match="unknown FlowTypeId"):
        tu.parse_ots(dumps(doc), {4090000})
    ft = J("flowtype")
    ft["value"][0]["FlowTypeDescription"] = "All Imports"
    with pytest.raises(CollectorError, match="FlowType changed"):
        tu.check_flow_types(dumps(ft))
    com = J("commodity")
    com["value"][0]["Cn8LongDescription"] = "Royal jelly"
    with pytest.raises(CollectorError, match="unexpected honey line"):
        tu.parse_commodities(dumps(com))
    with pytest.raises(CollectorError, match="not valid JSON"):
        tu.parse_countries(b"{oops")


@pytest.mark.parametrize("alpha,name,area,expected", [
    ("FR", "France", "European Union", ("FRA", "iso2")),
    ("CN", "China", "Asia and Oceania", ("CHN", "iso2")),
    ("AE", "UAE", "Middle East and N Africa", ("ARE", "iso2")),
    ("XS", "Serbia", "Eastern Europe exc EU", ("SRB", "hmrc_code")),
    ("XK", "Kosovo", "Eastern Europe exc EU", ("XKX", "hmrc_code")),
    ("CD", "Congo (Dem. Rep)", "Sub-Saharan Africa", ("COD", "iso2")),
    ("QS", "Stores & Provis.", "Stores and Provisions", (None, "aggregate")),
    ("QV", "Estimates", "European Union", (None, "aggregate")),
    ("", "Confidential Country", "Confidential Region", (None, "aggregate")),
    ("", "Other Western Europe", "Western Europe exc EU", (None, "aggregate")),
    ("XC", "Ceuta", "Middle East and N Africa", (None, "aggregate")),
    ("DH", "Abu Dhabi", "Middle East and N Africa", (None, "unknown")),
    ("FR", "Germany", "European Union", (None, "conflict")),
])
def test_map_hmrc_country(alpha, name, area, expected):
    assert tu.map_hmrc_country(alpha, name, area) == expected


def test_status_rule():
    """Release notes: the August 2026 release revises 2026 only; the June 2026 release revised 2025 and 2026."""
    assert tu.hmrc_data_status(2026, (2026, 8)) == DataStatus.PROVISIONAL
    assert tu.hmrc_data_status(2025, (2026, 8)) == DataStatus.PUBLISHED
    assert tu.hmrc_data_status(2025, (2026, 7)) == DataStatus.PUBLISHED
    assert tu.hmrc_data_status(2025, (2026, 6)) == DataStatus.PROVISIONAL
    assert tu.hmrc_data_status(2025, (2026, 1)) == DataStatus.PROVISIONAL
    assert tu.hmrc_data_status(2024, (2026, 1)) == DataStatus.PUBLISHED
    assert tu.hmrc_data_status(2025, (2025, 12)) == DataStatus.PROVISIONAL
    assert tu.window_for((2026, 8)) == ((2023, 1), (2026, 8))


# ---------------------------------------------------------------------------------------------
# End to end on the real captures
# ---------------------------------------------------------------------------------------------


def test_real_backfill_end_to_end(run, session_factory):
    res = run()
    assert res["status"] == "success" and res["warnings"] == [], res
    assert res["new"] == N_REAL
    assert names(run.sent) == ["date", "govuk", "flowtype", "commodity", "country", "ots"]
    assert run.sent[0].url.params["$filter"] == "MonthId ge 202101"

    with session_factory() as s:
        trades = _rows(s, T)
        assert len(trades) == 2401 and len({t.partner_iso3 for t in trades}) == 99
        assert all((t.reporter_iso3, t.currency, t.frequency, t.hs_code, t.reliability) == ("GBR", "GBP", "M", "0409",
                                                                                           "official") for t in trades)
        assert {(t.flow, t.value_basis) for t in trades} == {("import", "CIF"), ("export", "FOB")}
        assert all(t.raw_document_id and t.source_url.startswith(tu.OTS_URL + "?") for t in trades)
        by = {(t.flow, t.partner_iso3, t.period_label): t for t in trades}

        nz = by[("import", "NZL", "2026-08")]
        assert (nz.value, nz.net_weight_kg, nz.unit_value_per_kg) == (2_071_920.0, 181_530.0, 11.4137)
        assert (nz.period_start, nz.period_end, nz.published_at) == (date(2026, 8, 1), date(2026, 8, 31), date(2026, 10, 15))
        assert nz.data_status == "provisional" and nz.usd_value is None          # no ECB rates in this test
        x = nz.extra
        assert (x["hmrc_country_id"], x["hmrc_code"], x["partner_name"], x["mapped_by"]) == (804, "NZ", "New Zealand", "iso2")
        assert x["hmrc_flow_types"] == ["Non-EU Imports"] and x["partner_basis"].startswith("country of consignment")
        assert x["cn8"] == "04090000" and x["cn8_lines"] is None and x["suppression_index"] == 0
        assert x["release"] == {"newest_month": "2026-08", "published": "2026-10-15",
                                "page": tu.GOVUK_PAGE_URL + "august-2026"}
        assert by[("export", "IRL", "2026-08")].extra["hmrc_flow_types"] == ["EU Exports"]
        assert by[("import", "SRB", "2023-10")].extra["mapped_by"] == "hmrc_code"           # HMRC code XS

        # The total (WLD) is the sum of every row, with HMRC's EU / non-EU split.
        w = by[("import", "WLD", "2026-08")]
        assert (w.value, w.net_weight_kg) == (11_283_353.0, 5_937_521.0)
        assert w.extra["eu"] == {"value_gbp": 2_973_343.0, "kg": 741_002.0}
        assert w.extra["non_eu"] == {"value_gbp": 8_310_010.0, "kg": 5_196_519.0}
        assert w.extra["partner_rows"] == 31 and w.extra["not_allocated"] is None
        we = by[("export", "WLD", "2026-08")]
        assert (we.value, we.net_weight_kg, we.extra["eu"]["kg"], we.extra["non_eu"]["kg"]) == (
            430_654.0, 97_143.0, 59_290.0, 37_853.0)
        for flow in ("import", "export"):
            for label in {t.period_label for t in trades}:
                parts = [t for t in trades if t.flow == flow and t.period_label == label and t.partner_iso3 != "WLD"]
                total = by[(flow, "WLD", label)]
                assert round(sum(t.net_weight_kg for t in parts), 3) == total.net_weight_kg
                assert round(sum(t.value for t in parts), 2) == total.value

        # Annual figures, cross-checked against UN Comtrade / FAOSTAT (see the README).
        def year(flow, y):
            ws = [t for t in trades if t.flow == flow and t.partner_iso3 == "WLD" and t.period_label.startswith(y)]
            assert len(ws) == 12
            return sum(t.net_weight_kg for t in ws), sum(t.value for t in ws)
        assert year("import", "2023") == (50_923_029.0, 89_875_372.0)        # Comtrade 50,969.4 t, FAOSTAT 50,927.2 t
        assert year("import", "2024") == (60_303_816.0, 97_023_258.0)        # Comtrade 60,306.6 t
        assert year("import", "2025") == (58_974_881.0, 98_914_122.0)        # Comtrade 58,977.7 t
        assert year("export", "2024") == (2_323_658.0, 11_197_164.0)         # FAOSTAT 2,324.2 t

        # Status and publication date: 2026 is open (provisional, release of 15 Oct 2026), 2023-2025 closed.
        assert {(t.period_label[:4], t.data_status, t.published_at) for t in trades} == {
            ("2026", "provisional", date(2026, 10, 15)), ("2025", "published", None),
            ("2024", "published", None), ("2023", "published", None)}

        prices = _rows(s, P)
        assert len(prices) == 1662
        assert {(p.price_type, p.terms) for p in prices} == {(PriceType.IMPORT_UNIT_VALUE, "CIF"),
                                                             (PriceType.EXPORT_UNIT_VALUE, "FOB")}
        assert all(p.currency == "GBP" and p.unit == "kg" and p.variety == "unspecified" for p in prices)
        assert all(p.volume_kg >= tu.MIN_UNIT_VALUE_WEIGHT_KG for p in prices)
        assert not [p for p in prices if "WLD" in (p.origin_iso3, p.market_iso3)]
        assert all((p.market_iso3 == "GBR") == (p.price_type == PriceType.IMPORT_UNIT_VALUE) for p in prices)
        cn = _rows(s, P, origin_iso3="CHN", period_label="2026-08")[0]
        assert (cn.price_type, cn.market_iso3, cn.price_value, cn.volume_kg) == (
            PriceType.IMPORT_UNIT_VALUE, "GBR", 0.7784, 3_542_032.0)
        assert (cn.origin_label, cn.market_location, cn.published_at) == ("China", "United Kingdom", date(2026, 10, 15))
        ie = _rows(s, P, market_iso3="IRL", period_label="2026-08")[0]
        assert (ie.price_type, ie.origin_iso3, ie.price_value) == (PriceType.EXPORT_UNIT_VALUE, "GBR", 4.3761)
        # Small lots get a trade row but no unit value.
        small = by[("export", "JPN", "2026-08")]
        assert (small.value, small.net_weight_kg) == (5_642.0, 908.0)
        assert not _rows(s, P, market_iso3="JPN", period_label="2026-08", current=None)

        assert len(_rows(s, RawDocument, current=None)) == 6
        st = _state(s)
        assert (st["latest_month"], st["window_start"], st["parser"]) == ("2026-08", "2023-01", tu.PARSER_VERSION)
        assert st["release"]["published"] == "2026-10-15"
        src = s.scalars(select(Source).where(Source.key == KEY)).one()
        assert (src.latest_published_at, src.latest_period_label) == (date(2026, 10, 15), "2026-08")
        _no_duplicate_current(s)


def test_same_release_is_one_request_and_forced_rerun_is_idempotent(run, session_factory):
    assert run()["status"] == "success"
    res = run()
    assert res["status"] == "no_change" and res["seen"] == 0, res
    assert names(run.sent) == ["date"]
    res = run(force=True)
    assert res["status"] == "no_change" and (res["new"], res["revised"], res["seen"]) == (0, 0, N_REAL), res
    assert names(run.sent) == ["date", "flowtype", "commodity", "country", "ots"]   # release date kept in state
    with session_factory() as s:
        assert len(_rows(s, T, current=None)) == 2401 and len(_rows(s, P, current=None)) == 1662
        assert len(_rows(s, RawDocument, current=None)) == 6       # identical bytes are not archived twice
        _no_duplicate_current(s)


def test_new_release_adds_months_closes_the_previous_year_and_keeps_revisions(run, session_factory):
    """First the June 2026 release (2025 still open), then the real August one: 2025 becomes final (a
    revision of every 2025 row), July and August are new, and a revised and a vanished row are handled."""
    june = ots_upto(202606)
    res = run(date=date_upto(202606), ots=june,
              govuk=govuk_for("June", 2026, "2026-08-13T09:30:01+01:00"))
    assert res["status"] == "success" and res["warnings"] == [], res
    assert run.sent[1].url.path.endswith("-june-2026")
    with session_factory() as s:
        t25 = _rows(s, T, period_label="2025-12", flow="import", partner_iso3="WLD")[0]
        assert (t25.data_status, t25.published_at) == ("provisional", date(2026, 8, 13))
        n25 = sum(1 for t in _rows(s, T) if t.period_label.startswith("2025"))
        p25 = sum(1 for p in _rows(s, P) if p.period_label.startswith("2025"))
        assert (n25, p25) == (681, 461)

    # The real release, with China's August imports revised and Ireland's August imports gone.
    aug = J("ots")
    cn = next(r for r in aug["value"] if (r["MonthId"], r["FlowTypeId"], r["CountryId"]) == (202606, 3, 720))
    cn["Value"] += 1000.0
    aug["value"] = [r for r in aug["value"] if (r["MonthId"], r["FlowTypeId"], r["CountryId"]) != (202605, 1, 7)]
    res = run(ots=aug)
    # 681 + 461 rows of 2025 become final; China June (trade, price) and the June / May totals revised;
    # Ireland May withdrawn (trade, price). The withdrawal is reported, so the run is "partial".
    assert res["status"] == "partial" and (res["new"], res["revised"]) == (186, 1148), res
    assert run.sent[1].url.path.endswith("-august-2026")
    assert any("no longer shows UK honey imports for IRL 2026-05" in w for w in res["warnings"]), res["warnings"]
    with session_factory() as s:
        hist = _rows(s, T, current=None, period_label="2025-12", flow="import", partner_iso3="WLD")
        assert [(t.data_status, t.is_current, t.published_at) for t in hist] == [
            ("provisional", False, date(2026, 8, 13)), ("published", True, None)]
        assert sum(1 for t in _rows(s, T) if t.period_label.startswith("2025") and t.data_status == "published") == 681
        cn6 = _rows(s, T, current=None, period_label="2026-06", flow="import", partner_iso3="CHN")
        assert [t.is_current for t in cn6] == [False, True] and cn6[1].value - cn6[0].value == 1000.0
        assert cn6[1].published_at == date(2026, 10, 15)
        gone = _rows(s, T, current=None, period_label="2026-05", flow="import", partner_iso3="IRL")
        assert [t.is_current for t in gone] == [False]                  # withdrawn, kept in the history
        assert _rows(s, P, current=False, period_label="2026-05", origin_iso3="IRL")    # its unit value too
        assert _rows(s, T, period_label="2026-08", flow="import", partner_iso3="WLD")
        assert _state(s)["latest_month"] == "2026-08"
        _no_duplicate_current(s)


def test_suppression_unmapped_and_unusable_rows(run, session_factory):
    doc = J("ots")
    rows = doc["value"]
    nz = next(r for r in rows if (r["MonthId"], r["FlowTypeId"], r["CountryId"]) == (202608, 3, 804))
    nz["SuppressionIndex"] = 4                                # quantity suppressed for countries and ports
    base = next(r for r in rows if (r["MonthId"], r["FlowTypeId"]) == (202607, 3))
    rows.append({**copy.deepcopy(base), "CountryId": 977, "Value": 5000.0, "NetMass": 2000.0})   # confidential
    rows.append({**copy.deepcopy(base), "CountryId": 914, "Value": 7000.0, "NetMass": 3000.0})   # Abu Dhabi (legacy)
    bad = next(r for r in rows if (r["MonthId"], r["FlowTypeId"]) == (202606, 4))
    bad["Value"] = -12.0
    res = run(ots=doc)
    assert res["status"] == "partial", res
    w = " | ".join(res["warnings"])
    assert "suppression index 4" in w and "Confidential Country" in w and "Abu Dhabi" in w
    assert "unusable value=-12.0" in w and "2026-06 include an unusable row" in w
    with session_factory() as s:
        nz8 = _rows(s, T, period_label="2026-08", flow="import", partner_iso3="NZL")[0]
        assert (nz8.value, nz8.net_weight_kg, nz8.unit_value_per_kg) == (2_071_920.0, None, None)
        assert nz8.extra["suppression_index"] == 4
        assert not _rows(s, P, period_label="2026-08", origin_iso3="NZL")       # no weight, no unit value
        w8 = _rows(s, T, period_label="2026-08", flow="import", partner_iso3="WLD")[0]
        assert (w8.value, w8.net_weight_kg) == (11_283_353.0, None)            # a partial weight is never a total
        w7 = _rows(s, T, period_label="2026-07", flow="import", partner_iso3="WLD")[0]
        na = {d["hmrc_country_id"]: d for d in w7.extra["not_allocated"]}
        assert set(na) == {977, 914} and na[977]["why"] == "aggregate" and na[914]["why"] == "unknown"
        parts = [t for t in _rows(s, T, period_label="2026-07", flow="import") if t.partner_iso3 != "WLD"]
        assert w7.net_weight_kg == round(sum(t.net_weight_kg for t in parts) + 5000.0, 3)
        assert not _rows(s, T, period_label="2026-06", flow="export", partner_iso3="WLD")   # partial: not stored
        assert _rows(s, T, period_label="2026-06", flow="import", partner_iso3="WLD")
        assert _state(s)["unknown_partners"] == {"914": {"code": "DH", "name": "Abu Dhabi", "how": "unknown"}}


def test_failures_store_nothing(run, session_factory):
    res = run(ots=(403, b"Your request has been rejected. Please make sure you haven't exceeded the rate limit"))
    assert res["status"] == "failed" and "403" in res["error"], res
    doc = J("ots")
    for r in doc["value"]:
        r.pop("SuppressionIndex")
    res = run(ots=doc)
    assert res["status"] == "failed" and "schema drift" in res["error"], res
    res = run(date=b'{"value": []}')
    assert res["status"] == "failed" and "no readable month" in res["error"], res
    with session_factory() as s:
        assert _rows(s, T, current=None) == [] and _rows(s, P, current=None) == []
        assert _state(s).get("latest_month") is None
    # A release page that cannot be read is not fatal: open periods are stored without publication date.
    res = run(govuk=(404, b'{"error": "not found"}'))
    assert res["status"] == "partial" and "No GOV.UK release page" in res["warnings"][0], res
    with session_factory() as s:
        assert {t.published_at for t in _rows(s, T)} == {None}


def test_rows_of_the_newest_month_not_loaded_yet_are_asked_again(run, session_factory):
    res = run(ots=ots_upto(202607))
    assert res["status"] == "partial" and "publishes no honey row for it yet" in res["warnings"][0], res
    with session_factory() as s:
        assert _state(s)["latest_month"] == "2026-07"
    res = run()
    assert res["status"] == "success" and "ots" in names(run.sent), res
    with session_factory() as s:
        assert _state(s)["latest_month"] == "2026-08"
        assert _rows(s, T, period_label="2026-08", flow="export", partner_iso3="WLD")


def test_gbp_is_converted_with_ecb_rates(run, db, session_factory):
    d = date(2026, 8, 1)
    while d <= date(2026, 8, 31):
        if d.weekday() < 5:
            db.add(FxRate(rate_date=d, currency="USD", per_eur=1.17, source_key="ecb_fx"))
            db.add(FxRate(rate_date=d, currency="GBP", per_eur=0.86, source_key="ecb_fx"))
        d += timedelta(days=1)
    db.commit()
    assert run()["status"] == "success"
    with session_factory() as s:
        w = _rows(s, T, period_label="2026-08", flow="import", partner_iso3="WLD")[0]
        assert w.usd_value == pytest.approx(11_283_353.0 * 1.17 / 0.86, abs=0.02)
        assert w.eur_value == pytest.approx(11_283_353.0 / 0.86, abs=0.02)
        assert (w.fx_basis, w.fx_start, w.fx_end) == ("period_avg", date(2026, 8, 1), date(2026, 8, 31))
        cn = _rows(s, P, origin_iso3="CHN", period_label="2026-08")[0]
        assert cn.usd_per_kg == pytest.approx(0.7784 * 1.17 / 0.86, abs=1e-4)
        assert cn.eur_per_kg == pytest.approx(0.7784 / 0.86, abs=1e-4)
        assert _rows(s, T, period_label="2026-07", flow="import", partner_iso3="WLD")[0].usd_value is None  # no rates


def test_api_prefers_hmrc_over_comtrade_for_a_complete_year(run, db, api):
    """GBR's own official statistics come first for a complete year (Ctx.is_national: country GBR,
    official); UN Comtrade's annual figure stays listed as an alternative."""
    assert run()["status"] == "success"
    comtrade = Source(key="un_comtrade_t", name="Comtrade", publisher="UN", homepage="https://example.org",
                      kind="api", reliability="official", category="trade", expected_max_age_days=400)
    db.add(comtrade)
    db.flush()
    db.add(T(source_id=comtrade.id, series_key="ct|GBR|WLD|2025", reporter_iso3="GBR", partner_iso3="WLD",
             flow="import", currency="USD", value=130_247_218.0, usd_value=130_247_218.0, net_weight_kg=58_977_700.0,
             period_start=date(2025, 1, 1), period_end=date(2025, 12, 31), period_label="2025", frequency="A",
             data_status="published", reliability="official", value_hash="x"))
    db.commit()
    r = api.get("/api/trade/flows", params={"reporter": "GBR", "flow": "import", "year": 2025}).json()
    assert r["source_key"] == KEY and r["total"]["net_weight_kg"] == 58_974_881.0 and r["complete"] is True
    assert {a["source"]["key"] for a in r["alternatives"]} == {KEY, "un_comtrade_t"}
    assert r["rows"][0]["iso3"] == "CHN"
    leaders = api.get("/api/trade/leaders", params={"flow": "import", "year": 2025}).json()
    gbr = next(x for x in leaders["rows"] if x["iso3"] == "GBR")
    assert gbr["source"]["key"] == KEY and gbr["net_weight_kg"] == 58_974_881.0
    profile = api.get("/api/countries/GBR").json()
    assert profile["trade"]["import"]["latest"]["source"]["key"] == KEY
