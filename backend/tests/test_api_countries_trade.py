"""/api/trade/* and /api/countries*: international trade and country intelligence.

Covers: empty database (honest empty states with expected providers), leaders from World rows
vs summed partners, exporter- vs importer-declared flows never merged (mirror basis), annual
totals from 12 months only, one source per figure, partner shares (world total / partner sum,
others, not-allocated), FX-missing values, series per source with discrepancies, the country
profile assembly (sections, missing list, price types kept apart, news dedup), demo filtering
and input validation.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from paladex.collectors.base import month_bounds, year_bounds
from paladex.models import (
    NewsArticle,
    PriceObservation,
    ProductionStat,
    RegulationItem,
    Source,
    TradeFlowObservation,
    utcnow,
)
from paladex.services import ingest

Y = date.today().year - 1          # latest complete calendar year in these fixtures


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def make_source(db, key: str, category: str = "trade", *, reliability: str = "official",
                country: str | None = None, publisher: str | None = None) -> Source:
    s = Source(key=key, name=f"Source {key}", publisher=publisher or f"Publisher {key}",
               homepage="https://example.org", kind="api", reliability=reliability, category=category,
               country_iso3=country, expected_max_age_days=400)
    db.add(s)
    db.flush()
    return s


def trade(db, src: Source, reporter: str, partner: str, year: int, kg: float | None, *, flow: str = "import",
          usd: float | None = "auto", currency: str = "USD", value: float | None = "auto", month: int | None = None,
          is_demo: bool = False, status: str = "published") -> TradeFlowObservation:
    if month is None:
        start, end = year_bounds(year)
        label, freq = str(year), "A"
    else:
        start, end = month_bounds(year, month)
        label, freq = f"{year}-{month:02d}", "M"
    if value == "auto":
        value = None if kg is None else kg * 3
    if usd == "auto":
        usd = value if currency == "USD" else None
    _, row = ingest.record(
        db, TradeFlowObservation, source_id=src.id, is_demo=is_demo,
        series_key=f"{reporter}|{partner}|{flow}|{label}", hs_code="0409", reporter_iso3=reporter,
        partner_iso3=partner, flow=flow, net_weight_kg=kg, value=value, currency=currency, usd_value=usd,
        value_basis="CIF" if flow == "import" else "FOB",
        unit_value_per_kg=(value / kg) if value and kg else None,
        period_start=start, period_end=end, period_label=label, frequency=freq,
        published_at=end + timedelta(days=60), source_url=f"https://example.org/{src.key}",
        data_status="demo" if is_demo else status, reliability="demo" if is_demo else src.reliability,
    )
    return row


def production(db, src: Source, iso3: str, year: int, value: float, *, metric: str = "production", unit: str = "t",
               status: str = "published", is_demo: bool = False):
    start, end = year_bounds(year)
    ingest.record(
        db, ProductionStat, source_id=src.id, is_demo=is_demo, series_key=f"{iso3}|{metric}|{year}",
        country_iso3=iso3, metric=metric, value=value, unit=unit, period_start=start, period_end=end,
        period_label=str(year), frequency="A", published_at=end + timedelta(days=200),
        data_status="demo" if is_demo else status, reliability="demo" if is_demo else src.reliability,
        flag_raw="E" if status == "estimate" else "A",
    )


def price(db, src: Source, origin: str, price_type: str, month_back: int, value: float, *, variety: str = "polyflora",
          market: str = "USA", is_demo: bool = False):
    d = date.today().replace(day=1)
    y, m = d.year, d.month - month_back
    while m <= 0:
        m += 12
        y -= 1
    start, end = month_bounds(y, m)
    ingest.record(
        db, PriceObservation, source_id=src.id, is_demo=is_demo,
        series_key=f"{price_type}|{origin}|{variety}|{market}|{y}-{m:02d}",
        price_type=price_type, origin_iso3=origin, origin_label=origin, market_iso3=market, variety=variety,
        price_value=value, currency="USD", unit="kg", price_per_kg=value, usd_per_kg=value, eur_per_kg=value / 1.1,
        period_start=start, period_end=end, period_label=f"{y}-{m:02d}", frequency="M", published_at=end,
        data_status="demo" if is_demo else "published", reliability="demo" if is_demo else src.reliability,
    )


def news(db, src: Source, title: str, countries: list[str], *, days_ago: float = 2, duplicate_of: int | None = None,
         is_demo: bool = False) -> NewsArticle:
    url = f"https://news.example.org/{abs(hash((title, days_ago)))}"
    a = NewsArticle(source_id=src.id, url=url, canonical_url=url, title=title, title_norm=title.lower(),
                    publisher="Honey Times", language="en", published_at=utcnow() - timedelta(days=days_ago),
                    countries=countries, relevance_score=70, duplicate_of_id=duplicate_of, is_demo=is_demo)
    db.add(a)
    db.flush()
    return a


def get(api, path: str, **params) -> dict:
    r = api.get(path, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def by_iso(rows: list[dict]) -> dict[str, dict]:
    return {r["iso3"]: r for r in rows}


def show_demo(api, on: bool = True):
    assert api.put("/api/settings", json={"show_demo": on}).status_code == 200


# ---------------------------------------------------------------------------
# empty database
# ---------------------------------------------------------------------------


def test_empty_database_is_honest(api):
    f = get(api, "/api/trade/facets")
    assert f["total_rows"] == 0 and f["reporters"] == [] and f["years"] == []
    assert f["default_year"] == {"import": None, "export": None}
    assert {p["key"] for p in f["providers"]} >= {"un_comtrade", "eurostat_comext"}
    assert all(p["key"] != "demo" for p in f["providers"])

    for flow in ("import", "export"):
        d = get(api, "/api/trade/leaders", flow=flow)
        assert d["rows"] == [] and d["year"] is None and d["providers"]
    s = get(api, "/api/trade/series", reporter="ITA", flow="import")
    assert s["available"] is False and s["series"] == []
    fl = get(api, "/api/trade/flows", reporter="ITA", flow="import")
    assert fl["available"] is False and fl["rows"] == [] and fl["year"] is None

    c = get(api, "/api/countries")
    assert len(c["countries"]) > 50 and len(c["priority"]) == 20
    ita = by_iso(c["countries"])["ITA"]
    assert ita["m49"] == 380 and ita["priority"] is True and ita["lat"] is not None
    assert ita["metrics"]["exports"] is None and ita["metrics"]["production"] is None
    assert ita["available"]["context"] is True          # curated background exists
    assert not any(v for k, v in ita["available"].items() if k != "context")
    assert c["metrics"]["exports"]["countries"] == 0

    p = get(api, "/api/countries/ARG")
    assert p["country"]["name_it"] == "Argentina"
    assert {m["key"] for m in p["missing"]} == {"production", "exports", "imports", "prices", "news", "regulations"}
    exports_missing = next(m for m in p["missing"] if m["key"] == "exports")
    assert exports_missing["providers"][0]["key"] == "un_comtrade"     # global declared data first
    assert all(pr["key"] != "usda_fas_gats" for pr in exports_missing["providers"])  # US-only source left out
    # curated context is labelled as background, never as collected data
    assert p["context"]["available"] is True and p["context"]["is_collected_data"] is False
    assert "non dati raccolti" in p["context"]["label_it"]
    assert p["is_demo"] is False


# ---------------------------------------------------------------------------
# leaders
# ---------------------------------------------------------------------------


def test_leaders_world_row_vs_summed_partners(api, db):
    src = make_source(db, "un_comtrade_t")
    # DEU publishes a World total that differs from the sum of its partners (confidential trade)
    trade(db, src, "DEU", "WLD", Y, 80_000_000, usd=240_000_000)
    trade(db, src, "DEU", "UKR", Y, 50_000_000)
    trade(db, src, "DEU", "MEX", Y, 20_000_000)
    trade(db, src, "DEU", "WLD", Y - 1, 64_000_000, usd=192_000_000)
    # USA has only the partner breakdown
    trade(db, src, "USA", "ARG", Y, 60_000_000, usd=180_000_000)
    trade(db, src, "USA", "IND", Y, 55_000_000, usd=110_000_000)
    trade(db, src, "USA", "ARG", Y - 1, 50_000_000)
    trade(db, src, "USA", "IND", Y - 1, 50_000_000)
    # an aggregate reporter is never ranked as a country
    trade(db, src, "EU27", "WLD", Y, 200_000_000)
    db.commit()

    d = get(api, "/api/trade/leaders", flow="import", year=Y)
    assert [r["iso3"] for r in d["rows"]] == ["USA", "DEU"]
    usa, deu = d["rows"]
    assert usa["rank"] == 1 and deu["rank"] == 2
    assert deu["net_weight_kg"] == 80_000_000 and deu["summed_from_partners"] is False and deu["partners_count"] is None
    assert deu["usd_value"] == 240_000_000 and deu["unit_value_usd_per_kg"] == 3.0
    assert deu["yoy_volume_pct"] == 25.0 and deu["prev"]["year"] == Y - 1
    assert usa["net_weight_kg"] == 115_000_000 and usa["summed_from_partners"] is True and usa["partners_count"] == 2
    assert usa["usd_value"] == 290_000_000
    assert usa["unit_value_usd_per_kg"] == pytest.approx(290 / 115, abs=1e-3)
    assert usa["yoy_volume_pct"] == 15.0
    # provenance on every row
    for r in d["rows"]:
        assert r["source"]["key"] == "un_comtrade_t" and r["period_label"] == str(Y)
        assert r["published_at"] and r["source_url"] and r["data_status"] == "published" and r["is_demo"] is False
    assert d["sources"][0]["key"] == "un_comtrade_t" and d["mixed_sources"] is False
    assert d["summed_from_partners"] == 1

    v = get(api, "/api/trade/leaders", flow="import", year=Y, metric="value")
    assert [r["iso3"] for r in v["rows"]] == ["USA", "DEU"]
    assert d["default_year"] == Y and Y in d["available_years"]


def test_exporter_and_importer_declarations_are_never_merged(api, db):
    src = make_source(db, "un_comtrade_t")
    trade(db, src, "ARG", "WLD", Y, 70_000_000, flow="export")
    trade(db, src, "USA", "ARG", Y, 60_000_000)
    trade(db, src, "ITA", "ARG", Y, 4_000_000)
    trade(db, src, "USA", "ARG", Y - 1, 40_000_000)
    trade(db, src, "ITA", "ARG", Y - 1, 4_000_000)
    trade(db, src, "USA", "VNM", Y, 30_000_000)
    db.commit()

    declared = get(api, "/api/trade/leaders", flow="export", year=Y)
    assert [(r["iso3"], r["net_weight_kg"]) for r in declared["rows"]] == [("ARG", 70_000_000)]
    assert declared["basis"] == "declared"

    mirror = get(api, "/api/trade/leaders", flow="export", year=Y, basis="mirror")
    rows = by_iso(mirror["rows"])
    assert mirror["basis"] == "mirror" and set(rows) == {"ARG", "VNM"}
    assert rows["ARG"]["net_weight_kg"] == 64_000_000          # importers' declarations only, never + 70 000 t
    assert rows["ARG"]["reporters"] == ["USA", "ITA"] and rows["ARG"]["reporters_count"] == 2
    assert rows["ARG"]["yoy_volume_pct"] == pytest.approx(45.45, abs=0.01)   # like-for-like: 64 vs 44
    assert rows["VNM"]["yoy_volume_pct"] is None
    assert {r["iso3"] for r in mirror["reporters"]} == {"USA", "ITA"}

    assert api.get("/api/trade/leaders", params={"flow": "import", "basis": "mirror"}).status_code == 422


def test_monthly_rows_need_twelve_months_and_one_source_per_figure(api, db):
    comtrade = make_source(db, "un_comtrade_t")
    eurostat = make_source(db, "eurostat_t")
    # ITA: monthly only (Eurostat, EUR with stored USD conversion), 12 months -> annual total
    for m in range(1, 13):
        trade(db, eurostat, "ITA", "WLD", Y, 1_000_000, currency="EUR", value=3_000_000, usd=3_300_000, month=m)
    # FRA: only 9 months -> incomplete, never ranked
    for m in range(1, 10):
        trade(db, eurostat, "FRA", "WLD", Y, 2_000_000, currency="EUR", value=6_000_000, usd=6_600_000, month=m)
    # DEU: Comtrade annual AND Eurostat monthly -> one source (annual) is used, never the sum
    trade(db, comtrade, "DEU", "WLD", Y, 90_000_000)
    for m in range(1, 13):
        trade(db, eurostat, "DEU", "WLD", Y, 9_000_000, currency="EUR", value=27_000_000, usd=29_700_000, month=m)
    db.commit()

    d = get(api, "/api/trade/leaders", flow="import", year=Y)
    rows = by_iso(d["rows"])
    assert set(rows) == {"DEU", "ITA"}
    assert rows["ITA"]["summed_from_months"] is True and rows["ITA"]["months_count"] == 12
    assert rows["ITA"]["net_weight_kg"] == 12_000_000 and rows["ITA"]["usd_value"] == 39_600_000
    assert rows["ITA"]["value"] == 36_000_000 and rows["ITA"]["currency"] == "EUR"
    assert rows["ITA"]["frequency"] == "M" and rows["ITA"]["period_label"] == str(Y)
    assert rows["DEU"]["net_weight_kg"] == 90_000_000 and rows["DEU"]["source"]["key"] == "un_comtrade_t"
    assert d["mixed_sources"] is True
    assert [(i["iso3"], i["months_count"]) for i in d["incomplete"]] == [("FRA", 9)]

    # series: one line per source for DEU, disagreement reported, not resolved
    s = get(api, "/api/trade/series", reporter="DEU", flow="import", freq="A")
    assert {x["source"]["key"] for x in s["series"]} == {"un_comtrade_t", "eurostat_t"}
    euro = next(x for x in s["series"] if x["source"]["key"] == "eurostat_t")
    assert euro["points"][0]["summed_from_months"] is True and euro["points"][0]["net_weight_kg"] == 108_000_000
    assert s["discrepancies"] and s["discrepancies"][0]["period_label"] == str(Y)
    # FRA annual series excludes the incomplete year and says so
    sf = get(api, "/api/trade/series", reporter="FRA", flow="import", freq="A")
    assert sf["series"] == [] and sf["excluded_partial"][0]["months_count"] == 9
    sm = get(api, "/api/trade/series", reporter="FRA", flow="import", freq="M")
    assert len(sm["series"][0]["points"]) == 9


def test_fx_missing_value_is_not_guessed(api, db):
    src = make_source(db, "eurostat_t")
    trade(db, src, "ESP", "WLD", Y, 5_000_000, currency="EUR", value=15_000_000, usd=None)
    db.commit()
    row = get(api, "/api/trade/leaders", flow="import", year=Y)["rows"][0]
    assert row["usd_value"] is None and row["fx_missing"] is True and row["unit_value_usd_per_kg"] is None
    assert row["value"] == 15_000_000 and row["currency"] == "EUR"


# ---------------------------------------------------------------------------
# flows
# ---------------------------------------------------------------------------


def test_flows_shares_others_and_unallocated(api, db):
    src = make_source(db, "un_comtrade_t")
    trade(db, src, "DEU", "WLD", Y, 100_000_000, usd=300_000_000)
    trade(db, src, "DEU", "UKR", Y, 60_000_000, usd=150_000_000)
    trade(db, src, "DEU", "MEX", Y, 30_000_000, usd=120_000_000)
    trade(db, src, "DEU", "EXTRA_EU", Y, 90_000_000)     # partner group: never a partner row
    trade(db, src, "DEU", "UKR", Y - 1, 40_000_000)
    db.commit()

    f = get(api, "/api/trade/flows", reporter="DEU", flow="import", year=Y, top=1)
    assert f["available"] is True and f["share_basis"] == "world_total"
    assert [r["iso3"] for r in f["rows"]] == ["UKR"]
    ukr = f["rows"][0]
    assert ukr["share_volume_pct"] == 60.0 and ukr["share_value_pct"] == 50.0
    assert ukr["unit_value_usd_per_kg"] == 2.5 and ukr["yoy_volume_pct"] == 50.0
    assert f["others"] == {"count": 1, "net_weight_kg": 30_000_000, "usd_value": 120_000_000,
                           "share_volume_pct": 30.0, "share_value_pct": 40.0}
    assert f["unallocated"]["net_weight_kg"] == 10_000_000 and f["unallocated"]["share_volume_pct"] == 10.0
    assert f["total"]["net_weight_kg"] == 100_000_000 and f["partners_count"] == 2
    assert f["source"]["key"] == "un_comtrade_t" and f["period_label"] == str(Y) and f["freshness"]["status"]

    # Partner sum when no World row; default year = latest complete year
    trade(db, src, "USA", "ARG", Y, 75_000_000)
    trade(db, src, "USA", "IND", Y, 25_000_000)
    db.commit()
    u = get(api, "/api/trade/flows", reporter="USA", flow="import")
    assert u["year"] == Y and u["share_basis"] == "partner_sum" and u["unallocated"] is None
    assert [(r["iso3"], r["share_volume_pct"]) for r in u["rows"]] == [("ARG", 75.0), ("IND", 25.0)]
    assert u["total"]["summed_from_partners"] is True

    assert api.get("/api/trade/flows", params={"reporter": "DEU", "flow": "transit"}).status_code == 422
    assert api.get("/api/trade/series", params={"reporter": "DEU", "freq": "Q"}).status_code == 422


# ---------------------------------------------------------------------------
# countries
# ---------------------------------------------------------------------------


def test_countries_list_headline_metrics(api, db):
    trade_src = make_source(db, "un_comtrade_t")
    prod_src = make_source(db, "faostat_t", "production")
    news_src = make_source(db, "news_t", "news", reliability="trade_press")
    trade(db, trade_src, "ARG", "WLD", Y, 70_000_000, flow="export")
    trade(db, trade_src, "ARG", "WLD", Y - 1, 60_000_000, flow="export")
    production(db, prod_src, "ARG", Y - 1, 74_000)
    production(db, prod_src, "CHN", Y - 1, 460_000, status="estimate")
    production(db, prod_src, "CHN", Y - 1, 9_000_000, metric="colonies", unit="number")
    news(db, news_src, "Argentina honey exports rise", ["ARG"])
    news(db, news_src, "Old story", ["ARG"], days_ago=60)
    db.commit()

    c = get(api, "/api/countries")
    arg = by_iso(c["countries"])["ARG"]
    assert arg["metrics"]["exports"]["net_weight_kg"] == 70_000_000 and arg["metrics"]["exports"]["year"] == Y
    assert arg["metrics"]["exports"]["source"]["key"] == "un_comtrade_t"
    assert arg["metrics"]["exports"]["yoy_volume_pct"] == pytest.approx(16.67, abs=0.01)
    assert arg["metrics"]["production"]["value_t"] == 74_000 and arg["metrics"]["production"]["year"] == Y - 1
    assert arg["metrics"]["news_30d"]["count"] == 1
    assert arg["available"]["exports"] and arg["available"]["production"] and arg["available"]["news"]
    assert not arg["available"]["imports"] and not arg["available"]["prices"]
    chn = by_iso(c["countries"])["CHN"]
    assert chn["metrics"]["production"]["value_t"] == 460_000          # colonies never read as tonnes
    assert chn["metrics"]["production"]["data_status"] == "estimate"
    assert c["metrics"]["exports"]["countries"] == 1 and c["metrics"]["production"]["countries"] == 2
    # the importers of ARG make it "available according to partners" only when they declare it
    assert arg["available"]["exports_mirror"] is False


def test_country_profile_assembly(api, db):
    comtrade = make_source(db, "un_comtrade_t")
    fao = make_source(db, "faostat_t", "production")
    make_source(db, "nass_t", "production", country="USA")
    usda = make_source(db, "usda_prices_t", "prices", country="USA")
    eu = make_source(db, "eurostat_prices_t", "prices")
    news_src = make_source(db, "news_t", "news", reliability="trade_press")
    reg_src = make_source(db, "reg_t", "regulation")

    production(db, fao, "ARG", Y - 2, 70_000)
    production(db, fao, "ARG", Y - 1, 74_000, status="estimate")
    production(db, fao, "ARG", Y - 1, 3_000_000, metric="colonies", unit="number")
    # importers declare ARG honey (mirror); ARG itself declares nothing
    trade(db, comtrade, "USA", "ARG", Y, 60_000_000)
    trade(db, comtrade, "USA", "IND", Y, 40_000_000)
    # two price types for ARG origin, never mixed
    for mb, v in ((3, 3.0), (2, 3.1), (1, 3.2)):
        price(db, usda, "ARG", "wholesale_bulk", mb, v)
    price(db, eu, "ARG", "import_unit_value", 2, 3.6, market="DEU", variety="unspecified")
    first = news(db, news_src, "Argentine honey harvest", ["ARG", "URY"])
    news(db, news_src, "Argentine honey harvest (copy)", ["ARG"], duplicate_of=first.id)
    news(db, news_src, "Ukraine only", ["UKR"])
    news(db, news_src, "Argentine honey harvest", ["ARG"], days_ago=3)          # same title: deduplicated
    db.add(RegulationItem(source_id=reg_src.id, jurisdiction="US", doc_type="antidumping", reference="A-357-823",
                          title="Raw honey from Argentina: antidumping order", status="in_force",
                          published_at=date(Y, 6, 1), url="https://example.org/fr", countries=["ARG"]))
    db.add(RegulationItem(source_id=reg_src.id, jurisdiction="EU", doc_type="directive", reference="32024L1438",
                          title="Breakfast directive", url="https://example.org/eu", countries=[]))
    db.commit()

    p = get(api, "/api/countries/arg")
    assert p["country"]["iso3"] == "ARG"
    # production: one series per metric/unit/source, statuses preserved
    metrics = {m["metric"]: m for m in p["production"]["metrics"]}
    assert list(metrics) == ["production", "colonies"]
    prod = metrics["production"]["series"][0]
    assert prod["unit"] == "t" and [pt["value"] for pt in prod["points"]] == [70_000, 74_000]
    assert prod["latest"]["data_status"] == "estimate" and prod["latest"]["flag_raw"] == "E"
    # trade: nothing declared by ARG, mirror view from the USA kept apart
    exp = p["trade"]["export"]
    assert exp["available"] is False and exp["latest"] is None and exp["series"] == []
    assert [(r["iso3"], r["net_weight_kg"]) for r in exp["mirror"]["rows"]] == [("USA", 60_000_000)]
    assert p["availability"]["exports"] is False and p["availability"]["exports_mirror"] is True
    # prices grouped by type, latest per series
    groups = {g["price_type"]: g for g in p["prices"]["groups"]}
    assert list(groups) == ["wholesale_bulk", "import_unit_value"]
    assert groups["wholesale_bulk"]["rows"][0]["price_value"] == 3.2
    assert groups["wholesale_bulk"]["rows"][0]["observations"] == 3
    assert groups["import_unit_value"]["rows"][0]["market_iso3"] == "DEU"
    assert groups["wholesale_bulk"]["link"] == "/prezzi?tipo=wholesale_bulk&origini=ARG"
    # news: mentions only, duplicates and same-title copies removed
    assert [n["title"] for n in p["news"]["items"]] == ["Argentine honey harvest"]
    assert p["news"]["count_30d"] == 2
    # regulations mentioning the country (not the EU directive without countries)
    assert [r["reference"] for r in p["regulations"]["items"]] == ["A-357-823"]
    assert p["regulations"]["items"][0]["match"] == "mentioned"
    # missing: exactly what is absent, with the sources that would provide it
    missing = {m["key"]: m for m in p["missing"]}
    assert set(missing) == {"exports", "imports"}
    assert missing["exports"]["partial_alternative"] == "exports_mirror"
    assert missing["imports"]["partial_alternative"] is None
    assert {s["key"] for s in p["sources"]} >= {"faostat_t", "usda_prices_t", "eurostat_prices_t"}

    # USA: its own production source is listed for production; the US price list comes first
    us = get(api, "/api/countries/USA")
    m_us = {m["key"]: m for m in us["missing"]}
    us_prod = [pr["key"] for pr in m_us["production"]["providers"]]
    assert us_prod[0] == "nass_t" and "faostat_t" in us_prod
    # sources about the USA come before sources about other places
    us_prices = [pr["key"] for pr in m_us["prices"]["providers"]]
    assert us_prices.index("usda_prices_t") < us_prices.index("eurostat_prices_t")
    assert us["trade"]["import"]["available"] is True
    assert us["trade"]["import"]["partners"]["rows"][0]["iso3"] == "ARG"
    # ITA: a USA-only production source is never offered as Italy's provider
    it = get(api, "/api/countries/ITA")
    prov = next(m for m in it["missing"] if m["key"] == "production")["providers"]
    assert "nass_t" not in [pr["key"] for pr in prov]

    assert api.get("/api/countries/XXX").status_code == 404
    assert api.get("/api/countries/WLD").status_code == 404


# ---------------------------------------------------------------------------
# demo filtering
# ---------------------------------------------------------------------------


def test_demo_rows_hidden_unless_switched_on(api, db):
    demo = db.query(Source).filter(Source.key == "demo").one()
    real = make_source(db, "un_comtrade_t")
    trade(db, demo, "DEU", "UKR", Y, 21_000_000, is_demo=True)
    trade(db, real, "USA", "WLD", Y, 90_000_000)
    production(db, demo, "CHN", Y - 1, 460_000, is_demo=True)
    news(db, demo, "Demo honey story", ["CHN"], is_demo=True)
    db.commit()

    show_demo(api, False)
    d = get(api, "/api/trade/leaders", flow="import", year=Y)
    assert [r["iso3"] for r in d["rows"]] == ["USA"] and all(not r["is_demo"] for r in d["rows"])
    f = get(api, "/api/trade/facets")
    assert {r["iso3"] for r in f["reporters"]} == {"USA"}
    c = by_iso(get(api, "/api/countries")["countries"])
    assert c["CHN"]["metrics"]["production"] is None and c["CHN"]["available"]["news"] is False
    assert c["DEU"]["metrics"]["imports"] is None
    assert get(api, "/api/countries/CHN")["is_demo"] is False

    show_demo(api, True)
    d = get(api, "/api/trade/leaders", flow="import", year=Y)
    rows = by_iso(d["rows"])
    assert rows["DEU"]["is_demo"] is True and rows["DEU"]["data_status"] == "demo"
    assert rows["USA"]["is_demo"] is False
    c = by_iso(get(api, "/api/countries")["countries"])
    assert c["CHN"]["metrics"]["production"]["is_demo"] is True
    assert c["CHN"]["metrics"]["news_30d"]["count"] == 1
    prof = get(api, "/api/countries/CHN")
    assert prof["is_demo"] is True and prof["news"]["items"][0]["is_demo"] is True


def test_seeded_demo_data_feeds_trade_and_countries(api, db):
    from paladex.services.demo import seed_demo

    seed_demo(db)
    db.commit()
    show_demo(api, True)
    d = get(api, "/api/trade/leaders", flow="import")
    assert {r["iso3"] for r in d["rows"]} == {"USA", "DEU", "ITA"}
    assert all(r["summed_from_partners"] and r["is_demo"] for r in d["rows"])
    assert get(api, "/api/trade/leaders", flow="export")["rows"] == []
    mirror = get(api, "/api/trade/leaders", flow="export", basis="mirror")
    assert {"ARG", "IND", "UKR", "MEX", "HUN"} == {r["iso3"] for r in mirror["rows"]}
    c = get(api, "/api/countries")
    assert c["metrics"]["production"]["countries"] == 6 and c["metrics"]["production"]["is_demo"] is True


def test_eu_aggregate_total_is_extra_eu_never_the_world_row(api, db):
    """Comext WORLD for EU27_2020 counts intra-EU dispatches: the EU's own total is EXTRA_EU."""
    comext = db.query(Source).filter(Source.key == "eurostat_comext").one()
    for m in range(1, 13):
        for partner, kg in (("WLD", 20_000_000), ("EXTRA_EU", 2_000_000), ("USA", 400_000), ("CHE", 300_000)):
            trade(db, comext, "EU27", partner, Y, kg, flow="export", currency="EUR", value=kg * 5, usd=kg * 5.5, month=m)
        # a member state keeps its World row as the total
        for partner, kg in (("WLD", 5_000_000), ("EXTRA_EU", 1_000_000), ("USA", 100_000)):
            trade(db, comext, "ITA", partner, Y, kg, flow="export", currency="EUR", value=kg * 5, usd=kg * 5.5, month=m)
    db.commit()

    f = get(api, "/api/trade/flows", reporter="EU27", flow="export", year=Y)
    assert f["total"]["net_weight_kg"] == 24_000_000                       # 12 x EXTRA_EU, not 12 x WORLD
    assert f["share_basis"] == "extra_eu_total" and f["total_scope"] == "extra_eu"
    rows = by_iso(f["rows"])
    assert rows["USA"]["share_volume_pct"] == 20.0 and rows["CHE"]["share_volume_pct"] == 15.0
    un = f["unallocated"]
    assert un["net_weight_kg"] == 24_000_000 - 8_400_000 and un["share_volume_pct"] == 65.0
    assert un["reason"] == "partners_not_collected" and un["partner_list_complete"] is False

    s = get(api, "/api/trade/series", reporter="EU27", flow="export", freq="A")
    assert s["total_scope"] == "extra_eu"
    assert [p["net_weight_kg"] for p in s["series"][0]["points"]] == [24_000_000]
    sm = get(api, "/api/trade/series", reporter="EU27", flow="export", freq="M")
    assert {p["net_weight_kg"] for p in sm["series"][0]["points"]} == {2_000_000}

    ita = get(api, "/api/trade/flows", reporter="ITA", flow="export", year=Y)
    assert ita["total"]["net_weight_kg"] == 60_000_000 and ita["share_basis"] == "world_total"
    assert ita["total_scope"] == "world" and by_iso(ita["rows"])["USA"]["share_volume_pct"] == 2.0
    assert get(api, "/api/trade/series", reporter="ITA", flow="export")["series"][0]["points"][0]["net_weight_kg"] == 60_000_000


