"""Tests for the EU collectors (paladex/collectors/eu.py).

All fixtures in tests/fixtures/eu/ are RECONSTRUCTED from documentation (see the README
there); the numbers are illustrative.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import httpx
import pytest
import respx
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


def test_comext_interrupted_backfill_is_pulled_in_full_again(run_with_routes, session_factory, pin_today, monkeypatch):
    """COMEXT-1: rows committed by an interrupted first back-fill do not shrink the next pull to 24 months."""
    fixture = fixture_bytes("eu/comext_honey_2026-10-16.json")
    routes = {
        COMEXT_MAIN + r".*sinceTimePeriod=2021-12": fixture,                   # the 60-month back-fill window
        COMEXT_MAIN: (400, b'{"error": {"label": "this test only serves the 60-month window"}}'),
        COMEXT_ANY: fixture_bytes("eu/comext_probe_2026-10-16.json"),
    }
    real_store = eu.EurostatComextCollector._store_record
    fail_on = {"ITA"}

    def store_record(self, ctx, doc, release, published, rec, reporter, partner):
        if reporter in fail_on:
            raise RuntimeError("database is locked")                          # after DEU and EU27 were committed
        return real_store(self, ctx, doc, release, published, rec, reporter, partner)

    monkeypatch.setattr(eu.EurostatComextCollector, "_store_record", store_record)
    res = run_with_routes("eurostat_comext", routes)
    assert res["status"] == "failed" and "database is locked" in res["error"], res
    with session_factory() as s:
        assert {t.reporter_iso3 for t in _rows(s, TradeFlowObservation, "eurostat_comext")} == {"DEU", "EU27"}
    fail_on.clear()
    res = run_with_routes("eurostat_comext", routes)
    assert res["status"] == "success", res
    with session_factory() as s:
        assert {t.reporter_iso3 for t in _rows(s, TradeFlowObservation, "eurostat_comext")} == {"DEU", "EU27", "ITA"}
    res = run_with_routes("eurostat_comext", routes)                         # now complete: the cheap check only
    assert res["status"] == "no_change", res


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


def _comext_doc(rows: list[tuple[str, str, str, str, float, float]], updated: str = "2026-10-16T11:00:00+0200") -> bytes:
    """A DS-045409 JSON-stat answer: rows = (reporter, partner, flow, period, value EUR, quantity 100 kg)."""
    dims = {"freq": ["M"], "reporter": sorted({r[0] for r in rows}), "partner": sorted({r[1] for r in rows}),
            "product": [eu.HONEY_CN8], "flow": ["1", "2"], "indicators": [eu.COMEXT_VALUE, eu.COMEXT_QTY],
            "time": sorted({r[3] for r in rows})}
    ids = list(dims)
    size = [len(dims[d]) for d in ids]
    values = {}
    for rep, par, flow, period, value, qty in rows:
        for ind, v in ((eu.COMEXT_VALUE, value), (eu.COMEXT_QTY, qty)):
            pos = {"freq": 0, "reporter": dims["reporter"].index(rep), "partner": dims["partner"].index(par),
                   "product": 0, "flow": dims["flow"].index(flow), "indicators": dims["indicators"].index(ind),
                   "time": dims["time"].index(period)}
            idx = 0
            for d, n in zip(ids, size):
                idx = idx * n + pos[d]
            values[str(idx)] = v
    doc = {"version": "2.0", "class": "dataset", "updated": updated, "id": ids, "size": size, "value": values,
           "dimension": {d: {"category": {"index": {c: i for i, c in enumerate(cs)}, "label": {c: c for c in cs}}}
                         for d, cs in dims.items()}}
    return json.dumps(doc).encode()


def test_comext_panel_covers_every_member_state_with_its_main_partners():
    """Lead request 2026-11-05: Eurostat Comext reported only the EU27 and 8 member states. Every member
    state now reports; a member state also gets the other member states and the intra-EU total (most of
    its honey trade), the EU27 aggregate only extra-EU partners (its total is the extra-EU row)."""
    assert len(eu.EU_MEMBER_CODES) == 27 and eu.COMEXT_REPORTERS == ["EU27_2020", *eu.EU_MEMBER_CODES]
    assert {eu.map_geo(c) for c in eu.EU_MEMBER_CODES} == set(eu.EU_MEMBER_ISO3)
    assert eu.map_geo("INT_EU27_2020") == "INTRA_EU"
    # a member state: every partner (Italy's main buyers are Germany and France, not honey origins)
    assert all(eu.comext_partners(rep) is None for rep in eu.EU_MEMBER_CODES)
    assert "partner" not in eu._comext_params("2026-01", reporters=["IT"], partners=None, flows=["2"], indicators=["X"])
    eu27 = eu.comext_partners("EU27_2020")
    assert len(eu27) == len(set(eu27)) and all(eu.map_geo(p) for p in eu27)
    assert {"EXT_EU27_2020", "WORLD", "GB", "CH", "US", "SA", "JP", "UA", "CN", "AR"} <= set(eu27)
    assert not set(eu27) & set(eu.EU_MEMBER_CODES) and "INT_EU27_2020" not in eu27


def test_comext_pulls_each_member_state_with_intra_eu_partners(run_with_routes, session_factory, pin_today, monkeypatch):
    """One request per reporter; Austria's trade with Germany and the intra-EU total is stored, but no 'unit
    value by origin' is derived from intra-EU trade (recorded by member state of consignment)."""
    from paladex.models import AppSetting

    doc = _comext_doc([
        ("AT", "DE", "1", "2026-08", 900_000.0, 1_500.0), ("AT", "UA", "1", "2026-08", 300_000.0, 1_000.0),
        ("AT", "INT_EU27_2020", "1", "2026-08", 1_200_000.0, 2_200.0),
        ("AT", "EXT_EU27_2020", "1", "2026-08", 310_000.0, 1_030.0),
        ("AT", "WORLD", "1", "2026-08", 1_510_000.0, 3_230.0), ("AT", "CH", "2", "2026-08", 160_000.0, 200.0),
        ("AT", "IT", "2", "2026-08", 80_000.0, 120.0),
        # an answer for every partner also holds other aggregates and special codes: skipped quietly
        ("AT", "EXT_EA21", "1", "2026-08", 400_000.0, 1_100.0), ("AT", "EU27_2020", "1", "2026-08", 1.0, 1.0),
        ("AT", "XK", "2", "2026-08", 5_000.0, 10.0), ("AT", "QS", "2", "2026-08", 900.0, 1.0),
    ])
    empty = _comext_doc([("EU27_2020", "CN", "1", "2026-08", 1.0, 1.0)])     # served to every other reporter
    at_only = r"^https://ec\.europa\.eu/eurostat/api/comext/.*DS-045409\?(?=.*reporter=AT&)(?=.*QUANTITY_IN_100KG)"
    routes = {at_only: doc, COMEXT_MAIN: empty, COMEXT_ANY: fixture_bytes("eu/comext_probe_2026-10-16.json")}
    asked: list[dict] = []
    real_params = eu._comext_params

    def params(since, **kw):
        if eu.COMEXT_QTY in kw["indicators"]:
            asked.append(kw)
        return real_params(since, **kw)

    monkeypatch.setattr(eu, "_comext_params", params)
    res = run_with_routes("eurostat_comext", routes)
    assert res["status"] == "success", res
    with session_factory() as s:
        trades = _rows(s, TradeFlowObservation, "eurostat_comext", reporter_iso3="AUT")
        assert {(t.partner_iso3, t.flow) for t in trades} == {
            ("DEU", "import"), ("UKR", "import"), ("INTRA_EU", "import"), ("EXTRA_EU", "import"), ("WLD", "import"),
            ("CHE", "export"), ("ITA", "export")}
        de = next(t for t in trades if t.partner_iso3 == "DEU")
        assert de.net_weight_kg == 150_000 and de.value == 900_000 and de.value_basis == "CIF"
        prices = _rows(s, PriceObservation, "eurostat_comext")
        assert {(p.origin_iso3, p.market_iso3, p.price_type) for p in prices} == {
            ("UKR", "AUT", "import_unit_value"), ("EXTRA_EU", "AUT", "import_unit_value"),
            ("AUT", "CHE", "export_unit_value")}            # not from DEU, INTRA_EU, WLD or the export to ITA
        state = s.get(AppSetting, "collector_state:eurostat_comext").value
        assert state["panel"] == eu.comext_panel() and state["backfill_since"] == "2021-12"
    # one request per reporter, each naming exactly that reporter; the member states also ask for the
    # other member states and the intra-EU total, the EU27 does not
    assert [q["reporters"] for q in asked] == [[r] for r in eu.COMEXT_REPORTERS]
    at_q = next(q for q in asked if q["reporters"] == ["AT"])
    assert at_q["partners"] is None                                           # every partner
    eu_q = next(q for q in asked if q["reporters"] == ["EU27_2020"])
    assert "DE" not in eu_q["partners"] and "INT_EU27_2020" not in eu_q["partners"]


