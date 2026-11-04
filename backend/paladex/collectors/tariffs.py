"""Tariff layer: official import duties on natural honey (HS 0409) per origin, EU and US.

Two keyless collectors. Both write ``TariffMeasure`` rows through ``services.tariffs.record_measure``,
which is append-only: a changed duty, validity or quota balance becomes a new revision, and a measure
the source stops publishing is retired (``is_current=False``), never deleted.

* ``eu_tariff_xi``: the UK Online Trade Tariff API v2, **XI (Northern Ireland) service**. Under the
  Windsor Framework the EU Common Customs Tariff applies in Northern Ireland, so HMRC publishes the
  EU TARIC measures in the XI service: it is the UK government's official, machine-readable mirror
  of EU TARIC (Open Government Licence v3.0). The legally binding source remains EU TARIC and the EU
  act in the Official Journal, so every row carries the EU legal act (``regulation_url`` on EUR-Lex)
  and a deep link to the official TARIC consultation filtered to its origin. The collector keeps the
  EU import measures that are duties (third-country duty, tariff preferences, tariff quotas, and any
  anti-dumping or additional duty that would appear), expands geographical groups into the origins
  Parodi follows (``services.tariffs.TARIFF_ORIGINS``; ERGA OMNES stays one row) and reads the
  balance of every tariff quota from the quota search.
* ``us_hts``: the USITC Harmonized Tariff Schedule REST API. Heading 0409.00.00 gives the general
  (MFN) rate for all origins and the special-programme codes; preference rows are stored only for
  programmes whose countries are unambiguous (``S``/``S+`` USMCA: Mexico, Canada; ``CL``: Chile).
  Chapter 99 headings (additional duties) are read from the 0409 footnotes and from the ranges named
  in the research. A heading becomes a ``surcharge`` for one origin only when the HTS itself ties it
  to honey (footnote) and its text names exactly one country; everything else is stored as ``other``
  with ``extra.needs_review = True``, never assigned to countries by guesswork.

US anti-dumping duties are exporter-specific and are not in the HTS. They are not computed here:
``services.tariffs.US_AD_CASES`` links each origin to the Federal Register documents stored by the
``us_federal_register`` collector.

Verification status (read this before changing anything)
--------------------------------------------------------
Neither host could be reached while this module was written (sandbox egress was blocked). Every
endpoint, parameter and field name comes from ``docs/research/official_tariffs_trade_policy.json``
and ``docs/research/regulation.json``, both marked ``from_memory_unverified``. The module is therefore
defensive:

* Each run starts with a probe of the main document. XI: a JSON:API ``commodity`` for 0409000000
  with ``import_measures`` and ``included``, and the canary every CN line has (a third-country duty,
  measure type 103, for ERGA OMNES 1011). HTS: a JSON array of rows with ``htsno``/``general``/
  ``special``/``other`` containing 0409.00.00 with a readable general rate. If the probe fails the
  run raises ``SchemaDrift`` and stores nothing. HTTP 401/403 is reported as "the API now needs a key".
* A quota balance that cannot be read leaves the previous row untouched (no revision with an empty
  balance, no retirement); a group whose membership cannot be read is skipped with a warning.
* Rows are retired only after a complete read of their scope.
* No value is ever invented: duty expressions are stored as published (``duty_text``) and parsed into
  numbers only when the expression is a plain ad valorem and/or specific duty.
"""
from __future__ import annotations

import html
import json
import logging
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..enums import DataStatus, Reliability, SourceKind
from ..reference.countries import lookup_iso3
from ..services import tariffs as tariff_svc
from ..services.tariffs import ALL_ORIGINS, ERGA_OMNES, TARIFF_ORIGINS, MeasureType
from .base import CollectContext, Collector, CollectorError, FetchResult, Offline
from .regulation import detect_countries

log = logging.getLogger(__name__)


def today() -> date:
    """Reference date for 'as of' and quota periods (indirection so tests can pin it)."""
    return date.today()


class SchemaDrift(CollectorError):
    """The source answered, but not in the documented shape. Nothing from it is stored."""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _snippet(content: bytes, n: int = 160) -> str:
    return re.sub(r"\s+", " ", content[:n].decode("utf-8", errors="replace")).strip()


def _load_json(content: bytes, what: str) -> Any:
    try:
        return json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise SchemaDrift(f"{what}: response is not JSON ({exc}); starts with {_snippet(content, 120)!r}") from exc


_TAG_RE = re.compile(r"<[^>]+>")


def clean_text(value: Any) -> str | None:
    """Plain text as published: HTML tags and entities removed, whitespace collapsed. None if empty."""
    if value is None or isinstance(value, (dict, list, bool)):
        return None
    text = re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", str(value)))).strip()
    return text or None


