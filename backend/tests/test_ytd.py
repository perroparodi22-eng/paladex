"""Year to date ("2026 finora", api/ytd.py): the running year's monthly customs figures against THE
SAME months of the year before, from ONE source.

Covers the pure computation (same-months rule, partial months, gaps, full and stale years) and the
API: the country profile's own figure and its source choice (sources never mixed), a newest month
published without its total left out, partner sums when a source never publishes a total, what
partners declare when the country has none, the overview's year-so-far lists, and the FAOSTAT
release note on production.
"""
from __future__ import annotations

from datetime import date, timedelta

from paladex.api.trade import Agg
from paladex.api.ytd import Months, compute
from paladex.collectors.base import month_bounds, year_bounds
from paladex.models import ProductionStat, Source, TradeFlowObservation
from paladex.services import ingest

TODAY = date.today()
CY = TODAY.year                     # the running year
PY = CY - 1
# the last month of the running year the fixtures hold: recent enough to be "the year so far"
M = max(1, TODAY.month - 2)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def make_source(db, key: str, *, country: str | None = None, reliability: str = "official",
                category: str = "trade") -> Source:
    s = Source(key=key, name=f"Source {key}", publisher=f"Publisher {key}", homepage="https://example.org",
               kind="api", reliability=reliability, category=category, country_iso3=country,
               expected_max_age_days=60)
    db.add(s)
    db.flush()
    return s


def month(db, src: Source, reporter: str, partner: str, year: int, m: int, kg: float | None, *,
          flow: str = "export", usd: float | None = "auto", status: str = "published") -> None:
    start, end = month_bounds(year, m)
    if usd == "auto":
        usd = None if kg is None else kg * 3
    ingest.record(
        db, TradeFlowObservation, source_id=src.id, is_demo=False,
        series_key=f"{reporter}|{partner}|{flow}|{year}-{m:02d}", hs_code="0409", reporter_iso3=reporter,
        partner_iso3=partner, flow=flow, net_weight_kg=kg, value=usd, currency="USD", usd_value=usd,
        value_basis="FOB" if flow == "export" else "CIF", unit_value_per_kg=(usd / kg) if usd and kg else None,
        period_start=start, period_end=end, period_label=f"{year}-{m:02d}", frequency="M",
        published_at=end + timedelta(days=20), source_url=f"https://example.org/{src.key}",
        data_status=status, reliability=src.reliability,
    )


def annual(db, src: Source, reporter: str, year: int, kg: float, *, flow: str = "export") -> None:
    start, end = year_bounds(year)
    ingest.record(
        db, TradeFlowObservation, source_id=src.id, is_demo=False, series_key=f"{reporter}|WLD|{flow}|{year}",
        hs_code="0409", reporter_iso3=reporter, partner_iso3="WLD", flow=flow, net_weight_kg=kg, value=kg * 3,
        currency="USD", usd_value=kg * 3, value_basis="FOB", period_start=start, period_end=end,
        period_label=str(year), frequency="A", published_at=end + timedelta(days=200),
        data_status="published", reliability=src.reliability,
    )


def get(api, path: str) -> dict:
    r = api.get(path)
    assert r.status_code == 200, r.text
    return r.json()


def agg(kg: float | None, usd: float | None = None) -> Agg:
    return Agg(kg=kg, usd=usd, value=usd, kg_n=0 if kg is None else 1, usd_n=0 if usd is None else 1,
               val_n=0 if usd is None else 1, n=1, periods=1)


def months(spec: dict[tuple[int, int], float | None]) -> dict[date, Agg]:
    return {date(y, m, 1): agg(kg, None if kg is None else kg * 2) for (y, m), kg in spec.items()}


# ---------------------------------------------------------------------------
# the computation
# ---------------------------------------------------------------------------


