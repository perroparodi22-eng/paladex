"""Append-only, revision-aware storage of observations.

`record()` is the ONLY way collectors write numeric observations. Behaviour:

* new series_key                     -> insert revision 1                      -> "new"
* same series_key, identical values  -> only bump `last_seen_at`               -> "unchanged"
* same series_key, different values  -> keep old row (is_current=False), insert
                                        revision n+1 with supersedes_id          -> "revised"

So historical observations are never overwritten, and a revision by the publisher is
visible as such.
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

VALUE_FIELDS: dict[type, tuple[str, ...]] = {
    PriceObservation: ("price_low", "price_high", "price_value", "currency", "unit", "volume_kg"),
    TradeFlowObservation: ("net_weight_kg", "value", "currency", "value_basis"),
    ProductionStat: ("value", "unit", "flag_raw"),
    WeatherObservation: ("temp_mean_c", "precip_mm", "temp_anomaly_c", "precip_anomaly_pct"),
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


def record(session: Session, model: type, *, source_id: int, series_key: str, is_demo: bool = False, **fields) -> tuple[Outcome, object]:
    if model not in VALUE_FIELDS:
        raise TypeError(f"Unsupported observation model {model!r}")
    vh = value_hash(model, fields)
    current = session.scalars(
        select(model).where(
            model.source_id == source_id,
            model.series_key == series_key,
            model.is_current.is_(True),
            model.is_demo.is_(is_demo),
        )
    ).first()
    now = utcnow()
    if current is not None and current.value_hash == vh:
        current.last_seen_at = now
        # Late metadata (e.g. publication date discovered later) may be filled, never changed.
        for k in ("published_at", "source_url", "raw_document_id"):
            if getattr(current, k) is None and fields.get(k) is not None:
                setattr(current, k, fields[k])
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
