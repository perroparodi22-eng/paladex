"""Tests for collectors/production_europe.py: Spain MAPA (es_mapa_honey), Hungary KSH (hu_ksh_honey),
Bulgaria MZH Agrostatistics (bg_mzh_honey) and Greece ELSTAT (gr_elstat_honey).

Every `real_*` fixture in tests/fixtures/production_europe/ is a capture of the live source (5-6 Nov
2026, see the README there): unmodified, gzip-compressed, or (Bulgarian PDFs) their word layer.
Variants (a revision, drift) are built in the tests from those captures and say what they change.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
import ssl
from datetime import date, timedelta
from pathlib import Path

import httpx
import openpyxl
import pytest
import respx
from sqlalchemy import func, select

from paladex.collectors import production_europe as pe
from paladex.collectors.base import CollectorError, year_bounds
from paladex.models import AppSetting, CollectionRun, ProductionStat, RawDocument, Source, utcnow
from paladex.services import ingest

FIX = Path(__file__).parent / "fixtures" / "production_europe"
P = ProductionStat
KEYS = ("es_mapa_honey", "hu_ksh_honey", "bg_mzh_honey", "gr_elstat_honey")

ES_2025_URL = ("https://www.mapa.gob.es/es/dam/jcr:16c4ff63-7e45-4bb7-a8e2-8772fe041560/"
               "mielycera-25-web.2026-08-24-13-38-18.xlsx")
ES_2024_URL = ("https://www.mapa.gob.es/dam/mapa/contenido/estadisticas/temas/estadisticas-agrarias/3.ganaderia/"
               "estadistica-de-lana--miel-y-huevos/2024/mielycera-24-web.xlsx")
ES_LM_2025 = "Mon, 24 Aug 2026 11:38:18 GMT"
ES_LM_2024 = "Wed, 02 Jul 2025 11:33:55 GMT"
BG_PDF_URL = "https://www.mzh.government.bg/media/filer_public/2026/02/27/ra466_beeshoney2025-26022026.pdf"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;charset=UTF-8"
HTML = "text/html; charset=UTF-8"


def F(name: str) -> bytes:
    data = (FIX / name).read_bytes()
    return gzip.decompress(data) if name.endswith(".gz") else data


# ---------------------------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------------------------


def _static(spec):
    """bytes | (status, bytes[, content type[, extra headers]]) | callable(request)."""
    if callable(spec):
        return spec
    if isinstance(spec, bytes):
        spec = (200, spec)
    status, body, *rest = spec
    headers = {"content-type": rest[0] if rest else HTML}
    if len(rest) > 1:
        headers.update(rest[1])
    return lambda request: httpx.Response(status, content=body, headers=headers)


@pytest.fixture()
def run(db, monkeypatch):
    """Run a collector offline. `routes` maps an exact URL (a GET) to a response spec (see `_static`).
    Every request of the last run is in `run.sent`; any other URL fails as 'offline'."""
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
            for url, spec in routes.items():
                mock.route(method="GET", url=url).mock(side_effect=recorded(_static(spec)))

            def unrouted(request):
                sent.append(request)
                raise httpx.ConnectError("blocked in tests")
            mock.route().mock(side_effect=unrouted)
            with httpx.Client(follow_redirects=True) as client:
                return run_collector(key, trigger="test", force=force, client=client)

    _run.sent = []
    return _run


def urls(r) -> list[str]:
    return [str(x.url) for x in r.sent]


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


def _age_state(session_factory, key: str, days: int) -> None:
    with session_factory() as s:
        row = s.get(AppSetting, f"collector_state:{key}")
        row.value = {**row.value, "pulled_at": (utcnow() - timedelta(days=days)).isoformat(timespec="seconds")}
        s.commit()


def values_only(content: bytes, edit=None) -> bytes:
    """A copy of an .xlsx with every formula replaced by its cached value (openpyxl would otherwise save
    formulas without values), optionally edited by `edit(workbook)`."""
    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    if edit:
        edit(wb)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def find_cell(ws, text: str):
    return next(c for row in ws.iter_rows() for c in row if isinstance(c.value, str) and c.value.strip() == text)


# ---------------------------------------------------------------------------------------------
# Registration and metadata
# ---------------------------------------------------------------------------------------------


def test_registered_with_official_metadata():
    from paladex.collectors.registry import IMPORT_ERRORS, all_collectors, get_collector

    all_collectors(refresh=True)
    assert "paladex.collectors.production_europe" not in IMPORT_ERRORS
    for key, iso3 in zip(KEYS, ("ESP", "HUN", "BGR", "GRC"), strict=True):
        c = get_collector(key)
        assert c is not None, key
        assert c.reliability == "official" and c.category == "production" and c.country_iso3 == iso3
        assert c.requires_key is None and c.default_enabled is True
        assert c.name and c.name_en and c.publisher and c.terms_note and c.expected_max_age_days
        assert 0 < len(c.expected_update) < 120 and 0 < len(c.expected_update_en) < 120
        assert c.schedule["trigger"] == "cron" and "day" in c.schedule      # monthly, never a tight interval
        # a page a person can open, not a file or an API
        assert c.homepage.startswith("https://") and not re.search(r"\.(xlsx?|pdf|json)$|/api/", c.homepage)
    assert "Ley 37/2007" in get_collector("es_mapa_honey").terms_note


# ---------------------------------------------------------------------------------------------
# Spain, MAPA: TLS chain of www.mapa.gob.es
# ---------------------------------------------------------------------------------------------


def _pem_blocks(text: str) -> list[str]:
    return re.findall(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----\n?", text, flags=re.S)


def test_embedded_fnmt_cross_certificate_is_the_one_mapa_serves():
    served = _pem_blocks(F("real_mapa_tls_chain_as_served.pem").decode())
    assert len(served) == 5
    embedded = pe.FNMT_G2R_CROSS_PEM
    der = ssl.PEM_cert_to_DER_cert(embedded)
    assert der == ssl.PEM_cert_to_DER_cert(served[4])          # the cross-signed copy, sent last
    assert der != ssl.PEM_cert_to_DER_cert(served[2])          # not the self-signed copy that breaks OpenSSL
    assert hashlib.sha256(der).hexdigest().upper() == (
        "327EC93955C9145261B087C6FC5EAC8A71262BF2568E8D36F7C2FEDBD1B1077A")


def test_mapa_context_trusts_the_cross_certificate_with_full_verification(monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    ctx = pe.mapa_ssl_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    # partial chains off: the cross-certificate must itself verify up to "AC RAIZ FNMT-RCM"
    assert not ctx.verify_flags & getattr(ssl, "VERIFY_X509_PARTIAL_CHAIN", 0)

    def name(cert, part):
        return {k: v for rdn in cert[part] for k, v in rdn}

    certs = ctx.get_ca_certs()
    cross = [c for c in certs if name(c, "subject").get("commonName") == "AC RAIZ FNMT-RCM SERVIDORES SEGUROS G2R"]
    assert len(cross) == 1 and name(cross[0], "issuer") == {
        "countryName": "ES", "organizationName": "FNMT-RCM", "organizationalUnitName": "AC RAIZ FNMT-RCM"}
    # the issuing root is in the standard store, self-signed
    assert any(name(c, "subject") == name(cross[0], "issuer") == name(c, "issuer") for c in certs)
    assert len(certs) > 100                                     # the whole standard store, not just this cert


# ---------------------------------------------------------------------------------------------
# Spain, MAPA: parsers on the real files
# ---------------------------------------------------------------------------------------------


def test_real_page_lists_one_workbook_per_year():
    files = pe.find_es_files(F("real_mapa_estadistica_miel_y_cera.html").decode("utf-8"))
    assert list(files) == list(range(2013, 2026))
    assert files[2025] == ES_2025_URL and files[2024] == ES_2024_URL
    assert files[2014].endswith("/2014/mielycera.xls")         # year read from the folder
    assert files[2015].endswith("/2015/mielycera-15.xls")
    page = '<a href="/x/mielycera-25-web.xlsx">a</a><a href="/y/mielycera-25-web.xlsx">b</a>'
    with pytest.raises(CollectorError, match="two different"):
        pe.find_es_files(page)
    assert pe.find_es_files('<a href="/x/mielycera.xls">no year</a>') == {}


def test_real_2025_workbook():
    wb = pe.parse_es_workbook(F("real_mapa_mielycera-25-web.xlsx"), expected_year=2025)
    p, h = wb.production, wb.hives
    assert wb.year == 2025 and p.sheet == "Miel y cera 25" and h.sheet == "Colmenas 25"
    assert p.title == "MIEL Y CERA: Análisis provincial de producción (toneladas), 2025"
    assert p.national.label == "ESPAÑA" and round(p.national.honey[2], 6) == 29349.593722
    assert round(p.national.wax[2], 3) == 2060.437
    assert h.national.honey == (2164661.0, 587116.0, 2751777.0) and h.national.wax[2] == 2728744.0
    assert p.split == ("Explotaciones apícolas Trashumante", "Explotaciones apícolas Estantes")
    assert set(p.regions) == {code for code, _ in pe.ES_REGIONS.values()} and len(p.regions) == 17
    cl = p.regions["ES-CL"]                                     # "Castilla y León (16,8%)" of MAPA's report
    assert round(cl.honey[2], 1) == 4923.5 and p.region_labels["ES-CL"] == "CASTILLA Y LEÓN"
    assert [x.label for x in p.provinces["ES-CL"]] == ["Avila", "Burgos", "León", "Palencia", "Salamanca", "Segovia",
                                                      "Soria", "Valladolid", "Zamora"]
    assert p.provinces["ES-MD"] == []                           # single-province communities
    assert pe.check_es_workbook(wb) == []                       # the communities add up to ESPAÑA
    assert p.footnotes == [] and h.footnotes == []


def test_real_2024_and_2015_workbooks():
    wb24 = pe.parse_es_workbook(F("real_mapa_mielycera-24-web.xlsx"))
    assert wb24.year == 2024 and round(wb24.production.national.honey[2], 3) == 33180.633   # MAPA's report: 33.181 t
    assert wb24.hives.national.honey[2] == 2822924.0
    wb15 = pe.parse_es_workbook(F("real_mapa_mielycera-15.xls"), expected_year=2015)        # the .xls format
    assert round(wb15.production.national.honey[2], 3) == 33440.771
    assert wb15.production.split == ("Colmenas movilistas", "Colmenas fijistas")         # before the 2019 break
    assert pe.check_es_workbook(wb15) == []


def test_es_workbook_drift_fails_loudly():
    real = F("real_mapa_mielycera-25-web.xlsx")
    with pytest.raises(CollectorError, match="the link for 2024"):
        pe.parse_es_workbook(real, expected_year=2024)
    with pytest.raises(CollectorError, match="not an Excel workbook"):
        pe.parse_es_workbook(b"<!DOCTYPE html><title>Mantenimiento</title>")

    def rename(old, new, sheet="Miel y cera 25"):
        def edit(wb):
            find_cell(wb[sheet], old).value = new
        return edit

    with pytest.raises(CollectorError, match="no ESPAÑA row"):
        pe.parse_es_workbook(values_only(real, rename("ESPAÑA", "TOTAL NACIONAL")))
    with pytest.raises(CollectorError, match=r"16 autonomous communities \(missing \['Comunidad de Madrid'\]\)"):
        pe.parse_es_workbook(values_only(real, rename("MADRID", None)))         # a single-province community dropped
    with pytest.raises(CollectorError, match="not followed by their autonomous community"):
        pe.parse_es_workbook(values_only(real, rename("CANARIAS", "ISLAS CANARIAS")))
    with pytest.raises(CollectorError, match="header"):
        pe.parse_es_workbook(values_only(real, rename("TOTAL", "SUMA")))       # the honey TOTAL column header
    with pytest.raises(CollectorError, match="non-numeric"):
        pe.parse_es_workbook(values_only(real, lambda wb: setattr(
            wb["Miel y cera 25"].cell(find_cell(wb["Miel y cera 25"], "ESPAÑA").row, 4), "value", "n.d.")))
    with pytest.raises(CollectorError, match="production and hives sheets"):
        pe.parse_es_workbook(values_only(real, lambda wb: wb.remove(wb["Colmenas 25"])))
    with pytest.raises(CollectorError, match="unexpected row"):
        pe.parse_es_workbook(values_only(real, lambda wb: setattr(
            wb["Miel y cera 25"].cell(find_cell(wb["Miel y cera 25"], "Lugo").row, 3), "value", "x")))


def test_check_es_workbook_reports_but_never_fixes():
    def edit(wb):
        ws = wb["Miel y cera 25"]
        ws.cell(find_cell(ws, "CASTILLA Y LEÓN").row, 4).value = 5000.0          # +76.5 t on one community
    wb = pe.parse_es_workbook(values_only(F("real_mapa_mielycera-25-web.xlsx"), edit))
    msgs = pe.check_es_workbook(wb)
    assert len(msgs) == 1 and "2025 production (honey)" in msgs[0] and "29,349.594" in msgs[0]
    assert round(wb.production.national.honey[2], 3) == 29349.594                     # the total is untouched


def test_release_date_is_the_last_modified_only_when_plausible():
    assert pe.es_published(date(2026, 8, 24), 2025) == date(2026, 8, 24)
    assert pe.es_published(date(2025, 7, 2), 2024) == date(2025, 7, 2)
    assert pe.es_published(date(2025, 6, 2), 2016) is None            # the 2025 website migration, not a release
    assert pe.es_published(None, 2025) is None


# ---------------------------------------------------------------------------------------------
# Spain, MAPA: end to end
# ---------------------------------------------------------------------------------------------


def es_routes(page: bytes | None = None, y25: bytes | None = None, y24: bytes | None = None,
              url25: str = ES_2025_URL) -> dict:
    return {pe.ES_PAGE_URL: (200, page if page is not None else F("real_mapa_estadistica_miel_y_cera.html"), HTML),
            url25: (200, y25 if y25 is not None else F("real_mapa_mielycera-25-web.xlsx"), XLSX,
                    {"last-modified": ES_LM_2025}),
            ES_2024_URL: (200, y24 if y24 is not None else F("real_mapa_mielycera-24-web.xlsx"), XLSX,
                          {"last-modified": ES_LM_2024})}


@pytest.fixture()
def es_two_years(monkeypatch):
    """Keep 2024-2025 only (the real page lists 2013-2025; two real workbooks are kept as fixtures)."""
    monkeypatch.setattr(pe, "ES_FIRST_YEAR", 2024)


def test_es_end_to_end_on_the_real_files(run, session_factory, es_two_years, monkeypatch):
    contexts = []
    real_context = pe.mapa_ssl_context
    monkeypatch.setattr(pe, "mapa_ssl_context", lambda: contexts.append(1) or real_context())
    res = run("es_mapa_honey", es_routes())
    assert res["status"] == "success", res
    assert urls(run) == [pe.ES_PAGE_URL, ES_2024_URL, ES_2025_URL]
    assert contexts == [1]                                # MAPA requests go through the FNMT-aware client
    assert res["new"] == 72 and res["warnings"] == []     # (2 national + 2 x 17 communities) x 2 years

    with session_factory() as s:
        _no_duplicate_current(s)
        rows = _rows(s, "es_mapa_honey")
        assert len(rows) == 72
        assert all(r.country_iso3 == "ESP" and r.frequency == "A" and r.reliability == "official"
                   and r.data_status == "published" and r.raw_document_id for r in rows)
        by = {}
        for r in rows:
            by.setdefault((r.metric, r.period_label), []).append(r)
        assert {k: len(v) for k, v in by.items()} == {
            (m, y): (17 if m.endswith("_by_region") else 1)
            for m in ("production", "colonies", "production_by_region", "colonies_by_region") for y in ("2024", "2025")}
        n25 = by[("production", "2025")][0]
        assert (n25.value, n25.unit) == (29349.594, "t")
        assert (n25.period_start, n25.period_end) == year_bounds(2025)
        assert n25.published_at == date(2026, 8, 24) and n25.source_url == ES_2025_URL
        assert n25.series_key == "mapa_mielycera|ESP|production|2025"
        x = n25.extra
        assert round(x["value_as_published"], 6) == 29349.593722 and x["unit_as_published"] == "toneladas"
        assert x["wax_t"] == 2060.437 and x["hives"] == 2751777.0 and x["file_last_modified"] == "2026-08-24"
        assert x["split"] == {"Explotaciones apícolas Trashumante": 22352.037, "Explotaciones apícolas Estantes": 6997.557}
        assert "region" not in x and "29,349.594 t" in n25.notes
        n24 = by[("production", "2024")][0]
        assert n24.value == 33180.633 and n24.published_at == date(2025, 7, 2) and n24.source_url == ES_2024_URL
        c25 = by[("colonies", "2025")][0]
        assert (c25.value, c25.unit) == (2751777.0, "number") and c25.extra["hives_for_wax"] == 2728744.0
        cl = next(r for r in by[("production_by_region", "2025")] if r.extra["region_code"] == "ES-CL")
        assert cl.value == 4923.512 and cl.extra["region"] == "Castilla y León" and cl.unit == "t"
        assert cl.extra["provinces"]["Salamanca"] == 1882.592 and cl.series_key == "mapa_mielycera|ES-CL|production_by_region|2025"
        assert all("region" in r.extra for k, v in by.items() if k[0].endswith("_by_region") for r in v)
        raw = s.get(RawDocument, n25.raw_document_id)
        assert raw.url == ES_2025_URL and raw.title.startswith("MAPA – Estadística de Miel y Cera 2025")
        st = _state(s, "es_mapa_honey")
        assert st["files"] == {"2024": ES_2024_URL, "2025": ES_2025_URL} and st["latest_year"] == 2025
        src = s.scalars(select(Source).where(Source.key == "es_mapa_honey")).one()
        assert src.latest_period_label == "2025"


def test_es_second_run_reads_only_the_page(run, session_factory, es_two_years):
    assert run("es_mapa_honey", es_routes())["status"] == "success"
    res = run("es_mapa_honey", es_routes())
    assert res["status"] == "no_change" and res["new"] == 0
    assert urls(run) == [pe.ES_PAGE_URL]
    # forced: every workbook is read again, nothing changes
    res = run("es_mapa_honey", es_routes(), force=True)
    assert res["status"] == "no_change" and res["revised"] == 0
    assert urls(run) == [pe.ES_PAGE_URL, ES_2024_URL, ES_2025_URL]
    # after the refresh interval: re-downloaded, identical bytes are not parsed again
    _age_state(session_factory, "es_mapa_honey", pe.ES_FULL_REFRESH_DAYS + 1)
    res = run("es_mapa_honey", es_routes())
    assert res["status"] == "no_change" and res["seen"] == 0
    assert urls(run) == [pe.ES_PAGE_URL, ES_2024_URL, ES_2025_URL]
    with session_factory() as s:
        assert len(_rows(s, "es_mapa_honey", current=None)) == 72


def test_es_corrected_workbook_under_a_new_link_is_a_revision(run, session_factory, es_two_years):
    assert run("es_mapa_honey", es_routes())["status"] == "success"
    new_url = ES_2025_URL.replace("2026-08-24-13-38-18", "2026-11-20-09-00-00")
    page = F("real_mapa_estadistica_miel_y_cera.html").replace(
        ES_2025_URL.split("mapa.gob.es")[1].encode(), new_url.split("mapa.gob.es")[1].encode())

    def edit(wb):                                         # MAPA corrects Castilla y León and the national total
        ws = wb["Miel y cera 25"]
        for label, value in (("CASTILLA Y LEÓN", 4933.51218), ("ESPAÑA", 29359.593722272726)):
            ws.cell(find_cell(ws, label).row, 4).value = value
    res = run("es_mapa_honey", es_routes(page=page, url25=new_url,
                                         y25=values_only(F("real_mapa_mielycera-25-web.xlsx"), edit)))
    assert res["status"] == "success", res
    assert urls(run) == [pe.ES_PAGE_URL, new_url]          # only the changed link is downloaded
    assert res["revised"] == 2 and res["new"] == 0
    with session_factory() as s:
        _no_duplicate_current(s)
        hist = _rows(s, "es_mapa_honey", current=None, metric="production", period_label="2025")
        assert [(h.value, h.revision, h.is_current) for h in hist] == [(29349.594, 1, False), (29359.594, 2, True)]
        assert hist[1].source_url == new_url and hist[1].supersedes_id == hist[0].id
        assert _state(s, "es_mapa_honey")["files"]["2025"] == new_url


def test_es_old_file_without_a_plausible_release_date(run, session_factory, es_two_years):
    routes = es_routes()
    routes[ES_2024_URL] = (200, F("real_mapa_mielycera-24-web.xlsx"), XLSX, {"last-modified": "Mon, 02 Jun 2025 16:27:25 GMT"})
    routes[ES_2025_URL] = (200, F("real_mapa_mielycera-25-web.xlsx"), XLSX)            # no Last-Modified at all
    assert run("es_mapa_honey", routes)["status"] == "success"
    with session_factory() as s:
        rows = _rows(s, "es_mapa_honey", metric="production")
        assert [r.published_at for r in rows] == [date(2025, 6, 2), None]   # 2025-06-02 is plausible for 2024
        assert rows[1].extra["file_last_modified"] is None and rows[1].extra["release_date_note"]


def test_es_failures_store_nothing(run, session_factory, es_two_years):
    res = run("es_mapa_honey", {pe.ES_PAGE_URL: (200, b"<html><body>Mantenimiento</body></html>", HTML)})
    assert res["status"] == "failed" and "no 'Miel y cera' workbook" in res["error"]
    routes = es_routes()
    routes[ES_2025_URL] = (404, b"Not Found", "text/plain")
    res = run("es_mapa_honey", routes)
    assert res["status"] == "failed" and "HTTP 404" in res["error"]
    with session_factory() as s:
        # 2024 was checkpointed before 2025 failed; nothing of 2025 is stored
        assert {r.period_label for r in _rows(s, "es_mapa_honey", current=None)} == {"2024"}
    res = run("es_mapa_honey", {})
    assert res["status"] == "offline"


def _faostat_rows(db, iso3: str, values: dict[int, float]) -> None:
    fao = db.scalars(select(Source).where(Source.key == "faostat")).one()
    for year, value in values.items():
        start, end = year_bounds(year)
        ingest.record(db, ProductionStat, source_id=fao.id, series_key=f"faostat|QCL|{iso3}|production|{year}",
                      country_iso3=iso3, metric="production", value=value, unit="t", period_start=start,
                      period_end=end, period_label=str(year), frequency="A", flag_raw="A",
                      published_at=date(2025, 12, 31), source_url="https://bulks-faostat.fao.org/production/",
                      data_status="published", reliability="official")
    db.commit()


def test_faostat_and_mapa_are_side_by_side_in_the_production_views(run, api, db, es_two_years):
    assert run("es_mapa_honey", es_routes())["status"] == "success"
    _faostat_rows(db, "ESP", {2023: 27423.0, 2024: 33181.0})          # the live FAOSTAT figures
    table = api.get("/api/harvest/production", params={"scope": "all"}).json()
    esp = next(c for c in table["countries"] if c["iso3"] == "ESP")
    series = {s["source"]["key"]: s for s in esp["series"]}
    assert set(series) == {"faostat", "es_mapa_honey"}
    assert series["es_mapa_honey"]["latest"]["year"] == 2025 and series["es_mapa_honey"]["latest"]["value"] == 29349.594
    assert series["faostat"]["latest"]["year"] == 2024 and series["faostat"]["latest"]["value"] == 33181.0
    assert series["es_mapa_honey"]["years"] == 2                       # the 17 communities are not national points
    profile = api.get("/api/countries/ESP").json()
    metrics = {m["metric"]: m for m in profile["production"]["metrics"]}
    assert {s["source"]["key"] for s in metrics["production"]["series"]} == {"faostat", "es_mapa_honey"}
    assert not any(m.endswith("_by_region") for m in metrics)


# ---------------------------------------------------------------------------------------------
# Hungary, KSH STADAT 19.1.1.34
# ---------------------------------------------------------------------------------------------


def ksh_html() -> str:
    return F("real_ksh_stadat_mez0034_en.html").decode("utf-8")


def test_real_ksh_table():
    t = pe.parse_ksh_table(ksh_html())
    assert t.title == "19.1.1.34. Production of milk, eggs, wool, feather and honey"
    assert t.last_updated == date(2026, 10, 14)
    assert t.column == "Honey (production, tonne)"
    pts = {p.year: p for p in t.points}
    assert (pts[2025].raw, pts[2025].value, pts[2025].revised) == ("25,000", 25000.0, False)
    assert pts[2019].value == 18000.0 and pts[2022].value == 25000.0
    assert pts[1857].value is None and pts[1857].raw == ".."
    assert pts[1938].value == 6600.0 and min(pts) == 1857 and max(pts) == 2025


def test_ksh_drift_fails_loudly_and_revised_marker_is_read():
    html = ksh_html()
    with pytest.raises(CollectorError, match="no STADAT table"):
        pe.parse_ksh_table("<html><body>Karbantartás</body></html>")
    with pytest.raises(CollectorError, match="expected one 'Honey' column"):
        pe.parse_ksh_table(html.replace(">Honey</th>", ">Méz</th>"))
    with pytest.raises(CollectorError, match="not tonnes"):
        pe.parse_ksh_table(html.replace(">production, tonne</th>", ">production, kg</th>"))
    with pytest.raises(CollectorError, match="unreadable honey value"):
        pe.parse_ksh_table(re.sub(r'(<th style="text-align: center;">2025</th>(?:\s*<td[^>]*>[^<]*</td>){6}\s*<td[^>]*>)25,000',
                                  r"\g<1>approx. 25 000", html))
    revised = re.sub(r'(<th style="text-align: center;">2025</th>(?:\s*<td[^>]*>[^<]*</td>){6}\s*<td) style="text-align: right;">',
                     r'\1 style="text-align: right; color: green;">', html)
    pts = {p.year: p for p in pe.parse_ksh_table(revised).points}
    assert pts[2025].revised is True and pts[2024].revised is False


def test_ksh_end_to_end(run, session_factory):
    res = run("hu_ksh_honey", {pe.KSH_TABLE_URL: F("real_ksh_stadat_mez0034_en.html")})
    assert res["status"] == "success", res
    assert urls(run) == [pe.KSH_TABLE_URL] and res["new"] == 11
    with session_factory() as s:
        rows = _rows(s, "hu_ksh_honey")
        assert [r.period_label for r in rows] == [str(y) for y in range(2015, 2026)]
        r25 = rows[-1]
        assert (r25.country_iso3, r25.metric, r25.value, r25.unit) == ("HUN", "production", 25000.0, "t")
        assert r25.published_at == date(2026, 10, 14) and r25.source_url == pe.KSH_TABLE_URL and r25.raw_document_id
        assert r25.extra["value_as_published"] == "25,000" and r25.extra["revised_marker"] is False
        assert "rounded to the thousand tonnes" in r25.extra["rounding"]
        assert all(r.reliability == "official" and r.data_status == "published" for r in rows)
    res = run("hu_ksh_honey", {pe.KSH_TABLE_URL: F("real_ksh_stadat_mez0034_en.html")})
    assert res["status"] == "no_change" and urls(run) == [pe.KSH_TABLE_URL]
    # KSH revises 2025
    html = re.sub(r'(<th style="text-align: center;">2025</th>(?:\s*<td[^>]*>[^<]*</td>){6}\s*<td[^>]*>)25,000',
                  r"\g<1>26,000", ksh_html())
    res = run("hu_ksh_honey", {pe.KSH_TABLE_URL: html.encode()})
    assert res["status"] == "success" and (res["new"], res["revised"]) == (0, 1)
    with session_factory() as s:
        _no_duplicate_current(s)
        hist = _rows(s, "hu_ksh_honey", current=None, period_label="2025")
        assert [(h.value, h.is_current) for h in hist] == [(25000.0, False), (26000.0, True)]


# ---------------------------------------------------------------------------------------------
# Bulgaria, MZH Agrostatistics
# ---------------------------------------------------------------------------------------------


def bg_words(name: str = "real_mzh_ra466_beeshoney2025_words_p1-3.json.gz") -> list[list[dict]]:
    return json.loads(F(name))


BG_PDF_STAND_IN = b"%PDF-1.7 stand-in for the real MZH bulletin No 466 (see README)"


@pytest.fixture()
def bg_pdf(monkeypatch):
    """The collector reads the stand-in PDF as the real bulletin's word layer."""
    words = {"value": bg_words()}

    def fake(content: bytes, pages: int = 3):
        assert content == BG_PDF_STAND_IN
        return words["value"]
    monkeypatch.setattr(pe, "pdf_page_words", fake)
    return words


