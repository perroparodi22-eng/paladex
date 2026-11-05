"""Italian honey sources (paladex.collectors.italy).

The `real_*` fixtures in tests/fixtures/italy/ are REAL captures of the official sources taken
on 4 Nov 2026 (some trimmed, see the README there) and the tests assert the published values.
A few reconstructed fixtures remain for rules the real captures do not exercise (ONM bulletin
prose with price ranges, discovery fallbacks, a schema-drift PDF); they are named without the
`real_` prefix and their numbers are test data.
"""
from __future__ import annotations

import hashlib
import importlib.util
from datetime import date
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import select

from conftest import fixture_bytes
from paladex.collectors import italy as it
from paladex.collectors.base import CollectorError
from paladex.models import PriceObservation, RawDocument, Report, Source
from paladex.services import ingest

FIXTURES = Path(__file__).parent / "fixtures"
CUNEO_HONEY = it.CUNEO_HONEY_URL
CUNEO_HTML = it.CUNEO_LIST_URLS["html"]
CUNEO_CSV = it.CUNEO_LIST_URLS["csv"]
CUNEO_HTML_20353 = CUNEO_HTML.format(id=20353)
CUNEO_CSV_20353 = CUNEO_CSV.format(id=20353)
CUNEO_HTML_18861 = CUNEO_HTML.format(id=18861)
CUNEO_AVG_2025 = it.CUNEO_AVERAGES_URL.format(year=2025)
CUNEO_ANY_AVG = r"^https://www\.cuneoprezzi\.it/dataentry/site/ingrosso/medie/"
ISMEA_WEEKLY = it.ISMEA_URL.format(id=11024)
ISMEA_MONTHLY = it.ISMEA_URL.format(id=11026)
ONM_LUGLIO = "https://www.informamiele.it/luglio-2026-rilevazione-mensile/"
ONM_AGOSTO = "https://www.informamiele.it/agosto-2026-rilevazione-mensile/"
ONM_SETTEMBRE = "https://www.informamiele.it/settembre-2026-rilevazione-mensile/"
ONM_PDF_2025 = ("https://www.informamiele.it/wp-content/uploads/2026/10/"
                "Report-annuale-Monitoraggio-produzione-e-mercato-del-miele-stagione-2025.pdf")
SIENA_2026 = "https://www.as.camcom.it/listini-settimanali-provincia-siena-anno-2026"
SIENA_PDF_44 = ("https://www.as.camcom.it/sites/default/files/contenuto_redazione/pagina_base/allegati/"
                "listino_prezzi_n_44_del_04_11_2026.pdf")


def fx(name: str) -> bytes:
    return fixture_bytes(f"italy/{name}")


@pytest.fixture()
def today_2026(monkeypatch):
    monkeypatch.setattr(it, "_today", lambda: date(2026, 11, 4))


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
    # abbreviations printed in the real Cuneo averages header
    assert [it.it_month_number(m) for m in ("Genn.", "Febb.", "Magg.", "Sett.")] == [1, 2, 5, 9]


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
    # real unit cells: Cuneo 'al kg' / 'al kg.' / 'al Kg', Siena 'al Kg.' / 'per 100 Kg' / 'alla tonn.'
    assert [it.normalize_unit(u) for u in ("al kg", "al kg.", "al Kg ", "al Kg.", "per 100 Kg", "alla tonn.")] == \
        ["kg", "kg", "kg", "kg", "q", "t"]
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
        # labels as printed by the real sources
        "Tarassaco": "dandelion", "Melata di Bosco": "honeydew", "Melata d'abete": "honeydew",
        "Rododendro": "other", "Miele - Acacia": "acacia", "Miele (millefiori)": "polyflora",
    }
    for raw, expected in cases.items():
        assert it.normalize_it_variety(raw)[0] == expected, raw
    assert it.normalize_it_variety("Millefiori biologico") == ("organic_polyflora", True)
    assert it.split_cuneo_label("Acacia (fusto da 3 q.li)") == ("Acacia", "fusto da 3 q.li")
    assert it.split_cuneo_label("- Acacia (fusto da 3 q.li)") == ("Acacia", "fusto da 3 q.li")   # real leading dash
    assert it.split_cuneo_label("Millefiori (biologico)") == ("Millefiori (biologico)", None)
    assert it.split_cuneo_label("Tiglio - secchio da 25 kg") == ("Tiglio", "secchio da 25 kg")
    assert it.is_non_honey("Polline deumidificato (sacchi da 5 kg)") and not it.is_non_honey("Millefiori")


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
                                               "sfuso", None, "secchielli da 20-25 kg")] == \
        ["fusto_3q", "fusto_300kg", "secchio_25kg", "secchio", "sfuso", "non_specificato", "secchio"]


# ------------------------------------------------------------------------------------ Cuneo


def test_cuneo_real_index_is_not_the_honey_chapter():
    """Live finding: the ALIMENTARI index shows the 'Cereali' chapter, whose lists are not
    honey lists; the 'Miele' chapter is category=11."""
    page = fx("real_cuneo_index_alimentari.html")
    assert it.cuneo_page_category(page) == "Cereali"
    assert it.find_cuneo_lists(page, it.CUNEO_INDEX_URL) == []
    assert it.find_cuneo_category_url(page, it.CUNEO_INDEX_URL) == CUNEO_HONEY
    with pytest.raises(it.SchemaDrift):
        it.find_cuneo_lists(b"<html><body><a href='/'>home</a></body></html>")


def test_cuneo_real_honey_chapter_lists():
    page = fx("real_cuneo_category_miele.html")
    assert it.cuneo_page_category(page) == "Miele"
    links = it.find_cuneo_lists(page)
    assert len(links) == 28                                  # trimmed menu: newest 26 + oldest 2
    assert [(link.list_category, link.list_date) for link in links[:3]] == [
        (20353, date(2026, 9, 30)), (20204, date(2026, 8, 31)), (20063, date(2026, 7, 31))]
    assert links[0].title == "Miele - rilevazione mensile del 30 settembre 2026"
    assert links[0].url == "https://www.cuneoprezzi.it/ingrosso/alimentari/?listCategory=20353"
    # ids are not in date order on the real page (17545 = 30 Nov 2024, 17578 = 30 Oct 2024)
    assert [link.list_category for link in links if link.list_date.year == 2024][:2] == [17804, 17545]
    assert (links[-1].list_category, links[-1].list_date) == (15, date(2010, 11, 23))


def test_cuneo_real_list_html():
    lst = it.parse_cuneo_list_html(fx("real_cuneo_list_20353.html"))
    assert lst.title == "Miele - rilevazione mensile del 30 settembre 2026"
    assert lst.list_date == date(2026, 9, 30) and (lst.period_year, lst.period_month) == (2026, 9)
    assert lst.basis_note == "Prodotto sfuso in fusti da 3 q.li - franco partenza dal magazzino IVA compresa"
    assert lst.vat_included is True and lst.problems == []
    assert lst.no_quote == ["Melata di Bosco (secchio da 25 kg)", "Ciliegio (secchielli da 20-25 kg)",
                            "Melata d'abete (secchio da 25 kg)"]                # 'n.q.' = missing, never zero
    assert lst.non_honey == ["Polline deumidificato (sacchi da 5 kg)"]          # pollen is not honey
    rows = {r["name"]: r for r in lst.rows}
    assert set(rows) == {"Acacia", "Millefiori", "Castagno", "Tarassaco", "Tiglio",
                         "Millefiori di Alta Montagna", "Rododendro"}
    acacia = rows["Acacia"]
    assert (acacia["low"], acacia["high"], acacia["value"], acacia["unit"]) == (7.0, 8.0, 7.5, "kg")
    assert acacia["packaging"] == "fusto da 3 q.li" and acacia["packaging_code"] == "fusto_3q"
    assert acacia["vat_rate"] == 10.0 and acacia["origin_iso3"] == "ITA" and acacia["key"] == "acacia"
    assert (rows["Millefiori"]["low"], rows["Millefiori"]["high"]) == (4.5, 5.5)
    assert (rows["Tiglio"]["low"], rows["Tiglio"]["high"], rows["Tiglio"]["packaging_code"]) == (4.8, 5.8, "secchio_25kg")
    assert rows["Tarassaco"]["variety"] == "dandelion" and rows["Tarassaco"]["unit"] == "kg"      # 'al kg.'
    assert rows["Millefiori di Alta Montagna"]["variety"] == "other"
    assert (rows["Rododendro"]["low"], rows["Rododendro"]["high"]) == (7.5, 8.5)