def test_comext_new_panel_triggers_the_full_backfill(run_with_routes, session_factory, pin_today, monkeypatch):
    """An installation whose state was written for the old 9-reporter panel pulls five years for everyone,
    even though the Eurostat vintage did not change (the new member states would otherwise wait a month
    and then get 24 months only)."""
    from paladex.models import AppSetting

    routes = {COMEXT_MAIN: fixture_bytes("eu/comext_honey_2026-10-16.json"),
              COMEXT_ANY: fixture_bytes("eu/comext_probe_2026-10-16.json")}
    assert run_with_routes("eurostat_comext", routes)["status"] == "success"
    assert run_with_routes("eurostat_comext", routes)["status"] == "no_change"      # same vintage, same panel
    with session_factory() as s:
        row = s.get(AppSetting, "collector_state:eurostat_comext")
        row.value = {k: v for k, v in row.value.items() if k != "panel"}            # state of the old version
    seen: list[str] = []
    real_pull = eu.EurostatComextCollector._pull

    def pull(self, ctx, since, reporter):
        seen.append(f"{reporter}:{since}")
        return real_pull(self, ctx, since, reporter)

    monkeypatch.setattr(eu.EurostatComextCollector, "_pull", pull)
    res = run_with_routes("eurostat_comext", routes)
    assert res["status"] in ("success", "no_change"), res
    assert seen == [f"{r}:2021-12" for r in eu.COMEXT_REPORTERS]
    with session_factory() as s:
        assert s.get(AppSetting, "collector_state:eurostat_comext").value["panel"] == eu.comext_panel()


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
    assert de.period == (date(2026, 10, 5), date(2026, 10, 11))     # TAXUD week 41 of 2026, Monday-Sunday
    assert ("DEU", "CHN", "2026-W40") not in by                     # conflicting duplicates: not stored
    assert any("conflicting" in p for p in parsed.problems)
    assert any("invalid kg" in p for p in parsed.problems)
    assert parsed.unmapped_partners == {"QW": 1}