def bg_routes() -> dict:
    # page 2 first: respx's route for the query-less page-1 URL also matches "?page=N"
    return {pe.mzh_list_url(2): (200, F("real_mzh_danni_page2.html.gz"), HTML),
            pe.mzh_list_url(1): (200, F("real_mzh_danni_page1.html.gz"), HTML),
            BG_PDF_URL: (200, BG_PDF_STAND_IN, "application/pdf")}


def test_real_mzh_list_pages():
    assert pe.find_mzh_bulletins(F("real_mzh_danni_page1.html.gz").decode("utf-8")) == []   # other livestock data
    found = pe.find_mzh_bulletins(F("real_mzh_danni_page2.html.gz").decode("utf-8"))
    assert found == [pe.MzhBulletin(year=2025, url=BG_PDF_URL, published=date(2026, 2, 27),
                                    title="№ 466 – Февруари 2025- Пчеларството в България през 2025 година")]
    assert pe.mzh_list_url(2) == pe.MZH_LIST_URL + "?page=2"


def test_group_numbers_joins_thousands_only():
    words = [("България", 47.0, 86.8), ("8", 182.4, 187.0), ("416", 189.3, 202.9), ("808", 236.7, 250.3),
             ("851", 252.5, 266.0), ("96.1", 307.5, 322.0), ("9", 351.3, 355.8), ("649", 358.1, 371.7),
             ("-3.5%", 380.0, 400.0), ("695", 402.3, 415.9)]
    assert pe.group_numbers(words) == ["България", "8416", "808851", "96.1", "9649", "-3.5%", "695"]


