"""Tests for collectors/trade_uruguay_chile.py: Uruguay XXI SIE (uy_honey_exports) and Chile's
Servicio Nacional de Aduanas (cl_honey_exports).

Every fixture in tests/fixtures/trade_uruguay_chile/ is a REAL capture of 5 Nov 2026 (trimmed
where its README says so). Variants (a revision, a withdrawal, a broken layout) are derived from
the real files in this module, never typed in.
"""
from __future__ import annotations

import io
import re
from datetime import date
from pathlib import Path

import httpx
import openpyxl
import pytest
import respx
from sqlalchemy import func, select

from paladex.collectors import trade_uruguay_chile as m
from paladex.collectors.base import CollectorError
from paladex.collectors.trade_official import MIN_UNIT_VALUE_WEIGHT_KG
from paladex.enums import PriceType
from paladex.models import (
    AppSetting,
    PriceObservation,
    RawDocument,
    Source,
    TradeFlowObservation,
)

FIX = Path(__file__).parent / "fixtures" / "trade_uruguay_chile"
T, P = TradeFlowObservation, PriceObservation


def F(name: str) -> bytes:
    return (FIX / name).read_bytes()


# ---------------------------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------------------------


@pytest.fixture()
def run(db, monkeypatch):
    """Run a collector offline. `answer(request) -> httpx.Response` serves every request (GET and
    HEAD); the requests of the last run are in `run.sent`."""
    from paladex.collectors import base
    from paladex.collectors.runner import run_collector

    monkeypatch.setattr(base.time, "sleep", lambda *_: None)

    def _run(key: str, answer, *, force: bool = False) -> dict:
        sent: list[httpx.Request] = []
        _run.sent = sent

        def side_effect(request):
            sent.append(request)
            return answer(request)

        with respx.mock(assert_all_called=False) as mock:
            mock.route().mock(side_effect=side_effect)
            with httpx.Client(follow_redirects=True) as client:
                return run_collector(key, trigger="test", force=force, client=client)

    _run.sent = []
    return _run


@pytest.fixture()
def pin_today(monkeypatch):
    def _pin(d: date):
        monkeypatch.setattr(m, "today", lambda: d)
    _pin(date(2026, 11, 5))
    return _pin


def _rows(s, model, key: str, *, current: bool | None = None, **where):
    src = s.scalars(select(Source).where(Source.key == key)).one()
    q = select(model).where(model.source_id == src.id)
    if current is not None:
        q = q.where(model.is_current.is_(current))
    for k, v in where.items():
        q = q.where(getattr(model, k) == v)
    return s.scalars(q.order_by(model.id)).all()


def _state(s, key: str) -> dict:
    row = s.get(AppSetting, f"collector_state:{key}")
    return dict(row.value) if row else {}


def _no_duplicate_current(s) -> None:
    for model in (T, P):
        dup = s.execute(select(model.source_id, model.series_key, func.count()).where(model.is_current.is_(True))
                        .group_by(model.source_id, model.series_key).having(func.count() > 1)).all()
        assert dup == [], dup


def test_registered_with_official_metadata():
    from paladex.collectors.registry import get_collector

    uy, cl = get_collector("uy_honey_exports"), get_collector("cl_honey_exports")
    assert uy is not None and cl is not None
    for c in (uy, cl):
        assert c.reliability == "official" and c.category == "trade" and c.requires_key is None
        assert 0 < len(c.expected_update) < 120 and 0 < len(c.expected_update_en) < 120
        assert c.schedule["trigger"] == "cron" and "day_of_week" in c.schedule       # weekly
    assert (uy.country_iso3, cl.country_iso3) == ("URY", "CHL")
    assert "no weights" in uy.terms_note.lower() or "publishes no weights" in uy.terms_note
    assert "gross" in cl.terms_note and "KN" in cl.terms_note


# =============================================================================================
# Uruguay XXI SIE: pure functions
# =============================================================================================

SIE_CODES = ("840", "724", "276", "203", "380", "124", "756", "528", "56", "826", "250", "376", "620", "616",
             "784", "682", "208")
SIE_ISO = {"840": "USA", "724": "ESP", "276": "DEU", "203": "CZE", "380": "ITA", "124": "CAN", "756": "CHE",
           "528": "NLD", "56": "BEL", "826": "GBR", "250": "FRA", "376": "ISR", "620": "PRT", "616": "POL",
           "784": "ARE", "682": "SAU", "208": "DNK"}


def sie_pages() -> dict:
    pages = {("mes", ""): F("real_sie_mes_total_2026.html"), ("pais", ""): F("real_sie_pais_total_2026.html")}
    pages.update({("mes", c): F(f"real_sie_mes_{c}_2026.html") for c in SIE_CODES})
    return pages


def sie_answer(over: dict | None = None, *, by_year: dict | None = None):
    """Serve the SIE by (t, pa); `by_year` maps another `a` to its own pages."""
    pages = sie_pages()
    pages.update(over or {})

    def answer(request):
        if request.url.host != "herramientas.uruguayxxi.gub.uy":
            return httpx.Response(404, content=b"unexpected host")
        p = request.url.params
        assert (p["e"], p["cat"], p["ncm"], p["pr"]) == ("", "Todos", "0409", "")    # never a company query
        table = (by_year or {}).get(p["a"], pages if p["a"] == "2026" else {})
        body = table.get((p["t"], p["pa"]))
        if body is None:
            return httpx.Response(404, content=b"no such page")
        return httpx.Response(200, content=body, headers={"content-type": "text/html"})
    return answer


