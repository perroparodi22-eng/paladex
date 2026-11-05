"""Tests for collectors/production_official.py: Brazil IBGE SIDRA table 74 (br_ibge_honey),
Argentina SAGyP RENAPA (ar_magyp_hives), Chile Odepa (cl_odepa_hives), Canada Statistics Canada
(ca_statcan_honey), Mexico SIAP (mx_siap_honey) and Turkey TÜİK (tr_tuik_honey).

Every `real_*` fixture in tests/fixtures/production_official/ is an unmodified capture of the live
source (4-5 Nov 2026, see the README there). Variants (a revision, drift, an inconsistent extract)
are built in the tests from those captures and say what they change.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import func, select

from paladex.collectors import production_official as po
from paladex.collectors.base import CollectorError, year_bounds
from paladex.models import (
    AppSetting,
    CollectionRun,
    ProductionStat,
    RawDocument,
    Source,
    utcnow,
)
from paladex.services import ingest

FIX = Path(__file__).parent / "fixtures" / "production_official"
P = ProductionStat

SIDRA_FULL_URL = "https://apisidra.ibge.gov.br/values/t/74/n1/all/n3/all/v/106,215/p/2015-2026/c80/2687"
SIDRA_PROBE = "https://apisidra.ibge.gov.br/values/t/74/n1/all/v/106,215/p/last%201/c80/2687"
RENAPA_PROV_URL = ("https://datos.magyp.gob.ar/dataset/15fbd380-fa31-436c-9283-457c23e30ecc/resource/"
                   "fcf61106-a82c-4ce7-9997-a7f0f40345b5/download/renapa-productores-apiarios-colmenas-provincia-2026-marzo.csv")
RENAPA_DEPT_URL = ("https://datos.magyp.gob.ar/dataset/15fbd380-fa31-436c-9283-457c23e30ecc/resource/"
                   "68c49b26-6953-4656-8a32-dae497315e11/download/renapa-apiarios-colmenas-provincia-departamento-2026-marzo.csv")


def F(name: str) -> bytes:
    return (FIX / name).read_bytes()


# ---------------------------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def pin_today(monkeypatch):
    monkeypatch.setattr(po, "today", lambda: date(2026, 11, 5))


def _static(spec):
    if callable(spec):
        return spec
    if isinstance(spec, bytes):
        spec = (200, spec)
    status, body, *ctype = spec
    headers = {"content-type": ctype[0]} if ctype else {"content-type": "application/json; charset=utf-8"}
    return lambda request: httpx.Response(status, content=body, headers=headers)


@pytest.fixture()
def run(db, monkeypatch):
    """Run a collector offline. `routes` maps an exact URL (a GET), or ("POST", url), to bytes |
    (status, bytes[, content type]) | callable(request). Every request of the last run is in
    `run.sent`; any other URL fails as 'offline' (the internet check is patched to say offline)."""
    from paladex.collectors import base, runner
    from paladex.collectors.runner import run_collector

    monkeypatch.setattr(base.time, "sleep", lambda *_: None)
    monkeypatch.setattr(runner, "is_online", lambda *a, **k: False)

    def _run(key: str, routes: dict, *, force: bool = False) -> dict:
        sent: list[httpx.Request] = []
        _run.sent = sent

        def recorded(handler):
            def side_effect(request):
                sent.append(request)
                return handler(request)
            return side_effect

        with respx.mock(assert_all_called=False) as mock:
            for target, spec in routes.items():
                method, url = target if isinstance(target, tuple) else ("GET", target)
                mock.route(method=method, url=url).mock(side_effect=recorded(_static(spec)))

            def unrouted(request):
                sent.append(request)
                raise httpx.ConnectError("blocked in tests")
            mock.route().mock(side_effect=unrouted)
            with httpx.Client(follow_redirects=True) as client:
                return run_collector(key, trigger="test", force=force, client=client)

    _run.sent = []
    return _run


def _rows(s, key: str, *, current: bool | None = True, **where) -> list[ProductionStat]:
    src = s.scalars(select(Source).where(Source.key == key)).one()
    q = select(P).where(P.source_id == src.id)
    if current is not None:
        q = q.where(P.is_current.is_(current))
    for k, v in where.items():
        q = q.where(getattr(P, k) == v)
    return list(s.scalars(q.order_by(P.period_start, P.id)))


def _state(s, key: str) -> dict:
    row = s.get(AppSetting, f"collector_state:{key}")
    return dict(row.value) if row else {}


def _no_duplicate_current(s) -> None:
    dup = s.execute(select(P.source_id, P.series_key, func.count()).where(P.is_current.is_(True))
                    .group_by(P.source_id, P.series_key).having(func.count() > 1)).all()
    assert dup == [], dup


def ibge_routes(probe: bytes | None = None, full: bytes | None = None) -> dict:
    return {SIDRA_PROBE: probe if probe is not None else F("real_sidra_t74_probe_last1.json"),
            SIDRA_FULL_URL: full if full is not None else F("real_sidra_t74_honey_2015-2026.json")}


def renapa_routes(package: bytes | None = None, prov: bytes | None = None, dept: bytes | None = None,
                  prov_url: str = RENAPA_PROV_URL, dept_url: str = RENAPA_DEPT_URL) -> dict:
    csv = "text/csv"
    return {po.RENAPA_PACKAGE_URL: package if package is not None else F("real_renapa_package_show.json"),
            prov_url: (200, prov if prov is not None else F("real_renapa_provincia_2026-marzo.csv"), csv),
            dept_url: (200, dept if dept is not None else F("real_renapa_departamento_2026-marzo.csv"), csv)}


def sidra_doc(rows: list[dict]) -> bytes:
    """A SIDRA answer: the real header row of the full query followed by `rows`."""
    header = json.loads(F("real_sidra_t74_honey_2015-2026.json"))[0]
    return json.dumps([header, *rows], ensure_ascii=False).encode()


def real_sidra_rows() -> list[dict]:
    return json.loads(F("real_sidra_t74_honey_2015-2026.json"))[1:]


def edit_cells(rows: list[dict], changes: dict[tuple[str, str, str], str]) -> list[dict]:
    """Copy of `rows` with V replaced for (locality code D1C, variable D2C, year D3C)."""
    out = []
    for r in rows:
        r = dict(r)
        k = (r["D1C"], r["D2C"], r["D3C"])
        if k in changes:
            r["V"] = changes[k]
        out.append(r)
    return out


# ---------------------------------------------------------------------------------------------
# Registration and metadata
# ---------------------------------------------------------------------------------------------


def test_registered_with_official_metadata():
    from paladex.collectors.registry import IMPORT_ERRORS, all_collectors, get_collector

    all_collectors(refresh=True)
    assert "paladex.collectors.production_official" not in IMPORT_ERRORS
    for key, iso3 in (("br_ibge_honey", "BRA"), ("ar_magyp_hives", "ARG"), ("cl_odepa_hives", "CHL")):
        c = get_collector(key)
        assert c is not None, key
        assert c.reliability == "official" and c.category == "production" and c.country_iso3 == iso3
        assert c.requires_key is None and c.default_enabled is True
        assert 0 < len(c.expected_update) < 120 and 0 < len(c.expected_update_en) < 120
        assert c.schedule["trigger"] == "cron" and "day" in c.schedule      # monthly, never a tight interval
        assert c.expected_max_age_days and c.terms_note
    assert "CC BY 4.0" in get_collector("ar_magyp_hives").terms_note
    assert "IBGE" in get_collector("br_ibge_honey").terms_note


# ---------------------------------------------------------------------------------------------
# Brazil, IBGE SIDRA: pure functions on the real answers
# ---------------------------------------------------------------------------------------------


def test_sidra_urls_are_the_ones_checked_live():
    assert po.sidra_url(2015, 2026) == SIDRA_FULL_URL
    assert po.SIDRA_PROBE_URL == SIDRA_PROBE


def test_real_release_check_answer():
    rel = po.parse_sidra_probe(F("real_sidra_t74_probe_last1.json"))
    assert rel.latest_year == 2025
    assert rel.signature == "2025|106=71329020|215=1216769"


def test_real_table_74_honey_answer():
    parsed = po.parse_sidra(F("real_sidra_t74_honey_2015-2026.json"), first_year=2015, last_year=2026)
    assert parsed.problems == []
    assert parsed.years() == list(range(2015, 2026))
    assert len(parsed.rows) == 28 * 2 * 11                           # Brazil + 27 states, 2 variables, 11 years
    nat = {(r.variable, r.year): r for r in parsed.rows if r.level == "1"}
    assert (nat[("106", 2025)].raw, nat[("106", 2025)].unit_name, nat[("106", 2025)].unit_code) == (
        "71329020", "Quilogramas", "1007")
    assert (nat[("215", 2025)].raw, nat[("215", 2025)].unit_name, nat[("215", 2025)].unit_code) == (
        "1216769", "Mil Reais", "40")
    # IBGE's current 2024 figure: revised from 67,313,986 kg (first release, the figure FAOSTAT carries)
    assert nat[("106", 2024)].value == 68_235_733
    assert nat[("106", 2015)].value == 37_859_193
    states = {r.loc_code for r in parsed.rows if r.level == "3"}
    assert states == set(po.BR_STATES)
    pi = next(r for r in parsed.rows if r.loc_code == "22" and r.variable == "106" and r.year == 2025)
    assert pi.loc_name == "Piauí" and pi.level_name == "Unidade da Federação"
    # the states add up exactly to the national kg, and to the value within rounding
    assert po.check_sidra_totals(parsed) == []


def test_real_error_answers_fail_loudly():
    # a wrong category is answered with HTTP 200, an empty category name and '...': never stored as honey
    with pytest.raises(CollectorError, match="not 2687"):
        po.parse_sidra(F("real_sidra_t74_wrong_category_99999.json"))
    assert b"inexistente" in F("real_sidra_t74_wrong_variable_9999_http400.txt")


def test_parse_sidra_schema_drift_fails_loudly():
    rows = real_sidra_rows()[:4]
    header = json.loads(F("real_sidra_t74_honey_2015-2026.json"))[0]
    with pytest.raises(CollectorError, match="not valid JSON"):
        po.parse_sidra(b"<!DOCTYPE html><title>Just a moment...</title>")
    with pytest.raises(CollectorError, match="header row"):
        po.parse_sidra(json.dumps({"V": "1"}).encode())
    with pytest.raises(CollectorError, match="dimension labels"):
        po.parse_sidra(json.dumps([{**header, "D3N": "Mês"}, *rows]).encode())
    with pytest.raises(CollectorError, match="without"):
        po.parse_sidra(json.dumps([{k: v for k, v in header.items() if k != "MN"}, *rows]).encode())
    with pytest.raises(CollectorError, match="unit drift"):
        po.parse_sidra(sidra_doc([{**rows[0], "MN": "Toneladas"}]))
    with pytest.raises(CollectorError, match="variable"):
        po.parse_sidra(sidra_doc([{**rows[0], "D2N": "Produção de mel"}]))
    with pytest.raises(CollectorError, match="territorial level"):
        po.parse_sidra(sidra_doc([{**rows[0], "NC": "6", "NN": "Município"}]))
    with pytest.raises(CollectorError, match="not a year"):
        po.parse_sidra(sidra_doc([{**rows[0], "D3C": "2025-1"}]))
    with pytest.raises(CollectorError, match="no national"):
        po.parse_sidra_probe(sidra_doc([r for r in real_sidra_rows() if r["NC"] == "3"][:2]))


def test_parse_sidra_special_cells_and_years():
    base = real_sidra_rows()[0]                                      # Brazil, kg, 2015
    rows = [{**base, "V": "-"}, {**base, "V": "...", "MN": "", "MC": ""}, {**base, "V": "X"},
            {**base, "V": "n/d"}, {**base, "D3C": "2014", "D3N": "2014"}]
    parsed = po.parse_sidra(sidra_doc(rows), first_year=2015, last_year=2026)
    assert [(r.raw, r.value, r.symbol) for r in parsed.rows] == [("-", 0.0, "-"), ("...", None, "..."), ("X", None, "X")]
    assert any("unreadable value 'n/d'" in p for p in parsed.problems)
    assert any("outside the requested years" in p for p in parsed.problems)


def test_check_sidra_totals_reports_but_never_fixes():
    rows = real_sidra_rows()
    changed = edit_cells(rows, {("22", "106", "2025"): "1"})                       # Piauí 2025 kg
    msgs = po.check_sidra_totals(po.parse_sidra(sidra_doc(changed)))
    assert len(msgs) == 1 and "2025" in msgs[0] and "both kept as published" in msgs[0]
    no_sp = [r for r in rows if not (r["D1C"] == "35" and r["D3C"] == "2020")]
    msgs = po.check_sidra_totals(po.parse_sidra(sidra_doc(no_sp)))
    assert any("2020" in m and "SP" in m for m in msgs)
    # value: a difference within rounding (1 thousand reais per state) is not reported
    rounding = edit_cells(rows, {("1", "215", "2025"): str(1216769 + 20)})
    assert po.check_sidra_totals(po.parse_sidra(sidra_doc(rounding))) == []


# ---------------------------------------------------------------------------------------------
# Brazil, IBGE SIDRA: end to end
# ---------------------------------------------------------------------------------------------


def test_ibge_end_to_end_on_the_real_answers(run, session_factory):
    res = run("br_ibge_honey", ibge_routes())
    assert res["status"] == "success", res
    assert [str(r.url) for r in run.sent] == [SIDRA_PROBE, SIDRA_FULL_URL]          # two requests
    assert res["new"] == 616

    with session_factory() as s:
        _no_duplicate_current(s)
        rows = _rows(s, "br_ibge_honey")
        assert len(rows) == 616
        assert all(r.country_iso3 == "BRA" and r.frequency == "A" for r in rows)
        assert all(r.reliability == "official" and r.data_status == "published" for r in rows)
        assert all(r.source_url == SIDRA_FULL_URL and r.raw_document_id for r in rows)
        assert all(r.published_at is None for r in rows)            # SIDRA gives no release date: never guessed
        by_metric = {}
        for r in rows:
            by_metric.setdefault(r.metric, []).append(r)
        assert {m: len(v) for m, v in by_metric.items()} == {
            "production": 11, "production_value": 11, "production_by_region": 297, "production_value_by_region": 297}
        # national production in tonnes, the kg as published kept with the row
        nat = {r.period_label: r for r in by_metric["production"]}
        assert sorted(nat) == [str(y) for y in range(2015, 2026)]
        n25 = nat["2025"]
        assert (n25.value, n25.unit) == (71329.02, "t")
        assert (n25.period_start, n25.period_end) == year_bounds(2025)
        assert n25.extra["value_as_published"] == "71329020" and n25.extra["unit_as_published"] == "Quilogramas"
        assert n25.extra["conversion"] == "kg / 1000 = t (exact)" and "region" not in n25.extra
        assert n25.extra["category"] == "Mel de abelha" and n25.extra["sidra_table"] == "74"
        assert "71329020 kg as published" in n25.notes
        assert nat["2024"].value == 68235.733
        val = {r.period_label: r for r in by_metric["production_value"]}["2025"]
        assert (val.value, val.unit, val.extra["unit_as_published"]) == (1216769.0, "1000 BRL", "Mil Reais")
        # states: their own metric, the state in extra.region, never under metric "production"
        pi = next(r for r in by_metric["production_by_region"] if r.extra["region_abbr"] == "PI" and r.period_label == "2025")
        assert pi.extra["region"] == "Piauí" and pi.extra["region_code"] == "22" and pi.extra["macro_region"] == "Nordeste"
        assert pi.series_key == "ibge_ppm|t74|BR-PI|production_by_region|2025" and pi.unit == "t"
        assert all("region" in r.extra for r in by_metric["production_by_region"] + by_metric["production_value_by_region"])
        assert all("region" not in r.extra for r in by_metric["production"] + by_metric["production_value"])
        for year in range(2015, 2026):              # never summed into the national row, but consistent with it
            states = [r.value for r in by_metric["production_by_region"] if r.period_label == str(year)]
            assert len(states) == 27 and abs(sum(states) - nat[str(year)].value) < 1e-6
        raw = s.get(RawDocument, n25.raw_document_id)
        assert raw.url == SIDRA_FULL_URL and raw.title.startswith("IBGE SIDRA tabela 74")
        st = _state(s, "br_ibge_honey")
        assert st["release"] == "2025|106=71329020|215=1216769" and st["latest_year"] == 2025
        src = s.scalars(select(Source).where(Source.key == "br_ibge_honey")).one()
        assert src.latest_period_label == "2025"


def test_ibge_second_run_is_one_small_request(run, session_factory):
    assert run("br_ibge_honey", ibge_routes())["status"] == "success"
    res = run("br_ibge_honey", ibge_routes())
    assert res["status"] == "no_change" and res["new"] == 0
    assert [str(r.url) for r in run.sent] == [SIDRA_PROBE]
    # forced: the full table is read again, nothing changes
    res = run("br_ibge_honey", ibge_routes(), force=True)
    assert res["status"] == "no_change" and res["revised"] == 0
    assert [str(r.url) for r in run.sent] == [SIDRA_PROBE, SIDRA_FULL_URL]
    with session_factory() as s:
        assert len(_rows(s, "br_ibge_honey", current=None)) == 616


def test_ibge_full_table_is_reread_after_the_refresh_interval(run, session_factory):
    assert run("br_ibge_honey", ibge_routes())["status"] == "success"
    with session_factory() as s:
        row = s.get(AppSetting, "collector_state:br_ibge_honey")
        old = (utcnow() - timedelta(days=po.IBGE_FULL_REFRESH_DAYS + 1)).isoformat(timespec="seconds")
        row.value = {**row.value, "pulled_at": old}
        s.commit()
    res = run("br_ibge_honey", ibge_routes())
    assert res["status"] == "no_change"
    assert [str(r.url) for r in run.sent] == [SIDRA_PROBE, SIDRA_FULL_URL]       # same bytes: nothing re-parsed


def test_ibge_revision_of_a_published_year_is_kept_as_history(run, session_factory):
    assert run("br_ibge_honey", ibge_routes())["status"] == "success"
    # IBGE corrects 2025: Brazil and Piauí +1,000 kg (the states still add up to the national figure)
    piaui = next(x for x in real_sidra_rows() if (x["D1C"], x["D2C"], x["D3C"]) == ("22", "106", "2025"))
    revised = edit_cells(real_sidra_rows(), {("1", "106", "2025"): "71330020",
                                             ("22", "106", "2025"): str(int(piaui["V"]) + 1000)})
    probe = json.loads(F("real_sidra_t74_probe_last1.json"))
    for r in probe[1:]:
        if r["D2C"] == "106":
            r["V"] = "71330020"
    res = run("br_ibge_honey", ibge_routes(probe=json.dumps(probe).encode(), full=sidra_doc(revised)))
    assert res["status"] == "success", res
    assert (res["new"], res["revised"]) == (0, 2)
    with session_factory() as s:
        _no_duplicate_current(s)
        hist = _rows(s, "br_ibge_honey", current=None, metric="production", period_label="2025")
        assert [(h.value, h.revision, h.is_current) for h in hist] == [(71329.02, 1, False), (71330.02, 2, True)]
        assert hist[1].supersedes_id == hist[0].id
        assert _state(s, "br_ibge_honey")["release"] == "2025|106=71330020|215=1216769"


def test_ibge_rejections_and_drift_store_nothing(run, session_factory):
    res = run("br_ibge_honey", {SIDRA_PROBE: (400, F("real_sidra_t74_wrong_variable_9999_http400.txt"), "text/plain")})
    assert res["status"] == "failed" and "rejected the release check" in res["error"]
    wrong = F("real_sidra_t74_wrong_category_99999.json")
    res = run("br_ibge_honey", ibge_routes(full=wrong))
    assert res["status"] == "failed" and "not 2687" in res["error"]
    res = run("br_ibge_honey", ibge_routes(full=(403, b"<html>Just a moment...</html>", "text/html")))
    assert res["status"] == "failed" and "HTTP 403" in res["error"]
    nat_only_states = [r for r in real_sidra_rows() if r["NC"] == "3"]
    res = run("br_ibge_honey", ibge_routes(full=sidra_doc(nat_only_states)))
    assert res["status"] == "failed" and "no national honey figure" in res["error"]
    with session_factory() as s:
        assert _rows(s, "br_ibge_honey", current=None) == []
        assert s.scalar(select(func.count(RawDocument.id))) == 0


def test_ibge_unreachable_is_offline_not_a_failure(run, session_factory):
    res = run("br_ibge_honey", {})
    assert res["status"] == "offline"
    with session_factory() as s:
        run_row = s.scalars(select(CollectionRun).order_by(CollectionRun.id.desc())).first()
        assert run_row.status == "offline"


# ---------------------------------------------------------------------------------------------
# Brazil: FAOSTAT and IBGE side by side in the shared production views (never summed)
# ---------------------------------------------------------------------------------------------


def _faostat_brazil(db) -> None:
    fao = db.scalars(select(Source).where(Source.key == "faostat")).one()
    for year, value in ((2023, 64164.18), (2024, 67313.99)):        # the live FAOSTAT figures (QCL, flag A)
        start, end = year_bounds(year)
        ingest.record(db, ProductionStat, source_id=fao.id, series_key=f"faostat|QCL|BRA|production|{year}",
                      country_iso3="BRA", metric="production", value=value, unit="t", period_start=start,
                      period_end=end, period_label=str(year), frequency="A", flag_raw="A",
                      published_at=date(2025, 12, 31), source_url="https://bulks-faostat.fao.org/production/",
                      data_status="published", reliability="official")
    db.commit()


def test_faostat_and_ibge_are_side_by_side_in_the_production_views(run, api, db):
    assert run("br_ibge_honey", ibge_routes())["status"] == "success"
    _faostat_brazil(db)
    table = api.get("/api/harvest/production", params={"scope": "all"}).json()
    bra = next(c for c in table["countries"] if c["iso3"] == "BRA")
    series = {s["source"]["key"]: s for s in bra["series"]}
    assert set(series) == {"faostat", "br_ibge_honey"}               # two series, one per source
    assert series["br_ibge_honey"]["latest"]["year"] == 2025 and series["br_ibge_honey"]["latest"]["value"] == 71329.02
    assert series["br_ibge_honey"]["previous"]["value"] == 68235.733
    assert series["faostat"]["latest"]["year"] == 2024 and series["faostat"]["latest"]["value"] == 67313.99
    # the national IBGE series is not polluted by the states
    assert series["br_ibge_honey"]["years"] == 11

    country = api.get("/api/harvest/production/BRA").json()
    prod = next(m for m in country["metrics"] if m["metric"] == "production")
    assert {s["source"]["key"] for s in prod["series"]} == {"faostat", "br_ibge_honey"}
    ibge = next(s for s in prod["series"] if s["source"]["key"] == "br_ibge_honey")
    assert len(ibge["points"]) == 11 and ibge["unit"] == "t"
    # the 27 states are stored (production_by_region) but never shown as one national series: grouped by
    # metric they made one line jumping from state to state (review 2026-11-05)
    assert {m["metric"] for m in country["metrics"]} == {"production", "production_value"}

    profile = api.get("/api/countries/BRA").json()
    prof_prod = next(m for m in profile["production"]["metrics"] if m["metric"] == "production")
    assert {s["source"]["key"] for s in prof_prod["series"]} == {"faostat", "br_ibge_honey"}
    assert not any(m["metric"].endswith("_by_region") for m in profile["production"]["metrics"])
    assert bra["series"][0]["source"]["key"] == "br_ibge_honey"       # the newest official figure heads the row


# ---------------------------------------------------------------------------------------------
# Argentina, RENAPA: pure functions on the real files
# ---------------------------------------------------------------------------------------------


def test_real_renapa_package():
    pkg = po.parse_renapa_package(F("real_renapa_package_show.json"))
    assert pkg.province.id == "fcf61106-a82c-4ce7-9997-a7f0f40345b5" and pkg.province.url == RENAPA_PROV_URL
    assert pkg.department.id == "68c49b26-6953-4656-8a32-dae497315e11" and pkg.department.url == RENAPA_DEPT_URL
    assert pkg.province.last_modified.date() == date(2026, 3, 17)
    assert pkg.license == "Creative Commons Attribution 4.0"


def test_real_renapa_files():
    provinces = po.parse_renapa_provinces(F("real_renapa_provincia_2026-marzo.csv"))
    assert len(provinces) == 23
    assert (sum(p.producers for p in provinces), sum(p.apiaries for p in provinces), sum(p.hives for p in provinces)) == (
        23_560, 61_503, 4_411_965)
    ba = provinces[0]
    assert (ba.code, ba.name, ba.producers, ba.apiaries, ba.hives) == ("06", "Buenos Aires", 7921, 23955, 1_709_742)
    assert any(p.name == "Córdoba" for p in provinces) and any(p.name == "Entre Ríos" for p in provinces)  # Latin-1 file
    depts = po.parse_renapa_departments(F("real_renapa_departamento_2026-marzo.csv"))
    assert depts == po.RenapaDepartments(updated=date(2026, 3, 17), rows=486, apiaries=61_503, hives=4_411_965)


def test_renapa_drift_fails_loudly():
    pkg = json.loads(F("real_renapa_package_show.json"))
    no_dept = json.loads(json.dumps(pkg))
    no_dept["result"]["resources"] = [r for r in no_dept["result"]["resources"] if "departamento" not in r["name"]]
    with pytest.raises(CollectorError, match="no longer"):
        po.parse_renapa_package(json.dumps(no_dept).encode())
    # a resource id changes: found again by its name
    new_id = json.loads(json.dumps(pkg))
    new_id["result"]["resources"][1]["id"] = "00000000-new-id"
    assert po.parse_renapa_package(json.dumps(new_id).encode()).province.url == RENAPA_PROV_URL
    with pytest.raises(CollectorError, match="did not return the package"):
        po.parse_renapa_package(json.dumps({"success": False, "error": {"message": "Not found"}}).encode())
    with pytest.raises(CollectorError, match="not valid JSON"):
        po.parse_renapa_package(b"<html>maintenance</html>")
    prov = F("real_renapa_provincia_2026-marzo.csv")
    with pytest.raises(CollectorError, match="no column"):
        po.parse_renapa_provinces(prov.replace(b"colmenas", b"colonias", 1))
    with pytest.raises(CollectorError, match="not a whole number"):
        po.parse_renapa_provinces(prov.replace(b"1709742", b"1.709.742"))
    with pytest.raises(CollectorError, match="only 1 provinces"):
        po.parse_renapa_provinces(b"provincia_id,provincia,productores,apiarios,colmenas\n06,Buenos Aires,1,1,1\n")
    dept = F("real_renapa_departamento_2026-marzo.csv")
    with pytest.raises(CollectorError, match="2 update dates"):
        po.parse_renapa_departments(dept.replace(b"2026-03-17", b"2026-03-18", 1))
    with pytest.raises(CollectorError, match="no column"):
        po.parse_renapa_departments(dept.replace(b"fecha_actualizacion", b"fecha", 1))


# ---------------------------------------------------------------------------------------------
# Argentina, RENAPA: end to end
# ---------------------------------------------------------------------------------------------


def test_renapa_end_to_end_on_the_real_files(run, session_factory):
    res = run("ar_magyp_hives", renapa_routes())
    assert res["status"] == "success", res
    assert [str(r.url) for r in run.sent] == [po.RENAPA_PACKAGE_URL, RENAPA_PROV_URL, RENAPA_DEPT_URL]
    with session_factory() as s:
        rows = _rows(s, "ar_magyp_hives")
        assert len(rows) == 1
        r = rows[0]
        assert (r.country_iso3, r.metric, r.value, r.unit) == ("ARG", "colonies", 4_411_965.0, "number")
        assert (r.period_start, r.period_end, r.period_label, r.frequency) == (
            date(2026, 3, 17), date(2026, 3, 17), "2026-03-17", "irregular")
        assert (r.published_at, r.data_status, r.reliability) == (date(2026, 3, 17), "published", "official")
        assert r.source_url == RENAPA_PROV_URL and r.raw_document_id
        assert r.series_key == "renapa|ARG|colonies|2026-03-17"
        x = r.extra
        assert (x["producers"], x["apiaries"], x["hives"]) == (23_560, 61_503, 4_411_965)
        assert len(x["provinces"]) == 23 and x["provinces"][0]["name"] == "Buenos Aires"
        assert x["department_file"]["hives"] == 4_411_965 and x["department_file"]["url"] == RENAPA_DEPT_URL
        assert "sum of the 23 rows" in x["total_method"] and "Registered hives" in r.notes
        assert s.scalar(select(func.count(RawDocument.id))) == 2        # the two CSV files are archived


def test_renapa_unchanged_extract_is_one_metadata_request(run, session_factory):
    assert run("ar_magyp_hives", renapa_routes())["status"] == "success"
    res = run("ar_magyp_hives", renapa_routes())
    assert res["status"] == "no_change"
    assert [str(r.url) for r in run.sent] == [po.RENAPA_PACKAGE_URL]


def test_renapa_new_extract_adds_a_snapshot_and_keeps_the_old_one(run, session_factory):
    assert run("ar_magyp_hives", renapa_routes())["status"] == "success"
    # A new upload (as MAGyP does it: same resource ids, new file names and dates). Buenos Aires
    # gains 1,000 hives in one department and in the province row; the snapshot date moves.
    pkg = json.loads(F("real_renapa_package_show.json"))
    new_prov = RENAPA_PROV_URL.replace("2026-marzo", "2026-septiembre")
    new_dept = RENAPA_DEPT_URL.replace("2026-marzo", "2026-septiembre")
    for r in pkg["result"]["resources"]:
        if r["id"].startswith("fcf61106"):
            r["url"], r["last_modified"] = new_prov, "2026-09-15T10:00:00.000000"
        elif r["id"].startswith("68c49b26"):
            r["url"], r["last_modified"] = new_dept, "2026-09-15T09:59:00.000000"
    prov = F("real_renapa_provincia_2026-marzo.csv").replace(b"06,Buenos Aires,7921,23955,1709742",
                                                              b"06,Buenos Aires,7921,23955,1710742")
    dept = (F("real_renapa_departamento_2026-marzo.csv").replace(b"2026-03-17", b"2026-09-15")
            .replace(b"06854,25 de Mayo,271,21770", b"06854,25 de Mayo,271,22770"))
    res = run("ar_magyp_hives", renapa_routes(package=json.dumps(pkg).encode(), prov=prov, dept=dept,
                                              prov_url=new_prov, dept_url=new_dept))
    assert res["status"] == "success" and res["new"] == 1, res
    with session_factory() as s:
        rows = _rows(s, "ar_magyp_hives")
        assert [(r.period_label, r.value, r.published_at) for r in rows] == [
            ("2026-03-17", 4_411_965.0, date(2026, 3, 17)), ("2026-09-15", 4_412_965.0, date(2026, 9, 15))]
        assert rows[1].source_url == new_prov


def test_renapa_files_that_disagree_store_nothing(run, session_factory):
    dept = F("real_renapa_departamento_2026-marzo.csv").replace(b"06854,25 de Mayo,271,21770",
                                                                b"06854,25 de Mayo,271,21771")
    res = run("ar_magyp_hives", renapa_routes(dept=dept))
    assert res["status"] == "failed" and "disagree" in res["error"]
    with session_factory() as s:
        assert _rows(s, "ar_magyp_hives", current=None) == []
        assert _state(s, "ar_magyp_hives") == {}


# ---------------------------------------------------------------------------------------------
# Chile, Odepa "Cifras apícolas nacionales" (SAG SIPEC register): pure functions on real captures
# ---------------------------------------------------------------------------------------------

ODEPA_ARTICLE = "https://www.odepa.gob.cl/publicaciones/articulos/cifras-apicolas-nacionales-sipec-2025"
ODEPA_PDF = "https://bibliotecadigital.odepa.gob.cl/bitstreams/1f285eb9-7faa-41a5-8c41-b9e2cb92e895/download"
# Stand-in bytes for the 1.5 MB article PDF, which is not kept in the repository: its text layer
# (pages 9-10, the two region tables) is the real fixture `real_odepa_sipec_2025_pdf_text_pages_9-10.txt`.
PDF_STAND_IN = b"%PDF-1.6 stand-in for the real Odepa article PDF (see README)"


def odepa_pages() -> list[str]:
    return F("real_odepa_sipec_2025_pdf_text_pages_9-10.txt").decode("utf-8").split("\f")


def odepa_lines(pages: list[str] | None = None) -> list[str]:
    return [line.strip() for text in (pages or odepa_pages()) for line in text.splitlines() if line.strip()]


@pytest.fixture()
def odepa_pdf(monkeypatch):
    """The collector reads the stand-in PDF as the real PDF's text layer (pages 9-10)."""
    pages = {"value": odepa_pages()}

    def fake(content: bytes) -> list[str]:
        assert content == PDF_STAND_IN
        return pages["value"]
    monkeypatch.setattr(po, "pdf_pages_text", fake)
    return pages


