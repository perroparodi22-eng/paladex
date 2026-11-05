"""Starter data (services/starter.py): real data shipped with the app, merged once per version.

The rules under test: provenance and revision history are kept exactly; local data always wins;
nothing private (quotes, alerts, settings, runs, demo rows, raw files) is ever shipped; a second
start does nothing; collectors re-reading the same figures find them "unchanged".
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from paladex.db import Base
from paladex.models import (
    AlertRule,
    AppSetting,
    CollectionRun,
    FxRate,
    NewsArticle,
    PriceObservation,
    ProductionStat,
    RawDocument,
    RegulationItem,
    Report,
    Source,
    SupplierQuote,
    TariffMeasure,
    TradeFlowObservation,
    utcnow,
)
from paladex.models_companies import CompanyRecord, record_company
from paladex.services import ingest, starter

COLLECTED = datetime(2026, 11, 4, 20, 35, 12)


def _price(series_key: str, value: float, **kw) -> dict:
    base = dict(
        price_type="wholesale_bulk", origin_iso3="ARG", market_iso3="USA", variety="polyflora",
        price_value=value, currency="USD", unit="lb", price_per_kg=round(value / 0.45359237, 4),
        period_start=date(2026, 9, 1), period_end=date(2026, 9, 30), period_label="2026-09", frequency="M",
        published_at=date(2026, 10, 30), source_url="https://www.ams.usda.gov/mnreports/fvmhoney.pdf",
        data_status="published", reliability="official",
    )
    base.update(kw)
    return base


@pytest.fixture()
def cloud_db(db, tmp_path):
    """A second, independent Paladex database standing for the one the snapshot is built from.
    Its source ids deliberately differ from the local ones (sources inserted in reverse order)."""
    path = tmp_path / "cloud" / "paladex.sqlite3"
    path.parent.mkdir()
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    local_sources = db.scalars(select(Source).order_by(Source.id.desc())).all()
    with Session(engine) as s:
        for src in local_sources:
            s.add(Source(key=src.key, name=src.name, kind=src.kind, reliability=src.reliability,
                         category=src.category, enabled=src.enabled,
                         last_run_at=COLLECTED, last_run_status="success", last_success_at=COLLECTED))
        s.flush()
        sid = {x.key: x.id for x in s.scalars(select(Source))}
        usda, fao, eurlex = sid["usda_honey_report"], sid["faostat"], sid["eurlex_honey"]
        s.query(Source).filter(Source.key == "usda_honey_report").update(
            {"latest_published_at": date(2026, 10, 30), "latest_period_label": "2026-09",
             "latest_period_start": date(2026, 9, 1), "last_new_data_at": COLLECTED})
        raw = RawDocument(source_id=usda, url="https://x", content_hash="h", path="usda/x.pdf", size_bytes=1)
        s.add(raw)
        s.flush()
        # Series A: published, then revised by the publisher (two revisions, one chain).
        ingest.record(s, PriceObservation, source_id=usda, series_key="A", raw_document_id=raw.id, **_price("A", 2.10))
        ingest.record(s, PriceObservation, source_id=usda, series_key="A", **_price("A", 2.15))
        # Series B: the local database will already hold it (with another value).
        ingest.record(s, PriceObservation, source_id=usda, series_key="B", **_price("B", 1.80, origin_iso3="BRA"))
        # A demo row must never be shipped.
        ingest.record(s, PriceObservation, source_id=usda, series_key="A", is_demo=True, **_price("A", 9.99))
        ingest.record(s, TradeFlowObservation, source_id=fao, series_key="T1", reporter_iso3="ARG", partner_iso3="WLD",
                      flow="export", net_weight_kg=78_375_000.0, value=170_800_000.0, currency="USD", value_basis="FOB",
                      period_start=date(2024, 1, 1), period_end=date(2024, 12, 31), period_label="2024", frequency="A",
                      published_at=date(2026, 7, 24), data_status="published", reliability="official")
        ingest.record(s, ProductionStat, source_id=fao, series_key="P1", country_iso3="ARG", metric="production",
                      value=73_000.0, unit="t", flag_raw="A", period_start=date(2024, 1, 1), period_end=date(2024, 12, 31),
                      period_label="2024", frequency="A", published_at=date(2025, 12, 31),
                      data_status="published", reliability="official")
        # A company as an official register publishes it (Uruguay XXI SIE: exact FOB per year).
        record_company(s, source_id=sid["uy_sie_honey_exporters"], series_key="UY:NECTARBEE:export:2025",
                      country_iso3="URY", company_name="NECTARBEE S.A.", role="exporter", hs_code="0409",
                      measure_kind="exact_value", value=15_571_168.32, currency="USD", value_basis="FOB",
                      period_start=date(2025, 1, 1), period_end=date(2025, 12, 31), period_label="2025", frequency="A",
                      published_at=date(2026, 11, 5), data_status="published", reliability="official")
        for model in (PriceObservation, TradeFlowObservation, ProductionStat, CompanyRecord):
            for row in s.scalars(select(model)):
                row.collected_at = COLLECTED
                row.last_seen_at = COLLECTED
        s.add_all([
            FxRate(rate_date=date(2026, 11, 4), currency="USD", per_eur=1.0712),
            FxRate(rate_date=date(2026, 11, 3), currency="USD", per_eur=1.0698),
            Report(source_id=usda, report_key="2026-10-30", title="National Honey Report", url="https://r",
                   published_at=date(2026, 10, 30), collected_at=COLLECTED, raw_document_id=raw.id),
            RegulationItem(source_id=eurlex, jurisdiction="EU", doc_type="regulation", reference="32001L0110",
                           title="Honey Directive", url="https://eur-lex", collected_at=COLLECTED),
            TariffMeasure(source_id=sid["eu_tariff_xi"], series_key="EU:ARG:mfn", value_hash="v", jurisdiction="EU",
                          origin_iso3="ARG", hs_code="0409000000", measure_type="mfn", duty_text="17.30 %",
                          ad_valorem_pct=17.3, as_of=date(2026, 11, 4), collected_at=COLLECTED),
            SupplierQuote(supplier_name="Private supplier", origin_iso3="ARG", variety="polyflora", price_per_kg=3.0,
                          currency="USD", date_received=date(2026, 11, 1)),
            AlertRule(name="private rule", alert_type="price_change", params={}),
            AppSetting(key="collector_state:usda_honey_report", value={"x": 1}),
            CollectionRun(source_id=usda, status="success", started_at=COLLECTED, finished_at=COLLECTED),
        ])
        s.flush()
        first = NewsArticle(source_id=sid["news_ec_agri"], url="https://n/1", canonical_url="https://n/1",
                            title="Honey market", title_norm="honey market", collected_at=COLLECTED)
        s.add(first)
        s.flush()
        s.add(NewsArticle(source_id=sid["news_ec_agri"], url="https://n/2?utm=x", canonical_url="https://n/2",
                          title="Honey market", title_norm="honey market", collected_at=COLLECTED,
                          duplicate_of_id=first.id))
        s.commit()
    engine.dispose()
    return path


@pytest.fixture()
def built(cloud_db, tmp_path, monkeypatch):
    out = tmp_path / "starter" / "paladex-starter.sqlite3.xz"
    meta = starter.build(cloud_db, out)
    monkeypatch.setenv("PALADEX_STARTER_DATA_PATH", str(out))
    from paladex import config

    config.get_settings.cache_clear()
    return out, meta


def test_snapshot_ships_only_data_never_private_rows(built):
    out, meta = built
    assert meta["counts"]["price_observations"] == 3          # A rev1 + rev2, B; not the demo row
    assert meta["counts"]["trade_flows"] == 1 and meta["counts"]["production_stats"] == 1
    assert meta["counts"]["company_records"] == 1
    assert meta["data_collected_until"] == "2026-11-04T20:35:12"
    assert json.loads(starter.meta_path(out).read_text())["sha256"] == meta["sha256"]
    import lzma

    raw = out.with_name("check.sqlite3")
    raw.write_bytes(lzma.decompress(out.read_bytes()))
    c = sqlite3.connect(raw)
    for table in ("supplier_quotes", "alert_rules", "app_settings", "collection_runs", "raw_documents"):
        assert c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
    assert c.execute("SELECT COUNT(*) FROM price_observations WHERE is_demo = 1").fetchone()[0] == 0
    assert c.execute("SELECT COUNT(*) FROM price_observations WHERE raw_document_id IS NOT NULL").fetchone()[0] == 0
    assert c.execute("SELECT COUNT(*) FROM sources WHERE last_run_at IS NOT NULL").fetchone()[0] == 0
    c.close()


def test_import_keeps_provenance_history_and_local_data_wins(db, built):
    usda = db.scalars(select(Source).where(Source.key == "usda_honey_report")).one()
    # The local database already holds series B (collected on this computer): it must win.
    ingest.record(db, PriceObservation, source_id=usda.id, series_key="B", **_price("B", 1.95, origin_iso3="BRA"))
    db.commit()

    res = starter.import_if_needed()
    assert res is not None
    assert res["inserted"]["price_observations"] == 2 and res["kept_local"]["price_observations"] == 1
    db.expire_all()

    a = db.scalars(select(PriceObservation).where(PriceObservation.series_key == "A").order_by(PriceObservation.revision)).all()
    assert [(r.revision, r.price_value, r.is_current, r.is_demo) for r in a] == [(1, 2.10, False, False), (2, 2.15, True, False)]
    assert a[1].supersedes_id == a[0].id                       # chain remapped to the new ids
    assert all(r.source_id == usda.id for r in a)              # source mapped by key, not by id
    assert all(r.collected_at == COLLECTED for r in a)         # original collection time kept
    assert all(r.raw_document_id is None for r in a)
    assert a[1].source_url == "https://www.ams.usda.gov/mnreports/fvmhoney.pdf" and a[1].published_at == date(2026, 10, 30)

    b = db.scalars(select(PriceObservation).where(PriceObservation.series_key == "B")).all()
    assert [r.price_value for r in b] == [1.95]                 # untouched local row, nothing added

    assert db.scalar(select(TradeFlowObservation.net_weight_kg)) == 78_375_000.0
    assert db.scalar(select(ProductionStat.value)) == 73_000.0
    assert sorted(db.scalars(select(FxRate.rate_date))) == [date(2026, 11, 3), date(2026, 11, 4)]
    assert db.scalar(select(Report.title)) == "National Honey Report"
    assert db.scalar(select(RegulationItem.reference)) == "32001L0110"
    assert db.scalar(select(TariffMeasure.duty_text)) == "17.30 %"
    company = db.scalars(select(CompanyRecord)).one()
    uy = db.scalars(select(Source).where(Source.key == "uy_sie_honey_exporters")).one()
    assert (company.company_name, company.value, company.source_id) == ("NECTARBEE S.A.", 15_571_168.32, uy.id)
    assert company.collected_at == COLLECTED and company.is_current
    news = {n.canonical_url: n for n in db.scalars(select(NewsArticle))}
    assert news["https://n/2"].duplicate_of_id == news["https://n/1"].id

    # Nothing private, nothing about the other machine's runs.
    assert db.scalar(select(SupplierQuote.id)) is None
    assert db.scalar(select(AlertRule.id).where(AlertRule.name == "private rule")) is None
    assert db.get(AppSetting, "collector_state:usda_honey_report") is None
    assert db.scalar(select(CollectionRun.id)) is None
    db.refresh(usda)
    assert usda.last_run_at is None and usda.last_run_status is None
    # What the data looks like is carried forward (freshness is judged on the data held).
    assert usda.latest_published_at == date(2026, 10, 30) and usda.latest_period_label == "2026-09"

    stored = db.get(AppSetting, starter.SETTING_KEY).value
    assert stored["sha256"] == built[1]["sha256"] and stored["data_collected_until"] == "2026-11-04T20:35:12"


def test_second_start_does_nothing_and_recollection_is_unchanged(db, built):
    assert starter.import_if_needed() is not None
    assert starter.import_if_needed() is None                  # same version: nothing to do
    db.expire_all()
    usda = db.scalars(select(Source).where(Source.key == "usda_honey_report")).one()
    # The collector reading the same published figure again recognises it: no duplicate row.
    outcome, _ = ingest.record(db, PriceObservation, source_id=usda.id, series_key="A", **_price("A", 2.15))
    assert outcome == "unchanged"
    assert db.scalar(select(PriceObservation.id).where(PriceObservation.series_key == "A",
                                                       PriceObservation.revision == 3)) is None


def test_merge_is_idempotent_even_without_the_version_marker(db, built):
    starter.import_if_needed()
    db.query(AppSetting).filter(AppSetting.key == starter.SETTING_KEY).delete()
    db.commit()
    res = starter.import_if_needed()                           # e.g. the marker was lost
    assert res is not None and sum(res["inserted"].values()) == 0
    assert db.query(PriceObservation).count() == 3 and db.query(NewsArticle).count() == 2


def test_no_snapshot_or_corrupted_file_never_breaks_start_up(db, tmp_path, monkeypatch, built):
    from paladex import config

    monkeypatch.setenv("PALADEX_STARTER_DATA_PATH", str(tmp_path / "missing.sqlite3.xz"))
    config.get_settings.cache_clear()
    assert starter.import_if_needed() is None

    out, _ = built
    monkeypatch.setenv("PALADEX_STARTER_DATA_PATH", str(out))
    config.get_settings.cache_clear()
    out.write_bytes(out.read_bytes()[:-10])                    # truncated download
    assert starter.import_if_needed() is None
    assert db.query(PriceObservation).count() == 0


def test_first_run_state_and_status_endpoint(db, built, api):
    st = api.get("/api/collect/status").json()["first_run"]
    assert st == {"has_data": False, "local_runs": {}, "starter": None}

    starter.import_if_needed()
    st = api.get("/api/collect/status").json()["first_run"]
    assert st["has_data"] is True and st["local_runs"] == {}
    assert st["starter"]["data_collected_until"] == "2026-11-04T20:35:12"

    usda = db.scalars(select(Source).where(Source.key == "usda_honey_report")).one()
    db.add(CollectionRun(source_id=usda.id, status="no_change", started_at=utcnow(), finished_at=utcnow()))
    db.commit()
    assert api.get("/api/collect/status").json()["first_run"]["local_runs"] == {"no_change": 1}


def test_snapshot_from_an_older_version_still_merges(db, built):
    """A snapshot built before a required column existed: the column gets its default; a table
    whose missing column has no simple default is left out instead of failing the whole import."""
    import lzma

    out, _meta = built
    raw = out.with_name("old.sqlite3")
    raw.write_bytes(lzma.decompress(out.read_bytes()))
    c = sqlite3.connect(raw)
    c.execute("ALTER TABLE price_observations DROP COLUMN organic")      # NOT NULL, default False
    c.execute("ALTER TABLE reports DROP COLUMN collected_at")            # NOT NULL, default = now (no literal)
    c.commit()
    c.close()
    out.write_bytes(lzma.compress(raw.read_bytes()))
    meta = json.loads(starter.meta_path(out).read_text())
    meta["sha256"] = starter._sha256(out)
    starter.meta_path(out).write_text(json.dumps(meta))

    res = starter.import_if_needed()
    assert res is not None and res["skipped"] == ["reports"]
    assert res["inserted"]["price_observations"] == 3 and res["inserted"]["regulations"] == 1
    db.expire_all()
    assert {r.organic for r in db.scalars(select(PriceObservation))} == {False}
    assert db.scalar(select(Report.id)) is None