def fmt_sie(v: float) -> str:
    if v == 0:
        return "0"
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def edit_sie(content: bytes, changes: dict[tuple[str, int], float], *, rename: dict[str, str] | None = None) -> bytes:
    """Change cells of a real SIE table (label, year) -> value, recomputing 'Total Detalle' so the
    page stays self-consistent; `rename` changes row labels. Markup is kept as it is."""
    text = content.decode("utf-8")
    t0, t1 = text.find("<table"), text.find("</table>")
    table = text[t0:t1]
    years = [int(y) for y in re.findall(r"<th[^>]*>\s*(\d{4})", table)]
    parsed = []
    for tr in re.findall(r"<tr[^>]*>.*?</tr>", table, re.DOTALL):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.DOTALL)
        if tds:
            parsed.append([tr, re.sub(r"\s+", " ", tds[0]).strip(), [m.parse_sie_number(x.strip()) for x in tds[1:]]])
    for (label, year), v in changes.items():
        row = next(p for p in parsed if p[1] == label)
        row[2][years.index(year)] = v
    total = next(p for p in parsed if p[1] == "Total Detalle")
    total[2] = [round(sum(p[2][i] for p in parsed if p is not total), 2) for i in range(len(years))]
    new = table
    for tr, label, vals in parsed:
        def rep(mo, vals=vals, label=label, k={"i": 0}):  # noqa: B006 - a fresh counter per row (default bound here)
            i = k["i"]
            k["i"] += 1
            if i == 0:
                inner = mo.group(2)
                for old, newname in (rename or {}).items():
                    inner = inner.replace(old, newname) if label == old else inner
                return mo.group(1) + inner + mo.group(3)
            return mo.group(1) + fmt_sie(vals[i - 1]) + mo.group(3)
        new = new.replace(tr, re.sub(r"(<td[^>]*>)(.*?)(</td>)", rep, tr, flags=re.DOTALL), 1)
    return (text[:t0] + new + text[t1:]).encode("utf-8")


def test_parse_sie_number():
    assert m.parse_sie_number("1.662.275,70") == 1662275.7
    assert m.parse_sie_number("0") == 0.0 and m.parse_sie_number("200,00") == 200.0
    assert m.parse_sie_number("36.923,00") == 36923.0
    for bad in ("", "n/d", "1,662,275.70", "1.66.2", None):
        assert m.parse_sie_number(bad) is None


def test_sie_full_page_and_archived_extract_parse_alike():
    page = F("real_sie_mes_total_2026_page.html")
    extract = F("real_sie_mes_total_2026.html")
    a, b = m.parse_sie_table(page, "page"), m.parse_sie_table(extract, "extract")
    assert a.caption == b.caption == "Exportaciones por NCM: '0409', Período: 2022 - 2026"
    assert (a.first_year, a.last_year, a.country, a.ncm) == (2022, 2026, None, "0409")
    assert [c.label for c in a.columns] == ["2022", "2023", "2024", "2025", "2026 (ene - oct)"]
    assert a.columns[-1] == m.SieYearColumn(2026, 1, 10, True, "2026 (ene - oct)")
    assert a.rows == b.rows and a.total == b.total and a.problems == b.problems == []
    assert a.total == [35580437.25, 18478487.19, 27135495.47, 27928748.53, 33100409.13]
    assert m.sie_extract(page) == a.fragment == extract                 # what is archived = the fixture
    assert b'"label":' not in page and b"S.A." not in page              # no company list in the fixture
    years = m.parse_sie_options(page, "anio")
    assert "2026" in years and "2010" in years
    assert len(m.parse_sie_options(page, "pais")) == 296


def test_sie_monthly_coverage_status_and_current_month():
    t = m.parse_sie_table(F("real_sie_mes_total_2026.html"), "total")
    mm = m.sie_monthly(t, "total", date(2026, 11, 5))
    assert len(mm.values) == 58 and min(mm.values) == (2022, 1) and max(mm.values) == (2026, 10)
    assert (2026, 11) not in mm.values and (2026, 12) not in mm.values      # "0" cells of future months: not data
    assert mm.values[(2026, 10)] == 113064.65 and mm.values[(2022, 1)] == 1812935.51
    assert mm.provisional == {(2026, k) for k in range(1, 11)}             # the running year only
    assert (mm.coverage_end, mm.coverage_label) == ((2026, 10), "2026 (ene - oct)")
    # Still October: the month is not over, never stored
    early = m.sie_monthly(t, "total", date(2026, 10, 20))
    assert max(early.values) == (2026, 9) and len(early.values) == 57


def test_sie_destination_table_leaves_out_zero_months():
    """Real: the Czech table has 9 month rows; the missing months are zero, which the year totals
    (equal to the sum of the rows shown) confirm."""
    t = m.parse_sie_table(F("real_sie_mes_203_2026.html"), "CZE")
    assert t.country == "República Checa" and len(t.rows) == 9 and t.problems == []
    mm = m.sie_monthly(t, "CZE", date(2026, 11, 5))
    assert mm.values[(2026, 1)] == 49286.7 and mm.values[(2026, 7)] == 0.0 and mm.values[(2022, 9)] == 0.0
    # the published year total is 293,731.21; the SIE rounds every cell, so the months add up to .22
    assert round(sum(v for (y, _), v in mm.values.items() if y == 2025), 2) == 293731.22 and t.total[3] == 293731.21


def test_sie_layout_drift_fails_loudly():
    extract = F("real_sie_mes_840_2026.html").decode("utf-8")
    with pytest.raises(CollectorError, match="no result block"):
        m.parse_sie_table(b"<html><body>Mantenimiento</body></html>", "x")
    with pytest.raises(CollectorError, match="not an export query"):
        m.parse_sie_table(extract.replace("Exportaciones por NCM: '0409'", "Importaciones con categoria uruguay XXI: 'Miel'")
                          .encode(), "x")
    with pytest.raises(CollectorError, match="not filtered on NCM"):
        m.parse_sie_table(extract.replace("NCM: '0409'", "NCM: '04'").encode(), "x")
    with pytest.raises(CollectorError, match="do not match the period"):
        m.parse_sie_table(extract.replace("2022 - 2026", "2021 - 2025").encode(), "x")
    no_months = extract.replace("2026 (ene - oct)", "2026")
    t = m.parse_sie_table(no_months.encode(), "x")
    with pytest.raises(CollectorError, match="does not state the months"):
        m.sie_monthly(t, "x", date(2026, 11, 5))
    with pytest.raises(CollectorError, match="unexpected row"):
        m.sie_monthly(m.parse_sie_table(extract.replace("Enero", "Ene ro").encode(), "x"), "x", date(2026, 11, 5))
    # A year whose rows no longer add up to its published total is not trusted (not stored).
    bad = extract.replace("2.011.899,18", "2.021.899,18", 1)                     # +10,000 USD in one cell
    tb = m.parse_sie_table(bad.encode(), "x")
    assert any("published total" in p for p in tb.problems)
    mb = m.sie_monthly(tb, "x", date(2026, 11, 5))
    assert 2026 in mb.skipped_years and not any(y == 2026 for y, _ in mb.values)
    assert (2026, 1) in mb.unsure and mb.values[(2025, 1)] == 1207432.68


