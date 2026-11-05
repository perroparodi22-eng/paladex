"""Data quality: open/resolved issues, a summary for the "Fonti" page, run checks on demand,
and the list of optional API keys with plain-language instructions."""
from __future__ import annotations

from collections import Counter
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from .. import envfile
from ..config import get_settings
from ..db import get_db
from ..enums import RunStatus, Severity
from ..models import (
    DataQualityIssue,
    NewsArticle,
    PriceObservation,
    ProductionStat,
    RegulationItem,
    Report,
    Source,
    SupplierQuote,
    TradeFlowObservation,
    utcnow,
)
from ..services import quality as quality_service
from .common import freshness, get_setting, iso, show_demo, source_brief, sources_by_id

router = APIRouter(tags=["quality"])

_SEVERITY_ORDER = case(
    (DataQualityIssue.severity == Severity.CRITICAL.value, 0),
    (DataQualityIssue.severity == Severity.WARNING.value, 1),
    else_=2,
)


def serialize_issue(i: DataQualityIssue, srcs: dict[int, Source]) -> dict:
    details = i.details or {}
    return {
        "id": i.id,
        "type": i.issue_type,
        "severity": i.severity,
        "status": "open" if i.resolved_at is None else "resolved",
        "message_it": i.message_it,
        "message_en": i.message_en,
        "source": source_brief(srcs.get(i.source_id)) if i.source_id else None,
        "source_keys": details.get("source_keys") or ([details["source_key"]] if details.get("source_key") else []),
        "entity_type": i.entity_type,
        "entity_id": i.entity_id,
        "link": details.get("link"),
        "details": details,
        "detected_at": iso(i.detected_at),
        "last_seen_at": iso(i.last_seen_at),
        "resolved_at": iso(i.resolved_at),
    }


def _issue_mentions_source(i: DataQualityIssue, key: str, source_id: int | None) -> bool:
    if source_id is not None and i.source_id == source_id:
        return True
    d = i.details or {}
    return d.get("source_key") == key or key in (d.get("source_keys") or [])


