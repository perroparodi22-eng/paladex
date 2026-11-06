"""Append-only, revision-aware storage of observations.

`record()` is the ONLY way collectors write numeric observations. Behaviour:

* new series_key                     -> insert revision 1                      -> "new"
* same series_key, identical values  -> only bump `last_seen_at`               -> "unchanged"
* same series_key, different values  -> keep old row (is_current=False), insert
                                        revision n+1 with supersedes_id          -> "revised"

So historical observations are never overwritten, and a revision by the publisher is
visible as such.

When the current row of a series is a person's correction (reliability ``user``, written by
services/corrections.py with `add_revision`), a re-read of the source is compared with the OFFICIAL
values the correction replaced (``extra.correction.official_hash``), not with the corrected ones:

* the same official values         -> "unchanged": the correction stays current; the official
                                      revision's `last_seen_at` is bumped (it is still published)
* other values (the source moved)  -> "revised": the source's new value becomes current over the
                                      correction, the correction event is marked
                                      `superseded_by_source` and a notice is raised
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    PriceObservation,
    ProductionStat,
    TradeFlowObservation,
    WeatherObservation,
    utcnow,
)

Outcome = Literal["new", "unchanged", "revised"]

# Fields whose change makes a new revision. `data_status` is included so that a figure
# promoted from "provisional" to "published" (or downgraded to "estimate") is recorded as a
# revision too, keeping the history of what was known when.
VALUE_FIELDS: dict[type, tuple[str, ...]] = {
    PriceObservation: ("price_low", "price_high", "price_value", "currency", "unit", "volume_kg", "data_status"),
    TradeFlowObservation: ("net_weight_kg", "value", "currency", "value_basis", "data_status"),
    ProductionStat: ("value", "unit", "flag_raw", "data_status"),
    WeatherObservation: ("temp_mean_c", "precip_mm", "temp_anomaly_c", "precip_anomaly_pct", "data_status"),
}


def _canon(v):
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def value_hash(model: type, fields: dict) -> str:
    payload = {k: _canon(fields.get(k)) for k in VALUE_FIELDS[model]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _current_rows(session: Session, model: type, source_id: int, series_key: str, is_demo: bool) -> list:
    """The current row(s) of a series. Only `series_key` is filtered in SQL, the rest in Python: given
    all four terms, SQLite (no table statistics) used the `is_demo` index, which matches every real row,
    so each write scanned the whole table (30 ms per row on a 53k-row trade table, growing with it: a
    Comext pull of all member states took two minutes per reporter). By series_key: 0.02 ms."""
    rows = session.scalars(select(model).where(model.series_key == series_key)).all()
    return [r for r in rows if r.source_id == source_id and r.is_current and bool(r.is_demo) == bool(is_demo)]


def correction_of(row) -> dict | None:
    """The `extra.correction` record of a row written for a person's correction, else None."""
    if row is None or getattr(row, "reliability", None) != "user":
        return None
    extra = row.extra if isinstance(row.extra, dict) else None
    corr = extra.get("correction") if extra else None
    return corr if isinstance(corr, dict) and corr.get("event_id") else None


def current_row(session: Session, model: type, source_id: int, series_key: str, is_demo: bool = False):
    """The current row of a series (the newest revision if, abnormally, several are current)."""
    rows = _current_rows(session, model, source_id, series_key, is_demo)
    return max(rows, key=lambda r: (r.revision or 1, r.id)) if rows else None


def add_revision(session: Session, model: type, current, **fields):
    """Insert a new current revision of `current`'s series with the given column values (used by
    services/corrections.py for a person's correction and for undoing it). `current` is kept, with
    `is_current` cleared, exactly as when the source revises a figure."""
    if model not in VALUE_FIELDS:
        raise TypeError(f"Unsupported observation model {model!r}")
    now = utcnow()
    fields.setdefault("collected_at", now)
    row = model(source_id=current.source_id, series_key=current.series_key, value_hash=value_hash(model, fields),
                is_demo=current.is_demo, last_seen_at=now, **fields)
    current.is_current = False
    row.revision = (current.revision or 1) + 1
    row.supersedes_id = current.id
    session.add(row)
    session.flush()
    return row


