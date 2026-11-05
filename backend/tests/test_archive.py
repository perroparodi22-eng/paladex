"""Historical archive (Milestone 7c): year comparisons, trade and production by year, news by date
range, supplier quotes over time and the revision history of a series.

Rows are written through the same append-only writer the collectors use (`services.ingest.record`);
the numbers are illustrative.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta

from sqlalchemy import select

from paladex.api.common import set_setting
from paladex.models import (
    NewsArticle,
    PriceObservation,
    ProductionStat,
    Source,
    SupplierQuote,
    TradeFlowObservation,
    utcnow,
)
from paladex.services import ingest


def src(db, key: str) -> Source:
    return db.scalars(select(Source).where(Source.key == key)).one()


def month(label: str) -> tuple[date, date]:
    y, m = int(label[:4]), int(label[5:7])
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def unit_value(db, label: str, eur_per_kg: float, kg: float | None, *, origin="ARG", market="EU27",
               source="eurostat_comext", demo=False):
    s, e = month(label)
    _, row = ingest.record(
        db, PriceObservation, source_id=src(db, source).id, is_demo=demo,
        series_key=f"import_unit_value|{origin}|{market}|{label}", price_type="import_unit_value",
        variety="unspecified", origin_iso3=origin, market_iso3=market, price_value=eur_per_kg, currency="EUR",
        unit="kg", price_per_kg=eur_per_kg, volume_kg=kg, period_start=s, period_end=e, period_label=label,
        frequency="M", data_status="published", reliability="official", published_at=e + timedelta(days=45),
        source_url=f"https://ec.europa.eu/eurostat/comext/{label}",
    )
    db.flush()
    return row


def trade(db, label: str, kg: float, *, reporter="EU27", partner="ARG", source="eurostat_comext", freq="M"):
    if freq == "A":
        s, e = date(int(label), 1, 1), date(int(label), 12, 31)
    else:
        s, e = month(label)
    _, row = ingest.record(
        db, TradeFlowObservation, source_id=src(db, source).id, series_key=f"t|{reporter}|{partner}|import|{label}",
        reporter_iso3=reporter, partner_iso3=partner, flow="import", net_weight_kg=kg, value=kg * 2.2,
        currency="EUR", value_basis="CIF", period_start=s, period_end=e, period_label=label, frequency=freq,
        data_status="published", reliability="official", published_at=e + timedelta(days=45),
        source_url="https://ec.europa.eu/eurostat/comext",
    )
    db.flush()
    return row


def production(db, year: int, tonnes: float, *, country="ARG", flag="E"):
    _, row = ingest.record(
        db, ProductionStat, source_id=src(db, "faostat").id, series_key=f"prod|{country}|{year}", country_iso3=country,
        metric="production", value=tonnes, unit="t", flag_raw=flag, period_start=date(year, 1, 1),
        period_end=date(year, 12, 31), period_label=str(year), frequency="A", data_status="estimate",
        reliability="official", published_at=date(year + 1, 12, 20), source_url="https://www.fao.org/faostat/en/#data/QCL",
    )
    db.flush()
    return row


PRICE = {"price_type": "import_unit_value", "origin": "ARG", "variety": "unspecified", "market": "EU27"}


# ---------------------------------------------------------------------------
# Prices: year table and month overlay
# ---------------------------------------------------------------------------


def test_price_years_weighted_and_compared_on_the_same_months(api, db):
    for m, v in ((1, 2.00), (2, 2.10), (3, 2.20)):
        unit_value(db, f"2025-{m:02d}", v, 1_000_000)
    for m in range(4, 13):
        unit_value(db, f"2025-{m:02d}", 2.00, 1_000_000)
    unit_value(db, "2026-01", 2.20, 3_000_000)          # weighted: the bigger month counts more
    unit_value(db, "2026-02", 2.40, 1_000_000)
    db.commit()
    r = api.get("/api/archive/prices", params=PRICE).json()
    assert r["available"] and len(r["series"]) == 1
    sel = r["selected"]
    assert sel["source"]["key"] == "eurostat_comext" and sel["currency"] == "EUR" and sel["freq"] == "M"
    years = {y["year"]: y for y in sel["years"]}
    y25, y26 = years[2025], years[2026]
    assert y25["periods"] == 12 and y25["complete"] and y25["weighting"] == "volume"
    assert abs(y25["average"] - (2.00 + 2.10 + 2.20 + 9 * 2.00) / 12) < 1e-4
    assert y26["periods"] == 2 and not y26["complete"]
    assert abs(y26["average"] - (2.20 * 3 + 2.40) / 4) < 1e-4
    # January-February 2026 against January-February 2025 only (never against the full year)
    jf25 = (2.00 + 2.10) / 2
    assert y26["change_periods"] == 2 and y26["change_same_periods_only"]
    assert abs(y26["change_pct"] - round(((2.20 * 3 + 2.40) / 4 - jf25) / jf25 * 100, 2)) < 0.01
    assert y26["max"] == {"period_label": "2026-02", "value": 2.4}
    assert y26["published_at"] and y26["source_url"].endswith("2026-02")

    ov = sel["overlay"]
    assert ov["latest_year"] == 2026 and [y["year"] for y in ov["years"]] == [2026, 2025, 2024]
    pts26 = ov["years"][0]["points"]
    assert pts26[0]["value"] == 2.2 and pts26[1]["value"] == 2.4 and pts26[2] is None     # no filled months
    assert ov["years"][2]["months"] == 0 and all(p is None for p in ov["years"][2]["points"])


def test_price_archive_leaves_out_small_consignments_and_demo_rows(api, db):
    unit_value(db, "2026-01", 2.0, 400_000)
    unit_value(db, "2026-02", 9.0, 2_000)                # 2 t: not a bulk price
    unit_value(db, "2026-03", 5.0, 400_000, source="demo", demo=True)
    db.commit()
    sel = api.get("/api/archive/prices", params=PRICE).json()["selected"]
    assert [y["periods"] for y in sel["years"]] == [1]
    with_small = api.get("/api/archive/prices", params={**PRICE, "small": True}).json()["selected"]
    assert with_small["years"][0]["periods"] == 2
    set_setting(db, "show_demo", True)
    db.commit()
    r = api.get("/api/archive/prices", params=PRICE).json()
    assert any(s["is_demo"] for s in r["series"])        # demo shown only when switched on, as its own series


def test_price_options_and_default_series(api, db):
    unit_value(db, "2026-01", 2.0, 400_000)
    unit_value(db, "2026-01", 2.3, 300_000, market="DEU")
    db.commit()
    o = api.get("/api/archive/prices/options").json()
    assert o["price_type"] == "import_unit_value"
    assert o["default"] == {"price_type": "import_unit_value", "origin": "ARG", "variety": "unspecified",
                            "market": "EU27", "color_grade": None}
    assert {(c["origin"], c["market"]) for c in o["combos"]} == {("ARG", "EU27"), ("ARG", "DEU")}
    assert api.get("/api/archive/prices", params={**PRICE, "origin": "BRA"}).json()["available"] is False
    assert api.get("/api/archive/prices", params={**PRICE, "price_type": "spot"}).status_code == 422


# ---------------------------------------------------------------------------
# Trade and production
# ---------------------------------------------------------------------------


def test_trade_by_year_and_same_months_of_earlier_years(api, db):
    for y, kg in ((2024, 1_000_000), (2025, 1_500_000)):
        for m in range(1, 13):
            trade(db, f"{y}-{m:02d}", kg)
    for m in range(1, 4):
        trade(db, f"2026-{m:02d}", 2_000_000)
    trade(db, "2025", 20_000_000, source="un_comtrade", freq="A")      # another source: never summed
    db.commit()
    r = api.get("/api/archive/trade", params={"reporter": "EU27", "partner": "ARG", "flow": "import"}).json()
    assert r["available"]
    by_src = {s["source"]["key"]: s for s in r["annual"]}
    eu = {p["period_label"]: p for p in by_src["eurostat_comext"]["points"]}
    assert eu["2024"]["net_weight_kg"] == 12_000_000 and eu["2025"]["net_weight_kg"] == 18_000_000
    assert eu["2025"]["change_pct"] == 50.0 and eu["2025"]["summed_from_months"] is True
    assert "2026" not in eu                                             # an incomplete year is no annual total
    assert [p["period_label"] for p in by_src["un_comtrade"]["points"]] == ["2025"]
    ytd = next(s for s in r["ytd"] if s["source"]["key"] == "eurostat_comext")
    assert ytd["through_month"] == 3
    assert [(y["year"], y["net_weight_kg"]) for y in ytd["years"]] == [(2026, 6_000_000), (2025, 4_500_000),
                                                                      (2024, 3_000_000)]
    assert ytd["years"][0]["change_pct"] == 33.33 and ytd["years"][-1]["change_pct"] is None


def test_production_by_year_with_flags(api, db):
    production(db, 2023, 70_000)
    production(db, 2024, 63_000)
    db.commit()
    r = api.get("/api/archive/production", params={"country": "ARG"}).json()
    assert r["available"] and r["metric"] == "production"
    s = r["series"][0]
    assert s["source"]["key"] == "faostat" and s["unit"] == "t"
    assert [(p["year"], p["value"], p["change_pct"], p["flag"]) for p in s["points"]] == [
        (2023, 70_000, None, "E"), (2024, 63_000, -10.0, "E")]
    assert r["countries"][0]["iso3"] == "ARG"
    assert api.get("/api/archive/production", params={"country": "ITA"}).json()["available"] is False


# ---------------------------------------------------------------------------
# News, quotes
# ---------------------------------------------------------------------------


def test_news_by_date_range_with_counts_per_month(api, db):
    s = src(db, "news_bee_culture")
    for i, (when, title) in enumerate(((date(2025, 3, 10), "Argentina honey harvest"),
                                       (date(2025, 3, 20), "Argentina honey exports"),
                                       (date(2026, 1, 5), "EU honey labelling rules"))):
        db.add(NewsArticle(source_id=s.id, url=f"https://example.org/a{i}", canonical_url=f"https://example.org/a{i}",
                           title=title, title_norm=title.lower(), language="en",
                           published_at=utcnow().replace(year=when.year, month=when.month, day=when.day),
                           countries=["ARG"] if "Argentina" in title else ["EU27"], relevance_score=60))
    db.commit()
    r = api.get("/api/archive/news", params={"from": "2025-01-01", "to": "2025-12-31"}).json()
    assert r["total"] == 2 and [m["month"] for m in r["months"]] == ["2025-03"] and r["months"][0]["count"] == 2
    assert r["items"][0]["title"] == "Argentina honey exports"            # newest first
    assert r["archive"]["articles"] == 3 and r["archive"]["oldest"].startswith("2025-03-10")
    assert api.get("/api/archive/news", params={"q": "labelling"}).json()["total"] == 1
    assert api.get("/api/archive/news", params={"from": "2026-02-01", "to": "2026-01-01"}).status_code == 422


def test_quotes_history_includes_archived_and_never_mixes_terms(api, db):
    empty = api.get("/api/archive/quotes").json()
    assert empty["available"] is False and empty["items"] == [] and empty["total_all"] == 0

    def quote(day: date, price: float, *, currency="USD", incoterm="FOB", archived=False, supplier="Apicola Sur"):
        db.add(SupplierQuote(supplier_name=supplier, origin_iso3="ARG", variety="polyflora", price_per_kg=price,
                             currency=currency, incoterm=incoterm, date_received=day, archived=archived))

    quote(date(2025, 2, 1), 3.10, archived=True)
    quote(date(2025, 9, 1), 3.30)
    quote(date(2025, 10, 1), 2.95, currency="EUR", incoterm="CIF", supplier="Miel del Plata")
    quote(date(2026, 3, 1), 3.60)
    db.commit()
    r = api.get("/api/archive/quotes", params={"origin": "ARG"}).json()
    assert r["available"] and r["total"] == 4
    assert [q["date_received"] for q in r["items"]] == ["2026-03-01", "2025-10-01", "2025-09-01", "2025-02-01"]
    assert r["items"][-1]["archived"] is True and r["items"][0]["data_status"] == "user_entered"
    s2025 = [s for s in r["summary"] if s["year"] == 2025]
    assert {(s["currency"], s["incoterm"], s["quotes"]) for s in s2025} == {("USD", "FOB", 2), ("EUR", "CIF", 1)}
    usd = next(s for s in s2025 if s["currency"] == "USD")
    assert usd["min"] == 3.1 and usd["max"] == 3.3 and usd["average"] == 3.2


# ---------------------------------------------------------------------------
# Revisions
# ---------------------------------------------------------------------------


def test_revisions_show_superseded_and_withdrawn_values(api, db):
    unit_value(db, "2026-01", 2.00, 400_000)
    unit_value(db, "2026-02", 2.10, 400_000)
    unit_value(db, "2026-02", 2.15, 410_000)          # the source revised February
    unit_value(db, "2026-03", 2.30, 400_000)
    ingest.retire(db, PriceObservation, source_id=src(db, "eurostat_comext").id,
                  series_key="import_unit_value|ARG|EU27|2026-03")
    db.commit()
    r = api.get("/api/archive/revisions", params={"kind": "price", **PRICE}).json()
    assert r["counts"] == {"periods": 3, "stored_values": 4, "revised": 1, "withdrawn": 1}
    by = {p["period_label"]: p for p in r["periods"]}
    feb = by["2026-02"]
    assert feb["status"] == "revised" and [v["value"] for v in feb["revisions"]] == [2.1, 2.15]
    assert [v["is_current"] for v in feb["revisions"]] == [False, True]
    assert feb["revisions"][1]["change_pct"] == 2.38 and feb["revisions"][1]["supersedes_id"] == feb["revisions"][0]["id"]
    assert all(v["collected_at"] for v in feb["revisions"])
    assert by["2026-03"]["status"] == "withdrawn" and "2026-01" not in by

    series = api.get("/api/archive/prices", params=PRICE).json()["selected"]["id"]
    one = api.get("/api/archive/revisions", params={"kind": "price", **PRICE, "series": series}).json()
    assert one["counts"]["revised"] == 1
    assert api.get("/api/archive/revisions", params={"kind": "price", **PRICE, "series": "nope"}).json()["counts"]["periods"] == 0
    assert api.get("/api/archive/revisions", params={"kind": "price"}).status_code == 422


def test_revisions_of_trade_and_production(api, db):
    trade(db, "2026-01", 1_000_000)
    trade(db, "2026-01", 1_100_000)
    production(db, 2024, 63_000)
    production(db, 2024, 64_500, flag="A")
    db.commit()
    t = api.get("/api/archive/revisions", params={"kind": "trade", "reporter": "EU27", "partner": "ARG"}).json()
    assert t["counts"]["revised"] == 1 and [v["value"] for v in t["periods"][0]["revisions"]] == [1_000_000, 1_100_000]
    p = api.get("/api/archive/revisions", params={"kind": "production", "country": "ARG"}).json()
    assert [v["flag"] for v in p["periods"][0]["revisions"]] == ["E", "A"]