def _num(v: Any) -> float | None:
    """A finite number from a JSON number or a numeric string ("35000000.0"), else None."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        f = float(v)
    elif isinstance(v, str):
        try:
            f = float(v.strip().replace(",", ""))
        except ValueError:
            return None
    else:
        return None
    return f if math.isfinite(f) else None


def parse_iso_date(value: Any) -> date | None:
    """`YYYY-MM-DD`, optionally followed by a time ("2026-01-01T00:00:00.000Z"). None otherwise."""
    if not isinstance(value, str):
        return None
    m = re.match(r"^\s*(\d{4}-\d{2}-\d{2})", value)
    if not m:
        return None
    try:
        return date.fromisoformat(m.group(1))
    except ValueError:
        return None


def _https(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip().startswith("https://") else None


@dataclass(frozen=True)
class Duty:
    """A duty expression as published, and the numbers it reduces to (when it does)."""

    text: str | None
    ad_valorem_pct: float | None = None
    specific_amount: float | None = None
    specific_unit: str | None = None
    specific_currency: str | None = None
    complex: bool = False            # not reducible to ad valorem + specific: kept as text only

    @property
    def parsed(self) -> bool:
        return not self.complex and (self.ad_valorem_pct is not None or self.specific_amount is not None)

    def fields(self) -> dict:
        return {"duty_text": self.text, "ad_valorem_pct": self.ad_valorem_pct, "specific_amount": self.specific_amount,
                "specific_unit": self.specific_unit, "specific_currency": self.specific_currency}


def _leftover(text: str, *patterns: re.Pattern[str]) -> str:
    for p in patterns:
        text = p.sub(" ", text)
    return re.sub(r"[\s+/]+", "", text)


# ---------------------------------------------------------------------------
# EU duty expressions (TARIC, as shown by the XI service: "17.30 %", "0.00 % + 10.00 EUR / 100 kg")
# ---------------------------------------------------------------------------

_EU_PCT = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*%")
_EU_SPECIFIC = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(EUR|USD|GBP)\s*/?\s*(1000\s*kg|100\s*kg|kg|tonne|t)\b(?:\s*/?\s*net\b)?",
                          re.IGNORECASE)
# Meursing components, entry prices, maxima/minima, "nihil": not reducible to two numbers.
_EU_COMPLEX = re.compile(r"\b(?:MAX|MIN|EA|EAR|ADSZ|ADSZR|ADFM|ADFMR|AD\s*S/Z|AD\s*F/M|NIHIL)\b|entry price", re.IGNORECASE)
_UNIT_NORM = {"kg": "kg", "100kg": "100kg", "1000kg": "t", "tonne": "t", "t": "t"}


def parse_eu_duty(value: Any) -> Duty:
    text = clean_text(value)
    if not text:
        return Duty(None, complex=True)
    if _EU_COMPLEX.search(text):
        return Duty(text, complex=True)
    pcts = _EU_PCT.findall(text)
    specs = _EU_SPECIFIC.findall(text)
    if len(pcts) > 1 or len(specs) > 1 or (not pcts and not specs) or _leftover(text, _EU_PCT, _EU_SPECIFIC):
        return Duty(text, complex=True)
    av = float(pcts[0]) if pcts else None
    if specs:
        amount, cur, unit = specs[0]
        return Duty(text, av, float(amount), _UNIT_NORM.get(re.sub(r"\s+", "", unit.lower()), unit), cur.upper())
    return Duty(text, av)


# ---------------------------------------------------------------------------
# US rates (HTS: "1.9¢/kg", "Free", "5%", "The duty provided in the applicable subheading + 25%")
# ---------------------------------------------------------------------------

_US_CENTS = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*¢\s*/\s*kg\b", re.IGNORECASE)
_US_DOLLARS = re.compile(r"\$\s*(\d+(?:\.\d+)?)\s*/\s*kg\b", re.IGNORECASE)
_US_PCT = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*%")
_US_FREE = re.compile(r"^\s*free\s*$", re.IGNORECASE)
_US_BASE_PHRASE = re.compile(r"the duty provided in the applicable subheading", re.IGNORECASE)


def parse_us_rate(value: Any) -> Duty:
    """A column-1/column-2 rate. "Free" is 0 % ad valorem; cents are converted to USD per kg."""
    text = clean_text(value)
    if not text:
        return Duty(None, complex=True)
    if _US_FREE.match(text):
        return Duty(text, 0.0)
    pcts = _US_PCT.findall(text)
    cents = _US_CENTS.findall(text)
    dollars = _US_DOLLARS.findall(text)
    specs = [float(c) / 100 for c in cents] + [float(d) for d in dollars]
    if len(pcts) > 1 or len(specs) > 1 or (not pcts and not specs) or _leftover(text, _US_PCT, _US_CENTS, _US_DOLLARS):
        return Duty(text, complex=True)
    return Duty(text, float(pcts[0]) if pcts else None, round(specs[0], 6) if specs else None,
                "kg" if specs else None, "USD" if specs else None)


def parse_us_additional(value: Any) -> Duty:
    """A Chapter 99 'general' column: the additional duty on top of the applicable subheading.

    "The duty provided in the applicable subheading + 25%" -> 25 % additional. A text without the
    "+ ..." part (e.g. exemption headings) gives a Duty with no numbers; anything else is complex."""
    text = clean_text(value)
    if not text:
        return Duty(None)
    rest = _US_BASE_PHRASE.sub(" ", text).strip()
    if not rest:
        return Duty(text)                    # no additional duty (e.g. an exemption heading)
    if not rest.startswith("+"):
        return Duty(text, complex=True)
    inner = parse_us_rate(rest.lstrip("+ ").strip())
    if inner.complex:
        return Duty(text, complex=True)
    return Duty(text, inner.ad_valorem_pct, inner.specific_amount, inner.specific_unit, inner.specific_currency)


_SPECIAL_GROUP = re.compile(r"([^()]+?)\s*\(([^()]*)\)")


def parse_special(value: Any) -> tuple[list[tuple[str, list[str]]], bool]:
    """'Free (A+,AU,...,S,SG)' -> ([("Free", ["A+", "AU", ..., "S", "SG"])], ok). `ok` is False when
    text remains that is not a "rate (codes)" group, so the caller can flag it."""
    text = clean_text(value)
    if not text:
        return [], True
    groups = [(rate.strip(), [c.strip() for c in codes.split(",") if c.strip()]) for rate, codes in _SPECIAL_GROUP.findall(text)]
    ok = bool(groups) and not _SPECIAL_GROUP.sub(" ", text).strip()
    return groups, ok


# Special-programme indicators whose countries are unambiguous and relevant to Parodi. Others (GSP
# "A", "A+", "A*", AGOA "D", CBERA "E", ...) cover country lists that change: never expanded.
US_PROGRAM_ORIGINS: dict[str, tuple[str, ...]] = {"S": ("MEX", "CAN"), "S+": ("MEX", "CAN"), "CL": ("CHL",)}
US_PROGRAM_NAMES: dict[str, str] = {
    "S": "United States-Mexico-Canada Agreement (USMCA)",
    "S+": "United States-Mexico-Canada Agreement (USMCA)",
    "CL": "United States-Chile Free Trade Agreement",
}


# ===========================================================================
# 1) EU: UK Online Trade Tariff API v2, XI service (mirror of EU TARIC)
# ===========================================================================

XI_BASE = "https://www.trade-tariff.service.gov.uk/xi/api/v2"
XI_COMMODITY = "0409000000"
XI_COMMODITY_URL = f"{XI_BASE}/commodities/{XI_COMMODITY}"
XI_QUOTA_SEARCH_URL = f"{XI_BASE}/quotas/search"
XI_GEO_URL = XI_BASE + "/geographical_areas/{geo_id}"
XI_ERGA_OMNES = "1011"
XI_MIRROR_NOTE = ("UK Online Trade Tariff, XI (Northern Ireland) service: the UK government's mirror of EU TARIC "
                  "(Open Government Licence v3.0). Legally binding: EU TARIC and the EU act.")

# TARIC measure type id -> layer. Types not listed are kept only when their series is a duty series
# (C applicable duty, D anti-dumping/countervailing), as 'other' with needs_review.
XI_MEASURE_TYPES: dict[str, MeasureType] = {
    "103": MeasureType.MFN,               # Third country duty
    "142": MeasureType.PREFERENCE,        # Tariff preference
    "143": MeasureType.TRQ_IN,            # Preferential tariff quota
    "122": MeasureType.TRQ_IN,            # Non preferential tariff quota
    "551": MeasureType.ANTIDUMPING,       # Provisional anti-dumping duty
    "552": MeasureType.ANTIDUMPING,       # Definitive anti-dumping duty
    "553": MeasureType.ANTIDUMPING,       # Provisional countervailing duty
    "554": MeasureType.ANTIDUMPING,       # Definitive countervailing duty
    "555": MeasureType.ANTIDUMPING,       # Anti-dumping/countervailing duty - pending collection
    "695": MeasureType.SURCHARGE,         # Additional duties
    "696": MeasureType.SURCHARGE,         # Additional duties (safeguard)
}
XI_DUTY_SERIES = frozenset({"C", "D"})
# TARIC area codes that are not ISO alpha-2 (Serbia is XS in TARIC and Comext; Greece EL).
XI_GEO_OVERRIDES: dict[str, str | None] = {"XS": "SRB", "EL": "GRC", "XK": None, "XC": None, "XL": None}


@dataclass(frozen=True)
class LegalAct:
    code: str | None
    url: str | None
    published: date | None
    journal: str | None

    def as_dict(self) -> dict:
        return {"code": self.code, "url": self.url, "published": self.published.isoformat() if self.published else None,
                "journal": self.journal}


@dataclass
class XiMeasure:
    sid: str
    type_id: str
    type_description: str | None
    type_series: str | None
    geo_id: str
    geo_description: str | None
    excluded: tuple[str, ...]
    duty: Duty
    start: date | None
    end: date | None
    order_number: str | None
    legal_acts: tuple[LegalAct, ...]
    footnotes: tuple[str, ...]
    origin_flag: str | None              # "eu" / "uk" (XI also carries UK measures: VAT, excise, UK duties)
    is_import: bool | None


@dataclass
class XiGeo:
    geo_id: str
    description: str | None
    children: tuple[str, ...] | None     # None: membership not given in this document


@dataclass
class XiQuota:
    order_number: str
    volume_kg: float | None
    balance_kg: float | None
    unit_raw: str | None
    status: str | None                   # normalised: open / critical / exhausted / blocked / ...
    status_raw: str | None
    critical: str | None
    valid_from: date | None
    valid_to: date | None
    last_allocation: date | None
    problems: list[str] = field(default_factory=list)

    def covers(self, on: date) -> bool:
        return (self.valid_from is None or self.valid_from <= on) and (self.valid_to is None or on <= self.valid_to)


@dataclass
class XiCommodity:
    item_id: str
    description: str | None
    measures: list[XiMeasure]
    geos: dict[str, XiGeo]
    quotas: dict[str, XiQuota]           # order number -> definition included in the commodity document
    problems: list[str] = field(default_factory=list)


def _rel_data(obj: dict, name: str) -> Any:
    rel = obj.get("relationships")
    if not isinstance(rel, dict) or not isinstance(rel.get(name), dict):
        return None
    return rel[name].get("data")


def _has_rel(obj: dict, name: str) -> bool:
    rel = obj.get("relationships")
    return isinstance(rel, dict) and isinstance(rel.get(name), dict) and "data" in rel[name]


def _rel_one(obj: dict, name: str) -> tuple[str, str] | None:
    d = _rel_data(obj, name)
    if isinstance(d, dict) and d.get("id") is not None:
        return str(d.get("type") or ""), str(d["id"])
    return None


def _rel_many(obj: dict, name: str) -> list[tuple[str, str]]:
    d = _rel_data(obj, name)
    if isinstance(d, dict):
        d = [d]
    if not isinstance(d, list):
        return []
    return [(str(x.get("type") or ""), str(x["id"])) for x in d if isinstance(x, dict) and x.get("id") is not None]


def _attrs(obj: dict | None) -> dict:
    a = obj.get("attributes") if isinstance(obj, dict) else None
    return a if isinstance(a, dict) else {}


_MASS_UNITS = (
    (re.compile(r"tonne|1\s*000\s*kg|\(t\)|\bt\b", re.IGNORECASE), 1000.0),
    (re.compile(r"kilogram|\bkg\b", re.IGNORECASE), 1.0),
)


def _kg_factor(unit: str | None) -> float | None:
    if not unit:
        return None
    for pat, factor in _MASS_UNITS:
        if pat.search(unit):
            return factor
    return None


def parse_xi_definition(attrs: dict, order_number: str) -> XiQuota:
    """A quota definition (initial volume, balance, period, status). Volumes and balances are
    strings in the measurement unit (kg for honey); other units are kept raw, not converted."""
    problems: list[str] = []
    unit = clean_text(attrs.get("measurement_unit"))
    factor = _kg_factor(unit)
    vol, bal = _num(attrs.get("initial_volume")), _num(attrs.get("balance"))
    if factor is None:
        if vol is not None or bal is not None:
            problems.append(f"quota {order_number}: unit {unit!r} is not a mass unit; volume and balance not stored as kg")
        vol_kg = bal_kg = None
    else:
        vol_kg = vol * factor if vol is not None else None
        bal_kg = bal * factor if bal is not None else None
    status_raw = clean_text(attrs.get("status"))
    return XiQuota(
        order_number=order_number, volume_kg=vol_kg, balance_kg=bal_kg, unit_raw=unit,
        status=status_raw.lower() if status_raw else None, status_raw=status_raw,
        critical=clean_text(attrs.get("critical")),
        valid_from=parse_iso_date(attrs.get("validity_start_date")), valid_to=parse_iso_date(attrs.get("validity_end_date")),
        last_allocation=parse_iso_date(attrs.get("last_allocation_date")), problems=problems,
    )


def _xi_measure(m: dict, idx: dict[tuple[str, str], dict], problems: list[str]) -> XiMeasure | None:
    sid = str(m.get("id"))
    a = _attrs(m)
    mt = _rel_one(m, "measure_type")
    type_id = mt[1] if mt else (str(a["measure_type_id"]) if a.get("measure_type_id") is not None else None)
    if not type_id:
        problems.append(f"measure {sid}: no measure type; skipped")
        return None
    mt_attrs = _attrs(idx.get(("measure_type", type_id)))
    geo = _rel_one(m, "geographical_area")
    geo_id = geo[1] if geo else (str(a["geographical_area_id"]) if a.get("geographical_area_id") is not None else None)
    if not geo_id:
        problems.append(f"measure {sid} (type {type_id}): no geographical area; skipped")
        return None
    geo_attrs = _attrs(idx.get(("geographical_area", geo_id)))
    excluded: list[str] = []
    for rel_name in ("excluded_countries", "excluded_geographical_areas"):
        for typ, xid in _rel_many(m, rel_name):
            obj = idx.get((typ, xid))
            gid = _attrs(obj).get("geographical_area_id") if typ != "geographical_area" else None
            excluded.append(str(gid or xid))
    de = _rel_one(m, "duty_expression")
    de_attrs = _attrs(idx.get(("duty_expression", de[1]))) if de else {}
    raw_duty = de_attrs.get("base") or de_attrs.get("formatted_base")
    if raw_duty is None and isinstance(a.get("duty_expression"), dict):
        raw_duty = a["duty_expression"].get("base") or a["duty_expression"].get("formatted_base")
    order_number = None
    on = _rel_one(m, "order_number")
    if on:
        order_number = clean_text(_attrs(idx.get(("order_number", on[1]))).get("number")) or on[1]
    acts: list[LegalAct] = []
    for typ, lid in _rel_many(m, "legal_acts") + _rel_many(m, "legal_act"):
        la = _attrs(idx.get((typ or "legal_act", lid)) or idx.get(("legal_act", lid)))
        acts.append(LegalAct(
            code=clean_text(la.get("regulation_code")) or lid, url=_https(la.get("regulation_url")),
            published=parse_iso_date(la.get("published_date")),
            journal=" ".join(x for x in (clean_text(la.get("officialjournal_number")),
                                         clean_text(la.get("officialjournal_page"))) if x) or None,
        ))
    footnotes = tuple(fid for _, fid in _rel_many(m, "footnotes"))
    origin_flag = a.get("origin")
    is_import = a.get("import")
    return XiMeasure(
        sid=sid, type_id=type_id, type_description=clean_text(mt_attrs.get("description")),
        type_series=clean_text(mt_attrs.get("measure_type_series_id")), geo_id=geo_id,
        geo_description=clean_text(geo_attrs.get("description")), excluded=tuple(excluded),
        duty=parse_eu_duty(raw_duty), start=parse_iso_date(a.get("effective_start_date")),
        end=parse_iso_date(a.get("effective_end_date")), order_number=order_number, legal_acts=tuple(acts),
        footnotes=footnotes, origin_flag=str(origin_flag).lower() if isinstance(origin_flag, str) else None,
        is_import=is_import if isinstance(is_import, bool) else None,
    )


def parse_xi_commodity(content: bytes, item_id: str = XI_COMMODITY) -> XiCommodity:
    """Parse the XI commodity document (JSON:API). Raises ``SchemaDrift`` when the envelope is not
    the documented one or no import measure can be resolved; malformed measures become problems."""
    obj = _load_json(content, "XI commodity")
    if not isinstance(obj, dict) or not isinstance(obj.get("data"), dict):
        raise SchemaDrift(f"XI commodity: no JSON:API 'data' object (top-level keys: "
                          f"{sorted(obj)[:10] if isinstance(obj, dict) else type(obj).__name__})")
    data = obj["data"]
    attrs = _attrs(data)
    got = str(attrs.get("goods_nomenclature_item_id") or "")
    if got != item_id:
        raise SchemaDrift(f"XI commodity: goods_nomenclature_item_id is {got!r}, expected {item_id!r}")
    if not _has_rel(data, "import_measures"):
        raise SchemaDrift(f"XI commodity: no relationships.import_measures (relationships: "
                          f"{sorted((data.get('relationships') or {}))[:12]})")
    included = obj.get("included")
    if not isinstance(included, list):
        raise SchemaDrift("XI commodity: 'included' is missing or not a list")
    idx: dict[tuple[str, str], dict] = {}
    for o in included:
        if isinstance(o, dict) and o.get("type") is not None and o.get("id") is not None:
            idx[(str(o["type"]), str(o["id"]))] = o
    problems: list[str] = []
    measures: list[XiMeasure] = []
    refs = _rel_many(data, "import_measures")
    for typ, mid in refs:
        m = idx.get(("measure", mid)) or idx.get((typ, mid))
        if m is None:
            problems.append(f"measure {mid} is referenced but not included; skipped")
            continue
        parsed = _xi_measure(m, idx, problems)
        if parsed is not None:
            measures.append(parsed)
    if refs and not measures:
        raise SchemaDrift(f"XI commodity: none of the {len(refs)} import measures could be resolved "
                          f"(included types: {sorted({t for t, _ in idx})[:15]})")
    geos: dict[str, XiGeo] = {}
    for (typ, gid), o in idx.items():
        if typ != "geographical_area":
            continue
        children = None
        if _has_rel(o, "children_geographical_areas"):
            children = tuple(cid for _, cid in _rel_many(o, "children_geographical_areas"))
        geos[gid] = XiGeo(gid, clean_text(_attrs(o).get("description")), children)
    quotas: dict[str, XiQuota] = {}
    for (typ, oid), o in idx.items():
        if typ != "order_number":
            continue
        number = clean_text(_attrs(o).get("number")) or oid
        d = _rel_one(o, "definition")
        if d is not None:
            dobj = idx.get((d[0] or "definition", d[1])) or idx.get(("definition", d[1]))
            if dobj is not None:
                quotas[number] = parse_xi_definition(_attrs(dobj), number)
    return XiCommodity(item_id=got, description=clean_text(attrs.get("description")), measures=measures, geos=geos,
                       quotas=quotas, problems=problems)


def parse_xi_quota_search(content: bytes, order_number: str, on: date) -> tuple[XiQuota | None, list[str]]:
    """The definition of `order_number` that covers date `on` (the latest-starting one if several).
    Returns (None, problems) when the source lists no definition for that date (e.g. early January)."""
    obj = _load_json(content, f"XI quota search {order_number}")
    if not isinstance(obj, dict) or not isinstance(obj.get("data"), list):
        raise SchemaDrift(f"XI quota search {order_number}: no 'data' list")
    problems: list[str] = []
    found: list[XiQuota] = []
    with_figures = 0
    for d in obj["data"]:
        if not isinstance(d, dict):
            continue
        a = _attrs(d)
        if "initial_volume" in a or "balance" in a:
            with_figures += 1
        rel = _rel_one(d, "order_number") or _rel_one(d, "quota_order_number")
        number = clean_text(a.get("quota_order_number_id")) or (rel[1] if rel else None)
        if number is not None and number.replace(".", "") != order_number.replace(".", ""):
            problems.append(f"quota search {order_number}: returned order number {number}; ignored")
            continue
        q = parse_xi_definition(a, order_number)
        problems += q.problems
        found.append(q)
    if obj["data"] and not with_figures:
        raise SchemaDrift(f"XI quota search {order_number}: definitions carry neither 'initial_volume' nor 'balance'")
    covering = [q for q in found if q.covers(on)]
    if not covering:
        if found:
            problems.append(f"quota {order_number}: no definition covers {on.isoformat()}")
        return None, problems
    covering.sort(key=lambda q: (q.valid_from or date.min))
    return covering[-1], problems


def parse_xi_geo_children(content: bytes, geo_id: str) -> tuple[str, ...]:
    """Members of a geographical group from /geographical_areas/{id}. Raises SchemaDrift if absent."""
    obj = _load_json(content, f"XI geographical area {geo_id}")
    data = obj.get("data") if isinstance(obj, dict) else None
    if not isinstance(data, dict) or not _has_rel(data, "children_geographical_areas"):
        raise SchemaDrift(f"XI geographical area {geo_id}: no relationships.children_geographical_areas")
    return tuple(cid for _, cid in _rel_many(data, "children_geographical_areas"))


def xi_geo_to_iso3(geo_id: str) -> str | None:
    """TARIC area code -> ISO3 (XS -> SRB). None for groups and codes outside the reference list."""
    g = (geo_id or "").strip().upper()
    if g in XI_GEO_OVERRIDES:
        return XI_GEO_OVERRIDES[g]
    if len(g) == 2 and g.isalpha():
        return lookup_iso3(g)
    return None


def xi_is_group(geo_id: str) -> bool:
    g = (geo_id or "").strip()
    return not (len(g) == 2 and g.isalpha())


def expand_origins(geo_id: str, excluded: Iterable[str], children: Iterable[str] | None,
                   relevant: Iterable[str] = TARIFF_ORIGINS) -> list[str] | None:
    """Origins a measure applies to, limited to `relevant`. ERGA OMNES stays one pseudo-origin.
    None when `geo_id` is a group whose membership is unknown (`children` is None)."""
    if geo_id == XI_ERGA_OMNES:
        return [ERGA_OMNES]
    relevant = list(relevant)
    if not xi_is_group(geo_id):
        iso = xi_geo_to_iso3(geo_id)
        return [iso] if iso in relevant else []
    if children is None:
        return None
    members = {xi_geo_to_iso3(c) for c in children}
    out = {xi_geo_to_iso3(e) for e in excluded}
    return [o for o in relevant if o in members and o not in out]


@dataclass
class XiSelected:
    measure: XiMeasure
    layer: MeasureType
    needs_review: bool
    reason: str | None


def select_xi_tariff_measures(com: XiCommodity) -> tuple[list[XiSelected], list[str]]:
    """EU import duty measures (see XI_MEASURE_TYPES). UK measures (origin 'uk': VAT, excise, UK
    duties for goods not at risk) are dropped. Raises SchemaDrift when EU and UK measures cannot be
    told apart (no origin flag at all and the same type/area appears twice)."""
    problems: list[str] = []
    flagged = [m for m in com.measures if m.origin_flag is not None]
    if not flagged:
        seen: set[tuple[str, str]] = set()
        for m in com.measures:
            k = (m.type_id, m.geo_id)
            if m.type_id in XI_MEASURE_TYPES and k in seen:
                raise SchemaDrift(f"XI commodity: measures carry no 'origin' (eu/uk) attribute and type {m.type_id} "
                                  f"for area {m.geo_id} appears twice: EU and UK duties cannot be told apart")
            seen.add(k)
        if com.measures:
            problems.append("XI measures carry no 'origin' (eu/uk) attribute; kept the EU duty types only")
    out: list[XiSelected] = []
    for m in com.measures:
        if m.origin_flag is None and flagged:
            problems.append(f"measure {m.sid} (type {m.type_id}) has no 'origin' attribute; skipped")
            continue
        if m.origin_flag not in (None, "eu") or m.is_import is False:
            continue
        layer = XI_MEASURE_TYPES.get(m.type_id)
        if layer is not None:
            out.append(XiSelected(m, layer, m.duty.complex, "duty expression not reducible to a rate" if m.duty.complex else None))
        elif (m.type_series or "").upper() in XI_DUTY_SERIES:
            out.append(XiSelected(m, MeasureType.OTHER, True,
                                  f"TARIC measure type {m.type_id} ({m.type_description or 'no description'}) not mapped"))
            problems.append(f"measure {m.sid}: unmapped duty measure type {m.type_id} kept as 'other' (needs review)")
    return out, problems


def _xi_series_key(origin: str, m: XiMeasure) -> str:
    return f"EU|{XI_COMMODITY}|{origin}|{m.type_id}|{m.order_number or '-'}|{m.geo_id}"


class XiEuTariffCollector(Collector):
    key = "eu_tariff_xi"
    name = "Dazi UE sul miele: TARIC (servizio XI del governo britannico)"
    publisher = "HM Revenue & Customs, UK Online Trade Tariff (XI), dati TARIC della Commissione europea"
    homepage = "https://www.trade-tariff.service.gov.uk/xi/commodities/0409000000"
    kind = SourceKind.API
    reliability = Reliability.OFFICIAL
    category = "regulation"
    language = "en"
    expected_update = "Giornaliero (la TARIC UE cambia ogni giorno; i saldi dei contingenti più volte a settimana)"
    expected_update_en = "Daily (EU TARIC changes every day; quota balances several times a week)"
    expected_max_age_days = 7
    terms_note = ("The XI (Northern Ireland) service of the UK Online Trade Tariff is the UK government's official "
                  "mirror of the EU TARIC, which applies in Northern Ireland under the Windsor Framework. Contains "
                  "public sector information licensed under the Open Government Licence v3.0. The legally binding "
                  "source is EU TARIC and the EU act in the Official Journal: every measure links to both.")
    # After the daily TARIC update (about 07:30 CET) and before the morning briefing.
    schedule = {"trigger": "cron", "hour": 8, "minute": 12}
    order = 62

    def collect(self, ctx: CollectContext) -> None:
        t = today()
        doc = self._fetch(ctx, XI_COMMODITY_URL, "XI commodity 0409000000")
        com = parse_xi_commodity(doc.content)                    # probe: SchemaDrift stores nothing
        for p in com.problems:
            ctx.warn(f"XI: {p}")
        selected, problems = select_xi_tariff_measures(com)
        for p in problems:
            ctx.warn(f"XI: {p}")
        if not any(s.measure.type_id == "103" and s.measure.geo_id == XI_ERGA_OMNES for s in selected):
            raise SchemaDrift("XI commodity: no EU third-country duty (type 103) for ERGA OMNES (1011); every CN "
                              "line has one, so the measure model has changed. Nothing stored")

        complete = True                     # every measure resolved: safe to retire what disappeared
        groups: dict[str, tuple[str, ...] | None] = {}
        quotas: dict[str, XiQuota | None] = {}
        written: set[str] = set()
        keys_this_run: dict[str, int] = {}
        for s in selected:
            m = s.measure
            children = com.geos.get(m.geo_id).children if m.geo_id in com.geos else None
            if xi_is_group(m.geo_id) and m.geo_id != XI_ERGA_OMNES and children is None:
                if m.geo_id not in groups:
                    groups[m.geo_id] = self._group_members(ctx, m.geo_id)
                children = groups[m.geo_id]
            origins = expand_origins(m.geo_id, m.excluded, children)
            if origins is None:
                ctx.warn(f"XI: members of geographical group {m.geo_id} ({m.geo_description or '?'}) unknown; "
                         f"measure {m.sid} (type {m.type_id}) not stored this run")
                complete = False
                continue
            if not origins:
                continue
            quota: XiQuota | None = None
            if m.order_number:
                if m.order_number not in quotas:
                    quotas[m.order_number] = self._quota(ctx, m.order_number, t, com.quotas.get(m.order_number))
                quota = quotas[m.order_number]
                if quota is None:
                    complete = False
                    ctx.warn(f"XI: balance of quota {m.order_number} could not be read; its rows keep their "
                             f"previous values and are not re-dated this run")
                    continue
            for origin in origins:
                key = _xi_series_key(origin, m)
                if key in keys_this_run:            # same type/area/order twice (e.g. overlapping acts)
                    key = f"{key}|{m.sid}"
                keys_this_run[key] = 1
                self._record(ctx, written, key, origin, s, quota, doc, t)
        ctx.checkpoint()

        if complete:
            for key in tariff_svc.retire_missing(ctx.session, source_id=ctx.source.id, prefix=f"EU|{XI_COMMODITY}|",
                                                 keep=written):
                ctx.counters.revised += 1
                ctx.warn(f"XI: measure {key} is no longer published; kept in the history as withdrawn")
        else:
            ctx.warn("XI: some measures could not be resolved; withdrawn measures not checked this run")
        ctx.counters.newest_published = t
        ctx.counters.newest_period_label = t.isoformat()

    # ------------------------------------------------------------------ http
    def _fetch(self, ctx: CollectContext, url: str, what: str, params: Any = None) -> FetchResult:
        doc = ctx.fetch(url, params=params, accept_status=(200, 401, 403, 404), title=what)
        if doc.status_code in (401, 403):
            raise CollectorError(f"{what}: HTTP {doc.status_code}. The XI API now refuses anonymous access "
                                 f"(a developer key may have been introduced); see api.trade-tariff.service.gov.uk")
        if doc.status_code == 404:
            raise CollectorError(f"{what}: HTTP 404 for {doc.url} (CN code or API path changed?)")
        return doc

    def _group_members(self, ctx: CollectContext, geo_id: str) -> tuple[str, ...] | None:
        try:
            doc = self._fetch(ctx, XI_GEO_URL.format(geo_id=geo_id), f"XI geographical area {geo_id}")
            return parse_xi_geo_children(doc.content, geo_id)
        except Offline:
            raise
        except CollectorError as exc:
            ctx.warn(f"XI: geographical area {geo_id}: {exc}")
            return None

    def _quota(self, ctx: CollectContext, order_number: str, on: date, fallback: XiQuota | None) -> XiQuota | None:
        """Quota definition covering `on`: the quota search first, else the definition included in
        the commodity document. None when neither could be read."""
        params = [("order_number", order_number.replace(".", "")), ("years[]", str(on.year))]
        try:
            doc = self._fetch(ctx, XI_QUOTA_SEARCH_URL, f"XI quota {order_number}", params=params)
            quota, problems = parse_xi_quota_search(doc.content, order_number, on)
            for p in problems:
                ctx.warn(f"XI: {p}")
            if quota is not None:
                return quota
            if fallback is not None and fallback.covers(on):
                return fallback
            # The source answered and lists no definition for today: an empty quota row is the truth.
            return XiQuota(order_number=order_number, volume_kg=None, balance_kg=None, unit_raw=None, status=None,
                           status_raw=None, critical=None, valid_from=None, valid_to=None, last_allocation=None,
                           problems=["no definition for the current period"])
        except Offline:
            raise
        except CollectorError as exc:
            ctx.warn(f"XI: quota search {order_number} failed ({exc})")
            if fallback is not None and fallback.covers(on):
                return fallback
            return None

    # ----------------------------------------------------------------- write
    def _record(self, ctx: CollectContext, written: set[str], key: str, origin: str, s: XiSelected,
                quota: XiQuota | None, doc: FetchResult, t: date) -> None:
        m = s.measure
        first = m.legal_acts[0] if m.legal_acts else None
        excluded_origins = sorted({o for o in (xi_geo_to_iso3(e) for e in m.excluded) if o})
        extra: dict[str, Any] = {
            "mirror": XI_MIRROR_NOTE,
            "measure_sid": m.sid,
            "measure_type_id": m.type_id,
            "measure_type_series": m.type_series,
            "geo_area": {"id": m.geo_id, "description": m.geo_description, "group": xi_is_group(m.geo_id)},
            "excluded_geo": list(m.excluded) or None,
            "excluded_origins": excluded_origins or None,
            "legal_acts": [la.as_dict() for la in m.legal_acts] or None,
            "footnotes": list(m.footnotes) or None,
            "needs_review": s.needs_review,
            "review_reason": s.reason,
        }
        quota_fields: dict[str, Any] = {"quota_order_number": m.order_number}
        if quota is not None:
            quota_fields.update(quota_volume_kg=quota.volume_kg, quota_balance_kg=quota.balance_kg,
                                quota_status=quota.status)
            extra["quota"] = {
                "unit_raw": quota.unit_raw, "status_raw": quota.status_raw, "critical": quota.critical,
                "period_start": quota.valid_from.isoformat() if quota.valid_from else None,
                "period_end": quota.valid_to.isoformat() if quota.valid_to else None,
                "last_allocation_date": quota.last_allocation.isoformat() if quota.last_allocation else None,
                "note": "; ".join(quota.problems) or None,
                "shared_by_group": xi_is_group(m.geo_id),
            }
        fields = dict(
            jurisdiction="EU", origin_iso3=origin, hs_code=XI_COMMODITY, measure_type=s.layer.value,
            measure_code=m.type_id, description=m.type_description, **m.duty.fields(), **quota_fields,
            valid_from=m.start, valid_to=m.end,
            legal_reference="; ".join(la.code for la in m.legal_acts if la.code)[:300] or None,
            legal_url=first.url if first else None, consult_url=tariff_svc.taric_url(origin, t),
            source_url=doc.url, raw_document_id=doc.raw_document_id or None,
            published_at=first.published if first else None,
            extra={k: v for k, v in extra.items() if v is not None},
        )
        _record(ctx, written, key, t, fields)


def _record(ctx: CollectContext, written: set[str], key: str, as_of: date, fields: dict) -> None:
    """Append-only write through services.tariffs (the tariff counterpart of ctx.add_*)."""
    fields.setdefault("reliability", ctx.source.reliability)
    fields.setdefault("data_status", DataStatus.PUBLISHED.value)
    outcome, _row = tariff_svc.record_measure(ctx.session, source_id=ctx.source.id, series_key=key, as_of=as_of,
                                              **fields)
    ctx.counters.count(outcome)
    written.add(key)


# ===========================================================================
# 2) US: USITC Harmonized Tariff Schedule REST API
# ===========================================================================

HTS_BASE = "https://hts.usitc.gov/reststop"
HTS_EXPORT_URL = f"{HTS_BASE}/exportList"
HTS_SEARCH_URL = f"{HTS_BASE}/search"
HTS_HEADING = "0409.00.00"
HTS_HEADING_RANGE = ("0409", "0410")
# Chapter 99 ranges named in the research: 9903.01-9903.04 (2025 IEEPA, 2026 Section 122 and successor
# surcharge headings; illustrative) and 9903.88-9903.89 (Section 301, China). The flag says whether
# headings NOT referenced by a 0409 footnote are kept for review: country-wide surcharges reach goods
# through U.S. notes and annexes, not footnotes; Section 301 headings apply only to the 8-digit lines
# whose footnotes point at them, so an unreferenced 301 heading does not concern honey.
HTS_CH99_RANGES: tuple[tuple[str, str, bool], ...] = (("9903.01", "9903.04", True), ("9903.88", "9903.89", False))
HTS_REQUIRED_KEYS = ("htsno", "description", "general", "special", "other")
_CH99_RE = re.compile(r"\b99\d\d\.\d\d\.\d\d\b")
_ALL_COUNTRIES_RE = re.compile(r"\b(?:any|all|each|every)\s+(?:other\s+)?(?:foreign\s+)?countr(?:y|ies)\b", re.IGNORECASE)
_HONEY_RE = re.compile(r"\bhoney\b|\b0409(?:\.00(?:\.00)?)?\b", re.IGNORECASE)
# Series-key scopes, so each part is retired only after a complete read of that part.
HTS_KEY_BASE = f"US|{HTS_HEADING}|base"          # general rate and special-programme preferences
HTS_KEY_CH99 = f"US|{HTS_HEADING}|ch99"          # Chapter 99 additional-duty headings


@dataclass
class HtsRow:
    htsno: str
    indent: int | None
    description: str | None
    general: str | None
    special: str | None
    other: str | None
    footnotes: tuple[str, ...]


def _footnote_texts(value: Any) -> tuple[str, ...]:
    out: list[str] = []
    if isinstance(value, list):
        for f in value:
            txt = clean_text(f.get("value")) if isinstance(f, dict) else clean_text(f)
            if txt:
                out.append(txt)
    elif isinstance(value, str) and value.strip():
        out.append(clean_text(value) or "")
    return tuple(x for x in out if x)


def parse_hts_rows(content: bytes, what: str) -> list[HtsRow]:
    """HTS export/search answer: a JSON array of row objects. Raises SchemaDrift when it is not, or
    when no row carries the documented keys."""
    obj = _load_json(content, what)
    if isinstance(obj, dict) and isinstance(obj.get("results"), list):
        obj = obj["results"]
    if not isinstance(obj, list):
        raise SchemaDrift(f"{what}: expected a JSON array of rows, got {type(obj).__name__}")
    rows: list[HtsRow] = []
    keys_seen: set[str] = set()
    for r in obj:
        if not isinstance(r, dict):
            continue
        keys_seen.update(r)
        if not all(k in r for k in HTS_REQUIRED_KEYS):
            continue
        try:
            indent = int(str(r.get("indent")).strip()) if r.get("indent") not in (None, "") else None
        except ValueError:
            indent = None
        rows.append(HtsRow(
            htsno=str(r.get("htsno") or "").strip(), indent=indent, description=clean_text(r.get("description")),
            general=clean_text(r.get("general")), special=clean_text(r.get("special")), other=clean_text(r.get("other")),
            footnotes=_footnote_texts(r.get("footnotes")),
        ))
    if obj and not rows:
        raise SchemaDrift(f"{what}: no row has the keys {', '.join(HTS_REQUIRED_KEYS)} (keys seen: {sorted(keys_seen)[:15]})")
    return rows


@dataclass
class Ch99Decision:
    heading: str
    origin: str
    layer: MeasureType
    needs_review: bool
    reason: str | None
    scope: str
    named: list[str]
    duty: Duty
    honey_mentioned: bool
    footnote_ref: bool


def ch99_scope(description: str | None) -> tuple[str, list[str]]:
    """Country scope of a Chapter 99 heading as written: ('single', [ISO3]), ('all', []),
    ('mixed', [...]) for "all countries" plus named ones (exceptions?), ('multiple', [...]) or ('unknown', [])."""
    text = description or ""
    named = detect_countries(text, exclude=("USA",))
    all_scope = bool(_ALL_COUNTRIES_RE.search(text))
    if all_scope:
        return ("mixed", named) if named else ("all", [])
    if len(named) == 1:
        return "single", named
    if named:
        return "multiple", named
    return "unknown", []


def classify_ch99(row: HtsRow, footnote_ref: bool, scan_unreferenced: bool = True) -> Ch99Decision | None:
    """Decide whether a Chapter 99 heading is stored, for which origin and as what. None = ignored.

    surcharge (no review): the 0409 footnotes point at it, its text names exactly one country, that
      country is a Parodi origin and the additional rate parses.
    other + needs_review: everything else kept (footnote-referenced, mentions honey/0409, or an
      additional duty on all countries or on a Parodi origin). Origin = the single named country when
      it is a Parodi origin, otherwise ALL; the countries named are kept in extra, never expanded."""
    duty = parse_us_additional(row.general)
    has_additional = duty.complex or duty.parsed
    scope, named = ch99_scope(row.description)
    honey = bool(_HONEY_RE.search(row.description or ""))
    relevant_single = scope == "single" and named[0] in TARIFF_ORIGINS
    if scope == "single" and not relevant_single:
        return None                                  # one named country, not an origin Parodi follows
    if not footnote_ref:
        if not scan_unreferenced or not has_additional:
            return None                              # no additional duty (e.g. an exemption heading)
        if not (honey or scope == "all" or relevant_single
                or (scope in ("mixed", "multiple") and any(c in TARIFF_ORIGINS for c in named))):
            return None
    if footnote_ref and relevant_single and duty.parsed:
        return Ch99Decision(row.htsno, named[0], MeasureType.SURCHARGE, False, None, scope, named, duty, honey, True)
    if not footnote_ref:
        reason = "heading not referenced by 0409.00.00: whether it covers honey is not verified"
    elif not duty.parsed:
        reason = "additional rate not readable as a plain rate"
    else:
        reason = f"country scope not unambiguous ({scope})"
    origin = named[0] if relevant_single else ALL_ORIGINS
    return Ch99Decision(row.htsno, origin, MeasureType.OTHER, True, reason, scope, named, duty, honey, footnote_ref)


class UsHtsCollector(Collector):
    key = "us_hts"
    name = "Dazi USA sul miele: tariffa doganale HTS (USITC)"
    publisher = "U.S. International Trade Commission (USITC)"
    homepage = "https://hts.usitc.gov/search?query=0409.00.00"
    kind = SourceKind.API
    reliability = Reliability.OFFICIAL
    category = "regulation"
    country_iso3 = "USA"
    language = "en"
    expected_update = "A ogni revisione della tariffa HTS (molte all'anno); controllo settimanale"
    expected_update_en = "At every HTS revision (dozens per year); checked weekly"
    expected_max_age_days = 21
    terms_note = ("Public domain (US Government work). Rates are stored exactly as published in the HTS. Chapter 99 "
                  "headings whose country or product scope cannot be read unambiguously are stored as 'needs review' "
                  "and never assigned to an origin by guesswork. Anti-dumping duties are exporter-specific and are not "
                  "in the HTS: Paladex links the Federal Register documents instead.")
    schedule = {"trigger": "cron", "day_of_week": "mon,thu", "hour": 8, "minute": 27}
    order = 63

    def collect(self, ctx: CollectContext) -> None:
        t = today()
        written: set[str] = set()
        # --- 0409: probe + general and special rates
        doc = self._fetch(ctx, HTS_EXPORT_URL, f"HTS {HTS_HEADING_RANGE[0]}-{HTS_HEADING_RANGE[1]}",
                          {"from": HTS_HEADING_RANGE[0], "to": HTS_HEADING_RANGE[1], "format": "JSON", "styles": "false"})
        rows = parse_hts_rows(doc.content, "HTS 0409")
        base = next((r for r in rows if r.htsno == HTS_HEADING), None)
        if base is None:
            raise SchemaDrift(f"HTS 0409: no row {HTS_HEADING} (htsno seen: {[r.htsno for r in rows][:10]})")
        general = parse_us_rate(base.general)
        if not general.text:
            raise SchemaDrift(f"HTS {HTS_HEADING}: empty 'general' rate column")
        footnote_headings: list[str] = []
        stat_rows = []
        for r in rows:
            if r.htsno == HTS_HEADING or r.htsno.startswith(HTS_HEADING + "."):
                for f in r.footnotes:
                    footnote_headings += [h for h in _CH99_RE.findall(f) if h not in footnote_headings]
                if r.htsno != HTS_HEADING:
                    stat_rows.append({"htsno": r.htsno, "description": r.description})
        self._record_base(ctx, written, base, general, stat_rows, footnote_headings, doc, t)
        self._retire(ctx, f"{HTS_KEY_BASE}|", written)
        ctx.checkpoint()

        # --- Chapter 99: additional duties
        ch99_ok = True
        ch99_rows: dict[str, tuple[HtsRow, str, bool, FetchResult]] = {}
        for lo, hi, scan in HTS_CH99_RANGES:
            try:
                rdoc = self._fetch(ctx, HTS_EXPORT_URL, f"HTS {lo}-{hi}", {"from": lo, "to": hi, "format": "JSON", "styles": "false"})
                for r in parse_hts_rows(rdoc.content, f"HTS {lo}-{hi}"):
                    if _CH99_RE.fullmatch(r.htsno):
                        ch99_rows.setdefault(r.htsno, (r, f"{lo}-{hi}", scan, rdoc))
            except Offline:
                raise
            except CollectorError as exc:
                ch99_ok = False
                ctx.warn(f"HTS: Chapter 99 range {lo}-{hi} not read ({exc})")
        for h in footnote_headings:
            if h in ch99_rows:
                continue
            try:
                sdoc = self._fetch(ctx, HTS_SEARCH_URL, f"HTS search {h}", {"keyword": h})
                match = next((r for r in parse_hts_rows(sdoc.content, f"HTS search {h}") if r.htsno == h), None)
            except Offline:
                raise
            except CollectorError as exc:
                ch99_ok = False
                ctx.warn(f"HTS: heading {h} (footnote of {HTS_HEADING}) not read ({exc})")
                continue
            if match is None:
                ch99_ok = False
                ctx.warn(f"HTS: heading {h} is referenced by {HTS_HEADING} but the search did not return it")
                continue
            ch99_rows[h] = (match, "search", False, sdoc)
        for h in sorted(ch99_rows):
            row, origin_of, scan, rdoc = ch99_rows[h]
            decision = classify_ch99(row, h in footnote_headings, scan)
            if decision is not None:
                self._record_ch99(ctx, written, row, decision, origin_of, rdoc, t)
        if ch99_ok:
            self._retire(ctx, f"{HTS_KEY_CH99}|", written)
        else:
            ctx.warn("HTS: Chapter 99 not read completely; withdrawn headings not checked this run")
        ctx.checkpoint()
        ctx.counters.newest_published = t
        ctx.counters.newest_period_label = t.isoformat()

    # ------------------------------------------------------------------ http
    def _fetch(self, ctx: CollectContext, url: str, what: str, params: dict) -> FetchResult:
        doc = ctx.fetch(url, params=params, headers={"Accept": "application/json"},
                        accept_status=(200, 401, 403, 404), title=what)
        if doc.status_code in (401, 403):
            raise CollectorError(f"{what}: HTTP {doc.status_code}; the HTS API refuses anonymous access")
        if doc.status_code == 404:
            raise CollectorError(f"{what}: HTTP 404 for {doc.url} (API path changed?)")
        return doc

    def _retire(self, ctx: CollectContext, prefix: str, written: set[str]) -> None:
        for key in tariff_svc.retire_missing(ctx.session, source_id=ctx.source.id, prefix=prefix, keep=written):
            ctx.counters.revised += 1
            ctx.warn(f"HTS: {key} is no longer published; kept in the history as withdrawn")

    # ----------------------------------------------------------------- write
    def _record_base(self, ctx: CollectContext, written: set[str], base: HtsRow, general: Duty, stat_rows: list[dict],
                     footnote_headings: list[str], doc: FetchResult, t: date) -> None:
        groups, special_ok = parse_special(base.special)
        if not special_ok:
            ctx.warn(f"HTS {HTS_HEADING}: special column {base.special!r} not fully readable; only clear groups used")
        common = dict(jurisdiction="US", hs_code=HTS_HEADING, valid_from=None, valid_to=None,
                      consult_url=tariff_svc.hts_url(HTS_HEADING), legal_url=tariff_svc.hts_url(HTS_HEADING),
                      source_url=doc.url, raw_document_id=doc.raw_document_id or None)
        if general.complex:
            ctx.warn(f"HTS {HTS_HEADING}: general rate {general.text!r} kept as text (not a plain rate)")
        unmapped = sorted({c for _, codes in groups for c in codes if c not in US_PROGRAM_ORIGINS})
        extra = {
            "column": "general (column 1)",
            "description": base.description,
            "special_text": base.special,
            "special_programs_not_expanded": unmapped or None,
            "column2_text": base.other,
            "column2_note": "Column 2 applies only to the countries listed in General Note 3(b) of the HTSUS." if base.other else None,
            "statistical_suffixes": stat_rows or None,
            "chapter99_footnotes": footnote_headings or None,
            "footnotes": list(base.footnotes) or None,
            "needs_review": general.complex,
        }
        _record(ctx, written, f"{HTS_KEY_BASE}|{ALL_ORIGINS}|general", t, dict(
            common, origin_iso3=ALL_ORIGINS, measure_type=MeasureType.MFN.value, measure_code="general",
            description=base.description, **general.fields(), legal_reference=f"HTSUS {HTS_HEADING}, column 1 general",
            extra={k: v for k, v in extra.items() if v is not None},
        ))
        for rate_text, codes in groups:
            rate = parse_us_rate(rate_text)
            by_origin: dict[str, list[str]] = {}
            for c in codes:
                for o in US_PROGRAM_ORIGINS.get(c, ()):
                    by_origin.setdefault(o, []).append(c)
            for origin, ocodes in by_origin.items():
                code_label = ",".join(ocodes)
                names = sorted({US_PROGRAM_NAMES[c] for c in ocodes})
                _record(ctx, written, f"{HTS_KEY_BASE}|{origin}|special:{code_label}", t, dict(
                    common, origin_iso3=origin, measure_type=MeasureType.PREFERENCE.value,
                    measure_code=f"special:{code_label}", description=base.description,
                    **rate.fields(), legal_reference=f"HTSUS {HTS_HEADING}, special column, indicator {code_label}",
                    extra={"program_codes": ocodes, "program_names": names, "special_text": base.special,
                           "needs_review": rate.complex},
                ))

    def _record_ch99(self, ctx: CollectContext, written: set[str], row: HtsRow, d: Ch99Decision, origin_of: str,
                     doc: FetchResult, t: date) -> None:
        extra = {
            "heading": d.heading,
            "needs_review": d.needs_review,
            "review_reason": d.reason,
            "footnote_of_0409": d.footnote_ref,
            "country_scope": d.scope,
            "countries_named": d.named or None,
            "honey_mentioned": d.honey_mentioned or None,
            "read_from": origin_of,
            "footnotes": list(row.footnotes) or None,
        }
        _record(ctx, written, f"{HTS_KEY_CH99}|{d.heading}|{d.origin}", t, dict(
            jurisdiction="US", origin_iso3=d.origin, hs_code=HTS_HEADING, measure_type=d.layer.value,
            measure_code=d.heading, description=row.description, **d.duty.fields(),
            valid_from=None, valid_to=None, legal_reference=f"HTSUS {d.heading}",
            legal_url=tariff_svc.hts_url(d.heading), consult_url=tariff_svc.hts_url(d.heading),
            source_url=doc.url, raw_document_id=doc.raw_document_id or None,
            extra={k: v for k, v in extra.items() if v is not None},
        ))


__all__ = [
    "Duty",
    "SchemaDrift",
    "UsHtsCollector",
    "XiEuTariffCollector",
    "ch99_scope",
    "classify_ch99",
    "expand_origins",
    "parse_eu_duty",
    "parse_hts_rows",
    "parse_special",
    "parse_us_additional",
    "parse_us_rate",
    "parse_xi_commodity",
    "parse_xi_geo_children",
    "parse_xi_quota_search",
    "select_xi_tariff_measures",
    "xi_geo_to_iso3",
]