def test_real_mzh_bulletin_2025():
    t = pe.parse_mzh_words(bg_words())
    assert t.year == 2025 and t.title == "Пчеларството в България през 2025 година"
    n = t.national
    assert (n.holdings, n.colonies, n.harvested, n.avg_colonies, n.honey_t, n.yield_kg) == (
        8416, 808851, 660713, 96.1, 9649, 14.6)
    assert {c: (r.honey_t, r.colonies) for c, r in t.regions.items()} == {
        "BG31": (1912, 123295), "BG32": (2449, 193087), "BG33": (2164, 186857), "BG34": (2024, 170162),
        "BG41": (306, 38756), "BG42": (794, 96694)}
    assert (t.previous_colonies, t.previous_harvested) == (838038, 695244)   # table 3: 1 Oct 2024
    assert t.wax_t == 46.7 and pe.check_mzh(t) == []


def test_real_mzh_bulletin_2024_with_a_garbled_derived_cell():
    t = pe.parse_mzh_words(bg_words("real_mzh_ra449_beeshoney2024_words_p1-3.json.gz"))
    assert t.year == 2024 and (t.national.honey_t, t.national.colonies) == (10440, 838038)
    se = t.regions["BG34"]
    assert se.avg_colonies is None and se.raw[3] == "101." and se.honey_t == 2154    # the counts are intact
    assert t.previous_colonies == 816673 and t.wax_t == 55.7
    assert pe.check_mzh(t) == ["2024: unreadable average/yield cell(s) in table 1 rows ['Югоизточен'] "
                               "(kept as published text)"]