def test_classify_sie_destinations_by_iso_numeric_code():
    pais = F("real_sie_pais_total_2026.html")
    options = m.parse_sie_options(pais, "pais")
    by_name = {m._norm(v): k for k, v in options.items()}
    table = m.parse_sie_table(pais, "destinations")
    got = {}
    for name, _ in table.rows:
        code = by_name[m._norm(name)]
        got[code] = m.classify_sie_destination(code, name)
    assert {c: iso for c, (iso, _) in got.items()} == SIE_ISO
    assert all(how == "code+name" for _, how in got.values())
    assert m.classify_sie_destination("276", "Francia") == (None, "conflict")
    assert m.classify_sie_destination("902", "Áreas Aduaneras Especiales de Argentina") == (None, "unknown")
    assert m.classify_sie_destination(None, "Z.F. Nueva Palmira") == (None, "unknown")
    assert m.classify_sie_destination("858", "Uruguay") == (None, "unknown")        # never its own market
    assert m.classify_sie_destination("842", "Estados Unidos") == (None, "unknown")  # Comtrade code, not ISO


# =============================================================================================
# Uruguay XXI SIE: end to end
# =============================================================================================


def test_uy_backfill_end_to_end_real(run, session_factory, pin_today):
    res = run("uy_honey_exports", sie_answer())
    assert res["status"] == "success" and res["warnings"] == [], res
    params = [(r.url.params["t"], r.url.params["pa"]) for r in run.sent]
    assert params[:2] == [("mes", ""), ("pais", "")] and len(params) == 19        # 1 total + 1 list + 17 destinations
    assert sorted(pa for t, pa in params[2:]) == sorted(SIE_CODES)
    with session_factory() as s:
        rows = _rows(s, T, "uy_honey_exports")
        assert len(rows) == 295 and all(r.is_current for r in rows)
        assert {r.partner_iso3 for r in rows} == {"WLD", *SIE_ISO.values()}
        assert all((r.reporter_iso3, r.flow, r.currency, r.value_basis, r.frequency, r.hs_code)
                   == ("URY", "export", "USD", "FOB", "M", "0409") for r in rows)
        assert all(r.net_weight_kg is None and r.unit_value_per_kg is None for r in rows)      # no weight published
        assert all(r.reliability == "official" and r.published_at is None for r in rows)
        assert not _rows(s, P, "uy_honey_exports")                                            # never a unit value
        by = {(r.partner_iso3, r.period_label): r for r in rows}
        w = by[("WLD", "2026-10")]
        assert (w.value, w.data_status) == (113064.65, "provisional")
        assert "running year" in w.extra["status_reason"] and w.extra["weight_published"] is False
        assert (by[("USA", "2025-12")].value, by[("USA", "2025-12")].data_status) == (1973426.95, "published")
        assert by[("USA", "2026-03")].value == 3620493.52 and by[("CZE", "2026-01")].value == 49286.7
        assert by[("USA", "2026-03")].source_url == (m.SIE_QUERY_URL + "?t=mes&pr=&e=&a=2026&pa=840&cat=Todos&ncm=0409")
        assert by[("USA", "2026-03")].extra["sie_country_code"] == "840"
        assert ("CZE", "2026-07") not in by                    # zero months: no flow row
        assert not [r for r in rows if r.period_label in ("2026-11", "2026-12")]
        # The 17 destinations add up to the published total in every month (real data)
        months = {r.period_label for r in rows}
        for label in months:
            parts = sum(r.value for r in rows if r.period_label == label and r.partner_iso3 != "WLD")
            assert abs(parts - by[("WLD", label)].value) < 0.05, label
        assert round(sum(r.value for r in rows if r.partner_iso3 == "WLD" and r.period_label.startswith("2025")), 2) == 27928748.52
        # Only the result tables are archived: never a company or person name
        raws = _rows(s, RawDocument, "uy_honey_exports")
        assert len(raws) == 19 and all(r.size_bytes < 30_000 for r in raws)
        st = _state(s, "uy_honey_exports")
        assert st["coverage"] == "2026 (ene - oct)" and st["latest_month"] == "2026-10" and st["backfill_done"]
    from paladex.config import get_settings
    for r in raws:
        body = (get_settings().raw_dir / r.path).read_bytes()
        assert b'"label":' not in body and b"S.A." not in body and b"empresa" not in body


def test_uy_unchanged_totals_cost_one_request(run, session_factory, pin_today):
    assert run("uy_honey_exports", sie_answer())["status"] == "success"
    res = run("uy_honey_exports", sie_answer())
    assert res["status"] == "no_change" and len(run.sent) == 1, res
    # A forced run re-reads everything and changes nothing (idempotent).
    res2 = run("uy_honey_exports", sie_answer(), force=True)
    assert res2["status"] == "no_change" and res2["new"] == 0 and res2["revised"] == 0 and len(run.sent) == 19
    with session_factory() as s:
        assert len(_rows(s, T, "uy_honey_exports")) == 295
        _no_duplicate_current(s)


