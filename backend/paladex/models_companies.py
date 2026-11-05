"""Company-level honey trade records published by official sources (`company_records`).

One row = one company, as an official source publishes it, for one role, one product code and one
period: e.g. "NECTARBEE S.A., exporter of NCM 0409, 2025: US$ 15,571,168.32 FOB" (Uruguay XXI), or
"NELSON HONEY UK LIMITED imported commodity 04090000 in January 2026" (HMRC, no figures).

Rules (docs/DEVELOPING.md, and the brief of the Companies page):

* Only official sources that publish company-level information. Nothing is inferred from news,
  marketing or commercial aggregators, and a company is never matched or merged across sources.
* `company_name` and `location` are stored exactly as published (whitespace collapsed). Private
  persons (sole traders) can appear in official lists: only the name and the location as published
  are stored, never a tax or personal identification number.
* `measure_kind` says what the figure is, and nothing is converted into something else:
  ``value_band`` (``value_min``/``value_max`` + currency, shown as a band), ``exact_value``
  (``value`` + currency + ``value_basis``), ``exact_volume`` (``volume_kg``), ``rank`` (a position
  the source itself publishes) or ``none`` (a register or list without figures: never ranked).
* Append-only like the observations (``services.ingest``): a changed figure becomes a new revision
  (the old row is kept with ``is_current=False``); a record the source no longer publishes is
  retired (``is_current=False``), never deleted.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base
from .models import utcnow

Outcome = Literal["new", "unchanged", "revised"]


class CompanyRole(StrEnum):
    EXPORTER = "exporter"                        # shipped the product in the period (customs records)
    IMPORTER = "importer"                        # brought the product in in the period (customs records)
    REGISTERED_EXPORTER = "registered_exporter"  # on an official register of authorised exporters


class MeasureKind(StrEnum):
    VALUE_BAND = "value_band"
    EXACT_VALUE = "exact_value"
    EXACT_VOLUME = "exact_volume"
    RANK = "rank"
    NONE = "none"


class CompanyRecord(Base):
    __tablename__ = "company_records"
    __table_args__ = (
        Index("ix_company_lookup", "country_iso3", "role", "is_current"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    raw_document_id: Mapped[int | None] = mapped_column(ForeignKey("raw_documents.id"))
    series_key: Mapped[str] = mapped_column(String(400), index=True)   # identity of "who + role + what + when"
    value_hash: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    supersedes_id: Mapped[int | None] = mapped_column(Integer)

    country_iso3: Mapped[str] = mapped_column(String(3), index=True)   # country of the publishing authority
    company_name: Mapped[str] = mapped_column(String(300))             # as published
    location: Mapped[str | None] = mapped_column(String(200))          # as published (town, region...), if any
    role: Mapped[str] = mapped_column(String(24), index=True)          # CompanyRole
    hs_code: Mapped[str] = mapped_column(String(14))                   # code as the source states it ("0409", "04090000")

    measure_kind: Mapped[str] = mapped_column(String(16))              # MeasureKind
    value: Mapped[float | None] = mapped_column(Float)                 # exact value, as published
    value_min: Mapped[float | None] = mapped_column(Float)             # band lower bound (None = open)
    value_max: Mapped[float | None] = mapped_column(Float)             # band upper bound (None = open)
    currency: Mapped[str | None] = mapped_column(String(3))
    value_basis: Mapped[str | None] = mapped_column(String(10))        # FOB / CIF
    volume_kg: Mapped[float | None] = mapped_column(Float)
    rank: Mapped[int | None] = mapped_column(Integer)                  # only when the source publishes a rank

    period_start: Mapped[date] = mapped_column(Date, index=True)
    period_end: Mapped[date] = mapped_column(Date)
    period_label: Mapped[str] = mapped_column(String(40))              # "2025", "2026-08", register date
    frequency: Mapped[str] = mapped_column(String(10))                 # A, M, YTD, register

    published_at: Mapped[date | None] = mapped_column(Date)
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    source_url: Mapped[str | None] = mapped_column(String(1000))
    data_status: Mapped[str] = mapped_column(String(20))               # DataStatus
    reliability: Mapped[str] = mapped_column(String(20))               # Reliability
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    extra: Mapped[dict | None] = mapped_column(JSON)


# Fields whose change makes a new revision. Provenance (links, dates) and `extra` are metadata.
VALUE_FIELDS: tuple[str, ...] = (
    "company_name", "location", "role", "hs_code", "measure_kind", "value", "value_min", "value_max", "currency",
    "value_basis", "volume_kg", "rank", "period_start", "period_end", "period_label", "data_status",
)
# Filled on an unchanged row only when still empty (late provenance), never overwritten.
_FILL_FIELDS = ("published_at", "source_url", "raw_document_id")


def _canon(v):
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def value_hash(fields: dict) -> str:
    payload = {k: _canon(fields.get(k)) for k in VALUE_FIELDS}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _current(session: Session, source_id: int, series_key: str, is_demo: bool) -> list[CompanyRecord]:
    rows = session.scalars(select(CompanyRecord).where(CompanyRecord.series_key == series_key)).all()
    return [r for r in rows if r.source_id == source_id and r.is_current and bool(r.is_demo) == bool(is_demo)]


def record_company(session: Session, *, source_id: int, series_key: str, is_demo: bool = False,
                   **fields) -> tuple[Outcome, CompanyRecord]:
    """Append-only write of one company record (see the module docstring)."""
    kind = fields.get("measure_kind")
    if kind not in {k.value for k in MeasureKind}:
        raise ValueError(f"unknown measure_kind {kind!r}")
    if fields.get("role") not in {r.value for r in CompanyRole}:
        raise ValueError(f"unknown role {fields.get('role')!r}")
    if kind == MeasureKind.NONE and any(fields.get(k) is not None for k in ("value", "value_min", "value_max", "volume_kg", "rank")):
        raise ValueError("a record without figures (measure_kind 'none') cannot carry a value or a rank")
    vh = value_hash(fields)
    current = next(iter(_current(session, source_id, series_key, is_demo)), None)
    now = utcnow()
    if current is not None and current.value_hash == vh:
        current.last_seen_at = now
        for k in _FILL_FIELDS:
            if getattr(current, k) is None and fields.get(k) is not None:
                setattr(current, k, fields[k])
        return "unchanged", current
    row = CompanyRecord(source_id=source_id, series_key=series_key, value_hash=vh, is_demo=is_demo,
                        collected_at=now, last_seen_at=now, **fields)
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


def retire_companies(session: Session, *, source_id: int, prefix: str, keep: set[str],
                     is_demo: bool = False) -> list[str]:
    """Withdraw the current records of `source_id` under `prefix` that are not in `keep` (the source no
    longer publishes them). Values stay; only `is_current` is cleared. Call it only after a complete,
    successful read of everything under `prefix`. Returns the retired series keys."""
    rows = session.scalars(select(CompanyRecord).where(
        CompanyRecord.source_id == source_id, CompanyRecord.is_current.is_(True),
        CompanyRecord.is_demo.is_(is_demo), CompanyRecord.series_key.startswith(prefix, autoescape=True),
    )).all()
    gone = []
    for r in rows:
        if r.series_key not in keep:
            r.is_current = False
            gone.append(r.series_key)
    if gone:
        session.flush()
    return sorted(gone)
