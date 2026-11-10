"""Corrections made by a person (services/corrections.py, corrections_sync.py, corrections_ai.py,
api/corrections.py): applied as new revisions with derived fields recomputed, undone by a new
revision, kept or superseded when the source is read again, exchanged between two computers through a
git branch (temporary bare repositories only), applied idempotently with conflicts shown, interpreted
from plain words with a mocked AI, and shown as `correction` in the API answers."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from test_alerts import PRICE_RULE, make_rule
from test_alerts import add_price as alert_price
from test_alerts import add_trade as alert_trade
from test_alerts import events as rule_events
from test_assistant import _context, _reply, add_quote, ask, facts_of, llm_on, market  # noqa: F401  (fixtures, as in test_api_memo.py)

from paladex.collectors.base import month_bounds, year_bounds
from paladex.models import (
    AlertEvent,
    DataQualityIssue,
    FxRate,
    PriceObservation,
    ProductionStat,
    Source,
    SupplierQuote,
    TradeFlowObservation,
)
from paladex.models_corrections import CorrectionEvent
from paladex.services import corrections as svc
from paladex.services import fx, ingest

TODAY = date.today()
_idx = TODAY.year * 12 + TODAY.month - 1 - 2          # a closed month, two months ago
PY, PM = _idx // 12, _idx % 12 + 1
PERIOD = f"{PY}-{PM:02d}"
YEAR = TODAY.year - 1
USD_PER_EUR = 1.10
LB = ingest.KG_PER_UNIT["lb"]
HAS_GIT = shutil.which("git") is not None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def make_sources(db) -> dict[str, Source]:
    out = {}
    for key, cat in (("t_usda", "prices"), ("t_indec", "trade"), ("t_fao", "production")):
        s = Source(key=key, name=f"Fonte {key}", name_en=f"Source {key}", publisher="Test publisher", kind="api",
                   reliability="official", category=cat, expected_max_age_days=400)
        db.add(s)
        out[cat] = s
    db.flush()
    return out


def add_fx(db) -> None:
    start, end = month_bounds(PY, PM)
    d = start
    while d <= end:
        if d.weekday() < 5:
            db.add(FxRate(rate_date=d, currency="USD", per_eur=USD_PER_EUR))
        d += timedelta(days=1)
    db.flush()


def price(db, src: Source, value: float, *, unit: str = "lb", currency: str = "USD", origin: str = "ARG",
          low: float | None = None, high: float | None = None, demo: bool = False, period: str = PERIOD):
    """As collectors/base.py add_price stores it (per kg + FX conversions)."""
    start, end = month_bounds(int(period[:4]), int(period[5:]))
    outcome, row = ingest.record(
        db, PriceObservation, source_id=src.id, is_demo=demo,
        series_key=f"wholesale_bulk|{origin}|white|{period}", price_type="wholesale_bulk", origin_iso3=origin,
        origin_label=origin, market_iso3="USA", variety="polyflora", color_grade="white", organic=False,
        terms="bulk, drums", price_value=value, price_low=low, price_high=high, currency=currency, unit=unit,
        price_per_kg=round(ingest.per_kg(value, unit), 6), period_start=start, period_end=end, period_label=period,
        frequency="M", published_at=end + timedelta(days=10), source_url="https://example.org/usda.pdf",
        data_status="demo" if demo else "published", reliability="demo" if demo else "official")
    if outcome != "unchanged" or row.usd_per_kg is None:
        fx.normalise_price(db, row)
    db.flush()
    return outcome, row


def trade(db, src: Source, kg: float, value: float, *, reporter: str = "ARG", period: str = PERIOD):
    start, end = month_bounds(int(period[:4]), int(period[5:]))
    outcome, row = ingest.record(
        db, TradeFlowObservation, source_id=src.id, series_key=f"indec|{reporter}|WLD|export|{period}",
        hs_code="0409", reporter_iso3=reporter, partner_iso3="WLD", flow="export", net_weight_kg=kg, value=value,
        currency="USD", value_basis="FOB", unit_value_per_kg=round(value / kg, 4), period_start=start,
        period_end=end, period_label=period, frequency="M", published_at=end + timedelta(days=20),
        source_url="https://example.org/indec.xlsx", data_status="published", reliability="official")
    if outcome != "unchanged" or row.usd_value is None:
        fx.normalise_trade(db, row)
    db.flush()
    return outcome, row


def production(db, src: Source, value: float, *, iso3: str = "ARG", year: int = YEAR, unit: str = "t"):
    start, end = year_bounds(year)
    return ingest.record(
        db, ProductionStat, source_id=src.id, series_key=f"faostat|QCL|{iso3}|production|{year}",
        country_iso3=iso3, metric="production", value=value, unit=unit, flag_raw="A", period_start=start,
        period_end=end, period_label=str(year), frequency="A", published_at=end + timedelta(days=300),
        data_status="published", reliability="official")


def series_rows(db, model, row) -> list:
    return list(db.scalars(select(model).where(model.series_key == row.series_key).order_by(model.revision)))


@pytest.fixture()
def data(db):
    srcs = make_sources(db)
    add_fx(db)
    _, p = price(db, srcs["prices"], 1.795)
    _, t = trade(db, srcs["trade"], 8_035_260.0, 23_686_271.62)
    _, pr = production(db, srcs["production"], 69_297.65)
    db.commit()
    return {"src": srcs, "price": p, "trade": t, "production": pr}


# ---------------------------------------------------------------------------
# Apply and revert, per table
# ---------------------------------------------------------------------------


def test_price_correction_is_a_new_revision_with_derived_fields(db, data):
    official = data["price"]
    ev = svc.create_event(db, "value_correction", table="price_observations", row_id=official.id,
                          value="3,40", unit="kg", currency="USD", reason="Listino dell'importatore")
    db.commit()
    rows = series_rows(db, PriceObservation, official)
    assert [r.revision for r in rows] == [1, 2] and [r.is_current for r in rows] == [False, True]
    old, new = rows
    assert old.price_value == 1.795 and old.reliability == "official"            # official kept as it was
    assert new.supersedes_id == old.id and new.reliability == "user" and new.data_status == "user_entered"
    assert new.unit == "lb" and new.currency == "USD"                            # the series' own unit
    assert new.price_value == pytest.approx(3.4 * LB, abs=1e-6)
    assert new.price_per_kg == pytest.approx(3.4) and new.usd_per_kg == pytest.approx(3.4)
    assert new.eur_per_kg == pytest.approx(3.4 / USD_PER_EUR, abs=1e-3)           # ECB period average
    assert new.fx_basis == "period_avg" and new.price_low is None and new.price_high is None
    assert new.source_url == old.source_url and new.published_at == old.published_at
    assert new.value_hash == ingest.value_hash(PriceObservation, {k: getattr(new, k) for k in ingest.VALUE_FIELDS[PriceObservation]})
    corr = new.extra["correction"]
    assert corr["event_id"] == ev.event_id and corr["author"] == "Utente" and corr["official_value"] == 1.795
    assert corr["official_row_id"] == old.id and corr["official_hash"] == old.value_hash
    assert corr["reason"] == "Listino dell'importatore"
    assert "Valore corretto da Utente" in new.notes and "1,795 USD/lb" in new.notes and "inserito come 3,40 USD/kg" in new.notes
    assert ev.status == "applied" and ev.applied_row_id == new.id and ev.sync_status == "pending_sync"
    assert ev.entered == {"value": 3.4, "low": None, "high": None, "unit": "kg", "currency": "USD"}
    assert ev.official_hash == old.value_hash and ev.target_unit == "lb" and ev.official_value == 1.795


def test_price_entered_in_euro_is_converted_with_the_period_rate(db, data):
    ev = svc.create_event(db, "value_correction", table="price_observations", row_id=data["price"].id,
                          value=3.1, unit="kg", currency="EUR", low=3.0, high=3.2)
    new = db.get(PriceObservation, ev.applied_row_id)
    assert new.currency == "USD" and new.unit == "lb"
    assert new.usd_per_kg == pytest.approx(3.1 * USD_PER_EUR, abs=1e-3)
    assert new.price_low == pytest.approx(3.0 * USD_PER_EUR * LB, abs=1e-5)
    assert new.price_high == pytest.approx(3.2 * USD_PER_EUR * LB, abs=1e-5)
    assert ev.entered["currency"] == "EUR" and ev.entered["value"] == 3.1


def test_trade_correction_recomputes_unit_value_and_usd(db, data):
    t = data["trade"]
    ev = svc.create_event(db, "value_correction", table="trade_flows", row_id=t.id, value="7500", unit="t",
                          reason="Dato INDEC rettificato")
    new = db.get(TradeFlowObservation, ev.applied_row_id)
    assert new.net_weight_kg == 7_500_000 and new.value == t.value
    assert new.unit_value_per_kg == round(t.value / 7_500_000, 4) and new.usd_value == t.value
    assert new.eur_value == pytest.approx(t.value / USD_PER_EUR, rel=1e-3)
    assert ev.target_field == "net_weight_kg" and ev.official_value == 8_035_260.0
    ev2 = svc.create_event(db, "value_correction", table="trade_flows", row_id=t.id, value=21_000_000, currency="USD",
                           field="value")
    newer = db.get(TradeFlowObservation, ev2.applied_row_id)
    # the second correction replaces the first; the official value stays the one it is compared with
    assert newer.value == 21_000_000 and newer.net_weight_kg == t.net_weight_kg
    assert newer.unit_value_per_kg == round(21_000_000 / t.net_weight_kg, 4)
    assert ev.status == "replaced" and ev2.status == "applied" and newer.extra["correction"]["official_row_id"] == t.id
    assert [r.revision for r in series_rows(db, TradeFlowObservation, t)] == [1, 2, 3]


def test_production_correction_converts_units(db, data):
    p = data["production"]
    ev = svc.create_event(db, "value_correction", table="production_stats", row_id=p.id, value=72_000_000, unit="kg")
    new = db.get(ProductionStat, ev.applied_row_id)
    assert new.value == 72_000 and new.unit == "t" and new.flag_raw is None and new.reliability == "user"
    with pytest.raises(svc.CorrectionError) as e:
        svc.create_event(db, "value_correction", table="production_stats", row_id=p.id, value=5, unit="lb", currency="USD")
    assert e.value.code == "unit_mismatch"


@pytest.mark.parametrize("table", ["price_observations", "trade_flows", "production_stats"])
def test_revert_restores_the_official_values_as_a_new_revision(db, data, table):
    key = {"price_observations": "price", "trade_flows": "trade", "production_stats": "production"}[table]
    official = data[key]
    model = svc.TABLES[table]
    ev = svc.create_event(db, "value_correction", table=table, row_id=official.id, value=2.5,
                          unit={"price_observations": "kg", "trade_flows": "t", "production_stats": "t"}[table])
    rev = svc.create_revert(db, ev.event_id, reason="Mi ero sbagliato")
    db.commit()
    rows = series_rows(db, model, official)
    assert [r.revision for r in rows] == [1, 2, 3] and [r.is_current for r in rows] == [False, False, True]
    restored = rows[2]
    assert restored.value_hash == official.value_hash and restored.reliability == "official"
    assert restored.data_status == "published" and restored.collected_at == official.collected_at
    assert restored.extra["reverted_correction"]["event_id"] == ev.event_id
    assert svc.row_correction(restored) is None and rows[1].reliability == "user"     # history intact
    assert ev.status == "reverted" and rev.status == "applied" and rev.applied_row_id == restored.id
    with pytest.raises(svc.CorrectionError) as e:
        svc.create_revert(db, ev.event_id)
    assert e.value.code == "not_revertible"


def test_demo_rows_same_values_and_missing_figures_are_refused(db, data):
    _, demo = price(db, data["src"]["prices"], 2.0, demo=True, origin="UKR")
    for kwargs, code in (({"row_id": demo.id, "value": 3}, "demo_row"),
                         ({"row_id": 999_999, "value": 3}, "not_found"),
                         ({"row_id": data["price"].id, "value": 1.795, "unit": "lb"}, "same_as_official"),
                         ({"row_id": data["price"].id, "value": None}, "missing_value"),
                         ({"row_id": data["price"].id, "value": 3, "currency": "XYZ"}, "fx_unavailable")):
        with pytest.raises(svc.CorrectionError) as e:
            svc.create_event(db, "value_correction", table="price_observations", **kwargs)
        assert e.value.code == code
    with pytest.raises(svc.CorrectionError) as e:
        svc.create_event(db, "value_correction", table="weather_observations", row_id=1, value=3)
    assert e.value.code == "unsupported_table"


def test_flag_wrong_opens_an_issue_and_note_is_kept(db, data):
    ev = svc.create_event(db, "flag_wrong", table="price_observations", row_id=data["price"].id,
                          reason="Troppo basso per l'Argentina")
    issue = db.get(DataQualityIssue, ev.issue_id)
    assert ev.status == "recorded" and issue.issue_type == "user_flag" and issue.resolved_at is None
    assert issue.entity_type == "price_observations" and issue.entity_id == data["price"].id
    assert "Troppo basso" in issue.message_it and issue.details["event_id"] == ev.event_id
    assert len(series_rows(db, PriceObservation, data["price"])) == 1                  # the figure is not changed
    note = svc.create_event(db, "note", country_iso3="arg", text="Raccolto in ritardo per la siccità")
    assert note.status == "recorded" and note.country_iso3 == "ARG" and note.reason.startswith("Raccolto")
    svc.create_revert(db, ev.event_id)
    assert issue.resolved_at is not None and ev.status == "reverted"
    with pytest.raises(svc.CorrectionError) as e:
        svc.create_event(db, "note", text="senza paese")
    assert e.value.code == "missing_country"


# ---------------------------------------------------------------------------
# Ingest policy
# ---------------------------------------------------------------------------


def test_source_reread_with_the_same_official_value_keeps_the_correction(db, data):
    official = data["price"]
    ev = svc.create_event(db, "value_correction", table="price_observations", row_id=official.id, value=3.4, unit="kg")
    db.commit()
    seen_before = official.last_seen_at
    outcome, row = price(db, data["src"]["prices"], 1.795)          # the collector reads the same figure again
    assert outcome == "unchanged" and row.id == ev.applied_row_id and row.is_current
    assert official.last_seen_at >= seen_before and not official.is_current
    assert ev.status == "applied" and len(series_rows(db, PriceObservation, official)) == 2
    assert db.scalars(select(AlertEvent)).first() is None


def test_source_publishing_a_new_value_wins_with_a_notice(db, data):
    official = data["price"]
    ev = svc.create_event(db, "value_correction", table="price_observations", row_id=official.id, value=3.4, unit="kg",
                          reason="Prezzo reale")
    db.commit()
    outcome, row = price(db, data["src"]["prices"], 1.85)              # USDA revises its figure
    db.commit()
    assert outcome == "revised" and row.is_current and row.reliability == "official" and row.price_value == 1.85
    assert row.supersedes_id == ev.applied_row_id and row.revision == 3
    assert ev.status == "superseded_by_source" and ev.status_detail["new_official_value"] == 1.85
    alert = db.scalars(select(AlertEvent).where(AlertEvent.dedup_key.like("correction:%"))).one()
    assert alert.title_it == "La fonte ha pubblicato un nuovo valore dopo la correzione di Utente"
    assert alert.ref_type == "price" and alert.ref_id == row.id and alert.severity == "warning"
    assert svc.row_correction(row) is None
    with pytest.raises(svc.CorrectionError):
        svc.create_revert(db, ev.event_id)                            # nothing in force to undo


def test_collector_writers_follow_the_policy(db, data):
    """The same through the collectors' own writers (CollectContext.add_price / add_trade)."""
    import httpx

    from paladex.collectors.base import CollectContext

    t = data["trade"]
    ev_t = svc.create_event(db, "value_correction", table="trade_flows", row_id=t.id, value=7500, unit="t")
    ev_p = svc.create_event(db, "value_correction", table="price_observations", row_id=data["price"].id,
                            value=3.4, unit="kg")
    start, end = month_bounds(PY, PM)
    with httpx.Client() as client:
        ctx = CollectContext(db, data["src"]["trade"], client=client)
        row = ctx.add_trade(series_key=t.series_key, reporter_iso3="ARG", partner_iso3="WLD", flow="export",
                            currency="USD", period_start=start, period_end=end, period_label=PERIOD, frequency="M",
                            net_weight_kg=8_035_260.0, value=23_686_271.62, hs_code="0409", value_basis="FOB",
                            published_at=end + timedelta(days=20), source_url="https://example.org/indec.xlsx")
        assert ctx.counters.new == 0 and ctx.counters.revised == 0 and row.id == ev_t.applied_row_id
        pctx = CollectContext(db, data["src"]["prices"], client=client)
        kw = {"series_key": f"ARG|white|{PERIOD}", "price_type": "wholesale_bulk", "variety": "polyflora",
              "currency": "USD", "unit": "lb", "period_start": start, "period_end": end, "period_label": PERIOD,
              "frequency": "M", "origin_iso3": "ARG", "origin_label": "ARG", "market_iso3": "USA",
              "color_grade": "white", "organic": False, "terms": "bulk, drums",
              "published_at": end + timedelta(days=10), "source_url": "https://example.org/usda.pdf"}
        same = pctx.add_price(price_value=1.795, **kw)
        assert same.id == ev_p.applied_row_id and same.usd_per_kg == pytest.approx(3.4)
        moved = pctx.add_price(price_value=1.70, **kw)
    assert pctx.counters.revised == 1 and moved.is_current and moved.reliability == "official"
    assert moved.price_per_kg == pytest.approx(1.70 / LB, abs=1e-5) and moved.usd_per_kg == pytest.approx(1.70 / LB, abs=1e-3)
    assert ev_p.status == "superseded_by_source" and ev_t.status == "applied"