def odepa_routes(page: bytes | None = None, article: bytes | None = None) -> dict:
    html = "text/html; charset=UTF-8"
    return {po.ODEPA_APICULTURA_URL: (200, page if page is not None else F("real_odepa_rubros_apicultura.html"), html),
            ODEPA_ARTICLE: (200, article if article is not None else
                            F("real_odepa_articulo_cifras_apicolas_nacionales_sipec_2025.html"), html),
            ODEPA_PDF: (200, PDF_STAND_IN, "application/pdf")}


def test_real_odepa_pages():
    page = F("real_odepa_rubros_apicultura.html").decode("utf-8")
    assert po.find_odepa_articles(page) == [ODEPA_ARTICLE]
    assert po.pick_odepa_article([ODEPA_ARTICLE, ODEPA_ARTICLE.replace("2025", "2026")]).endswith("-2026")
    assert po.pick_odepa_article(["https://www.odepa.gob.cl/publicaciones/articulos/cifras-apicolas-nacionales-a",
                                  "https://www.odepa.gob.cl/publicaciones/articulos/cifras-apicolas-nacionales-b"]).endswith("-a")
    # another "cifras apícolas" note (e.g. on exports) is not taken for the register series
    assert po.find_odepa_articles('<a href="https://www.odepa.gob.cl/publicaciones/articulos/cifras-apicolas-exportacion-2026">') == []
    art = po.parse_odepa_article(F("real_odepa_articulo_cifras_apicolas_nacionales_sipec_2025.html").decode("utf-8"),
                                 ODEPA_ARTICLE)
    assert art.pdf_url == ODEPA_PDF and art.published == date(2026, 10, 19)
    assert art.title.startswith("Cifras apícolas nacionales desde los registros administrativos")
    # the Spanish date in the text is the fallback when the machine-readable dates are missing
    bare = re.sub(r'<meta property="article:published_time"[^>]*>|datetime="[^"]*"', "",
                  F("real_odepa_articulo_cifras_apicolas_nacionales_sipec_2025.html").decode("utf-8"))
    assert po.parse_odepa_article(bare, ODEPA_ARTICLE).published == date(2026, 10, 19)
    with pytest.raises(CollectorError, match="no link to the full article"):
        po.parse_odepa_article("<html><h1>Cifras</h1></html>", ODEPA_ARTICLE)