def test_cuneo_real_list_csv_matches_html():
    html = it.parse_cuneo_list_html(fx("real_cuneo_list_20353.html"))
    csv_ = it.parse_cuneo_list_csv(fx("real_cuneo_list_20353.csv"))
    assert csv_.fmt == "csv" and csv_.list_date == html.list_date and csv_.title == html.title
    assert csv_.no_quote == html.no_quote and csv_.non_honey == html.non_honey
    assert csv_.rows == html.rows


def test_cuneo_real_list_with_quantity_condition_label():
    """30 Sept 2025: 'Acacia (quantitativi >10 q.li)'. The container comes from the chapter note
    and the item keeps the series of 'Acacia (fusto da 3 q.li)'."""
    lst = it.parse_cuneo_list_html(fx("real_cuneo_list_18861.html"))
    assert lst.list_date == date(2025, 9, 30)
    acacia = next(r for r in lst.rows if r["name"] == "Acacia")
    assert (acacia["low"], acacia["high"], acacia["value"]) == (7.5, 8.5, 8.0)
    assert acacia["packaging"] == "fusti da 3 q.li (quantitativi >10 q.li)"
    assert acacia["packaging_from"] == "list_note+label" and acacia["packaging_code"] == "fusto_3q"
    assert acacia["key"] == "acacia" and acacia["label"] == "Acacia (quantitativi >10 q.li)"


def _cuneo_html(rows: str, header: str = "<td></td><td>Miele - Prodotti dell'alveare</td><td>Unità di misura</td>"
                "<td>Prezzo minimo</td><td>Prezzo massimo</td><td>IVA</td><td>Osservazioni</td>",
                title: str = "rilevazione mensile del 31 ottobre 2026",
                note: str = "Prodotto sfuso in fusti da 3 q.li - franco partenza dal magazzino IVA compresa") -> bytes:
    """A list in the real 'download/html' layout, with test rows."""
    return (f"<html><body><h2 class='content_data_title'> Miele </h2><b>{title}</b><br>"
            f"<b>Quotazioni rilevate dalla Camera di Commercio</b><br>{note}<br>"
            f"<table><tr>{header}</tr>{rows}</table></body></html>").encode()


def test_cuneo_prices_per_quintal():
    lst = it.parse_cuneo_list_html(_cuneo_html(
        "<tr><td></td><td>- Acacia (fusto da 3 q.li)</td><td>al q.le</td><td>750,00</td><td>850,00</td><td>10%</td><td></td></tr>"
        "<tr><td></td><td>- Millefiori (fusto da 3 q.li)</td><td>al kg</td><td>5,50</td><td>6,50</td><td>10%</td><td></td></tr>"))
    acacia, mf = lst.rows
    assert (acacia["unit"], acacia["value"]) == ("q", 800.0)
    assert ingest.per_kg(acacia["value"], acacia["unit"]) == 8.0
    assert mf["unit"] == "kg"
    # a per-quintal number in a "kg" column is implausible -> skipped with a problem, not stored
    bad = it.parse_cuneo_list_html(_cuneo_html(
        "<tr><td></td><td>Acacia (fusto da 3 q.li)</td><td>al kg</td><td>750,00</td><td>850,00</td><td>10%</td><td></td></tr>"))
    assert bad.rows == [] and "implausible" in bad.problems[0]
    # no unit column: unit taken from the page wording, refused when absent
    no_um = "<td>Prodotto</td><td>Prezzo minimo</td><td>Prezzo massimo</td>"
    ok = it.parse_cuneo_list_html(_cuneo_html("<tr><td>Acacia</td><td>7,50</td><td>8,50</td></tr>", header=no_um,
                                              note="Prezzi in €/kg, IVA compresa"))
    assert ok.rows[0]["unit"] == "kg"
    with pytest.raises(it.SchemaDrift, match="unit"):
        it.parse_cuneo_list_html(_cuneo_html("<tr><td>Acacia</td><td>7,50</td><td>8,50</td></tr>", header=no_um,
                                             note="IVA compresa"))


def test_cuneo_schema_drift_and_malformed_rows():
    with pytest.raises(it.SchemaDrift, match="Prezzo min"):
        it.parse_cuneo_list_html(_cuneo_html("<tr><td>Acacia</td><td>al kg</td><td>8,00</td></tr>",
                                             header="<td>Prodotto</td><td>Unità di misura</td><td>Prezzo</td>"))
    with pytest.raises(it.SchemaDrift, match="date"):
        it.parse_cuneo_list_html(_cuneo_html("<tr><td></td><td>Acacia</td><td>al kg</td><td>7,50</td><td>8,50</td><td>10%</td><td></td></tr>",
                                             title="rilevazione mensile"))
    with pytest.raises(it.SchemaDrift):
        it.parse_cuneo_list_csv(b"Prodotto,Prezzo\nAcacia,8\n")
    lst = it.parse_cuneo_list_html(_cuneo_html(
        "<tr><td></td><td>- Acacia (fusto da 3 q.li)</td><td>al kg</td><td>7,50</td><td>8,5O</td><td>10%</td><td></td></tr>"
        "<tr><td></td><td>- Castagno (fusto da 3 q.li)</td><td>al kg</td><td>6,50</td><td>5,50</td><td>10%</td><td></td></tr>"
        "<tr><td></td><td>- Tiglio (fusto da 3 q.li)</td><td>litri</td><td>6,50</td><td>7,00</td><td>10%</td><td></td></tr>"
        "<tr><td></td><td>- Millefiori (fusto da 3 q.li)</td><td>al kg</td><td>5,50</td><td>6,50</td><td>10%</td><td></td></tr>"))
    assert [r["name"] for r in lst.rows] == ["Millefiori"]
    assert len(lst.problems) == 3
    assert any("unparseable" in p for p in lst.problems) and any("min 6.5 > max 5.5" in p for p in lst.problems)


def test_cuneo_real_averages_pdf():
    avg = it.parse_cuneo_averages_pdf(fx("real_cuneo_medie_2025.pdf"), year=2025)
    assert avg.method == "table" and avg.year == 2025 and avg.problems == []
    assert avg.non_honey == ["Polline deumidificato (sacchi da 5 kg)"]
    rows = {r["key"]: r for r in avg.rows}
    assert list(rows) == ["acacia", "millefiori", "castagno", "melata-di-bosco", "tiglio",
                          "millefiori-di-alta-montagna", "rododendro", "melata-d-abete"]
    acacia = rows["acacia"]
    assert acacia["monthly"] == {5: 8.25, 6: 8.25, 7: 8.25, 8: 8.0, 9: 8.0, 10: 8.0, 11: 8.0, 12: 8.0}  # Genn.-Apr. '-'
    assert acacia["annual"] == 8.09 and acacia["price_group"] == "Prezzo minimo massimo"
    assert acacia["packaging_code"] == "fusto_3q" and acacia["unit"] == "kg"
    assert rows["millefiori"]["monthly"][12] == 5.55 and rows["millefiori"]["annual"] == 5.83
    assert sorted(rows["castagno"]["monthly"]) == [1, 2, 3, 4, 7, 8, 9, 10, 11, 12]
    assert rows["tiglio"]["packaging_code"] == "secchio_25kg" and rows["tiglio"]["annual"] == 6.59
    assert rows["melata-d-abete"]["monthly"] == {12: 9.0} and rows["melata-d-abete"]["variety"] == "honeydew"
    # an averages cell is the midpoint of that month's list min and max (Sept 2025 list: 7,50-8,50)
    sept = {r["key"]: r for r in it.parse_cuneo_list_html(fx("real_cuneo_list_18861.html")).rows}
    for key in ("acacia", "millefiori", "castagno", "melata-di-bosco", "tiglio", "rododendro"):
        assert sept[key]["value"] == rows[key]["monthly"][9], key
    # the same page without detectable ruling: the word-position fallback reads the same rows
    words = it.parse_cuneo_averages_pdf(fx("real_cuneo_medie_2025_rewritten_norules.pdf"), year=2025)
    assert words.method == "words" and words.rows == avg.rows and words.problems == []
    with pytest.raises(it.SchemaDrift, match="2023"):
        it.parse_cuneo_averages_pdf(fx("real_cuneo_medie_2025.pdf"), year=2023)
    with pytest.raises(it.SchemaDrift, match="twelve months"):
        it.parse_cuneo_averages_pdf(fx("real_siena_listino_n44_2026_p1_p5.pdf"))
    with pytest.raises(CollectorError, match="PDF"):
        it.parse_cuneo_averages_pdf(b"<html>not a pdf</html>")


