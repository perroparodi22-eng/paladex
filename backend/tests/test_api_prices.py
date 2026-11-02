"""Price intelligence API: grouping, conversion, aggregation, demo filtering, discrepancies,
period-on-period changes with gaps, comparison window and CSV export."""
from __future__ import annotations

import csv
import io
from datetime import date

import pytest
from sqlalchemy import select

from paladex.api.common import set_setting
from paladex.collectors.base import month_bounds
from paladex.models import PriceObservation, Source
from paladex.services import ingest

TODAY = date.today()


def _ym(months_back: int) -> str:
    """Label of the month `months_back` months before the current one."""
    idx = TODAY.year * 12 + TODAY.month - 1 - months_back
    return f"{idx // 12}-{idx % 12 + 1:02d}"


@pytest.fixture()
def sources(db):
    a = Source(key="t_usda", name="Test USDA honey report", publisher="USDA AMS (test)", kind="pdf",
               reliability="official", category="prices", expected_max_age_days=40)
    b = Source(key="t_onm", name="Test Osservatorio", publisher="Osservatorio (test)", kind="pdf",
               reliability="industry", category="prices")
    db.add_all([a, b])
    db.flush()
    return a, b


def add_price(db, src, *, period: str, value: float, origin="ARG", variety="polyflora", price_type="wholesale_bulk",
              market="USA", currency="USD", unit="kg", low=None, high=None, color=None, per_kg=None, usd="auto",
              eur="auto", published="auto", demo=False, terms=None, freq="M", source_url=None, variety_raw=None):
    y, m = int(period[:4]), int(period[5:7])
    start, end = month_bounds(y, m)
    per_kg = per_kg if per_kg is not None else ingest.per_kg(value, unit)
    if usd == "auto":
        usd = per_kg if currency == "USD" else per_kg * 1.1
    if eur == "auto":
        eur = per_kg if currency == "EUR" else per_kg / 1.1
    _, row = ingest.record(
        db, PriceObservation, source_id=src.id, is_demo=demo,
        series_key=f"{price_type}|{origin}|{variety}|{color}|{market}|{terms}|{period}",
        price_type=price_type, origin_iso3=origin, origin_label=origin, market_iso3=market, variety=variety,
        variety_raw=variety_raw or variety, color_grade=color, terms=terms, price_value=value, price_low=low,
        price_high=high, currency=currency, unit=unit, price_per_kg=per_kg, usd_per_kg=usd, eur_per_kg=eur,
        period_start=start, period_end=end, period_label=period, frequency=freq,
        published_at=end if published == "auto" else published, source_url=source_url,
        data_status="demo" if demo else "published", reliability="demo" if demo else src.reliability,
    )
    return row


# ---------------------------------------------------------------------------