def test_uy_revision_and_withdrawal(run, session_factory, pin_today):
    """Derived from the real pages: Israel March 2025 revised (+100 USD), Portugal's only shipment
    (March 2025) withdrawn; the list and the total are changed consistently."""
    assert run("uy_honey_exports", sie_answer())["status"] == "success"
    isr = edit_sie(F("real_sie_mes_376_2026.html"), {("Abril", 2025): 128828.25})
    prt = edit_sie(F("real_sie_mes_620_2026.html"), {("Marzo", 2025): 0.0})
    pais = edit_sie(F("real_sie_pais_total_2026.html"), {("Israel", 2025): 185066.92, ("Portugal", 2025): 0.0})
    total_t = m.parse_sie_table(F("real_sie_mes_total_2026.html"), "t")
    april, march = dict(total_t.rows)["Abril"][3], dict(total_t.rows)["Marzo"][3]
    total = edit_sie(F("real_sie_mes_total_2026.html"), {("Abril", 2025): april + 100, ("Marzo", 2025): round(march - 145956.5, 2)})
    res = run("uy_honey_exports", sie_answer({("mes", ""): total, ("pais", ""): pais, ("mes", "376"): isr,
                                              ("mes", "620"): prt}))
    assert res["status"] == "partial" and res["revised"] >= 3, res
    assert any("PRT 2025-03" in w for w in res["warnings"]), res["warnings"]
    assert "620" not in [r.url.params["pa"] for r in run.sent]     # nothing left to read for Portugal
    with session_factory() as s:
        hist = _rows(s, T, "uy_honey_exports", partner_iso3="ISR", period_label="2025-04")
        assert [(h.value, h.revision, h.is_current) for h in hist] == [(128728.25, 1, False), (128828.25, 2, True)]
        assert hist[1].supersedes_id == hist[0].id
        wld = _rows(s, T, "uy_honey_exports", current=True, partner_iso3="WLD", period_label="2025-04")
        assert [w.value for w in wld] == [round(april + 100, 2)]
        prt_rows = _rows(s, T, "uy_honey_exports", partner_iso3="PRT")
        assert [(r.period_label, r.is_current) for r in prt_rows] == [("2025-03", False)]       # kept, not deleted
        _no_duplicate_current(s)


def test_uy_inconsistent_destination_is_left_as_it_is(run, session_factory, pin_today):
    assert run("uy_honey_exports", sie_answer())["status"] == "success"
    isr = edit_sie(F("real_sie_mes_376_2026.html"), {("Abril", 2025): 1.0})       # disagrees with the list
    res = run("uy_honey_exports", sie_answer({("mes", "376"): isr}), force=True)
    assert res["status"] == "partial" and any("Israel 2025" in w and "differ" in w for w in res["warnings"]), res
    with session_factory() as s:
        isr_rows = _rows(s, T, "uy_honey_exports", partner_iso3="ISR")
        assert len(isr_rows) == 11 and all(r.is_current and r.revision == 1 for r in isr_rows)


def test_uy_destination_with_an_untrusted_year_keeps_its_rows(run, session_factory, pin_today):
    """A destination table whose 2025 cells no longer add up to its total: 2025 is not read for it,
    and its stored 2025 rows are not withdrawn on that partial reading."""
    assert run("uy_honey_exports", sie_answer())["status"] == "success"
    isr = F("real_sie_mes_376_2026.html").replace(b"128.728,25", b"138.728,25", 1)    # April 2025 +10,000, total kept
    res = run("uy_honey_exports", sie_answer({("mes", "376"): isr}), force=True)
    assert res["status"] == "partial" and any("Israel" in w and "published total" in w for w in res["warnings"]), res
    assert res["revised"] == 0, res
    with session_factory() as s:
        rows = _rows(s, T, "uy_honey_exports", partner_iso3="ISR")
        assert len(rows) == 11 and all(r.is_current for r in rows)
    neg = m.parse_sie_table(F("real_sie_mes_376_2026.html").replace(b"128.728,25", b"-128.728,25", 1), "x")
    assert any("negative value" in p for p in neg.problems)
    assert (2025, 4) in m.sie_monthly(neg, "x", date(2026, 11, 5)).unsure


def test_uy_unmapped_destination_is_skipped_and_warned_once(run, session_factory, pin_today):
    pais = F("real_sie_pais_total_2026.html")
    i = pais.find(b"<h3")
    renamed = pais[:i] + pais[i:].replace(b"Dinamarca", b"Z.F. Nueva Palmira")      # a free zone, not a country
    res = run("uy_honey_exports", sie_answer({("pais", ""): renamed}))
    assert res["status"] == "partial" and sum("Nueva Palmira" in w for w in res["warnings"]) == 1, res
    with session_factory() as s:
        assert not _rows(s, T, "uy_honey_exports", partner_iso3="DNK")
        assert _rows(s, T, "uy_honey_exports", partner_iso3="WLD", period_label="2022-10")      # the total includes it
        assert "Z.F. Nueva Palmira" in _state(s, "uy_honey_exports")["unknown_partners"]
    res2 = run("uy_honey_exports", sie_answer({("pais", ""): renamed}), force=True)
    assert not any("Nueva Palmira" in w for w in res2["warnings"]), res2


def test_uy_drift_fails_without_storing(run, session_factory, pin_today):
    total = F("real_sie_mes_total_2026.html").replace(b"Exportaciones por NCM: '0409'",
                                                       b"Exportaciones por NCM: '04'")
    res = run("uy_honey_exports", sie_answer({("mes", ""): total}))
    assert res["status"] == "failed" and "not filtered on NCM 0409" in res["error"], res
    wrong = F("real_sie_mes_840_2026.html")
    res2 = run("uy_honey_exports", sie_answer({("mes", "724"): wrong}))
    assert res2["status"] == "failed" and "asked for destination 'España'" in res2["error"], res2
    with session_factory() as s:
        assert not [r for r in _rows(s, T, "uy_honey_exports") if r.partner_iso3 not in ("WLD", "USA")]