@pytest.mark.parametrize("year, week, bounds", [
    (2024, 1, (date(2024, 1, 1), date(2024, 1, 7))),        # 1 Jan 2024 is a Monday
    (2024, 53, (date(2024, 12, 30), date(2024, 12, 31))),   # published by TAXUD; ISO 2024 has no week 53
    (2025, 1, (date(2025, 1, 1), date(2025, 1, 5))),        # partial: ISO week 1 would start on 30 Dec 2024
    (2025, 35, (date(2025, 8, 25), date(2025, 8, 31))),     # live check: week 35 has only August rows
    (2025, 36, (date(2025, 9, 1), date(2025, 9, 7))),       # live check: week 36 has only September rows
    (2025, 40, (date(2025, 9, 29), date(2025, 10, 5))),     # live check: September and October rows
    (2025, 53, (date(2025, 12, 29), date(2025, 12, 31))),   # live check: December rows
    (2026, 1, (date(2026, 1, 1), date(2026, 1, 4))),
    (2026, 53, (date(2026, 12, 28), date(2026, 12, 31))),
    (2023, 1, (date(2023, 1, 1), date(2023, 1, 1))),        # 1 Jan 2023 is a Sunday: a one-day week 1
    (2023, 2, (date(2023, 1, 2), date(2023, 1, 8))),        # = ISO 2023-W01: every week differs by one
    (2040, 54, (date(2040, 12, 31), date(2040, 12, 31))),   # leap year starting on a Sunday
    (2026, 54, None), (2025, 0, None), (2024, 54, None),
])
def test_taxud_week_bounds(year, week, bounds):
    assert eu.taxud_week_bounds(year, week) == bounds