def _only_lists(page: bytes, keep: set[int]) -> bytes:
    """The real honey chapter page with its list menu restricted to `keep` (test routing)."""
    soup = BeautifulSoup(page, "lxml")
    for a in soup.find_all("a", href=True):
        m = it._LISTCAT_RE.search(a["href"])
        if m and int(m.group(1)) not in keep:
            (a.find_parent("li") or a).decompose()
    return str(soup).encode()


def _cuneo_routes(page: bytes | None = None, **overrides) -> dict:
    routes = {
        CUNEO_HONEY: page or _only_lists(fx("real_cuneo_category_miele.html"), {20353}),
        CUNEO_HTML_20353: fx("real_cuneo_list_20353.html"),
        CUNEO_AVG_2025: (200, fx("real_cuneo_medie_2025.pdf"), "application/pdf"),
        CUNEO_ANY_AVG: (404, b"not found"),
    }
    routes.update(overrides)
    return routes


def test_cuneo_end_to_end_real_and_idempotent(run_with_routes, session_factory, today_2026):
    res = run_with_routes("cciaa_cuneo_miele", _cuneo_routes())
    assert res["status"] == "success", res
    with session_factory() as s:
        rows = _prices(s, "cciaa_cuneo_miele")
        lists = [r for r in rows if r.series_key.startswith("wholesale_bulk|cuneo|")]
        assert len(lists) == 7 and {r.period_label for r in lists} == {"2026-09"}
        acacia = next(r for r in lists if r.variety == "acacia")
        assert acacia.series_key == "wholesale_bulk|cuneo|acacia|2026-09"
        assert acacia.price_type == "wholesale_bulk" and acacia.market_iso3 == "ITA"
        assert acacia.market_location == "Cuneo" and acacia.origin_iso3 == "ITA"
        assert (acacia.price_low, acacia.price_high, acacia.price_value) == (7.0, 8.0, 7.5)
        assert acacia.currency == "EUR" and acacia.unit == "kg" and acacia.price_per_kg == 7.5
        assert acacia.period_start == date(2026, 9, 1) and acacia.period_end == date(2026, 9, 30)
        assert acacia.published_at == date(2026, 9, 30) and acacia.frequency == "M"
        assert acacia.data_status == "published" and acacia.reliability == "industry"
        assert acacia.source_url == CUNEO_HTML_20353 and acacia.raw_document_id
        assert acacia.variety_raw == "Acacia"
        # one stable wording per product (the list's exact wording and VAT rate stay in extra)
        assert acacia.terms == "fusto da 3 q.li; franco partenza dal magazzino; IVA compresa"
        assert acacia.extra["vat_rate_pct"] == 10
        assert acacia.extra["packaging_code"] == "fusto_3q" and acacia.extra["drum"] is True
        assert acacia.extra["vat_included"] is True and acacia.extra["list_category"] == 20353
        tiglio = next(r for r in lists if r.variety == "linden")
        assert (tiglio.price_low, tiglio.price_high) == (4.8, 5.8) and tiglio.extra["drum"] is False
        assert not any("polline" in (r.variety_raw or "").lower() for r in rows)      # never stored as honey
        assert not any(r.variety == "honeydew" for r in lists)       # Melata 'n.q.' = not quoted, nothing stored
        # back-fill: 2025 averages (no 2025 list held -> every month is a gap), flagged as averages
        avgs = [r for r in rows if r.series_key.startswith("wholesale_bulk|cuneo-media|")]
        monthly = [r for r in avgs if r.frequency == "M"]
        annual = [r for r in avgs if r.frequency == "A"]
        assert len(annual) == 8 and len(monthly) == 73
        acacia_y = next(r for r in annual if r.variety == "acacia")
        assert acacia_y.series_key == "wholesale_bulk|cuneo-media|acacia|2025"
        assert acacia_y.price_value == 8.09 and acacia_y.period_label == "2025" and acacia_y.price_low is None
        assert acacia_y.extra["statistic"] == "annual_average" and acacia_y.data_status == "published"
        assert "media tra prezzo minimo e massimo" in acacia_y.notes
        assert acacia_y.terms == "fusto da 3 q.li; media annua; franco partenza dal magazzino; IVA compresa"
        assert acacia_y.extra["vat_included"] is True
        dec = next(r for r in monthly if r.variety_raw == "Millefiori" and r.period_label == "2025-12")
        assert dec.price_value == 5.55 and dec.extra["statistic"] == "monthly_average"
        assert not any(r.period_label in ("2025-01", "2025-02", "2025-03", "2025-04") and r.variety == "acacia"
                       for r in monthly)                            # '-' in the PDF: no quotation
    res2 = run_with_routes("cciaa_cuneo_miele", _cuneo_routes())
    assert res2["status"] == "no_change", res2
    assert res2["new"] == 0 and res2["revised"] == 0


def test_cuneo_monthly_list_wins_over_the_average(run_with_routes, session_factory, today_2026):
    """A month held as a min-max list quotation is not filled again from the averages PDF, even
    when the list labels the item differently ('quantitativi >10 q.li' vs 'fusto da 3 q.li')."""
    page = _only_lists(fx("real_cuneo_category_miele.html"), {20353, 18861})
    res = run_with_routes("cciaa_cuneo_miele", _cuneo_routes(page, **{CUNEO_HTML_18861: fx("real_cuneo_list_18861.html")}))
    assert res["status"] == "success", res
    with session_factory() as s:
        acacia = [r for r in _prices(s, "cciaa_cuneo_miele") if r.variety == "acacia"]
        sept = [r for r in acacia if r.period_label == "2025-09"]
        assert [(r.series_key, r.price_low, r.price_high) for r in sept] == [("wholesale_bulk|cuneo|acacia|2025-09", 7.5, 8.5)]
        assert sept[0].extra["packaging"] == "fusti da 3 q.li (quantitativi >10 q.li)" and sept[0].extra["drum"] is True
        aug = [r for r in acacia if r.period_label == "2025-08"]
        assert [(r.series_key, r.price_value) for r in aug] == [("wholesale_bulk|cuneo-media|acacia|2025-08", 8.0)]


def test_cuneo_average_for_a_month_the_list_did_not_quote_is_flagged(run_with_routes, session_factory, today_2026):
    """Real disagreement: the list of 30 May 2025 says 'n.q.' for Tiglio, Millefiori di Alta
    Montagna and Rododendro, while the 2025 averages PDF prints May values (6,50 / 8,00 /
    8,50). The published average is kept, flagged and explained; nothing is resolved."""
    page = _only_lists(fx("real_cuneo_category_miele.html"), {20353, 18386})
    res = run_with_routes("cciaa_cuneo_miele", _cuneo_routes(page, **{CUNEO_HTML.format(id=18386): fx("real_cuneo_list_18386.html")}))
    assert res["status"] == "success", res
    with session_factory() as s:
        may = {r.series_key: r for r in _prices(s, "cciaa_cuneo_miele") if r.period_label == "2025-05"}
        tiglio = may["wholesale_bulk|cuneo-media|tiglio|2025-05"]
        assert tiglio.price_value == 6.5 and tiglio.extra["list_says_not_quoted"] is True
        assert "riporta 'n.q.'" in tiglio.notes
        assert may["wholesale_bulk|cuneo-media|rododendro|2025-05"].price_value == 8.5
        # acacia was quoted (8,00-8,50): the list wins, no average for that month
        assert (may["wholesale_bulk|cuneo|acacia|2025-05"].price_low, may["wholesale_bulk|cuneo|acacia|2025-05"].price_high) == (8.0, 8.5)
        assert "wholesale_bulk|cuneo-media|acacia|2025-05" not in may
        june = next(r for r in _prices(s, "cciaa_cuneo_miele") if r.series_key == "wholesale_bulk|cuneo-media|tiglio|2025-06")
        assert "list_says_not_quoted" not in june.extra                  # no list held for June: plain gap fill


