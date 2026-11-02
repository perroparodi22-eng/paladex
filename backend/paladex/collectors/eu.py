"""European Union honey sources: four collectors in one module.

* ``eurostat_comext``: Eurostat Comext DS-045409 (JSON-stat 2.0). Monthly imports and exports
  of CN 04090000 for the EU27 and the main member states, by partner, with derived import
  and export unit values.
* ``ec_taxud_weekly``: EC Agri-food Data Portal, TAXUD weekly import surveillance for the
  "Honey" sector. Provisional customs data, about 5 weeks ahead of Comext.
* ``ec_honey_market``: DG AGRI honey page. Detects new "Honey market overview / presentation"
  PDFs, archives them and registers them as reports. Narrative text is always stored; a
  price table is parsed only when its structure is unambiguous.
* ``rasff_honey``: RASFF Window food-safety notifications for honey, via the undocumented
  JSON backend of the public RASFF Window.

None of these hosts could be reached while this module was written. The formats follow
``docs/research/eu.json``, which says for each item what is verified and what is
reconstructed. The test fixtures in ``tests/fixtures/eu/`` follow the same documentation.
Every parser fails loudly (``CollectorError``) on schema drift rather than store doubtful
numbers. Malformed single rows produce ``ctx.warn`` and are skipped.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

from dateutil.parser import isoparse
from sqlalchemy import select

from ..enums import DataStatus, PriceType, Reliability, SourceKind, TradeFlow, Variety
from ..models import AppSetting, RegulationItem, Report, TradeFlowObservation, utcnow
from ..reference.countries import country_name, lookup_iso3
from .base import CollectContext, Collector, CollectorError, FetchResult, month_bounds, year_bounds

log = logging.getLogger(__name__)

JSON_HEADERS = {"Accept": "application/json"}

# A customs unit value is derived as value / net weight. On tiny consignments (samples,
# a few jars) it says nothing about the bulk market and is often extreme, so price rows are
# derived only when the flow weighs at least this much. The trade row itself is always kept.
MIN_UNIT_VALUE_WEIGHT_KG = 1_000.0


def today() -> date:
    """Reference date for look-back windows (indirection so tests can pin it)."""
    return date.today()


# ---------------------------------------------------------------------------
# Geography: Comext / customs codes -> ISO3 or platform pseudo-codes
# ---------------------------------------------------------------------------

# Codes that are not plain ISO 3166 alpha-2, or are aggregates. Comext uses its own
# geonomenclature: Serbia is "XS" (not RS); Greece is "GR" in Comext and "EL" in Eurostat
# and agridata; the United Kingdom is "GB" (and "UK" in older agridata years).
GEO_OVERRIDES: dict[str, str] = {
    "EU27_2020": "EU27",
    "EXT_EU27_2020": "EXTRA_EU",
    "WORLD": "WLD",
    "XS": "SRB",
    "EL": "GRC",
    "GR": "GRC",
    "UK": "GBR",
    "GB": "GBR",
}

# Customs pseudo-partners that are not countries (stores and provisions, high seas,
# countries not specified ...). They are skipped quietly: they are not origins.
NON_COUNTRY_CODES = frozenset({"QP", "QQ", "QR", "QS", "QU", "QV", "QW", "QX", "QY", "QZ", "XX"})

AGGREGATE_CODES = frozenset({"EU27", "EXTRA_EU", "WLD"})


def map_geo(code: Any) -> str | None:
    """Map a Comext/agridata/RASFF geo code to ISO3 (or EU27 / EXTRA_EU / WLD). None if unknown."""
    c = str(code or "").strip().upper()
    if not c:
        return None
    if c in GEO_OVERRIDES:
        return GEO_OVERRIDES[c]
    if c in NON_COUNTRY_CODES or len(c) not in (2, 3):
        return None
    return lookup_iso3(c)


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------


def _load_json(content: bytes, what: str) -> Any:
    try:
        return json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        snippet = content[:120].decode("utf-8", errors="replace").strip()
        raise CollectorError(f"{what}: response is not valid JSON ({exc}); starts with {snippet!r}") from exc


def _num(v: Any) -> float | None:
    """A finite number from a JSON number or a plain numeric string, else None."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        f = float(v)
    elif isinstance(v, str):
        try:
            f = float(v.strip())
        except ValueError:
            return None
    else:
        return None
    return f if math.isfinite(f) else None


def _int(v: Any) -> int | None:
    f = _num(v)
    return int(f) if f is not None and f == int(f) else None


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def _get_state(session, key: str) -> dict:
    row = session.get(AppSetting, f"collector_state:{key}")
    return dict(row.value) if row is not None and isinstance(row.value, dict) else {}


def _set_state(session, key: str, value: dict) -> None:
    """Small per-collector bookkeeping (not observations): e.g. the last Comext vintage seen."""
    full_key = f"collector_state:{key}"
    row = session.get(AppSetting, full_key)
    if row is None:
        session.add(AppSetting(key=full_key, value=value))
    else:
        row.value = value


def _has_rows(ctx: CollectContext, model) -> bool:
    return ctx.session.scalar(select(model.id).where(model.source_id == ctx.source.id).limit(1)) is not None


# ===========================================================================
# 1) JSON-stat 2.0 decoder (generic)
# ===========================================================================


class JsonStatError(CollectorError):
    """The document is not a decodable JSON-stat dataset."""


@dataclass(frozen=True)
class JsonStatCell:
    coords: dict[str, str]      # dimension id -> category code
    value: Any                  # as published (number); validated by the caller
    status: str | None = None


@dataclass
class JsonStatDataset:
    ids: list[str]
    sizes: list[int]
    categories: dict[str, list[str]]          # dimension id -> codes in position order
    labels: dict[str, dict[str, str]]         # dimension id -> code -> label
    cells: list[JsonStatCell]
    updated: str | None = None
    extension: dict = field(default_factory=dict)

    def no_data_codes(self, dim: str) -> set[str]:
        """Codes the publisher lists under extension['positions-with-no-data'][dim] (Eurostat)."""
        positions = (self.extension.get("positions-with-no-data") or {}).get(dim) or []
        codes = self.categories.get(dim, [])
        return {codes[p] for p in positions if isinstance(p, int) and 0 <= p < len(codes)}


def _category_codes(dim_id: str, dim: Any, size: int) -> tuple[list[str], dict[str, str]]:
    if not isinstance(dim, dict) or not isinstance(dim.get("category"), dict):
        raise JsonStatError(f"JSON-stat dimension {dim_id!r} has no 'category' object")
    cat = dim["category"]
    raw_labels = cat.get("label")
    labels = {str(k): str(v) for k, v in raw_labels.items()} if isinstance(raw_labels, dict) else {}
    index = cat.get("index")
    if index is None:
        # JSON-stat allows omitting 'index' for a single-category dimension.
        if size == 1 and len(labels) == 1:
            return list(labels), labels
        raise JsonStatError(f"JSON-stat dimension {dim_id!r} has no category.index")
    if isinstance(index, list):
        codes: list[str | None] = [str(c) for c in index]
    elif isinstance(index, dict):
        codes = [None] * size
        for code, pos in index.items():
            if isinstance(pos, bool) or not isinstance(pos, int) or not 0 <= pos < size or codes[pos] is not None:
                raise JsonStatError(f"JSON-stat dimension {dim_id!r}: invalid or duplicate position {pos!r} for {code!r}")
            codes[pos] = str(code)
    else:
        raise JsonStatError(f"JSON-stat dimension {dim_id!r}: category.index must be an object or a list")
    if len(codes) != size or any(c is None for c in codes):
        raise JsonStatError(f"JSON-stat dimension {dim_id!r}: category.index has {len(index)} entries but size is {size}")
    return [c for c in codes if c is not None], labels


def _status_getter(status: Any, total: int):
    if status is None:
        return lambda i: None
    if isinstance(status, str):
        return lambda i: status
    if isinstance(status, list):
        return lambda i: status[i] if i < len(status) else None
    if isinstance(status, dict):
        return lambda i: status.get(str(i))
    raise JsonStatError("JSON-stat 'status' must be null, a string, a list or an object")