def test_same_months_of_the_year_before_only():
    today = date(2026, 11, 5)
    # 2026 Jan-Sep; 2025 the whole year: compared on Jan-Sep 2025 only, never on the full year
    data = months({**{(2026, m): 10.0 for m in range(1, 10)}, **{(2025, m): 5.0 for m in range(1, 13)}})
    y = compute(data, today)
    assert (y.year, y.month_to) == (2026, 9)
    assert y.current.kg == 90.0 and y.previous.kg == 45.0
    assert y.comparable

    # 2025 holds only Nov-Dec from this source (UN Comtrade monthly for Italy): no comparison
    data = months({**{(2026, m): 10.0 for m in range(1, 8)}, (2025, 11): 5.0, (2025, 12): 5.0})
    y = compute(data, today)
    assert y.month_to == 7 and y.previous is None and not y.comparable
    assert y.prev_months_available == [11, 12]


def test_partial_and_missing_months():
    today = date(2026, 11, 5)
    base = {(2025, m): 5.0 for m in range(1, 13)}
    # a newest month published without the country total is left out (Months.counted), and said so
    cells = Months()
    for (yy, mm), kg in {**base, **{(2026, m): 10.0 for m in range(1, 8)}}.items():
        cells.cells[date(yy, mm, 1)] = {"w": agg(kg, kg * 2)}
    cells.cells[date(2026, 8, 1)] = {"p": agg(1.0, 2.0)}          # 7 partners, no World row
    counted, summed, excluded = cells.counted()
    assert date(2026, 8, 1) not in counted and excluded == {date(2026, 8, 1): "no_total"} and not summed
    y = compute(counted, today, excluded=excluded)
    assert y.month_to == 7 and y.current.kg == 70.0 and y.previous.kg == 35.0
    assert y.excluded == [{"month": "2026-08", "reason": "no_total"}]

    # a gap stops the period: Jan-Mar, then May-Jun -> Jan-Mar only, the later months listed
    data = months({**base, **{(2026, m): 10.0 for m in (1, 2, 3, 5, 6)}})
    y = compute(data, date(2026, 7, 5))
    assert y.month_to == 3 and y.current.kg == 30.0
    assert [e["month"] for e in y.excluded] == ["2026-05", "2026-06"]
    # ... and in November, Jan-Mar is too old to be "the year so far"
    assert compute(data, today) is None

    # no January: nothing
    assert compute(months({**base, (2026, 2): 1.0}), today) is None

    # a month without a weight: the volume is not summed partially
    data = months({**base, **{(2026, m): 10.0 for m in range(1, 4)}})
    data[date(2026, 2, 1)] = agg(None, 50.0)
    y = compute(data, date(2026, 5, 5))
    from paladex.api.ytd import _figures
    assert _figures(y.cur_months)["net_weight_kg"] is None


def test_source_without_totals_is_summed_over_partners_in_both_years():
    cells = Months()
    for yy in (2025, 2026):
        for mm in range(1, 4):
            cells.cells[date(yy, mm, 1)] = {"p": agg(4.0, 8.0)}
    counted, summed, excluded = cells.counted()
    assert summed and len(counted) == 6 and not excluded


def test_full_or_stale_years_are_not_the_year_so_far():
    # the newest year is complete: the annual figure is the freshest
    assert compute(months({(2025, m): 5.0 for m in range(1, 13)}), date(2026, 2, 10)) is None
    # early in a year, last year's Jan-Nov still is the freshest period
    y = compute(months({**{(2025, m): 5.0 for m in range(1, 12)}, **{(2024, m): 4.0 for m in range(1, 13)}}),
                date(2026, 2, 10))
    assert y is not None and (y.year, y.month_to) == (2025, 11)
    # last month more than 6 months old (Sep 2025 seen in Nov 2026): stale
    assert compute(months({(2025, m): 5.0 for m in range(1, 10)}), date(2026, 11, 5)) is None


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_profile_leads_with_the_countrys_own_year_so_far(api, db):
    indec = make_source(db, "ar_official_t", country="ARG")
    comtrade = make_source(db, "un_comtrade_t")
    for m in range(1, 13):
        month(db, indec, "ARG", "WLD", PY, m, 1_000_000)
    for m in range(1, M + 1):
        month(db, indec, "ARG", "WLD", CY, m, 1_500_000, status="provisional")
    # a global dataset with the running year only: never mixed with INDEC's previous year
    for m in range(1, M + 1):
        month(db, comtrade, "ARG", "WLD", CY, m, 9_000_000)
    annual(db, comtrade, "ARG", PY, 11_000_000)
    db.commit()

    t = get(api, "/api/countries/ARG")["trade"]["export"]
    own = t["ytd"]["own"]
    assert t["ytd"]["status"] == "ok" and t["ytd"]["mirror"] is None
    assert own["source"]["key"] == "ar_official_t"                 # the comparable source
    assert (own["year"], own["month_from"], own["month_to"]) == (CY, 1, M)
    assert own["net_weight_kg"] == 1_500_000 * M
    assert own["previous"]["net_weight_kg"] == 1_000_000 * M          # same months, not the full year
    assert own["previous"]["period_label"] == (f"{PY}-01/{PY}-{M:02d}" if M > 1 else f"{PY}-01")
    assert own["change_volume_pct"] == 50.0
    assert own["usd_value"] == 4_500_000 * M and own["change_value_pct"] == 50.0
    assert own["data_status"] == "provisional" and own["frequency"] == "M"
    assert own["is_current_year"] is True and own["comparable"] is True
    # the full years are still there, as before
    assert t["latest"]["year"] == PY


