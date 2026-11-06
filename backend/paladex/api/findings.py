"""Other sources (non-official): verified web findings (/api/findings...). Read-only, except the AI switch.

    GET /findings?country=&metric=   current verified findings (newest first), optional filters
    GET /findings/ai                 the weekly AI web search: switch, cap, provider, cost estimate
                                     (prices used and their date), usage of the last runs
    PUT /findings/ai                 {enabled?, max_searches?}: the owner's switch (Sources page)

``country_block`` is the ``web_findings`` block of GET /countries/{iso3}. Findings are kept apart from
the official data: nothing here feeds the map, rankings, totals, comparisons, alerts or the official
series, and GET /countries (the map list) never reads them.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models_findings import FindingMetric, WebFinding
from .common import demo_clause, get_setting, iso, set_setting

router = APIRouter(prefix="/findings", tags=["findings"])

METRIC_ORDER = [m.value for m in FindingMetric]
PER_METRIC = 6
NOTE = {
    "it": ("Dati trovati sul web, ciascuno verificato da Paladex sulla pagina che cita (la frase citata e il numero "
           "sono stati ritrovati sulla pagina). Non sono statistiche ufficiali e non vengono mai sommati ai dati "
           "ufficiali, alla mappa o ai confronti."),
    "en": ("Figures found on the web, each checked by Paladex on the page it cites (the quoted sentence and the number "
           "were found on that page). They are not official statistics and are never added to the official figures, "
           "the map or the comparisons."),
}


def serialize(r: WebFinding) -> dict:
    v = r.verification or {}
    extra = r.extra or {}
    return {
        "id": r.id, "country_iso3": r.country_iso3, "metric": r.metric,
        "period_label": r.period_label, "period_start": iso(r.period_start), "period_end": iso(r.period_end),
        "value": r.value, "unit": r.unit, "value_as_published": r.value_as_published,
        "value_low": extra.get("value_low"), "value_high": extra.get("value_high"),   # a range, as published
        "status": r.status, "kind": r.kind, "is_official": bool(r.is_official),
        "publisher": r.publisher, "source_url": r.source_url, "source_title": r.source_title,
        "published_at": iso(r.published_at), "language": r.language, "quote": r.quote,
        "also_reported_by": r.also_reported_by or [],
        "verified_at": iso(r.verified_at),
        "last_check": {"at": v.get("checked_at"), "ok": v.get("ok"), "reason": v.get("reason"), "detail": v.get("detail"),
                       "doc_type": v.get("doc_type"), "number_in_quote": v.get("number_in_quote")} if v else None,
        "found_by": extra.get("found_by"), "ai_model": extra.get("model") if extra.get("found_by") == "ai_web_search" else None,
        "collected_at": iso(r.collected_at), "revision": r.revision, "notes": r.notes, "is_demo": bool(r.is_demo),
    }


def _rows(db: Session, *, country: str | None = None, metric: str | None = None) -> list[WebFinding]:
    W = WebFinding
    q = select(W).where(W.is_current.is_(True), W.verified_at.is_not(None), demo_clause(W, db))
    if country:
        q = q.where(W.country_iso3 == country)
    if metric:
        q = q.where(W.metric == metric)
    rows = db.scalars(q).all()
    # newest first: the period's end, then the publication date
    return sorted(rows, key=lambda r: (r.period_end or date.min, r.published_at or date.min, r.id), reverse=True)


def _not_found(iso3: str, db: Session) -> list[dict]:
    """What was searched for this country without finding a recent figure (the seed's research and the
    optional AI search), for the empty state."""
    from ..collectors.web_findings import seed_summary
    from ..services.findings_ai import AI_STATE_SETTING

    seed = seed_summary()
    out = [{"by": "seed", "searched": str(x.get("searched") or ""), "result": str(x.get("result") or ""),
            "on": seed.compiled_on}
           for x in seed.not_found if isinstance(x, dict) and str(x.get("country_iso3") or "").upper() == iso3]
    ai = (get_setting(db, AI_STATE_SETTING) or {}).get(iso3)
    if isinstance(ai, dict) and not ai.get("stored"):
        out.append({"by": "ai_web_search", "searched": str(ai.get("searched") or "; ".join(ai.get("queries") or [])),
                    "result": "", "on": ai.get("searched_at")})
    return out


def country_block(db: Session, iso3: str) -> dict:
    """The ``web_findings`` block of a country profile."""
    from ..collectors.web_findings import seed_summary

    rows = _rows(db, country=iso3)
    by_metric: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_metric[r.metric].append(serialize(r))
    metrics = [{"metric": m, "findings": by_metric[m][:PER_METRIC], "count": len(by_metric[m])}
               for m in METRIC_ORDER if by_metric.get(m)]
    seed = seed_summary()
    return {
        "available": bool(rows), "count": len(rows), "metrics": metrics,
        "not_found": [] if rows else _not_found(iso3, db),
        "seed_compiled_on": seed.compiled_on, "note_it": NOTE["it"], "note_en": NOTE["en"],
        "is_official_statistics": False,
    }


@router.get("")
def list_findings(country: str | None = None, metric: str | None = None, db: Session = Depends(get_db)):
    code = country.strip().upper() if country else None
    if code is not None and not (code.isalpha() and len(code) == 3):
        raise HTTPException(422, "country: ISO3 code expected")
    if metric is not None and metric not in METRIC_ORDER:
        raise HTTPException(422, f"metric: one of {', '.join(METRIC_ORDER)}")
    rows = _rows(db, country=code, metric=metric)
    return {"findings": [serialize(r) for r in rows], "count": len(rows), "note_it": NOTE["it"], "note_en": NOTE["en"]}


# ---------------------------------------------------------------------------
# The optional weekly AI web search
# ---------------------------------------------------------------------------

def _ai_payload(db: Session) -> dict:
    from ..services import findings_ai as fa

    settings = get_settings()
    st = fa.ai_status(db, settings)
    runs = [r for r in (get_setting(db, fa.AI_USAGE_SETTING) or []) if isinstance(r, dict)]
    return {
        **st,
        "estimate": fa.estimate(st["model"], st["max_searches"]),
        "max_searches_limit": fa.MAX_SEARCHES_LIMIT,
        "searches_per_country": fa.SEARCHES_PER_COUNTRY,
        "runs": runs[-6:][::-1],              # newest first
        "openai_supported": False,
    }


@router.get("/ai")
def get_ai(db: Session = Depends(get_db)):
    return _ai_payload(db)


class AiBody(BaseModel):
    enabled: bool | None = None
    max_searches: int | None = Field(default=None, ge=1, le=100)


@router.put("/ai")
def put_ai(body: AiBody, db: Session = Depends(get_db)):
    from ..services import findings_ai as fa

    stored = fa.stored_settings(db)
    if body.enabled is not None:
        stored["enabled"] = body.enabled
    if body.max_searches is not None:
        stored["max_searches"] = body.max_searches
    set_setting(db, fa.AI_SETTING, stored)
    db.commit()
    return _ai_payload(db)
