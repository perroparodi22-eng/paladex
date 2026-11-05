"""AI assistant and daily AI briefing ("Assistente IA", /api/assistant/...).

* ``POST /assistant/ask``                 {question, lang, quote_ids?}: an answer built from the local
                                          database only (services.assistant): numbered facts with their
                                          provenance, sections, notes and warnings. With an AI provider the
                                          text is written by the model and post-checked; without, the
                                          retrieved facts are the answer (``ai_used=false``).
* ``GET  /assistant/history``             the last questions asked on this PC; ``GET /assistant/history/{id}``
                                          one full answer; ``DELETE /assistant/history`` clears the list.
* ``GET  /assistant/status``              AI provider configured or not, how to enable it, today's briefing.
* ``GET  /assistant/quotes``              valid supplier offers the owner can pick for a comparison.
* ``GET  /assistant/briefing``            today's stored AI briefing (sections, points with citations).
* ``POST /assistant/briefing/regenerate`` write today's AI briefing again (services.briefing).

Supplier offers stay on this computer: they are read only for questions about offers, and the AI
provider then sees "Offerta A/B/C", never the supplier name or the notes (see services.assistant).
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import SupplierQuote
from ..reference.countries import country_name
from ..reference.varieties import LABELS as VARIETY_LABELS
from ..services import assistant as svc
from ..services import briefing as brief
from ..services import llm
from .common import demo_clause, iso

router = APIRouter(prefix="/assistant", tags=["assistant"])


class AskBody(BaseModel):
    question: str = Field(..., min_length=1, max_length=svc.QUESTION_MAX_CHARS)
    lang: Literal["it", "en"] = "it"
    quote_ids: list[int] | None = Field(None, max_length=10)

    @field_validator("question")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("empty question")
        return v


class RegenerateBody(BaseModel):
    lang: Literal["it", "en"] | None = None


@router.post("/ask")
def ask(body: AskBody, db: Session = Depends(get_db)) -> dict:
    return svc.answer(db, body.question, body.lang, quote_ids=body.quote_ids or None)


@router.get("/history")
def history(limit: int = Query(svc.HISTORY_MAX, ge=1, le=svc.HISTORY_MAX)) -> dict:
    items = svc.load_history(limit)
    return {"items": items, "count": len(items), "max": svc.HISTORY_MAX}


@router.get("/history/{entry_id}")
def history_item(entry_id: str) -> dict:
    ans = svc.history_entry(entry_id)
    if ans is None:
        raise HTTPException(404, "Domanda non trovata nella cronologia")
    return ans


@router.delete("/history")
def clear_history() -> dict:
    return {"deleted": svc.clear_history()}


@router.get("/status")
def status(db: Session = Depends(get_db)) -> dict:
    return svc.status(db)


@router.get("/quotes")
def quotes(lang: str = Query("it", pattern="^(it|en)$"), db: Session = Depends(get_db)) -> dict:
    """Valid (not archived, not expired) offers, newest first: the choice for 'Confronta queste offerte'."""
    Q = SupplierQuote
    today = svc.clock_today()
    rows = db.scalars(select(Q).where(demo_clause(Q, db), Q.archived.is_(False),
                                      or_(Q.valid_until.is_(None), Q.valid_until >= today))
                      .order_by(Q.date_received.desc(), Q.id.desc()).limit(50)).all()
    return {"items": [{
        "id": q.id, "supplier_name": q.supplier_name, "origin_iso3": q.origin_iso3,
        "origin_name": country_name(q.origin_iso3, lang) or q.origin_iso3,
        "variety": q.variety, "variety_name": VARIETY_LABELS.get(q.variety, {}).get(lang, q.variety),
        "price_per_kg": q.price_per_kg, "currency": q.currency, "incoterm": q.incoterm,
        "date_received": iso(q.date_received), "valid_until": iso(q.valid_until), "is_demo": q.is_demo,
    } for q in rows]}


@router.get("/briefing")
def briefing(lang: str = Query("it", pattern="^(it|en)$"), db: Session = Depends(get_db)) -> dict:
    return {"enabled": llm.is_enabled(), "date": svc.clock_today().isoformat(), "schedule": "07:00",
            "briefing": brief.stored(db, lang)}


@router.post("/briefing/regenerate")
def regenerate_briefing(body: RegenerateBody | None = None, db: Session = Depends(get_db)) -> dict:
    """Write today's AI briefing again (both languages unless one is given). Without an AI provider
    nothing is written and the overview keeps its rule-based summary."""
    langs = [body.lang] if body and body.lang else list(brief.LANGS)
    res = brief.generate_daily(db, langs, force=True)
    res["briefing"] = {lang: brief.stored(db, lang) for lang in langs} if res["enabled"] else None
    return res