def test_partial_newest_month_and_partner_sums(api, db):
    eurostat = make_source(db, "eurostat_t")
    comex = make_source(db, "br_comex_t", country="BRA")
    for yy, last in ((PY, 12), (CY, M)):
        for m in range(1, last + 1):
            month(db, eurostat, "ITA", "WLD", yy, m, 2_000_000, flow="import")
            month(db, eurostat, "ITA", "ARG", yy, m, 500_000, flow="import")
    # the next month arrives with a few partners and no total: left out, and said so
    if M < 12:
        month(db, eurostat, "ITA", "ARG", CY, M + 1, 100_000, flow="import")
    # Brazil's source never publishes a total: partner sums in both years, flagged
    for yy, last in ((PY, 12), (CY, M)):
        for m in range(1, last + 1):
            month(db, comex, "BRA", "USA", yy, m, 300_000)
            month(db, comex, "BRA", "DEU", yy, m, 100_000 if yy == PY else 200_000)
    db.commit()

    ita = get(api, "/api/countries/ITA")["trade"]["import"]["ytd"]["own"]
    assert ita["month_to"] == M and ita["net_weight_kg"] == 2_000_000 * M
    assert ita["change_volume_pct"] == 0.0
    if M < 12:
        assert ita["excluded_months"] == [{"month": f"{CY}-{M + 1:02d}", "reason": "no_total"}]

    bra = get(api, "/api/countries/BRA")["trade"]["export"]["ytd"]["own"]
    assert bra["summed_from_partners"] is True and bra["partners_count"] == 2
    assert bra["net_weight_kg"] == 500_000 * M and bra["previous"]["net_weight_kg"] == 400_000 * M
    assert bra["change_volume_pct"] == 25.0


def test_no_monthly_data_and_what_partners_declare(api, db):
    census = make_source(db, "us_census_t", country="USA")
    eurostat = make_source(db, "eurostat_t")
    comtrade = make_source(db, "un_comtrade_t")
    annual(db, comtrade, "IND", PY, 120_000_000)
    for yy, last in ((PY, 12), (CY, M)):
        for m in range(1, last + 1):
            month(db, census, "USA", "WLD", yy, m, 20_000_000, flow="import")
            month(db, census, "USA", "IND", yy, m, 8_000_000 if yy == CY else 10_000_000, flow="import")
            month(db, eurostat, "DEU", "WLD", yy, m, 6_000_000, flow="import")
            month(db, eurostat, "DEU", "IND", yy, m, 50_000, flow="import")
    db.commit()

    t = get(api, "/api/countries/IND")["trade"]["export"]
    assert t["ytd"]["own"] is None and t["ytd"]["status"] == "no_monthly"
    rows = {r["iso3"]: r for r in t["ytd"]["mirror"]["rows"]}
    assert t["ytd"]["mirror"]["declared_flow"] == "import"
    assert set(rows) == {"USA", "DEU"}                       # one row per declaring country, never summed
    assert rows["USA"]["source"]["key"] == "us_census_t" and rows["USA"]["change_volume_pct"] == -20.0
    assert rows["USA"]["net_weight_kg"] == 8_000_000 * M and rows["USA"]["link"] == "/paesi/USA"
    assert rows["DEU"]["source"]["key"] == "eurostat_t"
    # a flow with no monthly data at all on either side
    imp = get(api, "/api/countries/IND")["trade"]["import"]["ytd"]
    assert imp == {"own": None, "status": "no_monthly", "last_month": None, "mirror": None}