def test_cuneo_list_selection_newest_and_backfill_window(run_with_routes, monkeypatch, today_2026):
    """The newest CUNEO_MAX_LISTS lists every run, plus never-downloaded lists of the last 24
    months (at most CUNEO_MAX_NEW_LISTS per run)."""
    seen: list[int] = []
    monkeypatch.setattr(it.CuneoHoneyCollector, "_import_list",
                        lambda self, ctx, link, newest=True: seen.append(link.list_category))
    monkeypatch.setattr(it.CuneoHoneyCollector, "_backfill_averages", lambda self, ctx: None)
    run_with_routes("cciaa_cuneo_miele", {CUNEO_HONEY: fx("real_cuneo_category_miele.html")})
    links = it.find_cuneo_lists(fx("real_cuneo_category_miele.html"))
    in_window = [link.list_category for link in links if link.list_date >= date(2024, 11, 1)]
    assert seen == in_window and seen[-1] == 17545 and len(seen) == 23     # 30 Nov 2024 is the oldest kept
    seen.clear()
    monkeypatch.setattr(it, "CUNEO_MAX_NEW_LISTS", 2)
    run_with_routes("cciaa_cuneo_miele", {CUNEO_HONEY: fx("real_cuneo_category_miele.html")})
    assert seen == [20353, 20204, 20063, 19954, 19842]


def test_cuneo_chapter_moved(run_with_routes, session_factory, today_2026):
    """category=11 no longer shows 'Miele': the chapter menu entry is followed (with a warning)."""
    moved = "https://www.cuneoprezzi.it/ingrosso/alimentari/?category=99"
    index = fx("real_cuneo_index_alimentari.html").replace(b"?category=11", b"?category=99")
    routes = _cuneo_routes(**{CUNEO_HONEY: index,
                              moved: _only_lists(fx("real_cuneo_category_miele.html"), {20353})})
    res = run_with_routes("cciaa_cuneo_miele", routes)
    assert res["status"] == "partial" and any("now at" in w and moved in w for w in res["warnings"]), res
    with session_factory() as s:
        assert len([r for r in _prices(s, "cciaa_cuneo_miele") if r.period_label == "2026-09"]) == 7
    no_menu = _cuneo_routes(**{CUNEO_HONEY: b"<html><body><h2 class='content_data_title'>Cereali</h2></body></html>"})
    res = run_with_routes("cciaa_cuneo_miele", no_menu)
    assert res["status"] == "failed" and "Miele" in res["error"]


def _averages_pdf_2025(december: str, media: str) -> bytes:
    """A one-row 'Miele - medie 2025' PDF in the real header layout (G.P. | Genn. ... Dic. |
    Anno), written with the dependency-free PDF writer of the EU fixtures. Test data."""
    spec = importlib.util.spec_from_file_location("eu_fixture_builder", FIXTURES / "eu" / "build_fixtures.py")
    b = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(b)
    months = ["Genn.", "Febb.", "Mar.", "Apr.", "Magg.", "Giu.", "Lug.", "Ago.", "Sett.", "Ott.", "Nov.", "Dic."]
    rows = [["", "G.P.", *months, "Anno"],
            ["- Acacia (fusto da 3 q.li)", "Prezzo", *["8,00"] * 11, december or "-", media]]
    page = (b.text(40, 540, "Miele - medie 2025", 14)
            + b.text(40, 520, "Prodotto sfuso in fusti da 3 q.li - franco partenza dal magazzino IVA compresa", 9)
            + b.table(24, 500, [150, 34] + [44] * 12 + [44], rows, size=8))
    return b.build_pdf([page], "Miele - medie 2025")


def test_cuneo_last_years_averages_are_read_again_until_settled(run_with_routes, session_factory, monkeypatch):
    """CUNEO-1: in January last year's averages PDF is still incomplete; later copies are read."""
    partial = _averages_pdf_2025("", "8,00")             # December not out yet: 'Anno' over 11 months
    complete = _averages_pdf_2025("8,60", "8,05")
    corrected = _averages_pdf_2025("8,60", "8,10")

    def run(day: date, pdf: bytes) -> dict:
        monkeypatch.setattr(it, "_today", lambda: day)
        return run_with_routes("cciaa_cuneo_miele", _cuneo_routes(**{CUNEO_AVG_2025: (200, pdf, "application/pdf")}))

    def acacia_2025(s) -> tuple[list, list]:
        rows = [r for r in _prices(s, "cciaa_cuneo_miele") if r.series_key.startswith("wholesale_bulk|cuneo-media|")]
        annual = [r for r in rows if r.frequency == "A" and r.period_label == "2025"]
        return annual, [r for r in rows if r.period_label == "2025-12"]

    assert run(date(2026, 1, 6), partial)["status"] == "success"
    with session_factory() as s:
        annual, dec = acacia_2025(s)
        assert [(r.price_value, r.data_status) for r in annual] == [(8.0, "provisional")] and dec == []
        assert "provvisoria" in annual[0].notes
    # three weeks later the PDF holds December: it is fetched again and the mean is revised
    res = run(date(2026, 1, 27), complete)
    assert res["status"] == "success" and res["revised"] == 1 and res["new"] == 1, res
    with session_factory() as s:
        annual, dec = acacia_2025(s)
        assert [(r.price_value, r.data_status, r.revision) for r in annual] == [(8.05, "provisional", 2)]
        assert [r.price_value for r in dec] == [8.6]
    # the first run after the settle date reads it once more: same bytes, mean now published
    res = run(date(2026, 4, 7), complete)
    assert res["status"] == "success" and res["revised"] == 1 and res["new"] == 0, res
    with session_factory() as s:
        annual, _ = acacia_2025(s)
        assert [(r.price_value, r.data_status) for r in annual] == [(8.05, "published")]
        assert "provvisoria" not in annual[0].notes
    # settled: the year is no longer requested (a later edit of the PDF is not picked up)
    res = run(date(2026, 4, 14), corrected)
    assert res["status"] == "no_change", res
    with session_factory() as s:
        assert [r.price_value for r in acacia_2025(s)[0]] == [8.05]
        hist = s.scalars(select(PriceObservation).where(PriceObservation.series_key.like("%cuneo-media|acacia|2025"))
                         .order_by(PriceObservation.revision)).all()
        assert [(r.price_value, r.data_status) for r in hist] == [
            (8.0, "provisional"), (8.05, "provisional"), (8.05, "published")]


def test_cuneo_csv_fallback_when_html_download_fails(run_with_routes, session_factory, today_2026):
    routes = _cuneo_routes(**{CUNEO_HTML_20353: (404, b"no"), CUNEO_CSV_20353: fx("real_cuneo_list_20353.csv")})
    res = run_with_routes("cciaa_cuneo_miele", routes)
    assert res["status"] == "success", res
    with session_factory() as s:
        acacia = next(r for r in _prices(s, "cciaa_cuneo_miele") if r.variety == "acacia" and r.period_label == "2026-09")
        assert acacia.source_url == CUNEO_CSV_20353 and acacia.extra["format"] == "csv"
        assert (acacia.price_low, acacia.price_high) == (7.0, 8.0)


def test_cuneo_schema_drift_fails_run(run_with_routes, session_factory, today_2026):
    drifted = fx("real_cuneo_list_20353.html").replace(b"Prezzo minimo", b"Quotazione").replace(b"Prezzo massimo", b"Note")
    res = run_with_routes("cciaa_cuneo_miele", _cuneo_routes(**{CUNEO_HTML_20353: drifted}))
    assert res["status"] == "failed" and "Prezzo min" in res["error"], res
    with session_factory() as s:
        assert _prices(s, "cciaa_cuneo_miele") == []


def test_cuneo_malformed_row_gives_partial_run(run_with_routes, session_factory, today_2026):
    page = fx("real_cuneo_list_20353.html")
    i = page.index(b"- Castagno")
    broken = page[:i] + page[i:].replace(b"5,50", b"abc", 1)
    res = run_with_routes("cciaa_cuneo_miele", _cuneo_routes(**{CUNEO_HTML_20353: broken}))
    assert res["status"] == "partial" and any("Castagno" in w for w in res["warnings"]), res
    with session_factory() as s:
        sept = [r for r in _prices(s, "cciaa_cuneo_miele") if r.period_label == "2026-09"]
        assert {r.variety_raw for r in sept} == {"Acacia", "Millefiori", "Tarassaco", "Tiglio",
                                                 "Millefiori di Alta Montagna", "Rododendro"}


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


