"""Rebuild the generated EU fixtures (Comext JSON-stat vintages and DG AGRI PDFs).

    cd backend && python tests/fixtures/eu/build_fixtures.py

Everything produced here is RECONSTRUCTED test data (see README.md): the JSON-stat
*structure* follows a real DS-045409 response; all numbers and the PDF texts are
illustrative and must never be read as market data.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent

# ---------------------------------------------------------------------------
# Comext DS-045409 JSON-stat
# ---------------------------------------------------------------------------

REPORTERS = {"DE": "Germany (incl. German Democratic Republic 'DD' from 1991)",
             "EU27_2020": "European Union - 27 countries (from 2020)", "IT": "Italy"}
PARTNERS = {"AR": "Argentina", "CN": "China", "EXT_EU27_2020": "Extra-EU27 (from 2020)", "UA": "Ukraine",
            "WORLD": "All countries of the world", "XS": "Serbia"}
INDICATORS = ["VALUE_IN_EUROS", "QUANTITY_IN_100KG"]   # same (non-alphabetical) order as the real capture

# (reporter, partner, flow) -> (quantity in 100 kg per month, EUR/kg), illustrative magnitudes
BASE = {
    ("EU27_2020", "CN", "1"): (48_000, 1.85), ("EU27_2020", "UA", "1"): (52_000, 2.45),
    ("EU27_2020", "AR", "1"): (14_000, 2.95), ("EU27_2020", "XS", "1"): (900, 5.40),
    ("EU27_2020", "EXT_EU27_2020", "1"): (150_000, 2.40), ("EU27_2020", "WORLD", "1"): (290_000, 3.10),
    ("EU27_2020", "EXT_EU27_2020", "2"): (25_000, 5.70), ("EU27_2020", "WORLD", "2"): (160_000, 3.90),
    ("EU27_2020", "CN", "2"): (300, 6.20),
    ("IT", "CN", "1"): (2_500, 1.90), ("IT", "UA", "1"): (4_000, 2.50), ("IT", "AR", "1"): (3_000, 3.00),
    ("IT", "XS", "1"): (4, 6.00), ("IT", "EXT_EU27_2020", "1"): (15_000, 2.60), ("IT", "WORLD", "1"): (32_000, 3.30),
    ("IT", "EXT_EU27_2020", "2"): (1_800, 7.50), ("IT", "WORLD", "2"): (6_500, 5.90),
    ("DE", "CN", "1"): (9_000, 1.80), ("DE", "UA", "1"): (14_000, 2.40), ("DE", "AR", "1"): (6_000, 2.90),
    ("DE", "XS", "1"): (120, 5.30), ("DE", "EXT_EU27_2020", "1"): (40_000, 2.35), ("DE", "WORLD", "1"): (70_000, 2.80),
    ("DE", "EXT_EU27_2020", "2"): (6_000, 6.10), ("DE", "WORLD", "2"): (24_000, 4.40),
}


def _cells(months_with_data: list[str], overrides: dict) -> dict:
    out = {}
    for (rep, par, flow), (q, uv) in BASE.items():
        for i, period in enumerate(months_with_data):
            if (rep, par, flow) == ("IT", "XS", "1") and period == "2026-04":
                continue                                         # a sparse hole: no trade that month
            qty = round(q * (1 + 0.03 * ((i * 3 + len(par)) % 7 - 3)))
            val = round(qty * 100 * uv * (1 + 0.01 * ((i * 7 + len(rep)) % 5 - 2)))
            out[(rep, par, flow, period)] = {"VALUE_IN_EUROS": val, "QUANTITY_IN_100KG": qty}
    # DE exports to Serbia: value published without a quantity (weight unknown -> no unit value)
    for period in months_with_data:
        out[("DE", "XS", "2", period)] = {"VALUE_IN_EUROS": 12_000}
    for key, vals in overrides.items():
        out[key] = vals
    return out


def jsonstat(updated: str, times: list[str], no_data_times: list[str], cells: dict, *,
             reporters=REPORTERS, partners=PARTNERS, flows=("1", "2"), indicators=INDICATORS) -> dict:
    dims = {
        "freq": {"M": "Monthly"}, "reporter": reporters, "partner": partners,
        "product": {"04090000": "Natural honey"}, "flow": {f: {"1": "IMPORT", "2": "EXPORT"}[f] for f in flows},
        "indicators": {i: i for i in indicators}, "time": {t: t for t in times},
    }
    ids = ["freq", "reporter", "partner", "product", "flow", "indicators", "time"]
    codes = {d: list(dims[d]) for d in ids}
    size = [len(codes[d]) for d in ids]
    values = {}
    for (rep, par, flow, period), inds in cells.items():
        if rep not in codes["reporter"] or par not in codes["partner"] or flow not in codes["flow"]:
            continue
        for ind, v in inds.items():
            if ind not in codes["indicators"]:
                continue
            pos = [0, codes["reporter"].index(rep), codes["partner"].index(par), 0, codes["flow"].index(flow),
                   codes["indicators"].index(ind), codes["time"].index(period)]
            flat = 0
            for p, s in zip(pos, size, strict=True):
                flat = flat * s + p
            values[str(flat)] = float(v) if ind == "VALUE_IN_EUROS" else v
    # Eurostat emits the sparse dict in no particular order: shuffle deterministically.
    values = dict(sorted(values.items(), key=lambda kv: (int(kv[0]) * 7919) % 1009))
    return {
        "version": "2.0", "class": "dataset", "label": "EU trade since 1988 by HS2-4-6 and CN8", "source": "ESTAT",
        "updated": updated, "value": values,
        "id": ids, "size": size,
        "dimension": {
            d: {"label": {"freq": "Frequency", "time": "TIME_PERIOD"}.get(d, d.upper()),
                "category": {"index": {c: i for i, c in enumerate(codes[d])}, "label": dims[d]}}
            for d in ids
        },
        "extension": {
            "lang": "EN", "id": "DS-045409", "agencyId": "ESTAT", "version": "1.0",
            "datastructure": {"id": "DS-045409", "agencyId": "ESTAT", "version": "6.6"},
            "annotation": [
                {"type": "DISSEMINATION_OBJECT_TYPE", "title": "DATASET"},
                {"type": "DISSEMINATION_TIMESTAMP_DATA", "date": updated},
                {"type": "ESMS_HTML", "title": "Explanatory texts (metadata)",
                 "href": "https://ec.europa.eu/eurostat/cache/metadata/en/ext_go_detail_sims.htm"},
                {"type": "UPDATE_DATA", "date": updated},
            ],
            "positions-with-no-data": {
                "freq": [], "reporter": [], "partner": [], "product": [], "flow": [], "indicators": [],
                "time": [codes["time"].index(t) for t in no_data_times],
            },
        },
    }


def build_comext() -> None:
    # Vintage 1: released 2026-10-16, data up to 2026-08; 2026-09 and 2026-10 are empty.
    times_v1 = [f"2026-{m:02d}" for m in range(3, 11)]
    v1 = jsonstat("2026-10-16T11:00:00+0200", times_v1, ["2026-09", "2026-10"], _cells(times_v1[:6], {
        ("EU27_2020", "CN", "1", "2026-08"): {"VALUE_IN_EUROS": 9_250_000, "QUANTITY_IN_100KG": 50_000},  # 1.85 EUR/kg
        ("EU27_2020", "XS", "1", "2026-08"): {"VALUE_IN_EUROS": 486_000, "QUANTITY_IN_100KG": 900},       # 5.40 EUR/kg
        ("IT", "XS", "1", "2026-08"): {"VALUE_IN_EUROS": 2_400, "QUANTITY_IN_100KG": 4},                  # 400 kg: tiny
    }))
    # Vintage 2: released 2026-11-13; adds 2026-09 and revises EU27 imports from China for 2026-08.
    times_v2 = [f"2026-{m:02d}" for m in range(3, 12)]
    v2 = jsonstat("2026-11-13T11:00:00+0100", times_v2, ["2026-10", "2026-11"], _cells(times_v2[:7], {
        ("EU27_2020", "CN", "1", "2026-08"): {"VALUE_IN_EUROS": 9_500_000, "QUANTITY_IN_100KG": 50_000},  # revised: 1.90
        ("EU27_2020", "XS", "1", "2026-08"): {"VALUE_IN_EUROS": 486_000, "QUANTITY_IN_100KG": 900},
        ("IT", "XS", "1", "2026-08"): {"VALUE_IN_EUROS": 2_400, "QUANTITY_IN_100KG": 4},
    }))
    (HERE / "comext_honey_2026-10-16.json").write_text(json.dumps(v1, indent=1))
    (HERE / "comext_honey_2026-11-13.json").write_text(json.dumps(v2, indent=1))
    # The cheap vintage probes: EU27 x extra-EU imports, value only.
    for name, upd, times, nod in (("comext_probe_2026-10-16.json", "2026-10-16T11:00:00+0200",
                                   ["2026-08", "2026-09", "2026-10", "2026-11"], ["2026-09", "2026-10", "2026-11"]),
                                  ("comext_probe_2026-11-13.json", "2026-11-13T11:00:00+0100",
                                   ["2026-08", "2026-09", "2026-10", "2026-11"], ["2026-10", "2026-11"])):
        cells = {("EU27_2020", "EXT_EU27_2020", "1", t): {"VALUE_IN_EUROS": 36_000_000 + i}
                 for i, t in enumerate(times) if t not in nod}
        doc = jsonstat(upd, times, nod, cells, reporters={"EU27_2020": REPORTERS["EU27_2020"]},
                       partners={"EXT_EU27_2020": PARTNERS["EXT_EU27_2020"]}, flows=("1",), indicators=["VALUE_IN_EUROS"])
        (HERE / name).write_text(json.dumps(doc, indent=1))


# ---------------------------------------------------------------------------
# Minimal PDF writer (text + ruled tables, standard Helvetica, no dependencies)
# ---------------------------------------------------------------------------


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def text(x: float, y: float, s: str, size: int = 12) -> str:
    return f"BT /F1 {size} Tf {x} {y} Td ({_esc(s)}) Tj ET\n"


def lines(x: float, y: float, rows: list[str], size: int = 11, leading: int = 16) -> str:
    return "".join(text(x, y - i * leading, r, size) for i, r in enumerate(rows))


def table(x0: float, y_top: float, col_widths: list[int], rows: list[list[str]], row_h: int = 20, size: int = 10) -> str:
    xs = [x0]
    for w in col_widths:
        xs.append(xs[-1] + w)
    y_bottom = y_top - row_h * len(rows)
    out = "0.6 w\n"
    for r in range(len(rows) + 1):
        y = y_top - r * row_h
        out += f"{x0} {y} m {xs[-1]} {y} l S\n"
    for x in xs:
        out += f"{x} {y_top} m {x} {y_bottom} l S\n"
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            out += text(xs[c] + 5, y_top - (r + 1) * row_h + 6, cell, size)
    return out


def build_pdf(pages: list[str], title: str) -> bytes:
    n = len(pages)
    page_ids = [4 + 2 * i for i in range(n)]
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: f"<< /Type /Pages /Kids [{' '.join(f'{p} 0 R' for p in page_ids)}] /Count {n} >>".encode(),
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    }
    for i, stream in enumerate(pages):
        pid, cid = page_ids[i], page_ids[i] + 1
        objects[pid] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 842 595] "
                        f"/Resources << /Font << /F1 3 0 R >> >> /Contents {cid} 0 R >>").encode()
        data = stream.encode("latin-1")
        objects[cid] = f"<< /Length {len(data)} >>\nstream\n".encode() + data + b"\nendstream"
    info_id = max(objects) + 1
    objects[info_id] = f"<< /Title ({_esc(title)}) /Producer (Paladex test fixture builder) >>".encode()
    out = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    offsets = {}
    for oid in sorted(objects):
        offsets[oid] = len(out)
        out += f"{oid} 0 obj\n".encode() + objects[oid] + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {info_id + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{offsets[i]:010d} 00000 n \n" for i in range(1, info_id + 1)).encode()
    out += f"trailer\n<< /Size {info_id + 1} /Root 1 0 R /Info {info_id} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


FIXTURE_LINE = "[RECONSTRUCTED TEST FIXTURE - illustrative text and numbers, not real data]"


def build_pdfs() -> None:
    overview = [
        text(60, 520, "Honey market overview", 24)
        + text(60, 490, "January 2026", 14)
        + lines(60, 450, [
            "European Commission - Directorate-General for Agriculture and Rural Development",
            FIXTURE_LINE,
            "Market situation: EU production recovered in 2025 after two weak seasons.",
            "Imports from Ukraine and China remain the main supply of bulk honey to EU packers.",
            "Import prices stayed under pressure in the second half of 2025.",
        ]),
        # Page 2: one unambiguous table (single price type, single unit, year columns).
        text(60, 540, "Honey prices at production site - multifloral honey (EUR/kg)", 16)
        + text(60, 515, "Source: Member States notifications under Reg. (EU) 2022/1475", 10)
        + table(60, 490, [160, 90, 90], [
            ["Member State", "2023", "2024"],
            ["Italy", "6,10", "6,40"],
            ["Spain", "3,95", "4,20"],
            ["Hungary", "3,40", "3,55"],
            ["Romania", "-", "3,30"],
            ["EU", "5,98", "6,05"],
        ]),
        # Page 3: numbers only in free text (chart commentary) -> must NOT become prices.
        text(60, 540, "EU imports by origin - Source: Eurostat COMEXT", 16)
        + lines(60, 500, [
            "Import unit value by origin (EUR/kg): China 1.85 EUR/kg, Ukraine 2.45 EUR/kg,",
            "Argentina 2.95 EUR/kg. Volumes are shown in the chart below.",
            FIXTURE_LINE,
        ]),
        # Page 4: ambiguous - one table under a title naming two price types.
        text(60, 540, "Honey prices: production site and bulk to wholesalers (EUR/kg)", 16)
        + table(60, 500, [160, 90, 90], [
            ["Member State", "2023", "2024"],
            ["Italy", "6,10", "3,90"],
            ["Spain", "3,95", "2,80"],
        ]),
    ]
    autumn = [
        text(60, 520, "Market presentation - Honey", 24)
        + text(60, 490, "Civil Dialogue Group Animal Products - autumn 2024", 14)
        + lines(60, 450, [FIXTURE_LINE, "EU self-sufficiency in honey is estimated at around 60 percent.",
                          "Charts: production by Member State, beehives, imports and exports."]),
        text(60, 540, "EU imports by origin (t) - Source: Eurostat COMEXT", 16)
        + lines(60, 500, ["Chart only. No tabular data on this page.", FIXTURE_LINE]),
    ]
    (HERE / "honey-market-overview-january-2026_en.pdf").write_bytes(build_pdf(overview, "Honey market overview"))
    (HERE / "market-presentation-honey_autumn2024_en.pdf").write_bytes(build_pdf(autumn, "Market presentation honey"))


if __name__ == "__main__":
    build_comext()
    build_pdfs()
    print("fixtures written to", HERE)