def test_mzh_drift_fails_loudly():
    words = bg_words()
    no_caption = [[w for w in page if w["text"] != "производство"] for page in words]
    with pytest.raises(CollectorError, match="no table 1"):
        pe.parse_mzh_words(no_caption)
    no_region = [[w for w in page if w["text"] != "Североизточен"] for page in words]
    with pytest.raises(CollectorError, match="5 of the 6 regions"):
        pe.parse_mzh_words(no_region)
    no_title = [[w for w in page if w["text"] != "Пчеларството"] for page in words]
    with pytest.raises(CollectorError, match="no 'Пчеларството"):
        pe.parse_mzh_words(no_title)
    with pytest.raises(CollectorError, match="cannot be read"):
        pe.pdf_page_words(b"not a pdf at all")


def test_pdf_page_words_reads_a_word_layer():
    fpdf = pytest.importorskip("fpdf")
    doc = fpdf.FPDF()
    doc.add_page()
    doc.set_font("helvetica", size=11)
    doc.cell(text="Bulgaria 8 416 808 851")
    words = pe.pdf_page_words(bytes(doc.output()))
    assert [w["text"] for w in words[0]] == ["Bulgaria", "8", "416", "808", "851"]
    assert pe.word_lines(words) and set(words[0][0]) == {"text", "x0", "x1", "top", "bottom"}


