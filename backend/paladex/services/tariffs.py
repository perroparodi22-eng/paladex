"""Tariff layer: shared vocabulary, append-only storage and official links for `TariffMeasure`.

Used by the tariff collectors (``collectors/tariffs.py``) and the regulations API.

Storage follows the observation rules of ``services.ingest`` (DEVELOPING.md, rule 4):

* new series_key                         -> insert revision 1                         -> "new"
* same series_key, same duty/quota/legal -> refresh only the "checked" metadata        -> "unchanged"
  (``as_of``, ``last_seen_at``, ``consult_url``; empty provenance fields are filled, never changed)
* same series_key, anything else changed -> keep the old row (is_current=False) and insert
  revision n+1 with ``supersedes_id``                                                   -> "revised"
* a measure the source no longer publishes -> ``retire_missing`` clears ``is_current``; values stay.

So a quota balance drawn down day by day leaves one revision per change: that is the fill history.

``US_AD_CASES`` is a curated registry of the US anti-dumping orders on honey (case numbers from
``docs/research/official_tariffs_trade_policy.json``). It holds no rates: it only lets the UI link
an origin to the Federal Register documents the ``us_federal_register`` collector stores.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Literal
from urllib.parse import quote_plus, urlencode

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import TariffMeasure, utcnow
from ..reference.countries import countries

Outcome = Literal["new", "unchanged", "revised"]


class MeasureType(StrEnum):
    """What a duty layer is. Layers stack; they are never summed by Paladex."""

    MFN = "mfn"                      # third-country / general (column 1) duty
    PREFERENCE = "preference"        # preferential rate (FTA, GSP, special programme)
    TRQ_IN = "trq_in"                # rate inside a tariff-rate quota (with order number and balance)
    TRQ_OUT = "trq_out"              # rate above the quota, only when the source publishes it as such
    ANTIDUMPING = "antidumping"      # anti-dumping / countervailing duty measure
    SURCHARGE = "surcharge"          # additional duty whose scope (country, product) is unambiguous
    OTHER = "other"                  # anything else, e.g. a Chapter 99 heading whose scope needs review


# Pseudo-origins: a measure for every origin (EU "ERGA OMNES", geographical area 1011) or the
# US general column (all countries without a better rate).
ERGA_OMNES = "ERGA_OMNES"
ALL_ORIGINS = "ALL"
GENERAL_ORIGINS = (ERGA_OMNES, ALL_ORIGINS)

# Origins Parodi Group buys from or watches, in display order (priority countries come first in
# the API). Group measures (GSP, FTA groups ...) are expanded into these origins only.
TARIFF_ORIGINS: tuple[str, ...] = (
    "CHN", "ARG", "BRA", "URY", "UKR", "SRB", "VNM", "IND", "MEX", "TUR", "MDA", "THA", "CHL", "NZL", "CAN", "USA",
)

# Fields whose change makes a new revision. Links and the date checked are metadata, not values.
VALUE_FIELDS: tuple[str, ...] = (
    "jurisdiction", "origin_iso3", "hs_code", "measure_type", "measure_code", "description", "duty_text",
    "ad_valorem_pct", "specific_amount", "specific_unit", "specific_currency",
    "quota_order_number", "quota_volume_kg", "quota_balance_kg", "quota_status",
    "valid_from", "valid_to", "legal_reference", "data_status",
)
# Refreshed on an unchanged row: they say when / where the measure was last confirmed.
_REFRESH_FIELDS = ("as_of", "consult_url")
# Filled on an unchanged row only when still empty (late provenance), never overwritten.
_FILL_FIELDS = ("source_url", "raw_document_id", "legal_url", "published_at")


def _canon(v):
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def value_hash(fields: dict) -> str:
    payload = {k: _canon(fields.get(k)) for k in VALUE_FIELDS}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def record_measure(session: Session, *, source_id: int, series_key: str, as_of: date, is_demo: bool = False,
                   **fields) -> tuple[Outcome, TariffMeasure]:
    """Append-only write of one measure (see module docstring). Returns (outcome, current row)."""
    vh = value_hash(fields)
    current = session.scalars(
        select(TariffMeasure).where(
            TariffMeasure.source_id == source_id,
            TariffMeasure.series_key == series_key,
            TariffMeasure.is_current.is_(True),
            TariffMeasure.is_demo.is_(is_demo),
        )
    ).first()
    now = utcnow()
    if current is not None and current.value_hash == vh:
        current.last_seen_at = now
        if current.as_of is None or as_of > current.as_of:
            current.as_of = as_of
            if fields.get("consult_url"):
                current.consult_url = fields["consult_url"]
        for k in _FILL_FIELDS:
            if getattr(current, k) is None and fields.get(k) is not None:
                setattr(current, k, fields[k])
        return "unchanged", current

    row = TariffMeasure(source_id=source_id, series_key=series_key, value_hash=vh, is_demo=is_demo, as_of=as_of,
                        collected_at=now, last_seen_at=now, **fields)
    if current is None:
        row.revision = 1
        session.add(row)
        session.flush()
        return "new", row
    current.is_current = False
    row.revision = (current.revision or 1) + 1
    row.supersedes_id = current.id
    session.add(row)
    session.flush()
    return "revised", row


def retire_missing(session: Session, *, source_id: int, prefix: str, keep: set[str],
                   is_demo: bool = False) -> list[str]:
    """Withdraw the current rows of `source_id` whose series_key starts with `prefix` and is not in
    `keep` (the source no longer publishes them). Values are untouched; only `is_current` is
    cleared, as on a revision. Returns the retired series keys. Call it only after a complete,
    successful read of everything under `prefix`."""
    rows = session.scalars(
        select(TariffMeasure).where(
            TariffMeasure.source_id == source_id,
            TariffMeasure.is_current.is_(True),
            TariffMeasure.is_demo.is_(is_demo),
            TariffMeasure.series_key.startswith(prefix, autoescape=True),
        )
    ).all()
    retired = []
    for r in rows:
        if r.series_key not in keep:
            r.is_current = False
            retired.append(r.series_key)
    if retired:
        session.flush()
    return retired


def quota_fill_pct(volume_kg: float | None, balance_kg: float | None) -> float | None:
    """Share of a tariff quota already allocated, in %, as published (1 - balance / initial volume).
    None when either figure is missing or the volume is not positive. Not clamped: a value outside
    0-100 (e.g. a balance above the initial volume after a transfer) is shown as it is."""
    if volume_kg is None or balance_kg is None or volume_kg <= 0:
        return None
    return round((1 - balance_kg / volume_kg) * 100, 2)


# ---------------------------------------------------------------------------
# Official links
# ---------------------------------------------------------------------------

TARIC_MEASURES_URL = "https://ec.europa.eu/taxation_customs/dds2/taric/measures.jsp"
HTS_SEARCH_PAGE = "https://hts.usitc.gov/search"
FR_SEARCH_PAGE = "https://www.federalregister.gov/documents/search"

# TARIC geographical codes that are not the ISO alpha-2 code.
_TARIC_GEO: dict[str, str] = {"SRB": "XS", "GRC": "EL"}
_ISO2 = {c["iso3"]: c["iso2"] for c in countries()}


def taric_geo(origin_iso3: str) -> str:
    """TARIC area code for an origin ("" for ERGA OMNES / all origins, "XS" for Serbia)."""
    if origin_iso3 in GENERAL_ORIGINS:
        return ""
    return _TARIC_GEO.get(origin_iso3) or _ISO2.get(origin_iso3, "")


def taric_url(origin_iso3: str, on: date, taric_code: str = "0409000000") -> str:
    """Deep link to the official EU TARIC measure consultation for `taric_code`, filtered to one
    origin and simulated at date `on` (the legally authoritative display)."""
    params = {
        "Lang": "en", "Taric": taric_code, "SimDate": on.strftime("%Y%m%d"), "Area": taric_geo(origin_iso3),
        "MeasType": "", "StartPub": "", "EndPub": "", "MeasText": "", "GoodsText": "", "op": "",
        "search_text": "goods", "textSearch": "", "LangDescr": "en", "OrderNum": "", "Regulation": "",
        "measStartDat": "", "measEndDat": "",
    }
    return f"{TARIC_MEASURES_URL}?{urlencode(params)}"


def hts_url(number: str = "0409.00.00") -> str:
    """Official USITC HTS search page for an HTS number or Chapter 99 heading."""
    return f"{HTS_SEARCH_PAGE}?query={quote_plus(number)}"


def fr_search_url(term: str) -> str:
    """Official Federal Register search page for a full-text term (quotes make a phrase)."""
    return f"{FR_SEARCH_PAGE}?{urlencode({'conditions[term]': term})}"


# ---------------------------------------------------------------------------
# US anti-dumping orders on honey: a case registry, NOT rates
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdCase:
    origin_iso3: str
    case_number: str | None          # None: not in the research; read it from the order notice
    product: str                     # as Commerce names it
    title_pattern: str               # regex on Federal Register titles (case-insensitive)
    fr_term: str                     # Federal Register full-text search term (official search page)

    @property
    def title_re(self) -> re.Pattern[str]:
        return re.compile(self.title_pattern, re.IGNORECASE)

    def matches(self, title: str | None) -> bool:
        return bool(title) and bool(self.title_re.search(title))

    @property
    def fr_search_url(self) -> str:
        return fr_search_url(self.fr_term)


# Titles follow Commerce patterns, e.g. "Raw Honey From Brazil: Final Results of Antidumping Duty
# Administrative Review; 2023-2024" and the joint "Raw Honey From Argentina, Brazil, India, and the
# Socialist Republic of Vietnam: Antidumping Duty Orders". The country must come before the colon.
_RAW = r"\braw honey from\b[^:]*?\b"
US_AD_CASES: tuple[AdCase, ...] = (
    AdCase("CHN", "A-570-863", "Honey from the People's Republic of China",
           r"\bhoney from the people[’']?s republic of china\b", '"honey from the people\'s republic of china"'),
    AdCase("ARG", "A-357-823", "Raw Honey from Argentina", _RAW + r"argentina\b", '"raw honey from argentina"'),
    AdCase("BRA", "A-351-857", "Raw Honey from Brazil", _RAW + r"brazil\b", '"raw honey from brazil"'),
    AdCase("IND", None, "Raw Honey from India", _RAW + r"india\b", '"raw honey from india"'),
    AdCase("VNM", None, "Raw Honey from the Socialist Republic of Vietnam",
           _RAW + r"(?:the socialist republic of )?viet ?nam\b", '"raw honey" vietnam'),
)
AD_CASE_BY_ORIGIN: dict[str, AdCase] = {c.origin_iso3: c for c in US_AD_CASES}


def ad_cases_for_title(title: str | None) -> list[AdCase]:
    """The registry cases a Federal Register title belongs to (a joint notice may cover several)."""
    return [c for c in US_AD_CASES if c.matches(title)]
