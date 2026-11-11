"""Honey prices of European countries from official statistics.

* ``eurostat_honey_prices``: Eurostat, "Selling prices of animal products (absolute prices) - annual
  price" (dataset ``apri_ap_anouta``), product ``12920000`` "Honey - prices per 100 kg". One figure
  per country and year, in euro and in the national currency: the average price the country's
  producers sold honey at, as its statistical office reports it to Eurostat. It is the only free,
  machine-readable honey price that exists for most European countries (owner's request of 11 Nov
  2026: "all European countries should have their prices listed"). On 11 Nov 2026 it held 18
  countries, 15 of them up to 2023 or 2024 (Czechia stops in 2017, Slovakia in 2008, Kosovo has one
  year in its own currency only).

  It is an ANNUAL PRODUCER price (stored as ``PriceType.PRODUCER``): not a wholesale price of bulk
  honey in drums, and in countries where beekeepers sell mostly in jars (Germany, Austria,
  Luxembourg: 12-15 EUR/kg) it is far above any bulk price. The interface says so.

  No key. One small request (about 15 kB) holds every country and year, so each run reads it all
  again and `ingest.record` keeps what is unchanged; a revised value becomes a new revision.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from dateutil.parser import isoparse

from ..enums import DataStatus, PriceType, Reliability, SourceKind, Variety
from ..reference.countries import country_name
from .base import CollectContext, Collector, CollectorError, year_bounds
from .eu import JSON_HEADERS, JsonStatError, decode_jsonstat, map_geo

log = logging.getLogger(__name__)

EUROSTAT_PRICE_DATASET = "apri_ap_anouta"
EUROSTAT_PRICE_URL = f"https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{EUROSTAT_PRICE_DATASET}"
# The page a person opens (the API address returns JSON): the dataset in Eurostat's data browser.
EUROSTAT_PRICE_PAGE = f"https://ec.europa.eu/eurostat/databrowser/view/{EUROSTAT_PRICE_DATASET}/default/table?lang=en"
EUROSTAT_HONEY_CODE = "12920000"
# Eurostat status flags that are not a plain published value.
_STATUS = {"p": DataStatus.PROVISIONAL, "e": DataStatus.ESTIMATE}
# A price outside this range (EUR per 100 kg) is not stored: the unit or the product has changed.
_PLAUSIBLE_EUR_100KG = (20.0, 5000.0)


@dataclass(frozen=True)
class HoneyPricePoint:
    geo: str                    # as published ("DE", "EL")
    iso3: str
    year: int
    eur_100kg: float
    national_100kg: float | None
    status: str | None          # Eurostat flag ("p" = provisional), None = published


@dataclass
class HoneyPriceRelease:
    updated: str | None
    points: list[HoneyPricePoint]
    skipped: list[str]          # what was published but not stored, in words


def parse_eurostat_honey_prices(content: bytes) -> HoneyPriceRelease:
    """Decode the JSON-stat answer. Raises CollectorError when the dataset no longer says "honey,
    per 100 kg" for the product code: the unit is never assumed."""
    try:
        ds = decode_jsonstat(json.loads(content))
    except (ValueError, JsonStatError) as exc:
        raise CollectorError(f"Eurostat {EUROSTAT_PRICE_DATASET}: the answer is not a JSON-stat dataset ({exc})") from exc
    for dim in ("currency", "prod_ani", "geo", "time"):
        if dim not in ds.ids:
            raise CollectorError(f"Eurostat {EUROSTAT_PRICE_DATASET}: dimension {dim!r} is missing (found {ds.ids})")
    label = (ds.labels["prod_ani"].get(EUROSTAT_HONEY_CODE) or "").lower()
    if "honey" not in label or "100 kg" not in label:
        raise CollectorError(f"Eurostat {EUROSTAT_PRICE_DATASET}: product {EUROSTAT_HONEY_CODE} now reads {label!r}, "
                             "not 'Honey - prices per 100 kg'; nothing stored")
    cells: dict[tuple[str, int], dict[str, tuple[float, str | None]]] = {}
    skipped: list[str] = []
    for c in ds.cells:
        co = c.coords
        if co["prod_ani"] != EUROSTAT_HONEY_CODE or co.get("freq", "A") != "A":
            continue
        try:
            year, value = int(co["time"]), float(c.value)
        except (TypeError, ValueError):
            skipped.append(f"{co['geo']} {co['time']}: value {c.value!r} is not a number")
            continue
        cells.setdefault((co["geo"], year), {})[co["currency"]] = (value, c.status)
    points: list[HoneyPricePoint] = []
    for (geo, year), by_ccy in sorted(cells.items()):
        iso3 = map_geo(geo)
        if iso3 is None or len(iso3) != 3 or country_name(iso3, "en") in (None, iso3):
            skipped.append(f"{geo} {year}: not a country Paladex knows")
            continue
        if "EUR" not in by_ccy:
            skipped.append(f"{geo} {year}: published in the national currency only")
            continue
        eur, status = by_ccy["EUR"]
        if not _PLAUSIBLE_EUR_100KG[0] <= eur <= _PLAUSIBLE_EUR_100KG[1]:
            skipped.append(f"{geo} {year}: {eur} EUR per 100 kg is outside the plausible range")
            continue
        nac = by_ccy.get("NAC")
        points.append(HoneyPricePoint(geo=geo, iso3=iso3, year=year, eur_100kg=eur,
                                      national_100kg=nac[0] if nac else None, status=status))
    return HoneyPriceRelease(updated=ds.updated, points=points, skipped=skipped)