def test_mzh_end_to_end(run, session_factory, bg_pdf):
    res = run("bg_mzh_honey", bg_routes())
    assert res["status"] == "success", res
    assert urls(run) == [pe.mzh_list_url(1), pe.mzh_list_url(2), BG_PDF_URL]
    assert res["new"] == 15                    # production + colonies 2025, colonies 2024, 6 regions x 2
    with session_factory() as s:
        _no_duplicate_current(s)
        rows = _rows(s, "bg_mzh_honey")
        assert all(r.country_iso3 == "BGR" and r.source_url == BG_PDF_URL and r.published_at == date(2026, 2, 27)
                   and r.reliability == "official" and r.data_status == "published" and r.raw_document_id for r in rows)
        nat = {(r.metric, r.period_label): r for r in rows if not r.metric.endswith("_by_region")}
        assert set(nat) == {("production", "2025"), ("colonies", "2025"), ("colonies", "2024")}
        p = nat[("production", "2025")]
        assert (p.value, p.unit) == (9649.0, "t") and p.extra["colonies_harvested"] == 660713
        assert p.extra["value_as_published"] == "9649" and p.extra["wax_t"] == 46.7 and "region" not in p.extra
        assert nat[("colonies", "2025")].value == 808851.0 and nat[("colonies", "2025")].extra["reference_date"] == "2025-10-01"
        assert nat[("colonies", "2024")].value == 838038.0 and nat[("colonies", "2024")].extra["table"] == "Таблица 3"
        reg = [r for r in rows if r.metric == "production_by_region"]
        assert len(reg) == 6 and sum(r.value for r in reg) == 9649.0          # consistent, never summed into the row
        ne = next(r for r in reg if r.extra["region_code"] == "BG33")
        assert ne.value == 2164.0 and ne.extra["region_as_published"] == "Североизточен"
        assert _state(s, "bg_mzh_honey")["url"] == BG_PDF_URL
    res = run("bg_mzh_honey", bg_routes())
    assert res["status"] == "no_change" and urls(run) == [pe.mzh_list_url(1), pe.mzh_list_url(2)]