def test_series_requires_single_price_type_and_groups_lines(api, db, sources):
    usda, onm = sources
    for p, v in (("2026-07", 3.0), ("2026-08", 3.1)):
        add_price(db, usda, period=p, value=v, color="white")
        add_price(db, usda, period=p, value=v - 0.4, color="light amber")
        add_price(db, usda, period=p, value=2.4, origin="UKR", variety="sunflower")
        add_price(db, onm, period=p, value=v + 0.1, market="ITA", currency="EUR")
        add_price(db, usda, period=p, value=1.9, price_type="producer", origin="USA")
    db.commit()

    assert api.get("/api/prices/series").status_code == 422          # never mixes types
    assert api.get("/api/prices/series?price_type=nonsense").status_code == 422

    d = api.get("/api/prices/series?price_type=wholesale_bulk").json()
    keys = {(s["source"]["key"], s["origin_iso3"], s["market_iso3"], s["variety"], s["color_grade"]) for s in d["series"]}
    assert keys == {
        ("t_usda", "ARG", "USA", "polyflora", "white"),
        ("t_usda", "ARG", "USA", "polyflora", "light amber"),
        ("t_usda", "UKR", "USA", "sunflower", None),
        ("t_onm", "ARG", "ITA", "polyflora", None),
    }
    assert all(s["price_type"] == "wholesale_bulk" for s in d["series"])
    assert all(len(s["points"]) == 2 and s["n_points"] == 2 for s in d["series"])
    # priority-country ordering puts Argentina before Ukraine; ids are stable and unique
    assert d["series"][-1]["origin_iso3"] == "UKR"
    assert len({s["id"] for s in d["series"]}) == 4
    ids_again = {s["id"] for s in api.get("/api/prices/series?price_type=wholesale_bulk").json()["series"]}
    assert ids_again == {s["id"] for s in d["series"]}
    # provenance at series and point level
    s0 = d["series"][0]
    assert s0["source"]["name"] and s0["published_at"] and s0["collected_at"] and s0["freshness"]["status"]
    pt = s0["points"][0]
    for k in ("period_label", "period_start", "value", "low", "high", "original", "published_at", "collected_at",
              "source_url", "data_status", "is_demo"):
        assert k in pt
    assert {x["key"] for x in d["sources"]} == {"t_usda", "t_onm"}

    # filters: origin list (repeat or comma), source, colour "not specified"
    d = api.get("/api/prices/series?price_type=wholesale_bulk&origin=UKR&origin=ARG&source=t_onm").json()
    assert [s["source"]["key"] for s in d["series"]] == ["t_onm"]
    d = api.get("/api/prices/series?price_type=wholesale_bulk&origin=ARG,UKR&color_grade=_none").json()
    assert {s["origin_iso3"] for s in d["series"]} == {"ARG", "UKR"} and all(s["color_grade"] is None for s in d["series"])

    prod = api.get("/api/prices/series?price_type=producer").json()
    assert [s["origin_iso3"] for s in prod["series"]] == ["USA"]


def test_currency_conversion_uses_stored_per_kg_fields(api, db, sources):
    usda, onm = sources
    # Published per POUND in USD. Stored normalised values are what the API must use: the EUR
    # figure is deliberately not equal to any FX rate the API could compute itself.
    add_price(db, usda, period="2026-09", value=2.0, low=1.8, high=2.2, unit="lb", per_kg=4.40925, usd=4.40925, eur=4.0)
    # A USD row whose EUR conversion is missing (no FX rate at ingest): EUR value must be null.
    add_price(db, usda, period="2026-09", value=3.0, origin="UKR", variety="sunflower", eur=None)
    # A EUR row: EUR view uses price_per_kg; USD view uses the stored usd_per_kg.
    add_price(db, onm, period="2026-09", value=500.0, unit="100kg", market="ITA", currency="EUR", usd=5.55)
    db.commit()

    def by_origin(currency, **extra):
        d = api.get("/api/prices/series", params={"price_type": "wholesale_bulk", "currency": currency, **extra}).json()
        return {(s["origin_iso3"], s["market_iso3"]): s for s in d["series"]}, d

    eur, meta = by_origin("EUR")
    assert meta["currency"] == "EUR" and meta["unit"] == "kg"
    p = eur[("ARG", "USA")]["points"][0]
    assert p["value"] == 4.0 and p["low"] == pytest.approx(3.6) and p["high"] == pytest.approx(4.4)
    assert p["original"] == {"value": 2.0, "low": 1.8, "high": 2.2, "currency": "USD", "unit": "lb"}
    assert eur[("ARG", "ITA")]["points"][0]["value"] == 5.0          # 500 EUR / 100 kg
    missing = eur[("UKR", "USA")]
    assert missing["points"][0]["value"] is None and missing["points"][0]["original"]["value"] == 3.0
    assert missing["fx_missing_points"] == 1

    usd, _ = by_origin("USD")
    assert usd[("ARG", "USA")]["points"][0]["value"] == pytest.approx(4.40925, abs=1e-4)   # 4 decimals
    assert usd[("ARG", "ITA")]["points"][0]["value"] == 5.55
    assert usd[("UKR", "USA")]["points"][0]["value"] == 3.0

    orig, meta = by_origin("original")
    assert meta["currency"] == "original"
    assert orig[("ARG", "ITA")]["currency"] == "EUR" and orig[("ARG", "ITA")]["points"][0]["value"] == 5.0
    assert orig[("ARG", "USA")]["currency"] == "USD"

    assert api.get("/api/prices/series?price_type=wholesale_bulk&currency=GBP").status_code == 422


