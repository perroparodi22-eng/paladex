"""Database schema.

Design rules (see docs/ARCHITECTURE.md §Data model):

* Every fact row points to a `Source` and carries `source_url`, `published_at`,
  `collected_at`, its period, unit, currency, country, a type and a reliability/status.
* Observations are append-only. When a source revises a number, the old row is kept
  (`is_current = False`) and a new revision is inserted with `supersedes_id` pointing back.
  Nothing collected is ever overwritten or deleted by the collectors.
* `is_demo = True` marks demonstration rows; they are excluded from every query unless the
  user explicitly turns demo data on, and are always badged in the UI.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------


class Country(Base):
    __tablename__ = "countries"

    iso3: Mapped[str] = mapped_column(String(3), primary_key=True)
    iso2: Mapped[str | None] = mapped_column(String(2), index=True)
    m49: Mapped[int | None] = mapped_column(Integer, index=True)       # UN Comtrade / FAOSTAT M49
    fao_code: Mapped[int | None] = mapped_column(Integer, index=True)  # FAOSTAT area code
    name_en: Mapped[str] = mapped_column(String(120))
    name_it: Mapped[str] = mapped_column(String(120))
    priority: Mapped[bool] = mapped_column(Boolean, default=False)      # Parodi focus market
    region: Mapped[str | None] = mapped_column(String(60))
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    # Curated, sourced background knowledge (main varieties, seasons). JSON:
    # {"varieties": [...], "harvest_months": [...], "notes_it": "...", "notes_en": "...", "refs": [urls]}
    profile: Mapped[dict | None] = mapped_column(JSON)


class Source(Base):
    """A data source we collect from (or the user, for manual entries)."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    publisher: Mapped[str | None] = mapped_column(String(200))
    homepage: Mapped[str | None] = mapped_column(String(500))
    kind: Mapped[str] = mapped_column(String(20))                # SourceKind
    reliability: Mapped[str] = mapped_column(String(20))         # Reliability
    category: Mapped[str] = mapped_column(String(30))            # prices | trade | production | news | regulation | weather | fx
    country_iso3: Mapped[str | None] = mapped_column(String(10))
    language: Mapped[str | None] = mapped_column(String(5))
    expected_update: Mapped[str | None] = mapped_column(String(120))   # human text (Italian), e.g. "Mensile (verso il 15)"
    expected_update_en: Mapped[str | None] = mapped_column(String(200))  # the same in English
    expected_max_age_days: Mapped[int | None] = mapped_column(Integer)  # used by the staleness check
    terms_note: Mapped[str | None] = mapped_column(Text)
    requires_key: Mapped[str | None] = mapped_column(String(60))       # settings attribute name, if a key is needed
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    # Denormalised status for fast dashboard queries
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_run_status: Mapped[str | None] = mapped_column(String(20))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_new_data_at: Mapped[datetime | None] = mapped_column(DateTime)
    latest_published_at: Mapped[date | None] = mapped_column(Date)    # newest publication date we hold
    latest_period_label: Mapped[str | None] = mapped_column(String(40))
    latest_period_start: Mapped[date | None] = mapped_column(Date)    # start of that period: the label only moves forward

    runs: Mapped[list[CollectionRun]] = relationship(back_populates="source")


class CollectionRun(Base):
    __tablename__ = "collection_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20))  # RunStatus
    trigger: Mapped[str] = mapped_column(String(20), default="schedule")  # schedule | manual | startup | cli
    items_seen: Mapped[int] = mapped_column(Integer, default=0)
    items_new: Mapped[int] = mapped_column(Integer, default=0)
    items_revised: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[list | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)

    source: Mapped[Source] = relationship(back_populates="runs")