def decode_jsonstat(doc: Any) -> JsonStatDataset:
    """Decode a JSON-stat 2.0 *dataset* into one cell per published value.

    Values may be dense (a list, with null for missing cells) or sparse (an object keyed by
    the flat cell index as a string, as Eurostat publishes them). The flat index is row-major
    over `id` order, so the last dimension varies fastest:
    ``flat = sum(pos[k] * prod(size[k+1:]))``. A position is mapped back to its code through
    ``dimension[d].category.index`` (object ``{code: position}`` or list of codes), never
    through the order of keys in the JSON. Missing cells are not returned: absent means no
    data, never zero.
    """
    if not isinstance(doc, dict):
        raise JsonStatError("JSON-stat document must be an object")
    ids, sizes, dims = doc.get("id"), doc.get("size"), doc.get("dimension")
    if not isinstance(ids, list) or not isinstance(sizes, list) or not isinstance(dims, dict):
        raise JsonStatError(f"not a JSON-stat dataset: needs 'id', 'size' and 'dimension' (keys: {sorted(doc)[:12]})")
    if len(ids) != len(sizes) or not all(isinstance(s, int) and not isinstance(s, bool) and s >= 0 for s in sizes):
        raise JsonStatError(f"JSON-stat 'id' {ids} and 'size' {sizes} do not match")
    ids = [str(i) for i in ids]
    categories: dict[str, list[str]] = {}
    labels: dict[str, dict[str, str]] = {}
    for dim_id, size in zip(ids, sizes, strict=True):
        if dim_id not in dims:
            raise JsonStatError(f"JSON-stat dimension {dim_id!r} listed in 'id' but not described")
        categories[dim_id], labels[dim_id] = _category_codes(dim_id, dims[dim_id], size)

    total = math.prod(sizes)
    strides = [math.prod(sizes[k + 1:]) for k in range(len(sizes))]
    raw = doc.get("value")
    if isinstance(raw, dict):
        try:
            items = [(int(k), v) for k, v in raw.items()]
        except (TypeError, ValueError) as exc:
            raise JsonStatError(f"JSON-stat sparse 'value' has a non-integer key: {exc}") from exc
    elif isinstance(raw, list):
        if len(raw) != total:
            raise JsonStatError(f"JSON-stat dense 'value' has {len(raw)} entries, expected {total}")
        items = list(enumerate(raw))
    elif raw is None:
        items = []
    else:
        raise JsonStatError("JSON-stat 'value' must be an object or a list")
    status_of = _status_getter(doc.get("status"), total)

    cells: list[JsonStatCell] = []
    for flat, v in sorted(items, key=lambda kv: kv[0]):
        if v is None:
            continue
        if not 0 <= flat < total:
            raise JsonStatError(f"JSON-stat value index {flat} outside the cube (size {total})")
        coords, rem = {}, flat
        for dim_id, stride in zip(ids, strides, strict=True):
            pos, rem = divmod(rem, stride)
            coords[dim_id] = categories[dim_id][pos]
        cells.append(JsonStatCell(coords=coords, value=v, status=status_of(flat)))
    ext = doc.get("extension") if isinstance(doc.get("extension"), dict) else {}
    return JsonStatDataset(ids=ids, sizes=list(sizes), categories=categories, labels=labels, cells=cells,
                           updated=doc.get("updated"), extension=ext)


# ===========================================================================
# 2) Eurostat Comext DS-045409
# ===========================================================================

COMEXT_DATASET = "DS-045409"
COMEXT_URL = f"https://ec.europa.eu/eurostat/api/comext/dissemination/statistics/1.0/data/{COMEXT_DATASET}"
HONEY_CN8 = "04090000"
COMEXT_REPORTERS = ["EU27_2020", "IT", "DE", "ES", "BE", "FR", "PL", "PT", "NL"]
# Main origins (Serbia is XS in Comext) plus the extra-EU aggregate and the world total.
COMEXT_PARTNERS = [
    "CN", "UA", "AR", "XS", "BR", "VN", "IN", "MX", "TR", "MD", "UY", "CL", "TH", "CU", "NZ",
    "GT", "SV", "NI", "US", "CA", "EXT_EU27_2020", "WORLD",
]
COMEXT_VALUE = "VALUE_IN_EUROS"
COMEXT_QTY = "QUANTITY_IN_100KG"
COMEXT_DIMS = ("freq", "reporter", "partner", "product", "flow", "indicators", "time")
COMEXT_BACKFILL_MONTHS = 60     # first run (or force): five years of monthly history
COMEXT_REPULL_MONTHS = 24       # on every new release: preliminary months get revised
COMEXT_PROBE_MONTHS = 3         # the cheap "has a new vintage been published?" request

_PERIOD_RE = re.compile(r"^(\d{4})-?M?(\d{2})$")


@dataclass
class ComextRecord:
    reporter: str               # Comext code, e.g. "EU27_2020", "IT"
    partner: str                # Comext code, e.g. "XS", "EXT_EU27_2020"
    flow: str                   # "1" import, "2" export
    period: str                 # "YYYY-MM"
    year: int
    month: int
    value_eur: float | None
    quantity_100kg: float | None
    flags: dict[str, str] = field(default_factory=dict)
    reporter_label: str = ""
    partner_label: str = ""


@dataclass
class ComextRelease:
    updated_raw: str
    updated: datetime
    records: list[ComextRecord]
    dropped_periods: list[str]
    problems: list[str]


def _comext_updated(doc: dict) -> tuple[str, datetime]:
    raw = doc.get("updated")
    if not raw:
        for ann in (doc.get("extension") or {}).get("annotation") or []:
            if isinstance(ann, dict) and ann.get("type") == "UPDATE_DATA" and ann.get("date"):
                raw = ann["date"]
                break
    if not raw:
        raise CollectorError("Eurostat Comext response has no 'updated' timestamp (schema drift); nothing stored")
    try:
        return str(raw), isoparse(str(raw))
    except (ValueError, OverflowError) as exc:
        raise CollectorError(f"Eurostat Comext 'updated' value {raw!r} is not a timestamp") from exc


def _comext_doc(content: bytes) -> dict:
    doc = _load_json(content, "Eurostat Comext")
    if not isinstance(doc, dict):
        raise CollectorError("Eurostat Comext: expected a JSON object")
    if "error" in doc:
        err = doc["error"]
        label = err.get("label") if isinstance(err, dict) else err
        raise CollectorError(f"Eurostat Comext error: {label}")
    if "warning" in doc and "value" not in doc:
        w = doc["warning"]
        raise CollectorError(f"Eurostat Comext asynchronous/oversize reply: {w.get('label') if isinstance(w, dict) else w}")
    return doc


def parse_comext_updated(content: bytes) -> str:
    """Only the vintage ('updated') of a Comext response; used by the cheap daily check."""
    return _comext_updated(_comext_doc(content))[0]


def parse_comext(content: bytes) -> ComextRelease:
    """Parse a DS-045409 JSON-stat response into one record per reporter x partner x flow x month.

    Fails loudly on schema drift (a missing dimension or indicator, no vintage). Months the
    publisher lists as having no data, and months after the vintage date, are dropped, never
    zero-filled. Only CN 04090000 at monthly frequency is kept.
    """
    doc = _comext_doc(content)
    updated_raw, updated = _comext_updated(doc)
    missing_dims = [d for d in COMEXT_DIMS if d not in (doc.get("id") or [])]
    if missing_dims:
        raise CollectorError(f"Eurostat Comext schema drift: dimension(s) {missing_dims} missing "
                             f"(got {doc.get('id')}); nothing stored")
    ds = decode_jsonstat(doc)
    for ind in (COMEXT_VALUE, COMEXT_QTY):
        if ind not in ds.categories["indicators"]:
            raise CollectorError(f"Eurostat Comext schema drift: indicator {ind} missing "
                                 f"(got {ds.categories['indicators']}); nothing stored")
    if HONEY_CN8 not in ds.categories["product"]:
        raise CollectorError(f"Eurostat Comext: product {HONEY_CN8} missing from the response "
                             f"(got {ds.categories['product'][:5]}); nothing stored")

    no_data = ds.no_data_codes("time")
    newest_allowed = (updated.year, updated.month)
    groups: dict[tuple, dict[str, tuple[Any, str | None]]] = defaultdict(dict)
    for cell in ds.cells:
        c = cell.coords
        if c["freq"] != "M" or c["product"] != HONEY_CN8:
            continue
        key = (c["reporter"], c["partner"], c["flow"], c["time"])
        groups[key][c["indicators"]] = (cell.value, cell.status)

    problems: list[str] = []
    dropped: set[str] = set(no_data)
    records: list[ComextRecord] = []
    periods_ok = 0
    for (reporter, partner, flow, period), inds in sorted(groups.items()):
        m = _PERIOD_RE.match(period)
        if not m or not 1 <= int(m.group(2)) <= 12:
            problems.append(f"Comext: unrecognised period {period!r} for {reporter}/{partner}; skipped")
            continue
        periods_ok += 1
        year, month = int(m.group(1)), int(m.group(2))
        if period in no_data or (year, month) > newest_allowed:
            dropped.add(period)       # empty or future month: never stored, never zero-filled
            continue
        if flow not in ("1", "2"):
            continue
        values: dict[str, float | None] = {}
        bad = False
        for ind in (COMEXT_VALUE, COMEXT_QTY):
            if ind not in inds:
                values[ind] = None
                continue
            v = _num(inds[ind][0])
            if v is None or v < 0:
                problems.append(f"Comext: invalid {ind}={inds[ind][0]!r} for {reporter}/{partner}/{flow}/{period}; row skipped")
                bad = True
                break
            values[ind] = v
        if bad or (values[COMEXT_VALUE] is None and values[COMEXT_QTY] is None):
            continue
        flags = {ind: st for ind, (_, st) in inds.items() if st}
        records.append(ComextRecord(
            reporter=reporter, partner=partner, flow=flow, period=f"{year:04d}-{month:02d}", year=year, month=month,
            value_eur=values[COMEXT_VALUE], quantity_100kg=values[COMEXT_QTY], flags=flags,
            reporter_label=ds.labels["reporter"].get(reporter, reporter),
            partner_label=ds.labels["partner"].get(partner, partner),
        ))
    if groups and periods_ok == 0:
        raise CollectorError("Eurostat Comext: no time period could be parsed (format changed?); nothing stored")
    return ComextRelease(updated_raw=updated_raw, updated=updated, records=records,
                         dropped_periods=sorted(dropped), problems=problems)