REAL_ISMEA_2026_06 = {"Miele - Acacia": ("acacia", 8.0), "Miele - Agrumi": ("orange_blossom", 5.7),
                      "Miele - Castagno": ("chestnut", 4.9), "Miele - Eucalipto": ("eucalyptus", 5.25),
                      "Miele - Millefiori": ("polyflora", 4.2), "Miele - Sulla": ("other", 4.5),
                      "Miele - Tiglio": ("linden", 4.9)}


def test_ismea_real_variety_pages():
    """Real layout: header Piazza | Anno-Mese-Sett. | Prezzo | Variaz. ..., the variety in a
    'Miele - <Varietà>' group row above each 'Italia' row."""
    weekly = it.parse_ismea_prices(fx("real_ismea_11024_settimanali_varieta.html"))
    assert weekly.problems == [] and weekly.vat_included is None and weekly.updated is None   # neither stated
    assert weekly.title == "Api e Miele - Prezzi medi alla produzione"
    assert {r["product"]: (r["variety"], r["price"]) for r in weekly.rows} == REAL_ISMEA_2026_06
    acacia = weekly.rows[0]
    assert (acacia["market"], acacia["unit"], acacia["chg_prev"], acacia["chg_year"]) == ("Italia", "kg", 0.0, None)
    assert (acacia["period"]["label"], acacia["period"]["start"], acacia["period"]["end"]) == \
        ("2026-06-S4", date(2026, 6, 22), date(2026, 6, 28))
    monthly = it.parse_ismea_prices(fx("real_ismea_11026_mensili_varieta.html"))
    assert monthly.title == "Api e Miele - Prezzi medi alla produzione - f.co azienda" and monthly.problems == []
    assert {r["product"]: (r["variety"], r["price"]) for r in monthly.rows} == REAL_ISMEA_2026_06
    assert {r["period"]["label"] for r in monthly.rows} == {"2026-06"}


def test_ismea_schema_drift():
    with pytest.raises(it.SchemaDrift, match="Prezzo"):
        it.parse_ismea_prices(b"<table><tr><th>Varieta</th><th>Settimana</th><th>Valore</th></tr></table>")
    with pytest.raises(it.SchemaDrift, match="iframe"):
        it.parse_ismea_prices(b"<html><body><iframe src='/ReportServer?/Miele'></iframe></body></html>")
    with pytest.raises(it.SchemaDrift, match="unit"):
        it.parse_ismea_prices(b"<table><tr><th>Prodotto</th><th>Anno-Mese-Sett.</th><th>Prezzo</th></tr>"
                              b"<tr><td>Acacia</td><td>2026-6-4</td><td>8,00</td></tr></table>")
    bad = it.parse_ismea_prices(b"<table><tr><th>Piazza</th><th>Anno-Mese-Sett.</th><th>Prezzo</th></tr>"
                                b"<tr><th>Italia</th><td>2026-6-4</td><td>9,00 &euro;/Kg</td></tr>"   # no group row yet
                                b"<tr><th colspan='3'>Miele - Acacia</th></tr>"
                                b"<tr><th>Italia</th><td>2026-6-9</td><td>8,00 &euro;/Kg</td></tr>"
                                b"<tr><th colspan='3'>Miele - Tiglio</th></tr>"
                                b"<tr><th>Italia</th><td>2026-6-4</td><td>circa 5</td></tr>"
                                b"<tr><th colspan='3'>Miele - Castagno</th></tr>"
                                b"<tr><th>Italia</th><td>2026-6-4</td><td>4,90 &euro;/Kg</td></tr></table>")
    assert [r["product"] for r in bad.rows] == ["Miele - Castagno"] and len(bad.problems) == 3


def test_ismea_end_to_end_real_and_idempotent(run_with_routes, session_factory):
    routes = {ISMEA_WEEKLY: fx("real_ismea_11024_settimanali_varieta.html"),
              ISMEA_MONTHLY: fx("real_ismea_11026_mensili_varieta.html")}
    res = run_with_routes("ismea_miele", routes)
    assert res["status"] == "success" and res["new"] == 14, res
    with session_factory() as s:
        rows = _prices(s, "ismea_miele")
        assert {r.price_type for r in rows} == {"producer"} and {r.unit for r in rows} == {"kg"}
        weekly = {r.variety_raw: r for r in rows if r.frequency == "W"}
        monthly = {r.variety_raw: r for r in rows if r.frequency == "M"}
        assert {k: (v.variety, v.price_value) for k, v in weekly.items()} == REAL_ISMEA_2026_06
        assert {k: (v.variety, v.price_value) for k, v in monthly.items()} == REAL_ISMEA_2026_06
        acacia = weekly["Miele - Acacia"]
        assert acacia.currency == "EUR" and acacia.source_url == ISMEA_WEEKLY
        assert (acacia.period_start, acacia.period_end, acacia.period_label) == (date(2026, 6, 22), date(2026, 6, 28), "2026-06-S4")
        assert acacia.market_iso3 == "ITA" and acacia.origin_iso3 == "ITA" and acacia.market_location == "Italia"
        assert acacia.reliability == "official" and acacia.data_status == "published" and acacia.published_at is None
        assert acacia.extra["period_raw"] == "2026-6-4" and acacia.notes and "convenzione" in acacia.notes
        # the pages state no VAT treatment: recorded as not stated, never assumed
        assert acacia.terms == "prezzo medio alla produzione; IVA non indicata"
        assert acacia.extra["vat_included"] is None and acacia.extra["vat_source"] == "not_stated"
        mf = monthly["Miele - Millefiori"]
        assert mf.terms == "prezzo medio alla produzione, franco azienda; IVA non indicata"
        assert (mf.period_start, mf.period_end, mf.price_value) == (date(2026, 6, 1), date(2026, 6, 30), 4.2)
        assert mf.source_url == ISMEA_MONTHLY
    assert run_with_routes("ismea_miele", routes)["status"] == "no_change"


# -------------------------------------------------------------------------------------- ONM


def test_onm_discovery_paths():
    real = it.discover_onm_from_feed(fx("real_onm_feed.xml"), it.ONM_FEED_URL)
    assert [(p.kind, p.ref_year, p.ref_month, p.published) for p in real] == [
        ("monthly", 2026, 9, date(2026, 10, 20)), ("other", None, None, date(2026, 9, 30)),
        ("monthly", 2026, 8, date(2026, 9, 17))]                     # 'Report di Prime Valutazioni' is not a bulletin
    assert real[0].url == ONM_SETTEMBRE
    feed = it.discover_onm_from_feed(fx("onm_feed.xml"))           # reconstructed: carries a priced bulletin
    kinds = {(p.kind, p.ref_year, p.ref_month, p.season) for p in feed}
    assert ("monthly", 2026, 8, None) in kinds and ("monthly", 2026, 7, None) in kinds
    assert ("annual", None, None, 2025) in kinds
    rest = it.discover_onm_from_wp_json(fx("onm_wp_posts.json"))
    assert [(p.kind, p.ref_month) for p in rest] == [("monthly", 8), ("monthly", 7), ("other", None)]
    listing = it.discover_onm_from_listing(fx("onm_listing_comunicati.html"), "https://www.informamiele.it/category/comunicati/")
    assert {(p.ref_year, p.ref_month, p.published) for p in listing} == {
        (2026, 8, date(2026, 9, 21)), (2026, 7, date(2026, 8, 20)), (2022, 8, date(2022, 9, 15))}
    with pytest.raises(CollectorError):
        it.discover_onm_from_feed(b"<html><body>Not a feed</body></html>")
    with pytest.raises(CollectorError):
        it.discover_onm_from_wp_json(b'{"code": "rest_no_route"}')
    archive = it.find_onm_annual_pdfs(fx("real_onm_report_archive.html"), it.ONM_REPORT_ARCHIVE_URL)
    assert archive[0].url == ONM_PDF_2025 and archive[0].season == 2025
    assert len(archive) == 12 and not any("prime" in link.url.lower() for link in archive)   # 'Prime Valutazioni' excluded


