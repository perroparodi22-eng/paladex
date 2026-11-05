"""ECB euro foreign exchange reference rates (free, no key, official).

https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/
First run downloads the full history (since 1999), later runs the last 90 days, unless the
newest stored rate is too old for the 90-day file to close the gap (app not opened for months,
data folder restored from an old backup): then the full history is downloaded again, so no
period is left without rates (prices in a gap could otherwise never be converted).
"""
from __future__ import annotations

from datetime import date, timedelta
from xml.etree import ElementTree as ET

from sqlalchemy import func, select

from ..enums import Reliability, SourceKind
from ..models import FxRate
from ..services import fx
from .base import CollectContext, Collector, CollectorError

HIST_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.xml"
HIST_90D_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"
# Use the 90-day file only when the newest stored rate is younger than this (~10 days of overlap).
MAX_GAP_FOR_90D_DAYS = 80


def parse_ecb_xml(content: bytes) -> list[tuple[date, str, float]]:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise CollectorError(f"ECB XML not parseable: {exc}") from exc
    out: list[tuple[date, str, float]] = []
    for cube in root.iter():
        if not cube.tag.endswith("Cube") or "time" not in cube.attrib:
            continue
        d = date.fromisoformat(cube.attrib["time"])
        for child in cube:
            cur, rate = child.attrib.get("currency"), child.attrib.get("rate")
            if cur and rate:
                out.append((d, cur, float(rate)))
    return out


class EcbFxCollector(Collector):
    key = "ecb_fx"
    name = "Tassi di cambio di riferimento BCE"
    name_en = "ECB euro foreign exchange reference rates"
    publisher = "European Central Bank"
    homepage = "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html"
    kind = SourceKind.API
    reliability = Reliability.OFFICIAL
    category = "fx"
    expected_update = "Ogni giorno lavorativo TARGET verso le 16:00 CET"
    expected_update_en = "Every TARGET working day around 16:00 CET"
    expected_max_age_days = 5
    terms_note = "ECB reference rates are published for information purposes; free reuse with attribution."
    schedule = {"trigger": "cron", "hour": 17, "minute": 15}
    order = 0

    def collect(self, ctx: CollectContext) -> None:
        newest_stored = ctx.session.scalar(select(func.max(FxRate.rate_date)))
        full = ctx.force or newest_stored is None or newest_stored < date.today() - timedelta(days=MAX_GAP_FOR_90D_DAYS)
        doc = ctx.fetch(HIST_URL if full else HIST_90D_URL, store=False)
        rows = parse_ecb_xml(doc.content)
        if not rows:
            raise CollectorError("ECB file contained no rates")
        if not full and newest_stored and min(r[0] for r in rows) > newest_stored + timedelta(days=fx.MAX_LOOKBACK_DAYS):
            # Safety net independent of the local clock: the 90-day file does not reach back to
            # our newest rate, so dates in between would stay without rates.
            ctx.warn(f"Tassi BCE: mancavano i cambi dal {newest_stored.isoformat()}; scaricato lo storico completo")
            doc = ctx.fetch(HIST_URL, store=False)
            rows = parse_ecb_xml(doc.content)
            if not rows:
                raise CollectorError("ECB file contained no rates")
        existing = {
            (d, c) for d, c in ctx.session.execute(
                select(FxRate.rate_date, FxRate.currency).where(FxRate.rate_date >= min(r[0] for r in rows))
            )
        }
        newest = None
        for d, cur, rate in rows:
            newest = d if newest is None or d > newest else newest
            if (d, cur) in existing:
                ctx.counters.count("unchanged")
                continue
            ctx.session.add(FxRate(rate_date=d, currency=cur, per_eur=rate, source_key=self.key))
            ctx.counters.count("new")
        ctx.counters.newest_published = newest
        ctx.counters.newest_period_label = newest.isoformat() if newest else None
        ctx.counters.newest_period_start = newest
