"""Tests for the tariff collectors (paladex/collectors/tariffs.py) and the append-only tariff store
(paladex/services/tariffs.py).

All fixtures in tests/fixtures/tariffs/ are RECONSTRUCTED from documentation (see the README
there); measures, rates and identifiers are illustrative, not the real tariff.
"""
from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from paladex.collectors import tariffs as tr
from paladex.collectors.registry import get_collector
from paladex.models import CollectionRun, RawDocument, Source, TariffMeasure
from paladex.services import tariffs as svc

FIX = Path(__file__).parent / "fixtures" / "tariffs"
TODAY = date(2026, 11, 4)

XI = r"^https://www\.trade-tariff\.service\.gov\.uk/xi/api/v2"
XI_COMMODITY = XI + r"/commodities/0409000000"
XI_QUOTA = XI + r"/quotas/search\?order_number="
XI_GEO_9901 = XI + r"/geographical_areas/9901"
HTS = r"^https://hts\.usitc\.gov/reststop"
HTS_0409 = HTS + r"/exportList\?from=0409&"
HTS_9903_01 = HTS + r"/exportList\?from=9903\.01&"
HTS_9903_88 = HTS + r"/exportList\?from=9903\.88&"
HTS_SEARCH = HTS + r"/search\?keyword="


def fx(name: str) -> bytes:
    return (FIX / name).read_bytes()


def fx_json(name: str):
    return json.loads(fx(name))


def as_bytes(obj) -> bytes:
    return json.dumps(obj).encode()


def _routes(base: dict, override: dict | None) -> dict:
    """Overrides first: the first matching route wins."""
    routes = dict(override or {})
    for k, v in base.items():
        routes.setdefault(k, v)
    return routes


def xi_routes(override: dict | None = None) -> dict:
    return _routes({
        XI_COMMODITY: fx("xi_commodity_0409000000.json"),
        XI_QUOTA + "099990": fx("xi_quota_099990.json"),
        XI_QUOTA + "099991": fx("xi_quota_099991.json"),
        XI_QUOTA + "099992": fx("xi_quota_099992.json"),
        XI_GEO_9901: fx("xi_geo_9901.json"),
    }, override)


def hts_routes(override: dict | None = None) -> dict:
    return _routes({
        HTS_0409: fx("hts_0409.json"),
        HTS_9903_01: fx("hts_9903_01.json"),
        HTS_9903_88: fx("hts_9903_88.json"),
    }, override)


@pytest.fixture()
def pin_today(monkeypatch):
    def _pin(d: date):
        monkeypatch.setattr(tr, "today", lambda: d)
    _pin(TODAY)
    return _pin


def _source(s, key: str) -> Source:
    return s.scalars(select(Source).where(Source.key == key)).one()


def _current(s, key: str) -> dict[str, TariffMeasure]:
    src = _source(s, key)
    rows = s.scalars(select(TariffMeasure).where(TariffMeasure.source_id == src.id, TariffMeasure.is_current.is_(True)))
    return {r.series_key: r for r in rows}


def _by(rows: dict[str, TariffMeasure], origin: str, measure_type: str | None = None) -> list[TariffMeasure]:
    return [r for r in rows.values() if r.origin_iso3 == origin and (measure_type is None or r.measure_type == measure_type)]


def _one(rows, origin, measure_type=None) -> TariffMeasure:
    found = _by(rows, origin, measure_type)
    assert len(found) == 1, [(r.series_key, r.measure_type) for r in found]
    return found[0]


def _commodity_without(*sids: str) -> bytes:
    doc = fx_json("xi_commodity_0409000000.json")
    doc["data"]["relationships"]["import_measures"]["data"] = [
        r for r in doc["data"]["relationships"]["import_measures"]["data"] if r["id"] not in sids]
    return as_bytes(doc)