def comext_data_status(year: int, updated: date, flags: dict[str, str] | None = None) -> DataStatus:
    """Eurostat revises a year's monthly figures until about October of the following year.

    So a month of year Y is 'provisional' in any vintage published before 1 October Y+1 and
    'published' afterwards. A cell flagged 'p' by the publisher is always provisional.
    """
    if flags and any("p" in str(f).lower() for f in flags.values()):
        return DataStatus.PROVISIONAL
    return DataStatus.PROVISIONAL if updated < date(year + 1, 10, 1) else DataStatus.PUBLISHED


def _comext_params(since: str, *, reporters: list[str], partners: list[str], flows: list[str],
                   indicators: list[str]) -> dict:
    return {
        "format": "JSON", "lang": "EN", "freq": "M", "reporter": reporters, "partner": partners,
        "product": HONEY_CN8, "flow": flows, "indicators": indicators, "sinceTimePeriod": since,
    }


def _http_error_label(content: bytes) -> str:
    try:
        doc = json.loads(content)
        err = doc.get("error") if isinstance(doc, dict) else None
        if isinstance(err, dict):
            return str(err.get("label") or err)
        if err:
            return str(err)
    except ValueError:
        pass
    return content[:200].decode("utf-8", errors="replace")


class EurostatComextCollector(Collector):
    key = "eurostat_comext"
    name = "Eurostat Comext: commercio UE di miele (NC 04090000)"
    publisher = "Eurostat (European Commission)"
    homepage = "https://ec.europa.eu/eurostat/web/international-trade-in-goods/database"
    kind = SourceKind.API
    reliability = Reliability.OFFICIAL
    category = "trade"
    language = "en"
    expected_update = "Monthly, around mid-month (data up to about two months earlier)"
    expected_max_age_days = 45
    terms_note = ("Source: Eurostat (DS-045409). Reuse under CC BY 4.0 (Commission Decision 2011/833/EU) "
                  "with attribution. Recent months are preliminary and revised until about October of "
                  "the following year. Unit values are derived (value / net weight), not market quotes.")
    # A cheap vintage check every day (Eurostat publishes at 11:00 CET); the full re-pull of
    # the last 24 months only runs when the 'updated' timestamp has changed.
    schedule = {"trigger": "cron", "hour": 13, "minute": 20}

    def collect(self, ctx: CollectContext) -> None:
        state = _get_state(ctx.session, self.key)
        if _has_rows(ctx, TradeFlowObservation) and not ctx.force:
            if state.get("updated"):
                probe_updated = self._probe(ctx)
                if isoparse(probe_updated) == isoparse(state["updated"]):
                    log.info("[%s] Comext vintage %s unchanged; nothing to pull", self.key, probe_updated)
                    return
            months = COMEXT_REPULL_MONTHS
        else:
            months = COMEXT_BACKFILL_MONTHS
        t = today()
        sy, sm = _shift_month(t.year, t.month, -(months - 1))
        doc, release = self._pull(ctx, f"{sy:04d}-{sm:02d}")
        self._store(ctx, doc, release)
        _set_state(ctx.session, self.key, {"updated": release.updated_raw, "since": f"{sy:04d}-{sm:02d}",
                                           "pulled_at": utcnow().isoformat(timespec="seconds")})

    def _probe(self, ctx: CollectContext) -> str:
        t = today()
        sy, sm = _shift_month(t.year, t.month, -COMEXT_PROBE_MONTHS)
        params = _comext_params(f"{sy:04d}-{sm:02d}", reporters=["EU27_2020"], partners=["EXT_EU27_2020"],
                                flows=["1"], indicators=[COMEXT_VALUE])
        doc = ctx.fetch(COMEXT_URL, params=params, headers=JSON_HEADERS, store=False)
        return parse_comext_updated(doc.content)

    def _pull(self, ctx: CollectContext, since: str) -> tuple[FetchResult, ComextRelease]:
        partners = list(COMEXT_PARTNERS)
        while True:
            params = _comext_params(since, reporters=COMEXT_REPORTERS, partners=partners, flows=["1", "2"],
                                    indicators=[COMEXT_VALUE, COMEXT_QTY])
            doc = ctx.fetch(COMEXT_URL, params=params, headers=JSON_HEADERS, accept_status=(200, 400, 404),
                            title=f"Eurostat {COMEXT_DATASET} honey since {since}")
            if doc.status_code == 200:
                return doc, parse_comext(doc.content)
            if "WORLD" in partners:
                # The WORLD aggregate is optional: if the API rejects it, retry without it.
                log.warning("[%s] Comext rejected the request (HTTP %s: %s); retrying without WORLD",
                            self.key, doc.status_code, _http_error_label(doc.content))
                partners.remove("WORLD")
                continue
            raise CollectorError(f"Eurostat Comext answered HTTP {doc.status_code}: {_http_error_label(doc.content)}")

    def _store(self, ctx: CollectContext, doc: FetchResult, release: ComextRelease) -> None:
        published = release.updated.date()
        if release.dropped_periods:
            log.info("[%s] months without data dropped (not zero-filled): %s", self.key, ", ".join(release.dropped_periods))
        by_reporter: dict[str, list[ComextRecord]] = defaultdict(list)
        for rec in release.records:
            by_reporter[rec.reporter].append(rec)
        for reporter_code in sorted(by_reporter):
            reporter = map_geo(reporter_code)
            if reporter is None or reporter in ("EXTRA_EU", "WLD"):
                ctx.warn(f"Comext: unexpected reporter code {reporter_code!r}; its rows were skipped")
                continue
            for rec in by_reporter[reporter_code]:
                partner = map_geo(rec.partner)
                if partner is None:
                    ctx.warn(f"Comext: partner code {rec.partner!r} ({rec.partner_label}) has no mapping; row skipped")
                    continue
                self._store_record(ctx, doc, release, published, rec, reporter, partner)
            ctx.checkpoint()        # one batch per reporter
        for p in release.problems:
            ctx.warn(p)

    def _store_record(self, ctx, doc, release, published, rec: ComextRecord, reporter: str, partner: str) -> None:
        is_import = rec.flow == "1"
        flow = TradeFlow.IMPORT if is_import else TradeFlow.EXPORT
        basis = "CIF" if is_import else "FOB"
        kg = rec.quantity_100kg * 100 if rec.quantity_100kg is not None else None
        status = comext_data_status(rec.year, published, rec.flags)
        p_start, p_end = month_bounds(rec.year, rec.month)
        extra = {"dataset": COMEXT_DATASET, "source_updated": release.updated_raw, "cn8": HONEY_CN8,
                 "reporter_code": rec.reporter, "partner_code": rec.partner, "quantity_100kg": rec.quantity_100kg}
        if rec.flags:
            extra["status_flags"] = rec.flags
        if partner == "WLD":
            extra["note"] = "WORLD includes intra-EU trade (recorded by country of consignment)"
        common = dict(period_start=p_start, period_end=p_end, period_label=rec.period, frequency="M",
                      published_at=published, source_url=doc.url, raw_document_id=doc.raw_document_id,
                      data_status=status)
        ctx.add_trade(
            series_key=f"comext|{reporter}|{partner}|{flow.value}|{rec.period}", hs_code="0409",
            reporter_iso3=reporter, partner_iso3=partner, flow=flow.value, currency="EUR",
            value=rec.value_eur, net_weight_kg=kg, value_basis=basis, extra=extra, **common,
        )
        # Derived unit value. WORLD is excluded: it mixes extra-EU origins with intra-EU
        # consignments (re-dispatched honey), so it is not a price "by origin".
        if partner == "WLD" or not rec.value_eur or kg is None or kg < MIN_UNIT_VALUE_WEIGHT_KG:
            return
        if is_import:
            price_type, origin, market = PriceType.IMPORT_UNIT_VALUE, partner, reporter
            origin_label = rec.partner_label
            note = ("Valore unitario all'importazione = valore CIF / peso netto (Eurostat Comext DS-045409). "
                    "Dato doganale derivato, non una quotazione di mercato.")
        else:
            price_type, origin, market = PriceType.EXPORT_UNIT_VALUE, reporter, partner
            origin_label = rec.reporter_label
            note = ("Valore unitario all'esportazione = valore FOB / peso netto (Eurostat Comext DS-045409). "
                    "Dato doganale derivato, non una quotazione di mercato.")
        ctx.add_price(
            series_key=f"comext|{market}|{origin}|{rec.period}", price_type=price_type,
            variety=Variety.UNSPECIFIED.value, price_value=round(rec.value_eur / kg, 4), currency="EUR", unit="kg",
            origin_iso3=origin, origin_label=origin_label, market_iso3=market, terms=basis, volume_kg=kg,
            notes=note, extra=extra, **common,
        )