class EurostatHoneyPricesCollector(Collector):
    key = "eurostat_honey_prices"
    name = "Eurostat: prezzo di vendita del miele alla produzione, per paese (annuale)"
    name_en = "Eurostat: producers' selling price of honey, by country (annual)"
    publisher = "Eurostat (European Commission)"
    homepage = EUROSTAT_PRICE_PAGE
    kind = SourceKind.API
    reliability = Reliability.OFFICIAL
    category = "prices"
    language = "en"
    expected_update = "Annuale (i prezzi di un anno arrivano nell'anno successivo); controllato ogni settimana"
    expected_update_en = "Annual (a year's prices arrive during the following year); checked every week"
    expected_max_age_days = 500
    terms_note = ("Source: Eurostat, dataset apri_ap_anouta (selling prices of animal products, absolute prices), "
                  "product 12920000 'Honey - prices per 100 kg'. Reuse under CC BY 4.0 (Commission Decision "
                  "2011/833/EU) with attribution. Annual national averages reported by each country's statistical "
                  "office: a producer price, not a wholesale price of bulk honey; several countries stopped reporting.")
    schedule = {"trigger": "cron", "day_of_week": "tue", "hour": 10, "minute": 35}

    def collect(self, ctx: CollectContext) -> None:
        doc = ctx.fetch(EUROSTAT_PRICE_URL, params={"format": "JSON", "lang": "en", "prod_ani": EUROSTAT_HONEY_CODE},
                        headers=JSON_HEADERS, title="Eurostat apri_ap_anouta, honey (prices per 100 kg)")
        release = parse_eurostat_honey_prices(doc.content)
        if not release.points:
            raise CollectorError(f"Eurostat {EUROSTAT_PRICE_DATASET}: no honey price in the answer")
        published = None
        if release.updated:
            try:
                published = isoparse(release.updated).date()
            except ValueError:
                ctx.warn(f"Eurostat {EUROSTAT_PRICE_DATASET}: unreadable 'updated' stamp {release.updated!r}")
        for p in release.points:
            ps, pe = year_bounds(p.year)
            name = country_name(p.iso3, "en")
            ctx.add_price(
                series_key=f"eurostat|{EUROSTAT_PRICE_DATASET}|{p.iso3}|{p.year}", price_type=PriceType.PRODUCER,
                variety=Variety.UNSPECIFIED.value, variety_raw="Honey (Eurostat product 12920000)",
                price_value=p.eur_100kg, currency="EUR", unit="100kg",
                origin_iso3=p.iso3, origin_label=name, market_iso3=p.iso3, market_location=f"{name} (national average)",
                terms="producers' selling price, annual national average",
                period_start=ps, period_end=pe, period_label=str(p.year), frequency="A",
                data_status=_STATUS.get(p.status or "", DataStatus.PUBLISHED), reliability=Reliability.OFFICIAL,
                published_at=published, source_url=EUROSTAT_PRICE_PAGE, raw_document_id=doc.raw_document_id,
                notes=(f"Eurostat {EUROSTAT_PRICE_DATASET}, 'Honey - prices per 100 kg', {p.geo} {p.year}: "
                       f"{p.eur_100kg} EUR per 100 kg. Producers' selling price (annual national average), "
                       "not a wholesale price of bulk honey."),
                extra={"dataset": EUROSTAT_PRICE_DATASET, "product_code": EUROSTAT_HONEY_CODE, "geo": p.geo,
                       "eur_per_100kg": p.eur_100kg, "national_currency_per_100kg": p.national_100kg,
                       "eurostat_flag": p.status, "dataset_updated": release.updated},
            )
        if release.skipped:
            log.info("[%s] not stored: %s", self.key, "; ".join(release.skipped[:20]))


__all__ = ["EurostatHoneyPricesCollector", "HoneyPricePoint", "HoneyPriceRelease", "parse_eurostat_honey_prices"]