def test_uy_new_year_not_offered_yet_falls_back_to_the_newest(run, session_factory, pin_today):
    """2 January 2027: the SIE does not offer 2027 yet (its year selector stops at 2026)."""
    pin_today(date(2027, 1, 2))
    by_year = {"2027": {("mes", ""): F("real_sie_mes_total_2026_page.html")}, "2026": sie_pages()}
    res = run("uy_honey_exports", sie_answer(by_year=by_year))
    assert res["status"] == "success", res
    assert [r.url.params["a"] for r in run.sent[:2]] == ["2027", "2026"]
    with session_factory() as s:
        assert max(r.period_label for r in _rows(s, T, "uy_honey_exports")) == "2026-10"


# =============================================================================================
# Chile, Servicio Nacional de Aduanas: pure functions
# =============================================================================================

DOCS_DUS = "/aduana/site/docs/20241112/20241112153724/"
DOCS_STATS = "/aduana/site/docs/20181214/20181214101258/"
CL_FILES: dict[str, tuple[str, tuple[str, str] | None]] = {
    "/base-de-datos-operaciones-de-salida/aduana/2024-11-12/153724.html": ("real_cl_dus_listing.html", None),
    "/exportacion-por-pais-y-codigo-arancelario/aduana/2018-12-14/101258.html": ("real_cl_stats_listing.html", None),
    DOCS_DUS + "tablas_de_codigos_v2_0.xlsx": ("real_cl_tablas_de_codigos_v2_0.xlsx",
                                               ('"13204-65af8bee9813f"', "Tue, 08 Sep 2026 13:31:01 GMT")),
    DOCS_DUS + "salida_da_09_2026.csv": ("real_cl_salida_da_09_2026_trimmed.csv",
                                         ('"12de1b2-65e5950277f67"', "Wed, 21 Oct 2026 12:59:10 GMT")),
    DOCS_DUS + "salidas_2024.csv": ("real_cl_salidas_2024_trimmed.csv",
                                    ('"194c951-62b1e8d1b611b"', "Tue, 07 Jan 2025 14:27:56 GMT")),
    DOCS_DUS + "salidas_dic_2023.zip": ("real_cl_salidas_dic_2023_trimmed.zip",
                                        ('"5046ed-626bb8232ed65"', "Tue, 12 Nov 2024 18:37:25 GMT")),
    DOCS_STATS + "expo_pais_sa_monto_0112_2025.xlsx": ("real_cl_expo_pais_sa_monto_0112_2025_trimmed.xlsx",
                                                       ('"347db3-6485abb720512"', "Wed, 14 Jan 2026 15:26:29 GMT")),
    DOCS_STATS + "expo_pais_sa_peso_0112_25.xlsx": ("real_cl_expo_pais_sa_peso_0112_25_trimmed.xlsx",
                                                    ('"313a85-6485abc47a0aa"', "Wed, 14 Jan 2026 15:26:43 GMT")),
    DOCS_STATS + "expo_pais_sa_monto_0109_2026.xlsx": ("real_cl_expo_pais_sa_monto_0109_2026_trimmed.xlsx",
                                                       ('"26ede8-65d415b31b3b2"', "Wed, 07 Oct 2026 14:59:04 GMT")),
    DOCS_STATS + "expo_pais_sa_peso_0109_2026.xlsx": ("real_cl_expo_pais_sa_peso_0109_2026_trimmed.xlsx",
                                                      ('"246898-65d415bda01a2"', "Wed, 07 Oct 2026 14:59:15 GMT")),
}
DUS_LISTING = "/base-de-datos-operaciones-de-salida/aduana/2024-11-12/153724.html"


def cl_answer(over: dict | None = None):
    """Serve aduana.cl by path: {path: (bytes, (etag, last-modified) | None)}. HEAD gets the headers."""
    files = {path: (F(name), v) for path, (name, v) in CL_FILES.items()}
    files.update(over or {})

    def answer(request):
        if request.url.host != "www.aduana.cl":
            return httpx.Response(404, content=b"unexpected host")
        spec = files.get(request.url.path)
        if spec is None:
            return httpx.Response(404, content=b"not found")
        body, v = spec
        headers = {"content-type": "text/html" if request.url.path.endswith(".html") else "application/octet-stream"}
        if v:
            headers.update({"etag": v[0], "last-modified": v[1]})
        headers["content-length"] = str(len(body))
        if request.method == "HEAD":
            return httpx.Response(200, headers=headers)
        return httpx.Response(200, content=body, headers=headers)
    return answer


def test_parse_real_listings_and_code_table():
    lst = m.parse_cl_dus_listing(F("real_cl_dus_listing.html"))
    assert min(lst.years) == 2002 and max(lst.years) == 2026
    assert lst.years[2026].endswith("/salida_da_09_2026.csv") and lst.years[2025].endswith("/salidas2025.rar")
    assert lst.years[2023].endswith("/salidas_dic_2023.zip") and lst.years[2024].startswith("https://www.aduana.cl/")
    assert lst.code_table_url.endswith("/tablas_de_codigos_v2_0.xlsx")
    assert lst.operation_types == m.CL_EXPORT_OPERATION_TYPES
    stats = m.parse_cl_stats_listing(F("real_cl_stats_listing.html"))
    assert stats[("monto", 2025)].endswith("expo_pais_sa_monto_0112_2025.xlsx")
    assert stats[("peso", 2025)].endswith("expo_pais_sa_peso_0112_25.xlsx")          # irregular names: read, not built
    assert stats[("peso", 2026)].endswith("expo_pais_sa_peso_0109_2026.xlsx")
    with pytest.raises(CollectorError, match="no yearly file link"):
        m.parse_cl_dus_listing(b"<html><a href='/x.html'>Inicio</a></html>")
    names = m.parse_cl_country_table(F("real_cl_tablas_de_codigos_v2_0.xlsx"))
    assert len(names) == 258 and names[563] == "Alemania" and names[515] == "Holanda"
    for code, (iso, _) in m.CL_COUNTRY_CODES.items():
        assert m.classify_cl_destination(code, names)[:2] == (iso, "table+name"), code
    assert m.classify_cl_destination(226, names)[:2] == ("CAN", "name")
    for code in (0, 502, 902, 905, 997, 249, 888):          # unknown, West Germany, ships' stores, free zone, Chile...
        assert m.classify_cl_destination(code, names)[0] is None, code
    assert m.classify_cl_destination(563, {**names, 563: "Francia"})[:2] == (None, "conflict")
    wb = openpyxl.Workbook()
    wb.active.title = "Monedas"
    buf = io.BytesIO()
    wb.save(buf)
    with pytest.raises(CollectorError, match="no 'Países' sheet"):
        m.parse_cl_country_table(buf.getvalue())


