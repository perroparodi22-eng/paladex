"""Currency conversion using locally stored ECB reference rates.

Convention: FxRate.per_eur = units of `currency` per 1 EUR (as published by the ECB).
Conversions use the most recent rate on or before the requested date (max 14 days back);
if there is none, the conversion returns None and the UI shows the original currency only
(we never guess a rate). `backfill_normalised_prices()` fills usd/eur columns later once
rates arrive.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from ..models import FxRate, PriceObservation, TradeFlowObservation

MAX_LOOKBACK_DAYS = 14


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


def normalise_price(session: Session, obs: PriceObservation) -> None:
    on = fx_reference_date(obs.period_end)
    usd = convert(session, obs.price_per_kg, obs.currency, "USD", on)
    eur = convert(session, obs.price_per_kg, obs.currency, "EUR", on)
    obs.usd_per_kg = round(usd[0], 4) if usd else None
    obs.eur_per_kg = round(eur[0], 4) if eur else None
    obs.fx_date = (usd or eur or (None, None))[1]


def normalise_trade(session: Session, obs: TradeFlowObservation) -> None:
    on = fx_reference_date(obs.period_end)
    usd = convert(session, obs.value, obs.currency, "USD", on)
    eur = convert(session, obs.value, obs.currency, "EUR", on)
    obs.usd_value = round(usd[0], 2) if usd else None
    obs.eur_value = round(eur[0], 2) if eur else None


def backfill_normalised_prices(session: Session) -> int:
    """Fill usd/eur columns that were empty because rates were missing at ingest time."""
    n = 0
    rows = session.scalars(
        select(PriceObservation).where(or_(PriceObservation.usd_per_kg.is_(None), PriceObservation.eur_per_kg.is_(None)))
    ).all()
    for obs in rows:
        before = (obs.usd_per_kg, obs.eur_per_kg)
        normalise_price(session, obs)
        n += before != (obs.usd_per_kg, obs.eur_per_kg)
    trows = session.scalars(
        select(TradeFlowObservation).where(
            TradeFlowObservation.value.is_not(None),
            or_(TradeFlowObservation.usd_value.is_(None), TradeFlowObservation.eur_value.is_(None)),
        )
    ).all()
    for t in trows:
        before = (t.usd_value, t.eur_value)
        normalise_trade(session, t)
        n += before != (t.usd_value, t.eur_value)
    return n
