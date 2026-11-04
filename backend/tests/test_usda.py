"""USDA collectors: AMS National Honey Report (PDF), FAS GATS (Census imports), NASS Quick Stats.

All fixtures in tests/fixtures/usda/ are RECONSTRUCTED from documentation (see the README there):
the sandbox that built them could not reach the USDA hosts.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import asdict
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import func, select

from paladex import config
from paladex.collectors import usda
from paladex.collectors.base import CollectorError, redact_url
from paladex.collectors.usda import (
    describe,
    extract_color,
    lines_from_text,
    parse_esmis_releases,
    parse_gats_commodities,
    parse_gats_imports,
    parse_gats_release_dates,
    parse_honey_report_lines,
    parse_honey_report_pdf,
    parse_nass_rows,
    parse_price_token,
    select_gats_months,
    split_price_tail,
    words_to_lines,
)
from paladex.enums import DataStatus, PriceType
from paladex.models import (
    AppSetting,
    PriceObservation,
    ProductionStat,
    RawDocument,
    Report,
    Source,
    TradeFlowObservation,
)

FIX = Path(__file__).parent / "fixtures" / "usda"
LB = 0.45359237


def fx(name: str) -> bytes:
    return (FIX / name).read_bytes()


def count(s, model, *where) -> int:
    return s.scalar(select(func.count(model.id)).where(*where)) or 0


def one(s, model, *where):
    rows = s.scalars(select(model).where(*where)).all()
    assert len(rows) == 1, rows
    return rows[0]


def db_write_possible() -> bool:
    """True when another connection could start writing right now, i.e. no collector holds
    the SQLite write lock (a short timeout instead of the app's 10 s busy_timeout)."""
    from paladex.db import get_engine

    con = sqlite3.connect(get_engine().url.database, timeout=0.2)
    try:
        con.execute("BEGIN IMMEDIATE")
        con.rollback()
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        con.close()


# =============================================================================================
# National Honey Report - line-level parser (pure functions)
# =============================================================================================


@pytest.mark.parametrize("token,expected", [
    ("$1.90", (1.90, False)),
    ("1.44", (1.44, False)),
    ("$ 2.05", (2.05, False)),
    ("190.00", (1.90, True)),        # legacy issues print cents
    ("210", (2.10, True)),
    ("95", (0.95, True)),
])
def test_parse_price_token(token, expected):
    assert parse_price_token(token) == expected


@pytest.mark.parametrize("line,body,price", [
    ("IDAHO  Clover  Extra Light Amber  $1.90", "IDAHO  Clover  Extra Light Amber", (1.90, None, False)),
    ("ARGENTINA  Light Amber  1.44 - 1.73", "ARGENTINA  Light Amber", (1.44, 1.73, False)),
    ("ARGENTINA  Light Amber  $1.44-$1.73", "ARGENTINA  Light Amber", (1.44, 1.73, False)),
    ("BRAZIL  Light Amber  1.98 – 2.15", "BRAZIL  Light Amber", (1.98, 2.15, False)),
    ("MINNESOTA  Clover  White  210-225", "MINNESOTA  Clover  White", (2.10, 2.25, True)),
    ("payment, in volumes of 10,000 pounds or greater unless otherwise stated.", None, None),
    ("packers, handlers & other large users, as of June 30, 2026", None, None),     # a year is not a price
    ("IDAHO  Clover  White  $2.80*", "IDAHO  Clover  White", (2.80, None, False)),  # footnote marker
    ("TEXAS  Wildflower  Light Amber  1.80 1/", "TEXAS  Wildflower  Light Amber", (1.80, None, False)),
    ("CALIFORNIA  No report issued", None, None),
])
def test_split_price_tail(line, body, price):
    got_body, got_price = split_price_tail(line)
    assert got_price == price
    if price is not None:
        assert got_body == body


@pytest.mark.parametrize("text,grade,rest", [
    ("Extra Light Amber", "extra light amber", ""),
    ("Clover  Light Amber", "light amber", "Clover"),
    ("ELA", "extra light amber", ""),
    ("Honey Dew  Lt. Amber", "light amber", "Honey Dew"),
    ("NATURAL HONEY, NESOI, WHITE OR LIGHTER", "white or lighter", "NATURAL HONEY, NESOI,"),
    ("Natural honey, amber and darker", "amber or darker", "Natural honey,"),
    ("Clover", None, "Clover"),
    ("miel de la pampa", None, "miel de la pampa"),       # lower-case "la" is not a colour code
])
def test_extract_color(text, grade, rest):
    assert extract_color(text) == (grade, rest)


@pytest.mark.parametrize("descriptor,expected", [
    ("Honey Dew  White", ("Honey Dew", "white", False, "honeydew")),
    ("Organic  Light Amber", (None, "light amber", True, "unspecified")),
    ("Mixed  Light Amber", ("Mixed", "light amber", False, "polyflora")),
    ("Organic Mixed Flower  Extra Light Amber", ("Mixed Flower", "extra light amber", True, "organic_polyflora")),
    ("Canola  White", ("Canola", "white", False, "rapeseed")),
    ("Tallow  Light Amber", ("Tallow", "light amber", False, "other")),
    ("Light Amber", (None, "light amber", False, "unspecified")),
])
def test_describe(descriptor, expected):
    assert describe(descriptor) == expected


def test_words_to_lines_columns_and_indent():
    # 5 pt per character; a 1-char gap (space) stays in the cell, a wide gap starts a new column
    def w(text, x0, top):
        return {"text": text, "x0": x0, "x1": x0 + 5 * len(text), "top": top}
    words = [w("IDAHO", 36, 100), w("Clover", 126, 100.6), w("Extra", 216, 100), w("Light", 246, 100),
             w("Amber", 276, 100), w("$1.90", 366, 100),
             w("Orange", 126, 112), w("White", 216, 112), w("$2.20", 366, 112)]
    lines = words_to_lines(words, page=3)
    assert [ln.text for ln in lines] == ["IDAHO  Clover  Extra Light Amber  $1.90", "Orange  White  $2.20"]
    assert lines[0].indent == 0 and lines[1].indent == 18.0 and lines[1].page == 3
    assert lines[0].cells == ["IDAHO", "Clover", "Extra Light Amber", "$1.90"]


def test_lines_from_text_pages_and_indent():
    lines = lines_from_text("A  B\n\n   C\n\fD\n")
    assert [(ln.page, ln.text, ln.indent) for ln in lines] == [(1, "A  B", 0.0), (1, "C", 3.0), (2, "D", 0.0)]


# =============================================================================================
# National Honey Report - whole-document parser on the reconstructed layouts
# =============================================================================================


def _parse_txt(name: str):
    return parse_honey_report_lines(lines_from_text((FIX / name).read_text()))


def test_parse_current_layout():
    p = _parse_txt("fvmhoney_2026-06-30.txt")
    assert p.issue_date == date(2026, 6, 30) and (p.volume, p.number) == ("XLVI", 5)
    assert p.sections == ["beekeeper", "canadian_beekeeper", "importer", "ace_imports", "exports", "visual"]
    assert p.warnings == [] and p.narrative is None          # narratives dropped since Jan 2025
    by = {(x.section, x.label, x.descriptor, x.color_grade): x for x in p.prices}
    assert len(p.prices) == 21                                 # placeholders ("No report issued") give no row
    idaho = by[("beekeeper", "IDAHO", "Clover", "extra light amber")]
    assert (idaho.value, idaho.low, idaho.high, idaho.currency, idaho.origin_iso3) == (1.90, None, None, "USD", "USA")
    assert idaho.variety == "clover" and not idaho.printed_in_cents
    orange = by[("beekeeper", "CALIFORNIA", "Orange", "extra light amber")]   # carried-forward state label
    assert (orange.low, orange.high, orange.value) == (2.35, 2.50, 2.425)
    alberta = by[("canadian_beekeeper", "ALBERTA", "Canola", "white")]
    assert (alberta.market_iso3, alberta.origin_iso3, alberta.currency) == ("CAN", "CAN", "USD")
    assert alberta.variety == "rapeseed"
    arg = by[("importer", "ARGENTINA", None, "light amber")]
    assert (arg.origin_iso3, arg.low, arg.high, arg.variety) == ("ARG", 1.44, 1.73, "unspecified")
    assert "duty paid" in arg.terms and "ex-dock or point of entry" in arg.terms
    assert by[("importer", "ARGENTINA", "Honey Dew", "white")].variety == "honeydew"
    assert by[("importer", "URUGUAY", None, "extra light amber")].value == 1.36    # "ELA" continuation row
    organic = by[("importer", "BRAZIL", None, "light amber")]
    assert organic.organic is True
    assert by[("importer", "CANADA", "Clover", "white")].origin_iso3 == "CAN"
    # CBP ACE import tables: one per HTS-10 category, month = May 2026 (one month lag)
    assert len(p.imports) == 10
    ela_arg = next(r for r in p.imports if r.hts_code == "0409000045" and r.origin_iso3 == "ARG")
    assert (ela_arg.year, ela_arg.month, ela_arg.color_grade, ela_arg.organic) == (2026, 5, "extra light amber", False)
    assert (ela_arg.kilograms, ela_arg.value) == (2145600, 5320500)
    assert (ela_arg.cif_value, ela_arg.total_value) == (260100, 5580600)
    assert ela_arg.ytd == {"kg": 9870400, "value": 24470900, "cif": 1196400, "total": 25667300}
    org_total = next(r for r in p.imports if r.hts_code == "0409000005" and r.origin_iso3 == "WLD")
    assert org_total.organic is True and org_total.color_grade is None and org_total.kilograms == 3945440


def test_parse_legacy_layout_cents_and_narrative():
    p = _parse_txt("fvmhoney_2024-12-31.txt")
    assert p.issue_date == date(2024, 12, 31) and p.warnings == []
    assert p.sections == ["beekeeper", "canadian_beekeeper", "importer", "narrative"]
    assert len(p.prices) == 14 and all(x.printed_in_cents for x in p.prices)
    cal = next(x for x in p.prices if x.label == "CALIFORNIA" and x.descriptor == "Alfalfa")
    assert cal.value == 1.95 and cal.variety == "other"
    mn = next(x for x in p.prices if x.descriptor == "Basswood")
    assert mn.label == "MINNESOTA" and mn.variety == "linden" and mn.value == 2.30
    assert next(x for x in p.prices if x.label == "VIETNAM").value == 1.00
    assert p.narrative.startswith("COLONY, HONEY PLANT AND MARKET CONDITIONS\n\nCALIFORNIA\nColonies in the Central")
    assert "almond pollination contracts. Demand for bulk honey was light" in p.narrative
    assert "MIDWEST\nMost colonies were wintering" in p.narrative


@pytest.mark.parametrize("name", ["fvmhoney_2026-06-30", "fvmhoney_2025-09-30", "fvmhoney_2024-12-31"])
def test_pdf_extraction_matches_text_layout(name):
    """The fixture PDFs (proportional font, unruled columns) parse exactly like their text layouts."""
    from_pdf = parse_honey_report_pdf(fx(f"{name}.pdf"))
    from_txt = _parse_txt(f"{name}.txt")

    def strip(rows):
        out = []
        for r in rows:
            d = asdict(r)
            d.pop("raw_line")
            out.append(d)
        return out

    assert from_pdf.issue_date == from_txt.issue_date
    assert strip(from_pdf.prices) == strip(from_txt.prices)
    assert strip(from_pdf.imports) == strip(from_txt.imports)
    assert from_pdf.narrative == from_txt.narrative
    assert from_pdf.warnings == []


def test_unknown_and_unparseable_content_is_warned_never_guessed():
    text = "\n".join([
        "Volume XLVI - Number 6          Page 1          July 31, 2026",
        "Prices paid to importers for bulk honey, duty paid, containers included, ex-dock or point of entry.",
        "ARGENTINA          Light Amber      $1.50",
        "ATLANTIS           Light Amber      $1.10",
        "                   White            $1.20",
        "BRAZIL             Light Amber      $45.00",
        "This line cannot be parsed in any way",
        "Prices paid to packers for retail honey, cents per pound",
        "CALIFORNIA         Clover           White         $3.10",
        "Prices paid to Canadian beekeepers for unprocessed, bulk honey, f.o.b. shipping point.",
        "ALBERTA            Canola           White         $1.70",
        "Natural Honey, Not For Retail Sale, Light Amber (HTS Code 0409000056)",
        "Country of Origin      Kilograms       Value   CIF Value Total Value",
        "ARGENTINA              1,000,000   2,400,000     100,000   2,500,000",
    ])
    p = parse_honey_report_lines(lines_from_text(text))
    assert p.issue_date == date(2026, 7, 31)
    assert [(x.label, x.value) for x in p.prices] == [("ARGENTINA", 1.50)]
    assert p.imports == []
    joined = "\n".join(p.warnings)
    assert "unknown origin 'ATLANTIS'" in joined               # also for its continuation row
    assert joined.count("unknown origin 'ATLANTIS'") == 2
    assert "implausible price 45.0" in joined
    assert "unparsed line in 'importer' table" in joined
    assert "unrecognised price section" in joined and "1 price-like line(s) skipped" in joined
    assert "currency of the Canadian table not stated" in joined
    assert "has no month" in joined


@pytest.mark.parametrize("rows,expected", [
    (["KOREA, SOUTH       Extra Light Amber  $2.40"], ["unknown origin 'KOREA, SOUTH'"]),
    (["Laos               Extra Light Amber  $2.40"], ["unknown origin 'Laos'"]),
    (["Dominican Republic  Extra Light Amber  $2.40"], ["unknown origin 'Dominican Republic'"]),
    # a label wrapped onto a second line: the price on the second line belongs to neither row
    (["BRAZIL             Organic Mixed Flower (certified",
      "   by USDA NOP)    Extra Light Amber  $2.40"],
     ["unparsed line in 'importer' table", "price row without a state/origin label"]),
])
def test_unknown_label_row_never_inherits_the_previous_origin(rows, expected):
    text = "\n".join([
        "Prices paid to importers for bulk honey, duty paid, containers included, ex-dock or point of entry.",
        "ARGENTINA          Light Amber      $1.55",
        *rows,
    ])
    p = parse_honey_report_lines(lines_from_text(text))
    assert [(x.label, x.origin_iso3, x.value) for x in p.prices] == [("ARGENTINA", "ARG", 1.55)]
    joined = "\n".join(p.warnings)
    for msg in expected:
        assert msg in joined, joined


def test_narrative_sentence_about_prices_stays_in_the_narrative():
    text = "\n".join([
        "COLONY, HONEY PLANT AND MARKET CONDITIONS",
        "TEXAS",
        "Colonies were strong after spring rains.",
        "Prices paid to beekeepers were steady",
        "and demand for light amber honey was good.",
    ])
    p = parse_honey_report_lines(lines_from_text(text))
    assert p.warnings == [] and p.sections == ["narrative"]
    assert p.narrative.endswith("Prices paid to beekeepers were steady and demand for light amber honey was good.")


def test_import_table_row_checks():
    text = "\n".join([
        "U.S. HONEY IMPORTS BY COUNTRY OF ORIGIN",
        "Natural Honey, Certified for Organic (HTS Code 0409000005)",
        "                     May 2026",
        "Country of Origin      Kilograms       Value   CIF Value Total Value",
        "BRAZIL                 3,412,880  12,051,200     402,310  12,453,510",
        "NARNIA                    10,000      20,000       1,000      21,000",
        "MEXICO                   120,060     455,100",
        "URUGUAY                        -           -           -           -",
    ])
    p = parse_honey_report_lines(lines_from_text(text))
    assert [(r.origin_iso3, r.kilograms) for r in p.imports] == [("BRA", 3412880), ("URY", None)]
    assert any("unknown country of origin 'NARNIA'" in w for w in p.warnings)
    assert any("has 2 numbers, header has 4 columns" in w for w in p.warnings)


def test_pdf_parser_rejects_unusable_documents():
    with pytest.raises(CollectorError, match="not a PDF"):
        parse_honey_report_pdf(b"<html>Service unavailable</html>")
    with pytest.raises(CollectorError, match="could not be read"):
        parse_honey_report_pdf(b"%PDF-1.7\nthis is not really a pdf")


def test_parse_esmis_releases():
    releases, warnings = parse_esmis_releases(json.loads(fx("esmis_fvmhoney_page0.json")))
    assert warnings == []
    assert [r.release_date for r in releases] == [date(2025, 9, 30), date(2025, 8, 29), date(2024, 12, 31)]
    assert releases[0].pdf_url.endswith("/7p88fj37r/rr173w627/FVMHONEY.PDF")
    assert releases[1].pdf_url is None
    assert releases[2].pdf_url.endswith("FVMHONEY.PDF")              # PDF preferred over the TXT twin
    with pytest.raises(CollectorError):
        parse_esmis_releases({"message": ""})
    rel, warn = parse_esmis_releases({"results": [{"id": "1", "release_datetime": "soon", "files": []}]})
    assert rel == [] and warn


# =============================================================================================
# National Honey Report - collector end to end
# =============================================================================================

ESMIS_PDF_2025 = "https://esmis.nal.usda.gov/sites/default/release-files/m613mx60p/7p88fj37r/rr173w627/FVMHONEY.PDF"
ESMIS_PDF_2024 = "https://esmis.nal.usda.gov/sites/default/release-files/m613mx60p/fixture0001/fixture0002/FVMHONEY.PDF"


def honey_routes(**override):
    routes = {
        usda.ESMIS_FVMHONEY_URL: (200, fx("esmis_fvmhoney_page0.json"), "application/json"),
        ESMIS_PDF_2025: (200, fx("fvmhoney_2025-09-30.pdf"), "application/pdf"),
        ESMIS_PDF_2024: (200, fx("fvmhoney_2024-12-31.pdf"), "application/pdf"),
        usda.AMS_LATEST_URL: (200, fx("fvmhoney_2026-06-30.pdf"), "application/pdf"),
    }
    routes.update(override)
    return {k: v for k, v in routes.items() if v is not None}


def test_honey_report_end_to_end(run_with_routes, session_factory):
    res = run_with_routes("usda_honey_report", honey_routes())
    assert res["status"] == "success", res
    with session_factory() as s:
        src = one(s, Source, Source.key == "usda_honey_report")
        assert src.latest_published_at == date(2026, 6, 30)
        reports = {r.report_key: r for r in s.scalars(select(Report).where(Report.source_id == src.id))}
        assert sorted(reports) == ["2024-12-31", "2025-08-29", "2025-09-30", "2026-06-30"]
        assert reports["2024-12-31"].raw_document_id and "almond pollination" in reports["2024-12-31"].narrative
        assert reports["2025-08-29"].raw_document_id is None             # listed on ESMIS without a file
        assert reports["2025-08-29"].url == usda.ESMIS_PUBLICATION_URL
        assert reports["2026-06-30"].url == usda.AMS_LATEST_URL and reports["2026-06-30"].narrative is None
        assert reports["2025-09-30"].url == ESMIS_PDF_2025

        P = PriceObservation
        assert count(s, P) == 21 + 10 + 6 + 4 + 14
        assert count(s, P, P.price_type == PriceType.PRODUCER.value) == 11 + 3 + 9
        assert count(s, P, P.price_type == PriceType.WHOLESALE_BULK.value) == 10 + 3 + 5
        assert count(s, P, P.price_type == PriceType.IMPORT_UNIT_VALUE.value) == 10 + 4
        # price types never mixed: wholesale = importer table (market USA), import UV always per kg
        assert count(s, P, P.price_type == PriceType.WHOLESALE_BULK.value, P.market_iso3 != "USA") == 0
        assert count(s, P, P.price_type == PriceType.IMPORT_UNIT_VALUE.value, P.unit != "kg") == 0
        assert count(s, P, P.price_type != PriceType.IMPORT_UNIT_VALUE.value, P.unit != "lb") == 0

        idaho = one(s, P, P.period_label == "2026-06", P.origin_label == "Idaho")
        assert (idaho.price_type, idaho.variety, idaho.color_grade) == ("producer", "clover", "extra light amber")
        assert (idaho.price_value, idaho.currency, idaho.unit) == (1.90, "USD", "lb")
        assert round(idaho.price_per_kg, 4) == round(1.90 / LB, 4) == 4.1888       # per-kg conversion
        assert idaho.usd_per_kg == 4.1888
        assert (idaho.market_iso3, idaho.origin_iso3, idaho.market_location) == ("USA", "USA", "Idaho")
        # the AMS file is overwritten monthly: the price links to the archived bytes it was parsed from
        assert idaho.source_url == f"/api/reports/{reports['2026-06-30'].id}/file"
        assert idaho.extra["fetched_from"] == usda.AMS_LATEST_URL and idaho.published_at == date(2026, 6, 30)
        assert (idaho.period_start, idaho.period_end, idaho.frequency) == (date(2026, 6, 1), date(2026, 6, 30), "M")
        assert (idaho.data_status, idaho.reliability) == ("published", "official")
        assert idaho.raw_document_id == reports["2026-06-30"].raw_document_id
        assert idaho.extra["parser_version"] == usda.PARSER_VERSION and idaho.extra["page"] == 1

        arg = one(s, P, P.period_label == "2026-06", P.origin_iso3 == "ARG", P.price_type == "wholesale_bulk",
                  P.color_grade == "light amber")
        assert (arg.price_low, arg.price_high, arg.price_value) == (1.44, 1.73, 1.585)
        assert round(arg.price_per_kg, 4) == round(1.585 / LB, 4)
        assert arg.origin_label == "Argentina" and arg.variety == "unspecified" and "duty paid" in arg.terms

        canada = one(s, P, P.market_iso3 == "CAN", P.period_label == "2026-06", P.origin_label == "Alberta")
        assert canada.price_type == "producer" and canada.currency == "USD"

        legacy = one(s, P, P.period_label == "2024-12", P.origin_label == "California", P.variety_raw == "Alfalfa")
        assert legacy.price_value == 1.95 and legacy.extra["printed_in_cents"] is True
        assert legacy.source_url == ESMIS_PDF_2024 and legacy.published_at == date(2024, 12, 31)

        ace = one(s, P, P.price_type == "import_unit_value", P.origin_iso3 == "ARG", P.period_label == "2026-05")
        assert ace.price_value == round(5320500 / 2145600, 4) and ace.volume_kg == 2145600
        assert ace.color_grade == "extra light amber" and ace.published_at == date(2026, 6, 30)
        assert ace.extra["cif_value_usd"] == 260100 and ace.extra["hts_code"] == "0409000045"
        assert "HTS 0409000045" in ace.terms
        assert count(s, P, P.price_type == "import_unit_value", P.origin_iso3 == "WLD") == 3

        n_prices, n_reports, n_raw = count(s, P), count(s, Report), count(s, RawDocument)

    # second identical run: nothing new, no duplicate rows
    res2 = run_with_routes("usda_honey_report", honey_routes())
    assert res2["status"] == "no_change", res2
    with session_factory() as s:
        assert (count(s, PriceObservation), count(s, Report), count(s, RawDocument)) == (n_prices, n_reports, n_raw)
        assert count(s, PriceObservation, PriceObservation.is_current.is_(False)) == 0


def test_honey_report_falls_back_to_ams_when_esmis_fails(run_with_routes, session_factory):
    res = run_with_routes("usda_honey_report", honey_routes(**{usda.ESMIS_FVMHONEY_URL: (500, b"boom")}))
    assert res["status"] == "partial", res
    assert any("ESMIS archive unavailable" in w for w in res["warnings"])
    with session_factory() as s:
        assert [r.report_key for r in s.scalars(select(Report))] == ["2026-06-30"]
        assert count(s, PriceObservation) == 31


def test_honey_report_uses_mirror_when_ams_fails(run_with_routes, session_factory):
    res = run_with_routes("usda_honey_report", honey_routes(**{
        usda.ESMIS_FVMHONEY_URL: (200, b'{"results": []}', "application/json"),
        usda.AMS_LATEST_URL: (404, b"not found"),
        usda.AMS_MIRROR_URL: (200, fx("fvmhoney_2026-06-30.pdf"), "application/pdf"),
    }))
    assert res["status"] == "partial", res                  # the empty ESMIS list is reported
    assert any("empty National Honey Report release list" in w for w in res["warnings"])
    with session_factory() as s:
        report = one(s, Report)
        assert report.url == usda.AMS_MIRROR_URL
        rows = s.scalars(select(PriceObservation)).all()
        assert len(rows) == 31
        assert all(r.source_url == f"/api/reports/{report.id}/file" for r in rows)
        assert all(r.extra["fetched_from"] == usda.AMS_MIRROR_URL for r in rows)


def test_honey_report_bad_latest_file_is_a_warning(run_with_routes, session_factory):
    res = run_with_routes("usda_honey_report", honey_routes(**{
        usda.AMS_LATEST_URL: (200, b"<html>maintenance</html>", "text/html")}))
    assert res["status"] == "partial", res
    assert any("AMS latest issue not processed: downloaded file is not a PDF" in w for w in res["warnings"])
    with session_factory() as s:
        assert count(s, PriceObservation) == 6 + 4 + 14          # the two ESMIS issues


def test_honey_report_offline(run_with_routes):
    assert run_with_routes("usda_honey_report", {})["status"] == "offline"


def test_honey_report_states_are_separate_price_series(run_with_routes, api):
    """Producer prices of different states share origin/market USA, colour and terms: the state
    (market_location) must keep them apart, never averaged into one line."""
    assert run_with_routes("usda_honey_report", honey_routes())["status"] == "success"
    body = api.get("/api/prices/series", params={"price_type": "producer", "source": "usda_honey_report"}).json()

    def june(state: str, variety: str, color: str) -> dict:
        found = [s for s in body["series"]
                 if (s["market_location"], s["variety"], s["color_grade"]) == (state, variety, color)]
        assert len(found) == 1, [(s["market_location"], s["variety"], s["color_grade"]) for s in body["series"]]
        return {p["period_label"]: p for p in found[0]["points"]}["2026-06"]

    for state, variety, color, usd_lb in [
        ("Idaho", "clover", "extra light amber", 1.90), ("South Dakota", "clover", "extra light amber", 1.95),
        ("Montana", "clover", "white", 2.10), ("North Dakota", "clover", "white", 2.10),
        ("California", "orange_blossom", "extra light amber", 2.425),
        ("Florida", "orange_blossom", "extra light amber", 2.20),
    ]:
        p = june(state, variety, color)
        assert p["n_points"] == 1, (state, p)
        assert p["original"]["value"] == usd_lb and p["original"]["unit"] == "lb"
        assert p["value"] == round(usd_lb / LB, 4)
    # "DAKOTA" (Sept 2025 issue) is its own series, not joined to South or North Dakota
    dakota = [s for s in body["series"] if s["market_location"] == "Dakota"]
    assert len(dakota) == 1 and [p["period_label"] for p in dakota[0]["points"]] == ["2025-09"]
    latest = api.get("/api/prices/latest", params={"price_type": "producer", "source": "usda_honey_report"}).json()
    assert len({r["series_id"] for r in latest["rows"]}) == len(latest["rows"]) == len(body["series"])


def test_honey_report_price_links_survive_the_monthly_overwrite(run_with_routes, api, session_factory):
    """AMS overwrites fvmhoney.pdf every month: a price parsed from it keeps a link to the exact
    archived file, not to whatever the URL serves next month."""
    assert run_with_routes("usda_honey_report", honey_routes())["status"] == "success"
    with session_factory() as s:
        idaho = one(s, PriceObservation, PriceObservation.period_label == "2026-06",
                    PriceObservation.origin_label == "Idaho")
        link, fetched_from = idaho.source_url, idaho.extra["fetched_from"]
    assert fetched_from == usda.AMS_LATEST_URL and link.startswith("/api/reports/")
    # next month the same URL serves a different issue
    res = run_with_routes("usda_honey_report", honey_routes(**{
        usda.AMS_LATEST_URL: (200, fx("fvmhoney_2025-09-30.pdf"), "application/pdf")}))
    assert res["status"] in ("success", "no_change"), res
    with session_factory() as s:
        idaho = one(s, PriceObservation, PriceObservation.period_label == "2026-06",
                    PriceObservation.origin_label == "Idaho")
        assert idaho.source_url == link
    got = api.get(link)
    assert got.status_code == 200 and got.content == fx("fvmhoney_2026-06-30.pdf")
    rows = api.get("/api/prices/latest", params={"price_type": "producer", "source": "usda_honey_report"}).json()
    idaho_row = next(r for r in rows["rows"] if r["market_location"] == "Idaho" and r["period_label"] == "2026-06")
    assert idaho_row["source_url"] == link


def test_esmis_retry_wait_does_not_hold_the_database_write_lock(run_with_routes, monkeypatch):
    """ESMIS answering with an empty list is retried 5 s apart; other writers (scheduler, the
    'Aggiorna dati' button, API writes) must not be locked out meanwhile."""
    waits: list[bool] = []

    def fake_sleep(seconds):
        if seconds == 5:
            waits.append(db_write_possible())

    monkeypatch.setattr(usda.time, "sleep", fake_sleep)
    res = run_with_routes("usda_honey_report", honey_routes(**{
        usda.ESMIS_FVMHONEY_URL: (200, b'{"results": []}', "application/json")}))
    assert res["status"] == "partial", res
    assert waits == [True] * usda.ESMIS_EMPTY_RETRIES


# =============================================================================================
# FAS GATS - pure functions
# =============================================================================================


def test_gats_release_selection():
    releases = parse_gats_release_dates(json.loads(fx("gats_release_dates.json")))
    assert releases[0].yyyymm == "202608" and releases[0].released == date(2026, 10, 6)
    assert len(releases) == 8 + 36 + 12
    todo = select_gats_months(releases, {}, window=36, cap=18)
    assert [r.yyyymm for r in todo][:3] == ["202608", "202607", "202606"] and len(todo) == 18
    all36 = select_gats_months(releases, {}, window=36, cap=100)
    assert len(all36) == 36 and all36[-1].yyyymm == "202309"
    processed = {r.yyyymm: r.timestamp for r in all36}
    assert select_gats_months(releases, processed, window=36, cap=18) == []
    processed["202501"] = "2025-03-06T08:30:00"                # revised by the 2026-06-24 annual release
    assert [r.yyyymm for r in select_gats_months(releases, processed, window=36, cap=18)] == ["202501"]
    with pytest.raises(CollectorError):
        parse_gats_release_dates({"error": "x"})


def test_parse_gats_imports_keeps_only_honey_lines():
    payload = json.loads(fx("gats_imports_AR_202608.json"))
    lines, n, warnings = parse_gats_imports(payload, partner="AR", yyyymm="202608")
    assert n == 4 and warnings == []
    assert [(ln.hs10, ln.kg, ln.value, ln.cif_total, ln.cif_charges) for ln in lines] == [
        ("0409000045", 1850000.0, 4550000.0, 4771000.0, 221000.0),
        ("0409000056", 620000.0, 1450000.0, 1525500.0, 75500.0),
    ]
    bad = [{"hS10Code": "0409000045", "date": "202608", "countryCode": "AR", "censusUOMId1": 78,
            "consumptionQuantity1": 5.0, "consumptionValue": 9.0}]
    lines, _, warnings = parse_gats_imports(bad, partner="AR", yyyymm="202608")
    assert lines == [] and "not kg" in warnings[0]                    # unknown unit: never guessed
    with pytest.raises(CollectorError):
        parse_gats_imports({"error": {"code": "API_KEY_INVALID"}}, partner="AR", yyyymm="202608")


def test_gats_commodity_descriptions_give_colour():
    table = parse_gats_commodities(json.loads(fx("gats_commodities.json")))
    assert set(table) == {"0409000005", "0409000010", "0409000035", "0409000045", "0409000056", "0409000065"}
    assert usda.hs10_attributes(table["0409000005"]) == (None, True)
    assert usda.hs10_attributes(table["0409000045"]) == ("extra light amber", False)
    assert usda.hs10_attributes(table["0409000065"]) == ("amber or darker", False)
    assert usda.hs10_attributes(None) == (None, False)


# =============================================================================================
# FAS GATS - collector end to end
# =============================================================================================

GATS_KEY = "test-gats-key-123"


def _gats_url(partner: str, year: int, month: int) -> str:
    return "^" + re.escape(usda.GATS_IMPORTS_URL.format(partner=partner, year=year, month=month)) + "$"


def gats_routes(release_dates: bytes | None = None, ar_202608: bytes | None = None) -> dict:
    return {
        usda.GATS_RELEASES_URL: (200, release_dates or fx("gats_release_dates.json"), "application/json"),
        usda.GATS_COMMODITIES_URL: (200, fx("gats_commodities.json"), "application/json"),
        _gats_url("AR", 2026, 8): (200, ar_202608 or fx("gats_imports_AR_202608.json"), "application/json"),
        _gats_url("AR", 2026, 7): (200, fx("gats_imports_AR_202607.json"), "application/json"),
        _gats_url("VM", 2026, 8): (200, fx("gats_imports_VM_202608.json"), "application/json"),
        _gats_url("VM", 2026, 7): (200, b"[]", "application/json"),
        _gats_url("CH", 2026, 8): (200, fx("gats_imports_CH_202608.json"), "application/json"),
        _gats_url("CH", 2026, 7): (200, fx("gats_imports_CH_202608.json").replace(b"202608", b"202607"),
                                   "application/json"),
    }


@pytest.fixture()
def gats_small(db, monkeypatch):
    """GATS with the API key set, three origins and a two-month window (keeps the test small)."""
    monkeypatch.setenv("PALADEX_DATA_GOV_API_KEY", GATS_KEY)
    config.get_settings.cache_clear()
    monkeypatch.setattr(usda, "GATS_PARTNERS", {"AR": "ARG", "VM": "VNM", "CH": "CHN"})
    monkeypatch.setattr(usda, "GATS_WINDOW_MONTHS", 2)
    yield
    config.get_settings.cache_clear()


def test_gats_end_to_end(gats_small, run_with_routes, session_factory):
    res = run_with_routes("usda_fas_gats", gats_routes())
    assert res["status"] == "success", res
    T, P = TradeFlowObservation, PriceObservation
    with session_factory() as s:
        assert count(s, T) == 6                                    # 3 origins x 2 months, zeros included
        ar = one(s, T, T.partner_iso3 == "ARG", T.period_label == "2026-08")
        assert (ar.reporter_iso3, ar.flow, ar.hs_code) == ("USA", "import", "0409")
        assert (ar.currency, ar.frequency) == ("USD", "M")
        assert (ar.net_weight_kg, ar.value, ar.value_basis) == (2470000.0, 6000000.0, "customs")
        assert ar.unit_value_per_kg == round(6000000 / 2470000, 4)
        assert ar.extra["cif_value_usd"] == 4771000 + 1525500 and ar.extra["cif_charges_usd"] == 221000 + 75500
        assert [ln["hs10"] for ln in ar.extra["hs10_lines"]] == ["0409000045", "0409000056"]
        assert ar.published_at == date(2026, 10, 6) and ar.period_start == date(2026, 8, 1)
        assert ar.source_url == usda.GATS_IMPORTS_URL.format(partner="AR", year=2026, month=8)
        assert (ar.data_status, ar.reliability) == ("published", "official")
        china = one(s, T, T.partner_iso3 == "CHN", T.period_label == "2026-08")
        assert (china.net_weight_kg, china.value, china.extra["no_honey_lines"]) == (0, 0, True)
        assert one(s, T, T.partner_iso3 == "VNM", T.period_label == "2026-07").extra["partner_records"] == 0

        assert count(s, P) == 3 + 2 + 2                              # AR-08 total+2 lines, AR-07, VM-08
        assert count(s, P, P.price_type != PriceType.IMPORT_UNIT_VALUE.value) == 0
        total = one(s, P, P.origin_iso3 == "ARG", P.period_label == "2026-08", P.color_grade.is_(None))
        assert (total.price_value, total.unit, total.currency) == (round(6000000 / 2470000, 4), "kg", "USD")
        assert total.price_per_kg == total.price_value and total.volume_kg == 2470000
        assert (total.variety, total.market_iso3, total.origin_label) == ("unspecified", "USA", "Argentina")
        ela = one(s, P, P.origin_iso3 == "ARG", P.period_label == "2026-08", P.color_grade == "extra light amber")
        assert ela.price_value == round(4550000 / 1850000, 4) and "HTS 0409000045" in ela.terms
        assert ela.variety_raw == "NATURAL HONEY, NESOI, EXTRA LIGHT AMBER"
        assert ela.extra["cif_unit_value_usd_per_kg"] == round(4771000 / 1850000, 4)
        # the API key never reaches the database
        for url in s.scalars(select(RawDocument.url)):
            assert GATS_KEY not in url
        state = s.get(AppSetting, "collector_state:usda_fas_gats").value
        assert state["processed"] == {"202608": "2026-10-06T08:00:00", "202607": "2026-09-03T08:30:00"}
        counts = (count(s, T), count(s, P))

    res2 = run_with_routes("usda_fas_gats", gats_routes())
    assert res2["status"] == "no_change", res2
    with session_factory() as s:
        assert (count(s, T), count(s, P)) == counts

    # Census revises August (new release timestamp, different numbers) -> appended revision
    revised_dates = fx("gats_release_dates.json").replace(b"2026-10-06T08:00:00", b"2026-11-02T08:30:00")
    revised_ar = fx("gats_imports_AR_202608.json").replace(b"4550000.0", b"4600000.0")
    res3 = run_with_routes("usda_fas_gats", gats_routes(revised_dates, revised_ar))
    assert res3["status"] == "success" and res3["revised"] >= 1, res3
    with session_factory() as s:
        rows = s.scalars(select(T).where(T.partner_iso3 == "ARG", T.period_label == "2026-08").order_by(T.id)).all()
        assert [(r.revision, r.is_current, r.value) for r in rows] == [(1, False, 6000000.0), (2, True, 6050000.0)]
        assert rows[1].supersedes_id == rows[0].id
        assert count(s, T, T.is_current.is_(True)) == 6


def _run_gats_recording(calls: list, remaining: str = "990", probe=None) -> dict:
    """Run the GATS collector with respx, recording every request; responses carry the
    api.data.gov `x-ratelimit-remaining` header. `probe(request)` runs while each request is
    in flight."""
    from paladex.collectors.runner import run_collector

    with respx.mock(assert_all_called=False) as mock:
        for pattern, (status, body, ctype) in gats_routes().items():
            def handler(request, body=body, status=status, ctype=ctype):
                calls.append(request)
                if probe is not None:
                    probe(request)
                return httpx.Response(status, content=body,
                                      headers={"content-type": ctype, "x-ratelimit-remaining": remaining})
            if pattern.startswith("^"):
                mock.get(url__regex=pattern).mock(side_effect=handler)
            else:
                mock.get(url__startswith=pattern).mock(side_effect=handler)
        mock.route().mock(side_effect=httpx.ConnectError("blocked in tests"))
        with httpx.Client() as client:
            return run_collector("usda_fas_gats", trigger="test", client=client)


@pytest.fixture()
def no_sleep(monkeypatch):
    from paladex.collectors import base

    monkeypatch.setattr(base.time, "sleep", lambda *_: None)


def test_gats_sends_key_header_and_does_not_refetch(gats_small, no_sleep):
    calls: list[httpx.Request] = []
    assert _run_gats_recording(calls)["status"] == "success"
    assert calls and all(c.headers.get("X-Api-Key") == GATS_KEY for c in calls)
    assert all(GATS_KEY not in str(c.url) for c in calls)
    assert sum("/censusImports/" in str(c.url) for c in calls) == 6
    calls.clear()
    assert _run_gats_recording(calls)["status"] == "no_change"
    assert [str(c.url) for c in calls] == [usda.GATS_RELEASES_URL]    # only the release calendar


def test_gats_stops_early_when_quota_runs_low(gats_small, no_sleep, session_factory):
    calls: list[httpx.Request] = []
    res = _run_gats_recording(calls, remaining="5")
    assert res["status"] == "partial" and any("quota nearly used up" in w for w in res["warnings"])
    assert sum("/censusImports/" in str(c.url) for c in calls) == 1   # stopped after the first partner
    with session_factory() as s:
        assert count(s, TradeFlowObservation) == 1                    # what was fetched is kept
        state = s.get(AppSetting, "collector_state:usda_fas_gats").value
        assert state.get("processed", {}) == {}                        # month incomplete: retried next run


def test_gats_downloads_never_hold_the_database_write_lock(gats_small, no_sleep):
    """Each partner-month is committed as soon as it is stored, so the minutes spent downloading
    (21 partners per month, the 7.6 MB /commodities list) never lock other writers out."""
    seen: list[tuple[str, bool]] = []
    calls: list[httpx.Request] = []

    def probe(request):
        if "/censusImports/" in request.url.path or request.url.path.endswith("/commodities"):
            seen.append((request.url.path, db_write_possible()))

    assert _run_gats_recording(calls, probe=probe)["status"] == "success"
    assert len(seen) == 1 + 6                                       # /commodities + 3 partners x 2 months
    assert [path for path, free in seen if not free] == []


def _gats_listing(name: str, drop: tuple[str, ...] = ()) -> bytes:
    return json.dumps([r for r in json.loads(fx(name)) if r["hS10Code"] not in drop]).encode()


def test_gats_defers_hs10_unit_values_until_descriptions_load(gats_small, run_with_routes, session_factory):
    """Without the /commodities descriptions the per-HS-10 unit values would be stored without
    colour/organic for good (those fields are not revision fields): they wait for a later run."""
    T, P = TradeFlowObservation, PriceObservation
    routes = {**gats_routes(), usda.GATS_COMMODITIES_URL: (500, b"oops")}
    res = run_with_routes("usda_fas_gats", routes)
    assert res["status"] == "partial", res
    assert any("deferred" in w for w in res["warnings"]), res["warnings"]
    with session_factory() as s:
        assert count(s, T) == 6                                     # trade rows do not need descriptions
        assert count(s, P) == 3                                     # HS 0409 totals: AR-08, AR-07, VM-08
        assert count(s, P, P.terms.like("%HTS 0409%")) == 0         # no per-HS-10 row without its colour
        state = s.get(AppSetting, "collector_state:usda_fas_gats").value
        assert state.get("processed", {}) == {}                     # both months are fetched again

    res2 = run_with_routes("usda_fas_gats", gats_routes())
    assert res2["status"] == "success", res2
    with session_factory() as s:
        assert count(s, T) == 6 and count(s, P) == 3 + 2 + 2
        assert count(s, T, T.is_current.is_(False)) == count(s, P, P.is_current.is_(False)) == 0
        ela = one(s, P, P.origin_iso3 == "ARG", P.period_label == "2026-08", P.terms.like("%HTS 0409000045"))
        assert (ela.color_grade, ela.organic) == ("extra light amber", False)
        assert ela.variety_raw == "NATURAL HONEY, NESOI, EXTRA LIGHT AMBER"
        state = s.get(AppSetting, "collector_state:usda_fas_gats").value
        assert state["processed"] == {"202608": "2026-10-06T08:00:00", "202607": "2026-09-03T08:30:00"}


def test_gats_revision_withdraws_unit_values_no_longer_published(gats_small, run_with_routes, session_factory, api):
    T, P = TradeFlowObservation, PriceObservation
    assert run_with_routes("usda_fas_gats", gats_routes())["status"] == "success"
    line_key = "import_unit_value|usda_gats|USA|ARG|0409000056|202608"
    total_key = "import_unit_value|usda_gats|USA|ARG|0409|202608"
    ela_key = "import_unit_value|usda_gats|USA|ARG|0409000045|202608"

    # 1) Census revises August: the 0409000056 line is gone from Argentina's listing
    dates = fx("gats_release_dates.json").replace(b"2026-10-06T08:00:00", b"2026-11-02T08:30:00")
    res = run_with_routes("usda_fas_gats", gats_routes(dates, _gats_listing("gats_imports_AR_202608.json",
                                                                            drop=("0409000056",))))
    assert res["status"] == "partial" and res["revised"] >= 3, res    # trade row, total, withdrawn line
    assert [w for w in res["warnings"] if "withdrawn" in w] == [
        "GATS AR 2026-08: the Census release of 2026-11-02T08:30:00 no longer reports a quantity and value for "
        "HS 0409000056; the unit value(s) published earlier are withdrawn (kept in the history)"]
    with session_factory() as s:
        line = one(s, P, P.series_key == line_key)
        assert line.is_current is False and line.revision == 1          # kept for history, not deleted
        assert line.price_value == round(1450000 / 620000, 4)            # values untouched
        assert line.extra["release_timestamp"] == "2026-10-06T08:00:00"
        assert one(s, P, P.series_key == total_key, P.is_current.is_(True)).price_value == round(4550000 / 1850000, 4)
        assert one(s, P, P.series_key == ela_key).is_current is True   # unchanged line untouched
    latest = api.get("/api/prices/latest", params={"price_type": "import_unit_value", "origin": "ARG"}).json()
    aug = [r for r in latest["rows"] if r["period_label"] == "2026-08"]
    assert aug and not any("0409000056" in r["terms"] for r in aug)

    # 2) a later revision leaves no honey line for Argentina in August
    dates2 = dates.replace(b"2026-11-02T08:30:00", b"2026-11-30T08:30:00")
    res = run_with_routes("usda_fas_gats", gats_routes(dates2, _gats_listing(
        "gats_imports_AR_202608.json", drop=("0409000045", "0409000056"))))
    assert res["status"] == "partial", res
    assert any("2026-11-30T08:30:00" in w and "HS 0409000045, 0409;" in w for w in res["warnings"]), res
    with session_factory() as s:
        trade = one(s, T, T.partner_iso3 == "ARG", T.period_label == "2026-08", T.is_current.is_(True))
        assert (trade.net_weight_kg, trade.value, trade.extra["no_honey_lines"]) == (0, 0, True)
        assert count(s, P, P.origin_iso3 == "ARG", P.period_label == "2026-08", P.is_current.is_(True)) == 0
        assert one(s, P, P.series_key == total_key, P.revision == 2).is_current is False
        assert count(s, P, P.origin_iso3 == "ARG", P.period_label == "2026-08") == 4   # history kept
        assert count(s, P, P.origin_iso3 == "ARG", P.period_label == "2026-07", P.is_current.is_(True)) == 2
    latest = api.get("/api/prices/latest", params={"price_type": "import_unit_value", "origin": "ARG"}).json()
    assert latest["rows"] and all(r["period_label"] != "2026-08" for r in latest["rows"])


def test_gats_without_key_is_skipped(run_with_routes, monkeypatch):
    monkeypatch.delenv("PALADEX_DATA_GOV_API_KEY", raising=False)
    config.get_settings.cache_clear()
    res = run_with_routes("usda_fas_gats", gats_routes())
    assert res["status"] == "skipped" and "DATA_GOV_API_KEY" in res["error"]


def test_gats_rejected_key_fails_cleanly(gats_small, run_with_routes):
    res = run_with_routes("usda_fas_gats", {usda.GATS_RELEASES_URL: (403, b'{"error":{"code":"API_KEY_INVALID"}}')})
    assert res["status"] == "failed" and "rejected the API key" in res["error"]


# =============================================================================================
# NASS Quick Stats
# =============================================================================================

NASS_KEY = "nass-secret-key-456"


def test_parse_nass_rows():
    obs, skipped = parse_nass_rows(json.loads(fx("nass_honey_national.json")))
    got = {(o.kind, o.year): o for o in obs}
    assert sorted(got) == [("colonies", 2024), ("colonies", 2025), ("price", 2018), ("price", 2024), ("price", 2025),
                           ("production", 2018), ("production", 2024), ("production", 2025),
                           ("stocks", 2025), ("yield_per_colony", 2024), ("yield_per_colony", 2025)]
    assert got[("production", 2025)].value == round(134_750_000 * LB / 1000, 3)
    assert got[("production", 2025)].unit == "t"
    assert got[("yield_per_colony", 2025)].value == round(51.0 * LB, 3)
    assert got[("colonies", 2025)].value == 2_642_000                 # annual, not the Jan-1 quarterly count
    assert got[("price", 2018)].value == 2.21                         # CENTS / LB before the 2019 crop
    assert got[("price", 2025)].load_date == date(2026, 3, 13)
    assert all(o.data_status == "published" for o in obs)
    assert skipped["suppressed / missing value"] == 1 and skipped["practice / channel split"] == 1
    with pytest.raises(CollectorError):
        parse_nass_rows({"error": ["bad request - invalid query"]})


@pytest.fixture()
def nass_key(db, monkeypatch):                # after `db`, which clears the NASS key from the env
    monkeypatch.setenv("PALADEX_USDA_NASS_API_KEY", NASS_KEY)
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


def test_nass_end_to_end(nass_key, run_with_routes, session_factory):
    routes = {usda.NASS_API_URL: (200, fx("nass_honey_national.json"), "application/json")}
    res = run_with_routes("usda_nass_honey", routes)
    assert res["status"] == "success", res
    S, P = ProductionStat, PriceObservation
    with session_factory() as s:
        assert count(s, S) == 8 and count(s, P) == 3
        prod = one(s, S, S.metric == "production", S.period_label == "2025")
        assert (prod.country_iso3, prod.unit, prod.frequency) == ("USA", "t", "A")
        assert prod.value == round(134_750_000 * LB / 1000, 3)
        assert (prod.period_start, prod.period_end) == (date(2025, 1, 1), date(2025, 12, 31))
        assert prod.published_at == date(2026, 3, 13) and prod.source_url == usda.NASS_PUBLIC_URL
        assert (prod.data_status, prod.reliability) == ("published", "official")
        assert prod.extra["short_desc"] == "HONEY - PRODUCTION, MEASURED IN LB"
        assert one(s, S, S.metric == "colonies", S.period_label == "2025").unit == "number"
        assert one(s, S, S.metric == "yield_per_colony", S.period_label == "2024").unit == "kg/colony"
        price = one(s, P, P.period_label == "2025")
        assert (price.price_type, price.market_iso3, price.origin_iso3, price.unit) == ("producer", "USA", "USA", "lb")
        assert price.price_value == 3.05 and round(price.price_per_kg, 4) == round(3.05 / LB, 4)
        assert one(s, P, P.period_label == "2018").price_value == 2.21
        raw = s.scalars(select(RawDocument)).all()
        assert len(raw) == 1 and "key=REDACTED" in raw[0].url and NASS_KEY not in raw[0].url
        n = (count(s, S), count(s, P))

    res2 = run_with_routes("usda_nass_honey", routes)
    assert res2["status"] == "no_change", res2
    with session_factory() as s:
        assert (count(s, S), count(s, P)) == n

    # NASS revises the prior year in the next Honey report -> a new revision, the old one kept
    revised = fx("nass_honey_national.json").replace(b'"Value": "2.41"', b'"Value": "2.45"')
    res3 = run_with_routes("usda_nass_honey", {usda.NASS_API_URL: (200, revised, "application/json")})
    assert res3["status"] == "success" and res3["revised"] == 1, res3
    with session_factory() as s:
        rows = s.scalars(select(P).where(P.period_label == "2024").order_by(P.id)).all()
        assert [(r.price_value, r.is_current) for r in rows] == [(2.41, False), (2.45, True)]


def test_nass_key_never_reaches_the_log(nass_key, run_with_routes, caplog):
    """httpx logs every request URL (query string included) at INFO, the app's root level."""
    routes = {usda.NASS_API_URL: (200, fx("nass_honey_national.json"), "application/json")}
    with caplog.at_level(logging.INFO, logger="httpx"):
        assert run_with_routes("usda_nass_honey", routes)["status"] == "success"
    messages = [r.getMessage() for r in caplog.records]
    assert any("HTTP Request:" in m and "key=REDACTED" in m for m in messages), messages
    assert all(NASS_KEY not in m for m in messages)


def test_nass_without_key_is_skipped(run_with_routes):
    res = run_with_routes("usda_nass_honey", {usda.NASS_API_URL: fx("nass_honey_national.json")})
    assert res["status"] == "skipped" and "USDA_NASS_API_KEY" in res["error"]


def test_nass_bad_key_and_errors_never_leak_the_key(nass_key, run_with_routes):
    res = run_with_routes("usda_nass_honey", {usda.NASS_API_URL: (401, b'{"error":["unauthorized"]}')})
    assert res["status"] == "failed" and "rejected the API key" in res["error"]
    res = run_with_routes("usda_nass_honey", {usda.NASS_API_URL: (500, b"oops")})
    assert res["status"] == "failed" and NASS_KEY not in res["error"] and "key=REDACTED" in res["error"]


def test_redact_url():
    assert redact_url("https://x.org/a?key=SECRET&year=2020") == "https://x.org/a?key=REDACTED&year=2020"
    assert redact_url("https://x.org/a?page=0") == "https://x.org/a?page=0"
    assert redact_url("https://x.org/a") == "https://x.org/a"


def test_collector_metadata():
    from paladex.collectors.registry import all_collectors

    found = {c.key: c for c in all_collectors() if c.__module__ == usda.__name__}
    assert set(found) == {"usda_honey_report", "usda_fas_gats", "usda_nass_honey"}
    assert found["usda_fas_gats"].requires_key == "data_gov_api_key"
    assert found["usda_nass_honey"].requires_key == "usda_nass_api_key"
    assert found["usda_honey_report"].requires_key is None
    keys = ("usda_honey_report", "usda_fas_gats", "usda_nass_honey")
    assert [found[k].expected_max_age_days for k in keys] == [40, 70, 400]
    assert "not endorsed or certified by NASS" in found["usda_nass_honey"].terms_note
    assert DataStatus.PUBLISHED.value == "published"