def test_onm_real_posts_market_text():
    sett = it.parse_onm_post(fx("real_onm_post_settembre_2026.html"))
    assert sett.published == date(2026, 10, 20) and sett.has_market_section
    assert sett.market_paragraphs[0].startswith("Le transazioni rilevate nel mese di settembre")
    assert not any("MIELEINFORMA" in p or p.startswith("Ricordiamo") for p in sett.market_paragraphs)   # boilerplate
    assert it.extract_onm_prices(sett.market_paragraphs) == []
    ago = it.parse_onm_post(fx("real_onm_post_agosto_2026.html"))
    assert ago.published == date(2026, 9, 17)
    assert any("attorno ai 4,00 €/kg per il millefiori" in p for p in ago.market_paragraphs)
    assert it.extract_onm_prices(ago.market_paragraphs) == []           # a single offer value is never stored


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
        # a foreign honey named as context, not as the origin of the quoted price (ONM-2)
        "Nel mercato all'ingrosso, complice la concorrenza del miele ucraino, il millefiori in fusti è quotato tra 4 e 4,50 €/kg.",
        ("Nel mercato all'ingrosso, nonostante la pressione del miele d'importazione, il millefiori in fusti è "
         "quotato tra 4 e 4,50 €/kg."),
        "Il miele ungherese in fusti: acacia 4,8-5,2 €/kg, millefiori 3-3,5 €/kg.",          # origin opens the list
    ):
        assert it.extract_onm_prices([sentence]) == [], sentence
    # the same item twice with different numbers in one bulletin is ambiguous -> dropped
    assert it.extract_onm_prices(["In fusti il millefiori tra 4 e 5 €/kg.", "In fusti il millefiori tra 6 e 7 €/kg."]) == []


def _onm_rows(sentence: str) -> list[tuple]:
    return [(o["variety_raw"], o["low"], o["high"], o["packaging_code"], o["organic"], o["origin_iso3"])
            for o in it.extract_onm_prices([sentence])]


def test_onm_qualifiers_belong_to_their_own_pair():
    """ONM-1: a qualifier written after a price belongs to that price, not to the next variety."""
    # (a) '(fusto)' / '(latta)' after each price: the tin prices are not stored as drum prices
    assert _onm_rows("Sul mercato all'ingrosso il millefiori si scambia tra 4 e 4,5 €/kg (fusto), il castagno tra "
                     "6,5 e 6,7 €/kg (latta) e l'acacia tra 8,5 e 9 €/kg (latta).") == [
        ("millefiori", 4.0, 4.5, "fusto", False, "ITA"),
        ("castagno", 6.5, 6.7, "secchio", False, "ITA"),
        ("acacia", 8.5, 9.0, "secchio", False, "ITA"),
    ]
    # (b) '(bio)' after the castagno price is the castagno's, not the acacia's
    assert _onm_rows("Sul mercato all'ingrosso il millefiori si scambia tra 4 e 4,5 €/kg, il castagno tra 7 e "
                     "7,5 €/kg (bio), l'acacia tra 8,5 e 9 €/kg.") == [
        ("millefiori", 4.0, 4.5, "non_specificato", False, "ITA"),
        ("castagno", 7.0, 7.5, "non_specificato", True, "ITA"),
        ("acacia", 8.5, 9.0, "non_specificato", False, "ITA"),
    ]
    # (c) '(ungherese)' after the acacia price: Hungarian acacia, Italian millefiori
    assert _onm_rows("Sul mercato all'ingrosso l'acacia si scambia tra 4,8 e 5,2 €/kg (ungherese), il millefiori "
                     "tra 4 e 4,5 €/kg.") == [
        ("acacia", 4.8, 5.2, "non_specificato", False, "HUN"),
        ("millefiori", 4.0, 4.5, "non_specificato", False, "ITA"),
    ]
    # (d) prefix style: ', in latta il castagno' leads into the castagno
    assert _onm_rows("In fusti il millefiori 4-4,5 €/kg, in latta il castagno 6,5-6,7 €/kg.") == [
        ("millefiori", 4.0, 4.5, "fusto", False, "ITA"),
        ("castagno", 6.5, 6.7, "secchio", False, "ITA"),
    ]
    # (e) a bare 'in fusto' between two pairs could be either's: never given to the castagno
    rows = _onm_rows("Sul mercato all'ingrosso il millefiori si scambia a 4-4,5 €/kg in fusto, il castagno a "
                     "6,5-6,7 €/kg, mentre in latta l'acacia tra 8,5 e 9 €/kg.")
    assert ("acacia", 8.5, 9.0, "secchio", False, "ITA") in rows
    assert not [r for r in rows if r[0] == "castagno"]
    assert all(r[3] == "fusto" for r in rows if r[0] == "millefiori")
    # a tin named in a later segment is not a fallback for an earlier, unqualified pair
    assert _onm_rows("All'ingrosso il millefiori tra 4 e 4,5 €/kg; in latta il castagno tra 6,5 e 6,7 €/kg.") == [
        ("millefiori", 4.0, 4.5, "non_specificato", False, "ITA"),
        ("castagno", 6.5, 6.7, "secchio", False, "ITA"),
    ]


def test_onm_origin_only_from_the_subjects_own_clause():
    """ONM-2: the origin is read where it qualifies the variety, never from context words."""
    assert _onm_rows("Il miele ungherese di acacia in fusti è offerto tra 4,80 e 5,20 €/kg.") == [
        ("acacia", 4.8, 5.2, "fusto", False, "HUN")]
    assert _onm_rows("In fusti il millefiori ungherese è offerto tra 3 e 3,5 €/kg.") == [
        ("millefiori", 3.0, 3.5, "fusto", False, "HUN")]
    # price-first wording: the adjective after the variety is read too
    assert _onm_rows("All'ingrosso si pagano 6,50-6,70 €/kg per il castagno ungherese, 4-4,5 €/kg per il millefiori.") == [
        ("castagno", 6.5, 6.7, "non_specificato", False, "HUN"),
        ("millefiori", 4.0, 4.5, "non_specificato", False, "ITA"),
    ]


def test_onm_real_annual_report_2025_tables():
    t = it.parse_onm_annual_pdf(fx("real_onm_report_annuale_2025_p42_p46.pdf"))
    assert t.problems == [] and t.import_rows == []        # import prices by origin are a chart only (p. 41)
    assert t.variety_caption == ("Prezzi all'ingrosso rilevati nel 2025 per i principali mieli convenzionali in "
                                 "fusti da 300 kg. Partite superiori ai 30 q.li. Euro/kg Iva inclusa, franco produttore.")
    assert t.variety_year == 2025
    assert t.variety_note == ("Nota: Per i corrispondenti mieli biologici il differenziale di prezzo è circa il "
                              "10-12% in più.")
    assert [(r["label"], r["variety"], r["low"], r["high"], r["value"], r["change_pct"]) for r in t.variety_rows] == [
        ("Acacia", "acacia", 7.5, 8.5, 8.0, 2.6),
        ("Agrumi", "orange_blossom", 5.6, 6.0, 5.7, -1.7),          # 'Medio' is not the midpoint of min-max
        ("Castagno", "chestnut", 4.8, 5.0, 4.9, 0.0),
        ("Millefiori", "polyflora", 4.0, 4.5, 4.2, -6.7),
    ]


