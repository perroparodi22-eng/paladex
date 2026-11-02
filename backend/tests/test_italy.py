"""Italian honey sources (paladex.collectors.italy).

Fixtures in tests/fixtures/italy/ are RECONSTRUCTED from docs/research/italy.json (see the
README there), not captured from the live sites.
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from conftest import fixture_bytes
from paladex.collectors import italy as it
from paladex.collectors.base import CollectorError
from paladex.models import PriceObservation, Report, Source
from paladex.services import ingest

CUNEO_INDEX = it.CUNEO_INDEX_URL
CUNEO_HTML_15948 = it.CUNEO_LIST_URL.format(fmt="html", id=15948)
CUNEO_HTML_15702 = it.CUNEO_LIST_URL.format(fmt="html", id=15702)
CUNEO_CSV_15948 = it.CUNEO_LIST_URL.format(fmt="csv", id=15948)
CUNEO_AVG_2025 = it.CUNEO_AVERAGES_URL.format(year=2025)
CUNEO_ANY_AVG = r"^https://www\.cuneoprezzi\.it/dataentry/site/ingrosso/medie/"
ISMEA_WEEKLY = it.ISMEA_URL.format(id=11024)
ISMEA_MONTHLY = it.ISMEA_URL.format(id=11025)
ONM_LUGLIO = "https://www.informamiele.it/luglio-2026-rilevazione-mensile/"
ONM_AGOSTO = "https://www.informamiele.it/agosto-2026-rilevazione-mensile/"
ONM_PDF_2024 = "https://www.informamiele.it/wp-content/uploads/2025/03/REPORT-Annuale-2024.pdf"
SIENA_PDF_14 = ("https://www.as.camcom.it/sites/default/files/contenuto_redazione/pagina_base/allegati/"
                "listino_prezzi_n_14_del_08_04_2026.pdf")


def fx(name: str) -> bytes:
    return fixture_bytes(f"italy/{name}")


@pytest.fixture()
def today_2026(monkeypatch):
    monkeypatch.setattr(it, "_today", lambda: date(2026, 11, 2))


def _prices(s, key: str) -> list[PriceObservation]:
    src = s.scalars(select(Source).where(Source.key == key)).one()
    return s.scalars(select(PriceObservation).where(PriceObservation.source_id == src.id,
                                                    PriceObservation.is_current.is_(True))).all()


def _reports(s, key: str) -> dict[str, Report]:
    src = s.scalars(select(Source).where(Source.key == key)).one()
    return {r.report_key: r for r in s.scalars(select(Report).where(Report.source_id == src.id))}


# ---------------------------------------------------------------------------------- helpers


def test_registry_has_the_four_italian_collectors():
    from paladex.collectors.registry import all_collectors

    keys = {c.key: c for c in all_collectors(refresh=True)}
    for key in ("cciaa_cuneo_miele", "ismea_miele", "onm_informamiele", "cciaa_siena_miele"):
        assert key in keys
        assert keys[key].schedule["trigger"] == "cron" and "day_of_week" in keys[key].schedule
        assert keys[key].country_iso3 == "ITA"


def test_italian_dates():
    assert it.parse_it_date("Miele - rilevazione mensile del 30 settembre 2023") == date(2023, 9, 30)
    assert it.parse_it_date("1° ottobre 2026") == date(2026, 10, 1)
    assert it.parse_it_date("Listino n. 14 del 08.04.2026") == date(2026, 4, 8)
    assert it.parse_it_date("listino_prezzi_n_14_del_08_04_2026.pdf") == date(2026, 4, 8)
    assert it.parse_it_date("2026-10-20T09:00:00") == date(2026, 10, 20)
    assert it.parse_it_date("31 febbraio 2026") is None            # invalid dates are not guessed
    assert it.parse_it_date("nessuna data") is None
    assert it.parse_it_month_year("agosto-2026-rilevazione-mensile") == (2026, 8)
    assert it.parse_it_month_year("Dicembre 2025") == (2025, 12)
    assert [it.it_month_number(m) for m in ("gennaio", "Set", "sett.", "DIC", "foo")] == [1, 9, 9, 12, None]


def test_italian_numbers_and_units():
    assert it.parse_it_number("7,50") == 7.5
    assert it.parse_it_number("1.234,56") == 1234.56
    assert it.parse_it_number("8,00 €/Kg") == 8.0
    assert it.parse_it_number("€ 7,50") == 7.5
    assert it.parse_it_number("-0,5%") == -0.5
    assert it.parse_it_number("1.500") == 1500.0
    for missing in ("nd", "-", "", "n.q.", "N.D."):
        assert it.parse_it_number(missing) is None
    with pytest.raises(ValueError):
        it.parse_it_number("7,5O")
    assert [it.normalize_unit(u) for u in ("kg", "Kg.", "q.le", "Q.li", "quintale", "€/kg", "litro")] == \
        ["kg", "kg", "q", "q", "q", "kg", None]
    assert it._unit_from_text("Prezzi in €/Kg") == "kg"
    assert it._unit_from_text("euro al quintale") == "q"
    assert it._unit_from_text("€/kg e €/q.le") is None             # ambiguous
    assert it._vat_flag("franco partenza IVA compresa") is True
    assert it._vat_flag("prezzi I.V.A. esclusa") is False
    assert it._vat_flag("franco magazzino") is None


def test_variety_normalisation_italian():
    cases = {
        "Castagno": "chestnut", "Agrumi": "orange_blossom", "Millefiori": "polyflora", "Tiglio": "linden",
        "Melata": "honeydew", "Acacia": "acacia", "Eucalipto": "eucalyptus", "Girasole": "sunflower",
        "Millefiori di alta montagna": "other", "alta montagna": "other", "Sulla": "other",
        "Miele selezionato": "other", "Miele": "unspecified", "": "unspecified",
    }
    for raw, expected in cases.items():
        assert it.normalize_it_variety(raw)[0] == expected, raw
    assert it.normalize_it_variety("Millefiori biologico") == ("organic_polyflora", True)
    assert it.split_cuneo_label("Acacia (fusto da 3 q.li)") == ("Acacia", "fusto da 3 q.li")
    assert it.split_cuneo_label("Millefiori (biologico)") == ("Millefiori (biologico)", None)
    assert it.split_cuneo_label("Tiglio - secchio da 25 kg") == ("Tiglio", "secchio da 25 kg")


def test_origin_and_packaging_detection():
    o = it.detect_origin("miele d'acacia ungherese")
    assert (o.iso3, o.foreign, o.ambiguous) == ("HUN", True, False)
    assert it.detect_origin("millefiori argentino").iso3 == "ARG"
    assert it.detect_origin("prodotto ucraino").iso3 == "UKR"
    assert it.detect_origin("miele cinese e argentino").ambiguous
    generic = it.detect_origin("miele d'importazione")
    assert generic.foreign and generic.iso3 is None and generic.label == "d'importazione"
    assert not it.detect_origin("Acacia (fusto da 3 q.li)").foreign
    assert [it.classify_packaging(t) for t in ("fusto da 3 q.li", "fusti da 300 kg", "secchio da 25 kg", "latta",
                                               "sfuso", None)] == \
        ["fusto_3q", "fusto_300kg", "secchio_25kg", "secchio", "sfuso", "non_specificato"]


# ------------------------------------------------------------------------------------ Cuneo


def test_cuneo_index_discovery():
    links = it.find_cuneo_lists(fx("cuneo_index_alimentari.html"))
    assert [(link.list_category, link.list_date) for link in links] == [(15948, date(2023, 9, 30)),
                                                                       (15702, date(2023, 8, 31))]
    assert links[0].url == "https://www.cuneoprezzi.it/ingrosso/ALIMENTARI/?listCategory=15948"
    # lists exist but none is for honey -> empty (warned by the collector, not a crash)
    assert it.find_cuneo_lists(b'<a href="?listCategory=1">Uova - del 2 ottobre 2023</a>') == []
    # no list link at all -> the index layout changed
    with pytest.raises(it.SchemaDrift):
        it.find_cuneo_lists(b"<html><body><a href='/'>home</a></body></html>")


def test_cuneo_list_html_parse():
    lst = it.parse_cuneo_list_html(fx("cuneo_list_15948.html"))
    assert lst.list_date == date(2023, 9, 30) and (lst.period_year, lst.period_month) == (2023, 9)
    assert lst.vat_included is True and "franco partenza dal magazzino" in lst.basis_note
    assert lst.no_quote == ["Melata (fusto da 3 q.li)"]         # '-' = not quoted, never zero
    assert lst.problems == []
    rows = {r["name"]: r for r in lst.rows}
    assert set(rows) == {"Acacia", "Millefiori", "Castagno", "Tiglio", "Millefiori di alta montagna"}
    acacia = rows["Acacia"]
    assert (acacia["low"], acacia["high"], acacia["value"], acacia["unit"]) == (7.5, 8.5, 8.0, "kg")
    assert acacia["packaging_code"] == "fusto_3q" and acacia["vat_rate"] == 10.0
    assert acacia["origin_iso3"] == "ITA"
    assert rows["Tiglio"]["packaging_code"] == "secchio_25kg"
    alta = rows["Millefiori di alta montagna"]
    assert alta["variety"] == "other" and alta["packaging"] == "secchio da 25 kg"


def test_cuneo_list_csv_matches_html():
    html = it.parse_cuneo_list_html(fx("cuneo_list_15948.html"))
    csv_ = it.parse_cuneo_list_csv(fx("cuneo_list_15948.csv"))
    assert csv_.fmt == "csv" and csv_.list_date == html.list_date
    assert csv_.basis_note == html.basis_note and csv_.no_quote == html.no_quote
    assert csv_.rows == html.rows


def _cuneo_html(rows: str, header: str = "<th>Prodotto</th><th>U.M.</th><th>Prezzo min</th><th>Prezzo max</th><th>IVA %</th>",
                title: str = "Miele - rilevazione mensile del 31 ottobre 2026",
                note: str = "Prodotto sfuso in fusti da 3 q.li - franco partenza dal magazzino IVA compresa") -> bytes:
    return (f"<html><body><h2>{title}</h2><p>{note}</p><table><tr>{header}</tr>{rows}</table></body></html>").encode()


def test_cuneo_prices_per_quintal():
    lst = it.parse_cuneo_list_html(_cuneo_html(
        "<tr><td>Acacia (fusto da 3 q.li)</td><td>q.le</td><td>750,00</td><td>850,00</td><td>10</td></tr>"
        "<tr><td>Millefiori (fusto da 3 q.li)</td><td>kg</td><td>5,50</td><td>6,50</td><td>10</td></tr>"))
    acacia, mf = lst.rows
    assert (acacia["unit"], acacia["value"]) == ("q", 800.0)
    assert ingest.per_kg(acacia["value"], acacia["unit"]) == 8.0
    assert mf["unit"] == "kg"
    # a per-quintal number in a "kg" column is implausible -> skipped with a problem, not stored
    bad = it.parse_cuneo_list_html(_cuneo_html(
        "<tr><td>Acacia (fusto da 3 q.li)</td><td>kg</td><td>750,00</td><td>850,00</td><td>10</td></tr>"))
    assert bad.rows == [] and "implausible" in bad.problems[0]
    # no U.M. column: unit taken from the page wording, refused when absent
    no_um = "<th>Prodotto</th><th>Prezzo min</th><th>Prezzo max</th>"
    ok = it.parse_cuneo_list_html(_cuneo_html("<tr><td>Acacia</td><td>7,50</td><td>8,50</td></tr>", header=no_um,
                                              note="Prezzi in €/kg, IVA compresa"))
    assert ok.rows[0]["unit"] == "kg"
    with pytest.raises(it.SchemaDrift, match="unit"):
        it.parse_cuneo_list_html(_cuneo_html("<tr><td>Acacia</td><td>7,50</td><td>8,50</td></tr>", header=no_um,
                                             note="IVA compresa"))


def test_cuneo_schema_drift_and_malformed_rows():
    with pytest.raises(it.SchemaDrift, match="Prezzo min"):
        it.parse_cuneo_list_html(_cuneo_html("<tr><td>Acacia</td><td>kg</td><td>8,00</td></tr>",
                                             header="<th>Prodotto</th><th>U.M.</th><th>Prezzo</th>"))
    with pytest.raises(it.SchemaDrift, match="date"):
        it.parse_cuneo_list_html(_cuneo_html("<tr><td>Acacia</td><td>kg</td><td>7,50</td><td>8,50</td><td>10</td></tr>",
                                             title="Miele - rilevazione mensile"))
    with pytest.raises(it.SchemaDrift):
        it.parse_cuneo_list_csv(b"Prodotto,Prezzo\nAcacia,8\n")
    lst = it.parse_cuneo_list_html(_cuneo_html(
        "<tr><td>Acacia (fusto da 3 q.li)</td><td>kg</td><td>7,50</td><td>8,5O</td><td>10</td></tr>"
        "<tr><td>Castagno (fusto da 3 q.li)</td><td>kg</td><td>6,50</td><td>5,50</td><td>10</td></tr>"
        "<tr><td>Tiglio (fusto da 3 q.li)</td><td>litri</td><td>6,50</td><td>7,00</td><td>10</td></tr>"
        "<tr><td>Millefiori (fusto da 3 q.li)</td><td>kg</td><td>5,50</td><td>6,50</td><td>10</td></tr>"))
    assert [r["name"] for r in lst.rows] == ["Millefiori"]
    assert len(lst.problems) == 3
    assert any("unparseable" in p for p in lst.problems) and any("min 6.5 > max 5.5" in p for p in lst.problems)


def test_cuneo_averages_pdf_ruled_and_unruled():
    ruled = it.parse_cuneo_averages_pdf(fx("cuneo_medie_2025.pdf"), year=2025)
    assert ruled.method == "table" and ruled.year == 2025 and ruled.problems == []
    rows = {r["name"]: r for r in ruled.rows}
    assert rows["Acacia"]["annual"] == 8.09 and rows["Acacia"]["monthly"][7] == 8.2
    assert sorted(rows["Castagno"]["monthly"]) == list(range(3, 13))       # blank Jan/Feb stay missing
    assert rows["Millefiori di alta montagna"]["variety"] == "other"
    unruled = it.parse_cuneo_averages_pdf(fx("cuneo_medie_2024_unruled.pdf"))
    assert unruled.method == "words"
    acacia, mf = unruled.rows
    assert 3 not in acacia["monthly"] and acacia["monthly"][4] == 8.0 and acacia["annual"] == 8.04
    assert sorted(mf["monthly"]) == [1, 2, 3, 7, 8, 9, 10, 11, 12]
    with pytest.raises(it.SchemaDrift, match="2023"):
        it.parse_cuneo_averages_pdf(fx("cuneo_medie_2025.pdf"), year=2023)
    with pytest.raises(it.SchemaDrift, match="twelve months"):
        it.parse_cuneo_averages_pdf(fx("siena_listino_n14_2026.pdf"))
    with pytest.raises(CollectorError, match="PDF"):
        it.parse_cuneo_averages_pdf(b"<html>not a pdf</html>")


def _cuneo_routes(**overrides) -> dict:
    routes = {
        CUNEO_INDEX: fx("cuneo_index_alimentari.html"),
        CUNEO_HTML_15948: fx("cuneo_list_15948.html"),
        CUNEO_HTML_15702: fx("cuneo_list_15702.html"),
        CUNEO_AVG_2025: fx("cuneo_medie_2025.pdf"),
        CUNEO_ANY_AVG: (404, b"not found"),
    }
    routes.update(overrides)
    return routes


def test_cuneo_end_to_end_and_idempotent(run_with_routes, session_factory, today_2026):
    res = run_with_routes("cciaa_cuneo_miele", _cuneo_routes())
    assert res["status"] == "success", res
    with session_factory() as s:
        rows = _prices(s, "cciaa_cuneo_miele")
        lists = [r for r in rows if r.series_key.startswith("wholesale_bulk|cuneo|")]
        assert len(lists) == 5 + 2                               # Sept 2023 (5 quoted) + Aug 2023 (2)
        acacia = next(r for r in lists if r.variety == "acacia" and r.period_label == "2023-09")
        assert acacia.price_type == "wholesale_bulk" and acacia.market_iso3 == "ITA"
        assert acacia.market_location == "Cuneo" and acacia.origin_iso3 == "ITA"
        assert (acacia.price_low, acacia.price_high, acacia.price_value) == (7.5, 8.5, 8.0)
        assert acacia.currency == "EUR" and acacia.unit == "kg" and acacia.price_per_kg == 8.0
        assert acacia.eur_per_kg == 8.0
        assert acacia.period_start == date(2023, 9, 1) and acacia.period_end == date(2023, 9, 30)
        assert acacia.published_at == date(2023, 9, 30) and acacia.frequency == "M"
        assert acacia.data_status == "published" and acacia.reliability == "industry"
        assert acacia.source_url == CUNEO_HTML_15948 and acacia.raw_document_id
        assert acacia.terms.startswith("fusto da 3 q.li") and "IVA compresa (aliquota 10%)" in acacia.terms
        assert acacia.extra["packaging_code"] == "fusto_3q" and acacia.extra["drum"] is True
        assert acacia.extra["vat_included"] is True and acacia.extra["list_category"] == 15948
        tiglio = next(r for r in lists if r.variety == "linden")
        assert tiglio.price_type == "wholesale_bulk" and tiglio.extra["drum"] is False
        assert tiglio.extra["packaging"] == "secchio da 25 kg" and tiglio.terms.startswith("secchio da 25 kg")
        alta = next(r for r in lists if r.variety_raw == "Millefiori di alta montagna")
        assert alta.variety == "other"
        assert not any(r.variety == "honeydew" for r in lists)  # Melata '-' = not quoted, nothing stored
        # back-fill: 2025 averages, gap filling under their own series, flagged as averages
        avgs = [r for r in rows if r.series_key.startswith("wholesale_bulk|cuneo-media|")]
        monthly = [r for r in avgs if r.frequency == "M"]
        annual = [r for r in avgs if r.frequency == "A"]
        assert len(annual) == 5 and len(monthly) == 12 + 12 + 10 + 12 + 4
        acacia_y = next(r for r in annual if r.variety == "acacia")
        assert acacia_y.price_value == 8.09 and acacia_y.period_label == "2025" and acacia_y.price_low is None
        assert acacia_y.extra["statistic"] == "annual_average"
        assert all(r.extra["statistic"] == "monthly_average" for r in monthly)
    res2 = run_with_routes("cciaa_cuneo_miele", _cuneo_routes())
    assert res2["status"] == "no_change", res2
    assert res2["new"] == 0 and res2["revised"] == 0


def test_cuneo_csv_fallback_when_html_download_fails(run_with_routes, session_factory, today_2026):
    routes = _cuneo_routes(**{CUNEO_HTML_15948: (404, b"no"), CUNEO_CSV_15948: fx("cuneo_list_15948.csv")})
    res = run_with_routes("cciaa_cuneo_miele", routes)
    assert res["status"] == "success", res
    with session_factory() as s:
        acacia = next(r for r in _prices(s, "cciaa_cuneo_miele") if r.variety == "acacia" and r.period_label == "2023-09")
        assert acacia.source_url == CUNEO_CSV_15948 and acacia.extra["format"] == "csv"


def test_cuneo_schema_drift_fails_run(run_with_routes, session_factory, today_2026):
    drifted = fx("cuneo_list_15948.html").replace(b"Prezzo min", b"Quotazione").replace(b"Prezzo max", b"Note")
    res = run_with_routes("cciaa_cuneo_miele", _cuneo_routes(**{CUNEO_HTML_15948: drifted}))
    assert res["status"] == "failed" and "Prezzo min" in res["error"], res
    with session_factory() as s:
        assert _prices(s, "cciaa_cuneo_miele") == []


def test_cuneo_malformed_row_gives_partial_run(run_with_routes, session_factory, today_2026):
    broken = fx("cuneo_list_15948.html").replace(b"<td>5,50</td><td>6,50</td>", b"<td>5,50</td><td>abc</td>")
    res = run_with_routes("cciaa_cuneo_miele", _cuneo_routes(**{CUNEO_HTML_15948: broken}))
    assert res["status"] == "partial" and any("Millefiori" in w for w in res["warnings"]), res
    with session_factory() as s:
        sept = [r for r in _prices(s, "cciaa_cuneo_miele") if r.period_label == "2023-09"]
        assert {r.variety for r in sept} == {"acacia", "chestnut", "linden", "other"}


# ------------------------------------------------------------------------------------ ISMEA


def test_ismea_week_convention():
    assert it.ismea_week_bounds(2026, 6, 4) == (date(2026, 6, 22), date(2026, 6, 28))
    # 1 Feb 2026 is a Sunday: week 1 of February is the Mon-Sun week holding the first Thursday (5 Feb)
    assert it.ismea_week_bounds(2026, 2, 1) == (date(2026, 2, 2), date(2026, 2, 8))
    # 1 Oct 2026 is a Thursday: week 1 starts on Monday 28 September
    assert it.ismea_week_bounds(2026, 10, 1) == (date(2026, 9, 28), date(2026, 10, 4))
    assert it.ismea_week_bounds(2026, 7, 5) == (date(2026, 7, 27), date(2026, 8, 2))
    with pytest.raises(ValueError):
        it.ismea_week_bounds(2026, 6, 5)                     # June 2026 has four such weeks
    p = it.ismea_period("2026-6-4")
    assert (p["label"], p["frequency"], p["extra"]["period_raw"], p["extra"]["iso_week"]) == \
        ("2026-06-S4", "W", "2026-6-4", "2026-W26")
    m = it.ismea_period("2026-6")
    assert (m["start"], m["end"], m["label"], m["frequency"]) == (date(2026, 6, 1), date(2026, 6, 30), "2026-06", "M")
    with pytest.raises(ValueError):
        it.ismea_period("giugno 2026")


def test_ismea_parse_pages():
    weekly = it.parse_ismea_prices(fx("ismea_11024_settimanali.html"))
    assert weekly.problems == [] and weekly.vat_included is None    # not stated on this page
    by = {r["product"]: r for r in weekly.rows}
    assert set(by) == {"Acacia", "Agrumi", "Castagno", "Eucalipto", "Millefiori", "Sulla", "Tiglio"}  # Girasole 'nd'
    assert by["Acacia"]["price"] == 8.0 and by["Acacia"]["unit"] == "kg" and by["Acacia"]["chg_prev"] == 0.0
    assert by["Acacia"]["chg_year"] is None
    assert by["Agrumi"]["variety"] == "orange_blossom" and by["Sulla"]["variety"] == "other"
    assert by["Millefiori"]["period"]["label"] == "2026-06-S4"
    monthly = it.parse_ismea_prices(fx("ismea_11025_mensili.html"))
    assert monthly.vat_included is True
    (row,) = monthly.rows
    assert (row["variety"], row["price"], row["period"]["frequency"]) == ("unspecified", 5.48, "M")


def test_ismea_schema_drift():
    with pytest.raises(it.SchemaDrift, match="Prezzo"):
        it.parse_ismea_prices(b"<table><tr><th>Varieta</th><th>Settimana</th><th>Valore</th></tr></table>")
    with pytest.raises(it.SchemaDrift, match="iframe"):
        it.parse_ismea_prices(b"<html><body><iframe src='/ReportServer?/Miele'></iframe></body></html>")
    with pytest.raises(it.SchemaDrift, match="unit"):
        it.parse_ismea_prices(b"<table><tr><th>Prodotto</th><th>Settimana</th><th>Prezzo</th></tr>"
                              b"<tr><td>Acacia</td><td>2026-6-4</td><td>8,00</td></tr></table>")
    bad = it.parse_ismea_prices(b"<p>Prezzi in &euro;/kg</p><table><tr><th>Prodotto</th><th>Settimana</th><th>Prezzo</th></tr>"
                                b"<tr><td>Acacia</td><td>2026-6-9</td><td>8,00</td></tr>"
                                b"<tr><td>Tiglio</td><td>2026-6-4</td><td>circa 5</td></tr>"
                                b"<tr><td>Castagno</td><td>2026-6-4</td><td>4,90</td></tr></table>")
    assert [r["product"] for r in bad.rows] == ["Castagno"] and len(bad.problems) == 2


def test_ismea_end_to_end_and_idempotent(run_with_routes, session_factory):
    routes = {ISMEA_WEEKLY: fx("ismea_11024_settimanali.html"), ISMEA_MONTHLY: fx("ismea_11025_mensili.html")}
    res = run_with_routes("ismea_miele", routes)
    assert res["status"] == "success" and res["new"] == 8, res
    with session_factory() as s:
        rows = _prices(s, "ismea_miele")
        assert {r.price_type for r in rows} == {"producer"}
        acacia = next(r for r in rows if r.variety == "acacia")
        assert (acacia.price_value, acacia.unit, acacia.currency) == (8.0, "kg", "EUR")
        assert (acacia.period_start, acacia.period_end, acacia.frequency) == (date(2026, 6, 22), date(2026, 6, 28), "W")
        assert acacia.market_iso3 == "ITA" and acacia.origin_iso3 == "ITA" and acacia.market_location == "Italia"
        assert acacia.reliability == "official" and acacia.data_status == "published"
        assert acacia.extra["period_raw"] == "2026-6-4" and acacia.extra["vat_source"] == "research_documentation"
        assert "IVA compresa" in acacia.terms and "all'origine" in acacia.terms
        assert acacia.notes and "convenzione" in acacia.notes
        italia = next(r for r in rows if r.frequency == "M")
        assert italia.variety == "unspecified" and italia.price_value == 5.48 and italia.extra["vat_source"] == "page"
    assert run_with_routes("ismea_miele", routes)["status"] == "no_change"


# -------------------------------------------------------------------------------------- ONM


def test_onm_discovery_paths():
    feed = it.discover_onm_from_feed(fx("onm_feed.xml"))
    kinds = {(p.kind, p.ref_year, p.ref_month, p.season) for p in feed}
    assert ("monthly", 2026, 8, None) in kinds and ("monthly", 2026, 7, None) in kinds
    assert ("annual", None, None, 2025) in kinds
    luglio = next(p for p in feed if p.ref_month == 7)
    assert luglio.published == date(2026, 8, 20) and "millefiori convenzionale" in luglio.content_html
    rest = it.discover_onm_from_wp_json(fx("onm_wp_posts.json"))
    assert [(p.kind, p.ref_month) for p in rest] == [("monthly", 8), ("monthly", 7), ("other", None)]
    assert rest[0].title == "Agosto 2026 – Rilevazione mensile" and rest[0].published == date(2026, 9, 21)
    listing = it.discover_onm_from_listing(fx("onm_listing_comunicati.html"), "https://www.informamiele.it/category/comunicati/")
    assert {(p.ref_year, p.ref_month, p.published) for p in listing} == {
        (2026, 8, date(2026, 9, 21)), (2026, 7, date(2026, 8, 20)), (2022, 8, date(2022, 9, 15))}
    assert all(p.kind == "monthly" for p in listing)            # 'prime valutazioni' is not a bulletin
    with pytest.raises(CollectorError):
        it.discover_onm_from_feed(b"<html><body>Not a feed</body></html>")
    with pytest.raises(CollectorError):
        it.discover_onm_from_wp_json(b'{"code": "rest_no_route"}')


def test_onm_post_market_section():
    luglio = it.parse_onm_post(fx("onm_post_luglio_2026.html"))
    assert luglio.title == "Luglio 2026 - Rilevazione mensile" and luglio.published == date(2026, 8, 20)
    assert luglio.has_market_section and len(luglio.market_paragraphs) == 4
    assert all("regine" not in p and not p.startswith("Le rese") for p in luglio.market_paragraphs)
    assert luglio.price_basis == "franco produttore, IVA inclusa"
    agosto = it.parse_onm_post(fx("onm_post_agosto_2026.html"))        # bold-paragraph headings
    assert agosto.has_market_section and agosto.market_paragraphs[0].startswith("Rimane stazionario")
    assert it.extract_onm_prices(agosto.market_paragraphs) == []        # only an offer 'attorno ai 4,00 €/kg'


def test_onm_price_extraction_rules():
    # Documented Oct 2025 wording (Apicoltore Moderno PDF): the range is paired with the conventional
    # millefiori; the organic 'intorno ai 5 €/kg' single value is not stored.
    out = it.extract_onm_prices(["Sul mercato all'ingrosso il miele millefiori convenzionale mostra quotazioni "
                                 "prevalentemente comprese tra 4 e 4,5 €/kg (fusto), mentre il millefiori biologico "
                                 "si attesta intorno ai 5 €/kg (fusto)."])
    assert [(o["variety"], o["low"], o["high"], o["organic"], o["packaging_code"], o["origin_iso3"]) for o in out] == \
        [("polyflora", 4.0, 4.5, False, "fusto", "ITA")]
    # organic stated in the pair
    bio = it.extract_onm_prices(["In fusti il millefiori biologico è quotato 6,00-6,30 €/kg."])
    assert bio[0]["variety"] == "polyflora" and bio[0]["organic"] is True
    # range-first wording ('... per il castagno')
    rf = it.extract_onm_prices(["All'ingrosso si pagano 6,50-6,70 €/kg per il castagno."])
    assert rf[0]["variety"] == "chestnut" and rf[0]["packaging_code"] == "non_specificato"
    # foreign origins named in the sentence
    ar = it.extract_onm_prices(["Il millefiori argentino sfuso è offerto tra 3,10 e 3,40 €/kg."])
    assert ar[0]["origin_iso3"] == "ARG" and ar[0]["origin_label"] == "argentino"
    imp = it.extract_onm_prices(["Il millefiori d'importazione in fusti viene offerto a 2,80-3,00 €/kg."])
    assert imp[0]["origin_iso3"] is None and imp[0]["origin_label"] == "d'importazione"
    # ambiguous or out-of-scope sentences give nothing
    for sentence in (
        "Le quotazioni all'ingrosso di castagno e tiglio oscillano tra 6,50 e 6,70 €/kg.",   # 2 varieties, 1 range
        "Tra apicoltori, in latta, il millefiori viene scambiato a 6,00-6,50 €/kg.",         # no bulk context
        "Il millefiori in fusti è stato venduto tra 4 e 4,5.",                               # no €/kg unit
        "In fusti il millefiori resta attorno ai 4,00 €/kg.",                                # single value
        "Il millefiori ungherese e quello rumeno in fusti costano 3,00-3,50 €/kg.",          # two origins
        "In fusti il millefiori italiano e quello ucraino tra 3,00 e 4,50 €/kg.",            # Italian and foreign
        "Nel mercato all'ingrosso in fusti e in latta il millefiori tra 5 e 6 €/kg.",        # drum or bucket?
        "In fusti l'acacia è a 80-90 €/kg.",                                                 # implausible
    ):
        assert it.extract_onm_prices([sentence]) == [], sentence
    # the same item twice with different numbers in one bulletin is ambiguous -> dropped
    assert it.extract_onm_prices(["In fusti il millefiori tra 4 e 5 €/kg.", "In fusti il millefiori tra 6 e 7 €/kg."]) == []


def test_onm_annual_pdf_tables(monkeypatch):
    t = it.parse_onm_annual_pdf(fx("onm_report_annuale_2024.pdf"))
    assert t.problems == []
    assert "fusti da 300 kg" in t.variety_caption and "importazione" in t.import_caption
    v = {r["label"]: r for r in t.variety_rows}
    assert set(v) == {"Acacia", "Agrumi", "Castagno", "Millefiori", "Tiglio", "Sulla"}   # 'Media' row skipped
    assert (v["Acacia"]["low"], v["Acacia"]["high"], v["Acacia"]["value"]) == (8.5, 10.5, 9.4)
    assert v["Agrumi"]["variety"] == "orange_blossom" and v["Sulla"]["variety"] == "other"
    imp = {r["origin_iso3"]: r for r in t.import_rows}
    assert set(imp) == {"ARG", "UKR", "CHN", "HUN", "MDA"}                                # 'Altri paesi' skipped
    assert imp["ARG"]["value"] == 2.85
    # two tables answering the same caption -> ambiguous, none imported
    page = ["Prezzi all'ingrosso dei mieli in fusti", "Varietà Min Max Media", "Acacia 8,50 10,50 9,40"]
    monkeypatch.setattr(it, "_pdf_lines", lambda content: [page, page])
    dup = it.parse_onm_annual_pdf(b"%PDF")
    assert dup.variety_rows == [] and "ambiguous" in dup.problems[0]
    # a row with a missing cell is not guessed
    monkeypatch.setattr(it, "_pdf_lines", lambda content: [[
        "Prezzi all'ingrosso dei mieli in fusti", "Varietà Min Max Media", "Acacia 8,50 9,40", "Tiglio 6,00 7,20 6,60"]])
    gap = it.parse_onm_annual_pdf(b"%PDF")
    assert [r["label"] for r in gap.variety_rows] == ["Tiglio"] and "2 values for 3 columns" in gap.problems[0]


def _onm_routes(**overrides) -> dict:
    routes = {
        it.ONM_FEED_URL: (200, fx("onm_feed.xml"), "application/rss+xml"),
        ONM_LUGLIO: fx("onm_post_luglio_2026.html"),
        ONM_AGOSTO: fx("onm_post_agosto_2026.html"),
        it.ONM_REPORT_ARCHIVE_URL: fx("onm_report_archive.html"),
        ONM_PDF_2024: (200, fx("onm_report_annuale_2024.pdf"), "application/pdf"),
    }
    routes.update(overrides)
    return routes


def test_onm_end_to_end_and_idempotent(run_with_routes, session_factory):
    res = run_with_routes("onm_informamiele", _onm_routes())
    assert res["status"] == "success", res
    with session_factory() as s:
        reports = _reports(s, "onm_informamiele")
        assert set(reports) == {"rilevazione-mensile-2026-07", "rilevazione-mensile-2026-08",
                                "report-annuale-2024", "report-annuale-2025"}
        jul = reports["rilevazione-mensile-2026-07"]
        assert jul.published_at == date(2026, 8, 20) and jul.period_label == "2026-07" and jul.url == ONM_LUGLIO
        assert jul.narrative.startswith("Nel mese di luglio") and "regine" not in jul.narrative
        assert jul.raw_document_id
        assert reports["rilevazione-mensile-2026-08"].narrative.startswith("Rimane stazionario")
        assert reports["report-annuale-2024"].url == ONM_PDF_2024
        assert reports["report-annuale-2025"].published_at == date(2026, 3, 3)
        rows = _prices(s, "onm_informamiele")
        monthly = [r for r in rows if r.frequency == "M"]
        assert len(monthly) == 3
        assert {r.price_type for r in rows} == {"wholesale_bulk"}
        for r in monthly:
            assert r.data_status == "provisional" and r.notes.startswith("estratto dal testo del bollettino")
            assert r.period_label == "2026-07" and r.published_at == date(2026, 8, 20)
            assert r.market_iso3 == "ITA" and r.extra["needs_review"] is True and r.extra["context_sentence"]
            assert "franco produttore, IVA inclusa" in r.terms
        hun = next(r for r in monthly if r.origin_iso3 == "HUN")
        assert hun.variety == "acacia" and (hun.price_low, hun.price_high) == (4.8, 5.2)
        mf = next(r for r in monthly if r.variety == "polyflora")
        assert (mf.price_low, mf.price_high, mf.price_value, mf.origin_iso3) == (5.0, 6.5, 5.75, "ITA")
        annual = [r for r in rows if r.frequency == "A"]
        assert len(annual) == 6 + 5
        assert all(r.data_status == "published" and r.period_label == "2024" for r in annual)
        ukr = next(r for r in annual if r.origin_iso3 == "UKR")
        assert ukr.market_iso3 == "ITA" and ukr.variety == "unspecified" and ukr.price_value == 2.45
        assert "importazione" in ukr.terms
        acacia = next(r for r in annual if r.variety == "acacia")
        assert acacia.origin_iso3 == "ITA" and (acacia.price_low, acacia.price_high, acacia.price_value) == (8.5, 10.5, 9.4)
    res2 = run_with_routes("onm_informamiele", _onm_routes())
    assert res2["status"] == "no_change" and res2["new"] == 0, res2


def test_onm_falls_back_to_wp_json_and_feed_copy(run_with_routes, session_factory):
    routes = _onm_routes(**{
        it.ONM_FEED_URL: (404, b"Not Found"),
        it.ONM_WP_API_URL: (200, fx("onm_wp_posts.json"), "application/json"),
        ONM_AGOSTO: (403, b"Forbidden"),                         # use the REST copy of the post
        it.ONM_REPORT_ARCHIVE_URL: (404, b"Not Found"),
    })
    res = run_with_routes("onm_informamiele", routes)
    assert res["status"] == "partial", res
    assert any("archive unavailable" in w for w in res["warnings"])
    with session_factory() as s:
        reports = _reports(s, "onm_informamiele")
        ago = reports["rilevazione-mensile-2026-08"]
        assert ago.raw_document_id is None and ago.narrative.startswith("Rimane stazionario")
        assert ago.published_at == date(2026, 9, 21)
        assert len([r for r in _prices(s, "onm_informamiele") if r.period_label == "2026-07"]) == 3


def test_onm_html_listing_fallback(run_with_routes, session_factory):
    routes = _onm_routes(**{
        it.ONM_FEED_URL: (404, b""), it.ONM_WP_API_URL: (404, b""),
        it.ONM_LISTING_URLS[0]: fx("onm_listing_comunicati.html"),
        "https://www.informamiele.it/agosto-2022-indagine-produttiva-ed-economica/": (404, b""),
    })
    res = run_with_routes("onm_informamiele", routes)
    assert res["status"] == "partial" and any("2022" in w for w in res["warnings"]), res
    with session_factory() as s:
        assert {"rilevazione-mensile-2026-07", "rilevazione-mensile-2026-08"} <= set(_reports(s, "onm_informamiele"))


def test_onm_discovery_failure_is_an_error(run_with_routes):
    routes = {it.ONM_FEED_URL: (404, b""), it.ONM_WP_API_URL: (404, b""),
              it.ONM_LISTING_URLS[0]: (404, b""), it.ONM_LISTING_URLS[1]: (404, b"")}
    res = run_with_routes("onm_informamiele", routes)
    assert res["status"] == "failed" and "could not be discovered" in res["error"]


# ------------------------------------------------------------------------------------ Siena


def test_siena_discovery_and_parse():
    links, archives = it.find_siena_pdfs(fx("siena_prezzi.html"))
    assert [(link.number, link.list_date) for link in links] == [
        (14, date(2026, 4, 8)), (24, date(2025, 6, 18)), (34, date(2024, 8, 28))]
    assert archives[0].endswith("listini-settimanali-provincia-siena-anno-2025")
    lst = it.parse_siena_pdf(fx("siena_listino_n14_2026.pdf"))
    assert (lst.number, lst.list_date, lst.problems) == (14, date(2026, 4, 8), [])
    mf, sel = lst.rows
    assert (mf["label"], mf["variety"], mf["low"], mf["high"], mf["unit"]) == ("Miele millefiori", "polyflora", 6.0, 7.0, "kg")
    assert (sel["variety"], sel["low"], sel["high"]) == ("other", 6.5, 10.0)
    assert mf["price_type"] == "wholesale_bulk" and mf["price_type_basis"] == "title"
    assert it._price_type_from_wording("PREZZI AL CONSUMO")[0] == "retail"
    assert it._price_type_from_wording("prezzi alla produzione")[0] == "producer"
    assert it._price_type_from_wording("prezzi all'ingrosso e al consumo") == (None, None)


def test_siena_schema_drift():
    with pytest.raises(it.SchemaDrift, match="da Euro"):
        it.parse_siena_pdf(fx("siena_listino_drift.pdf"))


def test_siena_end_to_end_and_idempotent(run_with_routes, session_factory):
    routes = {it.SIENA_INDEX_URL: fx("siena_prezzi.html"),
              SIENA_PDF_14: (200, fx("siena_listino_n14_2026.pdf"), "application/pdf")}
    res = run_with_routes("cciaa_siena_miele", routes)
    assert res["status"] == "success" and res["new"] == 2, res
    with session_factory() as s:
        rows = _prices(s, "cciaa_siena_miele")
        mf = next(r for r in rows if r.variety == "polyflora")
        assert mf.price_type == "wholesale_bulk" and mf.market_location == "Siena" and mf.origin_iso3 == "ITA"
        assert (mf.period_start, mf.period_end, mf.period_label) == (date(2026, 4, 6), date(2026, 4, 12), "2026-W15")
        assert mf.published_at == date(2026, 4, 8) and mf.frequency == "W"
        assert mf.terms.startswith("listino settimanale n. 14 del 08.04.2026")
        assert mf.extra["packaging_code"] == "non_specificato" and mf.source_url == SIENA_PDF_14
    assert run_with_routes("cciaa_siena_miele", routes)["status"] == "no_change"


def test_siena_archive_fallback_and_missing_links(run_with_routes, today_2026):
    archive_2026 = it.SIENA_ARCHIVE_URL.format(year=2026)
    routes = {it.SIENA_INDEX_URL: b"<html><body><p>Nessun listino</p></body></html>",
              archive_2026: fx("siena_prezzi.html"),
              SIENA_PDF_14: (200, fx("siena_listino_n14_2026.pdf"), "application/pdf")}
    assert run_with_routes("cciaa_siena_miele", routes)["status"] == "success"
    res = run_with_routes("cciaa_siena_miele", {
        it.SIENA_INDEX_URL: b"<html></html>", archive_2026: (404, b""),
        it.SIENA_ARCHIVE_URL.format(year=2025): b"<html></html>"})
    assert res["status"] == "failed" and "no weekly price-list PDF" in res["error"]