def test_quarterly_and_annual_aggregation_never_fills_gaps(api, db, sources):
    usda, _ = sources
    for p, v in (("2025-11", 9.0), ("2026-01", 1.0), ("2026-02", 2.0), ("2026-04", 4.0)):   # March missing
        add_price(db, usda, period=p, value=v, low=v - 0.5, high=v + 0.5)
    db.commit()

    q = api.get("/api/prices/series?price_type=wholesale_bulk&freq=Q").json()["series"][0]
    pts = {p["period_label"]: p for p in q["points"]}
    assert list(pts) == ["2025-Q4", "2026-Q1", "2026-Q2"]
    assert pts["2026-Q1"]["value"] == 1.5 and pts["2026-Q1"]["n_points"] == 2 and pts["2026-Q1"]["expected_points"] == 3
    assert pts["2026-Q1"]["periods"] == ["2026-01", "2026-02"]
    assert pts["2026-Q1"]["low"] == 1.0 and pts["2026-Q1"]["high"] == 2.0
    assert pts["2026-Q2"]["value"] == 4.0 and pts["2026-Q2"]["n_points"] == 1
    assert pts["2026-Q1"]["period_start"] == "2026-01-01" and pts["2026-Q1"]["period_end"] == "2026-03-31"
    assert q["freq"] == "Q" and q["native_frequency"] == "M"

    a = api.get("/api/prices/series?price_type=wholesale_bulk&freq=A").json()["series"][0]
    pts = {p["period_label"]: p for p in a["points"]}
    assert pts["2026"]["value"] == pytest.approx(7 / 3, abs=1e-4)
    assert pts["2026"]["n_points"] == 3 and pts["2026"]["expected_points"] == 12
    assert pts["2025"]["value"] == 9.0 and pts["2025"]["n_points"] == 1

    # monthly: one point per month that exists, nothing for March
    m = api.get("/api/prices/series?price_type=wholesale_bulk&freq=M").json()["series"][0]
    assert [p["period_label"] for p in m["points"]] == ["2025-11", "2026-01", "2026-02", "2026-04"]

    # 'from' is widened to the start of the quarter so the first bucket is complete
    d = api.get("/api/prices/series?price_type=wholesale_bulk&freq=Q&from=2026-02").json()
    assert d["from"] == "2026-01-01"
    assert d["series"][0]["points"][0]["period_label"] == "2026-Q1" and d["series"][0]["points"][0]["n_points"] == 2

    # an annual-only series is never split into months
    add_price(db, usda, period="2024-01", value=2.0, origin="CHN", price_type="producer", freq="A")
    db.commit()
    pr = api.get("/api/prices/series?price_type=producer&freq=M").json()["series"][0]
    assert pr["freq"] == "A" and [p["period_label"] for p in pr["points"]] == ["2024"]
    assert api.get("/api/prices/series?price_type=wholesale_bulk&freq=W").status_code == 422


def test_demo_rows_hidden_unless_enabled(api, db, sources):
    usda, _ = sources
    demo_src = db.scalars(select(Source).where(Source.key == "demo")).one()
    add_price(db, usda, period="2026-09", value=3.0)
    add_price(db, demo_src, period="2026-09", value=9.0, demo=True)       # would be a >10% "discrepancy"
    db.commit()

    d = api.get("/api/prices/series?price_type=wholesale_bulk").json()
    assert [s["source"]["key"] for s in d["series"]] == ["t_usda"]
    assert api.get("/api/prices/facets").json()["demo_rows"] == 0
    assert api.get("/api/prices/observations").json()["total"] == 1
    assert all(r["is_demo"] is False for r in api.get("/api/prices/latest?price_type=wholesale_bulk").json()["rows"])

    set_setting(db, "show_demo", True)
    db.commit()
    d = api.get("/api/prices/series?price_type=wholesale_bulk").json()
    demo = [s for s in d["series"] if s["is_demo"]]
    assert len(d["series"]) == 2 and len(demo) == 1
    assert demo[0]["data_status"] == "demo" and demo[0]["points"][0]["is_demo"] is True
    assert api.get("/api/prices/facets").json()["demo_rows"] == 1
    # demo values are never compared with real ones
    assert d["discrepancies"] == []