@router.get("/quality/issues")
def list_issues(
    status: Literal["open", "resolved", "all"] = "open",
    severity: str | None = Query(None, description="info | warning | critical (comma-separated allowed)"),
    issue_type: str | None = Query(None, alias="type", description="QualityIssueType (comma-separated allowed)"),
    source: str | None = Query(None, description="source key"),
    limit: int = Query(200, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    q = select(DataQualityIssue)
    if status == "open":
        q = q.where(DataQualityIssue.resolved_at.is_(None))
    elif status == "resolved":
        q = q.where(DataQualityIssue.resolved_at.is_not(None))
    if severity:
        q = q.where(DataQualityIssue.severity.in_([s.strip() for s in severity.split(",") if s.strip()]))
    if issue_type:
        q = q.where(DataQualityIssue.issue_type.in_([t.strip() for t in issue_type.split(",") if t.strip()]))
    if status == "resolved":
        q = q.order_by(DataQualityIssue.resolved_at.desc(), DataQualityIssue.id.desc())
    else:
        q = q.order_by(_SEVERITY_ORDER, DataQualityIssue.last_seen_at.desc(), DataQualityIssue.id.desc())
    rows = list(db.scalars(q))
    srcs = sources_by_id(db)
    if source:
        sid = next((s.id for s in srcs.values() if s.key == source), None)
        rows = [i for i in rows if _issue_mentions_source(i, source, sid)]
    counts = Counter(i.severity for i in rows)
    return {
        "total": len(rows),
        "counts": {s.value: counts.get(s.value, 0) for s in Severity},
        "issues": [serialize_issue(i, srcs) for i in rows[:limit]],
        "last_check_at": get_setting(db, quality_service.LAST_RUN_SETTING),
    }


def _demo_counts(db: Session) -> dict[str, int]:
    out = {}
    for label, model in (("prices", PriceObservation), ("trade", TradeFlowObservation), ("production", ProductionStat),
                         ("news", NewsArticle), ("reports", Report), ("regulations", RegulationItem),
                         ("quotes", SupplierQuote)):
        out[label] = db.scalar(select(func.count()).select_from(model).where(model.is_demo.is_(True))) or 0
    return out


@router.get("/quality/summary")
def summary(db: Session = Depends(get_db)):
    from .meta import _collect_state_public

    sources = [s for s in db.scalars(select(Source)) if s.key != "demo" and s.kind != "manual"]
    enabled = [s for s in sources if s.enabled]
    settings = get_settings()
    fresh = Counter(freshness(s)["status"] for s in enabled)
    errors = sum(1 for s in enabled if s.last_run_status == RunStatus.FAILED.value)
    key_missing = sum(1 for s in enabled if s.requires_key and not getattr(settings, s.requires_key, None))
    offline = sum(1 for s in enabled if s.last_run_status == RunStatus.OFFLINE.value)
    last_check = max((s.last_run_at for s in sources if s.last_run_at), default=None)
    last_success = max((s.last_success_at for s in sources if s.last_success_at), default=None)
    last_new = max((s.last_new_data_at for s in sources if s.last_new_data_at), default=None)

    open_rows = db.execute(
        select(DataQualityIssue.severity, DataQualityIssue.issue_type, func.count())
        .where(DataQualityIssue.resolved_at.is_(None))
        .group_by(DataQualityIssue.severity, DataQualityIssue.issue_type)
    ).all()
    by_sev: Counter = Counter()
    by_type: Counter = Counter()
    for sev, typ, n in open_rows:
        by_sev[sev] += n
        by_type[typ] += n
    resolved_30d = db.scalar(
        select(func.count()).select_from(DataQualityIssue)
        .where(DataQualityIssue.resolved_at.is_not(None), DataQualityIssue.resolved_at >= utcnow() - timedelta(days=30))
    ) or 0

    demo_rows = _demo_counts(db)
    return {
        "sources": {
            "total": len(sources), "enabled": len(enabled), "disabled": len(sources) - len(enabled),
            "current": fresh.get("current", 0), "aging": fresh.get("aging", 0), "stale": fresh.get("stale", 0),
            "never": fresh.get("never", 0), "unknown": fresh.get("unknown", 0),
            "errors": errors, "key_missing": key_missing, "offline": offline,
        },
        "last_check_at": iso(last_check),
        "last_success_at": iso(last_success),
        "last_new_data_at": iso(last_new),
        "issues": {
            "open": sum(by_sev.values()),
            "critical": by_sev.get(Severity.CRITICAL.value, 0),
            "warning": by_sev.get(Severity.WARNING.value, 0),
            "info": by_sev.get(Severity.INFO.value, 0),
            "by_type": dict(by_type),
            "resolved_last_30_days": resolved_30d,
        },
        "quality_checked_at": get_setting(db, quality_service.LAST_RUN_SETTING),
        "collect": _collect_state_public(),
        "demo": {"visible": show_demo(db), "rows": demo_rows, "total": sum(demo_rows.values())},
    }


@router.post("/quality/run")
def run_now(db: Session = Depends(get_db)):
    result = quality_service.run_checks(db)
    db.commit()
    return result


@router.get("/quality/keys")
def api_keys(db: Session = Depends(get_db)):
    """Optional API keys: which sources need them, whether they are set, how to get them.
    Never returns the key values themselves."""
    settings = get_settings()
    optional = quality_service._optional_key_sources()
    by_attr: dict[str, list[dict]] = {}
    for s in db.scalars(select(Source).where(Source.requires_key.is_not(None)).order_by(Source.name)):
        by_attr.setdefault(s.requires_key, []).append({"key": s.key, "name": s.name, "name_en": s.name_en, "optional": s.key in optional})
    out = []
    for attr, srcs in by_attr.items():
        help_ = quality_service.KEY_HELP.get(attr, {})
        out.append({
            "setting": attr,
            "env_var": quality_service.env_var_for(attr),
            "configured": bool(getattr(settings, attr, None)),
            "service": help_.get("service"),
            "signup_url": help_.get("signup_url"),
            "help_it": help_.get("it"),
            "help_en": help_.get("en"),
            "sources": srcs,
        })
    return {"keys": out, "env_file": ".env"}


class KeyValue(BaseModel):
    value: str = Field(default="", max_length=400)


@router.put("/quality/keys/{setting}")
def save_api_key(setting: str, body: KeyValue):
    """Save a pasted key in the local `.env` file (this computer only) and use it right away.

    Only the known optional keys (and the AI provider) can be written. The value is never
    returned. The JSON body means a web page elsewhere cannot submit it from the owner's browser
    (a cross-site JSON request needs a CORS permission this app never grants)."""
    allowed = set(quality_service.KEY_HELP) | {"llm_provider"}
    if setting not in allowed:
        raise HTTPException(404, "unknown key")
    value = body.value.strip()
    if setting == "llm_provider":
        if value not in envfile.LLM_PROVIDERS:
            raise HTTPException(422, "provider must be anthropic, openai or none")
    elif value and not envfile.VALUE_RE.match(value):
        raise HTTPException(422, "La chiave contiene spazi o caratteri non validi: incollare solo la chiave. / "
                                 "The key contains spaces or invalid characters: paste the key only.")
    envfile.set_env_value(quality_service.env_var_for(setting), value or None)
    get_settings.cache_clear()
    return {"setting": setting, "configured": bool(getattr(get_settings(), setting, None))}