def test_mzh_bulletin_for_another_year_is_refused(run, session_factory, bg_pdf):
    bg_pdf["value"] = bg_words("real_mzh_ra449_beeshoney2024_words_p1-3.json.gz")    # listed as 2025, about 2024
    res = run("bg_mzh_honey", bg_routes())
    assert res["status"] == "failed" and "is about 2024" in res["error"]
    with session_factory() as s:
        assert _rows(s, "bg_mzh_honey", current=None) == []


def test_mzh_no_bulletin_listed(run, session_factory):
    routes = {pe.mzh_list_url(i): (200, F("real_mzh_danni_page1.html.gz"), HTML) for i in range(pe.MZH_MAX_PAGES, 0, -1)}
    res = run("bg_mzh_honey", routes)
    assert res["status"] == "failed" and "no beekeeping bulletin" in res["error"]
    assert urls(run) == [pe.mzh_list_url(i) for i in range(1, pe.MZH_MAX_PAGES + 1)]


# ---------------------------------------------------------------------------------------------
# Greece, ELSTAT SPK33
# ---------------------------------------------------------------------------------------------


def gr_links() -> dict[str, tuple[str, str]]:
    return pe.find_elstat_tables(F("real_elstat_spk33.html.gz").decode("utf-8"))


def gr_routes() -> dict:
    links = gr_links()
    return {pe.ELSTAT_PAGE_URL: (200, F("real_elstat_spk33.html.gz"), HTML),
            links["7c"][0]: (200, F("real_elstat_spk33_2024_table7c.xlsx"), XLSX),
            links["04"][0]: (200, F("real_elstat_spk33_2024_table04.xlsx"), XLSX)}