def test_discrepancy_detection(api, db, sources):
    usda, onm = sources
    add_price(db, usda, period="2026-09", value=3.00, source_url="https://example.org/usda.pdf")
    add_price(db, onm, period="2026-09", value=3.50)                 # +16.7 % -> flagged
    add_price(db, usda, period="2026-08", value=3.00)
    add_price(db, onm, period="2026-08", value=3.20)                 # +6.7 % -> fine
    add_price(db, onm, period="2026-09", value=9.00, market="ITA")   # other market: not comparable
    add_price(db, onm, period="2026-09", value=9.00, variety="acacia")
    db.commit()

    d = api.get("/api/prices/discrepancies").json()
    assert d["threshold_pct"] == 10 and d["total"] == 1
    item = d["items"][0]
    assert (item["origin_iso3"], item["variety"], item["market_iso3"], item["period_label"]) == ("ARG", "polyflora", "USA", "2026-09")
    assert item["spread_pct"] == pytest.approx(16.7, abs=0.05)
    assert [e["source"]["key"] for e in item["entries"]] == ["t_usda", "t_onm"]      # both shown, none hidden
    assert item["entries"][0]["source_url"] == "https://example.org/usda.pdf"

    s = api.get("/api/prices/series?price_type=wholesale_bulk").json()
    assert len(s["discrepancies"]) == 1
    # filtering to one source removes the comparison
    assert api.get("/api/prices/series?price_type=wholesale_bulk&source=t_usda").json()["discrepancies"] == []
    assert api.get("/api/prices/discrepancies?price_type=producer").json()["total"] == 0


def test_latest_changes_respect_gaps_and_staleness(api, db, sources):
    usda, _ = sources
    # ARG: latest month, the month before is MISSING, one year earlier exists
    add_price(db, usda, period=_ym(1), value=3.3)
    add_price(db, usda, period=_ym(3), value=3.0)
    add_price(db, usda, period=_ym(13), value=3.0)
    # UKR: previous month exists, no year-ago value
    add_price(db, usda, period=_ym(1), value=2.2, origin="UKR", variety="sunflower")
    add_price(db, usda, period=_ym(2), value=2.0, origin="UKR", variety="sunflower")
    # BRA: last published long ago -> stale against the source's 40-day rhythm
    add_price(db, usda, period=_ym(8), value=4.0, origin="BRA")
    db.commit()

    rows = {r["origin_iso3"]: r for r in api.get("/api/prices/latest?price_type=wholesale_bulk").json()["rows"]}
    arg = rows["ARG"]
    assert arg["period_label"] == _ym(1)
    assert arg["previous"] is None and arg["change_prev_pct"] is None          # never extrapolated over a gap
    assert arg["year_ago"]["period_label"] == _ym(13) and arg["change_yoy_pct"] == pytest.approx(10.0)
    ukr = rows["UKR"]
    assert ukr["change_prev_pct"] == pytest.approx(10.0) and ukr["year_ago"] is None and ukr["change_yoy_pct"] is None
    assert arg["is_stale"] is False and arg["freshness"]["basis"] == "source"
    assert rows["BRA"]["is_stale"] is True and rows["BRA"]["freshness"]["status"] == "stale"
    # 'from' does not hide the year-ago comparison
    r2 = api.get(f"/api/prices/latest?price_type=wholesale_bulk&origin=ARG&from={_ym(2)}").json()["rows"][0]
    assert r2["change_yoy_pct"] == pytest.approx(10.0)
    # quarterly view compares quarters
    q = api.get("/api/prices/latest?price_type=wholesale_bulk&freq=Q&origin=UKR").json()["rows"][0]
    assert q["freq"] == "Q" and q["latest"]["n_points"] >= 1