def test_parse_real_taxud_week_53_and_week_1():
    """Real captures (2026-11-04): TAXUD publishes week 53 of 2024 and of 2025 (ISO has neither)."""
    p24 = eu.parse_taxud_weekly(fixture_bytes("eu/real_taxud_honey_2024_w52-53_AR-UA.json"))
    assert not p24.problems and p24.other_products == {"15219091": 1, "12129995": 1}   # beeswax etc. ignored
    by24 = {(r.reporter_iso3, r.partner_iso3, r.period_label): r for r in p24.records}
    de53 = by24[("DEU", "ARG", "2024-W53")]
    assert de53.period == (date(2024, 12, 30), date(2024, 12, 31))
    assert de53.partner_label == "Argentina" and de53.cn8 == ["04090000"]
    p25 = eu.parse_taxud_weekly(fixture_bytes("eu/real_taxud_honey_2025_w01-52-53_AR-UA.json"))
    assert not p25.problems
    by25 = {(r.reporter_iso3, r.partner_iso3, r.period_label): r for r in p25.records}
    assert {k for k in by25 if k[2] == "2025-W53"} == {("DEU", "ARG", "2025-W53"), ("ESP", "ARG", "2025-W53"),
                                                       ("FRA", "UKR", "2025-W53")}
    assert by25[("FRA", "UKR", "2025-W53")].period == (date(2025, 12, 29), date(2025, 12, 31))
    assert by25[("DEU", "UKR", "2025-W01")].period == (date(2025, 1, 1), date(2025, 1, 5))
    assert by25[("GRC", "UKR", "2025-W01")].member_state == "EL"
    p26 = eu.parse_taxud_weekly(fixture_bytes("eu/real_taxud_honey_2026_w01-02_AR-UA.json"))
    # Two real rows with the same published dimensions and different figures: not summed, not stored.
    assert [p for p in p26.problems if "conflicting" in p] == [
        "TAXUD: conflicting duplicate rows for PL/UA 2026-W01 (61950 kg vs 187775 kg); that cell is not stored"]
    assert ("POL", "UKR", "2026-W01") not in {(r.reporter_iso3, r.partner_iso3, r.period_label) for r in p26.records}


def test_taxud_end_to_end_real_captures(run_with_routes, session_factory, pin_today):
    pin_today(date(2026, 11, 4))
    routes = {
        eu.TAXUD_SECTORS_URL: fixture_bytes("eu/taxud_sectors.json"),
        eu.TAXUD_OPENAPI_URL: fixture_bytes("eu/taxud_api_docs.json"),
        r"^https://api\.tech\.ec\.europa\.eu/agrifood/api/taxud/weeklyData/import\?.*marketingYears=2024":
            fixture_bytes("eu/real_taxud_honey_2024_w52-53_AR-UA.json"),
        r"^https://api\.tech\.ec\.europa\.eu/agrifood/api/taxud/weeklyData/import\?.*marketingYears=2025":
            fixture_bytes("eu/real_taxud_honey_2025_w01-52-53_AR-UA.json"),
        TAXUD_IMPORT_2026: fixture_bytes("eu/real_taxud_honey_2026_w01-02_AR-UA.json"),
    }
    res = run_with_routes("ec_taxud_weekly", routes)
    assert res["status"] == "partial" and len(res["warnings"]) == 1 and "PL/UA 2026-W01" in res["warnings"][0], res
    with session_factory() as s:
        trades = _rows(s, TradeFlowObservation, "ec_taxud_weekly")
        assert len(trades) == 6 + 29 + 25                                # every cell but the conflicting one
        w53 = sorted((t.period_label, t.reporter_iso3, t.partner_iso3, t.period_start, t.period_end)
                     for t in trades if t.period_label.endswith("-W53"))
        assert w53 == [("2024-W53", "DEU", "ARG", date(2024, 12, 30), date(2024, 12, 31)),
                       ("2025-W53", "DEU", "ARG", date(2025, 12, 29), date(2025, 12, 31)),
                       ("2025-W53", "ESP", "ARG", date(2025, 12, 29), date(2025, 12, 31)),
                       ("2025-W53", "FRA", "UKR", date(2025, 12, 29), date(2025, 12, 31))]
        fr = next(t for t in trades if (t.period_label, t.reporter_iso3) == ("2025-W53", "FRA"))
        assert fr.extra["week_days"] == 3 and "Not an ISO week" in fr.extra["week_rule"]
        it = next(t for t in trades if (t.period_label, t.reporter_iso3, t.partner_iso3) == ("2026-W01", "ITA", "ARG"))
        assert (it.period_start, it.period_end, it.extra["week_days"]) == (date(2026, 1, 1), date(2026, 1, 4), 4)


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
    # undated decks are ordered by the period they name, not ahead of everything
    assert (autumn.deck_date, overview.deck_date) == (date(2024, 9, 1), date(2026, 1, 29))


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