def test_real_odepa_tables():
    hives = po.parse_odepa_table(odepa_lines(), po.ODEPA_HIVES_TABLE, "hives")
    assert hives.title == "Tabla 2. Número de colmenas por región, período 2019-2025"
    assert hives.years == list(range(2019, 2026))
    assert hives.total == [909_577, 855_999, 855_967, 915_595, 1_009_629, 1_034_059, 1_084_923]
    assert len(hives.regions) == 16 and hives.incomplete == []
    assert hives.regions["Maule"][-1] == 265_971 and hives.regions["O'Higgins"][-1] == 230_873
    # as published, the regions add up to the total except in 2020 (+3) and 2025 (+6)
    assert [s - t for s, t in zip(hives.region_sums(), hives.total)] == [0, 3, 0, 0, 0, 0, 6]
    keepers = po.parse_odepa_table(odepa_lines(), po.ODEPA_BEEKEEPERS_TABLE, "beekeepers")
    assert keepers.total == [6_207, 5_857, 5_398, 5_549, 6_241, 6_433, 6_624]
    # Magallanes has blank cells: 5 numbers for 7 years cannot be placed from the text, never guessed
    assert keepers.incomplete == ["Magallanes - Antártica Chilena"] and keepers.region_sums() is None


def test_odepa_table_drift_fails_loudly():
    lines = odepa_lines()
    with pytest.raises(CollectorError, match="no table"):
        po.parse_odepa_table([line for line in lines if not line.startswith("Tabla 2.")], po.ODEPA_HIVES_TABLE, "hives")
    t2 = next(i for i, line in enumerate(lines) if line.startswith("Tabla 2."))
    no_header = lines[:t2 + 1] + lines[t2 + 2:]                    # the "Región 2019 ... 2025" line of table 2 removed
    with pytest.raises(CollectorError, match="header"):
        po.parse_odepa_table(no_header, po.ODEPA_HIVES_TABLE, "hives")
    short_total = [line.replace("1.034.059 1.084.923", "1.034.059") for line in lines]
    with pytest.raises(CollectorError, match="Total nacional' row has 6 values"):
        po.parse_odepa_table(short_total, po.ODEPA_HIVES_TABLE, "hives")
    gaps = [line.replace("Región 2019 2020 2021", "Región 2019 2021 2022") for line in lines]
    with pytest.raises(CollectorError, match="not consecutive"):
        po.parse_odepa_table(gaps, po.ODEPA_HIVES_TABLE, "hives")
    no_total = [line for line in lines if not line.startswith("Total nacional 909.577")]
    with pytest.raises(CollectorError, match="unexpected line"):
        po.parse_odepa_table(no_total, po.ODEPA_HIVES_TABLE, "hives")
    with pytest.raises(CollectorError, match="cannot be read"):
        po.pdf_pages_text(b"not a pdf at all")


