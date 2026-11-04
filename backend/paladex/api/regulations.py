"""Regulations and duties ("Normative e dazi").

* ``GET /regulations``: official documents (EU legislation, Federal Register, RASFF notifications)
  stored as ``RegulationItem`` rows, with filters, facets and provenance.
* ``GET /regulations/duties``: the current import-duty layers on honey per origin (``TariffMeasure``),
  grouped per origin and jurisdiction (EU, US), with the date each layer was last confirmed, the
  official links, quota fill and, for the US, the anti-dumping case of the origin linked to its
  Federal Register documents (no rates: they are exporter-specific).
* ``GET /regulations/duties/{origin}``: every revision of every layer of one origin (history).

Nothing is computed into a "total duty": layers are shown side by side, as published.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..enums import DataStatus
from ..models import Country, RegulationItem, Source, TariffMeasure
from ..reference.countries import is_known_iso3
from ..services.tariffs import (
    AD_CASE_BY_ORIGIN,
    ALL_ORIGINS,
    ERGA_OMNES,
    GENERAL_ORIGINS,
    TARIFF_ORIGINS,
    US_AD_CASES,
    MeasureType,
    hts_url,
    quota_fill_pct,
    taric_url,
)
from .common import demo_clause, freshness, iso, source_brief, sources_by_id

router = APIRouter(tags=["regulations"])

TARIFF_SOURCES = {"EU": "eu_tariff_xi", "US": "us_hts"}
FR_SOURCE = "us_federal_register"
JURISDICTIONS = ("EU", "US")
TYPE_ORDER = {t.value: i for i, t in enumerate(MeasureType)}
AD_DOCS_LIMIT = 5


def _escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _json_contains(column, code: str):
    """JSON list column contains `code` (an ISO3 validated against the reference table)."""
    return cast(column, String).like(f'%"{code}"%')


def _list_param(value: str | None, upper: bool = False) -> list[str]:
    items = [x.strip() for x in (value or "").split(",") if x.strip()]
    return [x.upper() for x in items] if upper else items


# ---------------------------------------------------------------------------
# Official documents
# ---------------------------------------------------------------------------


def _ad_links(title: str | None) -> list[dict]:
    return [{"origin_iso3": c.origin_iso3, "case_number": c.case_number, "product": c.product}
            for c in US_AD_CASES if c.matches(title)]


def serialize_regulation(r: RegulationItem, src: Source | None) -> dict:
    is_fr = src is not None and src.key == FR_SOURCE
    return {
        "id": r.id,
        "reference": r.reference,
        "jurisdiction": r.jurisdiction,
        "doc_type": r.doc_type,
        "title": r.title,
        "status": r.status,
        "published_at": iso(r.published_at),
        "effective_date": iso(r.effective_date),
        "url": r.url,
        "source_url": r.url,
        "countries": r.countries or [],
        "summary_en": r.summary_en,
        "summary_it": r.summary_it,
        "summary_is_ai": r.summary_is_ai,
        "collected_at": iso(r.collected_at),
        "source": source_brief(src),
        "reliability": src.reliability if src else None,
        "data_status": DataStatus.DEMO.value if r.is_demo else DataStatus.PUBLISHED.value,
        "is_demo": r.is_demo,
        "ad_cases": _ad_links(r.title) if is_fr else [],
    }


def _facets(db: Session) -> dict:
    R = RegulationItem
    juris = db.execute(select(R.jurisdiction, func.count()).where(demo_clause(R, db)).group_by(R.jurisdiction)).all()
    types = db.execute(select(R.doc_type, func.count()).where(demo_clause(R, db)).group_by(R.doc_type)).all()
    countries: dict[str, int] = defaultdict(int)
    for lst in db.scalars(select(R.countries).where(demo_clause(R, db))):
        for c in set(lst or []):
            countries[c] += 1

    def _sorted(pairs) -> list[dict]:
        return [{"key": k, "count": n} for k, n in sorted(pairs, key=lambda kv: (-kv[1], str(kv[0]))) if k]

    return {"jurisdictions": _sorted(juris), "doc_types": _sorted(types), "countries": _sorted(countries.items())}


def _document_sources(db: Session) -> list[dict]:
    """Sources that write official documents (category 'regulation', tariff collectors excluded)."""
    rows = db.scalars(select(Source).where(Source.category == "regulation", Source.key.not_in(TARIFF_SOURCES.values()))
                      .order_by(Source.name)).all()
    return [{**source_brief(s), "enabled": s.enabled, "last_run_at": iso(s.last_run_at),
             "last_run_status": s.last_run_status, "last_success_at": iso(s.last_success_at),
             "latest_published_at": iso(s.latest_published_at), "freshness": freshness(s)} for s in rows]


@router.get("/regulations")
def list_regulations(
    jurisdiction: str | None = Query(None, description="EU, US, IT ... (comma-separated)"),
    doc_type: str | None = Query(None, description="regulation, antidumping, food_safety_notification ... (comma-separated)"),
    country: str | None = Query(None, description="ISO3 of a country named in the document"),
    q: str | None = Query(None, max_length=200, description="text in title, reference or summary"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    R = RegulationItem
    stmt = select(R).where(demo_clause(R, db))
    juris = _list_param(jurisdiction, upper=True)
    if juris:
        stmt = stmt.where(R.jurisdiction.in_(juris))
    types = _list_param(doc_type)
    if types:
        stmt = stmt.where(R.doc_type.in_(types))
    iso3 = (country or "").strip().upper() or None
    if iso3:
        if not is_known_iso3(iso3):
            raise HTTPException(400, f"Unknown country code {country!r}")
        stmt = stmt.where(_json_contains(R.countries, iso3))
    if q and q.strip():
        pat = f"%{_escape_like(q.strip())}%"
        stmt = stmt.where(or_(R.title.ilike(pat, escape="\\"), R.reference.ilike(pat, escape="\\"),
                              R.summary_en.ilike(pat, escape="\\"), R.summary_it.ilike(pat, escape="\\")))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(R.published_at.desc().nulls_last(), R.collected_at.desc(), R.id.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    srcs = sources_by_id(db)
    last = db.scalar(select(func.max(R.collected_at)).where(demo_clause(R, db)))
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
        "items": [serialize_regulation(r, srcs.get(r.source_id)) for r in rows],
        "facets": _facets(db),
        "sources": _document_sources(db),
        "last_collected_at": iso(last),
    }


# ---------------------------------------------------------------------------
# Duties per origin
# ---------------------------------------------------------------------------


def serialize_measure(m: TariffMeasure, src: Source | None) -> dict:
    extra = m.extra or {}
    quota = None
    if m.quota_order_number:
        q = extra.get("quota") or {}
        quota = {
            "order_number": m.quota_order_number,
            "volume_kg": m.quota_volume_kg,
            "balance_kg": m.quota_balance_kg,
            "status": m.quota_status,
            "fill_pct": quota_fill_pct(m.quota_volume_kg, m.quota_balance_kg),
            "period_start": q.get("period_start"),
            "period_end": q.get("period_end"),
            "last_allocation_date": q.get("last_allocation_date"),
            "critical": q.get("critical"),
            "shared_by_group": q.get("shared_by_group"),
            "note": q.get("note"),
        }
    return {
        "id": m.id,
        "series_key": m.series_key,
        "jurisdiction": m.jurisdiction,
        "origin_iso3": m.origin_iso3,
        "scope": "general" if m.origin_iso3 in GENERAL_ORIGINS else "origin",
        "hs_code": m.hs_code,
        "measure_type": m.measure_type,
        "measure_code": m.measure_code,
        "description": m.description,
        "duty_text": m.duty_text,
        "ad_valorem_pct": m.ad_valorem_pct,
        "specific_amount": m.specific_amount,
        "specific_unit": m.specific_unit,
        "specific_currency": m.specific_currency,
        "quota": quota,
        "valid_from": iso(m.valid_from),
        "valid_to": iso(m.valid_to),
        "legal_reference": m.legal_reference,
        "legal_url": m.legal_url,
        "consult_url": m.consult_url,
        "source_url": m.source_url,
        "published_at": iso(m.published_at),
        "as_of": iso(m.as_of),
        "collected_at": iso(m.collected_at),
        "last_seen_at": iso(m.last_seen_at),
        "revision": m.revision,
        "is_current": m.is_current,
        "supersedes_id": m.supersedes_id,
        "needs_review": bool(extra.get("needs_review")),
        "review_reason": extra.get("review_reason"),
        "extra": extra,
        "source": source_brief(src),
        "reliability": m.reliability,
        "data_status": DataStatus.DEMO.value if m.is_demo else m.data_status,
        "is_demo": m.is_demo,
    }


def _sort_key(row: dict) -> tuple:
    return (TYPE_ORDER.get(row["measure_type"], 99), row["measure_code"] or "", row["quota"]["order_number"] if row["quota"] else "")


def _origin_order(db: Session, extra_origins: set[str]) -> list[Country | str]:
    countries = {c.iso3: c for c in db.scalars(select(Country).where(Country.iso3.in_(list(TARIFF_ORIGINS) + list(extra_origins))))}
    base = [o for o in TARIFF_ORIGINS]
    base += sorted(o for o in extra_origins if o not in TARIFF_ORIGINS)
    prio = [o for o in base if countries.get(o) is not None and countries[o].priority]
    rest = [o for o in base if o not in prio]
    return [countries.get(o) or o for o in prio + rest]


def _ad_documents(db: Session) -> list[RegulationItem]:
    """Federal Register documents that may belong to a honey AD case (title mentions honey)."""
    R = RegulationItem
    return db.scalars(
        select(R).join(Source, Source.id == R.source_id)
        .where(Source.key == FR_SOURCE, demo_clause(R, db), R.title.ilike("%honey%"))
        .order_by(R.published_at.desc().nulls_last(), R.id.desc())
    ).all()


def ad_case_block(iso3: str, fr_docs: list[RegulationItem]) -> dict | None:
    case = AD_CASE_BY_ORIGIN.get(iso3)
    if case is None:
        return None
    docs = [d for d in fr_docs if case.matches(d.title)]
    return {
        "case_number": case.case_number,
        "product": case.product,
        "fr_search_url": case.fr_search_url,
        "documents_total": len(docs),
        "documents": [{"id": d.id, "reference": d.reference, "title": d.title, "doc_type": d.doc_type,
                       "published_at": iso(d.published_at), "url": d.url, "is_demo": d.is_demo}
                      for d in docs[:AD_DOCS_LIMIT]],
    }


def _jurisdiction_status(db: Session, rows: list[dict]) -> dict:
    out = {}
    for j, key in TARIFF_SOURCES.items():
        src = db.scalars(select(Source).where(Source.key == key)).first()
        jr = [r for r in rows if r["jurisdiction"] == j]
        as_of = max((r["as_of"] for r in jr if r["as_of"]), default=None)
        out[j] = {
            "source": source_brief(src),
            "terms_note": src.terms_note if src else None,
            "enabled": src.enabled if src else False,
            "last_run_at": iso(src.last_run_at) if src else None,
            "last_run_status": src.last_run_status if src else None,
            "last_success_at": iso(src.last_success_at) if src else None,
            "freshness": freshness(src) if src else None,
            "as_of": as_of,
            "count": len(jr),
            "review_count": sum(1 for r in jr if r["needs_review"]),
            "general": sorted((r for r in jr if r["scope"] == "general"), key=_sort_key),
        }
    return out


def _validate_origin(origin: str | None, *, allow_general: bool) -> str | None:
    if origin is None or not origin.strip():
        return None
    o = origin.strip().upper()
    if o in TARIFF_ORIGINS or (allow_general and o in GENERAL_ORIGINS) or is_known_iso3(o):
        return o
    raise HTTPException(400, f"Unknown origin {origin!r}")


@router.get("/regulations/duties")
def duties(origin: str | None = Query(None, description="ISO3 of one origin"), db: Session = Depends(get_db)):
    only = _validate_origin(origin, allow_general=False)
    T = TariffMeasure
    srcs = sources_by_id(db)
    current = db.scalars(select(T).where(T.is_current.is_(True), demo_clause(T, db))).all()
    rows = [serialize_measure(m, srcs.get(m.source_id)) for m in current]
    by_origin: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        by_origin[(r["origin_iso3"], r["jurisdiction"])].append(r)
    juris = _jurisdiction_status(db, rows)
    fr_docs = _ad_documents(db)
    extra_origins = {r["origin_iso3"] for r in rows if r["scope"] == "origin" and r["origin_iso3"] not in TARIFF_ORIGINS}
    today = date.today()
    out = []
    for c in _origin_order(db, extra_origins):
        iso3 = c if isinstance(c, str) else c.iso3
        if only and iso3 != only:
            continue
        eu_rows = sorted(by_origin.get((iso3, "EU"), []), key=_sort_key)
        us_rows = sorted(by_origin.get((iso3, "US"), []), key=_sort_key)
        eu_general = [r["id"] for r in juris["EU"]["general"]
                      if iso3 not in ((r["extra"] or {}).get("excluded_origins") or [])]
        us_general = [r["id"] for r in juris["US"]["general"]]
        eu_dates = [r["as_of"] for r in eu_rows if r["as_of"]] + [r["as_of"] for r in juris["EU"]["general"]
                                                                   if r["id"] in eu_general and r["as_of"]]
        us_dates = [r["as_of"] for r in us_rows if r["as_of"]] + [r["as_of"] for r in juris["US"]["general"] if r["as_of"]]
        eu_as_of = max(eu_dates, default=None)
        out.append({
            "iso3": iso3,
            "name_it": None if isinstance(c, str) else c.name_it,
            "name_en": None if isinstance(c, str) else c.name_en,
            "priority": False if isinstance(c, str) else bool(c.priority),
            "eu": {
                "rows": eu_rows,
                "general_ids": eu_general,
                "has_own_mfn": any(r["measure_type"] == MeasureType.MFN.value for r in eu_rows),
                "as_of": eu_as_of,
                "review_count": sum(1 for r in eu_rows if r["needs_review"]),
                "links": {"taric": taric_url(iso3, date.fromisoformat(eu_as_of) if eu_as_of else today)},
            },
            "us": {
                "rows": us_rows,
                "general_ids": us_general,
                "domestic": iso3 == "USA",
                "as_of": max(us_dates, default=None),
                "review_count": sum(1 for r in us_rows if r["needs_review"]),
                "links": {"hts": hts_url()},
                "ad_case": ad_case_block(iso3, fr_docs),
            },
        })
    return {
        "origins": out,
        "jurisdictions": juris,
        "ad_cases": [{"origin_iso3": c.origin_iso3, "case_number": c.case_number, "product": c.product,
                      "fr_search_url": c.fr_search_url} for c in US_AD_CASES],
        "has_data": bool(rows),
        "show_general": {"EU": ERGA_OMNES, "US": ALL_ORIGINS},
    }


@router.get("/regulations/duties/{origin}")
def duty_history(origin: str, db: Session = Depends(get_db)):
    o = origin.strip().upper()
    if not (o in TARIFF_ORIGINS or o in GENERAL_ORIGINS or (re.fullmatch(r"[A-Z]{3}", o) and is_known_iso3(o))):
        raise HTTPException(404, f"Unknown origin {origin!r}")
    T = TariffMeasure
    wanted = [o] if o in GENERAL_ORIGINS else [o, *GENERAL_ORIGINS]
    rows = db.scalars(select(T).where(T.origin_iso3.in_(wanted), demo_clause(T, db))
                      .order_by(T.series_key, T.revision.desc(), T.id.desc())).all()
    srcs = sources_by_id(db)
    groups: dict[tuple[int, str, bool], list[dict]] = defaultdict(list)
    for m in rows:
        groups[(m.source_id, m.series_key, m.is_demo)].append(serialize_measure(m, srcs.get(m.source_id)))
    series = []
    for revs in groups.values():
        latest = revs[0]
        # A general (ERGA OMNES) layer that excludes this origin does not apply to it.
        if latest["scope"] == "general" and o not in GENERAL_ORIGINS \
                and o in ((latest["extra"] or {}).get("excluded_origins") or []):
            continue
        series.append({
            "series_key": latest["series_key"],
            "jurisdiction": latest["jurisdiction"],
            "origin_iso3": latest["origin_iso3"],
            "scope": latest["scope"],
            "measure_type": latest["measure_type"],
            "measure_code": latest["measure_code"],
            "current": any(r["is_current"] for r in revs),
            "revisions": revs,
        })
    series.sort(key=lambda s: (JURISDICTIONS.index(s["jurisdiction"]) if s["jurisdiction"] in JURISDICTIONS else 9,
                               s["scope"] != "origin", TYPE_ORDER.get(s["measure_type"], 99), s["series_key"]))
    country = db.get(Country, o)
    return {
        "origin": o,
        "name_it": country.name_it if country else None,
        "name_en": country.name_en if country else None,
        "series": series,
        "ad_case": ad_case_block(o, _ad_documents(db)) if o not in GENERAL_ORIGINS else None,
        "links": {"taric": taric_url(o, date.today()), "hts": hts_url()},
    }