def test_parse_cl_dus_real_files():
    d26 = m.parse_cl_dus(F("real_cl_salida_da_09_2026_trimmed.csv"), year=2026, url="x.csv")
    assert len(d26.rows) == 101 and sorted(d26.months_in_file) == list(range(1, 10)) and d26.problems == []
    assert {r.sach for r in d26.rows} == {"04090010", "04090090"} and {r.unit for r in d26.rows} == {6}
    first = d26.rows[0]
    assert (first.month, first.op_type, first.dest_code, first.sach, first.fob_usd, first.gross_kg, first.quantity) == (
        1, 200, 505, "04090090", 248297.84, 90288.0, 85824.0)
    lines = F("real_cl_salida_da_09_2026_trimmed.csv").split(b"\n")
    assert d26.extract.split(b"\n")[0] == lines[0]                                   # header kept verbatim
    assert d26.extract.count(b";0409") == 101 and b"13220409,22" not in d26.extract  # decoys never kept
    d23 = m.parse_cl_dus(F("real_cl_salidas_dic_2023_trimmed.zip"), year=2023, url="x.zip")
    assert d23.member == "Salidas_dic_2023.csv" and len(d23.rows) == 86 and sorted(d23.months_in_file) == list(range(1, 13))
    assert d23.rows[0].sach == "04090090" and d23.rows[0].fob_usd == 66109.5               # quoted fields read
    with pytest.raises(m.ClUnreadable):
        m.parse_cl_dus(b"Rar!\x1a\x07\x01\x00" + b"\x00" * 20, year=2025, url="y.rar")
    no_fob = F("real_cl_salida_da_09_2026_trimmed.csv").replace(b"FOBUS_AJUSTADO_IVV", b"FOB_AJUSTADO", 1)
    with pytest.raises(CollectorError, match="FOBUS_AJUSTADO_IVV"):
        m.parse_cl_dus(no_fob, year=2026, url="x.csv")
    other_year = m.parse_cl_dus(F("real_cl_salida_da_09_2026_trimmed.csv"), year=2025, url="x.csv")
    assert other_year.rows == [] and other_year.other_years == 138                # every data line of the file


def test_parse_cl_numbers():
    assert m.parse_cl_number("29501,08") == 29501.08 and m.parse_cl_number("613") == 613.0
    assert m.parse_cl_number('"9,1"') == 9.1 and m.parse_cl_number("1.234,5") == 1234.5
    for bad in ("", "1.234", "1.5", "n/d", None, "12,3,4"):
        assert m.parse_cl_number(bad) is None


def test_parse_cl_statistics_workbooks():
    monto = m.parse_cl_stats_book(F("real_cl_expo_pais_sa_monto_0112_2025_trimmed.xlsx"), kind="monto", year=2025, url="m")
    peso = m.parse_cl_stats_book(F("real_cl_expo_pais_sa_peso_0112_25_trimmed.xlsx"), kind="peso", year=2025, url="p")
    assert monto.months == list(range(1, 13)) and len(monto.values) == 20 and monto.problems == []
    assert round(sum(monto.values[("Alemania", "04090090")].values()), 2) == 13839045.12
    assert round(sum(peso.values[("Alemania", "04090090")].values()), 1) == 5775531.5
    assert ("Albania", "00259900") not in monto.values                  # not honey
    with pytest.raises(CollectorError, match="peso en kilos brutos"):
        m.parse_cl_stats_book(F("real_cl_expo_pais_sa_monto_0112_2025_trimmed.xlsx"), kind="peso", year=2025, url="m")
    with pytest.raises(CollectorError, match="no month columns of 2024"):
        m.parse_cl_stats_book(F("real_cl_expo_pais_sa_monto_0112_2025_trimmed.xlsx"), kind="monto", year=2024, url="m")


def test_cl_window_is_whole_years_over_36_months():
    assert m.cl_window_start((2026, 9)) == (2023, 1)
    assert m.cl_window_start((2027, 1)) == (2024, 1)
    assert m.cl_window_start((2026, 12)) == (2024, 1)


# =============================================================================================
# Chile: end to end
# =============================================================================================