# ===========================================================================
# 3) EC Agri-food Data Portal: TAXUD weekly import surveillance, sector "Honey"
# ===========================================================================

TAXUD_BASE = "https://api.tech.ec.europa.eu/agrifood/api/taxud/weeklyData"
TAXUD_SECTORS_URL = f"{TAXUD_BASE}/sectors"
TAXUD_IMPORT_URL = f"{TAXUD_BASE}/import"
TAXUD_OPENAPI_URL = "https://api.tech.ec.europa.eu/agrifood/v3/api-docs"
TAXUD_SECTOR = "Honey"
# Field names third-party clients validate against the live API (research: eu.json).
TAXUD_REQUIRED_FIELDS = ("marketingYear", "week", "memberStateCode", "partnerCode", "cn8ProductCode", "kg", "euroValue")
TAXUD_NOTE = ("Sorveglianza doganale TAXUD (dati settimanali provvisori, soggetti a revisione; "
              "solo importazioni extra-UE). Fonte: Commissione europea, Agri-food Data Portal.")


@dataclass
class TaxudRecord:
    year: int
    week: int
    member_state: str           # code as published (e.g. "DE", "EL")
    reporter_iso3: str
    partner: str                # code as published
    partner_iso3: str
    partner_label: str
    kg: float
    eur: float
    categories: dict[str, dict[str, float]]   # importCategory -> {"kg", "eur"}
    cn8: list[str]
    taric10: list[str]
    rows: int
    marketing_year: str

    @property
    def period_label(self) -> str:
        return f"{self.year:04d}-W{self.week:02d}"

    @property
    def period(self) -> tuple[date, date]:
        return date.fromisocalendar(self.year, self.week, 1), date.fromisocalendar(self.year, self.week, 7)


@dataclass
class TaxudParse:
    records: list[TaxudRecord]
    problems: list[str]
    unmapped_partners: Counter
    other_products: Counter


def parse_taxud_sectors(content: bytes) -> list[str]:
    data = _load_json(content, "TAXUD sectors")
    if isinstance(data, dict) and isinstance(data.get("sectors"), list):
        data = data["sectors"]
    if not isinstance(data, list):
        raise CollectorError(f"TAXUD sectors: expected a JSON list, got {type(data).__name__}")
    names = []
    for item in data:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            n = item.get("name") or item.get("sector") or item.get("sectorName")
            if isinstance(n, str):
                names.append(n)
    if not names:
        raise CollectorError("TAXUD sectors: the list contains no sector names (format changed?)")
    return names


def taxud_openapi_import_params(spec: Any) -> list[str] | None:
    """Parameter names documented for the weeklyData/import path, or None if the path is gone."""
    paths = spec.get("paths") if isinstance(spec, dict) else None
    if not isinstance(paths, dict):
        return None
    for path, ops in paths.items():
        if str(path).rstrip("/").endswith("taxud/weeklyData/import") and isinstance(ops, dict):
            get = ops.get("get") or {}
            return [p.get("name") for p in get.get("parameters") or [] if isinstance(p, dict) and p.get("name")]
    return None


def _taxud_category(row: dict) -> str:
    cat = row.get("importCategory")
    return str(cat).strip() if cat not in (None, "") else "n/d"


def parse_taxud_weekly(content: bytes, sector: str = TAXUD_SECTOR) -> TaxudParse:
    """Parse a weeklyData/import response and aggregate it per member state x origin x ISO week.

    Rows that differ only by import category (preferential / MFN), TARIC code, procedure or
    preference are summed; the split by import category is kept. Exact duplicate rows are
    ignored. Duplicates with conflicting numbers make that week/member state/origin cell
    unusable: it is reported and NOT stored (no guessing). A required field missing from
    every row means the API changed: CollectorError, nothing stored.
    """
    data = _load_json(content, "TAXUD weekly import")
    if not isinstance(data, list):
        raise CollectorError(f"TAXUD weekly import: expected a JSON array, got {type(data).__name__}")
    out = TaxudParse(records=[], problems=[], unmapped_partners=Counter(), other_products=Counter())
    dict_rows = [r for r in data if isinstance(r, dict)]
    if not data:
        return out
    if not dict_rows:
        raise CollectorError("TAXUD weekly import: the array contains no objects (format changed?)")
    present = set().union(*(r.keys() for r in dict_rows))
    missing = [k for k in TAXUD_REQUIRED_FIELDS if k not in present]
    if missing:
        raise CollectorError(f"TAXUD schema drift: field(s) {missing} absent from all {len(dict_rows)} rows "
                             f"(fields present: {sorted(present)}); nothing stored")
    if "sector" in present and not any(str(r.get("sector", "")).lower() == sector.lower() for r in dict_rows):
        raise CollectorError(f"TAXUD ignored the requested sector {sector!r} "
                             f"(got {sorted({str(r.get('sector')) for r in dict_rows})[:5]}); nothing stored")

    cells: dict[tuple, tuple[float, float]] = {}
    meta: dict[tuple, dict] = {}
    conflicts: set[tuple] = set()
    for i, r in enumerate(data):
        if not isinstance(r, dict):
            out.problems.append(f"TAXUD row {i}: not an object; skipped")
            continue
        if "sector" in r and str(r["sector"]).lower() != sector.lower():
            continue
        lacking = [k for k in TAXUD_REQUIRED_FIELDS if r.get(k) in (None, "")]
        if lacking:
            out.problems.append(f"TAXUD row {i}: missing {lacking}; skipped")
            continue
        cn8 = str(r["cn8ProductCode"]).strip()
        if not cn8.startswith("0409"):
            out.other_products[cn8] += 1
            continue
        my = str(r["marketingYear"]).strip()
        week = _int(r["week"])
        if not re.fullmatch(r"\d{4}", my):
            out.problems.append(f"TAXUD row {i}: marketing year {my!r} is not a calendar year; week cannot be dated; skipped")
            continue
        try:
            date.fromisocalendar(int(my), week or 0, 1)
        except ValueError:
            out.problems.append(f"TAXUD row {i}: week {r['week']!r} is not a valid ISO week of {my}; skipped")
            continue
        kg, eur = _num(r["kg"]), _num(r["euroValue"])
        if kg is None or eur is None or kg < 0 or eur < 0:
            out.problems.append(f"TAXUD row {i}: invalid kg={r['kg']!r} / euroValue={r['euroValue']!r}; skipped")
            continue
        ms = str(r["memberStateCode"]).strip().upper()
        ms_iso = map_geo(ms)
        if ms_iso is None or ms_iso in AGGREGATE_CODES:
            out.problems.append(f"TAXUD row {i}: unknown member state code {ms!r}; skipped")
            continue
        pc = str(r["partnerCode"]).strip().upper()
        p_iso = map_geo(pc)
        if p_iso is None or p_iso in AGGREGATE_CODES:
            out.unmapped_partners[pc] += 1
            continue
        category = _taxud_category(r)
        taric = str(r.get("taric10ProductCode") or "").strip()
        agg_key = (int(my), week, ms, pc)
        dim_key = agg_key + (cn8, taric, category, str(r.get("procedure") or ""), str(r.get("preference") or ""))
        if dim_key in cells:
            if cells[dim_key] != (kg, eur):
                conflicts.add(agg_key)
                out.problems.append(f"TAXUD: conflicting duplicate rows for {ms}/{pc} {my}-W{week:02d} "
                                    f"({cells[dim_key][0]:g} kg vs {kg:g} kg); that cell is not stored")
            continue
        cells[dim_key] = (kg, eur)
        meta[dim_key] = {"ms_iso": ms_iso, "p_iso": p_iso, "my": my,
                         "partner_label": str(r.get("partnerName") or r.get("partner") or "")}

    agg: dict[tuple, TaxudRecord] = {}
    for dim_key, (kg, eur) in cells.items():
        agg_key = dim_key[:4]
        if agg_key in conflicts:
            continue
        year, week, ms, pc = agg_key
        cn8, taric, category = dim_key[4], dim_key[5], dim_key[6]
        m = meta[dim_key]
        rec = agg.get(agg_key)
        if rec is None:
            rec = agg[agg_key] = TaxudRecord(
                year=year, week=week, member_state=ms, reporter_iso3=m["ms_iso"], partner=pc,
                partner_iso3=m["p_iso"], partner_label=m["partner_label"] or country_name(m["p_iso"], "en"),
                kg=0.0, eur=0.0, categories={}, cn8=[], taric10=[], rows=0, marketing_year=m["my"],
            )
        rec.kg += kg
        rec.eur += eur
        rec.rows += 1
        split = rec.categories.setdefault(category, {"kg": 0.0, "eur": 0.0})
        split["kg"] += kg
        split["eur"] += eur
        if cn8 not in rec.cn8:
            rec.cn8.append(cn8)
        if taric and taric not in rec.taric10:
            rec.taric10.append(taric)
    out.records = [agg[k] for k in sorted(agg)]
    return out