def test_reporters_own_official_statistics_come_first_for_a_complete_year(api, db):
    """Lead request 2026-11-05: Argentina's 2024 exports were ranked on UN Comtrade (78,375 t) although INDEC's
    own complete monthly series gives 85,736 t (Comtrade leaves out INDEC's confidential destinations). For a
    complete year the reporter's own official source wins; the global figure stays listed as an alternative.
    An incomplete national year never replaces a complete global one."""
    comtrade = make_source(db, "un_comtrade_t")
    indec = make_source(db, "ar_indec_t", country="ARG")
    comex = make_source(db, "br_comex_t", country="BRA")
    trade(db, comtrade, "ARG", "WLD", Y, 78_375_280, flow="export")
    for m in range(1, 13):
        w = trade(db, indec, "ARG", "WLD", Y, 7_144_667, flow="export", month=m)        # 85,736 t over 12 months
        w.extra = {"confidential_bucket": {"kg": 613_392.0, "fob_usd": 1_290_000.0}}      # 7,360.7 t in the year
        trade(db, indec, "ARG", "DEU", Y, 2_000_000, flow="export", month=m)
    trade(db, comtrade, "BRA", "WLD", Y, 37_930_750, flow="export")
    for m in range(1, 10):                                                              # 9 months only
        trade(db, comex, "BRA", "WLD", Y, 4_000_000, flow="export", month=m)
    db.commit()

    rows = by_iso(get(api, "/api/trade/leaders", flow="export", year=Y)["rows"])
    assert rows["ARG"]["source"]["key"] == "ar_indec_t" and rows["ARG"]["net_weight_kg"] == 85_736_004
    assert rows["ARG"]["summed_from_months"] is True and rows["ARG"]["months_count"] == 12
    assert rows["BRA"]["source"]["key"] == "un_comtrade_t"            # the national year is incomplete
    flows = get(api, "/api/trade/flows", reporter="ARG", flow="export", year=Y)
    assert flows["source_key"] == "ar_indec_t" and flows["total"]["net_weight_kg"] == 85_736_004
    assert {a["source"]["key"] for a in flows["alternatives"]} == {"ar_indec_t", "un_comtrade_t"}
    profile = get(api, "/api/countries/ARG")
    assert profile["trade"]["export"]["latest"]["source"]["key"] == "ar_indec_t"
    # the reason for the gap with UN Comtrade (destinations under statistical secrecy) stays visible
    series = get(api, "/api/trade/series", reporter="ARG", flow="export", freq="A")
    pts = {x["source"]["key"]: x["points"][-1] for x in series["series"]}
    assert pts["ar_indec_t"]["confidential_kg"] == 7_360_704.0 and pts["un_comtrade_t"]["confidential_kg"] is None
    assert series["discrepancies"] == []          # 9.4 %: under the 10 % flag, the reason is on the point itself


