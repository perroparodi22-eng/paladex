"""Alert center API (/api/alerts/...): rules CRUD, event feed, read state, 'test now' preview.

Endpoints:
    GET    /alerts/rules                 rules with plain-language descriptions and event counts
    POST   /alerts/rules                 create a rule (it starts watching now; see services.alerts)
    PUT    /alerts/rules/{id}            rename, change conditions, switch on/off
    DELETE /alerts/rules/{id}            delete a rule and its events
    POST   /alerts/rules/{id}/test       what the saved rule finds on the current data
    POST   /alerts/preview               the same for a rule being edited (not saved)
    GET    /alerts/events                feed: unread first, then newest; filters
    PUT    /alerts/events/{id}           mark one event read / unread
    POST   /alerts/events/read-all       mark every (or one rule's) event read
    GET    /alerts/unread-count          for the bell in the top bar
    POST   /alerts/evaluate              check every rule now (also runs after each collection)
    GET    /alerts/options               what the rule editor can offer (only things that have data)

The example rules are created the first time this section is used (or after the first collection),
once: a rule the owner deletes never comes back.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, delete, func, select, update
from sqlalchemy.orm import Session

from ..db import get_db
from ..enums import AlertType, PriceType
from ..models import (
    AlertEvent,
    AlertRule,
    NewsArticle,
    PriceObservation,
    RegulationItem,
    Report,
    Source,
    TariffMeasure,
    TradeFlowObservation,
    utcnow,
)
from ..reference.countries import PRIORITY_ISO3, is_known_iso3
from ..reference.varieties import LABELS as VARIETY_LABELS
from ..services import alerts as svc
from .common import get_setting, iso, source_brief, sources_by_id

router = APIRouter(prefix="/alerts", tags=["alerts"])

MAX_KEYWORDS = 20
MAX_LIST = 40
TRADE_PSEUDO = {"WLD", "EU27", "EU28", "EXTRA_EU", "INTRA_EU"}


# ---------------------------------------------------------------------------
# Seeding on first use
# ---------------------------------------------------------------------------


def _ensure_seeded(db: Session) -> None:
    """Create the example rules once and take their baseline (the 14-day report look-back fires)."""
    if get_setting(db, svc.SEED_SETTING):
        return
    if svc.ensure_default_rules(db):
        svc.evaluate_all(db)
    db.commit()


# ---------------------------------------------------------------------------
# Validation of rule parameters
# ---------------------------------------------------------------------------


def _bad(msg_it: str, msg_en: str) -> HTTPException:
    return HTTPException(422, f"{msg_it} / {msg_en}")


def _iso3(v, *, allow: set[str] = frozenset(), field: str = "country") -> str:
    code = str(v or "").strip().upper()
    if not code or not (code in allow or (re.fullmatch(r"[A-Z]{3}", code) and is_known_iso3(code))):
        raise _bad(f"Codice paese non valido ({field}): {v!r}", f"Invalid country code ({field}): {v!r}")
    return code


def _threshold(v) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise _bad("Soglia non valida", "Invalid threshold") from None
    if not (0 < x <= 1000) or math.isnan(x):
        raise _bad("La soglia deve essere tra 0 e 1000%", "The threshold must be between 0 and 1000%")
    return round(x, 2)


def _str_list(v, *, limit: int = MAX_LIST, max_len: int = 60) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        v = [x for x in v.split(",")]
    if not isinstance(v, list):
        raise _bad("Elenco non valido", "Invalid list")
    out: list[str] = []
    for x in v:
        s = str(x).strip()[:max_len]
        if s and s not in out:
            out.append(s)
    return out[:limit]


def validate_params(db: Session, alert_type: str, params: dict | None) -> dict:
    """Normalised parameters for `alert_type`, or HTTP 422 explaining what is wrong (IT / EN)."""
    p = svc.public_params(params or {})
    if alert_type == AlertType.PRICE_CHANGE.value:
        pt = p.get("price_type")
        if pt not in [x.value for x in PriceType]:
            raise _bad("Tipo di prezzo non valido", "Invalid price type")
        variety = p.get("variety")
        if variety not in VARIETY_LABELS:
            raise _bad("Varietà non valida", "Invalid variety")
        direction = p.get("direction") or "up"
        if direction not in svc.DIRECTIONS:
            raise _bad("Direzione non valida (up, down, any)", "Invalid direction (up, down, any)")
        color = (str(p.get("color_grade")).strip() or None) if p.get("color_grade") else None
        return {
            "price_type": pt, "origin": _iso3(p.get("origin"), field="origin"), "variety": variety,
            "market": _iso3(p["market"], allow={"EU27", "WLD"}, field="market") if p.get("market") else None,
            "color_grade": color[:60] if color else None, "threshold_pct": _threshold(p.get("threshold_pct")),
            "direction": direction,
        }
    if alert_type == AlertType.NEW_REPORT.value:
        keys = _str_list(p.get("source_keys"))
        if not keys:
            raise _bad("Scegli almeno una fonte", "Choose at least one source")
        known = set(db.scalars(select(Source.key).where(Source.key.in_(keys))))
        unknown = [k for k in keys if k not in known]
        if unknown:
            raise _bad(f"Fonte sconosciuta: {', '.join(unknown)}", f"Unknown source: {', '.join(unknown)}")
        return {"source_keys": keys}
    if alert_type == AlertType.NEWS_KEYWORD.value:
        keywords = _str_list(p.get("keywords"), limit=MAX_KEYWORDS)
        countries = [_iso3(c) for c in _str_list(p.get("countries"))]
        try:
            rel = int(p.get("min_relevance") or 0)
        except (TypeError, ValueError):
            raise _bad("Rilevanza non valida", "Invalid relevance") from None
        if not 0 <= rel <= 100:
            raise _bad("La rilevanza va da 0 a 100", "Relevance goes from 0 to 100")
        if not keywords and not countries:
            raise _bad("Indica almeno una parola o un paese", "Give at least one word or one country")
        return {"keywords": keywords, "countries": countries, "min_relevance": rel}
    if alert_type == AlertType.REGULATION.value:
        juris = [j.upper() for j in _str_list(p.get("jurisdictions"), max_len=10)]
        if any(not re.fullmatch(r"[A-Z]{2,10}", j) for j in juris):
            raise _bad("Giurisdizione non valida", "Invalid jurisdiction")
        doc_types = _str_list(p.get("doc_types"), max_len=40)
        if any(not re.fullmatch(r"[a-z_]{2,40}", t) for t in doc_types):
            raise _bad("Tipo di documento non valido", "Invalid document type")
        countries = [_iso3(c) for c in _str_list(p.get("countries"))]
        return {"jurisdictions": juris, "doc_types": doc_types, "countries": countries,
                "include_tariffs": bool(p.get("include_tariffs", True))}
    if alert_type == AlertType.TRADE_CHANGE.value:
        flow = p.get("flow") or "import"
        if flow not in ("import", "export"):
            raise _bad("Flusso non valido (import, export)", "Invalid flow (import, export)")
        freq = (p.get("freq") or "M").upper()
        if freq not in svc.TRADE_FREQS:
            raise _bad("Frequenza non valida (M, A)", "Invalid frequency (M, A)")
        direction = p.get("direction") or "any"
        if direction not in svc.DIRECTIONS:
            raise _bad("Direzione non valida (up, down, any)", "Invalid direction (up, down, any)")
        return {
            "reporter": _iso3(p.get("reporter"), allow={"EU27", "EU28"}, field="reporter"),
            "partner": _iso3(p.get("partner") or "WLD", allow={"WLD"}, field="partner"),
            "flow": flow, "threshold_pct": _threshold(p.get("threshold_pct")), "freq": freq, "direction": direction,
        }
    raise _bad(f"Tipo di avviso sconosciuto: {alert_type!r}", f"Unknown alert type: {alert_type!r}")


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def _event_counts(db: Session) -> dict[int, dict]:
    q = select(AlertEvent.rule_id, func.count(), func.sum(case((AlertEvent.read.is_(False), 1), else_=0)),
               func.max(AlertEvent.triggered_at)).group_by(AlertEvent.rule_id)
    return {rid: {"total": n, "unread": int(u or 0), "last": last} for rid, n, u, last in db.execute(q)}


def serialize_rule(db: Session, r: AlertRule, counts: dict | None = None) -> dict:
    c = (counts or {}).get(r.id, {"total": 0, "unread": 0, "last": None})
    meta = (r.params or {}).get(svc.META_KEY) or {}
    return {
        "id": r.id,
        "name": r.name,
        "alert_type": r.alert_type,
        "params": svc.public_params(r.params),
        "enabled": r.enabled,
        "created_at": iso(r.created_at),
        "watching_since": iso(svc.rule_since(r)),
        "last_checked_at": iso(r.last_checked_at),
        "description_it": svc.describe(db, r.alert_type, r.params or {}, "it"),
        "description_en": svc.describe(db, r.alert_type, r.params or {}, "en"),
        "events_total": c["total"],
        "events_unread": c["unread"],
        "last_event_at": iso(c["last"]),
        "is_example": bool(meta.get("seed")),
    }


_REF_MODELS = {"price": PriceObservation, "trade": TradeFlowObservation, "report": Report, "news": NewsArticle,
               "regulation": RegulationItem, "tariff": TariffMeasure}


def _ref_provenance(db: Session, events: list[AlertEvent]) -> dict[tuple[str, int], dict]:
    """Source, original document and dates of what each event refers to (one query per kind)."""
    wanted: dict[str, set[int]] = defaultdict(set)
    for e in events:
        if e.ref_type in _REF_MODELS and e.ref_id:
            wanted[e.ref_type].add(e.ref_id)
    srcs = sources_by_id(db)
    out: dict[tuple[str, int], dict] = {}
    for kind, ids in wanted.items():
        model = _REF_MODELS[kind]
        for row in db.scalars(select(model).where(model.id.in_(list(ids)))):
            if kind == "report" or kind in ("news", "regulation"):
                url, pub = row.url, row.published_at
            elif kind == "tariff":
                url, pub = row.consult_url or row.legal_url or row.source_url, row.as_of
            else:
                url, pub = row.source_url, row.published_at
            out[(kind, row.id)] = {
                "source": source_brief(srcs.get(row.source_id)), "source_url": url, "published_at": iso(pub),
                "collected_at": iso(row.collected_at), "period_label": getattr(row, "period_label", None),
                "is_demo": bool(getattr(row, "is_demo", False)),
            }
    return out


def serialize_event(e: AlertEvent, rule: AlertRule | None, prov: dict | None) -> dict:
    link = e.link
    return {
        "id": e.id,
        "rule_id": e.rule_id,
        "rule_name": rule.name if rule else None,
        "alert_type": rule.alert_type if rule else None,
        "dedup_key": e.dedup_key,
        "triggered_at": iso(e.triggered_at),
        "severity": e.severity,
        "title_it": e.title_it,
        "title_en": e.title_en,
        "body_it": e.body_it,
        "body_en": e.body_en,
        "link": link,
        "link_internal": bool(link and link.startswith("/")),
        "ref_type": e.ref_type,
        "ref_id": e.ref_id,
        "read": e.read,
        "source": (prov or {}).get("source"),
        "source_url": (prov or {}).get("source_url"),
        "published_at": (prov or {}).get("published_at"),
        "collected_at": (prov or {}).get("collected_at"),
        "period_label": (prov or {}).get("period_label"),
        "is_demo": bool((prov or {}).get("is_demo")),
    }


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    alert_type: str
    params: dict = Field(default_factory=dict)
    enabled: bool = True


class RuleUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    params: dict | None = None
    enabled: bool | None = None


class PreviewIn(BaseModel):
    alert_type: str
    params: dict = Field(default_factory=dict)


def _get_rule(db: Session, rule_id: int) -> AlertRule:
    r = db.get(AlertRule, rule_id)
    if r is None:
        raise HTTPException(404, "Regola non trovata / Rule not found")
    return r


@router.get("/rules")
def list_rules(db: Session = Depends(get_db)):
    _ensure_seeded(db)
    rules = db.scalars(select(AlertRule).order_by(AlertRule.enabled.desc(), AlertRule.id)).all()
    counts = _event_counts(db)
    return {
        "rules": [serialize_rule(db, r, counts) for r in rules],
        "types": svc.ALERT_TYPES,
        "last_checked_at": iso(max((r.last_checked_at for r in rules if r.last_checked_at), default=None)),
    }


@router.post("/rules", status_code=201)
def create_rule(body: RuleIn, db: Session = Depends(get_db)):
    params = validate_params(db, body.alert_type, body.params)
    now = utcnow()
    rule = AlertRule(name=body.name.strip(), alert_type=body.alert_type, params=svc.start_watch(db, params, now),
                     enabled=body.enabled, created_at=now)
    db.add(rule)
    db.flush()
    new = svc.evaluate_rule(db, rule) if rule.enabled else 0
    db.commit()
    return {"rule": serialize_rule(db, rule, _event_counts(db)), "new_events": new}


@router.put("/rules/{rule_id}")
def update_rule(rule_id: int, body: RuleUpdate, db: Session = Depends(get_db)):
    rule = _get_rule(db, rule_id)
    now = utcnow()
    restart = False
    if body.name is not None:
        rule.name = body.name.strip()
    if body.params is not None:
        params = validate_params(db, rule.alert_type, body.params)
        if params != svc.public_params(rule.params):
            # New conditions watch from now on: data already in the database is not news for them.
            rule.params = svc.start_watch(db, params, now, rule.params)
            restart = True
    if body.enabled is not None and body.enabled != rule.enabled:
        rule.enabled = body.enabled
        if body.enabled:
            # Switched back on: what arrived while it was off is not reported in bulk.
            rule.params = svc.start_watch(db, svc.public_params(rule.params), now, rule.params)
            restart = True
    new = svc.evaluate_rule(db, rule) if (restart and rule.enabled) else 0
    db.commit()
    return {"rule": serialize_rule(db, rule, _event_counts(db)), "new_events": new}


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = _get_rule(db, rule_id)
    n = db.execute(delete(AlertEvent).where(AlertEvent.rule_id == rule.id)).rowcount or 0
    db.delete(rule)
    db.commit()
    return {"deleted": rule_id, "events_deleted": n}


@router.post("/rules/{rule_id}/test")
def test_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = _get_rule(db, rule_id)
    return svc.preview(db, rule.alert_type, rule.params or {}, rule=rule)


@router.post("/preview")
def preview_rule(body: PreviewIn, db: Session = Depends(get_db)):
    params = validate_params(db, body.alert_type, body.params)
    return svc.preview(db, body.alert_type, params)


@router.post("/evaluate")
def evaluate_now(db: Session = Depends(get_db)):
    svc.ensure_default_rules(db)
    res = svc.evaluate_all(db)
    db.commit()
    return {**res, "checked_at": iso(utcnow())}


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


@router.get("/events")
def list_events(
    status: str = Query("all", pattern="^(all|unread)$"),
    rule_id: int | None = Query(None),
    alert_type: str | None = Query(None),
    severity: str | None = Query(None, pattern="^(info|warning|critical)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    _ensure_seeded(db)
    E = AlertEvent
    conds = []
    if status == "unread":
        conds.append(E.read.is_(False))
    if rule_id is not None:
        conds.append(E.rule_id == rule_id)
    if alert_type:
        if alert_type not in svc.ALERT_TYPES:
            raise HTTPException(422, "Tipo di avviso sconosciuto / Unknown alert type")
        conds.append(E.rule_id.in_(select(AlertRule.id).where(AlertRule.alert_type == alert_type)))
    if severity:
        conds.append(E.severity == severity)
    total = db.scalar(select(func.count()).select_from(E).where(*conds)) or 0
    rows = db.scalars(select(E).where(*conds).order_by(E.read.asc(), E.triggered_at.desc(), E.id.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    rules = {r.id: r for r in db.scalars(select(AlertRule))}
    prov = _ref_provenance(db, rows)
    unread = db.scalar(select(func.count()).select_from(E).where(E.read.is_(False))) or 0
    return {
        "items": [serialize_event(e, rules.get(e.rule_id), prov.get((e.ref_type, e.ref_id))) for e in rows],
        "total": total,
        "unread": unread,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if total else 0,
        "rules": [{"id": r.id, "name": r.name, "alert_type": r.alert_type} for r in rules.values()],
    }


class ReadIn(BaseModel):
    read: bool = True


@router.put("/events/{event_id}")
def mark_event(event_id: int, body: ReadIn, db: Session = Depends(get_db)):
    e = db.get(AlertEvent, event_id)
    if e is None:
        raise HTTPException(404, "Avviso non trovato / Alert not found")
    e.read = body.read
    db.commit()
    return {"id": e.id, "read": e.read}


class ReadAllIn(BaseModel):
    rule_id: int | None = None


@router.post("/events/read-all")
def mark_all(body: ReadAllIn, db: Session = Depends(get_db)):
    stmt = update(AlertEvent).where(AlertEvent.read.is_(False))
    if body.rule_id is not None:
        stmt = stmt.where(AlertEvent.rule_id == body.rule_id)
    n = db.execute(stmt.values(read=True)).rowcount or 0
    db.commit()
    return {"marked": n}


@router.get("/unread-count")
def unread_count(db: Session = Depends(get_db)):
    _ensure_seeded(db)
    E = AlertEvent
    unread, warn, latest = db.execute(select(
        func.count(), func.sum(case((E.severity.in_(["warning", "critical"]), 1), else_=0)), func.max(E.triggered_at),
    ).where(E.read.is_(False))).one()
    return {"unread": unread or 0, "unread_warning": int(warn or 0), "latest_unread_at": iso(latest)}


# ---------------------------------------------------------------------------
# Editor options: only what has data
# ---------------------------------------------------------------------------


def _priority(iso3: str | None) -> int:
    try:
        return PRIORITY_ISO3.index(iso3)  # type: ignore[arg-type]
    except ValueError:
        return len(PRIORITY_ISO3)


def price_options(db: Session, *, monthly_only: bool) -> list[dict]:
    """Price series combinations (type, origin, variety, market, colour) present in real current rows."""
    from .prices import bulk_unit_value_clause

    M = PriceObservation
    conds = [M.is_current.is_(True), M.is_demo.is_(False), bulk_unit_value_clause(M), M.origin_iso3.is_not(None)]
    if monthly_only:
        conds.append(M.frequency == "M")
    q = (select(M.price_type, M.origin_iso3, M.variety, M.market_iso3, M.color_grade, func.count(),
                func.max(M.period_label), func.min(M.period_label))
         .where(*conds).group_by(M.price_type, M.origin_iso3, M.variety, M.market_iso3, M.color_grade))
    out = [{"price_type": pt, "origin": o, "variety": v, "market": mk, "color_grade": c, "count": n,
            "last_period": last, "first_period": first}
           for pt, o, v, mk, c, n, last, first in db.execute(q)]
    out.sort(key=lambda x: (x["price_type"], _priority(x["origin"]), x["origin"], -x["count"]))
    return out


def trade_options(db: Session) -> list[dict]:
    """Reporters with their flows, frequencies and partners (real current rows, monthly / annual)."""
    T = TradeFlowObservation
    q = (select(T.reporter_iso3, T.flow, T.frequency, T.partner_iso3, func.count(), func.max(T.period_label))
         .where(T.is_current.is_(True), T.is_demo.is_(False), T.frequency.in_(["A", "M"]), T.hs_code.like("0409%"))
         .group_by(T.reporter_iso3, T.flow, T.frequency, T.partner_iso3))
    reps: dict[str, dict] = {}
    for rep, flow, freq, partner, n, last in db.execute(q):
        r = reps.setdefault(rep, {"iso3": rep, "flows": {}})
        f = r["flows"].setdefault(flow, {"freqs": set(), "partners": set(), "rows": 0, "last_period": None})
        f["freqs"].add(freq)
        f["rows"] += n
        if f["last_period"] is None or (last or "") > f["last_period"]:
            f["last_period"] = last
        if partner == "EXTRA_EU" or partner == "WLD":
            f["partners"].add("WLD")
        elif partner not in TRADE_PSEUDO:
            f["partners"].add(partner)
    out = []
    for r in reps.values():
        flows = {}
        for k, f in r["flows"].items():
            partners = sorted(f["partners"], key=lambda x: (x != "WLD", _priority(x), x))
            flows[k] = {"freqs": sorted(f["freqs"], key=lambda x: "MA".index(x)), "partners": partners,
                        "rows": f["rows"], "last_period": f["last_period"]}
        out.append({"iso3": r["iso3"], "flows": flows})
    out.sort(key=lambda r: (r["iso3"] not in ("EU27", "ITA", "USA", "DEU"), _priority(r["iso3"]), r["iso3"]))
    return out


@router.get("/options")
def options(db: Session = Depends(get_db)):
    srcs = sources_by_id(db)
    R = Report
    rep_q = (select(R.source_id, func.count(), func.max(R.published_at)).where(R.is_demo.is_(False))
             .group_by(R.source_id))
    report_sources = []
    for sid, n, last in db.execute(rep_q):
        s = srcs.get(sid)
        if s is not None:
            report_sources.append({**source_brief(s), "reports": n, "latest_published_at": iso(last)})
    report_sources.sort(key=lambda x: (x["reliability"] != "official", x["name"]))

    N = NewsArticle
    news_countries: dict[str, int] = defaultdict(int)
    for lst in db.scalars(select(N.countries).where(N.is_demo.is_(False), N.duplicate_of_id.is_(None))):
        for c in set(lst or []):
            news_countries[c] += 1
    news_total = db.scalar(select(func.count()).select_from(N).where(N.is_demo.is_(False))) or 0

    G = RegulationItem
    juris = dict(db.execute(select(G.jurisdiction, func.count()).where(G.is_demo.is_(False)).group_by(G.jurisdiction)).all())
    tjuris = dict(db.execute(select(TariffMeasure.jurisdiction, func.count()).where(TariffMeasure.is_demo.is_(False))
                             .group_by(TariffMeasure.jurisdiction)).all())
    types = db.execute(select(G.jurisdiction, G.doc_type, func.count()).where(G.is_demo.is_(False))
                       .group_by(G.jurisdiction, G.doc_type)).all()
    reg_countries: dict[str, int] = defaultdict(int)
    for lst in db.scalars(select(G.countries).where(G.is_demo.is_(False))):
        for c in set(lst or []):
            reg_countries[c] += 1

    def ranked(d: dict[str, int]) -> list[dict]:
        return [{"iso3": k, "count": n} for k, n in sorted(d.items(), key=lambda kv: (_priority(kv[0]), -kv[1], kv[0]))]

    return {
        "price": price_options(db, monthly_only=True),
        "report_sources": report_sources,
        "news": {"countries": ranked(news_countries), "articles": news_total},
        "regulation": {
            "jurisdictions": [{"key": k, "count": juris.get(k, 0), "tariffs": tjuris.get(k, 0)}
                              for k in sorted(set(juris) | set(tjuris), key=lambda j: (j not in ("EU", "US"), j))],
            "doc_types": [{"jurisdiction": j, "key": t, "count": n} for j, t, n in sorted(types, key=lambda x: (x[0], -x[2]))],
            "countries": ranked(reg_countries),
        },
        "trade": trade_options(db),
        "examples": [{"name": d["name"], "alert_type": d["alert_type"], "params": d["params"]} for d in svc.DEFAULT_RULES],
    }