def test_cl_backfill_end_to_end_real(run, session_factory):
    res = run("cl_honey_exports", cl_answer())
    assert res["status"] == "partial", res                 # 2025 is a RAR archive: read from the statistics, warned
    assert len(res["warnings"]) == 1 and "RAR" not in res["warnings"][0] and ".rar archive" in res["warnings"][0]
    assert [(r.method, r.url.path.rsplit("/", 1)[-1]) for r in run.sent] == [
        ("GET", "153724.html"), ("GET", "salida_da_09_2026.csv"), ("GET", "tablas_de_codigos_v2_0.xlsx"),
        ("GET", "101258.html"), ("GET", "expo_pais_sa_monto_0112_2025.xlsx"), ("GET", "expo_pais_sa_peso_0112_25.xlsx"),
        ("GET", "salidas_2024.csv"), ("GET", "salidas_dic_2023.zip")]
    with session_factory() as s:
        trades = _rows(s, T, "cl_honey_exports")
        assert len(trades) == 201 and min(t.period_label for t in trades) == "2023-01"
        assert max(t.period_label for t in trades) == "2026-09"
        assert all((t.reporter_iso3, t.flow, t.currency, t.value_basis, t.frequency, t.hs_code, t.data_status, t.reliability)
                   == ("CHL", "export", "USD", "FOB", "M", "0409", "published", "official") for t in trades)
        by = {(t.partner_iso3, t.period_label): t for t in trades}
        de = by[("DEU", "2026-01")]
        assert (de.value, de.net_weight_kg, de.unit_value_per_kg) == (798187.67, 280622.0, 2.8444)
        assert de.published_at == date(2026, 10, 21) and de.source_url.endswith("/salida_da_09_2026.csv")
        x = de.extra
        assert x["gross_weight_kg"] == 295366.0 and x["family"] == "dus" and x["destination_codes"] == [563]
        assert [(ln["sach"], ln["fob_usd"], ln["net_kg"], ln["gross_kg"]) for ln in x["sach_lines"]] == [
            ("04090010", 82921.2, 21456.0, 22572.0), ("04090090", 715266.47, 259166.0, 272794.0)]
        # 2024: the totals UN Comtrade republishes within 0.02 % (14,677,655.25 USD / 5,790,439.9 kg)
        y24 = [t for t in trades if t.period_label.startswith("2024")]
        assert round(sum(t.value for t in y24), 2) == 14680630.19 and round(sum(t.net_weight_kg for t in y24), 1) == 5790457.5
        assert all(t.published_at == date(2025, 1, 7) for t in y24)
        # 2025 from the statistics workbooks: FOB, gross weight in extra, never a net weight
        y25 = [t for t in trades if t.period_label.startswith("2025")]
        assert len(y25) == 61 and all(t.net_weight_kg is None and t.extra["family"] == "stats" for t in y25)
        assert round(sum(t.value for t in y25), 2) == 21420938.73
        assert by[("DEU", "2025-04")].extra["gross_weight_kg"] == 1349902.1
        assert {t.published_at for t in y25} == {date(2026, 1, 14)}
        prices = _rows(s, P, "cl_honey_exports")
        assert len(prices) == 116 and {p.price_type for p in prices} == {PriceType.EXPORT_UNIT_VALUE}
        assert all(p.volume_kg >= MIN_UNIT_VALUE_WEIGHT_KG for p in prices)
        assert not [p for p in prices if p.period_label.startswith("2025")]          # no net weight, no unit value
        pd = _rows(s, P, "cl_honey_exports", market_iso3="DEU", period_label="2026-01")[0]
        assert (pd.price_value, pd.usd_per_kg, pd.origin_iso3, pd.terms, pd.currency, pd.unit) == (
            2.8444, 2.8444, "CHL", "FOB", "USD", "kg")
        usa = _rows(s, P, "cl_honey_exports", market_iso3="USA", period_label="2026-09")[0]
        assert (usa.volume_kg, usa.price_value) == (1161.6, round(9853.86 / 1161.6, 4))
        assert by[("COL", "2026-05")].value == 51.54                                  # 32 kg: trade row only
        assert not _rows(s, P, "cl_honey_exports", market_iso3="COL", period_label="2026-05")
        raws = _rows(s, RawDocument, "cl_honey_exports")
        assert len(raws) == 6 and all(r.size_bytes < 100_000 for r in raws)
        st = _state(s, "cl_honey_exports")
        assert st["latest_month"] == "2026-09" and st["years"]["2025"]["family"] == "stats"
        assert len(st["dus_months"]) == 33


def test_cl_unchanged_files_cost_head_requests_only(run, session_factory):
    assert run("cl_honey_exports", cl_answer())["status"] == "partial"
    res = run("cl_honey_exports", cl_answer())
    assert res["status"] == "no_change" and res["warnings"] == [], res
    assert [(r.method, r.url.path.rsplit("/", 1)[-1]) for r in run.sent] == [
        ("GET", "153724.html"), ("HEAD", "salida_da_09_2026.csv"), ("GET", "101258.html"),
        ("HEAD", "expo_pais_sa_monto_0112_2025.xlsx"), ("HEAD", "expo_pais_sa_peso_0112_25.xlsx"),
        ("HEAD", "salidas_2024.csv"), ("HEAD", "salidas_dic_2023.zip")]
    res2 = run("cl_honey_exports", cl_answer(), force=True)
    assert res2["status"] == "no_change" and res2["new"] == 0 and res2["revised"] == 0, res2
    with session_factory() as s:
        assert len(_rows(s, T, "cl_honey_exports")) == 201
        _no_duplicate_current(s)


def _new_release() -> tuple[bytes, bytes]:
    """The next monthly file, derived from the real one: Germany September revised (406,113.44 ->
    407,113.44 USD), Portugal September withdrawn, a first October shipment (a copy of a real
    September line). The listing points to `salida_da_10_2026.csv`."""
    csv_bytes = F("real_cl_salida_da_09_2026_trimmed.csv")
    lines = csv_bytes.split(b"\n")
    out = []
    october = None
    for ln in lines:
        if ln.startswith(b"2026;9;") and b";501;" in ln and b";04090090;" in ln:
            continue                                                    # Portugal 2026-09 gone
        if ln.startswith(b"2026;9;") and b";406113,44;406113,44;" in ln:
            ln = ln.replace(b";406113,44;406113,44;", b";407113,44;407113,44;")
        if ln.startswith(b"2026;9;") and b";505;" in ln and b";04090090;" in ln:
            october = b"2026;10;" + ln[len(b"2026;9;"):]
        out.append(ln)
    assert october is not None
    out.insert(-1, october)
    listing = F("real_cl_dus_listing.html").replace(b"salida_da_09_2026.csv", b"salida_da_10_2026.csv")
    return b"\n".join(out), listing