def _fill_late_metadata(row, fields: dict) -> None:
    # Late metadata (e.g. publication date discovered later) may be filled, never changed.
    for k in ("published_at", "source_url", "raw_document_id"):
        if getattr(row, k) is None and fields.get(k) is not None:
            setattr(row, k, fields[k])


def _record_over_correction(session: Session, model: type, current, corr: dict, vh: str,
                            fields: dict) -> tuple[Outcome, object]:
    """`record()` when the current row is a person's correction (see the module docstring)."""
    now = utcnow()
    if vh == corr.get("official_hash"):
        official = session.get(model, corr["official_row_id"]) if corr.get("official_row_id") else None
        if official is not None:
            official.last_seen_at = now
            _fill_late_metadata(official, fields)
        return "unchanged", current
    row = model(source_id=current.source_id, series_key=current.series_key, value_hash=vh, is_demo=current.is_demo,
                collected_at=now, last_seen_at=now, **fields)
    current.is_current = False
    row.revision = (current.revision or 1) + 1
    row.supersedes_id = current.id
    session.add(row)
    session.flush()
    from .corrections import on_source_superseded

    on_source_superseded(session, model, current, row, corr)
    return "revised", row


def record(session: Session, model: type, *, source_id: int, series_key: str, is_demo: bool = False, **fields) -> tuple[Outcome, object]:
    if model not in VALUE_FIELDS:
        raise TypeError(f"Unsupported observation model {model!r}")
    vh = value_hash(model, fields)
    current = next(iter(_current_rows(session, model, source_id, series_key, is_demo)), None)
    corr = correction_of(current)
    if corr is not None:
        return _record_over_correction(session, model, current, corr, vh, fields)
    now = utcnow()
    if current is not None and current.value_hash == vh:
        current.last_seen_at = now
        _fill_late_metadata(current, fields)
        return "unchanged", current

    row = model(
        source_id=source_id,
        series_key=series_key,
        value_hash=vh,
        is_demo=is_demo,
        collected_at=now,
        last_seen_at=now,
        **fields,
    )
    if current is None:
        row.revision = 1
        session.add(row)
        session.flush()
        return "new", row
    current.is_current = False
    row.revision = (current.revision or 1) + 1
    row.supersedes_id = current.id
    session.add(row)
    session.flush()
    return "revised", row


def retire(session: Session, model: type, *, source_id: int, series_key: str, is_demo: bool = False) -> int:
    """Withdraw a series the source no longer publishes (or that no longer qualifies, e.g. a derived
    unit value whose trade row lost its weight). The current row is kept with its values untouched;
    only `is_current` is cleared, the same flag flip `record()` does on a revision, so history stays
    append-only and the last published value remains in the archive. Returns the rows retired (0 when
    the series has no current row)."""
    if model not in VALUE_FIELDS:
        raise TypeError(f"Unsupported observation model {model!r}")
    rows = _current_rows(session, model, source_id, series_key, is_demo)
    for row in rows:
        row.is_current = False
    if rows:
        session.flush()
        corrected = [(r, c) for r in rows if (c := correction_of(r)) is not None]
        if corrected:
            from .corrections import on_source_withdrawn

            for r, c in corrected:
                on_source_withdrawn(session, model, r, c)
    return len(rows)


# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------

KG_PER_UNIT = {
    "kg": 1.0,
    "g": 0.001,
    "lb": 0.45359237,
    "t": 1000.0,
    "tonne": 1000.0,
    "100kg": 100.0,
    "q": 100.0,          # quintale (Italian price lists)
    "cwt": 45.359237,    # US hundredweight (100 lb)
}


def per_kg(price: float, unit: str) -> float:
    """Convert a price quoted per `unit` of mass into a price per kg (same currency)."""
    try:
        return price / KG_PER_UNIT[unit]
    except KeyError as exc:  # pragma: no cover - programming error
        raise ValueError(f"Unknown mass unit {unit!r}") from exc
