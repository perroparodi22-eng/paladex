"""Honey exporters and importers by company: collectors/companies_official.py (Uruguay XXI SIE "Por
Empresa", HMRC UK Trade Info traders), models_companies.py and api/companies.py.

Every fixture in tests/fixtures/companies/ is a REAL capture of 5 Nov 2026 (trimmed where its README
says so). Variants (a revision, a withdrawn company, a broken answer) are derived from the real files
here, never typed in.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select

from paladex.collectors import companies_official as co
from paladex.collectors.base import CollectorError
from paladex.collectors.trade_uruguay_chile import parse_sie_table
from paladex.models import RawDocument, Source
from paladex.models_companies import CompanyRecord, record_company

FIX = Path(__file__).parent / "fixtures" / "companies"
SIE_PAGE = (FIX / "real_sie_empresa_2026_page.html").read_bytes()
HMRC_IMP = (FIX / "real_hmrc_import_04090000_2026-07_08.json").read_bytes()
HMRC_EXP = (FIX / "real_hmrc_export_04090000_2026-07_08.json").read_bytes()
SIE_URL = "https://herramientas.uruguayxxi.gub.uy/sistema_de_estadistica/filtros.php"
C = CompanyRecord


@pytest.fixture(autouse=True)
def _pin_today(monkeypatch):
    monkeypatch.setattr(co, "today", lambda: date(2026, 11, 5))


def _current(db_session, **where):
    q = select(C).where(C.is_current.is_(True))
    for k, v in where.items():
        q = q.where(getattr(C, k) == v)
    return list(db_session.scalars(q))


@pytest.fixture()
def s(session_factory):
    with session_factory() as session:
        yield session


def _hmrc_routes(imp: bytes = HMRC_IMP, exp: bytes = HMRC_EXP) -> dict:
    return {r"^https://api\.uktradeinfo\.com/Import": (200, imp, "application/json"),
            r"^https://api\.uktradeinfo\.com/Export": (200, exp, "application/json")}


# ---------------------------------------------------------------------------------------------
# Uruguay XXI SIE, "Por Empresa"
# ---------------------------------------------------------------------------------------------


def test_sie_company_table_real_page():
    table = parse_sie_table(SIE_PAGE, "by company")
    assert table.caption == "Exportaciones por NCM: '0409', Período: 2022 - 2026"
    assert [c.label for c in table.columns] == ["2022", "2023", "2024", "2025", "2026 (ene - oct)"]
    assert table.problems == []                     # every year: the rows add up to the published total
    assert table.total[3] == 27928748.53 and table.total[4] == 33100409.13
    assert len(table.rows) == 17
    recs, complete, problems = co.sie_company_years(table, date(2026, 11, 5))
    assert problems == [] and complete == {2022, 2023, 2024, 2025, 2026}
    by = {(r.company, r.year): r for r in recs}
    assert by[("NECTARBEE S.A.", 2025)].value_usd == 15571168.32
    nb = by[("NECTARBEE S.A.", 2026)]
    assert (nb.value_usd, nb.running, nb.first_month, nb.last_month) == (18061978.55, True, 1, 10)
    assert by[("BUZARAM COMPANY S.A.", 2026)].value_usd == 5750902.81
    # zero cells are not records (BUZARAM exported nothing in 2022)
    assert ("BUZARAM COMPANY S.A.", 2022) not in by
    # the name truncated by the SIE is kept as published
    assert ("SOCIEDAD ANONIMA URUGUAYA DE IMPORTACIONES Y EXPORTACIONES (UR", 2025) in by
    assert len(recs) == 60


def test_sie_month_table_is_refused():
    """The monthly total has the same caption: a table of months means the company view was ignored."""
    month_table = (Path(__file__).parent / "fixtures" / "trade_uruguay_chile" / "real_sie_mes_total_2026.html").read_bytes()
    with pytest.raises(CollectorError, match="lists months, not companies"):
        co.sie_company_years(parse_sie_table(month_table, "x"), date(2026, 11, 5))


def test_uy_collector_end_to_end(run_with_routes, s):
    res = run_with_routes("uy_sie_honey_exporters", {SIE_URL: (200, SIE_PAGE, "text/html")})
    assert res["status"] == "success", res
    assert res["new"] == 60 and res["warnings"] == []
    rows = _current(s, country_iso3="URY")
    assert len(rows) == 60
    nb25 = next(r for r in rows if r.company_name == "NECTARBEE S.A." and r.period_label == "2025")
    assert (nb25.role, nb25.measure_kind, nb25.value, nb25.currency, nb25.value_basis) == (
        "exporter", "exact_value", 15571168.32, "USD", "FOB")
    assert (nb25.data_status, nb25.frequency, nb25.hs_code) == ("published", "A", "0409")
    assert nb25.extra["national_total_usd"] == 27928748.53
    assert nb25.source_url.startswith(SIE_URL) and "t=empresa" in nb25.source_url and "ncm=0409" in nb25.source_url
    nb26 = next(r for r in rows if r.company_name == "NECTARBEE S.A." and r.period_label == "2026")
    assert (nb26.data_status, nb26.frequency, nb26.period_end) == ("provisional", "YTD", date(2026, 10, 31))
    # the stored 2025 rows add up to the published total, to the cent of rounding the SIE itself shows
    # (its rows sum to 27,928,748.52, its "Total Detalle" reads 27,928,748.53)
    assert abs(sum(r.value for r in rows if r.period_label == "2025") - 27928748.53) < 0.015
    # private persons: the name only, no location, no ID anywhere
    person = next(r for r in rows if r.company_name == "LORENZ HELMUT")
    assert person.location is None and set(person.extra) == {
        "ncm", "national_total_usd", "column_label", "months_covered", "running_year", "query", "sie_caption", "web_ui"}
    # archived: the caption and the table only, not the page with its autocomplete list
    raw = s.get(RawDocument, nb25.raw_document_id)
    assert raw.size_bytes < 10_000
    src = s.scalars(select(Source).where(Source.key == "uy_sie_honey_exporters")).one()
    assert src.category == "companies" and src.latest_period_label == "2026"

    # the same answer again: nothing new, nothing revised
    again = run_with_routes("uy_sie_honey_exporters", {SIE_URL: (200, SIE_PAGE, "text/html")})
    assert again["status"] == "no_change" and again["new"] == 0 and again["revised"] == 0


def test_uy_revision_and_withdrawal(run_with_routes, s):
    run_with_routes("uy_sie_honey_exporters", {SIE_URL: (200, SIE_PAGE, "text/html")})
    # Variant derived from the real page: URUMIEL's 2026 value revised and the total moved by the same
    # amount; CAMPO CERCANO's only row (200,00 in 2023) and that amount taken out of the 2023 total.
    text = SIE_PAGE.decode("utf-8")
    text = text.replace("117.140,80", "117.240,80").replace("33.100.409,13", "33.100.509,13")
    text = re.sub(r"<tr>\s*<td>\s*CAMPO CERCANO S A\s*</td>.*?</tr>", "", text, flags=re.S)
    text = text.replace("18.478.487,19", "18.478.287,19")
    res = run_with_routes("uy_sie_honey_exporters", {SIE_URL: (200, text.encode("utf-8"), "text/html")})
    assert res["status"] == "partial", res          # the withdrawal is reported
    assert res["revised"] == 2 and res["new"] == 0
    uru = _current(s, company_name="URUMIEL LTDA.", period_label="2026")
    assert len(uru) == 1 and uru[0].value == 117240.80 and uru[0].revision == 2
    old = s.scalars(select(C).where(C.company_name == "URUMIEL LTDA.", C.period_label == "2026", C.is_current.is_(False))).one()
    assert old.value == 117140.80                    # history kept
    assert _current(s, company_name="CAMPO CERCANO S A") == []
    assert s.scalar(select(func.count(C.id)).where(C.company_name == "CAMPO CERCANO S A")) == 1


def test_uy_rows_that_do_not_add_up_are_not_stored(run_with_routes, s):
    text = SIE_PAGE.decode("utf-8").replace("15.571.168,32", "15.571.968,32")   # 2025 no longer adds up
    res = run_with_routes("uy_sie_honey_exporters", {SIE_URL: (200, text.encode("utf-8"), "text/html")})
    assert res["status"] == "partial"
    assert any("2025" in w and "published total" in w for w in res["warnings"])
    assert _current(s, period_label="2025") == []
    assert len(_current(s, period_label="2024")) > 0


# ---------------------------------------------------------------------------------------------
# HMRC UK Trade Info traders
# ---------------------------------------------------------------------------------------------


def test_hmrc_location_keeps_no_street_and_no_full_postcode():
    t = {"Address1": "16 HORNBEAM CLOSE", "Address2": "ST. MARTINS", "Address3": "OSWESTRY", "Address4": "",
         "Address5": "", "PostCode": "SY11 3FL"}
    assert co.hmrc_location(t) == "OSWESTRY, SY11"
    assert co.hmrc_location({"Address1": "1 HIGH ST", "Address2": "-", "PostCode": "E7 9AB"}) == "E7"
    assert co.hmrc_location({"Address1": "1 HIGH ST", "PostCode": "unknown"}) is None
    assert co.postcode_district("IM9 3AJ") == "IM9"


def test_hmrc_parse_real_answer():
    rows, problems = co.parse_hmrc_traders(json.loads(HMRC_IMP), "Import", first_month=202411)
    assert problems == [] and len(rows) == 191
    nelson = next(r for r in rows if r.name == "NELSON HONEY UK LIMITED")
    assert (nelson.month, nelson.location, nelson.role.value) == ((2026, 7), "GLOUCESTERSHIRE, GL17", "importer")
    other = json.loads(HMRC_IMP)
    other["value"][0]["CommodityId"] = 4090001
    with pytest.raises(CollectorError, match="not 4090000"):
        co.parse_hmrc_traders(other, "Import", first_month=202411)


def test_hmrc_collector_end_to_end(run_with_routes, s):
    res = run_with_routes("uk_hmrc_honey_traders", _hmrc_routes())
    assert res["status"] == "success", res
    assert res["new"] == 191 + 36
    rows = _current(s, country_iso3="GBR")
    assert {r.role for r in rows} == {"importer", "exporter"}
    assert all(r.measure_kind == "none" and r.value is None and r.rank is None for r in rows)
    nz = [r for r in rows if r.company_name == "HONEY NEW ZEALAND EUROPE LTD" and r.role == "importer"]
    assert sorted(r.period_label for r in nz) == ["2026-07", "2026-08"]
    assert {r.location for r in nz} == {"HINCKLEY, LE10"}
    # nothing more precise than the town and the postcode district is kept, in the rows or the archive
    for r in rows:
        assert not re.search(r"\b[A-Z]{1,2}\d[A-Z\d]? \d[A-Z]{2}\b", r.location or "")
    raw = s.get(RawDocument, rows[0].raw_document_id)
    archived = (s.get(Source, rows[0].source_id).key, raw.size_bytes)
    assert archived[0] == "uk_hmrc_honey_traders"
    from paladex.config import get_settings
    body = (get_settings().raw_dir / raw.path).read_text()
    assert "LE10 3ER" not in body and "GLOUCESTER ROAD" not in body and "HINCKLEY, LE10" in body
    # the request asked for honey and the last 24 months, with the trader expanded
    assert "CommodityId+eq+4090000" in rows[0].source_url.replace("%20", "+")

    again = run_with_routes("uk_hmrc_honey_traders", _hmrc_routes())
    assert again["status"] == "no_change"


def test_hmrc_withdrawn_trader_is_retired(run_with_routes, s):
    run_with_routes("uk_hmrc_honey_traders", _hmrc_routes())
    data = json.loads(HMRC_IMP)
    gone = next(r for r in data["value"] if r["Trader"]["CompanyName"] == "NELSON HONEY UK LIMITED")
    data["value"] = [r for r in data["value"] if r is not gone]
    res = run_with_routes("uk_hmrc_honey_traders", _hmrc_routes(imp=json.dumps(data).encode()))
    assert res["revised"] == 1 and any("no longer lists 1 honey importer" in w for w in res["warnings"])
    assert _current(s, company_name="NELSON HONEY UK LIMITED", period_label="2026-07") == []
    assert s.scalar(select(func.count(C.id)).where(C.company_name == "NELSON HONEY UK LIMITED")) == 1


def test_a_list_without_figures_cannot_carry_one(s):
    with pytest.raises(ValueError, match="cannot carry a value"):
        record_company(s, source_id=1, series_key="x", country_iso3="GBR", company_name="A", location=None,
                       role="importer", hs_code="04090000", measure_kind="none", value=1.0,
                       period_start=date(2026, 1, 1), period_end=date(2026, 1, 31), period_label="2026-01",
                       frequency="M", data_status="published", reliability="official")


# ---------------------------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------------------------


def test_api_availability_per_country(api):
    d = api.get("/api/companies").json()
    st = {c["iso3"]: c for c in d["countries"]}
    assert st["URY"]["status"] == "figures" and st["URY"]["source_keys"] == ["uy_sie_honey_exporters"]
    assert st["GBR"]["status"] == "register"
    for iso3 in ("BRA", "ARG", "USA", "CHE", "NOR", "ITA", "DEU", "ESP", "FRA"):
        assert st[iso3]["status"] == "not_published", iso3
        assert st[iso3]["reason_it"] and st[iso3]["reason_en"] and st[iso3]["authority"]
    assert st["CHL"]["status"] == "unavailable"
    assert st["CHN"]["status"] == "unverified" and st["CHN"]["checked_on"] is None
    assert "Decree 11,544/2023" in st["BRA"]["reason_en"] and "gov.br/mdic" in st["BRA"]["url"]
    assert "ISTAT" in st["ITA"]["authority"]
    # figures first, then registers, ... unverified last
    order = [c["status"] for c in d["countries"]]
    assert order.index("figures") < order.index("register") < order.index("not_published") < order.index("unverified")
    assert st["URY"]["companies"] == {}


def test_api_country_lists(api, run_with_routes):
    run_with_routes("uy_sie_honey_exporters", {SIE_URL: (200, SIE_PAGE, "text/html")})
    run_with_routes("uk_hmrc_honey_traders", _hmrc_routes())

    ov = {c["iso3"]: c for c in api.get("/api/companies").json()["countries"]}
    assert ov["URY"]["companies"] == {"exporter": 17} and ov["URY"]["latest_period"] == "2026"
    assert ov["GBR"]["companies"]["importer"] > 90 and ov["GBR"]["latest_period"] == "2026-08"

    uy = api.get("/api/companies/ury").json()
    assert uy["availability"]["status"] == "figures"
    (lst,) = uy["lists"]
    assert (lst["role"], lst["measure_kind"], lst["currency"], lst["value_basis"]) == ("exporter", "exact_value", "USD", "FOB")
    assert lst["ref_period"] == "2025" and lst["company_count"] == 17
    assert [p["label"] for p in lst["periods"]] == ["2022", "2023", "2024", "2025", "2026"]
    assert lst["periods"][-1]["running_year"] and lst["periods"][-1]["months_covered"] == [1, 10]
    first, second = lst["companies"][:2]
    assert (first["name"], first["rank_in_ref"]) == ("NECTARBEE S.A.", 1)
    assert first["values"]["2025"]["value"] == 15571168.32 and first["values"]["2025"]["share_pct"] == 55.8
    assert second["name"] == "BUZARAM COMPANY S.A."
    # companies without 2025 exports come after, unranked
    tail = lst["companies"][-1]
    assert tail["rank_in_ref"] is None and "2025" not in tail["values"]
    assert lst["source"]["key"] == "uy_sie_honey_exporters" and lst["source"]["freshness"]["status"]

    gb = api.get("/api/companies/GBR").json()
    roles = [x["role"] for x in gb["lists"]]
    assert roles == ["exporter", "importer"]
    imp = gb["lists"][1]
    assert imp["measure_kind"] == "none" and imp["periods"] == ["2026-07", "2026-08"]
    names = [c["name"] for c in imp["companies"]]
    assert names == sorted(names, key=str.casefold)               # alphabetical, never ranked
    assert all("values" not in c and "rank_in_ref" not in c for c in imp["companies"])
    nz = next(c for c in imp["companies"] if c["name"] == "HONEY NEW ZEALAND EUROPE LTD")
    assert nz["periods"] == ["2026-07", "2026-08"] and nz["location"] == "HINCKLEY, LE10"

    br = api.get("/api/companies/BRA").json()
    assert br["lists"] == [] and br["availability"]["status"] == "not_published"
    assert api.get("/api/companies/XYZ").status_code == 404


def test_sources_page_counts_company_rows(api, run_with_routes):
    run_with_routes("uy_sie_honey_exporters", {SIE_URL: (200, SIE_PAGE, "text/html")})
    rows = {x["key"]: x for x in api.get("/api/sources").json()["sources"]}
    assert rows["uy_sie_honey_exporters"]["counts"] == {"companies": 60}
    assert rows["uk_hmrc_honey_traders"]["category"] == "companies"
