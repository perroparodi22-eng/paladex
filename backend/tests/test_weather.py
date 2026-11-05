"""NASA POWER weather collector + honey-region reference (Milestone 5).

Fixtures are real NASA POWER answers captured on 4 Nov 2026 (tests/fixtures/weather/README.md).
"""
from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from paladex.collectors import weather
from paladex.collectors.base import CollectorError
from paladex.models import AppSetting, RawDocument, Source, WeatherObservation
from paladex.reference import regions as R
from paladex.reference.countries import is_known_iso3

TODAY = date(2026, 11, 4)
POWER = r"^https://power\.larc\.nasa\.gov/api/temporal/"
M_PLA_1991 = POWER + r"monthly/point\?.*latitude=40\.03&start=1991&end=2026"
M_PLA_2024 = POWER + r"monthly/point\?.*latitude=40\.03&start=2024&end=2026"
M_BAD_1991 = POWER + r"monthly/point\?.*latitude=38\.88&start=1991&end=2026"
M_BAD_2024 = POWER + r"monthly/point\?.*latitude=38\.88&start=2024&end=2026"
D_PLA_1001 = POWER + r"daily/point\?.*latitude=40\.03&start=20261001&end=20261031"
D_PLA_0901 = POWER + r"daily/point\?.*latitude=40\.03&start=20260901&end=20261031"
D_BAD_1001 = POWER + r"daily/point\?.*latitude=38\.88&start=20261001&end=20261031"

DAILY_PLA_URL = ("https://power.larc.nasa.gov/api/temporal/daily/point?parameters=T2M%2CPRECTOTCORR&community=AG"
                 "&longitude=-6.09&latitude=40.03&start=20261001&end=20261031&format=JSON")
MONTHLY_PLA_URL = ("https://power.larc.nasa.gov/api/temporal/monthly/point?parameters=T2M%2CPRECTOTCORR&community=AG"
                   "&longitude=-6.09&latitude=40.03&start=1991&end=2026&format=JSON")

FIXTURES = Path(__file__).parent / "fixtures" / "weather"