def test_pdf_pages_text_reads_a_text_layer():
    fpdf = pytest.importorskip("fpdf")
    doc = fpdf.FPDF()
    doc.add_page()
    doc.set_font("helvetica", size=11)
    doc.cell(text="Total nacional 909.577 855.999")
    assert "Total nacional 909.577 855.999" in po.pdf_pages_text(bytes(doc.output()))[0]


# ---------------------------------------------------------------------------------------------
# Chile: end to end
# ---------------------------------------------------------------------------------------------


def test_odepa_end_to_end_on_the_real_pages(run, odepa_pdf, session_factory):
    res = run("cl_odepa_hives", odepa_routes())
    assert res["status"] == "partial", res                        # the source's own +3 / +6 is reported once
    assert len(res["warnings"]) == 1 and "2020: regions 856,002 vs total 855,999" in res["warnings"][0]
    assert [str(r.url) for r in run.sent] == [po.ODEPA_APICULTURA_URL, ODEPA_ARTICLE, ODEPA_PDF]
    with session_factory() as s:
        _no_duplicate_current(s)
        rows = _rows(s, "cl_odepa_hives")
        assert [(r.period_label, r.value) for r in rows] == [
            ("2019", 909_577.0), ("2020", 855_999.0), ("2021", 855_967.0), ("2022", 915_595.0),
            ("2023", 1_009_629.0), ("2024", 1_034_059.0), ("2025", 1_084_923.0)]
        r = rows[-1]
        assert (r.country_iso3, r.metric, r.unit, r.frequency) == ("CHL", "colonies", "number", "A")
        assert (r.period_start, r.period_end) == (date(2025, 10, 1), date(2025, 10, 31))
        assert (r.published_at, r.data_status, r.reliability) == (date(2026, 10, 19), "published", "official")
        assert r.source_url == ODEPA_PDF and r.raw_document_id
        assert r.extra["value_as_published"] == "1.084.923" and r.extra["row"] == "Total nacional"
        assert r.extra["regions"]["Maule"] == 265_971 and r.extra["regions_sum"] == 1_084_929
        assert r.extra["beekeepers_total"] == 6_624 and "not necessarily" in r.extra["caveat"]
        assert r.extra["article_url"] == ODEPA_ARTICLE and r.extra["table"].startswith("Tabla 2.")
        raw = s.get(RawDocument, r.raw_document_id)
        assert raw.url == ODEPA_PDF and raw.published_at == date(2026, 10, 19)


