"""Collector framework.

A collector is a small class that knows ONE source. It declares metadata (shown on the
"Fonti" page and used for staleness checks) and implements `collect(ctx)`. All network
access goes through `ctx.fetch()` (polite, cached on disk, recorded as RawDocument) and all
writes go through the `ctx.add_*` helpers, which enforce provenance and the append-only
revision rules.

Writing a collector:

    class MyCollector(Collector):
        key = "my_source"
        name = "My source"
        ...
        def collect(self, ctx: CollectContext) -> None:
            doc = ctx.fetch("https://example.org/data.json")
            if doc.unchanged and not ctx.force:
                return                                  # same bytes as last time
            for row in doc.json():
                ctx.add_price(...)
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..enums import DataStatus, PriceType, Reliability, SourceKind
from ..models import (
    PriceObservation,
    ProductionStat,
    RawDocument,
    RegulationItem,
    Report,
    Source,
    TradeFlowObservation,
    WeatherObservation,
    utcnow,
)
from ..services import fx, ingest

log = logging.getLogger(__name__)


class CollectorError(Exception):
    """Raised for an unrecoverable problem with a source (bad format, HTTP 4xx...)."""


class MissingKey(CollectorError):
    """The collector needs an API key that is not configured."""


class Offline(CollectorError):
    """No internet connection (or the host is unreachable)."""


@dataclass
class FetchResult:
    url: str
    status_code: int
    content: bytes
    content_type: str | None
    raw_document_id: int
    unchanged: bool                 # identical bytes already stored for this source
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def text(self) -> str:
        for enc in ("utf-8", "cp1252", "latin-1"):
            try:
                return self.content.decode(enc)
            except UnicodeDecodeError:
                continue
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.text)


@dataclass
class RunCounters:
    seen: int = 0
    new: int = 0
    revised: int = 0
    warnings: list[str] = field(default_factory=list)
    newest_published: date | None = None
    newest_period_label: str | None = None
    newest_period_start: date | None = None
    committed_new: int = 0
    committed_revised: int = 0

    def count(self, outcome: str) -> None:
        self.seen += 1
        if outcome == "new":
            self.new += 1
        elif outcome == "revised":
            self.revised += 1


class CollectContext:
    """Everything a collector needs: db session, polite HTTP, provenance-aware writers."""

    # Minimum seconds between two requests to the same host (politeness / rate limits).
    MIN_INTERVAL_PER_HOST = 1.5

    def __init__(
        self,
        session: Session,
        source: Source,
        settings: Settings | None = None,
        client: httpx.Client | None = None,
        force: bool = False,
    ):
        self.session = session
        self.source = source
        self.settings = settings or get_settings()
        self.force = force
        self.counters = RunCounters()
        self._own_client = client is None
        self.client = client or httpx.Client(
            timeout=self.settings.http_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": self.settings.user_agent, "Accept-Language": "en,it;q=0.8"},
        )
        self._last_hit: dict[str, float] = {}

    # ------------------------------------------------------------------ http
    def fetch(
        self,
        url: str,
        *,
        params: dict | None = None,
        headers: dict | None = None,
        title: str | None = None,
        published_at: date | None = None,
        retries: int = 2,
        accept_status: tuple[int, ...] = (200,),
        store: bool = True,
    ) -> FetchResult:
        host = urlparse(url).netloc
        last = self._last_hit.get(host)
        if last is not None:
            wait = self.MIN_INTERVAL_PER_HOST - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = self.client.get(url, params=params, headers=headers)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                if attempt > retries:
                    raise Offline(f"Cannot reach {host}: {exc}") from exc
                time.sleep(2 * attempt)
                continue
            except httpx.TimeoutException as exc:
                if attempt > retries:
                    raise CollectorError(f"Timeout fetching {url}") from exc
                time.sleep(2 * attempt)
                continue
            finally:
                self._last_hit[host] = time.monotonic()
            if resp.status_code in (429, 502, 503, 504) and attempt <= retries:
                retry_after = resp.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 5 * attempt
                time.sleep(min(delay, 60))
                continue
            break
        if resp.status_code not in accept_status:
            raise CollectorError(f"HTTP {resp.status_code} for {resp.request.url}")
        content = resp.content
        ctype = resp.headers.get("content-type")
        raw_id, unchanged = (0, False)
        if store:
            raw_id, unchanged = self._store_raw(str(resp.request.url), content, ctype, title, published_at)
        return FetchResult(
            url=str(resp.request.url),
            status_code=resp.status_code,
            content=content,
            content_type=ctype,
            raw_document_id=raw_id,
            unchanged=unchanged,
            headers=dict(resp.headers),
        )

    def _store_raw(self, url, content, ctype, title, published_at) -> tuple[int, bool]:
        h = hashlib.sha256(content).hexdigest()
        existing = self.session.scalars(
            select(RawDocument).where(RawDocument.source_id == self.source.id, RawDocument.content_hash == h)
        ).first()
        if existing:
            return existing.id, True
        ext = _guess_ext(url, ctype)
        rel = Path(self.source.key) / f"{utcnow():%Y%m%d-%H%M%S}-{h[:12]}{ext}"
        dest = self.settings.raw_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        doc = RawDocument(
            source_id=self.source.id, url=url[:1000], content_hash=h, content_type=(ctype or "")[:100],
            path=str(rel), size_bytes=len(content), title=(title or "")[:500] or None, published_at=published_at,
        )
        self.session.add(doc)
        self.session.flush()
        return doc.id, False

    # -------------------------------------------------------------- helpers
    def checkpoint(self) -> None:
        """Commit what has been collected so far (use between independent batches so a
        late failure does not discard earlier, valid data)."""
        self.session.commit()
        self.counters.committed_new = self.counters.new
        self.counters.committed_revised = self.counters.revised

    def warn(self, msg: str) -> None:
        log.warning("[%s] %s", self.source.key, msg)
        if len(self.counters.warnings) < 50:
            self.counters.warnings.append(msg[:500])

    def _track_period(self, published_at: date | None, period_label: str | None, period_start: date | None) -> None:
        c = self.counters
        if published_at and (c.newest_published is None or published_at > c.newest_published):
            c.newest_published = published_at
        if period_start and (c.newest_period_start is None or period_start > c.newest_period_start):
            c.newest_period_start = period_start
            c.newest_period_label = period_label

    def _common(self, kw: dict) -> dict:
        kw.setdefault("reliability", self.source.reliability)
        kw.setdefault("data_status", DataStatus.PUBLISHED.value)
        for k in ("reliability", "data_status"):
            if hasattr(kw[k], "value"):
                kw[k] = kw[k].value
        return kw

    # -------------------------------------------------------------- writers
    def add_price(
        self,
        *,
        series_key: str,
        price_type: PriceType | str,
        variety: str,
        price_value: float,
        currency: str,
        unit: str,
        period_start: date,
        period_end: date,
        period_label: str,
        frequency: str,
        price_low: float | None = None,
        price_high: float | None = None,
        **kw,
    ) -> PriceObservation:
        """Record a price. `price_value` is in `currency` per `unit` (kg, lb, t, 100kg...)."""
        kw = self._common(kw)
        pt = price_type.value if hasattr(price_type, "value") else price_type
        outcome, row = ingest.record(
            self.session, PriceObservation, source_id=self.source.id, series_key=f"{pt}|{series_key}",
            price_type=pt, variety=variety, price_value=price_value, price_low=price_low, price_high=price_high,
            currency=currency.upper(), unit=unit, price_per_kg=round(ingest.per_kg(price_value, unit), 6),
            period_start=period_start, period_end=period_end, period_label=period_label, frequency=frequency, **kw,
        )
        if outcome != "unchanged" or row.usd_per_kg is None:
            fx.normalise_price(self.session, row)
        self.counters.count(outcome)
        self._track_period(kw.get("published_at"), period_label, period_start)
        return row

    def add_trade(
        self,
        *,
        series_key: str,
        reporter_iso3: str,
        partner_iso3: str,
        flow: str,
        currency: str,
        period_start: date,
        period_end: date,
        period_label: str,
        frequency: str,
        net_weight_kg: float | None = None,
        value: float | None = None,
        **kw,
    ) -> TradeFlowObservation:
        kw = self._common(kw)
        uv = round(value / net_weight_kg, 4) if value and net_weight_kg else None
        outcome, row = ingest.record(
            self.session, TradeFlowObservation, source_id=self.source.id, series_key=series_key,
            reporter_iso3=reporter_iso3, partner_iso3=partner_iso3, flow=flow, currency=currency.upper(),
            net_weight_kg=net_weight_kg, value=value, unit_value_per_kg=uv,
            period_start=period_start, period_end=period_end, period_label=period_label, frequency=frequency, **kw,
        )
        if outcome != "unchanged" or (row.value is not None and row.usd_value is None):
            fx.normalise_trade(self.session, row)
        self.counters.count(outcome)
        self._track_period(kw.get("published_at"), period_label, period_start)
        return row

    def add_production(
        self, *, series_key: str, country_iso3: str, metric: str, value: float, unit: str,
        period_start: date, period_end: date, period_label: str, frequency: str = "A", **kw,
    ) -> ProductionStat:
        kw = self._common(kw)
        outcome, row = ingest.record(
            self.session, ProductionStat, source_id=self.source.id, series_key=series_key,
            country_iso3=country_iso3, metric=metric, value=value, unit=unit,
            period_start=period_start, period_end=period_end, period_label=period_label, frequency=frequency, **kw,
        )
        self.counters.count(outcome)
        self._track_period(kw.get("published_at"), period_label, period_start)
        return row

    def add_weather(self, *, series_key: str, region_key: str, country_iso3: str, period_start: date,
                    period_end: date, period_label: str, frequency: str = "M", **kw) -> WeatherObservation:
        kw = self._common(kw)
        outcome, row = ingest.record(
            self.session, WeatherObservation, source_id=self.source.id, series_key=series_key,
            region_key=region_key, country_iso3=country_iso3, period_start=period_start, period_end=period_end,
            period_label=period_label, frequency=frequency, **kw,
        )
        self.counters.count(outcome)
        return row

    def add_report(self, *, report_key: str, title: str, url: str, published_at: date | None = None,
                   period_label: str | None = None, raw_document_id: int | None = None,
                   narrative: str | None = None) -> tuple[Report, bool]:
        """Register an official report release. Returns (report, is_new)."""
        existing = self.session.scalars(
            select(Report).where(Report.source_id == self.source.id, Report.report_key == report_key)
        ).first()
        if existing:
            if narrative and not existing.narrative:
                existing.narrative = narrative
            if raw_document_id and not existing.raw_document_id:
                existing.raw_document_id = raw_document_id
            return existing, False
        r = Report(
            source_id=self.source.id, report_key=report_key, title=title[:500], url=url, published_at=published_at,
            period_label=period_label, raw_document_id=raw_document_id or None, narrative=narrative,
        )
        self.session.add(r)
        self.session.flush()
        self.counters.count("new")
        self._track_period(published_at, None, None)
        return r, True

    def add_regulation(self, *, reference: str, jurisdiction: str, doc_type: str, title: str, url: str,
                       published_at: date | None = None, **kw) -> tuple[RegulationItem, bool]:
        existing = self.session.scalars(
            select(RegulationItem).where(RegulationItem.source_id == self.source.id, RegulationItem.reference == reference)
        ).first()
        if existing:
            self.counters.count("unchanged")
            return existing, False
        r = RegulationItem(source_id=self.source.id, reference=reference, jurisdiction=jurisdiction,
                           doc_type=doc_type, title=title[:1000], url=url, published_at=published_at, **kw)
        self.session.add(r)
        self.session.flush()
        self.counters.count("new")
        self._track_period(published_at, None, None)
        return r, True

    def add_news(self, **kw):
        """Store a news item (dedup, tagging and relevance handled by services.news)."""
        from ..services import news as news_service

        article, outcome = news_service.ingest_article(self.session, self.source, **kw)
        self.counters.count(outcome)
        if article is not None and article.published_at:
            self._track_period(article.published_at.date(), None, None)
        return article

    def close(self) -> None:
        if self._own_client:
            self.client.close()


class Collector(ABC):
    """Base class. Subclasses set the metadata attributes and implement `collect`."""

    key: str
    name: str
    publisher: str
    homepage: str
    kind: SourceKind
    reliability: Reliability
    category: str                       # prices | trade | production | news | regulation | weather | fx | reports
    country_iso3: str | None = None
    language: str | None = None
    expected_update: str = ""
    expected_max_age_days: int | None = None
    terms_note: str = ""
    requires_key: str | None = None     # name of the Settings attribute holding the key
    key_optional: bool = False          # True if the collector works (reduced) without the key
    # APScheduler trigger: {"trigger": "cron", "hour": 6, "minute": 30} or {"trigger": "interval", "hours": 3}
    schedule: dict = {"trigger": "interval", "hours": 12}
    # Lower runs first in "collect all" (FX must precede prices so conversions work).
    order: int = 50

    @classmethod
    def source_spec(cls) -> dict:
        return {
            "key": cls.key, "name": cls.name, "publisher": cls.publisher, "homepage": cls.homepage,
            "kind": cls.kind, "reliability": cls.reliability, "category": cls.category,
            "country_iso3": cls.country_iso3, "language": cls.language, "expected_update": cls.expected_update,
            "expected_max_age_days": cls.expected_max_age_days, "terms_note": cls.terms_note,
            "requires_key": cls.requires_key,
        }

    def key_value(self, settings: Settings) -> str | None:
        return getattr(settings, self.requires_key) if self.requires_key else None

    @abstractmethod
    def collect(self, ctx: CollectContext) -> None:
        ...


def _guess_ext(url: str, ctype: str | None) -> str:
    ctype = (ctype or "").lower()
    path = urlparse(url).path.lower()
    for ext in (".pdf", ".xlsx", ".xls", ".csv", ".json", ".xml", ".zip", ".html", ".txt"):
        if path.endswith(ext):
            return ext
    if "pdf" in ctype:
        return ".pdf"
    if "json" in ctype:
        return ".json"
    if "xml" in ctype or "rss" in ctype or "atom" in ctype:
        return ".xml"
    if "csv" in ctype:
        return ".csv"
    if "spreadsheet" in ctype or "excel" in ctype:
        return ".xlsx"
    if "zip" in ctype:
        return ".zip"
    if "html" in ctype:
        return ".html"
    return ".bin"


def month_bounds(year: int, month: int) -> tuple[date, date]:
    import calendar

    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def year_bounds(year: int) -> tuple[date, date]:
    return date(year, 1, 1), date(year, 12, 31)


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    from dateutil import parser as dparser

    try:
        return dparser.parse(value, dayfirst=False).date()
    except (ValueError, OverflowError):
        return None


def to_datetime(d: date | datetime | None) -> datetime | None:
    if d is None or isinstance(d, datetime):
        return d
    return datetime(d.year, d.month, d.day)
