"""Official watchers against REAL captures (live run of 4 November 2026).

Fixtures in tests/fixtures/official_watchers/real/ (see the README there): the DGFT notifications
list (trimmed), two DGFT minimum-export-price notifications (scanned PDFs, no text layer), the
Tesseract OCR text of all five honey notifications at 300 and 400 dpi, the SENASA Plan CREHA page
and the first page of a real "Lista EAR". Every expected value below was read on the official
documents themselves.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from paladex.collectors import official_watchers as ow
from paladex.models import RegulationItem, Source
from paladex.services import ocr

REAL = Path(__file__).parent / "fixtures" / "official_watchers" / "real"
TODAY = date(2026, 11, 4)
PDF = "application/pdf"
DGFT_FILES = r"^https://content\.dgft\.gov\.in/Website/dgftprod/"
EAR_FILES = "https://www.argentina.gob.ar/sites/default/files/"
SENASA_LIST = r"^https://www\.argentina\.gob\.ar/senasa/noticias$"


def rx(name: str) -> bytes:
    return (REAL / name).read_bytes()


@pytest.fixture()
def pin_today(monkeypatch):
    monkeypatch.setattr(ow, "today", lambda: TODAY)


def _items(s, key: str) -> dict[str, RegulationItem]:
    src = s.scalars(select(Source).where(Source.key == key)).one()
    return {r.reference: r for r in s.scalars(select(RegulationItem).where(RegulationItem.source_id == src.id))}


# ===========================================================================
# DGFT: the real notifications list
# ===========================================================================

# (number, date, description start, PDF file name) of the honey rows, in the order of the list.
REAL_HONEY_ROWS = [
    ("09/2026-27", date(2026, 4, 10), "Amendment for extension of validity of Minimum Export Price (MEP) on export "
                                      "of Natural Honey", "Notification NO. 09.pdf"),
    ("52/2025-26", date(2025, 12, 31), "Amendment for extension of validity of Minimum Export Price (MEP) on export "
                                       "of Natural Honey", "Notification 52 (ENG).pdf"),
    ("27/2025-26", date(2025, 8, 22), "Amendment of Minimum Export Price (MEP) on export of Honey - regarding.",
     "Notification English 22.08.2025.pdf"),
    ("45/2024-25", date(2024, 12, 30), "Imposition of Minimum Export Price (MEP) on Export of Honey.",
     "Notification No 45 Eng.pdf"),
    ("75/2023", date(2024, 3, 14), "Imposition of Minimum Export Price (MEP) on export of Honey.",
     "Notification No. 75-2023-english.pdf"),
]


def test_real_dgft_list_rows():
    rows, problems = ow.parse_dgft_notifications(rx("dgft_notifications.html"), ow.DGFT_LIST_URL)
    assert problems == []                       # live run: 10 "notification number not recognised" warnings
    assert len(rows) == 15 and all(r.number for r in rows)
    honey = [r for r in rows if ow.dgft_is_honey(r)]
    assert [(r.number, r.notified_on) for r in honey] == [(n, d) for n, d, _, _ in REAL_HONEY_ROWS]
    for r, (_, _, desc, pdf) in zip(honey, REAL_HONEY_ROWS):
        assert r.description.startswith(desc) and r.pdf_url.endswith(pdf) and not r.corrigendum
        assert r.pdf_url.startswith("https://content.dgft.gov.in/Website/")
    by_raw = {r.number_raw: r for r in rows}
    # bare numbers take the Year column; the FTP 2023 series keeps its form
    assert by_raw["36"].number == "36/2026-27" and by_raw["36"].year == "2026-27"
    assert by_raw["16"].number == "16/2026-27"
    assert by_raw["64"].number == "64/2024-25"
    assert by_raw["57"].number == "57/2023" and by_raw["57"].year == "2023"
    assert by_raw["08/2023"].number == "08/2023" and by_raw["08/2023"].year == "2024-25"
    assert by_raw["75/2023"].reference == "DGFT Notification No. 75/2023"
    # a corrigendum gets its own reference, not that of the notification it corrects
    corr = by_raw["Corrigendum to Notification no. 16/2024.25 dated 06.06.2024"]
    assert corr.corrigendum and corr.number == "16/2024-25" and corr.notified_on == date(2024, 6, 12)
    assert corr.reference == "DGFT Corrigendum of 12.06.2024 to Notification No. 16/2024-25"
    assert len({r.reference for r in rows}) == len(rows)


def test_real_dgft_pdfs_are_scans_without_text():
    for name in ("dgft_notification_75-2023.pdf", "dgft_notification_09-2026-27.pdf"):
        assert rx(name).startswith(b"%PDF") and ow.pdf_text(rx(name)).strip() == ""


# ===========================================================================
# DGFT: minimum export price terms read from the OCR text of the real scans
# ===========================================================================

# Read on the scanned notifications (Effect of this Notification / policy-condition table):
#   75/2023     "MEP of US $ 2000 per Metric Ton (PMT) is imposed till 31st December, 2024";
#               "The Notification will come into immediate effect."; no FOB wording.
#   45/2024-25  "US$ 2000 F.O.B per Metric Ton (PMT), till 31st December, 2025"; "extended beyond 31st
#               December, 2024 till 31st December, 2025"; no effective-date wording.
#   27/2025-26  "revised from US Dollar 2000 Per Metric Ton to US Dollar 1400 per Metric Ton with
#               immediate effect, till 31st December 2025."
#   52/2025-26  "shall remain at US Dollar 1400 FOB per Metric Ton till 31st March 2026, with immediate effect."
#               (the table also prints the superseded "till 31st December 2025")
#   09/2026-27  "MEP of US Dollar 1400 FOB per Metric Ton ... is extended till 31st December 2026."
#               ("as under, with immediate effect" in the operative paragraph)
REAL_TERMS = {
    "75-2023": (date(2024, 3, 14), 2000.0, date(2024, 12, 31), date(2024, 3, 14), None),
    "45-2024-25": (date(2024, 12, 30), 2000.0, date(2025, 12, 31), None, "FOB"),
    "27-2025-26": (date(2025, 8, 22), 1400.0, date(2025, 12, 31), date(2025, 8, 22), "FOB"),
    "52-2025-26": (date(2025, 12, 31), 1400.0, date(2026, 3, 31), date(2025, 12, 31), "FOB"),
    "09-2026-27": (date(2026, 4, 10), 1400.0, date(2026, 12, 31), date(2026, 4, 10), "FOB"),
}


@pytest.mark.parametrize("dpi", [300, 400])
@pytest.mark.parametrize("name", sorted(REAL_TERMS))
def test_real_mep_terms_from_ocr_text(name, dpi):
    notified, mep, until, effective, basis = REAL_TERMS[name]
    text = (REAL / "ocr" / f"dgft_notification_{name}_{dpi}dpi.txt").read_text(encoding="utf-8")
    terms = ow.parse_mep_terms(text, notified, ocr=True)
    assert (terms.mep_usd_per_t, terms.valid_until, terms.effective_date, terms.basis) == (mep, until, effective,
                                                                                           basis)
    assert terms.problems == []
    if effective is not None:
        assert terms.effective_basis == "with immediate effect (notification date)"


def test_real_ocr_text_needs_the_ocr_normalisation():
    # Without the ordinal clean-up the superscript "st" misread by OCR hides the validity dates.
    text = (REAL / "ocr" / "dgft_notification_52-2025-26_300dpi.txt").read_text(encoding="utf-8")
    assert ow.parse_mep_terms(text, date(2025, 12, 31)).valid_until is None
    assert ow.parse_mep_terms(text, date(2025, 12, 31), ocr=True).valid_until == date(2026, 3, 31)


def test_effect_section_beats_the_superseded_condition_in_the_table():
    text = ("hereby extends the validity ... as under, with immediate effect: Existing Policy condition Revised Policy "
            "condition Subject to a Minimum Export Price (MEP) of US Dollar 900 FOB per Metric Ton, till 31st May 2030. "
            "Subject to a Minimum Export Price (MEP) of US Dollar 900 FOB per Metric Ton, till 30th November 2030. "
            "2. Effect of this Notification: The MEP of US Dollar 900 FOB per Metric Ton shall remain till "
            "30th November 2030. (Issued from File No. 01/91/180)")
    terms = ow.parse_mep_terms(text, date(2030, 5, 20))
    assert terms.valid_until == date(2030, 11, 30) and terms.validity_dates_found == [date(2030, 5, 31),
                                                                                      date(2030, 11, 30)]
    assert terms.mep_usd_per_t == 900.0 and terms.basis == "FOB" and terms.problems == []


@pytest.mark.parametrize("raw,expected", [
    ("till 31* December, 2024", "till 31 December, 2024"),
    ("till 31‘' December, 2024", "till 31 December, 2024"),
    ("beyond 31s! December, 2024", "beyond 31 December, 2024"),
    ("till 318' December 2025", "till 31 December 2025"),
    ("till 3154 March 2026", "till 31 March 2026"),
    ("till 318tMarch 2026", "till 31 March 2026"),
    ("till 31S*March 2026", "till 31 March 2026"),
    ("till 34St March 2026", "till 34St March 2026"),        # no day 34: left alone, so not read
    ("till 31 December 2026", "till 31 December 2026"),      # not "3" + noise "1"
    ("till 31st December 2026", "till 31st December 2026"),
    ("dated 22.08.2025, the", "dated 22.08.2025, the"),
])
def test_ocr_ordinal_normalisation(raw, expected):
    assert ow.normalise_ocr_ordinals(raw) == expected


def test_two_ocr_readings_must_agree():
    a = ow.MepTerms(mep_usd_per_t=1400.0, valid_until=date(2026, 12, 31), effective_date=date(2026, 4, 10),
                    effective_basis="with immediate effect (notification date)", basis="FOB")
    b = ow.MepTerms(mep_usd_per_t=1490.0, valid_until=date(2026, 12, 31), effective_date=date(2026, 4, 10),
                    effective_basis="with immediate effect (notification date)", basis="FOB")
    m = ow.merge_ocr_terms(a, b)
    assert m.mep_usd_per_t is None and m.valid_until == date(2026, 12, 31) and m.effective_date == date(2026, 4, 10)
    assert m.problems == ["OCR readings disagree on the minimum export price (1400.0 vs 1490.0); not stored"]
    assert ow.merge_ocr_terms(a, a).mep_usd_per_t == 1400.0


# ===========================================================================
# DGFT end to end on the real list and scans
# ===========================================================================

def _dgft_real_routes() -> dict:
    return {
        ow.DGFT_LIST_URL: rx("dgft_notifications.html"),
        DGFT_FILES + r"32d42ad7-3efd-4c36-9ead-1cf5e0691bf2/": (200, rx("dgft_notification_75-2023.pdf"), PDF),
        DGFT_FILES + r"1b7a5f43-e2c8-4eed-a5ff-cbdeccbf8c84/": (200, rx("dgft_notification_09-2026-27.pdf"), PDF),
        DGFT_FILES: (503, b"<html><body>Service Unavailable</body></html>", "text/html"),   # the other three
    }


@pytest.mark.skipif(ocr.available() is None, reason="Tesseract OCR is not installed")
def test_real_dgft_end_to_end_with_ocr(run_with_routes, session_factory, pin_today):
    res = run_with_routes("in_dgft_honey", _dgft_real_routes())
    assert res["status"] == "partial" and res["new"] == 2, res
    assert sum("PDF not available" in w and "retried next run" in w for w in res["warnings"]) == 3, res
    assert not any("number not recognised" in w or "OCR" in w for w in res["warnings"]), res
    with session_factory() as s:
        items = _items(s, "in_dgft_honey")
        assert set(items) == {"DGFT Notification No. 09/2026-27", "DGFT Notification No. 75/2023"}
        cur = items["DGFT Notification No. 09/2026-27"]
        assert (cur.doc_type, cur.published_at, cur.effective_date) == ("price_floor", date(2026, 4, 10),
                                                                         date(2026, 4, 10))
        assert cur.countries == ["IND"] and cur.jurisdiction == "IN" and cur.summary_en is None
        e = cur.extra
        assert (e["mep_usd_per_t"], e["mep_currency"], e["mep_unit"], e["mep_basis"]) == (1400.0, "USD", "t", "FOB")
        assert e["valid_until"] == "2026-12-31" and e["notification_number"] == "09/2026-27"
        assert e["terms_text_source"] == "ocr" and e["ocr_dpi"] == [300, 400] and e["ocr_engine"].startswith("tesseract")
        assert "Minimum Export Price" in e["ocr_excerpt"]
        first = items["DGFT Notification No. 75/2023"]
        assert first.extra["mep_usd_per_t"] == 2000.0 and first.extra["valid_until"] == "2024-12-31"
        assert first.effective_date == date(2024, 3, 14) and "mep_basis" not in first.extra    # no FOB wording


def test_real_dgft_scans_without_ocr_are_stored_without_terms(run_with_routes, session_factory, pin_today,
                                                              monkeypatch):
    monkeypatch.setattr(ow.ocr, "available", lambda: None)
    res = run_with_routes("in_dgft_honey", _dgft_real_routes())
    assert res["status"] == "partial" and res["new"] == 2, res
    assert sum("scanned image without a text layer and OCR is not installed" in w for w in res["warnings"]) == 2
    with session_factory() as s:
        cur = _items(s, "in_dgft_honey")["DGFT Notification No. 09/2026-27"]
        assert cur.extra["terms_parsed"] is False and "mep_usd_per_t" not in cur.extra and cur.effective_date is None


# ===========================================================================
# SENASA: the real Plan CREHA page and Lista EAR
# ===========================================================================

def test_real_creha_ear_links():
    links, pdfs = ow.find_ear_links(rx("senasa_creha.html"), ow.SENASA_CREHA_URL)
    assert pdfs == 12
    got = [(l.reference, l.text, l.url.rsplit("/", 1)[-1]) for l in links]
    assert got == [
        ("SENASA Lista EAR 2026 N°09", "Lista EAR - Especies 09-2026", "ear_09-26_especie.pdf"),
        ("SENASA Lista EAR 2026 N°09", "Lista EAR - Productos 09-2026", "ear_09-26_producto.pdf"),
        # the list of imported products has its own numbering: not "Lista EAR 2026 N°16"
        ("SENASA Lista EAR Impo 2026 N°16", "Lista EAR Impo N° 16 - Importados, vigilancia - Año 2026",
         "lev_impo_n_16-2026.pdf"),
        ("SENASA Lista EAR 2020 N°09", "EAR - Productos - 09/20 (pdf, 394.7 Kb)", "ear_09-20_producto.pdf"),
        ("SENASA Lista EAR 2020 N°09", "EAR - Especie - 09/20 (pdf, 456.0 Kb)", "ear_09-20_especie.pdf"),
    ]
    assert all(l.listed_date is None for l in links)     # "09-2026" is the list number, not a date


def test_real_ear_pdf_header_date_and_honey_rows():
    ear = ow.parse_ear_pdf(rx("ear_09-26_producto_p1.pdf"))
    assert ear.text_ok and ear.list_date == date(2026, 10, 8)        # "... Plan CREHA Animal 08/10/2026"
    assert (ear.title, ear.list_year, ear.list_number) == ("LISTA EAR AÑO 2026 N° 09 - Por Producto", 2026, 9)
    assert ear.honey_rows == [
        "Miel B-17733 OXITETRACICLINA 2023 8", "Miel X-871-1 OXITETRACICLINA 2024 28",
        "Miel S4120-1 OXITETRACICLINA 2024 37", "Miel X4151-5 FENOL 2024 41", "Miel R-008 QUINOLONAS 2025 54",
        "Miel B59912-1 FENOL 2026 3",
    ]


def test_real_ear_2020_header_has_the_date_on_its_own_line(monkeypatch):
    text = (REAL / "ear_09-20_producto_p1_text.txt").read_text(encoding="utf-8")
    monkeypatch.setattr(ow, "pdf_text", lambda content: text)
    ear = ow.parse_ear_pdf(b"%PDF")
    assert ear.list_date == date(2020, 10, 1) and (ear.list_year, ear.list_number) == (2020, 9)


def test_ear_header_date_of_another_year_is_not_used(monkeypatch):
    monkeypatch.setattr(ow, "pdf_text", lambda content: "Plan CREHA Animal 08/10/2019\nLISTA EAR AÑO 2026 N° 09 - "
                                                        "Producto\nMiel X-1 FENOL 2026 3")
    assert ow.parse_ear_pdf(b"%PDF").list_date is None


def test_real_senasa_run_with_boletin_oficial_unreachable(run_with_routes, session_factory, pin_today):
    """The live situation: CREHA and the EAR PDF answer, www.boletinoficial.gob.ar resets the
    connection. The run is partial, the EAR list is stored with the date printed in its header."""
    routes = {
        SENASA_LIST: (Path(__file__).parent / "fixtures" / "official_watchers" / "senasa_noticias.html").read_bytes(),
        ow.SENASA_CREHA_URL: rx("senasa_creha.html"),
        EAR_FILES + "ear_09-26_producto.pdf": (200, rx("ear_09-26_producto_p1.pdf"), PDF),
        "^" + EAR_FILES.replace(".", r"\.") + r".*\.pdf$": (404, b"<html><title>No encontrada</title></html>"),
    }
    res = run_with_routes("ar_senasa_honey", routes)
    assert res["status"] == "partial" and res["error"] is None, res
    assert any(w.startswith("Boletín Oficial (primera sección): host unreachable") for w in res["warnings"]), res
    with session_factory() as s:
        items = _items(s, "ar_senasa_honey")
        ear = items["SENASA Lista EAR 2026 N°09"]
        assert ear.title == "Lista EAR - Productos 09-2026" and ear.published_at == date(2026, 10, 8)
        assert ear.url == EAR_FILES + "ear_09-26_producto.pdf" and ear.doc_type == "residue_alert"
        assert ear.extra["date_source"] == "pdf_header" and ear.extra["honey_row_count"] == 6
        assert ear.extra["pdf_title"] == "LISTA EAR AÑO 2026 N° 09 - Por Producto"
        assert not any(r.startswith("BO-AR") for r in items)