def test_odepa_second_run_reads_only_the_listing(run, odepa_pdf, session_factory):
    assert run("cl_odepa_hives", odepa_routes())["status"] == "partial"
    res = run("cl_odepa_hives", odepa_routes())
    assert res["status"] == "no_change" and res["warnings"] == []
    assert [str(r.url) for r in run.sent] == [po.ODEPA_APICULTURA_URL]
    # forced: everything read again, the known inconsistency is not reported a second time
    res = run("cl_odepa_hives", odepa_routes(), force=True)
    assert res["status"] == "no_change" and res["warnings"] == []


def test_odepa_listing_without_the_article(run, odepa_pdf, session_factory):
    page = F("real_odepa_rubros_apicultura.html").replace(b"cifras-apicolas-nacionales-sipec-2025", b"otra-nota")
    res = run("cl_odepa_hives", odepa_routes(page=page))
    assert res["status"] == "failed" and "no 'Cifras apícolas nacionales' article" in res["error"]
    assert run("cl_odepa_hives", odepa_routes())["status"] == "partial"
    res = run("cl_odepa_hives", odepa_routes(page=page))          # data already stored: kept, warned once
    assert res["status"] == "partial" and "kept" in res["warnings"][0]
    with session_factory() as s:
        assert len(_rows(s, "cl_odepa_hives")) == 7


def test_odepa_unreadable_table_stores_nothing(run, odepa_pdf, session_factory):
    odepa_pdf["value"] = [p.replace("Total nacional 909.577", "Total nacional") for p in odepa_pages()]
    res = run("cl_odepa_hives", odepa_routes())
    assert res["status"] == "failed" and "Total nacional' row has 6 values" in res["error"]
    with session_factory() as s:
        assert _rows(s, "cl_odepa_hives", current=None) == []


# ---------------------------------------------------------------------------------------------
# Canada, Mexico, Turkey: registration
# ---------------------------------------------------------------------------------------------


def test_new_collectors_registered_with_official_metadata():
    from paladex.collectors.registry import all_collectors, get_collector

    all_collectors(refresh=True)
    for key, iso3 in (("ca_statcan_honey", "CAN"), ("mx_siap_honey", "MEX"), ("tr_tuik_honey", "TUR")):
        c = get_collector(key)
        assert c is not None, key
        assert c.reliability == "official" and c.category == "production" and c.country_iso3 == iso3
        assert c.requires_key is None and c.default_enabled is True
        assert 0 < len(c.expected_update) < 120 and 0 < len(c.expected_update_en) < 120
        assert c.name_en and len(c.name) <= 200 and len(c.name_en) <= 120
        assert c.schedule["trigger"] == "cron" and "day" in c.schedule      # monthly
        assert c.expected_max_age_days and c.terms_note