def test_onm_annual_table_rules(monkeypatch):
    def lines(*pages):
        monkeypatch.setattr(it, "_pdf_lines", lambda content: [list(p) for p in pages])
        return it.parse_onm_annual_pdf(b"%PDF")

    # the real 2024 caption names the currency but not the unit: refused, never guessed
    t = lines(["Prezzi principali mieli convenzionali in fusti da 300 kg. Partite superiori ai 30 q.li.",
               "Euro Iva inclusa, franco produttore.", "TIPO VARIAZIONE %", "Min Max Medio", "di miele 2024/2023",
               "Acacia 7,5 8,5 7,8 18,2%", "Agrumi 5,6 6,1 5,8 11,5%"])
    assert t.variety_rows == [] and "does not state EUR/kg" in t.problems[0]
    # two tables answering the same caption -> ambiguous, none imported
    page = ["Prezzi all'ingrosso dei mieli in fusti (Euro/kg)", "Varietà Min Max Media", "Acacia 8,50 10,50 9,40"]
    dup = lines(page, page)
    assert dup.variety_rows == [] and "ambiguous" in dup.problems[0]
    # a row with a missing cell is not guessed
    gap = lines(["Prezzi all'ingrosso dei mieli in fusti (Euro/kg)", "Varietà Min Max Media", "Acacia 8,50 9,40",
                 "Tiglio 6,00 7,20 6,60"])
    assert [r["label"] for r in gap.variety_rows] == ["Tiglio"] and "2 values for 3 columns" in gap.problems[0]
    # an import table by country of origin is read when present (test data: no real report has one so far)
    imp = lines(["Prezzi del miele d'importazione per paese di origine", "Euro al kg, prodotto sdoganato in fusti",
                 "Paese di origine Min Max Media", "Argentina 2,60 3,10 2,85", "Ucraina 2,20 2,70 2,45",
                 "Altri paesi 2,00 3,50 2,70"])
    assert {r["origin_iso3"]: r["value"] for r in imp.import_rows} == {"ARG": 2.85, "UKR": 2.45}
    # a regional or swarm table is not a variety table
    other = lines(["Prezzi sciami su 5 telai e regine da apicoltura convenzionale (in Euro Iva esclusa)",
                   "SCIAMI REGINE", "AREA", "di rilevazione", "Min Max Min Max", "Nord 100 130 16 20"])
    assert other.variety_rows == [] and other.problems == []


def _real_onm_routes(**overrides) -> dict:
    routes = {
        it.ONM_FEED_URL: (200, fx("real_onm_feed.xml"), "application/rss+xml; charset=UTF-8"),
        ONM_SETTEMBRE: fx("real_onm_post_settembre_2026.html"),
        ONM_AGOSTO: fx("real_onm_post_agosto_2026.html"),
        it.ONM_REPORT_ARCHIVE_URL: fx("real_onm_report_archive.html"),
        ONM_PDF_2025: (200, fx("real_onm_report_annuale_2025_p42_p46.pdf"), "application/pdf"),
    }
    routes.update(overrides)
    return routes


def test_onm_end_to_end_real_and_idempotent(run_with_routes, session_factory):
    res = run_with_routes("onm_informamiele", _real_onm_routes())
    assert res["status"] == "success", res
    with session_factory() as s:
        reports = _reports(s, "onm_informamiele")
        assert set(reports) == {"rilevazione-mensile-2026-09", "rilevazione-mensile-2026-08", "report-annuale-2025"}
        sett = reports["rilevazione-mensile-2026-09"]
        assert sett.published_at == date(2026, 10, 20) and sett.url == ONM_SETTEMBRE and sett.raw_document_id
        assert sett.narrative.startswith("Le transazioni rilevate nel mese di settembre")
        assert "MIELEINFORMA" not in sett.narrative
        annual_report = reports["report-annuale-2025"]
        assert annual_report.url == ONM_PDF_2025 and annual_report.raw_document_id
        rows = _prices(s, "onm_informamiele")
        assert not [r for r in rows if r.frequency == "M"]          # the bulletins give no unambiguous range
        annual = {r.variety: r for r in rows}
        assert {v: (r.price_low, r.price_high, r.price_value) for v, r in annual.items()} == {
            "acacia": (7.5, 8.5, 8.0), "orange_blossom": (5.6, 6.0, 5.7),
            "chestnut": (4.8, 5.0, 4.9), "polyflora": (4.0, 4.5, 4.2)}
        acacia = annual["acacia"]
        assert acacia.series_key == "wholesale_bulk|onm-annuale|2025|varieta|acacia"
        assert acacia.price_type == "wholesale_bulk" and acacia.unit == "kg" and acacia.currency == "EUR"
        assert (acacia.period_start, acacia.period_end, acacia.period_label, acacia.frequency) == \
            (date(2025, 1, 1), date(2025, 12, 31), "2025", "A")
        assert acacia.market_iso3 == "ITA" and acacia.origin_iso3 == "ITA" and acacia.data_status == "published"
        assert acacia.source_url == ONM_PDF_2025 and acacia.raw_document_id
        assert acacia.terms.startswith("Prezzi all'ingrosso rilevati nel 2025") and "Iva inclusa" in acacia.terms
        assert acacia.extra["change_vs_prev_year_pct"] == 2.6 and acacia.extra["value_column"] == "Medio"
        assert acacia.extra["packaging_code"] == "fusto_300kg" and acacia.extra["drum"] is True
        assert acacia.extra["vat_included"] is True
        assert acacia.notes.startswith("Nota: Per i corrispondenti mieli biologici")
    res2 = run_with_routes("onm_informamiele", _real_onm_routes())
    assert res2["status"] == "no_change" and res2["new"] == 0, res2


def test_onm_annual_report_without_readable_table_is_report_only(run_with_routes, session_factory, monkeypatch):
    monkeypatch.setattr(it, "_pdf_lines", lambda content: [["Andamento mercato miele", "Testo senza tabelle"]])
    res = run_with_routes("onm_informamiele", _real_onm_routes())
    assert res["status"] == "partial" and any("registered as a report without prices" in w for w in res["warnings"])
    with session_factory() as s:
        assert "report-annuale-2025" in _reports(s, "onm_informamiele")
        assert _prices(s, "onm_informamiele") == []


def _onm_routes(**overrides) -> dict:
    """Reconstructed feed and bulletins (priced prose), real archive and annual report."""
    routes = {
        it.ONM_FEED_URL: (200, fx("onm_feed.xml"), "application/rss+xml"),
        ONM_LUGLIO: fx("onm_post_luglio_2026.html"),
        ONM_AGOSTO: fx("onm_post_agosto_2026.html"),
        it.ONM_REPORT_ARCHIVE_URL: fx("real_onm_report_archive.html"),
        ONM_PDF_2025: (200, fx("real_onm_report_annuale_2025_p42_p46.pdf"), "application/pdf"),
    }
    routes.update(overrides)
    return routes


def test_onm_bulletin_prices_end_to_end(run_with_routes, session_factory):
    res = run_with_routes("onm_informamiele", _onm_routes())
    assert res["status"] == "success", res
    with session_factory() as s:
        reports = _reports(s, "onm_informamiele")
        assert {"rilevazione-mensile-2026-07", "rilevazione-mensile-2026-08", "report-annuale-2025"} <= set(reports)
        jul = reports["rilevazione-mensile-2026-07"]
        assert jul.published_at == date(2026, 8, 20) and jul.period_label == "2026-07" and jul.url == ONM_LUGLIO
        assert jul.narrative.startswith("Nel mese di luglio") and "regine" not in jul.narrative
        monthly = [r for r in _prices(s, "onm_informamiele") if r.frequency == "M"]
        assert len(monthly) == 3
        for r in monthly:
            assert r.data_status == "provisional" and r.notes.startswith("estratto dal testo del bollettino")
            assert r.period_label == "2026-07" and r.published_at == date(2026, 8, 20)
            assert r.market_iso3 == "ITA" and r.extra["needs_review"] is True and r.extra["context_sentence"]
            assert "franco produttore, IVA inclusa" in r.terms
        hun = next(r for r in monthly if r.origin_iso3 == "HUN")
        assert hun.variety == "acacia" and (hun.price_low, hun.price_high) == (4.8, 5.2)
        mf = next(r for r in monthly if r.variety == "polyflora")
        assert (mf.price_low, mf.price_high, mf.price_value, mf.origin_iso3) == (5.0, 6.5, 5.75, "ITA")
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
    assert any(ONM_AGOSTO in w and "feed/API copy" in w for w in res["warnings"]), res
    with session_factory() as s:
        reports = _reports(s, "onm_informamiele")
        ago = reports["rilevazione-mensile-2026-08"]
        assert ago.narrative.startswith("Rimane stazionario")
        assert ago.published_at == date(2026, 9, 21)
        # ONM-3: the REST answer the text was taken from is archived as downloaded
        copy = s.get(RawDocument, ago.raw_document_id)
        assert copy.url.startswith(it.ONM_WP_API_URL) and copy.content_hash == hashlib.sha256(fx("onm_wp_posts.json")).hexdigest()
        assert len([r for r in _prices(s, "onm_informamiele") if r.period_label == "2026-07"]) == 3


