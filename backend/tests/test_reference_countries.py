"""Country reference table (paladex/reference/countries.py) checked against real source data.

Fixtures in tests/fixtures/reference/ are live captures of 4 November 2026 (see the README there).
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from paladex.collectors.eu import map_geo, parse_rasff_search
from paladex.reference.countries import countries, country_name, lookup_fao, lookup_iso3

FIX = Path(__file__).parent / "fixtures" / "reference"

# Origins that honey sources (RASFF, FAOSTAT, Comtrade, the EU third-country list) name and that
# were missing from the table before the first live run.
ADDED = {
    "NPL": ("NP", 524, 149), "SYR": ("SY", 760, 212), "BGD": ("BD", 50, 16), "LKA": ("LK", 144, 38),
    "ZMB": ("ZM", 894, 251), "CMR": ("CM", 120, 32), "MDG": ("MG", 450, 129), "HND": ("HN", 340, 95),
    "DOM": ("DO", 214, 56), "GEO": ("GE", 268, 73), "ARM": ("AM", 51, 1), "AZE": ("AZ", 31, 52),
    "UZB": ("UZ", 860, 235), "MNG": ("MN", 496, 141), "LAO": ("LA", 418, 120), "KHM": ("KH", 116, 115),
    "SGP": ("SG", 702, 200),
}


def _faostat_areas() -> dict[int, tuple[int, str]]:
    with (FIX / "faostat_areas.csv").open(encoding="utf-8") as fh:
        return {int(r["Area Code"]): (int(r["Area Code (M49)"].lstrip("'")), r["Area"])
                for r in csv.DictReader(fh) if r["Area Code (M49)"].lstrip("'").isdigit()}


def test_codes_are_unique_and_well_formed():
    cs = countries()
    for key in ("iso3", "iso2", "m49"):
        values = [c[key] for c in cs]
        assert len(values) == len(set(values)), key
    assert len([c["fao_code"] for c in cs if c["fao_code"]]) == len({c["fao_code"] for c in cs if c["fao_code"]})
    for c in cs:
        assert len(c["iso3"]) == 3 and c["iso3"].isupper() and len(c["iso2"]) == 2 and c["iso2"].isupper()
        assert c["name_en"] and c["name_it"]
    curated = [c for c in cs if c["region"] is not None]     # the rest: ISO list, no coordinates/profile
    assert len(cs) >= 249 and len(curated) >= 100
    for c in curated:
        assert -90 <= c["lat"] <= 90 and -180 <= c["lon"] <= 180
    assert {c["region"] for c in curated} == {"South America", "North America", "Central America & Caribbean", "Europe",
                                         "Middle East", "Asia", "Africa", "Oceania"}


def test_every_fao_code_matches_faostat():
    """Each FAO area code in the table is the one FAOSTAT itself uses for that M49 code."""
    areas = _faostat_areas()
    for c in countries():
        if c["fao_code"] is None:
            continue
        assert c["fao_code"] in areas, c["iso3"]
        assert areas[c["fao_code"]][0] == c["m49"], (c["iso3"], c["fao_code"], areas[c["fao_code"]])


@pytest.mark.parametrize("iso3", sorted(ADDED))
def test_added_countries(iso3):
    iso2, m49, fao = ADDED[iso3]
    c = next(x for x in countries() if x["iso3"] == iso3)
    assert (c["iso2"], c["m49"], c["fao_code"]) == (iso2, m49, fao)
    assert lookup_iso3(iso2) == lookup_iso3(m49) == lookup_iso3(iso3) == lookup_fao(fao) == iso3
    assert lookup_iso3(c["name_en"]) == lookup_iso3(c["name_it"]) == iso3
    assert map_geo(iso2) == iso3                       # Comext / RASFF ISO2 codes


def test_official_long_names():
    areas = _faostat_areas()
    # FAOSTAT / Comtrade spellings
    assert lookup_iso3(areas[212][1]) == "SYR"         # "Syrian Arab Republic"
    assert lookup_iso3(areas[120][1]) == "LAO"         # "Lao People's Democratic Republic"
    assert lookup_iso3(areas[250][1]) == "COD"         # "Democratic Republic of the Congo"
    assert lookup_iso3(areas[236][1]) == "VEN"         # "Venezuela (Bolivarian Republic of)"
    assert lookup_iso3("Dominican Rep.") == "DOM" and lookup_iso3("Lao People's Dem. Rep.") == "LAO"
    assert country_name("SYR") == "Siria" and country_name("KHM", "en") == "Cambodia"
    assert country_name("GEO") == "Georgia" and country_name("AZE") == "Azerbaigian"


def test_real_rasff_origins_are_mapped():
    page = parse_rasff_search((FIX / "real_rasff_origins.json").read_bytes())
    assert not page.problems
    by_ref = {n.reference: n for n in page.notifications}
    assert by_ref["2026.8785"].subject == "Grayanotoxin in honey from Nepal, via the Netherlands"
    assert by_ref["2026.8785"].origin_iso3 == ["NPL"] and by_ref["2026.8785"].origin_names == ["Nepal"]
    assert by_ref["2026.4893"].origin_iso3 == ["SYR"]  # "... honey product from the Syrian Arab Republic"
    assert by_ref["2024.3224"].origin_iso3 == ["SGP"]
    assert all(n.origin_iso3 for n in page.notifications)          # no origin left unmapped
    assert sorted({i for n in page.notifications for i in n.origin_iso3}) == ["CHN", "DEU", "NPL", "SGP", "SYR", "TUR"]
    assert by_ref["2025.7911"].origin_iso3 == ["DEU", "TUR"]       # two origins, both kept
    raw = json.loads((FIX / "real_rasff_origins.json").read_text(encoding="utf-8"))
    assert len(raw["notifications"]) == len(page.notifications) == 8
