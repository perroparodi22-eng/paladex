"""Regenerate the RECONSTRUCTED fixtures of tests/test_trade_official.py.

    cd backend && python tests/fixtures/trade_official/build_fixtures.py

Every number is illustrative test data, not market data. See README.md for what each file
reconstructs and from which documentation.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent


def write(name: str, obj) -> None:
    (HERE / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def write_rows(name: str, rows: list) -> None:
    """Census layout: a JSON array of compact arrays, one per line, header first."""
    body = ",\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in rows)
    (HERE / name).write_text(f"[{body}]", encoding="utf-8")


# ---------------------------------------------------------------------------------------------
# Brazil, Comex Stat (api-comexstat.mdic.gov.br)
# ---------------------------------------------------------------------------------------------

def comex_envelope(data, language="en"):
    return {"data": data, "success": True, "message": None, "processo_info": None, "language": language}


def comex_rows(table):
    """table: [(year, month, country, state, fob_usd, kg)]. Numbers alternate between JSON strings
    and numbers (third-party clients report both)."""
    out = []
    for i, (y, m, country, state, fob, kg) in enumerate(table):
        out.append({
            "year": str(y), "monthNumber": str(m), "country": country, "state": state,
            "coNcm": "04090000", "ncm": "Natural honey",
            "metricFOB": str(fob) if i % 2 == 0 else fob, "metricKG": str(kg) if i % 2 == 0 else kg,
        })
    return comex_envelope({"list": out})


COMEX_2026_09 = [
    (2026, 9, "United States", "Piauí", 4_260_000, 1_200_000),
    (2026, 9, "United States", "Ceará", 2_100_000, 600_000),
    (2026, 9, "United States", "Rio Grande do Sul", 1_110_000, 300_000),
    (2026, 9, "Canada", "Paraná", 432_000, 120_000),
    (2026, 9, "Netherlands", "Santa Catarina", 222_000, 60_000),
    (2026, 9, "Singapore", "São Paulo", 9_000, 2_000),
    (2026, 9, "Australia", "São Paulo", 2_100, 300),             # < 1 t: trade row only
]
COMEX_2026_08 = [
    (2026, 8, "United States", "Piauí", 3_850_000, 1_100_000),
    (2026, 8, "United States", "Ceará", 1_725_000, 500_000),
    (2026, 8, "Canada", "Paraná", 355_000, 100_000),
    (2026, 8, "Germany", "Santa Catarina", 72_960, 19_200),
]
COMEX_2026_07 = [(2026, 7, "United States", "Piauí", 3_150_000, 900_000)]
COMEX_EARLIER = [
    (2026, 1, "United States", "Piauí", 3_560_700, 1_000_000),
    (2025, 10, "United States", "Rio Grande do Sul", 850_000, 250_000),
]

# Release of 2026-11-05 (latest month 2026-10): trailing months re-pulled.
COMEX_2026_08_REV = [
    (2026, 8, "United States", "Piauí", 3_905_000, 1_100_000),   # revised FOB
    (2026, 8, "United States", "Ceará", 1_725_000, 500_000),
    (2026, 8, "Canada", "Paraná", 355_000, 100_000),
    (2026, 8, "Germany", "Santa Catarina", 3_040, 800),          # revised below 1 t: unit value withdrawn
]
COMEX_2026_09_REV = [r for r in COMEX_2026_09 if r[2] != "Netherlands"]   # flow withdrawn
COMEX_2026_10 = [
    (2026, 10, "United States", "Piauí", 3_600_000, 1_000_000),
    (2026, 10, "Canada", "Paraná", 324_000, 90_000),
]


def build_comex() -> None:
    write("comex_dates_updated_2026-10-06.json",
          comex_envelope({"updated": "2026-10-06", "year": 2026, "monthNumber": 9}, language="pt"))
    write("comex_dates_updated_2026-11-05.json",
          comex_envelope({"updated": "2026-11-05", "year": 2026, "monthNumber": 10}, language="pt"))
    write("comex_filters.json", comex_envelope({"list": [
        {"filter": f, "text": t} for f, t in (
            ("country", "Countries"), ("economicBlock", "Economic blocks"), ("state", "State of the company"),
            ("via", "Mode of transport"), ("urf", "Customs office"), ("section", "HS section"),
            ("chapter", "HS2"), ("heading", "HS4"), ("subHeading", "HS6"), ("ncm", "NCM 8 digits"),
        )]}))
    write("comex_details.json", comex_envelope({"list": [
        {"detail": d, "text": t} for d, t in (
            ("country", "Countries"), ("economicBlock", "Economic blocks"), ("state", "State of the company"),
            ("via", "Mode of transport"), ("urf", "Customs office"), ("chapter", "HS2"), ("heading", "HS4"),
            ("subHeading", "HS6"), ("ncm", "NCM 8 digits"),
        )]}))
    write("comex_metrics.json", comex_envelope({"list": [
        {"id": "metricFOB", "text": "US$ FOB", "flow": "both"},
        {"id": "metricKG", "text": "Net kilograms", "flow": "both"},
        {"id": "metricStatistic", "text": "Statistical quantity", "flow": "both"},
        {"id": "metricFreight", "text": "Freight US$", "flow": "import"},
        {"id": "metricInsurance", "text": "Insurance US$", "flow": "import"},
        {"id": "metricCIF", "text": "US$ CIF", "flow": "import"},
    ]}))
    write("comex_general_2025-10_2026-09.json",
          comex_rows(COMEX_2026_09 + COMEX_2026_08 + COMEX_2026_07 + COMEX_EARLIER))
    write("comex_general_2024-10_2025-09.json", comex_rows([
        (2025, 3, "United States", "Piauí", 2_480_000, 800_000),
        (2024, 11, "Germany", "Santa Catarina", 115_200, 38_400),
    ]))
    write("comex_general_2023-10_2024-09.json", comex_rows([
        (2024, 2, "United States", "Piauí", 2_030_000, 700_000),
    ]))
    write("comex_general_2026-08_2026-10.json", comex_rows(COMEX_2026_10 + COMEX_2026_09_REV + COMEX_2026_08_REV))
    write("comex_rate_limited.json", {"data": None, "success": False,
                                      "message": "Too many requests. Please try again in 10 seconds.",
                                      "processo_info": None, "language": "en"})


# ---------------------------------------------------------------------------------------------
# United States, Census International Trade API (api.census.gov)
# ---------------------------------------------------------------------------------------------

CENSUS_HEADER = ["CTY_CODE", "CTY_NAME", "I_COMMODITY", "I_COMMODITY_SDESC", "GEN_VAL_MO", "GEN_QY1_MO",
                 "UNIT_QY1", "CON_VAL_MO", "CON_QY1_MO", "GEN_CIF_MO", "CON_CIF_MO", "DUT_VAL_MO", "CAL_DUT_MO",
                 "SUMMARY_LVL", "COMM_LVL", "I_COMMODITY", "time"]

HS6_DESC = "NATURAL HONEY"
HS10_DESC = {
    "0409000005": "NATURAL HONEY, CERTIFIED ORGANIC",
    "0409000035": "NATURAL HONEY, NESOI, WHITE OR LIGHTER",
    "0409000045": "NATURAL HONEY, NESOI, EXTRA LIGHT AMBER",
    "0409000056": "NATURAL HONEY, NESOI, LIGHT AMBER",
}
# (code, name, period, con_kg, con_val): general imports = consumption + a small bonded share,
# CIF = value + 4.5 %, calculated duty = 1.9 cents/kg (illustrative).
CENSUS_COUNTRY_ROWS = {
    "2026-08": [
        ("3570", "ARGENTINA", 4_200_000, 13_650_000), ("3510", "BRAZIL", 2_100_000, 7_455_000),
        ("5330", "INDIA", 3_000_000, 6_600_000), ("5520", "VIETNAM", 2_400_000, 4_800_000),
        ("4623", "UKRAINE", 500_000, 1_250_000), ("2010", "MEXICO", 300_000, 1_050_000),
        ("1220", "CANADA", 900_000, 3_240_000), ("3550", "URUGUAY", 400_000, 1_280_000),
        ("4890", "TURKEY", 600, 4_800), ("6141", "NEW ZEALAND", 50_000, 1_750_000),
        ("5590", "SINGAPORE", 1_500, 9_000),
    ],
    "2026-07": [
        ("3570", "ARGENTINA", 3_800_000, 12_160_000), ("3510", "BRAZIL", 1_900_000, 6_650_000),
        ("5330", "INDIA", 2_800_000, 6_020_000), ("5520", "VIETNAM", 2_000_000, 4_000_000),
        ("4623", "UKRAINE", 450_000, 1_125_000),
    ],
    "2026-01": [("3570", "ARGENTINA", 3_000_000, 9_300_000)],
    "2025-11": [("3570", "ARGENTINA", 2_500_000, 7_625_000)],
    "2025-03": [("3570", "ARGENTINA", 3_500_000, 10_500_000)],
    "2024-02": [("3570", "ARGENTINA", 3_200_000, 9_280_000)],
}
# Next FT-900 release: 2026-07 revised (Argentina value up; India cut below 1 t; Ukraine dropped),
# 2026-08 unchanged, 2026-09 new.
CENSUS_COUNTRY_ROWS_REV = {
    "2026-07": [
        ("3570", "ARGENTINA", 3_800_000, 12_350_000), ("3510", "BRAZIL", 1_900_000, 6_650_000),
        ("5330", "INDIA", 800, 1_760), ("5520", "VIETNAM", 2_000_000, 4_000_000),
    ],
    "2026-08": CENSUS_COUNTRY_ROWS["2026-08"],
    "2026-09": [("3570", "ARGENTINA", 4_000_000, 13_200_000), ("3510", "BRAZIL", 2_000_000, 7_200_000)],
}
OTHER_COUNTRIES_KG, OTHER_COUNTRIES_VAL = 25_000, 90_000      # origins not listed above
GROUPS = [("0003", "EUROPEAN UNION"), ("3XXX", "SOUTH AMERICA"), ("5XXX", "ASIA")]


def census_row(code, name, commodity, desc, kg, val, period, lvl, comm_lvl):
    gen_kg, gen_val = kg + (kg // 100), val + (val // 100)
    return [code, name, commodity, desc, str(gen_val), str(gen_kg), "KG", str(val), str(kg),
            str(round(gen_val * 1.045)), str(round(val * 1.045)), str(val), str(round(kg * 0.019)),
            lvl, comm_lvl, commodity, period]


def census_hs6(rows_by_period: dict, periods: list[str]) -> list:
    out = [CENSUS_HEADER]
    for period in periods:
        rows = rows_by_period.get(period, [])
        if not rows:
            continue
        tot_kg = sum(r[2] for r in rows) + OTHER_COUNTRIES_KG
        tot_val = sum(r[3] for r in rows) + OTHER_COUNTRIES_VAL
        out.append(census_row("-", "TOTAL FOR ALL COUNTRIES", "040900", HS6_DESC, tot_kg, tot_val, period, "DET", "HS6"))
        for code, name in GROUPS:
            out.append(census_row(code, name, "040900", HS6_DESC, tot_kg // 3, tot_val // 3, period, "CGP", "HS6"))
        for code, name, kg, val in rows:
            out.append(census_row(code, name, "040900", HS6_DESC, kg, val, period, "DET", "HS6"))
    return out


def census_hs10(lines: list[tuple]) -> list:
    """lines: [(code, name, hs10, kg, val, period)]"""
    out = [CENSUS_HEADER]
    for code, name, hs10, kg, val, period in lines:
        out.append(census_row(code, name, hs10, HS10_DESC[hs10], kg, val, period, "DET", "HS10"))
    return out


HS10_2026_08 = [
    ("3570", "ARGENTINA", "0409000035", 2_500_000, 8_250_000, "2026-08"),
    ("3570", "ARGENTINA", "0409000045", 1_700_000, 5_400_000, "2026-08"),
    ("3510", "BRAZIL", "0409000005", 1_500_000, 5_400_000, "2026-08"),
    ("3510", "BRAZIL", "0409000056", 600_000, 2_055_000, "2026-08"),
]


def build_census() -> None:
    variables = {
        "CTY_CODE": "Country Code", "CTY_NAME": "Country Name", "I_COMMODITY": "Import Commodity Code",
        "I_COMMODITY_SDESC": "15-character Import Commodity Description",
        "I_COMMODITY_LDESC": "50-character Import Commodity Description",
        "GEN_VAL_MO": "General Imports, Total Value", "GEN_QY1_MO": "General Imports, Quantity 1",
        "GEN_QY2_MO": "General Imports, Quantity 2", "GEN_CIF_MO": "General Imports, CIF Value",
        "GEN_CHA_MO": "General Imports, Charges",
        "CON_VAL_MO": "Imports for Consumption, Total Value", "CON_QY1_MO": "Imports for Consumption, Quantity 1",
        "CON_QY2_MO": "Imports for Consumption, Quantity 2", "CON_CIF_MO": "Imports for Consumption, CIF Value",
        "CON_CHA_MO": "Imports for Consumption, Charges", "DUT_VAL_MO": "Dutiable Value",
        "CAL_DUT_MO": "Calculated Duty", "UNIT_QY1": "Unit of Quantity 1", "UNIT_QY2": "Unit of Quantity 2",
        "COMM_LVL": "4-character aggregation levels for commodity code", "SUMMARY_LVL": "Detail or Country Grouping indicator",
        "YEAR": "Year", "MONTH": "Month", "time": "ISO-8601 Date/Time value",
    }
    write("census_variables.json", {"variables": {
        k: {"label": v, "predicateType": "string" if k != "time" else "datetime", "group": "N/A", "limit": 0}
        for k, v in variables.items()}})
    write_rows("census_hs6_2025-11_2026-10.json", census_hs6(CENSUS_COUNTRY_ROWS, ["2025-11", "2026-01", "2026-07", "2026-08"]))
    write_rows("census_hs6_2024-11_2025-10.json", census_hs6(CENSUS_COUNTRY_ROWS, ["2025-03"]))
    write_rows("census_hs6_2023-11_2024-10.json", census_hs6(CENSUS_COUNTRY_ROWS, ["2024-02"]))
    write_rows("census_hs10_2025-11_2026-10.json", census_hs10(HS10_2026_08 + [
        ("3570", "ARGENTINA", "0409000035", 3_800_000, 12_160_000, "2026-07"),
    ]))
    write_rows("census_hs10_2024-11_2025-10.json", census_hs10([
        ("3570", "ARGENTINA", "0409000035", 3_500_000, 10_500_000, "2025-03")]))
    write_rows("census_hs10_2023-11_2024-10.json", census_hs10([
        ("3570", "ARGENTINA", "0409000035", 3_200_000, 9_280_000, "2024-02")]))
    # Trailing window asked a few days after the backfill, before the next release: same numbers.
    write_rows("census_hs6_2026-06_2026-10.json", census_hs6(CENSUS_COUNTRY_ROWS, ["2026-07", "2026-08"]))
    write_rows("census_hs10_2026-06_2026-10.json", census_hs10(HS10_2026_08 + [
        ("3570", "ARGENTINA", "0409000035", 3_800_000, 12_160_000, "2026-07"),
    ]))
    write_rows("census_hs6_2026-06_2026-11.json", census_hs6(CENSUS_COUNTRY_ROWS_REV, ["2026-07", "2026-08", "2026-09"]))
    write_rows("census_hs10_2026-06_2026-11.json", census_hs10(HS10_2026_08 + [
        ("3570", "ARGENTINA", "0409000035", 3_800_000, 12_350_000, "2026-07"),
        ("3570", "ARGENTINA", "0409000035", 4_000_000, 13_200_000, "2026-09"),
    ]))
    (HERE / "census_invalid_key.html").write_text(
        "<html><head><title>Invalid Key</title></head><body>A valid <em>key</em> must be included with each "
        "data API request. You included a key with this request, however, it is not valid. Please check your "
        "key and try again.<br><br>If you do not have a key you may sign up for one "
        "<a href=\"https://api.census.gov/data/key_signup.html\">here</a>.</body></html>\n", encoding="utf-8")


if __name__ == "__main__":
    build_comex()
    build_census()
    print("fixtures written to", HERE)