def test_real_elstat_page_and_tables():
    links = gr_links()
    assert set(links) == {"7c", "04"}
    assert links["7c"][0].startswith("https://www.statistics.gr/en/statistics?")           # ":443" of the page dropped
    assert "documentID=595840" in links["7c"][0] and links["7c"][1].startswith("7c. Production of other primary")
    assert "documentID=595834" in links["04"][0] and "beehives" in links["04"][1]
    honey = pe.parse_elstat_honey(F("real_elstat_spk33_2024_table7c.xlsx"))
    assert honey.year == 2024 and honey.national.value == 25595.792 and honey.national.label_en == "Greece Total"
    assert len(honey.regions) == 13 and round(sum(r.value for r in honey.regions.values()), 3) == 25595.792
    assert honey.regions["EL43"].value == 5524.813 and honey.regions["EL43"].label_en == "Region of Crete"
    assert "honey" in honey.unit_note.lower() and "tons" in honey.unit_note
    hives = pe.parse_elstat_beehives(F("real_elstat_spk33_2024_table04.xlsx"))
    assert hives.year == 2024 and hives.reference_date == "2024-12-31"
    assert hives.national.parts == (3641.0, 2157445.0) and hives.national.value == 2161086.0
    assert hives.regions["EL61"].label_en == "Region of Thessally"      # ELSTAT's spelling, mapped to Thessaly