def test_source_publishing_the_corrected_value_confirms_it(db, data):
    official = data["production"]
    ev = svc.create_event(db, "value_correction", table="production_stats", row_id=official.id, value=72_000)
    outcome, row = production(db, data["src"]["production"], 72_000)
    assert outcome == "revised" and row.reliability == "official" and ev.status == "confirmed_by_source"


def test_source_withdrawing_a_corrected_series(db, data):
    ev = svc.create_event(db, "value_correction", table="production_stats", row_id=data["production"].id, value=1)
    assert ingest.retire(db, ProductionStat, source_id=data["src"]["production"].id,
                         series_key=data["production"].series_key) == 1
    assert ev.status == "superseded_by_source" and ev.status_detail["withdrawn"] is True


# ---------------------------------------------------------------------------
# Received events: idempotent, conflicts
# ---------------------------------------------------------------------------


def remote_doc(db, row, value, *, table="price_observations", unit="kg", official_hash=None, author="Mario",
               created=None) -> dict:
    """The JSON another computer would have written for a correction of `row`."""
    model = svc.TABLES[table]
    norm = svc.normalize(db, table, row, value=value, unit=unit)
    ev = CorrectionEvent(event_id=str(uuid.uuid4()), created_at=created or svc.utcnow().replace(microsecond=0),
                         author=author, device_id="f" * 32, kind="value_correction",
                         source_key=db.get(Source, row.source_id).key, reason="dal telefono",
                         entered=norm["entered"], corrected_value=norm["main"],
                         normalized=svc._jsonable({k: norm["fields"][k] for k in ingest.VALUE_FIELDS[model]}),
                         **svc._target_columns(table, row, norm["field"]))
    if official_hash:
        ev.official_hash = official_hash
    return svc.to_document(ev)


