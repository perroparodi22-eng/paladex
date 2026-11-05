"""Data-quality checks, quality/reports/search API."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from paladex.collectors.base import month_bounds
from paladex.enums import DataStatus, PriceType, Reliability, RunStatus, TradeFlow
from paladex.models import (
    CollectionRun,
    DataQualityIssue,
    NewsArticle,
    PriceObservation,
    RawDocument,
    RegulationItem,
    Report,
    Source,
    TradeFlowObservation,
)
from paladex.services import ingest, quality

TODAY = date(2026, 11, 2)
NOW = datetime(2026, 11, 2, 9, 0)


# --------------------------------------------------------------------------- helpers
def make_source(db, key: str, **kw) -> Source:
    spec = {"key": key, "name": kw.pop("name", f"Fonte {key}"), "publisher": kw.pop("publisher", f"Publisher {key}"),
            "homepage": f"https://example.org/{key}", "kind": "api", "reliability": Reliability.OFFICIAL.value,
            "category": kw.pop("category", "prices"), "expected_max_age_days": kw.pop("expected_max_age_days", None),
            "enabled": kw.pop("enabled", True)}
    spec.update(kw)
    s = Source(**spec)
    db.add(s)
    db.flush()
    return s


def add_price(db, src: Source, ym: tuple[int, int], value: float, *, origin="ARG", variety="polyflora",
              price_type=PriceType.WHOLESALE_BULK.value, market="USA", currency="USD", usd: float | None = None,
              is_demo=False, color=None, freq="M"):
    start, end = month_bounds(*ym)
    label = f"{ym[0]}-{ym[1]:02d}"
    return ingest.record(
        db, PriceObservation, source_id=src.id, is_demo=is_demo,
        series_key=f"{price_type}|{origin}|{variety}|{market}|{color}|{label}",
        price_type=price_type, origin_iso3=origin, market_iso3=market, variety=variety, color_grade=color,
        price_value=value, currency=currency, unit="kg", price_per_kg=value,
        usd_per_kg=usd if usd is not None else (value if currency == "USD" else None),
        period_start=start, period_end=end, period_label=label, frequency=freq, published_at=end,
        data_status=DataStatus.DEMO.value if is_demo else DataStatus.PUBLISHED.value,
        reliability=Reliability.DEMO.value if is_demo else Reliability.OFFICIAL.value,
    )[1]


def months_back(n: int, today: date = TODAY) -> tuple[int, int]:
    idx = today.year * 12 + today.month - 1 - n
    return idx // 12, idx % 12 + 1


def add_run(db, src: Source, status: str, minutes_ago: int, error: str | None = None):
    t = NOW - timedelta(minutes=minutes_ago)
    db.add(CollectionRun(source_id=src.id, status=status, trigger="test", started_at=t, finished_at=t, error=error))
    db.flush()


def issues(db, prefix: str = "", open_only=True) -> dict[str, DataQualityIssue]:
    q = select(DataQualityIssue)
    if open_only:
        q = q.where(DataQualityIssue.resolved_at.is_(None))
    return {i.dedup_key: i for i in db.scalars(q) if i.dedup_key.startswith(prefix)}


def run(db, today=TODAY, now=NOW):
    res = quality.run_checks(db, today=today, now=now)
    db.flush()
    return res


# --------------------------------------------------------------------------- (a) stale
def test_stale_thresholds_and_auto_resolve(db):
    ok = make_source(db, "fresh_src", expected_max_age_days=10, latest_published_at=TODAY - timedelta(days=15))
    warn = make_source(db, "late_src", expected_max_age_days=10, latest_published_at=TODAY - timedelta(days=16))
    crit = make_source(db, "dead_src", expected_max_age_days=10, latest_published_at=TODAY - timedelta(days=31))
    make_source(db, "off_src", expected_max_age_days=10, enabled=False, latest_published_at=TODAY - timedelta(days=90))
    make_source(db, "never_src", expected_max_age_days=10)
    run(db)
    found = issues(db, "stale:")
    assert set(found) == {"stale:late_src", "stale:dead_src"}
    assert found["stale:late_src"].severity == "warning"
    assert found["stale:dead_src"].severity == "critical"
    assert "31 giorni" in found["stale:dead_src"].message_it and "31 days" in found["stale:dead_src"].message_en
    assert found["stale:late_src"].details["age_days"] == 16
    assert ok.id not in {i.source_id for i in found.values()}

    # fresh data arrives -> resolved automatically; the row is kept with resolved_at
    warn.latest_published_at = TODAY - timedelta(days=1)
    crit.latest_published_at = None
    crit.last_new_data_at = datetime(2026, 11, 1, 6, 0)   # falls back to last_new_data_at
    stats = run(db, now=NOW + timedelta(hours=1))
    assert stats["resolved"] >= 2
    assert issues(db, "stale:") == {}
    resolved = issues(db, "stale:", open_only=False)
    assert resolved["stale:late_src"].resolved_at == NOW + timedelta(hours=1)

    # it comes back -> reopened (same row, no duplicate)
    warn.latest_published_at = TODAY - timedelta(days=40)
    stats = run(db, now=NOW + timedelta(hours=2))
    assert stats["reopened"] == 1
    row = issues(db, "stale:")["stale:late_src"]
    assert row.id == resolved["stale:late_src"].id and row.severity == "critical"
    assert db.scalar(select(DataQualityIssue).where(DataQualityIssue.dedup_key == "stale:late_src")) is not None


# --------------------------------------------------------------- (b) collection failed
def test_collection_failures_ignore_offline(db):
    one = make_source(db, "one_fail")
    add_run(db, one, RunStatus.SUCCESS, 300)
    add_run(db, one, RunStatus.FAILED, 10, error="HTTP 404 for https://example.org/x.pdf")
    three = make_source(db, "three_fail")
    for i, st in enumerate([RunStatus.FAILED, RunStatus.OFFLINE, RunStatus.FAILED, RunStatus.OFFLINE, RunStatus.FAILED]):
        add_run(db, three, st, 100 - i * 10, error="CollectorError: Timeout fetching https://x")
    offline = make_source(db, "only_offline")
    for i in range(4):
        add_run(db, offline, RunStatus.OFFLINE, 50 - i, error="No internet connection")
    recovered = make_source(db, "recovered")
    add_run(db, recovered, RunStatus.FAILED, 60, error="boom")
    add_run(db, recovered, RunStatus.NO_CHANGE, 5)
    run(db)
    found = issues(db, "collect:")
    assert set(found) == {"collect:one_fail", "collect:three_fail"}
    assert found["collect:one_fail"].severity == "warning"
    assert "documento non si trova più" in found["collect:one_fail"].message_it
    assert found["collect:three_fail"].severity == "critical"
    assert found["collect:three_fail"].details["consecutive_failures"] == 3
    assert "non ha risposto in tempo" in found["collect:three_fail"].message_it

    add_run(db, one, RunStatus.SUCCESS, 1)
    run(db)
    assert "collect:one_fail" not in issues(db, "collect:")


# ------------------------------------------------------------------ (c) missing API key
def test_missing_key_info_issue(db, monkeypatch):
    src = make_source(db, "keyed_src", name="USDA MyMarketNews", requires_key="usda_mmn_api_key",
                      last_run_status=RunStatus.SKIPPED.value)
    make_source(db, "keyed_disabled", requires_key="usda_mmn_api_key", enabled=False)
    run(db)
    found = issues(db, "key:")
    assert "key:keyed_src" in found and "key:keyed_disabled" not in found
    i = found["key:keyed_src"]
    assert i.severity == "info" and i.issue_type == "missing"
    assert "PALADEX_USDA_MMN_API_KEY=" in i.message_it and ".env" in i.message_it
    assert "https://mymarketnews.ams.usda.gov" in i.message_en
    assert i.details["env_var"] == "PALADEX_USDA_MMN_API_KEY"

    from paladex import config

    monkeypatch.setenv("PALADEX_USDA_MMN_API_KEY", "abc")
    config.get_settings.cache_clear()
    run(db)
    assert "key:keyed_src" not in issues(db, "key:")
    assert src.id  # source untouched


# ----------------------------------------------------------------------- (d) outliers
def test_outlier_relative_and_robust_z(db):
    src = make_source(db, "usda_like")
    # an old spike (now history) is NOT flagged; only each series' latest figure is judged
    values = [2.50, 2.55, 2.48, 2.52, 9.90, 2.51, 2.49, 2.53, 4.10]
    rows = [add_price(db, src, months_back(len(values) - i), v) for i, v in enumerate(values)]
    rows[6] = rows[8]          # the latest point, the one flagged below
    # a stable sibling series with normal moves: never flagged
    for i, v in enumerate([3.00, 3.06, 3.10, 3.04, 3.12, 3.18, 3.22, 3.15]):
        add_price(db, src, months_back(8 - i), v, variety="clover")
    # flat history then +12 %: flagged by robust z; +4 %: not
    for i, v in enumerate([5.0, 5.0, 5.0, 5.0, 5.6]):
        add_price(db, src, months_back(5 - i), v, variety="acacia", origin="HUN")
    for i, v in enumerate([6.0, 6.0, 6.0, 6.0, 6.24]):
        add_price(db, src, months_back(5 - i), v, variety="chestnut", origin="ITA")
    run(db)
    found = issues(db, "outlier:")
    assert set(found) == {f"outlier:price:{rows[6].id}", f"outlier:price:{_last_id(db, 'acacia')}"}
    o = found[f"outlier:price:{rows[6].id}"]
    assert o.severity == "warning" and o.entity_type == "price_observation"
    assert o.details["value"] == 4.1 and o.details["median"] == pytest.approx(2.515)
    assert o.details["period"] == rows[6].period_label and o.details["rule"] == "relative"
    assert "4,10 USD/kg contro una mediana di" in o.message_it and "(+63,0%)" in o.message_it
    assert "4.10 USD/kg against a median of" in o.message_en
    assert o.details["link"] == "/prezzi?origin=ARG&variety=polyflora&price_type=wholesale_bulk"
    z = found[f"outlier:price:{_last_id(db, 'acacia')}"]
    assert z.details["rule"] == "robust_z" and z.details["flat_history"] is True

    # the publisher corrects the value -> new revision, old issue auto-resolved
    add_price(db, src, months_back(1), 2.54)
    run(db, now=NOW + timedelta(minutes=5))
    assert f"outlier:price:{rows[6].id}" not in issues(db, "outlier:")


def _last_id(db, variety: str) -> int:
    return db.scalars(select(PriceObservation.id).where(PriceObservation.variety == variety,
                                                         PriceObservation.is_current.is_(True))
                      .order_by(PriceObservation.period_start.desc())).first()


def test_outlier_needs_history(db):
    src = make_source(db, "short")
    for i, v in enumerate([2.0, 2.0, 9.0]):
        add_price(db, src, months_back(3 - i), v)
    run(db)
    assert issues(db, "outlier:") == {}


# -------------------------------------------------------------------- (e) discrepancy
def test_discrepancy_between_sources(db):
    a = make_source(db, "src_a", name="Listino A")
    b = make_source(db, "src_b", name="Listino B")
    c = make_source(db, "src_c", name="Listino C")
    add_price(db, a, (2026, 9), 2.80, market="ITA")
    add_price(db, b, (2026, 9), 3.40, market="ITA", currency="EUR", usd=3.40)
    add_price(db, a, (2026, 8), 2.80, market="ITA")
    add_price(db, c, (2026, 8), 3.00, market="ITA")   # +7 %: fine
    add_price(db, a, (2026, 7), 2.80, market="ITA")
    add_price(db, c, (2026, 7), 4.00, market="DEU")   # different market: not comparable
    add_price(db, a, (2026, 6), 2.50, market="ITA", color="white")
    add_price(db, c, (2026, 6), 3.50, market="ITA", color="light amber")   # different colour grade: not comparable
    run(db)
    found = issues(db, "discrepancy:")
    assert len(found) == 1
    d = next(iter(found.values()))
    assert d.severity == "warning" and d.source_id is None
    assert d.details["difference_pct"] == pytest.approx(21.43, abs=0.01)
    assert [v["source_key"] for v in d.details["values"]] == ["src_a", "src_b"]
    assert "Listino A 2,80 USD/kg" in d.message_it and "Listino B 3,40 USD/kg" in d.message_it
    assert "Listino B 3.40 USD/kg" in d.message_en
    assert d.details["period"] == "2026-09"


def test_discrepancy_mixed_currency_without_fx_is_skipped(db):
    a = make_source(db, "eur_src")
    b = make_source(db, "usd_src")
    pa = add_price(db, a, (2026, 9), 2.0, currency="EUR")
    pa.usd_per_kg = None
    add_price(db, b, (2026, 9), 4.0)
    run(db)
    assert issues(db, "discrepancy:") == {}


# ------------------------------------------------------------------ (f) missing months
def test_missing_months_in_last_year(db):
    src = make_source(db, "gappy")
    for n in (10, 9, 6, 5):
        add_price(db, src, months_back(n), 3.0)
    for n in range(1, 8):
        add_price(db, src, months_back(n), 4.0, variety="acacia")
    for n in (30, 24, 23):  # gaps older than 12 months are not reported
        add_price(db, src, months_back(n), 5.0, variety="chestnut")
    run(db)
    found = issues(db, "missing:")
    assert len(found) == 1
    m = next(iter(found.values()))
    assert m.severity == "info"
    assert m.details["missing_periods"] == ["2026-03", "2026-04"]
    assert "mancano 2 mesi" in m.message_it and "mar 2026" in m.message_it
    assert "2 months missing" in m.message_en


# -------------------------------------------------------------------------- (g) trade
def add_trade(db, src, key, *, kg, value, currency="USD", usd=None, is_demo=False, partner="UKR"):
    start, end = date(2025, 1, 1), date(2025, 12, 31)
    return ingest.record(
        db, TradeFlowObservation, source_id=src.id, is_demo=is_demo, series_key=key, hs_code="0409",
        reporter_iso3="DEU", partner_iso3=partner, flow=TradeFlow.IMPORT.value, net_weight_kg=kg, value=value,
        currency=currency, usd_value=usd, period_start=start, period_end=end, period_label="2025", frequency="A",
        data_status="published", reliability="official",
    )[1]


def test_suspicious_trade_rows(db):
    src = make_source(db, "comtrade_like", category="trade")
    bad = add_trade(db, src, "a", kg=20000, value=900000)
    add_trade(db, src, "b", kg=20000, value=60000)
    cheap = add_trade(db, src, "c", kg=100000, value=10000)
    zero = add_trade(db, src, "d", kg=0, value=50000)
    add_trade(db, src, "e", kg=20000, value=1800000, currency="EUR")   # no FX: cannot judge, never guess
    add_trade(db, src, "f", kg=20000, value=1800000, currency="EUR", usd=1980000, partner="CHN")  # 99 USD/kg
    add_trade(db, src, "g", kg=1000, value=45000, partner="ARG")       # small lot (< 10 t): not judged
    add_trade(db, src, "h", kg=0, value=900, partner="ARG")            # tiny value without weight: not judged
    run(db)
    found = issues(db, "trade:")
    keys = set(found)
    assert f"trade:unit_value:{bad.id}" in keys and f"trade:unit_value:{cheap.id}" in keys
    assert f"trade:zero_weight:{zero.id}" in keys
    assert len(keys) == 4
    msg = found[f"trade:unit_value:{bad.id}"].message_it
    assert "45,00 USD/kg" in msg and "Germania da Ucraina" in msg
    assert found[f"trade:zero_weight:{zero.id}"].details["link"].startswith("/commercio?reporter=DEU")


# ------------------------------------------------------------------- demo rows ignored
def test_demo_rows_are_ignored(db):
    from paladex.services.demo import seed_demo

    seed_demo(db, months=24, today=TODAY)
    demo = db.scalars(select(Source).where(Source.key == "demo")).one()
    demo.expected_max_age_days = 1
    demo.latest_published_at = date(2020, 1, 1)
    src = make_source(db, "real")
    for i, v in enumerate([2.0, 2.0, 2.0, 2.0, 9.0]):
        add_price(db, demo, months_back(5 - i), v, origin="CHN", is_demo=True)
    add_trade(db, demo, "demo-bad", kg=10, value=10000, is_demo=True)
    add_trade(db, src, "zero-demo", kg=0, value=10, is_demo=True)
    add_price(db, src, (2026, 9), 9.9, origin="ARG", variety="clover", is_demo=True)
    run(db)
    for i in issues(db).values():
        assert i.source_id != demo.id
        assert "demo" not in (i.details or {}).get("source_keys", [])
    assert issues(db, "outlier:") == {} and issues(db, "trade:") == {} and issues(db, "discrepancy:") == {}
    assert issues(db, "missing:") == {} and "stale:demo" not in issues(db)


def test_foreign_issues_are_not_auto_resolved(db):
    db.add(DataQualityIssue(dedup_key="parser:usda:2026-10", issue_type="parse_warning", severity="info",
                            message_it="x", message_en="x"))
    db.flush()
    run(db)
    assert "parser:usda:2026-10" in issues(db)


def test_runner_hook_runs_quality(db, session_factory):
    src = make_source(db, "hooked", expected_max_age_days=1, latest_published_at=date.today() - timedelta(days=30))
    db.commit()
    from paladex.collectors.runner import post_collection_hooks

    post_collection_hooks()
    with session_factory() as s:
        assert s.scalar(select(DataQualityIssue).where(DataQualityIssue.dedup_key == "stale:hooked")) is not None
    assert src.id


# --------------------------------------------------------------------- quality API
def test_quality_api(api, db):
    a = make_source(db, "api_a", expected_max_age_days=5, latest_published_at=date.today() - timedelta(days=60))
    b = make_source(db, "api_b", requires_key="comtrade_api_key", last_run_status="skipped")
    add_run(db, b, RunStatus.FAILED, 1, error="boom")
    db.commit()
    r = api.post("/api/quality/run")
    assert r.status_code == 200 and r.json()["new"] >= 2
    issues_ = api.get("/api/quality/issues").json()
    keys = {i["details"].get("source_key") for i in issues_["issues"]}
    assert {"api_a", "api_b"} <= keys
    first = issues_["issues"][0]
    assert first["severity"] == "critical"   # critical first
    assert {"message_it", "message_en", "link", "source", "status"} <= set(first)
    only_a = api.get("/api/quality/issues", params={"source": "api_a"}).json()
    assert {i["details"]["source_key"] for i in only_a["issues"]} == {"api_a"}
    infos = api.get("/api/quality/issues", params={"severity": "info", "type": "missing"}).json()
    assert all(i["severity"] == "info" and i["type"] == "missing" for i in infos["issues"]) and infos["total"] >= 1
    assert api.get("/api/quality/issues", params={"status": "resolved"}).json()["total"] == 0
    assert api.get("/api/quality/issues", params={"status": "bogus"}).status_code == 422

    s = api.get("/api/quality/summary").json()
    assert s["issues"]["critical"] >= 1 and s["issues"]["open"] == issues_["total"]
    assert s["sources"]["stale"] >= 1 and s["quality_checked_at"]
    assert s["demo"] == {"visible": False, "rows": s["demo"]["rows"], "total": 0}

    keys_ = api.get("/api/quality/keys").json()["keys"]
    ct = next(k for k in keys_ if k["setting"] == "comtrade_api_key")
    assert ct["env_var"] == "PALADEX_COMTRADE_API_KEY" and ct["configured"] is False
    assert "api_b" in {s_["key"] for s_ in ct["sources"]} and ct["signup_url"].startswith("https://")
    assert a.id


# --------------------------------------------------------------------- reports API
@pytest.fixture()
def report_setup(db):
    from paladex.config import get_settings

    raw_dir = get_settings().raw_dir
    src = make_source(db, "usda_rep", name="USDA National Honey Report", publisher="USDA AMS", category="reports")
    (raw_dir / "usda_rep").mkdir(parents=True, exist_ok=True)
    (raw_dir / "usda_rep" / "fvmhoney.pdf").write_bytes(b"%PDF-1.4 test")
    (raw_dir / "usda_rep" / "page.html").write_bytes(b"<html><script>alert(1)</script></html>")
    secret = raw_dir.parent / "secret.txt"
    secret.write_text("top secret")
    docs = {}
    for name, path, ctype in (("pdf", "usda_rep/fvmhoney.pdf", "application/pdf"),
                              ("html", "usda_rep/page.html", "text/html; charset=utf-8"),
                              ("trav", "../secret.txt", "text/plain"),
                              ("abs", str(secret), "text/plain"),
                              ("gone", "usda_rep/missing.pdf", "application/pdf")):
        d = RawDocument(source_id=src.id, url=f"https://example.org/{name}", content_hash=name * 8, content_type=ctype,
                        path=path, size_bytes=10)
        db.add(d)
        db.flush()
        docs[name] = d
    reps = {}
    for i, name in enumerate(docs):
        r = Report(source_id=src.id, report_key=f"2026-{i + 1:02d}", title=f"National Honey Report {name}",
                   period_label=f"2026-{i + 1:02d}", published_at=date(2026, i + 1, 15), url="https://www.ams.usda.gov/mnreports/fvmhoney.pdf",
                   raw_document_id=docs[name].id, narrative="Argentina white honey firm; " * 40)
        db.add(r)
        db.flush()
        reps[name] = r
    plain = Report(source_id=src.id, report_key="2025-12", title="Older release", published_at=date(2025, 12, 15),
                   url="https://example.org/old", summary_it="Riassunto", summary_is_ai=True)
    demo = Report(source_id=src.id, report_key="demo-1", title="DEMO report", url="https://example.org/demo",
                  published_at=date(2026, 10, 1), is_demo=True)
    db.add_all([plain, demo])
    db.commit()
    return {"src": src, "reports": reps, "plain": plain, "demo": demo}


def test_reports_list_and_filters(api, report_setup):
    body = api.get("/api/reports").json()
    assert body["total"] == 6   # demo hidden
    first = body["reports"][0]
    assert first["published_at"] == "2026-05-15"
    assert first["source"]["key"] == "usda_rep" and first["source_url"].startswith("https://")
    assert first["raw_document"]["file_url"] == f"/api/reports/{first['id']}/file"
    assert first["narrative_excerpt"].endswith("…") and "narrative" not in first
    older = api.get("/api/reports", params={"to": "2025-12-31"}).json()
    assert [r["title"] for r in older["reports"]] == ["Older release"]
    assert older["reports"][0]["summary_is_ai"] is True and older["reports"][0]["raw_document"] is None
    assert api.get("/api/reports", params={"from": "2026-03-01", "source": "usda_rep"}).json()["total"] == 3
    assert api.get("/api/reports", params={"source": "nope"}).json()["total"] == 0
    paged = api.get("/api/reports", params={"page": 2, "page_size": 4}).json()
    assert paged["pages"] == 2 and len(paged["reports"]) == 2
    detail = api.get(f"/api/reports/{first['id']}").json()
    assert detail["narrative"].startswith("Argentina")
    assert api.get(f"/api/reports/{report_setup['demo'].id}").status_code == 404


def test_report_file_serving_is_path_safe(api, report_setup):
    reps = report_setup["reports"]
    r = api.get(f"/api/reports/{reps['pdf'].id}/file")
    assert r.status_code == 200 and r.content == b"%PDF-1.4 test"
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].startswith("inline") and "usda_rep-2026-01.pdf" in r.headers["content-disposition"]
    h = api.get(f"/api/reports/{reps['html'].id}/file")
    assert h.status_code == 200 and h.headers["content-security-policy"] == "sandbox"
    assert h.headers["x-content-type-options"] == "nosniff"
    for name in ("trav", "abs", "gone"):
        assert api.get(f"/api/reports/{reps[name].id}/file").status_code == 404, name
    assert api.get(f"/api/reports/{report_setup['plain'].id}/file").status_code == 404
    assert api.get(f"/api/reports/{report_setup['demo'].id}/file").status_code == 404
    assert api.get("/api/reports/999999/file").status_code == 404


def test_safe_raw_path(tmp_path):
    from paladex.api.reports import safe_raw_path

    base = tmp_path / "raw"
    (base / "a").mkdir(parents=True)
    (base / "a" / "f.pdf").write_bytes(b"x")
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, base / "link")
    assert safe_raw_path(base, "a/f.pdf") == (base / "a" / "f.pdf").resolve()
    for bad in ("../x", "a/../../x", "/etc/passwd", "", None, "a/\x00.pdf", ".", "link/f.pdf"):
        assert safe_raw_path(base, bad) is None, bad
    assert isinstance(safe_raw_path(base, "a/new.pdf"), Path)   # may not exist yet: caller checks is_file()


# ---------------------------------------------------------------------- search API
@pytest.fixture()
def search_setup(db):
    src = make_source(db, "usda_search", name="USDA National Honey Report", publisher="USDA AMS")
    news_src = make_source(db, "news_search", name="Google News", publisher="Google", category="news",
                           reliability=Reliability.AGGREGATOR.value)
    add_price(db, src, (2026, 9), 2.8, origin="ARG", variety="acacia")
    add_price(db, src, (2026, 8), 2.7, origin="ARG", variety="polyflora")
    add_price(db, src, (2026, 9), 6.1, origin="HUN", variety="acacia", market="ITA")

    def news(title, url, **kw):
        db.add(NewsArticle(source_id=news_src.id, url=url, canonical_url=url, title=title, title_norm=title.lower(),
                           published_at=kw.pop("published_at", datetime(2026, 10, 20)), **kw))

    news("Hungary acacia harvest down 40% after frost", "https://n.example/1", snippet="Hungarian beekeepers report...",
         countries=["HUN"], summary_it="Raccolto di acacia in calo in Ungheria.")
    news("Argentine honey exports rise", "https://n.example/2", countries=["ARG"])
    news("Mercato del miele: prezzi stabili", "https://n.example/3", snippet="Nessuna variazione per l'acacia italiana")
    db.flush()
    first = db.scalars(select(NewsArticle).where(NewsArticle.url == "https://n.example/2")).one()
    news("Argentine honey exports are rising", "https://n.example/4", duplicate_of_id=first.id)
    news("DEMO: Argentina honey news", "https://n.example/5", is_demo=True)
    db.add(Report(source_id=src.id, report_key="2026-10", title="National Honey Report October 2026",
                  url="https://www.ams.usda.gov/mnreports/fvmhoney.pdf", published_at=date(2026, 10, 15),
                  narrative="Argentina: white honey prices firm."))
    db.add(RegulationItem(source_id=src.id, jurisdiction="US", doc_type="antidumping", reference="FR 2026-12345",
                          title="Raw honey from Argentina: antidumping duty order", url="https://www.federalregister.gov/x",
                          countries=["ARG"], published_at=date(2026, 6, 1)))
    db.commit()


def _group(body, key):
    return next(g for g in body["groups"] if g["key"] == key)


def test_search_groups_and_targets(api, search_setup):
    body = api.get("/api/search", params={"q": "Argentina"}).json()
    assert [g["key"] for g in body["groups"]] == ["countries", "varieties", "prices", "news", "reports", "regulations", "sources"]
    countries = _group(body, "countries")["items"]
    assert countries[0]["iso3"] == "ARG" and countries[0]["target"] == "/paesi/ARG" and countries[0]["has_prices"]
    prices = _group(body, "prices")["items"]
    assert {p["target"] for p in prices} == {"/prezzi?origin=ARG&variety=acacia", "/prezzi?origin=ARG&variety=polyflora"}
    assert prices[0]["latest_period_end"] == "2026-09-30"
    news = _group(body, "news")
    assert [n["title"] for n in news["items"]] == ["Argentine honey exports rise"]   # duplicate + demo hidden
    assert news["items"][0]["target"] == "/notizie?q=Argentina" and news["items"][0]["url"].startswith("https://")
    reports = _group(body, "reports")["items"]
    assert reports[0]["target"] == "https://www.ams.usda.gov/mnreports/fvmhoney.pdf" and reports[0]["external"] is True
    regs = _group(body, "regulations")["items"]
    assert regs[0]["reference"] == "FR 2026-12345"
    assert body["suggestions"] is None


def test_search_cross_language_and_combined(api, search_setup):
    body = api.get("/api/search", params={"q": "acacia ungheria"}).json()
    assert [c["iso3"] for c in _group(body, "countries")["items"]] == ["HUN"]
    assert [v["key"] for v in _group(body, "varieties")["items"]] == ["acacia"]
    assert [p["target"] for p in _group(body, "prices")["items"]] == ["/prezzi?origin=HUN&variety=acacia"]
    titles = [n["title"] for n in _group(body, "news")["items"]]
    assert titles == ["Hungary acacia harvest down 40% after frost"]   # "ungheria" matched "Hungary"
    assert _group(body, "news")["items"][0]["summary_is_ai"] is True

    castagno = api.get("/api/search", params={"q": "castagno"}).json()
    assert [v["key"] for v in _group(castagno, "varieties")["items"]] == ["chestnut"]
    prefix = api.get("/api/search", params={"q": "ucr"}).json()
    assert "UKR" in [c["iso3"] for c in _group(prefix, "countries")["items"]]
    tariffs = api.get("/api/search", params={"q": "dazi argentina"}).json()   # IT word, EN document
    assert [r["reference"] for r in _group(tariffs, "regulations")["items"]] == ["FR 2026-12345"]
    usda = api.get("/api/search", params={"q": "usda"}).json()
    assert "/fonti#usda_search" in {x["target"] for x in _group(usda, "sources")["items"]}
    assert _group(usda, "reports")["total"] == 1


def test_search_empty_and_no_results(api, search_setup):
    empty = api.get("/api/search").json()
    assert empty["total"] == 0 and empty["suggestions"]["countries"] and empty["suggestions"]["varieties"]
    assert empty["suggestions"]["countries"][0]["iso3"] in {"ARG", "HUN"}   # countries with data first
    none = api.get("/api/search", params={"q": "zzqx"}).json()
    assert none["total"] == 0 and none["suggestions"] is not None
    weird = api.get("/api/search", params={"q": "%_\\"})
    assert weird.status_code == 200 and weird.json()["total"] == 0
    assert api.get("/api/search", params={"q": "2026"}).status_code == 200


def test_premium_origin_unit_values_are_not_parse_warnings(db):
    """Manuka lanes (New Zealand) are regularly 30-60+ USD/kg: not a reading error. The origin is
    the partner of an import and the reporter of an export; other origins keep 0.3-30 USD/kg."""
    src = make_source(db, "comtrade_like", category="trade")

    def flow(key, reporter, partner, flow_, usd_per_kg):
        return ingest.record(
            db, TradeFlowObservation, source_id=src.id, series_key=key, hs_code="0409", reporter_iso3=reporter,
            partner_iso3=partner, flow=flow_, net_weight_kg=20000, value=usd_per_kg * 20000, currency="USD",
            period_start=date(2025, 1, 1), period_end=date(2025, 12, 31), period_label="2025", frequency="A",
            data_status="published", reliability="official",
        )[1]

    flow("nz-cn", "NZL", "CHN", TradeFlow.EXPORT.value, 40)      # NZ manuka exports to China
    flow("jp-nz", "JPN", "NZL", TradeFlow.IMPORT.value, 40)      # Japan imports from NZ
    flow("it-nz", "ITA", "NZL", TradeFlow.IMPORT.value, 62)
    bad = flow("de-ua", "DEU", "UKR", TradeFlow.IMPORT.value, 45)   # Ukrainian bulk at 45 USD/kg: suspicious
    cn_nz = flow("cn-nz", "CHN", "NZL", TradeFlow.EXPORT.value, 40)  # export FROM China: the generic bound applies
    absurd = flow("nz-x", "NZL", "CHN", TradeFlow.EXPORT.value, 400)
    run(db)
    found = issues(db, "trade:")
    assert set(found) == {f"trade:unit_value:{bad.id}", f"trade:unit_value:{cn_nz.id}", f"trade:unit_value:{absurd.id}"}
    assert found[f"trade:unit_value:{absurd.id}"].details["range_usd_per_kg"] == [0.3, 150.0]
    assert "0,30–150 USD/kg" in found[f"trade:unit_value:{absurd.id}"].message_it
    assert found[f"trade:unit_value:{bad.id}"].details["range_usd_per_kg"] == [0.3, 30.0]
