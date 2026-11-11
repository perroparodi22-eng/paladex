"""Eurostat's annual selling price of honey per European country (collectors/prices_europe.py).

The fixture is the service's real answer of 11 Nov 2026 (dataset apri_ap_anouta, product 12920000).
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from paladex.collectors import prices_europe as pe
from paladex.collectors.base import CollectorError
from paladex.models import PriceObservation, Source

REAL = (Path(__file__).parent / "fixtures" / "eu" / "real_eurostat_apri_ap_anouta_honey.json").read_bytes()


def _rows(s, **filters):
    q = select(PriceObservation).join(Source).where(Source.key == "eurostat_honey_prices", PriceObservation.is_current)
    for k, v in filters.items():
        q = q.where(getattr(PriceObservation, k) == v)
    return s.scalars(q).all()


def test_real_answer_one_price_per_country_and_year_in_euro():
    rel = pe.parse_eurostat_honey_prices(REAL)
    assert rel.updated == "2025-05-15T11:00:00+0200"
    by = {(p.iso3, p.year): p for p in rel.points}
    assert {p.iso3 for p in rel.points} == {"AUT", "BGR", "CYP", "CZE", "DEU", "GRC", "ESP", "HRV", "HUN", "LTU", "LUX",
                                            "LVA", "POL", "PRT", "ROU", "SVN", "SVK"}
    assert by["DEU", 2024].eur_100kg == 1513.41 and by["DEU", 2024].geo == "DE"
    assert by["GRC", 2024].geo == "EL" and by["GRC", 2024].eur_100kg == 663.31          # Eurostat's code for Greece
    assert (by["HUN", 2024].eur_100kg, by["HUN", 2024].national_100kg) == (225.8, 89258.0)   # euro and forint
    assert by["LVA", 2024].status == "p"                                                # provisional, as flagged
    assert max(y for (c, y) in by if c == "CZE") == 2017 and max(y for (c, y) in by if c == "SVK") == 2008
    # Kosovo publishes one year in its own currency only: said, never converted by guess
    assert any(s.startswith("XK 2019") for s in rel.skipped)


def test_a_changed_product_label_or_a_broken_answer_stores_nothing():
    doc = json.loads(REAL)
    doc["dimension"]["prod_ani"]["category"]["label"]["12920000"] = "Honey - prices per 1 kg"
    with pytest.raises(CollectorError, match="per 100 kg"):
        pe.parse_eurostat_honey_prices(json.dumps(doc).encode())
    with pytest.raises(CollectorError, match="JSON-stat"):
        pe.parse_eurostat_honey_prices(b"<html>maintenance</html>")
    # a value that cannot be a price per 100 kg (the unit changed without the label) is left out
    doc = json.loads(REAL)
    first = next(iter(doc["value"]))
    doc["value"][first] = 9.5
    assert any("outside the plausible range" in s for s in pe.parse_eurostat_honey_prices(json.dumps(doc).encode()).skipped)


def test_end_to_end_producer_prices_per_kg_and_a_second_run_changes_nothing(run_with_routes, session_factory):
    routes = {pe.EUROSTAT_PRICE_URL: (200, REAL, "application/json")}
    res = run_with_routes("eurostat_honey_prices", routes)
    assert res["status"] == "success" and res["new"] > 300, res
    with session_factory() as s:
        de = _rows(s, origin_iso3="DEU", period_label="2024")[0]
        assert de.price_type == "producer" and (de.price_value, de.currency, de.unit) == (1513.41, "EUR", "100kg")
        assert de.price_per_kg == 15.1341 and de.eur_per_kg == 15.1341
        assert (de.market_iso3, de.frequency, de.period_start, de.period_end) == ("DEU", "A", date(2024, 1, 1), date(2024, 12, 31))
        assert de.data_status == "published" and de.reliability == "official" and de.raw_document_id
        # the link opens Eurostat's table for a person, not the JSON address
        assert de.source_url == pe.EUROSTAT_PRICE_PAGE and "databrowser" in de.source_url
        assert de.published_at == date(2025, 5, 15)
        assert "not a wholesale price" in de.notes and de.extra["national_currency_per_100kg"] == 1513.41
        assert _rows(s, origin_iso3="LVA", period_label="2024")[0].data_status == "provisional"
        assert _rows(s, origin_iso3="HUN", period_label="2024")[0].extra["national_currency_per_100kg"] == 89258.0
        assert len({r.origin_iso3 for r in _rows(s)}) == 17
        n = len(_rows(s))
    res2 = run_with_routes("eurostat_honey_prices", routes)
    assert res2["status"] == "no_change" and res2["new"] == 0, res2
    with session_factory() as s:
        assert len(_rows(s)) == n