class RawDocument(Base):
    """Every downloaded file/response is kept on disk for audit and re-parsing."""

    __tablename__ = "raw_documents"
    __table_args__ = (UniqueConstraint("source_id", "content_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    url: Mapped[str] = mapped_column(String(1000))
    content_hash: Mapped[str] = mapped_column(String(64))
    content_type: Mapped[str | None] = mapped_column(String(100))
    path: Mapped[str] = mapped_column(String(500))      # relative to settings.raw_dir
    size_bytes: Mapped[int] = mapped_column(Integer)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    title: Mapped[str | None] = mapped_column(String(500))
    published_at: Mapped[date | None] = mapped_column(Date)


# ---------------------------------------------------------------------------
# Observations (append-only, revisioned)
# ---------------------------------------------------------------------------


class _ObservationMixin:
    """Shared provenance + revision columns."""

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    raw_document_id: Mapped[int | None] = mapped_column(ForeignKey("raw_documents.id"))
    series_key: Mapped[str] = mapped_column(String(300), index=True)  # identity of "what + when" within a source
    value_hash: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    supersedes_id: Mapped[int | None] = mapped_column(Integer)

    period_start: Mapped[date] = mapped_column(Date, index=True)
    period_end: Mapped[date] = mapped_column(Date)
    period_label: Mapped[str] = mapped_column(String(40))  # "2026-09", "2025", "2026-W41", "2026-Q3"
    frequency: Mapped[str] = mapped_column(String(10))     # D W M Q A irregular

    published_at: Mapped[date | None] = mapped_column(Date)       # by the source
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    source_url: Mapped[str | None] = mapped_column(String(1000))

    data_status: Mapped[str] = mapped_column(String(20))   # DataStatus
    reliability: Mapped[str] = mapped_column(String(20))   # Reliability
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    extra: Mapped[dict | None] = mapped_column(JSON)


class PriceObservation(_ObservationMixin, Base):
    __tablename__ = "price_observations"
    __table_args__ = (
        Index("ix_price_lookup", "variety", "origin_iso3", "price_type", "period_start"),
    )

    price_type: Mapped[str] = mapped_column(String(30), index=True)  # PriceType
    origin_iso3: Mapped[str | None] = mapped_column(String(10), index=True)  # where the honey comes from
    origin_label: Mapped[str | None] = mapped_column(String(120))           # raw text, e.g. "Argentina", "Domestic"
    market_iso3: Mapped[str | None] = mapped_column(String(10), index=True)  # where the price is observed
    market_location: Mapped[str | None] = mapped_column(String(120))
    variety: Mapped[str] = mapped_column(String(30), index=True)           # Variety
    variety_raw: Mapped[str | None] = mapped_column(String(200))
    color_grade: Mapped[str | None] = mapped_column(String(60))            # USDA color: white / extra light amber / ...
    organic: Mapped[bool] = mapped_column(Boolean, default=False)
    terms: Mapped[str | None] = mapped_column(String(200))                 # e.g. "bulk, drums, delivered", "CIF"

    # As published (original currency & unit)
    price_low: Mapped[float | None] = mapped_column(Float)
    price_high: Mapped[float | None] = mapped_column(Float)
    price_value: Mapped[float] = mapped_column(Float)     # mid/avg as published (or mid of range)
    currency: Mapped[str] = mapped_column(String(3))
    unit: Mapped[str] = mapped_column(String(20))          # "kg", "lb", "t", "100kg"
    # Normalised per-kg values (same currency) + FX-converted for comparison
    price_per_kg: Mapped[float] = mapped_column(Float)
    usd_per_kg: Mapped[float | None] = mapped_column(Float)
    eur_per_kg: Mapped[float | None] = mapped_column(Float)
    fx_date: Mapped[date | None] = mapped_column(Date)
    # How usd/eur were derived (services.fx): "spot" (one ECB rate, fx_date) or "period_avg"
    # (mean of the ECB daily rates fx_start..fx_end). fx_end < period_end = provisional
    # (period still open at conversion); the backfill recomputes it once the period has closed.
    fx_basis: Mapped[str | None] = mapped_column(String(12))
    fx_start: Mapped[date | None] = mapped_column(Date)
    fx_end: Mapped[date | None] = mapped_column(Date)
    volume_kg: Mapped[float | None] = mapped_column(Float)  # traded volume behind the price, if given


class TradeFlowObservation(_ObservationMixin, Base):
    __tablename__ = "trade_flows"
    __table_args__ = (
        Index("ix_trade_lookup", "reporter_iso3", "partner_iso3", "flow", "period_start"),
    )

    hs_code: Mapped[str] = mapped_column(String(12), default="0409")
    reporter_iso3: Mapped[str] = mapped_column(String(10), index=True)   # "EU" aggregates use pseudo codes like "EU27"
    partner_iso3: Mapped[str] = mapped_column(String(10), index=True)    # "WLD" = world total
    flow: Mapped[str] = mapped_column(String(12), index=True)           # TradeFlow
    net_weight_kg: Mapped[float | None] = mapped_column(Float)
    value: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3))
    value_basis: Mapped[str | None] = mapped_column(String(10))         # CIF / FOB / primary
    unit_value_per_kg: Mapped[float | None] = mapped_column(Float)      # value / net weight (same currency)
    usd_value: Mapped[float | None] = mapped_column(Float)
    eur_value: Mapped[float | None] = mapped_column(Float)
    fx_basis: Mapped[str | None] = mapped_column(String(12))  # as PriceObservation.fx_basis
    fx_start: Mapped[date | None] = mapped_column(Date)
    fx_end: Mapped[date | None] = mapped_column(Date)