# ---------------------------------------------------------------------------
# Pure parsers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text, av, amount, unit, cur, complex_", [
    ("17.30 %", 17.3, None, None, None, False),
    ("<span>17.30</span> %", 17.3, None, None, None, False),
    ("0.00 %", 0.0, None, None, None, False),
    ("0.00 % + 10.00 EUR / 100 kg/net", 0.0, 10.0, "100kg", "EUR", False),
    ("3.5 EUR / 100 kg", None, 3.5, "100kg", "EUR", False),
    ("12.8 % MAX 5.00 EUR / 100 kg", None, None, None, None, True),
    ("9.00 % + EA", None, None, None, None, True),
    ("", None, None, None, None, True),
])
def test_parse_eu_duty(text, av, amount, unit, cur, complex_):
    d = tr.parse_eu_duty(text)
    assert (d.ad_valorem_pct, d.specific_amount, d.specific_unit, d.specific_currency, d.complex) == (av, amount, unit, cur, complex_)
    if text and "span" not in text:
        assert d.text == text                      # always kept as published


@pytest.mark.parametrize("text, av, amount, complex_", [
    ("1.9¢/kg", None, 0.019, False),
    ("6.6¢/kg", None, 0.066, False),
    ("Free", 0.0, None, False),
    ("5%", 5.0, None, False),
    ("1.9¢/kg + 2%", 2.0, 0.019, False),
    ("$1.23/kg", None, 1.23, False),
    ("See heading 9903.01.25", None, None, True),
])
def test_parse_us_rate(text, av, amount, complex_):
    d = tr.parse_us_rate(text)
    assert (d.ad_valorem_pct, d.specific_amount, d.complex) == (av, amount, complex_)
    if amount is not None:
        assert (d.specific_unit, d.specific_currency) == ("kg", "USD")


def test_parse_us_additional_and_special():
    d = tr.parse_us_additional("The duty provided in the applicable subheading + 25%")
    assert d.parsed and d.ad_valorem_pct == 25.0
    exempt = tr.parse_us_additional("The duty provided in the applicable subheading")
    assert not exempt.parsed and not exempt.complex          # no additional duty at all
    assert tr.parse_us_additional("25%").complex              # not "+ ...": not read as additional
    groups, ok = tr.parse_special("Free (A+,AU,BH,CL,CO,D,E,IL,JO,KR,MA,OM,P,PA,PE,S,SG)")
    assert ok and groups == [("Free", ["A+", "AU", "BH", "CL", "CO", "D", "E", "IL", "JO", "KR", "MA", "OM", "P",
                                        "PA", "PE", "S", "SG"])]
    groups, ok = tr.parse_special("Free (A,AU) 0.5¢/kg (JP)")
    assert ok and groups == [("Free", ["A", "AU"]), ("0.5¢/kg", ["JP"])]
    assert tr.parse_special("Free (A,AU) see note")[1] is False


def test_xi_parse_select_and_group_expansion():
    com = tr.parse_xi_commodity(fx("xi_commodity_0409000000.json"))
    assert com.item_id == "0409000000" and len(com.measures) == 14 and not com.problems
    selected, problems = tr.select_xi_tariff_measures(com)
    sids = {s.measure.sid for s in selected}
    assert {"3000102", "3000103"}.isdisjoint(sids)            # UK duty and UK VAT (origin 'uk')
    assert "3000104" not in sids                              # veterinary control: series B, not a duty
    other = next(s for s in selected if s.measure.sid == "3000114")
    assert other.layer is svc.MeasureType.OTHER and other.needs_review and "105" in other.reason
    assert any("105" in p for p in problems)

    by_sid = {s.measure.sid: s.measure for s in selected}
    mfn = by_sid["3000101"]
    assert (mfn.type_id, mfn.geo_id, mfn.duty.ad_valorem_pct) == ("103", "1011", 17.3)
    assert mfn.legal_acts[0].code == "R2658/87" and mfn.legal_acts[0].url.startswith("https://eur-lex.europa.eu/")
    assert tr.expand_origins("1011", (), None) == [svc.ERGA_OMNES]            # ERGA OMNES stays one row
    assert tr.expand_origins("XS", (), None) == ["SRB"]                        # TARIC code for Serbia
    assert tr.expand_origins("NO", (), None) == []                             # not a Parodi origin
    gsp = by_sid["3000108"]
    children = com.geos["2020"].children
    assert children == ("IN", "PK", "ID", "NG")
    assert tr.expand_origins(gsp.geo_id, gsp.excluded, children) == ["IND"]
    assert tr.expand_origins(gsp.geo_id, ("IN",), children) == []              # excluded country removed
    assert com.geos["9901"].children is None                                   # must be fetched
    assert tr.expand_origins("9901", (), None) is None
    assert tr.expand_origins("9901", (), ("AR", "CL", "PY")) == ["ARG", "CHL"]
    ua = by_sid["3000105"]
    assert ua.order_number == "099990" and com.quotas["099990"].balance_kg == 13_500_000.0