# ---------------------------------------------------------------------------------------------
# Canada, Statistics Canada table 32-10-0353-01
# ---------------------------------------------------------------------------------------------

STATCAN_META_ROUTE = ("POST", po.STATCAN_METADATA_URL)
STATCAN_DATA_ROUTE = ("POST", po.STATCAN_DATA_URL)


def statcan_routes(meta: bytes | None = None, data: bytes | None = None) -> dict:
    return {STATCAN_META_ROUTE: meta if meta is not None else F("real_statcan_getCubeMetadata.json"),
            STATCAN_DATA_ROUTE: data if data is not None else F("real_statcan_data_honey_2015-2025.json")}


def statcan_cube() -> po.StatcanCube:
    return po.parse_statcan_metadata(F("real_statcan_getCubeMetadata.json"))


def edit_statcan(doc: bytes, edit) -> bytes:
    d = json.loads(doc)
    edit(d)
    return json.dumps(d).encode()


def test_real_statcan_metadata_and_request():
    cube = statcan_cube()
    assert (cube.start_year, cube.end_year, cube.release_time) == (1924, 2025, "2026-04-29T09:23")
    assert {k: m.member_id for k, m in cube.estimates.items()} == {"beekeepers": 1, "colonies": 2, "production": 4, "value": 5}
    assert cube.national_id == 1 and len(cube.geos) == 10 and cube.terminated == []
    assert {g.code for g in cube.geos.values() if g.geo_level == 2} == {"11", "12", "13", "24", "35", "46", "47", "48", "59"}
    assert "Does not include Newfoundland and Labrador." in cube.notes_for(1, 4)
    assert "Production excludes inventory." in cube.notes_for(1, 4)
    assert "Production excludes inventory." not in cube.notes_for(1, 2)
    assert cube.corrections and cube.corrections[0].startswith("2025-12-19")
    body = po.statcan_request_body(cube)
    # the body the README fixture was captured with
    assert body == [{"productId": 32100353, "coordinate": f"{g}.{e}.0.0.0.0.0.0.0.0", "latestN": 11}
                    for g in range(1, 11) for e in (1, 2, 4, 5)]


def test_real_statcan_data():
    cube = statcan_cube()
    points, problems = po.parse_statcan_data(F("real_statcan_data_honey_2015-2025.json"), cube)
    assert problems == [] and len(points) == 10 * 4 * 11
    can = {(p.estimate, p.year): p for p in points if p.geo_id == 1}
    p25 = can[("production", 2025)]
    assert (p25.raw, p25.scalar_code, p25.value, p25.flag) == (84080.0, 3, 84080000.0, None)
    assert p25.release == datetime(2026, 4, 29, 8, 30) and p25.vector_id == 47879
    assert can[("value", 2024)].raw == 210238.0 and can[("colonies", 2025)].raw == 854653.0
    assert can[("beekeepers", 2025)].raw == 16360.0
    assert can[("production", 2023)].release == datetime(2024, 12, 12, 8, 30)
    # provinces add up to Canada except one published inconsistency (beekeepers 2017), reported, never fixed
    assert po.check_statcan_totals(points, cube) == [
        "Statistics Canada: Beekeepers 2017: the provinces add up to 10,607, Canada is 10,589; both kept as published"]
    # the 4 Nov capture (estimates 2, 4, 5, latest 5 years) reads the same figures
    old, _ = po.parse_statcan_data(F("real_statcan_data_latest5.json"), cube)
    assert {(p.geo_id, p.estimate, p.year): p.raw for p in old} == {
        (p.geo_id, p.estimate, p.year): p.raw for p in points if p.year >= 2021 and p.estimate != "beekeepers"}


def test_statcan_refusals_and_drift_fail_loudly():
    cube = statcan_cube()
    with pytest.raises(CollectorError, match="no data point"):     # the real answer to a wrong coordinate
        po.parse_statcan_data(F("real_statcan_data_invalid_coordinate.json"), cube)
    meta = F("real_statcan_getCubeMetadata.json")

    def unit(d):
        d[0]["object"]["dimension"][1]["member"][3]["memberUomCode"] = 9999       # production no longer in pounds
    with pytest.raises(CollectorError, match="unit drift"):
        po.parse_statcan_metadata(edit_statcan(meta, unit))

    def renamed(d):
        d[0]["object"]["dimension"][1]["member"][4]["memberNameEn"] = "Value of honey"
    with pytest.raises(CollectorError, match="no estimate 'Value of natural honey, total'"):
        po.parse_statcan_metadata(edit_statcan(meta, renamed))

    def dims(d):
        d[0]["object"]["dimension"][0]["dimensionNameEn"] = "Region"
    with pytest.raises(CollectorError, match="dimensions"):
        po.parse_statcan_metadata(edit_statcan(meta, dims))

    def quarterly(d):
        d[0]["object"]["vectorDataPoint"][0]["refPer"] = "2015-04-01"
    with pytest.raises(CollectorError, match="not a year"):
        po.parse_statcan_data(edit_statcan(F("real_statcan_data_honey_2015-2025.json"), quarterly), cube)


def test_statcan_end_to_end_on_the_real_answers(run, session_factory):
    res = run("ca_statcan_honey", statcan_routes())
    assert res["status"] == "partial", res          # the beekeepers 2017 inconsistency, reported once
    assert res["warnings"] == ["Statistics Canada: Beekeepers 2017: the provinces add up to 10,607, Canada is 10,589; "
                               "both kept as published"]
    assert [(r.method, str(r.url)) for r in run.sent] == [STATCAN_META_ROUTE, STATCAN_DATA_ROUTE]
    assert json.loads(run.sent[0].content) == [{"productId": 32100353}]
    assert json.loads(run.sent[1].content) == po.statcan_request_body(statcan_cube())
    assert res["new"] == 10 * 3 * 11

    with session_factory() as s:
        _no_duplicate_current(s)
        rows = _rows(s, "ca_statcan_honey")
        by_metric: dict[str, list[ProductionStat]] = {}
        for r in rows:
            by_metric.setdefault(r.metric, []).append(r)
        assert {m: len(v) for m, v in by_metric.items()} == {
            "production": 11, "production_value": 11, "colonies": 11,
            "production_by_region": 99, "production_value_by_region": 99, "colonies_by_region": 99}
        assert all(r.country_iso3 == "CAN" and r.frequency == "A" and r.reliability == "official" for r in rows)
        assert all(r.data_status == "published" and r.source_url == po.STATCAN_TABLE_PAGE and r.raw_document_id
                   for r in rows)
        nat = {r.period_label: r for r in by_metric["production"]}
        assert sorted(nat) == [str(y) for y in range(2015, 2026)]
        p25 = nat["2025"]
        assert (p25.value, p25.unit) == (38138.046, "t")             # 84,080 thousand lb x 0.45359237
        assert p25.extra["value_as_published"] == 84080.0 and p25.extra["scalar"] == "thousands"
        assert p25.extra["unit_as_published"] == "Pounds" and "0.45359237" in p25.extra["conversion"]
        assert p25.published_at == date(2026, 4, 29) and "region" not in p25.extra
        assert "Does not include Newfoundland and Labrador." in p25.extra["footnotes"]
        assert nat["2024"].value == 33678.78 and nat["2023"].value == 43384.749
        assert nat["2023"].published_at == date(2024, 12, 12)
        val = {r.period_label: r for r in by_metric["production_value"]}["2025"]
        assert (val.value, val.unit, val.extra["unit_as_published"]) == (241314.0, "1000 CAD", "Dollars")
        col = {r.period_label: r for r in by_metric["colonies"]}["2025"]
        assert (col.value, col.unit, col.extra["beekeepers"]) == (854653.0, "number", 16360.0)
        ab = next(r for r in by_metric["production_by_region"] if r.extra["region_abbr"] == "AB" and r.period_label == "2025")
        assert ab.series_key == "statcan|32-10-0353-01|CA-AB|production_by_region|2025"
        assert (ab.extra["region"], ab.extra["region_code"], ab.extra["value_as_published"]) == ("Alberta", "48", 34216.0)
        assert all("region" in r.extra for m in ("production_by_region", "production_value_by_region",
                                                 "colonies_by_region") for r in by_metric[m])
        raw = s.get(RawDocument, p25.raw_document_id)
        assert raw.url == po.STATCAN_DATA_URL and raw.published_at == date(2026, 4, 29)
        assert _state(s, "ca_statcan_honey")["release"] == "2025|2026-04-29T09:23|1"


