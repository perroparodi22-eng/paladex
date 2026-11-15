"""Thailand: official honey exports and imports by partner country, monthly.

* ``th_customs_honey``: Thai Customs Department, "Statistic report" (customs.go.th), natural honey,
  statistic code 04090000000 (the 11-digit level is the only one published with quantities). One
  page per flow and month: every partner country with the month's quantity (kg) and value (baht:
  FOB for exports, CIF for imports), the cumulative figures of the year, and a SUM row. No key, no
  login; the page answers a plain link, which is the link shown to the reader.

  Found on 15 Nov 2026 (owner: "try to find other sources ... official 2025 exports for Thailand"):
  until then Thailand's page showed FAO's yearly estimate and what the buying countries declare.
  The page states the latest month released (September 2026 on that day).

  What is stored: one trade row per partner and month with a quantity or a value, plus the month's
  total as partner ``WLD`` (the page's own SUM row, never a sum made here); unit values as prices
  only above a minimum weight. The first run reads from January two years before the latest month;
  later runs read the last few months again (the Department reserves the right to revise).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from html import unescape
from urllib.parse import urlencode

from sqlalchemy import select

from ..enums import DataStatus, PriceType, Reliability, SourceKind, TradeFlow, Variety
from ..models import TradeFlowObservation
from ..reference.countries import country_name
from .base import CollectContext, Collector, CollectorError, month_bounds
from .eu import _get_state, _set_state, map_geo

log = logging.getLogger(__name__)

TH_URL = "https://www.customs.go.th/statistic_report.php"
TH_CODE = "04090000000"
TH_BACKFILL_YEARS = 2               # first run: from January of (latest year - 2)
TH_REPULL_MONTHS = 4                # later runs: the last months again (revisions)
MIN_UNIT_VALUE_WEIGHT_KG = 1000.0   # below this a unit value is a parcel, not a price
VALUE_BASIS = {"export": "FOB", "import": "CIF"}
_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10,
           "nov": 11, "dec": 12}
# codes of the page that are not countries (zones, "other country", the high seas)
_NOT_COUNTRIES = {"ZZ", "FZ", "EZ", "OT", "YY", "DD"}


def th_params(flow: str, year: int, month: int) -> dict:
    return {"lang": "en", "show_search": "1", "top_menu": "menu_homepage", "tab": "by_country", "imex_type": flow,
            "tariff_code": TH_CODE, "country_code": "", "month": str(month), "year": str(year)}


def th_page_url(flow: str, year: int, month: int) -> str:
    """The same page as a link a person can open."""
    return f"{TH_URL}?{urlencode(th_params(flow, year, month))}"


@dataclass(frozen=True)
class ThRow:
    code: str            # as published (ISO alpha-2, or one of the page's own codes)
    name: str
    kg: float
    value: float         # baht


@dataclass
class ThPage:
    flow: str
    year: int
    month: int
    basis: str                       # "FOB" | "CIF", as the page's column says
    rows: list[ThRow]
    total_kg: float | None
    total_value: float | None
    latest_released: tuple[int, int] | None


def _cells(row_html: str) -> list[str]:
    return [re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", c))).strip()
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.S)]


def _num(text: str) -> float:
    return float(text.replace(",", "").strip() or 0)


def _month_year(label: str) -> tuple[int, int] | None:
    m = re.fullmatch(r"\s*([A-Za-z]{3})[a-z]*\.?\s+((?:19|20)\d{2})\s*", label)
    if not m or m.group(1).lower() not in _MONTHS:
        return None
    return int(m.group(2)), _MONTHS[m.group(1).lower()]


def parse_latest_released(text: str) -> tuple[int, int] | None:
    """(year, month) of "Latest released: September 2026" on the page."""
    plain = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", text)))
    m = re.search(r"Latest released\s*:?\s*([A-Za-z]+\.?\s+(?:19|20)\d{2})", plain)
    return _month_year(m.group(1)) if m else None


def parse_th_customs(content: bytes | str, flow: str, year: int, month: int) -> ThPage:
    """Read one "by country" page. Raises CollectorError when the page is not the table asked for:
    another month, no quantity in kilograms, or a value column that is not baht FOB/CIF."""
    html = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
    latest = parse_latest_released(html)
    table = next((t for t in re.findall(r"<table.*?</table>", html, re.S)
                  if re.search(r">\s*COUNTRY\s*<", t)), None)
    if table is None:
        raise CollectorError(f"Thai Customs: no table by country on the page for {flow} {year}-{month:02d}")
    rows = [c for c in (_cells(r) for r in re.findall(r"<tr.*?</tr>", table, re.S)) if c]
    head, sub = rows[0], rows[1] if len(rows) > 1 else []
    got = _month_year(head[1]) if len(head) > 1 else None
    if got != (year, month):
        raise CollectorError(f"Thai Customs: asked {flow} {year}-{month:02d}, the page shows {head[1:2]}")
    if "(KGM)" not in re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html))):
        raise CollectorError("Thai Customs: the page no longer says the quantity is in kilograms (KGM); nothing stored")
    if len(sub) < 4 or sub[0] != "Quantity" or "Baht" not in sub[1]:
        raise CollectorError(f"Thai Customs: unexpected columns {sub}; nothing stored")
    basis = sub[1].split("(")[0].strip().upper()
    if basis != VALUE_BASIS[flow]:
        raise CollectorError(f"Thai Customs: {flow} values are {basis!r} on the page, {VALUE_BASIS[flow]} was expected")
    out: list[ThRow] = []
    total_kg = total_value = None
    for c in rows[2:]:
        if c[0] == "SUM" and len(c) >= 5:
            total_kg, total_value = _num(c[1]), _num(c[2])
        elif len(c) >= 6 and re.fullmatch(r"[A-Z]{2}", c[0]):
            out.append(ThRow(code=c[0], name=c[1], kg=_num(c[2]), value=_num(c[3])))
    return ThPage(flow=flow, year=year, month=month, basis=basis, rows=out, total_kg=total_kg, total_value=total_value,
                  latest_released=latest)


def _months_between(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    out, (y, m) = [], start
    while (y, m) <= end:
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _shift(ym: tuple[int, int], months: int) -> tuple[int, int]:
    n = ym[0] * 12 + (ym[1] - 1) + months
    return n // 12, n % 12 + 1


class ThCustomsHoneyCollector(Collector):
    key = "th_customs_honey"
    name = "Thailandia – Dogana (Thai Customs): export e import di miele per paese, mensile"
    name_en = "Thailand – Customs Department: honey exports and imports by country, monthly"
    publisher = "Thai Customs Department"
    homepage = "https://www.customs.go.th/statistic_report.php?lang=en&show_search=1"
    kind = SourceKind.HTML
    reliability = Reliability.OFFICIAL
    category = "trade"
    country_iso3 = "THA"
    language = "en"
    expected_update = "Mensile (la pagina indica l'ultimo mese pubblicato); controllato ogni giorno"
    expected_update_en = "Monthly (the page states the latest month released); checked every day"
    expected_max_age_days = 75
    terms_note = ("Thai Customs Department, Statistic report, statistic code 04090000000 (natural honey): quantity in "
                  "kilograms and value in baht (FOB for exports, CIF for imports) by partner country. The Department "
                  "reserves the right to revise the figures; recent months are read again at every check.")
    schedule = {"trigger": "cron", "hour": 8, "minute": 50}

    def collect(self, ctx: CollectContext) -> None:
        probe = ctx.fetch(TH_URL, params={"lang": "en", "show_search": "1"}, store=False)
        latest = parse_latest_released(probe.text)
        if latest is None:
            raise CollectorError("Thai Customs: the page does not state the latest month released; nothing read")
        state = _get_state(ctx.session, self.key)
        has_rows = ctx.session.scalar(select(TradeFlowObservation.id).where(
            TradeFlowObservation.source_id == ctx.source.id).limit(1)) is not None
        if state.get("backfilled") and has_rows and not ctx.force:
            start = _shift(latest, -(TH_REPULL_MONTHS - 1))
        else:
            start = (latest[0] - TH_BACKFILL_YEARS, 1)
        for year, month in _months_between(start, latest):
            for flow in ("export", "import"):
                doc = ctx.fetch(TH_URL, params=th_params(flow, year, month),
                                title=f"Thai Customs, honey {flow}s by country, {year}-{month:02d}")
                self._store(ctx, parse_th_customs(doc.content, flow, year, month), doc.raw_document_id)
            ctx.checkpoint()
        _set_state(ctx.session, self.key, {"backfilled": True, "latest_released": f"{latest[0]:04d}-{latest[1]:02d}"})

    def _store(self, ctx: CollectContext, page: ThPage, raw_id: int | None) -> None:
        ps, pe = month_bounds(page.year, page.month)
        label = f"{page.year:04d}-{page.month:02d}"
        flow = TradeFlow.EXPORT.value if page.flow == "export" else TradeFlow.IMPORT.value
        url = th_page_url(page.flow, page.year, page.month)
        common = dict(period_start=ps, period_end=pe, period_label=label, frequency="M", data_status=DataStatus.PUBLISHED,
                      reliability=Reliability.OFFICIAL, source_url=url, raw_document_id=raw_id or None)
        what = "esportazioni" if page.flow == "export" else "importazioni"
        listed_kg = 0.0
        for r in page.rows:
            if r.kg <= 0 and r.value <= 0:
                continue                      # the country traded in other months of the year, not in this one
            listed_kg += r.kg
            iso3 = None if r.code in _NOT_COUNTRIES else map_geo(r.code)
            if iso3 is None or len(iso3) != 3 or country_name(iso3, "en") in ("", iso3):
                continue                      # a zone or a code Paladex does not know: it stays in the total only
            ctx.add_trade(
                series_key=f"th_customs|{page.flow}|{iso3}|{label}", hs_code="0409", reporter_iso3="THA", partner_iso3=iso3,
                flow=flow, currency="THB", value=r.value or None, net_weight_kg=r.kg or None,
                value_basis=page.basis,
                extra={"statistic_code": TH_CODE, "country_as_published": f"{r.code} {r.name}"},
                notes=f"Dogana thailandese, miele naturale ({TH_CODE}), {what} {label}: {r.name}.", **common)
            if r.kg >= MIN_UNIT_VALUE_WEIGHT_KG and r.value > 0:
                origin, market = ("THA", iso3) if page.flow == "export" else (iso3, "THA")
                ctx.add_price(
                    series_key=f"th_customs|{origin}|{market}|{label}",
                    price_type=PriceType.EXPORT_UNIT_VALUE if page.flow == "export" else PriceType.IMPORT_UNIT_VALUE,
                    variety=Variety.UNSPECIFIED.value, variety_raw=f"Natural honey ({TH_CODE})",
                    price_value=round(r.value / r.kg, 4), currency="THB", unit="kg", origin_iso3=origin,
                    origin_label=country_name(origin, "en"), market_iso3=market,
                    market_location=country_name(market, "en"), terms=page.basis, volume_kg=r.kg,
                    notes=(f"Thai Customs, natural honey: value {page.basis} divided by the kilograms declared "
                           f"({label}). A customs average, not a price list."), **common)
        if page.total_kg is None or page.total_value is None:
            if page.rows:
                ctx.warn(f"Thai Customs {page.flow} {label}: no SUM row on the page; the month's total is not stored")
            return
        if abs(listed_kg - page.total_kg) > 1.0:
            ctx.warn(f"Thai Customs {page.flow} {label}: the countries add up to {listed_kg:,.0f} kg, the page's "
                     f"SUM says {page.total_kg:,.0f} kg; both stored as published")
        if page.total_kg > 0 or page.total_value > 0:
            ctx.add_trade(
                series_key=f"th_customs|{page.flow}|WLD|{label}", hs_code="0409", reporter_iso3="THA", partner_iso3="WLD",
                flow=flow, currency="THB", value=page.total_value or None, net_weight_kg=page.total_kg or None,
                value_basis=page.basis, extra={"statistic_code": TH_CODE, "row": "SUM"},
                notes=f"Dogana thailandese, miele naturale ({TH_CODE}): totale delle {what} del mese (riga SUM della pagina).",
                **common)


__all__ = ["ThCustomsHoneyCollector", "ThPage", "ThRow", "parse_latest_released", "parse_th_customs", "th_page_url", "th_params"]