def test_xi_quota_search_parsing():
    q, problems = tr.parse_xi_quota_search(fx("xi_quota_099990.json"), "099990", TODAY)
    assert not problems
    assert (q.volume_kg, q.balance_kg, q.status, q.status_raw) == (35_000_000.0, 13_250_000.0, "open", "Open")
    assert (q.valid_from, q.valid_to, q.last_allocation) == (date(2026, 1, 1), date(2026, 12, 31), date(2026, 10, 30))
    assert tr.parse_xi_quota_search(fx("xi_quota_099992.json"), "099992", TODAY) == (None, [])
    # a definition for another year does not cover today
    q, problems = tr.parse_xi_quota_search(fx("xi_quota_099990.json"), "099990", date(2027, 2, 1))
    assert q is None and "no definition covers" in problems[0]
    # tonnes are converted, other units are not stored as kg
    doc = fx_json("xi_quota_099990.json")
    doc["data"][0]["attributes"]["measurement_unit"] = "Tonne (1000 kg)"
    doc["data"][0]["attributes"].update(initial_volume="35000.0", balance="13250.0")
    q, _ = tr.parse_xi_quota_search(as_bytes(doc), "099990", TODAY)
    assert (q.volume_kg, q.balance_kg) == (35_000_000.0, 13_250_000.0)
    # hectokilograms (TARIC unit DTN) are 100 kg, not kg read off the "(100 kg)" abbreviation
    doc["data"][0]["attributes"]["measurement_unit"] = "Hectokilogram (100 kg)"
    doc["data"][0]["attributes"].update(initial_volume="350000.0", balance="132500.0")
    q, problems = tr.parse_xi_quota_search(as_bytes(doc), "099990", TODAY)
    assert (q.volume_kg, q.balance_kg) == (35_000_000.0, 13_250_000.0) and not problems
    for unit, factor in (("Hectokilogram", 100.0), ("100 kg", 100.0), ("Tonne", 1000.0), ("Tonne (1000 kg)", 1000.0),
                         ("Kilogram (kg)", 1.0), ("kg", 1.0), ("Hectolitre (hl)", None), ("Number of items (p/st)", None),
                         ("Litre pure (100 %) alcohol", None), (None, None)):
        assert tr._kg_factor(unit) == factor, unit
    doc["data"][0]["attributes"]["measurement_unit"] = "Hectolitre (hl)"
    q, problems = tr.parse_xi_quota_search(as_bytes(doc), "099990", TODAY)
    assert q.volume_kg is None and q.balance_kg is None and "not a mass unit" in problems[0]
    with pytest.raises(tr.SchemaDrift):
        tr.parse_xi_quota_search(b'{"data": [{"attributes": {"volume": "1"}}]}', "099990", TODAY)
    with pytest.raises(tr.SchemaDrift):
        tr.parse_xi_quota_search(b'{"definitions": []}', "099990", TODAY)


def test_xi_parse_drift():
    with pytest.raises(tr.SchemaDrift, match="not JSON"):
        tr.parse_xi_commodity(b"<html>maintenance</html>")
    doc = fx_json("xi_commodity_0409000000.json")
    bad = copy.deepcopy(doc)
    bad["data"]["attributes"]["goods_nomenclature_item_id"] = "0409000010"
    with pytest.raises(tr.SchemaDrift, match="goods_nomenclature_item_id"):
        tr.parse_xi_commodity(as_bytes(bad))
    bad = copy.deepcopy(doc)
    del bad["included"]
    with pytest.raises(tr.SchemaDrift, match="included"):
        tr.parse_xi_commodity(as_bytes(bad))
    bad = copy.deepcopy(doc)
    bad["included"] = [o for o in bad["included"] if o["type"] != "measure"]
    with pytest.raises(tr.SchemaDrift, match="none of the 14 import measures"):
        tr.parse_xi_commodity(as_bytes(bad))
    # no eu/uk flag at all and the same type/area twice: EU and UK duties cannot be told apart
    bad = copy.deepcopy(doc)
    for o in bad["included"]:
        if o["type"] == "measure":
            o["attributes"].pop("origin")
    with pytest.raises(tr.SchemaDrift, match="cannot be told apart"):
        tr.select_xi_tariff_measures(tr.parse_xi_commodity(as_bytes(bad)))