class TaxudWeeklyCollector(Collector):
    key = "ec_taxud_weekly"
    name = "Commissione europea: importazioni settimanali di miele (sorveglianza TAXUD)"
    publisher = "European Commission, DG AGRI Agri-food Data Portal (TAXUD surveillance data)"
    homepage = "https://agridata.ec.europa.eu/extensions/DashboardTaxud/TaxudWeeklyImport-m.html"
    kind = SourceKind.API
    reliability = Reliability.OFFICIAL
    category = "trade"
    language = "en"
    expected_update = "Weekly (provisional customs surveillance data; extra-EU imports only)"
    expected_max_age_days = 21
    terms_note = ("Source: European Commission, DG AGRI Agri-food Data Portal (TAXUD surveillance data). "
                  "Provisional customs-declaration figures, subject to change without notice; they will "
                  "not match Comext exactly. Free reuse with attribution (Decision 2011/833/EU).")
    schedule = {"trigger": "cron", "day_of_week": "thu", "hour": 10, "minute": 40}

    def collect(self, ctx: CollectContext) -> None:
        sector = self._probe_sectors(ctx)
        first_run = not _has_rows(ctx, TradeFlowObservation)
        if first_run or ctx.force:
            self._probe_openapi(ctx)
        y = today().year
        for year in range(y - (2 if first_run else 1), y + 1):
            doc = ctx.fetch(TAXUD_IMPORT_URL, params={"sectors": sector, "marketingYears": str(year)},
                            headers=JSON_HEADERS, accept_status=(200, 404),
                            title=f"TAXUD weekly honey imports {year}")
            if doc.status_code == 404:          # the API answers 404 "No results found" for empty filters
                log.info("[%s] no TAXUD honey data for %s", self.key, year)
                continue
            if doc.unchanged and not ctx.force:
                continue
            parsed = parse_taxud_weekly(doc.content, sector)
            for p in parsed.problems:
                ctx.warn(p)
            if parsed.unmapped_partners:
                log.info("[%s] partner codes outside the country reference skipped: %s", self.key,
                         dict(parsed.unmapped_partners))
            if parsed.other_products:
                log.info("[%s] non-0409 products in the Honey sector ignored: %s", self.key, dict(parsed.other_products))
            for rec in parsed.records:
                self._store(ctx, doc, sector, rec)
            ctx.checkpoint()

    def _probe_sectors(self, ctx: CollectContext) -> str:
        doc = ctx.fetch(TAXUD_SECTORS_URL, headers=JSON_HEADERS, store=False)
        names = parse_taxud_sectors(doc.content)
        for n in names:
            if n == TAXUD_SECTOR:
                return n
        for n in names:
            if n.strip().lower() == TAXUD_SECTOR.lower():
                return n
        raise CollectorError(f"TAXUD no longer lists a {TAXUD_SECTOR!r} sector (available: {', '.join(names[:40])})")

    def _probe_openapi(self, ctx: CollectContext) -> None:
        """First run: check the published OpenAPI spec still documents our parameters."""
        try:
            doc = ctx.fetch(TAXUD_OPENAPI_URL, headers=JSON_HEADERS, store=False)
            spec = json.loads(doc.content)
        except (CollectorError, ValueError) as exc:
            log.warning("[%s] OpenAPI spec not available (%s); continuing with the documented parameters", self.key, exc)
            return
        params = taxud_openapi_import_params(spec)
        if params is None:
            ctx.warn("TAXUD OpenAPI spec no longer documents the taxud/weeklyData/import path; check the API")
            return
        log.info("[%s] TAXUD weeklyData/import parameters: %s", self.key, params)
        missing = [p for p in ("sectors", "marketingYears") if p not in params]
        if missing:
            ctx.warn(f"TAXUD OpenAPI spec no longer lists parameter(s) {missing} for weeklyData/import")

    def _store(self, ctx: CollectContext, doc: FetchResult, sector: str, rec: TaxudRecord) -> None:
        p_start, p_end = rec.period
        extra = {
            "sector": sector, "marketing_year": rec.marketing_year, "week": rec.week,
            "member_state_code": rec.member_state, "partner_code": rec.partner,
            "import_categories": {k: {"kg": round(v["kg"], 3), "eur": round(v["eur"], 2)} for k, v in sorted(rec.categories.items())},
            "cn8": rec.cn8, "taric10": rec.taric10, "source_rows": rec.rows,
        }
        common = dict(period_start=p_start, period_end=p_end, period_label=rec.period_label, frequency="W",
                      source_url=doc.url, raw_document_id=doc.raw_document_id, data_status=DataStatus.PROVISIONAL,
                      extra=extra)
        ctx.add_trade(
            series_key=f"taxud|{rec.reporter_iso3}|{rec.partner_iso3}|import|{rec.period_label}", hs_code="0409",
            reporter_iso3=rec.reporter_iso3, partner_iso3=rec.partner_iso3, flow=TradeFlow.IMPORT.value,
            currency="EUR", value=rec.eur, net_weight_kg=rec.kg, value_basis="CIF", notes=TAXUD_NOTE, **common,
        )
        if rec.kg < MIN_UNIT_VALUE_WEIGHT_KG or rec.eur <= 0:
            return
        ctx.add_price(
            series_key=f"taxud|{rec.reporter_iso3}|{rec.partner_iso3}|{rec.period_label}",
            price_type=PriceType.IMPORT_UNIT_VALUE, variety=Variety.UNSPECIFIED.value,
            price_value=round(rec.eur / rec.kg, 4), currency="EUR", unit="kg", origin_iso3=rec.partner_iso3,
            origin_label=rec.partner_label, market_iso3=rec.reporter_iso3, terms="CIF", volume_kg=rec.kg,
            notes="Valore unitario settimanale = valore / peso netto. " + TAXUD_NOTE, **common,
        )


# ===========================================================================
# 4) DG AGRI honey page: market overview / presentation PDFs
# ===========================================================================

HONEY_PAGE_URL = "https://agriculture.ec.europa.eu/farming/animal-products/honey_en"
NARRATIVE_PAGES = 4
NARRATIVE_MAX_CHARS = 12_000

_DOC_DOWNLOAD_RE = re.compile(r"/document/download/(?P<uuid>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})_(?P<lang>[a-z]{2})", re.I)
_MARKET_DOC_RE = re.compile(r"market[\s_-]*(overview|presentation|situation|update)|honey[\s_-]*market\b", re.I)
_GENERIC_LINK_RE = re.compile(r"^(download|scarica|t[ée]l[ée]charger|herunterladen|pdf|open|view|read more|[a-z]{2}|"
                              r"\(?\s*\d+([.,]\d+)?\s*[kmg]b\s*(-\s*pdf)?\s*\)?)$", re.I)
_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
           "october", "november", "december"]
