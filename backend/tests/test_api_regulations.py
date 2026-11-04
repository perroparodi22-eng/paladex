"""API tests for /api/regulations (official documents) and /api/regulations/duties (tariff layer).

Tariff rows come from running the collectors on the RECONSTRUCTED fixtures in
tests/fixtures/tariffs/ (illustrative values, see the README there). Regulation documents are
inserted directly; their titles imitate the Federal Register / EUR-Lex / RASFF patterns.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from paladex.collectors import tariffs as tr
from paladex.models import RegulationItem, Source, TariffMeasure
from paladex.services import tariffs as svc

FIX = Path(__file__).parent / "fixtures" / "tariffs"
TODAY = date(2026, 11, 4)
XI = r"^https://www\.trade-tariff\.service\.gov\.uk/xi/api/v2"
HTS = r"^https://hts\.usitc\.gov/reststop"


def fx(name: str) -> bytes:
    return (FIX / name).read_bytes()


def xi_routes(**override) -> dict:
    routes = {
        XI + r"/commodities/0409000000": fx("xi_commodity_0409000000.json"),
        XI + r"/quotas/search\?order_number=099990": fx("xi_quota_099990.json"),
        XI + r"/quotas/search\?order_number=099991": fx("xi_quota_099991.json"),
        XI + r"/quotas/search\?order_number=099992": fx("xi_quota_099992.json"),
        XI + r"/geographical_areas/9901": fx("xi_geo_9901.json"),
    }
    return {**override, **{k: v for k, v in routes.items() if k not in override}}


HTS_ROUTES = {
    HTS + r"/exportList\?from=0409&": fx("hts_0409.json"),
    HTS + r"/exportList\?from=9903\.01&": fx("hts_9903_01.json"),
    HTS + r"/exportList\?from=9903\.88&": fx("hts_9903_88.json"),
}


@pytest.fixture()
def pin_today(monkeypatch):
    def _pin(d: date):
        monkeypatch.setattr(tr, "today", lambda: d)
    _pin(TODAY)
    return _pin


def show_demo(api, on: bool = True):
    assert api.put("/api/settings", json={"show_demo": on}).status_code == 200


def _src(db, key: str) -> Source:
    return db.scalars(select(Source).where(Source.key == key)).one()


def _add_docs(db) -> dict[str, RegulationItem]:
    fr, eurlex, rasff, demo = (_src(db, k) for k in ("us_federal_register", "eurlex_honey", "rasff_honey", "demo"))
    items = {
        "orders": RegulationItem(
            source_id=fr.id, jurisdiction="US", doc_type="antidumping", reference="2099-90001",
            title="Raw Honey From Argentina, Brazil, India, and the Socialist Republic of Vietnam: Antidumping Duty Orders",
            published_at=date(2022, 6, 10), url="https://www.federalregister.gov/d/2099-90001",
            countries=["ARG", "BRA", "IND", "VNM"], summary_en="Commerce is issuing antidumping duty orders (illustrative).",
            status="published"),
        "china": RegulationItem(
            source_id=fr.id, jurisdiction="US", doc_type="antidumping", reference="2099-90002",
            title="Honey From the People's Republic of China: Final Results of Antidumping Duty Administrative Review",
            published_at=date(2026, 1, 15), url="https://www.federalregister.gov/d/2099-90002", countries=["CHN"]),
        "directive": RegulationItem(
            source_id=eurlex.id, jurisdiction="EU", doc_type="directive", reference="32024L1438",
            title="Directive (EU) 2024/1438 of the European Parliament and of the Council of 14 May 2024 amending "
                  "Council Directives 2001/110/EC relating to honey ...",
            published_at=date(2024, 5, 14), url="https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024L1438"),
        "rasff": RegulationItem(
            source_id=rasff.id, jurisdiction="EU", doc_type="food_safety_notification", reference="2099.9001",
            title="Honey from Ukraine with an illustrative finding", published_at=date(2026, 10, 1),
            url="https://webgate.ec.europa.eu/rasff-window/screen/notification/99901", countries=["UKR"]),
        "demo": RegulationItem(
            source_id=demo.id, jurisdiction="EU", doc_type="regulation", reference="DEMO-1", title="Demo honey act",
            published_at=date(2026, 11, 1), url="https://example.org/demo", is_demo=True),
    }
    db.add_all(items.values())
    db.commit()
    return items


# ---------------------------------------------------------------------------
# /api/regulations
# ---------------------------------------------------------------------------


def test_regulations_list_filters_facets_and_provenance(api, db):
    _add_docs(db)
    d = api.get("/api/regulations").json()
    assert d["total"] == 4 and d["pages"] == 1                      # demo hidden
    assert [i["reference"] for i in d["items"]] == ["2099.9001", "2099-90002", "32024L1438", "2099-90001"]
    china = d["items"][1]
    assert china["source"]["key"] == "us_federal_register" and china["reliability"] == "official"
    assert china["data_status"] == "published" and china["source_url"] == china["url"] and china["collected_at"]
    assert china["ad_cases"] == [{"origin_iso3": "CHN", "case_number": "A-570-863",
                                  "product": "Honey from the People's Republic of China"}]
    orders = d["items"][3]
    assert [c["origin_iso3"] for c in orders["ad_cases"]] == ["ARG", "BRA", "IND", "VNM"]
    assert d["items"][2]["ad_cases"] == []                          # EU documents carry no US case
    f = d["facets"]
    assert {x["key"]: x["count"] for x in f["jurisdictions"]} == {"EU": 2, "US": 2}
    assert {x["key"]: x["count"] for x in f["doc_types"]}["antidumping"] == 2
    assert {x["key"]: x["count"] for x in f["countries"]}["UKR"] == 1
    assert {s["key"] for s in d["sources"]} >= {"us_federal_register", "eurlex_honey", "rasff_honey"}
    assert not {"eu_tariff_xi", "us_hts"} & {s["key"] for s in d["sources"]}

    assert api.get("/api/regulations", params={"jurisdiction": "us"}).json()["total"] == 2
    assert api.get("/api/regulations", params={"doc_type": "directive,food_safety_notification"}).json()["total"] == 2
    assert [i["reference"] for i in api.get("/api/regulations", params={"country": "UKR"}).json()["items"]] == ["2099.9001"]
    assert api.get("/api/regulations", params={"q": "people's republic"}).json()["total"] == 1
    assert api.get("/api/regulations", params={"q": "100%_"}).json()["total"] == 0        # LIKE wildcards escaped
    assert api.get("/api/regulations", params={"country": "XXX"}).status_code == 400
    p2 = api.get("/api/regulations", params={"page_size": 1, "page": 2}).json()
    assert p2["pages"] == 4 and [i["reference"] for i in p2["items"]] == ["2099-90002"]

    show_demo(api)
    d = api.get("/api/regulations").json()
    assert d["total"] == 5 and d["items"][0]["is_demo"] is True and d["items"][0]["data_status"] == "demo"


def test_regulations_empty(api):
    d = api.get("/api/regulations").json()
    assert d["total"] == 0 and d["items"] == [] and d["last_collected_at"] is None
    assert d["facets"] == {"jurisdictions": [], "doc_types": [], "countries": []}


# ---------------------------------------------------------------------------
# /api/regulations/duties
# ---------------------------------------------------------------------------


def test_duties_empty_state(api):
    d = api.get("/api/regulations/duties").json()
    assert d["has_data"] is False
    assert [o["iso3"] for o in d["origins"]][:3] == ["CHN", "ARG", "BRA"]
    assert all(not o["eu"]["rows"] and not o["us"]["rows"] for o in d["origins"])
    assert d["jurisdictions"]["EU"]["source"]["key"] == "eu_tariff_xi" and d["jurisdictions"]["EU"]["last_run_at"] is None
    assert d["jurisdictions"]["US"]["freshness"]["status"] == "never"
    # AD case links exist even before any Federal Register document is collected (no rates)
    arg = next(o for o in d["origins"] if o["iso3"] == "ARG")
    assert arg["us"]["ad_case"]["case_number"] == "A-357-823" and arg["us"]["ad_case"]["documents"] == []
    assert arg["us"]["ad_case"]["fr_search_url"].startswith("https://www.federalregister.gov/documents/search?")


def test_duties_grouped_per_origin_and_jurisdiction(api, db, run_with_routes, pin_today):
    run_with_routes("eu_tariff_xi", xi_routes())
    run_with_routes("us_hts", HTS_ROUTES)
    _add_docs(db)
    d = api.get("/api/regulations/duties").json()
    assert d["has_data"] is True
    order = [o["iso3"] for o in d["origins"]]
    assert order == ["CHN", "ARG", "BRA", "URY", "UKR", "SRB", "VNM", "IND", "MEX", "TUR", "CHL", "NZL", "CAN", "USA",
                     "MDA", "THA"]                                   # priority origins first, then the others
    by = {o["iso3"]: o for o in d["origins"]}

    eu = d["jurisdictions"]["EU"]
    assert eu["as_of"] == "2026-11-04" and eu["source"]["reliability"] == "official"
    assert "mirror of the EU TARIC" in eu["terms_note"]
    general = {g["measure_type"]: g for g in eu["general"]}
    assert general["mfn"]["duty_text"] == "17.30 %" and general["mfn"]["origin_iso3"] == "ERGA_OMNES"
    assert general["other"]["needs_review"] is True and eu["review_count"] == 1

    ukr = by["UKR"]
    assert ukr["priority"] is True and ukr["name_it"] == "Ucraina"
    trq = ukr["eu"]["rows"][0]
    assert trq["measure_type"] == "trq_in" and trq["duty_text"] == "0.00 %"
    assert trq["quota"]["order_number"] == "099990" and trq["quota"]["fill_pct"] == 62.14
    assert trq["quota"]["status"] == "open" and trq["quota"]["period_end"] == "2026-12-31"
    assert trq["legal_url"].startswith("https://eur-lex.europa.eu/") and "Area=UA" in trq["consult_url"]
    assert trq["as_of"] == "2026-11-04" and trq["source"]["key"] == "eu_tariff_xi" and trq["is_demo"] is False
    assert general["mfn"]["id"] in ukr["eu"]["general_ids"] and ukr["eu"]["has_own_mfn"] is False
    assert "Area=UA" in ukr["eu"]["links"]["taric"] and "SimDate=20261104" in ukr["eu"]["links"]["taric"]
    assert ukr["us"]["rows"] == [] and ukr["us"]["ad_case"] is None   # no US AD order on Ukrainian honey
    assert "Area=XS" in by["SRB"]["eu"]["links"]["taric"]

    # group expansion: a shared quota appears for each member origin
    assert [r["quota"]["order_number"] for r in by["ARG"]["eu"]["rows"]] == ["099992"]
    assert by["ARG"]["eu"]["rows"][0]["quota"]["fill_pct"] is None   # no definition: never invented
    assert [r["measure_type"] for r in by["CHL"]["eu"]["rows"]] == ["preference", "trq_in"]

    us = d["jurisdictions"]["US"]
    us_general = {g["measure_code"]: g for g in us["general"]}
    assert us_general["general"]["duty_text"] == "1.9¢/kg" and us_general["general"]["specific_amount"] == 0.019
    assert {"9903.01.25", "9903.01.29"} <= set(us_general) and us["review_count"] == 3
    assert set(by["CHN"]["us"]["general_ids"]) == {g["id"] for g in us["general"]}
    mex = by["MEX"]["us"]["rows"]
    assert [(r["measure_type"], r["duty_text"]) for r in mex] == [("preference", "Free")]
    cn = by["CHN"]["us"]
    assert [(r["measure_type"], r["measure_code"], r["needs_review"]) for r in cn["rows"]] == [("surcharge", "9903.88.15", False)]
    assert cn["ad_case"]["case_number"] == "A-570-863" and cn["ad_case"]["documents_total"] == 1
    assert cn["ad_case"]["documents"][0]["reference"] == "2099-90002"
    assert by["BRA"]["us"]["rows"][0]["needs_review"] is True and by["BRA"]["us"]["review_count"] == 1
    assert by["ARG"]["us"]["ad_case"]["documents"][0]["reference"] == "2099-90001"
    assert by["IND"]["us"]["ad_case"]["case_number"] is None          # not in the research: not invented
    assert by["URY"]["us"]["ad_case"] is None and by["USA"]["us"]["domestic"] is True
    assert {c["origin_iso3"] for c in d["ad_cases"]} == {"CHN", "ARG", "BRA", "IND", "VNM"}

    one = api.get("/api/regulations/duties", params={"origin": "ukr"}).json()
    assert [o["iso3"] for o in one["origins"]] == ["UKR"]
    assert api.get("/api/regulations/duties", params={"origin": "ZZZ"}).status_code == 400


def _commodity_with_safeguard() -> bytes:
    """The XI commodity fixture plus an ERGA OMNES additional duty (TARIC type 696, 25.00 %),
    a general layer that parses cleanly (illustrative, like the rest of the fixture)."""
    doc = json.loads(fx("xi_commodity_0409000000.json"))
    mfn = next(o for o in doc["included"] if o["type"] == "measure" and o["id"] == "3000101")
    sg = json.loads(json.dumps(mfn))
    sg["id"], sg["attributes"]["id"] = "3000199", 3000199
    sg["relationships"]["measure_type"]["data"]["id"] = "696"
    sg["relationships"]["duty_expression"]["data"]["id"] = "3000199-duty_expression"
    doc["included"] += [
        sg,
        {"id": "696", "type": "measure_type",
         "attributes": {"id": "696", "description": "Additional duties (safeguard)", "measure_type_series_id": "C"}},
        {"id": "3000199-duty_expression", "type": "duty_expression",
         "attributes": {"base": "25.00 %", "formatted_base": "<span>25.00</span> %"}},
    ]
    doc["data"]["relationships"]["import_measures"]["data"].append({"id": "3000199", "type": "measure"})
    return json.dumps(doc).encode()


def test_duties_general_eu_layer_other_than_mfn_is_returned_for_every_origin(api, run_with_routes, pin_today):
    """An erga-omnes safeguard/additional duty is a general layer the matrix must render next to
    the MFN (EuCell shows every applicable general row not needing review)."""
    run_with_routes("eu_tariff_xi", xi_routes(**{XI + r"/commodities/0409000000": _commodity_with_safeguard()}))
    d = api.get("/api/regulations/duties").json()
    general = {g["measure_code"]: g for g in d["jurisdictions"]["EU"]["general"]}
    sg = general["696"]
    assert (sg["measure_type"], sg["scope"], sg["ad_valorem_pct"], sg["needs_review"]) == ("surcharge", "general", 25.0, False)
    assert [g["measure_code"] for g in d["jurisdictions"]["EU"]["general"]][:2] == ["103", "696"]   # MFN first
    for o in d["origins"]:
        assert sg["id"] in o["eu"]["general_ids"], o["iso3"]


def test_duties_cell_date_exposes_layers_the_last_run_could_not_reconfirm(api, run_with_routes, pin_today):
    """XI: the Mexican quota search fails and the commodity has no inline definition, so the
    quota row keeps its 11-04 balance and date. The MFN is re-confirmed on 11-20: the cell must
    not present the 16-day-old balance as verified on 11-20."""
    run_with_routes("eu_tariff_xi", xi_routes())
    pin_today(date(2026, 11, 20))
    res = run_with_routes("eu_tariff_xi", xi_routes(**{XI + r"/quotas/search\?order_number=099991": (500, b"upstream error")}))
    assert res["status"] == "partial"
    d = api.get("/api/regulations/duties").json()
    eu = d["jurisdictions"]["EU"]
    assert eu["as_of"] == "2026-11-20" and eu["last_run_status"] == "partial"
    mfn = next(g for g in eu["general"] if g["measure_type"] == "mfn")
    assert mfn["as_of"] == "2026-11-20" and mfn["stale"] is False
    mex = next(o for o in d["origins"] if o["iso3"] == "MEX")["eu"]
    trq = next(r for r in mex["rows"] if r["measure_type"] == "trq_in")
    assert (trq["as_of"], trq["stale"], trq["quota"]["balance_kg"]) == ("2026-11-04", True, 1_200_000.0)
    assert mex["as_of"] == "2026-11-04" and mex["as_of_latest"] == "2026-11-20"   # never only the newer date
    assert "SimDate=20261120" in mex["links"]["taric"]
    ukr = next(o for o in d["origins"] if o["iso3"] == "UKR")["eu"]   # re-confirmed: one date, nothing stale
    assert ukr["as_of"] == ukr["as_of_latest"] == "2026-11-20" and not any(r["stale"] for r in ukr["rows"])


def test_duties_us_surcharge_not_reconfirmed_is_marked_stale(api, run_with_routes, pin_today):
    """HTS: the Section 301 range and the footnote search fail (ch99_ok=False). The general 1.9¢/kg
    row is refreshed; the China surcharge keeps its old date and must not look verified today."""
    run_with_routes("us_hts", HTS_ROUTES)
    pin_today(date(2026, 11, 20))
    res = run_with_routes("us_hts", {**HTS_ROUTES, HTS + r"/exportList\?from=9903\.88&": (503, b"down"),
                                     HTS + r"/search\?keyword=": (503, b"down")})
    assert res["status"] == "partial"
    d = api.get("/api/regulations/duties").json()
    us = d["jurisdictions"]["US"]
    base = next(g for g in us["general"] if g["measure_code"] == "general")
    assert base["as_of"] == "2026-11-20" and base["stale"] is False
    chn = next(o for o in d["origins"] if o["iso3"] == "CHN")["us"]
    s301 = next(r for r in chn["rows"] if r["measure_code"] == "9903.88.15")
    assert (s301["as_of"], s301["stale"]) == ("2026-11-04", True)
    assert chn["as_of"] == "2026-11-04" and chn["as_of_latest"] == "2026-11-20"
    mex = next(o for o in d["origins"] if o["iso3"] == "MEX")["us"]
    assert mex["as_of"] == mex["as_of_latest"] == "2026-11-20"


def test_duty_history_shows_every_revision(api, db, run_with_routes, pin_today):
    run_with_routes("eu_tariff_xi", xi_routes())
    pin_today(date(2026, 11, 5))
    quota = json.loads(fx("xi_quota_099990.json"))
    quota["data"][0]["attributes"]["balance"] = "9000000.0"
    run_with_routes("eu_tariff_xi", xi_routes(**{XI + r"/quotas/search\?order_number=099990": json.dumps(quota).encode()}))
    h = api.get("/api/regulations/duties/UKR").json()
    assert h["origin"] == "UKR" and h["name_en"] == "Ukraine"
    series = {s["series_key"]: s for s in h["series"]}
    trq = next(s for s in h["series"] if s["measure_type"] == "trq_in")
    assert trq["scope"] == "origin" and trq["current"] is True
    assert [(r["revision"], r["is_current"], r["quota"]["balance_kg"], r["quota"]["fill_pct"]) for r in trq["revisions"]] == \
        [(2, True, 9_000_000.0, 74.29), (1, False, 13_250_000.0, 62.14)]
    assert trq["revisions"][0]["supersedes_id"] == trq["revisions"][1]["id"]
    assert h["series"][0]["scope"] == "origin"                         # own layers before general ones
    assert any(s["scope"] == "general" and s["measure_type"] == "mfn" for s in series.values())
    assert "Area=UA" in h["links"]["taric"] and h["ad_case"] is None
    assert api.get("/api/regulations/duties/ERGA_OMNES").json()["series"]
    assert api.get("/api/regulations/duties/XYZ").status_code == 404


def test_duties_demo_isolation(api, db):
    demo_src = _src(db, "demo")
    _, row = svc.record_measure(
        db, source_id=demo_src.id, series_key="demo|EU|THA|mfn", as_of=TODAY, is_demo=True,
        jurisdiction="EU", origin_iso3="THA", hs_code="0409000000", measure_type="mfn", measure_code="103",
        duty_text="99.00 %", ad_valorem_pct=99.0, data_status="demo", reliability="demo")
    db.commit()
    d = api.get("/api/regulations/duties").json()
    assert d["has_data"] is False
    assert next(o for o in d["origins"] if o["iso3"] == "THA")["eu"]["rows"] == []
    assert api.get("/api/regulations/duties/THA").json()["series"] == []
    show_demo(api)
    d = api.get("/api/regulations/duties").json()
    rows = next(o for o in d["origins"] if o["iso3"] == "THA")["eu"]["rows"]
    assert [(r["id"], r["is_demo"], r["data_status"]) for r in rows] == [(row.id, True, "demo")]
    show_demo(api, False)
    assert db.scalars(select(TariffMeasure).where(TariffMeasure.is_demo.is_(True))).one().duty_text == "99.00 %"
    assert api.delete("/api/demo").status_code == 200              # purge removes demo tariff rows too
    db.expire_all()
    assert db.scalars(select(TariffMeasure).where(TariffMeasure.is_demo.is_(True))).all() == []