def _fixture_builder():
    """tests/fixtures/eu/build_fixtures.py (dependency-free PDF writer), loaded as a module."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("eu_fixture_builder", FIXTURES / "eu" / "build_fixtures.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _deck(title: str, rows: list[list[str]]) -> bytes:
    """A one-page deck: a page title and one ruled table, as in the January 2026 fixture."""
    b = _fixture_builder()
    page = (b.text(60, 540, title, 16) + b.text(60, 515, b.FIXTURE_LINE, 10)
            + b.table(60, 490, [160] + [90] * (len(rows[0]) - 1), rows))
    return b.build_pdf([page], title)


def test_honey_market_dead_link_does_not_block_other_decks(run_with_routes, session_factory):
    """DGAGRI-1: one deck answering 404 is skipped; the other decks are still read."""
    res = run_with_routes("ec_honey_market", _honey_routes(autumn=(404, b"Not found", "text/html")))
    assert res["status"] == "partial" and any("download failed" in w for w in res["warnings"]), res
    with session_factory() as s:
        assert [r.url for r in _rows(s, Report, "ec_honey_market")] == [OVERVIEW_URL]
        assert len(_rows(s, PriceObservation, "ec_honey_market")) == 9
    res2 = run_with_routes("ec_honey_market", _honey_routes())        # the dead link is retried
    assert res2["status"] == "success" and res2["new"] == 1, res2


def test_honey_market_every_download_failing_is_a_failure(run_with_routes, session_factory):
    routes = {**_honey_routes(autumn=(404, b"Not found", "text/html")), OVERVIEW_URL: (404, b"Not found", "text/html")}
    res = run_with_routes("ec_honey_market", routes)
    assert res["status"] == "failed" and "could be downloaded" in res["error"], res


def test_honey_market_older_deck_never_supersedes_a_newer_one(run_with_routes, session_factory):
    """DGAGRI-2: the autumn-2024 deck, retried after the January-2026 one, keeps the 2026 figure current."""
    autumn = _deck("Honey prices at production site - multifloral honey (EUR/kg)",
                   [["Member State", "2023"], ["Italy", "5,40"]])
    res = run_with_routes("ec_honey_market", _honey_routes(autumn=(200, b"<html>Service unavailable</html>", "text/html")))
    assert res["status"] == "partial", res
    res2 = run_with_routes("ec_honey_market", _honey_routes(autumn=(200, autumn, "application/pdf")))
    assert res2["status"] == "success" and res2["new"] == 1 and res2["revised"] == 0, res2
    with session_factory() as s:
        hist = _rows(s, PriceObservation, "ec_honey_market", origin_iso3="ITA", period_label="2023")
        assert [(p.price_value, p.is_current, p.published_at) for p in hist] == [(6.1, True, date(2026, 1, 29))]
        assert hist[0].extra["deck_date"] == "2026-01-29"
        assert {r.url for r in _rows(s, Report, "ec_honey_market")} == {AUTUMN_URL, OVERVIEW_URL}
    # the autumn file replaced in place with other figures is still the older deck: no revision
    replaced = _deck("Honey prices at production site - multifloral honey (EUR/kg)",
                     [["Member State", "2023"], ["Italy", "6,25"]])
    res3 = run_with_routes("ec_honey_market", _honey_routes(autumn=(200, replaced, "application/pdf")), force=True)
    assert res3["revised"] == 0, res3                                # autumn deck (Sept 2024) < January 2026
    with session_factory() as s:
        cur = [p for p in _rows(s, PriceObservation, "ec_honey_market", origin_iso3="ITA", period_label="2023") if p.is_current]
        assert [p.price_value for p in cur] == [6.1]


def test_honey_market_force_reextracts_prices_of_a_known_deck(run_with_routes, session_factory, monkeypatch):
    """DGAGRI-3: after a failed table extraction, --force re-reads the unchanged PDF."""
    def broken(content):
        raise ValueError("pdfminer could not read the page")

    real = eu.extract_price_tables
    monkeypatch.setattr(eu, "extract_price_tables", broken)
    res = run_with_routes("ec_honey_market", _honey_routes())
    assert res["status"] == "partial" and any("table extraction failed" in w for w in res["warnings"]), res
    with session_factory() as s:
        assert _rows(s, PriceObservation, "ec_honey_market") == []
    monkeypatch.setattr(eu, "extract_price_tables", real)          # parser fixed (not undo(): keeps the no-sleep patch)
    res2 = run_with_routes("ec_honey_market", _honey_routes(), force=True)
    assert res2["status"] == "success" and res2["new"] == 9, res2
    res3 = run_with_routes("ec_honey_market", _honey_routes(), force=True)
    assert res3["new"] == 0 and res3["revised"] == 0, res3
    with session_factory() as s:
        assert len(_rows(s, PriceObservation, "ec_honey_market", is_current=True)) == 9
        assert len(_rows(s, Report, "ec_honey_market")) == 2         # no duplicate report for the same bytes


def test_import_unit_value_tables_need_origin_rows(tmp_path):
    """DGAGRI-4: on an import page, member-state rows are importers, not origins."""
    assert eu._parse_price_table([["Member State", "2023"], ["Germany", "2,10"]], row_headers=eu._ORIGIN_HEADERS) is None
    by_ms = _deck("Import unit value by Member State (EUR/kg)",
                  [["Member State", "2023", "2024"], ["Germany", "2,10", "2,05"], ["Italy", "2,30", "2,20"]])
    assert eu.extract_price_tables(by_ms) == []
    with_eu_total = _deck("Import unit value by origin (EUR/kg)",
                          [["Origin", "2023", "2024"], ["China", "1,85", "1,90"], ["EU", "2,40", "2,45"]])
    assert eu.extract_price_tables(with_eu_total) == []
    by_origin = _deck("Import unit value by origin (EUR/kg)", [["Origin", "2023", "2024"], ["China", "1,85", "1,90"]])
    rows = eu.extract_price_tables(by_origin)
    assert [(r.price_type, r.market_iso3, r.origin_iso3, r.year, r.value) for r in rows] == [
        (PriceType.IMPORT_UNIT_VALUE, "EU27", "CHN", 2023, 1.85), (PriceType.IMPORT_UNIT_VALUE, "EU27", "CHN", 2024, 1.9)]
    # producer pages keep accepting member-state tables
    producer = _deck("Honey prices at production site (EUR/kg)", [["Member State", "2024"], ["Italy", "6,40"]])
    assert [(r.market_iso3, r.origin_iso3) for r in eu.extract_price_tables(producer)] == [("ITA", "ITA")]


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


@pytest.fixture()
def run_rasff(run_with_routes):
    """Run rasff_honey against `responder(body) -> (status, bytes)`, which sees every POSTed JSON
    body. Returns (result, bodies). `run_with_routes` provides the database and disables sleeps."""
    from paladex.collectors.runner import run_collector

    def _run(responder, force: bool = False):
        bodies: list[dict] = []

        def answer(request):
            body = json.loads(request.content)
            bodies.append(body)
            status, content = responder(body)
            return httpx.Response(status, content=content, headers={"content-type": "application/json"})

        with respx.mock(assert_all_called=False) as mock:
            mock.route(method="POST", url__startswith=eu.RASFF_SEARCH_URL).mock(side_effect=answer)
            mock.route().mock(side_effect=httpx.ConnectError("blocked in tests"))
            with httpx.Client(follow_redirects=True) as client:
                res = run_collector("rasff_honey", trigger="test", force=force, client=client)
        return res, bodies

    return _run


def _rasff_notifications() -> list[dict]:
    return json.loads(fixture_bytes("eu/rasff_search_honey_p1.json"))["notifications"]


def _rasff_answer(notifications: list[dict], total_pages: int = 1) -> tuple[int, bytes]:
    return 200, json.dumps({"totalPages": total_pages, "totalElements": len(notifications),
                            "notifications": notifications}).encode()


def test_rasff_window_reaches_back_to_the_last_complete_run(run_rasff, session_factory, pin_today):
    """RASFF-1: after more than 30 days without a run, the gap is still read."""
    late = {**_rasff_notifications()[0], "notifId": 913000, "reference": "2026.8101",
            "ecValidationDate": "10-11-2026 11:20:00", "subject": "Chloramphenicol in honey from China"}

    def server(body):            # the backend filters on the validation date, as the real one does
        since = datetime.strptime(body["ecValidDateFrom"][:10], "%d-%m-%Y").date() if "ecValidDateFrom" in body else date.min
        items = [n for n in [late, *_rasff_notifications()]
                 if datetime.strptime(n["ecValidationDate"][:10], "%d-%m-%Y").date() >= since]
        return _rasff_answer(items)

    res, bodies = run_rasff(lambda body: _rasff_answer(_rasff_notifications()))   # run on 2026-11-02
    assert res["status"] == "success" and bodies[0]["ecValidDateFrom"] == "01-01-2020 00:00:00", res
    pin_today(date(2026, 12, 21))                                                   # seven weeks later
    res, bodies = run_rasff(server)
    assert bodies[0]["ecValidDateFrom"] == "26-10-2026 00:00:00", bodies            # not 21-11-2026
    assert res["status"] == "success" and res["new"] == 1, res
    with session_factory() as s:
        assert "2026.8101" in {r.reference for r in _rows(s, RegulationItem, "rasff_honey")}


def test_rasff_interrupted_backfill_is_resumed_in_full(run_rasff, session_factory, pin_today):
    """RASFF-1: rows checkpointed by an interrupted first back-fill do not make later runs incremental."""
    first, second = _rasff_notifications()[:2], _rasff_notifications()[2:]
    pages = {1: _rasff_answer(first, total_pages=2), 2: (503, b'{"error": "unavailable"}')}
    res, _ = run_rasff(lambda body: pages[body["parameters"]["pageNumber"]])
    assert res["status"] == "failed" and "503" in res["error"], res
    with session_factory() as s:
        assert {r.reference for r in _rows(s, RegulationItem, "rasff_honey")} == {"2026.7712", "2026.7604"}
    pages[2] = _rasff_answer(second, total_pages=2)
    res, bodies = run_rasff(lambda body: pages[body["parameters"]["pageNumber"]])
    assert bodies[0]["ecValidDateFrom"] == "01-01-2020 00:00:00", bodies
    assert [b["parameters"]["pageNumber"] for b in bodies] == [1, 2]           # page 1 holds nothing new: read on
    assert res["status"] == "success" and res["new"] == 1, res
    with session_factory() as s:
        assert {r.reference for r in _rows(s, RegulationItem, "rasff_honey")} == {"2026.7712", "2026.7604", "2026.7420"}
    # once the back-fill is complete, runs are incremental again
    res, bodies = run_rasff(lambda body: pages[body["parameters"]["pageNumber"]])
    assert res["status"] == "no_change" and [b["parameters"]["pageNumber"] for b in bodies] == [1], res
    assert bodies[0]["ecValidDateFrom"] == "03-10-2026 00:00:00"


def test_rasff_shape_change_fails_run(run_with_routes, session_factory, pin_today):
    res = run_with_routes("rasff_honey", {RASFF: (200, b'{"content": [{"notifId": 1}], "totalPages": 1}', "application/json")})
    assert res["status"] == "failed" and "RASFF response shape changed" in res["error"], res
    with session_factory() as s:
        assert _rows(s, RegulationItem, "rasff_honey") == []


def test_all_eu_collectors_registered():
    from paladex.collectors.registry import all_collectors

    keys = {c.key for c in all_collectors(refresh=True)}
    assert {"eurostat_comext", "ec_taxud_weekly", "ec_honey_market", "rasff_honey"} <= keys
