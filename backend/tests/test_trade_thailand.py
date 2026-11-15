"""Thailand's official honey trade by partner, monthly (collectors/trade_thailand.py).

The fixtures are the Thai Customs pages as answered on 15 Nov 2026 (statistic code 04090000000).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from paladex.collectors import trade_thailand as th
from paladex.collectors.base import CollectorError
from paladex.models import PriceObservation, Source, TradeFlowObservation

FIX = Path(__file__).parent / "fixtures" / "trade_thailand"
EXP_DEC25 = (FIX / "real_export_2025_12.html").read_bytes()
EXP_SEP26 = (FIX / "real_export_2026_09.html").read_bytes()
IMP_SEP26 = (FIX / "real_import_2026_09.html").read_bytes()


def test_real_pages_month_figures_total_and_latest_month():
    p = th.parse_th_customs(EXP_SEP26, "export", 2026, 9)
    assert (p.basis, p.total_kg, p.total_value) == ("FOB", 1_364_646.0, 104_334_872.0)
    assert p.latest_released == (2026, 9)
    us = next(r for r in p.rows if r.code == "US")
    assert (us.name, us.kg, us.value) == ("UNITED STATES", 301_901.0, 20_287_710.0)      # the month, not the cumulative column
    assert abs(sum(r.kg for r in p.rows) - p.total_kg) <= 1
    imp = th.parse_th_customs(IMP_SEP26, "import", 2026, 9)
    assert (imp.basis, imp.total_kg, imp.total_value) == ("CIF", 51_497.0, 4_728_903.0)
    dec = th.parse_th_customs(EXP_DEC25, "export", 2025, 12)
    assert dec.total_kg == 754_606.0 and next(r for r in dec.rows if r.code == "AU").kg == 0   # traded earlier in the year only


def test_a_page_that_is_not_the_one_asked_for_stores_nothing():
    with pytest.raises(CollectorError, match="asked export 2026-09"):
        th.parse_th_customs(EXP_DEC25, "export", 2026, 9)              # another month
    with pytest.raises(CollectorError, match="CIF"):
        th.parse_th_customs(IMP_SEP26, "export", 2026, 9)              # import values are CIF, not FOB
    with pytest.raises(CollectorError, match="kilograms"):
        th.parse_th_customs(EXP_SEP26.replace(b"(KGM)", b"(C62)"), "export", 2026, 9)
    with pytest.raises(CollectorError, match="no table"):
        th.parse_th_customs(b"<html>maintenance</html>", "export", 2026, 9)
    assert th.parse_latest_released("<td>Latest released</td><td>September 2026</td>") == (2026, 9)
    assert th.parse_latest_released("nothing here") is None
    # the link shown to the reader opens the same table
    assert th.th_page_url("export", 2025, 12).startswith("https://www.customs.go.th/statistic_report.php?lang=en&")
    assert "tariff_code=04090000000" in th.th_page_url("export", 2025, 12) and "month=12&year=2025" in th.th_page_url("export", 2025, 12)


def test_end_to_end_partners_world_total_and_unit_values(run_with_routes, session_factory, monkeypatch):
    monkeypatch.setattr(th, "_months_between", lambda start, end: [end])       # one month instead of the back-fill
    base = r"^https://www\.customs\.go\.th/statistic_report\.php\?"
    routes = {
        base + r"lang=en&show_search=1$": EXP_SEP26,                           # the probe: "Latest released September 2026"
        base + r".*imex_type=export.*month=9&year=2026$": EXP_SEP26,
        base + r".*imex_type=import.*month=9&year=2026$": IMP_SEP26,
    }
    res = run_with_routes("th_customs_honey", routes)
    assert res["status"] == "success" and not res["warnings"], res
    with session_factory() as s:
        rows = s.scalars(select(TradeFlowObservation).join(Source).where(Source.key == "th_customs_honey")).all()
        world = {r.flow: r for r in rows if r.partner_iso3 == "WLD"}
        assert (world["export"].net_weight_kg, world["export"].value, world["export"].currency) == (1_364_646.0, 104_334_872.0, "THB")
        assert (world["import"].net_weight_kg, world["import"].value_basis) == (51_497.0, "CIF")
        us = next(r for r in rows if r.flow == "export" and r.partner_iso3 == "USA")
        assert (us.reporter_iso3, us.net_weight_kg, us.value, us.value_basis) == ("THA", 301_901.0, 20_287_710.0, "FOB")
        assert (us.period_label, us.frequency, us.period_start, us.period_end) == ("2026-09", "M", date(2026, 9, 1), date(2026, 9, 30))
        assert us.reliability == "official" and us.source_url == th.th_page_url("export", 2026, 9) and us.raw_document_id
        # a country listed for earlier months of the year only has no row for this month
        assert all(r.net_weight_kg or r.value for r in rows)
        assert not any(r.partner_iso3 == "ARG" for r in rows if r.flow == "import")     # Argentina: 0 in September
        prices = s.scalars(select(PriceObservation).join(Source).where(Source.key == "th_customs_honey")).all()
        usp = next(p for p in prices if p.market_iso3 == "USA")
        assert usp.price_type == "export_unit_value" and usp.origin_iso3 == "THA"
        assert usp.price_value == round(20_287_710 / 301_901, 4) and (usp.currency, usp.unit) == ("THB", "kg")
        assert all(p.volume_kg >= th.MIN_UNIT_VALUE_WEIGHT_KG for p in prices)            # a parcel is not a price
        n = len(rows), len(prices)
    monkeypatch.setattr(th, "_months_between", lambda start, end: [end])
    res2 = run_with_routes("th_customs_honey", routes)
    assert res2["status"] == "no_change" and res2["new"] == 0, res2
    with session_factory() as s:
        assert len(s.scalars(select(TradeFlowObservation).join(Source).where(Source.key == "th_customs_honey")).all()) == n[0]


def test_months_read_first_run_from_two_januaries_back_then_the_last_few():
    assert th._months_between((2026, 6), (2026, 9)) == [(2026, 6), (2026, 7), (2026, 8), (2026, 9)]
    assert th._months_between((2025, 11), (2026, 2)) == [(2025, 11), (2025, 12), (2026, 1), (2026, 2)]
    assert th._shift((2026, 2), -3) == (2025, 11) and th._shift((2026, 9), -(th.TH_REPULL_MONTHS - 1)) == (2026, 6)