_DAY_MONTH_YEAR_RE = re.compile(r"\b(\d{1,2})\s+(" + "|".join(_MONTHS) + r")\s+(\d{4})\b", re.I)
_MONTH_YEAR_RE = re.compile(r"\b(" + "|".join(_MONTHS) + r")\s+(\d{4})\b", re.I)
_SEASON_YEAR_RE = re.compile(r"(spring|summer|autumn|winter)[\s_-]*(\d{4})", re.I)


@dataclass
class HoneyReportLink:
    url: str                    # normalised (prefLang and other noise removed)
    uuid: str
    filename: str
    title: str
    published_at: date | None
    period_label: str | None

    @property
    def report_key(self) -> str:
        return f"{self.uuid}/{self.filename}" if self.filename else self.uuid


def _clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _is_generic(text: str) -> bool:
    """Link text that says nothing about the document ('Download', 'EN', '(1.67 MB - PDF)')."""
    return not text or bool(_GENERIC_LINK_RE.match(text))


def _normalise_doc_url(href: str, base: str) -> tuple[str, str, str] | None:
    """(url, uuid, filename) for an EC '/document/download/' link; prefLang etc. stripped."""
    absu = urljoin(base, href)
    u = urlparse(absu)
    m = _DOC_DOWNLOAD_RE.search(u.path)
    if not m:
        return None
    filename = (parse_qs(u.query).get("filename") or [""])[0]
    url = f"{u.scheme}://{u.netloc}{u.path}" + (f"?filename={filename}" if filename else "")
    return url, m.group("uuid").lower(), filename


def _parse_date_text(text: str) -> date | None:
    m = _DAY_MONTH_YEAR_RE.search(text or "")
    if not m:
        return None
    try:
        return date(int(m.group(3)), _MONTHS.index(m.group(2).lower()) + 1, int(m.group(1)))
    except ValueError:
        return None


def _period_label(*texts: str) -> str | None:
    for t in texts:
        m = _MONTH_YEAR_RE.search(t or "")
        if m:
            return f"{int(m.group(2)):04d}-{_MONTHS.index(m.group(1).lower()) + 1:02d}"
        m = _SEASON_YEAR_RE.search(t or "")
        if m:
            return f"{m.group(2)} {m.group(1).lower()}"
    return None


def _title_from_filename(filename: str) -> str:
    """'market-presentation-honey_autumn2024_en.pdf' -> 'Market presentation honey autumn2024' ('' if none)."""
    stem = re.sub(r"(_[a-z]{2})?\.pdf$", "", filename or "", flags=re.I)
    words = _clean_text(re.sub(r"[-_]+", " ", stem))
    return words[:1].upper() + words[1:]