def test_compare_uses_each_series_latest_point_in_window(api, db, sources):
    usda, _ = sources
    add_price(db, usda, period="2026-10", value=3.0)
    add_price(db, usda, period="2026-09", value=2.0, variety="clover")
    add_price(db, usda, period="2026-10", value=4.0, variety="clover", color="white", source_url="https://x/clover")
    add_price(db, usda, period="2026-08", value=2.5, origin="UKR", variety="sunflower")
    add_price(db, usda, period="2026-05", value=5.0, origin="SRB", variety="acacia")   # outside 3-month window
    db.commit()

    d = api.get("/api/prices/compare?price_type=wholesale_bulk&by=origin").json()
    assert d["anchor_period"] == "2026-10" and d["window_from"] == "2026-08-01" and d["window_to"] == "2026-10-31"
    bars = {b["key"]: b for b in d["bars"]}
    assert set(bars) == {"ARG", "UKR"}
    # ARG = mean of three series' latest points: polyflora 3.0 (Oct), clover 2.0 (Sep), clover/white 4.0 (Oct)
    assert bars["ARG"]["value"] == pytest.approx(3.0) and bars["ARG"]["n_series"] == 3
    assert bars["ARG"]["mixed_periods"] is True and bars["ARG"]["period_labels"] == ["2026-09", "2026-10"]
    assert bars["UKR"]["period_label"] == "2026-08"                       # each bar states its own period
    assert [e["key"] for e in d["excluded"]] == ["SRB"] and d["excluded"][0]["last_period"] == "2026-05"
    assert d["bars"][0]["value"] >= d["bars"][-1]["value"]

    d = api.get("/api/prices/compare?price_type=wholesale_bulk&by=origin&window=6").json()
    assert {b["key"] for b in d["bars"]} == {"ARG", "UKR", "SRB"}
    d = api.get("/api/prices/compare?price_type=wholesale_bulk&by=variety&period=2026-09").json()
    v = {b["key"]: b for b in d["bars"]}
    assert d["anchor_period"] == "2026-09" and v["clover"]["value"] == 2.0 and v["clover"]["period_label"] == "2026-09"
    assert "acacia" not in v
    assert api.get("/api/prices/compare?price_type=wholesale_bulk&by=colour").status_code == 422
    empty = api.get("/api/prices/compare?price_type=retail").json()
    assert empty["bars"] == [] and empty["anchor_period"] is None


def test_observations_pagination_and_csv(api, db, sources):
    usda, _ = sources
    for i, p in enumerate(("2026-07", "2026-08", "2026-09")):
        add_price(db, usda, period=p, value=1.5 + i, low=1.4 + i, high=1.6 + i, unit="lb", color="extra light amber",
                  source_url="https://example.org/report.pdf", variety_raw="=HYPERLINK(\"x\")")
    demo_src = db.scalars(select(Source).where(Source.key == "demo")).one()
    add_price(db, demo_src, period="2026-09", value=7.0, demo=True)
    set_setting(db, "show_demo", True)
    db.commit()

    d = api.get("/api/prices/observations?price_type=wholesale_bulk&page_size=2").json()
    assert d["total"] == 4 and d["pages"] == 2 and len(d["rows"]) == 2
    assert d["rows"][0]["period_label"] == "2026-09"
    r = d["rows"][0]
    for k in ("source", "source_url", "published_at", "collected_at", "data_status", "reliability", "currency",
              "unit", "price_value", "price_per_kg", "revision", "is_demo"):
        assert k in r
    assert api.get("/api/prices/observations?page=2&page_size=2").json()["rows"][0]["period_label"] in ("2026-08", "2026-09")

    res = api.get("/api/prices/observations?price_type=wholesale_bulk&format=csv&lang=it")
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/csv")
    assert "attachment" in res.headers["content-disposition"] and ".csv" in res.headers["content-disposition"]
    raw = res.content
    assert raw.startswith(b"\xef\xbb\xbf")                                    # UTF-8 BOM for Excel
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig")), delimiter=";"))
    header = rows[0]
    assert header[0] == "Periodo" and "Fonte" in header and "Documento originale" in header and "Varietà" in header
    assert len(rows) == 5
    rec = dict(zip(header, rows[1]))
    real = [dict(zip(header, x)) for x in rows[1:] if dict(zip(header, x))["Fonte"] == "Test USDA honey report"]
    sep_row = next(x for x in real if x["Periodo"] == "2026-09")
    assert sep_row["Prezzo (come pubblicato)"] == "3,5" and sep_row["Unità di misura"] == "lb"   # decimal comma
    assert sep_row["Tipo di prezzo"] == "Prezzo all'ingrosso (sfuso)" and sep_row["Origine"] == "Argentina"
    assert sep_row["Varietà"] == "Millefiori" and sep_row["Documento originale"] == "https://example.org/report.pdf"
    assert sep_row["Varietà (testo della fonte)"].startswith("'=")          # spreadsheet formula neutralised
    assert sep_row["Dato dimostrativo"] == "No"
    assert any(dict(zip(header, x))["Dato dimostrativo"].startswith("SÌ") for x in rows[1:])
    assert rec["Periodo"] == "2026-09"

    en = api.get("/api/prices/observations?format=csv&lang=en&origin=ARG&source=t_usda").content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(en)))
    assert rows[0][0] == "Period" and "Original document" in rows[0]
    assert dict(zip(rows[0], rows[1]))["Price (as published)"] == "3.5"
    assert api.get("/api/prices/observations?format=xml").status_code == 422


