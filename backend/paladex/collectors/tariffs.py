"""Tariff layer: official import duties on natural honey (HS 0409) per origin, EU and US.

Two keyless collectors. Both write ``TariffMeasure`` rows through ``services.tariffs.record_measure``,
which is append-only: a changed duty, validity or quota balance becomes a new revision, and a measure
the source stops publishing is retired (``is_current=False``), never deleted.

* ``eu_tariff_xi``: the UK Online Trade Tariff API v2, **XI (Northern Ireland) service**. Under the
  Windsor Framework the EU Common Customs Tariff applies in Northern Ireland, so HMRC publishes the
  EU TARIC measures in the XI service: it is the UK government's official, machine-readable mirror
  of EU TARIC (Open Government Licence v3.0). The legally binding source remains EU TARIC and the EU
  act in the Official Journal, so every row carries the EU legal act (``regulation_url`` on EUR-Lex)
  and a deep link to the official TARIC consultation filtered to its origin. Natural honey is the
  heading 0409 00 00 00 with two declarable lines since 1 May 2024 (0409 00 00 10 Manuka honey,
  0409 00 00 90 Other): ``/headings/0409`` lists them, each ``/commodities/{line}`` gives its import
  measures. A measure listed on every line (e.g. the 17.30 % third-country duty) is stored once under
  ``0409000000``; one listed on some lines only (e.g. the staged EU-New Zealand rate of the "Other"
  line) gets a row per line, with the line in ``hs_code`` and ``description``. The commodity
  documents do not list the tariff quotas: those come from ``/quotas/search?goods_nomenclature_item_id
  =0409000000`` (order number, volume, balance, period, measure ids) and ``/measures/{sid}`` (in-quota
  duty, origins, legal act). The collector keeps the EU import measures that are duties (third-country
  duty, tariff preferences, tariff quotas, additional duties, and any anti-dumping duty that would
  appear), expands geographical groups into the origins Parodi follows
  (``services.tariffs.TARIFF_ORIGINS``; ERGA OMNES stays one row).
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
XI was checked against the live API on 2026-11-04 (real captures in ``tests/fixtures/tariffs/real_*``).
HTS was written from ``docs/research/official_tariffs_trade_policy.json`` (``from_memory_unverified``).
Both collectors are defensive:

* Each run starts with a probe. XI: the heading document (``goods_nomenclature_item_id`` 0409000000
  with declarable child commodities, or ``import_measures`` itself), every line's commodity document
  with ``import_measures`` and ``included``, and the canary every CN line has (a third-country duty,
  measure type 103, for ERGA OMNES 1011). A line that cannot be read fails the run (a measure is
  assigned to the whole heading only when it is seen on every line). HTS: a JSON array of rows with
  ``htsno``/``general``/``special``/``other`` containing 0409.00.00 with a readable general rate. If
  the probe fails the run raises ``SchemaDrift`` and stores nothing. HTTP 401/403 is reported as "the
  API now needs a key".
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
XI_HEADING = "0409"
XI_COMMODITY = "0409000000"          # heading 0409 as a 10-digit code: measures that apply to every honey line
XI_HEADING_URL = f"{XI_BASE}/headings/{XI_HEADING}"
XI_COMMODITY_URL = XI_BASE + "/commodities/{code}"
XI_MEASURE_URL = XI_BASE + "/measures/{sid}"
XI_QUOTA_SEARCH_URL = f"{XI_BASE}/quotas/search"
XI_GEO_URL = XI_BASE + "/geographical_areas/{geo_id}"
XI_ERGA_OMNES = "1011"
XI_QUOTA_MAX_PAGES = 10              # the quota search pages by 5 definitions
XI_MIRROR_NOTE = ("UK Online Trade Tariff, XI (Northern Ireland) service: the UK government's mirror of EU TARIC "
                  "(Open Government Licence v3.0). Legally binding: EU TARIC and the EU act.")

# TARIC measure type id -> layer. Types not listed are kept only when their series is a duty series
# (C applicable duty, D anti-dumping/countervailing, J additional duties), as 'other' with needs_review.
XI_MEASURE_TYPES: dict[str, MeasureType] = {
    "103": MeasureType.MFN,               # Third country duty
    "142": MeasureType.PREFERENCE,        # Tariff preference
    "106": MeasureType.PREFERENCE,        # Customs Union Duty (the rate for customs-union partners, e.g. SM)
    "143": MeasureType.TRQ_IN,            # Preferential tariff quota
    "122": MeasureType.TRQ_IN,            # Non preferential tariff quota
    "551": MeasureType.ANTIDUMPING,       # Provisional anti-dumping duty
    "552": MeasureType.ANTIDUMPING,       # Definitive anti-dumping duty
    "553": MeasureType.ANTIDUMPING,       # Provisional countervailing duty
    "554": MeasureType.ANTIDUMPING,       # Definitive countervailing duty
    "555": MeasureType.ANTIDUMPING,       # Anti-dumping/countervailing duty - pending collection
    "695": MeasureType.SURCHARGE,         # Additional duties
    "696": MeasureType.SURCHARGE,         # Additional duties (safeguard)
    "107": MeasureType.OTHER,             # Low-value consignment customs duty (see XI_REVIEW_TYPES)
}
# Known duty measures that are not a rate on an ordinary import: stored as published, always
# flagged for review with this reason (and not reported as "unmapped" on every run).
XI_REVIEW_TYPES: dict[str, str] = {
    "107": ("Low-value consignment customs duty: a flat amount per item on low-value consignments (see the "
            "measure footnotes), not an ad valorem or per-kg rate on ordinary imports"),
}
XI_DUTY_SERIES = frozenset({"C", "D", "J"})
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
    conditions: tuple[dict, ...] = ()    # measure conditions as published (requirement, action, duty)
    footnote_texts: dict[str, str] = field(default_factory=dict)
    goods_code: str | None = None        # the goods code the measure is defined on, when the document says


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
    quotas: dict[str, XiQuota]           # order number -> definition included in the document
    problems: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class XiLeaf:
    code: str
    description: str | None


@dataclass
class XiNomenclature:
    """`GET /headings/0409`: the heading and the declarable CN lines under it. When the heading is
    itself declarable (it carries the import measures), `declarable` is True and `leaves` is the
    heading alone."""

    item_id: str
    description: str | None
    declarable: bool
    leaves: list[XiLeaf]


@dataclass
class XiQuotaListing:
    """One quota definition from the quota search: its order number, figures, measures and origins."""

    order_number: str
    definition: XiQuota
    measure_sids: tuple[str, ...]
    geo_ids: tuple[str, ...]


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


def _index(included: Any) -> dict[tuple[str, str], dict]:
    idx: dict[tuple[str, str], dict] = {}
    for o in included if isinstance(included, list) else []:
        if isinstance(o, dict) and o.get("type") is not None and o.get("id") is not None:
            idx[(str(o["type"]), str(o["id"]))] = o
    return idx


# A unit is recognised by its leading name or by the exact abbreviation in brackets, hectokilogram
# (TARIC DTN = 100 kg) first: an unanchored "kilogram" / "kg" would read "Hectokilogram (100 kg)" as kg.
_MASS_UNITS = (
    (re.compile(r"^\s*hectokilogram\b|^\s*100\s*kg\b|\(\s*100\s*kg\s*\)", re.IGNORECASE), 100.0),
    (re.compile(r"^\s*(?:tonne|metric\s+ton)\b|^\s*1\s*000\s*kg\b|\(\s*(?:t|1\s*000\s*kg)\s*\)", re.IGNORECASE), 1000.0),
    (re.compile(r"^\s*(?:kilogram|kg)\b", re.IGNORECASE), 1.0),
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


def _goods_code(obj: dict, idx: dict[tuple[str, str], dict]) -> str | None:
    gn = _rel_one(obj, "goods_nomenclature")
    if gn is None:
        return None
    code = clean_text(_attrs(idx.get(gn)).get("goods_nomenclature_item_id"))
    return code if code and re.fullmatch(r"\d{10}", code) else None


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
    footnote_texts = {fid: text[:600] for fid in footnotes
                      if (text := clean_text(_attrs(idx.get(("footnote", fid))).get("description")))}
    conditions: list[dict] = []
    for typ, cid in _rel_many(m, "measure_conditions"):
        ca = _attrs(idx.get((typ or "measure_condition", cid)))
        if not ca:
            continue
        cond = {"condition": clean_text(ca.get("condition")),
                "requirement": clean_text(ca.get("requirement")) or clean_text(ca.get("certificate_description")),
                "document_code": clean_text(ca.get("document_code")), "action": clean_text(ca.get("action")),
                "duty": clean_text(ca.get("duty_expression"))}
        conditions.append({k: v for k, v in cond.items() if v})
    origin_flag = a.get("origin")
    is_import = a.get("import")
    return XiMeasure(
        sid=sid, type_id=type_id, type_description=clean_text(mt_attrs.get("description")),
        type_series=clean_text(mt_attrs.get("measure_type_series_id")), geo_id=geo_id,
        geo_description=clean_text(geo_attrs.get("description")), excluded=tuple(excluded),
        duty=parse_eu_duty(raw_duty), start=parse_iso_date(a.get("effective_start_date")),
        end=parse_iso_date(a.get("effective_end_date")), order_number=order_number, legal_acts=tuple(acts),
        footnotes=footnotes, origin_flag=str(origin_flag).lower() if isinstance(origin_flag, str) else None,
        is_import=is_import if isinstance(is_import, bool) else None, conditions=tuple(conditions),
        footnote_texts=footnote_texts, goods_code=_goods_code(m, idx),
    )


def _xi_geos(idx: dict[tuple[str, str], dict]) -> dict[str, XiGeo]:
    geos: dict[str, XiGeo] = {}
    for (typ, gid), o in idx.items():
        if typ != "geographical_area":
            continue
        children = None
        if _has_rel(o, "children_geographical_areas"):
            children = tuple(cid for _, cid in _rel_many(o, "children_geographical_areas"))
        geos[gid] = XiGeo(gid, clean_text(_attrs(o).get("description")), children)
    return geos


def _xi_inline_quotas(idx: dict[tuple[str, str], dict]) -> dict[str, XiQuota]:
    """Quota definitions included next to their order numbers (order_number -> definition)."""
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
    return quotas


def parse_xi_nomenclature(content: bytes, item_id: str = XI_COMMODITY) -> XiNomenclature:
    """Parse `GET /headings/0409` (JSON:API). Natural honey is a heading with declarable child
    commodities (since 1 May 2024: 0409000010 Manuka honey and 0409000090 Other); only those lines
    carry import measures. A declarable heading (with `import_measures` itself) is accepted too.
    Raises ``SchemaDrift`` when neither measures nor declarable lines can be found."""
    obj = _load_json(content, "XI heading 0409")
    if not isinstance(obj, dict) or not isinstance(obj.get("data"), dict):
        raise SchemaDrift(f"XI heading 0409: no JSON:API 'data' object (top-level keys: "
                          f"{sorted(obj)[:10] if isinstance(obj, dict) else type(obj).__name__})")
    data = obj["data"]
    attrs = _attrs(data)
    got = str(attrs.get("goods_nomenclature_item_id") or "")
    if got != item_id:
        raise SchemaDrift(f"XI heading 0409: goods_nomenclature_item_id is {got!r}, expected {item_id!r}")
    description = clean_text(attrs.get("description"))
    if _has_rel(data, "import_measures"):
        return XiNomenclature(item_id=got, description=description, declarable=True, leaves=[XiLeaf(got, description)])
    idx = _index(obj.get("included"))
    leaves: list[XiLeaf] = []
    for typ, cid in _rel_many(data, "commodities"):
        ca = _attrs(idx.get((typ or "commodity", cid)))
        code = str(ca.get("goods_nomenclature_item_id") or "")
        declarable = ca.get("declarable")
        if declarable is None:
            declarable = ca.get("leaf")
        if declarable is not True or not re.fullmatch(rf"{XI_HEADING}\d{{6}}", code):
            continue
        if code not in {lf.code for lf in leaves}:
            leaves.append(XiLeaf(code, clean_text(ca.get("description"))))
    if not leaves:
        raise SchemaDrift(f"XI heading 0409: no import_measures and no declarable commodity under it "
                          f"(relationships: {sorted((data.get('relationships') or {}))[:12]})")
    return XiNomenclature(item_id=got, description=description, declarable=False, leaves=sorted(leaves, key=lambda x: x.code))


def parse_xi_commodity(content: bytes, item_id: str = XI_COMMODITY) -> XiCommodity:
    """Parse an XI commodity document (JSON:API) of a declarable line. Raises ``SchemaDrift`` when
    the envelope is not the documented one or no import measure can be resolved; malformed measures
    become problems."""
    what = f"XI commodity {item_id}"
    obj = _load_json(content, what)
    if not isinstance(obj, dict) or not isinstance(obj.get("data"), dict):
        raise SchemaDrift(f"{what}: no JSON:API 'data' object (top-level keys: "
                          f"{sorted(obj)[:10] if isinstance(obj, dict) else type(obj).__name__})")
    data = obj["data"]
    attrs = _attrs(data)
    got = str(attrs.get("goods_nomenclature_item_id") or "")
    if got != item_id:
        raise SchemaDrift(f"{what}: goods_nomenclature_item_id is {got!r}, expected {item_id!r}")
    if not _has_rel(data, "import_measures"):
        raise SchemaDrift(f"{what}: no relationships.import_measures (relationships: "
                          f"{sorted((data.get('relationships') or {}))[:12]})")
    included = obj.get("included")
    if not isinstance(included, list):
        raise SchemaDrift(f"{what}: 'included' is missing or not a list")
    idx = _index(included)
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
        raise SchemaDrift(f"{what}: none of the {len(refs)} import measures could be resolved "
                          f"(included types: {sorted({t for t, _ in idx})[:15]})")
    return XiCommodity(item_id=got, description=clean_text(attrs.get("description")), measures=measures,
                       geos=_xi_geos(idx), quotas=_xi_inline_quotas(idx), problems=problems)


def parse_xi_measure_document(content: bytes, sid: str) -> XiCommodity:
    """`GET /measures/{sid}`: one measure with its type, duty, legal acts, area (group members
    included), order number and current definition. Returned as a one-measure XiCommodity."""
    what = f"XI measure {sid}"
    obj = _load_json(content, what)
    data = obj.get("data") if isinstance(obj, dict) else None
    if not isinstance(data, dict) or str(data.get("id")) != sid or data.get("type") != "measure":
        raise SchemaDrift(f"{what}: no JSON:API measure object with id {sid}")
    idx = _index(obj.get("included"))
    problems: list[str] = []
    m = _xi_measure(data, idx, problems)
    if m is None:
        raise SchemaDrift(f"{what}: {'; '.join(problems) or 'unreadable'}")
    return XiCommodity(item_id=m.goods_code or "", description=None, measures=[m], geos=_xi_geos(idx),
                       quotas=_xi_inline_quotas(idx), problems=problems)


def parse_xi_quota_listing(content: bytes, what: str) -> tuple[list[XiQuotaListing], dict, list[str]]:
    """`GET /quotas/search?goods_nomenclature_item_id=...`: the quota definitions of a goods code,
    with their measures and origins. Returns (listings, pagination, problems)."""
    obj = _load_json(content, what)
    if not isinstance(obj, dict) or not isinstance(obj.get("data"), list):
        raise SchemaDrift(f"{what}: no 'data' list")
    idx = _index(obj.get("included"))
    problems: list[str] = []
    out: list[XiQuotaListing] = []
    with_figures = 0
    for d in obj["data"]:
        if not isinstance(d, dict):
            continue
        a = _attrs(d)
        if "initial_volume" in a or "balance" in a:
            with_figures += 1
        rel = _rel_one(d, "order_number") or _rel_one(d, "quota_order_number")
        number = clean_text(a.get("quota_order_number_id")) or (rel[1] if rel else None)
        if not number:
            problems.append(f"{what}: a definition without order number; skipped")
            continue
        q = parse_xi_definition(a, number)
        problems += q.problems
        geos = tuple(gid for _, gid in _rel_many(idx.get(("order_number", number)) or {}, "geographical_areas"))
        out.append(XiQuotaListing(number, q, tuple(mid for _, mid in _rel_many(d, "measures")), geos))
    if obj["data"] and not with_figures:
        raise SchemaDrift(f"{what}: definitions carry neither 'initial_volume' nor 'balance'")
    meta = obj.get("meta") if isinstance(obj.get("meta"), dict) else {}
    pagination = meta.get("pagination") if isinstance(meta.get("pagination"), dict) else {}
    return out, pagination, problems


def covering_definition(defs: Iterable[XiQuota], on: date) -> XiQuota | None:
    """The definition that covers `on` (the latest-starting one if several)."""
    covering = sorted((q for q in defs if q.covers(on)), key=lambda q: q.valid_from or date.min)
    return covering[-1] if covering else None


def parse_xi_quota_search(content: bytes, order_number: str, on: date) -> tuple[XiQuota | None, list[str]]:
    """`GET /quotas/search?order_number=...`: the definition of `order_number` that covers date `on`
    (the latest-starting one if several). Returns (None, problems) when the source lists no
    definition for that date (e.g. early January)."""
    listings, _pagination, problems = parse_xi_quota_listing(content, f"XI quota search {order_number}")
    found: list[XiQuota] = []
    for lst in listings:
        if lst.order_number.replace(".", "") != order_number.replace(".", ""):
            problems.append(f"quota search {order_number}: returned order number {lst.order_number}; ignored")
            continue
        found.append(lst.definition)
    q = covering_definition(found, on)
    if q is None and found:
        problems.append(f"quota {order_number}: no definition covers {on.isoformat()}")
    return q, problems


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


def _review_reason(m: XiMeasure) -> str | None:
    if m.type_id in XI_REVIEW_TYPES:
        return XI_REVIEW_TYPES[m.type_id]
    if not m.duty.complex:
        return None
    if m.duty.text is None and any(c.get("duty") for c in m.conditions):
        return "the duty depends on the measure conditions (see 'conditions'), not a single rate"
    return "duty expression not reducible to a rate"


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
            reason = _review_reason(m)
            out.append(XiSelected(m, layer, reason is not None, reason))
        elif (m.type_series or "").upper() in XI_DUTY_SERIES:
            out.append(XiSelected(m, MeasureType.OTHER, True,
                                  f"TARIC measure type {m.type_id} ({m.type_description or 'no description'}) not mapped"))
            problems.append(f"measure {m.sid}: unmapped duty measure type {m.type_id} kept as 'other' (needs review)")
    return out, problems


def _xi_series_key(code: str, origin: str, m: XiMeasure) -> str:
    return f"EU|{code}|{origin}|{m.type_id}|{m.order_number or '-'}|{m.geo_id}"


def _has_mfn_canary(com: XiCommodity) -> bool:
    return any(m.type_id == "103" and m.geo_id == XI_ERGA_OMNES and m.origin_flag in (None, "eu")
               for m in com.measures)


@dataclass
class _XiRead:
    """Everything read in one run: measures merged across the declarable lines (by measure sid)."""

    leaves: list[XiLeaf]
    measures: dict[str, XiMeasure] = field(default_factory=dict)
    codes: dict[str, set[str]] = field(default_factory=dict)          # sid -> CN lines it was listed on
    docs: dict[str, FetchResult] = field(default_factory=dict)        # sid -> document it was read from
    geos: dict[str, XiGeo] = field(default_factory=dict)
    inline_quotas: dict[str, XiQuota] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    @property
    def all_codes(self) -> set[str]:
        return {lf.code for lf in self.leaves}

    def add(self, com: XiCommodity, codes: set[str], doc: FetchResult) -> None:
        for m in com.measures:
            if m.sid not in self.measures:
                self.measures[m.sid] = m
                self.docs[m.sid] = doc
            self.codes.setdefault(m.sid, set()).update(codes)
        for gid, g in com.geos.items():
            if gid not in self.geos or (self.geos[gid].children is None and g.children is not None):
                self.geos[gid] = g
        for number, q in com.quotas.items():
            self.inline_quotas.setdefault(number, q)
        for p in com.problems:
            if p not in self.problems:
                self.problems.append(p)


class XiEuTariffCollector(Collector):
    key = "eu_tariff_xi"
    name = "Dazi UE sul miele: TARIC (servizio XI del governo britannico)"
    publisher = "HM Revenue & Customs, UK Online Trade Tariff (XI), dati TARIC della Commissione europea"
    homepage = "https://www.trade-tariff.service.gov.uk/xi/headings/0409"
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
        read = self._read_lines(ctx)                             # probe: SchemaDrift stores nothing
        complete = True                     # everything resolved: safe to retire what disappeared
        quota_defs, listing_ok = self._quota_listing(ctx, read)
        complete &= listing_ok
        for p in read.problems:
            ctx.warn(f"XI: {p}")
        com = XiCommodity(item_id=XI_COMMODITY, description=None, measures=list(read.measures.values()),
                          geos=read.geos, quotas=read.inline_quotas)
        selected, problems = select_xi_tariff_measures(com)
        for p in problems:
            ctx.warn(f"XI: {p}")

        groups: dict[str, tuple[str, ...] | None] = {}
        quotas: dict[str, XiQuota | None] = {}
        written: set[str] = set()
        keys_this_run: dict[str, int] = {}
        leaf_desc = {lf.code: lf.description for lf in read.leaves}
        # Deterministic order, so a duplicate key gets the same "|sid" suffix on every run.
        for s in sorted(selected, key=lambda x: (x.measure.type_id, x.measure.geo_id, x.measure.order_number or "",
                                                  x.measure.sid)):
            m = s.measure
            children = read.geos[m.geo_id].children if m.geo_id in read.geos else None
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
                    quotas[m.order_number] = self._quota(ctx, m.order_number, t, quota_defs,
                                                         read.inline_quotas.get(m.order_number))
                quota = quotas[m.order_number]
                if quota is None:
                    complete = False
                    ctx.warn(f"XI: balance of quota {m.order_number} could not be read; its rows keep their "
                             f"previous values and are not re-dated this run")
                    continue
            codes = read.codes.get(m.sid, set())
            # A measure listed on every declarable line applies to the whole heading: one row under
            # 0409000000. One listed on some lines only (e.g. a staged FTA rate) gets a row per line.
            targets = [XI_COMMODITY] if codes == read.all_codes else sorted(codes)
            for code in targets:
                for origin in origins:
                    key = _xi_series_key(code, origin, m)
                    if key in keys_this_run:            # same type/area/order twice (e.g. overlapping acts)
                        key = f"{key}|{m.sid}"
                    keys_this_run[key] = 1
                    self._record(ctx, written, key, code, leaf_desc, origin, s, quota, read.docs[m.sid], t)
        ctx.checkpoint()

        if complete:
            for key in tariff_svc.retire_missing(ctx.session, source_id=ctx.source.id, prefix=f"EU|{XI_HEADING}",
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

    def _read_lines(self, ctx: CollectContext) -> _XiRead:
        """The heading, then every declarable line under it. All lines must be read (a measure is
        assigned to the heading only when it is listed on every line): any failure fails the run."""
        head = self._fetch(ctx, XI_HEADING_URL, "XI heading 0409")
        nom = parse_xi_nomenclature(head.content)
        read = _XiRead(leaves=nom.leaves)
        if nom.declarable:
            docs = [(nom.leaves[0], head)]
        else:
            # "Other" (0409000090, every honey but Manuka) is read first, so the measures common to
            # all lines cite the line bulk honey is declared under.
            docs = [(lf, self._fetch(ctx, XI_COMMODITY_URL.format(code=lf.code), f"XI commodity {lf.code}"))
                    for lf in sorted(nom.leaves, key=lambda x: x.code, reverse=True)]
        for leaf, doc in docs:
            com = parse_xi_commodity(doc.content, leaf.code)
            if not _has_mfn_canary(com):
                raise SchemaDrift(f"XI commodity {leaf.code}: no EU third-country duty (type 103) for ERGA OMNES "
                                  f"(1011); every CN line has one, so the measure model has changed. Nothing stored")
            read.add(com, {leaf.code}, doc)
        return read

    def _quota_listing(self, ctx: CollectContext, read: _XiRead) -> tuple[dict[str, list[XiQuota]], bool]:
        """Tariff quotas on honey. The commodity documents do not list the quota measures, so the
        quota search by goods code gives the order numbers, definitions (volume, balance, period)
        and measure ids; each quota measure not already read is fetched from /measures/{sid}.
        Returns (definitions by order number, complete)."""
        defs: dict[str, list[XiQuota]] = {}
        listings: list[XiQuotaListing] = []
        what = f"XI quota search {XI_COMMODITY}"
        try:
            page = 1
            while page <= XI_QUOTA_MAX_PAGES:
                params = [("goods_nomenclature_item_id", XI_COMMODITY)] + ([("page", str(page))] if page > 1 else [])
                doc = self._fetch(ctx, XI_QUOTA_SEARCH_URL, what if page == 1 else f"{what} page {page}", params=params)
                found, pagination, problems = parse_xi_quota_listing(doc.content, what)
                for p in problems:
                    ctx.warn(f"XI: {p}")
                listings += found
                total, per_page = _num(pagination.get("total_count")), _num(pagination.get("per_page"))
                if not found or total is None or not per_page or page * per_page >= total:
                    break
                page += 1
            else:
                ctx.warn(f"XI: quota search for {XI_COMMODITY} has more than {XI_QUOTA_MAX_PAGES} pages; the rest "
                         f"is not read this run")
                return defs, False
        except Offline:
            raise
        except CollectorError as exc:
            ctx.warn(f"XI: quota search for {XI_COMMODITY} failed ({exc}); quota rows keep their previous values")
            return defs, False
        complete = True
        for lst in listings:
            defs.setdefault(lst.order_number, []).append(lst.definition)
            if lst.geo_ids and all(not xi_is_group(g) and xi_geo_to_iso3(g) not in TARIFF_ORIGINS for g in lst.geo_ids):
                continue                        # e.g. Algeria, Tunisia: not an origin Parodi follows
            for sid in lst.measure_sids:
                if sid in read.measures:
                    continue
                try:
                    doc = self._fetch(ctx, XI_MEASURE_URL.format(sid=sid), f"XI measure {sid} (quota {lst.order_number})")
                    one = parse_xi_measure_document(doc.content, sid)
                except Offline:
                    raise
                except CollectorError as exc:
                    ctx.warn(f"XI: quota {lst.order_number}: measure {sid} could not be read ({exc}); not stored "
                             f"this run")
                    complete = False
                    continue
                m = one.measures[0]
                code = m.goods_code or XI_COMMODITY
                if code == XI_COMMODITY:            # defined on the heading: applies to every line
                    codes = read.all_codes
                elif code in read.all_codes:
                    codes = {code}
                else:
                    ctx.warn(f"XI: quota {lst.order_number}: measure {sid} is on goods code {code}, not a honey line; "
                             f"ignored")
                    continue
                read.add(one, codes, doc)
        return defs, complete

    def _group_members(self, ctx: CollectContext, geo_id: str) -> tuple[str, ...] | None:
        try:
            doc = self._fetch(ctx, XI_GEO_URL.format(geo_id=geo_id), f"XI geographical area {geo_id}")
            return parse_xi_geo_children(doc.content, geo_id)
        except Offline:
            raise
        except CollectorError as exc:
            ctx.warn(f"XI: {exc}")
            return None

    def _quota(self, ctx: CollectContext, order_number: str, on: date, listed: dict[str, list[XiQuota]],
               fallback: XiQuota | None) -> XiQuota | None:
        """Quota definition covering `on`: from the quota search by goods code when it listed this
        order number, else from a search by order number, else the definition included in the
        document. None when nothing could be read."""
        empty = XiQuota(order_number=order_number, volume_kg=None, balance_kg=None, unit_raw=None, status=None,
                        status_raw=None, critical=None, valid_from=None, valid_to=None, last_allocation=None,
                        problems=["no definition for the current period"])
        if order_number in listed:
            q = covering_definition(listed[order_number], on)
            if q is not None:
                return q
            if fallback is not None and fallback.covers(on):
                return fallback
            ctx.warn(f"XI: quota {order_number}: no definition covers {on.isoformat()}")
            return empty
        params = [("order_number", order_number.replace(".", ""))]
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
            return empty
        except Offline:
            raise
        except CollectorError as exc:
            ctx.warn(f"XI: quota search {order_number} failed ({exc})")
            if fallback is not None and fallback.covers(on):
                return fallback
            return None

    # ----------------------------------------------------------------- write
    def _record(self, ctx: CollectContext, written: set[str], key: str, code: str, leaf_desc: dict[str, str | None],
                origin: str, s: XiSelected, quota: XiQuota | None, doc: FetchResult, t: date) -> None:
        m = s.measure
        first = m.legal_acts[0] if m.legal_acts else None
        excluded_origins = sorted({o for o in (xi_geo_to_iso3(e) for e in m.excluded) if o})
        description = m.type_description
        if code != XI_COMMODITY:
            description = f"{m.type_description or 'Measure'} (CN {code}: {leaf_desc.get(code) or '?'})"
        extra: dict[str, Any] = {
            "mirror": XI_MIRROR_NOTE,
            "measure_sid": m.sid,
            "measure_type_id": m.type_id,
            "measure_type_series": m.type_series,
            "cn_code": code,
            "cn_scope": "heading" if code == XI_COMMODITY else "line",
            "cn_lines": [{"code": c, "description": leaf_desc.get(c)} for c in sorted(leaf_desc)] if code == XI_COMMODITY
            else [{"code": code, "description": leaf_desc.get(code)}],
            "geo_area": {"id": m.geo_id, "description": m.geo_description, "group": xi_is_group(m.geo_id)},
            "excluded_geo": list(m.excluded) or None,
            "excluded_origins": excluded_origins or None,
            "legal_acts": [la.as_dict() for la in m.legal_acts] or None,
            "footnotes": list(m.footnotes) or None,
            "footnote_texts": m.footnote_texts or None,
            "conditions": list(m.conditions) or None,
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
            jurisdiction="EU", origin_iso3=origin, hs_code=code, measure_type=s.layer.value,
            measure_code=m.type_id, description=description, **m.duty.fields(), **quota_fields,
            valid_from=m.start, valid_to=m.end,
            legal_reference="; ".join(la.code for la in m.legal_acts if la.code)[:300] or None,
            legal_url=first.url if first else None, consult_url=tariff_svc.taric_url(origin, t, code),
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
