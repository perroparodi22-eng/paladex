"""FX: ECB history gaps (F4) and period-average conversion of M/Q/A values (F5)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from paladex.collectors.fx_ecb import HIST_90D_URL, HIST_URL
from paladex.models import FxRate, PriceObservation, Source, TradeFlowObservation
from paladex.services import fx, ingest

TODAY = date(2026, 11, 4)


def _weekdays(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _seed(db, currency: str, days: list[date], rate) -> None:
    for d in days:
        db.add(FxRate(rate_date=d, currency=currency, per_eur=rate(d), source_key="ecb_fx"))
    db.flush()


def _ecb_xml(days: list[date], rate=lambda d: 1.1) -> bytes:
    cubes = "".join(f'<Cube time="{d.isoformat()}"><Cube currency="USD" rate="{rate(d):.4f}"/></Cube>'
                    for d in sorted(days, reverse=True))
    return ('<?xml version="1.0" encoding="UTF-8"?><gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" '
            'xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref"><gesmes:subject>Reference rates</gesmes:subject>'
            f'<Cube>{cubes}</Cube></gesmes:Envelope>').encode()


def _price(db, *, currency: str, start: date, end: date, label: str, freq: str, value: float = 10.0,
           key: str = "x", is_demo: bool = False, **extra) -> PriceObservation:
    src = db.scalars(select(Source).where(Source.key == "ecb_fx")).one()
    row = ingest.record(
        db, PriceObservation, source_id=src.id, series_key=f"wholesale_bulk|{key}|{label}", is_demo=is_demo,
        price_type="wholesale_bulk", variety="polyflora", price_value=value, currency=currency, unit="kg",
        price_per_kg=value, period_start=start, period_end=end, period_label=label, frequency=freq,
        data_status="published", reliability="official", **extra,
    )[1]
    db.flush()
    return row


# ---------------------------------------------------------------------- F4: ECB history gap
def test_ecb_downloads_full_history_when_the_90_day_file_cannot_close_the_gap(run_with_routes, session_factory):
    today = date.today()
    first = _weekdays(today - timedelta(days=200), today - timedelta(days=180))
    assert run_with_routes("ecb_fx", {HIST_URL: _ecb_xml(first)})["status"] == "success"

    # A weekly USD price whose week falls ~4 months back: no rate within 14 days yet.
    gap_end = today - timedelta(days=120)
    with session_factory() as s:
        p = _price(s, currency="USD", start=gap_end - timedelta(days=6), end=gap_end, label="gap", freq="W")
        fx.normalise_price(s, p)
        assert p.eur_per_kg is None

    # Months later: the 90-day file reaches back only 89 days; the full history has everything.
    recent = _weekdays(today - timedelta(days=89), today - timedelta(days=1))
    full = _weekdays(today - timedelta(days=200), today - timedelta(days=1))
    res = run_with_routes("ecb_fx", {HIST_90D_URL: _ecb_xml(recent), HIST_URL: _ecb_xml(full)})
    assert res["status"] == "success"
    with session_factory() as s:
        dates = set(s.scalars(select(FxRate.rate_date)))
        assert set(full) <= dates      # the gap was filled from the full history
        fx.backfill_normalised_prices(s)
    with session_factory() as s:
        p = s.scalars(select(PriceObservation).where(PriceObservation.period_label == "gap")).one()
        assert p.eur_per_kg == pytest.approx(10 / 1.1, abs=1e-4) and p.fx_basis == "spot"


def test_ecb_gap_safety_net_does_not_depend_on_the_local_clock(run_with_routes, session_factory):
    today = date.today()
    first = _weekdays(today - timedelta(days=75), today - timedelta(days=70))   # recent enough for the 90-day file
    assert run_with_routes("ecb_fx", {HIST_URL: _ecb_xml(first)})["status"] == "success"
    # ... but this 90-day file starts long after our newest rate (e.g. a wrong PC clock)
    recent = _weekdays(today - timedelta(days=40), today - timedelta(days=1))
    full = _weekdays(today - timedelta(days=75), today - timedelta(days=1))
    res = run_with_routes("ecb_fx", {HIST_90D_URL: _ecb_xml(recent), HIST_URL: _ecb_xml(full)})
    assert res["status"] == "partial" and "storico completo" in res["warnings"][0]
    with session_factory() as s:
        assert set(full) <= set(s.scalars(select(FxRate.rate_date)))


# ------------------------------------------------------------- F5: period-average conversion
def test_annual_value_converts_at_the_yearly_mean(db):
    days = _weekdays(date(2024, 1, 1), date(2024, 12, 31))
    usd = lambda d: 1.0 + d.timetuple().tm_yday / 1000            # 1.001 ... 1.366 (year-end far from the mean)
    _seed(db, "USD", days, usd)
    p = _price(db, currency="EUR", start=date(2024, 1, 1), end=date(2024, 12, 31), label="2024", freq="A")
    fx.normalise_price(db, p)
    mean = sum(usd(d) for d in days) / len(days)
    assert p.usd_per_kg == round(10 * mean, 4)
    assert p.usd_per_kg != round(10 * usd(date(2024, 12, 31)), 4)    # not the 31 December spot rate
    assert p.eur_per_kg == 10.0
    assert (p.fx_basis, p.fx_start, p.fx_end, p.fx_date) == ("period_avg", date(2024, 1, 1), date(2024, 12, 31),
                                                             date(2024, 12, 31))


def test_cross_rates_are_averaged_day_by_day(db):
    days = _weekdays(date(2023, 1, 1), date(2023, 12, 31))
    try_rate = lambda d: 20 + d.timetuple().tm_yday * 0.04          # TRY per EUR, ~20 -> ~34.6
    usd_rate = lambda d: 1.05 + d.timetuple().tm_yday * 0.0002
    _seed(db, "TRY", days, try_rate)
    _seed(db, "USD", days, usd_rate)
    p = _price(db, currency="TRY", start=date(2023, 1, 1), end=date(2023, 12, 31), label="2023", freq="A", value=100.0)
    fx.normalise_price(db, p)
    exp_eur = 100 * sum(1 / try_rate(d) for d in days) / len(days)
    exp_usd = 100 * sum(usd_rate(d) / try_rate(d) for d in days) / len(days)
    assert p.eur_per_kg == round(exp_eur, 4) and p.usd_per_kg == round(exp_usd, 4)
    # trade totals use the same basis
    src = db.scalars(select(Source).where(Source.key == "ecb_fx")).one()
    t = ingest.record(db, TradeFlowObservation, source_id=src.id, series_key="t", reporter_iso3="TUR", partner_iso3="WLD",
                      flow="export", currency="TRY", value=1_000_000.0, net_weight_kg=1000.0,
                      period_start=date(2023, 1, 1), period_end=date(2023, 12, 31), period_label="2023", frequency="A",
                      data_status="published", reliability="official")[1]
    fx.normalise_trade(db, t)
    assert t.usd_value == round(1_000_000 * exp_usd / 100, 2) and t.fx_basis == "period_avg"


def test_too_few_rate_days_give_no_conversion(db):
    days = _weekdays(date(2024, 1, 1), date(2024, 12, 31))[::2]      # half the working days only
    _seed(db, "USD", days, lambda d: 1.1)
    p = _price(db, currency="EUR", start=date(2024, 1, 1), end=date(2024, 12, 31), label="2024", freq="A")
    fx.normalise_price(db, p)
    assert p.usd_per_kg is None and p.eur_per_kg == 10.0             # never a guess
    assert p.fx_basis == "period_avg" and p.fx_end is None


def test_daily_and_weekly_quotes_keep_the_spot_rate(db):
    _seed(db, "USD", _weekdays(date(2026, 10, 1), date(2026, 10, 30)), lambda d: 1.0 + d.day / 100)
    p = _price(db, currency="EUR", start=date(2026, 10, 26), end=date(2026, 11, 1), label="2026-W44", freq="W")
    fx.normalise_price(db, p)
    assert p.usd_per_kg == round(10 * 1.30, 4)                        # Friday 30 October, the last rate before
    assert (p.fx_basis, p.fx_date, p.fx_end) == ("spot", date(2026, 10, 30), date(2026, 11, 1))


def test_open_period_is_recomputed_once_it_has_closed(db):
    _seed(db, "USD", _weekdays(date(2026, 10, 1), date(2026, 10, 13)), lambda d: 1.10)
    p = _price(db, currency="EUR", start=date(2026, 10, 1), end=date(2026, 10, 31), label="2026-10", freq="M")
    fx.normalise_price(db, p, today=date(2026, 10, 14))
    assert p.usd_per_kg == 11.0 and p.fx_end == date(2026, 10, 13)   # provisional: month still open
    db.flush()
    # still open: left alone
    fx.backfill_normalised_prices(db, today=date(2026, 10, 20))
    assert p.usd_per_kg == 11.0
    later = _weekdays(date(2026, 10, 14), date(2026, 10, 30))
    _seed(db, "USD", later, lambda d: 1.20)
    _seed(db, "USD", [date(2026, 11, 2)], lambda d: 1.30)
    fx.backfill_normalised_prices(db, today=TODAY)
    n_all = len(_weekdays(date(2026, 10, 1), date(2026, 10, 31)))
    mean = (1.10 * (n_all - len(later)) + 1.20 * len(later)) / n_all
    assert p.usd_per_kg == round(10 * mean, 4)
    assert (p.fx_basis, p.fx_start, p.fx_end) == ("period_avg", date(2026, 10, 1), date(2026, 10, 31))
    assert p.price_value == 10.0 and p.revision == 1                # source value and revisions untouched


def test_rows_converted_before_the_basis_was_recorded_are_recomputed_once(db):
    days = _weekdays(date(2024, 1, 1), date(2024, 12, 31))
    _seed(db, "USD", days, lambda d: 1.0 + d.timetuple().tm_yday / 1000)
    old = _price(db, currency="EUR", start=date(2024, 1, 1), end=date(2024, 12, 31), label="2024", freq="A",
                 usd_per_kg=13.66, eur_per_kg=10.0, fx_date=date(2024, 12, 31))   # spot at year end, no basis
    demo = _price(db, currency="EUR", start=date(2024, 1, 1), end=date(2024, 12, 31), label="2024", freq="A",
                  key="demo", is_demo=True, usd_per_kg=10.8, eur_per_kg=10.0)
    fx.backfill_normalised_prices(db, today=TODAY)
    assert old.fx_basis == "period_avg" and old.usd_per_kg != 13.66
    assert demo.usd_per_kg == 10.8 and demo.fx_basis is None          # demo rows keep their own values