def test_hts_parsing_and_ch99_classification():
    rows = tr.parse_hts_rows(fx("hts_0409.json"), "HTS 0409")
    base = rows[0]
    assert (base.htsno, base.general, base.other) == ("0409.00.00", "1.9¢/kg", "6.6¢/kg")
    assert base.footnotes == ("See 9903.88.15.",)
    with pytest.raises(tr.SchemaDrift):
        tr.parse_hts_rows(b'{"error": "maintenance"}', "HTS")
    with pytest.raises(tr.SchemaDrift, match="keys seen"):
        tr.parse_hts_rows(b'[{"hts": "0409.00.00", "rate": "1.9"}]', "HTS")

    ch99 = {r.htsno: r for r in tr.parse_hts_rows(fx("hts_9903_01.json"), "HTS 9903.01") if r.htsno}
    d = tr.classify_ch99(ch99["9903.01.25"], footnote_ref=False)
    assert (d.origin, d.layer, d.needs_review, d.scope, d.duty.ad_valorem_pct) == ("ALL", "other", True, "all", 10.0)
    d = tr.classify_ch99(ch99["9903.01.26"], footnote_ref=False)
    assert (d.origin, d.layer, d.needs_review) == ("BRA", "other", True)       # product coverage not verified
    assert tr.classify_ch99(ch99["9903.01.27"], footnote_ref=False) is None    # Japan: not a Parodi origin
    assert tr.classify_ch99(ch99["9903.01.28"], footnote_ref=False) is None    # no additional duty
    d = tr.classify_ch99(ch99["9903.01.29"], footnote_ref=False)
    assert (d.origin, d.scope, d.named) == ("ALL", "mixed", ["CAN", "MEX"])    # never expanded to countries
    s301 = {r.htsno: r for r in tr.parse_hts_rows(fx("hts_9903_88.json"), "HTS 9903.88")}
    assert tr.classify_ch99(s301["9903.88.03"], footnote_ref=False, scan_unreferenced=False) is None
    d = tr.classify_ch99(s301["9903.88.15"], footnote_ref=True, scan_unreferenced=False)
    assert (d.origin, d.layer, d.needs_review, d.duty.ad_valorem_pct) == ("CHN", "surcharge", False, 7.5)


# ---------------------------------------------------------------------------
# EU: XI collector end to end
# ---------------------------------------------------------------------------


def test_xi_metadata_registered():
    c = get_collector("eu_tariff_xi")
    assert c is not None and c.reliability == "official" and c.category == "regulation"
    assert "mirror of the EU TARIC" in c.terms_note and "Open Government Licence" in c.terms_note
    assert "legally binding" in c.terms_note
    h = get_collector("us_hts")
    assert h is not None and h.reliability == "official" and h.requires_key is None


