"""Honey exporters and importers by company: collectors/companies_official.py (Uruguay XXI SIE "Por
Empresa", HMRC UK Trade Info traders, India EIC approved honey establishments, Canada ISED Canadian
Importers Database), models_companies.py and api/companies.py.

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
EIC_JSON = (FIX / "real_eic_facilities_honey_2026-11-05.json").read_bytes()
CID_PAGE = (FIX / "real_cid_hs6_040900_2026-11-05.html").read_bytes()
SIE_URL = "https://herramientas.uruguayxxi.gub.uy/sistema_de_estadistica/filtros.php"
EIC_URL = "https://eicindia.gov.in/api/facilities"
CID_URL = "https://www.ised-isde.canada.ca/app/ixb/cid-bdic/productReport.html"
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
# India: Export Inspection Council, establishments approved for honey export
# ---------------------------------------------------------------------------------------------


def test_india_state_keeps_only_the_state():
    assert co.india_state("Village and Post Kandera,Teh-Baraut,District-Baghpat, UP -250620") == "Uttar Pradesh"
    assert co.india_state("Plot No. 01, Kami-Gannur Road, Kami Village, Sonepat, (HR)- 131001") == "Haryana"
    assert co.india_state("V&PO Birakheri,Saharanpur-247340,U.P.") == "Uttar Pradesh"
    assert co.india_state("Patanjali Food and Herbal Park,Laksar Road,Haridwar-249404(Uttarakhand)") == "Uttarakhand"
    # the state named last wins (an address naming two states ends with its own)
    assert co.india_state("C/o: Pagro Frozen Foods, Adjoining GT Road (Haryana border), Fatehgarh Sahib, Punjab-140406.") == "Punjab"
    # no state name ("Gajarat" as published): the PIN prefix 38 belongs to Gujarat only
    assert co.india_state("Block No. 268, Changodar,Ahmedabad,  Gajarat, 382213") == "Gujarat"
    # PIN 24xxxx is shared by Uttar Pradesh and Uttarakhand: no guess
    assert co.india_state("Vill Mundet, Deoband Road, Roorkee 247656") is None
    assert co.india_state(None) is None


def test_eic_parse_real_answer():
    payload = json.loads(EIC_JSON)
    rows, total, problems = co.parse_eic_facilities(payload)
    assert problems == [] and total == 31 and len(rows) == 27          # the 4 dairy/fruit rows are not honey
    by = {e.approval_no: e for e in rows}
    pat = by["Honey/04/027/2018"]
    assert (pat.name, pat.state, pat.valid_until, pat.eu_approved) == (
        "Patanjali Food Limited", "Uttarakhand", "2028-07-26", True)
    akr = by["Honey/04/038/2024"]
    assert (akr.name, akr.state, akr.approved_for, akr.eu_approved) == ("AKR Great Honeybee Pvt. Ltd.", "Haryana", "Non-EU", False)
    assert by["Honey/04/035/2023"].state is None
    assert sum(e.eu_approved is True for e in rows) == 16 and sum(e.eu_approved is False for e in rows) == 11
    # two establishments of one company are two entries (two approval numbers)
    assert sum(e.name.startswith("Shakti Apifoods") for e in rows) == 2
    # not the register: fail loudly
    with pytest.raises(CollectorError, match="not a non-empty list"):
        co.parse_eic_facilities({"error": "x"})
    with pytest.raises(CollectorError, match="category_id"):
        co.parse_eic_facilities([{"id": 1, "name": "A"}])
    # an inactive row is not listed
    payload[[r["approval_no"] for r in payload].index("Honey/04/027/2018")]["is_active"] = 0
    assert "Honey/04/027/2018" not in {e.approval_no for e in co.parse_eic_facilities(payload)[0]}


def test_eic_collector_end_to_end(run_with_routes, s, monkeypatch):
    res = run_with_routes("in_eic_honey_establishments", {EIC_URL: (200, EIC_JSON, "application/json")})
    assert res["status"] == "success", res
    assert res["new"] == 27 and res["warnings"] == []
    rows = _current(s, country_iso3="IND")
    assert len(rows) == 27
    assert all((r.role, r.measure_kind, r.hs_code, r.period_label, r.frequency) ==
               ("registered_exporter", "none", "0409", "2026-11", "register") for r in rows)
    assert all(r.value is None and r.rank is None for r in rows)
    pat = next(r for r in rows if r.company_name == "Patanjali Food Limited")
    assert pat.location == "Uttarakhand" and pat.extra["approval_no"] == "Honey/04/027/2018"
    assert pat.extra["eu_approved"] is True and pat.extra["valid_until"] == "2028-07-26"
    assert (pat.period_start, pat.period_end) == (date(2026, 11, 1), date(2026, 11, 30))
    # the address is neither stored nor archived
    from paladex.config import get_settings
    raw = s.get(RawDocument, pat.raw_document_id)
    body = (get_settings().raw_dir / raw.path).read_text()
    assert "Laksar Road" not in body and "Honey/04/027/2018" in body and "Uttarakhand" in body
    assert all("Road" not in (r.location or "") for r in rows)

    again = run_with_routes("in_eic_honey_establishments", {EIC_URL: (200, EIC_JSON, "application/json")})
    assert again["status"] == "no_change" and again["new"] == 0

    # next month: the same register is listed again for December (one record per month listed);
    # an establishment EIC no longer lists is withdrawn for that month only
    monkeypatch.setattr(co, "today", lambda: date(2026, 12, 2))
    data = [r for r in json.loads(EIC_JSON) if r["approval_no"] != "Honey/04/038/2024"]
    dec = run_with_routes("in_eic_honey_establishments", {EIC_URL: (200, json.dumps(data).encode(), "application/json")})
    assert dec["new"] == 26 and dec["revised"] == 0
    assert len(_current(s, country_iso3="IND", period_label="2026-12")) == 26
    assert len(_current(s, country_iso3="IND", period_label="2026-11")) == 27
    # the withdrawal within a month that was read again is reported
    data2 = [r for r in data if r["approval_no"] != "Honey/04/027/2018"]
    gone = run_with_routes("in_eic_honey_establishments", {EIC_URL: (200, json.dumps(data2).encode(), "application/json")})
    assert gone["revised"] == 1 and any("no longer lists 1 honey establishment" in w for w in gone["warnings"])
    assert _current(s, company_name="Patanjali Food Limited", period_label="2026-12") == []


# ---------------------------------------------------------------------------------------------
# Canada: ISED Canadian Importers Database, major importers of HS6 040900
# ---------------------------------------------------------------------------------------------


def test_cid_parse_real_page():
    r = co.parse_cid_report(CID_PAGE)
    assert (r.year, len(r.importers), r.total_value_cad, r.listed_share_pct, r.problems) == (2024, 25, 66356117.0, 79.92, [])
    by = {i.name: i for i in r.importers}
    assert by["BILLY BEE HONEY PRODUCTS COMPANY"].location == "London, Ontario"
    assert by["INTEGRA LIFESCIENCES SALES LLC"].location == "Princeton, New Jersey"      # non-resident importer
    assert by["MIDLANDS APIARIES LIMITED"].location == "Ashburton"                        # no province published
    assert "CITADELLE, COOPERATIVE DE PRODUCTEURS DE SIROP D'ERABLE/ CIT" in by           # as published (truncated)
    assert [i.name for i in r.importers] == sorted(i.name for i in r.importers)
    # another product's report, or a page without the importer table, is refused
    with pytest.raises(CollectorError, match="not the report for HS6 040900"):
        co.parse_cid_report(CID_PAGE.replace(b"<title>040900", b"<title>170290"))
    with pytest.raises(CollectorError, match="Major Canadian importers"):
        co.parse_cid_report(CID_PAGE.replace(b"Major Canadian importers", b"Major importers"))
    with pytest.raises(CollectorError, match="year"):
        co.parse_cid_report(CID_PAGE.replace(b"<span>in 2024</span>", b"<span></span>"))


def test_cid_collector_end_to_end(run_with_routes, s):
    res = run_with_routes("ca_cid_honey_importers", {CID_URL: (200, CID_PAGE, "text/html")})
    assert res["status"] == "success", res
    assert res["new"] == 25 and res["warnings"] == []
    rows = _current(s, country_iso3="CAN")
    assert all((r.role, r.measure_kind, r.hs_code, r.period_label, r.frequency) ==
               ("importer", "none", "040900", "2024", "A") for r in rows)
    billy = next(r for r in rows if r.company_name == "BILLY BEE HONEY PRODUCTS COMPANY")
    assert billy.location == "London, Ontario" and billy.value is None
    assert billy.extra["total_value_cad"] == 66356117.0 and billy.extra["listed_importers"] == 25
    assert "hsCode=040900" in billy.source_url
    # no postal code stored or archived
    from paladex.config import get_settings
    body = (get_settings().raw_dir / s.get(RawDocument, billy.raw_document_id).path).read_text()
    assert "N6A 4Z2" not in body and "BILLY BEE HONEY PRODUCTS COMPANY" in body
    assert all(not re.search(r"[A-Z]\d[A-Z] ?\d[A-Z]\d", r.location or "") for r in rows)

    again = run_with_routes("ca_cid_honey_importers", {CID_URL: (200, CID_PAGE, "text/html")})
    assert again["status"] == "no_change"

    # an importer no longer listed for the year is withdrawn (variant derived from the real page)
    text = CID_PAGE.decode("utf-8")
    text = re.sub(r"<tr>\s*<td >FRITO LAY CANADA</td>.*?</tr>", "", text, flags=re.S)
    res2 = run_with_routes("ca_cid_honey_importers", {CID_URL: (200, text.encode("utf-8"), "text/html")})
    assert res2["revised"] == 1 and any("no longer lists 1 honey importer" in w for w in res2["warnings"])
    assert _current(s, company_name="FRITO LAY CANADA") == []


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
    assert "Decree 11,544/2023" in st["BRA"]["reason_en"] and "gov.br/mdic" in st["BRA"]["url"]
    assert "ISTAT" in st["ITA"]["authority"]
    # the twelve main non-EU origins have all been checked: two registers, ten lists that exist but
    # cannot be read (EU Login, bot protection, unreachable hosts), each with authority and reason
    origins = ("CHN", "IND", "VNM", "UKR", "MEX", "TUR", "THA", "NZL", "CAN", "AUS", "SRB", "MDA")
    for iso3 in origins:
        a = st[iso3]
        assert a["status"] != "unverified" and a["checked_on"] == "2026-11-05", iso3
        assert a["authority"] != "—" and a["url"] and a["reason_it"] and a["reason_en"], iso3
    assert (st["IND"]["status"], st["IND"]["source_keys"], st["IND"]["roles"]) == (
        "register", ["in_eic_honey_establishments"], ["registered_exporter"])
    assert (st["CAN"]["status"], st["CAN"]["source_keys"], st["CAN"]["roles"]) == (
        "register", ["ca_cid_honey_importers"], ["importer"])
    assert {st[i]["status"] for i in origins if i not in ("IND", "CAN")} == {"unavailable"}
    assert "Export Inspection Council" in st["IND"]["authority"] and "SENASICA" in st["MEX"]["authority"]
    assert "EU Login" in st["UKR"]["reason_en"] and "Imperva" in st["NZL"]["reason_en"]
    # A country can also be listed only for its companies found on the web (reference/companies_web.py,
    # 15 Nov 2026: Japan, then Switzerland, Norway, the Western Balkans, Colombia...): what its authorities
    # publish has not been researched, and the page says so.
    from paladex.api.companies import AVAILABILITY
    from paladex.reference import companies_web

    web_only = {i for i in companies_web.counts() if i not in AVAILABILITY}
    assert d["status_counts"]["unverified"] == len(web_only) and "JPN" in web_only
    assert all(st[i]["status"] == "unverified" and st[i]["web_companies"] > 0 for i in web_only)
    # figures first, then registers, then lists that exist but cannot be used, then not published
    order = [c["status"] for c in d["countries"]]
    assert order.index("figures") < order.index("register") < order.index("unavailable") < order.index("not_published")
    assert order == sorted(order, key=["figures", "register", "unavailable", "not_published", "unverified"].index)
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

    run_with_routes("in_eic_honey_establishments", {EIC_URL: (200, EIC_JSON, "application/json")})
    run_with_routes("ca_cid_honey_importers", {CID_URL: (200, CID_PAGE, "text/html")})
    ov = {c["iso3"]: c for c in api.get("/api/companies").json()["countries"]}
    assert ov["IND"]["companies"] == {"registered_exporter": 27} and ov["IND"]["latest_period"] == "2026-11"
    assert ov["CAN"]["companies"] == {"importer": 25} and ov["CAN"]["latest_period"] == "2024"
    ind = api.get("/api/companies/IND").json()
    (reg,) = ind["lists"]
    assert (reg["role"], reg["measure_kind"], reg["company_count"], reg["periods"]) == (
        "registered_exporter", "none", 27, ["2026-11"])
    names = [c["name"] for c in reg["companies"]]
    assert names == sorted(names, key=lambda n: re.sub(r"^[^0-9A-Za-z]+", "", n).casefold())   # never ranked
    assert next(c for c in reg["companies"] if c["name"] == "Patanjali Food Limited")["location"] == "Uttarakhand"
    assert reg["source"]["key"] == "in_eic_honey_establishments" and "commodity-wise-facilities" in reg["web_url"]
    can = api.get("/api/companies/CAN").json()
    (imp_ca,) = can["lists"]
    assert (imp_ca["role"], imp_ca["company_count"], imp_ca["latest_period"], imp_ca["frequency"]) == (
        "importer", 25, "2024", "A")
    assert reg["frequency"] == "register" and imp["frequency"] == "M"

    br = api.get("/api/companies/BRA").json()
    assert br["lists"] == [] and br["availability"]["status"] == "not_published"
    assert api.get("/api/companies/XYZ").status_code == 404


def test_sources_page_counts_company_rows(api, run_with_routes):
    run_with_routes("uy_sie_honey_exporters", {SIE_URL: (200, SIE_PAGE, "text/html")})
    rows = {x["key"]: x for x in api.get("/api/sources").json()["sources"]}
    assert rows["uy_sie_honey_exporters"]["counts"] == {"companies": 60}
    assert rows["uk_hmrc_honey_traders"]["category"] == "companies"
