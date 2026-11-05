"""Tests for collectors/trade_origins.py: Ukraine (State Customs Service open data, `ua_honey_exports`)
and Mexico (INEGI BCMM monthly cube, `mx_honey_exports`) honey exports by destination.

The fixtures in tests/fixtures/trade_origins/ are REAL captures of 2026-11-05 (gzipped here; see the
README there). Variants (a new release, a revision, a bad download, schema drift) are built from them
in code.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
import respx
from sqlalchemy import select

from paladex.collectors import trade_origins as to
from paladex.collectors.base import CollectorError
from paladex.collectors.registry import get_collector
from paladex.enums import DataStatus, PriceType
from paladex.models import (
    AppSetting,
    PriceObservation,
    RawDocument,
    Source,
    TradeFlowObservation,
)

FIX = Path(__file__).parent / "fixtures" / "trade_origins"
T, P = TradeFlowObservation, PriceObservation
UA, MX = "ua_honey_exports", "mx_honey_exports"


def G(name: str) -> bytes:
    return gzip.decompress((FIX / name).read_bytes())


def raw_gz(name: str) -> bytes:
    """A fixture served as the .gz file data.gov.ua would send."""
    return (FIX / name).read_bytes()


UA_FILES = {(2026, 8): "real_ua_bi_trade_2026-08_en_honey_rows.csv.gz",
            (2026, 9): "real_ua_bi_trade_2026-09_en_excerpt.csv.gz",
            (2026, 10): "real_ua_bi_trade_2026-10_en_honey_rows.csv.gz"}


def ua_package(files: dict[tuple[int, int], bytes]) -> dict:
    """The real package_show answer, reduced to the months in `files`; the MD5 and size data.gov.ua lists
    are those of the bytes served (the fixtures are excerpts of the real 10 MB files)."""
    doc = json.loads(G("real_datagovua_package_show_scsu-bi-trade-src-en_2026-11-05.json.gz"))
    keep = []
    for r in doc["result"]["resources"]:
        m = to.UA_RESOURCE_RE.fullmatch(r["name"])
        if m and (int(m.group(1)), int(m.group(2))) in files:
            body = files[(int(m.group(1)), int(m.group(2)))]
            keep.append({**r, "file_hash_sum": hashlib.md5(body).hexdigest(), "size": len(body)})
    doc["result"]["resources"] = keep
    return doc


def rewrite_ua(name: str, edit) -> bytes:
    """A fixture file with its CSV rows passed through `edit(header, rows) -> rows`, re-gzipped."""
    rows = list(csv.reader(io.StringIO(G(name).decode("utf-8"), newline="")))
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(rows[0])
    for r in edit(rows[0], rows[1:]):
        w.writerow(r)
    return gzip.compress(out.getvalue().encode("utf-8"), mtime=0)


# ---------------------------------------------------------------------------------------------
# Harnesses
# ---------------------------------------------------------------------------------------------


@pytest.fixture()
def run_ua(db, monkeypatch):
    """Run `ua_honey_exports` offline. `files` maps months to the bytes served (default: the three real
    fixtures); `package` overrides the package_show answer; `md5_of` overrides the bytes whose MD5 is listed."""
    from paladex.collectors import base
    from paladex.collectors.runner import run_collector

    monkeypatch.setattr(base.time, "sleep", lambda *_: None)

    def _run(files=None, package=None, force=False, served=None) -> dict:
        files = files or {m: raw_gz(n) for m, n in UA_FILES.items()}
        pkg = package or ua_package(files)
        urls = {r["url"]: r for r in pkg["result"]["resources"]}
        sent: list[httpx.Request] = []
        _run.sent = sent

        def reply(request):
            sent.append(request)
            url = str(request.url)
            if url.startswith(to.UA_PACKAGE_URL):
                return httpx.Response(200, content=json.dumps(pkg).encode(), headers={"content-type": "application/json"})
            r = urls.get(url)
            if r is None:
                return httpx.Response(404, content=b"not found")
            m = to.UA_RESOURCE_RE.fullmatch(r["name"])
            month = (int(m.group(1)), int(m.group(2)))
            body = (served or {}).get(month, files[month])
            return httpx.Response(200, content=body, headers={"content-type": "application/gzip"})

        with respx.mock(assert_all_called=False) as mock:
            mock.route(host="data.gov.ua").mock(side_effect=reply)
            mock.route().mock(side_effect=httpx.ConnectError("blocked in tests"))
            with httpx.Client(follow_redirects=True) as client:
                return run_collector(UA, trigger="test", force=force, client=client)

    _run.sent = []
    return _run


def mx_page(year: int, page: int) -> bytes:
    return G(f"real_inegi_honey_exports_{year}_p{page}.html.gz")


MX_START = G("real_inegi_bcmm_start_2026-11-05.html.gz")


@pytest.fixture()
def run_mx(db, monkeypatch):
    """Run `mx_honey_exports` offline: GET of the cube page, POSTs of the viewer form answered with the
    real page for the year and page asked. `pages` overrides {(year, page): bytes}."""
    from paladex.collectors import base
    from paladex.collectors.runner import run_collector

    monkeypatch.setattr(base.time, "sleep", lambda *_: None)

    def _run(start: bytes = MX_START, pages=None, force=False) -> dict:
        sent: list[tuple[str, int, int]] = []
        _run.sent = sent

        def query(request):
            form = parse_qs(request.content.decode("ascii"), encoding="cp1252")
            year = int(form["rows"][0].split("[Año].&[")[1].split("]")[0])
            page = int(form["NumPagFil"][0])
            sent.append(("query", year, page))
            body = (pages or {}).get((year, page))
            if body is None:
                body = mx_page(year, page)
            return httpx.Response(200, content=body, headers={"content-type": "text/html"})

        def start_page(request):
            sent.append(("start", 0, 0))
            return httpx.Response(200, content=start, headers={"content-type": "text/html"})

        with respx.mock(assert_all_called=False) as mock:
            mock.route(method="GET", url__startswith=to.INEGI_START_URL).mock(side_effect=start_page)
            mock.route(method="POST", url__startswith=to.INEGI_QUERY_URL).mock(side_effect=query)
            mock.route().mock(side_effect=httpx.ConnectError("blocked in tests"))
            with httpx.Client(follow_redirects=True) as client:
                return run_collector(MX, trigger="test", force=force, client=client)

    _run.sent = []
    return _run


def _rows(s, key, model, *, current=True, **where):
    src = s.scalars(select(Source).where(Source.key == key)).one()
    q = select(model).where(model.source_id == src.id)
    if current is not None:
        q = q.where(model.is_current.is_(current))
    for k, v in where.items():
        q = q.where(getattr(model, k) == v)
    return s.scalars(q.order_by(model.id)).all()


def _one(s, key, **where):
    rows = _rows(s, key, T, **where)
    assert len(rows) == 1, rows
    return rows[0]


# ---------------------------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("key,iso3", [(UA, "UKR"), (MX, "MEX")])
def test_registered_with_official_metadata(key, iso3):
    c = get_collector(key)
    assert c is not None and c.country_iso3 == iso3 and c.reliability == "official" and c.category == "trade"
    assert c.name_en and c.publisher and c.terms_note and c.homepage.startswith("https://")
    assert 0 < len(c.expected_update) < 120 and 0 < len(c.expected_update_en) < 120
    assert c.schedule["trigger"] == "cron"


# ---------------------------------------------------------------------------------------------
# Ukraine: pure functions on the real files
# ---------------------------------------------------------------------------------------------


def test_parse_real_package():
    res, notes = to.parse_ua_package(G("real_datagovua_package_show_scsu-bi-trade-src-en_2026-11-05.json.gz"))
    assert len(res) == 118 and max(res) == (2026, 10) and min(res) == (2017, 1)
    newest = res[(2026, 10)]
    assert newest.md5 == "b901d40253d7c566396aca65e77ed43d" and newest.modified == date(2026, 11, 3)
    # 2023-05 is listed twice: the newer upload is read, and said so.
    assert res[(2023, 5)].resource_id == "6c3b4f38-ac05-4d0f-802e-221d366d56a7"
    assert len(notes) == 1 and "BI_trade_2023-05_EN is listed twice" in notes[0]
    with pytest.raises(CollectorError):
        to.parse_ua_package(b'{"success": false, "error": {"message": "Not found"}}')
    with pytest.raises(CollectorError):
        to.parse_ua_package(json.dumps({"success": True, "result": {"resources": [{"name": "BI_trade_2026_EN"}]}}).encode())


def test_parse_real_month_file():
    p = to.parse_ua_month(raw_gz(UA_FILES[(2026, 9)]), (2026, 9))
    assert p.problems == [] and p.total_rows == 373 and p.honey_rows == 73 and p.import_rows == 2
    assert len(p.rows) == 72                                  # 73 honey rows, one is an import only
    assert round(sum(r.export_usd for r in p.rows), 2) == 24_471_650.0
    assert round(sum(r.kg for r in p.rows), 2) == 7_604_630.94
    mixed = [r for r in p.rows if r.kg_basis != "netto"]
    # Poland, Khmelnytskyi office: 498,550 kg for both flows; the taxed imports (all imports) weigh 21,240 kg.
    assert [(r.partner, r.kg, r.kg_basis) for r in mixed] == [("PL Poland", 477_310.0, "netto_minus_taxed_import")]
    extract = list(csv.reader(io.StringIO(p.extract.decode("utf-8"))))
    assert len(extract) == 74 and extract[0][0] == "Year"   # header + every honey row (both flows)
    assert {r.code for r in p.rows} == {"0409000000"}


def test_mixed_row_without_full_taxed_imports_has_no_weight():
    def edit(h, rows):
        i = h.index("Taxed import USD")
        return [r[:i] + ["1000.0"] + r[i + 1:] if r[h.index("Import USD")] == "64021.43" else r for r in rows]
    p = to.parse_ua_month(rewrite_ua(UA_FILES[(2026, 9)], edit), (2026, 9))
    pl = [r for r in p.rows if r.kg_basis != "netto"]
    assert [(r.kg, r.kg_basis) for r in pl] == [(None, "unknown_mixed_row")]


def test_month_file_fails_loudly():
    with pytest.raises(CollectorError, match="not a gzip"):
        to.parse_ua_month(b"<html>maintenance</html>", (2026, 9))
    no_kg = rewrite_ua(UA_FILES[(2026, 8)], lambda h, rows: rows)
    text = gzip.decompress(no_kg).decode().replace("Netto kg", "Net kg", 1)
    with pytest.raises(CollectorError, match="schema drift"):
        to.parse_ua_month(gzip.compress(text.encode()), (2026, 8))
    with pytest.raises(CollectorError, match="another month"):
        to.parse_ua_month(raw_gz(UA_FILES[(2026, 8)]), (2026, 7))


@pytest.mark.parametrize("raw,expected", [
    ("PL Poland", ("POL", "iso2")), ("US United States", ("USA", "iso2")), ("GB United Kingdom", ("GBR", "iso2")),
    ("  Unspecified", (None, "unspecified")), ("nan", (None, "unspecified")), ("PL Germany", (None, "conflict")),
    ("Poland", (None, "unknown")), ("QQ Nowhere", (None, "unknown")),
])
def test_map_ua_partner(raw, expected):
    assert to.map_ua_partner(raw) == expected


def test_ua_status_rule():
    assert to.ua_data_status(2026, 2026) == DataStatus.PROVISIONAL
    assert to.ua_data_status(2025, 2026) == DataStatus.PROVISIONAL
    assert to.ua_data_status(2024, 2026) == DataStatus.PUBLISHED


# ---------------------------------------------------------------------------------------------
# Ukraine: end to end
# ---------------------------------------------------------------------------------------------


def test_ua_end_to_end(run_ua, session_factory):
    res = run_ua()
    assert res["status"] == "success", res
    assert len(run_ua.sent) == 4                              # package_show + 3 files
    with session_factory() as s:
        wld = _one(s, UA, partner_iso3="WLD", period_label="2026-09")
        assert (wld.value, wld.net_weight_kg, wld.currency, wld.flow, wld.frequency) == (
            24_471_650.0, 7_604_630.94, "USD", "export", "M")
        assert wld.reporter_iso3 == "UKR" and wld.data_status == "provisional" and wld.published_at == date(2026, 11, 3)
        assert wld.extra["partners"] == 26 and wld.extra["file"] == "BI_trade_2026-09_EN"
        assert "Taxed import" in wld.extra["kg_note"]
        deu = _one(s, UA, partner_iso3="DEU", period_label="2026-09")
        assert (deu.value, deu.net_weight_kg) == (5_835_420.0, 1_740_856.3)
        pol = _one(s, UA, partner_iso3="POL", period_label="2026-09")
        assert pol.net_weight_kg == 912_684.2 and "minus the taxed import" in pol.extra["kg_basis"]
        assert _one(s, UA, partner_iso3="WLD", period_label="2026-10").net_weight_kg == 5_032_397.61
        assert _one(s, UA, partner_iso3="WLD", period_label="2026-08").value == 10_937_390.0
        # Unit values only from at least 1 t; none for the world total.
        uv = _rows(s, UA, P, market_iso3="DEU", period_label="2026-09")
        assert len(uv) == 1 and uv[0].price_type == PriceType.EXPORT_UNIT_VALUE.value
        assert uv[0].price_value == round(5_835_420.0 / 1_740_856.3, 4) and uv[0].origin_iso3 == "UKR"
        assert not _rows(s, UA, P, market_iso3="SGP")         # 7 kg to Singapore: trade row only
        assert _one(s, UA, partner_iso3="SGP", period_label="2026-09").net_weight_kg == 6.7
        assert not _rows(s, UA, P, market_iso3="WLD")
        # Only the honey rows are archived, never the 10 MB file.
        src = s.scalars(select(Source).where(Source.key == UA)).one()
        docs = s.scalars(select(RawDocument).where(RawDocument.source_id == src.id)).all()
        assert max(d.size_bytes for d in docs) < 120_000

    # Nothing changed: one request.
    assert run_ua()["new"] == 0 and len(run_ua.sent) == 1


def test_ua_revision_withdrawal_and_bad_download(run_ua, session_factory):
    assert run_ua()["status"] == "success"
    files = {m: raw_gz(n) for m, n in UA_FILES.items()}

    def revise(h, rows):
        iv, ip = h.index("Export USD"), h.index("State")
        out = []
        for r in rows:
            if r[ip] == "LT Lithuania":
                continue                                       # no longer published
            if r[ip] == "DE Germany" and r[h.index("Customs")] == "Odesa Customs Office":
                r = r[:iv] + [str(float(r[iv]) + 1000)] + r[iv + 1:]
            out.append(r)
        return out

    files[(2026, 10)] = rewrite_ua(UA_FILES[(2026, 10)], revise)
    res = run_ua(files=files)
    assert res["status"] == "partial" and res["revised"] >= 3, res   # DEU, WLD revised; LTU withdrawn
    assert len(run_ua.sent) == 2                              # only the changed file is downloaded
    with session_factory() as s:
        assert _one(s, UA, partner_iso3="DEU", period_label="2026-10").value == 4_954_840.0
        assert not _rows(s, UA, T, partner_iso3="LTU", period_label="2026-10")
        assert _rows(s, UA, T, current=False, partner_iso3="LTU", period_label="2026-10")
        assert not _rows(s, UA, P, market_iso3="LTU", period_label="2026-10")
        assert _one(s, UA, partner_iso3="WLD", period_label="2026-10").value == 16_091_760.0 + 1000 - 540_490.0

    # A download shorter than the size listed stores nothing; the month is asked again next time.
    listed = dict(files)
    listed[(2026, 9)] = rewrite_ua(UA_FILES[(2026, 9)],
                                   lambda h, rows: [r for r in rows if r[h.index("State")] != "MH Marshall Islands"])
    short = listed[(2026, 9)][:-200]
    res = run_ua(files=listed, served={(2026, 9): short})
    assert res["status"] == "partial" and any("bytes downloaded" in w for w in res["warnings"]) and res["new"] == 0
    with session_factory() as s:
        state = s.get(AppSetting, f"collector_state:{UA}").value
        assert state["months"]["2026-09"]["sig"].endswith(hashlib.md5(files[(2026, 9)]).hexdigest())
        assert _one(s, UA, partner_iso3="WLD", period_label="2026-09").value == 24_471_650.0
    assert run_ua(files=listed, served={(2026, 9): short})["status"] == "partial"
    assert len(run_ua.sent) == 2                              # asked again: package + the 2026-09 file

    # Seen live on the 2023 files: the MD5 listed does not match a complete file of the listed size. The
    # file is read (its gzip checksum is verified on decompression) with a one-time warning.
    pkg = ua_package(listed)
    for r in pkg["result"]["resources"]:
        if r["name"] == "BI_trade_2026-09_EN":
            r["file_hash_sum"] = "e43f2685ddb7ea1a93ab75cf5add3346"
    res = run_ua(files=listed, package=pkg)
    assert res["status"] == "partial" and any("does not match the file" in w for w in res["warnings"])
    with session_factory() as s:
        assert _one(s, UA, partner_iso3="WLD", period_label="2026-09").value == 24_471_640.0   # 10 USD row gone
    with pytest.raises(CollectorError, match="not a gzip"):
        to.parse_ua_month(listed[(2026, 9)][:-200], (2026, 9))


# ---------------------------------------------------------------------------------------------
# Mexico: pure functions on the real pages
# ---------------------------------------------------------------------------------------------


def test_parse_real_start_page():
    cube = to.parse_inegi_start(MX_START)
    assert (cube.server, cube.database, cube.cube) == ("W-OLAPCLPRO25", "COMEX_BCMM_MENSUAL", "COMEX_BCMM_MENSUAL_2023")
    assert cube.first == (2023, 1) and cube.last == (2026, 8) and cube.adjusted_until == (2025, 12)
    assert to.mx_data_status((2025, 12), cube) == DataStatus.PUBLISHED
    assert to.mx_data_status((2026, 1), cube) == DataStatus.PROVISIONAL
    with pytest.raises(CollectorError):
        to.parse_inegi_start(b"<html><body>Mantenimiento</body></html>")


def test_parse_real_result_page():
    cube = to.parse_inegi_start(MX_START)
    p = to.parse_inegi_page(mx_page(2025, 1), cube, 2025)
    assert p.total_rows == 137 and p.per_page == 33 and len(p.rows) == 33 and p.problems == []
    first = p.rows[0]
    assert (first.month, first.partner, first.value, first.qty) == ((2025, 1), "Total", 2_607_288.0, 844_875.0)
    usa = next(r for r in p.rows if r.month == (2025, 1) and r.partner == "Estados Unidos")
    assert (usa.value, usa.qty) == (1_494_682.0, 461_140.0)
    feb_usa = next(r for r in p.rows if r.month == (2025, 2) and r.partner == "Estados Unidos")
    assert feb_usa.confidential and feb_usa.value is None and feb_usa.qty is None
    # The answer must echo the query sent: a 2025 page is not a 2024 answer.
    with pytest.raises(CollectorError, match="another query"):
        to.parse_inegi_page(mx_page(2025, 1), cube, 2024)
    other = mx_page(2025, 1).replace(b"04.09.0001 (Kg) Miel natural.", b"04.09.0099 (Kg) Las dem\xe1s.")
    with pytest.raises(CollectorError, match="another product"):
        to.parse_inegi_page(other, cube, 2025)
    with pytest.raises(CollectorError, match="no query echo"):
        to.parse_inegi_page(b"<html>error:Object reference not set</html>", cube, 2025)


@pytest.mark.parametrize("name,expected", [
    ("Estados Unidos", ("USA", "name")), ("Alemania", ("DEU", "name")), ("Reino Unido", ("GBR", "name")),
    ("Arabia Saudita", ("SAU", "name")), ("Japón", ("JPN", "name")), ("Suiza", ("CHE", "name")),
    ("Países Bajos", ("NLD", "name")), ("Corea del Sur", ("KOR", "name")), ("Europa", (None, "aggregate")),
    ("Países no identificados", (None, "aggregate")), ("Narnia", (None, "unknown")),
])
def test_map_inegi_partner(name, expected):
    assert to.map_inegi_partner(name) == expected


# ---------------------------------------------------------------------------------------------
# Mexico: end to end
# ---------------------------------------------------------------------------------------------


def test_mx_end_to_end(run_mx, session_factory):
    res = run_mx()
    assert res["status"] == "success" and res["warnings"] == [], res
    assert len(run_mx.sent) == 18                             # start page + 17 result pages (2023-2026)
    with session_factory() as s:
        totals = _rows(s, MX, T, partner_iso3="WLD")
        assert len(totals) == 44
        y25 = [t for t in totals if t.period_label.startswith("2025")]
        assert round(sum(t.value for t in y25)) == 79_616_835 and round(sum(t.net_weight_kg for t in y25)) == 25_906_658
        assert {t.data_status for t in y25} == {"published"}
        assert {t.data_status for t in totals if t.period_label.startswith("2026")} == {"provisional"}
        # The visible destinations add up to UN Comtrade's Mexico 2025 (65.92 M USD, 21,234 t): Comtrade
        # leaves out INEGI's confidential cells.
        dest25 = [t for t in _rows(s, MX, T) if t.partner_iso3 != "WLD" and t.period_label.startswith("2025")]
        assert round(sum(t.value for t in dest25)) == 65_916_141 and round(sum(t.net_weight_kg for t in dest25)) == 21_234_014
        feb = _one(s, MX, partner_iso3="WLD", period_label="2025-02")
        assert {d["iso3"] for d in feb.extra["confidential_destinations"]} == {"ESP", "USA"}
        assert feb.extra["confidential_part"] == {"usd": 1_108_388.0, "kg": 398_049.0}
        assert not _rows(s, MX, T, partner_iso3="USA", period_label="2025-02")   # "C" is never a zero
        jan = _one(s, MX, partner_iso3="USA", period_label="2025-01")
        assert (jan.value, jan.net_weight_kg, jan.currency, jan.data_status) == (1_494_682.0, 461_140.0, "USD", "published")
        uv = _rows(s, MX, P, market_iso3="USA", period_label="2025-01")
        assert len(uv) == 1 and uv[0].price_value == round(1_494_682.0 / 461_140.0, 4) and uv[0].origin_iso3 == "MEX"
        assert len(_rows(s, MX, P)) == 140 and not _rows(s, MX, P, market_iso3="WLD")

    # Same cube: one request.
    assert run_mx()["new"] == 0 and run_mx.sent == [("start", 0, 0)]


def test_mx_new_month_rereads_only_the_revised_year(run_mx, session_factory):
    assert run_mx()["status"] == "success"
    newer = MX_START.replace(b"agosto 2026", b"septiembre 2026")
    res = run_mx(start=newer)
    assert res["status"] == "no_change"                       # same 2026 figures in the fixture pages
    assert {y for kind, y, _ in run_mx.sent if kind == "query"} == {2026}
    # The adjusted range moves (annual revision): every year is read again.
    adjusted = newer.replace(b"Cifras ajustadas de enero 2023 a diciembre 2025, a partir de enero 2026",
                             b"Cifras ajustadas de enero 2023 a diciembre 2026, a partir de enero 2027")
    assert run_mx(start=adjusted)["status"] == "success"
    assert {y for kind, y, _ in run_mx.sent if kind == "query"} == {2023, 2024, 2025, 2026}
    with session_factory() as s:
        assert _one(s, MX, partner_iso3="WLD", period_label="2026-08").data_status == "published"


def test_mx_short_answer_is_asked_again(run_mx, session_factory):
    res = run_mx(pages={(2026, 3): mx_page(2026, 2)})        # page 3 answered with page 2's rows
    assert res["status"] == "partial" and any("announced" in w for w in res["warnings"])
    with session_factory() as s:
        assert not [t for t in _rows(s, MX, T) if t.period_label.startswith("2026")]
        assert len(_rows(s, MX, T, partner_iso3="WLD")) == 36
        assert "2026" not in s.get(AppSetting, f"collector_state:{MX}").value["years"]


def test_api_prefers_inegi_over_comtrade_for_a_complete_year(run_mx, db, api):
    """MEX's own official statistics come first for a complete year (Ctx.is_national: country MEX,
    official); UN Comtrade's annual figure, which leaves out INEGI's confidential cells, stays listed."""
    assert run_mx()["status"] == "success"
    comtrade = Source(key="un_comtrade_t", name="Comtrade", publisher="UN", homepage="https://example.org",
                      kind="api", reliability="official", category="trade", expected_max_age_days=400)
    db.add(comtrade)
    db.flush()
    db.add(T(source_id=comtrade.id, series_key="ct|MEX|WLD|2025", reporter_iso3="MEX", partner_iso3="WLD",
             flow="export", currency="USD", value=65_916_141.0, usd_value=65_916_141.0, net_weight_kg=21_234_006.0,
             period_start=date(2025, 1, 1), period_end=date(2025, 12, 31), period_label="2025", frequency="A",
             data_status="published", reliability="official", value_hash="x"))
    db.commit()
    r = api.get("/api/trade/flows", params={"reporter": "MEX", "flow": "export", "year": 2025}).json()
    assert r["source_key"] == MX and r["total"]["net_weight_kg"] == 25_906_658.0 and r["complete"] is True
    assert {a["source"]["key"] for a in r["alternatives"]} == {MX, "un_comtrade_t"}
    profile = api.get("/api/countries/MEX").json()
    assert profile["trade"]["export"]["latest"]["source"]["key"] == MX


def test_ua_unmapped_partner_stays_in_the_total_and_withdraws_nothing(run_ua, session_factory):
    assert run_ua()["status"] == "success"
    files = {m: raw_gz(n) for m, n in UA_FILES.items()}
    files[(2026, 8)] = rewrite_ua(UA_FILES[(2026, 8)], lambda h, rows: [
        r[:h.index("State")] + ["ES Germany"] + r[h.index("State") + 1:] if r[h.index("State")] == "ES Spain" else r
        for r in rows])
    res = run_ua(files=files)
    assert res["status"] == "partial" and any("ES Germany" in w for w in res["warnings"])
    with session_factory() as s:
        wld = _one(s, UA, partner_iso3="WLD", period_label="2026-08")
        assert wld.value == 10_937_390.0                       # unchanged: the rows stay in the total
        assert _one(s, UA, partner_iso3="ESP", period_label="2026-08").value == 1_277_000.0   # not withdrawn
