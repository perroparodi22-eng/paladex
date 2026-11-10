"""/api/harvest/*: production by country, weather conditions per honey region with rule-based flags
(automatic assessments, never data), harvest reports and news.

Weather rows come from the real collector run on the real NASA POWER captures (Extremadura,
tests/fixtures/weather); the rule tests use small hand-built month records (pure function).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from paladex.api import harvest as H
from paladex.collectors import weather
from paladex.collectors.base import year_bounds
from paladex.models import (
    CollectionRun,
    NewsArticle,
    ProductionStat,
    Report,
    Source,
    utcnow,
)
from paladex.reference import regions as R
from paladex.services import ingest

WEATHER_FIXTURES = Path(__file__).parent / "fixtures" / "weather"
POWER = r"^https://power\.larc\.nasa\.gov/api/temporal/"


def weather_routes() -> dict:
    """The real NASA POWER answers for the two Extremadura points (see tests/fixtures/weather/README.md)."""
    def f(name: str) -> bytes:
        return (WEATHER_FIXTURES / name).read_bytes()

    return {
        POWER + r"monthly/point\?.*latitude=40\.03&start=1991&end=2026": f("monthly_plasencia_1991_2026.json"),
        POWER + r"monthly/point\?.*latitude=38\.88&start=1991&end=2026": f("monthly_badajoz_1991_2026.json"),
        POWER + r"daily/point\?.*latitude=40\.03&start=20261001&end=20261031": f("daily_plasencia_20261001_20261031.json"),
        POWER + r"daily/point\?.*latitude=38\.88&start=20261001&end=20261031": f("daily_badajoz_20261001_20261031.json"),
    }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def source(db, key: str) -> Source:
    from sqlalchemy import select

    return db.scalars(select(Source).where(Source.key == key)).one()


def production(db, src: Source, iso3: str, year: int, value: float, *, status: str = "published", unit: str = "t",
               flag: str | None = "A", is_demo: bool = False, metric: str = "production"):
    start, end = year_bounds(year)
    ingest.record(
        db, ProductionStat, source_id=src.id, is_demo=is_demo, series_key=f"{src.key}|{iso3}|{metric}|{unit}|{year}",
        country_iso3=iso3, metric=metric, value=value, unit=unit, period_start=start, period_end=end,
        period_label=str(year), frequency="A", published_at=date(year + 1, 12, 20), flag_raw=flag,
        source_url=f"https://example.org/{src.key}", data_status="demo" if is_demo else status,
        reliability="demo" if is_demo else src.reliability, notes=f"flag {flag}" if flag else None,
    )


def md(label: str, *, flowering: bool = True, pct: float | None = 100.0, normal: float | None = 50.0,
       anomaly: float | None = 0.0, status: str = "published", points: int = 2) -> dict:
    """One region-month record as `region_month` builds it (only the fields the rules read)."""
    return {"period_label": label, "flowering": flowering, "precip_pct": pct, "precip_normal_mm": normal,
            "temp_anomaly_c": anomaly, "data_status": status, "points_with_data": points}


@pytest.fixture()
def extremadura_weather(monkeypatch, run_with_routes):
    """The real collector on the real Extremadura captures (4 Nov 2026)."""
    monkeypatch.setattr(weather, "_today", lambda: date(2026, 11, 4))
    monkeypatch.setattr(weather, "_regions", lambda: (R.get_region("ESP-EXT"),))
    res = run_with_routes("nasa_power_weather", weather_routes())
    assert res["status"] == "success", res
    return res


# ---------------------------------------------------------------------------
# Empty database: honest states
# ---------------------------------------------------------------------------


def test_empty_database_says_weather_is_being_collected_and_keeps_production_separate(api):
    w = api.get("/api/harvest/weather").json()
    assert w["available"] is False and w["months"] == [] and w["latest_period_label"] is None
    assert w["collection"]["state"] == "never"
    assert len(w["regions"]) == len(R.all_regions())
    assert {r["condition"] for r in w["regions"]} == {"no_data"}
    assert all(r["flags"] == [] and r["recent"] == [] for r in w["regions"])
    # the rules are always shown, labelled as automatic assessments
    assert [r["key"] for r in w["rules"]] == ["drought_watch", "heat_stress", "wet_season"]
    assert "non dati confermati" in w["assessment_label_it"] and "not confirmed data" in w["assessment_label_en"]
    assert "NASA" in w["citation"] and w["source"]["key"] == "nasa_power_weather"
    # curated context is flagged as such
    ext = next(r for r in w["regions"] if r["key"] == "ESP-EXT")
    assert ext["context"]["is_context"] is True and ext["context"]["flowering_months"] == [3, 4, 5, 6, 7]

    p = api.get("/api/harvest/production").json()
    assert p["available"] is False and p["countries"] == []
    assert any(x["key"] == "faostat" for x in p["providers"])

    r = api.get("/api/harvest/reports").json()
    assert r["reports"] == [] and r["news"] == []
    assert {x["key"] for x in r["report_providers"]} >= {"onm_informamiele", "usda_honey_report"}


def test_a_running_collection_is_reported(api, db):
    src = source(db, "nasa_power_weather")
    db.add(CollectionRun(source_id=src.id, status="running", trigger="startup", started_at=utcnow()))
    db.commit()
    assert api.get("/api/harvest/weather").json()["collection"]["state"] == "running"


# ---------------------------------------------------------------------------
# Production
# ---------------------------------------------------------------------------


def test_production_latest_year_change_and_status(api, db):
    fao = source(db, "faostat")
    production(db, fao, "ARG", 2023, 69701.22, status="estimate", flag="E")
    production(db, fao, "ARG", 2024, 69297.65, status="estimate", flag="E")
    production(db, fao, "USA", 2022, 56920.0)
    production(db, fao, "USA", 2024, 60960.0)            # 2023 missing: no change is computed
    production(db, fao, "KEN", 2024, 19462.0)            # not a monitored country
    production(db, fao, "ITA", 2024, 9.0, is_demo=True)  # demo rows stay hidden
    db.commit()
    p = api.get("/api/harvest/production").json()          # default: the countries monitored on this page
    assert p["available"] is True and p["scope"] == "monitored"
    assert [c["iso3"] for c in p["countries"]] == ["ARG", "USA"]
    assert p["countries_with_data"] == 3 and p["monitored_with_data"] == 2
    p = api.get("/api/harvest/production", params={"scope": "all"}).json()
    by = {c["iso3"]: c for c in p["countries"]}
    assert set(by) == {"ARG", "USA", "KEN"}
    arg = by["ARG"]["series"][0]
    assert arg["latest"]["year"] == 2024 and arg["latest"]["value"] == 69297.65
    assert isinstance(arg["latest"]["row_id"], int) and arg["latest"]["correction"] is None   # what a person fixes by tapping
    assert arg["latest"]["data_status"] == "estimate" and arg["latest"]["flag_raw"] == "E"
    assert arg["previous"]["year"] == 2023 and arg["change_pct"] == round(100 * (69297.65 - 69701.22) / 69701.22, 1)
    assert arg["source"]["key"] == "faostat" and arg["reliability"] == "official" and arg["latest"]["source_url"]
    assert by["USA"]["series"][0]["previous"] is None and by["USA"]["series"][0]["change_pct"] is None
    assert by["ARG"]["monitored"] is True and "ARG-BA" in by["ARG"]["regions"] and by["KEN"]["monitored"] is False
    # ordered by the latest volume
    assert [c["iso3"] for c in p["countries"]] == ["ARG", "USA", "KEN"]
    assert api.get("/api/harvest/production", params={"scope": "nope"}).status_code == 422
    assert p["years"] == [2024] and p["sources"][0]["key"] == "faostat"


def test_forecasts_and_other_sources_are_never_merged_with_the_latest_data(api, db):
    fao, stat = source(db, "faostat"), source(db, "usda_nass_honey")
    production(db, fao, "USA", 2023, 62000.0)
    production(db, fao, "USA", 2024, 60960.0)
    production(db, stat, "USA", 2024, 61000000.0, unit="kg", flag=None)
    production(db, stat, "USA", 2025, 59000000.0, unit="kg", status="forecast", flag=None)
    db.commit()
    usa = next(c for c in api.get("/api/harvest/production").json()["countries"] if c["iso3"] == "USA")
    assert len(usa["series"]) == 2
    nass = next(s for s in usa["series"] if s["source"]["key"] == "usda_nass_honey")
    assert nass["unit"] == "kg" and nass["latest"]["year"] == 2024 and nass["latest_t"] == 61000.0
    assert nass["forecast"]["year"] == 2025 and nass["forecast"]["data_status"] == "forecast"
    fao_s = next(s for s in usa["series"] if s["source"]["key"] == "faostat")
    assert fao_s["forecast"] is None and fao_s["change_pct"] == round(100 * (60960 - 62000) / 62000, 1)


def test_production_country_series_for_the_chart(api, db):
    fao = source(db, "faostat")
    for y, v in ((2022, 71762.14), (2023, 69701.22), (2024, 69297.65)):
        production(db, fao, "ARG", y, v, status="estimate", flag="E")
    production(db, fao, "ARG", 2024, 3100000.0, metric="colonies", unit="number")
    db.commit()
    d = api.get("/api/harvest/production/arg").json()
    assert d["iso3"] == "ARG" and d["name_it"] == "Argentina" and "ARG-BA" in d["regions"]
    prod = next(m for m in d["metrics"] if m["metric"] == "production")
    pts = prod["series"][0]["points"]
    assert [p["period_label"] for p in pts] == ["2022", "2023", "2024"] and pts[-1]["data_status"] == "estimate"
    assert {m["metric"] for m in d["metrics"]} == {"production", "colonies"}
    assert api.get("/api/harvest/production/XYZ").status_code == 404


# ---------------------------------------------------------------------------
# Weather: rules (pure function)
# ---------------------------------------------------------------------------


def test_drought_needs_two_consecutive_dry_flowering_months():
    months = [md("2026-02", flowering=False, pct=20), md("2026-03", pct=41), md("2026-04", pct=53),
              md("2026-05", pct=72), md("2026-06", pct=17)]
    flags = H.evaluate_flags(months, recent_from="2026-04")
    assert [(f["rule"], f["months"], f["values"]) for f in flags] == [("drought_watch", ["2026-03", "2026-04"], [41, 53])]
    assert flags[0]["recent"] is True and flags[0]["metric"] == "precip_pct"
    # one dry month alone is not enough; outside the flowering season nothing counts
    assert H.evaluate_flags([md("2026-03", pct=41), md("2026-04", pct=80)], None) == []
    assert H.evaluate_flags([md("2026-01", flowering=False, pct=10), md("2026-02", flowering=False, pct=10)], None) == []


def test_precipitation_rules_skip_tiny_normals_and_missing_months_break_a_run():
    # July in Extremadura: a normal of ~6 mm makes any percentage meaningless
    assert H.evaluate_flags([md("2026-06", pct=17, normal=15.4), md("2026-07", pct=3, normal=5.7)], None) == []
    assert H.evaluate_flags([md("2026-07", pct=300, normal=5.7)], None) == []
    gap = [md("2026-03", pct=41), md("2026-04", pct=None, normal=None, points=0), md("2026-05", pct=30)]
    assert H.evaluate_flags(gap, None) == []


def test_heat_and_wet_rules_and_provisional_data():
    months = [md("2026-04", anomaly=2.5), md("2026-05", anomaly=1.9), md("2026-06", anomaly=4.2, pct=210),
              md("2026-07", anomaly=2.0, status="provisional", pct=170)]
    flags = H.evaluate_flags(months, recent_from="2026-06")
    heat = [f for f in flags if f["rule"] == "heat_stress"]
    assert [f["months"] for f in heat] == [["2026-06", "2026-07"]]       # +2.5 alone (April) is not enough
    assert heat[0]["data_status"] == "provisional" and heat[0]["metric"] == "temp_anomaly_c"
    wet = [f for f in flags if f["rule"] == "wet_season"]
    assert [(f["months"], f["values"]) for f in wet] == [(["2026-06", "2026-07"], [210, 170])]
    # a wet SEASON: one month above 160% is not enough, and "above" means above (160% is not)
    assert H.evaluate_flags([md("2026-05", pct=300), md("2026-06", pct=90)], None) == []
    assert H.evaluate_flags([md("2026-05", pct=160), md("2026-06", pct=160)], None) == []
    assert [r["min_months"] for r in H.RULES] == [2, 2, 2]


def test_exceptional_values_are_kept_but_flagged_for_checking():
    # NASA POWER, February 2026, Sibari (Calabria): 3099.6 mm against a normal of 80 mm
    assert H.is_exceptional(3099.6, 80.0) is True
    assert H.is_exceptional(633.3, 400.0) is False        # a wet monsoon month: high, but in its own climate
    assert H.is_exceptional(252.7, 10.3) is False         # 24 x a dry-season normal, but under 300 mm
    assert H.is_exceptional(None, 80.0) is False and H.is_exceptional(500.0, None) is False
    months = [md("2026-02", pct=2790), md("2026-03", pct=900)]
    months[0]["exceptional_points"] = ["Piana di Sibari"]
    (flag,) = H.evaluate_flags(months, None)
    assert flag["rule"] == "wet_season" and flag["exceptional_months"] == ["2026-02"]


def test_region_month_averages_points_and_never_fills_a_missing_point():
    reg = R.get_region("ESP-EXT")

    class Row:
        def __init__(self, t, ta, p, pp, nt, np_, status="published"):
            self.temp_mean_c, self.temp_anomaly_c, self.precip_mm, self.precip_anomaly_pct = t, ta, p, pp
            self.extra = {"normal_temp_c": nt, "normal_precip_mm": np_, "basis": "monthly", "sources": ["MERRA2"]}
            self.data_status, self.source_url, self.revision = status, "https://power.larc.nasa.gov/x", 1
            self.collected_at = self.last_seen_at = datetime(2026, 11, 4)

    rows = {("ESP-EXT-plasencia", "2026-03"): Row(10.84, 0.37, 20.5, 36.1, 10.47, 56.8),
            ("ESP-EXT-badajoz", "2026-03"): Row(11.34, 0.08, 25.1, 46.6, 11.26, 53.9, status="provisional"),
            ("ESP-EXT-plasencia", "2026-04"): Row(15.87, 2.8, 26.7, 45.9, 13.07, 58.2)}
    mar = H.region_month(reg, "2026-03", rows)
    assert mar["points_with_data"] == 2 and mar["points_total"] == 2 and mar["flowering"] is True
    assert mar["temp_anomaly_c"] == round((0.37 + 0.08) / 2, 2)
    assert mar["precip_pct"] == round(100 * (20.5 + 25.1) / (56.8 + 53.9), 1)   # mean rain / mean normal
    assert mar["data_status"] == "provisional" and len(mar["points"]) == 2
    apr = H.region_month(reg, "2026-04", rows)
    assert apr["points_with_data"] == 1 and apr["temp_anomaly_c"] == 2.8          # the other point is not invented
    empty = H.region_month(reg, "2026-05", rows)
    assert empty["points_with_data"] == 0 and empty["precip_pct"] is None and empty["data_status"] is None


# ---------------------------------------------------------------------------
# Weather: end to end on the real NASA POWER data
# ---------------------------------------------------------------------------


def test_weather_on_real_data_flags_the_2026_dry_spring_and_hot_summer_in_extremadura(api, extremadura_weather):
    w = api.get("/api/harvest/weather").json()
    assert w["available"] is True and w["regions_with_data"] == 1
    assert w["months"][0] == "2025-11" and w["months"][-1] == "2026-10" and len(w["months"]) == 12
    assert w["recent_months"] == ["2026-08", "2026-09", "2026-10"]
    assert w["latest_period_label"] == "2026-10" and w["latest_data_status"] == "provisional"
    assert w["accessed_at"] and w["collection"]["state"] == "success"
    ext = next(r for r in w["regions"] if r["key"] == "ESP-EXT")
    assert ext["has_data"] is True and ext["latest_period_label"] == "2026-10"
    assert [m["period_label"] for m in ext["recent"]] == w["recent_months"]
    oct_ = ext["recent"][-1]
    assert oct_["data_status"] == "provisional" and oct_["points_with_data"] == 2 and "points" not in oct_
    # NASA POWER 2026: March-April far below normal rain, June-July far above normal temperature,
    # both in the flowering season (March-July); not in the last 3 months, so not "recent".
    flags = {f["rule"]: f for f in ext["flags"]}
    assert set(flags) == {"drought_watch", "heat_stress"}
    assert flags["drought_watch"]["months"] == ["2026-03", "2026-04"]
    assert flags["drought_watch"]["values"] == [round(100 * (20.5 + 25.1) / (56.8 + 53.9), 1),
                                                round(100 * (26.7 + 32.7) / (58.2 + 54.2), 1)]
    assert flags["heat_stress"]["months"] == ["2026-06", "2026-07"]
    assert flags["heat_stress"]["values"][0] > 4 and flags["heat_stress"]["data_status"] == "published"
    assert not any(f["recent"] for f in ext["flags"])
    assert ext["condition"] == "drought_watch" and ext["condition_recent"] is None
    other = next(r for r in w["regions"] if r["key"] == "ARG-BA")
    assert other["has_data"] is False and other["condition"] == "no_data"


def test_weather_region_detail_has_every_point_with_its_exact_query(api, extremadura_weather):
    d = api.get("/api/harvest/weather/esp-ext").json()
    reg = d["region"]
    assert len(reg["months"]) == 12
    oct_ = reg["months"][-1]
    pla = next(p for p in oct_["points"] if p["point"] == "ESP-EXT-plasencia")
    assert pla["basis"] == "daily" and pla["nasa_sources"] == ["GEOSIT"] and pla["data_status"] == "provisional"
    assert pla["source_url"].startswith("https://power.larc.nasa.gov/api/temporal/daily/point?")
    assert (pla["temp_mean_c"], pla["temp_anomaly_c"], pla["precip_mm"], pla["precip_anomaly_pct"]) == (18.77, 2.63, 29.3, 33.7)
    aug = next(m for m in reg["months"] if m["period_label"] == "2026-06")
    assert all(p["basis"] == "monthly" and "start=1991" in p["source_url"] for p in aug["points"])
    assert api.get("/api/harvest/weather/XX-NOPE").status_code == 404


# ---------------------------------------------------------------------------
# Reports and news
# ---------------------------------------------------------------------------


def test_reports_are_limited_per_source_and_news_are_production_or_weather(api, db):
    onm, usda = source(db, "onm_informamiele"), source(db, "usda_honey_report")
    for i in range(5):
        db.add(Report(source_id=usda.id, report_key=f"2026-0{i + 1}", title=f"National Honey Report {i}",
                      url=f"https://www.ams.usda.gov/{i}", published_at=date(2026, i + 1, 28), period_label=f"2026-0{i + 1}"))
    db.add(Report(source_id=onm.id, report_key="annual-2025", title="Report annuale ONM - stagione 2025",
                  url="https://www.informamiele.it/report.pdf", published_at=None, period_label="2025"))
    gdelt = source(db, "news_gdelt")
    now = utcnow()
    for i, (title, topics, demo) in enumerate([
        ("Drought cuts Argentina honey crop", ["production", "weather"], False),
        ("Honey prices rise in Europe", ["prices"], False),
        ("Fake harvest story", ["production"], True),
        ("Frost hits acacia flowering in Hungary", ["weather"], False),
        ("The gift of honey all over the world", ["weather"], False),      # weakly relevant: below the cutoff
    ]):
        db.add(NewsArticle(source_id=gdelt.id, url=f"https://news.example/{i}", canonical_url=f"https://news.example/{i}",
                           title=title, title_norm=title.lower(), topics=topics, is_demo=demo,
                           published_at=now - timedelta(days=i), relevance_score=16 if "gift" in title else 50))
    db.commit()
    r = api.get("/api/harvest/reports").json()
    keys = [x["source"]["key"] for x in r["reports"]]
    assert keys.count("usda_honey_report") == H.REPORTS_PER_SOURCE and keys.count("onm_informamiele") == 1
    assert r["reports"][0]["title"] == "National Honey Report 4"          # newest first
    assert all(x["source_url"] for x in r["reports"])
    titles = [n["title"] for n in r["news"]]
    assert titles == ["Drought cuts Argentina honey crop", "Frost hits acacia flowering in Hungary"]
    assert r["news"][0]["harvest_topics"] == ["production", "weather"]
    assert r["news_link"].startswith("/notizie?topic=") and r["news_min_relevance"] == H.NEWS_MIN_RELEVANCE


def test_regional_production_never_becomes_a_national_series(api, db):
    """Lead request 2026-11-05: IBGE stores Brazil's 27 states as `production_by_region` (state in extra.region).
    Grouped by metric they made ONE series of 297 points whose 'latest' was an arbitrary state and whose
    year-on-year change compared two states. Per-country and archive series leave `*_by_region` metrics out;
    the national IBGE figures stay, and the newest official figure (IBGE 2025) heads Brazil's row."""
    from paladex.models import Source

    fao = source(db, "faostat")
    ibge = Source(key="t_ibge", name="IBGE PPM", publisher="IBGE", homepage="https://example.org", kind="api",
                  reliability="official", category="production", country_iso3="BRA", expected_max_age_days=400)
    db.add(ibge)
    db.flush()
    production(db, fao, "BRA", 2023, 64200.0)
    production(db, fao, "BRA", 2024, 65900.0)
    production(db, ibge, "BRA", 2024, 66100.0)
    production(db, ibge, "BRA", 2025, 71300.0)
    production(db, ibge, "BRA", 2025, 1_450_000.0, metric="production_value", unit="1000 BRL")
    for state, value in (("Paraná", 9800.0), ("Rio Grande do Sul", 9100.0), ("Piauí", 6200.0)):
        for y in (2024, 2025):
            start, end = year_bounds(y)
            ingest.record(
                db, ProductionStat, source_id=ibge.id, series_key=f"ibge|BRA|{state}|{y}", country_iso3="BRA",
                metric="production_by_region", value=value, unit="t", period_start=start, period_end=end,
                period_label=str(y), frequency="A", published_at=date(y + 1, 9, 20), data_status="published",
                reliability="official", extra={"region": state})
    db.commit()

    d = api.get("/api/harvest/production/BRA").json()
    assert {m["metric"] for m in d["metrics"]} == {"production", "production_value"}
    prod = next(m for m in d["metrics"] if m["metric"] == "production")
    ibge_s = next(s for s in prod["series"] if s["source"]["key"] == "t_ibge")
    assert [p["value"] for p in ibge_s["points"]] == [66100.0, 71300.0] and ibge_s["latest"]["period_label"] == "2025"
    profile = api.get("/api/countries/BRA").json()
    assert {m["metric"] for m in profile["production"]["metrics"]} == {"production", "production_value"}
    arch = api.get("/api/archive/production", params={"country": "BRA", "metric": "production"}).json()
    assert {m["key"] for m in arch["metrics"]} == {"production", "production_value"}
    assert sorted(len(s["points"]) for s in arch["series"]) == [2, 2]
    assert api.get("/api/archive/production",
                   params={"country": "BRA", "metric": "production_by_region"}).json()["available"] is False
    row = next(c for c in api.get("/api/harvest/production", params={"scope": "all"}).json()["countries"]
               if c["iso3"] == "BRA")
    assert row["series"][0]["source"]["key"] == "t_ibge" and row["primary_year"] == 2025 and row["primary_t"] == 71300.0
    assert row["series"][1]["source"]["key"] == "faostat"
