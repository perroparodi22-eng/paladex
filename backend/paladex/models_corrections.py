"""Corrections made by a person to a figure (services/corrections.py, docs/ARCHITECTURE.md).

A `CorrectionEvent` is an append-only record of something a user did about a stored figure:

* ``value_correction`` - "this value is wrong, the right one is X": applied as a NEW revision of
  the same series (reliability ``user``), the official row stays in the history;
* ``revert``           - undoes an earlier event: a new revision with the official values restored;
* ``flag_wrong``       - "this figure looks wrong" (no value): opens a data-quality issue;
* ``note``             - free text about a country (optionally about one figure).

Events have a global id (uuid4) and are exchanged between the owner's installations through the
``paladex-corrections`` branch of the git repository (services/corrections_sync.py), one JSON file
per event. The columns below the "local state" line describe what happened ON THIS COMPUTER (applied,
conflict, synced ...); they are never exported. Rows are never deleted; their local state changes.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .models import utcnow


class CorrectionEvent(Base):
    __tablename__ = "correction_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)   # uuid4, the same on every computer
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)           # UTC, when the person confirmed
    author: Mapped[str] = mapped_column(String(120))                             # display name of the person
    device_id: Mapped[str] = mapped_column(String(64))                           # installation that created it
    kind: Mapped[str] = mapped_column(String(20), index=True)                    # value_correction | revert | flag_wrong | note

    # --- target (the figure, as identified on the computer that created the event) ---
    target_table: Mapped[str | None] = mapped_column(String(40), index=True)    # price_observations | trade_flows | production_stats
    source_key: Mapped[str | None] = mapped_column(String(60))
    series_key: Mapped[str | None] = mapped_column(String(300), index=True)
    period_label: Mapped[str | None] = mapped_column(String(40))
    target_unit: Mapped[str | None] = mapped_column(String(30))                 # as stored in the table
    target_currency: Mapped[str | None] = mapped_column(String(3))
    target_field: Mapped[str | None] = mapped_column(String(30))                # price_value | net_weight_kg | value
    country_iso3: Mapped[str | None] = mapped_column(String(10), index=True)
    label: Mapped[str | None] = mapped_column(String(300))                      # "Argentina · Millefiori · 2026-09"
    official_hash: Mapped[str | None] = mapped_column(String(64))               # value_hash of the official row then
    official_before: Mapped[dict | None] = mapped_column(JSON)                  # its value fields then
    official_value: Mapped[float | None] = mapped_column(Float)                 # its main value then (target_unit/currency)

    # --- the correction ---
    entered: Mapped[dict | None] = mapped_column(JSON)          # {value, low, high, unit, currency} as typed
    corrected_value: Mapped[float | None] = mapped_column(Float)  # main value as stored (target_unit/currency)
    normalized: Mapped[dict | None] = mapped_column(JSON)       # the value fields written to the table
    reverts_event_id: Mapped[str | None] = mapped_column(String(36), index=True)
    reason: Mapped[str | None] = mapped_column(Text)            # why (value_correction, flag_wrong), the text (note)
    ai_interpretation: Mapped[dict | None] = mapped_column(JSON)

    # --- local state (this computer only; never exported) ---
    origin: Mapped[str] = mapped_column(String(10), default="local")             # local | remote
    status: Mapped[str] = mapped_column(String(30), index=True)
    status_detail: Mapped[dict | None] = mapped_column(JSON)
    target_row_id: Mapped[int | None] = mapped_column(Integer)                   # official row it replaced, here
    applied_row_id: Mapped[int | None] = mapped_column(Integer)                  # row written for it, here
    issue_id: Mapped[int | None] = mapped_column(Integer)                        # data-quality issue (flag_wrong)
    sync_status: Mapped[str] = mapped_column(String(20), default="pending_sync", index=True)  # pending_sync | synced | received
    synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    sync_error: Mapped[str | None] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)      # when this computer stored it
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