def test_xi_end_to_end(db, run_with_routes, pin_today):
    res = run_with_routes("eu_tariff_xi", xi_routes())
    assert res["status"] == "partial", res                    # the unmapped type 105 is reported
    rows = _current(db, "eu_tariff_xi")
    assert len(rows) == 11
    mfn = _one(rows, "ERGA_OMNES", "mfn")
    assert (mfn.jurisdiction, mfn.hs_code, mfn.measure_code, mfn.duty_text, mfn.ad_valorem_pct) == \
        ("EU", "0409000000", "103", "17.30 %", 17.3)
    assert (mfn.reliability, mfn.data_status, mfn.revision, mfn.as_of) == ("official", "published", 1, TODAY)
    assert mfn.description == "Third country duty"
    assert mfn.legal_reference == "R2658/87" and mfn.legal_url == "https://eur-lex.europa.eu/legal-content/EN/AUTO/?uri=CELEX:31987R2658"
    assert mfn.published_at == date(1987, 9, 7)
    assert mfn.consult_url.startswith(svc.TARIC_MEASURES_URL) and "SimDate=20261104" in mfn.consult_url
    assert "Area=&" in mfn.consult_url                        # all origins
    assert mfn.source_url == "https://www.trade-tariff.service.gov.uk/xi/api/v2/commodities/0409000000"
    assert mfn.raw_document_id and db.get(RawDocument, mfn.raw_document_id) is not None
    assert "mirror of EU TARIC" in mfn.extra["mirror"] and mfn.extra["needs_review"] is False
    other = _one(rows, "ERGA_OMNES", "other")
    assert other.extra["needs_review"] is True and other.measure_code == "105"

    ua = _one(rows, "UKR", "trq_in")
    assert (ua.quota_order_number, ua.quota_volume_kg, ua.quota_balance_kg, ua.quota_status) == \
        ("099990", 35_000_000.0, 13_250_000.0, "open")
    assert ua.extra["quota"]["last_allocation_date"] == "2026-10-30" and "Area=UA" in ua.consult_url
    assert svc.quota_fill_pct(ua.quota_volume_kg, ua.quota_balance_kg) == 62.14
    srb = _one(rows, "SRB", "preference")
    assert "Area=XS" in srb.consult_url and srb.extra["geo_area"]["id"] == "XS"
    ind = _one(rows, "IND", "preference")
    assert ind.ad_valorem_pct == 13.8 and ind.extra["geo_area"] == {"id": "2020", "description": "GSP - General arrangements", "group": True}
    assert ind.valid_to == date(2027, 12, 31)
    mex = _one(rows, "MEX", "trq_in")
    assert (mex.quota_status, mex.extra["quota"]["critical"]) == ("critical", "Y")
    # group quota: members fetched from /geographical_areas/9901; no definition covers today
    for origin in ("ARG", "CHL"):
        g = _one(rows, origin, "trq_in")
        assert g.quota_order_number == "099992" and g.quota_volume_kg is None and g.quota_balance_kg is None
        assert g.extra["quota"]["shared_by_group"] is True and "no definition" in g.extra["quota"]["note"]
    assert _one(rows, "CHL", "preference").ad_valorem_pct == 0.0
    assert {r.origin_iso3 for r in rows.values()} == {"ERGA_OMNES", "UKR", "SRB", "VNM", "IND", "MEX", "ARG", "CHL", "MDA"}
    src = _source(db, "eu_tariff_xi")
    assert src.latest_published_at == TODAY                   # "as of": the date the tariff was read


def test_xi_append_only_revision_and_as_of(db, run_with_routes, pin_today):
    assert run_with_routes("eu_tariff_xi", xi_routes())["status"] == "partial"
    pin_today(date(2026, 11, 5))
    quota = fx_json("xi_quota_099990.json")
    quota["data"][0]["attributes"].update(balance="9000000.0", last_allocation_date="2026-11-04")
    run_with_routes("eu_tariff_xi", xi_routes({XI_QUOTA + "099990": as_bytes(quota)}))
    db.expire_all()
    src = _source(db, "eu_tariff_xi")
    ua_all = db.scalars(select(TariffMeasure).where(TariffMeasure.source_id == src.id, TariffMeasure.origin_iso3 == "UKR")
                        .order_by(TariffMeasure.revision)).all()
    assert [(r.revision, r.is_current, r.quota_balance_kg) for r in ua_all] == [(1, False, 13_250_000.0), (2, True, 9_000_000.0)]
    assert ua_all[1].supersedes_id == ua_all[0].id and ua_all[1].as_of == date(2026, 11, 5)
    assert ua_all[0].as_of == TODAY                            # the old revision keeps its last confirmation
    mfn = _one(_current(db, "eu_tariff_xi"), "ERGA_OMNES", "mfn")
    assert mfn.revision == 1 and mfn.as_of == date(2026, 11, 5) and "SimDate=20261105" in mfn.consult_url
    assert db.scalar(select(TariffMeasure.id).where(TariffMeasure.source_id == src.id).order_by(TariffMeasure.id.desc())) \
        == ua_all[1].id                                       # nothing else was inserted