def test_facets_only_offer_what_has_data(api, db, sources):
    usda, onm = sources
    add_price(db, usda, period="2026-09", value=3.0, origin="VNM", color="light amber")
    add_price(db, usda, period="2026-09", value=3.0, origin="ARG", color="white")
    add_price(db, usda, period="2026-09", value=3.0, origin="MLT", variety="acacia")
    add_price(db, onm, period="2026-09", value=4.0, origin="ARG", market="ITA", currency="EUR")
    add_price(db, usda, period="2025-01", value=1.0, origin="USA", price_type="producer", freq="A")
    db.commit()

    f = api.get("/api/prices/facets?price_type=wholesale_bulk").json()
    assert f["total"] == 4
    pt = {p["key"]: p["count"] for p in f["price_types"]}
    assert pt["wholesale_bulk"] == 4 and pt["producer"] == 1 and pt["retail"] == 0
    origins = [o["key"] for o in f["origins"]]
    assert origins[0] == "ARG" and "USA" not in origins
    assert origins.index("VNM") < origins.index("MLT")                     # priority countries first
    assert {c["key"] for c in f["currencies"]} == {"USD", "EUR"}
    assert {s["key"] for s in f["sources"]} == {"t_usda", "t_onm"}
    assert {c["key"] for c in f["color_grades"]} == {"light amber", "white", "_none"}
    assert f["period"] == {"min": "2026-09-01", "max": "2026-09-30"}

    # a facet ignores its own filter but honours the others
    f2 = api.get("/api/prices/facets?price_type=wholesale_bulk&variety=acacia").json()
    assert [o["key"] for o in f2["origins"]] == ["MLT"]
    assert {v["key"] for v in f2["varieties"]} == {"polyflora", "acacia"}
    f3 = api.get("/api/prices/facets?price_type=wholesale_bulk&source=t_onm").json()
    assert [m["key"] for m in f3["markets"]] == ["ITA"]

    assert api.get("/api/prices/facets?from=2026-13").status_code == 422


def test_empty_database_degrades_gracefully(api):
    assert api.get("/api/prices/facets").json()["total"] == 0
    s = api.get("/api/prices/series?price_type=wholesale_bulk").json()
    assert s["series"] == [] and s["discrepancies"] == [] and s["sources"] == []
    assert api.get("/api/prices/latest?price_type=import_unit_value").json()["rows"] == []
    assert api.get("/api/prices/observations").json() == {"total": 0, "page": 1, "page_size": 25, "pages": 1, "rows": []}
    assert api.get("/api/prices/discrepancies").json()["items"] == []
    csv_body = api.get("/api/prices/observations?format=csv&lang=it").content
    assert csv_body.startswith(b"\xef\xbb\xbfPeriodo;")