def test_onm_feed_copy_prices_point_to_the_archived_feed(run_with_routes, session_factory):
    """ONM-3: prices text-extracted from the feed copy keep a link to the bytes they came from."""
    res = run_with_routes("onm_informamiele", _onm_routes(**{ONM_LUGLIO: (500, b"Internal Server Error")}))
    assert res["status"] == "partial" and any(ONM_LUGLIO in w and "feed/API copy" in w for w in res["warnings"]), res
    with session_factory() as s:
        jul = [r for r in _prices(s, "onm_informamiele") if r.period_label == "2026-07"]
        # the feed copy holds the first market paragraph only (no Hungarian acacia)
        assert sorted(r.variety for r in jul) == ["acacia", "polyflora"]
        assert all(r.data_status == "provisional" for r in jul)
        assert {r.raw_document_id for r in jul} != {None}
        docs = {s.get(RawDocument, r.raw_document_id).url for r in jul}
        assert docs == {it.ONM_FEED_URL} and all(r.extra["parsed_from"] == it.ONM_FEED_URL for r in jul)
        assert all(r.source_url == ONM_LUGLIO for r in jul)
        assert _reports(s, "onm_informamiele")["rilevazione-mensile-2026-07"].raw_document_id == jul[0].raw_document_id


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


def test_siena_real_discovery():
    # the 'prezzi' page is the 2019 page: its newest own PDF is from February 2020 (the live bug)
    links, archives = it.find_siena_pdfs(fx("real_siena_prezzi.html"))
    assert (links[0].number, links[0].list_date) == (6, date(2020, 2, 12))
    assert archives[:2] == [SIENA_2026, "https://www.as.camcom.it/listini-prezzi-anno-2025"]
    years = it.siena_archive_years(fx("real_siena_prezzi.html"))
    assert sorted(years) == list(range(2018, 2027))
    assert years[2024] == "https://www.as.camcom.it/listini-prezzi-provincia-siena-anno-2024"   # slugs vary by year
    links, _ = it.find_siena_pdfs(fx("real_siena_anno_2026.html"), SIENA_2026)
    assert len(links) == 44
    assert (links[0].number, links[0].list_date, links[0].url) == (44, date(2026, 11, 4), SIENA_PDF_44)
    # 'listino_prezzi_n.1_2026.pdf' has no date in its name: number and date come from the link text
    assert (links[-1].number, links[-1].list_date) == (1, date(2026, 1, 7))
    assert links[-1].url.endswith("listino_prezzi_n.1_2026.pdf")


def test_siena_real_list_parse():
    lst = it.parse_siena_pdf(fx("real_siena_listino_n44_2026_p1_p5.pdf"))
    assert (lst.number, lst.list_date, lst.problems) == (44, date(2026, 11, 4), [])
    mf, sel = lst.rows
    assert (mf["label"], mf["variety"], mf["low"], mf["high"], mf["value"], mf["unit"]) == \
        ("Miele (millefiori)", "polyflora", 6.0, 7.0, 6.5, "kg")
    assert (sel["label"], sel["variety"], sel["low"], sel["high"]) == ("Miele (selezionati)", "other", 6.5, 10.0)
    assert mf["price_type"] == "wholesale_bulk" and mf["price_type_basis"] == "title"
    assert mf["price_type_words"] == "prezzi all'ingrosso"
    assert mf["section"] == "VARIE - IVA esclusa" and mf["vat_included"] is False and mf["vat_basis"] == "section"
    assert it._price_type_from_wording("PREZZI AL CONSUMO")[0] == "retail"
    assert it._price_type_from_wording("prezzi alla produzione")[0] == "producer"
    assert it._price_type_from_wording("prezzi all'ingrosso e al consumo") == (None, None)


def test_siena_schema_drift_and_unexpected_honey_line(monkeypatch):
    with pytest.raises(it.SchemaDrift, match="da Euro"):
        it.parse_siena_pdf(fx("siena_listino_drift.pdf"))
    monkeypatch.setattr(it, "_pdf_lines", lambda content: [[
        "Listino settimanale dei prezzi all'ingrosso accertati sulla piazza di Siena", "Listino n. 45 del 11.11.2026",
        "Denominazione della merce e qualità u. misura da Euro a Euro Variazione", "VARIE - IVA esclusa",
        "Miele (millefiori) al Kg. 6,00 7,00 +0,50",            # signed variation: read, not a price
        "Miele (selezionati) al Kg. 6,50 10,00 0,50",           # a third unsigned number: ambiguous
    ]])
    lst = it.parse_siena_pdf(b"%PDF")
    assert [(r["label"], r["low"], r["high"], r["change"]) for r in lst.rows] == [("Miele (millefiori)", 6.0, 7.0, 0.5)]
    assert len(lst.problems) == 1 and "Miele (selezionati)" in lst.problems[0]


def _siena_routes(**overrides) -> dict:
    routes = {it.SIENA_INDEX_URL: fx("real_siena_prezzi.html"),
              SIENA_2026: fx("real_siena_anno_2026.html"),
              SIENA_PDF_44: (200, fx("real_siena_listino_n44_2026_p1_p5.pdf"), "application/pdf")}
    routes.update(overrides)
    return routes


def test_siena_end_to_end_real_and_idempotent(run_with_routes, session_factory, today_2026):
    res = run_with_routes("cciaa_siena_miele", _siena_routes())
    assert res["status"] == "success" and res["new"] == 2, res
    with session_factory() as s:
        rows = _prices(s, "cciaa_siena_miele")
        mf = next(r for r in rows if r.variety == "polyflora")
        assert (mf.price_low, mf.price_high, mf.price_value, mf.unit, mf.currency) == (6.0, 7.0, 6.5, "kg", "EUR")
        assert mf.price_type == "wholesale_bulk" and mf.market_location == "Siena" and mf.origin_iso3 == "ITA"
        assert (mf.period_start, mf.period_end, mf.period_label) == (date(2026, 11, 2), date(2026, 11, 8), "2026-W45")
        assert mf.published_at == date(2026, 11, 4) and mf.frequency == "W"
        assert mf.terms == ("listino settimanale n. 44 del 04.11.2026; prezzi all'ingrosso; confezione non indicata; "
                            "IVA esclusa")
        assert mf.extra["vat_included"] is False and mf.extra["section"] == "VARIE - IVA esclusa"
        assert mf.extra["packaging_code"] == "non_specificato" and mf.source_url == SIENA_PDF_44
        sel = next(r for r in rows if r.variety_raw == "Miele (selezionati)")
        assert (sel.variety, sel.price_low, sel.price_high) == ("other", 6.5, 10.0)
    assert run_with_routes("cciaa_siena_miele", _siena_routes())["status"] == "no_change"


def test_siena_archive_fallback_stale_and_missing_links(run_with_routes, monkeypatch, today_2026):
    # prices page down: the 2026 archive URL pattern is tried directly
    res = run_with_routes("cciaa_siena_miele", _siena_routes(**{it.SIENA_INDEX_URL: (503, b"")}))
    assert res["status"] == "success", res
    # only the 2019 page links PDFs: used, with a warning
    old = ("https://www.as.camcom.it/sites/default/files/contenuto_redazione/pagina_base/allegati/"
           "listino_n._06_del_12-02-2020_0.pdf")
    res = run_with_routes("cciaa_siena_miele", _siena_routes(**{
        SIENA_2026: (404, b""), it.SIENA_ARCHIVE_URL.format(year=2025): (404, b""),
        "https://www.as.camcom.it/listini-prezzi-anno-2025": (404, b""),
        old: (200, fx("real_siena_listino_n44_2026_p1_p5.pdf"), "application/pdf")}))
    assert any("no yearly archive page" in w for w in res["warnings"]), res
    # nothing anywhere
    res = run_with_routes("cciaa_siena_miele", {
        it.SIENA_INDEX_URL: b"<html></html>", SIENA_2026: (404, b""),
        it.SIENA_ARCHIVE_URL.format(year=2025): b"<html></html>"})
    assert res["status"] == "failed" and "no weekly price-list PDF" in res["error"]


def test_siena_stale_newest_list_is_warned(run_with_routes, monkeypatch):
    monkeypatch.setattr(it, "_today", lambda: date(2026, 12, 31))
    res = run_with_routes("cciaa_siena_miele", _siena_routes(**{
        it.SIENA_ARCHIVE_URL.format(year=2025): (404, b""),
        "https://www.as.camcom.it/listini-prezzi-anno-2025": (404, b"")}))
    assert res["status"] == "partial" and any("older than 35 days" in w for w in res["warnings"]), res
