"""Currency conversion using locally stored ECB reference rates.

Convention: FxRate.per_eur = units of `currency` per 1 EUR (as published by the ECB).

Two conversion bases, recorded on every converted row (`fx_basis`, `fx_start`, `fx_end`):

* "spot"       daily / weekly quotes (and anything not M/Q/A): the most recent rate on or
               before the reference date (the period's last day, capped at today), at most
               14 days back. `fx_date` is the date of the rate used.
* "period_avg" monthly, quarterly and annual averages or totals: the mean of the ECB daily
               rates over the period (cross rates averaged day by day, never a ratio of two
               averages). Only computed when the rates cover at least 80 % of the period's
               working days; otherwise there is no conversion. `fx_date` = `fx_end`.

If no conversion is possible the result is None and the UI shows the original currency only
(we never guess a rate). A period still open when converted (`fx_end` < `period_end`) is
provisional: `backfill_normalised_prices()` recomputes it once the period has closed, and also
fills usd/eur columns that were empty because rates were missing at ingest time. Only the
derived columns change; source values and revisions are never touched.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import FxRate, PriceObservation, TradeFlowObservation

MAX_LOOKBACK_DAYS = 14
# Frequencies whose values are period averages / totals: converted at the period-average rate.
PERIOD_FREQUENCIES = frozenset({"M", "Q", "A"})
# Share of the period's working days (Mon-Fri) that must have an ECB rate. TARGET holidays are
# only ~6 days a year, so a complete ECB series is always above this.
MIN_PERIOD_COVERAGE = 0.8

BASIS_SPOT = "spot"
BASIS_PERIOD_AVG = "period_avg"


def rate_per_eur(session: Session, currency: str, on: date) -> tuple[float, date] | None:
    currency = currency.upper()
    if currency == "EUR":
        return 1.0, on
    row = session.scalars(
        select(FxRate)
        .where(FxRate.currency == currency, FxRate.rate_date <= on, FxRate.rate_date >= on - timedelta(days=MAX_LOOKBACK_DAYS))
        .order_by(FxRate.rate_date.desc())
        .limit(1)
    ).first()
    if row is None:
        return None
    return row.per_eur, row.rate_date


def convert(session: Session, amount: float | None, from_ccy: str, to_ccy: str, on: date) -> tuple[float, date] | None:
    if amount is None:
        return None
    from_ccy, to_ccy = from_ccy.upper(), to_ccy.upper()
    if from_ccy == to_ccy:
        return amount, on
    a = rate_per_eur(session, from_ccy, on)
    b = rate_per_eur(session, to_ccy, on)
    if a is None or b is None:
        return None
    eur = amount / a[0]
    return eur * b[0], min(a[1], b[1])


def fx_reference_date(period_end: date, today: date | None = None) -> date:
    """Rate date used for a period: its last day, capped at today."""
    today = today or date.today()
    return min(period_end, today)


# ---------------------------------------------------------------------------
# Period averages
# ---------------------------------------------------------------------------
def working_days(start: date, end: date) -> int:
    """Number of Monday-Friday days in [start, end]."""
    if end < start:
        return 0
    days = (end - start).days + 1
    weeks, rest = divmod(days, 7)
    wd = start.weekday()
    return weeks * 5 + sum(1 for i in range(rest) if (wd + i) % 7 < 5)


def _daily_rates(session: Session, currency: str, start: date, end: date) -> dict[date, float]:
    return dict(session.execute(
        select(FxRate.rate_date, FxRate.per_eur)
        .where(FxRate.currency == currency, FxRate.rate_date >= start, FxRate.rate_date <= end)
    ).all())


def period_cross_rate(session: Session, from_ccy: str, to_ccy: str, start: date, end: date) -> tuple[float, int] | None:
    """Mean over [start, end] of the daily ECB cross rate (`to_ccy` per 1 `from_ccy`), with the
    number of days used. None when the rates cover less than MIN_PERIOD_COVERAGE of the working
    days of the window (never a guess)."""
    from_ccy, to_ccy = from_ccy.upper(), to_ccy.upper()
    if end < start:
        return None
    if from_ccy == to_ccy:
        return 1.0, 0
    a = None if from_ccy == "EUR" else _daily_rates(session, from_ccy, start, end)
    b = None if to_ccy == "EUR" else _daily_rates(session, to_ccy, start, end)
    if a is None:
        days = set(b)
    elif b is None:
        days = set(a)
    else:
        days = set(a) & set(b)
    needed = max(1, math.ceil(MIN_PERIOD_COVERAGE * working_days(start, end)))
    if len(days) < needed:
        return None
    crosses = [(b[d] if b is not None else 1.0) / (a[d] if a is not None else 1.0) for d in days]
    return sum(crosses) / len(crosses), len(days)


def period_rate_per_eur(session: Session, currency: str, start: date, end: date) -> tuple[float, int] | None:
    """Mean ECB rate (units of `currency` per EUR) over [start, end] and the number of days used."""
    return period_cross_rate(session, "EUR", currency, start, end)


# ---------------------------------------------------------------------------
# Row normalisation
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FxBasis:
    basis: str                 # BASIS_SPOT | BASIS_PERIOD_AVG
    start: date | None         # period_avg: first day averaged
    end: date                  # last day the conversion covers (< period_end: provisional)
    rate_date: date | None     # spot: date of the ECB rate used; period_avg: = end


def _basis_for(frequency: str | None) -> str:
    return BASIS_PERIOD_AVG if (frequency or "").upper() in PERIOD_FREQUENCIES else BASIS_SPOT


def _newest_rate_date(session: Session, cache: dict | None) -> date | None:
    if cache is not None and "newest" in cache:
        return cache["newest"]
    newest = session.scalar(select(func.max(FxRate.rate_date)))
    if cache is not None:
        cache["newest"] = newest
    return newest


def conversion_factor(session: Session, from_ccy: str, to_ccy: str, *, period_start: date, period_end: date,
                      frequency: str | None, today: date | None = None,
                      cache: dict | None = None) -> tuple[float, FxBasis | None] | None:
    """Multiplier converting `from_ccy` amounts of this period into `to_ccy`, with the basis
    used (None for an identity conversion). None when no rate is available."""
    from_ccy, to_ccy = (from_ccy or "").upper(), to_ccy.upper()
    if from_ccy == to_ccy:
        return 1.0, None
    today = today or date.today()
    if _basis_for(frequency) == BASIS_SPOT:
        on = fx_reference_date(period_end, today)
        a = rate_per_eur(session, from_ccy, on)
        b = rate_per_eur(session, to_ccy, on)
        if a is None or b is None:
            return None
        return b[0] / a[0], FxBasis(BASIS_SPOT, None, on, min(a[1], b[1]))
    newest = _newest_rate_date(session, cache)
    if newest is None:
        return None
    # Up to today and up to the newest rate held: a period still open is averaged so far (provisional).
    end = min(period_end, today, newest)
    key = (from_ccy, to_ccy, period_start, end)
    if cache is not None and key in cache:
        avg = cache[key]
    else:
        avg = period_cross_rate(session, from_ccy, to_ccy, period_start, end)
        if cache is not None:
            cache[key] = avg
    if avg is None:
        return None
    return avg[0], FxBasis(BASIS_PERIOD_AVG, period_start, end, end)


def _apply_basis(obs, basis: FxBasis | None, frequency: str | None) -> None:
    obs.fx_basis = basis.basis if basis else _basis_for(frequency)
    obs.fx_start = basis.start if basis else None
    obs.fx_end = basis.end if basis else None


def normalise_price(session: Session, obs: PriceObservation, today: date | None = None, cache: dict | None = None) -> None:
    kw = dict(period_start=obs.period_start, period_end=obs.period_end, frequency=obs.frequency, today=today, cache=cache)
    usd = conversion_factor(session, obs.currency, "USD", **kw)
    eur = conversion_factor(session, obs.currency, "EUR", **kw)
    amount = obs.price_per_kg
    obs.usd_per_kg = round(amount * usd[0], 4) if usd and amount is not None else None
    obs.eur_per_kg = round(amount * eur[0], 4) if eur and amount is not None else None
    basis = (usd and usd[1]) or (eur and eur[1]) or None   # the real conversion (not USD->USD)
    obs.fx_date = basis.rate_date if basis else None
    _apply_basis(obs, basis, obs.frequency)


def normalise_trade(session: Session, obs: TradeFlowObservation, today: date | None = None, cache: dict | None = None) -> None:
    kw = dict(period_start=obs.period_start, period_end=obs.period_end, frequency=obs.frequency, today=today, cache=cache)
    usd = conversion_factor(session, obs.currency, "USD", **kw) if obs.value is not None else None
    eur = conversion_factor(session, obs.currency, "EUR", **kw) if obs.value is not None else None
    obs.usd_value = round(obs.value * usd[0], 2) if usd else None
    obs.eur_value = round(obs.value * eur[0], 2) if eur else None
    _apply_basis(obs, (usd and usd[1]) or (eur and eur[1]) or None, obs.frequency)


def _provisional(model, today: date):
    """Converted while the period was still open, and the period has closed since."""
    return (model.fx_end.is_not(None)) & (model.fx_end < model.period_end) & (model.period_end <= today)


def _lost_value(before: tuple, after: tuple) -> bool:
    return any(b is not None and a is None for b, a in zip(before, after))


def _rows(session: Session, model, condition, chunk: int = 500):
    """Matching rows, loaded and flushed in chunks: the one-off recompute after an upgrade can
    cover every trade row (Comext alone: ~100k), which must not all sit in memory at once."""
    ids = session.scalars(select(model.id).where(condition).order_by(model.id)).all()
    for i in range(0, len(ids), chunk):
        yield from session.scalars(select(model).where(model.id.in_(ids[i:i + chunk]))).all()
        session.flush()   # converted rows become clean, so the session no longer pins them


def backfill_normalised_prices(session: Session, today: date | None = None) -> int:
    """Fill usd/eur columns that were empty because rates were missing at ingest time, recompute
    provisional conversions of periods that have closed since, and (once) rows converted before
    the conversion basis was recorded. Returns the number of rows whose usd/eur values changed."""
    today = today or date.today()
    cache: dict = {}
    n = 0
    P = PriceObservation
    for obs in _rows(session, P, or_(
        P.usd_per_kg.is_(None), P.eur_per_kg.is_(None),
        (P.is_demo.is_(False) & (P.fx_basis.is_(None) | _provisional(P, today))),
    )):
        before = (obs.usd_per_kg, obs.eur_per_kg, obs.fx_date, obs.fx_basis, obs.fx_start, obs.fx_end)
        provisional = obs.fx_end is not None and obs.fx_end < obs.period_end
        normalise_price(session, obs, today=today, cache=cache)
        if provisional and _lost_value(before[:2], (obs.usd_per_kg, obs.eur_per_kg)):
            # the closed period cannot be converted yet: keep the (labelled) provisional values
            obs.usd_per_kg, obs.eur_per_kg, obs.fx_date, obs.fx_basis, obs.fx_start, obs.fx_end = before
        n += before[:2] != (obs.usd_per_kg, obs.eur_per_kg)
    T = TradeFlowObservation
    for t in _rows(session, T, T.value.is_not(None) & or_(
        T.usd_value.is_(None), T.eur_value.is_(None),
        (T.is_demo.is_(False) & (T.fx_basis.is_(None) | _provisional(T, today))),
    )):
        before = (t.usd_value, t.eur_value, t.fx_basis, t.fx_start, t.fx_end)
        provisional = t.fx_end is not None and t.fx_end < t.period_end
        normalise_trade(session, t, today=today, cache=cache)
        if provisional and _lost_value(before[:2], (t.usd_value, t.eur_value)):
            t.usd_value, t.eur_value, t.fx_basis, t.fx_start, t.fx_end = before
        n += before[:2] != (t.usd_value, t.eur_value)
    return n