def find_honey_reports(html: str, page_url: str = HONEY_PAGE_URL) -> list[HoneyReportLink]:
    """Find 'Honey market overview / presentation' PDF links on the DG AGRI honey page.

    The page uses Europa Component Library blocks in which the link text is often just
    "Download": the title and the date are taken from the smallest enclosing block that
    contains that one document (class '*__title', <time datetime>, or '29 January 2026').
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    found: dict[str, HoneyReportLink] = {}
    for a in soup.find_all("a", href=True):
        norm = _normalise_doc_url(a["href"], page_url)
        if norm is None:
            continue
        url, uuid, filename = norm
        if filename and not filename.lower().endswith(".pdf"):
            continue
        raw_text = _clean_text(a.get_text(" "))
        link_text = re.sub(r"^(download|scarica)\b[\s:-]*", "", raw_text, flags=re.I)
        if _is_generic(link_text):
            link_text = _clean_text(a.get("title") or a.get("aria-label") or "")
        block_title, block = _enclosing_block(a, page_url, url)
        # Inline links usually carry the title themselves; ECL file blocks say "Download"
        # and keep the title in a '*__title' element of the block.
        title = (link_text if not _is_generic(link_text) else None) or block_title or _title_from_filename(filename)
        if not title:
            continue                    # nothing tells us what this document is: do not guess
        context = f"{title} {filename}"
        if "honey" not in context.lower() or not _MARKET_DOC_RE.search(context):
            continue
        # The date is read only inside a block that holds this one document (never from a
        # paragraph that also links other files), or from the link text itself.
        published = _parse_date_text(raw_text)
        scope = block
        if scope is not None and published is None:
            t = scope.find("time")
            if t is not None and t.get("datetime"):
                try:
                    published = isoparse(t["datetime"]).date()
                except (ValueError, OverflowError):
                    published = None
            if published is None:
                published = _parse_date_text(scope.get_text(" "))
        link = HoneyReportLink(url=url, uuid=uuid, filename=filename, title=title[:500], published_at=published,
                               period_label=_period_label(title, filename))
        prev = found.get(url)
        if prev is None or (len(link.title) > len(prev.title)) or (prev.published_at is None and published):
            found[url] = link
    return sorted(found.values(), key=lambda r: (r.published_at or date.min, r.url))


def _enclosing_block(a, page_url: str, url: str):
    """(title, block) for the link's document.

    `block` is the largest ancestor (up to 6 levels, stopping at the first '*__title') that
    holds this document and no other one; None when even the direct parent links other
    documents. `title` is the text of a '*__title' element inside that block, if any.
    """
    node, block = a, None
    for _ in range(6):
        node = node.parent
        if node is None or node.name in ("body", "html", "main"):
            break
        others = {n[0] for n in (_normalise_doc_url(x["href"], page_url) for x in node.find_all("a", href=True)) if n}
        if others - {url}:
            break                      # this ancestor holds several documents: do not look further
        block = node
        title_el = node.find(class_=re.compile(r"(__|-)title\b"))
        if title_el is not None:
            t = _clean_text(title_el.get_text(" "))
            if not _is_generic(t):
                return t, node
    return None, block


def extract_pdf_narrative(content: bytes, max_pages: int = NARRATIVE_PAGES) -> str | None:
    """Text of the first pages, verbatim (whitespace tidied). None if there is no text layer."""
    import pdfplumber

    parts = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages[:max_pages]:
            text = page.extract_text() or ""
            lines = [_clean_text(line) for line in text.splitlines()]
            text = "\n".join(line for line in lines if line)
            if text:
                parts.append(text)
    narrative = "\n\n".join(parts).strip()
    if not narrative:
        return None
    return narrative[:NARRATIVE_MAX_CHARS]


@dataclass
class PdfPriceRow:
    price_type: PriceType
    market_iso3: str
    origin_iso3: str
    origin_label: str
    variety: str
    year: int
    value: float
    page: int


_PRICE_UNIT_RE = re.compile(r"(?:eur|€)\s*/\s*kg", re.I)
_OTHER_UNIT_RE = re.compile(r"(?:eur|€)\s*/\s*(?:100\s*kg|t\b|tonne|lb)", re.I)
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")
_PRICE_CELL_RE = re.compile(r"^\d{1,3}(?:[.,]\d{1,3})?$")
_EMPTY_CELL = {"", "-", "–", "—", ":", "n.a.", "n/a", "na", "n.d."}
_ROW_HEADERS = {"member state", "member states", "ms", "country", "origin", "country of origin"}


def _classify_price_page(text: str) -> tuple[PriceType, str] | None:
    """The single price type a page is about, or None when it is absent or ambiguous."""
    t = text.lower()
    kinds = []
    if "import" in t and ("unit value" in t or "import price" in t):
        kinds.append((PriceType.IMPORT_UNIT_VALUE, "import"))
    if "production site" in t or "producer price" in t or "farm-gate" in t or "farm gate" in t:
        kinds.append((PriceType.PRODUCER, "producer"))
    if "bulk" in t and "wholesal" in t:
        kinds.append((PriceType.WHOLESALE_BULK, "bulk"))
    return kinds[0] if len(kinds) == 1 else None


def _parse_price_table(table: list[list[Any]]) -> list[tuple[str, str, int, float]] | None:
    """[(row label, iso3, year, value)] if the table is unambiguous, else None.

    Unambiguous means: header 'Member State'/'Origin'/'Country' followed only by distinct
    year columns; every row label is a known country (or the EU); every non-empty cell is
    a plain number. One odd cell rejects the whole table.
    """
    if not table or len(table) < 2:
        return None
    header = [_clean_text(str(c or "")) for c in table[0]]
    if header[0].lower() not in _ROW_HEADERS or len(header) < 2:
        return None
    years = header[1:]
    if not all(_YEAR_RE.match(y) for y in years) or len(set(years)) != len(years):
        return None
    out = []
    for row in table[1:]:
        cells = [_clean_text(str(c or "")) for c in row]
        if len(cells) != len(header):
            return None
        label = cells[0]
        if label.upper() in ("EU", "EU-27", "EU27", "EU 27") or label.lower() in ("eu average", "eu-27 average"):
            iso = "EU27"
        else:
            iso = lookup_iso3(label)
        if iso is None or iso in ("EXTRA_EU", "WLD"):
            return None
        for y, cell in zip(years, cells[1:], strict=True):
            if cell.lower() in _EMPTY_CELL:
                continue
            if not _PRICE_CELL_RE.match(cell):
                return None
            out.append((label, iso, int(y), float(cell.replace(",", "."))))
    return out or None


def extract_price_tables(content: bytes) -> list[PdfPriceRow]:
    """Prices from clearly structured tables only (see `_parse_price_table`).

    The page must name exactly one price type and exactly one unit (EUR/kg). Anything else
    (charts, free text, mixed tables) is ignored: the report is kept, no number is guessed.
    """
    import pdfplumber

    rows: list[PdfPriceRow] = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page_no, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""
            kind = _classify_price_page(text)
            if kind is None or not _PRICE_UNIT_RE.search(text) or _OTHER_UNIT_RE.search(text):
                continue
            price_type, _ = kind
            variety = Variety.POLYFLORA.value if re.search(r"multi-?floral|poly-?floral|millefiori", text, re.I) \
                else Variety.UNSPECIFIED.value
            tables = page.extract_tables() or []
            if len(tables) != 1:
                continue            # several tables on one page: we cannot tell which is which
            parsed = _parse_price_table(tables[0])
            if not parsed:
                continue
            for label, iso, year, value in parsed:
                if price_type == PriceType.IMPORT_UNIT_VALUE:
                    market, origin = "EU27", iso
                else:
                    market = origin = iso
                rows.append(PdfPriceRow(price_type=price_type, market_iso3=market, origin_iso3=origin,
                                        origin_label=label, variety=variety, year=year, value=value, page=page_no))
    return rows


class EcHoneyMarketCollector(Collector):
    key = "ec_honey_market"
    name = "Commissione europea (DG AGRI): presentazioni sul mercato del miele"
    publisher = "European Commission, DG Agriculture and Rural Development"
    homepage = HONEY_PAGE_URL
    kind = SourceKind.PDF
    reliability = Reliability.OFFICIAL
    category = "reports"
    language = "en"
    expected_update = "Irregular, about twice a year (spring/autumn honey market presentations)"
    expected_max_age_days = 400
    terms_note = ("Commission website content, reusable with attribution under Decision 2011/833/EU unless a "
                  "document says otherwise. Charts may embed third-party data (FAO, Eurostat).")
    schedule = {"trigger": "cron", "day_of_week": "mon", "hour": 9, "minute": 25}

    def collect(self, ctx: CollectContext) -> None:
        # The page is always re-parsed (cheap): documents already registered are skipped
        # without downloading, so a PDF that failed last time is simply retried.
        page = ctx.fetch(HONEY_PAGE_URL, title="DG AGRI honey page")
        links = find_honey_reports(page.text, page.url)
        if not links:
            ctx.warn("No 'honey market overview/presentation' PDF found on the DG AGRI honey page; "
                     "the page layout may have changed")
            return
        for link in links:
            self._process(ctx, link)
            ctx.checkpoint()

    def _process(self, ctx: CollectContext, link: HoneyReportLink) -> None:
        key = link.report_key
        existing = ctx.session.scalars(
            select(Report).where(Report.source_id == ctx.source.id, Report.report_key == key)
        ).first()
        if existing is not None and not ctx.force:
            ctx.counters.count("unchanged")
            return
        pdf = ctx.fetch(link.url, title=link.title, published_at=link.published_at)
        if not pdf.content.startswith(b"%PDF"):
            ctx.warn(f"DG AGRI document {link.url} is not a PDF (content-type {pdf.content_type}); skipped")
            return
        if existing is not None:
            if pdf.unchanged:
                ctx.counters.count("unchanged")
                return
            # Same link, new bytes: the Commission replaced the file in place. Keep both
            # versions, told apart by the sha256 of the new file.
            key = f"{key}#{hashlib.sha256(pdf.content).hexdigest()[:12]}"
        narrative = None
        try:
            narrative = extract_pdf_narrative(pdf.content)
        except Exception as exc:  # noqa: BLE001 - pdfminer raises many exception types
            ctx.warn(f"DG AGRI PDF {link.filename or link.url}: text extraction failed ({type(exc).__name__}: {exc})")
        report, is_new = ctx.add_report(report_key=key, title=link.title, url=link.url, published_at=link.published_at,
                                        period_label=link.period_label, raw_document_id=pdf.raw_document_id,
                                        narrative=narrative)
        if not is_new:
            return
        try:
            rows = extract_price_tables(pdf.content)
        except Exception as exc:  # noqa: BLE001
            ctx.warn(f"DG AGRI PDF {link.filename or link.url}: table extraction failed ({type(exc).__name__}: {exc})")
            return
        for r in rows:
            p_start, p_end = year_bounds(r.year)
            ctx.add_price(
                series_key=f"dgagri|{r.market_iso3}|{r.origin_iso3}|{r.variety}|{r.year}", price_type=r.price_type,
                variety=r.variety, price_value=r.value, currency="EUR", unit="kg", period_start=p_start,
                period_end=p_end, period_label=str(r.year), frequency="A", origin_iso3=r.origin_iso3,
                origin_label=r.origin_label, market_iso3=r.market_iso3, published_at=link.published_at,
                source_url=link.url, raw_document_id=pdf.raw_document_id, data_status=DataStatus.PUBLISHED,
                terms="bulk" if r.price_type == PriceType.WHOLESALE_BULK else None,
                notes=f"Tabella del documento DG AGRI \"{link.title}\", pagina {r.page}.",
                extra={"report_key": key, "page": r.page},
            )


# ===========================================================================
# 5) RASFF Window: honey food-safety notifications (undocumented JSON backend)
# ===========================================================================

RASFF_BASE = "https://webgate.ec.europa.eu/rasff-window/backend/public"
RASFF_SEARCH_URL = f"{RASFF_BASE}/notification/search/consolidated/en/"
RASFF_SCREEN_URL = "https://webgate.ec.europa.eu/rasff-window/screen/notification/{notif_id}"
RASFF_HONEY_CATEGORY_ID = 18451                 # "honey and royal jelly" (live dictionary, 2026-10-25)
RASFF_PAGE_SIZE = 50                            # the backend rejects 100 and above
RASFF_MAX_PAGES = 40
RASFF_LOOKBACK_DAYS = 30
RASFF_BACKFILL_FROM = date(2020, 1, 1)          # RASFF Window search covers 2020 onwards
RASFF_MIN_INTERVAL = 3.0                        # seconds between calls (rate limit is enforced)
RASFF_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://webgate.ec.europa.eu",
    "Referer": "https://webgate.ec.europa.eu/rasff-window/screen/list",
    "X-Requested-With": "XMLHttpRequest",
}
RASFF_REQUIRED_FIELDS = ("notifId", "reference", "subject", "ecValidationDate")
# Category 18451 also covers royal jelly, pollen and propolis: keep honey only.
_HONEY_SUBJECT_RE = re.compile(r"honey|\bmiel\b|\bmiele\b|honig|manuka", re.I)


@dataclass
class RasffNotification:
    notif_id: int
    reference: str
    subject: str
    validated_at: date | None
    origin_iso3: list[str]
    origin_names: list[str]
    notifying: str | None
    classification: str | None
    risk: str | None
    product_category: str | None
    product_type: str | None

    @property
    def url(self) -> str:
        return RASFF_SCREEN_URL.format(notif_id=self.notif_id)

    @property
    def status(self) -> str | None:
        """Compact 'classification / risk decision' (column is 40 characters)."""
        cls = _clean_text(re.sub(r"\bnotification\b", " ", self.classification or "", flags=re.I))
        cls = re.sub(r"^information for\s+(attention|follow-up)$", r"info (\1)", cls, flags=re.I)
        s = " / ".join(p for p in (cls, _clean_text(self.risk or "")) if p)
        return s[:40] or None

    def summary(self) -> str:
        parts = [f"RASFF notification {self.reference}."]
        if self.classification:
            parts.append(f"Classification: {self.classification}.")
        if self.risk:
            parts.append(f"Risk decision: {self.risk}.")
        if self.notifying:
            parts.append(f"Notified by: {self.notifying}.")
        if self.origin_names:
            parts.append(f"Origin: {', '.join(self.origin_names)}.")
        if self.product_category:
            parts.append(f"Product category: {self.product_category}.")
        return " ".join(parts)


@dataclass
class RasffPage:
    total_pages: int
    total_elements: int | None
    notifications: list[RasffNotification]
    problems: list[str]
    categories: list[str]       # product category descriptions seen (contract check)


def _desc(obj: Any) -> str | None:
    if isinstance(obj, dict):
        v = obj.get("description") or obj.get("organizationName") or obj.get("name")
        return _clean_text(str(v)) if v else None
    return _clean_text(obj) if isinstance(obj, str) and obj.strip() else None


def _rasff_date(value: Any) -> date | None:
    """RASFF dates are 'dd-mm-yyyy HH:MM:SS' (Brussels time, no zone), never ISO."""
    try:
        return datetime.strptime(str(value).strip()[:10], "%d-%m-%Y").date()
    except ValueError:
        return None


def parse_rasff_search(content: bytes) -> RasffPage:
    """Parse one page of the consolidated search. Unexpected shape -> CollectorError."""
    doc = _load_json(content, "RASFF search")
    if not isinstance(doc, dict) or not isinstance(doc.get("notifications"), list):
        keys = sorted(doc)[:12] if isinstance(doc, dict) else type(doc).__name__
        raise CollectorError(f"RASFF response shape changed: expected an object with a 'notifications' list (got {keys})")
    total_pages = _int(doc.get("totalPages"))
    if total_pages is None or total_pages < 0:
        raise CollectorError(f"RASFF response shape changed: 'totalPages' missing or invalid ({doc.get('totalPages')!r})")
    items = doc["notifications"]
    page = RasffPage(total_pages=total_pages, total_elements=_int(doc.get("totalElements")),
                     notifications=[], problems=[], categories=[])
    dict_items = [it for it in items if isinstance(it, dict)]
    if items and not dict_items:
        raise CollectorError("RASFF response shape changed: notifications are not objects")
    if dict_items:
        present = set().union(*(it.keys() for it in dict_items))
        missing = [k for k in RASFF_REQUIRED_FIELDS if k not in present]
        if missing:
            raise CollectorError(f"RASFF response shape changed: field(s) {missing} absent from every notification "
                                 f"(fields present: {sorted(present)})")
    dated = 0
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            page.problems.append(f"RASFF item {i}: not an object; skipped")
            continue
        nid, ref, subject = _int(it.get("notifId")), _clean_text(str(it.get("reference") or "")), _clean_text(str(it.get("subject") or ""))
        if nid is None or not ref or not subject:
            page.problems.append(f"RASFF item {i}: missing notifId/reference/subject; skipped")
            continue
        validated = _rasff_date(it.get("ecValidationDate"))
        if validated is None:
            page.problems.append(f"RASFF {ref}: unreadable ecValidationDate {it.get('ecValidationDate')!r}")
        else:
            dated += 1
        origins = it.get("originCountries") or []
        origins = origins if isinstance(origins, list) else [origins]
        iso3, names = [], []
        for o in origins:
            code = o.get("isoCode") if isinstance(o, dict) else None
            mapped = map_geo(code)
            if mapped and mapped not in AGGREGATE_CODES and mapped not in iso3:
                iso3.append(mapped)
            name = _desc(o) or (str(code) if code else None)
            if name and name not in names:
                names.append(name)
        notifying = it.get("notifyingCountry")
        cat = _desc(it.get("productCategory"))
        if cat:
            page.categories.append(cat)
        page.notifications.append(RasffNotification(
            notif_id=nid, reference=ref, subject=subject, validated_at=validated, origin_iso3=iso3,
            origin_names=names, notifying=_desc(notifying) or (notifying.get("isoCode") if isinstance(notifying, dict) else None),
            classification=_desc(it.get("notificationClassification")), risk=_desc(it.get("riskDecision")),
            product_category=cat, product_type=_desc(it.get("productType")),
        ))
    if page.notifications and dated == 0:
        raise CollectorError("RASFF response shape changed: no ecValidationDate could be read (expected dd-mm-yyyy)")
    return page


def _rasff_body(page: int, date_from: date | None) -> dict:
    body: dict[str, Any] = {"parameters": {"pageNumber": page, "itemsPerPage": RASFF_PAGE_SIZE},
                            "productCategory": [RASFF_HONEY_CATEGORY_ID]}
    if date_from is not None:
        body["ecValidDateFrom"] = f"{date_from:%d-%m-%Y} 00:00:00"
    return body


class RasffHoneyCollector(Collector):
    key = "rasff_honey"
    name = "RASFF: notifiche di sicurezza alimentare sul miele"
    publisher = "European Commission, RASFF Window"
    homepage = "https://webgate.ec.europa.eu/rasff-window/screen/search"
    kind = SourceKind.API
    reliability = Reliability.OFFICIAL
    category = "regulation"
    language = "en"
    expected_update = "Daily (notifications validated on working days); honey notifications are irregular"
    expected_max_age_days = 120
    terms_note = ("Source: European Commission, RASFF Window. Public information reusable under Decision "
                  "2011/833/EU. The JSON backend is NOT an officially documented API and may change without "
                  "notice; brands and operators are omitted by design.")
    schedule = {"trigger": "cron", "hour": 8, "minute": 35}

    def collect(self, ctx: CollectContext) -> None:
        ctx.MIN_INTERVAL_PER_HOST = max(ctx.MIN_INTERVAL_PER_HOST, RASFF_MIN_INTERVAL)
        known = set(ctx.session.scalars(select(RegulationItem.reference).where(RegulationItem.source_id == ctx.source.id)))
        incremental = bool(known) and not ctx.force
        date_from: date | None = today() - timedelta(days=RASFF_LOOKBACK_DAYS) if incremental else RASFF_BACKFILL_FROM
        page_no = 1
        while page_no <= RASFF_MAX_PAGES:
            doc, date_from = self._search(ctx, page_no, date_from)
            page = parse_rasff_search(doc.content)
            for p in page.problems:
                ctx.warn(p)
            if page.categories and not any("honey" in c.lower() for c in page.categories):
                raise CollectorError(f"RASFF category filter {RASFF_HONEY_CATEGORY_ID} no longer returns honey "
                                     f"(got categories {sorted(set(page.categories))[:5]}); nothing stored")
            page_has_new = False
            for n in page.notifications:
                if not _HONEY_SUBJECT_RE.search(n.subject):
                    continue        # royal jelly, pollen, propolis ...
                page_has_new |= n.reference not in known
                ctx.add_regulation(
                    reference=n.reference, jurisdiction="EU", doc_type="food_safety_notification", title=n.subject,
                    url=n.url, published_at=n.validated_at, countries=n.origin_iso3 or None, status=n.status,
                    summary_en=n.summary(),
                )
            ctx.checkpoint()
            if page_no >= page.total_pages or not page.notifications:
                break
            if incremental and not page_has_new:
                break               # newest first: the rest is already stored
            page_no += 1

    def _search(self, ctx: CollectContext, page_no: int, date_from: date | None) -> tuple[FetchResult, date | None]:
        """One search page. Returns the response and the date filter actually used."""
        retried_body = False
        while True:
            doc = ctx.fetch(RASFF_SEARCH_URL, method="POST", json_body=_rasff_body(page_no, date_from),
                            headers=RASFF_HEADERS, accept_status=(200, 400), title=f"RASFF honey search p{page_no}")
            if doc.status_code == 400 and date_from is not None:
                # Combining productCategory with ecValidDateFrom is unverified: fall back to
                # the category filter alone (results are newest first, paging stops early).
                log.warning("[%s] RASFF rejected the date filter (%s); retrying without it",
                            self.key, _http_error_label(doc.content))
                date_from = None
                continue
            if doc.status_code != 200:
                raise CollectorError(f"RASFF search answered HTTP {doc.status_code}: {_http_error_label(doc.content)}")
            try:
                json.loads(doc.content)
            except ValueError:
                if not retried_body:    # an occasional 200 with an empty / non-JSON body: retry once
                    retried_body = True
                    log.warning("[%s] RASFF returned a non-JSON body; retrying once", self.key)
                    continue
            return doc, date_from       # a second bad body is reported by parse_rasff_search


__all__ = [
    "decode_jsonstat", "parse_comext", "parse_comext_updated", "comext_data_status", "map_geo",
    "parse_taxud_sectors", "parse_taxud_weekly", "taxud_openapi_import_params", "find_honey_reports",
    "extract_pdf_narrative", "extract_price_tables", "parse_rasff_search",
    "EurostatComextCollector", "TaxudWeeklyCollector", "EcHoneyMarketCollector", "RasffHoneyCollector",
]
