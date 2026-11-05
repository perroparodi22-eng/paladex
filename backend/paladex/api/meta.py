"""Meta endpoints: health, reference lists, sources & collection control, settings."""
from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..enums import DataStatus, PriceType, Reliability
from ..models import (
    CollectionRun,
    Country,
    FxRate,
    NewsArticle,
    PriceObservation,
    ProductionStat,
    RegulationItem,
    Report,
    Source,
    TradeFlowObservation,
)
from ..reference.varieties import CORE_VARIETIES, LABELS
from .common import age_hours, freshness, get_setting, iso, set_setting, show_demo

router = APIRouter(tags=["meta"])

_collect_state: dict = {"running": False, "started_at": None, "keys": None, "results": None}
_collect_lock = threading.Lock()

PRICE_TYPE_LABELS = {
    PriceType.WHOLESALE_BULK: {"it": "Prezzo all'ingrosso (sfuso)", "en": "Wholesale (bulk)"},
    PriceType.PRODUCER: {"it": "Prezzo al produttore", "en": "Producer / beekeeper price"},
    PriceType.IMPORT_UNIT_VALUE: {"it": "Valore unitario import (dogana)", "en": "Import unit value (customs)"},
    PriceType.EXPORT_UNIT_VALUE: {"it": "Valore unitario export (dogana)", "en": "Export unit value (customs)"},
    PriceType.RETAIL: {"it": "Prezzo al dettaglio", "en": "Retail price"},
    PriceType.OTHER: {"it": "Altro", "en": "Other"},
}
STATUS_LABELS = {
    DataStatus.LIVE: {"it": "In tempo reale", "en": "Live"},
    DataStatus.PUBLISHED: {"it": "Dato pubblicato", "en": "Published"},
    DataStatus.PROVISIONAL: {"it": "Provvisorio", "en": "Provisional"},
    DataStatus.ESTIMATE: {"it": "Stima", "en": "Estimate"},
    DataStatus.FORECAST: {"it": "Previsione", "en": "Forecast"},
    DataStatus.AI_ASSESSMENT: {"it": "Valutazione IA", "en": "AI assessment"},
    DataStatus.USER_ENTERED: {"it": "Inserito dall'utente", "en": "User entered"},
    DataStatus.DEMO: {"it": "DIMOSTRATIVO", "en": "DEMO"},
}
RELIABILITY_LABELS = {
    Reliability.OFFICIAL: {"it": "Fonte ufficiale", "en": "Official source"},
    Reliability.INDUSTRY: {"it": "Fonte di settore", "en": "Industry source"},
    Reliability.TRADE_PRESS: {"it": "Stampa di settore", "en": "Trade press"},
    Reliability.AGGREGATOR: {"it": "Aggregatore notizie", "en": "News aggregator"},
    Reliability.USER: {"it": "Inserito dall'utente", "en": "User entered"},
    Reliability.AI: {"it": "Generato da IA", "en": "AI generated"},
    Reliability.DEMO: {"it": "Dimostrativo", "en": "Demo"},
}


# Primary sources first: government / intergovernmental, then industry bodies, then third parties.
RELIABILITY_RANK = {
    Reliability.OFFICIAL.value: 0, Reliability.INDUSTRY.value: 1, Reliability.TRADE_PRESS.value: 2,
    Reliability.AGGREGATOR.value: 3, Reliability.USER.value: 4, Reliability.AI.value: 5, Reliability.DEMO.value: 6,
}


@router.get("/health")
def health():
    return {"ok": True}


@router.get("/meta")
def meta(db: Session = Depends(get_db)):
    countries = db.scalars(select(Country).order_by(Country.name_it)).all()
    return {
        "flags": get_settings().public_flags(),
        "show_demo": show_demo(db),
        "language": get_setting(db, "language", "it"),
        "countries": [
            {"iso3": c.iso3, "iso2": c.iso2, "name_it": c.name_it, "name_en": c.name_en, "priority": c.priority,
             "region": c.region, "lat": c.lat, "lon": c.lon}
            for c in countries
        ],
        "varieties": [{"key": k, **LABELS[k], "core": k in CORE_VARIETIES} for k in LABELS],
        "price_types": [{"key": k.value, **v} for k, v in PRICE_TYPE_LABELS.items()],
        "data_status": [{"key": k.value, **v} for k, v in STATUS_LABELS.items()],
        "reliability": [{"key": k.value, **v} for k, v in RELIABILITY_LABELS.items()],
    }


def _source_counts(db: Session) -> dict[int, dict]:
    out: dict[int, dict] = {}

    def add(model, label, current_only=True):
        q = select(model.source_id, func.count()).group_by(model.source_id)
        if current_only and hasattr(model, "is_current"):
            q = q.where(model.is_current.is_(True))
        for sid, n in db.execute(q):
            out.setdefault(sid, {})[label] = n

    add(PriceObservation, "prices")
    add(TradeFlowObservation, "trade")
    add(ProductionStat, "production")
    add(NewsArticle, "news", current_only=False)
    add(Report, "reports", current_only=False)
    add(RegulationItem, "regulations", current_only=False)
    fx_n = db.scalar(select(func.count(FxRate.id)))
    fx_src = db.scalars(select(Source).where(Source.key == "ecb_fx")).first()
    if fx_src is not None and fx_n:
        out.setdefault(fx_src.id, {})["fx_rates"] = fx_n
    return out