def test_statcan_second_run_is_the_metadata_only(run, session_factory):
    assert run("ca_statcan_honey", statcan_routes())["status"] == "partial"
    res = run("ca_statcan_honey", statcan_routes())
    assert res["status"] == "no_change" and [str(r.url) for r in run.sent] == [po.STATCAN_METADATA_URL]
    res = run("ca_statcan_honey", statcan_routes(), force=True)     # forced: read again, nothing new, no repeat warning
    assert res["status"] == "no_change" and res["warnings"] == [] and len(run.sent) == 2


def test_statcan_new_release_with_a_preliminary_revision(run, session_factory):
    assert run("ca_statcan_honey", statcan_routes())["status"] == "partial"

    def release(d):
        d[0]["object"]["releaseTime"] = "2026-12-10T09:00"

    def revise(d):
        for item in d:
            if item["object"]["coordinate"] == "1.4.0.0.0.0.0.0.0.0":
                pt = item["object"]["vectorDataPoint"][-1]
                pt.update({"value": 85000.0, "symbolCode": 1, "releaseTime": "2026-12-10T08:30"})
    res = run("ca_statcan_honey", statcan_routes(meta=edit_statcan(F("real_statcan_getCubeMetadata.json"), release),
                                                 data=edit_statcan(F("real_statcan_data_honey_2015-2025.json"), revise)))
    assert res["revised"] == 1 and res["new"] == 0, res
    # only Canada was changed: the provinces no longer add up, which is reported (once), never fixed
    assert res["status"] == "partial" and res["warnings"] == [
        "Statistics Canada: Production of natural honey, total 2025: the provinces add up to 84,080,000, Canada is "
        "85,000,000; both kept as published"]
    with session_factory() as s:
        hist = _rows(s, "ca_statcan_honey", current=None, metric="production", period_label="2025")
        assert [(r.value, r.is_current) for r in hist] == [(38138.046, False), (round(85000000 * 0.45359237 / 1000, 3), True)]
        cur = hist[-1]
        assert cur.data_status == "provisional" and cur.flag_raw == "p" and cur.published_at == date(2026, 12, 10)


# ---------------------------------------------------------------------------------------------
# Mexico, SIAP year-end close (cierre de la producción pecuaria)
# ---------------------------------------------------------------------------------------------

SIAP_YEARS = list(range(2015, 2026))
XML = "text/xml; charset=\"iso-8859-1\""


def siap_report(year: int) -> bytes:
    return F(f"real_siap_xajax_reporte2_miel_{year}.xml")


def siap_routes(**overrides: bytes) -> dict:
    routes = {po.SIAP_YEARS_URL: (200, F("real_siap_xajax_llenaAnio.xml"), XML)}
    for y in SIAP_YEARS:
        routes[po.siap_report_url(y)] = (200, overrides.get(f"y{y}", siap_report(y)), XML)
    return routes


def test_siap_urls_are_the_ones_checked_live():
    assert po.SIAP_YEARS_URL == "https://nube.agricultura.gob.mx/cierre_pecuario/?xajax=llenaAnio&xajaxargs%5B%5D=aniopec"
    assert po.siap_report_url(2024) == (
        "https://nube.agricultura.gob.mx/cierre_pecuario/?xajax=reporte2&xajaxargs%5B%5D=2024&xajaxargs%5B%5D=undefined"
        "&xajaxargs%5B%5D=0&xajaxargs%5B%5D=0&xajaxargs%5B%5D=0&xajaxargs%5B%5D=0&xajaxargs%5B%5D=1000101"
        "&xajaxargs%5B%5D=0&xajaxargs%5B%5D=0&xajaxargs%5B%5D=1910080&xajaxargs%5B%5D=Miel")


def test_real_siap_answers():
    assert po.parse_siap_years(F("real_siap_xajax_llenaAnio.xml")) == list(range(1980, 2026))
    totals = {}
    for y in SIAP_YEARS:
        rep = po.parse_siap_report(siap_report(y), y)
        assert rep.problems == [] and po.check_siap_report(rep) == [], y      # states = total, price = value / volume
        assert [s.name for s in rep.states] == list(po.MX_STATES), y        # the 32 entities, INEGI order
        totals[y] = rep.total
    assert totals[2024].raw == ("57,430.360", "43.01", "2,469,836.120")
    assert (totals[2024].production_t, totals[2024].price_mxn_kg, totals[2024].value_kmxn) == (57430.36, 43.01, 2469836.12)
    assert totals[2025].production_t == 60297.544 and totals[2015].production_t == 61881.117
    rep = po.parse_siap_report(siap_report(2024), 2024)
    yuc = next(s for s in rep.states if s.name == "Yucatán")
    assert (yuc.production_t, yuc.price_mxn_kg, yuc.value_kmxn) == (9250.391, 27.01, 249886.665)
    assert rep.source_note.startswith("Fuente: Dirección General del Servicio de Información Agroalimentaria")


def test_siap_drift_fails_loudly():
    with pytest.raises(CollectorError, match="not 'Miel"):          # the real wax (cera) report
        po.parse_siap_report(F("real_siap_xajax_reporte2_cera_2025.xml"), 2025)
    with pytest.raises(CollectorError, match="asked for 2025"):
        po.parse_siap_report(siap_report(2024), 2025)
    with pytest.raises(CollectorError, match="columns"):
        po.parse_siap_report(siap_report(2024).replace(b"(toneladas)", b"(kilogramos)"), 2024)
    with pytest.raises(CollectorError, match="'Total' row is incomplete"):
        po.parse_siap_report(siap_report(2024).replace(b"57,430.360", b"n.d."), 2024)
    with pytest.raises(CollectorError, match="no 'Resultado' content"):
        po.parse_siap_report(b'<?xml version="1.0" encoding="iso-8859-1" ?><xjx></xjx>', 2024)


def test_siap_end_to_end_on_the_real_answers(run, session_factory):
    from paladex.models import PriceObservation

    res = run("mx_siap_honey", siap_routes())
    assert res["status"] == "success", res
    assert [str(r.url) for r in run.sent] == [po.SIAP_YEARS_URL] + [po.siap_report_url(y) for y in reversed(SIAP_YEARS)]
    assert all(r.method == "GET" for r in run.sent)
    assert res["new"] == 11 * (2 + 1 + 2 * 32)          # national volume + value, the price, 32 states x 2

    with session_factory() as s:
        _no_duplicate_current(s)
        rows = _rows(s, "mx_siap_honey")
        by_metric: dict[str, list[ProductionStat]] = {}
        for r in rows:
            by_metric.setdefault(r.metric, []).append(r)
        assert {m: len(v) for m, v in by_metric.items()} == {
            "production": 11, "production_value": 11, "production_by_region": 352, "production_value_by_region": 352}
        assert all(r.country_iso3 == "MEX" and r.data_status == "published" and r.published_at is None for r in rows)
        nat = {r.period_label: r for r in by_metric["production"]}
        p24 = nat["2024"]
        assert (p24.value, p24.unit, p24.source_url) == (57430.36, "t", po.siap_report_url(2024))
        assert p24.extra["production_as_published"] == "57,430.360" and p24.extra["price_mxn_per_kg"] == 43.01
        assert "region" not in p24.extra and nat["2025"].value == 60297.544
        v24 = {r.period_label: r for r in by_metric["production_value"]}["2024"]
        assert (v24.value, v24.unit) == (2469836.12, "1000 MXN")
        yuc = next(r for r in by_metric["production_by_region"] if r.extra["region"] == "Yucatán" and r.period_label == "2024")
        assert yuc.series_key == "siap|cierre|MX-YUC|production_by_region|2024" and yuc.value == 9250.391
        assert (yuc.extra["region_code"], yuc.extra["price_mxn_per_kg"]) == ("31", 27.01)
        for y in SIAP_YEARS:                                        # never summed into the national row
            states = [r.value for r in by_metric["production_by_region"] if r.period_label == str(y)]
            assert len(states) == 32 and abs(sum(states) - nat[str(y)].value) < 1e-6
        prices = list(s.scalars(select(PriceObservation).join(Source).where(Source.key == "mx_siap_honey")))
        assert len(prices) == 11 and {p.price_type for p in prices} == {"producer"}      # national only, never states
        pr = next(p for p in prices if p.period_label == "2024")
        assert (pr.price_value, pr.currency, pr.unit, pr.price_per_kg) == (43.01, "MXN", "kg", 43.01)
        assert (pr.origin_iso3, pr.market_iso3, pr.variety) == ("MEX", "MEX", "unspecified")
        assert pr.market_location == "Mexico (national average)" and pr.source_url == po.siap_report_url(2024)