def test_received_event_applies_once(db, data):
    doc = remote_doc(db, data["price"], 3.4)
    doc = json.loads(json.dumps(doc))                       # as read from the git file
    res = svc.import_documents(db, [doc])
    assert res["received"] == 1 and res["applied"] == {"applied": 1}
    ev = svc.get_event(db, doc["event_id"])
    assert ev.origin == "remote" and ev.sync_status == "received" and ev.author == "Mario"
    row = db.get(PriceObservation, ev.applied_row_id)
    assert row.is_current and row.extra["correction"]["author"] == "Mario"
    assert svc.import_documents(db, [doc]) == {"received": 0, "invalid": 0, "applied": {}}
    assert len(series_rows(db, PriceObservation, data["price"])) == 2
    assert svc.import_documents(db, [{"format": "x"}, {**doc, "event_id": "not-a-uuid"}])["invalid"] == 2


def test_received_event_conflicts_when_the_official_value_differs(db, data):
    doc = remote_doc(db, data["price"], 3.4, official_hash="0" * 64)
    svc.import_documents(db, [doc])
    ev = svc.get_event(db, doc["event_id"])
    assert ev.status == "conflict" and ev.status_detail["official_now"] == 1.795
    assert len(series_rows(db, PriceObservation, data["price"])) == 1          # not applied
    notice = db.scalars(select(AlertEvent).where(AlertEvent.dedup_key == f"correction:{ev.event_id}:conflict")).one()
    assert "Mario" in notice.title_it
    svc.import_documents(db, [])                                               # retried: still a conflict, one notice
    assert ev.status == "conflict" and db.scalars(select(AlertEvent)).all() == [notice]