class ProductionStat(_ObservationMixin, Base):
    __tablename__ = "production_stats"

    country_iso3: Mapped[str] = mapped_column(String(10), index=True)
    metric: Mapped[str] = mapped_column(String(40), index=True)  # production | colonies | yield_per_colony | producer_price | stocks
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(30))                # t, kg, number, USD/t, LCU/t ...
    flag_raw: Mapped[str | None] = mapped_column(String(20))     # e.g. FAOSTAT "A", "E", "I"


class WeatherObservation(_ObservationMixin, Base):
    __tablename__ = "weather_observations"

    region_key: Mapped[str] = mapped_column(String(60), index=True)
    country_iso3: Mapped[str] = mapped_column(String(10), index=True)
    temp_mean_c: Mapped[float | None] = mapped_column(Float)
    precip_mm: Mapped[float | None] = mapped_column(Float)
    temp_anomaly_c: Mapped[float | None] = mapped_column(Float)
    precip_anomaly_pct: Mapped[float | None] = mapped_column(Float)
    baseline: Mapped[str | None] = mapped_column(String(20))     # e.g. "1991-2020"


class FxRate(Base):
    __tablename__ = "fx_rates"
    __table_args__ = (UniqueConstraint("rate_date", "currency"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rate_date: Mapped[date] = mapped_column(Date, index=True)
    currency: Mapped[str] = mapped_column(String(3), index=True)
    per_eur: Mapped[float] = mapped_column(Float)   # units of `currency` per 1 EUR (ECB convention)
    source_key: Mapped[str] = mapped_column(String(60), default="ecb_fx")


# ---------------------------------------------------------------------------
# Documents: official reports, news, regulations
# ---------------------------------------------------------------------------


class Report(Base):
    """An official publication release (e.g. USDA National Honey Report, Oct 2026)."""

    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("source_id", "report_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    report_key: Mapped[str] = mapped_column(String(200))   # stable id within the source (e.g. "2026-10")
    title: Mapped[str] = mapped_column(String(500))
    period_label: Mapped[str | None] = mapped_column(String(40))
    published_at: Mapped[date | None] = mapped_column(Date, index=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    url: Mapped[str] = mapped_column(String(1000))
    raw_document_id: Mapped[int | None] = mapped_column(ForeignKey("raw_documents.id"))
    summary_en: Mapped[str | None] = mapped_column(Text)
    summary_it: Mapped[str | None] = mapped_column(Text)
    summary_is_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    narrative: Mapped[str | None] = mapped_column(Text)    # market commentary text extracted verbatim
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class NewsArticle(Base):
    __tablename__ = "news_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    url: Mapped[str] = mapped_column(String(1500))
    canonical_url: Mapped[str] = mapped_column(String(1500), unique=True)
    title: Mapped[str] = mapped_column(String(600))
    title_norm: Mapped[str] = mapped_column(String(600), index=True)   # for duplicate detection
    publisher: Mapped[str | None] = mapped_column(String(200))          # original outlet (for aggregator feeds)
    language: Mapped[str | None] = mapped_column(String(5))
    published_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    image_url: Mapped[str | None] = mapped_column(String(1500))
    snippet: Mapped[str | None] = mapped_column(Text)        # feed description, as published (stripped of HTML)
    countries: Mapped[list | None] = mapped_column(JSON)     # ISO3 list
    topics: Mapped[list | None] = mapped_column(JSON)        # topic keys
    relevance_score: Mapped[int] = mapped_column(Integer, default=0, index=True)  # 0-100
    relevance_reason: Mapped[str | None] = mapped_column(String(500))
    # AI-generated fields (always labelled as AI in the UI)
    summary_en: Mapped[str | None] = mapped_column(Text)
    summary_it: Mapped[str | None] = mapped_column(Text)
    title_en: Mapped[str | None] = mapped_column(String(600))
    title_it: Mapped[str | None] = mapped_column(String(600))
    ai_processed_at: Mapped[datetime | None] = mapped_column(DateTime)
    ai_model: Mapped[str | None] = mapped_column(String(80))
    # Duplicate handling: duplicates are kept but point at the first-seen article
    duplicate_of_id: Mapped[int | None] = mapped_column(ForeignKey("news_articles.id"), index=True)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class RegulationItem(Base):
    __tablename__ = "regulations"
    __table_args__ = (UniqueConstraint("source_id", "reference"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    jurisdiction: Mapped[str] = mapped_column(String(10), index=True)  # EU, IT, US, ...
    doc_type: Mapped[str] = mapped_column(String(40))                 # regulation, directive, tariff, antidumping, import_alert, agreement, notice
    reference: Mapped[str] = mapped_column(String(200))               # CELEX, FR document number, ...
    title: Mapped[str] = mapped_column(String(1000))
    status: Mapped[str | None] = mapped_column(String(40))            # in_force, proposed, adopted, repealed, ...
    published_at: Mapped[date | None] = mapped_column(Date, index=True)
    effective_date: Mapped[date | None] = mapped_column(Date)
    url: Mapped[str] = mapped_column(String(1000))
    countries: Mapped[list | None] = mapped_column(JSON)
    summary_en: Mapped[str | None] = mapped_column(Text)
    summary_it: Mapped[str | None] = mapped_column(Text)
    summary_is_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # Source-specific metadata: official PDF URL, citation, action, agencies, raw document id...
    extra: Mapped[dict | None] = mapped_column(JSON)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class TariffMeasure(Base):
    """One official import-duty layer on honey for one origin, as published (EU TARIC via the UK
    XI mirror, US HTS). Append-only like the observations: a changed duty, validity or quota
    balance becomes a new revision (`services.tariffs.record_measure`); a measure the source no
    longer publishes is retired (`is_current=False`), never deleted. `as_of` is the last date the
    source was checked and still published this exact measure."""

    __tablename__ = "tariff_measures"
    __table_args__ = (
        Index("ix_tariff_lookup", "jurisdiction", "origin_iso3", "is_current"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    raw_document_id: Mapped[int | None] = mapped_column(ForeignKey("raw_documents.id"))
    series_key: Mapped[str] = mapped_column(String(300), index=True)  # identity of the measure within a source
    value_hash: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    supersedes_id: Mapped[int | None] = mapped_column(Integer)

    jurisdiction: Mapped[str] = mapped_column(String(10), index=True)   # importing side: "EU" | "US"
    origin_iso3: Mapped[str] = mapped_column(String(12), index=True)    # ISO3, or "ERGA_OMNES" / "ALL"
    hs_code: Mapped[str] = mapped_column(String(14))                    # "0409000000" (TARIC), "0409.00.00" (HTS)
    measure_type: Mapped[str] = mapped_column(String(20), index=True)   # mfn | preference | trq_in | trq_out | antidumping | surcharge | other
    measure_code: Mapped[str | None] = mapped_column(String(40))        # TARIC measure type id ("103"), HTS column / heading
    description: Mapped[str | None] = mapped_column(Text)               # measure type / heading text as published
    duty_text: Mapped[str | None] = mapped_column(String(500))          # duty expression as published ("17.30 %", "1.9¢/kg")
    ad_valorem_pct: Mapped[float | None] = mapped_column(Float)
    specific_amount: Mapped[float | None] = mapped_column(Float)
    specific_unit: Mapped[str | None] = mapped_column(String(20))       # "kg", "100kg", "t"
    specific_currency: Mapped[str | None] = mapped_column(String(3))
    quota_order_number: Mapped[str | None] = mapped_column(String(20))
    quota_volume_kg: Mapped[float | None] = mapped_column(Float)
    quota_balance_kg: Mapped[float | None] = mapped_column(Float)
    quota_status: Mapped[str | None] = mapped_column(String(20))        # open | critical | exhausted | blocked ...
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    legal_reference: Mapped[str | None] = mapped_column(String(300))    # EU act ("R2658/87"), HTSUS heading ...
    legal_url: Mapped[str | None] = mapped_column(String(1000))         # EUR-Lex / official text
    consult_url: Mapped[str | None] = mapped_column(String(1000))       # official consultation page (TARIC, HTS search)
    source_url: Mapped[str | None] = mapped_column(String(1000))        # the API document the row was read from
    published_at: Mapped[date | None] = mapped_column(Date)             # publication of the legal act, when given
    as_of: Mapped[date] = mapped_column(Date, index=True)               # last date the source confirmed this measure
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    data_status: Mapped[str] = mapped_column(String(20), default="published")
    reliability: Mapped[str] = mapped_column(String(20), default="official")
    # Source-specific metadata: measure sid, geographical group, excluded countries, legal acts,
    # special-programme codes, "needs_review" (applicability not parsed unambiguously) ...
    extra: Mapped[dict | None] = mapped_column(JSON)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


# ---------------------------------------------------------------------------
# Business tools (user data — never touched by collectors)
# ---------------------------------------------------------------------------


class SupplierQuote(Base):
    __tablename__ = "supplier_quotes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_name: Mapped[str] = mapped_column(String(200), index=True)
    origin_iso3: Mapped[str] = mapped_column(String(10), index=True)
    variety: Mapped[str] = mapped_column(String(30), index=True)
    variety_note: Mapped[str | None] = mapped_column(String(200))
    price_per_kg: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3))
    quantity_kg: Mapped[float | None] = mapped_column(Float)
    packaging: Mapped[str | None] = mapped_column(String(120))       # "300 kg metal drums", "IBC", ...
    incoterm: Mapped[str | None] = mapped_column(String(10))         # FOB, CFR, CIF, DAP, ...
    incoterm_place: Mapped[str | None] = mapped_column(String(120))
    shipping_cost: Mapped[float | None] = mapped_column(Float)
    shipping_cost_currency: Mapped[str | None] = mapped_column(String(3))
    shipping_cost_basis: Mapped[str | None] = mapped_column(String(20))  # per_container | per_kg | total
    insurance_pct: Mapped[float | None] = mapped_column(Float)
    duty_pct: Mapped[float | None] = mapped_column(Float)
    other_costs: Mapped[float | None] = mapped_column(Float)
    other_costs_currency: Mapped[str | None] = mapped_column(String(3))
    date_received: Mapped[date] = mapped_column(Date, index=True)
    valid_until: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    # Milestone 7a (landed-cost calculator). Nullable, so older database files gain them in place
    # (db.migrate_add_missing_columns). `price_per_kg` stays the per-kg price in `currency`; a price
    # quoted per pound keeps its figure as typed in `price_quoted` with `price_unit = "lb"`.
    price_unit: Mapped[str | None] = mapped_column(String(5))         # "kg" | "lb" as quoted (None = kg)
    price_quoted: Mapped[float | None] = mapped_column(Float)         # the price exactly as quoted, per price_unit
    destination: Mapped[str | None] = mapped_column(String(3))       # "ITA" (EU customs) | "USA" (None = ITA)
    # Itemised extra costs: [{"kind": origin|port|broker|inland|bank|other, "amount", "currency",
    #                         "basis": per_container|per_kg|total|pct_goods, "note"}]
    cost_items: Mapped[list | None] = mapped_column(JSON)


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    alert_type: Mapped[str] = mapped_column(String(30))   # AlertType
    params: Mapped[dict] = mapped_column(JSON)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)


class AlertEvent(Base):
    __tablename__ = "alert_events"
    __table_args__ = (UniqueConstraint("rule_id", "dedup_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("alert_rules.id"), index=True)
    dedup_key: Mapped[str] = mapped_column(String(200))
    triggered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    severity: Mapped[str] = mapped_column(String(10), default="info")
    title_it: Mapped[str] = mapped_column(String(500))
    title_en: Mapped[str] = mapped_column(String(500))
    body_it: Mapped[str | None] = mapped_column(Text)
    body_en: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(500))      # in-app route or external URL
    ref_type: Mapped[str | None] = mapped_column(String(30))
    ref_id: Mapped[int | None] = mapped_column(Integer)
    read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class Briefing(Base):
    __tablename__ = "briefings"
    __table_args__ = (UniqueConstraint("briefing_date", "language"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    briefing_date: Mapped[date] = mapped_column(Date, index=True)
    language: Mapped[str] = mapped_column(String(2))
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    generator: Mapped[str] = mapped_column(String(80))          # "rules" or the LLM model name
    content: Mapped[dict] = mapped_column(JSON)                 # structured sections with source refs


class DataQualityIssue(Base):
    __tablename__ = "data_quality_issues"
    __table_args__ = (UniqueConstraint("dedup_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dedup_key: Mapped[str] = mapped_column(String(300))
    issue_type: Mapped[str] = mapped_column(String(30), index=True)   # QualityIssueType
    severity: Mapped[str] = mapped_column(String(10))
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"))
    message_it: Mapped[str] = mapped_column(Text)
    message_en: Mapped[str] = mapped_column(Text)
    details: Mapped[dict | None] = mapped_column(JSON)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)
