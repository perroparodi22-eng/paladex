"""Tests for the EU collectors (paladex/collectors/eu.py).

All fixtures in tests/fixtures/eu/ are RECONSTRUCTED from documentation (see the README
there); the numbers are illustrative.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select

from paladex.collectors import eu
from paladex.enums import PriceType
from paladex.models import PriceObservation, RawDocument, RegulationItem, Report, Source, TradeFlowObservation

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_bytes(rel: str) -> bytes:
    return (FIXTURES / rel).read_bytes()

COMEXT_ANY = eu.COMEXT_URL
COMEXT_MAIN = r"^https://ec\.europa\.eu/eurostat/api/comext/dissemination/statistics/1\.0/data/DS-045409\?.*QUANTITY_IN_100KG"
TAXUD_IMPORT_2026 = r"^https://api\.tech\.ec\.europa\.eu/agrifood/api/taxud/weeklyData/import\?.*marketingYears=2026"
RASFF = ("POST", eu.RASFF_SEARCH_URL)


@pytest.fixture()
def pin_today(monkeypatch):
    def _pin(d: date):
        monkeypatch.setattr(eu, "today", lambda: d)
    _pin(date(2026, 11, 2))
    return _pin


def _rows(s, model, key: str, **filters):
    src = s.scalars(select(Source).where(Source.key == key)).one()
    q = select(model).where(model.source_id == src.id)
    for k, v in filters.items():
        q = q.where(getattr(model, k) == v)
    return s.scalars(q.order_by(model.id)).all()


# ---------------------------------------------------------------------------
# JSON-stat decoder
# ---------------------------------------------------------------------------


def _toy_jsonstat(**over):
    doc = {
        "version": "2.0", "class": "dataset",
        "id": ["a", "b", "c"], "size": [2, 3, 2],
        "dimension": {
            "a": {"category": {"index": {"X": 0, "Y": 1}}},
            # keys deliberately NOT in position order: positions must come from the index values
            "b": {"category": {"index": {"r3": 2, "r1": 0, "r2": 1}, "label": {"r1": "One", "r2": "Two", "r3": "Three"}}},
            "c": {"category": {"index": ["c0", "c1"]}},             # list form is valid JSON-stat too
        },
        "value": {"11": 9.0, "0": 1, "7": 5},
    }
    doc.update(over)
    return doc


def test_jsonstat_sparse_values_use_strides_and_category_index():
    ds = eu.decode_jsonstat(_toy_jsonstat())
    got = {tuple(c.coords[d] for d in ("a", "b", "c")): c.value for c in ds.cells}
    # flat = a*6 + b*2 + c: 0 -> (X,r1,c0); 7 -> (Y,r1,c1); 11 -> (Y,r3,c1)
    assert got == {("X", "r1", "c0"): 1, ("Y", "r1", "c1"): 5, ("Y", "r3", "c1"): 9.0}
    assert ds.categories["b"] == ["r1", "r2", "r3"]
    assert ds.labels["b"]["r3"] == "Three"
    assert len(ds.cells) == 3                       # missing cells are absent, never zero


def test_jsonstat_dense_values_status_and_single_category_without_index():
    doc = _toy_jsonstat(value=[None] * 11 + [4.5], status={"11": "p"})
    doc["dimension"]["a"] = {"category": {"index": {"X": 0, "Y": 1}}}
    ds = eu.decode_jsonstat(doc)
    assert [(c.coords, c.value, c.status) for c in ds.cells] == [({"a": "Y", "b": "r3", "c": "c1"}, 4.5, "p")]
    single = {"id": ["f"], "size": [1], "dimension": {"f": {"category": {"label": {"M": "Monthly"}}}}, "value": {"0": 3}}
    assert eu.decode_jsonstat(single).cells[0].coords == {"f": "M"}


@pytest.mark.parametrize("bad", [
    {"value": {"12": 1}},                                              # outside the cube (2*3*2 = 12 cells)
    {"value": {"x": 1}},                                               # non-integer key
    {"value": [1, 2, 3]},                                              # dense list of the wrong length
    {"size": [2, 3]},                                                  # id / size mismatch
    {"dimension": {"a": {"category": {"index": {"X": 0, "Y": 5}}},     # position out of range
                   "b": {"category": {"index": ["r1", "r2", "r3"]}}, "c": {"category": {"index": ["c0", "c1"]}}}},
])
def test_jsonstat_rejects_malformed_documents(bad):
    with pytest.raises(eu.JsonStatError):
        eu.decode_jsonstat(_toy_jsonstat(**bad))


# ---------------------------------------------------------------------------
# Eurostat Comext
# ---------------------------------------------------------------------------


def test_geo_mapping_including_serbia_xs():
    assert eu.map_geo("XS") == "SRB"           # Comext geonomenclature: Serbia is XS, not RS
    assert eu.map_geo("RS") == "SRB"
    assert eu.map_geo("EL") == "GRC" and eu.map_geo("GR") == "GRC"
    assert eu.map_geo("EU27_2020") == "EU27"
    assert eu.map_geo("EXT_EU27_2020") == "EXTRA_EU"
    assert eu.map_geo("WORLD") == "WLD"
    assert eu.map_geo("QW") is None and eu.map_geo("") is None


def test_parse_comext_drops_empty_months_and_reads_vintage():
    rel = eu.parse_comext(fixture_bytes("eu/comext_honey_2026-10-16.json"))
    assert rel.updated_raw == "2026-10-16T11:00:00+0200"
    assert rel.dropped_periods == ["2026-09", "2026-10"]
    assert {r.period for r in rel.records} == {f"2026-{m:02d}" for m in range(3, 9)}
    serbia = [r for r in rel.records if r.reporter == "EU27_2020" and r.partner == "XS" and r.period == "2026-08"]
    assert len(serbia) == 1 and serbia[0].quantity_100kg == 900 and serbia[0].partner_label == "Serbia"
    # the sparse hole stays a hole
    assert not [r for r in rel.records if (r.reporter, r.partner, r.flow, r.period) == ("IT", "XS", "1", "2026-04")]
    assert rel.problems == []


def test_comext_data_status_follows_revision_window():
    assert eu.comext_data_status(2026, date(2026, 10, 16)) == "provisional"
    assert eu.comext_data_status(2025, date(2026, 9, 15)) == "provisional"     # revised until ~October Y+1
    assert eu.comext_data_status(2025, date(2026, 10, 16)) == "published"
    assert eu.comext_data_status(2024, date(2026, 10, 16), {"VALUE_IN_EUROS": "p"}) == "provisional"


def test_comext_end_to_end_unit_values_and_cheap_check(run_with_routes, session_factory, pin_today):
    routes = {COMEXT_MAIN: fixture_bytes("eu/comext_honey_2026-10-16.json"),
              COMEXT_ANY: fixture_bytes("eu/comext_probe_2026-10-16.json")}
    res = run_with_routes("eurostat_comext", routes)
    assert res["status"] == "success", res
    with session_factory() as s:
        trades = _rows(s, TradeFlowObservation, "eurostat_comext")
        assert trades and all(t.currency == "EUR" and t.frequency == "M" for t in trades)
        assert not [t for t in trades if t.period_label in ("2026-09", "2026-10")]      # empty months dropped
        srb = [t for t in trades if (t.reporter_iso3, t.partner_iso3, t.flow, t.period_label) == ("EU27", "SRB", "import", "2026-08")]
        assert len(srb) == 1 and srb[0].net_weight_kg == 90_000 and srb[0].value == 486_000
        assert srb[0].value_basis == "CIF" and srb[0].published_at == date(2026, 10, 16)
        assert srb[0].data_status == "provisional" and srb[0].reliability == "official"
        assert srb[0].source_url.startswith(eu.COMEXT_URL) and srb[0].raw_document_id
        assert srb[0].extra["partner_code"] == "XS"
        assert {t.partner_iso3 for t in trades} == {"ARG", "CHN", "EXTRA_EU", "UKR", "WLD", "SRB"}
        assert {t.reporter_iso3 for t in trades} == {"DEU", "EU27", "ITA"}
        exports = [t for t in trades if t.flow == "export"]
        assert exports and all(t.value_basis == "FOB" for t in exports)
        # value published without quantity: trade row kept, weight unknown
        de_xs = [t for t in exports if t.reporter_iso3 == "DEU" and t.partner_iso3 == "SRB"]
        assert de_xs and all(t.net_weight_kg is None and t.unit_value_per_kg is None for t in de_xs)

        prices = _rows(s, PriceObservation, "eurostat_comext")
        imp = [p for p in prices if p.price_type == PriceType.IMPORT_UNIT_VALUE]
        cn = [p for p in imp if (p.market_iso3, p.origin_iso3, p.period_label) == ("EU27", "CHN", "2026-08")]
        assert len(cn) == 1 and cn[0].price_value == 1.85 and cn[0].unit == "kg" and cn[0].currency == "EUR"
        assert cn[0].variety == "unspecified" and cn[0].terms == "CIF" and cn[0].volume_kg == 5_000_000
        assert cn[0].eur_per_kg == 1.85 and cn[0].data_status == "provisional"
        assert [p.price_value for p in imp if (p.market_iso3, p.origin_iso3, p.period_label) == ("EU27", "SRB", "2026-08")] == [5.4]
        # tiny flow (IT from Serbia, 400 kg): trade row stored, no unit value derived
        assert [t for t in trades if (t.reporter_iso3, t.partner_iso3, t.period_label) == ("ITA", "SRB", "2026-08")]
        assert not [p for p in imp if (p.market_iso3, p.origin_iso3, p.period_label) == ("ITA", "SRB", "2026-08")]
        assert all(p.volume_kg >= eu.MIN_UNIT_VALUE_WEIGHT_KG for p in prices)
        # WORLD mixes intra-EU consignments: never a "price by origin"
        assert not [p for p in prices if "WLD" in (p.origin_iso3, p.market_iso3)]
        assert {p.origin_iso3 for p in imp} >= {"EXTRA_EU", "CHN", "UKR", "ARG", "SRB"}
        exp = [p for p in prices if p.price_type == PriceType.EXPORT_UNIT_VALUE]
        assert exp and all(p.terms == "FOB" for p in exp)
        assert {(p.origin_iso3, p.market_iso3) for p in exp} >= {("EU27", "EXTRA_EU"), ("ITA", "EXTRA_EU")}
        assert not {PriceType.WHOLESALE_BULK, PriceType.PRODUCER} & {p.price_type for p in prices}
        n_trades, n_prices = len(trades), len(prices)

    # Second run: the cheap probe shows the same vintage -> nothing pulled, nothing duplicated.
    res2 = run_with_routes("eurostat_comext", routes)
    assert res2["status"] == "no_change", res2
    # A forced re-pull of identical data adds nothing either.
    res3 = run_with_routes("eurostat_comext", routes, force=True)
    assert res3["status"] == "no_change" and res3["new"] == 0 and res3["revised"] == 0, res3
    with session_factory() as s:
        assert len(_rows(s, TradeFlowObservation, "eurostat_comext")) == n_trades
        assert len(_rows(s, PriceObservation, "eurostat_comext")) == n_prices


def test_comext_new_vintage_is_repulled_and_revisions_are_kept(run_with_routes, session_factory, pin_today):
    run_with_routes("eurostat_comext", {COMEXT_MAIN: fixture_bytes("eu/comext_honey_2026-10-16.json"),
                                        COMEXT_ANY: fixture_bytes("eu/comext_probe_2026-10-16.json")})
    pin_today(date(2026, 11, 20))
    res = run_with_routes("eurostat_comext", {COMEXT_MAIN: fixture_bytes("eu/comext_honey_2026-11-13.json"),
                                              COMEXT_ANY: fixture_bytes("eu/comext_probe_2026-11-13.json")})
    assert res["status"] == "success" and res["revised"] >= 2 and res["new"] > 0, res
    with session_factory() as s:
        hist = _rows(s, PriceObservation, "eurostat_comext", price_type="import_unit_value", market_iso3="EU27",
                     origin_iso3="CHN", period_label="2026-08")
        assert [(p.price_value, p.revision, p.is_current) for p in hist] == [(1.85, 1, False), (1.9, 2, True)]
        assert hist[1].supersedes_id == hist[0].id and hist[1].published_at == date(2026, 11, 13)
        trade = _rows(s, TradeFlowObservation, "eurostat_comext", reporter_iso3="EU27", partner_iso3="CHN",
                      flow="import", period_label="2026-08")
        assert [(t.value, t.is_current) for t in trade] == [(9_250_000, False), (9_500_000, True)]
        # the new month arrived; the still-empty ones did not
        labels = {t.period_label for t in _rows(s, TradeFlowObservation, "eurostat_comext")}
        assert "2026-09" in labels and "2026-10" not in labels
        # exactly one current row per series
        dup = s.execute(select(TradeFlowObservation.series_key, func.count()).where(TradeFlowObservation.is_current.is_(True))
                        .group_by(TradeFlowObservation.series_key).having(func.count() > 1)).all()
        assert dup == []


def test_comext_schema_drift_fails_loudly(run_with_routes, session_factory, pin_today):
    doc = json.loads(fixture_bytes("eu/comext_honey_2026-10-16.json"))
    ind = doc["dimension"]["indicators"]["category"]
    ind["index"], ind["label"] = {"VALUE_IN_EUROS": 0, "NET_MASS_KG": 1}, {"VALUE_IN_EUROS": "v", "NET_MASS_KG": "q"}
    res = run_with_routes("eurostat_comext", {COMEXT_MAIN: json.dumps(doc).encode()})
    assert res["status"] == "failed" and "QUANTITY_IN_100KG" in res["error"], res
    doc2 = json.loads(fixture_bytes("eu/comext_honey_2026-10-16.json"))
    doc2["id"] = [d for d in doc2["id"] if d != "flow"]
    res2 = run_with_routes("eurostat_comext", {COMEXT_MAIN: json.dumps(doc2).encode()})
    assert res2["status"] == "failed" and "flow" in res2["error"], res2
    with session_factory() as s:
        assert _rows(s, TradeFlowObservation, "eurostat_comext") == []


def test_comext_retries_without_world_when_rejected(run_with_routes, session_factory, pin_today):
    err = json.dumps({"error": {"status": 400, "id": 100, "label": "Invalid category WORLD for dimension partner"}}).encode()
    res = run_with_routes("eurostat_comext", {
        r"^https://ec\.europa\.eu/eurostat/.*partner=WORLD": (400, err),
        COMEXT_MAIN: fixture_bytes("eu/comext_honey_2026-10-16.json"),
    })
    assert res["status"] == "success", res
    with session_factory() as s:
        urls = [d.url for d in _rows(s, RawDocument, "eurostat_comext") if d.url and "QUANTITY" in d.url]
        assert urls and any("WORLD" not in u for u in urls)


# ---------------------------------------------------------------------------
# TAXUD weekly surveillance
# ---------------------------------------------------------------------------


def _taxud_routes(import_body: bytes | None = None, sectors: bytes | None = None, docs: bytes | None = None):
    return {
        eu.TAXUD_SECTORS_URL: sectors or fixture_bytes("eu/taxud_sectors.json"),
        eu.TAXUD_OPENAPI_URL: docs or fixture_bytes("eu/taxud_api_docs.json"),
        TAXUD_IMPORT_2026: import_body or fixture_bytes("eu/taxud_import_honey_2026.json"),
        eu.TAXUD_IMPORT_URL: (404, b'{"message":"No results found"}', "application/json"),
    }


def test_parse_taxud_aggregates_dedups_and_flags_conflicts():
    parsed = eu.parse_taxud_weekly(fixture_bytes("eu/taxud_import_honey_2026.json"))
    by = {(r.reporter_iso3, r.partner_iso3, r.period_label): r for r in parsed.records}
    assert set(by) == {("DEU", "UKR", "2026-W41"), ("ITA", "CHN", "2026-W41"), ("ITA", "ARG", "2026-W40"),
                       ("ESP", "UKR", "2026-W42"), ("GRC", "UKR", "2026-W42"), ("NLD", "SRB", "2026-W41")}
    de = by[("DEU", "UKR", "2026-W41")]
    assert (de.kg, de.eur, de.rows) == (22_000, 49_800, 2)          # exact duplicate ignored, MFN row summed
    assert de.categories == {"Import - preferential": {"kg": 20_000, "eur": 44_800},
                             "Import - most favoured nation": {"kg": 2_000, "eur": 5_000}}
    assert de.period == (date(2026, 10, 5), date(2026, 10, 11))     # ISO week 41 of 2026, Monday-Sunday
    assert ("DEU", "CHN", "2026-W40") not in by                     # conflicting duplicates: not stored
    assert any("conflicting" in p for p in parsed.problems)
    assert any("invalid kg" in p for p in parsed.problems)
    assert parsed.unmapped_partners == {"QW": 1}


def test_taxud_end_to_end(run_with_routes, session_factory, pin_today):
    res = run_with_routes("ec_taxud_weekly", _taxud_routes())
    assert res["status"] == "partial" and len(res["warnings"]) == 2, res      # conflict + malformed row
    with session_factory() as s:
        trades = _rows(s, TradeFlowObservation, "ec_taxud_weekly")
        assert len(trades) == 6
        assert all(t.frequency == "W" and t.data_status == "provisional" and t.flow == "import" for t in trades)
        de = next(t for t in trades if (t.reporter_iso3, t.partner_iso3) == ("DEU", "UKR"))
        assert (de.period_label, de.period_start, de.period_end) == ("2026-W41", date(2026, 10, 5), date(2026, 10, 11))
        assert de.extra["import_categories"]["Import - preferential"] == {"kg": 20_000, "eur": 44_800}
        assert de.source_url.startswith(eu.TAXUD_IMPORT_URL) and de.raw_document_id
        prices = _rows(s, PriceObservation, "ec_taxud_weekly")
        assert {(p.market_iso3, p.origin_iso3) for p in prices} == {("DEU", "UKR"), ("ITA", "CHN"), ("ITA", "ARG"),
                                                                    ("GRC", "UKR"), ("NLD", "SRB")}   # ESP 500 kg: none
        de_p = next(p for p in prices if p.market_iso3 == "DEU")
        assert de_p.price_type == "import_unit_value" and de_p.price_value == round(49_800 / 22_000, 4)
        assert de_p.frequency == "W" and de_p.data_status == "provisional" and de_p.variety == "unspecified"
        n = len(trades), len(prices)
    res2 = run_with_routes("ec_taxud_weekly", _taxud_routes())
    assert res2["status"] == "no_change" and res2["new"] == 0, res2
    with session_factory() as s:
        assert (len(_rows(s, TradeFlowObservation, "ec_taxud_weekly")), len(_rows(s, PriceObservation, "ec_taxud_weekly"))) == n


def test_taxud_probe_failures(run_with_routes, session_factory, pin_today):
    res = run_with_routes("ec_taxud_weekly", _taxud_routes(sectors=b'["Beef", "Garlic", "Sugar"]'))
    assert res["status"] == "failed" and "Honey" in res["error"], res
    res = run_with_routes("ec_taxud_weekly", _taxud_routes(sectors=b'{"error": "maintenance"}'))
    assert res["status"] == "failed" and "sectors" in res["error"], res
    # a required field renamed in every row -> schema drift, nothing stored
    rows = json.loads(fixture_bytes("eu/taxud_import_honey_2026.json"))
    for r in rows:
        r["valueInEuro"] = r.pop("euroValue")
    res = run_with_routes("ec_taxud_weekly", _taxud_routes(import_body=json.dumps(rows).encode()))
    assert res["status"] == "failed" and "schema drift" in res["error"] and "euroValue" in res["error"], res
    with session_factory() as s:
        assert _rows(s, TradeFlowObservation, "ec_taxud_weekly") == []


def test_taxud_openapi_probe_warns_when_path_disappears(run_with_routes, session_factory, pin_today):
    res = run_with_routes("ec_taxud_weekly", _taxud_routes(docs=b'{"openapi": "3.0.1", "paths": {}}'))
    assert res["status"] == "partial"
    assert any("OpenAPI" in w for w in res["warnings"]), res
    with session_factory() as s:
        assert len(_rows(s, TradeFlowObservation, "ec_taxud_weekly")) == 6     # data still collected


# ---------------------------------------------------------------------------
# DG AGRI honey page
# ---------------------------------------------------------------------------

OVERVIEW_URL = ("https://agriculture.ec.europa.eu/document/download/7d2f1c3e-9b4a-4e1f-8c55-2a6b0e4d9f10_en"
                "?filename=honey-market-overview-january-2026_en.pdf")
AUTUMN_URL = ("https://agriculture.ec.europa.eu/document/download/c04a9774-5ba3-41f5-b256-08396b2888ec_en"
              "?filename=market-presentation-honey_autumn2024_en.pdf")


def _honey_routes(autumn: bytes | tuple | None = None):
    return {
        eu.HONEY_PAGE_URL: (200, fixture_bytes("eu/honey_page.html"), "text/html; charset=utf-8"),
        OVERVIEW_URL: (200, fixture_bytes("eu/honey-market-overview-january-2026_en.pdf"), "application/pdf"),
        AUTUMN_URL: autumn or (200, fixture_bytes("eu/market-presentation-honey_autumn2024_en.pdf"), "application/pdf"),
    }


def test_find_honey_reports_on_page():
    links = eu.find_honey_reports(fixture_bytes("eu/honey_page.html").decode())
    assert [link.url for link in links] == [AUTUMN_URL, OVERVIEW_URL]       # prefLang stripped, deduplicated
    autumn, overview = links
    assert overview.title == "Honey market overview (January 2026)"        # from the ECL block, not "Download"
    assert (overview.published_at, overview.period_label) == (date(2026, 1, 29), "2026-01")
    # the paragraph holds two documents: its "8 October 2024" belongs to the CDG minutes, not to this deck
    assert autumn.published_at is None and autumn.period_label == "2024 autumn"
    assert autumn.report_key == "c04a9774-5ba3-41f5-b256-08396b2888ec/market-presentation-honey_autumn2024_en.pdf"


def test_price_table_rules_are_strict():
    ok = [["Member State", "2023", "2024"], ["Italy", "6,10", "6,40"], ["Romania", "-", "3,30"]]
    assert eu._parse_price_table(ok) == [("Italy", "ITA", 2023, 6.1), ("Italy", "ITA", 2024, 6.4), ("Romania", "ROU", 2024, 3.3)]
    assert eu._parse_price_table([["Member State", "2023"], ["Italy", "approx. 6"]]) is None       # odd cell
    assert eu._parse_price_table([["Member State", "Q1", "Q2"], ["Italy", "6,1", "6,2"]]) is None  # not years
    assert eu._parse_price_table([["Region", "2023"], ["Italy", "6,1"]]) is None                   # unknown header
    assert eu._parse_price_table([["Member State", "2023"], ["Atlantis", "6,1"]]) is None          # unknown row
    assert eu._classify_price_page("Honey prices at production site (EUR/kg)")[0] == PriceType.PRODUCER
    assert eu._classify_price_page("Prices at production site and in bulk to wholesalers") is None


def test_honey_market_end_to_end(run_with_routes, session_factory):
    res = run_with_routes("ec_honey_market", _honey_routes())
    assert res["status"] == "success", res
    with session_factory() as s:
        reports = {r.url: r for r in _rows(s, Report, "ec_honey_market")}
        assert set(reports) == {AUTUMN_URL, OVERVIEW_URL}
        ov = reports[OVERVIEW_URL]
        assert ov.title == "Honey market overview (January 2026)" and ov.published_at == date(2026, 1, 29)
        assert ov.raw_document_id and ov.narrative.startswith("Honey market overview")
        assert "Import prices stayed under pressure" in ov.narrative
        assert reports[AUTUMN_URL].published_at is None and "self-sufficiency" in reports[AUTUMN_URL].narrative
        prices = _rows(s, PriceObservation, "ec_honey_market")
        # only the unambiguous table (page 2): 4 countries + EU, Romania 2023 is "-" (not zero-filled)
        assert len(prices) == 9
        assert {p.price_type for p in prices} == {"producer"}                  # free text / mixed table ignored
        ita = sorted((p.period_label, p.price_value) for p in prices if p.origin_iso3 == "ITA")
        assert ita == [("2023", 6.1), ("2024", 6.4)]
        eu27 = [p for p in prices if p.market_iso3 == "EU27"]
        assert sorted(p.price_value for p in eu27) == [5.98, 6.05]
        p0 = prices[0]
        assert (p0.variety, p0.currency, p0.unit, p0.frequency, p0.data_status) == ("polyflora", "EUR", "kg", "A", "published")
        assert p0.published_at == date(2026, 1, 29) and p0.source_url == OVERVIEW_URL and "pagina 2" in p0.notes
    res2 = run_with_routes("ec_honey_market", _honey_routes())
    assert res2["status"] == "no_change" and res2["new"] == 0, res2
    with session_factory() as s:
        assert len(_rows(s, Report, "ec_honey_market")) == 2 and len(_rows(s, PriceObservation, "ec_honey_market")) == 9


def test_honey_market_non_pdf_is_skipped_and_retried_later(run_with_routes, session_factory):
    res = run_with_routes("ec_honey_market", _honey_routes(autumn=(200, b"<html>Service unavailable</html>", "text/html")))
    assert res["status"] == "partial" and any("not a PDF" in w for w in res["warnings"]), res
    res2 = run_with_routes("ec_honey_market", _honey_routes())        # next run picks up the missing deck
    assert res2["status"] == "success" and res2["new"] == 1, res2
    with session_factory() as s:
        assert len(_rows(s, Report, "ec_honey_market")) == 2


# ---------------------------------------------------------------------------
# RASFF
# ---------------------------------------------------------------------------


def test_parse_rasff_search():
    page = eu.parse_rasff_search(fixture_bytes("eu/rasff_search_honey_p1.json"))
    assert page.total_pages == 1 and len(page.notifications) == 4 and page.problems == []
    by = {n.reference: n for n in page.notifications}
    n = by["2026.7712"]
    assert (n.notif_id, n.validated_at, n.origin_iso3, n.notifying) == (912345, date(2026, 10, 27), ["CHN"], "Italy")
    assert n.status == "border rejection / serious"
    assert n.url == "https://webgate.ec.europa.eu/rasff-window/screen/notification/912345"
    assert by["2026.7420"].origin_iso3 == ["SRB", "HUN"]
    assert by["2026.7420"].status == "info (follow-up) / potentially serious"
    assert all(len(x.status) <= 40 for x in page.notifications)


@pytest.mark.parametrize("body, msg", [
    (b'{"content": [], "totalPages": 0}', "notifications"),
    (b'{"notifications": [], "pages": 0}', "totalPages"),
    (b'{"notifications": [{"id": 1, "ref": "2026.1"}], "totalPages": 1}', "absent from every notification"),
    (b'<html>maintenance</html>', "not valid JSON"),
])
def test_parse_rasff_search_unexpected_shape(body, msg):
    with pytest.raises(eu.CollectorError, match=msg):
        eu.parse_rasff_search(body)


def test_rasff_end_to_end(run_with_routes, session_factory, pin_today):
    res = run_with_routes("rasff_honey", {RASFF: (200, fixture_bytes("eu/rasff_search_honey_p1.json"), "application/json")})
    assert res["status"] == "success" and res["new"] == 3, res
    with session_factory() as s:
        items = {r.reference: r for r in _rows(s, RegulationItem, "rasff_honey")}
        assert set(items) == {"2026.7712", "2026.7604", "2026.7420"}         # royal jelly filtered out
        r = items["2026.7712"]
        assert (r.jurisdiction, r.doc_type, r.title) == ("EU", "food_safety_notification", "Chloramphenicol in honey from China")
        assert r.published_at == date(2026, 10, 27) and r.countries == ["CHN"]
        assert r.url == "https://webgate.ec.europa.eu/rasff-window/screen/notification/912345"
        assert r.status == "border rejection / serious" and "Notified by: Italy" in r.summary_en
        assert r.summary_is_ai is False
        assert items["2026.7604"].status == "info (attention) / not serious"
    res2 = run_with_routes("rasff_honey", {RASFF: (200, fixture_bytes("eu/rasff_search_honey_p1.json"), "application/json")})
    assert res2["status"] == "no_change" and res2["new"] == 0, res2
    with session_factory() as s:
        assert len(_rows(s, RegulationItem, "rasff_honey")) == 3


def test_rasff_shape_change_fails_run(run_with_routes, session_factory, pin_today):
    res = run_with_routes("rasff_honey", {RASFF: (200, b'{"content": [{"notifId": 1}], "totalPages": 1}', "application/json")})
    assert res["status"] == "failed" and "RASFF response shape changed" in res["error"], res
    with session_factory() as s:
        assert _rows(s, RegulationItem, "rasff_honey") == []


def test_all_eu_collectors_registered():
    from paladex.collectors.registry import all_collectors

    keys = {c.key for c in all_collectors(refresh=True)}
    assert {"eurostat_comext", "ec_taxud_weekly", "ec_honey_market", "rasff_honey"} <= keys
