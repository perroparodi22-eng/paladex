"""Clearly-labelled DEMONSTRATION data, used only to try the interface before real sources
are connected. Every row has is_demo=True, data_status="demo", reliability="demo", is
attached to the "demo" source and is badged "DEMO" in the UI. `purge_demo()` removes it all.

The numbers are synthetic (deterministic pseudo-random walk) and MUST NOT be read as market
information.
"""
from __future__ import annotations

import math
import random
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..collectors.base import month_bounds, year_bounds
from ..enums import DataStatus, PriceType, Reliability, TradeFlow, Variety
from ..models import (
    NewsArticle,
    PriceObservation,
    ProductionStat,
    RegulationItem,
    Report,
    Source,
    SupplierQuote,
    TariffMeasure,
    TradeFlowObservation,
)
from . import ingest

DEMO_SERIES = [
    ("ARG", Variety.POLYFLORA, 3.10), ("ARG", Variety.CLOVER, 3.25), ("UKR", Variety.SUNFLOWER, 2.40),
    ("UKR", Variety.ACACIA, 4.60), ("CHN", Variety.POLYFLORA, 1.70), ("BRA", Variety.ORGANIC_POLYFLORA, 3.60),
    ("VNM", Variety.POLYFLORA, 1.95), ("HUN", Variety.ACACIA, 6.10), ("SRB", Variety.ACACIA, 5.40),
    ("ITA", Variety.CHESTNUT, 7.20), ("ITA", Variety.ACACIA, 9.30), ("ESP", Variety.ORANGE_BLOSSOM, 5.10),
    ("MEX", Variety.POLYFLORA, 3.40), ("IND", Variety.POLYFLORA, 2.10), ("URY", Variety.EUCALYPTUS, 3.00),
]


def _demo_source(session: Session) -> Source:
    return session.scalars(select(Source).where(Source.key == "demo")).one()


def seed_demo(session: Session, months: int = 48, today: date | None = None) -> int:
    today = today or date.today()
    src = _demo_source(session)
    rng = random.Random(20261102)
    n = 0
    common = dict(data_status=DataStatus.DEMO.value, reliability=Reliability.DEMO.value,
                  notes="DATO DIMOSTRATIVO — non reale / DEMO DATA — not real", source_url=None)
    for origin, variety, base in DEMO_SERIES:
        price = base
        for i in range(months, 0, -1):
            y, m = today.year, today.month - i
            while m <= 0:
                m += 12
                y -= 1
            start, end = month_bounds(y, m)
            price = max(0.8, price * (1 + rng.gauss(0.002, 0.025)) + 0.05 * math.sin(m / 12 * 2 * math.pi))
            ingest.record(
                session, PriceObservation, source_id=src.id, is_demo=True,
                series_key=f"demo|{origin}|{variety}|{y}-{m:02d}",
                price_type=PriceType.WHOLESALE_BULK.value, origin_iso3=origin, origin_label=origin,
                market_iso3="ITA", variety=variety.value, variety_raw=variety.value, price_value=round(price, 2),
                price_low=round(price * 0.96, 2), price_high=round(price * 1.04, 2), currency="USD", unit="kg",
                price_per_kg=round(price, 2), usd_per_kg=round(price, 2), eur_per_kg=round(price / 1.08, 2),
                period_start=start, period_end=end, period_label=f"{y}-{m:02d}", frequency="M",
                published_at=end, terms="DEMO — bulk, drums", **common,
            )
            n += 1
    for reporter, partner, kt in (("DEU", "UKR", 21000), ("DEU", "MEX", 9000), ("USA", "ARG", 60000),
                                  ("USA", "IND", 55000), ("ITA", "HUN", 6000), ("ITA", "ARG", 4000)):
        for yr in range(today.year - 6, today.year):
            start, end = year_bounds(yr)
            kg = kt * 1000 * (1 + rng.gauss(0, 0.12))
            val = kg * rng.uniform(2.0, 3.8)
            ingest.record(
                session, TradeFlowObservation, source_id=src.id, is_demo=True,
                series_key=f"demo|{reporter}|{partner}|{yr}", hs_code="0409", reporter_iso3=reporter,
                partner_iso3=partner, flow=TradeFlow.IMPORT.value, net_weight_kg=round(kg), value=round(val),
                currency="USD", value_basis="CIF", unit_value_per_kg=round(val / kg, 3), usd_value=round(val),
                period_start=start, period_end=end, period_label=str(yr), frequency="A", published_at=end, **common,
            )
            n += 1
    for iso3, t in (("CHN", 460000), ("TUR", 95000), ("IRN", 75000), ("ARG", 70000), ("UKR", 65000), ("IND", 70000)):
        for yr in range(today.year - 8, today.year - 1):
            start, end = year_bounds(yr)
            ingest.record(
                session, ProductionStat, source_id=src.id, is_demo=True, series_key=f"demo|{iso3}|{yr}",
                country_iso3=iso3, metric="production", value=round(t * (1 + rng.gauss(0, 0.07))), unit="t",
                period_start=start, period_end=end, period_label=str(yr), frequency="A", published_at=end, **common,
            )
            n += 1
    if not session.scalars(select(SupplierQuote).where(SupplierQuote.is_demo.is_(True))).first():
        for name, origin, var, p, inc in (("DEMO Exporter A", "ARG", Variety.POLYFLORA, 3.05, "FOB"),
                                          ("DEMO Exporter B", "UKR", Variety.SUNFLOWER, 2.35, "CIF"),
                                          ("DEMO Exporter C", "SRB", Variety.ACACIA, 5.30, "DAP")):
            session.add(SupplierQuote(
                supplier_name=name, origin_iso3=origin, variety=var.value, price_per_kg=p, currency="USD",
                quantity_kg=20000, packaging="300 kg metal drums", incoterm=inc, date_received=today,
                notes="DEMO — offerta fittizia", is_demo=True,
            ))
            n += 1
    session.flush()
    return n


def purge_demo(session: Session) -> int:
    n = 0
    for model in (PriceObservation, TradeFlowObservation, ProductionStat, NewsArticle, Report, RegulationItem, SupplierQuote,
                  TariffMeasure):
        res = session.execute(delete(model).where(model.is_demo.is_(True)))
        n += res.rowcount or 0
    return n