def test_cl_new_release_revises_withdraws_and_adds(run, session_factory):
    assert run("cl_honey_exports", cl_answer())["status"] == "partial"
    data, listing = _new_release()
    res = run("cl_honey_exports", cl_answer({
        DUS_LISTING: (listing, None),
        DOCS_DUS + "salida_da_10_2026.csv": (data, ('"new"', "Thu, 19 Nov 2026 12:00:00 GMT"))}))
    assert res["status"] == "partial" and any("PRT 2026-09" in w for w in res["warnings"]), res
    assert ("GET", "salida_da_10_2026.csv") in [(r.method, r.url.path.rsplit("/", 1)[-1]) for r in run.sent]
    with session_factory() as s:
        hist = _rows(s, T, "cl_honey_exports", partner_iso3="DEU", period_label="2026-09")
        # 178,983 + 54,265 + 184,167.96 + 406,113.44 + 71,031.50 = 894,560.90 USD; 261,164 kg net
        assert [(h.value, h.revision, h.is_current) for h in hist] == [(894560.9, 1, False), (895560.9, 2, True)]
        assert hist[1].net_weight_kg == 261164.0
        assert hist[1].published_at == date(2026, 11, 19) and hist[0].published_at == date(2026, 10, 21)
        ph = _rows(s, P, "cl_honey_exports", market_iso3="DEU", period_label="2026-09")
        assert [p.is_current for p in ph] == [False, True] and ph[1].price_value == round(895560.9 / 261164, 4)
        prt = _rows(s, T, "cl_honey_exports", partner_iso3="PRT", period_label="2026-09")
        assert [r.is_current for r in prt] == [False]
        assert not _rows(s, P, "cl_honey_exports", current=True, market_iso3="PRT", period_label="2026-09")
        oct_rows = _rows(s, T, "cl_honey_exports", period_label="2026-10")
        assert [(r.partner_iso3, r.value, r.net_weight_kg) for r in oct_rows] == [("FRA", 73453.29, 21456.0)]
        unchanged = _rows(s, T, "cl_honey_exports", partner_iso3="DEU", period_label="2026-01")
        assert [(r.revision, r.published_at) for r in unchanged] == [(1, date(2026, 10, 21))]
        assert _state(s, "cl_honey_exports")["latest_month"] == "2026-10"
        _no_duplicate_current(s)


def test_cl_unknown_destination_and_quantity_not_in_net_kilos(run, session_factory):
    data = F("real_cl_salida_da_09_2026_trimmed.csv")
    data = data.replace(b"2026;1;48;200;13;4;992;499;341;", b"2026;1;48;200;13;4;992;499;905;", 1)    # UAE -> free zone
    data = data.replace(b";04090090;4926,93;4926,93;901,5;580,8;6", b";04090090;4926,93;4926,93;901,5;580,8;10", 1)
    res = run("cl_honey_exports", cl_answer({DOCS_DUS + "salida_da_09_2026.csv": (data, ('"x"', "Wed, 21 Oct 2026 12:59:10 GMT"))}))
    assert res["status"] == "partial", res
    assert sum("905" in w and "Zona franca Iquique" in w for w in res["warnings"]) == 1
    assert any("USA" in w and "not declared in KN" in w for w in res["warnings"])
    with session_factory() as s:
        assert not _rows(s, T, "cl_honey_exports", partner_iso3="ARE", period_label="2026-01")
        usa = _rows(s, T, "cl_honey_exports", partner_iso3="USA", period_label="2026-09")[0]
        assert usa.value == 9853.86 and usa.net_weight_kg is None and usa.extra["gross_weight_kg"] == 1803.0
        assert not _rows(s, P, "cl_honey_exports", market_iso3="USA", period_label="2026-09")
        assert "905" in _state(s, "cl_honey_exports")["unknown_partners"]


def test_cl_schema_drift_fails_without_storing(run, session_factory):
    no_fob = F("real_cl_salida_da_09_2026_trimmed.csv").replace(b"FOBUS_AJUSTADO_IVV", b"FOB_AJUSTADO", 1)
    res = run("cl_honey_exports", cl_answer({DOCS_DUS + "salida_da_09_2026.csv": (no_fob, None)}))
    assert res["status"] == "failed" and "FOBUS_AJUSTADO_IVV" in res["error"], res
    res2 = run("cl_honey_exports", cl_answer({DUS_LISTING: (b"<html><body>Sitio en mantenimiento</body></html>", None)}))
    assert res2["status"] == "failed" and "no yearly file link" in res2["error"], res2
    gross_as_fob = F("real_cl_expo_pais_sa_peso_0112_25_trimmed.xlsx")
    res3 = run("cl_honey_exports", cl_answer({DOCS_STATS + "expo_pais_sa_monto_0112_2025.xlsx": (gross_as_fob, None)}))
    assert res3["status"] == "failed" and "monto fob" in res3["error"], res3
    with session_factory() as s:
        assert not [t for t in _rows(s, T, "cl_honey_exports") if t.period_label.startswith("2025")]


def test_cl_statistics_fallback_never_overwrites_net_weights(run, session_factory):
    """If the running year's DUS file later comes as a RAR archive, its months already stored with
    net weights are not replaced by the gross-only statistics."""
    assert run("cl_honey_exports", cl_answer())["status"] == "partial"
    listing = F("real_cl_dus_listing.html").replace(b"salida_da_09_2026.csv", b"salidas2026.rar")
    res = run("cl_honey_exports", cl_answer({DUS_LISTING: (listing, None)}))
    assert res["status"] == "partial" and res["revised"] == 0 and res["new"] == 0, res
    assert any("2026 file of the DUS base is a .rar archive" in w for w in res["warnings"])
    with session_factory() as s:
        de = _rows(s, T, "cl_honey_exports", partner_iso3="DEU", period_label="2026-01")
        assert [(r.net_weight_kg, r.revision, r.is_current) for r in de] == [(280622.0, 1, True)]
        assert len(_rows(s, P, "cl_honey_exports", current=True)) == 116