def test_received_event_after_the_source_moved_on(db, data):
    doc = remote_doc(db, data["price"], 3.4)                  # made on the official 1.795
    price(db, data["src"]["prices"], 1.9)                     # this computer already has the source's new value
    svc.import_documents(db, [doc])
    ev = svc.get_event(db, doc["event_id"])
    assert ev.status == "superseded_by_source" and ev.status_detail["official_now"] == 1.9


def test_received_event_waits_for_the_figure_and_order_decides(db, data):
    srcs = data["src"]
    _, other = price(db, srcs["prices"], 1.5, origin="UKR")
    doc = remote_doc(db, other, 2.0)
    doc["target"]["series_key"] = "wholesale_bulk|MEX|white|" + PERIOD        # not on this computer yet
    svc.import_documents(db, [doc])
    ev = svc.get_event(db, doc["event_id"])
    assert ev.status == "waiting"
    price(db, srcs["prices"], 1.5, origin="MEX")
    svc.import_documents(db, [])
    assert ev.status == "applied"
    # two computers corrected the same figure: the newer correction is the one in force, everywhere
    t0 = svc.utcnow().replace(microsecond=0)
    older = remote_doc(db, data["price"], 3.0, created=t0 - timedelta(hours=1), author="Anna")
    newer = remote_doc(db, data["price"], 3.6, created=t0, author="Mario")
    svc.import_documents(db, [newer])
    svc.import_documents(db, [older])
    cur = ingest.current_row(db, PriceObservation, srcs["prices"].id, data["price"].series_key)
    assert cur.extra["correction"]["author"] == "Mario"
    assert svc.get_event(db, older["event_id"]).status == "replaced"


def test_received_correction_and_its_undo_together(db, data):
    doc = remote_doc(db, data["price"], 3.4)
    undo = {"format": svc.FORMAT, "version": 1, "event_id": str(uuid.uuid4()), "kind": "revert",
            "created_at": doc["created_at"], "author": "Mario", "device_id": "f" * 32,
            "reverts_event_id": doc["event_id"], "target": doc["target"], "correction": {}}
    svc.import_documents(db, [undo, doc])
    rows = series_rows(db, PriceObservation, data["price"])
    assert [r.reliability for r in rows] == ["official", "user", "official"] and rows[-1].is_current
    assert svc.get_event(db, doc["event_id"]).status == "reverted"


# ---------------------------------------------------------------------------
# Git synchronisation (temporary bare repositories only)
# ---------------------------------------------------------------------------


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True,
                          env={**svc_env(), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}).stdout


def svc_env() -> dict:
    from paladex.services.corrections_sync import git_env

    return git_env()


@pytest.fixture()
def computers(tmp_path, monkeypatch):
    """A bare 'GitHub' repository and three clones, each with its own database (pc1, pc2, phone)."""
    if not HAS_GIT:
        pytest.skip("git not installed")
    from paladex import config
    from paladex import db as dbmod

    monkeypatch.setenv("PALADEX_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PALADEX_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("PALADEX_LLM_PROVIDER", "none")
    monkeypatch.setenv("PALADEX_CORRECTIONS_SYNC", "true")
    remote = tmp_path / "github.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", "-q", str(remote), str(seed)], check=True, capture_output=True)
    (seed / "README.md").write_text("paladex\n")
    _git(seed, "add", "README.md")
    _git(seed, "commit", "-q", "-m", "program")
    _git(seed, "push", "-q", "origin", "HEAD")
    pcs = {}
    for name in ("pc1", "pc2", "phone"):
        clone = tmp_path / name
        subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True, capture_output=True)
        pcs[name] = {"repo": clone, "db": tmp_path / f"{name}.sqlite3"}

    def use(name: str):
        monkeypatch.setenv("PALADEX_CORRECTIONS_GIT_DIR", str(pcs[name]["repo"]))
        config.get_settings.cache_clear()
        if dbmod._engine is not None:
            dbmod._engine.dispose()
        dbmod.init_db(f"sqlite:///{pcs[name]['db']}")
        return dbmod.session_scope

    for name in pcs:          # every computer holds the same official figures
        with use(name)() as s:
            srcs = make_sources(s)
            add_fx(s)
            price(s, srcs["prices"], 1.795)
            production(s, srcs["production"], 69_297.65)
    yield {"use": use, "remote": remote, "pcs": pcs}
    if dbmod._engine is not None:
        dbmod._engine.dispose()
    dbmod._engine = None
    config.get_settings.cache_clear()


def _current(s, model):
    return s.scalars(select(model).where(model.is_current.is_(True))).one()


def _branch_files(remote: Path) -> list[str]:
    return sorted(_git(remote, "ls-tree", "-r", "--name-only", "paladex-corrections").split())


def test_two_computers_exchange_corrections_through_git(computers):
    from paladex.services import corrections_sync as cs

    use, remote = computers["use"], computers["remote"]
    pc1 = computers["pcs"]["pc1"]["repo"]
    head_before = _git(pc1, "rev-parse", "HEAD")
    with use("pc1")() as s:
        ev = svc.create_event(s, "value_correction", table="price_observations",
                              row_id=_current(s, PriceObservation).id, value=3.4, unit="kg", reason="vero prezzo")
        eid = ev.event_id
    res = cs.sync_now()
    assert res["ok"] and res["last_pushed"] == 1
    files = _branch_files(remote)
    assert files == ["README.md", f"events/{TODAY.year}/{eid}.json"]
    doc = json.loads(_git(remote, "show", f"paladex-corrections:events/{TODAY.year}/{eid}.json"))
    assert doc["event_id"] == eid and doc["target"]["official_value"] == 1.795 and "status" not in doc
    # the program's own branch, index and working tree are untouched
    assert _git(pc1, "rev-parse", "HEAD") == head_before and _git(pc1, "status", "--porcelain") == ""
    with use("pc1")() as s:
        assert svc.get_event(s, eid).sync_status == "synced"

    with use("pc2")() as s:
        assert _current(s, PriceObservation).reliability == "official"
    res = cs.sync_now()
    assert res["ok"] and res["last_received"]["received"] == 1
    with use("pc2")() as s:
        cur = _current(s, PriceObservation)
        assert cur.reliability == "user" and cur.usd_per_kg == pytest.approx(3.4)
        assert cur.extra["correction"]["event_id"] == eid
        ev2 = svc.get_event(s, eid)
        assert ev2.origin == "remote" and ev2.status == "applied"
        # pc2 undoes it; pc1 follows
        rev_id = svc.create_revert(s, eid).event_id
    assert cs.sync_now()["ok"]
    assert cs.sync_now()["last_received"]["received"] == 0                     # idempotent
    use("pc1")
    assert cs.sync_now()["last_received"]["received"] == 1
    with use("pc1")() as s:
        assert _current(s, PriceObservation).reliability == "official"
        assert svc.get_event(s, eid).status == "reverted" and svc.get_event(s, rev_id).origin == "remote"