def test_xi_withdrawn_measure_is_retired_not_deleted(db, run_with_routes, pin_today):
    run_with_routes("eu_tariff_xi", xi_routes())
    pin_today(date(2026, 11, 5))
    res = run_with_routes("eu_tariff_xi", xi_routes({XI_COMMODITY: _commodity_without("3000107")}))
    assert res["status"] == "partial"
    db.expire_all()
    src = _source(db, "eu_tariff_xi")
    vn = db.scalars(select(TariffMeasure).where(TariffMeasure.source_id == src.id, TariffMeasure.origin_iso3 == "VNM")).all()
    assert len(vn) == 1 and vn[0].is_current is False and vn[0].ad_valorem_pct == 0.0   # values untouched
    run = db.scalars(select(CollectionRun).where(CollectionRun.source_id == src.id).order_by(CollectionRun.id.desc())).first()
    assert run.items_revised == 1 and any("no longer published" in w for w in run.warnings)


def test_xi_quota_failure_keeps_previous_row_and_blocks_retirement(db, run_with_routes, pin_today):
    run_with_routes("eu_tariff_xi", xi_routes())
    pin_today(date(2026, 11, 5))
    res = run_with_routes("eu_tariff_xi", xi_routes({
        XI_COMMODITY: _commodity_without("3000107"),
        XI_QUOTA + "099991": (500, b"upstream error"),           # Mexico: no inline definition either
        XI_QUOTA + "099990": (500, b"upstream error"),           # Ukraine: inline definition used instead
    }))
    assert res["status"] == "partial"
    db.expire_all()
    rows = _current(db, "eu_tariff_xi")
    mex = _one(rows, "MEX", "trq_in")
    assert mex.revision == 1 and mex.as_of == TODAY and mex.quota_balance_kg == 1_200_000.0   # untouched
    ua = _one(rows, "UKR", "trq_in")
    assert ua.revision == 2 and ua.quota_balance_kg == 13_500_000.0                           # commodity definition
    assert _one(rows, "VNM", "preference").is_current                                         # not retired this run
    run = db.scalars(select(CollectionRun).order_by(CollectionRun.id.desc())).first()
    assert any("withdrawn measures not checked" in w for w in run.warnings)


def test_xi_group_lookup_failure_skips_only_that_measure(db, run_with_routes, pin_today):
    res = run_with_routes("eu_tariff_xi", xi_routes({XI_GEO_9901: (404, b"not found")}))
    assert res["status"] == "partial"
    rows = _current(db, "eu_tariff_xi")
    assert not _by(rows, "ARG") and _one(rows, "CHL", "preference")
    run = db.scalars(select(CollectionRun).order_by(CollectionRun.id.desc())).first()
    assert any("members of geographical group 9901" in w and "unknown" in w for w in run.warnings)


@pytest.mark.parametrize("routes, message", [
    ({XI_COMMODITY: _commodity_without("3000101")}, "no EU third-country duty"),
    ({XI_COMMODITY: b'{"data": {"type": "commodity", "attributes": {"goods_nomenclature_item_id": "0409000000"}}}'},
     "import_measures"),
    ({XI_COMMODITY: (403, b"Forbidden")}, "refuses anonymous access"),
])
def test_xi_failures_store_nothing(db, run_with_routes, pin_today, routes, message):
    res = run_with_routes("eu_tariff_xi", xi_routes(routes))
    assert res["status"] == "failed" and message in res["error"]
    assert not db.scalars(select(TariffMeasure)).all()


# ---------------------------------------------------------------------------
# US: HTS collector end to end
# ---------------------------------------------------------------------------


