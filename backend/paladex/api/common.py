"""Shared API helpers: demo-data switch, freshness, serialisation."""
from __future__ import annotations

import calendar
import json
import re
from datetime import date, datetime, timedelta
from enum import Enum

from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AppSetting, Source, utcnow


def get_setting(session: Session, key: str, default=None):
    row = session.get(AppSetting, key)
    return default if row is None else row.value


def set_setting(session: Session, key: str, value) -> None:
    row = session.get(AppSetting, key)
    if row is None:
        session.add(AppSetting(key=key, value=value))
    else:
        row.value = value


def show_demo(session: Session) -> bool:
    """Demo rows are hidden unless the user switched them on."""
    return bool(get_setting(session, "show_demo", False))


def demo_clause(model, session: Session):
    """SQLAlchemy filter: real rows only, or real + demo if demo display is on."""
    if show_demo(session):
        return model.is_demo.in_([True, False])
    return model.is_demo.is_(False)


def _period_end(start: date, label: str | None) -> date:
    """Last day of the period starting on `start` labelled `label` ('2026', '2026-Q3', '2026-09',
    '2026-W44'); the start itself for any other label (a day, a source-specific week)."""
    lab = (label or "").strip().upper()
    if re.fullmatch(r"\d{4}", lab):
        return date(start.year, 12, 31)
    if m := re.fullmatch(r"\d{4}-?Q([1-4])", lab):
        last_month = int(m[1]) * 3
        return date(start.year, last_month, calendar.monthrange(start.year, last_month)[1])
    if re.fullmatch(r"\d{4}-\d{2}", lab):
        return date(start.year, start.month, calendar.monthrange(start.year, start.month)[1])
    if re.fullmatch(r"\d{4}-W\d{2}", lab):
        return start + timedelta(days=6)
    return start


def source_reference_date(source: Source) -> date | None:
    """The date a source's newest data is judged from: its newest publication date. A source that
    gives none is dated by when new data last reached us, unless that data was already older than
    one publication cycle when it arrived (a first collection, or a source that stopped publishing:
    ISMEA's June prices collected in November): then by the end of its newest period, which no
    publication can precede. Old data must never look current."""
    if source.latest_published_at:
        return source.latest_published_at
    collected = source.last_new_data_at.date() if source.last_new_data_at else None
    end = _period_end(source.latest_period_start, source.latest_period_label) if source.latest_period_start else None
    if end is not None and (collected is None or (source.expected_max_age_days
                                                  and (collected - end).days > source.expected_max_age_days)):
        return end
    return collected


def freshness(source: Source, today: date | None = None) -> dict:
    """How current is a source's newest data, judged against its own publication rhythm.

    status: "current"  – newest publication within the expected cycle
            "aging"    – up to 1.5x the expected cycle
            "stale"    – older than that (shown as a warning; data is NOT presented as current)
            "never"    – nothing collected yet
            "unknown"  – no expected cycle defined
    """
    today = today or date.today()
    ref = source_reference_date(source)
    if ref is None:
        return {"status": "never", "age_days": None, "reference_date": None}
    age = (today - ref).days
    exp = source.expected_max_age_days
    if not exp:
        status = "unknown"
    elif age <= exp:
        status = "current"
    elif age <= exp * 1.5:
        status = "aging"
    else:
        status = "stale"
    return {"status": status, "age_days": age, "reference_date": ref.isoformat()}


def iso(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def _json_default(o):
    """What FastAPI's encoder does for the non-JSON values our answers contain."""
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    if isinstance(o, (set, frozenset, tuple)):
        return list(o)
    if isinstance(o, Enum):
        return o.value
    raise TypeError(f"not JSON serialisable: {type(o).__name__}")


class FastJSONResponse(JSONResponse):
    """The same bytes as FastAPI's default answer, written in one pass by the json module.

    FastAPI first walks every value of a returned dict through `jsonable_encoder` (half a second
    for the 900,000 values of a full customs price history) before writing it; an endpoint that
    returns this response skips that walk. Dates become ISO strings, as before."""

    def render(self, content) -> bytes:
        return json.dumps(content, ensure_ascii=False, allow_nan=False, indent=None, separators=(",", ":"),
                          default=_json_default).encode("utf-8")


def json_response(content) -> FastJSONResponse:
    return FastJSONResponse(content)


def source_brief(source: Source | None) -> dict | None:
    if source is None:
        return None
    return {"key": source.key, "name": source.name, "name_en": source.name_en, "publisher": source.publisher,
            "reliability": source.reliability, "homepage": source.homepage}


def sources_by_id(session: Session) -> dict[int, Source]:
    return {s.id: s for s in session.scalars(select(Source))}


def age_hours(dt: datetime | None) -> float | None:
    if dt is None:
        return None
    return round((utcnow() - dt).total_seconds() / 3600, 1)