def test_rejected_push_is_rebuilt_on_the_new_tip(computers):
    from paladex.services import corrections_sync as cs

    use, remote = computers["use"], computers["remote"]
    use("pc1")
    assert cs.sync_now()["ok"]                    # nothing yet: the branch does not exist
    assert cs.availability()[0].remote_tip() is None
    with use("pc2")() as s:
        e2 = svc.create_event(s, "value_correction", table="production_stats",
                              row_id=_current(s, ProductionStat).id, value=70_000).event_id
    git2 = cs.availability()[0]
    stale_tip = git2.remote_tip()                  # pc2 read the branch (absent) ...
    with use("pc1")() as s:
        e1 = svc.create_event(s, "value_correction", table="price_observations",
                              row_id=_current(s, PriceObservation).id, value=3.4, unit="kg").event_id
    assert cs.sync_now()["ok"]                     # ... then pc1 pushed first
    use("pc2")
    pushed, tip = cs._push(git2, stale_tip)        # rejected, rebuilt on pc1's commit, pushed
    assert pushed == 1 and tip == git2.remote_tip()
    assert _branch_files(remote) == sorted(["README.md", f"events/{TODAY.year}/{e1}.json",
                                            f"events/{TODAY.year}/{e2}.json"])
    with use("pc2")() as s:
        assert svc.get_event(s, e1).status == "applied"            # pc1's event applied on the way
        assert _current(s, PriceObservation).reliability == "user"
    log = _git(remote, "log", "--format=%P", "paladex-corrections").split("\n")
    assert len([x for x in log if x.strip()]) == 1                 # linear history: one parent link