def test_providers_are_only_sources_that_can_fill_the_block(api, db):
    """Review 2026-11-05: Uruguay's export-only collector was listed as a provider of Uruguay's IMPORTS and of its
    prices (it stores neither). A source whose stored data shows it never produces that kind is left out;
    sources with that kind of data, or with nothing stored yet, stay."""
    uy = make_source(db, "uy_exports_t", country="URY")
    comtrade = make_source(db, "un_comtrade_t2")
    make_source(db, "never_run_t", country="URY")
    for m in range(1, 13):
        trade(db, uy, "URY", "USA", Y, 500_000, flow="export", month=m)
    trade(db, comtrade, "ITA", "WLD", Y, 20_000_000)                     # data, but not about Uruguay
    db.commit()
    t = get(api, "/api/countries/URY")["trade"]
    exp_keys = {p["key"] for p in t["providers"]}
    imp_keys = {p["key"] for p in t["providers_import"]}
    assert "uy_exports_t" in exp_keys and "uy_exports_t" not in imp_keys
    assert "un_comtrade_t2" in imp_keys and "never_run_t" in imp_keys       # imports elsewhere; nothing yet
    price_keys = {p["key"] for p in get(api, "/api/countries/URY")["prices"]["providers"]}
    assert "uy_exports_t" not in price_keys and "never_run_t" in price_keys