def test_siap_second_run_and_a_revision(run, session_factory):
    assert run("mx_siap_honey", siap_routes())["status"] == "success"
    res = run("mx_siap_honey", siap_routes())
    assert res["status"] == "no_change"
    assert [str(r.url) for r in run.sent] == [po.SIAP_YEARS_URL, po.siap_report_url(2025)]
    # SIAP revises the latest year: every year is read again, only the changed figures become revisions
    revised = siap_report(2025).replace(b"9,893.", b"9,894.").replace(b"60,297.544", b"60,298.544")
    assert b"9,894." in revised
    res = run("mx_siap_honey", siap_routes(y2025=revised))
    assert res["status"] == "success" and res["revised"] == 2 and res["new"] == 0, res
    assert len(run.sent) == 1 + 11
    with session_factory() as s:
        hist = _rows(s, "mx_siap_honey", current=None, metric="production", period_label="2025")
        assert [(r.value, r.is_current) for r in hist] == [(60297.544, False), (60298.544, True)]


def test_siap_unreadable_latest_year_stores_nothing(run, session_factory):
    res = run("mx_siap_honey", siap_routes(y2025=siap_report(2025).replace(b"Miel", b"Cera")))
    assert res["status"] == "failed" and "not 'Miel" in res["error"]
    with session_factory() as s:
        assert _rows(s, "mx_siap_honey", current=None) == []


# ---------------------------------------------------------------------------------------------
# Turkey, TÜİK animal production statistics ("Arıcılık" table)
# ---------------------------------------------------------------------------------------------

TUIK_PRESS_URL = "https://veriportali.tuik.gov.tr/api/tr/press/58015"
TUIK_XLS_URL = ("https://veriportali.tuik.gov.tr/api/tr/data/downloads?t=i&pid=58015&p=KApxb1ssWoKy0ovL00kvLoyG3R9mj7ld"
                "fibsfuYaObxKlGQs8h%2Biw45fC%2FJ%2FTCF6")


def tuik_routes(listing: bytes | None = None, press: bytes | None = None, xls: bytes | None = None) -> dict:
    return {po.TUIK_PRESS_LIST_URL: listing if listing is not None else F("real_tuik_press_list_tr.json"),
            TUIK_PRESS_URL: press if press is not None else F("real_tuik_press_58015_tr.json"),
            TUIK_XLS_URL: (200, xls if xls is not None else F("real_tuik_aricilik_2025.xls"), "application/vnd.ms-excel")}


def test_real_tuik_answers():
    assert po.parse_tuik_press_list(F("real_tuik_press_list_tr.json")) == "58015"
    b = po.parse_tuik_press(F("real_tuik_press_58015_tr.json"), "58015")
    assert (b.title, b.period, b.published, b.table_url) == ("Hayvansal Üretim İstatistikleri", "2025", date(2026, 2, 10),
                                                              TUIK_XLS_URL)
    t = po.parse_tuik_apiculture_xls(F("real_tuik_aricilik_2025.xls"))
    assert (t.title, t.sheet, t.source_note) == ("Arıcılık", "46_t11", "Kaynak: Tarım ve Orman Bakanlığı")
    years = {y.year: y for y in t.years}
    assert sorted(years) == list(range(1991, 2026))
    y24, y25 = years[2024], years[2025]
    assert (y24.honey_t, y24.new_hives, y24.old_hives, y24.holdings, y24.wax_t) == (95492.311, 8717162, 244813, 97984, 3315.791)
    assert (y25.honey_t, y25.new_hives + y25.old_hives) == (97253.019, 8817155)
    assert years[2012].holdings is None                 # '-' before 2013 (villages were counted instead)


def test_tuik_drift_fails_loudly():
    with pytest.raises(CollectorError, match="0 'Hayvansal Üretim İstatistikleri' entries"):
        po.parse_tuik_press_list(F("real_tuik_press_list_tr.json").replace("Hayvansal Üretim".encode(), b"Bitkisel Uretim"))
    with pytest.raises(CollectorError, match="0 'Arıcılık' statistical tables"):
        po.parse_tuik_press(F("real_tuik_press_58015_tr.json").replace('"Arıcılık"'.encode(), b'"Aricilik X"'), "58015")
    with pytest.raises(CollectorError, match="not a readable .xls"):
        po.parse_tuik_apiculture_xls(b"<html>Sayfa bulunamad\xc4\xb1</html>")


def test_tuik_end_to_end_on_the_real_answers(run, session_factory):
    res = run("tr_tuik_honey", tuik_routes())
    assert res["status"] == "success", res
    assert [str(r.url) for r in run.sent] == [po.TUIK_PRESS_LIST_URL, TUIK_PRESS_URL, TUIK_XLS_URL]
    assert [r.headers.get("X-Requested-With") for r in run.sent] == ["XMLHttpRequest", "XMLHttpRequest", None]
    assert res["new"] == 22
    with session_factory() as s:
        _no_duplicate_current(s)
        rows = _rows(s, "tr_tuik_honey")
        prod = {r.period_label: r for r in rows if r.metric == "production"}
        col = {r.period_label: r for r in rows if r.metric == "colonies"}
        assert sorted(prod) == sorted(col) == [str(y) for y in range(2015, 2026)]
        assert all(r.country_iso3 == "TUR" and r.published_at == date(2026, 2, 10) and r.source_url == TUIK_XLS_URL
                   for r in rows)
        assert (prod["2024"].value, prod["2024"].unit) == (95492.311, "t")
        assert prod["2024"].extra["bulletin_url"] == "https://veriportali.tuik.gov.tr/tr/press/58015"
        c24 = col["2024"]
        assert (c24.value, c24.unit) == (8961975.0, "number")
        assert (c24.extra["new_hives"], c24.extra["old_hives"], c24.extra["holdings"]) == (8717162, 244813, 97984)
        raw = s.get(RawDocument, c24.raw_document_id)
        assert raw.url == TUIK_XLS_URL and raw.published_at == date(2026, 2, 10)
    res = run("tr_tuik_honey", tuik_routes())
    assert res["status"] == "no_change" and [str(r.url) for r in run.sent] == [po.TUIK_PRESS_LIST_URL]


# ---------------------------------------------------------------------------------------------
# FAOSTAT and the national agencies side by side in the shared production views (never summed)
# ---------------------------------------------------------------------------------------------


def _faostat(db, iso3: str, rows: dict[int, float], metric: str = "production", unit: str = "t") -> None:
    fao = db.scalars(select(Source).where(Source.key == "faostat")).one()
    for year, value in rows.items():
        start, end = year_bounds(year)
        ingest.record(db, ProductionStat, source_id=fao.id, series_key=f"faostat|QCL|{iso3}|{metric}|{year}",
                      country_iso3=iso3, metric=metric, value=value, unit=unit, period_start=start,
                      period_end=end, period_label=str(year), frequency="A", flag_raw="A",
                      published_at=date(2025, 12, 31), source_url="https://bulks-faostat.fao.org/production/",
                      data_status="published", reliability="official")
    db.commit()


@pytest.mark.parametrize("key,iso3,routes,fao,latest", [
    ("ca_statcan_honey", "CAN", statcan_routes, {2023: 43385.0, 2024: 35460.0}, (2025, 38138.046)),
    ("mx_siap_honey", "MEX", siap_routes, {2023: 58033.18, 2024: 57430.36}, (2025, 60297.544)),
    ("tr_tuik_honey", "TUR", tuik_routes, {2023: 114886.43, 2024: 95492.31}, (2025, 97253.019)),
])
def test_faostat_and_national_agency_side_by_side(run, api, db, key, iso3, routes, fao, latest):
    assert run(key, routes())["status"] in ("success", "partial")
    _faostat(db, iso3, fao)                      # the live FAOSTAT figures (QCL, flag A)
    table = api.get("/api/harvest/production", params={"scope": "all"}).json()
    row = next(c for c in table["countries"] if c["iso3"] == iso3)
    series = {s["source"]["key"]: s for s in row["series"]}
    assert set(series) == {"faostat", key}                           # two series, one per source
    assert (series[key]["latest"]["year"], series[key]["latest"]["value"]) == latest
    assert series[key]["years"] == 11 and series["faostat"]["latest"]["value"] == fao[2024]
    country = api.get(f"/api/harvest/production/{iso3}").json()
    prod = next(m for m in country["metrics"] if m["metric"] == "production")
    assert {s["source"]["key"] for s in prod["series"]} == {"faostat", key}
    assert not any(m["metric"].endswith("_by_region") for m in country["metrics"])
    profile = api.get(f"/api/countries/{iso3}").json()
    prof = next(m for m in profile["production"]["metrics"] if m["metric"] == "production")
    assert {s["source"]["key"] for s in prof["series"]} == {"faostat", key}