def test_hts_end_to_end(db, run_with_routes, pin_today):
    res = run_with_routes("us_hts", hts_routes())
    assert res["status"] in ("success", "partial"), res
    rows = _current(db, "us_hts")
    mfn = _one(rows, "ALL", "mfn")
    assert (mfn.jurisdiction, mfn.hs_code, mfn.measure_code, mfn.duty_text) == ("US", "0409.00.00", "general", "1.9¢/kg")
    assert (mfn.specific_amount, mfn.specific_unit, mfn.specific_currency, mfn.ad_valorem_pct) == (0.019, "kg", "USD", None)
    assert mfn.description == "Natural honey" and mfn.reliability == "official" and mfn.as_of == TODAY
    assert mfn.consult_url == "https://hts.usitc.gov/search?query=0409.00.00"
    assert mfn.extra["column2_text"] == "6.6¢/kg" and mfn.extra["chapter99_footnotes"] == ["9903.88.15"]
    assert "A+" in mfn.extra["special_programs_not_expanded"] and "S" not in mfn.extra["special_programs_not_expanded"]
    assert [s["htsno"] for s in mfn.extra["statistical_suffixes"]] == ["0409.00.00.05", "0409.00.00.10"]
    for origin in ("MEX", "CAN"):
        p = _one(rows, origin, "preference")
        assert (p.measure_code, p.duty_text, p.ad_valorem_pct) == ("special:S", "Free", 0.0)
        assert "USMCA" in p.extra["program_names"][0]
    assert _one(rows, "CHL", "preference").measure_code == "special:CL"
    # Chapter 99
    cn = _one(rows, "CHN", "surcharge")
    assert (cn.measure_code, cn.ad_valorem_pct, cn.extra["needs_review"], cn.extra["footnote_of_0409"]) == \
        ("9903.88.15", 7.5, False, True)
    assert cn.consult_url == "https://hts.usitc.gov/search?query=9903.88.15" and cn.legal_reference == "HTSUS 9903.88.15"
    br = _one(rows, "BRA", "other")
    assert br.extra["needs_review"] is True and br.ad_valorem_pct == 40.0
    all_other = {r.measure_code: r for r in _by(rows, "ALL", "other")}
    assert set(all_other) == {"9903.01.25", "9903.01.29"}
    assert all_other["9903.01.29"].extra["countries_named"] == ["CAN", "MEX"]
    assert all(r.extra["needs_review"] for r in all_other.values())
    codes = {r.measure_code for r in rows.values()}
    assert {"9903.01.27", "9903.01.28", "9903.88.03"}.isdisjoint(codes)
    assert not _by(rows, "JPN")


def test_hts_footnote_heading_outside_ranges_uses_search(db, run_with_routes, pin_today):
    base = fx_json("hts_0409.json")
    base[0]["footnotes"] = [{"columns": ["general"], "value": "See 9903.77.01.", "type": "endnote"}]
    search = [{"htsno": "9903.77.01", "indent": "1", "description": "Articles the product of Vietnam, as provided for "
               "in U.S. note 9 to this subchapter (illustrative)", "general": "The duty provided in the applicable "
               "subheading + 12%", "special": "", "other": "", "footnotes": []}]
    res = run_with_routes("us_hts", hts_routes({HTS_0409: as_bytes(base), HTS_SEARCH + "9903.77.01": as_bytes(search)}))
    assert res["status"] in ("success", "partial")
    rows = _current(db, "us_hts")
    vn = _one(rows, "VNM", "surcharge")
    assert vn.ad_valorem_pct == 12.0 and vn.extra["read_from"] == "search"
    assert not _by(rows, "CHN")                       # 9903.88.15 no longer referenced: not stored


def test_hts_ch99_failure_keeps_base_and_skips_retirement(db, run_with_routes, pin_today):
    run_with_routes("us_hts", hts_routes())
    pin_today(date(2026, 11, 9))
    res = run_with_routes("us_hts", hts_routes({HTS_9903_01: (503, b"down")}))
    assert res["status"] == "partial"
    db.expire_all()
    rows = _current(db, "us_hts")
    assert _one(rows, "ALL", "mfn").as_of == date(2026, 11, 9)
    br = _one(rows, "BRA", "other")
    assert br.is_current and br.as_of == TODAY                # not confirmed, not retired
    run = db.scalars(select(CollectionRun).order_by(CollectionRun.id.desc())).first()
    assert any("withdrawn headings not checked" in w for w in run.warnings)


def test_hts_rate_change_is_a_revision_and_dropped_programme_is_retired(db, run_with_routes, pin_today):
    run_with_routes("us_hts", hts_routes())
    pin_today(date(2026, 11, 9))
    base = fx_json("hts_0409.json")
    base[0]["general"] = "2.0¢/kg"
    base[0]["special"] = "Free (A+,AU,BH,CO,D,E,IL,JO,KR,MA,OM,P,PA,PE,S,SG)"     # CL removed
    run_with_routes("us_hts", hts_routes({HTS_0409: as_bytes(base)}))
    db.expire_all()
    src = _source(db, "us_hts")
    gen = db.scalars(select(TariffMeasure).where(TariffMeasure.source_id == src.id, TariffMeasure.measure_type == "mfn")
                     .order_by(TariffMeasure.revision)).all()
    assert [(g.revision, g.is_current, g.duty_text) for g in gen] == [(1, False, "1.9¢/kg"), (2, True, "2.0¢/kg")]
    cl = db.scalars(select(TariffMeasure).where(TariffMeasure.source_id == src.id, TariffMeasure.origin_iso3 == "CHL")).one()
    assert cl.is_current is False and cl.duty_text == "Free"