def test_stale_monthly_data_is_not_the_year_so_far(api, db):
    eurostat = make_source(db, "eurostat_t")
    for yy in (CY - 3, CY - 2):
        for m in range(1, 10 if yy == CY - 2 else 13):
            month(db, eurostat, "FRA", "WLD", yy, m, 1_000_000, flow="import")
    db.commit()
    y = get(api, "/api/countries/FRA")["trade"]["import"]["ytd"]
    assert y["own"] is None and y["status"] == "stale" and y["last_month"] == f"{CY - 2}-09"


def test_overview_lists_the_year_so_far_before_the_annual_ranking(api, db):
    census = make_source(db, "us_census_t", country="USA")
    indec = make_source(db, "ar_official_t", country="ARG")
    eurostat = make_source(db, "eurostat_t")
    comtrade = make_source(db, "un_comtrade_t")
    for rep in ("USA", "DEU"):
        annual(db, comtrade, rep, PY, 50_000_000, flow="import")
    annual(db, comtrade, "ARG", PY, 90_000_000)
    for yy, last in ((PY, 12), (CY, M)):
        for m in range(1, last + 1):
            month(db, census, "USA", "WLD", yy, m, 20_000_000, flow="import")
            month(db, eurostat, "DEU", "WLD", yy, m, 5_000_000, flow="import")
            month(db, indec, "ARG", "WLD", yy, m, 7_000_000)
            # the EU aggregate is not a country: never in the list
            month(db, eurostat, "EU27", "EXTRA_EU", yy, m, 15_000_000, flow="import")
    db.commit()

    trade = get(api, "/api/overview")["trade"]
    ytd = trade["ytd"]
    imp, exp = ytd["importers"], ytd["exporters"]
    assert imp["year"] == CY and [r["iso3"] for r in imp["rows"]] == ["USA", "DEU"]
    assert {r["source"]["key"] for r in imp["rows"]} == {"us_census_t", "eurostat_t"}
    assert all(r["month_to"] == M and r["comparable"] for r in imp["rows"])
    assert imp["rows"][0]["name"] == "Stati Uniti" and imp["rows"][0]["link"] == "/paesi/USA"
    assert [r["iso3"] for r in exp["rows"]] == ["ARG"]
    # the annual ranking stays
    assert trade["importers"] is not None


def test_faostat_newest_year_says_when_the_next_one_is_due(api, db):
    from sqlalchemy import select

    fao = db.scalars(select(Source).where(Source.key == "faostat")).one()    # the registered FAOSTAT source
    nass = make_source(db, "usda_nass_t", country="USA", category="production")
    for iso3, src, year, value in (("USA", fao, CY - 2, 60_960), ("USA", nass, CY - 1, 52_488), ("ARG", fao, CY - 2, 69_298)):
        start, end = year_bounds(year)
        ingest.record(db, ProductionStat, source_id=src.id, is_demo=False, series_key=f"{iso3}|production|{year}",
                      country_iso3=iso3, metric="production", value=value, unit="t", period_start=start,
                      period_end=end, period_label=str(year), frequency="A", published_at=end + timedelta(days=200),
                      data_status="published", reliability="official")
    db.commit()

    arg = get(api, "/api/countries/ARG")["production"]["metrics"][0]["series"][0]
    assert arg["next_release"] == {"year": CY - 1, "expected": f"{CY}-12", "overdue": TODAY >= date(CY + 1, 1, 1)}
    usa = get(api, "/api/countries/USA")["production"]["metrics"][0]["series"]
    # the newer national figure first, FAOSTAT after it
    assert [s["source"]["key"] for s in usa] == ["usda_nass_t", "faostat"]
    assert usa[0]["next_release"] is None
