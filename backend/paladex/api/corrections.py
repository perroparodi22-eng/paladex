"""Corrections made by a person (/api/corrections/...): services/corrections.py.

    POST /corrections                    create a value correction, a "doubtful figure" flag or a note
                                         (applied at once, queued for synchronisation)
    POST /corrections/{event_id}/revert  undo it (a new revision with the official values restored)
    GET  /corrections                    list (filters: status, kind, country, table + row_id ...)
    GET  /corrections/{event_id}         one event
    POST /corrections/interpret          the person's words -> candidate figures and the proposed change
                                         (AI reads the sentence; nothing is written)
    GET  /corrections/sync               synchronisation state (last pull/push, pending, errors)
    POST /corrections/sync               synchronise now
    GET|PUT /corrections/settings        the name shown on this computer's corrections

Writes are refused to anything but this computer's own interface by main.LocalOnlyGuard.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Source
from ..models_corrections import CorrectionEvent
from ..services import corrections as svc
from ..services import corrections_sync as sync_svc
from .common import iso, source_brief

router = APIRouter(prefix="/corrections", tags=["corrections"])


def _http(exc: svc.CorrectionError) -> HTTPException:
    return HTTPException(exc.status, detail=exc.detail())


class TargetIn(BaseModel):
    table: str = Field(max_length=40)
    row_id: int | None = None
    source_key: str | None = Field(None, max_length=60)
    series_key: str | None = Field(None, max_length=300)


class CorrectionIn(BaseModel):
    kind: Literal["value_correction", "flag_wrong", "note"] = "value_correction"
    target: TargetIn | None = None
    value: float | str | None = None
    low: float | str | None = None
    high: float | str | None = None
    unit: str | None = Field(None, max_length=20)
    currency: str | None = Field(None, max_length=10)
    field: Literal["net_weight_kg", "value"] | None = None      # trade flows: quantity or value
    reason: str | None = Field(None, max_length=svc.MAX_TEXT)
    text: str | None = Field(None, max_length=svc.MAX_TEXT)     # a note's text
    country_iso3: str | None = Field(None, max_length=10)
    ai_interpretation: dict | None = None


class RevertIn(BaseModel):
    reason: str | None = Field(None, max_length=svc.MAX_TEXT)


class InterpretContext(BaseModel):
    table: str = Field(max_length=40)
    row_id: int | None = None
    source_key: str | None = Field(None, max_length=60)
    series_key: str | None = Field(None, max_length=300)


class InterpretIn(BaseModel):
    text: str = Field(max_length=2000)
    lang: Literal["it", "en"] = "it"
    context: InterpretContext | None = None


class SettingsIn(BaseModel):
    author: str | None = Field(None, max_length=120)
    # Exchange corrections with the other computers (off until switched on here, on each computer).
    sync: bool | None = None


def _figure(db: Session, ev: CorrectionEvent) -> dict | None:
    """The row written for an event (what the figure now shows)."""
    table, field = ev.target_table, ev.target_field
    model = svc.TABLES.get(table or "")
    row = db.get(model, ev.applied_row_id) if model is not None and ev.applied_row_id else None
    if row is None:
        return None
    unit, ccy = svc.unit_currency(table, row, field)
    src = db.get(Source, row.source_id)
    return {"table": table, "row_id": row.id, "is_current": row.is_current, "revision": row.revision,
            "value": getattr(row, svc.main_field(table, field)), "unit": unit, "currency": ccy, "field": field,
            "data_status": row.data_status, "reliability": row.reliability, "period_label": row.period_label,
            "source": source_brief(src), "correction": svc.row_correction(row), "link": svc.figure_link(table, row),
            "collected_at": iso(row.collected_at)}


def _after_write(db: Session) -> None:
    db.commit()
    sync_svc.sync_in_background("event")     # pushes the new event when synchronisation is on
    from . import memo

    memo.warm_in_background()


@router.post("", status_code=201)
def create(body: CorrectionIn, db: Session = Depends(get_db)):
    t = body.target
    try:
        ev = svc.create_event(
            db, body.kind, table=t.table if t else None, row_id=t.row_id if t else None,
            source_key=t.source_key if t else None, series_key=t.series_key if t else None,
            value=body.value, low=body.low, high=body.high, unit=body.unit, currency=body.currency, field=body.field,
            reason=body.reason, text=body.text, country_iso3=body.country_iso3,
            ai_interpretation=body.ai_interpretation)
    except svc.CorrectionError as exc:
        db.rollback()
        raise _http(exc) from None
    device = svc.device_id(db)
    _after_write(db)
    return {"event": svc.serialize(ev, this_device=device), "figure": _figure(db, ev)}


@router.post("/interpret")
def interpret(body: InterpretIn, db: Session = Depends(get_db)):
    from ..services import corrections_ai

    ctx = body.context.model_dump() if body.context else None
    try:
        return corrections_ai.interpret(db, body.text, body.lang, ctx)
    except svc.CorrectionError as exc:
        raise _http(exc) from None


@router.get("/sync")
def sync_state(db: Session = Depends(get_db)):
    return sync_svc.status(db)


@router.post("/sync")
def sync_now(db: Session = Depends(get_db)):
    db.close()       # the synchronisation uses its own sessions
    res = sync_svc.sync_now(push=True, trigger="manual")
    from ..db import session_factory

    with session_factory()() as s:
        state = sync_svc.status(s)
    return {**state, "ok": res.get("ok", False), "last_received": res.get("last_received")}


@router.get("/settings")
def get_settings_(db: Session = Depends(get_db)):
    from ..config import get_settings

    return {"author": svc.author_name(db), "default_author": svc.DEFAULT_AUTHOR,
            "author_from_env": bool((get_settings().user_name or "").strip()),
            "sync_enabled": get_settings().corrections_sync}


@router.put("/settings")
def put_settings(body: SettingsIn, db: Session = Depends(get_db)):
    from .. import envfile
    from ..config import get_settings

    out: dict = {}
    if body.author is not None or body.sync is None:
        try:
            out["author"] = svc.set_author_name(db, body.author)
        except svc.CorrectionError as exc:
            raise _http(exc) from None
        db.commit()
    if body.sync is not None:
        # Written to this computer's .env (like the source keys), so the choice survives a restart.
        envfile.set_env_value("PALADEX_CORRECTIONS_SYNC", "true" if body.sync else "false")
        get_settings.cache_clear()
        if body.sync:
            from .. import scheduler as sched_mod

            if sched_mod._scheduler is not None:
                sync_svc.schedule(sched_mod._scheduler)
        else:
            from .. import scheduler as sched_mod

            if sched_mod._scheduler is not None and sched_mod._scheduler.get_job("corrections:sync"):
                sched_mod._scheduler.remove_job("corrections:sync")
        out["sync_enabled"] = get_settings().corrections_sync
    return out


@router.get("")
def list_events(
    status: str | None = Query(None, description="comma list: applied, conflict, superseded_by_source ..."),
    kind: str | None = Query(None, description="comma list: value_correction, revert, flag_wrong, note"),
    country: str | None = Query(None, description="ISO3: events about this country (notes for the country page)"),
    table: str | None = Query(None, description="with row_id: events about that figure's series"),
    row_id: int | None = Query(None),
    sync: str | None = Query(None, description="pending_sync | synced | received"),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    E = CorrectionEvent
    conds = []
    if status:
        conds.append(E.status.in_([s.strip() for s in status.split(",") if s.strip()]))
    if kind:
        conds.append(E.kind.in_([k.strip() for k in kind.split(",") if k.strip()]))
    if country:
        conds.append(E.country_iso3 == country.strip().upper())
    if sync:
        conds.append(E.sync_status == sync)
    if table and row_id is not None:
        model = svc.TABLES.get(table)
        row = db.get(model, row_id) if model is not None else None
        if row is None:
            raise HTTPException(404, detail={"code": "not_found", "message_it": "Dato non trovato.",
                                             "message_en": "Figure not found."})
        src = db.get(Source, row.source_id)
        conds.append(or_(E.applied_row_id == row_id, E.target_row_id == row_id,
                         (E.target_table == table) & (E.series_key == row.series_key) & (E.source_key == src.key)))
    total = db.scalar(select(func.count()).select_from(E).where(*conds)) or 0
    rows = db.scalars(select(E).where(*conds).order_by(E.created_at.desc(), E.id.desc()).limit(limit)).all()
    counts = dict(db.execute(select(E.status, func.count()).group_by(E.status)).all())
    pending = db.scalar(select(func.count()).select_from(E).where(E.origin == "local",
                                                                  E.sync_status == "pending_sync")) or 0
    device = svc._setting(db, svc.DEVICE_SETTING)
    return {"total": total, "items": [svc.serialize(e, this_device=device) for e in rows],
            "counts": counts, "pending_sync": pending, "author": svc.author_name(db)}


@router.get("/{event_id}")
def get_event(event_id: str, db: Session = Depends(get_db)):
    ev = svc.get_event(db, event_id)
    if ev is None:
        raise HTTPException(404, detail={"code": "not_found", "message_it": "Correzione non trovata.",
                                         "message_en": "Correction not found."})
    out = svc.serialize(ev, this_device=svc._setting(db, svc.DEVICE_SETTING))
    out["figure"] = _figure(db, ev)
    return out


@router.post("/{event_id}/revert", status_code=201)
def revert(event_id: str, body: RevertIn | None = None, db: Session = Depends(get_db)):
    try:
        ev = svc.create_revert(db, event_id, reason=body.reason if body else None)
    except svc.CorrectionError as exc:
        db.rollback()
        raise _http(exc) from None
    device = svc.device_id(db)
    _after_write(db)
    target = svc.get_event(db, event_id)
    return {"event": svc.serialize(ev, this_device=device),
            "reverted": svc.serialize(target, this_device=device) if target else None,
            "figure": _figure(db, ev)}