def fx(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@pytest.fixture()
def extremadura(monkeypatch):
    """Collect only the two Extremadura points, on the day the fixtures were captured."""
    monkeypatch.setattr(weather, "_today", lambda: TODAY)
    monkeypatch.setattr(weather, "_regions", lambda: (R.get_region("ESP-EXT"),))


@pytest.fixture()
def requests_made(monkeypatch):
    """The (url, params) of every request the collector makes."""
    made: list[tuple[str, dict]] = []
    original = weather.NasaPowerWeatherCollector._fetch

    def counting(self, ctx, run, url, params, title):
        made.append((url, dict(params)))
        return original(self, ctx, run, url, params, title)

    monkeypatch.setattr(weather.NasaPowerWeatherCollector, "_fetch", counting)
    return made


def _routes(**over):
    routes = {
        M_PLA_1991: fx("monthly_plasencia_1991_2026.json"),
        M_BAD_1991: fx("monthly_badajoz_1991_2026.json"),
        D_PLA_1001: fx("daily_plasencia_20261001_20261031.json"),
        D_BAD_1001: fx("daily_badajoz_20261001_20261031.json"),
    }
    routes.update(over)
    return routes


def _rows(session_factory, point: str | None = None) -> dict[str, WeatherObservation]:
    """Current rows by series key."""
    with session_factory() as s:
        rows = s.scalars(select(WeatherObservation).where(WeatherObservation.is_current.is_(True))).all()
        s.expunge_all()
    return {r.series_key: r for r in rows if point is None or r.series_key.startswith(point + "|")}


def _setting(session_factory, key: str):
    with session_factory() as s:
        row = s.get(AppSetting, key)
        return None if row is None else row.value


# ---------------------------------------------------------------------------
# Regions reference
# ---------------------------------------------------------------------------


def test_regions_cover_the_requested_production_areas():
    keys = [r.key for r in R.all_regions()]
    assert len(keys) == len(set(keys))
    for k in ("ARG-BA", "ARG-ER", "ARG-SF", "ARG-CB", "ARG-LP", "BRA-PI", "BRA-CE", "BRA-PR", "BRA-SC", "BRA-RS",
              "BRA-MG", "MEX-YUC", "MEX-CAM", "MEX-JAL", "MEX-VER", "USA-ND", "USA-SD", "USA-MT", "USA-CA", "USA-FL",
              "USA-TX", "CAN-AB", "CAN-SK", "CAN-MB", "ITA-PIE", "ITA-LOM", "ITA-EMR", "ITA-TOS", "ITA-SIC", "ITA-CAL",
              "ESP-VC", "ESP-EXT", "ESP-AND", "ESP-CLM", "TUR-MUG", "TUR-ORD", "CHN-HEN", "CHN-SHD", "CHN-SCH",
              "CHN-HUB", "CHN-ZJ", "CHN-HLJ", "IND-PB", "IND-UP", "IND-BR"):
        assert k in keys, k
    covered = set(R.countries())
    for iso3 in ("ARG", "URY", "BRA", "CHL", "MEX", "USA", "CAN", "UKR", "HUN", "ROU", "BGR", "SRB", "MDA", "ITA",
                 "ESP", "TUR", "CHN", "VNM", "IND", "AUS", "NZL", "ETH", "DEU", "POL"):
        assert iso3 in covered, iso3
    assert sum(1 for r in R.all_regions() if r.country_iso3 == "UKR") >= 3


@pytest.mark.parametrize("grid", [(0.5, 0.625), (0.5, 0.5)], ids=["merra2", "half-degree"])
def test_regions_are_well_formed_and_points_never_share_a_power_grid_cell(grid):
    point_keys, cells = set(), {}
    for r in R.all_regions():
        assert is_known_iso3(r.country_iso3), r.key
        assert 1 <= len(r.points) <= 4, r.key
        assert r.name_it and r.name_en and r.varieties_it and len(r.varieties_it) == len(r.varieties_en), r.key
        assert r.flowering_months and r.harvest_months
        assert all(1 <= m <= 12 for m in (*r.flowering_months, *r.harvest_months)), r.key
        assert len(set(r.flowering_months)) == len(r.flowering_months)
        assert bool(r.note_it) == bool(r.note_en), r.key
        for p in r.points:
            assert p.key.startswith(r.key.split("-")[0]), p.key
            assert "|" not in p.key and "%" not in p.key and "_" not in p.key, p.key   # series keys, LIKE patterns
            assert p.key not in point_keys, p.key
            point_keys.add(p.key)
            assert -60 < p.lat < 70 and -180 <= p.lon <= 180
            # POWER meteorology is served at the MERRA-2 resolution (0.5° x 0.625°); its docs also speak
            # of a 0.5° grid: no two points may fall in the same cell of either.
            cell = (math.floor((p.lat + 90) / grid[0]), math.floor((p.lon + 180) / grid[1]))
            assert cell not in cells, f"{p.key} shares a grid cell with {cells.get(cell)}"
            cells[cell] = p.key
            assert R.region_of_point(p.key) is r
    assert R.months(10, 3) == (10, 11, 12, 1, 2, 3)
    assert R.months(4, 8) == (4, 5, 6, 7, 8)
    assert R.get_region("ARG-BA").hemisphere == "S" and R.get_region("ITA-PIE").hemisphere == "N"
    ctx = R.context(R.get_region("ESP-EXT"))
    assert ctx["is_context"] is True and ctx["flowering_months"] == [3, 4, 5, 6, 7]


# ---------------------------------------------------------------------------
# Pure helpers on the real answers
# ---------------------------------------------------------------------------


def test_parse_monthly_real_answer():
    doc, monthly = weather.parse_monthly(fx("monthly_plasencia_1991_2026.json"))
    assert (doc.lat, doc.lon) == (40.03, -6.09)
    assert doc.sources == ["MERRA2"] and doc.api_version == "v2.10.0"
    assert min(monthly) == (1991, 1) and all(1 <= m <= 12 for _, m in monthly)   # month 13 (annual) dropped
    t, p = monthly[(2025, 8)]
    assert t == 29.6 and p == 0.2
    assert monthly[(2026, 9)] == (26.68, 0.15)
    assert monthly[(2026, 10)] == (None, None) and monthly[(2026, 11)] == (None, None)   # -999 = not yet processed
    assert weather.newest_valid_month(monthly) == (2026, 9)


def test_normals_are_1991_2020_from_the_same_series():
    _, monthly = weather.parse_monthly(fx("monthly_plasencia_1991_2026.json"))
    n = weather.compute_normals(monthly)
    assert n.years == [30] * 12
    assert n.temp_c[7] == 26.98                  # August normal; Aug 2025 = 29.6 -> +2.62 °C
    assert n.precip_mm[7] == 9.2
    # precipitation normal = mean of monthly totals (rate mm/day x days of that month)
    jan = [monthly[(y, 1)][1] * 31 for y in range(1991, 2021)]
    assert n.precip_mm[0] == round(sum(jan) / 30, 1)
    # a calendar month with too few valid years gets no normal at all
    short = {k: v for k, v in monthly.items() if not (k[1] == 2 and k[0] < 2010)}
    n2 = weather.compute_normals(short)
    assert n2.temp_c[1] is None and n2.precip_mm[1] is None and n2.years[1] == 11


def test_daily_months_are_kept_only_when_complete():
    doc, daily = weather.parse_daily(fx("daily_plasencia_20261001_20261104.json"))
    assert doc.sources == ["GEOSIT"]              # October 2026: near-real-time stream only
    complete, incomplete = weather.months_from_daily(daily)
    assert [(v.year, v.month) for v in complete] == [(2026, 10)]
    oct_ = complete[0]
    oct_days = [v for d, v in daily.items() if d.month == 10]
    assert oct_.days == 31 and oct_.basis == "daily"
    assert oct_.temp_c == round(sum(t for t, _ in oct_days) / 31, 2)
    assert oct_.precip_mm == round(sum(p for _, p in oct_days), 1)
    assert incomplete == [((2026, 11), 1, 30)]


def test_parse_rejects_wrong_units_and_error_answers():
    data = json.loads(fx("monthly_plasencia_2024_2026.json"))
    data["parameters"]["PRECTOTCORR"]["units"] = "mm"
    with pytest.raises(CollectorError, match="expected 'mm/day'"):
        weather.parse_monthly(json.dumps(data).encode())
    with pytest.raises(CollectorError, match="correct latitude"):
        weather.parse_monthly(fx("error_422_invalid_latitude.json"))


@pytest.mark.parametrize("today,expected", [
    (date(2026, 11, 4), (2026, 10)), (date(2026, 11, 3), (2026, 9)),
    (date(2026, 3, 4), (2026, 2)), (date(2026, 3, 3), (2026, 1)), (date(2027, 1, 10), (2026, 12)),
])
def test_last_complete_month_respects_the_service_latency(today, expected):
    assert weather.last_complete_month(today) == expected


def test_month_window_and_labels():
    w = weather.month_window((2026, 10))
    assert len(w) == 24 and w[0] == (2024, 11) and w[-1] == (2026, 10)
    assert weather.parse_month_label("2026-09") == (2026, 9)
    assert weather.parse_month_label("2026-13") is None and weather.parse_month_label(None) is None


def test_rhythm_text_fits_the_sources_table():
    c = weather.NasaPowerWeatherCollector
    assert len(c.expected_update) <= 120 and len(c.expected_update_en) <= 120


# ---------------------------------------------------------------------------
# End to end (offline, real answers)
# ---------------------------------------------------------------------------


def test_collect_stores_published_and_provisional_months_with_anomalies(extremadura, run_with_routes, session_factory,
                                                                         requests_made):
    res = run_with_routes("nasa_power_weather", _routes())
    assert res["status"] == "success", res
    # first run: 2 requests per point (monthly 1991-2026 for the normals and MERRA-2 months, daily for October)
    assert len(requests_made) == 4
    rows = _rows(session_factory)
    # window: Nov 2024 .. Oct 2026 (24 months) per point; Nov 2026 is still in progress
    assert len(rows) == 48
    assert not any(k.endswith("2026-11") for k in rows)
    aug = rows["ESP-EXT-plasencia|2025-08"]
    assert (aug.temp_mean_c, aug.precip_mm, aug.temp_anomaly_c, aug.precip_anomaly_pct) == (29.6, 6.2, 2.62, 67.4)
    assert aug.data_status == "published" and aug.reliability == "official" and aug.baseline == "1991-2020"
    assert aug.region_key == "ESP-EXT" and aug.country_iso3 == "ESP" and aug.period_label == "2025-08"
    assert aug.source_url == MONTHLY_PLA_URL
    assert aug.extra["basis"] == "monthly" and aug.extra["normal_temp_c"] == 26.98 and aug.extra["sources"] == ["MERRA2"]
    assert aug.raw_document_id is not None

    oct_ = rows["ESP-EXT-plasencia|2026-10"]
    assert oct_.data_status == "provisional"
    assert (oct_.temp_mean_c, oct_.precip_mm, oct_.temp_anomaly_c, oct_.precip_anomaly_pct) == (18.77, 29.3, 2.63, 33.7)
    assert oct_.source_url == DAILY_PLA_URL
    assert oct_.extra["basis"] == "daily" and oct_.extra["days"] == 31 and oct_.extra["sources"] == ["GEOSIT"]
    assert oct_.extra["baseline_url"] == MONTHLY_PLA_URL and oct_.notes

    normals = _setting(session_factory, "nasa_power_normals:ESP-EXT-plasencia")
    assert normals["baseline"] == "1991-2020" and normals["source_url"] == MONTHLY_PLA_URL
    assert normals["temp_c"][7] == 26.98 and normals["lat"] == 40.03 and normals["rebuilt_from_rows"] is False
    status = _setting(session_factory, weather.STATUS_SETTING)
    assert status["latest"] == "2026-09"
    with session_factory() as s:
        src = s.scalars(select(Source).where(Source.key == "nasa_power_weather")).one()
        assert src.latest_period_label == "2026-10" and src.category == "weather" and src.reliability == "official"
        # only successful answers are archived
        assert s.scalar(select(RawDocument.id).where(RawDocument.url.like("%latitude=95%"))) is None


def test_second_run_asks_nothing_when_every_point_is_up_to_date(extremadura, run_with_routes, requests_made):
    assert run_with_routes("nasa_power_weather", _routes())["status"] == "success"
    requests_made.clear()
    # No routes at all: any request would fail as "offline". October is held (provisional) and the
    # monthly API was seen ending with September less than PROBE_INTERVAL_HOURS ago: nothing to ask.
    res = run_with_routes("nasa_power_weather", {})
    assert res["status"] == "no_change", res
    assert requests_made == []


def test_a_stale_probe_costs_one_request_not_one_per_point(extremadura, monkeypatch, run_with_routes, requests_made):
    assert run_with_routes("nasa_power_weather", _routes())["status"] == "success"
    requests_made.clear()
    monkeypatch.setattr(weather, "PROBE_INTERVAL_HOURS", -1)          # the last check is now too old
    res = run_with_routes("nasa_power_weather", {M_PLA_2024: fx("monthly_plasencia_2024_2026.json")})
    assert res["status"] == "no_change", res
    # Plasencia asks the monthly API (still ending with September); Badajoz then knows that MERRA-2
    # has nothing newer for it either, and its October is already held: no request for Badajoz.
    assert [u for u, _ in requests_made] == [weather.MONTHLY_URL]
    assert requests_made[0][1]["start"] == "2024"


def test_provisional_month_becomes_published_revision(extremadura, monkeypatch, run_with_routes, session_factory,
                                                      requests_made):
    monkeypatch.setattr(weather, "_regions", lambda: (R.Region(
        "ESP-EXT", "ESP", "Estremadura", "Extremadura", (R.get_region("ESP-EXT").points[0],), ("x",), ("x",),
        R.months(3, 7), R.months(5, 9)),))
    # Derived input: the real monthly answer as it looked before NASA processed September 2026.
    before = json.loads(fx("monthly_plasencia_1991_2026.json"))
    for p in ("T2M", "PRECTOTCORR"):
        before["properties"]["parameter"][p]["202609"] = -999.0
    res = run_with_routes("nasa_power_weather", {
        M_PLA_1991: json.dumps(before).encode(), D_PLA_0901: fx("daily_plasencia_20260901_20261031.json")})
    assert res["status"] == "success", res
    sep = _rows(session_factory)["ESP-EXT-plasencia|2026-09"]
    assert sep.data_status == "provisional" and sep.extra["basis"] == "daily" and sep.revision == 1
    assert sep.extra["sources"] == ["MERRA2", "GEOSIT"]
    assert (sep.temp_mean_c, sep.precip_mm) == (26.68, 4.4)          # sum of the daily values

    # A day later the monthly API has September: it replaces the provisional value as a revision.
    # October is still held (provisional) and not yet in the monthly series: no daily request.
    monkeypatch.setattr(weather, "PROBE_INTERVAL_HOURS", -1)
    requests_made.clear()
    res = run_with_routes("nasa_power_weather", {M_PLA_2024: fx("monthly_plasencia_2024_2026.json")})
    assert res["status"] == "success" and res["revised"] >= 1, res
    assert [u for u, _ in requests_made] == [weather.MONTHLY_URL]
    sep2 = _rows(session_factory)["ESP-EXT-plasencia|2026-09"]
    assert sep2.data_status == "published" and sep2.extra["basis"] == "monthly"
    assert sep2.revision == 2 and sep2.supersedes_id == sep.id
    assert (sep2.temp_mean_c, sep2.precip_mm) == (26.68, 4.5)        # 0.15 mm/day x 30 days, as NASA rounds it
    with session_factory() as s:
        old = s.get(WeatherObservation, sep.id)
        assert old.is_current is False and old.data_status == "provisional"     # history kept
    oct_ = _rows(session_factory)["ESP-EXT-plasencia|2026-10"]
    assert oct_.data_status == "provisional" and oct_.revision == 1


def test_normals_are_rebuilt_from_the_rows_after_a_data_only_copy(extremadura, monkeypatch, run_with_routes,
                                                                   session_factory, requests_made):
    assert run_with_routes("nasa_power_weather", _routes())["status"] == "success"
    original = _setting(session_factory, "nasa_power_normals:ESP-EXT-badajoz")
    # The starter data copies observations but no settings: no cached normals, no probe status.
    with session_factory() as s:
        s.execute(delete(AppSetting).where(AppSetting.key.like("nasa_power_%")))
    requests_made.clear()
    res = run_with_routes("nasa_power_weather", {M_PLA_2024: fx("monthly_plasencia_2024_2026.json")})
    assert res["status"] == "no_change", res
    # one probe of the monthly API (window only, no 1991-2026 download), nothing for Badajoz
    assert [(u, p["start"]) for u, p in requests_made] == [(weather.MONTHLY_URL, "2024")]
    rebuilt = _setting(session_factory, "nasa_power_normals:ESP-EXT-badajoz")
    assert rebuilt["rebuilt_from_rows"] is True
    assert {k: rebuilt[k] for k in ("temp_c", "precip_mm", "years", "source_url")} == \
        {k: original[k] for k in ("temp_c", "precip_mm", "years", "source_url")}


def test_rate_limit_stops_the_run_but_keeps_what_was_collected(extremadura, run_with_routes, session_factory):
    res = run_with_routes("nasa_power_weather", _routes(**{M_BAD_1991: (429, b'{"detail":"Too Many Requests"}')}))
    assert res["status"] == "partial", res
    assert any("429" in w for w in res["warnings"])
    rows = _rows(session_factory)
    assert len(rows) == 24 and all(k.startswith("ESP-EXT-plasencia|") for k in rows)


def test_a_service_outage_stops_after_three_points(monkeypatch, run_with_routes, session_factory, requests_made):
    monkeypatch.setattr(weather, "_today", lambda: TODAY)
    monkeypatch.setattr(weather, "_regions", lambda: (R.get_region("ESP-EXT"), R.get_region("ESP-AND")))
    res = run_with_routes("nasa_power_weather", {POWER: (503, b"Service Unavailable")})
    assert res["status"] == "failed", res
    assert "nessun punto raccolto" in res["error"]
    # 4 points, but the run stops after 3 in a row (each retried by the framework): the 4th is never asked
    assert len(requests_made) == 3
    assert _rows(session_factory) == {}


def test_invalid_request_and_wrong_point_are_reported_per_point(extremadura, run_with_routes, session_factory):
    # Badajoz: NASA refuses the request (real 422 answer); Plasencia: an answer for another point.
    res = run_with_routes("nasa_power_weather", _routes(**{
        M_BAD_1991: (422, fx("error_422_invalid_latitude.json")),
        M_PLA_1991: fx("monthly_badajoz_1991_2026.json"),
    }))
    assert res["status"] == "failed", res
    assert "nessun punto raccolto" in res["error"]
    assert _rows(session_factory) == {}


def test_one_failing_point_does_not_stop_the_others(extremadura, run_with_routes, session_factory):
    res = run_with_routes("nasa_power_weather", _routes(**{M_BAD_1991: (422, fx("error_422_invalid_latitude.json"))}))
    assert res["status"] == "partial"
    assert any("422" in w and "Badajoz" in w for w in res["warnings"])
    assert len(_rows(session_factory, "ESP-EXT-plasencia")) == 24