def test_no_network_or_credentials_keeps_events_pending(computers, tmp_path):
    from paladex.services import corrections_sync as cs

    use = computers["use"]
    repo = computers["pcs"]["pc1"]["repo"]
    _git(repo, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
    with use("pc1")() as s:
        eid = svc.create_event(s, "value_correction", table="price_observations",
                               row_id=_current(s, PriceObservation).id, value=3.4, unit="kg").event_id
    res = cs.sync_now()
    assert not res["ok"] and res["error"]["code"] in ("git_error", "credentials", "network")
    with use("pc1")() as s:
        ev = svc.get_event(s, eid)
        assert ev.sync_status == "pending_sync" and ev.sync_error
        st = cs.status(s)
        assert st["pending"] == 1 and st["error"]["code"] == res["error"]["code"] and st["enabled"]
    # not a git checkout at all
    def _writable(func, path, _exc):     # git's object files are read-only: on Windows they cannot be deleted as is
        os.chmod(path, 0o700)
        func(path)

    shutil.rmtree(repo / ".git", onerror=_writable)
    res = cs.sync_now()
    assert not res["ok"] and res["error"]["code"] == "not_a_checkout"
    with use("pc1")() as s:
        assert svc.get_event(s, eid).sync_status == "pending_sync"


def test_phone_copy_only_reads_the_branch(computers, monkeypatch):
    from paladex import cli
    from paladex.services import corrections_sync as cs

    use, remote = computers["use"], computers["remote"]
    with use("pc1")() as s:
        eid = svc.create_event(s, "value_correction", table="price_observations",
                               row_id=_current(s, PriceObservation).id, value=3.4, unit="kg").event_id
    assert cs.sync_now()["ok"]
    tip = _git(remote, "rev-parse", "paladex-corrections")
    with use("phone")() as s:
        local = svc.create_event(s, "note", country_iso3="ARG", text="non deve uscire").event_id
    assert cli.main(["corrections-apply", "--from-git"]) == 0
    assert _git(remote, "rev-parse", "paladex-corrections") == tip               # never pushed
    with use("phone")() as s:
        assert _current(s, PriceObservation).extra["correction"]["event_id"] == eid
        assert svc.get_event(s, local).sync_status == "pending_sync"


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_api_create_list_revert_and_sync_state(api, db, data):
    body = {"kind": "value_correction", "target": {"table": "price_observations", "row_id": data["price"].id},
            "value": "3,40", "unit": "kg", "currency": "USD", "reason": "listino"}
    res = api.post("/api/corrections", json=body)
    assert res.status_code == 201, res.text
    out = res.json()
    ev = out["event"]
    assert ev["status"] == "applied" and ev["made_here"] and ev["revertible"] and ev["sync"]["state"] == "pending_sync"
    assert out["figure"]["reliability"] == "user" and out["figure"]["correction"]["event_id"] == ev["event_id"]
    lst = api.get("/api/corrections").json()
    assert lst["total"] == 1 and lst["items"][0]["event_id"] == ev["event_id"] and lst["pending_sync"] == 1
    by_fig = api.get("/api/corrections", params={"table": "price_observations", "row_id": data["price"].id}).json()
    assert by_fig["total"] == 1
    assert api.get(f"/api/corrections/{ev['event_id']}").json()["status"] == "applied"
    res = api.post(f"/api/corrections/{ev['event_id']}/revert", json={"reason": "errore mio"})
    assert res.status_code == 201 and res.json()["reverted"]["status"] == "reverted"
    assert res.json()["figure"]["reliability"] == "official"
    assert api.post(f"/api/corrections/{ev['event_id']}/revert").status_code == 409
    st = api.get("/api/corrections/sync").json()
    assert st["enabled"] is False and st["reason"] == "disabled" and st["pending"] == 2
    assert api.post("/api/corrections/sync").json()["ok"] is False
    # errors carry a stable code
    bad = api.post("/api/corrections", json={**body, "unit": "furlong"})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "unit_mismatch"
    assert api.post("/api/corrections", json={**body, "target": {"table": "price_observations", "row_id": 9999}}).status_code == 404
    note = api.post("/api/corrections", json={"kind": "note", "country_iso3": "ARG", "text": "siccità a Entre Ríos"})
    assert note.status_code == 201
    notes = api.get("/api/corrections", params={"kind": "note", "country": "ARG", "status": "recorded"}).json()
    assert [n["text"] for n in notes["items"]] == ["siccità a Entre Ríos"]


def test_api_author_setting(api, db):
    assert api.get("/api/corrections/settings").json()["author"] == "Utente"
    assert api.put("/api/corrections/settings", json={"author": "  Mario   Parodi "}).json()["author"] == "Mario Parodi"
    assert api.get("/api/corrections/settings").json()["author"] == "Mario Parodi"


def test_api_writes_are_local_only(api, db, data):
    cross = {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"}
    body = {"target": {"table": "price_observations", "row_id": data["price"].id}, "value": 9, "unit": "kg"}
    assert api.post("/api/corrections", json=body, headers=cross).status_code == 403
    assert api.post("/api/corrections/sync", headers=cross).status_code == 403
    assert api.post("/api/corrections/interpret", json={"text": "x"}, headers=cross).status_code == 403
    assert api.get("/api/corrections", headers={"Host": "evil.example"}).status_code == 400
    assert db.scalars(select(CorrectionEvent)).first() is None


# ---------------------------------------------------------------------------
# Provenance: the `correction` object in the answers
# ---------------------------------------------------------------------------


def test_prices_answers_carry_the_correction(api, db, data):
    ev = svc.create_event(db, "value_correction", table="price_observations", row_id=data["price"].id,
                          value=3.4, unit="kg", reason="listino")
    db.commit()
    q = {"price_type": "wholesale_bulk", "origin": "ARG", "currency": "USD"}
    series = api.get("/api/prices/series", params=q).json()["series"]
    assert len(series) == 1
    s = series[0]
    assert s["correction"]["event_id"] == ev.event_id and s["correction"]["official_value"] == 1.795
    pt = s["points"][-1]
    assert pt["value"] == pytest.approx(3.4) and pt["correction"]["author"] == "Utente"
    assert pt["data_status"] == "user_entered"
    latest = api.get("/api/prices/latest", params=q).json()["rows"][0]
    assert latest["correction"]["reason"] == "listino" and latest["latest"]["correction"]["event_id"] == ev.event_id
    obs = api.get("/api/prices/observations", params={"price_type": "wholesale_bulk"}).json()["rows"]
    assert obs[0]["correction"]["unit"] == "lb" and obs[0]["reliability"] == "user"
    # history: the official row is still there, marked as such
    rev = api.get("/api/archive/revisions", params={"kind": "price", "price_type": "wholesale_bulk",
                                                     "origin": "ARG"}).json()
    entries = rev["periods"][0]["revisions"]
    assert [e["reliability"] for e in entries] == ["official", "user"]
    assert entries[0]["correction"] is None and entries[1]["correction"]["event_id"] == ev.event_id
    # without corrections, nothing is added to the points
    svc.create_revert(db, ev.event_id)
    db.commit()
    s = api.get("/api/prices/series", params=q).json()["series"][0]
    assert s["correction"] is None and "correction" not in s["points"][-1]


def test_trade_and_production_answers_carry_the_correction(api, db, data):
    t_ev = svc.create_event(db, "value_correction", table="trade_flows", row_id=data["trade"].id, value=7_500, unit="t")
    p_ev = svc.create_event(db, "value_correction", table="production_stats", row_id=data["production"].id,
                            value=72_000, reason="dato del ministero")
    db.commit()
    tr = api.get("/api/trade/series", params={"reporter": "ARG", "flow": "export", "freq": "M"}).json()
    pt = tr["series"][0]["points"][-1]
    assert pt["net_weight_kg"] == 7_500_000 and pt["correction"]["event_id"] == t_ev.event_id
    assert pt["correction"]["rows"] == 1 and pt["correction"]["part_of_total"] is False
    assert pt["reliability"] == "user" and pt["data_status"] == "user_entered"
    prod = api.get("/api/archive/production", params={"country": "ARG"}).json()
    point = prod["series"][0]["points"][-1]
    assert point["value"] == 72_000 and point["correction"]["reason"] == "dato del ministero"
    table = api.get("/api/harvest/production", params={"scope": "all"}).json()
    arg = json.dumps(table)
    assert p_ev.event_id in arg and "dato del ministero" in arg
    profile = api.get("/api/countries/ARG")
    assert profile.status_code == 200, profile.text
    metrics = profile.json()["production"]["metrics"]
    prod_series = next(m for m in metrics if m["metric"] == "production")["series"][0]
    assert prod_series["latest"]["correction"]["event_id"] == p_ev.event_id


# ---------------------------------------------------------------------------
# AI interpretation (provider mocked)
# ---------------------------------------------------------------------------


@pytest.fixture()
def ai_on(monkeypatch, db):
    from paladex import config
    from paladex.services import llm

    monkeypatch.setenv("PALADEX_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("PALADEX_ANTHROPIC_API_KEY", "sk-test")
    config.get_settings.cache_clear()
    calls: list[dict] = []
    answer: dict = {}

    def fake(system, user, schema_hint=None, max_tokens=1024, *, settings=None, client=None):
        calls.append({"system": system, "user": user})
        return dict(answer)

    monkeypatch.setattr(llm, "complete_json", fake)
    yield {"calls": calls, "answer": answer}
    config.get_settings.cache_clear()


def test_interpret_without_ai_key_is_409(api, db):
    res = api.post("/api/corrections/interpret", json={"text": "il prezzo è sbagliato", "lang": "it"})
    assert res.status_code == 409 and res.json()["detail"]["code"] == "ai_unavailable"


def test_interpret_resolves_real_candidates(api, db, data, ai_on):
    month_it = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
                "ottobre", "novembre", "dicembre"][PM - 1]
    ai_on["answer"].update(route="correction", kind="value_correction", table="price_observations",
                           country_iso3="ARG", price_type="wholesale_bulk", period=PERIOD, old_value=3.96,
                           new_value=3.4, unit="kg", currency="USD", reason="listino importatore",
                           summary="Prezzo argentino", variety="polyflora")
    text = f"Parodi Group: il prezzo del miele argentino di {month_it} non è 3,96 ma 3,40 dollari al chilo"
    res = api.post("/api/corrections/interpret", json={"text": text, "lang": "it"})
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["route"] == "correction" and out["kind"] == "value_correction"
    assert "Parodi" not in ai_on["calls"][0]["user"] and "[azienda]" in ai_on["calls"][0]["user"]
    c = out["candidates"][0]
    assert c["row_id"] == data["price"].id and c["matches_old_value"]          # 1.795 USD/lb = 3.957 USD/kg
    assert c["current"]["value"] == 1.795 and c["current"]["unit"] == "lb"
    assert c["proposal"]["to"] == pytest.approx(3.4 * LB, abs=1e-6)
    create = c["proposal"]["create"]
    assert create["target"] == {"table": "price_observations", "row_id": data["price"].id}
    assert db.scalars(select(CorrectionEvent)).first() is None                 # nothing written
    # the interface confirms: the proposal is the request body
    done = api.post("/api/corrections", json={**create, "ai_interpretation": out["ai_interpretation"]})
    assert done.status_code == 201 and done.json()["event"]["ai_interpretation"]["understood"]["new_value"] == 3.4


def test_interpret_never_invents_numbers_and_uses_the_context(api, db, data, ai_on):
    ai_on["answer"].update(route="correction", kind="value_correction", table="production_stats",
                           country_iso3="ARG", new_value=99_999, metric="production", summary="x")
    res = api.post("/api/corrections/interpret",
                   json={"text": "questo dato della produzione è sbagliato, è più alto",
                         "context": {"table": "production_stats", "row_id": data["production"].id}}).json()
    assert res["understood"]["new_value"] is None and res["kind"] == "flag_wrong"
    assert [c["row_id"] for c in res["candidates"]] == [data["production"].id]
    assert res["candidates"][0]["proposal"]["create"]["kind"] == "flag_wrong"
    ai_on["answer"].update(new_value=72, kind="value_correction")
    res = api.post("/api/corrections/interpret",
                   json={"text": "sono 72 mila tonnellate", "context": {"table": "production_stats",
                                                                       "row_id": data["production"].id}}).json()
    assert res["understood"]["new_value"] == 72 and res["candidates"][0]["proposal_error"] is None


def test_interpret_routes_supplier_offers_without_calling_the_ai(api, db, data, ai_on):
    db.add(SupplierQuote(supplier_name="Apícola del Sur", origin_iso3="ARG", variety="polyflora",
                         price_per_kg=3.2, currency="USD", date_received=TODAY))
    db.commit()
    for text in ("Il fornitore ci ha offerto miele argentino a 3,20", "Apícola del Sur chiede 3,30 per il millefiori"):
        out = api.post("/api/corrections/interpret", json={"text": text}).json()
        assert out["route"] == "quotes" and out["candidates"] == []
    assert ai_on["calls"] == []
    ai_on["answer"].update(route="quotes", summary="offerta")
    out = api.post("/api/corrections/interpret", json={"text": "Mi propongono 3,10 per 20 tonnellate"}).json()
    assert out["route"] == "quotes" and len(ai_on["calls"]) == 1 and out["candidates"] == []


def test_interpret_note(api, db, data, ai_on):
    ai_on["answer"].update(route="correction", kind="note", country_iso3="ARG",
                           note_text="Raccolto in ritardo per la siccità", summary="nota")
    out = api.post("/api/corrections/interpret", json={"text": "In Argentina il raccolto è in ritardo per la siccità"}).json()
    assert out["note"]["country_iso3"] == "ARG" and out["note"]["create"]["kind"] == "note"
    res = api.post("/api/corrections", json=out["note"]["create"])
    assert res.status_code == 201 and res.json()["event"]["text"] == "Raccolto in ritardo per la siccità"


def test_starter_snapshot_never_carries_corrections(db, data, tmp_path):
    import sqlite3

    from paladex.config import get_settings

    p, t = data["price"], data["trade"]
    svc.create_event(db, "value_correction", table="price_observations", row_id=p.id, value=3.4, unit="kg")
    svc.create_event(db, "value_correction", table="price_observations", row_id=p.id, value=3.5, unit="kg")
    ev = svc.create_event(db, "value_correction", table="trade_flows", row_id=t.id, value=1, unit="t")
    svc.create_revert(db, ev.event_id)
    db.commit()
    copy = tmp_path / "copy.sqlite3"
    src = sqlite3.connect(get_settings().db_path)
    dst = sqlite3.connect(copy)
    src.backup(dst)
    src.close()
    assert svc.strip_from_snapshot(dst) == 3
    dst.commit()
    rows = dst.execute("SELECT id, is_current, supersedes_id, reliability FROM price_observations ORDER BY id").fetchall()
    assert rows == [(p.id, 1, None, "official")]
    trows = dst.execute("SELECT id, is_current, supersedes_id, reliability FROM trade_flows ORDER BY id").fetchall()
    assert trows[0] == (t.id, 0, None, "official") and trows[1][1:] == (1, t.id, "official")   # the undo's copy
    dst.close()


# ---------------------------------------------------------------------------
# Assistant: corrections are market data stated as corrected, never supplier offers
# ---------------------------------------------------------------------------

@pytest.fixture()
def clock(monkeypatch):
    """The assistant's fixed clock, as in test_assistant.py (its market fixture is built on it)."""
    import test_assistant as TA

    monkeypatch.setattr(TA.A, "clock_today", lambda: TA.TODAY)
    monkeypatch.setattr(TA.A, "clock_now", lambda: TA.NOW)


def _corrected_argentina(db) -> CorrectionEvent:
    row = db.scalars(select(PriceObservation).where(
        PriceObservation.is_current.is_(True), PriceObservation.origin_iso3 == "ARG",
        PriceObservation.price_type == "wholesale_bulk").order_by(PriceObservation.period_start.desc())).first()
    assert row.price_value == 4.05
    ev = svc.create_event(db, "value_correction", table="price_observations", row_id=row.id, value=4.30, unit="kg",
                          reason="listino degli importatori")
    db.commit()
    return ev


def test_assistant_states_a_correction_with_the_market_data(market, clock):
    add_quote(market, "Apicultores del Sur SA", "ARG", 3.20, notes="sconto riservato")
    market.commit()
    ev = _corrected_argentina(market)
    ans = ask(market, "Cosa sta succedendo ai prezzi del miele argentino?")
    w = next(p for p in facts_of(ans, "price") if p["price_type"] == "wholesale_bulk")
    assert w["status"] == "corrected" and w["status_label"].startswith("Corretto da Utente il ")
    assert "4,30 USD/kg" in w["text"] and "Valore corretto da Utente il" in w["text"]
    assert "valore ufficiale della fonte: 4,05 USD/kg" in w["text"] and "listino degli importatori" in w["text"]
    assert w["correction"]["event_id"] == ev.event_id and w["correction"]["official_value"] == 4.05
    assert w["source"]["key"] == "usda_honey_report" and not w["private"]
    # with the market data, not with the offers (which this question does not even retrieve)
    section = next(s for s in ans["sections"] if any(w["id"] in i["refs"] for i in s["items"]))
    assert section["key"] == "verified" and all(s["key"] != "quotes" for s in ans["sections"])
    assert not facts_of(ans, "quote") and not ans["private_data_used"]
    # supplier offers keep their own status, section and privacy
    offers = ask(market, "Confronta queste offerte")
    quotes = facts_of(offers, "quote")
    assert quotes and all(q["private"] and q["status"] == "user" and q["status_label"] == "Inserito da voi"
                          and q["correction"] is None for q in quotes)
    assert offers["sections"][0]["key"] == "quotes"
    quote_ids = {q["id"] for q in quotes}
    assert all(set(i["refs"]) <= quote_ids for i in offers["sections"][0]["items"])


def test_assistant_trade_fact_states_the_correction(market, clock):
    import test_assistant as TA

    year = TA.TODAY.year - 1
    row = market.scalars(select(TradeFlowObservation).where(
        TradeFlowObservation.reporter_iso3 == "ARG", TradeFlowObservation.period_label == str(year))).one()
    ev = svc.create_event(market, "value_correction", table="trade_flows", row_id=row.id, value=85_000, unit="t",
                          reason="dato SENASA")
    market.commit()
    ans = ask(market, "Quanto miele ha esportato l'Argentina?")
    t = next(f for f in facts_of(ans, "trade") if f["period_label"] == str(year))
    assert t["status"] == "corrected" and t["correction"]["event_id"] == ev.event_id
    assert "85.000 t" in t["text"] and "Valore corretto da Utente il" in t["text"]
    assert "valore ufficiale della fonte: 81.820 t" in t["text"] and "dato SENASA" in t["text"]


def test_assistant_tells_the_ai_who_corrected_and_the_official_value(market, clock, llm_on):
    import respx

    from paladex.services import llm

    add_quote(market, "Apicultores del Sur SA", "ARG", 3.20)
    market.commit()
    _corrected_argentina(market)
    seen: dict = {}

    def model(request):
        _, ctx = _context(request)
        seen["body"], seen["ctx"] = request.content.decode(), ctx
        block = next(b for b in ctx if b["status"].startswith("Corrected by"))
        seen["block"] = block
        return _reply({"sections": [{"key": "verified", "sentences": [
            {"text": "Il prezzo all'ingrosso è 4,30 USD/kg, corretto da Utente (valore ufficiale 4,05 USD/kg).",
             "refs": [block["id"]]}]}]})

    with respx.mock() as mock:
        mock.post(llm.ANTHROPIC_URL).mock(side_effect=model)
        ans = ask(market, "Cosa sta succedendo ai prezzi del miele argentino?")
    block = seen["block"]
    assert block["source"] != "(entered by the user)" and "valore ufficiale della fonte: 4,05 USD/kg" in block["text"]
    assert "Apicultores" not in seen["body"] and "Offerta A" not in seen["body"]
    assert ans["ai_used"] and not ans["sent_private_to_ai"]
    kept = [i["text"] for s in ans["sections"] for i in s["items"]]
    assert any("corretto da Utente" in t for t in kept)


# ---------------------------------------------------------------------------
# Alerts: a correction is not the source publishing
# ---------------------------------------------------------------------------


def test_price_alert_never_fires_on_a_correction(db):
    from paladex.enums import AlertType
    from paladex.services import alerts

    alert_price(db, "2026-06", 1.40)
    alert_price(db, "2026-07", 1.50)
    aug = alert_price(db, "2026-08", 1.52)                     # +1.3 %: below the 5 % rule
    rule = make_rule(db, AlertType.PRICE_CHANGE, PRICE_RULE)
    svc.create_event(db, "value_correction", table="price_observations", row_id=aug.id, value=1.80)   # +20 %
    alerts.evaluate_all(db)
    assert rule_events(db, rule) == []
    alert_price(db, "2026-08", 1.65)                           # the source revises its own figure: +10 %
    alerts.evaluate_all(db)
    evs = rule_events(db, rule)
    assert len(evs) == 1 and "1,65" in evs[0].body_it
    # the only rule-less notice is the correction's own one
    notices = db.scalars(select(AlertEvent).where(AlertEvent.rule_id.is_(None))).all()
    assert [n.dedup_key.split(":")[-1] for n in notices] == ["source"]


def test_trade_alert_never_fires_on_a_correction(db):
    from paladex.enums import AlertType
    from paladex.services import alerts

    params = {"reporter": "EU27", "partner": "WLD", "flow": "import", "threshold_pct": 20, "freq": "M",
              "direction": "any"}
    base = alert_trade(db, "2025-08", 10_000_000)
    rule = make_rule(db, AlertType.TRADE_CHANGE, params)
    aug = alert_trade(db, "2026-08", 10_500_000)               # +5 %
    alerts.evaluate_all(db)
    assert rule_events(db, rule) == []
    svc.create_event(db, "value_correction", table="trade_flows", row_id=aug.id, value=14_000, unit="t")   # +40 %
    alerts.evaluate_all(db)
    assert rule_events(db, rule) == []
    # a corrected year-ago figure is never the comparison base either
    base_ev = svc.create_event(db, "value_correction", table="trade_flows", row_id=base.id, value=5_000, unit="t")
    alerts.evaluate_all(db)
    assert rule_events(db, rule) == []
    alert_trade(db, "2026-08", 13_000_000)                     # the source's own revision (over the correction): +30 %
    alert_trade(db, "2025-08", 10_000_000)                     # same official year-ago value: its correction stays
    alerts.evaluate_all(db)
    assert rule_events(db, rule) == []
    pv = alerts.preview(db, AlertType.TRADE_CHANGE, params)
    assert pv["checked"][0]["reason"] == "no_previous"
    svc.create_revert(db, base_ev.event_id)                    # undone: the official base is back (not new data)
    alerts.evaluate_all(db)
    evs = rule_events(db, rule)
    assert len(evs) == 1 and "13.000 t" in evs[0].body_it and "10.000 t" in evs[0].body_it


def test_sync_is_off_by_default_and_switched_on_only_on_screen(api, tmp_path, monkeypatch):
    """No computer, copy of the folder or test run publishes corrections unless someone switched the
    exchange on, on that computer (incident 6 Nov 2026: a test server pushed test events)."""
    from paladex.config import Settings, get_settings
    from paladex.services import corrections_sync

    monkeypatch.delenv("PALADEX_CORRECTIONS_SYNC", raising=False)
    env = tmp_path / ".env"
    env.write_text("", encoding="utf-8")
    monkeypatch.setenv("PALADEX_ENV_FILE", str(env))
    get_settings.cache_clear()
    assert Settings(_env_file=str(env)).corrections_sync is False
    assert corrections_sync.availability()[1] == "disabled"
    assert corrections_sync.sync_in_background() is None
    assert api.get("/api/corrections/settings").json()["sync_enabled"] is False

    r = api.put("/api/corrections/settings", json={"sync": True})
    assert r.status_code == 200 and r.json()["sync_enabled"] is True
    assert "PALADEX_CORRECTIONS_SYNC=true" in env.read_text(encoding="utf-8")
    r = api.put("/api/corrections/settings", json={"sync": False})
    assert r.json()["sync_enabled"] is False
    assert "PALADEX_CORRECTIONS_SYNC=false" in env.read_text(encoding="utf-8")
    get_settings.cache_clear()


def test_the_test_events_pushed_by_mistake_are_never_applied(computers, monkeypatch):
    """The 9 development test events found on the real branch on 6 Nov 2026 are ignored by id:
    an event on the branch whose id is in the list is never received nor applied."""
    from paladex.services import corrections_sync as cs

    assert len(cs.IGNORED_EVENT_IDS) == 9 and "43831269-2249-46ef-a9ac-c9f069c04dc0" in cs.IGNORED_EVENT_IDS
    use = computers["use"]
    with use("pc1")() as s:
        eid = svc.create_event(s, "value_correction", table="price_observations",
                               row_id=_current(s, PriceObservation).id, value=3.4, unit="kg", reason="test").event_id
    assert cs.sync_now()["last_pushed"] == 1
    monkeypatch.setattr(cs, "IGNORED_EVENT_IDS", cs.IGNORED_EVENT_IDS | {eid})
    use("pc2")
    res = cs.sync_now()
    assert res["ok"] and res["last_received"]["received"] == 0
    with use("pc2")() as s:
        assert _current(s, PriceObservation).reliability == "official"
        assert svc.get_event(s, eid) is None