@pytest.mark.parametrize("routes, message", [
    ({HTS_0409: b"[]"}, "no row 0409.00.00"),
    ({HTS_0409: b'{"message": "Service unavailable"}'}, "expected a JSON array"),
    ({HTS_0409: as_bytes([{"htsno": "0409.00.00", "indent": "0", "description": "Natural honey", "general": "",
                           "special": "", "other": "", "footnotes": []}])}, "empty 'general'"),
])
def test_hts_drift_stores_nothing(db, run_with_routes, pin_today, routes, message):
    res = run_with_routes("us_hts", hts_routes(routes))
    assert res["status"] == "failed" and message in res["error"]
    assert not db.scalars(select(TariffMeasure)).all()


# ---------------------------------------------------------------------------
# services.tariffs
# ---------------------------------------------------------------------------


def test_record_measure_unchanged_fills_provenance_only(db):
    src = _source(db, "eu_tariff_xi")
    base = dict(jurisdiction="EU", origin_iso3="UKR", hs_code="0409000000", measure_type="preference",
                measure_code="142", duty_text="0.00 %", ad_valorem_pct=0.0, consult_url="https://x/1")
    outcome, row = svc.record_measure(db, source_id=src.id, series_key="k", as_of=TODAY, **base)
    assert outcome == "new" and row.revision == 1
    outcome, same = svc.record_measure(db, source_id=src.id, series_key="k", as_of=date(2026, 11, 3),
                                       **dict(base, consult_url="https://x/old", source_url="https://src"))
    assert outcome == "unchanged" and same.id == row.id
    assert same.as_of == TODAY and same.consult_url == "https://x/1"   # an older check never moves as_of back
    assert same.source_url == "https://src"                               # empty provenance is filled
    outcome, rev = svc.record_measure(db, source_id=src.id, series_key="k", as_of=TODAY, **dict(base, duty_text="2.00 %",
                                                                                                    ad_valorem_pct=2.0))
    assert outcome == "revised" and rev.supersedes_id == row.id and row.is_current is False
    # demo rows live in their own revision chain
    outcome, demo = svc.record_measure(db, source_id=src.id, series_key="k", as_of=TODAY, is_demo=True, **base)
    assert outcome == "new" and demo.is_demo and rev.is_current


def test_ad_case_registry_matches_federal_register_titles():
    assert [c.origin_iso3 for c in svc.ad_cases_for_title(
        "Raw Honey From Argentina, Brazil, India, and the Socialist Republic of Vietnam: Antidumping Duty Orders")] == \
        ["ARG", "BRA", "IND", "VNM"]
    assert [c.case_number for c in svc.ad_cases_for_title(
        "Honey From the People's Republic of China: Final Results of Antidumping Duty Administrative Review")] == ["A-570-863"]
    assert svc.ad_cases_for_title("Raw Honey From Brazil: Final Results of Antidumping Duty Administrative Review; "
                                  "2023-2024")[0].case_number == "A-351-857"
    assert not svc.ad_cases_for_title("Initiation of Antidumping and Countervailing Duty Administrative Reviews")
    assert not svc.ad_cases_for_title("Certain Steel Nails From India: Final Results")
    assert svc.AD_CASE_BY_ORIGIN["IND"].case_number is None          # not invented: read it from the order notice
    assert svc.AD_CASE_BY_ORIGIN["ARG"].fr_search_url.startswith("https://www.federalregister.gov/documents/search?")
    assert svc.quota_fill_pct(None, 1) is None and svc.quota_fill_pct(0, 0) is None
    assert svc.taric_geo("SRB") == "XS" and svc.taric_geo("ERGA_OMNES") == ""
