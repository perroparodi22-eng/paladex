"""USDA collectors: AMS National Honey Report (PDF), FAS GATS (Census imports), NASS Quick Stats.

The National Honey Report and ESMIS fixtures in tests/fixtures/usda/ are REAL captures (page subsets
of the published PDFs, Nov 2026); the GATS and NASS fixtures are still RECONSTRUCTED from
documentation. See the README there.
"""
from __future__ import annotations

import functools
import json
import logging
import re
import sqlite3
from collections import Counter
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
    MmnDocument,
    NotAHoneyReport,
    ace_origin,
    chars_to_words,
    column_blocks,
    dedupe_glyphs,
    describe,
    extract_color,
    group_warnings,
    lines_from_text,
    market_month,
    parse_esmis_releases,
    parse_gats_commodities,
    parse_gats_imports,
    parse_gats_release_dates,
    parse_honey_report_lines,
    parse_honey_report_pdf,
    parse_mmn_filerepo,
    parse_nass_rows,
    parse_price_token,
    pdf_to_lines,
    select_gats_months,
    split_color,
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
# National Honey Report - line-level helpers (pure functions)
# =============================================================================================


@pytest.mark.parametrize("token,expected", [
    ("$1.90", (1.90, False)),
    ("1.44", (1.44, False)),
    ("$ 2.05", (2.05, False)),
    ("$.91", (0.91, False)),         # 2023-2024 issues print "$.91"
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
    ("Light Amber  $1.59 -  $1.64", "Light Amber", (1.59, 1.64, False)),          # July 2025: "-" in its own cell
    ("Mustard  White  $.95 - $1.39", "Mustard  White", (0.95, 1.39, False)),
    ("BRAZIL  Light Amber  1.98 – 2.15", "BRAZIL  Light Amber", (1.98, 2.15, False)),
    ("MINNESOTA  Clover  White  210-225", "MINNESOTA  Clover  White", (2.10, 2.25, True)),
    ("payment, in volumes of 10,000 pounds or greater unless otherwise stated.", None, None),
    ("packers, handlers & other large users, as of June 30, 2026", None, None),     # a year is not a price
    ("IDAHO  Clover  White  $2.80*", "IDAHO  Clover  White", (2.80, None, False)),  # footnote marker
    ("TEXAS  Wildflower  Light Amber  1.80 1/", "TEXAS  Wildflower  Light Amber", (1.80, None, False)),
    ("CANADA  No Sales Reported", None, None),
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


@pytest.mark.parametrize("text,floral,grade,problem", [
    ("Extra Light Amber", [], "extra light amber", None),
    ("Clover Light Amber", ["Clover"], "light amber", None),
    # "Extra Light" is how the March 2025 issue (and the HTS 0409000045 table title) prints Extra Light Amber
    ("Mixed Flower Extra Light", ["Mixed", "Flower"], "extra light amber", None),
    ("Honey Dew ELA", ["Honey", "Dew"], "extra light amber", None),
    ("Alfalfa Whitte", ["Alfalfa"], "white", None),                     # misprint in the May 2024 issue
    ("Amber or Darker", [], "amber or darker", None),
    ("Mixed Flower Flower White", ["Mixed", "Flower", "Flower"], "white", None),   # July 2025, as printed
    ("Clover", ["Clover"], None, None),
    # never guessed: garbled cell of the July 2025 issue, colour ranges of the 2023-2024 issues
    ("CanoLight Amber White", None, "white", "more than one colour grade or a colour range"),
    ("Clover White / Extra Light", None, "extra light amber", "more than one colour grade or a colour range"),
    ("Valley Extra Light / Light", None, None, "colour grade not readable"),
])
def test_split_color(text, floral, grade, problem):
    rest, got_grade, start, got_problem = split_color(text.split())
    assert (got_grade, got_problem) == (grade, problem)
    if floral is not None:
        assert rest == floral and start == len(floral)


@pytest.mark.parametrize("descriptor,expected", [
    ("Honey Dew  White", ("Honey Dew", "white", False, "honeydew")),
    ("Organic  Light Amber", (None, "light amber", True, "unspecified")),
    ("Mixed  Light Amber", ("Mixed", "light amber", False, "polyflora")),
    ("Organic Mixed Flower  Extra Light Amber", ("Mixed Flower", "extra light amber", True, "organic_polyflora")),
    ("Canola  White", ("Canola", "white", False, "rapeseed")),
    ("Tallow  Light Amber", ("Tallow", "light amber", False, "other")),
    ("Light Amber", (None, "light amber", False, "unspecified")),
    ("Basswood, Linden  White", ("Basswood, Linden", "white", False, "linden")),
    ("Polyfloral  Extra Light", ("Polyfloral", "extra light amber", False, "polyflora")),
    ("(blank)  Light Amber", (None, "light amber", False, "unspecified")),    # empty pivot-table cell
])
def test_describe(descriptor, expected):
    assert describe(descriptor) == expected


@pytest.mark.parametrize("line,issue,expected", [
    ("HONEY MARKET FOR THE MONTH OF FEBURARY 2025", date(2025, 3, 28), ((2025, 2), "FEBURARY 2025")),
    ("HONEY MARKET FOR THE MONTH OF JANURARY 2025", date(2025, 2, 28), ((2025, 1), "JANURARY 2025")),
    ("HONEY MARKET FOR THE MONTH OF SEPTEMBER 2026", date(2026, 10, 30), ((2026, 9), "SEPTEMBER 2026")),
    ("HONEY MARKET FOR THE MONTH OF DECEMBER 2024", date(2025, 1, 29), ((2024, 12), "DECEMBER 2024")),
    # a month far from the issue date, or a word that is no month: not used
    ("HONEY MARKET FOR THE MONTH OF MAY 2026", date(2025, 6, 30), (None, "MAY 2026")),
    ("HONEY MARKET FOR THE MONTH OF HARVEST 2025", date(2025, 6, 30), (None, "HARVEST 2025")),
    ("IN VOLUMES OF 10,000 POUNDS OR GREATER UNLESS OTHERWISE STATED", date(2025, 6, 30), (None, None)),
])
def test_market_month(line, issue, expected):
    assert market_month(line, issue) == expected


@pytest.mark.parametrize("label,expected", [
    ("ARGENTINA", ("ARG", None)),
    ("QUEBEC, CANADA", ("CAN", "QUEBEC")),
    ("BRITISH COLUMBIA (INTERIOR), CANADA", ("CAN", "BRITISH COLUMBIA (INTERIOR)")),
    ("MANITOBA", ("CAN", "MANITOBA")),
    ("GERMANY, FED. REPUBLIC", ("DEU", None)),
    ("TURKIYE", ("TUR", None)),
    ("KOREA, SOUTH", ("KOR", None)),
    ("CHINA(MAINLAND)", ("CHN", None)),
    ("REPUBLIC OF SOUTH AFRICA", ("ZAF", None)),
    ("Grand Total", ("WLD", None)),
    ("GUINEA", ("GIN", None)),         # every ISO country is recognised
    ("ATLANTIS", (None, None)),        # not a country: skipped, not invented
])
def test_ace_origin(label, expected):
    assert ace_origin(label) == expected


def _glyph(text, x0, width, bottom=264.6, size=13.2, matrix=(0.821, -1e-17, -1e-17, 1.096)):
    return {"text": text, "x0": x0, "x1": x0 + width, "top": bottom - size, "bottom": bottom, "size": size,
            "matrix": (*matrix, x0, 800 - bottom)}


def test_chars_to_words_reads_compressed_glyphs_as_words():
    """The real tables use horizontally compressed glyphs (matrix 0.821/1.096, b and c a hair off
    zero): pdfplumber calls them not upright and spells 'D A K O T A'. A space glyph drawn on top of
    the first digit of a right-aligned number (CBP tables) must not split '11,102'."""
    chars = [_glyph(c, 35.8 + 7.0 * i, 7.0) for i, c in enumerate("DAKOTA")]
    chars += [_glyph(c, 109.9 + 5.0 * i, 5.0) for i, c in enumerate("Clover")]
    digits = [_glyph(c, 183.64 + 3.84 * i, 3.9, bottom=120.5, size=7.68) for i, c in enumerate("11,102")]
    space = _glyph(" ", 183.64, 1.93, bottom=120.5, size=7.68)
    rotated = _glyph("X", 300.0, 5.0, matrix=(0.0, 1.0, -1.0, 0.0))
    words = chars_to_words(dedupe_glyphs([*chars, *digits, space, rotated, dict(chars[0])]))
    assert sorted(w["text"] for w in words) == ["11,102", "Clover", "DAKOTA"]


def _word(text, x0, bottom, cw=5.0):
    return {"text": text, "x0": x0, "x1": x0 + cw * len(text), "top": bottom - 9, "bottom": bottom, "size": 9}


def test_column_blocks_split_tables_printed_side_by_side():
    """Two tables side by side with their own row pitch become two blocks; one table whose cells
    share baselines stays one block."""
    heading, x = [], 80.0               # a paragraph line: words one space (5 pt) apart
    for text in "Prices paid to beekeepers for extracted honey, cents per pound, delivered nearby".split():
        heading.append(_word(text, x, 60))
        x += 5 * len(text) + 5
    left = [w for i in range(8) for w in (_word("STATE", 36, 100 + 17 * i), _word("Clover", 110, 100 + 17 * i),
                                          _word("White", 190, 100 + 17 * i), _word("$1.91", 262, 100 + 17 * i))]
    right = [w for i in range(10) for w in (_word("ORIGIN", 315, 96 + 14.6 * i), _word("Mixed", 380, 96 + 14.6 * i),
                                            _word("White", 450, 96 + 14.6 * i), _word("$1.64", 530, 96 + 14.6 * i))]
    blocks = column_blocks(heading + left + right, 612.0, 5.5)
    assert [len(b) for b in blocks] == [len(heading), len(left), len(right)]
    assert {w["x0"] for w in blocks[1]} == {36, 110, 190, 262} and {w["x0"] for w in blocks[2]} == {315, 380, 450, 530}
    one_table = [w for i in range(12) for w in (_word("STATE", 36, 100 + 15 * i), _word("Clover", 200, 100 + 15 * i),
                                                _word("$1.91", 520, 100 + 15 * i))]
    assert len(column_blocks(heading + one_table, 612.0, 5.5)) == 1


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
    assert lines[1].x0 == 126 and lines[1].word_x == (126, 216, 366)


def test_lines_from_text_pages_and_indent():
    lines = lines_from_text("A  B\n\n   C\n\fD\n")
    assert [(ln.page, ln.text, ln.indent) for ln in lines] == [(1, "A  B", 0.0), (1, "C", 3.0), (2, "D", 0.0)]
    assert lines[0].word_x == (0.0, 3.0) and lines[1].x0 == 3.0


# =============================================================================================
# National Honey Report - whole documents: REAL issues (tests/fixtures/usda/README.md)
# =============================================================================================


@functools.cache
def real(name: str):
    return parse_honey_report_pdf(fx(name))


def by_key(parse):
    out: dict = {}
    for x in parse.prices:
        out.setdefault((x.section, x.label, x.descriptor, x.color_grade, x.organic), []).append(x)
    return out


MARCH_2025 = "real_fvmhoney_2025-03-28_p1-3-4.pdf"
OCTOBER_2026 = "real_fvmhoney_2026-10-30_p1-2-11.pdf"
DECEMBER_2024 = "real_fvmhoney_2024-12-26_p1-2-6.pdf"
JUNE_2025_FIRST = "real_fvmhoney_2025-06-30_first_p1-2.pdf"
JUNE_2025_CORRECTED = "real_fvmhoney_2025-06-30_corrected_p1-2.pdf"
APRIL_2025_IMAGES = "real_fvmhoney_2025-04-30_p1.pdf"
TOMATO = "real_esmis_misfiled_tomato_2025-05-15_p1.pdf"
MAY_2026_IMPORTS = "real_fvmhoney_2026-05-29_p1-9-10.pdf"       # MyMarketNews copy


def test_real_two_column_page_is_split_and_compressed_glyphs_read():
    """March 2025, page 1: US beekeepers on the left, Canada + importers on the right, beekeeper
    glyphs compressed. The live run read 'D A K O T A C lo v e r ... ARGENTINA Mixed Flower White $1.64'."""
    page1 = [ln.text for ln in pdf_to_lines(fx(MARCH_2025)) if ln.page == 1]
    assert "DAKOTA  Clover  Extra Light Amber  $1.85" in page1
    assert "MONTANA  Clover  White  $1.91" in page1
    assert "ARGENTINA  Mixed Flower  White  $1.64" in page1
    assert "CANADA  Canola  White  $1.35" in page1
    # reading order: the whole left column, then the right column
    assert page1.index("NEW YORK  Mixed Flower  White  $3.00") < page1.index("CANADA  Canola  White  $1.35")


def test_real_march_2025_issue():
    p = real(MARCH_2025)
    assert p.issue_date == date(2025, 3, 28) and (p.volume, p.number) == ("XLV", 3)
    assert p.market_month == (2025, 2) and p.market_month_printed == "FEBURARY 2025" and not p.corrected
    assert p.sections == ["beekeeper", "canadian_beekeeper", "importer", "exports", "ace_imports"]
    assert Counter(x.section for x in p.prices) == {"beekeeper": 10, "canadian_beekeeper": 2, "importer": 21}
    assert all(x.currency == "USD" and x.unit == "lb" and not x.printed_in_cents for x in p.prices)
    k = by_key(p)
    [dakota_ela] = k[("beekeeper", "DAKOTA", "Clover", "extra light amber", False)]
    [dakota_white] = k[("beekeeper", "DAKOTA", "Clover", "white", False)]       # "White $1.85" in the colour column
    assert (dakota_ela.value, dakota_white.value, dakota_white.floral_inherited) == (1.85, 1.85, True)
    assert dakota_ela.origin_iso3 == "USA" and dakota_ela.market_iso3 == "USA"
    [ny] = k[("beekeeper", "NEW YORK", "Mixed Flower", "white", False)]
    assert (ny.value, ny.low, ny.high, ny.variety) == (3.00, None, None, "polyflora")
    [fl] = k[("beekeeper", "FLORIDA", "Brazilian Pepper", "light amber", False)]
    assert fl.value == 1.50
    [canola] = k[("canadian_beekeeper", "CANADA", "Canola", "white", False)]
    assert (canola.value, canola.market_iso3, canola.origin_iso3, canola.currency) == (1.35, "CAN", "CAN", "USD")
    arg = k[("importer", "ARGENTINA", "Mixed Flower", "extra light amber", False)]
    assert [(a.low, a.high, a.value, a.floral_inherited) for a in arg] == [(1.47, 1.62, 1.545, True)]
    assert [a.value for a in k[("importer", "ARGENTINA", "Mixed Flower", "white", False)]] == [1.64, 1.53]
    [bra_org] = k[("importer", "BRAZIL", None, "light amber", True)]
    assert (bra_org.low, bra_org.high, bra_org.origin_iso3) == (1.42, 1.85, "BRA")
    assert [x.value for x in k[("importer", "INDIA", "Mustard", "amber", False)]] == [1.09]
    assert [x.value for x in k[("importer", "UKRAINE", "Sunflower", "white", False)]] == [1.04]
    assert [x.value for x in k[("importer", "VIETNAM", "Mixed Flower", "light amber", False)]] == [1.02]
    assert "duty paid" in bra_org.terms and "ex-dock or point of entry" in bra_org.terms
    # CBP ACE table, HTS 0409000045 ("Extra Light"), February 2025, '$' in its own cell
    assert len(p.imports) == 17 and {(r.hts_code, r.year, r.month) for r in p.imports} == {("0409000045", 2025, 2)}
    [ace_arg] = [r for r in p.imports if r.origin_iso3 == "ARG"]
    assert ace_arg.color_grade == "extra light amber" and not ace_arg.organic
    assert (ace_arg.kilograms, ace_arg.value, ace_arg.cif_value, ace_arg.total_value) == (694418, 1857205, 86302, 1943507)
    assert ace_arg.ytd == {"kg": 2029192, "value": 4927528, "cif": 292196, "total": 5219724}
    [quebec] = [r for r in p.imports if r.region]
    assert (quebec.origin_iso3, quebec.region, quebec.kilograms) == ("CAN", "QUEBEC", 738)
    [total] = [r for r in p.imports if r.origin_iso3 == "WLD"]
    assert (total.kilograms, total.value) == (4565860, 10989273)
    # BULGARIA prints 7 cells for 8 columns: skipped, never realigned by guess
    assert p.warnings == ["import tables: 1 row(s) whose cells do not match the column header skipped "
                          "(p.3 BULGARIA (7/8 cells))"]


def test_real_october_2026_issue():
    """The AMS 'latest issue' file of Nov 2026: pivot-table layout, compressed glyphs on page 2."""
    p = real(OCTOBER_2026)
    assert p.issue_date == date(2026, 10, 30) and (p.volume, p.number) == ("XLVI", 10)
    assert p.market_month == (2026, 9)
    assert Counter(x.section for x in p.prices) == {"beekeeper": 64, "canadian_beekeeper": 2, "importer": 14}
    k = by_key(p)
    assert [x.value for x in k[("beekeeper", "TEXAS", "Clover", "white", False)]] == [2.35]
    [valley_la] = k[("beekeeper", "CALIFORNIA", "Valley", "light amber", False)]
    assert (valley_la.value, valley_la.floral_inherited) == (2.23, True)
    # two "Clover" groups under DAKOTA, both kept as printed
    assert [(x.low, x.high) for x in k[("beekeeper", "DAKOTA", "Clover", "white", False)]] == [(2.29, 2.35),
                                                                                              (1.90, 2.35)]
    [blank] = k[("beekeeper", "WISCONSIN", None, "light amber", False)]          # "(blank)" floral cell
    assert (blank.value, blank.variety) == (2.60, "unspecified")
    [linden] = k[("beekeeper", "MINNESOTA", "Basswood, Linden", "white", False)]
    assert (linden.value, linden.variety) == (2.23, "linden")
    [can_la] = k[("canadian_beekeeper", "CANADA", "Canola", "light amber", False)]
    assert (can_la.value, can_la.market_iso3, can_la.floral_inherited) == (1.46, "CAN", True)
    [arg] = [x for x in k[("importer", "ARGENTINA", "Mixed", "white", False)] if not x.floral_inherited]
    assert (arg.low, arg.high, arg.value, arg.variety) == (1.52, 2.07, 1.795, "polyflora")
    assert [x.value for x in k[("importer", "INDIA", "Mustard", "extra light amber", False)]] == [1.04]
    [bra_org] = k[("importer", "BRAZIL", None, "light amber", True)]
    assert (bra_org.low, bra_org.high) == (2.13, 2.23)
    [ury] = k[("importer", "URUGUAY", "Mixed", "light amber", False)]
    assert (ury.low, ury.high) == (1.55, 1.83)
    # "Mixed  White  $2.15 - $1.45" under CANADA: low > high, skipped
    assert "p.2: price range with low > high - skipped [Mixed White $2.15 - $1.45]" in p.warnings
    assert not any(x.value == 2.15 and x.section == "canadian_beekeeper" for x in p.prices)
    [ace_arg] = [r for r in p.imports if r.origin_iso3 == "ARG"]
    assert (ace_arg.year, ace_arg.month, ace_arg.hts_code) == (2026, 9, "0409000045")
    assert (ace_arg.kilograms, ace_arg.value, ace_arg.cif_value) == (2409164, 7097909, 220853)
    [total] = [r for r in p.imports if r.origin_iso3 == "WLD"]
    assert (total.kilograms, total.value, total.total_value) == (5162319, 11693809, 12334944)


def test_real_december_2024_issue_with_narrative():
    """Dec 2024: the beekeeper table continues at the top of the right column; the last issue with
    the 'Colony, honey plant and market conditions' narrative; a misspelt state label."""
    p = real(DECEMBER_2024)
    assert p.market_month == (2024, 11) and p.issue_date == date(2024, 12, 26)
    assert Counter(x.section for x in p.prices) == {"beekeeper": 41, "importer": 27}
    beek = [x.label for x in p.prices if x.section == "beekeeper"]
    assert beek[-6:] == ["NEBRASKA", "OREGON", "TEXAS", "UTAH", "WASHINGTON", "WYOMING"]
    [georgia] = [x for x in p.prices if x.label == "GEORGIA"]
    assert (georgia.label_as_printed, georgia.descriptor, georgia.value) == ("GEORIGA", "Tallow", 1.50)
    k = by_key(p)
    assert [x.value for x in k[("beekeeper", "MICHIGAN", "Basswood", "extra light amber", False)]] == [2.80]
    assert [(x.low, x.high) for x in k[("importer", "VIETNAM", "Mixed Flower", "light amber", False)]] == [(0.84, 1.22)]
    assert p.narrative.startswith("COLONY, HONEY PLANT AND MARKET CONDITIONS DURING NOVEMBER 2024")
    assert "APPALACHIAN DISTRICT (MD, PA, VA, WV): November began warmer than normal" in p.narrative
    [ace_arg] = [r for r in p.imports if r.origin_iso3 == "ARG"]
    assert ace_arg.hts_code == "0409000056" and ace_arg.color_grade == "light amber"   # title wrapped on 2 lines
    assert (ace_arg.year, ace_arg.month, ace_arg.kilograms, ace_arg.value) == (2024, 11, 1002501, 2088617)


def test_real_corrected_copy_changes_the_market_month():
    first, corrected = real(JUNE_2025_FIRST), real(JUNE_2025_CORRECTED)
    assert first.issue_date == corrected.issue_date == date(2025, 6, 30)
    assert (first.market_month, first.corrected) == ((2025, 6), False)
    assert (corrected.market_month, corrected.corrected) == ((2025, 5), True)

    def rows(p):
        return [(x.section, x.label, x.descriptor, x.color_grade, x.low, x.high, x.value) for x in p.prices]
    assert rows(first) == rows(corrected) and len(rows(first)) == 44
    assert ("beekeeper", "TEXAS", "Clover", "white", None, None, 1.90) in rows(first)
    assert ("beekeeper", "TEXAS", "Clover", "white", None, None, 1.95) in rows(first)     # printed twice


def test_real_price_tables_printed_as_images_are_reported():
    p = real(APRIL_2025_IMAGES)
    assert p.prices == [] and p.market_month == (2025, 3)
    assert ("p.1: the 'beekeeper' price table is printed as an image in this PDF (not machine-readable) - "
            "no prices taken from it") in p.warnings


def test_real_misfiled_esmis_file_is_not_a_honey_report():
    with pytest.raises(NotAHoneyReport, match="TOMATO"):
        parse_honey_report_pdf(fx(TOMATO))


# =============================================================================================
# National Honey Report - state machine on text layouts (edge cases)
# =============================================================================================


def test_real_import_table_without_title_is_skipped_not_filed_under_the_table_above():
    """The May 29, 2026 issue prints an import table without its title (original p.10, here p.3). Its rows
    used to be filed under the HTS 0409000065 table above it (Ukraine $2.33/kg over the page-9 figure of
    $7.88/kg); the HTS code is unknown, so they are skipped."""
    parse = real(MAY_2026_IMPORTS)
    assert parse.issue_date == date(2026, 5, 29) and parse.market_month == (2026, 4)
    assert {(r.hts_code, r.page, r.year, r.month) for r in parse.imports} == {("0409000065", 2, 2026, 4)}
    assert len(parse.imports) == 86
    assert [(r.kilograms, r.value) for r in parse.imports if r.origin_iso3 == "UKR"] == [(12366, 97431)]
    assert [w[:110] for w in parse.warnings if "without a title" in w] == [
        "p.3: import table without a title (after 'Natural Honey, Not For Retail Sale, Amber or Darker (HTS Cod') - its"]


def test_text_layout_floral_source_and_organic_carry_down_the_colour_column():
    text = "\n".join([
        "Volume XLV - Number 3      Issued Monthly      March 28, 2025",
        "HONEY MARKET FOR THE MONTH OF FEBRUARY 2025",
        "Prices paid to importers for bulk honey, duty paid, containers included, ex-dock or point of entry.",
        "ARGENTINA   Mixed Flower   White         $1.64",
        "                           Extra Light   $1.47 - $1.62",
        "            ORGANIC        Light Amber   $1.42 - $1.85",
        "                           Amber         $1.50",
        "            Light Amber                  $1.40",
    ])
    p = parse_honey_report_lines(lines_from_text(text))
    assert p.market_month == (2025, 2) and p.warnings == []
    assert [(x.descriptor, x.organic, x.color_grade, x.value, x.floral_inherited) for x in p.prices] == [
        ("Mixed Flower", False, "white", 1.64, False),
        ("Mixed Flower", False, "extra light amber", 1.545, True),
        (None, True, "light amber", 1.635, False),
        (None, True, "amber", 1.50, True),
        (None, False, "light amber", 1.40, False),       # starts in the floral column: no floral source
    ]


def test_text_layout_rows_below_a_skipped_row_never_inherit_a_wrong_floral_source():
    text = "\n".join([
        "HONEY MARKET FOR THE MONTH OF AUGUST 2024",
        "Prices paid to beekeepers for extracted, unprocessed honey in major producing states.",
        "DAKOTAS   Clover     White                  $1.85",
        "          Canola     White / Extra Light    $1.91",
        "                     Light Amber            $1.91",
        "          Spurge     White                  $1.91",
        "                     Light Amber            $9.91 - $1.91",
        "                     Amber                  $1.80",
    ])
    p = parse_honey_report_lines(lines_from_text(text))
    assert [(x.descriptor, x.color_grade, x.value) for x in p.prices] == [
        ("Clover", "white", 1.85), ("Spurge", "white", 1.91), ("Spurge", "amber", 1.80)]
    assert p.warnings == [
        "p.1: more than one colour grade or a colour range - row skipped [Canola White / Extra Light $1.91]",
        "p.1: floral source of the row above not readable - row skipped [Light Amber $1.91]",
        "p.1: price range with low > high - skipped [Light Amber $9.91 - $1.91]",
    ]


def test_unknown_and_unparseable_content_is_warned_never_guessed():
    text = "\n".join([
        "Volume XLVI - Number 6          Page 1          July 31, 2026",
        "Prices paid to importers for bulk honey, duty paid, containers included, ex-dock or point of entry.",
        "ARGENTINA          Light Amber      $1.50",
        "ATLANTIS           Light Amber      $1.10",
        "                   White            $1.20",
        "BRAZIL             Light Amber      $45.00",
        "INDIA  Mixed  White  $1.01      VIETNAM  Mixed Flower  White  $1.02",     # two tables merged
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
    assert p.issue_date == date(2026, 7, 31) and p.market_month is None
    assert [(x.label, x.value) for x in p.prices] == [("ARGENTINA", 1.50)]
    assert p.imports == []
    joined = "\n".join(p.warnings)
    assert "unknown origin 'ATLANTIS'" in joined               # also for its continuation row
    assert joined.count("unknown origin 'ATLANTIS'") == 2
    assert "implausible price 45.0" in joined
    assert "row holds more than one price (two tables side by side?)" in joined
    assert "unparsed line in 'importer' table" in joined
    assert "unrecognised price section" in joined and "1 price-like line(s) skipped" in joined
    assert "currency of the Canadian table not stated" in joined
    assert "has no month" in joined


@pytest.mark.parametrize("rows,expected", [
    (["NARNIA, NORTH      Extra Light Amber  $2.40"], ["unknown origin 'NARNIA, NORTH'"]),
    (["Narnia             Extra Light Amber  $2.40"], ["unknown origin 'Narnia'"]),
    (["Westeros Republic  Extra Light Amber  $2.40"], ["unknown origin 'Westeros Republic'"]),
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
        "The import data is sourced from the Customs and Border Protection's Automated Commercial Environment (ACE).",
        "Natural Honey, Certified for Organic (HTS Code 0409000005)",
        "Month:   May 2026   2026 TOTAL TO DATE",
        "Country of Origin",
        "     Kilograms       Value   CIF Value Total Value",
        "BRAZIL                 3,412,880  $ 12,051,200  $   402,310  $ 12,453,510",
        "NARNIA                    10,000      20,000       1,000      21,000",
        "MEXICO                   120,060     455,100",
        "URUGUAY                        -   $       -   $       -   $       -",
        "1. Source: Customs and Border Protection (CBP) Automated Commercial Environment (ACE)",
    ])
    p = parse_honey_report_lines(lines_from_text(text))
    assert [(r.origin_iso3, r.kilograms, r.value, r.year, r.month) for r in p.imports] == [
        ("BRA", 3412880, 12051200, 2026, 5), ("URY", None, None, 2026, 5)]
    assert p.warnings == [
        "import tables: 1 row(s) of origins outside the country list skipped (NARNIA)",
        "import tables: 1 row(s) whose cells do not match the column header skipped (p.1 MEXICO (2/4 cells))",
    ]


def test_group_warnings_merges_row_level_messages():
    assert group_warnings([
        "p.1: colour grade not readable - row skipped [Valley Extra Light / Light $2.80]",
        "p.2: colour grade not readable - row skipped [Buckwheat Extra Light / Light $1.91]",
        "section 'canadian_beekeeper' found but no row could be parsed",
    ]) == [
        ("colour grade not readable - row skipped (2x, e.g. p.1 [Valley Extra Light / Light $2.80]; "
         "p.2 [Buckwheat Extra Light / Light $1.91])"),
        "section 'canadian_beekeeper' found but no row could be parsed",
    ]


def test_pdf_parser_rejects_unusable_documents():
    with pytest.raises(CollectorError, match="not a PDF"):
        parse_honey_report_pdf(b"<html>Service unavailable</html>")
    with pytest.raises(CollectorError, match="could not be read"):
        parse_honey_report_pdf(b"%PDF-1.7\nthis is not really a pdf")


def test_parse_esmis_releases_real_listing():
    """The real ESMIS answer lists most releases twice (agency 'AMS' and 'AMS-SC')."""
    payload = json.loads(fx("real_esmis_fvmhoney_page0.json"))
    assert len(payload["results"]) == 25
    releases, warnings = parse_esmis_releases(payload)
    assert warnings == []
    assert len(releases) == 13 == len({r.release_id for r in releases})
    assert releases[0].release_date == date(2025, 9, 30) and releases[-1].release_date == date(2025, 2, 28)
    assert releases[0].pdf_url.endswith("/m613mx60p/7p88fj37r/rr173w627/FVMHONEY.PDF")
    assert date(2025, 5, 15) in [r.release_date for r in releases]   # the misfiled tomato report: known only by its PDF
    with pytest.raises(CollectorError):
        parse_esmis_releases({"message": ""})
    rel, warn = parse_esmis_releases({"results": [{"id": "1", "release_datetime": "soon", "files": []}]})
    assert rel == [] and warn


# =============================================================================================
# National Honey Report - collector end to end (real fixtures)
# =============================================================================================

ESMIS_BASE = "https://esmis.nal.usda.gov/sites/default/release-files/m613mx60p/"
ESMIS_FILES = {     # ESMIS release date -> (file URL as listed in the real ESMIS answer, fixture)
    "2025-03-28": (ESMIS_BASE + "4j03fv56x/p841bj501/FVMHONEY.PDF", MARCH_2025),
    "2025-04-30": (ESMIS_BASE + "4742c648m/j67332753/FVMHONEY.PDF", APRIL_2025_IMAGES),
    "2025-05-15": (ESMIS_BASE + "ff367354m/ww72d826j/FVMHONEY.PDF", TOMATO),
    "2025-07-01": (ESMIS_BASE + "9p2928560/3n205z785/FVMHONEY.PDF", JUNE_2025_FIRST),
    "2025-07-02": (ESMIS_BASE + "w0894925c/bn99c5321/FVMHONEY.PDF", JUNE_2025_CORRECTED),
}


def esmis_listing(dates=tuple(ESMIS_FILES)) -> bytes:
    """The real ESMIS answer, restricted to the releases whose PDFs the tests serve."""
    payload = json.loads(fx("real_esmis_fvmhoney_page0.json"))
    payload["results"] = [r for r in payload["results"] if r["release_datetime"][:10] in dates]
    return json.dumps(payload).encode()


MMN_FILES_BASE = "https://mymarketnews.ams.usda.gov/filerepo/sites/default/files/2901/"
MMN_PAGE0 = r"^https://mymarketnews\.ams\.usda\.gov/filerepo/reports\?field_slug_id_value=2901$"
MMN_PAGE1 = r"^https://mymarketnews\.ams\.usda\.gov/filerepo/reports\?field_slug_id_value=2901&page=1$"
OCTOBER_2025_CORRECTED = "real_fvmhoney_2025-10-31_corrected_p1-2-10.pdf"
SEPTEMBER_2026 = "real_fvmhoney_2026-09-30_p1-2-11.pdf"
# MyMarketNews listing date -> (document URL as in the REAL listing, fixture served: page subsets of the
# issue; the December 2024 and March 2025 subsets were cut from the ESMIS copy of the same issue)
MMN_FILES = {
    "2024-12-26": (MMN_FILES_BASE + "2024-12-26/1182116/ams_2901_00062.pdf", DECEMBER_2024),
    "2025-03-28": (MMN_FILES_BASE + "2025-03-28/1232225/ams_2901_00065.pdf", MARCH_2025),
    "2025-05-15": (MMN_FILES_BASE + "2025-05-15/1244645/ams_2901_00067.pdf", TOMATO),     # also misfiled here
    "2025-11-12": (MMN_FILES_BASE + "2025-11-12/1285160/ams_2901_00078.pdf", OCTOBER_2025_CORRECTED),
    "2026-09-30": (MMN_FILES_BASE + "2026-09-30/1355143/ams_2901_00094.pdf", SEPTEMBER_2026),
    # a re-upload of the September 2026 issue: the very same file (checked live, sha256 d6e043d4...)
    "2026-10-23": (MMN_FILES_BASE + "2026-10-23/1360720/ams_2901_00095_01.pdf", SEPTEMBER_2026),
    "2026-10-30": (MMN_FILES_BASE + "2026-10-30/1362397/ams_2901_00096.pdf", OCTOBER_2026),
}
# issues on file from ESMIS (March 2025) or the AMS URL (October 2026) are never requested from MyMarketNews
MMN_NOT_ELSEWHERE = tuple(d for d in MMN_FILES if d not in ("2025-03-28", "2026-10-30"))


def mmn_listing(dates: tuple[str, ...] | None = tuple(MMN_FILES), next_page: bool = True) -> bytes:
    """The real MyMarketNews listing (page 0: 50 documents, 2023-07-26 .. 2026-10-30), restricted to
    the rows of `dates` (None: all) and, without `next_page`, to a single page."""
    text = fx("real_mmn_filerepo_2901_page0.html").decode()
    if dates is not None:
        def keep(m: re.Match) -> str:
            found = re.search(r"/files/2901/(\d{4}-\d{2}-\d{2})/", m.group(0))
            return m.group(0) if found is None or found.group(1) in dates else ""
        text = re.sub(r"<tr>.*?</tr>", keep, text, flags=re.S)
    if not next_page:
        text = re.sub(r'<nav class="pager".*?</nav>', "", text, flags=re.S)
    return text.encode()


def mmn_routes(dates=MMN_NOT_ELSEWHERE, *, files=True, **override) -> dict:
    """Listing pages 0 (filtered to MMN_FILES) and 1 (real), plus the documents of `dates`."""
    routes = {MMN_PAGE0: (200, mmn_listing(), "text/html; charset=UTF-8"),
              MMN_PAGE1: (200, fx("real_mmn_filerepo_2901_page1.html"), "text/html; charset=UTF-8")}
    if files:
        routes.update({MMN_FILES[d][0]: (200, fx(MMN_FILES[d][1]), "application/pdf") for d in dates})
    routes.update(override)
    return {k: v for k, v in routes.items() if v is not None}


def honey_routes(**override):
    routes = {
        usda.ESMIS_FVMHONEY_URL: (200, esmis_listing(), "application/json"),
        usda.AMS_LATEST_URL: (200, fx(OCTOBER_2026), "application/pdf"),
        # the MyMarketNews listing reduced to the issue the AMS URL serves: nothing to fill from it
        MMN_PAGE0: (200, mmn_listing(dates=("2026-10-30",), next_page=False), "text/html; charset=UTF-8"),
    }
    for url, name in ESMIS_FILES.values():
        routes[url] = (200, fx(name), "application/pdf")
    routes.update(override)
    return {k: v for k, v in routes.items() if v is not None}


# rows the October 2026 issue stores: 80 prices + 9 ACE unit values (rows of at least 1,000 kg)
OCT_2026_ROWS = 80 + 9


def test_honey_report_end_to_end(run_with_routes, session_factory):
    res = run_with_routes("usda_honey_report", honey_routes())
    assert res["status"] == "partial", res        # the real issues carry warnings (see below)
    warnings = "\n".join(res["warnings"])
    assert "2025-05-15" in warnings and "is filed under FVMHONEY but not a National Honey Report" in warnings
    assert "'beekeeper' price table is printed as an image" in warnings
    assert ("National Honey Report – June 30, 2025 (corrected copy): corrected copy - 44 row(s) published only "
            "by the earlier copy of this issue were withdrawn") in warnings
    assert "price range with low > high - skipped [Mixed White $2.15 - $1.45]" in warnings
    with session_factory() as s:
        src = one(s, Source, Source.key == "usda_honey_report")
        assert src.latest_published_at == date(2026, 10, 30)
        reports = {r.report_key: r for r in s.scalars(select(Report).where(Report.source_id == src.id))}
        # the misfiled tomato report is not registered as a honey report
        assert sorted(reports) == ["2025-03-28", "2025-04-30", "2025-07-01", "2025-07-02", "2026-10-30"]
        assert {k: r.period_label for k, r in reports.items()} == {
            "2025-03-28": "2025-02", "2025-04-30": "2025-03", "2025-07-01": "2025-06", "2025-07-02": "2025-05",
            "2026-10-30": "2026-09"}
        assert reports["2025-07-02"].title == "National Honey Report – June 30, 2025 (corrected copy)"
        assert reports["2025-03-28"].url == ESMIS_FILES["2025-03-28"][0]
        assert reports["2026-10-30"].url == usda.AMS_LATEST_URL and reports["2026-10-30"].raw_document_id
        state = s.get(AppSetting, "collector_state:usda_honey_report").value
        assert list(state["not_fvmhoney"]) == [ESMIS_FILES["2025-05-15"][0]] and state["esmis_backfill_done"]

        P = PriceObservation
        current = P.is_current.is_(True)
        # March 2025 (33 prices + 12 ACE) + June 2025 corrected (44) + October 2026; the first June copy is withdrawn
        assert count(s, P, current) == 33 + 12 + 44 + OCT_2026_ROWS
        assert count(s, P, P.is_current.is_(False)) == 44
        # price types never mixed: wholesale = importer table (market USA), import UV always per kg
        assert count(s, P, P.price_type == PriceType.WHOLESALE_BULK.value, P.market_iso3 != "USA") == 0
        assert count(s, P, P.price_type == PriceType.IMPORT_UNIT_VALUE.value, P.unit != "kg") == 0
        assert count(s, P, P.price_type != PriceType.IMPORT_UNIT_VALUE.value, P.unit != "lb") == 0
        assert count(s, P, P.price_type != PriceType.IMPORT_UNIT_VALUE.value, P.currency != "USD") == 0

        # market month, not the issue month
        ny = one(s, P, P.period_label == "2025-02", P.origin_label == "New York")
        assert (ny.price_type, ny.variety, ny.variety_raw, ny.color_grade) == ("producer", "polyflora",
                                                                                "Mixed Flower", "white")
        assert (ny.price_value, ny.currency, ny.unit, ny.published_at) == (3.00, "USD", "lb", date(2025, 3, 28))
        assert round(ny.price_per_kg, 4) == round(3.00 / LB, 4) == 6.6139
        assert (ny.period_start, ny.period_end, ny.frequency) == (date(2025, 2, 1), date(2025, 2, 28), "M")
        assert ny.source_url == ESMIS_FILES["2025-03-28"][0] and ny.extra["market_month_as_printed"] == "FEBURARY 2025"
        assert (ny.data_status, ny.reliability) == ("published", "official")
        assert ny.extra["parser_version"] == usda.PARSER_VERSION and ny.extra["page"] == 1

        arg = one(s, P, P.period_label == "2025-02", P.origin_iso3 == "ARG", P.price_type == "wholesale_bulk",
                  P.color_grade == "extra light amber")
        assert (arg.price_low, arg.price_high, arg.price_value) == (1.47, 1.62, 1.545)
        assert arg.variety_raw == "Mixed Flower" and arg.extra["floral_source_from_row_above"] is True
        assert arg.origin_label == "Argentina" and arg.market_iso3 == "USA" and "duty paid" in arg.terms

        canola = one(s, P, P.market_iso3 == "CAN", P.period_label == "2025-02", P.variety == "rapeseed")
        assert (canola.price_type, canola.price_value, canola.variety, canola.currency) == ("producer", 1.35,
                                                                                           "rapeseed", "USD")

        ace = one(s, P, P.price_type == "import_unit_value", P.origin_iso3 == "ARG", P.period_label == "2025-02")
        assert ace.price_value == round(1857205 / 694418, 4) == 2.6745 and ace.volume_kg == 694418
        assert ace.color_grade == "extra light amber" and ace.published_at == date(2025, 3, 28)
        assert ace.extra["cif_value_usd"] == 86302 and ace.extra["hts_code"] == "0409000045"
        assert "HTS 0409000045" in ace.terms
        manitoba = one(s, P, P.price_type == "import_unit_value", P.origin_label == "Canada (Manitoba)")
        assert manitoba.origin_iso3 == "CAN" and "|CAN|manitoba|2026-09" in manitoba.series_key
        assert manitoba.price_value == round(142683 / 39059, 4) and manitoba.volume_kg == 39059
        # no unit value from tiny lots (QUEBEC 738 kg, ITALY 3 kg in Feb 2025): same 1,000 kg rule as Comtrade/Eurostat
        assert count(s, P, P.price_type == "import_unit_value", P.volume_kg < usda.ACE_MIN_UNIT_VALUE_KG) == 0
        assert count(s, P, P.price_type == "import_unit_value", P.origin_iso3.in_(["ITA", "CAN"]),
                     P.period_label == "2025-02") == 0

        # corrected copy: the first copy's rows (filed under JUNE) are withdrawn, the May rows are current
        assert count(s, P, current, P.published_at == date(2025, 6, 30), P.period_label == "2025-06") == 0
        assert count(s, P, current, P.published_at == date(2025, 6, 30), P.period_label == "2025-05") == 44
        wyoming = one(s, P, current, P.period_label == "2025-05", P.origin_label == "Wyoming")
        assert (wyoming.price_value, wyoming.color_grade, wyoming.extra["corrected_copy"]) == (2.28, "light amber", True)

        # AMS latest issue: the file is overwritten monthly, prices link to the archived bytes
        texas = one(s, P, P.period_label == "2026-09", P.origin_label == "Texas")
        assert (texas.price_value, texas.variety, texas.color_grade) == (2.35, "clover", "white")
        assert texas.source_url == f"/api/reports/{reports['2026-10-30'].id}/file"
        assert texas.extra["fetched_from"] == usda.AMS_LATEST_URL and texas.published_at == date(2026, 10, 30)
        n_prices, n_reports, n_raw = count(s, P), count(s, Report), count(s, RawDocument)

    # second identical run: nothing new, no warning (the misfiled file is remembered), no duplicate rows
    res2 = run_with_routes("usda_honey_report", honey_routes())
    assert res2["status"] == "no_change", res2
    with session_factory() as s:
        assert (count(s, PriceObservation), count(s, Report), count(s, RawDocument)) == (n_prices, n_reports, n_raw)


def test_honey_report_falls_back_to_ams_when_esmis_fails(run_with_routes, session_factory):
    res = run_with_routes("usda_honey_report", honey_routes(**{usda.ESMIS_FVMHONEY_URL: (500, b"boom")}))
    assert res["status"] == "partial", res
    assert any("ESMIS archive unavailable" in w for w in res["warnings"])
    with session_factory() as s:
        assert [r.report_key for r in s.scalars(select(Report))] == ["2026-10-30"]
        assert count(s, PriceObservation) == OCT_2026_ROWS


def test_honey_report_uses_mirror_when_ams_fails(run_with_routes, session_factory):
    res = run_with_routes("usda_honey_report", honey_routes(**{
        usda.ESMIS_FVMHONEY_URL: (200, b'{"results": []}', "application/json"),
        usda.AMS_LATEST_URL: (404, b"not found"),
        usda.AMS_MIRROR_URL: (200, fx(OCTOBER_2026), "application/pdf"),
    }))
    assert res["status"] == "partial", res                  # the empty ESMIS list is reported
    assert any("empty National Honey Report release list" in w for w in res["warnings"])
    with session_factory() as s:
        report = one(s, Report)
        assert report.url == usda.AMS_MIRROR_URL
        rows = s.scalars(select(PriceObservation)).all()
        assert len(rows) == OCT_2026_ROWS
        assert all(r.source_url == f"/api/reports/{report.id}/file" for r in rows)
        assert all(r.extra["fetched_from"] == usda.AMS_MIRROR_URL for r in rows)


def test_honey_report_bad_latest_file_is_a_warning(run_with_routes, session_factory):
    res = run_with_routes("usda_honey_report", honey_routes(**{
        usda.AMS_LATEST_URL: (200, b"<html>maintenance</html>", "text/html")}))
    assert res["status"] == "partial", res
    assert any("AMS latest issue not processed: downloaded file is not a PDF" in w for w in res["warnings"])
    with session_factory() as s:
        assert count(s, PriceObservation, PriceObservation.is_current.is_(True)) == 33 + 12 + 44


def test_honey_report_offline(run_with_routes):
    assert run_with_routes("usda_honey_report", {})["status"] == "offline"


def test_honey_report_states_are_separate_price_series(run_with_routes, api):
    """Producer prices of different states share origin/market USA, colour and terms: the state
    (market_location) must keep them apart, never averaged into one line."""
    assert run_with_routes("usda_honey_report", honey_routes())["status"] == "partial"
    body = api.get("/api/prices/series", params={"price_type": "producer", "source": "usda_honey_report"}).json()

    def september(state: str, variety: str, color: str) -> dict:
        found = [s for s in body["series"]
                 if (s["market_location"], s["variety"], s["color_grade"]) == (state, variety, color)]
        assert len(found) == 1, [(s["market_location"], s["variety"], s["color_grade"]) for s in body["series"]]
        return {p["period_label"]: p for p in found[0]["points"]}["2026-09"]

    for state, variety, color, usd_lb in [
        ("Texas", "clover", "white", 2.35), ("Montana", "clover", "white", 2.35),
        ("Colorado", "rapeseed", "white", 2.70), ("Minnesota", "rapeseed", "white", 2.29),
        ("Wyoming", "clover", "extra light amber", 2.50), ("New York", "linden", "extra light amber", 3.00),
    ]:
        p = september(state, variety, color)
        assert p["n_points"] == 1, (state, p)
        assert p["original"]["value"] == usd_lb and p["original"]["unit"] == "lb"
        assert p["value"] == round(usd_lb / LB, 4)
    # "DAKOTA" is its own region, never joined to North or South Dakota
    places = {s["market_location"] for s in body["series"]}
    assert "Dakota" in places and not places & {"North Dakota", "South Dakota"}
    latest = api.get("/api/prices/latest", params={"price_type": "producer", "source": "usda_honey_report"}).json()
    assert len({r["series_id"] for r in latest["rows"]}) == len(latest["rows"]) == len(body["series"])


def test_honey_report_price_links_survive_the_monthly_overwrite(run_with_routes, api, session_factory):
    """AMS overwrites fvmhoney.pdf every month: a price parsed from it keeps a link to the exact
    archived file, not to whatever the URL serves next month."""
    assert run_with_routes("usda_honey_report", honey_routes())["status"] == "partial"
    with session_factory() as s:
        texas = one(s, PriceObservation, PriceObservation.period_label == "2026-09",
                    PriceObservation.origin_label == "Texas")
        link, fetched_from = texas.source_url, texas.extra["fetched_from"]
    assert fetched_from == usda.AMS_LATEST_URL and link.startswith("/api/reports/")
    # next month the same URL serves a different issue
    res = run_with_routes("usda_honey_report", honey_routes(**{
        usda.AMS_LATEST_URL: (200, fx(DECEMBER_2024), "application/pdf")}))
    assert res["status"] in ("success", "partial", "no_change"), res
    with session_factory() as s:
        texas = one(s, PriceObservation, PriceObservation.period_label == "2026-09",
                    PriceObservation.origin_label == "Texas")
        assert texas.source_url == link
    got = api.get(link)
    assert got.status_code == 200 and got.content == fx(OCTOBER_2026)
    rows = api.get("/api/prices/latest", params={"price_type": "producer", "source": "usda_honey_report"}).json()
    texas_row = next(r for r in rows["rows"] if r["market_location"] == "Texas" and r["period_label"] == "2026-09")
    assert texas_row["source_url"] == link


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
# National Honey Report - MyMarketNews file repository (issues ESMIS no longer files)
# =============================================================================================


def test_parse_mmn_filerepo_real_listing():
    """The real listing: 50 rows a page, newest first, links relative to /filerepo/reports."""
    docs, more = parse_mmn_filerepo(fx("real_mmn_filerepo_2901_page0.html").decode(),
                                    base_url=usda.MMN_FILEREPO_URL + "?field_slug_id_value=2901")
    assert more is True and len(docs) == 50 == len({d.url for d in docs})
    assert docs[0] == MmnDocument(date(2026, 10, 30), 1362397, MMN_FILES["2026-10-30"][0])
    assert docs[-1].report_date == date(2023, 7, 26) and docs[-1].url.endswith("/1027770/ams_2901_00045_01.pdf")
    assert {url for url, _ in MMN_FILES.values()} <= {d.url for d in docs}
    assert [d.report_date for d in docs] == sorted((d.report_date for d in docs), reverse=True)
    older, more = parse_mmn_filerepo(fx("real_mmn_filerepo_2901_page1.html").decode(), page=1)
    assert more is True and len(older) == 50                      # the pager links to page 3 (page=2)
    assert (older[0].report_date, older[-1].report_date) == (date(2023, 6, 27), date(2019, 7, 29))
    # only PDF links of slug 2901 count; absolute links too; no pager link past this page
    snippet = ('<a href="https://mymarketnews.ams.usda.gov/filerepo/sites/default/files/2901/2018-02-26/686229/'
               'FV20180226MHONEY.PDF">x</a><a href="sites/default/files/3357/2026-10-30/1/ams_3357_00001.pdf">y</a>'
               '<a href="?field_slug_id_value=2901&amp;page=0">1</a>')
    docs, more = parse_mmn_filerepo(snippet)
    assert [(d.report_date, d.node_id) for d in docs] == [(date(2018, 2, 26), 686229)] and more is False
    assert parse_mmn_filerepo("<html>maintenance</html>") == ([], False)


def test_months_back_and_gap_text():
    assert usda.months_back(2026, 1, 1) == (2025, 12) and usda.months_back(2026, 9, 23) == (2024, 10)
    assert usda._months_text(["2026-02", "2025-09", "2025-10", "2025-11", "2025-12", "2026-01", "2026-04"]) == \
        "2025-09..2026-02, 2026-04 (7 months)"


ESMIS_MARCH_ONLY = {usda.ESMIS_FVMHONEY_URL: (200, esmis_listing(("2025-03-28",)), "application/json")}


def test_honey_report_fills_the_esmis_gap_from_mymarketnews(run_with_routes, session_factory):
    """ESMIS lists only the March 2025 issue, the AMS URL serves October 2026: the issues in between
    come from MyMarketNews (real listing rows, real issues), once each, through the same parser."""
    res = run_with_routes("usda_honey_report", {**honey_routes(**ESMIS_MARCH_ONLY, **{MMN_PAGE0: None}),
                                                **mmn_routes()})
    assert res["status"] == "partial", res
    warnings = "\n".join(res["warnings"])
    assert "not processed" not in warnings and "unavailable" not in warnings, warnings   # nothing on file re-fetched
    assert (f"MyMarketNews document {MMN_FILES['2025-05-15'][0]} is listed under slug 2901 but not a National "
            "Honey Report (page 1 starts with 'TOMATO  FAX  REPORT'); ignored") in warnings
    assert ("No issue on file for market month(s) 2024-10, 2024-12..2025-01, 2025-03..2025-08, 2025-10..2026-07 "
            "(19 months)") in warnings
    with session_factory() as s:
        src = one(s, Source, Source.key == "usda_honey_report")
        reports = {r.report_key: r for r in s.scalars(select(Report).where(Report.source_id == src.id))}
        assert {k: (r.period_label, r.published_at.isoformat()) for k, r in reports.items()} == {
            "2024-12-26": ("2024-11", "2024-12-26"), "2025-03-28": ("2025-02", "2025-03-28"),
            "2025-11-12": ("2025-09", "2025-10-31"),        # listed Nov 12 (after the shutdown), printed Oct 31
            "2026-09-30": ("2026-08", "2026-09-30"), "2026-10-30": ("2026-09", "2026-10-30")}
        assert reports["2025-11-12"].title == "National Honey Report – October 31, 2025 (corrected copy)"
        assert reports["2025-11-12"].url == MMN_FILES["2025-11-12"][0] and reports["2025-11-12"].raw_document_id
        assert reports["2025-03-28"].url == ESMIS_FILES["2025-03-28"][0]        # ESMIS's copy kept, not doubled
        state = s.get(AppSetting, "collector_state:usda_honey_report").value
        assert MMN_FILES["2025-05-15"][0] in state["not_fvmhoney"]
        assert state["mmn"]["files"] == {
            MMN_FILES["2024-12-26"][0]: "stored as report 2024-12-26",
            MMN_FILES["2025-11-12"][0]: "stored as report 2025-11-12",
            MMN_FILES["2026-09-30"][0]: "stored as report 2026-09-30",
            MMN_FILES["2026-10-23"][0]: "same file as report 2026-09-30",
        }
        assert len(state["mmn"]["missing"]) == 19 and state["mmn"]["checked"] == date.today().isoformat()

        P = PriceObservation
        current = P.is_current.is_(True)
        oct25 = s.scalars(select(P).where(P.raw_document_id == reports["2025-11-12"].raw_document_id)).all()
        assert len(oct25) == 62 + 9     # 50 beekeeper + 12 importer prices, 9 ACE unit values (Uruguay: no value)
        assert {(p.published_at, p.source_url, p.is_current) for p in oct25} == {
            (date(2025, 10, 31), MMN_FILES["2025-11-12"][0], True)}
        assert {(p.period_label, p.extra["corrected_copy"]) for p in oct25 if p.price_type != "import_unit_value"} \
            == {("2025-09", True)}
        arg = one(s, P, P.period_label == "2025-09", P.origin_iso3 == "ARG", P.price_type == "wholesale_bulk",
                  P.color_grade == "white")
        assert (arg.price_low, arg.price_high, arg.price_value, arg.unit) == (1.46, 1.49, 1.475, "lb")
        avocado = one(s, P, P.period_label == "2025-09", P.variety_raw == "Avocado")
        assert (avocado.origin_label, avocado.price_type, avocado.price_value) == ("California", "producer", 2.00)
        ace = one(s, P, P.price_type == "import_unit_value", P.origin_iso3 == "IND", P.period_label == "2025-09")
        assert ace.price_value == round(7787355 / 4036106, 4) and ace.extra["hts_code"] == "0409000045"
        sep26 = s.scalars(select(P).where(current, P.raw_document_id == reports["2026-09-30"].raw_document_id)).all()
        assert len(sep26) == 66 + 11 and {p.published_at for p in sep26} == {date(2026, 9, 30)}
        assert count(s, P, current, P.period_label == "2026-08", P.price_type != "import_unit_value") == 66
        dec = s.scalars(select(P).where(current, P.raw_document_id == reports["2024-12-26"].raw_document_id)).all()
        assert dec and {p.source_url for p in dec} == {MMN_FILES["2024-12-26"][0]}
        georgia = one(s, P, P.period_label == "2024-11", P.origin_label == "Georgia")   # printed "GEORIGA"
        assert georgia.extra["label_as_printed"] == "GEORIGA"
        # the March 2025 issue exactly once, although MyMarketNews lists it as well
        assert count(s, P, P.published_at == date(2025, 3, 28)) == 33 + 12
        n = (count(s, P), count(s, Report), count(s, RawDocument))

    # same day again: MyMarketNews is not asked twice a day (its routes are gone: a request would fail)
    res2 = run_with_routes("usda_honey_report", honey_routes(**ESMIS_MARCH_ONLY, **{MMN_PAGE0: None}))
    assert res2["status"] == "no_change", res2
    with session_factory() as s:
        assert (count(s, PriceObservation), count(s, Report), count(s, RawDocument)) == n


def test_mymarketnews_reupload_of_a_stored_issue_is_not_stored_twice(run_with_routes, session_factory):
    """A re-upload whose bytes differ (here: a trailing PDF comment) is recognised by the issue date
    printed in it; a corrected copy would be stored (and supersede), a plain copy is not."""
    routes = {
        **honey_routes(**ESMIS_MARCH_ONLY, **{MMN_PAGE0: None}),
        **mmn_routes(dates=("2026-09-30",), **{
            MMN_PAGE0: (200, mmn_listing(("2026-09-30", "2026-10-23", "2026-10-30"), next_page=False), "text/html"),
            MMN_FILES["2026-10-23"][0]: (200, fx(SEPTEMBER_2026) + b"\n% re-uploaded\n", "application/pdf")})}
    res = run_with_routes("usda_honey_report", routes)
    assert (f"MyMarketNews document {MMN_FILES['2026-10-23'][0]} is the issue of 2026-09-30, already on file "
            "(report 2026-09-30); not stored twice") in res["warnings"]
    with session_factory() as s:
        assert sorted(r.report_key for r in s.scalars(select(Report))) == ["2025-03-28", "2026-09-30", "2026-10-30"]
        files = s.get(AppSetting, "collector_state:usda_honey_report").value["mmn"]["files"]
        assert files[MMN_FILES["2026-10-23"][0]] == "duplicate of report 2026-09-30"
        assert count(s, PriceObservation, PriceObservation.published_at == date(2026, 9, 30)) == 66 + 11
        n = (count(s, PriceObservation), count(s, Report), count(s, RawDocument))

    # a forced run re-reads every listed document and re-stores the stored ones: nothing doubles
    res = run_with_routes("usda_honey_report", routes, force=True)
    assert res["status"] in ("partial", "success"), res
    with session_factory() as s:
        assert (count(s, PriceObservation), count(s, Report), count(s, RawDocument)) == n
        files = s.get(AppSetting, "collector_state:usda_honey_report").value["mmn"]["files"]
        assert files[MMN_FILES["2026-09-30"][0]] == "stored as report 2026-09-30"


def _set_mmn_state(session_factory, **values) -> None:
    with session_factory() as s:
        row = s.get(AppSetting, "collector_state:usda_honey_report")
        state = json.loads(json.dumps(row.value))
        state.setdefault("mmn", {}).update(values)
        row.value = state
        s.commit()


def test_mymarketnews_is_read_only_while_a_hole_is_new_or_once_a_month(run_with_routes, session_factory):
    without_mmn = honey_routes(**ESMIS_MARCH_ONLY, **{MMN_PAGE0: None})
    assert run_with_routes("usda_honey_report", {**without_mmn, **mmn_routes()})["status"] == "partial"
    yesterday = date.fromordinal(date.today().toordinal() - 1).isoformat()

    # next day, same hole, looked up yesterday: the listing is not read (a request would fail: no route)
    _set_mmn_state(session_factory, attempted=yesterday)
    res = run_with_routes("usda_honey_report", without_mmn)
    assert res["status"] == "no_change", res

    # a month later the same hole is looked up again: the listing only, every listed file is known
    month_ago = date.fromordinal(date.today().toordinal() - usda.MMN_RECHECK_DAYS).isoformat()
    _set_mmn_state(session_factory, attempted=yesterday, checked=month_ago)
    res = run_with_routes("usda_honey_report", {**without_mmn, **mmn_routes(files=False)})
    warnings = "\n".join(res["warnings"])
    assert "No issue on file for market month(s)" in warnings and "not processed" not in warnings, warnings
    with session_factory() as s:
        state = s.get(AppSetting, "collector_state:usda_honey_report").value
        assert state["mmn"]["checked"] == state["mmn"]["attempted"] == date.today().isoformat()

    # a new hole (the newest issue is lost: the AMS URL moved on unseen) is looked up the next day
    _set_mmn_state(session_factory, attempted=yesterday, missing=["2024-10"])
    res = run_with_routes("usda_honey_report", {**without_mmn, **mmn_routes(files=False)})
    assert any("No issue on file for market month(s)" in w for w in res["warnings"]), res


def test_mymarketnews_is_not_read_when_no_month_is_missing(run_with_routes, monkeypatch, session_factory):
    monkeypatch.setattr(usda, "MMN_GAP_MONTHS", 1)          # only the newest market month is checked
    routes = honey_routes(**{MMN_PAGE0: None})
    res = run_with_routes("usda_honey_report", routes)
    assert not [w for w in res["warnings"] if "MyMarketNews" in w or "No issue on file" in w], res["warnings"]
    with session_factory() as s:
        assert "mmn" not in s.get(AppSetting, "collector_state:usda_honey_report").value


def test_mymarketnews_unreachable_keeps_the_gap_and_says_so(db, monkeypatch, session_factory):
    """The host accepts the connection and closes it without an answer (seen from the development
    network): the run goes on with ESMIS and the AMS issue, reports the months still missing, and
    does not try again before the next day."""
    from paladex.collectors import base, runner
    from paladex.collectors.runner import run_collector

    monkeypatch.setattr(base.time, "sleep", lambda *_: None)
    monkeypatch.setattr(runner, "is_online", lambda *a, **k: True)

    def run() -> tuple[dict, respx.MockRouter]:
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__regex=MMN_PAGE0).mock(
                side_effect=httpx.RemoteProtocolError("Server disconnected without sending a response."))
            for url, (status, body, ctype) in honey_routes(**{MMN_PAGE0: None}).items():
                mock.get(url__startswith=url).mock(return_value=httpx.Response(
                    status, content=body, headers={"content-type": ctype}))
            mock.route().mock(side_effect=httpx.ConnectError("blocked in tests"))
            with httpx.Client(follow_redirects=True) as client:
                return run_collector("usda_honey_report", trigger="test", client=client), mock

    res, mock = run()
    assert res["status"] == "partial", res
    gap = [w for w in res["warnings"] if w.startswith("MyMarketNews archive unavailable")]
    assert gap == [("MyMarketNews archive unavailable (mymarketnews.ams.usda.gov: RemoteProtocolError Server "
                    "disconnected without sending a response.); market months still without an issue: "
                    "2024-10..2025-01, 2025-04, 2025-07..2026-08 (19 months)")], res["warnings"]
    with session_factory() as s:
        assert sorted(r.report_key for r in s.scalars(select(Report))) == [
            "2025-03-28", "2025-04-30", "2025-07-01", "2025-07-02", "2026-10-30"]
        assert s.get(AppSetting, "collector_state:usda_honey_report").value["mmn"] == {
            "attempted": date.today().isoformat()}
    res2, mock2 = run()
    assert res2["status"] == "no_change", res2
    assert not any("mymarketnews" in str(c.request.url) for c in mock2.calls)


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