def test_elstat_drift_fails_loudly():
    real = F("real_elstat_spk33_2024_table7c.xlsx")
    with pytest.raises(CollectorError, match="no 'Honey' column"):
        pe.parse_elstat_honey(values_only(real, lambda wb: setattr(find_cell(wb.worksheets[0], "Honey"), "value", "Honey (t)")))
    with pytest.raises(CollectorError, match="12 of the 13 regions"):
        pe.parse_elstat_honey(values_only(real, lambda wb: setattr(find_cell(wb.worksheets[0], "Region of Crete"), "value",
                                                                   "Crete")))
    with pytest.raises(CollectorError, match="Table 7c"):
        pe.parse_elstat_honey(F("real_elstat_spk33_2024_table04.xlsx"))


def test_elstat_end_to_end(run, session_factory):
    links = gr_links()
    res = run("gr_elstat_honey", gr_routes())
    assert res["status"] == "success", res
    assert urls(run) == [pe.ELSTAT_PAGE_URL, links["7c"][0], links["04"][0]]
    assert res["new"] == 28
    with session_factory() as s:
        _no_duplicate_current(s)
        rows = _rows(s, "gr_elstat_honey")
        assert all(r.country_iso3 == "GRC" and r.period_label == "2024" and r.published_at is None
                   and r.reliability == "official" and r.raw_document_id for r in rows)
        nat = {r.metric: r for r in rows if not r.metric.endswith("_by_region")}
        assert (nat["production"].value, nat["production"].unit, nat["production"].source_url) == (25595.792, "t", links["7c"][0])
        assert (nat["colonies"].value, nat["colonies"].source_url) == (2161086.0, links["04"][0])
        assert nat["colonies"].extra["local_hives"] == 3641.0 and nat["colonies"].extra["reference_date"] == "2024-12-31"
        assert len([r for r in rows if r.metric == "production_by_region"]) == 13
        assert len([r for r in rows if r.metric == "colonies_by_region"]) == 13
    res = run("gr_elstat_honey", gr_routes())
    assert res["status"] == "no_change" and urls(run) == [pe.ELSTAT_PAGE_URL]


def test_elstat_table_4_of_another_year_is_not_stored(run, session_factory):
    routes = gr_routes()
    routes[gr_links()["04"][0]] = (200, values_only(F("real_elstat_spk33_2024_table04.xlsx"), lambda wb: setattr(
        find_cell(wb.worksheets[0], next(c.value for row in wb.worksheets[0].iter_rows(max_row=4) for c in row
                                         if isinstance(c.value, str) and c.value.startswith("Table 4."))),
        "value", "Table 4. Poultry, rabbits (all ages) and beehoves on 31st December 2023, by Region")), XLSX)
    res = run("gr_elstat_honey", routes)
    assert res["status"] == "partial" and "table 4 is for 2023" in " ".join(res["warnings"])
    with session_factory() as s:
        assert {r.metric for r in _rows(s, "gr_elstat_honey")} == {"production", "production_by_region"}


def test_unreachable_sources_are_offline(run, session_factory):
    for key in KEYS:
        assert run(key, {})["status"] == "offline", key
    with session_factory() as s:
        assert s.scalar(select(func.count(CollectionRun.id)).where(CollectionRun.status == "offline")) == len(KEYS)
