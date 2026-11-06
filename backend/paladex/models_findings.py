"""Other sources (non-official): figures found on the web and verified by Paladex (`web_findings`).

Official statistics often stop at 2024. A finding is the newest figure for a country that exists
somewhere on the web (an official publication that is not machine-readable, a USDA FAS attaché
report, an association, the trade press, the news), kept APART from the official series:

* one row = one figure exactly as one page publishes it: country, metric, period, ``value`` (the
  number), ``unit``, ``value_as_published`` (the text as printed, e.g. "75.000 t"), its ``status``
  (forecast, estimate, provisional official...), the ``kind`` of publisher, whether it is an official
  publication (``is_official``), the page (``source_url``) and the exact ``quote`` that carries it;
* a finding exists only if Paladex itself opened ``source_url`` and found the quote AND the number of
  ``value_as_published`` in the page text (``services.web_verify``). ``verified_at`` is the last
  successful check, ``verification`` what was checked (and the history of the checks);
* findings never feed the map, rankings, totals, comparisons, alerts or the official series: they are
  read only by the "Other sources (non-official)" panel of a country and by ``GET /api/findings``;
* append-only like the observations (``services.ingest``): a changed figure becomes a new revision
  (the old row is kept with ``is_current=False``); nothing is ever deleted. A page that later
  disappears does not remove the finding: the failed re-check is noted in ``verification``.
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


class FindingMetric(StrEnum):
    PRODUCTION = "production"
    EXPORTS = "exports"
    IMPORTS = "imports"
    HIVES = "hives"
    PRODUCER_PRICE = "producer_price"
    EXPORT_PRICE = "export_price"


class FindingStatus(StrEnum):
    OFFICIAL_FINAL = "official_final"              # final figure of an official body
    OFFICIAL_PROVISIONAL = "official_provisional"  # provisional figure of an official body
    OFFICIAL_ESTIMATE = "official_estimate"        # an official body's own estimate
    FORECAST = "forecast"                          # a forecast (e.g. USDA attaché, association outlook)
    ESTIMATE = "estimate"                          # an estimate by a non-official publisher
    REPORTED = "reported"                          # a figure reported (press, news) without more detail


class FindingKind(StrEnum):
    OFFICIAL_STATISTIC = "official_statistic"      # statistics office / ministry statistic not in a machine-readable series
    OFFICIAL_PUBLICATION = "official_publication"  # official report, bulletin, yearbook
    GOVERNMENT_STATEMENT = "government_statement"  # minister, ministry press release
    USDA_FAS = "usda_fas"                          # USDA Foreign Agricultural Service (GAIN attaché reports)
    INTERNATIONAL_BODY = "international_body"      # FAO, EU Commission, IHEC...
    ASSOCIATION = "association"                    # beekeepers' / exporters' association
    TRADE_PRESS = "trade_press"
    NEWS = "news"
    MARKET_REPORT = "market_report"                # broker / market newsletter


# Kinds whose publisher can be an official one (``is_official`` is refused for the others).
# ``is_official`` describes the PAGE (who publishes it); ``status`` describes the FIGURE: a news page
# reporting a statistics office's final figure is status official_final, is_official false (shown as
# "non-official source" with the figure's status).
OFFICIAL_KINDS = frozenset({FindingKind.OFFICIAL_STATISTIC, FindingKind.OFFICIAL_PUBLICATION,
                            FindingKind.GOVERNMENT_STATEMENT, FindingKind.USDA_FAS, FindingKind.INTERNATIONAL_BODY})


class WebFinding(Base):
    __tablename__ = "web_findings"
    __table_args__ = (
        Index("ix_web_finding_lookup", "country_iso3", "metric", "is_current"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    raw_document_id: Mapped[int | None] = mapped_column(ForeignKey("raw_documents.id"))  # excerpt of the page around the quote
    series_key: Mapped[str] = mapped_column(String(400), index=True)   # country | metric | period | unit | page
    value_hash: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    supersedes_id: Mapped[int | None] = mapped_column(Integer)

    country_iso3: Mapped[str] = mapped_column(String(3), index=True)
    metric: Mapped[str] = mapped_column(String(20), index=True)        # FindingMetric
    period_label: Mapped[str] = mapped_column(String(40))              # as the page states it: "2025", "2025/26", "Jan-Sep 2026"
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date, index=True)
    value: Mapped[float | None] = mapped_column(Float)                 # the number of value_as_published (None: a range...)
    unit: Mapped[str] = mapped_column(String(40))                      # "t", "USD", "hives", "USD/kg"...
    value_as_published: Mapped[str] = mapped_column(String(160))       # "75.000 toneladas", "US$ 1.2 billion"
    status: Mapped[str] = mapped_column(String(24))                    # FindingStatus
    kind: Mapped[str] = mapped_column(String(24))                      # FindingKind
    is_official: Mapped[bool] = mapped_column(Boolean, default=False)  # published by an official body (not in a statistical series)

    publisher: Mapped[str] = mapped_column(String(300))
    source_url: Mapped[str] = mapped_column(String(1000))
    source_title: Mapped[str | None] = mapped_column(String(500))
    published_at: Mapped[date | None] = mapped_column(Date)
    language: Mapped[str | None] = mapped_column(String(8))
    quote: Mapped[str] = mapped_column(Text)                           # verbatim sentence carrying the figure
    also_reported_by: Mapped[list | None] = mapped_column(JSON)        # other pages reporting the same figure (not verified)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)     # last SUCCESSFUL check on the page
    verification: Mapped[dict | None] = mapped_column(JSON)            # what was checked + the history of the checks

    collected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    extra: Mapped[dict | None] = mapped_column(JSON)                   # found_by (seed | ai_web_search), provider, model...


# Fields whose change makes a new revision (the figure and its evidence). Check results, the archived
# excerpt and the notes are metadata about the finding, not the finding.
VALUE_FIELDS: tuple[str, ...] = (
    "country_iso3", "metric", "period_label", "period_start", "period_end", "value", "unit", "value_as_published",
    "status", "kind", "is_official", "publisher", "source_url", "source_title", "published_at", "quote",
    "also_reported_by",
)
# Filled on an unchanged row only when still empty, never overwritten.
_FILL_FIELDS = ("language", "notes")
# Updated on every successful check of an unchanged row (they describe our checks, not the figure):
# the time of the check, what was checked, and the archived excerpt of the page it was checked on.
_CHECK_FIELDS = ("verified_at", "verification", "raw_document_id")


def _canon(v):
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def value_hash(fields: dict) -> str:
    payload = {k: _canon(fields.get(k)) for k in VALUE_FIELDS}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def current_finding(session: Session, source_id: int, series_key: str, is_demo: bool = False) -> WebFinding | None:
    rows = session.scalars(select(WebFinding).where(WebFinding.series_key == series_key)).all()
    return next((r for r in rows if r.source_id == source_id and r.is_current and bool(r.is_demo) == bool(is_demo)), None)


def _check(fields: dict) -> None:
    for k, enum in (("metric", FindingMetric), ("status", FindingStatus), ("kind", FindingKind)):
        if fields.get(k) not in {e.value for e in enum}:
            raise ValueError(f"unknown {k} {fields.get(k)!r}")
    if fields.get("is_official") and fields["kind"] not in OFFICIAL_KINDS:
        raise ValueError(f"a {fields['kind']!r} publisher cannot be marked official")
    for k in ("quote", "source_url", "value_as_published", "publisher", "unit", "period_label"):
        if not fields.get(k):
            raise ValueError(f"a finding needs {k}")
    if fields.get("verified_at") is None:
        raise ValueError("a finding is stored only after Paladex verified it on its page")


def record_finding(session: Session, *, source_id: int, series_key: str, is_demo: bool = False,
                   **fields) -> tuple[Outcome, WebFinding]:
    """Append-only write of one VERIFIED finding (see the module docstring)."""
    _check(fields)
    vh = value_hash(fields)
    current = current_finding(session, source_id, series_key, is_demo)
    now = utcnow()
    if current is not None and current.value_hash == vh:
        current.last_seen_at = now
        for k in _FILL_FIELDS:
            if getattr(current, k) is None and fields.get(k) is not None:
                setattr(current, k, fields[k])
        for k in _CHECK_FIELDS:
            if fields.get(k):
                setattr(current, k, fields[k])
        return "unchanged", current
    row = WebFinding(source_id=source_id, series_key=series_key, value_hash=vh, is_demo=is_demo,
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


def retire_findings(session: Session, *, source_id: int, rows: list[WebFinding]) -> list[str]:
    """Withdraw current findings (``is_current=False``; values and history stay). Returns their keys."""
    gone = []
    for r in rows:
        if r.source_id == source_id and r.is_current:
            r.is_current = False
            gone.append(r.series_key)
    if gone:
        session.flush()
    return sorted(gone)
