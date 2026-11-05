"""Supplier quotes (api/quotes.py) and the landed-cost calculator (services/landed_cost.py).

Tariff rows are inserted directly with the values the real collectors stored on 2026-11-04 from the
UK XI mirror of EU TARIC and the USITC HTS (Mercosur quota 090881: 1,722,960 kg, balance 1,304,730 kg,
open; Ukraine quota 096701 exhausted; third-country duty 17.30 %; US general 1.9 ¢/kg; Chapter 99
headings flagged "needs review"). The ECB USD rate 1.1216 is the real reference rate of 2026-11-02.
Market reference rows imitate the shape of the Eurostat / USDA / CCIAA Cuneo rows (values illustrative).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from paladex.models import FxRate, PriceObservation, Source, SupplierQuote, TariffMeasure
from paladex.services import landed_cost as lc

TODAY = date(2026, 11, 4)
RECEIVED = date(2026, 11, 2)
USD = 1.1216


def _src(db, key: str) -> Source:
    return db.scalars(select(Source).where(Source.key == key)).one()


def _fx(db, rates: dict[str, float] | None = None, days=(date(2026, 10, 30), RECEIVED, date(2026, 11, 3), TODAY)):
    rates = rates or {"USD": USD}
    for d in days:
        for ccy, v in rates.items():
            # a different rate on "today", so the received/today switch is visible
            db.add(FxRate(rate_date=d, currency=ccy, per_eur=v if d != TODAY else round(v * 1.01, 4)))
    db.flush()


def _measure(db, key: str, **kw) -> TariffMeasure:
    j = kw["jurisdiction"]
    src = _src(db, "eu_tariff_xi" if j == "EU" else "us_hts")
    defaults = dict(hs_code="0409000000" if j == "EU" else "0409.00.00", as_of=TODAY, data_status="published",
                    reliability="official", value_hash=key, is_current=True, revision=1)
    m = TariffMeasure(source_id=src.id, series_key=key, **{**defaults, **kw})
    db.add(m)
    db.flush()
    return m


@pytest.fixture()
def tariffs(db):
    rows = {
        "eu_mfn": _measure(db, "eu|mfn", jurisdiction="EU", origin_iso3="ERGA_OMNES", measure_type="mfn", measure_code="103",
                           description="Third country duty", duty_text="17.30 %", ad_valorem_pct=17.3,
                           valid_from=date(2005, 1, 1), legal_reference="R2658/87", extra={"needs_review": False}),
        "eu_695": _measure(db, "eu|695", jurisdiction="EU", origin_iso3="ERGA_OMNES", measure_type="surcharge",
                           measure_code="695", description="Additional duties", valid_from=date(2025, 7, 20),
                           extra={"needs_review": True, "review_reason": "the duty depends on the measure conditions",
                                  "excluded_origins": ["BLR", "RUS"]}),
        "arg_trq": _measure(db, "eu|arg|trq", jurisdiction="EU", origin_iso3="ARG", measure_type="trq_in", measure_code="143",
                            description="Preferential tariff quota", duty_text="0.00 %", ad_valorem_pct=0.0,
                            quota_order_number="090881", quota_volume_kg=1_722_960.0, quota_balance_kg=1_304_730.0,
                            quota_status="open", valid_from=date(2026, 5, 1), valid_to=date(2026, 12, 31),
                            legal_reference="R1988/20",
                            extra={"needs_review": False, "geo_area": {"id": "5500", "description": "Mercosur", "group": True},
                                   "quota": {"period_start": "2026-10-01", "period_end": "2026-12-31",
                                             "last_allocation_date": "2026-10-26", "shared_by_group": True}}),
        "ukr_trq": _measure(db, "eu|ukr|trq", jurisdiction="EU", origin_iso3="UKR", measure_type="trq_in", measure_code="143",
                            duty_text="0.00 %", ad_valorem_pct=0.0, quota_order_number="096701",
                            quota_volume_kg=35_000_000.0, quota_balance_kg=0.0, quota_status="exhausted",
                            valid_from=date(2026, 1, 1), valid_to=date(2026, 12, 31), extra={"needs_review": False}),
        "srb_pref": _measure(db, "eu|srb|pref", jurisdiction="EU", origin_iso3="SRB", measure_type="preference",
                             measure_code="142", duty_text="0.00 %", ad_valorem_pct=0.0, valid_from=date(2010, 2, 1),
                             extra={"needs_review": False}),
        "nzl_old": _measure(db, "eu|nzl|old", jurisdiction="EU", origin_iso3="NZL", hs_code="0409000090",
                            measure_type="preference", measure_code="142", duty_text="4.30 %", ad_valorem_pct=4.3,
                            valid_from=date(2025, 1, 1), valid_to=date(2025, 12, 31), extra={"needs_review": False}),
        "us_general": _measure(db, "us|general", jurisdiction="US", origin_iso3="ALL", measure_type="mfn",
                               measure_code="general", description="Natural honey", duty_text="1.9¢/kg",
                               specific_amount=0.019, specific_unit="kg", specific_currency="USD",
                               extra={"needs_review": False, "special_text": "Free (A+,AU,BH,CL,CO,D,E, IL,JO,KR,MA,OM,P,PA,PE,S, SG)",
                                      "column2_text": "6.6¢/kg"}),
        "us_ch99_all": _measure(db, "us|9903.01.25", jurisdiction="US", origin_iso3="ALL", measure_type="other",
                                measure_code="9903.01.25", duty_text="The duty provided in the applicable subheading + 10%",
                                ad_valorem_pct=10.0, extra={"needs_review": True, "review_reason": "heading not referenced by 0409.00.00"}),
        # published for all origins, but its text names China and Hong Kong only
        "us_ch99_chn": _measure(db, "us|9903.01.20", jurisdiction="US", origin_iso3="ALL", measure_type="other",
                                measure_code="9903.01.20", duty_text="The duty provided in the applicable subheading + 10%",
                                ad_valorem_pct=10.0, extra={"needs_review": True, "country_scope": "multiple",
                                                            "countries_named": ["CHN", "HKG"]}),
        "us_ch99_vnm": _measure(db, "us|9903.01.72", jurisdiction="US", origin_iso3="VNM", measure_type="other",
                                measure_code="9903.01.72", ad_valorem_pct=46.0, duty_text="+ 46%",
                                extra={"needs_review": True}),
        "us_mex_pref": _measure(db, "us|mex|S", jurisdiction="US", origin_iso3="MEX", measure_type="preference",
                                measure_code="special:S", duty_text="Free", ad_valorem_pct=0.0,
                                extra={"needs_review": False, "program_codes": ["S"], "program_names": ["USMCA"]}),
    }
    _fx(db, {"USD": USD, "CNY": 8.0})
    db.commit()   # the API tests read through their own session
    return rows


def calc(db, **kw):
    base = dict(origin_iso3="ARG", variety="polyflora", price=3.0, currency="USD", date_received=RECEIVED)
    return lc.calculate(db, lc.QuoteInput(**{**base, **kw}), today=TODAY)


def by_kind(res, kind):
    return next(s for s in res["scenarios"] if s["kind"] == kind)


def line(res, key):
    return next(x for x in res["lines"] + res["after_duty"] if x["key"] == key)


def codes(res, kind=None):
    return [f["code"] for f in res["flags"] if kind is None or f["kind"] == kind]


# ---------------------------------------------------------------------------
# Calculator
# ---------------------------------------------------------------------------


def test_argentina_fob_into_italy_returns_quota_and_full_duty_alternatives(db, tariffs):
    res = calc(db, incoterm="FOB", quantity_kg=20_000, shipping_cost=2500, shipping_cost_currency="USD",
               shipping_cost_basis="per_container", insurance_pct=0.3)
    goods = 3.0 / USD
    freight = 2500 / 20_000 / USD
    ins = (goods + freight) * 0.003 / 0.997
    cif = goods + freight + ins
    assert line(res, "goods")["per_kg"]["eur"] == pytest.approx(goods, abs=1e-6)
    assert line(res, "goods")["fx"] == {"currency": "USD", "per_eur": USD, "rate_date": "2026-11-02", "missing": False}
    assert line(res, "freight")["input"]["containers"] == 1
    assert line(res, "insurance")["per_kg"]["eur"] == pytest.approx(ins, abs=1e-6)
    assert line(res, "customs_value")["per_kg"]["eur"] == pytest.approx(cif, abs=1e-6)

    trq, mfn = by_kind(res, "trq_in"), by_kind(res, "mfn")
    assert (trq["role"], trq["available"]) == ("in_quota", True)
    assert trq["measure"]["quota"]["balance_kg"] == 1_304_730.0
    assert trq["measure"]["quota"]["order_number"] == "090881"
    assert trq["total"]["per_kg"]["eur"] == pytest.approx(cif, abs=1e-6)
    assert mfn["role"] == "out_of_quota"
    assert mfn["duty"]["eur"] == pytest.approx(cif * 0.173, abs=1e-6)
    assert mfn["total"]["per_kg"]["eur"] == pytest.approx(cif * 1.173, abs=1e-6)
    assert mfn["total"]["per_drum"]["eur"] == pytest.approx(cif * 1.173 * 300, abs=1e-4)
    assert mfn["total"]["per_container"]["usd"] == pytest.approx(cif * 1.173 * USD * 20_000, abs=1e-2)
    # Nothing is chosen silently: both alternatives are in the headline range
    h = res["headline"]
    assert h["alternatives"] is True and h["complete"] is True
    assert h["eur_per_kg_min"] == pytest.approx(cif, abs=1e-6)
    assert h["eur_per_kg_max"] == pytest.approx(cif * 1.173, abs=1e-6)
    assert "quota_alternatives" in codes(res, "info")
    # the additional-duty layer needing review is listed, never applied
    assert [m["measure_code"] for m in res["duty"]["review"]] == ["695"]
    assert res["duty"]["as_of"] == "2026-11-04"
    assert "Area=AR" in res["duty"]["links"]["taric"]


def test_exhausted_quota_is_shown_unavailable_and_the_full_duty_applies(db, tariffs):
    res = calc(db, origin_iso3="UKR", variety="sunflower", price=2.35, currency="EUR", incoterm="CIF")
    trq = by_kind(res, "trq_in")
    assert trq["available"] is False and trq["unavailable_reason"] == "exhausted"
    mfn = by_kind(res, "mfn")
    assert mfn["total"]["per_kg"]["eur"] == pytest.approx(2.35 * 1.173)
    assert res["headline"]["alternatives"] is False
    assert res["headline"]["eur_per_kg_min"] == res["headline"]["eur_per_kg_max"] == pytest.approx(2.35 * 1.173)
    assert "quota_unavailable" in codes(res, "warning")
    # CIF: freight and insurance are in the price, nothing missing
    assert line(res, "freight")["status"] == "included" and line(res, "insurance")["status"] == "included"
    assert res["headline"]["complete"] is True


def test_quota_balance_below_quantity_is_a_warning(db, tariffs):
    res = calc(db, incoterm="CIF", quantity_kg=1_500_000)
    assert "quota_balance_below_quantity" in codes(res, "warning")
    assert by_kind(res, "trq_in")["available"] is True


def test_preference_applies_with_proof_of_origin_note_and_expired_measures_are_ignored(db, tariffs):
    res = calc(db, origin_iso3="SRB", variety="acacia", price=5.3, currency="EUR", incoterm="DAP")
    [s] = res["scenarios"]
    assert s["kind"] == "preference" and s["duty"]["eur"] == 0
    assert s["notes"][0]["code"] == "proof_of_origin"
    assert s["notes"][0]["params"]["mfn"]["ad_valorem_pct"] == 17.3
    assert "dap_customs_value" in codes(res, "info")
    # NZL's 4.3 % preference expired on 2025-12-31: the general duty applies, not the old rate
    nz = calc(db, origin_iso3="NZL", price=6.0, currency="EUR", incoterm="CIF")
    assert [s["kind"] for s in nz["scenarios"]] == ["mfn"]


def test_incoterm_adds_only_what_the_price_does_not_include(db, tariffs):
    common = dict(quantity_kg=20_000, shipping_cost=2500, shipping_cost_currency="USD", shipping_cost_basis="per_container",
                  insurance_pct=0.3)
    cif = calc(db, incoterm="CIF", **common)
    assert line(cif, "freight")["status"] == "included"
    assert line(cif, "freight")["per_kg"]["eur"] == 0
    assert "freight_ignored" in codes(cif, "info")
    assert line(cif, "customs_value")["per_kg"]["usd"] == pytest.approx(3.0)

    cfr = calc(db, incoterm="CFR", **common)
    assert line(cfr, "freight")["status"] == "included"
    assert line(cfr, "insurance")["status"] == "ok"
    assert line(cfr, "insurance")["per_kg"]["usd"] == pytest.approx(3.0 * 0.003 / 0.997, abs=1e-6)

    ddp = calc(db, incoterm="DDP", **common, duty_pct=12)
    [s] = ddp["scenarios"]
    assert s["kind"] == "included" and s["total"]["per_kg"]["usd"] == pytest.approx(3.0)
    assert "duty_override_ignored" in codes(ddp, "info")

    exw = calc(db, incoterm="EXW", **common)
    assert "origin_costs_missing" in codes(exw, "missing")
    exw2 = calc(db, incoterm="EXW", **common,
                cost_items=[lc.CostItem(kind="origin", amount=400, currency="USD", basis="per_container")])
    assert "origin_costs_missing" not in codes(exw2)
    # origin costs are part of the EU customs value (before the border)
    assert line(exw2, "customs_value")["per_kg"]["usd"] == pytest.approx(
        line(exw, "customs_value")["per_kg"]["usd"] + 400 / 20_000 * (1 + 0.003 / 0.997), abs=1e-6)

    none = calc(db)
    assert {"incoterm_missing", "freight_missing", "insurance_missing"} <= set(codes(none, "missing"))

    # an insurance % typed for a CIF price is shown but not added (the price already includes it)
    assert line(cif, "insurance")["status"] == "included" and line(cif, "insurance")["input"]["pct"] == 0.3
    assert "insurance_ignored" in codes(cif, "info")
    assert by_kind(cif, "trq_in")["total"]["per_kg"]["usd"] == pytest.approx(3.0)


def test_insurance_and_freight_are_never_assumed(db, tariffs):
    res = calc(db, incoterm="FOB")
    assert line(res, "insurance") == {"key": "insurance", "status": "missing", "per_kg": None, "input": None,
                                      "source": None, "fx": None}
    assert line(res, "freight")["status"] == "missing"
    assert res["headline"]["complete"] is False
    assert set(res["headline"]["missing"]) == {"freight_missing", "insurance_missing"}
    # computed without them: goods + duty only
    assert by_kind(res, "mfn")["total"]["per_kg"]["usd"] == pytest.approx(3.0 * 1.173)


def test_price_per_pound_containers_and_cost_bases(db, tariffs):
    res = calc(db, price=1.36, price_unit="lb", incoterm="CFR", insurance_pct=0.5, quantity_kg=30_000,
               cost_items=[lc.CostItem(kind="port", amount=350, currency="EUR", basis="per_container"),
                           lc.CostItem(kind="broker", amount=600, currency="EUR", basis="total"),
                           lc.CostItem(kind="inland", amount=0.02, currency="EUR", basis="per_kg"),
                           lc.CostItem(kind="bank", amount=0.2, basis="pct_goods")])
    per_kg = 1.36 / lc.LB_KG
    assert line(res, "goods")["input"]["per_kg_original"] == pytest.approx(per_kg, abs=1e-6)
    port = line(res, "port")
    assert port["input"]["containers"] == 2   # 30 t -> two 20 t containers
    assert port["per_kg"]["eur"] == pytest.approx(350 * 2 / 30_000, abs=1e-6)
    assert line(res, "broker")["per_kg"]["eur"] == pytest.approx(600 / 30_000, abs=1e-6)
    assert line(res, "inland")["per_kg"]["eur"] == pytest.approx(0.02)
    assert line(res, "bank")["per_kg"]["usd"] == pytest.approx(per_kg * 0.002, abs=1e-6)
    assert res["assumptions"]["containers"] == 2
    trq = by_kind(res, "trq_in")
    expected = line(res, "customs_value")["per_kg"]["eur"] + 350 * 2 / 30_000 + 600 / 30_000 + 0.02 + per_kg / USD * 0.002
    assert trq["total"]["per_kg"]["eur"] == pytest.approx(expected, abs=1e-6)
    assert trq["total"]["quantity"]["eur"] == pytest.approx(expected * 30_000, abs=1e-2)

    # a total amount needs the quantity: not computable, flagged, never spread on a guessed weight
    nq = calc(db, incoterm="CIF", cost_items=[lc.CostItem(kind="broker", amount=600, currency="EUR", basis="total")])
    assert line(nq, "broker")["status"] == "not_computable"
    assert "cost_no_quantity" in codes(nq, "missing")
    assert next(f for f in nq["flags"] if f["code"] == "cost_no_quantity")["params"] == {"cost": "broker"}
    assert nq["headline"]["complete"] is False


def test_fx_uses_the_ecb_rate_of_the_chosen_date_and_never_guesses(db, tariffs):
    received = calc(db, incoterm="CIF")
    today = lc.calculate(db, lc.QuoteInput(origin_iso3="ARG", variety="polyflora", price=3.0, currency="USD",
                                           date_received=RECEIVED, incoterm="CIF"), fx_mode="today", today=TODAY)
    assert received["fx"]["rates"] == [{"currency": "USD", "per_eur": USD, "rate_date": "2026-11-02"}]
    assert today["fx"]["rates"][0]["rate_date"] == "2026-11-04"
    assert line(today, "goods")["per_kg"]["eur"] == pytest.approx(3.0 / round(USD * 1.01, 4))
    # a currency without an ECB rate: the EUR amount is unknown, never estimated
    res = calc(db, currency="ARS", price=3000.0, incoterm="CIF")
    assert line(res, "goods")["per_kg"] == {"eur": None, "usd": None}
    assert "fx_missing" in codes(res, "missing")
    assert res["fx"]["missing"] == ["ARS"]
    assert res["headline"]["eur_per_kg_min"] is None
    # a quote older than the stored rates (more than 14 days back): no conversion either
    old = calc(db, date_received=date(2026, 9, 1), incoterm="CIF")
    assert old["fx"]["missing"] == ["USD"] and line(old, "goods")["per_kg"] == {"eur": None, "usd": 3.0}


def test_us_destination_general_rate_and_explicit_warnings(db, tariffs):
    res = calc(db, destination="USA", incoterm="CFR", insurance_pct=0.3)
    [s] = res["scenarios"]
    assert s["kind"] == "mfn" and s["rate"]["specific_amount"] == 0.019
    assert s["duty"]["usd"] == pytest.approx(0.019)
    assert res["jurisdiction"] == "US"
    assert "us_value_includes_freight" in codes(res, "info")
    # anti-dumping (Argentina) and Chapter 99: warnings with links, never a rate
    assert {"us_antidumping", "us_additional_duty_review"} <= set(codes(res, "warning"))
    assert res["duty"]["ad_case"]["case_number"] == "A-357-823"
    assert res["duty"]["ad_case"]["fr_search_url"].startswith("https://www.federalregister.gov/")
    assert [m["measure_code"] for m in res["duty"]["review"]] == ["9903.01.25"]
    assert res["duty"]["us"]["column2_text"] == "6.6¢/kg"
    assert res["headline"]["usd_per_kg_max"] == pytest.approx(3.0 * (1 + 0.003 / 0.997) + 0.019)

    # a heading naming other countries only is not listed for this origin (only counted)
    assert res["duty"]["review_other_origins"] == 1
    chn = calc(db, origin_iso3="CHN", destination="USA", incoterm="CIF")
    assert sorted(m["measure_code"] for m in chn["duty"]["review"]) == ["9903.01.20", "9903.01.25"]
    assert chn["duty"]["review_other_origins"] == 0

    vnm = calc(db, origin_iso3="VNM", destination="USA", incoterm="CIF")
    assert sorted(m["measure_code"] for m in vnm["duty"]["review"]) == ["9903.01.25", "9903.01.72"]
    assert "us_antidumping" in codes(vnm, "warning")

    mex = calc(db, origin_iso3="MEX", destination="USA", incoterm="CIF")
    [p] = mex["scenarios"]
    assert p["kind"] == "preference" and p["duty"]["usd"] == 0
    assert p["notes"][0]["code"] == "program_certification" and p["notes"][0]["params"]["codes"] == ["S"]
    assert "us_antidumping" not in codes(mex)

    usa = calc(db, origin_iso3="USA", destination="USA", incoterm="DAP")
    assert [s["kind"] for s in usa["scenarios"]] == ["domestic"]


def test_user_duty_replaces_the_automatic_duty(db, tariffs):
    res = calc(db, incoterm="CIF", duty_pct=5)
    [s] = res["scenarios"]
    assert s["kind"] == "override" and s["rate"]["ad_valorem_pct"] == 5
    assert s["total"]["per_kg"]["usd"] == pytest.approx(3.15)
    assert "duty_override" in codes(res, "info")
    # the official measures stay listed for reference
    assert {m["measure_type"] for m in res["duty"]["applied"]} == {"trq_in", "mfn"}


def test_origins_without_data_or_inside_the_eu(db, tariffs):
    eth = calc(db, origin_iso3="ETH", incoterm="CIF")
    assert [s["kind"] for s in eth["scenarios"]] == ["mfn"]
    assert "origin_not_covered" in codes(eth, "warning")
    hun = calc(db, origin_iso3="HUN", variety="acacia", price=6.0, currency="EUR", incoterm="DAP")
    assert [s["kind"] for s in hun["scenarios"]] == ["domestic"]
    assert hun["scenarios"][0]["total"]["per_kg"]["eur"] == 6.0


def test_no_tariff_data_means_duty_not_available(db):
    _fx(db)
    res = calc(db, incoterm="CIF")
    [s] = res["scenarios"]
    assert s["kind"] == "unknown" and s["duty"] is None and s["total"] is None
    assert "duty_unavailable" in codes(res, "missing")
    assert res["headline"]["eur_per_kg_min"] is None


def _price(db, key, **kw):
    src = _src(db, key)
    defaults = dict(source_id=src.id, series_key=f"{key}|{kw.get('market_iso3')}|{kw.get('period_label')}|{kw.get('color_grade')}",
                    value_hash="x", frequency="M", data_status="published", reliability="official", currency="EUR",
                    unit="kg", is_current=True)
    p = PriceObservation(**{**defaults, **kw})
    p.price_per_kg = p.price_per_kg if p.price_per_kg is not None else p.price_value
    db.add(p)
    db.flush()
    return p


def test_market_reference_keeps_each_price_type_apart(db):
    m = lambda y, mo: (date(y, mo, 1), date(y, mo, 28))  # noqa: E731
    for market, period, v in (("ITA", (2026, 7), 2.39), ("ITA", (2026, 6), 2.20), ("EU27", (2026, 8), 2.50)):
        s, e = m(*period)
        _price(db, "eurostat_comext", price_type="import_unit_value", origin_iso3="ARG", market_iso3=market,
               variety="unspecified", price_value=v, eur_per_kg=v, period_start=s, period_end=e,
               period_label=f"{period[0]}-{period[1]:02d}", terms="CIF")
    s, e = m(2026, 9)
    for color, v in (("white", 1.795), ("light amber", 1.77)):
        _price(db, "usda_honey_report", price_type="wholesale_bulk", origin_iso3="ARG", market_iso3="USA",
               variety="polyflora", color_grade=color, price_value=v, currency="USD", unit="lb",
               price_per_kg=v / lc.LB_KG, usd_per_kg=v / lc.LB_KG, period_start=s, period_end=e, period_label="2026-09")
    _price(db, "usda_honey_report", price_type="wholesale_bulk", origin_iso3="ARG", market_iso3="USA",
           variety="sunflower", price_value=1.6, currency="USD", unit="lb", period_start=date(2025, 8, 1),
           period_end=date(2025, 8, 31), period_label="2025-08")
    _price(db, "cciaa_cuneo_miele", price_type="wholesale_bulk", origin_iso3="ITA", market_iso3="ITA",
           variety="polyflora", price_value=5.0, price_low=4.5, price_high=5.5, period_start=s, period_end=e,
           period_label="2026-09", reliability="industry")
    # demo rows never appear next to a real quote
    demo = _src(db, "demo")
    db.add(PriceObservation(source_id=demo.id, series_key="demo", value_hash="d", price_type="wholesale_bulk",
                            origin_iso3="ITA", market_iso3="ITA", variety="polyflora", price_value=99, price_per_kg=99,
                            currency="EUR", unit="kg", period_start=date(2026, 10, 1), period_end=date(2026, 10, 31),
                            period_label="2026-10", frequency="M", data_status="demo", reliability="demo", is_demo=True))
    db.flush()

    ref = lc.market_reference(db, "ARG", "polyflora", today=TODAY)
    blocks = {b["key"]: b for b in ref["blocks"]}
    eu = blocks["eu_import"]["rows"]
    assert [(r["market_iso3"], r["period_label"]) for r in eu] == [("ITA", "2026-07"), ("EU27", "2026-08")]
    assert all(r["price_type"] == "import_unit_value" and r["source"]["key"] == "eurostat_comext" for r in eu)
    us = blocks["us_importer"]["rows"]
    assert {r["color_grade"] for r in us} == {"white", "light amber"} and all(r["variety_match"] for r in us)
    assert all(r["unit"] == "lb" and r["period_label"] == "2026-09" for r in us)
    it = blocks["it_wholesale"]["rows"]
    assert [(r["source"]["key"], r["price_value"], r["is_demo"]) for r in it] == [("cciaa_cuneo_miele", 5.0, False)]
    assert it[0]["age_days"] == (TODAY - e).days

    # a variety USDA does not publish for the origin: the origin's latest rows, flagged
    acacia = {b["key"]: b for b in lc.market_reference(db, "ARG", "acacia", today=TODAY)["blocks"]}
    assert acacia["us_importer"]["variety_match"] is False
    assert all(not r["variety_match"] for r in acacia["us_importer"]["rows"])
    assert acacia["it_wholesale"]["rows"] == []
    # an EU origin has no extra-EU import unit value
    hun = {b["key"]: b for b in lc.market_reference(db, "HUN", "acacia", today=TODAY)["blocks"]}
    assert hun["eu_import"]["not_applicable"] is True and hun["eu_import"]["rows"] == []
    # generic buckets are never matched to a price-list line of the same bucket
    other = {b["key"]: b for b in lc.market_reference(db, "ARG", "other", today=TODAY)["blocks"]}
    assert other["it_wholesale"]["variety_generic"] is True and other["it_wholesale"]["rows"] == []
    assert other["us_importer"]["variety_match"] is False


def test_market_reference_skips_customs_unit_values_of_small_consignments(db):
    for period, v, kg in (((2026, 6), 2.31, 120_000.0), ((2026, 7), 9.80, 600.0)):
        s, e = date(*period, 1), date(*period, 28)
        _price(db, "eurostat_comext", price_type="import_unit_value", origin_iso3="URY", market_iso3="ITA",
               variety="unspecified", price_value=v, eur_per_kg=v, volume_kg=kg, period_start=s, period_end=e,
               period_label=f"{period[0]}-{period[1]:02d}", terms="CIF")
    blocks = {b["key"]: b for b in lc.market_reference(db, "URY", "eucalyptus", today=TODAY)["blocks"]}
    # 600 kg in July (a sample, a few drums) is not a bulk price: the latest bulk month is shown
    assert [(r["period_label"], r["volume_kg"]) for r in blocks["eu_import"]["rows"]] == [("2026-06", 120_000.0)]
    assert blocks["eu_import"]["min_volume_kg"] == 10_000


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@pytest.fixture()
def pin(monkeypatch):
    from paladex.api import quotes

    monkeypatch.setattr(quotes, "today", lambda: TODAY)


def body(**kw) -> dict:
    b = {"supplier_name": "Exportadora Pampa SA", "origin_iso3": "ARG", "variety": "polyflora", "price": 3.0,
         "currency": "USD", "incoterm": "FOB", "quantity_kg": 20000, "packaging": "fusti metallici da 300 kg",
         "shipping_cost": 2500, "shipping_cost_currency": "USD", "shipping_cost_basis": "per_container",
         "date_received": RECEIVED.isoformat(), "valid_until": "2026-11-30"}
    return {**b, **kw}


def test_crud_keeps_history_fields_and_never_deletes(api, db, tariffs, pin):
    r = api.post("/api/quotes", json=body(price=1.36, price_unit="lb", cost_items=[
        {"kind": "port", "amount": 350, "currency": "eur", "basis": "per_container", "note": " THC Genova "}]))
    assert r.status_code == 201, r.text
    q = r.json()
    assert q["price"] == 1.36 and q["price_unit"] == "lb"
    assert q["price_per_kg"] == pytest.approx(1.36 / lc.LB_KG, abs=1e-6)
    assert q["cost_items"] == [{"kind": "port", "amount": 350.0, "basis": "per_container", "currency": "EUR", "note": "THC Genova"}]
    assert q["data_status"] == "user_entered" and q["is_demo"] is False and q["status"] == "active"
    qid = q["id"]

    row = db.get(SupplierQuote, qid)
    row.updated_at = datetime(2026, 11, 3, 8, 0)
    db.commit()
    r = api.put(f"/api/quotes/{qid}", json=body(price=3.1, notes="Prezzo rivisto"))
    assert r.status_code == 200
    upd = r.json()
    assert upd["created_at"] == q["created_at"]
    assert upd["updated_at"] > "2026-11-03T08:00:00"
    assert upd["price"] == 3.1 and upd["price_unit"] == "kg" and upd["notes"] == "Prezzo rivisto"

    assert api.post(f"/api/quotes/{qid}/archive").json()["status"] == "archived"
    assert api.post(f"/api/quotes/{qid}/unarchive").json()["status"] == "active"
    dup = api.post(f"/api/quotes/{qid}/duplicate")
    assert dup.status_code == 201
    d = dup.json()
    assert d["id"] != qid and d["supplier_name"] == upd["supplier_name"] and d["price"] == 3.1 and not d["archived"]

    # no route deletes a quote
    assert api.delete(f"/api/quotes/{qid}").status_code == 405
    assert db.get(SupplierQuote, qid) is not None
    assert api.get("/api/quotes/99999").status_code == 404


def test_detail_has_landed_cost_market_reference_and_ad_documents(api, db, tariffs, pin):
    from paladex.models import RegulationItem

    fr = _src(db, "us_federal_register")
    db.add(RegulationItem(source_id=fr.id, jurisdiction="US", doc_type="antidumping", reference="2099-1",
                          title="Raw Honey From Argentina: Final Results of Antidumping Duty Administrative Review",
                          published_at=date(2026, 6, 1), url="https://www.federalregister.gov/d/2099-1"))
    db.commit()
    qid = api.post("/api/quotes", json=body(destination="USA")).json()["id"]
    d = api.get(f"/api/quotes/{qid}").json()
    assert d["quote"]["destination"] == "USA"
    assert d["landed"]["duty"]["ad_case"]["documents_total"] == 1
    assert d["landed"]["duty"]["ad_case"]["documents"][0]["url"] == "https://www.federalregister.gov/d/2099-1"
    assert {b["key"] for b in d["market"]["blocks"]} == {"eu_import", "us_importer", "it_wholesale"}
    t = api.get(f"/api/quotes/{qid}", params={"fx": "today"}).json()
    assert t["landed"]["fx"]["date"] == "2026-11-04"
    assert api.get(f"/api/quotes/{qid}", params={"fx": "yesterday"}).status_code == 422
    assert api.get(f"/api/quotes/{qid}", params={"container_kg": 50}).status_code == 422


def test_validation(api, db, pin):
    def bad(**kw):
        r = api.post("/api/quotes", json=body(**kw))
        assert r.status_code == 422, (kw, r.text)

    bad(date_received="2026-11-05")                       # in the future
    bad(valid_until="2026-11-01")                         # before the date received
    bad(origin_iso3="XXX")
    bad(variety="truffle")
    bad(price=0)
    bad(price=-2)
    bad(currency="dollars")
    bad(incoterm="FAS")
    bad(shipping_cost_currency=None)
    bad(shipping_cost_basis=None)
    bad(insurance_pct=40)
    bad(supplier_name="   ")
    bad(cost_items=[{"kind": "port", "amount": 100, "basis": "per_container"}])          # no currency
    bad(cost_items=[{"kind": "bank", "amount": 150, "basis": "pct_goods"}])             # > 100 %
    bad(cost_items=[{"kind": "x", "amount": 1, "basis": "per_kg", "currency": "EUR"}])
    bad(price=2_000_000)
    # a price in a currency with small units (HUF, IDR ...) is accepted
    assert api.post("/api/quotes", json=body(price=1450, currency="HUF")).status_code == 201
    ok = api.post("/api/quotes", json=body(shipping_cost=None, shipping_cost_currency="USD", shipping_cost_basis="total"))
    assert ok.status_code == 201
    assert ok.json()["shipping_cost_currency"] is None and ok.json()["shipping_cost_basis"] is None


def _quote(db, **kw) -> SupplierQuote:
    d = dict(supplier_name="S", origin_iso3="ARG", variety="polyflora", price_per_kg=3.0, currency="USD",
             incoterm="CIF", date_received=RECEIVED)
    m = SupplierQuote(**{**d, **kw})
    db.add(m)
    db.commit()
    return m


def test_list_status_filters_counts_and_landed_cost(api, db, tariffs, pin):
    a = _quote(db, supplier_name="Apis Pampa", valid_until=TODAY + timedelta(days=30))
    b = _quote(db, supplier_name="Bee Ukraine", origin_iso3="UKR", variety="sunflower", valid_until=TODAY + timedelta(days=7),
               notes="contratto quadro")
    c = _quote(db, supplier_name="Cerro Azul", valid_until=TODAY - timedelta(days=1))
    d = _quote(db, supplier_name="Delta Honey", origin_iso3="VNM", archived=True)
    e = _quote(db, supplier_name="Eagle", origin_iso3="SRB", variety="acacia", valid_until=TODAY)

    r = api.get("/api/quotes").json()
    status = {i["id"]: i["status"] for i in r["items"]}
    assert status == {a.id: "active", b.id: "expiring", c.id: "expired", e.id: "expiring"}   # archived hidden by default
    assert r["counts"] == {"active": 1, "expiring": 2, "expired": 1, "archived": 1}
    item = next(i for i in r["items"] if i["id"] == a.id)
    assert item["landed"]["headline"]["alternatives"] is True
    assert {s["kind"] for s in item["landed"]["scenarios"]} == {"trq_in", "mfn"}
    assert next(i for i in r["items"] if i["id"] == b.id)["days_to_expiry"] == 7

    ids = lambda **p: sorted(i["id"] for i in api.get("/api/quotes", params=p).json()["items"])  # noqa: E731
    assert ids(status="archived") == [d.id]
    assert ids(status="active,expiring") == sorted([a.id, b.id, e.id])
    assert ids(status="all") == sorted([a.id, b.id, c.id, d.id, e.id])
    assert ids(origin="ukr") == [b.id]
    assert ids(variety="acacia") == [e.id]
    assert ids(supplier="apis pampa") == [a.id]
    assert ids(q="quadro") == [b.id]
    assert ids(q="100%") == []
    assert api.get("/api/quotes", params={"status": "open"}).status_code == 422
    # the ECB rate of today instead of the date received, on request
    t = api.get("/api/quotes", params={"fx": "today"}).json()
    assert t["fx_mode"] == "today"
    assert next(i for i in t["items"] if i["id"] == a.id)["landed"]["fx"]["date"] == TODAY.isoformat()
    assert item["landed"]["fx"]["date"] == RECEIVED.isoformat()
    assert api.get("/api/quotes", params={"fx": "tomorrow"}).status_code == 422
    facets = api.get("/api/quotes").json()["facets"]
    assert {f["key"] for f in facets["origins"]} == {"ARG", "UKR", "VNM", "SRB"}


def test_compare_ranks_by_landed_eur_per_kg(api, db, tariffs, pin):
    arg = _quote(db, supplier_name="ARG CIF 3.00", price_per_kg=3.0)                     # 0 % in quota / 17.3 % out
    ukr = _quote(db, supplier_name="UKR CIF 2.60", origin_iso3="UKR", price_per_kg=2.6)  # quota exhausted: 17.3 %
    srb = _quote(db, supplier_name="SRB CIF 2.90", origin_iso3="SRB", price_per_kg=2.9)  # preference 0 %

    r = api.get("/api/quotes/compare", params={"ids": f"{arg.id},{ukr.id},{srb.id}"}).json()
    order = [x["quote"]["id"] for x in r["items"]]
    assert order == [srb.id, ukr.id, arg.id]          # conservative: ARG counted out of quota
    assert r["best_id"] == srb.id
    first, second, third = r["items"]
    assert first["rank"] == 1 and first["diff_eur_per_kg"] == 0
    assert second["value_usd_per_kg"] == pytest.approx(2.6 * 1.173)
    assert second["diff_eur_per_kg"] == pytest.approx((2.6 * 1.173 - 2.9) / USD, abs=1e-6)
    assert second["diff_eur_per_container"] == pytest.approx((2.6 * 1.173 - 2.9) / USD * 20_000, abs=0.05)
    assert third["scenario"]["kind"] == "mfn"

    best = api.get("/api/quotes/compare", params={"ids": f"{arg.id},{ukr.id},{srb.id}", "basis": "best"}).json()
    assert [x["quote"]["id"] for x in best["items"]] == [srb.id, ukr.id, arg.id] or best["items"][0]["quote"]["id"] == srb.id
    arg_best = next(x for x in best["items"] if x["quote"]["id"] == arg.id)
    assert arg_best["scenario"]["kind"] == "trq_in" and arg_best["value_usd_per_kg"] == pytest.approx(3.0)

    assert api.get("/api/quotes/compare", params={"ids": str(arg.id)}).status_code == 422
    assert api.get("/api/quotes/compare", params={"ids": ",".join(str(i) for i in range(1, 8))}).status_code == 422
    assert api.get("/api/quotes/compare", params={"ids": "a,b"}).status_code == 422
    assert api.get("/api/quotes/compare", params={"ids": f"{arg.id},99999"}).status_code == 404


def test_calculate_endpoint_for_unsaved_quotes(api, db, tariffs, pin):
    r = api.post("/api/quotes/calculate", json=body(supplier_name=None, insurance_pct=0.3))
    assert r.status_code == 200
    assert {s["kind"] for s in r.json()["scenarios"]} == {"trq_in", "mfn"}
    assert api.post("/api/quotes/calculate", json=body(price=0)).status_code == 422
    assert api.post("/api/quotes/calculate", json=body(), params={"container_kg": 22000}).json()["assumptions"]["container_kg"] == 22000


def test_csv_export_is_italian_excel_friendly(api, db, tariffs, pin):
    _quote(db, supplier_name="=HYPERLINK(\"x\")", price_per_kg=3.0, quantity_kg=20000, notes="Nota; con punto e virgola",
           cost_items=[{"kind": "port", "amount": 350, "currency": "EUR", "basis": "per_container"}])
    r = api.get("/api/quotes/export", params={"lang": "it"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "paladex-offerte-fornitori-" in r.headers["content-disposition"]
    text = r.content.decode("utf-8")
    assert text.startswith("﻿")
    header, row = text.lstrip("﻿").split("\r\n")[:2]
    assert header.split(";")[:3] == ["N.", "Fornitore", "Origine"]
    assert "'=HYPERLINK" in row                       # formula neutralised
    assert ";Argentina;Millefiori;" in row
    assert ";3;USD;kg;" in row
    assert "Porto / terminal: 350 EUR per container" in row
    assert "\"Nota; con punto e virgola\"" in row
    assert "Contingente 090881: 0 %" in row and "Dazio pieno (paesi terzi): 17,3 %" in row
    assert "1 EUR = 1,1216 USD (2026-11-02)" in row
    en = api.get("/api/quotes/export", params={"lang": "en"}).content.decode("utf-8")
    assert en.lstrip("﻿").split("\r\n")[0].split(",")[:2] == ["No.", "Supplier"]


def test_demo_quotes_are_isolated(api, db, tariffs, pin):
    from paladex.services.demo import seed_demo

    _quote(db, supplier_name="Real supplier")
    seed_demo(db, months=2, today=RECEIVED)
    db.commit()
    names = [i["supplier_name"] for i in api.get("/api/quotes").json()["items"]]
    assert names == ["Real supplier"]
    demo_id = db.scalars(select(SupplierQuote.id).where(SupplierQuote.is_demo.is_(True))).first()
    assert api.get(f"/api/quotes/{demo_id}").status_code == 404
    assert api.put("/api/settings", json={"show_demo": True}).status_code == 200
    items = api.get("/api/quotes").json()["items"]
    assert len(items) == 4 and sum(i["is_demo"] for i in items) == 3
    assert all(i["data_status"] == "demo" for i in items if i["is_demo"])
    # a demo quote stays demo when copied; a new quote is never demo
    dup = api.post(f"/api/quotes/{demo_id}/duplicate").json()
    assert dup["is_demo"] is True
    assert api.post("/api/quotes", json={**body(), "is_demo": True}).json()["is_demo"] is False
    csv_text = api.get("/api/quotes/export", params={"lang": "it"}).content.decode("utf-8")
    assert "SÌ — NON REALE" in csv_text