def serialize_source(s: Source, counts: dict | None = None) -> dict:
    settings = get_settings()
    key_missing = bool(s.requires_key) and not getattr(settings, s.requires_key, None)
    return {
        "key": s.key, "name": s.name, "publisher": s.publisher, "homepage": s.homepage, "kind": s.kind,
        "reliability": s.reliability, "category": s.category, "country_iso3": s.country_iso3,
        "expected_update": s.expected_update, "expected_update_en": s.expected_update_en,
        "expected_max_age_days": s.expected_max_age_days,
        "terms_note": s.terms_note, "enabled": s.enabled, "requires_key": s.requires_key, "key_missing": key_missing,
        "last_run_at": iso(s.last_run_at), "last_run_status": s.last_run_status,
        "last_success_at": iso(s.last_success_at), "last_new_data_at": iso(s.last_new_data_at),
        "latest_published_at": iso(s.latest_published_at), "latest_period_label": s.latest_period_label,
        "hours_since_check": age_hours(s.last_run_at),
        "freshness": freshness(s), "counts": counts or {},
    }


@router.get("/sources")
def list_sources(db: Session = Depends(get_db)):
    counts = _source_counts(db)
    rows = db.scalars(select(Source).where(Source.key != "demo")).all()
    # Official / government sources first within each category, then industry, press, aggregators.
    rows = sorted(rows, key=lambda s: (s.category or "", RELIABILITY_RANK.get(s.reliability, 9), (s.name or "").lower()))
    return {"sources": [serialize_source(s, counts.get(s.id)) for s in rows], "collect": _collect_state_public()}


@router.get("/sources/{key}/runs")
def source_runs(key: str, limit: int = 30, db: Session = Depends(get_db)):
    src = db.scalars(select(Source).where(Source.key == key)).first()
    if not src:
        raise HTTPException(404, "unknown source")
    runs = db.scalars(
        select(CollectionRun).where(CollectionRun.source_id == src.id).order_by(CollectionRun.started_at.desc()).limit(limit)
    ).all()
    return {
        "source": serialize_source(src),
        "runs": [
            {"id": r.id, "started_at": iso(r.started_at), "finished_at": iso(r.finished_at), "status": r.status,
             "trigger": r.trigger, "items_seen": r.items_seen, "items_new": r.items_new,
             "items_revised": r.items_revised, "warnings": r.warnings, "error": r.error}
            for r in runs
        ],
    }


class SourceToggle(BaseModel):
    enabled: bool


@router.put("/sources/{key}")
def toggle_source(key: str, body: SourceToggle, db: Session = Depends(get_db)):
    src = db.scalars(select(Source).where(Source.key == key)).first()
    if not src:
        raise HTTPException(404, "unknown source")
    src.enabled = body.enabled
    db.commit()
    return serialize_source(src)


class CollectRequest(BaseModel):
    keys: list[str] | None = None
    force: bool = False


def _collect_state_public() -> dict:
    return {k: (iso(v) if k == "started_at" else v) for k, v in _collect_state.items()}


def start_collection(keys: list[str] | None = None, force: bool = False, trigger: str = "manual") -> bool:
    """Start a background collection unless one is already running."""
    from ..collectors.runner import run_all
    from ..models import utcnow

    with _collect_lock:
        if _collect_state["running"]:
            return False
        _collect_state.update(running=True, started_at=utcnow(), keys=keys, results=None)

    def worker():
        try:
            _collect_state["results"] = run_all(trigger=trigger, force=force, keys=keys)
        finally:
            _collect_state["running"] = False

    threading.Thread(target=worker, name="paladex-collect", daemon=True).start()
    return True


@router.post("/collect")
def collect(body: CollectRequest):
    started = start_collection(body.keys, body.force)
    return {"started": started, "state": _collect_state_public()}


@router.get("/collect/status")
def collect_status(db: Session = Depends(get_db)):
    from ..services.starter import first_run_state

    # `first_run` lets the interface explain the first minutes after installation (starter data
    # shown while this computer's first collection runs, or no data yet).
    return {**_collect_state_public(), "first_run": first_run_state(db)}


class SettingsBody(BaseModel):
    show_demo: bool | None = None
    language: str | None = None


@router.get("/settings")
def get_settings_endpoint(db: Session = Depends(get_db)):
    return {"show_demo": show_demo(db), "language": get_setting(db, "language", "it"),
            "flags": get_settings().public_flags()}


@router.put("/settings")
def put_settings(body: SettingsBody, db: Session = Depends(get_db)):
    if body.show_demo is not None:
        set_setting(db, "show_demo", body.show_demo)
    if body.language in ("it", "en"):
        set_setting(db, "language", body.language)
    db.commit()
    return get_settings_endpoint(db)


@router.post("/demo/seed")
def demo_seed(db: Session = Depends(get_db)):
    from ..services.demo import seed_demo

    n = seed_demo(db)
    set_setting(db, "show_demo", True)
    db.commit()
    return {"inserted": n}


@router.delete("/demo")
def demo_purge(db: Session = Depends(get_db)):
    from ..services.demo import purge_demo

    n = purge_demo(db)
    set_setting(db, "show_demo", False)
    db.commit()
    return {"deleted": n}
